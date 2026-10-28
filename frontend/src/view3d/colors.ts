// 표면 색: ColorBrewer Blues 9단계(#f7fbff → #08306b) 선형 보간 256칸(계약 §6.1). 0 = 가장 옅음, 범위 위 = 가장 진함, NaN = 회색.
// three 정점 색은 선형 작업 공간이라 sRGB 표를 선형으로 바꾼 표(LUT_LINEAR)를 쓴다. CSS 레전드는 sRGB 정점을 그대로 쓴다.
import type { RGB } from "../lib/colormap";

export const BLUES9: RGB[] = [
  [247, 251, 255], [222, 235, 247], [198, 219, 239], [158, 202, 225], [107, 174, 214], [66, 146, 198], [33, 113, 181], [8, 81, 156], [8, 48, 107],
];
export const LUT_SIZE = 256;
/** 계산 불가(NaN) 회색(sRGB) */
export const NAN_RGB: RGB = [154, 161, 171];

export function bluesSrgb(t: number): RGB {
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0)) * (BLUES9.length - 1);
  const i = Math.min(Math.floor(x), BLUES9.length - 2);
  const f = x - i;
  const a = BLUES9[i];
  const b = BLUES9[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

export const srgbToLinear = (c8: number): number => {
  const c = c8 / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
};

function buildLut(linear: boolean): Float32Array {
  const lut = new Float32Array(LUT_SIZE * 3);
  for (let k = 0; k < LUT_SIZE; k++) {
    const c = bluesSrgb(k / (LUT_SIZE - 1));
    for (let j = 0; j < 3; j++) lut[k * 3 + j] = linear ? srgbToLinear(c[j]) : c[j] / 255;
  }
  return lut;
}
export const LUT_SRGB = buildLut(false);
export const LUT_LINEAR = buildLut(true);
export const NAN_LINEAR: [number, number, number] = [srgbToLinear(NAN_RGB[0]), srgbToLinear(NAN_RGB[1]), srgbToLinear(NAN_RGB[2])];

/** 값 → 0~1 (범위 밖은 끝색). 범위가 퇴화(max ≤ min)면 0. 비유한 값은 NaN */
export function normalize(v: number, min: number, max: number): number {
  if (!Number.isFinite(v)) return NaN;
  if (!(max > min)) return 0;
  return Math.max(0, Math.min(1, (v - min) / (max - min)));
}

/** 정점 색 채우기(선형 공간, 길이 3n). src 가 있으면 LOD: 정점 i 의 값 = values[src[i]] */
export function fillVertexColors(values: ArrayLike<number>, min: number, max: number, out: Float32Array, src?: ArrayLike<number> | null): Float32Array {
  const n = src ? src.length : values.length;
  for (let i = 0; i < n; i++) {
    const t = normalize(values[src ? src[i] : i], min, max);
    if (Number.isNaN(t)) {
      out[i * 3] = NAN_LINEAR[0];
      out[i * 3 + 1] = NAN_LINEAR[1];
      out[i * 3 + 2] = NAN_LINEAR[2];
    } else {
      const k = Math.round(t * (LUT_SIZE - 1)) * 3;
      out[i * 3] = LUT_LINEAR[k];
      out[i * 3 + 1] = LUT_LINEAR[k + 1];
      out[i * 3 + 2] = LUT_LINEAR[k + 2];
    }
  }
  return out;
}

/** 상대 휘도(sRGB 입력) — 시험: 값이 커질수록 어두워진다 */
export function luminance(c: RGB): number {
  return 0.2126 * srgbToLinear(c[0]) + 0.7152 * srgbToLinear(c[1]) + 0.0722 * srgbToLinear(c[2]);
}

/** ColorLegend 의 CSS 띠 */
export const BLUES_GRADIENT = `linear-gradient(90deg, ${BLUES9.map((x, i) => `rgb(${x.join(",")}) ${Math.round((100 * i) / (BLUES9.length - 1))}%`).join(", ")})`;
