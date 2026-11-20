import { request, API_PREFIX } from "./client";
import type {
  AnalysisCreate, AnalysisFileOut, DeleteCheckOut, DeleteOut, AnalysisOut, ComparisonCreate, DispFieldOut, DispLayer, ComparisonOut, EntryCreate, EntryOut, EntryPatch, EntryQuery, FieldLayer, FieldOut, SectionAxis,
  SectionOut,
  ArtifactOut, CaseCreate, CaseOut, EslRunOut, ExportTarget, ForcesOut, InspectH3dResult, InspectRadResult, InspectResultsResult, JobOut,
  JobType, LogOut, Me, Metric, Preview, Project, QueueOut, StatusOut, SupportSetOut, SupportSuggestOut, TstarView,
  ValidationOut, ValidationSourcesHistOut, ValidationSourcesOut, View3dOut, View3dReconOut, View3dSourcesOut,
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
  /** v0.15.1 opt.step·tail(끝부분, 화면 '로그 보기') */
  jobLog: (id: string, cursor?: number | null, opt?: { step?: number | null; tail?: boolean }) =>
    request<LogOut>("GET", `/jobs/${id}/log`, { query: { cursor, step: opt?.step ?? undefined, tail: opt?.tail ? "true" : undefined } }),
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
  /** v0.5.8: 3D 하중 보기 manifest(상위 100행·군집·지지·범위). 파일은 view3dFile 로 받는다 */
  view3d: (id: string, src?: string) => request<View3dOut>("GET", `/esl-runs/${id}/view3d`, src ? { query: { src } } : {}),
  /** v0.24.1: 하중 출처 목록(행마다 가능 여부·응답 가능·사유) — manifest 와 별도 경로(EslRunOut 불변) */
  view3dSources: (id: string) => request<View3dSourcesOut>("GET", `/esl-runs/${id}/view3d/sources`),
  /** v0.24.1: 재현(목표·재현·오차) 진단 — 첫 요청이 파생 캐시를 만든다. src 없음 = 전 노드(legacy) */
  view3dRecon: (id: string, src?: string) => request<View3dReconOut>("GET", `/esl-runs/${id}/view3d/recon`, src ? { query: { src } } : {}),
  validations: (caseId: string) => request<ValidationOut[]>("GET", `/cases/${caseId}/validations`),
  /** v0.24.3: src(legacy 가 아닌 출처 키) 없음 = 옛 URL 그대로 */
  validation: (id: string, src?: string) => request<ValidationOut>("GET", `/validations/${id}`, src ? { query: { src } } : {}),
  /** v0.24.3: ④ 검증 출처별 판정·조건·한계 행 */
  validationSources: (id: string) => request<ValidationSourcesOut>("GET", `/validations/${id}/sources`),
  validationsSources: (caseId: string) => request<ValidationSourcesHistOut>("GET", `/cases/${caseId}/validations/sources`),
  artifacts: (caseId: string) => request<ArtifactOut[]>("GET", `/cases/${caseId}/artifacts`),
  downloadUrl: (artifactId: string) => `${API_PREFIX}/artifacts/${artifactId}/download`,
  exportJob: (caseId: string, esl_run_id: string, targets: ExportTarget[]) =>
    request<JobOut>("POST", `/cases/${caseId}/jobs`, { body: { job_type: "EXPORT", params: { esl_run_id, targets } } }),

  // ---- P2 (계약 esl_p2_library.md §11)
  field: (vid: string, layer: FieldLayer, maxPoints?: number, src?: string) =>
    request<FieldOut>("GET", `/validations/${vid}/field`, { query: { layer, max_points: maxPoints, src } }),
  /** v0.5.7(esl_disp_primary §7): 변위 전 노드 컨투어. full_solve 미수행·LEGACY 는 409 PREREQUISITE_MISSING(missing: disp_compare) */
  dispField: (vid: string, layer: DispLayer, maxPoints?: number, src?: string) =>
    request<DispFieldOut>("GET", `/validations/${vid}/disp-field`, { query: { layer, max_points: maxPoints, src } }),
  /** axis 기본 eta(길이 방향 단면), at = 고정 좌표의 0~1 정규화 위치 */
  section: (vid: string, axis: SectionAxis = "eta", at = 0.5, src?: string) =>
    request<SectionOut>("GET", `/validations/${vid}/section`, { query: { axis, at, src } }),
  caseReportUrl: (caseId: string) => `${API_PREFIX}/cases/${caseId}/report`,
  libraryEntries: (q: EntryQuery) => request<EntryOut[]>("GET", "/library/entries", { query: { ...q } }),
  libraryEntry: (id: string) => request<EntryOut>("GET", `/library/entries/${id}`),
  createEntry: (body: EntryCreate) => request<EntryOut>("POST", "/library/entries", { body }),
  patchEntry: (id: string, body: EntryPatch) => request<EntryOut>("PATCH", `/library/entries/${id}`, { body }),
  retireEntry: (id: string, reason?: string) => request<EntryOut>("POST", `/library/entries/${id}/retire`, { body: { reason: reason ?? null } }),
  analyses: (projectId: string) => request<AnalysisOut[]>("GET", "/library/analyses", { query: { project_id: projectId } }),
  createAnalysis: (body: AnalysisCreate) => request<AnalysisOut>("POST", "/library/analyses", { body }),
  analysis: (id: string) => request<AnalysisOut>("GET", `/library/analyses/${id}`),
  analysisDeleteCheck: (id: string) => request<DeleteCheckOut>("GET", `/library/analyses/${id}/delete-check`),
  deleteAnalysis: (id: string) => request<DeleteOut>("DELETE", `/library/analyses/${id}`),
  analysisFiles: (id: string) => request<AnalysisFileOut[]>("GET", `/library/analyses/${id}/files`),
  analysisReportUrl: (id: string) => `${API_PREFIX}/library/analyses/${id}/report`,
  analysisDownloadUrl: (id: string, rel: string) => `${API_PREFIX}/library/analyses/${id}/download` + `?rel=${encodeURIComponent(rel)}`,
  // ---- 설계 버전 비교(§12.2)
  comparisons: (projectId: string) => request<ComparisonOut[]>("GET", "/library/comparisons", { query: { project_id: projectId } }),
  createComparison: (body: ComparisonCreate) => request<ComparisonOut>("POST", "/library/comparisons", { body }),
  comparison: (id: string) => request<ComparisonOut>("GET", `/library/comparisons/${id}`),
  comparisonDeleteCheck: (id: string) => request<DeleteCheckOut>("GET", `/library/comparisons/${id}/delete-check`),
  deleteComparison: (id: string) => request<DeleteOut>("DELETE", `/library/comparisons/${id}`),
  comparisonReportUrl: (id: string) => `${API_PREFIX}/library/comparisons/${id}/report`,
};
