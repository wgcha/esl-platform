// v0.9.0 비드 형상 DOE API(계약 esl_bead_doe.md §10). check:api 대상 — 백엔드 openapi 가 나오면 경로·스키마 대조.
import { API_PREFIX, ApiError, CODE_TEXT, errorText, request } from "./client";
import type {
  DoeBasisMeta, DoeBeadSource, DoeDeriveOut, DoeSelectAutoOut, DoeSelectBase, DoeSelectCfg, DoeSelectDeriveIn, DoeSelectionPutIn, DoeSelectionAny, DoeSelectionOut, DoeSelectViewManifest, DoeSelectGraphOut,
  DoeCellWarning, DoeDefeatureFeature, DoeDefeatureKind, DoeDefeatureList, DoeShapeDefeature, DoeShapeDiag,
  DoeCheckIn, DoeCheckOut, DoeCompareCfg, DoeMeshAttempt, DoeMeshMethod, DoeMeshMode, DoeMeshPart, DoePrepShape, DoeShapeRef, DoeDesignStatus, DoeFileOut, DoeMatrixOut, DoeMethod, DoeMethodSources, DoeParam, DoeParamType, DoeParamsOut, DoePhase, DoePlanOut,
  DoePerEslOut, DoeRankRow, DoeResultOut, DoeScenario, DoeSettingsOut, DoeSpec, DoeStudyIn, DoeStudyOut, EntryOut,
  DoeFixedXferMethod, DoePrepFixedXfer, DoeWarning,
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
  scenarios: { same: false, mesh: false, step: false, compare: false, select: false },
  max_entries: 50,
  max_designs: 200,
  doe: { methods: ["lhs", "halton", "fullfact"], default_method: "lhs", default_n: 30, seed: 1, levels_default: 3, levels_max: 9, default_types: ["D", "W"] },
  mesh: { size_auto: true, size_min_mm: 1, size_max_mm: 20 },
  boundary: { fastener_warn_mm: 10, load_warn_mm: 20, load_share_min: 0.2 },
  step_max_mb: 200,
  part_title: null,
  compare_reason: null,
  compare: { enabled: false, reason: null, max_shapes: 20, total_max_mb: 1000, mesh_size_mm: 3 },
  select_reason: null,
  select: { enabled: false, reason: null, feature_angle_deg: 15, max_beads: 20, max_tiers: 6, blend: { min_mm: 15, max_mm: 200, k: null } },
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
    scenarios: normalizeScenarios(sub("scenarios"), r.scenarios),
    max_entries: num(r.max_entries, DEFAULT_SETTINGS.max_entries),
    max_designs: num(r.max_designs, DEFAULT_SETTINGS.max_designs),
    doe: sub("doe"),
    mesh: sub("mesh"),
    boundary: sub("boundary"),
    step_max_mb: num(r.step_max_mb, DEFAULT_SETTINGS.step_max_mb),
    part_title: typeof r.part_title === "string" ? r.part_title : null,
    method_sources: normalizeDoeSources(r.method_sources),
    compare_reason: typeof r.compare_reason === "string" ? r.compare_reason : null,
    compare: normalizeCompareCfg(r.compare, r),
    select: normalizeSelectCfg(r.select, r),
    select_reason: typeof r.select_reason === "string" ? r.select_reason : null,
  };
}

/** v0.16.2 scenarios.select_auto·select_mesh(esl_bead_auto.md §3.2) — 서버가 줄 때만 */
function normalizeScenarios(base: DoeSettingsOut["scenarios"], raw: unknown): DoeSettingsOut["scenarios"] {
  const v = isObj(raw) ? raw : {};
  return {
    ...base,
    ...(typeof v.select_auto === "boolean" ? { select_auto: v.select_auto } : {}),
    ...(typeof v.select_mesh === "boolean" ? { select_mesh: v.select_mesh } : {}),
  };
}

/** v0.15.0 select 설정 보정(빠진 칸 = 계약 기본값, enabled 가 없으면 scenarios.select) */
function normalizeSelectCfg(raw: unknown, top: Record<string, unknown>): DoeSelectCfg {
  const v = isObj(raw) ? raw : {};
  const d = DEFAULT_SETTINGS.select!;
  const sc = isObj(top.scenarios) ? top.scenarios : {};
  const bl = isObj(v.blend) ? v.blend : {};
  return {
    enabled: typeof v.enabled === "boolean" ? v.enabled : sc.select === true,
    reason: typeof v.reason === "string" ? v.reason : typeof top.select_reason === "string" ? top.select_reason : null,
    feature_angle_deg: num(v.feature_angle_deg, d.feature_angle_deg),
    max_beads: num(v.max_beads, d.max_beads),
    max_tiers: num(v.max_tiers, d.max_tiers),
    blend: { min_mm: num(bl.min_mm, d.blend.min_mm), max_mm: num(bl.max_mm, d.blend.max_mm), k: typeof bl.k === "number" ? bl.k : null },
    // v0.16.1(SR-D-2·9) — 서버가 줄 때만
    ...(v.fixed_policy === "warn" || v.fixed_policy === "skip" ? { fixed_policy: v.fixed_policy } : {}),
    ...(v.quality_fail_policy === "warn" || v.quality_fail_policy === "skip" ? { quality_fail_policy: v.quality_fail_policy } : {}),
    ...(isObj(v.hold) ? { hold: { ring_mm: num(v.hold.ring_mm, 3), blend_mm: num(v.hold.blend_mm, 8) } } : {}),
    // v0.16.2 AD-D-7
    ...(isObj(v.hole) ? { hole: { bridge_max_mm: num(v.hole.bridge_max_mm, 20) } } : {}),
  };
}

