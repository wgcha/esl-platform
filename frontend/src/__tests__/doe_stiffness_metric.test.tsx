// V-SM-9(esl_stiffness_metric.md §7·§8): 순위표 주 열 = 새 지표(lin), 보조 열 토글(재풀이 C 비·불평형·ρ·강체 제거 umax·εmax), 불평형 흐림·경고,
// SM_LIN_RANGE 경고, 검증 낙하 안내 1줄, 3D 범례 강체 제거 표기, legacy 결과 = 지금 그대로. 화면 크기는 scripts/screenshots-v0200.mjs.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { isCrossMesh, isLinResult, rankThresholds } from "../api/doe";
import { makeCompareResult, compareIds, makeComparePrep, withCrossMesh, withMetric } from "../mock/doedata";

describe("순위 지표 규칙(화면 쪽 함수·mock)", () => {
  it("isLinResult: lin 만 새 표시, 키 없음·solve = 옛 표시", () => {
    expect(isLinResult({})).toBe(false);
    expect(isLinResult({ metric: "solve" })).toBe(false);
    expect(isLinResult({ metric: "lin" })).toBe(true);
  });
  it("withMetric: score_solve 에 옛 score, 불평형·ρ·umax_def 채움, |ρ−1|>lin_valid 안 = 재풀이 C 대체(basis solve)", () => {
    const sh = (f: string, ref = false) => ({ upload_id: "u", name: f, reference: ref, file_name: `${f}.step`, sha256: f });
    const base = makeCompareResult(makeComparePrep(compareIds([sh("a", true), sh("b"), sh("c"), sh("d")]), "step"), ["le-1", "le-2"]);
    const r = withMetric(base);
    expect(r.metric).toBe("lin");
    expect([...r.ranking.map((x) => x.id)].sort()).toEqual([...base.ranking.map((x) => x.id)].sort());
    const orig = new Map(base.ranking.map((x) => [x.id, x.score]));
    for (const x of r.ranking) {
      expect(x.score_solve).toBe(orig.get(x.id));
      expect(x.umax_def).toBeLessThan(x.umax);
      const out = Math.abs((x.rho_min ?? 1) - 1) > 0.3 || Math.abs((x.rho_max ?? 1) - 1) > 0.3;
      expect(x.basis).toBe(out ? "solve" : "lin");
      if (out) expect(x.score).toBe(x.score_solve);
    }
    expect(r.rank?.n_fallback).toBe(r.ranking.filter((x) => x.basis === "solve").length);
    expect(r.ranking.map((x) => x.score)).toEqual([...r.ranking.map((x) => x.score)].sort((a, b) => a - b));
  });
  it("결정 A withCrossMesh: score = 재풀이 비, ρ·불평형 없음, metric_effective solve·cross_mesh·SM_CROSS_MESH", () => {
    const sh = (f: string, ref = false) => ({ upload_id: "u", name: f, reference: ref, file_name: `${f}.step`, sha256: f });
    const base = makeCompareResult(makeComparePrep(compareIds([sh("a", true), sh("b"), sh("c"), sh("d")]), "step"), ["le-1", "le-2"]);
    const r = withCrossMesh(base);
    expect(isLinResult(r)).toBe(false);
    expect(isCrossMesh(r)).toBe(true);
    expect(r.metric_effective).toBe("solve");
    expect(r.ranking.map((x) => [x.id, x.score])).toEqual(base.ranking.map((x) => [x.id, x.score]));
    expect(r.ranking.every((x) => x.rho_min == null && x.imbalance_max == null && x.umax_def != null)).toBe(true);
    expect(r.warnings.map((w) => w.code)).toContain("SM_CROSS_MESH");
    expect(isCrossMesh({})).toBe(false);
  });
});

describe("임계값 출처(하드코딩 없음)", () => {
  it("결과 스냅샷 rank → settings.rank → 없으면 null", () => {
    expect(rankThresholds({ rank: { lin_valid: 0.2, imbalance_warn: 0.05 } }, { rank: { lin_valid: 0.3, imbalance_warn: 0.02 } })).toEqual({ linValid: 0.2, imbalanceWarn: 0.05 });
    expect(rankThresholds({}, { rank: { lin_valid: 0.3, imbalance_warn: 0.02 } })).toEqual({ linValid: 0.3, imbalanceWarn: 0.02 });
    expect(rankThresholds({}, null)).toEqual({ linValid: null, imbalanceWarn: null });
  });
  it("둘 다 없으면 흐림·ρ 경고 없음", async () => {
    renderApp("/p/p-body/doe/doe-21", "power", (srv) => {
      delete srv.doe.settings.rank;
      const rec = srv.doe.recs.find((r) => r.out.id === "doe-21")!;
      const res = withMetric(rec.result!);
      delete res.rank;
      rec.result = res;
    });
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(screen.getByTestId("rank-aux-toggle")).toBeTruthy());
    fireEvent.click(screen.getByTestId("rank-aux-toggle"));
    await waitFor(() => expect(within(t).getAllByTestId(/^aux-imb-/).length).toBeGreaterThan(0));
    expect(t.querySelectorAll(".sm-faded").length).toBe(0);
    expect(within(t).getAllByTestId(/^aux-imb-/).every((c) => !/⚠/.test(c.textContent ?? ""))).toBe(true);
    expect(within(t).getAllByTestId(/^aux-rho-/).every((c) => !/⚠/.test(c.textContent ?? ""))).toBe(true);
  }, 20000);
});

