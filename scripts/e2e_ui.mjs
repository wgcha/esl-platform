#!/usr/bin/env node
// 실서버 UI E2E: 임시 PostgreSQL + uvicorn(backend) + 워커 + 빌드된 프런트(/esl/ 하위 경로 정적 서빙, physicsai 의
// Caddy 패턴 = /esl/api/* → backend 프록시, /esl/* → frontend/dist strip_prefix + index.html fallback)를 띄우고
// Playwright(Chromium)로 합성 Case 를 ①~⑥ 진행한다. 인증 dev_static. 단계별 스크린샷 저장.
//
// 사용: node scripts/e2e_ui.mjs [스크린샷 폴더]   (먼저 cd frontend && npm run build)
// env: PG_BIN(기본 /usr/lib/postgresql/<최신>/bin), PYTHON(기본 python3), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers),
//      PLAYWRIGHT_MODULE(playwright 모듈 경로, 기본 전역 설치), ESL_E2E_KEEP=1 이면 임시 폴더를 남김.
// Playwright 브라우저는 설치하지 않는다(환경에 있는 Chromium 사용).
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
const SHOTS = path.resolve(process.argv[2] || path.join(REPO, "work", "ui_live"));
process.env.PLAYWRIGHT_BROWSERS_PATH ||= "/opt/pw-browsers";

