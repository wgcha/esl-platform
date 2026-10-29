import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/endpoints";
import type { Case } from "../api/types";
import { NO_PERMISSION, canRun, useApp } from "../app/AppContext";
import { MENU_CREATE, Shell } from "../shell/Shell";
import { N_STEPS, STEP_NAMES, stepState } from "../shell/StageStepper";
import { Empty, ErrorLine } from "../components/ui";
import { usePolling } from "../lib/usePolling";
import { dt } from "../lib/format";

/** 진행 한 줄: 화면 4단계(step_status) 기준 */
function progressOf(c: Case) {
  let last = 0;
  let running = 0;
  for (let n = 1; n <= N_STEPS; n++) {
    const s = stepState(c, n)?.state;
    if (s === "done" || s === "stale") last = n;
    if (s === "running" && !running) running = n;
  }
  if (running) return `${STEP_NAMES[running - 1]} 실행 중`;
  return last ? `${STEP_NAMES[last - 1]}까지 완료` : "시작 전";
}

export function CaseList() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const project = projects.find((p) => p.id === projectId);
  const cases = usePolling(() => api.cases(projectId), 5000, [projectId]);
  const nav = useNavigate();
  const allowed = canRun(me, projectId);
  return (
    <Shell crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: MENU_CREATE }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">{MENU_CREATE}</h1>
        <span className="muted small">Case 목록 — Case 마다 ①입력 ②t*·지지점 ③ESL ④검증 후 라이브러리에 등록</span>
        <span className="spacer" />
        <Link to={`/p/${projectId}/history`} className="page-link">
          실행 이력
        </Link>
        <span className="primary-wrap" title={allowed ? undefined : NO_PERMISSION}>
          <button type="button" className="btn primary" disabled={!allowed} onClick={() => nav(`/p/${projectId}/cases/new`)}>
            새 Case
          </button>
        </span>
      </div>
      <ErrorLine text={cases.error} />
      {cases.data && cases.data.length === 0 && <Empty>아직 Case가 없습니다</Empty>}
      {cases.data && cases.data.length > 0 && (
        <div className="table-wrap scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Case</th>
              <th>폴더</th>
              <th>진행</th>
              <th>만든 사람</th>
              <th className="num">수정</th>
            </tr>
          </thead>
          <tbody>
            {cases.data.map((c) => (
              <tr key={c.id}>
                <td>
                  <Link to={`/p/${projectId}/c/${c.id}/step/1`}>{c.title}</Link>
                </td>
                <td className="mono">{c.folder_name}</td>
                <td>{progressOf(c)}</td>
                <td>{c.created_by_name}</td>
                <td className="num">{dt(c.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </Shell>
  );
}
