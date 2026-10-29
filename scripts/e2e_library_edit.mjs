#!/usr/bin/env node
// 실서버 라이브러리 항목 수정 E2E(v0.8.0): 임시 PostgreSQL + uvicorn(backend) + 가짜 대시보드(사용자 4명) + 빌드된 프런트(/esl/)
// 를 띄우고 Playwright(Chromium)로 [수정] → 모델·씬·메모 편집·저장 → 목록·필터·크기 판정 반영, 권한(등록자·관리자·다른 사용자·조회),
// version 충돌(409) 문구, entry.json 불변(DB 덮어쓰기 규칙)을 확인한다. 워커는 띄우지 않는다(계산 없음).
//
// 사용: node scripts/e2e_library_edit.mjs [스크린샷 폴더] [--probe]   (먼저 cd frontend && npm run build)
//   --probe = 수정 행/대화상자의 입력칸만 사용자별로 출력(재현용, 검사 없음)
// env: PG_BIN, PYTHON, PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers), PLAYWRIGHT_MODULE, ESL_E2E_KEEP=1
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
const DIST = path.join(REPO, "frontend", "dist");
const PY = process.env.PYTHON || "python3";
const args = process.argv.slice(2);
const PROBE = args.includes("--probe");
const SHOTS = path.resolve(args.find((a) => !a.startsWith("--")) || path.join(REPO, "work", "ui_library_edit"));
process.env.PLAYWRIGHT_BROWSERS_PATH ||= "/opt/pw-browsers";

