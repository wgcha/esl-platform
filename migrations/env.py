"""Alembic 환경: URL = config.attributes["url"](시험) → env ESL_DATABASE_URL."""

from __future__ import annotations

import os
import sys

from alembic import context
from sqlalchemy import create_engine

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "backend"), os.path.join(ROOT, "worker"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from esl_platform.core.db.engine import normalize_url  # noqa: E402
from esl_platform.core.db.tables import metadata  # noqa: E402

config = context.config
target_metadata = metadata


def _url() -> str:
    url = config.attributes.get("url") or os.environ.get(os.environ.get("ESL_DATABASE_URL_ENV", "ESL_DATABASE_URL"))
    if not url:
        raise RuntimeError("DB URL 이 없습니다: env ESL_DATABASE_URL")
    return normalize_url(url)


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    conn = config.attributes.get("connection")
    if conn is not None:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
