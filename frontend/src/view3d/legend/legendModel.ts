// v0.25.1 범례 모델(계약 esl_view3d_scene_legend.md §5.3~§5.5) — 순수 함수·표. three·api·React import 없음, 색 정점 없음.
import { f3, type ColorRole } from "../../lib/colormap";

export type Range = { min: number; max: number };
export type LegendScale = "linear" | "log";
export type NumFormat = "auto" | "fixed" | "exp";
export type OutMode = "clamp" | "gray";

/** 범례 모양 — 모든 3D 보기 공통 1벌(이 브라우저에 기억, 범위·로그는 기억하지 않음) */
export interface LegendSettings {
  /** 레벨 수 2~20 */
  levels: number;
  /** true = 연속(레벨 수 무시) */
  continuous: boolean;
  scale: LegendScale;
  format: NumFormat;
  /** 0~6 */
  digits: number;
  out: OutMode;
  reversed: boolean;
  minMark: boolean;
  upin: boolean;
  /** 로그 최소 보정: 최소 ≤ 0 이면 최소 = 최대/10^logDecades */
  logDecades: number;
}

/** 표시 기본값 — 이 표 한 곳(프런트 표시 기본은 서버 설정이 아님, D-0.25.1-VL-10) */
export const LEGEND_DEFAULTS: LegendSettings = {
  levels: 9,
  continuous: false,
  scale: "linear",
  format: "auto",
  digits: 3,
  out: "clamp",
  reversed: false,
  minMark: false,
  upin: true,
  logDecades: 3,
};
export const LEVELS_MIN = 2;
export const LEVELS_MAX = 20;
export const DIGITS_MAX = 6;

/** 기억·입력값을 범위 안으로 정리(형식이 틀린 필드는 기본값) */
export function normalizeLegend(o: Partial<Record<keyof LegendSettings, unknown>> | null | undefined): LegendSettings {
  const d = LEGEND_DEFAULTS;
  const src = o ?? {};
  const int = (v: unknown, lo: number, hi: number, dflt: number) => (typeof v === "number" && Number.isFinite(v) ? Math.max(lo, Math.min(hi, Math.round(v))) : dflt);
  const bool = (v: unknown, dflt: boolean) => (typeof v === "boolean" ? v : dflt);
  const pick = <T extends string>(v: unknown, ok: readonly T[], dflt: T): T => (ok.includes(v as T) ? (v as T) : dflt);
  return {
    levels: int(src.levels, LEVELS_MIN, LEVELS_MAX, d.levels),
    continuous: bool(src.continuous, d.continuous),
    scale: pick(src.scale, ["linear", "log"], d.scale),
    format: pick(src.format, ["auto", "fixed", "exp"], d.format),
    digits: int(src.digits, 0, DIGITS_MAX, d.digits),
    out: pick(src.out, ["clamp", "gray"], d.out),
    reversed: bool(src.reversed, d.reversed),
    minMark: bool(src.minMark, d.minMark),
    upin: bool(src.upin, d.upin),
    logDecades: int(src.logDecades, 1, 12, d.logDecades),
  };
}

/** 셰이더·범례에 주는 레벨 수: 연속 = 0 */
export const levelsOf = (s: Pick<LegendSettings, "levels" | "continuous">): number => (s.continuous ? 0 : s.levels);

export type ColorModeKey = "disp" | "load" | "c" | "dc" | "field" | "region";
export interface ColorModeRow {
  /** 자원 roles 키(seq|div|region) */
  role: ColorRole;
  /** 값에 부호가 있을 수 있음(→ 로그 불가) */
  signed: boolean;
  /** 로그 눈금 가능(양수 값 모드만) */
  logOk: boolean;
  /** 범위 0 중심 대칭 ±V */
  sym: boolean;
  /** 쌍의 두 카드가 같은 범위·범례를 씀(차이 = false) */
  pairRange: boolean;
  /** 범례 편집 가능(분류 표시 = false) */
  editable: boolean;
}
/** 색 모드 표 — 행 = 모드, 모든 열 필수(빈 칸 = 시험 실패 V-0251-30) */
export const COLOR_MODES: Record<ColorModeKey, ColorModeRow> = {
  disp: { role: "seq", signed: false, logOk: true, sym: false, pairRange: true, editable: true },
  load: { role: "seq", signed: false, logOk: true, sym: false, pairRange: true, editable: true },
  c: { role: "seq", signed: true, logOk: false, sym: false, pairRange: true, editable: true },
  dc: { role: "div", signed: true, logOk: false, sym: true, pairRange: false, editable: true },
  field: { role: "seq", signed: false, logOk: true, sym: false, pairRange: true, editable: true },
  region: { role: "region", signed: false, logOk: false, sym: false, pairRange: true, editable: false },
};
export function modeOf(key: ColorModeKey): ColorModeRow {
  return COLOR_MODES[key];
}

