import { Navigate, Route, Routes } from "react-router-dom";
import { AppProvider } from "./AppContext";
import { ProjectList } from "../pages/ProjectList";
import { CaseList } from "../pages/CaseList";
import { CasePage } from "../pages/CasePage";
import { LibraryList } from "../pages/library/LibraryList";
import { AnalysisNew } from "../pages/library/AnalysisNew";
import { AnalysisDetail } from "../pages/library/AnalysisDetail";
import { ComparisonNew } from "../pages/library/ComparisonNew";
import { ComparisonDetail } from "../pages/library/ComparisonDetail";

export function App() {
  return (
    <AppProvider>
      <Routes>
        <Route path="/" element={<ProjectList />} />
        <Route path="/p/:projectId" element={<CaseList />} />
        <Route path="/p/:projectId/c/:caseId/stage/:n" element={<CasePage />} />
        <Route path="/p/:projectId/c/:caseId" element={<Navigate to="stage/1" replace />} />
        <Route path="/p/:projectId/library" element={<LibraryList />} />
        <Route path="/p/:projectId/library/analyses/new" element={<AnalysisNew />} />
        <Route path="/p/:projectId/library/analyses/:analysisId" element={<AnalysisDetail />} />
        <Route path="/p/:projectId/library/comparisons/new" element={<ComparisonNew />} />
        <Route path="/p/:projectId/library/comparisons/:comparisonId" element={<ComparisonDetail />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppProvider>
  );
}
