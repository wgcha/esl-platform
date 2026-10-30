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
    reason: dict[str, Any] | None = None     # v0.10.0 step_status: {code, message} (예 SUPPORT_AUTO_BLOCKED)


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
    input_h3d_meta: dict[str, Any] | None = None
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
    stage_status: dict[str, StageState] | None = None   # deprecated(v0.10.0): 옛 1..6 단계 — 화면은 step_status
    # v0.10.0(esl_menu_restructure.md §5.4): 화면 4단계 {input, tstar, esl, validate}
    step_status: dict[str, StageState] | None = None


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
    opt_run_id: str | None = None
    upload_id: str | None = Field(default=None, description="v0.11.0 SCX_FETCH 대상 업로드 세션")
    project_id: str
    job_type: str
    stage: int
    lane: str = Field(description="SLOT | LIGHT | XFER(v0.11.0 — HTTP 전송·원격 대기)")
    state: str
    queue_position: int | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_step_no: int | None = None
    progress_pct: float | None = None
    progress_label: str | None = Field(default=None, description="진행 라벨(예: 'h3d 12.3 / 30.0 GB', '대시보드가 SCX에서 받는 중')")
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
    xfer: "QueueXfer | None" = None         # v0.11.0 XFER 레인(SCX 전송·원격 대기)


class QueueXfer(_Out):
    running_all: list[JobOut] = []
    queued: list[JobOut] = []
    lanes: int = 2


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
    plane: dict[str, Any] | None = None
    corners: list[int]
    # v0.10.0(esl_menu_restructure.md §5.1·§5.2): 자동 선택 품질 검사 결과
    status: Literal["OK", "BLOCKED"] = "OK"
    mode: str | None = None
    checks: dict[str, float] | None = None
    problems: list[dict[str, Any]] = Field(default_factory=list)
    rule_version: int | None = None


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


class View3dTopRow(_Out):
    rank: int
    node_id: int
    vertex: int
    x: float
    y: float
    z: float
    fx: float
    fy: float
    fz: float
    mag: float
    fn: float                         # 면외 하중 Fn = F·n_i (N, 부호 있음 — 툴팁·표)
    pa: float                          # 면압 |Fn|/A_i (MPa) — 표면 색 값
    is_support: bool


class View3dClusterRow(_Out):
    label: str
    n_nodes: int
    center: list[float]
    u_center: list[float]
    r: list[float]
    r_mag: float
    sum_abs: float
    cancel: float
    m: list[float]
    m_mag: float
    min_node_id: int


class View3dClusterSet(_Out):
    k_actual: int
    rows: list[View3dClusterRow]


class View3dFile(_Out):
    name: str
    bytes: int


class View3dLod(View3dFile):
    n_vertices: int


class View3dValuesArray(_Out):
    key: Literal["pa", "fn", "fmag", "u"]
    dtype: Literal["int16", "uint16"]
    comps: int
    offset: int
    scale: float | list[float]


class View3dValues(View3dFile):
    arrays: list[View3dValuesArray]


class View3dBBox(_Out):
    min: list[float]
    max: list[float]
    diag: float


class View3dRange(_Out):
    max: float
    p99: float | None = None


class View3dRanges(_Out):
    pa: View3dRange
    fn_abs: View3dRange
    fmag_max: float
    u_max: float


class View3dSupport(_Out):
    node_id: int
    vertex: int
    dof: str
    x0: list[float]


