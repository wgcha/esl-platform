"""DB 엔진(PostgreSQL + psycopg3)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def normalize_url(url: str) -> str:
    """`postgresql://` → `postgresql+psycopg://` (psycopg3 드라이버 고정)."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str, pool_size: int = 5) -> Engine:
    return create_engine(normalize_url(url), pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True,
                         future=True)
