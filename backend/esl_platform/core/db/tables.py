"""DB 스키마(계약 esl.md §3 + esl_platform_p1b.md §3 + esl_p2_library.md §11). SQLAlchemy Core, PostgreSQL 전용.

공통: ID = UUID4 VARCHAR(36), 시간 TIMESTAMPTZ(DB 시계), 파일 본문·대용량 배열 저장 금지(경로·sha256·요약만),
갱신 행은 `version BIGINT` 낙관적 잠금.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Sequence,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)
ID = String(36)
TS = TIMESTAMP(timezone=True)

TERMINAL_STATES = ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")
JOB_TYPES = ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE", "EXPORT", "CASE_REPORT", "LIB_ANALYZE")
ARTIFACT_KINDS = ("CASE", "EXTRACT", "TSTAR", "SUPPORT", "ESL", "VALIDATION", "EXPORT", "REPORT", "RUN", "LOG")
# 0003: 제약 SQL(마이그레이션과 공유)
CK_JOBS_JOB_TYPE = "job_type IN (" + ",".join(f"'{t}'" for t in JOB_TYPES) + ")"
CK_JOBS_STAGE = "stage BETWEEN 1 AND 8"
CK_JOBS_SUBJECT = ("(job_type = 'LIB_ANALYZE' AND case_id IS NULL AND analysis_id IS NOT NULL)"
                   " OR (job_type <> 'LIB_ANALYZE' AND case_id IS NOT NULL AND analysis_id IS NULL)")
CK_ARTIFACTS_KIND = "kind IN (" + ",".join(f"'{k}'" for k in ARTIFACT_KINDS) + ")"

job_queue_seq = Sequence("job_queue_seq", metadata=metadata)

cases = Table(
    "cases",
    metadata,
    Column("id", ID, primary_key=True),
    Column("project_id", String, nullable=False),
    Column("folder_name", String(64), nullable=False, unique=True),
    Column("title", String(200), nullable=False),
    Column("status", String, nullable=False, server_default="ACTIVE"),
    Column("rad_path", String, nullable=False),
    Column("results_dir", String, nullable=False),
    Column("h3d_path", String, nullable=True),
    Column("input_fingerprint", JSONB, nullable=False),
    Column("part_title", String(200), nullable=False),
    Column("part_id", BigInteger, nullable=True),
    Column("extract_summary", JSONB, nullable=True),
    Column("tstar", JSONB, nullable=True),
    Column("current_support_set_id", ID, nullable=True),
    Column("current_esl_run_id", ID, nullable=True),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    Column("version", BigInteger, nullable=False, server_default="1"),
    CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_cases_status"),
    CheckConstraint("folder_name ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'", name="ck_cases_folder_name"),
    CheckConstraint("lower(split_part(folder_name, '.', 1)) !~ '^(con|prn|aux|nul|com[1-9]|lpt[1-9])$'"
                    " AND folder_name !~ '[. ]$'", name="ck_cases_folder_reserved"),
    CheckConstraint("length(btrim(title)) > 0", name="ck_cases_title"),
    CheckConstraint("version >= 1", name="ck_cases_version"),
    CheckConstraint(
        "tstar IS NULL OR (tstar ? 'frame_index' AND tstar ? 'metric' AND tstar->>'source' IN ('auto','user'))",
        name="ck_cases_tstar",
    ),
)
Index("ix_cases_project", cases.c.project_id, cases.c.status)
# 0002: Windows 예약 장치명(CON·PRN·AUX·NUL·COM1-9·LPT1-9, 확장자 포함)·끝 점/공백 금지, 대소문자 무시 UNIQUE
Index("ux_cases_folder_lower", func.lower(cases.c.folder_name), unique=True)
Index("ux_cases_project_title_active", cases.c.project_id, cases.c.title, unique=True,
      postgresql_where=text("status = 'ACTIVE'"))

jobs = Table(
    "jobs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("case_id", ID, ForeignKey("cases.id"), nullable=True),     # 0003: LIB_ANALYZE 는 NULL
    Column("analysis_id", ID, ForeignKey("analysis_runs.id"), nullable=True),  # 0003: LIB_ANALYZE 대상 분석
    Column("project_id", String, nullable=False),
    Column("job_type", String, nullable=False),
    Column("stage", SmallInteger, nullable=False),
    Column("lane", String, nullable=False),
    Column("state", String, nullable=False),
    Column("holds_slot", Boolean, nullable=False, server_default=text("false")),
    Column("queue_seq", BigInteger, nullable=True),
    Column("queued_at", TS, nullable=True),
    Column("started_at", TS, nullable=True),
    Column("finished_at", TS, nullable=True),
    Column("current_step_no", Integer, nullable=True),
    Column("progress_pct", Float, nullable=True),
    Column("progress_label", String, nullable=True),
    Column("params", JSONB, nullable=False),
    Column("result", JSONB, nullable=True),
    Column("warnings", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("env_snapshot", JSONB, nullable=True),
    Column("failure_code", String, nullable=True),
    Column("failure_message", String(500), nullable=True),
    Column("cancel_requested_at", TS, nullable=True),
    Column("cancel_requested_by", String, nullable=True),
    Column("retry_of_job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("resume_from_step", Integer, nullable=True),
    Column("lease_owner_id", String, nullable=True),
    Column("lease_token", String, nullable=True),
    Column("lease_generation", BigInteger, nullable=False, server_default="0"),
    Column("lease_acquired_at", TS, nullable=True),
    Column("lease_expires_at", TS, nullable=True),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    Column("version", BigInteger, nullable=False, server_default="1"),
    CheckConstraint(CK_JOBS_JOB_TYPE, name="ck_jobs_job_type"),
    CheckConstraint("lane IN ('SLOT','LIGHT')", name="ck_jobs_lane"),
    CheckConstraint(CK_JOBS_STAGE, name="ck_jobs_stage"),
    CheckConstraint(CK_JOBS_SUBJECT, name="ck_jobs_subject"),
    CheckConstraint("state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELED','INTERRUPTED')",
                    name="ck_jobs_state"),
    CheckConstraint("holds_slot = (state = 'RUNNING' AND lane = 'SLOT')", name="ck_jobs_holds_slot"),
    CheckConstraint("(queue_seq IS NOT NULL) = (state = 'QUEUED')", name="ck_jobs_queue_seq"),
    CheckConstraint(
        "(lease_owner_id IS NULL AND lease_token IS NULL AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)"
        " OR (lease_owner_id IS NOT NULL AND lease_token IS NOT NULL AND lease_acquired_at IS NOT NULL"
        " AND lease_expires_at IS NOT NULL AND lease_expires_at > lease_acquired_at)",
        name="ck_jobs_lease_identity",
    ),
    CheckConstraint("lease_token IS NULL OR state = 'RUNNING'", name="ck_jobs_lease_state"),
    CheckConstraint("(state NOT IN ('FAILED','INTERRUPTED')) OR failure_code IS NOT NULL",
                    name="ck_jobs_failure_code"),
    CheckConstraint("version >= 1", name="ck_jobs_version"),
)
Index("ix_jobs_state_lane_seq", jobs.c.state, jobs.c.lane, jobs.c.queue_seq)
Index("ix_jobs_case_created", jobs.c.case_id, jobs.c.created_at.desc())
Index("ux_jobs_case_type_active", jobs.c.case_id, jobs.c.job_type, unique=True,
      postgresql_where=text("state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"))
# 0002: 같은 Case 의 작업은 lane 과 무관하게 동시에 RUNNING 1개(산출물 폴더 직렬화)
Index("ux_jobs_case_running", jobs.c.case_id, unique=True, postgresql_where=text("state = 'RUNNING'"))
# 0003: 같은 분석의 비종료 작업은 1개
Index("ux_jobs_analysis_active", jobs.c.analysis_id, unique=True,
      postgresql_where=text("analysis_id IS NOT NULL AND state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"))

job_steps = Table(
    "job_steps",
    metadata,
    Column("id", ID, primary_key=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),
    Column("step_no", Integer, nullable=False),
    Column("step_key", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("core_stage", String, nullable=True),
    Column("state", String, nullable=False, server_default="PENDING"),
    Column("started_at", TS, nullable=True),
    Column("finished_at", TS, nullable=True),
    Column("exit_code", Integer, nullable=True),
    Column("progress_pct", Float, nullable=True),
    Column("log_rel", String, nullable=True),
    Column("outputs", JSONB, nullable=True),
    Column("failure_code", String, nullable=True),
    Column("failure_message", String(500), nullable=True),
    UniqueConstraint("job_id", "step_no", name="uq_job_steps_job_step"),
    CheckConstraint("kind IN ('INTERNAL')", name="ck_job_steps_kind"),
    CheckConstraint("state IN ('PENDING','RUNNING','SUCCEEDED','FAILED','SKIPPED','CANCELED')",
                    name="ck_job_steps_state"),
    CheckConstraint("state <> 'FAILED' OR failure_code IS NOT NULL", name="ck_job_steps_failure_code"),
)

support_sets = Table(
    "support_sets",
    metadata,
    Column("id", ID, primary_key=True),
    Column("case_id", ID, ForeignKey("cases.id"), nullable=False, index=True),
    Column("node_ids", JSONB, nullable=False),
    Column("dofs", JSONB, nullable=False),
    Column("source", String, nullable=False),
    Column("plane", JSONB, nullable=True),
    Column("created_by", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("source IN ('auto','user')", name="ck_support_sets_source"),
    CheckConstraint("jsonb_typeof(node_ids) = 'array' AND jsonb_array_length(node_ids) = 3",
                    name="ck_support_sets_node_ids"),
    CheckConstraint("jsonb_typeof(dofs) = 'array' AND jsonb_array_length(dofs) = 3", name="ck_support_sets_dofs"),
)

esl_runs = Table(
    "esl_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("case_id", ID, ForeignKey("cases.id"), nullable=False, index=True),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),
    Column("frame_index", Integer, nullable=False),
    Column("time", Float, nullable=True),
    Column("metric", String, nullable=False),
    Column("support_set_id", ID, ForeignKey("support_sets.id"), nullable=False),
    Column("kabsch", JSONB, nullable=True),
    Column("forces", JSONB, nullable=True),
    Column("supports", JSONB, nullable=True),
    Column("warnings", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("dir_rel", String, nullable=False),
    Column("status", String, nullable=False),
    Column("inputs_hash", String(64), nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("status IN ('READY','FAILED')", name="ck_esl_runs_status"),
    CheckConstraint("frame_index >= 0", name="ck_esl_runs_frame"),
)

validations = Table(
    "validations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("esl_run_id", ID, ForeignKey("esl_runs.id"), nullable=False, index=True),
    Column("case_id", ID, ForeignKey("cases.id"), nullable=False),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),
    Column("disp_rms_rel", Float, nullable=True),
    Column("reaction_rel", Float, nullable=True),
    Column("hotspots", JSONB, nullable=False),
    Column("excluded", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("verdict", String, nullable=False),
    Column("fail_reasons", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("criteria", JSONB, nullable=False),
    Column("field", JSONB, nullable=True),          # 0003: validation.json field 요약(계약 P2 §7.2)
    Column("dir_rel", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("verdict IN ('PASS','FAIL')", name="ck_validations_verdict"),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("id", ID, primary_key=True),
    Column("case_id", ID, ForeignKey("cases.id"), nullable=False),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("kind", String, nullable=False),
    Column("rel", String, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("sha256", String(64), nullable=True),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    UniqueConstraint("case_id", "rel", name="uq_artifacts_case_rel"),
    CheckConstraint(CK_ARTIFACTS_KIND, name="ck_artifacts_kind"),
    CheckConstraint("size >= 0", name="ck_artifacts_size"),
    CheckConstraint("rel NOT LIKE '/%' AND rel NOT LIKE '%..%'", name="ck_artifacts_rel"),
)

# ---------------------------------------------------------------- 0003: 라이브러리(계약 esl_p2_library.md §11)
library_entries = Table(
    "library_entries",
    metadata,
    Column("id", ID, primary_key=True),
    Column("project_id", String, nullable=False),
    Column("case_id", ID, ForeignKey("cases.id"), nullable=False),
    Column("esl_run_id", ID, ForeignKey("esl_runs.id"), nullable=False),
    Column("validation_id", ID, ForeignKey("validations.id"), nullable=True),
    Column("status", String, nullable=False, server_default="ACTIVE"),
    Column("model", JSONB, nullable=False),       # {name, inch, version, date, product_mass, part_mass, ...}
    Column("scene", JSONB, nullable=False),       # {project, scenario, seq, drop_type, drop_class, round, scene_no, ...}
    Column("quality", JSONB, nullable=False),     # {verdict, field_max_err_pct, field_p90_err_pct, noise, ...}
    Column("tstar", JSONB, nullable=True),
    Column("summary", JSONB, nullable=True),      # 정규화 요약 메타(grid, total_F·M, sum_abs_f, mesh_sha256 …)
    Column("dir_rel", String, nullable=False),    # esl_root 기준 항목 폴더(_library/entries/<id>)
    Column("summary_rel", String, nullable=False),  # esl_root 기준 summary.npz
    Column("sha256", String(64), nullable=False),   # summary.npz sha256
    Column("files", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("warnings", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("note", String(2000), nullable=True),
    Column("force_reason", String(2000), nullable=True),
    Column("registered_by", String, nullable=False),
    Column("registered_by_name", String, nullable=False),
    Column("registered_at", TS, nullable=False, server_default=func.now()),
    Column("retired_by_id", String, nullable=True),
    Column("retired_at", TS, nullable=True),
    Column("retire_reason", String(2000), nullable=True),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    Column("version", BigInteger, nullable=False, server_default="1"),
    CheckConstraint("status IN ('ACTIVE','RETIRED')", name="ck_library_entries_status"),
    CheckConstraint("(status = 'RETIRED') = (retired_at IS NOT NULL)", name="ck_library_entries_retired"),
    CheckConstraint("dir_rel NOT LIKE '/%' AND dir_rel NOT LIKE '%..%'", name="ck_library_entries_dir_rel"),
    CheckConstraint("version >= 1", name="ck_library_entries_version"),
)
Index("ux_library_entries_run_active", library_entries.c.esl_run_id, unique=True,
      postgresql_where=text("status = 'ACTIVE'"))
Index("ix_library_entries_project", library_entries.c.project_id, library_entries.c.status)

analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("project_id", String, nullable=False),
    Column("title", String(200), nullable=True),
    Column("target_entry_id", ID, ForeignKey("library_entries.id"), nullable=True),
    Column("filters", JSONB, nullable=False),
    Column("options", JSONB, nullable=False),
    Column("entry_ids", JSONB, nullable=False),   # 생성 시점에 확정한 대상 항목 id 목록
    Column("job_id", ID, nullable=True),          # 최신 LIB_ANALYZE 작업(상태 = 작업 상태, 순환 FK 없음)
    Column("result", JSONB, nullable=True),       # 요약: 대표·포락·통계
    Column("result_rel", String, nullable=True),  # esl_root 기준 analysis.json
    Column("report_rel", String, nullable=True),
    Column("optdeck_rel", String, nullable=True),
    Column("dir_rel", String, nullable=False),    # _analysis/<id>
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("jsonb_typeof(entry_ids) = 'array' AND jsonb_array_length(entry_ids) >= 1",
                    name="ck_analysis_runs_entry_ids"),
    CheckConstraint("dir_rel NOT LIKE '/%' AND dir_rel NOT LIKE '%..%'", name="ck_analysis_runs_dir_rel"),
)
Index("ix_analysis_runs_project", analysis_runs.c.project_id, analysis_runs.c.created_at.desc())

notifications = Table(
    "notifications",
    metadata,
    Column("seq", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", String, nullable=False),
    Column("event", String, nullable=False),
    Column("job_id", ID, nullable=True),
    Column("case_id", ID, nullable=True),
    Column("project_id", String, nullable=True),
    Column("title", String(120), nullable=False),
    Column("body", String(500), nullable=False, server_default=""),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("read_at", TS, nullable=True),
    CheckConstraint(
        "event IN ('JOB_STARTED','JOB_SUCCEEDED','JOB_FAILED','JOB_CANCELED','JOB_INTERRUPTED')",
        name="ck_notifications_event",
    ),
)
Index("ix_notifications_user_seq", notifications.c.user_id, notifications.c.seq.desc())

worker_slot = Table(
    "worker_slot",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("holder_job_id", ID, nullable=True),
    Column("lease_owner_id", String, nullable=True),
    Column("lease_token", String, nullable=True),
    Column("lease_generation", BigInteger, nullable=False, server_default="0"),
    Column("lease_acquired_at", TS, nullable=True),
    Column("lease_expires_at", TS, nullable=True),
    CheckConstraint("id = 1", name="ck_worker_slot_single"),
    CheckConstraint(
        "(lease_owner_id IS NULL AND lease_token IS NULL AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)"
        " OR (lease_owner_id IS NOT NULL AND lease_token IS NOT NULL AND lease_acquired_at IS NOT NULL"
        " AND lease_expires_at IS NOT NULL AND lease_expires_at > lease_acquired_at)",
        name="ck_worker_slot_lease_identity",
    ),
    CheckConstraint("(holder_job_id IS NULL) = (lease_token IS NULL)", name="ck_worker_slot_holder"),
)

worker_heartbeats = Table(
    "worker_heartbeats",
    metadata,
    Column("worker_id", String, primary_key=True),
    Column("host", String, nullable=False),
    Column("pid", Integer, nullable=False),
    Column("app_version", String, nullable=False),
    Column("started_at", TS, nullable=False, server_default=func.now()),
    Column("last_seen_at", TS, nullable=False, server_default=func.now()),
    Column("limiter", String, nullable=True),
    Column("info", JSONB, nullable=True),
)

__all__ = [
    "metadata", "job_queue_seq", "cases", "jobs", "job_steps", "support_sets", "esl_runs", "validations",
    "artifacts", "notifications", "worker_slot", "worker_heartbeats", "library_entries", "analysis_runs",
    "TERMINAL_STATES", "JOB_TYPES", "ARTIFACT_KINDS",
]
