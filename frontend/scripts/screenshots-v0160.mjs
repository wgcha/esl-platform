// v0.16.0 ④ 메시 옵션 화면 증적(mock, esl_compare_mesh_options.md §8·V-C2-12): 1920·2560 각각 3장 —
//   (1) 형상 표(STEP 3 + rad/inc 묶음 메시 행 1 — 출처 토글 · 주 파일 + include · 파트 ID 자동 채움)
//   (2) 고급 설정 펼침(메시 방식 [자동 | CAD | 재메시] · 실패 시 세분화 허용)
//   (3) 결과(doe-7: 형상 표 '메시 방식' 열 · 순위표·ESL별 표 배지)
// + 같은 화면의 가로 스크롤·잘린 카드·표 잘림 없음, 주 버튼 1개 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0160.mjs [출력폴더]   (기본 /home/claude/screens/v0160)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0160");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5198;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.16.0";
const NEW = `${base}/p/p-body/doe/new?entries=le-1,le-2,le-9&${Q}`;
const DONE = `${base}/p/p-body/doe/doe-7?${Q}`;
const FILES = ["chr_base.step", "chr_rib_A.step", "chr_bead_C_long_name_variant_2026.step", "chr_hm_rev3_0000.rad", "chr_body_shell.inc", "chr_fix_rbe2.inc"];

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
const openNew = async (page) => {
  await page.goto(NEW);
  await page.getByRole("radio", { name: /④ 형상 직접 비교/ }).check();
  await page.getByLabel("비교할 STEP·메시 끌어다 놓기(여러 개)").setInputFiles(FILES.map((name) => ({ name, mimeType: "application/octet-stream", buffer: Buffer.from(`${name}\n`.repeat(400)) })));
  await page.getByTestId("shape-row-4").waitFor({ timeout: 20000 });
  await page.getByRole("textbox", { name: "형상 1 이름" }).fill("현행");
  await page.getByRole("textbox", { name: "형상 2 이름" }).fill("리브 A안");
  await page.getByRole("textbox", { name: "형상 4 이름" }).fill("현행 HM 메시 rev3");
  await page.getByTestId("doe-check").waitFor({ timeout: 10000 });
  await page.waitForFunction(() => document.querySelector('input[aria-label="형상 4 파트 ID"]')?.value === "1001");
  await page.waitForTimeout(400);
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
    await openNew(page);
    await check(page, w, h, "형상 표(STEP·메시 혼합)");
    await shot(page, `1_shapes_mixed_${w}.png`);
    await page.locator('[data-testid="compare-adv"] > summary').click();
    await page.getByRole("radio", { name: "CAD" }).hover();
    await page.getByTestId("compare-adv").scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await check(page, w, h, "고급 설정");
    await shot(page, `2_advanced_${w}.png`);
    await page.goto(DONE);
    await page.waitForSelector('table[aria-label="순위표"]');
    await page.waitForTimeout(800);
    await check(page, w, h, "결과(doe-7)");
    await shot(page, `3_results_${w}.png`, true);
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
