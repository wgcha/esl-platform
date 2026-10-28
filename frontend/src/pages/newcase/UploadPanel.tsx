// 새 Case — 내 PC에서 올리기(계약 esl_p3_ux.md §1.1·§6): rad·include + h3d(기본, 서버가 추출) 또는 추출 결과 폴더(대안, 접힘)
// → 분할 업로드(이어 올리기·남은 시간) → complete 검사(파트·누락 include).
import { useEffect, useRef, useState, type DragEvent } from "react";
import type { H3dMeta, RadPart, UploadCompleteOut, UploadOut } from "../../api/types";

type Checked = UploadCompleteOut & { parts: RadPart[]; missing_includes: string[]; problems: string[] };
export const normCheck = (r: UploadCompleteOut): Checked => ({ ...r, parts: r.parts ?? [], missing_includes: r.missing_includes ?? [], problems: r.problems ?? [] });
import { ApiError, errorText } from "../../api/client";
import { p3 } from "../../api/p3";
import { Badge, ErrorLine } from "../../components/ui";
import { bytes, dt } from "../../lib/format";
import { slimLine, slimTip } from "../../lib/slim";
import { uploadStore, type Picked } from "../../lib/uploadStore";
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

export const H3D_NOTE = "h3d는 수 GB라 오래 걸립니다 — 끊겨도 '이어 올리기'로 받은 데부터 다시 보냅니다(청크 여러 개를 동시에 보냅니다). 서버가 h3d에서 직접 추출합니다.";
export const CLEAR_NONE_REASON = "지울 파일을 선택하세요";
export const SENDING_TIP = "전송 중 — 멈춤 후 선택";
export const LIMIT_NOTE = "업로드 세션은 계산 대기열과 별개입니다 — 아래 목록에서 이어서 하거나 취소하세요";
const GIB = 1024 ** 3;
/** ui.upload_slim_hint_gb 를 받기 전·못 받았을 때 기본값(계약 §7) */
export const SLIM_HINT_GB_DEFAULT = 5;

export function bigH3dText(size: number): string {
  return `이 h3d는 ${bytes(size)}입니다 — 크면 'PC에서 추출해 올리기'의 압축 모드(PC 도구, 필요한 결과만 남긴 h3d)가 훨씬 빠릅니다.`;
}

/** 지우기 오류 문구 */
function clearErrorText(e: unknown): string {
  if (e instanceof ApiError && e.code === "UPLOAD_IN_USE") return "이 업로드로 만든 Case가 있어 뺄 수 없습니다";
  if (e instanceof ApiError && e.code === "UPLOAD_FILE_BUSY") return "그 파일을 아직 받는 중입니다 — 잠시 뒤 다시 지우세요";
  return errorText(e);
}


