"""ESL 실행·하중표·검증·산출물."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from ...core.auth import Principal
from ..deps import get_ctx, get_principal
from ..schemas import ArtifactOut, EslRunOut, ForcesOut, ValidationOut
from ..services import results as svc

router = APIRouter(tags=["results"])


@router.get("/esl-runs/{run_id}", response_model=EslRunOut)
def get_run(run_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_esl_run(get_ctx(request), run_id)


@router.get("/esl-runs/{run_id}/forces", response_model=ForcesOut)
def forces(run_id: str, request: Request, top: int = Query(default=50, ge=1, le=1000),
           principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.forces(get_ctx(request), run_id, top)


@router.get("/validations/{vid}", response_model=ValidationOut)
def get_validation(vid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_validation(get_ctx(request), vid)


@router.get("/cases/{case_id}/validations", response_model=list[ValidationOut])
def list_validations(case_id: str, request: Request, principal: Principal = Depends(get_principal)
                     ) -> list[dict[str, Any]]:
    return svc.list_validations(get_ctx(request), case_id)


@router.get("/cases/{case_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(case_id: str, request: Request, principal: Principal = Depends(get_principal)
                   ) -> list[dict[str, Any]]:
    return svc.list_artifacts(get_ctx(request), case_id)


@router.get("/artifacts/{aid}/download", response_class=FileResponse)
def download(aid: str, request: Request, principal: Principal = Depends(get_principal)) -> FileResponse:
    path, name = svc.artifact_file(get_ctx(request), aid)
    return FileResponse(path, filename=name, media_type="application/octet-stream")
