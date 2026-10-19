import { api } from "../api/endpoints";
import { Badge, Card, Empty, Stat } from "../components/ui";
import { usePolling } from "../lib/usePolling";
import { METRIC_LABEL, fmtFixed, pct, sci, vec } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, submitJob, useAction } from "./common";
import { dofText } from "./Stage3";

export function Stage4({ c, reload, allowed }: StageProps) {
  const runId = c.current_esl_run_id;
  const run = usePolling(() => (runId ? api.eslRun(runId) : Promise.resolve(null)), 0, [runId, c.version]);
  const forces = usePolling(() => (runId ? api.forces(runId, 50) : Promise.resolve(null)), 0, [runId]);
  const sets = usePolling(() => (c.current_support_set_id ? api.supportSets(c.id) : Promise.resolve([])), 0, [c.current_support_set_id]);
  const support = sets.data?.find((s) => s.id === c.current_support_set_id);
  const act = useAction(reload);
  const r = run.data;

  const missing = [!c.tstar && "② t*", !c.current_support_set_id && "③ 지지점"].filter(Boolean);
  const prereq = missing.length ? `${missing.join("·")}을(를) 먼저 확정하세요.` : null;

  return (
    <StageFrame
      title="④ ESL"
      status={c.stage_status?.["4"]}
      error={act.error ?? run.error}
      onJobDone={() => void reload()}
      primary={{ label: "ESL 계산", onClick: () => act.run(() => submitJob(c, "ESL_SOLVE")), disabledReason: blockReason(allowed, c, 4, prereq), busy: act.busy }}
    >
      <Card title="입력 요약">
        <div className="stats">
          <Stat
            label="t*"
            value={c.tstar ? `${c.tstar.time.toFixed(3)} s (프레임 ${c.tstar.frame_index})` : "–"}
            hint={c.tstar ? `${METRIC_LABEL[c.tstar.metric]} · 요소 ${c.tstar.elem_id}` : undefined}
          />
          <Stat label="지표" value={c.tstar ? METRIC_LABEL[c.tstar.metric] : "–"} />
          <Stat label="지지 노드" value={support ? support.node_ids.join(", ") : "–"} />
          <Stat label="dof" value={support ? support.dofs.map(dofText).join(" / ") : "–"} />
        </div>
        {r && (r.frame_index !== c.tstar?.frame_index || r.support_set_id !== c.current_support_set_id) && (
          <div className="small warn-text">
            아래 결과는 이전 입력(프레임 {r.frame_index}) 기준입니다.
          </div>
        )}
      </Card>
      {!runId ? (
        <Empty>아직 ESL을 계산하지 않았습니다.</Empty>
      ) : !r ? (
        <Empty>불러오는 중…</Empty>
      ) : (
        <>
          <Card title="결과" right={r.status === "READY" ? <Badge kind="ok">READY</Badge> : <Badge kind="bad">FAILED</Badge>}>
            <div className="stats">
              <Stat label="강체 회전각" value={`${fmtFixed(r.kabsch?.rot_deg, 2)}°`} />
              <Stat label="변형 RMS / max" value={`${fmtFixed(r.kabsch?.rms_def, 3)} / ${fmtFixed(r.kabsch?.max_def, 3)}`} hint="강체 제거 후 상대 변위(mm)" />
              <Stat label="ΣF" value={<span className="mono small">{vec(r.forces?.sum_f ?? undefined)}</span>} />
              <Stat label="ΣM" value={<span className="mono small">{vec(r.forces?.sum_m ?? undefined)}</span>} />
              <Stat label="평형 오차" value={sci(r.forces?.equilibrium_rel)} hint={r.forces?.moment_rel != null ? `모멘트 ${sci(r.forces.moment_rel)}` : undefined} />
              <Stat label="잡음 (힘)" value={pct(r.forces?.noise.force_rel, 2)} hint={r.forces?.noise.disp_precision ?? undefined} />
              <Stat label="잡음 (hotspot 변형률)" value={pct(r.forces?.noise.hotspot_strain_rel, 2)} />
              <Stat label="하중 노드 수" value={r.forces?.n_nodes_loaded?.toLocaleString() ?? "–"} />
            </div>
            {r.warnings.length > 0 && (
              <ul className="reasons">
                {r.warnings.map((w) => (
                  <li key={w} className="small warn-text">
                    {w}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="F_eq 상위 노드">
            {forces.data ? (
              <div className="scroll">
                <table className="tbl compact">
                  <thead>
                    <tr>
                      <th>노드</th>
                      <th>x</th>
                      <th>y</th>
                      <th>z</th>
                      <th>Fx</th>
                      <th>Fy</th>
                      <th>Fz</th>
                      <th>|F|</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {forces.data.rows.map((f) => (
                      <tr key={f.node_id}>
                        <td>{f.node_id}</td>
                        <td>{f.x.toFixed(1)}</td>
                        <td>{f.y.toFixed(1)}</td>
                        <td>{f.z.toFixed(1)}</td>
                        <td>{f.fx.toFixed(1)}</td>
                        <td>{f.fy.toFixed(1)}</td>
                        <td>{f.fz.toFixed(1)}</td>
                        <td>
                          <strong>{f.mag.toFixed(1)}</strong>
                        </td>
                        <td>{f.is_support && <Badge kind="info">지지점</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>불러오는 중…</Empty>
            )}
          </Card>
        </>
      )}
    </StageFrame>
  );
}
