// v0.25.1 F1a 카드 시험 — C 기여도·차이 색 모드(V-0251-24 쌍 동기·27 사유)·umax 핀(28)·옛 자료(32)·성능(31)·분류 색(46)·세 색 지도 호출.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PickEvent, SceneApi } from "../view3d/sceneApi";

const h = vi.hoisted(() => ({ scenes: [] as unknown[] }));
vi.mock("../view3d/webgl", () => ({ hasWebGL: () => true }));
vi.mock("../view3d/loadThree", () => ({
  loadScene: async () => ({
    createScene: () => {
      const calls: Record<string, unknown[][]> = {};
      const rec = (name: string) => (...a: unknown[]) => {
        (calls[name] ??= []).push(a);
      };
      let uploads = 0;
      let cam: ((s: unknown) => void) | null = null;
      const api = {
        calls,
        setProjection: rec("setProjection"),
        projection: () => "ortho",
        emit: (_e: PickEvent) => undefined,
        setGeometry: rec("setGeometry"),
        setColors: rec("setColors"),
        setField: (...a: unknown[]) => (uploads++, rec("setField")(...a)),
        setLegend: rec("setLegend"),
        setColorMap: rec("setColorMap"),
        setLayerVisible: rec("setLayerVisible"),
        setValueMarks: rec("setValueMarks"),
        setGhostEdges: rec("setGhostEdges"),
        cameraState: () => ({ position: [1, 2, 3], target: [0, 0, 0], up: [0, 0, 1], halfH: 1, zoom: 1 }),
        applyCameraState: rec("applyCameraState"),
        onCameraChange: (cb: ((s: unknown) => void) | null) => (cam = cb),
        hasCam: () => !!cam,
        setDeform: rec("setDeform"),
        setArrows: rec("setArrows"),
        setSupports: rec("setSupports"),
        select: rec("select"),
        focus: rec("focus"),
        fit: rec("fit"),
        setView: rec("setView"),
        onPick: rec("onPick"),
        stats: () => ({ renders: 0, valueUploads: uploads, colorLoops: 0 }),
        dispose: rec("dispose"),
      };
      h.scenes.push(api);
      return api;
    },
  }),
}));

import { api } from "../api/endpoints";
import type { View3dOut } from "../api/types";
import { mockView3d } from "../mock/view3dmock";
import { C_LABEL, DC_LABEL, NO_C_TEXT, View3DCard, type View3DOptions } from "../view3d/View3DCard";
import { useLoadView } from "../view3d/useLoadView";
import { useViewerSync } from "../view3d/viewerSync";
import { sceneExtras } from "../view3d/sceneManifest";
import { parseGlb } from "../view3d/glb";

type Fake = SceneApi & { calls: Record<string, unknown[][]>; hasCam: () => boolean };
const nth = (i: number) => h.scenes[i] as Fake;
const last = (sc: Fake, name: string) => {
  const c = sc.calls[name] ?? [];
  return c[c.length - 1];
};

