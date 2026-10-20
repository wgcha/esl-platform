// 분할 업로드(계약 esl_p3_ux.md §1.1·§6): 세션 만들기 → 파일별 청크 PUT(File.slice 스트리밍, 동시 2청크) → 실패 시 재시도·서버 received 로 맞춤
// → 이어 올리기(탭을 닫았다 같은 파일을 다시 고르면 localStorage 세션 + 서버 received 부터).
// sha256: h3d 는 수십 GB 라 파일 전체 해시는 계산하지 않는다. 청크(16 MB)마다 Web Crypto 로 계산해 X-Chunk-Sha256 헤더로 보낸다
// (crypto.subtle 이 없는 비보안 http 컨텍스트면 생략 — 서버는 크기로만 검증).
import { ApiError, errorText } from "../api/client";
import { p3, putChunk } from "../api/p3";
import type { UploadCompleteOut, UploadFileIn, UploadOut } from "../api/types";

/** 파이프라인 깊이: 보내는 청크 1 + 미리 읽고 해시하는 청크 1(서버가 offset 순서를 검증해 PUT 동시 전송은 안 함) */
export const PARALLEL = 2;
export const DEFAULT_CHUNK = 16 * 1024 ** 2;
/** 업로드 전 예상 시간 계산용 사내망 가정 속도(실측 전) */
export const ASSUMED_BPS = 30 * 1024 ** 2;
const STORE = "esl.upload.";

export interface PickedFile {
  file: File;
  /** "rad/…" 또는 "results/…" */
  rel: string;
}

export type UploadPhase = "idle" | "hashing" | "uploading" | "paused" | "error" | "uploaded" | "completing" | "done";

export interface UploadProgress {
  phase: UploadPhase;
  received: number[];
  sent: number;
  total: number;
  current: number;
  /** 실측 전송 속도(B/s), 모르면 null */
  rate: number | null;
  retries: number;
  error: string | null;
  uploadId: string | null;
  /** 이 브라우저에 남아 있던 세션을 서버 received 부터 이어 올리는 중 */
  resumed: boolean;
}

export interface UploaderDeps {
  createUpload: typeof p3.createUpload;
  upload: typeof p3.upload;
  addUploadFiles: typeof p3.addUploadFiles;
  completeUpload: typeof p3.completeUpload;
  putChunk: typeof putChunk;
  hash: (b: Blob) => Promise<string | null>;
  sleep: (ms: number) => Promise<void>;
  now: () => number;
}

