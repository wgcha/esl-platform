// P2 목 데이터: 전 요소 비교(겹쳐보기·단면선)·라이브러리 항목·종합분석. 결정적(난수 없음).
// 판 요소 격자 100×50(12 mm) 위 합성 변형률 장. 요약(분위수·히스토그램)은 코어 summarize 와 같은 규칙으로 계산한다.
import type {
  AnalysisCase, AnalysisFileOut, AnalysisLoadCase, AnalysisOut, AnalysisResult, EntryOut, FieldLayer, FieldOut, FieldPoint, FieldRow,
  FieldSummary, SectionAxis, SectionOut,
} from "../api/types";
import { PLANE, TSTAR_METRICS } from "./data";

const NXE = 100;
const NYE = 50;
const LX = 1200;
const LY = 600;
const MIN_REL = 0.1;
export const FIELD_CRITERIA = { max_err_pct_max: 10, p90_err_max: 20 };

export const REASON_TEXT: Record<string, string> = {
  OK: "비교 대상(t* 에서 상승 중, ε_rad ≥ min_rel·max)",
  HOLD: "t* 에서 상승 중이 아님 — Max_Strain 이 이전 최대값을 유지(hold) 중이라 순간값이 아님",
  LOW: "상승 중이지만 ε_rad < min_rel·max ε_rad (작은 변형률 — 상대오차가 의미 없음)",
  EXCLUDED: "tstar.exclude_elem_ids 로 제외",
  NO_PREV: "직전 프레임 값이 없어 상승 여부를 알 수 없음(예전 TCL 출력)",
};

interface Elem {
  id: number;
  a: number;
  b: number;
  rad: number;
  esl: number;
  rel: number;
  reason: string;
}

/** 전역 좌표 → PCA 평면 (a, b) */
function project(p: number[]): [number, number] {
  const d = p.map((v, k) => v - PLANE.origin[k]);
  const dot = (e: number[]) => d[0] * e[0] + d[1] * e[1] + d[2] * e[2];
  return [dot(PLANE.e1), dot(PLANE.e2)];
}

function build(): Elem[] {
  const out: Elem[] = [];
  const hot = TSTAR_METRICS.max_strain.hotspots.map((h) => ({ id: h.elem_id, ab: project(h.centroid!) }));
  const cellOf = (a: number, b: number) => {
    const i = Math.min(NXE - 1, Math.max(0, Math.floor(((a + LX / 2) / LX) * NXE)));
    const j = Math.min(NYE - 1, Math.max(0, Math.floor(((b + LY / 2) / LY) * NYE)));
    return j * NXE + i;
  };
  // hotspot 요소 id 를 가장 가까운 칸에 심는다(겹치면 오른쪽 이웃 칸)
  const special = new Map<number, number>();
  for (const h of hot) {
    let k = cellOf(h.ab[0], h.ab[1]);
    while (special.has(k)) k += 1;
    special.set(k, h.id);
  }
  for (let j = 0; j < NYE; j++)
    for (let i = 0; i < NXE; i++) {
      const a = -LX / 2 + (i + 0.5) * (LX / NXE);
      const b = -LY / 2 + (j + 0.5) * (LY / NYE);
      const g = (ca: number, cb: number, sa: number, sb: number) => Math.exp(-(((a - ca) / sa) ** 2) - ((b - cb) / sb) ** 2);
      const rad = 0.003 + 0.136 * g(281, -84, 150, 110) + 0.05 * g(170, 41, 70, 60) + 0.045 * g(-210, 230, 170, 90) + 0.03 * g(-420, -200, 120, 120);
      // 오차: 최대변형률 근처 과소(-12%), 가장자리 쪽 과대, 완만한 물결
      const rel = -0.124 * g(281, -84, 90, 70) + 0.06 * Math.sin(a / 140) * Math.cos(b / 110) + 0.025 * (b / LY);
      const hold = a < -470 || (a > 420 && b > 120) || ((a + 210) ** 2 / 160 ** 2 + (b - 230) ** 2 / 80 ** 2 < 1 && a < -250);
      const k = j * NXE + i;
      const id = special.get(k) ?? 200001 + k;
      // hotspot 1위 요소 = 최대변형률 요소(검증 hotspot 표와 같은 값: ε_rad 0.1418, 오차 −12.4%)
      const top = id === hot[0].id;
      const r0 = top ? 0.1418 : rad;
      const e0 = top ? -0.124 : rel;
      out.push({ id, a, b, rad: r0, esl: r0 * (1 + e0), rel: e0, reason: hold ? "HOLD" : "OK" });
    }
  const max = Math.max(...out.filter((e) => e.reason === "OK").map((e) => e.rad));
  for (const e of out) if (e.reason === "OK" && e.rad < MIN_REL * max) e.reason = "LOW";
  // 경계 열 일부 = 예전 TCL 출력(직전 프레임 없음)
  for (const e of out) if (e.b > LY / 2 - 12 && e.a > 0 && e.a < 120) e.reason = "NO_PREV";
  return out;
}

