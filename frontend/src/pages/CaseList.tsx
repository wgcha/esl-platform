import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { errorText } from "../api/client";
import type { Case } from "../api/types";
import { NO_PERMISSION, canRun, useApp } from "../app/AppContext";
import { Shell } from "../shell/Shell";
import { STAGE_NAMES } from "../shell/StageStepper";
import { Empty, ErrorLine, Field, PrimaryButton } from "../components/ui";
import { RadInspectView, ResultsInspectView, usePathInspect } from "../components/PathInspect";
import { usePolling } from "../lib/usePolling";
import { dt } from "../lib/format";

function progressOf(c: Case) {
  const st = c.stage_status ?? {};
  let last = 0;
  for (let n = 1; n <= 6; n++) if (st[String(n)]?.state === "done" || st[String(n)]?.state === "stale") last = n;
  const running = Object.entries(st).find(([, s]) => s.state === "running");
  if (running) return `${STAGE_NAMES[Number(running[0]) - 1]} 실행 중`;
  return last ? `${STAGE_NAMES[last - 1]}까지 완료` : "시작 전";
}

function NewCaseForm({ projectId, onCancel }: { projectId: string; onCancel: () => void }) {
  const nav = useNavigate();
  const [folder, setFolder] = useState("");
  const [title, setTitle] = useState("");
  const [partTitle, setPartTitle] = useState("");
  const rad = usePathInspect("RAD");
  const res = usePathInspect("RESULTS");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reason = !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(folder)
    ? "폴더 이름을 입력하세요(영문·숫자·_·-)"
    : !rad.result?.ok
      ? "rad 경로를 '확인'하세요"
      : !res.result?.ok
        ? "결과 폴더를 '확인'하세요"
        : null;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const c = await api.createCase({
        project_id: projectId,
        folder_name: folder,
        title: title || folder,
        rad_path: rad.result!.normalized_path,
        results_dir: res.result!.normalized_path ?? res.path,
        part_title: partTitle || undefined,
      });
      nav(`/p/${projectId}/c/${c.id}/stage/1`);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <section className="card new-case" aria-label="새 Case">
      <header className="card-head">
        <h3>새 Case</h3>
      </header>
      <div className="card-body">
        <div className="form-grid">
          <Field label="폴더 이름">
            <input className="mono" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="rear40" />
          </Field>
          <Field label="제목">
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="후방 충돌 40kph" />
          </Field>
        </div>
        {rad.field("rad 경로 (_0000.rad)", "D:\\ESL_INPUT\\...\\model_0000.rad")}
        {rad.result && <RadInspectView r={rad.result} partTitle={partTitle} />}
        {res.field("결과 폴더 (TCL 출력)", "D:\\ESL_INPUT\\...\\h3d_csv")}
        {res.result && <ResultsInspectView r={res.result} />}
        <Field label="파트 title">
          <input value={partTitle} onChange={(e) => setPartTitle(e.target.value)} placeholder="비우면 설정 기본값" />
        </Field>
        <ErrorLine text={error} />
        <div className="actions">
          <PrimaryButton label="Case 만들기" onClick={create} disabledReason={reason} busy={busy} />
          <button type="button" className="btn ghost" onClick={onCancel}>
            닫기
          </button>
        </div>
      </div>
    </section>
  );
}

export function CaseList() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const project = projects.find((p) => p.id === projectId);
  const cases = usePolling(() => api.cases(projectId), 5000, [projectId]);
  const [open, setOpen] = useState(false);
  const allowed = canRun(me, projectId);
  return (
    <Shell crumbs={[{ label: project?.name ?? projectId }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">Case 목록</h1>
        <span className="spacer" />
        {!open && (
          <span className="primary-wrap" title={allowed ? undefined : NO_PERMISSION}>
            <button type="button" className="btn primary" disabled={!allowed} onClick={() => setOpen(true)}>
              새 Case
            </button>
          </span>
        )}
      </div>
      {open && <NewCaseForm projectId={projectId} onCancel={() => setOpen(false)} />}
      <ErrorLine text={cases.error} />
      {cases.data && cases.data.length === 0 && <Empty>아직 Case가 없습니다</Empty>}
      {cases.data && cases.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Case</th>
              <th>폴더</th>
              <th>진행</th>
              <th>만든 사람</th>
              <th className="num">수정</th>
            </tr>
          </thead>
          <tbody>
            {cases.data.map((c) => (
              <tr key={c.id}>
                <td>
                  <Link to={`/p/${projectId}/c/${c.id}/stage/1`}>{c.title}</Link>
                </td>
                <td className="mono">{c.folder_name}</td>
                <td>{progressOf(c)}</td>
                <td>{c.created_by_name}</td>
                <td className="num">{dt(c.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Shell>
  );
}
