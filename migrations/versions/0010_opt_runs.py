"""비드 최적화 서버 실행(계약 esl_opt_run.md §12, v0.7.0).

- 새 테이블 ``opt_templates``(전역 S2 템플릿), ``opt_keepouts``(금지 영역 세트 — 템플릿 또는 topo_sha256 키),
  ``opt_runs``(최적화 실행) + 인덱스.
- ``library_entries``: ``topo_sha256``(char 64, NULL — 지연 백필) + ``ix_library_entries_topo``, ``deform_mode`` JSONB NULL.
- ``jobs.opt_run_id``(FK opt_runs) + ``ix_jobs_opt_run``·``ux_jobs_opt_run_active``(실행당 비종료 작업 1개).
  CHECK 교체: ``ck_jobs_job_type``(+OPT_RUN), ``ck_jobs_stage``(1~10), ``ck_jobs_subject``(OPT_RUN 분기, 기존 분기에
  ``opt_run_id IS NULL``). ``ck_artifacts_kind``(+OPT_RESULT·OPT_SOLVE).
- 번호·체인(OR-D-22): 0009 는 MCP 예약. 0009 가 아직 없으므로 ``down_revision = "0008"``. v0.9.0(BD-D-21): 이 뒤에
  0011(비드 DOE)이 붙고, MCP 0009 는 구현 시점 HEAD 뒤(지금 기준 down_revision "0011")에 붙는다.
- CHECK 정의는 0010 시점 값으로 고정(아래 *_0010) — 0011 이 bead_doe_id 를 넣어 다시 정의한다.
- 멱등: 0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있다 → checkfirst / IF NOT EXISTS / 제약은
  DROP IF EXISTS 후 같은 정의로 다시 추가. downgrade 미지원(데이터 보호).

Revision ID: 0010
Revises: 0008
Create Date: 2026-10-29
"""

from alembic import op
from sqlalchemy import text

from esl_platform.core.db import tables

revision = "0010"
down_revision = "0008"
branch_labels = None
depends_on = None


# 0010 시점의 작업 제약(고정). 0011 이 bead_doe_id·DOE_* 를 넣어 다시 정의한다(tables.CK_JOBS_* 는 그 열을 참조하므로
# 0008 DB 를 올릴 때 0010 단계에서 쓰면 안 됨 — 0004 와 같은 규칙).
_JOB_TYPES_0010 = ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE", "EXPORT", "CASE_REPORT", "LIB_ANALYZE", "LIB_COMPARE", "OPT_RUN")
_KINDS_0010 = ("CASE", "EXTRACT", "TSTAR", "SUPPORT", "ESL", "VALIDATION", "EXPORT", "REPORT", "RUN", "LOG", "OPT_RESULT",
               "OPT_SOLVE")
CK_JOBS_JOB_TYPE_0010 = "job_type IN (" + ",".join(f"'{t}'" for t in _JOB_TYPES_0010) + ")"
CK_JOBS_STAGE_0010 = "stage BETWEEN 1 AND 10"
CK_JOBS_SUBJECT_0010 = ("(job_type = 'LIB_ANALYZE' AND case_id IS NULL AND analysis_id IS NOT NULL"
                        " AND comparison_id IS NULL AND opt_run_id IS NULL)"
                        " OR (job_type = 'LIB_COMPARE' AND case_id IS NULL AND analysis_id IS NULL"
                        " AND comparison_id IS NOT NULL AND opt_run_id IS NULL)"
                        " OR (job_type = 'OPT_RUN' AND case_id IS NULL AND analysis_id IS NULL"
                        " AND comparison_id IS NULL AND opt_run_id IS NOT NULL)"
                        " OR (job_type NOT IN ('LIB_ANALYZE','LIB_COMPARE','OPT_RUN') AND case_id IS NOT NULL"
                        " AND analysis_id IS NULL AND comparison_id IS NULL AND opt_run_id IS NULL)")
CK_ARTIFACTS_KIND_0010 = "kind IN (" + ",".join(f"'{k}'" for k in _KINDS_0010) + ")"


def _recheck(bind, table: str, name: str, sql: str) -> None:
    bind.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))
    bind.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sql})"))


def upgrade() -> None:
    bind = op.get_bind()
    for t in (tables.opt_templates, tables.opt_keepouts, tables.opt_runs):
        t.create(bind, checkfirst=True)
    for stmt in (
        "CREATE INDEX IF NOT EXISTS ix_opt_templates_status ON opt_templates (status, created_at DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_opt_keepouts_template ON opt_keepouts (template_id)"
        " WHERE template_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_opt_keepouts_topo ON opt_keepouts (topo_sha256)"
        " WHERE topo_sha256 IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_opt_runs_project ON opt_runs (project_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_opt_runs_template ON opt_runs (template_id)",
        "ALTER TABLE library_entries ADD COLUMN IF NOT EXISTS topo_sha256 VARCHAR(64)",
        "ALTER TABLE library_entries ADD COLUMN IF NOT EXISTS deform_mode JSONB",
        "CREATE INDEX IF NOT EXISTS ix_library_entries_topo ON library_entries (topo_sha256)",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS opt_run_id VARCHAR(36)",
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_jobs_opt_run_id_opt_runs') THEN "
        "ALTER TABLE jobs ADD CONSTRAINT fk_jobs_opt_run_id_opt_runs FOREIGN KEY (opt_run_id) REFERENCES opt_runs (id); "
        "END IF; END $$",
        "CREATE INDEX IF NOT EXISTS ix_jobs_opt_run ON jobs (opt_run_id) WHERE opt_run_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_opt_run_active ON jobs (opt_run_id) WHERE opt_run_id IS NOT NULL"
        " AND state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')",
    ):
        bind.execute(text(stmt))
    _recheck(bind, "jobs", "ck_jobs_job_type", CK_JOBS_JOB_TYPE_0010)
    _recheck(bind, "jobs", "ck_jobs_stage", CK_JOBS_STAGE_0010)
    _recheck(bind, "jobs", "ck_jobs_subject", CK_JOBS_SUBJECT_0010)
    _recheck(bind, "artifacts", "ck_artifacts_kind", CK_ARTIFACTS_KIND_0010)


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
