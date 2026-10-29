"""라이브러리 서비스(계약 esl_p2_library.md §1·§3·§11): 항목 등록·메타 수정·retire·목록, 종합분석 생성·조회·파일.

- 등록은 동기(API 프로세스): ESL 실행 스냅샷 ``runs/<esl_run_id>/`` 를 코어 ``entry.build`` 로 읽어
  ``<esl_root>/_library/entries/<id>/`` 에 저장(수정 불가) + DB 행. Case 폴더에는 쓰지 않는다.
- v0.10.0(esl_menu_restructure.md §7): 등록 = 현재 기준(scheme 있음) PASS 만. FAIL·UNDETERMINED → 422 VALIDATION_NOT_PASS
  (사유가 있어도 — force_reason 무시), LEGACY(scheme NULL) → 422 VALIDATION_LEGACY. 같은 run 의 ACTIVE 항목이 있으면 409 ENTRY_EXISTS.
- 적격 = quality.status PASS ∧ scheme 있음. 부적격(LEGACY·사유와 함께 등록된 FAIL·판정 불가)은 비드 최적화·강성 평가 스터디·
  종합분석에서 422 ENTRY_NOT_ELIGIBLE(필터 분석은 제외 후 excluded_ineligible). [재검증] = VALIDATE 작업(origin
  library_revalidate) — PASS 면 워커 VAL_REGISTER 가 같은 트랜잭션에서 quality 를 갱신(항목 폴더 불변).
- 분석 생성은 대상 항목을 확정(필터 → id 목록)해 LIB_ANALYZE 작업(SLOT)을 큐에 넣는다. DB 메타(사용자 수정)는
  작업 params 의 overlay 로 스냅샷되어 코어 항목 meta 에 덮어쓰인다.
- v0.7.0(esl_opt_run.md §5.1·§7.3·§7.4): 항목 응답에 ``size{inch, L_xi, L_eta}``·``topo_sha256``·``deform_mode{auto, user,
  effective, metrics}``. 등록 시 코어 meta 값을 그대로 저장하고, 기존 항목은 첫 조회 때 항목 폴더(entry.json → 없으면
  raw.npz)로 지연 백필(``backfill_opt_meta``, 버전 증가 없음). 기준값 변경(``opt_run.mode.rule_version``)이면 auto 만 다시
  계산하고 user 는 유지. ``PATCH deform_mode``(null = 자동으로 되돌림)는 메타 수정과 같은 권한·version 잠금.
"""

from __future__ import annotations

import copy
import datetime as _dt
import logging
import os
import shutil
import uuid
from typing import Any

from esl_worker import core_adapter
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from ...core import core_outputs as co
from ...core.auth import Principal
from ...core.config import opt_settings
from ...core.db.tables import cases as cases_t
from ...core.db.tables import esl_runs, library_entries
from ...core.db.tables import jobs as jobs_t
from ...core.inputs import extract_stale, inputs_hash
from ...core.state_machine import TERMINAL
from ...core.errors import DomainError, conflict, forbidden, not_found, unprocessable
from ...core.paths import ANALYSIS_DIR, LIBRARY_DIR, esl_subdir, safe_case_file
from ...core.repositories import cases as cases_repo
from ...core.repositories import jobs as jobs_repo
from ...core.repositories import library as lib_repo
from ...core.repositories.cases import VersionConflict
from ..context import AppContext
from .common import (
    analysis_dir,
    case_dir,
    job_out,
    load_case,
    require_config_ok,
    require_execute,
    require_library_config,
    validation_status,
)

MODEL_KEYS = ("name", "inch", "version", "date", "product_mass")
SCENE_KEYS = ("project", "scenario", "seq", "drop_type", "drop_class", "round", "scene_no", "orient", "suffix",
              "variant")


def _core_error(exc: core_adapter.CoreError) -> DomainError:
    if exc.code in ("PREREQUISITE_MISSING", "ENTRY_EXISTS", "ID_MISMATCH"):
        return conflict(exc.code, exc.message)
    if exc.code in ("INPUT_INVALID", "CONFIG_INVALID"):
        return unprocessable(exc.code, exc.message)
    return DomainError(exc.code, exc.message, status=500)


