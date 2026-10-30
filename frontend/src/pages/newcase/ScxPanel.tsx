// 새 Case — SCX 드라이브에서 고르기(계약 esl_scx_relay.md §10.1 — 기능 A, v0.11.0).
// 루트(scx_drive.roots) → 폴더 → 힌트 배지(rad·h3d)로 고름 → [SCX에서 내려받기] → 워커 SCX_FETCH(파일별 진행·취소·재시도 = 파일 단위 이어받기)
// → 끝나면 기존 업로드 확인 결과(파트·누락 include) → 페이지의 [Case 만들기]. 드라이브 쓰기 없음.
import { useEffect, useRef, useState } from "react";
import { ApiError, errorText } from "../../api/client";
import { p3, putChunk } from "../../api/p3";
import { relJoin, scx, shortReason } from "../../api/scx";
import type { JobOut, ScxEntryOut, ScxBrowseOut, ScxHint, ScxStatusOut, UploadFileOut, UploadOut } from "../../api/types";
import { Badge, Empty, ErrorLine } from "../../components/ui";
import { JobProgress } from "../../components/JobProgress";
import { bytes, dt } from "../../lib/format";
import { ResultView, nameFromRad, normCheck, type Checked } from "./UploadPanel";
import type { InputSelection } from "./types";

const PICK_LABEL: Partial<Record<ScxHint, string>> = { rad: "rad 선택", h3d: "h3d 선택" };
/** 내려받을 때 자동으로 함께 받는 파일 종류(SR-D-8) */
export const AUTO_LABEL: Partial<Record<ScxHint, string>> = { engine: "엔진 rad · 자동", include: "include · 자동", state: "상태(.sta/.str) · 자동" };
export const SCX_AUTO_NOTE = "include·엔진 rad(_0001.rad…)·이전 런 상태 파일(.sta/.str)은 내려받을 때 rad를 읽어 자동으로 함께 받습니다.";
export const SCX_FETCH_LABEL = "SCX에서 내려받기";
export const SCX_RETRY_NOTE = "재시도하면 이미 받아 sha256 을 확인한 파일은 건너뛰고, 끊긴 파일만 처음부터 다시 받습니다.";

interface Picked {
  rel: string;
  name: string;
  size: number | null;
  display: string;
  /** rad 를 고른 폴더의 자동 포함 파일 수(엔진·상태) */
  engines?: number;
  states?: number;
}
interface Run {
  upload_id: string;
  job_id: string;
  root: string;
  rad: Picked;
  h3d: Picked;
}

const storeKey = (projectId: string) => `esl.scxFetch.${projectId}`;
function loadRun(projectId: string): Run | null {
  try {
    const s = sessionStorage.getItem(storeKey(projectId));
    return s ? (JSON.parse(s) as Run) : null;
  } catch {
    return null;
  }
}
function saveRun(projectId: string, run: Run | null) {
  try {
    if (run) sessionStorage.setItem(storeKey(projectId), JSON.stringify(run));
    else sessionStorage.removeItem(storeKey(projectId));
  } catch {
    /* 저장소 없음 — 진행은 화면을 떠나면 다시 붙지 않을 뿐 */
  }
}

/** Case 를 만든 뒤 진행 기록을 지운다(다음 새 Case 는 탐색부터) */
export const clearScxRun = (projectId: string) => saveRun(projectId, null);

/** 탭·패널 비활성 사유(SR-D-19). null = 사용 가능 */
export function scxTabReason(status: ScxStatusOut | null, statusError: string | null): string | null {
  if (statusError) return statusError;
  if (!status) return "SCX 연결 상태 확인 중…";
  if (!status.fetch.enabled) return status.fetch.reason ?? status.fetch.reason_code ?? "SCX 드라이브를 쓸 수 없습니다";
  return null;
}

