import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorText } from "../api/client";
import { JOB_TYPE_LABEL, durText, history, summaryText, type HistoryItem, type HistoryQuery } from "../api/history";
import { dt } from "../lib/format";
import { Badge, Empty, ErrorLine, JobStatusBadge } from "./ui";

import { STEP_MARKS, stepOfStage } from "../shell/StageStepper";

/** 작업 단계 표식: 옛 jobs.stage(1..6) → 화면 단계(①~④) */
const stageMark = (stage: number) => (stage >= 1 && stage <= 6 ? STEP_MARKS[stepOfStage(stage) - 1] : "");

/** 결과 칩: 현재 / 과거 / 입력 바뀜 */
function ResultChips({ it }: { it: HistoryItem }) {
  if (!it.result_ref) return <span className="muted">–</span>;
  return (
    <span className="inline-actions">
      {it.result_state === "current" && <Badge kind="ok">현재</Badge>}
      {it.result_state === "past" && <Badge kind="info">과거</Badge>}
      {it.stale && (
        <span title="이 결과를 만든 뒤 입력이 바뀜">
          <Badge kind="warn">입력 바뀜</Badge>
        </span>
      )}
    </span>
  );
}

export function HistoryTable({ items, projectId, showCase }: { items: HistoryItem[]; projectId: string; showCase: boolean }) {
  const nav = useNavigate();
  return (
    <div className="table-wrap scroll">
      <table className="table history-table" aria-label="실행 이력">
        <thead>
          <tr>
            <th>시각</th>
            <th>단계·작업</th>
            {showCase && <th>Case</th>}
            <th>상태</th>
            <th className="num">소요</th>
            <th>실행자</th>
            <th>결과</th>
            <th>요약</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const to = `/p/${projectId}/jobs/${it.id}`;
            return (
              <tr key={it.id} className="click-row" data-testid="history-row" onClick={() => nav(to)}>
                <td>
                  <Link to={to} onClick={(e) => e.stopPropagation()}>
                    {dt(it.created_at)}
                  </Link>
                </td>
                <td>
                  <span className="stage-mark" aria-hidden="true">
                    {stageMark(it.stage) || "◆"}
                  </span>{" "}
                  {JOB_TYPE_LABEL[it.job_type]}
                </td>
                {showCase && <td>{it.case_title ?? it.subject_title ?? "라이브러리"}</td>}
                <td>
                  <JobStatusBadge state={it.state} />
                </td>
                <td className="num">{durText(it.duration_s)}</td>
                <td>{it.created_by_name}</td>
                <td>
                  <ResultChips it={it} />
                </td>
                <td className="small muted">{summaryText(it)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 이력 목록 + "더 보기"(keyset 커서). query 가 바뀌면 처음부터 다시 읽는다. */
export function HistoryList({ query, projectId, showCase }: { query: Omit<HistoryQuery, "cursor">; projectId: string; showCase: boolean }) {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify(query);
  const seq = useRef(0);

  const load = useCallback(
    async (cur: string | null, append: boolean) => {
      const my = ++seq.current;
      setBusy(true);
      try {
        const page = await history.list({ ...query, cursor: cur, limit: query.limit ?? 30 });
        if (my !== seq.current) return;
        setItems((old) => (append && old ? [...old, ...page.items] : page.items));
        setCursor(page.next_cursor);
        setMore(page.has_more);
        setError(null);
      } catch (e) {
        if (my === seq.current) setError(errorText(e));
      } finally {
        if (my === seq.current) setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );

  useEffect(() => {
    setItems(null);
    void load(null, false);
  }, [load]);

  return (
    <>
      <ErrorLine text={error} />
      {items === null && !error && <Empty>불러오는 중…</Empty>}
      {items && items.length === 0 && <Empty>조건에 맞는 실행 이력이 없습니다</Empty>}
      {items && items.length > 0 && <HistoryTable items={items} projectId={projectId} showCase={showCase} />}
      {items && more && (
        <div className="history-more">
          <button type="button" className="btn" disabled={busy} onClick={() => void load(cursor, true)}>
            {busy ? "불러오는 중…" : "더 보기"}
          </button>
        </div>
      )}
    </>
  );
}
