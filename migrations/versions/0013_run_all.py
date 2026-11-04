"""ESL 생성 Case 일괄 실행(계약 esl_run_all.md §2, v0.13.0).

- 새 테이블 ``run_alls``(체인 시도 1회 = 1행) + ``ux_run_alls_case_running``(Case 당 RUNNING 1개)·``ix_run_alls_case_created``.
- ``jobs.run_all_id``(FK run_alls — 체인이 만든 작업만) + ``ix_jobs_run_all``. ``run_alls.cur_job_id`` → jobs 와 순환 FK 라
  tables.py 는 use_alter, 여기서는 표를 만든 뒤 ALTER 로 FK 를 붙인다.
- 기존 CHECK 변경 없음(새 작업 종류 없음).
- 멱등: 0001 이 tables.metadata 를 create_all 하므로 새 DB 에는 이미 있다 → IF NOT EXISTS / 제약은 없을 때만 추가.
  downgrade 미지원(데이터 보호). MCP 예약 0009 는 구현 시점 HEAD 뒤(지금 기준 down "0013").

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04
"""

from alembic import op
from sqlalchemy import text

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

# 0013 시점 고정 정의(tables.py 와 같은 문자열 — 이후 tables.py 가 바뀌어도 이 revision 은 그대로)
_STEPS_IN = "('input','tstar','esl','validate')"
CK_RUN_ALLS = {
    "ck_run_alls_status": "status IN ('RUNNING','STOPPED','DONE','CANCELED')",
    "ck_run_alls_from_step": f"from_step IN {_STEPS_IN}",
    "ck_run_alls_steps": f"(cur_step IS NULL OR cur_step IN {_STEPS_IN}) AND (stop_step IS NULL OR stop_step IN {_STEPS_IN})",
    "ck_run_alls_verdict": "verdict IS NULL OR verdict IN ('PASS','FAIL','UNDETERMINED')",
    "ck_run_alls_finished": "(status = 'RUNNING') = (finished_at IS NULL)",
}


def _add_constraint(name: str, table: str, ddl: str) -> str:
    return ("DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN "
            f"ALTER TABLE {table} ADD CONSTRAINT {name} {ddl}; "
            "END IF; END $$")


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS run_alls (
            id VARCHAR(36) NOT NULL,
            case_id VARCHAR(36) NOT NULL,
            project_id VARCHAR NOT NULL,
            from_step VARCHAR(16) NOT NULL,
            status VARCHAR(16) DEFAULT 'RUNNING' NOT NULL,
            cur_step VARCHAR(16),
            cur_job_id VARCHAR(36),
            stop_step VARCHAR(16),
            stop_code VARCHAR(64),
            stop_reason JSONB,
            verdict VARCHAR(16),
            job_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
            skipped JSONB DEFAULT '[]'::jsonb NOT NULL,
            prev_user_tstar JSONB,
            core_settings JSONB NOT NULL,
            resumed_from_id VARCHAR(36),
            created_by VARCHAR NOT NULL,
            created_by_name VARCHAR NOT NULL,
            canceled_by VARCHAR,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            finished_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT pk_run_alls PRIMARY KEY (id),
            CONSTRAINT fk_run_alls_case_id_cases FOREIGN KEY (case_id) REFERENCES cases (id),
            CONSTRAINT fk_run_alls_resumed_from_id_run_alls FOREIGN KEY (resumed_from_id) REFERENCES run_alls (id)
        )"""))
    for name, sql in CK_RUN_ALLS.items():
        bind.execute(text(_add_constraint(name, "run_alls", f"CHECK ({sql})")))
    for stmt in (
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS run_all_id VARCHAR(36)",
        _add_constraint("fk_jobs_run_all_id_run_alls", "jobs", "FOREIGN KEY (run_all_id) REFERENCES run_alls (id)"),
        _add_constraint("fk_run_alls_cur_job_id_jobs", "run_alls", "FOREIGN KEY (cur_job_id) REFERENCES jobs (id)"),
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_run_alls_case_running ON run_alls (case_id) WHERE status = 'RUNNING'",
        "CREATE INDEX IF NOT EXISTS ix_run_alls_case_created ON run_alls (case_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_jobs_run_all ON jobs (run_all_id) WHERE run_all_id IS NOT NULL",
    ):
        bind.execute(text(stmt))


def downgrade() -> None:
    raise RuntimeError("downgrade 는 지원하지 않습니다(데이터 보호)")
