// 목 서버 v0.11.0 SCX 드라이브에서 고르기(계약 esl_scx_relay.md §5·§7·§8·§9.1 — 기능 A).
// 백엔드·워커는 병렬 개발 중 — 이 목은 계약 스키마(ScxStatusOut·ScxBrowseOut·ScxFetchIn/Out)와 오류 코드만 따른다.
import type { Avail, JobOut, JobProgressLabel, ScxBrowseEntry, ScxHint, ScxStatusOut, StepOut } from "../api/types";
import type { P3Mock } from "./p3mock";

interface MockResponse {
  status: number;
  body?: unknown;
}
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResponse => ({
  status,
  body: { detail: { code, message, ...extra } },
});

const KB = 1024;
const MB = 1024 ** 2;
const GB = 1024 ** 3;
type DTree = { [name: string]: DTree | number };

/** 목 설정 scx_drive.roots(릴레이 홈 기준 상대) — projects [] = 모든 프로젝트 */
export const MOCK_SCX_ROOTS: { key: string; label: string; rel: string; projects: string[] }[] = [
  { key: "drop", label: "낙하해석 공유", rel: "share/drop", projects: [] },
  { key: "pkg", label: "포장 낙하(바디)", rel: "share/pkg", projects: ["p-body"] },
];
export const MOCK_SCX_HOME = "/Users/vd.dashboard";
/** 목 adapters lock(commit 12자) — 세션 client.version */
export const MOCK_SCX_COMMIT = "a363a89e8f93";

const scene = (stem: string, h3d: number, extra: DTree = {}): DTree => ({
  [`${stem}_0000.rad`]: 1.2 * MB,
  [`${stem}_0001.rad`]: 4 * KB,
  "inc_mat.inc": 61 * KB,
  "inc_mesh.inc": 140 * MB,
  [`${stem}.h3d`]: h3d,
  [`${stem}_0001.out`]: 2.1 * MB,
  ...extra,
});
const TREES: Record<string, DTree> = {
  drop: {
    "75QN90": {
      drop_front: scene("ref", 28.4 * GB),
      drop_corner_LT: scene("corner", 24.1 * GB, { "corner_prev.sta": 380 * MB }),
      "drop_edge_B": { "edge_0000.rad": 1.1 * MB, "inc_mat.inc": 61 * KB, "edge.h3d": 22.7 * GB },
      // 릴레이 상한(목 64 GiB)을 넘는 h3d — 크기 경고 시연
      drop_full_rec: scene("full", 70 * GB),
    },
    "65QN80": { drop_rear: scene("rear", 18.2 * GB) },
    ".scx_tmp": { "x.part": 1 },
    "readme.txt": 1 * KB,
  },
  pkg: { "QN80H_75": { corner_drop_LT: scene("pkg", 7.1 * GB) } },
};

/** §7.1 hint 규칙(engine_globs 기본 {stem}_0001.rad·{stem}_000[2-9].rad) */
export function scxHint(name: string): ScxHint | null {
  if (/_0000\.rad$/i.test(name)) return "rad";
  if (/_000[1-9]\.rad$/i.test(name)) return "engine";
  if (/\.h3d$/i.test(name)) return "h3d";
  if (/\.(inc|k)$/i.test(name)) return "include";
  if (/\.(sta|str)$/i.test(name)) return "state";
  return null;
}

type Mode = "ok" | "disabled" | "down" | "no_roots";
interface Fetch {
  upload_id: string;
  root: string;
  rad_rel: string;
  h3d_rel: string;
}

export class ScxMock {
  /** 시연·시험: ok | disabled(scx_drive.enabled false) | down(대시보드 다운) | no_roots */
  mode: Mode = "ok";
  /** 목 health max_download_bytes(64 GiB) */
  maxDownload = 64 * GB;
  pageSize = 200;
  /** 다음 SCX_FETCH 를 이 step 에서 1회 실패(재시도 시험·시연) */
  failOnce: { step: "SF_RAD" | "SF_H3D"; code: string; message: string } | null = null;
  /** SF_H3D 진행(틱당 비율, %) */
  h3dStepPct = 25;
  fetches = new Map<string, Fetch>();
  /** 시험: 마지막 POST /scx/fetches 본문 */
  lastFetchIn: Record<string, unknown> | null = null;

