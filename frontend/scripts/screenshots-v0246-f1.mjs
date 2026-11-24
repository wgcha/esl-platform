// v0.24.6 W-F1 뷰어 증적(mock): ① 높이 ±0(v0.24.5 빌드 대조) ② 스크린샷 ③ 30만 노드 성능.
// 사용: BASE_DIST=<v0.24.5 mock 빌드> NEW_DIST=<새 mock 빌드> node scripts/screenshots-v0246-f1.mjs [출력폴더]   (기본 /home/claude/shots)
//   빌드: npx vite build --mode mock --outDir <폴더>
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
const BASE_DIST = process.env.BASE_DIST ?? "/home/claude/dist-mock-base-f1";
const NEW_DIST = process.env.NEW_DIST ?? "/home/claude/dist-mock-new-f1";
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const serve = (dist, port) => spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const servers = [serve(BASE_DIST, 5291), serve(NEW_DIST, 5292)];
const urlOf = (port, q = "") => `http://127.0.0.1:${port}/esl/p/p-body/c/c-demo/stage/4?freeze=1&mockUser=power&seenVersion=0.24.6${q}`;
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
const shot = async (page, name) => {
  const p = path.join(out, `v0246_viewer_${name}.png`);
  await page.screenshot({ path: p });
  console.log(p);
};
const ready = async (page) => {
  await page.waitForSelector('[data-testid="v3d-host"][data-phase="ready"]', { timeout: 60000 });
  await page.waitForTimeout(1500);
};
const metrics = (page) =>
  page.evaluate(() => {
    const r = (sel) => document.querySelector(sel)?.getBoundingClientRect();
    const card = document.querySelector('[data-testid="v3d-host"]')?.closest("section.card");
    const bar = r('[data-testid="v3d-view-bar"]');
    const host = r('[data-testid="v3d-host"]');
    return {
      scrollHeight: document.documentElement.scrollHeight,
      cardH: card?.getBoundingClientRect().height,
      hostH: host?.height,
      hostW: host?.width,
      barInside: !!bar && !!host && bar.left >= host.left && bar.right <= host.right && bar.top >= host.top,
      barW: bar?.width,
      barH: bar?.height,
    };
  });