class View3dOut(_Out):
    """④ 3D 하중 보기 manifest(계약 esl_3d_load.md §3.6·§4). 파일 URL 은 API 루트 기준 경로."""

    schema_: str = Field(alias="schema")
    builder_version: int
    key: str
    esl_run_id: str
    n_nodes: int
    n_elems: int
    n_tris: int
    units: str
    force_unit: str
    pressure_unit: str
    up: str
    bbox: View3dBBox
    plate_normal: list[float]
    geometry: View3dFile
    lod: View3dLod | None = None
    values: View3dValues
    ranges: View3dRanges
    sum_f: list[float]
    sum_m: list[float]
    moment_center: list[float]
    supports: list[View3dSupport]
    top: list[View3dTopRow]
    clusters: dict[str, View3dClusterSet]
    created_at: str
    geometry_url: str
    lod_url: str | None = None
    values_url: str

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ValidationOut(_Out):
    id: str
    esl_run_id: str
    case_id: str
    job_id: str
    disp_rms_rel: float | None = None
    reaction_rel: float | None = None
    hotspots: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    verdict: Literal["PASS", "FAIL", "UNDETERMINED"]
    fail_reasons: list[str]
    criteria: dict[str, Any]
    field: dict[str, Any] | None = None
    dir_rel: str
    created_at: datetime
    stale: bool
    # 0.5.7(계약 esl_disp_primary.md §7): 변위 주지표 판정. scheme null = 이전 판정 체계(status LEGACY)
    scheme: str | None = None
    status: Literal["PASS", "FAIL", "UNDETERMINED", "LEGACY"] = "LEGACY"
    disp_max_rel: float | None = None
    disp_noise_rel: float | None = None
    undetermined_reason: str | None = None
    disp: dict[str, Any] | None = None
    strain_ref: dict[str, Any] | None = None


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


class ColorRangeRobust(_Out):
    """견고한 자동 범위(계약 esl_disp_primary.md §14.2): P99 를 유효숫자 2자리로 올림. raw = 올림 전 분위값."""

    min: float | None = None
    max: float | None = None
    basis: str = "p99"
    raw: float | None = None


class FieldOut(_Out):
    """points 행 = [elem_id, a, b, value(null = 값 없음), reason(OK|HOLD|LOW|EXCLUDED|NO_PREV), flags].
    flags = 비트(1 = 기준 초과 요소, 2 = 소성 영역 epsp>0), 예전 검증 산출물은 0."""

    validation_id: str
    layer: Literal["rad", "esl", "err"]
    n_total: int
    n_returned: int
    decimated: bool
    cell: list[float] | None = None
    plane: FieldPlane
    color_range: ColorRange
    color_range_robust: ColorRangeRobust | None = None
    points: list[list[int | float | str | None]]


class DispFieldOut(_Out):
    """변위 전 노드 분석 2D 점(계약 esl_disp_primary.md §7). points 행 = [node_id, a, b, value, is_support].
    layer: err = e/U, rel = ‖d_rel‖, val = ‖d_val‖. 다운샘플 셀 대표 = e 최대 노드."""

    validation_id: str
    layer: Literal["err", "rel", "val"]
    n_total: int
    n_returned: int
    decimated: bool
    cell: list[float] | None = None
    plane: FieldPlane
    color_range: ColorRange
    color_range_robust: ColorRangeRobust | None = None
    U: float
    points: list[list[int | float | None]]


class SectionStats(_Out):
    dw_max_abs: float | None = None
    s_at_dw_max: float | None = None
    dw_rms: float | None = None
    U: float | None = None
    dw_max_rel: float | None = None
    dw_rms_rel: float | None = None
    w_max_abs: float | None = None


class SectionLine(_Out):
    """지도에 그릴 단면 중심선(PCA 평면 실좌표, 대상 파트 범위 양 끝) + 띠 실좌표 반폭 band_abs."""

    a0: float
    b0: float
    a1: float
    b1: float
    band_abs: float
    xi_range: list[float]
    eta_range: list[float]


