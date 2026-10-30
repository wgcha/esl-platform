"""SCX 기능 사용 가능 판정 1곳(계약 esl_scx_relay.md SR-D-19) — `GET /scx/status`·browse·fetch·워커 시작 공용.

원인 순서: 설정 꺼짐(SCX_FETCH_DISABLED·VD_DISABLED) → hpc.scx 없음(SCX_NOT_CONFIGURED) → 어댑터 없음(SCX_ADAPTER_MISSING)
→ 설정 오류(SCX_CONFIG_INVALID) → 비밀 문제(SCX_SECRET_INVALID) → 릴레이 연결 실패·거부(SCX_RELAY_UNREACHABLE·UNAUTHORIZED·
FORBIDDEN·DISABLED) → 대시보드 SCX 모드 아님(SCX_DRIVE_MODE_OFF) → (A) 프로젝트 루트 0개(SCX_NO_ROOTS)
/ (B) writes_active false·job_api false·appliance 미설정·drive_base 가 relay_base 밖. 다 통과하면 사용 가능(v0.12.0 — 이전
버전의 VD_NOT_AVAILABLE 해제).
헬스는 게이트웨이별 TTL 캐시(hpc.scx.health_ttl_s), 한 번 호출 시간 한도 3 s(어댑터 HEALTH_TIMEOUT_S).
"""

from __future__ import annotations

import datetime as _dt
import threading
import time
from typing import Any

from ..errors import DomainError
from . import messages
from .gateway import ADAPTER_COMMIT, adapter_status, get_gateway
from .settings import appliance_set, scx_cfg

HEALTH_TIMEOUT_S = 3.0
_LOCK = threading.Lock()
_CACHE: dict[int, tuple[float, dict[str, Any] | None, messages.ScxFailure | None, str]] = {}


def reset_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def health(gw, ttl_s: float, *, force: bool = False) -> tuple[dict[str, Any] | None, messages.ScxFailure | None, str]:
    """(health dict | None, 실패 | None, checked_at ISO). TTL 안이면 캐시."""
    from simdash_adapters.hpc import HpcGatewayError

    now = time.monotonic()
    with _LOCK:
        c = _CACHE.get(id(gw))
    if c is not None and not force and ttl_s > 0 and now - c[0] < ttl_s:
        return c[1], c[2], c[3]
    try:
        h = gw.client().call("GET", "/health", timeout=HEALTH_TIMEOUT_S)
        rec = (now, h if isinstance(h, dict) else {}, None, _now_iso())
    except HpcGatewayError as exc:
        rec = (now, None, messages.classify(exc), _now_iso())
    with _LOCK:
        _CACHE[id(gw)] = rec
    return rec[1], rec[2], rec[3]


def allowed_roots(settings, project_id: str | None) -> list[Any]:
    """프로젝트에 허용된 scx_drive.roots(projects [] = 모든 프로젝트)."""
    return [r for r in settings.scx_drive.roots if not r.projects or (project_id and project_id in r.projects)]


def _avail(code: str | None, reason: str | None = None) -> dict[str, Any]:
    return {"enabled": code is None, "reason_code": code, "reason": None if code is None else (reason or messages.text(code))}


def drive_base_shared(cfg) -> bool:
    """hpc.scx.drive_base 가 공용 계정 홈 자체("~", "~/")인가 — 검증 낙하 제출은 계정 전용 폴더("~/<폴더>")만."""
    v = str(getattr(cfg, "drive_base", "") or "").strip()
    return v.rstrip("/") == "~"


def _base_inside(drive_base: str, relay_base: str) -> bool:
    from simdash_adapters.hpc.scx_naming import drive_base_rel

    try:
        b = drive_base_rel(drive_base)
    except ValueError:
        return False
    rb = (relay_base or "").strip("/")
    if not rb:
        return True
    fb, fr = b.casefold().split("/"), rb.casefold().split("/")
    return fb[: len(fr)] == fr and len(fb) >= len(fr)


