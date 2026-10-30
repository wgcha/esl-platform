// v0.12.0 검증 낙하 카드(esl_scx_relay.md §10.2): 요청 묶음(batch)별 씬 1행 — 진행 칸(업로드·대기·실행·회수·비교)·상태·SCX 잡 ID.
// 고른 행 아래: 드라이브 폴더(경로 복사) · 진행·로그·취소·재시도(JobProgress 재사용, SCX 잡이 있으면 취소 확인 창) ·
// 결과 모름(UNKNOWN) = [잡 ID 연결]·[포기] · 완료 = 원 낙하 vs 검증 낙하 비교 표(정보 표시, PASS/FAIL 없음) + [CSV 받기].
import { useEffect, useMemo, useState } from "react";
import { downloadFile, errorText } from "../api/client";
import {
  PHASE_LABEL, VD_ABANDON_CONFIRM, VD_CANCEL_CONFIRM, VD_STAGES, VERDICT_LABEL, isActiveDrop, isUnknown, ratioText, reachedStage, stageMarks, valText, verify,
} from "../api/verify";
import type { EntryOut, VerifyCompare, VerifyDropOut } from "../api/types";
import { dt } from "../lib/format";
import { Badge, Card } from "./ui";
import { CopyPath } from "./CopyPath";
import { JobProgress } from "./JobProgress";

const MARK_CLASS = { done: "succeeded", cur: "running", todo: "pending", fail: "failed" } as const;

function StageMarks({ d }: { d: VerifyDropOut }) {
  const marks = stageMarks(d.phase, reachedStage(d));
  return (
    <ol className="job-steps vd-steps" aria-label="검증 낙하 단계">
      {VD_STAGES.map((s, i) => (
        <li key={s} className={MARK_CLASS[marks[i]]} aria-current={marks[i] === "cur" ? "step" : undefined}>
          {s}
        </li>
      ))}
    </ol>
  );
}

function PhaseBadge({ d }: { d: VerifyDropOut }) {
  if (isUnknown(d)) return <Badge kind="warn">결과 모름</Badge>;
  const kind = d.phase === "DONE" ? "ok" : d.phase === "FAILED" ? "bad" : d.phase === "CANCELED" ? "warn" : "info";
  return <Badge kind={kind}>{PHASE_LABEL[d.phase]}</Badge>;
}

