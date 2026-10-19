export const fmt = (v: number | null | undefined, digits = 3) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toPrecision(digits);
export const fmtFixed = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "–" : v.toFixed(d));
export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`);
export const sci = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toExponential(2));
export const vec = (a: number[] | undefined, f: (x: number) => string = sci) => (a ? `(${a.map(f).join(", ")})` : "–");
export function bytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
export const dt = (iso: string | null | undefined) => (iso ? iso.replace("T", " ").slice(0, 16) : "–");
export const METRIC_LABEL = { max_strain: "Max_Strain", plastic_strain: "Plastic" } as const;
export const JOB_STATE_LABEL: Record<string, string> = {
  QUEUED: "대기",
  RUNNING: "실행 중",
  SUCCEEDED: "완료",
  FAILED: "실패",
  CANCELED: "취소",
  INTERRUPTED: "중단",
};
