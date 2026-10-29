// v0.10.0 ESL 라이브러리 API(계약 esl_menu_restructure.md §6·§7.3): 다중 내보내기 묶음 · 재검증.
// CaseOut·EntryOut 키는 types.ts, 이 파일은 새 엔드포인트의 요청·응답 타입과 호출만 둔다.
import { API_PREFIX, request } from "./client";
import type { ExportTarget, JobOut, JobState } from "./types";

export type ExportIdPolicy = "per_model_sequential" | "independent";

export interface ExportOptions {
  /** "auto" = 설정 export.radioss.id_offset, 정수 ≥ 0 = 지정 */
  id_offset: "auto" | number;
  id_policy?: ExportIdPolicy;
}

export interface ExportBatchCreate {
  project_id: string;
  entry_ids: string[];
  targets: ExportTarget[];
  options: ExportOptions;
}

export type ExportBatchState = "QUEUED" | "RUNNING" | "SUCCEEDED" | "PARTIAL" | "FAILED" | "CANCELED";
export type ExportItemState = "PENDING" | "DONE" | "FAILED";

export interface ExportBatchJob {
  job_id: string;
  case_id?: string | null;
  state: JobState;
  progress_pct?: number | null;
  failure_code?: string | null;
  failure_message?: string | null;
}

export interface ExportBatchFile {
  rel: string;
  size: number;
}

export interface ExportBundleInfo {
  ready: boolean;
  bytes?: number | null;
}

export interface ExportBatchItem {
  entry_id: string;
  label: string;
  case_id?: string | null;
  legacy?: boolean;
  state: ExportItemState;
  files?: ExportBatchFile[];
  /** [시작, 끝] ID(Radioss·fem, 양 끝 포함). 아직 없거나 Radioss·fem 대상이 없으면 null */
  id_range?: [number, number] | null;
  warnings?: string[];
  error?: { code: string; message: string } | null;
}

export interface ExportBatchOut {
  batch_id: string;
  project_id: string;
  created_by: string;
  created_by_name?: string | null;
  created_at?: string | null;
  targets: ExportTarget[];
  options: ExportOptions;
  state: ExportBatchState;
  jobs: ExportBatchJob[];
  items: ExportBatchItem[];
  bundle: ExportBundleInfo;
}

/** GET /library/exports 목록 한 줄(최근 묶음 요약 — 서버 ExportBatchSummary 그대로) */
export interface ExportBatchSummary {
  batch_id: string;
  project_id: string;
  created_by: string;
  created_by_name?: string | null;
  created_at?: string | null;
  state: ExportBatchState;
  targets?: ExportTarget[];
  n_items: number;
  job_ids?: string[];
}

/** 재검증 작업 결과(jobs.result.revalidate, §7.4 — 워커 register.revalidate_transition) */
export interface RevalidateResult {
  outcome: "PROMOTED" | "KEPT_LEGACY" | "ENTRY_CHANGED";
  /** 새 검증 판정 상태(PASS·FAIL·UNDETERMINED·LEGACY) */
  status?: string | null;
  /** 새 검증의 FAIL 사유 코드(예 DISP_MAX). PASS 면 빈 배열 */
  fail_reasons?: string[] | null;
  entry_id?: string | null;
  validation_id?: string | null;
  verdict?: string | null;
}

export const EXPORT_TERMINAL: ExportBatchState[] = ["SUCCEEDED", "PARTIAL", "FAILED", "CANCELED"];

export const library = {
  createExport: (body: ExportBatchCreate) => request<ExportBatchOut>("POST", "/library/exports", { body }),
  exportBatch: (batchId: string) => request<ExportBatchOut>("GET", `/library/exports/${batchId}`),
  exportBatches: (projectId: string, limit = 20) => request<ExportBatchSummary[]>("GET", "/library/exports", { query: { project_id: projectId, limit } }),
  exportBundleUrl: (batchId: string) => `${API_PREFIX}/library/exports/${batchId}/bundle`,
  revalidate: (entryId: string) => request<JobOut>("POST", `/library/entries/${entryId}/revalidate`, { body: {} }),
};

/** zip 파일 이름(서버 Content-Disposition 이 우선, 이것은 저장 대화상자 기본값) */
export function exportZipName(b: { created_at?: string | null; items: unknown[] } | { created_at?: string | null; n_items: number }) {
  const d = b.created_at ? new Date(b.created_at) : new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const n = "items" in b ? b.items.length : b.n_items;
  return `esl_export_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}_${n}.zip`;
}
