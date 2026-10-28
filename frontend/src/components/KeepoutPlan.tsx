// 비드 금지 영역(esl_opt_run.md §7.5·§10.3): SVG 평면도(a,b mm) + 사각형 표. 드래그 ↔ 숫자 동기화, 자동 영역 on/off,
// 세트 불러오기·저장(PUT /opt/keepouts, version 잠금). 평면도 자료 = GET /opt/plan-view(워커 마스크와 같은 함수).
import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { opt } from "../api/opt";
import { ApiError, errorText } from "../api/client";
import type { KeepoutAuto, KeepoutRect, KeepoutSetOut, PlanViewOut, RectCorner, XY } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { dt } from "../lib/format";
import { Empty } from "./ui";

export interface Frame {
  a_range: XY;
  b_range: XY;
}
export interface KeepoutValue {
  rects: KeepoutRect[];
  auto: Required<KeepoutAuto>;
}

export const CORNER_LABEL: Record<RectCorner, string> = { a0b0: "좌하", a1b0: "우하", a0b1: "좌상", a1b1: "우상" };
const CORNERS: RectCorner[] = ["a0b0", "a1b0", "a0b1", "a1b1"];

/** 사각형 → 평면 상자 [a_lo, a_hi, b_lo, b_hi] (mm). 기준 모서리에서 안쪽으로 x·y 떨어진 점을 가까운 꼭지점으로 w×h */
export function rectBox(r: KeepoutRect, f: Frame): [number, number, number, number] {
  const [a0, a1] = f.a_range;
  const [b0, b1] = f.b_range;
  const right = r.corner === "a1b0" || r.corner === "a1b1";
  const top = r.corner === "a0b1" || r.corner === "a1b1";
  const alo = right ? a1 - r.x_mm - r.w_mm : a0 + r.x_mm;
  const blo = top ? b1 - r.y_mm - r.h_mm : b0 + r.y_mm;
  return [alo, alo + r.w_mm, blo, blo + r.h_mm];
}

/** 상자 왼아래(alo, blo)로 옮긴 사각형 — 기준 모서리 유지, X·Y 는 1 mm 반올림·0 이상 */
export function placeRect(r: KeepoutRect, f: Frame, alo: number, blo: number): KeepoutRect {
  const [a0, a1] = f.a_range;
  const [b0, b1] = f.b_range;
  const right = r.corner === "a1b0" || r.corner === "a1b1";
  const top = r.corner === "a0b1" || r.corner === "a1b1";
  const x = right ? a1 - (alo + r.w_mm) : alo - a0;
  const y = top ? b1 - (blo + r.h_mm) : blo - b0;
  return { ...r, x_mm: Math.max(0, Math.round(x)), y_mm: Math.max(0, Math.round(y)) };
}

/** 드래그: 시작 상자에서 (da, db) mm 이동, 대상 경계 안으로 제한 */
export function dragRect(r: KeepoutRect, f: Frame, start: [number, number], da: number, db: number): KeepoutRect {
  const [a0, a1] = f.a_range;
  const [b0, b1] = f.b_range;
  const alo = Math.min(Math.max(a0, start[0] + da), Math.max(a0, a1 - r.w_mm));
  const blo = Math.min(Math.max(b0, start[1] + db), Math.max(b0, b1 - r.h_mm));
  return placeRect(r, f, alo, blo);
}

/** 기준 모서리 바꾸기: 위치는 그대로, X·Y 를 새 모서리 기준으로 */
export function changeCorner(r: KeepoutRect, f: Frame, corner: RectCorner): KeepoutRect {
  const [alo, , blo] = rectBox(r, f);
  return placeRect({ ...r, corner }, f, alo, blo);
}