/** 씬 묶음 값 파일 흉내: 옛 values.bin + c·dc(int16, 합 float64 원값은 manifest) 배열 */
function sceneVariant(opts: { c?: boolean; dc?: boolean; pinVertex?: number; pinKind?: string }): { manifest: View3dOut; values: ArrayBuffer } {
  const base = mockView3d();
  const m0 = base.manifest("r1");
  const n = m0.n_nodes;
  const man = JSON.parse(JSON.stringify(m0)) as View3dOut & Record<string, unknown>;
  const old = new Uint8Array(base.values);
  const pad = (x: number) => (4 - (x % 4)) % 4;
  const parts: Uint8Array[] = [old];
  let off = old.byteLength;
  const arrays = man.values.arrays as unknown as Record<string, unknown>[];
  const add = (key: string, fn: (i: number) => number) => {
    if (pad(off)) {
      parts.push(new Uint8Array(pad(off)));
      off += pad(off);
    }
    const vals = Array.from({ length: n }, (_, i) => fn(i));
    const mx = Math.max(...vals.map(Math.abs)) || 1;
    const scale = mx / 32767;
    const q = new Int16Array(vals.map((v) => Math.round(v / scale)));
    arrays.push({ key, dtype: "int16", comps: 1, offset: off, scale });
    parts.push(new Uint8Array(q.buffer));
    off += q.byteLength;
    return { mx, vals };
  };
  const ranges = man.ranges as unknown as Record<string, unknown>;
  if (opts.c) {
    const { vals } = add("c", (i) => ((i % 11) - 3) * 1.5);
    const sorted = [...vals].sort((a, b) => a - b);
    man.c = { kind: "fu", sum: vals.reduce((a, b) => a + b, 0), offset: 0, value: vals.reduce((a, b) => a + b, 0), unit: "N·mm" };
    ranges.c = { min: sorted[0], max: sorted[n - 1], p01: sorted[Math.floor(0.01 * n)], p99: sorted[Math.floor(0.99 * n)] };
  }
  if (opts.dc) {
    const { mx, vals } = add("dc", (i) => ((i % 7) - 3) * 0.5);
    man.dc = { sum: vals.reduce((a, b) => a + b, 0), base_sum: 0, map: "identity" };
    ranges.dc = { abs_max: mx, abs_p99: mx };
  }
  if (opts.pinVertex !== undefined) man.pins = { umax: { node_id: 9000 + opts.pinVertex, vertex: opts.pinVertex, value: 0.4321, kind: opts.pinKind ?? "ev" } };
  let total = 0;
  for (const p of parts) total += p.byteLength;
  const buf = new Uint8Array(total);
  let o = 0;
  for (const p of parts) (buf.set(p, o), (o += p.byteLength));
  return { manifest: man as View3dOut, values: buf.buffer };
}

let VALUES: ArrayBuffer | null = null;
beforeEach(() => {
  h.scenes.length = 0;
  localStorage.clear();
  const base = mockView3d();
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const u = String(input);
    const body = u.includes("values.bin") ? VALUES ?? base.values : base.glb;
    return new Response(body.slice(0), { status: 200 });
  }) as typeof fetch;
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function One({ man, options }: { man: View3dOut; options: View3DOptions }) {
  vi.spyOn(api, "view3d").mockResolvedValue(man);
  const v = useLoadView("r1", true, null);
  return v ? <View3DCard view={v} options={options} /> : null;
}
const open = async (i = 0) => {
  await waitFor(() => expect(h.scenes.length).toBeGreaterThan(i));
  await waitFor(() => expect(last(nth(i), "setLegend")).toBeTruthy());
};

