import { useEffect, useRef, useState } from "react";
import { api } from "../api/endpoints";
import type { Job, JobState } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { JOB_STATE_LABEL } from "../lib/format";

const TERMINAL: JobState[] = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];

/** 작업 진행(2초 갱신) + 로그 tail. 종료되면 onDone 호출. */
export function JobProgress({ jobId, onDone }: { jobId: string; onDone?: (j: Job) => void }) {
  const job = usePolling(() => api.getJob(jobId), 2000, [jobId]);
  const [lines, setLines] = useState<string[]>([]);
  const cursor = useRef<string | null>(null);
  const doneFired = useRef(false);
  const j = job.data;
  const terminal = !!j && TERMINAL.includes(j.state);

  useEffect(() => {
    setLines([]);
    cursor.current = null;
    doneFired.current = false;
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

  if (!j) return <div className="job muted">작업 상태 불러오는 중…</div>;
  const total = j.steps.length || 1;
  const doneSteps = j.steps.filter((s) => s.state === "SUCCEEDED").length;
  const cur = j.steps.find((s) => s.state === "RUNNING");
  const pctAll = Math.round(((doneSteps + (cur?.progress_pct ?? 0) / 100) / total) * 100);
  return (
    <div className={`job ${j.state.toLowerCase()}`} data-testid="job-progress">
      <div className="job-head">
        <strong>{JOB_STATE_LABEL[j.state]}</strong>
        <span className="muted">
          {cur ? `step ${cur.step_no}/${total} ${cur.step_key}` : j.state === "QUEUED" ? `대기 순번 #${j.queue_seq ?? "–"}` : ""}
        </span>
        {j.failure_code && <span className="bad-text">{j.failure_code}{j.failure_message ? ` — ${j.failure_message}` : ""}</span>}
      </div>
      <div className="bar" role="progressbar" aria-valuenow={pctAll} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${pctAll}%` }} />
      </div>
      <pre className="log" aria-label="작업 로그">{lines.slice(-12).join("\n") || " "}</pre>
    </div>
  );
}
