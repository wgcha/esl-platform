// V-0241-V3D-19·20(프런트) + 현장 피드백: 스터디 자료 만들기 버튼 ≤ 1 · 하중 색 토글 · 재현 진단 · 불가 사유 가시 줄.
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
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