/** ④ compare 설정 보정(빠진 칸 = 계약 기본값). enabled·reason 이 없으면 scenarios.compare·compare_reason 에서 */
function normalizeCompareCfg(raw: unknown, top: Record<string, unknown>): DoeCompareCfg {
  const v = isObj(raw) ? raw : {};
  const d = DEFAULT_SETTINGS.compare!;
  const sc = isObj(top.scenarios) ? top.scenarios : {};
  const reason = typeof v.reason === "string" ? v.reason : typeof top.compare_reason === "string" ? top.compare_reason : null;
  return {
    enabled: typeof v.enabled === "boolean" ? v.enabled : sc.compare === true,
    reason,
    max_shapes: num(v.max_shapes, d.max_shapes),
    total_max_mb: num(v.total_max_mb, d.total_max_mb),
    mesh_size_mm: num(v.mesh_size_mm, d.mesh_size_mm),
    // v0.16.0 메시 옵션 칸 — 서버가 줄 때만(옛 서버 = 없음 → 고급 설정 숨김, 메시 입력 안 받음)
    ...(v.mesh_mode === "cad" || v.mesh_mode === "remesh" || v.mesh_mode === "freeform" || v.mesh_mode === "auto" ? { mesh_mode: v.mesh_mode as DoeMeshMode } : {}),
    ...(typeof v.remesh_available === "boolean" ? { remesh_available: v.remesh_available } : {}),
    ...(isObj(v.mesh_input)
      ? {
          mesh_input: {
            enabled: v.mesh_input.enabled === true,
            formats: Array.isArray(v.mesh_input.formats) ? v.mesh_input.formats.filter((x): x is string => typeof x === "string") : [".rad", ".inc"],
            max_mb: num(v.mesh_input.max_mb, 500),
          },
        }
      : {}),
    ...(typeof v.step_ready === "boolean" ? { step_ready: v.step_ready } : {}),
    ...(isObj(v.mesh) ? { mesh: v.mesh as DoeCompareCfg["mesh"] } : {}),
    ...(isObj(v.defeature) ? { defeature: v.defeature as DoeCompareCfg["defeature"] } : {}),
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
  COMPARE_DISABLED: "'형상 직접 비교'가 서버에서 꺼져 있습니다(관리자 문의)",
  COMPARE_GMSH_UNAVAILABLE: "메시 생성기(gmsh)가 없어 '형상 직접 비교'를 쓸 수 없습니다(관리자 문의)",
  SELECT_DISABLED: "'비드 직접 선택'이 서버에서 꺼져 있습니다(관리자 문의)",
};

/** ④ 비활성 사유 코드(서버 compare_reason → compare.reason → 옛 서버면 reason 이 DOE_DISABLED 일 때만) */
export const compareReason = (st: DoeSettingsOut): string | null =>
  st.compare_reason ?? st.compare?.reason ?? (st.reason === "DOE_DISABLED" ? "DOE_DISABLED" : null);

/** 실행 불가 사유(꺼짐) — null = 사용 가능. ④ 는 paicad 를 쓰지 않아 paicad 사유로 막지 않는다(SC-D-3) */
export function doeBlockedReason(st: DoeSettingsOut, scenario?: DoeScenario | null): string | null {
  if (st.enabled) return null;
  if (scenario === "compare") return compareReason(st) === "DOE_DISABLED" ? DISABLED_REASON.DOE_DISABLED : null;
  // v0.15.0 select 는 paicad 무관(BS-D-2) — DOE 꺼짐만 막는다
  if (scenario === "select") return st.reason === "DOE_DISABLED" || (st.select_reason ?? st.select?.reason) === "DOE_DISABLED" ? DISABLED_REASON.DOE_DISABLED : null;
  return (st.reason && DISABLED_REASON[st.reason]) ?? DISABLED_REASON.PAICAD_NOT_CONFIGURED;
}

/** 시나리오별 비활성 사유(설정 scenarios·gmsh) */
export function scenarioBlocked(st: DoeSettingsOut, s: DoeScenario): string | null {
  if (st.scenarios[s]) return null;
  if (s === "select") return (st.select_reason ?? st.select?.reason) === "DOE_DISABLED" ? DISABLED_REASON.DOE_DISABLED : DISABLED_REASON.SELECT_DISABLED;
  if (s === "step" && !st.gmsh.ready) return DISABLED_REASON.GMSH_UNAVAILABLE;
  if (s === "compare") {
    const r = compareReason(st);
    if (r === "DOE_DISABLED") return DISABLED_REASON.DOE_DISABLED;
    if (r === "GMSH_UNAVAILABLE" || (!r && !st.gmsh.ready)) return DISABLED_REASON.COMPARE_GMSH_UNAVAILABLE;
    return DISABLED_REASON.COMPARE_DISABLED;
  }
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
  /** ④ 비교 실행(matrix_sha256 없음, SC-D-1) */
  runCompare: (id: string, version: number) => request<DoeStudyOut>("POST", `/doe/studies/${id}/run`, { body: { version } }),
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
  // ---- v0.15.0 비드 직접 선택(esl_bead_select.md §9)
  /** 선택 보기 파일(part.glb · select.bin · select_manifest.json) */
  selectViewUrl: (id: string, file: "part.glb" | "select.bin" | "select_manifest.json" | "graph.bin") => `${API_PREFIX}/doe/studies/${id}/select/view/${file}`,
  selectManifest: (id: string) => request<DoeSelectViewManifest>("GET", `/doe/studies/${id}/select/view/select_manifest.json`),
  /** 저장 없이 서버 재계산(사면·경계·공칭·경고). bead 주면 그 비드만 */
  derive: (id: string, selection: DoeSelectionAny, bead?: string | null) =>
    request<DoeDeriveOut>("POST", `/doe/studies/${id}/select/derive`, { body: (bead ? { selection, bead } : { selection }) satisfies DoeSelectDeriveIn }),
  selection: (id: string) => request<DoeSelectionOut | null>("GET", `/doe/studies/${id}/selection`),
  saveSelection: (id: string, version: number, selection: DoeSelectionAny) => request<DoeStudyOut>("PUT", `/doe/studies/${id}/selection`, { body: { version, selection } satisfies DoeSelectionPutIn }),
  /** 기저(rev = 저장 선택 rev — 미리보기한 선택과 다르면 404) */
  basisUrl: (id: string, rev: number) => `${API_PREFIX}/doe/studies/${id}/select/basis?rev=${rev}`,
  basisMeta: (id: string, rev: number) => request<DoeBasisMeta>("GET", `/doe/studies/${id}/select/basis`, { query: { meta: "1", rev: String(rev) } }),
  // ---- v0.16.1 ④ 작은 형상 억제 목록(esl_select_relax.md §9 — mesh/defeature.json 그대로, 없으면 404)
  shapeDefeature: (id: string, did: string) => request<DoeDefeatureList>("GET", `/doe/studies/${id}/shapes/${encodeURIComponent(did)}/defeature`).then(normalizeDefeatureList),
  // ---- v0.16.2 자동 탐지 seed(esl_bead_auto.md §3.3 — 404 AUTO_NOT_AVAILABLE · 409 PREP_NOT_READY)
  selectAuto: (id: string) => request<DoeSelectAutoOut>("GET", `/doe/studies/${id}/select/auto`),
  // ---- v0.17.0 비드 네트워크 그래프(esl_beadgraph.md §6.1 — 404 GRAPH_NOT_AVAILABLE · 409 PREP_NOT_READY)
  selectGraph: (id: string) => request<DoeSelectGraphOut>("GET", `/doe/studies/${id}/select/graph`),
};
/** 계약 이름(api/doe.ts getSelectGraph) */
export const getSelectGraph = doe.selectGraph;
/** 계약 이름(api/doe.ts getSelectAuto) */
export const getSelectAuto = doe.selectAuto;
/** seed 불러오기: 404 AUTO_NOT_AVAILABLE = seed 없음(null), 그 밖 오류는 그대로. 비드 0개 seed(자동 탐지 실패)도 null */
export async function loadSelectAuto(id: string): Promise<{ seed: DoeSelectAutoOut | null; code: string | null }> {
  try {
    const r = await doe.selectAuto(id);
    // v0.18.0(SG-D-16): ③ manual seed = 빈 비드 + fixed_user(A 고정 이전) — 고정만 있어도 seed
    if (!r?.selection || !Array.isArray(r.selection.beads) || (!r.selection.beads.length && !seedHasFixed(r.selection))) return { seed: null, code: r?.warnings?.find((w) => w.code === "AUTO_DETECT_FAILED") ? "AUTO_DETECT_FAILED" : "AUTO_EMPTY" };
    return { seed: { ...r, warnings: Array.isArray(r.warnings) ? r.warnings : [], map: Array.isArray(r.map) ? r.map : [] }, code: null };
  } catch (e) {
    if (e instanceof ApiError && e.code === "AUTO_NOT_AVAILABLE") return { seed: null, code: "AUTO_NOT_AVAILABLE" };
    throw e;
  }
}
/** seed 에 고정(fixed_user) 요소가 있음 */
export const seedHasFixed = (sel: { fixed_user?: { q: [number, number][]; t: [number, number][] } | null }): boolean =>
  !!sel.fixed_user && (sel.fixed_user.q.length > 0 || sel.fixed_user.t.length > 0);
/** 계약 R4 이름(api/doe.ts getShapeDefeature) */
export const getShapeDefeature = doe.shapeDefeature;

/** defeature.json 보정(빠진 칸·잘못된 행 무시) */
export function normalizeDefeatureList(raw: unknown): DoeDefeatureList {
  const r = isObj(raw) ? raw : {};
  const features = Array.isArray(r.features) ? (r.features.filter((f) => isObj(f) && typeof f.kind === "string" && Array.isArray(f.center)) as unknown as DoeDefeatureFeature[]) : [];
  return {
    features,
    n: typeof r.n === "number" ? r.n : features.length,
    truncated: r.truncated === true,
    counts: isObj(r.counts) ? (r.counts as DoeDefeatureList["counts"]) : null,
  };
}

// ---------------------------------------------------------------- 표기
export const SCENARIOS: DoeScenario[] = ["same", "mesh", "step", "compare"];
/** v0.16.2 새 스터디 라디오 위치(①②③④). ①② = 시나리오 select(① case · ② mesh) — same·mesh 는 새로 만들지 않음(AD-D-1·13) */
export type NewRadio = "case" | "bmesh" | "step" | "compare";
export const NEW_RADIOS: NewRadio[] = ["case", "bmesh", "step", "compare"];
export const NEW_RADIO_NO: Record<NewRadio, string> = { case: "①", bmesh: "②", step: "③", compare: "④" };
export const NEW_RADIO_NAME: Record<NewRadio, string> = { case: "같은 모델", bmesh: "다른 모델(B 메시)", step: "다른 모델(STEP만)", compare: "형상 직접 비교(STEP 여러 개)" };
/** 라디오 → 요청 시나리오·기준. v0.18.0(esl_step_graph.md §5.1) ③ = select + select_base "step" — 새 ③ 은 scenario step 을 만들지 않음 */
export const radioRequest = (r: NewRadio): { scenario: DoeScenario; selectBase: DoeSelectBase | null } =>
  r === "case" ? { scenario: "select", selectBase: "case" } : r === "bmesh" ? { scenario: "select", selectBase: "mesh" } : r === "step" ? { scenario: "select", selectBase: "step" } : { scenario: r, selectBase: null };
/** 기존 스터디 → 라디오 위치(same = ①, mesh = ②, step(이전 방식)·select step = ③, select = select_base) */
export const studyRadio = (s: DoeScenario, base?: DoeSelectBase | null): NewRadio =>
  s === "same" ? "case" : s === "mesh" ? "bmesh" : s === "select" ? (base === "mesh" ? "bmesh" : base === "step" ? "step" : "case") : s;
/** 라디오 → select 기준(①②③ 만, ④ = null) */
export const radioBase = (r: NewRadio): DoeSelectBase | null => (r === "case" ? "case" : r === "bmesh" ? "mesh" : r === "step" ? "step" : null);
/** v0.18.0 기존 ③(scenario step, paicad) 스터디 표시(§5.3) */
export const LEGACY_STEP_LABEL = "이전 방식(paicad)";
/** ①② 하위 라디오(AD-D-1) */
export const BEAD_SOURCE_NAME: Record<DoeBeadSource, string> = { auto: "자동 탐지", manual: "직접 선택" };
/** v0.16.2 ①② 하위 선택 비활성 사유(null = 가능). 옛 서버(select_auto·select_mesh 없음)는 paicad 준비·select 가능으로 판정 */
export function selectSubBlocked(st: DoeSettingsOut, base: DoeSelectBase, source: DoeBeadSource): string | null {
  const sb = scenarioBlocked(st, "select");
  if (sb) return sb;
  if (base === "mesh" && st.scenarios.select_mesh === false) return "서버에서 다른 모델(B 메시) 비드 선택이 꺼져 있습니다";
  // v0.18.0(esl_step_graph.md §4.2·§6): ③ = select 가능 ∧ gmsh ready(paicad 무관) — select_step 또는 gmsh 로 판정
  if (base === "step" && (st.scenarios.select_step === false || !st.gmsh.ready)) return DISABLED_REASON.GMSH_UNAVAILABLE;
  // v0.17.0(esl_beadgraph.md §5.5): 자동 탐지 = 메시 분류기(select 가능 ∧ select.graph.enabled) — paicad 무관
  if (source === "auto" && (st.scenarios.select_auto === false || st.select?.graph?.enabled === false)) return "서버에서 비드 자동 분류가 꺼져 있습니다 — 직접 선택을 쓰세요";
  return null;
}
export const SCENARIO_NAME: Record<DoeScenario, string> = { same: "같은 모델", mesh: "다른 모델(메시 있음)", step: "다른 모델(STEP만)", compare: "형상 직접 비교(STEP 여러 개)", select: "같은 모델" };
export const SCENARIO_NO: Record<DoeScenario, string> = { same: "①", mesh: "②", step: "③", compare: "④", select: "①" };
/** v0.16.2 스터디 목록 시나리오 표기: ② B 메시 기준 select(inputs.select_base "mesh") = "② 다른 모델(B 메시)", 그 밖 = SCENARIO_NO·NAME.
 * v0.18.0: ③ STEP 기준 select = "③ 다른 모델(STEP만)", 기존 ③(scenario step) = "③ 다른 모델(STEP만) — 이전 방식(paicad)" */
export const studyScenarioLabel = (s: DoeScenario, base?: DoeSelectBase | null): string =>
  s === "select" && base === "mesh"
    ? `${NEW_RADIO_NO.bmesh} ${NEW_RADIO_NAME.bmesh}`
    : s === "select" && base === "step"
      ? `${NEW_RADIO_NO.step} ${NEW_RADIO_NAME.step}`
      : s === "step"
        ? `${SCENARIO_NO.step} ${SCENARIO_NAME.step} — ${LEGACY_STEP_LABEL}`
        : `${SCENARIO_NO[s]} ${SCENARIO_NAME[s]}`;
/** ① 하위 선택 "비드 정의"(BS-D-1) */
export const BEAD_DEF_NAME = { same: "자동 탐지(STEP)", select: "직접 선택(메시)" } as const;
/** 라디오 값: select 는 ① 라디오 아래 하위 선택 */
export const radioScenario = (s: DoeScenario): DoeScenario => (s === "select" ? "same" : s);
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
  FAILED_SIZE: "크기·정렬 불일치",
  CANCELED: "취소",
};
export const isSkipped = (s: DoeDesignStatus) => s.startsWith("SKIPPED_");
/** v0.15.0 select 셀 상태 이름: FAILED_MESH = 품질 실패(§6) */
export const cellStatusName = (s: DoeDesignStatus, select: boolean) => (select && s === "FAILED_MESH" ? "품질 실패" : STATUS_NAME[s]);
export const isFailed = (s: DoeDesignStatus) => s.startsWith("FAILED_") || s === "CANCELED";