export function UploadPanel({
  projectId,
  name,
  disabled,
  onChange,
  uploaderOpts,
  initialUploadId,
  onOpenPcTab,
  onOpenUpload,
  onSessionId,
}: {
  projectId: string;
  name: string;
  disabled: boolean;
  onChange: (sel: InputSelection | null, suggestedName?: string) => void;
  uploaderOpts?: ConstructorParameters<typeof Uploader>[4];
  /** §9: PC 도구가 올린 업로드(?upload=)로 채워 열기 */
  initialUploadId?: string | null;
  /** 큰 h3d 안내의 'PC에서 추출해 올리기' 탭 링크 */
  onOpenPcTab?: () => void;
  /** '진행 중인 업로드'의 '이어서 열기' — ?upload=<id> 로 연다 */
  onOpenUpload?: (id: string) => void;
  /** 업로드 세션이 만들어지면(POST /uploads 성공) 그 id — 호출 측이 URL 을 ?upload=<id> 로 바꾼다 */
  onSessionId?: (id: string) => void;
}) {
  // 앱 수준 업로드 저장소: 다른 페이지로 갔다 와도(?upload=<id>) 같은 Uploader·목록·진행률에 다시 붙는다
  const adoptRef = useRef(initialUploadId ? uploadStore.findById(initialUploadId) : undefined);
  const adopt = adoptRef.current;
  const keyRef = useRef<string | null>(adopt?.key ?? null);
  const lastResult = useRef<UploadCompleteOut | null>(null);
  const lastErr = useRef<string | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [files, setFiles] = useState<Picked[]>(adopt?.files ?? []);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [skipped, setSkipped] = useState<string[]>([]);
  const [prog, setProg] = useState<UploadProgress | null>(adopt?.prog ?? null);
  const [result, setResult] = useState<Checked | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [altOpen, setAltOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [hintGb, setHintGb] = useState(SLIM_HINT_GB_DEFAULT);
  const [listKey, setListKey] = useState(0);
  const up = useRef<Uploader | null>(adopt?.uploader ?? null);
  const [pcUpload, setPcUpload] = useState<PcUpload | null>(null);
  const allRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    p3.version().then(
      (v) => alive && typeof v.ui?.upload_slim_hint_gb === "number" && setHintGb(v.ui.upload_slim_hint_gb),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, []);

  /** 확인 결과를 화면·Case 입력 선택에 반영 */
  function applyResult(raw: UploadCompleteOut) {
    const r = normCheck(raw);
    setResult(r);
    const src = r.h3d_path ? ({ kind: "h3d", path: r.h3d_path } as const) : r.results_dir ? ({ kind: "results", path: r.results_dir } as const) : null;
    const ok = r.ok && !!r.rad_path && !!src && r.missing_includes.length === 0;
    onChangeRef.current(ok ? { rad_path: r.rad_path!, source: src!, parts: r.parts, ok: true } : null);
  }
  function clearResult() {
    setResult(null);
    lastResult.current = null;
    if (keyRef.current) uploadStore.patch(keyRef.current, { result: null });
  }

  // 저장소 구독: 전송 진행·확인 결과·오류를 화면에 반영(화면이 없는 동안 끝난 결과도 다시 붙을 때 반영)
  const syncRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    const sync = () => {
      const s = uploadStore.get(keyRef.current);
      if (!s) return;
      setProg(s.prog);
      if (s.result && s.result !== lastResult.current) {
        lastResult.current = s.result;
        applyResult(s.result);
      }
      if (s.error && s.error !== lastErr.current) {
        lastErr.current = s.error;
        setError(s.error);
      }
    };
    syncRef.current = sync;
    sync();
    return uploadStore.subscribe(sync);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (keyRef.current) uploadStore.patch(keyRef.current, { files });
  }, [files]);
  const sessionId = prog?.uploadId ?? null;
  useEffect(() => {
    if (sessionId && sessionId !== initialUploadId && keyRef.current) onSessionId?.(sessionId);
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!initialUploadId) return;
    const mine = uploadStore.findById(initialUploadId);
    if (mine) {
      // 이 브라우저가 올리는(또는 올렸던) 업로드: 저장소 세션에 붙는다(다른 업로드 화면에서 상단 표시로 넘어온 경우 포함)
      if (mine.key !== keyRef.current) {
        keyRef.current = mine.key;
        up.current = mine.uploader;
        lastResult.current = null;
        lastErr.current = null;
        setFiles(mine.files);
        setSelected(new Set());
        setPcUpload(null);
        setResult(null);
        syncRef.current();
      }
      return;
    }
    let alive = true;
    (async () => {
      try {
        const u = await p3.upload(initialUploadId);
        const live = u.files.filter((f) => !f.removed);
        if (u.state === "OPEN" && live.some((f) => !f.done)) {
          // 아직 다 받지 못한 업로드: 받은 양을 보여 주고, 같은 파일을 다시 고르면 이어 올린다고 안내
          if (!alive) return;
          clearResult();
          setPcUpload({ name: u.name, n: live.length, bytes: u.total_bytes, id: u.upload_id, partial: live.map((f) => ({ rel: f.rel, size: f.size, got: f.received_total ?? f.received })) });
          onChange(null);
          return;
        }
        const r = normCheck(u.state === "COMPLETED" && u.result ? { ...u.result, upload_id: u.upload_id, state: "COMPLETED" } : await p3.completeUpload(initialUploadId));
        if (!alive) return;
        const meta = r.h3d_meta ?? live.find((f) => f.meta)?.meta ?? null;
        setPcUpload({ name: u.name, n: live.length, bytes: u.total_bytes, id: u.upload_id, meta });
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

  function resetLocal() {
    uploadStore.drop(keyRef.current);
    keyRef.current = null;
    lastResult.current = null;
    lastErr.current = null;
    up.current = null;
    setFiles([]);
    setSelected(new Set());
    setSkipped([]);
    setProg(null);
    clearResult();
    setError(null);
    setNote(null);
    onChange(null);
    setListKey((k) => k + 1);
  }

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
    if (up.current) {
      void addToSession(kind, ok, bad);
      return;
    }
    // h3d 와 결과 폴더는 둘 중 하나: 새로 고른 쪽만 남긴다
    const other = kind === "h3d" ? "results/" : kind === "results" ? "h3d/" : null;
    const keep = files.filter((f) => !ok.some((n) => n.rel === f.rel) && !(other && ok.length && f.rel.startsWith(other)) && !(kind === "h3d" && ok.length && f.rel.startsWith("h3d/")));
    // 작은 rad·include·결과 파일 먼저, 큰 h3d 는 마지막
    const order = (r: string) => (r.startsWith("rad/") ? 0 : r.startsWith("results/") ? 1 : 2);
    const next = [...keep, ...ok].sort((a, b) => order(a.rel) - order(b.rel) || a.rel.localeCompare(b.rel));
    const rad = next.find((f) => /^rad\/.*\.rad$/i.test(f.rel));
    setFiles(next);
    setSelected(new Set());
    onChange(null, rad ? nameFromRad(rad.file.name) : undefined);
    setSkipped((s) => [...s, ...bad]);
    clearResult();
  }

  /** 세션이 있을 때 고른 파일은 목록에 더하고 서버에 등록(addUploadFiles) — 올리기는 '이어 올리기'로 */
  async function addToSession(kind: Kind, ok: Picked[], bad: string[]) {
    const fresh: Picked[] = [];
    for (const n of ok) {
      if (files.some((f) => f.rel === n.rel)) bad.push(`${n.file.name} (목록에 있음 — 먼저 지우세요)`);
      else if (kind === "h3d" && files.some((f) => f.rel.startsWith("h3d/") || f.rel.startsWith("results/"))) bad.push(`${n.file.name} (h3d·결과 폴더는 하나만 — 먼저 지우세요)`);
      else if (kind === "results" && files.some((f) => f.rel.startsWith("h3d/"))) bad.push(`${n.file.name} (h3d가 있음 — 먼저 지우세요)`);
      else fresh.push(n);
    }
    setSkipped((s) => [...s, ...bad]);
    if (!fresh.length) return;
    try {
      const start = await up.current!.register(fresh.map((f) => ({ file: f.file, rel: f.rel })));
      setFiles((old) => [...old, ...fresh.map((f, j) => ({ ...f, idx: start + j }))]);
      clearResult();
      setError(null);
      onChange(null);
      setNote(null);
    } catch (e) {
      setError(clearErrorText(e));
    }
  }

  async function complete() {
    const key = keyRef.current;
    if (!key) return;
    const r = await uploadStore.complete(key);
    if (r && r !== lastResult.current) {
      lastResult.current = r;
      applyResult(r);
    }
    const err = uploadStore.get(key)?.error;
    if (err) {
      lastErr.current = err;
      setError(err);
    }
  }

  async function start() {
    setError(null);
    setNote(null);
    lastErr.current = null;
    if (!up.current) {
      const sess = uploadStore.create(projectId, name, files, uploaderOpts);
      keyRef.current = sess.key;
      up.current = sess.uploader;
      setFiles(sess.files);
    }
    const ok = await uploadStore.start(keyRef.current!);
    if (!ok && up.current?.progress.errorCode === "UPLOAD_LIMIT") setListKey((k) => k + 1);
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
    clearResult();
    setError(null);
    try {
      const startIdx = await up.current.register(more);
      setFiles((f) => [...f, ...more.map((m, j) => ({ ...m, idx: startIdx + j }))]);
      lastErr.current = null;
      await uploadStore.start(keyRef.current!);
    } catch (e) {
      setError(errorText(e));
    }
  }

  // ------------------------------------------------------------------ 목록 선택·지우기(계약 §6.2, US-18)
  const sending = new Set(prog?.active ?? []);
  const confirming = prog?.phase === "completing";
  const selectable = (f: Picked) => !disabled && !clearing && !confirming && !(f.idx !== undefined && sending.has(f.idx));
  const rows = files.filter(selectable);
  const selFiles = files.filter((f) => selected.has(f.rel) && selectable(f));
  const allSel = rows.length > 0 && rows.every((f) => selected.has(f.rel));
  const someSel = selFiles.length > 0 && !allSel;
  useEffect(() => {
    if (allRef.current) allRef.current.indeterminate = someSel;
  }, [someSel]);
  const clearReason = clearing ? "지우는 중…" : confirming ? "서버 확인 중 — 끝난 뒤 지울 수 있습니다" : disabled ? null : selFiles.length === 0 ? CLEAR_NONE_REASON : null;

  function toggle(rel: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(rel)) n.delete(rel);
      else n.add(rel);
      return n;
    });
  }
  const toggleAll = () => setSelected(allSel ? new Set() : new Set(rows.map((f) => f.rel)));

  async function clearSelected() {
    if (!selFiles.length) return;
    setError(null);
    const gone = new Set(selFiles.map((f) => f.rel));
    const all = selFiles.length === files.length;
    if (!up.current) {
      // 올리기 전: 목록에서만 제거(전체면 초기화)
      if (all) return resetLocal();
      setFiles(files.filter((f) => !gone.has(f.rel)));
      setSelected(new Set());
      clearResult();
      onChange(null);
      return;
    }
    setClearing(true);
    try {
      if (all) {
        await up.current.cancel(); // 세션 취소(서버가 _backup 으로 옮김)
        return resetLocal();
      }
      const wasDone = prog?.phase === "done";
      await up.current.remove(selFiles.map((f) => f.idx!));
      setFiles((old) => old.filter((f) => !gone.has(f.rel)));
      setSelected(new Set());
      clearResult();
      onChange(null);
      if (wasDone) {
        setNote("파일을 지워 서버에서 다시 확인하는 중…");
        await complete();
        setNote("파일을 지운 뒤 다시 확인했습니다(재검사).");
      }
    } catch (e) {
      setError(clearErrorText(e));
    } finally {
      setClearing(false);
    }
  }

  const total = prog && started ? prog.total : files.reduce((s, f) => s + f.file.size, 0);
  const count = (k: Kind) => files.filter((f) => f.rel.startsWith(`${k}/`)).length;
  const radN = count("rad");
  const h3dN = count("h3d");
  const resN = count("results");
  const sent = prog?.sent ?? 0;
  const frac = total ? sent / total : 0;
  const rate = prog?.rate ?? null;
  const left = Math.max(0, total - sent);
  const hasRad = files.some((f) => /^rad\/.*\.rad$/i.test(f.rel));
  const startReason = !files.length ? "파일을 고르세요" : !hasRad ? "rad 파일(_0000.rad)을 포함하세요" : !h3dN && !resN ? "h3d 파일을 고르세요(또는 추출 결과 폴더)" : null;
  const lock = disabled || busy || clearing || prog?.phase === "done";
  const bigH3d = hintGb > 0 ? files.find((f) => f.rel.startsWith("h3d/") && f.file.size > hintGb * GIB) : undefined;
  const resumeLabel = !!prog && (prog.phase === "error" || prog.phase === "paused" || (prog.phase === "uploaded" && left > 0));
  const limitHit = prog?.errorCode === "UPLOAD_LIMIT";

  const openList = (
    <OpenUploads
      refreshKey={listKey}
      forceOpen={limitHit}
      fallback={prog?.errorOpen ?? []}
      activeId={up.current?.uploadId ?? initialUploadId ?? null}
      onResume={(id) => onOpenUpload?.(id)}
      onCancelled={(id) => {
        if (up.current?.uploadId === id) resetLocal();
        else if (initialUploadId === id) setPcUpload(null);
        if (limitHit) setError(null);
      }}
    />
  );

  if (pcUpload)
    return (
      <div className="upload-panel" data-testid="pc-upload">
        <div className={pcUpload.partial ? "inspect bad" : "inspect ok"}>
          <div>
            {pcUpload.partial ? <Badge kind="warn">다 받지 못함</Badge> : <Badge kind="info">PC에서 올림</Badge>} <b>{pcUpload.name}</b>{" "}
            {pcUpload.meta && (
              <span title={slimTip(pcUpload.meta)} data-testid="pc-upload-mode">
                <Badge kind={pcUpload.meta.kind === "h3d_slim" ? "ok" : "info"}>{pcUpload.meta.kind === "h3d_slim" ? "압축 모드" : "원본"}</Badge>{" "}
                <span className="small">{slimLine(pcUpload.meta)}</span>{" "}
              </span>
            )}
            <span className="muted">
              {pcUpload.n}개 · {bytes(pcUpload.bytes)} —{" "}
              {pcUpload.partial
                ? "일부만 받은 업로드입니다. 같은 파일을 '내 PC에서 올리기'에서 다시 고르면 이어 올립니다(PC 도구면 같은 명령을 다시 실행)."
                : "ESL_extract.bat 이 추출해 올린 파일입니다. 아래 Case 정보를 확인하고 'Case 만들기'."}
            </span>
          </div>
          {pcUpload.partial && (
            <ul className="small mono" data-testid="partial-files">
              {pcUpload.partial.map((f) => (
                <li key={f.rel}>
                  {f.rel} · {bytes(f.got)} / {bytes(f.size)}
                </li>
              ))}
            </ul>
          )}
        </div>
        <ResultView result={result} />
        <ErrorLine text={error} />
        {openList}
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
      {bigH3d && (
        <div className="small big-h3d-hint" data-testid="big-h3d-hint" role="note">
          {bigH3dText(bigH3d.file.size)}{" "}
          {onOpenPcTab && (
            <button type="button" className="linkbtn" onClick={onOpenPcTab}>
              'PC에서 추출해 올리기' 탭 열기
            </button>
          )}
        </div>
      )}
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
                  <th className="chk">
                    <input ref={allRef} type="checkbox" aria-label="전체 선택" checked={allSel} disabled={rows.length === 0} onChange={toggleAll} />
                  </th>
                  <th>파일</th>
                  <th className="num">크기</th>
                  <th className="num">받음</th>
                </tr>
              </thead>
              <tbody>
                {files.map((f, i) => {
                  const rec = (f.idx !== undefined ? prog?.received[f.idx] : 0) ?? 0;
                  const ok = selectable(f);
                  const isSending = f.idx !== undefined && sending.has(f.idx);
                  return (
                    <tr key={f.rel} className={selected.has(f.rel) && ok ? "sel" : undefined}>
                      <td className="chk" title={isSending ? SENDING_TIP : undefined}>
                        <input type="checkbox" aria-label="파일 선택" data-testid={`row-check-${i}`} checked={ok && selected.has(f.rel)} disabled={!ok} onChange={() => toggle(f.rel)} />
                      </td>
                      <td className="mono">{f.rel}</td>
                      <td className="num">{bytes(f.file.size)}</td>
                      <td className="num">{rec >= f.file.size && f.file.size > 0 ? "✓" : rec ? `${Math.floor((rec / f.file.size) * 100)}%` : isSending ? "…" : "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="upload-summary" data-testid="upload-summary">
            <span>
              {files.length}개 · {bytes(files.reduce((s, f) => s + f.file.size, 0))}
            </span>
            <span className="muted">
              {prog && prog.phase === "uploading"
                ? rate
                  ? `${bytes(rate)}/s · 남은 시간 약 ${etaText(left, rate)}${prog.parallel > 1 ? ` · 동시 ${prog.inflight}/${prog.parallel}` : ""}`
                  : "속도 계산 중…"
                : !prog
                  ? `예상 약 ${etaText(total, ASSUMED_BPS)} (사내망 ${ASSUMED_BPS / 1024 ** 2} MB/s 가정)`
                  : null}
            </span>
            <span className="spacer" />
            {!busy && prog?.phase !== "done" && startReason && (
              <span className="small warn-text" data-testid="upload-start-reason">{startReason}</span>
            )}
            {!busy && prog?.phase !== "done" && (
              <span className="primary-wrap" title={startReason ?? undefined}>
                <button type="button" className="btn" disabled={!!startReason || disabled || clearing} onClick={() => void start()}>
                  {resumeLabel ? "이어 올리기" : prog?.phase === "uploaded" ? "다시 확인" : "올리기"}
                </button>
              </span>
            )}
            {prog?.phase === "uploading" && (
              <button type="button" className="btn ghost" onClick={() => up.current?.stop()}>
                멈춤
              </button>
            )}
            {clearReason && (
              <span className="small muted" data-testid="clear-reason">
                {clearReason}
              </span>
            )}
            <span className="primary-wrap" title={clearReason ?? undefined}>
              <button type="button" className="btn ghost" data-testid="clear-btn" disabled={selFiles.length === 0 || clearing || confirming} onClick={() => void clearSelected()}>
                지우기({selFiles.length})
              </button>
            </span>
          </div>
          {note && (
            <div className="small muted" data-testid="recheck-note" role="status">
              {note}
            </div>
          )}
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
              {limitHit && (
                <div className="small warn-text" data-testid="upload-limit-note">
                  {LIMIT_NOTE}
                </div>
              )}
            </div>
          )}
        </>
      )}
      <ErrorLine text={error} />
      <ResultView result={result} onAdd={() => addRef.current?.click()} />
      <input ref={addRef} type="file" multiple hidden aria-label="추가로 올릴 include" onChange={(e) => (void addMissing(e.target.files), (e.target.value = ""))} />
      {openList}
    </div>
  );
}

