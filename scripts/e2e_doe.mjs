#!/usr/bin/env node
// v0.9.0 비드 DOE 실서버 E2E(계약 esl_bead_doe.md §3·§10·§12, V-BD-15·17): 임시 PostgreSQL + uvicorn(backend) + 워커
// (가짜 paicad tests/fake_paicad.py, gmsh 실제) + 빌드된 프런트(/esl/ 하위 경로, e2e_ui.mjs 와 같은 프록시 구조)를 띄우고
// Playwright(Chromium, 2560×1440)로
//   ③ 다른 모델(STEP만): 라이브러리 체크 → [선택한 ESL로 비드 DOE] → 시나리오 ③ → STEP 업로드 → 입력 준비 → 변수(D1·D2
//      풀 팩토리얼 3수준) → 미리보기 격자(공칭 d000 썸네일·스킵 배지) → DOE 실행 → 순위·민감도·3D 비교·받기
//   ① 같은 모델: 새 DOE(entries=…) → STEP 업로드 → 입력 준비 → 미리보기 → 실행 → 순위
// 를 1회씩 진행하고, 화면이 읽는 서버 응답 키(preview.cells·excluded·noise_floor·links.from_ab/to_ab/kind·
// settings doe.default_types·part_title·method_sources·best.files·view3d manifest 경로)를 실제 응답으로 대조한다.
//
// 사용: (cd frontend && npm run build) && node scripts/e2e_doe.mjs [스크린샷 폴더]   (기본 /home/claude/screens/v090)
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
const SHOTS = path.resolve(process.argv[2] || "/home/claude/screens/v090");
process.env.PLAYWRIGHT_BROWSERS_PATH ||= "/opt/pw-browsers";
const PID = "p-1";

