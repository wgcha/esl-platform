import { useCallback, useEffect } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { canRun, useApp } from "../app/AppContext";
import { MENU_CREATE, Shell } from "../shell/Shell";
import { N_STEPS, StageStepper, stepLabel } from "../shell/StageStepper";
import { usePolling } from "../lib/usePolling";
import { Empty, ErrorLine } from "../components/ui";
import type { StageProps } from "../stages/StageFrame";
import { Stage1 } from "../stages/Stage1";
import { Stage2 } from "../stages/Stage2";
import { Stage4 } from "../stages/Stage4";
import { Stage5 } from "../stages/Stage5";
import type { ComponentType } from "react";
import { BundleButton } from "../components/BundleButton";
import { p3 } from "../api/p3";
import { rememberCase } from "../lib/recent";
import { CumulativeBadge } from "../components/Cumulative";

/** 화면 단계 ①입력 ②t*·지지점 ③ESL ④검증 (v0.10.0, esl_menu_restructure.md §4.3) — 파일 이름은 옛 번호 그대로 */
const STEPS: ComponentType<StageProps>[] = [Stage1, Stage2, Stage4, Stage5];

export const MOVED_EXPORT_TEXT = "⑥ 내보내기 단계는 없어졌습니다 — Case 결과는 상단 [결과 받기(zip)], 비드 최적화·강성 평가는 등록 후 ESL 라이브러리에서";

export function CasePage() {
  const { projectId = "", caseId = "", n = "1" } = useParams();
  const [sp] = useSearchParams();
  const step = Number(n);
  const { me, projects } = useApp();
  const cs = usePolling(() => api.getCase(caseId), 0, [caseId]);
  const c = cs.data;
  const anyRunning = !!c && Object.values(c.step_status ?? c.stage_status ?? {}).some((s) => s.state === "running");
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

  if (!(step >= 1 && step <= N_STEPS)) return <Navigate to={`/p/${projectId}/c/${caseId}/step/1`} replace />;
  const project = projects.find((p) => p.id === projectId);
  const base = `/p/${projectId}/c/${caseId}`;
  const Step = STEPS[step - 1];
  return (
    <Shell
      projectId={projectId}
      crumbs={[
        { label: project?.name ?? projectId, to: `/p/${projectId}` },
        { label: MENU_CREATE, to: `/p/${projectId}` },
        { label: c?.title ?? "Case", to: `${base}/step/1` },
        { label: stepLabel(step) },
      ]}
      stepper={
        <div className="case-bar">
          <StageStepper base={base} current={step} c={c} />
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
      {sp.get("moved") === "export" && (
        <div className="info-box" role="status" data-testid="moved-export">
          {MOVED_EXPORT_TEXT} · <Link to={`/p/${projectId}/library`}>ESL 라이브러리 열기</Link>
        </div>
      )}
      <ErrorLine text={cs.error} />
      {c ? <Step key={`${caseId}-${step}`} c={c} reload={reloadCase} allowed={canRun(me, projectId)} /> : !cs.error && <Empty>불러오는 중…</Empty>}
    </Shell>
  );
}
