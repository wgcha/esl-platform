import { Link } from "react-router-dom";
import type { StageStateName as StageState, StageStatus } from "../api/types";

export const STAGE_NAMES = ["입력", "t*", "지지점", "ESL", "검증", "내보내기"] as const;
const STATE_LABEL: Record<StageState, string> = { none: "없음", running: "실행 중", done: "완료", stale: "이전 단계 변경됨", failed: "실패" };
/** 단계 상태 → 점 색(PhysicsAI .dot 규칙: ok·run·wait·bad·off) */
const DOT: Record<StageState, string> = { none: "off", running: "run", done: "ok", stale: "wait", failed: "bad" };

export function StageStepper({ base, current, status }: { base: string; current: number; status: Record<string, StageStatus> | null | undefined }) {
  return (
    <nav aria-label="단계">
      <ol className="stepper">
        {STAGE_NAMES.map((name, i) => {
          const n = i + 1;
          const st = status?.[String(n)]?.state ?? "none";
          return (
            <li key={n} className={`step ${n === current ? "current" : ""}`}>
              <Link to={`${base}/stage/${n}`} aria-current={n === current ? "step" : undefined}>
                <span className="step-mark">{"①②③④⑤⑥"[i]}</span>
                <span className="step-name">{name}</span>
                <span className={`dot ${DOT[st]}`} title={STATE_LABEL[st]} aria-label={`상태 ${STATE_LABEL[st]}`} data-state={st} />
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
