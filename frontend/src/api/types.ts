// 백엔드 실제 API 타입. 기준: docs/contracts/openapi_p1b.json(components.schemas) — 인터페이스 이름 = 스키마 이름.
// `npm run check:api`(scripts/check-api.mjs)가 스키마 키·필수·null 허용을 이 파일과 대조한다.
// 스키마가 자유 형식(object)인 응답(/tstar, /preview, /paths/inspect, extract_summary 등)은 백엔드 서비스 코드
// (backend/esl_platform/api/services, core/core_outputs.py, worker/esl_worker/register.py) 기준으로 옮겼다.

// ---------------------------------------------------------------- 오류
/** 오류 본문 {detail:{code,message,...}}. 413 ARTIFACT_TOO_LARGE 는 rel·path·size·limit 를 더 준다. */
export interface ApiErrorDetail {
  code: string;
  message: string;
  missing?: string[];
  candidates?: number[];
  rel?: string;
  path?: string;
  size?: number;
  limit?: number;
  [k: string]: unknown;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

// ---------------------------------------------------------------- 사용자·프로젝트·상태
export type Role = "general" | "power" | "admin";

export interface Me {
  user_id: string;
  username: string;
  display_name: string;
  is_global_admin: boolean;
  roles: Record<string, string>; // project_id → 역할(Role)
}

export interface Project {
  id: string;
  name: string;
  product_name: string | null;
}

export interface Health {
  status: string;
  version: string;
}

/** 설정 검증 오류 1건(키 경로 + 메시지) */
export interface ConfigIssue {
  key: string;
  message: string;
}
export interface ConfigStatus {
  ok: boolean;
  errors: ConfigIssue[];
}
export interface WorkerStatus {
  online: boolean;
  last_seen_at?: string | null;
  limiter?: string | null;
}
/** 코어 solver.backend 해석값(= ShellModel.stats.backend)과 사용 가능 백엔드(iterative 포함) */
export interface ToolsStatus {
  solver_backend: string;
  solver_backends_available: string[];
}
export interface StatusOut {
  config: ConfigStatus;
  worker: WorkerStatus;
  tools: ToolsStatus;
  version: string;
  core_version: string;
}
export type SystemStatus = StatusOut;

// ---------------------------------------------------------------- Case
export type StageStateName = "none" | "running" | "done" | "stale" | "failed";
export type StageNo = 1 | 2 | 3 | 4 | 5 | 6;
/** openapi StageState = 단계 상태 객체 */
export interface StageState {
  state: StageStateName;
  job_id?: string | null;
}
export type StageStatus = StageState;

export type Metric = "max_strain" | "plastic_strain";

/** cases.tstar */
export interface TStar {
  metric: Metric;
  frame_index: number;
  time: number;
  elem_id: number;
  value: number;
  source: "auto" | "user";
}

export interface MaterialSummary {
  id: number;
  law: string;
  E: number | null;
  nu: number | null;
  rho?: number | null;
  source: string;
}

/** cases.extract_summary (worker register_extract) */
export interface ExtractSummary {
  job_id: string;
  requested_part_title: string;
  part_id: number | null;
  part_title: string | null;
  units_label: string | null;
  n_nodes: number;
  n_elems: number;
  n_quad: number | null;
  n_tria: number | null;
  n_frames: number;
  mats: MaterialSummary[];
  /** 변위가 추출된 후보 프레임 D */
  disp_frames: number[];
  metrics: Metric[];
  warnings: string[];
}

export interface CaseOut {
  id: string;
  project_id: string;
  folder_name: string;
  title: string;
  status: string; // ACTIVE | ARCHIVED
  rad_path: string;
  results_dir: string;
  h3d_path: string | null;
  input_fingerprint: Record<string, unknown>;
  part_title: string;
  part_id: number | null;
  extract_summary: ExtractSummary | null;
  tstar: TStar | null;
  current_support_set_id: string | null;
  current_esl_run_id: string | null;
  /** Case 산출물 폴더(= folder_path) */
  case_dir: string;
  /** 결과 폴더 절대경로(표시·복사용) */
  folder_path: string;
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  version: number;
  /** GET /cases/{id}·쓰기 응답에만 */
  stage_status?: Record<string, StageState> | null;
}
export type Case = CaseOut;

export interface CaseCreate {
  project_id: string;
  folder_name: string;
  title: string;
  rad_path: string;
  results_dir: string;
  part_title?: string | null;
}

export interface CasePatch {
  version: number;
  title?: string | null;
  part_title?: string | null;
}

// ---------------------------------------------------------------- 경로 확인 (POST /paths/inspect, 자유 형식)
export interface InspectReq {
  purpose: "RAD" | "RESULTS";
  path: string;
}

export interface RadPart {
  id: number;
  title: string;
  n_elems?: number;
  [k: string]: unknown;
}

export interface InspectRadResult {
  normalized_path: string;
  ok: boolean;
  problems: string[];
  parts: RadPart[];
  includes: { path: string; ok: boolean }[];
  part_title: string;
  target_part: RadPart | null;
}

export interface ResultsFile {
  name: string;
  size?: number;
  mtime?: number;
  [k: string]: unknown;
}

export interface InspectResultsResult {
  normalized_path: string;
  ok: boolean;
  problems: string[];
  /** done.json 이 없거나 읽을 수 없으면 null */
  done: {
    ok: boolean;
    part_id: number | null;
    part_spec: string | null;
    candidate_frames: Partial<Record<Metric, number[]>> | null;
    hot_k: number | null;
    warnings: string[];
    h3d?: string | null;
  } | null;
  n_frames: number | null;
  files: ResultsFile[];
}

// ---------------------------------------------------------------- 작업
export type JobType = "CASE_EXTRACT" | "ESL_SOLVE" | "VALIDATE" | "EXPORT";
export type JobState = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELED" | "INTERRUPTED";

export interface JobCreate {
  job_type: JobType;
  params?: Record<string, unknown>;
}

export interface StepOut {
  step_no: number;
  step_key: string;
  kind: string;
  core_stage: string | null;
  state: string;
  progress_pct: number | null;
  exit_code: number | null;
  failure_code: string | null;
  failure_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}
export type JobStep = StepOut;

export interface JobOut {
  id: string;
  case_id: string;
  project_id: string;
  job_type: JobType;
  stage: number;
  lane: "SLOT" | "LIGHT";
  state: JobState;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  warnings: string[];
  cancel_requested: boolean;
  current_step_no: number | null;
  progress_pct: number | null;
  /** 대기 중일 때 대기열 순번(1부터) */
  queue_position: number | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  failure_code: string | null;
  failure_message: string | null;
  retry_of_job_id: string | null;
  resume_from_step: number | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  version: number;
  /** GET /jobs/{id}·작업 생성 응답에만 */
  steps?: StepOut[] | null;
}
export type Job = JobOut;
export type JobSummary = JobOut;

export interface LogOut {
  step: number;
  lines: string[];
  /** 바이트 오프셋. 다음 요청의 cursor */
  next_cursor: number;
  eof: boolean;
}
export type JobLog = LogOut;

export interface QueueLane {
  running: JobOut | null;
  queued: JobOut[];
}

export interface QueueOut {
  running: JobOut | null;
  queued: JobOut[];
  light: QueueLane;
}
export type Queue = QueueOut;

// ---------------------------------------------------------------- t* (GET /cases/{id}/tstar, 자유 형식)
export interface TstarPoint {
  frame_index: number;
  time: number;
  elem_id: number;
  value: number;
}

export interface TstarCandidate extends TstarPoint {
  rank: number;
  /** 변위가 추출된 프레임(D)인지. false 면 t*로 고를 수 없음(422 FRAME_NOT_CANDIDATE) */
  in_D: boolean | null;
}

export interface Hotspot {
  rank: number;
  elem_id: number;
  value: number;
  centroid: [number, number, number] | null;
  /** t* 에서 상승 중(검증 대상). null = 정보 없음 */
  rising: boolean | null;
}

export interface TstarMetricBlock {
  tstar: TstarPoint | null;
  candidates: TstarCandidate[];
  /** max-hold 곡선 m(f) = max_{e∈H} v[f,e] */
  history: { time: number[]; value: number[] };
  hotspots: Hotspot[];
  error?: string;
}

export interface TstarView {
  selected: TStar | null;
  default_metric: Metric | null;
  metrics: Partial<Record<Metric, TstarMetricBlock>>;
  /** 선택(없으면 기본) 지표의 hotspot */
  hotspots: Hotspot[];
  /** 변위가 추출된 후보 프레임 D */
  frames_D: number[];
}

export interface TstarPut {
  version: number;
  metric: string;
  frame_index: number;
}

// ---------------------------------------------------------------- 지지점·미리보기
export interface Plane {
  origin: number[];
  e1: number[];
  e2: number[];
  n: number[];
}

/** GET /cases/{id}/preview (자유 형식) */
export interface Preview {
  frame_index: number | null;
  plane: Plane;
  /** [node_id, a, b, value] */
  points: [number, number, number, number][];
  decimated: boolean;
  n_nodes: number;
  value: string;
  supports: { node_id: number; dof: string }[];
}

export type SupportSuggestReq = Record<string, never>;

export interface SupportSuggestOut {
  node_ids: number[];
  dofs: string[];
  coords: number[][];
  plane: Plane;
  /** PCA 4꼭지점 노드 ID */
  corners: number[];
}
export type SupportSuggest = SupportSuggestOut;

export interface SupportCreate {
  node_ids: number[];
}

export interface SupportSetOut {
  id: string;
  case_id: string;
  node_ids: number[];
  dofs: string[];
  source: "auto" | "user";
  plane: Plane | null;
  created_by: string;
  created_at: string;
  is_current?: boolean;
}
export type SupportSet = SupportSetOut;

// ---------------------------------------------------------------- ESL·검증·산출물
export interface EslKabsch {
  rot_deg: number | null;
  rms_def: number | null;
  max_def: number | null;
}

export interface EslForces {
  n_nodes_loaded: number | null;
  sum_f: number[] | null;
  sum_m: number[] | null;
  sum_abs_f?: number | null;
  equilibrium_rel: number | null;
  moment_rel?: number | null;
  max_f: { node_id: number; mag: number } | null;
  noise: { force_rel: number | null; hotspot_strain_rel: number | null; disp_precision?: string | null };
}

export interface EslRunOut {
  id: string;
  case_id: string;
  job_id: string;
  frame_index: number;
  time: number | null;
  metric: string;
  support_set_id: string;
  kabsch: EslKabsch | null;
  forces: EslForces | null;
  supports: { node_id: number; dof: string }[] | null;
  warnings: string[];
  dir_rel: string;
  status: "READY" | "FAILED";
  created_at: string;
  stale: boolean;
  is_current: boolean;
  /** 이 ESL 결과의 최신 검증 id */
  latest_validation_id: string | null;
}
export type EslRun = EslRunOut;

export interface ForceRow {
  node_id: number;
  x: number;
  y: number;
  z: number;
  fx: number;
  fy: number;
  fz: number;
  mag: number;
  is_support: boolean;
}

export interface ForcesOut {
  esl_run_id: string;
  n_nodes: number;
  rows: ForceRow[];
}

export interface ValidationHotspot {
  rank?: number | null;
  elem_id: number;
  eps_rad: number;
  eps_val: number;
  rel_err: number;
}

export interface ValidationOut {
  id: string;
  esl_run_id: string;
  case_id: string;
  job_id: string;
  /** full solve 생략 시 null(skipped) */
  disp_rms_rel: number | null;
  reaction_rel: number | null;
  hotspots: ValidationHotspot[];
  excluded: { elem_id: number; reason: string }[];
  verdict: "PASS" | "FAIL";
  fail_reasons: string[];
  /** 코어 validation.json criteria (disp_rms_rel_max, hotspot_strain_rel_err_max, reaction_rel_max, …) */
  criteria: Record<string, unknown>;
  dir_rel: string;
  created_at: string;
  stale: boolean;
}
export type Validation = ValidationOut;

export interface ArtifactOut {
  id: string;
  case_id: string;
  job_id: string | null;
  kind: string;
  rel: string;
  size: number;
  /** 서버 절대경로(복사용) */
  path: string;
  /** size ≤ ui.max_artifact_bytes. false 면 다운로드는 413 ARTIFACT_TOO_LARGE */
  downloadable: boolean;
  created_at: string;
}
export type Artifact = ArtifactOut;

export type ExportTarget = "radioss_inc" | "fem" | "csv";
