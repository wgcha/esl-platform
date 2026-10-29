"""비드 DOE 저장소(계약 esl_bead_doe.md §13): bead_does + 연구별 작업 조회 + 워커 paicad 점검 기록 읽기.
호출자가 트랜잭션을 연다.

워커(D3) 등록 step 이 쓰는 함수: ``get_study(for_update=True)`` → ``update_study(conn, id, phase=…, prep=…|doe=…|
result=…, report_rel=…, paicad_version=…)``(version 을 1 올림). 응답 형식은 api/services/doe.py 머리말.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, desc, func, insert, select, update
from sqlalchemy.engine import Connection

from ..db.tables import bead_does, jobs, worker_heartbeats
from . import row_dict
from .cases import VersionConflict

TERMINAL = ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")


def insert_study(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(insert(bead_does).values(**values))
    return get_study(conn, values["id"])


def get_study(conn: Connection, sid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(bead_does).where(bead_does.c.id == sid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def list_studies(conn: Connection, *, project_id: str | None = None, project_ids: list[str] | None = None,
                 limit: int = 200) -> list[dict[str, Any]]:
    q = select(bead_does)
    conds = []
    if project_id:
        conds.append(bead_does.c.project_id == project_id)
    if project_ids is not None:
        conds.append(bead_does.c.project_id.in_(list(project_ids)))
    if conds:
        q = q.where(and_(*conds))
    rows = conn.execute(q.order_by(bead_does.c.created_at.desc(), bead_does.c.id).limit(limit)).all()
    return [row_dict(r) for r in rows]


def update_study(conn: Connection, sid: str, *, expect_version: int | None = None, **values: Any) -> dict[str, Any]:
    """갱신 + version 1 증가. expect_version 이 있으면 낙관적 잠금(다르면 VersionConflict)."""
    cond = bead_does.c.id == sid
    if expect_version is not None:
        cond = and_(cond, bead_does.c.version == int(expect_version))
    r = conn.execute(update(bead_does).where(cond).values(updated_at=func.now(), version=bead_does.c.version + 1,
                                                         **values))
    if r.rowcount != 1:
        raise VersionConflict(sid)
    return get_study(conn, sid)


def studies_by_ids(conn: Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    cols = (bead_does.c.id, bead_does.c.title, bead_does.c.scenario, bead_does.c.phase, bead_does.c.dir_rel,
            bead_does.c.report_rel)
    return {r.id: row_dict(r) for r in conn.execute(select(*cols).where(bead_does.c.id.in_(ids))).all()}


# ---------------------------------------------------------------- 연구별 작업
def latest_job(conn: Connection, sid: str, *, job_type: str | None = None, state: str | None = None
               ) -> dict[str, Any] | None:
    conds = [jobs.c.bead_doe_id == sid]
    if job_type:
        conds.append(jobs.c.job_type == job_type)
    if state:
        conds.append(jobs.c.state == state)
    q = select(jobs).where(and_(*conds)).order_by(desc(jobs.c.created_at), desc(jobs.c.queued_at)).limit(1)
    return row_dict(conn.execute(q).first())


def active_job(conn: Connection, sid: str) -> dict[str, Any] | None:
    q = select(jobs).where(and_(jobs.c.bead_doe_id == sid, jobs.c.state.notin_(TERMINAL))).limit(1)
    return row_dict(conn.execute(q).first())


def latest_jobs(conn: Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    """연구 id → 가장 최근 작업(목록 화면, 쿼리 1개)."""
    if not ids:
        return {}
    rn = func.row_number().over(partition_by=jobs.c.bead_doe_id, order_by=(desc(jobs.c.created_at),
                                                                           desc(jobs.c.queued_at))).label("rn")
    sub = select(jobs, rn).where(jobs.c.bead_doe_id.in_(ids)).subquery()
    rows = conn.execute(select(sub).where(sub.c.rn == 1)).all()
    out = {}
    for r in rows:
        d = row_dict(r)
        d.pop("rn", None)
        out[d["bead_doe_id"]] = d
    return out


# ---------------------------------------------------------------- 워커 paicad·gmsh 점검 기록(§6.5)
def paicad_record(conn: Connection) -> dict[str, Any] | None:
    """가장 최근 heartbeat 중 info.paicad 가 있는 워커의 기록 {paicad: {...}, gmsh: {...}|None, age_s}.

    형식(워커 D3 가 heartbeat info 에 기록): ``info.paicad = {ready, version, ocp, pinned, warning, reason, checked_at}``
    (= ``esl.doe.paicad_io.check_version`` 결과 + 점검 시각), ``info.gmsh = {ready, version}``. 백엔드는 paicad 를 실행하지
    않고 이 값만 읽는다."""
    q = (select(worker_heartbeats.c.info, (func.now() - worker_heartbeats.c.last_seen_at).label("age"))
         .where(worker_heartbeats.c.info["paicad"].isnot(None))
         .order_by(worker_heartbeats.c.last_seen_at.desc()).limit(1))
    r = conn.execute(q).first()
    if r is None or not isinstance(r.info, dict) or not isinstance(r.info.get("paicad"), dict):
        return None
    g = r.info.get("gmsh")
    return {"paicad": r.info["paicad"], "gmsh": g if isinstance(g, dict) else None,
            "age_s": r.age.total_seconds() if r.age is not None else None}
