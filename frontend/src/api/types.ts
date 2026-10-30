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
  /** v0.10.0(esl_menu_restructure.md §5.4): 상태 사유(예: SUPPORT_AUTO_BLOCKED·TSTAR_NOT_CONFIRMED) */
  reason?: StageReason | null;
}
export interface StageReason {
  code: string;
  message: string;
}
/** v0.10.0 §5.4: 화면 4단계 상태(①입력 ②t*·지지점 ③ESL ④검증). stage_status("1".."6")는 하위 호환(deprecated) */
export interface StepStatus {
  input: StageState;
  tstar: StageState;
  esl: StageState;
  validate: StageState;
}
export type StepKey = keyof StepStatus;

/** v0.10.0 §5.2: 자동 3-2-1 지지 품질 검사 */
export interface SupportChecks {
  area_ratio: number | null;
  min_dist_rel: number | null;
  cond_ratio: number | null;
}
export interface SupportProblem {
  code: string;
  message: string;
  value?: number | null;
  limit?: number | null;
}
/** cases.tstar.support_auto(§5.1): OK = 자동 저장, BLOCKED = 검사 실패(지지 없음), KEPT = 기존 지지 유지, MANUAL = 고급 칸 수동 지정 */
export interface SupportAuto {
  status: "OK" | "BLOCKED" | "KEPT" | "MANUAL";
  mode?: "pca4" | "pca8" | null;
  source?: "auto" | "user" | null;
  checks?: SupportChecks | null;
  problems?: SupportProblem[] | null;
  rule_version?: number | null;
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
  /** v0.10.0 §5.1: t* 확정 때 함께 한 자동 3-2-1 결과(추출 재등록 시 사라짐) */
  support_auto?: SupportAuto | null;
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
  /** v0.8.0 누적 낙하 씬(rad 가 이전 런 상태 파일 .str/.sta 를 include)일 때만 — 계약 esl_cumulative_input.md §8·§13 */
  cumulative?: CumulativeSummary;
}

export type CumulativeMode = "cumulative" | "incremental" | "trivial";
export interface CumulativeDiagnosis {
  mode: CumulativeMode;
  detected: CumulativeMode | "ambiguous";
  r0: number | null;
  mono: number | null;
  n_S: number;
  forced: boolean;
}
export interface CumulativeThickness {
  source: "state" | "rad";
  k_l_source?: "state" | "prop" | "rad";
  n_elems: number;
  n_state: number;
  t0: number | number[] | null;
  ratio: { min: number; p01: number; mean: number; p99: number; max: number } | null;
  n_changed: number | null;
  max_thinning_pct: number | null;
  elem_max_thinning: number | null;
}
export interface CumulativeSummary {
  enabled: boolean;
  files: { name: string; kinds: ("geometry" | "initial")[]; runname: string | null; size: number | null }[];
  epsp_mode: CumulativeMode;
  eq_mode: CumulativeMode;
  /** 이전 소성 요소값 집계(mid_mean·mid_max·max·mean) */
  agg: string;
  n_prev_elems: number;
  prev_max: number;
  prev_p99?: number;
  coord_source: "state" | "rad" | "state+rad";
  n_nodes_state: number;
  n_nodes_rad?: number;
  thickness: CumulativeThickness;
  diagnosis?: { epsp: CumulativeDiagnosis; eq: CumulativeDiagnosis };
  warning_codes: string[];
}

export interface CaseOut {
  id: string;
  project_id: string;
  folder_name: string;
  title: string;
  status: string; // ACTIVE | ARCHIVED
  rad_path: string;
  /** h3d 입력이면 서버 추출 출력 폴더(<esl_root>/_h3d/<폴더>/raw — 추출 전엔 없음) */
  results_dir: string;
  h3d_path: string | null;
  /** §6·§10: 입력 종류 — H3D = 서버가 h3d 에서 추출(① 첫 step H3D_EXTRACT), RESULTS = 추출 결과 폴더 */
  input_kind: CaseInputKind;
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
  /** v0.6.0 §6.5: 입력 h3d 의 업로드 메타(압축 모드 배지). 없으면 null */
  input_h3d_meta?: H3dMeta | null;
  /** GET /cases/{id}·쓰기 응답에만 (v0.10.0: deprecated — 화면은 step_status 만 쓴다) */
  stage_status?: Record<string, StageState> | null;
  /** v0.10.0 §5.4: 화면 4단계 상태 */
  step_status?: StepStatus | null;
}
export type Case = CaseOut;

export type CaseInputKind = "RESULTS" | "H3D";

/** §6: rad 필수 + h3d_path(서버 추출) 또는 results_dir(추출 결과 폴더) 중 하나 */
export interface CaseCreate {
  project_id: string;
  folder_name: string;
  title: string;
  rad_path: string;
  h3d_path?: string | null;
  results_dir?: string | null;
  part_title?: string | null;
}

export interface CasePatch {
  version: number;
  title?: string | null;
  part_title?: string | null;
}

// ---------------------------------------------------------------- 경로 확인 (POST /paths/inspect, 자유 형식)
export interface InspectReq {
  purpose: "RAD" | "RESULTS" | "H3D";
  path: string;
  part_title?: string | null;
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
/** P2(계약 esl_p2_library.md §11·§12): CASE_REPORT(LIGHT, Case HTML 보고서), LIB_ANALYZE(SLOT, 라이브러리 종합분석),
 *  LIB_COMPARE(LIGHT, 설계 버전 비교) */
export type JobType = "CASE_EXTRACT" | "ESL_SOLVE" | "VALIDATE" | "EXPORT" | "CASE_REPORT" | "LIB_ANALYZE" | "LIB_COMPARE" | "OPT_RUN" | "DOE_PREP" | "DOE_PREVIEW" | "DOE_RUN" | "SCX_FETCH";
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
  /** 라이브러리 작업(LIB_ANALYZE)은 null */
  case_id: string | null;
  /** LIB_ANALYZE 의 analysis_runs.id */
  analysis_id?: string | null;
  /** LIB_COMPARE 의 comparisons.id */
  comparison_id?: string | null;
  /** v0.7.0 OPT_RUN 의 opt_runs.id (esl_opt_run.md §6.1) */
  opt_run_id?: string | null;
  project_id: string;
  job_type: JobType;
  stage: number;
  /** v0.11.0 XFER = HTTP 전송·원격 대기 전용 레인(esl_scx_relay.md SR-D-9) */
  lane: "SLOT" | "LIGHT" | "XFER";
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
/** v0.11.0 진행 문구(예 "h3d 12.3 / 30.0 GB", "대시보드가 SCX에서 받는 중" — esl_scx_relay.md §7.1). 백엔드 JobOut 스키마에
 *  progress_label 이 들어가면 JobOut 으로 옮긴다(그 전까지 check:api 가 TS 전용 키로 막지 않게 별도 타입). */
export type JobProgressLabel = { progress_label?: string | null };
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
  /** 하위 호환: SLOT 레인 실행 중 첫 작업 */
  running: JobOut | null;
  /** §6: SLOT 레인 실행 중 전부(동시 실행 최대 slots 개) */
  running_all: JobOut[];
  /** worker.slots — SLOT 레인 동시 실행 수 */
  slots: number;
  queued: JobOut[];
  light: QueueLane;
}
export type Queue = QueueOut;

// ---------------------------------------------------------------- t* (GET /cases/{id}/tstar, 자유 형식)
export interface TstarPoint {
  frame_index: number;
  time: number;
  elem_id: number;
  /** 누적 씬이면 누적값(이전 + 이번) */
  value: number;
  /** v0.8.0 누적 씬만: 이번 낙하 증분·이전 값 */
  value_inc?: number;
  value_prev?: number;
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
  value_inc?: number;
  value_prev?: number;
}

export interface TstarMetricBlock {
  tstar: TstarPoint | null;
  candidates: TstarCandidate[];
  /** max-hold 곡선 m(f) = max_{e∈H} v[f,e] (누적 씬이면 누적, value_inc = 이번 낙하 증분) */
  history: { time: number[]; value: number[]; value_inc?: number[] };
  hotspots: Hotspot[];
  error?: string;
  /** v0.8.0 누적 씬: 이전 손상만(이번 증가 없음) 제외 수 */
  cumulative?: { mode: CumulativeMode; n_excluded_no_increment: number };
}

