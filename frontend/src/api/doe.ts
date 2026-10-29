// v0.9.0 비드 형상 DOE API(계약 esl_bead_doe.md §10). check:api 대상 — 백엔드 openapi 가 나오면 경로·스키마 대조.
import { API_PREFIX, request } from "./client";
import type {
  DoeCheckIn, DoeCheckOut, DoeDesignStatus, DoeFileOut, DoeMatrixOut, DoeMethod, DoeMethodSources, DoeParam, DoeParamType, DoeParamsOut, DoePhase, DoePlanOut,
  DoePerEslOut, DoeRankRow, DoeResultOut, DoeScenario, DoeSettingsOut, DoeSpec, DoeStudyIn, DoeStudyOut, EntryOut,
} from "./types";

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown) => (typeof v === "string" ? v : "");
const num = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);

// ---------------------------------------------------------------- 응답 보정(빈 화면 방지 — 이전 서버·부분 응답)
/** 서버 응답이 비었을 때만 쓰는 꺼짐 쪽 기본값(값의 원본은 서버 설정 bead_doe.*) */
const DEFAULT_SETTINGS: Omit<DoeSettingsOut, "method_sources"> = {
  enabled: false,
  reason: null,
  paicad: { ready: false, version: null, pinned: null, warning: null },
  gmsh: { ready: false, version: null },
  scenarios: { same: false, mesh: false, step: false },
  max_entries: 50,
  max_designs: 200,
  doe: { methods: ["lhs", "halton", "fullfact"], default_method: "lhs", default_n: 30, seed: 1, levels_default: 3, levels_max: 9, default_types: ["D", "W"] },
  mesh: { size_auto: true, size_min_mm: 1, size_max_mm: 20 },
  boundary: { fastener_warn_mm: 10, load_warn_mm: 20, load_share_min: 0.2 },
  step_max_mb: 200,
  part_title: null,
};

export const doeSourcesOk = (m: DoeMethodSources | null | undefined): m is DoeMethodSources =>
  !!m && !m.error && Array.isArray(m.summary_ko) && isObj(m.methods) && Array.isArray(m.sources);

export function normalizeDoeSources(raw: unknown): DoeMethodSources {
  const m = isObj(raw) ? raw : {};
  const strMap = (v: unknown) => (isObj(v) ? Object.fromEntries(Object.entries(v).filter(([, x]) => typeof x === "string")) as Record<string, string> : {});
  const out: DoeMethodSources = {
    version: str(m.version),
    summary_ko: Array.isArray(m.summary_ko) ? m.summary_ko.filter((x): x is string => typeof x === "string") : [],
    methods: strMap(m.methods),
    metrics: strMap(m.metrics),
    limits: Array.isArray(m.limits) ? m.limits.filter((x): x is string => typeof x === "string") : [],
    sources: Array.isArray(m.sources) ? (m.sources.filter((x) => isObj(x) && typeof x.title === "string") as unknown as DoeMethodSources["sources"]) : [],
  };
  const err = typeof m.error === "string" ? m.error : !isObj(raw) || !isObj(m.methods) ? "방법·출처 자료가 없습니다" : null;
  if (err) out.error = err;
  return out;
}

/** GET /doe/settings 응답 보정: 빠진 칸은 기본값(꺼짐 쪽) */
export function normalizeDoeSettings(raw: unknown): DoeSettingsOut {
  const r = isObj(raw) ? raw : {};
  const sub = <K extends "paicad" | "gmsh" | "scenarios" | "doe" | "mesh" | "boundary">(k: K): DoeSettingsOut[K] => {
    const v = isObj(r[k]) ? (r[k] as Record<string, unknown>) : {};
    const d = DEFAULT_SETTINGS[k] as unknown as Record<string, unknown>;
    return Object.fromEntries(Object.keys(d).map((x) => [x, v[x] ?? d[x]])) as unknown as DoeSettingsOut[K];
  };
  return {
    enabled: r.enabled === true,
    reason: typeof r.reason === "string" ? r.reason : null,
    paicad: sub("paicad"),
    gmsh: sub("gmsh"),
    scenarios: sub("scenarios"),
    max_entries: num(r.max_entries, DEFAULT_SETTINGS.max_entries),
    max_designs: num(r.max_designs, DEFAULT_SETTINGS.max_designs),
    doe: sub("doe"),
    mesh: sub("mesh"),
    boundary: sub("boundary"),
    step_max_mb: num(r.step_max_mb, DEFAULT_SETTINGS.step_max_mb),
    part_title: typeof r.part_title === "string" ? r.part_title : null,
    method_sources: normalizeDoeSources(r.method_sources),
  };
}

