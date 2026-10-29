#!/usr/bin/env node
// v0.10.0 메뉴 재구성 실서버 E2E(계약 esl_menu_restructure.md §12 V-MR-E2E): 임시 PostgreSQL + uvicorn(backend) + 워커 +
// 빌드된 프런트(/esl/ 하위 경로, e2e_ui.mjs 와 같은 프록시 구조)를 띄우고 Playwright(Chromium, 2560×1440)로
//   A  새 Case(서버 폴더) → ① 추출 → ② t* 확정(지지 3-2-1 자동 OK·카드 3행) → ③ ESL → ④ 검증 PASS → [라이브러리에 등록]
//   B  가늘고 긴 판 Case → ② t* 확정 → 자동 지지 BLOCKED(사유) → ESL_SOLVE 409 support_blocked → '고급 — 지지 노드 직접 지정'
//      (나쁜 3점 422 SUPPORT_CHECK_FAILED problems 표시 → 좋은 3점 저장 MANUAL) → ③ → ④ FAIL(엄격 기준 백엔드로 검증 등록)
//      → 등록 버튼 비활성 + 사유, POST /library/entries 422 VALIDATION_NOT_PASS → 현재 기준 재검증 PASS → 등록
//   C  A 와 같은 모델(같은 rad) Case — API 로 ①~④ + 등록
//   라이브러리: A·C(같은 모델, 서로 다른 Case) 선택 → [내보내기] 창 → zip 받기 → manifest id_range 겹침 없음·inc ID 범위 대조
//   B 항목을 LEGACY 로(이전 판정 체계 등록 재현 — DB) → 행 LEGACY 배지 → [재검증] → PROMOTED(배지 사라짐·안내)
//   옛 /stage/3 → /step/2, /stage/6 → /step/4?moved=export 안내, /doe → 강성 평가 스터디 탭, 탭 진입
// 엄격 기준 백엔드: 같은 DB·저장소를 쓰는 두 번째 uvicorn(validation 기준 1e-12). 검증 기준은 작업 등록 시 params.settings 로
// 고정되므로 이 백엔드로 등록한 VALIDATE 만 FAIL 이 된다(워커는 하나).
//
// 사용: (cd frontend && npm run build) && node scripts/e2e_menu.mjs [스크린샷 폴더]   (기본 /home/claude/screens/v0100)
// env: PG_BIN, PYTHON(기본 python3), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers), PLAYWRIGHT_MODULE, ESL_E2E_KEEP=1(임시 폴더 유지)
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
const SHOTS = path.resolve(process.argv[2] || "/home/claude/screens/v0100");
process.env.PLAYWRIGHT_BROWSERS_PATH ||= "/opt/pw-browsers";
const PID = "dev";
const PYPATH = [path.join(REPO, "backend"), path.join(REPO, "worker"), REPO].join(path.delimiter);

