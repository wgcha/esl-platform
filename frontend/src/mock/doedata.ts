// v0.9.0 비드 형상 DOE 목 API(계약 esl_bead_doe.md §10). MockServer.handle 이 /doe/* 를 여기로 넘긴다.
// 준비·미리보기·실행 작업(DOE_PREP·DOE_PREVIEW·DOE_RUN)은 목 서버 대기열로 돌고, 끝나면 GET 시점에 연구 상태를 채운다.
// 행렬·셀 상태·순위·민감도는 입력에서 결정적으로 만든다(같은 spec → 같은 sha·같은 결과).
import type {
  DoeDefeatureFeature, DoeDefeatureList, DoeRankWarn,
  CompareShapeIn, DoeBead, DoeCheckOut, DoeCheckShape, DoeDesignStatus, DoeExcluded, DoeFileOut, DoeMatrixOut, DoeMethodSources, DoeParam, DoeParamsOut, DoePlanLink, DoePlanOut,
  DoeMeshMethod, DoeMeshMode, DoeMeshPart, DoePrepShape, DoePreviewCell, DoeRankRow, DoeResultOut, DoeScenario, DoeSettingsOut, DoeShapeQuality, DoeShapeRef, DoeSpec, DoeStudyOut, DoeWarning, EntryOut, JobOut, JobType, Me, MeshCheckOut, XY,
} from "../api/types";
import { mockView3d } from "./view3dmock";
import type { DoeSelectAutoOut, DoeSelectionAny, DoeSelectionIn, DoeSelectionOut, DoeSelectionV2 } from "../api/types";
import { graphAutoSeed, graphBasis, graphDerive, graphManifest, graphMesh, graphOut, graphParams, graphPlan, graphValidate, stepAutoSeed, stepPlan } from "./graphmock";
import { selAutoSeed, selBasis, selCellStatus, selColorMax, selDefaultSelection, selDerive, selManifest, selMesh, selParams, selPlan, selThumbSvg, selValidate } from "./selectmock";

interface MockResponse {
  status: number;
  body?: unknown;
}
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResponse => ({ status, body: { detail: { code, message, ...extra } } });
const ok = (body: unknown, status = 200): MockResponse => ({ status, body });

export interface DoeCtx {
  entries: () => EntryOut[];
  me: () => Me;
  canRun: (projectId: string) => boolean;
  newJob: (projectId: string, jt: JobType, params: Record<string, unknown>) => JobOut;
  jobs: () => JobOut[];
  now: () => string;
  upload: (id: string) => { project_id: string; ready: boolean; files: string[]; state: string } | null;
  markUploadCompleted: (id: string) => void;
}

// ---------------------------------------------------------------- 설정·방법 출처(원본 resources/doe_method_sources.json 형식)
export const DOE_METHOD_SOURCES: DoeMethodSources = {
  version: "2026-11-04.1",
  summary_ko: [
    "선택한 ESL(낙하 t* 한 시점의 등가정적하중)을 비드 형상 안마다 같은 지지(3-2-1)로 선형 정적 해석합니다.",
    "순위 = 선택 ESL 중 최악 컴플라이언스 ÷ 베이스라인(공칭) 최악 컴플라이언스 — 작을수록 강성이 좋습니다.",
  ],
  methods: {
    lhs: "LHS(라틴 하이퍼큐브): 변수마다 범위를 안 수만큼 층으로 나눠 층당 1점 — 적은 안으로 고르게",
    halton: "Halton(뒤섞음): 저불일치 수열 — 안 수를 늘려도 고르게 채움",
    fullfact: "풀 팩토리얼: 변수별 등간격 수준의 모든 조합(수준^변수 개수)",
  },
  metrics: {
    score: "score = max_i C(안, ESL i) / max_i C(공칭, ESL i), 개선율 = 1 − score",
    src: "SRC: 정규화 변수 → score 선형 회귀의 표준화 계수(부호 = 방향)",
    spearman: "Spearman ρ: 순위 상관(단조 관계, 비선형도 포착)",
  },
  limits: ["선형 강성 비교입니다(낙하 응답 재현 아님).", "ESL 은 원 형상에서 정의돼 형상 변화 후 하중 재분배를 반영하지 않습니다."],
  sources: [
    { title: "Structural optimization using equivalent static loads at all time intervals", authors: "Park, G.J., Kang, B.S. 계열", note: "ESL 정의 K_L·u(서지만)" },
    { title: "Altair OptiStruct — Equivalent Static Load Method (ESLM)", authors: "Altair Engineering", url: "https://help.altair.com/2024/hwsolvers/os/topics/solvers/os/opt_composite_equiv_static_load_method_c.htm" },
    { title: "A comparison of three methods for selecting values of input variables in the analysis of output from a computer code", authors: "McKay, Beckman, Conover (1979)", note: "LHS" },
    { title: "SciPy — scipy.stats.qmc.Halton", url: "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.Halton.html" },
    { title: "physicsai paicad 형상 엔진 계약 shell-morph.md", note: "비드 파라미터·feasible·모핑" },
  ],
};

export function makeDoeSettings(): DoeSettingsOut {
  return {
    enabled: true,
    reason: null,
    paicad: { ready: true, version: "0.14.0", pinned: "0.14.0", warning: null },
    gmsh: { ready: true, version: "4.13.1" },
    scenarios: { same: true, mesh: true, step: true, compare: true, select: true, select_auto: true, select_mesh: true, select_step: true },
    max_entries: 50,
    max_designs: 200,
    doe: { methods: ["lhs", "halton", "fullfact"], default_method: "lhs", default_n: 30, seed: 1, levels_default: 3, levels_max: 9, default_types: ["D", "W"] },
    mesh: { size_auto: true, size_min_mm: 1, size_max_mm: 20 },
    boundary: { fastener_warn_mm: 10, load_warn_mm: 20, load_share_min: 0.2 },
    step_max_mb: 200,
    part_title: "chassis rear",
    method_sources: DOE_METHOD_SOURCES,
    compare_reason: null,
    compare: {
      enabled: true,
      reason: null,
      max_shapes: 20,
      total_max_mb: 1000,
      mesh_size_mm: 3,
      // v0.16.0 메시 옵션(esl_compare_mesh_options.md §6 GET /doe/settings compare)
      mesh_mode: "auto",
      remesh_available: true,
      mesh_input: { enabled: true, formats: [".rad", ".inc"], max_mb: 500 },
      step_ready: true,
      // v0.16.1(esl_select_relax.md §4.4)
      mesh: { ladder: ["cad", "refine_local", "refine_global", "freeform", "defeature", "tria"] },
      defeature: { hole_max_d_mm: 8, min_bead_height_mm: 2, fillet_max_r_mm: 1.5, kinds: ["flange", "hole", "slot", "bead", "fillet", "narrow"] },
    },
    select: {
      enabled: true, reason: null, feature_angle_deg: 15, max_beads: 20, max_tiers: 6, blend: { min_mm: 15, max_mm: 200, k: 8 },
      // v0.16.1 SR-D-2·9
      fixed_policy: "warn", quality_fail_policy: "warn", hold: { ring_mm: 3, blend_mm: 8 },
      // v0.16.2 AD-D-7
      hole: { bridge_max_mm: 20 },
      // v0.17.0 BEADGRAPH(§5.5)
      graph: { enabled: true, island: { max_mm: 60 }, sym_tol_mm: 0.5 },
      // v0.18.0 STEP_GRAPH(esl_step_graph.md §4.2)
      step_graph: { tria_policy: "warn" },
    },
  };
}

// ---------------------------------------------------------------- 비드·변수(paicad extract 모양)
const L = 1660;
const H = 947;
const BEADS: DoeBead[] = [
  { id: "B1", k: 1, shape: "linear", sense: "concave", center_ab: [420, 620], nominal: { depth: 4.0, width: 12, length: 520 }, fixed_overlap: false, png: "B1.png" },
  { id: "B2", k: 2, shape: "linear", sense: "convex", center_ab: [1240, 620], nominal: { depth: 3.5, width: 10, length: 460 }, fixed_overlap: false, png: "B2.png" },
  { id: "B3", k: 3, shape: "linear", sense: "convex", center_ab: [830, 300], nominal: { depth: 3.0, width: 14, length: 700 }, fixed_overlap: false, png: "B3.png" },
  { id: "B4", k: 4, shape: "circular", sense: "concave", center_ab: [830, 640], nominal: { depth: 2.5, width: 60 }, fixed_overlap: false, png: "B4.png" },
  { id: "B5", k: 5, shape: "circular", sense: "concave", center_ab: [180, 160], nominal: { depth: 2.0, width: 40 }, fixed_overlap: true, png: "B5.png" },
];
const p = (bead: string, k: number, type: DoeParam["type"], nominal: number, feasible: XY, use_default: boolean, group: string[] = []): DoeParam => ({
  name: `CHR_BEAD_${type}_${k}`,
  type,
  bead,
  nominal,
  feasible,
  feasible_source: "estimate",
  default_range: feasible,
  use_default,
  group_members: group,
});
export const PARAMS: DoeParam[] = [
  p("B1", 1, "D", 4.0, [2.1, 6.4], true),
  p("B1", 1, "W", 12, [8, 16], true),
  p("B1", 1, "U", 420, [380, 460], true),
  p("B1", 1, "V", 620, [590, 650], true),
  p("B2", 2, "D", 3.5, [1.8, 5.6], true),
  p("B2", 2, "W", 10, [7, 14], true),
  p("B3", 3, "D", 3.0, [1.5, 5.0], true, ["CHR_BEAD_D_4"]),
  p("B3", 3, "W", 14, [10, 18], true, ["CHR_BEAD_W_4"]),
  p("B5", 5, "D", 2.0, [1.0, 3.0], false),
];
const DEFAULT_PARAMS = PARAMS;
const PARAM_WARNINGS: DoeWarning[] = [
  { code: "BEAD_FIXED_OVERLAP", bead: "B5", message: "B5 비드가 체결 고정 영역과 겹쳐 기본 제외했습니다." },
  { code: "BEAD_NEAR_FIXED", bead: "B4", message: "B4 비드가 체결부에서 6.2 mm 떨어져 있습니다(넓히면 고정 침범 가능)." },
];

/** v0.17.1 긴 사다리 경고(워커 문구 형식 — esl/doe/stages.py·mesh_remesh.py·mesh_tria.py) */
const LADDER_STAGES = "cad 실패 412.3 s → refine_local 건너뜀(병합 면 실패 아님) → refine_global 실패(시간 초과) 600.0 s → defeature 건너뜀(억제 대상 없음) → remesh 실패 88.1 s → freeform 성공 131.7 s";
export const LADDER_WARNINGS: DoeWarning[] = [
  {
    code: "MESH_FREEFORM",
    message: `[단계별: ${LADDER_STAGES}] CAD 면 경계를 따르지 않는 freeform 재메시(특징각 40°·곡선각 30°)입니다 — 요소 변이 작은 CAD 특징선을 따르지 않을 수 있습니다. 원 형상 대비 최대 0.214 mm. 지름 4.5 mm 미만 구멍 17개는 번질 수 있습니다(메시에서 사라진 구멍 3개)`,
  },
  {
    code: "MESH_TRIA_FALLBACK",
    message: "CAD 면 메시·이산 재메시가 모두 실패해 OCC 삼각화(BRepMesh, 편차 0.05 mm)를 그대로 삼각형 쉘로 썼습니다(삼각형 48211개, 4각 0 %, 원 형상 대비 최대 0.031 mm). 삼각형 요소는 4각보다 굽힘 강성이 조금 높게 나올 수 있습니다",
  },
  { code: "AUTO_TOO_MANY_BEADS", n: 24, max: 20, message: "자동 탐지 비드 24개가 상한 20개(select.max_beads)를 넘어 앞에서부터 20개만 초기 선택에 넣었습니다." },
  { code: "BG_GROUP_NOMINAL_SPREAD", message: "비드 B3: 묶은 세그먼트의 공칭 깊이가 3.8~5.1 mm 로 달라 길이 가중 평균을 공칭으로 씁니다(변화량은 같음)." },
  { code: "AUTO_GROUP_DROPPED", level: "info", message: "(정보) paicad 대칭 묶음(group)은 초기 선택에 넣지 않았습니다 — 비드마다 따로 변수가 됩니다." },
  { code: "BG_SHARED_CHILD", level: "info", message: "(정보) 비드 B2: 공유 자식 바닥 s14 은 제자리이고 그 벽 212 노드가 높이 차를 흡수합니다." },
];
export const LADDER_FAIL_TEXT = `[단계별: cad 실패 412.3 s → refine_local 건너뜀(병합 면 실패 아님) → refine_global 실패(시간 초과) 600.0 s → remesh 실패 88.1 s → freeform 실패 120.4 s → tria 실패 9.8 s] CAD 메시 실패: gmsh 메시 생성에 실패했습니다(면 37: 1D 메시 실패) → 세분화·재메시·freeform 재메시·삼각형 폴백도 실패: OCC 삼각화가 면 37·41·58 을 만들지 못했습니다`;

// ---------------------------------------------------------------- 결정적 난수·행렬(BD-D-8 모양 — 목 구현)
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function radical(i: number, base: number) {
  let f = 1;
  let r = 0;
  while (i > 0) {
    f /= base;
    r += f * (i % base);
    i = Math.floor(i / base);
  }
  return r;
}
const PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37];
export function fnv(s: string) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}
const r2 = (v: number) => Math.round(v * 100) / 100;

export function makeMatrix(spec: DoeSpec, PARAMS: DoeParam[] = DEFAULT_PARAMS): DoeMatrixOut {
  const ps = [...spec.params].sort((a, b) => a.name.localeCompare(b.name));
  const k = ps.length;
  const seed = spec.seed ?? 1;
  const units: number[][] = [];
  if (spec.method === "fullfact") {
    const lv = spec.levels ?? 3;
    const total = lv ** k;
    for (let i = 0; i < total; i++) {
      let x = i;
      const row: number[] = [];
      for (let j = 0; j < k; j++) {
        row.push((x % lv) / (lv - 1));
        x = Math.floor(x / lv);
      }
      units.push(row);
    }
  } else if (spec.method === "halton") {
    const n = spec.n ?? 30;
    const off = Math.floor(mulberry32(seed)() * 50) + 1;
    for (let i = 0; i < n; i++) units.push(ps.map((_, j) => radical(i + off, PRIMES[j % PRIMES.length])));
  } else {
    const n = spec.n ?? 30;
    const rnd = mulberry32(seed);
    const perms = ps.map(() => {
      const a = Array.from({ length: n }, (_, i) => i);
      for (let i = n - 1; i > 0; i--) {
        const j = Math.floor(rnd() * (i + 1));
        [a[i], a[j]] = [a[j], a[i]];
      }
      return a;
    });
    for (let i = 0; i < n; i++) units.push(ps.map((_, j) => (perms[j][i] + rnd()) / n));
  }
  const nominal = Object.fromEntries(ps.map((x) => [x.name, PARAMS.find((q) => q.name === x.name)?.nominal ?? (x.lo + x.hi) / 2]));
  const seen = new Set<string>([JSON.stringify(ps.map((x) => r2(nominal[x.name])))]);
  const designs: DoeMatrixOut["designs"] = [{ id: "d000", values: Object.fromEntries(ps.map((x) => [x.name, r2(nominal[x.name])])) }];
  let dropped = 0;
  for (const u of units) {
    const vals = ps.map((x, j) => r2(x.lo + u[j] * (x.hi - x.lo)));
    const key = JSON.stringify(vals);
    if (seen.has(key)) {
      dropped += 1;
      continue;
    }
    seen.add(key);
    designs.push({ id: `d${String(designs.length).padStart(3, "0")}`, values: Object.fromEntries(ps.map((x, j) => [x.name, vals[j]])) });
  }
  const warnings: DoeWarning[] = spec.params
    .filter((x) => {
      const q = PARAMS.find((y) => y.name === x.name);
      return q && (x.lo < q.feasible[0] || x.hi > q.feasible[1]);
    })
    .map((x) => ({ code: "RANGE_OUTSIDE_FEASIBLE", name: x.name, message: `${x.name} 범위가 feasible(추정) 밖입니다 — 미리보기에서 실패 안이 늘 수 있습니다` }));
  const norm: DoeSpec = { method: spec.method, seed, params: ps, ...(spec.method === "fullfact" ? { levels: spec.levels ?? 3 } : { n: spec.n ?? 30 }) };
  const sha = (fnv(JSON.stringify(norm)) + fnv(JSON.stringify(designs))).padEnd(64, "0");
  return { spec: norm, matrix_sha256: sha, designs, n_designs: designs.length, dropped_duplicates: dropped, warnings };
}

/** spec 검증(§5) — null = 통과 */
export function specProblem(spec: DoeSpec | undefined, st: DoeSettingsOut, PARAMS: DoeParam[] = DEFAULT_PARAMS): MockResponse | null {
  if (!spec || !Array.isArray(spec.params) || !spec.params.length) return err(422, "DOE_NO_PARAMS", "포함 변수가 없습니다.");
  for (const x of spec.params) {
    const q = PARAMS.find((y) => y.name === x.name);
    if (!q) return err(422, "DOE_PARAM_UNKNOWN", `알 수 없는 변수: ${x.name}`, { name: x.name });
    if (!(x.lo < x.hi) || ((q.type === "D" || q.type === "W") && x.lo <= 0)) return err(422, "DOE_RANGE_INVALID", `${x.name}: 범위가 올바르지 않습니다(lo < hi, 깊이·폭 > 0).`, { name: x.name });
  }
  const count = spec.method === "fullfact" ? (spec.levels ?? 3) ** spec.params.length : spec.n ?? st.doe.default_n;
  if (count + 1 > st.max_designs) return err(422, "DOE_TOO_LARGE", `안 수 ${count} + 공칭 1 > 최대 ${st.max_designs}안`, { n: count, max: st.max_designs });
  return null;
}

