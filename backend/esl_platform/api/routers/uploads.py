"""브라우저 분할 업로드(계약 esl_p3_ux.md §1.1) — 허용된 유일한 업로드 경로. multipart 미사용(청크 PUT octet-stream)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

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
    """청크(application/octet-stream). 프로토콜 2: offset = k·chunk_size 인 정렬 청크 하나를 정확히(Content-Length 필수 —
    없으면 411, 길이 불일치 422), 순서 무관·동시(upload.parallel, 초과 429 + Retry-After), 이미 받은 청크는 200 duplicate.
    본문은 스트리밍으로 `.part` 의 위치에 직접 쓴다. 프로토콜 1(업그레이드 전 세션)은 offset = 받은 크기(409 + received).
    헤더 X-Chunk-Sha256(청크 sha256)이 있으면 검증(다르면 422, 표시하지 않음). 파일 전체 sha256 은 서버가 계산해 기록."""
    ctx = get_ctx(request)
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != OCTET:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", f"Content-Type 은 {OCTET} 이어야 합니다", status=415)
    try:
        declared: int | None = int(request.headers["content-length"])
        if declared < 0:
            declared = None
    except (KeyError, ValueError):
        declared = None
    pl = await run_in_threadpool(svc.acquire_chunk, ctx, principal, upload_id, index, offset, declared)
    try:
        if pl.mode == 1:
            return await _put_v1(ctx, principal, request, pl, x_chunk_sha256, declared)
        if pl.duplicate:                                   # 본문은 읽어 버린다(≤ C)
            n = 0
            async for part in request.stream():
                n += len(part)
                if n > pl.chunk:
                    raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({pl.chunk} B)보다 큽니다", status=413,
                                      limit=pl.chunk)
            return pl.out
        sink = await run_in_threadpool(svc.open_sink, ctx, pl)
        try:
            buf = bytearray()
            async for part in request.stream():
                if sink.total + len(buf) + len(part) > pl.exp_len:
                    raise DomainError("CHUNK_TOO_LARGE", f"본문이 선언한 청크 길이({pl.exp_len} B)보다 깁니다(표시하지 않음)",
                                      status=413, limit=pl.exp_len)
                buf += part
                if len(buf) >= sink.buf_size:
                    data = bytes(buf)
                    buf.clear()
                    await run_in_threadpool(sink.write, data)
            if buf:
                await run_in_threadpool(sink.write, bytes(buf))
            return await run_in_threadpool(svc.commit_chunk, ctx, principal, pl, sink, x_chunk_sha256)
        finally:
            sink.close()
    except ClientDisconnect:
        raise DomainError("CLIENT_DISCONNECTED", "전송이 중간에 끊겼습니다(표시하지 않음)", status=400) from None
    finally:
        svc.release_chunk(pl)


async def _put_v1(ctx, principal, request: Request, pl, x_chunk_sha256, declared) -> dict[str, Any]:
    limit = ctx.settings.upload.chunk_bytes
    if declared is not None and declared > limit:
        raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({limit} B)보다 큽니다", status=413, limit=limit)
    buf = bytearray()
    async for part in request.stream():
        buf += part
        if len(buf) > limit:
            raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({limit} B)보다 큽니다", status=413, limit=limit)
    return await run_in_threadpool(svc.put_chunk_v1, ctx, principal, pl.upload_id, pl.index, pl.offset, bytes(buf),
                                  x_chunk_sha256)


@router.post("/uploads/{upload_id}/complete", response_model=UploadCompleteOut)
def complete(upload_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """서버 검사: rad 파싱(파트 목록·include 해석), h3d 헤더 또는 결과 폴더(done.json·필수 CSV). 통과 시 COMPLETED."""
    return svc.complete(get_ctx(request), principal, upload_id)


@router.delete("/uploads/{upload_id}", response_model=UploadOut)
def cancel(upload_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """미완료 세션 취소 — 받은 파일은 <upload_root>/_backup 으로 이동(삭제 없음)."""
    return svc.cancel(get_ctx(request), principal, upload_id)


@router.delete("/uploads/{upload_id}/files/{index}", response_model=UploadOut)
def remove_file(upload_id: str, index: int, request: Request,
                principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """파일 하나 빼기 — 항목은 removed 로 표시(index 유지)하고 받은 부분은 _backup 으로 이동(삭제 없음). 완료된 업로드는
    이 업로드로 만든 Case 가 없을 때만(409 UPLOAD_IN_USE), 빼면 OPEN 으로 돌아가 다시 complete 해야 한다."""
    return svc.remove_file(get_ctx(request), principal, upload_id, index)
