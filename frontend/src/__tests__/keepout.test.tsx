// V-OR-18(금지 영역): 사각형 4 기준 모서리 좌표 변환, 평면도 드래그 ↔ 숫자 동기화, 방향키 이동, 세트 불러오기/저장·충돌 메시지.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { KeepoutPlan, changeCorner, dragRect, placeRect, rectBox, rectProblem, type Frame } from "../components/KeepoutPlan";
import type { KeepoutRect, PlanViewOut, RectCorner } from "../api/types";

const F: Frame = { a_range: [0, 1000], b_range: [0, 600] };
const R = (corner: RectCorner): KeepoutRect => ({ name: "PCB", corner, x_mm: 120, y_mm: 80, w_mm: 300, h_mm: 200 });

describe("사각형 좌표(§5.2 Rect, §7.5)", () => {
  it("4 기준 모서리 → 상자", () => {
    expect(rectBox(R("a0b0"), F)).toEqual([120, 420, 80, 280]);
    expect(rectBox(R("a1b0"), F)).toEqual([580, 880, 80, 280]);
    expect(rectBox(R("a0b1"), F)).toEqual([120, 420, 320, 520]);
    expect(rectBox(R("a1b1"), F)).toEqual([580, 880, 320, 520]);
    // frame 원점이 0 이 아니어도
    expect(rectBox(R("a1b1"), { a_range: [-500, 500], b_range: [10, 610] })).toEqual([80, 380, 330, 530]);
  });

  it("상자 → X·Y(역변환, 1 mm 반올림), 모서리 바꿔도 위치 유지", () => {
    for (const c of ["a0b0", "a1b0", "a0b1", "a1b1"] as RectCorner[]) {
      const r = R(c);
      const [alo, , blo] = rectBox(r, F);
      expect(placeRect(r, F, alo, blo)).toEqual(r);
      const moved = placeRect(r, F, alo + 10.4, blo - 5.6);
      const [a2, , b2] = rectBox(moved, F);
      expect(Math.abs(a2 - (alo + 10.4))).toBeLessThanOrEqual(0.6);
      expect(Math.abs(b2 - (blo - 5.6))).toBeLessThanOrEqual(0.6);
    }
    const r = changeCorner(R("a0b0"), F, "a1b1");
    expect(r).toMatchObject({ corner: "a1b1", x_mm: 580, y_mm: 320 });
    expect(rectBox(r, F)).toEqual(rectBox(R("a0b0"), F));
  });

  it("드래그는 경계 안으로 제한, 값 검사", () => {
    const r = R("a0b0");
    expect(dragRect(r, F, [120, 80], -500, 9999)).toMatchObject({ x_mm: 0, y_mm: 400 });
    expect(dragRect(R("a1b1"), F, [580, 320], 50, -20)).toMatchObject({ x_mm: 70, y_mm: 100 });
    expect(rectProblem(r, F)).toBeNull();
    expect(rectProblem({ ...r, w_mm: 0 }, F)).toMatch(/가로/);
    expect(rectProblem({ ...r, x_mm: -1 }, F)).toMatch(/X·Y/);
    expect(rectProblem({ ...r, x_mm: 2000 }, F)).toMatch(/경계 밖/);
    expect(rectProblem({ ...r, name: " " }, F)).toMatch(/이름/);
  });
});

describe("평면도 자동 영역 kinds(서버 PlanViewAuto.kinds)", () => {
  const plan = (kinds: ("hole" | "edge")[] | undefined): PlanViewOut => ({
    key: { template_id: "t", topo_sha256: null },
    frame: { a_range: [0, 100], b_range: [0, 60] },
    outline: [[0, 0], [100, 0], [100, 60], [0, 60]],
    holes: [],
    elems: { n_total: 0, decimated: false, points: [] },
    auto_keepout: { hole_radius_mm: 15, edge_band_mm: 10, polygons: [[[0, 0], [100, 0], [100, 60]], [[40, 20], [50, 20], [50, 30]]], kinds },
  });
  const draw = (kinds: ("hole" | "edge")[] | undefined) =>
    render(<KeepoutPlan plan={plan(kinds)} value={{ rects: [], auto: { hole: true, edge: true } }} onChange={() => {}} selected={null} onSelect={() => {}} />);

  it("kinds 가 polygons 와 같은 길이면 구멍·가장자리 따로, 비었거나(구 캐시) 길이가 다르면 한 경로", () => {
    draw(["edge", "hole"]);
    expect(screen.getByTestId("ko-auto-hole")).toBeTruthy();
    expect(screen.getByTestId("ko-auto-edge").getAttribute("d")!.match(/M/g)).toHaveLength(1);
    cleanup();
    draw([]);
    expect(screen.queryByTestId("ko-auto-hole")).toBeNull();
    expect(screen.getByTestId("ko-auto-edge").getAttribute("d")!.match(/M/g)).toHaveLength(2);
    cleanup();
    draw(["edge"]);
    expect(screen.queryByTestId("ko-auto-hole")).toBeNull();
  });
});

const S1 = "/p/p-body/opt/new?entries=le-1,le-2,le-3";

/** jsdom 은 배치가 없어 svg 화면 크기를 viewBox 와 같게(1px = 1mm) 둔다 */
function sizeSvg() {
  const svg = screen.getByRole("img", { name: "비드 금지 영역 평면도" }) as unknown as SVGSVGElement;
  const [x, y, w, h] = svg.getAttribute("viewBox")!.split(" ").map(Number);
  svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: w, height: h, right: w, bottom: h, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
  return { x, y };
}
const num = (name: string) => (screen.getByRole("spinbutton", { name }) as HTMLInputElement).value;