class SectionSuggest(_Out):
    key: Literal["max_disp_err", "hotspot1"]
    label: str
    xi: float
    eta: float
    id: int


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
    # 0.5.7(계약 §15.2)
    dw: list[float] = Field(default_factory=list)
    stats: SectionStats = Field(default_factory=SectionStats)
    has_val: bool = False
    line: SectionLine | None = None
    units: str | None = None
    suggest: list[SectionSuggest] = Field(default_factory=list)


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
    status: str | None = None          # PASS|FAIL|UNDETERMINED|LEGACY (0.5.7 이전 등록은 없음 → LEGACY 로 취급)
    scheme: str | None = None
    disp_max_rel: float | None = None
    disp_noise_rel: float | None = None
    strain_exceed_frac: float | None = None
    undetermined_reason: str | None = None
    fail_reasons: list[str] = Field(default_factory=list)
    field_max_err_pct: float | None = None
    field_p90_err_pct: float | None = None
    hotspot1_rel_err: float | None = None
    disp_rms_rel: float | None = None
    reaction_rel: float | None = None
    noise: dict[str, Any] | None = None
    confirmed_fail: dict[str, Any] | None = None
    confirmed_undetermined: dict[str, Any] | None = None
    revalidated: dict[str, Any] | None = None   # v0.10.0 재검증 전환 기록 {from_validation_id, from_status, job_id, at, by, by_name}


class EntrySize(_Out):
    inch: int | None = None
    L_xi: float | None = None
    L_eta: float | None = None


class DeformModeOut(_Out):
    auto: Literal["dent", "twist", "bend"] | None = None
    user: Literal["dent", "twist", "bend"] | None = None
    effective: Literal["dent", "twist", "bend"] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    user_by: str | None = None
    user_at: str | None = None
    rule_version: int | None = None


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
    # v0.7.0(esl_opt_run.md §5.1): 크기·S1 모델 키·변형 모드(지연 백필)
    size: EntrySize | None = None
    topo_sha256: str | None = None
    deform_mode: DeformModeOut | None = None
    # v0.10.0(esl_menu_restructure.md §7.4): 적격(현재 기준 PASS) 여부·재검증 가능 여부·진행 중 재검증 작업
    eligible: bool = False
    ineligible_reason: Literal["LEGACY", "FAIL", "UNDETERMINED"] | None = None
    revalidate_block: dict[str, Any] | None = None
    revalidate_job: dict[str, Any] | None = None


class EntryCreate(_Req):
    esl_run_id: str = Field(min_length=1, max_length=64)
    validation_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=2000)
    force_reason: str | None = Field(default=None, min_length=1, max_length=2000)   # v0.10.0: 무시(구 클라이언트 호환)


# ---------------------------------------------------------------- v0.10.0 라이브러리 다중 내보내기(§6.1)
class ExportOptions(_Req):
    id_offset: Literal["auto"] | int = "auto"
    id_policy: Literal["per_model_sequential", "independent"] = "per_model_sequential"

    @field_validator("id_offset")
    @classmethod
    def _off(cls, v):
        if not isinstance(v, str) and (isinstance(v, bool) or v < 0 or v > 2_147_483_646):
            raise ValueError("id_offset 은 'auto' 또는 0 이상 정수")
        return v