export const doePath = (projectId: string, id?: string) => `/p/${projectId}/doe/${id ?? "new"}`;

/** 경고 1줄(서버 문구 우선, 없으면 화면 문구 맵, 없으면 코드) */
export const warnText = (w: { code: string; message?: string | null; level?: unknown; var?: unknown; usable?: unknown; [k: string]: unknown }) =>
  w.message ||
  (w.code === "SELECT_INNER_LOOP" && w.level === "info" ? SELECT_CODE_TEXT.SELECT_INNER_LOOP_RING : "") ||
  (w.code === "SELECT_RANGE_INVERTS" && Array.isArray(w.usable) && w.usable.length === 2
    ? `${String(w.var ?? "")} 기본 범위 끝에서 요소가 뒤집힙니다 — 뒤집힘 없는 범위 ≈ ${Number(w.usable[0])}~${Number(w.usable[1])} mm`
    : "") ||
  autoWarnText(w) ||
  CODE_TEXT[w.code] || SELECT_CODE_TEXT[w.code] || w.code;
/** v0.16.1 정보 수준 비드 안내(SR-D-25·28 — level "info"): ⚠ 개수에 넣지 않고 ⓘ 로 표시. v0.16.2 AUTO_GROUP_DROPPED·AUTO_SLOPE_DIFF 도 */
export const isInfoWarn = (w: { code?: string; level?: unknown }) => w.level === "info" || (w.level == null && !!w.code && AUTO_INFO.has(w.code));

