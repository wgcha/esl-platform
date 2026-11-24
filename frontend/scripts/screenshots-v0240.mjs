// v0.24.0 화면 증적(mock, 2560×1440): 하중 정의 탭 [경계력 ESL]·[내력 ESL](탭 4개) · Case ESL 화면 경계력·내력·소성 줄 · 자료 없음(사유·계산 버튼) + 문서 높이.
// 사용: npm run build:mock && node scripts/screenshots-v0240.mjs [출력폴더]
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
const port = 5245;
const server = spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: root, stdio: "pipe" });
const base = `http://127.0.0.1:${port}/esl`;
const Q = "freeze=1&mockUser=power&seenVersion=0.24.0&demoBforce=1";
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
  const shot = async (name, testid) => {
    await page.waitForTimeout(2500);
    const h = await page.evaluate(() => {
      const card = document.querySelector("[data-testid=doe-result-rows]")?.closest(".card");
      return { doc: document.documentElement.scrollHeight, cardBottom: card ? Math.round(card.getBoundingClientRect().bottom + window.scrollY) : null };
    });
    heights[name] = h;
    await page.screenshot({ path: path.join(out, name) });
    const line = testid ? (await page.getByTestId(testid).first().textContent().catch(() => ""))?.trim() : "";
    console.log(`${name}: 문서 높이 ${h.doc} · 결과 카드 아래 ${h.cardBottom}${line ? ` · ${line}` : ""}`);
  };
  // 1) 경계력 탭(doe-50 — contact 등급)
  await page.goto(`${base}/p/p-body/doe/doe-50?${Q}`);
  await page.getByTestId("doe-load-tab").first().waitFor();
  await page.waitForTimeout(2000);
  await shot("v0240_tab_jig_before.png");
  await page.getByTestId("doe-load-tab").locator("[data-tab=bforce]").click();
  await shot("v0240_tab_bforce.png", "bf-chip");
  // 2) 경계력 자료 없음(doe-51) — 탭 비활성 사유(키보드 포커스) + [경계력 ESL 계산]
  await page.goto(`${base}/p/p-body/doe/doe-51?${Q}`);
  await page.getByTestId("doe-load-tab").first().waitFor();
  await page.waitForTimeout(2000);
  await page.getByTestId("doe-load-tab").locator("[data-tab=bforce]").focus();
  await shot("v0240_contact_diag.png", "doe-load-tab-why");
  // 2b) v0.24.0 보완 내력 ESL 탭(doe-50 — 잔차·공유 노드·소성 칩, 순위표 umax(평가 영역))
  await page.goto(`${base}/p/p-body/doe/doe-50?${Q}`);
  await page.getByTestId("doe-load-tab").first().waitFor();
  await page.waitForTimeout(2000);
  await page.getByTestId("doe-load-tab").locator("[data-tab=fint]").click();
  await shot("v0240_tab_fint.png", "nodal-chip-fint");
  // 2c) 탭 4개 · 내력 자료 없음(doe-51) — 내력 탭 비활성 사유(키보드 포커스) + [경계력 ESL 계산]·[내력 ESL 계산]
  await page.goto(`${base}/p/p-body/doe/doe-51?${Q}`);
  await page.getByTestId("doe-load-tab").first().waitFor();
  await page.waitForTimeout(2000);
  await page.getByTestId("doe-load-tab").locator("[data-tab=fint]").focus();
  await shot("v0240_tabs4.png", "doe-load-tab-why");
  // 3) Case ESL 화면 경계력 요약 한 줄
  await page.goto(`${base}/p/p-body/c/c-demo/step/3?${Q}`);
  await page.getByTestId("esl-bforce-line").first().waitFor({ timeout: 15000 });
  await shot("v0240_esl_line.png", "esl-bforce-line");
  console.log(JSON.stringify(heights));
  await browser.close();
} finally {
  server.kill();
}
