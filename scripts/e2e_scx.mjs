#!/usr/bin/env node
// v0.11.0 SCX 드라이브에서 고르기 실서버 E2E(계약 esl_scx_relay.md 기능 A): 임시 PostgreSQL + uvicorn(backend) + 워커(esl_worker, XFER 레인)
// + 가짜 대시보드 릴레이(backend/tests/scx/fake_scx_relay.py — 별도 Python 프로세스, h3d 를 천천히 보냄) + 빌드된 프런트
// (/esl/ 정적 서빙, /esl/api/* → backend 프록시)를 띄우고 Playwright(Chromium, 2560×1440)로
//   1) 새 Case → SCX 탭 → 루트·폴더 탐색(A/model 에서 rad, A/res 에서 h3d) → SCX에서 내려받기 → 진행(작업 진행 문구 + 파일별 h3d 진행률)
//      → 확인 결과 → Case 만들기 → ① 입력 단계 진입. 서버 응답(source scx·drive_rel·client scx-relay·lane XFER·result.scx)도 대조
//   2) 릴레이 프로세스를 죽인 뒤 새 Case 다시 열기 → SCX 탭 비활성 + 사유(SCX_RELAY_UNREACHABLE), 다른 탭 정상
// 를 확인한다. mock 아님. 인증 dev_static(전역 관리자 — 연결 상세 표시).
//
// 사용: node scripts/e2e_scx.mjs [스크린샷 폴더]   (먼저 cd frontend && npm run build)
// env: PG_BIN, PYTHON(기본 python3), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers), PLAYWRIGHT_MODULE,
//      ESL_E2E_H3D_MB(기본 8), ESL_E2E_RATE_MBPS(기본 1 — 가짜 릴레이 h3d 전송 속도), ESL_E2E_KEEP=1 이면 임시 폴더를 남김.
import { spawn, spawnSync, execSync } from "node:child_process";
import { createRequire } from "node:module";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DIST = path.join(REPO, "frontend", "dist");
const PY = process.env.PYTHON || "python3";
const SHOTS = path.resolve(process.argv[2] || path.join(REPO, "work", "scx_live"));
const H3D_MB = Number(process.env.ESL_E2E_H3D_MB || 8);
const RATE_MBPS = Number(process.env.ESL_E2E_RATE_MBPS || 1);
const PID = "dev";
process.env.PLAYWRIGHT_BROWSERS_PATH ||= "/opt/pw-browsers";

