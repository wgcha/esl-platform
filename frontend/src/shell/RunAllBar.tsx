// v0.13.0 일괄 실행(계약 esl_run_all.md §8·§9): Case 화면 [일괄 실행]/[이어서 실행] 버튼 + stepper 아래 진행 줄 1줄.
// 단계 점은 기존 StageStepper 4점 그대로 — 진행 줄은 현재 체인 단계(runAllStepOf)를 넘겨 그 점에 테두리 강조만 더한다.
// 화면당 주 버튼(data-primary)은 단계 버튼 1개 — 이 버튼은 Case 메뉴의 Case 단위 실행 버튼(data-run-all)이라 data-primary 를 달지 않는다.
import { useState } from "react";
import { Link } from "react-router-dom";
import { errorText, stopCodeText } from "../api/client";
import { p3 } from "../api/p3";
import type { Case, RunAllError, RunAllOut, StepKey } from "../api/types";
import { NO_PERMISSION } from "../app/AppContext";
import { REGISTER_LABEL } from "../components/LibraryRegister";
import { STEP_KEYS, stepLabel } from "./StageStepper";

export const RUN_ALL_LABEL = "일괄 실행";
export const RESUME_LABEL = "이어서 실행";
export const RUN_ALL_CANCEL_LABEL = "일괄 취소";
export const RUN_ALL_CANCEL_CONFIRM = "일괄 실행을 취소할까요? 일괄 실행이 만든 대기·실행 중 작업도 취소됩니다.";
export const RUN_ALL_BUSY_REASON = "일괄 실행 중";
export const RUN_ALL_ARCHIVED_REASON = "보관된 Case 입니다";
export const RUN_ALL_ALL_DONE_REASON = `모든 단계가 완료되었습니다(PASS) — ④에서 ${REGISTER_LABEL}`;
export const RUN_ALL_DONE_TEXT = `검증 통과 — 결과를 확인하고 [${REGISTER_LABEL}]`;
export const RUN_ALL_CANCELED_TEXT = "일괄 실행 취소됨";
export const RUN_ALL_BADGE = "일괄";

const stepNo = (k: StepKey | null | undefined) => (k ? STEP_KEYS.indexOf(k) + 1 : 0);
export const runAllStepName = (k: StepKey | null | undefined) => (stepNo(k) ? stepLabel(stepNo(k)) : "");

/** 진행 줄이 보이는 체인(없음·superseded 면 null) */
export const visibleRun = (c: Pick<Case, "run_all"> | null | undefined): RunAllOut | null => (c?.run_all && !c.run_all.superseded ? c.run_all : null);

/** StageStepper 강조 단계: RUNNING = cur_step, STOPPED = stop_step, 그 밖 없음 */
export function runAllStepOf(c: Pick<Case, "run_all"> | null | undefined): StepKey | null {
  const r = visibleRun(c);
  if (!r) return null;
  if (r.status === "RUNNING") return r.cur_step;
  if (r.status === "STOPPED") return r.stop_step;
  return null;
}

/** 주 버튼 라벨·시작 단계·비활성 사유(§9) */
export function runAllButton(c: Case, allowed: boolean): { label: string; from: StepKey | null; disabledReason: string | null } {
  const r = c.run_all ?? null;
  const resume = r?.status === "STOPPED" && r.can_resume;
  const label = resume ? RESUME_LABEL : RUN_ALL_LABEL;
  const from = resume ? r!.stop_step : null;
  const ss = c.step_status;
  const allDone = !!ss && STEP_KEYS.every((k) => ss[k]?.state === "done");
  const reason = !allowed
    ? NO_PERMISSION
    : c.status === "ARCHIVED"
      ? RUN_ALL_ARCHIVED_REASON
      : r?.status === "RUNNING"
        ? RUN_ALL_BUSY_REASON
        : allDone && r?.status === "DONE" && r.verdict === "PASS" && !r.superseded
          ? RUN_ALL_ALL_DONE_REASON
          : null;
  return { label, from, disabledReason: reason };
}

