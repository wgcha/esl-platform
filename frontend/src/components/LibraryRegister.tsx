// ④ 검증의 라이브러리 등록(v0.10.0, esl_menu_restructure.md §7.1·§7.2): 변위 기준 PASS(현재 scheme)만 등록.
// FAIL·판정 불가·LEGACY 는 등록 불가 + 사유 한 줄(사유 입력 대화상자 없음). 등록 = 바로 POST, 주 버튼은 ④ 화면이 갖는다.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { EntryOut, ValidationOut } from "../api/types";
import { NO_PERMISSION } from "../app/AppContext";
import { usePolling } from "../lib/usePolling";
import { Badge } from "./ui";
import { statusOf } from "./VerdictStatus";

export const REGISTER_LABEL = "라이브러리에 등록";
export const REG_NOT_PASS = "변위 기준 PASS만 등록할 수 있습니다 — FAIL 사유는 [결과 받기(zip)]로 확인";
export const REG_LEGACY = "현재 기준으로 다시 검증한 뒤 등록하세요";
export const REG_STALE = "이전 입력의 검증입니다 — ④ 검증을 다시 실행한 뒤 등록하세요";

/** 등록 불가 사유(권한 제외). null = 등록 가능 */
export function registerBlock(v: ValidationOut): string | null {
  if (v.stale) return REG_STALE;
  const s = statusOf(v);
  if (s === "LEGACY") return REG_LEGACY;
  if (s !== "PASS") return REG_NOT_PASS;
  return null;
}

/** ④ 화면이 주 버튼을 정하는 데 쓰는 등록 상태: 등록됨(entry)·가능 여부·등록 실행 */
export function useRegistration(projectId: string, v: ValidationOut | null, allowed: boolean) {
  const entries = usePolling(() => (v ? api.libraryEntries({ project_id: projectId, status: "ACTIVE" }) : Promise.resolve(null)), 0, [projectId, v?.esl_run_id]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const done: EntryOut | null = (v && entries.data?.find((e) => e.esl_run_id === v.esl_run_id)) || null;
  const loaded = !!entries.data;
  const reason = v ? registerBlock(v) : null;
  /** 주 버튼을 '라이브러리에 등록'으로: 목록을 읽었고, 미등록이고, PASS(현재 기준)이고, 최신 입력 */
  const canRegister = !!v && loaded && !done && !reason;
  async function register() {
    if (!v) return;
    setBusy(true);
    setError(null);
    try {
      await api.createEntry({ esl_run_id: v.esl_run_id, validation_id: v.id });
      await entries.reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return { done, loaded, reason, canRegister, register, busy, error, permission: allowed ? null : NO_PERMISSION };
}

export type Registration = ReturnType<typeof useRegistration>;

/** 판정 카드 안 표시: 등록됨 · 보기 / 등록 불가 사유 한 줄 */
export function LibraryRegister({ projectId, reg }: { projectId: string; reg: Registration }) {
  if (!reg.loaded) return null;
  if (reg.done)
    return (
      <span className="inline-actions" data-testid="reg-done">
        <Badge kind="info">라이브러리 등록됨</Badge>
        <Link className="small" to={`/p/${projectId}/library`}>
          보기
        </Link>
      </span>
    );
  if (reg.reason)
    return (
      <span className="inline-actions" data-testid="reg-block">
        <span className="primary-wrap" title={reg.reason}>
          <button type="button" className="btn small" disabled>
            {REGISTER_LABEL}
          </button>
        </span>
        <span className="small muted" role="note">
          {reg.reason}
        </span>
      </span>
    );
  return null;
}
