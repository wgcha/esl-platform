"""P2 플랫폼(계약 esl_p2_library.md §11): 라이브러리·종합분석 테이블, CASE_REPORT·LIB_ANALYZE 작업.

- ``library_entries``·``analysis_runs`` 생성(+ 부분 unique ``ux_library_entries_run_active``).
- ``jobs``: ``case_id`` NULL 허용(LIB_ANALYZE 는 Case 가 없음), ``analysis_id`` 추가(FK analysis_runs),
  ``ck_jobs_job_type``·``ck_jobs_stage`` 확장, ``ck_jobs_subject``(LIB_ANALYZE ⇔ analysis_id, 그 외 ⇔ case_id),
  ``ux_jobs_analysis_active``(분석당 비종료 작업 1개).
- ``validations.field``(validation.json field 요약), ``artifacts`` kind 에 REPORT.

0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있을 수 있다 → checkfirst / IF NOT EXISTS /
제약은 DROP IF EXISTS 후 다시 추가(같은 정의, 멱등).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

from alembic import op
from sqlalchemy import text

from esl_platform.core.db import tables

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


# 0003 시점의 작업 대상 제약(고정). 0004 가 comparison_id 를 넣어 다시 정의한다(tables.CK_JOBS_SUBJECT 는 그 열을
# 참조하므로 0003 에서 쓰면 0002 DB 업그레이드가 실패한다).
CK_JOBS_SUBJECT_0003 = ("(job_type = 'LIB_ANALYZE' AND case_id IS NULL AND analysis_id IS NOT NULL)"
                        " OR (job_type <> 'LIB_ANALYZE' AND case_id IS NOT NULL AND analysis_id IS NULL)")


def _recheck(bind, table: str, name: str, sql: str) -> None:
    bind.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))
    bind.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sql})"))


def upgrade() -> None:
    bind = op.get_bind()
    # 1) 새 테이블(+ 정의된 인덱스). analysis_runs 는 library_entries 를 참조하므로 순서대로.
    for t in (tables.library_entries, tables.analysis_runs):
        t.create(bind, checkfirst=True)
    bind.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_library_entries_run_active ON library_entries "
                      "(esl_run_id) WHERE status = 'ACTIVE'"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_library_entries_project ON library_entries "
                      "(project_id, status)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_analysis_runs_project ON analysis_runs "
                      "(project_id, created_at DESC)"))
    # 2) jobs
    bind.execute(text("ALTER TABLE jobs ALTER COLUMN case_id DROP NOT NULL"))
    bind.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS analysis_id VARCHAR(36)"))
    bind.execute(text(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_jobs_analysis_id_analysis_runs') THEN "
        "ALTER TABLE jobs ADD CONSTRAINT fk_jobs_analysis_id_analysis_runs FOREIGN KEY (analysis_id) "
        "REFERENCES analysis_runs (id); "
        "END IF; END $$"))
    _recheck(bind, "jobs", "ck_jobs_job_type", tables.CK_JOBS_JOB_TYPE)
    _recheck(bind, "jobs", "ck_jobs_stage", tables.CK_JOBS_STAGE)
    _recheck(bind, "jobs", "ck_jobs_subject", CK_JOBS_SUBJECT_0003)
    bind.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_analysis_active ON jobs (analysis_id) WHERE analysis_id IS NOT NULL"
        " AND state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"))
    # 3) validations.field, artifacts kind
    bind.execute(text("ALTER TABLE validations ADD COLUMN IF NOT EXISTS field JSONB"))
    _recheck(bind, "artifacts", "ck_artifacts_kind", tables.CK_ARTIFACTS_KIND)


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
