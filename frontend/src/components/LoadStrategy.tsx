// 하중 선정 전략·목표 기준(esl_opt_run.md §7.4·§10.3): 전략 라디오 A(추천)·B·C(+k), 목표 기준 라디오 절대(추천)·상대.
// 설명 문구는 /opt/settings.method_sources(전략·목표 기준 한 줄). B 는 모드별 후보 수 표시, 세 모드 모두 0 이면 비활성.
import type { DeformMode, LoadStrategy as Strategy, ObjectiveNorm, OptSettingsOut } from "../api/types";
import { MODES, MODE_LABEL, STRATEGY_NAME } from "../api/opt";
import { Badge } from "./ui";

export interface StrategyValue {
  strategy: Strategy;
  /** C 의 k(입력 문자열) */
  k: string;
  norm: ObjectiveNorm;
}

/** k 입력 검사: C 일 때만, 정수 1..max */
export function kProblem(v: StrategyValue, max: number): string | null {
  if (v.strategy !== "C") return null;
  const n = Number(v.k);
  return v.k.trim() !== "" && Number.isInteger(n) && n >= 1 && n <= max ? null : `k 는 1~${max} 정수입니다`;
}

export function LoadStrategy({ value, onChange, settings, modeCounts }: { value: StrategyValue; onChange: (v: StrategyValue) => void; settings: OptSettingsOut; modeCounts: Record<DeformMode, number> }) {
  // 방법·출처 자료가 없을 수 있음(서버 {error}) — 설명 문구만 비우고 선택은 그대로(v0.7.2: 여기서 TypeError → 빈 화면이었음)
  const ms = settings.method_sources;
  const src = { strategies: { A: ms?.strategies?.A ?? "", B: ms?.strategies?.B ?? "", C: ms?.strategies?.C ?? "" }, objective_norms: { abs: ms?.objective_norms?.abs ?? "", rel: ms?.objective_norms?.rel ?? "" } };
  const max = settings.loads?.max_cases ?? 20;
  const nModes = MODES.filter((m) => (modeCounts[m] ?? 0) > 0).length;
  const bOff = nModes === 0;
  const kBad = kProblem(value, max);
  const set = (p: Partial<StrategyValue>) => onChange({ ...value, ...p });
  const modeLine = MODES.map((m) => `${MODE_LABEL[m]} ${modeCounts[m] || "(제외)"}`).join(" · ");
  return (
    <div className="strategy">
      <div role="radiogroup" aria-label="하중 선정 전략" className="radio-rows">
        <label className="radio-row">
          <input type="radio" name="opt-strategy" value="A" checked={value.strategy === "A"} onChange={() => set({ strategy: "A" })} />
          <b>{STRATEGY_NAME.A}</b> <Badge kind="info">추천</Badge>
          <span className="small muted">{src.strategies.A}</span>
        </label>
        <label className="radio-row" title={bOff ? "모드가 분류된 ESL 이 없습니다" : undefined}>
          <input type="radio" name="opt-strategy" value="B" checked={value.strategy === "B"} disabled={bOff} onChange={() => set({ strategy: "B" })} />
          <b>{STRATEGY_NAME.B}</b>
          <span className="small muted">
            {src.strategies.B} · 현재 {nModes}개 ({modeLine})
          </span>
        </label>
        <label className="radio-row">
          <input type="radio" name="opt-strategy" value="C" checked={value.strategy === "C"} onChange={() => set({ strategy: "C" })} />
          <b>{STRATEGY_NAME.C}</b>
          <span className="inline-field">
            k
            <input type="number" aria-label="군집 수 k" min={1} max={max} step={1} value={value.k} disabled={value.strategy !== "C"} aria-invalid={!!kBad} onChange={(e) => set({ k: e.target.value })} />
            <span className="small muted">(1~{max})</span>
          </span>
          <span className="small muted">{src.strategies.C}</span>
        </label>
      </div>
      {kBad && <div className="small error-text">{kBad}</div>}
      <div role="radiogroup" aria-label="목표 기준" className="radio-inline">
        <span className="small muted">목표 기준:</span>
        <label className="radio-row">
          <input type="radio" name="opt-norm" value="abs" checked={value.norm === "abs"} onChange={() => set({ norm: "abs" })} />
          <b>절대</b> <Badge kind="info">추천</Badge>
          <span className="small muted">{src.objective_norms.abs}</span>
        </label>
        <label className="radio-row">
          <input type="radio" name="opt-norm" value="rel" checked={value.norm === "rel"} onChange={() => set({ norm: "rel" })} />
          <b>상대</b>
          <span className="small muted">{src.objective_norms.rel}</span>
        </label>
      </div>
    </div>
  );
}
