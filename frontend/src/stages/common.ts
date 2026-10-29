import { useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { Case, JobType } from "../api/types";
import { NO_PERMISSION } from "../app/AppContext";
import { stepState } from "../shell/StageStepper";

/** 작업 등록 → Case 다시 읽기 */
export function useAction(reload: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run, setError };
}

export const submitJob = (c: Case, jt: JobType, params: Record<string, unknown> = {}) => api.createJob(c.id, jt, params);

/** 주 버튼 비활성 사유(우선순위: 권한 → 실행 중 → 사전조건). step = 화면 단계 1..4(v0.10.0) */
export function blockReason(allowed: boolean, c: Case, step: number, prereq: string | null = null) {
  if (!allowed) return NO_PERMISSION;
  if (stepState(c, step)?.state === "running") return "작업이 진행 중입니다";
  return prereq;
}

export const SUPPORT_BLOCKED_REASON = "② 지지점 자동 선택 실패 — ②에서 사유 확인";
export const TSTAR_NEEDED_REASON = "② t* 확정이 필요합니다";

/** ③ ESL 사전조건(§5.3): 지지 세트 없음 + BLOCKED / 미확정 */
export function eslPrereq(c: Case): string | null {
  if (!c.extract_summary) return "① 추출을 먼저 실행하세요";
  if (c.current_support_set_id && c.tstar) return null;
  if (c.tstar?.support_auto?.status === "BLOCKED") return SUPPORT_BLOCKED_REASON;
  return TSTAR_NEEDED_REASON;
}
