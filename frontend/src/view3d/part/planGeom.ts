// v0.17.3 공통 평면도 좌표(esl_view_unify.md VU-D-3): 판 평면(a = ξ, b = η, mm) → SVG 좌표. PartPlan·KeepoutPlan 이 같이 쓴다.
// 여백·축 글자 위치는 v0.17.1 까지의 BoundaryPlan·SelectPlan·KeepoutPlan 과 같다(그림 크기·비율 그대로).
import type { DoePlanLink, DoeSettingsOut, PlanViewFrame, XY } from "../../api/types";

export interface PlanBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PlanGeom {
  /** 판 가로·세로(mm) */
  Lx: number;
  Hy: number;
  /** max(Lx, Hy) — 글자·점 크기 기준 */
  S: number;
  pad: number;
  /** 전체 viewBox(축 글자 포함) */
  vb: PlanBox;
  X: (a: number) => number;
  Y: (b: number) => number;
  poly: (pts: XY[]) => string;
}

export function planGeom(f: PlanViewFrame): PlanGeom {
  const [a0, a1] = f.a_range;
  const [b0, b1] = f.b_range;
  const Lx = a1 - a0;
  const Hy = b1 - b0;
  const S = Math.max(Lx, Hy) || 1;
  const pad = S * 0.035;
  const vb = { x: -pad, y: -pad * 0.6, w: Lx + pad * 1.6, h: Hy + pad * 1.9 };
  const X = (a: number) => a - a0;
  const Y = (b: number) => b1 - b;
  const poly = (pts: XY[]) => (pts.length ? `M${pts.map(([a, b]) => `${X(a).toFixed(1)},${Y(b).toFixed(1)}`).join("L")}Z` : "");
  return { Lx, Hy, S, pad, vb, X, Y, poly };
}

export const vbText = (b: PlanBox) => `${b.x} ${b.y} ${b.w} ${b.h}`;

/** 화면(client px) → viewBox 좌표(preserveAspectRatio xMidYMid meet). 크기를 모르면(jsdom) null */
export function clientToBox(rect: { left: number; top: number; width: number; height: number }, box: PlanBox, cx: number, cy: number): [number, number] | null {
  if (!(rect.width > 0 && rect.height > 0)) return null;
  const s = Math.min(rect.width / box.w, rect.height / box.h) || 1;
  const ox = rect.left + (rect.width - box.w * s) / 2;
  const oy = rect.top + (rect.height - box.h * s) / 2;
  return [(cx - ox) / s + box.x, (cy - oy) / s + box.y];
}

/** 확대·축소: 점 p(viewBox 좌표)를 고정하고 k 배(k < 1 = 확대). 전체보다 크게는 안 줄임, 1/40 보다 작게 안 키움 */
export function zoomBox(box: PlanBox, full: PlanBox, p: [number, number], k: number): PlanBox {
  const kk = Math.min(Math.max(k, full.w / 40 / box.w), full.w / box.w);
  const w = box.w * kk;
  const h = box.h * kk;
  return { x: p[0] - (p[0] - box.x) * kk, y: p[1] - (p[1] - box.y) * kk, w, h };
}

/** 점 묶음(viewBox 좌표)에 맞춘 상자(여백 8 %), 화면비는 full 과 같게 */
export function fitBox(pts: [number, number][], full: PlanBox): PlanBox | null {
  if (!pts.length) return null;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const [x, y] of pts) (x0 = Math.min(x0, x)), (x1 = Math.max(x1, x)), (y0 = Math.min(y0, y)), (y1 = Math.max(y1, y));
  const r = full.w / full.h;
  let w = Math.max(x1 - x0, full.w / 40) * 1.16;
  let h = Math.max(y1 - y0, full.h / 40) * 1.16;
  if (w / h > r) h = w / r;
  else w = h * r;
  return { x: (x0 + x1) / 2 - w / 2, y: (y0 + y1) / 2 - h / 2, w, h };
}

/** 폭 W 최소·최대 윤곽 = ring + e × (W − W_nom)/2 (브라우저 계산 — 표의 현재 범위 즉시 반영) */
export function offsetRing(ring: XY[], e: XY[], d: number): XY[] {
  return ring.map(([a, b], i) => [a + (e[i]?.[0] ?? 0) * d, b + (e[i]?.[1] ?? 0) * d]);
}

/** 경계 경고 기준(mm): 하중 = load_warn_mm, 그 밖 = fastener_warn_mm */
export function linkThreshold(l: DoePlanLink, st: DoeSettingsOut): number {
  return l.kind === "load" ? st.boundary.load_warn_mm : st.boundary.fastener_warn_mm;
}
