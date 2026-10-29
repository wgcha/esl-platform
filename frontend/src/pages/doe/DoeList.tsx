// 비드 DOE 목록(esl_bead_doe.md §12.1 라이브러리 탭 [비드 DOE]): 연구별 시나리오·ESL·DOE·상태·최적 개선율. 결과는 라이브러리에 넣지 않는다.
import { Link } from "react-router-dom";
import { METHOD_NAME, PHASE_NAME, SCENARIO_NAME, SCENARIO_NO, doe, doePath } from "../../api/doe";
import type { DoePhase } from "../../api/types";
import { Badge, Card, Empty } from "../../components/ui";
import { usePolling } from "../../lib/usePolling";
import { dt } from "../../lib/format";

const KIND: Record<DoePhase, "ok" | "bad" | "warn" | "info"> = { PREP: "info", READY: "warn", PREVIEW: "info", PREVIEW_READY: "warn", RUN: "info", DONE: "ok", FAILED: "bad" };

export function DoeList({ projectId }: { projectId: string }) {
  const list = usePolling(() => doe.studies({ project_id: projectId }), 10000, [projectId]);
  return (
    <Card title="비드 DOE">
      {!list.data ? (
        <Empty>{list.error ?? "불러오는 중…"}</Empty>
      ) : list.data.length === 0 ? (
        <Empty>아직 비드 DOE 가 없습니다 — 항목 탭에서 ESL 을 체크하고 '선택한 ESL로 비드 DOE'</Empty>
      ) : (
        <div className="table-wrap scroll">
          <table className="table compact" aria-label="비드 DOE 목록">
            <thead>
              <tr>
                <th className="num">만든 시각</th>
                <th>제목 · STEP</th>
                <th>시나리오</th>
                <th className="num">ESL</th>
                <th>DOE</th>
                <th>미리보기</th>
                <th>상태</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((s) => (
                <tr key={s.id}>
                  <td className="num">{dt(s.created_at)}</td>
                  <td>
                    <div>{s.title}</div>
                    <span className="small muted">{s.inputs.step.file_name}</span>
                  </td>
                  <td>
                    {SCENARIO_NO[s.scenario]} {SCENARIO_NAME[s.scenario]}
                  </td>
                  <td className="num">{s.entry_ids.length}</td>
                  <td className="small">{s.doe ? `${METHOD_NAME[s.doe.spec.method] ?? s.doe.spec.method} · ${s.doe.n_designs}안 · 변수 ${s.doe.spec.params.length}` : "–"}</td>
                  <td className="small">{s.doe?.preview ? `OK ${s.doe.preview.ok} · 스킵 ${s.doe.preview.skipped.collision + s.doe.preview.skipped.fixed + s.doe.preview.skipped.geom}` : "–"}</td>
                  <td>
                    <Badge kind={KIND[s.phase]}>{PHASE_NAME[s.phase]}</Badge>
                  </td>
                  <td>
                    <Link to={doePath(projectId, s.id)}>열기</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
