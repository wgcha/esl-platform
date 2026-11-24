// V-0246-VW-1~13(프런트, W-F1): 3D 뷰어 강화 — 계획 표·층 토글·구간 범례·최대 표식·특징선·탐침·수동 범위 유지·기억·쌍 동기화·편집 보기 DOM 불변.
import { cleanup, fireEvent, render, renderHook, screen, waitFor, within, act } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PickEvent, SceneApi, SceneOptions, CameraState } from "../view3d/sceneApi";

const h = vi.hoisted(() => ({ scenes: [] as unknown[] }));

vi.mock("../view3d/webgl", () => ({ hasWebGL: () => true }));
vi.mock("../view3d/loadThree", () => ({
  loadScene: async () => ({
    createScene: (_c: unknown, opts: unknown) => {
      const calls: Record<string, unknown[][]> = {};
      let pick: ((e: PickEvent) => void) | null = null;
      let cam: ((s: unknown) => void) | null = null;
      const rec = (name: string) => (...a: unknown[]) => {
        (calls[name] ??= []).push(a);
      };
      let proj = (opts as { projection?: string }).projection ?? "ortho";
      let uploads = 0;
      const api = {
        calls,
        opts,
        setProjection: (p: string) => {
          rec("setProjection")(p);
          proj = p;
        },
        projection: () => proj,
        emit: (e: PickEvent) => pick?.(e),
        emitCam: (s: unknown) => cam?.(s),
        hasCamCb: () => !!cam,
        setGeometry: rec("setGeometry"),
        setColors: rec("setColors"),
        setField: (...a: unknown[]) => (uploads++, rec("setField")(...a)),
        setLegend: rec("setLegend"),
        setLayerVisible: rec("setLayerVisible"),
        setValueMarks: rec("setValueMarks"),
        setGhostEdges: rec("setGhostEdges"),
        cameraState: () => ({ position: [1, 2, 3], target: [0, 0, 0], up: [0, 0, 1], halfH: 1, zoom: 1 }),
        applyCameraState: rec("applyCameraState"),
        onCameraChange: (cb: ((s: unknown) => void) | null) => (cam = cb),
        setDeform: rec("setDeform"),
        setArrows: rec("setArrows"),
        setSupports: rec("setSupports"),
        select: rec("select"),
        focus: rec("focus"),
        fit: rec("fit"),
        setView: rec("setView"),
        onPick: (cb: (e: PickEvent) => void) => (pick = cb),
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
import { makeMesh, mockView3d } from "../mock/view3dmock";
import { renderApp } from "../test/render";
import { bandT, bandedGradient, normalize } from "../view3d/colors";
import { FEATURE_DEG, featureEdges } from "../view3d/edges";
import { infoLine, shortFieldName } from "../view3d/info";
import { LegendOverlay, boundaryIndices } from "../view3d/LegendOverlay";
import { extremes, marksFor } from "../view3d/marks";
import { View3DCard } from "../view3d/View3DCard";
import { ViewToolbar } from "../view3d/ViewToolbar";
import { LEVEL_CHOICES, VIEWER_PLANS, planOf, type ViewerState } from "../view3d/viewerPlan";
import { VIEWER_KEY, readViewerPrefs, writeViewerPrefs } from "../view3d/viewerPrefs";
import { useViewerSync } from "../view3d/viewerSync";
import { decodeValues } from "../view3d/values";
import { useLoadView } from "../view3d/useLoadView";
import { parseGlb } from "../view3d/glb";
import { defaultScaleExp, pairScaleExp } from "../view3d/deform";

type FakeScene = SceneApi & { calls: Record<string, unknown[][]>; emit: (e: PickEvent) => void; emitCam: (s: unknown) => void; opts: SceneOptions };
const scene = () => h.scenes[h.scenes.length - 1] as FakeScene;
const count = (name: string) => (scene().calls[name] ?? []).length;
const last = (name: string) => {
  const c = scene().calls[name] ?? [];
  return c[c.length - 1];
};
const url = (c: string, n: number) => `/p/p-body/c/${c}/stage/${n}`;
const ready = async () => {
  await waitFor(() => expect(screen.getByTestId("v3d-host").getAttribute("data-phase")).toBe("ready"));
  await waitFor(() => expect(last("setArrows")).toBeTruthy());
  await waitFor(() => expect(last("setLegend")).toBeTruthy());
};
const rangeMax = () => Number(screen.getByTestId("v3d-legend").getAttribute("data-range-max"));
const layerCalls = (layer: string) => (scene().calls["setLayerVisible"] ?? []).filter((c) => c[0] === layer).map((c) => c[1]);
const lastOf = <T,>(a: T[]): T => a[a.length - 1];
const openGear = () => fireEvent.click(screen.getByTestId("v3d-gear"));

beforeEach(() => {
  h.scenes.length = 0;
  localStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

describe("V-0246-VW-1 VIEWER_PLANS 계획 표", () => {
  it("모든 행·열 채움, LEVEL_CHOICES 0 포함, 알 수 없는 키 = 오류", () => {
    expect(Object.keys(VIEWER_PLANS).sort()).toEqual(["case_disp", "case_load", "study_design", "study_jigdiag", "study_recon"]);
    for (const [k, p] of Object.entries(VIEWER_PLANS)) {
      expect(p.layers.length, k).toBeGreaterThan(0);
      expect(["none", "pair"], k).toContain(p.sync);
      for (const f of ["bc", "load", "ghost", "marks"] as const) expect(typeof p.defaults[f], `${k}.${f}`).toBe("boolean");
      expect((LEVEL_CHOICES as readonly number[]).includes(p.defaults.levels), k).toBe(true);
    }
    expect(LEVEL_CHOICES[0]).toBe(0);
    expect([...LEVEL_CHOICES]).toEqual([0, 6, 9, 12]);
    expect(() => planOf("nope")).toThrow();
    // Q-VW-3 기본 가정: 연속·최대 표식 켬·원형 끔, 경계조건·하중 켬(지금 그림)
    expect(planOf("case_load").defaults).toEqual({ bc: true, load: true, ghost: false, marks: true, levels: 0 });
    expect(planOf("study_design").sync).toBe("pair");
    expect(planOf("case_load").sync).toBe("none");
  });
});

describe("V-0246-VW-2·3 층 켜기/끄기 · 단축키", () => {
  it("칩 클릭 → setLayerVisible 만(재요청 0·장면 다시 만들기 0), 기본 = 켬", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const sc = scene();
    expect(lastOf(layerCalls("supports"))).toBe(true);
    expect(lastOf(layerCalls("arrows"))).toBe(true);
    const reqs: string[] = [];
    const f0 = globalThis.fetch;
    globalThis.fetch = ((i: RequestInfo | URL, init?: RequestInit) => (reqs.push(String(i)), f0(i, init))) as typeof fetch;
    const nSup = count("setSupports");
    const nArr = count("setArrows");
    const bc = screen.getByTestId("v3d-layer-bc");
    expect(bc.textContent).toBe("경계조건");
    expect(bc.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(bc);
    expect(bc.getAttribute("aria-pressed")).toBe("false");
    expect(lastOf(layerCalls("supports"))).toBe(false);
    fireEvent.click(screen.getByTestId("v3d-layer-load"));
    expect(lastOf(layerCalls("arrows"))).toBe(false);
    fireEvent.click(bc);
    expect(lastOf(layerCalls("supports"))).toBe(true);
    expect(reqs).toEqual([]);
    expect(count("setSupports")).toBe(nSup);
    expect(count("setArrows")).toBe(nArr);
    expect(sc.calls["dispose"]).toBeUndefined();
    globalThis.fetch = f0;
  });

  it("지지 선택 중 경계조건 끔 → 선택 해제, 데이터 없으면 칩 비활성 + 사유", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    act(() => scene().emit({ type: "support", index: 0 }));
    await waitFor(() => expect(screen.getByTestId("v3d-info").textContent).toContain("지지"));
    fireEvent.click(screen.getByTestId("v3d-layer-bc"));
    await waitFor(() => expect(screen.queryByTestId("v3d-info")).toBeNull());
  });

  it("지지 0개·화살표 0개 → 칩 비활성 + title", async () => {
    const m = { ...(mockView3d().manifest("c-demo") as View3dOut), supports: [] };
    vi.spyOn(api, "view3d").mockResolvedValue(m);
    renderApp(url("c-demo", 4));
    await ready();
    const bc = screen.getByTestId("v3d-layer-bc") as HTMLButtonElement;
    expect(bc.disabled).toBe(true);
    expect(bc.title).toBe("이 보기에 경계조건 표식이 없습니다");
    expect(bc.getAttribute("aria-pressed")).toBe("false");
    expect((screen.getByTestId("v3d-layer-load") as HTMLButtonElement).disabled).toBe(false);
  });

  it("하중 끔 + 표 행 선택 → 화살표 강조 없이 노드 표식, 바닥 문구 ' · 화살표 숨김'", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const note = screen.getByTestId("v3d-note");
    expect(note.textContent).not.toContain("화살표 숨김");
    fireEvent.click(screen.getByTestId("v3d-layer-load"));
    expect(note.textContent).toMatch(/ · 화살표 숨김$/);
    const row = screen.getAllByRole("row").find((r) => r.getAttribute("data-key") === "3")!;
    fireEvent.click(row);
    await waitFor(() => {
      const s = last("select")!;
      expect(s[0]).toBeNull();
      expect(typeof s[1]).toBe("number");
    });
    // 하중 켜면 화살표 강조 복귀
    fireEvent.click(screen.getByTestId("v3d-layer-load"));
    await waitFor(() => expect(typeof last("select")![0]).toBe("number"));
  });

  it("단축키 B·L(3D 칸 초점), 입력 칸 초점이면 무시", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const host = screen.getByTestId("v3d-host");
    fireEvent.keyDown(host, { key: "b" });
    expect(screen.getByTestId("v3d-layer-bc").getAttribute("aria-pressed")).toBe("false");
    fireEvent.keyDown(host, { key: "L" });
    expect(screen.getByTestId("v3d-layer-load").getAttribute("aria-pressed")).toBe("false");
    const input = document.createElement("input");
    host.appendChild(input);
    fireEvent.keyDown(input, { key: "b" });
    expect(screen.getByTestId("v3d-layer-bc").getAttribute("aria-pressed")).toBe("false");
    fireEvent.keyDown(host, { key: "b" });
    expect(screen.getByTestId("v3d-layer-bc").getAttribute("aria-pressed")).toBe("true");
  });
});

describe("V-0246-VW-4 bandT · 구간 띠", () => {
  it("v = max → 마지막 칸, v < min → 첫 칸, NaN, 퇴화 범위, L = 0 은 normalize", () => {
    expect(bandT(10, 0, 10, 9)).toBeCloseTo(8.5 / 9, 12);
    expect(bandT(99, 0, 10, 9)).toBeCloseTo(8.5 / 9, 12);
    expect(bandT(-5, 0, 10, 9)).toBeCloseTo(0.5 / 9, 12);
    expect(bandT(0, 0, 10, 6)).toBeCloseTo(0.5 / 6, 12);
    expect(bandT(5, 0, 10, 6)).toBeCloseTo(3.5 / 6, 12); // t = .5 → 칸 3
    expect(Number.isNaN(bandT(NaN, 0, 10, 9))).toBe(true);
    expect(Number.isNaN(bandT(Infinity, 0, 10, 0))).toBe(true);
    expect(bandT(5, 3, 3, 9)).toBe(0);
    expect(bandT(5, 4, 3, 12)).toBe(0);
    for (const v of [-1, 0, 2.5, 5, 10, 11]) expect(bandT(v, 0, 10, 0)).toBe(normalize(v, 0, 10));
  });
  it("bandedGradient(9) 계단 정지점 18개, 연속(0) = 지금 띠", () => {
    const g = bandedGradient(9);
    expect(g.match(/rgb\(/g)!.length).toBe(18);
    expect(g).toContain(" 0%");
    expect(g).toContain(" 100%");
    expect(bandedGradient(0)).toContain("linear-gradient(90deg");
    expect(bandedGradient(0).match(/rgb\(/g)!.length).toBe(9);
  });
});

describe("V-0246-VW-5 범례 변경 = setLegend 만", () => {
  it("범위·레벨 변경 → setLegend 만, setField 0회·valueUploads 불변·colorLoops 0·setColors 0", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const sc = scene();
    const f0 = count("setField");
    const up0 = sc.stats().valueUploads;
    expect(f0).toBeGreaterThan(0);
    expect(count("setColors")).toBe(0);
    expect(last("setLegend")![0]).toMatchObject({ levels: 0 });
    const inp = within(screen.getByTestId("v3d-legend")).getByLabelText("범위 최대");
    fireEvent.change(inp, { target: { value: "0.5" } });
    await waitFor(() => expect(last("setLegend")![0]).toMatchObject({ min: 0, max: 0.5, levels: 0 }));
    openGear();
    const seg = screen.getByTestId("v3d-opt-levels");
    fireEvent.click(seg.querySelector("[data-levels='9']")!);
    await waitFor(() => expect(last("setLegend")![0]).toMatchObject({ max: 0.5, levels: 9 }));
    fireEvent.click(seg.querySelector("[data-levels='6']")!);
    await waitFor(() => expect(last("setLegend")![0]).toMatchObject({ levels: 6 }));
    expect(count("setField")).toBe(f0);
    expect(sc.stats().valueUploads).toBe(up0);
    expect(sc.stats().colorLoops).toBe(0);
    expect(count("setColors")).toBe(0);
    // 구간이면 바닥 띠 = 계단, 연속이면 지금 띠
    expect((screen.getByTestId("v3d-legend").querySelector(".ramp") as HTMLElement).style.background).toContain("rgb(");
  });
});

describe("V-0246-VW-6 LegendOverlay", () => {
  const R = { min: 0, max: 9 };
  it("연속이면 렌더 없음", () => {
    const { container } = render(<LegendOverlay levels={0} range={R} title="x" hostHeight={600} />);
    expect(container.firstChild).toBeNull();
  });
  it("L+1 경계값(f3), 위 = 최대, ▲▼ 개수, 최대 표식 한 줄", () => {
    render(<LegendOverlay levels={9} range={R} title="변위 |u| (mm)" above={3} below={2} maxLine="최대 9 @N 7" hostHeight={900} />);
    const ticks = screen.getAllByTestId("v3d-legend-ov-tick").map((e) => e.textContent);
    expect(ticks).toHaveLength(10);
    expect(ticks[0]).toBe("9");
    expect(lastOf(ticks)).toBe("0");
    expect(screen.getByTestId("v3d-legend-ov-above").textContent).toContain("3");
    expect(screen.getByTestId("v3d-legend-ov-below").textContent).toContain("2");
    expect(screen.getByTestId("v3d-legend-ov-max").textContent).toBe("최대 9 @N 7");
    expect(screen.getByTestId("v3d-legend-ov").getAttribute("aria-hidden")).toBe("true");
  });
  it("높이가 모자라면 경계값을 한 칸 걸러(최대·최소 유지)", () => {
    expect(boundaryIndices(12, 20, 16)).toHaveLength(13);
    expect(boundaryIndices(12, 10, 16)).toEqual([0, 2, 4, 6, 8, 10, 12]);
    expect(boundaryIndices(9, 10, 16)).toEqual([0, 2, 4, 6, 8, 9]);
    render(<LegendOverlay levels={12} range={R} title="t" hostHeight={150} />);
    expect(screen.getAllByTestId("v3d-legend-ov-tick").length).toBeLessThan(13);
  });
  it("카드: 구간 선택 시 겹침 범례가 칸 안에 생기고 연속으로 돌리면 사라진다", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    expect(screen.queryByTestId("v3d-legend-ov")).toBeNull();
    openGear();
    fireEvent.click(screen.getByTestId("v3d-opt-levels").querySelector("[data-levels='9']")!);
    await waitFor(() => expect(screen.getByTestId("v3d-legend-ov")).toBeTruthy());
    expect(screen.getByTestId("v3d-host").parentElement!.contains(screen.getByTestId("v3d-legend-ov"))).toBe(true);
    fireEvent.click(screen.getByTestId("v3d-opt-levels").querySelector("[data-levels='0']")!);
    await waitFor(() => expect(screen.queryByTestId("v3d-legend-ov")).toBeNull());
  });
});

describe("V-0246-VW-7 extremes · 최대 표식", () => {
  it("NaN·Inf 무시, 동률은 작은 정점", () => {
    const e = extremes([NaN, 2, 5, 5, -1, Infinity, -1]);
    expect(e.max).toEqual({ vertex: 2, value: 5 });
    expect(e.min).toEqual({ vertex: 4, value: -1 });
    expect(extremes([NaN, NaN])).toEqual({ max: null, min: null });
    expect(extremes([])).toEqual({ max: null, min: null });
  });
  it("zero 종류 = 최대만, 그 밖 = 최대·최소", () => {
    expect(marksFor([1, 3, 2], "zero").map((m) => m.which)).toEqual(["max"]);
    expect(marksFor([1, 3, 2], "sym").map((m) => m.which)).toEqual(["max", "min"]);
    expect(marksFor([1, 3, 2], "minmax").map((m) => m.which)).toEqual(["max", "min"]);
  });
  it("카드: 최대 표식 문구 '최대 v 단위 · N<id>', 변형 배율이 바뀌면 위치만, 끄면 빈 목록", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const man = mockView3d().manifest("x");
    const vals = decodeValues(mockView3d().values, man);
    const ex = extremes(vals.pa!);
    const g = parseGlb(mockView3d().glb);
    const marks = last("setValueMarks")![0] as { vertex: number; text: string; position: number[] }[];
    expect(marks).toHaveLength(1);
    expect(marks[0].vertex).toBe(ex.max!.vertex);
    expect(marks[0].text).toMatch(/^최대 .+ MPa · N\d+$/);
    expect(marks[0].text.endsWith(`N${g.nodeIds![ex.max!.vertex]}`)).toBe(true);
    // 변위 보기(최대 위치에서 u ≠ 0)에서 변형 켜고 배율 바꾸면 같은 문구·다른 위치
    fireEvent.click(screen.getByTestId("v3d-mode").querySelector("[data-mode=tgt]")!);
    await waitFor(() => expect(screen.getByTestId("v3d-legend").textContent).toContain("목표 변위"));
    await waitFor(() => expect((lastOf(scene().calls["setValueMarks"]!)[0] as typeof marks)[0].text).toMatch(/ mm · N/));
    fireEvent.click(screen.getByRole("button", { name: "변형 형상" }));
    const m1 = last("setValueMarks")![0] as typeof marks;
    fireEvent.change(screen.getByLabelText("변형 확대 배율"), { target: { value: "3" } });
    const m2 = last("setValueMarks")![0] as typeof marks;
    expect(m2[0].text).toBe(m1[0].text);
    expect(m2[0].position).not.toEqual(m1[0].position);
    openGear();
    fireEvent.click(screen.getByTestId("v3d-opt-marks"));
    expect(last("setValueMarks")![0]).toEqual([]);
    expect(lastOf(layerCalls("marks"))).toBe(false);
  });
  it("영역 색(fieldOverride)은 표식 없음", async () => {
    const m = mockView3d().manifest("r1") as View3dOut;
    vi.spyOn(api, "view3d").mockResolvedValue(m);
    const values = new Float32Array(m.n_nodes).map((_, i) => i % 7);
    function T() {
      const v = useLoadView("r1", true, null);
      return v ? <View3DCard view={v} options={{ colorBy: "disp", fieldOverride: { values, min: 0, max: 6, label: "영역" } }} /> : null;
    }
    render(<T />);
    await waitFor(() => expect(last("setLegend")).toBeTruthy());
    expect(last("setValueMarks")![0]).toEqual([]);
  });
});

describe("V-0246-VW-8 featureEdges", () => {
  // 접힌 판: x 0..2, y 0..1(평면 z=0, 두 칸) + 오른쪽 y 1..2 를 90° 위로 접음. 사각형마다 대각선(삼각형 2)
  const P: number[] = [];
  const idx: number[] = [];
  const at = (x: number, y: number, z: number) => (P.push(x, y, z), P.length / 3 - 1);
  const g0 = [0, 1, 2].map((x) => at(x, 0, 0));
  const g1 = [0, 1, 2].map((x) => at(x, 1, 0));
  const g2 = [0, 1, 2].map((x) => at(x, 1, 1)); // 접힘 뒤 위로 선 면
  const quad = (a: number, b: number, c: number, d: number) => idx.push(a, b, c, a, c, d);
  for (let i = 0; i < 2; i++) quad(g0[i], g0[i + 1], g1[i + 1], g1[i]);
  for (let i = 0; i < 2; i++) quad(g1[i], g1[i + 1], g2[i + 1], g2[i]);
  const key = (a: number, b: number) => (a < b ? `${a}-${b}` : `${b}-${a}`);
  const edges = featureEdges(Float32Array.from(P), Uint32Array.from(idx));
  const set = new Set<string>();
  for (let i = 0; i < edges.length; i += 2) set.add(key(edges[i], edges[i + 1]));
  it("자유 경계 + 접힘선 포함, 평면 사각형 대각선 제외", () => {
    // 접힘선 g1: (1,1,0)-(2,1,0) …
    expect(set.has(key(g1[0], g1[1]))).toBe(true);
    expect(set.has(key(g1[1], g1[2]))).toBe(true);
    // 바깥 경계
    expect(set.has(key(g0[0], g0[1]))).toBe(true);
    expect(set.has(key(g0[0], g1[0]))).toBe(true);
    expect(set.has(key(g2[1], g2[2]))).toBe(true);
    // 대각선(g0[0]-g1[1], g0[1]-g1[2], g1[0]-g2[1], g1[1]-g2[2]) 은 없음
    expect(set.has(key(g0[0], g1[1]))).toBe(false);
    expect(set.has(key(g0[1], g1[2]))).toBe(false);
    expect(set.has(key(g1[0], g2[1]))).toBe(false);
    // 평면 안 내부 모서리(g0[1]-g1[1])도 없음
    expect(set.has(key(g0[1], g1[1]))).toBe(false);
    expect(FEATURE_DEG).toBe(30);
    expect(featureEdges(new Float32Array(0), new Uint32Array(0)).length).toBe(0);
  });
  it("면 방향이 뒤집혀도 같은 결과", () => {
    const flipped = idx.slice();
    for (let t = 0; t < flipped.length; t += 6) [flipped[t + 1], flipped[t + 2]] = [flipped[t + 2], flipped[t + 1]]; // 사각형 한 쌍의 앞 삼각형만 뒤집음
    const e2 = featureEdges(Float32Array.from(P), Uint32Array.from(flipped));
    const s2 = new Set<string>();
    for (let i = 0; i < e2.length; i += 2) s2.add(key(e2[i], e2[i + 1]));
    expect(s2.has(key(g1[0], g1[1]))).toBe(true);
    expect(s2.has(key(g0[0], g1[1]))).toBe(false);
  });
  it("고정 fixture(tests/fixtures/view3d/small): 자유 경계 모서리 수 = 독립 계산", async () => {
    const b = readFileSync(path.resolve(__dirname, "../../../tests/fixtures/view3d/small/part.glb"));
    const buf = new ArrayBuffer(b.byteLength);
    new Uint8Array(buf).set(b);
    const gl = parseGlb(buf);
    const cnt = new Map<string, number>();
    for (let t = 0; t < gl.indices.length; t += 3)
      for (let e = 0; e < 3; e++) {
        const k = key(gl.indices[t + e], gl.indices[t + ((e + 1) % 3)]);
        cnt.set(k, (cnt.get(k) ?? 0) + 1);
      }
    const boundary = [...cnt.values()].filter((v) => v === 1).length;
    const fe = featureEdges(gl.positions, gl.indices);
    const fs = new Set<string>();
    for (let i = 0; i < fe.length; i += 2) fs.add(key(fe[i], fe[i + 1]));
    let seenBoundary = 0;
    for (const [k, v] of cnt) if (v === 1 && fs.has(k)) seenBoundary++;
    expect(seenBoundary).toBe(boundary);
    expect(fe.length / 2).toBeGreaterThanOrEqual(boundary);
  });
  it("합성 mock 판 3만 노드급도 빠르다(≤ 1 s) — 해시 타입 배열", () => {
    const m = makeMesh();
    const t0 = performance.now();
    const e = featureEdges(Float32Array.from(m.x), m.indices);
    expect(performance.now() - t0).toBeLessThan(1000);
    expect(e.length).toBeGreaterThan(0);
  });
  it("카드: 변형 켠 뒤 ⚙ 에서 원형을 켜면 특징선 1회 계산·setGhostEdges 1회, 변형 끄면 층 숨김", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    openGear();
    const cb = screen.getByTestId("v3d-opt-ghost") as HTMLInputElement;
    expect(cb.disabled).toBe(true);
    expect(cb.closest("label")!.title).toContain("변형 형상");
    fireEvent.click(screen.getByRole("button", { name: "변형 형상" }));
    expect(cb.disabled).toBe(false);
    expect(count("setGhostEdges")).toBe(0);
    fireEvent.click(cb);
    await waitFor(() => expect(count("setGhostEdges")).toBe(1));
    expect(lastOf(layerCalls("ghost"))).toBe(true);
    fireEvent.click(cb);
    fireEvent.click(cb);
    expect(count("setGhostEdges")).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "변형 형상" }));
    expect(lastOf(layerCalls("ghost"))).toBe(false);
  });
});

describe("V-0246-VW-9 infoLine 탐침", () => {
  const man = mockView3d().manifest("x");
  const vals = decodeValues(mockView3d().values, man);
  const g = parseGlb(mockView3d().glb);
  const v = 100;
  it("변위 보기: 노드 · 값 · u 성분 · 면압… · 좌표 순서, 양자화 표기", () => {
    const disp = new Float32Array(man.n_nodes);
    for (let i = 0; i < disp.length; i++) disp[i] = Math.hypot(vals.u![i * 3], vals.u![i * 3 + 1], vals.u![i * 3 + 2]);
    const line = infoLine({ kind: "vertex", vertex: v }, man, vals, g.nodeIds, {
      color: { short: shortFieldName("응답 변위 |u_fit| (mm)"), values: disp, unit: "mm", step: Math.max(...vals.scale.u) },
      u: vals.u,
      uStep: vals.scale.u,
      xyz: g.positions,
    })!;
    const parts = line.split(" · ");
    expect(parts[0]).toBe(`노드 ${g.nodeIds![v]}`);
    expect(parts[1]).toMatch(/^응답 변위 \|u_fit\| -?\d+(\.\d+)? mm$/);
    expect(parts[2]).toMatch(/^u \(-?[\d.]+, -?[\d.]+, -?[\d.]+\) mm$/);
    expect(parts[3]).toMatch(/^면압 /);
    expect(lastOf(parts)).toMatch(/^\(-?[\d.,]+, -?[\d.,]+, -?[\d.,]+\) mm$/);
    // 양자화 간격까지만(u 간격보다 긴 소수 자리 없음)
    const dec = Math.max(0, Math.ceil(-Math.log10(vals.scale.u[0])));
    expect(parts[2].match(/\((-?[\d.]+),/)![1].split(".")[1]?.length ?? 0).toBe(dec);
  });
  it("recon 배열(float32)은 f3, 추가 정보가 없으면 지금 문구 그대로", () => {
    const u = new Float32Array(man.n_nodes * 3).fill(0.123456);
    const line = infoLine({ kind: "vertex", vertex: v }, man, vals, g.nodeIds, { u, uStep: null })!;
    expect(line).toContain("u (0.1235, 0.1235, 0.1235) mm");
    const plain = infoLine({ kind: "vertex", vertex: v }, man, vals, g.nodeIds)!;
    expect(plain).not.toContain("u (");
    expect(plain.startsWith(`노드 ${g.nodeIds![v]} · 면압`)).toBe(true);
    expect(shortFieldName("변위 |u| (mm)")).toBe("변위 |u|");
  });
  it("카드: 변위 보기 클릭 정보 줄에 값·u·좌표", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    fireEvent.click(screen.getByTestId("v3d-mode").querySelector("[data-mode=tgt]")!);
    await waitFor(() => expect(screen.getByTestId("v3d-legend").textContent).toContain("목표 변위"));
    act(() => scene().emit({ type: "vertex", vertex: 200 }));
    await waitFor(() => expect(screen.getByTestId("v3d-info").textContent).toMatch(/목표 변위 \|u_tgt\| .+ mm · u \(.+\) mm · .*\(.+\) mm$/));
  });
});

describe("V-0246-VW-10 ③ 수동 범위 유지", () => {
  it("수동 범위 → 출처 탭 전환 후 유지, [자동] → 자동, 하중 범위 키에 출처 없음", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const auto = rangeMax();
    const inp = within(screen.getByTestId("v3d-legend")).getByLabelText("범위 최대");
    fireEvent.change(inp, { target: { value: "0.37" } });
    await waitFor(() => expect(rangeMax()).toBeCloseTo(0.37, 6));
    expect(screen.getByTestId("v3d-legend").getAttribute("data-manual")).toBe("true");
    const keys = Object.keys(localStorage).filter((k) => k.startsWith("esl.legend.v1:"));
    expect(keys).toEqual(["esl.legend.v1:c-demo:load:pa"].map((k) => keys.find((x) => x.endsWith(":load:pa")) ?? k));
    expect(keys.every((k) => !/:(full|bforce|fint|jig)/.test(k.replace(/^esl\.legend\.v1:/, "").replace(/c-demo.*?:load:\w+$/, "")))).toBe(true);
    const tab = (k: string) => screen.getByTestId("v3d-src-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
    fireEvent.click(tab("bforce"));
    await waitFor(() => expect(tab("bforce").getAttribute("aria-selected")).toBe("true"));
    await ready();
    await waitFor(() => expect(rangeMax()).toBeCloseTo(0.37, 6));
    expect(screen.getByTestId("v3d-legend").getAttribute("data-manual")).toBe("true");
    fireEvent.click(within(screen.getByTestId("v3d-legend")).getByRole("button", { name: "자동" }));
    await waitFor(() => expect(rangeMax()).toBeCloseTo(auto, 6));
  });
  it("변위 보기 수동 범위(목표·응답 공통)도 출처 전환 후 유지", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const tab = (k: string) => screen.getByTestId("v3d-src-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
    fireEvent.click(tab("bforce"));
    await waitFor(() => expect(tab("bforce").getAttribute("aria-selected")).toBe("true"));
    await ready();
    fireEvent.click(screen.getByTestId("v3d-mode").querySelector("[data-mode=fit]")!);
    await waitFor(() => expect(screen.getByTestId("v3d-recon-line").textContent).toContain("재현 MAC"));
    fireEvent.change(within(screen.getByTestId("v3d-legend")).getByLabelText("범위 최대"), { target: { value: "0.2" } });
    await waitFor(() => expect(rangeMax()).toBeCloseTo(0.2, 6));
    // 출처 탭 전환 시 보기는 하중으로 초기화되지만 수동 범위는 그대로 — 목표 보기에서 다시 확인
    fireEvent.click(tab("full"));
    await waitFor(() => expect(tab("full").getAttribute("aria-selected")).toBe("true"));
    await ready();
    fireEvent.click(screen.getByTestId("v3d-mode").querySelector("[data-mode=tgt]")!);
    await waitFor(() => expect(screen.getByTestId("v3d-legend").textContent).toContain("목표 변위"));
    expect(rangeMax()).toBeCloseTo(0.2, 6);
  });
});

describe("V-0246-VW-11 viewerPrefs", () => {
  it("계획 키별 저장·읽기, 키 1개", () => {
    const s: ViewerState = { bc: false, load: true, ghost: true, marks: false, levels: 9 };
    writeViewerPrefs("case_load", s);
    writeViewerPrefs("study_design", { ...s, levels: 6 });
    expect(readViewerPrefs("case_load")).toEqual(s);
    expect(readViewerPrefs("study_design").levels).toBe(6);
    expect(readViewerPrefs("case_disp")).toEqual(planOf("case_disp").defaults);
    expect(Object.keys(localStorage)).toEqual([VIEWER_KEY]);
    expect(VIEWER_KEY).toBe("esl.v3d.viewer.v1");
  });
  it("localStorage 가 던져도 기본값·쓰기 무시, 형식 오류 무시", () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readViewerPrefs("case_load")).toEqual(planOf("case_load").defaults);
    expect(() => writeViewerPrefs("case_load", planOf("case_load").defaults)).not.toThrow();
    get.mockRestore();
    set.mockRestore();
    localStorage.setItem(VIEWER_KEY, "{broken");
    expect(readViewerPrefs("case_load")).toEqual(planOf("case_load").defaults);
    localStorage.setItem(VIEWER_KEY, JSON.stringify({ case_load: { bc: "yes", load: false, levels: 7 } }));
    expect(readViewerPrefs("case_load")).toEqual({ ...planOf("case_load").defaults, load: false });
    localStorage.setItem(VIEWER_KEY, "[1]");
    expect(readViewerPrefs("case_load")).toEqual(planOf("case_load").defaults);
  });
  it("카드: 끈 층·레벨이 다음 카드에 기억된다(보기 종류별)", async () => {
    const r = renderApp(url("c-demo", 4));
    await ready();
    fireEvent.click(screen.getByTestId("v3d-layer-bc"));
    openGear();
    fireEvent.click(screen.getByTestId("v3d-opt-levels").querySelector("[data-levels='12']")!);
    r.unmount();
    h.scenes.length = 0;
    renderApp(url("c-demo", 4));
    await ready();
    expect(screen.getByTestId("v3d-layer-bc").getAttribute("aria-pressed")).toBe("false");
    expect(last("setLegend")![0]).toMatchObject({ levels: 12 });
    expect(lastOf(layerCalls("supports"))).toBe(false);
  });
});

