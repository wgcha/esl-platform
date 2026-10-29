// 케이스 단계 스텝퍼(v0.10.0, esl_menu_restructure.md §4.3·§5.4): ①입력 ②t*·지지점 ③ESL ④검증. 상태 = case.step_status.
import { Link } from "react-router-dom";
import type { Case, StageState, StageStateName as StageStateKey, StepKey } from "../api/types";

export const STEP_NAMES = ["입력", "t*·지지점", "ESL", "검증"] as const;
export const STEP_KEYS: StepKey[] = ["input", "tstar", "esl", "validate"];
export const STEP_MARKS = "①②③④";
export const N_STEPS = STEP_NAMES.length;

/** 옛 단계 번호(1..6, jobs.stage·links.stage) → 새 화면 단계(1..4). ③지지점 → ②, ⑥내보내기 → ④ */
export const STEP_OF_STAGE: Record<number, number> = { 1: 1, 2: 2, 3: 2, 4: 3, 5: 4, 6: 4 };
export const stepOfStage = (stage: number | null | undefined) => (stage != null && STEP_OF_STAGE[stage]) || 1;

export const stepPath = (projectId: string, caseId: string, n: number, query = "") => `/p/${projectId}/c/${caseId}/step/${n}${query ? `?${query.replace(/^\?/, "")}` : ""}`;
export const stepLabel = (n: number) => `${STEP_MARKS[n - 1]} ${STEP_NAMES[n - 1]}`;

/** 화면 단계 상태. step_status 가 없는 예전 서버 응답이면 stage_status 에서 같은 규칙으로 근사(1→input, 2∧3→tstar, 4→esl, 5→validate) */
export function stepState(c: Pick<Case, "step_status" | "stage_status">, n: number): StageState | undefined {
  const k = STEP_KEYS[n - 1];
  if (c.step_status) return c.step_status[k];
  const ss = c.stage_status;
  if (!ss) return undefined;
  if (k === "tstar") {
    const t = ss["2"];
    const s = ss["3"];
    if (t?.state === "done" && s && s.state !== "done") return { ...s, state: s.state === "none" ? "none" : s.state };
    return t;
  }
  return ss[{ input: "1", esl: "4", validate: "5" }[k]];
}

const STATE_LABEL: Record<StageStateKey, string> = { none: "없음", running: "실행 중", done: "완료", stale: "이전 단계 변경됨", failed: "실패" };
/** 단계 상태 → 점 색(PhysicsAI .dot 규칙: ok·run·wait·bad·off) */
const DOT: Record<StageStateKey, string> = { none: "off", running: "run", done: "ok", stale: "wait", failed: "bad" };

export function StageStepper({ base, current, c }: { base: string; current: number; c: Pick<Case, "step_status" | "stage_status"> | null | undefined }) {
  return (
    <nav aria-label="단계">
      <ol className="stepper">
        {STEP_NAMES.map((name, i) => {
          const n = i + 1;
          const s = c ? stepState(c, n) : undefined;
          const st = s?.state ?? "none";
          const tip = s?.reason?.message ? `${STATE_LABEL[st]} — ${s.reason.message}` : STATE_LABEL[st];
          return (
            <li key={n} className={`step ${n === current ? "current" : ""}`}>
              <Link to={`${base}/step/${n}`} aria-current={n === current ? "step" : undefined}>
                <span className="step-mark">{STEP_MARKS[i]}</span>
                <span className="step-name">{name}</span>
                <span className={`dot ${DOT[st]}`} title={tip} aria-label={`상태 ${STATE_LABEL[st]}`} data-state={st} />
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