// ---------------------------------------------------------------- v0.15.0 비드 직접 선택 문구(서버 문구가 없을 때만 — 원본 resources/doe_messages.json)
export const SELECT_CODE_TEXT: Record<string, string> = {
  SELECTION_MISSING: "비드 선택을 먼저 저장하세요",
  FIXED_INFO_MISSING: "체결 정보 없음 — 체결부를 '고정'으로 칠하세요",
  SELECT_SLOPE_LEAK: "사면이 너무 멀리 퍼졌습니다 — 바닥을 더 고르거나 경계 −1줄",
  SELECT_TIER_MISSING: "고르지 않은 단이 있습니다 — [+ 단]으로 그 바닥을 고르세요",
  SELECT_OPEN_BOUNDARY: "경계가 판 가장자리에서 열려 있어 폭 W 변수를 쓸 수 없습니다",
  SELECT_DISCONNECTED: "비드 요소가 여러 덩어리로 나뉘어 있습니다",
  SELECT_NONPLANAR_BASE: "상판이 평면이 아니라 사면 보간을 거리 비율로 합니다",
  SELECT_BLEND_OVERLAP: "다른 비드의 블렌딩 범위와 겹칩니다(변위 합산)",
  SELECT_BLEND_CLIPPED: "체결부 앞에서 블렌딩 반경을 줄였습니다",
  SELECT_FIXED_IN_BEAD: "비드 안에 고정 노드가 있어 그 비드 변수를 기본 제외했습니다",
  SELECT_FIXED_IN_BLEND: "블렌딩 범위 안에 고정 노드가 있어 폭을 바꾼 안은 제외됩니다",
  SELECT_WIDTH_UNDEFINED: "국부 폭을 잴 수 없어 폭 변수를 쓰지 않습니다",
  SELECT_FIXED_LAYER_OVERLAP: "'고정' 층이 비드 층과 겹칩니다",
  SELECTION_DROPPED: "기준 메시가 바뀌어 저장된 비드 선택을 쓸 수 없습니다 — 다시 고르고 '선택 저장'",
  SELECT_OVERLAP: "한 요소가 두 비드·층에 들어 있습니다",
  SELECT_ELEM_UNKNOWN: "기준 메시에 없는 요소가 있습니다",
  SELECT_EMPTY_TIER: "바닥 요소가 없는 단이 있습니다",
  SELECT_TIERS_GAP: "단 번호가 건너뜁니다",
  SELECT_LINK_INVALID: "단 묶음이 올바르지 않습니다",
  SELECT_BEAD_ID_INVALID: "비드 id 가 올바르지 않습니다",
  SELECT_NAME_INVALID: "비드 이름은 1~32자, 제어문자 없이 쓰세요",
  SELECT_TOO_LARGE: "선택이 너무 큽니다 — 비드·층을 줄이세요",
  SELECT_DERIVE_TIMEOUT: "사면·경계 계산 시간이 초과됐습니다 — 비드 하나씩 계산하세요",
  PREVIEW_NOT_READY: "미리보기를 먼저 실행하세요",
  SELECT_FIXED_VIOLATION: "고정 노드 침범",
  SELECT_QUALITY_FAIL: "모핑 후 메시 품질 Fail 비율 초과",
  SELECT_MORPH_INVERTED: "모핑 후 요소 뒤집힘",
  // v0.16.1(esl_select_relax.md §10)
  SELECT_FIXED_MOVED: "체결 위치 어긋남 — 고정 노드가 모핑대로 움직였습니다",
  SELECT_QUALITY_WARN: "모핑 후 메시 품질 Fail 비율 초과(경고 — 실행함)",
  SELECT_INNER_LOOP: "섬이 아닌 안쪽 고리가 있어 그 둘레도 폭 변경에 따라 움직입니다",
  SELECT_ISLAND_TOO_LARGE: "둘러싸인 영역이 섬 크기 상한보다 커서 섬으로 보지 않았습니다",
  SELECT_ISLAND_SHEAR: "곡면 바닥이라 섬 평행 이동과 둘레 사이에 차이가 있습니다",
  SELECT_HOLD_NO_FIXED: "'체결 구멍 둘레 고정'을 켰지만 이 비드에 고정 노드가 없습니다",
  SELECT_HOLD_INVALID: "'체결 구멍 둘레 고정' 값이 올바르지 않습니다",
  // v0.16.1 R1c·통합(SR-D-25~28)
  SELECT_BEAD_NETWORK: "다른 비드와 이어져 있습니다(T·L 교차) — 교차부 사면은 가까운 바닥의 비드로 나눴습니다. 이웃 비드도 함께 선택했는지 확인하세요",
  SELECT_INNER_LOOP_RING: "고리형 비드 — 안쪽 둔덕 둘레도 폭 변경에 따라 움직입니다(정상)",
  SELECT_SLOPE_ABOVE_PLATE: "판 높이 위(경계에 걸친 보스 벽)로는 사면을 넓히지 않았습니다",
  SELECT_W_RANGE_RESET: "폭 W 기본 하한이 공칭보다 커서(국부 폭 오탐) 공칭을 포함하도록 고쳤습니다",
  SELECT_RANGE_INVERTS: "기본 범위 끝에서 요소가 뒤집힙니다 — 범위를 줄이거나 블렌딩 반경을 키우세요",
  // v0.16.1 어려운 사례 수정(SR-D-35~43)
  SELECT_BASE_AMBIGUOUS: "기준 평면을 정할 수 없습니다 — 교차하는 비드를 함께 선택하세요",
  SELECT_BASE_REFIT: "경계가 선택하지 않은 다른 비드를 지나 판 쪽 경계로 기준 평면을 다시 맞췄습니다 — 교차 비드도 함께 선택하세요",
  SELECT_FEATURE_DISTORTED: "바닥 안 비선택 피처가 바닥과 같이 움직이지 않아 형상이 찢어집니다(제외)",
  SELECT_CROSS_BEAD_MOVE: "폭 변화가 다른 선택 비드의 경계·바닥을 움직였습니다",
  SELECT_CROSS_BEAD_VIOLATION: "다른 선택 비드 침범(제외)",
  SELECT_RANGE_COMBO: "변수를 함께 바꾸면 뒤집히는 조합이 있습니다 — 함께 쓸 수 있는 범위를 확인하세요",
  SELECT_W_RANGE_LIMIT: "폭 W 범위 끝의 경계 이동이 단 간격·이웃 비드 거리보다 큽니다",
  // v0.16.2 자동 탐지·건너 잇기·극단 요소(esl_bead_auto.md §8)
  AUTO_DETECT_FAILED: "비드 자동 탐지에 실패했습니다 — 직접 선택으로 진행하세요",
  AUTO_TOO_MANY_BEADS: "자동 탐지 비드가 상한보다 많아 앞에서부터 잘랐습니다",
  AUTO_GROUP_DROPPED: "자동 탐지의 비드 묶음은 풀어서 가져왔습니다",
  AUTO_BEAD_UNMAPPED: "자동 탐지 비드의 바닥 요소를 메시에서 찾지 못했습니다",
  AUTO_SLOPE_DIFF: "자동 탐지 사면 폭이 계산한 사면과 다릅니다(참고)",
  AUTO_NOT_AVAILABLE: "자동 탐지 결과가 없습니다",
  SELECT_BRIDGE_SKIPPED: "큰 구멍은 건너 잇지 않았습니다",
  MORPH_EXTREME_ELEMENTS: "모핑 후 극단 요소(넓이 비·법선 회전)가 있습니다",
  // v0.17.0 비드 네트워크 분류기(esl_beadgraph.md §6.4)
  GRAPH_FAILED: "자동 분류 실패 — 직접 칠하기(요소 비드)로 계속",
  GRAPH_RASTER_COARSE: "큰 바닥은 골격 해상도를 낮춰 분류했습니다",
  GRAPH_NOT_AVAILABLE: "비드 분류 결과가 없습니다",
  AUTO_HINT_UNAVAILABLE: "STEP 비드 인식 힌트를 쓸 수 없습니다(자동 분류와 무관)",
  BG_GROUP_NOT_CONNECTED: "한 비드의 세그먼트가 접합 구역으로 이어져 있지 않습니다",
  BG_TIE_NOMINAL: "대칭으로 묶은 비드의 공칭 치수가 너무 다릅니다",
  BG_SEG_UNKNOWN: "분류 결과에서 찾을 수 없는 세그먼트가 있습니다 — 지우고 다시 고르세요",
  BG_EDIT_INVALID: "세그먼트 편집(전환·병합·분할)이 올바르지 않습니다",
  SELECT_SCHEMA_MISMATCH: "이 스터디의 선택 형식과 다릅니다 — 새로 고친 뒤 저장하세요",
  BG_GRAPH_STALE: "분류 결과가 바뀌었습니다 — 다시 확인 후 저장",
  BG_GROUP_NOMINAL_SPREAD: "묶은 세그먼트의 공칭 깊이가 서로 달라 평균을 공칭으로 씁니다",
  BG_SEGMENT_SHORT: "세그먼트가 접합 램프보다 짧아 기본 변수에서 뺐습니다",
  BG_RAMP_SHORT: "범위가 기본보다 넓어 접합 램프가 짧습니다",
  BG_SHARED_CHILD: "자식 바닥이 다른 변에도 닿아 제자리에 두고 벽이 높이 차를 흡수합니다",
  BG_CORNER_GUARD: "바닥 코너가 좁아 그 곳 사면을 가파르게 했습니다",
  BG_ISLAND_HELD: "섬 안 고정 노드를 제자리에 두었습니다",
  BG_RANGE_CLAMPED: "기본 W 범위 끝에서 요소가 뒤집혀 뒤집힘 없는 범위로 줄였습니다",
  BG_BASIS_LEAK: "기저가 허용 구역 밖을 움직입니다(구현 오류)",
  BG_ACHIEVED_MISMATCH: "목표 깊이를 정확히 얻지 못했습니다(구현 오류)",
  BG_OUTSIDE_MOVED: "바뀐 세그먼트 밖이 움직였습니다",
  // v0.18.0 ③ STEP 기준 select(esl_step_graph.md §4.2 — 원본 resources/doe_messages.json)
  STEP_GRAPH_TRIA: "삼각형 메시 — 걸친 보스가 있는 채널의 D·W 안은 바깥 이동으로 실패할 수 있음",
  STEP_GRAPH_TRIA_BLOCKED: "삼각형 메시로 끝나 준비를 멈췄습니다(서버 설정 tria_policy: block)",
  FIXED_XFER_NONE: "A 고정점을 옮기지 못했습니다 — 고정 층에 직접 칠하세요",
  FIXED_XFER_UNMATCHED: "옮기지 못한 A 고정 클러스터가 있습니다",
  STEP_GRAPH_REGION: "주 시트 밖 형상 — 평가·비드 후보 제외",
  STEP_GRAPH_REGION_SMALL: "평가 영역(주 시트)이 메시의 절반보다 작습니다 — 영역 설정을 확인하세요",
  STEP_GRAPH_ISLAND_AS_WALL: "벽으로 분류된 걸침 보스 후보 — 그 세그먼트의 D·W 안은 보스를 벽과 함께 움직임(트리에서 확인)",
};
/** v0.17.0 GRAPH_FAILED 사유(code) */
export const GRAPH_FAIL_REASON: Record<string, string> = { ERROR: "분류 오류", TIMEOUT: "시간 초과", TOO_LARGE: "요소 수 상한 초과", DISABLED: "서버에서 꺼짐", NO_FLOOR: "바닥을 찾지 못함" };
/** v0.17.0 띠 문구(§6.2) */
export const GRAPH_FAILED_TEXT = "자동 분류 실패 — 직접 칠하기(요소 비드)로 계속";
export const BG_STALE_TEXT = "분류 결과가 바뀌었습니다 — 다시 확인 후 저장";
/** GRAPH_FAILED 사유: 준비 경고 {code: "GRAPH_FAILED", message, detail} — 안쪽 사유는 detail 하나(AUTO_DETECT_FAILED 와 같은 형식) */
export function graphFailText(w: Record<string, unknown> | null | undefined): string {
  const c = typeof w?.detail === "string" && GRAPH_FAIL_REASON[w.detail] ? w.detail : undefined;
  return `자동 분류 실패${c ? `(${GRAPH_FAIL_REASON[c]})` : ""}`;
}
/** v0.18.0 FIXED_XFER_NONE 사유 */
export const XFER_NONE_REASON: Record<string, string> = { A_CASE_MISSING: "A Case 없음", A_SCAN_FAILED: "A 체결 스캔 실패", NO_MATCH: "대응 없음", DISABLED: "서버에서 꺼짐" };
/** v0.18.0 ③ 기준 메시 방식 칩(cad / 폴백 freeform / 삼각형 폴백 — esl_step_graph.md §6) */
export function meshMethodName(m: unknown): string {
  const k = String(m ?? "");
  return k === "cad" ? "CAD" : k === "freeform" ? "폴백 freeform" : k === "tria" ? "삼각형 폴백" : k === "refine" || k.startsWith("refine") ? "CAD 세분화" : k === "defeature" ? "형상 단순화" : k || "?";
}
/** v0.18.0 고정 이전 방법 문구(SG-D-13) */
export const XFER_METHOD_NAME: Record<DoeFixedXferMethod, string> = { xyz_nearest: "좌표 일치 — 최근접 노드", xyz_fitted: "구멍 맞춤 이동 — 최근접 노드", ab_hole_snap: "좌표 불일치 — B 구멍 스냅", none: "자동 설정 없음" };
/** v0.18.0 고정 이전 1줄: "A 고정 n개 중 m개를 옮김(좌표 일치 — 최근접 노드) — 고정 층에서 수정" */
export function xferText(x: DoePrepFixedXfer): string {
  const total = x.matched + x.unmatched;
  if (x.method === "none" || x.matched <= 0) return `A 고정점 자동 설정 없음${total ? `(A 고정 ${total}개 — 대응 없음)` : ""} — 고정 층에 직접 칠하세요`;
  return `A 고정 ${total}개 중 ${x.matched}개를 옮김(${XFER_METHOD_NAME[x.method]}) — 고정 층에서 수정${x.unmatched ? ` · 못 옮김 ${x.unmatched}개` : ""}`;
}
/** v0.18.0 평가 영역 1줄(SG-D-19) */
export const regionText = (r: { n_out: number }) => `주 시트 밖 형상 ${r.n_out.toLocaleString()} 요소 — 평가·비드 후보 제외`;
/** v0.18.0 ③ 선택 화면 요약에 모으는 준비 코드(① 입력 카드 목록에서는 뺌 — 한 번만 보이게) */
export const STEP_PREP_CODES = new Set(["STEP_GRAPH_TRIA", "STEP_GRAPH_TRIA_BLOCKED", "FIXED_XFER_NONE", "FIXED_XFER_UNMATCHED", "STEP_GRAPH_REGION", "STEP_GRAPH_REGION_SMALL", "STEP_GRAPH_ISLAND_AS_WALL"]);
type StepPrep = {
  fixed?: { source: string; n: number; xfer?: DoePrepFixedXfer | null } | null;
  region?: { n_out: number } | null;
  mesh?: { method?: string | null; tri_frac?: number | null } | null;
  warnings: DoeWarning[];
};
type FoldLine = { text: string; info: boolean; code: string };
/** v0.18.0 ③ select(step) 선택 화면 요약 — 주제마다 MsgFold 1줄(D-0.17.1-FOLD):
 *  fixed = 고정 이전 1줄(정보) + 못 옮긴 A 고정 목록, region = 평가 영역 1줄(정보) + 영역 작음 경고, mesh = 삼각형 메시 경고.
 *  요약 줄이 이미 말한 코드(FIXED_XFER_NONE·STEP_GRAPH_REGION)는 한 번만. 삼각형 경고는 서버 경고가 없으면 prep.mesh(방법 tria 또는 삼각 비율 > 기준)로 */
