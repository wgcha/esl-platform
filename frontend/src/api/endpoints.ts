import { request, API_PREFIX } from "./client";
import type {
  AnalysisCreate, AnalysisFileOut, AnalysisOut, ComparisonCreate, DispFieldOut, DispLayer, ComparisonOut, EntryCreate, EntryOut, EntryPatch, EntryQuery, FieldLayer, FieldOut, SectionAxis,
  SectionOut,
  ArtifactOut, CaseCreate, CaseOut, EslRunOut, ExportTarget, ForcesOut, InspectH3dResult, InspectRadResult, InspectResultsResult, JobOut,
  JobType, LogOut, Me, Metric, Preview, Project, QueueOut, StatusOut, SupportSetOut, SupportSuggestOut, TstarView,
  ValidationOut,
} from "./types";

export const api = {
  me: () => request<Me>("GET", "/me"),
  projects: () => request<Project[]>("GET", "/projects"),
  status: () => request<StatusOut>("GET", "/status"),
  queue: () => request<QueueOut>("GET", "/queue"),
  inspectRad: (path: string, partTitle?: string) =>
    request<InspectRadResult>("POST", "/paths/inspect", { body: { purpose: "RAD", path, ...(partTitle?.trim() ? { part_title: partTitle.trim() } : {}) } }),
  inspectResults: (path: string) =>
    request<InspectResultsResult>("POST", "/paths/inspect", { body: { purpose: "RESULTS", path } }),
  /** §6: h3d 파일 가벼운 검사(크기·헤더) */
  inspectH3d: (path: string) => request<InspectH3dResult>("POST", "/paths/inspect", { body: { purpose: "H3D", path } }),
  cases: (projectId: string) => request<CaseOut[]>("GET", "/cases", { query: { project_id: projectId, status: "ACTIVE" } }),
  createCase: (body: CaseCreate) => request<CaseOut>("POST", "/cases", { body }),
  getCase: (id: string) => request<CaseOut>("GET", `/cases/${id}`),
  patchCase: (id: string, body: { version: number; title?: string; part_title?: string }) =>
    request<CaseOut>("PATCH", `/cases/${id}`, { body }),
  createJob: (caseId: string, job_type: JobType, params: Record<string, unknown> = {}) =>
    request<JobOut>("POST", `/cases/${caseId}/jobs`, { body: { job_type, params } }),
  caseJobs: (caseId: string) => request<JobOut[]>("GET", `/cases/${caseId}/jobs`),
  getJob: (id: string) => request<JobOut>("GET", `/jobs/${id}`),
  cancelJob: (id: string) => request<JobOut>("POST", `/jobs/${id}/cancel`),
  retryJob: (id: string) => request<JobOut>("POST", `/jobs/${id}/retry`),
  jobLog: (id: string, cursor?: number | null) => request<LogOut>("GET", `/jobs/${id}/log`, { query: { cursor } }),
  tstar: (caseId: string) => request<TstarView>("GET", `/cases/${caseId}/tstar`),
  putTstar: (caseId: string, body: { version: number; metric: Metric; frame_index: number }) =>
    request<CaseOut>("PUT", `/cases/${caseId}/tstar`, { body }),
  preview: (caseId: string, frameIndex?: number) =>
    request<Preview>("GET", `/cases/${caseId}/preview`, { query: { frame_index: frameIndex } }),
  suggestSupport: (caseId: string) => request<SupportSuggestOut>("POST", `/cases/${caseId}/support-sets/suggest`, { body: {} }),
  createSupport: (caseId: string, node_ids: number[]) =>
    request<SupportSetOut>("POST", `/cases/${caseId}/support-sets`, { body: { node_ids } }),
  supportSets: (caseId: string) => request<SupportSetOut[]>("GET", `/cases/${caseId}/support-sets`),
  eslRuns: (caseId: string) => request<EslRunOut[]>("GET", `/cases/${caseId}/esl-runs`),
  eslRun: (id: string) => request<EslRunOut>("GET", `/esl-runs/${id}`),
  forces: (id: string, top = 50) => request<ForcesOut>("GET", `/esl-runs/${id}/forces`, { query: { top } }),
  validations: (caseId: string) => request<ValidationOut[]>("GET", `/cases/${caseId}/validations`),
  validation: (id: string) => request<ValidationOut>("GET", `/validations/${id}`),
  artifacts: (caseId: string) => request<ArtifactOut[]>("GET", `/cases/${caseId}/artifacts`),
  downloadUrl: (artifactId: string) => `${API_PREFIX}/artifacts/${artifactId}/download`,
  exportJob: (caseId: string, esl_run_id: string, targets: ExportTarget[]) =>
    request<JobOut>("POST", `/cases/${caseId}/jobs`, { body: { job_type: "EXPORT", params: { esl_run_id, targets } } }),

  // ---- P2 (계약 esl_p2_library.md §11)
  field: (vid: string, layer: FieldLayer, maxPoints?: number) =>
    request<FieldOut>("GET", `/validations/${vid}/field`, { query: { layer, max_points: maxPoints } }),
  /** v0.5.7(esl_disp_primary §7): 변위 전 노드 컨투어. full_solve 미수행·LEGACY 는 409 PREREQUISITE_MISSING(missing: disp_compare) */
  dispField: (vid: string, layer: DispLayer, maxPoints?: number) =>
    request<DispFieldOut>("GET", `/validations/${vid}/disp-field`, { query: { layer, max_points: maxPoints } }),
  /** axis 기본 eta(길이 방향 단면), at = 고정 좌표의 0~1 정규화 위치 */
  section: (vid: string, axis: SectionAxis = "eta", at = 0.5) => request<SectionOut>("GET", `/validations/${vid}/section`, { query: { axis, at } }),
  caseReportUrl: (caseId: string) => `${API_PREFIX}/cases/${caseId}/report`,
  libraryEntries: (q: EntryQuery) => request<EntryOut[]>("GET", "/library/entries", { query: { ...q } }),
  createEntry: (body: EntryCreate) => request<EntryOut>("POST", "/library/entries", { body }),
  patchEntry: (id: string, body: EntryPatch) => request<EntryOut>("PATCH", `/library/entries/${id}`, { body }),
  retireEntry: (id: string, reason?: string) => request<EntryOut>("POST", `/library/entries/${id}/retire`, { body: { reason: reason ?? null } }),
  analyses: (projectId: string) => request<AnalysisOut[]>("GET", "/library/analyses", { query: { project_id: projectId } }),
  createAnalysis: (body: AnalysisCreate) => request<AnalysisOut>("POST", "/library/analyses", { body }),
  analysis: (id: string) => request<AnalysisOut>("GET", `/library/analyses/${id}`),
  analysisFiles: (id: string) => request<AnalysisFileOut[]>("GET", `/library/analyses/${id}/files`),
  analysisReportUrl: (id: string) => `${API_PREFIX}/library/analyses/${id}/report`,
  analysisDownloadUrl: (id: string, rel: string) => `${API_PREFIX}/library/analyses/${id}/download` + `?rel=${encodeURIComponent(rel)}`,
  // ---- 설계 버전 비교(§12.2)
  comparisons: (projectId: string) => request<ComparisonOut[]>("GET", "/library/comparisons", { query: { project_id: projectId } }),
  createComparison: (body: ComparisonCreate) => request<ComparisonOut>("POST", "/library/comparisons", { body }),
  comparison: (id: string) => request<ComparisonOut>("GET", `/library/comparisons/${id}`),
  comparisonReportUrl: (id: string) => `${API_PREFIX}/library/comparisons/${id}/report`,
};
