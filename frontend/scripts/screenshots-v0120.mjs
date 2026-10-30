// v0.12.0 검증 낙하 화면 증적(mock, esl_scx_relay.md §10.2·V-SR-15(B)): 2560×1440 2장 —
//   (1) 검증 낙하 계획 대화상자(안·씬 라디오·N·씬 표·제외된 누적 씬 경고·제출 건수·예상 시간·상한)
//   (2) 검증 낙하 카드(묶음별 씬 진행 칸·SCX 잡 ID + 완료 행의 원 낙하 vs 검증 낙하 비교 표)
// + 1920×1080·2560×1440 에서 가로 스크롤·잘린 카드·표 가로 스크롤 없음, 주 버튼 수(페이지 1 · 대화상자 열림 = 페이지 1 + 모달 1) 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0120.mjs [출력폴더]   (기본 /home/claude/screens/v0120)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0120");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5194;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const STUDY = `${base}/p/p-body/doe/doe-1?freeze=1&mockUser=power&seenVersion=0.12.0`;

let failed = 0;
const check = async (page, w, h, name, wantPrim) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .modal")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap")].filter((t) => t.offsetParent && t.scrollWidth > t.clientWidth + 1).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    const modal = document.querySelector(".modal");
    const modalCut = modal ? modal.getBoundingClientRect().bottom > window.innerHeight + 1 && modal.scrollHeight <= modal.clientHeight : false;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps, prim, modalCut };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.prim === wantPrim && !r.modalCut;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 가로 스크롤 ${r.wraps} · 주 버튼 ${r.prim}/${wantPrim}${r.modalCut ? " · 대화상자 잘림" : ""}`);
  if (!ok) await page.screenshot({ path: path.join(out, `check_${w}_${name.replace(/\s+/g, "_")}.png`), fullPage: true });
};
const dialog = async (page) => {
  await page.goto(STUDY);
  const open = page.getByTestId("vd-open");
  await open.waitFor();
  await page.waitForFunction(() => {
    const b = document.querySelector('[data-testid="vd-open"]');
    return b && !b.disabled;
  });
  await open.click();
  await page.waitForFunction(() => /^제출 \d+건/.test(document.querySelector('[data-testid="vd-summary"]')?.textContent ?? ""));
  await page.getByText("고급 — Radioss 버전·ncpu").click();
  await page.waitForTimeout(300);
};
const card = async (page) => {
  await page.goto(`${STUDY}&demoVerify=1`);
  const c = page.getByTestId("vd-card");
  await c.waitFor();
  await c.getByRole("button", { name: "75QN80H Corner 146" }).click();
  await page.getByRole("table", { name: "원 낙하 대비 검증 낙하" }).waitFor();
  await page.locator(".card", { has: c }).scrollIntoViewIfNeeded();
  await page.evaluate(() => document.querySelector('[data-testid="vd-card"]').closest(".card").scrollIntoView({ block: "end" }));
  await page.waitForTimeout(300);
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

  await dialog(page);
  await page.screenshot({ path: path.join(out, "1_verify_plan_dialog_2560.png") });
  console.log(path.join(out, "1_verify_plan_dialog_2560.png"));
  await card(page);
  await page.screenshot({ path: path.join(out, "2_verify_card_progress_compare_2560.png") });
  console.log(path.join(out, "2_verify_card_progress_compare_2560.png"));

  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    await dialog(page);
    await check(page, w, h, "계획 대화상자", 2);
    await card(page);
    await check(page, w, h, "진행·비교 카드", 1);
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