export function stepPrepGroups(prep: StepPrep | null | undefined, triaWarnFrac = 0.5): { fixed: FoldLine[]; region: FoldLine[]; mesh: FoldLine[] } {
  const g = { fixed: [] as FoldLine[], region: [] as FoldLine[], mesh: [] as FoldLine[] };
  if (!prep) return g;
  const ws = prep.warnings.filter((w) => STEP_PREP_CODES.has(w.code));
  const line = (w: DoeWarning): FoldLine => ({ text: warnText(w), info: isInfoWarn(w), code: w.code });
  const xfer = prep.fixed?.xfer ?? null;
  const noneW = ws.find((w) => w.code === "FIXED_XFER_NONE");
  if (xfer) g.fixed.push({ text: xferText(xfer), info: true, code: "FIXED_XFER" });
  else if (noneW) g.fixed.push(line(noneW));
  else if (prep.fixed?.source === "none") g.fixed.push({ text: "A 고정점 자동 설정 없음 — 고정 층에 직접 칠하세요", info: true, code: "FIXED_XFER_NONE" });
  g.fixed.push(...ws.filter((w) => w.code === "FIXED_XFER_UNMATCHED").map(line));
  const regionW = ws.find((w) => w.code === "STEP_GRAPH_REGION");
  if (prep.region && prep.region.n_out > 0) g.region.push({ text: regionText(prep.region), info: true, code: "STEP_GRAPH_REGION" });
  else if (regionW) g.region.push(line(regionW));
  g.region.push(...ws.filter((w) => w.code === "STEP_GRAPH_REGION_SMALL").map(line));
  const m = prep.mesh;
  const triaW = ws.filter((w) => w.code === "STEP_GRAPH_TRIA" || w.code === "STEP_GRAPH_TRIA_BLOCKED");
  if (triaW.length) g.mesh.push(...triaW.map(line));
  else if (m && (m.method === "tria" || (typeof m.tri_frac === "number" && m.tri_frac > triaWarnFrac)))
    g.mesh.push({ text: warnText({ code: "STEP_GRAPH_TRIA", mesh_method: m.method, tri_frac: m.tri_frac }), info: false, code: "STEP_GRAPH_TRIA" });
  g.mesh.push(...ws.filter((w) => w.code === "STEP_GRAPH_ISLAND_AS_WALL").map(line));  // SG-X-2(분류 — 메시 출처 문제)
  return g;
}
/** v0.16.2 자동 탐지 단계 이름(AUTO_DETECT_FAILED.step) */
const AUTO_STEP_NAME: Record<string, string> = { version: "형상 엔진 확인", assem_full: "조립 읽기", fixed: "체결 스캔", extract0: "형상 읽기", extract: "비드 인식", tag: "메시 대응" };
/** v0.16.2 정보 수준 자동 탐지 코드(서버가 level 을 안 줄 때도 ⓘ) */
const AUTO_INFO = new Set(["AUTO_GROUP_DROPPED", "AUTO_SLOPE_DIFF", "AUTO_HINT_UNAVAILABLE", "GRAPH_RASTER_COARSE", "BG_SHARED_CHILD", "BG_CORNER_GUARD", "BG_ISLAND_HELD", "BG_RANGE_CLAMPED", "FIXED_XFER_NONE", "FIXED_XFER_UNMATCHED", "STEP_GRAPH_REGION"]);
/** v0.16.2 자동 탐지·건너 잇기 경고 1줄(인자 포함) — 서버 문구가 없을 때. AUTO_DETECT_FAILED = {code, message, step, detail}(detail = 안쪽 paicad·코어 코드) */
function autoWarnText(w: Record<string, unknown>): string {
  const n = (v: unknown) => (typeof v === "number" ? Number(v.toFixed(1)).toString() : String(v ?? "?"));
  const B = (v: unknown) => String(v ?? "?").toUpperCase();
  switch (w.code) {
    case "AUTO_DETECT_FAILED":
      return `비드 자동 탐지 실패(${AUTO_STEP_NAME[String(w.step ?? "")] ?? String(w.step ?? "?")}${w.detail ? ` · ${String(w.detail)}` : ""}) — 직접 선택으로 진행하세요`;
    case "AUTO_TOO_MANY_BEADS":
      return w.n != null && w.max != null ? `자동 탐지 비드 ${n(w.n)}개 — 상한 ${n(w.max)}개까지만 가져왔습니다` : "";
    case "AUTO_BEAD_UNMAPPED":
      return w.bead != null ? `${String(w.bead).toUpperCase()}: 바닥 요소를 메시에서 찾지 못했습니다 — 직접 고르세요` : "";
    case "AUTO_SLOPE_DIFF":
      return w.bead != null && typeof w.rel === "number" ? `${String(w.bead).toUpperCase()}: 자동 탐지 사면 폭이 계산값과 ${(w.rel * 100).toFixed(0)} % 다릅니다(참고)` : "";
    case "SELECT_BRIDGE_SKIPPED":
      return w.eq_d_mm != null ? `등가 지름 ${n(w.eq_d_mm)} mm 구멍은 건너 잇지 않았습니다${w.gap_mm != null ? `(틈 ${n(w.gap_mm)} mm)` : ""}` : "";
    // v0.17.0 BG_*(esl_beadgraph.md §6.4)
    case "GRAPH_FAILED":
      return `${graphFailText(w)} — 직접 칠하기(요소 비드)로 계속`;
    case "BG_GROUP_NOT_CONNECTED":
      return w.bead != null ? `${B(w.bead)}: 세그먼트가 접합 구역으로 이어져 있지 않습니다 — 이웃 세그먼트만 한 비드로` : "";
    case "BG_TIE_NOMINAL":
      return Array.isArray(w.beads) ? `대칭 묶기 ${w.beads.map(B).join("·")}: 공칭 치수가 너무 다릅니다` : "";
    case "BG_SEG_UNKNOWN":
      return w.anchor != null ? `세그먼트(앵커 ${n(w.anchor)})를 분류 결과에서 찾지 못했습니다 — 지우고 다시 고르세요` : "";
    case "BG_GROUP_NOMINAL_SPREAD":
      return w.bead != null && w.min != null && w.max != null ? `${B(w.bead)}: 공칭 깊이 ${n(w.min)}~${n(w.max)} mm — 길이 가중 평균을 공칭으로` : "";
    case "BG_SEGMENT_SHORT":
      return w.bead != null && w.length_mm != null ? `${B(w.bead)}: 길이 ${n(w.length_mm)} mm < 램프 2×${n(w.ramp_mm)} mm — 기본 변수에서 뺐습니다` : "";
    case "BG_RAMP_SHORT":
      return w.var != null && w.L_mm != null ? `${String(w.var)}: 접합 램프 ${n(w.L_mm)} mm < 필요 ${n(w.need_mm)} mm(범위가 기본보다 넓음)` : "";
    case "BG_SHARED_CHILD":
      return w.bead != null ? `${B(w.bead)}: 자식 바닥 ${n(w.child)} 은 제자리 — 이 변의 벽이 높이 차를 흡수(${n(w.n_nodes)} 노드)` : "";
    case "BG_CORNER_GUARD":
      return w.bead != null ? `${B(w.bead)}: 바닥 코너 ${n(w.n_nodes)} 노드의 사면을 최대 ${n(w.flank_max_deg)}° 로 가파르게 했습니다` : "";
    // v0.18.0 ③ STEP 기준(esl_step_graph.md §4.2)
    case "STEP_GRAPH_TRIA":
      return `삼각형 메시(${meshMethodName(w.mesh_method)}${typeof w.tri_frac === "number" ? ` · 삼각 ${Math.round(w.tri_frac * 100)} %` : ""}) — 걸친 보스가 있는 채널의 D·W 안은 바깥 이동으로 실패할 수 있음`;
    case "FIXED_XFER_NONE":
      return `A 고정점 자동 설정 없음(${XFER_NONE_REASON[String(w.reason ?? "")] ?? String(w.reason ?? "?")}) — 고정 층에 직접 칠하세요`;
    case "FIXED_XFER_UNMATCHED":
      return w.label != null ? `A 고정 ${String(w.label)}: B 에서 대응을 못 찾음${typeof w.d_mm === "number" ? `(최소 ${n(w.d_mm)} mm)` : ""} — 필요하면 고정 층에 칠하세요` : "";
    case "STEP_GRAPH_REGION":
      return typeof w.n_out === "number" ? regionText({ n_out: w.n_out }) : "";
    case "BG_RANGE_CLAMPED":
      return w.var != null && Array.isArray(w.from) && Array.isArray(w.to)
        ? `${String(w.var)}: 기본 범위 ${n(w.from[0])}~${n(w.from[1])} mm 끝에서 뒤집혀 ${n(w.to[0])}~${n(w.to[1])} mm 로 줄였습니다`
        : "";
    case "BG_ISLAND_HELD":
      return w.island != null ? `섬 ${n(w.island)}: 고정 노드가 있어 제자리 블렌딩` : "";
    case "BG_OUTSIDE_MOVED":
      return w.n != null && w.max_mm != null ? `바뀐 세그먼트 밖 ${n(w.n)} 노드가 최대 ${n(w.max_mm)} mm 움직였습니다` : "";
    default:
      return "";
  }
}
/** v0.16.1 derive 경고 코드(비드·선택 warnings[].code — 서버 문구 원본 resources/doe_messages.json) */
export type SelectDeriveWarnCode =
  | "SELECT_SLOPE_LEAK" | "SELECT_TIER_MISSING" | "SELECT_OPEN_BOUNDARY" | "SELECT_DISCONNECTED" | "SELECT_NONPLANAR_BASE"
  | "SELECT_BLEND_OVERLAP" | "SELECT_BLEND_CLIPPED" | "SELECT_FIXED_IN_BEAD" | "SELECT_FIXED_IN_BLEND" | "SELECT_WIDTH_UNDEFINED"
  | "SELECT_FIXED_LAYER_OVERLAP" | "SELECT_INNER_LOOP" | "SELECT_ISLAND_TOO_LARGE" | "SELECT_ISLAND_SHEAR"
  | "SELECT_HOLD_NO_FIXED" | "SELECT_BEAD_NETWORK" | "SELECT_SLOPE_ABOVE_PLATE" | "SELECT_W_RANGE_RESET" | "SELECT_RANGE_INVERTS"
  | "SELECT_BASE_REFIT" | "SELECT_RANGE_COMBO" | "SELECT_W_RANGE_LIMIT";

