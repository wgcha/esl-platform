"""결과 조회 서비스: ESL 실행·하중표·검증·산출물(목록·다운로드)."""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from ...core import core_outputs as co
from ...core.errors import DomainError, conflict, not_found
from ...core.paths import safe_case_file
from ...core.repositories import cases as cases_repo
from ..context import AppContext
from .common import case_dir, esl_run_out, load_case, validation_out


def _run(conn, run_id: str) -> dict[str, Any]:
    run = cases_repo.get_esl_run(conn, run_id)
    if run is None:
        raise not_found("ESL_RUN_NOT_FOUND", "ESL 결과를 찾을 수 없습니다")
    return run


def get_esl_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        run = _run(conn, run_id)
        case = load_case(conn, run["case_id"])
        return esl_run_out(case, run, conn)


def forces(ctx: AppContext, run_id: str, top: int) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        run = _run(conn, run_id)
        case = load_case(conn, run["case_id"])
    if case.get("current_esl_run_id") != run_id:
        raise conflict("ESL_RUN_NOT_CURRENT", "이후 ESL 계산으로 산출물이 바뀌었습니다(현재 결과만 하중표 제공)")
    cdir = case_dir(ctx, case)
    try:
        fz = co.f_eq(cdir)
        nid_m, x0 = co.model_nodes(cdir)
    except (co.OutputMissing, OSError, ValueError, KeyError):
        raise conflict("PREREQUISITE_MISSING", "ESL 산출물(04_esl/f_eq.npz)이 없습니다", missing=["esl"]) from None
    nid = np.asarray(fz["node_id"], np.int64)
    F = np.asarray(fz["f"], np.float64)
    if not np.array_equal(nid, nid_m):
        raise DomainError("OUTPUT_INCONSISTENT", "f_eq.npz 와 model.npz 노드가 다릅니다", status=500)
    sup = {int(s["node_id"]) for s in (run.get("supports") or []) if isinstance(s, dict) and "node_id" in s}
    mag = np.linalg.norm(F, axis=1)
    order = np.lexsort((nid, -mag))[:top]
    rows = [{"node_id": int(nid[i]), "x": float(x0[i, 0]), "y": float(x0[i, 1]), "z": float(x0[i, 2]),
             "fx": float(F[i, 0]), "fy": float(F[i, 1]), "fz": float(F[i, 2]), "mag": float(mag[i]),
             "is_support": int(nid[i]) in sup} for i in order]
    return {"esl_run_id": run_id, "n_nodes": int(nid.size), "rows": rows}


def get_validation(ctx: AppContext, vid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        val = cases_repo.get_validation(conn, vid)
        if val is None:
            raise not_found("VALIDATION_NOT_FOUND", "검증 결과를 찾을 수 없습니다")
        run = _run(conn, val["esl_run_id"])
        case = load_case(conn, val["case_id"])
        return validation_out(case, run, val)


def list_validations(ctx: AppContext, case_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
        out = []
        for v in cases_repo.list_validations(conn, case_id=case_id):
            out.append(validation_out(case, _run(conn, v["esl_run_id"]), v))
        return out


def _artifact_out(ctx: AppContext, case: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    d = dict(a)
    d.pop("sha256", None)
    d["path"] = os.path.join(case_dir(ctx, case), a["rel"])
    d["downloadable"] = a["size"] <= ctx.settings.ui.max_artifact_bytes
    return d


def list_artifacts(ctx: AppContext, case_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
        return [_artifact_out(ctx, case, a) for a in cases_repo.list_artifacts(conn, case_id)]


def artifact_file(ctx: AppContext, aid: str) -> tuple[str, str]:
    with ctx.engine.connect() as conn:
        a = cases_repo.get_artifact(conn, aid)
        if a is None:
            raise not_found("ARTIFACT_NOT_FOUND", "산출물을 찾을 수 없습니다")
        case = load_case(conn, a["case_id"])
    root = case_dir(ctx, case)
    path = safe_case_file(root, a["rel"])
    if not os.path.isfile(path):
        raise not_found("ARTIFACT_NOT_FOUND", "산출물 파일이 없습니다(이후 실행으로 _backup 으로 이동했을 수 있음)")
    size = os.path.getsize(path)
    if size > ctx.settings.ui.max_artifact_bytes:
        raise DomainError("ARTIFACT_TOO_LARGE", "파일이 커서 다운로드할 수 없습니다. 경로를 복사해 여세요", status=413,
                          rel=a["rel"], path=path, size=size, limit=ctx.settings.ui.max_artifact_bytes)
    return path, os.path.basename(path)
