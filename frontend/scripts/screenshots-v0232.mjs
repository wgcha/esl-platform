// v0.23.2 화면 증적(mock, 2560×1440): 지그 칩(계산됨·미계산) · 3D 비교 조건 줄(지그 하중 / 전 노드 ESL 토글).
// 사용: npm run build:mock && node scripts/screenshots-v0232.mjs [출력폴더]
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);
const port = 5243;
const server = spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.23.2&demoJig=1";
try {
  for (let i = 0; ; i++) {
    try { if ((await fetch(`${base}/`)).ok) break; } catch { /* 아직 */ }
    if (i > 100) throw new Error("preview 서버 시작 시간 초과");
    await new Promise((r) => setTimeout(r, 200));
  }
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"] });
  const ctx = await browser.newContext({ viewport: { width: 2560, height: 1440 } });
  const page = await ctx.newPage();
  const go = async (id, name, fn) => {
    await page.goto(`${base}/p/p-body/doe/${id}?${Q}`);
    await page.getByTestId("jig-line").first().waitFor();
    await page.waitForTimeout(2500);
    if (fn) await fn();
    const chip = (await page.getByTestId("jig-line").first().textContent())?.trim();
    const cond = (await page.getByTestId("v3d-cond").first().textContent().catch(() => ""))?.trim();
    await page.screenshot({ path: path.join(out, name) });
    console.log(`${name}: 칩 "${chip}" · 3D "${cond}"`);
  };
  await go("doe-40", "v0232_jig_ok_doe40_jigmode.png");
  await go("doe-40", "v0232_jig_ok_doe40_eslmode.png", async () => { await page.getByTestId("v3d-mode").getByRole("button", { name: "전 노드 ESL" }).click(); await page.waitForTimeout(2000); });
  await go("doe-21", "v0232_not_computed_doe21.png");
  await go("doe-42", "v0232_fallback_doe42.png");
  await browser.close();
} finally {
  server.kill();
}
