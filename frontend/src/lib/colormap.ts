// v0.25.1 색 지도 — TS 쪽 유일한 읽기 모듈(계약 esl_view3d_scene_legend.md §5.5·§5.8).
// 정점 원본 = resources/colormaps.json 한 곳(빌드에 포함). 호출부는 **역할**(seq·div·region)로 지도를 고르고 정점·지도 이름을 적지 않는다.
// 보간 규칙(파이썬 esl/io/colormaps.py 와 같은 식 — 반올림까지): s = t·(n−1)(t 는 [0,1] 로 자름, NaN = 0), i = min(floor(s), n−2), f = s − i,
// 채널 = floor(a + (b − a)·f + 0.5).
// 금지: three·api·React import, 색 정점 숫자 리터럴(맨 아래 @deprecated 블록은 F1c 병합 때 지운다).
import CM from "../../../resources/colormaps.json";

export type RGB = [number, number, number];
/** 호출부가 쓰는 이름. 지도 이름(rainbow·diverge·blues)은 자원 `roles` 가 정한다 */
export type ColorRole = "seq" | "div" | "region";
export type SpecialName = "nan" | "out" | "none";

export interface ColorMap {
  /** 자원의 지도 이름 */
  name: string;
  kind: "seq" | "div" | "class";
  stops: RGB[];
  center?: number;
  /** 자원의 256색 sha256(시험 V-0251-38) */
  check: string;
}

interface RawMap {
  kind: string;
  stops: number[][];
  center?: number;
  check: string;
}
interface RawResource {
  schema: string;
  interp: string;
  maps: Record<string, RawMap>;
  roles: Record<string, string>;
  special: Record<string, number[]>;
}

/** 자원 검사(계약 §5.8): 스키마·정점 수·정점 값·div 의 center. 틀리면 throw — 빌드 시험(V-0251-39)이 잡는다 */
export function validateColormaps(raw: unknown): RawResource {
  const r = raw as RawResource;
  if (!r || r.schema !== "esl/colormaps/1") throw new Error("colormaps.json: 알 수 없는 schema");
  for (const [name, m] of Object.entries(r.maps ?? {})) {
    if (!Array.isArray(m.stops) || m.stops.length < 2) throw new Error(`colormaps.json: ${name} 정점이 2개 미만`);
    for (const s of m.stops) {
      if (!Array.isArray(s) || s.length !== 3 || s.some((c) => !Number.isInteger(c) || c < 0 || c > 255)) throw new Error(`colormaps.json: ${name} 정점 형식 오류`);
    }
    if (m.kind === "div") {
      if (m.stops.length % 2 !== 1) throw new Error(`colormaps.json: ${name} (div) 정점 수가 홀수가 아님`);
      if (typeof m.center !== "number") throw new Error(`colormaps.json: ${name} (div) center 없음`);
      const ci = m.center * (m.stops.length - 1);
      if (Math.abs(ci - Math.round(ci)) > 1e-9) throw new Error(`colormaps.json: ${name} (div) center 에 정점이 없음`);
    }
  }
  for (const role of ["seq", "div", "region"]) {
    if (!r.roles || !r.maps[r.roles[role]]) throw new Error(`colormaps.json: 역할 ${role} 의 지도가 없음`);
  }
  for (const s of ["nan", "out", "none"]) if (!r.special || !Array.isArray(r.special[s]) || r.special[s].length !== 3) throw new Error(`colormaps.json: special.${s} 없음`);
  return r;
}

const RES = validateColormaps(CM);

function toMap(name: string): ColorMap {
  const m = RES.maps[name];
  return { name, kind: m.kind as ColorMap["kind"], stops: m.stops as RGB[], center: m.center, check: m.check };
}
const MAPS: Record<string, ColorMap> = Object.fromEntries(Object.keys(RES.maps).map((n) => [n, toMap(n)]));

/** 역할(또는 지도 이름) → 지도 */
export function mapFor(role: ColorRole | string): ColorMap {
  const name = RES.roles[role] ?? role;
  const m = MAPS[name];
  if (!m) throw new Error(`알 수 없는 색 지도/역할: ${role}`);
  return m;
}

/** 정수 sRGB. t = 0~1(범위 밖은 자름, NaN = 0) */
export function srgb(map: ColorMap, t: number): RGB {
  const n = map.stops.length;
  const tt = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  const s = tt * (n - 1);
  const i = Math.min(Math.floor(s), n - 2);
  const f = s - i;
  const a = map.stops[i];
  const b = map.stops[i + 1];
  return [Math.floor(a[0] + (b[0] - a[0]) * f + 0.5), Math.floor(a[1] + (b[1] - a[1]) * f + 0.5), Math.floor(a[2] + (b[2] - a[2]) * f + 0.5)];
}