export interface TstarView {
  selected: TStar | null;
  default_metric: Metric | null;
  metrics: Partial<Record<Metric, TstarMetricBlock>>;
  /** 선택(없으면 기본) 지표의 hotspot */
  hotspots: Hotspot[];
  /** 변위가 추출된 후보 프레임 D */
  frames_D: number[];
  /** v0.8.0 누적 씬만 */
  cumulative?: { enabled: boolean; epsp_mode: CumulativeMode; eq_mode: CumulativeMode; agg: string; n_prev_elems: number; min_increment: number };
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
  plane?: Plane | null;
  /** PCA 4꼭지점 노드 ID */
  corners: number[];
  /** v0.10.0 §5.1: 같은 auto_support 결과(status 기본 OK, BLOCKED 면 node_ids 비고 problems) */
  status?: "OK" | "BLOCKED";
  mode?: "pca4" | "pca8" | null;
  checks?: SupportChecks | null;
  problems?: SupportProblem[];
  rule_version?: number | null;
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
  /** v0.5.7(esl_disp_primary §3.3): UNDETERMINED = 판정 불가(전체 재해석 생략·변형 없음) */
  verdict: "PASS" | "FAIL" | "UNDETERMINED";
  /** 판정 체계: 새 검증 "disp_primary/1", 0.5.7 이전 검증은 null(= LEGACY) */
  scheme: string | null;
  /** 표시 상태. scheme 이 null 이면 LEGACY, 아니면 verdict */
  status: ValidationStatus;
  disp_max_rel: number | null;
  disp_noise_rel: number | null;
  /** NO_FULL_SOLVE | ZERO_DISP (UNDETERMINED 일 때만) */
  undetermined_reason: string | null;
  /** 변위 전 노드 분석 요약(§3.5). full_solve 미수행·LEGACY 는 null */
  disp: DispSummary | null;
  /** 변형률 참고 집계(§3.4). LEGACY 는 null */
  strain_ref: StrainRef | null;
  fail_reasons: string[];
  /** 코어 validation.json criteria (disp_rms_rel_max, hotspot_strain_rel_err_max, reaction_rel_max, …) */
  criteria: Record<string, unknown>;
  dir_rel: string;
  created_at: string;
  stale: boolean;
  /** P2 §7.2·§11: 전 요소 재현 정확도 요약(validation.json field). 예전 검증은 null/없음 */
  field?: FieldSummary | null;
}
export type Validation = ValidationOut;
export type ValidationStatus = "PASS" | "FAIL" | "UNDETERMINED" | "LEGACY";

// ---------------------------------------------------------------- 변위 주지표 판정 (계약 esl_disp_primary.md §3.4·§3.5·§4·§7)
export interface DispHist {
  /** log10(r) bin 경계(균등) */
  edges_log10: number[];
  counts: number[];
  n: number;
  /** r = 0 노드 수(따로 센다) */
  n_zero: number;
}

export interface DispTopRow {
  node_id: number;
  /** e/U */
  r: number;
  e: number;
  /** ‖d_rel‖ */
  u_rel_mag: number;
  a: number;
  b: number;
  is_support: boolean;
}

export interface DispSummary {
  U: number;
  n_nodes: number;
  n_support: number;
  rms_rel: number;
  max_rel: number;
  max_node_id: number;
  /** r = e/U 분위 */
  p50?: number;
  p90?: number;
  p99?: number;
  max?: number;
  hist: DispHist;
  top: DispTopRow[];
  support: { node_id: number; r: number; e?: number }[];
  plane?: FieldPlane;
}

export interface StrainPlastic {
  n_plastic: number;
  frac_plastic: number;
  n_exceed_plastic: number;
}

/** 변형률 참고 집계. 소성 영역은 epsp 가 없으면 plastic = null */
export interface StrainRef {
  exceeded: boolean;
  n_exceed: number;
  frac_exceed: number;
  frac_exceed_valid?: number | null;
  p99_err_pct: number | null;
  plastic?: StrainPlastic | null;
  n_plastic?: number | null;
  frac_plastic?: number | null;
  n_exceed_plastic?: number | null;
  /** v0.8.0 누적 씬: 비교 기준 = 이번 낙하 증분, 소성 요소 수 누적/이번 */
  basis?: "increment";
  n_plastic_cum?: number;
  n_plastic_inc?: number;
  cum_max?: number;
  inc_max?: number;
}

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

// ================================================================ P2 (계약 esl_p2_library.md §7·§11)
// openapi_p1b.json 갱신 전: 계약 §11 + 코어(esl/pipeline.py _field_compare, esl/report/field.py summarize) 기준.

// ---------------------------------------------------------------- 전 요소 비교 요약 (validation.field)
/** 비교 사유 코드(field.REASONS): OK 만 비교 대상 */
export type FieldReason = "OK" | "HOLD" | "LOW" | "EXCLUDED" | "NO_PREV";

export interface FieldRow {
  elem_id: number;
  eps_rad: number;
  eps_esl: number;
  err_pct: number | null;
  valid: boolean;
  reason: string;
  xi?: number;
  eta?: number;
}

/** 최대변형률 비교: t* 상승 요소 중 ε_rad 최대 요소와 같은 요소의 ESL 값, ESL 전체 최대 */
export interface FieldMax {
  elem_id: number;
  eps_rad: number;
  eps_esl: number;
  err_pct: number;
  abs_err_pct: number;
  eps_esl_max: number;
  eps_esl_max_elem_id: number;
  peak_err_pct: number;
  xi?: number;
  eta?: number;
  esl_max_xi?: number;
  esl_max_eta?: number;
}

export interface FieldQuantiles {
  mean: number;
  p50: number;
  p90: number;
  p95: number;
  max: number;
}

export interface FieldHist {
  edges: number[];
  counts: number[];
  range_pct: number | null;
  n: number;
  n_clipped: number;
}

export interface FieldSummary {
  n_elems: number;
  n_rising: number;
  n_valid: number;
  n_ok?: number;
  n_hold?: number;
  n_low?: number;
  n_excluded?: number;
  n_no_prev?: number;
  max: FieldMax | null;
  /** valid 요소 |오차| % 분위수 */
  abs_err_pct: FieldQuantiles | null;
  /** 오차 ≤5·10·20 % 요소 비율(0~1), 키 "5"·"10"·"20" */
  frac_within: Record<string, number> | null;
  top: FieldRow[];
  worst: FieldRow[];
  hist: FieldHist;
  /** 판정 기준(%): 최대변형률 오차·P90 */
  criteria?: { max_err_pct_max: number; p90_err_max: number };
  min_rel?: number;
  prev_source?: string;
  reason_text?: Record<string, string>;
  note?: string;
}

// ---------------------------------------------------------------- 겹쳐보기 자료 (GET /validations/{id}/field, /section)
export type FieldLayer = "rad" | "esl" | "err";
/** [elem_id, a, b, value, reason, flags?] — (a, b) = PCA 평면 실좌표(ξ, η). value: err 레이어는 valid 아니면 null.
 *  flags(v0.5.7, 비트): 1 = 기준 초과 요소, 2 = 소성 영역(epsp>0). 예전 서버는 열이 없다. */
export type FieldPoint = [number, number, number, number | null, string, number?];

export interface FieldPlane {
  origin: number[];
  e1: number[];
  e2: number[];
}

/** rad·esl = 두 레이어 공통 [min, max](유한값 전체), err = ±R %(|오차| P99 기준). 값이 없으면 null */
export interface ColorRange {
  min?: number | null;
  max?: number | null;
}

/** 견고한 자동 색 범위(§14.2): raw = 올림 전 분위값 */
export interface ColorRangeRobust {
  min: number | null;
  max: number | null;
  basis: string;
  raw: number | null;
}

export interface FieldOut {
  validation_id: string;
  layer: FieldLayer;
  n_total: number;
  n_returned: number;
  decimated: boolean;
  /** 다운샘플 격자 칸 크기 [dξ, dη] (다운샘플 안 하면 null) */
  cell?: number[] | null;
  plane: FieldPlane;
  color_range: ColorRange;
  color_range_robust?: ColorRangeRobust | null;
  points: FieldPoint[];
}

/** 변위 컨투어 레이어: err = e/U, rel = ‖d_rel‖(Radioss), val = ‖d_val‖(ESL) */
export type DispLayer = "err" | "rel" | "val";
/** [node_id, a, b, value, is_support] */
export type DispPoint = [number, number, number, number, boolean | number];

export interface DispFieldOut {
  validation_id: string;
  layer: DispLayer;
  n_total: number;
  n_returned: number;
  decimated: boolean;
  cell?: number[] | null;
  plane: FieldPlane;
  color_range: ColorRange;
  color_range_robust?: ColorRangeRobust | null;
  U: number;
  points: DispPoint[];
}

export type SectionAxis = "xi" | "eta";
/** 단면선: s = 단면 방향 실좌표, w0 = 초기 면외 좌표, w_rad·w_esl = 면외 변위(Radioss u_rel·ESL u_val) */
export interface SectionOut {
  validation_id: string;
  axis: SectionAxis;
  at: number;
  band: number;
  n_elems: number;
  s: number[];
  w_rad: number[];
  w_esl: number[];
  w0: number[];
  /** w_esl − w_rad (실제 길이 단위, 배율 없음). has_val=false 면 빈 배열 */
  dw: number[];
  stats: SectionStats;
  /** 전체 재해석 해가 있는가(compare_disp.npz). false 면 ESL·Δw 선을 숨긴다 */
  has_val: boolean;
  /** 지도에 그릴 단면 중심선(PCA 평면 실좌표)과 띠 반폭 */
  line: SectionLine | null;
  /** 길이 단위 표시 문자열(설정 units.length) */
  units: string | null;
  suggest: SectionSuggest[];
}

