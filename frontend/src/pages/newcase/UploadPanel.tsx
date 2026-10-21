// 새 Case — 내 PC에서 올리기(계약 esl_p3_ux.md §1.1·§6): rad·include + h3d(기본, 서버가 추출) 또는 추출 결과 폴더(대안, 접힘)
// → 분할 업로드(이어 올리기·남은 시간) → complete 검사(파트·누락 include).
import { useEffect, useRef, useState, type DragEvent } from "react";
import type { RadPart, UploadCompleteOut } from "../../api/types";

type Checked = UploadCompleteOut & { parts: RadPart[]; missing_includes: string[]; problems: string[] };
export const normCheck = (r: UploadCompleteOut): Checked => ({ ...r, parts: r.parts ?? [], missing_includes: r.missing_includes ?? [], problems: r.problems ?? [] });
import { errorText } from "../../api/client";
import { p3 } from "../../api/p3";
import { Badge, ErrorLine } from "../../components/ui";
import { bytes } from "../../lib/format";
import { ASSUMED_BPS, Uploader, etaText, type PickedFile, type UploadProgress } from "../../lib/uploader";
import type { InputSelection } from "./types";

export const ALLOWED_EXT = [".rad", ".inc", ".k", ".csv", ".json", ".txt", ".tcl", ".h3d"];
type Kind = "rad" | "h3d" | "results";
const extOf = (n: string) => n.slice(n.lastIndexOf(".")).toLowerCase();
export const allowedName = (n: string) => n.lastIndexOf(".") > 0 && ALLOWED_EXT.includes(extOf(n));

/** 폴더 선택(webkitRelativePath) 이면 첫 폴더를 떼고, 아니면 파일 이름만 */
export function relOf(kind: Kind, f: File, relPath?: string): string {
  const p = (relPath ?? (f as File & { webkitRelativePath?: string }).webkitRelativePath ?? "").replace(/\\/g, "/");
  const inner = p.includes("/") ? p.split("/").slice(1).join("/") : f.name;
  return `${kind}/${inner || f.name}`;
}

/** 업로드 이름(서버 폴더 이름 일부): rad 파일 이름에서 _0000.rad 을 떼고 영문·숫자·_·- 만 */
export function nameFromRad(n: string | undefined): string {
  const stem = (n ?? "case").replace(/\.rad$/i, "").replace(/_0000$/, "");
  const s = stem.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^[^A-Za-z0-9]+/, "").slice(0, 60);
  return s || "case";
}

type Picked = { file: File; rel: string };

/** 끌어다 놓은 항목(폴더 포함)을 [파일, 상대경로]로 펼친다 */
async function filesFromDrop(e: DragEvent): Promise<{ file: File; path: string }[]> {
  const items = [...(e.dataTransfer.items ?? [])];
  const entries = items.map((it) => (typeof it.webkitGetAsEntry === "function" ? it.webkitGetAsEntry() : null)).filter(Boolean) as FileSystemEntry[];
  if (!entries.length) return [...(e.dataTransfer.files ?? [])].map((file) => ({ file, path: file.name }));
  const out: { file: File; path: string }[] = [];
  async function walk(en: FileSystemEntry, prefix: string): Promise<void> {
    if (en.isFile) {
      const file = await new Promise<File>((res, rej) => (en as FileSystemFileEntry).file(res, rej));
      out.push({ file, path: prefix + en.name });
    } else if (en.isDirectory) {
      const reader = (en as FileSystemDirectoryEntry).createReader();
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const c of batch) await walk(c, `${prefix}${en.name}/`);
      }
    }
  }
  for (const en of entries) await walk(en, "");
  return out;
}

