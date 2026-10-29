"""실행 이력 조회(계약 esl_p3_history.md §3): jobs 행 keyset 목록 + 목록에 필요한 행의 일괄 조회(N+1 없음).

모두 읽기 전용. 목록 쿼리는 params·result 원문을 가져오지 않고 필요한 스칼라만 JSON 경로로 뽑는다.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import and_, column, func, literal, or_, select, true, tuple_, values
from sqlalchemy.engine import Connection
from sqlalchemy.types import String

from ..db.tables import analysis_runs, bead_does, cases, comparisons, esl_runs, jobs, opt_runs, support_sets, validations
from . import row_dict

LIST_COLUMNS = (
    jobs.c.id, jobs.c.case_id, jobs.c.analysis_id, jobs.c.comparison_id, jobs.c.opt_run_id, jobs.c.bead_doe_id,
    jobs.c.project_id,
    jobs.c.job_type,
    jobs.c.stage, jobs.c.state, jobs.c.queued_at, jobs.c.started_at, jobs.c.finished_at, jobs.c.current_step_no,
    jobs.c.progress_pct, jobs.c.failure_code, jobs.c.failure_message, jobs.c.retry_of_job_id, jobs.c.created_by,
    jobs.c.created_by_name, jobs.c.created_at,
    # params·result 에서 필요한 스칼라만(원문은 목록에 넣지 않는다)
    jobs.c.params[("settings", "case", "part_title")].label("p_part_title"),   # ESL 실행 당시 part_title
    jobs.c.params["part_title"].label("p_extract_title"),                        # 추출 요청 part_title
    jobs.c.params["esl_run_id"].label("p_run_id"),                               # 내보내기·보고서 대상 ESL 실행
    jobs.c.params["origin"].astext.label("p_origin"),                            # v0.10.0 library(라이브러리 내보내기)·library_revalidate
    jobs.c.result[("registered", "n_items")].label("r_n_items"),                 # v0.10.0 라이브러리 내보내기 항목 수
    jobs.c.result[("registered", "extract", "n_elems")].label("r_n_elems"),
    jobs.c.result[("registered", "tstar", "frame_index")].label("r_tstar_frame"),
    jobs.c.result[("registered", "tstar", "value")].label("r_tstar_value"),
    jobs.c.result[("registered", "targets")].label("r_targets"),
    jobs.c.result[("registered", "files")].label("r_files"),
    func.now().label("db_now"),
)


def escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_page(conn: Connection, project_id: str, *, case_id: str | None, job_types: list[str] | None,
              states: list[str] | None, user_id: str | None, q: str | None, dt_from: _dt.datetime | None,
              dt_to: _dt.datetime | None, after: tuple[_dt.datetime, str] | None, limit: int) -> list[dict[str, Any]]:
    """created_at DESC, id DESC 로 limit+1 행(다음 페이지 유무 판단용)."""
    w = [jobs.c.project_id == project_id]
    if case_id:
        w.append(jobs.c.case_id == case_id)
    if job_types:
        w.append(jobs.c.job_type.in_(job_types))
    if states:
        w.append(jobs.c.state.in_(states))
    if user_id:
        w.append(jobs.c.created_by == user_id)
    if dt_from is not None:
        w.append(jobs.c.created_at >= dt_from)
    if dt_to is not None:
        w.append(jobs.c.created_at <= dt_to)
    if q:
        pat = f"%{escape_like(q)}%"
        conds = [
            jobs.c.case_id.in_(select(cases.c.id).where(and_(cases.c.project_id == project_id, or_(
                cases.c.title.ilike(pat, escape="\\"), cases.c.folder_name.ilike(pat, escape="\\"))))),
            jobs.c.analysis_id.in_(select(analysis_runs.c.id).where(and_(
                analysis_runs.c.project_id == project_id, analysis_runs.c.title.ilike(pat, escape="\\")))),
            jobs.c.comparison_id.in_(select(comparisons.c.id).where(and_(
                comparisons.c.project_id == project_id, comparisons.c.title.ilike(pat, escape="\\")))),
            jobs.c.opt_run_id.in_(select(opt_runs.c.id).where(and_(
                opt_runs.c.project_id == project_id, opt_runs.c.title.ilike(pat, escape="\\")))),
            jobs.c.bead_doe_id.in_(select(bead_does.c.id).where(and_(
                bead_does.c.project_id == project_id, bead_does.c.title.ilike(pat, escape="\\")))),
        ]
        if len(q) >= 8 and all(ch in "0123456789abcdefABCDEF-" for ch in q):
            conds.append(jobs.c.id.like(escape_like(q.lower()) + "%", escape="\\"))
        w.append(or_(*conds))
    if after is not None:
        w.append(tuple_(jobs.c.created_at, jobs.c.id) < tuple_(literal(after[0]), literal(after[1])))
    stmt = select(*LIST_COLUMNS).where(and_(*w)).order_by(jobs.c.created_at.desc(), jobs.c.id.desc()).limit(limit + 1)
    return [row_dict(r) for r in conn.execute(stmt).all()]


def cases_by_ids(conn: Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    return {r.id: row_dict(r) for r in conn.execute(select(cases).where(cases.c.id.in_(ids))).all()}


def analyses_by_ids(conn: Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    cols = (analysis_runs.c.id, analysis_runs.c.title, analysis_runs.c.job_id)
    return {r.id: row_dict(r) for r in conn.execute(select(*cols).where(analysis_runs.c.id.in_(ids))).all()}


def comparisons_by_ids(conn: Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    cols = (comparisons.c.id, comparisons.c.title, comparisons.c.job_id)
    return {r.id: row_dict(r) for r in conn.execute(select(*cols).where(comparisons.c.id.in_(ids))).all()}


def retried_by(conn: Connection, job_ids: list[str]) -> dict[str, str]:
    """작업 id → 그 작업을 재시도한 가장 최근 작업 id."""
    if not job_ids:
        return {}
    rows = conn.execute(
        select(jobs.c.retry_of_job_id, jobs.c.id).where(jobs.c.retry_of_job_id.in_(job_ids))
        .order_by(jobs.c.created_at, jobs.c.id)).all()
    return {r[0]: r[1] for r in rows}      # 나중 행이 덮어씀 → 최신


def runs_for(conn: Connection, run_ids: list[str], job_ids: list[str]) -> list[dict[str, Any]]:
    """id ∈ run_ids 또는 job_id ∈ job_ids 인 ESL 실행 + 그 실행을 만든 작업의 당시 part_title(`past_part_title`)."""
    conds = []
    if run_ids:
        conds.append(esl_runs.c.id.in_(run_ids))
    if job_ids:
        conds.append(esl_runs.c.job_id.in_(job_ids))
    if not conds:
        return []
    stmt = (select(esl_runs, jobs.c.params[("settings", "case", "part_title")].label("past_part_title"))
            .select_from(esl_runs.join(jobs, jobs.c.id == esl_runs.c.job_id)).where(or_(*conds)))
    return [row_dict(r) for r in conn.execute(stmt).all()]


def validations_by_jobs(conn: Connection, job_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not job_ids:
        return {}
    cols = (validations.c.id, validations.c.job_id, validations.c.esl_run_id, validations.c.case_id,
            validations.c.verdict, validations.c.scheme, validations.c.disp_rms_rel, validations.c.disp_max_rel,
            validations.c.reaction_rel, validations.c.created_at)
    return {r.job_id: row_dict(r) for r in conn.execute(select(*cols).where(validations.c.job_id.in_(job_ids))).all()}


def validations_by_ids(conn: Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    return {r.id: row_dict(r) for r in conn.execute(select(validations).where(validations.c.id.in_(ids))).all()}


def latest_validation_ids(conn: Connection, run_ids: list[str]) -> dict[str, str]:
    """ESL 실행 id → 그 실행의 가장 최근 검증 id."""
    if not run_ids:
        return {}
    rn = func.row_number().over(partition_by=validations.c.esl_run_id,
                                order_by=(validations.c.created_at.desc(), validations.c.id.desc())).label("rn")
    sub = select(validations.c.esl_run_id, validations.c.id, rn).where(validations.c.esl_run_id.in_(run_ids)).subquery()
    rows = conn.execute(select(sub.c.esl_run_id, sub.c.id).where(sub.c.rn == 1)).all()
    return {r[0]: r[1] for r in rows}


def latest_success_jobs(conn: Connection, pairs: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """(case_id, job_type) → 가장 최근 SUCCEEDED 작업 id. 한 문장(LATERAL)으로 조회한다(쌍마다 index 로 1건)."""
    if not pairs:
        return {}
    pv = values(column("case_id", String), column("job_type", String), name="pairs").data(sorted(set(pairs)))
    # v0.10.0: 라이브러리 내보내기(params.origin = library)는 Case 의 ⑥ 결과가 아니므로 제외(MR-D-7)
    sub = (select(jobs.c.id).where(and_(jobs.c.case_id == pv.c.case_id, jobs.c.job_type == pv.c.job_type,
                                        jobs.c.state == "SUCCEEDED", jobs.c.params["origin"].astext.is_(None)))
           .order_by(jobs.c.created_at.desc(), jobs.c.id.desc()).limit(1).lateral("latest"))
    stmt = select(pv.c.case_id, pv.c.job_type, sub.c.id).select_from(pv.join(sub, true()))
    return {(r[0], r[1]): r[2] for r in conn.execute(stmt).all()}


def support_node_ids(conn: Connection, ids: list[str]) -> dict[str, list[int]]:
    if not ids:
        return {}
    rows = conn.execute(select(support_sets.c.id, support_sets.c.node_ids).where(support_sets.c.id.in_(ids))).all()
    return {r[0]: [int(x) for x in (r[1] or [])] for r in rows}


def job_registered(conn: Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute(select(jobs.c.result["registered"]).where(jobs.c.id == job_id)).first()
    return row[0] if row else None


def list_rows_by_ids(conn: Connection, ids: list[str]) -> list[dict[str, Any]]:
    """list_page 와 같은 열 모양의 행(상세에서 같은 결과 상태 계산을 쓰기 위함)."""
    if not ids:
        return []
    return [row_dict(r) for r in conn.execute(select(*LIST_COLUMNS).where(jobs.c.id.in_(ids))).all()]