export function rectProblem(r: KeepoutRect, f: Frame | null): string | null {
  if (!r.name.trim() || r.name.length > 40) return "이름 1~40자";
  if (![r.x_mm, r.y_mm, r.w_mm, r.h_mm].every(Number.isFinite)) return "숫자를 입력하세요";
  if (r.x_mm < 0 || r.y_mm < 0) return "X·Y ≥ 0";
  if (r.w_mm <= 0 || r.h_mm <= 0) return "가로·세로 > 0";
  if (f) {
    const [alo, ahi, blo, bhi] = rectBox(r, f);
    if (ahi <= f.a_range[0] || alo >= f.a_range[1] || bhi <= f.b_range[0] || blo >= f.b_range[1]) return "대상 경계 밖";
  }
  return null;
}

const frameDiff = (a: Frame, b: Frame) => Math.max(...[0, 1].flatMap((i) => [Math.abs(a.a_range[i] - b.a_range[i]), Math.abs(a.b_range[i] - b.b_range[i])]));

// ---------------------------------------------------------------- 평면도
export function KeepoutPlan({ plan, value, onChange, selected, onSelect, readOnly }: { plan: PlanViewOut; value: KeepoutValue; onChange: (v: KeepoutValue) => void; selected: number | null; onSelect: (i: number | null) => void; readOnly?: boolean }) {
  const f = plan.frame;
  const [a0, a1] = f.a_range;
  const [b0, b1] = f.b_range;
  const L = a1 - a0;
  const H = b1 - b0;
  const pad = Math.max(L, H) * 0.035;
  const vb = { x: -pad, y: -pad * 0.6, w: L + pad * 1.6, h: H + pad * 1.9 };
  const X = (a: number) => a - a0;
  const Y = (b: number) => b1 - b;
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ i: number; sx: number; sy: number; start: [number, number] } | null>(null);
  const poly = (pts: XY[]) => `M${pts.map(([a, b]) => `${X(a).toFixed(1)},${Y(b).toFixed(1)}`).join("L")}Z`;
  // 서버 kinds(구멍/가장자리, polygons 와 같은 길이). 없거나 길이가 다르면 구분 없이 한 경로로 칠함
  const k0 = plan.auto_keepout.kinds;
  const kinds = k0 && k0.length === plan.auto_keepout.polygons.length && k0.length > 0 ? k0 : null;
  const autoPath = (k: "hole" | "edge") => plan.auto_keepout.polygons.filter((_, i) => (kinds ? kinds[i] === k : k === "edge")).map(poly).join(" ");
  const showAll = !kinds && (value.auto.hole || value.auto.edge);

  /** 화면 좌표 → 평면 mm (preserveAspectRatio xMidYMid meet) */
  function toPlan(cx: number, cy: number): [number, number] {
    const el = svgRef.current!;
    const r = el.getBoundingClientRect();
    const s = Math.min(r.width / vb.w, r.height / vb.h) || 1;
    const ox = r.left + (r.width - vb.w * s) / 2;
    const oy = r.top + (r.height - vb.h * s) / 2;
    return [(cx - ox) / s + vb.x, (cy - oy) / s + vb.y];
  }
  const setRect = (i: number, r: KeepoutRect) => onChange({ ...value, rects: value.rects.map((x, k) => (k === i ? r : x)) });

  function down(e: MouseEvent, i: number) {
    if (readOnly) return;
    e.preventDefault();
    const [sx, sy] = toPlan(e.clientX, e.clientY);
    const [alo, , blo] = rectBox(value.rects[i], f);
    drag.current = { i, sx, sy, start: [alo, blo] };
    onSelect(i);
  }
  function move(e: MouseEvent) {
    const d = drag.current;
    if (!d) return;
    const [x, y] = toPlan(e.clientX, e.clientY);
    setRect(d.i, dragRect(value.rects[d.i], f, d.start, x - d.sx, -(y - d.sy)));
  }
  const up = () => (drag.current = null);
  function key(e: KeyboardEvent, i: number) {
    if (readOnly) return;
    const step = e.shiftKey ? 10 : 1;
    const dir: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    const d = dir[e.key];
    if (!d) return;
    e.preventDefault();
    const [alo, , blo] = rectBox(value.rects[i], f);
    setRect(i, dragRect(value.rects[i], f, [alo, blo], d[0], d[1]));
  }

  return (
    <svg
      ref={svgRef}
      className="keepout-svg"
      viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
      role="img"
      aria-label="비드 금지 영역 평면도"
      onMouseMove={move}
      onMouseUp={up}
      onMouseLeave={up}
      onMouseDown={(e) => {
        if (e.target === svgRef.current) onSelect(null);
      }}
    >
      <defs>
        <pattern id="ko-hatch" patternUnits="userSpaceOnUse" width={Math.max(L, H) / 120} height={Math.max(L, H) / 120} patternTransform="rotate(45)">
          <rect width="100%" height="100%" className="ko-hatch-bg" />
          <line x1="0" y1="0" x2="0" y2={Math.max(L, H) / 120} className="ko-hatch-line" strokeWidth={Math.max(L, H) / 400} />
        </pattern>
      </defs>
      <path d={poly(plan.outline)} className="ko-outline" />
      <g className="ko-points" aria-hidden="true">
        {plan.elems.points.map(([a, b, pid], i) => (
          <circle key={i} cx={X(a)} cy={Y(b)} r={Math.max(L, H) / 700} className={pid % 2 ? "p1" : "p2"} />
        ))}
      </g>
      {(value.auto.edge || showAll) && <path d={showAll ? plan.auto_keepout.polygons.map(poly).join(" ") : autoPath("edge")} fillRule="evenodd" className="ko-auto" data-testid="ko-auto-edge" />}
      {value.auto.hole && kinds && <path d={autoPath("hole")} fillRule="evenodd" className="ko-auto" data-testid="ko-auto-hole" />}
      {plan.holes.map((h, i) => (
        <path key={i} d={poly(h)} className="ko-hole" />
      ))}
      {value.rects.map((r, i) => {
        const [alo, ahi, blo, bhi] = rectBox(r, f);
        const w = Math.max(0, ahi - alo);
        const h = Math.max(0, bhi - blo);
        return (
          <g key={i} className={`ko-rect${selected === i ? " on" : ""}`} data-testid={`ko-rect-${i}`} tabIndex={readOnly ? -1 : 0} role="button" aria-label={`${r.name} 사각형 (방향키로 이동)`} onMouseDown={(e) => down(e, i)} onKeyDown={(e) => key(e, i)} onFocus={() => onSelect(i)}>
            <rect x={X(alo)} y={Y(bhi)} width={w} height={h} />
            <text x={X(alo) + w / 2} y={Y(bhi) + h / 2} textAnchor="middle" dominantBaseline="middle" fontSize={Math.max(L, H) / 60}>
              {r.name}
            </text>
          </g>
        );
      })}
      <g className="ko-axis" fontSize={Math.max(L, H) / 75}>
        <text x={0} y={H + pad * 0.9} textAnchor="start">
          0
        </text>
        <text x={L} y={H + pad * 0.9} textAnchor="end">
          {Math.round(L)} mm (ξ)
        </text>
        <text x={-pad * 0.15} y={0} textAnchor="end" dominantBaseline="hanging">
          {Math.round(H)}
        </text>
        <text x={-pad * 0.15} y={H} textAnchor="end">
          0 (η)
        </text>
      </g>
    </svg>
  );
}

