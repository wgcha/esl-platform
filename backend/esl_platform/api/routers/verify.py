"""Radioss 검증 낙하(계약 esl_scx_relay.md 기능 B §7) — 계획·생성·조회·[잡 ID 연결]/[포기]·비교 CSV·파일.

권한: 계획·생성·연결/포기 = 프로젝트 power 이상, 조회 = 멤버. 진행·취소·재시도는 기존 `/jobs/{id}`·`/cancel`·`/retry`
(VERIFY_DROP 취소 = VD_WAIT 중이면 SCX 잡 terminate 1회).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from ...core.auth import Principal
from ..deps import get_ctx, get_principal
from ..schemas import VerifyDropCreateOut, VerifyDropIn, VerifyDropOut, VerifyPlanOut, VerifyResolveIn
from ..services import verify_drop as svc

router = APIRouter(tags=["verify"])


@router.post("/verify-drops/plan", response_model=VerifyPlanOut)
def verify_plan(body: VerifyDropIn, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """대화상자 씬 목록·제외 사유·제출 건수·예상 시간(저장 안 함). 생성과 같은 씬 선택."""
    return svc.plan(get_ctx(request), principal, body)


@router.post("/verify-drops", response_model=VerifyDropCreateOut, status_code=201)
def verify_create(body: VerifyDropIn, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """씬마다 verify_drops 행 1개 + VERIFY_DROP(XFER) 작업 1개(batch_id 로 묶음). 씬별 제외는 excluded[]."""
    return svc.create(get_ctx(request), principal, body)


@router.get("/verify-drops", response_model=list[VerifyDropOut])
def verify_list(request: Request, bead_doe_id: str = Query(min_length=1, max_length=64),
                principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_drops(get_ctx(request), principal, bead_doe_id)


@router.get("/verify-drops/{did}", response_model=VerifyDropOut)
def verify_get(did: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_drop(get_ctx(request), principal, did)


@router.post("/verify-drops/{did}/resolve", response_model=VerifyDropOut)
def verify_resolve(did: str, body: VerifyResolveIn, request: Request,
                   principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """제출 결과 모름(UNKNOWN) 정리: attach = SCX 잡 ID 연결(→ 폴링부터 새 작업), abandon = 포기(→ [재시도]는 새 attempt)."""
    return svc.resolve(get_ctx(request), principal, did, body)


@router.get("/verify-drops/{did}/compare.csv", response_class=FileResponse)
def verify_compare_csv(did: str, request: Request, principal: Principal = Depends(get_principal)) -> FileResponse:
    p = svc.result_file(get_ctx(request), principal, did, "compare.csv")
    return FileResponse(p, filename=f"verify_{did[:8]}_compare.csv", media_type="text/csv; charset=utf-8")


@router.get("/verify-drops/{did}/files/{name}", response_class=FileResponse)
def verify_file(did: str, name: str, request: Request, principal: Principal = Depends(get_principal)) -> FileResponse:
    """stage.json·compare.json·compare.csv·Radioss out(result/*.out)."""
    p = svc.result_file(get_ctx(request), principal, did, name)
    return FileResponse(p, filename=os.path.basename(p), media_type="application/octet-stream")
