// v0.9.0 비드 형상 DOE 목 API(계약 esl_bead_doe.md §10). MockServer.handle 이 /doe/* 를 여기로 넘긴다.
// 준비·미리보기·실행 작업(DOE_PREP·DOE_PREVIEW·DOE_RUN)은 목 서버 대기열로 돌고, 끝나면 GET 시점에 연구 상태를 채운다.
// 행렬·셀 상태·순위·민감도는 입력에서 결정적으로 만든다(같은 spec → 같은 sha·같은 결과).
import type {
  DoeBead, DoeCheckOut, DoeDesignStatus, DoeExcluded, DoeFileOut, DoeMatrixOut, DoeMethodSources, DoeParam, DoeParamsOut, DoePlanLink, DoePlanOut, DoePreviewCell, DoeRankRow,
  DoeResultOut, DoeScenario, DoeSettingsOut, DoeSpec, DoeStudyOut, DoeWarning, EntryOut, JobOut, JobType, Me, MeshCheckOut, XY,
} from "../api/types";
import { mockView3d } from "./view3dmock";

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
  version: "2026-10-29.1",
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
    scenarios: { same: true, mesh: true, step: true },
    max_entries: 50,
    max_designs: 200,
    doe: { methods: ["lhs", "halton", "fullfact"], default_method: "lhs", default_n: 30, seed: 1, levels_default: 3, levels_max: 9, default_types: ["D", "W"] },
    mesh: { size_auto: true, size_min_mm: 1, size_max_mm: 20 },
    boundary: { fastener_warn_mm: 10, load_warn_mm: 20, load_share_min: 0.2 },
    step_max_mb: 200,
    part_title: "chassis rear",
    method_sources: DOE_METHOD_SOURCES,
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
const PARAM_WARNINGS: DoeWarning[] = [
  { code: "BEAD_FIXED_OVERLAP", bead: "B5", message: "B5 비드가 체결 고정 영역과 겹쳐 기본 제외했습니다." },
  { code: "BEAD_NEAR_FIXED", bead: "B4", message: "B4 비드가 체결부에서 6.2 mm 떨어져 있습니다(넓히면 고정 침범 가능)." },
];

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

