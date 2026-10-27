// 변위 오차 r = e/U 의 log10 히스토그램(계약 esl_disp_primary.md §3.5): log10(r) 균등 bin, r = 0 노드는 n_zero 로 따로.
// 점선 = 판정 기준(disp_rms_rel_max·disp_max_rel_max) — 범위 밖이면 그리지 않는다.
import type { DispHist } from "../api/types";
import { f3 } from "../lib/colormap";
import { ticks, useWidth } from "./MaxHoldChart";

const M = { l: 52, r: 12, t: 10, b: 38 };
const H = 200;

export function DispHistogram({ hist, rmsCrit, maxCrit }: { hist: DispHist; rmsCrit?: number | null; maxCrit?: number | null }) {
  const { ref, width: W } = useWidth<HTMLDivElement>(480);
  const e = hist.edges_log10;
  if (!hist.counts.length || e.length < 2) return <div className="empty">변위 오차가 0인 노드뿐입니다(n_zero {hist.n_zero.toLocaleString()})</div>;
  const x0 = e[0];
  const x1 = e[e.length - 1];
  const ymax = Math.max(...hist.counts) * 1.1 || 1;
  const sx = (v: number) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - (v / ymax) * (H - M.t - M.b);
  const marks = [
    { v: rmsCrit, t: "RMS 기준" },
    { v: maxCrit, t: "최대 기준" },
  ]
    .filter((m): m is { v: number; t: string } => typeof m.v === "number" && m.v > 0)
    .map((m) => ({ x: Math.log10(m.v), t: m.t }))
    .filter((m) => m.x >= x0 && m.x <= x1);
  return (
    <div ref={ref} className="chart">
      <svg width={W} height={H} role="img" aria-label="변위 오차 히스토그램">
        {ticks(0, ymax, 4).map((v) => (
          <g key={`y${v}`}>
            <line x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} className="chart-grid" />
            <text x={M.l - 6} y={sy(v)} dy="0.32em" textAnchor="end" className="chart-tick">
              {v}
            </text>
          </g>
        ))}
        {hist.counts.map((c, i) => (
          <rect key={i} className="hist-bar" x={sx(e[i]) + 0.5} y={sy(c)} width={Math.max(0.5, sx(e[i + 1]) - sx(e[i]) - 1)} height={sy(0) - sy(c)}>
            <title>{`r = 10^${f3(e[i])} ~ 10^${f3(e[i + 1])}: ${c.toLocaleString()}개`}</title>
          </rect>
        ))}
        {ticks(x0, x1, 6).map((v) => (
          <text key={`x${v}`} x={sx(v)} y={H - M.b + 16} textAnchor="middle" className="chart-tick">
            {`1e${v}`}
          </text>
        ))}
        {marks.map((m) => (
          <g key={m.t}>
            <line className="chart-marker" x1={sx(m.x)} x2={sx(m.x)} y1={M.t} y2={H - M.b} />
            <text x={sx(m.x) - 3} y={M.t + 10} textAnchor="end" className="chart-label marker">
              {m.t}
            </text>
          </g>
        ))}
        <line className="chart-axis" x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} />
        <text x={(M.l + W - M.r) / 2} y={H - 6} textAnchor="middle" className="chart-label">
          노드별 변위 오차 r = e/U (log 눈금)
        </text>
      </svg>
      <div className="small muted" data-testid="disp-hist-note">
        노드 {hist.n.toLocaleString()}개{hist.n_zero > 0 ? ` · 오차 0 노드 ${hist.n_zero.toLocaleString()}개(그래프 제외)` : ""}
      </div>
    </div>
  );
}
