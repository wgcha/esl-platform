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
    EntryCreate,
    EntryOut,
    EntryPatch,
    EntryRetire,
)
from ..services import bundle as bundle_svc
from ..services import comparisons as cmp_svc
from ..services import library as svc

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


@router.post("/library/analyses", response_model=AnalysisOut, status_code=201)
def create_analysis(body: AnalysisCreate, request: Request,
                    principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.create_analysis(get_ctx(request), principal, body)


@router.get("/library/analyses", response_model=list[AnalysisOut])
def list_analyses(request: Request, project_id: str | None = None,
                  principal: Principal = Depends(get_principal)) -> list[dict[str, Any]]:
    return svc.list_analyses(get_ctx(request), project_id)


@router.get("/library/analyses/{aid}", response_model=AnalysisOut)
def get_analysis(aid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_analysis(get_ctx(request), aid)


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
    return cmp_svc.list_comparisons(get_ctx(request), project_id, model)


@router.get("/library/comparisons/{cid}", response_model=ComparisonOut)
def get_comparison(cid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return cmp_svc.get_comparison(get_ctx(request), cid)


@router.get("/library/comparisons/{cid}/report", response_class=HTMLResponse)
def comparison_report(cid: str, request: Request, download: bool = False,
                      principal: Principal = Depends(get_principal)) -> Response:
    return html_report(cmp_svc.comparison_report(get_ctx(request), cid), f"comparison_{cid}_report.html", download)
