// 하중 화살표 순수 로직(계약 §5·§6.2): 슬라이더 단계 ↔ 모드·개수, 선형 길이 규칙, 장면에 넘길 사양.
import type { View3dCluster, View3dOut } from "../api/types";
import type { V3 } from "./pick";

export const ARROW_COLOR = "#d62728";
export const ARROW_SELECTED = "#ff7f0e";
export const CLUSTER_COLOR = "#a50f15";

/** 사용자 결정 2026-10-28: 100·50·20·10 노드 → 합력 5·4·3·2 (노드 모드 최소 10 = 임계) */
export const NODE_STAGES = [100, 50, 20, 10] as const;
export const CLUSTER_STAGES = [5, 4, 3, 2] as const;
export const N_STAGES = NODE_STAGES.length + CLUSTER_STAGES.length;

export type ArrowMode = { kind: "nodes"; n: number } | { kind: "cluster"; k: number };

/** 슬라이더 위치(0 = 100 노드) → 모드 */
export function stageMode(i: number): ArrowMode {
  const j = Math.max(0, Math.min(N_STAGES - 1, Math.round(i)));
  return j < NODE_STAGES.length ? { kind: "nodes", n: NODE_STAGES[j] } : { kind: "cluster", k: CLUSTER_STAGES[j - NODE_STAGES.length] };
}
export function stageIndex(m: ArrowMode): number {
  return m.kind === "nodes" ? NODE_STAGES.indexOf(m.n as (typeof NODE_STAGES)[number]) : NODE_STAGES.length + CLUSTER_STAGES.indexOf(m.k as (typeof CLUSTER_STAGES)[number]);
}
export function stageText(i: number): string {
  const m = stageMode(i);
  return m.kind === "nodes" ? `${m.n} 노드` : `군집 ${m.k}`;
}

type StageSource = Pick<View3dOut, "top" | "clusters">;

/** 단계 사용 가능 여부: 노드 단계는 상위 행이 충분할 때(첫 단계는 행이 있으면 항상), 군집 단계는 k_actual = k 일 때 */
export function stageEnabled(src: StageSource, i: number): boolean {
  const m = stageMode(i);
  if (m.kind === "nodes") return src.top.length > 0 && (src.top.length >= m.n || m.n === NODE_STAGES[0]);
  const c = src.clusters?.[String(m.k)];
  return !!c && c.k_actual === m.k && c.rows.length === m.k;
}

/** 사용 가능한 가장 가까운 단계(같으면 왼쪽). 하나도 없으면 -1 */
export function nearestEnabledStage(src: StageSource, i: number): number {
  for (let d = 0; d < N_STAGES; d++) {
    if (i - d >= 0 && stageEnabled(src, i - d)) return i - d;
    if (i + d < N_STAGES && stageEnabled(src, i + d)) return i + d;
  }
  return -1;
}

/** 노드 모드 표·화살표 행 수 = min(n, 상위 행 수) */
export function nodeCount(src: StageSource, n: number): number {
  return Math.min(n, src.top.length);
}

/** 길이 = L_max·|F|/F_ref, 최소 0.15·L_max (작은 화살표도 보이게) */
export const MIN_LEN_FRAC = 0.15;
export function arrowLength(mag: number, fref: number, lmax: number): number {
  const frac = fref > 0 ? mag / fref : 0;
  return lmax * Math.max(MIN_LEN_FRAC, Math.min(1, frac));
}

export interface ArrowSpec {
  /** 노드 모드 = rank, 군집 모드 = 라벨 */
  key: string;
  kind: "node" | "cluster";
  tail: V3;
  dir: V3;
  length: number;
  shaftLen: number;
  headLen: number;
  shaftRadius: number;
  headRadius: number;
  color: string;
  mag: number;
  vertex: number | null;
  label?: string;
}

export const unit = (v: ArrayLike<number>): V3 | null => {
  const m = Math.hypot(v[0], v[1], v[2]);
  return m > 0 ? [v[0] / m, v[1] / m, v[2] / m] : null;
};

/** 화살표 치수: L_max = 0.10 diag, 머리 = 0.25 길이(최대 0.04 diag), 축 반지름 0.008 diag, 군집은 굵기 2배 */
export function buildArrow(key: string, kind: ArrowSpec["kind"], tail: V3, f: ArrayLike<number>, mag: number, fref: number, diag: number, vertex: number | null, label?: string): ArrowSpec | null {
  const dir = unit(f);
  if (!dir) return null;
  const length = arrowLength(mag, fref, 0.1 * diag);
  const headLen = Math.min(0.25 * length, 0.04 * diag);
  const thick = kind === "cluster" ? 2 : 1;
  return {
    key,
    kind,
    tail,
    dir,
    length,
    headLen,
    shaftLen: length - headLen,
    shaftRadius: 0.008 * diag * thick,
    headRadius: 0.018 * diag * thick,
    color: kind === "cluster" ? CLUSTER_COLOR : ARROW_COLOR,
    mag,
    vertex,
    label,
  };
}

export function clusterOf(m: Pick<View3dOut, "clusters">, k: number): View3dCluster | null {
  return m.clusters?.[String(k)] ?? null;
}

/** 화살표 사양. u = 복원된 u_rel(길이 3n) 또는 null, kscale = 변형 배율(변형 형상 꺼짐이면 0) */
export function buildArrowSpecs(m: Pick<View3dOut, "top" | "clusters" | "bbox">, mode: ArrowMode, u: ArrayLike<number> | null, kscale: number): ArrowSpec[] {
  const diag = m.bbox.diag;
  const out: ArrowSpec[] = [];
  if (mode.kind === "nodes") {
    const rows = m.top.slice(0, mode.n);
    const fref = rows.reduce((a, r) => Math.max(a, r.mag), 0);
    for (const r of rows) {
      const d = u && kscale ? [u[r.vertex * 3] * kscale, u[r.vertex * 3 + 1] * kscale, u[r.vertex * 3 + 2] * kscale] : [0, 0, 0];
      const a = buildArrow(String(r.rank), "node", [r.x + d[0], r.y + d[1], r.z + d[2]], [r.fx, r.fy, r.fz], r.mag, fref, diag, r.vertex);
      if (a) out.push(a);
    }
    return out;
  }
  const c = clusterOf(m, mode.k);
  if (!c) return out;
  const fref = c.rows.reduce((a, r) => Math.max(a, r.r_mag), 0);
  for (const r of c.rows) {
    const du = r.u_center && kscale ? r.u_center : [0, 0, 0];
    const kk = r.u_center && kscale ? kscale : 0;
    const a = buildArrow(r.label, "cluster", [r.center[0] + kk * du[0], r.center[1] + kk * du[1], r.center[2] + kk * du[2]], r.r, r.r_mag, fref, diag, null, `${r.label} ${fmtN(r.r_mag)} N`);
    if (a) out.push(a);
  }
  return out;
}

function fmtN(v: number): string {
  const a = Math.abs(v);
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  return v.toFixed(2);
}
