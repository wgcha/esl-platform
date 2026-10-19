// /status config.errors = {key, message}[] (백엔드 ConfigIssue) 표시
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { RightPanel } from "../shell/RightPanel";
import { MockServer, createMockFetch } from "../mock/server";

describe("RightPanel 설정 오류", () => {
  it("config.errors 의 key·message 를 표시", async () => {
    const server = new MockServer();
    server.configErrors = [{ key: "storage.esl_root", message: "절대경로여야 합니다" }];
    globalThis.fetch = createMockFetch(server);
    render(
      <MemoryRouter>
        <RightPanel />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/설정 오류: storage\.esl_root: 절대경로여야 합니다/)).toBeTruthy();
  });
});
