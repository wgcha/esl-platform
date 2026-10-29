// V-BD-17 화면 증적(mock, esl_bead_doe.md §12): 2560×1440 3장 — (1) 입력·비드 변수·평면도 (2) 미리보기 썸네일 격자 (3) 순위·민감도·3D 비교.
// + 1920×1080·2560×1440 에서 가로 스크롤·카드 잘림·표 가로 스크롤이 없는지 검사(새 DOE·미리보기 완료·결과·라이브러리 DOE 탭). 실패하면 종료 코드 1.
// 사용: npm run build:mock && node scripts/screenshots-v090.mjs [출력폴더]   (기본 /home/claude/screens/v090)
// 환경: PLAYWRIGHT_MODULE(기본 전역 playwright), PLAYWRIGHT_BROWSERS_PATH(기본 /opt/pw-browsers).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] ?? "/home/claude/screens/v090");
mkdirSync(out, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "/opt/pw-browsers";
const modPath = process.env.PLAYWRIGHT_MODULE ?? "/home/claude/.npm-global/lib/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(modPath).href);

const port = 5189;
const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
const base = `http://127.0.0.1:${port}/esl`;
const NEW = `${base}/p/p-body/doe/new?entries=le-1,le-2,le-3&freeze=1&mockUser=power`;
const PREVIEW = `${base}/p/p-body/doe/doe-2?freeze=1&mockUser=power`;
const DONE = `${base}/p/p-body/doe/doe-1?freeze=1&mockUser=power`;
const LIB = `${base}/p/p-body/library?tab=doe&freeze=1&mockUser=power`;

let failed = 0;
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
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 2560, height: 1440 } });

  // (1) 입력·비드 변수·평면도(② 다른 모델 + B 메시 — 경계 경고 포함)
  await page.goto(PREVIEW);
  await page.waitForSelector('table[aria-label="비드 변수"]');
  await page.waitForSelector('[data-testid="plan-warn-link"]');
  await page.waitForFunction(() => /실제 \d+안/.test(document.querySelector('[data-testid="doe-count"]')?.textContent ?? ""));
  await page.screenshot({ path: path.join(out, "doe_inputs_params_2560.png") });
  console.log(path.join(out, "doe_inputs_params_2560.png"));

  // (2) 미리보기 썸네일 격자
  await page.waitForFunction(() => document.querySelectorAll(".doe-thumb img").length > 10);
  await page.locator('section[aria-label^="④ 미리보기"]').screenshot({ path: path.join(out, "doe_preview_grid_2560.png") });
  console.log(path.join(out, "doe_preview_grid_2560.png"));

  // (3) 순위·민감도·3D 비교 — 요소 캡처 때 고정 상단 바가 겹치지 않게 정적으로
  await page.goto(DONE);
  await page.addStyleTag({ content: ".topbar, header { position: static !important; }" });
  await page.waitForSelector('table[aria-label="순위표"]');
  await page.waitForSelector('[data-testid="sens-r2"]');
  await page.waitForTimeout(1500);
  await page.locator('section[aria-label^="⑤ 결과"]').screenshot({ path: path.join(out, "doe_ranking_sensitivity_2560.png") });
  console.log(path.join(out, "doe_ranking_sensitivity_2560.png"));

  for (const [w, h] of [
    [1920, 1080],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width: w, height: h });
    for (const [name, url, ready] of [
      ["새 DOE", NEW, '[data-testid="doe-step-drop"]'],
      ["미리보기 완료", PREVIEW, 'ul[aria-label="미리보기 썸네일"]'],
      ["결과", DONE, 'table[aria-label="순위표"]'],
      ["라이브러리 DOE 탭", LIB, 'table[aria-label="비드 DOE 목록"]'],
    ]) {
      await page.goto(url);
      await page.waitForSelector(ready);
      await page.waitForTimeout(400);
      const r = await page.evaluate(() => {
        const de = document.documentElement;
        const cut = [...document.querySelectorAll(".card")].filter((c) => c.getBoundingClientRect().right > de.clientWidth + 1).length;
        const wraps = [...document.querySelectorAll(".table-wrap")].filter((t) => t.scrollWidth > t.clientWidth + 1).length;
        return { hScroll: de.scrollWidth > de.clientWidth + 1, cut, wraps };
      });
      const ok = !r.hScroll && r.cut === 0 && r.wraps === 0;
      if (!ok) failed += 1;
      console.log(`${ok ? "OK  " : "FAIL"} ${w}×${h} ${name}: 가로 스크롤 ${r.hScroll ? "있음" : "없음"} · 잘린 카드 ${r.cut} · 표 가로 스크롤 ${r.wraps}`);
      if (!ok || name === "결과") await page.screenshot({ path: path.join(out, `check_${w}_${name.replace(/\s+/g, "_")}.png`), fullPage: true });
      if (name === "미리보기 완료") {
        // 썸네일 카드 내부: 그림(4:3)이 카드 안에 다 들어가고, 안 id·스킵 사유 배지가 카드 안에 보여야 함(검증 지적 — 카드 잘림)
        await page.waitForTimeout(800);
        const t = await page.evaluate(() =>
          [...document.querySelectorAll(".doe-thumb")].map((li) => {
            const lr = li.getBoundingClientRect();
            const img = li.querySelector(".doe-thumb-img").getBoundingClientRect();
            const cap = li.querySelector(".doe-thumb-cap");
            const cr = cap.getBoundingClientRect();
            const badge = cap.querySelector(".badge");
            const br = badge?.getBoundingClientRect();
            const inside = (r) => r.height > 0 && r.top >= lr.top - 0.5 && r.bottom <= lr.bottom + 0.5 && r.right <= lr.right + 0.5;
            return { id: li.dataset.testid, status: li.dataset.status, imgOk: inside(img) && Math.abs(img.width / img.height - 4 / 3) < 0.05, capOk: inside(cr) && !!cap.textContent?.trim(), badgeOk: !badge || inside(br), skipped: li.classList.contains("skipped") };
          }),
        );
        const bad = t.filter((x) => !x.imgOk || !x.capOk || !x.badgeOk || (x.skipped && !x.badgeOk));
        const skippedWithBadge = t.filter((x) => x.skipped).length;
        const okT = t.length > 0 && bad.length === 0;
        if (!okT) failed += 1;
        console.log(`${okT ? "OK  " : "FAIL"} ${w}×${h} 썸네일 카드 ${t.length}개: 그림·안 id·배지 보임${bad.length ? ` — 잘림 ${JSON.stringify(bad.slice(0, 3))}` : ""} (스킵 배지 ${skippedWithBadge})`);
        if (!okT) await page.locator('ul[aria-label="미리보기 썸네일"]').screenshot({ path: path.join(out, `check_${w}_thumbs.png`) });
      }
    }
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
