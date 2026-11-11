// v0.18.0 STEP_GRAPH(esl_step_graph.md V-SG-8 — 화면, mock): ③ 새 스터디 = select + select_base "step"(STEP·인치·쉘 물성·메시 방식, 요소 크기 칸 없음),
// 선택 화면 요약(고정 이전 1줄 · 평가 영역 1줄 · 삼각형 메시 경고 — 모두 MsgFold), seed fixed_user(고정만 seed 도 기본 상태·초기화 = seed),
// ⑤ 평면도(PartView) 주 시트 영역 층·A 이전 고정 표시, 목록·상세 이름(③ select / 이전 방식 ③ paicad).
import { act, fireEvent, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../test/render";
import {
  loadSelectAuto, radioRequest, regionText, selectSubBlocked, stepPrepGroups, studyRadio, studyScenarioLabel, xferText,
} from "../api/doe";
import { makeDoeSettings } from "../mock/doedata";
import { MockServer, createMockFetch } from "../mock/server";
import { stepAutoSeed } from "../mock/graphmock";
import { useBeadSelect } from "../components/BeadSelectCard";
import { selectPlan } from "../view3d/part/adapters";
import type { DoePlanOut } from "../api/types";

const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const radio = (name: RegExp | string) => screen.getByRole("radio", { name }) as HTMLInputElement;
const reasonOf = (b: HTMLElement) => b.closest(".primary-wrap")?.getAttribute("title") ?? "";

afterEach(() => vi.restoreAllMocks());

describe("③ select step — 순수 함수", () => {
  it("라디오 ③ → select + step, 기존 스터디 위치·목록 이름(③ select / 이전 방식 paicad)", () => {
    expect(radioRequest("step")).toEqual({ scenario: "select", selectBase: "step" });
    expect(studyRadio("select", "step")).toBe("step");
    expect(studyRadio("step", null)).toBe("step");
    expect(studyScenarioLabel("select", "step")).toBe("③ 다른 모델(STEP만)");
    expect(studyScenarioLabel("step", null)).toBe("③ 다른 모델(STEP만) — 이전 방식(paicad)");
    expect(studyScenarioLabel("select", "mesh")).toBe("② 다른 모델(B 메시)");
  });

  it("막힘: gmsh 없음 또는 select_step false = GMSH 사유, paicad 없음은 무관", () => {
    const st = makeDoeSettings();
    expect(selectSubBlocked(st, "step", "manual")).toBeNull();
    st.paicad.ready = false;
    expect(selectSubBlocked(st, "step", "manual")).toBeNull();
    st.scenarios.select_step = false;
    expect(selectSubBlocked(st, "step", "manual")).toMatch(/gmsh/);
    const st2 = makeDoeSettings();
    st2.gmsh.ready = false;
    expect(selectSubBlocked(st2, "step", "auto")).toMatch(/gmsh/);
  });

  it("고정 이전 1줄: 좌표 일치(최근접) · 불일치(구멍 스냅, 못 옮김 수) · 없음", () => {
    expect(xferText({ method: "xyz_nearest", matched: 12, unmatched: 0, frame_ok: true })).toBe("A 고정 12개 중 12개를 옮김(좌표 일치 — 최근접 노드) — 고정 층에서 수정");
    expect(xferText({ method: "xyz_fitted", matched: 8, unmatched: 0, frame_ok: false })).toBe("A 고정 8개 중 8개를 옮김(구멍 맞춤 이동 — 최근접 노드) — 고정 층에서 수정");
    expect(xferText({ method: "ab_hole_snap", matched: 11, unmatched: 1, frame_ok: false })).toBe("A 고정 12개 중 11개를 옮김(좌표 불일치 — B 구멍 스냅) — 고정 층에서 수정 · 못 옮김 1개");
    expect(xferText({ method: "none", matched: 0, unmatched: 3, frame_ok: false })).toMatch(/자동 설정 없음\(A 고정 3개 — 대응 없음\)/);
    expect(regionText({ n_out: 1234 })).toBe("주 시트 밖 형상 1,234 요소 — 평가·비드 후보 제외");
  });

  it("요약 묶음: 고정·영역은 정보(요약 줄과 같은 코드는 한 번), 삼각형은 경고 — 서버 경고 없으면 prep.mesh 로", () => {
    const g = stepPrepGroups({
      fixed: { source: "a_transfer", n: 40, xfer: { method: "ab_hole_snap", matched: 2, unmatched: 1, frame_ok: false } },
      region: { n_out: 500 },
      mesh: { method: "tria", tri_frac: 1 },
      warnings: [
        { code: "FIXED_XFER_UNMATCHED", label: "F07", d_mm: 14.2, level: "info" },
        { code: "STEP_GRAPH_REGION", n_out: 500, level: "info" },
        { code: "STEP_GRAPH_REGION_SMALL" },
        { code: "AUTO_HINT_UNAVAILABLE" },
      ],
    });
    expect(g.fixed.map((x) => x.code)).toEqual(["FIXED_XFER", "FIXED_XFER_UNMATCHED"]);
    expect(g.fixed[1].text).toMatch(/A 고정 F07: B 에서 대응을 못 찾음\(최소 14.2 mm\)/);
    expect(g.fixed.every((x) => x.info)).toBe(true);
    expect(g.region.map((x) => [x.code, x.info])).toEqual([["STEP_GRAPH_REGION", true], ["STEP_GRAPH_REGION_SMALL", false]]);
    expect(g.mesh).toHaveLength(1);
    expect(g.mesh[0]).toMatchObject({ code: "STEP_GRAPH_TRIA", info: false });
    expect(g.mesh[0].text).toMatch(/삼각형 메시\(삼각형 폴백 · 삼각 100 %\)/);
    // 영역 = 전체·cad 메시·이전 없음(사유 경고)
    const g2 = stepPrepGroups({ fixed: { source: "none", n: 0 }, region: { n_out: 0 }, mesh: { method: "cad", tri_frac: 0.02 }, warnings: [{ code: "FIXED_XFER_NONE", reason: "A_CASE_MISSING", level: "info" }] });
    expect(g2.fixed.map((x) => x.text)).toEqual(["A 고정점 자동 설정 없음(A Case 없음) — 고정 층에 직접 칠하세요"]);
    expect(g2.region).toEqual([]);
    expect(g2.mesh).toEqual([]);
  });

  it("PartView 어댑터: ③ 은 영역 외곽 층·A 이전 고정 표시, ② ① 은 없음(자료가 없으면 층 숨김)", () => {
    const plan: DoePlanOut = {
      frame: { a_range: [0, 100], b_range: [0, 50] }, outline: [[0, 0], [100, 0], [100, 50], [0, 50]], holes: [], elems: { n_total: 0, decimated: true, points: [] },
      beads: [], fixed: [{ a: 1, b: 2, src: "a_transfer" }, { a: 3, b: 4, src: "user" }], a_points: [], load_points: [], links: [], region_ab: [[[0, 0], [100, 0], [100, 40], [0, 40]]],
    } as unknown as DoePlanOut & { region_ab: [number, number][][] };
    const p3 = selectPlan(plan, {}, false, true);
    expect(p3.region).toHaveLength(1);
    expect(p3.fixed).toEqual([{ a: 1, b: 2, xfer: true }, { a: 3, b: 4 }]);
    const p1 = selectPlan(plan, {}, false);
    expect(p1.region).toBeNull();
    expect(p1.fixed!.some((f) => f.xfer)).toBe(false);
    const p3b = selectPlan({ ...plan, region_ab: undefined }, {}, false, true);
    expect(p3b.region).toBeNull();
  });
});

describe("③ select step — 화면(mock)", () => {
  it("새 ③: 하위 '비드' 라디오, STEP 필수·인치·쉘 물성(서버 기본값)·메시 방식 고급(요소 크기 칸 없음) → select + select_base step", async () => {
    const r = renderApp("/p/p-body/doe/new?entries=le-1,le-9", "power");
    await waitFor(() => expect(radio(/③ 다른 모델\(STEP만\)/).checked).toBe(true));
    expect(screen.getByTestId("doe-beaddef")).toBeTruthy();
    expect(radio(/^직접 선택$/).checked).toBe(true);
    expect(screen.queryByTestId("doe-mesh-drop")).toBeNull();
    expect(screen.queryByRole("textbox", { name: "B 파트 제목" })).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "요소 크기 (mm)" })).toBeNull();
    expect(screen.getByTestId("compare-adv")).toBeTruthy(); // ④ 메시 방식 칸 재사용(기본 접힘)
    await waitFor(() => expect(reasonOf(primaries(r.container)[0])).toMatch(/STEP 을 올리세요/));
    fireEvent.change(screen.getByLabelText("Ch/R 중립면 STEP 끌어다 놓기"), { target: { files: [new File([new Uint8Array(4096)], "QN80J_mid.stp")] } });
    await waitFor(() => expect((screen.getByRole("spinbutton", { name: "두께 t (mm)" }) as HTMLInputElement).value).toBe("1.2"), { timeout: 4000 });
    expect(screen.getByTestId("doe-check").textContent).toMatch(/STEP QN80J_mid\.stp/);
    expect(screen.getByTestId("doe-check").textContent).not.toMatch(/기준 Case/);
    fireEvent.change(screen.getByRole("spinbutton", { name: "인치" }), { target: { value: "75" } });
    await waitFor(() => expect(primaries(r.container)[0].disabled).toBe(false), { timeout: 4000 });
    expect(primaries(r.container)).toHaveLength(1);
    fireEvent.click(primaries(r.container)[0]);
    expect(await screen.findByRole("heading", { level: 1, name: "강성 평가 스터디" })).toBeTruthy();
    const rec = r.server.doe.recs[r.server.doe.recs.length - 1];
    expect(rec.out.scenario).toBe("select");
    expect(rec.out.inputs).toMatchObject({ select_base: "step", bead_source: "manual", inch: 75, part_title: null, props: { t: 1.2, E: 205000, nu: 0.3 }, select_schema: 2 });
    expect(rec.out.inputs.mesh_size_mm).toBeNull();
    // 상세: ③ 위치 + 하위 라디오(읽기만), 기준 칩
    await waitFor(() => expect(radio(/③ 다른 모델\(STEP만\)/).checked).toBe(true));
    expect(screen.queryByTestId("doe-legacy")).toBeNull();
    expect(screen.getByTestId("doe-base-chip").textContent).toMatch(/기준 STEP 메시/);
  }, 15000);

  it("doe-15(자동·저장됨): 선택 화면 요약 = 고정 이전 1줄·평가 영역 1줄(MsgFold), 삼각형 경고 없음, ① 카드 요약·⑤ 영역 층·A 이전 고정", async () => {
    renderApp("/p/p-body/doe/doe-15", "power", (s) => s.doe.demoStepSel());
    const xfer = await screen.findByTestId("bs-step-xfer", undefined, { timeout: 6000 });
    expect(xfer.textContent).toMatch(/A 고정 12개 중 12개를 옮김\(좌표 일치 — 최근접 노드\) — 고정 층에서 수정/);
    expect(screen.getByTestId("bs-step-region").textContent).toMatch(/주 시트 밖 형상 [\d,]+ 요소 — 평가·비드 후보 제외/);
    expect(screen.getByTestId("bs-step-region-count").textContent).toMatch(/ⓘ 경고 0건 · 정보 1건/);
    expect(screen.queryByTestId("bs-step-tria")).toBeNull();
    // 같은 코드가 ① 준비 경고 목록에 또 나오지 않음
    expect(screen.queryByTestId("prep-warn")).toBeNull();
    expect(screen.getByText(/STEP 메시 [\d.]+만 노드 ✓ · 메시 CAD · 고정: A 이전 \d+ 노드 ✓/)).toBeTruthy();
    // ⑤ 평면도: 주 시트 영역 층 + A 이전 고정
    await waitFor(() => expect(screen.getByTestId("pv-select")).toBeTruthy(), { timeout: 6000 });
    expect(screen.getByTestId("pv-layer-region")).toBeTruthy();
    expect(screen.getByTestId("plan-region")).toBeTruthy();
    expect(screen.getAllByTestId("plan-fixed-xfer").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId("pv-layer-region"));
    expect(screen.queryByTestId("plan-region")).toBeNull();
  }, 15000);

  it("doe-16(직접·삼각형 폴백): 삼각형 경고 1줄(⚠), 구멍 스냅 + 못 옮긴 클러스터, '체결 정보 없음' 띠 대신 요약", async () => {
    renderApp("/p/p-body/doe/doe-16", "power", (s) => s.doe.demoStepSel());
    const tria = await screen.findByTestId("bs-step-tria", undefined, { timeout: 6000 });
    expect(screen.getByTestId("bs-step-tria-count").textContent).toMatch(/⚠ 경고 1건/);
    expect(tria.textContent).toMatch(/삼각형 메시\(삼각형 폴백 · 삼각 100 %\)/);
    const xfer = screen.getByTestId("bs-step-xfer");
    expect(xfer.textContent).toMatch(/A 고정 12개 중 11개를 옮김\(좌표 불일치 — B 구멍 스냅\)/);
    fireEvent.click(xfer.querySelector("button")!);
    expect(xfer.textContent).toMatch(/A 고정 F07: B 에서 대응을 못 찾음\(최소 14.2 mm\)/);
    expect(screen.queryByTestId("bs-step-region")).toBeNull(); // 영역 = 전체
    expect(screen.queryByTestId("bs-fixed-missing")).toBeNull();
    // 이 화면 밖 ④ 사다리 문구(MESH_TRIA_FALLBACK)는 ① 카드 목록에
    expect(screen.getByTestId("prep-warn")).toBeTruthy();
  }, 15000);

  it("이전 방식 ③(doe-17): ③ 위치 + '이전 방식(paicad)' 표시, 하위 라디오 없음 · 목록 이름", async () => {
    renderApp("/p/p-body/doe/doe-17", "power", (s) => s.doe.demoStepSel());
    await waitFor(() => expect(radio(/③ 다른 모델\(STEP만\)/).checked).toBe(true));
    expect(screen.getByTestId("doe-legacy").textContent).toMatch(/이전 방식\(paicad\)/);
    expect(screen.queryByTestId("doe-beaddef")).toBeNull();
  });

  it("스터디 목록: ③ select = '③ 다른 모델(STEP만)', 이전 ③ = '… — 이전 방식(paicad)'", async () => {
    renderApp("/p/p-body/doe", "power", (s) => s.doe.demoStepSel());
    const row15 = await screen.findByText("QN80J Ch/R 비드 — STEP 그래프(자동)", undefined, { timeout: 6000 });
    expect(row15.closest("tr")!.textContent).toMatch(/③ 다른 모델\(STEP만\)(?! —)/);
    const row17 = screen.getByText("QN80J Ch/R 비드 — STEP만(이전 방식)");
    expect(row17.closest("tr")!.textContent).toMatch(/③ 다른 모델\(STEP만\) — 이전 방식\(paicad\)/);
  });
});

