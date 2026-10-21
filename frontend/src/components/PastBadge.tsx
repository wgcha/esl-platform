import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { STALE_REASON_LABEL, type ReviewOut } from "../api/history";
import { dt } from "../lib/format";
import { DiffTable } from "./DiffTable";
import { Badge, ErrorLine } from "./ui";

export const PAST_FILES_GONE = "파일 보존 안 됨 — 기록된 값만 표시";

/** 배지 "과거 실행 · <시각>" */
export function PastBadge({ at }: { at: string | null | undefined }) {
  return (
    <span className="past-badge" data-testid="past-badge">
      과거 실행 · {dt(at)}
    </span>
  );
}

/** '입력 바뀜' 칩(사유는 툴팁) */
export function StaleChip({ reasons }: { reasons: string[] }) {
  if (!reasons.length) return null;
  return (
    <span title={reasons.map((r) => STALE_REASON_LABEL[r] ?? r).join(" · ")} data-testid="stale-chip">
      <Badge kind="warn">입력 바뀜</Badge>
    </span>
  );
}

/** 과거 결과 읽기 전용 화면의 틀: 제목 · 배지 · 입력 바뀜 칩 · 현재와 다른 점 · "현재 결과로" 링크 1개. 실행 버튼은 없다. */
export function PastFrame({
  title,
  review,
  error,
  currentHref,
  children,
}: {
  title: string;
  review: ReviewOut | null;
  error?: string | null;
  currentHref: string;
  children: ReactNode;
}) {
  const res = review?.result;
  return (
    <div data-testid="past-frame">
      <div className="page-title-row stage-head">
        <h2 className="page-title">{title}</h2>
        <PastBadge at={review?.job.finished_at ?? review?.job.created_at} />
        {res && <StaleChip reasons={res.stale_reasons} />}
        <span className="spacer" />
        <Link to={currentHref} className="past-link">
          현재 결과로
        </Link>
      </div>
      <ErrorLine text={error} />
      {res && res.diff.length > 0 && <DiffTable diff={res.diff} />}
      {res?.availability === "summary" && (
        <div className="warn-box" role="status" data-testid="files-gone">
          {res.files_note ?? PAST_FILES_GONE}
        </div>
      )}
      {children}
    </div>
  );
}
