import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/endpoints";
import { STATE_FILTERS } from "../../api/history";
import { useApp } from "../../app/AppContext";
import { HistoryList } from "../../components/HistoryTable";
import { Shell } from "../../shell/Shell";
import { usePolling } from "../../lib/usePolling";

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
        { label: cs.data?.title ?? "Case", to: `${base}/stage/1` },
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
      <HistoryList query={{ project_id: projectId, case_id: caseId, state: state || undefined }} projectId={projectId} showCase={false} />
    </Shell>
  );
}
