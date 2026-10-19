"""워커 heartbeat 저장소."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from ..db.tables import worker_heartbeats
from . import row_dict


def heartbeat(conn: Connection, *, worker_id: str, host: str, pid: int, app_version: str, limiter: str | None,
              info: dict[str, Any] | None) -> None:
    stmt = pg_insert(worker_heartbeats).values(worker_id=worker_id, host=host, pid=pid, app_version=app_version,
                                               limiter=limiter, info=info)
    stmt = stmt.on_conflict_do_update(index_elements=["worker_id"],
                                      set_=dict(last_seen_at=func.now(), limiter=limiter, info=info))
    conn.execute(stmt)


def latest(conn: Connection) -> dict[str, Any] | None:
    row = conn.execute(select(worker_heartbeats, (func.now() - worker_heartbeats.c.last_seen_at).label("age"))
                       .order_by(worker_heartbeats.c.last_seen_at.desc()).limit(1)).first()
    return row_dict(row)
