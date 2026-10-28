// 변형 형상(계약 §8): 위치 = base + k·û. ⑤ SectionChart 와 같은 표기·동작(슬라이더 지수 0~4, 0.01 단위, "실제 크기(×1)").
import { f3 } from "../lib/colormap";

export const EXP_MIN = 0;
export const EXP_MAX = 4;
export const EXP_STEP = 0.01;

/** 기본 k = 10^round(log10(clamp(0.05·diag/u_max, 1, 1e4)), 2). 변위가 0 이면 1 */
export function defaultScaleExp(diag: number, umax: number): number {
  const k0 = !(umax > 0) || !(diag > 0) ? 1 : Math.min(Math.max((0.05 * diag) / umax, 1), 1e4);
  return Math.round(Math.log10(k0) * 100) / 100;
}
export const scaleFromExp = (e: number): number => Math.pow(10, Math.max(EXP_MIN, Math.min(EXP_MAX, e)));
export const defaultScale = (diag: number, umax: number): number => scaleFromExp(defaultScaleExp(diag, umax));

/** "변형 확대 배율 ×{k} (실제 최대 {u_max} mm)" */
export function scaleLabel(k: number, umax: number): string {
  return `변형 확대 배율 ×${f3(k)} (실제 최대 ${umax > 0 ? f3(umax) : "–"} mm)`;
}

/** out = base + k·u (길이 3n). 30만 정점 ≤ 30 ms 목표 — 단순 루프 */
export function applyDeform(base: ArrayLike<number>, u: ArrayLike<number> | null, k: number, out: Float32Array): Float32Array {
  const m = out.length;
  if (!u || k === 0) {
    for (let i = 0; i < m; i++) out[i] = base[i];
    return out;
  }
  for (let i = 0; i < m; i++) out[i] = base[i] + k * u[i];
  return out;
}

/** 정점 하나의 (변형) 위치 */
export function pointAt(base: ArrayLike<number>, u: ArrayLike<number> | null, vertex: number, k: number): [number, number, number] {
  const i = vertex * 3;
  if (!u) return [base[i], base[i + 1], base[i + 2]];
  return [base[i] + k * u[i], base[i + 1] + k * u[i + 1], base[i + 2] + k * u[i + 2]];
}
