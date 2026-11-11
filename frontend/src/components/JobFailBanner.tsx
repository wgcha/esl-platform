// v0.15.1 작업 상태가 화면에서 사라지지 않게: 실패 배너(단계명·사유 코드·사용자 문구·[로그 보기]) · 진행 줄(단계 k/N) · 로그 tail.
// 실패 배너는 최신 작업이 실패·취소·중단인 동안 계속 보인다(폴링·phase 변화로 사라지지 않음 — 다음 작업이 시작돼야 바뀜).
import { useEffect, useState } from "react";
import { api } from "../api/endpoints";
import { errorText, failureHint } from "../api/client";
import { JOB_TYPE_LABEL, STEP_LABEL } from "../api/history";
import { warnText } from "../api/doe";
import type { JobOut } from "../api/types";
import { BlockErr, msgHead } from "./MsgFold";

const FAILED_STATES = ["FAILED", "CANCELED", "INTERRUPTED"];
const STATE_NAME: Record<string, string> = { FAILED: "실패", CANCELED: "취소됨", INTERRUPTED: "중단됨" };

export const isFailedJob = (j: JobOut | null | undefined): j is JobOut => !!j && FAILED_STATES.includes(j.state);

/** 실패한 단계(없으면 마지막으로 돈 단계) */
export function failedStep(j: JobOut) {
  const st = j.steps ?? [];
  return st.find((x) => x.state === "FAILED") ?? st.find((x) => x.state === "CANCELED" || x.state === "INTERRUPTED") ?? [...st].reverse().find((x) => x.state !== "PENDING") ?? null;
}

/** 진행 중: "단계 k/N · 이름" */
export function progressText(j: JobOut): string | null {
  const st = j.steps ?? [];
  if (!st.length) return null;
  const cur = st.find((x) => x.state === "RUNNING") ?? st.find((x) => x.state === "PENDING") ?? st[st.length - 1];
  const k = st.indexOf(cur) + 1;
  return `단계 ${k}/${st.length} · ${STEP_LABEL[cur.step_key] ?? cur.step_key}${cur.state === "RUNNING" && cur.progress_pct ? ` ${Math.round(cur.progress_pct)}%` : ""}`;
}

/** 로그 tail(그 단계 step_*.log 끝부분 — 서버 /jobs/{id}/log?tail=true, 권한·경로·크기 상한은 서버) */
export function JobLogTail({ jobId, step }: { jobId: string; step: number | null }) {
  const [lines, setLines] = useState<string[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    setErr(null);
    api
      .jobLog(jobId, null, { step, tail: true })
      .then((r) => alive && setLines(r.lines))
      .catch((e) => alive && setErr(errorText(e)));
    return () => {
      alive = false;
    };
  }, [jobId, step, n]);
  return (
    <div className="job-log-tail" data-testid="job-log-tail">
      <div className="inline-actions small">
        <span className="muted">로그 끝부분{step ? ` · 단계 ${step}` : ""}</span>
        <button type="button" className="btn small ghost" onClick={() => setN((x) => x + 1)}>
          새로 고침
        </button>
      </div>
      {err ? <div className="error-text small">{err}</div> : <pre aria-label="단계 로그">{lines === null ? "불러오는 중…" : lines.slice(-200).join("\n") || "(로그 없음)"}</pre>}
    </div>
  );
}

/** 최신 작업 실패 배너(화면 위 고정). compact(v0.17.1 DOE) = 빨간 1줄(제목·단계·코드·머리말) + [자세히] → 문구·[로그 보기] */
export function JobFailBanner({ job, compact }: { job: JobOut | null | undefined; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [job?.id]);
  if (!isFailedJob(job)) return null;
  const st = failedStep(job);
  const code = st?.failure_code ?? job.failure_code;
  const msg = st?.failure_message ?? job.failure_message;
  const user = failureHint(code, msg) ?? (code ? warnText({ code, message: null }) : null);
  if (compact) {
    const head = user && user !== code ? user : msg;
    const title = [
      `${JOB_TYPE_LABEL[job.job_type] ?? job.job_type} ${STATE_NAME[job.state] ?? job.state}`,
      st ? `단계 ${st.step_no} ${STEP_LABEL[st.step_key] ?? st.step_key}` : null,
      code,
      head ? msgHead(head) : null,
    ].filter(Boolean).join(" · ");
    return (
      <BlockErr title={title} testId="job-fail-banner">
        {(user && user !== code) || msg ? (
          <div className="msg-fold-body" data-testid="job-fail-msg">
            {user && user !== code ? user : null}
            {msg && msg !== user ? `${user && user !== code ? "\n" : ""}${msg}` : null}
          </div>
        ) : null}
        <div>
          <button type="button" className="btn small ghost" aria-expanded={open} onClick={() => setOpen((x) => !x)}>
            {open ? "로그 닫기" : "로그 보기"}
          </button>
        </div>
        {open && <JobLogTail jobId={job.id} step={st?.step_no ?? null} />}
      </BlockErr>
    );
  }
  return (
    <div className="warn-box job-fail-banner" role="alert" data-testid="job-fail-banner">
      <div className="job-fail-head">
        <b>
          {JOB_TYPE_LABEL[job.job_type] ?? job.job_type} {STATE_NAME[job.state] ?? job.state}
        </b>
        {st && <span> · 단계 {st.step_no} {STEP_LABEL[st.step_key] ?? st.step_key}</span>}
        {code && <span className="mono"> · {code}</span>}
        <span className="spacer" />
        <button type="button" className="btn small ghost" aria-expanded={open} onClick={() => setOpen((x) => !x)}>
          {open ? "로그 닫기" : "로그 보기"}
        </button>
      </div>
      {(user && user !== code) || msg ? (
        <div className="small" data-testid="job-fail-msg">
          {user && user !== code ? user : null}
          {msg && msg !== user ? <span className="muted">{user && user !== code ? " — " : ""}{msg}</span> : null}
        </div>
      ) : null}
      {open && <JobLogTail jobId={job.id} step={st?.step_no ?? null} />}
    </div>
  );
}