/** 단면이 비면 전부 null */
export interface SectionStats {
  dw_max_abs: number | null;
  s_at_dw_max: number | null;
  dw_rms: number | null;
  U: number | null;
  dw_max_rel: number | null;
  dw_rms_rel: number | null;
  /** max(|w_rad|, |w_esl|) — 배율 표기용 실제 최대 면외 변위 */
  w_max_abs: number | null;
}

export interface SectionLine {
  a0: number;
  b0: number;
  a1: number;
  b1: number;
  band_abs: number;
  /** 대상 파트 요소 중심의 정규화 xi 범위 [min,max] — 지도 클릭 정규화 기준 */
  xi_range: number[];
  eta_range: number[];
}

export type SectionSuggestKey = "max_disp_err" | "hotspot1";
/** xi·eta = 0~1 정규화 좌표, id = node_id(max_disp_err) 또는 elem_id(hotspot1) */
export interface SectionSuggest {
  key: SectionSuggestKey;
  label: string;
  xi: number;
  eta: number;
  id: number;
}

// ---------------------------------------------------------------- 라이브러리 (library_entries)
export type EntryStatus = "ACTIVE" | "RETIRED";
export type DropType = "Corner" | "Edge" | "Face";

export interface EntryModel {
  name?: string | null;
  inch?: number | null;
  version?: string | null;
  date?: string | null;
  project?: string | null;
  /** 제품 질량(kg, 사용자 입력). mass 정규화에 필요(없으면 NORMALIZATION_META_MISSING) */
  product_mass?: number | null;
  /** 파트 질량(rad 계산) — 제품 질량 아님 */
  part_mass?: number | null;
  part_id?: number | null;
  part_title?: string | null;
  units_label?: string | null;
  n_nodes?: number | null;
  n_elems?: number | null;
}

export interface EntryScene {
  project?: string | null;
  scenario?: string | null;
  seq?: number | null;
  drop_type?: string | null;
  /** ISTA orient 면 수로 본 분류(Corner|Edge|Face) */
  drop_class?: string | null;
  round?: string | null;
  scene_no?: number | null;
  orient?: string | null;
  faces?: number[] | null;
  suffix?: string | null;
  variant?: string | null;
  raw?: string | null;
  warnings?: string[];
}

/** FAIL 확정 등록 기록 */
export interface ConfirmedFail {
  reason: string | null;
  by: string;
  by_name: string;
  at: string;
}

export interface EntryQuality {
  verdict?: string | null;
  fail_reasons?: string[];
  field_max_err_pct?: number | null;
  field_p90_err_pct?: number | null;
  hotspot1_rel_err?: number | null;
  disp_rms_rel?: number | null;
  reaction_rel?: number | null;
  noise?: Record<string, unknown> | null;
  confirmed_fail?: ConfirmedFail | null;
  /** v0.5.7: scheme 없음 = LEGACY(이전 판정 체계) */
  status?: ValidationStatus | null;
  scheme?: string | null;
  disp_max_rel?: number | null;
  disp_noise_rel?: number | null;
  strain_exceed_frac?: number | null;
  undetermined_reason?: string | null;
  confirmed_undetermined?: ConfirmedFail | null;
  /** v0.10.0 §7.4: 재검증으로 정상 전환된 기록 */
  revalidated?: EntryRevalidated | null;
}

export interface EntryRevalidated {
  from_validation_id: string | null;
  from_status: string | null;
  job_id: string;
  at: string;
  by: string;
  by_name: string;
}

/** v0.10.0 §7.4: 부적격 사유(LEGACY·사유와 함께 등록된 FAIL·판정 불가) */
export type IneligibleReason = "LEGACY" | "FAIL" | "UNDETERMINED";
/** §7.3 재검증 불가 사유: code = 오류 코드(CASE_ARCHIVED·REVALIDATE_NOT_POSSIBLE·CASE_JOB_BUSY), reason = 세부(RUN_SNAPSHOT_MISSING·EXTRACT_CHANGED, 없으면 code), message = 한글 안내(툴팁) */
export interface RevalidateBlock {
  code: string;
  reason: string;
  message: string;
}

export interface EntryOut {
  id: string;
  project_id: string;
  case_id: string;
  case_title?: string | null;
  esl_run_id: string;
  validation_id?: string | null;
  status: EntryStatus;
  retired_by_id?: string | null;
  retired_at?: string | null;
  retire_reason?: string | null;
  model: EntryModel;
  scene: EntryScene;
  quality: EntryQuality;
  tstar?: Record<string, unknown> | null;
  summary?: Record<string, unknown> | null;
  dir_rel: string;
  summary_rel: string;
  sha256: string;
  registered_by: string;
  registered_by_name: string;
  registered_at: string;
  updated_at: string;
  note?: string | null;
  force_reason?: string | null;
  warnings: string[];
  version: number;
  /** v0.7.0(esl_opt_run.md §5.1): 크기·모델 동일성 키·변형 모드(지연 백필이라 없을 수 있음) */
  size?: EntrySize | null;
  topo_sha256?: string | null;
  deform_mode?: DeformModeOut | null;
  /** v0.10.0 §7.4: 강성 평가 스터디·비드 최적화·종합분석에 쓸 수 있는가(quality.status PASS ∧ scheme) */
  eligible?: boolean;
  ineligible_reason?: IneligibleReason | null;
  /** 재검증 불가 사유(미리 계산) — 있으면 [재검증] 비활성 + 툴팁 */
  revalidate_block?: RevalidateBlock | null;
  /** 진행 중인 재검증 작업(VALIDATE origin library_revalidate) */
  revalidate_job?: { job_id: string; state: JobState } | null;
}
export type LibraryEntry = EntryOut;

/** 변형 모드(§7.4): 덴팅·뒤틀림·굽힘 */
export type DeformMode = "dent" | "twist" | "bend";
export interface EntrySize {
  inch: number | null;
  /** 정규화 frame 치수(mm) */
  L_xi: number | null;
  L_eta: number | null;
}
export interface DeformModeOut {
  /** 자동 분류(분류 불가면 null) */
  auto?: DeformMode | null;
  /** 사용자 수정(없으면 null) */
  user?: DeformMode | null;
  /** user ?? auto */
  effective?: DeformMode | null;
  metrics?: { bend?: number; twist?: number; resid?: number; kappa?: number };
  user_by?: string | null;
  user_at?: string | null;
  rule_version?: number | null;
}

export interface EntryCreate {
  esl_run_id: string;
  validation_id?: string | null;
  note?: string | null;
  /** 검증 FAIL 을 확정 등록할 때 필수 */
  force_reason?: string | null;
}

export interface EntryModelPatch {
  name?: string | null;
  inch?: number | null;
  version?: string | null;
  date?: string | null;
  product_mass?: number | null;
}

export interface EntryScenePatch {
  project?: string | null;
  scenario?: string | null;
  seq?: number | null;
  drop_type?: DropType | null;
  round?: string | null;
  scene_no?: number | null;
  orient?: string | null;
  suffix?: string | null;
  variant?: string | null;
}

export interface EntryPatch {
  version: number;
  model?: EntryModelPatch | null;
  scene?: EntryScenePatch | null;
  note?: string | null;
  /** v0.7.0: 변형 모드 사용자 수정. null = 자동으로 되돌림, 키 없음 = 변경 없음 */
  deform_mode?: DeformMode | null;
}

export interface EntryRetire {
  reason?: string | null;
}

export interface EntryQuery {
  project_id: string;
  model?: string;
  inch?: string;
  drop_type?: string;
  drop_class?: string;
  orient?: string;
  scenario?: string;
  verdict?: string;
  status?: EntryStatus;
  /** v0.7.0: 변형 모드(effective) 필터 */
  mode?: string;
}

// ---------------------------------------------------------------- 종합분석 (analysis_runs)
export type Normalization = "none" | "mass" | "inch2";
export type Objective = "minmax" | "weighted";
/** §12.1 최적화 하중(덱 subcase) 구성: 모든 씬(기본) | 대표 | 대표+최악 */
export type OptdeckCases = "all" | "representative" | "representative+worst";

/** 비우면 전체. entry_ids 를 주면 다른 필터 무시 */
export interface AnalysisFilters {
  entry_ids?: string[] | null;
  model?: string[] | null;
  inch?: number[] | null;
  drop_type?: string[] | null;
  drop_class?: string[] | null;
  orient?: string[] | null;
  scenario?: string[] | null;
  verdict?: string[] | null;
}

export interface AnalysisOptions {
  normalization?: Normalization | null;
  n_representative?: number | null;
  objective?: Objective | null;
  svd_energy?: number | null;
  worst_case?: boolean | null;
  /** 정규화 대상 값(대상 항목 메타가 없을 때) */
  target_mass?: number | null;
  target_inch?: number | null;
  /** 없으면 서버 설정 optdeck.cases(기본 all) */
  optdeck_cases?: OptdeckCases | null;
}