interface PcUpload {
  id: string;
  name: string;
  n: number;
  bytes: number;
  meta?: H3dMeta | null;
  partial?: { rel: string; size: number; got: number }[];
}

/** 이슈 #29: 사용자당 열린(OPEN) 업로드 한도(UPLOAD_LIMIT)에 걸리는 업로드 세션 목록 — 작업 대기열과 별개 */
function OpenUploads({
  refreshKey,
  forceOpen,
  fallback,
  activeId,
  onResume,
  onCancelled,
}: {
  refreshKey: number;
  forceOpen: boolean;
  fallback: { upload_id: string; name: string }[];
  activeId: string | null;
  onResume: (id: string) => void;
  onCancelled: (id: string) => void;
}) {
  const [list, setList] = useState<UploadOut[] | null>(null);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    p3.uploads("OPEN").then(
      (l) => alive && setList(l),
      (e) => alive && (setList([]), setErr(errorText(e))),
    );
    return () => {
      alive = false;
    };
  }, [refreshKey, tick, forceOpen]);
  useEffect(() => {
    if (forceOpen) setOpen(true);
  }, [forceOpen]);

  async function cancel(u: { upload_id: string; name: string; n?: number; bytes?: number }) {
    const msg = `'${u.name}' 업로드를 취소할까요?\n올린 파일${u.n ? ` ${u.n}개(${bytes(u.bytes ?? 0)})` : ""}은 삭제되지 않고 서버의 _backup 폴더로 옮겨집니다.`;
    if (typeof window !== "undefined" && !window.confirm(msg)) return;
    setBusyId(u.upload_id);
    setErr(null);
    try {
      await p3.cancelUpload(u.upload_id);
      onCancelled(u.upload_id);
      setTick((t) => t + 1);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusyId(null);
    }
  }

  const rows: { id: string; name: string; u?: UploadOut }[] = (list ?? []).length
    ? (list ?? []).map((u) => ({ id: u.upload_id, name: u.name, u }))
    : list === null
      ? []
      : fallback.map((f) => ({ id: f.upload_id, name: f.name }));
  if (!rows.length && !err) return null;
  return (
    <details className="open-uploads" data-testid="open-uploads" open={open || forceOpen} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>진행 중인 업로드 ({rows.length})</summary>
      <div className="small muted">
        내가 시작했고 아직 닫지 않은 업로드입니다(사용자당 최대 2개). 같은 파일을 위 칸에서 다시 고르면 이어 올리고, 필요 없으면 취소하세요 — 취소해도 파일은 삭제되지 않고 서버 _backup 폴더로 옮겨집니다.
      </div>
      <div className="table-wrap scroll">
        <table className="table compact" aria-label="진행 중인 업로드">
          <thead>
            <tr>
              <th>이름</th>
              <th className="num">파일</th>
              <th className="num">받은 양 / 전체</th>
              <th>만든 시각</th>
              <th>상태</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map(({ id, name, u }) => {
              const live = u?.files.filter((f) => !f.removed) ?? [];
              const problems = u?.result && u.result.ok === false ? [...(u.result.problems ?? []), ...(u.result.missing_includes?.length ? [`include 누락 ${u.result.missing_includes.length}개`] : [])] : [];
              const full = !!u && u.total_bytes > 0 && u.received_bytes >= u.total_bytes;
              return (
                <tr key={id} data-testid={`open-upload-${id}`}>
                  <td>
                    {name}
                    {id === activeId && <span className="muted small"> (지금 화면)</span>}
                  </td>
                  <td className="num">{u ? live.length : "–"}</td>
                  <td className="num">{u ? `${bytes(u.received_bytes)} / ${bytes(u.total_bytes)}` : "–"}</td>
                  <td className="small">{u ? dt(u.created_at) : "–"}</td>
                  <td className="small">
                    {!u ? null : problems.length ? (
                      <>
                        <Badge kind="warn">검사 문제</Badge> {problems.join(" · ")}
                      </>
                    ) : full ? (
                      <Badge kind="info">다 올림 — 확인 대기</Badge>
                    ) : (
                      <Badge kind="info">받는 중 {Math.floor((u.received_bytes / Math.max(1, u.total_bytes)) * 100)}%</Badge>
                    )}
                  </td>
                  <td className="actions">
                    <button type="button" className="btn small" disabled={!u || busyId === id} onClick={() => onResume(id)}>
                      이어서 열기
                    </button>
                    <button type="button" className="btn small ghost" disabled={busyId === id} onClick={() => void cancel({ upload_id: id, name, n: u ? live.length : undefined, bytes: u?.total_bytes })}>
                      취소
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ErrorLine text={err} />
    </details>
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
