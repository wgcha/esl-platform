// V-OR-18 화면 증적(mock, esl_opt_run.md §10): 2560×1440 3장 — (1) 새 비드 최적화 (2) 비드 금지 영역 평면도 (3) 결과 상세.
// + 1920×1080 에서 가로 스크롤·카드 잘림이 없는지 검사(새 최적화·상세·라이브러리). 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v070.mjs [출력폴더]   (기본 /home/claude/screens/v070)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v070");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5187;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const NEW = `${base}/p/p-body/opt/new?entries=le-1,le-2,le-3&freeze=1&mockUser=power`;
const DETAIL = `${base}/p/p-body/opt/opt-1?freeze=1&mockUser=power`;
const LIB = `${base}/p/p-body/library?freeze=1&mockUser=power`;

let failed = 0;
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

  // (1) 새 비드 최적화 — 저장된 금지 영역 세트를 불러온 뒤
  await page.goto(NEW);
  await page.waitForFunction(() => /불러옴/.test(document.querySelector('[data-testid="keepout-status"]')?.textContent ?? ""));
  await page.waitForSelector('button[data-primary]:not([disabled])');
  await page.screenshot({ path: path.join(out, "opt_new_2560.png"), fullPage: true });
  console.log(path.join(out, "opt_new_2560.png"));

  // (2) 금지 영역 평면도 — 사각형 하나 더 넣고 PCB 를 선택(드래그 후)
  const g = page.locator('[data-testid="ko-rect-0"] rect');
  const bb = await g.boundingBox();
  await page.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2);
  await page.mouse.down();
  await page.mouse.move(bb.x + bb.width / 2 + 60, bb.y + bb.height / 2 - 30, { steps: 5 });
  await page.mouse.up();
  await page.click('button:has-text("＋사각형")');
  await page.locator('section[aria-label="② 비드 금지 영역"]').screenshot({ path: path.join(out, "opt_keepout_2560.png") });
  console.log(path.join(out, "opt_keepout_2560.png"));

  // (3) 결과 상세
  await page.goto(DETAIL);
  await page.waitForSelector('[data-testid="selection-summary"]');
  await page.waitForSelector("img.bead-map");
  await page.screenshot({ path: path.join(out, "opt_detail_2560.png"), fullPage: true });
  console.log(path.join(out, "opt_detail_2560.png"));

  // 1920×1080 · 2560×1440 잘림 검사
  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    for (const [name, url, ready] of [
      ["새 최적화", NEW, '[data-testid="keepout-editor"] svg'],
      ["상세", DETAIL, '[data-testid="selection-summary"]'],
      ["라이브러리", LIB, 'table[aria-label="라이브러리 항목"]'],
    ]) {
      await page.goto(url);
      await page.waitForSelector(ready);
      await page.waitForTimeout(300);
      const r = await page.evaluate(() => {
        const de = document.documentElement;
        const cut = [...document.querySelectorAll(".card")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
        const wraps = [...document.querySelectorAll(".table-wrap")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
        return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps };
      });
      const ok = !r.hScroll && r.cut === 0 && r.wraps === 0;
      if (!ok) failed += 1;
      console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 가로 스크롤 ${r.wraps}`);
    }
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