const ELEMS = build();
const r4 = (v: number) => +v.toPrecision(5);

function pctile(sorted: number[], q: number) {
  if (!sorted.length) return 0;
  const x = (sorted.length - 1) * q;
  const lo = Math.floor(x);
  const hi = Math.ceil(x);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (x - lo);
}

function niceCeil(x: number) {
  if (!(x > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(x));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= x * (1 - 1e-12)) return m * p;
  return 10 * p;
}

function row(e: Elem): FieldRow {
  return { elem_id: e.id, eps_rad: r4(e.rad), eps_esl: r4(e.esl), err_pct: r4(100 * e.rel), valid: e.reason === "OK", reason: e.reason, xi: e.a, eta: e.b };
}

export function makeFieldSummary(): FieldSummary {
  const valid = ELEMS.filter((e) => e.reason === "OK");
  const rising = ELEMS.filter((e) => e.reason === "OK" || e.reason === "LOW");
  const km = rising.reduce((m, e) => (e.rad > m.rad ? e : m), rising[0]);
  const jm = ELEMS.reduce((m, e) => (e.esl > m.esl ? e : m), ELEMS[0]);
  const abs = valid.map((e) => Math.abs(100 * e.rel)).sort((x, y) => x - y);
  const signed = valid.map((e) => 100 * e.rel);
  const R = Math.max(1, niceCeil(pctile(abs, 0.99)));
  const bins = 20;
  const edges = Array.from({ length: bins + 1 }, (_, k) => -R + (2 * R * k) / bins);
  const counts = new Array(bins).fill(0);
  for (const v of signed) counts[Math.min(bins - 1, Math.max(0, Math.floor(((Math.max(-R, Math.min(R, v)) + R) / (2 * R)) * bins)))] += 1;
  const cnt = (r: string) => ELEMS.filter((e) => e.reason === r).length;
  return {
    n_elems: ELEMS.length,
    n_rising: rising.length,
    n_valid: valid.length,
    n_ok: cnt("OK"),
    n_hold: cnt("HOLD"),
    n_low: cnt("LOW"),
    n_excluded: 0,
    n_no_prev: cnt("NO_PREV"),
    max: {
      elem_id: km.id,
      eps_rad: r4(km.rad),
      eps_esl: r4(km.esl),
      err_pct: r4(100 * km.rel),
      abs_err_pct: r4(Math.abs(100 * km.rel)),
      eps_esl_max: r4(jm.esl),
      eps_esl_max_elem_id: jm.id,
      peak_err_pct: r4((100 * (jm.esl - km.rad)) / km.rad),
      xi: km.a,
      eta: km.b,
      esl_max_xi: jm.a,
      esl_max_eta: jm.b,
    },
    abs_err_pct: {
      mean: r4(abs.reduce((s, v) => s + v, 0) / abs.length),
      p50: r4(pctile(abs, 0.5)),
      p90: r4(pctile(abs, 0.9)),
      p95: r4(pctile(abs, 0.95)),
      max: r4(abs[abs.length - 1]),
    },
    frac_within: Object.fromEntries([5, 10, 20].map((t) => [String(t), r4(abs.filter((v) => v <= t).length / abs.length)])),
    top: [...valid].sort((x, y) => y.rad - x.rad).slice(0, 20).map(row),
    worst: [...valid].sort((x, y) => Math.abs(y.rel) - Math.abs(x.rel)).slice(0, 20).map(row),
    hist: { edges, counts, range_pct: R, n: signed.length, n_clipped: signed.filter((v) => Math.abs(v) > R).length },
    criteria: FIELD_CRITERIA,
    min_rel: MIN_REL,
    prev_source: "strain_frames",
    reason_text: REASON_TEXT,
    note: "F_eq 는 u_rel(강체 제거 변위장)을 선형 탄성 모델에서 재현하는 하중이므로, 변형률(운동학량)은 요소 정식화·회전 자유도 차이만큼만 어긋나고, 응력은 소성 영역에서 탄성 과대평가된다.",
  };
}

