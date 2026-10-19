"""Case·지지점 세트·ESL 실행·검증·산출물 저장소."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from ..db.tables import artifacts, cases, esl_runs, support_sets, validations
from . import row_dict


class VersionConflict(RuntimeError):
    pass


# ---------------------------------------------------------------- cases
def insert_case(conn: Connection, **values: Any) -> dict[str, Any]:
    cid = str(uuid.uuid4())
    conn.execute(insert(cases).values(id=cid, **values))
    return get_case(conn, cid)


def get_case(conn: Connection, case_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(cases).where(cases.c.id == case_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def list_cases(conn: Connection, project_id: str | None, status: str | None) -> list[dict[str, Any]]:
    q = select(cases)
    if project_id:
        q = q.where(cases.c.project_id == project_id)
    if status:
        q = q.where(cases.c.status == status)
    return [row_dict(r) for r in conn.execute(q.order_by(cases.c.created_at.desc())).all()]


def update_case(conn: Connection, case_id: str, version: int | None, **values: Any) -> dict[str, Any]:
    """낙관적 잠금: version 이 주어지면 일치할 때만 갱신(불일치 → VersionConflict)."""
    cond = cases.c.id == case_id
    if version is not None:
        cond = and_(cond, cases.c.version == int(version))
    r = conn.execute(update(cases).where(cond).values(updated_at=func.now(), version=cases.c.version + 1, **values))
    if r.rowcount != 1:
        raise VersionConflict(case_id)
    return get_case(conn, case_id)


# ---------------------------------------------------------------- support_sets
def insert_support_set(conn: Connection, **values: Any) -> dict[str, Any]:
    sid = str(uuid.uuid4())
    conn.execute(insert(support_sets).values(id=sid, **values))
    return get_support_set(conn, sid)


def get_support_set(conn: Connection, sid: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(support_sets).where(support_sets.c.id == sid)).first())


def list_support_sets(conn: Connection, case_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(select(support_sets).where(support_sets.c.case_id == case_id)
                        .order_by(support_sets.c.created_at.desc())).all()
    return [row_dict(r) for r in rows]


# ---------------------------------------------------------------- esl_runs / validations
def insert_esl_run(conn: Connection, **values: Any) -> dict[str, Any]:
    rid = values.pop("id", None) or str(uuid.uuid4())
    conn.execute(insert(esl_runs).values(id=rid, **values))
    return get_esl_run(conn, rid)


def get_esl_run(conn: Connection, rid: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(esl_runs).where(esl_runs.c.id == rid)).first())


def list_esl_runs(conn: Connection, case_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(select(esl_runs).where(esl_runs.c.case_id == case_id)
                        .order_by(esl_runs.c.created_at.desc())).all()
    return [row_dict(r) for r in rows]


def insert_validation(conn: Connection, **values: Any) -> dict[str, Any]:
    vid = str(uuid.uuid4())
    conn.execute(insert(validations).values(id=vid, **values))
    return get_validation(conn, vid)


def get_validation(conn: Connection, vid: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(validations).where(validations.c.id == vid)).first())


def list_validations(conn: Connection, *, case_id: str | None = None, esl_run_id: str | None = None
                     ) -> list[dict[str, Any]]:
    q = select(validations)
    if case_id:
        q = q.where(validations.c.case_id == case_id)
    if esl_run_id:
        q = q.where(validations.c.esl_run_id == esl_run_id)
    return [row_dict(r) for r in conn.execute(q.order_by(validations.c.created_at.desc())).all()]


# ---------------------------------------------------------------- artifacts
def upsert_artifact(conn: Connection, *, case_id: str, job_id: str | None, kind: str, rel: str, size: int,
                    sha256: str | None) -> None:
    stmt = pg_insert(artifacts).values(id=str(uuid.uuid4()), case_id=case_id, job_id=job_id, kind=kind, rel=rel,
                                       size=size, sha256=sha256)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_artifacts_case_rel",
        set_=dict(job_id=stmt.excluded.job_id, kind=stmt.excluded.kind, size=stmt.excluded.size,
                  sha256=stmt.excluded.sha256, created_at=func.now()),
    )
    conn.execute(stmt)


def list_artifacts(conn: Connection, case_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(select(artifacts).where(artifacts.c.case_id == case_id)
                        .order_by(artifacts.c.kind, artifacts.c.rel)).all()
    return [row_dict(r) for r in rows]


def get_artifact(conn: Connection, aid: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(artifacts).where(artifacts.c.id == aid)).first())
