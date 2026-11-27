// v0.25.1 F1a 증적(mock): 공용 3D 뷰어 높이 — base(e9745958, 색·범례 변경 전) 빌드 vs 새 빌드, Case ③ 3D 카드와 스터디 결과 3D 줄을 2560×1440·1920×1080 에서 잰다(세로 증가 0 = V-0251-29 의 F1a 몫).
// 스크린샷: 레인보우 기본·범례 클릭 팝오버·차이 대비(없음). 사용: BASE_DIST=<base mock 빌드> NEW_DIST=<새 mock 빌드> node scripts/screenshots-v0251-f1a.mjs [출력폴더]
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
const BASE_DIST = process.env.BASE_DIST ?? "/home/claude/dist-mock-base-0251f1a";
const NEW_DIST = process.env.NEW_DIST ?? "/home/claude/dist-mock-new-0251f1a";
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const serve = (dist, port) => spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const servers = [serve(BASE_DIST, 5691), serve(NEW_DIST, 5692)];
const Q = "freeze=1&mockUser=power&seenVersion=0.24.9";
const caseUrl = (port) => `http://127.0.0.1:${port}/esl/p/p-body/c/c-demo/stage/4?${Q}`;
const studyUrl = (port) => `http://127.0.0.1:${port}/esl/p/p-body/doe/doe-40?demoJig=1&${Q}`;
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
const metrics = (page, study) =>
  page.evaluate((st) => {
    const r = (sel) => document.querySelector(sel)?.getBoundingClientRect();
    const hosts = [...document.querySelectorAll('[data-testid="v3d-host"]')].map((e) => Math.round(e.getBoundingClientRect().height * 100) / 100);
    const cards = [...document.querySelectorAll('[data-testid="v3d-host"]')].map((e) => Math.round((e.closest("section.card")?.getBoundingClientRect().height ?? 0) * 100) / 100);
    return { scrollHeight: document.documentElement.scrollHeight, hosts, cards, row3d: st ? r(".doe-row-3d")?.height ?? null : null, legend: !!document.querySelector('[data-testid="v3d-legend-ov"]') };
  }, study);
let failed = 0;
try {
  await Promise.all([waitUp(5691), waitUp(5692)]);
  const browser = await chromium.launch({ args: ARGS });
  const open = async (url, w, h, need) => {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => console.error("pageerror:", e.message));
    await prime(page);
    await page.goto(url);
    await page.waitForSelector(need, { timeout: 60000 });
    await page.waitForTimeout(2500);
    return { ctx, page };
  };
  for (const [name, urlOf, need, study] of [
    ["Case ③", caseUrl, '[data-testid="v3d-host"][data-phase="ready"]', false],
    ["스터디 결과 3D 줄", studyUrl, '.doe-row-3d [data-testid="v3d-host"][data-phase="ready"]', true],
  ]) {
    for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
      const res = {};
      for (const [k, port] of [["base", 5691], ["new", 5692]]) {
        const { ctx, page } = await open(urlOf(port), w, h, need);
        res[k] = await metrics(page, study);
        if (k === "new" && !study) {
          const suf = w === 2560 ? "2560" : "1920";
          await page.screenshot({ path: path.join(out, `v0251_f1a_${suf}_01_rainbow.png`) });
          await page.getByTestId("v3d-legend-ov").click();
          await page.waitForTimeout(400);
          await page.screenshot({ path: path.join(out, `v0251_f1a_${suf}_02_legend_pop.png`) });
          const after = await metrics(page, study);
          if (after.scrollHeight !== res.new.scrollHeight) {
            failed++;
            console.log(`FAIL 팝오버가 레이아웃을 바꿈 ${res.new.scrollHeight}→${after.scrollHeight}`);
          }
        }
        await ctx.close();
      }
      const same = res.base.scrollHeight === res.new.scrollHeight && JSON.stringify(res.base.hosts) === JSON.stringify(res.new.hosts) && JSON.stringify(res.base.cards) === JSON.stringify(res.new.cards) && res.base.row3d === res.new.row3d;
      if (!same) failed++;
      console.log(`${same ? "OK  " : "FAIL"} ${name} ${w}×${h} scrollHeight ${res.base.scrollHeight}→${res.new.scrollHeight} · 카드 ${res.base.cards}→${res.new.cards} · 3D 칸 ${res.base.hosts}→${res.new.hosts}${study ? ` · 3D 줄 ${res.base.row3d}→${res.new.row3d}` : ""} · 새 빌드 범례 겹침 ${res.new.legend}`);
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