/** GET /validations/{id}/field — 백엔드(services/results.field)와 같은 규칙:
 *  rad·esl 값은 사유와 무관하게 그대로(회색 판단은 사유로), err 는 valid 아니면 null. 색 범위 rad·esl = 둘 합친 유한값 [min,max]. */
export function makeField(vid: string, layer: FieldLayer, maxPoints = 20000): FieldOut {
  const stride = ELEMS.length > maxPoints ? Math.ceil(ELEMS.length / maxPoints) : 1;
  const pick = stride === 1 ? ELEMS : ELEMS.filter((_, k) => k % stride === 0);
  const s = makeFieldSummary();
  const points: FieldPoint[] = pick.map((e) => {
    const v = layer === "rad" ? e.rad : layer === "esl" ? e.esl : e.reason === "OK" ? 100 * e.rel : null;
    return [e.id, +e.a.toFixed(2), +e.b.toFixed(2), v === null ? null : r4(v), e.reason];
  });
  const all = ELEMS.flatMap((e) => [e.rad, e.esl]);
  const R = niceCeil(s.abs_err_pct ? pctile(ELEMS.filter((e) => e.reason === "OK").map((e) => Math.abs(100 * e.rel)).sort((x, y) => x - y), 0.99) : 1);
  return {
    validation_id: vid,
    layer,
    n_total: ELEMS.length,
    n_returned: points.length,
    decimated: stride > 1,
    cell: stride > 1 ? [(LX / NXE) * Math.sqrt(stride), (LY / NYE) * Math.sqrt(stride)] : null,
    plane: { origin: PLANE.origin, e1: PLANE.e1, e2: PLANE.e2 },
    color_range: layer === "err" ? { min: -R, max: R } : { min: r4(Math.min(...all)), max: r4(Math.max(...all)) },
    points,
  };
}

/** GET /validations/{id}/section: ξ(또는 η) = at 고정 단면의 면외 좌표·변위(mm) */
export function makeSection(vid: string, axis: SectionAxis, at = 0.5): SectionOut {
  const n = axis === "xi" ? NYE : NXE;
  const L = axis === "xi" ? LY : LX;
  const s: number[] = [];
  const w0: number[] = [];
  const wr: number[] = [];
  const we: number[] = [];
  for (let k = 0; k < n; k++) {
    const x = -L / 2 + (k + 0.5) * (L / n);
    s.push(+x.toFixed(2));
    w0.push(+(6 * Math.cos((Math.PI * x) / L) - 4).toFixed(4));
    const c = axis === "xi" ? -84 : 281;
    const bump = -3.4 * Math.exp(-(((x - c) / (L * 0.22)) ** 2));
    wr.push(+(bump + 0.4 * Math.sin(x / 90)).toFixed(5));
    we.push(+(bump * 0.93 + 0.36 * Math.sin(x / 90) + 0.05).toFixed(5));
  }
  return { validation_id: vid, axis, at, band: 0.02, n_elems: n * 2, s, w0, w_rad: wr, w_esl: we };
}

// ---------------------------------------------------------------- 라이브러리 항목
const SCENES: [string, number, string, string, string, string, string, "PASS" | "FAIL", number | null, number, number | null][] = [
  // model, inch, scenario, seq, drop_type, scene_no, orient, verdict, max_err, p90, product_mass
  ["75QN80H", 75, "CUMULATIVE", "17", "Corner", "10", "146", "PASS", 6.2, 9.8, 38.5],
  ["75QN80H", 75, "CUMULATIVE", "18", "Edge", "11", "14", "PASS", 4.1, 7.3, 38.5],
  ["75QN80H", 75, "SINGLE", "03", "Face", "03", "3", "PASS", 2.8, 5.0, 38.5],
  ["65QN80H", 65, "SINGLE", "05", "Corner", "05", "235", "PASS", 8.7, 14.2, 27.9],
  ["65QN80H", 65, "CUMULATIVE", "12", "Edge", "08", "26", "FAIL", 13.6, 18.9, 27.9],
  ["85QN80H", 85, "SINGLE", "02", "Face", "02", "1", "PASS", 3.3, 6.1, null],
  ["85QN80H", 85, "CUMULATIVE", "21", "Corner", "14", "245", "PASS", 9.1, 16.4, null],
  ["65QN80H", 65, "SINGLE", "07", "Face", "07", "5", "PASS", 5.5, 8.8, 27.9],
];

