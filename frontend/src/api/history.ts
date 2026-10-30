// P3-이력 API(계약 esl_p3_history.md §3). check:api 가 endpoints.ts·p3.ts 와 함께 이 파일의 경로도 openapi 와 대조한다.
import { API_PREFIX, request } from "./client";
import { STEP_OF_STAGE } from "../shell/StageStepper";
import type { JobOut, JobState, JobType, LogOut, StepOut } from "./types";
import { PHASE_NAME, SCENARIO_NAME, SCENARIO_NO } from "./doe";

export type HistoryResultKind = "extract" | "esl_run" | "validation" | "export" | "report" | "analysis" | "comparison" | "opt_run";

export interface HistoryItem {
  id: string;
  job_type: JobType;
  stage: number;
  state: JobState;
  case_id: string | null;
  case_title: string | null;
  case_folder: string | null;
  analysis_id: string | null;
  comparison_id: string | null;
  /** v0.7.0 OPT_RUN 의 opt_runs.id(없는 서버면 키 없음) */
  opt_run_id?: string | null;
  subject_title: string | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  wait_s: number | null;
  current_step_no: number | null;
  progress_pct: number | null;
  failure_code: string | null;
  failure_message: string | null;
  retry_of_job_id: string | null;
  retried_by_job_id: string | null;
  result_ref?: HistoryRef | null;
  result_state?: "current" | "past" | null;
  stale: boolean;
  /** 목록 한 줄용: 추출 {n_elems, tstar_frame, tstar_value} · ESL {frame_index, metric} · 검증 {status, verdict, disp_rms_rel, disp_max_rel} · 내보내기 {targets, n_files} */
  summary?: Record<string, unknown> | null;
}

