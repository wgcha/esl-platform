"""원자적 교체 공통 함수(이슈 #53 WinError 32).

``atomic_replace(src, dst)`` = ``os.replace`` + Windows 잠금 재시도. Windows 에서 백신(실시간 검사)·검색 인덱서·
탐색기 미리보기가 방금 쓴 파일(임시 파일 또는 대상)을 잠깐 열고 있으면 MoveFileEx 가 PermissionError
(WinError 32 공유 위반 / 5 액세스 거부)로 실패한다. 이 오류만 지수 백오프로 다시 시도하고, 시도 횟수(``attempts``)나
총 대기(``max_wait_s``)를 다 쓰면 ``FileLocked``(EslError ``FILE_LOCKED``, 사용자 문구 + 두 경로)를 던진다.
그 밖의 오류·POSIX 의 PermissionError 는 그대로 다시 던진다(실패한 os.replace 는 src 를 그대로 둔다 — 재시도 안전).

설정: 워커·백엔드가 ``worker.fs_retry {attempts, max_wait_s}`` 로 ``configure`` 한다(코어 자식 프로세스는 spec 으로 받음).
기본값 = ``DEFAULTS``(백엔드 설정 모델 기본과 같음 — 시험이 확인).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

from .errors import EslError

DEFAULTS: dict[str, Any] = {"attempts": 8, "max_wait_s": 10.0, "base_s": 0.05}
LOCK_WINERRORS = (5, 32)          # ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION

_cfg: dict[str, Any] = dict(DEFAULTS)
_lock = threading.Lock()


def user_path(path: str, root: str | None = None) -> str:
    """사용자에게 보일 경로: root(예: esl_root) 안이면 root 기준 상대 경로('/' 구분), 아니면 파일 이름만(서버 절대 경로 숨김)."""
    p = os.path.abspath(str(path))
    if root:
        r = os.path.abspath(str(root))
        try:
            if os.path.commonpath([p, r]) == r and p != r:
                return os.path.relpath(p, r).replace(os.sep, "/")
        except ValueError:                                  # Windows 다른 드라이브
            pass
    return os.path.basename(p)


class FileLocked(EslError):
    """사용자 문구(message)에는 파일 이름만 — 서버 절대 경로는 src·dst 속성(서버 로그 전용, ``log_text``)."""

    def __init__(self, src: str, dst: str, attempts: int, waited_s: float, cause: BaseException | None = None):
        self.src, self.dst = str(src), str(dst)
        why = ""
        if cause is not None:                               # str(PermissionError) 에는 절대 경로가 들어 있어 쓰지 않음
            we = getattr(cause, "winerror", None)
            why = f" [{'WinError ' + str(we) if we is not None else type(cause).__name__}" \
                  f"{': ' + str(cause.strerror) if getattr(cause, 'strerror', None) else ''}]"
        super().__init__(
            "FILE_LOCKED",
            f"다른 프로그램(백신·검색 인덱서·탐색기 미리보기 등)이 파일을 쓰고 있어 바꾸지 못했습니다 "
            f"({attempts}회, {waited_s:.1f} s 대기): {os.path.basename(self.dst)} ← {os.path.basename(self.src)}" + why)

    def log_text(self) -> str:
        """서버 로그용(절대 경로 포함)."""
        return f"{self.message} — 대상 {self.dst}, 임시 {self.src}"


def configure(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """프로세스 전역 재시도 설정(None·빈 값 키는 DEFAULTS). 적용된 설정 사본을 돌려준다."""
    global _cfg
    new = dict(DEFAULTS)
    for k, v in (cfg or {}).items():
        if k in DEFAULTS and v is not None:
            new[k] = type(DEFAULTS[k])(v)
    with _lock:
        _cfg = new
    return dict(new)


def settings() -> dict[str, Any]:
    return dict(_cfg)


def is_lock_error(exc: BaseException) -> bool:
    """Windows 파일 잠금(PermissionError + winerror 5/32)인지."""
    return isinstance(exc, PermissionError) and getattr(exc, "winerror", None) in LOCK_WINERRORS


def atomic_replace(src: str, dst: str, *, attempts: int | None = None, max_wait_s: float | None = None,
                   _replace: Callable[[str, str], None] | None = None,
                   _sleep: Callable[[float], None] | None = None) -> None:
    """os.replace(src, dst) — Windows 잠금(WinError 5/32)은 지수 백오프 재시도, 끝내 실패하면 FileLocked."""
    cfg = _cfg
    n = max(1, int(attempts if attempts is not None else cfg["attempts"]))
    cap = max(0.0, float(max_wait_s if max_wait_s is not None else cfg["max_wait_s"]))
    base = max(0.001, float(cfg["base_s"]))
    rep = _replace or os.replace
    sleep = _sleep or time.sleep
    waited = 0.0
    for i in range(n):
        try:
            rep(src, dst)
            return
        except PermissionError as exc:
            if not is_lock_error(exc):
                raise
            last = exc
        if i == n - 1 or waited >= cap:
            break
        d = min(base * (2 ** i), cap - waited)
        if d > 0:
            sleep(d)
            waited += d
    raise FileLocked(src, dst, i + 1, waited, last) from last
