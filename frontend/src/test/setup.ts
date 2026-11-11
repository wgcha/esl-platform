import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

(globalThis as unknown as { __MOCK__: boolean }).__MOCK__ = false;
afterEach(() => {
  cleanup();
  // v0.17.1 경고 접기 상태(sessionStorage)가 다음 시험으로 새지 않게
  try {
    window.sessionStorage.clear();
  } catch {
    /* 저장소 없음 */
  }
});
