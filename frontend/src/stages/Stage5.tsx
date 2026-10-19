import { api } from "../api/endpoints";
import { Badge, Card, Empty, Stat } from "../components/ui";
import { usePolling } from "../lib/usePolling";
import { pct, sci } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, submitJob, useAction } from "./common";

export function Stage5({ c, reload, allowed }: StageProps) {
  const runId = c.current_esl_run_id;
  const run = usePolling(() => (runId ? api.eslRun(runId) : Promise.resolve(null)), 0, [runId, c.version]);
  const vid = run.data?.latest_validation_id ?? null;
  const val = usePolling(() => (vid ? api.validation(vid) : Promise.resolve(null)), 0, [vid]);
  const act = useAction(reload);
  const v = val.data;

  const prereq = !runId ? "④ ESL을 먼저 계산하세요." : run.data?.stale ? "④ ESL을 다시 계산하세요(입력이 바뀜)." : null;
  const crit = v?.criteria ?? {};

  return (
    <StageFrame
      title="⑤ 검증"
      status={c.stage_status?.["5"]}
      error={act.error ?? run.error ?? val.error}
      onJobDone={() => void reload()}
      primary={{
        label: "검증 실행",
        onClick: () => act.run(() => submitJob(c, "VALIDATE", { esl_run_id: runId })),
        disabledReason: blockReason(allowed, c, 5, prereq),
        busy: act.busy,
      }}
    >
      {!v ? (
        <Empty>{runId ? "아직 검증하지 않았습니다." : "④ ESL을 먼저 계산하세요."}</Empty>
      ) : (
        <>
          <Card title="판정" right={v.verdict === "PASS" ? <Badge kind="ok">PASS</Badge> : <Badge kind="bad">FAIL</Badge>}>
            <div className="stats">
              <Stat label="변위 RMS (상대)" value={sci(v.disp_rms_rel)} hint={crit.disp_rms_rel_max !== undefined ? `기준 ≤ ${sci(crit.disp_rms_rel_max)}` : undefined} />
              <Stat label="반력 (상대)" value={sci(v.reaction_rel)} />
              <Stat label="hotspot 최대 오차" value={pct(Math.max(0, ...v.hotspots.map((h) => h.rel_err)))} hint={crit.hotspot_rel_err_max !== undefined ? `기준 ≤ ${pct(crit.hotspot_rel_err_max)}` : undefined} />
            </div>
            {Object.keys(crit).length > 0 && (
              <div className="small muted">
                기준:{" "}
                {Object.entries(crit)
                  .map(([k, x]) => `${k} = ${x}`)
                  .join(" · ")}
              </div>
            )}
            {v.fail_reasons.length > 0 && (
              <ul className="reasons">
                {v.fail_reasons.map((f) => (
                  <li key={f} className="bad-text">
                    {f}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <div className="grid2">
            <Card title="hotspot ε_eq 오차">
              <table className="tbl compact">
                <thead>
                  <tr>
                    <th>요소</th>
                    <th>ε (Radioss)</th>
                    <th>ε (검증)</th>
                    <th>오차</th>
                  </tr>
                </thead>
                <tbody>
                  {v.hotspots.map((h) => {
                    const over = crit.hotspot_rel_err_max !== undefined && h.rel_err > crit.hotspot_rel_err_max;
                    return (
                      <tr key={h.elem_id} className={over ? "bad-row" : undefined}>
                        <td>{h.elem_id}</td>
                        <td>{h.eps_rad.toFixed(4)}</td>
                        <td>{h.eps_val.toFixed(4)}</td>
                        <td>{pct(h.rel_err)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>
            <Card title="제외 요소">
              {v.excluded.length ? (
                <table className="tbl compact">
                  <thead>
                    <tr>
                      <th>요소</th>
                      <th>사유</th>
                    </tr>
                  </thead>
                  <tbody>
                    {v.excluded.map((x) => (
                      <tr key={x.elem_id}>
                        <td>{x.elem_id}</td>
                        <td>{x.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty>없음</Empty>
              )}
            </Card>
          </div>
        </>
      )}
    </StageFrame>
  );
}
