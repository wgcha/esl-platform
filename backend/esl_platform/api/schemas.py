"""요청·응답 스키마(Pydantic v2). 응답에 lease_*·세션 토큰 없음."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FOLDER_RE = r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$"
WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)


def check_folder_name(v: str) -> str:
    """Case 폴더명: FOLDER_RE + Windows 예약 장치명(확장자 붙어도)·끝 점/공백 금지."""
    if v != v.rstrip(" .") or v.endswith((" ", ".")):
        raise ValueError("폴더 이름은 점이나 공백으로 끝날 수 없습니다")
    if WIN_RESERVED.match(v.split(".", 1)[0].strip()):
        raise ValueError(f"Windows 예약 이름은 폴더 이름으로 쓸 수 없습니다: {v}")
    return v


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------- 요청
class InspectReq(_Req):
    purpose: Literal["RAD", "RESULTS", "H3D"]
    path: str = Field(min_length=1, max_length=1024)
    part_title: str | None = Field(default=None, max_length=200)  # RAD 전용. 없으면 설정 case.part_title


class CaseCreate(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    folder_name: str = Field(pattern=FOLDER_RE)
    title: str = Field(min_length=1, max_length=200)
    rad_path: str = Field(min_length=1, max_length=1024)
    # P3-UX §6: 결과 폴더(PC 추출) 또는 h3d(서버 추출) 중 정확히 하나
    results_dir: str | None = Field(default=None, min_length=1, max_length=1024)
    h3d_path: str | None = Field(default=None, min_length=1, max_length=1024)
    part_title: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _one_input(self) -> "CaseCreate":
        if (self.results_dir is None) == (self.h3d_path is None):
            raise ValueError("results_dir 와 h3d_path 중 정확히 하나가 필요합니다")
        return self

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("빈 제목")
        return v.strip()

    @field_validator("folder_name")
    @classmethod
    def _folder(cls, v: str) -> str:
        return check_folder_name(v)


class CasePatch(_Req):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    part_title: str | None = Field(default=None, min_length=1, max_length=200)


class JobCreate(_Req):
    job_type: Literal["CASE_EXTRACT", "ESL_SOLVE", "VALIDATE", "EXPORT", "CASE_REPORT"]
    params: dict[str, Any] = Field(default_factory=dict)


class CaseExtractParams(_Req):
    """CASE_EXTRACT(P3-UX §6): h3d 입력일 때 추출 옵션(없으면 코어 설정 extract.hot_k·tstar.top_n_times)."""

    hot_k: int | None = Field(default=None, ge=1, le=100000)
    top_n: int | None = Field(default=None, ge=1, le=100)


class CaseReportParams(_Req):
    validation_id: str | None = None


class EslSolveParams(_Req):
    frame_index: int | None = Field(default=None, ge=0)
    support_set_id: str | None = None
    material_override: dict[str, dict[str, float]] | None = None


class RunRefParams(_Req):
    esl_run_id: str


class ExportParams(_Req):
    esl_run_id: str
    targets: list[Literal["radioss_inc", "fem", "csv"]] = Field(default_factory=lambda: ["radioss_inc", "fem", "csv"],
                                                                min_length=1)


class TstarPut(_Req):
    version: int = Field(ge=1)
    metric: str = Field(min_length=1, max_length=40)
    frame_index: int = Field(ge=0)


class SupportSuggestReq(_Req):
    pass


class SupportCreate(_Req):
    node_ids: list[int] = Field(min_length=3, max_length=3)

    @field_validator("node_ids")
    @classmethod
    def _distinct(cls, v: list[int]) -> list[int]:
        if len(set(v)) != 3:
            raise ValueError("서로 다른 노드 ID 3개")
        return v


# ---------------------------------------------------------------- 응답
class Health(_Out):
    status: str
    version: str


class Me(_Out):
    user_id: str
    username: str
    display_name: str
    is_global_admin: bool
    roles: dict[str, str]


class Project(_Out):
    id: str
    name: str
    product_name: str | None = None


class StageState(_Out):
    state: Literal["none", "running", "done", "stale", "failed"]
    job_id: str | None = None


class CaseOut(_Out):
    id: str
    project_id: str
    folder_name: str
    title: str
    status: str
    rad_path: str
    results_dir: str
    h3d_path: str | None = None
    input_kind: Literal["RESULTS", "H3D"] = "RESULTS"
    input_fingerprint: dict[str, Any]
    part_title: str
    part_id: int | None = None
    extract_summary: dict[str, Any] | None = None
    tstar: dict[str, Any] | None = None
    current_support_set_id: str | None = None
    current_esl_run_id: str | None = None
    case_dir: str
    folder_path: str
    created_by: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    version: int
    stage_status: dict[str, StageState] | None = None


class StepOut(_Out):
    step_no: int
    step_key: str
    kind: str
    core_stage: str | None = None
    state: str
    progress_pct: float | None = None
    exit_code: int | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobOut(_Out):
    id: str
    case_id: str | None = None
    analysis_id: str | None = None
    comparison_id: str | None = None
    project_id: str
    job_type: str
    stage: int
    lane: str
    state: str
    queue_position: int | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_step_no: int | None = None
    progress_pct: float | None = None
    params: dict[str, Any]
    result: dict[str, Any] | None = None
    warnings: list[Any]
    failure_code: str | None = None
    failure_message: str | None = None
    cancel_requested: bool
    retry_of_job_id: str | None = None
    resume_from_step: int | None = None
    created_by: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    version: int
    steps: list[StepOut] | None = None


class QueueLane(_Out):
    running: JobOut | None = None
    queued: list[JobOut]


class QueueOut(_Out):
    running: JobOut | None = None
    running_all: list[JobOut] = []          # P3-UX §6: SLOT 레인 동시 실행(worker.slots) — 시작 순
    slots: int = 1
    queued: list[JobOut]
    light: QueueLane


class LogOut(_Out):
    step: int
    lines: list[str]
    next_cursor: int
    eof: bool


class SupportSetOut(_Out):
    id: str
    case_id: str
    node_ids: list[int]
    dofs: list[str]
    source: str
    plane: dict[str, Any] | None = None
    created_by: str
    created_at: datetime
    is_current: bool = False


class SupportSuggestOut(_Out):
    node_ids: list[int]
    dofs: list[str]
    coords: list[list[float]]
    plane: dict[str, Any]
    corners: list[int]


class EslRunOut(_Out):
    id: str
    case_id: str
    job_id: str
    frame_index: int
    time: float | None = None
    metric: str
    support_set_id: str
    kabsch: dict[str, Any] | None = None
    forces: dict[str, Any] | None = None
    supports: list[dict[str, Any]] | None = None
    warnings: list[Any]
    dir_rel: str
    status: str
    created_at: datetime
    stale: bool
    is_current: bool
    latest_validation_id: str | None = None


class ForceRow(_Out):
    node_id: int
    x: float
    y: float
    z: float
    fx: float
    fy: float
    fz: float
    mag: float
    is_support: bool


class ForcesOut(_Out):
    esl_run_id: str
    n_nodes: int
    rows: list[ForceRow]


class ValidationOut(_Out):
    id: str
    esl_run_id: str
    case_id: str
    job_id: str
    disp_rms_rel: float | None = None
    reaction_rel: float | None = None
    hotspots: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    verdict: str
    fail_reasons: list[str]
    criteria: dict[str, Any]
    field: dict[str, Any] | None = None
    dir_rel: str
    created_at: datetime
    stale: bool


class ArtifactOut(_Out):
    id: str
    case_id: str
    job_id: str | None = None
    kind: str
    rel: str
    size: int
    path: str
    downloadable: bool
    created_at: datetime


class ConfigIssue(_Out):
    key: str
    message: str


class ConfigStatus(_Out):
    ok: bool
    errors: list[ConfigIssue]


class WorkerStatus(_Out):
    online: bool
    last_seen_at: datetime | None = None
    limiter: str | None = None


class ToolsStatus(_Out):
    solver_backend: str
    solver_backends_available: list[str]


class StatusOut(_Out):
    config: ConfigStatus
    worker: WorkerStatus
    tools: ToolsStatus
    version: str
    core_version: str


# ---------------------------------------------------------------- P2: 전 요소 비교(계약 esl_p2_library.md §7.3·§11)
class FieldPlane(_Out):
    origin: list[float]
    e1: list[float]
    e2: list[float]


class ColorRange(_Out):
    min: float | None = None
    max: float | None = None


class FieldOut(_Out):
    """points 행 = [elem_id, a, b, value(null = 값 없음), reason(OK|HOLD|LOW|EXCLUDED|NO_PREV)]."""

    validation_id: str
    layer: Literal["rad", "esl", "err"]
    n_total: int
    n_returned: int
    decimated: bool
    cell: list[float] | None = None
    plane: FieldPlane
    color_range: ColorRange
    points: list[list[int | float | str | None]]


class SectionOut(_Out):
    validation_id: str
    axis: Literal["xi", "eta"]
    at: float
    band: float
    n_elems: int
    s: list[float]
    w_rad: list[float]
    w_esl: list[float]
    w0: list[float]


# ---------------------------------------------------------------- P2: 라이브러리
class EntryModel(_Out):
    name: str | None = None
    inch: int | None = None
    version: str | None = None
    date: str | None = None
    project: str | None = None
    product_mass: float | None = None
    part_mass: float | None = None
    part_id: int | None = None
    part_title: str | None = None
    units_label: str | None = None
    n_nodes: int | None = None
    n_elems: int | None = None


class EntryScene(_Out):
    project: str | None = None
    scenario: str | None = None
    seq: int | None = None
    drop_type: str | None = None
    drop_class: str | None = None
    round: str | None = None
    scene_no: int | None = None
    orient: str | None = None
    suffix: str | None = None
    variant: str | None = None
    faces: list[int] | None = None
    raw: str | None = None
    warnings: list[str] = Field(default_factory=list)


class EntryQuality(_Out):
    verdict: str | None = None
    fail_reasons: list[str] = Field(default_factory=list)
    field_max_err_pct: float | None = None
    field_p90_err_pct: float | None = None
    hotspot1_rel_err: float | None = None
    disp_rms_rel: float | None = None
    reaction_rel: float | None = None
    noise: dict[str, Any] | None = None
    confirmed_fail: dict[str, Any] | None = None


class EntryOut(_Out):
    id: str
    project_id: str
    case_id: str
    case_title: str | None = None
    esl_run_id: str
    validation_id: str | None = None
    status: Literal["ACTIVE", "RETIRED"]
    model: EntryModel
    scene: EntryScene
    quality: EntryQuality
    tstar: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    dir_rel: str
    summary_rel: str
    sha256: str
    warnings: list[str]
    note: str | None = None
    force_reason: str | None = None
    registered_by: str
    registered_by_name: str
    registered_at: datetime
    retired_by_id: str | None = None
    retired_at: datetime | None = None
    retire_reason: str | None = None
    updated_at: datetime
    version: int


class EntryCreate(_Req):
    esl_run_id: str = Field(min_length=1, max_length=64)
    validation_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=2000)
    force_reason: str | None = Field(default=None, min_length=1, max_length=2000)


class EntryRetire(_Req):
    reason: str | None = Field(default=None, max_length=2000)


class EntryModelPatch(_Req):
    name: str | None = Field(default=None, max_length=200)
    inch: int | None = Field(default=None, ge=1, le=1000)
    version: str | None = Field(default=None, max_length=64)
    date: str | None = Field(default=None, max_length=32)
    product_mass: float | None = Field(default=None, gt=0)


class EntryScenePatch(_Req):
    project: str | None = Field(default=None, max_length=200)
    scenario: str | None = Field(default=None, max_length=200)
    seq: int | None = Field(default=None, ge=0)
    drop_type: Literal["Corner", "Edge", "Face"] | None = None
    round: str | None = Field(default=None, max_length=32)
    scene_no: int | None = Field(default=None, ge=0)
    orient: str | None = Field(default=None, pattern=r"^[1-6]{1,3}$")
    suffix: str | None = Field(default=None, max_length=32)
    variant: str | None = Field(default=None, max_length=64)


class EntryPatch(_Req):
    version: int = Field(ge=1)
    model: EntryModelPatch | None = None
    scene: EntryScenePatch | None = None
    note: str | None = Field(default=None, max_length=2000)


class AnalysisFilters(_Req):
    model: list[str] | None = None
    inch: list[int] | None = None
    drop_type: list[str] | None = None
    drop_class: list[str] | None = None
    orient: list[str] | None = None
    scenario: list[str] | None = None
    verdict: list[str] | None = None
    entry_ids: list[str] | None = None


class AnalysisOptions(_Req):
    normalization: Literal["none", "mass", "inch2"] | None = None
    n_representative: int | None = Field(default=None, ge=1, le=50)
    objective: Literal["minmax", "weighted"] | None = None
    worst_case: bool | None = None
    svd_energy: float | None = Field(default=None, gt=0, le=1)
    target_mass: float | None = Field(default=None, gt=0)
    target_inch: float | None = Field(default=None, gt=0)
    # §12.1 최적화 하중(덱 subcase) 구성: 없으면 설정 optdeck.cases(기본 all = 모든 씬)
    optdeck_cases: Literal["all", "representative", "representative+worst"] | None = None


class AnalysisCreate(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=200)
    target_entry_id: str | None = Field(default=None, max_length=64)
    filters: AnalysisFilters = Field(default_factory=AnalysisFilters)
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)


class AnalysisOut(_Out):
    id: str
    project_id: str
    title: str | None = None
    target_entry_id: str | None = None
    filters: dict[str, Any]
    options: dict[str, Any]
    entry_ids: list[str]
    n_entries: int
    status: str
    job_id: str | None = None
    job: JobOut | None = None
    result: dict[str, Any] | None = None
    result_rel: str | None = None
    report_rel: str | None = None
    optdeck_rel: str | None = None
    dir_rel: str
    folder_path: str
    created_by: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime


class ComparisonFilters(_Req):
    inch: list[int] | None = None
    drop_type: list[str] | None = None
    drop_class: list[str] | None = None
    orient: list[str] | None = None
    scenario: list[str] | None = None
    verdict: list[str] | None = None


class ComparisonOptions(_Req):
    cos_min: float | None = Field(default=None, gt=0, le=1)
    n_representative: int | None = Field(default=None, ge=1, le=50)


class ComparisonCreate(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    new_version: str = Field(min_length=1, max_length=64)
    base_version: str | None = Field(default=None, min_length=1, max_length=64)   # 없으면 비교 버전 직전
    title: str | None = Field(default=None, max_length=200)
    filters: ComparisonFilters = Field(default_factory=ComparisonFilters)
    options: ComparisonOptions = Field(default_factory=ComparisonOptions)


class ComparisonOut(_Out):
    id: str
    project_id: str
    title: str | None = None
    model: str
    base_version: str
    new_version: str
    filters: dict[str, Any]
    options: dict[str, Any]
    base_entry_ids: list[str]
    new_entry_ids: list[str]
    n_paired: int
    status: str
    verdict: Literal["CONVERGED", "ITERATE"] | None = None
    job_id: str | None = None
    job: JobOut | None = None
    result: dict[str, Any] | None = None
    result_rel: str | None = None
    report_rel: str | None = None
    dir_rel: str
    folder_path: str
    created_by: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime


class AnalysisFileOut(_Out):
    rel: str
    kind: Literal["report", "optdeck", "analysis", "log", "other"]
    size: int
    path: str
    downloadable: bool


# ---------------------------------------------------------------- P3-UX: 업로드·찾아보기·버전(계약 esl_p3_ux.md §1~§3)
class UploadFileIn(_Req):
    rel: str = Field(min_length=1, max_length=400, description="rad/… | results/… | h3d/… ('/' 구분 상대경로)")
    size: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class UploadCreate(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    files: list[UploadFileIn] = Field(min_length=1)


class UploadFilesAdd(_Req):
    files: list[UploadFileIn] = Field(min_length=1)


class UploadFileOut(_Out):
    index: int
    rel: str
    size: int
    received: int
    done: bool
    sha256: str | None = None
    sha256_expected: str | None = None


class UploadCheckOut(_Out):
    ok: bool
    rad_path: str | None = None
    results_dir: str | None = None
    h3d_path: str | None = None
    parts: list[dict[str, Any]] = []
    missing_includes: list[str] = []
    problems: list[str] = []


class UploadOut(_Out):
    upload_id: str
    project_id: str
    name: str
    state: Literal["OPEN", "COMPLETED", "CANCELED", "STALE"]
    dir_path: str
    chunk_size: int
    total_bytes: int
    received_bytes: int
    files: list[UploadFileOut]
    result: UploadCheckOut | None = None
    backup_path: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class UploadChunkOut(_Out):
    index: int
    received: int
    done: bool
    sha256: str | None = None


class UploadCompleteOut(UploadCheckOut):
    upload_id: str
    state: Literal["OPEN", "COMPLETED"]


class BrowseRoot(_Out):
    index: int
    label: str
    path: str
    kind: Literal["input", "upload", "spdm"]
    writable: bool


class BrowseEntry(_Out):
    name: str
    type: Literal["dir", "file"]
    size: int | None = None
    mtime: float
    hint: Literal["rad", "results", "h3d"] | None = None


class BrowseOut(_Out):
    roots: list[BrowseRoot]
    root: int | None = None
    path: str
    parent: str | None = None
    abs_path: str | None = None
    hint: Literal["results"] | None = None
    entries: list[BrowseEntry]
    total: int
    offset: int
    limit: int
    truncated: bool


class VersionOut(_Out):
    version: str
    commit: str | None = None
    built_at: str | None = None


class ChangelogEntry(_Out):
    version: str
    date: str | None = None
    sections: dict[str, list[str]]


# ---------------------------------------------------------------- P3-UX §9.1: PC 연결 코드·토큰
class ClientCodeCreate(_Req):
    project_id: str = Field(min_length=1, max_length=64)


class ClientCodeOut(_Out):
    code: str
    project_id: str
    expires_at: datetime


class ClientExchange(_Req):
    code: str = Field(min_length=1, max_length=32)
    device_name: str = Field(min_length=1, max_length=100)


class ClientUser(_Out):
    user_id: str
    username: str
    display_name: str


class ClientProject(_Out):
    id: str
    name: str | None = None


class ClientExchangeOut(_Out):
    token: str
    token_id: str
    user: ClientUser
    project: ClientProject
    expires_at: datetime


class ClientTokenOut(_Out):
    id: str
    token_prefix: str
    project_id: str
    project_name: str | None = None
    device_name: str
    user_id: str
    username: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    state: Literal["ACTIVE", "EXPIRED", "REVOKED"]


# ---------------------------------------------------------------- P3-이력(계약 esl_p3_history.md §3)
class HistoryRef(_Out):
    kind: Literal["extract", "esl_run", "validation", "export", "report", "analysis", "comparison"]
    id: str


class HistoryItem(_Out):
    id: str
    job_type: str
    stage: int
    state: str
    case_id: str | None = None
    case_title: str | None = None
    case_folder: str | None = None
    analysis_id: str | None = None
    comparison_id: str | None = None
    subject_title: str | None = None
    created_by: str
    created_by_name: str
    created_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: float | None = None
    wait_s: float | None = None
    current_step_no: int | None = None
    progress_pct: float | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    retry_of_job_id: str | None = None
    retried_by_job_id: str | None = None
    result_ref: HistoryRef | None = None
    result_state: Literal["current", "past"] | None = None
    stale: bool = False
    summary: dict[str, Any] | None = None


class HistoryPage(_Out):
    items: list[HistoryItem]
    next_cursor: str | None = None
    has_more: bool


class ReviewStepOut(StepOut):
    command: list[str] | None = None        # 전역 관리자에게만 키가 나온다(그 외 응답에는 키 자체가 없음)


class ReviewJobOut(JobOut):
    steps: list[ReviewStepOut] | None = None


class ReviewStepTiming(_Out):
    step_no: int
    step_key: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: float | None = None


class ReviewTiming(_Out):
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    wait_s: float | None = None
    duration_s: float | None = None
    steps: list[ReviewStepTiming]


class ReviewFingerprint(_Out):
    kind: str
    path: str | None = None
    size: int | None = None
    mtime: float | None = None


class ReviewInput(_Out):
    params: dict[str, Any]
    settings_summary: dict[str, Any]
    input_fingerprint: list[ReviewFingerprint] | None = None


class ReviewFailedStep(_Out):
    step_no: int
    step_key: str
    exit_code: int | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class ReviewError(_Out):
    failure_code: str | None = None
    failure_message: str | None = None
    failed_step: ReviewFailedStep | None = None
    warnings: list[Any]


class ReviewLog(_Out):
    step_no: int
    step_key: str
    state: str
    has_log: bool
    size: int


class DiffRow(_Out):
    key: str
    label: str
    past: Any = None
    current: Any = None


class ReviewResult(_Out):
    ref: HistoryRef | None = None
    availability: Literal["full", "summary", "none"]
    state: Literal["current", "past"] | None = None
    stale_reasons: list[str]
    files_note: str | None = None
    past: dict[str, Any]
    diff: list[DiffRow]
    links: dict[str, Any]


class ReviewOut(_Out):
    job: ReviewJobOut
    timing: ReviewTiming
    input: ReviewInput
    error: ReviewError
    logs: list[ReviewLog]
    result: ReviewResult


class HistoryFileOut(_Out):
    name: str
    size: int
    downloadable: bool
