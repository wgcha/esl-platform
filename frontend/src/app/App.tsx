import { Navigate, Route, Routes, useLocation } from "react-router-dom";
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
        <Route path="/p/:projectId/c/:caseId/stage/:n" element={<CasePage />} />
        <Route path="/p/:projectId/c/:caseId/history" element={<CaseHistory />} />
        <Route path="/p/:projectId/history" element={<ProjectHistory />} />
        <Route path="/p/:projectId/jobs/:jobId" element={<JobReview />} />
        <Route path="/p/:projectId/c/:caseId" element={<Navigate to="stage/1" replace />} />
        <Route path="/p/:projectId/library" element={<LibraryList />} />
        <Route path="/p/:projectId/library/analyses/new" element={<AnalysisNew />} />
        <Route path="/p/:projectId/library/analyses/:analysisId" element={<AnalysisDetail />} />
        <Route path="/p/:projectId/library/comparisons/new" element={<ComparisonNew />} />
        <Route path="/p/:projectId/library/comparisons/:comparisonId" element={<ComparisonDetail />} />
        <Route path="/p/:projectId/opt" element={<Navigate to="../library?tab=opt" relative="path" replace />} />
        <Route path="/p/:projectId/opt/new" element={<OptNew />} />
        <Route path="/p/:projectId/opt/:optId" element={<OptDetail />} />
        <Route path="/p/:projectId/doe" element={<Navigate to="../library?tab=doe" relative="path" replace />} />
        <Route path="/p/:projectId/doe/:doeId" element={<DoeStudy />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </ErrorBoundary>
      </RunStatusProvider>
    </AppProvider>
    </ErrorBoundary>
  );
}
