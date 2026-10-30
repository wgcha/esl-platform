// 새 Case 화면(계약 esl_p3_ux.md §1·§6·§9 + esl_scx_relay.md §10.1): 탭 4개 "내 PC에서 올리기"(기본) / "서버 폴더에서 고르기" / "PC에서 추출해 올리기" / "SCX 드라이브에서 고르기"
// (PC 연결 코드·연결된 PC — PC 도구가 올리면 ?upload= 로 "내 PC에서 올리기"가 채워져 열린다).
// 입력 = rad(+include) 필수 + h3d(기본, 서버가 추출) 또는 추출 결과 폴더(대안). 고른 뒤 Case 이름·파트 → 주 버튼 "Case 만들기"(화면당 1개).
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { p3 } from "../../api/p3";
import { errorText } from "../../api/client";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { Shell } from "../../shell/Shell";
import { Card, ErrorLine, Field, PrimaryButton } from "../../components/ui";
import { normPartTitle } from "../../lib/partTitle";
import { uploadStore } from "../../lib/uploadStore";
import { UploadPanel } from "./UploadPanel";
import { ServerPanel } from "./ServerPanel";
import { PcPanel } from "./PcPanel";
import { ScxPanel, clearScxRun, scxTabReason } from "./ScxPanel";
import { scx } from "../../api/scx";
import type { ScxStatusOut } from "../../api/types";
import type { InputSelection } from "./types";

export const DEFAULT_PART = "chassis_rear";
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
type Tab = "upload" | "server" | "pc" | "scx";
const TABS: Tab[] = ["upload", "server", "pc", "scx"];
export const TAB_LABEL: Record<Tab, string> = { upload: "내 PC에서 올리기", server: "서버 폴더에서 고르기", pc: "PC에서 추출해 올리기", scx: "SCX 드라이브에서 고르기" };
export const SCX_TAB_REASON = "SCX 드라이브에서 rad·h3d를 골라 내려받으세요";
export const PC_TAB_REASON = "PC 도구(ESL_extract.bat)가 추출·올리기를 마치면 이 화면이 채워진 채로 열립니다";

export function NewCase() {
  const { projectId = "" } = useParams();
  const { me, projects } = useApp();
  const nav = useNavigate();
  const [qs, setQs] = useSearchParams();
  const initialUpload = qs.get("upload");
  const project = projects.find((p) => p.id === projectId);
  const allowed = canRun(me, projectId);
  // ?tab=pc|server|scx 로 바로 열기(가이드 바로가기)
  const qTab = qs.get("tab");
  const [tab, setTabRaw] = useState<Tab>(!initialUpload && (qTab === "pc" || qTab === "server" || qTab === "scx") ? qTab : "upload");
  const [serverSeen, setServerSeen] = useState(tab === "server");
  const [scxSeen, setScxSeen] = useState(tab === "scx");
  // v0.11.0 SR-D-19: SCX 탭 사용 가능 여부(서버 판정 1곳) — 꺼짐·대시보드 다운이면 탭만 비활성 + 사유
  const [scxStatus, setScxStatus] = useState<ScxStatusOut | null>(null);
  const [scxErr, setScxErr] = useState<string | null>(null);
  const loadScx = () =>
    scx
      .status(projectId)
      .then((st) => (setScxStatus(st), setScxErr(null)))
      .catch((e) => setScxErr(errorText(e)));
  useEffect(() => {
    void loadScx();
  }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps
  const scxReason = scxTabReason(scxStatus, scxErr);
  const setTab = (t: Tab) => {
    setTabRaw(t);
    if (t === "server") setServerSeen(true);
    if (t === "scx") {
      setScxSeen(true);
      void loadScx();
    }
  };
  const [sel, setSel] = useState<Record<Tab, InputSelection | null>>({ upload: null, server: null, pc: null, scx: null });
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
  const partOk = !cur || cur.parts.length === 0 || cur.parts.some((p) => normPartTitle(p.title) === normPartTitle(part));
  const reason = !allowed
    ? NO_PERMISSION
    : !cur
      ? tab === "upload"
        ? "rad와 h3d(또는 결과 폴더)를 올리고 확인을 마치세요"
        : tab === "pc"
          ? PC_TAB_REASON
          : tab === "scx"
            ? scxReason ?? SCX_TAB_REASON
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
      uploadStore.dropByRad(cur.rad_path);
      if (tab === "scx") clearScxRun(projectId);
      nav(`/p/${projectId}/c/${c.id}/step/1`);
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
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            id={`tab-${t}`}
            aria-selected={tab === t}
            aria-controls={`panel-${t}`}
            aria-disabled={t === "scx" && !!scxReason ? true : undefined}
            title={t === "scx" && scxReason ? scxReason : undefined}
            className={`tab${tab === t ? " on" : ""}${t === "scx" && scxReason ? " dis" : ""}`}
            onClick={() => setTab(t)}
          >
            {TAB_LABEL[t]}
            {sel[t] && <span className="dot ok" aria-label="선택 완료" />}
          </button>
        ))}
      </div>
      <section className="card" role="tabpanel" id="panel-upload" aria-labelledby="tab-upload" hidden={tab !== "upload"}>
        <div className="card-body">
          <UploadPanel initialUploadId={initialUpload} onSessionId={(id) => setQs({ upload: id }, { replace: true })} onOpenPcTab={() => setTab("pc")} onOpenUpload={(id) => setQs({ upload: id })} projectId={projectId} name={NAME_RE.test(name) ? name : "case"} disabled={!allowed} onChange={onChange("upload")} />
        </div>
      </section>
      <section className="card" role="tabpanel" id="panel-server" aria-labelledby="tab-server" hidden={tab !== "server"}>
        <div className="card-body">{serverSeen ? <ServerPanel partTitle={part} onChange={onChange("server")} /> : null}</div>
      </section>
      <section className="card" role="tabpanel" id="panel-pc" aria-labelledby="tab-pc" hidden={tab !== "pc"}>
        <div className="card-body">{tab === "pc" ? <PcPanel projectId={projectId} projectName={project?.name} allowed={allowed} reason={NO_PERMISSION} /> : null}</div>
      </section>
      <section className="card" role="tabpanel" id="panel-scx" aria-labelledby="tab-scx" hidden={tab !== "scx"}>
        <div className="card-body">
          {scxSeen ? (
            <ScxPanel
              projectId={projectId}
              status={scxStatus}
              statusError={scxErr}
              allowed={allowed}
              noPermission={NO_PERMISSION}
              isAdmin={!!me?.is_global_admin}
              name={NAME_RE.test(name) ? name : "case"}
              onChange={onChange("scx")}
              onUploaded={(id) => setQs({ upload: id, tab: "scx" }, { replace: true })}
            />
          ) : null}
        </div>
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
