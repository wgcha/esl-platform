// V-JIG-9(esl_jig_rank.md §7·§8): 지그 순위 화면 — 주 열 "지그 C"·정의 문구·기준 재현 한 줄·보조 토글, poor 경고색, fallback 문구,
// solve 결과 + score_jig → 보조 "지그 C 비", legacy 결과 DOM 불변. 화면 크기는 work/screens/jig_rank.png.
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { JIG_CODE_TEXT, isJigResult, warnText } from "../api/doe";
import { withJig, withMetric, withSolveMetric } from "../mock/doedata";

afterEach(cleanup);
const open = (id: string) => renderApp(`/p/p-body/doe/${id}`, "power", (s) => s.doe.demoJig());
const heads = (t: HTMLElement) => within(t).getAllByRole("columnheader").map((c) => c.textContent);

describe("지그 결과 mock·규칙", () => {
  it("isJigResult: metric_effective jig 만 true(fallback·solve·키 없음 = false)", () => {
    expect(isJigResult({})).toBe(false);
    expect(isJigResult({ metric_effective: "solve" })).toBe(false);
    expect(isJigResult({ rank: { metric_effective: "jig" } })).toBe(true);
    expect(isJigResult({ metric_effective: "jig", rank: { metric_effective: "solve" } })).toBe(false);
  });
  it("withJig ok·poor: 고정 필드명·score 오름차순, fallback: metric jig·effective solve·jig.status fallback", () => {
    renderApp("/p/p-body/doe/doe-21", "power", (s) => {
      const base = s.doe.recs.find((r) => r.out.id === "doe-21")!.result!;
      const ok = withJig(withSolveMetric(withMetric(base)), "ok");
      expect(ok.metric_effective).toBe("jig");
      expect(Object.keys(ok.jig!).sort()).toEqual(["cancel_rel_max", "code", "entries", "fit_mac_min", "fit_mac_min_nomodes", "fit_umax_err_max", "fit_umax_err_max_nomodes", "hz_321", "hz_jig", "hz_ratio", "n_contact", "n_jig", "n_modes", "n_patch", "n_regions", "region_source", "status", "th", "tie_rel_max"]);
      expect(Object.keys(ok.jig!.th).sort()).toEqual(["cancel_warn", "mac_min", "tie_rel_warn", "umax_err_max"]);
      expect(Object.keys(ok.jig!.entries[0]).sort()).toEqual(["F_sum_abs", "cancel_rel", "entry_id", "err_p95", "label", "mac", "mac_nomodes", "n_active", "rot_deg", "umax_err", "umax_err_nomodes"]);
      expect(ok.ranking.map((r) => r.score)).toEqual([...ok.ranking.map((r) => r.score)].sort((a, b) => a - b));
      expect(ok.ranking.every((r) => r.score_jig === r.score && r.umax_jig != null && r.C_jig)).toBe(true);
      expect(ok.jig!.n_regions).toBe(ok.jig!.n_contact + ok.jig!.n_patch);
      const fb = withJig(withSolveMetric(withMetric(base)), "fallback");
      expect([fb.metric, fb.rank?.metric_effective, fb.jig?.status, fb.jig?.code]).toEqual(["jig", "solve", "fallback", "JIG_NO_TIE"]);
    });
  });
  it("warnText: 서버 message 없으면 JIG_CODE_TEXT", () => {
    expect(warnText({ code: "JIG_NO_TIE" })).toBe(JIG_CODE_TEXT.JIG_NO_TIE);
  });
});

describe("지그 ok — doe-40", () => {
  it("주 열 '지그 C'·정의 문구·기준 재현 한 줄(MAC·umax 오차·영역 수)·보조 토글 3열", async () => {
    open("doe-40");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(heads(t)).toContain("지그 C"));
    expect(heads(t)).not.toContain("재풀이 C");
    const line = screen.getByTestId("jig-line");
    expect(line.textContent).toMatch(/^기준 재현\(지그\): MAC\(모드 포함\) ≥ 0\.9\d+ \(제외 0\.\d+\) · umax 오차 ≤ \d+\.\d %/);
    expect(line.textContent).toMatch(/하중 영역 3개\(접촉 2 · 패치 1\) · 지그 노드 14/);
    expect(line.className).toContain("muted");
    expect(screen.queryByTestId("jig-cancel")).toBeNull();           // cancel_rel_max ≤ cancel_warn → ⚠ 없음
    expect(line.title).toMatch(/지그 1차 11\.8 Hz \(3-2-1 대비 ×15\.73\)/);   // Hz 는 툴팁만
    expect(line.title).toMatch(/MAC 0\.9\d+ \(모드 제외 0\.\d+\) · umax 오차/);     // 엔트리별 값은 툴팁
    expect(screen.getByTestId("metric-defs").textContent).toMatch(/score: max\(C_jig 안\) \/ max\(C_jig 기준\).*영역 3개, 접촉\+패치.*같은 지그·같은 하중/);
    expect(screen.getByText(/정렬: score\(지그 C\)/)).toBeTruthy();
    fireEvent.click(screen.getByTestId("rank-aux-toggle"));
    await waitFor(() => expect(heads(t)).toEqual(expect.arrayContaining(["재풀이 C 비", "불평형", "umax(지그) 비"])));
    expect(within(t).getAllByTestId(/^aux-umaxjig-/).length).toBeGreaterThan(0);
    expect(within(t).getAllByTestId(/^aux-solve-/).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("sm-verify-note")).toBeNull();
    // 열 수 일치(행마다 셀 수 = 머리 수 — 보조 열 켠 상태)
    const n = heads(t).length;
    for (const tr of within(t).getAllByRole("row").slice(1)) if (!tr.classList.contains("doe-values-row")) expect(tr.children.length).toBe(n);
  }, 20000);
});

