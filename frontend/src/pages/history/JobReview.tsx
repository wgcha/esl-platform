import { useEffect, useRef, useState } from "react";
import { stepOfStage, stepPath } from "../../shell/StageStepper";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { errorText, failureHint, warnText } from "../../api/client";
import { JOB_TYPE_LABEL, STALE_REASON_LABEL, STEP_LABEL, durText, history, linkPath, type PastFile, type ReviewOut } from "../../api/history";
import { canRun, useApp } from "../../app/AppContext";
import { DiffTable, diffValue } from "../../components/DiffTable";
import { PAST_FILES_GONE, PastBadge, StaleChip } from "../../components/PastBadge";
import { openReport } from "../../components/ReportLink";
import { Badge, Card, Empty, ErrorLine, JobStatusBadge, PrimaryButton, Stat } from "../../components/ui";
import { bytes, dt } from "../../lib/format";
import { usePolling } from "../../lib/usePolling";
import { Shell } from "../../shell/Shell";

/** 한 단계 펼침: {a:{b:1}} -> "a.b"=1 (배열·더 깊은 객체는 값 그대로) */
function flat(data: Record<string, unknown>): [string, unknown][] {
  const out: [string, unknown][] = [];
  for (const [k, v] of Object.entries(data)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const sub = Object.entries(v as Record<string, unknown>);
      if (sub.length) sub.forEach(([k2, v2]) => out.push([`${k}.${k2}`, v2]));
      else out.push([k, v]);
    } else out.push([k, v]);
  }
  return out;
}

const pick = (o: Record<string, unknown>, keys: string[]) => Object.fromEntries(keys.filter((k) => k in o).map((k) => [k, o[k]]));

/** 결과 종류별로 past(기록된 값)에서 화면에 보일 값만 고른다. 실제 응답: 추출 {extract,tstar}, ESL = esl_run_out 전체, 검증 = validation_out + has_field. */
function pastScalars(kind: string | undefined, past: Record<string, unknown>): Record<string, unknown> {
  switch (kind) {
    case "esl_run":
      return pick(past, ["frame_index", "time", "metric", "status", "kabsch", "forces", "warnings"]);
    case "validation": {
      const h = Array.isArray(past.hotspots) ? past.hotspots.length : null;
      return { ...pick(past, ["status", "verdict", "scheme", "undetermined_reason", "fail_reasons", "disp_rms_rel", "disp_max_rel", "reaction_rel", "disp_noise_rel", "criteria", "has_field"]), ...(h === null ? {} : { hotspots: `${h}개` }) };
    }
    case "export": {
      const { files: _f, ...rest } = past;
      void _f;
      return rest;
    }
    default:
      return past;
  }
}