/** best.files: 문자열 rel 목록이 와도 같은 모양으로 */
export function normalizeFiles(raw: unknown): DoeFileOut[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((f) => (typeof f === "string" ? { rel: f } : isObj(f) && typeof f.rel === "string" ? (f as unknown as DoeFileOut) : null)).filter((f): f is DoeFileOut => !!f);
}

/** §11.4 ESL별 개선 지표 정의(ⓘ 팝오버·보고서와 같은 문구) */
export const METRIC_DEFS: { key: string; label: string; text: string }[] = [
  { key: "all_improved", label: "전 씬 개선", text: "모든 ESL 에서 베이스라인보다 컴플라이언스가 줄었는가(최악 비율 < 1 − 허용치)" },
  { key: "min_improvement", label: "최소 개선율", text: "1 − max(C_안 / C_베이스라인) — 가장 덜 개선된(또는 가장 악화된) 씬의 개선율" },
  { key: "n_worsened", label: "개선/악화 씬", text: "비율 < 1 − 허용치 = 개선, > 1 + 허용치 = 악화, 그 사이 = 변화 없음" },
  { key: "geo_mean_improvement", label: "기하평균 개선율", text: "1 − (Π C_안 / C_베이스라인)^(1/n) — 씬 전체의 평균적 개선" },
  { key: "pareto", label: "Pareto", text: "베이스라인·다른 안 어느 것에도 모든 ESL 에서 지배당하지 않는 안(●)" },
];

export type RankSortKey = "score" | "min_improvement" | "geo_mean_improvement" | "n_worsened" | "pareto";

/** 순위표 열 머리 정렬(동률 = score → 안 id). 지표가 없는 행(이전 결과)은 뒤로 */
export function sortRanking(rows: DoeRankRow[], key: RankSortKey): DoeRankRow[] {
  const v = (r: DoeRankRow): number => {
    switch (key) {
      case "score":
        return r.score;
      case "min_improvement":
        return r.min_improvement == null ? Infinity : -r.min_improvement;
      case "geo_mean_improvement":
        return r.geo_mean_improvement == null ? Infinity : -r.geo_mean_improvement;
      case "n_worsened":
        return r.n_worsened ?? Infinity;
      case "pareto":
        return r.pareto ? 0 : 1;
    }
  };
  return [...rows].sort((a, b) => v(a) - v(b) || a.score - b.score || a.id.localeCompare(b.id));
}

export function normalizeResult(raw: DoeResultOut): DoeResultOut {
  return {
    ...raw,
    esl: Array.isArray(raw.esl) ? raw.esl : [],
    ranking: Array.isArray(raw.ranking) ? raw.ranking : [],
    excluded: Array.isArray(raw.excluded) ? raw.excluded : [],
    view3d: Array.isArray(raw.view3d) ? raw.view3d : [],
    warnings: Array.isArray(raw.warnings) ? raw.warnings : [],
    best: raw.best ? { id: raw.best.id, files: normalizeFiles(raw.best.files) } : null,
  };
}

// ---------------------------------------------------------------- 비활성 사유(§6.5)
export const DISABLED_REASON: Record<string, string> = {
  DOE_DISABLED: "강성 평가 스터디가 서버에서 꺼져 있습니다(관리자 문의)",
  PAICAD_NOT_CONFIGURED: "형상 엔진(paicad)이 설치되지 않았습니다(관리자 문의)",
  PAICAD_NOT_FOUND: "형상 엔진(paicad)이 설치되지 않았습니다(관리자 문의)",
  PAICAD_VERSION_LOW: "형상 엔진(paicad) 버전이 낮습니다(관리자 문의)",
  PAICAD_OCP_MISSING: "형상 엔진(paicad)의 CAD 커널(OCP)이 없습니다(관리자 문의)",
  PAICAD_CHECK_FAILED: "형상 엔진(paicad) 점검에 실패했습니다(관리자 문의)",
  GMSH_UNAVAILABLE: "메시 생성기(gmsh)가 없어 'STEP만' 시나리오를 쓸 수 없습니다(관리자 문의)",
};

/** 실행 불가 사유(꺼짐) — null = 사용 가능 */
export function doeBlockedReason(st: DoeSettingsOut): string | null {
  if (st.enabled) return null;
  return (st.reason && DISABLED_REASON[st.reason]) ?? DISABLED_REASON.PAICAD_NOT_CONFIGURED;
}

/** 시나리오별 비활성 사유(설정 scenarios·gmsh) */
export function scenarioBlocked(st: DoeSettingsOut, s: DoeScenario): string | null {
  if (st.scenarios[s]) return null;
  if (s === "step" && !st.gmsh.ready) return DISABLED_REASON.GMSH_UNAVAILABLE;
  return "서버에서 이 시나리오가 꺼져 있습니다";
}

