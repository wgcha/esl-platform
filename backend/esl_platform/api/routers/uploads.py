"""브라우저 분할 업로드(계약 esl_p3_ux.md §1.1) — 허용된 유일한 업로드 경로. multipart 미사용(청크 PUT octet-stream)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.concurrency import run_in_threadpool

from ...core.auth import Principal
from ...core.errors import DomainError
from ..deps import get_ctx, get_principal
from ..schemas import UploadChunkOut, UploadCompleteOut, UploadCreate, UploadFilesAdd, UploadOut
from ..services import uploads as svc

router = APIRouter(tags=["uploads"])

OCTET = "application/octet-stream"
CHUNK_BODY = {"requestBody": {"required": True, "content": {OCTET: {"schema": {"type": "string", "format": "binary"}}}}}


@router.post("/uploads", response_model=UploadOut, status_code=201)
def create_upload(body: UploadCreate, request: Request, principal: Principal = Depends(get_principal)
                  ) -> dict[str, Any]:
    """업로드 세션 생성(용량·확장자·이름 사전 검사, 폴더 <upload_root>/<사용자>/<UTC>_<이름>/ 생성)."""
    return svc.create_upload(get_ctx(request), principal, body)


@router.get("/uploads", response_model=list[UploadOut])
def list_uploads(request: Request, state: Literal["OPEN", "COMPLETED", "CANCELED", "STALE"] | None = None,
                 principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    """내 업로드(최근 50개) — 새로 고친 뒤 이어 올리기용."""
    return svc.list_uploads(get_ctx(request), principal, state)


@router.get("/uploads/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """파일별 received(서버가 받은 크기 — 이어 올리기 offset)·done·sha256."""
    return svc.get_upload(get_ctx(request), principal, upload_id)


@router.post("/uploads/{upload_id}/files", response_model=UploadOut)
def add_files(upload_id: str, body: UploadFilesAdd, request: Request,
              principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """미완료 세션에 파일 추가(complete 가 알려 준 누락 include 등). 새 파일 index 는 기존 뒤에 붙는다."""
    return svc.add_files(get_ctx(request), principal, upload_id, body)


@router.put("/uploads/{upload_id}/files/{index}", response_model=UploadChunkOut, openapi_extra=CHUNK_BODY)
async def put_chunk(upload_id: str, index: int, request: Request, offset: int = Query(ge=0),
                    x_chunk_sha256: str | None = Header(default=None, pattern=r"^[0-9a-fA-F]{64}$"),
                    principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """청크(application/octet-stream, ≤ chunk_size). offset 은 서버가 받은 크기와 같아야 한다(409 + received).
    헤더 X-Chunk-Sha256(청크 sha256)이 있으면 검증(다르면 422, 쓰지 않음). 파일 전체 sha256 은 서버가 받으며 계산해 기록."""
    ctx = get_ctx(request)
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != OCTET:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", f"Content-Type 은 {OCTET} 이어야 합니다", status=415)
    limit = ctx.settings.upload.chunk_bytes
    try:
        declared = int(request.headers.get("content-length", "-1"))
    except ValueError:
        declared = -1
    if declared > limit:
        raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({limit} B)보다 큽니다", status=413, limit=limit)
    buf = bytearray()
    async for part in request.stream():
        buf += part
        if len(buf) > limit:
            raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({limit} B)보다 큽니다", status=413, limit=limit)
    return await run_in_threadpool(svc.put_chunk, ctx, principal, upload_id, index, offset, bytes(buf),
                                  x_chunk_sha256)


@router.post("/uploads/{upload_id}/complete", response_model=UploadCompleteOut)
def complete(upload_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """서버 검사: rad 파싱(파트 목록·include 해석), h3d 헤더 또는 결과 폴더(done.json·필수 CSV). 통과 시 COMPLETED."""
    return svc.complete(get_ctx(request), principal, upload_id)


@router.delete("/uploads/{upload_id}", response_model=UploadOut)
def cancel(upload_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """미완료 세션 취소 — 받은 파일은 <upload_root>/_backup 으로 이동(삭제 없음)."""
    return svc.cancel(get_ctx(request), principal, upload_id)
