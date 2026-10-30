// ⑤ 단면선(계약 esl_disp_primary.md §9 D7·§15): 판 길이/폭 방향 단면의 면외 좌표 — 초기 w0, Radioss w0 + k·w_rad, ESL w0 + k·w_esl,
// (v0.5.9: Δw 보조 축 곡선 폐지 — 통계 수치만 텍스트로 유지, §15.6). 단면 위치(at, 0~1)·축·추천은 Stage5 가 쥐고 두 지도(변위 컨투어·겹쳐보기)와 공유한다.
// 배율 k 는 로그 슬라이더(10^0 ~ 10^4). 기본 k 는 최대 면외 변위 × k ≈ 단면 길이의 5% (코어 보고서와 같음).
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { SectionAxis, SectionOut, SectionSuggestKey } from "../api/types";
import { f3 } from "../lib/colormap";
import { sci } from "../lib/format";
import { NumInput } from "./ColorLegend";
import { ticks, useWidth } from "./MaxHoldChart";
import type { SectionMap } from "./mapshared";
import { Empty } from "./ui";

export const AXIS_LABEL: Record<SectionAxis, string> = { eta: "길이 방향 단면", xi: "폭 방향 단면" };
const X_LABEL: Record<SectionAxis, string> = { eta: "판 길이 방향 (mm)", xi: "판 폭 방향 (mm)" };
export const SUGGEST_LABEL: Record<SectionSuggestKey, string> = {
  max_disp_err: "최대 변위 오차 노드 지나는 단면",
  hotspot1: "변형률 hotspot 1위 지나는 단면",
};
export const DEBOUNCE_MS = 200;
const M = { l: 58, r: 14, t: 12, b: 40 };
type Rng = { min: number; max: number };
export type SeriesKey = "init" | "rad" | "esl";
const SERIES_LABEL: Record<SeriesKey, string> = { init: "초기 형상", rad: "Radioss (u_rel)", esl: "ESL (u_val)" };
export const secAxisKey = (vid: string, axis: SectionAxis) => `esl.secaxis.v1:${vid}:${axis}`;
const validR = (r: Rng | null | undefined): r is Rng => !!r && Number.isFinite(r.min) && Number.isFinite(r.max) && r.min < r.max;
function readAxes(key: string): { x: Rng | null; y: Rng | null } {
  try {
    const o = JSON.parse(window.localStorage.getItem(key) ?? "null") as { x?: Rng; y?: Rng } | null;
    const pick = (r: unknown) => (r && typeof (r as Rng).min === "number" && typeof (r as Rng).max === "number" && validR(r as Rng) ? { min: (r as Rng).min, max: (r as Rng).max } : null);
    return { x: pick(o?.x), y: pick(o?.y) };
  } catch {
    return { x: null, y: null };
  }
}
function writeAxes(key: string, v: { x: Rng | null; y: Rng | null }) {
  try {
    if (!v.x && !v.y) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* 저장소를 쓸 수 없어도 메모리 상태로 동작 */
  }
}
const round2 = (v: number) => Math.round(Math.max(0, Math.min(1, v)) * 100) / 100;

export function defaultScaleExp(d: SectionOut): number {
  let wmax = 0;
  for (const v of [...d.w_rad, ...(d.has_val ? d.w_esl : [])]) wmax = Math.max(wmax, Math.abs(v));
  const span = d.s.length ? Math.max(...d.s) - Math.min(...d.s) : 0;
  const k0 = wmax <= 0 || span <= 0 ? 1 : Math.min(Math.max((0.05 * span) / wmax, 1), 1e4);
  return Math.round(Math.log10(k0) * 100) / 100;
}

export type SectionPick = "manual" | SectionSuggestKey;

export interface SectionCtl {
  axis: SectionAxis;
  at: number;
  pick: SectionPick;
  data: SectionOut | null;
  error: string | null;
  setAxis: (a: SectionAxis) => void;
  /** 슬라이더·지도 클릭: 추천은 "직접 지정"으로 돌아간다 */
  setAt: (v: number) => void;
  choose: (p: SectionPick) => void;
  /** 두 지도에 넘기는 값 */
  map: SectionMap;
}