describe("V-0246-VW-12 ViewerSync", () => {
  const fake = () => {
    let cb: ((s: CameraState) => void) | null = null;
    const apply = vi.fn((s: CameraState) => {
      // 적용 중 장면이 다시 알려도(핑퐁 시뮬레이션) 중계가 막아야 한다
      cb?.(s);
    });
    const sc = { cameraState: () => ({ position: [1, 0, 0], target: [0, 0, 0], up: [0, 0, 1], halfH: 1, zoom: 2 }) as CameraState, applyCameraState: apply, onCameraChange: (c: typeof cb) => (cb = c) } as unknown as SceneApi;
    return { sc, apply, fire: (s: CameraState) => cb?.(s) };
  };
  const cs: CameraState = { position: [5, 5, 5], target: [0, 0, 0], up: [0, 0, 1], halfH: 3, zoom: 1.5 };
  it("한 카드 카메라 변경 → 상대 applyCameraState 1회, 자기 자신 0회, 핑퐁 없음", () => {
    const { result } = renderHook(() => useViewerSync("study_design"));
    const a = fake();
    const b = fake();
    let da = () => {};
    let db = () => {};
    act(() => {
      da = result.current.attach("a", a.sc);
      db = result.current.attach("b", b.sc);
    });
    expect(b.apply).toHaveBeenCalledTimes(1); // 늦게 붙은 카드는 먼저 있던 카드 시점으로
    b.apply.mockClear();
    a.fire(cs);
    expect(b.apply).toHaveBeenCalledTimes(1);
    expect(b.apply).toHaveBeenCalledWith(cs);
    expect(a.apply).not.toHaveBeenCalled();
    b.fire({ ...cs, zoom: 4 });
    expect(a.apply).toHaveBeenCalledTimes(1);
    expect(b.apply).toHaveBeenCalledTimes(1);
    da();
    db();
    b.apply.mockClear();
    a.fire(cs);
    expect(b.apply).not.toHaveBeenCalled();
  });
  it("층·레벨·변형 공유 상태, 계획 기본값에서 시작하고 층·레벨만 기억", () => {
    const { result } = renderHook(() => useViewerSync("study_design"));
    expect(result.current.state).toMatchObject({ bc: true, load: true, ghost: false, marks: true, levels: 0, deformOn: false, real: false });
    act(() => result.current.set({ bc: false, levels: 9, deformOn: true, kexp: 2 }));
    expect(result.current.state).toMatchObject({ bc: false, levels: 9, deformOn: true, kexp: 2 });
    expect(readViewerPrefs("study_design")).toMatchObject({ bc: false, levels: 9 });
    expect(JSON.stringify(readViewerPrefs("study_design"))).not.toContain("deform");
  });
  it("쌍 카드 둘이 같은 상태를 읽고, Case ③(카드 하나)은 장면에 카메라 중계를 걸지 않는다", async () => {
    const m = mockView3d().manifest("r1") as View3dOut;
    vi.spyOn(api, "view3d").mockResolvedValue(m);
    function Pair() {
      const sync = useViewerSync("study_design");
      const a = useLoadView("r1", true, null);
      const b = useLoadView("r1", true, null);
      return (
        <>
          {a && <View3DCard view={a} options={{ title: "A", plan: "study_design", viewerSync: sync }} />}
          {b && <View3DCard view={b} options={{ title: "B", plan: "study_design", viewerSync: sync }} />}
        </>
      );
    }
    render(<Pair />);
    await waitFor(() => expect(h.scenes.length).toBe(2));
    await waitFor(() => expect((h.scenes[1] as FakeScene).calls["setLegend"]).toBeTruthy());
    const [sa, sb] = h.scenes as FakeScene[];
    const chips = screen.getAllByTestId("v3d-layer-bc");
    fireEvent.click(chips[0]);
    expect(chips[1].getAttribute("aria-pressed")).toBe("false");
    expect(lastOf(sb.calls["setLayerVisible"]!.filter((c) => c[0] === "supports"))[1]).toBe(false);
    // 카메라 중계: A 변경 → B 적용
    await waitFor(() => expect((sa as unknown as { hasCamCb: () => boolean }).hasCamCb()).toBe(true));
    const n0 = (sb.calls["applyCameraState"] ?? []).length;
    act(() => sa.emitCam({ position: [9, 9, 9], target: [0, 0, 0], up: [0, 0, 1], halfH: 1, zoom: 1 }));
    expect((sb.calls["applyCameraState"] ?? []).length).toBe(n0 + 1);
    // 변형 공유
    fireEvent.click(screen.getAllByRole("button", { name: "변형 형상" })[0]);
    expect(screen.getAllByRole("button", { name: "변형 형상" })[1].getAttribute("aria-pressed")).toBe("true");
  });
  it("Case ③ 은 sync 없음 — onCameraChange 를 걸지 않는다", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    expect((scene() as unknown as { hasCamCb: () => boolean }).hasCamCb()).toBe(false);
  });
});