describe("지그 poor·fallback", () => {
  it("poor: 경고색 + JIG_FIT_POOR title(임계값 포함), 순위 계속", async () => {
    open("doe-41");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(heads(t)).toContain("지그 C"));
    const line = screen.getByTestId("jig-line");
    expect(line.className).toContain("warn-text");
    expect(line.getAttribute("data-status")).toBe("poor");
    expect(line.title).toContain(JIG_CODE_TEXT.JIG_FIT_POOR);
    expect(line.title).toMatch(/MAC ≥ 0\.9, umax 오차 ≤ 20 %/);
    expect(line.textContent).toMatch(/접촉 0 · 패치 3/);
    expect(screen.getByTestId("jig-cancel").title).toContain(JIG_CODE_TEXT.JIG_LOAD_CANCEL);   // JIG_LOAD_CANCEL ⚠ 1개, 같은 줄
    expect(line.querySelectorAll("[data-testid=jig-cancel]").length).toBe(1);
    expect(line.parentElement!.querySelectorAll("[data-testid=jig-line]").length).toBe(1);
    expect(within(t).getAllByTestId(/^rank-d/).length).toBeGreaterThan(0);
  }, 20000);
  it("fallback: '지그 순위 불가' + 사유, 주 열 재풀이 C, 지그 열·토글 없음", async () => {
    open("doe-42");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(heads(t)).toContain("재풀이 C"));
    expect(heads(t)).not.toContain("지그 C");
    const line = screen.getByTestId("jig-line");
    expect(line.textContent).toContain(`지그 순위 불가 — ${JIG_CODE_TEXT.JIG_NO_TIE}, 재풀이 C 로 순위`);
    expect(line.className).toContain("warn-text");
    expect(screen.getByText(/정렬: score\(재풀이 C\)/)).toBeTruthy();
    expect(screen.queryByTestId("metric-defs")!.textContent).not.toMatch(/C_jig/);
  }, 20000);
});

describe("solve 결과 + score_jig, legacy", () => {
  it("metric_effective solve 에 행 score_jig 가 있으면 보조 토글에 '지그 C 비' 1열", async () => {
    renderApp("/p/p-body/doe/doe-21", "power", (s) => {
      const rec = s.doe.recs.find((r) => r.out.id === "doe-21")!;
      const r = withSolveMetric(rec.result!);
      rec.result = { ...r, ranking: r.ranking.map((x) => ({ ...x, score_jig: +(x.score * 0.9).toFixed(3) })) };
    });
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(heads(t)).toContain("재풀이 C"));
    expect(heads(t)).not.toContain("지그 C 비");
    fireEvent.click(screen.getByTestId("rank-aux-toggle"));
    await waitFor(() => expect(heads(t).filter((h) => h === "지그 C 비").length).toBe(1));
    expect(within(t).getAllByTestId(/^aux-jig-/).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("jig-line")).toBeNull();      // 지그 블록 없음 = 한 줄 없음
  }, 20000);
  it("legacy(doe-3)·지그 블록 없는 결과: 지그 줄·열·토글 없음", async () => {
    renderApp("/p/p-body/doe/doe-3");
    const t = await screen.findByRole("table", { name: "순위표" });
    expect(heads(t)).toEqual(expect.arrayContaining(["score", "umax", "εmax"]));
    expect(heads(t).some((h) => /지그/.test(h ?? ""))).toBe(false);
    expect(screen.queryByTestId("jig-line")).toBeNull();
    expect(screen.queryByTestId("rank-aux-toggle")).toBeNull();
    expect(screen.getByTestId("metric-defs").textContent).not.toMatch(/지그/);
  }, 15000);
});