const ctxOpts = (w, h) => ({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
const prime = (page) => page.addInitScript(() => { try { localStorage.setItem("esl.statusDrawer", "closed"); } catch { /* 무시 */ } });

let failed = 0;
try {
  await Promise.all([waitUp(5291), waitUp(5292)]);
  const browser = await chromium.launch({ args: ARGS });

  // ① 높이 ±0
  console.log("== ① 높이(v0.24.5 빌드 대조)");
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    const res = {};
    for (const [k, port] of [["base", 5291], ["new", 5292]]) {
      const ctx = await browser.newContext(ctxOpts(w, h));
      const page = await ctx.newPage();
      await prime(page);
      await page.goto(urlOf(port));
      await ready(page);
      res[k] = await metrics(page);
      await ctx.close();
    }
    const same = res.base.scrollHeight === res.new.scrollHeight && res.base.cardH === res.new.cardH && res.base.hostH === res.new.hostH;
    if (!same) failed++;
    console.log(`${same ? "OK  " : "FAIL"} ${w}×${h} scrollHeight ${res.base.scrollHeight}→${res.new.scrollHeight} · 카드 ${res.base.cardH}→${res.new.cardH} · 3D 칸 ${res.base.hostH}→${res.new.hostH} · 막대 칸 안 ${res.new.barInside} · 막대 ${Math.round(res.new.barW)}×${Math.round(res.new.barH)}px`);
  }

  // ② 스크린샷
  console.log("== ② 스크린샷");
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    const ctx = await browser.newContext(ctxOpts(w, h));
    const page = await ctx.newPage();
    page.on("pageerror", (e) => console.error("pageerror:", e.message));
    await prime(page);
    await page.goto(urlOf(5292));
    await ready(page);
    const suf = w === 2560 ? "2560" : "1920";
    const host = page.getByTestId("v3d-host");
    await shot(page, `01_default_${suf}`);
    await page.getByTestId("v3d-layer-bc").click();
    await page.waitForTimeout(500);
    await shot(page, `02_bc_off_${suf}`);
    await page.getByTestId("v3d-layer-load").click();
    await page.waitForTimeout(500);
    await shot(page, `03_bc_load_off_${suf}`);
    await page.getByTestId("v3d-layer-bc").click();
    await page.getByTestId("v3d-layer-load").click();
    // 변위 보기 + 변형 + 원형 + 구간 9
    await page.getByTestId("v3d-mode").locator("[data-mode=tgt]").click();
    await page.waitForTimeout(500);
    await page.getByRole("button", { name: "변형 형상" }).click();
    await page.getByTestId("v3d-gear").click();
    await page.getByTestId("v3d-opt-ghost").check();
    await page.waitForTimeout(800);
    await shot(page, `04_ghost_popover_${suf}`);
    await page.getByTestId("v3d-opt-levels").locator("[data-levels='9']").click();
    await page.keyboard.press("Escape");
    await page.waitForTimeout(800);
    await shot(page, `05_levels9_overlay_ghost_${suf}`);
    await host.click({ position: { x: Math.round(w * 0.3), y: Math.round(h * 0.25) } });
    await page.waitForTimeout(400);
    await shot(page, `06_probe_${suf}`);
    const m = await metrics(page);
    console.log(`${suf}: 구간 9·원형·변위 보기 — 막대 칸 안 ${m.barInside}`);
    await ctx.close();
  }

  // ③ 성능(30만 노드)
  console.log("== ③ 성능(?mockView3d=plate300k)");
  const ctx = await browser.newContext(ctxOpts(2560, 1440));
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.error("pageerror:", e.message));
  await prime(page);
  await page.addInitScript(() => {
    const W = (window.__gl = { clear: 0, draw: 0, buf: 0, bufBytes: 0, tex: 0, gl: null });
    for (const proto of [WebGL2RenderingContext.prototype]) {
      for (const n of ["bufferData", "bufferSubData"]) { const o = proto[n]; proto[n] = function (...a) { W.buf++; const d = a[1]; W.bufBytes += typeof d === "number" ? d : d?.byteLength ?? 0; return o.apply(this, a); }; }
      for (const n of ["texImage2D", "texSubImage2D"]) { const o = proto[n]; proto[n] = function (...a) { W.tex++; return o.apply(this, a); }; }
      const oc = proto.clear; proto.clear = function (...a) { W.clear++; W.gl = this; return oc.apply(this, a); };
      for (const n of ["drawElements", "drawArrays", "drawElementsInstanced", "drawArraysInstanced"]) { const o = proto[n]; proto[n] = function (...a) { W.draw++; return o.apply(this, a); }; }
    }
  });
  const t0 = Date.now();
  await page.goto(urlOf(5292, "&mockView3d=plate300k"));
  await ready(page);
  console.log(`30만 노드 판 적재·첫 그림까지 ${Date.now() - t0} ms`);
  const info = await page.evaluate(() => document.querySelector('[data-testid="v3d-note"]')?.textContent);
  // 작업 시간: 클릭 → 다음 그림(clear 증가) → gl.finish
  const timed = async (label, action) => {
    await page.waitForTimeout(1200);
    const r = await page.evaluate(async (actionSrc) => {
      const W = window.__gl;
      const before = { clear: W.clear, buf: W.buf, tex: W.tex, bytes: W.bufBytes };
      const t = performance.now();
      window.__act();
      let tDraw = null;
      for (let i = 0; i < 600 && W.clear === before.clear; i++) await new Promise((r) => requestAnimationFrame(r));
      tDraw = performance.now() - t;
      if (W.gl) W.gl.readPixels(0, 0, 1, 1, W.gl.RGBA, W.gl.UNSIGNED_BYTE, new Uint8Array(4)); // 그림이 끝날 때까지 기다림(소프트웨어 GL)
      const tFin = performance.now() - t;
      return { drawMs: +tDraw.toFixed(1), finishMs: +tFin.toFixed(1), frames: W.clear - before.clear, bufferUploads: W.buf - before.buf, bytes: W.bufBytes - before.bytes, texUploads: W.tex - before.tex };
    }, "");
    return { label, ...r };
  };
  const run = async (label, domFn) => {
    await page.evaluate((src) => { window.__act = new Function(src); }, domFn);
    const r = await timed(label);
    console.log(`${label}: 다음 그림까지 ${r.drawMs} ms · GPU 완료까지 ${r.finishMs} ms · 프레임 ${r.frames} · 버퍼 업로드 ${r.bufferUploads}(${r.bytes} B) · 텍스처 업로드 ${r.texUploads}`);
    return r;
  };
  const q = (id) => `document.querySelector('[data-testid="${id}"]')`;
  const results = {};
  results.bc = await run("경계조건 토글", `${q("v3d-layer-bc")}.click()`);
  results.bc2 = await run("경계조건 토글(2회째)", `${q("v3d-layer-bc")}.click()`);
  results.load = await run("하중 토글", `${q("v3d-layer-load")}.click()`);
  await page.waitForTimeout(400);
  // 범례 범위 변경: 입력 칸 값 바꾸기(React 입력 이벤트)
  await page.getByTestId("v3d-gear").click();
  results.lv9 = await run("범례 구간 9", `${q("v3d-opt-levels")}.querySelector("[data-levels='9']").click()`);
  results.lv0 = await run("범례 연속", `${q("v3d-opt-levels")}.querySelector("[data-levels='0']").click()`);
  await page.evaluate(() => { window.__act = () => { const i = document.querySelector('[data-testid="v3d-legend"] input'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(i, String(Number(i.value) * 0.5)); i.dispatchEvent(new Event("input", { bubbles: true })); }; });
  results.range = await timed("범례 범위");
  console.log(`범례 범위 변경: 다음 그림까지 ${results.range.drawMs} ms · GPU 완료까지 ${results.range.finishMs} ms · 버퍼 업로드 ${results.range.bufferUploads} · 텍스처 업로드 ${results.range.texUploads}`);
  // 원형 첫 켬(변형 켠 뒤)
  await page.getByRole("button", { name: "변형 형상" }).click();
  await page.waitForTimeout(800);
  await page.getByTestId("v3d-gear").click();
  await page.evaluate(() => { window.__act = () => document.querySelector('[data-testid="v3d-opt-ghost"]').click(); });
  results.ghost = await timed("원형 첫 켬");
  console.log(`원형 외곽선 첫 켬(특징선 계산+업로드): 다음 그림까지 ${results.ghost.drawMs} ms · GPU 완료까지 ${results.ghost.finishMs} ms`);
  await page.evaluate(() => { window.__act = () => document.querySelector('[data-testid="v3d-opt-ghost"]').click(); });
  results.ghost2 = await timed("원형 끔");
  console.log(`원형 끔(visible): 다음 그림까지 ${results.ghost2.drawMs} ms · 버퍼 업로드 ${results.ghost2.bufferUploads}`);
  await shot(page, "07_plate300k_2560");
  // 회전 fps: 칸 위 드래그 2 초
  const box = await page.getByTestId("v3d-host").boundingBox();
  await page.keyboard.press("Escape");
  const f0 = await page.evaluate(() => window.__gl.clear);
  const tt = Date.now();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  for (let i = 0; i < 40; i++) {
    await page.mouse.move(box.x + box.width / 2 + i * 6, box.y + box.height / 2 + i * 2);
    await page.waitForTimeout(40);
  }
  await page.mouse.up();
  const dt = (Date.now() - tt) / 1000;
  const f1 = await page.evaluate(() => window.__gl.clear);
  console.log(`회전 드래그 ${dt.toFixed(1)} s 동안 프레임 ${f1 - f0} → ${((f1 - f0) / dt).toFixed(1)} fps(LOD·소프트웨어 GL, 입력 25 Hz 상한)`);
  console.log(`노트: ${info}`);
  await ctx.close();
  await browser.close();
} finally {
  for (const s of servers) s.kill();
}
if (failed) {
  console.error(`실패 ${failed}`);
  process.exit(1);
}
