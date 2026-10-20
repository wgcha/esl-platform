import { api } from "../api/endpoints";
import type { JobOut } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { JobStatusBadge } from "../components/ui";

const TYPE_LABEL: Record<string, string> = {
  CASE_EXTRACT: "추출",
  ESL_SOLVE: "ESL 계산",
  VALIDATE: "검증",
  EXPORT: "내보내기",
  CASE_REPORT: "보고서",
  LIB_ANALYZE: "종합분석",
  LIB_COMPARE: "버전 비교",
};

function JobRow({ j }: { j: JobOut }) {
  return (
    <li className={`qrow ${j.state.toLowerCase()}`}>
      <span className="qtitle">{TYPE_LABEL[j.job_type] ?? j.job_type}</span>
      <span className="qmeta ellipsis" title={j.case_id ?? j.analysis_id ?? j.comparison_id ?? undefined}>
        {j.created_by_name}
        {j.queue_position ? ` #${j.queue_position}` : ""}
      </span>
      <JobStatusBadge state={j.state} />
    </li>
  );
}

/** 대기열·워커 상태 (5초 갱신). PhysicsAI 우측 패널과 같은 카드(.panel) 구성. */
export function RightPanel() {
  const queue = usePolling(api.queue, 5000);
  const status = usePolling(api.status, 5000);
  const q = queue.data;
  const s = status.data;
  // §6: SLOT 레인 동시 실행(최대 slots 개) — running_all, 이전 서버 응답이면 running 하나
  const runningAll = q ? (q.running_all?.length ? q.running_all : q.running ? [q.running] : []) : [];
  const slots = q?.slots ?? 1;
  const slot = q ? [...runningAll, ...q.queued] : [];
  const light = q ? [...(q.light.running ? [q.light.running] : []), ...q.light.queued] : [];
  return (
    <aside className="rightpanel" aria-label="대기열·워커">
      <section className="panel" aria-label="워커">
        <header className="panel-head">
          <h2>워커</h2>
        </header>
        {s ? (
          <div className="worker-line">
            <span className={`dot ${s.worker.online ? "ok" : "bad"}`} />
            <span>{s.worker.online ? "동작 중" : "응답 없음"}</span>
            <span className="muted" title={`사용 가능: ${s.tools.solver_backends_available.join(", ")}`}>
              · 솔버 {s.tools.solver_backend}
            </span>
            {!s.config.ok && <div className="small error-text">설정 오류: {s.config.errors.map((e) => `${e.key}: ${e.message}`).join(", ")}</div>}
          </div>
        ) : (
          <div className="empty small">{status.error ?? "불러오는 중…"}</div>
        )}
      </section>
      <section className="panel" aria-label="계산 대기열">
        <header className="panel-head">
          <h2>계산 대기열</h2>
          {q && (
            <span className="slots-meta" data-testid="queue-slots" title="동시에 실행하는 계산 수(설정 worker.slots)">
              동시 실행 {runningAll.length}/{slots}
            </span>
          )}
        </header>
        {q ? (
          slot.length ? (
            <ul className="qlist">
              {slot.map((j) => (
                <JobRow key={j.id} j={j} />
              ))}
            </ul>
          ) : (
            <div className="empty small">없음</div>
          )
        ) : (
          <div className="empty small">{queue.error ?? "불러오는 중…"}</div>
        )}
      </section>
      {light.length > 0 && (
        <section className="panel" aria-label="보고서·내보내기 대기열">
          <header className="panel-head">
            <h2>보고서·내보내기 대기열</h2>
          </header>
          <ul className="qlist">
            {light.map((j) => (
              <JobRow key={j.id} j={j} />
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}