export interface HistoryPage {
  items: HistoryItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface HistoryQuery {
  project_id: string;
  case_id?: string;
  job_type?: string;
  state?: string;
  mine?: boolean;
  q?: string;
  from?: string;
  to?: string;
  cursor?: string | null;
  limit?: number;
}

export interface ReviewStepOut extends StepOut {
  /** 전역 관리자에게만 키가 나온다(그 외 응답에는 키 자체가 없음) */
  command?: string[] | null;
}

export interface ReviewJobOut extends JobOut {
  steps?: ReviewStepOut[] | null;
}

export interface ReviewStepTiming {
  step_no: number;
  step_key: string;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
}

export interface ReviewTiming {
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  /** 시작 전이면 null */
  wait_s: number | null;
  duration_s: number | null;
  steps: ReviewStepTiming[];
}

export interface ReviewFingerprint {
  kind: string;
  path?: string | null;
  size?: number | null;
  /** 에포크 초(실수) */
  mtime?: number | null;
}

export interface ReviewInput {
  params: Record<string, unknown>;
  /** {criteria:{…}, tstar_metric, material_override} */
  settings_summary: Record<string, unknown>;
  input_fingerprint?: ReviewFingerprint[] | null;
}

export interface ReviewFailedStep {
  step_no: number;
  step_key: string;
  exit_code?: number | null;
  failure_code?: string | null;
  failure_message?: string | null;
}

export interface ReviewError {
  failure_code?: string | null;
  failure_message?: string | null;
  failed_step?: ReviewFailedStep | null;
  /** 취소·성공 작업은 warnings 만 */
  warnings: unknown[];
}

export interface ReviewLog {
  step_no: number;
  step_key: string;
  state: string;
  has_log: boolean;
  size: number;
}

export interface DiffRow {
  key: string;
  label: string;
  past?: unknown;
  current?: unknown;
}
export type ReviewDiff = DiffRow;

export interface HistoryRef {
  kind: HistoryResultKind;
  id: string;
}

/** 화면 이동용: {stage, query?}. 1/4 run/5 val/6/7/8 analysis/9 comparison/10 opt_run — 8·9 는 라이브러리 화면, 10 은 최적화 상세 */
export interface ReviewLinks {
  stage?: number;
  query?: Record<string, string>;
}

export interface ReviewResult {
  ref?: HistoryRef | null;
  availability: "full" | "summary" | "none";
  state?: "current" | "past" | null;
  stale_reasons: string[];
  files_note?: string | null;
  /** 결과 없음이면 {} */
  past: Record<string, unknown>;
  diff: DiffRow[];
  /** 결과 없음이면 {} */
  links: ReviewLinks;
}

export interface ReviewOut {
  job: ReviewJobOut;
  timing: ReviewTiming;
  input: ReviewInput;
  error: ReviewError;
  logs: ReviewLog[];
  result: ReviewResult;
}

export interface HistoryFileOut {
  name: string;
  size: number;
  downloadable: boolean;
}
export type HistoryFile = HistoryFileOut;

/** 내보내기 결과 past.files 의 한 줄. 보존 파일이 없고 이름만 기록된 경우 size=null·downloadable=false */
export interface PastFile {
  name: string;
  size: number | null;
  downloadable: boolean;
}

/** links → 앱 경로. 8(analysis)·9(comparison)는 라이브러리 상세 화면. */
export function linkPath(projectId: string, caseId: string | null, l: ReviewLinks | null | undefined): string | null {
  if (!l || !l.stage) return null;
  const qs = new URLSearchParams(l.query ?? {});
  if (l.stage === 8 && qs.get("analysis")) return `/p/${projectId}/library/analyses/${qs.get("analysis")}`;
  if (l.stage === 9 && qs.get("comparison")) return `/p/${projectId}/library/comparisons/${qs.get("comparison")}`;
  if (l.stage === 10 && (qs.get("opt") ?? qs.get("opt_run"))) return `/p/${projectId}/opt/${qs.get("opt") ?? qs.get("opt_run")}`;
  if (l.stage === 11 && (qs.get("doe") ?? qs.get("bead_doe"))) return `/p/${projectId}/doe/${qs.get("doe") ?? qs.get("bead_doe")}`;
  if (!caseId || l.stage > 7) return null;
  const q = qs.toString();
  // v0.10.0(esl_menu_restructure.md §4.2): 서버 links.stage(옛 1..6) → 화면 단계 /step/1..4
  return `/p/${projectId}/c/${caseId}/step/${STEP_OF_STAGE[l.stage] ?? 1}${q ? `?${q}` : ""}`;
}

export const history = {
  list: (q: HistoryQuery) => request<HistoryPage>("GET", "/history", { query: { ...q } }),
  review: (jobId: string) => request<ReviewOut>("GET", `/jobs/${jobId}/review`),
  /** 기존 GET /jobs/{id}/log 에 step 을 붙여 step별 본문을 읽는다 */
  log: (jobId: string, step: number, cursor?: number | null) => request<LogOut>("GET", `/jobs/${jobId}/log`, { query: { step, cursor } }),
  files: (jobId: string) => request<HistoryFile[]>("GET", `/jobs/${jobId}/files`),
  fileUrl: (jobId: string, name: string) => `${API_PREFIX}/jobs/${jobId}/files/${encodeURIComponent(name)}/download`,
  reportUrl: (jobId: string) => `${API_PREFIX}/jobs/${jobId}/report`,
};

export const JOB_TYPE_LABEL: Record<JobType, string> = {
  CASE_EXTRACT: "추출",
  ESL_SOLVE: "ESL 계산",
  VALIDATE: "검증",
  EXPORT: "내보내기",
  CASE_REPORT: "보고서",
  LIB_ANALYZE: "종합분석",
  LIB_COMPARE: "버전 비교",
  OPT_RUN: "비드 최적화",
  DOE_PREP: "강성 평가 준비",
  DOE_PREVIEW: "강성 평가 미리보기",
  DOE_RUN: "강성 평가 실행",
  SCX_FETCH: "SCX 내려받기",
};

/** 단계(step_key) 한글 라벨 — v0.7.0 OPT_RUN 6단계(계약 esl_opt_run.md §6.1). 없는 키는 키 그대로 */
export const STEP_LABEL: Record<string, string> = {
  OPT_PREP: "대상 준비",
  OPT_LOAD: "하중·선정",
  OPT_DECK: "덱 생성",
  OS_SOLVE: "OptiStruct",
  OPT_POST: "후처리",
  OPT_REGISTER: "등록",
  // v0.9.0 비드 DOE(esl_bead_doe.md §9.1)
  BD_INPUT: "입력 검사",
  BD_MESH0: "베이스라인 메시",
  BD_GEOM: "형상 엔진",
  BD_LOADS: "하중·경계",
  BD_PREP_REGISTER: "등록",
  BD_MATRIX: "DOE 행렬",
  BD_GRID: "썸네일",
  BD_PREVIEW_REGISTER: "등록",
  BD_BASELINE: "베이스라인",
  BD_DESIGNS: "안별 해석",
  BD_POST: "순위·보고서",
  BD_REGISTER: "등록",
  // v0.11.0 SCX 드라이브에서 고르기(esl_scx_relay.md §8)
  SF_RAD: "rad·include 받기",
  SF_H3D: "h3d 받기",
  SF_REGISTER: "확인·등록",
};
/** 작업 종류별 단계 순서(대기열 응답에는 steps 가 없어 current_step_no → 키). 서버 core/job_types.py 와 같은 순서 */
export const JOB_STEP_KEYS: Partial<Record<JobType, string[]>> = {
  OPT_RUN: ["OPT_PREP", "OPT_LOAD", "OPT_DECK", "OS_SOLVE", "OPT_POST", "OPT_REGISTER"],
  DOE_PREP: ["BD_INPUT", "BD_MESH0", "BD_GEOM", "BD_LOADS", "BD_PREP_REGISTER"],
  DOE_PREVIEW: ["BD_MATRIX", "BD_GRID", "BD_PREVIEW_REGISTER"],
  DOE_RUN: ["BD_BASELINE", "BD_DESIGNS", "BD_POST", "BD_REGISTER"],
  SCX_FETCH: ["SF_RAD", "SF_H3D", "SF_REGISTER"],
};
export const stepLabel = (key: string | null | undefined) => (key ? STEP_LABEL[key] ?? key : "");
/** 실행 중 작업의 현재 단계 키(steps 가 있으면 그것, 없으면 JOB_STEP_KEYS 순서) */
export function currentStepKey(j: { job_type: JobType; current_step_no: number | null; steps?: { step_no: number; step_key: string }[] | null }): string | null {
  if (j.current_step_no == null) return null;
  return j.steps?.find((s) => s.step_no === j.current_step_no)?.step_key ?? JOB_STEP_KEYS[j.job_type]?.[j.current_step_no - 1] ?? null;
}

/** 상태 필터: 전체 / 성공 / 실패·중단 */
export const STATE_FILTERS = [
  { value: "", label: "전체" },
  { value: "SUCCEEDED", label: "성공" },
  { value: "FAILED,INTERRUPTED", label: "실패·중단" },
] as const;

/** 소요 시간 표기: 12초 · 3분 05초 · 1시간 02분 */
export function durText(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return "–";
  const t = Math.max(0, Math.round(s));
  if (t < 60) return `${t}초`;
  const p = (n: number) => String(n).padStart(2, "0");
  if (t < 3600) return `${Math.floor(t / 60)}분 ${p(t % 60)}초`;
  return `${Math.floor(t / 3600)}시간 ${p(Math.floor((t % 3600) / 60))}분`;
}

export const STALE_REASON_LABEL: Record<string, string> = {
  extract: "이후 다시 추출함",
  part_title: "대상 부품 이름이 바뀜",
  tstar: "t*(프레임·지표)가 바뀜",
  support_set: "지지점이 바뀜",
  input_files: "입력 파일(rad·h3d)이 바뀜",
};

/** 목록 한 줄 요약 */
/** 강성 평가 스터디(이전 이름 비드 DOE) 이력 요약 표기(연구 화면과 같은 이름 — api/doe.ts) */
const DOE_SCENARIO_LABEL: Record<string, string> = Object.fromEntries(Object.entries(SCENARIO_NAME).map(([k, v]) => [k, `${SCENARIO_NO[k as keyof typeof SCENARIO_NO]} ${v}`]));
const DOE_PHASE_LABEL: Record<string, string> = PHASE_NAME;

export function summaryText(it: HistoryItem): string {
  const s = it.summary;
  if (!s) return it.failure_code ?? "";
  const n = (k: string) => (typeof s[k] === "number" ? (s[k] as number) : null);
  switch (it.job_type) {
    case "CASE_EXTRACT":
      return `요소 ${n("n_elems")?.toLocaleString() ?? "–"} · t* 프레임 ${n("tstar_frame") ?? "–"}`;
    case "ESL_SOLVE":
      return `프레임 ${n("frame_index") ?? "–"} · ${String(s.metric ?? "–")}`;
    case "VALIDATE": {
      const d = n("disp_rms_rel");
      // v0.5.7: summary {status, verdict, disp_rms_rel, disp_max_rel} — status 가 있으면 판정 불가·이전 판정 체계도 구분해 보인다
      const st = typeof s.status === "string" ? s.status : null;
      const label = st === "UNDETERMINED" ? "판정 불가" : st === "LEGACY" ? `이전 판정 체계(당시 ${String(s.verdict ?? "–")})` : String(st ?? s.verdict ?? "–");
      return `${label} · 변위 RMS ${d === null ? "생략" : d.toExponential(1)}`;
    }
    case "EXPORT":
      // v0.10.0 §6.3: 라이브러리 다중 내보내기 summary {n_items, targets}
      if (n("n_items") !== null) return `내보내기(라이브러리) · ESL ${n("n_items")}개 · ${Array.isArray(s.targets) ? (s.targets as string[]).join("·") : "–"}`;
      return `${Array.isArray(s.targets) ? (s.targets as string[]).join("·") : "–"} · 파일 ${n("n_files") ?? "–"}개`;
    case "OPT_RUN":
      // v0.7.0: summary {scenario, load_strategy, n_cases, converged}
      return `${String(s.scenario ?? "–")} · 전략 ${String(s.load_strategy ?? "–")} · 케이스 ${n("n_cases") ?? "–"}${s.converged === false ? " · 미수렴" : ""}`;
    case "DOE_PREP":
    case "DOE_PREVIEW":
    case "DOE_RUN": {
      // v0.9.0: summary {scenario, phase} — 상세 화면(연구)과 같은 시나리오·단계 이름
      const scn = typeof s.scenario === "string" && s.scenario in DOE_SCENARIO_LABEL ? DOE_SCENARIO_LABEL[s.scenario] : String(s.scenario ?? "–");
      const ph = typeof s.phase === "string" && s.phase in DOE_PHASE_LABEL ? DOE_PHASE_LABEL[s.phase] : String(s.phase ?? "–");
      return `${scn} · ${ph}`;
    }
    default:
      return "";
  }
}