const procs = [];
let tmp = null;
let pg = null;
const t0 = Date.now();
const log = (...a) => console.log(`[e2e ${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);

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

/** /esl/api/* → backend 프록시, /esl/* → dist(strip_prefix, try_files index.html) — Caddy 운영 설정과 같은 경로 구조 */
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

function setupInputs(dbUrl) {
  // 합성 Case(코어 합성 E2E 데이터) + 플랫폼 설정(dev_static) — 파이썬으로 생성
  const code = `
import json, sys, yaml
sys.path[:0] = [${JSON.stringify(path.join(REPO, "tests", "pipeline"))}, ${JSON.stringify(REPO)}]
import synth_case
tmp = ${JSON.stringify(tmp)}
import os
inputs = os.path.join(tmp, "inputs"); root = os.path.join(tmp, "esl_root")
os.makedirs(inputs, exist_ok=True); os.makedirs(root, exist_ok=True)
c = synth_case.build(os.path.join(inputs, "synth"))
core = yaml.safe_load(open(${JSON.stringify(path.join(REPO, "config", "esl.example.yaml"))}, encoding="utf-8"))
core["extract"]["disp_precision"] = "float64"
d = yaml.safe_load(open(${JSON.stringify(path.join(REPO, "config", "esl_platform.example.yaml"))}, encoding="utf-8"))
d["profile"] = "dev"
d["auth"]["mode"] = "dev_static"
d["storage"] = {"esl_root": root, "input_roots": [inputs], "spdm_roots": []}
d["worker"].update({"heartbeat_interval_s": 1, "lease_ttl_s": 10, "claim_interval_s": 0.5, "cancel_check_interval_s": 0.5,
                    "state_dir": os.path.join(tmp, "state")})
d["ui"]["max_artifact_bytes"] = 4096        # 413 경로(다운로드 대신 경로 복사)를 실제로 타도록 작게
d["ui"]["poll_job_ms"] = 1000
d["core"] = {"settings": core}
p = os.path.join(tmp, "esl_platform.yaml")
yaml.safe_dump(d, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
from alembic import command
from alembic.config import Config
cfg = Config(${JSON.stringify(path.join(REPO, "alembic.ini"))}); cfg.attributes["url"] = ${JSON.stringify(dbUrl)}
command.upgrade(cfg, "head")
print(json.dumps({"config": p, "rad": c["rad"], "csv": c["csv"], "esl_root": root}))
`;
  const r = spawnSync(PY, ["-c", code], {
    cwd: REPO,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: [path.join(REPO, "backend"), path.join(REPO, "worker"), REPO].join(path.delimiter) },
  });
  if (r.status !== 0) throw new Error(`입력·설정 생성 실패\n${r.stdout}\n${r.stderr}`);
  return JSON.parse(r.stdout.trim().split("\n").pop());
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

// ---------------------------------------------------------------------------------------------- 시나리오
async function scenario(base, inp) {
  const { chromium } = loadPlaywright();
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: base });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  const nonGet = [];
  page.on("request", (r) => {
    if (r.url().includes("/esl/api/") && r.method() !== "GET") nonGet.push([r.method(), r.headers()["x-esl-request"]]);
  });
  const shot = async (name) => {
    const f = path.join(SHOTS, `${name}.png`);
    await page.screenshot({ path: f, fullPage: true });
    log("스크린샷", f);
  };
  const primary = () => page.locator("button[data-primary]");
  const stageLink = (n) => page.getByRole("navigation", { name: "단계" }).getByRole("link").nth(n - 1);
  const waitDone = async (n, ms = 180000) => {
    await page.waitForFunction(
      (k) => document.querySelectorAll('nav[aria-label="단계"] [data-state]')[k - 1]?.getAttribute("data-state") === "done",
      n,
      { timeout: ms, polling: 500 },
    );
  };
  const expectEnabled = async () => {
    await page.waitForFunction(() => {
      const b = document.querySelector("button[data-primary]");
      return b && !b.disabled;
    }, null, { timeout: 30000 });
  };

  // 프로젝트 → Case 목록 → 새 Case
  await page.goto(`${base}/esl/`);
  await page.getByRole("link", { name: /개발 프로젝트 dev/ }).click();
  await page.getByRole("heading", { name: "Case 목록" }).waitFor();
  await page.getByRole("button", { name: "새 Case" }).click();
  const form = page.getByRole("region", { name: "새 Case" });
  await form.getByLabel("폴더 이름").fill("e2e_case01");
  await form.getByLabel("제목").fill("합성 판 E2E");
  const pathInputs = form.locator(".path-field input");
  await pathInputs.nth(0).fill(inp.rad);
  await form.locator(".path-field").nth(0).getByRole("button", { name: "확인" }).click();
  await form.getByText("rad 읽기 가능").waitFor();
  await pathInputs.nth(1).fill(inp.csv);
  await form.locator(".path-field").nth(1).getByRole("button", { name: "확인" }).click();
  await form.getByText("done.json 정상").waitFor();
  await shot("00_new_case");
  await form.getByRole("button", { name: "Case 만들기" }).click();

  // ① 입력 → 추출
  await page.getByRole("heading", { level: 2, name: "① 입력" }).waitFor();
  await page.getByText("done.json 정상").waitFor();
  await expectEnabled();
  await primary().click();
  await page.getByTestId("job-progress").waitFor();
  await waitDone(1);
  await page.getByText("후보 프레임(D)").waitFor();
  await shot("01_input_extract");

  // ② t*: 다른 후보로 확정했다가 rank 1(자동 t*)로 되돌림(PUT 2회)
  await stageLink(2).click();
  await page.getByRole("heading", { level: 2, name: "② t*" }).waitFor();
  await page.getByRole("img", { name: /max-hold 곡선/ }).waitFor();
  const radios = page.getByRole("radio", { name: /^프레임 / });
  await radios.first().waitFor();
  const nCand = await radios.count();
  const rank1 = await radios.nth(0).getAttribute("aria-label");
  if (nCand > 1) {
    await radios.nth(1).check();
    await primary().click();
    await page.waitForFunction(() => document.querySelector('[data-testid="current-tstar"]')?.textContent?.includes("사용자 선택"), null, { timeout: 15000 });
    await page.getByRole("radio", { name: rank1 }).check();
    await primary().click();
    await page.waitForFunction(
      (lbl) => {
        const t = document.querySelector('[data-testid="current-tstar"]')?.textContent ?? "";
        return t.includes(`${lbl} `) && t.includes("사용자 선택");
      },
      rank1,
      { timeout: 15000 },
    );
  }
  await shot("02_tstar");

  // ③ 지지점: 자동 제안값 저장
  await stageLink(3).click();
  await page.getByRole("heading", { level: 2, name: "③ 지지점" }).waitFor();
  const ids = page.getByRole("textbox", { name: /지지 노드/ });
  await page.waitForFunction(() => [...document.querySelectorAll('input[aria-label^="지지 노드"]')].every((i) => i.value), null, { timeout: 30000 });
  await expectEnabled();
  log("지지 노드", await ids.evaluateAll((els) => els.map((e) => e.value)));
  await primary().click();
  await page.getByText(/저장됨 · /).waitFor({ timeout: 30000 });
  await shot("03_support");

  // ④ ESL
  await stageLink(4).click();
  await page.getByRole("heading", { level: 2, name: "④ ESL" }).waitFor();
  await expectEnabled();
  await primary().click();
  await waitDone(4);
  await page.getByText("강체 회전각").waitFor({ timeout: 30000 });
  await page.getByText("F_eq 상위 노드").waitFor();
  await shot("04_esl");

  // ⑤ 검증
  await stageLink(5).click();
  await page.getByRole("heading", { level: 2, name: "⑤ 검증" }).waitFor();
  await expectEnabled();
  await primary().click();
  await waitDone(5);
  const badge = page.locator(".card").filter({ hasText: "판정" }).locator(".badge").first();
  await badge.waitFor({ timeout: 30000 });
  const verdict = (await badge.textContent())?.trim();
  log("검증 판정", verdict);
  await shot("05_validate");
  if (verdict !== "PASS") throw new Error(`검증 판정이 PASS 가 아님: ${verdict}`);

  // ⑥ 내보내기 + 다운로드(작은 파일) + 413(큰 파일: 경로 복사)
  await stageLink(6).click();
  await page.getByRole("heading", { level: 2, name: "⑥ 내보내기" }).waitFor();
  await expectEnabled();
  await primary().click();
  await waitDone(6);
  await page.locator("td.mono", { hasText: "06_export/" }).first().waitFor({ timeout: 30000 });
  const folder = (await page.getByTestId("folder-path").textContent())?.trim();
  if (!folder || !folder.endsWith("e2e_case01")) throw new Error(`결과 폴더 경로 이상: ${folder}`);
  const rows = page.locator("tbody tr").filter({ has: page.locator("td.mono", { hasText: "06_export/" }) });
  const nRows = await rows.count();
  const tooLarge = page.getByTestId("too-large");
  const nLarge = await tooLarge.count();
  log(`내보낸 파일 ${nRows}개, 다운로드 한도 초과 ${nLarge}개`);
  if (nLarge < 1) throw new Error("413(크기 초과) 안내가 없음");
  // 작은 파일 다운로드
  const dlLink = page.getByRole("link", { name: "다운로드" }).first();
  if ((await dlLink.count()) > 0) {
    const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 15000 }), dlLink.click()]);
    log("다운로드", dl.suggestedFilename());
  }
  // 큰 파일: 경로 복사
  const first = tooLarge.first();
  const txt = await first.textContent();
  if (!txt.includes("파일이 커서 다운로드 대신 경로를 복사하세요")) throw new Error(`413 안내 문구 없음: ${txt}`);
  await first.getByRole("button", { name: "경로 복사" }).click();
  await first.getByRole("button", { name: "복사됨" }).waitFor({ timeout: 5000 });
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  if (!clip.startsWith(folder)) throw new Error(`복사된 경로 이상: ${clip}`);
  log("경로 복사", clip);
  // 실제 413 응답도 확인(목록의 downloadable 과 별개로 서버가 413 detail 을 줌)
  const big = await page.evaluate(async () => {
    const cid = location.pathname.split("/c/")[1].split("/")[0];
    const arts = await (await fetch(`/esl/api/cases/${cid}/artifacts`)).json();
    const a = arts.find((x) => !x.downloadable);
    const r = await fetch(`/esl/api/artifacts/${a.id}/download`);
    return { status: r.status, body: await r.json(), a };
  });
  if (big.status !== 413 || big.body.detail.code !== "ARTIFACT_TOO_LARGE" || big.body.detail.path !== big.a.path)
    throw new Error(`413 응답 이상: ${JSON.stringify(big)}`);
  await shot("06_export");

  // 진행 요약(Case 목록)·상태 패널의 솔버
  await page.goto(`${base}/esl/p/dev`);
  await page.getByRole("link", { name: "합성 판 E2E" }).waitFor();
  await page.getByText(/· 솔버 /).waitFor();
  await shot("07_case_list");

  if (nonGet.some(([, h]) => h !== "1")) throw new Error(`X-ESL-Request 누락 요청: ${JSON.stringify(nonGet)}`);
  if (errors.length) throw new Error("브라우저 오류:\n" + errors.join("\n"));
  await browser.close();
  return { verdict, nRows, nLarge, nonGet: nonGet.length };
}

async function main() {
  if (!fs.existsSync(path.join(DIST, "index.html"))) throw new Error("frontend/dist 가 없습니다 — cd frontend && npm run build");
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "esl-e2e-"));
  // PostgreSQL 임시 클러스터
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
  asPg([path.join(bin, "pg_ctl"), "-D", pg.data, "-l", path.join(pgDir, "log"), "-w", "-o",
    `-p ${pgPort} -k ${pgDir} -c listen_addresses=127.0.0.1 -c fsync=off`, "start"]);
  const dbUrl = `postgresql+psycopg://postgres@127.0.0.1:${pgPort}/postgres`;
  log("PostgreSQL", dbUrl);

  const inp = setupInputs(dbUrl);
  log("입력", inp.rad, inp.csv);
  const env = {
    ESL_PLATFORM_CONFIG: inp.config,
    ESL_DATABASE_URL: dbUrl,
    ESL_BIND_HOST: "127.0.0.1",
    PYTHONPATH: [path.join(REPO, "backend"), path.join(REPO, "worker"), REPO].join(path.delimiter),
  };
  const apiPort = await freePort();
  startProc("uvicorn", PY, ["-m", "uvicorn", "esl_platform.api.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], env);
  startProc("worker", PY, ["-m", "esl_worker"], env);
  await waitHttp(`http://127.0.0.1:${apiPort}/esl/api/health`);
  const frontPort = await freePort();
  const front = await startFront(frontPort, apiPort);
  const base = `http://127.0.0.1:${frontPort}`;
  await waitHttp(`${base}/esl/`);
  const st = await (await fetch(`${base}/esl/api/status`)).json();
  log("status", JSON.stringify(st.tools), "worker", JSON.stringify(st.worker));
  try {
    const r = await scenario(base, inp);
    log("E2E 성공", JSON.stringify({ ...r, tools: st.tools }), "스크린샷:", SHOTS);
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
      for (const n of ["uvicorn", "worker"]) {
        const f = path.join(tmp, `${n}.log`);
        if (fs.existsSync(f)) console.error(`---- ${n}.log (끝 40줄)\n` + fs.readFileSync(f, "utf8").split("\n").slice(-40).join("\n"));
      }
    }
    await cleanup();
    process.exit(1);
  });