class ExportBatchCreate(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    entry_ids: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    options: ExportOptions = Field(default_factory=ExportOptions)


class ExportBatchJob(_Out):
    job_id: str
    case_id: str | None = None
    state: str
    progress_pct: float | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class ExportBatchFile(_Out):
    rel: str
    size: int


class ExportBatchItem(_Out):
    entry_id: str
    label: str
    case_id: str | None = None
    legacy: bool = False
    state: Literal["PENDING", "DONE", "FAILED"]
    files: list[ExportBatchFile] = Field(default_factory=list)
    id_range: list[int] | None = None
    warnings: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class ExportBundleInfo(_Out):
    ready: bool
    bytes: int | None = None


class ExportBatchOut(_Out):
    batch_id: str
    project_id: str
    created_by: str
    created_by_name: str | None = None
    created_at: datetime | str | None = None
    targets: list[str]
    options: dict[str, Any]
    state: Literal["QUEUED", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED", "CANCELED"]
    jobs: list[ExportBatchJob]
    items: list[ExportBatchItem]
    bundle: ExportBundleInfo


class ExportBatchSummary(_Out):
    batch_id: str
    project_id: str
    created_by: str
    created_by_name: str | None = None
    created_at: datetime | None = None
    targets: list[str] = Field(default_factory=list)
    n_items: int
    state: Literal["QUEUED", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED", "CANCELED"]
    job_ids: list[str] = Field(default_factory=list)


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
    # v0.7.0: 변형 모드 사용자 수정(null = 자동으로 되돌림). 키가 없으면 변경 없음
    deform_mode: Literal["dent", "twist", "bend"] | None = None


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
    excluded_ineligible: int | None = None   # v0.10.0: 필터 분석에서 뺀 부적격(LEGACY·FAIL·판정 불가) 항목 수(생성 응답만)


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
class UploadResultKind(_Req):
    type: str = Field(min_length=1, max_length=64)
    layer: str | None = Field(default=None, max_length=32)


class UploadMeta(_Req):
    """h3d 업로드 메타(계약 esl_upload_speed.md §4.6) — `.h3d` 파일에만, JSON ≤ 16 KB. 서버는 표시·검사용으로만 신뢰."""
    kind: Literal["h3d_slim", "h3d_original"]
    v: int = Field(default=1, ge=1, le=1)
    source_name: str | None = Field(default=None, max_length=255)
    source_bytes: int | None = Field(default=None, ge=0)
    source_mtime: str | None = Field(default=None, max_length=40)
    slim_bytes: int | None = Field(default=None, ge=0)
    hvtrans_sec: float | None = Field(default=None, ge=0)
    hvtrans_version: str | None = Field(default=None, max_length=64)
    cfg: str | None = Field(default=None, max_length=8192)
    cfg_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    part_id: int | None = Field(default=None, ge=0)
    part_title: str | None = Field(default=None, max_length=200)
    results: list[UploadResultKind] | None = Field(default=None, max_length=8)
    frames: Literal["all"] | None = None
    tool_version: str | None = Field(default=None, max_length=32)


class UploadClient(_Req):
    name: str = Field(max_length=32)
    version: str = Field(max_length=32)


class UploadFileIn(_Req):
    rel: str = Field(min_length=1, max_length=400, description="rad/… | results/… | h3d/… ('/' 구분 상대경로)")
    size: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    meta: UploadMeta | None = None


class UploadCreate(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    files: list[UploadFileIn] = Field(min_length=1)
    client: UploadClient | None = None


class UploadFilesAdd(_Req):
    files: list[UploadFileIn] = Field(min_length=1)


class UploadFileOut(_Out):
    index: int
    rel: str
    source: Literal["browser", "scx"] = Field(default="browser", description="v0.11.0 scx = SCX 드라이브에서 워커가 받은 파일(PUT 409)")
    drive_rel: str | None = Field(default=None, description="v0.11.0 source scx: SCX 드라이브 경로(루트 기준)")
    size: int
    received: int = Field(description="앞에서부터 연속으로 받은 바이트(구 클라이언트 이어 올리기 offset)")
    received_total: int = 0
    chunks: list[list[int]] = Field(default=[], description="받은 청크 번호 범위 [[a,b),…]")
    n_chunks: int = 0
    removed: bool = False
    meta: dict[str, Any] | None = None
    done: bool
    sha256: str | None = None
    sha256_expected: str | None = None


class UploadCheckOut(_Out):
    ok: bool
    rad_path: str | None = None
    results_dir: str | None = None
    h3d_path: str | None = None
    h3d_meta: dict[str, Any] | None = None
    parts: list[dict[str, Any]] = []
    missing_includes: list[str] = []
    problems: list[str] = []
    state_includes: list[dict[str, Any]] = Field(
        default=[], description="v0.8.0 누적 씬: rad include 중 이전 런 상태 파일(.sta/.str 또는 #RADIOSS STATE FILE) "
                                "{rel, spec, kinds[geometry|initial], found}")
    scx: dict[str, Any] | None = Field(
        default=None, description="v0.11.0 SCX 드라이브에서 받은 세션: {root, rad_rel, h3d_rel, missing_specs[{spec, src, reason}]}"
                                  " (rel 은 루트 기준)")


class UploadClientOut(_Out):
    """업로드를 시작한 클라이언트(POST /uploads client) — esl-pc = PC 도구, esl-web = 브라우저. 없으면 null(구 세션·미지정)."""
    name: str
    version: str


class UploadOut(_Out):
    upload_id: str
    project_id: str
    name: str
    state: Literal["OPEN", "COMPLETED", "CANCELED", "STALE"]
    dir_path: str
    protocol: Literal[1, 2] = 2
    chunk_size: int
    max_parallel: int = 1
    total_bytes: int
    received_bytes: int
    problems_count: int = 0
    client: UploadClientOut | None = None
    files: list[UploadFileOut]
    result: UploadCheckOut | None = None
    backup_path: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class UploadChunkOut(_Out):
    index: int
    received: int
    received_total: int | None = None
    chunk: int | None = None
    duplicate: bool = False
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
    ui: dict[str, Any] = {}


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
    kind: Literal["extract", "esl_run", "validation", "export", "report", "analysis", "comparison", "opt_run"]
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
    opt_run_id: str | None = None
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


# ---------------------------------------------------------------- v0.7.0 비드 최적화(계약 esl_opt_run.md §5)
# 사각형·비드 치수 값 범위는 서비스가 검사한다(KEEPOUT_INVALID·INVALID_PARAMS — 계약 §5.3 오류 코드를 쓰기 위해 스키마는 느슨하게).
class RectIn(_Req):
    name: str | None = Field(default=None, max_length=200)
    corner: str = Field(min_length=1, max_length=8)        # a0b0 | a1b0 | a0b1 | a1b1
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float


class KeepoutAuto(_Req):
    hole: bool = True
    edge: bool = True


class KeepoutIn(_Req):
    rects: list[RectIn] = Field(default_factory=list, max_length=1000)
    auto: KeepoutAuto = Field(default_factory=KeepoutAuto)


class KeepoutSetIn(KeepoutIn):
    template_id: str | None = Field(default=None, max_length=64)
    topo_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    version: int | None = Field(default=None, ge=1)         # 갱신 시 필수(낙관적 잠금)

    @model_validator(mode="after")
    def _key(self) -> "KeepoutSetIn":
        if (self.template_id is None) == (self.topo_sha256 is None):
            raise ValueError("template_id 와 topo_sha256 중 정확히 하나가 필요합니다")
        return self


class TemplateCheckIn(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    upload_id: str = Field(min_length=1, max_length=64)
    part_title: str | None = Field(default=None, min_length=1, max_length=200)


class TemplateIn(TemplateCheckIn):
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    title: str = Field(min_length=1, max_length=200)
    inch: int | None = Field(default=None, ge=1, le=1000)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("제목이 비었습니다")
        return v.strip()


class S1CheckIn(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    entry_ids: list[str] = Field(min_length=1, max_length=10000)


class BeadIn(_Req):
    angle: float
    min_width: float
    height: float


class OptDesignIn(_Req):
    nondesign_pids: list[int] | None = Field(default=None, max_length=10000)
    bead: BeadIn | None = None
    keepout: KeepoutIn = Field(default_factory=KeepoutIn)


class SupportIn(_Req):
    node_id: int
    dof: str = Field(pattern=r"^[1-6]{1,6}$")


class OptOptionsIn(_Req):
    supports: list[SupportIn] | None = Field(default=None, min_length=3, max_length=3)    # S2 만
    objective_norm: Literal["abs", "rel"] | None = None
    load_strategy: Literal["A", "B", "C"] | None = None
    k: int | None = None                                                                 # C 만, 1..max_cases


class OptRunIn(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    scenario: Literal["S1", "S2"]
    title: str | None = Field(default=None, max_length=200)
    entry_ids: list[str] = Field(min_length=1, max_length=10000)
    analysis_id: str | None = Field(default=None, max_length=64)
    template_id: str | None = Field(default=None, max_length=64)
    design: OptDesignIn = Field(default_factory=OptDesignIn)
    options: OptOptionsIn = Field(default_factory=OptOptionsIn)


class OptSizeSettings(_Out):
    tol_rel: float
    plate_tol_rel: float
    require_inch: bool


class OptBeadSettings(_Out):
    angle: float
    min_width: float
    height: float


class OptKeepoutAutoSettings(_Out):
    hole_radius_mm: float
    edge_band_mm: float


class OptLoadsSettings(_Out):
    default_objective_norm: Literal["abs", "rel"]
    default_strategy: Literal["A", "B", "C"]
    mac_merge: float
    max_cases: int
    default_k: int


class OptSettingsOut(_Out):
    enabled: bool
    solver_ready: bool
    solver_reason: str | None = None
    size: OptSizeSettings
    bead_defaults: OptBeadSettings
    keepout_auto: OptKeepoutAutoSettings
    loads: OptLoadsSettings
    method_sources: dict[str, Any]
    max_rects: int
    max_entries: int
    template_max_elems: int
    template_ext: list[str]
    max_preview_points: int


class MeshPid(_Out):
    pid: int
    title: str | None = None
    n_elems: int
    thickness: float | None = None
    E: float | None = None
    nu: float | None = None


class MeshCheckOut(_Out):
    upload_id: str
    ok: bool
    sha256: str
    format: Literal["rad", "fem"] | None = None
    file_name: str
    parts: list[dict[str, Any]] = Field(default_factory=list)
    part_title: str | None = None
    mesh: dict[str, Any]
    pids: list[MeshPid] = Field(default_factory=list)
    frame: dict[str, Any]
    quality: dict[str, Any]
    supports_auto: list[dict[str, Any]] = Field(default_factory=list)


class TemplateOut(_Out):
    id: str
    title: str
    inch: int | None = None
    description: str
    format: Literal["rad", "fem"]
    file_name: str
    part_title: str | None = None
    sha256: str
    n_nodes: int
    n_elems: int
    L_xi: float
    L_eta: float
    z_range: list[float]
    pids: list[MeshPid]
    quality_warnings: list[dict[str, Any]] = Field(default_factory=list)
    supports_auto: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["ACTIVE", "ARCHIVED"]
    n_runs: int
    created_by: str
    created_by_name: str
    created_at: datetime
    archived_at: datetime | None = None
    can_delete: bool


class TemplateDeleteOut(_Out):
    deleted: bool
    archived: bool


class S1Base(_Out):
    entry_id: str
    case_id: str
    case_title: str | None = None
    part_title: str | None = None
    rad_file_name: str | None = None
    n_nodes: int | None = None
    n_elems: int | None = None
    topo_sha256: str | None = None
    pids: list[MeshPid] = Field(default_factory=list)
    supports: list[dict[str, Any]] = Field(default_factory=list)


class S1EntryRow(_Out):
    entry_id: str
    same_model: bool
    reason: str | None = None


class S1CheckOut(_Out):
    base: S1Base
    entries: list[S1EntryRow]
    warnings: list[dict[str, Any]] = Field(default=[], description="정보 경고 {code, message} — v0.8.0 S1_BASE_CUMULATIVE")


class PlanViewFrame(_Out):
    a_range: list[float]
    b_range: list[float]


class PlanViewElems(_Out):
    n_total: int
    decimated: bool
    points: list[list[float]]


class PlanViewAuto(_Out):
    hole_radius_mm: float
    edge_band_mm: float
    polygons: list[list[list[float]]]
    kinds: list[Literal["hole", "edge"]] = Field(default_factory=list)   # polygons 와 같은 길이(구멍/가장자리)
    counts: dict[str, int] = Field(default_factory=dict)


class PlanViewOut(_Out):
    key: dict[str, str | None]
    frame: PlanViewFrame
    outline: list[list[float]]
    holes: list[list[list[float]]]
    elems: PlanViewElems
    auto_keepout: PlanViewAuto
    warnings: list[str] = Field(default_factory=list)


class KeepoutRectOut(_Out):
    name: str
    corner: Literal["a0b0", "a1b0", "a0b1", "a1b1"]
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float


class KeepoutSetOut(_Out):
    id: str
    key: dict[str, str | None]
    version: int
    rects: list[KeepoutRectOut]
    auto: dict[str, bool]
    frame: dict[str, Any]
    updated_by_name: str
    updated_at: datetime
    warnings: list[str] = Field(default_factory=list)


class OptRunOut(_Out):
    id: str
    project_id: str
    scenario: Literal["S1", "S2"]
    title: str | None = None
    entry_ids: list[str]
    analysis_id: str | None = None
    base: dict[str, Any] | None = None
    template_id: str | None = None
    template: dict[str, Any] | None = None
    size: dict[str, Any] | None = None
    design: dict[str, Any]
    options: dict[str, Any]
    load_strategy: Literal["A", "B", "C"]
    k: int | None = None
    objective_norm: Literal["abs", "rel"]
    job_id: str | None = None
    job: JobOut | None = None
    state: str
    result: dict[str, Any] | None = None
    report_ready: bool
    dir_rel: str
    folder_path: str
    created_by: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime


class OptFileOut(_Out):
    rel: str
    kind: Literal["report", "result", "selection", "deck", "solve", "target", "log", "other"]
    size: int
    downloadable: bool


# ---------------------------------------------------------------- v0.9.0 비드 형상 DOE(계약 esl_bead_doe.md §10.2)
# 이름 = 프런트 types.ts 인터페이스 이름(check:api 대조). 중첩 인라인 객체는 dict(프런트 인라인 타입과 키 대조 생략).
DoeScenarioLit = Literal["same", "mesh", "step"]
DoePhaseLit = Literal["PREP", "READY", "PREVIEW", "PREVIEW_READY", "RUN", "DONE", "FAILED"]


class DoeProps(_Req):
    t: float = Field(gt=0)
    E: float = Field(gt=0)
    nu: float = Field(ge=0, lt=0.5)


class DoeCheckIn(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    scenario: DoeScenarioLit
    entry_ids: list[str] = Field(min_length=1, max_length=10000)
    step_upload_id: str = Field(min_length=1, max_length=64)
    mesh_upload_id: str | None = Field(default=None, min_length=1, max_length=64)    # ② 만
    part_title: str | None = Field(default=None, min_length=1, max_length=200)     # ② 만(기본 bead_doe.part_title)
    inch: int | None = Field(default=None, ge=1, le=1000)


class DoeStudyIn(DoeCheckIn):
    title: str | None = Field(default=None, max_length=200)
    props: DoeProps | None = None                                                  # ③ 만(기본 = A Ch/R, Q2 A)
    mesh_size_mm: float | None = Field(default=None, gt=0)                         # ③ 만(bead_doe.mesh.size_*_mm)


class DoeSpecParam(_Req):
    name: str = Field(min_length=1, max_length=200)
    lo: float
    hi: float


class DoeSpec(_Req):
    method: Literal["lhs", "halton", "fullfact"]
    n: int | None = None
    levels: int | None = None
    seed: int | None = None
    params: list[DoeSpecParam] = Field(max_length=1000)


class DoeMatrixIn(_Req):
    version: int = Field(ge=1)
    spec: DoeSpec


class DoeRunIn(_Req):
    version: int = Field(ge=1)
    matrix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    solver: str = Field(default="linear", max_length=32)      # linear 만(다른 값 422 SOLVER_UNSUPPORTED, UI 칸 없음)


class DoeSettingsOut(_Out):
    enabled: bool
    reason: str | None = None
    paicad: dict[str, Any]
    gmsh: dict[str, Any]
    scenarios: dict[str, bool]
    max_entries: int
    max_designs: int
    doe: dict[str, Any]
    mesh: dict[str, Any]
    boundary: dict[str, Any]
    step_max_mb: float
    part_title: str | None = None
    method_sources: dict[str, Any]


class DoeCheckOut(_Out):
    ok: bool
    step: dict[str, Any]
    base: dict[str, Any] | None = None
    mesh: MeshCheckOut | None = None
    entries: list[dict[str, Any]]
    size: dict[str, Any] | None = None
    props_default: dict[str, Any] | None = None
    mesh_size_default_mm: float | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class DoeStudyOut(_Out):
    id: str
    project_id: str
    scenario: DoeScenarioLit
    title: str
    entry_ids: list[str]
    inputs: dict[str, Any]
    phase: DoePhaseLit
    version: int
    prep: dict[str, Any] | None = None
    doe: dict[str, Any] | None = None
    job: JobOut | None = None
    result_ready: bool
    created_by_name: str
    created_at: datetime


class DoeParamsOut(_Out):
    beads: list[dict[str, Any]]
    params: list[dict[str, Any]]
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class DoePlanOut(_Out):
    frame: PlanViewFrame
    outline: list[list[float]]
    holes: list[list[list[float]]]
    elems: PlanViewElems
    beads: list[dict[str, Any]] = Field(default_factory=list)
    fixed: list[dict[str, Any]] = Field(default_factory=list)
    a_points: list[dict[str, Any]] = Field(default_factory=list)
    load_points: list[dict[str, Any]] = Field(default_factory=list)
    links: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DoeMatrixOut(_Out):
    spec: dict[str, Any]
    matrix_sha256: str
    designs: list[dict[str, Any]]
    n_designs: int
    dropped_duplicates: int
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class DoeResultOut(_Out):
    C_ref: float
    baseline: dict[str, Any]
    n_ok: int
    n_skipped: dict[str, int]
    n_failed: dict[str, int]
    ranking: list[dict[str, Any]]
    excluded: list[dict[str, Any]] = Field(default_factory=list)
    sensitivity: dict[str, Any] | None = None
    boundary_warnings_n: int
    view3d: list[str]
    best: dict[str, Any] | None = None
    noise_floor: float | None = None
    # v0.10.0 §11.4 ESL별 개선 지표(행: worst_ratio·min_improvement·all_improved·n_improved·n_worsened·
    # geo_mean_improvement·pareto, per_esl_inline 이면 per_esl[{entry_id,label,C,ratio,umax,epsmax}])
    ratio_tol: float | None = None
    per_esl_inline: bool = False
    esl: list[dict[str, Any]] = Field(default_factory=list)
    sort: str = "score"
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class DoePerEslDesign(_Out):
    id: str
    per_esl: list[dict[str, Any]]


class DoePerEslOut(_Out):
    esl: list[dict[str, Any]]
    ratio_tol: float | None = None
    designs: list[DoePerEslDesign]


class DoeFileOut(_Out):
    rel: str
    size: int = 0
    downloadable: bool = True


# ---------------------------------------------------------------- v0.11.0 SCX 릴레이(계약 esl_scx_relay.md §7.1) — 기능 A
class ScxAvail(_Out):
    enabled: bool
    reason_code: str | None = None
    reason: str | None = None


class ScxRootOut(_Out):
    key: str
    label: str


class ScxRelayOut(_Out):
    reachable: bool
    drive_state: str | None = None
    queue_paused: bool = False
    writes_active: bool = False
    job_api: bool = False
    max_download_bytes: int | None = None
    checked_at: datetime | None = None


class ScxAdaptersOut(_Out):
    version: str | None = None
    commit: str | None = None


class ScxStatusOut(_Out):
    fetch: ScxAvail
    verify: ScxAvail
    roots: list[ScxRootOut]
    relay: ScxRelayOut
    adapters: ScxAdaptersOut


class ScxEntryOut(_Out):
    name: str
    kind: Literal["dir", "file"]
    size: int | None = None
    modified_at: str | None = None
    hint: Literal["rad", "engine", "h3d", "include", "state"] | None = None


class ScxBrowseOut(_Out):
    root: str
    path: str = Field(description="루트 기준 상대 경로('' = 루트)")
    display: str = Field(description="표시 전용 전체 경로(home_display 기준)")
    entries: list[ScxEntryOut]
    total: int
    truncated: bool


class ScxFetchIn(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    root: str = Field(min_length=1, max_length=32)
    rad_rel: str = Field(min_length=1, max_length=1024, description="루트 기준 rad(starter) 경로")
    h3d_rel: str = Field(min_length=1, max_length=1024, description="루트 기준 h3d 경로(필수)")


class ScxFetchOut(_Out):
    upload_id: str
    job_id: str