export function css(map: ColorMap, t: number): string {
  const c = srgb(map, t);
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export const srgbToLinear = (c8: number): number => {
  const c = c8 / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
};

export const LUT_SIZE = 256;

/** 256색 RGB uint8 표(768바이트) — t = k/(n−1). 자원 `check` 와 맞대는 값(V-0251-38) */
export function table(map: ColorMap, n = LUT_SIZE): Uint8Array {
  const out = new Uint8Array(n * 3);
  for (let k = 0; k < n; k++) {
    const c = srgb(map, n > 1 ? k / (n - 1) : 0);
    out[k * 3] = c[0];
    out[k * 3 + 1] = c[1];
    out[k * 3 + 2] = c[2];
  }
  return out;
}

/** 셰이더 색표 256칸(0~1 float). linear = three 작업 공간(sRGB → 선형). reversed = 높음 ↔ 낮음 */
export function buildLut(map: ColorMap, opts?: { reversed?: boolean; linear?: boolean }): Float32Array {
  const tb = table(map, LUT_SIZE);
  const lut = new Float32Array(LUT_SIZE * 3);
  for (let k = 0; k < LUT_SIZE; k++) {
    const src = opts?.reversed ? LUT_SIZE - 1 - k : k;
    for (let j = 0; j < 3; j++) lut[k * 3 + j] = opts?.linear ? srgbToLinear(tb[src * 3 + j]) : tb[src * 3 + j] / 255;
  }
  return lut;
}

/** 특수색 sRGB(nan = 계산 불가 · out = 범위 밖 · none = 영향 없음) */
export function special(name: SpecialName): RGB {
  const s = RES.special[name];
  return [s[0], s[1], s[2]];
}
export function specialCss(name: SpecialName): string {
  const s = special(name);
  return `rgb(${s[0]},${s[1]},${s[2]})`;
}
export function specialLinear(name: SpecialName): [number, number, number] {
  const s = special(name);
  return [srgbToLinear(s[0]), srgbToLinear(s[1]), srgbToLinear(s[2])];
}

/** CSS 띠(왼쪽 = 낮음 → 오른쪽 = 높음). levels > 0 이면 칸마다 중앙값 색의 계단(경계에서 계단, 정지점 2L 개). reversed = 색 순서 뒤집기 */
export function cssGradient(map: ColorMap, opts?: { reversed?: boolean; levels?: number; angle?: number }): string {
  const dir = `${opts?.angle ?? 90}deg`;
  const L = opts?.levels ?? 0;
  const col = (t: number) => css(map, opts?.reversed ? 1 - t : t);
  if (L > 0) {
    const stops: string[] = [];
    for (let i = 0; i < L; i++) {
      const c = col((i + 0.5) / L);
      const a = Math.round((100000 * i) / L) / 1000;
      const b = Math.round((100000 * (i + 1)) / L) / 1000;
      stops.push(`${c} ${a}%`, `${c} ${b}%`);
    }
    return `linear-gradient(${dir}, ${stops.join(", ")})`;
  }
  const n = map.stops.length;
  const stops = Array.from({ length: n }, (_, i) => `${col(i / (n - 1))} ${Math.round((100 * i) / (n - 1))}%`);
  return `linear-gradient(${dir}, ${stops.join(", ")})`;
}

/** 유효 숫자 4자리(보고서 f3 과 같은 규칙) */
export function f3(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  return a !== 0 && (a < 1e-3 || a >= 1e6) ? v.toExponential(3) : String(+v.toPrecision(4));
}

// ---------------------------------------------------------------- @deprecated — F1c(2D·썸네일) 병합 때 삭제(통합 시험 V-0251-37 이 0건을 확인)
// F1c 가 쓰는 파일(DispOverlay·FieldOverlay·library/common.tsx·BeadSelectCard)이 아직 아래를 import 한다. 새 코드는 쓰지 말 것 — mapFor·srgb·css·cssGradient 를 쓴다.
/** @deprecated mapFor("seq")·css 로 바꾼다(F1c) */
export const VIRIDIS: RGB[] = [
  [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142],
  [31, 158, 137], [53, 183, 121], [109, 205, 89], [180, 222, 44], [253, 231, 37],
];
/** @deprecated mapFor("div")·css 로 바꾼다(F1c) */
export const DIVERGING: RGB[] = [
  [49, 54, 149], [69, 117, 180], [145, 191, 219], [240, 228, 140], [252, 141, 89], [215, 48, 39], [165, 0, 38],
];
/** @deprecated specialCss("nan") 으로 바꾼다(F1c) */
export const NA_COLOR = "#9aa1ab";
/** @deprecated css(map, t) 로 바꾼다(F1c) */
export function lerp(c: RGB[], t: number): string {
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0)) * (c.length - 1);
  const i = Math.min(Math.floor(x), c.length - 2);
  const f = x - i;
  const a = c[i];
  const b = c[i + 1];
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(a[1] + (b[1] - a[1]) * f)},${Math.round(a[2] + (b[2] - a[2]) * f)})`;
}
/** @deprecated cssGradient(map) 으로 바꾼다(F1c) */
export function gradient(c: RGB[]): string {
  return `linear-gradient(90deg, ${c.map((x, i) => `rgb(${x.join(",")}) ${Math.round((100 * i) / (c.length - 1))}%`).join(", ")})`;
}
/** @deprecated BeadSelectCard HeightLegend(F1c)가 view3d/colors 를 통해 아직 쓴다 — 옛 띠(빨강 = 얕아짐). F1c 가 cssGradient(mapFor("div")) 로 바꾼 뒤 삭제 */
export const DIVERGING_GRADIENT = gradient([
  [103, 0, 31], [178, 24, 43], [214, 96, 77], [244, 165, 130], [253, 219, 199], [247, 247, 247], [209, 229, 240], [146, 197, 222], [67, 147, 195], [33, 102, 172], [5, 48, 97],
]);
