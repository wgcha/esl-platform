import { request, API_PREFIX } from "./client";
import type {
  Artifact, Case, CaseCreate, EslRun, ExportTarget, ForceRow, InspectRadResult, InspectResultsResult, Job, JobLog,
  JobType, Me, Metric, Preview, Project, Queue, SupportSet, SupportSuggest, SystemStatus, TstarView, Validation,
} from "./types";

export const api = {
  me: () => request<Me>("GET", "/me"),
  projects: () => request<Project[]>("GET", "/projects"),
  status: () => request<SystemStatus>("GET", "/status"),
  queue: () => request<Queue>("GET", "/queue"),
  inspectRad: (path: string) => request<InspectRadResult>("POST", "/paths/inspect", { body: { purpose: "RAD", path } }),
  inspectResults: (path: string) =>
    request<InspectResultsResult>("POST", "/paths/inspect", { body: { purpose: "RESULTS", path } }),
  cases: (projectId: string) => request<Case[]>("GET", "/cases", { query: { project_id: projectId, status: "ACTIVE" } }),
  createCase: (body: CaseCreate) => request<Case>("POST", "/cases", { body }),
  getCase: (id: string) => request<Case>("GET", `/cases/${id}`),
  patchCase: (id: string, body: { version: number; title?: string; part_title?: string }) =>
    request<Case>("PATCH", `/cases/${id}`, { body }),
  createJob: (caseId: string, job_type: JobType, params: Record<string, unknown> = {}) =>
    request<Job>("POST", `/cases/${caseId}/jobs`, { body: { job_type, params } }),
  getJob: (id: string) => request<Job>("GET", `/jobs/${id}`),
  jobLog: (id: string, cursor?: string | null) => request<JobLog>("GET", `/jobs/${id}/log`, { query: { cursor } }),
  tstar: (caseId: string) => request<TstarView>("GET", `/cases/${caseId}/tstar`),
  putTstar: (caseId: string, body: { version: number; metric: Metric; frame_index: number }) =>
    request<Case>("PUT", `/cases/${caseId}/tstar`, { body }),
  preview: (caseId: string, frameIndex?: number) =>
    request<Preview>("GET", `/cases/${caseId}/preview`, { query: { frame_index: frameIndex } }),
  suggestSupport: (caseId: string) => request<SupportSuggest>("POST", `/cases/${caseId}/support-sets/suggest`, { body: {} }),
  createSupport: (caseId: string, node_ids: number[]) =>
    request<SupportSet>("POST", `/cases/${caseId}/support-sets`, { body: { node_ids } }),
  supportSets: (caseId: string) => request<SupportSet[]>("GET", `/cases/${caseId}/support-sets`),
  eslRun: (id: string) => request<EslRun>("GET", `/esl-runs/${id}`),
  forces: (id: string, top = 50) => request<{ rows: ForceRow[] }>("GET", `/esl-runs/${id}/forces`, { query: { top } }),
  validation: (id: string) => request<Validation>("GET", `/validations/${id}`),
  artifacts: (caseId: string) => request<Artifact[]>("GET", `/cases/${caseId}/artifacts`),
  downloadUrl: (artifactId: string) => `${API_PREFIX}/artifacts/${artifactId}/download`,
  exportJob: (caseId: string, esl_run_id: string, targets: ExportTarget[]) =>
    request<Job>("POST", `/cases/${caseId}/jobs`, { body: { job_type: "EXPORT", params: { esl_run_id, targets } } }),
};