describe("V-0246-VW-13 편집 보기(controls 없음) 막대 DOM 불변", () => {
  it("ViewToolbar lead/tail 없음 = 버튼 5개(X·Y·Z·등각·꽉 차게), 칩·구분선·⚙ 없음", () => {
    const { container } = render(<ViewToolbar scene={() => null} modelBbox={{ min: [0, 0, 0], max: [1, 1, 1] }} />);
    const bar = container.querySelector(".v3d-view-bar")!;
    expect(Array.from(bar.children).map((c) => c.getAttribute("aria-label"))).toEqual(["X 보기", "Y 보기", "Z 보기", "등각 보기", "꽉 차게 보기"]);
    expect(bar.querySelector(".v3d-bar-sep, .v3d-chip, [data-testid=v3d-gear]")).toBeNull();
  });
  it("PartStage 에 controls 를 안 주면 칩·⚙ 없음, 주면 막대 안에 [칩] ┃ 시점 ┃ [⚙]", async () => {
    const { PartStage } = await import("../view3d/part/PartStage");
    const ref = { current: null } as unknown as React.RefObject<HTMLDivElement>;
    const bb = { min: [0, 0, 0], max: [1, 1, 1] };
    const { container, rerender } = render(<PartStage host={ref} scene={() => null} phase="ready" bbox={bb} testId="x" ariaLabel="x" />);
    expect(container.querySelector(".v3d-chip, [data-testid=v3d-gear]")).toBeNull();
    rerender(<PartStage host={ref} scene={() => null} phase="ready" bbox={bb} testId="x" ariaLabel="x" controls={{ lead: <b className="v3d-chip">L</b>, tail: <i data-testid="v3d-gear">T</i> }} />);
    const kids = Array.from(container.querySelector(".v3d-view-bar")!.children);
    expect(kids[0].className).toBe("v3d-chip");
    expect(lastOf(kids).getAttribute("data-testid")).toBe("v3d-gear");
  });
});