function KeyValues({ data }: { data: Record<string, unknown> }) {
  const rows = flat(data);
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
  const [next, setNext] = useState<{ cursor: number; eof: boolean }>({ cursor: 0, eof: true });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 서버는 한 번에 일정 크기까지만 준다(next_cursor·eof) — 처음 한 덩어리를 읽고, 남았으면 "이어서 보기"로 이어 읽는다.
  async function read(cursor: number, append: boolean, alive: () => boolean) {
    if (step === null) return;
    setBusy(true);
    try {
      const r = await history.log(jobId, step, cursor);
      if (!alive()) return;
      setLines((old) => (append && old ? [...old, ...r.lines] : r.lines));
      setNext({ cursor: r.next_cursor, eof: r.eof });
      setErr(null);
    } catch (e) {
      if (alive()) setErr(errorText(e));
    } finally {
      if (alive()) setBusy(false);
    }
  }
  useEffect(() => {
    if (step === null) return;
    let ok = true;
    setLines(null);
    void read(0, false, () => ok);
    return () => {
      ok = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, step]);
  if (!withLog.length) return <Empty>남은 로그가 없습니다</Empty>;
  return (
    <>
      <label className="field inline-field">
        <span className="field-label">step</span>
        <select value={step ?? ""} onChange={(e) => setStep(Number(e.target.value))} aria-label="로그 step">
          {withLog.map((l) => (
            <option key={l.step_no} value={l.step_no}>
              {l.step_no}. {l.step_key}{STEP_LABEL[l.step_key] ? ` ${STEP_LABEL[l.step_key]}` : ""} ({bytes(l.size)})
            </option>
          ))}
        </select>
      </label>
      <ErrorLine text={err} />
      <div className="logview">
        <pre aria-label="step 로그">{lines === null ? "불러오는 중…" : lines.join("\n") || " "}</pre>
      </div>
      {lines !== null && !next.eof && (
        <button type="button" className="btn small" disabled={busy} onClick={() => void read(next.cursor, true, () => true)}>
          {busy ? "불러오는 중…" : "이어서 보기"}
        </button>
      )}
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
  const fileRows: PastFile[] = files.data ?? (Array.isArray(past.files) ? (past.files as PastFile[]) : []);
  const scalars = pastScalars(res.ref?.kind, past);
  const libPath = res.ref?.kind === "analysis" || res.ref?.kind === "comparison" ? linkPath(rv.job.project_id, null, res.links) : null;
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
            <div className="table-wrap scroll">
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
                    <td className="num">{f.size === null || f.size === undefined ? "–" : bytes(f.size)}</td>
                    <td>{res.availability === "full" && f.downloadable ? <a href={history.fileUrl(jobId, f.name)}>받기</a> : <span className="muted small">보존 안 됨</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
          {res.ref?.kind === "report" && res.availability === "full" && (
            <button type="button" className="btn small" onClick={() => openReport(history.reportUrl(jobId))}>
              보고서 새 탭으로 열기
            </button>
          )}
          {libPath && (
            <div className="small">
              {res.state === "past" && <span className="muted">이후 다시 실행됨 · </span>}
              <Link to={libPath}>{res.ref?.kind === "analysis" ? "현재 분석 열기" : "현재 비교 열기"}</Link>
            </div>
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
  const caseInfo = usePolling(() => (rv.data?.job.case_id ? api.getCase(rv.data.job.case_id) : Promise.resolve(null)), 0, [rv.data?.job.case_id]);
  const [retryMsg, setRetryMsg] = useState<string | null>(null);
  const [retryErr, setRetryErr] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const project = projects.find((p) => p.id === projectId);
  const r = rv.data;
  const job = r?.job;
  const allowed = canRun(me, projectId);

  function openPast() {
    // ④ ?run= · ⑤ ?val= 만 단계 화면의 읽기 전용 모드로 간다. ①·⑥·보고서는 이 화면의 결과 카드가 열람 위치(계약 §5).
    const kind = r?.result.ref?.kind;
    const to = kind === "esl_run" || kind === "validation" ? linkPath(projectId, job?.case_id ?? null, r?.result.links) : null;
    if (to) nav(to);
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
        <div className="wide2">
          {(r.error.failure_code || r.error.failure_message || r.error.warnings.length > 0) && (
            <Card title={r.error.failure_code || r.error.failure_message ? "오류" : "경고"}>
              {(r.error.failure_code || r.error.failure_message) && (
                <div className="error-text" data-testid="job-error">
                  <strong>{r.error.failure_code}</strong>
                  {r.error.failure_message ? ` — ${r.error.failure_message}` : ""}
                </div>
              )}
              {failureHint(r.error.failure_code, r.error.failure_message) && (
                <div className="small error-text" data-testid="failure-hint">
                  {failureHint(r.error.failure_code, r.error.failure_message)}
                </div>
              )}
              {r.error.failed_step && (
                <div className="small muted">
                  실패 step: {r.error.failed_step.step_no}. {r.error.failed_step.step_key}{STEP_LABEL[r.error.failed_step.step_key] ? ` ${STEP_LABEL[r.error.failed_step.step_key]}` : ""}
                  {r.error.failed_step.exit_code !== null ? ` (exit ${r.error.failed_step.exit_code})` : ""}
                </div>
              )}
              {r.error.warnings.length > 0 && (
                <ul className="reasons">
                  {r.error.warnings.map((w, i) => (
                    <li key={i} className="small warn-text" data-testid="job-warning">
                      {typeof w === "string" ? warnText(w) : diffValue(w)}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
          <Card title="개요">
            <div className="stats">
              <Stat label="상태" value={<JobStatusBadge state={job.state} />} />
              <Stat label="Case" value={job.case_id ? <Link to={stepPath(projectId, job.case_id, job.stage >= 1 && job.stage <= 6 ? stepOfStage(job.stage) : 1)}>{caseInfo.data?.title ?? job.case_id}</Link> : "라이브러리"} />
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
                <div className="table-wrap scroll">
                <table className="table compact">
                  <tbody>
                    {r.input.input_fingerprint.map((f, i) => (
                      <tr key={`${f.kind}-${f.path ?? i}`}>
                        <td>{f.kind}</td>
                        <td className="mono small">{f.path ?? "–"}</td>
                        <td className="num">{f.size === null || f.size === undefined ? "–" : bytes(f.size)}</td>
                        <td className="num">{f.mtime === null || f.mtime === undefined ? "–" : dt(new Date(f.mtime * 1000).toISOString())}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              </details>
            )}
          </Card>
          <Card title="step">
            <div className="table-wrap scroll">
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
                {(job.steps ?? []).map((s) => {
                  const t = r.timing.steps.find((x) => x.step_no === s.step_no);
                  return (
                    <tr key={s.step_no}>
                      <td className="num">{s.step_no}</td>
                      <td>
                        {s.step_key}{STEP_LABEL[s.step_key] ? <span className="muted"> {STEP_LABEL[s.step_key]}</span> : null}
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
            </div>
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
        </div>
      )}
    </Shell>
  );
}