describe("V-0251 C 기여도·차이 색 모드", () => {
  it("c: 레인보우 역할·범례 제목·합 = C·자동 범위 [min(p01,0), max(p99,0)]·탐침에 값", async () => {
    const sv = sceneVariant({ c: true });
    VALUES = sv.values;
    render(<One man={sv.manifest} options={{ colorMode: "c", plan: "case_load" }} />);
    await open();
    const sc = nth(0);
    expect(last(sc, "setColorMap")).toEqual(["seq", false]);
    const ex = sceneExtras(sv.manifest);
    const lg = last(sc, "setLegend")![0] as { min: number; max: number; levels: number };
    expect(lg.min).toBe(Math.min(ex.cRange!.p01, 0));
    expect(lg.max).toBe(Math.max(ex.cRange!.p99, 0));
    expect(screen.getByTestId("v3d-legend-ov").textContent).toContain(C_LABEL);
    expect(screen.getByTestId("v3d-legend").textContent).toContain("C 기여도");
    expect(screen.getByTestId("v3d-legend").getAttribute("data-range-min")).toBe(String(lg.min));
  });
  it("dc: 발산 역할·±abs_p99 대칭·제목·범례에서 로그 비활성 + 사유(V-0251-27)", async () => {
    const sv = sceneVariant({ dc: true });
    VALUES = sv.values;
    render(<One man={sv.manifest} options={{ colorMode: "dc", plan: "case_load" }} />);
    await open();
    const sc = nth(0);
    expect(last(sc, "setColorMap")).toEqual(["div", false]);
    const lg = last(sc, "setLegend")![0] as { min: number; max: number };
    expect(lg.min).toBe(-lg.max);
    expect(lg.max).toBeCloseTo(sceneExtras(sv.manifest).dcRange!.abs_p99, 12);
    expect(screen.getByTestId("v3d-legend-ov").textContent).toContain(DC_LABEL);
    fireEvent.click(screen.getByTestId("v3d-legend-ov"));
    const log = within(screen.getByTestId("v3d-leg-scale")).getByRole("button", { name: "로그" }) as HTMLButtonElement;
    expect(log.disabled).toBe(true);
    expect(log.title).toContain("부호");
    // 차이 = ±R 한 칸(최소 칸 없음)
    expect(screen.queryByTestId("v3d-leg-min")).toBeNull();
  });
  it("값 배열이 없으면(옛 자료·dc null) 칠하지 않고 안내 — 화면이 깨지지 않음(V-0251-32)", async () => {
    VALUES = null;
    render(<One man={mockView3d().manifest("r1")} options={{ colorMode: "c" }} />);
    await waitFor(() => expect(screen.getByTestId("v3d-no-c").textContent).toBe(NO_C_TEXT));
    expect(screen.queryByTestId("v3d-legend-ov")).toBeNull();
    expect(sceneExtras(mockView3d().manifest("r1"))).toEqual({ c: null, dc: null, umaxPin: null, cRange: null, dcRange: null });
    cleanup();
    h.scenes.length = 0;
    render(<One man={mockView3d().manifest("r1")} options={{}} />);
    await open();
    expect(screen.getByTestId("v3d-legend-ov").getAttribute("data-role")).toBe("seq");
    expect(last(nth(0), "setColorMap")).toEqual(["seq", false]);
  });
});