const procs = [];
let tmp = null;
let pg = null;
const t0 = Date.now();
const log = (...a) => console.log(`[e2e-scx ${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
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
const PYPATH = [path.join(REPO, "backend"), path.join(REPO, "worker"), REPO].join(path.delimiter);
/** 저장소 동봉 simdash_adapters wheel(zip import — scripts/test-all 과 같은 방식) */
function adapterWheel() {
  const lock = JSON.parse(fs.readFileSync(path.join(REPO, "deploy", "simdash_adapters.lock"), "utf8"));
  const w = path.join(REPO, "deploy", "wheels", lock.wheel);
  check(fs.existsSync(w), `어댑터 wheel 없음: ${w}`);
  return w;
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

/** /esl/api/* → backend 프록시, /esl/* → dist(index.html fallback) */
function startFront(port, apiPort) {
  const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json" };
  const srv = http.createServer((req, res) => {
    const u = new URL(req.url, "http://x");
    if (u.pathname.startsWith("/esl/api/") || u.pathname === "/esl/api") {
      const pr = http.request({ host: "127.0.0.1", port: apiPort, path: req.url, method: req.method, headers: req.headers }, (r2) => {
        res.writeHead(r2.statusCode, r2.headers);
        r2.pipe(res);
      });
      pr.on("error", () => {
        res.writeHead(502);
        res.end("bad gateway");
      });
      req.pipe(pr);
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

/** 가짜 릴레이(살아 있는 Python 프로세스) + 드라이브 합성 모델 + 플랫폼 설정 + migration. 준비되면 JSON 한 줄을 stdout 에 쓰고 대기 */
function startRelay(dbUrl) {
  const code = `
import json, os, sys, time
from pathlib import Path
R = ${JSON.stringify(REPO)}
sys.path[:0] = [os.path.join(R, "backend", "tests"), os.path.join(R, "backend"), os.path.join(R, "worker"), R]
import yaml
from scx_support import build_model, scx_settings, start_relay
base = Path(${JSON.stringify(tmp)}) / "base"; base.mkdir()
relay = start_relay(base / "drive")
h3d = b"HYPER3D " + os.urandom(1024 * 1024) + bytes(${H3D_MB} * 1024 * 1024 - 1024 * 1024 - 8)
model = build_model(relay, h3d=h3d)
relay.download_rate_bps = int(${RATE_MBPS} * 1024 * 1024)        # h3d 를 천천히(진행률 화면)
d = scx_settings(base, relay)
d["auth"]["mode"] = "dev_static"
d["worker"].update({"heartbeat_interval_s": 1, "lease_ttl_s": 10, "claim_interval_s": 0.5, "cancel_check_interval_s": 0.5})
d["ui"]["poll_job_ms"] = 1000
d["upload"]["max_file_bytes"] = 1024 ** 3
d["upload"]["max_upload_bytes"] = 2 * 1024 ** 3
p = base / "esl_platform.yaml"
p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
from alembic import command
from alembic.config import Config
cfg = Config(os.path.join(R, "alembic.ini")); cfg.attributes["url"] = ${JSON.stringify(dbUrl)}
command.upgrade(cfg, "head")
print(json.dumps({"config": str(p), "relay": relay.url, "rad": model["rad"], "h3d": model["h3d"], "h3d_size": len(h3d),
                  "upload_root": d["storage"]["upload_root"]}), flush=True)
while True:
    time.sleep(3600)
`;
  const outFile = path.join(tmp, "relay.log");
  const p = startProc("relay", PY, ["-c", code], { PYTHONPATH: `${adapterWheel()}${path.delimiter}${PYPATH}` });
  return new Promise((resolve, reject) => {
    const end = Date.now() + 90000;
    const poll = () => {
      const txt = fs.existsSync(outFile) ? fs.readFileSync(outFile, "utf8") : "";
      const line = txt.split("\n").find((l) => l.startsWith("{") && l.includes('"relay"'));
      if (line) return resolve({ proc: p, ...JSON.parse(line) });
      if (p.exitCode != null) return reject(new Error(`가짜 릴레이·설정 준비 실패\n${txt}`));
      if (Date.now() > end) return reject(new Error(`가짜 릴레이 준비 시간 초과\n${txt}`));
      setTimeout(poll, 200);
    };
    poll();
  });
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
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("dialog", (d) => void d.accept());
  const api = (p) =>
    page.evaluate(async (p) => {
      const r = await fetch(`/esl/api${p}`, { headers: { "X-ESL-Request": "1" } });
      return { status: r.status, body: await r.json() };
    }, p);
  const vshot = async (name) => {
    const f = path.join(SHOTS, `${name}.png`);
    await page.screenshot({ path: f });
    log("스크린샷(2560x1440)", f);
    return f;
  };
  const NEW = `${base}/esl/p/${PID}/cases/new`;
  const result = {};

  // ---------------- 1) 탐색 → 선택 → 내려받기(진행률) → Case 만들기 → ①
  await page.goto(`${base}/esl/`);
  const st = await api(`/scx/status?project_id=${PID}`);
  check(st.status === 200 && st.body.fetch.enabled === true, `scx/status 이상: ${JSON.stringify(st.body)}`);
  check(st.body.verify.enabled === false && st.body.relay.reachable === true && st.body.roots.map((r) => r.key).join() === "drop", `scx/status 키 이상: ${JSON.stringify(st.body)}`);
  check(Object.keys(st.body).sort().join() === "adapters,fetch,relay,roots,verify", "ScxStatusOut 키 이상");
  // v0.12.0 L4: 화면이 /scx/status 를 받아 탭 상태를 그린 뒤에 확인(로드 전 aria 값을 읽는 경합 방지)
  const stLoaded = page.waitForResponse((r) => r.url().includes("/esl/api/scx/status") && r.status() === 200, { timeout: 30000 });
  await page.goto(`${NEW}?tab=scx`);
  await page.getByRole("heading", { name: "새 Case" }).waitFor();
  await stLoaded;
  const tab = page.getByRole("tab", { name: /SCX 드라이브에서 고르기/ });
  for (let i = 0; i < 100 && (await tab.getAttribute("aria-selected")) !== "true"; i++) await sleep(100);
  check((await tab.getAttribute("aria-selected")) === "true" && !(await tab.getAttribute("aria-disabled")), "SCX 탭이 켜져 있지 않음");
  // 루트(이 프로젝트에 허용된 drop 1개 — p2only 는 프로젝트 p-2 전용이라 빠짐) → 경로 줄 첫 칸
  await page.getByRole("navigation", { name: "폴더 경로" }).getByRole("button", { name: "낙하해석 공유" }).waitFor();
  const table = page.getByRole("table", { name: "SCX 드라이브 폴더 목록" });
  await table.getByRole("button", { name: "A/" }).click();
  await table.getByRole("button", { name: "model/" }).click();
  await table.getByRole("button", { name: "rad 선택" }).waitFor();
  check(await table.getByText("엔진 rad · 자동").isVisible(), "엔진 rad 표지 없음");
  await table.getByRole("button", { name: "rad 선택" }).click();
  await page.getByTestId("scx-auto").waitFor();
  await table.getByRole("button", { name: ".. 위로" }).click();
  await table.getByRole("button", { name: "res/" }).click();
  await table.getByRole("button", { name: "h3d 선택" }).click();
  const start = page.getByTestId("scx-start");
  for (let i = 0; i < 50 && (await start.isDisabled()); i++) await sleep(100);
  check(!(await start.isDisabled()), "SCX에서 내려받기 버튼이 켜지지 않음");
  const tStart = Date.now();
  const fetchResp = page.waitForResponse((r) => r.url().includes("/esl/api/scx/fetches") && r.request().method() === "POST");
  await start.click();
  const fr = await fetchResp;
  check(fr.status() === 202, `POST /scx/fetches ${fr.status()}`);
  const fout = await fr.json();
  check(Object.keys(fout).sort().join() === "job_id,upload_id", `ScxFetchOut 키 이상: ${JSON.stringify(fout)}`);
  await page.getByTestId("scx-fetch").waitFor({ timeout: 20000 });
  // 진행 중: 파일별 h3d 진행률(서버 files[].received_total) + 작업 진행 문구
  await page.getByTestId("file-progress").waitFor({ timeout: 60000 });
  await page.getByTestId("job-progress-label").filter({ hasText: /^h3d \d+\.\d \/ \d+\.\d (GB|MB)$/ }).waitFor({ timeout: 30000 });
  const label = await page.getByTestId("job-progress-label").textContent();
  const prog = await page.getByTestId("file-progress").textContent();
  const shot1 = await vshot("e2e_1_scx_fetch_progress");
  const open = (await api("/uploads?state=OPEN")).body;
  const up0 = open.find((u) => u.name === "ref");
  check(up0, `진행 중 업로드 없음: ${JSON.stringify(open).slice(0, 300)}`);
  const live = (await api(`/uploads/${up0.upload_id}`)).body;
  const h0 = live.files.find((f) => f.rel === "h3d/ref.h3d");
  check(h0 && h0.source === "scx" && !h0.done && h0.received_total > 0 && h0.received_total < h0.size, `받는 중 h3d 항목 이상: ${JSON.stringify(h0)}`);
  check(live.client?.name === "scx-relay", `세션 client 이상: ${JSON.stringify(live.client)}`);
  result.progress = { label, file: prog?.trim(), received_total: h0.received_total, size: h0.size };
  log("1a) 진행 중", JSON.stringify(result.progress));
  // 완료 → 확인 결과
  await page.getByTestId("scx-fetch").getByLabel("올린 파일 확인 결과").filter({ hasText: "rad·h3d 확인됨" }).waitFor({ timeout: 120000 });
  const fetchSecs = (Date.now() - tStart) / 1000;
  const done = (await api(`/uploads/${up0.upload_id}`)).body;
  check(done.state === "COMPLETED" && done.result?.ok, `업로드 COMPLETED 아님: ${JSON.stringify(done).slice(0, 400)}`);
  check(done.files.every((f) => f.source === "scx" && f.done && f.drive_rel), `files source·drive_rel 이상: ${JSON.stringify(done.files)}`);
  check(done.result.scx?.rad_rel === inp.rad && done.result.scx?.h3d_rel === inp.h3d && done.result.scx.missing_specs.length === 0, `result.scx 이상: ${JSON.stringify(done.result.scx)}`);
  check(fout.upload_id === up0.upload_id, "업로드 id 불일치");
  const fj = (await api(`/jobs/${fout.job_id}`)).body;
  check(fj.lane === "XFER" && fj.state === "SUCCEEDED" && fj.upload_id === up0.upload_id, `SCX_FETCH 작업 이상: ${JSON.stringify(fj).slice(0, 300)}`);
  await page.getByTestId("scx-fetch").getByText("SCX에서 받음").waitFor();
  // ?upload=<id> 로 바뀐 주소 → '내 PC에서 올리기' 탭의 업로드 요약도 출처 'SCX에서 받음'(files[].source scx)
  check(((await page.getByTestId("pc-upload").textContent()) ?? "").includes("SCX에서 받음"), "업로드 요약 출처가 SCX 가 아님");
  // Case 만들기 → ① 입력
  const create = page.getByRole("button", { name: "Case 만들기" });
  for (let i = 0; i < 100 && (await create.isDisabled()); i++) await sleep(100);
  await create.click();
  await page.getByRole("heading", { level: 2, name: /① 입력/ }).waitFor({ timeout: 30000 });
  const caseUrl = page.url();
  result.fetch = { secs: Number(fetchSecs.toFixed(1)), files: done.files.map((f) => f.rel), job: { lane: fj.lane, state: fj.state, label: fj.progress_label, steps: (fj.steps ?? []).map((s) => `${s.step_key}:${s.state}`) }, case_url: caseUrl };
  log("1b) 완료·Case", JSON.stringify(result.fetch));

  // ---------------- 2) 릴레이 다운 → 탭 비활성 + 사유
  inp.proc.__stopping = true;
  inp.proc.kill("SIGKILL");
  await sleep(500);
  const stLoaded2 = page.waitForResponse((r) => r.url().includes("/esl/api/scx/status"), { timeout: 30000 });
  await page.goto(NEW);
  await page.getByRole("heading", { name: "새 Case" }).waitFor();
  await stLoaded2;
  const tab2 = page.getByRole("tab", { name: /SCX 드라이브에서 고르기/ });
  for (let i = 0; i < 100 && (await tab2.getAttribute("aria-disabled")) !== "true"; i++) await sleep(100);
  check((await tab2.getAttribute("aria-disabled")) === "true", "릴레이 다운인데 SCX 탭이 켜져 있음");
  const tip = (await tab2.getAttribute("title")) ?? "";
  check(tip.includes("대시보드에 연결할 수 없습니다"), `탭 사유 툴팁 이상: ${tip}`);
  await tab2.click({ force: true });          // aria-disabled 는 안내용 — 눌러서 사유 패널을 볼 수 있다
  const off = page.getByTestId("scx-off");
  await off.waitFor();
  const offText = (await off.textContent()) ?? "";
  check(offText.includes("대시보드에 연결할 수 없습니다"), `패널 사유 이상: ${offText}`);
  await page.getByText("관리자: 연결 상세").click();
  await page.getByTestId("scx-admin-detail").getByText(/fetch: SCX_RELAY_UNREACHABLE/).waitFor();
  const st2 = (await api(`/scx/status?project_id=${PID}`)).body;
  check(st2.fetch.enabled === false && st2.fetch.reason_code === "SCX_RELAY_UNREACHABLE" && st2.relay.reachable === false, `다운 상태 이상: ${JSON.stringify(st2)}`);
  const shot2 = await vshot("e2e_2_scx_relay_down");
  // 다른 탭은 그대로
  await page.getByRole("tab", { name: "내 PC에서 올리기" }).click();
  await page.getByLabel("① rad · include 파일 파일").waitFor({ state: "attached" });
  check(await page.locator("#panel-upload").isVisible(), "'내 PC에서 올리기' 패널이 보이지 않음");
  result.down = { reason_code: st2.fetch.reason_code, tooltip: tip };
  log("2) 릴레이 다운", JSON.stringify(result.down));

  check(!errors.length, `페이지 오류: ${errors.join(" | ")}`);
  await browser.close();
  return { ...result, shots: [shot1, shot2] };
}

async function main() {
  if (!fs.existsSync(path.join(DIST, "index.html"))) throw new Error("frontend/dist 가 없습니다 — cd frontend && npm run build");
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "esl-e2e-scx-"));
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
  const inp = await startRelay(dbUrl);
  log("가짜 릴레이", inp.relay, `h3d ${inp.h3d_size} B @ ${RATE_MBPS} MB/s`);
  const env = {
    ESL_PLATFORM_CONFIG: inp.config,
    ESL_DATABASE_URL: dbUrl,
    ESL_BIND_HOST: "127.0.0.1",
    PYTHONPATH: `${adapterWheel()}${path.delimiter}${PYPATH}`,
  };
  const apiPort = await freePort();
  startProc("uvicorn", PY, ["-m", "uvicorn", "esl_platform.api.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], env);
  startProc("worker", PY, ["-m", "esl_worker"], env);
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
      for (const n of ["uvicorn", "worker", "relay"]) {
        const f = path.join(tmp, `${n}.log`);
        if (fs.existsSync(f)) console.error(`---- ${n}.log (끝 40줄)\n` + fs.readFileSync(f, "utf8").split("\n").slice(-40).join("\n"));
      }
    }
    await cleanup();
    process.exit(1);
  });
