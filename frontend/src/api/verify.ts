// v0.12.0 Radioss 검증 낙하 API·화면 규칙(계약 esl_scx_relay.md §7·§9.3·§10.2 — 기능 B). check:api 가 이 파일의 경로도 openapi 와 대조한다.
// 판단(개선·악화·비슷)·예측 일치는 서버(esl.verify.compare)가 정한다 — 화면은 표시만(PASS/FAIL 없음, Q3 A).
import { API_PREFIX, request } from "./client";
import { shortReason } from "./scx";
import type {
  DoeResultOut, DoeStudyOut, ScxAvail, VerifyDesignOut, VerifyDropCreateOut, VerifyDropIn, VerifyDropOut, VerifyDropPhase, VerifyPlanOut, VerifyResolveIn, VerifyVerdict,
} from "./types";

export const verify = {
  /** 저장 안 함 — 대화상자 씬 목록·제출 건수·예상 시간 */
  plan: (body: VerifyDropIn) => request<VerifyPlanOut>("POST", "/verify-drops/plan", { body }),
  /** 201: 씬마다 verify_drops 행 + VERIFY_DROP(XFER) */
  create: (body: VerifyDropIn) => request<VerifyDropCreateOut>("POST", "/verify-drops", { body }),
  list: (beadDoeId: string) => request<VerifyDropOut[]>("GET", "/verify-drops", { query: { bead_doe_id: beadDoeId } }),
  get: (id: string) => request<VerifyDropOut>("GET", `/verify-drops/${id}`),
  /** SUBMISSION_UNKNOWN 정리: attach(잡 ID 연결 — 서버가 VD_WAIT 부터 새 작업을 자동 큐) · abandon(포기 — [재시도] = 새 attempt) */
  resolve: (id: string, body: VerifyResolveIn) => request<VerifyDropOut>("POST", `/verify-drops/${id}/resolve`, { body }),
  csvUrl: (id: string) => `${API_PREFIX}/verify-drops/${id}/compare.csv`,
};

/** 주 버튼 라벨(대화상자) · 카드 버튼 라벨 */
export const VD_BUTTON = "검증 낙하";
export const VD_START = "검증 낙하 시작";
export const VD_CANCEL_CONFIRM = "SCX 잡도 종료합니다. 취소할까요?";
export const VD_ABANDON_CONFIRM = "SCX 에 잡이 실제로 있으면 중복 실행될 수 있습니다. 포기할까요?";
/** 결과 모름 안내 — 연결하면 서버가 그 잡을 이어서 기다리는 작업을 자동으로 큐(재시도 불필요), 포기하면 [재시도] = 새로 제출 */
export const VD_UNKNOWN_HELP =
  "SCX 화면에서 잡을 확인하세요. 잡이 있으면 ID 를 연결하면 그 잡을 이어서 기다립니다(자동). 잡이 없으면 포기한 뒤 [재시도]로 새로 제출합니다.";

/** 씬별 제외 코드 → 짧은 문구(사유 본문은 서버 reason) */
export const VD_EXCLUDE_LABEL: Record<string, string> = {
  VD_CUMULATIVE_EXCLUDED: "누적 씬",
  VD_ENGINE_MISSING: "엔진 rad 없음",
  VD_INCLUDE_LAYOUT: "include 배치 불가",
  VD_ALREADY_ACTIVE: "진행 중",
  VD_CASE_NOT_READY: "원 Case 준비 안 됨",
};
export const excludeLabel = (code: string) => VD_EXCLUDE_LABEL[code] ?? code;

export const TERMINAL_PHASE: VerifyDropPhase[] = ["DONE", "FAILED", "CANCELED"];
export const isActiveDrop = (d: Pick<VerifyDropOut, "phase">) => !TERMINAL_PHASE.includes(d.phase);
/** 결과 모름(사람 확인) — 자동 진행·재시도 없음 */
export const isUnknown = (d: Pick<VerifyDropOut, "submission">) => d.submission?.state === "UNKNOWN";

