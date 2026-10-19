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
    SupportCreate,
    SupportSetOut,
    SupportSuggestOut,
    SupportSuggestReq,
    TstarPut,
)
from ..services import cases as svc
from ..services import jobs as job_svc

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
