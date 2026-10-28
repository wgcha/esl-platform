import type { JobOut } from "../api/types";
import { JobStatusBadge } from "../components/ui";
import { runningJobs, useRunStatus } from "../shell/RunStatus";
import { DrawerSection } from "./DrawerSection";

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

/** 계산 대기열(SLOT 레인 실행·대기). 값은 RunStatusProvider 의 폴링 결과. */
export function QueuePanel() {
  const { queue: q, queueError } = useRunStatus();
  if (!q) return <div className="empty small">{queueError ?? "불러오는 중…"}</div>;
  const slot = [...runningJobs(q), ...q.queued];
  return slot.length ? (
    <ul className="qlist">
      {slot.map((j) => (
        <JobRow key={j.id} j={j} />
      ))}
    </ul>
  ) : (
    <div className="empty small">없음</div>
  );
}

/** 보고서·내보내기 대기열(LIGHT 레인) — 있을 때만 구획을 만든다 */
export function LightQueueSection() {
  const { queue: q } = useRunStatus();
  if (!q) return null;
  const light = [...(q.light.running ? [q.light.running] : []), ...q.light.queued];
  if (!light.length) return null;
  return (
    <DrawerSection title="보고서·내보내기 대기열" id="drawer-light">
      <ul className="qlist">
        {light.map((j) => (
          <JobRow key={j.id} j={j} />
        ))}
      </ul>
    </DrawerSection>
  );
}