const procs = [];
let tmp = null;
let pg = null;
const t0 = Date.now();
const log = (...a) => console.log(`[e2e-lib ${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
const COOKIE = "analysis_canvas_session";

// 가짜 대시보드 사용자(토큰 = 쿠키 값). 프로젝트 p-1: power·power2 = 실행, general = 조회, admin = 전역 관리자
const USERS = {
  "tok-power": { id: "u-power", username: "power", display_name: "김등록", is_global_admin: false, memberships: [{ project_id: "p-1", role: "power" }] },
  "tok-power2": { id: "u-power2", username: "power2", display_name: "이다른", is_global_admin: false, memberships: [{ project_id: "p-1", role: "power" }] },
  "tok-admin": { id: "u-admin", username: "admin", display_name: "관리자", is_global_admin: true, memberships: [] },
  "tok-general": { id: "u-general", username: "general", display_name: "박조회", is_global_admin: false, memberships: [{ project_id: "p-1", role: "general" }] },
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

function startProc(name, cmd, argv, env) {
  const out = fs.openSync(path.join(tmp, `${name}.log`), "a");
  const p = spawn(cmd, argv, { cwd: REPO, env: { ...process.env, ...env }, stdio: ["ignore", out, out] });
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

function startDashboard(port) {
  const srv = http.createServer((req, res) => {
    const tok = (req.headers.authorization || "").replace(/^Bearer\s+/, "").trim();
    const u = USERS[tok];
    const send = (st, body) => {
      res.writeHead(st, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (!u) return send(401, { detail: "인증 필요" });
    if (req.url.startsWith("/api/auth/me")) return send(200, { ...u, account_status: "ACTIVE" });
    if (req.url.startsWith("/api/projects")) return send(200, [{ id: "p-1", name: "포장 낙하", product_name: "TV" }]);
    return send(404, {});
  });
  return new Promise((r) => srv.listen(port, "127.0.0.1", () => r(srv)));
}

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

/** 설정(dashboard 인증 → 가짜 대시보드) + DB 마이그레이션 + Case·ESL 실행·라이브러리 항목 3개(entry.json 포함) */
function setup(dbUrl, dashPort) {
  const code = `
import json, os, sys, uuid, yaml
sys.path[:0] = [${JSON.stringify(path.join(REPO, "backend", "tests"))}]
tmp = ${JSON.stringify(tmp)}
root = os.path.join(tmp, "esl_root"); inputs = os.path.join(tmp, "inputs")
os.makedirs(root); os.makedirs(inputs)
d = yaml.safe_load(open(${JSON.stringify(path.join(REPO, "config", "esl_platform.example.yaml"))}, encoding="utf-8"))
d["profile"] = "dev"
d["auth"]["mode"] = "dashboard"
d["auth"]["dashboard_internal_url"] = "http://127.0.0.1:${dashPort}"
d["library"] = {"config_path": ${JSON.stringify(path.join(REPO, "config", "library.example.yaml"))}}
d["storage"] = {"esl_root": root, "input_roots": [inputs], "spdm_roots": []}
d["worker"]["state_dir"] = os.path.join(tmp, "state")
d["report"] = {"auto": False}
core = yaml.safe_load(open(${JSON.stringify(path.join(REPO, "config", "esl.example.yaml"))}, encoding="utf-8"))
d["core"] = {"settings": core}
p = os.path.join(tmp, "esl_platform.yaml")
yaml.safe_dump(d, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
from alembic import command
from alembic.config import Config
cfg = Config(${JSON.stringify(path.join(REPO, "alembic.ini"))}); cfg.attributes["url"] = ${JSON.stringify(dbUrl)}
command.upgrade(cfg, "head")
from esl_platform.core.config import load_config_dict, opt_settings
lc = load_config_dict(d, environ={}); assert lc.ok, lc.errors()
rv = int(opt_settings(lc.settings)["mode"]["rule_version"])
from sqlalchemy import create_engine, insert, update
from esl_platform.core.db.tables import cases, library_entries
from p2_support import seed_run, seed_entry
eng = create_engine(${JSON.stringify(dbUrl)})
cid = str(uuid.uuid4())
with eng.begin() as c:
    c.execute(insert(cases).values(id=cid, project_id="p-1", folder_name="case_e2e", title="라이브러리 E2E Case",
              rad_path=os.path.join(inputs, "m_0000.rad"), results_dir=inputs, input_fingerprint={}, part_title="CHASSIS",
              created_by="u-power", created_by_name="김등록"))
out = {"config": p, "esl_root": root, "entries": {}}
specs = [("A", "55QX10A", 55, "Corner", "146", "u-power", 1220.0, 700.0, 1),
         ("B", "55QX10A", 55, "Edge", "12", "u-power", 1221.0, 701.0, 2),
         ("C", "65QX10A", 65, "Face", "1", "u-power2", 1430.0, 820.0, 1)]
for key, name, inch, dt_, ori, who, lx, le, sno in specs:
    r = seed_run(eng, cid)
    eid = seed_entry(eng, cid, r["run_id"], esl_root=root, name=name, inch=inch, drop_type=dt_, orient=ori,
                     registered_by=who, scene_no=sno, version="v1")
    names = {"u-power": "김등록", "u-power2": "이다른"}
    dm = {"auto": "dent", "metrics": {}, "user": None, "user_by": None, "user_at": None, "rule_version": rv}
    ej = os.path.join(root, "_library", "entries", eid, "entry.json")
    json.dump({"entry_id": eid, "topo_sha256": ("ab" if key != "C" else "cd") * 32, "deform_mode": dm,
               "model": {"product": name, "inch": inch}, "frame": {"L_xi": lx, "L_eta": le}},
              open(ej, "w", encoding="utf-8"), ensure_ascii=False)
    with eng.begin() as c:
        c.execute(update(library_entries).where(library_entries.c.id == eid).values(
            registered_by_name=names[who],
            summary={"grid": {"nx": 24, "ny": 14}, "frame": {"L_xi": lx, "L_eta": le}}))
    out["entries"][key] = {"id": eid, "entry_json": ej}
print(json.dumps(out))
`;
  const r = spawnSync(PY, ["-c", code], {
    cwd: REPO,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: [path.join(REPO, "backend"), path.join(REPO, "worker"), REPO].join(path.delimiter) },
  });
  if (r.status !== 0) throw new Error(`설정·시드 실패\n${r.stdout}\n${r.stderr}`);
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
  await new Promise((r) => setTimeout(r, 500));
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

const sha = (f) => createHash("sha256").update(fs.readFileSync(f)).digest("hex");
const check = (ok, msg) => {
  if (!ok) throw new Error(`검사 실패: ${msg}`);
  log("확인", msg);
};

// ---------------------------------------------------------------------------------------------- 시나리오
async function asUser(browser, base, token, viewport = { width: 1600, height: 1000 }) {
  const ctx = await browser.newContext({ viewport });
  await ctx.addCookies([{ name: COOKIE, value: token, url: base }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  const reqs = [];
  // 응답이 온 순서대로 본문 파싱 전에 기록(예전엔 await r.json() 뒤 push 라 두 PATCH 의 순서가 뒤바뀔 수 있었음).
  // 본문은 rec.done 이 끝나면 채워짐 — 검사는 last() 로 기다린 뒤 읽는다.
  page.on("response", (r) => {
    if (r.url().includes("/esl/api/library/entries/") && r.request().method() === "PATCH") {
      const rec = { status: r.status(), sent: JSON.parse(r.request().postData() || "null"), body: null, xreq: r.request().headers()["x-esl-request"] };
      reqs.push(rec);
      rec.done = r.json().then(
        (b) => {
          rec.body = b;
        },
        () => {},
      );
    }
  });
  const last = async () => {
    const rec = reqs.at(-1);
    if (rec) await rec.done;
    return rec;
  };
  await page.goto(`${base}/esl/p/p-1/library`);
  await page.getByRole("table", { name: "라이브러리 항목" }).waitFor({ timeout: 20000 });
  return { ctx, page, errors, reqs, last };
}

const rowOf = (page, text) => page.getByRole("table", { name: "라이브러리 항목" }).locator("tbody tr").filter({ hasText: text });

async function probe(browser, base, seed) {
  for (const tok of ["tok-power", "tok-admin", "tok-power2", "tok-general"]) {
    const { ctx, page } = await asUser(browser, base, tok);
    const row = rowOf(page, "Scene 1").filter({ hasText: "55QX10A" }).first();
    const btn = row.getByRole("button", { name: "수정" });
    const dis = await btn.isDisabled();
    const title = await btn.locator("xpath=..").getAttribute("title");
    let fields = [];
    if (!dis) {
      await btn.click();
      const ed = page.locator('[data-testid="edit-row"], [role="dialog"]').first();
      await ed.waitFor();
      fields = await ed.locator("input, select, textarea").evaluateAll((els) =>
        els.map((e) => `${e.getAttribute("aria-label")}${e.disabled ? "(disabled)" : ""}${e.readOnly ? "(readonly)" : ""}`),
      );
      const txt = await ed.innerText();
      log(`[probe ${tok}] 편집 UI 텍스트: ${txt.replace(/\s+/g, " ").slice(0, 200)}`);
    }
    log(`[probe ${tok}] 수정 버튼 disabled=${dis} title=${title} 입력칸=${JSON.stringify(fields)}`);
    await ctx.close();
  }
  // 백엔드 직접: 모델명·인치 PATCH 가 저장되는가, 다른 power 가 남의 항목을 고칠 수 있는가
  const A = seed.entries.A.id;
  const api = async (tok, method, p, body) => {
    const r = await fetch(`${base}/esl/api${p}`, { method, headers: { Cookie: `${COOKIE}=${tok}`, "Content-Type": "application/json", "X-ESL-Request": "1" }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: await r.json().catch(() => null) };
  };
  const e = (await api("tok-power", "GET", `/library/entries/${A}`)).body;
  const r1 = await api("tok-power", "PATCH", `/library/entries/${A}`, { version: e.version, model: { name: "55QX10B", inch: 56 } });
  log(`[probe API] 등록자 PATCH model.name·inch → ${r1.status} name=${r1.body?.model?.name} inch=${r1.body?.model?.inch} size.inch=${r1.body?.size?.inch}`);
  const r2 = await api("tok-power2", "PATCH", `/library/entries/${A}`, { version: r1.body.version, note: "남의 항목" });
  log(`[probe API] 다른 power PATCH note → ${r2.status}`);
  const r3 = await api("tok-power", "PATCH", `/library/entries/${A}`, { version: 1, note: "x" });
  log(`[probe API] 이전 version PATCH → ${r3.status} ${r3.body?.detail?.code}`);
  log(`[probe] entry.json 변경 없음: ${sha(seed.entries.A.entry_json) === seed.entries.A.sha0}`);
}

async function scenario(browser, base, seed) {
  const A = seed.entries.A;
  const B = seed.entries.B;
  const C = seed.entries.C;
  fs.mkdirSync(SHOTS, { recursive: true });

  // 1) 등록자(power): A 의 모델·씬·메모 편집 → 저장
  const u = await asUser(browser, base, "tok-power", { width: 2560, height: 1440 });
  const { page } = u;
  const rowA = () => rowOf(page, "55QX10A").filter({ hasText: "Scene 1" }).filter({ hasText: "146" });
  await rowA().getByRole("button", { name: "수정" }).click();
  const dlg = page.getByRole("dialog", { name: /라이브러리 항목 수정/ });
  await dlg.waitFor();
  const fill = async (label, v) => {
    const el = dlg.getByLabel(label, { exact: true });
    check(!(await el.isDisabled()) && (await el.getAttribute("readonly")) === null, `등록자: '${label}' 편집 가능`);
    await el.fill(v);
  };
  await fill("모델명", "55QX10B");
  await fill("인치", "56");
  await fill("모델 버전", "v2");
  await fill("날짜", "2026-10-29");
  await fill("제품 질량 (kg)", "18.5");
  await fill("프로젝트", "PKG-E2E");
  await fill("시나리오", "STACK");
  await fill("순번", "4");
  await dlg.getByLabel("낙하 유형", { exact: true }).selectOption("Edge");
  await fill("라운드", "R2");
  await fill("씬 번호", "3");
  await fill("orient", "12");
  await fill("접미사", "b");
  await fill("변형", "rib");
  await fill("메모", "E2E 수정 메모");
  // 잘못된 값 → 저장 비활성
  await dlg.getByLabel("인치", { exact: true }).fill("0");
  check(await dlg.getByRole("button", { name: "저장" }).isDisabled(), "인치 0 → 저장 비활성");
  await dlg.getByLabel("인치", { exact: true }).fill("56");
  check(!(await dlg.getByRole("button", { name: "저장" }).isDisabled()), "올바른 값 → 저장 가능");
  fs.mkdirSync(SHOTS, { recursive: true });
  const shot = path.join(SHOTS, "library_edit_dialog.png");
  await page.screenshot({ path: shot });
  log("스크린샷(2560x1440)", shot);
  await dlg.getByRole("button", { name: "저장" }).click();
  await dlg.waitFor({ state: "detached" });
  const rq = await u.last();
  check(rq && rq.status === 200 && rq.xreq === "1", `PATCH 200(X-ESL-Request) — 보낸 값 ${JSON.stringify(rq?.sent)}`);
  check(rq.sent.model.name === "55QX10B" && rq.sent.model.inch === 56 && rq.sent.scene.drop_type === "Edge" && rq.sent.note === "E2E 수정 메모", "요청 본문 = 바꾼 필드");
  check(rq.body.model.name === "55QX10B" && rq.body.size.inch === 56 && rq.body.scene.drop_class === "Edge" && rq.body.scene.scene_no === 3, "응답 = 저장 값(size.inch 56, drop_class Edge)");
  // 목록·필터 반영
  const rowNew = rowOf(page, "55QX10B");
  await rowNew.first().waitFor();
  const txt = await rowNew.first().innerText();
  // v0.10.0 ESL 목록 열(모델·인치/크기·씬·모드·판정·등록·동작) — 제품 질량은 열에서 빠짐(API 로 확인)
  check(/56/.test(txt) && /STACK/.test(txt), `목록 행 반영: ${txt.replace(/\s+/g, " ")}`);
  const massNow = await page.evaluate(async (id) => (await (await fetch(`/esl/api/library/entries/${id}`)).json()).model.product_mass, A.id);
  check(massNow === 18.5, `제품 질량 저장(API) ${massNow}`);
  await page.getByRole("combobox", { name: "모델", exact: true }).selectOption("55QX10B");
  await page.waitForFunction(() => document.querySelectorAll('table[aria-label="라이브러리 항목"] tbody tr').length === 1);
  check(true, "모델 필터 55QX10B → 1행");
  await page.getByRole("button", { name: "필터 지우기" }).click();
  // 크기 판정(v0.10.0: 체크는 자유, 강성 평가·비드 최적화 버튼이 '크기 다름' 사유로 비활성): B(55) 기준 + A(56)
  await rowOf(page, "55QX10A").getByRole("checkbox").check();
  await rowOf(page, "55QX10B").getByRole("checkbox").check();
  const why = page.getByTestId("pick-why");
  await why.waitFor();
  check(/크기 다름/.test((await why.textContent()) ?? ""), "인치 변경 → 크기 판정(같은 크기) 반영 — 선택 줄 비활성 사유");
  check(await page.getByTestId("pick-bar").getByRole("button", { name: "비드 최적화 (2)" }).isDisabled(), "크기 다름 → 비드 최적화 비활성");
  await page.getByRole("button", { name: "선택 해제" }).click();
  // 409: 대화상자 연 뒤 다른 곳에서 먼저 수정 → 저장 시 오류 문구 + 최신 값 불러오기
  await rowOf(page, "55QX10A").getByRole("button", { name: "수정" }).click();
  await dlg.waitFor();
  const cur = await page.evaluate(async (id) => (await (await fetch(`/esl/api/library/entries/${id}`)).json()).version, B.id);
  const bump = await page.evaluate(
    async ([id, v]) => (await fetch(`/esl/api/library/entries/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json", "X-ESL-Request": "1" }, body: JSON.stringify({ version: v, note: "먼저 수정" }) })).status,
    [B.id, cur],
  );
  check(bump === 200, "다른 창에서 B 먼저 수정");
  await dlg.getByLabel("메모", { exact: true }).fill("늦은 수정");
  await dlg.getByRole("button", { name: "저장" }).click();
  await dlg.getByRole("alert").filter({ hasText: "다른 사용자가 먼저 수정" }).waitFor();
  check((await u.last()).status === 409, "이전 version 저장 → 409 + 오류 문구");
  await dlg.getByRole("button", { name: "최신 값 불러오기" }).click();
  await page.waitForFunction(() => (document.querySelector('[role="dialog"] textarea[aria-label="메모"]') || {}).value === "먼저 수정");
  await dlg.getByLabel("메모", { exact: true }).fill("다시 수정");
  await dlg.getByRole("button", { name: "저장" }).click();
  await dlg.waitFor({ state: "detached" });
  check((await u.last()).status === 200, "최신 값 불러온 뒤 저장 200");
  // 남의 항목(C): 등록자 아님 → 수정 비활성 + 사유
  const btnC = rowOf(page, "65QX10A").getByRole("button", { name: "수정" });
  check(await btnC.isDisabled(), "등록자(power) 아닌 C: 수정 비활성");
  check(/등록자|관리자/.test((await btnC.locator("xpath=..").getAttribute("title")) ?? ""), "비활성 사유 툴팁(등록자·관리자)");
  if (u.errors.length) throw new Error("브라우저 오류:\n" + u.errors.join("\n"));
  await u.ctx.close();

  // 2) 다른 사용자(power2): A·B 비활성, 자기 항목 C 가능
  const o = await asUser(browser, base, "tok-power2");
  check(await rowOf(o.page, "55QX10B").getByRole("button", { name: "수정" }).isDisabled(), "다른 사용자: A 수정 비활성");
  await rowOf(o.page, "65QX10A").getByRole("button", { name: "수정" }).click();
  const dlgO = o.page.getByRole("dialog", { name: /라이브러리 항목 수정/ });
  await dlgO.getByLabel("인치", { exact: true }).fill("75");
  await dlgO.getByRole("button", { name: "저장" }).click();
  await dlgO.waitFor({ state: "detached" });
  const lo = await o.last();
  check(lo.status === 200 && lo.body.size.inch === 75, "다른 사용자: 자기 항목 C 인치 저장");
  const forb = await o.page.evaluate(async (id) => {
    const e = await (await fetch(`/esl/api/library/entries/${id}`)).json();
    return (await fetch(`/esl/api/library/entries/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json", "X-ESL-Request": "1" }, body: JSON.stringify({ version: e.version, note: "남의 것" }) })).status;
  }, A.id);
  check(forb === 403, "다른 사용자 API PATCH(남의 항목) → 403");
  await o.ctx.close();

  // 3) 관리자: 남의 항목 A 수정 가능
  const ad = await asUser(browser, base, "tok-admin");
  await rowOf(ad.page, "55QX10B").getByRole("button", { name: "수정" }).click();
  const dlgA = ad.page.getByRole("dialog", { name: /라이브러리 항목 수정/ });
  await dlgA.getByLabel("모델 버전", { exact: true }).fill("v3");
  await dlgA.getByRole("button", { name: "저장" }).click();
  await dlgA.waitFor({ state: "detached" });
  const la = await ad.last();
  check(la.status === 200 && la.body.model.version === "v3", "관리자: 남의 항목 수정 200");
  await ad.ctx.close();

  // 4) 조회 사용자: 비활성 + 권한 사유
  const g = await asUser(browser, base, "tok-general");
  const bg = rowOf(g.page, "55QX10B").getByRole("button", { name: "수정" });
  check(await bg.isDisabled() && /권한/.test((await bg.locator("xpath=..").getAttribute("title")) ?? ""), "조회 사용자: 수정 비활성 + 권한 사유");
  await g.ctx.close();

  // 5) entry.json 불변(사용자 메타는 DB 에만) + 종합분석 대상 필터가 새 메타로
  for (const k of ["A", "B", "C"]) check(sha(seed.entries[k].entry_json) === seed.entries[k].sha0, `entry.json 그대로(${k})`);
  const an = await fetch(`${base}/esl/api/library/analyses`, {
    method: "POST",
    headers: { Cookie: `${COOKIE}=tok-power`, "Content-Type": "application/json", "X-ESL-Request": "1" },
    body: JSON.stringify({ project_id: "p-1", filters: { model: ["55QX10B"], inch: [56] } }),
  });
  const anb = await an.json();
  check(an.status === 201 && anb.n_entries === 1 && anb.entry_ids[0] === A.id, "종합분석 필터(모델 55QX10B·인치 56) → A 1개");
}

async function main() {
  if (!fs.existsSync(path.join(DIST, "index.html"))) throw new Error("frontend/dist 가 없습니다 — cd frontend && npm run build");
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "esl-e2e-lib-"));
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
  const dashPort = await freePort();
  const dash = await startDashboard(dashPort);
  const seed = setup(dbUrl, dashPort);
  for (const k of Object.keys(seed.entries)) seed.entries[k].sha0 = sha(seed.entries[k].entry_json);
  const env = { ESL_PLATFORM_CONFIG: seed.config, ESL_DATABASE_URL: dbUrl, ESL_BIND_HOST: "127.0.0.1", PYTHONPATH: [path.join(REPO, "backend"), path.join(REPO, "worker"), REPO].join(path.delimiter) };
  const apiPort = await freePort();
  startProc("uvicorn", PY, ["-m", "uvicorn", "esl_platform.api.main:app", "--host", "127.0.0.1", "--port", String(apiPort)], env);
  await waitHttp(`http://127.0.0.1:${apiPort}/esl/api/health`);
  const frontPort = await freePort();
  const front = await startFront(frontPort, apiPort);
  const base = `http://127.0.0.1:${frontPort}`;
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  try {
    if (PROBE) await probe(browser, base, seed);
    else await scenario(browser, base, seed);
    log(PROBE ? "probe 끝" : "E2E 성공", "스크린샷:", SHOTS);
  } finally {
    await browser.close();
    front.close();
    dash.close();
  }
}

main()
  .then(async () => {
    await cleanup();
    process.exit(0);
  })
  .catch(async (e) => {
    console.error("E2E 실패:", e?.stack ?? e);
    const f = tmp && path.join(tmp, "uvicorn.log");
    if (f && fs.existsSync(f)) console.error("---- uvicorn.log (끝 40줄)\n" + fs.readFileSync(f, "utf8").split("\n").slice(-40).join("\n"));
    await cleanup();
    process.exit(1);
  });
