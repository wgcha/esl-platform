import { useEffect, useRef, useState } from "react";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { JobOut, JobState } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { JOB_STATE_LABEL } from "../lib/format";

const TERMINAL: JobState[] = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
const RETRYABLE: JobState[] = ["FAILED", "CANCELED", "INTERRUPTED"];

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

  if (!j) return <div className="job muted">작업 상태 불러오는 중…</div>;
  const steps = j.steps ?? [];
  const total = steps.length || 1;
  const doneSteps = steps.filter((s) => s.state === "SUCCEEDED").length;
  const cur = steps.find((s) => s.state === "RUNNING");
  const pctAll = j.progress_pct ?? Math.round(((doneSteps + (cur?.progress_pct ?? 0) / 100) / total) * 100);
  return (
    <div className={`job ${j.state.toLowerCase()}`} data-testid="job-progress">
      <div className="job-head">
        <strong>{JOB_STATE_LABEL[j.state]}</strong>
        <span className="muted">
          {cur ? `step ${cur.step_no}/${total} ${cur.step_key}` : j.state === "QUEUED" ? `대기 순번 #${j.queue_position ?? "–"}` : ""}
        </span>
        {j.failure_code && (
          <span className="bad-text">
            {j.failure_code}
            {j.failure_message ? ` — ${j.failure_message}` : ""}
          </span>
        )}
        {allowed && !terminal && !j.cancel_requested && (
          <button type="button" className="btn link" onClick={() => act(() => api.cancelJob(j.id))}>
            취소
          </button>
        )}
        {allowed && RETRYABLE.includes(j.state) && (
          <button type="button" className="btn link" onClick={() => act(() => api.retryJob(j.id))}>
            재시도
          </button>
        )}
      </div>
      {actError && <div className="small bad-text">{actError}</div>}
      <div className="bar" role="progressbar" aria-valuenow={pctAll} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${pctAll}%` }} />
      </div>
      <pre className="log" aria-label="작업 로그">{lines.slice(-12).join("\n") || " "}</pre>
    </div>
  );
}
