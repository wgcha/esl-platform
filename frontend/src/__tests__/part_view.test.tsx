// V-VU-1~9(esl_view_unify.md §6): 공통 PartView — 시나리오 어댑터마다 맞는 층만, 없는 층 숨김, [3D | 평면도], 평면도·3D 시점 툴바, 화면 연결.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ elemColors: 0, markers: [] as (Float32Array | null)[], views: [] as string[] }));
vi.mock("../view3d/webgl", () => ({ hasWebGL: () => true }));
vi.mock("../view3d/loadThree", () => ({
  loadScene: async () => ({
    createScene: () => {
      const nop = () => undefined;
      let proj = "ortho";
      return {
        setGeometry: nop, setColors: nop, setDeform: nop, setArrows: nop, setSupports: nop, select: nop, focus: nop, fit: nop,
        setView: (a: string) => h.views.push(a),
        setProjection: (p: string) => (proj = p), projection: () => proj, onPick: nop, stats: () => ({ renders: 0 }), dispose: nop,
        setColorMap: nop, setElements: nop, setElemColors: () => (h.elemColors += 1), setOverlayLines: nop,
        setMarkers: (p: Float32Array | null) => h.markers.push(p),
        pickElem: () => null,
      };
    },
  }),
}));

import { makeDoeSettings, makePlan, withBoundary } from "../mock/doedata";
import { selDefaultSelection, selPlan } from "../mock/selectmock";
import { PartView } from "../view3d/part/PartView";
import { designViewData, legacyViewData, planLayers, selectPlan, selectViewData } from "../view3d/part/adapters";
import type { Part3DData } from "../view3d/part/types";
import { renderApp } from "../test/render";

const tri: Part3DData["mesh"] = { positions: new Float32Array([0, 0, 0, 10, 0, 0, 0, 10, 0]), indices: new Uint32Array([0, 1, 2]) };
const st = makeDoeSettings();
const vb = () => screen.getByTestId("pv-plan").getAttribute("viewBox");

beforeEach(() => {
  h.elemColors = 0;
  h.markers.length = 0;
  h.views.length = 0;
});

