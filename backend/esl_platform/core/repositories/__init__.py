"""저장소 계층(SQLAlchemy Core, 호출자가 트랜잭션을 연다)."""

from __future__ import annotations

from typing import Any


def row_dict(r: Any) -> dict[str, Any]:
    return dict(r._mapping) if r is not None else None
