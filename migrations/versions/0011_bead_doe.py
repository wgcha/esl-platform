"""비드 형상 DOE(계약 esl_bead_doe.md §13, v0.9.0).

- 새 테이블 ``bead_does``(비드 DOE 연구) + ``ix_bead_does_project``.
- ``jobs.bead_doe_id``(FK bead_does) + ``ix_jobs_bead_doe``·``ux_jobs_bead_doe_active``(연구당 비종료 작업 1개).
  CHECK 교체: ``ck_jobs_job_type``(+DOE_PREP·DOE_PREVIEW·DOE_RUN), ``ck_jobs_stage``(1~11), ``ck_jobs_subject``(DOE 3종
  분기 = bead_doe_id NOT NULL·나머지 NULL, 기존 분기에 ``bead_doe_id IS NULL``). ``ck_artifacts_kind``(+DOE_RESULT).
- ``uploads`` 변경 없음(purpose ``doe_step``·``doe_mesh`` 는 기존 result JSONB).
- 번호·체인(BD-D-21): ``down_revision = "0010"``. MCP 예약 0009 는 구현 시점 HEAD 뒤에 붙는다(v0.11.0 기준 down "0012").
- v0.11.0(esl_scx_relay.md SR-D-17): CHECK 정의는 0011 시점 값으로 고정(아래 *_0011) — 0012 가 upload_id·verify_drop_id·
  SCX_FETCH·VERIFY_*·lane XFER 를 넣어 다시 정의한다(tables.CK_* 는 0012 열을 참조하므로 0011 단계에서 쓰면 안 됨).
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


# 0011 시점의 작업·산출물 제약(고정 — BD-D-21 의 0010 수정과 같은 규칙)
_JOB_TYPES_0011 = ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE", "EXPORT", "CASE_REPORT", "LIB_ANALYZE", "LIB_COMPARE", "OPT_RUN",
                   "DOE_PREP", "DOE_PREVIEW", "DOE_RUN")
_KINDS_0011 = ("CASE", "EXTRACT", "TSTAR", "SUPPORT", "ESL", "VALIDATION", "EXPORT", "REPORT", "RUN", "LOG", "OPT_RESULT",
               "OPT_SOLVE", "DOE_RESULT")
_DOE_IN = "('DOE_PREP','DOE_PREVIEW','DOE_RUN')"
CK_JOBS_JOB_TYPE_0011 = "job_type IN (" + ",".join(f"'{t}'" for t in _JOB_TYPES_0011) + ")"
CK_JOBS_STAGE_0011 = "stage BETWEEN 1 AND 11"
CK_JOBS_SUBJECT_0011 = ("(job_type = 'LIB_ANALYZE' AND case_id IS NULL AND analysis_id IS NOT NULL"
                        " AND comparison_id IS NULL AND opt_run_id IS NULL AND bead_doe_id IS NULL)"
                        " OR (job_type = 'LIB_COMPARE' AND case_id IS NULL AND analysis_id IS NULL"
                        " AND comparison_id IS NOT NULL AND opt_run_id IS NULL AND bead_doe_id IS NULL)"
                        " OR (job_type = 'OPT_RUN' AND case_id IS NULL AND analysis_id IS NULL"
                        " AND comparison_id IS NULL AND opt_run_id IS NOT NULL AND bead_doe_id IS NULL)"
                        f" OR (job_type IN {_DOE_IN} AND case_id IS NULL AND analysis_id IS NULL"
                        " AND comparison_id IS NULL AND opt_run_id IS NULL AND bead_doe_id IS NOT NULL)"
                        f" OR (job_type NOT IN ('LIB_ANALYZE','LIB_COMPARE','OPT_RUN','DOE_PREP','DOE_PREVIEW','DOE_RUN')"
                        " AND case_id IS NOT NULL AND analysis_id IS NULL AND comparison_id IS NULL AND opt_run_id IS NULL"
                        " AND bead_doe_id IS NULL)")
CK_ARTIFACTS_KIND_0011 = "kind IN (" + ",".join(f"'{k}'" for k in _KINDS_0011) + ")"


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
    _recheck(bind, "jobs", "ck_jobs_job_type", CK_JOBS_JOB_TYPE_0011)
    _recheck(bind, "jobs", "ck_jobs_stage", CK_JOBS_STAGE_0011)
    _recheck(bind, "jobs", "ck_jobs_subject", CK_JOBS_SUBJECT_0011)
    _recheck(bind, "artifacts", "ck_artifacts_kind", CK_ARTIFACTS_KIND_0011)


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