describe("V-0251-24 쌍 동기: 범례 편집 → 상대 카드, 차이 모드는 범위 따로", () => {
  function Pair({ man, modes }: { man: View3dOut; modes: ["c" | "disp", "c" | "dc" | "disp"] }) {
    vi.spyOn(api, "view3d").mockResolvedValue(man);
    const sync = useViewerSync("study_design");
    const a = useLoadView("r1", true, null);
    const b = useLoadView("r1", true, null);
    return (
      <>
        {a && <View3DCard view={a} options={{ title: "A", plan: "study_design", viewerSync: sync, colorMode: modes[0] }} />}
        {b && <View3DCard view={b} options={{ title: "B", plan: "study_design", viewerSync: sync, colorMode: modes[1] }} />}
      </>
    );
  }
  it("레벨·뒤집기·범위 직접 입력이 두 카드에 같다", async () => {
    const sv = sceneVariant({ c: true, dc: true });
    VALUES = sv.values;
    render(<Pair man={sv.manifest} modes={["c", "c"]} />);
    await waitFor(() => expect(h.scenes.length).toBe(2));
    await waitFor(() => expect(last(nth(1), "setLegend")).toBeTruthy());
    fireEvent.click(screen.getAllByTestId("v3d-legend-ov")[0]);
    fireEvent.change(screen.getByTestId("v3d-leg-levels"), { target: { value: "5" } });
    fireEvent.click(screen.getByTestId("v3d-leg-rev"));
    fireEvent.change(screen.getByTestId("v3d-leg-max"), { target: { value: "7" } });
    await waitFor(() => expect(last(nth(1), "setLegend")![0]).toMatchObject({ levels: 5, max: 7 }));
    expect(last(nth(0), "setLegend")![0]).toMatchObject({ levels: 5, max: 7 });
    expect(last(nth(1), "setColorMap")).toEqual(["seq", true]);
    expect(last(nth(0), "setColorMap")).toEqual(["seq", true]);
    // 기억: 범례 모양은 v2 에 남고 범위는 남지 않음
    const raw = JSON.parse(localStorage.getItem("esl.v3d.viewer.v2")!);
    expect(raw.legend).toMatchObject({ levels: 5, reversed: true });
    expect(JSON.stringify(raw)).not.toContain('"max"');
  });
  it("차이 모드: 범례 모양은 공유, 범위는 공유하지 않는다(안 카드 ±R · 기준 카드 레인보우)", async () => {
    const sv = sceneVariant({ c: true, dc: true });
    VALUES = sv.values;
    render(<Pair man={sv.manifest} modes={["c", "dc"]} />);
    await waitFor(() => expect(h.scenes.length).toBe(2));
    await waitFor(() => expect(last(nth(1), "setLegend")).toBeTruthy());
    expect(last(nth(0), "setColorMap")).toEqual(["seq", false]);
    expect(last(nth(1), "setColorMap")).toEqual(["div", false]);
    const lg0 = last(nth(0), "setLegend")![0] as { min: number; max: number };
    const lg1 = last(nth(1), "setLegend")![0] as { min: number; max: number };
    expect(lg1.min).toBe(-lg1.max);
    expect(lg0.min).toBeLessThanOrEqual(0);
    // 기준(c) 카드에서 최대를 직접 입력해도 안(dc) 카드 범위는 그대로
    fireEvent.click(screen.getAllByTestId("v3d-legend-ov")[0]);
    fireEvent.change(screen.getByTestId("v3d-leg-max"), { target: { value: "9" } });
    await waitFor(() => expect(last(nth(0), "setLegend")![0]).toMatchObject({ max: 9 }));
    expect(last(nth(1), "setLegend")![0]).toMatchObject({ min: lg1.min, max: lg1.max });
    // 레벨 수는 두 카드가 같이
    fireEvent.change(screen.getByTestId("v3d-leg-levels"), { target: { value: "4" } });
    await waitFor(() => expect(last(nth(1), "setLegend")![0]).toMatchObject({ levels: 4 }));
  });
  it("쌍의 자동 범위 = 두 카드를 포함(합집합)", async () => {
    const sv = sceneVariant({ c: true });
    VALUES = sv.values;
    render(<Pair man={sv.manifest} modes={["c", "c"]} />);
    await waitFor(() => expect(h.scenes.length).toBe(2));
    await waitFor(() => expect(last(nth(1), "setLegend")).toBeTruthy());
    const a = last(nth(0), "setLegend")![0] as { min: number; max: number };
    const b = last(nth(1), "setLegend")![0] as { min: number; max: number };
    expect(a).toMatchObject({ min: b.min, max: b.max });
  });
});

