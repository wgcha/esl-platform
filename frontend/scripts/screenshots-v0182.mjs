// v0.18.2 ① 그래프 방식(schema 2) 평면도 자료 화면 증적(mock + 코어 응답): doe-10(H6 그래프 seed)에서 [선택 저장] 뒤
// GET …/plan-view 를 코어 plan_data 결과(H6 픽스처 auto seed — esl_beadgraph.md BG-D-46)로 바꿔 ⑤ 평면도에 비드 윤곽·라벨·단 고리,
// 변수 행을 고르면 단면 미니 그림이 나오는지 1920·2560 에서 찍는다. 가로 스크롤·잘린 카드 없음, 비드 윤곽 경로 ≥ 비드 수,
// 단면 그림 있음을 검사. 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0182.mjs <plan.json> [출력폴더]   (기본 /home/claude/screens/v0182)
//   plan.json = python 으로 코어 bead_select.plan_data(H6 그래프 선택) 결과를 쓴 파일
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const planPath = process.argv[2];
if (!planPath) throw new Error("plan.json 경로가 필요합니다");
const plan = readFileSync(path.resolve(planPath), "utf-8");
const out = path.resolve(process.argv[3] ?? "/home/claude/screens/v0182");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5231;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.18.2";

let failed = 0;
const check = async (page, w, h, name, extra) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row, .pv")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
    return { hScroll: de.scrollWidth > de.clientWidth + 1, cut };
  });
  const ok = !r.hScroll && r.cut === 0 && (extra?.ok ?? true);
  if (!ok) failed += 1;
  console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut}${extra ? ` · ${extra.text}` : ""}`);
};
const shot = async (page, name) => {
  const p = path.join(out, name);
  await page.screenshot({ path: p });
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
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"] });
  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    const page = await ctx.newPage();
    await page.goto(`${base}/p/p-body/doe/doe-10?${Q}`);
    await page.getByTestId("bead-b1").waitFor({ timeout: 30000 });
    // mock 은 시작 때 window.fetch 를 목 래퍼로 바꿈(src/mock/install.ts) — 그 위에 plan-view 만 코어 결과로 덮음
    await page.evaluate((body) => {
      const m = window.fetch;
      window.fetch = async (input, init) => {
        const u = typeof input === "string" ? input : input.url;
        if (/\/doe\/studies\/[^/]+\/plan-view(\?|$)/.test(u)) return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
        return m(input, init);
      };
    }, plan);
    await page.locator("button[data-primary]", { hasText: "선택 저장" }).click();
    const pv = page.getByTestId("pv-select");
    await pv.waitFor({ timeout: 30000 });
    await pv.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await page.evaluate(() => window.scrollBy(0, -70));
    await page.waitForTimeout(1200);
    const nPaths = await pv.locator("svg path, svg polygon, svg polyline").count();
    const nLabels = await pv.locator("svg text").count();
    await check(page, w, h, "① 그래프 평면도", { ok: nPaths >= 14 && nLabels >= 14, text: `윤곽·고리 ${nPaths} · 글자 ${nLabels}` });
    await shot(page, `1_graph_plan_${w}.png`);
    const row = page.locator('[data-testid^="param-B3_"]').first();
    await row.click();
    const sec = page.getByTestId("section-mini");
    await sec.waitFor({ timeout: 10000 }).catch(() => undefined);
    await pv.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await page.evaluate(() => window.scrollBy(0, -70));
    await page.waitForTimeout(800);
    const hasSec = (await sec.count()) > 0 && (await sec.locator("path").count()) >= 1;
    await check(page, w, h, "① 그래프 단면(B3)", { ok: hasSec, text: `단면 그림 ${hasSec ? "있음" : "없음"}` });
    await shot(page, `2_graph_section_${w}.png`);
    await ctx.close();
  }
  await browser.close();
} finally {
  server.kill();
}
if (failed) {
  console.error(`실패 ${failed}건`);
  process.exit(1);
}
