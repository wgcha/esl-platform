// ⑤ 겹쳐보기: PCA 평면 요소 중심 컨투어(canvas 2D). 레이어 Radioss ε / ESL ε / 오차 %, 불투명도 슬라이더로
// Radioss 위에 ESL 을 겹친다. 공통 색 범위, 회색 = 비교 불가(사유는 마우스 오버 툴팁), hotspot·최대변형률 표식.
// 시각 규칙은 코어 Case HTML 보고서(esl/report/case_report.py "겹쳐보기")와 같다.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/endpoints";
import type { FieldLayer, FieldOut, FieldSummary, ValidationHotspot } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { DIVERGING, NA_COLOR, VIRIDIS, f3, gradient, lerp } from "../lib/colormap";
import { useWidth } from "./MaxHoldChart";
import { Empty } from "./ui";

/** rad·esl 레이어에서 회색인 사유(LOW 는 상승 중이므로 색 표시). 오차 레이어는 OK 외 전부 회색. */
const GREY_EPS = new Set(["HOLD", "EXCLUDED", "NO_PREV"]);

export const REASON_LABEL: Record<string, string> = {
  OK: "비교 대상",
  HOLD: "t* 에서 상승 중이 아님(hold) — 순간값이 아님",
  LOW: "작은 변형률(ε_rad < min_rel·max) — 상대오차 의미 없음",
  EXCLUDED: "사용자 제외 요소",
  NO_PREV: "직전 프레임 값 없음(예전 TCL 출력)",
};

export function isGrey(layer: FieldLayer, value: number | null, reason: string) {
  if (value === null || !Number.isFinite(value)) return true;
  return layer === "err" ? reason !== "OK" : GREY_EPS.has(reason);
}

/** 점 색(회색이면 null). range: rad·esl = 공통 [min, max], err = ±R */
export function cellColor(layer: FieldLayer, value: number | null, reason: string, range: { min: number; max: number }): string | null {
  if (isGrey(layer, value, reason)) return null;
  if (layer === "err") {
    const R = Math.max(Math.abs(range.min), Math.abs(range.max)) || 1;
    return lerp(DIVERGING, (value! / R + 1) / 2);
  }
  return lerp(VIRIDIS, (value! - range.min) / (range.max - range.min || 1));
}

type Mode = "eps" | "err";
type Range = { min: number; max: number };

/** rad·esl 공통 색 범위: 서버 color_range(두 레이어 합친 값) — 없으면 비교 가능 점에서 계산 */
export function rangeOf(fs: FieldOut[]): Range {
  let lo = Infinity;
  let hi = -Infinity;
  for (const f of fs) {
    if (f.color_range.min != null) lo = Math.min(lo, f.color_range.min);
    if (f.color_range.max != null) hi = Math.max(hi, f.color_range.max);
  }
  if (!(hi > lo))
    for (const f of fs)
      for (const p of f.points)
        if (p[3] !== null && !isGrey(f.layer, p[3], p[4])) {
          lo = Math.min(lo, p[3]);
          hi = Math.max(hi, p[3]);
        }
  return hi > lo ? { min: Math.min(0, lo), max: hi } : { min: 0, max: 1 };
}

/** 오차 색 범위 ±R(서버 color_range, 없으면 1%) */
export function errRangeOf(f: FieldOut): Range {
  const R = Math.max(Math.abs(f.color_range.min ?? 0), Math.abs(f.color_range.max ?? 0)) || 1;
  return { min: -R, max: R };
}

interface Geo {
  W: number;
  H: number;
  sx: (a: number) => number;
  sy: (b: number) => number;
  cell: number;
}

const PAD = 18;

function geometry(f: FieldOut, W: number): Geo {
  let amin = Infinity, amax = -Infinity, bmin = Infinity, bmax = -Infinity;
  for (const p of f.points) {
    if (p[1] < amin) amin = p[1];
    if (p[1] > amax) amax = p[1];
    if (p[2] < bmin) bmin = p[2];
    if (p[2] > bmax) bmax = p[2];
  }
  const dx = amax - amin || 1;
  const dy = bmax - bmin || 1;
  const H = Math.round(Math.max(240, Math.min(560, ((W - 2 * PAD) * dy) / dx + 2 * PAD)));
  const s = Math.min((W - 2 * PAD) / dx, (H - 2 * PAD) / dy);
  const ox = (W - s * dx) / 2;
  const oy = (H - s * dy) / 2;
  // 표시 칸 크기: 다운샘플 격자 칸(cell) 또는 평면 범위 ÷ 점 수(요소 크기 근사)
  const cellW = f.cell && f.cell.length === 2 ? Math.sqrt(f.cell[0] * f.cell[1]) * 1.04 : Math.sqrt((dx * dy) / Math.max(1, f.points.length)) * 1.08;
  return { W, H, sx: (a) => ox + (a - amin) * s, sy: (b) => H - oy - (b - bmin) * s, cell: Math.max(1.2, cellW * s) };
}

