// v0.14.0 ④ 형상 직접 비교 화면 증적(mock, esl_step_compare.md §7·V-SC-10): 2장 —
//   (1) 2560×1440 새 강성 평가 스터디 ④ 입력 카드(형상 표 4행 · 기준 라디오 · 이름 · 물성 3칸 · 주 버튼 [입력 준비])
//   (2) 1920×1080 결과(doe-3: 순위표 이름 열 · 실패 형상 · 민감도 숨김 1줄 · 3D 기준 vs 선택 형상)
// + 1920×1080·2560×1440 에서 ④ 입력·준비 결과(doe-4)·결과(doe-3) 화면의 가로 스크롤·잘린 카드·표 잘림 없음, 주 버튼 1개 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0140.mjs [출력폴더]   (기본 /home/claude/screens/v0140)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0140");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5196;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.14.0";
const NEW = `${base}/p/p-body/doe/new?entries=le-1,le-2,le-9&${Q}`;
const READY = `${base}/p/p-body/doe/doe-4?${Q}`;
const DONE = `${base}/p/p-body/doe/doe-3?${Q}`;
const FILES = ["chr_base.step", "chr_rib_A.step", "chr_rib_B.step", "chr_bead_C_long_name_variant_2026.step"];

let failed = 0;
const check = async (page, w, h, name) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    // 표 안 가로 스크롤(순위표·ESL별 표는 설계상 표 안 스크롤 허용 — .scroll) 밖의 표 잘림
    const wraps = [...document.querySelectorAll(".table-wrap:not(.scroll)")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps, prim };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.prim === 1;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 잘림 ${r.wraps} · 주 버튼 ${r.prim}/1`);
  if (!ok) await page.screenshot({ path: path.join(out, `check_${w}_${name.replace(/\s+/g, "_")}.png`), fullPage: true });
};
const openNew = async (page) => {
  await page.goto(NEW);
  await page.getByRole("radio", { name: /④ 형상 직접 비교/ }).check();
  await page.getByLabel(/^비교할 STEP(·메시)? 끌어다 놓기\(여러 개\)$/).setInputFiles(FILES.map((name) => ({ name, mimeType: "application/step", buffer: Buffer.from(`ISO-10303-21;\n${name}\n`.repeat(400)) })));
  await page.getByTestId(`shape-row-${FILES.length}`).waitFor({ timeout: 20000 });
  await page.getByRole("textbox", { name: "형상 1 이름" }).fill("현행");
  await page.getByRole("textbox", { name: "형상 2 이름" }).fill("리브 A안");
  await page.getByTestId("doe-check").waitFor({ timeout: 10000 });
  await page.waitForTimeout(500);
};
const openAt = async (page, url, sel) => {
  await page.goto(url);
  await page.waitForSelector(sel);
  await page.waitForTimeout(600);
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

  await openNew(page);
  await page.screenshot({ path: path.join(out, "1_compare_inputs_2560.png") });
  console.log(path.join(out, "1_compare_inputs_2560.png"));
  await page.setViewportSize({ width: 1920, height: 1080 });
  await openAt(page, DONE, 'table[aria-label="순위표"]');
  await page.screenshot({ path: path.join(out, "2_compare_results_1920.png") });
  console.log(path.join(out, "2_compare_results_1920.png"));

  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    await openNew(page);
    await check(page, w, h, "④ 입력");
    await openAt(page, READY, '[data-testid="prep-shape-d003"]');
    await check(page, w, h, "④ 준비 결과");
    await openAt(page, DONE, 'table[aria-label="순위표"]');
    await check(page, w, h, "④ 결과");
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
