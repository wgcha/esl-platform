"""강성 평가 스터디 시나리오 select — 비드 직접 선택·규칙 모핑(계약 esl_bead_select.md §15, v0.15.0).

- ``ck_bead_does_scenario`` DROP IF EXISTS 후 ``IN ('same','mesh','step','compare','select')``(열 길이 변경 없음 — 0014 String(8)).
- ``bead_does.selection`` JSONB NULL(ADD COLUMN IF NOT EXISTS) — 사용자 선택 원본(rev·sha256·input·derived 요약, BS-D-4).
- ``ck_bead_does_selection`` = ``scenario = 'select' OR selection IS NULL``(DROP IF EXISTS 후 ADD).
- 기존 행: selection 은 NULL 로 추가되므로 새 CHECK 를 모두 만족(데이터 불변).
- 번호·체인: v0.14.0 ``0014``(step_compare) 뒤 — down_revision = "0014".
- 멱등(이미 열·같은 CHECK 가 있어도 같은 결과), downgrade 미지원(데이터 보호). 시점 고정 상수(0004·0010·0011·0014 규칙).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-04
"""

from alembic import op
from sqlalchemy import text

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# 0015 시점 고정 정의(tables.py 와 같은 문자열 — 이후 tables.py 가 바뀌어도 이 revision 은 그대로)
CK_BEAD_DOES_SCENARIO_0015 = "scenario IN ('same','mesh','step','compare','select')"
CK_BEAD_DOES_SELECTION_0015 = "scenario = 'select' OR selection IS NULL"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE bead_does ADD COLUMN IF NOT EXISTS selection JSONB NULL"))
    bind.execute(text("ALTER TABLE bead_does DROP CONSTRAINT IF EXISTS ck_bead_does_scenario"))
    bind.execute(text(f"ALTER TABLE bead_does ADD CONSTRAINT ck_bead_does_scenario CHECK ({CK_BEAD_DOES_SCENARIO_0015})"))
    bind.execute(text("ALTER TABLE bead_does DROP CONSTRAINT IF EXISTS ck_bead_does_selection"))
    bind.execute(text(f"ALTER TABLE bead_does ADD CONSTRAINT ck_bead_does_selection CHECK ({CK_BEAD_DOES_SELECTION_0015})"))


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
