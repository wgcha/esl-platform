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
      expect(Object.keys(ok.jig!).sort()).toEqual(["cancel_rel_max", "code", "entries", "fit_mac_min", "fit_mac_min_nomodes", "fit_umax_err_max", "fit_umax_err_max_nomodes", "fit_work_eff_min", "hz_321", "hz_jig", "hz_ratio", "n_contact", "n_jig", "n_modes", "n_patch", "n_regions", "region_source", "status", "th", "tie_rel_max", "tie_spread"]);
      expect(Object.keys(ok.jig!.th).sort()).toEqual(["cancel_warn", "mac_min", "tie_rel_warn", "tie_spread_min", "umax_err_max", "work_eff_min"]);
      expect(Object.keys(ok.jig!.entries[0]).sort()).toEqual(["F_sum_abs", "cancel_rel", "entry_id", "err_p95", "label", "mac", "mac_nomodes", "n_active", "rot_deg", "umax_err", "umax_err_nomodes", "work_eff"]);
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
  it("주 열 '지그 C'·정의 문구·기준 재현 한 줄(MAC·umax 오차·영역 수)·보조 토글 = 지그 값만(v0.23.3 탭)", async () => {
    open("doe-40");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(heads(t)).toContain("지그 C"));
    expect(heads(t)).not.toContain("재풀이 C");
    const line = screen.getByTestId("jig-line");
    // v0.23.1 상태 띠 칩: 짧은 값(MAC·umax 오차) + 이전 한 줄 전체 = title 첫 줄
    expect(line.textContent).toMatch(/^기준 재현\(지그\) MAC ≥ 0\.9\d+ · umax 오차 ≤ \d+\.\d %/);
    expect(line.title).toMatch(/^기준 재현\(지그\): MAC\(모드 포함\) ≥ 0\.9\d+ \(제외 0\.\d+\) · umax 오차 ≤ \d+\.\d %/);
    expect(line.title).toMatch(/하중 영역 3개\(접촉 2 · 패치 1\) · 지그 노드 14/);
    expect(line.className).not.toContain("muted");                    // v0.23.2 D-0.23.2-3: 중립 상태 = 기본 글자색
    expect(screen.queryByTestId("jig-cancel")).toBeNull();           // 일 효율 ≥ work_eff_min → ⚠ 없음(cancel_rel 은 툴팁 정보만)
    expect(line.title).toMatch(/지그 1차 11\.8 Hz \(3-2-1 대비 ×15\.73\)/);   // Hz 는 툴팁만
    expect(line.title).toMatch(/MAC 0\.9\d+ \(모드 제외 0\.\d+\) · umax 오차/);     // 엔트리별 값은 툴팁
    expect(screen.getByTestId("metric-defs").textContent).toMatch(/score: max\(C_jig 안\) \/ max\(C_jig 기준\).*영역 3개, 접촉\+패치.*같은 지그·같은 하중/);
    expect(screen.getByText(/정렬: score\(지그 C\)/)).toBeTruthy();
    fireEvent.click(screen.getByTestId("rank-aux-toggle"));
    // v0.23.3 하중 정의 탭(D-0.23.3-4): 지그 탭 보조 열 = 지그 값만(재풀이 C 비·불평형은 전 노드 탭으로)
    await waitFor(() => expect(heads(t)).toContain("umax(지그) 비"));
    expect(heads(t)).not.toContain("재풀이 C 비");
    expect(heads(t)).not.toContain("불평형");
    expect(within(t).getAllByTestId(/^aux-umaxjig-/).length).toBeGreaterThan(0);
    expect(within(t).queryAllByTestId(/^aux-solve-/).length).toBe(0);
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
    expect(line.title).toMatch(/접촉 0 · 패치 3/);
    expect(screen.getByTestId("jig-cancel").title).toContain(JIG_CODE_TEXT.JIG_LOAD_CANCEL);
    expect(screen.getByTestId("jig-cancel").title).toMatch(/일 효율 0\.030 < 0\.05/);   // JIG_LOAD_CANCEL ⚠ 1개, 같은 줄
    expect(line.querySelectorAll("[data-testid=jig-cancel]").length).toBe(1);
    expect((line.textContent ?? "").split("⚠").length - 1).toBe(1);                  // D-JIG-19: 줄 안 ⚠ = JIG_LOAD_CANCEL 1개만
    expect(line.title).toContain(JIG_CODE_TEXT.JIG_SUPPORT_WEAK);                    // tie 몰림·FIT_POOR 는 툴팁
    expect(line.parentElement!.querySelectorAll("[data-testid=jig-line]").length).toBe(1);
    expect(within(t).getAllByTestId(/^rank-d/).length).toBeGreaterThan(0);
  }, 20000);
  it("fallback: '지그 순위 불가' + 사유, 주 열 재풀이 C, 지그 열·토글 없음", async () => {
    open("doe-42");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(heads(t)).toContain("재풀이 C"));
    expect(heads(t)).not.toContain("지그 C");
    const line = screen.getByTestId("jig-line");
    expect(line.title).toContain(`지그 순위 불가 — ${JIG_CODE_TEXT.JIG_NO_TIE}, 재풀이 C 로 순위`);
    expect(line.textContent).toMatch(/지그 순위 불가/);
    expect(line.textContent).not.toContain("⚠");
    expect(line.className).toContain("warn-text");
    expect(screen.getByText(/정렬: score\(재풀이 C\)/)).toBeTruthy();
    expect(screen.queryByTestId("metric-defs")!.textContent).not.toMatch(/C_jig/);
  }, 20000);
});

