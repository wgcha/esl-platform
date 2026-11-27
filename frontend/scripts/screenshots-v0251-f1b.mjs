// v0.25.1 F1b 증적(mock): 스터디 결과 3D 줄 높이 — base(e9745958) 빌드 doe-40 vs 새 빌드 doe-40(옛 결과: 안내 한 줄) · doe-60(씬 선택 칸·씬 요약).
// 3D 바 높이·3D 줄·카드·3D 칸·scrollHeight 를 2560×1440·1920×1080 에서 잰다(증가 0 = V-0251-29 의 F1b 몫). 스크린샷: 씬 선택·C 기여도·차이·개선율 표.
// 사용: BASE_DIST=<base mock 빌드> NEW_DIST=<새 mock 빌드> node scripts/screenshots-v0251-f1b.mjs [출력폴더]
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
const BASE_DIST = process.env.BASE_DIST ?? "/home/claude/dist-mock-base-0251f1a";
const NEW_DIST = process.env.NEW_DIST ?? "/home/claude/dist-mock-new-0251f1b";
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const serve = (dist, port) => spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const servers = [serve(BASE_DIST, 5791), serve(NEW_DIST, 5792)];
const Q = "freeze=1&mockUser=power&seenVersion=0.24.9";
const url = (port, id, demo) => `http://127.0.0.1:${port}/esl/p/p-body/doe/${id}?${demo}=1&${Q}`;
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
const metrics = (page) =>
  page.evaluate(() => {
    const h = (sel) => Math.round((document.querySelector(sel)?.getBoundingClientRect().height ?? -1) * 100) / 100;
    const hosts = [...document.querySelectorAll(".doe-row-3d [data-testid=\"v3d-host\"]")].map((e) => Math.round(e.getBoundingClientRect().height * 100) / 100);
    const cards = [...document.querySelectorAll(".doe-row-3d [data-testid=\"v3d-host\"]")].map((e) => Math.round((e.closest("section.card")?.getBoundingClientRect().height ?? 0) * 100) / 100);
    return { scrollHeight: document.documentElement.scrollHeight, bar: h(".doe-row-3d .doe-compare > .inline-actions"), row3d: h(".doe-row-3d"), hosts, cards };
  });
let failed = 0;
try {
  await Promise.all([waitUp(5791), waitUp(5792)]);
  const browser = await chromium.launch({ args: ARGS });
  const open = async (u, w, h) => {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => console.error("pageerror:", e.message));
    await page.addInitScript(() => { try { localStorage.setItem("esl.statusDrawer", "closed"); } catch { /* 무시 */ } });
    await page.goto(u);
    await page.waitForSelector('.doe-row-3d [data-testid="v3d-host"][data-phase="ready"]', { timeout: 60000 });
    await page.waitForTimeout(2500);
    return { ctx, page };
  };
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    const suf = String(w);
    const res = {};
    for (const [k, port, id, demo] of [["base doe-40", 5791, "doe-40", "demoJig"], ["new doe-40(옛 결과)", 5792, "doe-40", "demoJig"], ["new doe-60(씬)", 5792, "doe-60", "demoScene"]]) {
      const { ctx, page } = await open(url(port, id, demo), w, h);
      res[k] = await metrics(page);
      if (k === "new doe-60(씬)") {
        await page.screenshot({ path: path.join(out, `v0251_f1b_${suf}_01_scene.png`) });
        res.sceneSel = await page.evaluate(() => !!document.querySelector('[data-testid="v3d-scene-select"]'));
        await page.locator('[data-testid="v3d-color"] [data-color=c]').click();
        await page.waitForTimeout(1500);
        res.afterC = await metrics(page);
        await page.screenshot({ path: path.join(out, `v0251_f1b_${suf}_02_c.png`) });
        await page.locator('[data-testid="v3d-color"] [data-color=dc]').click();
        await page.waitForTimeout(1500);
        res.afterDc = await metrics(page);
        await page.screenshot({ path: path.join(out, `v0251_f1b_${suf}_03_dc.png`) });
      }
      if (k === "new doe-40(옛 결과)") await page.screenshot({ path: path.join(out, `v0251_f1b_${suf}_00_old.png`) });
      await ctx.close();
    }
    const base = res["base doe-40"];
    for (const k of ["new doe-40(옛 결과)", "new doe-60(씬)", "afterC", "afterDc"]) {
      const m = res[k];
      const same = m.scrollHeight === base.scrollHeight && m.bar === base.bar && m.row3d === base.row3d && JSON.stringify(m.hosts) === JSON.stringify(base.hosts) && JSON.stringify(m.cards) === JSON.stringify(base.cards);
      if (!same) failed++;
      console.log(`${same ? "OK  " : "FAIL"} ${w}×${h} ${k}: scrollHeight ${base.scrollHeight}→${m.scrollHeight} · 3D 바 ${base.bar}→${m.bar} · 3D 줄 ${base.row3d}→${m.row3d} · 카드 ${base.cards}→${m.cards} · 3D 칸 ${base.hosts}→${m.hosts}`);
    }
  }
  await browser.close();
} catch (e) {
  console.error(e);
  failed++;
} finally {
  for (const s of servers) s.kill();
}
process.exit(failed ? 1 : 0);
