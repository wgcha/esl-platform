import { useSearchParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { warnText } from "../api/client";
import { history } from "../api/history";
import { PastFrame } from "../components/PastBadge";
import { Badge, Card, Empty, Stat } from "../components/ui";
import { LoadTable } from "../view3d/LoadTable";
import { View3DCard } from "../view3d/View3DCard";
import { useLoadView } from "../view3d/useLoadView";
import { usePolling } from "../lib/usePolling";
import { METRIC_LABEL, fmtFixed, pct, sci, vec } from "../lib/format";
import { StageFrame, type StageProps } from "./StageFrame";
import { blockReason, eslPrereq, submitJob, useAction } from "./common";
import { dofText } from "../lib/format";
import { stepPath, stepState } from "../shell/StageStepper";

export function Stage4({ c, reload, allowed }: StageProps) {
  const [sp] = useSearchParams();
  const pastRunId = sp.get("run"); // 과거 실행 읽기 전용(?run=)
  const runId = pastRunId ?? c.current_esl_run_id;
  const run = usePolling(() => (runId ? api.eslRun(runId) : Promise.resolve(null)), 0, [runId, c.version]);
  const sets = usePolling(() => (c.current_support_set_id ? api.supportSets(c.id) : Promise.resolve([])), 0, [c.current_support_set_id]);
  const support = sets.data?.find((s) => s.id === c.current_support_set_id);
  const act = useAction(reload);
  const r = run.data;
  const pastJobId = pastRunId ? r?.job_id ?? null : null;
  const review = usePolling(() => (pastJobId ? history.review(pastJobId) : Promise.resolve(null)), 0, [pastJobId]);

  // 3D 하중 보기 + 상위 표(과거 실행은 availability = full 일 때만)
  const showLoad = !!r && !(pastRunId && review.data?.result.availability !== "full");
  const view = useLoadView(runId ?? null, showLoad);

  const prereq = eslPrereq(c);

  const content = (
    <>
      {!pastRunId && (
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
      )}
      {!runId ? (
        <Empty>아직 ESL을 계산하지 않았습니다</Empty>
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
                    {warnText(w)}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {showLoad && view && (
            <>
              <View3DCard view={view} />
              {c.extract_summary?.cumulative && (
                <div className="small muted" data-testid="v3d-state-note">
                  형상: 이전 런 변형 상태
                </div>
              )}
              <LoadTable view={view} />
            </>
          )}
        </>
      )}
    </>
  );
  if (pastRunId)
    return (
      <PastFrame title="③ ESL" review={review.data} error={run.error ?? review.error} currentHref={stepPath(c.project_id, c.id, 3)}>
        {content}
      </PastFrame>
    );
  return (
    <StageFrame
      title="③ ESL"
      status={stepState(c, 3)}
      error={act.error ?? run.error}
      onJobDone={() => void reload()}
      primary={{ label: "ESL 계산", onClick: () => act.run(() => submitJob(c, "ESL_SOLVE")), disabledReason: blockReason(allowed, c, 3, prereq), busy: act.busy }}
    >
      {content}
    </StageFrame>
  );
}
