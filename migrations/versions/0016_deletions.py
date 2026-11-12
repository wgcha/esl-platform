"""목록 항목 삭제 기록 ``deletions``(계약 esl_item_delete.md §6, v0.19.0).

- 새 테이블 ``deletions``(삭제된 항목 1건 = 1행: kind·item_id·project_id·title·삭제자·summary·dirs[{rel, trash_name}]·
  purge_state(ABSENT|PENDING|PURGED|FAILED)·purge_attempts·purge_error·purged_at) + ``ix_deletions_project``(project_id,
  deleted_at DESC)·``ux_deletions_kind_item``(kind, item_id UNIQUE)·``ix_deletions_purge``(purge_state, deleted_at).
- 기존 테이블 변경 없음. ON DELETE CASCADE 도 추가하지 않는다(삭제는 서비스가 명시적으로 연쇄).
- 번호·체인: down_revision = "0015"(0015_bead_select — 파일 이름이 아니라 revision id).
- 멱등: 0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있다 → checkfirst. downgrade 미지원(데이터 보호).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-12
"""

from alembic import op
from sqlalchemy import text

from esl_platform.core.db import tables

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables.deletions.create(bind, checkfirst=True)
    for stmt in (
        "CREATE INDEX IF NOT EXISTS ix_deletions_project ON deletions (project_id, deleted_at DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_deletions_kind_item ON deletions (kind, item_id)",
        "CREATE INDEX IF NOT EXISTS ix_deletions_purge ON deletions (purge_state, deleted_at)",
    ):
        bind.execute(text(stmt))


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