  constructor(
    private ctx: {
      p3: P3Mock;
      canRun: (pid: string) => boolean;
      newJob: (pid: string, params: Record<string, unknown>) => JobOut;
      log: (jobId: string, line: string) => void;
      now: () => string;
    },
  ) {}

  private rootsFor(pid: string) {
    if (this.mode === "no_roots") return [];
    return MOCK_SCX_ROOTS.filter((r) => !r.projects.length || r.projects.includes(pid));
  }

  fetchAvail(pid: string): Avail {
    if (this.mode === "disabled") return { enabled: false, reason_code: "SCX_DRIVE_DISABLED", reason: "SCX 드라이브 기능이 꺼져 있습니다(관리자: scx_drive.enabled)" };
    if (this.mode === "down")
      return { enabled: false, reason_code: "SCX_RELAY_UNREACHABLE", reason: "대시보드에 연결할 수 없습니다(대시보드 실행 여부·relay_url 포트 확인 — 관리자)" };
    if (!this.rootsFor(pid).length) return { enabled: false, reason_code: "SCX_NO_ROOTS", reason: "이 프로젝트에 허용된 SCX 드라이브 루트가 없습니다(관리자: scx_drive.roots)" };
    return { enabled: true, reason_code: null, reason: null };
  }

  status(pid: string): ScxStatusOut {
    const down = this.mode === "down";
    return {
      fetch: this.fetchAvail(pid),
      verify: { enabled: false, reason_code: "VD_DISABLED", reason: "검증 낙하가 꺼져 있습니다(관리자: verify_drop.enabled)" },
      roots: this.fetchAvail(pid).enabled ? this.rootsFor(pid).map(({ key, label }) => ({ key, label })) : [],
      relay: {
        reachable: !down,
        drive_state: down ? null : "READY",
        queue_paused: false,
        writes_active: false,
        job_api: !down,
        max_download_bytes: down ? null : this.maxDownload,
        checked_at: this.ctx.now(),
      },
      adapters: { version: "0.1.0", commit: MOCK_SCX_COMMIT },
    };
  }

  /** 루트 기준 상대 경로 검사 → 노드 */
  private resolve(pid: string, rootKey: string, rel: string): { node: DTree | number } | MockResponse {
    const root = this.rootsFor(pid).find((r) => r.key === rootKey);
    if (!root) return err(404, "SCX_ROOT_NOT_FOUND", "SCX 드라이브 루트를 찾을 수 없습니다");
    const segs = rel ? rel.split("/") : [];
    if (/[\\~]/.test(rel) || rel.startsWith("/") || segs.some((s) => s === "" || s === "." || s === ".." || s.startsWith(".")))
      return err(422, "SCX_PATH_NOT_ALLOWED", "허용 범위 밖 경로입니다");
    let node: DTree | number = TREES[root.key];
    for (const s of segs) {
      if (typeof node === "number" || !(s in node)) return err(404, "SCX_PATH_NOT_FOUND", "드라이브에 없는 경로입니다(이동·삭제됨)");
      node = node[s];
    }
    return { node };
  }

  private display(pid: string, rootKey: string, rel: string) {
    const root = this.rootsFor(pid).find((r) => r.key === rootKey);
    return [MOCK_SCX_HOME, root?.rel ?? "", rel].filter(Boolean).join("/");
  }

