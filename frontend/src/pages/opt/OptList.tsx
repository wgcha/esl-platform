// 최적화 실행 목록(esl_opt_run.md §10.1 "최적화 실행" 탭, OR-D-21): 결과는 라이브러리에 넣지 않고 여기 남는다.
import { Link } from "react-router-dom";
import { NORM_NAME, SCENARIO_LABEL, STRATEGY_NAME, opt, optPath } from "../../api/opt";
import { Card, Empty, JobStatusBadge } from "../../components/ui";
import { usePolling } from "../../lib/usePolling";
import { dt } from "../../lib/format";

export function OptList({ projectId }: { projectId: string }) {
  const runs = usePolling(() => opt.runs({ project_id: projectId }), 10000, [projectId]);
  return (
    <Card title="최적화 실행">
      {!runs.data ? (
        <Empty>{runs.error ?? "불러오는 중…"}</Empty>
      ) : runs.data.length === 0 ? (
        <Empty>아직 비드 최적화가 없습니다 — 항목 탭에서 ESL 을 체크하고 '선택한 ESL로 비드 최적화'</Empty>
      ) : (
        <div className="table-wrap scroll">
          <table className="table compact" aria-label="최적화 실행 목록">
            <thead>
              <tr>
                <th className="num">만든 시각</th>
                <th>제목 · 대상</th>
                <th>시나리오</th>
                <th className="num">ESL</th>
                <th>하중 선정 · 목표</th>
                <th>결과</th>
                <th>상태</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.data.map((r) => {
                const res = r.state === "SUCCEEDED" ? r.result : null;
                return (
                  <tr key={r.id}>
                    <td className="num">{dt(r.created_at)}</td>
                    <td>
                      {r.title && <div>{r.title}</div>}
                      <span className={r.title ? "small muted" : undefined}>{r.scenario === "S1" ? `${r.base?.case_title ?? "?"} · ${r.base?.part_title ?? ""}` : r.template?.title ?? "템플릿"}</span>
                    </td>
                    <td>
                      {r.scenario} {SCENARIO_LABEL[r.scenario]}
                    </td>
                    <td className="num">{r.entry_ids.length}</td>
                    <td>
                      {STRATEGY_NAME[r.load_strategy]}
                      {r.k != null ? ` (k ${r.k})` : ""} · {NORM_NAME[r.objective_norm]}
                    </td>
                    <td className="small">{res ? `목적 ${res.objective.initial?.toFixed(2)}→${res.objective.final?.toFixed(2)} · 비드 ${Math.round(res.bead.area_frac * 100)}%${res.converged ? "" : " · 미수렴"}` : "–"}</td>
                    <td>
                      <JobStatusBadge state={r.state} />
                    </td>
                    <td>
                      <Link to={optPath(projectId, r.id)}>열기</Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