describe("② 결과 — doe-21(metric lin, 같은 메시)", () => {
  it("주 열 '강성 지표', umax·εmax 열 없음, 보조 열 토글로 5열, 불평형 큰 행 흐림·⚠, 안내 1줄", async () => {
    renderApp("/p/p-body/doe/doe-21");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(screen.getByTestId("sm-verify-note")).toBeTruthy());
    expect(screen.getByTestId("sm-verify-note").textContent).toMatch(/Radioss 검증 낙하/);
    const heads = () => within(t).getAllByRole("columnheader").map((c) => c.textContent);
    expect(heads()).toContain("강성 지표");
    expect(heads()).not.toContain("umax");
    expect(heads()).not.toContain("εmax");
    expect(heads()).not.toContain("재풀이 C 비");
    fireEvent.click(screen.getByTestId("rank-aux-toggle"));
    await waitFor(() => expect(heads()).toContain("재풀이 C 비"));
    expect(heads()).toEqual(expect.arrayContaining(["불평형", "ρ", "umax(강체 제거)", "εmax"]));
    // 3번째 안(imbalance 0.18 > 0.02): 흐림 + ⚠
    const rows = within(t).getAllByTestId(/^rank-d/);
    const faded = rows.filter((r) => r.classList.contains("sm-faded"));
    expect(faded.length).toBeGreaterThan(0);
    expect(within(faded[0]).getByTestId(/^aux-imb-/).textContent).toMatch(/⚠/);
    expect(rows.some((r) => !r.classList.contains("sm-faded"))).toBe(true);
    // 경고 목록: SM_LIN_RANGE
    expect(screen.getByText(/1차 근사가 개선을 과장/)).toBeTruthy();
    // R-SM-1 결정: 범위 밖 안 = 주 열 값 옆 '재풀이' 표시(툴팁), 새 버튼·토글 없음
    const fb = within(t).getAllByTestId(/^basis-solve-/);
    expect(fb.length).toBeGreaterThan(0);
    expect(fb[0].textContent).toBe("재풀이");
    expect(fb[0].getAttribute("title")).toBe("1차 근사 범위 밖(|ρ−1|>0.3) — 재풀이 C로 순위");
    expect(rows.length - fb.length).toBeGreaterThan(0);
  }, 20000);

});

describe("④ 결과 — doe-20(결정 A: 다른 메시 비교)", () => {
  it("주 열 '재풀이 C', 안내 1줄(정밀도 낮음), 지표 보조 토글·1차 안내 없음, umax·εmax 열(강체 제거), 경고 목록에 중복 없음", async () => {
    renderApp("/p/p-body/doe/doe-20");
    const t = await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(screen.getByTestId("sm-cross-note")).toBeTruthy());
    expect(screen.getByTestId("sm-cross-note").textContent).toMatch(/다른 메시 비교\(정밀도 낮음\)/);
    const heads = within(t).getAllByRole("columnheader").map((c) => c.textContent);
    expect(heads).toContain("재풀이 C");
    expect(heads).not.toContain("강성 지표");
    expect(heads).toEqual(expect.arrayContaining(["umax", "εmax"]));
    expect(screen.queryByTestId("rank-aux-toggle")).toBeNull();
    expect(screen.queryByTestId("sm-verify-note")).toBeNull();
    expect(within(t).queryAllByTestId(/^basis-solve-/).length).toBe(0);        // ④ 불변(전부 solve — 대체 표시 없음)
    expect(screen.queryAllByText(/1차 강성 지표를 쓰지 않고/).length).toBe(0); // 서버 경고 문구는 안내 1줄로 대신
  }, 20000);

  it("3D 안내·범례: 강체 제거 · 해석값(순위와 무관)", async () => {
    renderApp("/p/p-body/doe/doe-20");
    await waitFor(() => expect(screen.getByText(/강체 제거, 해석값\(순위와 무관\)/)).toBeTruthy(), { timeout: 8000 });
  }, 15000);
});

describe("legacy 결과 — doe-3(metric 없음)", () => {
  it("지금 표시 그대로: score·umax·εmax 열, 보조 토글·안내 없음", async () => {
    renderApp("/p/p-body/doe/doe-3");
    const t = await screen.findByRole("table", { name: "순위표" });
    const heads = within(t).getAllByRole("columnheader").map((c) => c.textContent);
    expect(heads).toEqual(expect.arrayContaining(["umax", "εmax"]));
    expect(heads).not.toContain("강성 지표");
    expect(screen.queryByTestId("rank-aux-toggle")).toBeNull();
    expect(screen.queryByTestId("sm-verify-note")).toBeNull();
  }, 15000);
});
