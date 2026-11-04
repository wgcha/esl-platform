// v0.15.1 회귀(esl_bead_select.md §3-3·§11): 저장 선택이 없는 select 스터디에서 [+ 비드] → 바닥 클릭 → [사면·경계 자동] → [선택 저장] 하면
// 변수 표(DoeParamTable B1 D1 …)가 열려야 한다. 원인(v0.15.0): 저장 직후 GET selection 응답이 오기 전 이전 값({v: null})을 보고
// '기준 메시 바뀜(SELECTION_DROPPED)'으로 잘못 판정해 변수 표·평면도를 숨겼다. 저장 전에는 다음 단계 안내, 변수 0개면 사유를 보인다.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LABEL, selMesh } from "../mock/selectmock";

const h = vi.hoisted(() => ({ pickElem: -1, markers: [] as (Float32Array | null)[] }));
vi.mock("../view3d/webgl", () => ({ hasWebGL: () => true }));
vi.mock("../view3d/loadThree", () => ({
  loadScene: async () => ({
    createScene: () => {
      const nop = () => undefined;
      let proj = "ortho";
      return {
        setGeometry: nop, setColors: nop, setDeform: nop, setArrows: nop, setSupports: nop, select: nop, focus: nop, fit: nop, setView: nop,
        setProjection: (p: string) => (proj = p), projection: () => proj, onPick: nop, stats: () => ({ renders: 0 }), dispose: nop,
        setColorMap: nop, setElements: nop, setElemColors: nop, setOverlayLines: nop,
        setMarkers: (p: Float32Array | null) => h.markers.push(p),
        pickElem: () => (h.pickElem >= 0 ? { elem: h.pickElem, point: [0, 0, 0] } : null),
      };
    },
  }),
}));

import { renderApp } from "../test/render";

// jsdom 에는 PointerEvent 가 없다 — MouseEvent 로 흉내(button·clientX 전달)
if (typeof globalThis.PointerEvent === "undefined") {
  (globalThis as { PointerEvent?: unknown }).PointerEvent = class extends MouseEvent {
    pointerId = 1;
  };
}

const primary = (c: HTMLElement) => c.querySelector("button[data-primary]") as HTMLButtonElement;

beforeEach(() => {
  const m = selMesh();
  h.pickElem = [...m.label.keys()].find((e) => m.label[e] === LABEL.b1t1) ?? -1;
});

