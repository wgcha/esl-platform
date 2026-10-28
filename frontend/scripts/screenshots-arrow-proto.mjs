// 화살표 스타일 시안 검토용(mock): 스타일(current·s1·s2·s3)마다 2560×1440 화살표 100 / 합력 5 + 클로즈업(DPR 2).
// 사용: node scripts/screenshots-arrow-proto.mjs [출력폴더]   (Vite 개발 서버를 mock 모드로 직접 띄운다)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers). 헤드리스 WebGL 은 swiftshader.
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/arrow_proto");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5184;
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
  for (const style of (process.env.STYLES ?? "current,s1,s2,s3").split(",")) {
    for (const dpr of [1, 2]) {
      const ctx = await browser.newContext({ viewport: { width: 2560, height: 1440 }, deviceScaleFactor: dpr });
      const page = await ctx.newPage();
      page.on("pageerror", (e) => console.error("pageerror:", e.message));
      page.on("console", (m) => m.type() === "error" && console.error("console.error:", m.text()));
      await page.addInitScript(() => {
        try {
          localStorage.setItem("esl.statusDrawer", "closed");
        } catch {
          /* 무시 */
        }
      });
      await page.goto(`${base}/p/p-body/c/c-demo/stage/4?freeze=1&arrow=${style}`);
      await page.waitForSelector('[data-testid="v3d-host"][data-phase="ready"]', { timeout: 30000 });
      await page.waitForTimeout(1200);
      const box = await page.getByTestId("v3d-host").boundingBox();
      const clip = { x: box.x + box.width * 0.3, y: box.y + box.height * 0.2, width: 800, height: 520 };
      if (dpr === 1) await page.screenshot({ path: path.join(out, `${style}_arrows100.png`) });
      else await page.screenshot({ path: path.join(out, `${style}_arrows100_closeup.png`), clip });
      const slider = page.getByLabel("화살표 단계");
      await slider.focus();
      for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowRight");
      await page.waitForTimeout(800);
      if (dpr === 1) await page.screenshot({ path: path.join(out, `${style}_cluster5.png`) });
      else await page.screenshot({ path: path.join(out, `${style}_cluster5_closeup.png`), clip });
      await ctx.close();
    }
  }
  console.log("저장:", out);
} finally {
  await browser?.close();
  server.kill();
}
