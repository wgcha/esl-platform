// v0.10.0 메뉴 재구성 화면 증적(mock, esl_menu_restructure.md §8·V-MR-26): 2560×1440 4장 —
//   (1) 최상단 메뉴 + ESL 라이브러리 선택 동작(LEGACY 포함 3개 선택 → 선택 줄)  (2) 케이스 ② t*·지지 요약
//   (3) [내보내기] 창(실행 중 진행)  (4) ④ 검증 등록 거부 사유(FAIL)
// + 1920×1080·2560×1440 에서 가로 스크롤·잘린 카드·표 가로 스크롤 없음, 라이브러리 첫 화면에 필터 + 선택 줄 + 표 8행 이상,
//   내보내기 창이 화면 안, ② 주 버튼이 보이는지 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0100.mjs [출력폴더]   (기본 /home/claude/screens/v0100)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0100");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5191;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.10.0";
const LIB = `${base}/p/p-body/library?${Q}`;
const STEP2 = `${base}/p/p-body/c/c-demo/step/2?${Q}`;
const STEP4_FAIL = `${base}/p/p-body/c/c-demo/step/4?${Q}&demoValidation=FAIL`;
const PICK = ["75QN80H v072 146 선택", "75QN80H v072 14 선택", "85QN80H v072 245 선택"];

let failed = 0;
const check = async (page, w, h, name, extra = async () => ({ ok: true, msg: "" })) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps };
  });
  const x = await extra();
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && x.ok;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 가로 스크롤 ${r.wraps}${x.msg ? ` · ${x.msg}` : ""}`);
  if (!ok) await page.screenshot({ path: path.join(out, `check_${w}_${name.replace(/\s+/g, "_")}.png`), fullPage: true });
};
const pick = async (page) => {
  await page.waitForSelector('table[aria-label="라이브러리 항목"] tbody tr');
  for (const l of PICK) await page.getByRole("checkbox", { name: l }).check();
  await page.waitForSelector('[data-testid="pick-bar"]');
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

  // (1) 최상단 메뉴 + 라이브러리 선택 동작
  await page.goto(LIB);
  await pick(page);
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(out, "1_menu_library_selection_2560.png") });
  console.log(path.join(out, "1_menu_library_selection_2560.png"));

  // (3) 내보내기 창 — 시작 후 작업 몇 걸음 진행(목 tick) → 진행 표
  await page.getByRole("button", { name: /^내보내기 \(3\)$/ }).click();
  await page.getByRole("button", { name: "내보내기 시작" }).click();
  await page.waitForSelector('[data-testid="export-progress"]');
  await page.evaluate(() => {
    const m = window.__eslMock;
    for (let k = 0; k < 4; k++) m.tick();
  });
  await page.waitForTimeout(2600);
  await page.screenshot({ path: path.join(out, "3_export_dialog_2560.png") });
  console.log(path.join(out, "3_export_dialog_2560.png"));

  // (2) 케이스 ② t*·지지 요약
  await page.goto(STEP2);
  await page.waitForSelector('[data-testid="support-checks"]');
  await page.waitForSelector('[data-testid="tstar-marker"]');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(out, "2_step2_tstar_support_2560.png") });
  console.log(path.join(out, "2_step2_tstar_support_2560.png"));

  // (4) ④ 검증 FAIL → 등록 거부 사유
  await page.goto(STEP4_FAIL);
  await page.waitForSelector('[data-testid="reg-block"]');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(out, "4_register_rejected_2560.png") });
  console.log(path.join(out, "4_register_rejected_2560.png"));

  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    // 라이브러리 첫 화면: 필터 + 선택 줄 + 표 8행 이상이 화면 안
    await page.goto(LIB);
    await pick(page);
    await page.waitForTimeout(300);
    await check(page, w, h, "라이브러리(선택)", async () => {
      const v = await page.evaluate(() => {
        const vh = window.innerHeight;
        const bar = document.querySelector('[data-testid="pick-bar"]').getBoundingClientRect();
        const filt = document.querySelector(".filters").getBoundingClientRect();
        const rows = [...document.querySelectorAll('table[aria-label="라이브러리 항목"] tbody tr')].filter((r) => r.getBoundingClientRect().bottom <= vh).length;
        return { rows, bar: bar.bottom <= vh, filt: filt.bottom <= vh };
      });
      return { ok: v.rows >= 8 && v.bar && v.filt, msg: `첫 화면 표 ${v.rows}행 · 선택 줄 ${v.bar ? "보임" : "안 보임"}` };
    });
    // 내보내기 창
    await page.getByRole("button", { name: /^내보내기 \(3\)$/ }).click();
    await page.waitForSelector('[role="dialog"]');
    await check(page, w, h, "내보내기 창", async () => {
      const v = await page.evaluate(() => {
        const r = document.querySelector('[role="dialog"]').getBoundingClientRect();
        return { inside: r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight, w: Math.round(r.width) };
      });
      return { ok: v.inside, msg: `창 폭 ${v.w}px · ${v.inside ? "화면 안" : "잘림"}` };
    });
    // ② t*·지지점: 주 버튼 보임
    await page.goto(STEP2);
    await page.waitForSelector('[data-testid="support-summary"]');
    await page.waitForTimeout(300);
    await check(page, w, h, "② t*·지지점", async () => {
      const v = await page.evaluate(() => {
        const b = document.querySelector("button[data-primary]").getBoundingClientRect();
        return b.top >= 0 && b.bottom <= window.innerHeight;
      });
      return { ok: v, msg: `주 버튼 ${v ? "보임" : "안 보임"}` };
    });
    await page.goto(STEP4_FAIL);
    await page.waitForSelector('[data-testid="reg-block"]');
    await check(page, w, h, "④ 검증(FAIL)");
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