describe("select: 저장 선택 없음 → 선택 저장 → 변수 표", () => {
  it("저장 전 안내 한 줄, 저장 후 SELECTION_DROPPED 오판 없이 변수 표(B1 D1)", async () => {
    const r = renderApp("/p/p-body/doe/doe-5", "power", (s) => {
      s.doe.recs.find((x) => x.out.id === "doe-5")!.sel = null;
    });
    await waitFor(() => expect(screen.getByTestId("bs-host").getAttribute("data-phase")).toBe("ready"));
    // 저장 전: 변수 표 자리에 다음 단계 안내
    expect(screen.getByTestId("vars-next").textContent).toMatch(/\[사면·경계 자동\] → \[선택 저장\]/);
    // 시점 툴바(v0.15.1): 선택 없으면 '선택 영역에 맞추기' 비활성
    const fitSel = () => screen.getByRole("button", { name: "선택 영역에 맞추기" }) as HTMLButtonElement;
    expect(screen.getByRole("toolbar", { name: "시점" })).toBeTruthy();
    expect(fitSel().disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "+ 비드" }));
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy());
    const host = screen.getByTestId("bs-host");
    fireEvent.pointerDown(host, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerUp(host, { button: 0, clientX: 10, clientY: 10 });
    await waitFor(() => expect(primary(r.container).disabled).toBe(false));
    expect(fitSel().disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "사면·경계 자동" }));
    await waitFor(() => expect(screen.getByTestId("bead-b1").textContent).toMatch(/D 22\.0/));
    expect(primary(r.container).textContent).toBe("선택 저장");
    fireEvent.click(primary(r.container));
    await waitFor(() => expect(screen.getByTestId("param-B1_D1")).toBeTruthy());
    expect(screen.queryByTestId("selection-dropped")).toBeNull();
    expect(screen.queryByTestId("vars-next")).toBeNull();
    expect(primary(r.container).textContent).toBe("미리보기");
  });

  it("변수 0개(경고) → 사유 표시", async () => {
    renderApp("/p/p-body/doe/doe-5", "power", (s) => {
      const rec = s.doe.recs.find((x) => x.out.id === "doe-5")!;
      rec.sel!.derived.beads = rec.sel!.derived.beads.map((b) => ({ ...b, tiers: [], range_default: { D: {}, W: null } as never, warnings: [{ code: "SELECT_WIDTH_UNDEFINED" }] }));
    });
    await waitFor(() => expect(screen.getByTestId("vars-empty")).toBeTruthy());
    expect(screen.getByTestId("vars-empty").textContent).toMatch(/변수가 없습니다 — .*국부 폭을 잴 수 없어/);
  });

  it("지우개·층 비우기·비드 ✕·단 삭제(v0.15.1): 확인 후 지움, Ctrl+Z 로 되돌림, 저장 선택이 있으면 '선택 변경됨' + 미리보기 무효", async () => {
    const r = renderApp("/p/p-body/doe/doe-6", "power");
    await waitFor(() => expect(screen.getByTestId("bs-host").getAttribute("data-phase")).toBe("ready"));
    await waitFor(() => expect(screen.getByTestId("bead-b2")).toBeTruthy());
    const okConfirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    // 지우개: 안내 반영 · 클릭 = 빼기
    const er = screen.getByTestId("bs-eraser");
    fireEvent.click(er);
    expect(er.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("bs-hint").textContent).toMatch(/지우개 켜짐/);
    const host = screen.getByTestId("bs-host");
    const floor = () => screen.getByTestId("bead-b1").textContent ?? "";
    expect(floor()).toMatch(/단1 바닥 [1-9]/);
    fireEvent.pointerDown(host, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerUp(host, { button: 0, clientX: 10, clientY: 10 });
    await waitFor(() => expect(floor()).toMatch(/단1 바닥 0/));
    await waitFor(() => expect(screen.getByTestId("selection-stale")).toBeTruthy());
    expect(primary(r.container).textContent).toBe("선택 저장");
    fireEvent.keyDown(host, { key: "z", ctrlKey: true });
    await waitFor(() => expect(floor()).toMatch(/단1 바닥 [1-9]/));
    fireEvent.click(er);
    // 단 삭제(마지막 단만) → 되돌림
    fireEvent.click(screen.getByRole("button", { name: "단 2 삭제" }));
    await waitFor(() => expect(floor()).not.toMatch(/단2 바닥/));
    fireEvent.keyDown(host, { key: "z", ctrlKey: true });
    await waitFor(() => expect(floor()).toMatch(/단2 바닥/));
    // 층 비우기(확인 문구)
    fireEvent.click(screen.getByRole("button", { name: "층 비우기" }));
    expect(okConfirm.mock.calls[okConfirm.mock.calls.length - 1]?.[0]).toMatch(/단 1 바닥' 층의 요소를 모두 비웁니다/);
    await waitFor(() => expect(floor()).toMatch(/단1 바닥 0/));
    fireEvent.keyDown(host, { key: "z", ctrlKey: true });
    await waitFor(() => expect(floor()).toMatch(/단1 바닥 [1-9]/));
    // 비드 삭제: 취소하면 그대로, 확인하면 지움(변수 b1 이름 문구) → Ctrl+Z
    okConfirm.mockReturnValueOnce(false);
    fireEvent.click(screen.getByRole("button", { name: "B1 삭제" }));
    expect(screen.getByTestId("bead-b2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "B1 삭제" }));
    expect(okConfirm.mock.calls[okConfirm.mock.calls.length - 1]?.[0]).toMatch(/B1_D·_W/);
    await waitFor(() => expect(screen.queryByTestId("bead-b2")).toBeNull());
    expect((screen.getByLabelText("B1 이름") as HTMLInputElement).value).toBe("원형 비드");
    await waitFor(() => expect(screen.getByTestId("selection-stale")).toBeTruthy());
    fireEvent.keyDown(host, { key: "z", ctrlKey: true });
    await waitFor(() => expect(screen.getByTestId("bead-b2")).toBeTruthy());
    expect((screen.getByLabelText("B1 이름") as HTMLInputElement).value).toBe("좌 경로 비드");
    okConfirm.mockRestore();
  });

  it("고정 침범 안 3D 보기(v0.15.1): 침범 노드 빨간 점(setMarkers 3·n) + 원인 줄, 다른 안은 점 없음", async () => {
    renderApp("/p/p-body/doe/doe-6", "power");
    const thumbs = await screen.findByRole("list", { name: "미리보기 썸네일" });
    const fixedCell = [...thumbs.querySelectorAll('[data-status="SKIPPED_FIXED"]')][0] as HTMLElement;
    fireEvent.click(fixedCell);
    await waitFor(() => expect(screen.getByTestId("bs-design-host").getAttribute("data-phase")).toBe("ready"));
    await waitFor(() => expect(h.markers.some((m) => m && m.length === 37 * 3)).toBe(true));
    expect(screen.getByTestId("design-fixed-viol").textContent).toMatch(/빨간 점 = 움직인 고정 노드 37개/);
    const ok = [...thumbs.querySelectorAll('[data-status="READY"]')][0] as HTMLElement;
    h.markers.length = 0;
    fireEvent.click(ok);
    await waitFor(() => expect(h.markers.length).toBeGreaterThan(0));
    expect(h.markers[h.markers.length - 1]).toBeNull();
    expect(screen.queryByTestId("design-fixed-viol")).toBeNull();
  });

  it("비드 편집·초기화(v0.15.1): 행 클릭 = 활성, 이름·단 층 고르기·사면 다시 계산, 이 비드/전체 초기화 + Ctrl+Z, 저장본은 서버 그대로·'저장 안 한 변경'", async () => {
    const r = renderApp("/p/p-body/doe/doe-5", "power");
    await waitFor(() => expect(screen.getByTestId("bs-host").getAttribute("data-phase")).toBe("ready"));
    await waitFor(() => expect(screen.getByTestId("bead-b2")).toBeTruthy());
    const rev0 = r.server.doe.recs.find((x) => x.out.id === "doe-5")!.sel!.rev;
    const host = screen.getByTestId("bs-host");
    const layer = () => (screen.getByLabelText("대상 층") as HTMLSelectElement).value;
    // 행 클릭 → 활성
    fireEvent.click(screen.getByTestId("bead-b2").querySelector("header")!);
    await waitFor(() => expect(screen.getByTestId("bead-b2").getAttribute("aria-current")).toBe("true"));
    expect(layer()).toBe("t:1:1");
    fireEvent.change(screen.getByLabelText("B2 이름"), { target: { value: "원형 비드(수정)" } });
    await waitFor(() => expect(primary(r.container).textContent).toBe("선택 저장"));
    expect(screen.getByTestId("bs-dirty")).toBeTruthy();
    // B1 단 2 층 고르기 · 사면 층
    fireEvent.click(screen.getByTestId("bead-b1").querySelector("header")!);
    await waitFor(() => expect(screen.getByRole("button", { name: "B1 단 2 편집" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "B1 단 2 편집" }));
    expect(layer()).toBe("t:0:2");
    fireEvent.click(screen.getByRole("button", { name: "B1 사면 편집" }));
    expect(layer()).toBe("s:0");
    fireEvent.click(screen.getByRole("button", { name: "사면 다시 계산" }));
    await waitFor(() => expect(screen.getByTestId("bead-b1").textContent).toMatch(/자동 \d+/));
    // 이 비드 초기화(이름 유지) → Ctrl+Z
    const floor = () => screen.getByTestId("bead-b1").textContent ?? "";
    fireEvent.click(screen.getByRole("button", { name: "이 비드 초기화" }));
    await waitFor(() => expect(floor()).toMatch(/단1 바닥 0.*단2 바닥 0/));
    expect((screen.getByLabelText("B1 이름") as HTMLInputElement).value).toBe("좌 경로 비드");
    expect(floor()).toMatch(/자동 계산 전/);                       // 그 비드 derive(사면 제안·D·W)도 비움
    expect(floor()).not.toMatch(/자동 \d+|D \d/);
    fireEvent.keyDown(host, { key: "z", ctrlKey: true });
    await waitFor(() => expect(floor()).toMatch(/단1 바닥 [1-9]/));
    // 전체 초기화(확인) → 비드 없음, 서버 저장본 그대로 → Ctrl+Z
    const c = vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "전체 초기화" }));
    expect(c.mock.calls[0][0]).toMatch(/모든 비드와 고정·제외 층을 비웁니다/);
    await waitFor(() => expect(screen.queryByTestId("bead-b1")).toBeNull());
    expect(screen.getByTestId("bs-dirty")).toBeTruthy();
    expect(r.server.doe.recs.find((x) => x.out.id === "doe-5")!.sel!.rev).toBe(rev0);
    fireEvent.keyDown(host, { key: "z", ctrlKey: true });
    await waitFor(() => expect(screen.getByTestId("bead-b2")).toBeTruthy());
    c.mockRestore();
  });

  it("실행 후(편집 불가): 편집·삭제·초기화·지우개 비활성 + '복제해서 편집' 툴팁", async () => {
    renderApp("/p/p-body/doe/doe-6", "power", (s) => {
      s.doe.recs.find((x) => x.out.id === "doe-6")!.out.phase = "DONE";
    });
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy());
    for (const name of ["B1 삭제", "이 비드 초기화", "전체 초기화", "층 비우기", "지우개", "B1 단 1 편집", "+ 비드"]) {
      const b = screen.getByRole("button", { name }) as HTMLButtonElement;
      expect(b.disabled).toBe(true);
      expect(b.getAttribute("title")).toMatch(/복제해서 편집/);
    }
  });
});
