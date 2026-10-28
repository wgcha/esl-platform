// ⑤ 변위 컨투어(전 노드, 계약 esl_disp_primary.md §9·§14·§15): PCA 평면(판 길이 방향 × 판 폭 방향) 노드 컨투어.
// 레이어 = 오차 e/U(ESL − Radioss, 미소 강체 제거 후) · Radioss ‖d_rel‖ · ESL ‖d_val‖. 3-2-1 지지 노드는 원으로 표시.
// 값은 모두 0 이상 — 색 범위는 [0, 최대](자동 = 서버 color_range_robust P99, 수동 = 레전드 입력). 범위 밖은 끝색 + ▲.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/endpoints";
import type { DispFieldOut, DispLayer, DispSummary } from "../api/types";
import { VIRIDIS, f3, gradient, lerp } from "../lib/colormap";
import { usePolling } from "../lib/usePolling";
import { ColorLegend, autoRange, countOut, useLegendRange } from "./ColorLegend";
import { useWidth } from "./MaxHoldChart";
import { SectionMarks, geometry, pickAt, type Geo, type SectionMap } from "./mapshared";
import { Empty } from "./ui";

export const DISP_LAYER_LABEL: Record<DispLayer, string> = {
  err: "오차 e/U",
  rel: "Radioss u_rel",
  val: "ESL u_val",
};

const LEGEND_LABEL: Record<DispLayer, string> = {
  err: "e/U — |ESL − Radioss| ÷ U (미소 강체 제거 후)",
  rel: "‖d_rel‖ Radioss 변위 크기 (mm)",
  val: "‖d_val‖ ESL 변위 크기 (mm)",
};

/** 값 → 색(0..max 선형). 범위 밖은 끝색 */
export function dispColor(value: number, range: { min: number; max: number }): string {
  return lerp(VIRIDIS, (value - range.min) / (range.max - range.min || 1));
}

function draw(cv: HTMLCanvasElement | null, f: DispFieldOut | undefined, range: { min: number; max: number }, g: Geo | null) {
  if (!cv || !f || !g || (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent))) return;
  const ctx = cv.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(g.W * dpr);
  cv.height = Math.round(g.H * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, g.W, g.H);
  const w = g.cell;
  for (const [, a, b, v] of f.points) {
    ctx.fillStyle = dispColor(v, range);
    ctx.fillRect(g.sx(a) - w / 2, g.sy(b) - w / 2, w, w);
  }
}