describe("③ manual seed(고정만) — useBeadSelect", () => {
  it("빈 비드 + fixed_user seed = 기본 상태(고정 층 미리 칠함), 고정 지우고 전체 초기화 → seed 고정으로", async () => {
    const server = new MockServer({ user: "power" });
    server.doe.demoStepSel();
    globalThis.fetch = createMockFetch(server);
    const st = makeDoeSettings();
    const got = await loadSelectAuto("doe-16");
    expect(got.seed).not.toBeNull();
    expect(got.seed!.selection.beads).toEqual([]);
    const seed = stepAutoSeed(false).selection;
    const nSeed = seed.fixed_user!.q.reduce((s, [a, b]) => s + b - a + 1, 0);
    expect(nSeed).toBeGreaterThan(0);
    const { result } = renderHook(() => useBeadSelect("doe-16", true, null, st, seed, { schema: 2 }));
    await waitFor(() => expect(result.current.state).not.toBeNull(), { timeout: 6000 });
    const fixedN = () => result.current.state!.fixed.reduce((s: number, v: number) => s + (v ? 1 : 0), 0);
    expect(result.current.hasSeed).toBe(true);
    expect(fixedN()).toBe(nSeed);
    act(() => {
      const s = result.current.state!;
      s.fixed.fill(0);
    });
    expect(fixedN()).toBe(0);
    act(() => result.current.resetAll());
    expect(fixedN()).toBe(nSeed);
  });
});
