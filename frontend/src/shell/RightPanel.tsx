import { api } from "../api/endpoints";
import type { JobOut } from "../api/types";
import { usePolling } from "../lib/usePolling";
import { JOB_STATE_LABEL } from "../lib/format";

const TYPE_LABEL: Record<string, string> = { CASE_EXTRACT: "추출", ESL_SOLVE: "ESL 계산", VALIDATE: "검증", EXPORT: "내보내기" };

function JobRow({ j }: { j: JobOut }) {
  return (
    <li className={`qrow ${j.state.toLowerCase()}`}>
      <span className="qtype">{TYPE_LABEL[j.job_type] ?? j.job_type}</span>
      <span className="qcase" title={j.case_id}>
        {j.created_by_name}
        {j.queue_position ? ` #${j.queue_position}` : ""}
      </span>
      <span className="qstate">{JOB_STATE_LABEL[j.state]}</span>
    </li>
  );
}

/** 대기열·워커 상태 (5초 갱신) */
export function RightPanel() {
  const queue = usePolling(api.queue, 5000);
  const status = usePolling(api.status, 5000);
  const q = queue.data;
  const s = status.data;
  const slot = q ? [...(q.running ? [q.running] : []), ...q.queued] : [];
  const light = q ? [...(q.light.running ? [q.light.running] : []), ...q.light.queued] : [];
  return (
    <aside className="panel" aria-label="대기열·워커">
      <section>
        <h3>워커</h3>
        {s ? (
          <div className="kv">
            <span className={`dot ${s.worker.online ? "ok" : "bad"}`} />
            <span>{s.worker.online ? "동작 중" : "응답 없음"}</span>
            <span className="muted" title={`사용 가능: ${s.tools.solver_backends_available.join(", ")}`}>
              {" "}
              · 솔버 {s.tools.solver_backend}
            </span>
            {!s.config.ok && <div className="small bad-text">설정 오류: {s.config.errors.map((e) => `${e.key}: ${e.message}`).join(", ")}</div>}
          </div>
        ) : (
          <div className="muted">{status.error ?? "불러오는 중…"}</div>
        )}
      </section>
      <section>
        <h3>계산 대기열</h3>
        {q ? slot.length ? <ul className="qlist">{slot.map((j) => <JobRow key={j.id} j={j} />)}</ul> : <div className="muted">비어 있음</div> : <div className="muted">{queue.error ?? "불러오는 중…"}</div>}
      </section>
      {light.length > 0 && (
        <section>
          <h3>내보내기 대기열</h3>
          <ul className="qlist">{light.map((j) => <JobRow key={j.id} j={j} />)}</ul>
        </section>
      )}
    </aside>
  );
}
