// v0.17.1 경고 접기 화면 증적(mock ?demoLadder=1): ③ 다른 모델(STEP만) 메싱 뒤 긴 사다리 경고([단계별: …], MESH_FREEFORM·MESH_TRIA_FALLBACK, AUTO_*·BG_*)
//   doe-12 준비 경고 요약 1줄(접힘) → 펼침(첫 긴 항목 펼침 = 높이 고정 스크롤 상자), doe-13 준비 실패 빨간 1줄 → [자세히]
// 1920·2560 각각 4장 + 가로 스크롤·잘린 카드·표 잘림 없음, 주 버튼 1개 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0171.mjs [출력폴더]   (기본 /home/claude/screens/v0171)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0171");
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
const Q = "freeze=1&mockUser=power&seenVersion=0.17.1&demoLadder=1";
const WARN = `${base}/p/p-body/doe/doe-12?${Q}`;
const FAIL = `${base}/p/p-body/doe/doe-13?${Q}`;

let failed = 0;
const check = async (page, w, h, name) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap:not(.scroll)")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps, prim };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.prim === 1;
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
  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    await page.goto(WARN);
    const fold = page.getByTestId("prep-warn");
    await fold.waitFor({ timeout: 20000 });
    await page.waitForTimeout(800);
    await check(page, w, h, "doe-12 경고 접힘");
    await shot(page, `1_warn_collapsed_${w}.png`);
    await fold.getByRole("button", { name: /자세히/ }).click();
    await fold.locator(".msg-fold-entry").first().click();
    await fold.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await check(page, w, h, "doe-12 경고 펼침");
    await shot(page, `2_warn_expanded_${w}.png`);
    await page.goto(FAIL);
    const ban = page.getByTestId("job-fail-banner");
    await ban.waitFor({ timeout: 20000 });
    await page.waitForTimeout(800);
    await check(page, w, h, "doe-13 실패 1줄");
    await shot(page, `3_fail_collapsed_${w}.png`);
    await ban.getByRole("button", { name: "자세히" }).click();
    await page.waitForTimeout(300);
    await check(page, w, h, "doe-13 실패 펼침");
    await shot(page, `4_fail_expanded_${w}.png`);
    await ctx.close();
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
