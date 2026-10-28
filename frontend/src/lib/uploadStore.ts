// 업로드 세션 저장소(앱 수준 싱글턴). Uploader 를 화면 컴포넌트가 아니라 여기서 쥐고 있어, 같은 브라우저 탭 안에서 다른 페이지로 갔다 와도
// 전송이 계속되고 돌아오면 같은 인스턴스에 다시 붙는다(SPA 이동만 대상 — 탭을 닫거나 새로고침하면 끊기고 '이어 올리기').
// 상단 바 진행 표시(UploadChip)와 beforeunload 경고(활성 전송 중에만)도 여기서 관리한다.
import { errorText } from "../api/client";
import type { UploadCompleteOut } from "../api/types";
import { Uploader, type PickedFile, type UploadProgress } from "./uploader";

export type Picked = { file: File; rel: string; /** 서버 업로드 항목 번호(세션이 생긴 뒤) */ idx?: number };

export interface Session {
  key: string;
  projectId: string;
  name: string;
  uploader: Uploader;
  files: Picked[];
  prog: UploadProgress | null;
  /** 마지막 complete 결과(파일을 지우거나 더하면 null 로 되돌림) */
  result: UploadCompleteOut | null;
  error: string | null;
  /** 확인까지 마친(ok) 시각 — 상단 표시 '업로드 완료 — 열기'를 잠깐 보이는 데 쓴다 */
  finishedAt: number | null;
}

/** '업로드 완료 — 열기'를 보이는 시간(ms) */
export const DONE_SHOW_MS = 8000;
const ACTIVE = new Set(["hashing", "uploading", "completing"]);

type Opts = ConstructorParameters<typeof Uploader>[4];

class UploadStore {
  private sessions = new Map<string, Session>();
  private subs = new Set<() => void>();
  private seq = 0;
  private version = 0;
  private unload: ((e: BeforeUnloadEvent) => void) | null = null;

  subscribe = (fn: () => void) => {
    this.subs.add(fn);
    return () => void this.subs.delete(fn);
  };
  /** useSyncExternalStore 용 스냅샷(바뀔 때마다 증가) */
  getVersion = () => this.version;

  private notify() {
    this.version += 1;
    this.syncUnload();
    for (const f of [...this.subs]) f();
  }

  list(): Session[] {
    return [...this.sessions.values()];
  }
  get(key: string | null | undefined): Session | undefined {
    return key ? this.sessions.get(key) : undefined;
  }
  findById(uploadId: string | null | undefined): Session | undefined {
    if (!uploadId) return undefined;
    return this.list().find((s) => s.uploader.uploadId === uploadId);
  }

  create(projectId: string, name: string, files: Picked[], opts?: Opts): Session {
    this.seq += 1;
    const key = `s${this.seq}`;
    const plain: PickedFile[] = files.map((f) => ({ file: f.file, rel: f.rel }));
    const uploader = new Uploader(projectId, name, plain, (p) => this.onProgress(key, p), opts);
    const s: Session = { key, projectId, name, uploader, files: files.map((f, i) => ({ ...f, idx: i })), prog: null, result: null, error: null, finishedAt: null };
    this.sessions.set(key, s);
    this.notify();
    return s;
  }

  private onProgress(key: string, p: UploadProgress) {
    const s = this.sessions.get(key);
    if (!s) return;
    s.prog = p;
    this.notify();
  }

  /** 화면이 바꾼 값(파일 목록·결과) 반영. result 가 바뀌면 구독자에게 알린다 */
  patch(key: string, patch: Partial<Pick<Session, "files" | "result" | "error">>) {
    const s = this.sessions.get(key);
    if (!s) return;
    const before = s.result;
    Object.assign(s, patch);
    if (patch.result !== undefined && patch.result !== before) {
      if (!patch.result) s.finishedAt = null;
      this.notify();
    }
  }

  /** 올리기(이어 올리기) 후 확인까지. 끝까지 보냈으면 true. 화면이 사라져도 계속된다 */
  async start(key: string): Promise<boolean> {
    const s = this.sessions.get(key);
    if (!s) return false;
    s.error = null;
    const ok = await s.uploader.run();
    if (ok) await this.complete(key);
    return ok;
  }

  async complete(key: string): Promise<UploadCompleteOut | null> {
    const s = this.sessions.get(key);
    if (!s) return null;
    try {
      const r = await s.uploader.complete();
      s.result = r;
      s.error = null;
      s.finishedAt = r.ok && r.state === "COMPLETED" ? Date.now() : null;
    } catch (e) {
      s.error = errorText(e);
    }
    this.notify();
    return s.result;
  }

  /** 세션 잊기(취소·초기화·Case 생성 뒤). 전송 중이면 멈춘다 */
  drop(key: string | null | undefined) {
    const s = this.get(key);
    if (!s) return;
    if (s.prog && ACTIVE.has(s.prog.phase)) s.uploader.stop();
    this.sessions.delete(s.key);
    this.notify();
  }

  /** 이 rad 경로로 Case 를 만들었으면 그 업로드 세션은 더 필요 없다 */
  dropByRad(radPath: string | null | undefined) {
    if (!radPath) return;
    for (const s of this.list()) if (s.result?.rad_path === radPath) this.drop(s.key);
  }

  /** 지금 전송(또는 확인) 중인 세션 */
  active(): Session[] {
    return this.list().filter((s) => s.prog && ACTIVE.has(s.prog.phase));
  }

  /** 상단 표시용: 전송 중인 세션, 없으면 방금 끝난 세션(DONE_SHOW_MS 안) */
  chip(now = Date.now()): { kind: "active"; n: number; pct: number; session: Session } | { kind: "done"; session: Session } | null {
    const act = this.active().filter((s) => s.uploader.uploadId);
    if (act.length) {
      const sent = act.reduce((a, s) => a + (s.prog?.sent ?? 0), 0);
      const total = act.reduce((a, s) => a + (s.prog?.total ?? 0), 0);
      return { kind: "active", n: act.length, pct: total ? Math.floor((sent / total) * 100) : 0, session: act[0] };
    }
    const done = this.list()
      .filter((s) => s.finishedAt && now - s.finishedAt < DONE_SHOW_MS && s.uploader.uploadId)
      .sort((a, b) => b.finishedAt! - a.finishedAt!)[0];
    return done ? { kind: "done", session: done } : null;
  }

  /** 활성 전송 중에만 beforeunload 경고(탭 닫기·새로고침). 끊겨도 이어 올리기로 계속 가능 */
  private syncUnload() {
    if (typeof window === "undefined") return;
    const busy = this.list().some((s) => s.prog && (s.prog.phase === "uploading" || s.prog.phase === "hashing"));
    if (busy && !this.unload) {
      this.unload = (e) => {
        e.preventDefault();
        e.returnValue = "";
      };
      window.addEventListener("beforeunload", this.unload);
    } else if (!busy && this.unload) {
      window.removeEventListener("beforeunload", this.unload);
      this.unload = null;
    }
  }

  /** 시험용: 모두 멈추고 비운다 */
  _reset() {
    for (const s of this.list()) s.uploader.stop();
    this.sessions.clear();
    this.notify();
  }
}

export const uploadStore = new UploadStore();

export function uploadPath(s: Session): string {
  return `/p/${s.projectId}/cases/new?upload=${s.uploader.uploadId}`;
}
