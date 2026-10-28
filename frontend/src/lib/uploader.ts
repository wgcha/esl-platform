// 분할 업로드. 계약 esl_upload_speed.md §5.5(v0.6.0 프로토콜 2) + esl_p3_ux.md §1.1·§6(세션·이어 올리기·sha256).
// - 세션을 만들면 서버가 protocol 2 를 알려 준다 → 청크(기본 64 MB)를 동시 min(max_parallel, 4)개 PUT. 작업 큐 = 파일 순서 → 청크 번호 순서
//   (받은 범위는 건너뜀)로 내보내 NTFS 0 채움을 줄인다. 이어 올리기 = 서버가 알려 주는 받은 청크 범위(`chunks`).
// - protocol 이 없는 구 서버·업그레이드 전 세션은 기존 순차 경로(offset 순서 검증, 서버 received).
// - sha256: 파일 전체는 계산하지 않는다. 청크마다 Web Crypto 로 계산해 X-Chunk-Sha256 으로 보내고, 같은 ArrayBuffer 를 본문으로 쓴다(두 번 읽지 않음).
//   crypto.subtle 이 없는 비보안 http 컨텍스트면 Blob 그대로(메모리 거의 0, 서버는 크기로만 검증).
import { ApiError, errorText } from "../api/client";
import { p3, putChunk } from "../api/p3";
import type { UploadCompleteOut, UploadFileIn, UploadFileOut, UploadOut } from "../api/types";

export const DEFAULT_CHUNK = 64 * 1024 ** 2;
/** 브라우저 동시 전송 상한(서버 max_parallel 과 작은 쪽) */
export const BROWSER_MAX_PARALLEL = 4;
/** 업로드 전 예상 시간 계산용 사내망 가정 속도(병렬 기준, 실측 전) */
export const ASSUMED_BPS = 60 * 1024 ** 2;
/** 속도 = 최근 10초 이동 평균 */
export const RATE_WINDOW_MS = 10_000;
const STORE = "esl.upload.";

export interface PickedFile {
  file: File;
  /** "rad/…" 또는 "results/…" */
  rel: string;
}

export type UploadPhase = "idle" | "hashing" | "uploading" | "paused" | "error" | "uploaded" | "completing" | "done";

export interface UploadProgress {
  phase: UploadPhase;
  /** 파일 index 별 받은 바이트(프로토콜 2 = 받은 청크 합, 1 = 연속 앞부분). 뺀 파일도 자리를 유지 */
  received: number[];
  /** 뺀 파일을 제외한 받은 바이트 합 */
  sent: number;
  /** 뺀 파일을 제외한 전체 바이트 */
  total: number;
  current: number;
  /** 최근 10초 이동 평균 전송 속도(B/s), 모르면 null */
  rate: number | null;
  retries: number;
  error: string | null;
  /** 오류 코드(예 UPLOAD_LIMIT)와, 서버가 함께 준 열린 업로드 목록(이슈 #29) */
  errorCode: string | null;
  errorOpen: { upload_id: string; name: string }[];
  uploadId: string | null;
  /** 이 브라우저에 남아 있던 세션을 서버가 받은 데부터 이어 올리는 중 */
  resumed: boolean;
  /** 지금 청크를 보내는 중인 파일 index(목록에서 선택 불가) */
  active: number[];
  /** 지금 PUT 이 진행 중인 청크 수 */
  inflight: number;
  /** 이 세션의 동시 전송 수(1 = 순차) */
  parallel: number;
  protocol: 1 | 2;
  /** 뺀 파일 index */
  removed: number[];
}

export interface Prepared {
  /** sha256 을 계산했으면 같은 ArrayBuffer, 아니면 Blob */
  body: Blob | ArrayBuffer;
  sha: string | null;
}

