// 판정 상태 표시(계약 esl_disp_primary.md §3.3·§9): PASS(ok) · FAIL(bad) · 판정 불가(중립) · 이전 판정 체계(중립, 당시 PASS|FAIL).
// scheme 이 없으면 LEGACY — 저장값이 아니라 표시 상태다. 검증 화면·이력·라이브러리가 함께 쓴다.
import type { ValidationOut, ValidationStatus } from "../api/types";
import { Badge } from "./ui";

export const STATUS_LABEL: Record<ValidationStatus, string> = {
  PASS: "PASS",
  FAIL: "FAIL",
  UNDETERMINED: "판정 불가",
  LEGACY: "이전 판정 체계",
};

type StatusLike = { status?: ValidationStatus | null; scheme?: string | null; verdict?: string | null };

/** 표시 상태. status 가 있으면 그대로, 없으면(예전 서버) scheme 유무로 */
export function statusOf(v: StatusLike): ValidationStatus {
  if (v.status) return v.status;
  if (!v.scheme) return "LEGACY";
  return v.verdict === "PASS" || v.verdict === "FAIL" || v.verdict === "UNDETERMINED" ? v.verdict : "FAIL";
}

/** 라이브러리 항목 상태(esl_disp_primary.md §7): quality.scheme 없음 = LEGACY, 아니면 quality.status(없으면 quality.verdict) */
export function entryStatus(q: { scheme?: string | null; status?: ValidationStatus | null; verdict?: string | null }): ValidationStatus {
  if (!q.scheme) return "LEGACY";
  return statusOf({ status: q.status, scheme: q.scheme, verdict: q.verdict });
}

export function StatusBadge({ v }: { v: StatusLike }) {
  const s = statusOf(v);
  if (s === "PASS") return <Badge kind="ok">PASS</Badge>;
  if (s === "FAIL") return <Badge kind="bad">FAIL</Badge>;
  if (s === "UNDETERMINED") return <span className="badge neutral">판정 불가</span>;
  return (
    <span className="inline-actions" data-testid="legacy-badge">
      <span className="badge neutral">이전 판정 체계</span>
      {v.verdict && <span className="small muted">당시 {v.verdict}</span>}
    </span>
  );
}

export const critText = (x: unknown) => (typeof x === "number" ? String(x) : Array.isArray(x) ? x.join(",") : x == null ? "–" : String(x));

/** 판정 불가 사유 한 줄 */
export function undeterminedText(v: Pick<ValidationOut, "undetermined_reason" | "criteria">): string {
  const fs = v.criteria?.full_solve;
  switch (v.undetermined_reason) {
    case "NO_FULL_SOLVE":
      return `전체 재해석 생략(full_solve=${critText(fs)}) — 변위 비교가 없어 판정하지 않음`;
    case "ZERO_DISP":
      return "변형이 없어(U = 0) 상대 변위 오차를 정의할 수 없어 판정하지 않음";
    default:
      return `판정 불가${v.undetermined_reason ? ` — ${v.undetermined_reason}` : ""}`;
  }
}
