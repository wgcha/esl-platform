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
    cdir = case_dir(ctx, case)
    src = co.esl_source_dir(cdir, run)       # runs/<id>/ 스냅샷 또는 같은 실행의 04_esl
    if src is None:
        if case.get("current_esl_run_id") != run_id or co.esl_tag(cdir) is not None:
            raise conflict("ESL_RUN_NOT_CURRENT", "이 ESL 결과의 산출물이 없습니다(이후 ESL 계산으로 바뀜)")
        src = cdir                          # tag 기록 이전 형식의 현재 결과
    try:
        fz = co.f_eq(src)
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


# ---------------------------------------------------------------- P2: 전 요소 비교(계약 esl_p2_library.md §7.3·§11)
def locate_validation_dir(ctx: AppContext, case: dict[str, Any], val: dict[str, Any],
                          latest_id: str | None) -> tuple[str, bool] | None:
    """검증 val 의 05_val 산출물 폴더 (절대경로, `_backup` 에서 찾았는지) 또는 None.

    순서: run 스냅샷(runs/<id>/05_val, 표식 = val id) → (val 이 Case 최신 검증이면) Case 05_val → H-4(계약
    esl_p3_history.md): `_backup/*/runs/<run_id>/05_val` 중 표식이 val id 와 정확히 같은 폴더(최신 순 최대
    ``history.backup_scan_max`` 개 폴더, 심링크 무시).
    """
    cdir = case_dir(ctx, case)
    vid = val["id"]
    snap = co.val_snapshot_dir(cdir, val["esl_run_id"])
    if co.val_marker(snap) == vid:
        return snap, False
    if latest_id == vid:
        return os.path.join(cdir, co.D_VAL), False
    found = co.find_backup_validation_dir(cdir, val["esl_run_id"], vid, ctx.settings.history.backup_scan_max)
    return (found, True) if found else None


def _val_npz(ctx: AppContext, vid: str, name: str, *, required: bool = True,
             missing_key: str = "compare_field") -> tuple[dict[str, np.ndarray] | None, dict[str, Any]]:
    """검증 vid 의 05_val/<name>: run 스냅샷(runs/<id>/05_val, 표식 = vid) 또는 (vid 가 Case 최신 검증이면)
    Case 05_val, 없으면 `_backup` 표식 탐색(H-4, 읽기 전용). 산출물 폴더를 못 찾으면 409 VALIDATION_FILES_GONE.
    파일이 없으면 required 면 409 PREREQUISITE_MISSING(missing=[missing_key]), 아니면 None. 반환 (npz dict, 검증 행)."""
    with ctx.engine.connect() as conn:
        val = cases_repo.get_validation(conn, vid)
        if val is None:
            raise not_found("VALIDATION_NOT_FOUND", "검증 결과를 찾을 수 없습니다")
        case = load_case(conn, val["case_id"])
        latest = cases_repo.list_validations(conn, case_id=case["id"])
    cdir = case_dir(ctx, case)
    loc = locate_validation_dir(ctx, case, val, latest[0]["id"] if latest else None)
    if loc is None:
        raise conflict("VALIDATION_FILES_GONE", "이 검증의 산출물이 이후 검증으로 바뀌었습니다(같은 ESL 결과로 다시 검증)")
    d, from_backup = loc
    if from_backup:
        raw = os.path.join(d, name)
        if os.path.islink(raw) or not co.inside(os.path.realpath(raw), os.path.realpath(cdir)):
            raise conflict("VALIDATION_FILES_GONE", "이 검증의 산출물이 이후 검증으로 바뀌었습니다(같은 ESL 결과로 다시 검증)")
    path = safe_case_file(cdir, os.path.relpath(os.path.join(d, name), cdir))
    if not os.path.isfile(path):
        if not required:
            return None, val
        if missing_key == "disp_compare":
            raise conflict("PREREQUISITE_MISSING", "변위 전 노드 비교 산출물(compare_disp.npz)이 없습니다"
                           "(전체 재해석을 하지 않았거나 이전 판정 체계 검증 — 다시 검증하세요)", missing=["disp_compare"])
        raise conflict("PREREQUISITE_MISSING", "전 요소 비교 산출물(compare_field.npz)이 없습니다(이전 코어 버전의 검증)",
                       missing=["compare_field"])
    try:
        with np.load(path, allow_pickle=False) as z:
            return {k: z[k] for k in z.files}, val
    except (OSError, ValueError) as exc:
        raise DomainError("OUTPUT_INVALID", f"{name} 를 읽을 수 없습니다: {exc}", status=500) from None


def _compare_field(ctx: AppContext, vid: str) -> dict[str, np.ndarray]:
    return _val_npz(ctx, vid, "compare_field.npz")[0]


def _fin(v: float) -> float | None:
    return float(v) if np.isfinite(v) else None


