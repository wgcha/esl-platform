import type { JobOut } from "../api/types";
import { JOB_TYPE_LABEL, currentStepKey, stepLabel } from "../api/history";
import { JobStatusBadge } from "../components/ui";
import { runningJobs, useRunStatus } from "../shell/RunStatus";
import { DrawerSection } from "./DrawerSection";

function JobRow({ j }: { j: JobOut }) {
  const step = j.state === "RUNNING" ? currentStepKey(j) : null;
  return (
    <li className={`qrow ${j.state.toLowerCase()}`}>
      <span className="qtitle">
        {JOB_TYPE_LABEL[j.job_type] ?? j.job_type}
        {step && JOB_STEP_LABELLED.has(j.job_type) && (
          <span className="small muted" title={step}>
            {" "}
            · {stepLabel(step)}
          </span>
        )}
      </span>
      <span className="qmeta ellipsis" title={j.case_id ?? j.analysis_id ?? j.comparison_id ?? j.opt_run_id ?? undefined}>
        {j.created_by_name}
        {j.queue_position ? ` #${j.queue_position}` : ""}
      </span>
      <JobStatusBadge state={j.state} />
    </li>
  );
}

/** 단계 라벨을 붙이는 작업(단계 이름이 사용자에게 의미 있는 것) */
const JOB_STEP_LABELLED = new Set<string>(["OPT_RUN"]);

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