export interface AnalysisCreate {
  project_id: string;
  title?: string | null;
  target_entry_id?: string | null;
  filters?: AnalysisFilters;
  options?: AnalysisOptions;
}

/** analysis_runs.result (워커 register._analysis_summary) */
export interface AnalysisCase {
  index: number;
  entry_id: string;
  product: string | null;
  inch: number | null;
  drop_class: string | null;
  orient: string | null;
  scene: number | string | null;
  scenario: string | null;
  verdict: string | null;
  cluster: number;
  is_medoid: boolean;
  is_worst: boolean;
  sum_abs_f: number;
  scale_factor: number;
  svd_coef: number[];
}

export interface AnalysisLoadCase {
  label: string;
  role: "medoid" | "worst";
  cluster: number;
  entry_id: string;
  case_index: number;
}

export interface AnalysisCluster {
  id: number;
  size: number;
  medoid_entry: string;
  worst_entry: string;
  mean_dist: number;
  members: (string | null)[];
}

export interface AnalysisResult {
  n_cases: number;
  grid: { nx: number; ny: number } | null;
  target: { entry_id: string; model: Record<string, unknown> | null } | null;
  svd: { n_modes: number; threshold: number | null; feature: string | null; cum_energy_at_r: number | null; energy: number[] };
  load_cases: AnalysisLoadCase[];
  clusters: AnalysisCluster[];
  envelope: { max: number; argmax_cell: number[] } | null;
  mapping: Record<string, unknown> | null;
  stats: Record<string, unknown> | null;
  cases: AnalysisCase[];
  warnings: string[];
  optdeck: {
    deck: string;
    files: string[];
    objective: string;
    n_subcases: number;
    n_design_elems: number;
    n_nondesign_elems: number;
    card_format: string;
    reference_compliance: unknown;
  } | null;
  /** §12.1 덱 하중 구성(이전 분석에는 없음) */
  deck?: DeckSummary | null;
}

/** 덱 하중 구성: 설정·적용 모드, subcase 수, max_cases 초과 자동 축소 여부, 제외 씬(사유) */
export interface DeckSummary {
  requested: OptdeckCases;
  mode: OptdeckCases;
  reduced: boolean;
  max_cases: number;
  n_cases: number;
  n_subcases: number;
  n_excluded: number;
  excluded: { entry_id: string; scene: string | null; reason: string }[];
}

export interface AnalysisOut {
  id: string;
  project_id: string;
  title?: string | null;
  target_entry_id?: string | null;
  filters: AnalysisFilters;
  options: AnalysisOptions;
  entry_ids: string[];
  n_entries: number;
  /** 연동 작업(LIB_ANALYZE) 상태, 작업이 없으면 NONE */
  status: JobState | "NONE";
  job_id?: string | null;
  job?: JobOut | null;
  result?: AnalysisResult | null;
  /** v0.10.0 §7.5: 필터 기반 분석에서 부적격이라 뺀 항목 수(0이면 생략) */
  excluded_ineligible?: number | null;
  dir_rel: string;
  folder_path: string;
  result_rel?: string | null;
  report_rel?: string | null;
  optdeck_rel?: string | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
}
export type Analysis = AnalysisOut;

/** GET /library/analyses/{id}/files — 다운로드는 GET /library/analyses/{id}/download?rel= */
export interface AnalysisFileOut {
  rel: string;
  kind: "report" | "optdeck" | "analysis" | "log" | "other";
  size: number;
  path: string;
  downloadable: boolean;
}

// ---------------------------------------------------------------- 설계 버전 비교 (comparisons, §12.2)
export interface ComparisonFilters {
  inch?: number[] | null;
  drop_type?: string[] | null;
  drop_class?: string[] | null;
  orient?: string[] | null;
  scenario?: string[] | null;
  verdict?: string[] | null;
}

export interface ComparisonOptions {
  cos_min?: number | null;
  n_representative?: number | null;
}

/** POST /library/comparisons — 기준 버전이 없으면 비교 버전 직전(서버 자연 정렬) */
export interface ComparisonCreate {
  project_id: string;
  model: string;
  new_version: string;
  base_version?: string | null;
  title?: string | null;
  filters?: ComparisonFilters;
  options?: ComparisonOptions;
}

export type ComparisonVerdict = "CONVERGED" | "ITERATE";

export interface ComparisonQuality {
  verdict: string | null;
  hotspot1_rel_err: number | null;
  field_p90: number | null;
}

/** comparisons.result.scenes[] (워커 _compare_summary) */
export interface ComparisonScene {
  label: string;
  base_entry: string;
  new_entry: string;
  cos: number;
  force_ratio: number | null;
  hotspot_shift: number | null;
  eps_ratio: number | null;
  quality_base: ComparisonQuality;
  quality_new: ComparisonQuality;
  changed: boolean;
  reasons: string[];
}

interface Range3 {
  min: number | null;
  max: number | null;
  mean: number | null;
}

/** 판정 기준(§12.4: cos_min 기본 0.95, 셀당 노드 하한 64, coarsen false|half) */
export interface ComparisonCriteria {
  cos_min: number;
  rep_same: boolean;
  min_nodes_per_cell?: number;
  coarsen?: false | "half";
}

/** 셀당 노드 해상도(§12.4): ok | warn(< min_nodes_per_cell) | low(< 16, 판정 신뢰 낮음) | unknown */
export type ComparisonReliability = "ok" | "warn" | "low" | "unknown";

export interface ComparisonResolution {
  nodes_per_cell_min: number | null;
  nodes_per_cell_base_min: number | null;
  nodes_per_cell_new_min: number | null;
  min_nodes_per_cell: number;
  low_trust_below: number;
  level: ComparisonReliability;
  label: string;
  coarsen: false | "half";
  coarsen_applied: boolean;
  feature_grid: { nx: number; ny: number };
}

export interface ComparisonResult {
  convergence: {
    verdict: ComparisonVerdict;
    label: string;
    converged: boolean;
    criteria: ComparisonCriteria;
    reliability?: ComparisonReliability;
    reliability_label?: string;
    reasons: string[];
    changed_scenes: { label: string; base_entry: string; new_entry: string; cos: number; reasons: string[] }[];
  };
  aggregate: {
    n_paired: number;
    cos_min: number;
    cos_mean: number;
    argmin_cos: string;
    force_ratio: Range3;
    eps_ratio: Range3;
    hotspot_shift: Range3;
    n_below_cos: number;
    n_verdict_changed: number;
    n_changed: number;
  };
  criteria: ComparisonCriteria;
  resolution?: ComparisonResolution | null;
  n_base: number;
  n_new: number;
  n_paired: number;
  representatives: {
    k: number;
    rep_same: boolean;
    /** medoid_cos = 짝 medoid cos ≥ cos_min, base_kept = 기준 대표가 새 버전에서도 거의 최적 */
    rep_basis?: "medoid_cos" | "base_kept" | null;
    medoid_id_same?: boolean;
    partition_same: boolean;
    partition_agreement: number;
    base_reps_cost_excess?: number;
    matching: unknown[];
  };
  scenes: ComparisonScene[];
  unpaired: { base_only: { label: string; entry_id: string }[]; new_only: { label: string; entry_id: string }[] } | null;
  warnings: string[];
}

