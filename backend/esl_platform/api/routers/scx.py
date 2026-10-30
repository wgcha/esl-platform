"""SCX 드라이브에서 고르기(계약 esl_scx_relay.md 기능 A §7) — 상태·탐색·내려받기 요청. 내려받기 자체는 워커 SCX_FETCH(XFER).

진행은 기존 `GET /jobs/{id}`(progress_pct·progress_label)·`GET /uploads/{id}`, 취소·재시도는 기존 `/jobs/{id}/cancel`·`/retry`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ...core.auth import Principal
from ..deps import get_ctx, get_principal
from ..schemas import ScxBrowseOut, ScxFetchIn, ScxFetchOut, ScxStatusOut
from ..services import scx_drive as svc

router = APIRouter(tags=["scx"])


@router.get("/scx/status", response_model=ScxStatusOut)
def scx_status(request: Request, project_id: str = Query(min_length=1, max_length=64),
               principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """기능별 사용 가능 여부(항상 200 — 사유는 본문 reason_code·reason). 릴레이 헬스는 hpc.scx.health_ttl_s 캐시, 한 번 3 s 한도."""
    return svc.get_status(get_ctx(request), principal, project_id)


@router.get("/scx/browse", response_model=ScxBrowseOut)
def scx_browse(request: Request, project_id: str = Query(min_length=1, max_length=64),
               root: str = Query(min_length=1, max_length=32), path: str = Query(default="", max_length=1024),
               offset: int = Query(default=0, ge=0), limit: int | None = Query(default=None, ge=1),
               principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """루트(scx_drive.roots) 기준 폴더 목록(폴더 먼저·이름 순, 숨김 제외, hint). power 이상. 범위 밖·SPDM 422,
    없는 루트·경로 404, 항목 과다 413, 릴레이 다운·비활성 503 SCX_UNAVAILABLE{reason_code}."""
    return svc.browse(get_ctx(request), principal, project_id, root, path, offset, limit)


@router.post("/scx/fetches", response_model=ScxFetchOut, status_code=202)
def scx_fetch(body: ScxFetchIn, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """rad(+include·엔진 rad 자동)·h3d 내려받기 요청: 업로드 세션(OPEN, <upload_root>/<사용자>/<UTC>_<이름>/) + SCX_FETCH 작업을
    한 트랜잭션에 만든다. 끝나면 워커가 기존 complete 검사(inspect_upload)를 실행 — 이후 기존 ?upload= 화면·POST /cases."""
    return svc.create_fetch(get_ctx(request), principal, body)
