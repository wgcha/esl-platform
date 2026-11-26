// v0.25.0 F1 증적(mock): 새 스터디·그래프 select 화면(doe-10) 높이 — base(release/v0.25.0 59c81863) 빌드 vs 새 빌드(추가 비드 설정 끔 = ±0)
// vs 새 빌드(demoVBead=1: 접힌 절 · 펼침 · 비드 1개 추가) 를 2560×1440·1920×1080 에서 잰다. 스크린샷 저장.
// 사용: BASE_DIST=<base mock 빌드> NEW_DIST=<새 mock 빌드> node scripts/screenshots-v0250-f1.mjs [출력폴더]   (기본 /home/claude/shots)
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
const BASE_DIST = process.env.BASE_DIST ?? "/home/claude/dist-mock-base-0250f1";
const NEW_DIST = process.env.NEW_DIST ?? "/home/claude/dist-mock-new-0250f1";
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const serve = (dist, port) => spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", dist, "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const servers = [serve(BASE_DIST, 5591), serve(NEW_DIST, 5592)];
const Q = "freeze=1&mockUser=power&seenVersion=0.24.9";
const url = (port, p, extra = "") => `http://127.0.0.1:${port}/esl/p/p-body/${p}?${Q}${extra}`;
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
const metrics = (page) =>
  page.evaluate(() => {
    const h = (sel) => document.querySelector(sel)?.getBoundingClientRect().height ?? null;
    return {
      scrollHeight: document.documentElement.scrollHeight,
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      list: document.querySelector('[data-testid="bead-b1"]')?.closest("section.card")?.getBoundingClientRect().height ?? null,
      vb: h('[data-testid="bs-vb"]'),
    };
  });
let failed = 0;
try {
  await Promise.all([waitUp(5591), waitUp(5592)]);
  const browser = await chromium.launch({ args: ARGS });
  const open = async (port, u, w, h, need) => {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => console.error("pageerror:", e.message));
    await prime(page);
    await page.goto(u);
    await page.waitForSelector(need, { timeout: 60000 });
    await page.waitForTimeout(2500);
    return { ctx, page };
  };
  for (const [w, h] of [[2560, 1440], [1920, 1080]]) {
    console.log(`== ${w}×${h}`);
    // ① 새 스터디 화면 · 옛 스터디 화면(추가 비드 설정 끔) — base 와 같아야 함
    for (const [name, p, need] of [["새 스터디 화면", "doe/new", "form, section"], ["그래프 select(doe-10) — 설정 끔", "doe/doe-10", '[data-testid="bead-b1"]']]) {
      const a = await open(5591, url(5591, p), w, h, need);
      const ma = await metrics(a.page);
      await a.ctx.close();
      const b = await open(5592, url(5592, p), w, h, need);
      const mb = await metrics(b.page);
      await b.ctx.close();
      const ok = ma.scrollHeight === mb.scrollHeight && ma.list === mb.list;
      if (!ok) failed++;
      console.log(`${ok ? "OK  " : "FAIL"} ${name}\n   base scrollHeight=${ma.scrollHeight} list=${ma.list}\n   new  scrollHeight=${mb.scrollHeight} list=${mb.list}`);
    }
    // ② demoVBead=1: 접힘 → 펼침 → 비드 1개 추가(활성 행 + 미리보기)
    const d = await open(5592, url(5592, "doe/doe-10", "&demoVBead=1"), w, h, '[data-testid="bs-vb"]');
    const m0 = await metrics(d.page);
    const hScroll = (m) => (m.scrollWidth > m.clientWidth ? "가로 스크롤 있음" : "가로 스크롤 없음");
    console.log(`     demo 접힘  scrollHeight=${m0.scrollHeight} list=${m0.list} vb=${m0.vb} ${hScroll(m0)}`);
    await d.page.screenshot({ path: path.join(out, `v0250_f1_collapsed_${w}.png`) });
    await d.page.click('[data-testid="bs-vb-summary"]');
    await d.page.waitForTimeout(500);
    const m1 = await metrics(d.page);
    console.log(`     demo 펼침  scrollHeight=${m1.scrollHeight} list=${m1.list} vb=${m1.vb} ${hScroll(m1)}`);
    await d.page.screenshot({ path: path.join(out, `v0250_f1_open_${w}.png`) });
    await d.page.click('[data-testid="bs-vb-mode-coord"]');
    for (const [l, v] of [["ξ", "300"], ["η", "300"], ["길이", "120"], ["각도", "0"], ["D 최대", "5"], ["W", "20"]]) await d.page.fill(`input[aria-label="${l}"]`, v);
    await d.page.click('[data-testid="bs-vb-add"]');
    await d.page.waitForSelector('[data-testid="bs-vb-status-a1"][data-ok="true"]', { timeout: 20000 });
    await d.page.waitForTimeout(2500);
    const m2 = await metrics(d.page);
    console.log(`     비드 1개   scrollHeight=${m2.scrollHeight} list=${m2.list} vb=${m2.vb} ${hScroll(m2)}`);
    await d.page.screenshot({ path: path.join(out, `v0250_f1_added_${w}.png`) });
    await d.ctx.close();
  }
  await browser.close();
} finally {
  for (const s of servers) s.kill();
}
if (failed) {
  console.error(`실패 ${failed}건`);
  process.exit(1);
}
