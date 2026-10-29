// v0.7.0 비드 최적화 서버 실행 API(계약 esl_opt_run.md §5). check:api 대상 — 백엔드 openapi 가 나오면 경로·스키마 대조.
import { API_PREFIX, request } from "./client";
import type {
  DeformMode, EntryOut, KeepoutSetIn, KeepoutSetOut, LoadRowStatus, LoadStrategy, MeshCheckOut, ObjectiveNorm, OptFileOut, OptMethodSources, OptRunIn, OptRunOut, OptScenario,
  OptSettingsOut, PlanViewOut, S1CheckIn, S1CheckOut, TemplateCheckIn, TemplateDeleteOut, TemplateIn, TemplateOut, TemplateStatus,
} from "./types";

// ---------------------------------------------------------------- v0.7.2 응답 보정(빈 화면 방지)
const DEFAULT_SETTINGS: Omit<OptSettingsOut, "method_sources"> = {
  enabled: false,
  solver_ready: false,
  solver_reason: null,
  size: { tol_rel: 0.02, plate_tol_rel: 0.05, require_inch: true },
  bead_defaults: { angle: 45, min_width: 60, height: 10 },
  keepout_auto: { hole_radius_mm: 15, edge_band_mm: 10 },
  loads: { default_objective_norm: "abs", default_strategy: "A", mac_merge: 0.95, max_cases: 20, default_k: 5 },
  max_rects: 20,
  max_entries: 200,
  template_max_elems: 500000,
  template_ext: [".rad", ".inc", ".fem"],
  max_preview_points: 20000,
};
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown) => (typeof v === "string" ? v : "");

/** 방법·출처 자료가 온전한지(서버가 자료 파일을 못 읽으면 {error} 만 온다) */
export const methodSourcesOk = (m: OptMethodSources | null | undefined): m is OptMethodSources =>
  !!m && !m.error && Array.isArray(m.summary_ko) && isObj(m.strategies) && isObj(m.objective_norms) && Array.isArray(m.sources);

/** 방법·출처: 빠진 칸은 빈 문구(error 유지) — 화면은 설명 없이 동작 */
export function normalizeMethodSources(raw: unknown): OptMethodSources {
  const m = isObj(raw) ? raw : {};
  const st = isObj(m.strategies) ? m.strategies : {};
  const on = isObj(m.objective_norms) ? m.objective_norms : {};
  const out: OptMethodSources = {
    version: str(m.version),
    summary_ko: Array.isArray(m.summary_ko) ? m.summary_ko.filter((x): x is string => typeof x === "string") : [],
    strategies: { A: str(st.A), B: str(st.B), C: str(st.C) },
    objective_norms: { abs: str(on.abs), rel: str(on.rel) },
    sources: Array.isArray(m.sources) ? (m.sources.filter((x) => isObj(x) && typeof x.title === "string") as unknown as OptMethodSources["sources"]) : [],
  };
  const err = typeof m.error === "string" ? m.error : !isObj(raw) || !isObj(m.strategies) ? "방법·출처 자료가 없습니다" : null;
  if (err) out.error = err;
  return out;
}

/** GET /opt/settings 응답 보정: 빠졌거나 null 인 칸은 기본값(꺼짐 쪽) — 이전 서버·부분 응답에도 화면이 깨지지 않게 */
export function normalizeOptSettings(raw: unknown): OptSettingsOut {
  const r = isObj(raw) ? raw : {};
  const sub = <K extends "size" | "bead_defaults" | "keepout_auto" | "loads">(k: K): OptSettingsOut[K] => {
    const v = isObj(r[k]) ? (r[k] as Record<string, unknown>) : {};
    const d = DEFAULT_SETTINGS[k] as unknown as Record<string, unknown>;
    return Object.fromEntries(Object.keys(d).map((x) => [x, v[x] ?? d[x]])) as unknown as OptSettingsOut[K];
  };
  const num = (k: "max_rects" | "max_entries" | "template_max_elems" | "max_preview_points") => (typeof r[k] === "number" ? (r[k] as number) : DEFAULT_SETTINGS[k]);
  return {
    enabled: r.enabled === true,
    solver_ready: r.solver_ready === true,
    solver_reason: typeof r.solver_reason === "string" ? r.solver_reason : null,
    size: sub("size"),
    bead_defaults: sub("bead_defaults"),
    keepout_auto: sub("keepout_auto"),
    loads: sub("loads"),
    method_sources: normalizeMethodSources(r.method_sources),
    max_rects: num("max_rects"),
    max_entries: num("max_entries"),
    template_max_elems: num("template_max_elems"),
    template_ext: Array.isArray(r.template_ext) ? (r.template_ext as string[]) : DEFAULT_SETTINGS.template_ext,
    max_preview_points: num("max_preview_points"),
  };
}

/** 실행 불가 사유 한 줄(꺼짐·솔버 미준비). 경로는 서버가 관리자에게만 solver_reason 에 넣는다. null = 실행 가능 */
export function optBlockedReason(st: OptSettingsOut): string | null {
  if (!st.enabled) return st.solver_reason ?? "비드 최적화가 서버에서 꺼져 있습니다 — 관리자 문의";
  if (!st.solver_ready) return st.solver_reason ?? "서버 OptiStruct 경로가 설정되지 않았습니다 — 관리자 문의";
  return null;
}

export const opt = {
  settings: () => request<unknown>("GET", "/opt/settings").then(normalizeOptSettings),
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
  /** 결과 zip. parts(서버 OPT_PARTS) = report·result(opt.json·post·load)·deck(기본 셋) [+solve = OptiStruct 원본, raw = npz·대상] */
  bundleUrl: (id: string, parts = "report,result,deck") => `${API_PREFIX}/opt/runs/${id}/bundle` + `?parts=${encodeURIComponent(parts)}`,
  reportUrl: (id: string) => `${API_PREFIX}/opt/runs/${id}/report`,
  beadMapUrl: (id: string) => `${API_PREFIX}/opt/runs/${id}/bead-map.png`,
};

/** /opt/settings 1회 조회 캐시(라이브러리 목록 행 선택의 크기 허용 등 — 실패하면 다음 호출에서 다시) */
let settingsOnce: Promise<OptSettingsOut> | null = null;
export function optSettingsCached(): Promise<OptSettingsOut> {
  if (!settingsOnce)
    settingsOnce = opt.settings().catch((e) => {
      settingsOnce = null;
      throw e;
    });
  return settingsOnce;
}
/** 시험용: 캐시 비우기 */
export const resetOptSettingsCache = () => {
  settingsOnce = null;
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
/** 다른 모델 사유: s1-check(서버 topo_sha256 비교) = TOPOLOGY·MODEL_INFO_MISSING, OPT_PREP 전체 규칙 = NODE_IDS·CONNECTIVITY·COORDS */
export const MISMATCH_REASON: Record<string, string> = {
  TOPOLOGY: "노드 ID·요소 연결 다름",
  MODEL_INFO_MISSING: "모델 정보 없음",
  NODE_IDS: "노드 ID 다름",
  CONNECTIVITY: "요소 연결 다름",
  COORDS: "좌표 다름",
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
export const sizeOf = (e: EntryOut): SizeOf => ({ inch: e.size?.inch ?? e.model?.inch ?? null, L_xi: e.size?.L_xi ?? null, L_eta: e.size?.L_eta ?? null });

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
