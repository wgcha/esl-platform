// v0.17.1 "③ STEP만 메싱 뒤 주황 경고·로그가 너무 길다": 경고·정보 = 요약 1줄(기본 접힘) "⚠ 경고 N건 · 정보 M건 — 자세히",
// 누르면 목록(항목마다 접기, 긴 글 = 높이 고정 스크롤 상자), 펼침 상태 = 스터디별 sessionStorage. 막는 실패 = 빨간 1줄 + [자세히].
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { BlockErr, MsgFold, foldCounts, msgHead } from "../components/MsgFold";
import { LADDER_FAIL_TEXT, LADDER_WARNINGS } from "../mock/doedata";
import { isInfoWarn, warnText } from "../api/doe";

const items = LADDER_WARNINGS.map((w) => ({ text: warnText(w), info: isInfoWarn(w) }));

describe("MsgFold(요약 1줄)", () => {
  it("머리말: 앞의 [단계별: …] 를 빼고 첫 줄만, 개수 = 경고·정보", () => {
    expect(msgHead("[단계별: cad 실패 1.0 s → tria 성공 2.0 s] CAD 메시 실패: x\n둘째 줄")).toBe("CAD 메시 실패: x");
    expect(msgHead("[x]")).toBe("[x]");
    expect(foldCounts(items)).toEqual({ warn: 4, info: 2 });
  });

  it("기본 접힘 · 클릭하면 펼침(항목마다 접기, 긴 글은 스크롤 상자) · 개수 정확 · 상태는 sessionStorage", () => {
    const { unmount } = render(<MsgFold items={items} storeKey="doe-x:prep" testId="f" />);
    const f = screen.getByTestId("f");
    expect(screen.getByTestId("f-count").textContent).toBe("⚠ 경고 4건 · 정보 2건");
    // 머리말 = 가장 중요한 항목(첫 경고) — [단계별: …] 는 빼고
    expect(f.querySelector(".msg-fold-head")!.textContent).toMatch(/^CAD 면 경계를 따르지 않는 freeform 재메시/);
    expect(f.textContent).not.toMatch(/단계별/);
    expect(screen.queryByRole("list", { name: "경고·정보 목록" })).toBeNull();
    const line = within(f).getByRole("button", { name: /자세히/ });
    expect(line.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(line);
    expect(line.getAttribute("aria-expanded")).toBe("true");
    const list = screen.getByRole("list", { name: "경고·정보 목록" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(6);
    // 긴 사다리 항목: 머리말만 → 누르면 전체(스크롤 상자)
    expect(list.textContent).not.toMatch(/\[단계별: cad 실패 412\.3 s/);
    const entry = within(list).getAllByRole("button", { expanded: false })[0];
    fireEvent.click(entry);
    expect(list.querySelector(".msg-fold-body")!.textContent).toMatch(/^\[단계별: cad 실패 412\.3 s → .* freeform 성공 131\.7 s\] CAD 면 경계를/);
    expect(window.sessionStorage.getItem("esl.msgfold.doe-x:prep")).toBe("1");
    unmount();
    // 같은 스터디 = 펼친 채로 다시 그림, 다른 스터디 = 접힘
    render(<MsgFold items={items} storeKey="doe-x:prep" testId="g" />);
    expect(screen.getByRole("list", { name: "경고·정보 목록" })).toBeTruthy();
    render(<MsgFold items={items} storeKey="doe-y:prep" testId="h" />);
    expect(within(screen.getByTestId("h")).queryByRole("list")).toBeNull();
  });

  it("정보만 있으면 ⓘ, 빈 목록이면 아무것도 없음", () => {
    render(<MsgFold items={[{ text: "a", info: true }]} testId="i" />);
    expect(screen.getByTestId("i-count").textContent).toBe("ⓘ 경고 0건 · 정보 1건");
    const { container } = render(<MsgFold items={[]} testId="j" />);
    expect(container.innerHTML).toBe("");
  });

  it("막는 오류 = 빨간 1줄 제목 + [자세히](내용 접힘)", () => {
    render(<BlockErr title="준비 실패" detail={LADDER_FAIL_TEXT} testId="b" />);
    const b = screen.getByTestId("b");
    expect(b.getAttribute("role")).toBe("alert");
    expect(b.textContent).toBe("✗ 준비 실패자세히");
    fireEvent.click(within(b).getByRole("button", { name: "자세히" }));
    expect(b.textContent).toMatch(/\[단계별: cad 실패/);
  });
});

describe("DOE 화면(③ STEP만 · 사다리 경고 시연 doe-12·13)", () => {
  it("doe-12: 준비 경고 = 요약 1줄(경고 6 · 정보 2, 기본 접힘) → 클릭하면 펼침", async () => {
    renderApp("/p/p-body/doe/doe-12", "power", (s) => s.doe.demoLadder());
    const f = await screen.findByTestId("prep-warn", undefined, { timeout: 4000 });
    // LADDER 4 경고 + 2 정보 + PARAM_WARNINGS 2 경고
    expect(within(f).getByTestId("prep-warn-count").textContent).toBe("⚠ 경고 6건 · 정보 2건");
    expect(within(f).queryByRole("list")).toBeNull();
    expect(f.textContent).not.toMatch(/MESH_TRIA_FALLBACK|OCC 삼각화/);
    fireEvent.click(within(f).getByRole("button", { name: /자세히/ }));
    expect(within(f).getAllByRole("listitem")).toHaveLength(8);
    expect(f.textContent).toMatch(/OCC 삼각화\(BRepMesh/);
  });

  it("doe-13: 준비 실패(사다리 문구) = 빨간 1줄(짧은 제목) + [자세히] → 전체 문구·[로그 보기]", async () => {
    renderApp("/p/p-body/doe/doe-13", "power", (s) => s.doe.demoLadder());
    const b = await screen.findByTestId("job-fail-banner", undefined, { timeout: 4000 });
    expect(b.querySelector(".block-err-title")!.textContent).toMatch(/^✗ 강성 평가 준비 실패 · 단계 2 베이스라인 메시 · MESH_FAILED · CAD 메시 실패: gmsh/);
    expect(b.textContent).not.toMatch(/\[단계별/);
    expect(screen.queryByTestId("job-fail-msg")).toBeNull();
    fireEvent.click(within(b).getByRole("button", { name: "자세히" }));
    await waitFor(() => expect(screen.getByTestId("job-fail-msg").textContent).toMatch(/\[단계별: cad 실패 412\.3 s/));
    expect(within(b).getByRole("button", { name: "로그 보기" })).toBeTruthy();
    // ① 입력 카드 진행 패널: 실패 문구 1줄(머리말), 작업 로그는 [로그 보기] 전까지 접힘
    const prog = await screen.findByTestId("job-progress", undefined, { timeout: 4000 });
    expect(prog.querySelector(".job-fail-one")!.textContent).toMatch(/^MESH_FAILED — CAD 메시 실패/);
    expect(within(prog).queryByLabelText("작업 로그")).toBeNull();
    fireEvent.click(within(prog).getByRole("button", { name: "로그 보기" }));
    expect(within(prog).getByLabelText("작업 로그")).toBeTruthy();
  });
});
