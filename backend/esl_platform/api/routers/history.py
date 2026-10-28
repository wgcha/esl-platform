"""실행 이력(계약 esl_p3_history.md §3): 목록·작업 상세·과거 결과 파일. 모두 GET, 조회 = ACTIVE 인증 사용자."""

from __future__ import annotations

import datetime as _dt
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from ...core.auth import Principal
from ..deps import get_ctx, get_principal
from ..html_report import html_report
from ..schemas import HistoryFileOut, HistoryPage, ReviewOut
from ..services import history as svc
from ..services import jobs as jobs_svc

router = APIRouter(tags=["history"])


@router.get("/history", response_model=HistoryPage)
def history(request: Request, project_id: str = Query(min_length=1, max_length=200),
            case_id: str | None = Query(default=None, max_length=64),
            job_type: str | None = Query(default=None, max_length=200, description="쉼표 목록"),
            state: str | None = Query(default=None, max_length=200, description="쉼표 목록"),
            mine: bool = False, q: str | None = Query(default=None, max_length=100),
            from_: _dt.datetime | None = Query(default=None, alias="from"),
            to: _dt.datetime | None = Query(default=None), cursor: str | None = None,
            limit: int = Query(default=50, ge=1, le=200),
            principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """프로젝트 실행 이력(created_at DESC, id DESC keyset). 전체 개수는 세지 않는다(has_more)."""
    return svc.list_history(get_ctx(request), principal, project_id=project_id, case_id=case_id, job_type=job_type,
                            state=state, mine=mine, q=q, dt_from=from_, dt_to=to, cursor=cursor, limit=limit)


@router.get("/jobs/{job_id}/review", response_model=ReviewOut, response_model_exclude_unset=True)
def review(job_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """작업 다시 확인: 입력값·오류·소요 시간·로그 목록·그때 결과(기록된 값). step.command 는 전역 관리자에게만."""
    jobs_svc.check_job_view(get_ctx(request), principal, job_id)
    return svc.review(get_ctx(request), principal, job_id)


@router.get("/jobs/{job_id}/files", response_model=list[HistoryFileOut])
def job_files(job_id: str, request: Request, principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    jobs_svc.check_job_view(get_ctx(request), principal, job_id)
    return svc.job_files(get_ctx(request), job_id)


@router.get("/jobs/{job_id}/files/{name}/download", response_class=FileResponse)
def job_file_download(job_id: str, name: str, request: Request,
                      principal: Principal = Depends(get_principal)) -> FileResponse:
    jobs_svc.check_job_view(get_ctx(request), principal, job_id)
    path, fname = svc.job_file(get_ctx(request), job_id, name)
    return FileResponse(path, filename=fname, media_type="application/octet-stream")


@router.get("/jobs/{job_id}/report", response_class=HTMLResponse)
def job_report(job_id: str, request: Request, download: bool = False,
               principal: Principal = Depends(get_principal)) -> Response:
    jobs_svc.check_job_view(get_ctx(request), principal, job_id)
    path, fname = svc.job_report(get_ctx(request), job_id)
    return html_report(path, fname, download)