// ---------------------------------------------------------------- 미리보기 셀·결과(결정적)
function cellStatus(id: string, values: Record<string, number>): { status: DoeDesignStatus; code: string | null; thumb: boolean } {
  const i = Number(id.slice(1));
  const d1 = values.CHR_BEAD_D_1;
  const w1 = values.CHR_BEAD_W_1;
  if ((d1 != null && d1 > 6.1) || i % 11 === 3) return { status: "SKIPPED_COLLISION", code: "GEOM_FEATURE_COLLISION", thumb: true };
  if ((w1 != null && w1 > 15.6) || i % 17 === 9) return { status: "SKIPPED_FIXED", code: "SHELL_FIXED_REGION_VIOLATION", thumb: true };
  if (i % 29 === 14) return { status: "SKIPPED_GEOM", code: "GEOM_TOPOLOGY_CHANGED", thumb: false };
  return { status: "READY", code: null, thumb: i % 23 !== 7 };
}

export function makeCells(m: DoeMatrixOut): DoePreviewCell[] {
  return m.designs.filter((d) => d.id !== "d000").map((d) => ({ id: d.id, values: d.values, ...cellStatus(d.id, d.values) }));
}

const COEF: Record<string, number> = { D: 0.95, W: 0.35, U: -0.08, V: 0.05 };
function scoreOf(values: Record<string, number>, PARAMS: DoeParam[]): number {
  let s = 1;
  for (const [name, v] of Object.entries(values)) {
    const q = PARAMS.find((x) => x.name === name);
    if (!q) continue;
    const span = q.feasible[1] - q.feasible[0] || 1;
    const x = (v - q.nominal) / span;
    s -= 0.22 * COEF[q.type] * x + (q.type === "D" ? 0.12 * x * x : 0);
  }
  const jitter = (parseInt(fnv(JSON.stringify(values)).slice(0, 4), 16) / 65535 - 0.5) * 0.012;
  return Math.max(0.55, +(s + jitter).toFixed(4));
}

function solve(A: number[][], b: number[]): number[] | null {
  const n = b.length;
  const M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let piv = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[piv][c])) piv = r;
    if (Math.abs(M[piv][c]) < 1e-12) return null;
    [M[c], M[piv]] = [M[piv], M[c]];
    for (let r = 0; r < n; r++) {
      if (r === c) continue;
      const f = M[r][c] / M[c][c];
      for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k];
    }
  }
  return M.map((r, i) => r[n] / r[i]);
}
const ranks = (xs: number[]) => {
  const idx = xs.map((v, i) => [v, i] as const).sort((a, b) => a[0] - b[0]);
  const out = new Array<number>(xs.length);
  for (let i = 0; i < idx.length; ) {
    let j = i;
    while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++;
    for (let k = i; k <= j; k++) out[idx[k][1]] = (i + j) / 2;
    i = j + 1;
  }
  return out;
};
const corr = (a: number[], b: number[]) => {
  const ma = a.reduce((s, v) => s + v, 0) / a.length;
  const mb = b.reduce((s, v) => s + v, 0) / b.length;
  let sab = 0;
  let saa = 0;
  let sbb = 0;
  for (let i = 0; i < a.length; i++) {
    sab += (a[i] - ma) * (b[i] - mb);
    saa += (a[i] - ma) ** 2;
    sbb += (b[i] - mb) ** 2;
  }
  return saa && sbb ? sab / Math.sqrt(saa * sbb) : 0;
};
const sd = (a: number[]) => {
  const m = a.reduce((s, v) => s + v, 0) / a.length;
  return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / Math.max(1, a.length - 1));
};

export function makeResult(spec: DoeSpec, cells: DoePreviewCell[], entryIds: string[], scenario: DoeScenario, PARAMS: DoeParam[] = DEFAULT_PARAMS): DoeResultOut {
  const C_ref = 4.82e5;
  const base = { id: "d000" as const, score: 1, umax: 3.92, epsmax: 0.0026 };
  const excluded: DoeExcluded[] = [];
  const okRows: { id: string; values: Record<string, number>; score: number; warn: DoeRankWarn[] }[] = [];
  for (const c of cells) {
    if (c.status !== "READY") {
      excluded.push({ id: c.id, status: c.status, code: c.code ?? null, values: c.values });
      continue;
    }
    const i = Number(c.id.slice(1));
    if (i % 19 === 12) {
      excluded.push({ id: c.id, status: "FAILED_MORPH", code: "GEOM_QUALITY", values: c.values });
      continue;
    }
    const warn = (c.warnings ?? []).map((w) => (w.code === "SELECT_FIXED_MOVED" ? "FIXED_MOVED" : "QUALITY_WARN") as DoeRankWarn);
    // v0.16.2 AD-D-8: 극단 요소(MORPH_EXTREME_ELEMENTS)도 순위 ⚠ — select 목 일부 안
    if (scenario === "select" && okRows.length % 7 === 1) warn.push("MORPH_EXTREME_ELEMENTS");
    okRows.push({ id: c.id, values: c.values, score: scoreOf(c.values, PARAMS), warn });
  }
  okRows.sort((a, b) => a.score - b.score || a.id.localeCompare(b.id));
  const noise_floor = scenario === "step" ? 0.012 : null;
  const ranking: DoeRankRow[] = okRows.map((r, k) => ({
    rank: k + 1,
    id: r.id,
    values: r.values,
    score: r.score,
    improvement: +(1 - r.score).toFixed(4),
    worst_entry_id: entryIds[parseInt(fnv(r.id).slice(0, 2), 16) % entryIds.length],
    umax: +(base.umax * r.score ** 0.9).toFixed(3),
    epsmax: +(base.epsmax * r.score ** 0.7).toFixed(5),
    umax_all: +(base.umax * r.score ** 0.9 * 1.04).toFixed(3),
    epsmax_all: +(base.epsmax * r.score ** 0.7 * 1.06).toFixed(5),
    noise: noise_floor != null ? Math.abs(1 - r.score) < noise_floor : false,
    warnings_n: Number(r.id.slice(1)) % 7 === 2 ? 1 : 0,
    ...(r.warn.length ? { warn: r.warn } : {}),
    ...perEslMock(r.id, r.score, entryIds, noise_floor),
  }));
  // Pareto(§11.4): 다른 안·베이스라인(전부 1)에 모든 ESL 에서 지배당하지 않음
  const vec = (r: DoeRankRow) => (r.per_esl ?? []).map((p) => p.ratio);
  for (const r of ranking) {
    const a = vec(r);
    const others = [...ranking.filter((o) => o !== r).map(vec), a.map(() => 1)];
    r.pareto = !others.some((o) => o.length === a.length && o.every((v, i) => v <= a[i]) && o.some((v, i) => v < a[i]));
  }
  // 민감도: OK 안(베이스라인 포함) — 변수 [lo,hi] → [0,1]
  const names = spec.params.map((x) => x.name);
  const all = [{ values: Object.fromEntries(names.map((n) => [n, PARAMS.find((q) => q.name === n)?.nominal ?? 0])), score: 1 }, ...okRows];
  let sensitivity: DoeResultOut["sensitivity"] = null;
  const warnings: DoeWarning[] = [];
  if (all.length >= names.length + 2) {
    const X = all.map((r) => names.map((n, j) => (r.values[n] - spec.params[j].lo) / (spec.params[j].hi - spec.params[j].lo || 1)));
    const y = all.map((r) => r.score);
    const A = X.map((r) => [1, ...r]);
    const AtA = A[0].map((_, i) => A[0].map((__, j) => A.reduce((s, r) => s + r[i] * r[j], 0)));
    const Aty = A[0].map((_, i) => A.reduce((s, r, k) => s + r[i] * y[k], 0));
    const beta = solve(AtA, Aty) ?? new Array(names.length + 1).fill(0);
    const yhat = A.map((r) => r.reduce((s, v, i) => s + v * beta[i], 0));
    const my = y.reduce((s, v) => s + v, 0) / y.length;
    const ssr = y.reduce((s, v, i) => s + (v - yhat[i]) ** 2, 0);
    const sst = y.reduce((s, v) => s + (v - my) ** 2, 0);
    const sy = sd(y);
    const ry = ranks(y);
    sensitivity = {
      method: "src+spearman",
      r2: sst ? +(1 - ssr / sst).toFixed(3) : 0,
      params: names.map((n, j) => {
        const xj = X.map((r) => r[j]);
        return { name: n, src: sy ? +((beta[j + 1] * sd(xj)) / sy).toFixed(3) : 0, spearman: +corr(ranks(xj), ry).toFixed(3) };
      }),
    };
  } else warnings.push({ code: "SENSITIVITY_TOO_FEW", message: `OK 안이 ${all.length}개로 변수 수 + 2 보다 적어 민감도를 계산하지 않았습니다` });
  if (!ranking.length) warnings.push({ code: "NO_FEASIBLE_DESIGNS", message: "실행 가능한 안이 없습니다(모두 스킵·실패)" });
  const count = (pre: string) => Object.fromEntries(Object.entries(excluded.filter((e) => e.status.startsWith(pre)).reduce<Record<string, number>>((m, e) => ((m[e.status] = (m[e.status] ?? 0) + 1), m), {})));
  const best = ranking[0]?.id ?? null;
  const bestFiles: DoeFileOut[] = best
    ? scenario === "step"
      ? [
          { rel: `best/${best}/ch_r.rad`, size: 18_220_331, downloadable: true },
          { rel: `best/${best}/ch_r.fem`, size: 16_118_002, downloadable: true },
          { rel: `best/${best}/sample.brep`, size: 2_331_204, downloadable: true },
          { rel: `best/${best}/sample.step`, size: 3_118_440, downloadable: true },
          { rel: `best/${best}/values.json`, size: 512, downloadable: true },
        ]
      : [
          { rel: `best/${best}/out_files/inc_mesh.inc`, size: 140_220_111, downloadable: true },
          { rel: `best/${best}/sample.brep`, size: 2_331_204, downloadable: true },
          { rel: `best/${best}/sample.step`, size: 3_118_440, downloadable: true },
          { rel: `best/${best}/values.json`, size: 512, downloadable: true },
        ]
    : [];
  return {
    C_ref,
    baseline: base,
    n_ok: ranking.length,
    n_skipped: count("SKIPPED_"),
    n_failed: count("FAILED_"),
    ranking,
    excluded,
    sensitivity,
    boundary_warnings_n: boundaryCount(scenario, entryIds).n_warn,
    view3d: ["d000", ...ranking.slice(0, 3).map((r) => r.id)],
    best: best ? { id: best, files: bestFiles } : null,
    noise_floor,
    ratio_tol: Math.max(1e-6, noise_floor ?? 0),
    per_esl_inline: true,
    esl: entryIds.map((e) => ({ entry_id: e, label: e.slice(0, 8) })),
    sort: "score",
    ...(scenario === "select" ? { summary: { best_clean: ranking.find((r) => !r.warn?.length)?.id ?? null } } : {}),
    warnings,
  };
}

/** 안·ESL 별 비율 r = C_안 / C_베이스라인(결정적 — 안 id·ESL 해시로 score 주변에 흩뿌림, 일부 씬은 악화) */
export function perEslMock(id: string, score: number, entryIds: string[], noise: number | null) {
  const tol = Math.max(1e-6, noise ?? 0);
  const per = entryIds.map((e, i) => {
    const h = parseInt(fnv(`${id}:${e}`).slice(0, 4), 16) / 0xffff;
    const ratio = +(score * (0.8 + 0.45 * h) + (i === 0 ? 0 : 0.02)).toFixed(4);
    const C = +(4.82e5 * (0.7 + 0.1 * i) * ratio).toFixed(1);
    return { entry_id: e, label: e.slice(0, 8), C, ratio, umax: +(3.9 * ratio ** 0.9).toFixed(3), epsmax: +(0.0026 * ratio ** 0.7).toFixed(5) };
  });
  const r = per.map((p) => p.ratio);
  const worst = Math.max(...r);
  const gm = Math.exp(r.reduce((s, v) => s + Math.log(v), 0) / r.length);
  return {
    worst_ratio: worst,
    min_improvement: +(1 - worst).toFixed(4),
    all_improved: worst < 1 - tol,
    n_improved: r.filter((v) => v < 1 - tol).length,
    n_worsened: r.filter((v) => v > 1 + tol).length,
    n_unchanged: r.filter((v) => Math.abs(1 - v) <= tol).length,
    geo_mean_improvement: +(1 - gm).toFixed(4),
    pareto: false,
    per_esl: per,
  };
}

// ---------------------------------------------------------------- 평면도
const ring = (cx: number, cy: number, rx: number, ry: number, n = 24): XY[] => Array.from({ length: n }, (_, i) => [+(cx + rx * Math.cos((2 * Math.PI * i) / n)).toFixed(1), +(cy + ry * Math.sin((2 * Math.PI * i) / n)).toFixed(1)] as XY);
const HOLES: XY[] = [
  [140, 120],
  [1520, 120],
  [140, 827],
  [1520, 827],
  [830, 110],
  [830, 840],
];
export function makePlan(scenario: DoeScenario, entryIds: string[]): DoePlanOut {
  const points: [number, number, number][] = [];
  const step = L / 60;
  for (let a = step / 2; a < L; a += step) for (let b = step / 2; b < H; b += step) points.push([+a.toFixed(1), +b.toFixed(1), 1]);
  const beads = BEADS.map((b) => {
    const [cx, cy] = b.center_ab;
    const w = b.shape === "circular" ? b.nominal.width / 2 : (b.nominal.length ?? 300) / 2;
    const h = b.shape === "circular" ? b.nominal.width / 2 : Math.max(10, b.nominal.width * 1.6);
    return { id: b.id, ring: ring(cx, cy, w, h) };
  });
  const fixed = HOLES.slice(0, scenario === "step" ? 0 : 6).map(([a, b], i) => ({ label: `B-RBE2-${i + 1}`, kind: "RBE2", a: a + 2, b: b - 1 }));
  if (scenario === "same") return { frame: { a_range: [0, L], b_range: [0, H] }, outline: [[0, 0], [L, 0], [L, H], [0, H]], holes: HOLES.map(([a, b]) => ring(a, b, 9, 9, 16)), elems: { n_total: points.length, decimated: false, points }, beads, fixed, a_points: [], load_points: [], links: [] };
  const a_points = [
    { label: "A-RBE2-1", a: 152, b: 128 },
    { label: "A-RBE2-2", a: 1508, b: 131 },
    { label: "A-RBE2-3", a: 156, b: 812 },
    { label: "A-RBE2-4", a: 1494, b: 846 },
    { label: "A-TIE-1", a: 830, b: 132 },
    { label: "S321-1", a: 30, b: 30 },
  ];
  const cand = [...fixed.map((f) => ({ label: f.label, a: f.a, b: f.b })), ...HOLES.map(([a, b], i) => ({ label: `B-H${i + 1}`, a, b }))];
  const near = (a: number, b: number) => cand.reduce((best, c) => (Math.hypot(c.a - a, c.b - b) < Math.hypot(best.a - a, best.b - b) ? c : best), cand[0]);
  const links: DoePlanLink[] = a_points.map((x) => {
    const c = near(x.a, x.b);
    const d = +Math.hypot(c.a - x.a, c.b - x.b).toFixed(1);
    return { from: x.label, to: c.label, d_mm: d, warn: d > 10, from_ab: [x.a, x.b] as XY, to_ab: [c.a, c.b] as XY, kind: x.label.startsWith("S321") ? "support" : "fastener" };
  });
  const load_points = entryIds.slice(0, 3).map((e, i) => ({ entry_id: e, share: [0.42, 0.31, 0.24][i], a: [1380, 300, 980][i], b: [520, 700, 470][i] }));
  for (const lp of load_points) {
    const c = near(lp.a, lp.b);
    const d = +Math.hypot(c.a - lp.a, c.b - lp.b).toFixed(1);
    links.push({ from: `하중 ${lp.entry_id}`, to: c.label, d_mm: d, warn: d > 20, from_ab: [lp.a, lp.b], to_ab: [c.a, c.b], kind: "load" });
  }
  return { frame: { a_range: [0, L], b_range: [0, H] }, outline: [[0, 0], [L, 0], [L, H], [0, H]], holes: HOLES.map(([a, b]) => ring(a, b, 9, 9, 16)), elems: { n_total: points.length, decimated: false, points }, beads, fixed, a_points, load_points, links };
}

/** v0.17.3 VU-D-7: ② B 메시 기준 select plan-view = 경계 매핑(A 체결·하중 집중·링크)을 select 평면 크기로 옮겨 붙임(백엔드 doe_select.plan_view 와 같음) */
export function withBoundary(rec: { out: { inputs: { select_base?: string | null }; entry_ids: string[] } }, p: DoePlanOut): DoePlanOut {
  if (rec.out.inputs.select_base !== "mesh") return p;
  const b = makePlan("mesh", rec.out.entry_ids);
  const [a0, a1] = p.frame.a_range;
  const [b0, b1] = p.frame.b_range;
  const k: XY = [(a1 - a0) / L, (b1 - b0) / H];
  const at = (x: XY): XY => [+(a0 + x[0] * k[0]).toFixed(1), +(b0 + x[1] * k[1]).toFixed(1)];
  const ab = (a: number, bb: number) => {
    const [x, y] = at([a, bb]);
    return { a: x, b: y };
  };
  return {
    ...p,
    a_points: b.a_points.map((x) => ({ ...x, ...ab(x.a, x.b) })),
    load_points: b.load_points.map((x) => ({ ...x, ...ab(x.a, x.b) })),
    links: b.links.map((l) => ({ ...l, from_ab: l.from_ab ? at(l.from_ab) : undefined, to_ab: l.to_ab ? at(l.to_ab) : undefined })),
  };
}

export function boundaryCount(scenario: DoeScenario, entryIds: string[]) {
  const links = makePlan(scenario, entryIds).links;
  return { n_warn: links.filter((l) => l.warn && l.kind !== "support").length, n_info: links.filter((l) => l.warn && l.kind === "support").length };
}

