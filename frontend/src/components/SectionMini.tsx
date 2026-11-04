// v0.15.0 단면 미니 그림(esl_bead_select.md §7.1): 공칭 폭 중앙값 위치의 비드 단면(서버 section), 공칭 실선 + 범위 lo·hi 점선(브라우저 계산).
// 깊이 D_k: z + (D − D_nom)·dz_dD[k] · 폭 W: s + (W − W_nom)·ds_dW, z + (W − W_nom)·dz_dW. z = 깊이(+ 아래). SVG 240×120.
import type { DoeSection } from "../api/types";

export interface SectionVar {
  type: "D" | "W";
  tier?: number | null;
  nominal: number;
  lo: number;
  hi: number;
}

const W = 240;
const H = 120;

export function sectionLine(sec: DoeSection, v: SectionVar | null, value: number | null): [number, number][] {
  const d = v && value != null ? value - v.nominal : 0;
  const dz = v?.type === "D" ? sec.dz_dD[String(v.tier ?? 1)] ?? [] : [];
  return sec.s.map((s, i) => {
    if (!v || !d) return [s, sec.z[i]];
    if (v.type === "D") return [s, sec.z[i] + d * (dz[i] ?? 0)];
    return [s + d * (sec.ds_dW[i] ?? 0), sec.z[i] + d * (sec.dz_dW[i] ?? 0)];
  });
}

export function SectionMini({ sec, v, title }: { sec: DoeSection | null | undefined; v: SectionVar | null; title: string }) {
  if (!sec || !sec.s.length) return <div className="small muted">단면 자료 없음</div>;
  const lines = [sectionLine(sec, null, null), ...(v ? [sectionLine(sec, v, v.lo), sectionLine(sec, v, v.hi)] : [])];
  const xs = lines.flat().map((p) => p[0]);
  const zs = lines.flat().map((p) => p[1]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const z0 = Math.min(0, ...zs);
  const z1 = Math.max(...zs, 1);
  const pad = 10;
  const sx = (W - 2 * pad) / Math.max(1e-9, x1 - x0);
  const sz = (H - 2 * pad - 14) / Math.max(1e-9, z1 - z0);
  const k = Math.min(sx, sz); // 같은 축척(단면 각이 그대로 보이게)
  const X = (s: number) => W / 2 + (s - (x0 + x1) / 2) * k;
  const Y = (z: number) => pad + (z - z0) * k;
  const path = (pts: [number, number][]) => `M${pts.map(([s, z]) => `${X(s).toFixed(1)},${Y(z).toFixed(1)}`).join("L")}`;
  const nomDepth = Math.max(...sec.z);
  const label = v ? `${v.nominal.toFixed(1)} (${v.lo.toFixed(1)}–${v.hi.toFixed(1)})` : `D ${nomDepth.toFixed(1)}`;
  return (
    <figure className="bs-section" data-testid="section-mini">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={`${title} 단면`}>
        <line x1={0} x2={W} y1={Y(0)} y2={Y(0)} className="bs-sec-plate" />
        {v && <path d={path(lines[1])} className="bs-sec-range" data-testid="section-lo" />}
        {v && <path d={path(lines[2])} className="bs-sec-range" data-testid="section-hi" />}
        <path d={path(lines[0])} className="bs-sec-nom" />
        <text x={W - 4} y={H - 4} textAnchor="end" className="bs-sec-text">
          {v ? `${v.type === "D" ? `D${v.tier ?? 1}` : "W"} ${label}` : label} mm
        </text>
      </svg>
      <figcaption className="small muted">{title} 단면 · 실선 공칭{v ? " · 점선 하한·상한" : ""}</figcaption>
    </figure>
  );
}
