// v0.11.0 SCX 드라이브에서 고르기 화면 증적(mock, esl_scx_relay.md §10.1·V-SR-15(A)): 2560×1440 2장 —
//   (1) 폴더 탐색·선택(rad·h3d 선택 + 엔진·include·상태 자동 표시)  (2) 가져오기 진행(파일별·전체 진행률, 취소)
// + 1920×1080·2560×1440 에서 가로 스크롤·잘린 카드·표 가로 스크롤 없음, 주 버튼 1개 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0110.mjs [출력폴더]   (기본 /home/claude/screens/v0110)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0110");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5193;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const NEW = `${base}/p/p-body/cases/new?freeze=1&mockUser=power&seenVersion=0.11.0&tab=scx`;

let failed = 0;
const check = async (page, w, h, name) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap")].filter((t) => t.offsetParent && t.scrollWidth > t.clientWidth + 1).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps, prim };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.prim === 1;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 가로 스크롤 ${r.wraps} · 주 버튼 ${r.prim}`);
  if (!ok) await page.screenshot({ path: path.join(out, `check_${w}_${name.replace(/\s+/g, "_")}.png`), fullPage: true });
};
const browse = async (page) => {
  await page.goto(NEW);
  await page.evaluate(() => sessionStorage.clear());
  await page.goto(NEW);
  const t = page.getByRole("table", { name: "SCX 드라이브 폴더 목록" });
  await t.getByRole("button", { name: "75QN90/" }).click();
  await t.getByRole("button", { name: "drop_corner_LT/" }).click();
  await t.getByRole("button", { name: "rad 선택" }).click();
  await t.getByRole("button", { name: "h3d 선택" }).click();
  await page.waitForSelector('[data-testid="scx-auto"]');
  await page.waitForTimeout(300);
};
const progress = async (page) => {
  await page.getByTestId("scx-start").click();
  await page.waitForSelector('[data-testid="scx-fetch"]');
  await page.evaluate(() => {
    const m = window.__eslMock;
    for (let k = 0; k < 6; k++) m.tick(); // rad·include 받음 → h3d 50%
  });
  await page.waitForSelector('[data-testid="file-progress"]', { timeout: 8000 });
  await page.waitForSelector('[data-testid="job-progress-label"]', { timeout: 8000 });
  await page.waitForTimeout(400);
};

try {
  for (let i = 0; ; i++) {
    try {
      if ((await fetch(`${base}/`)).ok) break;
    } catch {
      /* 아직 */
    }
    if (i > 100) throw new Error("preview 서버 시작 시간 초과");
    await new Promise((r) => setTimeout(r, 200));
  }
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 2560, height: 1440 } });

  await browse(page);
  await page.screenshot({ path: path.join(out, "1_scx_browse_select_2560.png") });
  console.log(path.join(out, "1_scx_browse_select_2560.png"));
  await progress(page);
  await page.screenshot({ path: path.join(out, "2_scx_fetch_progress_2560.png") });
  console.log(path.join(out, "2_scx_fetch_progress_2560.png"));

  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    await browse(page);
    await check(page, w, h, "탐색·선택");
    await progress(page);
    await check(page, w, h, "가져오기 진행");
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
