// v0.24.6 W-F2 스터디 결과 3행 증적(mock): 2560×1440·1920×1080 스크린샷 + 행·3D 칸 높이 측정.
// 사용: NEW_DIST=<vite build --mode mock --outDir 폴더> node scripts/screenshots-v0246-f2.mjs [출력폴더]
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
const DIST = process.env.NEW_DIST ?? "/tmp/f2_dist";
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs").href);
const srv = spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", DIST, "--port", "5293", "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
for (let i = 0; i < 150; i++) {
  try { if ((await fetch("http://127.0.0.1:5293/esl/")).ok) break; } catch { /* 아직 */ }
  await new Promise((r) => setTimeout(r, 200));
}
const ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"];
const browser = await chromium.launch({ args: ARGS });
try {
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    await page.addInitScript(() => { try { localStorage.setItem("esl.statusDrawer", "closed"); } catch { /* 무시 */ } });
    await page.goto("http://127.0.0.1:5293/esl/p/p-body/doe/doe-40?demoJig=1&freeze=1&mockUser=power&seenVersion=0.24.6", { waitUntil: "load" });
    await page.waitForSelector('[data-testid="doe-result-rows"]', { timeout: 60000 });
    await page.waitForSelector('[data-testid="v3d-host"][data-phase="ready"]', { timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const m = await page.evaluate(() => {
      const box = (sel) => { const e = document.querySelector(sel); return e ? e.getBoundingClientRect() : null; };
      const rows = ["doe-row-3d", "doe-row-tables", "doe-row-sens"].map((t) => { const r = box(`[data-testid=${t}]`); return [t, r ? Math.round(r.height) : null, r ? Math.round(r.width) : null]; });
      const hosts = [...document.querySelectorAll('.doe-row-3d .v3d-host')].map((e) => [Math.round(e.getBoundingClientRect().width), Math.round(e.getBoundingClientRect().height)]);
      const top = document.querySelector(".topbar")?.getBoundingClientRect().height ?? 0;
      return { innerH: innerHeight, topbar: Math.round(top), rows, hosts, scrollHeight: document.documentElement.scrollHeight };
    });
    console.log(w, JSON.stringify(m));
    await page.evaluate(() => document.querySelector('[data-testid=doe-result-rows]')?.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(out, `v0246_f2_${w}.png`) });
    await page.evaluate(() => document.querySelector('[data-testid=doe-row-tables]')?.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(out, `v0246_f2_${w}_rows23.png`) });
    await page.close();
  }
} finally {
  await browser.close();
  srv.kill();
}