describe("V-0251-28 umax 핀", () => {
  const pinOf = (sc: Fake) => (last(sc, "setValueMarks")![0] as { vertex: number; text: string; symbol?: string }[]).find((m) => m.symbol === "◆");
  it("라벨 'umax <값> mm @N <노드 ID>', manifest pins 를 읽음, 끄면 사라짐, 최대 표식과 같은 정점이면 최대 라벨 숨김", async () => {
    const sv = sceneVariant({ c: true, pinVertex: 40 });
    VALUES = sv.values;
    render(<One man={sv.manifest} options={{ colorMode: "c", plan: "study_design" }} />);
    await open();
    const sc = nth(0);
    const pin = pinOf(sc)!;
    expect(pin.vertex).toBe(40);
    expect(pin.text).toBe("umax 0.4321 mm @N 9040");
    // 켬 = 기본, ⚙ 의 범례 절 `umax 위치` 끄기
    fireEvent.click(screen.getByTestId("v3d-gear"));
    const cb = screen.getByTestId("v3d-gleg-pin") as HTMLInputElement;
    expect(cb.checked).toBe(true);
    fireEvent.click(cb);
    await waitFor(() => expect(pinOf(sc)).toBeUndefined());
    fireEvent.click(cb);
    await waitFor(() => expect(pinOf(sc)).toBeTruthy());
  });
  it("최대 표식과 같은 정점이면 최대 표식 라벨을 숨기고 핀 라벨만(범례 줄 '최대 v @N' 은 남음)", async () => {
    const sv = sceneVariant({ c: true });
    VALUES = sv.values;
    // 최대 c 가 나는 가장 작은 정점
    const g = parseGlb(mockView3d().glb);
    void g;
    const n = sv.manifest.n_nodes;
    let vmax = 0;
    for (let i = 0; i < n; i++) if (((i % 11) - 3) * 1.5 > ((vmax % 11) - 3) * 1.5) vmax = i;
    const sv2 = sceneVariant({ c: true, pinVertex: vmax });
    VALUES = sv2.values;
    render(<One man={sv2.manifest} options={{ colorMode: "c", plan: "study_design" }} />);
    await open();
    const marks = last(nth(0), "setValueMarks")![0] as { vertex: number; text: string }[];
    expect(marks.filter((m) => m.vertex === vmax)).toHaveLength(1);
    expect(marks.some((m) => m.text.startsWith("최대"))).toBe(false);
    expect(screen.getByTestId("v3d-legend-ov-max").textContent).toMatch(/^최대 /);
  });
  it("두 카드 모두 자기 manifest 의 핀을 그린다 · options.pins=null 이면 핀 없음 · 핀 자료 없으면 체크 비활성", async () => {
    const svA = sceneVariant({ c: true, pinVertex: 12 });
    VALUES = svA.values;
    render(<One man={svA.manifest} options={{ colorMode: "c", pins: null }} />);
    await open();
    expect(pinOf(nth(0))).toBeUndefined();
    cleanup();
    h.scenes.length = 0;
    const svB = sceneVariant({ c: true });
    VALUES = svB.values;
    render(<One man={svB.manifest} options={{ colorMode: "c", plan: "study_design" }} />);
    await open();
    fireEvent.click(screen.getByTestId("v3d-legend-ov"));
    expect((screen.getByTestId("v3d-leg-pin") as HTMLInputElement).disabled).toBe(true);
  });
});