// ---------------------------------------------------------------- 그림(목: SVG — 실제는 PNG)
export function thumbSvg(values: Record<string, number> | null, status: DoeDesignStatus | "NOMINAL") {
  const W = 320;
  const Hh = 240;
  const sx = (a: number) => 14 + (a / L) * (W - 28);
  const sy = (b: number) => 14 + (1 - b / H) * (Hh - 28);
  const shapes = BEADS.map((b) => {
    const kD = PARAMS.find((q) => q.bead === b.id && q.type === "D");
    const kW = PARAMS.find((q) => q.bead === b.id && q.type === "W");
    const d = values && kD ? values[kD.name] ?? kD.nominal : b.nominal.depth;
    const w = values && kW ? values[kW.name] ?? kW.nominal : b.nominal.width;
    const dev = Math.max(-1, Math.min(1, (d - b.nominal.depth) / 2));
    const col = dev >= 0 ? `rgb(${Math.round(220 - 140 * dev)},${Math.round(90 + 40 * dev)},${Math.round(60 + 20 * dev)})` : `rgb(70,${Math.round(130 - 60 * dev)},${Math.round(200)})`;
    const [cx, cy] = b.center_ab;
    if (b.shape === "circular") return `<circle cx="${sx(cx)}" cy="${sy(cy)}" r="${(w / 2 / L) * (W - 28) + 3}" fill="${col}"/>`;
    const len = ((b.nominal.length ?? 300) / L) * (W - 28);
    return `<rect x="${sx(cx) - len / 2}" y="${sy(cy) - w / 3}" width="${len}" height="${(w * 2) / 3}" rx="3" fill="${col}"/>`;
  }).join("");
  const grey = status !== "NOMINAL" && status !== "READY" ? ' opacity="0.45"' : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${Hh}" width="${W}" height="${Hh}"><rect width="${W}" height="${Hh}" fill="#f4f5f7"/><g${grey}><rect x="14" y="14" width="${W - 28}" height="${Hh - 28}" fill="#dfe3e8" stroke="#3d4450"/>${HOLES.map(([a, b]) => `<circle cx="${sx(a)}" cy="${sy(b)}" r="3" fill="#fff" stroke="#3d4450"/>`).join("")}${shapes}</g></svg>`;
}

// ---------------------------------------------------------------- v0.14.0 ④ 형상 직접 비교(esl_step_compare.md)
type CompareInputShape = NonNullable<DoeStudyOut["inputs"]["shapes"]>[number];
// eslint-disable-next-line no-control-regex
const CTRL_RE = /[\u0000-\u001f\u007f]/;
/** 목 sha256 = 파일 이름 해시(같은 파일 이름 = 같은 내용으로 봄 → SHAPE_DUPLICATE_FILE 경고) */
const shaOfFile = (file: string) => fnv(`step:${file}`).padEnd(64, "e");
const COMPARE_FAIL_MSG: Record<string, string> = {
  SHAPE_MISALIGNED: "기준 frame 과 원점·법선이 다릅니다(같은 좌표계 STEP 인지 확인)",
  SHAPE_SIZE_MISMATCH: "기준과 크기가 ±5 % 밖입니다",
  MESH_FAILED: "gmsh 메시 생성에 실패했습니다",
  REMESH_FAILED: "삼각형 재메시에 실패했습니다: 면 분류 실패. 특징각(remesh.feature_angle_deg)을 키우거나 메시 파일로 올리세요",
};
/** C2-D-1 COMPARE_MESH_METHOD_MIXED 조건: 방식이 둘 이상이고 refine·remesh·fallback·mesh_input(메시 입력) 중 하나가 섞임 */
export const MIXED_TRIGGER = ["refine", "remesh", "fallback", "mesh_input", "defeature"];
export const meshMethodsMixed = (kinds: Set<string>) => kinds.size > 1 && [...kinds].some((k) => MIXED_TRIGGER.includes(k));
export const COMPARE_REF_CASE_MESH: DoeWarning = { code: "COMPARE_REF_CASE_MESH", message: "기준이 낙하 메시(다른 메싱 방식)라 개선율에 메시 차이가 섞입니다" };

const MAX_FAIL_RATIO = 0.01;
/** 형상 메시 품질 요약(결정적, SC-D-13): 'rough' 가 이름·파일에 있으면 Fail 비율 상한 초과(경고 SHAPE_QUALITY_FAIL, 차단 아님) */
function mockQuality(key: string, h: number, nElems: number): DoeShapeQuality {
  const fail_ratio = key.includes("rough") ? 0.0184 : +(0.0006 + 0.002 * h).toFixed(4);
  const warn_ratio = +(fail_ratio * 3.2 + 0.004).toFixed(4);
  return {
    fail_elems: Math.round(nElems * fail_ratio),
    fail_ratio,
    warn_elems: Math.round(nElems * warn_ratio),
    warn_ratio,
    tria_pct: +(2 + 4 * h).toFixed(1),
    over_limit: fail_ratio > MAX_FAIL_RATIO,
    max_fail_ratio: MAX_FAIL_RATIO,
  };
}

/** v0.16.0 목 메시 방식(결정적, C2-D-9·18): mode 없음(v0.15 스터디) = cad. 메시 형상 = mesh_input.
 *  auto 에서 이름·파일에 'complex' → 국부 세분화, 'hard' → 전역 세분화(세분화 끔이면 재메시 폴백), 'broken' → 재메시 폴백('coarse' 면 충실도 경고).
 *  cad 에서 'broken' 은 MESH_FAILED(v0.15 와 같음). remesh = 모든 STEP 재메시. auto 에서 'dead' → 사다리 전부 실패(REMESH_FAILED + cad_error) */
const MOCK_CAD_ERROR = { code: "MESH_FAILED", message: "gmsh 메시 생성에 실패했습니다(면 37: 1D 메시 실패)" };
/** v0.16.1 목 억제 목록(SR-D-20 순서 = kind → 중심 사전순): 구멍 1 · 딤플 1 · 필렛 3 + 큰 목록 'many' 은 60행(50 + 외 10) */
export function mockDefeatureList(did: string): DoeDefeatureList {
  const f = (i: number, kind: DoeDefeatureFeature["kind"], center: [number, number, number], size: DoeDefeatureFeature["size"], dev: number): DoeDefeatureFeature => ({
    id: `f${i}`, kind, center, bbox: null, size, area_mm2: null, faces_n: kind === "fillet" ? 1 : 2, action: "suppressed", method: kind === "hole" ? "holes_v0141" : kind === "fillet" ? "compound" : "plane", dev_mm: dev,
  });
  const features: DoeDefeatureFeature[] = [
    f(1, "bead", [120, 130, 1.5], { h_mm: 1.5 }, 1.48),
    f(2, "fillet", [80, 100, 0.8], { r_mm: 1.5 }, 0.02),
    f(3, "fillet", [160, 100, 2.4], { r_mm: 1.5 }, 0.02),
    f(4, "fillet", [200, 100, 4.1], { r_mm: 1.5 }, 0.03),
    f(5, "hole", [60, 40, 0], { d_mm: 5 }, 2.5),
  ];
  void did;
  return { features, n: features.length, truncated: false, counts: { hole: 1, bead: 1, fillet: 3 } };
}

function mockFidelity(key: string) {
  const hd = key.includes("coarse") ? 0.42 : 0.12;
  return { hausdorff_mm: hd, max_dev_mm: +(hd * 0.9).toFixed(3), p95_mm: +(hd * 0.35).toFixed(3), area_ratio: key.includes("coarse") ? 0.996 : 1.001, deflection_mm: 0.05, warn_mm: 0.3, fail_mm: 1.5, over_warn: hd > 0.3 };
}
function mockMethod(x: CompareInputShape, key: string, mode: DoeMeshMode, refine: boolean, nRef: number): Partial<DoePrepShape> & { fail?: [string, string] } {
  if (x.source === "mesh")
    return { mesh_method: "mesh_input", edge_median_mm: key.includes("fine") ? 1.6 : 3.05, n_components: key.includes("split") ? 2 : 1, ...(key.includes("clean") ? {} : { diag: { holes_n: 14, holes_small_n: 6, islands_n: 3, free_loops_n: 14 } }) };
  const cadFail = { stage: "cad", h_mm: 3, status: "FAILED_MESH", code: "MESH_FAILED", seconds: 41 };
  if (mode === "remesh") return { mesh_method: "remesh", fidelity: mockFidelity(key) };
  if (mode === "cad") return key.includes("broken") ? { fail: ["FAILED_MESH", "MESH_FAILED"] } : { mesh_method: "cad" };
  if (key.includes("dead"))
    return {
      fail: ["FAILED_MESH", "REMESH_FAILED"],
      cad_error: MOCK_CAD_ERROR,
      attempts: [
        cadFail,
        ...(refine ? [{ stage: "refine_local", factor: 0.75, h_mm: 2.25, status: "FAILED_MESH", code: "MESH_FAILED", seconds: 50 }, { stage: "refine_global", factor: 0.8, h_mm: 2.4, status: "SKIPPED", skipped: true, reason: "time", code: "REFINE_SKIPPED_LIMIT" }] : []),
        { stage: "remesh", h_mm: 3, status: "FAILED_MESH", code: "REMESH_FAILED", seconds: 12 },
      ],
    };
  // v0.16.1 'dimple' → cad·세분화 실패 후 형상 단순화(defeature) 성공(SR-D-16)
  if (key.includes("dimple"))
    return {
      mesh_method: "defeature",
      cad_error: MOCK_CAD_ERROR,
      defeature: { n: 5, counts: { hole: 1, bead: 1, fillet: 3 }, skipped_n: 0, suppressed_max_mm: 2.5, outside_hausdorff_mm: 0.12 },
      attempts: [
        cadFail,
        ...(refine ? [{ stage: "refine_local", factor: 0.75, h_mm: 2.25, status: "FAILED_MESH", code: "MESH_FAILED", seconds: 48 }, { stage: "refine_global", factor: 0.8, h_mm: 2.4, status: "FAILED_MESH", code: "MESH_FAILED", seconds: 71 }] : []),
        { stage: "defeature", h_mm: 3, status: "OK", seconds: 36, n_elems: Math.round(nRef * 0.99) },
      ],
    };
  if (refine && key.includes("complex")) {
    const n = Math.round(nRef * 1.4);
    return {
      mesh_method: "refine",
      cad_error: MOCK_CAD_ERROR,
      refine: {
        kind: "local", stage_index: 1, h_mm: 1.5, factor: 0.5, base_h_mm: 3,
        faces: [0, 1, 2].map((k) => ({ bbox_key: `f${k}`, type: "BSplineSurface", center: [400 + 30 * k, 210, 4], ring: k ? 1 : 0 })),
        n_elems: n, n_est: Math.round(n * 0.96), elem_ratio_h: 1.38, elem_ratio_ref: 1.4,
        attempts: [cadFail, { stage: "refine_local", factor: 0.75, h_mm: 2.25, status: "FAILED_MESH", code: "MESH_FAILED", seconds: 52 }, { stage: "refine_local", factor: 0.5, h_mm: 1.5, status: "OK", seconds: 63, n_elems: n }],
      },
    };
  }
  if (refine && key.includes("hard")) {
    const n = Math.round(nRef * 1.6);
    return {
      mesh_method: "refine",
      cad_error: MOCK_CAD_ERROR,
      refine: {
        kind: "global", stage_index: 2, h_mm: 2.4, factor: 0.8, base_h_mm: 3, faces: [], n_elems: n, n_est: Math.round(n * 1.02), elem_ratio_h: 1.55, elem_ratio_ref: 1.6,
        attempts: [
          cadFail,
          { stage: "refine_local", status: "SKIPPED", skipped: true, reason: null, code: "REFINE_LOCAL_NO_FACE" },
          { stage: "refine_global", factor: 0.8, h_mm: 2.4, status: "OK", seconds: 88, n_elems: n },
        ],
      },
    };
  }
  if (key.includes("broken") || (!refine && (key.includes("complex") || key.includes("hard")))) return { mesh_method: "fallback", cad_error: MOCK_CAD_ERROR, fidelity: mockFidelity(key) };
  return { mesh_method: "cad" };
}

/** 준비 결과(형상별 메시·크기·정렬·품질, 결정적): 이름·파일에 'shift' → SHAPE_MISALIGNED, 'big' → SHAPE_SIZE_MISMATCH, 'broken' → MESH_FAILED(cad),
 *  'rough' → 품질 Fail 비율 상한 초과. v0.16.0 mode·refine = 메시 방식(mockMethod) */
export function makeComparePrep(shapes: CompareInputShape[], refSource: "step" | "case", mode: DoeMeshMode | null = null, refine = true): NonNullable<DoeStudyOut["prep"]> {
  const rows: DoePrepShape[] = [];
  const m: DoeMeshMode = mode ?? "cad";
  if (refSource === "case")
    rows.push({ id: "d000", name: "Case 메시", file_name: null, reference: true, source: "case", status: "READY", code: null, message: null, n_nodes: 221_380, n_elems: 218_400, quad_ratio: 0.98, quality: mockQuality("case", 0.2, 218_400), mesh_method: "mesh_input", edge_median_mm: 3.0, n_components: 1 });
  for (const x of shapes) {
    const key = `${x.name} ${x.file_name}`.toLowerCase();
    const h = parseInt(fnv(x.file_name ?? x.id).slice(0, 4), 16) / 0xffff;
    const mm0 = mockMethod(x, key, m, refine, 180_000);
    const fail = x.reference ? null : key.includes("shift") ? ["FAILED_SIZE", "SHAPE_MISALIGNED"] : key.includes("big") ? ["FAILED_SIZE", "SHAPE_SIZE_MISMATCH"] : mm0.fail ?? null;
    const { fail: _f, ...meth } = mm0;
    void _f;
    const meshed = fail?.[0] !== "FAILED_MESH";
    const nElems = meth.refine?.n_elems ?? Math.round(168_000 + 26_000 * h);
    rows.push({
      id: x.id,
      name: x.name,
      file_name: x.file_name,
      reference: x.reference,
      source: "step",
      status: (fail?.[0] ?? "READY") as DoeDesignStatus,
      code: fail?.[1] ?? null,
      message: fail ? COMPARE_FAIL_MSG[fail[1]] : null,
      n_nodes: meshed ? Math.round(nElems * 1.02) : null,
      n_elems: meshed ? nElems : null,
      quad_ratio: meshed ? +(0.93 + 0.05 * h).toFixed(3) : null,
      quality: meshed ? mockQuality(key, h, nElems) : null,
      ...(mode != null || x.source === "mesh" ? (meshed ? meth : { mesh_method: null, ...(meth.cad_error ? { cad_error: meth.cad_error, attempts: meth.attempts } : {}) }) : {}),
      ...(x.source === "mesh" ? { source: "mesh" as const } : {}),
    });
  }
  const failed = rows.filter((r) => r.status !== "READY").map((r) => ({ id: r.id, status: r.status, code: r.code ?? null }));
  const warnings: DoeWarning[] = refSource === "case" ? [COMPARE_REF_CASE_MESH] : [];
  // v0.16.0 경고(C2-D-1·10·13·23)
  if (mode != null || shapes.some((x) => x.source === "mesh")) {
    // C2-D-1: {cad, Case 메시} 만이면 COMPARE_REF_CASE_MESH 가 이미 알림 — refine·remesh·fallback·메시 입력이 섞일 때만
    const kinds = new Set(rows.filter((r) => r.status === "READY" && r.mesh_method).map((r) => (r.source === "case" ? "case" : (r.mesh_method as DoeMeshMethod))));
    if (meshMethodsMixed(kinds)) warnings.push({ code: "COMPARE_MESH_METHOD_MIXED", message: "형상마다 메시 방식이 달라 개선율에 메시 차이가 섞입니다" });
    for (const r of rows) {
      if (r.mesh_method === "defeature" && r.defeature)
        warnings.push({ code: "MESH_DEFEATURED", name: r.name, message: `${r.name}: CAD 메시 실패 → 작은 형상 ${r.defeature.n}개 억제(구멍 1 · 딤플 1 · 필렛 3), 억제 영역 최대 ${r.defeature.suppressed_max_mm} mm · 그 밖 최대 ${r.defeature.outside_hausdorff_mm} mm` });
      if (r.mesh_method === "fallback") warnings.push({ code: "REMESH_USED", name: r.name, message: `${r.name}: CAD 메시 실패 → 삼각형 재메시: ${r.cad_error?.message ?? ""}` });
      if (r.fidelity?.over_warn) warnings.push({ code: "REMESH_FIDELITY_WARN", name: r.name, message: `${r.name}: 재메시가 원 형상과 최대 ${r.fidelity.hausdorff_mm} mm 다릅니다(> ${r.fidelity.warn_mm} mm)` });
      if (r.mesh_method === "refine" && r.refine)
        warnings.push({
          code: "MESH_REFINED",
          name: r.name,
          message: `${r.name}: 기본 3 mm 메시에 실패해 ${r.refine.kind === "local" ? "국부" : "전역"} 세분화(h ${r.refine.h_mm} mm${r.refine.faces?.length ? `, 면 ${r.refine.faces.length}개` : ""})로 메시했습니다. 요소 수 기준 대비 ×${r.refine.elem_ratio_ref}. 요소 크기가 기준 메시와 달라 컴플라이언스에 메시 의존 오차가 섞입니다(작은 개선율은 해석 차이일 수 있음)`,
        });
      if (r.source === "mesh" && r.edge_median_mm != null && (r.edge_median_mm < 3 / 1.5 || r.edge_median_mm > 3 * 1.5))
        warnings.push({ code: "MESH_INPUT_SIZE_DIFF", name: r.name, message: `${r.name}: 메시 요소 크기 중앙값 ${r.edge_median_mm} mm 가 기준 3 mm 와 많이 다릅니다` });
      if (r.source === "mesh" && (r.n_components ?? 1) > 1) warnings.push({ code: "MESH_INPUT_DISCONNECTED", name: r.name, message: `${r.name}: 메시가 ${r.n_components}조각입니다` });
    }
  }
  const files = shapes.map((x) => x.sha256);
  if (new Set(files).size < files.length) warnings.push({ code: "SHAPE_DUPLICATE_FILE", message: "같은 STEP 파일이 두 번 이상 들어 있습니다" });
  for (const r of rows)
    if (r.quality?.over_limit)
      warnings.push({ code: "SHAPE_QUALITY_FAIL", message: `${r.id} ${r.name}: 메시 품질 Fail 요소 비율 ${(r.quality.fail_ratio * 100).toFixed(2)} % > ${r.quality.max_fail_ratio * 100} % — 차단 아님` });
  return {
    n_beads: 0,
    n_params: 0,
    paicad_version: null,
    warnings,
    boundary: null,
    n_shapes: rows.length,
    n_ready: rows.length - failed.length,
    failed,
    reference_source: refSource,
    shapes: rows,
    mesh: { size_mm: 3, gmsh_version: "4.13.1" },
  };
}

