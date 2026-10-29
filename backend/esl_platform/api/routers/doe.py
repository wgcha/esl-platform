"""비드 형상 DOE(계약 esl_bead_doe.md §10): 설정, 입력 검사, 연구, 변수 표·평면도, 행렬·미리보기·실행, 결과·파일·3D 비교."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from ...core.auth import Principal
from ..deps import get_ctx, get_principal
from ..html_report import html_report
from ..schemas import (
    DoeCheckIn,
    DoeCheckOut,
    DoeFileOut,
    DoeMatrixIn,
    DoeMatrixOut,
    DoeParamsOut,
    DoePlanOut,
    DoePerEslOut,
    DoeResultOut,
    DoeRunIn,
    DoeSettingsOut,
    DoeStudyIn,
    DoeStudyOut,
    View3dOut,
)
from ..services import doe as svc
from .results import ZIP_RESPONSE, zip_response

router = APIRouter(tags=["doe"])
PNG_RESPONSE = {200: {"content": {"image/png": {}}, "description": "PNG"}}
_PNG_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


@router.get("/doe/settings", response_model=DoeSettingsOut)
def doe_settings(request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """화면 기본값·사용 가능 여부(§6.5 — paicad 는 워커 점검 기록만 읽음)·방법·출처(resources/doe_method_sources.json)."""
    return svc.settings_out(get_ctx(request), principal)


@router.post("/doe/check-inputs", response_model=DoeCheckOut)
def doe_check_inputs(body: DoeCheckIn, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """입력 검사: STEP 머리·크기, ① 같은 모델(다른 모델 ESL 은 entries[].ok=false)·Case 폴더 크기, ② B 메시·크기 규칙,
    ③ 쉘 물성·요소 크기 기본값. 업로드는 읽기만(result.purpose = doe_step|doe_mesh 기록)."""
    return svc.check_inputs(get_ctx(request), principal, body)


@router.post("/doe/studies", response_model=DoeStudyOut, status_code=201)
def doe_study_create(body: DoeStudyIn, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.create_study(get_ctx(request), principal, body)


@router.get("/doe/studies", response_model=list[DoeStudyOut])
def doe_study_list(request: Request, project_id: str | None = Query(default=None, max_length=64),
                   principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_studies(get_ctx(request), principal, project_id)


@router.get("/doe/studies/{sid}", response_model=DoeStudyOut)
def doe_study_get(sid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_study(get_ctx(request), principal, sid)


@router.get("/doe/studies/{sid}/params", response_model=DoeParamsOut)
def doe_params(sid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.params_out(get_ctx(request), principal, sid)


@router.get("/doe/studies/{sid}/plan-view", response_model=DoePlanOut)
def doe_plan_view(sid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.plan_view(get_ctx(request), principal, sid)


@router.get("/doe/studies/{sid}/beads/{bead}.png", response_class=FileResponse, responses=PNG_RESPONSE)
def doe_bead_png(sid: str, bead: str, request: Request, principal: Principal = Depends(get_principal)) -> FileResponse:
    return FileResponse(svc.bead_png(get_ctx(request), principal, sid, bead), media_type="image/png",
                        headers=_PNG_HEADERS)


@router.post("/doe/studies/{sid}/matrix", response_model=DoeMatrixOut)
def doe_matrix(sid: str, body: DoeMatrixIn, request: Request,
               principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """DOE 행렬 생성만(저장 안 함). 미리보기·워커와 같은 함수 → 같은 matrix_sha256."""
    return svc.matrix(get_ctx(request), principal, sid, body)


@router.post("/doe/studies/{sid}/preview", response_model=DoeStudyOut, status_code=202)
def doe_preview(sid: str, body: DoeMatrixIn, request: Request,
                principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.preview(get_ctx(request), principal, sid, body)


@router.get("/doe/studies/{sid}/preview/thumb/{did}", response_class=FileResponse, responses=PNG_RESPONSE)
def doe_thumb(sid: str, did: str, request: Request, principal: Principal = Depends(get_principal)) -> FileResponse:
    return FileResponse(svc.thumb(get_ctx(request), principal, sid, did), media_type="image/png", headers=_PNG_HEADERS)


@router.post("/doe/studies/{sid}/run", response_model=DoeStudyOut, status_code=202)
def doe_run(sid: str, body: DoeRunIn, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """같은 matrix_sha256 의 미리보기가 끝난 뒤에만(409 PREVIEW_STALE). solver = linear 만(422 SOLVER_UNSUPPORTED)."""
    return svc.run(get_ctx(request), principal, sid, body)


@router.post("/doe/studies/{sid}/clone", response_model=DoeStudyOut, status_code=201)
def doe_clone(sid: str, request: Request, body: dict[str, Any] | None = Body(default=None),
              principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """같은 입력으로 새 연구 + DOE_PREP(본문 {title?})."""
    return svc.clone(get_ctx(request), principal, sid, body)


@router.get("/doe/studies/{sid}/results", response_model=DoeResultOut)
def doe_results(sid: str, request: Request, sort: str = Query(default="score", max_length=40),
                principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """순위·민감도·ESL별 개선 지표. sort = score(기본)|worst_ratio|geo_mean_improvement|n_worsened|pareto."""
    return svc.results(get_ctx(request), principal, sid, sort)


@router.get("/doe/studies/{sid}/results/per-esl", response_model=DoePerEslOut)
def doe_results_per_esl(sid: str, request: Request, design: str | None = Query(default=None, max_length=8000),
                        principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """ESL별 C·비율·umax·εmax(순위 행에 per_esl 이 없을 때 — 안 수 × ESL 수 > rank.per_esl_inline_max)."""
    return svc.results_per_esl(get_ctx(request), principal, sid, design)


@router.get("/doe/studies/{sid}/files", response_model=list[DoeFileOut])
def doe_files(sid: str, request: Request, principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_files(get_ctx(request), principal, sid)


@router.get("/doe/studies/{sid}/download", response_class=FileResponse)
def doe_download(sid: str, request: Request, rel: str = Query(min_length=1, max_length=512),
                 principal: Principal = Depends(get_principal)) -> FileResponse:
    path = svc.study_file(get_ctx(request), principal, sid, rel)
    return FileResponse(path, filename=os.path.basename(path), media_type="application/octet-stream")


@router.get("/doe/studies/{sid}/bundle", response_class=StreamingResponse, responses=ZIP_RESPONSE)
def doe_bundle(sid: str, request: Request, parts: str | None = Query(default=None, max_length=100),
               principal: Principal = Depends(get_principal)) -> StreamingResponse:
    """결과 받기(zip): parts = best,report,ranking(기본) [,result·prep, raw = npz·안 폴더]. 상한 초과 시 413."""
    return zip_response(svc.bundle(get_ctx(request), principal, sid, parts))


@router.get("/doe/studies/{sid}/report", response_class=HTMLResponse)
def doe_report(sid: str, request: Request, download: bool = False,
               principal: Principal = Depends(get_principal)) -> Response:
    return html_report(svc.report(get_ctx(request), principal, sid), f"doe_{sid}_report.html", download)


@router.get("/doe/studies/{sid}/view3d/{did}/manifest.json", response_model=View3dOut, response_model_by_alias=True)
def doe_view3d_manifest(sid: str, did: str, request: Request,
                        principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """3D 비교 manifest(기존 view3d 형식, 파일 URL = /doe/studies/{id}/view3d/{did}/…). 베이스라인 + 순위 상위 k."""
    return svc.view3d_manifest(get_ctx(request), principal, sid, did)


@router.get("/doe/studies/{sid}/view3d/{did}/{name}", response_class=FileResponse,
            responses={200: {"content": {"model/gltf-binary": {}, "application/octet-stream": {}},
                             "description": "GLB·values.bin"}})
def doe_view3d_file(sid: str, did: str, name: str, request: Request,
                    principal: Principal = Depends(get_principal)) -> FileResponse:
    path, media = svc.view3d_file(get_ctx(request), principal, sid, did, name)
    return FileResponse(path, media_type=media, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
