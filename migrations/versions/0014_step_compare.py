"""강성 평가 스터디 시나리오 ④ 형상 직접 비교(계약 esl_step_compare.md §9, v0.14.0).

- ``bead_does.scenario`` ``String(4)`` → ``String(8)``(ALTER TYPE — 데이터 불변, 'compare' 7자).
- ``ck_bead_does_scenario`` DROP IF EXISTS 후 ``IN ('same','mesh','step','compare')``.
- 그 밖 열·jobs CHECK 변경 없음(④ 입력·준비·결과는 기존 inputs·prep·result JSONB).
- 번호·체인: v0.13.0 ``0013``(run_all) 뒤 — down_revision = "0013"(계약 문서의 0013 표기 = 구현 시점 HEAD 뒤 규칙).
- 멱등(이미 String(8)·같은 CHECK 여도 같은 결과), downgrade 미지원(데이터 보호). 고정 상수(0004·0010·0011 규칙).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-04
"""

from alembic import op
from sqlalchemy import text

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

# 0014 시점 고정 정의(tables.py 와 같은 문자열 — 이후 tables.py 가 바뀌어도 이 revision 은 그대로)
SCENARIO_LEN_0014 = 8
CK_BEAD_DOES_SCENARIO_0014 = "scenario IN ('same','mesh','step','compare')"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(f"ALTER TABLE bead_does ALTER COLUMN scenario TYPE VARCHAR({SCENARIO_LEN_0014})"))
    bind.execute(text("ALTER TABLE bead_does DROP CONSTRAINT IF EXISTS ck_bead_does_scenario"))
    bind.execute(text(f"ALTER TABLE bead_does ADD CONSTRAINT ck_bead_does_scenario CHECK ({CK_BEAD_DOES_SCENARIO_0014})"))


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
