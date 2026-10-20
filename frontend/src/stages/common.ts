import { useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { Case, JobType } from "../api/types";
import { NO_PERMISSION } from "../app/AppContext";

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

/** 주 버튼 비활성 사유(우선순위: 권한 → 실행 중 → 사전조건) */
export function blockReason(allowed: boolean, c: Case, stage: number, prereq: string | null = null) {
  if (!allowed) return NO_PERMISSION;
  if (c.stage_status?.[String(stage)]?.state === "running") return "작업이 진행 중입니다";
  return prereq;
}
