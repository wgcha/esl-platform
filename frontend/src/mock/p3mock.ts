// 목 서버 P3-UX(계약 esl_p3_ux.md §1~§3): 업로드 세션·서버 폴더 찾아보기·결과 zip·버전·업데이트 내역.
import type { BrowseEntry, BrowseRoot, ClientCodeOut, ClientTokenOut, H3dMeta, UploadCheckOut, UploadFileOut, UploadOut, UploadState } from "../api/types";
import { parseChangelog } from "../lib/changelog";
import CHANGELOG_MD from "../../../CHANGELOG.md?raw";
import VERSION_TXT from "../../../VERSION?raw";

interface MockResponse {
  status: number;
  body?: unknown;
}
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResponse => ({
  status,
  body: { detail: { code, message, ...extra } },
});

export const MOCK_VERSION = { version: VERSION_TXT.trim(), commit: "4d927c5", built_at: "2026-10-20T11:40:00Z", ui: { upload_slim_hint_gb: 5 } };
export const MOCK_CHANGELOG = parseChangelog(CHANGELOG_MD);

const ALLOWED_EXT = [".rad", ".inc", ".k", ".csv", ".json", ".txt", ".tcl", ".h3d"];
const RESERVED = /^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$/i;
export const MOCK_UPLOAD_ROOT = "E:\\VD_SIMULATION_WEB\\esl-input";
/** 목 rad 가 참조하는 include */
export const MOCK_INCLUDES = ["inc_mat.inc", "inc_mesh.inc"];

interface MFile extends UploadFileOut {
  /** 받은 청크 번호(프로토콜 2) */
  got: Set<number>;
  removed: boolean;
  meta: H3dMeta | null;
}
interface Upl {
  id: string;
  project_id: string;
  name: string;
  dir: string;
  files: MFile[];
  state: UploadState;
  /** 프로토콜 2 세션(만들 때의 서버 protocol) */
  proto: 1 | 2;
  chunk: number;
  result: UploadCheckOut | null;
  /** 이 업로드로 만든 Case 가 있음(빼기 409 UPLOAD_IN_USE) */
  inUse: boolean;
  created_at: string;
  /** POST /uploads client(esl-web·esl-pc) — 없으면 null */
  client: { name: string; version: string } | null;
}

export function badRel(rel: string): string | null {
  if (!/^(rad|h3d|results)\//.test(rel)) return "rad/·h3d/·results/ 아래 상대경로만 허용합니다";
  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x1f\\:]/.test(rel) || rel.startsWith("/")) return "허용되지 않는 문자가 있습니다";
  const segs = rel.split("/");
  if (segs.some((s) => s === "" || s === "." || s === ".." || RESERVED.test(s))) return "허용되지 않는 이름입니다";
  const ext = rel.slice(rel.lastIndexOf(".")).toLowerCase();
  if (!ALLOWED_EXT.includes(ext)) return `허용되지 않는 확장자입니다(${ext})`;
  return null;
}

// ---------------------------------------------------------------- 서버 폴더 트리
type Tree = { [name: string]: Tree | number };
const RESULTS: Tree = { "done.json": 812, "frames.csv": 4_210, "model.csv": 9_120_331, "final.csv": 3_201_778, "history.csv": 88_120, "disp.csv": 412_998_120, "strain_frames.csv": 1_288_120_331 };
const SCENE = (h3d: number): Tree => ({ "model_0000.rad": 182_331_200, "inc_mat.inc": 61_220, "inc_mesh.inc": 140_220_111, h3d_csv: { ...RESULTS }, "chassis_rear.h3d": h3d });
/** §6: 서버 입력은 업로드 폴더(storage.upload_root) 안만. SPDM 은 browse_spdm 기본 false 라 보이지 않음 */
const ROOTS: { root: BrowseRoot; tree: Tree }[] = [
  {
    root: { index: 0, label: "업로드 폴더", path: MOCK_UPLOAD_ROOT, kind: "upload", writable: true },
    tree: {
      kim: {
        "20261019-031200_QN80H_rear40": { rad: { "model_0000.rad": 182_331_200, "inc_mat.inc": 61_220, "inc_mesh.inc": 140_220_111 }, h3d: { "chassis_rear.h3d": 6_812_331_000 } },
        "20261018-091500_QN90D_edgeB": { rad: { "model_0000.rad": 171_002_110, "inc_mat.inc": 61_220, "inc_mesh.inc": 133_001_200 }, results: { ...RESULTS } },
      },
      shared: { QN80H_75: { corner_drop_LT: SCENE(7_120_000_000) } },
      "readme.txt": 1_024,
    },
  },
];

