import { NavLink } from "react-router-dom";
import type { StageStateName as StageState, StageStatus } from "../api/types";

export const STAGE_NAMES = ["입력", "t*", "지지점", "ESL", "검증", "내보내기"] as const;
const STATE_LABEL: Record<StageState, string> = { none: "없음", running: "실행 중", done: "완료", stale: "이전 단계 변경됨", failed: "실패" };

export function StageStepper({ base, current, status }: { base: string; current: number; status: Record<string, StageStatus> | null | undefined }) {
  return (
    <nav className="stepper" aria-label="단계">
      <ol>
        {STAGE_NAMES.map((name, i) => {
          const n = i + 1;
          const st = status?.[String(n)]?.state ?? "none";
          return (
            <li key={n}>
              <NavLink to={`${base}/stage/${n}`} className={n === current ? "step active" : "step"} aria-current={n === current ? "step" : undefined}>
                <span className={`sdot ${st}`} title={STATE_LABEL[st]} aria-label={`상태 ${STATE_LABEL[st]}`} data-state={st} />
                <span className="snum">{"①②③④⑤⑥"[i]}</span>
                <span className="sname">{name}</span>
              </NavLink>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
