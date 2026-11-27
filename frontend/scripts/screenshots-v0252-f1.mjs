// v0.25.2 F1 증적(mock): 화면 높이 — base(release/v0.25.2 dc8cb725 = F1 전) 빌드 vs 새 빌드를 2560×1440·1920×1080 에서 잰다(V-0252-28·30·31 의 "높이 증가 0").
//   ② t*·지지점(Case c-demo): scrollHeight · 카드 높이 · 곡선 클릭으로 "직접" 행을 고른 뒤에도 같은지.
//   스터디 결과(④): base doe-60(옛 결과) vs 새 doe-60(옛 결과)·doe-80(강제 부여·참고용·경고 3)·doe-81(#96 꼴) — 기본 탭과 지그 변위 탭(3D 표식) 의 scrollHeight·3D 줄·카드.
// 사용: BASE_DIST=<base mock 빌드> NEW_DIST=<새 mock 빌드> node scripts/screenshots-v0252-f1.mjs [출력폴더]
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots_v0252_f1");
mkdirSync(out, { recursive: true });
const BASE_DIST = process.env.BASE_DIST ?? "/home/claude/dist-mock-base-0252f1";
const NEW_DIST = process.env.NEW_DIST ?? "/home/claude/dist-mock-new-0252f1";
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const serve = (dist, port) => spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const servers = [serve(BASE_DIST, 5891), serve(NEW_DIST, 5892)];
const Q = "freeze=1&mockUser=power&seenVersion=0.24.9";
const stage2 = (port) => `http://127.0.0.1:${port}/esl/p/p-body/c/c-demo/stage/2?${Q}`;
const study = (port, id, demo) => `http://127.0.0.1:${port}/esl/p/p-body/doe/${id}?${demo}=1&${Q}`;
const waitUp = async (port) => {
  for (let i = 0; i < 150; i++) {
    try {
      if ((await fetch(`http://127.0.0.1:${port}/esl/`)).ok) return;
    } catch {
      /* 아직 */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error("preview 서버 시작 시간 초과");
};
const ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"];
const round = (v) => Math.round(v * 100) / 100;
const metrics = (page, sel) =>
  page.evaluate((s) => {
    const r = (q) => Math.round((document.querySelector(q)?.getBoundingClientRect().height ?? -1) * 100) / 100;
    const cards = [...document.querySelectorAll(s)].map((e) => Math.round(e.getBoundingClientRect().height * 100) / 100);
    return { scrollHeight: document.documentElement.scrollHeight, cards, row3d: r(".doe-row-3d"), grid: r(".step2-grid") };
  }, sel);
let failed = 0;
const same = (a, b) => a.scrollHeight === b.scrollHeight && JSON.stringify(a.cards) === JSON.stringify(b.cards) && a.row3d === b.row3d && a.grid === b.grid;
try {
  await Promise.all([waitUp(5891), waitUp(5892)]);
  const browser = await chromium.launch({ args: ARGS });
  const open = async (u, w, h, need) => {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => console.error("pageerror:", e.message));
    await page.addInitScript(() => { try { localStorage.setItem("esl.statusDrawer", "closed"); } catch { /* 무시 */ } });
    await page.goto(u);
    await page.waitForSelector(need, { timeout: 60000 });
    await page.waitForTimeout(1500);
    return { ctx, page };
  };
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    const suf = String(w);
    // ---- ② t*·지지점
    const r2 = {};
    for (const [k, port] of [["base", 5891], ["new", 5892]]) {
      const { ctx, page } = await open(stage2(port), w, h, ".step2-grid .chart svg");
      r2[k] = await metrics(page, ".step2-grid > .card, .step2-pair > .card, .step2-support > *");
      if (k === "new") {
        await page.screenshot({ path: path.join(out, `v0252_f1_${suf}_01_stage2.png`) });
        const svg = page.locator('[data-testid="maxhold-svg"]');
        const box = await svg.boundingBox();
        // 곡선 위 후보 아닌 지점 클릭(가로 35 %) → "직접" 행 선택
        await page.mouse.move(box.x + box.width * 0.35, box.y + box.height * 0.4);
        await page.waitForTimeout(200);
        await page.screenshot({ path: path.join(out, `v0252_f1_${suf}_02_hover.png`) });
        await page.mouse.click(box.x + box.width * 0.35, box.y + box.height * 0.4);
        await page.waitForTimeout(500);
        r2.after = await metrics(page, ".step2-grid > .card, .step2-pair > .card, .step2-support > *");
        r2.manual = await page.evaluate(() => ({ input: document.querySelector('[data-testid="manual-input"]')?.value, disp: document.querySelector('[data-testid="manual-disp"]')?.textContent, row: !!document.querySelector('[data-testid="manual-row"].hl') }));
        await page.screenshot({ path: path.join(out, `v0252_f1_${suf}_03_manual.png`) });
      }
      await ctx.close();
    }
    for (const k of ["new", "after"]) {
      const ok = same(r2.base, r2[k]);
      if (!ok) failed++;
      console.log(`${ok ? "OK  " : "FAIL"} ② ${w}×${h} base→${k}: scrollHeight ${r2.base.scrollHeight}→${r2[k].scrollHeight} · grid ${r2.base.grid}→${r2[k].grid} · 카드 ${r2.base.cards}→${r2[k].cards}`);
    }
    console.log(`     직접 행: ${JSON.stringify(r2.manual)}`);
    // ---- 스터디 결과
    const cardSel = ".doe-row-3d section.card, [data-testid=\"doe-result-rows\"]";
    const base = {};
    for (const [k, port, id, demo, tab] of [
      ["base doe-60", 5891, "doe-60", "demoJigGrid", null],
      ["base doe-60 전노드", 5891, "doe-60", "demoJigGrid", "full"],
      ["base doe-60 지그변위", 5891, "doe-60", "demoJigGrid", "jig_disp"],
      ["new doe-60", 5892, "doe-60", "demoJigGrid", null],
      ["new doe-60 지그변위", 5892, "doe-60", "demoJigGrid", "jig_disp"],
      ["new doe-80", 5892, "doe-80", "demoJigForce", null],
      ["new doe-80 지그변위", 5892, "doe-80", "demoJigForce", "jig_disp"],
      ["new doe-81(#96)", 5892, "doe-81", "demoJigForce", null],
      ["new doe-81 지그변위(빈 탭)", 5892, "doe-81", "demoJigForce", "jig_disp"],
    ]) {
      const { ctx, page } = await open(study(port, id, demo), w, h, '[data-testid="doe-result-rows"], [data-testid="doe-load-tab"]');
      if (tab) {
        // 좁은 화면은 지그 3방식이 그룹 팝오버("지그 ▾")로 접힘 — 보이는 버튼이 없으면 그룹을 열어 옵션을 누른다
        const direct = page.locator(`[data-testid="doe-load-tab"] [data-tab=${tab}]:visible`);
        if (await direct.count()) await direct.first().click();
        else {
          const grp = tab.startsWith("jig") ? "jig" : tab;
          await page.locator(`[data-testid="doe-load-tab"] [data-group=${grp}]`).click();
          await page.locator(`[role=option][data-tab=${tab}]`).click();
        }
        await page.waitForSelector('.doe-row-3d [data-testid="v3d-host"][data-phase="ready"], [data-testid="empty-rank-note"]', { timeout: 60000 });
        await page.waitForTimeout(2500);
      }
      const m = await metrics(page, cardSel);
      m.note = await page.evaluate(() => Math.round((document.querySelector('[data-testid="empty-rank-note"]')?.getBoundingClientRect().height ?? -1) * 100) / 100);
      base[k] = m;
      const tag = k.replace(/[^a-z0-9]+/gi, "_");
      if (k.startsWith("new doe-8")) await page.screenshot({ path: path.join(out, `v0252_f1_${suf}_${tag}.png`) });
      await ctx.close();
    }
    const pairs = [["new doe-60", "base doe-60"], ["new doe-60 지그변위", "base doe-60 지그변위"], ["new doe-80", "base doe-60"], ["new doe-80 지그변위", "base doe-60 지그변위"], ["new doe-81(#96)", "base doe-60 전노드"]];
    for (const [a, b] of pairs) {
      // doe-81 은 전 노드 보기에 순위 행이 1개뿐이라 표 높이가 다름 — 3D 줄 높이만 같으면 됨
      const ok = a.startsWith("new doe-81") ? base[a].row3d === base[b].row3d : same(base[a], base[b]);
      if (!ok) failed++;
      console.log(`${ok ? "OK  " : "FAIL"} 스터디 ${w}×${h} ${b} → ${a}: scrollHeight ${base[b].scrollHeight}→${base[a].scrollHeight} · 3D 줄 ${base[b].row3d}→${base[a].row3d} · 카드 ${base[b].cards}→${base[a].cards}`);
    }
    const nh = base["new doe-81 지그변위(빈 탭)"].note;
    if (!(nh > 0 && nh < 26)) failed++;
    console.log(`${nh > 0 && nh < 26 ? "OK  " : "FAIL"} doe-81 빈 탭 안내 줄 높이 ${nh}px(1줄 < 26px)`);
  }
  await browser.close();
} catch (e) {
  console.error(e);
  failed++;
} finally {
  for (const s of servers) s.kill();
}
process.exit(failed ? 1 : 0);
