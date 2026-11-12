"""목록 항목 삭제 기록 저장소(계약 esl_item_delete.md §6): insert·get_by_item·list_pending·mark_purge. 호출자가 트랜잭션을 연다."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Connection

from ..db.tables import deletions
from . import row_dict

_ERR_MAX = 200


def insert_deletion(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(insert(deletions).values(**values))
    return get_by_item(conn, values["kind"], values["item_id"])


def get_by_item(conn: Connection, kind: str, item_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(deletions).where(and_(deletions.c.kind == kind,
                                                              deletions.c.item_id == item_id))).first())


def get(conn: Connection, did: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(deletions).where(deletions.c.id == did)).first())


def list_pending(conn: Connection, *, max_attempts: int, limit: int) -> list[dict[str, Any]]:
    """영구 삭제 대상: purge_state PENDING·FAILED 이고 purge_attempts < max_attempts, 오래된 삭제부터."""
    rows = conn.execute(
        select(deletions).where(and_(deletions.c.purge_state.in_(("PENDING", "FAILED")),
                                     deletions.c.purge_attempts < int(max_attempts)))
        .order_by(deletions.c.deleted_at, deletions.c.id).limit(int(limit))).all()
    return [row_dict(r) for r in rows]


def mark_purge(conn: Connection, did: str, state: str, *, error: str | None = None) -> None:
    """PURGED(purged_at 기록·오류 지움) 또는 FAILED(purge_attempts + 1, purge_error ≤ 200자)."""
    if state == "PURGED":
        vals: dict[str, Any] = {"purge_state": "PURGED", "purged_at": func.now(), "purge_error": None}
    elif state == "FAILED":
        vals = {"purge_state": "FAILED", "purge_attempts": deletions.c.purge_attempts + 1,
                "purge_error": (error or "")[:_ERR_MAX] or None}
    else:
        raise ValueError(f"mark_purge: 지원하지 않는 상태 {state}")
    conn.execute(update(deletions).where(deletions.c.id == did).values(**vals))


def count_stuck(conn: Connection, *, max_attempts: int) -> int:
    """purge_attempts 가 상한에 닿아 재시도가 멈춘 FAILED 행 수(check.py WARN)."""
    return int(conn.execute(select(func.count()).select_from(deletions).where(and_(
        deletions.c.purge_state == "FAILED", deletions.c.purge_attempts >= int(max_attempts)))).scalar_one())


def count_by_state(conn: Connection) -> dict[str, int]:
    rows = conn.execute(select(deletions.c.purge_state, func.count()).group_by(deletions.c.purge_state)).all()
    return {r[0]: int(r[1]) for r in rows}