describe("⚙ 팝오버 접근성", () => {
  it("Esc 로 닫고 ⚙ 로 초점 복귀, 바깥 클릭으로 닫힘, 막대 안(절대 위치) 렌더", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const gear = screen.getByTestId("v3d-gear");
    expect(gear.getAttribute("aria-expanded")).toBe("false");
    openGear();
    const pop = screen.getByTestId("v3d-viewer-pop");
    expect(screen.getByTestId("v3d-view-bar").contains(pop)).toBe(true);
    expect(pop.textContent).toContain("이 브라우저에 기억됩니다");
    fireEvent.keyDown(pop, { key: "Escape" });
    expect(screen.queryByTestId("v3d-viewer-pop")).toBeNull();
    expect(document.activeElement).toBe(gear);
    openGear();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByTestId("v3d-viewer-pop")).toBeNull();
  });
});

// ---- 검증 수정 2·3: 계획 표 열이 실제 동작을 결정 · 쌍 기본 배율은 적재 순서와 무관 ----
describe("검증 수정 2 계획 표 열 = 동작 (변이 시험: 열 값을 바꾸면 동작이 바뀜)", () => {
  const withRow = async (key: string, patch: Partial<(typeof VIEWER_PLANS)[string]>, fn: () => Promise<void>) => {
    const orig = VIEWER_PLANS[key];
    VIEWER_PLANS[key] = { ...orig, ...patch };
    try {
      await fn();
    } finally {
      VIEWER_PLANS[key] = orig;
    }
  };
  function Pair({ planKey }: { planKey: string }) {
    const sync = useViewerSync(planKey);
    const a = useLoadView("r1", true, null);
    const b = useLoadView("r1", true, null);
    return (
      <>
        {a && <View3DCard view={a} options={{ title: "A", plan: planKey, viewerSync: sync }} />}
        {b && <View3DCard view={b} options={{ title: "B", plan: planKey, viewerSync: sync }} />}
      </>
    );
  }
  const openPair = async (planKey: string) => {
    vi.spyOn(api, "view3d").mockResolvedValue(mockView3d().manifest("r1") as View3dOut);
    render(<Pair planKey={planKey} />);
    await waitFor(() => expect(h.scenes.length).toBe(2));
    await waitFor(() => expect((h.scenes[1] as FakeScene).calls["setLegend"]).toBeTruthy());
    await waitFor(() => expect(screen.getAllByTestId("v3d-layer-bc")).toHaveLength(2));
  };
  it("sync = pair: 칩·시점·변형이 상대 카드에 / sync = none 으로 바꾸면 viewerSync 를 줘도 따로", async () => {
    await withRow("study_design", { sync: "pair" }, async () => {
      await openPair("study_design");
      const [sa, sb] = h.scenes as FakeScene[];
      fireEvent.click(screen.getAllByTestId("v3d-layer-bc")[0]);
      expect(screen.getAllByTestId("v3d-layer-bc")[1].getAttribute("aria-pressed")).toBe("false");
      await waitFor(() => expect((sa as unknown as { hasCamCb: () => boolean }).hasCamCb()).toBe(true));
      const n0 = (sb.calls["applyCameraState"] ?? []).length;
      act(() => sa.emitCam({ position: [9, 9, 9], target: [0, 0, 0], up: [0, 0, 1], halfH: 1, zoom: 1 }));
      expect((sb.calls["applyCameraState"] ?? []).length).toBe(n0 + 1);
      cleanup();
    });
    h.scenes.length = 0;
    localStorage.clear();
    await withRow("study_design", { sync: "none" }, async () => {
      await openPair("study_design");
      const [sa, sb] = h.scenes as FakeScene[];
      fireEvent.click(screen.getAllByTestId("v3d-layer-bc")[0]);
      expect(screen.getAllByTestId("v3d-layer-bc")[0].getAttribute("aria-pressed")).toBe("false");
      expect(screen.getAllByTestId("v3d-layer-bc")[1].getAttribute("aria-pressed")).toBe("true"); // 상대 카드 그대로
      fireEvent.click(screen.getAllByRole("button", { name: "변형 형상" })[0]);
      expect(screen.getAllByRole("button", { name: "변형 형상" })[1].getAttribute("aria-pressed")).toBe("false");
      expect((sa as unknown as { hasCamCb: () => boolean }).hasCamCb()).toBe(false);
      expect((sb as unknown as { hasCamCb: () => boolean }).hasCamCb()).toBe(false);
    });
  });
  it("layers 에서 bc 를 빼면: 칩·단축키 없음 + 장면 지지 층은 사용자 값이 켬이어도 꺼짐(칩에만 적용되던 결함)", async () => {
    await withRow("case_load", { layers: ["load", "ghost", "marks"] }, async () => {
      renderApp(url("c-demo", 4));
      await ready();
      expect(screen.queryByTestId("v3d-layer-bc")).toBeNull();
      expect(screen.getByTestId("v3d-layer-load")).toBeTruthy();
      expect(lastOf(layerCalls("supports"))).toBe(false);
      expect(lastOf(layerCalls("arrows"))).toBe(true);
    });
    h.scenes.length = 0;
    cleanup();
    renderApp(url("c-demo", 4)); // 원래 행: 지지 층 켬
    await ready();
    expect(lastOf(layerCalls("supports"))).toBe(true);
  });
  it("layers 에서 marks 를 빼면 최대 표식 목록이 비고 층도 꺼짐, 원래 행은 표식 1개", async () => {
    await withRow("case_load", { layers: ["bc", "load", "ghost"] }, async () => {
      renderApp(url("c-demo", 4));
      await ready();
      expect(last("setValueMarks")?.[0] ?? []).toEqual([]);
      expect(lastOf(layerCalls("marks"))).toBe(false);
      expect(screen.queryByTestId("v3d-opt-marks")).toBeNull();
    });
    h.scenes.length = 0;
    cleanup();
    renderApp(url("c-demo", 4));
    await ready();
    expect((last("setValueMarks")![0] as unknown[]).length).toBe(1);
  });
});

