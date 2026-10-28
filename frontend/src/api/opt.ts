// v0.7.0 비드 최적화 서버 실행 API(계약 esl_opt_run.md §5). check:api 대상 — 백엔드 openapi 가 나오면 경로·스키마 대조.
import { API_PREFIX, request } from "./client";
import type {
  DeformMode, EntryOut, KeepoutSetIn, KeepoutSetOut, LoadRowStatus, LoadStrategy, MeshCheckOut, ObjectiveNorm, OptFileOut, OptRunIn, OptRunOut, OptScenario,
  OptSettingsOut, PlanViewOut, S1CheckIn, S1CheckOut, TemplateCheckIn, TemplateDeleteOut, TemplateIn, TemplateOut, TemplateStatus,
} from "./types";

export const opt = {
  settings: () => request<OptSettingsOut>("GET", "/opt/settings"),
  checkTemplate: (body: TemplateCheckIn) => request<MeshCheckOut>("POST", "/opt/templates/check", { body }),
  createTemplate: (body: TemplateIn) => request<TemplateOut>("POST", "/opt/templates", { body }),
  templates: (q: { status?: TemplateStatus; q?: string } = {}) => request<TemplateOut[]>("GET", "/opt/templates", { query: { ...q } }),
  template: (id: string) => request<TemplateOut>("GET", `/opt/templates/${id}`),
  deleteTemplate: (id: string) => request<TemplateDeleteOut>("DELETE", `/opt/templates/${id}`),
  s1Check: (body: S1CheckIn) => request<S1CheckOut>("POST", "/opt/s1-check", { body }),
  planView: (q: { template_id?: string; entry_id?: string }) => request<PlanViewOut>("GET", "/opt/plan-view", { query: { ...q } }),
  /** 세트 없음 = 404 KEEPOUT_NOT_FOUND(화면은 빈 세트) */
  keepouts: (q: { template_id?: string; topo?: string }) => request<KeepoutSetOut>("GET", "/opt/keepouts", { query: { ...q } }),
  putKeepouts: (body: KeepoutSetIn) => request<KeepoutSetOut>("PUT", "/opt/keepouts", { body }),
  createRun: (body: OptRunIn) => request<OptRunOut>("POST", "/opt/runs", { body }),
  runs: (q: { project_id: string; scenario?: OptScenario }) => request<OptRunOut[]>("GET", "/opt/runs", { query: { ...q } }),
  run: (id: string) => request<OptRunOut>("GET", `/opt/runs/${id}`),
  runFiles: (id: string) => request<OptFileOut[]>("GET", `/opt/runs/${id}/files`),
  downloadUrl: (id: string, rel: string) => `${API_PREFIX}/opt/runs/${id}/download` + `?rel=${encodeURIComponent(rel)}`,
  bundleUrl: (id: string, parts = "post,report,load") => `${API_PREFIX}/opt/runs/${id}/bundle` + `?parts=${encodeURIComponent(parts)}`,
  reportUrl: (id: string) => `${API_PREFIX}/opt/runs/${id}/report`,
  beadMapUrl: (id: string) => `${API_PREFIX}/opt/runs/${id}/bead-map.png`,
};

// ---------------------------------------------------------------- 표기
export const MODE_LABEL: Record<DeformMode, string> = { dent: "덴팅", twist: "뒤틀림", bend: "굽힘" };
export const MODES: DeformMode[] = ["dent", "twist", "bend"];
export const SCENARIO_LABEL: Record<OptScenario, string> = { S1: "기존 형상", S2: "템플릿" };
export const STRATEGY_NAME: Record<LoadStrategy, string> = { A: "A 전부 넣기", B: "B 모드별 최악", C: "C 군집 대표 k개" };
export const NORM_NAME: Record<ObjectiveNorm, string> = { abs: "절대", rel: "상대" };
export const ROW_STATUS_LABEL: Record<LoadRowStatus, string> = {
  included: "포함",
  merged: "병합됨",
  cluster_rep: "군집 대표",
  clustered: "군집 멤버",
  mode_rep: "모드 대표",
  not_selected: "미선정",
};
/** 선정되어 덱 subcase 가 되는 상태 */
export const SELECTED_STATUS: LoadRowStatus[] = ["included", "cluster_rep", "mode_rep"];
export const MISMATCH_REASON: Record<string, string> = {
  NODE_IDS: "노드 ID 다름",
  CONNECTIVITY: "요소 연결 다름",
  COORDS: "좌표 다름",
  NO_TOPO: "모델 정보 없음",
};

/** 지수 표기 3자리: 1.23e4 */
export const sci = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "–" : v.toExponential(2).replace("e+", "e"));

export const optPath = (projectId: string, id?: string) => `/p/${projectId}/opt/${id ?? "new"}`;

// ---------------------------------------------------------------- 크기 규칙(§7.1, OR-D-7) — 화면 검사(서버도 같은 규칙으로 422)
export interface SizeOf {
  inch: number | null;
  L_xi: number | null;
  L_eta: number | null;
}
export const sizeOf = (e: EntryOut): SizeOf => ({ inch: e.size?.inch ?? e.model.inch ?? null, L_xi: e.size?.L_xi ?? null, L_eta: e.size?.L_eta ?? null });

const relDiff = (a: number, b: number) => Math.abs(a - b) / Math.max(Math.abs(b), 1e-12);

/** ESL 간 같은 크기: 같은 인치(양쪽 있을 때) AND L_xi·L_eta ≤ tol */
export function sameSize(a: SizeOf, base: SizeOf, tol: number): boolean {
  if (a.inch != null && base.inch != null && a.inch !== base.inch) return false;
  if (a.L_xi == null || a.L_eta == null || base.L_xi == null || base.L_eta == null) return a.inch != null && a.inch === base.inch && a.L_xi == null && base.L_xi == null;
  return relDiff(a.L_xi, base.L_xi) <= tol && relDiff(a.L_eta, base.L_eta) <= tol;
}

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

/** 템플릿 ↔ ESL 치수 중앙값 ≤ plate_tol, 템플릿 인치는 있으면 같아야 함. 반환 = null(맞음) 또는 사유 */
export function templateMismatch(t: Pick<TemplateOut, "inch" | "L_xi" | "L_eta">, sizes: SizeOf[], plateTol: number): string | null {
  const xs = sizes.map((s) => s.L_xi).filter((v): v is number => v != null);
  const ys = sizes.map((s) => s.L_eta).filter((v): v is number => v != null);
  if (!xs.length || !ys.length) return "ESL 크기 정보 없음";
  const inch = sizes.find((s) => s.inch != null)?.inch ?? null;
  if (t.inch != null && inch != null && t.inch !== inch) return `인치 다름(${t.inch}형 ↔ ESL ${inch}형)`;
  const dx = relDiff(t.L_xi, median(xs));
  const dy = relDiff(t.L_eta, median(ys));
  if (dx > plateTol || dy > plateTol) return `크기 차 ${(Math.max(dx, dy) * 100).toFixed(1)}% > ${(plateTol * 100).toFixed(0)}%`;
  return null;
}

export const sizeText = (s: SizeOf) => `${s.inch != null ? `${s.inch}형 ` : ""}${s.L_xi != null && s.L_eta != null ? `${Math.round(s.L_xi)}×${Math.round(s.L_eta)}` : "크기 ?"}`;
