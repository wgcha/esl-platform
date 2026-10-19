"""작업 Case 단위 직렬화 + Case 폴더명 제약.

- ``ux_jobs_case_running``: 같은 Case 의 RUNNING 작업은 lane 과 무관하게 1개(부분 unique).
- ``ux_cases_folder_lower``: folder_name 대소문자 무시 UNIQUE(Windows 파일시스템).
- ``ck_cases_folder_reserved``: Windows 예약 장치명(CON·PRN·AUX·NUL·COM1-9·LPT1-9, 확장자 포함)·끝 점/공백 금지.

0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있을 수 있다 → IF NOT EXISTS / 존재 확인.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""

from alembic import op
from sqlalchemy import text

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_case_running ON jobs (case_id) WHERE state = 'RUNNING'"))
    bind.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_cases_folder_lower ON cases (lower(folder_name))"))
    bind.execute(text(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_cases_folder_reserved') THEN "
        "ALTER TABLE cases ADD CONSTRAINT ck_cases_folder_reserved CHECK ("
        "lower(split_part(folder_name, '.', 1)) !~ '^(con|prn|aux|nul|com[1-9]|lpt[1-9])$' "
        "AND folder_name !~ '[. ]$'); "
        "END IF; END $$"))


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
