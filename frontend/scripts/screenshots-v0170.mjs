// v0.17.0 BEADGRAPH 화면 증적(mock, esl_beadgraph.md §6.2·V-BG-17): 2560·1920 각각 —
//   (1) doe-10 그래프 seed 목록(⑂ 비드·세그먼트 수·미저장 배지) + 3D 세그먼트 색
//   (2) doe-10 트리 보기(바닥 위계·접합 구역·섬 묶음) + 트리 행 강조 ↔ 3D 노랑
//   (3) doe-10 3D 색 = 단계(tier) + 대칭 묶기 제안 펼침
//   (4) doe-11 GRAPH_FAILED 띠 + 칠하기 비드
//   (5) 새 스터디 ① 자동 탐지 — STEP 선택(없어도 입력 검사)
// + 가로 스크롤·잘린 카드·표 잘림 없음, 주 버튼 ≤ 1 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0170.mjs [출력폴더]   (기본 /home/claude/screens/v0170)
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0170");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5217;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.17.0";

let failed = 0;
const check = async (page, w, h, name) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap:not(.scroll)")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    const tree = document.querySelector('[data-testid="sg-tree"]');
    const treeCut = tree ? tree.scrollWidth > tree.clientWidth + 1 : false;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps, prim, treeCut };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.prim <= 1 && !r.treeCut;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 잘림 ${r.wraps} · 트리 잘림 ${r.treeCut ? "있음" : "없음"} · 주 버튼 ${r.prim}/1`);
};
const shot = async (page, name) => {
  const p = path.join(out, name);
  await page.screenshot({ path: p });
  console.log(p);
};
const toSelect = async (page) => {
  await page.getByTestId("bs-host").scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -70));
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
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const page = await browser.newPage({ viewport: { width: 2560, height: 1440 } });
  for (const [w, h] of [
    [2560, 1440],
    [1920, 1080],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    // (1) 그래프 seed 목록
    await page.goto(`${base}/p/p-body/doe/doe-10?${Q}`);
    await page.getByTestId("bead-b1").waitFor({ timeout: 30000 });
    await page.locator('[data-testid="bs-host"][data-phase="ready"]').waitFor({ timeout: 30000 }).catch(() => undefined);
    await toSelect(page);
    await page.waitForTimeout(1200);
    await check(page, w, h, "그래프 seed 목록");
    await shot(page, `ui_1_seed_list_${w}.png`);
    // (2) 트리 + 강조
    await page.getByTestId("bs-view-tree").click();
    await page.getByTestId("sg-tree").waitFor();
    const ch = page.locator('[data-testid^="sg-seg-"]', { hasText: "채널" }).first();
    await ch.click();
    await page.locator('[data-testid^="sg-islgrp-"]').first().click();
    await toSelect(page);
    await page.waitForTimeout(1000);
    await check(page, w, h, "세그먼트 트리 + 강조");
    await shot(page, `ui_2_tree_highlight_${w}.png`);
    // (3) tier 색 + 대칭 묶기 제안
    await page.getByTestId("bs-color-mode").selectOption("tier");
    await page.getByTestId("sg-sym").click();
    await page.getByTestId("sg-sym-list").waitFor();
    await toSelect(page);
    await page.waitForTimeout(1000);
    await check(page, w, h, "tier 색 + 대칭 묶기 제안");
    await shot(page, `ui_3_tier_sym_${w}.png`);
    // (4) GRAPH_FAILED
    await page.goto(`${base}/p/p-body/doe/doe-11?${Q}`);
    await page.getByTestId("bs-graph-failed").waitFor({ timeout: 30000 });
    await page.getByTestId("bs-add-bead").click();
    await page.getByTestId("bs-graph-failed").scrollIntoViewIfNeeded();
    await page.evaluate(() => window.scrollBy(0, -120));
    await page.waitForTimeout(1200);
    await check(page, w, h, "GRAPH_FAILED 띠 + 칠하기 비드");
    await shot(page, `ui_4_graph_failed_${w}.png`);
    // (5) 새 스터디 ① 자동 탐지 — STEP 선택
    await page.goto(`${base}/p/p-body/doe/new?entries=le-1,le-2,le-3&${Q}`);
    await page.getByRole("radio", { name: /^자동 탐지$/ }).check();
    await page.getByTestId("doe-check").waitFor({ timeout: 20000 });
    await page.waitForTimeout(600);
    await check(page, w, h, "새 스터디 ① 자동 탐지(STEP 선택)");
    await shot(page, `ui_5_new_auto_nostep_${w}.png`);
  }
  await browser.close();
} finally {
  server.kill();
}
if (failed) {
  console.error(`실패 ${failed}건`);
  process.exit(1);
}
