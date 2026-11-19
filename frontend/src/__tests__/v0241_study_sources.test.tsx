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
import { mockView3d } from "../mock/view3dmock";
import { LOAD_SOURCES, nodalNote, sourceAddOf, tabState } from "../pages/doe/doeTabs";
import { withBforce, withFint, withJig, withMetric, withSolveMetric } from "../mock/doedata";
import type { DoeResultOut } from "../api/types";

afterEach(cleanup);
const open = (id: string) => renderApp(`/p/p-body/doe/${id}`, "power", (s) => s.doe.demoBforce());
const tabBtn = (k: string) => screen.getByTestId("doe-load-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
const ADD_IDS = ["v3d-regen", "v3d-bf-add", "v3d-fi-add"];
const addCount = () => ADD_IDS.reduce((n, id) => n + screen.queryAllByTestId(id).length, 0);
const base = { ranking: [], baseline: { id: "d000", score: 1, umax: 1, epsmax: 0.001 }, warnings: [], view3d: [], esl: [{ entry_id: "e1", label: "E1" }], excluded: [], n_ok: 0, n_skipped: {}, n_failed: {}, C_ref: 1 } as unknown as DoeResultOut;

describe("V-0241-V3D-19 tabState.add · 자료 만들기 버튼", () => {
  it("add = 보기 없음 ∧ source_add.available ∧ allowed (source_add 우선, 옛 거울 폴백)", () => {
    const r0 = withBforce(withJig(withSolveMetric(withMetric({ ...base })), "ok"), "none");
    const bf = LOAD_SOURCES.find((s) => s.key === "bforce")!;
    expect(sourceAddOf(r0, bf)?.available).toBe(true);
    expect(tabState(r0).add.bforce).toBe(true);
    expect(tabState(r0).ok.bforce).toBe(false);
    const r1 = { ...r0, source_add: { bforce: { available: true, allowed: false, reason: "작성자만" } } };
    expect(tabState(r1).add.bforce).toBe(false);
    expect(tabState(r1).reason.bforce).toContain("작성자만");
    const r2 = { ...r0, source_add: { bforce: { available: false, allowed: true } } };
    expect(tabState(r2).add.bforce).toBe(false);
    // 보기가 있는 탭·full(add 열 null) = add 아님
    const ok = withBforce(withJig(withSolveMetric(withMetric({ ...base })), "ok"), "ok");
    expect(tabState(ok).add).toEqual({ jig: false, full: false, bforce: false, fint: expect.any(Boolean) });
  });
  it("화면: 탭 4개 × 상태 조합에서 자료 만들기 버튼 ≤ 1, testid 유지", async () => {
    open("doe-51");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    for (const k of ["jig", "full", "bforce", "fint"]) {
      if (tabBtn(k).getAttribute("aria-disabled") === "true") continue;
      fireEvent.click(tabBtn(k));
      await waitFor(() => expect(tabBtn(k).getAttribute("aria-selected")).toBe("true"));
      expect(addCount()).toBeLessThanOrEqual(1);
    }
    fireEvent.click(tabBtn("bforce"));
    expect(await screen.findByTestId("v3d-bf-add")).toBeTruthy();
    expect(addCount()).toBe(1);
  }, 30000);
});

describe("현장 피드백: 계산했는데 prep 결과가 불가 — 사유를 마우스 없이 한 줄로", () => {
  it("nodalNote: 블록 있음 ∧ status≠ok 일 때만, nodalUnavailable 문구 + 다음 행동", () => {
    const none = withBforce({ ...base }, "none");
    const bf = LOAD_SOURCES.find((s) => s.key === "bforce")!;
    const t = nodalNote(none, bf)!;
    expect(t).toContain("경계력 ESL 불가");
    expect(t).toContain("BF_NOT_FOUND");
    expect(t).toContain("h3d 추출부터 ESL 을 다시 실행한 뒤 [경계력 ESL 계산] 다시 누르세요");
    expect(nodalNote({ ...base }, bf)).toBeNull();                       // 블록 없음(미계산) = 줄 없음(탭 사유·버튼으로 충분)
    expect(nodalNote(withBforce({ ...base }, "ok"), bf)).toBeNull();     // ok
    expect(nodalNote(none, LOAD_SOURCES.find((s) => s.key === "full")!)).toBeNull();
    expect(nodalNote(withFint({ ...base }, "none" as never), LOAD_SOURCES.find((s) => s.key === "fint")!) ?? "").toMatch(/^$|내력 ESL 불가/);
  });
  it("doe-51 화면: 활성 탭이 달라도 불가 사유 줄이 보이고, 그 빈 탭 본문에는 한 번만(+ 버튼 유지)", async () => {
    open("doe-51");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const notes = await screen.findAllByTestId("nodal-unavail-note");
    const bfNote = notes.find((n) => n.getAttribute("data-src") === "bforce")!;
    expect(bfNote.textContent).toContain("BF_NOT_FOUND");
    expect(bfNote.textContent).toContain("[경계력 ESL 계산] 다시 누르세요");
    expect(addCount()).toBe(0);
    fireEvent.click(tabBtn("bforce"));
    await screen.findByTestId("v3d-bf-add");                                  // 버튼은 계속 보임 — 다시 누를 수 있음
    expect(screen.getByTestId("doe-source-add-why").textContent).toContain("BF_NOT_FOUND");
    expect(screen.queryAllByTestId("nodal-unavail-note").some((n) => n.getAttribute("data-src") === "bforce")).toBe(false);
  }, 30000);
});

describe("V-0241-V3D-20 소스 규율", () => {
  it("DoeStudy 의 재현 진단·자료 만들기 선택은 출처 표 열(recon·add)로만 — 출처 이름 문자열 비교 없음", () => {
    const src = Object.values(import.meta.glob("../pages/doe/DoeStudy.tsx", { query: "?raw", import: "default", eager: true }))[0] as string;
    const code = src.split("\n").filter((l) => !l.trim().startsWith("//") && !l.trim().startsWith("*") && !l.trim().startsWith("/**"));
    const bad = code.filter((l) => /(?:key|src|curTab|tab|source)\s*[!=]==?\s*"(?:jig|full|bforce|fint)"/.test(l) || /===\s*"(?:bforce|fint)"/.test(l));
    expect(bad).toEqual([]);
    // 이전 시험들이 쓰는 열 값
    expect(LOAD_SOURCES.map((s) => s.recon?.kind ?? null)).toEqual(["jigdiag", null, "sidecar", "sidecar"]);
    expect(LOAD_SOURCES.map((s) => s.add?.testid ?? null)).toEqual(["v3d-regen", null, "v3d-bf-add", "v3d-fi-add"]);
  });
});

const diagOf = async (doe: string, tab: string, segId = "v3d-recon-mode") => {
  open(doe);
  await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
  fireEvent.click(tabBtn(tab));
  await waitFor(() => expect(tabBtn(tab).getAttribute("aria-selected")).toBe("true"));
  const seg = await screen.findByTestId(segId);
  fireEvent.click(seg.querySelector("[data-mode=diag]")!);
};
const lastLegend = () => screen.getAllByTestId("v3d-legend");
const rmax = (el: HTMLElement) => Number(el.getAttribute("data-range-max"));

describe("V-0241-V3D-20 하중 색 · 재현 진단(스터디)", () => {
  it("v3d-color [응답 변위 | 하중]: 두 카드 같은 하중 범위(p99), 응답 변위로 되돌리면 변위 범례", async () => {
    open("doe-50");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const seg = await screen.findByTestId("v3d-color");
    expect(seg.querySelector("[data-color=disp]")!.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(lastLegend().length).toBe(2), { timeout: 8000 });
    expect(lastLegend()[0].textContent).toContain("변위");
    fireEvent.click(seg.querySelector("[data-color=load]")!);
    await waitFor(() => expect(lastLegend()[0].textContent).toContain("면압 |Fn|/A (MPa)"));
    const p99 = mockView3d().manifest("x").ranges.pa.p99!;
    const ls = lastLegend();
    expect(ls.length).toBe(2);
    expect(rmax(ls[0])).toBeCloseTo(p99, 6);
    expect(rmax(ls[1])).toBeCloseTo(p99, 6);
    fireEvent.click(seg.querySelector("[data-color=disp]")!);
    await waitFor(() => expect(lastLegend()[0].textContent).toContain("변위"));
  }, 30000);

  it("경계력 탭 [설계 비교 | 재현 진단]: sidecar 행 → ReconDiag, 목표·재현 / 오차, 재현 한 줄", async () => {
    await diagOf("doe-50", "bforce");
    const line = await screen.findByTestId("recon-diag-line", {}, { timeout: 8000 });
    await waitFor(() => expect(line.textContent).toContain("재현 MAC 0.934"), { timeout: 8000 });
    expect(line.textContent).toContain("강체 제거 Kabsch(S4)");
    expect(screen.getByTestId("recon-diag-entry")).toBeTruthy();
    await waitFor(() => expect(lastLegend().length).toBe(2), { timeout: 8000 });
    const rc = mockView3d().recon("x", "bforce");
    expect(lastLegend()[0].textContent).toContain("목표 변위 |u_tgt| (mm)");
    expect(lastLegend()[1].textContent).toContain("재현 변위 |u_fit| (mm)");
    expect(rmax(lastLegend()[0])).toBeCloseTo(Math.max(rc.ranges.tgt_max, rc.ranges.fit_max), 6);
    expect(rmax(lastLegend()[1])).toBeCloseTo(rmax(lastLegend()[0]), 6);
    fireEvent.click(screen.getByTestId("recon-diag-view").querySelector("[data-view=err]")!);
    await waitFor(() => expect(lastLegend()[0].textContent).toContain("오차 |u_fit − u_tgt| (mm)"));
    expect(rmax(lastLegend()[0])).toBeCloseTo(rc.ranges.err_max, 6);
    expect(rmax(lastLegend()[1])).toBeCloseTo(rc.ranges.fit_max, 6);
    expect(screen.queryByTestId("v3d-color")).toBeNull();             // 진단 보기에는 하중 색 토글 없음
  }, 30000);

  it("재현 사이드카 없는 경계력 탭(옛 결과): 진단 빈 칸 = V3D_RECON_NONE 문구 + 자료 만들기 버튼 1개", async () => {
    renderApp("/p/p-body/doe/doe-50", "power", (s) => {
      s.doe.demoBforce();
      const rec = s.doe.recs.find((r) => r.out.id === "doe-50")!;
      rec.result = { ...rec.result!, view3d_bf_recon: null, source_add: { bforce: { available: true, allowed: true, reason: null } } };
    });
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    fireEvent.click(tabBtn("bforce"));
    await waitFor(() => expect(tabBtn("bforce").getAttribute("aria-selected")).toBe("true"));
    fireEvent.click((await screen.findByTestId("v3d-recon-mode")).querySelector("[data-mode=diag]")!);
    await screen.findByText(/재현 진단 없음 — \[경계력 ESL 계산\]로 다시 계산하면 생깁니다/);
    expect(screen.getAllByTestId("v3d-bf-add").length).toBe(1);
    expect(addCount()).toBe(1);
  }, 30000);

  it("jig 탭 [설계 비교 | 지그 진단] 은 그대로(testid v3d-jig-mode), 재현 진단 세그먼트와 따로", async () => {
    open("doe-40");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    expect(await screen.findByTestId("v3d-jig-mode")).toBeTruthy();
    expect(screen.queryByTestId("v3d-recon-mode")).toBeNull();
    expect(screen.getByTestId("v3d-color")).toBeTruthy();
  }, 30000);
});