function draw(cv: HTMLCanvasElement | null, f: FieldOut | undefined, layer: FieldLayer, range: { min: number; max: number }, g: Geo | null) {
  if (!cv || !f || !g || (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent))) return;
  const ctx = cv.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(g.W * dpr);
  cv.height = Math.round(g.H * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, g.W, g.H);
  const w = g.cell;
  for (const [, a, b, v, reason] of f.points) {
    ctx.fillStyle = cellColor(layer, v, reason, range) ?? NA_COLOR;
    ctx.fillRect(g.sx(a) - w / 2, g.sy(b) - w / 2, w, w);
  }
}

export function FieldOverlay({ vid, hotspots, summary }: { vid: string; hotspots: ValidationHotspot[]; summary: FieldSummary | null | undefined }) {
  const data = usePolling(
    () => Promise.all((["rad", "esl", "err"] as FieldLayer[]).map((l) => api.field(vid, l))).then(([rad, esl, err]) => ({ rad, esl, err })),
    0,
    [vid],
  );
  const [mode, setMode] = useState<Mode>("eps");
  const [op, setOp] = useState(0); // ESL 불투명도 %
  const [tip, setTip] = useState<{ x: number; y: number; text: string; grey: boolean } | null>(null);
  const { ref, width } = useWidth<HTMLDivElement>(760);
  const c0 = useRef<HTMLCanvasElement>(null);
  const c1 = useRef<HTMLCanvasElement>(null);
  const d = data.data;

  const epsRange = useMemo(() => (d ? rangeOf([d.rad, d.esl]) : { min: 0, max: 1 }), [d]);
  const errRange = useMemo(() => (d ? errRangeOf(d.err) : { min: -1, max: 1 }), [d]);
  const geo = useMemo(() => (d ? geometry(d.rad, width) : null), [d, width]);
  const byId = useMemo(() => {
    const m = new Map<number, { a: number; b: number; rad: number | null; esl: number | null; err: number | null; reason: string }>();
    if (!d) return m;
    for (const p of d.rad.points) m.set(p[0], { a: p[1], b: p[2], rad: p[3], esl: null, err: null, reason: p[4] });
    for (const p of d.esl.points) {
      const x = m.get(p[0]);
      if (x) x.esl = p[3];
    }
    for (const p of d.err.points) {
      const x = m.get(p[0]);
      if (x) x.err = p[3];
    }
    return m;
  }, [d]);

  const baseLayer: FieldLayer = mode === "err" ? "err" : "rad";
  useEffect(() => {
    if (!d) return;
    draw(c0.current, mode === "err" ? d.err : d.rad, baseLayer, mode === "err" ? errRange : epsRange, geo);
    if (mode === "eps") draw(c1.current, d.esl, "esl", epsRange, geo);
  }, [d, mode, baseLayer, epsRange, errRange, geo]);

  // 표식: hotspot(순위) + 최대변형률 요소
  const markers = useMemo(() => {
    const out: { key: string; a: number; b: number; label: string; kind: "hot" | "max"; id: number }[] = [];
    const pos = new Map<number, [number, number]>();
    for (const r of [...(summary?.top ?? []), ...(summary?.worst ?? [])]) if (r.xi !== undefined && r.eta !== undefined) pos.set(r.elem_id, [r.xi, r.eta]);
    for (const [id, p] of byId) pos.set(id, [p.a, p.b]);
    hotspots.forEach((h, k) => {
      const p = pos.get(h.elem_id);
      if (p) out.push({ key: `h${h.elem_id}`, a: p[0], b: p[1], label: String(h.rank ?? k + 1), kind: "hot", id: h.elem_id });
    });
    const mx = summary?.max;
    // 최대변형률 표식을 먼저(아래) 그려 hotspot 순위 숫자가 가려지지 않게
    if (mx && mx.xi !== undefined && mx.eta !== undefined) out.unshift({ key: "max", a: mx.xi, b: mx.eta, label: "", kind: "max", id: mx.elem_id });
    return out;
  }, [hotspots, summary, byId]);

  if (data.error || !d || !geo)
    return (
      <div className="ovl" ref={ref}>
        {data.error ? <div className="error-text">{data.error}</div> : <Empty>겹쳐보기 자료 불러오는 중…</Empty>}
      </div>
    );

  const shownLayer: FieldLayer = mode === "err" ? "err" : op >= 100 ? "esl" : "rad";
  const f = d[shownLayer];
  const greyCount = f.points.filter((p) => isGrey(shownLayer, p[3], p[4])).length;
  const on = (k: "rad" | "esl" | "err") => (k === "err" ? mode === "err" : mode === "eps" && (k === "rad" ? op === 0 : op === 100));

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!geo || !d) return;
    const r = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - r.left;
    const my = e.clientY - r.top;
    let best: number | null = null;
    let bd = Math.max(64, (geo.cell * 0.75) ** 2);
    for (const [id, p] of byId) {
      const dx = geo.sx(p.a) - mx;
      const dy = geo.sy(p.b) - my;
      const dd = dx * dx + dy * dy;
      if (dd < bd) {
        bd = dd;
        best = id;
      }
    }
    if (best === null) return setTip(null);
    const p = byId.get(best)!;
    const layerVal = mode === "err" ? p.err : op >= 50 ? p.esl : p.rad;
    const grey = isGrey(mode === "err" ? "err" : op >= 50 ? "esl" : "rad", layerVal, p.reason);
    const text =
      `요소 ${best} · ε_rad ${f3(p.rad)} · ε_esl ${f3(p.esl)} · 오차 ${p.err === null ? "–" : `${f3(p.err)}%`}` +
      (grey ? ` · 비교 불가: ${REASON_LABEL[p.reason] ?? p.reason}` : "");
    setTip({ x: mx, y: my, text, grey });
  }

  return (
    <div className="ovl" ref={ref}>
      <div className="ctrl-row">
        <div className="seg" role="group" aria-label="레이어">
          <button type="button" className={on("rad") ? "on" : ""} aria-pressed={on("rad")} onClick={() => (setMode("eps"), setOp(0))}>
            Radioss ε
          </button>
          <button type="button" className={on("esl") ? "on" : ""} aria-pressed={on("esl")} onClick={() => (setMode("eps"), setOp(100))}>
            ESL ε
          </button>
          <button type="button" className={on("err") ? "on" : ""} aria-pressed={on("err")} onClick={() => setMode("err")}>
            오차 %
          </button>
        </div>
        <label className="range-field" title={mode === "err" ? "오차 레이어에서는 겹치기를 쓰지 않습니다" : "Radioss 위에 ESL 을 겹칩니다"}>
          <span className="small">Radioss</span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={op}
            disabled={mode === "err"}
            aria-label="ESL 불투명도"
            onChange={(e) => setOp(Number(e.target.value))}
          />
          <span className="small">ESL</span>
          <span className="mono small range-val" data-testid="ovl-op">
            {op}%
          </span>
        </label>
      </div>
      <div className="ovl-box" style={{ height: geo.H }} onMouseMove={onMove} onMouseLeave={() => setTip(null)} data-testid="ovl-box">
        <canvas ref={c0} style={{ width: geo.W, height: geo.H }} aria-label={`${shownLayer === "err" ? "오차" : "Radioss"} 컨투어`} data-layer={baseLayer} />
        <canvas
          ref={c1}
          className="ovl-top"
          style={{ width: geo.W, height: geo.H, opacity: mode === "eps" ? op / 100 : 0, visibility: mode === "eps" && op > 0 ? "visible" : "hidden" }}
          aria-label="ESL 컨투어"
          data-testid="ovl-esl"
        />
        <svg className="overlay" viewBox={`0 0 ${geo.W} ${geo.H}`} aria-label="hotspot 표식">
          {markers.map((m) => {
            const x = geo.sx(m.a);
            const y = geo.sy(m.b);
            return m.kind === "max" ? (
              <g key={m.key} className="mk-max" data-testid="max-marker">
                <circle cx={x} cy={y} r={13} />
                <path d={`M${x - 18},${y}h7M${x + 11},${y}h7M${x},${y - 18}v7M${x},${y + 11}v7`} />
              </g>
            ) : (
              <g key={m.key} className="mk-hot" data-testid="hotspot-marker">
                <circle cx={x} cy={y} r={8.5} />
                <text x={x} y={y} dy="0.34em" textAnchor="middle">
                  {m.label}
                </text>
              </g>
            );
          })}
        </svg>
        {tip && (
          <div className={`ovl-tip${tip.grey ? " grey" : ""}`} role="tooltip" style={{ left: Math.min(tip.x + 14, geo.W - 300), top: tip.y + 14 }}>
            {tip.text}
          </div>
        )}
      </div>
      <div className="legend small" data-testid="ovl-legend">
        {mode === "err" ? (
          <>
            <span>오차 % (ESL − Radioss)/Radioss</span>
            <span className="mono">−{f3(errRange.max)}</span>
            <span className="ramp" style={{ background: gradient(DIVERGING) }} />
            <span className="mono">+{f3(errRange.max)}</span>
          </>
        ) : (
          <>
            <span>ε_eq (Radioss·ESL 공통 범위)</span>
            <span className="mono">{f3(epsRange.min)}</span>
            <span className="ramp" style={{ background: gradient(VIRIDIS) }} />
            <span className="mono">{f3(epsRange.max)}</span>
          </>
        )}
        <span title={Object.values(REASON_LABEL).slice(1).join("\n")}>
          <span className="lg na" /> 비교 불가 <span data-testid="grey-count">{greyCount.toLocaleString()}</span>개
        </span>
        <span>
          <span className="lg hot" /> hotspot 순위
        </span>
        <span>
          <span className="lg max" /> 최대변형률 요소
        </span>
        <span className="muted">
          요소 {d.rad.n_total.toLocaleString()}개{d.rad.decimated ? ` → 격자 다운샘플 ${d.rad.n_returned.toLocaleString()}개` : ""}
        </span>
      </div>
    </div>
  );
}