export function makeMatrix(spec: DoeSpec): DoeMatrixOut {
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
export function specProblem(spec: DoeSpec | undefined, st: DoeSettingsOut): MockResponse | null {
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
function scoreOf(values: Record<string, number>): number {
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

export function makeResult(spec: DoeSpec, cells: DoePreviewCell[], entryIds: string[], scenario: DoeScenario): DoeResultOut {
  const C_ref = 4.82e5;
  const base = { id: "d000" as const, score: 1, umax: 3.92, epsmax: 0.0026 };
  const excluded: DoeExcluded[] = [];
  const okRows: { id: string; values: Record<string, number>; score: number }[] = [];
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
    okRows.push({ id: c.id, values: c.values, score: scoreOf(c.values) });
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
  }));
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
    warnings,
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

// ---------------------------------------------------------------- 상태
interface Rec {
  out: Omit<DoeStudyOut, "job" | "result_ready">;
  jobIds: string[];
  /** 진행 중 미리보기의 행렬(끝나면 preview 로) */
  pending: DoeMatrixOut | null;
  cells: DoePreviewCell[] | null;
  result: DoeResultOut | null;
  stepUpload: string | null;
}

const STEPS_OF: Record<string, string[]> = {
  DOE_PREP: ["BD_INPUT", "BD_MESH0", "BD_GEOM", "BD_LOADS", "BD_PREP_REGISTER"],
  DOE_PREVIEW: ["BD_MATRIX", "BD_GRID", "BD_PREVIEW_REGISTER"],
  DOE_RUN: ["BD_BASELINE", "BD_DESIGNS", "BD_POST", "BD_REGISTER"],
};
function doneJob(id: string, projectId: string, studyId: string, jt: JobType, t0: string, t1: string): JobOut {
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
    steps: STEPS_OF[jt].map((k, i) => ({ step_no: i + 1, step_key: k, kind: k === "BD_GEOM" || k === "BD_GRID" || k === "BD_DESIGNS" ? "LOCAL" : "INTERNAL", core_stage: null, state: k === "BD_MESH0" ? "SKIPPED" : "SUCCEEDED", progress_pct: 100, exit_code: 0, failure_code: null, failure_message: null, started_at: t0, finished_at: t1 })),
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
    this.recs.push(a, b);
  }

  private previewOf(rev: number, m: DoeMatrixOut, cells: DoePreviewCell[]) {
    return {
      rev,
      matrix_sha256: m.matrix_sha256,
      ok: cells.filter((c) => c.status === "READY").length,
      skipped: {
        collision: cells.filter((c) => c.status === "SKIPPED_COLLISION").length,
        fixed: cells.filter((c) => c.status === "SKIPPED_FIXED").length,
        geom: cells.filter((c) => c.status === "SKIPPED_GEOM").length,
      },
      cells,
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
      r.cells = makeCells(r.pending);
      r.out.doe.preview = this.previewOf(r.out.doe.rev, r.pending, r.cells);
      r.pending = null;
      r.out.phase = "PREVIEW_READY";
      r.out.version += 1;
    }
    if (r.out.phase === "RUN" && j.job_type === "DOE_RUN" && r.out.doe && r.cells) {
      r.result = makeResult(r.out.doe.spec, r.cells, r.out.entry_ids, r.out.scenario);
      r.out.phase = "DONE";
      r.out.version += 1;
    }
  }

  private studyOut(r: Rec): DoeStudyOut {
    this.sync(r);
    return { ...r.out, job: this.job(r.jobIds[r.jobIds.length - 1]), result_ready: r.out.phase === "DONE" };
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
    if (!this.settings.enabled) return err(503, this.settings.reason ?? "DOE_DISABLED", "강성 평가 스터디를 쓸 수 없습니다.");
    const scenario = b.scenario as DoeScenario;
    if (!["same", "mesh", "step"].includes(scenario)) return err(422, "INVALID_PARAMS", "시나리오가 올바르지 않습니다.");
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

  handle(method: string, path: string, query: URLSearchParams, b: Record<string, unknown>): MockResponse | null {
    if (!path.startsWith("/doe/")) return null;
    let r: RegExpMatchArray | null;
    if (method === "GET" && path === "/doe/settings") return ok(this.settings);
    if (method === "POST" && path === "/doe/check-inputs") return this.check(b);
    if (method === "POST" && path === "/doe/studies") {
      const c = this.check(b);
      if (c.status !== 200) return c;
      const co = c.body as DoeCheckOut;
      if (b.scenario === "same" && !co.ok) return err(422, "MODEL_MISMATCH", "다른 모델 ESL 이 있습니다 — 빼거나 '다른 모델' 시나리오로.");
      const title = String(b.title ?? "").trim();
      if (title.length > 200) return err(422, "INVALID_PARAMS", "제목은 200자 이하입니다.");
      const props = b.props as DoeStudyOut["inputs"]["props"];
      if (b.scenario === "step" && props && !(props.t > 0 && props.E > 0 && props.nu >= 0 && props.nu < 0.5)) return err(422, "INVALID_PARAMS", "쉘 물성이 올바르지 않습니다(t>0, E>0, 0≤ν<0.5).");
      const id = this.id("doe");
      const rec: Rec = {
        out: {
          id,
          project_id: String(b.project_id),
          scenario: b.scenario as DoeScenario,
          title: title || `강성 평가 ${co.step.file_name}`,
          entry_ids: b.entry_ids as string[],
          inputs: {
            step: { file_name: co.step.file_name, sha256: co.step.sha256 },
            mesh: co.mesh ? { file_name: co.mesh.file_name, sha256: co.mesh.sha256 } : null,
            part_title: (b.part_title as string | null) ?? (b.scenario === "mesh" ? this.settings.part_title ?? null : co.base?.part_title ?? null),
            inch: typeof b.inch === "number" ? b.inch : null,
            props: props ?? null,
            mesh_size_mm: typeof b.mesh_size_mm === "number" ? b.mesh_size_mm : null,
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
        stepUpload: String(b.step_upload_id),
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
        const bad = specProblem(spec, st);
        if (bad) return bad;
        const m = makeMatrix(spec!);
        if (sub === "/matrix") return ok(m);
        if (b.version !== rec.out.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 바꿨습니다. 새로 고친 뒤 다시 시도하세요");
        if (this.active(rec)) return err(409, "JOB_ACTIVE", "이 연구의 작업이 진행 중입니다.");
        if (rec.out.phase === "RUN" || rec.out.phase === "DONE") return err(409, "ALREADY_RUN", "이미 실행했습니다 — 복제해서 새 연구로.");
        rec.out.doe = { rev: (rec.out.doe?.rev ?? 0) + 1, spec: m.spec, matrix_sha256: m.matrix_sha256, n_designs: m.n_designs, preview: null };
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
        const n: Rec = { out: { ...rec.out, id, title: String(b.title ?? `${rec.out.title} (복제)`), phase: "PREP", version: 1, prep: null, doe: null, created_at: this.ctx.now(), created_by_name: this.ctx.me().display_name }, jobIds: [], pending: null, cells: null, result: null, stepUpload: rec.stepUpload };
        n.jobIds.push(this.ctx.newJob(n.out.project_id, "DOE_PREP", { bead_doe_id: id }).id);
        this.recs.push(n);
        return ok(this.studyOut(n), 201);
      }
      if (method === "GET" && sub === "/results") {
        if (rec.out.phase !== "DONE" || !rec.result) return err(409, "RESULT_NOT_READY", "결과가 아직 없습니다.");
        return ok(rec.result);
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