export interface UploaderDeps {
  createUpload: typeof p3.createUpload;
  upload: typeof p3.upload;
  addUploadFiles: typeof p3.addUploadFiles;
  completeUpload: typeof p3.completeUpload;
  cancelUpload: typeof p3.cancelUpload;
  removeUploadFile: typeof p3.removeUploadFile;
  putChunk: typeof putChunk;
  /** 청크 Blob → 본문 + sha256 (기본: Web Crypto 가 있으면 ArrayBuffer 한 번 읽고 해시) */
  prepare: (b: Blob) => Promise<Prepared>;
  sleep: (ms: number) => Promise<void>;
  now: () => number;
}

const defaultDeps: UploaderDeps = {
  createUpload: (b) => p3.createUpload(b),
  upload: (id) => p3.upload(id),
  addUploadFiles: (id, f) => p3.addUploadFiles(id, f),
  completeUpload: (id) => p3.completeUpload(id),
  cancelUpload: (id) => p3.cancelUpload(id),
  removeUploadFile: (id, i) => p3.removeUploadFile(id, i),
  putChunk,
  prepare: prepareChunk,
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  now: () => Date.now(),
};

/** 청크 시작 오프셋 목록(from 부터) */
export function planChunks(size: number, chunk: number, from = 0): { offset: number; end: number }[] {
  const out: { offset: number; end: number }[] = [];
  for (let o = from; o < size; o += chunk) out.push({ offset: o, end: Math.min(size, o + chunk) });
  return out;
}

export function sha256Available(): boolean {
  return typeof crypto !== "undefined" && !!crypto.subtle && typeof crypto.subtle.digest === "function";
}

/** File.slice 한 조각만 메모리로(Blob.arrayBuffer 가 없는 환경은 FileReader) */
function readBuf(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === "function") return blob.arrayBuffer();
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result as ArrayBuffer);
    r.onerror = () => rej(r.error);
    r.readAsArrayBuffer(blob);
  });
}