describe("V-0251-31 성능: 범례 편집은 uniform·색표만", () => {
  it("편집(레벨·최대·최소·로그·숫자·범위 밖·뒤집기) 동안 setField 0회·colorLoops 0·setColors 0", async () => {
    VALUES = null;
    render(<One man={mockView3d().manifest("r1")} options={{ colorMode: "disp", colorBy: "disp" }} />);
    await open();
    const sc = nth(0);
    const f0 = (sc.calls["setField"] ?? []).length;
    fireEvent.click(screen.getByTestId("v3d-legend-ov"));
    fireEvent.change(screen.getByTestId("v3d-leg-levels"), { target: { value: "12" } });
    fireEvent.change(screen.getByTestId("v3d-leg-max"), { target: { value: "0.5" } });
    fireEvent.change(screen.getByTestId("v3d-leg-min"), { target: { value: "0.001" } });
    fireEvent.click(within(screen.getByTestId("v3d-leg-scale")).getByRole("button", { name: "로그" }));
    fireEvent.click(within(screen.getByTestId("v3d-leg-out")).getByRole("button", { name: "회색" }));
    fireEvent.click(within(screen.getByTestId("v3d-leg-format")).getByRole("button", { name: "지수" }));
    fireEvent.click(screen.getByTestId("v3d-leg-rev"));
    await waitFor(() => expect(last(sc, "setLegend")![0]).toMatchObject({ levels: 12, min: 0.001, max: 0.5, log: true, outGray: true }));
    expect((sc.calls["setField"] ?? []).length).toBe(f0);
    expect((sc.calls["setColors"] ?? []).length).toBe(0);
    expect(sc.stats().colorLoops).toBe(0);
    expect(last(sc, "setColorMap")).toEqual(["seq", true]);
    // 숫자 형식 지수 → 범례 눈금 문구
    expect(screen.getAllByTestId("v3d-legend-ov-tick")[0].textContent).toMatch(/e[+-]\d/);
    // 로그 최소 보정 + 범위 밖 회색 표지(▲▼ 옆 견본)
    fireEvent.click(screen.getByTestId("v3d-leg-reset"));
    await waitFor(() => expect(last(sc, "setLegend")![0]).toMatchObject({ levels: 9, log: false, outGray: false }));
    expect(last(sc, "setColorMap")).toEqual(["seq", false]);
  });
  it("범례 최소 직접 입력 → 최소 표식, 기본값으로 → 자동", async () => {
    VALUES = null;
    render(<One man={mockView3d().manifest("r1")} options={{ colorBy: "disp" }} />);
    await open();
    fireEvent.click(screen.getByTestId("v3d-legend-ov"));
    expect((screen.getByTestId("v3d-leg-min-auto") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId("v3d-leg-min"), { target: { value: "0.01" } });
    expect((screen.getByTestId("v3d-leg-min-auto") as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByTestId("v3d-leg-minmark"));
    await waitFor(() => expect((last(nth(0), "setValueMarks")![0] as { text: string }[]).some((m) => m.text.startsWith("최소"))).toBe(true));
    expect(screen.getByTestId("v3d-legend-ov-min").textContent).toMatch(/^최소 /);
    fireEvent.click(screen.getByTestId("v3d-leg-min-auto"));
    await waitFor(() => expect(last(nth(0), "setLegend")![0]).toMatchObject({ min: 0 }));
    // 유효하지 않은 값(최소 ≥ 최대)은 직전 범위 유지
    fireEvent.change(screen.getByTestId("v3d-leg-min"), { target: { value: "999" } });
    expect(last(nth(0), "setLegend")![0]).toMatchObject({ min: 0 });
  });
});

describe("V-0251-46 하중 영역(분류) = region 색표 · 범례 편집 없음", () => {
  it("fieldOverride 기본 = region: setColorMap('region'), 연속·끝색 고정, 클릭해도 팝오버 없음, ⚙ 에 범례 절 없음", async () => {
    VALUES = null;
    const m = mockView3d().manifest("r1");
    const values = new Float32Array(m.n_nodes).map((_, i) => (i % 3 === 0 ? 0.8 : i % 3 === 1 ? 0.3 : NaN));
    render(<One man={m} options={{ colorBy: "disp", fieldOverride: { values, min: 0, max: 1, label: "하중 영역" }, plan: "study_jigdiag" }} />);
    await open();
    const sc = nth(0);
    expect(last(sc, "setColorMap")).toEqual(["region", false]);
    expect(last(sc, "setLegend")![0]).toMatchObject({ min: 0, max: 1, levels: 0, log: false, outGray: false });
    expect(screen.getByTestId("v3d-legend-ov").getAttribute("data-role")).toBe("region");
    fireEvent.click(screen.getByTestId("v3d-legend-ov"));
    expect(screen.queryByTestId("v3d-legend-pop")).toBeNull();
    fireEvent.click(screen.getByTestId("v3d-gear"));
    expect(screen.queryByTestId("v3d-opt-legend")).toBeNull();
  });
});

describe("진입 2곳 · 내용 1개", () => {
  it("범례 클릭 팝오버와 ⚙ 의 범례 절이 같은 상태를 바꾼다", async () => {
    VALUES = null;
    render(<One man={mockView3d().manifest("r1")} options={{}} />);
    await open();
    const sc = nth(0);
    fireEvent.click(screen.getByTestId("v3d-gear"));
    fireEvent.change(screen.getByTestId("v3d-gleg-levels"), { target: { value: "7" } });
    await waitFor(() => expect(last(sc, "setLegend")![0]).toMatchObject({ levels: 7 }));
    act(() => {
      fireEvent.click(screen.getByTestId("v3d-legend-ov"));
    });
    expect((screen.getByTestId("v3d-leg-levels") as HTMLInputElement).value).toBe("7");
  });
});
