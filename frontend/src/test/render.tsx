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

/** v0.23.1 단계 초점(esl_doe_ui_tidy.md §2)으로 접힌 카드를 펼친다 — 사용자가 카드 제목(펼치기)을 한 번 누르는 것과 같음 */
export async function openCard(title: string | RegExp) {
  const { screen, fireEvent } = await import("@testing-library/react");
  const name = typeof title === "string" ? new RegExp(`^${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`) : title;
  const b = await screen.findByRole("button", { name, expanded: false }, { timeout: 8000 });
  fireEvent.click(b);
  return b;
}
