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
  window.fetch = createMockFetch(server, window.fetch.bind(window));
  if (params.get("freeze") !== "1") setInterval(() => server.tick(), 2000);
  (window as unknown as { __eslMock: MockServer }).__eslMock = server;
}
