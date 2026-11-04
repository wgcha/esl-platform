import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { STATE_FILTERS } from "../../api/history";
import { useApp } from "../../app/AppContext";
import { HistoryList } from "../../components/HistoryTable";
import { Shell } from "../../shell/Shell";
import { usePolling } from "../../lib/usePolling";
import { p3 } from "../../api/p3";
import { errorText } from "../../api/client";
import type { RunAllOut } from "../../api/types";
import { dt } from "../../lib/format";
import { RUN_ALL_CANCELED_TEXT, runAllStepName, stopDetailText, stopMessage } from "../../shell/RunAllBar";
import { ErrorLine } from "../../components/ui";

/** 일괄 실행 기록 한 행의 결과 칸(§9) */
export function runAllResultText(r: RunAllOut): string {
  if (r.status === "RUNNING") return `진행 중 — ${runAllStepName(r.cur_step)}`;
  if (r.status === "DONE") return `완료 — ④ ${r.verdict ?? "PASS"}`;
  if (r.status === "CANCELED") return RUN_ALL_CANCELED_TEXT;
  const d = stopDetailText(r);
  return `${runAllStepName(r.stop_step)} 멈춤 — ${stopMessage(r)}${d ? ` (${d})` : ""}`;
}

/** Case 이력 위 접힌 "일괄 실행 기록"(GET …/run-all?all=1) — 펼칠 때 읽는다 */
function RunAllLog({ caseId }: { caseId: string }) {
  const [rows, setRows] = useState<RunAllOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <details
      className="adv-input run-all-log"
      data-testid="run-all-log"
      onToggle={(e) => {
        if ((e.currentTarget as HTMLDetailsElement).open && rows === null)
          p3.listRunAll(caseId)
            .then((x) => setRows(x ?? []))
            .catch((x) => setError(errorText(x)));
      }}
    >
      <summary>일괄 실행 기록</summary>
      <div className="adv-body">
        <ErrorLine text={error} />
        {rows === null && !error && <div className="small muted">불러오는 중…</div>}
        {rows && rows.length === 0 && <div className="small muted">일괄 실행 기록이 없습니다</div>}
        {rows && rows.length > 0 && (
          <div className="table-wrap">
            <table className="table" aria-label="일괄 실행 기록">
              <thead>
                <tr>
                  <th>시작 시각</th>
                  <th>시작자</th>
                  <th>시작 단계</th>
                  <th>결과</th>
                  <th className="num">작업 수</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} data-testid="run-all-log-row">
                    <td>{dt(r.created_at)}</td>
                    <td>{r.created_by_name}</td>
                    <td>{runAllStepName(r.from_step)}{r.resumed_from_id ? " (이어서)" : ""}</td>
                    <td>{runAllResultText(r)}</td>
                    <td className="num">{r.job_ids.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </details>
  );
}

/** Case 메뉴 '실행 이력' 탭: 그 Case 의 작업을 시간순으로. 필터는 상태만. */
export function CaseHistory() {
  const { projectId = "", caseId = "" } = useParams();
  const { projects } = useApp();
  const cs = usePolling(() => api.getCase(caseId), 0, [caseId]);
  const [state, setState] = useState("");
  const project = projects.find((p) => p.id === projectId);
  const base = `/p/${projectId}/c/${caseId}`;
  return (
    <Shell
      projectId={projectId}
      crumbs={[
        { label: project?.name ?? projectId, to: `/p/${projectId}` },
        { label: cs.data?.title ?? "Case", to: `${base}/step/1` },
        { label: "실행 이력" },
      ]}
    >
      <div className="page-title-row">
        <h1 className="page-title">실행 이력</h1>
        <span className="spacer" />
        <label className="field inline-field">
          <span className="field-label">상태</span>
          <select value={state} onChange={(e) => setState(e.target.value)} aria-label="상태 필터">
            {STATE_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <RunAllLog caseId={caseId} />
      <HistoryList query={{ project_id: projectId, case_id: caseId, state: state || undefined }} projectId={projectId} showCase={false} />
    </Shell>
  );
}