const hex = (h: ArrayBuffer) => [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");

export async function prepareChunk(blob: Blob): Promise<Prepared> {
  if (!sha256Available()) return { body: blob, sha: null };
  const buf = await readBuf(blob);
  try {
    return { body: buf, sha: hex(await crypto.subtle.digest("SHA-256", buf)) };
  } catch {
    return { body: buf, sha: null };
  }
}

export async function sha256Hex(blob: Blob): Promise<string | null> {
  if (!sha256Available()) return null;
  try {
    return hex(await crypto.subtle.digest("SHA-256", new Uint8Array(await readBuf(blob))));
  } catch {
    return null;
  }
}

/** 같은 파일 묶음을 다시 고르면 이전 세션을 이어 올리기 위한 서명 */
export function signature(projectId: string, files: PickedFile[]): string {
  return [projectId, ...files.map((f) => `${f.rel}:${f.file.size}:${f.file.lastModified}`)].join("|");
}

function storeGet(sig: string): { id: string; chunk: number } | null {
  try {
    const v = localStorage.getItem(STORE + sig);
    return v ? JSON.parse(v) : null;
  } catch {
    return null;
  }
}
function storeSet(sig: string, v: { id: string; chunk: number } | null) {
  try {
    if (v) localStorage.setItem(STORE + sig, JSON.stringify(v));
    else localStorage.removeItem(STORE + sig);
  } catch {
    /* 저장소 없음 */
  }
}

export function etaText(bytesLeft: number, bps: number): string {
  const s = Math.max(1, Math.round(bytesLeft / bps));
  if (s < 60) return `${s}초`;
  if (s < 3600) return `${Math.round(s / 60)}분`;
  return `${Math.floor(s / 3600)}시간 ${Math.round((s % 3600) / 60)}분`;
}

export interface RateSample {
  t: number;
  sent: number;
}
/** 최근 windowMs 이동 평균 속도(B/s). 샘플 = (시각, 받은 바이트) 오름차순, 받은 바이트가 늘 때만 쌓는다.
 *  분모는 now 까지라 멈추면 속도가 자연히 내려가고, 창 안에 샘플이 하나뿐(큰 청크가 느리게 도착)이면 바로 앞 샘플까지 넓혀 0 으로 떨어지지 않게 한다. */
export function movingRate(samples: RateSample[], now: number, windowMs = RATE_WINDOW_MS): number | null {
  if (samples.length < 2) return null;
  const last = samples[samples.length - 1];
  let k = samples.findIndex((s) => s.t >= now - windowMs);
  if (k < 0 || k >= samples.length - 1) k = samples.length - 2;
  const ref = samples[k];
  const dt = (now - ref.t) / 1000;
  if (dt < 0.5 || last.sent <= ref.sent) return null;
  return (last.sent - ref.sent) / dt;
}

interface FileState {
  size: number;
  /** 받은 청크 번호(프로토콜 2) */
  got: Set<number>;
  removed: boolean;
}

interface Task {
  i: number;
  k: number;
}
interface Ready extends Task, Prepared {
  off: number;
  len: number;
}

const isAbort = (e: unknown) => e instanceof ApiError && e.code === "ABORTED";

export class Uploader {
  files: PickedFile[];
  uploadId: string | null = null;
  chunk = DEFAULT_CHUNK;
  maxRetries: number;
  retryDelayMs: number;
  /** 시험용: 동시에 잡고 있던 청크 버퍼 최대 수, 동시 PUT 최대 수 */
  peakBuffers = 0;
  peakInflight = 0;
  private deps: UploaderDeps;
  private stopped = false;
  private abort = new AbortController();
  private p: UploadProgress;
  private sig: string;
  private st: FileState[];
  private samples: RateSample[] = [];
  private tickMs: number;
  private ticker: ReturnType<typeof setInterval> | null = null;
  // 병렬 전송 상태
  private queue: Task[] = [];
  private qpos = 0;
  private ahead: Promise<Ready | null> | null = null;
  private chain: Promise<unknown> = Promise.resolve();
  private fatal: unknown = null;
  private needRound = false;
  private bufs = 0;
  private inflight = 0;
  private activeN = new Map<number, number>();
  private restarts = new Map<number, number>();

  constructor(
    public projectId: string,
    public name: string,
    files: PickedFile[],
    private onProgress: (p: UploadProgress) => void = () => undefined,
    opts: { deps?: Partial<UploaderDeps>; maxRetries?: number; retryDelayMs?: number; tickMs?: number } = {},
  ) {
    this.files = [...files];
    this.deps = { ...defaultDeps, ...opts.deps };
    this.maxRetries = opts.maxRetries ?? 3;
    this.retryDelayMs = opts.retryDelayMs ?? 1000;
    this.tickMs = opts.tickMs ?? 1000;
    this.sig = signature(projectId, files);
    this.st = files.map((f) => ({ size: f.file.size, got: new Set<number>(), removed: false }));
    this.p = {
      phase: "idle",
      received: files.map(() => 0),
      sent: 0,
      total: 0,
      current: 0,
      rate: null,
      retries: 0,
      error: null,
      errorCode: null,
      errorOpen: [],
      uploadId: null,
      resumed: false,
      active: [],
      inflight: 0,
      parallel: 1,
      protocol: 1,
      removed: [],
    };
    this.p.total = this.total();
  }

  /** 뺀 파일을 제외한 전체 바이트 */
  total() {
    return this.files.reduce((s, f, i) => s + (this.st[i]?.removed ? 0 : f.file.size), 0);
  }

  /** 뺀 파일을 제외한 파일들 */
  live(): PickedFile[] {
    return this.files.filter((_, i) => !this.st[i].removed);
  }

  get protocol(): 1 | 2 {
    return this.p.protocol;
  }

  private emit(patch: Partial<UploadProgress> = {}) {
    this.p = { ...this.p, ...patch };
    this.p.sent = this.p.received.reduce((a, b, i) => a + (this.st[i]?.removed ? 0 : b), 0);
    this.p.total = this.total();
    this.p.active = [...this.activeN.keys()].sort((a, b) => a - b);
    this.p.inflight = this.inflight;
    this.p.removed = this.st.map((s, i) => (s.removed ? i : -1)).filter((i) => i >= 0);
    if (this.p.phase === "uploading") {
      const now = this.deps.now();
      const last = this.samples[this.samples.length - 1];
      if (!last || this.p.sent > last.sent) this.samples.push({ t: now, sent: this.p.sent });
      else if (this.p.sent < last.sent) this.samples = [{ t: now, sent: this.p.sent }]; // 파일을 빼거나 처음부터 다시: 기준 다시
      this.p.rate = movingRate(this.samples, now);
    }
    this.onProgress({ ...this.p, received: [...this.p.received], active: [...this.p.active], removed: [...this.p.removed] });
  }

  get progress() {
    return this.p;
  }

  stop() {
    this.stopped = true;
    this.abort.abort();
  }

  private specs(files: PickedFile[]): UploadFileIn[] {
    return files.map((f) => ({ rel: f.rel, size: f.file.size }));
  }

  private chunkLen(i: number, k: number): number {
    return Math.max(0, Math.min(this.chunk, this.st[i].size - k * this.chunk));
  }
  private nChunks(i: number): number {
    return Math.ceil(this.st[i].size / this.chunk);
  }
  private bytesOf(i: number): number {
    let b = 0;
    for (const k of this.st[i].got) b += this.chunkLen(i, k);
    return b;
  }

  /** 서버 상태를 로컬 상태에 반영(프로토콜·받은 청크 범위·뺀 파일) */
  private applyState(u: UploadOut) {
    this.p.protocol = u.protocol === 2 ? 2 : 1;
    this.p.parallel = this.p.protocol === 2 ? Math.max(1, Math.min(u.max_parallel ?? 1, BROWSER_MAX_PARALLEL)) : 1;
    if (u.chunk_size) this.chunk = u.chunk_size;
    const rec = [...this.p.received];
    for (const f of u.files) {
      const s = this.st[f.index];
      if (!s) continue;
      s.removed = !!f.removed;
      if (this.p.protocol === 2) {
        s.got = gotOf(f, this.chunk);
        rec[f.index] = this.bytesOf(f.index);
      } else {
        rec[f.index] = f.received ?? 0;
      }
    }
    this.p.received = rec;
  }

  /** 세션 확보: 저장된 세션이 살아 있으면 서버가 받은 데부터 이어 올리기 */
  private async ensureSession(): Promise<UploadOut> {
    if (!this.uploadId) {
      const saved = storeGet(this.sig);
      if (saved) {
        try {
          const st = await this.deps.upload(saved.id);
          if (st.state !== "OPEN") throw new Error(st.state);
          this.uploadId = saved.id;
          this.chunk = st.chunk_size || saved.chunk;
          this.applyState(st);
          this.p.resumed = st.files.some((x) => (x.received_total ?? x.received) > 0);
          return st;
        } catch {
          storeSet(this.sig, null);
        }
      }
      const created = await this.deps.createUpload({ project_id: this.projectId, name: this.name, files: this.specs(this.files), client: { name: "esl-web", version: "0.6.0" } });
      this.uploadId = created.upload_id;
      this.chunk = created.chunk_size || DEFAULT_CHUNK;
      this.applyState(created);
      storeSet(this.sig, { id: this.uploadId, chunk: this.chunk });
      return created;
    }
    const st = await this.deps.upload(this.uploadId);
    this.applyState(st);
    return st;
  }

  private async refresh() {
    const st = await this.deps.upload(this.uploadId!);
    this.applyState(st);
    this.emit();
    return st;
  }

  private startTicker() {
    this.stopTicker();
    if (this.tickMs > 0) this.ticker = setInterval(() => this.p.phase === "uploading" && this.emit(), this.tickMs);
  }
  private stopTicker() {
    if (this.ticker) clearInterval(this.ticker);
    this.ticker = null;
  }

  /** 올리기 시작 또는 이어 올리기. 끝까지 보내면 true */
  async run(): Promise<boolean> {
    this.stopped = false;
    this.abort = new AbortController();
    this.fatal = null;
    try {
      await this.ensureSession();
      this.samples = [];
      this.emit({ phase: "uploading", uploadId: this.uploadId, error: null, errorCode: null, errorOpen: [], rate: null });
      this.samples = [{ t: this.deps.now(), sent: this.p.sent }];
      this.startTicker();
      const ok = this.p.protocol === 2 ? await this.runParallel() : await this.runSequential();
      this.stopTicker();
      if (!ok) {
        this.emit({ phase: "paused" });
        return false;
      }
      this.emit({ phase: "uploaded" });
      return true;
    } catch (e) {
      this.stopTicker();
      const open = e instanceof ApiError && Array.isArray(e.detail.open) ? (e.detail.open as { upload_id: string; name: string }[]) : [];
      this.emit({ phase: "error", error: errorText(e), errorCode: e instanceof ApiError ? e.code : null, errorOpen: open });
      return false;
    }
  }

  // ------------------------------------------------------------------ 프로토콜 2: 병렬

  private pendingTasks(): Task[] {
    const out: Task[] = [];
    for (let i = 0; i < this.files.length; i++) {
      const s = this.st[i];
      if (s.removed || s.size === 0) continue;
      const n = this.nChunks(i);
      for (let k = 0; k < n; k++) if (!s.got.has(k)) out.push({ i, k });
    }
    return out;
  }

  private async runParallel(): Promise<boolean> {
    const N = Math.max(1, this.p.parallel);
    for (let round = 0; round < 10; round++) {
      const tasks = this.pendingTasks();
      if (!tasks.length) return true;
      this.queue = tasks;
      this.qpos = 0;
      this.ahead = null;
      this.needRound = false;
      await Promise.all(Array.from({ length: Math.min(N, tasks.length) }, () => this.worker()));
      this.ahead = null;
      if (this.fatal) throw this.fatal;
      if (this.stopped) return false;
      if (!this.needRound) break;
    }
    if (this.pendingTasks().length) throw new Error("서버가 받은 청크가 맞지 않습니다 — '이어 올리기'로 다시 시도하세요");
    return true;
  }

  private async worker(): Promise<void> {
    for (;;) {
      if (this.stopped || this.fatal) return;
      let t: Ready | null = null;
      try {
        t = await this.takeNext();
        if (!t) return;
        await this.sendReady(t);
      } catch (e) {
        if (!isAbort(e) && !this.fatal) this.fatal = e;
        if (!isAbort(e)) this.abort.abort();
        return;
      } finally {
        if (t) this.bufs -= 1;
      }
    }
  }

  /** 큐에서 다음 청크를 번호 순서로 하나씩(직렬) 꺼낸다. 꺼낸 뒤 바로 다음 청크를 미리 읽고 해시한다(최대 N+1 버퍼) */
  private takeNext(): Promise<Ready | null> {
    const p = this.chain.then(async () => {
      const cur = await (this.ahead ?? this.prepareNext());
      this.ahead = cur ? this.prepareNext() : null;
      this.ahead?.catch(() => undefined);
      return cur;
    });
    this.chain = p.catch(() => undefined);
    return p;
  }

  private async prepareNext(): Promise<Ready | null> {
    while (this.qpos < this.queue.length) {
      const t = this.queue[this.qpos++];
      const s = this.st[t.i];
      if (s.removed || s.got.has(t.k)) continue;
      const off = t.k * this.chunk;
      const len = this.chunkLen(t.i, t.k);
      this.bufs += 1;
      this.peakBuffers = Math.max(this.peakBuffers, this.bufs);
      try {
        const pr = await this.deps.prepare(this.files[t.i].file.slice(off, off + len));
        return { ...t, ...pr, off, len };
      } catch (e) {
        this.bufs -= 1;
        throw e;
      }
    }
    return null;
  }

  private markGot(i: number, k: number) {
    this.st[i].got.add(k);
    const rec = [...this.p.received];
    rec[i] = this.bytesOf(i);
    this.emit({ received: rec, current: i });
  }

  private setActive(i: number, d: 1 | -1) {
    const n = (this.activeN.get(i) ?? 0) + d;
    if (n > 0) this.activeN.set(i, n);
    else this.activeN.delete(i);
    this.inflight += d;
    this.peakInflight = Math.max(this.peakInflight, this.inflight);
  }

  /** 청크 하나 전송 + 재시도. 응답 규칙은 계약 §5.5 */
  private async sendReady(t: Ready): Promise<void> {
    let fails = 0;
    let waits = 0;
    for (;;) {
      const s = this.st[t.i];
      if (this.stopped || this.fatal) return;
      if (s.removed || s.got.has(t.k)) return;
      this.setActive(t.i, 1);
      this.emit();
      try {
        await this.deps.putChunk(this.uploadId!, t.i, t.off, t.body, t.sha, this.abort.signal);
        this.setActive(t.i, -1);
        this.markGot(t.i, t.k);
        return;
      } catch (e) {
        this.setActive(t.i, -1);
        this.emit();
        if (isAbort(e) || this.stopped) return;
        if (!(e instanceof ApiError)) throw e;
        const code = e.code;
        if (e.status === 429) {
          // 동시 제한: Retry-After 뒤 재시도(재시도 횟수에 안 셈)
          waits += 1;
          if (waits > 120) throw e;
          const ra = Number(e.detail.retry_after);
          await this.deps.sleep((ra > 0 ? ra : 1) * 1000);
          continue;
        }
        if (e.status === 409) {
          if (code === "UPLOAD_FILE_REMOVED") {
            this.st[t.i].removed = true;
            this.emit();
            return;
          }
          if (code === "UPLOAD_FILE_DONE") {
            for (let k = 0; k < this.nChunks(t.i); k++) this.st[t.i].got.add(k);
            this.markGot(t.i, t.k);
            return;
          }
          if (code === "UPLOAD_OFFSET_MISMATCH" || code === "CHUNK_IN_FLIGHT") {
            // 서버가 받은 범위로 다시 맞춘 뒤, 이미 받았으면 건너뛰고 아니면 다시 보낸다
            await this.refresh();
            if (this.st[t.i].got.has(t.k) || this.st[t.i].removed) return;
            fails += 1;
            if (fails > this.maxRetries + 1) throw e;
            if (code === "CHUNK_IN_FLIGHT") await this.deps.sleep(Math.min(2000, 200 * fails));
            continue;
          }
          throw e;
        }
        if (e.status === 422 && code === "SHA256_MISMATCH") {
          // 파일 전체 sha256 불일치: 서버가 받은 청크를 비웠다 → 그 파일을 처음부터 1회
          const n = this.restarts.get(t.i) ?? 0;
          if (n >= 1) throw e;
          this.restarts.set(t.i, n + 1);
          await this.refresh();
          this.needRound = true;
          return;
        }
        if (e.status === 507) throw e;
        const transient = e.status === 0 || e.status >= 500 || e.status === 408 || code === "CHUNK_SHA256_MISMATCH";
        if (!transient) throw e;
        fails += 1;
        this.p.retries += 1;
        if (fails > this.maxRetries) throw e;
        await this.deps.sleep(this.retryDelayMs * fails);
      }
    }
  }

  // ------------------------------------------------------------------ 프로토콜 1(구 서버): 순차

  private async runSequential(): Promise<boolean> {
    for (let i = 0; i < this.files.length; i++) {
      if (this.st[i].removed) continue;
      if (!(await this.sendFileSeq(i))) return false;
    }
    return true;
  }

  /** 파일 i 를 서버 received 부터 청크로. 서버가 offset 순서를 검증하므로 PUT 은 한 번에 1개, 다음 청크 읽기·sha256 은
   *  앞 청크 전송 중에 미리(파이프라인 2). 멈춤이면 false, 실패면 throw */
  private async sendFileSeq(i: number): Promise<boolean> {
    const f = this.files[i].file;
    let offset = this.p.received[i];
    const prep = (off: number) => {
      const blob = f.slice(off, Math.min(f.size, off + this.chunk));
      return { off, size: blob.size, ready: this.deps.prepare(blob) };
    };
    let cur = offset < f.size ? prep(offset) : null;
    let fails = 0;
    this.peakInflight = Math.max(this.peakInflight, 1);
    while (cur && offset < f.size) {
      if (this.stopped) return false;
      if (cur.off !== offset) cur = prep(offset);
      const nextOff = cur.off + cur.size;
      const ahead = nextOff < f.size ? prep(nextOff) : null;
      ahead?.ready.catch(() => undefined);
      try {
        const pr = await cur.ready;
        this.activeN.set(i, 1);
        this.inflight = 1;
        const r = await this.deps.putChunk(this.uploadId!, i, cur.off, pr.body, pr.sha, this.abort.signal);
        this.activeN.delete(i);
        this.inflight = 0;
        offset = r.received;
        fails = 0;
        cur = ahead && ahead.off === offset ? ahead : offset < f.size ? prep(offset) : null;
      } catch (e) {
        this.activeN.delete(i);
        this.inflight = 0;
        if (isAbort(e) || this.stopped) return false;
        const code = e instanceof ApiError ? e.code : "";
        if (e instanceof ApiError && e.status === 409) {
          // 순서 어긋남·이미 받음 → 서버 received 로 맞춤
          const rec = typeof e.detail.received === "number" ? (e.detail.received as number) : (await this.deps.upload(this.uploadId!)).files.find((x) => x.index === i)?.received;
          if (typeof rec === "number" && rec !== offset) {
            offset = rec;
            cur = offset < f.size ? prep(offset) : null;
            this.bump(i, offset);
            continue;
          }
        } else if (e instanceof ApiError && e.status >= 400 && e.status < 500 && ![408, 429].includes(e.status) && code !== "CHUNK_SHA256_MISMATCH") {
          throw e;
        } else if (e instanceof ApiError && e.status === 507) {
          throw e;
        }
        fails += 1;
        this.p.retries += 1;
        if (fails > this.maxRetries) throw e;
        await this.deps.sleep(this.retryDelayMs * fails);
        continue;
      }
      this.bump(i, offset);
    }
    return true;
  }

  private bump(i: number, offset: number) {
    const rec = [...this.p.received];
    rec[i] = offset;
    this.emit({ received: rec, current: i });
  }

  // ------------------------------------------------------------------ 파일 추가·빼기·세션 취소·확인

  /** 세션에 파일을 더 등록한다(올리기는 하지 않음). 새 파일의 시작 index 를 돌려준다 */
  async register(files: PickedFile[]): Promise<number> {
    if (!this.uploadId) throw new Error("업로드 세션이 없습니다");
    const res = await this.deps.addUploadFiles(this.uploadId, this.specs(files));
    const start = this.files.length;
    this.files.push(...files);
    this.st.push(...files.map((f) => ({ size: f.file.size, got: new Set<number>(), removed: false })));
    this.p.received.push(...files.map(() => 0));
    this.applyState(res);
    this.resign();
    this.emit();
    return start;
  }

  /** 누락 include 등 파일 추가 후 이어 올리기 */
  async add(files: PickedFile[]): Promise<boolean> {
    await this.register(files);
    return this.run();
  }

  private resign() {
    if (!this.uploadId) return;
    storeSet(this.sig, null);
    this.sig = signature(this.projectId, this.live());
    storeSet(this.sig, { id: this.uploadId, chunk: this.chunk });
  }

  /** 프로토콜 2 에서만 파일 하나씩 뺄 수 있다(구 서버·업그레이드 전 세션은 세션 취소만) */
  get canRemove() {
    return !this.uploadId || this.p.protocol === 2;
  }

  /** 계약 US-17/18: 선택한 파일을 큐에서 빼고 서버 DELETE /uploads/{id}/files/{index}. 보내는 중인 파일은 서버가 BUSY 로 막을 수 있어 몇 번 다시 시도 */
  async remove(indexes: number[]): Promise<UploadOut | null> {
    if (!this.uploadId) {
      for (const i of indexes) if (this.st[i]) this.st[i].removed = true;
      this.emit();
      return null;
    }
    if (this.p.protocol !== 2) throw new Error("이 서버는 올리던 파일을 하나씩 뺄 수 없습니다 — 전부 선택해 지우면 업로드를 취소합니다.");
    const was = indexes.filter((i) => this.st[i] && !this.st[i].removed);
    for (const i of was) this.st[i].removed = true; // 큐에서 즉시 제외
    this.emit();
    let last: UploadOut | null = null;
    const done: number[] = [];
    try {
      for (const i of was) {
        for (let a = 0; ; a++) {
          try {
            last = await this.deps.removeUploadFile(this.uploadId, i);
            done.push(i);
            break;
          } catch (e) {
            if (e instanceof ApiError && e.code === "UPLOAD_FILE_BUSY" && a < 4) {
              await this.deps.sleep(300 * (a + 1));
              continue;
            }
            throw e;
          }
        }
      }
    } catch (e) {
      for (const i of was) if (!done.includes(i)) this.st[i].removed = false;
      this.emit();
      throw e;
    }
    if (last) this.applyState(last);
    this.resign();
    // 전부 완료된 세션(COMPLETED)에서 뺐으면 서버는 OPEN 으로 돌아간다 → 호출자가 다시 complete
    if (this.p.phase === "done") this.emit({ phase: "uploaded", error: null });
    else this.emit();
    return last;
  }

  /** 전체 선택 후 지우기 = 세션 취소(서버가 _backup 으로 옮김). COMPLETED 는 취소가 안 되므로 파일을 모두 뺀다 */
  async cancel(): Promise<void> {
    this.stop();
    this.stopTicker();
    if (this.uploadId) {
      try {
        await this.deps.cancelUpload(this.uploadId);
      } catch (e) {
        const completed = e instanceof ApiError && e.status === 409 && (e.code === "UPLOAD_COMPLETED" || e.code === "UPLOAD_NOT_OPEN" || this.p.phase === "done");
        if (!completed) throw e;
        await this.remove(this.files.map((_, i) => i).filter((i) => !this.st[i].removed));
      }
      storeSet(this.sig, null);
      this.uploadId = null;
    }
    this.files.forEach((_, i) => (this.st[i].removed = true));
    this.emit({ phase: "idle", uploadId: null, error: null, rate: null });
  }

  async complete(): Promise<UploadCompleteOut> {
    this.emit({ phase: "completing" });
    try {
      const r = await this.deps.completeUpload(this.uploadId!);
      const ok = r.ok && r.state === "COMPLETED";
      if (ok) storeSet(this.sig, null);
      this.emit({ phase: ok ? "done" : "uploaded" });
      return r;
    } catch (e) {
      if (e instanceof ApiError && e.code === "UPLOAD_INCOMPLETE") {
        // 서버가 아직 다 받지 못한 파일이 있다고 한다 → 받은 범위를 다시 읽고 이어 올리기로
        try {
          await this.refresh();
        } catch {
          /* 다음 이어 올리기에서 다시 읽는다 */
        }
        this.emit({ phase: "paused", error: "서버가 다 받지 못한 파일이 있습니다 — '이어 올리기'로 빠진 부분만 보냅니다." });
        throw e;
      }
      this.emit({ phase: "uploaded", error: errorText(e) });
      throw e;
    }
  }
}

/** 서버 파일 항목 → 받은 청크 번호 집합 */
function gotOf(f: UploadFileOut, chunk: number): Set<number> {
  const n = Math.ceil(f.size / chunk);
  const out = new Set<number>();
  if (f.done) {
    for (let k = 0; k < n; k++) out.add(k);
  } else if (f.chunks) {
    for (const [a, b] of f.chunks) for (let k = a; k < Math.min(b, n); k++) out.add(k);
  } else {
    for (let k = 0; k < Math.floor((f.received ?? 0) / chunk); k++) out.add(k);
  }
  return out;
}
