// v0.24.7 DM F1 증적(mock): ① 새 스터디 scrollHeight 증가 ≤ 28 px ② 스터디 화면 ±0(v0.24.7 base 빌드 대조) ③ 복제 창 잘림·가로 스크롤 없음 ④ 스크린샷.
// 사용: BASE_DIST=<base mock 빌드> NEW_DIST=<새 mock 빌드> node scripts/screenshots-v0247-f1.mjs [출력폴더]   (기본 /home/claude/shots)
//   빌드: npx vite build --mode mock --outDir <폴더>
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
const BASE_DIST = process.env.BASE_DIST ?? "/home/claude/dist-mock-base-f1";
const NEW_DIST = process.env.NEW_DIST ?? "/home/claude/dist-mock-new-f1";
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const serve = (dist, port) => spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const servers = [serve(BASE_DIST, 5293), serve(NEW_DIST, 5294)];
const urlOf = (port, route, q = "") => `http://127.0.0.1:${port}/esl/p/p-body/doe/${route}${route.includes("?") ? "&" : "?"}freeze=1&mockUser=power&seenVersion=0.24.7${q}`;
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
const prime = (page) => page.addInitScript(() => { try { localStorage.setItem("esl.statusDrawer", "closed"); } catch { /* 무시 */ } });
const heights = (page) =>
  page.evaluate(() => {
    const wa = document.querySelector(".workarea");
    return { doc: document.documentElement.scrollHeight, wa: wa ? wa.scrollHeight : 0, docW: document.documentElement.scrollWidth, innerW: window.innerWidth };
  });
const settle = async (page, sel) => {
  await page.waitForSelector(sel, { timeout: 30000 });
  await page.waitForTimeout(1200);
};
const SIZES = [[2560, 1440], [1920, 1080]];
const results = [];
const ok = (name, pass, detail) => {
  results.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"} ${name} ${detail ?? ""}`);
};