export function ScxPanel({
  projectId,
  status,
  statusError,
  allowed,
  noPermission,
  isAdmin,
  name,
  onChange,
  onUploaded,
}: {
  projectId: string;
  status: ScxStatusOut | null;
  statusError: string | null;
  allowed: boolean;
  noPermission: string;
  isAdmin: boolean;
  /** 업로드 세션 이름(= Case 이름이 맞으면 그것) */
  name: string;
  onChange: (sel: InputSelection | null, suggestedName?: string) => void;
  /** 내려받기·확인이 끝난 업로드 세션 id — 호출 측이 ?upload=<id> 로 주소를 바꾼다 */
  onUploaded?: (uploadId: string) => void;
}) {
  const reason = scxTabReason(status, statusError);
  if (reason)
    return (
      <div className="scx-panel" data-testid="scx-off">
        <div className="inspect bad" role="status">
          <Badge kind="warn">사용할 수 없음</Badge> <span>{isAdmin ? reason : shortReason(reason)}</span>
          {!isAdmin && <span className="small muted"> — 계속되면 관리자에게 알리세요.</span>}
        </div>
        {isAdmin && status && (
          <details className="adv-input" data-testid="scx-admin-detail">
            <summary>관리자: 연결 상세</summary>
            <div className="adv-body small mono">
              <div>
                fetch: {status.fetch.reason_code ?? "OK"} · verify: {status.verify.reason_code ?? "OK"}
              </div>
              <div>
                relay: reachable={String(status.relay.reachable)} drive_state={status.relay.drive_state ?? "–"} job_api={String(status.relay.job_api)} max_download=
                {status.relay.max_download_bytes != null ? bytes(status.relay.max_download_bytes) : "–"} · 확인 {dt(status.relay.checked_at)}
              </div>
              <div>
                adapters: {status.adapters.version ?? "–"} ({status.adapters.commit ?? "–"})
              </div>
            </div>
          </details>
        )}
      </div>
    );
  if (!allowed)
    return (
      <div className="scx-panel">
        <div className="inspect bad">{noPermission}</div>
      </div>
    );
  return <ScxPanelOn projectId={projectId} status={status!} name={name} onChange={onChange} onUploaded={onUploaded} />;
}

function ScxPanelOn({
  projectId,
  status,
  name,
  onChange,
  onUploaded,
}: {
  projectId: string;
  status: ScxStatusOut;
  name: string;
  onChange: (sel: InputSelection | null, suggestedName?: string) => void;
  onUploaded?: (uploadId: string) => void;
}) {
  const [run, setRunRaw] = useState<Run | null>(() => loadRun(projectId));
  const setRun = (r: Run | null) => {
    setRunRaw(r);
    saveRun(projectId, r);
  };
  if (run) return <FetchView run={run} onRun={setRun} onChange={onChange} onUploaded={onUploaded} />;
  return <BrowseView projectId={projectId} status={status} name={name} onChange={onChange} onStarted={setRun} />;
}

