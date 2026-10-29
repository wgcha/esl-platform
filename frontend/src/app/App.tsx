import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { AppProvider } from "./AppContext";
import { RunStatusProvider } from "../shell/RunStatus";
import { ProjectList } from "../pages/ProjectList";
import { CaseList } from "../pages/CaseList";
import { CasePage } from "../pages/CasePage";
import { LibraryList } from "../pages/library/LibraryList";
import { AnalysisNew } from "../pages/library/AnalysisNew";
import { AnalysisDetail } from "../pages/library/AnalysisDetail";
import { ComparisonNew } from "../pages/library/ComparisonNew";
import { ComparisonDetail } from "../pages/library/ComparisonDetail";
import { NewCase } from "../pages/newcase/NewCase";
import { Updates } from "../pages/Updates";
import { Guide } from "../pages/guide/Guide";
import { CaseHistory } from "../pages/history/CaseHistory";
import { ProjectHistory } from "../pages/history/ProjectHistory";
import { JobReview } from "../pages/history/JobReview";
import { OptNew } from "../pages/opt/OptNew";
import { OptDetail } from "../pages/opt/OptDetail";
import { DoeStudy } from "../pages/doe/DoeStudy";
import { stepOfStage } from "../shell/StageStepper";

/** 옛 북마크 /stage/:n(1..6) → /step/:m (계약 esl_menu_restructure.md §4.2). query(?run·?val) 유지, ⑥은 ?moved=export 안내 */
export function StageRedirect() {
  const { projectId = "", caseId = "", n = "1" } = useParams();
  const loc = useLocation();
  const old = Number(n);
  const q = new URLSearchParams(loc.search);
  if (old === 6) q.set("moved", "export");
  const qs = q.toString();
  return <Navigate to={`/p/${projectId}/c/${caseId}/step/${stepOfStage(old)}${qs ? `?${qs}` : ""}`} replace />;
}

/** 라이브러리 옛 탭 키: ?tab=doe → study, ?tab=comparisons → analyses#comparisons. 그 외는 그대로 */
function LibraryRoute() {
  const loc = useLocation();
  const q = new URLSearchParams(loc.search);
  const t = q.get("tab");
  if (t === "doe" || t === "comparisons") {
    q.set("tab", t === "doe" ? "study" : "analyses");
    return <Navigate to={{ pathname: loc.pathname, search: `?${q}`, hash: t === "comparisons" ? "#comparisons" : loc.hash }} replace />;
  }
  return <LibraryList />;
}

export function App() {
  const loc = useLocation();
  // 화면 오류 경계: 바깥(공통 컨텍스트 포함) + 페이지 단위(경로가 바뀌면 자동 해제)
  return (
    <ErrorBoundary>
    <AppProvider>
      <RunStatusProvider>
      <ErrorBoundary resetKey={loc.pathname + loc.search}>
      <Routes>
        <Route path="/" element={<ProjectList />} />
        <Route path="/p/:projectId" element={<CaseList />} />
        <Route path="/p/:projectId/cases/new" element={<NewCase />} />
        <Route path="/updates" element={<Updates />} />
        <Route path="/guide" element={<Guide />} />
        <Route path="/p/:projectId/c/:caseId/step/:n" element={<CasePage />} />
        <Route path="/p/:projectId/c/:caseId/stage/:n" element={<StageRedirect />} />
        <Route path="/p/:projectId/c/:caseId/history" element={<CaseHistory />} />
        <Route path="/p/:projectId/history" element={<ProjectHistory />} />
        <Route path="/p/:projectId/jobs/:jobId" element={<JobReview />} />
        <Route path="/p/:projectId/c/:caseId" element={<Navigate to="step/1" replace />} />
        <Route path="/p/:projectId/library" element={<LibraryRoute />} />
        <Route path="/p/:projectId/library/analyses/new" element={<AnalysisNew />} />
        <Route path="/p/:projectId/library/analyses/:analysisId" element={<AnalysisDetail />} />
        <Route path="/p/:projectId/library/comparisons/new" element={<ComparisonNew />} />
        <Route path="/p/:projectId/library/comparisons/:comparisonId" element={<ComparisonDetail />} />
        <Route path="/p/:projectId/opt" element={<Navigate to="../library?tab=opt" relative="path" replace />} />
        <Route path="/p/:projectId/opt/new" element={<OptNew />} />
        <Route path="/p/:projectId/opt/:optId" element={<OptDetail />} />
        <Route path="/p/:projectId/doe" element={<Navigate to="../library?tab=study" relative="path" replace />} />
        <Route path="/p/:projectId/doe/:doeId" element={<DoeStudy />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </ErrorBoundary>
      </RunStatusProvider>
    </AppProvider>
    </ErrorBoundary>
  );
}