def field(ctx: AppContext, vid: str, layer: str, max_points: int | None) -> dict[str, Any]:
    from esl_worker import core_adapter

    z = _compare_field(ctx, vid)
    try:
        eid = np.asarray(z["elem_id"], np.int64)
        c2 = np.asarray(z["centroid2d"], np.float64)
        er = np.asarray(z["eps_rad"], np.float64)
        ee = np.asarray(z["eps_esl"], np.float64)
        rel = np.asarray(z["rel_err"], np.float64)
        valid = np.asarray(z["valid"], bool)
        reason = np.asarray(z["reason"], np.int64)
        plane = {"origin": z["plane_origin"].tolist(), "e1": z["plane_e1"].tolist(), "e2": z["plane_e2"].tolist()}
    except KeyError as exc:
        raise DomainError("OUTPUT_INVALID", f"compare_field.npz 키 없음: {exc}", status=500) from None
    # flags 비트: 1 = 기준 초과, 2 = 소성 영역(epsp>0). 0.5.7 이전 산출물은 0
    flags = np.zeros(eid.size, np.int64)
    if "exceed" in z:
        flags += np.asarray(z["exceed"], bool).astype(np.int64)
    if "plastic" in z:
        flags += 2 * np.asarray(z["plastic"], bool).astype(np.int64)
    mp = ctx.settings.ui.max_preview_points
    mp = min(int(max_points), mp) if max_points else mp
    idx, cell = core_adapter.field_downsample(c2[:, 0], c2[:, 1], er, valid, mp)
    idx = np.asarray(idx, np.int64)
    if layer == "rad":
        val = er
    elif layer == "esl":
        val = ee
    else:
        val = np.where(valid, 100.0 * rel, np.nan)
    # 색 범위는 다운샘플 전 전체 집합으로 계산(계약 §14.2)
    if layer == "err":
        R = core_adapter.field_err_range(100.0 * rel[valid]) if valid.any() else None
        cr = {"min": -float(R), "max": float(R)} if R else {"min": None, "max": None}
        robust = core_adapter.field_robust_range(100.0 * rel[valid], "sym")
    else:
        both = np.concatenate([er[np.isfinite(er)], ee[np.isfinite(ee)]])
        cr = {"min": float(both.min()), "max": float(both.max())} if both.size else {"min": None, "max": None}
        robust = core_adapter.field_robust_range(both, "minmax")
    names = core_adapter.field_reasons()
    v = val[idx]
    points = [[i, a, b, (x if x == x and abs(x) != float("inf") else None), names.get(r, str(r)), f]
              for i, a, b, x, r, f in zip(eid[idx].tolist(), c2[idx, 0].tolist(), c2[idx, 1].tolist(), v.tolist(),
                                          reason[idx].tolist(), flags[idx].tolist())]
    return {"validation_id": vid, "layer": layer, "n_total": int(eid.size), "n_returned": int(idx.size),
            "decimated": cell is not None, "cell": None if cell is None else [float(cell[0]), float(cell[1])],
            "plane": plane, "color_range": cr, "color_range_robust": robust, "points": points}


def disp_field(ctx: AppContext, vid: str, layer: str, max_points: int | None) -> dict[str, Any]:
    """변위 전 노드 분석 2D 점(계약 esl_disp_primary.md §7). compare_disp.npz 없으면 409 PREREQUISITE_MISSING."""
    from esl_worker import core_adapter

    z, _ = _val_npz(ctx, vid, "compare_disp.npz", missing_key="disp_compare")
    try:
        nid = np.asarray(z["node_id"], np.int64)
        ab = np.asarray(z["ab"], np.float64)
        d_rel = np.asarray(z["d_rel"], np.float64)
        d_val = np.asarray(z["d_val"], np.float64)
        e = np.asarray(z["e"], np.float64)
        sup = np.asarray(z["is_support"], bool)
        U = float(z["U"])
        plane = {"origin": z["plane_origin"].tolist(), "e1": z["plane_e1"].tolist(), "e2": z["plane_e2"].tolist()}
    except KeyError as exc:
        raise DomainError("OUTPUT_INVALID", f"compare_disp.npz 키 없음: {exc}", status=500) from None
    mrel = np.linalg.norm(d_rel, axis=1)
    mval = np.linalg.norm(d_val, axis=1)
    err = e / U if U > 0 else np.full(e.shape, np.nan)
    mp = ctx.settings.ui.max_preview_points
    mp = min(int(max_points), mp) if max_points else mp
    # 셀 대표 = e 최대 노드(최대 보존): downsample 의 "valid 우선·값 최대" 규칙에 값 = e, valid = 전부
    idx, cell = core_adapter.field_downsample(ab[:, 0], ab[:, 1], e, np.ones(e.shape, bool), mp)
    idx = np.asarray(idx, np.int64)
    val = {"err": err, "rel": mrel, "val": mval}[layer]
    if layer == "err":
        fin = err[np.isfinite(err)]
        cr = {"min": 0.0, "max": float(fin.max())} if fin.size else {"min": None, "max": None}
        robust = core_adapter.field_robust_range(err, "zero")
    else:
        both = np.concatenate([mrel[np.isfinite(mrel)], mval[np.isfinite(mval)]])
        cr = {"min": float(both.min()), "max": float(both.max())} if both.size else {"min": None, "max": None}
        robust = core_adapter.field_robust_range(both, "zero")
    v = val[idx].tolist()
    points = [[i, a, b, (x if x == x and abs(x) != float("inf") else None), int(sp)]
              for i, a, b, x, sp in zip(nid[idx].tolist(), ab[idx, 0].tolist(), ab[idx, 1].tolist(), v,
                                        sup[idx].tolist())]
    return {"validation_id": vid, "layer": layer, "n_total": int(nid.size), "n_returned": int(idx.size),
            "decimated": cell is not None, "cell": None if cell is None else [float(cell[0]), float(cell[1])],
            "plane": plane, "color_range": cr, "color_range_robust": robust, "U": U, "points": points}