/** 씬별 진행 칸(§10.2 단계: 업로드·대기·실행·회수·비교) — phase → 칸 번호 */
export const VD_STAGES = ["업로드", "대기", "실행", "회수", "비교"] as const;
const STAGE_OF: Record<VerifyDropPhase, number> = { PREP: 0, STAGING: 0, SUBMITTED: 1, RUNNING: 2, FETCHED: 3, POST: 4, DONE: 5, FAILED: -1, CANCELED: -1 };
export const PHASE_LABEL: Record<VerifyDropPhase, string> = {
  PREP: "준비",
  STAGING: "올리는 중",
  SUBMITTED: "SCX 대기",
  RUNNING: "실행 중",
  FETCHED: "결과 받는 중",
  POST: "추출·비교",
  DONE: "완료",
  FAILED: "실패",
  CANCELED: "취소됨",
};
/** 칸 상태: done | cur | todo | fail. 실패·취소는 마지막으로 도달한 칸(lastStage)을 fail 로 */
export function stageMarks(phase: VerifyDropPhase, lastStage = 0): ("done" | "cur" | "todo" | "fail")[] {
  const k = STAGE_OF[phase];
  return VD_STAGES.map((_, i) => {
    if (k < 0) return i < lastStage ? "done" : i === lastStage ? "fail" : "todo";
    return i < k ? "done" : i === k ? "cur" : "todo";
  });
}
/** 실패·취소 행이 어디까지 갔는지(SCX 잡 ID·제출 기록으로 추정) */
export function reachedStage(d: Pick<VerifyDropOut, "scx_job_id" | "submission" | "result" | "scx_status">): number {
  if (d.result) return 4;
  if (d.scx_status && /complet/i.test(d.scx_status)) return 3;
  if (d.scx_job_id) return 2;
  if (d.submission) return 1;
  return 0;
}

export const VERDICT_LABEL: Record<VerifyVerdict, string> = { better: "개선", worse: "악화", same: "비슷" };

/** 검증 가능한 안: 서버 plan.designs(best/ 가 남은 안), 없으면 결과 best 1개 */
export function eligibleDesigns(result: DoeResultOut | null | undefined, plan: Pick<VerifyPlanOut, "designs"> | null | undefined): VerifyDesignOut[] {
  if (plan?.designs?.length) return [...plan.designs].sort((a, b) => a.rank - b.rank);
  const best = result?.best?.id;
  if (!best) return [];
  return [{ id: best, rank: result?.ranking.find((r) => r.id === best)?.rank ?? 1 }];
}

/** [검증 낙하] 비활성 사유(§10.2·SR-D-19). null = 활성 */
export function verifyButtonReason(o: {
  allowed: boolean;
  noPermission: string;
  study: Pick<DoeStudyOut, "scenario" | "phase"> | null;
  result: DoeResultOut | null;
  avail: ScxAvail | null;
  availError: string | null;
  designs: VerifyDesignOut[];
  pick: string | null;
  planError: { code: string; message: string } | null;
  isAdmin: boolean;
}): string | null {
  if (!o.allowed) return o.noPermission;
  if (!o.study || !o.result) return "불러오는 중…";
  if (o.study.scenario !== "same") return "검증 낙하는 ① 같은 모델 스터디만 됩니다 — ②③ 은 원 모델에 다른 형상을 넣을 수 없습니다";
  if (o.study.phase !== "DONE") return "스터디가 끝나면 쓸 수 있습니다";
  if (o.availError) return o.availError;
  if (!o.avail) return "SCX 연결 확인 중…";
  if (!o.avail.enabled) return (o.isAdmin ? o.avail.reason : shortReason(o.avail.reason)) || "검증 낙하를 쓸 수 없습니다";
  if (!o.designs.length) return "모핑 사본(best/)이 남은 안이 없습니다";
  if (o.pick && !o.designs.some((d) => d.id === o.pick)) {
    const k = Math.max(...o.designs.map((d) => d.rank));
    return `선택한 안 ${o.pick} 은 모핑 사본이 없습니다 — 순위 1~${k} 안만 검증할 수 있습니다`;
  }
  if (o.planError && (o.planError.code === "VD_NO_SCENES" || o.planError.code === "VD_SCENARIO_UNSUPPORTED")) return o.planError.message;
  return null;
}

/** 비율 표기(소수 3자리) */
export const ratioText = (v: number | null | undefined) => (v === null || v === undefined || !Number.isFinite(v) ? "–" : v.toFixed(3));
/** 지표 값 표기(유효 4자리, 작은 값은 지수) */
export function valText(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  return a !== 0 && (a < 1e-2 || a >= 1e5) ? v.toExponential(3) : Number(v.toPrecision(4)).toString();
}
/** 예상 시간 문구 */
export const hoursText = (h: number | null | undefined) => (h === null || h === undefined || !Number.isFinite(h) ? "–" : h >= 10 ? `${Math.round(h)}` : `${Number(h.toFixed(1))}`);
