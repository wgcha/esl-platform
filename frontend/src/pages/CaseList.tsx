import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/endpoints";
import type { Case } from "../api/types";
import { NO_PERMISSION, canRun, useApp } from "../app/AppContext";
import { MENU_CREATE, Shell } from "../shell/Shell";
import { StepDots } from "../shell/StageStepper";
import { Badge, Empty, ErrorLine } from "../components/ui";
import { usePolling } from "../lib/usePolling";
import { dt } from "../lib/format";

const LIB_STATUS: Record<string, string> = { PASS: "PASS", FAIL: "FAIL", UNDETERMINED: "판정 불가", LEGACY: "LEGACY(이전 판정 체계)" };

/** #49 라이브러리 등록 배지: 이 Case 에서 등록된 ACTIVE 항목 수 + 최신 항목 판정(툴팁) */
function LibraryBadge({ c }: { c: Case }) {
  const n = c.library?.count ?? 0;
  if (!n) return <span className="small muted" data-testid="lib-badge">라이브러리 없음</span>;
  const st = c.library?.latest_status ?? null;
  const tip = `최신 등록 판정: ${st ? LIB_STATUS[st] ?? st : "–"}${c.library?.latest_registered_at ? ` · ${dt(c.library.latest_registered_at)}` : ""}`;
  return (
    <span title={tip} data-testid="lib-badge">
      <Badge kind={st === "PASS" ? "ok" : "warn"}>라이브러리 등록됨 {n}</Badge>
    </span>
  );
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
                <td className="nowrap">
                  <span className="case-progress">
                    <StepDots c={c} />
                    <LibraryBadge c={c} />
                  </span>
                </td>
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
