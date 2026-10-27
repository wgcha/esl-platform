// ⑤ 겹쳐보기: PCA 평면 요소 중심 컨투어(canvas 2D). 레이어 Radioss ε / ESL ε / 오차 %, 불투명도 슬라이더로
// Radioss 위에 ESL 을 겹친다. 공통 색 범위, 회색 = 비교 불가(사유는 마우스 오버 툴팁), hotspot·최대변형률 표식.
// v0.5.7: 변형률은 판정이 아니라 참고 — "기준 초과 요소"·"소성 영역" 표시 토글, 레전드 범위 편집(ColorLegend), 단면 위치선.
// 시각 규칙은 코어 Case HTML 보고서(esl/report/case_report.py "겹쳐보기")와 같다.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/endpoints";
import type { FieldLayer, FieldOut, FieldSummary, StrainRef, ValidationHotspot } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { DIVERGING, NA_COLOR, VIRIDIS, f3, gradient, lerp } from "../lib/colormap";
import { ColorLegend, autoRange, countOut, useLegendRange } from "./ColorLegend";
import { useWidth } from "./MaxHoldChart";
import { SectionMarks, geometry, pickAt, type Geo, type SectionMap } from "./mapshared";
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

/** 점 색(회색이면 null). range: rad·esl = 공통 [min, max], err = ±R. 범위 밖 값은 끝색(0~1 로 자름) */
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

/** rad·esl 공통 색 범위(예전 서버 대비): 서버 color_range(두 레이어 합친 값) — 없으면 비교 가능 점에서 계산 */
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

/** 오차 색 범위 ±R(예전 서버 대비: color_range, 없으면 1%) */
export function errRangeOf(f: FieldOut): Range {
  const R = Math.max(Math.abs(f.color_range.min ?? 0), Math.abs(f.color_range.max ?? 0)) || 1;
  return { min: -R, max: R };
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

/** flags 비트: 1 = 기준 초과 요소, 2 = 소성 영역(epsp>0) */
export const FLAG_EXCEED = 1;
export const FLAG_PLASTIC = 2;

function drawFlags(cv: HTMLCanvasElement | null, f: FieldOut | undefined, g: Geo | null, exceed: boolean, plastic: boolean) {
  if (!cv || !f || !g || (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent))) return;
  const ctx = cv.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(g.W * dpr);
  cv.height = Math.round(g.H * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, g.W, g.H);
  const w = g.cell;
  for (const p of f.points) {
    const fl = p[5] ?? 0;
    if (plastic && fl & FLAG_PLASTIC) {
      ctx.fillStyle = "#ff2bd6";
      const q = Math.max(1.5, w * 0.36);
      ctx.fillRect(g.sx(p[1]) - q / 2, g.sy(p[2]) - q / 2, q, q);
    }
    if (exceed && fl & FLAG_EXCEED) {
      ctx.strokeStyle = "#000";
      ctx.lineWidth = 1.6;
      ctx.strokeRect(g.sx(p[1]) - w / 2 - 0.5, g.sy(p[2]) - w / 2 - 0.5, w + 1, w + 1);
    }
  }
}

