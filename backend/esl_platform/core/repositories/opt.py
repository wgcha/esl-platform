"""비드 최적화 저장소(계약 esl_opt_run.md §12): opt_runs · opt_templates · opt_keepouts. 호출자가 트랜잭션을 연다."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.engine import Connection

from ..db.tables import opt_keepouts, opt_runs, opt_templates
from . import row_dict
from .cases import VersionConflict


def _like(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ---------------------------------------------------------------- opt_templates
def insert_template(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(insert(opt_templates).values(**values))
    return get_template(conn, values["id"])


def get_template(conn: Connection, tid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(opt_templates).where(opt_templates.c.id == tid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def list_templates(conn: Connection, *, status: str | None = None, q: str | None = None,
                   limit: int = 500) -> list[dict[str, Any]]:
    stmt = select(opt_templates)
    conds = []
    if status:
        conds.append(opt_templates.c.status == status)
    if q:
        pat = _like(q)
        conds.append(or_(opt_templates.c.title.ilike(pat, escape="\\"),
                         opt_templates.c.description.ilike(pat, escape="\\"),
                         opt_templates.c.file_name.ilike(pat, escape="\\")))
    if conds:
        stmt = stmt.where(and_(*conds))
    rows = conn.execute(stmt.order_by(opt_templates.c.created_at.desc(), opt_templates.c.id).limit(limit)).all()
    return [row_dict(r) for r in rows]


def update_template(conn: Connection, tid: str, **values: Any) -> dict[str, Any]:
    conn.execute(update(opt_templates).where(opt_templates.c.id == tid).values(updated_at=func.now(), **values))
    return get_template(conn, tid)


def delete_template(conn: Connection, tid: str) -> None:
    conn.execute(delete(opt_templates).where(opt_templates.c.id == tid))   # opt_keepouts 는 ON DELETE CASCADE


def template_run_counts(conn: Connection, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = conn.execute(select(opt_runs.c.template_id, func.count()).where(opt_runs.c.template_id.in_(ids))
                        .group_by(opt_runs.c.template_id)).all()
    return {r[0]: int(r[1]) for r in rows}


# ---------------------------------------------------------------- opt_keepouts
def get_keepout(conn: Connection, *, template_id: str | None = None, topo_sha256: str | None = None,
                for_update: bool = False) -> dict[str, Any] | None:
    if (template_id is None) == (topo_sha256 is None):
        raise ValueError("template_id 와 topo_sha256 중 정확히 하나")
    cond = opt_keepouts.c.template_id == template_id if template_id is not None else \
        opt_keepouts.c.topo_sha256 == topo_sha256
    q = select(opt_keepouts).where(cond)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def insert_keepout(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(insert(opt_keepouts).values(**values))
    return row_dict(conn.execute(select(opt_keepouts).where(opt_keepouts.c.id == values["id"])).first())


def update_keepout(conn: Connection, kid: str, version: int, **values: Any) -> dict[str, Any]:
    r = conn.execute(update(opt_keepouts).where(and_(opt_keepouts.c.id == kid, opt_keepouts.c.version == int(version)))
                     .values(updated_at=func.now(), version=opt_keepouts.c.version + 1, **values))
    if r.rowcount != 1:
        raise VersionConflict(kid)
    return row_dict(conn.execute(select(opt_keepouts).where(opt_keepouts.c.id == kid)).first())


# ---------------------------------------------------------------- opt_runs
def insert_run(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(insert(opt_runs).values(**values))
    return get_run(conn, values["id"])


def get_run(conn: Connection, rid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(opt_runs).where(opt_runs.c.id == rid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def list_runs(conn: Connection, *, project_id: str | None = None, scenario: str | None = None,
              project_ids: list[str] | None = None, limit: int = 200) -> list[dict[str, Any]]:
    q = select(opt_runs)
    conds = []
    if project_id:
        conds.append(opt_runs.c.project_id == project_id)
    if project_ids is not None:
        conds.append(opt_runs.c.project_id.in_(list(project_ids)))
    if scenario:
        conds.append(opt_runs.c.scenario == scenario)
    if conds:
        q = q.where(and_(*conds))
    return [row_dict(r) for r in conn.execute(q.order_by(opt_runs.c.created_at.desc(), opt_runs.c.id).limit(limit)).all()]


def update_run(conn: Connection, rid: str, **values: Any) -> dict[str, Any]:
    conn.execute(update(opt_runs).where(opt_runs.c.id == rid).values(updated_at=func.now(), **values))
    return get_run(conn, rid)


def runs_by_ids(conn: Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    cols = (opt_runs.c.id, opt_runs.c.title, opt_runs.c.job_id, opt_runs.c.scenario, opt_runs.c.dir_rel,
            opt_runs.c.report_rel)
    return {r.id: row_dict(r) for r in conn.execute(select(*cols).where(opt_runs.c.id.in_(ids))).all()}
