// V-CI-F1: 누적 씬 화면(배지·① 누적 입력 카드·② t* 3값·표 열·증분 곡선 토글·③ 증분 표기) + 비누적 Case 화면 불변
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/endpoints";
import type { CaseOut, CumulativeSummary, TstarView } from "../api/types";
import { renderApp } from "../test/render";
import { MaxHoldChart } from "../components/MaxHoldChart";
import { cumText } from "../components/Cumulative";

const url = (n: number) => `/p/p-body/c/c-demo/stage/${n}`;

const CUM: CumulativeSummary = {
  enabled: true,
  files: [
    { name: "Scene07_1st_0002.str", kinds: ["geometry"], runname: "Scene07_1st", size: 3_400_000 },
    { name: "Scene07_1st_0002.sta", kinds: ["initial"], runname: "Scene07_1st", size: 1_200_000_000 },
  ],
  epsp_mode: "cumulative",
  eq_mode: "incremental",
  agg: "mid_mean",
  n_prev_elems: 415,
  prev_max: 0.08,
  prev_p99: 0.02,
  coord_source: "state",
  n_nodes_state: 1107,
  n_nodes_rad: 0,
  thickness: {
    source: "state",
    k_l_source: "state",
    n_elems: 1144,
    n_state: 1144,
    t0: 2,
    ratio: { min: 0.97, p01: 0.971, mean: 0.99, p99: 1, max: 1 },
    n_changed: 120,
    max_thinning_pct: 3,
    elem_max_thinning: 50625,
  },
  diagnosis: {
    epsp: { mode: "cumulative", detected: "cumulative", r0: 1, mono: 1, n_S: 415, forced: false },
    eq: { mode: "incremental", detected: "incremental", r0: 0, mono: 0, n_S: 415, forced: false },
  },
  warning_codes: ["STATE_PARTIAL"],
};

function withCumCase() {
  const real = api.getCase;
  return vi.spyOn(api, "getCase").mockImplementation(async (id: string) => {
    const c = (await real(id)) as CaseOut;
    return { ...c, extract_summary: c.extract_summary ? { ...c.extract_summary, cumulative: CUM } : c.extract_summary };
  });
}

function withCumTstar() {
  const real = api.tstar;
  return vi.spyOn(api, "tstar").mockImplementation(async (id: string) => {
    const t = (await real(id)) as TstarView;
    const m = { ...t.metrics };
    for (const k of Object.keys(m) as (keyof typeof m)[]) {
      const b = m[k]!;
      m[k] = {
        ...b,
        tstar: b.tstar ? { ...b.tstar, value_prev: 0.08, value_inc: b.tstar.value - 0.08 } : null,
        candidates: b.candidates.map((x) => ({ ...x, value_prev: 0.08, value_inc: x.value - 0.08 })),
        hotspots: b.hotspots.map((h) => ({ ...h, value_prev: 0.01, value_inc: h.value - 0.01 })),
        history: { ...b.history, value_inc: b.history.value.map((v) => v / 2) },
        cumulative: { mode: "incremental", n_excluded_no_increment: 7 },
      };
    }
    return { ...t, metrics: m, cumulative: { enabled: true, epsp_mode: "cumulative", eq_mode: "incremental", agg: "mid_mean", n_prev_elems: 415, min_increment: 1e-5 } };
  });
}

describe("V-CI-F1 누적 씬 화면", () => {
  it("① 누적 입력 카드 + Case 배지", async () => {
    const s = withCumCase();
    try {
      renderApp(url(1));
      expect(await screen.findByTestId("cum-card")).toBeTruthy();
      expect(screen.getByTestId("cum-badge").textContent).toContain("누적 씬");
      expect(screen.getByTestId("cum-badge").getAttribute("title")).toContain("Scene07_1st_0002.sta");
      expect(screen.getByText("Scene07_1st_0002.str")).toBeTruthy();
      expect(screen.getByText("상태 1,107 / rad 0")).toBeTruthy();
      expect(screen.getByText("증분(이번 낙하분)")).toBeTruthy();
      expect(screen.getByTestId("cum-warn").textContent).toContain("STATE_PARTIAL");
    } finally {
      s.mockRestore();
    }
  });

  it("② t* 3값·표 열·제외 수·증분 곡선 토글", async () => {
    const s1 = withCumCase();
    const s2 = withCumTstar();
    try {
      renderApp(url(2));
      const line = await screen.findByTestId("cum-tstar");
      expect(line.textContent).toMatch(/누적 [\d.]+ \(이전 0\.080* \+ 이번 [\d.]+\)/);
      expect(line.textContent).toContain("이전 손상만(이번 증가 없음) 7개 제외");
      expect(screen.getAllByText("이번(증분)").length).toBeGreaterThanOrEqual(3);     // 후보·hotspot 표 + 범례
      expect(screen.getAllByRole("columnheader", { name: "이전" }).length).toBe(2);
      expect(screen.queryByTestId("inc-line")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: /이번\(증분\)/ }));
      await waitFor(() => expect(screen.getByTestId("inc-line")).toBeTruthy());
    } finally {
      s1.mockRestore();
      s2.mockRestore();
    }
  });

  it("비누적 ② 화면 불변(누적 열·범례·배지 없음)", async () => {
    renderApp(url(2));
    await screen.findByRole("heading", { level: 2, name: "② t*·지지점" });
    await waitFor(() => expect(screen.getAllByRole("columnheader", { name: "값" }).length).toBe(2));
    expect(screen.queryByText("이번(증분)")).toBeNull();
    expect(screen.queryByTestId("cum-legend")).toBeNull();
    expect(screen.queryByTestId("cum-badge")).toBeNull();
    expect(screen.queryByTestId("cum-tstar")).toBeNull();
  });

  it("비누적 ① 화면: 누적 카드 없음", async () => {
    renderApp(url(1));
    await screen.findByRole("heading", { level: 2, name: "① 입력" });
    await waitFor(() => expect(screen.getByText("추출 결과")).toBeTruthy());
    expect(screen.queryByTestId("cum-card")).toBeNull();
  });

  it("값 표기·차트 범례(단위)", () => {
    expect(cumText({ value: 0.123, value_prev: 0.08, value_inc: 0.043 }, 3)).toBe("누적 0.123 (이전 0.0800 + 이번 0.0430)");
    expect(cumText({ value: 0.5 })).toBe("0.5000");
    render(<MaxHoldChart time={[0, 1, 2]} value={[0, 1, 2]} valueInc={[0, 0.5, 1]} candidates={[]} selectedFrame={null} label="x" />);
    expect(screen.getByTestId("cum-legend")).toBeTruthy();
  });
});
