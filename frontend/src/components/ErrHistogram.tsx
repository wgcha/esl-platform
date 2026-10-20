// valid 요소의 부호 있는 오차 % 히스토그램(코어 field.histogram: ±R, 범위 밖은 끝 막대). 점선 = ±P90 기준.
import type { FieldHist } from "../api/types";
import { f3 } from "../lib/colormap";
import { ticks, useWidth } from "./MaxHoldChart";

const M = { l: 48, r: 12, t: 10, b: 38 };

export function ErrHistogram({ hist, crit }: { hist: FieldHist; crit?: number | null }) {
  const { ref, width: W } = useWidth<HTMLDivElement>(480);
  if (!hist.counts.length) return <div className="empty">valid 요소 없음</div>;
  const H = 200;
  const x0 = hist.edges[0];
  const x1 = hist.edges[hist.edges.length - 1];
  const ymax = Math.max(...hist.counts) * 1.1 || 1;
  const sx = (v: number) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - (v / ymax) * (H - M.t - M.b);
  return (
    <div ref={ref} className="chart">
      <svg width={W} height={H} role="img" aria-label="오차 히스토그램">
        {ticks(0, ymax, 4).map((v) => (
          <g key={`y${v}`}>
            <line x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} className="chart-grid" />
            <text x={M.l - 6} y={sy(v)} dy="0.32em" textAnchor="end" className="chart-tick">
              {v}
            </text>
          </g>
        ))}
        {hist.counts.map((c, i) => (
          <rect
            key={i}
            className={hist.edges[i] < 0 && hist.edges[i + 1] > 0 ? "hist-bar zero" : "hist-bar"}
            x={sx(hist.edges[i]) + 0.5}
            y={sy(c)}
            width={Math.max(0.5, sx(hist.edges[i + 1]) - sx(hist.edges[i]) - 1)}
            height={sy(0) - sy(c)}
          >
            <title>{`${f3(hist.edges[i])} ~ ${f3(hist.edges[i + 1])}%: ${c}개`}</title>
          </rect>
        ))}
        {ticks(x0, x1, 6).map((v) => (
          <text key={`x${v}`} x={sx(v)} y={H - M.b + 16} textAnchor="middle" className="chart-tick">
            {f3(v)}
          </text>
        ))}
        {crit != null &&
          [-crit, crit].filter((c) => c >= x0 && c <= x1).map((c) => <line key={c} className="chart-marker" x1={sx(c)} x2={sx(c)} y1={M.t} y2={H - M.b} />)}
        <line className="chart-axis" x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} />
        <text x={(M.l + W - M.r) / 2} y={H - 6} textAnchor="middle" className="chart-label">
          오차 % (ε_esl − ε_rad)/ε_rad
        </text>
      </svg>
    </div>
  );
}
