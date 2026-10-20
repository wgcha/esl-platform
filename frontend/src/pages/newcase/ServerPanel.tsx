// 새 Case — 서버 폴더에서 고르기(계약 esl_p3_ux.md §1.2·§6): 루트(업로드 폴더 등) → 폴더 목록 → 힌트 배지(rad·h3d·결과 폴더) 클릭으로 선택.
// 경로 직접 입력은 '고급'으로 접어 둔다.
import { useEffect, useState } from "react";
import { p3 } from "../../api/p3";
import { api } from "../../api/endpoints";
import { errorText } from "../../api/client";
import type { BrowseEntry, BrowseOut, InspectRadResult, InspectResultsResult } from "../../api/types";
import { Badge, Empty, ErrorLine } from "../../components/ui";
import { RadInspectView, ResultsInspectView, usePathInspect } from "../../components/PathInspect";
import { bytes } from "../../lib/format";
import type { InputSelection, InputSource } from "./types";

const HINT_LABEL: Record<string, string> = { rad: "rad 선택", h3d: "h3d 선택", results: "결과 폴더 선택" };

export function joinPath(root: string, rel: string[], name?: string) {
  const sep = root.includes("\\") ? "\\" : "/";
  return [root.replace(/[\\/]+$/, ""), ...rel, ...(name ? [name] : [])].join(sep);
}

interface Sel {
  rad: { path: string; r: InspectRadResult | null; error: string | null } | null;
  src: (InputSource & { r?: InspectResultsResult | null; error?: string | null }) | null;
}

export function toSelection(sel: Sel): InputSelection | null {
  if (!sel.rad?.r?.ok || !sel.src) return null;
  if (sel.src.kind === "results" && !(sel.src.r?.ok && sel.src.r.done?.ok !== false)) return null;
  return { rad_path: sel.rad.r.normalized_path, source: { kind: sel.src.kind, path: sel.src.kind === "results" ? sel.src.r?.normalized_path ?? sel.src.path : sel.src.path }, parts: sel.rad.r.parts, ok: true };
}

