"""일괄 실행 체인 저장소(계약 esl_run_all.md §2·§5). 호출자가 트랜잭션을 연다.

전이(RUNNING → STOPPED·DONE·CANCELED)는 모두 행 FOR UPDATE 아래에서 `finish` 로만(종료 상태에서 다른 상태로 가지 않음).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Connection

from ..db.tables import jobs, run_alls
from ..state_machine import TERMINAL
from . import row_dict

RUNNING = "RUNNING"
TERMINAL_RUN = ("STOPPED", "DONE", "CANCELED")


def insert_run(conn: Connection, *, case_id: str, project_id: str, from_step: str, core_settings: dict[str, Any],
               created_by: str, created_by_name: str, prev_user_tstar: dict[str, Any] | None = None,
               resumed_from_id: str | None = None) -> dict[str, Any]:
    """RUNNING 행 1개. 같은 Case 에 RUNNING 행이 있으면 ux_run_alls_case_running 위반(IntegrityError) → 호출자가 409."""
    rid = str(uuid.uuid4())
    conn.execute(insert(run_alls).values(
        id=rid, case_id=case_id, project_id=project_id, from_step=from_step, status=RUNNING,
        core_settings=core_settings, prev_user_tstar=prev_user_tstar, resumed_from_id=resumed_from_id,
        created_by=created_by, created_by_name=created_by_name, job_ids=[], skipped=[]))
    return get_run(conn, rid)


def get_run(conn: Connection, run_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(run_alls).where(run_alls.c.id == run_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def running_for_case(conn: Connection, case_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(run_alls).where(and_(run_alls.c.case_id == case_id, run_alls.c.status == RUNNING))
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def waiting_on(conn: Connection, job_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    """이 작업을 기다리는 RUNNING 체인(없으면 None)."""
    q = select(run_alls).where(and_(run_alls.c.status == RUNNING, run_alls.c.cur_job_id == job_id))
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def latest_for_case(conn: Connection, case_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(run_alls).where(run_alls.c.case_id == case_id)
                                 .order_by(run_alls.c.created_at.desc(), run_alls.c.id.desc()).limit(1)).first())


def list_for_case(conn: Connection, case_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(select(run_alls).where(run_alls.c.case_id == case_id)
                        .order_by(run_alls.c.created_at.desc(), run_alls.c.id.desc()).limit(limit)).all()
    return [row_dict(r) for r in rows]


def update_run(conn: Connection, run_id: str, **values: Any) -> dict[str, Any]:
    conn.execute(update(run_alls).where(run_alls.c.id == run_id).values(updated_at=func.now(), **values))
    return get_run(conn, run_id)


def finish(conn: Connection, run: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    """RUNNING → 종료 상태(1회만). 이미 종료면 AssertionError(호출자가 RUNNING 행을 잠근 뒤 부른다)."""
    assert status in TERMINAL_RUN, status
    r = conn.execute(update(run_alls).where(and_(run_alls.c.id == run["id"], run_alls.c.status == RUNNING))
                     .values(status=status, finished_at=func.now(), updated_at=func.now(), **values))
    assert r.rowcount == 1, "run_all 종료 전이는 RUNNING 행에서 1회만"
    return get_run(conn, run["id"])


def orphaned(conn: Connection, limit: int = 20) -> list[dict[str, Any]]:
    """끊김 복구(§5): RUNNING 인데 cur_job_id 작업이 이미 종료된 행."""
    rows = conn.execute(
        select(run_alls).select_from(run_alls.join(jobs, jobs.c.id == run_alls.c.cur_job_id))
        .where(and_(run_alls.c.status == RUNNING, jobs.c.state.in_(list(TERMINAL))))
        .order_by(run_alls.c.updated_at).limit(limit)
    ).all()
    return [row_dict(r) for r in rows]


def later_running(conn: Connection, run: dict[str, Any]) -> bool:
    return conn.execute(select(run_alls.c.id).where(and_(
        run_alls.c.case_id == run["case_id"], run_alls.c.status == RUNNING, run_alls.c.id != run["id"],
        run_alls.c.created_at >= run["created_at"])).limit(1)).first() is not None


def superseded(conn: Connection, run: dict[str, Any]) -> bool:
    """종료 뒤 이 체인과 무관한 그 Case 의 ①③④ 작업이 새로 생김."""
    if run["status"] == RUNNING or run.get("finished_at") is None:
        return False
    mine = run["id"]
    return conn.execute(select(jobs.c.id).where(and_(
        jobs.c.case_id == run["case_id"], jobs.c.job_type.in_(["CASE_EXTRACT", "ESL_SOLVE", "VALIDATE"]),
        jobs.c.created_at > run["finished_at"],
        (jobs.c.run_all_id.is_(None)) | (jobs.c.run_all_id != mine))).limit(1)).first() is not None
