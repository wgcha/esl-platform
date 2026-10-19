import { Navigate, Route, Routes } from "react-router-dom";
import { AppProvider } from "./AppContext";
import { ProjectList } from "../pages/ProjectList";
import { CaseList } from "../pages/CaseList";
import { CasePage } from "../pages/CasePage";

export function App() {
  return (
    <AppProvider>
      <Routes>
        <Route path="/" element={<ProjectList />} />
        <Route path="/p/:projectId" element={<CaseList />} />
        <Route path="/p/:projectId/c/:caseId/stage/:n" element={<CasePage />} />
        <Route path="/p/:projectId/c/:caseId" element={<Navigate to="stage/1" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppProvider>
  );
}
