// #49 Case 목록 진행 칸: 4단계 점(①입력 ②t*·지지점 ③ESL ④검증, 스텝퍼 점 색 규칙) + 툴팁(단계명·상태·사유) + 라이브러리 등록 배지.
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { App } from "../app/App";
import { MockServer, createMockFetch } from "../mock/server";
import { StepDots } from "../shell/StageStepper";
import type { StepStatus } from "../api/types";

const STEPS: StepStatus = {
  input: { state: "done", job_id: "j1" },
  tstar: { state: "failed", job_id: null, reason: { code: "SUPPORT_AUTO_BLOCKED", message: "지지점을 자동으로 정하지 못했습니다" } },
  esl: { state: "running", job_id: "j3" },
  validate: { state: "stale", job_id: null },
};

describe("#49 StepDots", () => {
  it("점 4개 — 상태별 색(ok·bad·run·wait·off)·툴팁(단계명+상태+사유)", () => {
    const { container } = render(<StepDots c={{ step_status: STEPS }} />);
    const dots = [...container.querySelectorAll(".step-dot")] as HTMLElement[];
    expect(dots).toHaveLength(4);
    expect(dots.map((d) => d.dataset.state)).toEqual(["done", "failed", "running", "stale"]);
    expect(dots.map((d) => d.querySelector(".dot")!.className)).toEqual(["dot ok", "dot bad", "dot run", "dot wait"]);
    expect(dots[0].title).toBe("① 입력: 완료");
    expect(dots[1].title).toBe("② t*·지지점: 실패 — 지지점을 자동으로 정하지 못했습니다");
    expect(dots[2].title).toBe("③ ESL: 실행 중");
    expect(dots[3].title).toBe("④ 검증: 이전 단계 변경됨");
  });
  it("상태 없음 → 모두 off(없음)", () => {
    const { container } = render(<StepDots c={{ step_status: null, stage_status: null }} />);
    const dots = [...container.querySelectorAll(".step-dot")] as HTMLElement[];
    expect(dots.map((d) => d.querySelector(".dot")!.className)).toEqual(Array(4).fill("dot off"));
    expect(dots[3].title).toBe("④ 검증: 없음");
  });
});

describe("#49 Case 목록", () => {
  it("진행 칸 = 점 4개 + 등록 배지(등록됨 N / 없음), '시작 전' 문구 없음", async () => {
    const server = new MockServer({ user: "power" });
    globalThis.fetch = createMockFetch(server);
    render(
      <MemoryRouter initialEntries={["/p/p-body"]}>
        <App />
      </MemoryRouter>,
    );
    const demo = server.cases.find((c) => c.id === "c-demo")!;
    const link = await screen.findByRole("link", { name: demo.title });
    const row = link.closest("tr")!;
    const dots = row.querySelectorAll(".step-dot");
    expect(dots).toHaveLength(4);
    // c-demo 는 검증까지 끝난 Case — 점이 off 만은 아님
    expect([...dots].some((d) => (d as HTMLElement).dataset.state === "done")).toBe(true);
    const n = server.entries.filter((e) => e.case_id === "c-demo" && e.status === "ACTIVE").length;
    expect(n).toBeGreaterThan(0);
    expect(within(row).getByTestId("lib-badge").textContent).toBe(`라이브러리 등록됨 ${n}`);
    expect(within(row).getByTestId("lib-badge").getAttribute("title")).toMatch(/^최신 등록 판정: /);
    const fresh = server.cases.find((c) => !server.entries.some((e) => e.case_id === c.id && e.status === "ACTIVE") && c.project_id === "p-body")!;
    const frow = (await screen.findByRole("link", { name: fresh.title })).closest("tr")!;
    expect(within(frow).getByTestId("lib-badge").textContent).toBe("라이브러리 없음");
    await waitFor(() => expect(screen.queryByText("시작 전")).toBeNull());
  });
});
