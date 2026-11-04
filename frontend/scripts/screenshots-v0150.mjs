// v0.15.0 비드 직접 선택 화면 증적(mock, esl_bead_select.md §11·V-BS-17): 4장 —
//   (1) 2560×1440 doe-5 비드 선택(3D 요소 선택·비드 목록·변수·평면도·단면)  (2) 1920×1080 같은 화면
//   (3) 2560×1440 doe-6 미리보기 격자(범례·품질 실패 배지) + 안 3D 보기      (4) 1920×1080 같은 화면
// + 두 크기에서 새 스터디(직접 선택)·doe-5·doe-6 의 가로 스크롤·잘린 카드·표 잘림 없음, 주 버튼 1개 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0150.mjs [출력폴더]   (기본 /home/claude/screens/v0150)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0150");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5197;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.15.0";
const NEW = `${base}/p/p-body/doe/new?entries=le-1,le-2&${Q}`;
const SEL = `${base}/p/p-body/doe/doe-5?${Q}`;
const PV = `${base}/p/p-body/doe/doe-6?${Q}`;

let failed = 0;
const check = async (page, w, h, name) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    const wraps = [...document.querySelectorAll(".table-wrap:not(.scroll)")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const tools = [...document.querySelectorAll(".bs-tools")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
    const prim = [...document.querySelectorAll("button[data-primary]")].filter((b) => b.offsetParent).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps: wraps + tools, prim };
  });
  const ok = !r.hScroll && r.cut === 0 && r.wraps === 0 && r.prim === 1;
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표·도구 잘림 ${r.wraps} · 주 버튼 ${r.prim}/1`);
  if (!ok) await page.screenshot({ path: path.join(out, `check_${w}_${name.replace(/\s+/g, "_")}.png`), fullPage: true });
};
const openAt = async (page, url, sel) => {
  await page.goto(url);
  await page.waitForSelector(sel, { timeout: 20000 });
  await page.waitForTimeout(1200);
};
const openSel = async (page) => {
  await openAt(page, SEL, '[data-testid="plan-chip-b1"]');
  await page.waitForSelector('[data-testid="bs-host"][data-phase="ready"], [data-testid="bs-unavailable"]', { timeout: 20000 });
  await page.getByTestId("param-B1_W").click();
  await page.waitForTimeout(800);
};
const openPv = async (page) => {
  await openAt(page, PV, '[data-testid="height-legend"]');
  await page.getByTestId("thumb-d002").click();
  await page.waitForSelector('[data-testid="bs-design-host"]', { timeout: 20000 });
  await page.waitForTimeout(1500);
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
  for (const [w, h] of [
    [2560, 1440],
    [1920, 1080],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    await openSel(page);
    const a = path.join(out, `select_${w}.png`);
    await page.screenshot({ path: a, fullPage: true });
    shots.push(a);
    await check(page, w, h, "비드 선택(doe-5)");
    await openPv(page);
    const b = path.join(out, `preview_${w}.png`);
    await page.screenshot({ path: b, fullPage: true });
    shots.push(b);
    await check(page, w, h, "미리보기(doe-6)");
    await page.goto(NEW);
    await page.getByRole("radio", { name: "직접 선택(메시)" }).check();
    await page.getByTestId("doe-check").waitFor({ timeout: 10000 });
    await check(page, w, h, "새 스터디 직접 선택");
  }
  for (const s of shots) console.log(s);
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
