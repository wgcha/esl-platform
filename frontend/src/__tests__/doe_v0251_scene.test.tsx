// V-0241-V3D-19·20(프런트) + 현장 피드백: 스터디 자료 만들기 버튼 ≤ 1 · 하중 색 토글 · 재현 진단 · 불가 사유 가시 줄.
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PickEvent } from "../view3d/sceneApi";

const h = vi.hoisted(() => ({ webgl: true, scenes: [] as unknown[], loadFails: false }));

vi.mock("../view3d/webgl", () => ({ hasWebGL: () => h.webgl }));
vi.mock("../view3d/loadThree", () => ({
  loadScene: async () => {
    if (h.loadFails) throw new Error("chunk");
    return {
      createScene: (_c: unknown, opts: unknown) => {
        const calls: Record<string, unknown[][]> = {};
        let pick: ((e: PickEvent) => void) | null = null;
        const rec = (name: string) => (...a: unknown[]) => {
          (calls[name] ??= []).push(a);
        };
        let proj = (opts as { projection?: string }).projection ?? "ortho";
        const api = {
          calls,
          opts,
          setProjection: (p: string) => {
            rec("setProjection")(p);
            proj = p;
          },
          projection: () => proj,
          emit: (e: PickEvent) => pick?.(e),
          setGeometry: rec("setGeometry"),
          setColors: rec("setColors"),
          setDeform: rec("setDeform"),
          setArrows: rec("setArrows"),
          setSupports: rec("setSupports"),
          select: rec("select"),
          focus: rec("focus"),
          fit: rec("fit"),
          setView: rec("setView"),
          onPick: (cb: (e: PickEvent) => void) => (pick = cb),
          stats: () => ({ renders: 0 }),
          dispose: rec("dispose"),
        };
        h.scenes.push(api);
        return api;
      },
    };
  },
}));

import { renderApp } from "../test/render";
import { NO_C_TEXT } from "../view3d/View3DCard";
import { PER_ESL_HEAT_SPAN, heatStyle, perEslNote } from "../components/DoePerEslTable";
import { COLOR_SEL_BUTTONS, SCENE_TEXT, colorDisabled, hasScenePair, sceneChoices, sceneSummary, skippedFor, toggleScene } from "../pages/doe/doeScene";
import { sceneManifest } from "../mock/scenemock";
import { css, mapFor, relLuminance, table, textOn } from "../lib/colormap";
import CM from "../../../resources/colormaps.json";
import type { DoeMock } from "../mock/doedata";
import type { DoeResultOut } from "../api/types";

afterEach(cleanup);
let doeMock: DoeMock | null = null;
const open = (id: string) => renderApp(`/p/p-body/doe/${id}`, "power", (s) => {
  s.doe.demoScene();
  doeMock = s.doe;
});
const sel = () => screen.findByTestId("v3d-scene-select", {}, { timeout: 10000 }) as Promise<HTMLSelectElement>;
const calls = () => doeMock!.sceneManifestCalls;
const lastCalls = (n: number) => calls().slice(-n);