const procs = [];
let tmp = null;
let pg = null;
const t0 = Date.now();
const log = (...a) => console.log(`[e2e-doe ${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
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

/** 설정(dev_static, bead_doe + 가짜 paicad) · migration · 합성 Case + ESL 3개 · STEP 파일(③ 실제 판 STEP, ① 머리만) */
function setupInputs(dbUrl) {
  const code = `
import json, os, sys
from pathlib import Path
R = ${JSON.stringify(REPO)}
sys.path[:0] = [os.path.join(R, "worker", "tests"), os.path.join(R, "backend", "tests"), os.path.join(R, "backend"), os.path.join(R, "worker"), R]
import yaml
from doe_worker_support import RULES, doe_worker_settings, plate_step, set_control, write_fake_paicad
from doe_support import STEP_BYTES
base = Path(${JSON.stringify(tmp)}) / "base"
base.mkdir()
exe = write_fake_paicad(base)
set_control(exe, rules=RULES, brep="gmsh")
d = doe_worker_settings(base, exe)
d["auth"] = {**d["auth"], "mode": "dev_static",
             "dev_static_principal": {"user_id": "u-power", "username": "power", "display_name": "파워", "is_global_admin": False,
                                      "memberships": [{"project_id": "${PID}", "role": "power"}]}}
d["worker"].update({"heartbeat_interval_s": 1, "lease_ttl_s": 10, "claim_interval_s": 0.5, "cancel_check_interval_s": 0.5})
d["ui"]["poll_job_ms"] = 1000
d["bead_doe"]["settings_cache_s"] = 0
p = base / "esl_platform.yaml"
p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
from alembic import command
from alembic.config import Config
cfg = Config(os.path.join(R, "alembic.ini")); cfg.attributes["url"] = ${JSON.stringify(dbUrl)}
command.upgrade(cfg, "head")
from esl_platform.core.db.engine import make_engine
from test_opt_e2e import make_s1
eng = make_engine(${JSON.stringify(dbUrl)}, pool_size=2)
s1 = make_s1(eng, Path(d["storage"]["esl_root"]), Path(d["storage"]["input_roots"][0]))
eng.dispose()
files = base / "files"; files.mkdir()
plate_step(files / "plate_mid.step")
(files / "chassis_mid.step").write_bytes(STEP_BYTES)
print(json.dumps({"config": str(p), "entry_ids": s1["entry_ids"], "step3": str(files / "plate_mid.step"),
                  "step1": str(files / "chassis_mid.step"), "exe": str(exe), "esl_root": d["storage"]["esl_root"]}))
`;
  const r = spawnSync(PY, ["-c", code], { cwd: REPO, encoding: "utf8" });
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

// ---------------------------------------------------------------------------------------------- 응답 키 대조
const has = (o, keys, where) => {
  for (const k of keys) if (!o || typeof o !== "object" || !(k in o)) fail(`${where}: 키 ${k} 없음`, o);
};
function auditSettings(st) {
  has(st, ["enabled", "reason", "paicad", "gmsh", "scenarios", "max_entries", "max_designs", "doe", "mesh", "boundary", "step_max_mb", "part_title", "method_sources"], "settings");
  if (!st.enabled) fail("settings.enabled false", st);
  has(st.paicad, ["ready", "version", "pinned", "warning"], "settings.paicad");
  has(st.gmsh, ["ready", "version"], "settings.gmsh");
  has(st.scenarios, ["same", "mesh", "step"], "settings.scenarios");
  has(st.doe, ["methods", "default_method", "default_n", "seed", "levels_default", "levels_max", "default_types"], "settings.doe");
  if (!Array.isArray(st.doe.default_types) || !st.doe.default_types.includes("D")) fail("settings.doe.default_types", st.doe);
  if (typeof st.part_title !== "string") fail("settings.part_title", st.part_title);
  has(st.mesh, ["size_auto", "size_min_mm", "size_max_mm"], "settings.mesh");
  has(st.boundary, ["fastener_warn_mm", "load_warn_mm", "load_share_min"], "settings.boundary");
  const ms = st.method_sources;
  has(ms, ["version", "summary_ko", "methods", "sources"], "settings.method_sources");
  if (!Array.isArray(ms.summary_ko) || typeof ms.methods !== "object" || !Array.isArray(ms.sources) || ms.error) fail("method_sources 형식", ms);
  for (const m of ["lhs", "halton", "fullfact"]) if (typeof ms.methods[m] !== "string") fail(`method_sources.methods.${m}`, ms.methods);
  for (const s of ms.sources) if (typeof s.title !== "string") fail("method_sources.sources[].title", s);
}
function auditStudy(s, wantPreview) {
  has(s, ["id", "project_id", "scenario", "title", "entry_ids", "inputs", "phase", "version", "prep", "doe", "job", "result_ready", "created_by_name", "created_at"], "study");
  has(s.inputs, ["step", "part_title", "inch"], "study.inputs");
  if (s.prep) {
    has(s.prep, ["n_beads", "n_params", "paicad_version", "warnings", "boundary"], "study.prep");
    has(s.prep.boundary, ["n_warn", "n_info"], "study.prep.boundary");
  }
  if (wantPreview) {
    has(s.doe, ["rev", "spec", "matrix_sha256", "n_designs", "preview"], "study.doe");
    const pv = s.doe.preview;
    has(pv, ["rev", "matrix_sha256", "ok", "skipped", "cells"], "study.doe.preview");
    has(pv.skipped, ["collision", "fixed", "geom"], "preview.skipped");
    if (!Array.isArray(pv.cells) || !pv.cells.length) fail("preview.cells 비었음", pv);
    for (const c of pv.cells) has(c, ["id", "values", "status", "code", "thumb"], "preview.cells[]");
    if (pv.cells.some((c) => c.id === "d000" || c.id === "nominal")) fail("preview.cells 에 공칭/nominal 셀", pv.cells.map((c) => c.id));
  }
}
function auditPlan(plan, scenario) {
  has(plan, ["frame", "outline", "holes", "elems", "beads", "fixed", "a_points", "load_points", "links"], "plan");
  for (const l of plan.links) {
    has(l, ["from", "to", "d_mm", "warn"], "plan.links[]");
    if (scenario !== "same") {
      has(l, ["from_ab", "to_ab", "kind"], "plan.links[] 선 좌표");
      if (!["fastener", "load", "support"].includes(l.kind)) fail("plan.links[].kind", l);
    }
  }
  for (const b of plan.beads) has(b, ["id", "ring"], "plan.beads[]");
}
function auditParams(p) {
  has(p, ["beads", "params", "warnings"], "params");
  for (const b of p.beads) has(b, ["id", "k", "shape", "sense", "center_ab", "nominal", "fixed_overlap", "png"], "params.beads[]");
  for (const q of p.params) has(q, ["name", "type", "bead", "nominal", "feasible", "feasible_source", "default_range", "use_default", "group_members"], "params.params[]");
}
function auditResult(r, scenario) {
  has(r, ["C_ref", "baseline", "n_ok", "n_skipped", "n_failed", "ranking", "excluded", "sensitivity", "boundary_warnings_n", "view3d", "best", "noise_floor", "warnings"], "result");
  has(r.baseline, ["id", "score", "umax", "epsmax"], "result.baseline");
  if (!r.ranking.length) fail("result.ranking 비었음", r);
  for (const x of r.ranking) has(x, ["rank", "id", "values", "score", "improvement", "worst_entry_id", "umax", "epsmax", "umax_all", "epsmax_all", "warnings_n"], "ranking[]");
  if (!r.excluded.length) fail("result.excluded 비었음(미리보기 스킵 안이 있어야 함)", r);
  for (const x of r.excluded) has(x, ["id", "status", "code", "values"], "excluded[]");
  if (scenario === "step" && typeof r.noise_floor !== "number") fail("③ noise_floor 없음", r.noise_floor);
  if (scenario === "step" && !r.ranking.every((x) => typeof x.noise === "boolean")) fail("③ ranking[].noise", r.ranking);
  if (r.sensitivity) {
    has(r.sensitivity, ["method", "r2", "params"], "sensitivity");
    for (const q of r.sensitivity.params) has(q, ["name", "src", "spearman"], "sensitivity.params[]");
  }
  has(r.best, ["id", "files"], "result.best");
  if (!r.best.files.length) fail("best.files 비었음", r.best);
  for (const f of r.best.files) {
    if (typeof f !== "object" || typeof f.rel !== "string") fail("best.files[] 형식({rel, size, downloadable})", f);
    has(f, ["rel", "size", "downloadable"], "best.files[]");
  }
  if (!r.view3d.includes("d000") || r.view3d.length < 2) fail("result.view3d", r.view3d);
}

// ---------------------------------------------------------------------------------------------- 시나리오
async function runScenarios(base, inp) {
  const { chromium } = loadPlaywright();
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"] });
  const ctx = await browser.newContext({ viewport: { width: 2560, height: 1440 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  const bad = [];
  const v3d = [];
  const thumbs = [];
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("/esl/api/") && r.status() >= 500) bad.push([r.status(), u]);
    if (/\/doe\/studies\/[^/]+\/view3d\//.test(u)) v3d.push([r.status(), u.replace(/^.*\/esl\/api/, "")]);
    if (/\/preview\/thumb\//.test(u)) thumbs.push([r.status(), u.replace(/^.*\/thumb\//, ""), r.headers()["content-type"]]);
  });
  const api = (p) =>
    page.evaluate(async (u) => {
      const r = await fetch(`/esl/api${u}`);
      return { status: r.status, body: r.headers.get("content-type")?.includes("json") ? await r.json() : null };
    }, p);
  const shot = async (name) => {
    const f = path.join(SHOTS, `${name}.png`);
    await page.screenshot({ path: f });
    log("스크린샷(2560x1440)", f);
    return f;
  };
  const noHScroll = async (where) => {
    const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
    if (o.sw > o.cw + 1) fail(`${where}: 가로 스크롤`, o);
  };
  const waitPhase = async (sid, phases, ms = 300000) => {
    const end = Date.now() + ms;
    let s = null;
    while (Date.now() < end) {
      s = (await api(`/doe/studies/${sid}`)).body;
      if (s && phases.includes(s.phase)) return s;
      if (s?.phase === "FAILED") fail("연구 FAILED", { job: s.job?.failure_code, msg: s.job?.failure_message, steps: s.job?.steps?.map((x) => [x.step_key, x.state, x.failure_code]) });
      await page.waitForTimeout(1000);
    }
    fail(`phase 대기 시간 초과(${phases})`, s?.phase);
  };
  const out = {};

  // ---- 설정
  await page.goto(`${base}/esl/p/${PID}/library`);
  const st = (await api("/doe/settings")).body;
  auditSettings(st);
  if (!st.scenarios.step) fail("③ 비활성(gmsh)", st);
  log("settings OK", JSON.stringify({ paicad: st.paicad, gmsh: st.gmsh, part_title: st.part_title, default_types: st.doe.default_types }));

  async function newStudyFlow(scenario, stepFile) {
    if (scenario === "step") {
      // 라이브러리에서 3개 체크 → [선택한 ESL로 비드 DOE (3)]
      await page.goto(`${base}/esl/p/${PID}/library`);
      const boxes = page.locator('input[type="checkbox"][aria-label$=" 선택"]');
      await boxes.first().waitFor({ timeout: 30000 });
      const n = await boxes.count();
      for (let i = 0; i < n; i++) await boxes.nth(i).check();
      await page.getByRole("button", { name: `선택한 ESL로 비드 DOE (${n})` }).click();
      await page.waitForURL(/\/doe\/new\?entries=/);
      await page.getByText("③ 다른 모델(STEP만)").click();
    } else {
      await page.goto(`${base}/esl/p/${PID}/doe/new?entries=${inp.entry_ids.join(",")}`);
      await page.getByTestId("doe-auto").waitFor();
      if (!/①/.test((await page.getByTestId("doe-auto").textContent()) ?? "")) fail("① 자동 판별 아님");
    }
    await page.locator('input[type="file"]').first().setInputFiles(stepFile);
    await page.getByTestId("doe-check").waitFor({ timeout: 60000 });
    if (scenario === "step") {
      await page.waitForFunction(() => (document.querySelector('input[aria-label="두께 t (mm)"]')?.value ?? "") !== "", null, { timeout: 30000 });
      await page.getByLabel("요소 크기 (mm)").fill("20");
    }
    await page.getByLabel("제목").fill(scenario === "step" ? "E2E ③ STEP 만" : "E2E ① 같은 모델");
    const prep = page.getByRole("button", { name: "입력 준비" });
    await page.waitForFunction(() => {
      const b = [...document.querySelectorAll("button")].find((x) => x.textContent?.trim() === "입력 준비");
      return b && !b.disabled;
    }, null, { timeout: 60000 });
    await prep.click();
    await page.waitForURL(/\/doe\/(?!new)[^/?]+/, { timeout: 30000 });
    const sid = page.url().split("/doe/")[1].split(/[?#]/)[0];
    log(`${scenario} 연구`, sid);
    // 준비 → READY
    const s0 = await waitPhase(sid, ["READY"]);
    auditStudy(s0, false);
    const params = (await api(`/doe/studies/${sid}/params`)).body;
    auditParams(params);
    const plan = (await api(`/doe/studies/${sid}/plan-view`)).body;
    auditPlan(plan, scenario);
    await page.locator('table[aria-label="비드 변수"]').waitFor({ timeout: 60000 });
    // 변수: D1·D2 만, 2.5–6.5, 풀 팩토리얼 3수준(가짜 paicad 규칙 → 충돌·고정·형상 스킵)
    for (const p of params.params) {
      const row = page.getByTestId(`param-${p.name}`);
      const on = row.locator('input[type="checkbox"]');
      const want = p.type === "D" && /_(1|2)$/.test(p.name);
      if ((await on.isChecked()) !== want) await on.setChecked(want);
      if (want) {
        await row.locator('input[type="number"]').nth(0).fill("2.5");
        await row.locator('input[type="number"]').nth(1).fill("6.5");
      }
    }
    await page.getByLabel("DOE 방식").selectOption("fullfact");
    await page.getByLabel("수준").fill("3");
    await page.waitForFunction(() => /실제 10안/.test(document.querySelector('[data-testid="doe-count"]')?.textContent ?? ""), null, { timeout: 20000 });
    await noHScroll(`${scenario} 변수`);
    await page.getByRole("button", { name: "미리보기", exact: true }).first().click();
    const s1 = await waitPhase(sid, ["PREVIEW_READY"]);
    auditStudy(s1, true);
    await page.waitForFunction(() => document.querySelectorAll(".doe-thumb img").length >= 8, null, { timeout: 60000 });
    // 공칭 d000 썸네일 = grid/cells/nominal/thumb.png → GET preview/thumb/d000 200 PNG
    const d000 = await page.evaluate(async (u) => {
      const r = await fetch(u);
      const b = new Uint8Array(await r.arrayBuffer());
      return { status: r.status, type: r.headers.get("content-type"), png: b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47, n: b.length };
    }, `/esl/api/doe/studies/${sid}/preview/thumb/d000`);
    if (d000.status !== 200 || !d000.png) fail("공칭 d000 썸네일", d000);
    const nominalOnDisk = fs.existsSync(path.join(inp.esl_root, "_doe", sid, "doe", String(s1.doe.preview.rev), "grid", "cells", "nominal", "thumb.png"));
    if (!nominalOnDisk) fail("grid/cells/nominal/thumb.png 없음");
    const d000Img = await page.evaluate(() => {
      const im = document.querySelector('[data-testid="thumb-d000"] img');
      return im ? { ok: im.complete && im.naturalWidth > 0, w: im.naturalWidth } : null;
    });
    if (!d000Img?.ok) fail("화면 d000 썸네일 표시", d000Img);
    const pv = s1.doe.preview;
    const skippedBadges = await page.locator(".doe-thumb.skipped").count();
    if (skippedBadges !== pv.skipped.collision + pv.skipped.fixed + pv.skipped.geom) fail("스킵 배지 수", { skippedBadges, skipped: pv.skipped });
    log(`${scenario} 미리보기`, JSON.stringify({ ok: pv.ok, skipped: pv.skipped, cells: pv.cells.length, d000, badges: skippedBadges }));
    const shots = [];
    // 실행 가능(같은 matrix_sha256 미리보기 성공) 상태에서 화면 저장
    await page.waitForFunction(() => {
      const b = [...document.querySelectorAll("button")].find((x) => x.textContent?.trim() === "DOE 실행");
      return b && !b.disabled;
    }, null, { timeout: 30000 });
    if (await page.getByTestId("preview-stale").count()) fail("미리보기 직후 stale 표시");
    await page.evaluate(() => window.scrollTo(0, 0));
    if (scenario === "step") shots.push(await shot("e2e_1_step_params_preview"));
    await page.getByRole("button", { name: "DOE 실행" }).click();
    const s2 = await waitPhase(sid, ["DONE"], 600000);
    auditStudy(s2, true);
    const res = (await api(`/doe/studies/${sid}/results`)).body;
    auditResult(res, scenario);
    await page.locator('table[aria-label="순위표"]').waitFor({ timeout: 60000 });
    await page.getByTestId("sens-r2").waitFor({ timeout: 30000 }).catch(() => undefined);
    // 3D 비교: manifest 경로(/doe/studies/{id}/view3d/{did}/manifest.json) + geometry·values 200
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="v3d-host"][data-phase="ready"]').length >= 2, null, { timeout: 90000 });
    const man = v3d.filter(([, u]) => u.includes(`/doe/studies/${sid}/view3d/`) && u.endsWith("/manifest.json"));
    const files = v3d.filter(([, u]) => u.includes(`/doe/studies/${sid}/view3d/`) && !u.endsWith("/manifest.json"));
    if (man.length < 2 || man.some(([s]) => s !== 200) || !files.length || files.some(([s]) => s !== 200)) fail("view3d 요청", v3d);
    const mf = (await api(`/doe/studies/${sid}/view3d/d000/manifest.json`)).body;
    for (const k of ["geometry_url", "values_url"]) {
      const u = mf?.[k] ?? mf?.files?.[k];
      if (typeof u === "string" && !u.includes(`/doe/studies/${sid}/view3d/d000/`)) fail(`manifest.${k} 경로`, u);
    }
    // 받기: 순위 CSV(다운로드) · best 파일 1개 · zip
    const dlCsv = page.waitForEvent("download", { timeout: 30000 });
    await page.getByTestId("doe-downloads").getByText("순위 CSV").click();
    const csv = await dlCsv;
    const csvPath = path.join(tmp, `ranking_${scenario}.csv`);
    await csv.saveAs(csvPath);
    if (!/^id,|rank/.test(fs.readFileSync(csvPath, "utf8").split("\n")[0])) fail("순위 CSV 머리", fs.readFileSync(csvPath, "utf8").slice(0, 200));
    const geomLinks = page.getByTestId("doe-downloads").locator("a.btn");
    const nLinks = await geomLinks.count();
    const dl1 = page.waitForEvent("download", { timeout: 30000 });
    await geomLinks.first().click();
    const f1 = await dl1;
    const zipBtn = page.getByTestId("doe-downloads").getByRole("button", { name: /zip/ });
    let zipName = null;
    if (await zipBtn.count()) {
      const dlz = page.waitForEvent("download", { timeout: 60000 });
      await zipBtn.first().click();
      zipName = (await dlz).suggestedFilename();
    }
    await noHScroll(`${scenario} 결과`);
    const top = res.ranking[0];
    log(`${scenario} 결과`, JSON.stringify({ n_ok: res.n_ok, skipped: res.n_skipped, failed: res.n_failed, top: [top.id, top.score, top.improvement], noise_floor: res.noise_floor, best: res.best.files.map((f) => f.rel), excluded: res.excluded.map((x) => `${x.id}:${x.status}`), links: nLinks, first: f1.suggestedFilename(), zip: zipName }));
    // 결과 화면 스크린샷 — ⑤ 결과 카드가 보이게
    await page.locator('table[aria-label="순위표"]').scrollIntoViewIfNeeded();
    await page.evaluate(() => {
      const t = document.querySelector('table[aria-label="순위표"]');
      const card = t?.closest("section") ?? t;
      if (card) window.scrollTo(0, Math.max(0, card.getBoundingClientRect().top + window.scrollY - 70));
    });
    await page.waitForTimeout(500);
    shots.push(await shot(scenario === "step" ? "e2e_2_step_result" : "e2e_3_same_result"));
    return { sid, preview: { ok: pv.ok, skipped: pv.skipped }, n_ok: res.n_ok, top: top.id, noise_floor: res.noise_floor, best_files: res.best.files.length, shots };
  }

  try {
    out.step = await newStudyFlow("step", inp.step3);
    out.same = await newStudyFlow("same", inp.step1);
  } catch (e) {
    const f = path.join(tmp, "fail.png");
    await page.screenshot({ path: f, fullPage: true }).catch(() => undefined);
    if (process.env.ESL_E2E_KEEP === "1") log("실패 화면", f);
    log("실패 화면 글", ((await page.locator("main, body").first().textContent().catch(() => "")) ?? "").replace(/\s+/g, " ").slice(0, 1500));
    throw e;
  }

  // 대기열·이력·작업 상세 라벨(작업 종류 3종·단계)
  await page.goto(`${base}/esl/p/${PID}/history`);
  const hist = (await api(`/history?project_id=${PID}&limit=50`)).body;
  const doeItems = (hist.items ?? []).filter((it) => String(it.job_type).startsWith("DOE_"));
  if (doeItems.length < 6) fail("이력 DOE 작업 수", doeItems.map((x) => x.job_type));
  await page.waitForFunction(() => /비드 DOE 실행/.test([...document.querySelectorAll("table td")].map((t) => t.textContent).join(" ")), null, { timeout: 30000 });
  const txt = await page.evaluate(() => [...document.querySelectorAll("table td")].map((t) => t.textContent).join(" | "));
  for (const lb of ["비드 DOE 준비", "비드 DOE 미리보기", "비드 DOE 실행", "③ 다른 모델(STEP만) · 완료", "① 같은 모델 · 완료"]) if (!txt.includes(lb)) fail(`이력 표 ${lb} 없음`, txt.slice(0, 1500));
  const runItem = doeItems.find((x) => x.job_type === "DOE_RUN");
  await page.goto(`${base}/esl/p/${PID}/jobs/${runItem.job_id ?? runItem.id}`);
  await page.getByRole("heading", { name: /작업 상세 — 비드 DOE 실행/ }).waitFor({ timeout: 30000 });
  const rtxt = (await page.locator("body").textContent()) ?? "";
  for (const lb of ["BD_BASELINE", "베이스라인", "안별 해석", "순위·보고서"]) if (!rtxt.includes(lb)) fail(`작업 상세 단계 라벨 ${lb} 없음`);

  if (bad.length) fail("서버 5xx", bad);
  const real = errors.filter((e) => !/WebGL|swiftshader|GPU/i.test(e));
  if (real.length) fail("브라우저 오류", real);
  await browser.close();
  return out;
}

async function main() {
  if (!fs.existsSync(path.join(DIST, "index.html"))) throw new Error("frontend/dist 가 없습니다 — cd frontend && npm run build");
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "esl-e2e-doe-"));
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
  log("입력", JSON.stringify(inp));
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
  // 워커 heartbeat 의 paicad·gmsh 점검 기록 대기(/doe/settings enabled)
  const end = Date.now() + 60000;
  for (;;) {
    const st = await (await fetch(`${base}/esl/api/doe/settings`)).json();
    if (st.enabled && st.scenarios?.step) break;
    if (Date.now() > end) throw new Error(`비드 DOE 활성 대기 시간 초과: ${JSON.stringify(st).slice(0, 400)}`);
    await new Promise((r) => setTimeout(r, 500));
  }
  try {
    const r = await runScenarios(base, inp);
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
      for (const n of ["uvicorn", "worker"]) {
        const f = path.join(tmp, `${n}.log`);
        if (fs.existsSync(f)) console.error(`---- ${n}.log (끝 60줄)\n` + fs.readFileSync(f, "utf8").split("\n").slice(-60).join("\n"));
      }
    }
    await cleanup();
    process.exit(1);
  });
