import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { errorText } from "../../api/client";
import { JOB_TYPE_LABEL, STALE_REASON_LABEL, durText, history, type ReviewOut } from "../../api/history";
import { canRun, useApp } from "../../app/AppContext";
import { DiffTable, diffValue } from "../../components/DiffTable";
import { PAST_FILES_GONE, PastBadge, StaleChip } from "../../components/PastBadge";
import { openReport } from "../../components/ReportLink";
import { Badge, Card, Empty, ErrorLine, JobStatusBadge, PrimaryButton, Stat } from "../../components/ui";
import { bytes, dt } from "../../lib/format";
import { usePolling } from "../../lib/usePolling";
import { Shell } from "../../shell/Shell";

function KeyValues({ data }: { data: Record<string, unknown> }) {
  const rows = Object.entries(data);
  if (!rows.length) return <Empty>없음</Empty>;
  return (
    <table className="table compact kv-table">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <th scope="row" className="mono small">
              {k}
            </th>
            <td className="mono small">{diffValue(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StepLog({ jobId, rv }: { jobId: string; rv: ReviewOut }) {
  const withLog = rv.logs.filter((l) => l.has_log);
  const [step, setStep] = useState<number | null>(withLog[0]?.step_no ?? null);
  const [lines, setLines] = useState<string[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (step === null) return;
    let alive = true;
    setLines(null);
    history
      .log(jobId, step)
      .then((r) => alive && (setLines(r.lines), setErr(null)))
      .catch((e) => alive && setErr(errorText(e)));
    return () => {
      alive = false;
    };
  }, [jobId, step]);
  if (!withLog.length) return <Empty>남은 로그가 없습니다</Empty>;
  return (
    <>
      <label className="field inline-field">
        <span className="field-label">step</span>
        <select value={step ?? ""} onChange={(e) => setStep(Number(e.target.value))} aria-label="로그 step">
          {withLog.map((l) => (
            <option key={l.step_no} value={l.step_no}>
              {l.step_no}. {l.step_key} ({bytes(l.size)})
            </option>
          ))}
        </select>
      </label>
      <ErrorLine text={err} />
      <div className="logview">
        <pre aria-label="step 로그">{lines === null ? "불러오는 중…" : lines.join("\n") || " "}</pre>
      </div>
    </>
  );
}

/** 결과 카드: 기록된 값(DB)을 그대로 보여 준다. 파일이 필요한 보기는 보존된 경우만. */
function ResultCard({ jobId, rv }: { jobId: string; rv: ReviewOut }) {
  const res = rv.result;
  const files = usePolling(
    () => (res.availability === "full" && res.ref?.kind === "export" ? history.files(jobId) : Promise.resolve(null)),
    0,
    [jobId, res.availability, res.ref?.kind],
  );
  const past = res.past ?? {};
  const fileRows = files.data ?? (Array.isArray(past.files) ? (past.files as { name: string; size: number; downloadable: boolean }[]) : []);
  const { files: _files, ...scalars } = past;
  void _files;
  return (
    <Card
      title="결과"
      right={
        res.availability === "none" ? undefined : (
          <span className="inline-actions">
            {res.state === "current" && <Badge kind="ok">현재 결과</Badge>}
            {res.state === "past" && <PastBadge at={rv.job.finished_at} />}
            <StaleChip reasons={res.stale_reasons} />
          </span>
        )
      }
    >
      {res.availability === "none" ? (
        <Empty>{rv.job.state === "SUCCEEDED" ? "이 작업에는 보관된 결과가 없습니다" : "결과가 없는 작업입니다 (실패·취소·대기·실행 중)"}</Empty>
      ) : (
        <>
          {res.availability === "summary" && (
            <div className="small warn-text" data-testid="files-gone">
              {res.files_note ?? PAST_FILES_GONE}
            </div>
          )}
          <KeyValues data={scalars} />
          {res.ref?.kind === "export" && fileRows.length > 0 && (
            <table className="table compact" aria-label="내보내기 파일">
              <thead>
                <tr>
                  <th>파일</th>
                  <th className="num">크기</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {fileRows.map((f) => (
                  <tr key={f.name}>
                    <td className="mono small">{f.name}</td>
                    <td className="num">{bytes(f.size)}</td>
                    <td>{res.availability === "full" && f.downloadable ? <a href={history.fileUrl(jobId, f.name)}>받기</a> : <span className="muted small">보존 안 됨</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {res.ref?.kind === "report" && res.availability === "full" && (
            <button type="button" className="btn small" onClick={() => openReport(history.reportUrl(jobId))}>
              보고서 새 탭으로 열기
            </button>
          )}
          {res.links?.path && (
            <Link to={res.links.path} className="small">
              현재 분석 열기
            </Link>
          )}
          <DiffTable diff={res.diff} />
        </>
      )}
    </Card>
  );
}

export function JobReview() {
  const { projectId = "", jobId = "" } = useParams();
  const { me, projects } = useApp();
  const nav = useNavigate();
  const rv = usePolling(() => history.review(jobId), 0, [jobId]);
  const [retryMsg, setRetryMsg] = useState<string | null>(null);
  const [retryErr, setRetryErr] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const project = projects.find((p) => p.id === projectId);
  const r = rv.data;
  const job = r?.job;
  const allowed = canRun(me, projectId);

  function openPast() {
    const l = r?.result.links;
    if (job?.case_id && l?.stage) {
      const qs = new URLSearchParams(l.query ?? {}).toString();
      nav(`/p/${projectId}/c/${job.case_id}/stage/${l.stage}${qs ? `?${qs}` : ""}`);
    } else if (l?.path) nav(l.path);
    else resultRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }
  async function retry() {
    setRetryErr(null);
    try {
      const nj = await api.retryJob(jobId);
      setRetryMsg(`재시도를 요청했습니다 (${nj.id})`);
    } catch (e) {
      setRetryErr(errorText(e));
    }
  }

  const failed = !!job && ["FAILED", "INTERRUPTED", "CANCELED"].includes(job.state);
  const subject = job?.case_id ? { label: "Case 실행 이력", to: `/p/${projectId}/c/${job.case_id}/history` } : { label: "실행 이력", to: `/p/${projectId}/history` };
  return (
    <Shell crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: subject.label, to: subject.to }, { label: "작업 상세" }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">작업 상세{job ? ` — ${JOB_TYPE_LABEL[job.job_type]}` : ""}</h1>
        <span className="spacer" />
        {r && failed && allowed && (
          <button type="button" className="btn small ghost" onClick={() => void retry()}>
            재시도
          </button>
        )}
        {r && r.result.availability !== "none" && <PrimaryButton label="그때 결과 열기" onClick={openPast} />}
      </div>
      <ErrorLine text={rv.error ?? retryErr} />
      {retryMsg && (
        <div className="small" role="status">
          {retryMsg}
        </div>
      )}
      {!r && !rv.error && <Empty>불러오는 중…</Empty>}
      {r && job && (
        <>
          {(failed || job.failure_code) && (r.error.failure_code || r.error.failure_message) && (
            <Card title="오류">
              <div className="error-text" data-testid="job-error">
                <strong>{r.error.failure_code}</strong>
                {r.error.failure_message ? ` — ${r.error.failure_message}` : ""}
              </div>
              {r.error.failed_step && (
                <div className="small muted">
                  실패 step: {r.error.failed_step.step_no}. {r.error.failed_step.step_key}
                  {r.error.failed_step.exit_code !== null ? ` (exit ${r.error.failed_step.exit_code})` : ""}
                </div>
              )}
              {r.error.warnings.length > 0 && (
                <ul className="reasons">
                  {r.error.warnings.map((w) => (
                    <li key={w} className="small warn-text">
                      {w}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
          <Card title="개요">
            <div className="stats">
              <Stat label="상태" value={<JobStatusBadge state={job.state} />} />
              <Stat label="Case" value={job.case_id ? <Link to={`/p/${projectId}/c/${job.case_id}/stage/${job.stage || 1}`}>{job.case_id}</Link> : "라이브러리"} />
              <Stat label="생성" value={dt(job.created_at)} />
              <Stat label="대기" value={durText(r.timing.wait_s)} />
              <Stat label="소요" value={durText(r.timing.duration_s)} />
              <Stat label="실행자" value={job.created_by_name} />
              {job.retry_of_job_id && <Stat label="재시도 원본" value={<Link to={`/p/${projectId}/jobs/${job.retry_of_job_id}`}>{job.retry_of_job_id}</Link>} />}
            </div>
          </Card>
          <Card title="입력값">
            <KeyValues data={r.input.params} />
            {r.input.settings_summary && Object.keys(r.input.settings_summary).length > 0 && (
              <details>
                <summary>설정 요약 (판정 기준·t* 지표·재료 override)</summary>
                <KeyValues data={r.input.settings_summary} />
              </details>
            )}
            {r.input.input_fingerprint && r.input.input_fingerprint.length > 0 && (
              <details>
                <summary>입력 파일 지문 ({r.input.input_fingerprint.length})</summary>
                <table className="table compact">
                  <tbody>
                    {r.input.input_fingerprint.map((f) => (
                      <tr key={f.path}>
                        <td>{f.kind}</td>
                        <td className="mono small">{f.path}</td>
                        <td className="num">{bytes(f.size)}</td>
                        <td className="num">{dt(f.mtime)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
          </Card>
          <Card title="step">
            <table className="table compact" aria-label="step 표">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>step</th>
                  <th>상태</th>
                  <th className="num">소요</th>
                </tr>
              </thead>
              <tbody>
                {job.steps.map((s) => {
                  const t = r.timing.steps.find((x) => x.step_no === s.step_no);
                  return (
                    <tr key={s.step_no}>
                      <td className="num">{s.step_no}</td>
                      <td>
                        {s.step_key}
                        {s.command && (
                          <details>
                            <summary className="small muted">command</summary>
                            <code className="mono small">{s.command.join(" ")}</code>
                          </details>
                        )}
                      </td>
                      <td>{s.state}</td>
                      <td className="num">{durText(t?.duration_s)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
          <Card title="로그">
            <StepLog jobId={jobId} rv={r} />
          </Card>
          <div ref={resultRef}>
            <ResultCard jobId={jobId} rv={r} />
          </div>
          {r.result.stale_reasons.length > 0 && (
            <div className="small muted">
              입력 바뀜 사유: {r.result.stale_reasons.map((x) => STALE_REASON_LABEL[x] ?? x).join(" · ")}
            </div>
          )}
        </>
      )}
    </Shell>
  );
}