describe("V-0251-25 씬 연결 (순수)", () => {
  const mk = (): DoeResultOut => (doeMock ? ({} as DoeResultOut) : ({} as DoeResultOut));
  it("hasScenePair·skippedFor·sceneChoices·toggleScene", () => {
    const r = {
      ranking: [], baseline: {}, view3d: [], warnings: [],
      esl: [{ entry_id: "e1", label: "E1" }, { entry_id: "e2", label: "E2" }],
      scene_view: {
        entries: [{ entry_id: "e1", kk: 0 }, { entry_id: "e2", kk: 1 }],
        packs: { full: { designs: { d000: ["e1"], d001: ["e1"] }, skipped: [{ did: null, entry_id: "e2", code: "SCENE_BUDGET", text: "한도" }] } },
      },
    } as unknown as DoeResultOut;
    void mk;
    expect(hasScenePair(r, "full", "d001", "e1")).toBe(true);
    expect(hasScenePair(r, "full", "d001", "e2")).toBe(false);
    expect(hasScenePair(r, "jig", "d001", "e1")).toBe(false);            // 이 출처 묶음 없음 → 기존 폴더
    expect(skippedFor(r, "full", "d001", "e2")?.code).toBe("SCENE_BUDGET");
    expect(skippedFor(r, "full", "d001", "e1")).toBeNull();
    expect(sceneChoices(r, "full", "d001").map((c) => [c.entry_id, c.missing])).toEqual([["e1", false], ["e2", true]]);
    expect(sceneChoices(r, "jig", "d001").map((c) => c.missing)).toEqual([false, false]);
    expect(toggleScene(null, "e1")).toBe("e1");
    expect(toggleScene("e1", "e1")).toBeNull();
    expect(toggleScene("e1", "e2")).toBe("e2");
  });
  it("씬 요약: C·umax 두 값 + 변화율(표 값과 같은 manifest 값)", () => {
    const b = sceneManifest("s", "full", "d000", "e1", 0);
    const d = sceneManifest("s", "full", "d001", "e1", 0, 1.2);
    const t = sceneSummary({ label: "E1", base: b, cand: d });
    expect(t).toMatch(/^ESL E1 · C 기준 [\d.e+]+ → 안 [\d.e+]+ \([+−]\d+\.\d %\) · umax 기준 [\d.]+ → 안 [\d.]+ \(\+20\.0 %\) mm$/);
    expect(sceneSummary({ label: "E1", base: {}, cand: {} })).toBe("ESL E1");
  });
});

describe("V-0251-27 색 모드 비활성 사유", () => {
  it("c = 두 카드 모두 배열 필요, dc = 안 카드만", () => {
    const b = sceneManifest("s", "full", "d000", "e1", 0);
    const d = sceneManifest("s", "full", "d001", "e1", 0);
    expect(colorDisabled("c", "NC", "ND", b, d)).toBeNull();
    expect(colorDisabled("dc", "NC", "ND", b, d)).toBeNull();
    expect(colorDisabled("dc", "NC", "ND", d, b)).toBe("ND");            // 안 카드 dc null
    expect(colorDisabled("c", "NC", "ND", {}, d)).toBe("NC");
    expect(colorDisabled("disp", "NC", "ND", null, null)).toBeNull();
    expect(COLOR_SEL_BUTTONS.map((x) => x.key)).toEqual(["disp", "load", "c", "dc"]);
  });
});

describe("V-0251-45 ESL 개선율 칸 색(L10)", () => {
  it("개선 = 파랑 쪽 · 악화 = 빨강 쪽 · 0 = 무색 · 세기 ±PER_ESL_HEAT_SPAN · 자원 지도와 같은 rgb", () => {
    const rgb = (b?: string) => (b ?? "").match(/\d+/g)!.map(Number);
    const up = rgb(heatStyle(0.3).background);
    const dn = rgb(heatStyle(-0.3).background);
    expect(up[2]).toBeGreaterThan(up[0]);
    expect(dn[0]).toBeGreaterThan(dn[2]);
    expect(heatStyle(0)).toEqual({});
    expect(PER_ESL_HEAT_SPAN).toBe(0.5);
    expect(heatStyle(0.5).background).toBe(css(mapFor("div"), 0));       // 끝 = 지도 −끝(파랑)
    expect(heatStyle(-0.5).background).toBe(css(mapFor("div"), 1));
    expect(heatStyle(5).background).toBe(css(mapFor("div"), 0));         // 자름
  });
  it("진한 칸 흰 글자(통합 INT): 배경 상대 휘도 < 자원 text.dark_lum → on_dark, 아니면 on_light — 보고서와 같은 표·같은 기대값", () => {
    const tx = (CM as unknown as { text: { dark_lum: number; on_dark: number[]; on_light: number[] } }).text;
    const white = `rgb(${tx.on_dark.join(",")})`;
    const dark = `rgb(${tx.on_light.join(",")})`;
    // tests/doe/test_report_doe.py::test_v0251_45_per_esl_cell_colors 와 같은 (개선율, 기대) 표
    const TEXT_CASES: [number, string][] = [[0.5, white], [0.4, white], [0.3, dark], [0.05, dark], [-0.05, dark], [-0.3, dark], [-0.4, white], [-0.5, white]];
    for (const [imp, want] of TEXT_CASES) expect(heatStyle(imp).color, String(imp)).toBe(want);
    expect(heatStyle(0).color).toBeUndefined();
    for (const role of ["div", "seq"] as const) {
      const tb = table(mapFor(role));
      for (let k = 0; k < 256; k++) {
        const c: [number, number, number] = [tb[k * 3], tb[k * 3 + 1], tb[k * 3 + 2]];
        expect(textOn(c)).toBe(relLuminance(c) < tx.dark_lum ? white : dark);
      }
    }
  });
  it("표 설명 문구", () => {
    const r = { esl: [{ entry_id: "e1" }], ranking: [] } as unknown as DoeResultOut;
    expect(perEslNote(r, null)).toContain("파랑 개선(C 감소) · 빨강 악화(C 증가)");
  });
});