export function makeEntries(projectId: string): EntryOut[] {
  return SCENES.map(([model, inch, scenario, seq, drop, sc, orient, verdict, mx, p90, mass], k) => {
    const raw = `F:/Hyper_work/VD_25y/${model}/${model}_v072_260511/${scenario}/${seq}_${drop}_Drop_Scene${sc}_${drop}${orient}_comp.h3d`;
    const at = new Date(Date.UTC(2026, 9, 10 + k, 2, 30)).toISOString();
    const reason = verdict === "FAIL" ? "최대변형률 오차 13.6% — 누적 소성 시나리오로 확인 후 확정" : null;
    return {
      id: `le-${k + 1}`,
      project_id: projectId,
      case_id: k === 0 ? "c-demo" : `c-lib-${k + 1}`,
      case_title: `${model} ${drop} ${orient}`,
      esl_run_id: k === 0 ? "run-0" : `run-lib-${k + 1}`,
      validation_id: `val-lib-${k + 1}`,
      status: k === 7 ? "RETIRED" : "ACTIVE",
      retired_by_id: k === 7 ? "u-power" : null,
      retired_at: k === 7 ? at : null,
      retire_reason: null,
      model: { name: model, inch, version: "v072", date: "2026-05-11", project: "VD_25y", product_mass: mass, part_mass: 4.2, part_title: "rear_cover" },
      scene: { project: "VD_25y", scenario, seq: Number(seq), drop_type: drop, drop_class: drop, round: null, scene_no: Number(sc), orient, suffix: null, variant: "comp", raw, warnings: [] },
      quality: {
        verdict,
        fail_reasons: verdict === "FAIL" ? ["FIELD_MAX_ERR"] : [],
        field_max_err_pct: mx,
        field_p90_err_pct: p90,
        hotspot1_rel_err: mx === null ? null : mx / 100,
        noise: { hotspot_strain_rel: 0.0011 + 0.0003 * k },
        confirmed_fail: reason ? { reason, by: "u-power", by_name: "김해석", at } : null,
      },
      tstar: { metric: "max_strain", frame_index: 70 + k, time: 0.07 + k * 0.001 },
      summary: { grid: { nx: 24, ny: 14 } },
      dir_rel: `_library/le-${k + 1}`,
      summary_rel: `_library/le-${k + 1}/summary.npz`,
      sha256: `9f2c${k}a7e1b3d4c5f6`,
      registered_by: "u-power",
      registered_by_name: "김해석",
      registered_at: at,
      updated_at: at,
      note: null,
      force_reason: reason,
      warnings: [],
      version: 1,
    };
  });
}

// ---------------------------------------------------------------- 종합분석
const GRID = { nx: 24, ny: 14 };

/** 셀 합력 포락(정규화 격자): 꼭지점 낙하 모서리 + 마운트 부근 */
function envMag(i: number, j: number) {
  const x = i / (GRID.nx - 1);
  const y = j / (GRID.ny - 1);
  const corner = Math.max(Math.exp(-((x ** 2 + y ** 2) / 0.04)), Math.exp(-(((1 - x) ** 2 + y ** 2) / 0.05)), 0.8 * Math.exp(-(((1 - x) ** 2 + (1 - y) ** 2) / 0.05)));
  const mount = 0.55 * Math.exp(-(((x - 0.5) ** 2) / 0.02 + ((y - 0.62) ** 2) / 0.01));
  return 4200 * (0.06 + corner + mount);
}

