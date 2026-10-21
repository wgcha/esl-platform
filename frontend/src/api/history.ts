// P3-이력 API(계약 esl_p3_history.md §3). check:api 가 endpoints.ts·p3.ts 와 함께 이 파일의 경로도 openapi 와 대조한다.
import { API_PREFIX, request } from "./client";
import type { JobOut, JobState, JobType, LogOut, StepOut } from "./types";

export type HistoryResultKind = "extract" | "esl_run" | "validation" | "export" | "report" | "analysis" | "comparison";

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
  result_ref: { kind: HistoryResultKind; id: string } | null;
  result_state: "current" | "past" | null;
  stale: boolean;
  /** 목록 한 줄용: 추출 {n_elems, tstar_frame, tstar_value} · ESL {frame_index, metric} · 검증 {verdict, disp_rms_rel} · 내보내기 {targets, n_files} */
  summary: Record<string, unknown> | null;
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

export interface ReviewStep extends StepOut {
  /** 전역 관리자에게만 */
  command?: string[];
}

export interface ReviewTiming {
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  wait_s: number | null;
  duration_s: number | null;
  steps: { step_no: number; step_key: string; started_at: string | null; finished_at: string | null; duration_s: number | null }[];
}

export interface ReviewDiff {
  key: string;
  label: string;
  past: unknown;
  current: unknown;
}

export interface ReviewResult {
  ref: { kind: HistoryResultKind; id: string } | null;
  availability: "full" | "summary" | "none";
  state: "current" | "past" | null;
  stale_reasons: string[];
  files_note: string | null;
  past: Record<string, unknown> | null;
  diff: ReviewDiff[];
  /** 화면 이동용 상대 경로: {stage, query:{run|val}} 또는 {path}(라이브러리) */
  links: { stage?: number; query?: Record<string, string>; path?: string } | null;
}

export interface ReviewOut {
  job: Omit<JobOut, "steps"> & { steps: ReviewStep[] };
  timing: ReviewTiming;
  input: {
    params: Record<string, unknown>;
    settings_summary?: Record<string, unknown> | null;
    input_fingerprint?: { kind: string; path: string; size: number; mtime: string }[] | null;
  };
  error: {
    failure_code?: string | null;
    failure_message?: string | null;
    failed_step?: { step_no: number; step_key: string; exit_code: number | null; failure_code: string | null; failure_message: string | null } | null;
    warnings: string[];
  };
  logs: { step_no: number; step_key: string; state: string; has_log: boolean; size: number }[];
  result: ReviewResult;
}

export interface HistoryFile {
  name: string;
  size: number;
  downloadable: boolean;
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
};

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
      return `${String(s.verdict ?? "–")} · 변위 RMS ${d === null ? "생략" : d.toExponential(1)}`;
    }
    case "EXPORT":
      return `${Array.isArray(s.targets) ? (s.targets as string[]).join("·") : "–"} · 파일 ${n("n_files") ?? "–"}개`;
    default:
      return "";
  }
}