  handle(method: string, path: string, query: URLSearchParams, b: Record<string, unknown>): MockResponse | null {
    if (method === "GET" && path === "/scx/status") {
      const pid = query.get("project_id") ?? "";
      return { status: 200, body: this.status(pid) };
    }
    if (method === "GET" && path === "/scx/browse") {
      const pid = query.get("project_id") ?? "";
      if (!this.ctx.canRun(pid)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const av = this.fetchAvail(pid);
      if (!av.enabled) return err(503, "SCX_UNAVAILABLE", av.reason ?? "SCX 를 쓸 수 없습니다", { reason_code: av.reason_code });
      const root = query.get("root") ?? "";
      const rel = (query.get("path") ?? "").replace(/^\/+|\/+$/g, "");
      const r = this.resolve(pid, root, rel);
      if ("status" in r) return r;
      if (typeof r.node === "number") return err(422, "SCX_PATH_NOT_ALLOWED", "폴더가 아닙니다");
      const tree = r.node;
      const all: ScxBrowseEntry[] = Object.keys(tree)
        .filter((n) => !n.startsWith("."))
        .map((name) => {
          const v = tree[name];
          const dir = typeof v !== "number";
          return { name, kind: dir ? ("dir" as const) : ("file" as const), size: dir ? null : Math.round(v as number), modified_at: dir ? null : "2026-10-28T09:12:00Z", hint: dir ? null : scxHint(name) };
        })
        .sort((x, y) => (x.kind === y.kind ? x.name.localeCompare(y.name) : x.kind === "dir" ? -1 : 1));
      const offset = Number(query.get("offset") ?? 0) || 0;
      const limit = Math.min(Number(query.get("limit") ?? this.pageSize) || this.pageSize, this.pageSize);
      const entries = all.slice(offset, offset + limit);
      return { status: 200, body: { root, path: rel, display: this.display(pid, root, rel), entries, total: all.length, truncated: offset + entries.length < all.length } };
    }
    if (method === "POST" && path === "/scx/fetches") {
      this.lastFetchIn = b;
      const pid = String(b.project_id ?? "");
      if (!this.ctx.canRun(pid)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const av = this.fetchAvail(pid);
      if (!av.enabled) return err(503, "SCX_UNAVAILABLE", av.reason ?? "SCX 를 쓸 수 없습니다", { reason_code: av.reason_code });
      const name = String(b.name ?? "");
      if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(name)) return err(422, "UPLOAD_NAME_INVALID", "이름은 영문·숫자·_·- 64자 이하입니다");
      const root = String(b.root ?? "");
      const radRel = String(b.rad_rel ?? "");
      const h3dRel = String(b.h3d_rel ?? "");
      const rr = this.resolve(pid, root, radRel);
      if ("status" in rr) return rr;
      if (typeof rr.node !== "number" || scxHint(radRel.split("/").pop()!) !== "rad") return err(422, "SCX_NOT_RAD", "starter rad(_0000.rad)가 아닙니다");
      const hr = this.resolve(pid, root, h3dRel);
      if ("status" in hr) return hr;
      if (typeof hr.node !== "number" || scxHint(h3dRel.split("/").pop()!) !== "h3d") return err(422, "SCX_NOT_H3D", "h3d 파일이 아닙니다");
      const size = Math.round(hr.node);
      if (size > this.maxDownload)
        return err(422, "SCX_FILE_TOO_LARGE", `파일이 릴레이 상한(${Math.round(this.maxDownload / GB)} GB)을 넘습니다(관리자: SIMDASH_SCX_RELAY_MAX_DOWNLOAD_BYTES)`, { size, limit: this.maxDownload });
      const p3 = this.ctx.p3;
      if (p3.openCount() >= p3.maxOpen) return err(429, "UPLOAD_LIMIT", `진행 중인 업로드가 ${p3.openCount()}개입니다(사용자당 최대 ${p3.maxOpen}개) — 끝내거나 취소한 뒤 다시 시도하세요`, { limit: p3.maxOpen });
      const need = size + Math.round(rr.node) + 200 * MB;
      if (p3.storageLeft !== null && need > p3.storageLeft)
        return err(507, "INSUFFICIENT_STORAGE", "업로드 위치의 여유 공간이 부족합니다", { need, free: p3.storageLeft, reserve: 20 * GB });
      const upload_id = p3.createScxSession(pid, name, MOCK_SCX_COMMIT);
      const job = this.ctx.newJob(pid, { upload_id, root, rad_rel: radRel, h3d_rel: h3dRel });
      this.fetches.set(upload_id, { upload_id, root, rad_rel: radRel, h3d_rel: h3dRel });
      return { status: 202, body: { upload_id, job_id: job.id } };
    }
    return null;
  }

  /** 워커 1틱(SCX_FETCH). true = 처리함(일반 진행 대신). 끝난 step 은 호출 측이 다음으로 넘긴다 */
  advance(j: JobOut & JobProgressLabel, step: StepOut): "running" | "step_done" | "failed" {
    const f = this.fetches.get(String(j.params.upload_id ?? ""));
    if (!f) return "step_done";
    const p3 = this.ctx.p3;
    const id = f.upload_id;
    const dir = f.rad_rel.split("/").slice(0, -1).join("/");
    const folder = this.resolve(p3.uploads.get(id)!.project_id, f.root, dir);
    const tree = "node" in folder && typeof folder.node !== "number" ? folder.node : {};
    if (this.failOnce && this.failOnce.step === step.step_key && (step.progress_pct ?? 0) >= 50) {
      const fo = this.failOnce;
      this.failOnce = null;
      step.state = "FAILED";
      step.failure_code = fo.code;
      j.state = "FAILED";
      j.failure_code = fo.code;
      j.failure_message = fo.message;
      j.progress_label = null;
      j.finished_at = this.ctx.now();
      this.ctx.log(j.id, `  ${step.step_key}: ${fo.code} — ${fo.message}`);
      this.ctx.log(j.id, "작업 종료: FAILED");
      return "failed";
    }
    if (step.step_key === "SF_RAD") {
      // rad + include 폐포 + 엔진 rad + 상태 파일(같은 폴더, 목은 한 번에)
      const want = Object.keys(tree).filter((n) => typeof tree[n] === "number" && ["rad", "engine", "include", "state"].includes(scxHint(n) ?? ""));
      let skipped = 0;
      for (const n of want) {
        const k = p3.scxFile(id, `rad/${n}`, Math.round(tree[n] as number));
        const cur = p3.scxFiles(id).find((x) => x.index === k)!;
        if (cur.done) skipped += 1;
        else p3.scxReceived(id, k, cur.size);
      }
      if (skipped && step.progress_pct === 0) this.ctx.log(j.id, `  SF_RAD: sha256 확인된 파일 ${skipped}개 건너뜀(이어받기)`);
      step.progress_pct = Math.min(100, (step.progress_pct ?? 0) + 50);
      j.progress_label = `rad·include ${p3.scxFiles(id).filter((x) => x.done).length}개 받음`;
      this.ctx.log(j.id, `  SF_RAD: ${step.progress_pct}% — ${j.progress_label}`);
    } else if (step.step_key === "SF_H3D") {
      const name = f.h3d_rel.split("/").pop()!;
      const hr = this.resolve(p3.uploads.get(id)!.project_id, f.root, f.h3d_rel);
      const size = "node" in hr && typeof hr.node === "number" ? Math.round(hr.node) : 0;
      const k = p3.scxFile(id, `h3d/${name}`, size);
      const cur = p3.scxFiles(id).find((x) => x.index === k)!;
      if (cur.done) step.progress_pct = 100;
      else if ((step.progress_pct ?? 0) === 0) {
        // 받다 끊긴 .part 는 덮어 새로 받는다(SR-D-7 — 바이트 이어받기 없음)
        p3.scxReceived(id, k, 0);
        step.progress_pct = 1;
        j.progress_label = "대시보드가 SCX에서 받는 중";
      } else {
        step.progress_pct = Math.min(100, (step.progress_pct === 1 ? 0 : step.progress_pct ?? 0) + this.h3dStepPct);
        p3.scxReceived(id, k, Math.round((size * step.progress_pct) / 100));
        j.progress_label = `h3d ${((size * step.progress_pct) / 100 / GB).toFixed(1)} / ${(size / GB).toFixed(1)} GB`;
      }
      this.ctx.log(j.id, `  SF_H3D: ${step.progress_pct}% — ${j.progress_label ?? ""}`);
    } else {
      step.progress_pct = 100;
      j.progress_label = null;
      // SF_REGISTER: 기존 complete 검사와 같은 함수
      p3.handle("POST", `/uploads/${id}/complete`, new URLSearchParams(), {}, 0);
      this.ctx.log(j.id, "  SF_REGISTER: 업로드 확인(inspect_upload) 완료");
    }
    // 진행 가중 10 / 85 / 5 (§8)
    const w: Record<string, number> = { SF_RAD: 10, SF_H3D: 85, SF_REGISTER: 5 };
    const steps = j.steps ?? [];
    let pct = 0;
    for (const s of steps) pct += ((s.state === "SUCCEEDED" ? 100 : s === step ? step.progress_pct ?? 0 : 0) * (w[s.step_key] ?? 0)) / 100;
    j.progress_pct = Math.round(pct);
    return (step.progress_pct ?? 0) >= 100 ? "step_done" : "running";
  }
}