export function FieldOverlay({
  vid,
  hotspots,
  summary,
  strainRef,
  sec,
}: {
  vid: string;
  hotspots: ValidationHotspot[];
  summary: FieldSummary | null | undefined;
  strainRef?: StrainRef | null;
  sec?: SectionMap;
}) {
  const data = usePolling(
    () => Promise.all((["rad", "esl", "err"] as FieldLayer[]).map((l) => api.field(vid, l))).then(([rad, esl, err]) => ({ rad, esl, err })),
    0,
    [vid],
  );
  const [mode, setMode] = useState<Mode>("eps");
  const [op, setOp] = useState(0); // ESL 불투명도 %
  const [showExceed, setShowExceed] = useState(false);
  const [showPlastic, setShowPlastic] = useState(false);
  const [tip, setTip] = useState<{ x: number; y: number; text: string; grey: boolean } | null>(null);
  const { ref, width } = useWidth<HTMLDivElement>(760);
  const c0 = useRef<HTMLCanvasElement>(null);
  const c1 = useRef<HTMLCanvasElement>(null);
  const c2 = useRef<HTMLCanvasElement>(null);
  const d = data.data;

  // 자동 범위 = 서버 color_range_robust(P99), 없으면 예전 color_range. 수동 범위는 레전드 입력(localStorage 기억)
  const autoEps = useMemo(() => (d ? autoRange("minmax", d.rad.color_range_robust, null) ?? rangeOf([d.rad, d.esl]) : { min: 0, max: 1 }), [d]);
  const autoErr = useMemo(() => (d ? autoRange("sym", d.err.color_range_robust, null) ?? errRangeOf(d.err) : { min: -1, max: 1 }), [d]);
  const epsLg = useLegendRange(vid, "field", "eps", "minmax", autoEps);
  const errLg = useLegendRange(vid, "field", "err", "sym", autoErr);
  const epsRange = epsLg.range;
  const errRange = errLg.range;
  const geo = useMemo(() => (d ? geometry(d.rad, width) : null), [d, width]);
  const byId = useMemo(() => {
    const m = new Map<number, { a: number; b: number; rad: number | null; esl: number | null; err: number | null; reason: string; flags: number }>();
    if (!d) return m;
    for (const p of d.rad.points) m.set(p[0], { a: p[1], b: p[2], rad: p[3], esl: null, err: null, reason: p[4], flags: p[5] ?? 0 });
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
  useEffect(() => {
    if (d) drawFlags(c2.current, d.rad, geo, showExceed, showPlastic);
  }, [d, geo, showExceed, showPlastic]);

  // 범위 밖 점 수(끝색으로 칠해진 점): 보이는 레이어의 비교 가능 점
  const out = useMemo(() => {
    if (!d) return { above: 0, below: 0 };
    if (mode === "err")
      return countOut(
        d.err.points.filter((p) => !isGrey("err", p[3], p[4])).map((p) => p[3]),
        errRange,
      );
    const rad = countOut(
      d.rad.points.filter((p) => !isGrey("rad", p[3], p[4])).map((p) => p[3]),
      epsRange,
    );
    const esl = countOut(
      d.esl.points.filter((p) => !isGrey("esl", p[3], p[4])).map((p) => p[3]),
      epsRange,
    );
    return { above: Math.max(rad.above, esl.above), below: Math.max(rad.below, esl.below) };
  }, [d, mode, epsRange, errRange]);

  // 표식: hotspot(순위) + 최대변형률 요소
  const markers = useMemo(() => {
    const o: { key: string; a: number; b: number; label: string; kind: "hot" | "max"; id: number }[] = [];
    const pos = new Map<number, [number, number]>();
    for (const r of [...(summary?.top ?? []), ...(summary?.worst ?? [])]) if (r.xi !== undefined && r.eta !== undefined) pos.set(r.elem_id, [r.xi, r.eta]);
    for (const [id, p] of byId) pos.set(id, [p.a, p.b]);
    hotspots.forEach((h, k) => {
      const p = pos.get(h.elem_id);
      if (p) o.push({ key: `h${h.elem_id}`, a: p[0], b: p[1], label: String(h.rank ?? k + 1), kind: "hot", id: h.elem_id });
    });
    const mx = summary?.max;
    // 최대변형률 표식을 먼저(아래) 그려 hotspot 순위 숫자가 가려지지 않게
    if (mx && mx.xi !== undefined && mx.eta !== undefined) o.unshift({ key: "max", a: mx.xi, b: mx.eta, label: "", kind: "max", id: mx.elem_id });
    return o;
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
  const plasticN = strainRef ? strainRef.plastic?.n_plastic ?? strainRef.n_plastic ?? null : null;

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
      (p.flags & FLAG_EXCEED ? " · 기준 초과" : "") +
      (p.flags & FLAG_PLASTIC ? " · 소성 영역" : "") +
      (grey ? ` · 비교 불가: ${REASON_LABEL[p.reason] ?? p.reason}` : "");
    setTip({ x: mx, y: my, text, grey });
  }

  function onClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!sec || !geo) return;
    const r = e.currentTarget.getBoundingClientRect();
    sec.onPick(pickAt(geo, sec.axis, e.clientX - r.left, e.clientY - r.top));
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
          <input type="range" min={0} max={100} step={5} value={op} disabled={mode === "err"} aria-label="ESL 불투명도" onChange={(e) => setOp(Number(e.target.value))} />
          <span className="small">ESL</span>
          <span className="mono small range-val" data-testid="ovl-op">
            {op}%
          </span>
        </label>
        <label className="check small" title="오차가 compare.max_err_pct_max 를 넘는 요소를 검은 테두리로 표시(참고용)">
          <input type="checkbox" checked={showExceed} onChange={(e) => setShowExceed(e.target.checked)} /> 기준 초과 요소
          {strainRef ? ` ${strainRef.n_exceed.toLocaleString()}개` : ""}
        </label>
        <label className="check small" title="t* 프레임에서 소성 변형률 epsp > 0 인 요소를 자홍색 점으로 표시(참고용)">
          <input type="checkbox" checked={showPlastic} onChange={(e) => setShowPlastic(e.target.checked)} /> 소성 영역(epsp&gt;0)
          {plasticN != null ? ` ${plasticN.toLocaleString()}개` : ""}
        </label>
      </div>
      <div className={`ovl-box${sec ? " pick" : ""}`} style={{ height: geo.H }} onMouseMove={onMove} onMouseLeave={() => setTip(null)} onClick={onClick} data-testid="ovl-box">
        <canvas
          ref={c0}
          style={{ width: geo.W, height: geo.H }}
          aria-label={`${shownLayer === "err" ? "오차" : "Radioss"} 컨투어`}
          data-layer={baseLayer}
          data-range-min={mode === "err" ? errRange.min : epsRange.min}
          data-range-max={mode === "err" ? errRange.max : epsRange.max}
        />
        <canvas
          ref={c1}
          className="ovl-top"
          style={{ width: geo.W, height: geo.H, opacity: mode === "eps" ? op / 100 : 0, visibility: mode === "eps" && op > 0 ? "visible" : "hidden" }}
          aria-label="ESL 컨투어"
          data-testid="ovl-esl"
        />
        <canvas ref={c2} className="ovl-top" style={{ width: geo.W, height: geo.H }} aria-label="참고 표시(기준 초과·소성 영역)" data-testid="ovl-flags" data-exceed={showExceed} data-plastic={showPlastic} />
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
          {sec && <SectionMarks g={geo} sec={sec} />}
        </svg>
        {tip && (
          <div className={`ovl-tip${tip.grey ? " grey" : ""}`} role="tooltip" style={{ left: Math.min(tip.x + 14, geo.W - 300), top: tip.y + 14 }}>
            {tip.text}
          </div>
        )}
      </div>
      <div className="legend small" data-testid="ovl-legend">
        {mode === "err" ? (
          <ColorLegend kind="sym" label="오차 % (ESL − Radioss)/Radioss" range={errRange} manual={errLg.manual} gradient={gradient(DIVERGING)} onApply={errLg.apply} onReset={errLg.reset} above={out.above} below={out.below} />
        ) : (
          <ColorLegend kind="minmax" label="ε_eq (Radioss·ESL 공통 범위)" range={epsRange} manual={epsLg.manual} gradient={gradient(VIRIDIS)} onApply={epsLg.apply} onReset={epsLg.reset} above={out.above} below={out.below} />
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
        {sec && (
          <span>
            <span className="lg sec" /> 단면 위치(지도를 누르면 이동)
          </span>
        )}
        <span className="muted">
          요소 {d.rad.n_total.toLocaleString()}개{d.rad.decimated ? ` → 격자 다운샘플 ${d.rad.n_returned.toLocaleString()}개` : ""}
        </span>
      </div>
    </div>
  );
}
