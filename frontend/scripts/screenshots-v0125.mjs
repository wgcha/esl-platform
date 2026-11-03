// v0.12.5 자유 회전 증적(mock): 2560×1440 ④ 3D 하중 보기 1장 — 위아래로 극점을 넘어 계속 끌어 뒤집힌(아래·뒤에서 본) 시점.
// 사용: node scripts/screenshots-v0125.mjs [출력폴더]   (Vite 개발 서버를 mock 모드로 직접 띄운다)
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0124");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5188;
const server = spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "--mode", "mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
let log = "";
server.stdout.on("data", (d) => (log += d));
server.stderr.on("data", (d) => (log += d));
const base = `http://127.0.0.1:${port}/esl`;

async function waitUp() {
  for (let i = 0; i < 100; i++) {
    try {
      const r = await fetch(`${base}/`);
      if (r.ok) return;
    } catch {
      /* 아직 */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error("vite 서버가 올라오지 않았습니다\n" + log);
}

let browser;
try {
  await waitUp();
  browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"] });
  const ctx = await browser.newContext({ viewport: { width: 2560, height: 1440 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.error("pageerror:", e.message));
  page.on("console", (m) => m.type() === "error" && console.error("console.error:", m.text()));
  await page.addInitScript(() => {
    try {
      localStorage.setItem("esl.statusDrawer", "closed");
      localStorage.removeItem("esl.v3d.projection.v1");
    } catch {
      /* 무시 */
    }
  });
  await page.goto(`${base}/p/p-body/c/c-demo/stage/4?freeze=1`);
  await page.waitForSelector('[data-testid="v3d-host"][data-phase="ready"]', { timeout: 30000 });
  await page.waitForTimeout(1200);
  const box = await page.locator('[data-testid="v3d-host"] canvas').first().boundingBox();
  if (!box) throw new Error("3D 캔버스 없음");
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  // 한 방향(아래로)으로 세 번 연속 끌기: 각 0.2 화면 높이(= 72°) → 합 216°. 등각(앙각 35°)에서 꼭대기(90°)를 넘어
  // 뒤쪽 아래에서 올려다보는 시점까지 끊김 없이 돈다(Orbit 은 꼭대기에서 멈췄음)
  for (let i = 0; i < 3; i++) {
    const dy = box.height * 0.2;
    await page.mouse.move(cx, cy - dy / 2);
    await page.mouse.down();
    for (let k = 1; k <= 12; k++) {
      await page.mouse.move(cx, cy - dy / 2 + (dy * k) / 12);
      await page.waitForTimeout(16);
    }
    await page.mouse.up();
    await page.waitForTimeout(150);
  }
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(out, "01_free_rotate_past_pole.png") });
  console.log("저장:", out);
} finally {
  await browser?.close();
  server.kill();
}
