"""작업 조회·취소·재시도·로그."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ...core.auth import Principal
from ..deps import get_ctx, get_principal
from ..schemas import JobOut, LogOut
from ..services import jobs as svc

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_job(get_ctx(request), job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.cancel_job(get_ctx(request), principal, job_id)


@router.post("/jobs/{job_id}/retry", response_model=JobOut, status_code=201)
def retry(job_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.retry_job(get_ctx(request), principal, job_id)


@router.get("/jobs/{job_id}/log", response_model=LogOut)
def log(job_id: str, request: Request, step: int | None = Query(default=None, ge=1),
        cursor: int = Query(default=0, ge=0), principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.job_log(get_ctx(request), job_id, step, cursor)
