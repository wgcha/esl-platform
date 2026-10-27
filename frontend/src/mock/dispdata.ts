// 목 데이터: 변위 전 노드 분석(계약 esl_disp_primary.md §3.5·§7). 판 노드 120×60(data.ts) 위 합성 변위장 — 결정적(난수 없음).
// 변위 오차 r = e/U 는 ~1e-6 수준의 수치 오차 지도(3-2-1 정정 구속 때문에 지지 노드 근처가 약간 큼).
import type { ColorRangeRobust, DispFieldOut, DispLayer, DispSummary, DispTopRow } from "../api/types";
import { NX, NY, PLANE, N_NODES, nodeAB, nodeId } from "./data";

export const U_MM = 3.42; // Radioss 최대 변위 크기 U = max‖u_rel‖ (mm)
const R_MAX = 6.4e-6;

/** 결정적 의사 난수 0~1 */
function hash(k: number) {
  const x = Math.sin(k * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}

/** 유효숫자 2자리 올림(서버 esl.report.field.ceil2 와 같은 규칙) */
export function ceil2(x: number): number | null {
  if (!(x > 0) || !Number.isFinite(x)) return null;
  const e = Math.floor(Math.log10(x)) - 1;
  const m = Math.ceil(x / 10 ** e - 1e-9);
  return +(m * 10 ** e).toPrecision(12);
}

export function pctile(sorted: number[], q: number) {
  if (!sorted.length) return 0;
  const x = (sorted.length - 1) * q;
  const lo = Math.floor(x);
  const hi = Math.ceil(x);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (x - lo);
}

interface Nd {
  id: number;
  a: number;
  b: number;
  rel: number; // ‖d_rel‖ mm
  val: number; // ‖d_val‖ mm
  e: number; // mm
  r: number; // e/U
  sup: boolean;
}

export const SUPPORT_NODES = [nodeId(6, 6), nodeId(NX - 7, 6), nodeId(6, NY - 7)];

function build(): Nd[] {
  const raw: Nd[] = [];
  for (let id = 1; id <= N_NODES; id++) {
    const [a, b] = nodeAB(id);
    const g = (ca: number, cb: number, sa: number, sb: number) => Math.exp(-(((a - ca) / sa) ** 2) - ((b - cb) / sb) ** 2);
    const rel = U_MM * (0.04 + 0.96 * g(281, -84, 300, 210) + 0.0 * a);
    // log10 r ≈ −6.8 + 1.6·난수 + 0.7·(−240, 110 근처 응력 집중)
    const lr = -6.8 + 1.6 * hash(id) + 0.7 * g(-240, 110, 140, 90);
    const r = 10 ** lr;
    raw.push({ id, a, b, rel, val: rel * (1 + r), e: r * U_MM, r, sup: SUPPORT_NODES.includes(id) });
  }
  // 최대를 R_MAX 에 맞추고, 지지 노드는 평균보다 조금 크게
  const mx = Math.max(...raw.map((n) => n.r));
  for (const n of raw) {
    n.r = (n.r / mx) * R_MAX * (n.sup ? 0.55 : 1);
    n.e = n.r * U_MM;
    n.val = n.rel * (1 + n.r);
  }
  return raw;
}

const NODES = build();

export const R_VALUES = NODES.map((n) => n.r);
export const DISP_RMS = Math.sqrt(R_VALUES.reduce((s, r) => s + r * r, 0) / R_VALUES.length);
export const DISP_MAX = Math.max(...R_VALUES);
const MAX_NODE = NODES.reduce((m, n) => (n.r > m.r ? n : m), NODES[0]);

/** 최대 변위 오차 노드의 평면 좌표(단면 추천용) */
export const MAX_ERR_NODE = { id: MAX_NODE.id, a: MAX_NODE.a, b: MAX_NODE.b };

export function makeDispSummary(bins = 20, topN = 20): DispSummary {
  const sorted = [...R_VALUES].sort((x, y) => x - y);
  const pos = sorted.filter((v) => v > 0);
  const nZero = sorted.length - pos.length;
  const lo = Math.floor(Math.log10(pos[0]));
  const hi = Math.ceil(Math.log10(pos[pos.length - 1]));
  const edges = Array.from({ length: bins + 1 }, (_, k) => +(lo + ((hi - lo) * k) / bins).toFixed(6));
  const counts = new Array(bins).fill(0);
  for (const v of pos) counts[Math.min(bins - 1, Math.max(0, Math.floor(((Math.log10(v) - lo) / (hi - lo)) * bins)))] += 1;
  const top: DispTopRow[] = [...NODES]
    .sort((x, y) => y.r - x.r)
    .slice(0, topN)
    .map((n) => ({ node_id: n.id, r: n.r, e: n.e, u_rel_mag: +n.rel.toFixed(4), a: +n.a.toFixed(2), b: +n.b.toFixed(2), is_support: n.sup }));
  return {
    U: U_MM,
    n_nodes: N_NODES,
    n_support: SUPPORT_NODES.length,
    rms_rel: DISP_RMS,
    max_rel: DISP_MAX,
    max_node_id: MAX_NODE.id,
    p50: pctile(sorted, 0.5),
    p90: pctile(sorted, 0.9),
    p99: pctile(sorted, 0.99),
    max: DISP_MAX,
    hist: { edges_log10: edges, counts, n: pos.length, n_zero: nZero },
    top,
    support: NODES.filter((n) => n.sup).map((n) => ({ node_id: n.id, r: n.r, e: n.e })),
    plane: { origin: PLANE.origin, e1: PLANE.e1, e2: PLANE.e2 },
  };
}

function robust(layer: DispLayer): ColorRangeRobust {
  const vals = (layer === "err" ? NODES.map((n) => n.r) : [...NODES.map((n) => n.rel), ...NODES.map((n) => n.val)]).sort((x, y) => x - y);
  const raw = pctile(vals, 0.99);
  return { min: 0, max: ceil2(raw), basis: "p99", raw };
}

/** GET /validations/{id}/disp-field — err = e/U, rel = ‖d_rel‖, val = ‖d_val‖. 다운샘플은 stride(목) */
export function makeDispField(vid: string, layer: DispLayer, maxPoints = 20000): DispFieldOut {
  const stride = NODES.length > maxPoints ? Math.ceil(NODES.length / maxPoints) : 1;
  const pick = stride === 1 ? NODES : NODES.filter((n, k) => k % stride === 0 || n.sup);
  const val = (n: Nd) => (layer === "err" ? n.r : layer === "rel" ? n.rel : n.val);
  const all = (layer === "err" ? NODES.map((n) => n.r) : [...NODES.map((n) => n.rel), ...NODES.map((n) => n.val)]).sort((x, y) => x - y);
  return {
    validation_id: vid,
    layer,
    n_total: NODES.length,
    n_returned: pick.length,
    decimated: stride > 1,
    cell: stride > 1 ? [(1200 / (NX - 1)) * Math.sqrt(stride), (600 / (NY - 1)) * Math.sqrt(stride)] : null,
    plane: { origin: PLANE.origin, e1: PLANE.e1, e2: PLANE.e2 },
    color_range: { min: all[0], max: all[all.length - 1] },
    color_range_robust: robust(layer),
    U: U_MM,
    points: pick.map((n) => [n.id, +n.a.toFixed(2), +n.b.toFixed(2), val(n), n.sup]),
  };
}
