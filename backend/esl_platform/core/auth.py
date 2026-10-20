"""대시보드 세션 introspection 인증(계약 esl.md §5, PAI §5 패턴).

- 신원은 대시보드 `introspection_path`(Bearer = 세션 쿠키 값)로 확정. 결과는 TTL 캐시(키 = 토큰 sha256).
- 토큰 원문은 로그·DB·응답에 남기지 않는다. 실패 응답은 캐시하지 않는다.
- HTTP 전송은 httpx transport 주입형(시험은 가짜 대시보드 MockTransport).
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import AuthCfg
from .errors import DomainError

logger = logging.getLogger("esl_platform.auth")

ROLES = ("general", "power", "admin")
CACHE_MAX = 1000


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    display_name: str
    is_global_admin: bool
    roles: dict[str, str] = field(default_factory=dict)

    def role(self, project_id: str) -> str | None:
        if self.is_global_admin:
            return "admin"
        return self.roles.get(project_id)

    def can_execute(self, project_id: str) -> bool:
        return self.role(project_id) in ("power", "admin")


def auth_required() -> DomainError:
    return DomainError("AUTHENTICATION_REQUIRED", "대시보드에서 로그인하세요", status=401)


def is_loopback_url(url: str) -> bool:
    """URL 호스트가 루프백(127.0.0.0/8·::1·localhost)인지."""
    host = (urlsplit(url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _dashboard_detail(r: "httpx.Response") -> tuple[str, str]:
    """대시보드 오류 응답 {"detail":{"code","message"}}에서 (code, message). 형식이 다르면 빈 값."""
    try:
        d = r.json().get("detail")
    except Exception:  # noqa: BLE001 — 진단용, 형식이 달라도 원래 오류를 낸다
        return "", ""
    if isinstance(d, dict):
        return str(d.get("code") or "")[:80], str(d.get("message") or "")[:200]
    return "", str(d or "")[:200]


def _unreachable(msg: str = "대시보드에 연결할 수 없습니다") -> DomainError:
    return DomainError("DASHBOARD_UNREACHABLE", msg, status=503)


class DashboardClient:
    def __init__(self, cfg: AuthCfg, transport: httpx.BaseTransport | None = None) -> None:
        self.cfg = cfg
        # 루프백 대시보드는 HTTP(S)_PROXY·ALL_PROXY를 무시한다 — 회사 PC에서 127.0.0.1 호출이 프록시로 나가
        # 프록시가 403을 돌려주던 문제(#11, physicsai GitHub #1과 같은 처리). 루프백이 아니면 환경 프록시 존중.
        self._client = httpx.Client(base_url=cfg.dashboard_internal_url.rstrip("/"), timeout=cfg.timeout_s,
                                    transport=transport, follow_redirects=False,
                                    trust_env=not is_loopback_url(cfg.dashboard_internal_url))

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, token: str, request_id: str) -> httpx.Response:
        try:
            return self._client.get(path, headers={"Authorization": f"Bearer {token}", "X-Request-Id": request_id})
        except httpx.HTTPError:
            raise _unreachable() from None

    def _json(self, r: httpx.Response) -> Any:
        try:
            return r.json()
        except ValueError:
            raise _unreachable("대시보드 응답 형식 오류") from None

    def me(self, token: str, request_id: str) -> dict[str, Any]:
        r = self._get(self.cfg.introspection_path, token, request_id)
        if r.status_code == 401:
            raise auth_required()
        if r.status_code == 403:
            # 대시보드가 거부한 이유(AUTH_ACCOUNT_SUSPENDED 등)를 그대로 보여 준다(#11 진단).
            code, msg = _dashboard_detail(r)
            logger.warning("대시보드 /auth/me 403 (%s %s, %s)", code, msg, self.cfg.dashboard_internal_url)
            reason = f" — 대시보드 응답: {code} {msg}".rstrip() if code or msg else ""
            raise DomainError("ACCOUNT_NOT_ACTIVE", f"대시보드 계정이 활성 상태가 아닙니다{reason}", status=403)
        if r.status_code == 503:
            raise DomainError("DASHBOARD_AUTH_UNAVAILABLE", "대시보드 인증 설정이 완료되지 않았습니다", status=503)
        if r.status_code != 200:
            raise _unreachable(f"대시보드 응답 오류({r.status_code})")
        data = self._json(r)
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise _unreachable("대시보드 응답 형식 오류")
        return data

    def projects(self, token: str, request_id: str) -> list[dict[str, Any]]:
        r = self._get(self.cfg.projects_path, token, request_id)
        if r.status_code == 401:
            raise auth_required()
        if r.status_code != 200:
            raise _unreachable(f"대시보드 프로젝트 목록 오류({r.status_code})")
        data = self._json(r)
        if not isinstance(data, list):
            raise _unreachable("대시보드 응답 형식 오류")
        return [{"id": str(p["id"]), "name": str(p.get("name") or ""), "product_name": p.get("product_name")}
                for p in data if isinstance(p, dict) and p.get("id") is not None]


def principal_from_me(data: dict[str, Any]) -> Principal:
    roles: dict[str, str] = {}
    for m in data.get("memberships") or []:
        if isinstance(m, dict) and m.get("role") in ROLES and m.get("project_id") is not None:
            roles[str(m["project_id"])] = m["role"]
    uid = str(data["id"])
    return Principal(uid, str(data.get("username") or uid), str(data.get("display_name") or data.get("username")
                     or uid), bool(data.get("is_global_admin")), roles)


class _TTLCache:
    def __init__(self, ttl: float, clock: Callable[[], float], maxsize: int = CACHE_MAX) -> None:
        self.ttl, self.clock, self.maxsize = ttl, clock, maxsize
        self._d: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            hit = self._d.get(key)
            if hit is None:
                return None
            if hit[0] <= self.clock():
                self._d.pop(key, None)
                return None
            self._d.move_to_end(key)
            return hit[1]

    def put(self, key: str, value: Any) -> None:
        if self.ttl <= 0:
            return
        with self._lock:
            self._d[key] = (self.clock() + self.ttl, value)
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)

    def keys(self) -> list[str]:
        return list(self._d.keys())


def token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Authenticator:
    def __init__(self, cfg: AuthCfg, client: DashboardClient | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self.mode = cfg.mode
        self.client = client
        self.me_cache = _TTLCache(cfg.cache_ttl_s, clock)
        self.projects_cache = _TTLCache(cfg.cache_ttl_s, clock)

    def dev_principal(self) -> Principal:
        p = self.cfg.dev_static_principal
        assert p is not None
        return Principal(p.user_id, p.username, p.display_name, p.is_global_admin,
                         {m.project_id: m.role for m in p.memberships})

    def authenticate(self, token: str | None, request_id: str) -> Principal:
        if self.mode == "dev_static":
            return self.dev_principal()
        if not token:
            raise auth_required()
        key = token_key(token)
        cached = self.me_cache.get(key)
        if cached is not None:
            return cached
        assert self.client is not None
        data = self.client.me(token, request_id)
        if data.get("account_status") != "ACTIVE":
            raise DomainError("ACCOUNT_NOT_ACTIVE", "대시보드 계정이 활성 상태가 아닙니다(승인 대기 등)", status=403)
        principal = principal_from_me(data)
        self.me_cache.put(key, principal)
        return principal

    def projects(self, principal: Principal, token: str | None, request_id: str) -> list[dict[str, Any]]:
        if self.mode == "dev_static":
            ids = sorted({*principal.roles.keys(), "dev"})
            return [{"id": i, "name": f"개발 프로젝트 {i}", "product_name": None} for i in ids]
        key = token_key(token or "") + ":" + principal.user_id
        cached = self.projects_cache.get(key)
        if cached is not None:
            return cached
        assert self.client is not None and token
        data = self.client.projects(token, request_id)
        self.projects_cache.put(key, data)
        return data
