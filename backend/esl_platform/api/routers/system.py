"""health·me·projects·status·queue·paths/inspect."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ... import __version__
from ...core.auth import Principal
from ..deps import get_ctx, get_principal, get_token, request_id
from ..schemas import Health, InspectReq, Me, Project, QueueOut, StatusOut
from ..services import system

router = APIRouter(tags=["system"])


@router.get("/health", response_model=Health)
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


@router.get("/me", response_model=Me)
def me(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return {"user_id": principal.user_id, "username": principal.username, "display_name": principal.display_name,
            "is_global_admin": principal.is_global_admin, "roles": dict(principal.roles)}


@router.get("/projects", response_model=list[Project])
def projects(request: Request, principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    ctx = get_ctx(request)
    return ctx.auth.projects(principal, get_token(request), request_id(request))


@router.get("/status", response_model=StatusOut)
def status(request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return system.status(get_ctx(request))


@router.get("/queue", response_model=QueueOut)
def queue(request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return system.queue(get_ctx(request))


@router.post("/paths/inspect")
def inspect(body: InspectReq, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return system.inspect(get_ctx(request), principal, body.purpose, body.path)
