"""SCX 릴레이 게이트웨이(계약 esl_scx_relay.md SR-D-1·2·3·18). 백엔드·워커 공용, 프로세스당 1개(지연 생성).

- 어댑터 = physicsai `simdash_adapters`(wheel 동봉 — deploy/simdash_adapters.lock 커밋 고정). 없거나 이름이 빠졌으면
  `SCX_ADAPTER_MISSING`(SCX 기능만 비활성, 다른 기능 그대로).
- `EslScxGateway(ScxHpcGateway)`: `_load_secret` 만 재정의해 `ScxRelayClient(..., client_name=hpc.scx.client_name)` —
  헤더 `X-SCX-Relay-Client: esl`(어댑터 기본 physicsai). 비공개 메서드 의존은 lock 고정 + 시험(V-SR-2)으로 묶는다(R-SR-4).
- loopback 전용(어댑터 parse_relay_url), `http.client` 직접 연결(프록시 환경변수 무시), 리다이렉트 안 따름(어댑터).
- 비밀 값: 어댑터 on_secret → mask.register_secret(로그 필터·mask_text). 값은 repr·예외·응답에 없음.
- 드라이브 쓰기 메서드(upload·ensure_new_dir·submit_radioss·cancel·resolve)는 검증 낙하 워커 모듈(worker/esl_worker/scx_verify.py)
  에서만 부른다(정적 시험 — 백엔드 [잡 ID 연결]·[포기]도 그 모듈 함수 resolve_submission 경유).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from . import mask
from .settings import adapter_mapping, config_problems, resolve_secret_file, scx_cfg

log = logging.getLogger("esl.scx")
# = deploy/simdash_adapters.lock(commit·version) — 코드 스냅샷에는 deploy 폴더가 없어 상수로 둔다(시험이 lock 과 대조)
ADAPTER_COMMIT = "a363a89e8f93d3acfe90a9601318bf4f6cade0a7"
ADAPTER_VERSION = "0.1.0"
NEEDED = ("ScxHpcGateway", "ScxRadiossRequest", "ScxConfig", "ScxRelayClient", "read_secret_file", "validate_scx_config")

_LOCK = threading.Lock()
_ADAPTER: dict[str, Any] | None = None
_GW: dict[str, Any] = {"key": None, "gw": None}


def adapter_status(*, refresh: bool = False) -> dict[str, Any]:
    """{ok, version, commit, reason} — import simdash_adapters.hpc + 필요한 이름. 프로세스에서 한 번(refresh 로 다시)."""
    global _ADAPTER
    with _LOCK:
        if _ADAPTER is not None and not refresh:
            return dict(_ADAPTER)
        out: dict[str, Any] = {"ok": False, "version": None, "commit": ADAPTER_COMMIT[:12], "reason": None}
        try:
            import simdash_adapters
            import simdash_adapters.hpc as hpc

            out["version"] = getattr(simdash_adapters, "__version__", None)
            missing = [n for n in NEEDED if not hasattr(hpc, n)]
            if missing:
                out["reason"] = f"SCX_ADAPTER_MISSING: simdash_adapters.hpc 에 {', '.join(missing)} 없음"
            else:
                out["ok"] = True
        except ImportError as exc:
            out["reason"] = f"SCX_ADAPTER_MISSING: simdash_adapters 를 불러오지 못함({type(exc).__name__})"
        _ADAPTER = out
        return dict(out)


def gateway_error() -> type:
    """어댑터 오류 형(HpcGatewayError) — 어댑터 import 는 이 패키지 안에서만."""
    from simdash_adapters.hpc import HpcGatewayError

    return HpcGatewayError


def _gateway_class():
    from simdash_adapters.hpc import ScxHpcGateway, ScxRelayClient, read_secret_file

    class EslScxGateway(ScxHpcGateway):
        """client_name 만 다른 어댑터 게이트웨이(SR-D-3)."""

        def __init__(self, cfg: Any, secret_path: str | None, *, client_name: str = "esl", **kw: Any) -> None:
            self.client_name = client_name
            super().__init__(cfg, secret_path, **kw)

        def _load_secret(self) -> None:  # 어댑터 비공개 메서드 재정의(a363a89 기준 — lock 고정)
            if self.problems:
                return
            value, problem = read_secret_file(self.secret_path)
            self._secret_problem = problem
            if value is None:
                return
            if self._on_secret is not None:
                self._on_secret(value)
            self._client = ScxRelayClient(self.cfg.relay_url, value, http_timeout_s=self.cfg.http_timeout_s,
                                          transfer_timeout_s=self.cfg.transfer_timeout_s, client_name=self.client_name)

        def secret_problem(self) -> str | None:
            """비밀 파일 문제(값 없음) — 없으면 None."""
            if self.problems:
                return None
            with self._lock:
                if self._client is None:
                    self._load_secret()
                return None if self._client is not None else (self._secret_problem or "비밀 파일 문제")

        def __repr__(self) -> str:
            return f"EslScxGateway(relay={self.cfg.relay_url!r}, client={self.client_name!r}, secret_file={self.secret_path!r})"

    return EslScxGateway


def _key(settings) -> str:
    cfg = scx_cfg(settings)
    return json.dumps(cfg.model_dump() if cfg is not None else None, sort_keys=True, default=str)


def get_gateway(settings) -> tuple[Any | None, str | None, str | None]:
    """(게이트웨이 | None, 사유 코드, 사유 상세). 설정이 같으면 같은 인스턴스(프로세스당 1개 — 설정이 바뀌면 새로)."""
    cfg = scx_cfg(settings)
    if cfg is None:
        return None, "SCX_NOT_CONFIGURED", None
    ad = adapter_status()
    if not ad["ok"]:
        return None, "SCX_ADAPTER_MISSING", ad["reason"]
    probs = config_problems(settings)
    if probs:
        return None, "SCX_CONFIG_INVALID", "; ".join(probs)[:400]
    sec = resolve_secret_file(cfg)
    if sec["path"] is None:
        return None, "SCX_SECRET_INVALID", sec["problem"]
    key = _key(settings) + "|" + sec["path"]
    with _LOCK:
        if _GW["key"] == key and _GW["gw"] is not None:
            return _GW["gw"], None, None
        from simdash_adapters.hpc import ScxConfig

        mask.install_log_filter()
        gw = _gateway_class()(ScxConfig.from_mapping(adapter_mapping(cfg)), sec["path"], client_name=cfg.client_name,
                              logger=logging.getLogger("esl.scx.adapter"), on_secret=mask.register_secret)
        _GW.update(key=key, gw=gw)
        return gw, None, None


def radioss_request(body: dict[str, Any]) -> Any:
    """`POST /jobs/radioss` 본문(dict — ScxRadiossRequest.to_json 형식) → 어댑터 ScxRadiossRequest(v0.12.0 기능 B).
    어댑터 import 는 이 패키지 안에서만(정적 시험)."""
    from simdash_adapters.hpc import ScxRadiossRequest

    return ScxRadiossRequest.from_json(body)


def status_map() -> dict[str, tuple[str, str | None]]:
    """어댑터 SCX_STATUS_MAP(SCX 원문 상태 → (HpcState, outcome))."""
    from simdash_adapters.hpc.scx import SCX_STATUS_MAP

    return dict(SCX_STATUS_MAP)


def reset() -> None:
    """시험: 프로세스 상태 비우기(게이트웨이·어댑터 확인 캐시)."""
    global _ADAPTER
    with _LOCK:
        _GW.update(key=None, gw=None)
        _ADAPTER = None
    from . import status

    status.reset_cache()


__all__ = ["adapter_status", "get_gateway", "gateway_error", "radioss_request", "status_map", "reset", "ADAPTER_COMMIT",
           "ADAPTER_VERSION"]