describe("검증 수정 3 쌍 기본 배율 = 적재 순서와 무관한 결정적 규칙(pairScaleExp)", () => {
  it("pairScaleExp: 쌍 최대 대각선·최대 변위 기준, 순서 바꿔도 같음, 비면 null", () => {
    const a = { diag: 100, umax: 0.5 };
    const b = { diag: 120, umax: 2 };
    expect(pairScaleExp([a, b])).toBe(pairScaleExp([b, a]));
    expect(pairScaleExp([a, b])).toBe(defaultScaleExp(120, 2));
    expect(pairScaleExp([a])).toBe(defaultScaleExp(100, 0.5));
    expect(pairScaleExp([a, b])).not.toBe(defaultScaleExp(100, 0.5)); // 먼저 로드된 카드(a) 기준이 아님
    expect(pairScaleExp([])).toBeNull();
  });
  it("카드: A 가 먼저 로드되든 B 가 먼저든 두 카드 배율 슬라이더가 같은 값(= 쌍 규칙)", async () => {
    const base = mockView3d().manifest("x") as View3dOut;
    const mk = (u: number, diag: number): View3dOut => ({ ...base, bbox: { ...base.bbox, diag }, ranges: { ...base.ranges, u_max: u } }) as View3dOut;
    const mA = mk(0.5, 100);
    const mB = mk(5, 100);
    const run = async (slow: "rA" | "rB") => {
      h.scenes.length = 0;
      vi.restoreAllMocks();
      vi.spyOn(api, "view3d").mockImplementation(((id: string) => new Promise((res) => setTimeout(() => res(id === "rA" ? mA : mB), id === slow ? 60 : 0))) as never);
      function P() {
        const sync = useViewerSync("study_design");
        const a = useLoadView("rA", true, null);
        const b = useLoadView("rB", true, null);
        return (
          <>
            {a && <View3DCard view={a} options={{ title: "A", plan: "study_design", viewerSync: sync }} />}
            {b && <View3DCard view={b} options={{ title: "B", plan: "study_design", viewerSync: sync }} />}
          </>
        );
      }
      const r = render(<P />);
      await waitFor(() => expect(h.scenes.length).toBe(2), { timeout: 3000 });
      await waitFor(() => expect(screen.getAllByRole("button", { name: "변형 형상" })).toHaveLength(2));
      fireEvent.click(screen.getAllByRole("button", { name: "변형 형상" })[0]);
      await waitFor(() => expect(screen.getAllByLabelText("변형 확대 배율")).toHaveLength(2));
      const v = screen.getAllByLabelText("변형 확대 배율").map((e) => (e as HTMLInputElement).value);
      r.unmount();
      return v;
    };
    const v1 = await run("rA"); // B 먼저
    const v2 = await run("rB"); // A 먼저
    expect(v1[0]).toBe(v1[1]);
    expect(v2[0]).toBe(v2[1]);
    expect(v1).toEqual(v2);
    expect(Number(v1[0])).toBeCloseTo(defaultScaleExp(100, 5), 5); // 큰 변위(B) 기준
    expect(Number(v1[0])).not.toBeCloseTo(defaultScaleExp(100, 0.5), 5);
  });
});
