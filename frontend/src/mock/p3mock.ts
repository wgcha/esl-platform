// 목 서버 P3-UX(계약 esl_p3_ux.md §1~§3): 업로드 세션·서버 폴더 찾아보기·결과 zip·버전·업데이트 내역.
import type { BrowseEntry, BrowseRoot, ClientCodeOut, ClientTokenOut, UploadFileOut, UploadOut, UploadState } from "../api/types";
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

export const MOCK_VERSION = { version: VERSION_TXT.trim(), commit: "4d927c5", built_at: "2026-10-20T11:40:00Z" };
export const MOCK_CHANGELOG = parseChangelog(CHANGELOG_MD);

const ALLOWED_EXT = [".rad", ".inc", ".k", ".csv", ".json", ".txt", ".tcl", ".h3d"];
const RESERVED = /^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$/i;
export const MOCK_UPLOAD_ROOT = "E:\\VD_SIMULATION_WEB\\esl-input";
/** 목 rad 가 참조하는 include */
export const MOCK_INCLUDES = ["inc_mat.inc", "inc_mesh.inc"];

interface Upl {
  id: string;
  project_id: string;
  name: string;
  dir: string;
  files: UploadFileOut[];
  state: UploadState;
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
  chunkSize = 16 * 1024 ** 2;
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