/** 로그 눈금을 쓸 수 있는가(모드가 허용 ∧ 범위 최대 > 0) */
export function logAllowed(mode: ColorModeRow, range: Range): boolean {
  return mode.logOk && !mode.signed && range.max > 0;
}

/** 범위·눈금 종류의 실제 값: 로그 + 최소 ≤ 0 이면 최소 = 최대/10^decades. 최대 ≤ 0 이거나 로그 불가면 선형 */
export function effectiveRange(range: Range, scale: LegendScale, decades: number): { range: Range; scale: LegendScale } {
  if (scale !== "log" || !(range.max > 0)) return { range, scale: "linear" };
  if (range.min > 0) return { range, scale };
  return { range: { min: range.max / Math.pow(10, decades), max: range.max }, scale };
}

/** 값 → 색 위치 t(0~1). 범위 밖은 끝(로그에서 v ≤ 0 은 0). 퇴화 범위 = 0, 비유한 값 = NaN. 범위는 effectiveRange 를 거친 것 */
export function toT(v: number, range: Range, scale: LegendScale = "linear"): number {
  if (!Number.isFinite(v)) return NaN;
  const { min, max } = range;
  if (!(max > min)) return 0;
  if (scale === "log") {
    if (!(min > 0) || v <= 0) return 0;
    return Math.max(0, Math.min(1, Math.log(v / min) / Math.log(max / min)));
  }
  return Math.max(0, Math.min(1, (v - min) / (max - min)));
}
/** toT 의 역함수(눈금·경계값) */
export function fromT(t: number, range: Range, scale: LegendScale = "linear"): number {
  if (scale === "log" && range.min > 0 && range.max > range.min) return range.min * Math.pow(range.max / range.min, t);
  return range.min + (range.max - range.min) * t;
}

/** 눈금 count 개(양 끝 포함) — 연속 범례의 5개. 선형·로그 모두 색 위치 t 에서 같은 간격 */
export function ticks(range: Range, scale: LegendScale = "linear", count = 5): number[] {
  return Array.from({ length: count }, (_, i) => fromT(count > 1 ? i / (count - 1) : 0, range, scale));
}
/** 레벨 L 칸의 경계값 L+1 개(0 = 최소 … L = 최대) */
export function boundaries(range: Range, scale: LegendScale, levels: number): number[] {
  return Array.from({ length: levels + 1 }, (_, i) => fromT(i / levels, range, scale));
}

/** 숫자 형식: auto = 유효 4자리(f3 — 지금 규칙) · fixed = 소수 digits 자리 · exp = 지수 digits 자리 */
export function formatValue(v: number | null | undefined, format: NumFormat = "auto", digits = 3): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const d = Math.max(0, Math.min(DIGITS_MAX, Math.round(digits)));
  if (format === "fixed") return v.toFixed(d);
  if (format === "exp") return v.toExponential(d);
  return f3(v);
}

/** 범위 밖 값 개수(끝색 또는 회색으로 칠해진 점). 최소 미만 / 최대 초과. 비유한 값 제외 */
export function countOut(values: ArrayLike<number>, range: Range): { above: number; below: number } {
  let above = 0;
  let below = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (!Number.isFinite(v)) continue;
    if (v > range.max) above += 1;
    else if (v < range.min) below += 1;
  }
  return { above, below };
}

/** 값 하나가 칠해지는 색 위치(범위 밖 = 끝색 또는 회색 표지 null). 시험·탐침용 — 셰이더 gpuColor 와 같은 규칙 */
export function colorPosition(v: number, range: Range, scale: LegendScale, levels: number, out: OutMode): number | null {
  if (!Number.isFinite(v)) return NaN;
  if (out === "gray" && (v < range.min || v > range.max)) return null;
  const t = toT(v, range, scale);
  if (!(levels > 0) || !(range.max > range.min)) return t;
  return (Math.min(Math.floor(t * levels), levels - 1) + 0.5) / levels;
}
