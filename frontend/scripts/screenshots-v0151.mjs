// v0.15.1 증적(mock): 2560×1440·1920×1080 각각 —
//   select_<w>.png      doe-5 비드 선택(시점 툴바 Z 보기·지우개·층 비우기) + 저장 후 변수 표·평면도
//   preview_fixed_<w>.png doe-6 고정 침범 안 3D(빨간 점·원인 줄)
// + 가로 스크롤·잘린 카드·도구 줄 잘림·주 버튼 1개·시점 툴바가 3D 칸 안 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0151.mjs [출력폴더]   (기본 /home/claude/screens/v0151)
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0151");
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
const Q = "freeze=1&mockUser=power&seenVersion=0.15.1";
const SEL = `${base}/p/p-body/doe/doe-5?${Q}`;

let failed = 0;
const check = async (page, w, h, name, wantPrimary = 1) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap:not(.scroll)")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const tools = [...document.querySelectorAll(".bs-tools, .v3d-view-bar")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const bars = [...document.querySelectorAll(".v3d-view-bar")].filter((b) => {
      const st = b.closest(".v3d-stage")?.getBoundingClientRect();
      const r = b.getBoundingClientRect();
      return !st || r.left < st.left - 0.5 || r.right > st.right + 0.5 || r.top < st.top - 0.5 || r.bottom > st.bottom + 0.5;
    }).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps: wraps + tools, bars, prim };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.bars === 0 && r.prim === wantPrimary;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표·도구 잘림 ${r.wraps} · 시점 툴바 밖 ${r.bars} · 주 버튼 ${r.prim}/${wantPrimary}`);
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
  const shots = [];
  const shot = async (name) => {
    const p = path.join(out, name);
    await page.screenshot({ path: p, fullPage: true });
    shots.push(p);
  };
  for (const [w, h] of [
    [2560, 1440],
    [1920, 1080],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    // 1) 비드 선택 + 시점 툴바 + 저장된 선택의 변수 표
    await page.goto(SEL);
    await page.waitForSelector('[data-testid="param-B1_D1"]', { timeout: 20000 });
    await page.waitForSelector('[data-testid="bs-host"][data-phase="ready"]', { timeout: 20000 });
    await page.getByRole("button", { name: "Z 보기" }).first().click();
    await page.waitForTimeout(400);
    await page.getByRole("button", { name: "선택 영역에 맞추기" }).first().click();
    await page.getByTestId("param-B1_W").click();
    await page.waitForTimeout(1000);
    await shot(`select_${w}.png`);
    await check(page, w, h, "비드 선택·변수 표(doe-5)");
    // 2) 고정 침범 안 3D(빨간 점·원인 줄)
    await page.goto(`${base}/p/p-body/doe/doe-6?${Q}`);
    await page.waitForSelector('[data-testid="height-legend"]', { timeout: 20000 });
    await page.locator('[data-status="SKIPPED_FIXED"]').first().click();
    await page.waitForSelector('[data-testid="bs-design-host"][data-phase="ready"]', { timeout: 20000 });
    await page.getByTestId("design-fixed-viol").waitFor({ timeout: 10000 });
    await page.waitForTimeout(1500);
    await page.getByTestId("design-fixed-viol").scrollIntoViewIfNeeded();
    const pf = path.join(out, `preview_fixed_${w}.png`);
    await page.screenshot({ path: pf });
    shots.push(pf);
    await check(page, w, h, "고정 침범 안 3D(doe-6)");
  }
  for (const s of shots) console.log(s);
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
