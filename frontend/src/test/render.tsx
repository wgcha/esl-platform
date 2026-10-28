import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "../app/App";
import { MockServer, createMockFetch } from "../mock/server";
import type { MockUserKey } from "../mock/data";

/** 목 서버를 fetch에 끼우고 앱을 path에서 렌더 */
export function renderApp(path: string, user: MockUserKey = "power", setup?: (server: MockServer) => void) {
  const server = new MockServer({ user });
  setup?.(server);
  globalThis.fetch = createMockFetch(server);
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  return { server, ...view };
}
