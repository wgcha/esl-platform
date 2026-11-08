"""코어 산출물 → DB 요약 등록(계약 esl_platform_p1b.md §2·§3). 대용량 배열은 DB에 넣지 않는다.

각 함수는 lease 를 확인한 트랜잭션 안에서 호출된다(호출자 executor).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from typing import Any

import numpy as np
from sqlalchemy.engine import Connection

from esl_platform.core import core_outputs as co
from esl_platform.core.atomic import atomic_replace
from esl_platform.core.repositories import cases as cases_repo

from . import esl_snapshot

VERDICT_SCHEMES = ("disp_primary/1",)       # validations.scheme 허용값(migration 0008 ck_validations_scheme)
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


def _artifact_files(cdir: str, rels: list[str]) -> list[tuple[str, str]]:
    """폴더(재귀, `_backup` 제외) 또는 파일 상대경로 목록 → [(rel, 절대경로)] (링크·.tmp 제외, 정렬)."""
    out: list[tuple[str, str]] = []
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
            out.append((f, p))
    return out


def _stat_key(p: str) -> tuple[int, int]:
    st = os.stat(p)
    return st.st_size, st.st_mtime_ns


def artifact_shas(cdir: str, rels: list[str]) -> dict[str, tuple[tuple[int, int], str | None]]:
    """v0.12.3: register_artifacts 의 sha256 을 DB 트랜잭션 밖에서 미리(inproc 작업 스레드) — {rel: ((size, mtime), sha)}."""
    out: dict[str, tuple[tuple[int, int], str | None]] = {}
    for f, p in _artifact_files(cdir, rels):
        try:
            k = _stat_key(p)
            out[f] = (k, _sha(p))
        except OSError:
            continue
    return out


def register_artifacts(conn: Connection, case_id: str, job_id: str, cdir: str, rels: list[str],
                       shas: dict[str, tuple[tuple[int, int], str | None]] | None = None) -> int:
    """폴더(재귀, `_backup` 제외) 또는 파일 상대경로 목록을 artifacts 에 upsert. shas = artifact_shas() 결과
    (크기·mtime 이 같을 때만 그 값, 아니면 여기서 다시 계산)."""
    n = 0
    for f, p in _artifact_files(cdir, rels):
        top = f.replace("\\", "/").split("/")[0]
        kind = KIND_BY_DIR.get(top) or ("LOG" if top == "logs" else "RUN" if f == co.RUN_JSON else "CASE")
        pre = (shas or {}).get(f)
        sha = pre[1] if pre is not None and pre[0] == _stat_key(p) else _sha(p)
        cases_repo.upsert_artifact(conn, case_id=case_id, job_id=job_id, kind=kind, rel=f.replace("\\", "/"),
                                   size=os.path.getsize(p), sha256=sha)
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
    # 변형률 source(esl_strain_fallback.md §5) — 옛 코어 결과는 키 없음(= max_strain)
    summary["strain_source"] = s.get("strain_source")
    if s.get("cumulative"):                 # 누적 씬만(비누적 Case 는 키 없음 — esl_cumulative_input.md §13)
        summary["cumulative"] = s["cumulative"]
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
    if verdict not in ("PASS", "FAIL", "UNDETERMINED"):
        raise RegisterError("OUTPUT_INVALID", f"validation.json verdict 오류: {verdict}")
    # 계약 esl_disp_primary.md §7: verdict_scheme 이 있으면 scheme 에 저장, 없으면(schema 2) NULL = LEGACY
    scheme = val.get("verdict_scheme") or None
    if scheme is not None and scheme not in VERDICT_SCHEMES:
        raise RegisterError("OUTPUT_INVALID", f"validation.json verdict_scheme 오류: {scheme}")
    reason = val.get("undetermined_reason") or None
    if verdict == "UNDETERMINED" and (scheme is None or reason is None):
        raise RegisterError("OUTPUT_INVALID", "UNDETERMINED 판정에는 verdict_scheme·undetermined_reason 이 필요합니다")
    disp = co.metric_value(val, "disp_rms_rel")
    reac = co.metric_value(val, "reaction_rel")
    disp_max = co.metric_value(val, "disp_max_rel")
    disp_noise = co.metric_value(val, "disp_noise_rel")
    fld = val.get("field") if isinstance(val.get("field"), dict) else None
    dsp = val.get("disp") if isinstance(val.get("disp"), dict) else None
    sref = val.get("strain_ref") if isinstance(val.get("strain_ref"), dict) else None
    v = cases_repo.insert_validation(
        conn, esl_run_id=p["esl_run_id"], case_id=case["id"], job_id=job["id"], disp_rms_rel=disp,
        reaction_rel=reac, hotspots=hots, excluded=excluded, verdict=verdict,
        fail_reasons=list(val.get("fail_reasons") or []), criteria=dict(val.get("criteria") or {}),
        field=_jsonable(fld) if fld is not None else None, dir_rel=co.D_VAL,
        scheme=scheme, disp_max_rel=disp_max, disp_noise_rel=disp_noise, undetermined_reason=reason,
        disp=_jsonable(dsp) if dsp is not None else None, strain_ref=_jsonable(sref) if sref is not None else None,
    )
    # 이 실행의 검증 스냅샷 runs/<esl_run_id>/05_val (라이브러리 등록·겹쳐보기 API 가 이후 검증과 무관하게 읽음)
    if os.path.isdir(co.run_snapshot_dir(cdir, run["id"])):
        try:
            esl_snapshot.save_validation(cdir, run["id"], v["id"])
        except OSError as exc:
            raise RegisterError("OUTPUT_INVALID", f"검증 산출물 스냅샷 실패: {exc}") from None
    out = {"validation_id": v["id"], "verdict": verdict, "status": verdict if scheme else "LEGACY",
           "disp_rms_rel": disp, "disp_max_rel": disp_max, "disp_noise_rel": disp_noise, "reaction_rel": reac,
           "undetermined_reason": reason}
    if p.get("origin") == "library_revalidate":
        out["revalidate"] = revalidate_transition(conn, job, v)
    return out


# ---------------------------------------------------------------- v0.10.0 재검증 전환(esl_menu_restructure.md §7.4)
QUALITY_FROM_VALIDATION = ("verdict", "status", "scheme", "undetermined_reason", "disp_rms_rel", "disp_max_rel",
                           "disp_noise_rel", "reaction_rel", "strain_exceed_frac", "fail_reasons", "field_max_err_pct",
                           "field_p90_err_pct")


def _quality_from(v: dict[str, Any]) -> dict[str, Any]:
    fld = v.get("field") if isinstance(v.get("field"), dict) else {}
    fmax = (fld.get("max") or {}).get("abs_err_pct") if isinstance(fld.get("max"), dict) else None
    fp90 = (fld.get("abs_err_pct") or {}).get("p90") if isinstance(fld.get("abs_err_pct"), dict) else None
    sref = v.get("strain_ref") if isinstance(v.get("strain_ref"), dict) else {}
    return {"verdict": v["verdict"], "status": v["verdict"] if v.get("scheme") else "LEGACY", "scheme": v.get("scheme"),
            "undetermined_reason": v.get("undetermined_reason"), "disp_rms_rel": _f(v.get("disp_rms_rel")),
            "disp_max_rel": _f(v.get("disp_max_rel")), "disp_noise_rel": _f(v.get("disp_noise_rel")),
            "reaction_rel": _f(v.get("reaction_rel")), "strain_exceed_frac": _f(sref.get("frac_exceed")),
            "fail_reasons": list(v.get("fail_reasons") or []), "field_max_err_pct": _f(fmax),
            "field_p90_err_pct": _f(fp90)}


def revalidate_transition(conn: Connection, job: dict[str, Any], v: dict[str, Any]) -> dict[str, Any]:
    """새 검증 등록과 같은 트랜잭션: 항목이 아직 ACTIVE ∧ 같은 esl_run ∧ 새 판정 PASS(scheme 있음) → quality 판정 키·
    validation_id 갱신 + quality.revalidated, force_reason·confirmed_* = null, version+1(PROMOTED). FAIL·판정 불가 → 불변
    (KEPT_LEGACY). 항목이 그사이 폐기·변경 → 불변(ENTRY_CHANGED). 항목 폴더(entry.json·raw.npz)는 바꾸지 않는다."""
    import datetime as _dt

    from esl_platform.core.repositories import library as lib_repo

    p = job["params"] or {}
    eid = p.get("entry_id")
    status = v["verdict"] if v.get("scheme") else "LEGACY"
    base = {"entry_id": eid, "validation_id": v["id"], "status": status, "verdict": v["verdict"],
            "fail_reasons": list(v.get("fail_reasons") or [])}
    e = lib_repo.get_entry(conn, eid, for_update=True) if eid else None
    if e is None or e["status"] != "ACTIVE" or e["esl_run_id"] != p.get("esl_run_id"):
        return {**base, "outcome": "ENTRY_CHANGED"}
    if status != "PASS":
        return {**base, "outcome": "KEPT_LEGACY"}
    q = dict(e.get("quality") or {})
    old = q.get("status") or ("LEGACY" if not q.get("scheme") else q.get("verdict"))
    q.update(_quality_from(v))
    q["confirmed_fail"] = q["confirmed_undetermined"] = None
    q["revalidated"] = {"from_validation_id": e.get("validation_id"), "from_status": old, "job_id": job["id"],
                        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                        "by": job.get("created_by"), "by_name": job.get("created_by_name")}
    lib_repo.update_entry(conn, eid, None, validation_id=v["id"], quality=_jsonable(q), force_reason=None)
    return {**base, "outcome": "PROMOTED"}


# ---------------------------------------------------------------- ⑥ 내보내기
def register_lib_export(conn: Connection, job: dict[str, Any], cdir: str) -> dict[str, Any]:
    """v0.10.0 라이브러리 내보내기(§6.2 EXP_REGISTER): 항목 폴더 export.json → registered{batch_id, items}. 항목 전부 실패면
    작업 FAILED EXPORT_ALL_FAILED(첫 오류), 일부 실패는 SUCCEEDED + 경고. Case 행·artifacts 는 건드리지 않는다."""
    p = job["params"] or {}
    real = os.path.realpath(cdir)
    items, warns = [], []
    for it in p.get("items") or []:
        lab = str(it.get("label") or "")
        path = os.path.join(cdir, lab, "export.json")
        rec = None
        if lab and "/" not in lab and "\\" not in lab and not os.path.islink(path) and co.inside(os.path.realpath(path), real):
            try:
                rec = co.read_json(path)
            except (OSError, ValueError):
                rec = None
        if not isinstance(rec, dict):
            rec = {"ok": False, "error": {"code": "TOOL_OUTPUT_MISSING", "message": f"{lab}/export.json 이 없습니다"}}
        ok = bool(rec.get("ok"))
        items.append({"entry_id": it.get("entry_id"), "label": lab, "state": "DONE" if ok else "FAILED",
                      "files": list(rec.get("files") or []) if ok else [], "id_range": rec.get("id_range"),
                      "id_max_used": rec.get("id_max_used"), "warnings": [str(w) for w in rec.get("warnings") or []],
                      "error": None if ok else rec.get("error")})
    bad = [x for x in items if x["state"] != "DONE"]
    if items and len(bad) == len(items):
        e0 = bad[0]["error"] or {}
        raise RegisterError("EXPORT_ALL_FAILED", f"내보낼 항목이 모두 실패했습니다 — {bad[0]['label']}: "
                            f"{e0.get('code')}: {e0.get('message')}"[:450])
    for x in bad:
        e0 = x["error"] or {}
        warns.append(f"내보내기 항목 실패 {x['label']}: {e0.get('code')}: {e0.get('message')}"[:300])
    return {"origin": "library", "batch_id": p.get("batch_id"), "targets": p.get("targets"), "n_items": len(items),
            "n_done": len(items) - len(bad), "items": items, "warnings_job": warns}


def register_export(conn: Connection, job: dict[str, Any], case: dict[str, Any], cdir: str) -> dict[str, Any]:
    if (job.get("params") or {}).get("origin") == "library":
        return register_lib_export(conn, job, cdir)
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


# ---------------------------------------------------------------- 실행 이력 보존(계약 esl_p3_history.md H-5)
def archive_history(cdir: str, job_type: str, job_id: str) -> int:
    """EXPORT 의 ``06_export`` 또는 CASE_REPORT 의 ``07_report/report.html`` 을 ``<case>/history/<job_id>/`` 로 **복사**한다.

    심링크는 복사하지 않고, ``.tmp`` 에 쓴 뒤 rename(중간 상태를 남기지 않음). 이미 있으면(같은 작업의 재호출) 그대로 둔다.
    복사한 파일 수를 돌려준다. 실패하면 OSError(호출자가 작업을 성공으로 두고 경고 ``HISTORY_ARCHIVE_FAILED`` 기록).
    """
    if job_type not in ("EXPORT", "CASE_REPORT"):
        return 0
    real_case = os.path.realpath(cdir)
    hdir = os.path.join(cdir, co.HISTORY_DIR)
    dst = os.path.join(hdir, job_id)
    if os.path.islink(hdir) or not co.inside(os.path.realpath(dst), real_case):
        raise OSError("history 폴더가 Case 폴더 밖이거나 심볼릭 링크입니다")
    if os.path.lexists(dst):
        return 0
    if job_type == "EXPORT":
        src = os.path.join(cdir, co.D_EXPORT)
        if os.path.islink(src) or not os.path.isdir(src):
            raise FileNotFoundError(src)
    else:
        src = os.path.join(cdir, co.D_REPORT, co.REPORT_HTML)
        if os.path.islink(src) or not os.path.isfile(src):
            raise FileNotFoundError(src)
    tmp = dst + ".tmp"
    if os.path.lexists(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    n = 0
    try:
        if job_type == "EXPORT":
            shutil.copytree(src, os.path.join(tmp, co.HISTORY_EXPORT), symlinks=True, copy_function=shutil.copy2,
                            ignore=lambda d, names: [x for x in names if os.path.islink(os.path.join(d, x))])
            n = sum(len(fs) for _r, _d, fs in os.walk(os.path.join(tmp, co.HISTORY_EXPORT)))
        else:
            shutil.copy2(src, os.path.join(tmp, co.HISTORY_REPORT))
            n = 1
        atomic_replace(tmp, dst)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return n


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


# ---------------------------------------------------------------- 비드 최적화(v0.7.0, esl_opt_run.md §6.2 OR-6)
OPT_RESULT_FILES = ("opt.json", "report.html", "post/bead.npz", "post/bead_nodes.csv", "post/bead_map.png",
                    "post/history.csv", "post/bead_mesh.rad", "post/bead_mesh.fem", "load/selection.json",
                    "target/keepout.png")


def opt_files(rdir: str) -> list[dict[str, Any]]:
    """결과 파일 목록(실행 폴더 기준 '/' 상대경로, _backup·solve/tmp 제외): 주요 결과 + deck/* + solve 원본(.out·h3d·hist·stat)."""
    out = []
    rels = list(OPT_RESULT_FILES)
    for sub, keep in (("deck", None), ("solve", (".out", ".h3d", ".hist", ".stat", ".json"))):
        d = os.path.join(rdir, sub)
        if os.path.isdir(d):
            for n in sorted(os.listdir(d)):
                p = os.path.join(d, n)
                if os.path.isfile(p) and not os.path.islink(p) and (keep is None or n.endswith(keep)):
                    rels.append(f"{sub}/{n}")
    for rel in rels:
        p = os.path.join(rdir, *rel.split("/"))
        if os.path.isfile(p) and not os.path.islink(p):
            out.append({"rel": rel, "size": os.path.getsize(p)})
    return out


def register_opt_run(conn: Connection, job: dict[str, Any], case: Any, rdir: str) -> dict[str, Any]:
    """OPT_REGISTER: opt.json(OptResult) + 결과 파일 목록 → opt_runs.result, report_rel. artifacts 는 쓰지 않는다
    (artifacts.case_id NOT NULL — 결과는 <esl_root>/_opt/<id>/ 파일, 백엔드 /opt/runs/{id}/files·download·bundle·report·
    bead-map.png 가 같은 위치를 읽는다). 라이브러리 반영 없음(확정 7)."""
    from esl_platform.core.repositories import opt as opt_repo

    r = opt_repo.get_run(conn, job["opt_run_id"], for_update=True)
    if r is None:
        raise RegisterError("OPT_RUN_NOT_FOUND", "최적화 실행 행이 없습니다")
    try:
        res = co.read_json(os.path.join(rdir, "opt.json"))
    except (OSError, ValueError) as exc:
        raise RegisterError("TOOL_OUTPUT_MISSING", f"opt.json 을 읽을 수 없습니다: {exc}") from None
    if not isinstance(res, dict) or not isinstance(res.get("load_selection"), dict):
        raise RegisterError("OUTPUT_INVALID", "opt.json 에 하중 선정 결과가 없습니다")
    files = opt_files(rdir)
    res = {**res, "files": files, "job_id": job["id"]}
    has_report = os.path.isfile(os.path.join(rdir, "report.html"))
    opt_repo.update_run(conn, r["id"], result=_jsonable(res), report_rel="report.html" if has_report else None)
    # 작업 경고에는 후처리에서 새로 생긴 것만(미수렴·c0_tol·메시 쓰기) — 생성·OPT_PREP·OPT_LOAD 경고는 이미 올라감
    seen = set((job.get("params") or {}).get("warnings") or [])
    seen |= set((res.get("load_selection") or {}).get("warnings") or [])
    try:
        seen |= set(co.read_json(os.path.join(rdir, "target", "prep.json")).get("warnings") or [])
    except (OSError, ValueError):
        pass
    new = [str(w) for w in res.get("warnings") or [] if w not in seen]
    return {"opt_run_id": r["id"], "n_files": len(files), "converged": res.get("converged"),
            "iterations": res.get("iterations"), "report": has_report, "warnings": new}


# ---------------------------------------------------------------- v0.9.0 비드 DOE(계약 esl_bead_doe.md §4·§13)
# 등록 step 은 bead_does 만 갱신한다(repositories.doe.update_study — version +1). 작업이 실패·취소되면 이 step 에 오지
# 않으므로 phase 는 그대로다(백엔드가 최근 작업 상태로 phase 를 파생). artifacts 는 쓰지 않는다(case_id NOT NULL — 결과는
# <esl_root>/_doe/<id>/ 파일, 백엔드 /doe/studies/{id}/files·results·report 가 같은 위치를 읽음).
_CODE_RE = re.compile(r"^([A-Z][A-Z0-9_]{2,63})(?::\s*(.*))?$", re.S)


def _doe_json(path: str) -> Any:
    try:
        if os.path.islink(path) or os.path.getsize(path) > 64 * 1024 * 1024:
            return None
        return co.read_json(path)
    except (OSError, ValueError):
        return None


def _doe_warning(w: Any, messages: dict[str, str]) -> dict[str, Any] | None:
    """준비 경고 1개 → {code, message}. 문자열 'CODE: 문구'·'CODE'·자유 문구, dict{code, message, bead?} 모두 받음."""
    if isinstance(w, dict):
        code = str(w.get("code") or "PREP_WARNING")
        msg = w.get("message") or messages.get(code) or code
        if w.get("bead"):
            msg = f"{w['bead']}: {msg}"
        return {"code": code, "message": str(msg)[:300]}
    if w in (None, ""):
        return None
    s = str(w)
    m = _CODE_RE.match(s)
    if m:
        return {"code": m.group(1), "message": (m.group(2) or messages.get(m.group(1)) or m.group(1))[:300]}
    return {"code": "PREP_WARNING", "message": s[:300]}


def _study(conn: Connection, job: dict[str, Any]) -> dict[str, Any]:
    from esl_platform.core.repositories import doe as doe_repo

    s = doe_repo.get_study(conn, job["bead_doe_id"], for_update=True)
    if s is None:
        raise RegisterError("DOE_NOT_FOUND", "강성 평가 스터디 행이 없습니다")
    # phase 역행 금지: 연구가 이 작업 단계를 이미 지났으면(예 끝난 연구에 오래된 미리보기 결과) 등록하지 않는다
    order = {"PREP": 0, "READY": 1, "PREVIEW": 2, "PREVIEW_READY": 3, "RUN": 4, "DONE": 5}
    own = {"DOE_PREP": "PREP", "DOE_PREVIEW": "PREVIEW", "DOE_RUN": "RUN"}.get(job.get("job_type"))
    if own is not None and order.get(s.get("phase"), -1) > order[own]:
        raise RegisterError("DOE_PHASE_STALE", f"연구 단계({s.get('phase')})가 이 작업({job.get('job_type')})을 이미 지났습니다 — 등록하지 않습니다")
    return s


def register_doe_prep(conn: Connection, job: dict[str, Any], case: Any, ddir: str) -> dict[str, Any]:
    """BD_PREP_REGISTER: phase READY, prep = {n_beads, n_params, paicad_version, warnings[{code, message}],
    boundary{n_warn, n_info}|null}, paicad_version."""
    from esl_platform.core.repositories import doe as doe_repo

    from . import core_adapter

    s = _study(conn, job)
    if s.get("scenario") == "compare":
        return _register_compare_prep(conn, s, ddir)
    inp = _doe_json(os.path.join(ddir, "prep", "input.json"))
    params = _doe_json(os.path.join(ddir, "prep", "params.json"))
    if not isinstance(inp, dict) or not isinstance(params, dict):
        raise RegisterError("TOOL_OUTPUT_MISSING", "준비 결과(prep/input.json·params.json)가 없습니다")
    pv = _doe_json(os.path.join(ddir, "prep", "paicad.json")) or {}
    bnd = _doe_json(os.path.join(ddir, "prep", "boundary.json"))
    try:
        msgs = core_adapter.doe_messages().get("messages") or {}
    except core_adapter.CoreError:
        msgs = {}
    warns = []
    for w in list(params.get("warnings") or []) + list(inp.get("warnings") or []) + list(inp.get("info") or []) + (
            [pv["warning"]] if pv.get("warning") else []):
        x = _doe_warning(w, msgs)
        if x is not None and x not in warns:
            warns.append(x)
    prep = {"n_beads": len(params.get("beads") or []), "n_params": len(params.get("params") or []),
            "paicad_version": pv.get("version"), "warnings": warns,
            "boundary": None if not isinstance(bnd, dict) else {"n_warn": int(bnd.get("n_warn") or 0),
                                                                "n_info": int(bnd.get("n_info") or 0)}}
    if s.get("scenario") == "select":       # v0.15.0 BD_PREP_REGISTER select 요약(esl_bead_select.md §8.1 5)
        base = _doe_json(os.path.join(ddir, "prep", "base.json")) or {}
        fx = inp.get("fixed") if isinstance(inp.get("fixed"), dict) else {}
        prep.update(n_nodes=base.get("n_nodes"), n_elems=base.get("n_elems"),
                    fixed={"source": fx.get("source") or "none", "n": int(fx.get("n") or 0)})
        prep.update(_select_auto_prep(s, inp, ddir, msgs, warns))
    doe_repo.update_study(conn, s["id"], phase="READY", prep=_jsonable(prep), paicad_version=pv.get("version"))
    return {"bead_doe_id": s["id"], "phase": "READY", **{k: prep[k] for k in ("n_beads", "n_params", "paicad_version")}}


AUTO_DETECT_MSG = "자동 탐지(paicad {step})가 실패했습니다({detail}) — 빈 선택에서 수동으로 선택하세요"


def _select_auto_prep(s: dict[str, Any], inp: dict[str, Any], ddir: str, msgs: dict[str, str],
                      warns: list[dict[str, Any]]) -> dict[str, Any]:
    """v0.16.2 select 준비 요약 보강(esl_bead_auto.md AD-D-2·3·13): select_base(mesh 일 때만 — ① 요약 불변), auto 스터디는
    auto = {ok, step, code, available(prep/select/auto_selection.json 있음), n_beads, selection_sha256}. 출처 = 코어 BD_LOADS 의
    prep/input.json auto(탐지 → seed 결과), 없으면 워커 prep/auto_detect.json. 실패면 준비 경고
    {code: AUTO_DETECT_FAILED, message, step, detail}(detail = 안쪽 paicad·코어 코드 — 경고 자신의 code 와 겹치지 않게)를 한 번,
    코어 seed 경고(AUTO_* — info 제외)도 준비 경고에 더한다(warns 제자리)."""
    out: dict[str, Any] = {}
    inputs = s.get("inputs") or {}
    if inputs.get("select_base") == "mesh" or inp.get("select_base") == "mesh":
        out["select_base"] = "mesh"
    if inputs.get("bead_source") != "auto" and inp.get("bead_source") != "auto":
        return out
    core = inp.get("auto") if isinstance(inp.get("auto"), dict) else None
    ad = _doe_json(os.path.join(ddir, "prep", "auto_detect.json"))
    src = core or (ad if isinstance(ad, dict) else {"ok": False, "step": "version", "code": "AUTO_DETECT_MISSING"})
    avail = os.path.isfile(os.path.join(ddir, "prep", "select", "auto_selection.json"))
    auto = {"ok": bool(src.get("ok")) and (avail or core is None), "step": src.get("step"), "code": src.get("code"),
            "available": avail, "n_beads": int((core or {}).get("n_beads") or 0),
            "selection_sha256": (core or {}).get("selection_sha256")}
    for w in (core or {}).get("warnings") or []:
        if isinstance(w, dict) and w.get("code") != "AUTO_DETECT_FAILED" and w.get("level") != "info":
            x = _doe_warning(w, msgs)
            if x is not None and x not in warns:
                warns.append(x)
    warns[:] = [w for w in warns if w.get("code") != "AUTO_DETECT_FAILED"]   # 코어 문자열 경고 → 아래 한 개(필드 포함)
    if not auto["ok"]:
        step, detail = auto["step"] or "version", auto["code"]
        tmpl = msgs.get("AUTO_DETECT_FAILED") or AUTO_DETECT_MSG
        try:
            msg = tmpl.format(step=step, detail=detail)
        except (KeyError, IndexError, ValueError):
            msg = AUTO_DETECT_MSG.format(step=step, detail=detail)
        warns.append({"code": "AUTO_DETECT_FAILED", "message": msg[:300], "step": step, "detail": detail})
    out["auto"] = auto
    return out


COMPARE_SHAPE_KEYS = ("id", "name", "file_name", "reference", "source", "status", "code", "message", "n_nodes", "n_elems",
                      "quad_ratio", "quality",
                      # v0.16.0 메시 옵션(esl_compare_mesh_options.md §3·C2-D-22) — 프런트는 refine·refine_bias 를 그대로 읽음
                      "part_id", "mesh_method", "cad_error", "fidelity", "edge_median_mm", "n_components", "refine",
                      "attempts",
                      # v0.16.1(esl_select_relax.md §5A.5·SR-D-24): mesh_method "defeature" 형상만 억제 요약
                      # {n, counts, skipped_n, suppressed_max_mm, outside_hausdorff_mm}(cad 형상의 코어 행 defeature = v0.14.1
                      # 구멍 메움 기록 — 넘기지 않음), 메시 입력 진단 diag{holes_n, …}
                      # (attempts 행의 stage defeature·compound·reason 은 attempts 그대로)
                      "defeature", "diag")


def _register_compare_prep(conn: Connection, s: dict[str, Any], ddir: str) -> dict[str, Any]:
    """④ BD_PREP_REGISTER(esl_step_compare.md §5): phase READY, prep = {n_beads 0, n_params 0, paicad_version null,
    warnings, boundary null, n_shapes, n_ready, failed[{id, status, code}], reference_source, shapes[{id, name, file_name,
    reference, source, status, code, message, n_nodes, n_elems, quad_ratio, quality{fail_elems, fail_ratio, warn_elems,
    warn_ratio, tria_pct, over_limit}}]}(프런트 계약 보강)."""
    from esl_platform.core.repositories import doe as doe_repo

    from . import core_adapter

    inp = _doe_json(os.path.join(ddir, "prep", "input.json"))
    cmp = _doe_json(os.path.join(ddir, "prep", "compare.json"))
    if not isinstance(inp, dict) or not isinstance(cmp, dict) or not isinstance(cmp.get("shapes"), list):
        raise RegisterError("TOOL_OUTPUT_MISSING", "준비 결과(prep/input.json·compare.json)가 없습니다")
    try:
        msgs = core_adapter.doe_messages().get("messages") or {}
    except core_adapter.CoreError:
        msgs = {}
    warns = []
    for w in list(inp.get("warnings") or []) + list(inp.get("info") or []) + list((cmp.get("loads") or {}).get("warnings")
                                                                                 or []):
        x = _doe_warning(w, msgs)
        if x is not None and x not in warns:
            warns.append(x)
    shapes = [{k: r.get(k) for k in COMPARE_SHAPE_KEYS} for r in cmp["shapes"] if isinstance(r, dict)]
    for x in shapes:
        q = x.get("quality")
        if isinstance(q, dict):
            x["quality"] = {k: q.get(k) for k in ("fail_elems", "fail_ratio", "warn_elems", "warn_ratio", "tria_pct",
                                                  "over_limit", "max_fail_ratio")}
    failed = [{"id": r["id"], "status": r["status"], "code": r.get("code")} for r in shapes if r.get("status") != "READY"]
    for x in shapes:                     # v0.16.1 키는 있을 때만(v0.16.0 준비 요약 그대로). 코어 행 defeature 는 cad 형상이면
        if x.get("mesh_method") != "defeature" or not isinstance(x.get("defeature"), dict):   # v0.14.1 구멍 메움 기록 → 넣지 않음
            x.pop("defeature", None)
        if not isinstance(x.get("diag"), dict):
            x.pop("diag", None)
    prep = {"n_beads": 0, "n_params": 0, "paicad_version": None, "warnings": warns, "boundary": None,
            "n_shapes": len(shapes), "n_ready": len(shapes) - len(failed), "failed": failed,
            # v0.16.1 R3: 작은 형상 억제(defeature) 단계로 메시한 형상 수
            "n_defeature": sum(r.get("mesh_method") == "defeature" for r in shapes),
            "reference_source": cmp.get("reference_source"), "shapes": shapes,
            "mesh": {"size_mm": (cmp.get("profile") or {}).get("size_mm"), "gmsh_version": cmp.get("gmsh_version")}}
    doe_repo.update_study(conn, s["id"], phase="READY", prep=_jsonable(prep))
    return {"bead_doe_id": s["id"], "phase": "READY", "n_shapes": prep["n_shapes"], "n_ready": prep["n_ready"]}


def register_doe_preview(conn: Connection, job: dict[str, Any], case: Any, ddir: str) -> dict[str, Any]:
    """BD_PREVIEW_REGISTER: phase PREVIEW_READY, doe.preview = {rev, matrix_sha256, ok, skipped{collision, fixed, geom}}
    (doe 의 나머지 키 유지). 셀 상태 원본은 doe/<rev>/grid/grid_manifest.json(백엔드가 읽음).
    v0.15.0 select: + preview.selection_sha256(grid_manifest = 작업 params.doe.selection.sha256 — 다르면 PREVIEW_STALE),
    skipped.mesh(FAILED_MESH 셀 수). v0.16.1 select: + warn(경고 READY 수), rules(grid_manifest.rules — 있을 때만)."""
    from esl_platform.core.repositories import doe as doe_repo

    from . import core_adapter, doe_jobs

    s = _study(conn, job)
    d = (job.get("params") or {}).get("doe") or {}
    rev = int(d["rev"])
    doe = dict(s.get("doe") or {})
    if doe.get("rev") is not None and int(doe["rev"]) != rev:
        raise RegisterError("VERSION_CONFLICT", f"연구 DOE rev {doe.get('rev')} ≠ 작업 rev {rev}")
    m = _doe_json(os.path.join(ddir, "doe", str(rev), "matrix.json"))
    if not isinstance(m, dict) or not isinstance(m.get("designs"), list):
        raise RegisterError("TOOL_OUTPUT_MISSING", "doe/<rev>/matrix.json 이 없습니다")
    ids = [x["id"] for x in m["designs"] if x["id"] != "d000"]
    try:
        g = core_adapter.doe_paicad_io().read_grid(os.path.join(ddir, "doe", str(rev), "grid"), ids)
    except Exception as exc:  # noqa: BLE001 - EslError(PAICAD_FAILED)
        raise RegisterError("TOOL_OUTPUT_MISSING", f"미리보기 결과를 읽지 못했습니다: {getattr(exc, 'message', exc)}") from None
    want = set(ids)
    cnt = doe_jobs.count_states([r for r in g["cells"] if r["id"] in want])
    doe["preview"] = {"rev": rev, "matrix_sha256": m.get("matrix_sha256"), "ok": cnt["ok"],
                      "skipped": {k: cnt[k] for k in ("collision", "fixed", "geom")}}
    man = g.get("manifest") or {}
    if s.get("scenario") == "select":
        msha = (g.get("manifest") or {}).get("selection_sha256")
        jsha = (d.get("selection") or {}).get("sha256")
        if not msha or (jsha and msha != jsha):
            raise RegisterError("PREVIEW_STALE", f"미리보기 선택 sha256({str(msha)[:12]}…)이 작업 선택({str(jsha)[:12]}…)과 다릅니다")
        doe["preview"]["selection_sha256"] = msha
        sc = doe_jobs.count_select_states([r for r in g["cells"] if r["id"] in want])
        doe["preview"]["skipped"]["mesh"] = sc["mesh"]
        # v0.16.1(esl_select_relax.md §4.3·§7.4): 경고 READY 안 수(실행 대상) · 판정 규칙 판(grid_manifest.rules — 없으면 v0.16.0 규칙,
        # 백엔드가 rules_outdated 띠). 셀별 warnings·fixed_viol 은 grid_manifest 원본(백엔드 preview_cells 가 읽음)
        doe["preview"]["warn"] = sc["warn"]
        if isinstance(man.get("rules"), int):
            doe["preview"]["rules"] = int(man["rules"])
    doe_repo.update_study(conn, s["id"], phase="PREVIEW_READY", doe=_jsonable(doe))
    return {"bead_doe_id": s["id"], "phase": "PREVIEW_READY", **doe["preview"]}


def register_doe_run(conn: Connection, job: dict[str, Any], case: Any, ddir: str) -> dict[str, Any]:
    """BD_REGISTER: phase DONE, result = post/result.json 요약(best_all 제외 — ranking 은 max_designs 행 이내),
    report_rel = report.html. v0.16.1 select: ranking 행 warn[]·warnings·summary.best_clean(SR-D-11)은 결과 그대로."""
    from esl_platform.core.repositories import doe as doe_repo

    s = _study(conn, job)
    res = _doe_json(os.path.join(ddir, "post", "result.json"))
    if not isinstance(res, dict) or "ranking" not in res:
        raise RegisterError("TOOL_OUTPUT_MISSING", "post/result.json 이 없습니다")
    summ = {k: v for k, v in res.items() if k != "best_all"}
    summ["job_id"] = job["id"]
    has_report = os.path.isfile(os.path.join(ddir, "report.html"))
    doe_repo.update_study(conn, s["id"], phase="DONE", result=_jsonable(summ),
                          report_rel="report.html" if has_report else None)
    return {"bead_doe_id": s["id"], "phase": "DONE", "n_ok": res.get("n_ok"),
            "best": (res.get("best") or {}).get("id"), "report": has_report}


REGISTER = {"CASE_EXTRACT": register_extract, "ESL_SOLVE": register_esl, "VALIDATE": register_validation,
            "EXPORT": register_export, "CASE_REPORT": register_case_report, "LIB_ANALYZE": register_lib_analyze,
            "LIB_COMPARE": register_lib_compare, "OPT_RUN": register_opt_run}