const mm1 = (v: number) => (v < 10 ? Number(v.toFixed(2)).toString() : v.toFixed(1));
/** v0.16.1 안 경고 1줄(§8): FIXED_MOVED = "고정 노드 n개, 최대 x mm 이동", QUALITY_WARN = "새 Fail m (r %)" */
export function cellWarnText(w: DoeCellWarning): string {
  if (w.code === "SELECT_FIXED_MOVED") return `고정 노드 ${w.n.toLocaleString()}개, 최대 ${mm1(w.max_mm)} mm 이동`;
  if (w.code === "SELECT_CROSS_BEAD_MOVE") return `다른 비드 경계·바닥 ${w.n.toLocaleString()}노드, 최대 ${mm1(w.max_mm)} mm 이동`;
  const ext = w.area_ratio_min != null || w.rot_max_deg != null
    ? ` · 넓이 비 최소 ${Number(w.area_ratio_min ?? 1).toFixed(2)} · 법선 회전 ${Math.round(Number(w.rot_max_deg ?? 0))}°` : "";
  return `새 Fail ${w.new_fail.toLocaleString()} (${(w.new_fail_ratio * 100).toFixed(1)} %)${ext}`;
}
/** 순위 행 경고 이름 */
export const RANK_WARN_NAME: Record<string, string> = { FIXED_MOVED: "체결 위치 어긋남", QUALITY_WARN: "품질 경고", CROSS_BEAD_MOVE: "다른 비드 침범", MORPH_EXTREME_ELEMENTS: "극단 요소" };
/** v0.16.1 판정 규칙 판 띠(§7.4) */
export const RULES_OUTDATED_TEXT = "판정 규칙이 바뀌었습니다 — 다시 미리보기하면 경고 안도 실행됩니다";

