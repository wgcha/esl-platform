// mock 모드 단계 ①~⑥ 스크린샷. 사용: npm run build:mock && npm run screenshots [-- <출력폴더>]
// Playwright는 설치하지 않고 환경의 것을 쓴다(PLAYWRIGHT_BROWSERS_PATH, 전역 playwright 모듈).
import { createRequire } from "node:module";
import { spawn, execSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

function loadPlaywright() {
  const candidates = [process.env.PLAYWRIGHT_MODULE, "playwright"].filter(Boolean);
  try {
    candidates.push(path.join(execSync("npm root -g").toString().trim(), "playwright"));
  } catch {
    /* 무시 */
  }
  for (const c of candidates) {
    try {
      return require(c);
    } catch {
      /* 다음 */
    }
  }
  throw new Error("playwright 모듈을 찾을 수 없습니다(PLAYWRIGHT_MODULE로 경로 지정).");
}

const { chromium } = loadPlaywright();
const port = 5185;
const out = path.resolve(process.argv[2] ?? path.join(root, "screenshots"));
mkdirSync(out, { recursive: true });

const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
try {
  let exited = null;
  server.on("exit", (c) => (exited = c));
  const deadline = Date.now() + 30000;
  for (;;) {
    if (exited !== null) throw new Error(`preview 종료 ${exited}`);
    try {
      if ((await fetch(`http://127.0.0.1:${port}/esl/`)).ok) break;
    } catch {
      /* 아직 */
    }
    if (Date.now() > deadline) throw new Error("preview 서버 시작 시간 초과");
    await new Promise((r) => setTimeout(r, 300));
  }

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const names = ["input", "tstar", "support", "esl", "validate", "export"];
  for (let n = 1; n <= 6; n++) {
    await page.goto(`http://127.0.0.1:${port}/esl/p/p-body/c/c-demo/stage/${n}?freeze=1&mockUser=power`);
    await page.waitForSelector("button[data-primary]");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    const file = path.join(out, `stage${n}_${names[n - 1]}.png`);
    await page.screenshot({ path: file, fullPage: true });
    console.log(file);
  }
  await browser.close();
} finally {
  server.kill();
}
