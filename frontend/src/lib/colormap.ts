// 색 지도: 코어 Case HTML 보고서(esl/report/case_report.py JS)와 같은 정점 — ε 는 viridis(10점), 오차는 발산(7점, 파랑=과소·빨강=과대).
export type RGB = [number, number, number];

export const VIRIDIS: RGB[] = [
  [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142],
  [31, 158, 137], [53, 183, 121], [109, 205, 89], [180, 222, 44], [253, 231, 37],
];
export const DIVERGING: RGB[] = [
  [49, 54, 149], [69, 117, 180], [145, 191, 219], [240, 228, 140], [252, 141, 89], [215, 48, 39], [165, 0, 38],
];
/** 비교 불가 회색(보고서 --na) */
export const NA_COLOR = "#9aa1ab";

export function lerp(c: RGB[], t: number): string {
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0)) * (c.length - 1);
  const i = Math.min(Math.floor(x), c.length - 2);
  const f = x - i;
  const a = c[i];
  const b = c[i + 1];
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(a[1] + (b[1] - a[1]) * f)},${Math.round(a[2] + (b[2] - a[2]) * f)})`;
}

export function gradient(c: RGB[]): string {
  return `linear-gradient(90deg, ${c.map((x, i) => `rgb(${x.join(",")}) ${Math.round((100 * i) / (c.length - 1))}%`).join(", ")})`;
}

/** 유효 숫자 4자리(보고서 f3 과 같은 규칙) */
export function f3(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  return a !== 0 && (a < 1e-3 || a >= 1e6) ? v.toExponential(3) : String(+v.toPrecision(4));
}
