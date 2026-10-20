"""코어 산출물 → DB 요약 등록(계약 esl_platform_p1b.md §2·§3). 대용량 배열은 DB에 넣지 않는다.

각 함수는 lease 를 확인한 트랜잭션 안에서 호출된다(호출자 executor).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any

import numpy as np
from sqlalchemy.engine import Connection

from esl_platform.core import core_outputs as co
from esl_platform.core.repositories import cases as cases_repo

from . import esl_snapshot

SHA_MAX_BYTES = 256 * 1024 * 1024
KIND_BY_DIR = {co.D_EXTRACT: "EXTRACT", co.D_TSTAR: "TSTAR", co.D_BC: "SUPPORT", co.D_ESL: "ESL",
               co.D_VAL: "VALIDATION", co.D_EXPORT: "EXPORT", co.D_REPORT: "REPORT"}


class RegisterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _sha(path: str) -> str | None:
    if os.path.getsize(path) > SHA_MAX_BYTES:
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def register_artifacts(conn: Connection, case_id: str, job_id: str, cdir: str, rels: list[str]) -> int:
    """폴더(재귀, `_backup` 제외) 또는 파일 상대경로 목록을 artifacts 에 upsert."""
    n = 0
    for rel in rels:
        base = os.path.join(cdir, rel)
        if os.path.isfile(base):
            files = [rel]
        elif os.path.isdir(base):
            files = []
            for root, dirs, names in os.walk(base):
                dirs[:] = [d for d in dirs if d != "_backup"]
                for name in names:
                    files.append(os.path.relpath(os.path.join(root, name), cdir))
        else:
            continue
        for f in sorted(files):
            p = os.path.join(cdir, f)
            if os.path.islink(p) or not os.path.isfile(p) or f.endswith(".tmp"):
                continue
            top = f.replace("\\", "/").split("/")[0]
            kind = KIND_BY_DIR.get(top) or ("LOG" if top == "logs" else "RUN" if f == co.RUN_JSON else "CASE")
            cases_repo.upsert_artifact(conn, case_id=case_id, job_id=job_id, kind=kind, rel=f.replace("\\", "/"),
                                       size=os.path.getsize(p), sha256=_sha(p))
            n += 1
    return n


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _need(fn, *args):
    try:
        return fn(*args)
    except co.OutputMissing as exc:
        raise RegisterError("TOOL_OUTPUT_MISSING", f"코어 산출물이 없습니다: {exc.rel}") from None
    except (OSError, ValueError, KeyError) as exc:
        raise RegisterError("OUTPUT_INVALID", f"코어 산출물을 읽을 수 없습니다: {exc}") from None


# ---------------------------------------------------------------- ① 추출 + t*
def register_extract(conn: Connection, job: dict[str, Any], case: dict[str, Any], cdir: str) -> dict[str, Any]:
    ex = co.stage_record(cdir, "extract")
    if ex.get("status") != "done":
        raise RegisterError("TOOL_OUTPUT_MISSING", "run.json 에 extract 완료 기록이 없습니다")
    s = dict(ex.get("summary") or {})
    info = _need(co.tstar_info, cdir)
    metric = info["default_metric"]
    blk = info["metrics"].get(metric) if metric else None
    if not blk or not blk.get("tstar"):
        raise RegisterError("OUTPUT_INVALID", "tstar.json 에 t* 가 없습니다")
    ts = blk["tstar"]
    tstar = {"metric": metric, "frame_index": ts["frame_index"], "time": ts["time"], "elem_id": ts["elem_id"],
             "value": ts["value"], "source": "auto"}
    tsr = co.stage_record(cdir, "tstar")
    summary = {
        "job_id": job["id"], "requested_part_title": (job["params"] or {}).get("part_title", case["part_title"]),
        "part_id": s.get("part_id"), "part_title": s.get("part_title"), "units_label": s.get("units_label"),
        "n_nodes": s.get("n_nodes"), "n_elems": s.get("n_elems"), "n_quad": s.get("n_quad"),
        "n_tria": s.get("n_tria"), "n_frames": s.get("n_frames"), "mats": s.get("mats") or [],
        "disp_frames": co.disp_frames(cdir), "metrics": sorted(info["metrics"]),
        "warnings": list(ex.get("warnings") or []) + list(tsr.get("warnings") or []),
    }
    vals: dict[str, Any] = {"extract_summary": summary, "tstar": tstar, "current_esl_run_id": None}
    if s.get("part_id") is not None:
        vals["part_id"] = int(s["part_id"])
    # 이전 지지점 세트는 노드가 모두 남아 있을 때만 유지
    if case.get("current_support_set_id"):
        sup = cases_repo.get_support_set(conn, case["current_support_set_id"])
        try:
            nid, _ = co.model_nodes(cdir)
            keep = sup is not None and all(int(n) in set(nid.tolist()) for n in sup["node_ids"])
        except (co.OutputMissing, OSError, ValueError, KeyError):
            keep = False
        if not keep:
            vals["current_support_set_id"] = None
    cases_repo.update_case(conn, case["id"], None, **vals)
    return {"extract": summary, "tstar": tstar}


def _lineage(conn: Connection, job: dict[str, Any]) -> set[str]:
    """작업 id + 재시도 원본들(retry_of_job_id 사슬). 코어 단계가 원본 작업에서 끝나고 등록만 재시도한 경우."""
    from esl_platform.core.repositories import jobs as jobs_repo

    out, cur = set(), job
    while cur is not None and cur["id"] not in out and len(out) < 50:
        out.add(cur["id"])
        cur = jobs_repo.get_job(conn, cur["retry_of_job_id"]) if cur.get("retry_of_job_id") else None
    return out


# ---------------------------------------------------------------- ④ ESL
def register_esl(conn: Connection, job: dict[str, Any], case: dict[str, Any], cdir: str) -> dict[str, Any]:
    p = job["params"] or {}
    summ = _need(co.esl_summary, cdir)
    if summ.get("tag") not in _lineage(conn, job):
        raise RegisterError("OUTPUT_INVALID", f"04_esl/esl_summary.json 이 이 작업의 결과가 아닙니다(tag={summ.get('tag')})")
    rec = co.stage_record(cdir, "esl")
    k = summ.get("kabsch") or {}
    fo = summ.get("forces") or {}
    noise = summ.get("noise") or {}
    fz = _need(co.f_eq, cdir)
    nid, x0 = _need(co.model_nodes, cdir)
    F = np.asarray(fz["f"], np.float64)
    ctr = np.asarray(fo.get("moment_center") or x0.mean(axis=0), np.float64)
    sum_m = np.cross(x0 - ctr, F).sum(axis=0) if F.shape == x0.shape else None
    kabsch = {"rot_deg": _f(k.get("rot_deg")), "rms_def": _f(k.get("rms_def")), "max_def": _f(k.get("max_def"))}
    forces = {
        "n_nodes_loaded": fo.get("n_nodes_nonzero", fo.get("n_nodes_loaded")),
        "sum_f": fo.get("sum_f"), "sum_m": None if sum_m is None else sum_m.tolist(),
        "sum_abs_f": _f(fo.get("sum_abs_f")),
        "equilibrium_rel": _f(fo.get("equilibrium_rel")), "moment_rel": _f(fo.get("moment_rel")),
        "max_f": fo.get("max_f"),
        "noise": {"force_rel": _f(noise.get("force_rel")), "hotspot_strain_rel": _f(noise.get("hotspot_strain_rel")),
                  "disp_precision": noise.get("disp_precision")},
    }
    supports = [{"node_id": int(s["node_id"]), "dof": str(s.get("dof"))} for s in (summ.get("supports") or [])]
    warnings = list(rec.get("warnings") or [])
    want = sorted(int(n) for n in (p.get("support_node_ids") or []))
    if want and sorted(s["node_id"] for s in supports) != want:
        warnings.append(f"코어 3-2-1 노드 {[s['node_id'] for s in supports]} 가 지지점 세트 {want} 와 다릅니다")
    fr = summ.get("frame") or {}
    rid = str(uuid.uuid4())
    try:
        snap_rel = esl_snapshot.save(cdir, rid)
    except OSError as exc:
        raise RegisterError("OUTPUT_INVALID", f"ESL 산출물 스냅샷 실패: {exc}") from None
    run = cases_repo.insert_esl_run(
        conn, id=rid, case_id=case["id"], job_id=job["id"], frame_index=int(fr.get("frame_index", p.get("frame_index"))),
        time=_f(fr.get("time")), metric=p.get("metric") or "max_strain", support_set_id=p["support_set_id"],
        kabsch=kabsch, forces=forces, supports=supports, warnings=warnings, dir_rel=snap_rel, status="READY",
        inputs_hash=p["inputs_hash"],
    )
    cases_repo.update_case(conn, case["id"], None, current_esl_run_id=run["id"])
    return {"esl_run_id": run["id"], "kabsch": kabsch, "forces": forces}


# ---------------------------------------------------------------- ⑤ 검증
def register_validation(conn: Connection, job: dict[str, Any], case: dict[str, Any], cdir: str) -> dict[str, Any]:
    p = job["params"] or {}
    val = _need(co.validation_json, cdir)
    run = cases_repo.get_esl_run(conn, p["esl_run_id"])
    ref = val.get("esl_ref")
    if run is None or (ref is not None and co.esl_tag(cdir) is not None and ref != run["job_id"]):
        raise RegisterError("OUTPUT_INVALID", "validation.json 이 대상 ESL 결과의 검증이 아닙니다")
    hots = []
    for h in val.get("hotspots") or []:
        hots.append({"elem_id": h.get("elem_id"), "eps_rad": _f(h.get("eps_rad")),
                     "eps_val": _f(h.get("eps_val", h.get("eps_os"))), "rel_err": _f(h.get("rel_err")),
                     "rank": h.get("rank")})
    # 코어 validation.json 키는 hotspots_excluded(이전 형식 excluded 도 허용)
    excluded = [{"elem_id": e.get("elem_id"), "reason": e.get("reason")}
                for e in (val.get("hotspots_excluded") or val.get("excluded") or []) if isinstance(e, dict)]
    verdict = val.get("verdict")
    if verdict not in ("PASS", "FAIL"):
        raise RegisterError("OUTPUT_INVALID", f"validation.json verdict 오류: {verdict}")
    disp = co.metric_value(val, "disp_rms_rel")
    reac = co.metric_value(val, "reaction_rel")
    fld = val.get("field") if isinstance(val.get("field"), dict) else None
    v = cases_repo.insert_validation(
        conn, esl_run_id=p["esl_run_id"], case_id=case["id"], job_id=job["id"], disp_rms_rel=disp,
        reaction_rel=reac, hotspots=hots, excluded=excluded, verdict=verdict,
        fail_reasons=list(val.get("fail_reasons") or []), criteria=dict(val.get("criteria") or {}),
        field=_jsonable(fld) if fld is not None else None, dir_rel=co.D_VAL,
    )
    # 이 실행의 검증 스냅샷 runs/<esl_run_id>/05_val (라이브러리 등록·겹쳐보기 API 가 이후 검증과 무관하게 읽음)
    if os.path.isdir(co.run_snapshot_dir(cdir, run["id"])):
        try:
            esl_snapshot.save_validation(cdir, run["id"], v["id"])
        except OSError as exc:
            raise RegisterError("OUTPUT_INVALID", f"검증 산출물 스냅샷 실패: {exc}") from None
    return {"validation_id": v["id"], "verdict": verdict, "disp_rms_rel": disp, "reaction_rel": reac}


# ---------------------------------------------------------------- ⑥ 내보내기
def register_export(conn: Connection, job: dict[str, Any], case: dict[str, Any], cdir: str) -> dict[str, Any]:
    rec = co.stage_record(cdir, "export")
    s = rec.get("summary") or {}
    run = cases_repo.get_esl_run(conn, (job["params"] or {}).get("esl_run_id"))
    ref = s.get("esl_ref")
    if run is None or (ref is not None and co.esl_tag(cdir) is not None and ref != run["job_id"]):
        raise RegisterError("OUTPUT_INVALID", "06_export 가 대상 ESL 결과의 내보내기가 아닙니다")
    files = list(s.get("files") or [])
    if not files:
        d = os.path.join(cdir, co.D_EXPORT)
        files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    if not files:
        raise RegisterError("TOOL_OUTPUT_MISSING", "06_export 에 파일이 없습니다")
    return {"export_dir": co.D_EXPORT, "files": files, "targets": s.get("targets") or (job["params"] or {}).get("targets"),
            "validation_used": s.get("validation_used"),
            "id_range": s.get("id_range"), "validation_verdict": (job["params"] or {}).get("validation_verdict"),
            "warnings": list(rec.get("warnings") or [])}


# ---------------------------------------------------------------- Case 보고서(P2)
def register_case_report(conn: Connection, job: dict[str, Any], case: dict[str, Any], cdir: str) -> dict[str, Any]:
    rel = f"{co.D_REPORT}/{co.REPORT_HTML}"
    path = os.path.join(cdir, co.D_REPORT, co.REPORT_HTML)
    if not os.path.isfile(path) or os.path.islink(path):
        raise RegisterError("TOOL_OUTPUT_MISSING", f"보고서가 없습니다: {rel}")
    s = co.stage_record(cdir, "report").get("summary") or {}
    p = job["params"] or {}
    return {"report_rel": rel, "bytes": os.path.getsize(path), "verdict": s.get("verdict"),
            "validation_id": p.get("validation_id"), "esl_run_id": p.get("esl_run_id"), "auto": bool(p.get("auto")),
            "missing": s.get("missing") or []}


# ---------------------------------------------------------------- 라이브러리 종합분석(P2)
def _analysis_summary(res: dict[str, Any], opt: dict[str, Any] | None) -> dict[str, Any]:
    cases = res.get("cases") or []
    svd = res.get("svd") or {}
    r = int(svd.get("n_modes") or 0)
    cum = svd.get("cum_energy") or []
    def eid(k):
        return cases[k]["entry_id"] if 0 <= k < len(cases) else None
    groups = {}
    for key, g in ((res.get("stats") or {}).get("groups") or {}).items():
        groups[key] = {v: {"n": x.get("n"), "sum_abs_f": x.get("sum_abs_f")} for v, x in g.items()}
    out = {
        "n_cases": res.get("n_cases"), "grid": res.get("grid"),
        "target": None if not res.get("target") else {"entry_id": res["target"].get("entry_id"),
                                                       "model": res["target"].get("model")},
        "svd": {"n_modes": r, "threshold": svd.get("threshold"), "feature": svd.get("feature"),
                "cum_energy_at_r": cum[r - 1] if 0 < r <= len(cum) else None, "energy": (svd.get("energy") or [])[:20]},
        "load_cases": [{k: lc.get(k) for k in ("label", "role", "cluster", "entry_id", "case_index")}
                       for lc in res.get("load_cases") or []],
        "clusters": [{"id": c.get("id"), "size": c.get("size"), "medoid_entry": c.get("medoid_entry"),
                      "worst_entry": c.get("worst_entry"), "mean_dist": c.get("mean_dist"),
                      "members": [eid(m) for m in c.get("members") or []]} for c in res.get("clusters") or []],
        "envelope": res.get("envelope"), "mapping": res.get("mapping"),
        "stats": {"groups": groups, "verification_summary": (res.get("stats") or {}).get("verification_summary")},
        "cases": [{k: c.get(k) for k in ("index", "entry_id", "product", "inch", "drop_class", "orient", "scene",
                                          "scenario", "verdict", "cluster", "is_medoid", "is_worst", "sum_abs_f",
                                          "scale_factor", "svd_coef")} for c in cases],
        "warnings": list(res.get("warnings") or []),
        "optdeck": None,
        "deck": _deck_summary(res),
    }
    if opt:
        out["optdeck"] = {k: opt.get(k) for k in ("deck", "files", "objective", "n_subcases", "n_design_elems",
                                                  "n_nondesign_elems", "card_format", "reference_compliance")}
    return out


def _deck_summary(res: dict[str, Any]) -> dict[str, Any] | None:
    """덱 하중 구성(§12.1): 설정·적용 모드, subcase 수, 자동 축소 여부, 제외 씬(사유)."""
    d = res.get("deck")
    if not d:
        return None
    return {"requested": d.get("requested"), "mode": d.get("mode"), "reduced": bool(d.get("reduced")),
            "max_cases": d.get("max_cases"), "n_cases": d.get("n_cases"), "n_subcases": d.get("n_subcases"),
            "n_excluded": len(d.get("excluded") or []),
            "excluded": [{k: x.get(k) for k in ("entry_id", "scene", "reason")} for x in (d.get("excluded") or [])]}


def register_lib_analyze(conn: Connection, job: dict[str, Any], case: Any, adir: str) -> dict[str, Any]:
    from esl_platform.core.repositories import library as lib_repo

    an = lib_repo.get_analysis(conn, job["analysis_id"], for_update=True)
    if an is None:
        raise RegisterError("ANALYSIS_NOT_FOUND", "분석 행이 없습니다")
    try:
        res = co.read_json(os.path.join(adir, "analysis.json"))
    except (OSError, ValueError) as exc:
        raise RegisterError("TOOL_OUTPUT_MISSING", f"analysis.json 을 읽을 수 없습니다: {exc}") from None
    if res.get("analysis_id") not in (None, an["id"]):
        raise RegisterError("OUTPUT_INVALID", f"analysis.json 이 이 분석의 것이 아닙니다({res.get('analysis_id')})")
    opt = None
    op = os.path.join(adir, "opt", "optdeck.json")
    if os.path.isfile(op):
        try:
            opt = co.read_json(op)
        except (OSError, ValueError):
            opt = None
    base = an["dir_rel"]
    summary = _jsonable(_analysis_summary(res, opt))
    lib_repo.update_analysis(
        conn, an["id"], result=summary, result_rel=f"{base}/analysis.json",
        report_rel=f"{base}/report.html" if os.path.isfile(os.path.join(adir, "report.html")) else None,
        optdeck_rel=f"{base}/opt" if opt is not None else None)
    return {"analysis_id": an["id"], "n_cases": summary["n_cases"],
            "load_cases": [lc["entry_id"] for lc in summary["load_cases"]], "optdeck": opt is not None}


# ---------------------------------------------------------------- 설계 버전 비교(P2 §12.2)
def _compare_summary(res: dict[str, Any]) -> dict[str, Any]:
    reps = res.get("representatives") or {}
    return {
        "convergence": res.get("convergence"), "aggregate": res.get("aggregate"), "criteria": res.get("criteria"),
        "resolution": res.get("resolution"),
        "n_base": res.get("n_base"), "n_new": res.get("n_new"), "n_paired": res.get("n_paired"),
        "representatives": {k: reps.get(k) for k in ("k", "rep_same", "rep_basis", "medoid_id_same", "partition_same",
                                                      "partition_agreement", "base_reps_cost_excess", "matching")},
        "scenes": [{k: s.get(k) for k in ("label", "base_entry", "new_entry", "cos", "force_ratio", "hotspot_shift",
                                          "eps_ratio", "quality_base", "quality_new", "changed", "reasons")}
                   for s in res.get("scenes") or []],
        "unpaired": res.get("unpaired"), "warnings": list(res.get("warnings") or []),
    }


def register_lib_compare(conn: Connection, job: dict[str, Any], case: Any, cdir: str) -> dict[str, Any]:
    from esl_platform.core.repositories import library as lib_repo

    c = lib_repo.get_comparison(conn, job["comparison_id"], for_update=True)
    if c is None:
        raise RegisterError("COMPARISON_NOT_FOUND", "비교 행이 없습니다")
    try:
        res = co.read_json(os.path.join(cdir, "compare.json"))
    except (OSError, ValueError) as exc:
        raise RegisterError("TOOL_OUTPUT_MISSING", f"compare.json 을 읽을 수 없습니다: {exc}") from None
    if res.get("comparison_id") not in (None, c["id"]):
        raise RegisterError("OUTPUT_INVALID", f"compare.json 이 이 비교의 것이 아닙니다({res.get('comparison_id')})")
    verdict = (res.get("convergence") or {}).get("verdict")
    if verdict not in ("CONVERGED", "ITERATE"):
        raise RegisterError("OUTPUT_INVALID", f"compare.json 판정이 없습니다({verdict})")
    base = c["dir_rel"]
    summary = _jsonable(_compare_summary(res))
    lib_repo.update_comparison(
        conn, c["id"], verdict=verdict, result=summary, result_rel=f"{base}/compare.json",
        report_rel=f"{base}/report.html" if os.path.isfile(os.path.join(cdir, "report.html")) else None)
    return {"comparison_id": c["id"], "verdict": verdict, "n_paired": res.get("n_paired"),
            "cos_min": (res.get("aggregate") or {}).get("cos_min")}


def _jsonable(o: Any) -> Any:
    import json

    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x)))


REGISTER = {"CASE_EXTRACT": register_extract, "ESL_SOLVE": register_esl, "VALIDATE": register_validation,
            "EXPORT": register_export, "CASE_REPORT": register_case_report, "LIB_ANALYZE": register_lib_analyze,
            "LIB_COMPARE": register_lib_compare}
