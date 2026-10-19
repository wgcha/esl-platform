// max-hold 곡선(SVG 직접). x = 시간 s, y = 지표 값. 후보 점과 t* 세로선 표시.
import type { TstarCandidate } from "../api/types";

const W = 1000;
const H = 320;
const M = { l: 64, r: 16, t: 16, b: 40 };

function tickFmt(ts: number[]) {
  const step = ts.length > 1 ? ts[1] - ts[0] : 1;
  const d = Math.max(0, -Math.floor(Math.log10(step)) + (step / 10 ** Math.floor(Math.log10(step)) === 2.5 ? 1 : 0));
  return (v: number) => v.toFixed(d);
}

function ticks(min: number, max: number, n = 5) {
  const span = max - min || 1;
  const step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= step0) ?? step0;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-12; v += step) out.push(+v.toPrecision(10));
  return out;
}

export function MaxHoldChart({
  time,
  value,
  candidates,
  selectedFrame,
  label,
}: {
  time: number[];
  value: number[];
  candidates: TstarCandidate[];
  selectedFrame: number | null;
  label: string;
}) {
  if (!time.length) return <div className="empty">곡선 데이터가 없습니다.</div>;
  const x0 = time[0];
  const x1 = time[time.length - 1] || 1;
  const y1 = Math.max(...value) * 1.08 || 1;
  const sx = (t: number) => M.l + ((t - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - (v / y1) * (H - M.t - M.b);
  const d = time.map((t, i) => `${i ? "L" : "M"}${sx(t).toFixed(1)},${sy(value[i]).toFixed(1)}`).join("");
  const sel = candidates.find((c) => c.frame_index === selectedFrame);
  const selT = sel ? sel.time : selectedFrame !== null && time[selectedFrame] !== undefined ? time[selectedFrame] : null;
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label} max-hold 곡선`}>
      {(() => { const ys = ticks(0, y1); const f = tickFmt(ys); return ys.map((v) => (
        <g key={`y${v}`}>
          <line x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} className="grid" />
          <text x={M.l - 6} y={sy(v) + 4} textAnchor="end" className="tick">
            {f(v)}
          </text>
        </g>
      )); })()}
      {ticks(x0, x1).map((t) => (
        <text key={`x${t}`} x={sx(t)} y={H - M.b + 16} textAnchor="middle" className="tick">
          {t.toFixed(3)}
        </text>
      ))}
      <text x={(M.l + W - M.r) / 2} y={H - 6} textAnchor="middle" className="axis-label">
        시간 (s)
      </text>
      <text x={14} y={(M.t + H - M.b) / 2} textAnchor="middle" className="axis-label" transform={`rotate(-90 14 ${(M.t + H - M.b) / 2})`}>
        {label} (max-hold)
      </text>
      <path d={d} className="line" />
      {candidates.map((c) => (
        <circle key={c.frame_index} cx={sx(c.time)} cy={sy(c.value)} r={4} className="cand">
          <title>{`후보 ${c.rank}: 프레임 ${c.frame_index}, t=${c.time}s, ${c.value}`}</title>
        </circle>
      ))}
      {selT !== null && (
        <g data-testid="tstar-marker">
          <line x1={sx(selT)} x2={sx(selT)} y1={M.t} y2={H - M.b} className="tstar" />
          <text x={sx(selT) + 6} y={M.t + 12} className="tstar-label">
            t* = {selT.toFixed(3)} s
          </text>
        </g>
      )}
    </svg>
  );
}
