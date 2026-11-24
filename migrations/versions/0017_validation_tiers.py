"""④ 검증 판정 단계화 — 조건부 PASS·MAC(계약 esl_validate_tiers.md §4.2, v0.24.5).

- ``validations`` 컬럼 추가: ``mac``(Float NULL), ``cond_reasons``(JSONB NOT NULL DEFAULT '[]'). 백필 없음(옛 행 mac NULL·[]).
- CHECK 교체: ``ck_validations_verdict`` += CONDITIONAL, ``ck_validations_scheme`` += 'disp_primary/2',
  추가 ``ck_validations_conditional``(verdict ≠ CONDITIONAL ∨ (scheme = 'disp_primary/2') IS TRUE — scheme NULL 이면 CHECK 가 통과하는 SQL 의 NULL 규칙을 막는다).
- ``run_alls``: ``ck_run_alls_verdict`` += CONDITIONAL.
- D-0.24.3-VAL-17 "migration 없음" 원칙의 예외(CHECK 제약이 값을 막음).
- 멱등: 0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있다 → ADD COLUMN IF NOT EXISTS,
  DROP CONSTRAINT IF EXISTS 후 생성.
- downgrade: CONDITIONAL 판정(validations·run_alls) 또는 scheme 'disp_primary/2' 행이 있으면 오류로 중단(데이터 보존 —
  0008 선례), 없으면 CHECK 복원·컬럼 삭제.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-24
"""

from alembic import op
from sqlalchemy import text

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

COLUMNS = (
    ("mac", "DOUBLE PRECISION"),
    ("cond_reasons", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
)
CK_VERDICT_0017 = "verdict IN ('PASS','CONDITIONAL','FAIL','UNDETERMINED')"
CK_SCHEME_0017 = "scheme IS NULL OR scheme IN ('disp_primary/1','disp_primary/2')"
CK_CONDITIONAL_0017 = "verdict <> 'CONDITIONAL' OR (scheme = 'disp_primary/2') IS TRUE"
CK_RUN_ALLS_0017 = "verdict IS NULL OR verdict IN ('PASS','CONDITIONAL','FAIL','UNDETERMINED')"
CK_VERDICT_0008 = "verdict IN ('PASS','FAIL','UNDETERMINED')"
CK_SCHEME_0008 = "scheme IS NULL OR scheme IN ('disp_primary/1')"
CK_RUN_ALLS_0013 = "verdict IS NULL OR verdict IN ('PASS','FAIL','UNDETERMINED')"


def _replace(bind, table: str, name: str, expr: str) -> None:
    bind.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))
    bind.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr})"))


def upgrade() -> None:
    bind = op.get_bind()
    for name, typ in COLUMNS:
        bind.execute(text(f"ALTER TABLE validations ADD COLUMN IF NOT EXISTS {name} {typ}"))
    _replace(bind, "validations", "ck_validations_verdict", CK_VERDICT_0017)
    _replace(bind, "validations", "ck_validations_scheme", CK_SCHEME_0017)
    _replace(bind, "validations", "ck_validations_conditional", CK_CONDITIONAL_0017)
    _replace(bind, "run_alls", "ck_run_alls_verdict", CK_RUN_ALLS_0017)


def downgrade() -> None:
    bind = op.get_bind()
    n_val = bind.execute(text(
        "SELECT count(*) FROM validations WHERE verdict = 'CONDITIONAL' OR scheme = 'disp_primary/2'")).scalar()
    n_run = bind.execute(text("SELECT count(*) FROM run_alls WHERE verdict = 'CONDITIONAL'")).scalar()
    if n_val or n_run:
        raise RuntimeError(f"downgrade 중단: 새 판정 체계(조건부 PASS·disp_primary/2) 검증 {n_val}건·전체 실행 {n_run}건이 "
                           "있습니다(데이터 보존). 먼저 해당 항목을 정리하세요")
    bind.execute(text("ALTER TABLE validations DROP CONSTRAINT IF EXISTS ck_validations_conditional"))
    _replace(bind, "validations", "ck_validations_scheme", CK_SCHEME_0008)
    _replace(bind, "validations", "ck_validations_verdict", CK_VERDICT_0008)
    _replace(bind, "run_alls", "ck_run_alls_verdict", CK_RUN_ALLS_0013)
    for name, _ in reversed(COLUMNS):
        bind.execute(text(f"ALTER TABLE validations DROP COLUMN IF EXISTS {name}"))
