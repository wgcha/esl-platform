// v0.24.3 ④ 검증 출처별(esl_validate_sources.md §7) 목 데이터 — 서버(mock/server.ts)가 쓴다.
// mode: "old" = 404(옛 서버 — 출처 탭 없이 v0.24.2 화면) · "ok" = 출처 행(full PASS · 경계력 FAIL·비교용 아님 · 내력 PASS ⚠) ·
//       "notrun" = 이 검증에 출처 결과 없음(v0.24.3 이전 검증 — 경계력·내력 탭이 선택 가능한 빈 탭).
import { statusOf } from "../components/VerdictStatus";
import type { ValidationOut, ValidationSourceRow } from "../api/types";

export type ValSourcesMode = "ok" | "old" | "notrun";

const NOT_RUN = "이 검증에는 출처별 결과가 없습니다(v0.24.3 이전 검증) — ④ 검증을 다시 실행하면 생깁니다";
const STUDY_ONLY = "강성 평가 스터디에서만 계산됩니다(Case 산출물 없음)";
const COND = (frame: string, bal: string) => `하중 ${frame} · 지지 3-2-1 · 균형 ${bal} · 목표 u_rel(S3 Kabsch) · 응답 = 검증 풀이`;
export const VAL_SRC_NOTE_RECON = "이 하중으로 정적 풀이한 변위와 Radioss 변위(강체 제거)의 차이 — 하중이 낙하 변형을 얼마나 재현하는지(물리 차이 포함)를 봅니다.";

const blank = (key: string): ValidationSourceRow => ({ key, available: false, code: null, reason: null, status: null, fail_reasons: [], undetermined_reason: null, reaction_role: null, reaction_tol: null, reaction_tol_key: null, reaction_warn: null, reaction_warned: null, cond_text: null, note: null, limits: [], limit_text: [], comparable: null });

/** 검증 v 의 출처 행(KEYS 순서). full = v 자신(DB 기준) */
export function valSourceRows(v: ValidationOut, mode: Exclude<ValSourcesMode, "old">, latest = true, jigRows = false): ValidationSourceRow[] {
  const rows = valSourceRows4(v, mode, latest);
  if (!jigRows) return rows;
  // v0.24.4(esl_jig_case.md §5.5): 지그 3행(KEYS 순서 jig·jig_disp·jig_spring) — jig 고정 PASS · jig_disp PASS ⚠(JIG_DISP_FROM_TARGET) · jig_spring = 이 검증에 없음
  const run = mode === "ok" && latest;
  const jigCond = (val: string) => `하중 지그 맞춤 · 지지 tie 면외(법선) 128 + 3-2-1 면내 3 · 값 ${val} · 목표 u_rel · 응답 = 검증 풀이`;
  const info = { reaction_role: "info" as const, reaction_tol_key: "validation.sources.reaction_tol", note: VAL_SRC_NOTE_RECON };
  const jig: ValidationSourceRow = run ? { ...blank("jig"), available: true, status: "PASS", ...info, cond_text: jigCond("0"), comparable: true } : { ...blank("jig"), code: "VAL_SRC_NOT_RUN", reason: NOT_RUN };
  const disp: ValidationSourceRow = run
    ? { ...blank("jig_disp"), available: true, status: "PASS", ...info, cond_text: jigCond("낙하 변위"), limits: ["JIG_DISP_FROM_TARGET"], limit_text: ["tie 변위를 낙하 결과에서 그대로 강제 — 순수 지그 비교로는 주의"], comparable: true }
    : { ...blank("jig_disp"), code: "VAL_SRC_NOT_RUN", reason: NOT_RUN };
  const spring: ValidationSourceRow = { ...blank("jig_spring"), code: "JIG_NOT_RUN", reason: "이 ESL 결과에는 지그 스프링 계산이 없습니다(v0.24.4 이전 계산) — ESL 을 다시 계산하면 생깁니다" };
  return [jig, disp, spring, ...rows.filter((r) => r.key !== "jig")];
}

function valSourceRows4(v: ValidationOut, mode: Exclude<ValSourcesMode, "old">, latest = true): ValidationSourceRow[] {
  const jig = { ...blank("jig"), code: "V3D_STUDY_ONLY", reason: STUDY_ONLY };
  const full: ValidationSourceRow = { ...blank("full"), available: true, status: statusOf(v), fail_reasons: v.fail_reasons, undetermined_reason: v.undetermined_reason, cond_text: COND("기준 형상 F = K₀·u_rel", "자기평형(구성상)"), comparable: true };
  if (mode === "notrun" || !latest) {
    return [jig, { ...full, cond_text: null, comparable: null }, { ...blank("bforce"), code: "VAL_SRC_NOT_RUN", reason: NOT_RUN }, { ...blank("fint"), code: "VAL_SRC_NOT_RUN", reason: NOT_RUN }];
  }
  const bforce: ValidationSourceRow = {
    ...blank("bforce"), available: true, status: "FAIL", fail_reasons: ["DISP_RMS"], reaction_role: "info", reaction_tol_key: "validation.sources.reaction_tol",
    cond_text: COND("기준 형상 F_ref = Rᵀ·F(낙하 프레임 → S3 Kabsch R)", "관성 이완"), note: VAL_SRC_NOTE_RECON,
    limits: ["BF_TIE_MISSING"], limit_text: ["tie 체결력 미포함 — 조립 부품 하중 누락"], comparable: false,
  };
  const fint: ValidationSourceRow = {
    ...blank("fint"), available: true, status: "PASS", reaction_role: "judge", reaction_tol: 0.1, reaction_tol_key: "validation.sources.reaction_tol", reaction_warn: 0.05, reaction_warned: false,
    cond_text: COND("기준 형상 F_ref = Rᵀ·F(낙하 프레임 → S3 Kabsch R)", "균형 보정 없음 — 불평형은 지지 반력으로"), note: VAL_SRC_NOTE_RECON,
    limits: ["FINT_ROT_LINKS"], limit_text: ["회전 링크 요소 내력 포함"], comparable: true,
  };
  return [jig, full, bforce, fint];
}

/** ?src=<키> 검증 응답: 부모 행 필드 + 출처 판정(목) */
export function valSourceOut(base: ValidationOut, key: string): ValidationOut {
  if (key === "bforce")
    return { ...base, verdict: "FAIL", status: "FAIL", disp_rms_rel: 3.4e-2, disp_max_rel: 7.9e-2, reaction_rel: 1.2e-3, fail_reasons: ["DISP_RMS", "DISP_MAX"], criteria: { ...base.criteria, reaction_role: "info" }, dir_rel: "05_val/bforce" };
  return { ...base, verdict: "PASS", status: "PASS", disp_rms_rel: (base.disp_rms_rel ?? 1e-6) * 1.6, disp_max_rel: (base.disp_max_rel ?? 1e-5) * 1.4, reaction_rel: 3.1e-8, fail_reasons: [], criteria: { ...base.criteria, reaction_role: "judge", ...(key === "fint" ? { reaction_rel_max: 0.1, reaction_warn_rel: 0.05 } : {}) }, dir_rel: `05_val/${key}` };
}
