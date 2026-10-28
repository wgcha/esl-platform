// 컨투어 레전드 범위 편집(계약 esl_disp_primary.md §14.3). 색 띠 끝의 숫자를 입력 칸으로 바꾸고, 새 버튼은 "자동" 하나.
//  - sym    : 변형률 오차 % — 입력 1칸 ±R (R > 0)
//  - zero   : 변위 e/U·‖d_rel‖·‖d_val‖ — 입력 1칸 최대(> 0), 최소 0 고정
//  - minmax : 변형률 rad/esl 공통 범위 — 최소·최대 2칸 (min < max)
// 잘못된 값(비유한·순서 역전·≤0)은 칸에 오류를 표시하고 직전 유효 범위를 유지한다.
// 수동 범위는 localStorage `esl.legend.v1:<validation_id>:<view>:<layer>` 에 {min,max} JSON 으로 기억한다.
// 읽기·쓰기·삭제 모두 try/catch — 저장소를 못 써도 메모리 상태만으로 동작한다(오류 표시 없음).
import { useCallback, useEffect, useState } from "react";
import { f3 } from "../lib/colormap";

export type LegendKind = "sym" | "zero" | "minmax";
export type Range = { min: number; max: number };
export type LegendView = "field" | "disp" | "load";

export const legendKey = (vid: string, view: LegendView, layer: string) => `esl.legend.v1:${vid}:${view}:${layer}`;

/** 종류별 유효 범위 검사 */
export function validRange(kind: LegendKind, r: Range | null | undefined): r is Range {
  if (!r || !Number.isFinite(r.min) || !Number.isFinite(r.max)) return false;
  if (kind === "sym") return r.max > 0 && r.min === -r.max;
  if (kind === "zero") return r.max > 0 && r.min === 0;
  return r.min < r.max;
}

export function readLegend(key: string, kind: LegendKind): Range | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const o = JSON.parse(raw) as { min?: unknown; max?: unknown };
    const r = { min: Number(o.min), max: Number(o.max) };
    return typeof o.min === "number" && typeof o.max === "number" && validRange(kind, r) ? r : null;
  } catch {
    return null;
  }
}

export function writeLegend(key: string, r: Range) {
  try {
    window.localStorage.setItem(key, JSON.stringify({ min: r.min, max: r.max }));
  } catch {
    /* 저장소를 쓸 수 없어도 메모리 상태로 동작 */
  }
}

export function clearLegend(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* 무시 */
  }
}

/** 서버 자동 범위(color_range_robust 우선, 없으면 color_range)를 종류에 맞게 정리 */
export function autoRange(kind: LegendKind, robust: { min?: number | null; max?: number | null } | null | undefined, plain: { min?: number | null; max?: number | null } | null | undefined): Range | null {
  const pick = (src: typeof robust) => {
    if (!src || src.max == null || !Number.isFinite(src.max)) return null;
    if (kind === "sym") {
      const R = Math.max(Math.abs(src.max), Math.abs(src.min ?? 0));
      return R > 0 ? { min: -R, max: R } : null;
    }
    if (kind === "zero") return src.max > 0 ? { min: 0, max: src.max } : null;
    return src.min != null && Number.isFinite(src.min) && src.max > src.min ? { min: src.min, max: src.max } : null;
  };
  return pick(robust) ?? pick(plain);
}

/** 수동 범위(있으면) 또는 자동 범위. 겹쳐보기·변위 컨투어 공통 */
export function useLegendRange(vid: string, view: LegendView, layer: string, kind: LegendKind, auto: Range) {
  const key = legendKey(vid, view, layer);
  const [manual, setManual] = useState<Range | null>(() => readLegend(key, kind));
  useEffect(() => {
    setManual(readLegend(key, kind));
  }, [key, kind]);
  const apply = useCallback(
    (r: Range) => {
      if (!validRange(kind, r)) return;
      setManual(r);
      writeLegend(key, r);
    },
    [key, kind],
  );
  const reset = useCallback(() => {
    setManual(null);
    clearLegend(key);
  }, [key]);
  return { range: manual ?? auto, manual: manual !== null, apply, reset };
}

