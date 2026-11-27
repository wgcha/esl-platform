// 색표 보조(v0.25.1 §5.5): 정규화·띠 위치·휘도·정점 색 채우기. 색 정점은 여기 없다 — lib/colormap.ts 가 자원(resources/colormaps.json)에서만 읽는다.
import { LUT_SIZE, buildLut, mapFor, specialLinear, srgbToLinear } from "../lib/colormap";
import type { RGB } from "../lib/colormap";

export { LUT_SIZE, srgbToLinear };
/** @deprecated shim — F1c(BeadSelectCard) 병합 때 삭제. lib/colormap.ts 의 deprecated 블록과 같이 지운다 */
export { DIVERGING_GRADIENT } from "../lib/colormap";

/** 값 → 0~1 (범위 밖은 끝색). 범위가 퇴화(max ≤ min)면 0. 비유한 값은 NaN */
export function normalize(v: number, min: number, max: number): number {
  if (!Number.isFinite(v)) return NaN;
  if (!(max > min)) return 0;
  return Math.max(0, Math.min(1, (v - min) / (max - min)));
}

/** v0.24.6 색 위치 t(0~1): L = 0 이면 normalize 와 같음(연속). L > 0 이면 구간 중앙값으로 계단(셰이더 gpuColor 와 같은 규칙).
 *  퇴화 범위(max ≤ min) = 0, 비유한 값 = NaN */
export function bandT(v: number, min: number, max: number, levels: number): number {
  const t = normalize(v, min, max);
  if (Number.isNaN(t) || !(levels > 0) || !(max > min)) return t;
  return (Math.min(Math.floor(t * levels), levels - 1) + 0.5) / levels;
}

/** 정점 색 채우기(선형 공간, 길이 3n) — CPU 경로(옛 장면 mock·시험용). src 가 있으면 LOD: 정점 i 의 값 = values[src[i]]. lut = 선형 색표(기본 seq 역할) */
export function fillVertexColors(values: ArrayLike<number>, min: number, max: number, out: Float32Array, src?: ArrayLike<number> | null, lut: Float32Array = defaultLut()): Float32Array {
  const nan = specialLinear("nan");
  const n = src ? src.length : values.length;
  for (let i = 0; i < n; i++) {
    const t = normalize(values[src ? src[i] : i], min, max);
    if (Number.isNaN(t)) {
      out[i * 3] = nan[0];
      out[i * 3 + 1] = nan[1];
      out[i * 3 + 2] = nan[2];
    } else {
      const k = Math.round(t * (LUT_SIZE - 1)) * 3;
      out[i * 3] = lut[k];
      out[i * 3 + 1] = lut[k + 1];
      out[i * 3 + 2] = lut[k + 2];
    }
  }
  return out;
}
let _lut: Float32Array | null = null;
function defaultLut(): Float32Array {
  return (_lut ??= buildLut(mapFor("seq"), { linear: true }));
}

/** 상대 휘도(sRGB 입력) */
export function luminance(c: RGB): number {
  return 0.2126 * srgbToLinear(c[0]) + 0.7152 * srgbToLinear(c[1]) + 0.0722 * srgbToLinear(c[2]);
}
