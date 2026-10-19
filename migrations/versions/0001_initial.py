"""초기 스키마(계약 esl.md §3 + esl_platform_p1b.md §3).

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

from alembic import op
from sqlalchemy import text

from esl_platform.core.db import tables

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # 0001 은 tables.metadata 를 그대로 만든다. 이후 스키마 변경은 반드시 새 revision(명시 op)으로 추가한다.
    tables.metadata.create_all(bind)
    bind.execute(text("INSERT INTO worker_slot (id, lease_generation) VALUES (1, 0) ON CONFLICT DO NOTHING"))


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
