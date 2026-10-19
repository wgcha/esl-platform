import type { ReactNode } from "react";
import type { Case, Job, StageStatus } from "../api/types";
import { JobProgress } from "../components/JobProgress";
import { ErrorLine, PrimaryButton } from "../components/ui";

export interface StageProps {
  c: Case;
  reload: () => Promise<void>;
  allowed: boolean;
}

export const STALE_TEXT = "이전 단계가 바뀌었습니다 — 다시 실행";

/** 단계 공통 틀: 제목·stale/실패 안내·주 버튼 1개·작업 진행·단일 결과 뷰 */
export function StageFrame({
  title,
  status,
  primary,
  error,
  onJobDone,
  children,
}: {
  title: string;
  status: StageStatus | undefined;
  primary: { label: string; onClick: () => void; disabledReason?: string | null; busy?: boolean };
  error?: string | null;
  onJobDone?: (j: Job) => void;
  children: ReactNode;
}) {
  const st = status?.state ?? "none";
  return (
    <>
      <div className="page-title-row stage-head">
        <h2 className="page-title">{title}</h2>
        <span className="spacer" />
        <PrimaryButton {...primary} />
      </div>
      {st === "stale" && (
        <div className="warn-box" role="status" data-testid="stale-banner">
          {STALE_TEXT}
        </div>
      )}
      <ErrorLine text={error} />
      {status?.job_id && (st === "running" || st === "failed") && <JobProgress jobId={status.job_id} onDone={onJobDone} />}
      {children}
    </>
  );
}
