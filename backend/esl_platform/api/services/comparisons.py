"""설계 버전 비교 서비스(계약 esl_p2_library.md §12.2): 생성(LIB_COMPARE 작업 큐)·목록·조회·보고서.

- 짝 = 같은 제품(model.name)의 기준/비교 버전 활성 항목 중 같은 씬 키(scenario, seq, drop_type, round, scene_no,
  orient, suffix; 대소문자 무시). 생성 시점에 짝이 없으면 422 ``NO_PAIRED_SCENES``(작업을 만들지 않음).
- 기준 버전이 없으면 비교 버전의 직전 버전(자연 정렬, 코어 규칙). 같은 버전끼리는 비교하지 않는다.
- 항목 목록·DB 메타(사용자 수정 가능)는 작업 params(overlay)로 스냅샷 — 코어는 항목 폴더(entry.json·summary.npz)만 읽는다.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from typing import Any

from esl_worker import core_adapter

from ...core.auth import Principal
from ...core.errors import not_found, unprocessable
from ...core.paths import COMPARE_DIR, esl_subdir, safe_case_file
from ...core.repositories import jobs as jobs_repo
from ...core.repositories import library as lib_repo
from ..context import AppContext
from .common import job_out, require_execute, require_library_config
from .library import _overlay

KEY_FIELDS = ("scenario", "seq", "drop_type", "round", "scene_no", "orient", "suffix")


def scene_key(e: dict[str, Any]) -> tuple:
    s = e.get("scene") or {}
    return tuple("" if s.get(k) is None else str(s.get(k)).strip().lower() for k in KEY_FIELDS)


def _version(e: dict[str, Any]) -> str | None:
    v = (e.get("model") or {}).get("version")
    return None if v is None or not str(v).strip() else str(v)


def comparison_out(ctx: AppContext, conn, c: dict[str, Any]) -> dict[str, Any]:
    d = dict(c)
    job = jobs_repo.get_job(conn, c["job_id"]) if c.get("job_id") else None
    d["job"] = job_out(conn, job, with_steps=True) if job else None
    d["status"] = job["state"] if job else "NONE"
    d["folder_path"] = os.path.join(ctx.settings.storage.esl_root, *c["dir_rel"].split("/"))
    return d


def _load(conn, cid: str, *, for_update: bool = False) -> dict[str, Any]:
    c = lib_repo.get_comparison(conn, cid, for_update=for_update)
    if c is None:
        raise not_found("COMPARISON_NOT_FOUND", "비교를 찾을 수 없습니다")
    return c


def create_comparison(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    require_execute(principal, body.project_id)
    lib_cfg = require_library_config(ctx)
    f = body.filters
    with ctx.engine.begin() as conn:
        rows = lib_repo.list_entries(conn, project_id=body.project_id, status="ACTIVE", model=[body.model],
                                     inch=[str(i) for i in f.inch] if f.inch else None, drop_type=f.drop_type,
                                     drop_class=f.drop_class, orient=f.orient, scenario=f.scenario, verdict=f.verdict)
        rows.sort(key=lambda e: (e["registered_at"], e["id"]))          # 같은 키가 여럿이면 마지막(최근 등록)
        versions = core_adapter.sort_versions({_version(e) for e in rows})
        if body.new_version not in versions:
            raise unprocessable("VERSION_NOT_FOUND", f"모델 {body.model} 에 비교 버전 {body.new_version} 의 활성 항목이 "
                                "없습니다", versions=versions)
        base_v = body.base_version or core_adapter.previous_version(versions, body.new_version)
        if base_v is None:
            raise unprocessable("NO_PAIRED_SCENES", f"비교 버전 {body.new_version} 이전 버전이 없습니다",
                                versions=versions)
        if base_v == body.new_version:
            raise unprocessable("INVALID_PARAMS", "기준 버전과 비교 버전이 같습니다")
        if base_v not in versions:
            raise unprocessable("VERSION_NOT_FOUND", f"모델 {body.model} 에 기준 버전 {base_v} 의 활성 항목이 없습니다",
                                versions=versions)
        base = {scene_key(e): e for e in rows if _version(e) == base_v}
        new = {scene_key(e): e for e in rows if _version(e) == body.new_version}
        paired = sorted(set(base) & set(new))
        if not paired:
            raise unprocessable("NO_PAIRED_SCENES", "기준·비교 버전에 같은 씬 키(시나리오·seq·낙하 유형·round·scene·"
                                "orient·suffix)의 항목이 없습니다", base_version=base_v, new_version=body.new_version)
        used = [base[k] for k in paired] + [new[k] for k in paired]
        grids = {tuple(((e["summary"] or {}).get("grid") or {}).get(k) for k in ("nx", "ny")) for e in used}
        if len(grids) != 1:
            raise unprocessable("GRID_MISMATCH", f"비교는 같은 정규화 격자가 필요합니다(항목 격자 {sorted(map(str, grids))})")
        b_rows, n_rows = list(base.values()), list(new.values())
        cid = str(uuid.uuid4())
        esl_subdir(ctx.settings, COMPARE_DIR, cid)          # 경로 안전성(실제 생성은 워커)
        filters = f.model_dump(exclude_none=True)
        options = body.options.model_dump(exclude_none=True)
        c = lib_repo.insert_comparison(
            conn, id=cid, project_id=body.project_id, title=body.title, model=body.model, base_version=base_v,
            new_version=body.new_version, filters=filters, options=options,
            base_entry_ids=[e["id"] for e in b_rows], new_entry_ids=[e["id"] for e in n_rows], n_paired=len(paired),
            dir_rel=f"{COMPARE_DIR}/{cid}", created_by=principal.user_id, created_by_name=principal.display_name)
        params = {"settings": copy.deepcopy(lib_cfg), "comparison_id": cid, "title": body.title, "model": body.model,
                  "base_version": base_v, "new_version": body.new_version, "options": options, "filters": filters,
                  "base": [{"id": e["id"], "dir_rel": e["dir_rel"], "overlay": _overlay(e)} for e in b_rows],
                  "new": [{"id": e["id"], "dir_rel": e["dir_rel"], "overlay": _overlay(e)} for e in n_rows]}
        job = jobs_repo.insert_job(conn, case_id=None, comparison_id=cid, project_id=body.project_id,
                                   job_type="LIB_COMPARE", params=json.loads(json.dumps(params, default=str)),
                                   created_by=principal.user_id, created_by_name=principal.display_name)
        c = lib_repo.update_comparison(conn, cid, job_id=job["id"])
        return comparison_out(ctx, conn, c)


def list_comparisons(ctx: AppContext, project_id: str | None, model: str | None) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        return [comparison_out(ctx, conn, c) for c in lib_repo.list_comparisons(conn, project_id, model)]


def get_comparison(ctx: AppContext, cid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        return comparison_out(ctx, conn, _load(conn, cid))


def comparison_report(ctx: AppContext, cid: str) -> str:
    with ctx.engine.connect() as conn:
        c = _load(conn, cid)
    path = safe_case_file(esl_subdir(ctx.settings, COMPARE_DIR, c["id"]), "report.html")
    if not os.path.isfile(path):
        raise not_found("REPORT_NOT_FOUND", "보고서가 아직 없습니다(비교 작업 완료 후 생성)")
    return path
