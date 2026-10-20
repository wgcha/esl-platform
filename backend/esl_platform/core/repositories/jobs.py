"""작업·step 저장소: 생성(E1), claim(E2, SLOT CAS·LIGHT 1개·Case 당 RUNNING 1개), 취소(E3/E7), 종료(E5~E7), 리퍼(E8).

호출자가 트랜잭션을 연다(`with engine.begin() as conn`). lease_token 은 이 계층 밖(API 응답)으로 나가지 않는다.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, exists, func, insert, literal, select, update
from sqlalchemy.engine import Connection

from ..db.tables import job_queue_seq, job_steps, jobs, notifications, worker_slot
from ..errors import LeaseLost
from ..job_types import JOB_TYPES
from ..state_machine import (
    CANCELED,
    FAILED,
    INTERRUPTED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    TERMINAL,
    check_transition,
)
from . import row_dict

LEASE_COLUMNS = ("lease_owner_id", "lease_token", "lease_generation", "lease_acquired_at", "lease_expires_at")
_NO_LEASE = dict(lease_owner_id=None, lease_token=None, lease_acquired_at=None, lease_expires_at=None)


class ClaimRace(RuntimeError):
    pass


def _ttl(seconds: float) -> Any:
    return func.now() + literal(timedelta(seconds=float(seconds)))


# ---------------------------------------------------------------- 조회
def get_job(conn: Connection, job_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(jobs).where(jobs.c.id == job_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def get_steps(conn: Connection, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(select(job_steps).where(job_steps.c.job_id == job_id).order_by(job_steps.c.step_no)).all()
    return [row_dict(r) for r in rows]


def list_case_jobs(conn: Connection, case_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(jobs).where(jobs.c.case_id == case_id).order_by(jobs.c.created_at.desc()).limit(limit)
    ).all()
    return [row_dict(r) for r in rows]


def latest_job(conn: Connection, case_id: str, job_type: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(
        select(jobs).where(and_(jobs.c.case_id == case_id, jobs.c.job_type == job_type))
        .order_by(jobs.c.created_at.desc()).limit(1)
    ).first())


def has_active_jobs(conn: Connection, case_id: str) -> bool:
    return conn.execute(
        select(jobs.c.id).where(and_(jobs.c.case_id == case_id, jobs.c.state.notin_(list(TERMINAL)))).limit(1)
    ).first() is not None


def queue_lane(conn: Connection, lane: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    running = row_dict(conn.execute(
        select(jobs).where(and_(jobs.c.lane == lane, jobs.c.state == RUNNING)).order_by(jobs.c.started_at).limit(1)
    ).first())
    queued = [row_dict(r) for r in conn.execute(
        select(jobs).where(and_(jobs.c.lane == lane, jobs.c.state == QUEUED)).order_by(jobs.c.queue_seq)
    ).all()]
    return running, queued


# ---------------------------------------------------------------- 생성(E1)
def insert_job(
    conn: Connection,
    *,
    case_id: str | None,
    project_id: str,
    job_type: str,
    params: dict[str, Any],
    created_by: str,
    created_by_name: str,
    retry_of_job_id: str | None = None,
    resume_from_step: int | None = None,
    analysis_id: str | None = None,
    comparison_id: str | None = None,
) -> dict[str, Any]:
    """E1. 같은 Case·job_type(또는 같은 분석) 비종료 작업이 있으면 부분 unique 위반(IntegrityError) → 호출자가 409."""
    check_transition(None, QUEUED)
    jt = JOB_TYPES[job_type]
    job_id = str(uuid.uuid4())
    seq = conn.execute(select(job_queue_seq.next_value())).scalar_one()
    conn.execute(insert(jobs).values(
        id=job_id, case_id=case_id, analysis_id=analysis_id, comparison_id=comparison_id, project_id=project_id,
        job_type=job_type,
        stage=jt.stage, lane=jt.lane,
        state=QUEUED, holds_slot=False, queue_seq=seq, queued_at=func.now(), params=params,
        created_by=created_by, created_by_name=created_by_name, retry_of_job_id=retry_of_job_id,
        resume_from_step=resume_from_step,
    ))
    for no, sd in enumerate(jt.steps, start=1):
        state = "SKIPPED" if resume_from_step and no < resume_from_step else "PENDING"
        conn.execute(insert(job_steps).values(
            id=str(uuid.uuid4()), job_id=job_id, step_no=no, step_key=sd.key, kind="INTERNAL",
            core_stage=sd.core_stage, state=state,
        ))
    return get_job(conn, job_id)


# ---------------------------------------------------------------- 알림
_EVENT_TITLE = {
    "JOB_STARTED": "작업 시작", "JOB_SUCCEEDED": "작업 완료", "JOB_FAILED": "작업 실패",
    "JOB_CANCELED": "작업 취소", "JOB_INTERRUPTED": "작업 중단",
}
_END_EVENT = {SUCCEEDED: "JOB_SUCCEEDED", FAILED: "JOB_FAILED", CANCELED: "JOB_CANCELED",
              INTERRUPTED: "JOB_INTERRUPTED"}


def notify(conn: Connection, job: dict[str, Any], event: str) -> None:
    conn.execute(insert(notifications).values(
        user_id=job["created_by"], event=event, job_id=job["id"], case_id=job["case_id"],
        project_id=job["project_id"], title=f"{_EVENT_TITLE[event]}: {job['job_type']}",
        body=(job.get("failure_message") or "")[:500],
    ))


# ---------------------------------------------------------------- claim(E2)
def _case_idle():
    """claim 조건: 같은 Case 에 RUNNING 작업이 없을 것(lane 무관). DB 부분 unique ux_jobs_case_running 이 최종 보장."""
    other = jobs.alias("running_same_case")
    return ~exists(select(literal(1)).select_from(other).where(and_(other.c.case_id == jobs.c.case_id,
                                                                    other.c.state == RUNNING)))


def claim_slot(conn: Connection, worker_id: str, ttl_s: float) -> dict[str, Any] | None:
    """SLOT 레인 claim: worker_slot 단일 행 CAS(lease_generation) + 작업 QUEUED→RUNNING."""
    slot = conn.execute(select(worker_slot).where(worker_slot.c.id == 1).with_for_update()).one()
    if slot.lease_token is not None:
        alive = conn.execute(select(literal(1)).where(literal(slot.lease_expires_at) > func.now())).first()
        if alive:
            return None
        if slot.holder_job_id:
            holder = get_job(conn, slot.holder_job_id, for_update=True)
            if holder and holder["state"] == RUNNING and holder["lease_token"] == slot.lease_token:
                interrupt(conn, holder)
        conn.execute(update(worker_slot).where(worker_slot.c.id == 1).values(holder_job_id=None, **_NO_LEASE))
    target = conn.execute(
        select(jobs.c.id, jobs.c.version, jobs.c.started_at)
        .where(and_(jobs.c.state == QUEUED, jobs.c.lane == "SLOT", jobs.c.cancel_requested_at.is_(None),
                    _case_idle()))
        .order_by(jobs.c.queue_seq).limit(1).with_for_update(skip_locked=True)
    ).first()
    if target is None:
        return None
    check_transition(QUEUED, RUNNING)
    token = secrets.token_urlsafe(32)
    gen = int(slot.lease_generation) + 1
    lv = dict(lease_owner_id=worker_id, lease_token=token, lease_generation=gen, lease_acquired_at=func.now(),
              lease_expires_at=_ttl(ttl_s))
    r1 = conn.execute(
        update(worker_slot)
        .where(and_(worker_slot.c.id == 1, worker_slot.c.lease_generation == slot.lease_generation))
        .values(holder_job_id=target.id, **lv)
    )
    r2 = conn.execute(
        update(jobs).where(and_(jobs.c.id == target.id, jobs.c.state == QUEUED, jobs.c.version == target.version))
        .values(state=RUNNING, holds_slot=True, queue_seq=None, started_at=func.coalesce(jobs.c.started_at,
                func.now()), updated_at=func.now(), version=jobs.c.version + 1, **lv)
    )
    if r1.rowcount != 1 or r2.rowcount != 1:
        raise ClaimRace()
    job = get_job(conn, target.id)
    notify(conn, job, "JOB_STARTED")
    return job


def claim_light(conn: Connection, worker_id: str, ttl_s: float) -> dict[str, Any] | None:
    """LIGHT 레인 claim: 동시 1개(실행 중 LIGHT 가 있으면 None)."""
    conn.execute(select(func.pg_advisory_xact_lock(4242)))
    busy = conn.execute(select(jobs.c.id).where(and_(jobs.c.state == RUNNING, jobs.c.lane == "LIGHT")).limit(1)
                        ).first()
    if busy:
        return None
    target = conn.execute(
        select(jobs.c.id, jobs.c.version, jobs.c.lease_generation)
        .where(and_(jobs.c.state == QUEUED, jobs.c.lane == "LIGHT", jobs.c.cancel_requested_at.is_(None),
                    _case_idle()))
        .order_by(jobs.c.queue_seq).limit(1).with_for_update(skip_locked=True)
    ).first()
    if target is None:
        return None
    check_transition(QUEUED, RUNNING)
    token = secrets.token_urlsafe(32)
    r = conn.execute(
        update(jobs).where(and_(jobs.c.id == target.id, jobs.c.state == QUEUED, jobs.c.version == target.version))
        .values(state=RUNNING, holds_slot=False, queue_seq=None, started_at=func.coalesce(jobs.c.started_at,
                func.now()), updated_at=func.now(), version=jobs.c.version + 1, lease_owner_id=worker_id,
                lease_token=token, lease_generation=int(target.lease_generation) + 1, lease_acquired_at=func.now(),
                lease_expires_at=_ttl(ttl_s))
    )
    if r.rowcount != 1:
        raise ClaimRace()
    job = get_job(conn, target.id)
    notify(conn, job, "JOB_STARTED")
    return job


# ---------------------------------------------------------------- lease
def renew(conn: Connection, job_id: str, token: str, ttl_s: float, *, slot: bool) -> bool:
    r = conn.execute(
        update(jobs).where(and_(jobs.c.id == job_id, jobs.c.lease_token == token, jobs.c.state == RUNNING,
                                jobs.c.lease_expires_at > func.now()))
        .values(lease_expires_at=_ttl(ttl_s))
    )
    if r.rowcount != 1:
        return False
    if slot:
        r2 = conn.execute(
            update(worker_slot).where(and_(worker_slot.c.id == 1, worker_slot.c.lease_token == token,
                                           worker_slot.c.lease_expires_at > func.now()))
            .values(lease_expires_at=_ttl(ttl_s))
        )
        if r2.rowcount != 1:
            return False
    return True


def assert_lease(conn: Connection, job_id: str, token: str) -> dict[str, Any]:
    job = conn.execute(
        select(jobs).where(and_(jobs.c.id == job_id, jobs.c.lease_token == token, jobs.c.state == RUNNING))
        .with_for_update()
    ).first()
    if job is None:
        raise LeaseLost(job_id)
    return row_dict(job)


def step_update(conn: Connection, job_id: str, token: str, step_no: int, **values: Any) -> None:
    """E4: step 진행 갱신(lease 확인)."""
    job = assert_lease(conn, job_id, token)
    check_transition(job["state"], RUNNING)
    conn.execute(update(job_steps).where(and_(job_steps.c.job_id == job_id, job_steps.c.step_no == step_no))
                 .values(**values))
    jv: dict[str, Any] = {"current_step_no": step_no, "updated_at": func.now()}
    conn.execute(update(jobs).where(jobs.c.id == job_id).values(**jv))


def add_warnings(conn: Connection, job_id: str, token: str, items: list[str]) -> None:
    if not items:
        return
    job = assert_lease(conn, job_id, token)
    conn.execute(update(jobs).where(jobs.c.id == job_id).values(warnings=list(job["warnings"] or []) + items))


def patch_result(conn: Connection, job_id: str, token: str, patch: dict[str, Any]) -> None:
    job = assert_lease(conn, job_id, token)
    res = dict(job.get("result") or {})
    res.update(patch)
    conn.execute(update(jobs).where(jobs.c.id == job_id).values(result=res))


def release(conn: Connection, job_id: str, token: str, next_state: str, *, failure_code: str | None = None,
            failure_message: str | None = None) -> dict[str, Any]:
    """E5/E6/E7: lease·슬롯 해제 + 종료 전이. 남은 PENDING step 은 SKIPPED(취소면 CANCELED)."""
    job = assert_lease(conn, job_id, token)
    check_transition(job["state"], next_state)
    values: dict[str, Any] = dict(state=next_state, holds_slot=False, finished_at=func.now(), updated_at=func.now(),
                                  version=jobs.c.version + 1, **_NO_LEASE)
    if next_state in (FAILED, INTERRUPTED, CANCELED):
        values["failure_code"] = failure_code or ("CANCELED" if next_state == CANCELED else "INTERNAL_ERROR")
        values["failure_message"] = (failure_message or "")[:500] or None
    if next_state == SUCCEEDED:
        values["progress_pct"] = 100.0
    conn.execute(update(jobs).where(jobs.c.id == job_id).values(**values))
    pend = "CANCELED" if next_state == CANCELED else "SKIPPED"
    conn.execute(update(job_steps).where(and_(job_steps.c.job_id == job_id, job_steps.c.state == "PENDING"))
                 .values(state=pend))
    if next_state == CANCELED:
        conn.execute(update(job_steps).where(and_(job_steps.c.job_id == job_id, job_steps.c.state == "RUNNING"))
                     .values(state="CANCELED", finished_at=func.now()))
    if job["holds_slot"]:
        conn.execute(update(worker_slot).where(and_(worker_slot.c.id == 1, worker_slot.c.lease_token == token))
                     .values(holder_job_id=None, **_NO_LEASE))
    out = get_job(conn, job_id)
    notify(conn, out, _END_EVENT[next_state])
    return out


# ---------------------------------------------------------------- 리퍼(E8)
def interrupt(conn: Connection, job: dict[str, Any]) -> bool:
    check_transition(job["state"], INTERRUPTED)
    r = conn.execute(
        update(jobs).where(and_(jobs.c.id == job["id"], jobs.c.version == job["version"]))
        .values(state=INTERRUPTED, holds_slot=False, failure_code="WORKER_LOST",
                failure_message="워커 응답이 끊겨(lease 만료) 작업이 중단되었습니다", finished_at=func.now(),
                updated_at=func.now(), version=jobs.c.version + 1, **_NO_LEASE)
    )
    if r.rowcount != 1:
        return False
    conn.execute(update(job_steps).where(and_(job_steps.c.job_id == job["id"], job_steps.c.state == "RUNNING"))
                 .values(state="FAILED", failure_code="WORKER_LOST", failure_message="워커 중단",
                         finished_at=func.now()))
    conn.execute(update(job_steps).where(and_(job_steps.c.job_id == job["id"], job_steps.c.state == "PENDING"))
                 .values(state="SKIPPED"))
    conn.execute(update(worker_slot).where(and_(worker_slot.c.id == 1, worker_slot.c.holder_job_id == job["id"]))
                 .values(holder_job_id=None, **_NO_LEASE))
    notify(conn, get_job(conn, job["id"]), "JOB_INTERRUPTED")
    return True


def reap_expired(conn: Connection) -> list[str]:
    rows = conn.execute(
        select(jobs).where(and_(jobs.c.state == RUNNING, jobs.c.lease_expires_at < func.now()))
        .with_for_update(skip_locked=True)
    ).all()
    out = [r.id for r in rows if interrupt(conn, row_dict(r))]
    conn.execute(update(worker_slot).where(and_(worker_slot.c.id == 1, worker_slot.c.lease_expires_at < func.now()))
                 .values(holder_job_id=None, **_NO_LEASE))
    return out


# ---------------------------------------------------------------- 취소
def is_cancel_requested(conn: Connection, job_id: str) -> bool:
    return conn.execute(select(jobs.c.cancel_requested_at).where(jobs.c.id == job_id)).scalar() is not None


def request_cancel(conn: Connection, job_id: str, user_id: str) -> dict[str, Any]:
    """QUEUED → 즉시 CANCELED(E3). RUNNING → 취소 플래그(워커가 감지해 E7). 종료 상태는 호출자가 409."""
    job = get_job(conn, job_id, for_update=True)
    assert job is not None
    if job["state"] == QUEUED:
        check_transition(QUEUED, CANCELED)
        conn.execute(update(jobs).where(jobs.c.id == job_id).values(
            state=CANCELED, queue_seq=None, failure_code="CANCELED", failure_message="사용자 취소",
            cancel_requested_at=func.now(), cancel_requested_by=user_id, finished_at=func.now(),
            updated_at=func.now(), version=jobs.c.version + 1))
        conn.execute(update(job_steps).where(and_(job_steps.c.job_id == job_id, job_steps.c.state == "PENDING"))
                     .values(state="CANCELED"))
        notify(conn, get_job(conn, job_id), "JOB_CANCELED")
    elif job["state"] == RUNNING and job["cancel_requested_at"] is None:
        conn.execute(update(jobs).where(jobs.c.id == job_id).values(
            cancel_requested_at=func.now(), cancel_requested_by=user_id, updated_at=func.now(),
            version=jobs.c.version + 1))
    return get_job(conn, job_id)


def first_failed_step(conn: Connection, job_id: str) -> int:
    for s in get_steps(conn, job_id):
        if s["state"] not in ("SUCCEEDED", "SKIPPED"):
            return int(s["step_no"])
    return 1