SUGGEST_LABEL = {"max_disp_err": "최대 변위 오차 노드 지나는 단면", "hotspot1": "변형률 hotspot 1위 지나는 단면"}


def section(ctx: AppContext, vid: str, axis: str, at: float) -> dict[str, Any]:
    """단면선(계약 esl_disp_primary.md §15.2). compare_field.npz(+있으면 compare_disp.npz)만 읽는다."""
    from esl_worker import core_adapter

    z, val = _val_npz(ctx, vid, "compare_field.npz")
    try:
        c2 = np.asarray(z["centroid2d"], np.float64)
        bx, by = (float(x) for x in np.asarray(z["sec_band"], np.float64)[:2])
        rng = z["xi_range"] if axis == "xi" else z["eta_range"]
        n0, w_rel, w_val = z["n0"], z["w_rel"], z["w_val"]
        xi_rng, eta_rng = z["xi_range"], z["eta_range"]
    except KeyError as exc:
        raise conflict("PREREQUISITE_MISSING", f"단면선 자료가 없습니다(compare_field.npz 키 {exc})",
                       missing=["section"]) from None
    fixed = core_adapter.field_normalize(c2[:, 0] if axis == "xi" else c2[:, 1], rng)
    along = c2[:, 1] if axis == "xi" else c2[:, 0]
    band = bx if axis == "xi" else by
    sec = core_adapter.field_section(fixed, along, n0, w_rel, w_val, at, band)

    def lst(a):
        return [float(x) for x in np.asarray(a, np.float64).tolist()]

    zd, _ = _val_npz(ctx, vid, "compare_disp.npz", required=False)
    has_val = zd is not None
    st = core_adapter.field_section_stats(sec["s"], sec["w_rel"], sec["w_val"] if has_val else None,
                                          float(zd["U"]) if has_val else None)
    suggest = []
    if has_val and np.size(zd["e"]):
        i = int(np.argmax(np.asarray(zd["e"], np.float64)))
        xn, en = core_adapter.field_normalized_point(np.asarray(zd["ab"], np.float64)[i], xi_rng, eta_rng)
        suggest.append({"key": "max_disp_err", "label": SUGGEST_LABEL["max_disp_err"], "xi": xn, "eta": en,
                        "id": int(np.asarray(zd["node_id"], np.int64)[i])})
    cand = (val.get("hotspots") or []) or (val.get("excluded") or [])
    if cand and isinstance(cand[0], dict) and cand[0].get("elem_id") is not None:
        pos = np.flatnonzero(np.asarray(z["elem_id"], np.int64) == int(cand[0]["elem_id"]))
        if pos.size:
            xn, en = core_adapter.field_normalized_point(c2[int(pos[0])], xi_rng, eta_rng)
            suggest.append({"key": "hotspot1", "label": SUGGEST_LABEL["hotspot1"], "xi": xn, "eta": en,
                            "id": int(cand[0]["elem_id"])})
    line = core_adapter.field_section_line(None, xi_rng, eta_rng, axis, at, band)
    return {"validation_id": vid, "axis": axis, "at": float(at), "band": float(band), "n_elems": int(sec["n_elems"]),
            "s": lst(sec["s"]), "w_rad": lst(sec["w_rel"]), "w_esl": lst(sec["w_val"]), "w0": lst(sec["n0"]),
            "dw": lst(st["dw"]), "stats": st["stats"], "has_val": has_val, "line": line,
            "units": ((ctx.config.core or {}).get("units") or {}).get("length"), "suggest": suggest}


def case_report(ctx: AppContext, case_id: str) -> tuple[str, str]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
    cdir = case_dir(ctx, case)
    path = safe_case_file(cdir, f"{co.D_REPORT}/{co.REPORT_HTML}")
    if not os.path.isfile(path):
        raise not_found("REPORT_NOT_FOUND", "보고서가 아직 없습니다(검증 후 자동 생성 또는 CASE_REPORT 작업)")
    return path, f"{case['folder_name']}_report.html"
