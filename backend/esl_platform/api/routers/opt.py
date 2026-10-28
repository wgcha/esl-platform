"""비드 최적화(계약 esl_opt_run.md §5): 설정, 템플릿, S1 확인, 평면도, 금지 영역 세트, 실행·파일."""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from ...core.auth import Principal
from ..deps import get_ctx, get_principal
from ..html_report import html_report
from ..schemas import (
    KeepoutSetIn,
    KeepoutSetOut,
    MeshCheckOut,
    OptFileOut,
    OptRunIn,
    OptRunOut,
    OptSettingsOut,
    PlanViewOut,
    S1CheckIn,
    S1CheckOut,
    TemplateCheckIn,
    TemplateDeleteOut,
    TemplateIn,
    TemplateOut,
)
from ..services import opt as svc
from ..services import opt_keepouts as ko_svc
from ..services import opt_templates as tpl_svc
from .results import ZIP_RESPONSE, zip_response

router = APIRouter(tags=["opt"])


@router.get("/opt/settings", response_model=OptSettingsOut)
def opt_settings(request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """화면 기본값: 비드 치수·자동 금지 영역·하중 선정 전략·목표 기준, 방법·출처(resources/opt_method_sources.json)."""
    return svc.settings_out(get_ctx(request))


# ---------------------------------------------------------------- 템플릿(S2)
@router.post("/opt/templates/check", response_model=MeshCheckOut)
def template_check(body: TemplateCheckIn, request: Request,
                   principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return tpl_svc.check_template(get_ctx(request), principal, body)


@router.post("/opt/templates", response_model=TemplateOut, status_code=201)
def template_register(body: TemplateIn, request: Request,
                      principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return tpl_svc.register_template(get_ctx(request), principal, body)


@router.get("/opt/templates", response_model=list[TemplateOut])
def template_list(request: Request, status: Literal["ACTIVE", "ARCHIVED"] | None = None,
                  q: str | None = Query(default=None, max_length=200),
                  principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return tpl_svc.list_templates(get_ctx(request), principal, status, q)


@router.get("/opt/templates/{tid}", response_model=TemplateOut)
def template_get(tid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return tpl_svc.get_template(get_ctx(request), principal, tid)


@router.delete("/opt/templates/{tid}", response_model=TemplateDeleteOut)
def template_delete(tid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """등록자·전역 관리자만. 실행이 참조 중이면 보관(ARCHIVED), 아니면 행 삭제 + 폴더 _templates/_backup 이동."""
    return tpl_svc.delete_template(get_ctx(request), principal, tid)


# ---------------------------------------------------------------- S1 확인·평면도·금지 영역
@router.post("/opt/s1-check", response_model=S1CheckOut)
def s1_check(body: S1CheckIn, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.s1_check(get_ctx(request), principal, body)


@router.get("/opt/plan-view", response_model=PlanViewOut)
def plan_view(request: Request, template_id: str | None = Query(default=None, max_length=64),
              entry_id: str | None = Query(default=None, max_length=64),
              principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.plan_view(get_ctx(request), principal, template_id, entry_id)


@router.get("/opt/keepouts", response_model=KeepoutSetOut)
def keepout_get(request: Request, template_id: str | None = Query(default=None, max_length=64),
                topo: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
                principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """세트가 없으면 404 KEEPOUT_NOT_FOUND(화면은 빈 세트로 시작)."""
    return ko_svc.get_set(get_ctx(request), principal, template_id, topo)


@router.put("/opt/keepouts", response_model=KeepoutSetOut)
def keepout_put(body: KeepoutSetIn, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return ko_svc.put_set(get_ctx(request), principal, body)


# ---------------------------------------------------------------- 실행
@router.post("/opt/runs", response_model=OptRunOut, status_code=201)
def run_create(body: OptRunIn, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.create_run(get_ctx(request), principal, body)


@router.get("/opt/runs", response_model=list[OptRunOut])
def run_list(request: Request, project_id: str | None = Query(default=None, max_length=64),
             scenario: Literal["S1", "S2"] | None = None,
             principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_runs(get_ctx(request), principal, project_id, scenario)


@router.get("/opt/runs/{rid}", response_model=OptRunOut)
def run_get(rid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_run(get_ctx(request), principal, rid)


@router.get("/opt/runs/{rid}/files", response_model=list[OptFileOut])
def run_files(rid: str, request: Request, principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_files(get_ctx(request), principal, rid)


@router.get("/opt/runs/{rid}/download", response_class=FileResponse)
def run_download(rid: str, request: Request, rel: str = Query(min_length=1, max_length=512),
                 principal: Principal = Depends(get_principal)) -> FileResponse:
    path = svc.run_file(get_ctx(request), principal, rid, rel)
    return FileResponse(path, filename=os.path.basename(path), media_type="application/octet-stream")


@router.get("/opt/runs/{rid}/bundle", response_class=StreamingResponse, responses=ZIP_RESPONSE)
def run_bundle(rid: str, request: Request, parts: str | None = Query(default=None, max_length=100),
               principal: Principal = Depends(get_principal)) -> StreamingResponse:
    """결과 받기(zip): parts = report,result,deck(기본) [,solve = OptiStruct 원본, raw = npz·대상]. 상한 초과 시 413."""
    return zip_response(svc.run_bundle(get_ctx(request), principal, rid, parts))


@router.get("/opt/runs/{rid}/report", response_class=HTMLResponse)
def run_report(rid: str, request: Request, download: bool = False,
               principal: Principal = Depends(get_principal)) -> Response:
    return html_report(svc.run_report(get_ctx(request), principal, rid), f"opt_{rid}_report.html", download)


@router.get("/opt/runs/{rid}/bead-map.png", response_class=FileResponse,
            responses={200: {"content": {"image/png": {}}, "description": "비드 맵 PNG"}})
def run_bead_map(rid: str, request: Request, principal: Principal = Depends(get_principal)) -> FileResponse:
    return FileResponse(svc.bead_map(get_ctx(request), principal, rid), media_type="image/png",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
