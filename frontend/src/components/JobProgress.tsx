import { useEffect, useRef, useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { JobOut, JobState } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { STEP_LABEL as SHARED_STEP_LABEL } from "../api/history";
import { JobStatusBadge } from "./ui";

const TERMINAL: JobState[] = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
const RETRYABLE: JobState[] = ["FAILED", "CANCELED", "INTERRUPTED"];
/** §6: h3d 입력 Case 의 ① 추출 단계 이름(서버 추출 step 이 있을 때만 단계 줄을 보인다) */
export const H3D_RUNNING = "서버에서 추출 중(HyperView)";
const STEP_LABEL: Record<string, string> = {
  H3D_EXTRACT: "서버 추출(HyperView)",
  EXTRACT: "정리(pack)",
  TSTAR_SCAN: "t* 후보",
  EXTRACT_REGISTER: "등록",
};

/** 작업 진행(2초 갱신) + 로그 tail + 취소·재시도. 종료되면 onDone 호출. */
export function JobProgress({ jobId, onDone, allowed = true }: { jobId: string; onDone?: (j: JobOut) => void; allowed?: boolean }) {
  const job = usePolling(() => api.getJob(jobId), 2000, [jobId]);
  const [lines, setLines] = useState<string[]>([]);
  const [actError, setActError] = useState<string | null>(null);
  const cursor = useRef<number | null>(null);
  const doneFired = useRef(false);
  const j = job.data;
  const terminal = !!j && TERMINAL.includes(j.state);

  useEffect(() => {
    setLines([]);
    cursor.current = null;
    doneFired.current = false;
    setActError(null);
  }, [jobId]);

  useEffect(() => {
    if (!j) return;
    let alive = true;
    api
      .jobLog(jobId, cursor.current)
      .then((r) => {
        if (!alive) return;
        cursor.current = r.next_cursor;
        if (r.lines.length) setLines((old) => [...old, ...r.lines].slice(-200));
      })
      .catch(() => undefined);
    if (terminal && !doneFired.current) {
      doneFired.current = true;
      onDone?.(j);
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [j]);

  async function act(fn: () => Promise<JobOut>) {
    setActError(null);
    try {
      await fn();
      await job.reload();
      onDone?.(j!);
    } catch (e) {
      setActError(errorText(e));
    }
  }

  if (!j) return <div className="job-inline empty small">작업 상태 불러오는 중…</div>;
  const steps = j.steps ?? [];
  const total = steps.length || 1;
  const doneSteps = steps.filter((s) => s.state === "SUCCEEDED").length;
  const cur = steps.find((s) => s.state === "RUNNING");
  const pctAll = j.progress_pct ?? Math.round(((doneSteps + (cur?.progress_pct ?? 0) / 100) / total) * 100);
  return (
    <div className={`job-inline job-${j.state.toLowerCase()}`} data-testid="job-progress">
      <div className="job-inline-row">
        <JobStatusBadge state={j.state} />
        <span className="muted small">
          {cur ? `step ${cur.step_no}/${total} ${cur.step_key}${SHARED_STEP_LABEL[cur.step_key] ? ` ${SHARED_STEP_LABEL[cur.step_key]}` : ""}` : j.state === "QUEUED" ? `대기 ${j.queue_position ?? "–"}번째` : ""}
        </span>
        {j.failure_code && (
          <span className="error-text small">
            {j.failure_code}
            {j.failure_message ? ` — ${j.failure_message}` : ""}
          </span>
        )}
        <span className="spacer" />
        {allowed && !terminal && !j.cancel_requested && (
          <button type="button" className="btn small ghost" onClick={() => act(() => api.cancelJob(j.id))}>
            취소
          </button>
        )}
        {allowed && RETRYABLE.includes(j.state) && (
          <button type="button" className="btn small ghost" onClick={() => act(() => api.retryJob(j.id))}>
            재시도
          </button>
        )}
      </div>
      {actError && (
        <div className="small error-text" role="alert">
          {actError}
        </div>
      )}
      {steps.some((s) => s.step_key === "H3D_EXTRACT") && (
        <>
          {cur?.step_key === "H3D_EXTRACT" && (
            <div className="h3d-phase" data-testid="h3d-extract-phase" role="status">
              {H3D_RUNNING}
              {cur.progress_pct ? ` ${Math.round(cur.progress_pct)}%` : ""} <span className="muted small">— h3d 크기에 따라 수 분~수십 분. 서버 HyperView가 h3d를 읽기만 합니다</span>
            </div>
          )}
          <ol className="job-steps" aria-label="추출 단계">
            {steps.map((s) => (
              <li key={s.step_no} className={s.state.toLowerCase()} aria-current={s.state === "RUNNING" ? "step" : undefined}>
                {s.step_key === "H3D_EXTRACT" && s.state === "RUNNING" ? H3D_RUNNING : STEP_LABEL[s.step_key] ?? s.step_key}
                {s.state === "RUNNING" && s.progress_pct ? ` ${s.progress_pct}%` : ""}
              </li>
            ))}
          </ol>
        </>
      )}
      <div className="progress" role="progressbar" aria-label="진행률" aria-valuenow={pctAll} aria-valuemin={0} aria-valuemax={100}>
        <div className="progress-fill" style={{ width: `${pctAll}%` }} />
      </div>
      <div className="logview">
        <pre aria-label="작업 로그">{lines.slice(-12).join("\n") || " "}</pre>
      </div>
    </div>
  );
}