/** 비교 결과(결정적): READY 형상마다 score(형상 해시), 실패 형상은 excluded, 민감도 없음(COMPARE_NO_PARAMS) */
export function makeCompareResult(prep: NonNullable<DoeStudyOut["prep"]>, entryIds: string[]): DoeResultOut {
  const rows = prep.shapes ?? [];
  const ref = rows.find((r) => r.reference) ?? rows[0];
  /** v0.16.0 결과 shape 메시 칸(C2-D-10): 있으면 복사, 세분화 형상은 수렴 점검 δ(C2-D-24 — 기준 d000 을 h_r 로 다시 풀어) */
  const meshOf = (r: DoePrepShape | undefined): Partial<DoeShapeRef> => {
    if (!r?.mesh_method) return {};
    const out: Partial<DoeShapeRef> = { mesh_method: r.mesh_method, ...(r.fidelity ? { fidelity: r.fidelity } : {}), ...(r.refine ? { refine: r.refine } : {}), ...(r.defeature ? { defeature: r.defeature } : {}) };
    if (r.refine && prep.reference_source !== "case") {
      const d = r.refine.kind === "local" ? 0.012 : 0.006;
      out.refine_bias = { h_mm: r.refine.h_mm, delta_max: d, tol: 0.01, over_tol: d > 0.01, per_esl: entryIds.map((e, k) => ({ entry_id: e, delta: +(d * (1 - 0.3 * k)).toFixed(4) })) };
    }
    return out;
  };
  const refShape: DoeShapeRef =
    prep.reference_source === "case"
      ? { name: "Case 메시", file_name: null, source: "case", ...meshOf(ref) }
      : { name: ref?.name ?? "기준", file_name: ref?.file_name ?? null, source: ref?.source === "mesh" ? "mesh" : "step", ...meshOf(ref) };
  const base = { id: "d000" as const, score: 1, umax: 3.92, epsmax: 0.0026, shape: refShape };
  const ok = rows
    .filter((r) => !r.reference && r.status === "READY")
    .map((r) => ({ r, score: +(0.74 + 0.32 * (parseInt(fnv(`${r.name}|${r.file_name}`).slice(0, 4), 16) / 0xffff)).toFixed(4) }))
    .sort((a, b) => a.score - b.score || a.r.id.localeCompare(b.r.id));
  const ranking: DoeRankRow[] = ok.map(({ r, score }, k) => ({
    rank: k + 1,
    id: r.id,
    values: {},
    shape: { name: r.name, file_name: r.file_name, reference: false, ...(r.source === "mesh" ? { source: "mesh" as const } : {}), ...meshOf(r) },
    score,
    improvement: +(1 - score).toFixed(4),
    worst_entry_id: entryIds[parseInt(fnv(r.id).slice(0, 2), 16) % entryIds.length],
    umax: +(base.umax * score ** 0.9).toFixed(3),
    epsmax: +(base.epsmax * score ** 0.7).toFixed(5),
    umax_all: +(base.umax * score ** 0.9 * 1.04).toFixed(3),
    epsmax_all: +(base.epsmax * score ** 0.7 * 1.06).toFixed(5),
    noise: false,
    warnings_n: 0,
    ...perEslMock(r.id, score, entryIds, null),
  }));
  const vec = (r: DoeRankRow) => (r.per_esl ?? []).map((p) => p.ratio);
  for (const r of ranking) {
    const a = vec(r);
    const others = [...ranking.filter((o) => o !== r).map(vec), a.map(() => 1)];
    r.pareto = !others.some((o) => o.length === a.length && o.every((v, i) => v <= a[i]) && o.some((v, i) => v < a[i]));
  }
  const excluded: DoeExcluded[] = rows.filter((r) => r.status !== "READY").map((r) => ({ id: r.id, status: r.status, code: r.code ?? null, shape: { name: r.name, file_name: r.file_name } }));
  const n_failed = excluded.reduce<Record<string, number>>((m, e) => ((m[e.status] = (m[e.status] ?? 0) + 1), m), {});
  const best = ranking[0]?.id ?? null;
  const warnings: DoeWarning[] = prep.reference_source === "case" ? [COMPARE_REF_CASE_MESH] : [];
  for (const w of prep.warnings) if (["COMPARE_MESH_METHOD_MIXED", "REMESH_USED", "REMESH_FIDELITY_WARN", "MESH_REFINED", "MESH_DEFEATURED"].includes(w.code)) warnings.push(w);
  for (const r of ranking)
    if (r.shape?.refine_bias?.over_tol)
      warnings.push({ code: "MESH_REFINE_BIAS", name: r.shape.name, message: `${r.shape.name}: 기준을 ${r.shape.refine_bias.h_mm} mm 로 다시 풀면 컴플라이언스가 최대 ${(r.shape.refine_bias.delta_max * 100).toFixed(1)} % 달라집니다(메시 편향)` });
  if (!ranking.length) warnings.push({ code: "NO_FEASIBLE_DESIGNS", message: "비교할 수 있는 형상이 없습니다(모두 실패)" });
  return {
    C_ref: 4.82e5,
    baseline: base,
    n_ok: ranking.length,
    n_skipped: {},
    n_failed,
    ranking,
    excluded,
    sensitivity: null,
    sensitivity_reason: "COMPARE_NO_PARAMS",
    scenario: "compare",
    reference_source: prep.reference_source ?? "step",
    boundary_warnings_n: 0,
    view3d: ["d000", ...ranking.slice(0, 3).map((r) => r.id)],
    best: best ? { id: best, files: [{ rel: `best/${best}/ch_r.rad`, size: 18_220_331, downloadable: true }, { rel: `best/${best}/ch_r.fem`, size: 16_118_002, downloadable: true }] } : null,
    noise_floor: null,
    ratio_tol: 1e-6,
    per_esl_inline: true,
    esl: entryIds.map((e) => ({ entry_id: e, label: e.slice(0, 8) })),
    sort: "score",
    warnings,
  };
}

/** 요청 형상 → 형상 id(SC-D-4): 기준 STEP = d000, 나머지 요청 순서 d001…(기준 없음이면 d001 부터) */
export function compareIds(shapes: { upload_id: string; rel?: string | null; name: string; reference?: boolean; file_name: string; sha256: string; source?: "step" | "mesh"; part_id?: number | null }[]): CompareInputShape[] {
  const ref = shapes.find((x) => x.reference);
  const out: CompareInputShape[] = [];
  // v0.16.0 메시 형상만 source·part_id(STEP 형상은 v0.15 와 같은 모양)
  const extra = (x: (typeof shapes)[number]) => (x.source === "mesh" ? { source: "mesh" as const, part_id: x.part_id ?? null } : {});
  if (ref) out.push({ id: "d000", name: ref.name.trim(), file_name: ref.file_name, sha256: ref.sha256, upload_id: ref.upload_id, rel: ref.rel ?? null, reference: true, ...extra(ref) });
  let k = 1;
  for (const x of shapes)
    if (x !== ref) out.push({ id: `d${String(k++).padStart(3, "0")}`, name: x.name.trim(), file_name: x.file_name, sha256: x.sha256, upload_id: x.upload_id, rel: x.rel ?? null, reference: false, ...extra(x) });
  return out;
}

/** v0.16.0 목 메시 파트(결정적): 주 파일 이름에 'multi' → 쉘 파트 2개, 아니면 1개 */
export function mockMeshParts(mainFile: string): DoeMeshPart[] {
  return mainFile.toLowerCase().includes("multi")
    ? [{ id: 1001, title: "chassis_rear", n_shells: 182_400 }, { id: 2001, title: "bracket_L", n_shells: 6_120 }]
    : [{ id: 1001, title: "chassis_rear", n_shells: 182_400 }];
}

// ---------------------------------------------------------------- 상태
interface Rec {
  out: Omit<DoeStudyOut, "job" | "result_ready">;
  jobIds: string[];
  /** 진행 중 미리보기의 행렬(끝나면 preview 로) */
  pending: DoeMatrixOut | null;
  cells: DoePreviewCell[] | null;
  result: DoeResultOut | null;
  stepUpload: string | null;
  /** v0.15.0 select 저장 선택 */
  sel?: DoeSelectionOut | null;
  pendingSel?: string | null;
  /** 시험용: 기준 메시가 바뀌어 저장 선택이 무효(409 SELECTION_MISSING reason SELECTION_DROPPED) */
  selDropped?: boolean;
  /** v0.16.2 자동 탐지 seed(GET …/select/auto) — 없으면 404 AUTO_NOT_AVAILABLE */
  autoSel?: DoeSelectAutoOut | null;
  /** v0.17.0 schema 2 스터디의 GRAPH_FAILED(GET …/select/graph 404) */
  graphFailed?: boolean;
}
/** v0.17.0 schema 2(그래프) select 스터디 */
const isG = (r: Rec) => r.out.scenario === "select" && r.out.inputs.select_schema === 2;

const STEPS_OF: Record<string, string[]> = {
  DOE_PREP: ["BD_INPUT", "BD_MESH0", "BD_GEOM", "BD_LOADS", "BD_PREP_REGISTER"],
  DOE_PREVIEW: ["BD_MATRIX", "BD_GRID", "BD_PREVIEW_REGISTER"],
  DOE_RUN: ["BD_BASELINE", "BD_DESIGNS", "BD_POST", "BD_REGISTER"],
};
function doneJob(id: string, projectId: string, studyId: string, jt: JobType, t0: string, t1: string, compare = false): JobOut {
  return {
    id,
    case_id: null,
    project_id: projectId,
    job_type: jt,
    stage: 11,
    lane: "SLOT",
    state: "SUCCEEDED",
    params: { bead_doe_id: studyId },
    result: null,
    warnings: [],
    cancel_requested: false,
    current_step_no: null,
    progress_pct: 100,
    queue_position: null,
    queued_at: t0,
    started_at: t0,
    finished_at: t1,
    failure_code: null,
    failure_message: null,
    retry_of_job_id: null,
    resume_from_step: null,
    created_by: "u-power",
    created_by_name: "김해석",
    created_at: t0,
    updated_at: t1,
    version: 1,
    steps: STEPS_OF[jt].map((k, i) => ({ step_no: i + 1, step_key: k, kind: k === "BD_GEOM" || k === "BD_GRID" || k === "BD_DESIGNS" ? "LOCAL" : "INTERNAL", core_stage: null, state: (compare ? k === "BD_GEOM" : k === "BD_MESH0") ? "SKIPPED" : "SUCCEEDED", progress_pct: 100, exit_code: 0, failure_code: null, failure_message: null, started_at: t0, finished_at: t1 })),
  };
}

export const DEFAULT_SPEC: DoeSpec = {
  method: "lhs",
  n: 30,
  seed: 1,
  params: PARAMS.filter((x) => x.use_default && (x.type === "D" || x.type === "W")).map((x) => ({ name: x.name, lo: x.feasible[0], hi: x.feasible[1] })),
};

export class DoeMock {
  settings: DoeSettingsOut = makeDoeSettings();
  recs: Rec[] = [];
  seededJobs: JobOut[] = [];
  seq = 0;
  /** 시험용: 다음 check-inputs 를 이 오류로 */
  checkError: MockResponse | null = null;
  constructor(private ctx: DoeCtx) {}

  private id(prefix: string) {
    this.seq += 1;
    return `${prefix}-${100 + this.seq}`;
  }

