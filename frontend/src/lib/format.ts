import type { StrainSource } from "../api/types";
export const fmt = (v: number | null | undefined, digits = 3) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toPrecision(digits);
/** toFixed + 부호 있는 0 정규화: 반올림 결과가 0 이면 "-0.0" 대신 "0.0" */
export function fixedZ(v: number, d = 1): string {
  const s = v.toFixed(d);
  return Number(s) === 0 ? (0).toFixed(d) : s;
}
export const fmtFixed = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "–" : fixedZ(v, d));
export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "–" : `${fixedZ(v * 100, d)}%`);
const bad = (v: number | null | undefined): v is null | undefined => v === null || v === undefined || !Number.isFinite(v);
/** 값이 이미 % 단위 */
export const pv = (v: number | null | undefined, d = 1) => (bad(v) ? "–" : `${fixedZ(v, d)}%`);
/** 값이 이미 % 단위, 부호 표시(+/−). 반올림해 0 이면 부호 없이 "0.0%" */
export const spv = (v: number | null | undefined, d = 1) => {
  if (bad(v)) return "–";
  const s = fixedZ(v, d);
  return `${Number(s) > 0 ? "+" : ""}${s}%`;
};
export const sci = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toExponential(2));
export const vec = (a: number[] | undefined, f: (x: number) => string = sci) => (a ? `(${a.map(f).join(", ")})` : "–");
export function bytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
/** 시각 표기(PhysicsAI fmtTime 과 같음): 현지 시각 "M/D HH:mm" */
export function dt(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
/** v0.12.1 변형률 대체 배지(esl_strain_fallback.md §1·§7): max_strain·없음 = 배지 없음 */
export const STRAIN_SOURCE_BADGE: Record<StrainSource, { text: string; kind: "info" | "warn" } | null> = {
  max_strain: null,
  plastic_strain: { text: "대체: 소성 변형률 기준", kind: "info" },
  strain_tensor: { text: "대체: Strain 텐서 기준", kind: "info" },
  max_stress: { text: "응력 기준 대체, 판정 신뢰 낮음", kind: "warn" },
};
export const strainSourceBadge = (s: StrainSource | null | undefined) => (s ? (STRAIN_SOURCE_BADGE[s] ?? null) : null);
export const METRIC_LABEL = { max_strain: "Max_Strain", plastic_strain: "Plastic" } as const;
export const JOB_STATE_LABEL: Record<string, string> = {
  QUEUED: "대기",
  RUNNING: "실행 중",
  SUCCEEDED: "성공",
  FAILED: "실패",
  CANCELED: "취소됨",
  INTERRUPTED: "중단됨",
};

const DOF_AX: Record<string, string> = { "1": "x", "2": "y", "3": "z" };
/** 3-2-1 dof 표기: "123" → "123 (x·y·z)" */
export const dofText = (d: string) => (/^[123]+$/.test(d) ? `${d} (${d.split("").map((k) => DOF_AX[k]).join("·")})` : d);
