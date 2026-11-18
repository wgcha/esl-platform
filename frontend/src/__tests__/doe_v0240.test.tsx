// V-0240-h(esl_bforce.md §8): 하중 정의 탭 [경계력 ESL] — 출처 표 행 1개(탭·순위표·칩·3D 쌍), 데이터 등급 사유·[경계력 ESL 계산] 버튼,
// 탭 독립(다른 출처 값 0), Case ESL 화면 경계력 요약 한 줄.
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { bfUnavailable, tabResult, tabState, warnTab } from "../pages/doe/doeTabs";
import { bfChipText, v3dPairCondText } from "../pages/doe/DoeStudy";
import { withBforce, withJig, withMetric, withSolveMetric } from "../mock/doedata";
import { bforceLineText } from "../stages/Stage4";
import type { DoeResultOut } from "../api/types";

afterEach(cleanup);
const open = (id: string) => renderApp(`/p/p-body/doe/${id}`, "power", (s) => s.doe.demoBforce());
const tabBtn = (k: string) => screen.getByTestId("doe-load-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
const heads = (t: HTMLElement) => within(t).getAllByRole("columnheader").map((h) => h.textContent?.trim() ?? "");
const base = { ranking: [], baseline: { id: "d000", score: 1, umax: 1, epsmax: 0.001 }, warnings: [], view3d: [], esl: [{ entry_id: "e1", label: "E1" }], excluded: [], n_ok: 0, n_skipped: {}, n_failed: {}, C_ref: 1 } as unknown as DoeResultOut;

describe("경계력 탭 순수 함수", () => {
  it("탭 상태·경고 분류·투영 섞임 0", () => {
    const r = withBforce(withJig(withSolveMetric(withMetric({ ...base })), "ok"), "ok");
    const ts = tabState(r);
    expect(ts.keys).toEqual(["jig", "full", "bforce"]);
    expect(ts.ok).toEqual({ jig: true, full: true, bforce: true });
    expect(ts.def).toBe("jig");                                                   // 경계력은 기본 탭이 아님(primaryFor 없음)
    expect(warnTab("BF_RECON_POOR")).toBe("bforce");
    const b = tabResult(r, "bforce");
    expect(b.metric_effective).toBe("bf");
    expect(b.jig).toBeNull();
    expect(b.jig_diag).toBeNull();
    const j = tabResult(r, "jig");
    expect(j.bforce).toBeNull();
    expect(j.view3d_bf ?? null).toBeNull();
  });
  it("자료 없음 사유·칩 문구·조건 줄", () => {
    const none = withBforce({ ...base }, "none");
    expect(tabState(none).ok.bforce).toBe(false);
    expect(bfUnavailable(none)).toContain("경계력 ESL 불가");
    expect(bfUnavailable(none)).toContain("BF_NOT_FOUND");
    expect(bfUnavailable({ ...base })).toContain("다른 메시 비교");
    const ok = withBforce({ ...base }, "ok");
    const t = bfChipText(ok.bforce!);
    expect(t.line).toContain("등급 contact");
    expect(t.line).toContain("tie 체결력 미포함");
    expect(t.warn).toBe(true);
    expect(t.title).toContain("ā");
    // 재현 MAC 경고 기준은 응답의 recon_mac_min(하드코딩 0.9 아님)
    const mk = (min: number | null, mac: number) => ({ ...ok.bforce!, limits: [], limit_text: [], recon_mac_min: min, entries: [{ ...ok.bforce!.entries![0], recon_mac: mac }] });
    expect(bfChipText(mk(0.95, 0.93)).warn).toBe(true);
    expect(bfChipText(mk(0.8, 0.85)).warn).toBe(false);
    expect(bfChipText(mk(null, 0.5)).warn).toBe(false);
    expect(bfChipText({ ...mk(0.9, 0.99), entries: [{ ...ok.bforce!.entries![0], recon_mac: 0.99, sign_suspect: true }] }).warn).toBe(true);
    expect(v3dPairCondText("경계력 ESL", "contact", ["E1", "E1"])).toBe("하중: 경계력 ESL(등급 contact) · 지지: 3-2-1 · 엔트리: E1");
  });
  it("Case ESL 화면 요약 한 줄", () => {
    const c = bforceLineText({ grade: "contact", mass_source: "deck", sum_abs: 1.5e5, sum_abs_ratio_full: 0.0031, abar_g: 41.2, corr_rel: 0.23, recon: "ok", mac: 0.962, umax_err: -0.041, reaction_rel: 2e-12, limits: ["BF_TIE_MISSING"], limit_text: ["tie 체결력 미포함 — 조립 부품 하중 누락"] });
    expect(c.text).toContain("등급 contact");
    expect(c.text).toContain("×0.0031");
    expect(c.text).toContain("ā = 41.2 g");
    expect(c.text).toContain("MAC 0.962");
    expect(c.text).toContain("tie 체결력 미포함");
    expect(c.warn).toBe(true);
    expect(bforceLineText({ grade: "none", code: "BF_NO_DATA" }).text).toContain("자료 없음");
    // 한계 문구는 백엔드 limit_text 그대로(화면 표 없음), 부호 의심 표시
    const w = bforceLineText({ grade: "contact", recon: "ok", mac: 0.97, limits: ["BF_TIE_MISSING"], limit_text: ["백엔드 문구"], sign_suspect: true });
    expect(w.text).toContain("백엔드 문구");
    expect(w.text).toContain("CONT 부호 의심");
    expect(w.warn).toBe(true);
  });
});

describe("경계력 탭 화면", () => {
  it("doe-50: 탭 3개, 경계력 탭 = 순위·칩·3D 쌍(조건 줄), 지그 값 없음", async () => {
    open("doe-50");
    const t = await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const seg = await screen.findByTestId("doe-load-tab");
    expect([...seg.querySelectorAll("button")].map((b) => b.getAttribute("data-tab"))).toEqual(["jig", "full", "bforce"]);
    expect(tabBtn("bforce").getAttribute("aria-disabled")).toBe("false");
    fireEvent.click(tabBtn("bforce"));
    await waitFor(() => expect(tabBtn("bforce").getAttribute("aria-selected")).toBe("true"));
    const chip = await screen.findByTestId("bf-chip");
    expect(chip.textContent).toContain("등급 contact");
    expect(screen.queryByTestId("jig-line")).toBeNull();
    const t2 = screen.getByRole("table", { name: "순위표" });                     // 탭마다 표를 새로 그림(key)
    expect(t2).not.toBe(t);
    expect(heads(t2).join(" ")).toContain("경계력 C");
    expect(heads(t2).join(" ")).not.toContain("지그 C");
    expect(screen.queryByTestId("v3d-jig-mode")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("v3d-cond").textContent).toContain("경계력 ESL"));
    expect(screen.queryByTestId("v3d-bf-add")).toBeNull();                        // 보기가 있으면 계산 버튼 없음
  }, 30000);
  it("doe-51: 경계력 탭 비활성 + 사유, 활성 탭 3D 머리에 [경계력 ESL 계산]", async () => {
    open("doe-51");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const b = tabBtn("bforce");
    expect(b.getAttribute("aria-disabled")).toBe("true");
    expect(b.getAttribute("title")).toContain("경계력 ESL 불가");
    const add = await screen.findByTestId("v3d-bf-add");
    expect((add as HTMLButtonElement).disabled).toBe(false);
  }, 30000);
});
