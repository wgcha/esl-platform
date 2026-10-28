"""⑤ 검증 변위 주지표 판정(계약 esl_disp_primary.md §6, v0.5.7).

- ``validations`` 컬럼 추가(전부 NULL 허용): ``scheme``(새 행 'disp_primary/1', 기존 행 NULL = LEGACY, 백필 없음),
  ``disp_max_rel``, ``disp_noise_rel``, ``undetermined_reason``, ``disp``(JSONB), ``strain_ref``(JSONB).
- CHECK 교체: ``ck_validations_verdict`` → PASS|FAIL|UNDETERMINED; 추가 ``ck_validations_scheme``,
  ``ck_validations_undetermined``(UNDETERMINED 는 scheme·undetermined_reason 필수).
- 멱등: 0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있다 → ADD COLUMN IF NOT EXISTS,
  DROP CONSTRAINT IF EXISTS 후 생성.
- downgrade: UNDETERMINED 행이 있으면 오류로 중단(데이터 보존), 없으면 CHECK 복원·컬럼 삭제.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28
"""

from alembic import op
from sqlalchemy import text

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

COLUMNS = (
    ("scheme", "VARCHAR"),
    ("disp_max_rel", "DOUBLE PRECISION"),
    ("disp_noise_rel", "DOUBLE PRECISION"),
    ("undetermined_reason", "VARCHAR"),
    ("disp", "JSONB"),
    ("strain_ref", "JSONB"),
)
CHECKS = (
    ("ck_validations_verdict", "verdict IN ('PASS','FAIL','UNDETERMINED')"),
    ("ck_validations_scheme", "scheme IS NULL OR scheme IN ('disp_primary/1')"),
    ("ck_validations_undetermined",
     "verdict <> 'UNDETERMINED' OR (scheme IS NOT NULL AND undetermined_reason IS NOT NULL)"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, typ in COLUMNS:
        bind.execute(text(f"ALTER TABLE validations ADD COLUMN IF NOT EXISTS {name} {typ}"))
    for name, expr in CHECKS:
        bind.execute(text(f"ALTER TABLE validations DROP CONSTRAINT IF EXISTS {name}"))
        bind.execute(text(f"ALTER TABLE validations ADD CONSTRAINT {name} CHECK ({expr})"))


def downgrade() -> None:
    bind = op.get_bind()
    n = bind.execute(text("SELECT count(*) FROM validations WHERE verdict = 'UNDETERMINED'")).scalar()
    if n:
        raise RuntimeError(f"downgrade 중단: verdict=UNDETERMINED 검증 {n}건이 있습니다(데이터 보존). "
                           "먼저 해당 검증을 정리하세요")
    for name, _ in reversed(CHECKS):
        bind.execute(text(f"ALTER TABLE validations DROP CONSTRAINT IF EXISTS {name}"))
    bind.execute(text("ALTER TABLE validations ADD CONSTRAINT ck_validations_verdict CHECK (verdict IN ('PASS','FAIL'))"))
    for name, _ in reversed(COLUMNS):
        bind.execute(text(f"ALTER TABLE validations DROP COLUMN IF EXISTS {name}"))