/** 원 낙하 vs 검증 낙하 비교 표 */
export function VerifyCompareTable({ c }: { c: VerifyCompare }) {
  return (
    <>
      <div className="table-wrap">
        <table className="table compact" aria-label="원 낙하 대비 검증 낙하">
          <thead>
            <tr>
              <th>지표</th>
              <th className="num">원 낙하</th>
              <th className="num">검증 낙하</th>
              <th className="num">비</th>
              <th className="num" title="강성 평가 스터디의 ESL별 선형 예측 비(이 씬의 ESL)">ESL 선형 예측 비</th>
              <th>판단</th>
              <th title="검증 비와 선형 예측 비가 같은 방향(둘 다 개선·둘 다 악화·둘 다 비슷)인지">예측 방향</th>
            </tr>
          </thead>
          <tbody>
            {c.rows.map((r) => (
              <tr key={r.key} data-row={r.key}>
                <td className="small">{r.label}</td>
                <td className="num mono small">{valText(r.orig)}</td>
                <td className="num mono small">{valText(r.verify)}</td>
                <td className="num mono small">{ratioText(r.ratio)}</td>
                <td className="num mono small">{ratioText(r.predicted)}</td>
                <td>
                  <Badge kind={r.verdict === "better" ? "ok" : r.verdict === "worse" ? "warn" : "info"}>{VERDICT_LABEL[r.verdict]}</Badge>
                </td>
                <td className="small">{r.agree === null ? "–" : r.agree ? "일치" : <span className="warn-text">반대</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="small muted" data-testid="vd-hot">
        원 낙하 상위 {c.hot.n}요소 ε_eq 비: 평균 {ratioText(c.hot.mean_ratio)} · 최대 {ratioText(c.hot.max_ratio)} · t* 원 {valText(c.tstar.orig_time)} s → 검증 프레임 {valText(c.tstar.verify_time)} s ·
        판단 = 비 기준(개선 &lt; 1 − 허용치 &lt; 비슷 &lt; 1 + 허용치 &lt; 악화), 합격 판정 아님
      </div>
      {c.warnings.length > 0 && (
        <ul className="reasons small warn-text">
          {c.warnings.map((w, i) => (
            <li key={i}>{w.message || w.code}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function UnknownBox({ d, allowed, onChanged }: { d: VerifyDropOut; allowed: boolean; onChanged: () => void }) {
  const [jobId, setJobId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function act(action: "attach" | "abandon") {
    if (action === "abandon" && !window.confirm(VD_ABANDON_CONFIRM)) return;
    setBusy(true);
    setError(null);
    try {
      await verify.resolve(d.id, { version: d.version, action, ...(action === "attach" ? { scx_job_id: jobId.trim() } : {}) });
      onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const why = !allowed ? "실행(power) 권한이 필요합니다" : null;
  return (
    <div className="warn-box vd-unknown" role="alert" data-testid="vd-unknown">
      <div className="small">제출 결과를 알 수 없습니다(요청 {d.submission?.request_id}). SCX 화면에서 잡을 확인한 뒤 잡이 있으면 ID 를 연결하고, 없으면 포기하세요(포기 후 재시도는 새로 제출).</div>
      <div className="inline-actions">
        <input className="mono" aria-label="SCX 잡 ID" placeholder="SCX 잡 ID" value={jobId} disabled={!!why || busy} onChange={(e) => setJobId(e.target.value)} />
        <span title={why ?? (!jobId.trim() ? "SCX 잡 ID 를 넣으세요" : undefined)}>
          <button type="button" className="btn small" disabled={!!why || busy || !jobId.trim()} onClick={() => void act("attach")}>
            잡 ID 연결
          </button>
        </span>
        <span title={why ?? undefined}>
          <button type="button" className="btn small ghost" disabled={!!why || busy} onClick={() => void act("abandon")}>
            포기
          </button>
        </span>
      </div>
      {error && <div className="small error-text">{error}</div>}
    </div>
  );
}

function CsvButton({ d }: { d: VerifyDropOut }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <span>
      <button
        type="button"
        className="btn small"
        onClick={async () => {
          setError(null);
          try {
            await downloadFile(verify.csvUrl(d.id), `verify_${d.id}.csv`);
          } catch (e) {
            setError(errorText(e));
          }
        }}
      >
        CSV 받기
      </button>
      {error && <span className="small error-text"> {error}</span>}
    </span>
  );
}

function Detail({ d, title, allowed, onChanged }: { d: VerifyDropOut; title: string; allowed: boolean; onChanged: () => void }) {
  const unknown = isUnknown(d);
  const last = d.job_ids[d.job_ids.length - 1] ?? null;
  return (
    <div className="vd-detail" data-testid="vd-detail">
      <div className="inline-actions">
        <span className="sub-title">
          {title} · 안 {d.design_id}
        </span>
        <span className="small muted">
          파일 {d.files_n}개{d.scx_status ? ` · SCX ${d.scx_status}` : ""}
        </span>
        <span className="spacer" />
        {d.phase === "DONE" && d.result && <CsvButton d={d} />}
      </div>
      {d.drive_dir_display && <CopyPath path={d.drive_dir_display} testId="vd-drive-dir" />}
      {unknown && <UnknownBox d={d} allowed={allowed} onChanged={onChanged} />}
      {d.phase !== "DONE" && last && (
        <JobProgress key={last} jobId={last} allowed={allowed} noRetry={unknown} confirmCancel={d.scx_job_id ? VD_CANCEL_CONFIRM : null} onDone={onChanged} onRetried={onChanged} />
      )}
      {d.phase === "DONE" && d.result && <VerifyCompareTable c={d.result} />}
    </div>
  );
}

export function VerifyDropCard({ drops, entries, allowed, onChanged }: { drops: VerifyDropOut[]; entries: EntryOut[]; allowed: boolean; onChanged: () => void }) {
  const [sel, setSel] = useState<string | null>(null);
  const batches = useMemo(() => {
    const m = new Map<string, VerifyDropOut[]>();
    for (const d of drops) m.set(d.batch_id, [...(m.get(d.batch_id) ?? []), d]);
    return [...m.values()];
  }, [drops]);
  const titleOf = (d: VerifyDropOut) => entries.find((e) => e.id === d.entry_id)?.case_title ?? d.case_id;
  // 기본 선택: 사람 확인이 필요한 행 → 진행 중 → 맨 위
  const fallback = drops.find(isUnknown)?.id ?? drops.find(isActiveDrop)?.id ?? drops[0]?.id ?? null;
  const cur = drops.find((d) => d.id === sel) ?? drops.find((d) => d.id === fallback) ?? null;
  useEffect(() => {
    if (sel && !drops.some((d) => d.id === sel)) setSel(null);
    else if (!sel && fallback) setSel(fallback); // 처음 고른 행은 상태가 바뀌어도 유지
  }, [drops, sel, fallback]);
  if (!drops.length) return null;
  const nActive = drops.filter(isActiveDrop).length;
  return (
    <Card title="검증 낙하" right={<span className="small muted">Radioss · SCX — 원 낙하와 비교(합격 판정 없음){nActive ? ` · 진행 ${nActive}` : ""}</span>}>
      <div className="vd-batches" data-testid="vd-card">
        {batches.map((b) => (
          <div key={b[0].batch_id} className="vd-batch">
            <div className="small muted">
              안 {b[0].design_id} · {dt(b[0].created_at)} · {b[0].created_by_name} · 씬 {b.length}
            </div>
            <div className="table-wrap">
              <table className="table compact" aria-label="검증 낙하 씬">
                <thead>
                  <tr>
                    <th>씬(Case)</th>
                    <th>진행</th>
                    <th>상태</th>
                    <th>SCX 잡 ID</th>
                  </tr>
                </thead>
                <tbody>
                  {b.map((d) => (
                    <tr key={d.id} aria-selected={cur?.id === d.id}>
                      <td>
                        <button type="button" className="vd-pick small" aria-pressed={cur?.id === d.id} onClick={() => setSel(d.id)}>
                          {titleOf(d)}
                        </button>
                      </td>
                      <td>
                        <StageMarks d={d} />
                      </td>
                      <td>
                        <PhaseBadge d={d} />
                      </td>
                      <td className="mono small">{d.scx_job_id ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
        {cur && <Detail key={cur.id} d={cur} title={titleOf(cur)} allowed={allowed} onChanged={onChanged} />}
      </div>
    </Card>
  );
}
