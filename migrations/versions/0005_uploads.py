"""P3-UX 브라우저 분할 업로드 세션(계약 esl_p3_ux.md §1.1): ``uploads`` 테이블.

0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있을 수 있다 → checkfirst / IF NOT EXISTS(멱등).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20
"""

from alembic import op
from sqlalchemy import text

from esl_platform.core.db import tables

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables.uploads.create(bind, checkfirst=True)
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_uploads_user_state ON uploads (user_id, state)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_uploads_state_updated ON uploads (state, updated_at)"))


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
