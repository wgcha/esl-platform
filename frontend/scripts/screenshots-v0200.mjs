// v0.20.0 ④ 하중 전달 화면 증적(mock): ④ 고급 설정(하중 전달 select) · 결과 진단(요약 1줄 + 접힘 표) · 3D 비교(같은 ESL 이름)를 1920·2560 에서 찍는다.
// 가로 스크롤·잘린 카드 없음을 검사, 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v0200.mjs [출력폴더]
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v0200-fe");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5240;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.20.0";

let failed = 0;
const check = async (page, w, h, name, extra) => {
  const r = await page.evaluate(() => {
    const de = document.documentElement;
    const cut = [...document.querySelectorAll(".card, .page-title-row, .doe-lt, .doe-adv")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
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
const top = async (page, loc) => {
  await loc.evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.evaluate(() => window.scrollBy(0, -80));
  await page.waitForTimeout(700);
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
    // 1) ④ 고급 설정
    await page.goto(`${base}/p/p-body/doe/new?entries=le-1,le-2,le-9&${Q}`);
    await page.getByRole("radio", { name: /④ 형상 직접 비교/ }).click();
    await page.getByLabel("비교할 STEP·메시 끌어다 놓기(여러 개)").setInputFiles([
      { name: "chr_base.step", mimeType: "application/octet-stream", buffer: Buffer.alloc(4096) },
      { name: "chr_rib_A.step", mimeType: "application/octet-stream", buffer: Buffer.alloc(4096) },
    ]);
    await page.getByTestId("shape-row-2").waitFor({ timeout: 15000 });
    const adv = page.getByTestId("compare-adv");
    await adv.locator("summary").click();
    await page.getByTestId("lt-select").selectOption("cell:3");
    await top(page, adv);
    const hint = (await page.getByTestId("lt-hint").textContent()) ?? "";
    await check(page, w, h, "④ 고급 설정 하중 전달", { ok: (await page.getByTestId("lt-select").inputValue()) === "cell:3", text: hint });
    await shot(page, `1_advanced_${w}.png`);
    // 1b) ①②③ 고급 설정(§13.8) — ① 은 셀을 골라 안내 줄까지
    for (const [tag, name] of [["case", /① 같은 모델/], ["bmesh", /② 다른 모델\(B 메시\)/], ["step", /③ 다른 모델\(STEP만\)/]]) {
      await page.goto(`${base}/p/p-body/doe/new?entries=le-1,le-2,le-9&${Q}`);
      await page.getByRole("radio", { name }).click();
      const a2 = page.getByTestId("compare-adv");
      await a2.locator("summary").click();
      if (tag === "case") await page.getByTestId("lt-select").selectOption("cell:5");
      await top(page, a2);
      const note = tag === "case" ? await page.getByTestId("lt-same-note").count() : 0;
      await check(page, w, h, `${tag} 고급 설정`, { ok: tag !== "case" || note === 1, text: `select ${(await page.getByTestId("lt-select").inputValue())} · 안내 ${note}` });
      await shot(page, `1b_adv_${tag}_${w}.png`);
    }
    // 2b) ② 결과 진단(plan once — 형상 표 없음)
    await page.goto(`${base}/p/p-body/doe/doe-21?${Q}`);
    const s2 = page.getByTestId("lt-summary");
    await s2.waitFor({ timeout: 30000 });
    await page.getByTestId("lt-details").locator("summary").click();
    await page.getByRole("table", { name: "하중 전달 베이스라인 참값 대비" }).waitFor({ timeout: 10000 });
    await top(page, page.getByTestId("lt-block"));
    await check(page, w, h, "② 결과 진단", { ok: (await page.getByRole("table", { name: "하중 전달 형상별" }).count()) === 0, text: ((await s2.textContent()) ?? "").slice(-30) });
    await shot(page, `2b_diag_bmesh_${w}.png`);
    // 2) 결과 진단
    await page.goto(`${base}/p/p-body/doe/doe-20?${Q}`);
    const sum = page.getByTestId("lt-summary");
    await sum.waitFor({ timeout: 30000 });
    await page.getByTestId("lt-details").locator("summary").click();
    await page.getByRole("table", { name: "하중 전달 형상별" }).waitFor({ timeout: 10000 });
    await top(page, page.getByTestId("lt-block"));
    await check(page, w, h, "결과 진단", { ok: true, text: ((await sum.textContent()) ?? "").slice(0, 80) });
    await shot(page, `2_diag_${w}.png`);
    // 3) 3D 비교(같은 ESL)
    const grid = page.locator(".doe-compare");
    await grid.waitFor({ timeout: 30000 });
    await page.waitForTimeout(2500);
    await top(page, grid);
    const hdr = (await grid.textContent()) ?? "";
    await check(page, w, h, "3D 비교", { ok: /ESL le-\d/.test(hdr), text: (hdr.match(/ESL [^ (]+/g) ?? []).join(" / ") });
    await shot(page, `3_compare3d_${w}.png`);
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
