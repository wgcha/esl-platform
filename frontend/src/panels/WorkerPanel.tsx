import { useRunStatus } from "../shell/RunStatus";

/** 워커 상태 · 솔버 · 사용 가능 백엔드 · 설정 오류 */
export function WorkerPanel() {
  const { status: s, statusError } = useRunStatus();
  if (!s) return <div className="empty small">{statusError ?? "불러오는 중…"}</div>;
  return (
    <div className="worker-line">
      <span className={`dot ${s.worker.online ? "ok" : "bad"}`} />
      <span>{s.worker.online ? "동작 중" : "응답 없음"}</span>
      <span className="muted" title={`사용 가능: ${s.tools.solver_backends_available.join(", ")}`}>
        · 솔버 {s.tools.solver_backend}
      </span>
      {s.tools.solver_backends_available.length > 0 && <div className="small muted">사용 가능: {s.tools.solver_backends_available.join(", ")}</div>}
      {!s.config.ok && <div className="small error-text">설정 오류: {s.config.errors.map((e) => `${e.key}: ${e.message}`).join(", ")}</div>}
    </div>
  );
}
