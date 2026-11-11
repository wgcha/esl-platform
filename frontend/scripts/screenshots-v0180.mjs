// v0.18.0 ③ STEP 기준 select(esl_step_graph.md V-SG-8) 화면 증적(mock, ?demoStepSel=1): 새 ③ 입력(STEP·인치·쉘 물성·메시 방식),
// doe-15 선택 화면 요약(고정 이전·평가 영역) + ⑤ 평면도(주 시트 영역·A 이전 고정), doe-16 삼각형 경고·구멍 스냅, doe-17 이전 방식 ③, 스터디 목록.
// 1920·2560 각각 + 가로 스크롤·잘린 카드·주 버튼 1개 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0180.mjs [출력폴더]   (기본 /home/claude/screens/v0180)
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0180");
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
const Q = "freeze=1&mockUser=power&seenVersion=0.18.0&demoStepSel=1";
const url = (id) => `${base}/p/p-body/doe/${id}?${Q}`;

let failed = 0;
/** prim = 기대 주 버튼 수(목록 화면은 0 — 주 버튼은 스터디 화면 머리에만) */
const check = async (page, w, h, name, prim = 1) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row, .pv")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap:not(.scroll)")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps, prim };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.prim === prim;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 잘림 ${r.wraps} · 주 버튼 ${r.prim}/${prim}`);
};
/** 파일 이름 앞붙이(통합 빌드 = SHOT_PREFIX=int_) */
const prefix = process.env.SHOT_PREFIX ?? "";
const shot = async (page, name) => {
  const p = path.join(out, prefix + name);
  await page.screenshot({ path: p });
  console.log(p);
};
/** 요소를 화면 위쪽에 두고 찍기 */
const at = async (page, loc) => {
  await loc.evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.evaluate(() => window.scrollBy(0, -70));
  await page.waitForTimeout(500);
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
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"] });
  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await ctx.newPage();

    // 새 ③: STEP 올림 → 쉘 물성 기본값·메시 방식(고급, 펼침)
    await page.goto(`${base}/p/p-body/doe/new?entries=le-1,le-9&${Q}`);
    await page.getByTestId("doe-step-drop").waitFor({ timeout: 20000 });
    await page.locator('input[aria-label="Ch/R 중립면 STEP 끌어다 놓기"]').setInputFiles({ name: "QN80J_chassis_rear_mid.step", mimeType: "application/octet-stream", buffer: Buffer.alloc(4096) });
    await page.getByTestId("doe-check").waitFor({ timeout: 20000 });
    await page.getByRole("spinbutton", { name: "인치" }).fill("75");
    await page.getByTestId("compare-adv").locator("summary").click();
    await page.waitForTimeout(800);
    await check(page, w, h, "새 ③ 입력");
    await shot(page, `1_new_step_${w}.png`);

    // doe-15 선택 화면 요약(펼침)
    await page.goto(url("doe-15"));
    const info = page.getByTestId("bs-step-info");
    await info.waitFor({ timeout: 20000 });
    await info.getByTestId("bs-step-xfer").locator("button").first().click();
    await at(page, page.getByRole("heading", { name: "② 비드 선택" }).or(info).first());
    await page.waitForTimeout(1500);
    await check(page, w, h, "doe-15 선택 화면");
    await shot(page, `2_step_select_${w}.png`);

    // doe-15 ⑤ 평면도: 주 시트 영역·A 이전 고정
    const pv = page.getByTestId("pv-select");
    await pv.waitFor({ timeout: 20000 });
    await at(page, pv);
    await check(page, w, h, "doe-15 ⑤ 평면도");
    await shot(page, `3_step_plan_${w}.png`);

    // doe-16 삼각형 경고·구멍 스냅
    await page.goto(url("doe-16"));
    const info16 = page.getByTestId("bs-step-info");
    await info16.waitFor({ timeout: 20000 });
    await info16.getByTestId("bs-step-tria").locator("button").first().click();
    await info16.getByTestId("bs-step-xfer").locator("button").first().click();
    await page.waitForTimeout(1500);
    await check(page, w, h, "doe-16 삼각형 · 구멍 스냅");
    await shot(page, `4_step_tria_${w}.png`);

    // doe-17 이전 방식 ③
    await page.goto(url("doe-17"));
    await page.getByTestId("doe-legacy").waitFor({ timeout: 20000 });
    await page.waitForTimeout(800);
    await check(page, w, h, "이전 방식 ③");
    await shot(page, `5_legacy_step_${w}.png`);

    // 스터디 목록
    await page.goto(`${base}/p/p-body/library?tab=study&${Q}`);
    await page.getByText("QN80J Ch/R 비드 — STEP 그래프(자동)").first().waitFor({ timeout: 20000 });
    await page.waitForTimeout(500);
    await check(page, w, h, "스터디 목록", 0);
    await shot(page, `6_study_list_${w}.png`);
    await ctx.close();
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
