"""대시보드 SCX 릴레이 사용(계약 esl_scx_relay.md §11, v0.11.0).

- 새 테이블 ``verify_drops``(검증 낙하 — 씬마다 1행, batch_id 묶음) + ``ix_verify_drops_doe``·``ix_verify_drops_batch``·
  ``ux_verify_drops_active``(같은 연구·안·Case 비종료 1개), ``scx_submissions``(request_id PK — SCX 제출 기록 영속, SR-D-11).
  v0.11.0 은 표만 만든다(기능 B 구현 v0.12.0).
- ``jobs.upload_id``(FK uploads — SCX_FETCH 대상)·``jobs.verify_drop_id``(FK verify_drops — VERIFY_* 대상) +
  ``ix_jobs_upload``·``ux_jobs_upload_active``·``ix_jobs_verify_drop``·``ux_jobs_verify_drop_active``(대상당 비종료 작업 1개).
- CHECK 교체: ``ck_jobs_job_type``(+SCX_FETCH·VERIFY_DROP·VERIFY_POST), ``ck_jobs_stage``(1~13), ``ck_jobs_lane``(+XFER),
  ``ck_jobs_subject``(SCX_FETCH = upload_id 만, VERIFY_* = verify_drop_id 만, 기존 분기에 두 열 IS NULL),
  ``ck_artifacts_kind``(+VERIFY_RESULT). ``ck_jobs_holds_slot`` 불변(XFER 는 슬롯 없음).
- ``uploads`` 변경 없음(files[] 키 source·drive_rel, result 키 scx 는 JSONB).
- 번호·체인(SR-D-17): ``down_revision = "0011"``(0011 의 CHECK 는 0011 시점 고정 상수로 바꿈). MCP 예약 0009 는 구현 시점 HEAD
  뒤에 붙는다(지금 기준 down "0012").
- 멱등: 0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있다 → checkfirst / IF NOT EXISTS / 제약은 DROP IF EXISTS
  후 같은 정의로 다시 추가. downgrade 미지원(데이터 보호).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-30
"""

from alembic import op
from sqlalchemy import text

from esl_platform.core.db import tables

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_TERMINAL = "('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"


def _recheck(bind, table: str, name: str, sql: str) -> None:
    bind.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))
    bind.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sql})"))


def _fk(name: str, col: str, ref: str) -> str:
    return ("DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN "
            f"ALTER TABLE jobs ADD CONSTRAINT {name} FOREIGN KEY ({col}) REFERENCES {ref} (id); "
            "END IF; END $$")


def upgrade() -> None:
    bind = op.get_bind()
    tables.verify_drops.create(bind, checkfirst=True)
    tables.scx_submissions.create(bind, checkfirst=True)
    for stmt in (
        "CREATE INDEX IF NOT EXISTS ix_verify_drops_doe ON verify_drops (bead_doe_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_verify_drops_batch ON verify_drops (batch_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_verify_drops_active ON verify_drops (bead_doe_id, design_id, case_id)"
        " WHERE phase NOT IN ('DONE','FAILED','CANCELED')",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS upload_id VARCHAR(36)",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS verify_drop_id VARCHAR(36)",
        _fk("fk_jobs_upload_id_uploads", "upload_id", "uploads"),
        _fk("fk_jobs_verify_drop_id_verify_drops", "verify_drop_id", "verify_drops"),
        "CREATE INDEX IF NOT EXISTS ix_jobs_upload ON jobs (upload_id) WHERE upload_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_upload_active ON jobs (upload_id) WHERE upload_id IS NOT NULL"
        f" AND state NOT IN {_TERMINAL}",
        "CREATE INDEX IF NOT EXISTS ix_jobs_verify_drop ON jobs (verify_drop_id) WHERE verify_drop_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_verify_drop_active ON jobs (verify_drop_id) WHERE verify_drop_id IS NOT NULL"
        f" AND state NOT IN {_TERMINAL}",
    ):
        bind.execute(text(stmt))
    _recheck(bind, "jobs", "ck_jobs_job_type", tables.CK_JOBS_JOB_TYPE)
    _recheck(bind, "jobs", "ck_jobs_stage", tables.CK_JOBS_STAGE)
    _recheck(bind, "jobs", "ck_jobs_lane", tables.CK_JOBS_LANE)
    _recheck(bind, "jobs", "ck_jobs_subject", tables.CK_JOBS_SUBJECT)
    _recheck(bind, "artifacts", "ck_artifacts_kind", tables.CK_ARTIFACTS_KIND)


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
