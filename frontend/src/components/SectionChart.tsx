// ⑤ 단면선: ξ(또는 η) = 0.5 고정 단면의 면외 좌표 — 초기 w0, Radioss w0 + k·w_rad, ESL w0 + k·w_esl.
// 배율 k 는 로그 슬라이더(10^0 ~ 10^4). 기본 k 는 최대 면외 변위 × k ≈ 단면 길이의 5% (코어 보고서와 같음).
import { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import type { SectionAxis, SectionOut } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { f3 } from "../lib/colormap";
import { ticks, useWidth } from "./MaxHoldChart";
import { Empty } from "./ui";

const M = { l: 58, r: 14, t: 12, b: 40 };

export function defaultScaleExp(d: SectionOut): number {
  let wmax = 0;
  for (const v of [...d.w_rad, ...d.w_esl]) wmax = Math.max(wmax, Math.abs(v));
  const span = d.s.length ? Math.max(...d.s) - Math.min(...d.s) : 0;
  const k0 = wmax <= 0 || span <= 0 ? 1 : Math.min(Math.max((0.05 * span) / wmax, 1), 1e4);
  return Math.round(Math.log10(k0) * 100) / 100;
}

export function SectionChart({ vid }: { vid: string }) {
  const [axis, setAxis] = useState<SectionAxis>("xi");
  const sec = usePolling(() => api.section(vid, axis), 0, [vid, axis]);
  const [kexp, setKexp] = useState<number | null>(null);
  const { ref, width: W } = useWidth<HTMLDivElement>(560);
  const d = sec.data;
  useEffect(() => {
    if (d && kexp === null) setKexp(defaultScaleExp(d));
  }, [d, kexp]);
  const ke = kexp ?? 0;
  const k = 10 ** ke;

  let plot = null;
  if (d && d.s.length) {
    const H = Math.round(Math.max(220, Math.min(W * 0.5, 340)));
    const ys = [d.w0, d.w0.map((v, i) => v + k * d.w_rad[i]), d.w0.map((v, i) => v + k * d.w_esl[i])];
    const x0 = Math.min(...d.s);
    const x1 = Math.max(...d.s) || x0 + 1;
    let y0 = Math.min(...ys.flat());
    let y1 = Math.max(...ys.flat());
    if (!(y1 > y0)) (y0 -= 1), (y1 += 1);
    const m = (y1 - y0) * 0.08;
    y0 -= m;
    y1 += m;
    const sx = (v: number) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
    const sy = (v: number) => H - M.b - ((v - y0) / (y1 - y0)) * (H - M.t - M.b);
    const path = (y: number[]) => d.s.map((s, i) => `${i ? "L" : "M"}${sx(s).toFixed(1)},${sy(y[i]).toFixed(1)}`).join("");
    plot = (
      <svg width={W} height={H} role="img" aria-label="단면선">
        {ticks(y0, y1).map((v) => (
          <g key={`y${v}`}>
            <line x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} className="chart-grid" />
            <text x={M.l - 6} y={sy(v)} dy="0.32em" textAnchor="end" className="chart-tick">
              {f3(v)}
            </text>
          </g>
        ))}
        {ticks(x0, x1, 6).map((v) => (
          <text key={`x${v}`} x={sx(v)} y={H - M.b + 16} textAnchor="middle" className="chart-tick">
            {f3(v)}
          </text>
        ))}
        <line className="chart-axis" x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} />
        <line className="chart-axis" x1={M.l} x2={M.l} y1={M.t} y2={H - M.b} />
        <text x={(M.l + W - M.r) / 2} y={H - 6} textAnchor="middle" className="chart-label">
          {axis === "xi" ? "η (PCA 평면, mm)" : "ξ (PCA 평면, mm)"}
        </text>
        <text textAnchor="middle" className="chart-label" transform={`translate(12 ${(M.t + H - M.b) / 2}) rotate(-90)`}>
          면외 n (mm)
        </text>
        <path d={path(ys[0])} className="ln-init" data-testid="sec-init" />
        <path d={path(ys[1])} className="ln-rad" data-testid="sec-rad" />
        <path d={path(ys[2])} className="ln-esl" data-testid="sec-esl" />
      </svg>
    );
  }

  return (
    <div className="ovl" ref={ref}>
      <div className="ctrl-row">
        <div className="seg" role="group" aria-label="단면">
          <button type="button" className={axis === "xi" ? "on" : ""} aria-pressed={axis === "xi"} onClick={() => setAxis("xi")}>
            ξ = 0.5
          </button>
          <button type="button" className={axis === "eta" ? "on" : ""} aria-pressed={axis === "eta"} onClick={() => setAxis("eta")}>
            η = 0.5
          </button>
        </div>
        <label className="range-field">
          <span className="small">배율</span>
          <input type="range" min={0} max={4} step={0.01} value={ke} aria-label="변형 배율" onChange={(e) => setKexp(Number(e.target.value))} />
          <span className="mono small range-val" data-testid="sec-k">
            ×{f3(k)}
          </span>
        </label>
      </div>
      {sec.error ? <div className="error-text">{sec.error}</div> : !d ? <Empty>불러오는 중…</Empty> : plot ?? <Empty>단면 요소 없음</Empty>}
      <div className="legend small">
        <span>
          <span className="lg ln-init" /> 초기
        </span>
        <span>
          <span className="lg ln-rad" /> Radioss (u_rel)
        </span>
        <span>
          <span className="lg ln-esl" /> ESL (u_val)
        </span>
      </div>
    </div>
  );
}
