// V-0240-F-d(esl_fint.md §8): 하중 정의 탭 [내력 ESL] — 출처 표 행 + 노드 힘 열(nodal), 탭 독립(다른 출처 값 0), 비활성 사유(FINT 없음),
// [경계력 ESL 계산]·[내력 ESL 계산] 버튼, 순위표 umax(평가 영역)·지표 정의, Case ESL 화면 내력·소성 줄.
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { LOAD_SOURCES, NODAL_FI, nodalUnavailable, tabResult, tabState, warnTab } from "../pages/doe/doeTabs";
import { nodalChipText } from "../pages/doe/DoeStudy";
import { withBforce, withFint, withJig, withMetric, withSolveMetric } from "../mock/doedata";
import { fintLineText, plasticLineText } from "../stages/Stage4";
import { evalRegionText } from "../api/doe";
import type { DoeResultOut } from "../api/types";

afterEach(cleanup);
const open = (id: string) => renderApp(`/p/p-body/doe/${id}`, "power", (s) => s.doe.demoBforce());
const tabBtn = (k: string) => screen.getByTestId("doe-load-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
const heads = (t: HTMLElement) => within(t).getAllByRole("columnheader").map((h) => h.textContent?.trim() ?? "");
const base = { ranking: [], baseline: { id: "d000", score: 1, umax: 1, epsmax: 0.001 }, warnings: [], view3d: [], esl: [{ entry_id: "e1", label: "E1" }, { entry_id: "e2", label: "E2" }], excluded: [], n_ok: 0, n_skipped: {}, n_failed: {}, C_ref: 1 } as unknown as DoeResultOut;

describe("내력 탭 순수 함수", () => {
  it("출처 표 4행·노드 힘 열, 탭 상태·투영 섞임 0", () => {
    expect(LOAD_SOURCES.map((s) => s.key)).toEqual(["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]);
    expect(LOAD_SOURCES.filter((s) => s.nodal).map((s) => s.nodal!.block)).toEqual(["bforce", "fint"]);
    const r = withFint(withBforce(withJig(withSolveMetric(withMetric({ ...base })), "ok"), "ok"), "ok");
    const ts = tabState(r);
    expect(ts.ok).toEqual({ jig: true, jig_disp: false, jig_spring: false, full: true, bforce: true, fint: true });
    expect(ts.def).toBe("jig");
    expect(warnTab("FINT_UNBALANCED")).toBe("fint");
    expect(warnTab("BF_RECON_POOR")).toBe("bforce");
    const f = tabResult(r, "fint");
    expect(f.metric_effective).toBe("fi");
    expect(f.bforce).toBeNull();
    expect(f.view3d_bf ?? null).toBeNull();
    expect(f.jig).toBeNull();
    expect(JSON.stringify(f.ranking)).not.toContain("C_bf");
    const b = tabResult(r, "bforce");
    expect(b.fint).toBeNull();
    expect(b.view3d_fi ?? null).toBeNull();
    expect(tabResult(r, "jig").fint).toBeNull();
    expect(tabResult(r, "full").fint).toBeNull();
  });
  it("FINT 없음 사유·칩 문구(잔차·공유 노드·소성)·평가 영역 문구", () => {
    const none = withFint({ ...base }, "none");
    expect(tabState(none).ok.fint).toBe(false);
    expect(nodalUnavailable(none, NODAL_FI, "내력 ESL")).toContain("/H3D/NODA/FINT");
    expect(nodalUnavailable({ ...base }, NODAL_FI, "내력 ESL")).toContain("다른 메시 비교");
    expect(nodalUnavailable({ ...base, fint_add: { available: true, allowed: true, reason: null } }, NODAL_FI, "내력 ESL")).toContain("내력 ESL 미계산");
    const ok = withFint({ ...base }, "ok");
    const t = nodalChipText(ok.fint!, "내력 ESL", true);
    expect(t.line).toMatch(/^내력 ESL · 등급 fint/);
    expect(t.line).toContain("공유 노드 12");
    expect(t.line).toContain("잔차 3.1e-6");
    expect(t.line).toContain("소성 4.3%");
    expect(t.warn).toBe(true);                                                     // 공유 노드 > 0
    expect(t.title).toContain("내력 잔차");
    const clean = { ...ok.fint!, limits: [], limit_text: [], entries: ok.fint!.entries!.map((e) => ({ ...e, n_shared: 0 })) };
    expect(nodalChipText(clean, "내력 ESL", true).warn).toBe(false);
    expect(nodalChipText({ ...clean, entries: clean.entries!.map((e) => ({ ...e, unbalanced: true })) }, "내력 ESL", true).warn).toBe(true);
    expect(evalRegionText(null)).toBe("대상 파트 전체");
    expect(evalRegionText({ mode: "exclude_free_edges", free_edge_mm: 10, n_nodes: 8, n_total: 10 })).toBe("자유 경계 10 mm 이내 제외(노드 8/10)");
    expect(evalRegionText({ mode: "box", boxes: [{}, {}] })).toBe("상자 2개 안");
  });
  it("Case ESL 화면 내력·소성 줄", () => {
    const l = fintLineText({ grade: "fint", sum_abs: 1.3e5, sum_abs_ratio_full: 0.057, res_force_rel: 2.1e-6, res_moment_rel: 4.2e-4, unbalanced: false, balance_applied: "none", shared_status: "ok", n_shared: 12, n_rot: 4, recon: "ok", mac: 0.985, umax_err: -0.021, reaction_rel: 2.8e-3, limits: [], limit_text: [], sign: -1 });
    expect(l.text).toContain("F = −FINT");
    expect(l.text).toContain("잔차 힘 2.1e-6");
    expect(l.text).toContain("공유 노드 12(회전 연결 4)");
    expect(l.text).toContain("MAC 0.985");
    expect(l.warn).toBe(true);
    expect(fintLineText({ grade: "none", code: "FINT_NO_DATA", reason: "내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가" }).text).toContain("/H3D/NODA/FINT");
    const u = fintLineText({ grade: "fint", unbalanced: true, shared_status: "ok", n_shared: 0, recon: "ok", mac: 0.99 });
    expect(u.text).toContain("불평형");
    expect(u.warn).toBe(true);
    expect(plasticLineText({ status: "ok", eps_min: 0.002, frac: 0.031, max: 0.0421, n: 214, n_total: 9874 })).toContain("면적 3.1%");
    expect(plasticLineText({ status: "none" })).toContain("없음");
  });
});

describe("내력 탭 화면", () => {
  it("doe-50: 내력 탭 = 내력 C·umax(평가 영역)·칩(경계력 칩 없음), 경계력 탭에 내력 값 없음", async () => {
    open("doe-50");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    expect(tabBtn("fint").getAttribute("aria-disabled")).toBe("false");
    fireEvent.click(tabBtn("fint"));
    await waitFor(() => expect(tabBtn("fint").getAttribute("aria-selected")).toBe("true"));
    const chip = await screen.findByTestId("nodal-chip-fint");
    expect(chip.textContent).toContain("공유 노드 12");
    expect(screen.queryByTestId("bf-chip")).toBeNull();
    const t = screen.getByRole("table", { name: "순위표" });
    const h = heads(t).join(" ");
    expect(h).toContain("내력 C");
    expect(h).toContain("umax(평가 영역)");
    expect(h).not.toContain("경계력 C");
    expect(screen.getByTestId("metric-eval").textContent).toContain("자유 경계 10 mm 이내 제외");
    await waitFor(() => expect(screen.getByTestId("v3d-cond").textContent).toContain("내력 ESL"));
    expect(screen.queryByTestId("v3d-fi-add")).toBeNull();                        // 보기가 있으면 계산 버튼 없음
    fireEvent.click(tabBtn("bforce"));
    await waitFor(() => expect(tabBtn("bforce").getAttribute("aria-selected")).toBe("true"));
    await screen.findByTestId("bf-chip");
    expect(screen.queryByTestId("nodal-chip-fint")).toBeNull();
    expect(heads(screen.getByRole("table", { name: "순위표" })).join(" ")).not.toContain("내력 C");
  }, 30000);
  it("doe-51: 내력·경계력 탭 = 선택 가능한 빈 탭(+) + 사유, 탭마다 본문 버튼 1개(v0.24.1 §6.3)", async () => {
    open("doe-51");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    expect(tabBtn("fint").getAttribute("aria-disabled")).toBe("false");
    expect(tabBtn("fint").getAttribute("title")).toContain("/H3D/NODA/FINT");
    expect(screen.queryByTestId("v3d-bf-add")).toBeNull();
    expect(screen.queryByTestId("v3d-fi-add")).toBeNull();
    fireEvent.click(tabBtn("bforce"));
    expect(await screen.findByTestId("v3d-bf-add")).toBeTruthy();
    expect(screen.queryByTestId("v3d-fi-add")).toBeNull();
    fireEvent.click(tabBtn("fint"));
    const fi = (await screen.findByTestId("v3d-fi-add")) as HTMLButtonElement;
    expect(fi.textContent).toBe("내력 ESL 계산");
    expect(fi.disabled).toBe(false);
    expect(screen.queryByTestId("v3d-bf-add")).toBeNull();
  }, 30000);
});
