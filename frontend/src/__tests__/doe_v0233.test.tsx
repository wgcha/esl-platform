// V-0233-8(esl_jig_view.md §7): 하중 정의 탭 [지그 ESL | 전 노드 ESL] — 기본 규칙·지그 미계산·탭별 섞임 0, 지그 탭 3D [설계 비교 | 지그 진단]·
// 진단 줄·세그먼트 3종·상대 부품별 tie 범례, 3D 다시 만들기 버튼 조건.
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { tabResult, tabState, warnTab } from "../pages/doe/doeTabs";
import { jigDiagText, regionArrows, regionField } from "../pages/doe/DoeStudy";
import { withJig, withMetric, withSolveMetric } from "../mock/doedata";
import type { DoeResultOut } from "../api/types";

afterEach(cleanup);
const openJig = (id: string, mod?: (r: DoeResultOut) => DoeResultOut) =>
  renderApp(`/p/p-body/doe/${id}`, "power", (s) => {
    s.doe.demoJig();
    if (mod) {
      const rec = s.doe.recs.find((r) => r.out.id === id)!;
      rec.result = mod(rec.result!);
    }
  });
const heads = (t: HTMLElement) => within(t).getAllByRole("columnheader").map((h) => h.textContent?.trim() ?? "");
const tabBtn = (k: "jig" | "full") => screen.getByTestId("doe-load-tab").querySelector(`[data-tab=${k}]`) as HTMLButtonElement;
const sensText = () => {
  const st = [...document.querySelectorAll(".doe-result-right .sub-title")].find((x) => x.textContent === "민감도");
  return st?.parentElement?.textContent ?? "";
};

describe("탭 순수 함수", () => {
  it("기본 탭 = metric_effective, 보기 없으면 주 결과 탭만, 경고 분류", () => {
    expect(warnTab("JIG_FIT_POOR")).toBe("jig");
    expect(warnTab("SM_IMBALANCE")).toBe("full");
    expect(warnTab("LT_DIAG_SKIPPED")).toBe("full");
    expect(warnTab("MESH_QUALITY_RANK")).toBe("full");
    expect(warnTab("SENSITIVITY_TOO_FEW")).toBe("common");
  });
  it("tabResult: 지그 탭 행에 전 노드 키 없음, 전 노드 탭 행에 지그 키 없음·jig null", () => {
    const base = { ranking: [], baseline: { id: "d000", score: 1, umax: 1, epsmax: 0.001 }, warnings: [], view3d: [], esl: [], excluded: [], n_ok: 0, n_skipped: {}, n_failed: {}, C_ref: 1 } as unknown as DoeResultOut;
    const r = withJig(withSolveMetric(withMetric({ ...base })), "ok");
    const ts = tabState(r);
    expect(ts.def).toBe("jig");
    expect(ts.ok).toEqual({ jig: true, full: true });
    const j = tabResult(r, "jig");
    const f = tabResult(r, "full");
    expect(j.rank?.metric_effective).toBe("jig");
    expect(f.rank?.metric_effective).toBe("solve");
    expect(f.jig).toBeNull();
    expect(f.jig_diag).toBeNull();
    const noViews = { ...r, rank_views: null, metric_effective: "solve" as const, rank: { ...r.rank!, metric_effective: "solve" as const } };
    const t2 = tabState(noViews);
    expect(t2.def).toBe("full");
    expect(t2.ok.jig).toBe(false);
    expect(t2.reason.jig).toMatch(/3D 다시 만들기/);
  });
});