// ---------------------------------------------------------------- API
export const doe = {
  settings: () => request<unknown>("GET", "/doe/settings").then(normalizeDoeSettings),
  checkInputs: (body: DoeCheckIn) => request<DoeCheckOut>("POST", "/doe/check-inputs", { body }),
  createStudy: (body: DoeStudyIn) => request<DoeStudyOut>("POST", "/doe/studies", { body }),
  studies: (q: { project_id: string }) => request<DoeStudyOut[]>("GET", "/doe/studies", { query: { ...q } }),
  study: (id: string) => request<DoeStudyOut>("GET", `/doe/studies/${id}`),
  params: (id: string) => request<DoeParamsOut>("GET", `/doe/studies/${id}/params`),
  planView: (id: string) => request<DoePlanOut>("GET", `/doe/studies/${id}/plan-view`),
  matrix: (id: string, version: number, spec: DoeSpec) => request<DoeMatrixOut>("POST", `/doe/studies/${id}/matrix`, { body: { version, spec } }),
  preview: (id: string, version: number, spec: DoeSpec) => request<DoeStudyOut>("POST", `/doe/studies/${id}/preview`, { body: { version, spec } }),
  /** solver 는 보내지 않음(기본 linear — UI 선택 칸 없음, 확정 6) */
  run: (id: string, version: number, matrix_sha256: string) => request<DoeStudyOut>("POST", `/doe/studies/${id}/run`, { body: { version, matrix_sha256 } }),
  clone: (id: string, title?: string | null) => request<DoeStudyOut>("POST", `/doe/studies/${id}/clone`, { body: title ? { title } : {} }),
  results: (id: string) => request<DoeResultOut>("GET", `/doe/studies/${id}/results`).then(normalizeResult),
  /** §11.4 ESL별 지표(순위 행에 per_esl 이 없을 때) */
  perEsl: (id: string, designs: string[]) =>
    request<DoePerEslOut>("GET", `/doe/studies/${id}/results/per-esl`, { query: { design: designs.join(",") } }),
  files: (id: string) => request<DoeFileOut[]>("GET", `/doe/studies/${id}/files`),
  beadPngUrl: (id: string, bead: string) => `${API_PREFIX}/doe/studies/${id}/beads/${encodeURIComponent(bead)}.png`,
  thumbUrl: (id: string, did: string) => `${API_PREFIX}/doe/studies/${id}/preview/thumb/${encodeURIComponent(did)}`,
  downloadUrl: (id: string, rel: string) => `${API_PREFIX}/doe/studies/${id}/download?rel=${encodeURIComponent(rel)}`,
  bundleUrl: (id: string, parts = "best,report,ranking") => `${API_PREFIX}/doe/studies/${id}/bundle?parts=${encodeURIComponent(parts)}`,
  reportUrl: (id: string) => `${API_PREFIX}/doe/studies/${id}/report`,
  /** 3D 비교 manifest(기존 view3d 파일 API 규칙 — 파일 URL 은 manifest 의 geometry_url·values_url) */
  view3dPath: (id: string, did: string, file = "manifest.json") => `/doe/studies/${id}/view3d/${encodeURIComponent(did)}/${file}`,
};

// ---------------------------------------------------------------- 표기
export const SCENARIOS: DoeScenario[] = ["same", "mesh", "step"];
export const SCENARIO_NAME: Record<DoeScenario, string> = { same: "같은 모델", mesh: "다른 모델(메시 있음)", step: "다른 모델(STEP만)" };
export const SCENARIO_NO: Record<DoeScenario, string> = { same: "①", mesh: "②", step: "③" };
export const METHOD_NAME: Record<DoeMethod, string> = { lhs: "LHS", halton: "Halton", fullfact: "풀 팩토리얼" };
export const TYPE_NAME: Record<DoeParamType, string> = { D: "깊이 D", W: "폭 W", U: "위치 U", V: "위치 V" };
export const PHASE_NAME: Record<DoePhase, string> = {
  PREP: "입력 준비 중",
  READY: "준비 완료",
  PREVIEW: "미리보기 중",
  PREVIEW_READY: "미리보기 완료",
  RUN: "실행 중",
  DONE: "완료",
  FAILED: "실패",
};
export const STATUS_NAME: Record<DoeDesignStatus, string> = {
  READY: "OK",
  RUNNING: "실행 중",
  OK: "OK",
  SKIPPED_COLLISION: "충돌",
  SKIPPED_FIXED: "고정 침범",
  SKIPPED_GEOM: "형상 불가",
  FAILED_MORPH: "모핑 실패",
  FAILED_MESH: "메시 실패",
  FAILED_SOLVE: "해석 실패",
  CANCELED: "취소",
};
export const isSkipped = (s: DoeDesignStatus) => s.startsWith("SKIPPED_");
export const isFailed = (s: DoeDesignStatus) => s.startsWith("FAILED_") || s === "CANCELED";