const procs = [];
let tmp = null;
let pg = null;
const t0 = Date.now();
const log = (...a) => console.log(`[e2e-menu ${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
const fail = (msg, extra) => {
  throw new Error(extra === undefined ? msg : `${msg}: ${JSON.stringify(extra).slice(0, 2000)}`);
};

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
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`응답 없음: ${url}`);
}
/** /esl/api/* → backend 프록시, /esl/* → dist(strip_prefix, index.html fallback) — e2e_ui.mjs 와 같음 */
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
    if (!u.pathname.startsWith("/esl/")) {
      res.writeHead(302, { Location: "/esl/" });
      res.end();
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

/** 설정 2개(기본·엄격 기준) · migration · 합성 입력 2종(판 = A·C, 가늘고 긴 판 = B, 지지 수동 3점 노드 ID) */
function setupInputs(dbUrl) {
  const code = `
import copy, json, os, sys, yaml
sys.path[:0] = [${JSON.stringify(path.join(REPO, "tests", "pipeline"))}, ${JSON.stringify(REPO)}]
import synth_case
tmp = ${JSON.stringify(tmp)}
inputs = os.path.join(tmp, "inputs"); root = os.path.join(tmp, "esl_root")
os.makedirs(inputs, exist_ok=True); os.makedirs(root, exist_ok=True)
plate = synth_case.build(os.path.join(inputs, "plate"))
# 가늘고 긴 판(600×60): PCA 4꼭지점·8후보 모두 두 점이 너무 가까움(SUPPORT_TOO_CLOSE) → 자동 지지 BLOCKED
orig = synth_case.plate
NX, NY = 60, 6
synth_case.plate = lambda: orig(nx=NX, ny=NY, Lx=600.0, Ly=60.0)
strip = synth_case.build(os.path.join(inputs, "strip"))
synth_case.plate = orig
nid = lambda i, j: 1001 + 2 * (i * (NY + 1) + j)
good = [nid(0, 0), nid(NX, 0), nid(NX // 2, NY)]            # 아래 두 꼭지점 + 위 가운데 → 면적비 ≈ 1, 거리 0.5·대각선
bad = [nid(0, 0), nid(1, 0), nid(2, 0)]                     # 한 줄·가까움
core = yaml.safe_load(open(${JSON.stringify(path.join(REPO, "config", "esl.example.yaml"))}, encoding="utf-8"))
core["extract"]["disp_precision"] = "float64"
d = yaml.safe_load(open(${JSON.stringify(path.join(REPO, "config", "esl_platform.example.yaml"))}, encoding="utf-8"))
d["profile"] = "dev"
d["auth"]["mode"] = "dev_static"
d["auth"]["dev_static_principal"] = {"user_id": "u-power", "username": "power", "display_name": "파워", "is_global_admin": False,
                                     "memberships": [{"project_id": "${PID}", "role": "power"}]}
d["library"]["config_path"] = ${JSON.stringify(path.join(REPO, "config", "library.example.yaml"))}
d["storage"] = {"esl_root": root, "input_roots": [inputs], "spdm_roots": []}
d["worker"].update({"heartbeat_interval_s": 1, "lease_ttl_s": 10, "claim_interval_s": 0.5, "cancel_check_interval_s": 0.5,
                    "state_dir": os.path.join(tmp, "state")})
d["ui"]["poll_job_ms"] = 1000
d["ui"]["library_export_enabled"] = True      # 라이브러리 내보내기(기본 숨김) — 이 E2E 는 켠 서버에서만 내보내기 단계를 돈다
d["core"] = {"settings": core}
p = os.path.join(tmp, "esl_platform.yaml")
yaml.safe_dump(d, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
s = copy.deepcopy(d)
s["core"]["settings"]["validation"]["disp_rms_rel_max"] = 1e-12
s["core"]["settings"]["validation"]["disp_max_rel_max"] = 1e-12
ps = os.path.join(tmp, "esl_platform_strict.yaml")
yaml.safe_dump(s, open(ps, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
from alembic import command
from alembic.config import Config
cfg = Config(${JSON.stringify(path.join(REPO, "alembic.ini"))}); cfg.attributes["url"] = ${JSON.stringify(dbUrl)}
command.upgrade(cfg, "head")
print(json.dumps({"config": p, "strict": ps, "plate": {"rad": plate["rad"], "csv": plate["csv"]},
                  "strip": {"rad": strip["rad"], "csv": strip["csv"]}, "good": good, "bad": bad, "esl_root": root}))
`;
  const r = spawnSync(PY, ["-c", code], { cwd: REPO, encoding: "utf8", env: { ...process.env, PYTHONPATH: PYPATH } });
  if (r.status !== 0) throw new Error(`입력·설정 생성 실패\n${r.stdout}\n${r.stderr}`);
  return JSON.parse(r.stdout.trim().split("\n").pop());
}

/** 이전 판정 체계(scheme 없음)로 등록된 항목 재현 — worker/tests/test_revalidate.py _make_legacy 와 같은 갱신 */
function makeLegacy(dbUrl, eid) {
  const code = `
import json, sqlalchemy as sa
e = sa.create_engine(${JSON.stringify(dbUrl)})
with e.begin() as c:
    n = c.execute(sa.text("UPDATE library_entries SET quality = (quality - 'scheme') || CAST(:q AS jsonb) WHERE id=:i"),
                  {"i": ${JSON.stringify(eid)}, "q": json.dumps({"status": "LEGACY"})}).rowcount
print(n)
`;
  const r = spawnSync(PY, ["-c", code], { cwd: REPO, encoding: "utf8" });
  if (r.status !== 0 || r.stdout.trim() !== "1") throw new Error(`LEGACY 전환 실패\n${r.stdout}\n${r.stderr}`);
}

/** zip 풀어 manifest·inc 읽기(파이썬 zipfile, 격리 모드) */
function readZip(zipPath) {
  const code = `
import json, re, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
man = json.loads(z.read("manifest.json"))
inc = {}
for n in names:
    if n.endswith("/esl_cload.inc") or n.endswith("/esl_force.fem"):
        t = z.read(n).decode("utf-8", "replace")
        ids = [int(x) for x in re.findall(r"^/(?:CLOAD|FUNCT|BCS|GRNOD/NODE)/(\\d+)", t, re.M)]
        ids += [int(x) for x in re.findall(r"^(?:FORCE|SPC|SPC1|LOAD)[ ,*]+(\\d+)", t, re.M)]
        inc[n] = ids
print(json.dumps({"names": names, "manifest": man, "ids": inc, "readme": "README.txt" in names}))
`;
  const r = spawnSync(PY, ["-I", "-c", code, zipPath], { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`zip 읽기 실패\n${r.stderr}`);
  return JSON.parse(r.stdout);
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
  await new Promise((r) => setTimeout(r, 800));
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

// ---------------------------------------------------------------------------------------------- API(직접, dev_static)
function apiClient(port) {
  const base = `http://127.0.0.1:${port}/esl/api`;
  return async (method, p, body) => {
    const r = await fetch(base + p, {
      method,
      headers: { "Content-Type": "application/json", "X-ESL-Request": "1" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const t = await r.text();
    let b = null;
    try {
      b = JSON.parse(t);
    } catch {
      b = t;
    }
    return { status: r.status, body: b };
  };
}
const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
async function waitJob(api, jobId, ms = 240000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const j = (await api("GET", `/jobs/${jobId}`)).body;
    if (TERMINAL.includes(j.state)) {
      if (j.state !== "SUCCEEDED") fail(`작업 ${j.job_type} ${j.state}`, { code: j.failure_code, msg: j.failure_message });
      return j;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  fail(`작업 대기 시간 초과 ${jobId}`);
}
async function job(api, cid, jt, params = {}) {
  const r = await api("POST", `/cases/${cid}/jobs`, { job_type: jt, params });
  if (r.status !== 201) fail(`${jt} 등록 실패 ${r.status}`, r.body);
  return waitJob(api, r.body.id);
}
async function newCase(api, folder, title, inp) {
  const r = await api("POST", "/cases", { project_id: PID, folder_name: folder, title, rad_path: inp.rad, results_dir: inp.csv, part_title: "Chassis  REAR" });
  if (r.status !== 201) fail("Case 생성 실패", r.body);
  return r.body.id;
}
async function confirmTstar(api, cid) {
  const c = (await api("GET", `/cases/${cid}`)).body;
  const r = await api("PUT", `/cases/${cid}/tstar`, { version: c.version, metric: c.tstar.metric, frame_index: c.tstar.frame_index });
  if (r.status !== 200) fail("t* 확정 실패", r.body);
  return r.body;
}
/** API 로 ①~④(+ 등록) — PASS 확인 */
async function caseViaApi(api, folder, title, inp) {
  const cid = await newCase(api, folder, title, inp);
  await job(api, cid, "CASE_EXTRACT");
  const c = await confirmTstar(api, cid);
  if (c.tstar.support_auto?.status !== "OK") fail(`${folder}: 자동 지지 OK 아님`, c.tstar.support_auto);
  await job(api, cid, "ESL_SOLVE");
  const run = (await api("GET", `/cases/${cid}`)).body.current_esl_run_id;
  const vj = await job(api, cid, "VALIDATE", { esl_run_id: run });
  if (vj.result?.registered?.verdict !== "PASS") fail(`${folder}: 검증 PASS 아님`, vj.result?.registered);
  const e = await api("POST", "/library/entries", { esl_run_id: run });
  if (e.status !== 201) fail(`${folder}: 등록 실패`, e.body);
  return { cid, run, entry: e.body };
}

// ---------------------------------------------------------------------------------------------- 시나리오
async function scenario(base, inp, api, strictApi, dbUrl) {
  const { chromium } = loadPlaywright();
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"] });
  const ctx = await browser.newContext({ viewport: { width: 2560, height: 1440 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  const bad5xx = [];
  page.on("response", (r) => r.url().includes("/esl/api/") && r.status() >= 500 && bad5xx.push([r.status(), r.url()]));
  const shots = [];
  const shot = async (name) => {
    const f = path.join(SHOTS, `${name}.png`);
    await page.screenshot({ path: f });
    shots.push(f);
    log("스크린샷(2560x1440)", f);
  };
  const noHScroll = async (where) => {
    const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
    if (o.sw > o.cw + 1) fail(`${where}: 가로 스크롤`, o);
  };
  const primary = () => page.locator("button[data-primary]").first();
  const stepLink = (n) => page.getByRole("navigation", { name: "단계" }).getByRole("link").nth(n - 1);
  const waitDone = (n, ms = 180000) =>
    page.waitForFunction((k) => document.querySelectorAll('nav[aria-label="단계"] [data-state]')[k - 1]?.getAttribute("data-state") === "done", n, { timeout: ms, polling: 500 });
  const expectEnabled = (label) =>
    page.waitForFunction((l) => {
      const b = document.querySelector("button[data-primary]");
      return b && !b.disabled && (!l || b.textContent.includes(l));
    }, label ?? null, { timeout: 60000 });
  const out = {};

  // ---------------------------------------------------------------- A: 새 Case(UI) ①→②(자동 OK)→③→④ PASS → 등록
  await page.goto(`${base}/esl/`);
  await page.getByRole("link", { name: /개발 프로젝트 dev/ }).click();
  // 상단 메뉴 2개
  const nav = page.locator("header");
  for (const m of ["ESL 생성", "ESL 라이브러리"]) await nav.getByRole("link", { name: m }).first().waitFor();
  await page.getByRole("button", { name: "새 Case" }).click();
  await page.getByRole("heading", { level: 1, name: "새 Case" }).waitFor();
  await page.getByRole("tab", { name: "서버 폴더에서 고르기" }).click();
  const panel = page.getByRole("tabpanel", { name: "서버 폴더에서 고르기" });
  await panel.getByText("고급: 경로 직접 입력").click();
  const adv = panel.locator(".adv-body");
  await adv.locator(".path-field input").nth(0).fill(inp.plate.rad);
  await adv.getByRole("button", { name: "rad로 쓰기" }).click();
  await adv.locator(".path-field input").nth(2).fill(inp.plate.csv);
  await adv.getByRole("button", { name: "결과 폴더로 쓰기" }).click();
  await panel.getByLabel("고른 입력").getByText("done.json 정상").waitFor();
  await page.getByPlaceholder("QN80H_rear40").fill("QN75A_e2e01");
  await page.getByLabel("대상 파트").fill("Chassis  REAR");
  await expectEnabled();
  await page.getByRole("button", { name: "Case 만들기" }).click();
  await page.getByRole("heading", { level: 2, name: "① 입력" }).waitFor();
  if (!/\/step\/1$/.test(new URL(page.url()).pathname)) fail("새 Case 첫 화면이 /step/1 이 아님", page.url());
  const cidA = new URL(page.url()).pathname.split("/c/")[1].split("/")[0];
  if ((await page.getByRole("navigation", { name: "단계" }).getByRole("link").count()) !== 4) fail("스텝퍼 4단계 아님");
  await expectEnabled("추출 실행");
  await primary().click();
  await waitDone(1);
  log("A ① 추출 완료", cidA);

  await stepLink(2).click();
  await page.getByRole("heading", { level: 2, name: "② t*·지지점" }).waitFor();
  await page.getByTestId("support-summary").getByText("t* 확정 시 자동으로 정합니다").waitFor();
  await expectEnabled("t* 확정");
  await primary().click();
  await waitDone(2);
  const sum = page.getByTestId("support-summary");
  await sum.locator("tbody tr").nth(2).waitFor();
  if ((await sum.locator("tbody tr").count()) !== 3) fail("지지 카드 3행 아님");
  await page.getByTestId("support-checks").waitFor();
  await page.getByText("자동", { exact: true }).first().waitFor();
  if (await page.getByTestId("support-advanced").count()) fail("OK 상태에 고급 칸이 보임(편집 UI 없음 원칙)");
  if (await sum.locator("input").count()) fail("지지 카드에 편집 입력칸");
  const caseA = (await api("GET", `/cases/${cidA}`)).body;
  if (caseA.tstar.support_auto?.status !== "OK" || caseA.step_status.tstar.state !== "done") fail("A support_auto/step_status", { sa: caseA.tstar.support_auto, st: caseA.step_status });
  out.A_checks = (await page.getByTestId("support-checks").textContent())?.trim();
  await page.getByTestId("support-summary").scrollIntoViewIfNeeded();
  await noHScroll("A ②");
  await shot("e2e_1_step2_auto_support");

  await stepLink(3).click();
  await page.getByRole("heading", { level: 2, name: "③ ESL" }).waitFor();
  await expectEnabled("ESL 계산");
  await primary().click();
  await waitDone(3);
  await stepLink(4).click();
  await page.getByRole("heading", { level: 2, name: "④ 검증" }).waitFor();
  await expectEnabled("검증 실행");
  await primary().click();
  await waitDone(4);
  await expectEnabled("라이브러리에 등록");
  const vA = (await api("GET", `/cases/${cidA}/validations`)).body[0];
  if (vA.status !== "PASS") fail("A 검증 PASS 아님", vA.status);
  await primary().click();
  await page.getByTestId("reg-done").waitFor({ timeout: 30000 });
  await expectEnabled("검증 실행");
  log("A ④ PASS → 등록 완료");

  // 옛 주소 리다이렉트
  await page.goto(`${base}/esl/p/${PID}/c/${cidA}/stage/3`);
  await page.getByRole("heading", { level: 2, name: "② t*·지지점" }).waitFor();
  if (!new URL(page.url()).pathname.endsWith("/step/2")) fail("/stage/3 → /step/2 아님", page.url());
  await page.goto(`${base}/esl/p/${PID}/c/${cidA}/stage/6`);
  await page.getByTestId("moved-export").waitFor();
  const u6 = new URL(page.url());
  if (!u6.pathname.endsWith("/step/4") || u6.searchParams.get("moved") !== "export") fail("/stage/6 → /step/4?moved=export 아님", page.url());
  out.redirects = "OK";

  // ---------------------------------------------------------------- B: 가늘고 긴 판 — BLOCKED → 고급 수동 → ③ → ④ FAIL → 등록 거부
  const cidB = await newCase(api, "QN65B_e2e02", "가늘고 긴 판", inp.strip);
  await job(api, cidB, "CASE_EXTRACT");
  await page.goto(`${base}/esl/p/${PID}/c/${cidB}/step/2`);
  await page.getByRole("heading", { level: 2, name: "② t*·지지점" }).waitFor();
  await expectEnabled("t* 확정");
  await primary().click();
  await page.getByTestId("support-blocked").waitFor({ timeout: 30000 });
  const probs = await page.getByTestId("support-problems").first().locator("li").allTextContents();
  if (!probs.some((t) => /너무 가깝/.test(t))) fail("BLOCKED 사유(두 점 가까움) 없음", probs);
  const cB = (await api("GET", `/cases/${cidB}`)).body;
  if (cB.tstar.support_auto?.status !== "BLOCKED" || cB.current_support_set_id || cB.step_status.tstar.state !== "failed" || cB.step_status.tstar.reason?.code !== "SUPPORT_AUTO_BLOCKED")
    fail("B BLOCKED 상태", { sa: cB.tstar.support_auto, st: cB.step_status.tstar });
  const es409 = await api("POST", `/cases/${cidB}/jobs`, { job_type: "ESL_SOLVE", params: {} });
  if (es409.status !== 409 || es409.body.detail?.support_blocked !== true || !es409.body.detail?.missing?.includes("support_set")) fail("ESL_SOLVE 409 support_blocked", es409);
  // ③ 화면 차단 사유
  await stepLink(3).click();
  await page.getByRole("heading", { level: 2, name: "③ ESL" }).waitFor();
  const why3 = await page.locator(".primary-wrap").first().getAttribute("title");
  if (!/지지점 자동 선택 실패/.test(why3 ?? "")) fail("③ 차단 사유", why3);
  await stepLink(2).click();
  const advB = page.getByTestId("support-advanced");
  await advB.locator("summary").click();
  const fillIds = async (ids) => {
    for (let k = 0; k < 3; k++) await advB.getByLabel(`지지 노드 ${k + 1}`).fill(String(ids[k]));
  };
  await fillIds(inp.bad);
  await advB.getByRole("button", { name: "지정 저장" }).click();
  await advB.getByTestId("support-problems").waitFor();
  const advErr = (await advB.getByRole("alert").textContent()) ?? "";
  if (!/품질 검사/.test(advErr)) fail("나쁜 3점 422 SUPPORT_CHECK_FAILED 문구", advErr);
  await fillIds(inp.good);
  await advB.getByRole("button", { name: "지정 저장" }).click();
  await waitDone(2);
  await page.getByText("사용자 지정(고급)").waitFor();
  const cB2 = (await api("GET", `/cases/${cidB}`)).body;
  if (cB2.tstar.support_auto?.status !== "MANUAL" || !cB2.current_support_set_id) fail("B MANUAL", cB2.tstar.support_auto);
  if (await page.getByTestId("support-advanced").count()) fail("수동 저장 후에도 고급 칸이 보임");
  log("B ② BLOCKED → 고급 수동 지정 성공", inp.good.join(","));
  await stepLink(3).click();
  await expectEnabled("ESL 계산");
  await primary().click();
  await waitDone(3);
  const runB = (await api("GET", `/cases/${cidB}`)).body.current_esl_run_id;
  // 엄격 기준 백엔드로 검증 등록 → FAIL
  const sv = await strictApi("POST", `/cases/${cidB}/jobs`, { job_type: "VALIDATE", params: { esl_run_id: runB } });
  if (sv.status !== 201) fail("엄격 검증 등록", sv);
  const svj = await waitJob(api, sv.body.id);
  if (svj.result?.registered?.verdict !== "FAIL") fail("B 엄격 검증 FAIL 아님", svj.result?.registered);
  await page.goto(`${base}/esl/p/${PID}/c/${cidB}/step/4`);
  await page.getByRole("heading", { level: 2, name: "④ 검증" }).waitFor();
  const regBlock = page.getByTestId("reg-block");
  await regBlock.waitFor({ timeout: 30000 });
  const regWhy = (await regBlock.textContent()) ?? "";
  if (!/변위 기준 PASS만 등록할 수 있습니다/.test(regWhy)) fail("FAIL 등록 비활성 사유", regWhy);
  if (!(await regBlock.getByRole("button", { name: "라이브러리에 등록" }).isDisabled())) fail("FAIL 등록 버튼이 활성");
  await expectEnabled("검증 실행");
  const rej = await api("POST", "/library/entries", { esl_run_id: runB, force_reason: "사유가 있어도" });
  if (rej.status !== 422 || rej.body.detail?.code !== "VALIDATION_NOT_PASS") fail("FAIL 등록 422 VALIDATION_NOT_PASS", rej);
  out.B_fail = { verdict: svj.result.registered.verdict, fail_reasons: svj.result.validate?.summary?.fail_reasons, register: `${rej.status} ${rej.body.detail.code}`, reason: regWhy.replace(/\s+/g, " ").trim() };
  log("B ④ FAIL → 등록 거부", JSON.stringify(out.B_fail));
  // 현재 기준(기본 백엔드)으로 다시 검증 → PASS → 등록
  await primary().click();
  await expectEnabled("라이브러리에 등록");
  await primary().click();
  await page.getByTestId("reg-done").waitFor({ timeout: 30000 });

  // ---------------------------------------------------------------- C: A 와 같은 모델(다른 Case) — API
  const C = await caseViaApi(api, "QN75A_e2e03", "같은 모델 두 번째", inp.plate);
  log("C ①~④ PASS·등록(API)", C.cid);

  // ---------------------------------------------------------------- 라이브러리: 같은 모델 ESL 2개 → 내보내기 → zip
  const ents = (await api("GET", `/library/entries?project_id=${PID}`)).body;
  const eA = ents.find((e) => e.case_id === cidA);
  const eB = ents.find((e) => e.case_id === cidB);
  const eC = ents.find((e) => e.case_id === C.cid);
  if (!eA || !eB || !eC) fail("등록 항목 3개 아님", ents.map((e) => e.case_id));
  if (!eA.topo_sha256 || eA.topo_sha256 !== eC.topo_sha256 || eA.topo_sha256 === eB.topo_sha256) fail("topo(같은 모델) 판정", [eA.topo_sha256, eB.topo_sha256, eC.topo_sha256]);
  for (const e of [eA, eB, eC]) if (!e.eligible || e.ineligible_reason !== null) fail("새 등록 항목 적격 아님", e);
  makeLegacy(dbUrl, eB.id); // 이전 판정 체계 등록 재현
  const vr = await page.evaluate(async () => (await fetch("/esl/api/version")).json());
  if (vr.ui?.library_export_max_entries !== 50) fail("GET /version ui.library_export_max_entries", vr.ui);

  const listResp = page.waitForResponse((r) => /\/esl\/api\/library\/entries\?/.test(r.url()) && r.request().method() === "GET");
  await page.goto(`${base}/esl/p/${PID}/library`);
  const rows = await (await listResp).json();
  const table = page.getByRole("table", { name: "라이브러리 항목" });
  await table.locator("tbody tr").nth(rows.length - 1).waitFor();
  const rowOf = (eid) => table.locator("tbody tr").nth(rows.findIndex((e) => e.id === eid));
  const check = async (eid) => rowOf(eid).locator('input[type="checkbox"]').check();
  // B: LEGACY 배지 + [재검증]
  await rowOf(eB.id).getByText("LEGACY").first().waitFor();
  await check(eA.id);
  await check(eC.id);
  const pick = page.getByTestId("pick-bar");
  await pick.waitFor();
  if (!/선택 2개/.test((await pick.textContent()) ?? "") || !/같은 모델 2\/2/.test((await pick.textContent()) ?? "")) fail("선택 줄", await pick.textContent());
  await pick.getByRole("button", { name: "내보내기 (2)" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByRole("heading", { name: "내보내기 — ESL 2개" }).waitFor();
  const createResp = page.waitForResponse((r) => r.url().endsWith("/esl/api/library/exports") && r.request().method() === "POST");
  await dlg.getByRole("button", { name: "내보내기 시작" }).click();
  const created = await (await createResp).json();
  if (created.jobs.length !== 2) fail("같은 모델·서로 다른 Case → EXPORT 작업 2개 아님", created.jobs);
  const zipBtn = dlg.getByRole("button", { name: "zip 받기" });
  await page.waitForFunction(() => {
    const b = [...document.querySelectorAll('[role="dialog"] button')].find((x) => x.textContent.trim() === "zip 받기");
    return b && !b.disabled;
  }, null, { timeout: 240000, polling: 1000 });
  const batch = (await api("GET", `/library/exports/${created.batch_id}`)).body;
  if (batch.state !== "SUCCEEDED") fail("내보내기 묶음 SUCCEEDED 아님", batch);
  for (const it of batch.items) if (it.state !== "DONE" || !Array.isArray(it.id_range) || it.id_range.length !== 2) fail("항목 DONE·id_range[시작,끝]", it);
  const [r1, r2] = batch.items.map((it) => it.id_range);
  if (!(r1[1] < r2[0] || r2[1] < r1[0])) fail("같은 모델 ID 범위 겹침", [r1, r2]);
  const summ = (await api("GET", `/library/exports?project_id=${PID}`)).body;
  const srow = summ.find((x) => x.batch_id === created.batch_id);
  for (const k of ["batch_id", "project_id", "created_by", "created_by_name", "created_at", "state", "targets", "n_items", "job_ids"])
    if (!srow || !(k in srow)) fail(`GET /library/exports 행 키 ${k}`, srow);
  await dlg.locator(".export-items").scrollIntoViewIfNeeded();
  await shot("e2e_2_library_export");
  const dlP = page.waitForEvent("download", { timeout: 60000 });
  await zipBtn.click();
  const dl = await dlP;
  const zipPath = path.join(tmp, dl.suggestedFilename() || "export.zip");
  await dl.saveAs(zipPath);
  const z = readZip(zipPath);
  if (!z.readme || z.manifest.items.length !== 2) fail("zip 구조(manifest·README·항목 2)", z.names);
  const zr = z.manifest.items.map((it) => it.id_range);
  if (!(zr[0][1] < zr[1][0] || zr[1][1] < zr[0][0])) fail("manifest id_range 겹침", zr);
  for (const it of z.manifest.items) {
    const lab = it.label;
    for (const [n, ids] of Object.entries(z.ids)) {
      if (!n.startsWith(`${lab}/`)) continue;
      const outside = ids.filter((x) => x < it.id_range[0] || x > it.id_range[1]);
      if (outside.length) fail(`${n} 의 ID 가 id_range 밖`, { range: it.id_range, outside: outside.slice(0, 5) });
    }
  }
  out.export = { zip: path.basename(zipPath), id_ranges: zr, files: z.names.length, inc_ids_checked: Object.values(z.ids).reduce((a, b) => a + b.length, 0) };
  log("내보내기 zip", JSON.stringify(out.export));
  await dlg.getByRole("button", { name: "닫기" }).click();
  await pick.getByRole("button", { name: "선택 해제" }).click();

  // ---------------------------------------------------------------- LEGACY 재검증 → PROMOTED
  await check(eB.id);
  const whyLegacy = (await page.getByTestId("pick-why").textContent()) ?? "";
  if (!/LEGACY 1개 선택됨/.test(whyLegacy)) fail("LEGACY 선택 시 비활성 사유", whyLegacy);
  if (!(await pick.getByRole("button", { name: "강성 평가 스터디 (1)" }).isDisabled())) fail("LEGACY 선택인데 강성 평가 스터디 활성");
  await pick.getByRole("button", { name: "선택 해제" }).click();
  const gate = await api("POST", "/library/analyses", { project_id: PID, filters: { entry_ids: [eB.id] }, options: {} });
  if (gate.status !== 422 || gate.body.detail?.code !== "ENTRY_NOT_ELIGIBLE") fail("LEGACY 종합분석 게이트 422 ENTRY_NOT_ELIGIBLE", gate);
  const revBtn = rowOf(eB.id).getByRole("button", { name: "재검증" });
  if (await revBtn.isDisabled()) fail("재검증 버튼 비활성", await rowOf(eB.id).locator(".primary-wrap").last().getAttribute("title"));
  await rowOf(eB.id).scrollIntoViewIfNeeded();
  await revBtn.click();
  await page.getByTestId("reval-chip").first().waitFor({ timeout: 10000 }).catch(() => undefined);
  await page.getByTestId("reval-toast").waitFor({ timeout: 240000 });
  const toast = (await page.getByTestId("reval-toast").textContent()) ?? "";
  if (!/현재 기준 PASS — 정상 항목으로 전환/.test(toast)) fail("PROMOTED 안내", toast);
  const eB2 = (await api("GET", `/library/entries/${eB.id}`)).body;
  if (!eB2.eligible || eB2.quality.status !== "PASS" || !eB2.quality.revalidated || eB2.quality.revalidated.from_status !== "LEGACY") fail("PROMOTED 후 항목", eB2.quality);
  const rj = (await api("GET", `/jobs/${eB2.quality.revalidated.job_id}`)).body;
  const rv = rj.result?.revalidate;
  if (rv?.outcome !== "PROMOTED" || rv.status !== "PASS" || !Array.isArray(rv.fail_reasons)) fail("jobs.result.revalidate{outcome,status,fail_reasons}", rv);
  await page.waitForFunction((i) => {
    const tr = document.querySelectorAll('table[aria-label="라이브러리 항목"] tbody tr')[i];
    return tr && !/LEGACY/.test(tr.textContent);
  }, rows.findIndex((e) => e.id === eB.id), { timeout: 15000 });
  out.revalidate = { outcome: rv.outcome, status: rv.status, fail_reasons: rv.fail_reasons };
  log("LEGACY 재검증", JSON.stringify(out.revalidate));
  await noHScroll("라이브러리");
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot("e2e_3_library_revalidated");

  // ---------------------------------------------------------------- 강성 평가 스터디 탭·옛 /doe 주소
  const tabs = await page.getByRole("tab").allTextContents();
  for (const t of ["ESL 목록", "강성 평가 스터디", "비드 최적화", "종합분석·버전 비교", "템플릿"]) if (!tabs.some((x) => x.includes(t))) fail(`탭 ${t} 없음`, tabs);
  await page.getByRole("tab", { name: "강성 평가 스터디" }).click();
  await page.waitForFunction(() => new URL(location.href).searchParams.get("tab") === "study");
  if ((await page.getByRole("tab", { name: "강성 평가 스터디" }).getAttribute("aria-selected")) !== "true") fail("강성 평가 스터디 탭 선택 안 됨");
  await page.goto(`${base}/esl/p/${PID}/doe`);
  await page.waitForFunction(() => location.pathname.endsWith("/library") && new URL(location.href).searchParams.get("tab") === "study", null, { timeout: 15000 });
  await page.goto(`${base}/esl/p/${PID}/library?tab=doe`);
  await page.waitForFunction(() => new URL(location.href).searchParams.get("tab") === "study", null, { timeout: 15000 });
  const body = (await page.locator("body").textContent()) ?? "";
  if (/비드 DOE/.test(body.replace(/이전 이름: 비드 DOE/g, ""))) fail("화면에 '비드 DOE' 문구");
  out.study_tab = "OK";

  if (bad5xx.length) fail("API 5xx", bad5xx);
  if (errors.length) fail("브라우저 오류", errors);
  await browser.close();
  return { ...out, shots };
}

async function main() {
  if (!fs.existsSync(path.join(DIST, "index.html"))) throw new Error("frontend/dist 가 없습니다 — cd frontend && npm run build");
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "esl-e2e-menu-"));
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
  log("입력", inp.plate.rad, inp.strip.rad);
  const env = { ESL_PLATFORM_CONFIG: inp.config, ESL_DATABASE_URL: dbUrl, ESL_BIND_HOST: "127.0.0.1", PYTHONPATH: PYPATH };
  const apiPort = await freePort();
  const strictPort = await freePort();
  startProc("uvicorn", PY, ["-m", "uvicorn", "esl_platform.api.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], env);
  startProc("uvicorn_strict", PY, ["-m", "uvicorn", "esl_platform.api.main:app", "--host", "127.0.0.1", "--port", String(strictPort)], { ...env, ESL_PLATFORM_CONFIG: inp.strict });
  startProc("worker", PY, ["-m", "esl_worker"], env);
  await waitHttp(`http://127.0.0.1:${apiPort}/esl/api/health`);
  await waitHttp(`http://127.0.0.1:${strictPort}/esl/api/health`);
  const frontPort = await freePort();
  const front = await startFront(frontPort, apiPort);
  const base = `http://127.0.0.1:${frontPort}`;
  await waitHttp(`${base}/esl/`);
  try {
    const r = await scenario(base, inp, apiClient(apiPort), apiClient(strictPort), dbUrl);
    log("E2E 성공", JSON.stringify(r, null, 1));
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
      for (const n of ["uvicorn", "uvicorn_strict", "worker"]) {
        const f = path.join(tmp, `${n}.log`);
        if (fs.existsSync(f)) console.error(`---- ${n}.log (끝 40줄)\n` + fs.readFileSync(f, "utf8").split("\n").slice(-40).join("\n"));
      }
    }
    await cleanup();
    process.exit(1);
  });