/** 단면 위치 상태 + 요청(디바운스 200 ms, (vid, axis, at 소수 2자리) 캐시, 대기 중에는 직전 그래프 유지) */
export function useSectionCtl(vid: string | null, enabled: boolean): SectionCtl {
  const [axis, setAxisS] = useState<SectionAxis>("eta");
  const [at, setAtS] = useState(0.5);
  const [pick, setPick] = useState<SectionPick>("manual");
  const [data, setData] = useState<SectionOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cache = useRef(new Map<string, SectionOut>());
  const hasData = useRef(false);
  hasData.current = data !== null;

  useEffect(() => {
    cache.current.clear();
    setData(null);
    setError(null);
    setPick("manual");
  }, [vid]);

  useEffect(() => {
    if (!vid || !enabled) return;
    const key = `${vid}|${axis}|${at.toFixed(2)}`;
    const hit = cache.current.get(key);
    if (hit) {
      setData(hit);
      setError(null);
      return;
    }
    let alive = true;
    const t = setTimeout(
      () => {
        api
          .section(vid, axis, Number(at.toFixed(2)))
          .then((r) => {
            cache.current.set(key, r);
            if (alive) {
              setData(r);
              setError(null);
            }
          })
          .catch((e) => alive && setError(errorText(e)));
      },
      hasData.current ? DEBOUNCE_MS : 0,
    );
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [vid, axis, at, enabled]);

  const suggest = data?.suggest ?? [];
  const coord = (key: SectionSuggestKey, a: SectionAxis) => {
    const s = suggest.find((x) => x.key === key);
    return s ? round2(a === "eta" ? s.eta : s.xi) : null;
  };
  const setAxis = useCallback(
    (a: SectionAxis) => {
      setAxisS(a);
      // 추천을 쓰는 중이면 새 축에 맞는 좌표로 다시 적용
      if (pick !== "manual") {
        const c = coord(pick, a);
        if (c !== null) setAtS(c);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pick, data],
  );
  const setAt = useCallback((v: number) => {
    setPick("manual");
    setAtS(round2(v));
  }, []);
  const choose = useCallback(
    (p: SectionPick) => {
      if (p === "manual") return setPick("manual");
      const c = coord(p, axis);
      if (c === null) return;
      setPick(p);
      setAtS(c);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [axis, data],
  );
  return {
    axis,
    at,
    pick,
    data,
    error,
    setAxis,
    setAt,
    choose,
    map: { axis, at, line: data?.line ?? null, lineAt: data ? data.at : null, suggest, onPick: setAt },
  };
}

export function SectionChart({ ctl }: { ctl: SectionCtl }) {
  const { axis, at, pick, data: d, error } = ctl;
  const [kexp, setKexp] = useState<number | null>(null);
  const [real, setReal] = useState(false); // "실제 크기(×1)" — k = 1 고정, 해제하면 직전 k 로 복귀
  const [hidden, setHidden] = useState<SeriesKey[]>([]); // 범례에서 숨긴 계열(최소 1개는 표시)
  const [man, setMan] = useState<{ x: Rng | null; y: Rng | null }>({ x: null, y: null }); // 수동 축 범위(null = 자동)
  const { ref, width: W } = useWidth<HTMLDivElement>(560);
  useEffect(() => {
    if (d && kexp === null) setKexp(defaultScaleExp(d));
  }, [d, kexp]);
  const vid = d?.validation_id ?? null;
  const axKey = vid ? secAxisKey(vid, axis) : null;
  useEffect(() => {
    setMan(axKey ? readAxes(axKey) : { x: null, y: null });
  }, [axKey]);
  const setAx = (which: "x" | "y", r: Rng | null) => {
    const next = { ...man, [which]: r };
    setMan(next);
    if (axKey) writeAxes(axKey, next);
  };
  // 첫 자료가 온 렌더부터 기본 배율을 쓴다(효과로 kexp 를 채우기 전 k = 1 로 한 번 그리면 자동 축 범위·입력 칸이
  // 한 박자 뒤 바뀌어, 그 사이 사용자가 고친 축 입력이 덮어써짐 — 부하 시 vitest V-DP-27·28 간헐 실패 원인)
  const ke = kexp ?? (d ? defaultScaleExp(d) : 0);
  const k = real ? 1 : 10 ** ke;
  const units = d?.units ?? "mm";
  const hasVal = !!d?.has_val;
  const wmax = d?.stats.w_max_abs ?? null;
  const sugg = (key: SectionSuggestKey) => d?.suggest.find((x) => x.key === key);
  const avail: SeriesKey[] = hasVal ? ["init", "rad", "esl"] : ["init", "rad"];
  const shown = avail.filter((x) => !hidden.includes(x));
  const toggle = (key: SeriesKey) => {
    if (hidden.includes(key)) setHidden(hidden.filter((x) => x !== key));
    else if (shown.length > 1) setHidden([...hidden, key]);
  };

  let plot = null;
  let axes: { x: Rng; y: Rng; mx: boolean; my: boolean } | null = null;
  if (d && d.s.length) {
    const H = Math.round(Math.max(220, Math.min(W * 0.5, 340)));
    const all: Record<SeriesKey, number[]> = {
      init: d.w0,
      rad: d.w0.map((v, i) => v + k * d.w_rad[i]),
      esl: hasVal ? d.w0.map((v, i) => v + k * d.w_esl[i]) : [],
    };
    const x0a = Math.min(...d.s);
    const x1a = Math.max(...d.s) || x0a + 1;
    // 자동 범위: 보이는 계열만
    let y0a = Math.min(...shown.flatMap((q) => all[q]));
    let y1a = Math.max(...shown.flatMap((q) => all[q]));
    if (!(y1a > y0a)) (y0a -= 1), (y1a += 1);
    const ma = (y1a - y0a) * 0.08;
    y0a -= ma;
    y1a += ma;
    const xr = validR(man.x) ? man.x : { min: x0a, max: x1a };
    const yr = validR(man.y) ? man.y : { min: y0a, max: y1a };
    axes = { x: xr, y: yr, mx: validR(man.x), my: validR(man.y) };
    const [x0, x1, y0, y1] = [xr.min, xr.max, yr.min, yr.max];
    const sx = (v: number) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
    const sy = (v: number) => H - M.b - ((v - y0) / (y1 - y0)) * (H - M.t - M.b);
    const path = (y: number[]) => d.s.map((s, i) => `${i ? "L" : "M"}${sx(s).toFixed(1)},${sy(y[i]).toFixed(1)}`).join("");
    const clipId = "sec-clip";
    plot = (
      <svg width={W} height={H} role="img" aria-label="단면선">
        <clipPath id={clipId}>
          <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} />
        </clipPath>
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
        <text x={(M.l + W - M.r) / 2} y={H - 6} textAnchor="middle" className="chart-label" data-testid="sec-xlabel">
          {X_LABEL[axis]}
        </text>
        <text textAnchor="middle" className="chart-label" transform={`translate(12 ${(M.t + H - M.b) / 2}) rotate(-90)`}>
          {`면외 n (${units})`}
        </text>
        <g clipPath={`url(#${clipId})`}>
          {shown.includes("init") && <path d={path(all.init)} className="ln-init" data-testid="sec-init" />}
          {shown.includes("rad") && <path d={path(all.rad)} className="ln-rad" data-testid="sec-rad" />}
          {shown.includes("esl") && <path d={path(all.esl)} className="ln-esl" data-testid="sec-esl" />}
        </g>
      </svg>
    );
  }

  const axisRow = (which: "x" | "y", label: string) =>
    axes && (
      <span className="lg-range" data-testid={`sec-ax-${which}`} data-manual={which === "x" ? axes.mx : axes.my}>
        <span>{label}</span>
        <NumInput
          label={`${which.toUpperCase()}축 최소`}
          value={axes[which].min}
          testId={`sec-ax-${which}-min`}
          onCommit={(v) => (v < axes![which].max ? (setAx(which, { min: v, max: axes![which].max }), true) : false)}
        />
        <span>~</span>
        <NumInput
          label={`${which.toUpperCase()}축 최대`}
          value={axes[which].max}
          testId={`sec-ax-${which}-max`}
          onCommit={(v) => (v > axes![which].min ? (setAx(which, { min: axes![which].min, max: v }), true) : false)}
        />
        <button type="button" className="btn small ghost" disabled={!(which === "x" ? axes.mx : axes.my)} onClick={() => setAx(which, null)} aria-label={`${which.toUpperCase()}축 자동`} title="보이는 계열 기준 자동 범위로 되돌립니다">
          자동
        </button>
      </span>
    );

  const st = d?.stats;
  const nz = (v: number | null | undefined) => v !== null && v !== undefined;
  return (
    <div className="ovl" ref={ref}>
      <div className="ctrl-row sec-head" data-testid="sec-head">
        <div className="seg" role="group" aria-label="단면 방향">
          {(["eta", "xi"] as SectionAxis[]).map((a) => (
            <button key={a} type="button" className={axis === a ? "on" : ""} aria-pressed={axis === a} onClick={() => ctl.setAxis(a)}>
              {AXIS_LABEL[a]}
            </button>
          ))}
        </div>
        <select
          aria-label="단면 추천"
          value={pick}
          onChange={(e) => ctl.choose(e.target.value as SectionPick)}
          title="자동으로 고른 위치를 지나는 단면으로 이동합니다"
        >
          <option value="manual">직접 지정</option>
          <option value="max_disp_err" disabled={!sugg("max_disp_err")}>
            {SUGGEST_LABEL.max_disp_err}
          </option>
          <option value="hotspot1" disabled={!sugg("hotspot1")}>
            {SUGGEST_LABEL.hotspot1}
          </option>
        </select>
        <label className="range-field" title={`${axis === "eta" ? "판 폭 방향(η)" : "판 길이 방향(ξ)"} 정규화 위치 0~1 — 지도를 눌러도 바뀝니다`}>
          <span className="small">단면 위치</span>
          <input type="range" min={0} max={1} step={0.01} value={at} aria-label="단면 위치" onChange={(e) => ctl.setAt(Number(e.target.value))} />
          <span className="mono small range-val" data-testid="sec-at">
            {at.toFixed(2)}
          </span>
        </label>
        <button type="button" className={`btn small ghost toggle${real ? " on" : ""}`} aria-pressed={real} onClick={() => setReal((x) => !x)} title="변형 확대 없이 실제 변위 그대로 그립니다">
          실제 크기(×1)
        </button>
        <label className="range-field" title="배율은 화면 표시용이며 값·판정에 영향 없음">
          <span className="small" data-testid="sec-scale-label">
            변형 확대 배율 <span data-testid="sec-k">×{f3(k)}</span> (실제 최대 면외 변위 <span data-testid="sec-wmax">{nz(wmax) ? `${f3(wmax)} ${units}` : "–"}</span>)
          </span>
          <input type="range" min={0} max={4} step={0.01} value={ke} disabled={real} aria-label="변형 확대 배율" onChange={(e) => setKexp(Number(e.target.value))} />
        </label>
      </div>
      {axes && (
        <div className="ctrl-row sec-axes small" data-testid="sec-axes">
          {axisRow("y", `면외 (${units})`)}
          {axisRow("x", "단면 위치")}
        </div>
      )}
      {error ? <div className="error-text">{error}</div> : !d ? <Empty>불러오는 중…</Empty> : plot ?? <Empty>단면 요소 없음</Empty>}
      {d && st && hasVal && nz(st.dw_max_abs) && (
        <div className="small sec-stats" data-testid="sec-stats">
          Δw 최대 {f3(st.dw_max_abs)} {units} (U 대비 {sci(st.dw_max_rel)}) · RMS {f3(st.dw_rms)} {units} (U 대비 {sci(st.dw_rms_rel)}) · 요소 {d.n_elems.toLocaleString()}개
        </div>
      )}
      <div className="legend small" data-testid="sec-legend">
        {avail.map((key) => (
          <button
            key={key}
            type="button"
            className={`lg-item${hidden.includes(key) ? " off" : ""}`}
            aria-pressed={!hidden.includes(key)}
            data-testid={`sec-lg-${key}`}
            onClick={() => toggle(key)}
            title={hidden.includes(key) ? "눌러서 표시" : shown.length > 1 ? "눌러서 숨김" : "최소 1개 계열은 표시해야 합니다"}
          >
            <span className={`lg ln-${key}`} /> {SERIES_LABEL[key]}
          </button>
        ))}
        {pick !== "manual" && sugg(pick) && <span className="muted">추천 {SUGGEST_LABEL[pick]} — {pick === "hotspot1" ? "요소" : "노드"} {sugg(pick)!.id}</span>}
      </div>
    </div>
  );
}