/** 범위 밖 값 개수(끝색으로 칠해진 점). 최소 미만 / 최대 초과 */
export function countOut(values: Iterable<number | null>, r: Range): { above: number; below: number } {
  let above = 0;
  let below = 0;
  for (const v of values) {
    if (v === null || !Number.isFinite(v)) continue;
    if (v > r.max) above += 1;
    else if (v < r.min) below += 1;
  }
  return { above, below };
}

const toText = (x: number) => (Number.isFinite(x) ? f3(x) : "");

export function NumInput({ label, value, onCommit, testId }: { label: string; value: number; onCommit: (v: number) => boolean; testId?: string }) {
  const [text, setText] = useState(toText(value));
  const [bad, setBad] = useState(false);
  useEffect(() => {
    // 밖(자동·다른 레이어)에서 값이 바뀐 경우만 다시 맞춘다 — 입력 중 형식을 바꾸지 않는다
    if (Number(text) !== value || text === "") {
      setText(toText(value));
      setBad(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input
      type="number"
      step="any"
      className={`lg-input mono${bad ? " bad" : ""}`}
      aria-label={label}
      aria-invalid={bad}
      title={bad ? "유효하지 않은 값 — 직전 범위를 유지합니다" : label}
      data-testid={testId}
      value={text}
      onChange={(e) => {
        const t = e.target.value;
        setText(t);
        const v = t.trim() === "" ? NaN : Number(t);
        setBad(!(Number.isFinite(v) && onCommit(v)));
      }}
    />
  );
}

export interface ColorLegendProps {
  kind: LegendKind;
  /** 색 띠 앞 설명(예: "오차 % (ESL − Radioss)/Radioss") */
  label: string;
  range: Range;
  manual: boolean;
  gradient: string;
  onApply: (r: Range) => void;
  onReset: () => void;
  above?: number;
  below?: number;
  testId?: string;
}

export function ColorLegend({ kind, label, range, manual, gradient, onApply, onReset, above = 0, below = 0, testId = "color-legend" }: ColorLegendProps) {
  return (
    <span className="lg-range" data-testid={testId} data-range-min={range.min} data-range-max={range.max} data-manual={manual}>
      <span>{label}</span>
      {below > 0 && (
        <span className="lg-out" data-testid="lg-below" title={`범위 밖 ${below.toLocaleString()}개`} aria-label={`범위 밖 ${below.toLocaleString()}개 (최소 미만)`}>
          ▼
        </span>
      )}
      {kind === "minmax" ? (
        <NumInput label="범위 최소" value={range.min} onCommit={(v) => (v < range.max ? (onApply({ min: v, max: range.max }), true) : false)} />
      ) : (
        <span className="mono">{kind === "sym" ? "−" : ""}{kind === "sym" ? f3(range.max) : "0"}</span>
      )}
      <span className="ramp" style={{ background: gradient }} />
      {kind === "minmax" ? (
        <NumInput label="범위 최대" value={range.max} onCommit={(v) => (v > range.min ? (onApply({ min: range.min, max: v }), true) : false)} />
      ) : (
        <span className="lg-pm">
          {kind === "sym" && <span className="mono">±</span>}
          <NumInput
            label={kind === "sym" ? "범위 ±R" : "범위 최대"}
            value={range.max}
            onCommit={(v) => (v > 0 ? (onApply(kind === "sym" ? { min: -v, max: v } : { min: 0, max: v }), true) : false)}
          />
        </span>
      )}
      {above > 0 && (
        <span className="lg-out" data-testid="lg-above" title={`범위 밖 ${above.toLocaleString()}개`} aria-label={`범위 밖 ${above.toLocaleString()}개 (최대 초과)`}>
          ▲
        </span>
      )}
      <button type="button" className="btn small ghost" disabled={!manual} onClick={onReset} title="서버의 견고한 자동 범위로 되돌립니다">
        자동
      </button>
    </span>
  );
}
