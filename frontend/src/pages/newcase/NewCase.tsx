// 새 Case 화면(계약 esl_p3_ux.md §1·§6): 탭 2개 "내 PC에서 올리기"(기본) / "서버 폴더에서 고르기".
// 입력 = rad(+include) 필수 + h3d(기본, 서버가 추출) 또는 추출 결과 폴더(대안). 고른 뒤 Case 이름·파트 → 주 버튼 "Case 만들기"(화면당 1개).
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { p3 } from "../../api/p3";
import { errorText } from "../../api/client";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { Shell } from "../../shell/Shell";
import { Card, ErrorLine, Field, PrimaryButton } from "../../components/ui";
import { UploadPanel } from "./UploadPanel";
import { ServerPanel } from "./ServerPanel";
import type { InputSelection } from "./types";

export const DEFAULT_PART = "chassis_rear";
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
type Tab = "upload" | "server";
export const TAB_LABEL: Record<Tab, string> = { upload: "내 PC에서 올리기", server: "서버 폴더에서 고르기" };

export function NewCase() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const nav = useNavigate();
  const [qs] = useSearchParams();
  const initialUpload = qs.get("upload");
  const project = projects.find((p) => p.id === projectId);
  const allowed = canRun(me, projectId);
  const [tab, setTabRaw] = useState<Tab>("upload");
  const [serverSeen, setServerSeen] = useState(false);
  const setTab = (t: Tab) => {
    setTabRaw(t);
    if (t === "server") setServerSeen(true);
  };
  const [sel, setSel] = useState<Record<Tab, InputSelection | null>>({ upload: null, server: null });
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [part, setPart] = useState(DEFAULT_PART);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cur = sel[tab];
  const onChange = (t: Tab) => (s: InputSelection | null, suggested?: string) => {
    setSel((old) => ({ ...old, [t]: s }));
    if (suggested && !nameTouched) setName(suggested);
  };
  const partOk = !cur || cur.parts.length === 0 || cur.parts.some((p) => p.title.toLowerCase() === part.trim().toLowerCase());
  const reason = !allowed
    ? NO_PERMISSION
    : !cur
      ? tab === "upload"
        ? "rad와 h3d(또는 결과 폴더)를 올리고 확인을 마치세요"
        : "rad 파일과 h3d(또는 결과 폴더)를 고르세요"
      : !NAME_RE.test(name)
        ? "Case 이름을 입력하세요(영문·숫자·_·-)"
        : !part.trim()
          ? "대상 파트를 입력하세요"
          : !partOk
            ? `파트 '${part}'가 rad에 없습니다`
            : null;

  async function create() {
    if (!cur) return;
    setBusy(true);
    setError(null);
    try {
      const c = await p3.createCase({
        project_id: projectId,
        folder_name: name,
        title: title.trim() || name,
        rad_path: cur.rad_path,
        h3d_path: cur.source.kind === "h3d" ? cur.source.path : null,
        results_dir: cur.source.kind === "results" ? cur.source.path : null,
        part_title: part.trim(),
      });
      nav(`/p/${projectId}/c/${c.id}/stage/1`);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Shell crumbs={[{ label: project?.name ?? projectId, to: `/p/${projectId}` }, { label: "새 Case" }]} projectId={projectId}>
      <div className="page-title-row">
        <h1 className="page-title">새 Case</h1>
        <span className="muted small">낙하 씬 1개 = rad + h3d(또는 추출 결과) + 대상 파트</span>
        <span className="spacer" />
        <Link to="/guide#new-case" className="topbar-link">
          도움말
        </Link>
        <PrimaryButton label="Case 만들기" onClick={create} disabledReason={reason} busy={busy} />
      </div>
      <div className="tabs" role="tablist" aria-label="입력 방법">
        {(["upload", "server"] as Tab[]).map((t) => (
          <button key={t} type="button" role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls={`panel-${t}`} className={tab === t ? "tab on" : "tab"} onClick={() => setTab(t)}>
            {TAB_LABEL[t]}
            {sel[t] && <span className="dot ok" aria-label="선택 완료" />}
          </button>
        ))}
      </div>
      <section className="card" role="tabpanel" id="panel-upload" aria-labelledby="tab-upload" hidden={tab !== "upload"}>
        <div className="card-body">
          <UploadPanel initialUploadId={initialUpload} projectId={projectId} name={NAME_RE.test(name) ? name : "case"} disabled={!allowed} onChange={onChange("upload")} />
        </div>
      </section>
      <section className="card" role="tabpanel" id="panel-server" aria-labelledby="tab-server" hidden={tab !== "server"}>
        <div className="card-body">{serverSeen ? <ServerPanel partTitle={part} onChange={onChange("server")} /> : null}</div>
      </section>
      <Card title="Case 정보">
        <div className="form-grid">
          <Field label="Case 이름" hint="결과 폴더 이름이 됩니다(영문·숫자·_·-)">
            <input
              className="mono"
              value={name}
              placeholder="QN80H_rear40"
              aria-invalid={!!name && !NAME_RE.test(name)}
              onChange={(e) => {
                setName(e.target.value);
                setNameTouched(true);
              }}
            />
          </Field>
          <Field label="대상 파트" hint={cur?.parts.length ? `rad 파트 ${cur.parts.length}개 중에서` : "rad의 파트 title"}>
            <input value={part} list="part-titles" onChange={(e) => setPart(e.target.value)} aria-invalid={!partOk} />
          </Field>
        </div>
        <datalist id="part-titles">
          {(cur?.parts ?? []).map((p) => (
            <option key={p.id} value={p.title} />
          ))}
        </datalist>
        <details className="adv-input">
          <summary>고급: 표시 제목</summary>
          <div className="adv-body">
            <Field label="제목(선택)" hint="비우면 Case 이름">
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="후방 충돌 40kph" />
            </Field>
          </div>
        </details>
        {cur && (
          <div className="small muted" data-testid="selected-summary">
            입력: rad <code>{cur.rad_path}</code> · {cur.source.kind === "h3d" ? "h3d(서버에서 추출)" : "추출 결과 폴더"} <code>{cur.source.path}</code>
          </div>
        )}
        <ErrorLine text={error} />
      </Card>
    </Shell>
  );
}
