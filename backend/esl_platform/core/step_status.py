"""Case 단계 상태(API·일괄 실행 훅 공용, v0.13.0 에 services/cases.py 에서 옮김 — 동작 불변).

`stage_status` = 옛 1..6 단계, `step_status` = 화면 4단계 {input, tstar, esl, validate}(esl_menu_restructure.md §5.4).
"""

from __future__ import annotations

from typing import Any

from .db.tables import jobs as jobs_t
from .inputs import esl_run_stale, extract_stale
from .repositories import cases as cases_repo
from .repositories import jobs as jobs_repo
from .state_machine import FAILED, INTERRUPTED, QUEUED, RUNNING, SUCCEEDED

ACTIVE_STATES = (QUEUED, RUNNING)


def _latest_case_export(conn, case_id: str) -> dict[str, Any] | None:
    """Case 단위 EXPORT(params.origin 없음)의 최신 작업 — 라이브러리 내보내기(origin=library)는 ⑥ 상태에 영향 없음(MR-D-7)."""
    from sqlalchemy import and_, select

    from .repositories import row_dict

    return row_dict(conn.execute(
        select(jobs_t).where(and_(jobs_t.c.case_id == case_id, jobs_t.c.job_type == "EXPORT",
                                  jobs_t.c.params["origin"].astext.is_(None)))
        .order_by(jobs_t.c.created_at.desc()).limit(1)).first())


def stage_status(conn, case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest = {jt: jobs_repo.latest_job(conn, case["id"], jt) for jt in ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE")}
    latest["EXPORT"] = _latest_case_export(conn, case["id"])

    def st(state: str, job: dict | None = None) -> dict[str, Any]:
        return {"state": state, "job_id": job["id"] if job else None}

    def failed(j: dict | None) -> bool:
        return j is not None and j["state"] in (FAILED, INTERRUPTED)

    out: dict[str, dict[str, Any]] = {}
    ex = latest["CASE_EXTRACT"]
    ex_stale = extract_stale(case)
    if ex and ex["state"] in ACTIVE_STATES:
        out["1"] = st("running", ex)
        out["2"] = st("running", ex)
    else:
        if case.get("extract_summary"):
            out["1"] = st("stale" if ex_stale else "done", ex)
        else:
            out["1"] = st("failed" if failed(ex) else "none", ex)
        if case.get("tstar"):
            out["2"] = st("stale" if ex_stale else "done")
        else:
            out["2"] = st("failed" if failed(ex) else "none", ex)
    out["3"] = st(("stale" if ex_stale else "done") if case.get("current_support_set_id") else "none")

    run = cases_repo.get_esl_run(conn, case["current_esl_run_id"]) if case.get("current_esl_run_id") else None
    run_stale = esl_run_stale(case, run) if run else False
    es = latest["ESL_SOLVE"]
    if es and es["state"] in ACTIVE_STATES:
        out["4"] = st("running", es)
    elif run:
        out["4"] = st("stale" if run_stale else "done", es)
    else:
        out["4"] = st("failed" if failed(es) else "none", es)

    va = latest["VALIDATE"]
    vals = cases_repo.list_validations(conn, esl_run_id=run["id"]) if run else []
    if va and va["state"] in ACTIVE_STATES:
        out["5"] = st("running", va)
    elif vals:
        out["5"] = st("stale" if run_stale else "done", va)
    else:
        out["5"] = st("failed" if failed(va) else "none", va)

    ep = latest["EXPORT"]
    if ep and ep["state"] in ACTIVE_STATES:
        out["6"] = st("running", ep)
    elif ep and ep["state"] == SUCCEEDED and run and (ep["params"] or {}).get("esl_run_id") == run["id"]:
        out["6"] = st("stale" if run_stale else "done", ep)
    else:
        out["6"] = st("failed" if failed(ep) else "none", ep)
    return out


REASON_MESSAGES = {
    "SUPPORT_AUTO_BLOCKED": "지지점을 자동으로 정하지 못했습니다 — ②에서 사유 확인",
    "TSTAR_NOT_CONFIRMED": "t* 확정이 필요합니다(확정 시 지지점 자동 선택)",
}


def step_status(case: dict[str, Any], ss: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """화면 4단계(§5.4): input = 옛 1, tstar = t*·지지점, esl = 옛 4, validate = 옛 5."""
    def r(code: str) -> dict[str, str]:
        return {"code": code, "message": REASON_MESSAGES[code]}

    t2 = dict(ss["2"])
    ts = case.get("tstar")
    if t2["state"] != "running" and ts:
        auto = (ts.get("support_auto") or {}) if isinstance(ts, dict) else {}
        if extract_stale(case):
            t2 = {"state": "stale", "job_id": None}
        elif case.get("current_support_set_id"):
            t2 = {"state": "done", "job_id": None}
        elif auto.get("status") == "BLOCKED":
            t2 = {"state": "failed", "job_id": None, "reason": r("SUPPORT_AUTO_BLOCKED")}
        else:
            t2 = {"state": "none", "job_id": None, "reason": r("TSTAR_NOT_CONFIRMED")}
    return {"input": dict(ss["1"]), "tstar": t2, "esl": dict(ss["4"]), "validate": dict(ss["5"])}
