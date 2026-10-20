"""PC 연결 코드·토큰(계약 esl_p3_ux.md §9.1). 코드 발급·목록·폐기는 브라우저 세션(power 이상), 교환은 인증 없이(코드가 증명)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ...core.auth import Principal
from ..deps import get_ctx, get_principal, get_token, request_id
from ..schemas import ClientCodeCreate, ClientCodeOut, ClientExchange, ClientExchangeOut, ClientTokenOut
from ..services import client_tokens as svc

router = APIRouter(tags=["client-tokens"])


@router.post("/client-tokens/codes", response_model=ClientCodeOut, status_code=201)
def create_code(body: ClientCodeCreate, request: Request, principal: Principal = Depends(get_principal)
                ) -> dict[str, Any]:
    """PC 연결 코드(6자리, 15분, 1회용) — 현재 프로젝트에 묶임. power 이상."""
    ctx = get_ctx(request)
    projects = ctx.auth.projects(principal, get_token(request), request_id(request))
    return svc.create_code(ctx, principal, projects, body.project_id)


@router.post("/client-tokens/exchange", response_model=ClientExchangeOut)
def exchange(body: ClientExchange, request: Request) -> dict[str, Any]:
    """PC 도구: 코드 → 토큰 esl_ct_…(응답에서 한 번만 보임). 실패 잠금(출발지별 5회 또는 구분 불가 시 서버 전체 30회 / 15분, 429). 세션·CSRF 헤더 불필요."""
    ctx = get_ctx(request)
    src = svc.request_source(request.client.host if request.client else None, request.headers.get("x-forwarded-for"),
                             ctx.settings.client_token.trusted_proxies)
    return svc.exchange(ctx, src, body.code, body.device_name)


@router.get("/client-tokens", response_model=list[ClientTokenOut])
def list_tokens(request: Request, project_id: str | None = Query(default=None, max_length=64),
                principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    """내 연결된 PC(토큰) 목록(최근 100개, 상태 ACTIVE·EXPIRED·REVOKED)."""
    return svc.list_tokens(get_ctx(request), principal, project_id)


@router.delete("/client-tokens/{token_id}", response_model=ClientTokenOut)
def revoke(token_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """연결된 PC 토큰 폐기(이후 그 토큰 요청은 401). 내 것(전역 관리자는 모두)."""
    return svc.revoke(get_ctx(request), principal, token_id)