export function ServerPanel({ partTitle, onChange }: { partTitle: string; onChange: (sel: InputSelection | null, suggestedName?: string) => void }) {
  const [root, setRoot] = useState(0);
  const [rel, setRel] = useState<string[]>([]);
  const [data, setData] = useState<BrowseOut | null>(null);
  const [more, setMore] = useState<BrowseEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSelRaw] = useState<Sel>({ rad: null, src: null });
  const radAdv = usePathInspect("RAD");
  const resAdv = usePathInspect("RESULTS");
  const [h3dAdv, setH3dAdv] = useState("");

  useEffect(() => {
    let alive = true;
    setError(null);
    setMore([]);
    p3.browse(root, rel.join("/"))
      // §6: SPDM 루트는 보이지 않게(browse_spdm 기본 false — 서버가 켜도 새 Case 입력에는 쓰지 않음)
      .then((d) => alive && setData({ ...d, roots: d.roots.filter((r) => r.kind !== "spdm") }))
      .catch((e) => alive && (setError(errorText(e)), setData((d) => (d ? { ...d, entries: [] } : d))));
    return () => {
      alive = false;
    };
  }, [root, rel]);

  function setSel(next: Sel, suggested?: string) {
    setSelRaw(next);
    onChange(toSelection(next), suggested);
  }

  const rootObj = data?.roots.find((r) => r.index === root);
  const full = (name?: string) => joinPath(rootObj?.path ?? "", rel, name);

  async function pickRad(path: string) {
    const name = path.split(/[\\/]/).pop() ?? "";
    const stem = name.replace(/\.rad$/i, "").replace(/_0000$/, "").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^[^A-Za-z0-9]+/, "");
    let next: Sel = { ...sel, rad: { path, r: null, error: null } };
    setSel(next, stem || undefined);
    try {
      next = { ...next, rad: { path, r: await api.inspectRad(path), error: null } };
    } catch (e) {
      next = { ...next, rad: { path, r: null, error: errorText(e) } };
    }
    setSel(next);
  }
  async function pickResults(path: string) {
    let next: Sel = { ...sel, src: { kind: "results", path, r: null } };
    setSel(next);
    try {
      next = { ...next, src: { kind: "results", path, r: await api.inspectResults(path) } };
    } catch (e) {
      next = { ...next, src: { kind: "results", path, r: null, error: errorText(e) } };
    }
    setSel(next);
  }
  function pickH3d(path: string) {
    setSel({ ...sel, src: { kind: "h3d", path } });
  }
  function choose(e: BrowseEntry) {
    const p = full(e.name);
    if (e.hint === "rad") void pickRad(p);
    else if (e.hint === "h3d") pickH3d(p);
    else if (e.hint === "results") void pickResults(p);
  }

  const entries = [...(data?.entries ?? []), ...more];
  const isSel = (e: BrowseEntry) => {
    const p = full(e.name);
    return sel.rad?.path === p || sel.src?.path === p;
  };

  return (
    <div className="server-panel">
      <div className="browse-head">
        {data && data.roots.length > 1 && (
          <div className="seg" role="group" aria-label="루트">
            {data.roots.map((r) => (
              <button
                key={r.index}
                type="button"
                className={r.index === root ? "on" : undefined}
                title={r.path}
                onClick={() => {
                  setRoot(r.index);
                  setRel([]);
                }}
              >
                {r.label}
              </button>
            ))}
          </div>
        )}
        <nav className="browse-crumbs" aria-label="폴더 경로">
          <button type="button" className="link" onClick={() => setRel([])} title={rootObj?.path}>
            {rootObj?.label ?? "루트"}
          </button>
          {rel.map((seg, i) => (
            <span key={i}>
              <span className="crumb-sep">›</span>
              <button type="button" className="link" onClick={() => setRel(rel.slice(0, i + 1))}>
                {seg}
              </button>
            </span>
          ))}
        </nav>
        <span className="small muted mono ellipsis">{full()}</span>
      </div>
      <div className="small muted">폴더 이름을 눌러 들어가고, 오른쪽 배지를 눌러 고릅니다 — rad 파일 1개와 h3d 파일(또는 추출 결과 폴더) 1개.</div>
      <ErrorLine text={error} />
      <div className="table-wrap scroll browse-list">
        <table className="table compact" aria-label="서버 폴더 목록">
          <thead>
            <tr>
              <th>이름</th>
              <th className="num">크기</th>
              <th>선택</th>
            </tr>
          </thead>
          <tbody>
            {rel.length > 0 && (
              <tr>
                <td colSpan={3}>
                  <button type="button" className="link" onClick={() => setRel(rel.slice(0, -1))}>
                    .. 위로
                  </button>
                </td>
              </tr>
            )}
            {entries.map((e) => (
              <tr key={e.name} className={isSel(e) ? "hl" : undefined}>
                <td>
                  {e.type === "dir" ? (
                    <button type="button" className="link entry-dir" onClick={() => setRel([...rel, e.name])}>
                      <span className="entry-icon dir" aria-hidden="true" />
                      {e.name}/
                    </button>
                  ) : (
                    <span className="entry-file">
                      <span className="entry-icon file" aria-hidden="true" />
                      {e.name}
                    </span>
                  )}
                </td>
                <td className="num">{e.type === "file" && e.size != null ? bytes(e.size) : ""}</td>
                <td>
                  {e.hint && (
                    <button type="button" className={`hint-badge ${e.hint}${isSel(e) ? " on" : ""}`} onClick={() => choose(e)} data-hint={e.hint}>
                      {isSel(e) ? "✓ " : ""}
                      {HINT_LABEL[e.hint]}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && entries.length === 0 && !error && <Empty>빈 폴더</Empty>}
      </div>
      {data?.truncated && (
        <div className="actions small">
          <span className="muted">
            {entries.length} / {data.total ?? "?"}개 표시
          </span>
          <button
            type="button"
            className="btn small"
            onClick={() =>
              p3
                .browse(root, rel.join("/"), entries.length)
                .then((d) => {
                  setMore((m) => [...m, ...d.entries]);
                  setData((x) => (x ? { ...x, truncated: d.truncated } : x));
                })
                .catch((e) => setError(errorText(e)))
            }
          >
            더 보기
          </button>
        </div>
      )}

      <div className="picked" aria-label="고른 입력">
        <div className="picked-row">
          <span className="field-label">rad</span>
          {sel.rad ? <code>{sel.rad.path}</code> : <span className="muted small">아직 고르지 않음</span>}
        </div>
        {sel.rad?.error && <div className="small error-text">{sel.rad.error}</div>}
        {sel.rad?.r && <RadInspectView r={sel.rad.r} partTitle={partTitle} />}
        <div className="picked-row">
          <span className="field-label">{sel.src?.kind === "results" ? "추출 결과 폴더" : "h3d"}</span>
          {sel.src ? <code>{sel.src.path}</code> : <span className="muted small">아직 고르지 않음</span>}
          {sel.src?.kind === "h3d" && <Badge kind="info">서버에서 추출</Badge>}
        </div>
        {sel.src?.kind === "h3d" && <div className="small muted" data-testid="h3d-note">Case를 만든 뒤 ① 입력에서 '추출 실행'을 누르면 서버의 HyperView가 이 h3d에서 필요한 값만 뽑습니다(h3d는 읽기만).</div>}
        {sel.src?.error && <div className="small error-text">{sel.src.error}</div>}
        {sel.src?.kind === "results" && sel.src.r && <ResultsInspectView r={sel.src.r} />}
      </div>

      <details className="adv-input">
        <summary>고급: 경로 직접 입력</summary>
        <div className="adv-body">
          {radAdv.field("rad 경로 (_0000.rad)", "E:\\VD_SIMULATION_WEB\\esl-input\\...\\model_0000.rad")}
          <div className="actions">
            <button type="button" className="btn small" disabled={!radAdv.path.trim()} onClick={() => void pickRad(radAdv.path.trim())}>
              rad로 쓰기
            </button>
          </div>
          <label className="pathinput path-field">
            <span className="field-label">h3d 경로</span>
            <div className="pathinput-row">
              <input type="text" className="mono" value={h3dAdv} spellCheck={false} placeholder="E:\VD_SIMULATION_WEB\esl-input\...\result.h3d" onChange={(e) => setH3dAdv(e.target.value)} />
              <button type="button" className="btn" disabled={!/\.h3d$/i.test(h3dAdv.trim())} onClick={() => pickH3d(h3dAdv.trim())}>
                h3d로 쓰기
              </button>
            </div>
          </label>
          {resAdv.field("또는 추출 결과 폴더", "E:\\VD_SIMULATION_WEB\\esl-input\\...\\h3d_csv")}
          <div className="actions">
            <button type="button" className="btn small" disabled={!resAdv.path.trim()} onClick={() => void pickResults(resAdv.path.trim())}>
              결과 폴더로 쓰기
            </button>
          </div>
        </div>
      </details>
    </div>
  );
}