  seed() {
    const es = this.ctx.entries().filter((e) => e.model.name === "75QN80H" && e.model.version === "v072" && e.status === "ACTIVE").map((e) => e.id);
    const base = (id: string, scenario: DoeScenario, title: string, at: string): Rec => ({
      out: {
        id,
        project_id: "p-body",
        scenario,
        title,
        entry_ids: es,
        inputs: {
          step: { file_name: scenario === "same" ? "chassis_rear_mid.step" : "QN80J_chassis_rear_mid.step", sha256: "a1".padEnd(64, "0") },
          mesh: scenario === "mesh" ? { file_name: "QN80J_chr.rad", sha256: "b2".padEnd(64, "0") } : null,
          part_title: scenario === "same" ? "chassis_rear" : "chassis rear",
          inch: 75,
          props: null,
          mesh_size_mm: null,
        },
        phase: "READY",
        version: 3,
        prep: { n_beads: BEADS.length, n_params: PARAMS.length, paicad_version: "0.14.0", warnings: PARAM_WARNINGS, boundary: boundaryCount(scenario, es) },
        doe: null,
        created_by_name: "김해석",
        created_at: at,
      },
      jobIds: [],
      pending: null,
      cells: null,
      result: null,
      stepUpload: null,
    });
    // 1) 완료된 연구(① 같은 모델)
    const a = base("doe-1", "same", "75형 Ch/R 비드 1차", "2026-10-29T01:00:00Z");
    const m = makeMatrix(DEFAULT_SPEC);
    a.cells = makeCells(m);
    a.out.doe = { rev: 1, spec: m.spec, matrix_sha256: m.matrix_sha256, n_designs: m.n_designs, preview: this.previewOf(1, m, a.cells) };
    a.result = makeResult(m.spec, a.cells, a.out.entry_ids, "same");
    a.out.phase = "DONE";
    a.out.version = 5;
    for (const [jt, t0, t1] of [
      ["DOE_PREP", "2026-10-29T01:00:05Z", "2026-10-29T01:12:00Z"],
      ["DOE_PREVIEW", "2026-10-29T01:20:00Z", "2026-10-29T01:24:00Z"],
      ["DOE_RUN", "2026-10-29T01:30:00Z", "2026-10-29T03:02:00Z"],
    ] as [JobType, string, string][]) {
      const j = doneJob(this.id("j-doe"), "p-body", a.out.id, jt, t0, t1);
      this.seededJobs.push(j);
      a.jobIds.push(j.id);
    }
    // 2) 미리보기까지 끝난 연구(② 다른 모델 + B 메시) — 실행 대기
    const b = base("doe-2", "mesh", "QN80J Ch/R 비드 — 75형 ESL", "2026-10-29T04:00:00Z");
    const spec2: DoeSpec = { ...DEFAULT_SPEC, n: 24, seed: 7 };
    const m2 = makeMatrix(spec2);
    b.cells = makeCells(m2);
    b.out.doe = { rev: 1, spec: m2.spec, matrix_sha256: m2.matrix_sha256, n_designs: m2.n_designs, preview: this.previewOf(1, m2, b.cells) };
    b.out.phase = "PREVIEW_READY";
    for (const [jt, t0, t1] of [
      ["DOE_PREP", "2026-10-29T04:00:05Z", "2026-10-29T04:09:00Z"],
      ["DOE_PREVIEW", "2026-10-29T04:12:00Z", "2026-10-29T04:15:00Z"],
    ] as [JobType, string, string][]) {
      const j = doneJob(this.id("j-doe"), "p-body", b.out.id, jt, t0, t1);
      this.seededJobs.push(j);
      b.jobIds.push(j.id);
    }
    // 3) ④ 형상 직접 비교 완료(기준 STEP + 4형상, 1개 정렬 실패)
    const mk = (files: [string, string][], refIdx: number | null) =>
      compareIds(files.map(([f, n], i) => ({ upload_id: "up-cmp-seed", rel: `rad/${f}`, name: n, reference: i === refIdx, file_name: f, sha256: shaOfFile(f) })));
    const cmp = (id: string, title: string, at: string, shapes: CompareInputShape[], refSource: "step" | "case"): Rec => {
      const r = base(id, "compare", title, at);
      r.out.inputs = { step: null, mesh: null, part_title: null, inch: null, props: { t: 1.2, E: 205000, nu: 0.3 }, mesh_size_mm: null, shapes, reference_source: refSource };
      r.out.prep = makeComparePrep(shapes, refSource);
      return r;
    };
    const c = cmp(
      "doe-3",
      "Ch/R 형상 비교 — 75형 4안",
      "2026-11-03T02:00:00Z",
      mk([["chr_base.step", "현행"], ["chr_rib_A.step", "리브 A안"], ["chr_rib_B_rough.step", "리브 B안"], ["chr_bead_C.step", "비드 C안"], ["chr_D_shift.step", "D안(원점 다름)"]], 0),
      "step",
    );
    c.result = makeCompareResult(c.out.prep!, c.out.entry_ids);
    c.out.phase = "DONE";
    c.out.version = 4;
    for (const [jt, t0, t1] of [
      ["DOE_PREP", "2026-11-03T02:00:05Z", "2026-11-03T02:06:00Z"],
      ["DOE_RUN", "2026-11-03T02:10:00Z", "2026-11-03T02:21:00Z"],
    ] as [JobType, string, string][]) {
      const j = doneJob(this.id("j-doe"), "p-body", c.out.id, jt, t0, t1, true);
      this.seededJobs.push(j);
      c.jobIds.push(j.id);
    }
    // 4) ④ 준비 완료(기준 없음 = Case 메시, 1개 크기 불일치) — 비교 실행 대기
    const d = cmp("doe-4", "Ch/R 형상 비교 — Case 기준", "2026-11-04T01:00:00Z", mk([["chr_rib_A.step", "리브 A안"], ["chr_rib_B.step", "리브 B안"], ["chr_big_E.step", "E안(큰 판)"]], null), "case");
    d.out.version = 2;
    const jd = doneJob(this.id("j-doe"), "p-body", d.out.id, "DOE_PREP", "2026-11-04T01:00:05Z", "2026-11-04T01:05:00Z", true);
    this.seededJobs.push(jd);
    d.jobIds.push(jd.id);
    // 4b) v0.16.0 ④ 메시 옵션 완료(기준 = HyperMesh 메시 입력 + STEP 4: CAD · 국부 세분화 · 전역 세분화 · 재메시 폴백(충실도 경고))
    const s7 = compareIds([
      { upload_id: "up-cmp-mesh", rel: "rad/chr_base_0000.rad", name: "현행(HM 메시)", reference: true, file_name: "chr_base_0000.rad", sha256: shaOfFile("chr_base_0000.rad"), source: "mesh", part_id: 1001 },
      ...([["chr_rib_A.step", "리브 A안"], ["chr_rib_F_complex.step", "리브 F안(복잡)"], ["chr_G_hard.step", "G안(곡면)"], ["chr_H_broken_coarse.step", "H안(띠 면)"], ["chr_K_dimple.step", "K안(딤플)"]] as [string, string][]).map(([f, n]) => ({
        upload_id: "up-cmp-mesh", rel: `rad/${f}`, name: n, reference: false, file_name: f, sha256: shaOfFile(f),
      })),
    ]);
    const g = base("doe-7", "compare", "Ch/R 형상 비교 — 메시 옵션(v0.16)", "2026-11-04T05:00:00Z");
    g.out.inputs = { step: null, mesh: null, part_title: null, inch: null, props: { t: 1.2, E: 205000, nu: 0.3 }, mesh_size_mm: null, shapes: s7, reference_source: "step", mesh_mode: "auto", mesh_refine: true };
    g.out.prep = makeComparePrep(s7, "step", "auto", true);
    g.result = makeCompareResult(g.out.prep, g.out.entry_ids);
    g.out.phase = "DONE";
    g.out.version = 4;
    for (const [jt, t0, t1] of [
      ["DOE_PREP", "2026-11-04T05:00:05Z", "2026-11-04T05:14:00Z"],
      ["DOE_RUN", "2026-11-04T05:20:00Z", "2026-11-04T05:41:00Z"],
    ] as [JobType, string, string][]) {
      const j = doneJob(this.id("j-doe"), "p-body", g.out.id, jt, t0, t1, true);
      this.seededJobs.push(j);
      g.jobIds.push(j.id);
    }
    // 5) v0.15.0 비드 직접 선택 — 선택 저장됨(READY, 미리보기 전)
    const sel5 = base("doe-5", "select", "75형 Ch/R 비드 직접 선택", "2026-11-04T03:00:00Z");
    sel5.out.inputs = { step: null, mesh: null, part_title: "chassis_rear", inch: null, props: null, mesh_size_mm: null };
    sel5.out.prep = this.selectPrep();
    this.saveSelection(sel5, selDefaultSelection(), "김해석");
    sel5.out.prep = { ...sel5.out.prep, n_beads: 2, n_params: this.paramsOf(sel5).length };
    sel5.out.version = 4;
    const j5 = doneJob(this.id("j-doe"), "p-body", sel5.out.id, "DOE_PREP", "2026-11-04T03:00:05Z", "2026-11-04T03:02:00Z");
    this.seededJobs.push(j5);
    sel5.jobIds.push(j5.id);
    // 6) 비드 직접 선택 — 미리보기 완료(썸네일 3D 음영·범례)
    const sel6 = base("doe-6", "select", "75형 Ch/R 비드 직접 선택 — 미리보기", "2026-11-04T04:00:00Z");
    sel6.out.inputs = { ...sel5.out.inputs };
    sel6.out.prep = { ...sel5.out.prep };
    this.saveSelection(sel6, selDefaultSelection(), "김해석");
    const ps6 = this.paramsOf(sel6);
    const spec6: DoeSpec = { method: "lhs", n: 24, seed: 3, params: ps6.filter((x) => x.use_default).map((x) => ({ name: x.name, lo: x.default_range[0], hi: x.default_range[1] })) };
    const m6 = makeMatrix(spec6, ps6);
    sel6.cells = this.selectCells(sel6, m6);
    sel6.out.doe = { rev: 1, spec: m6.spec, matrix_sha256: m6.matrix_sha256, n_designs: m6.n_designs, preview: this.previewOf(1, m6, sel6.cells, sel6) };
    sel6.out.phase = "PREVIEW_READY";
    sel6.out.version = 6;
    for (const [jt, t0, t1] of [
      ["DOE_PREP", "2026-11-04T04:00:05Z", "2026-11-04T04:02:00Z"],
      ["DOE_PREVIEW", "2026-11-04T04:10:00Z", "2026-11-04T04:13:00Z"],
    ] as [JobType, string, string][]) {
      const j = doneJob(this.id("j-doe"), "p-body", sel6.out.id, jt, t0, t1);
      this.seededJobs.push(j);
      sel6.jobIds.push(j.id);
    }
    // 8) v0.16.2 자동 탐지 seed — 준비 완료, 선택 미저장(seed = 화면 기본 상태)
    const sel8 = base("doe-8", "select", "75형 Ch/R 비드 자동 탐지", "2026-11-08T02:00:00Z");
    sel8.out.inputs = { ...sel5.out.inputs, step: { file_name: "ChR_75_mid.stp", sha256: "a8".padEnd(64, "0") }, bead_source: "auto" };
    sel8.out.prep = { ...this.selectPrep(), paicad_version: "0.14.0" };
    sel8.autoSel = selAutoSeed();
    sel8.out.version = 2;
    const j8 = doneJob(this.id("j-doe"), "p-body", sel8.out.id, "DOE_PREP", "2026-11-08T02:00:05Z", "2026-11-08T02:03:00Z");
    this.seededJobs.push(j8);
    sel8.jobIds.push(j8.id);
    // 9) 자동 탐지 실패(paicad extract) — 준비는 READY, seed 없음(404) → 직접 선택 도구로
    const sel9 = base("doe-9", "select", "75형 Ch/R 비드 자동 탐지 — 실패", "2026-11-08T03:00:00Z");
    sel9.out.inputs = { ...sel8.out.inputs };
    sel9.out.prep = { ...this.selectPrep(), warnings: [{ code: "AUTO_DETECT_FAILED", message: "", step: "extract", detail: "EXTRACT_NO_BEAD" }] };
    sel9.autoSel = null;
    sel9.out.version = 2;
    const j9 = doneJob(this.id("j-doe"), "p-body", sel9.out.id, "DOE_PREP", "2026-11-08T03:00:05Z", "2026-11-08T03:02:00Z");
    this.seededJobs.push(j9);
    sel9.jobIds.push(j9.id);
    // 10) v0.17.0 비드 네트워크 자동 분류(그래프 seed, STEP 없음) — 준비 완료, 선택 미저장
    const sel10 = base("doe-10", "select", "75형 Ch/R 비드 네트워크 자동 분류", "2026-11-09T02:00:00Z");
    sel10.out.inputs = { ...sel5.out.inputs, bead_source: "auto", select_schema: 2 };
    sel10.out.prep = this.graphPrep(false);
    sel10.autoSel = graphAutoSeed();
    sel10.out.version = 2;
    const j10 = doneJob(this.id("j-doe"), "p-body", sel10.out.id, "DOE_PREP", "2026-11-09T02:00:05Z", "2026-11-09T02:01:10Z");
    this.seededJobs.push(j10);
    sel10.jobIds.push(j10.id);
    // 11) v0.17.0 GRAPH_FAILED — 준비 READY, 그래프 없음(404) → 직접 칠하기(요소 비드)
    const sel11 = base("doe-11", "select", "75형 Ch/R 비드 분류 실패 — 직접 칠하기", "2026-11-09T03:00:00Z");
    sel11.out.inputs = { ...sel5.out.inputs, bead_source: "manual", select_schema: 2 };
    sel11.out.prep = this.graphPrep(true);
    sel11.graphFailed = true;
    sel11.out.version = 2;
    const j11 = doneJob(this.id("j-doe"), "p-body", sel11.out.id, "DOE_PREP", "2026-11-09T03:00:05Z", "2026-11-09T03:01:00Z");
    this.seededJobs.push(j11);
    sel11.jobIds.push(j11.id);
    this.recs.push(a, b, c, d, g, sel5, sel6, sel8, sel9, sel10, sel11);
  }

  /** v0.17.3 시연·시험(?demoMeshSel=1): ② 다른 모델(B 메시) 비드 직접 선택 — doe-14 선택 저장됨(평면도 경계 매핑 층) */
  demoMeshSel() {
    if (this.recs.some((r) => r.out.id === "doe-14")) return;
    const s5 = this.recs.find((r) => r.out.id === "doe-5")!;
    const r: Rec = { ...s5, out: { ...s5.out, id: "doe-14", title: "QN80J Ch/R 비드 직접 선택 — B 메시", created_at: "2026-11-11T03:00:00Z", inputs: { ...s5.out.inputs, mesh: { file_name: "QN80J_chr.rad", sha256: "b2".padEnd(64, "0") }, part_title: "chassis rear", inch: 75, select_base: "mesh" } }, jobIds: [] };
    r.out.prep = { ...s5.out.prep!, boundary: boundaryCount("mesh", r.out.entry_ids) };
    const j = doneJob(this.id("j-doe"), "p-body", "doe-14", "DOE_PREP", "2026-11-11T03:00:05Z", "2026-11-11T03:02:00Z");
    this.seededJobs.push(j);
    r.jobIds.push(j.id);
    this.recs.push(r);
  }

  /** v0.18.0 시연·시험(?demoStepSel=1): ③ STEP 기준 select — doe-15 자동 분류(선택 저장됨 · 좌표 일치 이전 · 추가 형상 영역) · doe-16 직접 선택(삼각형 폴백 · 구멍 스냅 · 미저장 seed = 고정만) · doe-17 이전 방식 ③(paicad) */
  demoStepSel() {
    if (this.recs.some((r) => r.out.id === "doe-15")) return;
    const s10 = this.recs.find((r) => r.out.id === "doe-10")!;
    const step = { file_name: "QN80J_chassis_rear_mid.step", sha256: "d4".padEnd(64, "0") };
    const mk = (id: string, title: string, at: string, src: "auto" | "manual", kind: "ok" | "tria"): Rec => {
      const r: Rec = {
        ...s10,
        out: { ...s10.out, id, title, created_at: at, doe: null, phase: "READY", version: 2, inputs: { ...s10.out.inputs, step, mesh: null, part_title: null, inch: 75, props: { t: 1.0, E: 205000, nu: 0.3 }, mesh_mode: "auto", mesh_refine: true, bead_source: src, select_base: "step", select_schema: 2 }, prep: this.stepPrep(kind), selection: null },
        jobIds: [],
        cells: null,
        result: null,
        sel: null,
        autoSel: stepAutoSeed(src === "auto"),
      };
      const j = doneJob(this.id("j-doe"), "p-body", id, "DOE_PREP", at.replace(":00Z", ":05Z"), at.replace(":00:00Z", ":03:00Z"));
      this.seededJobs.push(j);
      r.jobIds.push(j.id);
      return r;
    };
    const r15 = mk("doe-15", "QN80J Ch/R 비드 — STEP 그래프(자동)", "2026-11-12T01:00:00Z", "auto", "ok");
    this.saveSelection(r15, r15.autoSel!.selection, "차완기");
    r15.out.version = 3;
    const r16 = mk("doe-16", "QN80J Ch/R 비드 — STEP 그래프(직접·삼각형)", "2026-11-12T02:00:00Z", "manual", "tria");
    const tmpl = this.recs.find((r) => r.out.id === "doe-2")!;
    const r17: Rec = { ...tmpl, out: { ...tmpl.out, id: "doe-17", scenario: "step", title: "QN80J Ch/R 비드 — STEP만(이전 방식)", created_at: "2026-11-10T01:00:00Z", inputs: { ...tmpl.out.inputs, step, mesh: null, props: { t: 1.0, E: 205000, nu: 0.3 }, mesh_size_mm: 3 } }, jobIds: [...tmpl.jobIds] };
    this.recs.push(r17, r15, r16);
  }

  /** v0.17.1 시연·시험(?demoLadder=1): ③ 다른 모델(STEP만) 메싱 뒤 긴 사다리 경고 — doe-12 준비 완료(경고 접기) · doe-13 준비 실패(빨간 1줄) */
  demoLadder() {
    if (this.recs.some((r) => r.out.id === "doe-12")) return;
    const tmpl = this.recs.find((r) => r.out.id === "doe-2")!;
    const mk = (id: string, title: string, at: string): Rec => ({
      ...tmpl,
      out: { ...tmpl.out, id, scenario: "step", title, created_at: at, doe: null, phase: "READY", version: 2, inputs: { ...tmpl.out.inputs, step: { file_name: "QN80J_chassis_rear_mid.step", sha256: "c3".padEnd(64, "0") }, mesh: null, props: { t: 1.0, E: 205000, nu: 0.3 }, mesh_size_mm: 3 } },
      jobIds: [],
      cells: null,
      result: null,
    });
    const r12 = mk("doe-12", "QN80J Ch/R 비드 — STEP만(사다리 경고)", "2026-11-11T01:00:00Z");
    r12.out.prep = { ...tmpl.out.prep!, warnings: [...LADDER_WARNINGS, ...PARAM_WARNINGS] };
    const j12 = doneJob(this.id("j-doe"), "p-body", "doe-12", "DOE_PREP", "2026-11-11T01:00:05Z", "2026-11-11T01:31:00Z");
    this.seededJobs.push(j12);
    r12.jobIds.push(j12.id);
    const r13 = mk("doe-13", "QN80J Ch/R 비드 — STEP만(메시 실패)", "2026-11-11T02:00:00Z");
    r13.out.prep = null;
    r13.out.phase = "FAILED";
    const b13 = doneJob(this.id("j-doe"), "p-body", "doe-13", "DOE_PREP", "2026-11-11T02:00:05Z", "2026-11-11T02:22:00Z");
    const j13: JobOut = {
      ...b13,
      state: "FAILED",
      failure_code: "MESH_FAILED",
      failure_message: LADDER_FAIL_TEXT,
      steps: b13.steps!.map((x) =>
        x.step_no === 2 ? { ...x, state: "FAILED", failure_code: "MESH_FAILED", failure_message: LADDER_FAIL_TEXT } : x.step_no > 2 ? { ...x, state: "PENDING", finished_at: null } : { ...x, state: "SUCCEEDED" },
      ),
    };
    this.ctx.jobs().push(j13);
    r13.jobIds.push(j13.id);
    this.recs.push(r12, r13);
  }

  private previewOf(rev: number, m: DoeMatrixOut, cells: DoePreviewCell[], r?: Rec) {
    const sel = r?.out.scenario === "select";
    return {
      rev,
      matrix_sha256: m.matrix_sha256,
      ok: cells.filter((c) => c.status === "READY").length,
      skipped: {
        collision: cells.filter((c) => c.status === "SKIPPED_COLLISION").length,
        fixed: cells.filter((c) => c.status === "SKIPPED_FIXED").length,
        geom: cells.filter((c) => c.status === "SKIPPED_GEOM").length,
        ...(sel ? { mesh: cells.filter((c) => c.status === "FAILED_MESH").length } : {}),
      },
      cells,
      ...(sel ? { warn: cells.filter((c) => c.status === "READY" && c.warnings?.length).length } : {}),
      ...(sel && r ? { selection_sha256: r.sel?.sha256 ?? null, color: { v_max: selColorMax(cells, this.paramsOf(r)), unit: "mm" } } : {}),
    };
  }

  private job(id: string | undefined): JobOut | null {
    if (!id) return null;
    return this.ctx.jobs().find((j) => j.id === id) ?? this.seededJobs.find((j) => j.id === id) ?? null;
  }

  /** 작업 상태 → 연구 상태 반영 */
  private sync(r: Rec) {
    const j = this.job(r.jobIds[r.jobIds.length - 1]);
    if (!j) return;
    if (j.state === "FAILED" || j.state === "INTERRUPTED") {
      if (j.job_type === "DOE_PREP" || j.job_type === "DOE_RUN") r.out.phase = "FAILED";
      else if (r.out.phase === "PREVIEW") r.out.phase = "READY";
      return;
    }
    if (j.state === "CANCELED") {
      if (r.out.phase === "PREVIEW") r.out.phase = "READY";
      if (r.out.phase === "PREP" || r.out.phase === "RUN") r.out.phase = "FAILED";
      return;
    }
    if (j.state !== "SUCCEEDED") return;
    if (r.out.phase === "PREP" && j.job_type === "DOE_PREP" && r.out.scenario === "compare") {
      r.out.phase = "READY";
      r.out.prep = makeComparePrep(r.out.inputs.shapes ?? [], r.out.inputs.reference_source ?? "step", r.out.inputs.mesh_mode ?? null, r.out.inputs.mesh_refine !== false);
      r.out.version += 1;
    }
    if (r.out.phase === "RUN" && j.job_type === "DOE_RUN" && r.out.scenario === "compare" && r.out.prep) {
      r.result = makeCompareResult(r.out.prep, r.out.entry_ids);
      r.out.phase = "DONE";
      r.out.version += 1;
    }
    if (r.out.phase === "PREP" && j.job_type === "DOE_PREP" && isG(r)) {
      // v0.17.0 그래프 스터디: 분류 → 자동 = 그래프 seed(paicad 무관), 수동 = 빈 seed + 같은 트리
      r.out.phase = "READY";
      r.out.prep = r.out.inputs.select_base === "step" ? this.stepPrep("ok") : this.graphPrep(false);
      if (r.out.inputs.select_base === "step") r.autoSel = stepAutoSeed(r.out.inputs.bead_source === "auto");
      else if (r.out.inputs.bead_source === "auto") r.autoSel = graphAutoSeed();
      r.out.version += 1;
    }
    if (r.out.phase === "PREP" && j.job_type === "DOE_PREP" && r.out.scenario === "select") {
      r.out.phase = "READY";
      r.out.prep = this.selectPrep();
      // v0.16.2 자동 탐지(AD-D-2): paicad 있으면 seed, 없으면 AUTO_DETECT_FAILED{step:"version"} + seed 없음(준비는 READY)
      if (r.out.inputs.bead_source === "auto") {
        if (this.settings.paicad.ready) r.autoSel = selAutoSeed();
        else r.out.prep = { ...r.out.prep, warnings: [...r.out.prep.warnings, { code: "AUTO_DETECT_FAILED", step: "version" }] };
      }
      if (r.out.inputs.select_base === "mesh") r.out.prep = { ...r.out.prep, boundary: boundaryCount("mesh", r.out.entry_ids) };
      r.out.version += 1;
    }
    if (r.out.phase === "PREP" && j.job_type === "DOE_PREP") {
      r.out.phase = "READY";
      r.out.prep = {
        n_beads: BEADS.length,
        n_params: PARAMS.length,
        paicad_version: "0.14.0",
        warnings: PARAM_WARNINGS,
        boundary: boundaryCount(r.out.scenario, r.out.entry_ids),
      };
      r.out.version += 1;
    }
    if (r.out.phase === "PREVIEW" && j.job_type === "DOE_PREVIEW" && r.pending && r.out.doe) {
      r.cells = r.out.scenario === "select" ? this.selectCells(r, r.pending) : makeCells(r.pending);
      r.out.doe.preview = this.previewOf(r.out.doe.rev, r.pending, r.cells, r);
      r.pending = null;
      r.out.phase = "PREVIEW_READY";
      r.out.version += 1;
    }
    if (r.out.phase === "RUN" && j.job_type === "DOE_RUN" && r.out.doe && r.cells) {
      r.result = makeResult(r.out.doe.spec, r.cells, r.out.entry_ids, r.out.scenario, this.paramsOf(r));
      r.out.phase = "DONE";
      r.out.version += 1;
    }
  }

