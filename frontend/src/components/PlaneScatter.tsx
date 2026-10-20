// PCA 평면 2D 산점: 점은 canvas(≤20000), 지지점·꼭지점 표시는 SVG 겹침. 색 = 값(|u|).
import { useEffect, useMemo, useRef } from "react";

const W = 760;
const H = 420;
const PAD = 28;

// 순차 색(viridis 근사) — 5점 보간
const STOPS = [
  [68, 1, 84],
  [59, 82, 139],
  [33, 145, 140],
  [94, 201, 98],
  [253, 231, 37],
];
export function seqColor(t: number) {
  const x = Math.min(1, Math.max(0, t)) * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(x));
  const f = x - i;
  const c = STOPS[i].map((v, k) => Math.round(v + (STOPS[i + 1][k] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export interface Marker {
  label: string;
  a: number;
  b: number;
  kind: "support" | "corner";
}

export function PlaneScatter({ points, markers, valueLabel }: { points: [number, number, number, number][]; markers: Marker[]; valueLabel: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const geo = useMemo(() => {
    let amin = Infinity, amax = -Infinity, bmin = Infinity, bmax = -Infinity, vmin = Infinity, vmax = -Infinity;
    for (const [, a, b, v] of points) {
      if (a < amin) amin = a;
      if (a > amax) amax = a;
      if (b < bmin) bmin = b;
      if (b > bmax) bmax = b;
      if (v < vmin) vmin = v;
      if (v > vmax) vmax = v;
    }
    // 같은 축척(왜곡 없음)
    const s = Math.min((W - 2 * PAD) / (amax - amin || 1), (H - 2 * PAD) / (bmax - bmin || 1));
    const ox = (W - s * (amax - amin)) / 2;
    const oy = (H - s * (bmax - bmin)) / 2;
    return {
      sx: (a: number) => ox + (a - amin) * s,
      sy: (b: number) => H - oy - (b - bmin) * s,
      vmin,
      vmax,
    };
  }, [points]);

  useEffect(() => {
    const cv = canvas.current;
    if (!cv || (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent))) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr;
    cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const span = geo.vmax - geo.vmin || 1;
    const r = points.length > 10000 ? 1.4 : 2.2;
    for (const [, a, b, v] of points) {
      ctx.fillStyle = seqColor((v - geo.vmin) / span);
      ctx.fillRect(geo.sx(a) - r, geo.sy(b) - r, 2 * r, 2 * r);
    }
  }, [points, geo]);

  return (
    <div className="scatter">
      <div className="scatter-box">
        <canvas ref={canvas} style={{ width: "100%", aspectRatio: `${W} / ${H}` }} aria-label="PCA 평면 산점" />
        <svg viewBox={`0 0 ${W} ${H}`} className="overlay" aria-label="지지점 표시">
          {markers.map((m) => {
            const x = geo.sx(m.a);
            const y = geo.sy(m.b);
            return m.kind === "corner" ? (
              <rect key={`c${m.label}`} x={x - 5} y={y - 5} width={10} height={10} className="corner" />
            ) : (
              <g key={`s${m.label}`} data-testid="support-marker">
                <circle cx={x} cy={y} r={8} className="support" />
                <text x={x > W - 100 ? x - 12 : x + 12} y={y < 30 ? y + 24 : y - 12} textAnchor={x > W - 100 ? "end" : "start"} className="support-label">
                  {m.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="legend small">
        <span>{valueLabel}</span>
        <span className="mono">{geo.vmin.toPrecision(3)}</span>
        <span className="ramp" style={{ background: `linear-gradient(90deg, ${[0, 0.25, 0.5, 0.75, 1].map(seqColor).join(",")})` }} />
        <span className="mono">{geo.vmax.toPrecision(3)}</span>
        <span className="muted">점 {points.length.toLocaleString()}개</span>
        <span>
          <span className="lg corner" /> 평면 꼭지점
        </span>
        <span>
          <span className="lg support" /> 지지점
        </span>
      </div>
    </div>
  );
}
