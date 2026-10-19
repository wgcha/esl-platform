// 계약 esl_platform_p1b.md §3·§4(우선), esl.md §5(원형)를 손으로 옮긴 타입.
// 백엔드 OpenAPI가 생기면 scripts/check-api.mjs로 필드 이름을 대조한다.

export interface ApiErrorDetail {
  code: string;
  message: string;
  [k: string]: unknown;
}

export type Role = "general" | "power" | "admin";

export interface Me {
  user_id: string;
  username: string;
  display_name: string;
  is_global_admin: boolean;
  roles: Record<string, Role>; // project_id → 역할
}

export interface Project {
  id: string;
  name: string;
  product_name: string | null;
}

export type StageState = "none" | "running" | "done" | "stale" | "failed";
export type StageNo = 1 | 2 | 3 | 4 | 5 | 6;
export interface StageStatus {
  state: StageState;
  job_id?: string | null;
}

export type Metric = "max_strain" | "plastic_strain";

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
  source: string;
}

export interface ExtractSummary {
  n_nodes: number;
  n_elems: number;
  elem_types: Record<string, number>;
  n_frames: number;
  t_end: number;
  units_label: string;
  mat: MaterialSummary[];
}

export interface Case {
  id: string;
  project_id: string;
  folder_name: string;
  title: string;
  status: "ACTIVE" | "ARCHIVED";
  rad_path: string;
  results_dir: string;
  h3d_path: string | null;
  part_title: string;
  part_id: number | null;
  extract_summary: ExtractSummary | null;
  tstar: TStar | null;
  current_support_set_id: string | null;
  current_esl_run_id: string | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  version: number;
  /** GET /cases/{id}에만 */
  stage_status?: Record<string, StageStatus>;
  /** 결과 폴더 절대경로(표시·복사용). 계약 미기재 — 백엔드 확인 필요 */
  folder_path?: string;
}

export interface CaseCreate {
  project_id: string;
  folder_name: string;
  title: string;
  rad_path: string;
  results_dir: string;
  part_title?: string;
}

export interface InspectRadResult {
  normalized_path: string;
  ok: boolean;
  problems: string[];
  parts: { id: number; title: string; n_elems: number }[];
  includes: { path: string; ok: boolean }[];
  units_label?: string;
}

export interface InspectResultsResult {
  normalized_path?: string;
  ok: boolean;
  problems: string[];
  done: {
    ok: boolean;
    part_id: number | null;
    part_spec: string | null;
    candidate_frames: Partial<Record<Metric, number[]>>;
    hot_k: number | null;
    warnings: string[];
  };
  n_frames: number;
  files: string[];
}

export type JobType = "CASE_EXTRACT" | "ESL_SOLVE" | "VALIDATE" | "EXPORT";
export type JobState = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELED" | "INTERRUPTED";

export interface JobStep {
  step_no: number;
  step_key: string;
  state: string;
  progress_pct: number | null;
  exit_code: number | null;
  failure_code: string | null;
}

export interface JobSummary {
  id: string;
  case_id: string;
  case_title?: string;
  job_type: JobType;
  stage: number;
  lane: "SLOT" | "LIGHT";
  state: JobState;
  queue_seq: number | null;
  created_by_name: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  failure_code: string | null;
  failure_message?: string | null;
}

export interface Job extends JobSummary {
  params: Record<string, unknown>;
  steps: JobStep[];
}

export interface JobLog {
  lines: string[];
  next_cursor: string | null;
  eof: boolean;
}

export interface Queue {
  running: JobSummary | null;
  queued: JobSummary[];
  light: { running: JobSummary | null; queued: JobSummary[] };
}

export interface SystemStatus {
  config: { ok: boolean; errors: string[] };
  worker: { online: boolean; last_seen_at: string | null; limiter?: unknown };
  tools: { solver_backend: string; solver_backends_available: string[] };
}

export interface TstarCandidate {
  rank: number;
  frame_index: number;
  time: number;
  elem_id: number;
  value: number;
}

export interface TstarMetricBlock {
  tstar: { frame_index: number; time: number; elem_id: number; value: number };
  candidates: TstarCandidate[];
  history: { time: number[]; value: number[] };
}

export interface Hotspot {
  rank: number;
  elem_id: number;
  value: number;
  centroid: [number, number, number];
  rising: boolean;
}

export interface TstarView {
  selected: TStar | null;
  metrics: Partial<Record<Metric, TstarMetricBlock>>;
  hotspots: Hotspot[];
}

export interface Plane {
  origin: number[];
  e1: number[];
  e2: number[];
  n: number[];
}

export interface Preview {
  plane: Plane;
  /** [node_id, a, b, value] */
  points: [number, number, number, number][];
  decimated: boolean;
}

export interface SupportSuggest {
  node_ids: number[];
  dofs: string[];
  coords: number[][];
  plane: Plane;
  corners: number[][];
}

export interface SupportSet {
  id: string;
  case_id: string;
  node_ids: number[];
  dofs: string[];
  source: "auto" | "user";
  plane: Plane | null;
  created_by: string;
  created_at: string;
}

export interface EslRun {
  id: string;
  case_id: string;
  job_id: string;
  frame_index: number;
  time: number;
  support_set_id: string;
  kabsch: { rot_deg: number; rms_def: number; max_def: number };
  forces: {
    n_nodes_loaded: number;
    sum_f: number[];
    sum_m: number[];
    equilibrium_rel: number;
    max_f: { node_id: number; mag: number };
    noise: { force_rel: number; hotspot_strain_rel: number };
  };
  dir_rel: string;
  status: "READY" | "FAILED";
  created_at: string;
  stale: boolean;
  /** 최신 검증 id. 계약 미기재 — 백엔드 확인 필요 */
  latest_validation_id?: string | null;
}

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

export interface Validation {
  id: string;
  esl_run_id: string;
  job_id: string;
  disp_rms_rel: number;
  reaction_rel: number;
  hotspots: { elem_id: number; eps_rad: number; eps_val: number; rel_err: number }[];
  excluded: { elem_id: number; reason: string }[];
  verdict: "PASS" | "FAIL";
  fail_reasons: string[];
  criteria: Record<string, number>;
  dir_rel: string;
  created_at: string;
  stale: boolean;
}

export interface Artifact {
  id: string;
  kind: string;
  rel: string;
  size: number;
}

export type ExportTarget = "radioss_inc" | "fem" | "csv";