describe("어댑터 → 층(가진 자료만)", () => {
  it("V-VU-1 이전 방식 ① same: 평면도만, 외곽·메시·비드·고정 — A 체결·하중·경고 없음", () => {
    const d = legacyViewData({ plan: makePlan("same", ["e1"]), showLinks: false, st, nWarn: null, mesh: null });
    expect(d.layers).toEqual(["boundary", "mesh", "beads", "fixed"]);
    expect(d.scene).toBeNull();
    expect(d.warnings).toBeNull();
    render(<PartView data={d} />);
    expect(screen.queryByRole("radiogroup", { name: "보기" })).toBeNull();
    expect(screen.getByRole("img", { name: "비드·경계 평면도" })).toBeTruthy();
    expect(screen.queryByTestId("pv-layer-apoints")).toBeNull();
    expect(screen.queryByTestId("boundary-warn-n")).toBeNull();
  });

  it("V-VU-2 이전 방식 ②③: A 체결·하중 층 + 경고선 = 경고 수, 층 끄면 선·기호 숨김", () => {
    const plan = makePlan("step", ["e1", "e2", "e3"]);
    const d = legacyViewData({ plan, showLinks: true, st, nWarn: null, mesh: null });
    expect(d.layers).toEqual(expect.arrayContaining(["apoints", "loads"]));
    render(<PartView data={d} />);
    const n = screen.getAllByTestId("plan-warn-link").length;
    expect(n).toBeGreaterThan(0);
    expect(Number(screen.getByTestId("boundary-warn-n").textContent)).toBe(plan.links.filter((l) => l.warn).length);
    fireEvent.click(screen.getByTestId("pv-layer-loads"));
    expect(screen.queryAllByTestId("plan-load")).toHaveLength(0);
    const afterLoads = screen.queryAllByTestId("plan-warn-link").length;
    expect(afterLoads).toBeLessThan(n);
    fireEvent.click(screen.getByTestId("pv-layer-apoints"));
    expect(screen.queryAllByTestId("plan-apt")).toHaveLength(0);
    expect(screen.queryAllByTestId("plan-warn-link")).toHaveLength(0);
  });

  it("V-VU-3 ① select: 단 색·라벨 칩, 노드 층 기본 꺼짐 → 켜면 점, W 행 강조 = 범위 점선, A 체결 층 없음", () => {
    const p = selPlan(selDefaultSelection(), st);
    const d = selectViewData({ plan: p, chips: { b1: "B1 · D1 22.0" }, active: null, meshBase: false, st, nWarn: null, scene: null, sceneLayers: [] });
    expect(d.layers).not.toContain("apoints");
    expect(d.layers).toContain("nodes");
    const { rerender } = render(<PartView data={d} />);
    expect(screen.getByRole("img", { name: "비드 평면도" })).toBeTruthy();
    expect(screen.getByTestId("plan-chip-b1").textContent).toBe("B1 · D1 22.0");
    expect(screen.queryByTestId("plan-nodes")).toBeNull();
    fireEvent.click(screen.getByTestId("pv-layer-nodes"));
    expect(screen.getByTestId("plan-nodes")).toBeTruthy();
    rerender(<PartView data={{ ...d, active: { name: "B1_W", type: "W", bead: "b1", nominal: 60, lo: 50, hi: 70 } }} />);
    expect(screen.getByTestId("plan-w-range-b1")).toBeTruthy();
  });

  it("V-VU-4 ② select(B 메시): 백엔드가 넘긴 A 체결·하중·링크 → 층·경고 표, ① 은 같은 자료여도 숨김", () => {
    const rec = { out: { inputs: { select_base: "mesh" }, entry_ids: ["e1", "e2"] } };
    const p = withBoundary(rec, selPlan(selDefaultSelection(), st));
    expect(p.links.length).toBeGreaterThan(0);
    const d = selectViewData({ plan: p, chips: {}, active: null, meshBase: true, st, nWarn: 9, scene: null, sceneLayers: [] });
    expect(d.layers).toEqual(expect.arrayContaining(["apoints", "loads", "fixed", "beads"]));
    render(<PartView data={d} />);
    expect(screen.getAllByTestId("plan-warn-link").length).toBeGreaterThan(0);
    expect(Number(screen.getByTestId("boundary-warn-n").textContent)).toBeGreaterThanOrEqual(9);
    expect(planLayers(selectPlan(p, {}, false))).not.toContain("apoints");
  });
});

