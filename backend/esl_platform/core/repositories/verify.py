"""검증 낙하 저장소(계약 esl_scx_relay.md §11): verify_drops + scx_submissions + 검증별 작업 조회. 호출자가 트랜잭션을 연다.

- verify_drops.version: 낙관적 잠금(`update_drop(expect_version=)`), 갱신마다 1 증가.
- scx_submissions: request_id(PK) = `esl-vd-<verify_drop_id>-a<attempt>`. 삭제 없음. 상태 SUBMITTING → SUBMITTED·UNKNOWN·FAILED,
  UNKNOWN → ATTACHED·ABANDONED(사람 확인).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Connection

from ..db.tables import jobs, scx_submissions, verify_drops
from . import row_dict
from .cases import VersionConflict

TERMINAL = ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")
DROP_TERMINAL = ("DONE", "FAILED", "CANCELED")


def request_id(drop_id: str, attempt: int) -> str:
    return f"esl-vd-{drop_id}-a{int(attempt)}"


def insert_drop(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(insert(verify_drops).values(**values))
    return get_drop(conn, values["id"])


def get_drop(conn: Connection, did: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(verify_drops).where(verify_drops.c.id == did)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def list_drops(conn: Connection, *, bead_doe_id: str | None = None, batch_id: str | None = None,
               limit: int = 200) -> list[dict[str, Any]]:
    q = select(verify_drops)
    if bead_doe_id:
        q = q.where(verify_drops.c.bead_doe_id == bead_doe_id)
    if batch_id:
        q = q.where(verify_drops.c.batch_id == batch_id)
    rows = conn.execute(q.order_by(verify_drops.c.created_at.desc(), verify_drops.c.id).limit(limit)).all()
    return [row_dict(r) for r in rows]


def active_keys(conn: Connection, bead_doe_id: str, design_id: str) -> set[str]:
    """같은 (스터디, 안)의 비종료 검증 Case id 집합(SR-D-10 '비종료 1개')."""
    rows = conn.execute(select(verify_drops.c.case_id).where(and_(
        verify_drops.c.bead_doe_id == bead_doe_id, verify_drops.c.design_id == design_id,
        verify_drops.c.phase.notin_(list(DROP_TERMINAL))))).all()
    return {r.case_id for r in rows}


def update_drop(conn: Connection, did: str, *, expect_version: int | None = None, **values: Any) -> dict[str, Any]:
    cond = verify_drops.c.id == did
    if expect_version is not None:
        cond = and_(cond, verify_drops.c.version == int(expect_version))
    r = conn.execute(update(verify_drops).where(cond).values(updated_at=func.now(), version=verify_drops.c.version + 1,
                                                            **values))
    if r.rowcount != 1:
        raise VersionConflict(did)
    return get_drop(conn, did)


def drop_jobs(conn: Connection, did: str) -> list[dict[str, Any]]:
    rows = conn.execute(select(jobs).where(jobs.c.verify_drop_id == did).order_by(jobs.c.created_at, jobs.c.id)).all()
    return [row_dict(r) for r in rows]


def latest_job(conn: Connection, did: str, job_type: str | None = None) -> dict[str, Any] | None:
    q = select(jobs).where(jobs.c.verify_drop_id == did)
    if job_type:
        q = q.where(jobs.c.job_type == job_type)
    return row_dict(conn.execute(q.order_by(jobs.c.created_at.desc(), jobs.c.id.desc()).limit(1)).first())


def completed_hours(conn: Connection, project_id: str, limit: int = 50) -> list[float]:
    """같은 프로젝트 완료 검증(DONE)의 VERIFY_DROP 작업 시간(시간) — 예상 시간 중앙값용."""
    rows = conn.execute(
        select(jobs.c.started_at, jobs.c.finished_at)
        .select_from(jobs.join(verify_drops, jobs.c.verify_drop_id == verify_drops.c.id))
        .where(and_(verify_drops.c.project_id == project_id, verify_drops.c.phase == "DONE",
                    jobs.c.job_type == "VERIFY_DROP", jobs.c.state == "SUCCEEDED",
                    jobs.c.started_at.isnot(None), jobs.c.finished_at.isnot(None)))
        .order_by(jobs.c.finished_at.desc()).limit(limit)).all()
    return [max(0.0, (r.finished_at - r.started_at).total_seconds() / 3600.0) for r in rows]


# ---------------------------------------------------------------- 제출 기록(SR-D-11)
def get_submission(conn: Connection, rid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(scx_submissions).where(scx_submissions.c.request_id == rid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def latest_submission(conn: Connection, did: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = (select(scx_submissions).where(scx_submissions.c.verify_drop_id == did)
         .order_by(scx_submissions.c.attempt.desc()).limit(1))
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def insert_submission(conn: Connection, *, verify_drop_id: str, attempt: int, request_sha256: str) -> dict[str, Any]:
    rid = request_id(verify_drop_id, attempt)
    conn.execute(insert(scx_submissions).values(request_id=rid, verify_drop_id=verify_drop_id, attempt=int(attempt),
                                                request_sha256=request_sha256, state="SUBMITTING"))
    return get_submission(conn, rid)


def update_submission(conn: Connection, rid: str, **values: Any) -> dict[str, Any]:
    conn.execute(update(scx_submissions).where(scx_submissions.c.request_id == rid)
                 .values(updated_at=func.now(), **values))
    return get_submission(conn, rid)


def job_id_in_use(conn: Connection, scx_job_id: str, except_rid: str | None = None) -> bool:
    q = select(func.count()).select_from(scx_submissions).where(scx_submissions.c.scx_job_id == scx_job_id)
    if except_rid:
        q = q.where(scx_submissions.c.request_id != except_rid)
    return int(conn.execute(q).scalar_one()) > 0


__all__ = ["request_id", "insert_drop", "get_drop", "list_drops", "active_keys", "update_drop", "drop_jobs", "latest_job",
           "completed_hours", "get_submission", "latest_submission", "insert_submission", "update_submission",
           "job_id_in_use", "DROP_TERMINAL"]