def evaluate(settings, project_id: str | None, *, need_fetch: bool = True, need_verify: bool = True,
             force: bool = False) -> dict[str, Any]:
    """`ScxStatusOut` 본문 + 내부 키 `_gw`·`_health`(호출자가 지운다)."""
    roots = allowed_roots(settings, project_id)
    relay: dict[str, Any] = {"reachable": False, "drive_state": None, "queue_paused": False, "writes_active": False,
                             "job_api": False, "max_download_bytes": None, "checked_at": None}
    ad = adapter_status()
    out: dict[str, Any] = {"roots": [{"key": r.key, "label": r.label} for r in roots], "relay": relay,
                           "adapters": {"version": ad.get("version"), "commit": ADAPTER_COMMIT[:12]}, "_gw": None,
                           "_health": None}
    fetch_off = None if settings.scx_drive.enabled else "SCX_FETCH_DISABLED"
    verify_off = None if settings.verify_drop.enabled else "VD_DISABLED"
    want_fetch, want_verify = need_fetch and fetch_off is None, need_verify and verify_off is None
    common: tuple[str, str | None] | None = None
    if want_fetch or want_verify:
        gw, code, _detail = get_gateway(settings)
        if code is not None:
            common = (code, None)
        else:
            out["_gw"] = gw
            if gw.secret_problem():
                common = ("SCX_SECRET_INVALID", None)
            else:
                h, fail, checked = health(gw, float(scx_cfg(settings).health_ttl_s), force=force)
                relay["checked_at"] = checked
                if fail is not None:
                    common = (fail.code, fail.message)
                else:
                    out["_health"] = h
                    d = h.get("drive")
                    relay.update(reachable=True, queue_paused=bool(h.get("queue_paused")),
                                 writes_active=bool(h.get("writes_active")), job_api=bool(h.get("job_api")),
                                 drive_state=(d.get("state") if isinstance(d, dict) else d if isinstance(d, str) else None),
                                 max_download_bytes=h.get("max_download_bytes") if isinstance(h.get("max_download_bytes"), int)
                                 else None)
                    if h.get("drive_mode") not in (None, "scx"):
                        common = ("SCX_DRIVE_MODE_OFF", None)
    # A
    if fetch_off:
        out["fetch"] = _avail(fetch_off)
    elif common:
        out["fetch"] = _avail(*common)
    elif not roots:
        out["fetch"] = _avail("SCX_NO_ROOTS")
    else:
        out["fetch"] = _avail(None)
    # B(v0.12.0 구현 — 조건을 모두 통과하면 사용 가능)
    cfg = scx_cfg(settings)
    h = out["_health"] or {}
    if verify_off:
        out["verify"] = _avail(verify_off)
    elif common:
        out["verify"] = _avail(*common)
    elif drive_base_shared(cfg):
        out["verify"] = _avail("VD_DRIVE_BASE_SHARED")   # v0.12.0: 공유 홈("~") 에 PBS 제출 폴더를 만들지 않음
    elif not relay["writes_active"]:
        out["verify"] = _avail("SCX_WRITES_OFF")
    elif not relay["job_api"]:
        out["verify"] = _avail("SCX_JOB_API_OFF")
    elif not appliance_set(cfg):
        out["verify"] = _avail("SCX_APPLIANCE_MISSING")
    elif not _base_inside(cfg.drive_base, str(h.get("relay_base") or "")):
        out["verify"] = _avail("SCX_BASE_OUTSIDE_RELAY")
    else:
        out["verify"] = _avail(None)
    return out


def public(st: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in st.items() if not k.startswith("_")}


def require_fetch(settings, project_id: str, *, force: bool = False) -> tuple[Any, dict[str, Any]]:
    """기능 A 를 지금 쓸 수 있으면 (게이트웨이, health), 아니면 503 SCX_UNAVAILABLE{reason_code}."""
    st = evaluate(settings, project_id, need_verify=False, force=force)
    f = st["fetch"]
    if not f["enabled"]:
        raise DomainError("SCX_UNAVAILABLE", f["reason"] or messages.text(f["reason_code"]), status=503,
                          reason_code=f["reason_code"])
    return st["_gw"], st["_health"] or {}


def require_verify(settings, project_id: str, *, force: bool = False) -> tuple[Any, dict[str, Any]]:
    """기능 B 를 지금 쓸 수 있으면 (게이트웨이, health), 아니면 503 SCX_UNAVAILABLE{reason_code}."""
    st = evaluate(settings, project_id, need_fetch=False, force=force)
    v = st["verify"]
    if not v["enabled"]:
        raise DomainError("SCX_UNAVAILABLE", v["reason"] or messages.text(v["reason_code"]), status=503,
                          reason_code=v["reason_code"])
    return st["_gw"], st["_health"] or {}


__all__ = ["evaluate", "public", "require_fetch", "require_verify", "allowed_roots", "health", "reset_cache", "HEALTH_TIMEOUT_S"]