describe("시점 툴바·보기 전환", () => {
  it("V-VU-5 평면도 툴바: 선택 맞춤 = 확대(viewBox 바뀜) → 꽉 차게 = 원래대로, 단축키 F", () => {
    const d = legacyViewData({ plan: makePlan("same", ["e1"]), showLinks: false, st, nWarn: null, mesh: null });
    render(<PartView data={d} />);
    const full = vb();
    const fit = screen.getByRole("button", { name: "평면도 꽉 차게" }) as HTMLButtonElement;
    expect(fit.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "평면도 선택 맞춤" }));
    expect(vb()).not.toBe(full);
    expect(fit.disabled).toBe(false);
    fireEvent.click(fit);
    expect(vb()).toBe(full);
    fireEvent.click(screen.getByRole("button", { name: "평면도 선택 맞춤" }));
    fireEvent.keyDown(screen.getByLabelText("비드·경계 평면도 칸"), { key: "f" });
    expect(vb()).toBe(full);
  });

  it("V-VU-6 3D + 평면도: [3D] 고르면 3D 칸·시점 툴바(X 보기 → setView), 요소 색 층 끄면 다시 칠함", async () => {
    let lastOn: Record<string, boolean> = {};
    const scene: Part3DData = {
      key: "t",
      mesh: tri,
      hostTestId: "pv-t-3d",
      elemColors: (on) => {
        lastOn = { graph: on("graph"), islands: on("islands") };
        return new Uint8Array(4);
      },
    };
    const p = selPlan(selDefaultSelection(), st);
    const d = selectViewData({ plan: p, chips: {}, active: null, meshBase: false, st, nWarn: null, scene, sceneLayers: ["graph", "islands"] });
    render(<PartView data={d} />);
    expect(screen.queryByTestId("pv-t-3d")).toBeNull(); // 평면도만 볼 때 장면 없음
    expect(screen.queryByTestId("pv-layer-graph")).toBeNull(); // 3D 전용 층은 3D 에서만
    fireEvent.click(screen.getByTestId("pv-mode-3d"));
    await waitFor(() => expect(screen.getByTestId("pv-t-3d").getAttribute("data-phase")).toBe("ready"));
    expect(h.elemColors).toBeGreaterThan(0);
    expect(lastOn).toEqual({ graph: true, islands: true });
    fireEvent.click(screen.getByRole("button", { name: "X 보기" }));
    expect(h.views).toEqual(["x"]);
    fireEvent.click(screen.getByTestId("pv-layer-graph"));
    await waitFor(() => expect(lastOn.graph).toBe(false));
    expect(screen.queryByTestId("pv-layer-mesh")).toBeNull();
    fireEvent.click(screen.getByTestId("pv-mode-plan"));
    expect(screen.getByTestId("pv-plan")).toBeTruthy();
  });

  it("V-VU-7 안 3D(design): 3D 만(보기 전환·층 칩 없음), 빨간 점, 시점 툴바", async () => {
    const d = designViewData({ did: "d001", mesh: tri, u: new Float32Array(9), c: new Float32Array(3), vmax: 1, scale: 1, markers: new Float32Array([1, 2, 3]), selectionBbox: () => null });
    render(<PartView data={d} />);
    await waitFor(() => expect(screen.getByTestId("bs-design-host").getAttribute("data-phase")).toBe("ready"));
    expect(screen.queryByRole("radiogroup", { name: "보기" })).toBeNull();
    expect(screen.queryByRole("group", { name: "표시 층" })).toBeNull();
    expect(screen.getByRole("toolbar", { name: "시점" })).toBeTruthy();
    await waitFor(() => expect(h.markers.some((m) => m?.length === 3)).toBe(true));
  });
});

describe("화면 연결(mock)", () => {
  it("V-VU-8 이전 방식 ① 완료(doe-1): ③ 평면도 = PartView, 결과 d000 형상이 있으면 [3D] 보기", async () => {
    renderApp("/p/p-body/doe/doe-1", "power");
    await waitFor(() => expect(screen.getByTestId("pv-legacy")).toBeTruthy());
    expect(screen.getByRole("img", { name: "비드·경계 평면도" })).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("pv-mode-3d")).toBeTruthy());
    fireEvent.click(screen.getByTestId("pv-mode-3d"));
    await waitFor(() => expect(screen.getByTestId("pv-legacy-3d").getAttribute("data-phase")).toBe("ready"));
  });

  it("V-VU-9 ② select B 메시(doe-14): ⑤ 평면도에 A 체결·하중 층·경계 경고 표, ① select(doe-5)에는 없음", async () => {
    renderApp("/p/p-body/doe/doe-14", "power", (s) => s.doe.demoMeshSel());
    await waitFor(() => expect(screen.getByTestId("pv-select")).toBeTruthy());
    expect(screen.getByTestId("pv-layer-apoints")).toBeTruthy();
    expect(screen.getAllByTestId("plan-warn-link").length).toBeGreaterThan(0);
    expect(screen.getByTestId("boundary-warn-n")).toBeTruthy();
    expect(screen.getByTestId("pv-mode-3d")).toBeTruthy();
  });

  it("V-VU-9b ① select(doe-5): ⑤ PartView — A 체결 층·경고 표 없음, [3D] 보기 = 선택 형상(요소 색)", async () => {
    renderApp("/p/p-body/doe/doe-5", "power");
    await waitFor(() => expect(screen.getByTestId("pv-select")).toBeTruthy());
    expect(screen.queryByTestId("pv-layer-apoints")).toBeNull();
    expect(screen.queryByTestId("boundary-warn-n")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("pv-mode-3d")).toBeTruthy());
    const before = h.elemColors;
    fireEvent.click(screen.getByTestId("pv-mode-3d"));
    await waitFor(() => expect(screen.getByTestId("pv-select-3d").getAttribute("data-phase")).toBe("ready"));
    await waitFor(() => expect(h.elemColors).toBeGreaterThan(before));
  });
});
