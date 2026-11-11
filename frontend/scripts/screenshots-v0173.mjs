// v0.17.3 형상 보기 통일(PartView) 화면 증적(mock): ① select(doe-5) ⑤ 평면도·3D, ② B 메시 select(doe-14, ?demoMeshSel=1) 경계 층,
// ③ 이전 방식 STEP만(doe-12, ?demoLadder=1) 평면도, 이전 방식 ① 완료(doe-1) 평면도 + 3D(d000), ④ 형상 비교 결과(doe-3), 미리보기 격자 + 안 3D(doe-6), 결과 3D 비교(doe-1).
// 1920·2560 각각 + 가로 스크롤·잘린 카드·주 버튼 1개 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0173.mjs [출력폴더]   (기본 /home/claude/screens/v0173)
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0173");
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
const Q = "freeze=1&mockUser=power&seenVersion=0.17.3&demoLadder=1&demoMeshSel=1";
const url = (id) => `${base}/p/p-body/doe/${id}?${Q}`;

let failed = 0;
const check = async (page, w, h, name) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row, .pv")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap:not(.scroll)")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps, prim };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.prim === 1;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 잘림 ${r.wraps} · 주 버튼 ${r.prim}/1`);
};
const shot = async (page, name) => {
  const p = path.join(out, name);
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

    // ① select ⑤ 평면도 → 3D
    await page.goto(url("doe-5"));
    let pv = page.getByTestId("pv-select");
    await pv.waitFor({ timeout: 20000 });
    await at(page, pv);
    await check(page, w, h, "① select 평면도");
    await shot(page, `1_select_plan_${w}.png`);
    await pv.getByTestId("pv-mode-3d").click();
    await page.getByTestId("pv-select-3d").waitFor();
    await page.waitForTimeout(1500);
    await check(page, w, h, "① select 3D");
    await shot(page, `2_select_3d_${w}.png`);

    // ② B 메시 select — 경계 층·경고 표
    await page.goto(url("doe-14"));
    pv = page.getByTestId("pv-select");
    await pv.waitFor({ timeout: 20000 });
    await at(page, pv);
    await check(page, w, h, "② B 메시 select 평면도");
    await shot(page, `3_meshsel_plan_${w}.png`);

    // ③ 이전 방식 STEP만 — 평면도(준비 단계: 3D 없음)
    await page.goto(url("doe-12"));
    pv = page.getByTestId("pv-legacy");
    await pv.waitFor({ timeout: 20000 });
    await at(page, pv);
    await check(page, w, h, "③ 이전 방식 평면도");
    await shot(page, `4_legacy_step_plan_${w}.png`);

    // 이전 방식 ① 완료 — 평면도 → 3D(d000)
    await page.goto(url("doe-1"));
    pv = page.getByTestId("pv-legacy");
    await pv.waitFor({ timeout: 20000 });
    await pv.getByTestId("pv-mode-3d").waitFor({ timeout: 20000 });
    await at(page, pv);
    await pv.getByTestId("pv-mode-3d").click();
    await page.getByTestId("pv-legacy-3d").waitFor();
    await page.waitForTimeout(1500);
    await check(page, w, h, "이전 방식 ① 3D(d000)");
    await shot(page, `5_legacy_same_3d_${w}.png`);

    // 결과 3D 비교(이전 방식 ①)
    const res = page.getByText("3D 비교", { exact: true }).first();
    await res.waitFor({ timeout: 20000 });
    await at(page, res);
    await page.waitForTimeout(1500);
    await check(page, w, h, "결과 3D 비교");
    await shot(page, `6_result_compare3d_${w}.png`);

    // ④ 형상 비교 결과
    await page.goto(url("doe-3"));
    const c4 = page.getByText("3D 비교", { exact: true }).first();
    await c4.waitFor({ timeout: 20000 });
    await at(page, c4);
    await page.waitForTimeout(1500);
    await check(page, w, h, "④ 형상 비교 결과");
    await shot(page, `7_compare_result_${w}.png`);

    // 미리보기 격자 → 안 3D
    await page.goto(url("doe-6"));
    const thumbs = page.getByRole("list", { name: "미리보기 썸네일" });
    await thumbs.waitFor({ timeout: 20000 });
    await at(page, thumbs);
    await check(page, w, h, "미리보기 격자");
    await shot(page, `8_preview_grid_${w}.png`);
    await page.getByTestId("thumb-d001").click();
    const d3 = page.getByTestId("pv-design");
    await d3.waitFor({ timeout: 20000 });
    await at(page, page.getByRole("region", { name: "안 d001 3D 보기" }));
    await page.waitForTimeout(1500);
    await check(page, w, h, "안 3D");
    await shot(page, `9_preview_design3d_${w}.png`);
    await ctx.close();
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
