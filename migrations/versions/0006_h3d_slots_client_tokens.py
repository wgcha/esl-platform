"""P3-UX §6·§9.1: 서버 h3d 추출·워커 동시 실행·PC 연결 토큰.

- ``cases.input_kind``(RESULTS | H3D, 기본 RESULTS) + ``ck_cases_input_kind``.
- ``job_steps.kind`` 에 LOCAL(워커가 외부 프로그램 실행 — H3D_EXTRACT) 허용, ``job_steps.command``(실행 직전 argv).
- ``worker_slot``: 단일 행(id=1) 제약 → 행 1..16(``worker.slots`` 만큼 사용), 행 2..16 추가.
- ``client_codes``·``client_tokens``·``client_code_failures``(코드·토큰은 sha256 만 저장).

0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있을 수 있다 → checkfirst / IF NOT EXISTS /
제약은 DROP IF EXISTS 후 다시 추가(멱등).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20
"""

from alembic import op
from sqlalchemy import text

from esl_platform.core.db import tables

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _recheck(bind, table: str, name: str, sql: str) -> None:
    bind.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))
    bind.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sql})"))


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS input_kind VARCHAR NOT NULL DEFAULT 'RESULTS'"))
    _recheck(bind, "cases", "ck_cases_input_kind", tables.CK_CASES_INPUT_KIND)
    bind.execute(text("ALTER TABLE job_steps ADD COLUMN IF NOT EXISTS command JSONB"))
    _recheck(bind, "job_steps", "ck_job_steps_kind", tables.CK_JOB_STEPS_KIND)
    bind.execute(text("ALTER TABLE worker_slot DROP CONSTRAINT IF EXISTS ck_worker_slot_single"))
    _recheck(bind, "worker_slot", "ck_worker_slot_range", tables.CK_WORKER_SLOT_RANGE)
    bind.execute(text(f"INSERT INTO worker_slot (id, lease_generation) SELECT g, 0 FROM generate_series(1, "
                      f"{tables.WORKER_SLOT_ROWS}) AS g ON CONFLICT DO NOTHING"))
    for t in (tables.client_codes, tables.client_tokens, tables.client_code_failures):
        t.create(bind, checkfirst=True)
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_client_codes_hash ON client_codes (code_hash)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_client_tokens_user ON client_tokens (user_id, created_at DESC)"))


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
