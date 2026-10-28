// 템플릿 탭(esl_opt_run.md §3.2·§10.2): 모든 사용자 공개 목록 · 등록(.rad/.inc/.fem 청크 업로드 → 자동 검사 → 제목·인치(선택)·설명) ·
// 삭제(등록자·관리자만, 실행이 참조 중이면 보관). 주 버튼 = "템플릿 등록"(등록 패널 열기).
import { useRef, useState } from "react";
import { errorText } from "../../api/client";
import { opt } from "../../api/opt";
import type { MeshCheckOut, TemplateOut } from "../../api/types";
import { NO_PERMISSION, canRun, useApp } from "../../app/AppContext";
import { Badge, Card, Empty, ErrorLine, Field, PrimaryButton } from "../../components/ui";
import { Uploader, type UploadProgress } from "../../lib/uploader";
import { usePolling } from "../../lib/usePolling";
import { bytes, dt } from "../../lib/format";

function DeleteButton({ t, onDone }: { t: TemplateOut; onDone: (msg: string) => void }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!t.can_delete) return <span className="small muted" title="등록자·관리자만 삭제할 수 있습니다">–</span>;
  if (t.status === "ARCHIVED") return <span className="small muted">보관됨</span>;
  if (!confirm)
    return (
      <button type="button" className="btn small ghost" onClick={() => setConfirm(true)}>
        삭제
      </button>
    );
  return (
    <span className="inline-actions">
      <span className="small error-text">{t.n_runs ? "사용 중 — 보관할까요?" : "삭제할까요?"}</span>
      <button
        type="button"
        className="btn small danger"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const r = await opt.deleteTemplate(t.id);
            onDone(r.archived ? `'${t.title}' 보관됨 — 이전 실행이 참조 중이라 목록에서만 숨깁니다` : `'${t.title}' 삭제됨`);
          } catch (x) {
            setError(errorText(x));
            setBusy(false);
          }
        }}
      >
        {t.n_runs ? "보관" : "삭제"}
      </button>
      <button type="button" className="btn small ghost" onClick={() => setConfirm(false)}>
        아니오
      </button>
      {error && <span className="small error-text">{error}</span>}
    </span>
  );
}

