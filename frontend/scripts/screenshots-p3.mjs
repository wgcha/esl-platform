// P3-UX mock 스크린샷(새 Case 올리기 진행 중·서버 폴더·업데이트 내역·사용 가이드·PC 연결 탭·① 서버 h3d 추출).
// 사용: npm run build:mock && npm run screenshots:p3 [-- <출력폴더>]   (SHOTS=a.png,b.png 이면 그 파일만 저장)
// Playwright는 설치하지 않고 환경의 것을 쓴다(PLAYWRIGHT_BROWSERS_PATH, 전역 playwright 모듈).
import { createRequire } from "node:module";
import { spawn, execSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

function loadPlaywright() {
  const candidates = [process.env.PLAYWRIGHT_MODULE, "playwright"].filter(Boolean);
  try {
    candidates.push(path.join(execSync("npm root -g").toString().trim(), "playwright"));
  } catch {
    /* 무시 */
  }
  for (const c of candidates) {
    try {
      return require(c);
    } catch {
      /* 다음 */
    }
  }
  throw new Error("playwright 모듈을 찾을 수 없습니다(PLAYWRIGHT_MODULE로 경로 지정).");
}

const { chromium } = loadPlaywright();
const port = 5186;
const out = path.resolve(process.argv[2] ?? path.join(root, "screenshots"));
mkdirSync(out, { recursive: true });

const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--mode", "mock", "--outDir", "dist-mock", "--port", String(port), "--strictPort", "--host", "127.0.0.1"],
  { cwd: root, stdio: "pipe" },
);
try {
  let exited = null;
  server.on("exit", (c) => (exited = c));
  const deadline = Date.now() + 30000;
  for (;;) {
    if (exited !== null) throw new Error(`preview 종료 ${exited}`);
    try {
      if ((await fetch(`http://127.0.0.1:${port}/esl/`)).ok) break;
    } catch {
      /* 아직 */
    }
    if (Date.now() > deadline) throw new Error("preview 서버 시작 시간 초과");
    await new Promise((r) => setTimeout(r, 300));
  }

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const base = `http://127.0.0.1:${port}/esl`;
  const only = (process.env.SHOTS ?? "").split(",").map((x) => x.trim()).filter(Boolean);
  const shot = async (name, full = true) => {
    if (only.length && !only.includes(name)) return;
    const file = path.join(out, name);
    await page.screenshot({ path: file, fullPage: full });
    console.log(file);
  };
  const buf = (n) => Buffer.alloc(n, 65);
  const MB = 1024 * 1024;

  // 1) 새 Case — 내 PC에서 올리기(진행 중): 청크 1 MB, 18청크 뒤 멈춤
  await page.goto(`${base}/p/p-body/cases/new?freeze=1&mockUser=power&chunkMB=1&uploadHang=18&uploadDelayMs=80&seenVersion=0.4.0`);
  await page.waitForSelector("button[data-primary]");
  await page.setInputFiles('input[aria-label="① rad · include 파일 파일"]', [
    { name: "QN80H_rear40_0000.rad", mimeType: "application/octet-stream", buffer: buf(3 * MB) },
    { name: "inc_mat.inc", mimeType: "application/octet-stream", buffer: buf(60 * 1024) },
    { name: "inc_mesh.inc", mimeType: "application/octet-stream", buffer: buf(2 * MB) },
  ]);
  await page.setInputFiles('input[aria-label="② h3d 결과 파일 파일"]', [{ name: "QN80H_rear40.h3d", mimeType: "application/octet-stream", buffer: buf(40 * MB) }]);
  await page.click('role=button[name="올리기"]');
  await page.waitForFunction(() => Number(document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow") ?? 0) >= 30, null, { timeout: 30000 });
  await page.waitForTimeout(700);
  await shot("newcase_upload_progress.png");

  // 2) 서버 폴더에서 고르기: rad + h3d 선택
  await page.goto(`${base}/p/p-body/cases/new?freeze=1&mockUser=power&seenVersion=0.4.0`);
  await page.waitForSelector("button[data-primary]");
  await page.click('role=tab[name="서버 폴더에서 고르기"]');
  await page.click('role=button[name="kim/"]');
  await page.click('role=button[name="20261019-031200_QN80H_rear40/"]');
  await page.click('role=button[name="rad/"]');
  await page.click('role=button[name="rad 선택"]');
  await page.waitForSelector('[aria-label="rad 확인 결과"]');
  await page.click('.browse-crumbs >> role=button[name="20261019-031200_QN80H_rear40"]');
  await page.click('role=button[name="h3d/"]');
  await page.click('role=button[name="h3d 선택"]');
  await page.fill('input[placeholder="QN80H_rear40"]', "QN80H_rear40");
  await page.waitForTimeout(400);
  await shot("newcase_server_folder.png");

  // 3) 업데이트 내역(새 버전 점이 있던 상태에서 진입)
  await page.goto(`${base}/updates?freeze=1&mockUser=power&seenVersion=0.3.0`);
  await page.waitForSelector("article.release");
  await page.waitForTimeout(400);
  await shot("updates.png");

  // 4) 사용 가이드(바로가기용 최근 Case 를 먼저 연다)
  await page.goto(`${base}/p/p-body/c/c-demo/stage/1?freeze=1&mockUser=power&seenVersion=0.4.0`);
  await page.waitForSelector("button[data-primary]");
  await page.goto(`${base}/guide?freeze=1&mockUser=power&seenVersion=0.3.0`);
  await page.waitForSelector("article.guide-card");
  await page.waitForTimeout(400);
  await shot("guide.png");

  // 5) ⑥ 내보내기 — 결과 받기(zip)
  await page.goto(`${base}/p/p-body/c/c-demo/stage/6?freeze=1&mockUser=power&seenVersion=0.4.0`);
  await page.waitForSelector("button[data-primary]");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);
  await shot("stage6_bundle.png", false);

  // 6) 새 Case — PC에서 추출해 올리기: 연결 코드 표시 + 연결된 PC 목록
  await page.goto(`${base}/p/p-body/cases/new?tab=pc&freeze=1&mockUser=power&demoPc=1&seenVersion=0.4.0`);
  await page.click('role=button[name="PC 연결 코드 만들기"]');
  await page.waitForSelector('[data-testid="pc-code"]');
  await page.waitForSelector('table[aria-label="연결된 PC"]');
  await page.waitForTimeout(1200);
  await shot("newcase_pc_connect.png");

  // 7) h3d 로 만든 Case ① — 서버에서 추출 중(HyperView) 단계·로그, 대기열 동시 실행 2/2
  await page.goto(`${base}/p/p-body?freeze=1&mockUser=power&demoH3d=1&seenVersion=0.4.0`);
  const h3dId = await page.evaluate(() => window.__eslMock.cases.find((c) => c.input_kind === "H3D").id);
  await page.goto(`${base}/p/p-body/c/${h3dId}/stage/1?freeze=1&mockUser=power&demoH3d=1&seenVersion=0.4.0`);
  await page.waitForSelector('[data-testid="h3d-extract-phase"]');
  await page.waitForSelector('[data-testid="queue-slots"]');
  await page.waitForFunction(() => /\[hw\]/.test(document.querySelector('[aria-label="작업 로그"]')?.textContent ?? ""));
  await page.waitForTimeout(500);
  await shot("stage1_h3d_extract.png");
  await browser.close();
} finally {
  server.kill();
}
