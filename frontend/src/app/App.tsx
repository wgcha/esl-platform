import { Navigate, Route, Routes } from "react-router-dom";
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

export function App() {
  return (
    <AppProvider>
      <RunStatusProvider>
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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </RunStatusProvider>
    </AppProvider>
  );
}
