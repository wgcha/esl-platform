"""요청·응답 스키마(Pydantic v2). 응답에 lease_*·세션 토큰 없음."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    purpose: Literal["RAD", "RESULTS"]
    path: str = Field(min_length=1, max_length=1024)


class CaseCreate(_Req):
    project_id: str = Field(min_length=1, max_length=64)
    folder_name: str = Field(pattern=FOLDER_RE)
    title: str = Field(min_length=1, max_length=200)
    rad_path: str = Field(min_length=1, max_length=1024)
    results_dir: str = Field(min_length=1, max_length=1024)
    part_title: str | None = Field(default=None, min_length=1, max_length=200)

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
    job_type: Literal["CASE_EXTRACT", "ESL_SOLVE", "VALIDATE", "EXPORT"]
    params: dict[str, Any] = Field(default_factory=dict)


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
    case_id: str
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