/** 시작·이어서·취소 + 오류(버튼과 진행 줄이 같은 상태를 쓴다) */
export function useRunAll(c: Case | null | undefined, reload: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function act(fn: () => Promise<unknown>) {
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
  return {
    busy,
    error,
    start: (from: StepKey | null) => c && act(() => p3.startRunAll(c.id, from)),
    cancel: () => {
      if (!c) return;
      if (typeof window !== "undefined" && !window.confirm(RUN_ALL_CANCEL_CONFIRM)) return;
      void act(() => p3.cancelRunAll(c.id));
    },
  };
}

export function RunAllButton({ c, allowed, ra }: { c: Case; allowed: boolean; ra: ReturnType<typeof useRunAll> }) {
  const b = runAllButton(c, allowed);
  const disabled = !!b.disabledReason || ra.busy;
  return (
    <span className="primary-wrap run-all-wrap" title={b.disabledReason ?? (b.from ? `${runAllStepName(b.from)}부터 이어서 실행` : "①입력 → ②t*·지지점 → ③ESL → ④검증을 이어서 실행(완료 단계는 건너뜀)")}>
      <button type="button" className="btn run-all-btn" data-run-all="true" disabled={disabled} aria-disabled={disabled} onClick={() => void ra.start(b.from)}>
        {ra.busy ? "처리 중…" : b.label}
      </button>
      {b.disabledReason && <span className="sr-only">{b.disabledReason}</span>}
    </span>
  );
}

/** 멈춤 사유 상세(한 줄로 이어 붙임): ② 가드 reasons·지지 problems·누락 단계·실패 코드 */
export function stopDetailText(r: RunAllOut): string {
  const d = (r.stop_reason?.detail ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (Array.isArray(d.reasons)) for (const x of d.reasons) parts.push(typeof x === "string" ? stopCodeText(x) : stopCodeText((x as { code?: string }).code) || String((x as { message?: string }).message ?? ""));
  if (Array.isArray(d.problems)) for (const p of d.problems as { code?: string; message?: string }[]) parts.push(p.message ?? p.code ?? "");
  if (Array.isArray(d.missing)) parts.push(`필요: ${(d.missing as string[]).join(", ")}`);
  if (typeof d.failure_code === "string" && !(r.stop_reason?.message ?? "").includes(d.failure_code)) parts.push(d.failure_code);
  if (typeof d.undetermined_reason === "string" && !(r.stop_reason?.message ?? "").includes(d.undetermined_reason)) parts.push(d.undetermined_reason);
  return parts.filter(Boolean).join(" · ");
}

export const stopMessage = (r: RunAllOut) => r.stop_reason?.message || stopCodeText(r.stop_code);

const JOB_STATE_TEXT: Record<string, string> = { QUEUED: "대기 중", RUNNING: "실행 중" };

/** stepper 바로 아래 진행 줄 1줄. 체인이 없거나 superseded 면 숨김(생성 시 시작 오류만 있으면 그 문구) */
export function RunAllBar({ c, base, allowed, ra, createError }: { c: Case; base: string; allowed: boolean; ra: ReturnType<typeof useRunAll>; createError?: RunAllError | null }) {
  const r = visibleRun(c);
  if (!r) {
    const e = ra.error ?? (createError ? `일괄 실행을 시작하지 못했습니다 — ${createError.message || stopCodeText(createError.code)}` : null);
    if (!e) return null;
    return (
      <div className="run-all-bar bad" role="status" data-testid="run-all-bar" data-status="ERROR">
        <span className="run-all-tag">{RUN_ALL_BADGE}</span>
        <span className="run-all-text">{e}</span>
      </div>
    );
  }
  const projectId = c.project_id;
  let text: string;
  let detail = "";
  let tone = "";
  let tail: JSX.Element | null = null;
  if (r.status === "RUNNING") {
    tone = "run";
    text = `일괄 실행 중 — ${runAllStepName(r.cur_step) || "준비"}${r.cur_job_state ? ` · ${JOB_STATE_TEXT[r.cur_job_state] ?? "처리 중"}` : ""}`;
    tail = allowed ? (
      <button type="button" className="btn small ghost" data-testid="run-all-cancel" disabled={ra.busy} onClick={ra.cancel}>
        {RUN_ALL_CANCEL_LABEL}
      </button>
    ) : null;
  } else if (r.status === "STOPPED") {
    tone = "bad";
    text = `${runAllStepName(r.stop_step)}에서 멈춤 — ${stopMessage(r)}`;
    detail = stopDetailText(r);
    const jobId = (r.stop_reason?.detail as Record<string, unknown> | null | undefined)?.job_id;
    tail = (
      <>
        {typeof jobId === "string" && (
          <Link to={`/p/${projectId}/jobs/${jobId}`} className="run-all-link">
            작업 보기
          </Link>
        )}
        {r.stop_step && (
          <Link to={`${base}/step/${stepNo(r.stop_step)}`} className="run-all-link">
            그 단계로 가기
          </Link>
        )}
        {r.can_resume && <span className="muted small nowrap">고친 뒤 [{RESUME_LABEL}]</span>}
      </>
    );
  } else if (r.status === "DONE") {
    tone = "ok";
    text = r.verdict === "PASS" || !r.verdict ? RUN_ALL_DONE_TEXT : `④ 검증 ${r.verdict}`;
    tail = (
      <Link to={`${base}/step/4`} className="run-all-link">
        ④ 검증 열기
      </Link>
    );
  } else {
    tone = "off";
    text = r.stop_code === "JOB_CANCELED" ? `${RUN_ALL_CANCELED_TEXT} — ${stopCodeText("JOB_CANCELED")}` : RUN_ALL_CANCELED_TEXT;
  }
  const full = detail ? `${text} (${detail})` : text;
  return (
    <div className={`run-all-bar ${tone}`} role="status" data-testid="run-all-bar" data-status={r.status}>
      <span className="run-all-tag">{RUN_ALL_BADGE}</span>
      <span className="run-all-text" title={full}>
        {text}
        {detail && <span className="run-all-detail"> ({detail})</span>}
      </span>
      {ra.error && <span className="error-text small">{ra.error}</span>}
      <span className="run-all-tail">{tail}</span>
    </div>
  );
}

/** 이력 배지 '일괄'(title: 실행자·시각) */
export function RunAllBadge({ who, at }: { who?: string | null; at?: string | null }) {
  return (
    <span className="badge info run-all-badge" data-testid="run-all-badge" title={`일괄 실행으로 생성${who ? ` · ${who}` : ""}${at ? ` · ${at}` : ""}`}>
      {RUN_ALL_BADGE}
    </span>
  );
}