/** 등록 패널: 업로드 → 검사 → 메타 → 등록 */
function RegisterPanel({ projectId, ext, onDone }: { projectId: string; ext: string[]; onDone: (t: TemplateOut) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [prog, setProg] = useState<UploadProgress | null>(null);
  const [check, setCheck] = useState<MeshCheckOut | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [inch, setInch] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const okExt = (f: File) => ext.some((x) => f.name.toLowerCase().endsWith(x));

  async function start(picked: File[]) {
    const bad = picked.filter((f) => !okExt(f));
    if (bad.length) {
      setError(`${bad.map((f) => f.name).join(", ")}: ${ext.join("·")} 만 올릴 수 있습니다`);
      return;
    }
    if (!picked.some((f) => /\.(rad|fem)$/i.test(f.name))) {
      setError(".rad 또는 .fem 파일이 하나 있어야 합니다");
      return;
    }
    setFiles(picked);
    setError(null);
    setCheck(null);
    setBusy(true);
    try {
      const main = picked.find((f) => /\.(rad|fem)$/i.test(f.name))!;
      const up = new Uploader(projectId, `template_${main.name.replace(/\.[^.]+$/, "")}`, picked.map((f) => ({ file: f, rel: `rad/${f.name}` })), setProg);
      const ok = await up.run();
      if (!ok || !up.uploadId) throw new Error(up.progress.error ?? "업로드가 멈췄습니다");
      setUploadId(up.uploadId);
      const c = await opt.checkTemplate({ project_id: projectId, upload_id: up.uploadId });
      setCheck(c);
      if (!title) setTitle(main.name.replace(/\.[^.]+$/, ""));
    } catch (x) {
      setError(errorText(x));
    } finally {
      setBusy(false);
    }
  }

  async function register() {
    if (!check || !uploadId) return;
    setBusy(true);
    setError(null);
    try {
      const t = await opt.createTemplate({ project_id: projectId, upload_id: uploadId, sha256: check.sha256, part_title: check.part_title, title: title.trim(), inch: inch.trim() ? Number(inch) : null, description: desc.trim() || null });
      onDone(t);
    } catch (x) {
      setError(errorText(x));
      setBusy(false);
    }
  }

  const pct = prog && prog.total ? Math.round((prog.sent / prog.total) * 100) : 0;
  const inchBad = inch.trim() !== "" && !(Number.isInteger(Number(inch)) && Number(inch) > 0);
  const regReason = !check ? "검사가 끝나야 등록할 수 있습니다" : check.quality.errors.length ? "검사 오류가 있습니다" : !title.trim() ? "제목을 입력하세요" : inchBad ? "인치는 양의 정수입니다" : null;
  return (
    <div className="tpl-register" data-testid="template-register">
      <div
        className={`dropzone${over ? " over" : ""}${files.length ? " has" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!busy) void start([...e.dataTransfer.files]);
        }}
      >
        <div className="dropzone-title">{files.length ? files.map((f) => f.name).join(", ") : "쉘 메시 파일(.rad + include 또는 .fem)을 끌어다 놓기"}</div>
        <div className="small muted">평판 쉘(QUAD4·TRIA3) · 요소 최대 50만 · .fem INCLUDE 미지원</div>
        <div className="actions">
          <button type="button" className="btn small" disabled={busy} onClick={() => fileRef.current?.click()}>
            파일 고르기
          </button>
          <input ref={fileRef} type="file" multiple hidden accept={ext.join(",")} aria-label="템플릿 파일" onChange={(e) => void start([...(e.target.files ?? [])])} />
        </div>
      </div>
      {prog && (
        <div className="upload-progress">
          <div className="progress" role="progressbar" aria-label="업로드" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="small muted">
            {pct}% · {bytes(prog.sent)} / {bytes(prog.total)}
            {busy && prog.phase === "uploaded" ? " · 검사 중…" : ""}
          </span>
        </div>
      )}
      {check && (
        <div className="small" data-testid="template-check">
          {check.format} · {check.file_name} · 노드 {check.mesh.n_nodes.toLocaleString()} · 요소 {check.mesh.n_elems.toLocaleString()} · {Math.round(check.frame.L_xi)}×{Math.round(check.frame.L_eta)} mm · 검사 오류 {check.quality.errors.length} 경고 {check.quality.warnings.length}
          {[...check.quality.errors, ...check.quality.warnings].length > 0 && (
            <ul className="reasons">
              {check.quality.errors.map((w) => (
                <li key={w} className="error-text">
                  {w}
                </li>
              ))}
              {check.quality.warnings.map((w) => (
                <li key={w} className="warn-text">
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="filters">
        <Field label="제목">
          <input aria-label="템플릿 제목" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="인치(선택)">
          <input type="number" aria-label="템플릿 인치" min={1} value={inch} aria-invalid={inchBad} onChange={(e) => setInch(e.target.value)} />
        </Field>
        <Field label="설명">
          <input aria-label="템플릿 설명" maxLength={2000} value={desc} onChange={(e) => setDesc(e.target.value)} />
        </Field>
        <span className="primary-wrap" title={regReason ?? undefined}>
          <button type="button" className="btn" disabled={!!regReason || busy} onClick={register}>
            등록
          </button>
        </span>
      </div>
      <ErrorLine text={error} />
    </div>
  );
}

export function Templates({ projectId }: { projectId: string }) {
  const { me } = useApp();
  const allowed = canRun(me, projectId);
  const [showArchived, setShowArchived] = useState(false);
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const list = usePolling(() => opt.templates(showArchived ? {} : { status: "ACTIVE" }), 0, [showArchived]);
  const settings = usePolling(() => opt.settings(), 0, []);
  return (
    <Card
      title="템플릿 (모든 사용자 공개)"
      right={<PrimaryButton label="템플릿 등록" onClick={() => setOpen((o) => !o)} disabledReason={allowed ? null : NO_PERMISSION} />}
    >
      {open && (
        <RegisterPanel
          projectId={projectId}
          ext={settings.data?.template_ext ?? [".rad", ".inc", ".fem"]}
          onDone={(t) => {
            setOpen(false);
            setMsg(`'${t.title}' 등록됨`);
            void list.reload();
          }}
        />
      )}
      <div className="filters">
        <label className="check small">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> 보관 포함
        </label>
        <span className="spacer" />
        {msg && (
          <span className="small ok-text" role="status">
            {msg}
          </span>
        )}
      </div>
      {!list.data ? (
        <Empty>{list.error ?? "불러오는 중…"}</Empty>
      ) : list.data.length === 0 ? (
        <Empty>등록된 템플릿이 없습니다 — '템플릿 등록'으로 .rad/.fem 평판 메시를 올리세요</Empty>
      ) : (
        <div className="table-wrap scroll">
          <table className="table compact" aria-label="템플릿 목록">
            <thead>
              <tr>
                <th>제목</th>
                <th>형식</th>
                <th className="num">인치</th>
                <th className="num">크기(mm)</th>
                <th className="num">노드/요소</th>
                <th>등록자</th>
                <th className="num">사용</th>
                <th className="num">등록일</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((t) => (
                <tr key={t.id} className={t.status === "ARCHIVED" ? "retired" : undefined}>
                  <td>
                    {t.title} {t.status === "ARCHIVED" && <Badge kind="warn">보관됨</Badge>}
                    {t.quality_warnings.length > 0 && <span className="small warn-text" title={t.quality_warnings.join("\n")}> 경고 {t.quality_warnings.length}</span>}
                  </td>
                  <td>{t.format}</td>
                  <td className="num">{t.inch ?? "–"}</td>
                  <td className="num">
                    {Math.round(t.L_xi)}×{Math.round(t.L_eta)}
                  </td>
                  <td className="num">
                    {t.n_nodes.toLocaleString()}/{t.n_elems.toLocaleString()}
                  </td>
                  <td>{t.created_by_name}</td>
                  <td className="num">{t.n_runs}</td>
                  <td className="num">{dt(t.created_at)}</td>
                  <td>
                    <DeleteButton
                      t={t}
                      onDone={(m) => {
                        setMsg(m);
                        void list.reload();
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
