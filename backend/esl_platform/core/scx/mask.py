"""SCX 릴레이 문구 마스킹(계약 esl_scx_relay.md §5.2·SR-D-18).

- 비밀 값(릴레이 공유 비밀)은 프로세스 메모리에만 — 어댑터 `on_secret` 콜백으로 `register_secret` 에 등록하고, 로그 처리기 필터
  (`install_log_filter`)와 `mask_text` 가 `***` 로 바꾼다. 값은 응답·작업 로그·failure_message·설정 응답에 쓰지 않는다.
- `mask_text`: 비밀 값·`Bearer …`·JWT 형태·`X-SCX-Relay-Key: …` → `***`, 서버 절대경로 → `‹…›/<이름>`, 길이 상한(기본 200자).
"""

from __future__ import annotations

import logging
import re
import threading

_LOCK = threading.Lock()
_SECRETS: set[str] = set()
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]+=*")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*")
_RELAY_KEY = re.compile(r"(?i)(x-scx-relay-key\s*[:=]\s*)\S+")
_WIN_ABS = re.compile(r"(?<![\w])[A-Za-z]:(?:\\\\|\\|/)[^\s\"',;\]\)]*")
_POSIX_ABS = re.compile(r"(?<![\w.:/~\-›])/(?:[^\s/\"',;\]\)]+/)+[^\s\"',;\]\)]*")
MAX_LEN = 200


def register_secret(value: str) -> None:
    """어댑터 on_secret 콜백: 비밀 값을 마스킹 목록에 넣는다(값은 어디에도 기록하지 않음)."""
    if isinstance(value, str) and len(value) >= 8:
        with _LOCK:
            _SECRETS.add(value)


def _secrets() -> list[str]:
    with _LOCK:
        return sorted(_SECRETS, key=len, reverse=True)


def mask_secrets(text: str) -> str:
    for s in _secrets():
        if s in text:
            text = text.replace(s, "***")
    text = _RELAY_KEY.sub(lambda m: m.group(1) + "***", text)
    text = _BEARER.sub("Bearer ***", text)
    return _JWT.sub("***", text)


def _tail(m: re.Match) -> str:
    v = m.group(0)
    name = re.split(r"[\\/]+", v.rstrip("\\/"))[-1] if v.rstrip("\\/") else ""
    return f"‹…›/{name}" if name else "‹…›"


def mask_paths(text: str) -> str:
    """서버 절대경로(Windows·POSIX) → ‹…›/<마지막 구간>."""
    return _POSIX_ABS.sub(_tail, _WIN_ABS.sub(_tail, text))


def mask_text(text: object, limit: int | None = MAX_LEN, *, paths: bool = True) -> str:
    """사용자·DB 로 나가는 원문(릴레이 message·JobInfo.error_message 등) 정리."""
    s = "" if text is None else str(text)
    s = mask_secrets(s)
    if paths:
        s = mask_paths(s)
    if limit is not None and len(s) > limit:
        s = s[: max(0, limit - 1)] + "…"
    return s


class SecretFilter(logging.Filter):
    """로그 처리기 필터: 기록 문구의 비밀 값 → ***(경로는 바꾸지 않음 — 서버 로그는 관리자용)."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if not _SECRETS:
            return True
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - 형식 오류 기록은 그대로
            return True
        masked = mask_secrets(msg)
        if masked != msg:
            record.msg, record.args = masked, None
        return True


_FILTER = SecretFilter()


def install_log_filter(logger: logging.Logger | None = None) -> None:
    """루트(또는 주어진) 로거의 모든 처리기에 비밀 필터를 붙인다(이미 있으면 그대로). 게이트웨이 생성 때마다 부른다."""
    lg = logger or logging.getLogger()
    for h in list(lg.handlers):
        if _FILTER not in h.filters:
            h.addFilter(_FILTER)


__all__ = ["register_secret", "mask_text", "mask_secrets", "mask_paths", "install_log_filter", "SecretFilter", "MAX_LEN"]
