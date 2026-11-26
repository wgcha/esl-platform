// v0.24.8 F1 증적(mock): ① 결과 화면 높이 ±0(base 커밋 빌드 대조 — ④ 옛 스냅샷, 같은 빌드 안 격자 대조) ② 스크린샷 2560·1920.
// 사용: BASE_DIST=<base mock 빌드> NEW_DIST=<새 mock 빌드> node scripts/screenshots-v0248-f1.mjs [출력폴더]   (기본 /home/claude/shots)
//   빌드: npx vite build --mode mock --outDir <폴더>
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
const BASE_DIST = process.env.BASE_DIST ?? "/home/claude/dist-mock-base-jg";
const NEW_DIST = process.env.NEW_DIST ?? "/home/claude/dist-mock-new-jg";
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const serve = (dist, port) => spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const servers = [serve(BASE_DIST, 5391), serve(NEW_DIST, 5392)];
const urlOf = (port, id, q = "") => `http://127.0.0.1:${port}/esl/p/p-body/doe/${id}?freeze=1&mockUser=power&seenVersion=0.24.7&demoJigGrid=1&demoShape=1&hiddenSources=jig${q}`;
const waitUp = async (port) => {
  for (let i = 0; i < 150; i++) {
    try {
      if ((await fetch(`http://127.0.0.1:${port}/esl/`)).ok) return;
    } catch {
      /* 아직 */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error("preview 서버 시작 시간 초과");
};
const ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"];
const prime = (page) => page.addInitScript(() => { try { localStorage.setItem("esl.statusDrawer", "closed"); } catch { /* 무시 */ } });
const metrics = (page) =>
  page.evaluate(() => {
    const h = (sel) => document.querySelector(sel)?.getBoundingClientRect().height ?? null;
    const rows = document.querySelector('[data-testid="doe-result-rows"]');
    const card = rows?.closest("section.card") ?? rows?.closest(".card");
    const head = card?.firstElementChild;
    return {
      scrollHeight: document.documentElement.scrollHeight,
      cardH: card?.getBoundingClientRect().height ?? null,
      headH: head?.getBoundingClientRect().height ?? null,
      rowsH: rows?.getBoundingClientRect().height ?? null,
      row3d: h('[data-testid="doe-row-3d"]'),
      rowTables: h('[data-testid="doe-row-tables"]'),
      rowSens: h('[data-testid="doe-row-sens"]'),
      cond: h('[data-testid="v3d-cond"]'),
      tabs: !!document.querySelector('[data-testid="doe-load-tab"]'),
    };
  });
const ready = async (page, tab) => {
  await page.waitForSelector('[data-testid="doe-result-rows"]', { timeout: 60000 });
  if (tab) {
    // 2560 = 탭 3개가 펼쳐짐, 1920 = 지그 그룹이 메뉴 1개로 접힘(기존 동작) — 메뉴를 열어 항목을 누른다
    const root = '[data-testid="doe-load-tab"]';
    await page.waitForSelector(`${root} [data-tab]`, { timeout: 45000 });
    const trig = page.locator(`${root} [aria-haspopup=listbox]`);
    if (await trig.count()) {
      await trig.first().click();
      await page.locator(`[data-testid^="doe-load-pop-"] [data-tab=${tab}]`).first().click();
    } else {
      await page.waitForSelector(`${root} [data-tab=${tab}]:not([aria-disabled=true])`, { timeout: 45000 });
      await page.click(`${root} [data-tab=${tab}]`);
    }
  }
  await page.waitForSelector('[data-testid="v3d-host"][data-phase="ready"]', { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(1500);
};
const sameKeys = ["scrollHeight", "cardH", "headH", "rowsH", "row3d", "rowTables", "rowSens"];
const ctxOpts = (w, h) => ({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });

let failed = 0;
try {
  await Promise.all([waitUp(5391), waitUp(5392)]);
  const browser = await chromium.launch({ args: ARGS });
  const measure = async (port, id, w, h, tab = null, shot = null) => {
    const ctx = await browser.newContext(ctxOpts(w, h));
    const page = await ctx.newPage();
    page.on("pageerror", (e) => console.error("pageerror:", e.message));
    await prime(page);
    await page.goto(urlOf(port, id));
    await ready(page, tab);
    const m = await metrics(page);
    if (shot) await page.screenshot({ path: path.join(out, shot) });
    await ctx.close();
    return m;
  };
  const cmp = (a, b) => sameKeys.every((k) => a[k] === b[k]);
  const fmt = (m) => sameKeys.map((k) => `${k}=${m[k]}`).join(" ");
  console.log("== ① 높이 — base(f0718dd9) 빌드 vs 새 빌드, ④ 옛 스냅샷(doe-20·doe-31)");
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    for (const id of ["doe-20", "doe-31"]) {
      const a = await measure(5391, id, w, h);
      const b = await measure(5392, id, w, h);
      const ok = cmp(a, b);
      if (!ok) failed++;
      console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${id}\n   base ${fmt(a)}\n   new  ${fmt(b)}`);
    }
  }
  console.log("== ① 높이 — 새 빌드 격자(doe-60) vs 같은 자료 transfer·grid 없음(doe-61, jd 탭)");
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    const a = await measure(5392, "doe-61", w, h, "jig_disp");
    const b = await measure(5392, "doe-60", w, h, "jig_disp");
    const ok = cmp(a, b) && a.cond === b.cond;
    if (!ok) failed++;
    console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} jd 탭 (조건 줄 ${a.cond}→${b.cond})\n   plain ${fmt(a)}\n   grid  ${fmt(b)}`);
  }
  console.log("== ② 스크린샷");
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    const suf = w === 2560 ? "2560" : "1920";
    for (const [tab, name] of [["jig_disp", "jd"], ["jig_spring", "js"]]) {
      const m = await measure(5392, "doe-60", w, h, tab, `v0248_f1_grid_${name}_${suf}.png`);
      console.log(`v0248_f1_grid_${name}_${suf}.png tabs=${m.tabs} scrollHeight=${m.scrollHeight}`);
    }
    await measure(5391, "doe-20", w, h, null, `v0248_f1_base_compare_${suf}.png`);
    await measure(5392, "doe-20", w, h, null, `v0248_f1_old_compare_${suf}.png`);
  }
  await browser.close();
} finally {
  for (const s of servers) s.kill();
}
console.log(failed ? `FAIL ${failed}` : "OK 전부");
process.exit(failed ? 1 : 0);
