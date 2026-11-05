// v0.16.1 select 완화·형상 단순화 화면 증적(mock, esl_select_relax.md §8·V-SR-14·25): 1920·2560 각각 4장 —
//   (1) doe-5 비드 선택(섬 = 밝은 단 색 · 비드 행 "섬 n · 구멍 m" · [체결 구멍 둘레 고정] 체크)
//   (2) doe-6 미리보기(경고 안 ⚠ 배지 · "고정 노드 n개, 최대 x mm 이동" · 체결 위치 어긋남 원인)
//   (3) doe-6 실행 결과(순위 ⚠ · "경고 없는 최상위" 1줄)
//   (4) doe-7 ④ 형상 표(메시 방식 "형상 단순화" · 억제 목록 펼침 · 메시 입력 진단 글자)
// + 같은 화면의 가로 스크롤·잘린 카드·표 잘림 없음, 주 버튼 1개 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0161.mjs [출력폴더]   (기본 /home/claude/screens/v0161)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0161");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5199;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.16.1";
const Q_RUN = "mockUser=power&seenVersion=0.16.1";

let failed = 0;
const check = async (page, w, h, name) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap:not(.scroll)")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps, prim };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.prim <= 1;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 잘림 ${r.wraps} · 주 버튼 ${r.prim}/1`);
};
const shot = async (page, name, full = false) => {
  const p = path.join(out, name);
  await page.screenshot({ path: p, fullPage: full });
  console.log(p);
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
  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    // (1) 비드 선택
    await page.goto(`${base}/p/p-body/doe/doe-5?${Q}`);
    await page.getByTestId("bead-islands-b1").waitFor({ timeout: 20000 });
    await page.getByTestId("bead-b1").scrollIntoViewIfNeeded();
    await page.getByTestId("bead-hold-b1").hover();
    await page.waitForTimeout(800);
    await check(page, w, h, "비드 선택(섬·체결 구멍 둘레 고정)");
    await shot(page, `1_select_islands_${w}.png`);
    // (2) 미리보기 경고 안
    await page.goto(`${base}/p/p-body/doe/doe-6?${Q}`);
    await page.locator('[data-warn*="SELECT_FIXED_MOVED"]').first().waitFor({ timeout: 20000 });
    await page.getByRole("list", { name: "미리보기 썸네일" }).scrollIntoViewIfNeeded();
    await page.waitForTimeout(800);
    await check(page, w, h, "미리보기(경고 안 ⚠)");
    await shot(page, `2_preview_warn_${w}.png`);
    // (3) 실행 → 순위 ⚠ · 경고 없는 최상위(목 작업 진행 = freeze 없음)
    await page.goto(`${base}/p/p-body/doe/doe-6?${Q_RUN}`);
    await page.getByRole("button", { name: "강성 평가 실행" }).click({ timeout: 20000 });
    await page.waitForSelector('table[aria-label="순위표"]', { timeout: 90000 });
    await page.locator('table[aria-label="순위표"]').scrollIntoViewIfNeeded();
    await page.waitForTimeout(800);
    await check(page, w, h, "결과(순위 ⚠)");
    await shot(page, `3_rank_warn_${w}.png`);
    // (4) ④ 형상 단순화
    await page.goto(`${base}/p/p-body/doe/doe-7?${Q}`);
    await page.getByTestId("prep-method-d005").waitFor({ timeout: 20000 });
    await page.getByRole("button", { name: "d005 억제 목록 펼치기" }).click();
    await page.getByTestId("defeat-list-d005").waitFor({ timeout: 10000 });
    await page.getByTestId("prep-method-d005").locator(".badge").hover();
    await page.waitForTimeout(600);
    await check(page, w, h, "④ 형상 표(형상 단순화·억제 목록)");
    await shot(page, `4_compare_defeature_${w}.png`, true);
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
