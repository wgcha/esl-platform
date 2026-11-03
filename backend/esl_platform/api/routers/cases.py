"""cases CRUD·보관, t*, 미리보기, 지지점 세트, Case 별 목록."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request

from ...core.auth import Principal
from ..deps import get_ctx, get_principal, get_token, request_id
from ..schemas import (
    CaseCreate,
    CaseOut,
    CasePatch,
    EslRunOut,
    JobCreate,
    JobOut,
    RunAllOut,
    RunAllStart,
    SupportCreate,
    SupportSetOut,
    SupportSuggestOut,
    SupportSuggestReq,
    TstarPut,
)
from ..services import cases as svc
from ..services import jobs as job_svc
from ..services import run_all as run_all_svc

router = APIRouter(tags=["cases"])


@router.get("/cases", response_model=list[CaseOut])
def list_cases(request: Request, project_id: str | None = None,
               status: Literal["ACTIVE", "ARCHIVED"] | None = None,
               principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_cases(get_ctx(request), project_id, status)


@router.post("/cases", response_model=CaseOut, status_code=201)
def create_case(body: CaseCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.create_case(get_ctx(request), principal, get_token(request), request_id(request), body)


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_case(get_ctx(request), case_id)


@router.patch("/cases/{case_id}", response_model=CaseOut)
def patch_case(case_id: str, body: CasePatch, request: Request,
               principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.patch_case(get_ctx(request), principal, case_id, body)


@router.post("/cases/{case_id}/archive", response_model=CaseOut)
def archive_case(case_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.archive_case(get_ctx(request), principal, case_id)


@router.post("/cases/{case_id}/jobs", response_model=JobOut, status_code=201)
def create_job(case_id: str, body: JobCreate, request: Request,
               principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return job_svc.create_job(get_ctx(request), principal, case_id, body)


@router.get("/cases/{case_id}/jobs", response_model=list[JobOut])
def list_jobs(case_id: str, request: Request, principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return job_svc.list_case_jobs(get_ctx(request), case_id)


@router.get("/cases/{case_id}/tstar")
def get_tstar(case_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_tstar(get_ctx(request), case_id)


@router.put("/cases/{case_id}/tstar", response_model=CaseOut)
def put_tstar(case_id: str, body: TstarPut, request: Request,
              principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.put_tstar(get_ctx(request), principal, case_id, body)


@router.get("/cases/{case_id}/preview")
def preview(case_id: str, request: Request, frame_index: int | None = Query(default=None, ge=0),
            principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.preview(get_ctx(request), case_id, frame_index)


@router.post("/cases/{case_id}/support-sets/suggest", response_model=SupportSuggestOut)
def suggest(case_id: str, request: Request, body: SupportSuggestReq | None = None,
            principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.suggest_support(get_ctx(request), principal, case_id)


@router.post("/cases/{case_id}/support-sets", response_model=SupportSetOut, status_code=201)
def create_support(case_id: str, body: SupportCreate, request: Request,
                   principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.create_support(get_ctx(request), principal, case_id, body)


@router.get("/cases/{case_id}/support-sets", response_model=list[SupportSetOut])
def list_supports(case_id: str, request: Request, principal: Principal = Depends(get_principal)
                  ) -> list[dict[str, Any]]:
    return svc.list_supports(get_ctx(request), case_id)


@router.get("/cases/{case_id}/esl-runs", response_model=list[EslRunOut])
def list_runs(case_id: str, request: Request, principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_esl_runs(get_ctx(request), case_id)


# ---------------------------------------------------------------- v0.13.0 일괄 실행(계약 esl_run_all.md §8)
@router.post("/cases/{case_id}/run-all", response_model=RunAllOut, status_code=201)
def start_run_all(case_id: str, request: Request, body: RunAllStart | None = None,
                  principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """①→④ 일괄 실행 시작·[이어서 실행]. 첫 동작까지 이 요청 안에서 — 응답 시점에 이미 STOPPED·DONE 일 수 있다."""
    return run_all_svc.start(get_ctx(request), principal, case_id, body.from_ if body else None)


@router.get("/cases/{case_id}/run-all", response_model=RunAllOut | list[RunAllOut] | None)
def get_run_all(case_id: str, request: Request, all_: bool = Query(default=False, alias="all"),
                principal: Principal = Depends(get_principal)) -> Any:
    """최신 1행(없으면 null). ?all=1 → 최신순 목록(최대 50 — 이력 화면)."""
    if all_:
        return run_all_svc.list_runs(get_ctx(request), case_id)
    return run_all_svc.get_latest(get_ctx(request), case_id)


@router.post("/cases/{case_id}/run-all/cancel", response_model=RunAllOut)
def cancel_run_all(case_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """[일괄 취소]: 체인 CANCELED + 체인이 만든 진행 중 작업 취소(입양 작업은 그대로). 시작한 사람 또는 전역 관리자."""
    return run_all_svc.cancel(get_ctx(request), principal, case_id)
