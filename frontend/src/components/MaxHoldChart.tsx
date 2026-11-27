// max-hold 곡선(SVG 직접). x = 시간 s, y = 지표 값. 후보 점과 t* 세로선 표시.
// 픽셀 폭으로 그린다(PhysicsAI Chart 와 같은 글자 크기·여백·클래스).
import { useLayoutEffect, useRef, useState } from "react";
// v0.8.0: valueInc(누적 씬 이번 낙하 증분)를 주면 범례 버튼으로 증분 곡선을 켜고 끈다(기본 누적만).
import type { TstarCandidate } from "../api/types";

const M = { l: 58, r: 14, t: 18, b: 40 };

export function useWidth<T extends HTMLElement>(fallback = 600) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      if (w > 0) setWidth(w);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

function tickFmt(ts: number[]) {
  const step = ts.length > 1 ? ts[1] - ts[0] : 1;
  const d = Math.max(0, -Math.floor(Math.log10(step)) + (step / 10 ** Math.floor(Math.log10(step)) === 2.5 ? 1 : 0));
  return (v: number) => v.toFixed(d);
}

export function ticks(min: number, max: number, n = 5) {
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
  valueInc,
  candidates,
  selectedFrame,
  label,
  frames,
  onPick,
}: {
  time: number[];
  value: number[];
  valueInc?: number[];
  candidates: TstarCandidate[];
  selectedFrame: number | null;
  label: string;
  /** v0.25.2 §7.1: 곡선 점마다 프레임 번호(없으면 배열 위치) */
  frames?: number[];
  /** 주면 곡선 클릭 = 가장 가까운 프레임 선택(실행 권한 있을 때만 준다) */
  onPick?: (frame: number) => void;
}) {
  const { ref, width: W } = useWidth<HTMLDivElement>();
  const [showInc, setShowInc] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const inc = valueInc && valueInc.length === time.length ? valueInc : null;
  const H = Math.round(Math.max(280, Math.min(W * 0.32, 480)));
  if (!time.length) return <div className="empty">곡선 데이터가 없습니다</div>;
  const x0 = time[0];
  const x1 = time[time.length - 1] || 1;
  const y1 = Math.max(...value) * 1.08 || 1;
  const sx = (t: number) => M.l + ((t - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - (v / y1) * (H - M.t - M.b);
  const d = time.map((t, i) => `${i ? "L" : "M"}${sx(t).toFixed(1)},${sy(value[i]).toFixed(1)}`).join("");
  const dInc = inc && showInc ? time.map((t, i) => `${i ? "L" : "M"}${sx(t).toFixed(1)},${sy(Math.max(0, inc[i])).toFixed(1)}`).join("") : null;
  const frameAt = (i: number) => frames?.[i] ?? i;
  // t* 세로선 = 그 프레임의 시각(frame_stride > 1 에서도 맞음 — 프레임 번호 = 배열 위치 가정 안 함)
  const selPos = selectedFrame === null ? -1 : time.findIndex((_, i) => frameAt(i) === selectedFrame);
  const sel = candidates.find((c) => c.frame_index === selectedFrame);
  const selT = selPos >= 0 ? time[selPos] : sel ? sel.time : null;
  // 마우스 x → 가장 가까운 곡선 점(시각 차 최소, 동률 = 앞 프레임)
  const posAt = (clientX: number, svg: SVGSVGElement) => {
    const px = clientX - svg.getBoundingClientRect().left;
    const t = x0 + ((px - M.l) / (W - M.l - M.r)) * (x1 - x0 || 1);
    let best = 0;
    let bd = Infinity;
    for (let i = 0; i < time.length; i++) {
      const dd = Math.abs(time[i] - t);
      if (dd < bd) {
        bd = dd;
        best = i;
      }
    }
    return best;
  };
  const inPlot = (clientX: number, clientY: number, svg: SVGSVGElement) => {
    const r = svg.getBoundingClientRect();
    const px = clientX - r.left;
    const py = clientY - r.top;
    return px >= M.l && px <= W - M.r && py >= M.t && py <= H - M.b;
  };
  return (
    <div ref={ref} className="chart">
      <svg
        width={W}
        height={H}
        role="img"
        aria-label={`${label} max-hold 곡선`}
        className={onPick ? "pickable" : undefined}
        data-testid="maxhold-svg"
        onMouseMove={(e) => setHover(onPick && inPlot(e.clientX, e.clientY, e.currentTarget) ? posAt(e.clientX, e.currentTarget) : null)}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          if (onPick && inPlot(e.clientX, e.clientY, e.currentTarget)) onPick(frameAt(posAt(e.clientX, e.currentTarget)));
        }}
      >
        {(() => { const ys = ticks(0, y1); const f = tickFmt(ys); return ys.map((v) => (
          <g key={`y${v}`}>
            <line x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} className="chart-grid" />
            <text x={M.l - 6} y={sy(v)} dy="0.32em" textAnchor="end" className="chart-tick">
              {f(v)}
            </text>
          </g>
        )); })()}
        {ticks(x0, x1).map((t) => (
          <text key={`x${t}`} x={sx(t)} y={H - M.b + 16} textAnchor="middle" className="chart-tick">
            {t.toFixed(3)}
          </text>
        ))}
        <line className="chart-axis" x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} />
        <line className="chart-axis" x1={M.l} x2={M.l} y1={M.t} y2={H - M.b} />
        <text x={(M.l + W - M.r) / 2} y={H - 6} textAnchor="middle" className="chart-label">
          시간 (s)
        </text>
        <text textAnchor="middle" className="chart-label" transform={`translate(12 ${(M.t + H - M.b) / 2}) rotate(-90)`}>
          {label} (max-hold)
        </text>
        <path d={d} className="chart-line" />
        {dInc && <path d={dInc} className="chart-line inc" data-testid="inc-line" />}
        {candidates.map((c) => (
          <circle
            key={c.frame_index}
            cx={sx(c.time)}
            cy={sy(c.value)}
            r={c.frame_index === selectedFrame ? 4.5 : 3.5}
            className={c.frame_index === selectedFrame ? "chart-pt current" : "chart-pt"}
            data-testid={`chart-cand-${c.frame_index}`}
            onClick={(e) => {
              if (!onPick) return;
              e.stopPropagation();
              onPick(c.frame_index);
            }}
          >
            <title>{`후보 ${c.rank}: 프레임 ${c.frame_index}, t=${c.time}s, ${c.value}`}</title>
          </circle>
        ))}
        {selT !== null && (
          <g data-testid="tstar-marker">
            <line x1={sx(selT)} x2={sx(selT)} y1={M.t} y2={H - M.b} className="chart-marker" />
            <text x={sx(selT) + 6} y={M.t - 4} className="chart-label marker">
              t* = {selT.toFixed(3)} s
            </text>
          </g>
        )}
        {hover !== null && onPick && (
          <g data-testid="chart-hover" pointerEvents="none">
            <line x1={sx(time[hover])} x2={sx(time[hover])} y1={M.t} y2={H - M.b} className="chart-hover" />
            <text x={M.l + 8} y={M.t + 14} className="chart-label hover">
              프레임 {frameAt(hover)} · {time[hover].toFixed(3)} s · {+value[hover].toPrecision(4)}
            </text>
          </g>
        )}
      </svg>
      {inc && (
        <div className="legend small" data-testid="cum-legend">
          <span><span className="lg line" /> 누적(이전 + 이번)</span>
          <button type="button" className={showInc ? "lg-btn on" : "lg-btn"} aria-pressed={showInc} onClick={() => setShowInc((v) => !v)}>
            <span className="lg line inc" /> 이번(증분)
          </button>
        </div>
      )}
    </div>
  );
}