export const doePath = (projectId: string, id?: string) => `/p/${projectId}/doe/${id ?? "new"}`;

/** 경고 1줄(서버 문구 우선, 없으면 코드) */
export const warnText = (w: { code: string; message?: string | null }) => w.message || w.code;

// ---------------------------------------------------------------- 시나리오 자동 판별
/** 모든 ESL 이 같은 모델(topo_sha256 같음)이면 ①, 아니면 B 메시를 올렸으면 ②, 아니면 ③ */
export function autoScenario(entries: Pick<EntryOut, "topo_sha256">[], hasMesh: boolean): DoeScenario {
  const topo = entries.map((e) => e.topo_sha256 ?? null);
  if (topo.length && topo[0] && topo.every((t) => t === topo[0])) return "same";
  return hasMesh ? "mesh" : "step";
}

// ---------------------------------------------------------------- 변수 범위(§5, BD-D-7)
export interface ParamRow {
  name: string;
  on: boolean;
  lo: string;
  hi: string;
}

/** 기본 변수 행: use_default 이고 기본 종류(D·W)면 포함, 범위 = default_range(없으면 feasible) */
export function defaultRows(params: DoeParam[], types: DoeParamType[]): ParamRow[] {
  return params.map((p) => {
    const r = p.default_range ?? p.feasible;
    return { name: p.name, on: p.use_default && types.includes(p.type), lo: String(r[0]), hi: String(r[1]) };
  });
}

/** 행 오류(차단): 숫자 아님·lo ≥ hi·D/W 하한 ≤ 0 */
export function rowProblem(p: Pick<DoeParam, "type">, r: ParamRow): string | null {
  if (!r.on) return null;
  const lo = Number(r.lo);
  const hi = Number(r.hi);
  if (!r.lo.trim() || !r.hi.trim() || !Number.isFinite(lo) || !Number.isFinite(hi)) return "숫자를 입력하세요";
  if (!(lo < hi)) return "하한 < 상한이어야 합니다";
  if ((p.type === "D" || p.type === "W") && lo <= 0) return "깊이·폭 하한은 0보다 커야 합니다";
  return null;
}

/** feasible 밖(경고 배지만 — 미리보기가 실패 안을 거름) */
export function outsideFeasible(p: Pick<DoeParam, "feasible">, r: ParamRow): boolean {
  if (!r.on) return false;
  const lo = Number(r.lo);
  const hi = Number(r.hi);
  return lo < p.feasible[0] - 1e-9 || hi > p.feasible[1] + 1e-9;
}

export interface SpecForm {
  method: DoeMethod;
  n: string;
  levels: string;
  seed: string;
}

/** 화면 → DoeSpec(포함 변수만). 문제 있으면 사유 */
export function buildSpec(form: SpecForm, params: DoeParam[], rows: ParamRow[], st: DoeSettingsOut): { spec: DoeSpec | null; problem: string | null } {
  const byName = new Map(params.map((p) => [p.name, p]));
  const on = rows.filter((r) => r.on);
  if (!on.length) return { spec: null, problem: "변수를 하나 이상 고르세요" };
  for (const r of on) {
    const p = byName.get(r.name);
    if (!p) return { spec: null, problem: `알 수 없는 변수 ${r.name}` };
    const why = rowProblem(p, r);
    if (why) return { spec: null, problem: `${r.name}: ${why}` };
  }
  const seed = Number(form.seed);
  if (!(form.seed.trim() && Number.isInteger(seed) && seed >= 0 && seed <= 2 ** 32 - 1)) return { spec: null, problem: "시드는 0 이상 정수입니다" };
  const spec: DoeSpec = { method: form.method, seed, params: on.map((r) => ({ name: r.name, lo: Number(r.lo), hi: Number(r.hi) })) };
  if (form.method === "fullfact") {
    const lv = Number(form.levels);
    if (!(Number.isInteger(lv) && lv >= 2 && lv <= st.doe.levels_max)) return { spec: null, problem: `수준은 2~${st.doe.levels_max} 정수입니다` };
    spec.levels = lv;
    const total = lv ** on.length;
    if (total + 1 > st.max_designs) return { spec: null, problem: `안 수 ${total} + 공칭 1 > 최대 ${st.max_designs}안 — 수준이나 변수를 줄이세요` };
  } else {
    const n = Number(form.n);
    if (!(Number.isInteger(n) && n >= 2 && n <= st.max_designs - 1)) return { spec: null, problem: `안 수는 2~${st.max_designs - 1} 정수입니다` };
    spec.n = n;
  }
  return { spec, problem: null };
}

/** 개선율 표기: +19 % */
export const pctText = (v: number | null | undefined, digits = 0) => (v == null || !Number.isFinite(v) ? "–" : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(digits)} %`);