  private studyOut(r: Rec): DoeStudyOut {
    this.sync(r);
    const selection = r.out.scenario === "select" ? (r.sel ? { rev: r.sel.rev, sha256: r.sel.sha256, mesh_sha256: r.sel.derived.mesh_sha256 ?? null, n_beads: r.sel.input.beads.length, n_warnings: r.sel.derived.warnings?.length ?? 0, updated_by_name: r.sel.updated_by_name, updated_at: r.sel.updated_at } : null) : undefined;
    return { ...r.out, ...(selection !== undefined ? { selection } : {}), job: this.job(r.jobIds[r.jobIds.length - 1]), result_ready: r.out.phase === "DONE" };
  }

  // ---------------------------------------------------------------- v0.15.0 select
  private selectPrep(): NonNullable<DoeStudyOut["prep"]> {
    const mf = selManifest();
    const ready = this.settings.paicad.ready;
    return {
      n_beads: 0,
      n_params: 0,
      paicad_version: ready ? this.settings.paicad.version : null,
      warnings: ready ? [] : [{ code: "FIXED_INFO_MISSING", message: "체결 정보 없음 — 체결부를 고정으로 칠하세요" }],
      n_nodes: mf.n_nodes,
      n_elems: mf.n_elems,
      fixed: ready ? { source: "scan", n: mf.fixed.scan_n } : { source: "none", n: 0 },
    };
  }
  /** v0.17.0 schema 2 준비 요약(H6 목 메시) — failed = GRAPH_FAILED{TIMEOUT} 경고 */
  /** v0.18.0 ③ STEP 기준 준비 요약(목): ok = cad 메시·좌표 일치 이전·추가 형상, tria = 삼각형 폴백·B 구멍 스냅(못 옮김 1)·영역 = 전체 */
  stepPrep(kind: "ok" | "tria"): NonNullable<DoeStudyOut["prep"]> {
    const mf = graphManifest();
    const tria = kind === "tria";
    const nOut = tria ? 0 : Math.round(mf.n_elems * 0.18);
    return {
      n_beads: 0,
      n_params: 0,
      paicad_version: null,
      select_base: "step",
      n_nodes: mf.n_nodes,
      n_elems: mf.n_elems,
      mesh: { size_mm: 3, gmsh_version: "4.13.1", method: tria ? "tria" : "cad", tri_frac: tria ? 1 : 0.02, stage_times: [{ stage: "cad", outcome: tria ? "FAILED_MESH" : "READY", seconds: 41.2, tries: 1 }, ...(tria ? [{ stage: "freeform", outcome: "FAILED_MESH" as const, seconds: 63.5, tries: 1 }, { stage: "tria", outcome: "READY" as const, seconds: 8.1, tries: 1 }] : [])] },
      fixed: { source: "a_transfer", n: mf.fixed.scan_n, xfer: tria ? { method: "ab_hole_snap", matched: 11, unmatched: 1, frame_ok: false } : { method: "xyz_nearest", matched: 12, unmatched: 0, frame_ok: true } },
      region: { mode: "auto", n_in: mf.n_elems - nOut, n_out: nOut },
      boundary: { n_warn: tria ? 1 : 0, n_info: 0 },
      warnings: [
        ...(tria
          ? [
              { code: "MESH_TRIA_FALLBACK", message: "CAD·freeform 메시가 실패해 OCC 삼각형 메시로 대신했습니다 [단계별: cad 실패 41.2 s · freeform 실패 63.5 s · tria 성공 8.1 s]" },
              { code: "STEP_GRAPH_TRIA", mesh_method: "tria", tri_frac: 1 },
              { code: "FIXED_XFER_UNMATCHED", label: "F07", d_mm: 14.2, level: "info" as const },
            ]
          : [{ code: "STEP_GRAPH_REGION", n_in: mf.n_elems - nOut, n_out: nOut, out_bbox: [[0, 0, 16.7], [800, 120, 29.6]], mode: "auto", level: "info" as const }]),
      ],
    };
  }
  private graphPrep(failed: boolean): NonNullable<DoeStudyOut["prep"]> {
    const mf = graphManifest();
    return { n_beads: 0, n_params: 0, paicad_version: null, warnings: failed ? [{ code: "GRAPH_FAILED", detail: "TIMEOUT", message: "" }] : [], n_nodes: mf.n_nodes, n_elems: mf.n_elems, fixed: { source: "scan", n: mf.fixed.scan_n } };
  }
  /** select 변수(선택 저장 후) — 행렬·결과의 공칭·변수 이름 */
  paramsOf(r: Rec): DoeParam[] {
    if (r.out.scenario !== "select") return DEFAULT_PARAMS;
    if (!r.sel) return [];
    if (r.sel.input.schema_version === 2) return graphParams(r.sel.input).params;
    return selParams(r.sel.input, r.sel.derived, this.settings.select?.fixed_policy ?? "warn").params;
  }
  private selectCells(r: Rec, m: DoeMatrixOut): DoePreviewCell[] {
    const ps = this.paramsOf(r);
    const pol = { fixed: this.settings.select?.fixed_policy ?? "warn", quality: this.settings.select?.quality_fail_policy ?? "warn" } as const;
    return m.designs.filter((d) => d.id !== "d000").map((d) => ({ id: d.id, values: d.values, ...selCellStatus(d.id, d.values, ps, pol) }));
  }
  saveSelection(r: Rec, input: DoeSelectionAny, who: string) {
    if (input.schema_version === 2) {
      const d = graphDerive(input).body as import("../api/types").DoeDeriveOut;
      const rev = (r.sel?.rev ?? 0) + 1;
      r.sel = { rev, sha256: d.sha256, input, derived: { ...d, rev }, updated_by_name: who, updated_at: this.ctx.now() };
      return;
    }
    const { out } = selDerive(input, this.settings);
    const rev = (r.sel?.rev ?? 0) + 1;
    const { slope_suggested: _s, ...derived } = out;
    void _s;
    r.sel = { rev, sha256: out.sha256, input, derived: { ...derived, rev }, updated_by_name: who, updated_at: this.ctx.now() };
  }
  /** select 경로(§9). null = 해당 없음 */
  private handleSelect(rec: Rec, method: string, sub: string, query: URLSearchParams, b: Record<string, unknown>): MockResponse | null {
    const prepReady = rec.out.phase !== "PREP" && !!rec.out.prep;
    const notReady = () => err(409, "PREP_NOT_READY", "입력 준비가 끝나지 않았습니다.");
    let r: RegExpMatchArray | null;
    // ---- v0.17.0 schema 2(그래프) 스터디: H6 목 메시·graph.bin·GET …/select/graph
    if (isG(rec)) {
      const g = this.handleGraph(rec, method, sub, query, b, prepReady);
      if (g) return g;
    }
    if ((r = sub.match(/^\/select\/view\/([^/]+)$/)) && method === "GET") {
      if (!prepReady) return notReady();
      const m = selMesh();
      if (r[1] === "select_manifest.json") return ok(selManifest());
      if (r[1] === "part.glb") return { status: 200, body: m.glb };
      if (r[1] === "select.bin") return { status: 200, body: m.bin };
      return err(404, "NOT_FOUND", "파일이 없습니다.");
    }
    if (method === "POST" && sub === "/select/derive") {
      if (!prepReady) return notReady();
      const sel = b.selection as DoeSelectionIn | undefined;
      const bad = selValidate(sel, this.settings);
      if (bad) return bad;
      return ok(selDerive(sel!, this.settings).out);
    }
    if (method === "GET" && sub === "/select/auto") {
      if (!prepReady) return notReady();
      // v0.18.0 SG-D-16: ③ STEP 기준은 bead_source 와 무관하게 seed(manual = 빈 비드 + fixed_user)
      if ((rec.out.inputs.bead_source !== "auto" && rec.out.inputs.select_base !== "step") || !rec.autoSel) return err(404, "AUTO_NOT_AVAILABLE", "자동 탐지 결과가 없습니다.");
      return ok(rec.autoSel);
    }
    if (method === "GET" && sub === "/selection") {
      if (!prepReady) return notReady();
      return ok(rec.sel && !rec.selDropped ? rec.sel : null);
    }
    if (method === "PUT" && sub === "/selection") {
      if (!prepReady) return notReady();
      if (b.version !== rec.out.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로 고친 뒤 다시 시도하세요");
      if (this.active(rec)) return err(409, "JOB_ACTIVE", "이 연구의 작업이 진행 중입니다.");
      if (rec.out.phase === "RUN" || rec.out.phase === "DONE") return err(409, "ALREADY_RUN", "이미 실행했습니다 — 복제해서 새 연구로.");
      const sel = b.selection as DoeSelectionIn | undefined;
      const bad = selValidate(sel, this.settings);
      if (bad) return bad;
      this.saveSelection(rec, sel!, this.ctx.me().display_name);
      rec.selDropped = false;
      rec.out.version += 1;
      rec.out.prep = { ...rec.out.prep!, n_beads: sel!.beads.length, n_params: this.paramsOf(rec).length };
      return ok(this.studyOut(rec));
    }
    if (method === "GET" && sub === "/select/basis") {
      const pv = rec.out.doe?.preview;
      if (!rec.sel || !pv) return err(409, "PREVIEW_NOT_READY", "미리보기 전이라 기저가 없습니다.");
      const want = query.get("rev");
      if (want != null && Number(want) !== rec.sel.rev) return err(404, "FILE_NOT_FOUND", "그 선택 rev 의 기저가 없습니다(선택이 바뀌었으면 다시 미리보기)");
      const bs = selBasis(rec.sel.input as DoeSelectionIn, this.settings);
      if (query.get("meta") === "1") return ok(bs.meta);
      return { status: 200, body: bs.bin };
    }
    if (method === "GET" && (sub === "/params" || sub === "/plan-view")) {
      if (!prepReady) return notReady();
      if (!rec.sel || rec.selDropped) return err(409, "SELECTION_MISSING", rec.selDropped ? "비드 선택을 저장한 뒤에 하세요 — 기준 메시가 바뀌어 저장된 선택을 쓸 수 없습니다" : "비드 선택을 먼저 저장하세요.", rec.selDropped ? { reason: "SELECTION_DROPPED" } : {});
      return ok(sub === "/params" ? selParams(rec.sel.input as DoeSelectionIn, rec.sel.derived, this.settings.select?.fixed_policy ?? "warn") : withBoundary(rec, selPlan(rec.sel.input as DoeSelectionIn, this.settings)));
    }
    if (method === "POST" && (sub === "/matrix" || sub === "/preview") && !rec.sel) {
      if (!prepReady) return notReady();
      return err(409, "SELECTION_MISSING", "비드 선택을 먼저 저장하세요.");
    }
    if ((r = sub.match(/^\/preview\/thumb\/([^/]+)$/)) && method === "GET") {
      const did = decodeURIComponent(r[1]);
      const ps = this.paramsOf(rec);
      const v = rec.out.doe?.preview?.color?.v_max ?? 1;
      if (did === "d000" && rec.out.doe?.preview) return { status: 200, body: selThumbSvg(null, ps, v, "NOMINAL") };
      const c = rec.cells?.find((x) => x.id === did);
      if (!c || !c.thumb) return err(404, "NOT_FOUND", "썸네일이 없습니다.");
      return { status: 200, body: selThumbSvg(c.values, ps, v, c.status) };
    }
    if (method === "POST" && sub === "/run") {
      const pv = rec.out.doe?.preview;
      if (rec.sel && pv && pv.selection_sha256 !== rec.sel.sha256) return err(409, "PREVIEW_STALE", "비드 선택이 미리보기 뒤에 바뀌었습니다 — 미리보기를 다시 실행하세요.");
    }
    return null;
  }

  /** v0.17.0 그래프 스터디 select 경로(esl_beadgraph.md §6.1). null = 공통 처리 */
  private handleGraph(rec: Rec, method: string, sub: string, query: URLSearchParams, b: Record<string, unknown>, prepReady: boolean): MockResponse | null {
    const notReady = () => err(409, "PREP_NOT_READY", "입력 준비가 끝나지 않았습니다.");
    let r: RegExpMatchArray | null;
    if ((r = sub.match(/^\/select\/view\/([^/]+)$/)) && method === "GET") {
      if (!prepReady) return notReady();
      const m = graphMesh();
      if (r[1] === "select_manifest.json") return ok(graphManifest());
      if (r[1] === "part.glb") return { status: 200, body: m.glb };
      if (r[1] === "select.bin") return { status: 200, body: m.bin };
      if (r[1] === "graph.bin") return rec.graphFailed ? err(404, "GRAPH_NOT_AVAILABLE", "분류 결과가 없습니다.") : { status: 200, body: m.graphBin };
      return err(404, "NOT_FOUND", "파일이 없습니다.");
    }
    if (method === "GET" && sub === "/select/graph") {
      if (!prepReady) return notReady();
      return rec.graphFailed ? err(404, "GRAPH_NOT_AVAILABLE", "분류 결과가 없습니다(GRAPH_FAILED).") : ok(graphOut());
    }
    if (method === "POST" && sub === "/select/derive") {
      if (!prepReady) return notReady();
      const sel = b.selection as DoeSelectionV2 | undefined;
      return graphValidate(sel, !rec.graphFailed) ?? graphDerive(sel!);
    }
    if (method === "PUT" && sub === "/selection") {
      if (!prepReady) return notReady();
      if (b.version !== rec.out.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로 고친 뒤 다시 시도하세요");
      if (rec.out.phase === "RUN" || rec.out.phase === "DONE") return err(409, "ALREADY_RUN", "이미 실행했습니다 — 복제해서 새 연구로.");
      const sel = b.selection as DoeSelectionV2 | undefined;
      const bad = graphValidate(sel, !rec.graphFailed);
      if (bad) return bad;
      this.saveSelection(rec, sel!, this.ctx.me().display_name);
      rec.out.version += 1;
      rec.out.prep = { ...rec.out.prep!, n_beads: sel!.beads.length, n_params: this.paramsOf(rec).length };
      return ok(this.studyOut(rec));
    }
    if (method === "GET" && sub === "/select/basis" && rec.sel?.input.schema_version === 2) {
      if (!rec.out.doe?.preview) return err(409, "PREVIEW_NOT_READY", "미리보기 전이라 기저가 없습니다.");
      const bs = graphBasis(rec.sel.input);
      return query.get("meta") === "1" ? ok(bs.meta) : { status: 200, body: bs.bin };
    }
    if (method === "GET" && (sub === "/params" || sub === "/plan-view") && rec.sel?.input.schema_version === 2) {
      if (!prepReady) return notReady();
      return ok(sub === "/params" ? graphParams(rec.sel.input) : rec.out.inputs.select_base === "step" ? stepPlan(rec.sel.input) : withBoundary(rec, graphPlan(rec.sel.input)));
    }
    return null;
  }

  private active(r: Rec) {
    const j = this.job(r.jobIds[r.jobIds.length - 1]);
    return !!j && (j.state === "QUEUED" || j.state === "RUNNING");
  }

  private meshCheck(uploadId: string, main: string): MeshCheckOut {
    return {
      upload_id: uploadId,
      ok: true,
      sha256: `sha-${uploadId}`.padEnd(64, "c"),
      format: "rad",
      file_name: main.split("/").pop()!,
      parts: [{ id: 12, title: "chassis rear", n_elems: 218_400 }],
      part_title: "chassis rear",
      mesh: { n_nodes: 221_380, n_elems: 218_400, n_quad: 214_900, n_tria: 3_500, unsupported: {} },
      pids: [{ pid: 12, title: "chr_t1.2", n_elems: 218_400, thickness: 1.2, E: 205000, nu: 0.3 }],
      frame: { L_xi: 1652, L_eta: 940, z_range: [-14, 9], warnings: [] },
      quality: { errors: [], warnings: [] },
    } as unknown as MeshCheckOut;
  }

  private check(b: Record<string, unknown>): MockResponse {
    if (this.checkError) return this.checkError;
    const pid = String(b.project_id ?? "");
    if (!this.ctx.canRun(pid)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
    const scenario = b.scenario as DoeScenario;
    if (scenario === "compare") return this.checkCompare(b, pid);
    if (!this.settings.enabled) return err(503, this.settings.reason ?? "DOE_DISABLED", "강성 평가 스터디를 쓸 수 없습니다.");
    if (!["same", "mesh", "step", "select"].includes(scenario)) return err(422, "INVALID_PARAMS", "시나리오가 올바르지 않습니다.");
    if (scenario === "select") return this.checkSelect(b, pid);
    const ids = (b.entry_ids as string[]) ?? [];
    const es = this.ctx.entries();
    const sel = ids.map((id) => es.find((e) => e.id === id && e.project_id === pid && e.status === "ACTIVE"));
    if (!ids.length || sel.some((e) => !e)) return err(422, "ENTRY_NOT_FOUND", "선택한 ESL 중 이 프로젝트의 활성 항목이 아닌 것이 있습니다.");
    if (ids.length > this.settings.max_entries) return err(422, "INVALID_PARAMS", `ESL 은 최대 ${this.settings.max_entries}개입니다.`);
    const up = this.ctx.upload(String(b.step_upload_id ?? ""));
    if (!up) return err(404, "UPLOAD_NOT_FOUND", "STEP 업로드를 찾을 수 없습니다.");
    if (!up.ready) return err(409, "UPLOAD_NOT_READY", "STEP 업로드가 아직 끝나지 않았습니다.");
    const step = up.files.find((f) => /\.(step|stp)$/i.test(f));
    if (!step) return err(422, "STEP_INVALID", "STEP(.step·.stp) 파일이 없습니다.");
    this.ctx.markUploadCompleted(String(b.step_upload_id));
    const first = sel[0]!;
    const entries = sel.map((e) => ({ entry_id: e!.id, ok: scenario !== "same" || e!.topo_sha256 === first.topo_sha256, reason: scenario === "same" && e!.topo_sha256 !== first.topo_sha256 ? "MODEL_MISMATCH" : null }));
    const out: DoeCheckOut = { ok: entries.every((x) => x.ok), step: { file_name: step.split("/").pop()!, sha256: `sha-${b.step_upload_id}`.padEnd(64, "a"), size_mb: 3.4 }, entries, warnings: [] };
    if (scenario === "same") {
      out.base = { entry_id: first.id, case_id: first.case_id, case_title: first.case_title ?? null, part_title: "chassis_rear", n_nodes: 221_380, n_elems: 218_400, topo_sha256: first.topo_sha256 ?? "" };
      if (first.scene.scenario === "CUMULATIVE") out.warnings.push({ code: "BD_BASE_CUMULATIVE", message: "기준 Case 가 누적 씬입니다 — 형상은 rad /NODE 공칭, ESL 은 누적 변형 상태 기준" });
    }
    if (scenario === "mesh") {
      const mu = this.ctx.upload(String(b.mesh_upload_id ?? ""));
      if (!mu) return err(404, "UPLOAD_NOT_FOUND", "B 메시 업로드를 찾을 수 없습니다.");
      if (!mu.ready) return err(409, "UPLOAD_NOT_READY", "B 메시 업로드가 아직 끝나지 않았습니다.");
      const main = mu.files.find((f) => /\.rad$/i.test(f)) ?? mu.files.find((f) => /\.inc$/i.test(f));
      if (!main) return err(422, "MESH_INVALID", "B 메시(.rad 또는 .inc)가 없습니다.");
      this.ctx.markUploadCompleted(String(b.mesh_upload_id));
      out.mesh = this.meshCheck(String(b.mesh_upload_id), main);
      out.size = { L_xi: 1652, L_eta: 940, inch: typeof b.inch === "number" ? b.inch : 75, rel_xi: -0.005, rel_eta: -0.0074 };
    }
    if (scenario === "step") {
      out.size = null;
      out.props_default = { t: 1.2, E: 205000, nu: 0.3 };
      out.mesh_size_default_mm = 5;
    }
    return ok(out);
  }

  /** v0.18.0 ③ STEP 기준 select check-inputs(esl_step_graph.md SG-D-3): STEP 필수, 금지 = mesh_upload_id·part_title·mesh_size_mm, 같은 모델 검사 없음 */
  private checkSelectStep(b: Record<string, unknown>, pid: string, src: string): MockResponse {
    if (this.settings.scenarios.select_step === false || !this.settings.gmsh.ready) return err(503, "GMSH_UNAVAILABLE", "메시 생성기(gmsh)가 없어 'STEP만' 시나리오를 쓸 수 없습니다.");
    if (b.mesh_upload_id != null || b.part_title != null || b.mesh_size_mm != null) return err(422, "INVALID_PARAMS", "③ STEP 기준에는 B 메시·파트 제목·요소 크기를 쓰지 않습니다.");
    if (src === "auto" && this.settings.scenarios.select_auto === false) return err(503, "SELECT_DISABLED", "서버에서 비드 자동 분류가 꺼져 있습니다.");
    if (b.step_upload_id == null) return err(422, "INVALID_PARAMS", "STEP 이 필요합니다.");
    const ids = (b.entry_ids as string[]) ?? [];
    const es = this.ctx.entries();
    const sel = ids.map((id) => es.find((e) => e.id === id && e.project_id === pid && e.status === "ACTIVE"));
    if (!ids.length || sel.some((e) => !e)) return err(422, "ENTRY_NOT_FOUND", "선택한 ESL 중 이 프로젝트의 활성 항목이 아닌 것이 있습니다.");
    const up = this.ctx.upload(String(b.step_upload_id));
    if (!up) return err(404, "UPLOAD_NOT_FOUND", "STEP 업로드를 찾을 수 없습니다.");
    if (!up.ready) return err(409, "UPLOAD_NOT_READY", "STEP 업로드가 아직 끝나지 않았습니다.");
    const f = up.files.find((x) => /\.(step|stp)$/i.test(x));
    if (!f) return err(422, "STEP_INVALID", "STEP(.step·.stp) 파일이 없습니다.");
    this.ctx.markUploadCompleted(String(b.step_upload_id));
    const out: DoeCheckOut = {
      ok: true,
      step: { file_name: f.split("/").pop()!, sha256: `sha-${b.step_upload_id}`.padEnd(64, "a"), size_mb: 3.4 },
      entries: sel.map((e) => ({ entry_id: e!.id, ok: true, reason: null })),
      size: null,
      props_default: { t: 1.2, E: 205000, nu: 0.3 },
      mesh_mode: (b.mesh_mode as DoeCheckOut["mesh_mode"]) ?? this.settings.compare?.mesh_mode ?? "auto",
      remesh_available: this.settings.compare?.remesh_available ?? false,
      warnings: [],
    };
    return ok(out);
  }

  /** v0.15.0 select check-inputs: ① 과 같음(base), paicad 무관(BS-D-2).
   *  v0.16.2(esl_bead_auto.md §3.3): bead_source auto = STEP 필수·manual = STEP 금지, select_base mesh = B 메시 필수(② 검사 — 같은 모델 검사 없음) */
  private checkSelect(b: Record<string, unknown>, pid: string): MockResponse {
    const sc = this.settings.select;
    if (!sc?.enabled) return err(503, "SELECT_DISABLED", "비드 직접 선택이 서버에서 꺼져 있습니다.");
    const src = (b.bead_source ?? "manual") as string;
    const baseK = (b.select_base ?? "case") as string;
    if (!["auto", "manual"].includes(src) || !["case", "mesh", "step"].includes(baseK)) return err(422, "INVALID_PARAMS", "bead_source·select_base 가 올바르지 않습니다.");
    if (baseK === "step") return this.checkSelectStep(b, pid, src);
    if (b.shapes != null) return err(422, "INVALID_PARAMS", "비드 선택에는 형상을 쓰지 않습니다.");
    if (src === "manual" && b.step_upload_id != null) return err(422, "INVALID_PARAMS", "직접 선택에는 STEP 을 쓰지 않습니다.");
    // v0.17.0(BG §5.3): auto 의 STEP 은 선택(힌트) — 자동 분류는 paicad 무관
    if (src === "auto" && this.settings.scenarios.select_auto === false) return err(503, "SELECT_DISABLED", "서버에서 비드 자동 분류가 꺼져 있습니다.");
    if (baseK === "case" && (b.mesh_upload_id != null || b.part_title != null)) return err(422, "INVALID_PARAMS", "① 비드 선택에는 B 메시·파트 제목을 쓰지 않습니다.");
    if (baseK === "mesh" && b.mesh_upload_id == null) return err(422, "INVALID_PARAMS", "B 메시가 필요합니다.");
    const ids = (b.entry_ids as string[]) ?? [];
    const es = this.ctx.entries();
    const sel = ids.map((id) => es.find((e) => e.id === id && e.project_id === pid && e.status === "ACTIVE"));
    if (!ids.length || sel.some((e) => !e)) return err(422, "ENTRY_NOT_FOUND", "선택한 ESL 중 이 프로젝트의 활성 항목이 아닌 것이 있습니다.");
    let step: DoeCheckOut["step"] = null;
    if (src === "auto" && b.step_upload_id != null) {
      const up = this.ctx.upload(String(b.step_upload_id));
      if (!up) return err(404, "UPLOAD_NOT_FOUND", "STEP 업로드를 찾을 수 없습니다.");
      if (!up.ready) return err(409, "UPLOAD_NOT_READY", "STEP 업로드가 아직 끝나지 않았습니다.");
      const f = up.files.find((x) => /\.(step|stp)$/i.test(x));
      if (!f) return err(422, "STEP_INVALID", "STEP(.step·.stp) 파일이 없습니다.");
      this.ctx.markUploadCompleted(String(b.step_upload_id));
      step = { file_name: f.split("/").pop()!, sha256: `sha-${b.step_upload_id}`.padEnd(64, "a"), size_mb: 3.4 };
    }
    const first = sel[0]!;
    if (baseK === "mesh") {
      const mu = this.ctx.upload(String(b.mesh_upload_id));
      if (!mu) return err(404, "UPLOAD_NOT_FOUND", "B 메시 업로드를 찾을 수 없습니다.");
      if (!mu.ready) return err(409, "UPLOAD_NOT_READY", "B 메시 업로드가 아직 끝나지 않았습니다.");
      const main = mu.files.find((f) => /\.rad$/i.test(f)) ?? mu.files.find((f) => /\.inc$/i.test(f));
      if (!main) return err(422, "MESH_INVALID", "B 메시(.rad 또는 .inc)가 없습니다.");
      this.ctx.markUploadCompleted(String(b.mesh_upload_id));
      const out: DoeCheckOut = {
        ok: true,
        step,
        entries: sel.map((e) => ({ entry_id: e!.id, ok: true, reason: null })),
        mesh: this.meshCheck(String(b.mesh_upload_id), main),
        size: { L_xi: 1652, L_eta: 940, inch: typeof b.inch === "number" ? b.inch : 75, rel_xi: -0.005, rel_eta: -0.0074 },
        warnings: [],
      };
      return ok(out);
    }
    const entries = sel.map((e) => ({ entry_id: e!.id, ok: e!.topo_sha256 === first.topo_sha256, reason: e!.topo_sha256 !== first.topo_sha256 ? "MODEL_MISMATCH" : null }));
    const mf = selManifest();
    const out: DoeCheckOut = {
      ok: entries.every((x) => x.ok),
      step,
      entries,
      base: { entry_id: first.id, case_id: first.case_id, case_title: first.case_title ?? null, part_title: "chassis_rear", n_nodes: mf.n_nodes, n_elems: mf.n_elems, topo_sha256: first.topo_sha256 ?? "" },
      warnings: [],
    };
    return ok(out);
  }


  /** ④ check-inputs(§3 검증 순서) — paicad 무관(SC-D-3) */
  private checkCompare(b: Record<string, unknown>, pid: string): MockResponse {
    const st = this.settings;
    const why = st.compare_reason ?? (!st.enabled && st.reason === "DOE_DISABLED" ? "DOE_DISABLED" : !st.scenarios.compare ? (st.gmsh.ready ? "COMPARE_DISABLED" : "GMSH_UNAVAILABLE") : null);
    if (why === "DOE_DISABLED") return err(503, "DOE_DISABLED", "강성 평가 스터디가 꺼져 있습니다.");
    if (why) return err(503, why, why === "GMSH_UNAVAILABLE" ? "gmsh 가 없습니다." : "형상 직접 비교가 꺼져 있습니다.");
    if (b.step_upload_id != null || b.mesh_upload_id != null || b.part_title != null) return err(422, "INVALID_PARAMS", "형상 직접 비교에는 step_upload_id·mesh_upload_id·part_title 을 쓰지 않습니다.");
    const ids = (b.entry_ids as string[]) ?? [];
    const es = this.ctx.entries();
    const sel = ids.map((id) => es.find((e) => e.id === id && e.project_id === pid && e.status === "ACTIVE"));
    if (!ids.length || sel.some((e) => !e)) return err(422, "ENTRY_NOT_FOUND", "선택한 ESL 중 이 프로젝트의 활성 항목이 아닌 것이 있습니다.");
    if (ids.length > st.max_entries) return err(422, "INVALID_PARAMS", `ESL 은 최대 ${st.max_entries}개입니다.`);
    const shapes = (Array.isArray(b.shapes) ? b.shapes : []) as CompareShapeIn[];
    const max = st.compare?.max_shapes ?? 20;
    if (!shapes.length) return err(422, "SHAPES_EMPTY", "형상이 없습니다.");
    if (shapes.length > max) return err(422, "SHAPES_TOO_MANY", `형상은 최대 ${max}개입니다.`);
    const nRef = shapes.filter((x) => x.reference).length;
    if (nRef > 1) return err(422, "REFERENCE_MULTIPLE", "기준 형상은 하나만 지정할 수 있습니다.");
    if (nRef ? shapes.length < 2 : shapes.length < 1) return err(422, "SHAPES_TOO_FEW", "비교할 형상이 부족합니다.");
    const seen = new Set<string>();
    for (let i = 0; i < shapes.length; i++) {
      const n = String(shapes[i].name ?? "").trim();
      if (!n || n.length > 64 || CTRL_RE.test(n)) return err(422, "SHAPE_NAME_INVALID", "형상 이름이 올바르지 않습니다.", { index: i });
      if (seen.has(n.toLowerCase())) return err(422, "SHAPE_NAME_DUPLICATE", "형상 이름이 겹칩니다.", { index: i });
      seen.add(n.toLowerCase());
    }
    // 같은 (upload_id, rel) 2번, 또는 한 업로드를 여러 형상이 쓰는데 rel 이 없으면 INVALID_PARAMS(서버 _compare_check 와 같음)
    const keyOf = (x: CompareShapeIn) => `${x.upload_id}\u0000${x.rel ?? ""}`;
    const perUp = (u: string) => shapes.filter((x) => x.upload_id === u).length;
    if (new Set(shapes.map(keyOf)).size < shapes.length || shapes.some((x) => !x.rel && perUp(x.upload_id) > 1))
      return err(422, "INVALID_PARAMS", "같은 업로드 파일(upload_id·rel)을 두 번 넣었습니다 — 한 업로드에 STEP 이 여러 개면 형상마다 rel 을 주세요.");
    // v0.16.0 메시 방식·출처 검사(§6 순서)
    const cc = st.compare;
    const mode = b.mesh_mode;
    if (mode != null && mode !== "cad" && mode !== "remesh" && mode !== "freeform" && mode !== "auto") return err(422, "INVALID_PARAMS", "메시 방식이 올바르지 않습니다.");
    if ((mode === "remesh" || mode === "freeform") && !cc?.remesh_available) return err(422, "REMESH_UNAVAILABLE", `이 gmsh 버전(${st.gmsh.version ?? "?"})은 삼각형 재메시를 지원하지 않습니다`);
    const rows: DoeCheckShape[] = [];
    for (let i = 0; i < shapes.length; i++) {
      const src = shapes[i].source ?? "step";
      if (src !== "step" && src !== "mesh") return err(422, "INVALID_PARAMS", "형상 출처가 올바르지 않습니다.", { index: i });
      if (src === "step" && shapes[i].part_id != null) return err(422, "INVALID_PARAMS", "STEP 형상에는 파트 ID 를 쓰지 않습니다.", { index: i });
      const up = this.ctx.upload(String(shapes[i].upload_id ?? ""));
      if (!up) return err(404, "UPLOAD_NOT_FOUND", src === "mesh" ? "메시 업로드를 찾을 수 없습니다." : "STEP 업로드를 찾을 수 없습니다.", { index: i });
      if (!up.ready) return err(409, "UPLOAD_NOT_READY", "업로드가 아직 끝나지 않았습니다.", { index: i });
      if (src === "mesh") {
        if (!cc?.mesh_input?.enabled) return err(422, "MESH_FORMAT_UNSUPPORTED", "메시 입력이 꺼져 있습니다.", { index: i });
        const meshes = up.files.filter((x) => /\.(rad|inc)$/i.test(x));
        const rel = shapes[i].rel;
        if (rel && /\.(bdf|fem)$/i.test(rel)) return err(422, "MESH_FORMAT_UNSUPPORTED", "Nastran 메시는 아직 지원하지 않습니다(.rad·.inc 만).", { index: i });
        const main = rel ? meshes.find((x) => x === rel) : meshes.length === 1 ? meshes[0] : undefined;
        if (!main) return err(422, "MESH_INPUT_INVALID", rel ? `업로드에 메시 파일 '${rel}' 이 없습니다.` : "업로드에 메시 파일이 여러 개입니다(rel 로 주 파일 지정).", { index: i });
        const file = main.split("/").pop()!;
        const parts = mockMeshParts(file);
        const pidv = shapes[i].part_id;
        if (pidv == null && parts.length > 1) return err(422, "MESH_INPUT_PART_REQUIRED", "쉘 파트가 여러 개입니다 — 파트 ID 를 고르세요.", { index: i, parts });
        if (pidv != null && !parts.some((p) => p.id === pidv)) return err(422, "MESH_INPUT_PART_NOT_FOUND", `파트 ID ${pidv} 가 메시에 없습니다.`, { index: i, parts });
        this.ctx.markUploadCompleted(String(shapes[i].upload_id));
        const files = meshes.filter((x) => x.startsWith("rad/")).map((x, k) => ({ rel: x, sha256: shaOfFile(x), size_mb: +(x === main ? 42.5 : 3.1 + k).toFixed(2) }));
        const size = files.reduce((a, x) => a + x.size_mb, 0);
        rows.push({ index: i, name: String(shapes[i].name).trim(), file_name: file, sha256: shaOfFile(file), size_mb: +size.toFixed(2), reference: !!shapes[i].reference, source: "mesh", part_id: pidv ?? parts[0].id, main_rel: main, files, parts });
        continue;
      }
      const steps = up.files.filter((x) => /\.(step|stp)$/i.test(x));
      const rel = shapes[i].rel;
      const f = rel ? steps.find((x) => x === rel) : steps.length === 1 ? steps[0] : undefined;
      if (!f) return err(422, "STEP_INVALID", rel ? `업로드에 STEP 파일 '${rel}' 이 없습니다.` : "업로드에 STEP 이 하나가 아닙니다(rel 지정).", { index: i });
      this.ctx.markUploadCompleted(String(shapes[i].upload_id));
      const file = f.split("/").pop()!;
      rows.push({ index: i, name: String(shapes[i].name).trim(), file_name: file, sha256: shaOfFile(file), size_mb: +(3.4 + 0.3 * i).toFixed(2), reference: !!shapes[i].reference });
    }
    const total = rows.reduce((a, x) => a + x.size_mb, 0);
    if (total > (st.compare?.total_max_mb ?? 1000)) return err(422, "SHAPES_TOO_LARGE", "STEP 합계 크기가 상한을 넘었습니다.");
    const first = sel[0]!;
    const warnings: DoeWarning[] = [];
    const out: DoeCheckOut = {
      ok: true,
      step: null,
      entries: sel.map((e) => ({ entry_id: e!.id, ok: true, reason: null })),
      shapes: rows,
      reference_source: nRef ? "step" : "case",
      size: null,
      props_default: { t: 1.2, E: 205000, nu: 0.3 },
      ...(cc?.mesh_mode ? { mesh_mode: (mode as DoeMeshMode | undefined) ?? cc.mesh_mode, remesh_available: !!cc.remesh_available } : {}),
      warnings,
    };
    if (!nRef) {
      out.base = { entry_id: first.id, case_id: first.case_id, case_title: first.case_title ?? null, part_title: "chassis_rear", n_nodes: 221_380, n_elems: 218_400, topo_sha256: first.topo_sha256 ?? "" };
      warnings.push(COMPARE_REF_CASE_MESH);
    }
    if (new Set(rows.map((x) => x.sha256)).size < rows.length) warnings.push({ code: "SHAPE_DUPLICATE_FILE", message: "같은 STEP 파일이 두 번 이상 들어 있습니다" });
    return ok(out);
  }

  handle(method: string, path: string, query: URLSearchParams, b: Record<string, unknown>): MockResponse | null {
    if (!path.startsWith("/doe/")) return null;
    let r: RegExpMatchArray | null;
    if (method === "GET" && path === "/doe/settings") return ok(this.settings);
    if (method === "POST" && path === "/doe/check-inputs") return this.check(b);
    if (method === "POST" && path === "/doe/studies") {
      const c = this.check(b);
      if (c.status !== 200) return c;
      const co = c.body as DoeCheckOut;
      if (b.scenario === "compare") {
        if (b.mesh_size_mm != null) return err(422, "INVALID_PARAMS", "형상 직접 비교는 메시 크기를 바꿀 수 없습니다(설정 고정).");
        const props = (b.props as DoeStudyOut["inputs"]["props"]) ?? co.props_default ?? null;
        if (props && !(props.t > 0 && props.E > 0 && props.nu >= 0 && props.nu < 0.5)) return err(422, "INVALID_PARAMS", "쉘 물성이 올바르지 않습니다(t>0, E>0, 0≤ν<0.5).");
        const req = b.shapes as CompareShapeIn[];
        const shapes = compareIds(req.map((x, i) => ({ ...x, file_name: co.shapes![i].file_name, sha256: co.shapes![i].sha256, part_id: co.shapes![i].part_id ?? x.part_id ?? null })));
        const id = this.id("doe");
        const title = String(b.title ?? "").trim();
        const rec: Rec = {
          out: {
            id,
            project_id: String(b.project_id),
            scenario: "compare",
            title: title || `형상 비교 ${shapes.length}개`,
            entry_ids: b.entry_ids as string[],
            inputs: {
              step: null,
              mesh: null,
              part_title: null,
              inch: typeof b.inch === "number" ? b.inch : null,
              props,
              mesh_size_mm: null,
              shapes,
              reference_source: co.reference_source ?? "step",
              // v0.16.0 적용 메시 방식(요청 없으면 설정값) — 메시 형상만이면 해당 없음이지만 값은 기록
              ...(co.mesh_mode ? { mesh_mode: co.mesh_mode, mesh_refine: b.mesh_refine === false ? false : true } : {}),
            },
            phase: "PREP",
            version: 1,
            prep: null,
            doe: null,
            created_by_name: this.ctx.me().display_name,
            created_at: this.ctx.now(),
          },
          jobIds: [],
          pending: null,
          cells: null,
          result: null,
          stepUpload: null,
        };
        rec.jobIds.push(this.ctx.newJob(rec.out.project_id, "DOE_PREP", { bead_doe_id: id }).id);
        this.recs.push(rec);
        return ok(this.studyOut(rec), 201);
      }
      if ((b.scenario === "same" || b.scenario === "select") && !co.ok) return err(422, "MODEL_MISMATCH", "다른 모델 ESL 이 있습니다 — 빼거나 '다른 모델' 시나리오로.");
      const title = String(b.title ?? "").trim();
      if (title.length > 200) return err(422, "INVALID_PARAMS", "제목은 200자 이하입니다.");
      const props = b.props as DoeStudyOut["inputs"]["props"];
      if ((b.scenario === "step" || b.select_base === "step") && props && !(props.t > 0 && props.E > 0 && props.nu >= 0 && props.nu < 0.5)) return err(422, "INVALID_PARAMS", "쉘 물성이 올바르지 않습니다(t>0, E>0, 0≤ν<0.5).");
      if (b.select_base === "step" && !props) return err(422, "INVALID_PARAMS", "쉘 물성이 필요합니다.");
      const id = this.id("doe");
      const rec: Rec = {
        out: {
          id,
          project_id: String(b.project_id),
          scenario: b.scenario as DoeScenario,
          title: title || (b.scenario === "select" ? (b.select_base === "step" ? `STEP 비드 선택 ${co.step?.file_name ?? ""}` : "비드 직접 선택") : `강성 평가 ${co.step?.file_name ?? ""}`),
          entry_ids: b.entry_ids as string[],
          inputs: {
            step: co.step ? { file_name: co.step.file_name, sha256: co.step.sha256 } : null,
            mesh: co.mesh ? { file_name: co.mesh.file_name, sha256: co.mesh.sha256 } : null,
            part_title: (b.part_title as string | null) ?? (b.scenario === "mesh" || b.select_base === "mesh" ? this.settings.part_title ?? null : co.base?.part_title ?? null),
            inch: typeof b.inch === "number" ? b.inch : null,
            props: props ?? null,
            mesh_size_mm: typeof b.mesh_size_mm === "number" ? b.mesh_size_mm : null,
            // v0.16.2 select: bead_source 항상, select_base 는 mesh 일 때만(AD-D-22)
            // v0.17.0 새 select 스터디 = schema 2(BG-D-35)
            ...(b.scenario === "select" ? { bead_source: (b.bead_source as "auto" | "manual" | undefined) ?? "manual", select_schema: 2 as const, ...(b.select_base === "mesh" ? { select_base: "mesh" as const } : {}) } : {}),
            // v0.18.0 ③ STEP 기준: select_base step + 메시 방식(④ 와 같은 값)
            ...(b.scenario === "select" && b.select_base === "step" ? { select_base: "step" as const, part_title: null, mesh_mode: co.mesh_mode ?? null, mesh_refine: b.mesh_refine === false ? false : true } : {}),
          },
          phase: "PREP",
          version: 1,
          prep: null,
          doe: null,
          created_by_name: this.ctx.me().display_name,
          created_at: this.ctx.now(),
        },
        jobIds: [],
        pending: null,
        cells: null,
        result: null,
        stepUpload: b.step_upload_id != null ? String(b.step_upload_id) : null,
      };
      const j = this.ctx.newJob(rec.out.project_id, "DOE_PREP", { bead_doe_id: id });
      rec.jobIds.push(j.id);
      this.recs.push(rec);
      return ok(this.studyOut(rec), 201);
    }
    if (method === "GET" && path === "/doe/studies") {
      const pid = query.get("project_id");
      return ok(this.recs.filter((x) => !pid || x.out.project_id === pid).map((x) => this.studyOut(x)).reverse());
    }
    if ((r = path.match(/^\/doe\/studies\/([^/]+)(\/.*)?$/))) {
      const rec = this.recs.find((x) => x.out.id === r![1]);
      if (!rec) return err(404, "DOE_NOT_FOUND", "강성 평가 스터디를 찾을 수 없습니다.");
      const sub = r[2] ?? "";
      const write = method !== "GET";
      if (write && !this.ctx.canRun(rec.out.project_id)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      this.sync(rec);
      const st = this.settings;
      if (method === "GET" && sub === "") return ok(this.studyOut(rec));
      if (rec.out.scenario === "select") {
        const sr = this.handleSelect(rec, method, sub, query, b);
        if (sr) return sr;
      } else if (/^\/(select\/|selection$)/.test(sub)) return err(409, "SCENARIO_UNSUPPORTED", "비드 직접 선택 스터디가 아닙니다.");
      // ④ 형상 비교: 비드·DOE·미리보기 경로 없음(SC-D-1)
      if (rec.out.scenario === "compare" && (/^\/(params|plan-view|matrix|preview)$/.test(sub) || /^\/(beads|preview\/thumb)\//.test(sub)))
        return err(409, "SCENARIO_UNSUPPORTED", "형상 직접 비교에서는 쓸 수 없습니다.");
      if (method === "GET" && sub === "/params") {
        if (rec.out.phase === "PREP" || !rec.out.prep) return err(409, "PREP_NOT_READY", "입력 준비가 끝나지 않았습니다.");
        const out: DoeParamsOut = { beads: BEADS, params: PARAMS, warnings: PARAM_WARNINGS };
        return ok(out);
      }
      if (method === "GET" && sub === "/plan-view") {
        if (rec.out.phase === "PREP" || !rec.out.prep) return err(409, "PREP_NOT_READY", "입력 준비가 끝나지 않았습니다.");
        return ok(makePlan(rec.out.scenario, rec.out.entry_ids));
      }
      if ((r = sub.match(/^\/beads\/([^/]+)\.png$/)) && method === "GET") return BEADS.some((x) => x.id === r![1]) ? { status: 200, body: thumbSvg(null, "NOMINAL") } : err(404, "NOT_FOUND", "비드 그림이 없습니다.");
      if (method === "POST" && (sub === "/matrix" || sub === "/preview")) {
        if (rec.out.phase === "PREP" || !rec.out.prep) return err(409, "PREP_NOT_READY", "입력 준비가 끝나지 않았습니다.");
        const spec = b.spec as DoeSpec | undefined;
        const ps = this.paramsOf(rec);
        const bad = specProblem(spec, st, ps);
        if (bad) return bad;
        const m = makeMatrix(spec!, ps);
        if (sub === "/matrix") return ok(m);
        if (b.version !== rec.out.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로 고친 뒤 다시 시도하세요");
        if (this.active(rec)) return err(409, "JOB_ACTIVE", "이 연구의 작업이 진행 중입니다.");
        if (rec.out.phase === "RUN" || rec.out.phase === "DONE") return err(409, "ALREADY_RUN", "이미 실행했습니다 — 복제해서 새 연구로.");
        rec.out.doe = { rev: (rec.out.doe?.rev ?? 0) + 1, spec: m.spec, matrix_sha256: m.matrix_sha256, n_designs: m.n_designs, preview: null };
        if (rec.out.scenario === "select") rec.pendingSel = rec.sel?.sha256 ?? null;
        rec.pending = m;
        rec.cells = null;
        rec.out.phase = "PREVIEW";
        rec.out.version += 1;
        const j = this.ctx.newJob(rec.out.project_id, "DOE_PREVIEW", { bead_doe_id: rec.out.id, rev: rec.out.doe.rev });
        rec.jobIds.push(j.id);
        return ok(this.studyOut(rec), 202);
      }
      if ((r = sub.match(/^\/preview\/thumb\/([^/]+)$/)) && method === "GET") {
        const did = decodeURIComponent(r[1]);
        if (did === "d000" && rec.out.doe?.preview) return { status: 200, body: thumbSvg(null, "NOMINAL") };
        const c = rec.cells?.find((x) => x.id === did);
        if (!c || !c.thumb) return err(404, "NOT_FOUND", "썸네일이 없습니다.");
        return { status: 200, body: thumbSvg(c.values, c.status) };
      }
      if (method === "POST" && sub === "/run" && rec.out.scenario === "compare") {
        if (b.solver != null && b.solver !== "linear") return err(422, "SOLVER_UNSUPPORTED", "솔버는 linear 만 지원합니다.");
        if (b.version !== rec.out.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로 고친 뒤 다시 시도하세요");
        if (this.active(rec)) return err(409, "JOB_ACTIVE", "이 연구의 작업이 진행 중입니다.");
        if (rec.out.phase === "RUN" || rec.out.phase === "DONE") return err(409, "ALREADY_RUN", "이미 실행했습니다 — 복제해서 새 연구로.");
        if (rec.out.phase !== "READY") return err(409, "PREP_NOT_READY", "입력 준비가 끝나지 않았습니다.");
        rec.out.phase = "RUN";
        rec.out.version += 1;
        rec.jobIds.push(this.ctx.newJob(rec.out.project_id, "DOE_RUN", { bead_doe_id: rec.out.id }).id);
        return ok(this.studyOut(rec), 202);
      }
      if (method === "POST" && sub === "/run") {
        if (b.solver != null && b.solver !== "linear") return err(422, "SOLVER_UNSUPPORTED", "솔버는 linear 만 지원합니다.");
        if (b.version !== rec.out.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로 고친 뒤 다시 시도하세요");
        if (this.active(rec)) return err(409, "JOB_ACTIVE", "이 연구의 작업이 진행 중입니다.");
        if (rec.out.phase === "RUN" || rec.out.phase === "DONE") return err(409, "ALREADY_RUN", "이미 실행했습니다 — 복제해서 새 연구로.");
        const pv = rec.out.doe?.preview;
        if (!pv || pv.matrix_sha256 !== b.matrix_sha256 || rec.out.doe?.matrix_sha256 !== b.matrix_sha256) return err(409, "PREVIEW_STALE", "미리보기가 현재 DOE 설정과 다릅니다 — 미리보기를 다시 실행하세요.");
        rec.out.phase = "RUN";
        rec.out.version += 1;
        const j = this.ctx.newJob(rec.out.project_id, "DOE_RUN", { bead_doe_id: rec.out.id });
        rec.jobIds.push(j.id);
        return ok(this.studyOut(rec), 202);
      }
      if (method === "POST" && sub === "/clone") {
        const id = this.id("doe");
        const n: Rec = { out: { ...rec.out, id, title: String(b.title ?? `${rec.out.title} (복제)`), phase: "PREP", version: 1, prep: null, doe: null, created_at: this.ctx.now(), created_by_name: this.ctx.me().display_name }, jobIds: [], pending: null, cells: null, result: null, stepUpload: rec.stepUpload, sel: rec.sel ? { ...rec.sel, rev: 1 } : null };
        n.jobIds.push(this.ctx.newJob(n.out.project_id, "DOE_PREP", { bead_doe_id: id }).id);
        this.recs.push(n);
        return ok(this.studyOut(n), 201);
      }
      // v0.16.1 ④ 억제 목록(esl_select_relax.md §9 — mesh/defeature.json 그대로, 없으면 404)
      if ((r = sub.match(/^\/shapes\/([^/]+)\/defeature$/)) && method === "GET") {
        const sh = rec.out.prep?.shapes?.find((x) => x.id === r![1]);
        if (!sh || sh.mesh_method !== "defeature") return err(404, "NOT_FOUND", "억제 목록이 없습니다.");
        return ok(mockDefeatureList(sh.id));
      }
      if (method === "GET" && sub === "/results") {
        if (rec.out.phase !== "DONE" || !rec.result) return err(409, "RESULT_NOT_READY", "결과가 아직 없습니다.");
        return ok(rec.result);
      }
      if (method === "GET" && sub === "/results/per-esl") {
        if (rec.out.phase !== "DONE" || !rec.result) return err(409, "RESULT_NOT_READY", "결과가 아직 없습니다.");
        const want = (query.get("design") ?? "").split(",").filter(Boolean);
        const rows = rec.result.ranking.filter((x) => !want.length || want.includes(x.id));
        return ok({ esl: rec.result.esl ?? [], ratio_tol: rec.result.ratio_tol ?? null, designs: rows.map((x) => ({ id: x.id, name: x.shape?.name ?? null, per_esl: x.per_esl ?? [] })) });
      }
      if (method === "GET" && sub === "/files") {
        const files: DoeFileOut[] = [{ rel: "report.html", size: 512_331, downloadable: true }, { rel: "post/ranking.csv", size: 8_204, downloadable: true }, ...(rec.result?.best?.files ?? [])];
        return ok(files);
      }
      if (method === "GET" && (sub === "/download" || sub === "/bundle")) return rec.result ? { status: 200, body: sub === "/bundle" ? "PK mock zip\n" : "mock file\n" } : err(404, "NOT_READY", "결과가 아직 없습니다.");
      if (method === "GET" && sub === "/report") return rec.result ? { status: 200, body: "<html><body>mock DOE report</body></html>" } : err(404, "NOT_READY", "보고서가 아직 없습니다.");
      if ((r = sub.match(/^\/view3d\/([^/]+)\/manifest\.json$/)) && method === "GET") {
        const did = decodeURIComponent(r[1]);
        if (!rec.result?.view3d.includes(did)) return err(404, "NOT_FOUND", "3D 자료가 없습니다.");
        const m = mockView3d().manifest(`doe-${rec.out.id}-${did}`);
        const row = rec.result.ranking.find((x) => x.id === did);
        const ratio = row ? row.umax / rec.result.baseline.umax : 1;
        return ok({ ...m, ranges: { ...m.ranges, u_max: m.ranges.u_max * ratio }, geometry_url: `/doe/studies/${rec.out.id}/view3d/${did}/part.glb`, values_url: `/doe/studies/${rec.out.id}/view3d/${did}/values.bin` });
      }
      return err(404, "NOT_FOUND", `목 서버에 없는 경로: ${method} ${path}`);
    }
    return err(404, "NOT_FOUND", `목 서버에 없는 경로: ${method} ${path}`);
  }
}
