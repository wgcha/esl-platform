// v0.13.0 일괄 실행 화면 증적(mock, esl_run_all.md §9·V-RA-16): 2장 —
//   (1) 2560×1440 Case 화면 일괄 실행 중(① 강조 · 진행 줄 '일괄 실행 중 — ① 입력' · [일괄 취소] · 단계 주 버튼 RUN_ALL_ACTIVE 비활성)
//   (2) 1920×1080 ② 에서 멈춤(t* 확인 필요 사유 · [그 단계로 가기] · 주 버튼 [이어서 실행])
// + 1920×1080·2560×1440 에서 진행 중·멈춤·PASS·새 Case 화면의 가로 스크롤·잘린 카드·진행 줄/단계 이름/Case 메뉴 잘림 없음, 주 버튼 1개 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0130.mjs [출력폴더]   (기본 /home/claude/screens/v0130)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0130");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5195;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.13.0";
const caseUrl = (step, demo) => `${base}/p/p-body/c/c-new/step/${step}?${Q}&demoRunAll=${demo}`;

let failed = 0;
const check = async (page, w, h, name) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const over = (el) => el && el.offsetParent && el.scrollWidth > el.clientWidth + 1;
    const outside = (el) => el && el.getBoundingClientRect().right > de.clientWidth + 1;
    const cut = [...document.querySelectorAll(".card, .run-all-bar, .case-menu > *")].filter(outside).length;
    const names = [...document.querySelectorAll(".step-name")].filter(over).length;
    const barText = [...document.querySelectorAll(".run-all-text")].filter(over).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, names, barText, prim };
  });
  const ok = !r.hScroll && r.cut === 0 && r.names === 0 && r.barText === 0 && r.prim === 1;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 요소 ${r.cut} · 단계 이름 잘림 ${r.names} · 진행 줄 잘림 ${r.barText} · 주 버튼 ${r.prim}/1`);
  if (!ok) await page.screenshot({ path: path.join(out, `check_${w}_${name.replace(/\s+/g, "_")}.png`), fullPage: true });
};
const open = async (page, url, want) => {
  await page.goto(url);
  await page.getByTestId("run-all-bar").waitFor();
  await page.waitForFunction((s) => document.querySelector('[data-testid="run-all-bar"]')?.getAttribute("data-status") === s, want);
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

  await open(page, caseUrl(1, "running"), "RUNNING");
  await page.screenshot({ path: path.join(out, "1_run_all_running_2560.png") });
  console.log(path.join(out, "1_run_all_running_2560.png"));
  await page.setViewportSize({ width: 1920, height: 1080 });
  await open(page, caseUrl(2, "tstar"), "STOPPED");
  await page.screenshot({ path: path.join(out, "2_run_all_stopped_tstar_1920.png") });
  console.log(path.join(out, "2_run_all_stopped_tstar_1920.png"));

  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    await open(page, caseUrl(1, "running"), "RUNNING");
    await check(page, w, h, "진행 중");
    await open(page, caseUrl(2, "tstar"), "STOPPED");
    await check(page, w, h, "② 멈춤");
    await open(page, caseUrl(2, "blocked"), "STOPPED");
    await check(page, w, h, "② 지지 BLOCKED");
    await open(page, caseUrl(3, "failed"), "STOPPED");
    await check(page, w, h, "③ 실패");
    await open(page, caseUrl(4, "done"), "DONE");
    await check(page, w, h, "④ PASS");
    await page.goto(`${base}/p/p-body/cases/new?${Q}`);
    await page.getByTestId("run-all-check").waitFor();
    await page.waitForTimeout(300);
    await check(page, w, h, "새 Case 체크박스");
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
