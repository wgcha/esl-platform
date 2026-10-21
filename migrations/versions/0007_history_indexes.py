"""P3-이력(계약 esl_p3_history.md §4): 실행 이력 목록용 인덱스만 추가(테이블·컬럼 변경 없음).

- ``ix_jobs_project_created``  jobs(project_id, created_at DESC, id DESC) — 프로젝트 범위 keyset 목록
- ``ix_jobs_project_creator_created`` jobs(project_id, created_by, created_at DESC) — "내 작업만"
- ``ix_jobs_retry_of`` jobs(retry_of_job_id) WHERE retry_of_job_id IS NOT NULL — 재시도 후속 작업
- ``ix_esl_runs_job`` esl_runs(job_id), ``ix_validations_job`` validations(job_id)

0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있을 수 있다 → IF NOT EXISTS / DROP INDEX IF EXISTS(멱등).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21
"""

from alembic import op
from sqlalchemy import text

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_jobs_project_created", "jobs (project_id, created_at DESC, id DESC)"),
    ("ix_jobs_project_creator_created", "jobs (project_id, created_by, created_at DESC)"),
    ("ix_jobs_retry_of", "jobs (retry_of_job_id) WHERE retry_of_job_id IS NOT NULL"),
    ("ix_esl_runs_job", "esl_runs (job_id)"),
    ("ix_validations_job", "validations (job_id)"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, spec in INDEXES:
        bind.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {spec}"))


def downgrade() -> None:
    bind = op.get_bind()
    for name, _ in reversed(INDEXES):
        bind.execute(text(f"DROP INDEX IF EXISTS {name}"))
