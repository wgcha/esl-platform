// ⑤ 단면선(계약 esl_disp_primary.md §9 D7·§15): 판 길이/폭 방향 단면의 면외 좌표 — 초기 w0, Radioss w0 + k·w_rad, ESL w0 + k·w_esl,
// 차이 Δw = w_esl − w_rad(배율 없이 실제 단위, 오른쪽 보조 축). 단면 위치(at, 0~1)·축·추천은 Stage5 가 쥐고 두 지도(변위 컨투어·겹쳐보기)와 공유한다.
// 배율 k 는 로그 슬라이더(10^0 ~ 10^4). 기본 k 는 최대 면외 변위 × k ≈ 단면 길이의 5% (코어 보고서와 같음).
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { SectionAxis, SectionOut, SectionSuggestKey } from "../api/types";
import { f3 } from "../lib/colormap";
import { sci } from "../lib/format";
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
const M_DW = 64;
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
  const { ref, width: W } = useWidth<HTMLDivElement>(560);
  useEffect(() => {
    if (d && kexp === null) setKexp(defaultScaleExp(d));
  }, [d, kexp]);
  const ke = kexp ?? 0;
  const k = real ? 1 : 10 ** ke;
  const units = d?.units ?? "mm";
  const hasVal = !!d?.has_val;
  const wmax = d?.stats.w_max_abs ?? null;
  const sugg = (key: SectionSuggestKey) => d?.suggest.find((x) => x.key === key);

  let plot = null;
  if (d && d.s.length) {
    const H = Math.round(Math.max(220, Math.min(W * 0.5, 340)));
    const showDw = hasVal && d.dw.length === d.s.length;
    const mr = showDw ? M_DW : M.r;
    const ys = [d.w0, d.w0.map((v, i) => v + k * d.w_rad[i]), ...(hasVal ? [d.w0.map((v, i) => v + k * d.w_esl[i])] : [])];
    const x0 = Math.min(...d.s);
    const x1 = Math.max(...d.s) || x0 + 1;
    let y0 = Math.min(...ys.flat());
    let y1 = Math.max(...ys.flat());
    if (!(y1 > y0)) (y0 -= 1), (y1 += 1);
    const m = (y1 - y0) * 0.08;
    y0 -= m;
    y1 += m;
    const sx = (v: number) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - mr);
    const sy = (v: number) => H - M.b - ((v - y0) / (y1 - y0)) * (H - M.t - M.b);
    const path = (y: number[], fy = sy) => d.s.map((s, i) => `${i ? "L" : "M"}${sx(s).toFixed(1)},${fy(y[i]).toFixed(1)}`).join("");
    // Δw 보조 축(오른쪽): 0 을 가운데로 대칭
    let dwmax = showDw ? Math.max(...d.dw.map((v) => Math.abs(v))) : 0;
    if (!(dwmax > 0)) dwmax = 1;
    const sdw = (v: number) => H - M.b - ((v + dwmax * 1.1) / (2.2 * dwmax)) * (H - M.t - M.b);
    plot = (
      <svg width={W} height={H} role="img" aria-label="단면선">
        {ticks(y0, y1).map((v) => (
          <g key={`y${v}`}>
            <line x1={M.l} x2={W - mr} y1={sy(v)} y2={sy(v)} className="chart-grid" />
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
        <line className="chart-axis" x1={M.l} x2={W - mr} y1={H - M.b} y2={H - M.b} />
        <line className="chart-axis" x1={M.l} x2={M.l} y1={M.t} y2={H - M.b} />
        <text x={(M.l + W - mr) / 2} y={H - 6} textAnchor="middle" className="chart-label" data-testid="sec-xlabel">
          {X_LABEL[axis]}
        </text>
        <text textAnchor="middle" className="chart-label" transform={`translate(12 ${(M.t + H - M.b) / 2}) rotate(-90)`}>
          {`면외 n (${units})`}
        </text>
        {showDw && (
          <g data-testid="sec-dw-axis">
            <line className="chart-axis" x1={W - mr} x2={W - mr} y1={M.t} y2={H - M.b} />
            {ticks(-dwmax, dwmax, 4).map((v) => (
              <text key={`d${v}`} x={W - mr + 6} y={sdw(v)} dy="0.32em" textAnchor="start" className="chart-tick dw">
                {Math.abs(v) !== 0 && (Math.abs(v) < 1e-3 || Math.abs(v) >= 1e6) ? v.toExponential(1) : f3(v)}
              </text>
            ))}
            <text textAnchor="middle" className="chart-label dw" transform={`translate(${W - 8} ${(M.t + H - M.b) / 2}) rotate(90)`}>
              {`Δw (${units}, ×1)`}
            </text>
          </g>
        )}
        <path d={path(ys[0])} className="ln-init" data-testid="sec-init" />
        <path d={path(ys[1])} className="ln-rad" data-testid="sec-rad" />
        {hasVal && <path d={path(ys[2])} className="ln-esl" data-testid="sec-esl" />}
        {showDw && <path d={path(d.dw, sdw)} className="ln-dw" data-testid="sec-dw" />}
      </svg>
    );
  }

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
      {error ? <div className="error-text">{error}</div> : !d ? <Empty>불러오는 중…</Empty> : plot ?? <Empty>단면 요소 없음</Empty>}
      {d && st && hasVal && nz(st.dw_max_abs) && (
        <div className="small sec-stats" data-testid="sec-stats">
          Δw 최대 {f3(st.dw_max_abs)} {units} (U 대비 {sci(st.dw_max_rel)}) · RMS {f3(st.dw_rms)} {units} (U 대비 {sci(st.dw_rms_rel)}) · 요소 {d.n_elems.toLocaleString()}개
        </div>
      )}
      <div className="legend small">
        <span>
          <span className="lg ln-init" /> 초기
        </span>
        <span>
          <span className="lg ln-rad" /> Radioss (u_rel)
        </span>
        {hasVal && (
          <>
            <span>
              <span className="lg ln-esl" /> ESL (u_val)
            </span>
            <span>
              <span className="lg ln-dw" /> 차이 Δw (오른쪽 축)
            </span>
          </>
        )}
        {pick !== "manual" && sugg(pick) && <span className="muted">추천 {SUGGEST_LABEL[pick]} — {pick === "hotspot1" ? "요소" : "노드"} {sugg(pick)!.id}</span>}
      </div>
    </div>
  );
}
