"""ESL 실행·하중표·검증·산출물."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from ...core.auth import Principal
from ..deps import get_ctx, get_principal
from ..html_report import html_report
from ..schemas import ArtifactOut, EslRunOut, FieldOut, ForcesOut, SectionOut, ValidationOut
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


@router.get("/validations/{vid}/field", response_model=FieldOut)
def validation_field(vid: str, request: Request, layer: Literal["rad", "esl", "err"] = "rad",
                     max_points: int | None = Query(default=None, ge=10),
                     principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """전 요소 비교 2D 점(요소 중심 PCA 평면 좌표 + 값), 2D 셀 격자 다운샘플(≤ ui.max_preview_points)."""
    return svc.field(get_ctx(request), vid, layer, max_points)


@router.get("/validations/{vid}/section", response_model=SectionOut)
def validation_section(vid: str, request: Request, axis: Literal["xi", "eta"] = "xi",
                       at: float = Query(default=0.5, ge=0.0, le=1.0),
                       principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """단면선: 정규화 좌표 axis = at 고정 띠의 요소를 다른 축 방향으로 bin 평균(면외 변위 Radioss·ESL, 초기 면외 좌표)."""
    return svc.section(get_ctx(request), vid, axis, at)


@router.get("/cases/{case_id}/report", response_class=HTMLResponse)
def case_report(case_id: str, request: Request, download: bool = False,
                principal: Principal = Depends(get_principal)) -> Response:
    path, name = svc.case_report(get_ctx(request), case_id)
    return html_report(path, name, download)