describe("V-0251-25·26 화면: 씬 선택·옛 결과", () => {
  it("3D 바 선택 칸·ESL 표 열 머리·셀·순위표 최악 칸 → 두 카드 요청 URL 의 씬이 바뀜, 안을 바꿔도 유지", async () => {
    open("doe-60");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const s = await sel();
    const opts = [...s.options].map((o) => o.textContent);
    expect(opts[0]).toMatch(/^자동 — 최악 ESL\(/);
    expect(opts.length).toBeGreaterThan(2);
    expect(opts[opts.length - 1]).toContain(SCENE_TEXT.noDataTail.trim());   // 한도로 빠진 마지막 씬
    // 자동 = 씬 묶음의 최악 엔트리(기준 d000 도 같은 씬)
    await waitFor(() => expect(calls().length).toBeGreaterThanOrEqual(2), { timeout: 8000 });
    const auto = calls().slice(-2);
    expect(auto[0].split("/")[2]).toBe(auto[1].split("/")[2]);
    expect(new Set(auto.map((x) => x.split("/")[1]))).toContain("d000");
    // 선택 칸으로 씬 고르기
    const e2 = s.options[2].value;
    fireEvent.change(s, { target: { value: e2 } });
    await waitFor(() => expect(lastCalls(2).every((x) => x.endsWith(`/${e2}`))).toBe(true), { timeout: 8000 });
    await waitFor(() => expect(screen.getByTestId("v3d-scene-summary").textContent).toMatch(/C 기준 .* → 안 .*umax 기준/), { timeout: 8000 });
    // 안을 바꿔도 씬 유지
    const pickSel = screen.getByLabelText("3D 비교 안") as HTMLSelectElement;
    const other = [...pickSel.options].map((o) => o.value).find((v) => v !== pickSel.value)!;
    fireEvent.change(pickSel, { target: { value: other } });
    await waitFor(() => expect(lastCalls(2).every((x) => x.endsWith(`/${e2}`))).toBe(true), { timeout: 8000 });
    expect((await sel()).value).toBe(e2);
    // ESL 표 열 머리: 다른 씬 → 다시 누르면 자동
    const e1 = s.options[1].value;
    fireEvent.click(await screen.findByTestId(`per-esl-col-${e1}`));
    await waitFor(() => expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).toBe(e1));
    fireEvent.click(screen.getByTestId(`per-esl-col-${e1}`));
    await waitFor(() => expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).toBe(""));
    // 셀 클릭 = 그 안 + 그 씬
    const cell = document.querySelector(`[data-testid^="per-esl-cell-"][data-testid$="-${e2}"]`) as HTMLElement;
    const did = cell.getAttribute("data-testid")!.split("-")[3];
    fireEvent.click(cell);
    await waitFor(() => expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).toBe(e2));
    expect((screen.getByLabelText("3D 비교 안") as HTMLSelectElement).value).toBe(did);
    // 순위표 최악 ESL 칸 = 그 안 + 그 씬
    const worst = document.querySelector('[data-testid^="rank-worst-"]') as HTMLElement;
    const wd = worst.getAttribute("data-testid")!.replace("rank-worst-", "");
    fireEvent.click(worst);
    await waitFor(() => expect((screen.getByLabelText("3D 비교 안") as HTMLSelectElement).value).toBe(wd));
    expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).not.toBe("");
  }, 40000);

  it("C 기여도·차이 버튼: 씬 자료가 있으면 활성, 누르면 두 카드 범례 문구", async () => {
    open("doe-60");
    const seg = await screen.findByTestId("v3d-color");
    const cBtn = seg.querySelector("[data-color=c]") as HTMLButtonElement;
    const dBtn = seg.querySelector("[data-color=dc]") as HTMLButtonElement;
    await waitFor(() => expect(cBtn.disabled).toBe(false), { timeout: 8000 });
    expect(dBtn.disabled).toBe(false);
    fireEvent.click(cBtn);
    await waitFor(() => expect(screen.getAllByTestId("v3d-legend")[0].textContent).toContain("C 기여도"), { timeout: 8000 });
    fireEvent.click(dBtn);
    await waitFor(() => expect(screen.getAllByTestId("v3d-legend").map((x) => x.textContent).join("|")).toContain("차이"), { timeout: 8000 });
  }, 30000);

  it("출처 탭마다 같은 규칙: 직접 고른 씬은 탭을 바꿔도 유지, 요청 URL 의 출처 키 = 그 탭", async () => {
    open("doe-60");
    const s = await sel();
    const e2 = s.options[2].value;
    fireEvent.change(s, { target: { value: e2 } });
    const tabs = screen.getByTestId("doe-load-tab");
    let seen = 0;
    for (const k of ["full", "jig", "jig_disp", "jig_spring", "bforce", "fint"]) {
      const b = tabs.querySelector(`[data-tab=${k}]`) as HTMLButtonElement | null;
      if (!b || b.disabled || b.getAttribute("aria-disabled") === "true") continue;
      fireEvent.click(b);
      await waitFor(() => expect(lastCalls(2).every((x) => x.startsWith(`${k}/`) && x.endsWith(`/${e2}`))).toBe(true), { timeout: 8000 });
      expect((screen.getByTestId("v3d-scene-select") as HTMLSelectElement).value).toBe(e2);
      seen += 1;
    }
    expect(seen).toBeGreaterThanOrEqual(2);
  }, 60000);

  it("한도로 빠진 씬 선택 = 안내 + [씬 3D 만들기] 1개", async () => {
    open("doe-60");
    const s = await sel();
    fireEvent.change(s, { target: { value: s.options[s.options.length - 1].value } });
    const m = await screen.findByTestId("v3d-scene-missing");
    expect(m.textContent).toContain("저장 한도");
    expect(screen.getAllByTestId("v3d-scene-add").length).toBe(1);
    fireEvent.click(screen.getByTestId("v3d-scene-add"));
    await waitFor(() => expect(doeMock!.sceneAddCalls).toBe(1));
  }, 30000);

  it("옛 결과(scene_view null): 선택 칸 없음·씬 요청 0·안내 한 줄 + [씬 3D 만들기]", async () => {
    open("doe-61");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    await screen.findByTestId("v3d-scene-oldnote");
    expect(screen.queryByTestId("v3d-scene-select")).toBeNull();
    expect(screen.queryByTestId("v3d-scene-summary")).toBeNull();
    expect(document.querySelector('[data-testid^="rank-worst-"]')).toBeNull();
    expect(document.querySelector('[data-testid^="per-esl-col-"]')).toBeNull();
    const cBtn = (screen.getByTestId("v3d-color").querySelector("[data-color=c]") as HTMLButtonElement);
    expect(cBtn.disabled).toBe(true);
    expect(cBtn.title).toBe(NO_C_TEXT);
    expect(calls().length).toBe(0);
    expect(screen.getAllByTestId("v3d-scene-add").length).toBe(1);
  }, 30000);
});