function hintOf(name: string, node: Tree | number): BrowseEntry["hint"] {
  if (typeof node === "number") return /\.rad$/i.test(name) ? "rad" : /\.h3d$/i.test(name) ? "h3d" : null;
  return "done.json" in node ? "results" : null;
}

export class P3Mock {
  uploads = new Map<string, Upl>();
  seq = 0;
  chunkSize = 64 * 1024 ** 2;
  /** 서버 업로드 프로토콜: 2 = 병렬(기본), 1 = 구 서버(protocol 필드 없음·순차 전용) */
  protocol: 1 | 2 = 2;
  maxParallel = 4;
  /** 사용자당 열린(OPEN) 업로드 한도 */
  maxOpen = 2;
  /** 다음 n 번 청크 PUT 을 429(Retry-After 1초)로 */
  tooManyPuts = 0;
  /** 이 index 파일을 빼려 하면 409 UPLOAD_FILE_BUSY (시험) */
  busyFiles = new Set<number>();
  /** PUT 순서 기록 "index:k" */
  putLog: string[] = [];
  /** 빼기 DELETE 기록 "upload:index" */
  removedLog: string[] = [];
  /** 다음 n 번 청크 PUT 을 503 으로 실패(재시도 시험) */
  failPuts = 0;
  /** 이 수만큼 청크를 받은 뒤 PUT 응답을 멈춤(스크린샷 "진행 중") */
  hangAfter: number | null = null;
  putCount = 0;
  /** 청크 PUT 응답 지연(ms, 시연용 속도·남은 시간 표시) */
  putDelayMs = 0;
  /** 결과 zip 이 한도를 넘는 Case */
  bigBundle = new Set<string>(["c-stale"]);
  browsePageSize = 200;
  /** 남은 저장 공간(바이트). null = 무제한. 넘으면 507 */
  storageLeft: number | null = null;
  /** 마지막 청크 X-Chunk-Sha256 헤더(시험용) */
  chunkShas: (string | null)[] = [];
  /** 다음 n 번 청크를 CHUNK_SHA256_MISMATCH(422)로 거부(재전송 시험) */
  badShaPuts = 0;

  /** §9.1 PC 연결: 발급한 코드(1회용)·토큰 */
  codes: (ClientCodeOut & { user_id: string; used: boolean })[] = [];
  tokens: ClientTokenOut[] = [];
  /** 지금 시각(코드 만료 계산). 시험에서 바꿀 수 있음 */
  clock: () => number = () => Date.now();

  constructor(
    private ctx: {
      canRun: (pid: string) => boolean;
      username: () => string;
      userId: () => string;
      projectName: (pid: string) => string | null;
      casePath: (id: string) => string | null;
    },
  ) {}

  /** 시연·시험용: 연결된 PC 하나 추가(PC 도구가 코드를 교환한 것과 같음) */
  addToken(projectId: string, device: string, state: ClientTokenOut["state"] = "ACTIVE"): ClientTokenOut {
    this.seq += 1;
    const t: ClientTokenOut = {
      id: `ct-${this.seq}`,
      token_prefix: `esl_ct_${String(this.seq).padStart(5, "x")}`,
      project_id: projectId,
      project_name: this.ctx.projectName(projectId),
      device_name: device,
      user_id: this.ctx.userId(),
      username: this.ctx.username(),
      created_at: "2026-10-18T03:10:00Z",
      expires_at: state === "EXPIRED" ? "2026-10-01T03:10:00Z" : "2026-11-17T03:10:00Z",
      last_used_at: state === "ACTIVE" ? "2026-10-20T01:12:00Z" : null,
      revoked_at: state === "REVOKED" ? "2026-10-19T08:00:00Z" : null,
      state,
    };
    this.tokens.unshift(t);
    return t;
  }

