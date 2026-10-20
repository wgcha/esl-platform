// npm run dev:mock / build:mock 전용: window.fetch를 목 서버로 바꾸고 2초마다 작업을 진행시킨다.
// ?mockUser=admin|power|general 로 사용자 전환(localStorage에 기억), ?freeze=1 이면 진행 멈춤.
import { MockServer, createMockFetch } from "./server";
import type { MockUserKey } from "./data";

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
  if (params.get("demoPc") === "1") {
    server.p3.addToken("p-body", "KIM-PC (DESKTOP-7F3K2)", "REVOKED");
    server.p3.addToken("p-body", "KIM-NOTEBOOK (LT-0412)");
  }
  window.fetch = createMockFetch(server, window.fetch.bind(window));
  if (params.get("freeze") !== "1") setInterval(() => server.tick(), 2000);
  (window as unknown as { __eslMock: MockServer }).__eslMock = server;
}