function DropZone({
  title,
  hint,
  kind,
  folderOnly,
  fileOnly,
  accept,
  onPick,
  count,
  disabled,
}: {
  title: string;
  hint: string;
  kind: Kind;
  folderOnly?: boolean;
  fileOnly?: boolean;
  accept?: string;
  onPick: (files: { file: File; path?: string }[]) => void;
  count: number;
  disabled: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  useEffect(() => {
    dirRef.current?.setAttribute("webkitdirectory", "");
    dirRef.current?.setAttribute("directory", "");
  }, []);
  const take = (list: FileList | null) => list && onPick([...list].map((file) => ({ file })));
  return (
    <div
      className={`dropzone${over ? " over" : ""}${count ? " has" : ""}`}
      data-testid={`drop-${kind}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={async (e) => {
        e.preventDefault();
        setOver(false);
        if (disabled) return;
        onPick(await filesFromDrop(e));
      }}
    >
      <div className="dropzone-title">{title}</div>
      <div className="small muted">{hint}</div>
      <div className="actions">
        {!folderOnly && (
          <button type="button" className="btn small" disabled={disabled} onClick={() => fileRef.current?.click()}>
            파일 고르기
          </button>
        )}
        {!fileOnly && (
          <button type="button" className="btn small" disabled={disabled} onClick={() => dirRef.current?.click()}>
            폴더 고르기
          </button>
        )}
        <span className="small muted">또는 여기로 끌어다 놓기</span>
        {count > 0 && <Badge kind="ok">{count}개 선택</Badge>}
      </div>
      <input ref={fileRef} type="file" multiple hidden aria-label={`${title} 파일`} accept={accept ?? ALLOWED_EXT.join(",")} onChange={(e) => (take(e.target.files), (e.target.value = ""))} />
      <input ref={dirRef} type="file" multiple hidden aria-label={`${title} 폴더`} onChange={(e) => (take(e.target.files), (e.target.value = ""))} />
    </div>
  );
}

const PHASE_TEXT: Record<string, string> = {
  hashing: "검사값(sha256) 계산 중…",
  uploading: "올리는 중",
  paused: "멈춤 — '이어 올리기'로 계속",
  error: "실패 — '이어 올리기'로 받은 데까지 이어서 보냅니다",
  uploaded: "올리기 완료",
  completing: "서버에서 확인 중…",
  done: "올리기·확인 완료",
};

export const H3D_NOTE = "h3d는 수 GB라 오래 걸립니다 — 끊겨도 '이어 올리기'로 받은 데부터 다시 보냅니다. 서버가 h3d에서 직접 추출합니다.";

export function UploadPanel({
  projectId,
  name,
  disabled,
  onChange,
  uploaderOpts,
  initialUploadId,
}: {
  projectId: string;
  name: string;
  disabled: boolean;
  onChange: (sel: InputSelection | null, suggestedName?: string) => void;
  uploaderOpts?: ConstructorParameters<typeof Uploader>[4];
  /** §9: PC 도구가 올린 업로드(?upload=)로 채워 열기 */
  initialUploadId?: string | null;
}) {
  const [files, setFiles] = useState<Picked[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [prog, setProg] = useState<UploadProgress | null>(null);
  const [result, setResult] = useState<Checked | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [altOpen, setAltOpen] = useState(false);
  const up = useRef<Uploader | null>(null);
  const [pcUpload, setPcUpload] = useState<{ name: string; n: number; bytes: number } | null>(null);

  useEffect(() => {
    if (!initialUploadId) return;
    let alive = true;
    (async () => {
      try {
        const u = await p3.upload(initialUploadId);
        const r = normCheck(u.state === "COMPLETED" && u.result ? { ...u.result, upload_id: u.upload_id, state: "COMPLETED" } : await p3.completeUpload(initialUploadId));
        if (!alive) return;
        setPcUpload({ name: u.name, n: u.files.length, bytes: u.total_bytes });
        setResult(r);
        const src = r.h3d_path ? ({ kind: "h3d", path: r.h3d_path } as const) : r.results_dir ? ({ kind: "results", path: r.results_dir } as const) : null;
        const ok = r.ok && !!r.rad_path && !!src;
        const rad = r.rad_path?.split(/[\\/]/).pop();
        onChange(ok ? { rad_path: r.rad_path!, source: src!, parts: r.parts, ok: true } : null, nameFromRad(rad ?? u.name));
      } catch (e) {
        if (alive) setError(`PC에서 올린 업로드를 열 수 없습니다: ${errorText(e)}`);
      }
    })();
    return () => {
      alive = false;
    };
  }, [initialUploadId]); // eslint-disable-line react-hooks/exhaustive-deps
  const addRef = useRef<HTMLInputElement>(null);
  const started = !!up.current;
  const busy = prog?.phase === "hashing" || prog?.phase === "uploading" || prog?.phase === "completing";

  function pick(kind: Kind, list: { file: File; path?: string }[]) {
    const ok: Picked[] = [];
    const bad: string[] = [];
    for (const { file, path } of list) {
      const isH3d = /\.h3d$/i.test(file.name);
      if (!allowedName(file.name) || (kind === "h3d") !== isH3d) {
        bad.push(kind === "h3d" ? `${file.name} (h3d 파일만)` : isH3d ? `${file.name} (h3d는 ③ h3d 칸에)` : file.name);
        continue;
      }
      ok.push({ file, rel: relOf(kind, file, path) });
    }
    if (kind === "h3d") ok.splice(1); // h3d 는 1개
    // h3d 와 결과 폴더는 둘 중 하나: 새로 고른 쪽만 남긴다
    const other = kind === "h3d" ? "results/" : kind === "results" ? "h3d/" : null;
    const keep = files.filter((f) => !ok.some((n) => n.rel === f.rel) && !(other && ok.length && f.rel.startsWith(other)) && !(kind === "h3d" && ok.length && f.rel.startsWith("h3d/")));
    // 작은 rad·include·결과 파일 먼저, 큰 h3d 는 마지막
    const order = (r: string) => (r.startsWith("rad/") ? 0 : r.startsWith("results/") ? 1 : 2);
    const next = [...keep, ...ok].sort((a, b) => order(a.rel) - order(b.rel) || a.rel.localeCompare(b.rel));
    const rad = next.find((f) => /^rad\/.*\.rad$/i.test(f.rel));
    setFiles(next);
    onChange(null, rad ? nameFromRad(rad.file.name) : undefined);
    setSkipped((s) => [...s, ...bad]);
    setResult(null);
  }

  async function complete() {
    try {
      const r = normCheck(await up.current!.complete());
      setResult(r);
      const src = r.h3d_path ? ({ kind: "h3d", path: r.h3d_path } as const) : r.results_dir ? ({ kind: "results", path: r.results_dir } as const) : null;
      const ok = r.ok && !!r.rad_path && !!src && r.missing_includes.length === 0;
      onChange(ok ? { rad_path: r.rad_path!, source: src!, parts: r.parts, ok: true } : null);
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function start() {
    setError(null);
    if (!up.current) up.current = new Uploader(projectId, name, files, setProg, uploaderOpts);
    if (await up.current.run()) await complete();
  }

  async function addMissing(list: FileList | null) {
    if (!list || !up.current || !result) return;
    const miss = result.missing_includes.map((m) => m.replace(/\\/g, "/"));
    const more: PickedFile[] = [...list].map((file) => {
      const hit = miss.find((m) => m.split("/").pop()!.toLowerCase() === file.name.toLowerCase());
      // 서버는 "rad/inc/x.inc"(업로드 상대경로)로 알려 준다 — 그 자리로 올린다
      const safe = hit && !hit.startsWith("/") && !/^[A-Za-z]:/.test(hit) && !hit.split("/").includes("..");
      return { file, rel: safe ? (hit.startsWith("rad/") ? hit : `rad/${hit}`) : `rad/${file.name}` };
    });
    setFiles((f) => [...f, ...more]);
    setResult(null);
    setError(null);
    try {
      if (await up.current.add(more)) await complete();
    } catch (e) {
      setError(errorText(e));
    }
  }

  function reset() {
    up.current?.stop();
    up.current = null;
    setFiles([]);
    setSkipped([]);
    setProg(null);
    setResult(null);
    setError(null);
    onChange(null);
  }

  const total = files.reduce((s, f) => s + f.file.size, 0);
  const count = (k: Kind) => files.filter((f) => f.rel.startsWith(`${k}/`)).length;
  const radN = count("rad");
  const h3dN = count("h3d");
  const resN = count("results");
  const sent = prog?.sent ?? 0;
  const frac = total ? sent / total : 0;
  const rate = prog?.rate ?? null;
  const left = total - sent;
  const hasRad = files.some((f) => /^rad\/.*\.rad$/i.test(f.rel));
  const startReason = !files.length ? "파일을 고르세요" : !hasRad ? "rad 파일(_0000.rad)을 포함하세요" : !h3dN && !resN ? "h3d 파일을 고르세요(또는 추출 결과 폴더)" : null;
  const lock = disabled || started;

  if (pcUpload)
    return (
      <div className="upload-panel" data-testid="pc-upload">
        <div className="inspect ok">
          <div>
            <Badge kind="info">PC에서 올림</Badge> <b>{pcUpload.name}</b>{" "}
            <span className="muted">
              {pcUpload.n}개 · {bytes(pcUpload.bytes)} — ESL_extract.bat 이 추출해 올린 파일입니다. 아래 Case 정보를 확인하고 'Case 만들기'.
            </span>
          </div>
        </div>
        <ResultView result={result} />
        <ErrorLine text={error} />
      </div>
    );

  return (
    <div className="upload-panel">
      <div className="grid2">
        <DropZone
          kind="rad"
          title="① rad · include 파일"
          hint="_0000.rad 과 include(.inc·.k) — 여러 개 또는 폴더째"
          onPick={(l) => pick("rad", l)}
          count={radN}
          disabled={lock}
        />
        <DropZone kind="h3d" fileOnly accept=".h3d" title="② h3d 결과 파일" hint="낙하 해석 결과 h3d 1개 — 서버가 직접 추출합니다" onPick={(l) => pick("h3d", l)} count={h3dN} disabled={lock} />
      </div>
      <div className="small muted">{H3D_NOTE}</div>
      <details className="alt-input" open={altOpen || resN > 0} onToggle={(e) => setAltOpen((e.target as HTMLDetailsElement).open)}>
        <summary>추출 결과가 이미 있으면 — h3d 대신 결과 폴더 올리기</summary>
        <DropZone
          kind="results"
          folderOnly
          title="② 대신: 추출 결과 폴더"
          hint="PC에서 ESL_extract.bat 으로 만든 폴더(done.json·CSV). 고르면 h3d 선택은 빠집니다."
          onPick={(l) => pick("results", l)}
          count={resN}
          disabled={lock}
        />
      </details>
      {skipped.length > 0 && (
        <div className="small warn-text" role="status">
          제외 {skipped.length}개: {skipped.slice(0, 5).join(", ")}
          {skipped.length > 5 ? " …" : ""}
        </div>
      )}
      {files.length > 0 && (
        <>
          <div className="table-wrap scroll upload-list">
            <table className="table compact" aria-label="올릴 파일">
              <thead>
                <tr>
                  <th>파일</th>
                  <th className="num">크기</th>
                  <th className="num">받음</th>
                </tr>
              </thead>
              <tbody>
                {files.map((f, i) => {
                  const rec = prog?.received[i] ?? 0;
                  return (
                    <tr key={f.rel}>
                      <td className="mono">{f.rel}</td>
                      <td className="num">{bytes(f.file.size)}</td>
                      <td className="num">{rec >= f.file.size && f.file.size > 0 ? "✓" : rec ? `${Math.floor((rec / f.file.size) * 100)}%` : "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="upload-summary" data-testid="upload-summary">
            <span>
              {files.length}개 · {bytes(total)}
            </span>
            <span className="muted">
              {prog && rate && prog.phase === "uploading"
                ? `${bytes(rate)}/s · 남은 시간 약 ${etaText(left, rate)}`
                : !prog
                  ? `예상 약 ${etaText(total, ASSUMED_BPS)} (사내망 30 MB/s 기준)`
                  : null}
            </span>
            <span className="spacer" />
            {!busy && prog?.phase !== "done" && startReason && (
              <span className="small warn-text" data-testid="upload-start-reason">{startReason}</span>
            )}
            {!busy && prog?.phase !== "done" && (
              <span className="primary-wrap" title={startReason ?? undefined}>
                <button type="button" className="btn" disabled={!!startReason || disabled} onClick={() => void start()}>
                  {prog && (prog.phase === "error" || prog.phase === "paused") ? "이어 올리기" : prog?.phase === "uploaded" ? "다시 확인" : "올리기"}
                </button>
              </span>
            )}
            {prog?.phase === "uploading" && (
              <button type="button" className="btn ghost" onClick={() => up.current?.stop()}>
                멈춤
              </button>
            )}
            {!busy && (
              <button type="button" className="btn ghost" onClick={reset}>
                지우기
              </button>
            )}
          </div>
          {prog && (
            <div className="upload-progress" aria-label="올리기 진행">
              <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(frac * 100)}>
                <div className="progress-fill" style={{ width: `${(frac * 100).toFixed(1)}%` }} />
              </div>
              <div className="small">
                <b>{Math.floor(frac * 100)}%</b> {bytes(sent)} / {bytes(total)} · {PHASE_TEXT[prog.phase] ?? prog.phase}
                {prog.retries > 0 && <span className="muted"> · 재시도 {prog.retries}회</span>}
              </div>
              {prog.error && <div className="small error-text">{prog.error}</div>}
            </div>
          )}
        </>
      )}
      <ErrorLine text={error} />
      <ResultView result={result} onAdd={() => addRef.current?.click()} />
      <input ref={addRef} type="file" multiple hidden aria-label="추가로 올릴 include" onChange={(e) => (void addMissing(e.target.files), (e.target.value = ""))} />
    </div>
  );
}

function ResultView({ result, onAdd }: { result: Checked | null; onAdd?: () => void }) {
  if (!result) return null;
  return (
    <div className={result.missing_includes.length || result.problems.length ? "inspect bad" : "inspect ok"} aria-label="올린 파일 확인 결과">
      <div>
        {result.missing_includes.length || result.problems.length ? (
          <Badge kind="bad">추가 필요</Badge>
        ) : (
          <Badge kind="ok">{result.h3d_path ? "rad·h3d 확인됨 — Case를 만들면 서버가 추출합니다" : "rad·결과 폴더 확인됨"}</Badge>
        )}
        {result.parts.length > 0 && <span className="muted"> 파트 {result.parts.length}개: {result.parts.map((p) => p.title).join(", ")}</span>}
      </div>
      {result.problems.map((p) => (
        <div key={p} className="small error-text">
          {p}
        </div>
      ))}
      {result.missing_includes.length > 0 && (
        <div className="missing" data-testid="missing-includes">
          <div className="small error-text">rad 가 참조하는 include {result.missing_includes.length}개가 없습니다: {result.missing_includes.join(", ")}</div>
          {onAdd ? (
            <div className="actions">
              <button type="button" className="btn small" onClick={onAdd}>
                추가로 올리기
              </button>
              <span className="small muted">빠진 파일을 골라 올리면 다시 확인합니다.</span>
            </div>
          ) : (
            <span className="small muted">PC에서 빠진 include를 넣고 ESL_upload.bat 으로 다시 올리세요.</span>
          )}
        </div>
      )}
    </div>
  );
}