  private clientTokens(method: string, path: string, query: URLSearchParams, b: Record<string, unknown>): MockResponse | null {
    let r: RegExpMatchArray | null;
    if (method === "POST" && path === "/client-tokens/codes") {
      const pid = String(b.project_id ?? "");
      if (!this.ctx.canRun(pid)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한(power 이상)이 없습니다.");
      const code = String(100000 + ((this.codes.length * 271_829 + 482_113) % 900_000)).slice(0, 6);
      const out: ClientCodeOut = { code, project_id: pid, expires_at: new Date(this.clock() + 15 * 60_000).toISOString() };
      this.codes.push({ ...out, user_id: this.ctx.userId(), used: false });
      return { status: 201, body: out };
    }
    if (method === "GET" && path === "/client-tokens") {
      const pid = query.get("project_id");
      const mine = this.tokens.filter((t) => t.user_id === this.ctx.userId() && (!pid || t.project_id === pid));
      return { status: 200, body: mine.map((t) => ({ ...t })) };
    }
    if (method === "DELETE" && (r = path.match(/^\/client-tokens\/([^/]+)$/))) {
      const t = this.tokens.find((x) => x.id === r![1]);
      if (!t || t.user_id !== this.ctx.userId()) return err(404, "CLIENT_TOKEN_NOT_FOUND", "연결된 PC 토큰을 찾을 수 없습니다");
      if (!t.revoked_at) {
        t.revoked_at = new Date(this.clock()).toISOString();
        t.state = "REVOKED";
      }
      return { status: 200, body: { ...t } };
    }
    return null;
  }

  shouldHang(method: string, path: string) {
    return method === "PUT" && /^\/uploads\//.test(path) && this.hangAfter !== null && this.putCount >= this.hangAfter;
  }

  handle(method: string, path: string, query: URLSearchParams, b: Record<string, unknown>, bodySize: number): MockResponse | null {
    let r: RegExpMatchArray | null;
    if (method === "GET" && path === "/version") return { status: 200, body: MOCK_VERSION };
    if (method === "GET" && path === "/changelog") return { status: 200, body: MOCK_CHANGELOG };
    if (method === "GET" && path === "/fs/browse") return this.browse(query);
    if (path.startsWith("/client-tokens")) {
      const ct = this.clientTokens(method, path, query, b);
      if (ct) return ct;
    }
    if ((r = path.match(/^\/cases\/([^/]+)\/bundle$/)) && method === "GET") {
      const p = this.ctx.casePath(r[1]);
      if (!p) return err(404, "CASE_NOT_FOUND", "Case를 찾을 수 없습니다.");
      if (r[1] === "c-new") return err(404, "BUNDLE_EMPTY", "받을 파일이 없습니다.");
      if (this.bigBundle.has(r[1]))
        return err(413, "BUNDLE_TOO_LARGE", "결과가 커서 zip 으로 받을 수 없습니다. 폴더 경로를 복사해 여세요", { path: p, size: 7.2 * 1024 ** 3, limit: 5 * 1024 ** 3 });
      return { status: 200, body: "PK mock zip\n" };
    }
    if ((r = path.match(/^\/library\/analyses\/([^/]+)\/bundle$/)) && method === "GET") {
      if (!query.get("parts")) return err(422, "PARTS_REQUIRED", "parts 가 필요합니다(목 서버 검사).");
      return { status: 200, body: "PK mock zip\n" };
    }

    if (method === "GET" && path === "/uploads") {
      const st = query.get("state");
      const mine = [...this.uploads.values()].filter((u) => !st || u.state === st).reverse();
      return { status: 200, body: mine.map((u) => this.out(u)) };
    }
    if (method === "POST" && path === "/uploads") {
      const pid = String(b.project_id ?? "");
      if (!this.ctx.canRun(pid)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const name = String(b.name ?? "");
      if (!name.trim()) return err(422, "INVALID_NAME", "이름을 입력하세요.");
      const files = (b.files as { rel: string; size: number; meta?: H3dMeta | null }[]) ?? [];
      if (!files.length) return err(422, "NO_FILES", "올릴 파일이 없습니다.");
      for (const f of files) {
        const bad = badRel(f.rel);
        if (bad) return err(422, "UPLOAD_NAME_INVALID", `${f.rel}: ${bad}`);
        if (f.size > 64 * 1024 ** 3) return err(413, "UPLOAD_TOO_LARGE", `${f.rel}: 파일당 최대 64 GB`);
      }
      const open = [...this.uploads.values()].filter((u) => u.state === "OPEN");
      if (open.length >= this.maxOpen)
        return err(429, "UPLOAD_LIMIT", `진행 중인 업로드가 ${open.length}개입니다(사용자당 최대 ${this.maxOpen}개) — 끝내거나 취소한 뒤 다시 시도하세요`, {
          limit: this.maxOpen,
          open_uploads: open.map((u) => {
            const o = this.out(u);
            return { id: u.id, name: u.name, created_at: u.created_at, received_bytes: o.received_bytes, total_bytes: o.total_bytes, problems_count: o.problems_count ?? 0 };
          }),
        });
      const need = files.reduce((a, f) => a + f.size, 0);
      if (this.storageLeft !== null && need > this.storageLeft)
        return err(507, "INSUFFICIENT_STORAGE", "업로드 폴더 여유 공간이 부족합니다.", { need });
      this.seq += 1;
      const id = `up-${this.seq}`;
      const dir = `${MOCK_UPLOAD_ROOT}\\${this.ctx.username()}\\20261020-${String(100000 + this.seq).slice(1)}_${name.replace(/[^A-Za-z0-9_-]+/g, "_")}`;
      const u: Upl = {
        id,
        project_id: pid,
        name,
        dir,
        state: "OPEN",
        proto: this.protocol,
        chunk: this.protocol === 2 ? this.chunkSize : Math.min(this.chunkSize, 16 * 1024 ** 2),
        result: null,
        inUse: false,
        created_at: new Date(this.clock()).toISOString(),
        client: (b.client as { name: string; version: string } | null | undefined) ?? null,
        files: files.map((f, index) => this.mfile(index, f)),
      };
      this.uploads.set(id, u);
      return { status: 201, body: this.out(u) };
    }
    if ((r = path.match(/^\/uploads\/([^/]+)(\/files(?:\/(\d+))?|\/complete)?$/))) {
      const u = this.uploads.get(r[1]);
      if (!u) return err(404, "UPLOAD_NOT_FOUND", "업로드 세션을 찾을 수 없습니다.");
      if (method === "GET" && !r[2]) return { status: 200, body: this.out(u) };
      // 프로토콜 2: 파일 빼기(COMPLETED 도 가능 — Case 가 쓰지 않으면 OPEN 으로 돌아감)
      if (method === "DELETE" && r[3] !== undefined) {
        if (u.proto !== 2) return err(405, "METHOD_NOT_ALLOWED", "이 서버는 파일을 하나씩 뺄 수 없습니다.");
        const f = u.files[Number(r[3])];
        if (!f) return err(404, "UPLOAD_FILE_NOT_FOUND", "업로드 파일 번호가 없습니다.");
        if (u.state === "CANCELED" || u.state === "STALE") return err(409, "UPLOAD_CLOSED", "이미 닫힌 업로드입니다.");
        if (f.removed) return { status: 200, body: this.out(u) };
        if (this.busyFiles.has(f.index)) return err(409, "UPLOAD_FILE_BUSY", "그 파일의 청크를 쓰는 중입니다.");
        if (u.state === "COMPLETED") {
          if (u.inUse) return err(409, "UPLOAD_IN_USE", "이 업로드로 만든 Case가 있어 뺄 수 없습니다.");
          u.state = "OPEN";
          u.result = null;
        }
        f.removed = true;
        this.removedLog.push(`${u.id}:${f.index}`);
        return { status: 200, body: this.out(u) };
      }
      if (method === "DELETE" && !r[2]) {
        if (u.state === "COMPLETED") return err(409, "UPLOAD_COMPLETED", "이미 확인을 마친 업로드는 취소할 수 없습니다.");
        if (u.state !== "OPEN") return err(409, "UPLOAD_NOT_OPEN", "이미 끝났거나 취소된 업로드입니다.");
        u.state = "CANCELED";
        return { status: 200, body: this.out(u) };
      }
      if (u.state !== "OPEN") return err(409, "UPLOAD_NOT_OPEN", "이미 끝났거나 취소된 업로드입니다.");
      if (method === "PUT" && r[3] !== undefined) {
        const f = u.files[Number(r[3])];
        if (!f) return err(404, "UPLOAD_FILE_NOT_FOUND", "업로드 파일 번호가 없습니다.");
        if (this.failPuts > 0) {
          this.failPuts -= 1;
          return err(503, "TEMPORARY", "일시 오류");
        }
        if (this.tooManyPuts > 0) {
          this.tooManyPuts -= 1;
          return err(429, "UPLOAD_PARALLEL_LIMIT", "동시 전송 한도를 넘었습니다.", { retry_after: 1 });
        }
        if (f.removed) return err(409, "UPLOAD_FILE_REMOVED", "목록에서 뺀 파일입니다.");
        if (f.done) return err(409, "UPLOAD_FILE_DONE", "이미 다 받은 파일입니다.", { received: f.size });
        const off = Number(query.get("offset"));
        if (u.proto === 2) {
          const C = u.chunk;
          const n = Math.ceil(f.size / C);
          const k = off / C;
          if (off % C !== 0 || k >= n) return err(409, "UPLOAD_OFFSET_MISMATCH", "offset 이 청크 경계가 아닙니다.", { received: f.received });
          const want = Math.min(C, f.size - off);
          if (bodySize !== want) return err(422, "CHUNK_LENGTH_MISMATCH", "청크 길이가 맞지 않습니다.", { expected: want });
          if (this.badShaPuts > 0) {
            this.badShaPuts -= 1;
            return err(422, "CHUNK_SHA256_MISMATCH", "청크 sha256 이 다릅니다(쓰지 않음).", { received: f.received });
          }
          if (f.got.has(k)) return { status: 200, body: { index: f.index, received: f.received, received_total: f.received_total, chunk: k, duplicate: true, done: f.done, sha256: null } };
          if (this.storageLeft !== null) {
            if (bodySize > this.storageLeft) return err(507, "INSUFFICIENT_STORAGE", "서버 저장 공간이 부족합니다.");
            this.storageLeft -= bodySize;
          }
          this.putCount += 1;
          this.putLog.push(`${f.index}:${k}`);
          f.got.add(k);
          this.sync(f, C);
          return { status: 200, body: { index: f.index, received: f.received, received_total: f.received_total, chunk: k, duplicate: false, done: f.done, sha256: f.sha256 ?? null } };
        }
        // 프로토콜 1: 백엔드와 같이 offset 순서 엄격 검증(받은 크기와 같아야 함)
        if (off !== f.received) return err(409, "UPLOAD_OFFSET_MISMATCH", "offset 이 받은 크기와 다릅니다.", { received: f.received });
        if (bodySize > u.chunk) return err(413, "CHUNK_TOO_LARGE", "청크가 chunk_size 보다 큽니다.", { limit: u.chunk });
        if (off + bodySize > f.size) return err(422, "CHUNK_OVERFLOW", "선언한 파일 크기를 넘는 청크입니다.", { received: f.received });
        if (this.badShaPuts > 0) {
          this.badShaPuts -= 1;
          return err(422, "CHUNK_SHA256_MISMATCH", "청크 sha256 이 다릅니다(쓰지 않음).", { received: f.received });
        }
        if (this.storageLeft !== null) {
          if (bodySize > this.storageLeft) return err(507, "INSUFFICIENT_STORAGE", "서버 저장 공간이 부족합니다.");
          this.storageLeft -= bodySize;
        }
        this.putCount += 1;
        f.received += bodySize;
        f.received_total = f.received;
        f.done = f.received >= f.size;
        if (f.done) f.sha256 = "0".repeat(64);
        return { status: 200, body: { index: f.index, received: f.received, done: f.done, sha256: f.sha256 ?? null } };
      }
      if (method === "POST" && r[2] === "/files") {
        const files = (b.files as { rel: string; size: number; meta?: H3dMeta | null }[]) ?? [];
        for (const f of files) {
          const bad = badRel(f.rel);
          if (bad) return err(422, "UPLOAD_NAME_INVALID", `${f.rel}: ${bad}`);
          // 제거된 항목의 rel 은 중복 검사에서 제외(같은 이름으로 다시 추가 가능)
          if (u.files.some((x) => x.rel === f.rel && !x.removed)) return err(409, "UPLOAD_FILE_EXISTS", `이미 있는 파일입니다: ${f.rel}`);
        }
        for (const f of files) u.files.push(this.mfile(u.files.length, f));
        return { status: 200, body: this.out(u) };
      }
      if (method === "POST" && r[2] === "/complete") {
        const live = u.files.filter((f) => !f.removed);
        const pending = live.filter((f) => !f.done);
        if (pending.length)
          return err(409, "UPLOAD_INCOMPLETE", "아직 다 받지 못한 파일이 있습니다.", {
            pending: pending.map((f) => ({ index: f.index, rel: f.rel, missing: [[Math.floor(f.received / u.chunk), Math.ceil(f.size / u.chunk)]] })),
          });
        const rad = live.find((f) => /^rad\/.*\.rad$/i.test(f.rel));
        const names = new Set(live.map((f) => f.rel.split("/").pop()!.toLowerCase()));
        const missing = rad ? MOCK_INCLUDES.filter((i) => !names.has(i)).map((i) => `rad/${i}`) : [];
        const problems: string[] = [];
        if (!rad) problems.push("rad 파일(_0000.rad)이 없습니다");
        const h3d = live.find((f) => /^h3d\/.*\.h3d$/i.test(f.rel));
        const hasResults = live.some((f) => /^results\/(.*\/)?done\.json$/i.test(f.rel));
        if (!h3d && !hasResults) problems.push("h3d 파일 또는 추출 결과 폴더(done.json)가 필요합니다");
        const ok = !missing.length && !problems.length;
        const resDir = live.find((f) => /done\.json$/i.test(f.rel))?.rel.replace(/\/?done\.json$/i, "") ?? "results";
        const win = (rel: string) => `${u.dir}\\${rel.replace(/\//g, "\\")}`;
        const res: UploadCheckOut = {
          ok,
          rad_path: rad ? win(rad.rel) : null,
          h3d_path: h3d ? win(h3d.rel) : null,
          results_dir: hasResults ? win(resDir) : null,
          h3d_meta: h3d?.meta ?? null,
          parts: rad
            ? [
                { id: 10, title: "chassis_rear", n_elems: 223415 },
                { id: 11, title: "bumper_beam", n_elems: 18220 },
                { id: 12, title: "crash_box_L", n_elems: 6402 },
              ]
            : [],
          missing_includes: missing,
          problems,
        };
        if (ok) {
          u.state = "COMPLETED";
          u.result = res;
        } else {
          u.result = res;
        }
        return { status: 200, body: { ...res, upload_id: u.id, state: u.state } };
      }
    }
    return null;
  }

  private mfile(index: number, f: { rel: string; size: number; meta?: H3dMeta | null }): MFile {
    return { index, rel: f.rel, size: f.size, received: 0, received_total: 0, done: f.size === 0, got: new Set(), removed: false, meta: f.meta ?? null };
  }

  /** 받은 청크 집합 → 연속 앞부분·합계·완료 */
  private sync(f: MFile, C: number) {
    const n = Math.ceil(f.size / C);
    let lead = 0;
    while (f.got.has(lead)) lead += 1;
    f.received = Math.min(f.size, lead * C);
    f.received_total = [...f.got].reduce((a, k) => a + Math.min(C, f.size - k * C), 0);
    f.done = f.got.size >= n;
    if (f.done) f.sha256 = "0".repeat(64);
  }

  /** Case 입력 h3d 경로 → 그 업로드의 h3d 메타(§6.5 input_h3d_meta) */
  metaForPath(h3dPath: string | null): H3dMeta | null {
    if (!h3dPath) return null;
    for (const u of this.uploads.values()) if (u.state === "COMPLETED" && u.result?.h3d_path === h3dPath) return u.result.h3d_meta ?? null;
    return null;
  }

  /** Case 가 이 업로드를 입력으로 쓰기 시작 → 파일 빼기 409 UPLOAD_IN_USE */
  markInUse(h3dPath: string | null) {
    if (!h3dPath) return;
    for (const u of this.uploads.values()) if (u.state === "COMPLETED" && u.result?.h3d_path === h3dPath) u.inUse = true;
  }

  /** 시험·시연: 열린 업로드 하나를 바로 만든다(받은 양 지정, 청크 단위로 내림) */
  seedUpload(projectId: string, name: string, files: { rel: string; size: number; received?: number }[], opts: { problems?: string[]; ageMin?: number; client?: string } = {}): string {
    this.seq += 1;
    const id = `up-${this.seq}`;
    const C = this.chunkSize;
    const u: Upl = {
      id,
      project_id: projectId,
      name,
      dir: `${MOCK_UPLOAD_ROOT}\\${this.ctx.username()}\\20261020-${String(100000 + this.seq).slice(1)}_${name}`,
      state: "OPEN",
      proto: this.protocol,
      chunk: C,
      result: opts.problems ? { ok: false, problems: opts.problems } : null,
      inUse: false,
      created_at: new Date(this.clock() - (opts.ageMin ?? 90) * 60_000).toISOString(),
      client: opts.client ? { name: opts.client, version: "0.6.0" } : null,
      files: files.map((f, i) => {
        const m = this.mfile(i, f);
        const rec = f.received ?? 0;
        const n = Math.ceil(f.size / C);
        for (let k = 0; k < n; k++) if (rec >= f.size || (k + 1) * C <= rec) m.got.add(k);
        this.sync(m, C);
        return m;
      }),
    };
    this.uploads.set(id, u);
    return id;
  }

  private out(u: Upl): UploadOut {
    const live = u.files.filter((f) => !f.removed);
    const v2 = u.proto === 2;
    return {
      upload_id: u.id,
      project_id: u.project_id,
      name: u.name,
      state: u.state,
      dir_path: u.dir,
      chunk_size: u.chunk,
      total_bytes: live.reduce((a, f) => a + f.size, 0),
      received_bytes: live.reduce((a, f) => a + (v2 ? f.received_total! : f.received), 0),
      ...(v2 ? { protocol: 2 as const, max_parallel: this.maxParallel } : {}),
      problems_count: (u.result?.problems?.length ?? 0) + (u.result?.missing_includes?.length ?? 0),
      client: u.client,
      files: u.files.map((f) => {
        const { got, ...rest } = f;
        if (!v2) return { index: rest.index, rel: rest.rel, size: rest.size, received: rest.received, done: rest.done, sha256: rest.sha256 };
        const chunks: [number, number][] = [];
        for (const k of [...got].sort((a, b) => a - b)) {
          const last = chunks[chunks.length - 1];
          if (last && last[1] === k) last[1] = k + 1;
          else chunks.push([k, k + 1]);
        }
        return { ...rest, chunks, n_chunks: Math.ceil(f.size / u.chunk) };
      }),
      result: u.result,
      backup_path: null,
      created_at: u.created_at,
      updated_at: u.created_at,
      completed_at: null,
    };
  }

  private browse(query: URLSearchParams): MockResponse {
    const idx = Number(query.get("root") ?? 0);
    const root = ROOTS.find((x) => x.root.index === idx);
    if (!root) return err(404, "ROOT_NOT_FOUND", "루트가 없습니다.");
    const rel = (query.get("path") ?? "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    let node: Tree | number = root.tree;
    for (const seg of rel ? rel.split("/") : []) {
      if (seg === ".." || typeof node === "number" || !(seg in node)) return err(422, "PATH_OUTSIDE_ROOT", "허용된 폴더 밖이거나 없는 경로입니다.");
      node = (node as Tree)[seg];
    }
    if (typeof node === "number") return err(422, "NOT_A_DIR", "폴더가 아닙니다.");
    const all: BrowseEntry[] = Object.entries(node)
      .map(([name, v]) => ({ name, type: typeof v === "number" ? ("file" as const) : ("dir" as const), size: typeof v === "number" ? v : null, mtime: 1760900000, hint: hintOf(name, v) }))
      .sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === "dir" ? -1 : 1));
    const offset = Number(query.get("offset") ?? 0);
    const page = all.slice(offset, offset + this.browsePageSize);
    const parent = rel ? rel.split("/").slice(0, -1).join("/") : null;
    return {
      status: 200,
      body: {
        roots: ROOTS.map((x) => x.root),
        root: idx,
        path: rel,
        abs_path: [root.root.path, ...(rel ? rel.split("/") : [])].join("\\"),
        parent,
        hint: "done.json" in node ? "results" : null,
        entries: page,
        total: all.length,
        offset,
        limit: this.browsePageSize,
        truncated: offset + page.length < all.length,
      },
    };
  }
}