// ---------------------------------------------------------------- 사각형 표
export function RectTable({ value, onChange, frame, selected, onSelect, maxRects, readOnly }: { value: KeepoutValue; onChange: (v: KeepoutValue) => void; frame: Frame | null; selected: number | null; onSelect: (i: number | null) => void; maxRects: number; readOnly?: boolean }) {
  const rects = value.rects;
  const set = (i: number, r: KeepoutRect) => onChange({ ...value, rects: rects.map((x, k) => (k === i ? r : x)) });
  const num = (v: string) => (v.trim() === "" ? NaN : Number(v));
  const add = () => {
    let n = rects.length + 1;
    while (rects.some((r) => r.name === `영역${n}`)) n += 1;
    onChange({ ...value, rects: [...rects, { name: `영역${n}`, corner: "a0b0", x_mm: 100, y_mm: 100, w_mm: 200, h_mm: 150 }] });
    onSelect(rects.length);
  };
  return (
    <div className="ko-table">
      <table className="table compact" aria-label="금지 사각형">
        <thead>
          <tr>
            <th>이름</th>
            <th>기준 모서리</th>
            <th className="num">X</th>
            <th className="num">Y</th>
            <th className="num">가로</th>
            <th className="num">세로</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rects.length === 0 && (
            <tr>
              <td colSpan={7} className="muted small">
                사각형 없음 — 자동 영역만 적용
              </td>
            </tr>
          )}
          {rects.map((r, i) => {
            const bad = rectProblem(r, frame);
            const n = (k: "x_mm" | "y_mm" | "w_mm" | "h_mm", label: string) => (
              <td className="num">
                <input type="number" aria-label={`${r.name} ${label}`} step={1} min={k === "w_mm" || k === "h_mm" ? 1 : 0} value={Number.isFinite(r[k]) ? r[k] : ""} disabled={readOnly} aria-invalid={!!bad} onFocus={() => onSelect(i)} onChange={(e) => set(i, { ...r, [k]: num(e.target.value) })} />
              </td>
            );
            return (
              <tr key={i} className={selected === i ? "hl" : undefined} title={bad ?? undefined}>
                <td>
                  <input aria-label={`사각형 ${i + 1} 이름`} className="ko-name" maxLength={40} value={r.name} disabled={readOnly} onFocus={() => onSelect(i)} onChange={(e) => set(i, { ...r, name: e.target.value })} />
                </td>
                <td>
                  <select aria-label={`${r.name} 기준 모서리`} value={r.corner} disabled={readOnly} onChange={(e) => set(i, frame ? changeCorner(r, frame, e.target.value as RectCorner) : { ...r, corner: e.target.value as RectCorner })}>
                    {CORNERS.map((c) => (
                      <option key={c} value={c}>
                        {CORNER_LABEL[c]}
                      </option>
                    ))}
                  </select>
                </td>
                {n("x_mm", "X")}
                {n("y_mm", "Y")}
                {n("w_mm", "가로")}
                {n("h_mm", "세로")}
                <td>
                  <button
                    type="button"
                    className="btn small ghost"
                    disabled={readOnly}
                    onClick={() => {
                      onChange({ ...value, rects: rects.filter((_, k) => k !== i) });
                      onSelect(null);
                    }}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="inline-actions">
        <button type="button" className="btn small" disabled={readOnly || rects.length >= maxRects} title={rects.length >= maxRects ? `최대 ${maxRects}개` : undefined} onClick={add}>
          ＋사각형
        </button>
        <span className="small muted">mm · 기준 모서리에서 안쪽으로 X·Y</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 카드 본문(불러오기·저장 포함)
export interface KeepoutSource {
  /** 평면도 자료 */
  plan: { entry_id?: string; template_id?: string };
  /** 세트 키 */
  set: { topo?: string; template_id?: string };
  saveLabel: string;
}

/** 금지 영역 편집기: 평면도 + 표 + 자동 on/off + 세트 불러오기/저장. value 는 부모가 갖고(실행 스냅샷), 세트를 불러오면 onChange 로 채운다 */
export function KeepoutEditor({ src, value, onChange, auto, maxRects, allowed, onProblem }: {
  src: KeepoutSource;
  value: KeepoutValue;
  onChange: (v: KeepoutValue) => void;
  auto: { hole_radius_mm: number; edge_band_mm: number };
  maxRects: number;
  allowed: boolean;
  /** 사각형 값 문제(실행 버튼 비활성 사유) */
  onProblem?: (p: string | null) => void;
}) {
  const planKey = JSON.stringify(src.plan);
  const setKey = JSON.stringify(src.set);
  const plan = usePolling(() => opt.planView(src.plan), 0, [planKey]);
  const [saved, setSaved] = useState<KeepoutSetOut | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "bad" | "warn"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const frame = plan.data?.frame ?? null;

  useEffect(() => {
    let alive = true;
    setMsg(null);
    setSaved(null);
    opt
      .keepouts(src.set)
      .then((s) => {
        if (!alive) return;
        setSaved(s);
        onChange({ rects: s.rects, auto: s.auto });
        setLoadedKey(setKey);
      })
      .catch((e) => {
        if (!alive) return;
        if (!(e instanceof ApiError && e.status === 404)) setMsg({ kind: "bad", text: errorText(e) });
        onChange({ rects: [], auto: { hole: true, edge: true } });
        setLoadedKey(setKey);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setKey]);

  const problem = value.rects.map((r) => rectProblem(r, frame)).find((p) => p) ?? null;
  const firstBad = value.rects.find((r) => rectProblem(r, frame));
  const problemText = problem && firstBad ? `금지 사각형 '${firstBad.name || "?"}': ${problem}` : null;
  useEffect(() => onProblem?.(problemText), [problemText, onProblem]);

  const moved = saved && frame && frameDiff(saved.frame, frame) >= 1;

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      const out = await opt.putKeepouts({ ...(src.set.topo ? { topo_sha256: src.set.topo } : { template_id: src.set.template_id }), version: saved?.version ?? null, rects: value.rects, auto: value.auto });
      setSaved(out);
      setMsg({ kind: "ok", text: "저장했습니다 — 다음 실행에서 자동으로 불러옵니다" });
    } catch (e) {
      setMsg({ kind: "bad", text: e instanceof ApiError && e.code === "VERSION_CONFLICT" ? "다른 사용자가 먼저 저장했습니다 — 화면을 새로 고쳐 최신 세트를 불러온 뒤 다시 저장하세요" : errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ko-grid" data-testid="keepout-editor">
      <div className="ko-plan">
        {plan.data ? (
          <KeepoutPlan plan={plan.data} value={value} onChange={onChange} selected={selected} onSelect={setSelected} readOnly={loadedKey !== setKey} />
        ) : (
          <Empty>{plan.error ?? "평면도 불러오는 중…"}</Empty>
        )}
        {plan.data?.elems.decimated && <div className="small muted">요소 {plan.data.elems.n_total.toLocaleString()}개 중 일부만 점으로 표시 · 회색 빗금 = 자동 금지 · 주황 = 사각형(드래그·방향키로 이동)</div>}
      </div>
      <div className="ko-side">
        <div className="checks">
          <span className="small muted">자동:</span>
          <label className="check small">
            <input type="checkbox" checked={value.auto.hole} onChange={(e) => onChange({ ...value, auto: { ...value.auto, hole: e.target.checked } })} /> 구멍 주변 {auto.hole_radius_mm} mm
          </label>
          <label className="check small">
            <input type="checkbox" checked={value.auto.edge} onChange={(e) => onChange({ ...value, auto: { ...value.auto, edge: e.target.checked } })} /> 가장자리 {auto.edge_band_mm} mm
          </label>
          <span className="small muted">(설정값)</span>
        </div>
        <RectTable value={value} onChange={onChange} frame={frame} selected={selected} onSelect={setSelected} maxRects={maxRects} />
        {problemText && <div className="small error-text">{problemText}</div>}
        <div className="inline-actions ko-save">
          <span className="small muted" data-testid="keepout-status">
            {loadedKey !== setKey ? "세트 확인 중…" : saved ? `저장된 세트 불러옴(${dt(saved.updated_at)} ${saved.updated_by_name})` : "저장된 세트 없음"}
          </span>
          <span className="spacer" />
          <span className="primary-wrap" title={!allowed ? "권한이 없습니다" : problemText ?? undefined}>
            <button type="button" className="btn small" disabled={!allowed || busy || !!problemText || loadedKey !== setKey} onClick={save}>
              {src.saveLabel}
            </button>
          </span>
        </div>
        {moved && <div className="small warn-text">모델 경계가 달라짐 — 사각형 위치를 확인하세요</div>}
        {msg && (
          <div className={`small ${msg.kind === "ok" ? "ok-text" : msg.kind === "warn" ? "warn-text" : "error-text"}`} role={msg.kind === "bad" ? "alert" : "status"}>
            {msg.text}
          </div>
        )}
      </div>
    </div>
  );
}
