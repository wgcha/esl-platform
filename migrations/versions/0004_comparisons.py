"""P2 §12.2 설계 버전 비교(계약 esl_p2_library.md §12): ``comparisons`` 테이블, LIB_COMPARE 작업.

- ``comparisons`` 생성(+ ``ix_comparisons_project``).
- ``jobs.comparison_id`` 추가(FK comparisons), ``ck_jobs_job_type``(LIB_COMPARE)·``ck_jobs_stage``(1~9)·
  ``ck_jobs_subject``(작업 대상 = Case | 분석 | 비교 중 정확히 하나) 갱신, ``ux_jobs_comparison_active``(비교당 비종료
  작업 1개).

0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있을 수 있다 → checkfirst / IF NOT EXISTS /
제약은 DROP IF EXISTS 후 다시 추가(같은 정의, 멱등).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20
"""

from alembic import op
from sqlalchemy import text

from esl_platform.core.db import tables

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


# 0004 시점의 작업 대상 제약(고정). 0010 이 opt_run_id 를 넣어 다시 정의한다(tables.CK_JOBS_SUBJECT 는 그 열을
# 참조하므로 0004 에서 쓰면 0003 이하 DB 업그레이드가 실패한다).
CK_JOBS_SUBJECT_0004 = ("(job_type = 'LIB_ANALYZE' AND case_id IS NULL AND analysis_id IS NOT NULL"
                        " AND comparison_id IS NULL)"
                        " OR (job_type = 'LIB_COMPARE' AND case_id IS NULL AND analysis_id IS NULL"
                        " AND comparison_id IS NOT NULL)"
                        " OR (job_type NOT IN ('LIB_ANALYZE','LIB_COMPARE') AND case_id IS NOT NULL"
                        " AND analysis_id IS NULL AND comparison_id IS NULL)")


def _recheck(bind, table: str, name: str, sql: str) -> None:
    bind.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))
    bind.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sql})"))


def upgrade() -> None:
    bind = op.get_bind()
    tables.comparisons.create(bind, checkfirst=True)
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_comparisons_project ON comparisons (project_id, created_at DESC)"))
    bind.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS comparison_id VARCHAR(36)"))
    bind.execute(text(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_jobs_comparison_id_comparisons') THEN "
        "ALTER TABLE jobs ADD CONSTRAINT fk_jobs_comparison_id_comparisons FOREIGN KEY (comparison_id) "
        "REFERENCES comparisons (id); "
        "END IF; END $$"))
    _recheck(bind, "jobs", "ck_jobs_job_type", tables.CK_JOBS_JOB_TYPE)
    _recheck(bind, "jobs", "ck_jobs_stage", tables.CK_JOBS_STAGE)
    _recheck(bind, "jobs", "ck_jobs_subject", CK_JOBS_SUBJECT_0004)
    bind.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_comparison_active ON jobs (comparison_id) WHERE comparison_id IS NOT"
        " NULL AND state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"))


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
