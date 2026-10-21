import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { JOB_TYPE_LABEL, STATE_FILTERS } from "../../api/history";
import type { JobType } from "../../api/types";
import { useApp } from "../../app/AppContext";
import { HistoryList } from "../../components/HistoryTable";
import { Shell } from "../../shell/Shell";

/** 프로젝트 전체 실행 이력: 종류·상태·기간 필터, 검색, '내 작업만'. 필터는 URL query 로 유지. */
export function ProjectHistory() {
  const { projectId = "" } = useParams();
  const { projects } = useApp();
  const [sp, setSp] = useSearchParams();
  const project = projects.find((p) => p.id === projectId);
  const type = sp.get("type") ?? "";
  const state = sp.get("state") ?? "";
  const from = sp.get("from") ?? "";
  const to = sp.get("to") ?? "";
  const q = sp.get("q") ?? "";
  const mine = sp.get("mine") === "1";
  const [qText, setQText] = useState(q);
  useEffect(() => setQText(q), [q]);

  function set(k: string, v: string) {
    setSp(
      (old) => {
        const n = new URLSearchParams(old);
        if (v) n.set(k, v);
        else n.delete(k);
        return n;
      },
      { replace: true },
    );
  }
  // 검색어는 입력이 멈춘 뒤 반영
  useEffect(() => {
    if (qText === q) return;
    const t = setTimeout(() => set("q", qText.trim()), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qText]);

  const query = {
    project_id: projectId,
    job_type: type || undefined,
    state: state || undefined,
    mine: mine || undefined,
    q: q || undefined,
    // 서버는 시간대 없는 값을 UTC 로 읽으므로, 사용자의 현지 하루 경계를 UTC ISO 로 바꿔 보낸다
    from: from ? new Date(`${from}T00:00:00`).toISOString() : undefined,
    to: to ? new Date(`${to}T23:59:59`).toISOString() : undefined,
  };
  return (
    <Shell crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: "실행 이력" }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">실행 이력</h1>
      </div>
      <div className="filters" role="search" aria-label="이력 필터">
        <label className="field">
          <span className="field-label">작업 종류</span>
          <select value={type} onChange={(e) => set("type", e.target.value)}>
            <option value="">전체</option>
            {(Object.keys(JOB_TYPE_LABEL) as JobType[]).map((t) => (
              <option key={t} value={t}>
                {JOB_TYPE_LABEL[t]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">상태</span>
          <select value={state} onChange={(e) => set("state", e.target.value)}>
            {STATE_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">부터</span>
          <input type="date" value={from} onChange={(e) => set("from", e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">까지</span>
          <input type="date" value={to} onChange={(e) => set("to", e.target.value)} />
        </label>
        <label className="field grow">
          <span className="field-label">검색</span>
          <input type="search" placeholder="Case 제목·폴더·작업 id" value={qText} onChange={(e) => setQText(e.target.value)} />
        </label>
        <label className="check-field">
          <input type="checkbox" checked={mine} onChange={(e) => set("mine", e.target.checked ? "1" : "")} /> 내 작업만
        </label>
      </div>
      <HistoryList query={query} projectId={projectId} showCase />
    </Shell>
  );
}