describe("하중 정의 탭(doe-40 지그 ok)", () => {
  it("기본 = 지그 탭, 탭별 순위표·상태 띠·민감도·3D 가 섞이지 않음", async () => {
    openJig("doe-40");
    const t = await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    await waitFor(() => expect(heads(t)).toContain("지그 C"));
    expect(tabBtn("jig").getAttribute("aria-selected")).toBe("true");
    expect(heads(t)).not.toContain("재풀이 C");
    expect(screen.queryByTestId("lt-summary")).toBeNull();
    expect(screen.getByTestId("jig-line")).toBeTruthy();
    expect(screen.getByTestId("v3d-jig-mode")).toBeTruthy();
    expect(screen.queryByTestId("v3d-mode")).toBeNull();
    const sJig = sensText();
    const bodyJig = document.querySelector(".doe-result-2col")!.textContent ?? "";
    expect(bodyJig).not.toMatch(/재풀이 C 비|불평형/);
    fireEvent.click(tabBtn("full"));
    await waitFor(() => expect(heads(screen.getByRole("table", { name: "순위표" }))).toContain("재풀이 C"));
    const t2 = screen.getByRole("table", { name: "순위표" });
    expect(heads(t2)).not.toContain("지그 C");
    expect(screen.queryByTestId("jig-line")).toBeNull();
    expect(screen.queryByTestId("v3d-jig-mode")).toBeNull();
    expect(screen.queryByTestId("jig-diag")).toBeNull();
    expect(screen.getByTestId("lt-summary")).toBeTruthy();
    const tog = screen.queryByTestId("rank-aux-toggle");
    if (tog) fireEvent.click(tog);
    await waitFor(() => expect(heads(screen.getByRole("table", { name: "순위표" }))).not.toContain("지그 C 비"));
    expect(document.querySelector(".doe-result-2col")!.textContent).not.toMatch(/지그 C|umax\(지그\)/);
    expect(sensText()).not.toBe(sJig);                                   // 민감도 = 탭 score
    expect(screen.getByTestId("v3d-cond").textContent).toMatch(/^하중: 전 노드 ESL 재풀이 · 지지: 3-2-1/);
  }, 30000);

  it("지그 탭 3D: [설계 비교 | 지그 진단], 진단 줄(MAC·umax 오차·work_eff·tie_rel)·세그먼트 3종·계수·tie 범례", async () => {
    openJig("doe-40");
    const seg = await screen.findByTestId("v3d-jig-mode");
    expect([...seg.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["설계 비교", "지그 진단"]);
    fireEvent.click(seg.querySelector("[data-mode=diag]")!);
    const sel = (await screen.findByTestId("jig-diag-entry")) as HTMLSelectElement;
    fireEvent.change(sel, { target: { value: sel.options[0].value } });   // 기본 = 선택 안의 지그 최악 엔트리 → 첫 엔트리로
    await waitFor(() => expect(screen.getByTestId("jig-diag-line").textContent).toMatch(/MAC 0\.159/));
    const line = screen.getByTestId("jig-diag-line");
    expect(line.textContent).toMatch(/· MAC 0\.159\(모드 제외 0\.120\) · umax 오차 83\.9 % · work_eff 0\.41 · tie_rel 0\.034$/);
    expect(line.className).toContain("warn-text");                       // 목표 미달(MAC < 0.9)
    expect(line.title).toMatch(/하중 영역 3개\(접촉 2 · 패치 1\)/);
    expect(line.title).toMatch(/R1\(접촉 part 78 PANEL_REAR_COVER\)/);
    expect(line.title).toMatch(/영역 0\.82 · 체적력 0\.27 · 모드 0\.11/);
    expect(line.title).toMatch(/면외 71 % · 면내 29 %/);
    expect(line.title).toMatch(/part 78 PANEL_REAR_COVER 8노드·클러스터 4·지름 ≤ 13 mm·SECONDARY · tie_rel 0\.890/);
    expect(screen.getByTestId("jig-diag-coef").textContent).toMatch(/^체적력 \(0\.40, -12\.5, 1\.10\) N · 모드 a1 3\.20 a2 2\.10/);
    const view = screen.getByTestId("jig-diag-view");
    expect([...view.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["목표·맞춤", "오차", "영역"]);
    const legend = await screen.findByTestId("jig-tie-legend");
    expect(within(legend).getAllByTestId("jig-tie-group").map((x) => x.textContent)).toEqual([
      "▲ part 78 PANEL_REAR_COVER (8)", "▲ part 47 BRKT_STAND (4)", "▲ 상대 부품 모름 (2)"]);
    const entry = screen.getByTestId("jig-diag-entry") as HTMLSelectElement;
    expect(entry.options.length).toBeGreaterThan(1);
    fireEvent.change(entry, { target: { value: entry.options[1].value } });
    await waitFor(() => expect(screen.getByTestId("jig-diag-line").textContent).not.toMatch(/MAC 0\.159/));
    fireEvent.click(view.querySelector("[data-view=err]")!);
    await waitFor(() => expect(view.querySelector("[data-view=err]")!.getAttribute("aria-pressed")).toBe("true"));
    expect(screen.queryByTestId("v3d-regen")).toBeNull();                 // 진단·보기 다 있음 = 버튼 없음
  }, 30000);

  it("진단 자료 없는 지그 결과: 3D 다시 만들기 버튼(작성자) — 권한 없으면 비활성 + 이유", async () => {
    openJig("doe-40", (r) => ({ ...r, jig_diag: null }));
    const seg = await screen.findByTestId("v3d-jig-mode");
    const btn = await screen.findByTestId("v3d-regen");
    expect((btn as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(seg.querySelector("[data-mode=diag]")!);
    await screen.findByText(/지그 진단 3D 가 없습니다 — \[3D 다시 만들기\]로 만드세요/);
    cleanup();
    openJig("doe-40", (r) => ({ ...r, jig_diag: null, view3d_regen: { available: true, allowed: false, reason: "관리자 또는 이 스터디 작성자만 3D 를 다시 만들 수 있습니다" } }));
    const b2 = (await screen.findByTestId("v3d-regen")) as HTMLButtonElement;
    expect(b2.disabled).toBe(true);
    expect(b2.closest("[title]")!.getAttribute("title")).toMatch(/작성자만/);
  }, 30000);
});

describe("지그 미계산·fallback", () => {
  it("doe-42 fallback: 기본 = 전 노드 탭, 지그 탭 비활성 + 사유, 지그 칩(fallback) 유지", async () => {
    openJig("doe-42");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    expect(tabBtn("full").getAttribute("aria-selected")).toBe("true");
    expect(tabBtn("jig").getAttribute("aria-disabled")).toBe("true");
    expect(tabBtn("jig").title).toMatch(/^지그 순위 불가 — /);
    expect(screen.getByTestId("jig-line").getAttribute("data-status")).toBe("fallback");
  }, 30000);
});

describe("진단 순수 도우미", () => {
  it("regionField·regionArrows: 영역 밖 NaN, 접촉 > 패치, 화살표 수 = 합력 있는 영역", () => {
    const v = regionField(10, [{ id: 0, kind: "contact", n_nodes: 2, area_mm2: 1, center: [0, 0, 0], vertices: [1, 2] }, { id: 1, kind: "patch", n_nodes: 1, area_mm2: 1, center: [1, 0, 0], vertices: [5] }]);
    expect(Number.isNaN(v[0])).toBe(true);
    expect(v[1]).toBeGreaterThan(v[5]);
    const d = { n_jig: 4, n_contact: 1, n_patch: 1, regions: [{ id: 0, kind: "contact" as const, n_nodes: 2, area_mm2: 1, center: [0, 0, 0] }, { id: 1, kind: "patch" as const, n_nodes: 1, area_mm2: 1, center: [1, 0, 0] }], entries: [] };
    const e = { entry_id: "e", label: "E", kk: 0, dirs: {}, mac: 0.5, umax_err: 0.1, work_eff: 0.5, tie_rel: 0.1, rot_deg: 1, umax_tgt: 1, umax_fit: 1, err_max: 0.1, tgt_out_frac: 1, contrib: {}, F_region_sum: [0, 3, 0], modes: [],
      forces: [{ region: 0, kind: "contact", F: [0, 2, 0], F_mag: 2, F_n: 2, F_t1: 0, F_t2: 0, active: true }, { region: 1, kind: "patch", F: [0, 1, 0], F_mag: 1, F_n: 1, F_t1: 0, F_t2: 0, active: true }] };
    const a = regionArrows(e, d, 100);
    expect(a.map((x) => x.key)).toEqual(["R1", "R2"]);
    expect(a[0].length).toBeGreaterThan(a[1].length);                    // 길이 ∝ |F|
    expect(jigDiagText(e, d).coef).toBe("체적력 없음");
  });
});

describe("D-0.23.3-n 보완(옛 결과·다시 만들기 위치·탭 키보드)", () => {
  it("F1 metric_effective 없는 옛 결과: 전 노드 탭 가능(사유에 다시 만들기 안내 없음)", () => {
    const base = { ranking: [], baseline: { id: "d000", score: 1, umax: 1, epsmax: 0.001 }, warnings: [], view3d: [], esl: [], excluded: [], n_ok: 0, n_skipped: {}, n_failed: {}, C_ref: 1 } as unknown as DoeResultOut;
    const ts = tabState(base);
    expect(ts.ok.full).toBe(true);
    expect(ts.def).toBe("full");
    expect(ts.ok.jig).toBe(false);
    expect(ts.reason.jig ?? "").not.toMatch(/3D 다시 만들기/);
    expect(ts.reason.full).toBeNull();
  });

  it("F2 지그 계산됨 + solve + 사이드카 없음: 전 노드 탭에서도 3D 다시 만들기 버튼", async () => {
    openJig("doe-40", (r) => ({ ...r, rank_views: null, metric_effective: "solve", rank: { ...r.rank!, metric_effective: "solve" } }));
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    expect(tabBtn("full").getAttribute("aria-selected")).toBe("true");
    expect(tabBtn("jig").getAttribute("aria-disabled")).toBe("true");
    const btn = (await screen.findByTestId("v3d-regen")) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  }, 30000);

  it("탭 키보드: tablist/tab·aria-selected·aria-controls, 좌우 화살표 포커스 이동, 비활성 탭 포커스 시 사유 표시", async () => {
    openJig("doe-42");
    await screen.findByRole("table", { name: "순위표" }, { timeout: 8000 });
    const list = screen.getByRole("tablist", { name: "하중 정의" });
    const tabs = within(list).getAllByRole("tab");
    expect(tabs.map((t) => t.getAttribute("data-tab"))).toEqual(["jig", "full"]);
    for (const t of tabs) {
      expect(t.getAttribute("aria-controls")).toBe("doe-load-panel");
      expect(document.getElementById("doe-load-panel")!.getAttribute("role")).toBe("tabpanel");
    }
    expect(tabBtn("full").getAttribute("aria-selected")).toBe("true");
    expect(tabBtn("full").tabIndex).toBe(0);
    tabBtn("full").focus();
    fireEvent.keyDown(tabBtn("full"), { key: "ArrowLeft" });
    expect(document.activeElement).toBe(tabBtn("jig"));                  // 비활성 탭도 포커스 가능(사유 읽기)
    const why = await screen.findByTestId("doe-load-tab-why");
    expect(why.textContent).toMatch(/^지그 순위 불가 — /);
    expect(tabBtn("jig").getAttribute("aria-describedby")).toBeTruthy();
    expect(document.getElementById(tabBtn("jig").getAttribute("aria-describedby")!)!.textContent).toMatch(/^지그 순위 불가/);
    fireEvent.click(tabBtn("jig"));                                      // 비활성 클릭 = 무시
    expect(tabBtn("full").getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tabBtn("jig"), { key: "ArrowRight" });
    expect(document.activeElement).toBe(tabBtn("full"));
    expect(screen.queryByTestId("doe-load-tab-why")).toBeNull();
  }, 30000);
});