describe("solve 결과 + score_jig, legacy", () => {
  it("metric_effective solve 에 행 score_jig 가 있어도 전 노드 탭에는 '지그 C 비' 없음(v0.23.3 탭 분리)", async () => {
    renderApp("/p/p-body/doe/doe-21", "power", (s) => {
      const rec = s.doe.recs.find((r) => r.out.id === "doe-21")!;
      const r = withSolveMetric(rec.result!);
      rec.result = { ...r, ranking: r.ranking.map((x) => ({ ...x, score_jig: +(x.score * 0.9).toFixed(3) })) };
    });
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(heads(t)).toContain("재풀이 C"));
    expect(heads(t)).not.toContain("지그 C 비");
    const tog = screen.queryByTestId("rank-aux-toggle");
    if (tog) fireEvent.click(tog);
    await waitFor(() => expect(heads(t).filter((h) => h === "지그 C 비").length).toBe(0));
    expect(within(t).queryAllByTestId(/^aux-jig-/).length).toBe(0);
    const jigTab = screen.getByTestId("doe-load-tab").querySelector("[data-tab=jig]") as HTMLButtonElement;
    expect(jigTab.getAttribute("aria-disabled")).toBe("true");                                   // 지그 블록 없음 = 지그 탭 비활성 + 사유(칩 문구)
    expect(jigTab.title).toMatch(/지그 순위 도입\(v0\.23\.0\) 전/);
    // v0.23.2: 지그 블록 없음 = 미계산 칩(doe-21 = ① 새 스냅샷 → 복제하면 계산)
    expect(screen.getByTestId("jig-line").getAttribute("data-status")).toBe("none");
    expect(screen.getByTestId("jig-line").textContent).toBe("지그: 미계산(이전 설정 스터디 — 복제하면 계산)");
  }, 20000);
  it("legacy(doe-3)·지그 블록 없는 결과: 지그 줄·열·토글 없음", async () => {
    renderApp("/p/p-body/doe/doe-3");
    const t = await screen.findByRole("table", { name: "순위표" });
    expect(heads(t)).toEqual(expect.arrayContaining(["score", "umax", "εmax"]));
    expect(heads(t).some((h) => /지그/.test(h ?? ""))).toBe(false);
    expect(screen.getByTestId("jig-line").getAttribute("data-status")).toBe("none");     // v0.23.2 칩 항상(옛 = 미계산)
    expect(screen.queryByTestId("rank-aux-toggle")).toBeNull();
    expect(screen.getByTestId("metric-defs").textContent).not.toMatch(/지그/);
  }, 15000);
});

describe("JIG_LOAD_CANCEL 판정 = 일 효율(D-JIG-18)", () => {
  it("cancel_rel_max 가 커도 fit_work_eff_min ≥ work_eff_min 이면 ⚠ 없음, 미달이면 ⚠ 1개", async () => {
    renderApp("/p/p-body/doe/doe-21", "power", (s) => {
      const rec = s.doe.recs.find((r) => r.out.id === "doe-21")!;
      const r = withJig(withSolveMetric(withMetric(rec.result!)), "ok");
      rec.result = { ...r, jig: { ...r.jig!, cancel_rel_max: 0.9 } };
    });
    await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(screen.getByTestId("jig-line")).toBeTruthy());
    expect(screen.queryByTestId("jig-cancel")).toBeNull();
    cleanup();
    renderApp("/p/p-body/doe/doe-21", "power", (s) => {
      const rec = s.doe.recs.find((r) => r.out.id === "doe-21")!;
      const r = withJig(withSolveMetric(withMetric(rec.result!)), "ok");
      rec.result = { ...r, jig: { ...r.jig!, cancel_rel_max: 0.1, fit_work_eff_min: 0.01 } };
    });
    await waitFor(() => expect(screen.getByTestId("jig-cancel")).toBeTruthy());
  }, 20000);
  it("JIG_TIE_RELATIVE·JIG_SUPPORT_WEAK 는 ⚠ 없이 title 툴팁만(D-JIG-19)", async () => {
    renderApp("/p/p-body/doe/doe-21", "power", (s) => {
      const rec = s.doe.recs.find((r) => r.out.id === "doe-21")!;
      const r = withJig(withSolveMetric(withMetric(rec.result!)), "ok");
      rec.result = { ...r, jig: { ...r.jig!, tie_rel_max: 0.5, tie_spread: 0.005 } };
    });
    await waitFor(() => expect(screen.getByTestId("jig-line")).toBeTruthy());
    const line = screen.getByTestId("jig-line");
    expect(line.textContent).not.toContain("⚠");
    expect(screen.queryByTestId("jig-cancel")).toBeNull();
    expect(line.title).toContain(JIG_CODE_TEXT.JIG_TIE_RELATIVE);
    expect(line.title).toMatch(new RegExp(`${JIG_CODE_TEXT.JIG_SUPPORT_WEAK.slice(0, 10)}.*분포 0\\.0050 < 0\\.02`));
  }, 20000);
});