    if (method === "POST" && path === "/uploads") {
      const pid = String(b.project_id ?? "");
      if (!this.ctx.canRun(pid)) return err(403, "FORBIDDEN", "이 프로젝트에서 실행 권한이 없습니다.");
      const name = String(b.name ?? "");
      if (!name.trim()) return err(422, "INVALID_NAME", "이름을 입력하세요.");
      const files = (b.files as { rel: string; size: number }[]) ?? [];
      if (!files.length) return err(422, "NO_FILES", "올릴 파일이 없습니다.");
      for (const f of files) {
        const bad = badRel(f.rel);
        if (bad) return err(422, "UPLOAD_NAME_INVALID", `${f.rel}: ${bad}`);
        if (f.size > 64 * 1024 ** 3) return err(413, "UPLOAD_TOO_LARGE", `${f.rel}: 파일당 최대 64 GB`);
      }
      const need = files.reduce((a, f) => a + f.size, 0);
      if (this.storageLeft !== null && need > this.storageLeft)
        return err(507, "INSUFFICIENT_STORAGE", "업로드 폴더 여유 공간이 부족합니다.", { need });
      this.seq += 1;
      const id = `up-${this.seq}`;
      const dir = `${MOCK_UPLOAD_ROOT}\\${this.ctx.username()}\\20261020-${String(100000 + this.seq).slice(1)}_${name.replace(/[^A-Za-z0-9_-]+/g, "_")}`;
      const u: Upl = { id, project_id: pid, name, dir, state: "OPEN", files: files.map((f, index) => ({ index, rel: f.rel, size: f.size, received: 0, done: f.size === 0 })) };
      this.uploads.set(id, u);
      return { status: 201, body: this.out(u) };
    }
    if ((r = path.match(/^\/uploads\/([^/]+)(\/files(?:\/(\d+))?|\/complete)?$/))) {
      const u = this.uploads.get(r[1]);
      if (!u) return err(404, "UPLOAD_NOT_FOUND", "업로드 세션을 찾을 수 없습니다.");
      if (method === "GET" && !r[2]) return { status: 200, body: this.out(u) };
      if (u.state !== "OPEN") return err(409, "UPLOAD_NOT_OPEN", "이미 끝났거나 취소된 업로드입니다.");
      if (method === "DELETE" && !r[2]) {
        u.state = "CANCELED";
        return { status: 200, body: this.out(u) };
      }
      if (method === "PUT" && r[3] !== undefined) {
        const f = u.files[Number(r[3])];
        if (!f) return err(404, "UPLOAD_FILE_NOT_FOUND", "업로드 파일 번호가 없습니다.");
        if (this.failPuts > 0) {
          this.failPuts -= 1;
          return err(503, "TEMPORARY", "일시 오류");
        }
        if (f.done) return err(409, "UPLOAD_FILE_DONE", "이미 다 받은 파일입니다.", { received: f.size });
        // 백엔드와 같이 offset 순서 엄격 검증(받은 크기와 같아야 함)
        const off = Number(query.get("offset"));
        if (off !== f.received) return err(409, "UPLOAD_OFFSET_MISMATCH", "offset 이 받은 크기와 다릅니다.", { received: f.received });
        if (bodySize > this.chunkSize) return err(413, "CHUNK_TOO_LARGE", "청크가 chunk_size 보다 큽니다.", { limit: this.chunkSize });
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
        f.done = f.received >= f.size;
        if (f.done) f.sha256 = "0".repeat(64);
        return { status: 200, body: { index: f.index, received: f.received, done: f.done, sha256: f.sha256 ?? null } };
      }
      if (method === "POST" && r[2] === "/files") {
        const files = (b.files as { rel: string; size: number }[]) ?? [];
        for (const f of files) {
          const bad = badRel(f.rel);
          if (bad) return err(422, "UPLOAD_NAME_INVALID", `${f.rel}: ${bad}`);
          if (u.files.some((x) => x.rel === f.rel)) return err(409, "UPLOAD_FILE_EXISTS", `이미 있는 파일입니다: ${f.rel}`);
        }
        for (const f of files) u.files.push({ index: u.files.length, rel: f.rel, size: f.size, received: 0, done: f.size === 0 });
        return { status: 200, body: this.out(u) };
      }
      if (method === "POST" && r[2] === "/complete") {
        if (u.files.some((f) => !f.done)) return err(409, "UPLOAD_INCOMPLETE", "아직 다 받지 못한 파일이 있습니다.");
        const rad = u.files.find((f) => /^rad\/.*\.rad$/i.test(f.rel));
        const names = new Set(u.files.map((f) => f.rel.split("/").pop()!.toLowerCase()));
        const missing = rad ? MOCK_INCLUDES.filter((i) => !names.has(i)).map((i) => `rad/${i}`) : [];
        const problems: string[] = [];
        if (!rad) problems.push("rad 파일(_0000.rad)이 없습니다");
        const h3d = u.files.find((f) => /^h3d\/.*\.h3d$/i.test(f.rel));
        const hasResults = u.files.some((f) => /^results\/(.*\/)?done\.json$/i.test(f.rel));
        if (!h3d && !hasResults) problems.push("h3d 파일 또는 추출 결과 폴더(done.json)가 필요합니다");
        const ok = !missing.length && !problems.length;
        if (ok) u.state = "COMPLETED";
        const resDir = u.files.find((f) => /done\.json$/i.test(f.rel))?.rel.replace(/\/?done\.json$/i, "") ?? "results";
        const win = (rel: string) => `${u.dir}\\${rel.replace(/\//g, "\\")}`;
        return {
          status: 200,
          body: {
            ok,
            upload_id: u.id,
            state: u.state,
            rad_path: rad ? win(rad.rel) : null,
            h3d_path: h3d ? win(h3d.rel) : null,
            results_dir: hasResults ? win(resDir) : null,
            parts: rad
              ? [
                  { id: 10, title: "chassis_rear", n_elems: 223415 },
                  { id: 11, title: "bumper_beam", n_elems: 18220 },
                  { id: 12, title: "crash_box_L", n_elems: 6402 },
                ]
              : [],
            missing_includes: missing,
            problems,
          },
        };
      }
    }
    return null;
  }

  private out(u: Upl): UploadOut {
    const total = u.files.reduce((a, f) => a + f.size, 0);
    return {
      upload_id: u.id,
      project_id: u.project_id,
      name: u.name,
      state: u.state,
      dir_path: u.dir,
      chunk_size: this.chunkSize,
      total_bytes: total,
      received_bytes: u.files.reduce((a, f) => a + f.received, 0),
      files: u.files.map((f) => ({ ...f })),
      result: null,
      backup_path: null,
      created_at: "2026-10-20T02:00:00Z",
      updated_at: "2026-10-20T02:00:00Z",
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
