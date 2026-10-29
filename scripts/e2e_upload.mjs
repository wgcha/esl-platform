#!/usr/bin/env node
// v0.6.0 업로드 속도 실서버 E2E(계약 esl_upload_speed.md): 임시 PostgreSQL + uvicorn(backend, 실제 업로드 프로토콜 2) +
// 빌드된 프런트(/esl/ 하위 경로 정적 서빙, /esl/api/* → backend 프록시)를 띄우고 Playwright(Chromium, 2560×1440)로
//   1) 1 GB 합성 h3d + rad 병렬 업로드 → complete(COMPLETED·서버 파일 크기·sha256 = 로컬) — 진행 중 목록·상단 칩 스크린샷
//   2) 두 번째 업로드: 멈춤 → h3d 하나 지우기(DELETE /uploads/{id}/files/{i} → removed) → 전체 지우기 = 세션 취소(CANCELED)
//   3) 열린 업로드 2개에서 새 업로드 → UPLOAD_LIMIT: detail.open_uploads(서버 키) + '진행 중인 업로드' 목록 자동 펼침
// 를 확인한다. mock 아님. 인증 dev_static.
//
// 사용: node scripts/e2e_upload.mjs [스크린샷 폴더]   (먼저 cd frontend && npm run build)
// env: PG_BIN, PYTHON(기본 python3), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers), PLAYWRIGHT_MODULE,
//      ESL_E2E_BIG_MB(기본 1024), ESL_E2E_KEEP=1 이면 임시 폴더를 남김.
import { spawn, spawnSync, execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP_VERSION = fs.readFileSync(path.join(REPO, "VERSION"), "utf8").trim();   // 하드코딩 대신 VERSION 파일
const DIST = path.join(REPO, "frontend", "dist");
const PY = process.env.PYTHON || "python3";
const SHOTS = path.resolve(process.argv[2] || path.join(REPO, "work", "upload_live"));
const BIG_MB = Number(process.env.ESL_E2E_BIG_MB || 1024);
process.env.PLAYWRIGHT_BROWSERS_PATH ||= "/opt/pw-browsers";

const procs = [];
let tmp = null;
let pg = null;
const t0 = Date.now();
const log = (...a) => console.log(`[e2e-upload ${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function check(cond, msg) {
  if (!cond) throw new Error(msg);
}

function loadPlaywright() {
  const require = createRequire(import.meta.url);
  const cands = [process.env.PLAYWRIGHT_MODULE, "playwright"].filter(Boolean);
  try {
    cands.push(path.join(execSync("npm root -g").toString().trim(), "playwright"));
  } catch {
    /* 무시 */
  }
  for (const c of cands) {
    try {
      return require(c);
    } catch {
      /* 다음 */
    }
  }
  throw new Error("playwright 모듈을 찾을 수 없습니다(PLAYWRIGHT_MODULE 로 지정)");
}

const freePort = () =>
  new Promise((res, rej) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => res(p));
    });
    s.on("error", rej);
  });

const isRoot = typeof process.getuid === "function" && process.getuid() === 0;
function asPg(argv) {
  const cmd = isRoot ? ["runuser", "-u", "postgres", "--", ...argv] : argv;
  const r = spawnSync(cmd[0], cmd.slice(1), { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`실패: ${argv.join(" ")}\n${r.stdout}\n${r.stderr}`);
}
function pgBin() {
  if (process.env.PG_BIN) return process.env.PG_BIN;
  const base = "/usr/lib/postgresql";
  const vers = fs.existsSync(base) ? fs.readdirSync(base).sort((a, b) => Number(b) - Number(a)) : [];
  for (const v of vers) if (fs.existsSync(path.join(base, v, "bin", "initdb"))) return path.join(base, v, "bin");
  throw new Error("PostgreSQL(initdb)을 찾을 수 없습니다: PG_BIN 지정");
}
function startProc(name, cmd, args, env) {
  const out = fs.openSync(path.join(tmp, `${name}.log`), "a");
  const p = spawn(cmd, args, { cwd: REPO, env: { ...process.env, ...env }, stdio: ["ignore", out, out] });
  p.on("exit", (code, sig) => {
    if (!p.__stopping) log(`${name} 종료 code=${code} sig=${sig}`);
  });
  procs.push({ name, p });
  return p;
}
async function waitHttp(url, ms = 30000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      const r = await fetch(url);
      if (r.status < 500) return;
    } catch {
      /* 대기 */
    }
    await sleep(250);
  }
  throw new Error(`응답 없음: ${url}`);
}

/** 청크 PUT 관측(동시 수) + 스크린샷 구간에서만 지연(진행 중 화면을 잡기 위해 — 본문·서버 처리는 그대로) */
const puts = { n: 0, inflight: 0, maxInflight: 0, delayMs: 0 };
const PUT_RE = /^\/esl\/api\/uploads\/[^/]+\/files\/\d+$/;

/** /esl/api/* → backend 프록시(본문 스트리밍), /esl/* → dist(index.html fallback) */
function startFront(port, apiPort) {
  const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json" };
  const srv = http.createServer((req, res) => {
    const u = new URL(req.url, "http://x");
    if (u.pathname.startsWith("/esl/api/") || u.pathname === "/esl/api") {
      const isPut = req.method === "PUT" && PUT_RE.test(u.pathname);
      if (isPut) {
        puts.n += 1;
        puts.inflight += 1;
        puts.maxInflight = Math.max(puts.maxInflight, puts.inflight);
        res.on("close", () => (puts.inflight -= 1));
        if (puts.delayMs) req.pause();
      }
      const go = () => {
      const pr = http.request({ host: "127.0.0.1", port: apiPort, path: req.url, method: req.method, headers: req.headers }, (r2) => {
        res.writeHead(r2.statusCode, r2.headers);
        r2.pipe(res);
      });
      pr.on("error", () => {
        res.writeHead(502);
        res.end("bad gateway");
      });
      req.pipe(pr);
      req.resume();
      };
      if (isPut && puts.delayMs) setTimeout(go, puts.delayMs);
      else go();
      return;
    }
    if (u.pathname === "/" || u.pathname === "/esl") {
      res.writeHead(302, { Location: "/esl/" });
      res.end();
      return;
    }
    if (!u.pathname.startsWith("/esl/")) {
      res.writeHead(404);
      res.end("not found");
      return;
    }
    const rel = decodeURIComponent(u.pathname.slice("/esl/".length));
    let f = path.resolve(DIST, rel);
    if (!f.startsWith(DIST) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) f = path.join(DIST, "index.html");
    res.writeHead(200, { "Content-Type": types[path.extname(f)] ?? "application/octet-stream" });
    fs.createReadStream(f).pipe(res);
  });
  return new Promise((r) => srv.listen(port, "127.0.0.1", () => r(srv)));
}

/** 플랫폼 설정(dev_static·upload_root) + 합성 입력 파일(rad·include·h3d) + DB migration */
function setupInputs(dbUrl) {
  const code = `
import json, os, sys, yaml
sys.path[:0] = [${JSON.stringify(path.join(REPO, "backend", "tests"))}]
from test_p3_ux import mini_rad_text
tmp = ${JSON.stringify(tmp)}
files = os.path.join(tmp, "files"); root = os.path.join(tmp, "esl_root"); inputs = os.path.join(tmp, "inputs")
for d in (files, root, inputs): os.makedirs(d, exist_ok=True)
open(os.path.join(files, "drop_0000.rad"), "wb").write(mini_rad_text())
open(os.path.join(files, "extra.inc"), "wb").write(b"# include\\n")
def h3d(name, mb):
    p = os.path.join(files, name)
    with open(p, "wb") as f:
        f.write(b"HYPER3D " + os.urandom(1024 * 1024))       # 헤더 + 앞 1 MB 난수, 나머지는 0(희소 파일)
        f.truncate(mb * 1024 * 1024)
    return p
big = h3d("drop_0001.h3d", ${BIG_MB}); mid = h3d("mid_0001.h3d", 256)
core = yaml.safe_load(open(${JSON.stringify(path.join(REPO, "config", "esl.example.yaml"))}, encoding="utf-8"))
d = yaml.safe_load(open(${JSON.stringify(path.join(REPO, "config", "esl_platform.example.yaml"))}, encoding="utf-8"))
d["profile"] = "dev"
d["auth"]["mode"] = "dev_static"
d["library"]["config_path"] = ${JSON.stringify(path.join(REPO, "config", "library.example.yaml"))}
d["storage"] = {"esl_root": root, "input_roots": [inputs], "spdm_roots": [], "upload_root": os.path.join(tmp, "esl-input")}
d["upload"].update({"min_free_gb": 0})
d["core"] = {"settings": core}
p = os.path.join(tmp, "esl_platform.yaml")
yaml.safe_dump(d, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
from alembic import command
from alembic.config import Config
cfg = Config(${JSON.stringify(path.join(REPO, "alembic.ini"))}); cfg.attributes["url"] = ${JSON.stringify(dbUrl)}
command.upgrade(cfg, "head")
print(json.dumps({"config": p, "rad": os.path.join(files, "drop_0000.rad"), "inc": os.path.join(files, "extra.inc"), "big": big, "mid": mid}))
`;
  const r = spawnSync(PY, ["-c", code], {
    cwd: REPO,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: [path.join(REPO, "backend"), path.join(REPO, "worker"), REPO].join(path.delimiter) },
  });
  if (r.status !== 0) throw new Error(`입력·설정 생성 실패\n${r.stdout}\n${r.stderr}`);
  return JSON.parse(r.stdout.trim().split("\n").pop());
}

function sha256File(p) {
  const h = createHash("sha256");
  const fd = fs.openSync(p, "r");
  const buf = Buffer.alloc(16 * 1024 * 1024);
  let n;
  while ((n = fs.readSync(fd, buf, 0, buf.length, null)) > 0) h.update(buf.subarray(0, n));
  fs.closeSync(fd);
  return h.digest("hex");
}

async function cleanup() {
  for (const { p } of procs.reverse()) {
    p.__stopping = true;
    try {
      p.kill("SIGTERM");
    } catch {
      /* 무시 */
    }
  }
  await sleep(800);
  for (const { p } of procs) {
    try {
      p.kill("SIGKILL");
    } catch {
      /* 무시 */
    }
  }
  if (pg) {
    try {
      asPg([path.join(pg.bin, "pg_ctl"), "-D", pg.data, "-m", "immediate", "stop"]);
    } catch {
      /* 무시 */
    }
  }
  if (tmp && process.env.ESL_E2E_KEEP !== "1") fs.rmSync(tmp, { recursive: true, force: true });
}

// ---------------------------------------------------------------------------------------------- 시나리오
async function scenario(base, inp) {
  const { chromium } = loadPlaywright();
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 2560, height: 1440 } });
  const page = await ctx.newPage();
  page.on("crash", () => log("페이지 crash"));
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("dialog", (d) => void d.accept());
  const api = (p, init) =>
    page.evaluate(
      async ([p, init]) => {
        const r = await fetch(`/esl/api${p}`, { ...init, headers: { "Content-Type": "application/json", "X-ESL-Request": "1", ...(init?.headers ?? {}) } });
        return { status: r.status, body: r.status === 204 ? null : await r.json() };
      },
      [p, init ?? {}],
    );
  const vshot = async (name) => {
    const f = path.join(SHOTS, `${name}.png`);
    await page.screenshot({ path: f });
    log("스크린샷(2560x1440)", f);
    return f;
  };
  const NEW = `${base}/esl/p/dev/cases/new`;
  const pick = async (rad, h3d) => {
    await page.goto(NEW);
    await page.getByRole("heading", { name: "새 Case" }).waitFor();
    await page.getByLabel("① rad · include 파일 파일").setInputFiles(rad);
    await page.getByLabel("② h3d 결과 파일 파일").setInputFiles(h3d);
  };
  const result = {};

  // ---------------- 1) 1 GB 병렬 업로드 → complete
  await page.goto(`${base}/esl/`);
  const ver = await api("/version");
  check(ver.status === 200 && ver.body.version === APP_VERSION && ver.body.ui?.upload_slim_hint_gb === 5, `version 이상: ${JSON.stringify(ver)}`);
  await pick([inp.rad], [inp.big]);
  puts.delayMs = 0;
  const tUp = Date.now();
  await page.getByRole("button", { name: "올리기", exact: true }).click();
  const chip = page.getByTestId("upload-chip");
  await chip.waitFor({ timeout: 60000 });
  // 진행 중(서버가 받은 양 15~85%)이 될 때까지
  for (let i = 0; i < 600; i++) {
    const l = (await api("/uploads?state=OPEN")).body;
    const u = l[0];
    if (u && u.total_bytes > 0 && u.received_bytes / u.total_bytes >= 0.3) break;
    await sleep(100);
  }
  puts.delayMs = 12000;           // 스크린샷 두 장을 찍는 동안 다음 청크를 붙잡아 진행 중 상태를 유지
  await page.getByText(/동시 \d\/4/).waitFor({ timeout: 30000 });
  const cur = (await api("/uploads?state=OPEN")).body[0];
  check(cur && cur.protocol === 2 && cur.max_parallel === 4 && cur.chunk_size === 64 * 1024 ** 2, `UploadOut 이상: ${JSON.stringify(cur)?.slice(0, 400)}`);
  check(cur.client?.name === "esl-web", `client 이상: ${JSON.stringify(cur.client)}`);
  const shot1 = await vshot("e2e_1_uploading_list");
  // 다른 화면(프로젝트 홈)으로 가도 업로드가 이어지고 상단 칩이 보인다
  await page.evaluate(() => {
    history.pushState({}, "", "/esl/p/dev");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await page.waitForURL(/\/esl\/p\/dev$/);
  await page.getByRole("heading", { name: "새 Case" }).waitFor({ state: "detached", timeout: 10000 });
  await chip.waitFor();
  const chipText = (await chip.textContent()) ?? "";
  check(/업로드 \d+%/.test(chipText), `상단 칩 문구 이상: ${chipText}`);
  const shot2 = await vshot("e2e_2_top_chip");
  puts.delayMs = 0;
  // 완료까지(칩 '업로드 완료' 또는 서버 COMPLETED)
  let done = null;
  for (let i = 0; i < 1200 && !done; i++) {
    const l = (await api(`/uploads/${cur.upload_id}`)).body;
    if (l.state === "COMPLETED") done = l;
    else await sleep(250);
  }
  check(done, "1 GB 업로드가 COMPLETED 가 되지 않았습니다");
  const secs = (Date.now() - tUp) / 1000;
  const h = done.files.find((f) => f.rel.endsWith(".h3d"));
  const srv = path.join(done.dir_path, ...h.rel.split("/"));
  check(h.size === BIG_MB * 1024 ** 2 && h.received_total === h.size && h.n_chunks === Math.ceil(h.size / done.chunk_size), `h3d 항목 이상: ${JSON.stringify(h)}`);
  check(fs.statSync(srv).size === h.size, "서버 파일 크기 불일치");
  const localSha = sha256File(inp.big);
  check(h.sha256 === localSha && sha256File(srv) === localSha, `sha256 불일치 ${h.sha256} ${localSha}`);
  check(done.result?.ok === true && done.result.h3d_path && done.result.rad_path, `complete 결과 이상: ${JSON.stringify(done.result)}`);
  check(puts.maxInflight >= 2 && puts.maxInflight <= 4, `동시 PUT 수 이상: ${puts.maxInflight}`);
  result.big = { mb: BIG_MB, chunks: h.n_chunks, puts: puts.n, maxInflight: puts.maxInflight, secs: Number(secs.toFixed(1)), sha256: localSha.slice(0, 12) };
  log("1) 1 GB 업로드 완료", JSON.stringify(result.big));

  // ?upload= 재진입: 브라우저 업로드 → '브라우저에서 올림'
  await page.goto(`${NEW}?upload=${done.upload_id}`);
  const pcUp = page.getByTestId("pc-upload");
  await pcUp.waitFor();
  await page.getByText("브라우저에서 올림").waitFor();
  check(!(await pcUp.textContent()).includes("PC에서 올림"), "브라우저 업로드인데 'PC에서 올림' 표시");

  // ---------------- 2) 멈춤 → 파일 하나 빼기 → 전체 지우기(세션 취소)
  await pick([inp.rad, inp.inc], [inp.mid]);
  puts.delayMs = 20000;           // 청크가 프록시에서 붙잡혀 있는 동안 멈춤(해시 단계에서는 멈춤 버튼이 잠깐 사라지므로 다시 시도)
  await page.getByRole("button", { name: "올리기", exact: true }).click();
  for (let i = 0; i < 120; i++) {
    if (await page.getByRole("button", { name: "이어 올리기" }).isVisible()) break;
    await page.getByRole("button", { name: "멈춤" }).click({ timeout: 500 }).catch(() => undefined);
    await sleep(250);
  }
  puts.delayMs = 0;
  await page.getByRole("button", { name: "이어 올리기" }).waitFor({ timeout: 30000 });
  const second = (await api("/uploads?state=OPEN")).body.find((u) => u.upload_id !== done.upload_id);
  check(second, "두 번째 업로드 세션 없음");
  // 목록에서 h3d 행 선택 → 지우기(1)
  const rows = page.locator(".upload-list tbody tr");
  const n = await rows.count();
  let h3dRow = -1;
  for (let i = 0; i < n; i++) if (((await rows.nth(i).textContent()) ?? "").includes("mid_0001.h3d")) h3dRow = i;
  check(h3dRow >= 0, "h3d 행 없음");
  await page.getByTestId(`row-check-${h3dRow}`).check();
  await page.getByTestId("clear-btn").click();
  let removed = null;
  for (let i = 0; i < 100 && !removed; i++) {
    const u = (await api(`/uploads/${second.upload_id}`)).body;
    const f = u.files.find((x) => x.rel.endsWith("mid_0001.h3d"));
    if (f?.removed) removed = { u, f };
    else await sleep(200);
  }
  check(removed && removed.f.received_total === 0 && removed.u.total_bytes < second.total_bytes, `파일 빼기 실패: ${JSON.stringify(removed?.f)}`);
  // 남은 파일 전체 선택 → 지우기 = 세션 취소(_backup)
  await page.getByLabel("전체 선택").check();
  await page.getByTestId("clear-btn").click();
  let canceled = null;
  for (let i = 0; i < 100 && !canceled; i++) {
    const u = (await api(`/uploads/${second.upload_id}`)).body;
    if (u.state === "CANCELED") canceled = u;
    else await sleep(200);
  }
  check(canceled && canceled.backup_path, `세션 취소 실패: ${JSON.stringify(canceled)?.slice(0, 300)}`);
  result.cancel = { removed: removed.f.rel, total_after_remove: removed.u.total_bytes, state: canceled.state };
  log("2) 파일 빼기·세션 취소", JSON.stringify(result.cancel));

  // ---------------- 3) UPLOAD_LIMIT → open_uploads
  const mk = (name, size) => api("/uploads", { method: "POST", body: JSON.stringify({ project_id: "dev", name, files: [{ rel: "rad/x_0000.rad", size }], client: { name: "esl-pc", version: "0.6.0" } }) });
  const o1 = await mk("열린업로드A", 1000);
  const o2 = await mk("열린업로드B", 2000);
  check(o1.status === 201 && o2.status === 201, `열린 업로드 만들기 실패 ${o1.status} ${o2.status}`);
  check(o1.body.client?.name === "esl-pc", "client esl-pc 저장 안 됨");
  const lim = await mk("세번째", 10);
  check(lim.status === 429 && lim.body.detail.code === "UPLOAD_LIMIT", `UPLOAD_LIMIT 아님: ${JSON.stringify(lim)}`);
  const ou = lim.body.detail.open_uploads;
  check(Array.isArray(ou) && ou.length === 2 && ou.every((o) => ["id", "name", "created_at", "received_bytes", "total_bytes", "problems_count"].every((k) => k in o)), `open_uploads 키 이상: ${JSON.stringify(ou)}`);
  check(!("open" in lim.body.detail), "detail.open 이 남아 있음");
  await pick([inp.rad], [inp.big]);
  await page.getByRole("button", { name: "올리기", exact: true }).click();
  await page.getByTestId("upload-limit-note").waitFor({ timeout: 30000 });
  const det = page.getByTestId("open-uploads");
  await det.waitFor();
  check(await det.evaluate((e) => e.open), "'진행 중인 업로드' 목록이 펼쳐지지 않음");
  const detText = (await det.textContent()) ?? "";
  check(detText.includes("열린업로드A") && detText.includes("열린업로드B"), `목록에 열린 업로드 없음: ${detText.slice(0, 200)}`);
  await det.scrollIntoViewIfNeeded();
  const shot3 = await vshot("e2e_3_upload_limit");
  result.limit = { open_uploads: ou.map((o) => o.name), keys: Object.keys(ou[0]) };
  log("3) UPLOAD_LIMIT", JSON.stringify(result.limit));

  check(!errors.length, `페이지 오류: ${errors.join(" | ")}`);
  await browser.close();
  return { ...result, shots: [shot1, shot2, shot3] };
}

async function main() {
  if (!fs.existsSync(path.join(DIST, "index.html"))) throw new Error("frontend/dist 가 없습니다 — cd frontend && npm run build");
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "esl-e2e-up-"));
  const bin = pgBin();
  const pgDir = path.join(tmp, "pg");
  fs.mkdirSync(pgDir);
  if (isRoot) {
    fs.chmodSync(tmp, 0o755);
    execSync(`chown postgres ${JSON.stringify(pgDir)}`);
    fs.chmodSync(pgDir, 0o700);
  }
  const pgPort = await freePort();
  pg = { bin, data: path.join(pgDir, "data") };
  asPg([path.join(bin, "initdb"), "-D", pg.data, "-A", "trust", "-U", "postgres", "-E", "UTF8", "--no-sync"]);
  asPg([path.join(bin, "pg_ctl"), "-D", pg.data, "-l", path.join(pgDir, "log"), "-w", "-o", `-p ${pgPort} -k ${pgDir} -c listen_addresses=127.0.0.1 -c fsync=off`, "start"]);
  const dbUrl = `postgresql+psycopg://postgres@127.0.0.1:${pgPort}/postgres`;
  log("PostgreSQL", dbUrl);
  const inp = setupInputs(dbUrl);
  log("입력", inp.big, `${BIG_MB} MB`);
  const env = {
    ESL_PLATFORM_CONFIG: inp.config,
    ESL_DATABASE_URL: dbUrl,
    ESL_BIND_HOST: "127.0.0.1",
    PYTHONPATH: [path.join(REPO, "backend"), path.join(REPO, "worker"), REPO].join(path.delimiter),
  };
  const apiPort = await freePort();
  startProc("uvicorn", PY, ["-m", "uvicorn", "esl_platform.api.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], env);
  await waitHttp(`http://127.0.0.1:${apiPort}/esl/api/health`);
  const frontPort = await freePort();
  const front = await startFront(frontPort, apiPort);
  const base = `http://127.0.0.1:${frontPort}`;
  await waitHttp(`${base}/esl/`);
  try {
    const r = await scenario(base, inp);
    log("E2E 성공", JSON.stringify(r));
  } finally {
    front.close();
  }
}

main()
  .then(async () => {
    await cleanup();
    process.exit(0);
  })
  .catch(async (e) => {
    console.error("E2E 실패:", e?.stack ?? e);
    if (tmp) {
      const f = path.join(tmp, "uvicorn.log");
      if (fs.existsSync(f)) console.error("---- uvicorn.log (끝 40줄)\n" + fs.readFileSync(f, "utf8").split("\n").slice(-40).join("\n"));
    }
    await cleanup();
    process.exit(1);
  });