export interface ComparisonOut {
  id: string;
  project_id: string;
  title?: string | null;
  model: string;
  base_version: string;
  new_version: string;
  filters: ComparisonFilters;
  options: ComparisonOptions;
  base_entry_ids: string[];
  new_entry_ids: string[];
  n_paired: number;
  /** 연동 작업(LIB_COMPARE) 상태, 작업이 없으면 NONE */
  status: JobState | "NONE";
  verdict?: ComparisonVerdict | null;
  job_id?: string | null;
  job?: JobOut | null;
  result?: ComparisonResult | null;
  result_rel?: string | null;
  report_rel?: string | null;
  dir_rel: string;
  folder_path: string;
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------- P3-UX (계약 esl_p3_ux.md §1~§3)
/** POST /uploads 파일 항목. rel = "rad/<상대경로>" 또는 "results/<상대경로>" */
export interface UploadFileIn {
  rel: string;
  size: number;
  sha256?: string | null;
  /** v0.6.0 §4.6: .h3d 에만. PC 도구가 보내는 압축 모드 메타(브라우저는 보내지 않음) */
  meta?: H3dMeta | null;
}
/** v0.6.0 계약 esl_upload_speed.md §4.6 결과 종류(openapi UploadResultKind) */
export interface UploadResultKind {
  type: string;
  layer?: string | null;
}
/** v0.6.0 계약 esl_upload_speed.md §4.6 h3d 업로드 메타(openapi UploadMeta) */
export interface UploadMeta {
  kind: "h3d_slim" | "h3d_original";
  v?: number;
  source_name?: string | null;
  source_bytes?: number | null;
  source_mtime?: string | null;
  /** 슬림 크기(= 파일 size) */
  slim_bytes?: number | null;
  hvtrans_sec?: number | null;
  hvtrans_version?: string | null;
  cfg?: string | null;
  cfg_sha256?: string | null;
  part_id?: number | null;
  part_title?: string | null;
  results?: UploadResultKind[] | null;
  frames?: "all" | null;
  tool_version?: string | null;
}
/** 화면용 별칭(응답의 meta·h3d_meta·input_h3d_meta 는 서버가 그대로 돌려준 UploadMeta) */
export type H3dMeta = UploadMeta;
export interface UploadCreate {
  project_id: string;
  name: string;
  files: UploadFileIn[];
  /** v0.6.0: 시작한 클라이언트(esl-web = 브라우저, esl-pc = PC 도구) — UploadOut.client 로 돌려준다 */
  client?: UploadClient | null;
}
export interface UploadClient {
  name: string;
  version: string;
}
/** UploadOut.client(없으면 null: 구 세션·client 미지정) */
export interface UploadClientOut {
  name: string;
  version: string;
}
export interface UploadChunkOut {
  index: number;
  /** 연속 앞부분 바이트 */
  received: number;
  /** v0.6.0 프로토콜 2: 받은 청크 바이트 합 */
  received_total?: number | null;
  chunk?: number | null;
  duplicate?: boolean;
  done: boolean;
  sha256?: string | null;
}
export interface UploadFileOut {
  index: number;
  rel: string;
  size: number;
  /** 연속 앞부분 바이트(프로토콜 1 의미 유지) */
  received: number;
  done: boolean;
  sha256?: string | null;
  sha256_expected?: string | null;
  /** v0.6.0 프로토콜 2 — 받은 바이트 합, 받은 청크 번호 범위 [a,b), 청크 수, 제거 여부, 메타 */
  received_total?: number;
  chunks?: [number, number][];
  n_chunks?: number;
  removed?: boolean;
  meta?: H3dMeta | null;
}
/** complete 검사 결과(UploadOut.result 에도 저장) */
export interface UploadCheckOut {
  ok: boolean;
  rad_path?: string | null;
  h3d_path?: string | null;
  results_dir?: string | null;
  parts?: RadPart[];
  missing_includes?: string[];
  problems?: string[];
  /** v0.6.0: h3d 파일의 업로드 메타(없으면 null) */
  h3d_meta?: H3dMeta | null;
  /** v0.8.0: rad include 중 이전 런 상태 파일(.sta/.str) */
  state_includes?: Record<string, unknown>[];
}
export interface StateInclude {
  rel: string | null;
  spec: string;
  kinds: ("geometry" | "initial")[];
  found: boolean;
}
export interface UploadCompleteOut extends UploadCheckOut {
  upload_id: string;
  state: "OPEN" | "COMPLETED";
}
export type UploadState = "OPEN" | "COMPLETED" | "CANCELED" | "STALE";
/** POST /uploads·GET /uploads/{id}·POST …/files·DELETE 응답 */
export interface UploadOut {
  upload_id: string;
  project_id: string;
  name: string;
  state: UploadState;
  dir_path: string;
  chunk_size: number;
  total_bytes: number;
  received_bytes: number;
  /** v0.6.0: 2 = 병렬·위치 지정 쓰기. 없거나 1 = 순차(구 서버·업그레이드 전 세션) */
  protocol?: 1 | 2;
  max_parallel?: number;
  /** v0.6.0: 마지막 complete 검사 문제 수(problems + missing_includes) */
  problems_count?: number;
  /** v0.6.0: 시작한 클라이언트 — esl-pc 면 'PC에서 올림', 아니면 '브라우저에서 올림' */
  client?: UploadClientOut | null;
  files: UploadFileOut[];
  result?: UploadCheckOut | null;
  backup_path?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}
export interface UploadFilesAdd {
  files: UploadFileIn[];
}
/** 하위 호환 별칭 */
export type CaseCreateP3 = CaseCreate;

/** POST /paths/inspect purpose H3D(자유 형식): 크기·헤더 검사 */
export interface InspectH3dResult {
  normalized_path: string;
  ok: boolean;
  problems: string[];
  size: number;
  mtime: number;
}

// ---------------------------------------------------------------- PC 연결 코드·토큰(§9.1, /client-tokens*)
export interface ClientCodeCreate {
  project_id: string;
}
export interface ClientCodeOut {
  code: string;
  project_id: string;
  expires_at: string;
}
export interface ClientExchange {
  code: string;
  device_name: string;
}
export interface ClientUser {
  user_id: string;
  username: string;
  display_name: string;
}
export interface ClientProject {
  id: string;
  name?: string | null;
}
export interface ClientExchangeOut {
  token: string;
  token_id: string;
  user: ClientUser;
  project: ClientProject;
  expires_at: string;
}
export type ClientTokenState = "ACTIVE" | "EXPIRED" | "REVOKED";
export interface ClientTokenOut {
  id: string;
  token_prefix: string;
  project_id: string;
  project_name?: string | null;
  device_name: string;
  user_id: string;
  username: string;
  created_at: string;
  expires_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
  state: ClientTokenState;
}
/** 서버 폴더 찾아보기(§1.2, §6). hint "h3d" = 서버 추출 입력 */
export type BrowseHint = "rad" | "results" | "h3d";
export interface BrowseRoot {
  index: number;
  label: string;
  path: string;
  kind: "input" | "upload" | "spdm";
  writable: boolean;
}
export interface BrowseEntry {
  name: string;
  type: "dir" | "file";
  size?: number | null;
  mtime: number;
  hint?: BrowseHint | null;
}
export interface BrowseOut {
  roots: BrowseRoot[];
  root?: number | null;
  /** 루트 기준 상대경로 */
  path: string;
  abs_path?: string | null;
  parent?: string | null;
  /** 지금 폴더 자체의 힌트(결과 폴더면 "results") */
  hint?: "results" | null;
  entries: BrowseEntry[];
  total: number;
  offset: number;
  limit: number;
  truncated: boolean;
}
/** GET /version */
export interface VersionOut {
  version: string;
  commit: string | null;
  built_at: string | null;
  /** v0.6.0: 공개 설정. upload_slim_hint_gb = 이 크기(GB) 초과 h3d 에 압축 모드 안내(0 = 끔, 없으면 5) */
  ui?: { upload_slim_hint_gb?: number; library_export_enabled?: boolean; library_export_max_entries?: number };
}
export type ChangelogSection = "추가" | "변경" | "수정";
/** GET /changelog 원소 */
export interface ChangelogEntry {
  version: string;
  date?: string | null;
  sections: Partial<Record<ChangelogSection, string[]>>;
}

// ---------------------------------------------------------------- v0.5.8 3D 하중 보기 (계약 esl_3d_load.md §3.6·§4)
export interface View3dValuesArray {
  /** fn(int16, N, 부호) · fmag(uint16, N) · u(int16×3, mm) · pa(uint16, 면압 |Fn|/A MPa — 사용자 결정 2026-10-28) */
  key: "fn" | "fmag" | "u" | "pa";
  dtype: "int16" | "uint16";
  comps: number;
  offset: number;
  scale: number | number[];
}
export interface View3dTopRow {
  rank: number;
  node_id: number;
  vertex: number;
  x: number;
  y: number;
  z: number;
  fx: number;
  fy: number;
  fz: number;
  mag: number;
  fn: number;
  /** 면압 |Fn|/A (MPa) */
  pa: number;
  is_support: boolean;
}
export interface View3dClusterRow {
  label: string;
  n_nodes: number;
  center: number[];
  u_center: number[];
  r: number[];
  r_mag: number;
  sum_abs: number;
  cancel: number;
  m: number[];
  m_mag: number;
  min_node_id: number;
}
export interface View3dCluster {
  k_actual: number;
  rows: View3dClusterRow[];
}
export interface View3dSupport {
  node_id: number;
  vertex: number;
  dof: string;
  x0: number[];
}
export interface View3dRange {
  max: number;
  p99?: number | null;
}
export interface View3dBBox {
  min: number[];
  max: number[];
  diag: number;
}
export interface View3dFile {
  name: string;
  bytes: number;
}
export interface View3dLod {
  name: string;
  bytes: number;
  n_vertices: number;
}
export interface View3dValues {
  name: string;
  bytes: number;
  arrays: View3dValuesArray[];
}
export interface View3dRanges {
  /** 면압 MPa (표면 색 기본 범위) */
  pa: View3dRange;
  fn_abs: View3dRange;
  fmag_max: number;
  u_max: number;
}
export interface View3dClusterSet {
  k_actual: number;
  rows: View3dClusterRow[];
}
/** GET /esl-runs/{id}/view3d — 파일 URL 은 API 루트 기준 경로(접두 /esl/api 없음) */
export interface View3dOut {
  schema: string;
  builder_version: number;
  key: string;
  esl_run_id: string;
  n_nodes: number;
  n_elems: number;
  n_tris: number;
  units: string;
  force_unit: string;
  pressure_unit: string;
  up: string;
  bbox: View3dBBox;
  plate_normal: number[];
  geometry: View3dFile;
  lod?: View3dLod | null;
  values: View3dValues;
  ranges: View3dRanges;
  sum_f: number[];
  sum_m: number[];
  moment_center: number[];
  supports: View3dSupport[];
  top: View3dTopRow[];
  clusters: Record<string, View3dClusterSet>;
  created_at: string;
  geometry_url: string;
  lod_url?: string | null;
  values_url: string;
}

// ---------------------------------------------------------------- v0.7.0 비드 최적화 서버 실행 (esl_opt_run.md §5.2)
// 기준 = 백엔드 openapi(components.schemas) — 인터페이스 이름 = 스키마 이름(check:api 대조). 자유 형식(dict) 필드는
// 백엔드 서비스(api/services/opt*.py)·코어(esl/opt/mesh_check.py·select.py·post.py)·워커(register.py) 실제 값 기준.
export type OptScenario = "S1" | "S2";
export type LoadStrategy = "A" | "B" | "C";
export type ObjectiveNorm = "abs" | "rel";
/** 사각형 기준 모서리: a0b0 좌하 · a1b0 우하 · a0b1 좌상 · a1b1 우상 (ξ 오른쪽, η 위) */
export type RectCorner = "a0b0" | "a1b0" | "a0b1" | "a1b1";

export interface OptMethodSource {
  title: string;
  authors?: string | null;
  url?: string | null;
  note?: string | null;
}
/** resources/opt_method_sources.json (§9.1) — 문구·링크 원본 1곳(파일을 못 읽으면 서버가 {error} 를 준다) */
export interface OptMethodSources {
  version: string;
  summary_ko: string[];
  strategies: Record<LoadStrategy, string>;
  objective_norms: Record<ObjectiveNorm, string>;
  sources: OptMethodSource[];
  error?: string;
}

export interface OptSizeSettings {
  tol_rel: number;
  plate_tol_rel: number;
  require_inch: boolean;
}
export interface OptBeadSettings {
  /** 경사(°) */
  angle: number;
  /** 최소 폭(mm) */
  min_width: number;
  /** 높이(mm) */
  height: number;
}
export type OptBead = OptBeadSettings;
export interface OptKeepoutAutoSettings {
  hole_radius_mm: number;
  edge_band_mm: number;
}
export interface OptLoadsSettings {
  default_objective_norm: ObjectiveNorm;
  default_strategy: LoadStrategy;
  mac_merge: number;
  max_cases: number;
  default_k: number;
}
export interface OptSettingsOut {
  enabled: boolean;
  solver_ready: boolean;
  solver_reason?: string | null;
  size: OptSizeSettings;
  bead_defaults: OptBeadSettings;
  keepout_auto: OptKeepoutAutoSettings;
  loads: OptLoadsSettings;
  method_sources: OptMethodSources;
  max_rects: number;
  max_entries: number;
  template_max_elems: number;
  template_ext: string[];
  max_preview_points: number;
}

export interface MeshPid {
  pid: number;
  title?: string | null;
  n_elems: number;
  thickness?: number | null;
  E?: number | null;
  nu?: number | null;
}
export type OptPid = MeshPid;
export interface SupportIn {
  node_id: number;
  /** 구속 자유도 문자열(예 "123") */
  dof: string;
}
export type OptSupport = SupportIn;
/** 검사 문제 1건(코어 mesh_check: {code, message}) */
export interface MeshIssue {
  code: string;
  message: string;
}
/** rad 파트 목록(코어 list_parts) */
export interface MeshPart {
  id: number;
  title: string;
  n_elems: number;
  [k: string]: unknown;
}

export interface MeshCheckOut {
  upload_id: string;
  ok: boolean;
  sha256: string;
  format?: "rad" | "fem" | null;
  file_name: string;
  parts?: MeshPart[];
  part_title?: string | null;
  mesh: { n_nodes: number; n_elems: number; n_quad: number; n_tria: number; unsupported: Record<string, number> };
  pids?: MeshPid[];
  frame: { L_xi: number | null; L_eta: number | null; z_range: number[] | null; warnings: string[] };
  quality: { errors: MeshIssue[]; warnings: MeshIssue[]; metrics: Record<string, unknown> };
  supports_auto?: SupportIn[];
}
export interface TemplateCheckIn {
  project_id: string;
  upload_id: string;
  part_title?: string | null;
}
export interface TemplateIn {
  project_id: string;
  upload_id: string;
  sha256: string;
  part_title?: string | null;
  title: string;
  inch?: number | null;
  description?: string | null;
}
export type TemplateStatus = "ACTIVE" | "ARCHIVED";
export interface TemplateOut {
  id: string;
  title: string;
  inch?: number | null;
  description: string;
  format: "rad" | "fem";
  file_name: string;
  part_title?: string | null;
  sha256: string;
  n_nodes: number;
  n_elems: number;
  L_xi: number;
  L_eta: number;
  /** [z_min, z_max] mm */
  z_range: number[];
  pids: MeshPid[];
  quality_warnings?: MeshIssue[];
  supports_auto?: SupportIn[];
  status: TemplateStatus;
  n_runs: number;
  created_by: string;
  created_by_name: string;
  created_at: string;
  archived_at?: string | null;
  can_delete: boolean;
}
export interface TemplateDeleteOut {
  deleted: boolean;
  archived: boolean;
}

export interface S1CheckIn {
  project_id: string;
  entry_ids: string[];
}
export interface S1Base {
  entry_id: string;
  case_id: string;
  case_title?: string | null;
  part_title?: string | null;
  rad_file_name?: string | null;
  n_nodes?: number | null;
  n_elems?: number | null;
  topo_sha256?: string | null;
  pids?: MeshPid[];
  supports?: SupportIn[];
}
export type S1CheckBase = S1Base;
/** reason(서버 _same_model_rows): TOPOLOGY(노드·요소 연결 다름) · MODEL_INFO_MISSING(모델 정보 없음) */
export interface S1EntryRow {
  entry_id: string;
  same_model: boolean;
  reason?: string | null;
}
export interface S1CheckOut {
  base: S1Base;
  entries: S1EntryRow[];
  /** v0.8.0 정보 경고 {code, message} (S1_BASE_CUMULATIVE) */
  warnings?: Record<string, unknown>[];
}

export type XY = [number, number];
export interface PlanViewFrame {
  /** mm */
  a_range: XY;
  b_range: XY;
}
export interface PlanViewElems {
  n_total: number;
  decimated: boolean;
  /** [a, b, pid] */
  points: [number, number, number][];
}
export type AutoKeepoutKind = "hole" | "edge";
export interface PlanViewAuto {
  hole_radius_mm: number;
  edge_band_mm: number;
  /** 자동 영역 경계 루프 — 같은 kind 끼리 evenodd 로 칠한다 */
  polygons: XY[][];
  /** polygons 와 같은 길이(구멍/가장자리). 길이가 다르면(구 캐시) 화면은 구분 없이 칠함 */
  kinds?: AutoKeepoutKind[];
  counts?: Record<string, number>;
}
export interface PlanViewOut {
  key: { template_id?: string | null; topo_sha256?: string | null };
  frame: PlanViewFrame;
  outline: XY[];
  holes: XY[][];
  elems: PlanViewElems;
  auto_keepout: PlanViewAuto;
  warnings?: string[];
}

export interface RectIn {
  name?: string | null;
  corner: string;
  x_mm: number;
  y_mm: number;
  w_mm: number;
  h_mm: number;
}
export interface KeepoutRectOut {
  name: string;
  corner: RectCorner;
  x_mm: number;
  y_mm: number;
  w_mm: number;
  h_mm: number;
}
/** 화면 편집 값(이름 필수·기준 모서리 4종) — 서버 RectIn 으로 그대로 보낼 수 있다 */
export type KeepoutRect = KeepoutRectOut;
export interface KeepoutAuto {
  hole?: boolean;
  edge?: boolean;
}
export interface KeepoutIn {
  rects?: RectIn[];
  auto?: KeepoutAuto;
}
export interface KeepoutSetIn {
  template_id?: string | null;
  topo_sha256?: string | null;
  /** 갱신 시 필수 */
  version?: number | null;
  rects?: RectIn[];
  auto?: KeepoutAuto;
}
export interface KeepoutSetOut {
  id: string;
  key: { template_id?: string | null; topo_sha256?: string | null };
  version: number;
  rects: KeepoutRectOut[];
  auto: { hole: boolean; edge: boolean };
  frame: { a_range: XY; b_range: XY };
  updated_by_name: string;
  updated_at: string;
  /** 저장 frame 과 현재 대상 경계 차이 등 */
  warnings?: string[];
}

export interface BeadIn {
  angle: number;
  min_width: number;
  height: number;
}
export interface OptDesignIn {
  nondesign_pids?: number[] | null;
  bead?: BeadIn | null;
  keepout?: KeepoutIn;
}
export interface OptOptionsIn {
  /** S2 만 */
  supports?: SupportIn[] | null;
  objective_norm?: ObjectiveNorm | null;
  load_strategy?: LoadStrategy | null;
  /** C 만, 1..max_cases */
  k?: number | null;
}
export type OptRunOptions = OptOptionsIn;
export interface OptRunIn {
  project_id: string;
  scenario: OptScenario;
  title?: string | null;
  entry_ids: string[];
  analysis_id?: string | null;
  template_id?: string | null;
  design?: OptDesignIn;
  options?: OptOptionsIn;
}

export type LoadRowStatus = "included" | "merged" | "cluster_rep" | "clustered" | "mode_rep" | "not_selected";
export interface LoadSelectionRow {
  entry_id: string;
  scene: string | null;
  mode: DeformMode | null;
  C0: number;
  /** 덱 DOBJREF POS 값: abs = C_ref, rel = C0 */
  pos: number | null;
  umax: number | null;
  status: LoadRowStatus;
  merged_into: string | null;
  mac_to_target: number | null;
  /** 병합 대상과 반대 방향이면 -1 */
  sign: 1 | -1 | null;
  cluster: number | null;
  /** 선정된 케이스 라벨 L01… */
  label: string | null;
  /** "C0<=0"(제외) 등 */
  note?: string | null;
}
export interface LoadSelection {
  strategy: LoadStrategy;
  objective_norm: ObjectiveNorm;
  C_ref: number | null;
  k: number | null;
  mac_merge: number | null;
  max_cases: number;
  n_selected_esl: number;
  n_cases: number;
  rows: LoadSelectionRow[];
  clusters: { id: number; rep_entry_id: string; members: string[]; min_mac: number }[];
  excluded_modes: DeformMode[];
  sources_ref: string | null;
  warnings?: string[];
}
export interface OptSubcase {
  label: string;
  entry_id: string;
  C0_self: number;
  C0_os: number | null;
  C_final: number | null;
  ratio: number | null;
}
/** OPT_REGISTER 뒤 opt_runs.result = opt.json(OptResult) + files + job_id */
export interface OptResult {
  load_selection: LoadSelection;
  objective_norm: ObjectiveNorm;
  C_ref: number | null;
  converged: boolean;
  iterations: number | null;
  desmax: number;
  objective: { initial: number | null; final: number | null; history: number[] };
  subcases: OptSubcase[];
  keepout: { n_elems_auto_hole: number; n_elems_auto_edge: number; n_elems_rects: number; n_design_elems: number };
  bead: { height_max: number | null; area_frac: number | null };
  normals_flipped?: number | null;
  normals_opposite?: number | null;
  solve: { seconds: number | null; license_waits: number; reused: boolean };
  warnings: string[];
  /** 결과 파일(실행 폴더 기준 상대 경로) */
  files?: { rel: string; size: number }[];
  job_id?: string;
}
/** OPT_LOAD 뒤·완료 전 opt_runs.result = {stage:"load", load_selection} */
export interface OptLoadStageResult {
  stage: "load";
  load_selection: LoadSelection;
}
export type OptRunResult = OptResult | OptLoadStageResult;
export const isFullResult = (r: OptRunResult | null | undefined): r is OptResult => !!r && !("stage" in r) && "objective" in r;

export interface OptRunOut {
  id: string;
  project_id: string;
  scenario: OptScenario;
  title?: string | null;
  entry_ids: string[];
  analysis_id?: string | null;
  /** S1: s1-check base 와 같은 모양(서버 경로 제외) */
  base?: S1Base | null;
  template_id?: string | null;
  /** S2: 템플릿 요약 */
  template?: Pick<TemplateOut, "id" | "title" | "status" | "inch" | "L_xi" | "L_eta" | "format" | "file_name" | "n_nodes" | "n_elems"> | null;
  size?: { entries?: unknown[]; template?: unknown; warnings?: string[] } | null;
  /** 실행 스냅샷 */
  design: { bead: BeadIn; nondesign_pids: number[]; keepout: { rects: KeepoutRect[]; auto: { hole: boolean; edge: boolean } } };
  options: { objective_norm: ObjectiveNorm; load_strategy: LoadStrategy; k: number | null; supports: SupportIn[] | null };
  load_strategy: LoadStrategy;
  k?: number | null;
  objective_norm: ObjectiveNorm;
  job_id?: string | null;
  job?: JobOut | null;
  /** 작업 상태(작업 없으면 "NONE") */
  state: JobState | "NONE";
  /** OPT_LOAD 뒤 부분 결과(stage "load"), 완료 뒤 OptResult — isFullResult 로 구분 */
  result?: OptRunResult | null;
  report_ready: boolean;
  dir_rel: string;
  folder_path: string;
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
}
export type OptFileKind = "report" | "result" | "selection" | "deck" | "solve" | "target" | "log" | "other";
export interface OptFileOut {
  rel: string;
  kind: OptFileKind;
  size: number;
  downloadable: boolean;
}

// ---------------------------------------------------------------- v0.9.0 비드 형상 DOE (esl_bead_doe.md §10.2)
// 인터페이스 이름 = 계약 스키마 이름(check:api 대조 — 백엔드 openapi 가 나오면 맞춤). 계약에 없는 보강 칸은 "(보강)" 표시.
export type DoeScenario = "same" | "mesh" | "step";
export type DoeMethod = "lhs" | "halton" | "fullfact";
export type DoePhase = "PREP" | "READY" | "PREVIEW" | "PREVIEW_READY" | "RUN" | "DONE" | "FAILED";
export type DoeParamType = "D" | "W" | "U" | "V";
/** 안 상태(§9.2) */
export type DoeDesignStatus =
  | "READY"
  | "RUNNING"
  | "OK"
  | "SKIPPED_COLLISION"
  | "SKIPPED_FIXED"
  | "SKIPPED_GEOM"
  | "FAILED_MORPH"
  | "FAILED_MESH"
  | "FAILED_SOLVE"
  | "CANCELED";
/** 경고·정보 1건(code 는 §6.3·§8.2·§10.3 코드, message 는 서버 resources/doe_messages.json 문구) */
export interface DoeWarning {
  code: string;
  message?: string | null;
  name?: string | null;
  [k: string]: unknown;
}
/** 방법·출처(원본 resources/doe_method_sources.json, GET /doe/settings.method_sources) */
export interface DoeMethodSources {
  version: string;
  summary_ko: string[];
  /** DOE 방식별 한 줄(lhs·halton·fullfact) */
  methods: Record<string, string>;
  /** 지표·민감도 설명(score·src·spearman 등, 선택) */
  metrics?: Record<string, string>;
  /** 한계(선형 비교·ESL 재분배 미반영 등, 선택) */
  limits?: string[];
  sources: OptMethodSource[];
  error?: string;
}
export interface DoeSettingsOut {
  enabled: boolean;
  /** 비활성 사유 코드(§6.5) */
  reason: string | null;
  paicad: { ready: boolean; version: string | null; pinned: string | null; warning: string | null };
  gmsh: { ready: boolean; version: string | null };
  scenarios: Record<DoeScenario, boolean>;
  max_entries: number;
  max_designs: number;
  doe: {
    methods: DoeMethod[];
    default_method: DoeMethod;
    default_n: number;
    seed: number;
    levels_default: number;
    levels_max: number;
    /** (보강) 기본 포함 변수 종류 — 설정 bead_doe.doe.default_types */
    default_types?: DoeParamType[];
  };
  mesh: { size_auto: boolean; size_min_mm: number; size_max_mm: number };
  boundary: { fastener_warn_mm: number; load_warn_mm: number; load_share_min: number };
  step_max_mb: number;
  /** (보강) ② B 메시 기본 파트 제목 — 설정 bead_doe.part_title */
  part_title?: string | null;
  method_sources: DoeMethodSources;
}
export interface DoeCheckIn {
  project_id: string;
  scenario: DoeScenario;
  entry_ids: string[];
  step_upload_id: string;
  mesh_upload_id?: string | null;
  part_title?: string | null;
  inch?: number | null;
}
export interface DoeProps {
  t: number;
  E: number;
  nu: number;
}
export interface DoeCheckOut {
  ok: boolean;
  step: { file_name: string; sha256: string; size_mb: number };
  base?: { entry_id: string; case_id: string; case_title?: string | null; part_title: string; n_nodes: number; n_elems: number; topo_sha256: string } | null;
  mesh?: MeshCheckOut | null;
  entries: { entry_id: string; ok: boolean; reason: string | null }[];
  size?: { L_xi: number; L_eta: number; inch: number | null; rel_xi: number; rel_eta: number } | null;
  props_default?: DoeProps | null;
  mesh_size_default_mm?: number | null;
  warnings: DoeWarning[];
}
export interface DoeStudyIn extends DoeCheckIn {
  title?: string | null;
  props?: DoeProps | null;
  mesh_size_mm?: number | null;
}
export interface DoeSpecParam {
  name: string;
  lo: number;
  hi: number;
}
export interface DoeSpec {
  method: DoeMethod;
  n?: number | null;
  levels?: number | null;
  seed?: number | null;
  params: DoeSpecParam[];
}
/** (보강) 미리보기 셀 1개 — 썸네일 격자 상태 배지용. 계약 preview 요약(ok·skipped)만으로는 안별 표시가 안 됨 */
export interface DoePreviewCell {
  id: string;
  values: Record<string, number>;
  status: DoeDesignStatus;
  /** paicad 원 코드(스킵·실패) */
  code?: string | null;
  /** 썸네일 있음(false = THUMB_UNAVAILABLE 회색) */
  thumb: boolean;
}
export interface DoePreviewOut {
  rev: number;
  matrix_sha256: string;
  ok: number;
  skipped: { collision: number; fixed: number; geom: number };
  cells?: DoePreviewCell[];
}
export interface DoeStudyOut {
  id: string;
  project_id: string;
  scenario: DoeScenario;
  title: string;
  entry_ids: string[];
  inputs: {
    step: { file_name: string; sha256: string };
    mesh?: { file_name: string; sha256: string } | null;
    part_title: string | null;
    inch: number | null;
    props?: DoeProps | null;
    mesh_size_mm?: number | null;
  };
  phase: DoePhase;
  version: number;
  prep: { n_beads: number; n_params: number; paicad_version: string | null; warnings: DoeWarning[]; boundary: { n_warn: number; n_info: number } } | null;
  doe: { rev: number; spec: DoeSpec; matrix_sha256: string; n_designs: number; preview: DoePreviewOut | null } | null;
  job: JobOut | null;
  result_ready: boolean;
  created_by_name: string;
  created_at: string;
}
export interface DoeBead {
  id: string;
  k: number;
  shape: "linear" | "circular" | string;
  sense: string;
  center_ab: XY;
  nominal: { depth: number; width: number; length?: number | null };
  fixed_overlap: boolean;
  png: string | null;
}
export interface DoeParam {
  name: string;
  type: DoeParamType;
  bead: string;
  nominal: number;
  feasible: XY;
  feasible_source: "estimate" | "sweep";
  default_range: XY;
  use_default: boolean;
  group_members: string[];
}
export interface DoeParamsOut {
  beads: DoeBead[];
  params: DoeParam[];
  warnings: DoeWarning[];
}
export interface DoePlanLink {
  from: string;
  to: string;
  d_mm: number;
  warn: boolean;
  /** (보강) 선 긋기용 좌표(B 평면 mm)·종류 */
  from_ab?: XY;
  to_ab?: XY;
  kind?: "fastener" | "load" | "support";
}
export interface DoePlanOut {
  frame: PlanViewFrame;
  outline: XY[];
  holes: XY[][];
  elems: PlanViewElems;
  beads: { id: string; ring: XY[] }[];
  fixed: { label: string; kind: string; a: number; b: number }[];
  a_points: { label: string; a: number; b: number }[];
  load_points: { entry_id: string; share: number; a: number; b: number }[];
  links: DoePlanLink[];
  warnings?: string[];
}
export interface DoeMatrixIn {
  version: number;
  spec: DoeSpec;
}
export interface DoeMatrixOut {
  spec: DoeSpec;
  matrix_sha256: string;
  designs: { id: string; values: Record<string, number> }[];
  n_designs: number;
  dropped_duplicates: number;
  warnings: DoeWarning[];
}
export interface DoeRunIn {
  version: number;
  matrix_sha256: string;
  solver?: "linear";
}
export interface DoeRankRow {
  rank: number;
  id: string;
  values: Record<string, number>;
  score: number;
  improvement: number;
  worst_entry_id: string;
  umax: number;
  epsmax: number;
  umax_all: number;
  epsmax_all: number;
  noise?: boolean;
  warnings_n: number;
  /** v0.10.0 §11.4 ESL별 개선 지표(r_i = C_안,i / C_베이스라인,i). v0.10.0 이전 결과엔 없음 */
  worst_ratio?: number | null;
  min_improvement?: number | null;
  all_improved?: boolean | null;
  n_improved?: number;
  n_worsened?: number;
  n_unchanged?: number;
  geo_mean_improvement?: number | null;
  pareto?: boolean;
  /** 결과의 per_esl_inline 이 true 일 때만(아니면 GET …/results/per-esl) */
  per_esl?: DoePerEsl[];
}
/** 안 1개 · ESL 1개의 컴플라이언스·베이스라인 대비 비율 */
export interface DoePerEsl {
  entry_id: string;
  label?: string | null;
  C: number;
  ratio: number;
  umax: number;
  epsmax: number;
}
export interface DoePerEslDesign {
  id: string;
  per_esl: DoePerEsl[];
}
/** GET /doe/studies/{id}/results/per-esl?design=… */
export interface DoePerEslOut {
  esl: { entry_id: string; label?: string | null }[];
  ratio_tol?: number | null;
  designs: DoePerEslDesign[];
}
/** (보강) 순위 밖 안(스킵·실패) — 순위표 아래 상태 배지 */
export interface DoeExcluded {
  id: string;
  status: DoeDesignStatus;
  code?: string | null;
  values: Record<string, number>;
}
export interface DoeSensParam {
  name: string;
  src: number;
  spearman: number;
  main_effects?: { level: number; mean: number }[];
}
export interface DoeFileOut {
  rel: string;
  size?: number;
  downloadable?: boolean;
}
export interface DoeResultOut {
  C_ref: number;
  baseline: { id: "d000"; score: number; umax: number; epsmax: number };
  n_ok: number;
  n_skipped: Record<string, number>;
  n_failed: Record<string, number>;
  ranking: DoeRankRow[];
  excluded?: DoeExcluded[];
  sensitivity: { method: string; r2: number; params: DoeSensParam[] } | null;
  boundary_warnings_n: number;
  view3d: string[];
  best: { id: string; files: DoeFileOut[] } | null;
  /** (보강) ③ 잡음 바닥(|개선율|) — §7.2 */
  noise_floor?: number | null;
  /** v0.10.0 §11.4: '변화 없음' 허용치(③ 은 max(설정, noise_floor)) */
  ratio_tol?: number | null;
  /** 순위 행에 per_esl 이 들어 있는가(안 수 × ESL 수 ≤ 설정 상한) */
  per_esl_inline?: boolean;
  /** ESL 열 순서·라벨 */
  esl?: { entry_id: string; label?: string | null }[];
  /** 서버 정렬 키(기본 score) */
  sort?: string;
  warnings: DoeWarning[];
}

// ---------------------------------------------------------------- v0.11.0 SCX 드라이브에서 고르기(계약 esl_scx_relay.md §7·§7.1 — 기능 A)
/** 기능별 사용 가능 여부(SR-D-19: 사유 판정은 서버 1곳) */
export interface Avail {
  enabled: boolean;
  reason_code: string | null;
  reason: string | null;
}
export interface ScxRootOut {
  key: string;
  label: string;
}
export interface ScxRelayOut {
  reachable: boolean;
  drive_state: string | null;
  queue_paused: boolean;
  writes_active: boolean;
  job_api: boolean;
  max_download_bytes: number | null;
  checked_at: string;
}
export interface ScxAdaptersOut {
  version: string | null;
  commit: string | null;
}
/** GET /scx/status?project_id= (항상 200 — 사유는 본문) */
export interface ScxStatusOut {
  fetch: Avail;
  verify: Avail;
  /** 이 프로젝트에 허용된 루트(scx_drive.roots)만 */
  roots: ScxRootOut[];
  relay: ScxRelayOut;
  adapters: ScxAdaptersOut;
}
/** §7.1 hint: *_0000.rad → rad, engine_globs → engine, .h3d → h3d, .inc·.k → include, .sta·.str → state */
export type ScxHint = "rad" | "engine" | "h3d" | "include" | "state";
export interface ScxBrowseEntry {
  name: string;
  kind: "dir" | "file";
  size: number | null;
  modified_at: string | null;
  hint: ScxHint | null;
}
/** GET /scx/browse?project_id=&root=&path=&offset=&limit= */
export interface ScxBrowseOut {
  root: string;
  /** 루트 기준 상대("" = 루트) */
  path: string;
  /** 표시 전용 경로(공용 계정 홈 기준) */
  display: string;
  entries: ScxBrowseEntry[];
  total: number;
  truncated: boolean;
}
/** POST /scx/fetches — rel 은 루트 기준, h3d 필수 */
export interface ScxFetchIn {
  project_id: string;
  name: string;
  root: string;
  rad_rel: string;
  h3d_rel: string;
}
/** 202: 업로드 세션(OPEN) + SCX_FETCH 작업 */
export interface ScxFetchOut {
  upload_id: string;
  job_id: string;
}
