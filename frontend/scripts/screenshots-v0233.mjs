// v0.23.3 화면 증적(mock, 2560×1440): 하중 정의 탭(지그·전 노드) · 지그 진단 3D(목표|맞춤 · 오차 · 영역·화살표) + 문서 높이.
// 사용: npm run build:mock && node scripts/screenshots-v0233.mjs [출력폴더]
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/shots");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);
const port = 5244;
const server = spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.23.3&demoJig=1";
try {
  for (let i = 0; ; i++) {
    try { if ((await fetch(`${base}/`)).ok) break; } catch { /* 아직 */ }
    if (i > 100) throw new Error("preview 서버 시작 시간 초과");
    await new Promise((r) => setTimeout(r, 200));
  }
  const browser = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"] });
  const ctx = await browser.newContext({ viewport: { width: 2560, height: 1440 } });
  const page = await ctx.newPage();
  const heights = {};
  const open = async (id) => {
    await page.goto(`${base}/p/p-body/doe/${id}?${Q}`);
    await page.getByTestId("doe-load-tab").first().waitFor();
    await page.waitForTimeout(2500);
  };
  const shot = async (name) => {
    await page.waitForTimeout(2500);
    const h = await page.evaluate(() => {
      const card = document.querySelector("[data-testid=doe-result-rows]")?.closest(".card");
      return { doc: document.documentElement.scrollHeight, cardBottom: card ? Math.round(card.getBoundingClientRect().bottom + window.scrollY) : null };
    });
    heights[name] = h;
    await page.screenshot({ path: path.join(out, name) });
    const line = (await page.getByTestId("jig-diag-line").first().textContent().catch(() => ""))?.trim();
    console.log(`${name}: 문서 높이 ${h.doc} · 결과 카드 아래 ${h.cardBottom}${line ? ` · ${line}` : ""}`);
  };
  await open("doe-40");
  await shot("v0233_tab_jig.png");
  await page.getByTestId("doe-load-tab").locator("[data-tab=full]").click();
  await shot("v0233_tab_full.png");
  await page.getByTestId("doe-load-tab").locator("[data-tab=jig]").click();
  await page.waitForTimeout(800);
  await page.getByTestId("v3d-jig-mode").locator("[data-mode=diag]").click();
  await page.getByTestId("jig-diag-entry").selectOption({ index: 0 });
  await shot("v0233_diag_tgtfit.png");
  await page.getByTestId("jig-diag-view").locator("[data-view=err]").click();
  await shot("v0233_diag_err.png");
  await page.getByTestId("jig-diag-view").locator("[data-view=reg]").click();
  await shot("v0233_diag_regions.png");
  console.log(JSON.stringify(heights));
  await browser.close();
} finally {
  server.kill();
}
