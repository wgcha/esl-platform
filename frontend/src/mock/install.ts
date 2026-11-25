// npm run dev:mock / build:mock 전용: window.fetch를 목 서버로 바꾸고 2초마다 작업을 진행시킨다.
// ?mockUser=admin|power|general 로 사용자 전환(localStorage에 기억), ?freeze=1 이면 진행 멈춤.
import { MockServer, createMockFetch } from "./server";
import { variantValidation, type MockUserKey } from "./data";

const KEY = "esl.mockUser";

export function installMockFetch() {
  const params = new URLSearchParams(window.location.search);
  let user = params.get("mockUser") as MockUserKey | null;
  try {
    if (user) localStorage.setItem(KEY, user);
    else user = localStorage.getItem(KEY) as MockUserKey | null;
  } catch {
    /* 저장소 없음 */
  }
  const server = new MockServer({ user: user ?? "power" });
  // 업로드 시연: ?chunkMB=1 청크 크기, ?uploadHang=N N개 청크 뒤 멈춤(진행 중 화면), ?seenVersion=0.3.0 마지막 본 버전
  const chunk = Number(params.get("chunkMB"));
  if (chunk > 0) server.p3.chunkSize = chunk * 1024 * 1024;
  const delay = Number(params.get("uploadDelayMs"));
  if (delay > 0) server.p3.putDelayMs = delay;
  const hang = params.get("uploadHang");
  if (hang !== null) server.p3.hangAfter = Number(hang);
  const seen = params.get("seenVersion");
  try {
    if (seen) localStorage.setItem("esl.lastSeenVersion", seen);
  } catch {
    /* 저장소 없음 */
  }
  // §6·§9 시연: ?demoH3d=1 서버 추출 진행 중인 h3d Case(c-<n>), ?demoPc=1 연결된 PC 2대
  if (params.get("demoH3d") === "1") server.demoH3dExtract();
  // v0.10.0 시연: ?demoSupportBlocked=<caseId> 자동 지지 BLOCKED, ?demoExportFail=<entryId,…> 내보내기 항목 실패
  const sb = params.get("demoSupportBlocked");
  if (sb) server.demoSupportBlocked(sb);
  for (const id of (params.get("demoExportFail") ?? "").split(",").filter(Boolean)) server.failExportEntries.add(id);
  // ?demoValidation=FAIL|UNDETERMINED|LEGACY_FAIL: 첫 검증(c-demo)을 바꿔 ④ 등록 거부 사유 시연
  const dv = params.get("demoValidation") as Parameters<typeof variantValidation>[1] | null;
  if (dv) server.validations[0] = variantValidation(server.validations[0], dv);
  // v0.24.3 ④ 검증 출처별 시연: ?demoValSrc=ok(출처 탭·판정 표식·한계) | notrun(출처 결과 없음 — 빈 탭 + [검증 다시 실행])
  const dvs = params.get("demoValSrc");
  if (dvs === "ok" || dvs === "notrun") server.valSourcesMode = dvs;
  // v0.24.4 지그 3방식 시연: ?demoJigRows=1 — ③ 3D·④ 검증 출처 행에 jig·jig_disp·jig_spring(고정·변위 가능, 스프링 = JIG_NOT_RUN). 없으면 옛 Case(4행)
  if (params.get("demoJigRows") === "1") server.jigRows = true;
  // v0.24.5 화면 출처 숨김 시연: ?hiddenSources=default(실서버 기본 bforce·fint·jig) | <키,키…> | (없음 = 숨김 없음 = v0.24.4 화면)
  const hs = params.get("hiddenSources");
  if (hs) server.p3.hiddenSources = hs === "default" ? ["bforce", "fint", "jig"] : hs.split(",").filter(Boolean);
  // v0.12.0 검증 낙하 시연: ?demoVerify=1 doe-1 에 완료·실행 중·결과 모름 검증 낙하, ?verifyMode=disabled|writes_off
  if (params.get("demoVerify") === "1") server.verify.seedDemo("doe-1");
  const vm = params.get("verifyMode");
  if (vm === "disabled" || vm === "writes_off") server.scx.verifyMode = vm;
  // v0.13.0 일괄 실행 시연: ?demoRunAll=running|tstar|blocked|failed|done — c-new 에 체인(진행 중 · ② t* 확인 멈춤 · ② 지지 BLOCKED · ③ 실패 · ④ PASS)
  const dra = params.get("demoRunAll");
  if (dra) {
    if (dra === "tstar") server.tstarAdjusted.add("c-new");
    if (dra === "blocked") server.supportBlocked.add("c-new");
    if (dra === "failed") server.failJobTypes.add("ESL_SOLVE");
    server.handle("POST", "/cases/c-new/run-all", new URLSearchParams(), {});
    if (dra === "running") server.tick();
    else server.drain();
  }
  // v0.17.1 경고 접기 시연: ?demoLadder=1 doe-12(③ STEP만 · 긴 사다리 경고) · doe-13(메시 실패 — 빨간 1줄)
  if (params.get("demoLadder") === "1") server.doe.demoLadder();
  // v0.17.3 PartView 시연: ?demoMeshSel=1 doe-14(② B 메시 select — 평면도 A 체결·하중·경계 경고 층)
  if (params.get("demoMeshSel") === "1") server.doe.demoMeshSel();
  // v0.18.0 ③ STEP 기준 select 시연: ?demoStepSel=1 doe-15(자동·저장됨) · doe-16(직접·삼각형) · doe-17(이전 방식 ③)
  if (params.get("demoStepSel") === "1") server.doe.demoStepSel();
  // v0.21.0 형상 규칙 시연: ?demoShape=1 doe-30(① 부분 W·guard) · doe-31(④ 완화 직행·메시 품질 ⚠) · doe-32(③ 기준 메시 품질 미달 띠)
  if (params.get("demoShape") === "1") server.doe.demoShape();
  // v0.24.7 깊이 단면 동작 시연: ?demoDepth=1 doe-30(깊이면 폭 유지 — D 배지·W 사유 줄·W1 꼬리표) · doe-6(복제 창 — 키 없음 = 입구 고정(이전))
  if (params.get("demoDepth") === "1") server.doe.demoDepth();
  // v0.23.0 지그 순위 시연: ?demoJig=1 doe-40(지그 ok) · doe-41(재현 미달) · doe-42(지그 불가 → 재풀이 C)
  if (params.get("demoJig") === "1") server.doe.demoJig();
  // v0.24.8 격자 지그 시연: ?demoJigGrid=1 doe-60(④ 격자 지그 — jd·js 3D·매핑 오차 표식) · doe-61(대조) · doe-62·63(옛 스냅샷 — 복제 안내 2종)
  if (params.get("demoJigGrid") === "1") server.doe.demoJigGrid();
  // v0.24.0 경계력 ESL 시연: ?demoBforce=1 doe-50(contact 등급 ok) · doe-51(경계력 자료 없음)
  if (params.get("demoBforce") === "1") server.doe.demoBforce();
  if (params.get("demoPc") === "1") {
    server.p3.addToken("p-body", "KIM-PC (DESKTOP-7F3K2)", "REVOKED");
    server.p3.addToken("p-body", "KIM-NOTEBOOK (LT-0412)");
  }
  window.fetch = createMockFetch(server, window.fetch.bind(window));
  if (params.get("freeze") !== "1") setInterval(() => server.tick(), 2000);
  (window as unknown as { __eslMock: MockServer }).__eslMock = server;
}