describe("금지 영역 편집기(OptNew ② 카드)", () => {
  it("저장된 세트 자동 불러오기 → 평면도 드래그 ↔ X·Y 숫자 동기화, 방향키 1 mm", async () => {
    renderApp(S1);
    await waitFor(() => expect(screen.getByTestId("keepout-status").textContent).toMatch(/저장된 세트 불러옴.*차완기/));
    expect(num("PCB X")).toBe("120");
    expect(num("PCB Y")).toBe("80");
    // 자동 영역(구멍·가장자리) 회색 빗금 표시, 끄면 사라짐
    expect(screen.getByTestId("ko-auto-hole")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: /구멍 주변 15 mm/ }));
    expect(screen.queryByTestId("ko-auto-hole")).toBeNull();
    expect(screen.getByTestId("ko-auto-edge")).toBeTruthy();

    sizeSvg();
    const g = screen.getByTestId("ko-rect-0");
    const svg = screen.getByRole("img", { name: "비드 금지 영역 평면도" });
    fireEvent.mouseDown(g, { clientX: 400, clientY: 300 });
    fireEvent.mouseMove(svg, { clientX: 450, clientY: 280 }); // 오른쪽 50, 위 20 (화면 y 아래가 +)
    fireEvent.mouseUp(svg);
    expect(num("PCB X")).toBe("170");
    expect(num("PCB Y")).toBe("100");
    // 숫자 → 평면도
    fireEvent.change(screen.getByRole("spinbutton", { name: "PCB X" }), { target: { value: "300" } });
    expect(g.querySelector("rect")!.getAttribute("x")).toBe("300");
    // 방향키(1 mm, Shift 10 mm)
    fireEvent.keyDown(g, { key: "ArrowRight" });
    expect(num("PCB X")).toBe("301");
    fireEvent.keyDown(g, { key: "ArrowDown", shiftKey: true });
    expect(num("PCB Y")).toBe("90");
    // 기준 모서리 바꾸기: 위치 그대로(상자 x 같음), 새 모서리 기준 X·Y
    const x0 = Number(g.querySelector("rect")!.getAttribute("x"));
    fireEvent.change(screen.getByRole("combobox", { name: "PCB 기준 모서리" }), { target: { value: "a1b1" } });
    expect(Math.abs(Number(g.querySelector("rect")!.getAttribute("x")) - x0)).toBeLessThanOrEqual(1);
    expect(Number(num("PCB X"))).toBeGreaterThan(1000);
    // 우상 기준에서 드래그 오른쪽 = X 감소
    const before = Number(num("PCB X"));
    fireEvent.mouseDown(g, { clientX: 100, clientY: 100 });
    fireEvent.mouseMove(svg, { clientX: 130, clientY: 100 });
    fireEvent.mouseUp(svg);
    expect(Number(num("PCB X"))).toBe(before - 30);
  });

  it("＋사각형·삭제, 잘못된 값이면 저장·실행 비활성, 저장 → version 증가, 동시 수정 충돌 메시지", async () => {
    const { server, container } = renderApp(S1);
    await waitFor(() => expect(screen.getByTestId("keepout-status").textContent).toMatch(/불러옴/));
    fireEvent.click(screen.getByRole("button", { name: "＋사각형" }));
    expect(screen.getByRole("textbox", { name: "사각형 2 이름" })).toBeTruthy();
    fireEvent.change(screen.getByRole("spinbutton", { name: "영역2 가로" }), { target: { value: "0" } });
    expect((await screen.findAllByText(/금지 사각형 '영역2': 가로·세로 > 0/)).length).toBeGreaterThan(0);
    const save = screen.getByRole("button", { name: "이 모델에 저장" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    const primary = container.querySelector("button[data-primary]") as HTMLButtonElement;
    expect(primary.disabled).toBe(true);
    expect(primary.closest(".primary-wrap")!.getAttribute("title")).toMatch(/영역2/);
    fireEvent.change(screen.getByRole("spinbutton", { name: "영역2 가로" }), { target: { value: "120" } });
    await waitFor(() => expect(save.disabled).toBe(false));
    fireEvent.click(save);
    await screen.findByText(/저장했습니다/);
    const key = [...server.opt.keepouts.keys()].find((k) => k.startsWith("topo:"))!;
    expect(server.opt.keepouts.get(key)!.version).toBe(4);
    expect(server.opt.keepouts.get(key)!.rects.map((r) => r.name)).toEqual(["PCB", "영역2"]);
    // 다른 사용자가 먼저 저장(version 5) → 내 저장은 409
    server.opt.keepouts.get(key)!.version = 5;
    fireEvent.click(within(screen.getByRole("table", { name: "금지 사각형" })).getAllByRole("button", { name: "삭제" })[1]);
    fireEvent.click(save);
    await waitFor(() => expect(screen.getAllByRole("alert").some((a) => /다른 사용자가 먼저 저장/.test(a.textContent ?? ""))).toBe(true));
  });

  it("세트 없으면(404) 빈 세트 — 템플릿 탭은 '이 템플릿에 저장'", async () => {
    renderApp("/p/p-body/opt/new?entries=le-1,le-2&tab=S2");
    await waitFor(() => expect((screen.getByRole("combobox", { name: "템플릿" }) as HTMLSelectElement).value).toBe("tpl-1"));
    await waitFor(() => expect(screen.getByTestId("keepout-status").textContent).toBe("저장된 세트 없음"));
    expect(screen.getByRole("button", { name: "이 템플릿에 저장" })).toBeTruthy();
    expect(screen.getByText(/사각형 없음/)).toBeTruthy();
  });
});
