import { useCallback, useEffect } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { canRun, useApp } from "../app/AppContext";
import { Shell } from "../shell/Shell";
import { STAGE_NAMES, StageStepper } from "../shell/StageStepper";
import { usePolling } from "../lib/usePolling";
import { Empty, ErrorLine } from "../components/ui";
import type { StageProps } from "../stages/StageFrame";
import { Stage1 } from "../stages/Stage1";
import { Stage2 } from "../stages/Stage2";
import { Stage3 } from "../stages/Stage3";
import { Stage4 } from "../stages/Stage4";
import { Stage5 } from "../stages/Stage5";
import { Stage6 } from "../stages/Stage6";
import type { ComponentType } from "react";
import { BundleButton } from "../components/BundleButton";
import { p3 } from "../api/p3";
import { rememberCase } from "../lib/recent";
import { CumulativeBadge } from "../components/Cumulative";

const STAGES: ComponentType<StageProps>[] = [Stage1, Stage2, Stage3, Stage4, Stage5, Stage6];

export function CasePage() {
  const { projectId = "", caseId = "", n = "1" } = useParams();
  const stage = Number(n);
  const { me, projects } = useApp();
  const cs = usePolling(() => api.getCase(caseId), 0, [caseId]);
  const c = cs.data;
  const anyRunning = !!c && Object.values(c.stage_status ?? {}).some((s) => s.state === "running");
  const { reload } = cs;

  // 실행 중 작업이 있으면 Case 상태를 2초마다 갱신
  useEffect(() => {
    if (!anyRunning) return;
    const t = setInterval(() => void reload(), 2000);
    return () => clearInterval(t);
  }, [anyRunning, reload]);

  const reloadCase = useCallback(() => reload(), [reload]);
  useEffect(() => {
    if (c) rememberCase({ projectId, caseId, title: c.title });
  }, [projectId, caseId, c?.title]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!(stage >= 1 && stage <= 6)) return <Navigate to={`/p/${projectId}/c/${caseId}/stage/1`} replace />;
  const project = projects.find((p) => p.id === projectId);
  const base = `/p/${projectId}/c/${caseId}`;
  const Stage = STAGES[stage - 1];
  return (
    <Shell
      projectId={projectId}
      crumbs={[
        { label: project?.name ?? projectId, to: `/p/${projectId}` },
        { label: c?.title ?? "Case", to: `${base}/stage/1` },
        { label: `${"①②③④⑤⑥"[stage - 1]} ${STAGE_NAMES[stage - 1]}` },
      ]}
      stepper={
        <div className="case-bar">
          <StageStepper base={base} current={stage} status={c?.stage_status} />
          {c && (
            <nav className="case-menu" aria-label="Case 메뉴">
              <CumulativeBadge s={c.extract_summary?.cumulative} />
              <Link to={`${base}/history`} className="case-menu-link">
                실행 이력
              </Link>
              <BundleButton url={p3.caseBundleUrl(c.id)} filename={`${c.folder_name}_result.zip`} fallbackPath={c.folder_path} />
            </nav>
          )}
        </div>
      }
    >
      <ErrorLine text={cs.error} />
      {c ? <Stage key={`${caseId}-${stage}`} c={c} reload={reloadCase} allowed={canRun(me, projectId)} /> : !cs.error && <Empty>불러오는 중…</Empty>}
    </Shell>
  );
}