// ---------------------------------------------------------------- v0.14.0 ④ 형상 직접 비교(esl_step_compare.md)
/** 민감도 숨김 사유(결과 sensitivity_reason) */
export const SENS_REASON: Record<string, string> = {
  COMPARE_NO_PARAMS: "형상 직접 비교는 변수가 없어 민감도를 계산하지 않습니다 — 형상 이름 표로 비교하세요",
};
/** ④ 형상 상태 사유 코드(재사용 코드 — 서버 메시지가 없을 때만) */
const SHAPE_CODE_TEXT: Record<string, string> = {
  STEP_INVALID: "STEP 파일이 올바르지 않습니다",
  MESH_FAILED: "메시 생성 실패",
  MESH_TOO_LARGE: "메시 요소 수 상한 초과",
  SIZE_MISMATCH: "기준 형상과 ESL 의 크기가 다릅니다",
  SUPPORT_DEGENERATE: "지지 조건을 만들지 못했습니다",
  // v0.16.0 메시 옵션(서버 message 가 없을 때만)
  REMESH_FAILED: "삼각형 재메시에 실패했습니다 — 특징각을 키우거나 메시 파일로 올리세요",
  REMESH_CLASSIFY_FAILED: "면 분류에 실패했습니다",
  REMESH_STL_EMPTY: "STEP 에서 삼각화를 만들지 못했습니다(면 없음)",
  REMESH_FIDELITY: "재메시가 원 형상과 너무 다릅니다",
  REMESH_UNAVAILABLE: "이 gmsh 버전은 삼각형 재메시를 지원하지 않습니다",
  MESH_FORMAT_UNSUPPORTED: "지원하지 않는 메시 형식입니다(.rad·.inc 만)",
  MESH_INPUT_INVALID: "메시 파일을 읽지 못했습니다",
  MESH_INPUT_PART_REQUIRED: "쉘 파트가 여러 개입니다 — 파트 ID 를 고르세요",
  MESH_INPUT_PART_NOT_FOUND: "파트 ID 가 메시에 없습니다",
  MESH_INPUT_UNSUPPORTED_ELEMENT: "파트에 쉘이 아닌 요소가 있습니다",
  MESH_INPUT_UNIT: "메시 길이 단위가 mm 가 아닙니다",
  MESH_INPUT_TOO_LARGE: "메시 파일(주 + include) 합계가 상한을 넘었습니다",
  PATH_OUTSIDE_ROOT: "include 경로가 업로드 폴더 밖입니다",
};
export const shapeCodeText = (code: string | null | undefined) => (code ? CODE_TEXT[code] ?? SHAPE_CODE_TEXT[code] ?? code : "");
/** 이름 규칙(§3): 앞뒤 공백 제거 1~64자, 제어문자 금지, 대소문자 무시 중복 금지 */
export const SHAPE_NAME_MAX = 64;
// eslint-disable-next-line no-control-regex
const CTRL = /[\u0000-\u001f\u007f]/;
export function shapeNameProblem(name: string, all: string[], index: number): string | null {
  const n = name.trim();
  if (!n) return "이름을 입력하세요";
  if (n.length > SHAPE_NAME_MAX) return `이름은 ${SHAPE_NAME_MAX}자 이하입니다`;
  if (CTRL.test(n)) return "이름에 제어문자를 쓸 수 없습니다";
  const k = n.toLowerCase();
  if (all.some((x, i) => i !== index && x.trim().toLowerCase() === k)) return "이름이 겹칩니다(대소문자 무시)";
  return null;
}
/** 파일 이름 → 기본 형상 이름(확장자 제외, 64자) */
export const defaultShapeName = (file: string) => file.replace(/\.[^.]+$/, "").slice(0, SHAPE_NAME_MAX);
/** 형상 표 전체 규칙(§3 순서): 개수·기준 1개·이름. null = 통과 */
export function shapesProblem(shapes: { name: string }[], hasRef: boolean, maxShapes: number): string | null {
  if (!shapes.length) return "비교할 STEP 을 올리세요";
  if (shapes.length > maxShapes) return `STEP 은 최대 ${maxShapes}개입니다`;
  if (hasRef ? shapes.length < 2 : shapes.length < 1) return "기준 STEP 외에 비교할 STEP 을 하나 이상 올리세요";
  const names = shapes.map((s) => s.name);
  for (let i = 0; i < names.length; i++) {
    const why = shapeNameProblem(names[i], names, i);
    if (why) return `형상 ${i + 1}: ${why}`;
  }
  return null;
}
// ---------------------------------------------------------------- v0.16.0 ④ 메시 옵션(esl_compare_mesh_options.md §8)
export const STEP_EXT = [".step", ".stp"];
/** 파일 이름 → 형상 출처 기본값(확장자, §8). 그 밖 = null */
export function shapeKindOf(file: string, meshFormats: string[] = [".rad", ".inc"]): "step" | "mesh" | null {
  const f = file.toLowerCase();
  if (STEP_EXT.some((x) => f.endsWith(x))) return "step";
  if (meshFormats.some((x) => f.endsWith(x.toLowerCase()))) return "mesh";
  return null;
}
/** 메시 묶음 주 파일 후보(C2-D-2 규칙 = 서버 doe_source(kind mesh)): *_0000.rad 1개 → .rad 1개 → (.rad 없으면) .inc 1개.
 *  정해지면 [그 파일], 못 정하면 후보 전부(.rad 가 있으면 .rad, 없으면 .inc — 화면에서 고름) */