try {
  await Promise.all([waitUp(5293), waitUp(5294)]);
  const browser = await chromium.launch();
  for (const [w, h] of SIZES) {
    const tag = `${w}`;
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    await prime(page);
    // ① 새 스터디
    const m = {};
    for (const [k, port] of [["base", 5293], ["new", 5294]]) {
      await page.goto(urlOf(port, "new?entries=le-1"));
      await settle(page, '[role="radiogroup"][aria-label="시나리오"]');
      await page.waitForSelector('button:has-text("입력 준비")');
      m[k] = await heights(page);
      if (k === "new") await page.screenshot({ path: path.join(out, `v0247_f1_new_${tag}.png`) });
    }
    const dNew = Math.max(m.new.doc - m.base.doc, m.new.wa - m.base.wa);
    ok(`새 스터디 ${tag} scrollHeight 증가 ≤ 28`, dNew <= 28, `base ${JSON.stringify(m.base)} new ${JSON.stringify(m.new)} Δ${dNew}`);
    const radios = await page.locator('[data-testid="ds-radios"] input[type=radio]').count();
    ok(`새 스터디 ${tag} 라디오 2개`, radios === 2, `n=${radios}`);
    // ② 스터디 화면 ±0 (옛 스터디 — 칩은 같은 줄)
    for (const [route, q, sel] of [["doe-6", "", '[data-testid="ds-chip"]'], ["doe-30", "&demoShape=1", '[data-testid^="param-"]'], ["doe-20", "", '[data-testid="ds-chip"], h1.page-title']]) {
      const mm = {};
      for (const [k, port] of [["base", 5293], ["new", 5294]]) {
        await page.goto(urlOf(port, route, q));
        await page.waitForSelector("h1.page-title", { timeout: 30000 });
        await page.waitForTimeout(2500);
        mm[k] = await heights(page);
      }
      const d = Math.max(Math.abs(mm.new.doc - mm.base.doc), Math.abs(mm.new.wa - mm.base.wa));
      ok(`스터디 화면 ${route} ${tag} ±0`, d === 0, `base ${JSON.stringify(mm.base)} new ${JSON.stringify(mm.new)}`);
      void sel;
    }
    // ③ floor_fixed 변수 표 + 복제 창(새 빌드)
    await page.goto(urlOf(5294, "doe-30", "&demoDepth=1"));
    await page.waitForSelector('button[aria-expanded]', { timeout: 30000 });
    await page.waitForTimeout(1500);
    const c4 = page.getByRole("button", { name: /^④ 변수/ });
    if ((await c4.getAttribute("aria-expanded")) === "false") await c4.click();
    await page.waitForSelector('[data-testid^="dsfb-"]', { state: "visible", timeout: 30000 });
    await page.waitForTimeout(800);
    const tags = await page.evaluate(() => ({
      chip: document.querySelector('[data-testid="ds-chip"]')?.textContent,
      dsfb: document.querySelectorAll('[data-testid^="dsfb-"]').length,
      w1: document.querySelectorAll('[data-testid^="w1-"]').length,
      wna: document.querySelectorAll('[data-testid^="w-na-"]').length,
    }));
    ok(`floor_fixed 표 ${tag}`, tags.chip === "깊이면 폭 유지" && tags.dsfb >= 1 && tags.w1 >= 1 && tags.wna >= 1, JSON.stringify(tags));
    const hd = await heights(page);
    await page.screenshot({ path: path.join(out, `v0247_f1_table_${tag}.png`) });
    await page.locator('[data-testid^="w-na-"]').first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, `v0247_f1_table_wna_${tag}.png`) });
    // 단면 그림(요소 비드 floor_fixed — ds_dD: 입구만 벌어지고 깊이면 폭 그대로)
    await page.goto(urlOf(5294, "doe-5", "&demoDepth=1"));
    await page.waitForSelector('button[aria-expanded]', { timeout: 30000 });
    await page.waitForTimeout(1500);
    for (const re of [/^④ 변수/, /^⑤ 평면도/]) {
      const c = page.getByRole("button", { name: re });
      if ((await c.getAttribute("aria-expanded")) === "false") await c.click();
    }
    await page.waitForSelector('[data-testid="section-mini"]', { state: "visible", timeout: 30000 });
    await page.locator('[data-testid^="param-"]').first().click();
    await page.waitForTimeout(600);
    await page.locator('[data-testid="section-mini"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, `v0247_f1_section_${tag}.png`) });
    ok(`floor_fixed 스터디 ${tag} 가로 스크롤 없음`, hd.docW <= hd.innerW, JSON.stringify(hd));
    // 복제 창
    await page.goto(urlOf(5294, "doe-6", "&demoDepth=1"));
    await settle(page, 'button:has-text("복제")');
    const before = await heights(page);
    await page.click('button:has-text("복제")');
    await page.waitForSelector('[data-testid="clone-window"]');
    await page.screenshot({ path: path.join(out, `v0247_f1_clone_same_${tag}.png`) });
    await page.locator('[data-testid="clone-window"] input[value="floor_fixed"]').check();
    await page.waitForSelector('[data-testid="clone-note"]');
    await page.waitForTimeout(300);
    const geo = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="clone-window"]');
      const r = el.getBoundingClientRect();
      const lines = [...el.children].map((c) => Math.round(c.getBoundingClientRect().height));
      return { l: r.left, r: r.right, t: r.top, b: r.bottom, vw: window.innerWidth, vh: window.innerHeight, inner: el.scrollWidth - el.clientWidth, doc: document.documentElement.scrollWidth - window.innerWidth, h: r.height, lines, rows: el.children.length };
    });
    const after = await heights(page);
    ok(`복제 창 ${tag} 잘림 없음·가로 스크롤 없음·3줄`, geo.l >= 0 && geo.r <= geo.vw && geo.t >= 0 && geo.b <= geo.vh && geo.inner <= 0 && geo.doc <= 0 && geo.rows === 3, JSON.stringify(geo));
    ok(`복제 창 ${tag} 열어도 화면 높이 ±0`, after.doc === before.doc && after.wa === before.wa, `before ${JSON.stringify(before)} after ${JSON.stringify(after)}`);
    await page.screenshot({ path: path.join(out, `v0247_f1_clone_note_${tag}.png`) });
    await ctx.close();
  }
  await browser.close();
} finally {
  for (const s of servers) s.kill();
}
const bad = results.filter((r) => !r.pass);
console.log(bad.length ? `실패 ${bad.length}` : "전부 통과");
process.exit(bad.length ? 1 : 0);
