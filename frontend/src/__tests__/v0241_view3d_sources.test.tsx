// V-0241-V3D-15~18·21(프런트): Case ③ 3D 하중 출처 탭·보기·하중 색·재현 줄 (esl_view3d_sources.md §9).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PROJ_KEY } from "../view3d/projection";
import type { PickEvent, SceneApi, SceneOptions } from "../view3d/sceneApi";

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

import { renderHook } from "@testing-library/react";
import { api } from "../api/endpoints";
import { ApiError } from "../api/client";
import type { View3dOut, View3dSourcesOut } from "../api/types";
import { API_PREFIX } from "../api/client";
import { renderApp } from "../test/render";
import { resolveFileUrl } from "../view3d/fetchFiles";
import { useLoadView } from "../view3d/useLoadView";
import { LOAD_SOURCES } from "../pages/doe/doeTabs";
import { SOURCE_KEYS, SOURCE_ROWS, caseTabItems, defaultCaseSource, fallbackAllowed, reconLineText, unavailText } from "../view3d/sources";
import { decodeDisp } from "../view3d/values";
import { mockView3d } from "../mock/view3dmock";

type FakeScene = SceneApi & { calls: Record<string, unknown[][]>; emit: (e: PickEvent) => void; opts: SceneOptions };
const scene = () => h.scenes[h.scenes.length - 1] as FakeScene;
const last = (name: string) => {
  const c = scene().calls[name] ?? [];
  return c[c.length - 1];
};
const url = (c: string, n: number) => `/p/p-body/c/${c}/stage/${n}`;
const ready = async () => {
  await waitFor(() => expect(screen.getByTestId("v3d-host").getAttribute("data-phase")).toBe("ready"));
  await waitFor(() => expect(last("setArrows")).toBeTruthy());
};
const tab = (k: string) => screen.getByTestId("v3d-src-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
const mode = (k: string) => screen.getByTestId("v3d-mode").querySelector(`[data-mode=${k}]`) as HTMLButtonElement;
const rangeMax = () => Number(screen.getByTestId("v3d-legend").getAttribute("data-range-max"));

beforeEach(() => {
  h.webgl = true;
  h.loadFails = false;
  h.scenes.length = 0;
  localStorage.removeItem(PROJ_KEY);
  localStorage.clear();
});

const ROWS: View3dSourcesOut["rows"] = [
  { key: "jig", available: false, code: "V3D_STUDY_ONLY", reason: "강성 평가 스터디에서만 계산됩니다(Case 산출물 없음)", resp: false, resp_code: null, resp_reason: null, rigid: null },
  { key: "full", available: true, code: null, reason: null, resp: false, resp_code: "V3D_RESP_NEED_VAL", resp_reason: "응답 변위 없음 — ⑤ 검증에서 전체 풀이를 하면 보입니다", rigid: "linear" },
  { key: "bforce", available: true, code: null, reason: null, resp: true, resp_code: null, resp_reason: null, rigid: "kabsch" },
  { key: "fint", available: false, code: "V3D_SRC_NOT_RUN", reason: "이 ESL 결과에는 없습니다", resp: false, resp_code: null, resp_reason: null, rigid: null },
];

describe("V-0241-V3D-15 출처 표 · 탭 상태", () => {
  it("SOURCE_ROWS 키·순서·이름 = 스터디 LOAD_SOURCES(label·title 같은 값)", () => {
    expect(SOURCE_KEYS).toEqual(["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]);
    expect(LOAD_SOURCES.map((s) => s.key)).toEqual(SOURCE_KEYS as string[]);
    expect(LOAD_SOURCES.map((s) => [s.label, s.title])).toEqual(SOURCE_ROWS.map((s) => [s.label, s.title]));
    expect(SOURCE_ROWS.filter((r) => r.legacy).map((r) => r.key)).toEqual(["full"]);
    expect(SOURCE_ROWS.filter((r) => r.fallback).every((r) => r.legacy)).toBe(true);
  });
  it("unavailText 형식 `<이름> 불가 — <사유>`", () => {
    expect(unavailText("경계력 ESL", "이 ESL 결과에는 없습니다")).toBe("경계력 ESL 불가 — 이 ESL 결과에는 없습니다");
  });
  it("Case 탭 상태·사유 = sources 응답, 기본 탭 = default(불가면 첫 가능 탭)", () => {
    const s: View3dSourcesOut = { esl_run_id: "r", default: "full", rows: ROWS };
    const items = caseTabItems(s)!;
    expect(items.map((i) => [i.key, i.label, i.ok])).toEqual([["jig", "지그 ESL", false], ["full", "전 노드 ESL", true], ["bforce", "경계력 ESL", true], ["fint", "내력 ESL", false]]);
    expect(items[0].why).toBe(unavailText("지그 ESL", "강성 평가 스터디에서만 계산됩니다(Case 산출물 없음)"));
    expect(items[3].why).toBe("내력 ESL 불가 — 이 ESL 결과에는 없습니다");
    expect(defaultCaseSource(s)).toBe("full");
    expect(defaultCaseSource({ ...s, default: "fint" })).toBe("full");
    expect(defaultCaseSource({ ...s, default: "bforce" })).toBe("bforce");
    expect(caseTabItems(null)).toBeNull();
  });
  it("재현 한 줄 문구", () => {
    expect(reconLineText({ mac: 0.934, umax_err: -0.041, rigid: "kabsch" })).toBe("재현 MAC 0.934 · umax 오차 −4.1 % · 강체 제거 Kabsch(S4)");
    expect(reconLineText({ mac: null, umax_err: null, rigid: "linear" })).toBe("재현 MAC – · umax 오차 – · 강체 제거 선형(검증)");
  });
  it("recon.bin 복원(mock pack_disp 왕복)", () => {
    const m = mockView3d();
    const r = m.recon("r", "bforce");
    const d = decodeDisp(m.reconBin, r);
    expect(d.tgt!.length).toBe(r.n_nodes * 3);
    let mx = 0;
    for (let i = 0; i < r.n_nodes; i++) mx = Math.max(mx, Math.hypot(d.err![i * 3], d.err![i * 3 + 1], d.err![i * 3 + 2]));
    expect(mx).toBeGreaterThan(0);
    expect(Math.abs(mx - r.ranges.err_max)).toBeLessThan(r.ranges.err_max * 0.01);
  });
});

describe("V-0241-V3D-16 resolveFileUrl", () => {
  it("legacy URL 문자열은 지금과 같고, ?src= 가 있으면 &key=", () => {
    expect(resolveFileUrl("r1", "/esl-runs/r1/view3d/part.glb", "k1")).toBe(`${API_PREFIX}/esl-runs/r1/view3d/part.glb?key=k1`);
    expect(resolveFileUrl("r1", "part.glb", "k1")).toBe(`${API_PREFIX}/esl-runs/r1/view3d/part.glb?key=k1`);
    expect(resolveFileUrl("r1", "/esl-runs/r1/view3d/part.glb?src=bforce", "k 1")).toBe(`${API_PREFIX}/esl-runs/r1/view3d/part.glb?src=bforce&key=k%201`);
    expect(resolveFileUrl("r1", "/esl-runs/r1/view3d/values.bin")).toBe(`${API_PREFIX}/esl-runs/r1/view3d/values.bin`);
  });
});

describe("V-0241-V3D-17 useLoadView 출처", () => {
  const fail = () => Promise.reject(new ApiError(409, { code: "V3D_SOURCE_UNAVAILABLE", message: "출처 없음" }));
  it("/forces 폴백은 legacy 행만, src 별 요청 인자·rangeKey", async () => {
    expect([null, "full", "bforce", "fint", "jig"].map((k) => fallbackAllowed(k))).toEqual([true, true, false, false, false]);
    const v3 = vi.spyOn(api, "view3d").mockImplementation(fail);
    const forces = vi.spyOn(api, "forces").mockResolvedValue({ esl_run_id: "r", n_nodes: 1, rows: [] } as never);
    const a = renderHook(() => useLoadView("r1", true, "bforce"));
    await waitFor(() => expect(a.result.current?.error).toBeTruthy());
    expect(v3).toHaveBeenLastCalledWith("r1", "bforce");
    expect(forces).not.toHaveBeenCalled();
    expect(a.result.current?.rangeKey).toBe("r1:bforce");
    const b = renderHook(() => useLoadView("r1", true, "full"));
    await waitFor(() => expect(forces).toHaveBeenCalledWith("r1", 100));
    expect(v3).toHaveBeenLastCalledWith("r1", undefined);
    expect(b.result.current?.rangeKey).toBe("r1");
    const c = renderHook(() => useLoadView("r1", true));
    await waitFor(() => expect(c.result.current?.fallback).toBeTruthy());
    expect(c.result.current?.rangeKey).toBe("r1");
    vi.restoreAllMocks();
  });
  it("src 를 바꾸면 manifest·선택·단계가 초기화되고 새 src 로 다시 받는다", async () => {
    const m = mockView3d().manifest("r1") as View3dOut;
    const v3 = vi.spyOn(api, "view3d").mockResolvedValue(m);
    const { result, rerender } = renderHook(({ s }: { s: string }) => useLoadView("r1", true, s), { initialProps: { s: "full" } });
    await waitFor(() => expect(result.current?.manifest).toBeTruthy());
    result.current!.setSelection({ kind: "arrow", key: "3" });
    await waitFor(() => expect(result.current?.selection).toBeTruthy());
    rerender({ s: "bforce" });
    await waitFor(() => expect(v3).toHaveBeenLastCalledWith("r1", "bforce"));
    await waitFor(() => expect(result.current?.manifest).toBeTruthy());
    expect(result.current?.selection).toBeNull();
    expect(result.current?.stage).toBe(0);
    vi.restoreAllMocks();
  });
});

describe("V-0241-V3D-18·21 Case ③ 카드 — 탭·보기·하중 색·재현 줄", () => {
  it("탭 = 카드 머리 안, 보기·하중 색 = v3d-tools 안(새 블록 줄 없음), 기본 탭 = default, 불가 탭 사유", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const tabs = screen.getByTestId("v3d-src-tab");
    const card = tabs.closest("section.card")!;
    expect(card.getAttribute("aria-label")).toBe("3D 하중 보기");
    expect(tabs.closest("header.card-head")).toBeTruthy();
    const tools = card.querySelector(".v3d-tools")!;
    expect(tools.contains(screen.getByTestId("v3d-mode"))).toBe(true);
    expect(tools.contains(screen.getByTestId("v3d-load-field"))).toBe(true);
    // 카드 본문 직계 자식 = .v3d 하나(새 줄 없음), .v3d 안: tools · stage · foot
    const v3d = card.querySelector(".card-body > .v3d")!;
    expect(Array.from(v3d.children).map((c) => c.className.split(" ")[0])).toEqual(["v3d-tools", expect.any(String), "v3d-foot"]);
    expect(Array.from(tabs.querySelectorAll("button")).map((b) => b.textContent)).toEqual(["지그 ESL", "전 노드 ESL", "경계력 ESL", "내력 ESL"]);
    expect(tab("full").getAttribute("aria-selected")).toBe("true");
    expect(tab("jig").getAttribute("aria-disabled")).toBe("true");
    expect(tab("jig").title).toContain("지그 ESL 불가 — 강성 평가 스터디에서만");
    expect(tab("fint").title).toContain("내력 ESL 불가 — 이 ESL 결과에는 없습니다");
    expect(tab("bforce").getAttribute("aria-disabled")).toBe("false");
    // 비활성 탭 클릭 = 선택 안 바뀜
    fireEvent.click(tab("jig"));
    expect(tab("full").getAttribute("aria-selected")).toBe("true");
  });

  it("출처 탭 전환: ?src= 로 새 manifest, 보기·하중 색 초기화, 표·legacy 범위 키 유지", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const reqs: string[] = [];
    const f0 = globalThis.fetch;
    globalThis.fetch = ((i: RequestInfo | URL, init?: RequestInit) => (reqs.push(String(i)), f0(i, init))) as typeof fetch;
    fireEvent.click(tab("bforce"));
    await waitFor(() => expect(tab("bforce").getAttribute("aria-selected")).toBe("true"));
    await waitFor(() => expect(reqs.some((r) => /view3d\?src=bforce$/.test(r))).toBe(true));
    await waitFor(() => expect(reqs.some((r) => /part\.glb\?src=bforce&key=/.test(r))).toBe(true));
    await ready();
    expect(screen.getAllByRole("row").length).toBeGreaterThan(50);
    globalThis.fetch = f0;
  });

  it("하중 색 성분(면압·법선·크기): 범례 문구·범위 = manifest ranges", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    const man = mockView3d().manifest("x");
    const sel = screen.getByTestId("v3d-load-field") as HTMLSelectElement;
    expect(sel.value).toBe("pa");
    expect(screen.getByTestId("v3d-legend").textContent).toContain("면압 |Fn|/A (MPa)");
    expect(rangeMax()).toBeCloseTo(man.ranges.pa.p99!, 6);
    fireEvent.change(sel, { target: { value: "fn" } });
    await waitFor(() => expect(screen.getByTestId("v3d-legend").textContent).toContain("|Fn| 면외 하중 (N)"));
    expect(rangeMax()).toBeCloseTo(man.ranges.fn_abs.p99!, 6);
    fireEvent.change(sel, { target: { value: "fmag" } });
    await waitFor(() => expect(screen.getByTestId("v3d-legend").textContent).toContain("|F| 하중 크기 (N)"));
    expect(rangeMax()).toBeCloseTo(man.ranges.fmag_max, 6);
  });

  it("목표·응답 같은 범위, 오차 자기 범위, 재현 줄, 응답 불가 사유(검증 없음)", async () => {
    renderApp(url("c-demo", 4), "power", (s) => {
      s.v3dSources = { ...s.v3dSources, rows: s.v3dSources.rows.map((r) => (r.key === "full" ? { ...r, resp: false, resp_code: "V3D_RESP_NEED_VAL", resp_reason: "응답 변위 없음 — ⑤ 검증에서 전체 풀이를 하면 보입니다" } : r)) };
    });
    await ready();
    // full: 응답·오차 비활성 + 사유, 목표는 가능(values.bin u)
    expect(mode("fit").getAttribute("aria-disabled")).toBe("true");
    expect(mode("fit").title).toContain("⑤ 검증에서 전체 풀이");
    expect(mode("err").getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(mode("fit"));
    expect(mode("load").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(mode("tgt"));
    await waitFor(() => expect(screen.getByTestId("v3d-legend").textContent).toContain("목표 변위"));
    // bforce: 응답 가능
    fireEvent.click(tab("bforce"));
    await waitFor(() => expect(tab("bforce").getAttribute("aria-selected")).toBe("true"));
    await ready();
    expect(mode("load").getAttribute("aria-pressed")).toBe("true"); // 출처 전환 = 하중 보기로 초기화
    const rc = mockView3d().recon("x", "bforce");
    fireEvent.click(mode("fit"));
    await waitFor(() => expect(screen.getByTestId("v3d-recon-line").textContent).toContain("재현 MAC 0.934"));
    expect(screen.getByTestId("v3d-recon-line").textContent).toContain("강체 제거 Kabsch(S4)");
    await waitFor(() => expect(rangeMax()).toBeCloseTo(Math.max(rc.ranges.tgt_max, rc.ranges.fit_max), 6));
    expect(screen.getByTestId("v3d-legend").textContent).toContain("응답 변위 |u_fit| (mm)");
    fireEvent.click(mode("tgt"));
    await waitFor(() => expect(screen.getByTestId("v3d-legend").textContent).toContain("목표 변위"));
    expect(rangeMax()).toBeCloseTo(Math.max(rc.ranges.tgt_max, rc.ranges.fit_max), 6);
    fireEvent.click(mode("err"));
    await waitFor(() => expect(screen.getByTestId("v3d-legend").textContent).toContain("오차 |u_fit − u_tgt| (mm)"));
    expect(rangeMax()).toBeCloseTo(rc.ranges.err_max, 6);
    // 변형 형상: 오차 변위로 그림
    const sd = scene().calls["setDeform"] ?? [];
    expect(sd.length).toBeGreaterThan(0);
  });

  it("재현 실패(409)는 재현 줄에 사유 한 줄", async () => {
    renderApp(url("c-demo", 4), "power", (s) => (s.v3dReconFail = true));
    await ready();
    fireEvent.click(tab("bforce"));
    await waitFor(() => expect(tab("bforce").getAttribute("aria-selected")).toBe("true"));
    await ready();
    fireEvent.click(mode("fit"));
    await waitFor(() => expect(screen.getByTestId("v3d-recon-line").className).toContain("warn-text"));
  });

  it("옛 서버(sources 404) = 출처 탭·보기 세그먼트 없이 지금 화면 그대로", async () => {
    renderApp(url("c-demo", 4), "power", (s) => (s.view3dSourcesMode = "old"));
    await ready();
    expect(screen.queryByTestId("v3d-src-tab")).toBeNull();
    expect(screen.queryByTestId("v3d-mode")).toBeNull();
    expect(screen.queryByTestId("v3d-load-field")).toBeNull();
    expect(screen.getByTestId("v3d-legend").textContent).toContain("면압 |Fn|/A (MPa)");
  });

  it("탭 키보드: 화살표 = 포커스만 이동(비활성 탭 포함), 비활성 탭 사유 줄", async () => {
    renderApp(url("c-demo", 4));
    await ready();
    tab("full").focus();
    fireEvent.keyDown(tab("full"), { key: "ArrowLeft" });
    expect(document.activeElement).toBe(tab("jig"));
    await waitFor(() => expect(screen.getByTestId("v3d-src-tab-why").textContent).toContain("지그 ESL 불가"));
    fireEvent.keyDown(tab("jig"), { key: "End" });
    expect(document.activeElement).toBe(tab("fint"));
    expect(tab("full").getAttribute("aria-selected")).toBe("true");
  });
});
