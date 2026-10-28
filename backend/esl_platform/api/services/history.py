"""실행 이력 서비스(계약 esl_p3_history.md): 목록(`/history`), 상세(`/jobs/{id}/review`), 과거 파일.

- 이력의 단위는 jobs 행(H-1). 과거 결과 값은 DB 에 기록된 그 시점 값(H-2).
- 목록은 쿼리 수가 일정하다(작업 행 1 + 대상 Case·분석·비교·ESL 실행·검증·재시도·최신 성공 작업 일괄 조회).
- `result_state`·`stale_reasons`(H-6)와 `diff`(H-7)는 서버가 계산한다.
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import hashlib
import json
import os
import re
from typing import Any

from sqlalchemy.engine import Connection

from ...core import core_outputs as co
from ...core.auth import Principal
from ...core.errors import DomainError, not_found, unprocessable
from ...core.inputs import changed_inputs, esl_run_stale, extract_stale, inputs_hash
from ...core.job_types import JOB_TYPES
from ...core.paths import safe_case_file
from ...core.repositories import cases as cases_repo
from ...core.repositories import history as repo
from ...core.repositories import jobs as jobs_repo
from ...core.repositories import library as lib_repo
from ...core.repositories import opt as opt_repo
from ...core.state_machine import RUNNING, SUCCEEDED
from ..context import AppContext
from .common import analysis_dir, case_dir, esl_run_out, job_out, load_job, validation_out, validation_status
from .results import locate_validation_dir

STATES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")
KIND_BY_TYPE = {"CASE_EXTRACT": "extract", "ESL_SOLVE": "esl_run", "VALIDATE": "validation", "EXPORT": "export",
                "CASE_REPORT": "report", "LIB_ANALYZE": "analysis", "LIB_COMPARE": "comparison", "OPT_RUN": "opt_run"}
REASON_ORDER = ("extract", "part_title", "tstar", "support_set", "input_files")
FILES_NOTE = "파일 보존 안 됨 — 기록된 값만 표시"
DIFF_MAX = 12
FINGERPRINT_MAX = 1000


# ---------------------------------------------------------------- 커서(H-9)
def _invalid_cursor() -> DomainError:
    return unprocessable("INVALID_CURSOR", "커서가 올바르지 않습니다")


def encode_cursor(created_at: _dt.datetime, job_id: str) -> str:
    body = json.dumps({"t": created_at.astimezone(_dt.timezone.utc).isoformat(), "i": job_id}, separators=(",", ":"))
    chk = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return base64.urlsafe_b64encode(f"{chk}.{body}".encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(raw: str) -> tuple[_dt.datetime, str]:
    try:
        if len(raw) > 512:
            raise ValueError("too long")
        txt = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
        chk, _, body = txt.partition(".")
        if hashlib.sha256(body.encode("utf-8")).hexdigest()[:8] != chk:
            raise ValueError
        d = json.loads(body)
        t = _dt.datetime.fromisoformat(d["t"])
        i = d["i"]
        if t.tzinfo is None or not isinstance(i, str) or not re.fullmatch(r"[0-9a-fA-F-]{8,64}", i):
            raise ValueError
        return t, i
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeDecodeError):
        raise _invalid_cursor() from None


# ---------------------------------------------------------------- 도우미
def _secs(a: _dt.datetime | None, b: _dt.datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round(max(0.0, (b - a).total_seconds()), 3)


def _csv(raw: str | None, allowed: tuple[str, ...], name: str) -> list[str] | None:
    if raw is None or not raw.strip():
        return None
    vals = [v.strip() for v in raw.split(",") if v.strip()]
    bad = [v for v in vals if v not in allowed]
    if bad:
        raise unprocessable("INVALID_PARAMS", f"{name} 에 알 수 없는 값: {', '.join(bad)}", allowed=list(allowed))
    return list(dict.fromkeys(vals))


def _aware(d: _dt.datetime | None) -> _dt.datetime | None:
    if d is not None and d.tzinfo is None:
        return d.replace(tzinfo=_dt.timezone.utc)
    return d


def _n_files(files: Any) -> int | None:
    return len(files) if isinstance(files, list) else None


# ---------------------------------------------------------------- 결과 상태 계산(H-6)
class Resolved:
    """작업 1건의 결과 연결: ref · result_state · stale_reasons (+ 상세에서 쓰는 case·run·val)."""

    def __init__(self) -> None:
        self.ref: dict[str, str] | None = None
        self.state: str | None = None
        self.reasons: list[str] = []
        self.case: dict[str, Any] | None = None
        self.run: dict[str, Any] | None = None
        self.val: dict[str, Any] | None = None
        self.summary: dict[str, Any] | None = None


class Batch:
    """작업 행 목록의 결과 상태 계산에 필요한 행을 일괄 조회해 둔다(쿼리 수 = 행 수와 무관)."""

    def __init__(self, ctx: AppContext, conn: Connection, rows: list[dict[str, Any]]) -> None:
        self.ctx = ctx
        self.conn = conn
        ok = [r for r in rows if r["state"] == SUCCEEDED]
        self.cases = repo.cases_by_ids(conn, sorted({r["case_id"] for r in rows if r["case_id"]}))
        self.analyses = repo.analyses_by_ids(conn, sorted({r["analysis_id"] for r in rows if r["analysis_id"]}))
        self.comparisons = repo.comparisons_by_ids(conn, sorted({r["comparison_id"] for r in rows
                                                                  if r["comparison_id"]}))
        self.opt_runs = opt_repo.runs_by_ids(conn, sorted({r["opt_run_id"] for r in rows if r.get("opt_run_id")}))
        self.retried_by = repo.retried_by(conn, [r["id"] for r in rows])
        esl_jobs = [r["id"] for r in ok if r["job_type"] == "ESL_SOLVE"]
        self.vals_by_job = repo.validations_by_jobs(conn, [r["id"] for r in ok if r["job_type"] == "VALIDATE"])
        run_ids = {v["esl_run_id"] for v in self.vals_by_job.values()}
        run_ids |= {r["p_run_id"] for r in ok if r["job_type"] in ("EXPORT", "CASE_REPORT")
                    and isinstance(r.get("p_run_id"), str)}
        runs = repo.runs_for(conn, sorted(run_ids), esl_jobs)
        self.runs = {r["id"]: r for r in runs}
        self.run_by_job = {r["job_id"]: r for r in runs}
        self.latest_val = repo.latest_validation_ids(conn, sorted({v["esl_run_id"] for v in self.vals_by_job.values()}))
        self.latest_jobs = repo.latest_success_jobs(
            conn, [(r["case_id"], r["job_type"]) for r in ok if r["job_type"] in ("EXPORT", "CASE_REPORT")
                   and r["case_id"]])
        self._fp: dict[str, bool] = {}

    # --- 입력 파일 지문(Case 단위 1회)
    def input_files_changed(self, case: dict[str, Any]) -> bool:
        cid = case["id"]
        if cid not in self._fp:
            fp = case.get("input_fingerprint") or {}
            try:
                self._fp[cid] = bool(fp) and bool(changed_inputs(fp))
            except (OSError, TypeError, ValueError, AttributeError):
                self._fp[cid] = False
        return self._fp[cid]

    def run_reasons(self, case: dict[str, Any], run: dict[str, Any] | None) -> set[str]:
        out: set[str] = set()
        if run is not None:
            past_title = run.get("past_part_title")
            if (isinstance(past_title, str) and past_title != case["part_title"]) or extract_stale(case):
                out.add("part_title")
            es = case.get("extract_summary") or {}
            h = inputs_hash(extract_job_id=es.get("job_id"),
                            part_title=past_title if isinstance(past_title, str) else case["part_title"],
                            tstar={"frame_index": run["frame_index"], "metric": run["metric"]},
                            support_set_id=run["support_set_id"])
            if h != run["inputs_hash"]:
                out.add("extract")
            ts = case.get("tstar") or {}
            if ts.get("frame_index") != run["frame_index"] or ts.get("metric") != run["metric"]:
                out.add("tstar")
            if case.get("current_support_set_id") != run["support_set_id"]:
                out.add("support_set")
        if self.input_files_changed(case):
            out.add("input_files")
        return out

    def resolve(self, row: dict[str, Any]) -> Resolved:
        res = Resolved()
        jt = row["job_type"]
        case = self.cases.get(row["case_id"]) if row["case_id"] else None
        res.case = case
        if row["state"] != SUCCEEDED:
            return res
        reasons: set[str] = set()
        if jt in ("LIB_ANALYZE", "LIB_COMPARE"):
            sub, key, kind = ((self.analyses.get(row["analysis_id"]), row["analysis_id"], "analysis")
                              if jt == "LIB_ANALYZE" else
                              (self.comparisons.get(row["comparison_id"]), row["comparison_id"], "comparison"))
            res.ref = {"kind": kind, "id": key}
            res.state = "current" if sub is not None and sub.get("job_id") == row["id"] else "past"
            return res
        if jt == "OPT_RUN":
            sub = self.opt_runs.get(row["opt_run_id"])
            res.ref = {"kind": "opt_run", "id": row["opt_run_id"]}
            res.state = "current" if sub is not None and sub.get("job_id") == row["id"] else "past"
            if sub is not None:
                rr = sub.get("result") or {}
                ls = rr.get("load_selection") or {}
                res.summary = {"scenario": sub.get("scenario"), "load_strategy": sub.get("load_strategy"),
                               "n_cases": ls.get("n_cases"), "converged": rr.get("converged")}
            return res
        if case is None:
            return res
        es = case.get("extract_summary") or {}
        if jt == "CASE_EXTRACT":
            res.ref = {"kind": "extract", "id": row["id"]}
            is_cur = es.get("job_id") == row["id"]
            res.state = "current" if is_cur else "past"
            if not is_cur:
                reasons.add("extract")
            title = row.get("p_extract_title") if isinstance(row.get("p_extract_title"), str) else \
                (es.get("requested_part_title") if is_cur else None)
            if title is not None and title != case["part_title"]:
                reasons.add("part_title")
            if self.input_files_changed(case):
                reasons.add("input_files")
            res.summary = {"n_elems": row.get("r_n_elems"), "tstar_frame": row.get("r_tstar_frame"),
                           "tstar_value": row.get("r_tstar_value")}
        elif jt == "ESL_SOLVE":
            run = self.run_by_job.get(row["id"])
            if run is None:
                return res
            res.run = run
            res.ref = {"kind": "esl_run", "id": run["id"]}
            res.state = "current" if (case.get("current_esl_run_id") == run["id"]
                                      and not esl_run_stale(case, run)) else "past"
            reasons = self.run_reasons(case, run)
            res.summary = {"frame_index": run["frame_index"], "metric": run["metric"]}
        elif jt == "VALIDATE":
            val = self.vals_by_job.get(row["id"])
            if val is None:
                return res
            run = self.runs.get(val["esl_run_id"])
            res.val, res.run = val, run
            res.ref = {"kind": "validation", "id": val["id"]}
            res.state = "current" if (case.get("current_esl_run_id") == val["esl_run_id"]
                                      and self.latest_val.get(val["esl_run_id"]) == val["id"]) else "past"
            reasons = self.run_reasons(case, run)
            res.summary = {"status": validation_status(val), "verdict": val["verdict"],
                           "disp_rms_rel": val["disp_rms_rel"], "disp_max_rel": val.get("disp_max_rel")}
        elif jt in ("EXPORT", "CASE_REPORT"):
            run = self.runs.get(row["p_run_id"]) if isinstance(row.get("p_run_id"), str) else None
            res.run = run
            res.ref = {"kind": "export" if jt == "EXPORT" else "report", "id": row["id"]}
            res.state = "current" if self.latest_jobs.get((case["id"], jt)) == row["id"] else "past"
            reasons = self.run_reasons(case, run)
            if jt == "EXPORT":
                res.summary = {"targets": row.get("r_targets"), "n_files": _n_files(row.get("r_files"))}
        res.reasons = [r for r in REASON_ORDER if r in reasons]
        return res


def _item(row: dict[str, Any], b: Batch, res: Resolved) -> dict[str, Any]:
    case = b.cases.get(row["case_id"]) if row["case_id"] else None
    sub = b.analyses.get(row["analysis_id"]) if row["analysis_id"] else (
        b.comparisons.get(row["comparison_id"]) if row["comparison_id"] else (
            b.opt_runs.get(row["opt_run_id"]) if row.get("opt_run_id") else None))
    now = row["db_now"]
    started, finished = row["started_at"], row["finished_at"]
    duration = _secs(started, finished) if finished is not None else (
        _secs(started, now) if started is not None and row["state"] == RUNNING else None)
    return {
        "id": row["id"], "job_type": row["job_type"], "stage": row["stage"], "state": row["state"],
        "case_id": row["case_id"], "case_title": case["title"] if case else None,
        "case_folder": case["folder_name"] if case else None,
        "analysis_id": row["analysis_id"], "comparison_id": row["comparison_id"], "opt_run_id": row.get("opt_run_id"),
        "subject_title": case["title"] if case else (sub.get("title") if sub else None),
        "created_by": row["created_by"], "created_by_name": row["created_by_name"], "created_at": row["created_at"],
        "queued_at": row["queued_at"], "started_at": started, "finished_at": finished,
        "duration_s": duration, "wait_s": _secs(row["queued_at"], started),
        "current_step_no": row["current_step_no"], "progress_pct": row["progress_pct"],
        "failure_code": row["failure_code"], "failure_message": row["failure_message"],
        "retry_of_job_id": row["retry_of_job_id"], "retried_by_job_id": b.retried_by.get(row["id"]),
        "result_ref": res.ref, "result_state": res.state, "stale": bool(res.reasons), "summary": res.summary,
    }


# ---------------------------------------------------------------- GET /history
def list_history(ctx: AppContext, principal: Principal, *, project_id: str, case_id: str | None, job_type: str | None,
                 state: str | None, mine: bool, q: str | None, dt_from: _dt.datetime | None,
                 dt_to: _dt.datetime | None, cursor: str | None, limit: int) -> dict[str, Any]:
    types = _csv(job_type, tuple(JOB_TYPES), "job_type")
    states = _csv(state, STATES, "state")
    q = (q or "").strip() or None
    after = decode_cursor(cursor) if cursor else None
    with ctx.engine.connect() as conn:
        if case_id:
            case = cases_repo.get_case(conn, case_id)
            if case is None or case["project_id"] != project_id:
                raise not_found("CASE_NOT_FOUND", "Case 를 찾을 수 없습니다")
        rows = repo.list_page(conn, project_id, case_id=case_id, job_types=types, states=states,
                              user_id=principal.user_id if mine else None, q=q, dt_from=_aware(dt_from),
                              dt_to=_aware(dt_to), after=after, limit=limit)
        has_more = len(rows) > limit
        rows = rows[:limit]
        b = Batch(ctx, conn, rows)
        items = [_item(r, b, b.resolve(r)) for r in rows]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if has_more and rows else None
    return {"items": items, "next_cursor": nxt, "has_more": has_more}


def _status_text(val: dict[str, Any]) -> str:
    """비교 행 "판정" 값 = status(계약 esl_disp_primary.md §7). 이전 판정 체계는 당시 verdict 를 덧붙여 구분한다."""
    st = validation_status(val)
    return f"{st}({val['verdict']})" if st == "LEGACY" else st


# ---------------------------------------------------------------- GET /jobs/{id}/review
def _settings_summary(params: dict[str, Any]) -> dict[str, Any]:
    st = params.get("settings") or {}
    val, cmp_ = st.get("validation") or {}, st.get("compare") or {}
    return {
        "criteria": {"disp_rms_rel_max": val.get("disp_rms_rel_max"),
                     "disp_max_rel_max": val.get("disp_max_rel_max"),
                     "disp_noise_rel_max": val.get("disp_noise_rel_max"),
                     "hotspot_strain_rel_err_max": val.get("hotspot_strain_rel_err_max"),
                     "reaction_rel_max": val.get("reaction_rel_max"),
                     "max_err_pct_max": cmp_.get("max_err_pct_max"), "p90_err_max": cmp_.get("p90_err_max")},
        "tstar_metric": (st.get("tstar") or {}).get("metric"),
        "material_override": (st.get("case") or {}).get("material_override") or {},
    }


def _fingerprint_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    fp = params.get("input_fingerprint") or {}
    out: list[dict[str, Any]] = []

    def add(kind: str, path: Any, ref: Any) -> None:
        ref = ref if isinstance(ref, dict) else {}
        out.append({"kind": kind, "path": path if isinstance(path, str) else None, "size": ref.get("size"),
                    "mtime": ref.get("mtime")})

    if isinstance(fp.get("rad"), dict):
        add("rad", fp["rad"].get("path"), fp["rad"])
    for inc in fp.get("includes") or []:
        if isinstance(inc, dict):
            add("include", inc.get("path"), inc)
    if isinstance(fp.get("h3d"), dict):
        add("h3d", fp["h3d"].get("path"), fp["h3d"])
    res = fp.get("results") or {}
    base = res.get("path") if isinstance(res, dict) else None
    if isinstance(res, dict) and isinstance(base, str):
        sep = "\\" if "\\" in base and "/" not in base else "/"
        for name, ref in (res.get("files") or {}).items():
            add("result", base.rstrip("/\\") + sep + str(name), ref)
    return out[:FINGERPRINT_MAX]


def _subject_dir(ctx: AppContext, conn: Connection, job: dict[str, Any]) -> str | None:
    if job.get("analysis_id"):
        return analysis_dir(ctx, lib_repo.get_analysis(conn, job["analysis_id"]))
    if job.get("comparison_id"):
        return analysis_dir(ctx, lib_repo.get_comparison(conn, job["comparison_id"]))
    if job.get("opt_run_id"):
        r = opt_repo.get_run(conn, job["opt_run_id"])
        return analysis_dir(ctx, r) if r else None
    case = cases_repo.get_case(conn, job["case_id"]) if job.get("case_id") else None
    return case_dir(ctx, case) if case else None


def _log_info(base: str | None, step: dict[str, Any]) -> dict[str, Any]:
    size, has = 0, False
    if base and step.get("log_rel"):
        try:
            p = safe_case_file(base, step["log_rel"])
            if os.path.isfile(p) and not os.path.islink(p):
                size, has = os.path.getsize(p), True
        except (DomainError, OSError):
            pass
    return {"step_no": step["step_no"], "step_key": step["step_key"], "state": step["state"], "has_log": has,
            "size": size}


def _same(a: Any, b: Any) -> bool:
    return a == b


def _diff(pairs: list[tuple[str, str, Any, Any]]) -> list[dict[str, Any]]:
    return [{"key": k, "label": lbl, "past": p, "current": c} for k, lbl, p, c in pairs if not _same(p, c)][:DIFF_MAX]


def _hotspot_max(hots: Any) -> float | None:
    vals = []
    for h in hots or []:
        try:
            if isinstance(h, dict) and h.get("rel_err") is not None:
                vals.append(abs(float(h["rel_err"])))
        except (TypeError, ValueError):
            continue
    return max(vals) if vals else None


def _kab(run: dict[str, Any] | None) -> Any:
    k = (run or {}).get("kabsch") or {}
    return k.get("bc_residual", k.get("rms_def"))


def _fnorm(run: dict[str, Any] | None) -> Any:
    f = (run or {}).get("forces") or {}
    return f.get("total_norm", f.get("sum_abs_f"))


def review(ctx: AppContext, principal: Principal, job_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        job = load_job(conn, job_id)
        steps = jobs_repo.get_steps(conn, job_id)
        jo = job_out(conn, job, with_steps=True)
        if principal.is_global_admin:
            cmd = {s["step_no"]: s.get("command") for s in steps}
            for s in jo["steps"]:
                s["command"] = cmd.get(s["step_no"])
        row = repo.list_rows_by_ids(conn, [job_id])[0]
        b = Batch(ctx, conn, [row])
        res = b.resolve(row)
        base = _subject_dir(ctx, conn, job)
        params = jo["params"]
        now = row["db_now"]
        timing_steps = [{
            "step_no": s["step_no"], "step_key": s["step_key"], "started_at": s["started_at"],
            "finished_at": s["finished_at"],
            "duration_s": _secs(s["started_at"], s["finished_at"]) if s["finished_at"] is not None else (
                _secs(s["started_at"], now) if s["started_at"] is not None and s["state"] == "RUNNING" else None)}
            for s in steps]
        item = _item(row, b, res)
        err: dict[str, Any] = {"warnings": list(job.get("warnings") or [])}
        if job["state"] in ("FAILED", "INTERRUPTED"):
            fs = next((s for s in steps if s["state"] == "FAILED"), None)
            err = {"failure_code": job["failure_code"], "failure_message": job["failure_message"],
                   "failed_step": None if fs is None else {
                       "step_no": fs["step_no"], "step_key": fs["step_key"], "exit_code": fs["exit_code"],
                       "failure_code": fs["failure_code"], "failure_message": fs["failure_message"]},
                   "warnings": err["warnings"]}
        result = _result_block(ctx, conn, job, row, b, res)
    return {
        "job": jo,
        "timing": {"queued_at": job["queued_at"], "started_at": job["started_at"], "finished_at": job["finished_at"],
                   "wait_s": item["wait_s"], "duration_s": item["duration_s"], "steps": timing_steps},
        "input": {"params": params, "settings_summary": _settings_summary(job["params"] or {}),
                  "input_fingerprint": _fingerprint_rows(job["params"] or {}) if job["job_type"] == "CASE_EXTRACT"
                  else None},
        "error": err,
        "logs": [_log_info(base, s) for s in steps],
        "result": result,
    }


def _file_rows(ctx: AppContext, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lim = ctx.settings.ui.max_artifact_bytes
    return [{"name": f["name"], "size": f["size"], "downloadable": f["size"] <= lim} for f in files]


def _result_block(ctx: AppContext, conn: Connection, job: dict[str, Any], row: dict[str, Any], b: Batch,
                  res: Resolved) -> dict[str, Any]:
    none = {"ref": None, "availability": "none", "state": None, "stale_reasons": [], "files_note": None, "past": {},
            "diff": [], "links": {}}
    if res.ref is None:
        return none
    jt = job["job_type"]
    case = res.case
    reg = repo.job_registered(conn, job["id"]) or {}
    past: dict[str, Any] = {}
    diff: list[dict[str, Any]] = []
    links: dict[str, Any] = {}
    full = False
    if jt == "CASE_EXTRACT":
        past = {"extract": reg.get("extract"), "tstar": reg.get("tstar")}
        full = res.state == "current"
        links = {"stage": 1}
        es = (case or {}).get("extract_summary")
        ts = (case or {}).get("tstar")
        pe, pt = reg.get("extract") or {}, reg.get("tstar") or {}
        ce = es or {}
        ct = ts or {}
        cur = es is not None
        diff = _diff([
            ("part_title", "대상 파트", pe.get("part_title"), ce.get("part_title") if cur else None),
            ("n_elems", "요소 수", pe.get("n_elems"), ce.get("n_elems") if cur else None),
            ("n_frames", "프레임 수", pe.get("n_frames"), ce.get("n_frames") if cur else None),
            ("tstar.frame_index", "t* 프레임", pt.get("frame_index"), ct.get("frame_index") if ts else None),
            ("tstar.metric", "t* 지표", pt.get("metric"), ct.get("metric") if ts else None),
            ("tstar.value", "t* 값", pt.get("value"), ct.get("value") if ts else None),
        ])
    elif jt == "ESL_SOLVE":
        run = res.run
        past = esl_run_out(case, cases_repo.get_esl_run(conn, run["id"]), conn)
        full = co.esl_source_dir(case_dir(ctx, case), run) is not None
        links = {"stage": 4, "query": {"run": run["id"]}}
        cur = cases_repo.get_esl_run(conn, case["current_esl_run_id"]) if case.get("current_esl_run_id") else None
        nodes = repo.support_node_ids(conn, [i for i in (run["support_set_id"], cur and cur["support_set_id"]) if i])
        diff = _diff([
            ("frame_index", "프레임", run["frame_index"], cur["frame_index"] if cur else None),
            ("metric", "t* 지표", run["metric"], cur["metric"] if cur else None),
            ("support_node_ids", "지지점 노드", nodes.get(run["support_set_id"]),
             nodes.get(cur["support_set_id"]) if cur else None),
            ("kabsch.bc_residual", "경계조건 잔차", _kab(run), _kab(cur) if cur else None),
            ("forces.total_norm", "하중 크기 합", _fnorm(run), _fnorm(cur) if cur else None),
        ])
    elif jt == "VALIDATE":
        val = cases_repo.get_validation(conn, res.val["id"])
        run = cases_repo.get_esl_run(conn, val["esl_run_id"])
        latest = cases_repo.list_validations(conn, case_id=case["id"])
        loc = locate_validation_dir(ctx, case, val, latest[0]["id"] if latest else None)
        has_field = bool(loc) and os.path.isfile(os.path.join(loc[0], "compare_field.npz")) \
            and not os.path.islink(os.path.join(loc[0], "compare_field.npz"))
        past = {**validation_out(case, run, val), "has_field": has_field}
        full = has_field
        links = {"stage": 5, "query": {"val": val["id"]}}
        cv = None
        if case.get("current_esl_run_id"):
            vs = cases_repo.list_validations(conn, esl_run_id=case["current_esl_run_id"])
            cv = vs[0] if vs else None
        diff = _diff([
            ("verdict", "판정", _status_text(val), _status_text(cv) if cv else None),
            ("disp_rms_rel", "변위 RMS 상대오차", val["disp_rms_rel"], cv["disp_rms_rel"] if cv else None),
            ("reaction_rel", "반력 상대오차", val["reaction_rel"], cv["reaction_rel"] if cv else None),
            ("hotspot_max_err", "hotspot 최대 오차", _hotspot_max(val["hotspots"]),
             _hotspot_max(cv["hotspots"]) if cv else None),
            ("criteria", "판정 기준", val["criteria"], cv["criteria"] if cv else None),
        ])
    elif jt == "EXPORT":
        hist = co.history_files(case_dir(ctx, case), "EXPORT", job["id"])
        if hist:
            files = _file_rows(ctx, hist)
        else:
            files = [{"name": str(n), "size": None, "downloadable": False} for n in (reg.get("files") or [])]
        past = {"targets": reg.get("targets"), "id_range": reg.get("id_range"),
                "validation_verdict": reg.get("validation_verdict"), "files": files,
                "warnings": list(reg.get("warnings") or [])}
        full = bool(hist)
        links = {"stage": 6}
        lj = b.latest_jobs.get((case["id"], "EXPORT"))
        creg = (repo.job_registered(conn, lj) if lj and lj != job["id"] else reg) if lj else None
        cr = creg or {}
        diff = _diff([
            ("targets", "내보내기 대상", reg.get("targets"), cr.get("targets") if creg else None),
            ("id_range", "ID 범위", reg.get("id_range"), cr.get("id_range") if creg else None),
            ("files", "파일 수", _n_files(reg.get("files")), _n_files(cr.get("files")) if creg else None),
            ("validation_verdict", "검증 판정", reg.get("validation_verdict"),
             cr.get("validation_verdict") if creg else None),
        ])
    elif jt == "CASE_REPORT":
        past = {"verdict": reg.get("verdict"), "bytes": reg.get("bytes")}
        full = bool(co.history_files(case_dir(ctx, case), "CASE_REPORT", job["id"]))
        links = {"stage": 7}
    else:  # LIB_ANALYZE · LIB_COMPARE · OPT_RUN: 과거 값 재현 비범위 — 요약만 + 현재 분석·비교·최적화 열기
        past = dict(reg)
        if jt == "LIB_ANALYZE":
            links = {"stage": 8, "query": {"analysis": job["analysis_id"]}}
        elif jt == "OPT_RUN":
            links = {"stage": 10, "query": {"opt": job["opt_run_id"]}}
        else:
            links = {"stage": 9, "query": {"comparison": job["comparison_id"]}}
    avail = "full" if full else "summary"
    return {"ref": res.ref, "availability": avail, "state": res.state, "stale_reasons": res.reasons,
            "files_note": None if full else FILES_NOTE, "past": past, "diff": diff, "links": links}


# ---------------------------------------------------------------- 과거 파일(H-5)
def _history_job(ctx: AppContext, job_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    with ctx.engine.connect() as conn:
        job = load_job(conn, job_id)
        case = cases_repo.get_case(conn, job["case_id"]) if job.get("case_id") else None
    if case is None or job["job_type"] not in ("EXPORT", "CASE_REPORT"):
        raise not_found("HISTORY_FILES_GONE", "이 작업의 보존 파일이 없습니다")
    return job, case, case_dir(ctx, case)


def job_files(ctx: AppContext, job_id: str) -> list[dict[str, Any]]:
    job, _case, cdir = _history_job(ctx, job_id)
    files = co.history_files(cdir, job["job_type"], job_id)
    if not files:
        raise not_found("HISTORY_FILES_GONE", "이 작업의 보존 파일이 없습니다(이 기능 이전 실행이거나 보존이 꺼져 있었습니다)")
    return _file_rows(ctx, files)


def job_file(ctx: AppContext, job_id: str, name: str) -> tuple[str, str]:
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name or ".." in name:
        raise unprocessable("PATH_UNSAFE", "잘못된 파일 이름")
    job, _case, cdir = _history_job(ctx, job_id)
    path = co.history_file_path(cdir, job["job_type"], job_id, name)
    if path is None:
        raise not_found("HISTORY_FILES_GONE", "보존 파일이 없습니다")
    size = os.path.getsize(path)
    lim = ctx.settings.ui.max_artifact_bytes
    if size > lim:
        raise DomainError("ARTIFACT_TOO_LARGE", "파일이 커서 다운로드할 수 없습니다. 경로를 복사해 여세요", status=413,
                          rel=f"{co.HISTORY_DIR}/{job_id}/{name}", path=path, size=size, limit=lim)
    return path, name


def job_report(ctx: AppContext, job_id: str) -> tuple[str, str]:
    job, case, cdir = _history_job(ctx, job_id)
    if job["job_type"] != "CASE_REPORT":
        raise not_found("HISTORY_FILES_GONE", "이 작업의 보존 보고서가 없습니다")
    path = co.history_file_path(cdir, "CASE_REPORT", job_id, co.HISTORY_REPORT)
    if path is None:
        raise not_found("HISTORY_FILES_GONE", "이 작업의 보존 보고서가 없습니다")
    return path, f"{case['folder_name']}_report_{job_id[:8]}.html"
