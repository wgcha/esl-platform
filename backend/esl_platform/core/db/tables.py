"""DB 스키마(계약 esl.md §3 + esl_platform_p1b.md §3 + esl_p2_library.md §11·§12 + esl_opt_run.md §12
+ esl_bead_doe.md §13).
SQLAlchemy Core, PostgreSQL 전용.

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
JOB_TYPES = ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE", "EXPORT", "CASE_REPORT", "LIB_ANALYZE", "LIB_COMPARE", "OPT_RUN",
             "DOE_PREP", "DOE_PREVIEW", "DOE_RUN")          # 0011: 비드 DOE 3종
DOE_JOB_TYPES = ("DOE_PREP", "DOE_PREVIEW", "DOE_RUN")
ARTIFACT_KINDS = ("CASE", "EXTRACT", "TSTAR", "SUPPORT", "ESL", "VALIDATION", "EXPORT", "REPORT", "RUN", "LOG",
                  "OPT_RESULT", "OPT_SOLVE",     # 0010: 비드 최적화 결과·OptiStruct 원본
                  "DOE_RESULT")                  # 0011: 비드 DOE 결과
# 0003: 제약 SQL(마이그레이션과 공유)
CK_JOBS_JOB_TYPE = "job_type IN (" + ",".join(f"'{t}'" for t in JOB_TYPES) + ")"
CK_JOBS_STAGE = "stage BETWEEN 1 AND 11"    # 0004: 9 = 설계 버전 비교, 0010: 10 = 비드 최적화, 0011: 11 = 비드 DOE
# 0004·0010·0011: 작업 대상은 정확히 하나 — Case(Case 작업) | 분석(LIB_ANALYZE) | 비교(LIB_COMPARE) | 최적화 실행(OPT_RUN)
# | 비드 DOE 연구(DOE_PREP·DOE_PREVIEW·DOE_RUN)
_DOE_IN = "('DOE_PREP','DOE_PREVIEW','DOE_RUN')"
CK_JOBS_SUBJECT = ("(job_type = 'LIB_ANALYZE' AND case_id IS NULL AND analysis_id IS NOT NULL"
                   " AND comparison_id IS NULL AND opt_run_id IS NULL AND bead_doe_id IS NULL)"
                   " OR (job_type = 'LIB_COMPARE' AND case_id IS NULL AND analysis_id IS NULL"
                   " AND comparison_id IS NOT NULL AND opt_run_id IS NULL AND bead_doe_id IS NULL)"
                   " OR (job_type = 'OPT_RUN' AND case_id IS NULL AND analysis_id IS NULL"
                   " AND comparison_id IS NULL AND opt_run_id IS NOT NULL AND bead_doe_id IS NULL)"
                   f" OR (job_type IN {_DOE_IN} AND case_id IS NULL AND analysis_id IS NULL"
                   " AND comparison_id IS NULL AND opt_run_id IS NULL AND bead_doe_id IS NOT NULL)"
                   f" OR (job_type NOT IN ('LIB_ANALYZE','LIB_COMPARE','OPT_RUN','DOE_PREP','DOE_PREVIEW','DOE_RUN')"
                   " AND case_id IS NOT NULL AND analysis_id IS NULL AND comparison_id IS NULL AND opt_run_id IS NULL"
                   " AND bead_doe_id IS NULL)")
# 0006: Case 입력 종류, step 종류(LOCAL = 워커가 외부 프로그램 실행), worker_slot 행 수(worker.slots 상한)
CK_CASES_INPUT_KIND = "input_kind IN ('RESULTS','H3D') AND (input_kind = 'RESULTS' OR h3d_path IS NOT NULL)"
CK_JOB_STEPS_KIND = "kind IN ('INTERNAL','LOCAL')"
WORKER_SLOT_ROWS = 16
CK_WORKER_SLOT_RANGE = f"id BETWEEN 1 AND {WORKER_SLOT_ROWS}"
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
    # 0006(P3-UX §6): RESULTS = 추출 결과 폴더 입력, H3D = 서버 h3d 추출(CASE_EXTRACT 첫 step H3D_EXTRACT)
    Column("input_kind", String, nullable=False, server_default="RESULTS"),
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
    CheckConstraint(CK_CASES_INPUT_KIND, name="ck_cases_input_kind"),
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
    Column("comparison_id", ID, ForeignKey("comparisons.id"), nullable=True),  # 0004: LIB_COMPARE 대상 비교
    Column("opt_run_id", ID, ForeignKey("opt_runs.id"), nullable=True),        # 0010: OPT_RUN 대상 최적화 실행
    Column("bead_doe_id", ID, ForeignKey("bead_does.id"), nullable=True),      # 0011: DOE_* 대상 비드 DOE 연구
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
# 0004: 같은 비교의 비종료 작업은 1개
Index("ux_jobs_comparison_active", jobs.c.comparison_id, unique=True,
      postgresql_where=text("comparison_id IS NOT NULL AND state NOT IN ('SUCCEEDED','FAILED','CANCELED',"
                            "'INTERRUPTED')"))
# 0007(P3-이력): 프로젝트 범위 실행 이력 목록(keyset created_at DESC, id DESC)·"내 작업만"·재시도 후속 작업 조회
Index("ix_jobs_project_created", jobs.c.project_id, jobs.c.created_at.desc(), jobs.c.id.desc())
Index("ix_jobs_project_creator_created", jobs.c.project_id, jobs.c.created_by, jobs.c.created_at.desc())
Index("ix_jobs_retry_of", jobs.c.retry_of_job_id, postgresql_where=text("retry_of_job_id IS NOT NULL"))
# 0010: 최적화 실행 → 작업, 같은 실행의 비종료 작업은 1개
Index("ix_jobs_opt_run", jobs.c.opt_run_id, postgresql_where=text("opt_run_id IS NOT NULL"))
Index("ux_jobs_opt_run_active", jobs.c.opt_run_id, unique=True,
      postgresql_where=text("opt_run_id IS NOT NULL AND state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"))
# 0011: 비드 DOE 연구당 비종료 작업 1개(PREP·PREVIEW·RUN 통틀어)
Index("ix_jobs_bead_doe", jobs.c.bead_doe_id, postgresql_where=text("bead_doe_id IS NOT NULL"))
Index("ux_jobs_bead_doe_active", jobs.c.bead_doe_id, unique=True,
      postgresql_where=text("bead_doe_id IS NOT NULL AND state NOT IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"))

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
    Column("command", JSONB, nullable=True),        # 0006: LOCAL step 실행 직전 argv(전역 관리자만 — API 응답에 없음)
    UniqueConstraint("job_id", "step_no", name="uq_job_steps_job_step"),
    CheckConstraint(CK_JOB_STEPS_KIND, name="ck_job_steps_kind"),
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
Index("ix_esl_runs_job", esl_runs.c.job_id)       # 0007: 작업 → ESL 실행(이력)

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
    # 0008(계약 esl_disp_primary.md §6): 변위 주지표 판정. scheme NULL = 이전 판정 체계(LEGACY, 백필 없음)
    Column("scheme", String, nullable=True),
    Column("disp_max_rel", Float, nullable=True),
    Column("disp_noise_rel", Float, nullable=True),
    Column("undetermined_reason", String, nullable=True),
    Column("disp", JSONB, nullable=True),
    Column("strain_ref", JSONB, nullable=True),
    CheckConstraint("verdict IN ('PASS','FAIL','UNDETERMINED')", name="ck_validations_verdict"),
    CheckConstraint("scheme IS NULL OR scheme IN ('disp_primary/1')", name="ck_validations_scheme"),
    CheckConstraint("verdict <> 'UNDETERMINED' OR (scheme IS NOT NULL AND undetermined_reason IS NOT NULL)",
                    name="ck_validations_undetermined"),
)
Index("ix_validations_job", validations.c.job_id)  # 0007: 작업 → 검증(이력)

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
    # 0010(esl_opt_run.md §7.3·§7.4): S1 모델 키(노드 ID + 요소 연결, 좌표 제외)·변형 모드 레코드 — 기존 행은 첫 조회 때 지연 백필
    Column("topo_sha256", String(64), nullable=True),
    Column("deform_mode", JSONB, nullable=True),
    CheckConstraint("status IN ('ACTIVE','RETIRED')", name="ck_library_entries_status"),
    CheckConstraint("(status = 'RETIRED') = (retired_at IS NOT NULL)", name="ck_library_entries_retired"),
    CheckConstraint("dir_rel NOT LIKE '/%' AND dir_rel NOT LIKE '%..%'", name="ck_library_entries_dir_rel"),
    CheckConstraint("version >= 1", name="ck_library_entries_version"),
)
Index("ux_library_entries_run_active", library_entries.c.esl_run_id, unique=True,
      postgresql_where=text("status = 'ACTIVE'"))
Index("ix_library_entries_project", library_entries.c.project_id, library_entries.c.status)
Index("ix_library_entries_topo", library_entries.c.topo_sha256)

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

# ---------------------------------------------------------------- 0004: 설계 버전 비교(계약 esl_p2_library.md §12.2)
comparisons = Table(
    "comparisons",
    metadata,
    Column("id", ID, primary_key=True),
    Column("project_id", String, nullable=False),
    Column("title", String(200), nullable=True),
    Column("model", String(200), nullable=False),          # 제품명(library_entries.model.name)
    Column("base_version", String(64), nullable=False),
    Column("new_version", String(64), nullable=False),
    Column("filters", JSONB, nullable=False),
    Column("options", JSONB, nullable=False),
    Column("base_entry_ids", JSONB, nullable=False),        # 생성 시점에 확정한 기준 버전 항목
    Column("new_entry_ids", JSONB, nullable=False),         # 생성 시점에 확정한 비교 버전 항목
    Column("n_paired", Integer, nullable=False),            # 생성 시점 씬 키 짝 수(≥1)
    Column("job_id", ID, nullable=True),                    # 최신 LIB_COMPARE 작업(상태 = 작업 상태)
    Column("verdict", String, nullable=True),               # CONVERGED | ITERATE (작업 완료 후)
    Column("result", JSONB, nullable=True),                 # 요약: 판정·집계·씬 표
    Column("result_rel", String, nullable=True),            # esl_root 기준 compare.json
    Column("report_rel", String, nullable=True),
    Column("dir_rel", String, nullable=False),              # _compare/<id>
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("base_version <> new_version", name="ck_comparisons_versions"),
    CheckConstraint("jsonb_typeof(base_entry_ids) = 'array' AND jsonb_array_length(base_entry_ids) >= 1"
                    " AND jsonb_typeof(new_entry_ids) = 'array' AND jsonb_array_length(new_entry_ids) >= 1",
                    name="ck_comparisons_entry_ids"),
    CheckConstraint("n_paired >= 1", name="ck_comparisons_n_paired"),
    CheckConstraint("verdict IS NULL OR verdict IN ('CONVERGED','ITERATE')", name="ck_comparisons_verdict"),
    CheckConstraint("dir_rel NOT LIKE '/%' AND dir_rel NOT LIKE '%..%'", name="ck_comparisons_dir_rel"),
)
Index("ix_comparisons_project", comparisons.c.project_id, comparisons.c.created_at.desc())

# ---------------------------------------------------------------- 0010: 비드 최적화(계약 esl_opt_run.md §12)
OPT_SCENARIOS = ("S1", "S2")
opt_templates = Table(
    "opt_templates",
    metadata,
    Column("id", ID, primary_key=True),
    Column("title", String(200), nullable=False),
    Column("description", String(2000), nullable=False, server_default=""),
    Column("inch", Integer, nullable=True),
    Column("format", String(8), nullable=False),            # rad | fem
    Column("file_name", String(255), nullable=False),
    Column("part_title", String(200), nullable=True),
    Column("sha256", String(64), nullable=False),
    Column("n_nodes", Integer, nullable=False),
    Column("n_elems", Integer, nullable=False),
    Column("L_xi", Float, nullable=False),
    Column("L_eta", Float, nullable=False),
    Column("z_range", JSONB, nullable=False),
    Column("pids", JSONB, nullable=False),
    Column("quality", JSONB, nullable=False),
    Column("dir_rel", String, nullable=False),              # _templates/<id>
    Column("status", String, nullable=False, server_default="ACTIVE"),
    Column("origin_project_id", String, nullable=True),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("archived_by", String, nullable=True),
    Column("archived_at", TS, nullable=True),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_opt_templates_status"),
    CheckConstraint("format IN ('rad','fem')", name="ck_opt_templates_format"),
    CheckConstraint("(status = 'ARCHIVED') = (archived_at IS NOT NULL) AND (archived_at IS NULL) = (archived_by IS NULL)",
                    name="ck_opt_templates_archived"),
    CheckConstraint("length(btrim(title)) > 0", name="ck_opt_templates_title"),
    CheckConstraint("dir_rel NOT LIKE '/%' AND dir_rel NOT LIKE '%..%'", name="ck_opt_templates_dir_rel"),
)
Index("ix_opt_templates_status", opt_templates.c.status, opt_templates.c.created_at.desc())

opt_keepouts = Table(
    "opt_keepouts",
    metadata,
    Column("id", ID, primary_key=True),
    Column("template_id", ID, ForeignKey("opt_templates.id", ondelete="CASCADE"), nullable=True),
    Column("topo_sha256", String(64), nullable=True),
    Column("rects", JSONB, nullable=False),
    Column("auto", JSONB, nullable=False),
    Column("frame", JSONB, nullable=False),                 # 저장 시점 대상 frame {a_range, b_range}
    Column("version", BigInteger, nullable=False, server_default="1"),
    Column("updated_by", String, nullable=False),
    Column("updated_by_name", String, nullable=False),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("(template_id IS NULL) <> (topo_sha256 IS NULL)", name="ck_opt_keepouts_key"),
    CheckConstraint("jsonb_typeof(rects) = 'array'", name="ck_opt_keepouts_rects"),
    CheckConstraint("version >= 1", name="ck_opt_keepouts_version"),
)
Index("ux_opt_keepouts_template", opt_keepouts.c.template_id, unique=True,
      postgresql_where=text("template_id IS NOT NULL"))
Index("ux_opt_keepouts_topo", opt_keepouts.c.topo_sha256, unique=True, postgresql_where=text("topo_sha256 IS NOT NULL"))

opt_runs = Table(
    "opt_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("project_id", String, nullable=False),
    Column("scenario", String(2), nullable=False),
    Column("title", String(200), nullable=True),
    Column("entry_ids", JSONB, nullable=False),
    Column("analysis_id", ID, ForeignKey("analysis_runs.id"), nullable=True),
    Column("base", JSONB, nullable=True),                   # S1: 기준 ESL·Case·대상 파트
    Column("template_id", ID, ForeignKey("opt_templates.id"), nullable=True),   # S2
    Column("size", JSONB, nullable=True),
    Column("design", JSONB, nullable=False),                # bead·nondesign_pids·keepout 스냅샷
    Column("options", JSONB, nullable=False),
    Column("load_strategy", String(1), nullable=False, server_default="A"),
    Column("objective_norm", String(3), nullable=False, server_default="abs"),
    Column("k", SmallInteger, nullable=True),
    Column("job_id", ID, nullable=True),                    # 최신 OPT_RUN 작업(순환 FK 없음)
    Column("result", JSONB, nullable=True),
    Column("report_rel", String, nullable=True),
    Column("dir_rel", String, nullable=False),              # _opt/<id>
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("scenario IN ('S1','S2')", name="ck_opt_runs_scenario"),
    CheckConstraint("(scenario = 'S1' AND base IS NOT NULL AND template_id IS NULL)"
                    " OR (scenario = 'S2' AND template_id IS NOT NULL AND base IS NULL)", name="ck_opt_runs_subject"),
    CheckConstraint("jsonb_typeof(entry_ids) = 'array' AND jsonb_array_length(entry_ids) >= 1",
                    name="ck_opt_runs_entry_ids"),
    CheckConstraint("load_strategy IN ('A','B','C')", name="ck_opt_runs_load_strategy"),
    CheckConstraint("objective_norm IN ('abs','rel')", name="ck_opt_runs_objective_norm"),
    CheckConstraint("load_strategy <> 'C' OR (k IS NOT NULL AND k >= 1)", name="ck_opt_runs_k"),
    CheckConstraint("dir_rel NOT LIKE '/%' AND dir_rel NOT LIKE '%..%'", name="ck_opt_runs_dir_rel"),
)
Index("ix_opt_runs_project", opt_runs.c.project_id, opt_runs.c.created_at.desc())
Index("ix_opt_runs_template", opt_runs.c.template_id)

# ---------------------------------------------------------------- 0011: 비드 DOE(계약 esl_bead_doe.md §13)
DOE_SCENARIOS = ("same", "mesh", "step")
DOE_PHASES = ("PREP", "READY", "PREVIEW", "PREVIEW_READY", "RUN", "DONE", "FAILED")
bead_does = Table(
    "bead_does",
    metadata,
    Column("id", ID, primary_key=True),
    Column("project_id", String, nullable=False),
    Column("scenario", String(4), nullable=False),
    Column("title", String(200), nullable=False),
    Column("entry_ids", JSONB, nullable=False),
    Column("base", JSONB, nullable=True),                   # ① 기준 entry·case·part(서버 경로 없음 — 경로는 작업 params 에만)
    Column("inputs", JSONB, nullable=False),                # step·mesh(upload_id·sha256·file_name), part_title, inch, props, mesh_size_mm
    Column("phase", String(16), nullable=False, server_default="PREP"),
    Column("version", BigInteger, nullable=False, server_default="1"),    # 낙관적 잠금
    Column("prep", JSONB, nullable=True),                   # 준비 요약(n_beads, n_params, paicad_version, warnings, boundary)
    Column("doe", JSONB, nullable=True),                    # rev, spec, matrix_sha256, n_designs, preview 요약
    Column("run", JSONB, nullable=True),                    # solver, parallel
    Column("result", JSONB, nullable=True),                 # DoeResultOut 요약(ranking ≤ max_designs 행)
    Column("report_rel", String, nullable=True),
    Column("dir_rel", String, nullable=False),              # _doe/<id>
    Column("paicad_version", String(32), nullable=True),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("scenario IN ('same','mesh','step')", name="ck_bead_does_scenario"),
    CheckConstraint("phase IN ('PREP','READY','PREVIEW','PREVIEW_READY','RUN','DONE','FAILED')",
                    name="ck_bead_does_phase"),
    CheckConstraint("scenario <> 'same' OR base IS NOT NULL", name="ck_bead_does_base"),
    CheckConstraint("jsonb_typeof(entry_ids) = 'array' AND jsonb_array_length(entry_ids) >= 1",
                    name="ck_bead_does_entry_ids"),
    CheckConstraint("version >= 1", name="ck_bead_does_version"),
    CheckConstraint("dir_rel NOT LIKE '/%' AND dir_rel NOT LIKE '%..%'", name="ck_bead_does_dir_rel"),
)
Index("ix_bead_does_project", bead_does.c.project_id, bead_does.c.created_at.desc())

# P3-UX 브라우저 분할 업로드 세션(계약 esl_p3_ux.md §1.1). 파일 본문은 디스크(<upload_root>/...)에만, 여기는 목록·상태.
UPLOAD_STATES = ("OPEN", "COMPLETED", "CANCELED", "STALE")
uploads = Table(
    "uploads",
    metadata,
    Column("id", ID, primary_key=True),
    Column("project_id", String, nullable=False),
    Column("user_id", String, nullable=False),
    Column("username", String, nullable=False),
    Column("name", String(200), nullable=False),            # 사용자가 준 이름(정규화 전)
    Column("dir_path", String, nullable=False),             # <upload_root>/<user>/<UTC>_<name> 절대경로
    Column("state", String, nullable=False, server_default="OPEN"),
    Column("files", JSONB, nullable=False),                 # [{rel,size,sha256_expected,sha256,done}]
    Column("total_bytes", BigInteger, nullable=False),
    Column("result", JSONB, nullable=True),                 # 마지막 complete 검사 결과
    Column("backup_path", String, nullable=True),           # 취소·stale 시 옮긴 위치(<upload_root>/_backup/...)
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    Column("completed_at", TS, nullable=True),
    CheckConstraint("state IN ('OPEN','COMPLETED','CANCELED','STALE')", name="ck_uploads_state"),
    CheckConstraint("jsonb_typeof(files) = 'array'", name="ck_uploads_files"),
    CheckConstraint("total_bytes >= 0", name="ck_uploads_total"),
)
Index("ix_uploads_user_state", uploads.c.user_id, uploads.c.state)
Index("ix_uploads_state_updated", uploads.c.state, uploads.c.updated_at)

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
    CheckConstraint(CK_WORKER_SLOT_RANGE, name="ck_worker_slot_range"),   # 0006: 행 1..16(worker.slots 만큼 사용)
    CheckConstraint(
        "(lease_owner_id IS NULL AND lease_token IS NULL AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)"
        " OR (lease_owner_id IS NOT NULL AND lease_token IS NOT NULL AND lease_acquired_at IS NOT NULL"
        " AND lease_expires_at IS NOT NULL AND lease_expires_at > lease_acquired_at)",
        name="ck_worker_slot_lease_identity",
    ),
    CheckConstraint("(holder_job_id IS NULL) = (lease_token IS NULL)", name="ck_worker_slot_holder"),
)

# ---------------------------------------------------------------- 0006: PC 연결 코드·토큰(계약 esl_p3_ux.md §9.1)
# 코드·토큰 원문은 저장하지 않는다(sha256 만). 토큰 범위 = project_id 의 /uploads* 와 /version.
client_codes = Table(
    "client_codes",
    metadata,
    Column("id", ID, primary_key=True),
    Column("code_hash", String(64), nullable=False),
    Column("project_id", String, nullable=False),
    Column("project_name", String, nullable=True),
    Column("user_id", String, nullable=False),
    Column("username", String, nullable=False),
    Column("display_name", String, nullable=False),
    Column("role", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("expires_at", TS, nullable=False),
    Column("used_at", TS, nullable=True),
    Column("token_id", ID, nullable=True),
    CheckConstraint("role IN ('power','admin')", name="ck_client_codes_role"),
    CheckConstraint("expires_at > created_at", name="ck_client_codes_expires"),
)
Index("ix_client_codes_hash", client_codes.c.code_hash)

client_tokens = Table(
    "client_tokens",
    metadata,
    Column("id", ID, primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("token_prefix", String(16), nullable=False),        # 표시용 앞부분(esl_ct_xxxx)
    Column("project_id", String, nullable=False),
    Column("project_name", String, nullable=True),
    Column("user_id", String, nullable=False),
    Column("username", String, nullable=False),
    Column("display_name", String, nullable=False),
    Column("role", String, nullable=False),
    Column("device_name", String(100), nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("expires_at", TS, nullable=False),
    Column("last_used_at", TS, nullable=True),
    Column("revoked_at", TS, nullable=True),
    Column("revoked_by", String, nullable=True),
    CheckConstraint("role IN ('power','admin')", name="ck_client_tokens_role"),
    CheckConstraint("expires_at > created_at", name="ck_client_tokens_expires"),
)
Index("ix_client_tokens_user", client_tokens.c.user_id, client_tokens.c.created_at.desc())

client_code_failures = Table(
    "client_code_failures",
    metadata,
    Column("source", String(100), primary_key=True),           # 요청 출발지(IP)
    Column("failures", Integer, nullable=False, server_default="0"),
    Column("window_started_at", TS, nullable=False, server_default=func.now()),
    Column("locked_until", TS, nullable=True),
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
    "comparisons", "uploads", "opt_templates", "opt_keepouts", "opt_runs", "bead_does", "OPT_SCENARIOS", "DOE_SCENARIOS",
    "DOE_PHASES", "DOE_JOB_TYPES", "UPLOAD_STATES", "client_codes", "client_tokens", "client_code_failures",
    "TERMINAL_STATES", "JOB_TYPES", "ARTIFACT_KINDS",
]