const defaultDeps: UploaderDeps = {
  createUpload: (b) => p3.createUpload(b),
  upload: (id) => p3.upload(id),
  addUploadFiles: (id, f) => p3.addUploadFiles(id, f),
  completeUpload: (id) => p3.completeUpload(id),
  putChunk,
  hash: sha256Hex,
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

export async function sha256Hex(blob: Blob): Promise<string | null> {
  if (!sha256Available()) return null;
  try {
    const h = await crypto.subtle.digest("SHA-256", new Uint8Array(await readBuf(blob)));
    return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
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

export class Uploader {
  files: PickedFile[];
  uploadId: string | null = null;
  chunk = DEFAULT_CHUNK;
  maxRetries: number;
  retryDelayMs: number;
  private deps: UploaderDeps;
  private stopped = false;
  private p: UploadProgress;
  private sig: string;
  private t0 = 0;
  private sent0 = 0;

  constructor(
    public projectId: string,
    public name: string,
    files: PickedFile[],
    private onProgress: (p: UploadProgress) => void = () => undefined,
    opts: { deps?: Partial<UploaderDeps>; maxRetries?: number; retryDelayMs?: number } = {},
  ) {
    this.files = [...files];
    this.deps = { ...defaultDeps, ...opts.deps };
    this.maxRetries = opts.maxRetries ?? 3;
    this.retryDelayMs = opts.retryDelayMs ?? 1000;
    this.sig = signature(projectId, files);
    this.p = { phase: "idle", received: files.map(() => 0), sent: 0, total: this.total(), current: 0, rate: null, retries: 0, error: null, uploadId: null, resumed: false };
  }

  total() {
    return this.files.reduce((s, f) => s + f.file.size, 0);
  }

  private emit(patch: Partial<UploadProgress>) {
    this.p = { ...this.p, ...patch };
    this.p.sent = this.p.received.reduce((a, b) => a + b, 0);
    this.p.total = this.total();
    const dt = (this.deps.now() - this.t0) / 1000;
    if (this.p.phase === "uploading" && dt > 0.5) this.p.rate = (this.p.sent - this.sent0) / dt;
    this.onProgress({ ...this.p, received: [...this.p.received] });
  }

  get progress() {
    return this.p;
  }

  stop() {
    this.stopped = true;
  }

  private specs(files: PickedFile[]): UploadFileIn[] {
    return files.map((f) => ({ rel: f.rel, size: f.file.size }));
  }

  /** 세션 확보: 저장된 세션이 살아 있으면 서버 received 로 이어 올리기 */
  private async ensureSession(): Promise<UploadOut | null> {
    if (!this.uploadId) {
      const saved = storeGet(this.sig);
      if (saved) {
        try {
          const st = await this.deps.upload(saved.id);
          if (st.state !== "OPEN") throw new Error(st.state);
          this.uploadId = saved.id;
          this.chunk = saved.chunk;
          this.p.resumed = st.files.some((x) => x.received > 0);
          return st;
        } catch {
          storeSet(this.sig, null);
        }
      }
      const created = await this.deps.createUpload({ project_id: this.projectId, name: this.name, files: this.specs(this.files) });
      this.uploadId = created.upload_id;
      this.chunk = created.chunk_size || DEFAULT_CHUNK;
      storeSet(this.sig, { id: this.uploadId, chunk: this.chunk });
      return created;
    }
    return this.deps.upload(this.uploadId);
  }

  /** 올리기 시작 또는 이어 올리기. 끝까지 보내면 true */
  async run(): Promise<boolean> {
    this.stopped = false;
    try {
      const st = await this.ensureSession();
      const received = this.files.map((_, i) => st?.files.find((x) => x.index === i)?.received ?? this.p.received[i] ?? 0);
      this.t0 = this.deps.now();
      this.sent0 = received.reduce((a, b) => a + b, 0);
      this.emit({ phase: "uploading", received, uploadId: this.uploadId, error: null, rate: null });
      for (let i = 0; i < this.files.length; i++) {
        if (!(await this.sendFile(i))) {
          this.emit({ phase: "paused" });
          return false;
        }
      }
      this.emit({ phase: "uploaded" });
      return true;
    } catch (e) {
      this.emit({ phase: "error", error: errorText(e) });
      return false;
    }
  }

  /** 파일 i 를 received 부터 청크로. 서버가 offset 순서를 검증하므로 PUT 은 한 번에 1개, 다음 청크 읽기·sha256 은
   *  앞 청크 전송 중에 미리(파이프라인 PARALLEL=2). 멈춤이면 false, 실패면 throw */
  private async sendFile(i: number): Promise<boolean> {
    const f = this.files[i].file;
    let offset = this.p.received[i];
    const prep = (off: number) => {
      const blob = f.slice(off, Math.min(f.size, off + this.chunk));
      return { off, blob, sha: this.deps.hash(blob) };
    };
    let cur = offset < f.size ? prep(offset) : null;
    let fails = 0;
    while (cur && offset < f.size) {
      if (this.stopped) return false;
      if (cur.off !== offset) cur = prep(offset);
      const nextOff = cur.off + cur.blob.size;
      const ahead = nextOff < f.size ? prep(nextOff) : null; // 미리 읽기·해시(최대 2청크 메모리)
      try {
        const r = await this.deps.putChunk(this.uploadId!, i, cur.off, cur.blob, await cur.sha);
        offset = r.received;
        fails = 0;
        cur = ahead && ahead.off === offset ? ahead : offset < f.size ? prep(offset) : null;
      } catch (e) {
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

  /** 누락 include 등 파일 추가 후 이어 올리기 */
  async add(files: PickedFile[]): Promise<boolean> {
    if (!this.uploadId) throw new Error("업로드 세션이 없습니다");
    await this.deps.addUploadFiles(this.uploadId, this.specs(files));
    this.files.push(...files);
    this.p.received.push(...files.map(() => 0));
    return this.run();
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
      this.emit({ phase: "uploaded", error: errorText(e) });
      throw e;
    }
  }
}
