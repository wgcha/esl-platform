"""FastAPI 의존성: 인증(401) → CSRF 헤더(403 `CSRF_HEADER_REQUIRED`) → 문맥.

P3-UX §9.1: `Authorization: Bearer esl_ct_...`(PC 연결 토큰)은 대시보드 세션 대신 토큰 표(해시)로 인증한다 — 범위 밖 경로는
403 `CLIENT_TOKEN_SCOPE`, CSRF 헤더 면제(브라우저가 자동으로 붙이지 않는 헤더라 CSRF 대상이 아님).
"""

from __future__ import annotations

import uuid

from fastapi import Request

from ..core.auth import Principal
from ..core.errors import DomainError
from .context import AppContext

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-ESL-Request"
CLIENT_TOKEN_PREFIX = "esl_ct_"


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if not rid:
        rid = (request.headers.get("x-request-id") or str(uuid.uuid4()))[:64]
        request.state.request_id = rid
    return rid


def extract_token(request: Request, cookie_name: str) -> str | None:
    tok = request.cookies.get(cookie_name)
    if tok:
        return tok
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def client_bearer(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    value = value.strip()
    if scheme.lower() == "bearer" and value.startswith(CLIENT_TOKEN_PREFIX):
        return value
    return None


def get_principal(request: Request) -> Principal:
    ctx = get_ctx(request)
    ct = client_bearer(request)
    if ct is not None:
        from .services import client_tokens

        principal = client_tokens.authenticate(ctx, ct)
        client_tokens.check_scope(ctx, request.method, request.url.path)
        request.state.principal = principal
        return principal
    token = extract_token(request, ctx.settings.auth.cookie_name)
    principal = ctx.auth.authenticate(token, request_id(request))
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise DomainError("CSRF_HEADER_REQUIRED", f"요청 헤더 {CSRF_HEADER}: 1 이 필요합니다", status=403)
    request.state.principal = principal
    return principal


def get_token(request: Request) -> str | None:
    return extract_token(request, get_ctx(request).settings.auth.cookie_name)