/** analysis_runs.result (워커 _analysis_summary 형식) */
export function makeAnalysisResult(entries: EntryOut[], target: EntryOut | null, nRep: number, worst: boolean, objective: string): AnalysisResult {
  const K = entries.length;
  const k = Math.max(1, Math.min(nRep, K));
  const labels = entries.map((_, i) => i % k);
  const cases: AnalysisCase[] = entries.map((e, i) => ({
    index: i,
    entry_id: e.id,
    product: e.model.name ?? null,
    inch: e.model.inch ?? null,
    drop_class: e.scene.drop_class ?? null,
    orient: e.scene.orient ?? null,
    scene: e.scene.scene_no ?? null,
    scenario: e.scene.scenario ?? null,
    verdict: e.quality.verdict ?? null,
    cluster: labels[i],
    is_medoid: i < k,
    is_worst: worst && i >= k && i < 2 * k,
    sum_abs_f: Math.round(2.31e6 * (1 - 0.07 * i)),
    scale_factor: 1,
    svd_coef: [Math.cos(i), Math.sin(i), 0.1 * i],
  }));
  const clusters = Array.from({ length: k }, (_, c) => {
    const mem = cases.filter((x) => x.cluster === c);
    return { id: c, size: mem.length, medoid_entry: entries[c].id, worst_entry: mem[mem.length - 1].entry_id, mean_dist: 0.12 + 0.03 * c, members: mem.map((x) => x.entry_id) };
  });
  const load_cases: AnalysisLoadCase[] = clusters.map((c) => ({ label: `REP${c.id + 1}`, role: "medoid", cluster: c.id, entry_id: c.medoid_entry, case_index: c.id }));
  if (worst)
    for (const c of clusters)
      if (c.worst_entry !== c.medoid_entry)
        load_cases.push({ label: `WORST${c.id + 1}`, role: "worst", cluster: c.id, entry_id: c.worst_entry, case_index: cases.find((x) => x.entry_id === c.worst_entry)!.index });
  let max = 0;
  let arg = [0, 0];
  for (let i = 0; i < GRID.nx; i++)
    for (let j = 0; j < GRID.ny; j++)
      if (envMag(i, j) > max) {
        max = envMag(i, j);
        arg = [i, j];
      }
  return {
    n_cases: K,
    grid: GRID,
    target: target ? { entry_id: target.id, model: { product: target.model.name, inch: target.model.inch } } : null,
    svd: { n_modes: Math.min(K, 4), threshold: 0.9, feature: target ? "cell" : "cell(entry grid)", cum_energy_at_r: 0.913, energy: [0.52, 0.21, 0.11, 0.073, 0.04] },
    load_cases,
    clusters,
    envelope: { max, argmax_cell: arg },
    mapping: target ? { n_self: 1, n_mapped: K - 1, conservation_rel_max: 2.1e-12 } : null,
    stats: null,
    cases,
    warnings: K < nRep ? [`항목 ${K}개 < n_representative ${nRep} — 대표 ${K}개`] : [],
    optdeck: target
      ? { deck: "esl_bead.fem", files: ["esl_bead.fem", "loads_REP.inc", "run_optistruct.bat", "README.txt"], objective, n_subcases: load_cases.length, n_design_elems: 182_340, n_nondesign_elems: 41_075, card_format: "free", reference_compliance: null }
      : null,
  };
}

export function envelopeCsv(): string {
  const rows = ["i,j,xi_c,eta_c,max_abs_f,case_index,entry_id,dir_xi,dir_eta,dir_n,n_target_nodes"];
  for (let i = 0; i < GRID.nx; i++)
    for (let j = 0; j < GRID.ny; j++)
      rows.push([i, j, ((i + 0.5) / GRID.nx).toFixed(6), ((j + 0.5) / GRID.ny).toFixed(6), envMag(i, j).toExponential(9), 0, "le-1", 0, 0, 1, 30].join(","));
  return rows.join("\n") + "\n";
}

export function makeAnalysisFiles(a: AnalysisOut): AnalysisFileOut[] {
  const files: [string, AnalysisFileOut["kind"], number][] = [
    ["report.html", "report", 1_204_331],
    ...(a.optdeck_rel
      ? ([
          ["opt/esl_bead.fem", "optdeck", 48_211_532],
          ["opt/loads_REP.inc", "optdeck", 6_220_410],
          ["opt/run_optistruct.bat", "optdeck", 612],
          ["opt/README.txt", "optdeck", 3_904],
        ] as [string, AnalysisFileOut["kind"], number][])
      : []),
    ["analysis.json", "analysis", 88_410],
    ["envelope.csv", "analysis", 41_220],
    ["representatives.csv", "analysis", 1_118],
  ];
  return files.map(([rel, kind, size]) => ({ rel, kind, size, path: `${a.folder_path}\\${rel.replace(/\//g, "\\")}`, downloadable: size <= 20 * 1024 * 1024 }));
}

export function reportHtml(title: string) {
  return `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>${title}</title></head><body><main><h1>${title}</h1><p>목 보고서(자체 완결 HTML).</p></main></body></html>`;
}
