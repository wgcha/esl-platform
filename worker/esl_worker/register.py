"""코어 산출물 → DB 요약 등록(계약 esl_platform_p1b.md §2·§3). 대용량 배열은 DB에 넣지 않는다.

각 함수는 lease 를 확인한 트랜잭션 안에서 호출된다(호출자 executor).
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import numpy as np
from sqlalchemy.engine import Connection

from esl_platform.core import core_outputs as co
from esl_platform.core.repositories import cases as cases_repo

SHA_MAX_BYTES = 256 * 1024 * 1024
KIND_BY_DIR = {co.D_EXTRACT: "EXTRACT", co.D_TSTAR: "TSTAR", co.D_BC: "SUPPORT", co.D_ESL: "ESL",
               co.D_VAL: "VALIDATION", co.D_EXPORT: "EXPORT"}


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


# ---------------------------------------------------------------- ④ ESL
def register_esl(conn: Connection, job: dict[str, Any], case: dict[str, Any], cdir: str) -> dict[str, Any]:
    p = job["params"] or {}
    summ = _need(co.esl_summary, cdir)
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
    run = cases_repo.insert_esl_run(
        conn, case_id=case["id"], job_id=job["id"], frame_index=int(fr.get("frame_index", p.get("frame_index"))),
        time=_f(fr.get("time")), metric=p.get("metric") or "max_strain", support_set_id=p["support_set_id"],
        kabsch=kabsch, forces=forces, supports=supports, warnings=warnings, dir_rel=co.D_ESL, status="READY",
        inputs_hash=p["inputs_hash"],
    )
    cases_repo.update_case(conn, case["id"], None, current_esl_run_id=run["id"])
    return {"esl_run_id": run["id"], "kabsch": kabsch, "forces": forces}


# ---------------------------------------------------------------- ⑤ 검증
def register_validation(conn: Connection, job: dict[str, Any], case: dict[str, Any], cdir: str) -> dict[str, Any]:
    p = job["params"] or {}
    val = _need(co.validation_json, cdir)
    hots = []
    for h in val.get("hotspots") or []:
        hots.append({"elem_id": h.get("elem_id"), "eps_rad": _f(h.get("eps_rad")),
                     "eps_val": _f(h.get("eps_val", h.get("eps_os"))), "rel_err": _f(h.get("rel_err")),
                     "rank": h.get("rank")})
    excluded = [{"elem_id": e.get("elem_id"), "reason": e.get("reason")} for e in (val.get("excluded") or [])
                if isinstance(e, dict)]
    verdict = val.get("verdict")
    if verdict not in ("PASS", "FAIL"):
        raise RegisterError("OUTPUT_INVALID", f"validation.json verdict 오류: {verdict}")
    disp = co.metric_value(val, "disp_rms_rel")
    reac = co.metric_value(val, "reaction_rel")
    v = cases_repo.insert_validation(
        conn, esl_run_id=p["esl_run_id"], case_id=case["id"], job_id=job["id"], disp_rms_rel=disp,
        reaction_rel=reac, hotspots=hots, excluded=excluded, verdict=verdict,
        fail_reasons=list(val.get("fail_reasons") or []), criteria=dict(val.get("criteria") or {}),
        dir_rel=co.D_VAL,
    )
    return {"validation_id": v["id"], "verdict": verdict, "disp_rms_rel": disp, "reaction_rel": reac}


# ---------------------------------------------------------------- ⑥ 내보내기
def register_export(conn: Connection, job: dict[str, Any], case: dict[str, Any], cdir: str) -> dict[str, Any]:
    rec = co.stage_record(cdir, "export")
    s = rec.get("summary") or {}
    files = list(s.get("files") or [])
    if not files:
        d = os.path.join(cdir, co.D_EXPORT)
        files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    if not files:
        raise RegisterError("TOOL_OUTPUT_MISSING", "06_export 에 파일이 없습니다")
    return {"export_dir": co.D_EXPORT, "files": files, "targets": (job["params"] or {}).get("targets"),
            "id_range": s.get("id_range"), "validation_verdict": (job["params"] or {}).get("validation_verdict"),
            "warnings": list(rec.get("warnings") or [])}


REGISTER = {"CASE_EXTRACT": register_extract, "ESL_SOLVE": register_esl, "VALIDATE": register_validation,
            "EXPORT": register_export}
