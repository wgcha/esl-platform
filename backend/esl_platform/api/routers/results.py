"""ESL 실행·하중표·검증·산출물."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from ...core.auth import Principal
from ...core.errors import DomainError
from ..display_json import DisplayJSONResponse
from ..deps import get_ctx, get_principal
from ..html_report import html_report
from ..schemas import ArtifactOut, DispFieldOut, EslRunOut, FieldOut, ForcesOut, SectionOut, ValidationOut, View3dOut
from ..services import bundle as bundle_svc
from ..services import results as svc
from ..services import view3d as view3d_svc

router = APIRouter(tags=["results"])


@router.get("/esl-runs/{run_id}", response_model=EslRunOut)
def get_run(run_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_esl_run(get_ctx(request), run_id)


@router.get("/esl-runs/{run_id}/forces", response_model=ForcesOut)
def forces(run_id: str, request: Request, top: int = Query(default=50, ge=1, le=1000),
           principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.forces(get_ctx(request), run_id, top)


# ---------------------------------------------------------------- ④ 3D 하중 보기(계약 esl_3d_load.md §4)
VIEW3D_CACHE_CONTROL = "private, max-age=0, must-revalidate"
VIEW3D_FILE_RESPONSES = {
    200: {"content": {"model/gltf-binary": {"schema": {"type": "string", "format": "binary"}},
                      "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
          "description": "바이너리(ETag = manifest key, If-None-Match 일치 시 304)"},
    304: {"description": "변경 없음"}}


def _etag_headers(key: str) -> dict[str, str]:
    return {"ETag": f'"{key}"', "Cache-Control": VIEW3D_CACHE_CONTROL}


def _not_modified(request: Request, key: str) -> bool:
    """If-None-Match 에 key 가 있거나 `*` 이면 True (약한 검증자 W/ 허용)."""
    inm = request.headers.get("if-none-match")
    if not inm:
        return False
    tags = [t.strip().removeprefix("W/").strip('"') for t in inm.split(",")]
    return "*" in tags or key in tags


def _busy_response(exc: DomainError) -> Response:
    return DisplayJSONResponse(status_code=exc.status, content={"detail": exc.detail()}, headers={"Retry-After": "5"})


@router.get("/esl-runs/{run_id}/view3d", response_model=View3dOut, responses={304: {"description": "변경 없음"}})
def view3d_manifest(run_id: str, request: Request, response: Response,
                    principal: Principal = Depends(get_principal)) -> Any:
    """3D 하중 보기 manifest(상위 100행·군집 K=2..5·범위·지지점·파일 URL). 첫 요청이 파생 캐시를 만든다(runs/<id>/view3d)."""
    try:
        m, key = view3d_svc.manifest(get_ctx(request), run_id)
    except DomainError as exc:
        if exc.code == "VIEW3D_BUSY":
            return _busy_response(exc)
        raise
    if _not_modified(request, key):
        return Response(status_code=304, headers=_etag_headers(key))
    response.headers.update(_etag_headers(key))
    return m


def _view3d_file(request: Request, run_id: str, name: str, key: str | None) -> Response:
    path, media, k = view3d_svc.file(get_ctx(request), run_id, name, key)
    headers = _etag_headers(k)
    if _not_modified(request, k):
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type=media, headers=headers)


@router.get("/esl-runs/{run_id}/view3d/part.glb", response_class=FileResponse, responses=VIEW3D_FILE_RESPONSES)
def view3d_part(run_id: str, request: Request, key: str | None = Query(default=None, max_length=64),
                principal: Principal = Depends(get_principal)) -> Response:
    """부품 표면 GLB(mm, Z-up, 정점 = 노드 순서). `key`(선택) = manifest.key, 다르면 409 VIEW3D_STALE."""
    return _view3d_file(request, run_id, "part.glb", key)


@router.get("/esl-runs/{run_id}/view3d/part_lod.glb", response_class=FileResponse, responses=VIEW3D_FILE_RESPONSES)
def view3d_part_lod(run_id: str, request: Request, key: str | None = Query(default=None, max_length=64),
                    principal: Principal = Depends(get_principal)) -> Response:
    """저해상도(LOD) 표면 GLB(N > view3d.lod_min_nodes 일 때만, 없으면 404 VIEW3D_LOD_NONE). `_SRC` = 원 정점 번호."""
    return _view3d_file(request, run_id, "part_lod.glb", key)


@router.get("/esl-runs/{run_id}/view3d/values.bin", response_class=FileResponse, responses=VIEW3D_FILE_RESPONSES)
def view3d_values(run_id: str, request: Request, key: str | None = Query(default=None, max_length=64),
                  principal: Principal = Depends(get_principal)) -> Response:
    """노드 값 바이너리(면압 p·Fn·|F|·u_rel 양자화, 배치는 manifest.values.arrays)."""
    return _view3d_file(request, run_id, "values.bin", key)


@router.get("/validations/{vid}", response_model=ValidationOut)
def get_validation(vid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return svc.get_validation(get_ctx(request), vid)


@router.get("/cases/{case_id}/validations", response_model=list[ValidationOut])
def list_validations(case_id: str, request: Request, principal: Principal = Depends(get_principal)
                     ) -> list[dict[str, Any]]:
    return svc.list_validations(get_ctx(request), case_id)


@router.get("/cases/{case_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(case_id: str, request: Request, principal: Principal = Depends(get_principal)
                   ) -> list[dict[str, Any]]:
    return svc.list_artifacts(get_ctx(request), case_id)


@router.get("/artifacts/{aid}/download", response_class=FileResponse)
def download(aid: str, request: Request, principal: Principal = Depends(get_principal)) -> FileResponse:
    path, name = svc.artifact_file(get_ctx(request), aid)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.get("/validations/{vid}/field", response_model=FieldOut)
def validation_field(vid: str, request: Request, layer: Literal["rad", "esl", "err"] = "rad",
                     max_points: int | None = Query(default=None, ge=10),
                     principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """전 요소 비교 2D 점(요소 중심 PCA 평면 좌표 + 값), 2D 셀 격자 다운샘플(≤ ui.max_preview_points)."""
    return svc.field(get_ctx(request), vid, layer, max_points)


@router.get("/validations/{vid}/disp-field", response_model=DispFieldOut)
def validation_disp_field(vid: str, request: Request, layer: Literal["err", "rel", "val"] = "err",
                          max_points: int | None = Query(default=None, ge=10),
                          principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """변위 전 노드 분석 2D 점(err = e/U, rel = ‖d_rel‖, val = ‖d_val‖). 다운샘플 셀 대표 = e 최대 노드."""
    return svc.disp_field(get_ctx(request), vid, layer, max_points)


@router.get("/validations/{vid}/section", response_model=SectionOut)
def validation_section(vid: str, request: Request, axis: Literal["xi", "eta"] = "eta",
                       at: float = Query(default=0.5, ge=0.0, le=1.0),
                       principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """단면선: 정규화 좌표 axis = at 고정 띠의 요소를 다른 축 방향으로 bin 평균(면외 변위 Radioss·ESL, 초기 면외 좌표).
    axis=eta(기본): 판 길이 방향 단면, axis=xi: 판 폭 방향 단면. Δw·통계·지도용 선·추천 단면 포함."""
    return svc.section(get_ctx(request), vid, axis, at)


@router.get("/cases/{case_id}/report", response_class=HTMLResponse)
def case_report(case_id: str, request: Request, download: bool = False,
                principal: Principal = Depends(get_principal)) -> Response:
    path, name = svc.case_report(get_ctx(request), case_id)
    return html_report(path, name, download)


ZIP_RESPONSE = {200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
                      "description": "zip(스트리밍)"}}


def zip_response(b: dict[str, Any]) -> StreamingResponse:
    return StreamingResponse(bundle_svc.stream_zip(b["files"], b["prefix"]), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{b["filename"]}"',
                                      "X-Bundle-Files": str(len(b["files"])), "X-Bundle-Bytes": str(b["size"])})


@router.get("/cases/{case_id}/bundle", response_class=StreamingResponse, responses=ZIP_RESPONSE)
def case_bundle(case_id: str, request: Request, parts: str | None = Query(default=None, max_length=100),
                principal: Principal = Depends(get_principal)) -> StreamingResponse:
    """결과 받기(zip): parts = export,report,summary(기본) [,raw = npz 포함]. 상한 ui.max_bundle_bytes 초과 시 413."""
    return zip_response(bundle_svc.case_bundle(get_ctx(request), case_id, parts))