export function DispOverlay({ vid, disp, sec }: { vid: string; disp: DispSummary; sec?: SectionMap }) {
  const data = usePolling(
    () => Promise.all((["err", "rel", "val"] as DispLayer[]).map((l) => api.dispField(vid, l))).then(([err, rel, val]) => ({ err, rel, val })),
    0,
    [vid],
  );
  const [layer, setLayer] = useState<DispLayer>("err");
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const { ref, width } = useWidth<HTMLDivElement>(760);
  const cv = useRef<HTMLCanvasElement>(null);
  const d = data.data;

  const autoOf = (l: DispLayer): { min: number; max: number } => {
    const f = d?.[l];
    return (f && autoRange("zero", f.color_range_robust, f.color_range)) || { min: 0, max: 1 };
  };
  // 훅은 항상 같은 순서로(레이어마다 자기 키로 기억)
  const lgErr = useLegendRange(vid, "disp", "err", "zero", useMemo(() => autoOf("err"), [d])); // eslint-disable-line react-hooks/exhaustive-deps
  const lgRel = useLegendRange(vid, "disp", "rel", "zero", useMemo(() => autoOf("rel"), [d])); // eslint-disable-line react-hooks/exhaustive-deps
  const lgVal = useLegendRange(vid, "disp", "val", "zero", useMemo(() => autoOf("val"), [d])); // eslint-disable-line react-hooks/exhaustive-deps
  const lg = layer === "err" ? lgErr : layer === "rel" ? lgRel : lgVal;
  const range = lg.range;
  const geo = useMemo(() => (d ? geometry(d.err, width) : null), [d, width]);
  const f = d?.[layer];

  useEffect(() => {
    draw(cv.current, f, range, geo);
  }, [f, range, geo]);

  const byId = useMemo(() => {
    const m = new Map<number, { a: number; b: number; err: number; rel: number; val: number; sup: boolean }>();
    if (!d) return m;
    for (const p of d.err.points) m.set(p[0], { a: p[1], b: p[2], err: p[3], rel: NaN, val: NaN, sup: !!p[4] });
    for (const p of d.rel.points) {
      const x = m.get(p[0]);
      if (x) x.rel = p[3];
    }
    for (const p of d.val.points) {
      const x = m.get(p[0]);
      if (x) x.val = p[3];
    }
    return m;
  }, [d]);

  const out = useMemo(() => (f ? countOut(f.points.map((p) => p[3]), range) : { above: 0, below: 0 }), [f, range]);
  const supports = useMemo(() => (f ? f.points.filter((p) => !!p[4]).slice(0, 64) : []), [f]);

  if (data.error || !d || !geo || !f)
    return (
      <div className="ovl" ref={ref}>
        {data.error ? <div className="error-text">{data.error}</div> : <Empty>변위 컨투어 불러오는 중…</Empty>}
      </div>
    );

  const top = disp.top[0];

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!geo) return;
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
    setTip({ x: mx, y: my, text: `노드 ${best} · e/U ${f3(p.err)} · ‖d_rel‖ ${f3(p.rel)} · ‖d_val‖ ${f3(p.val)}${p.sup ? " · 3-2-1 지지 노드" : ""}` });
  }

  function onClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!sec || !geo) return;
    const r = e.currentTarget.getBoundingClientRect();
    sec.onPick(pickAt(geo, sec.axis, e.clientX - r.left, e.clientY - r.top, sec.line));
  }

  return (
    <div className="ovl" ref={ref}>
      <div className="ctrl-row">
        <div className="seg" role="group" aria-label="변위 레이어">
          {(["err", "rel", "val"] as DispLayer[]).map((l) => (
            <button key={l} type="button" className={layer === l ? "on" : ""} aria-pressed={layer === l} onClick={() => setLayer(l)}>
              {DISP_LAYER_LABEL[l]}
            </button>
          ))}
        </div>
        <span className="small muted">
          U = {f3(disp.U)} mm (Radioss 최대 변위) · 노드 {d.err.n_total.toLocaleString()}개{d.err.decimated ? ` → 격자 다운샘플 ${d.err.n_returned.toLocaleString()}개(셀 대표 = e 최대 노드)` : ""}
        </span>
      </div>
      <div className={`ovl-box${sec ? " pick" : ""}`} style={{ height: geo.H }} onMouseMove={onMove} onMouseLeave={() => setTip(null)} onClick={onClick} data-testid="disp-box">
        <canvas
          ref={cv}
          style={{ width: geo.W, height: geo.H }}
          aria-label={`변위 컨투어 — ${DISP_LAYER_LABEL[layer]}`}
          data-layer={layer}
          data-range-min={range.min}
          data-range-max={range.max}
          data-testid="disp-canvas"
        />
        <svg className="overlay" viewBox={`0 0 ${geo.W} ${geo.H}`} aria-label="지지 노드·최대 노드 표식">
          {supports.map((p) => (
            <g key={p[0]} className="mk-support" data-testid="support-marker">
              <circle cx={geo.sx(p[1])} cy={geo.sy(p[2])} r={6} />
              <title>{`3-2-1 지지 노드 ${p[0]}`}</title>
            </g>
          ))}
          {top && (
            <g className="mk-max" data-testid="disp-max-marker">
              <circle cx={geo.sx(top.a)} cy={geo.sy(top.b)} r={13} />
              <path d={`M${geo.sx(top.a) - 18},${geo.sy(top.b)}h7M${geo.sx(top.a) + 11},${geo.sy(top.b)}h7M${geo.sx(top.a)},${geo.sy(top.b) - 18}v7M${geo.sx(top.a)},${geo.sy(top.b) + 11}v7`} />
              <title>{`e 최대 노드 ${top.node_id}`}</title>
            </g>
          )}
          {sec && <SectionMarks g={geo} sec={sec} />}
        </svg>
        {tip && (
          <div className="ovl-tip" role="tooltip" style={{ left: Math.min(tip.x + 14, geo.W - 300), top: tip.y + 14 }}>
            {tip.text}
          </div>
        )}
      </div>
      <div className="legend small" data-testid="disp-legend">
        <ColorLegend
          kind="zero"
          label={LEGEND_LABEL[layer]}
          range={range}
          manual={lg.manual}
          gradient={gradient(VIRIDIS)}
          onApply={lg.apply}
          onReset={lg.reset}
          above={out.above}
          below={out.below}
          testId="disp-color-legend"
        />
        <span>
          <span className="lg support" /> 3-2-1 지지 노드 {disp.n_support}개
        </span>
        <span>
          <span className="lg max" /> e 최대 노드
        </span>
        {sec && (
          <span>
            <span className="lg sec" /> 단면 위치(지도를 누르면 이동)
          </span>
        )}
      </div>
    </div>
  );
}
