"""라이브러리 항목·종합분석·설계 버전 비교(계약 esl_p2_library.md §11·§12)."""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from ...core.auth import Principal
from ..deps import get_ctx, get_principal
from ..html_report import html_report
from .results import ZIP_RESPONSE, zip_response
from ..schemas import (
    AnalysisCreate,
    AnalysisFileOut,
    AnalysisOut,
    ComparisonCreate,
    ComparisonOut,
    DeleteCheckOut,
    DeleteOut,
    EntryCreate,
    EntryOut,
    EntryPatch,
    EntryRetire,
    ExportBatchCreate,
    ExportBatchOut,
    ExportBatchSummary,
    JobOut,
)
from ..services import bundle as bundle_svc
from ..services import comparisons as cmp_svc
from ..services import item_delete as del_svc
from ..services import library as svc
from ..services import library_export as export_svc

router = APIRouter(tags=["library"])


@router.post("/library/entries", response_model=EntryOut, status_code=201)
def register(body: EntryCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.register_entry(get_ctx(request), principal, body)


@router.get("/library/entries", response_model=list[EntryOut])
def list_entries(request: Request, project_id: str | None = None, model: str | None = None,
                 inch: str | None = None, drop_type: str | None = None, drop_class: str | None = None,
                 orient: str | None = None, scenario: str | None = None, verdict: str | None = None,
                 status: Literal["ACTIVE", "RETIRED"] | None = None,
                 mode: Literal["dent", "twist", "bend", "none"] | None = None,
                 principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_entries(get_ctx(request), project_id, status, mode=mode, model=model, inch=inch,
                            drop_type=drop_type, drop_class=drop_class, orient=orient, scenario=scenario,
                            verdict=verdict)


@router.get("/library/entries/{eid}", response_model=EntryOut)
def get_entry(eid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_entry(get_ctx(request), eid)


@router.patch("/library/entries/{eid}", response_model=EntryOut)
def patch_entry(eid: str, body: EntryPatch, request: Request,
                principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.patch_entry(get_ctx(request), principal, eid, body)


@router.post("/library/entries/{eid}/retire", response_model=EntryOut)
def retire(eid: str, request: Request, body: EntryRetire | None = None,
           principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.retire_entry(get_ctx(request), principal, eid, body)


@router.post("/library/entries/{eid}/revalidate", response_model=JobOut, status_code=201)
def revalidate(eid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """v0.10.0 §7.3: LEGACY·사유 등록 FAIL·판정 불가 항목을 현재 기준으로 다시 검증(VALIDATE origin library_revalidate)."""
    return svc.revalidate_entry(get_ctx(request), principal, eid)


# ---------------------------------------------------------------- v0.10.0 다중 내보내기(§6.1)
@router.post("/library/exports", response_model=ExportBatchOut, status_code=202)
def create_export(body: ExportBatchCreate, request: Request,
                  principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return export_svc.create_batch(get_ctx(request), principal, body)


@router.get("/library/exports", response_model=list[ExportBatchSummary])
def list_exports(request: Request, project_id: str = Query(min_length=1, max_length=64),
                 limit: int = Query(default=20, ge=1, le=100),
                 principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return export_svc.list_batches(get_ctx(request), principal, project_id, limit)


@router.get("/library/exports/{batch_id}", response_model=ExportBatchOut)
def get_export(batch_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return export_svc.get_batch(get_ctx(request), principal, batch_id)


@router.get("/library/exports/{batch_id}/bundle", response_class=StreamingResponse, responses=ZIP_RESPONSE)
def export_bundle(batch_id: str, request: Request, principal: Principal = Depends(get_principal)) -> StreamingResponse:
    """묶음 zip(manifest.json·README.txt·<NN>_<label>/). 진행 중 409 EXPORT_NOT_READY, 성공 0 409 EXPORT_FAILED, 상한 413."""
    return zip_response(export_svc.bundle(get_ctx(request), principal, batch_id))


@router.post("/library/analyses", response_model=AnalysisOut, status_code=201)
def create_analysis(body: AnalysisCreate, request: Request,
                    principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.create_analysis(get_ctx(request), principal, body)


@router.get("/library/analyses", response_model=list[AnalysisOut])
def list_analyses(request: Request, project_id: str | None = None,
                  principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_analyses(get_ctx(request), project_id, principal)


@router.get("/library/analyses/{aid}", response_model=AnalysisOut)
def get_analysis(aid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_analysis(get_ctx(request), aid, principal)


@router.get("/library/analyses/{aid}/delete-check", response_model=DeleteCheckOut)
def analysis_delete_check(aid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """v0.19.0 삭제 전 확인(참조하던 비드 최적화 수 n_opt_unlinked 포함)."""
    return del_svc.delete_check(get_ctx(request), principal, "ANALYSIS", aid)


@router.delete("/library/analyses/{aid}", response_model=DeleteOut)
def analysis_delete(aid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """v0.19.0 영구 삭제: 이 분석을 참조하던 opt_runs.analysis_id 는 NULL(최적화는 유지) + 폴더 _trash 이동."""
    return del_svc.delete_item(get_ctx(request), principal, "ANALYSIS", aid)


@router.get("/library/analyses/{aid}/report", response_class=HTMLResponse)
def analysis_report(aid: str, request: Request, download: bool = False,
                    principal: Principal = Depends(get_principal)) -> Response:
    return html_report(svc.analysis_report(get_ctx(request), aid), f"analysis_{aid}_report.html", download)


@router.get("/library/analyses/{aid}/files", response_model=list[AnalysisFileOut])
def analysis_files(aid: str, request: Request, principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_files(get_ctx(request), aid)


@router.get("/library/analyses/{aid}/download", response_class=FileResponse)
def analysis_download(aid: str, request: Request, rel: str = Query(min_length=1, max_length=512),
                      principal: Principal = Depends(get_principal)) -> FileResponse:
    path = svc.analysis_file(get_ctx(request), aid, rel)
    return FileResponse(path, filename=os.path.basename(path), media_type="application/octet-stream")


@router.get("/library/analyses/{aid}/bundle", response_class=StreamingResponse, responses=ZIP_RESPONSE)
def analysis_bundle(aid: str, request: Request, parts: str | None = Query(default=None, max_length=100),
                    principal: Principal = Depends(get_principal)) -> StreamingResponse:
    """분석 결과 받기(zip): parts = report,deck,csv(기본) [,raw = npz 포함]. 상한 초과 시 413."""
    return zip_response(bundle_svc.analysis_bundle(get_ctx(request), aid, parts))


# ---------------------------------------------------------------- 설계 버전 비교(§12.2)
@router.post("/library/comparisons", response_model=ComparisonOut, status_code=201)
def create_comparison(body: ComparisonCreate, request: Request,
                      principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return cmp_svc.create_comparison(get_ctx(request), principal, body)


@router.get("/library/comparisons", response_model=list[ComparisonOut])
def list_comparisons(request: Request, project_id: str | None = None, model: str | None = None,
                     principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return cmp_svc.list_comparisons(get_ctx(request), project_id, model, principal)


@router.get("/library/comparisons/{cid}", response_model=ComparisonOut)
def get_comparison(cid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return cmp_svc.get_comparison(get_ctx(request), cid, principal)


@router.get("/library/comparisons/{cid}/delete-check", response_model=DeleteCheckOut)
def comparison_delete_check(cid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """v0.19.0 삭제 전 확인."""
    return del_svc.delete_check(get_ctx(request), principal, "COMPARE", cid)


@router.delete("/library/comparisons/{cid}", response_model=DeleteOut)
def comparison_delete(cid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """v0.19.0 영구 삭제(DB 행 + 폴더 _trash 이동). 등록자·전역 관리자만."""
    return del_svc.delete_item(get_ctx(request), principal, "COMPARE", cid)


@router.get("/library/comparisons/{cid}/report", response_class=HTMLResponse)
def comparison_report(cid: str, request: Request, download: bool = False,
                      principal: Principal = Depends(get_principal)) -> Response:
    return html_report(cmp_svc.comparison_report(get_ctx(request), cid), f"comparison_{cid}_report.html", download)
