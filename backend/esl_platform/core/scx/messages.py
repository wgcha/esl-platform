"""SCX 오류 → esl 코드·사용자 문구(계약 esl_scx_relay.md §5.2). 원본 = `resources/scx_messages.json`(백엔드·워커·화면 공용)."""

from __future__ import annotations

import functools
import json
import os
from dataclasses import dataclass
from typing import Any

from .mask import mask_text


def messages_path() -> str:
    from ..config import app_root

    return os.path.join(app_root(), "resources", "scx_messages.json")


@functools.lru_cache(maxsize=1)
def load_messages() -> dict[str, Any]:
    """{relay_codes: {릴레이 code: esl code}, messages: {esl code: {message, retry}}}. 파일이 없으면 최소 기본(코드 = 문구)."""
    try:
        with open(messages_path(), encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and isinstance(d.get("messages"), dict) and isinstance(d.get("relay_codes"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"relay_codes": {}, "messages": {}}


def text(code: str, value: Any = None) -> str:
    """esl 코드 → 사용자 문구({value} 자리 채움). 없는 코드면 코드 그대로."""
    m = (load_messages()["messages"].get(code) or {}).get("message") or code
    return m.replace("{value}", "" if value is None else str(value))


def retry_flag(code: str) -> bool:
    return bool((load_messages()["messages"].get(code) or {}).get("retry"))


@dataclass(frozen=True)
class ScxFailure:
    code: str             # esl code(SCX_*)
    message: str          # 사용자 문구(+ 마스킹한 원문 요지)
    retryable: bool       # 자동 재시도 대상(SR-D-7)
    relay_code: str | None = None
    http_status: int | None = None


def classify(exc: BaseException) -> ScxFailure:
    """HpcGatewayError(어댑터) → ScxFailure. 원문은 mask_text 를 거쳐 덧붙인다(200자)."""
    relay = getattr(exc, "relay_code", None)
    status = getattr(exc, "http_status", None)
    gw_code = getattr(exc, "code", None)
    raw = str(exc)
    codes = load_messages()["relay_codes"]
    if relay and relay in codes:
        code = codes[relay]
    elif getattr(exc, "transport", False):
        code = "SCX_RELAY_UNREACHABLE"
    elif status == 404 and relay is None:
        code = "SCX_RELAY_DISABLED"           # 릴레이 라우트 없음(화면 포트·구버전 대시보드)
    elif gw_code == "NOT_CONFIGURED":
        code = "SCX_CONFIG_INVALID" if raw.startswith("SCX 설정 오류") else "SCX_SECRET_INVALID"
    elif relay:
        code = "SCX_SUBMIT_FAILED"
    else:
        code = "SCX_UNAVAILABLE"
    value = relay if code in ("SCX_SUBMIT_FAILED", "SCX_RADIOSS_FAILED") else None
    base = text(code, value)
    detail = mask_text(raw, 160)
    msg = base if not detail or detail in base else f"{base} — {detail}"
    retry = bool(getattr(exc, "transport", False)) or retry_flag(code)
    return ScxFailure(code, mask_text(msg, 450), retry, relay, status)


__all__ = ["load_messages", "text", "retry_flag", "classify", "ScxFailure", "messages_path"]
