// v0.24.9 F1 증적(mock): ① 높이 ±0(base 커밋 빌드 대조 — Case ③ 3D 카드·스터디 결과·새 스터디, 같은 빌드 U 유무 대조)
// ② 스크린샷 2560·1920: 지그 3방식 기호·범례 툴팁·탐침·U 행 변수 표.
// 사용: BASE_DIST=<base mock 빌드> NEW_DIST=<새 mock 빌드> node scripts/screenshots-v0249-f1.mjs [출력폴더]   (기본 /home/claude/shots)
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
const BASE_DIST = process.env.BASE_DIST ?? "/home/claude/dist-mock-base-0249";
const NEW_DIST = process.env.NEW_DIST ?? "/home/claude/dist-mock-new-0249";
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);
const sharp = (await import(pathToFileURL(createRequire(import.meta.url).resolve(process.env.SHARP_PATH ?? "/home/claude/.npm-global/lib/node_modules/sharp")).href)).default;

const serve = (dist, port) => spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const servers = [serve(BASE_DIST, 5491), serve(NEW_DIST, 5492)];
const Q = "freeze=1&mockUser=power&seenVersion=0.24.8&demoPosU=1&demoJig=1&demoJigGrid=1&demoShape=1";
const studyUrl = (port, id) => `http://127.0.0.1:${port}/esl/p/p-body/doe/${id}?${Q}`;
const caseUrl = (port) => `http://127.0.0.1:${port}/esl/p/p-body/c/c-demo/stage/4?${Q}&demoJigRows=${port === 5491 ? 1 : 2}`;
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
const prime = (page) => page.addInitScript(() => { try { localStorage.setItem("esl.statusDrawer", "closed"); } catch { /* 무시 */ } });
const ctxOpts = (w, h) => ({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
const hOf = (page, sel) => page.evaluate((s) => document.querySelector(s)?.getBoundingClientRect().height ?? null, sel);
const metrics = (page) =>
  page.evaluate(() => {
    const h = (sel) => document.querySelector(sel)?.getBoundingClientRect().height ?? null;
    const card = document.querySelector('[data-testid="v3d-host"]')?.closest("section.card");
    return {
      scrollHeight: document.documentElement.scrollHeight,
      card3d: card?.getBoundingClientRect().height ?? null,
      host: h('[data-testid="v3d-host"]'),
      rows: h('[data-testid="doe-result-rows"]'),
      row3d: h('[data-testid="doe-row-3d"]'),
      rowSens: h('[data-testid="doe-row-sens"]'),
      params: h("table.doe-params"),
      paramsWrap: h("table.doe-params")?.valueOf() == null ? null : document.querySelector("table.doe-params")?.closest(".table-wrap")?.getBoundingClientRect().height ?? null,
    };
  });
const pickTab = async (page, root, popPrefix, tab) => {
  await page.waitForSelector(`${root} [data-tab]`, { timeout: 45000 });
  const trig = page.locator(`${root} [aria-haspopup=listbox]`);
  if (await trig.count()) {
    await trig.first().click();
    await page.locator(`[data-testid^="${popPrefix}"] [data-tab=${tab}]`).first().click();
  } else {
    await page.waitForSelector(`${root} [data-tab=${tab}]:not([aria-disabled=true])`, { timeout: 45000 });
    await page.click(`${root} [data-tab=${tab}]`);
  }
};
const ready3d = async (page) => {
  await page.waitForSelector('[data-testid="v3d-host"][data-phase="ready"]', { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(1500);
};
/** 변수 표 카드("④ 변수")는 기본 접힘 — 펼친 상태로 잰다 */
const openVars = async (page) => {
  await page.waitForSelector("table.doe-params", { state: "attached", timeout: 60000 });
  const btn = page.locator('section[aria-label="④ 변수"] .card-fold-btn');
  if ((await btn.getAttribute("aria-expanded")) !== "true") await btn.click();
  await page.waitForSelector("table.doe-params", { state: "visible", timeout: 20000 });
  await page.waitForTimeout(800);
};
const CASE_TAB = { root: '[data-testid="v3d-src-tab"]', pop: "v3d-src-pop-" };
const STUDY_TAB = { root: '[data-testid="doe-load-tab"]', pop: "doe-load-pop-" };

let failed = 0;
const rep = [];
try {
  await Promise.all([waitUp(5491), waitUp(5492)]);
  const browser = await chromium.launch({ args: ARGS });
  const open = async (port, url, w, h, after) => {
    const ctx = await browser.newContext(ctxOpts(w, h));
    const page = await ctx.newPage();
    page.on("pageerror", (e) => console.error("pageerror:", e.message));
    await prime(page);
    await page.goto(url);
    await after(page);
    return { ctx, page };
  };
  const caseReady = (tab) => async (page) => {
    await page.waitForSelector('[data-testid="v3d-host"]', { timeout: 60000 });
    if (tab) await pickTab(page, CASE_TAB.root, CASE_TAB.pop, tab);
    await ready3d(page);
  };
  const studyReady = (tab, need = '[data-testid="doe-result-rows"]') => async (page) => {
    await page.waitForSelector(need, { timeout: 60000 });
    if (tab) await pickTab(page, STUDY_TAB.root, STUDY_TAB.pop, tab);
    await ready3d(page);
  };
  const cmpKeys = (a, b, keys) => keys.every((k) => a[k] === b[k]);
  const line = (m, keys) => keys.map((k) => `${k}=${m[k]}`).join(" ");

  console.log("== ① 높이 ±0 — base(3609c921) 빌드 vs 새 빌드");
  const cases = [
    ["Case ③ 3D 카드(기본 출처)", (p) => caseUrl(p), caseReady(null), ["scrollHeight", "card3d", "host"]],
    ["Case ③ 3D 카드(지그 고정 탭)", (p) => caseUrl(p), caseReady("jig"), ["scrollHeight", "card3d", "host"]],
    ["스터디 결과(doe-40 ② 지그)", (p) => studyUrl(p, "doe-40"), studyReady(null), ["scrollHeight", "rows", "row3d", "rowSens"]],
    ["스터디 결과(doe-60 ④ 격자)", (p) => studyUrl(p, "doe-60"), studyReady(null), ["scrollHeight", "rows", "row3d"]],
    ["새 스터디 화면", (p) => `http://127.0.0.1:${p}/esl/p/p-body/doe/new?${Q}`, async (p) => { await p.waitForTimeout(2500); }, ["scrollHeight"]],
    ["변수 표(doe-30 U 없음)", (p) => studyUrl(p, "doe-30"), openVars, ["scrollHeight", "params", "paramsWrap"]],
  ];
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    for (const [name, url, after, keys] of cases) {
      const a = await open(5491, url(5491), w, h, after);
      const ma = await metrics(a.page);
      await a.ctx.close();
      const b = await open(5492, url(5492), w, h, after);
      const mb = await metrics(b.page);
      await b.ctx.close();
      const ok = cmpKeys(ma, mb, keys);
      if (!ok) failed++;
      const msg = `${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}\n   base ${line(ma, keys)}\n   new  ${line(mb, keys)}`;
      console.log(msg);
      rep.push(msg);
    }
    // 같은 빌드: U 행 유무(doe-30 vs doe-70) — 표는 .table-wrap.scroll 로 페이지 높이 증가 0
    const a = await open(5492, studyUrl(5492, "doe-30"), w, h, openVars);
    const ma = await metrics(a.page);
    await a.ctx.close();
    const b = await open(5492, studyUrl(5492, "doe-70"), w, h, openVars);
    const mb = await metrics(b.page);
    await b.page.screenshot({ path: path.join(out, `v0249_f1_utable_${w}.png`) });
    await b.ctx.close();
    const keys = ["scrollHeight"];
    const ok = mb.scrollHeight <= ma.scrollHeight; // 증가 0(표가 스크롤 상자가 되어 오히려 줄어듦)
    if (!ok) failed++;
    const msg = `${ok ? "OK  " : "FAIL"} ${w}×${h} 변수 표 U 행 유무 scrollHeight ${ma.scrollHeight}→${mb.scrollHeight} · 표 래퍼 높이 ${ma.paramsWrap}→${mb.paramsWrap}(표 안 스크롤)`;
    console.log(msg);
    rep.push(msg);
    void keys;
  }

  console.log("== ② 지그 3방식 기호·범례·탐침 스크린샷");
  const MODES = [["jig", "fixed", "#7f7f7f"], ["jig_disp", "disp", "#0f9aa8"], ["jig_spring", "spring", "#e8870e"]];
  const colorNear = (r, g, b, t) => (R, G, B) => Math.abs(R - r) + Math.abs(G - g) + Math.abs(B - b) < t;
  const hex = (s) => [parseInt(s.slice(1, 3), 16), parseInt(s.slice(3, 5), 16), parseInt(s.slice(5, 7), 16)];
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    for (const [tab, name, color] of MODES) {
      const { ctx, page } = await open(5492, caseUrl(5492), w, h, caseReady(tab));
      await page.getByTestId("v3d-host").scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(out, `v0249_f1_case_${name}_${w}.png`) });
      // 범례 툴팁: 칩 title(네이티브 툴팁은 스크린샷에 안 잡힘) → 같은 문구를 칩 아래 임시 말풍선으로 그려 캡처
      const chip = page.getByTestId("v3d-layer-bc");
      const title = await chip.getAttribute("title");
      writeFileSync(path.join(out, `v0249_f1_legend_${name}_${w}.txt`), title ?? "");
      if (tab === "jig_spring") {
        await page.evaluate((t) => {
          const el = document.querySelector('[data-testid="v3d-layer-bc"]');
          const r = el.getBoundingClientRect();
          const d = document.createElement("div");
          d.setAttribute("data-testid", "fake-tip");
          d.style.cssText = `position:fixed;left:${r.left}px;top:${r.bottom + 6}px;z-index:99999;background:#222;color:#fff;font:12px sans-serif;padding:6px 8px;border-radius:4px;white-space:pre;max-width:520px`;
          d.textContent = t;
          document.body.appendChild(d);
        }, title ?? "");
        await page.screenshot({ path: path.join(out, `v0249_f1_legend_tooltip_${w}.png`) });
        await page.evaluate(() => document.querySelector('[data-testid="fake-tip"]')?.remove());
      }
      // 탐침: 기호 색 픽셀을 찾아 눌러 info 줄이 "지지 …" 가 될 때까지
      const hostBox = await page.getByTestId("v3d-host").boundingBox();
      const buf = await page.screenshot({ clip: hostBox });
      const { data, info } = await sharp(buf).raw().toBuffer({ resolveWithObject: true });
      const [r0, g0, b0] = hex(color);
      const near = colorNear(r0, g0, b0, 40);
      const pts = [];
      for (let y = 0; y < info.height; y += 3)
        for (let x = 0; x < info.width; x += 3) {
          const i = (y * info.width + x) * info.channels;
          if (near(data[i], data[i + 1], data[i + 2])) pts.push([x, y]);
        }
      let probe = null;
      const infoSel = '[data-testid="v3d-info"]';
      // 지지 픽은 노드 가까이(수 px)에서만 잡힘 — 가장 위 기호 둘레를 3 px 간격으로 훑는다(2560 은 3방식 전부, 1920 은 스프링만)
      if (pts.length && (w === 2560 || name === "spring")) {
        const [sx, sy] = pts.reduce((a, q) => (q[1] < a[1] ? q : a), pts[0]);
        outer: for (let dy = -36; dy <= 36; dy += 3)
          for (let dx = -36; dx <= 36; dx += 3) {
            await page.mouse.click(hostBox.x + sx + dx, hostBox.y + sy + dy);
            const t = await page.evaluate((sel) => document.querySelector(sel)?.textContent ?? "", infoSel);
            if (/^지지 \d/.test(t.trim())) {
              probe = t.trim();
              break outer;
            }
          }
      }
      if (probe) {
        await page.screenshot({ path: path.join(out, `v0249_f1_probe_${name}_${w}.png`) });
        writeFileSync(path.join(out, `v0249_f1_probe_${name}_${w}.txt`), probe);
      }
      const msg = `${w}×${h} ${name}: 기호 색 픽셀 ${pts.length} · 탐침 ${probe ?? "(못 찾음)"}`;
      console.log(msg);
      rep.push(msg);
      if (!pts.length) failed++;
      await ctx.close();
    }
    // 스터디 3D(doe-72) 방식별
    for (const [tab, name] of [["jig_disp", "jd"], ["jig_spring", "js"]]) {
      const { ctx, page } = await open(5492, studyUrl(5492, "doe-72"), w, h, studyReady(tab));
      await page.screenshot({ path: path.join(out, `v0249_f1_study_${name}_${w}.png`) });
      await ctx.close();
    }
    // 결과 경고 줄·순위 꼬리(doe-71)
    const { ctx, page } = await open(5492, studyUrl(5492, "doe-71"), w, h, studyReady(null));
    await page.screenshot({ path: path.join(out, `v0249_f1_result_spatial_${w}.png`) });
    await ctx.close();
  }
  await browser.close();
} finally {
  for (const s of servers) s.kill();
}
writeFileSync(path.join(out, "v0249_f1_heights.txt"), rep.join("\n"));
console.log(failed ? `FAIL ${failed}` : "OK 전부");
process.exit(failed ? 1 : 0);
