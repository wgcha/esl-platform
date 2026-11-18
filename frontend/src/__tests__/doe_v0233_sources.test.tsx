// V-0233-8b(esl_jig_view.md §2.1 출처 표): 화면은 LOAD_SOURCES 의 행만 읽는다 — 한 행(전 노드 ESL)을 지우면 탭이 하나만 남고 화면이 깨지지 않음.
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../test/render";

vi.mock("../pages/doe/doeTabs", async (orig) => {
  const m = await orig<typeof import("../pages/doe/doeTabs")>();
  return { ...m, LOAD_SOURCES: m.LOAD_SOURCES.filter((s) => s.key !== "full") };
});

afterEach(cleanup);

describe("출처 표 한 행 제거", () => {
  it("doe-40: 탭 1개(지그 ESL)·순위표·3D·상태 띠 정상, 전 노드 값 없음", async () => {
    renderApp("/p/p-body/doe/doe-40", "power", (s) => s.doe.demoJig());
    const t = await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const seg = await screen.findByTestId("doe-load-tab");
    expect([...seg.querySelectorAll("button")].map((b) => b.getAttribute("data-tab"))).toEqual(["jig"]);
    await waitFor(() => expect(within(t).getAllByRole("columnheader").map((h) => h.textContent?.trim())).toContain("지그 C"));
    expect(screen.getByTestId("jig-line")).toBeTruthy();
    expect(screen.getByTestId("v3d-jig-mode")).toBeTruthy();
    expect(screen.queryByTestId("lt-summary")).toBeNull();
  }, 30000);
  it("doe-21(지그 미계산 — 주 출처 행 없음): 남은 출처 탭 1개(비활성) + 사유 칩, 화면 유지", async () => {
    renderApp("/p/p-body/doe/doe-21");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const seg = await screen.findByTestId("doe-load-tab");
    const btns = [...seg.querySelectorAll("button")];
    expect(btns.map((b) => b.getAttribute("data-tab"))).toEqual(["jig"]);
    expect((btns[0] as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("jig-line").getAttribute("data-status")).toBe("none");
  }, 30000);
});
