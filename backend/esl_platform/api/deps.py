"""FastAPI 의존성: 인증(401) → CSRF 헤더(403 `CSRF_HEADER_REQUIRED`) → 문맥."""

from __future__ import annotations

import uuid

from fastapi import Request

from ..core.auth import Principal
from ..core.errors import DomainError
from .context import AppContext

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-ESL-Request"


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


def get_principal(request: Request) -> Principal:
    ctx = get_ctx(request)
    token = extract_token(request, ctx.settings.auth.cookie_name)
    principal = ctx.auth.authenticate(token, request_id(request))
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise DomainError("CSRF_HEADER_REQUIRED", f"요청 헤더 {CSRF_HEADER}: 1 이 필요합니다", status=403)
    request.state.principal = principal
    return principal


def get_token(request: Request) -> str | None:
    return extract_token(request, get_ctx(request).settings.auth.cookie_name)
