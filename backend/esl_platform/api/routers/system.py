"""health·me·projects·status·queue·paths/inspect."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ... import __version__
from ...core.auth import Principal
from ..deps import get_ctx, get_principal, get_token, request_id
from ..schemas import BrowseOut, ChangelogEntry, Health, InspectReq, Me, Project, QueueOut, StatusOut, VersionOut
from ..services import fsbrowse, system
from ..services import version as version_svc

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


@router.get("/fs/browse", response_model=BrowseOut)
def fs_browse(request: Request, root: int | None = Query(default=None, ge=0),
              path: str = Query(default="", max_length=1024), offset: int = Query(default=0, ge=0),
              limit: int | None = Query(default=None, ge=1), principal: Principal = Depends(get_principal)
              ) -> dict[str, Any]:
    """서버 폴더 찾아보기(읽기 전용): root 없으면 루트 목록만. path 는 루트 기준 상대경로."""
    return fsbrowse.browse(get_ctx(request), root, path, offset, limit, principal)


@router.get("/version", response_model=VersionOut)
def version(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return version_svc.build_info()


@router.get("/changelog", response_model=list[ChangelogEntry])
def changelog(principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return version_svc.changelog()
