"""비드 형상 DOE(계약 esl_bead_doe.md §13, v0.9.0).

- 새 테이블 ``bead_does``(비드 DOE 연구) + ``ix_bead_does_project``.
- ``jobs.bead_doe_id``(FK bead_does) + ``ix_jobs_bead_doe``·``ux_jobs_bead_doe_active``(연구당 비종료 작업 1개).
  CHECK 교체: ``ck_jobs_job_type``(+DOE_PREP·DOE_PREVIEW·DOE_RUN), ``ck_jobs_stage``(1~11), ``ck_jobs_subject``(DOE 3종
  분기 = bead_doe_id NOT NULL·나머지 NULL, 기존 분기에 ``bead_doe_id IS NULL``). ``ck_artifacts_kind``(+DOE_RESULT).
- ``uploads`` 변경 없음(purpose ``doe_step``·``doe_mesh`` 는 기존 result JSONB).
- 번호·체인(BD-D-21): ``down_revision = "0010"``. MCP 예약 0009 는 구현 시점 HEAD 뒤에 붙는다(지금 기준 down "0011").
- 멱등: 0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있다 → checkfirst / IF NOT EXISTS / 제약은
  DROP IF EXISTS 후 같은 정의로 다시 추가. downgrade 미지원(데이터 보호).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-29
"""

from alembic import op
from sqlalchemy import text

from esl_platform.core.db import tables

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _recheck(bind, table: str, name: str, sql: str) -> None:
    bind.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))
    bind.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sql})"))


def upgrade() -> None:
    bind = op.get_bind()
    tables.bead_does.create(bind, checkfirst=True)
    for stmt in (
        "CREATE INDEX IF NOT EXISTS ix_bead_does_project ON bead_does (project_id, created_at DESC)",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS bead_doe_id VARCHAR(36)",
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_jobs_bead_doe_id_bead_does') THEN "
        "ALTER TABLE jobs ADD CONSTRAINT fk_jobs_bead_doe_id_bead_does FOREIGN KEY (bead_doe_id) REFERENCES bead_does (id); "
        "END IF; END $$",
        "CREATE INDEX IF NOT EXISTS ix_jobs_bead_doe ON jobs (bead_doe_id) WHERE bead_doe_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_bead_doe_active ON jobs (bead_doe_id) WHERE bead_doe_id IS NOT NULL"
        " AND state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')",
    ):
        bind.execute(text(stmt))
    _recheck(bind, "jobs", "ck_jobs_job_type", tables.CK_JOBS_JOB_TYPE)
    _recheck(bind, "jobs", "ck_jobs_stage", tables.CK_JOBS_STAGE)
    _recheck(bind, "jobs", "ck_jobs_subject", tables.CK_JOBS_SUBJECT)
    _recheck(bind, "artifacts", "ck_artifacts_kind", tables.CK_ARTIFACTS_KIND)


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