def _stash(lib_root: str, d: str) -> None:
    """실패한 등록의 새 항목 폴더를 _library/_backup/<ts>_<id> 로 옮긴다(삭제 없음)."""
    if not os.path.isdir(d):
        return
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    dst = os.path.join(lib_root, "_backup", f"{ts}_{os.path.basename(d)}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(d, dst)


# ---------------------------------------------------------------- v0.7.0 지연 백필(topo_sha256 · deform_mode)
log = logging.getLogger("esl_platform.api")
_BACKFILL_FAILED: set[str] = set()      # 항목 폴더·raw 가 없어 계산하지 못한 항목(프로세스 안에서 재시도 안 함)


def entry_folder(ctx: AppContext, e: dict[str, Any]) -> str:
    """<esl_root>/_library/entries/<id>(링크·탈출 검사)."""
    return esl_subdir(ctx.settings, *e["dir_rel"].split("/"))


def mode_cfg(ctx: AppContext) -> dict[str, Any]:
    return opt_settings(ctx.settings)["mode"]


def _merge_user(new: dict[str, Any], old: dict[str, Any] | None) -> dict[str, Any]:
    """auto 만 새로, 사용자 수정(user·user_by·user_at)은 유지(esl.opt.modes.refresh 와 같은 규칙)."""
    if old and old.get("user") is not None:
        new = {**new, "user": old["user"], "user_by": old.get("user_by"), "user_at": old.get("user_at")}
    return new


def compute_opt_meta(ctx: AppContext, e: dict[str, Any], *, need_topo: bool,
                     need_mode: bool) -> tuple[str | None, dict[str, Any] | None]:
    """항목 폴더에서 (topo_sha256, deform_mode 레코드). entry.json 에 같은 rule_version 값이 있으면 그대로(raw 를 읽지 않음),
    없으면 raw.npz 로 esl.library.entry.opt_meta. 실패하면 EslError/OSError/ValueError/KeyError 를 그대로 올린다."""
    from ...core.opt_core import library_entry as lib_entry
    from ...core.opt_core import modes

    mc = mode_cfg(ctx)
    d = entry_folder(ctx, e)
    import json

    with open(os.path.join(d, "entry.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    topo = meta.get("topo_sha256") if need_topo else None
    dm = meta.get("deform_mode") if need_mode else None
    if need_mode and dm is not None and modes.needs_refresh(dm, mc):
        dm = None
    if (need_topo and not topo) or (need_mode and dm is None):
        ent = lib_entry.load(d, raw=True)
        t2, dm2 = lib_entry.opt_meta(ent.raw, ent.meta["frame"], mc)
        topo = topo or t2
        dm = dm if dm is not None else dm2
    return topo, dm


def backfill_opt_meta(ctx: AppContext, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """topo_sha256 이 없거나 deform_mode 가 없거나 rule_version 이 다른 항목을 채워 DB 에 저장(version 증가 없음).
    실패 → topo null(S1 불가 "모델 정보 없음"), 같은 프로세스에서 다시 시도하지 않음.
    v0.7.2: 항목 단위 격리 — 어떤 예외(이전 버전 항목 폴더 형식·DB 쓰기 실패 등)도 그 항목만 건너뛰고 경고 로그(목록·s1-check 500 방지)."""
    from ...core.opt_core import EslError
    from ...core.opt_core import modes

    mc = mode_cfg(ctx)
    out = []
    for e in rows:
        need_topo = not e.get("topo_sha256")
        need_mode = modes.needs_refresh(e.get("deform_mode"), mc)
        if not (need_topo or need_mode) or e["id"] in _BACKFILL_FAILED:
            out.append(e)
            continue
        try:
            topo, dm = compute_opt_meta(ctx, e, need_topo=need_topo, need_mode=need_mode)
            vals: dict[str, Any] = {}
            if need_topo and topo:
                vals["topo_sha256"] = topo
            if need_mode and isinstance(dm, dict):
                vals["deform_mode"] = _merge_user(dm, e.get("deform_mode"))
            if vals:
                with ctx.engine.begin() as c2:
                    c2.execute(update(library_entries).where(library_entries.c.id == e["id"]).values(**vals))
                e = {**e, **vals}
        except Exception as exc:  # noqa: BLE001 — 항목 하나의 백필 실패가 목록 전체를 깨지 않게
            _BACKFILL_FAILED.add(e["id"])
            known = isinstance(exc, (EslError, OSError, ValueError, KeyError, TypeError, DomainError))
            log.warning("라이브러리 항목 %s 지연 백필(topo_sha256·deform_mode) 실패 — 건너뜀(S1 '모델 정보 없음'): %s: %s",
                        e["id"], type(exc).__name__, exc, exc_info=not known)
        out.append(e)
    return out


def deform_mode_out(dm: dict[str, Any] | None) -> dict[str, Any] | None:
    from ...core.opt_core import modes

    if not dm:
        return None
    return {"auto": dm.get("auto"), "user": dm.get("user"), "effective": modes.effective(dm),
            "metrics": dm.get("metrics") or {}, "user_by": dm.get("user_by"), "user_at": dm.get("user_at"),
            "rule_version": dm.get("rule_version")}


def entry_size(e: dict[str, Any]) -> dict[str, Any]:
    fr = ((e.get("summary") or {}).get("frame") or {})
    return {"inch": (e.get("model") or {}).get("inch"), "L_xi": _num(fr.get("L_xi")), "L_eta": _num(fr.get("L_eta"))}


# ---------------------------------------------------------------- v0.10.0 적격·재검증(§7.3~§7.5)
def eligibility(q: dict[str, Any] | None) -> tuple[bool, str | None]:
    """(eligible, ineligible_reason). 적격 = quality.status(없으면 verdict) PASS ∧ scheme 있음. scheme 없음 = LEGACY,
    scheme 있는 FAIL·UNDETERMINED(이전 사유 등록, Q1 A) = 그 상태."""
    q = q or {}
    if not q.get("scheme"):
        return False, "LEGACY"
    st = str(q.get("status") or q.get("verdict") or "").upper()
    if st == "PASS":
        return True, None
    return False, "UNDETERMINED" if st == "UNDETERMINED" else "FAIL"


INELIGIBLE_KO = {"LEGACY": "LEGACY(이전 판정 체계)", "FAIL": "FAIL", "UNDETERMINED": "판정 불가"}


def require_eligible(rows: list[dict[str, Any]]) -> None:
    """MR-D-10 게이트: 부적격 항목이 있으면 422 ENTRY_NOT_ELIGIBLE {entry_ids, reasons}."""
    bad = [(e["id"], eligibility(e.get("quality"))[1]) for e in rows if not eligibility(e.get("quality"))[0]]
    if bad:
        raise unprocessable("ENTRY_NOT_ELIGIBLE", f"현재 기준 PASS 가 아닌 ESL {len(bad)}개가 선택되었습니다(LEGACY·FAIL·판정 "
                            "불가) — [재검증] 후 사용하세요", entry_ids=[i for i, _ in bad],
                            reasons={i: r for i, r in bad})


def require_eligible_ids(conn, ids) -> None:
    """MR-D-10 게이트를 저장된 대상(스터디·최적화 실행·분석의 entry_ids)에 다시 적용 — 복제·재시도·다음 단계 작업이
    생성 때의 게이트를 우회하지 않게(통합 검증 지적 1c). v0.10.0 이전에 부적격 항목으로 만든 대상도 여기서 막힌다."""
    ids = [i for i in dict.fromkeys(ids or []) if i]
    if ids:
        require_eligible(lib_repo.list_entries(conn, ids=ids))


BLOCK_MESSAGES = {
    "CASE_ARCHIVED": "Case 가 보관되어 재검증할 수 없습니다",
    "RUN_SNAPSHOT_MISSING": "ESL 결과 스냅샷이 없어 재검증할 수 없습니다 — Case를 다시 계산해 새로 등록하세요",
    "EXTRACT_CHANGED": "Case 추출이 바뀌어 재검증할 수 없습니다 — Case를 다시 계산해 새로 등록하세요",
    "CASE_JOB_BUSY": "같은 Case 의 검증 작업이 대기 중이거나 실행 중입니다",
}


def _block(code: str, reason: str | None = None) -> dict[str, Any]:
    return {"code": code, "reason": reason or code, "message": BLOCK_MESSAGES[reason or code]}


def revalidate_block(ctx: AppContext, case: dict[str, Any] | None, run: dict[str, Any] | None) -> dict[str, Any] | None:
    """§7.3 재검증 불가 사유(작업 충돌 제외 — 순서: 보관 → 스냅샷 → 추출 변경). None = 가능."""
    if case is None or case.get("status") == "ARCHIVED":
        return _block("CASE_ARCHIVED")
    if run is None or not os.path.isdir(co.run_snapshot_dir(case_dir(ctx, case), run["id"])):
        return _block("REVALIDATE_NOT_POSSIBLE", "RUN_SNAPSHOT_MISSING")
    es = case.get("extract_summary") or {}
    ih = inputs_hash(extract_job_id=es.get("job_id"), part_title=case["part_title"],
                     tstar={"frame_index": run["frame_index"], "metric": run["metric"]},
                     support_set_id=run["support_set_id"])
    if ih != run["inputs_hash"] or extract_stale(case):
        return _block("REVALIDATE_NOT_POSSIBLE", "EXTRACT_CHANGED")
    return None


def _by_id(conn, table, ids) -> dict[str, dict[str, Any]]:
    from ...core.repositories import row_dict

    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    return {r["id"]: r for r in (row_dict(x) for x in conn.execute(select(table).where(table.c.id.in_(ids))).all())}


# ---------------------------------------------------------------- 직렬화
def entries_out(ctx: AppContext | None, conn, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """항목 응답 일괄 계산(Case·run·진행 중 재검증 작업을 각각 한 번에 조회 — 항목 수와 무관한 쿼리 수, V-MR-16)."""
    from ...core.repositories import row_dict

    cases = _by_id(conn, cases_t, [e["case_id"] for e in rows])
    inel = [e for e in rows if e.get("status") == "ACTIVE" and not eligibility(e.get("quality"))[0]]
    runs = _by_id(conn, esl_runs, [e["esl_run_id"] for e in inel])
    active: dict[str, list[dict[str, Any]]] = {}
    cids = sorted({e["case_id"] for e in inel})
    if cids:
        for j in (row_dict(x) for x in conn.execute(select(jobs_t).where(
                jobs_t.c.case_id.in_(cids), jobs_t.c.job_type == "VALIDATE",
                jobs_t.c.state.notin_(list(TERMINAL)))).all()):
            active.setdefault(j["case_id"], []).append(j)
    out = []
    for e in rows:
        d = dict(e)
        case = cases.get(e["case_id"])
        d["case_title"] = case["title"] if case else None
        d["size"] = entry_size(e)
        d["deform_mode"] = deform_mode_out(e.get("deform_mode"))
        ok, why = eligibility(e.get("quality"))
        d["eligible"], d["ineligible_reason"] = ok, why
        d["revalidate_block"] = d["revalidate_job"] = None
        if e.get("status") == "ACTIVE" and not ok:
            jobs_here = active.get(e["case_id"]) or []
            mine = next((j for j in jobs_here if (j.get("params") or {}).get("origin") == "library_revalidate"
                         and (j.get("params") or {}).get("entry_id") == e["id"]), None)
            if mine is not None:
                d["revalidate_job"] = {"job_id": mine["id"], "state": mine["state"]}
            elif ctx is not None:
                d["revalidate_block"] = revalidate_block(ctx, case, runs.get(e["esl_run_id"])) or (
                    _block("CASE_JOB_BUSY") if jobs_here else None)
        out.append(d)
    return out


def entry_out(conn, e: dict[str, Any], ctx: AppContext | None = None) -> dict[str, Any]:
    return entries_out(ctx, conn, [e])[0]


def _load_entry(conn, eid: str, *, for_update: bool = False) -> dict[str, Any]:
    e = lib_repo.get_entry(conn, eid, for_update=for_update)
    if e is None:
        raise not_found("ENTRY_NOT_FOUND", "라이브러리 항목을 찾을 수 없습니다")
    return e


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _row_from_meta(meta: dict[str, Any], val: dict[str, Any], force_reason: str | None,
                   principal: Principal) -> dict[str, Any]:
    m = meta.get("model") or {}
    s = meta.get("scene") or {}
    q = meta.get("quality") or {}
    fld = q.get("field") or {}
    vf = val.get("field") or {}
    fmax = ((fld.get("max") or {}).get("abs_err_pct") if isinstance(fld.get("max"), dict) else None)
    fp90 = ((fld.get("abs_err_pct") or {}).get("p90") if isinstance(fld.get("abs_err_pct"), dict) else None)
    if fmax is None and isinstance(vf.get("max"), dict):
        fmax = vf["max"].get("abs_err_pct")
    if fp90 is None and isinstance(vf.get("abs_err_pct"), dict):
        fp90 = vf["abs_err_pct"].get("p90")
    model = {"name": m.get("product"), "inch": m.get("inch"), "version": m.get("version"), "date": m.get("date"),
             "project": m.get("project"), "product_mass": None, "part_mass": _num(m.get("part_mass")),
             "part_id": m.get("part_id"), "part_title": m.get("part_title"), "units_label": m.get("units_label"),
             "n_nodes": m.get("n_nodes"), "n_elems": m.get("n_elems")}
    scene = {"project": s.get("project"), "scenario": s.get("scenario"), "seq": s.get("seq"),
             "drop_type": s.get("drop_type"), "drop_class": s.get("drop_class"), "round": s.get("round"),
             "scene_no": s.get("scene"), "orient": s.get("orient"), "suffix": s.get("suffix"),
             "variant": s.get("variant"), "faces": s.get("faces"), "raw": s.get("source"),
             "path_kind": s.get("path_kind"), "warnings": list(s.get("warnings") or [])}
    quality = {"verdict": val["verdict"], "status": validation_status(val), "scheme": val.get("scheme"),
               "undetermined_reason": val.get("undetermined_reason"),
               "disp_max_rel": _num(val.get("disp_max_rel")), "disp_noise_rel": _num(val.get("disp_noise_rel")),
               "strain_exceed_frac": _num((val.get("strain_ref") or {}).get("frac_exceed")),
               "fail_reasons": list(val.get("fail_reasons") or []),
               "field_max_err_pct": _num(fmax), "field_p90_err_pct": _num(fp90),
               "hotspot1_rel_err": _num(q.get("hotspot1_rel_err")), "disp_rms_rel": _num(q.get("disp_rms_rel")),
               "reaction_rel": _num(q.get("reaction_rel")), "noise": q.get("noise"), "confirmed_fail": None,
               "confirmed_undetermined": None}
    if val["verdict"] != "PASS":
        # FAIL → confirmed_fail, UNDETERMINED → confirmed_undetermined (같은 형식 {reason, by, by_name, at})
        quality["confirmed_undetermined" if val["verdict"] == "UNDETERMINED" else "confirmed_fail"] = {
            "reason": force_reason, "by": principal.user_id, "by_name": principal.display_name,
            "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
    sm = meta.get("summary") or {}
    fr = meta.get("frame") or {}
    summary = {"grid": meta.get("grid"), "mesh_sha256": meta.get("mesh_sha256"),
               "load_sha256": meta.get("load_sha256"), "core_entry_id": meta.get("core_entry_id"),
               "total_F": sm.get("total_F"), "total_M": sm.get("total_M"), "sum_abs_f": _num(sm.get("sum_abs_f")),
               "max_f": _num(sm.get("max_f")), "n_cells_loaded": sm.get("n_cells_loaded"),
               "frame": {"L_xi": _num(fr.get("L_xi")), "L_eta": _num(fr.get("L_eta"))}}
    return {"model": model, "scene": scene, "quality": quality, "tstar": meta.get("tstar"), "summary": summary,
            "warnings": [str(w) for w in meta.get("warnings") or []], "files": meta.get("files") or {},
            "topo_sha256": meta.get("topo_sha256"), "deform_mode": meta.get("deform_mode")}


# ---------------------------------------------------------------- 등록
def _validation_ready(cdir: str, run: dict[str, Any], val: dict[str, Any], latest_case_val: str | None) -> bool:
    """검증 산출물이 디스크에 있는가: run 스냅샷 05_val(표식 = 이 검증) 또는 (이 검증이 Case 최신이면) 05_val."""
    snap = co.val_snapshot_dir(cdir, run["id"])
    if co.val_marker(snap) == val["id"] and os.path.isfile(os.path.join(snap, "validation.json")):
        return True
    if latest_case_val != val["id"]:
        return False
    try:
        vj = co.validation_json(cdir)
    except (co.OutputMissing, OSError, ValueError):
        return False
    return vj.get("esl_ref") in (None, run["job_id"])


def register_entry(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    lib_cfg = require_library_config(ctx)
    with ctx.engine.begin() as conn:
        run = conn.execute(select(esl_runs).where(esl_runs.c.id == body.esl_run_id).with_for_update()).first()
        if run is None:
            raise not_found("ESL_RUN_NOT_FOUND", "ESL 결과를 찾을 수 없습니다")
        run = dict(run._mapping)
        case = load_case(conn, run["case_id"])
        require_execute(principal, case["project_id"])
        if run["status"] != "READY":
            raise conflict("PREREQUISITE_MISSING", "READY 상태의 ESL 결과만 등록할 수 있습니다", missing=["esl_run"])
        dup = lib_repo.active_entry_for_run(conn, run["id"])
        if dup is not None:
            raise conflict("ENTRY_EXISTS", "이 ESL 결과는 이미 라이브러리에 등록되어 있습니다(정정은 retire 후 재등록)",
                           entry_id=dup["id"])
        vals = cases_repo.list_validations(conn, esl_run_id=run["id"])
        if body.validation_id:
            val = cases_repo.get_validation(conn, body.validation_id)
            if val is None or val["esl_run_id"] != run["id"]:
                raise unprocessable("INVALID_PARAMS", "이 ESL 결과의 검증이 아닙니다")
            if vals and vals[0]["id"] != val["id"]:
                raise conflict("VALIDATION_NOT_LATEST", "이 ESL 결과의 최신 검증만 등록할 수 있습니다",
                               latest_validation_id=vals[0]["id"])
        else:
            val = vals[0] if vals else None
        if val is None:
            raise conflict("PREREQUISITE_MISSING", "검증(⑤) 결과가 있는 ESL 결과만 등록할 수 있습니다",
                           missing=["validation"])
        # v0.10.0 MR-D-8: 현재 기준 PASS 만(force_reason 은 무시 — 구 클라이언트 호환)
        if not val.get("scheme"):
            raise unprocessable("VALIDATION_LEGACY", "이전 판정 체계 결과는 등록할 수 없습니다 — ④에서 다시 검증하세요",
                                verdict=val["verdict"])
        if val["verdict"] != "PASS":
            raise unprocessable("VALIDATION_NOT_PASS", f"검증 {val['verdict']} — 변위 기준 PASS 만 등록할 수 있습니다 "
                                "(FAIL 사유는 [결과 받기(zip)]로 확인)", verdict=val["verdict"])
        cdir = case_dir(ctx, case)
        if not os.path.isdir(co.run_snapshot_dir(cdir, run["id"])):
            raise conflict("PREREQUISITE_MISSING", "ESL 실행 스냅샷(runs/<id>/)이 없습니다", missing=["run_snapshot"])
        latest_case = cases_repo.list_validations(conn, case_id=case["id"])
        if not _validation_ready(cdir, run, val, latest_case[0]["id"] if latest_case else None):
            raise conflict("PREREQUISITE_MISSING", "검증 산출물이 이후 검증으로 바뀌었습니다. 이 ESL 결과로 검증을 다시 "
                           "실행하세요", missing=["validation_files"])
        lib_root = esl_subdir(ctx.settings, LIBRARY_DIR)
        os.makedirs(lib_root, exist_ok=True)
        eid = str(uuid.uuid4())
        edir = os.path.join(lib_root, "entries", eid)
        try:
            meta = core_adapter.build_library_entry(cdir, run["id"], lib_root, eid, lib_cfg,
                                                    scene_path=case.get("h3d_path") or case["results_dir"],
                                                    registered_by=principal.display_name, mode_cfg=mode_cfg(ctx))
        except core_adapter.CoreError as exc:
            _stash(lib_root, edir)
            raise _core_error(exc) from None
        if (meta.get("quality") or {}).get("verdict") != val["verdict"]:
            _stash(lib_root, edir)
            raise conflict("PREREQUISITE_MISSING", "검증 산출물이 이 ESL 결과의 것이 아닙니다", missing=["validation_files"])
        row = _row_from_meta(meta, val, None, principal)
        sha = ((meta.get("files") or {}).get("summary.npz") or {}).get("sha256")
        dir_rel = f"{LIBRARY_DIR}/entries/{eid}"
        try:
            with conn.begin_nested():
                e = lib_repo.insert_entry(
                    conn, id=eid, project_id=case["project_id"], case_id=case["id"], esl_run_id=run["id"],
                    validation_id=val["id"], status="ACTIVE", dir_rel=dir_rel, summary_rel=f"{dir_rel}/summary.npz",
                    sha256=sha, note=body.note, force_reason=None,
                    registered_by=principal.user_id, registered_by_name=principal.display_name, **row)
        except IntegrityError:
            _stash(lib_root, edir)
            raise conflict("ENTRY_EXISTS", "이 ESL 결과는 이미 라이브러리에 등록되어 있습니다") from None
        return entry_out(conn, e, ctx)


def list_entries(ctx: AppContext, project_id: str | None, status: str | None, mode: str | None = None,
                 **filters) -> list[dict[str, Any]]:
    """mode = dent|twist|bend|none(분류 불가·미분류) — effective 모드(사용자 수정 우선)로 거른다(백필 뒤)."""
    from ...core.opt_core import modes

    if mode is not None and mode not in (*modes.MODES, "none"):
        raise unprocessable("INVALID_PARAMS", "mode 는 dent | twist | bend | none")
    with ctx.engine.connect() as conn:
        rows = lib_repo.list_entries(conn, project_id=project_id, status=status, **filters)
    rows = backfill_opt_meta(ctx, rows)
    if mode is not None:
        rows = [e for e in rows if (modes.effective(e.get("deform_mode")) or "none") == mode]
    with ctx.engine.connect() as conn:
        return entries_out(ctx, conn, rows)


def get_entry(ctx: AppContext, eid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        e = _load_entry(conn, eid)
    e = backfill_opt_meta(ctx, [e])[0]
    with ctx.engine.connect() as conn:
        return entry_out(conn, e, ctx)


def retire_entry(ctx: AppContext, principal: Principal, eid: str, body) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        e = _load_entry(conn, eid, for_update=True)
        if e["registered_by"] != principal.user_id and principal.role(e["project_id"]) != "admin":
            raise forbidden("등록자 또는 관리자만 retire 할 수 있습니다")
        require_config_ok(ctx)
        if e["status"] == "RETIRED":
            raise conflict("ENTRY_RETIRED", "이미 retired 된 항목입니다")
        e = lib_repo.update_entry(conn, eid, None, status="RETIRED", retired_by_id=principal.user_id,
                                  retired_at=func.now(), retire_reason=(body.reason if body else None))
        return entry_out(conn, e, ctx)


def can_edit_meta(principal: Principal, e: dict[str, Any]) -> bool:
    """메타(모델·씬·메모) 수정 = 등록자 또는 관리자(프로젝트 admin·전역 관리자) — retire 와 같은 규칙(v0.8.0)."""
    return e["registered_by"] == principal.user_id or principal.role(e["project_id"]) == "admin"


def _clean(v: Any) -> Any:
    """문자열 메타: 앞뒤 공백 제거, 빈 문자열 = 값 없음(null)."""
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def patch_entry(ctx: AppContext, principal: Principal, eid: str, body) -> dict[str, Any]:
    """메타 수정. 권한: power 이상(변형 모드만 바꿀 때) + 모델·씬·메모는 등록자 또는 관리자. 항목 폴더(entry.json)는
    등록 때 그대로 두고(수정 불가) DB 메타만 바꾼다 — 종합분석은 작업 params overlay, 비드 최적화 크기는 DB model.inch."""
    with ctx.engine.begin() as conn:
        e = _load_entry(conn, eid, for_update=True)
        require_execute(principal, e["project_id"])
        meta = body.model is not None or body.scene is not None or "note" in body.model_fields_set
        if meta and not can_edit_meta(principal, e):
            raise forbidden("등록자 또는 관리자만 모델·씬·메모를 수정할 수 있습니다")
        lib_cfg = require_library_config(ctx)
        if e["status"] != "ACTIVE":
            raise conflict("ENTRY_RETIRED", "retired 항목은 수정할 수 없습니다")
        vals: dict[str, Any] = {}
        if body.model is not None:
            m = dict(e["model"])
            for k in body.model.model_fields_set:
                m[k] = _clean(getattr(body.model, k))
            vals["model"] = m
        if body.scene is not None:
            s = dict(e["scene"])
            for k in body.scene.model_fields_set:
                s[k] = _clean(getattr(body.scene, k))
            if body.scene.model_fields_set & {"orient", "drop_type"}:
                try:
                    ori, warns = core_adapter.interpret_orient(s.get("orient"), s.get("drop_type"), lib_cfg)
                except core_adapter.CoreError as exc:
                    raise _core_error(exc) from None
                s["drop_class"] = ori.get("drop_class") or s.get("drop_type")
                s["faces"] = ori.get("faces")
                s["warnings"] = [w for w in s.get("warnings") or [] if "orient" not in w and "drop_type" not in w]
                s["warnings"] += warns
            s["edited"] = True
            vals["scene"] = s
        if "note" in body.model_fields_set:
            vals["note"] = _clean(body.note)
        if "deform_mode" in body.model_fields_set:
            vals.update(_patch_deform_mode(ctx, principal, e, body.deform_mode))
        try:
            e = lib_repo.update_entry(conn, eid, body.version, **vals)
        except VersionConflict:
            raise conflict("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요") from None
        return entry_out(conn, e, ctx)


def _patch_deform_mode(ctx: AppContext, principal: Principal, e: dict[str, Any], user: str | None) -> dict[str, Any]:
    """변형 모드 사용자 수정(null = 자동으로 되돌림). 레코드가 없거나 기준값이 바뀌었으면 먼저 계산(실패하면 auto null)."""
    from ...core.opt_core import EslError
    from ...core.opt_core import modes

    mc = mode_cfg(ctx)
    out: dict[str, Any] = {}
    dm = e.get("deform_mode")
    if modes.needs_refresh(dm, mc):
        try:
            topo, new = compute_opt_meta(ctx, e, need_topo=not e.get("topo_sha256"), need_mode=True)
            if topo and not e.get("topo_sha256"):
                out["topo_sha256"] = topo
            dm = _merge_user(new, dm) if new is not None else dm
        except (EslError, OSError, ValueError, KeyError, TypeError, DomainError):
            pass
    if not dm:
        dm = {"auto": None, "metrics": {}, "user": None, "user_by": None, "user_at": None,
              "rule_version": int(mc["rule_version"])}
    try:
        out["deform_mode"] = modes.set_user(dm, user, principal.display_name,
                                            _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
    except EslError as exc:
        raise unprocessable("INVALID_PARAMS", exc.message) from None
    return out


# ---------------------------------------------------------------- 종합분석
def _overlay(e: dict[str, Any]) -> dict[str, Any]:
    return {"entry_id": e["id"], "model": {k: (e["model"] or {}).get(k) for k in MODEL_KEYS},
            "scene": {k: (e["scene"] or {}).get(k) for k in SCENE_KEYS},
            "verdict": (e["quality"] or {}).get("verdict"),
            # v0.10.0 §7.4: 판정 원본 = DB quality(재검증 전환 반영) — 보고서도 이 값을 쓴다
            "status": (e["quality"] or {}).get("status"), "scheme": (e["quality"] or {}).get("scheme")}


def _norm_check(mode: str | None, rows: list[dict], target: dict | None, opts) -> None:
    if mode not in ("mass", "inch2"):
        return
    key, label = ("product_mass", "제품 질량(model.product_mass)") if mode == "mass" else ("inch", "인치(model.inch)")
    miss = [e["id"] for e in rows if (e["model"] or {}).get(key) in (None, 0)]
    topt = opts.target_mass if mode == "mass" else opts.target_inch
    tval = topt if topt is not None else ((target or {}).get("model") or {}).get(key)
    if miss or tval in (None, 0):
        raise unprocessable("NORMALIZATION_META_MISSING", f"normalization={mode}: {label} 가 필요합니다"
                            + ("" if tval not in (None, 0) else " (대상 값 또는 options.target_"
                               + ("mass" if mode == "mass" else "inch") + ")"),
                            entry_ids=miss, target_missing=tval in (None, 0))


def analysis_out(ctx: AppContext, conn, a: dict[str, Any]) -> dict[str, Any]:
    d = dict(a)
    job = jobs_repo.get_job(conn, a["job_id"]) if a.get("job_id") else None
    d["job"] = job_out(conn, job, with_steps=True) if job else None
    d["status"] = job["state"] if job else "NONE"
    d["n_entries"] = len(a.get("entry_ids") or [])
    d["folder_path"] = analysis_dir(ctx, a)
    return d


def _load_analysis(conn, aid: str, *, for_update: bool = False) -> dict[str, Any]:
    a = lib_repo.get_analysis(conn, aid, for_update=for_update)
    if a is None:
        raise not_found("ANALYSIS_NOT_FOUND", "분석을 찾을 수 없습니다")
    return a


def create_analysis(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    require_execute(principal, body.project_id)
    lib_cfg = require_library_config(ctx)
    f = body.filters
    excluded = 0
    with ctx.engine.begin() as conn:
        if f.entry_ids:
            rows = lib_repo.list_entries(conn, project_id=body.project_id, status="ACTIVE", ids=f.entry_ids)
            found = {e["id"] for e in rows}
            miss = [i for i in f.entry_ids if i not in found]
            if miss:
                raise unprocessable("ENTRY_NOT_FOUND", "이 프로젝트의 활성 항목이 아닙니다", entry_ids=miss)
            require_eligible(rows)                       # MR-D-10
        else:
            rows = lib_repo.list_entries(conn, project_id=body.project_id, status="ACTIVE", model=f.model,
                                         inch=[str(i) for i in f.inch] if f.inch else None, drop_type=f.drop_type,
                                         drop_class=f.drop_class, orient=f.orient, scenario=f.scenario,
                                         verdict=f.verdict)
            keep = [e for e in rows if eligibility(e.get("quality"))[0]]
            excluded = len(rows) - len(keep)             # 필터 분석: 부적격 제외 후 수만 알림
            rows = keep
        if not rows:
            raise unprocessable("NO_MATCHING_ENTRIES", "필터에 맞는 활성 라이브러리 항목이 없습니다"
                                + (f"(부적격 {excluded}개 제외)" if excluded else ""), excluded_ineligible=excluded)
        rows.sort(key=lambda e: (e["registered_at"], e["id"]))
        target = None
        if body.target_entry_id:
            target = lib_repo.get_entry(conn, body.target_entry_id)
            if target is None or target["project_id"] != body.project_id or target["status"] != "ACTIVE":
                raise unprocessable("TARGET_INVALID", "대상은 이 프로젝트의 활성 라이브러리 항목이어야 합니다")
            require_eligible([target])
        opts = body.options
        _norm_check(opts.normalization, rows, target, opts)
        if target is None:
            grids = {tuple(((e["summary"] or {}).get("grid") or {}).get(k) for k in ("nx", "ny")) for e in rows}
            if len(grids) != 1:
                raise unprocessable("GRID_MISMATCH", f"대상 없는 분석은 같은 정규화 격자가 필요합니다(항목 격자 "
                                    f"{sorted(map(str, grids))})")
        aid = str(uuid.uuid4())
        esl_subdir(ctx.settings, ANALYSIS_DIR, aid)        # 경로 안전성(실제 생성은 워커)
        filters = f.model_dump(exclude_none=True)
        options = opts.model_dump(exclude_none=True)
        a = lib_repo.insert_analysis(
            conn, id=aid, project_id=body.project_id, title=body.title, target_entry_id=body.target_entry_id,
            filters=filters, options=options, entry_ids=[e["id"] for e in rows], dir_rel=f"{ANALYSIS_DIR}/{aid}",
            created_by=principal.user_id, created_by_name=principal.display_name)
        params = {"settings": copy.deepcopy(lib_cfg), "analysis_id": aid, "title": body.title,
                  "entries": [{"id": e["id"], "dir_rel": e["dir_rel"], "overlay": _overlay(e)} for e in rows],
                  "target": None if target is None else {"id": target["id"], "dir_rel": target["dir_rel"],
                                                         "overlay": _overlay(target)},
                  "options": options, "filters": filters}
        job = jobs_repo.insert_job(conn, case_id=None, analysis_id=aid, project_id=body.project_id,
                                   job_type="LIB_ANALYZE", params=_jsonable(params), created_by=principal.user_id,
                                   created_by_name=principal.display_name)
        a = lib_repo.update_analysis(conn, aid, job_id=job["id"])
        out = analysis_out(ctx, conn, a)
        if excluded:
            out["excluded_ineligible"] = excluded
        return out


# ---------------------------------------------------------------- v0.10.0 재검증(§7.3)
def revalidate_entry(ctx: AppContext, principal: Principal, eid: str) -> dict[str, Any]:
    """LEGACY·사유 등록 FAIL·판정 불가 항목 → 현재 기준 VALIDATE 작업(origin library_revalidate). 201 JobOut."""
    from .jobs import core_settings_for

    with ctx.engine.begin() as conn:
        e = _load_entry(conn, eid, for_update=True)
        require_execute(principal, e["project_id"])
        require_config_ok(ctx)
        if e["status"] != "ACTIVE":
            raise conflict("ENTRY_RETIRED", "폐기된 항목은 재검증할 수 없습니다")
        if eligibility(e.get("quality"))[0]:
            raise conflict("ENTRY_NOT_LEGACY", "이미 현재 기준 PASS 인 항목입니다")
        case = cases_repo.get_case(conn, e["case_id"], for_update=True)
        run = cases_repo.get_esl_run(conn, e["esl_run_id"])
        blk = revalidate_block(ctx, case, run)
        if blk is not None:
            if blk["code"] == "CASE_ARCHIVED":
                raise conflict("CASE_ARCHIVED", blk["message"])
            raise conflict("REVALIDATE_NOT_POSSIBLE", blk["message"], reason=blk["reason"])
        if run["status"] != "READY":
            raise conflict("REVALIDATE_NOT_POSSIBLE", BLOCK_MESSAGES["RUN_SNAPSHOT_MISSING"], reason="RUN_SNAPSHOT_MISSING")
        sup = cases_repo.get_support_set(conn, run["support_set_id"])
        params = {"esl_run_id": run["id"], "origin": "library_revalidate", "entry_id": e["id"],
                  "settings": core_settings_for(ctx, case, metric=run["metric"]), "frame_index": run["frame_index"],
                  "support_node_ids": list(sup["node_ids"]) if sup else None}
        try:
            with conn.begin_nested():
                job = jobs_repo.insert_job(conn, case_id=case["id"], project_id=case["project_id"], job_type="VALIDATE",
                                           params=params, created_by=principal.user_id,
                                           created_by_name=principal.display_name)
        except IntegrityError:
            raise conflict("CASE_JOB_BUSY", BLOCK_MESSAGES["CASE_JOB_BUSY"], case_ids=[case["id"]]) from None
        return job_out(conn, job, with_steps=True)


def _jsonable(o: Any) -> Any:
    import json

    return json.loads(json.dumps(o, default=str))


def list_analyses(ctx: AppContext, project_id: str | None) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        return [analysis_out(ctx, conn, a) for a in lib_repo.list_analyses(conn, project_id)]


def get_analysis(ctx: AppContext, aid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        return analysis_out(ctx, conn, _load_analysis(conn, aid))


def _adir(ctx: AppContext, a: dict[str, Any]) -> str:
    return esl_subdir(ctx.settings, ANALYSIS_DIR, a["id"])


def _kind(rel: str) -> str:
    if rel == "report.html":
        return "report"
    if rel.startswith("opt/"):
        return "optdeck"
    if rel.startswith("logs/"):
        return "log"
    if rel in ("analysis.json", "mapped_loads.npz", "envelope.csv", "representatives.csv"):
        return "analysis"
    return "other"


def list_files(ctx: AppContext, aid: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        a = _load_analysis(conn, aid)
    base = _adir(ctx, a)
    out = []
    if not os.path.isdir(base):
        return out
    order = {"report": 0, "optdeck": 1, "analysis": 2, "other": 3, "log": 4}
    for root, dirs, names in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d != "_backup" and not os.path.islink(os.path.join(root, d)))
        for n in sorted(names):
            p = os.path.join(root, n)
            if os.path.islink(p) or not os.path.isfile(p) or n.endswith(".tmp"):
                continue
            rel = os.path.relpath(p, base).replace("\\", "/")
            size = os.path.getsize(p)
            out.append({"rel": rel, "kind": _kind(rel), "size": size, "path": p,
                        "downloadable": size <= ctx.settings.ui.max_artifact_bytes})
    out.sort(key=lambda x: (order[x["kind"]], x["rel"]))
    return out


def analysis_file(ctx: AppContext, aid: str, rel: str) -> str:
    with ctx.engine.connect() as conn:
        a = _load_analysis(conn, aid)
    base = _adir(ctx, a)
    path = safe_case_file(base, rel)
    if not os.path.isfile(path):
        raise not_found("FILE_NOT_FOUND", "파일이 없습니다")
    size = os.path.getsize(path)
    if size > ctx.settings.ui.max_artifact_bytes:
        raise DomainError("ARTIFACT_TOO_LARGE", "파일이 커서 다운로드할 수 없습니다. 경로를 복사해 여세요", status=413,
                          rel=rel, path=path, size=size, limit=ctx.settings.ui.max_artifact_bytes)
    return path


def analysis_report(ctx: AppContext, aid: str) -> str:
    with ctx.engine.connect() as conn:
        a = _load_analysis(conn, aid)
    path = safe_case_file(_adir(ctx, a), "report.html")
    if not os.path.isfile(path):
        raise not_found("REPORT_NOT_FOUND", "보고서가 아직 없습니다(분석 작업 완료 후 생성)")
    return path