export function meshMainCandidates(names: string[]): string[] {
  const rad = names.filter((n) => /\.rad$/i.test(n));
  const z = rad.filter((n) => /_0000\.rad$/i.test(n));
  if (z.length === 1) return z;
  if (rad.length === 1) return rad;
  if (rad.length) return [...(z.length ? z : rad)].sort();
  return names.filter((n) => /\.inc$/i.test(n)).sort();
}
/** part_id 칸 검사(빈 칸 = 서버가 파트 하나면 자동, C2-D-4) */
export function partIdProblem(v: string): string | null {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isInteger(n) && n >= 1 && n <= 2 ** 31 - 1 ? null : "파트 ID 는 1 이상 정수입니다";
}
/** check-inputs 오류에 실린 파트 목록(422 MESH_INPUT_PART_REQUIRED detail.parts, detail.index) */
export function partsFromError(e: unknown): { index: number; parts: DoeMeshPart[] } | null {
  if (!(e instanceof ApiError) || typeof e.detail.index !== "number" || !Array.isArray(e.detail.parts)) return null;
  return { index: e.detail.index, parts: (e.detail.parts as unknown[]).filter((p): p is DoeMeshPart => isObj(p) && typeof p.id === "number") as DoeMeshPart[] };
}
export const MESH_MODE_NAME: Record<DoeMeshMode, string> = { auto: "자동", cad: "CAD", remesh: "재메시", freeform: "freeform" };
export const MESH_MODE_HINT: Record<DoeMeshMode, string> = {
  auto: "CAD 메시가 실패한 형상만 다시 시도(성공한 형상은 그대로): 크기 문제면 세분화, 특정 면 실패면 바로 freeform 재메시 → OCC 삼각형 폴백",
  cad: "CAD 면 구조 그대로 gmsh 메시(v0.15 방식)",
  remesh: "모든 STEP 을 삼각형 재메시(CAD 면 구조를 버림 — 원 형상과 편차 표시)",
  freeform: "CAD 면 경계를 따르지 않는 이산 재메시를 바로(CAD 메시 생략, 실패하면 OCC 삼각형 폴백) — 작은 특징선·구멍이 번질 수 있음",
};
/** remesh_available false 사유(REMESH_UNAVAILABLE 문구) */
export const remeshUnavailableText = (ver: string | null | undefined) => `이 gmsh 버전(${ver ?? "?"})은 삼각형 재메시를 지원하지 않습니다`;
/** 메시 방식 짧은 배지(순위표·ESL별 표) */
export const MESH_METHOD_SHORT: Record<DoeMeshMethod, string> = { cad: "CAD", refine: "세분화", remesh: "재메시", fallback: "재메시(폴백)", mesh_input: "메시 입력", defeature: "형상 단순화" };
/** v0.16.1 억제 종류 이름(§8 툴팁 "구멍 a · 딤플 b · 필렛 c") */
export const DEFEATURE_KIND_NAME: Record<DoeDefeatureKind, string> = { hole: "구멍", slot: "슬롯", flange: "버링", bead: "딤플", fillet: "필렛", narrow: "좁은 띠" };
const KIND_ORDER: DoeDefeatureKind[] = ["hole", "slot", "flange", "bead", "fillet", "narrow"];
/** 억제 요약 1줄: "구멍 1 · 딤플 1 · 필렛 3 억제, 억제 영역 최대 2.5 mm, 그 밖 0.12 mm" */
export function defeatureText(d: DoeShapeDefeature): string {
  const parts = KIND_ORDER.filter((k) => (d.counts?.[k] ?? 0) > 0).map((k) => `${DEFEATURE_KIND_NAME[k]} ${d.counts[k]}`);
  const out = [`${parts.length ? parts.join(" · ") : `작은 형상 ${d.n}개`} 억제`];
  if (d.suppressed_max_mm != null) out.push(`억제 영역 최대 ${mm1(d.suppressed_max_mm)} mm`);
  if (d.outside_hausdorff_mm != null) out.push(`그 밖 ${mm1(d.outside_hausdorff_mm)} mm`);
  return out.join(", ") + (d.skipped_n ? ` (건너뜀 ${d.skipped_n})` : "");
}
/** 특징 크기 문구: Ø5 / 1.9×12 / h 1.5 / r 1.5 */
export function featureSizeText(f: DoeDefeatureFeature): string {
  const z = f.size ?? {};
  const n = (v: number) => Number(v.toFixed(2)).toString();
  if (z.d_mm != null) return `Ø${n(z.d_mm)}`;
  if (z.w_mm != null && z.l_mm != null) return `${n(z.w_mm)}×${n(z.l_mm)}`;
  if (z.h_mm != null) return `h ${n(z.h_mm)}`;
  if (z.r_mm != null) return `r ${n(z.r_mm)}`;
  return "–";
}
/** v0.16.1 메시 입력 진단 글자(있을 때만): "작은 구멍 n · 섬 m" */
export function diagText(d: DoeShapeDiag | null | undefined): string | null {
  if (!d || (!d.holes_small_n && !d.islands_n)) return null;
  return [d.holes_small_n ? `작은 구멍 ${d.holes_small_n}` : null, d.islands_n ? `섬 ${d.islands_n}` : null].filter(Boolean).join(" · ");
}
type MeshShape = Pick<DoePrepShape, "mesh_method" | "refine" | "fidelity"> & { defeature?: DoeShapeDefeature | null; attempts?: DoeMeshAttempt[] | null; cad_error?: DoePrepShape["cad_error"]; refine_bias?: DoeShapeRef["refine_bias"]; edge_median_mm?: number | null; n_components?: number | null; source?: DoePrepShape["source"] };
const x1 = (v: number) => `×${Number(v.toFixed(2))}`;
const mm = (v: number) => `${Number(v.toFixed(2))} mm`;
/** '메시 방식' 열 문구(§8): CAD / 세분화(국부 ×0.5 · 1.5 mm · 면 3 · 요소 ×1.4) / 세분화(전역 2.4 mm · 요소 ×1.6) / 재메시 / 재메시(폴백) / 메시 입력 */
export function meshMethodLabel(s: MeshShape): string {
  const m = s.mesh_method;
  if (!m) return "–";
  if (m !== "refine" || !s.refine) return MESH_METHOD_SHORT[m];
  const r = s.refine;
  const ratio = r.elem_ratio_ref ?? r.elem_ratio_h;
  const parts =
    r.kind === "local"
      ? [`국부 ${x1(r.factor)}`, mm(r.h_mm), ...(r.faces?.length ? [`면 ${r.faces.length}`] : [])]
      : [`전역 ${mm(r.h_mm)}`];
  if (ratio != null) parts.push(`요소 ×${ratio.toFixed(1)}`);
  return `세분화(${parts.join(" · ")})`;
}
const SKIP_REASON: Record<string, string> = { elems: "요소 상한", memory: "메모리", time: "시간 예산", no_feature: "억제 대상 없음", not_compound: "병합 면 실패 아님" };
const STAGE_NAME: Record<string, string> = { cad: "CAD", refine_local: "국부 세분화", refine_global: "전역 세분화", defeature: "형상 단순화", remesh: "재메시", freeform: "freeform 재메시", tria: "삼각형 폴백" };
function attemptText(a: DoeMeshAttempt): string {
  const head = [STAGE_NAME[a.stage] ?? a.stage, a.factor != null && a.stage.startsWith("refine") ? x1(a.factor) : null, a.h_mm != null ? mm(a.h_mm) : null].filter(Boolean).join(" ");
  if (a.skipped) return `${head} — 건너뜀(${SKIP_REASON[a.reason ?? ""] ?? a.reason ?? a.code ?? "상한"})`;
  const ok = a.status === "OK" || a.status === "READY" || a.status === "SUCCEEDED";
  const tail = [ok ? "성공" : `실패${a.code ? ` ${a.code}` : ""}`, a.n_elems != null ? `요소 ${a.n_elems.toLocaleString()}` : null, a.seconds != null ? `${Math.round(a.seconds)} s` : null].filter(Boolean).join(" · ");
  return `${head} — ${tail}`;
}
/** '메시 방식' 툴팁(§8): 충실도 · CAD 첫 오류 · 시도 목록(건너뛴 사유) · 수렴 δ · 메시 입력(파트 ID·요소 크기 중앙값) */
export function meshMethodTip(s: MeshShape, partId?: number | null): string {
  const out: string[] = [];
  if (s.mesh_method === "mesh_input") {
    if (s.source === "case") out.push("기준 Case 낙하 메시");
    if (partId != null) out.push(`파트 ID ${partId}`);
    if (s.edge_median_mm != null) out.push(`요소 크기 중앙값 ${mm(s.edge_median_mm)}`);
    if (s.n_components != null && s.n_components > 1) out.push(`연결 성분 ${s.n_components}개`);
  }
  if (s.fidelity) {
    const f = s.fidelity;
    out.push(`최대 편차 ${f.max_dev_mm.toFixed(2)} mm · 면적비 ${f.area_ratio.toFixed(2)}x`);
    out.push(`Hausdorff ${f.hausdorff_mm.toFixed(2)} mm(경고 ${f.warn_mm} mm${f.fail_mm != null ? ` · 실패 ${f.fail_mm} mm` : ""}) · 원 CAD 대비 ≤ ${(f.hausdorff_mm + f.deflection_mm).toFixed(2)} mm`);
  }
  if (s.mesh_method === "defeature" && s.defeature) out.push(defeatureText(s.defeature));
  if (s.cad_error) out.push(`CAD 실패: ${s.cad_error.message || s.cad_error.code}`);
  const atts = s.refine?.attempts?.length ? s.refine.attempts : s.mesh_method === "defeature" ? s.attempts ?? null : null;
  if (atts?.length) out.push("시도:", ...atts.map((a, i) => `${i + 1}. ${attemptText(a)}`));
  if (s.refine_bias) {
    const b = s.refine_bias;
    out.push(`수렴 점검 δ 최대 ${pctText(b.delta_max, 1)} (기준을 ${mm(b.h_mm)} 로 다시 해석${b.tol != null ? ` · 허용 ${pctText(b.tol, 1)}` : ""})${b.over_tol ? " — 메시 편향 큼" : ""}`);
  }
  return out.join("\n");
}
const LADDER_LABEL: Record<string, string> = { refine_local: "세분화", refine_global: "세분화", defeature: "형상 단순화", remesh: "재메시", freeform: "freeform 재메시", tria: "삼각형 폴백" };
type FailShape = Pick<DoePrepShape, "status" | "code" | "message" | "cad_error" | "attempts">;
/** auto 사다리가 모두 실패한 형상 문구(워커 _ladder_fail_text 와 같은 틀): "CAD 메시 실패: … → 세분화·재메시도 실패: …".
 *  cad_error 가 없으면 원 message(없으면 코드 문구) */
export function shapeFailText(r: FailShape): string {
  const last = r.message || shapeCodeText(r.code);
  const ce = r.cad_error;
  if (!ce) return last;
  const cad = ce.message || ce.code;
  const tried: string[] = [];
  for (const a of r.attempts ?? []) {
    const lb = LADDER_LABEL[a.stage];
    if (lb && !a.skipped && !tried.includes(lb)) tried.push(lb);
  }
  if (!tried.length) {
    const why = [...new Set((r.attempts ?? []).filter((a) => a.skipped && a.reason).map((a) => a.reason as string))].sort();
    return `CAD 메시 실패: ${cad} → 세분화·재메시는 건너뜀(${why.join(", ") || "-"})`;
  }
  return `CAD 메시 실패: ${cad} → ${tried.join("·")}도 실패: ${last || "?"}`;
}
/** 실패 행 툴팁: 문구 + 시도 목록 */
export function shapeFailTip(r: FailShape): string {
  const out = [shapeFailText(r)];
  if (r.cad_error && r.attempts?.length) out.push("시도:", ...r.attempts.map((a, i) => `${i + 1}. ${attemptText(a)}`));
  return out.join("\n");
}
/** 배지 색: 충실도 경고·수렴 편향 초과 = 주황, 세분화·재메시 = info, 그 밖 = neutral */
export function meshMethodKind(s: MeshShape): "warn" | "info" | "neutral" {
  if (s.fidelity?.over_warn || s.refine_bias?.over_tol) return "warn";
  return s.mesh_method === "refine" || s.mesh_method === "remesh" || s.mesh_method === "fallback" || s.mesh_method === "defeature" ? "info" : "neutral";
}

/** ④ 오류 문구(detail.index 가 있으면 형상 번호 붙임) */
export function compareErrorText(e: unknown): string {
  const base = errorText(e);
  if (e instanceof ApiError && typeof e.detail.index === "number") return `${base} (형상 ${e.detail.index + 1})`;
  return base;
}

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
