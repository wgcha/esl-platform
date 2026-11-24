// v0.24.6 최대·최소 위치 표식(esl_viewer_hv.md §2.3) — 순수 계산.
import type { LegendKind } from "../components/ColorLegend";

export interface Extreme {
  vertex: number;
  value: number;
}
export interface Extremes {
  max: Extreme | null;
  min: Extreme | null;
}

/** 유한값 중 최대·최소 정점. NaN·Inf 무시, 동률이면 작은 정점 번호 */
export function extremes(values: ArrayLike<number>): Extremes {
  let max: Extreme | null = null;
  let min: Extreme | null = null;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (!Number.isFinite(v)) continue;
    if (!max || v > max.value) max = { vertex: i, value: v };
    if (!min || v < min.value) min = { vertex: i, value: v };
  }
  return { max, min };
}

/** 표식 대상: 범례 종류가 zero(0 이상 크기 필드)면 최대만 — 0 노드가 많아 최소 위치가 무의미. 종류 열로 결정(이름 분기 없음) */
export function marksFor(values: ArrayLike<number>, kind: LegendKind): { which: "max" | "min"; vertex: number; value: number }[] {
  const e = extremes(values);
  const out: { which: "max" | "min"; vertex: number; value: number }[] = [];
  if (e.max) out.push({ which: "max", ...e.max });
  if (kind !== "zero" && e.min) out.push({ which: "min", ...e.min });
  return out;
}