// ---------------------------------------------------------------------------------------------- 폴더 탐색·선택
function BrowseView({
  projectId,
  status,
  name,
  onChange,
  onStarted,
}: {
  projectId: string;
  status: ScxStatusOut;
  name: string;
  onChange: (sel: InputSelection | null, suggestedName?: string) => void;
  onStarted: (r: Run) => void;
}) {
  const [root, setRoot] = useState(status.roots[0]?.key ?? "");
  const [rel, setRel] = useState<string[]>([]);
  const [data, setData] = useState<ScxBrowseOut | null>(null);
  const [more, setMore] = useState<ScxEntryOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [rad, setRad] = useState<Picked | null>(null);
  const [h3d, setH3d] = useState<Picked | null>(null);
  const [busy, setBusy] = useState(false);
  const [startErr, setStartErr] = useState<{ text: string; code: string | null; detail: Record<string, unknown> } | null>(null);

  const path = rel.join("/");
  useEffect(() => {
    let alive = true;
    setError(null);
    setMore([]);
    scx
      .browse(projectId, root, path)
      .then((d) => alive && setData(d))
      .catch((e) => alive && (setError(errorText(e)), setData((d) => (d ? { ...d, entries: [] } : d))));
    return () => {
      alive = false;
    };
  }, [projectId, root, path]);

  const entries = [...(data?.entries ?? []), ...more];
  const display = data?.display ?? "";
  const rootLabel = status.roots.find((r) => r.key === root)?.label ?? root;
  const isSel = (e: ScxEntryOut) => {
    const r = relJoin(path, e.name);
    return rad?.rel === r || h3d?.rel === r;
  };

  function choose(e: ScxEntryOut) {
    const p: Picked = { rel: relJoin(path, e.name), name: e.name, size: e.size, display: display ? `${display}/${e.name}` : e.name };
    setStartErr(null);
    if (e.hint === "rad") {
      const here = entries.filter((x) => x.kind === "file");
      setRad({ ...p, engines: here.filter((x) => x.hint === "engine").length, states: here.filter((x) => x.hint === "state").length });
      onChange(null, nameFromRad(e.name));
    } else if (e.hint === "h3d") setH3d(p);
  }

  // 크기 경고: 릴레이 내려받기 상한(health max_download_bytes) — 서버가 시작 전 422 SCX_FILE_TOO_LARGE 로 다시 검사
  const limit = status.relay.max_download_bytes;
  const tooBig = !!h3d && h3d.size != null && limit != null && h3d.size > limit;
  const startReason = !rad ? "rad(_0000.rad) 파일을 고르세요" : !h3d ? "h3d 파일을 고르세요" : tooBig ? `h3d가 릴레이 내려받기 상한(${bytes(limit!)})을 넘습니다` : busy ? "요청 중…" : null;

  async function start() {
    if (!rad || !h3d) return;
    setBusy(true);
    setStartErr(null);
    try {
      const out = await scx.createFetch({ project_id: projectId, name, root, rad_rel: rad.rel, h3d_rel: h3d.rel });
      onStarted({ upload_id: out.upload_id, job_id: out.job_id, root, rad, h3d });
    } catch (e) {
      // 507 은 업로드용 공통 문구(CODE_TEXT) 대신 서버 문구(필요·여유 값)를 그대로
      setStartErr({ text: e instanceof ApiError && e.code === "INSUFFICIENT_STORAGE" ? e.message : errorText(e), code: e instanceof ApiError ? e.code : null, detail: e instanceof ApiError ? (e.detail as Record<string, unknown>) : {} });
      setBusy(false);
    }
  }

  return (
    <div className="server-panel scx-panel" data-testid="scx-browse">
      <div className="browse-head">
        {status.roots.length > 1 ? (
          <label className="scx-root">
            <span className="field-label">루트</span>
            <select
              value={root}
              aria-label="SCX 루트"
              onChange={(e) => {
                setRoot(e.target.value);
                setRel([]);
                setRad(null);
                setH3d(null);
                onChange(null);
              }}
            >
              {status.roots.map((r) => (
                <option key={r.key} value={r.key}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <nav className="browse-crumbs" aria-label="폴더 경로">
          <button type="button" className="link" onClick={() => setRel([])}>
            {rootLabel}
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
        <span className="small muted mono ellipsis" title={display}>
          {display}
        </span>
      </div>
      <div className="small muted">폴더 이름을 눌러 들어가고, 오른쪽 배지를 눌러 고릅니다 — rad(_0000.rad) 1개와 h3d 1개. {SCX_AUTO_NOTE}</div>
      <ErrorLine text={error} />
      <div className="table-wrap scroll browse-list">
        <table className="table compact" aria-label="SCX 드라이브 폴더 목록">
          <thead>
            <tr>
              <th>이름</th>
              <th className="num">크기</th>
              <th>수정</th>
              <th>선택</th>
            </tr>
          </thead>
          <tbody>
            {rel.length > 0 && (
              <tr>
                <td colSpan={4}>
                  <button type="button" className="link" onClick={() => setRel(rel.slice(0, -1))}>
                    .. 위로
                  </button>
                </td>
              </tr>
            )}
            {entries.map((e) => (
              <tr key={e.name} className={isSel(e) ? "hl" : undefined}>
                <td>
                  {e.kind === "dir" ? (
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
                <td className="num">{e.kind === "file" && e.size != null ? bytes(e.size) : ""}</td>
                <td className="small muted">{e.modified_at ? dt(e.modified_at) : ""}</td>
                <td>
                  {e.hint && PICK_LABEL[e.hint] && (
                    <button type="button" className={`hint-badge ${e.hint}${isSel(e) ? " on" : ""}`} onClick={() => choose(e)} data-hint={e.hint}>
                      {isSel(e) ? "✓ " : ""}
                      {PICK_LABEL[e.hint]}
                    </button>
                  )}
                  {e.hint && AUTO_LABEL[e.hint] && (
                    <span className={`hint-badge auto ${e.hint}`} data-hint={e.hint}>
                      {AUTO_LABEL[e.hint]}
                    </span>
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
            {entries.length} / {data.total}개 표시
          </span>
          <button
            type="button"
            className="btn small"
            onClick={() =>
              scx
                .browse(projectId, root, path, entries.length)
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
          {rad ? <code title={rad.display}>{rad.display}</code> : <span className="muted small">아직 고르지 않음</span>}
          {rad?.size != null && <span className="small muted">{bytes(rad.size)}</span>}
        </div>
        {rad && (
          <div className="picked-row small" data-testid="scx-auto">
            <span className="field-label">자동 포함</span>
            <span>
              include(rad를 읽어 수집){rad.engines ? ` · 엔진 rad ${rad.engines}개` : ""}
              {rad.states ? (
                <>
                  {" · "}
                  <Badge kind="info">이전 런 상태</Badge> .sta/.str {rad.states}개
                </>
              ) : null}
            </span>
          </div>
        )}
        <div className="picked-row">
          <span className="field-label">h3d</span>
          {h3d ? <code title={h3d.display}>{h3d.display}</code> : <span className="muted small">아직 고르지 않음</span>}
          {h3d?.size != null && <span className="small muted">{bytes(h3d.size)}</span>}
          {h3d && !tooBig && <Badge kind="info">서버에서 추출</Badge>}
        </div>
        {tooBig && (
          <div className="small error-text" data-testid="scx-too-big">
            h3d {bytes(h3d!.size!)} 가 대시보드 릴레이 내려받기 상한 {bytes(limit!)} 를 넘습니다 — 관리자에게 상한 상향을 요청하거나 'PC에서 추출해 올리기'(압축 모드)를 쓰세요.
          </div>
        )}
      </div>

      <div className="actions">
        <span className="small muted">
          업로드 이름 <code>{name}</code>(아래 Case 이름) · 받은 파일은 내 업로드 폴더에 저장됩니다(드라이브는 읽기만)
        </span>
        <span className="spacer" />
        <span title={startReason ?? undefined}>
          <button type="button" className="btn" disabled={!!startReason} onClick={() => void start()} data-testid="scx-start">
            {busy ? "요청 중…" : SCX_FETCH_LABEL}
          </button>
        </span>
      </div>
      {startErr && <StartError e={startErr} />}
    </div>
  );
}

/** 시작 오류: 크기 상한(422)·여유 공간(507)·동시 업로드 한도(429)는 값과 함께 */
function StartError({ e }: { e: { text: string; code: string | null; detail: Record<string, unknown> } }) {
  const num = (k: string) => (typeof e.detail[k] === "number" ? (e.detail[k] as number) : null);
  return (
    <div className="inspect bad" role="alert" data-testid="scx-start-error">
      <div className="small error-text">{e.text}</div>
      {e.code === "INSUFFICIENT_STORAGE" && num("need") != null && (
        <div className="small">
          필요 {bytes(num("need")!)}
          {num("free") != null ? ` · 현재 여유 ${bytes(num("free")!)}` : ""}
          {num("reserve") != null ? ` · 남겨 둘 여유 ${bytes(num("reserve")!)}` : ""}
        </div>
      )}
      {e.code === "SCX_FILE_TOO_LARGE" && num("size") != null && num("limit") != null && (
        <div className="small">
          파일 {bytes(num("size")!)} · 상한 {bytes(num("limit")!)}
        </div>
      )}
      {e.code === "UPLOAD_LIMIT" && <div className="small muted">'내 PC에서 올리기' 탭의 진행 중인 업로드를 마치거나 취소한 뒤 다시 시도하세요.</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- 가져오기 진행·완료
function FetchView({
  run,
  onRun,
  onChange,
  onUploaded,
}: {
  run: Run;
  onRun: (r: Run | null) => void;
  onChange: (sel: InputSelection | null, suggestedName?: string) => void;
  onUploaded?: (uploadId: string) => void;
}) {
  const [upload, setUpload] = useState<UploadOut | null>(null);
  const [job, setJob] = useState<JobOut | null>(null);
  const [result, setResult] = useState<Checked | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const addRef = useRef<HTMLInputElement>(null);
  const done = upload?.state === "COMPLETED" || !!result;

  // 업로드 세션(파일별 받은 양) 갱신 — 작업이 끝날 때까지 2초마다
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const u = await p3.upload(run.upload_id);
        if (!alive) return;
        setUpload(u);
        if (u.state === "COMPLETED" && u.result) return apply(u);
        if (u.state === "CANCELED" || u.state === "STALE") return setError(`업로드 세션이 ${u.state === "CANCELED" ? "취소" : "정리"}되었습니다 — 다시 고르세요`);
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 404) return onRun(null);
        setError(errorText(e));
      }
      if (alive) timer = setTimeout(tick, 2000);
    };
    void tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [run.upload_id]); // eslint-disable-line react-hooks/exhaustive-deps

  function apply(u: UploadOut) {
    const r = normCheck({ ...(u.result ?? { ok: false }), upload_id: u.upload_id, state: u.state === "COMPLETED" ? "COMPLETED" : "OPEN" });
    setResult(r);
    const ok = r.ok && !!r.rad_path && !!r.h3d_path && r.missing_includes.length === 0;
    onChange(ok ? { rad_path: r.rad_path!, source: { kind: "h3d", path: r.h3d_path! }, parts: r.parts, ok: true } : null, nameFromRad(run.rad.name));
    if (u.state === "COMPLETED") onUploaded?.(u.upload_id);
  }

  async function onJobDone(j: JobOut) {
    // JobProgress 는 취소·재시도 직후 이전 상태로도 부른다 — 끝난 상태만 반영
    if (!["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.state)) return;
    setJob(j);
    if (j.state !== "SUCCEEDED") return;
    try {
      const u = await p3.upload(run.upload_id);
      setUpload(u);
      if (u.result) apply(u);
    } catch (e) {
      setError(errorText(e));
    }
  }

  /** 누락 include(루트 밖·절대경로라 받지 못한 것)를 같은 세션에 추가로 올리고 다시 확인 */
  async function addMissing(list: FileList | null) {
    if (!list || !result) return;
    const miss = result.missing_includes.map((m) => m.replace(/\\/g, "/"));
    setError(null);
    try {
      const picks = [...list].map((file) => {
        const hit = miss.find((m) => m.split("/").pop()!.toLowerCase() === file.name.toLowerCase());
        const safe = hit && !hit.startsWith("/") && !/^[A-Za-z]:/.test(hit) && !hit.split("/").includes("..");
        return { file, rel: safe ? (hit.startsWith("rad/") ? hit : `rad/${hit}`) : `rad/${file.name}` };
      });
      setAdding(`올리는 중 0 / ${picks.length}`);
      const u = await p3.addUploadFiles(run.upload_id, picks.map((p) => ({ rel: p.rel, size: p.file.size })));
      const C = u.chunk_size || 64 * 1024 ** 2;
      let k = 0;
      for (const p of picks) {
        const f = u.files.find((x) => x.rel === p.rel && !x.removed)!;
        for (let off = 0; off < p.file.size; off += C) await putChunk(run.upload_id, f.index, off, p.file.slice(off, off + C));
        setAdding(`올리는 중 ${++k} / ${picks.length}`);
      }
      await p3.completeUpload(run.upload_id);
      const nu = await p3.upload(run.upload_id);
      setUpload(nu);
      apply(nu);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setAdding(null);
    }
  }

  const files = (upload?.files ?? []).filter((f) => !f.removed);
  const hasH3d = files.some((f) => f.rel.startsWith("h3d/"));
  const terminal = job && ["FAILED", "CANCELED", "INTERRUPTED"].includes(job.state);

  return (
    <div className="server-panel scx-panel" data-testid="scx-fetch">
      <div className="upload-summary">
        <Badge kind={done ? "ok" : "info"}>{done ? "SCX에서 받음" : "SCX에서 내려받는 중"}</Badge>
        <b>{upload?.name ?? ""}</b>
        <span className="small muted mono ellipsis" title={run.rad.display}>
          {run.rad.display}
        </span>
        <span className="spacer" />
        {(done || terminal) && (
          <button
            type="button"
            className="btn small ghost"
            onClick={() => {
              onChange(null);
              onRun(null);
            }}
          >
            다른 파일 고르기
          </button>
        )}
      </div>
      {!done && <JobProgress jobId={run.job_id} onDone={(j) => void onJobDone(j)} onRetried={(nj) => (setJob(null), onRun({ ...run, job_id: nj.id }))} />}
      {terminal && <div className="small muted" data-testid="scx-retry-note">{SCX_RETRY_NOTE}{job!.state === "CANCELED" ? " 받은 파일은 업로드 세션에 남습니다('내 PC에서 올리기'의 진행 중인 업로드에서 정리)." : ""}</div>}
      <div className="table-wrap scroll upload-list">
        <table className="table compact" aria-label="내려받는 파일">
          <thead>
            <tr>
              <th>파일</th>
              <th className="num">크기</th>
              <th>상태</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <FileRow key={f.index} f={f} />
            ))}
            {!hasH3d && !done && (
              <tr className="muted">
                <td className="mono">h3d/{run.h3d.name}</td>
                <td className="num">{run.h3d.size != null ? bytes(run.h3d.size) : ""}</td>
                <td>대기</td>
              </tr>
            )}
            {!files.length && !done && (
              <tr className="muted">
                <td className="mono">rad/{run.rad.name} + include</td>
                <td className="num">{run.rad.size != null ? bytes(run.rad.size) : ""}</td>
                <td>대기</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {upload && (
        <div className="small muted" data-testid="scx-total">
          전체 {files.filter((f) => f.done).length} / {files.length + (hasH3d ? 0 : 1)}개 · {bytes(upload.received_bytes)} / {bytes(Math.max(upload.total_bytes, upload.received_bytes + (hasH3d ? 0 : run.h3d.size ?? 0)))}
        </div>
      )}
      {result && <ResultView result={result} onAdd={adding ? undefined : () => addRef.current?.click()} />}
      {adding && <div className="small">{adding}</div>}
      <input ref={addRef} type="file" multiple hidden aria-label="빠진 include 파일" onChange={(e) => (void addMissing(e.target.files), (e.target.value = ""))} />
      <ErrorLine text={error} />
      {done && result?.ok && <div className="small muted">아래 Case 정보를 확인하고 'Case 만들기'.</div>}
    </div>
  );
}

function FileRow({ f }: { f: UploadFileOut }) {
  const got = f.received_total ?? f.received;
  const pct = f.size ? Math.min(100, Math.round((got / f.size) * 100)) : 100;
  return (
    <tr>
      <td className="mono">{f.rel}</td>
      <td className="num">{bytes(f.size)}</td>
      <td>
        {f.done ? (
          <span title={f.sha256 ?? undefined}>
            <Badge kind="ok">받음</Badge> <span className="small muted">sha256 확인</span>
          </span>
        ) : got > 0 ? (
          <span className="file-prog" data-testid="file-progress">
            <span className="progress" role="progressbar" aria-label={`${f.rel} 진행률`} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <span className="progress-fill" style={{ width: `${pct}%` }} />
            </span>
            <span className="small">
              {bytes(got)} / {bytes(f.size)} ({pct}%)
            </span>
          </span>
        ) : (
          <span className="small muted">받는 중…</span>
        )}
      </td>
    </tr>
  );
}
