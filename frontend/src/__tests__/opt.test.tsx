// V-OR-18(esl_opt_run.md §14): 라이브러리 행 선택·크기 비활성·ⓜ·모드 드롭다운 저장, S1/S2 탭, 다른 모델 빼기, 비드 3칸 기본값,
// 목표 기준·전략 라디오(추천 배지·C 만 k·B 비활성), ⓘ 팝오버(요약·전략별 줄·출처 새 탭·키보드 닫기), 주 버튼 비활성 사유,
// 상세 하중 선정 표(병합 대상·반대 방향·전략 표시), 템플릿 탭(등록·삭제 권한·보관). V-OR-1(화면 크기 규칙)·V-OR-21(목표 기준 화면) 포함.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { MISMATCH_REASON, opt, resetOptSettingsCache, sameSize, templateMismatch } from "../api/opt";
import { JOB_TYPE_LABEL, currentStepKey, linkPath, stepLabel } from "../api/history";
import { isFullResult } from "../api/types";
import { makeSelection } from "../mock/optdata";
import { MockServer } from "../mock/server";
import { failureFiles } from "../pages/opt/OptDetail";

describe("v0.7.0 통합 정합(서버 기준)", () => {
  it("대기열·이력 라벨: OPT_RUN = 비드 최적화, 단계 키 → 한글(steps 없으면 순서로)", () => {
    expect(JOB_TYPE_LABEL.OPT_RUN).toBe("비드 최적화");
    expect(currentStepKey({ job_type: "OPT_RUN", current_step_no: 4, steps: null })).toBe("OS_SOLVE");
    expect(stepLabel(currentStepKey({ job_type: "OPT_RUN", current_step_no: 1 }))).toBe("대상 준비");
    expect(currentStepKey({ job_type: "OPT_RUN", current_step_no: null })).toBeNull();
    expect(stepLabel("UNKNOWN_STEP")).toBe("UNKNOWN_STEP");
    // 이력 상세 링크: 서버 links {stage:10, query:{opt}} → 최적화 상세
    expect(linkPath("p1", null, { stage: 10, query: { opt: "o-1" } })).toBe("/p/p1/opt/o-1");
  });

  it("서버 값: s1-check 사유(TOPOLOGY·MODEL_INFO_MISSING), zip parts = report,result,deck, 부분 결과 구분", () => {
    expect(MISMATCH_REASON.TOPOLOGY).toBeTruthy();
    expect(MISMATCH_REASON.MODEL_INFO_MISSING).toBe("모델 정보 없음");
    expect(MISMATCH_REASON.NO_TOPO).toBeUndefined();
    expect(opt.bundleUrl("r1")).toMatch(/\/opt\/runs\/r1\/bundle\?parts=report%2Cresult%2Cdeck$/);
    const sel = makeSelection([], "A", null, "abs");
    expect(isFullResult({ stage: "load", load_selection: sel })).toBe(false);
    expect(isFullResult(null)).toBe(false);
  });
});

const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const reasonOf = (b: HTMLButtonElement) => b.closest(".primary-wrap")?.getAttribute("title") ?? null;
const rowsOf = () => within(screen.getByRole("table", { name: "라이브러리 항목" })).getAllByRole("row").slice(1);
const box = (name: string) => screen.getByRole("checkbox", { name }) as HTMLInputElement;

describe("크기 규칙(화면, V-OR-1)", () => {
  it("ESL 간 ±2 %, 인치 다르면 불가, 템플릿 ±5 %·인치 선택", () => {
    const b = { inch: 75, L_xi: 1000, L_eta: 600 };
    expect(sameSize({ inch: 75, L_xi: 1019, L_eta: 600 }, b, 0.02)).toBe(true);
    expect(sameSize({ inch: 75, L_xi: 1021, L_eta: 600 }, b, 0.02)).toBe(false);
    expect(sameSize({ inch: 65, L_xi: 1000, L_eta: 600 }, b, 0.02)).toBe(false);
    expect(sameSize({ inch: null, L_xi: 1000, L_eta: 600 }, b, 0.02)).toBe(true); // 한쪽 인치 없음 → 치수만
    expect(templateMismatch({ inch: null, L_xi: 1049, L_eta: 600 }, [b], 0.05)).toBeNull();
    expect(templateMismatch({ inch: null, L_xi: 1051, L_eta: 600 }, [b], 0.05)).toMatch(/크기 차/);
    expect(templateMismatch({ inch: 65, L_xi: 1000, L_eta: 600 }, [b], 0.05)).toMatch(/인치 다름/);
  });
});

describe("라이브러리 목록 — 행 선택·모드 열·탭(§10.1)", () => {
  it("v0.10.0 선택 자유(폐기만 불가), 첫 선택 = 기준, 크기가 다르면 [비드 최적화] 비활성 사유, ⓜ 같은 모델 → 새 비드 최적화(S2 기본)", async () => {
    const { container } = renderApp("/p/p-body/library");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    expect(primaries(container)).toHaveLength(0);
    fireEvent.click(box("75QN80H v072 146 선택"));
    expect(box("65QN80H v072 235 선택").disabled).toBe(false); // 체크는 자유
    // ⓜ: 기준과 같은 모델(topo) 행만
    const row = (label: string) => box(label).closest("tr")!;
    expect(row("75QN80H v072 14 선택").querySelector(".mm-mark")).toBeTruthy();
    expect(row("75QN80H v073 146 선택").querySelector(".mm-mark")).toBeNull();
    fireEvent.click(box("75QN80H v072 14 선택"));
    fireEvent.click(box("75QN80H v072 3 선택"));
    expect(screen.getByTestId("pick-bar").textContent).toMatch(/선택 3개 · 기준 75형 1660×947 · 같은 모델 3\/3/);
    // 다른 크기를 넣으면 비드 최적화·강성 평가 비활성(사유), 내보내기·종합분석은 가능
    fireEvent.click(box("65QN80H v072 235 선택"));
    const optBtn = () => screen.getByRole("button", { name: /^비드 최적화 \(/ }) as HTMLButtonElement;
    await waitFor(() => expect(optBtn().disabled).toBe(true));
    expect(optBtn().parentElement!.title).toMatch(/크기 다름\(기준 75형/);
    expect((screen.getByRole("button", { name: "종합분석 (4)" }) as HTMLButtonElement).disabled).toBe(false);
    expect((primaries(container)[0] as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(box("65QN80H v072 235 선택"));
    fireEvent.click(box("75QN80H v073 146 선택"));
    expect(screen.getByTestId("pick-bar").textContent).toMatch(/같은 모델 3\/4/);
    // 주 버튼은 [내보내기] 1개(비드 최적화는 보조 버튼)
    expect(primaries(container).map((b) => b.textContent)).toEqual(["내보내기 (4)"]);
    fireEvent.click(screen.getByRole("button", { name: "비드 최적화 (4)" }));
    expect(await screen.findByRole("heading", { level: 1, name: "새 비드 최적화" })).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("tab", { name: "템플릿(S2)" }).getAttribute("aria-selected")).toBe("true"));
  });

  it("크기 허용 = /opt/settings size.tol_rel(하드코딩 없음): 허용을 줄이면 같은 75형도 치수 차로 비활성", async () => {
    resetOptSettingsCache();
    renderApp("/p/p-body/library", "power", (s: MockServer) => {
      s.opt.settings.size.tol_rel = 0.0005;
    });
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    fireEvent.click(box("75QN80H v072 146 선택"));
    fireEvent.click(box("75QN80H v073 146 선택"));
    // 목 치수는 항목 순서별 ±0.15 % — 허용 0.05 % 면 75형끼리도 일부는 '크기 다름'
    const optBtn = () => screen.getByRole("button", { name: "비드 최적화 (2)" }) as HTMLButtonElement;
    await waitFor(() => expect(optBtn().disabled).toBe(true));
    expect(optBtn().parentElement!.title).toMatch(/크기 다름/);
    resetOptSettingsCache();
  });

  it("모드 드롭다운: 자동 = 회색, 바꾸면 PATCH 저장 → 굵게, '자동으로' 되돌림 · 모드 필터", async () => {
    const { server } = renderApp("/p/p-body/library");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    const sel = () => screen.getByRole("combobox", { name: "75QN80H v072 146 모드" }) as HTMLSelectElement;
    expect(sel().className).toBe("mode-auto");
    expect(sel().selectedOptions[0].textContent).toBe("굽힘");
    fireEvent.change(sel(), { target: { value: "dent" } });
    await waitFor(() => expect(server.entries.find((e) => e.id === "le-1")!.deform_mode!.user).toBe("dent"));
    await waitFor(() => expect(sel().className).toBe("mode-user"));
    expect(sel().value).toBe("dent");
    fireEvent.change(sel(), { target: { value: "" } });
    await waitFor(() => expect(server.entries.find((e) => e.id === "le-1")!.deform_mode!.user).toBeNull());
    expect(server.entries.find((e) => e.id === "le-1")!.deform_mode!.effective).toBe("bend");
    fireEvent.change(screen.getByRole("combobox", { name: "모드 필터" }), { target: { value: "dent" } });
    await waitFor(() => expect(rowsOf().length).toBeGreaterThan(0));
    await waitFor(() => expect(rowsOf().every((r) => /덴팅/.test(r.textContent ?? ""))).toBe(true));
  });

  it("조회 사용자: 모드 수정·비드 최적화 비활성", async () => {
    renderApp("/p/p-body/library", "general");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    expect((screen.getByRole("combobox", { name: "75QN80H v072 146 모드" }) as HTMLSelectElement).disabled).toBe(true);
    fireEvent.click(box("75QN80H v072 146 선택"));
    expect((screen.getByRole("button", { name: "비드 최적화 (1)" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("비드 최적화 탭: 목록 → 상세 / 템플릿 탭: 주 버튼 = 템플릿 등록, 삭제 권한·사용 중 보관", async () => {
    const { container, server } = renderApp("/p/p-body/library");
    fireEvent.click(await screen.findByRole("tab", { name: "비드 최적화" }));
    const tbl = await screen.findByRole("table", { name: "비드 최적화 목록" });
    expect(within(tbl).getByText("75형 강건 비드 1차")).toBeTruthy();
    expect(within(tbl).getByText(/목적 1\.00→0\.71/)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "템플릿" }));
    const tt = await screen.findByRole("table", { name: "템플릿 목록" });
    expect(primaries(container).map((b) => b.textContent)).toEqual(["템플릿 등록"]);
    const r1 = within(tt).getByText("75형 평판 v1").closest("tr")!;
    const r2 = within(tt).getByText("65형 평판 v2").closest("tr")!;
    expect(within(r2).queryByRole("button", { name: "삭제" })).toBeNull(); // 관리자 등록 — 김해석은 삭제 불가
    fireEvent.click(within(r1).getByRole("button", { name: "삭제" }));
    fireEvent.click(within(r1).getByRole("button", { name: "보관" }));
    expect(await screen.findByText(/보관됨 — 이전 실행이 참조 중/)).toBeTruthy();
    expect(server.opt.templates.find((t) => t.id === "tpl-1")!.status).toBe("ARCHIVED");
    await waitFor(() => expect(within(screen.getByRole("table", { name: "템플릿 목록" })).queryByText("75형 평판 v1")).toBeNull());
  });

  it("템플릿 등록: 파일 → 청크 업로드 → 자동 검사(경고) → 제목·인치 → 등록", async () => {
    const { server } = renderApp("/p/p-body/library?tab=templates");
    fireEvent.click(await screen.findByRole("button", { name: "템플릿 등록" }));
    const panel = screen.getByTestId("template-register");
    const file = new File([new Uint8Array(2048)], "plate75.fem");
    fireEvent.change(within(panel).getByLabelText("템플릿 파일"), { target: { files: [file] } });
    const chk = await screen.findByTestId("template-check", undefined, { timeout: 4000 });
    expect(chk.textContent).toMatch(/fem · plate75\.fem .*검사 오류 0 경고 1/);
    expect((within(panel).getByRole("textbox", { name: "템플릿 제목" }) as HTMLInputElement).value).toBe("plate75");
    fireEvent.change(within(panel).getByRole("spinbutton", { name: "템플릿 인치" }), { target: { value: "75" } });
    fireEvent.click(within(panel).getByRole("button", { name: "등록" }));
    expect(await screen.findByText("'plate75' 등록됨")).toBeTruthy();
    expect(server.opt.templates[0]).toMatchObject({ title: "plate75", inch: 75, format: "fem", created_by_name: "김해석" });
  });
});

const S1 = "/p/p-body/opt/new?entries=le-1,le-2,le-3";

describe("새 비드 최적화(§10.3)", () => {
  it("기본값: S1 탭, 비드 45·60·10, 전략 A·목표 절대(추천 배지), k 는 C 만, B 모드 수, 주 버튼 1개", async () => {
    const { container } = renderApp(S1);
    await waitFor(() => expect(screen.getByRole("tab", { name: "기존 형상(S1)" }).getAttribute("aria-selected")).toBe("true"));
    expect((screen.getByRole("spinbutton", { name: "비드 경사 (°)" }) as HTMLInputElement).value).toBe("45");
    expect((screen.getByRole("spinbutton", { name: "비드 폭 (mm)" }) as HTMLInputElement).value).toBe("60");
    expect((screen.getByRole("spinbutton", { name: "비드 높이 (mm)" }) as HTMLInputElement).value).toBe("10");
    const strat = screen.getByRole("radiogroup", { name: "하중 선정 전략" });
    const radio = (g: HTMLElement, v: string) => within(g).getAllByRole("radio").find((r) => (r as HTMLInputElement).value === v) as HTMLInputElement;
    expect(radio(strat, "A").checked).toBe(true);
    expect(radio(strat, "A").closest("label")!.textContent).toMatch(/추천/);
    expect(radio(strat, "B").closest("label")!.textContent).toMatch(/현재 2개 \(덴팅 \(제외\) · 뒤틀림 2 · 굽힘 1\)/);
    const norm = screen.getByRole("radiogroup", { name: "목표 기준" });
    expect(radio(norm, "abs").checked).toBe(true);
    expect(radio(norm, "abs").closest("label")!.textContent).toMatch(/추천/);
    const k = screen.getByRole("spinbutton", { name: "군집 수 k" }) as HTMLInputElement;
    expect(k.disabled).toBe(true);
    expect(k.value).toBe("5");
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    expect(primaries(container).map((b) => b.textContent)).toEqual(["최적화 실행"]);
    fireEvent.click(radio(strat, "C"));
    expect(k.disabled).toBe(false);
    fireEvent.change(k, { target: { value: "0" } });
    expect(reasonOf(primaries(container)[0])).toBe("k 는 1~20 정수입니다");
    fireEvent.change(k, { target: { value: "21" } });
    expect(primaries(container)[0].disabled).toBe(true);
    fireEvent.change(k, { target: { value: "3" } });
    expect(primaries(container)[0].disabled).toBe(false);
    fireEvent.change(screen.getByRole("spinbutton", { name: "비드 경사 (°)" }), { target: { value: "95" } });
    expect(reasonOf(primaries(container)[0])).toMatch(/경사/);
    // 같은 모델 표시
    expect(within(screen.getByRole("table", { name: "선택한 ESL" })).getAllByText("같은 모델 ✓")).toHaveLength(3);
    // 설계 PID 전부 빼면 실행 불가
    fireEvent.change(screen.getByRole("spinbutton", { name: "비드 경사 (°)" }), { target: { value: "45" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "PID 1 설계" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "PID 2 설계" }));
    expect(reasonOf(primaries(container)[0])).toMatch(/설계 PID/);
  });

  it("ⓘ 팝오버: 요약 3줄·전략별 한 줄(현재 굵게)·목표 기준·출처 링크 새 탭, Esc 로 닫고 버튼에 초점", async () => {
    renderApp(S1);
    const btn = await screen.findByRole("button", { name: "방법·출처" });
    await waitFor(() => expect((btn as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(btn);
    const dlg = screen.getByRole("dialog", { name: "방법·출처" });
    expect(within(dlg).getByText("각 ESL(t* 한 시점)을 하중 케이스 1개로 씁니다.")).toBeTruthy();
    expect(within(dlg).getByText(/부호와 무관해 반대 방향 하중/)).toBeTruthy();
    const cur = dlg.querySelectorAll("[data-current]");
    expect([...cur].map((x) => x.textContent)).toEqual([expect.stringMatching(/^A KIT 식/), expect.stringMatching(/^절대 기준\(추천\)/)]);
    expect(within(dlg).getByText(/모드 대표: 덴팅·뒤틀림·굽힘별 최악/)).toBeTruthy();
    const links = within(dlg).getAllByRole("link");
    expect(links).toHaveLength(2);
    for (const a of links) {
      expect(a.getAttribute("target")).toBe("_blank");
      expect(a.getAttribute("rel")).toBe("noopener noreferrer");
    }
    expect(within(dlg).getByText(/Park, G\.J\./)).toBeTruthy();
    fireEvent.keyDown(dlg, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "방법·출처" })).toBeNull();
    expect(document.activeElement).toBe(btn);
  });

  it("S1 다른 모델: ✗ 표시·실행 비활성 사유 → [다른 모델 빼기] → 실행 가능, 템플릿 안내", async () => {
    const { container } = renderApp("/p/p-body/opt/new?entries=le-1,le-9,le-2");
    await waitFor(() => expect(screen.getByRole("tab", { name: "템플릿(S2)" }).getAttribute("aria-selected")).toBe("true"));
    fireEvent.click(screen.getByRole("tab", { name: "기존 형상(S1)" }));
    expect(await screen.findByText("다른 모델 ✗")).toBeTruthy();
    expect(reasonOf(primaries(container)[0])).toMatch(/다른 모델 ESL 1개/);
    expect(screen.getByRole("button", { name: "템플릿 최적화" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "다른 모델 빼기" }));
    await waitFor(() => expect(within(screen.getByRole("table", { name: "선택한 ESL" })).getAllByRole("row")).toHaveLength(3));
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    expect(screen.queryByText("다른 모델 ✗")).toBeNull();
  });

  it("S2: 크기 맞는 템플릿만 고를 수 있음, 크기 다른 ESL 은 실행 비활성", async () => {
    const { container } = renderApp("/p/p-body/opt/new?entries=le-1,le-9&tab=S2");
    const sel = (await screen.findByRole("combobox", { name: "템플릿" })) as HTMLSelectElement;
    await waitFor(() => expect(sel.value).toBe("tpl-1"));
    const opt65 = [...sel.options].find((o) => o.value === "tpl-2")!;
    expect(opt65.disabled).toBe(true);
    expect(opt65.textContent).toMatch(/인치 다름/);
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    // 65형 ESL 을 섞으면
    renderApp("/p/p-body/opt/new?entries=le-1,le-4&tab=S2");
    await waitFor(() => expect(screen.getAllByText("크기 다름 ✗").length).toBe(1));
    const ps = [...document.querySelectorAll("button[data-primary]")];
    const p = ps[ps.length - 1] as HTMLButtonElement;
    expect(reasonOf(p)).toMatch(/크기가 다른 ESL 1개/);
  });

  it("솔버 미설정: 상단 경고 띠 + 비활성 사유 / 모드 분류 없음: 전략 B 비활성", async () => {
    const { container } = renderApp(S1, "power", (s: MockServer) => {
      s.opt.settings.solver_ready = false;
      for (const e of s.entries) e.deform_mode = { auto: null, user: null, effective: null };
    });
    expect((await screen.findAllByText(/서버 OptiStruct 경로가 설정되지 않았습니다/)).length).toBeGreaterThan(0);
    await waitFor(() => expect(reasonOf(primaries(container)[0])).toMatch(/OptiStruct 경로/));
    const strat = await screen.findByRole("radiogroup", { name: "하중 선정 전략" });
    const b = within(strat).getAllByRole("radio").find((r) => (r as HTMLInputElement).value === "B") as HTMLInputElement;
    expect(b.disabled).toBe(true);
  });

  it("실행: 전략·목표 기준·k·비드·금지 영역 스냅샷을 POST → 상세(하중·선정 전)", async () => {
    const { container, server } = renderApp(S1);
    await waitFor(() => expect(screen.getByTestId("keepout-status").textContent).toMatch(/불러옴/));
    const strat = screen.getByRole("radiogroup", { name: "하중 선정 전략" });
    fireEvent.click(within(strat).getAllByRole("radio")[2]);
    fireEvent.change(screen.getByRole("spinbutton", { name: "군집 수 k" }), { target: { value: "2" } });
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "목표 기준" })).getAllByRole("radio")[1]);
    fireEvent.change(screen.getByRole("textbox", { name: "제목" }), { target: { value: "  2차 " } });
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false));
    fireEvent.click(primaries(container)[0]);
    expect(await screen.findByRole("heading", { level: 1, name: "비드 최적화" })).toBeTruthy();
    const run = server.opt.runs[server.opt.runs.length - 1];
    expect(run).toMatchObject({ scenario: "S1", title: "2차", load_strategy: "C", k: 2, objective_norm: "rel", entry_ids: ["le-1", "le-2", "le-3"] });
    expect(run.design.bead).toEqual({ angle: 45, min_width: 60, height: 10 });
    expect(run.design.keepout).toEqual({ rects: [{ name: "PCB", corner: "a0b0", x_mm: 120, y_mm: 80, w_mm: 300, h_mm: 200 }], auto: { hole: true, edge: true } });
    expect(server.jobs[server.jobs.length - 1]).toMatchObject({ job_type: "OPT_RUN", stage: 10, params: { opt_run_id: run.id } });
    expect(await screen.findByText("하중·선정 단계가 끝나면 보입니다")).toBeTruthy();
    expect(reasonOf(primaries(container)[0])).toBe("최적화가 끝나면 볼 수 있습니다");
  });
});

describe("최적화 상세(§10.4)", () => {
  it("하중 선정 표(병합 대상·MAC·반대 방향·전략·목표 기준), 결과·받기, 보고서 주 버튼", async () => {
    const { container } = renderApp("/p/p-body/opt/opt-1");
    expect((await screen.findAllByText("75형 강건 비드 1차")).length).toBeGreaterThan(0);
    const sum = await screen.findByTestId("selection-summary");
    expect(sum.textContent).toMatch(/^전략 A 전부 넣기 · 목표 절대\(C_ref 1\.40e4\) · ESL 3 → 케이스 2 \(병합 1, 군집 없음\)$/);
    const t = screen.getByRole("table", { name: "하중 선정" });
    const rows = within(t).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-status"))).toEqual(["included", "included", "merged"]);
    expect(rows[0].textContent).toMatch(/포함 L01.*75QN80H v072 · 17 Corner 146.*굽힘/);
    expect(rows[2].textContent).toMatch(/병합됨.*→ L02 \(MAC 0\.96, 반대 방향\)/);
    const steps = screen.getByRole("list", { name: "최적화 단계" });
    expect(within(steps).getAllByRole("listitem").map((l) => l.textContent)).toEqual(["✓ 대상 준비", "✓ 하중·선정", "✓ 덱 생성", "✓ OptiStruct", "✓ 후처리", "✓ 등록"]);
    expect(within(screen.getByRole("table", { name: "케이스별 컴플라이언스" })).getAllByRole("row")).toHaveLength(3);
    expect(screen.getByRole("img", { name: "수렴 그래프" })).toBeTruthy();
    expect(screen.getByRole("link", { name: ".rad" }).getAttribute("href")).toBe("/esl/api/opt/runs/opt-1/download?rel=post%2Fbead_mesh.rad");
    expect(screen.getByRole("link", { name: ".fem" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "결과 받기(zip)" })).toBeTruthy();
    expect(primaries(container).map((b) => [b.textContent, b.disabled])).toEqual([["보고서 보기", false]]);
    // ⓘ 는 상세 표에도 같은 팝오버(실행값 굵게)
    const btn = screen.getByRole("button", { name: "방법·출처" });
    await waitFor(() => expect((btn as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(btn);
    expect(screen.getByRole("dialog", { name: "방법·출처" }).querySelectorAll("[data-current]")).toHaveLength(2);
  });

  it("실패 확인 파일: 덱 .fem·.inc, solve/ .out·os_errors.txt·solve.json 만(tmp·h3d 제외)", () => {
    const f = (rel: string) => ({ rel, kind: rel.split("/")[0] as "deck", size: 1, downloadable: true });
    const rels = ["deck/esl_bead.fem", "deck/esl_loads.inc", "deck/README.txt", "solve/esl_bead.out", "solve/os_errors.txt",
      "solve/solve.json", "solve/esl_bead_des.h3d", "solve/tmp/x.out", "report.html"];
    expect(failureFiles(rels.map(f)).map((x) => x.rel)).toEqual(["deck/esl_bead.fem", "deck/esl_loads.inc", "solve/esl_bead.out",
      "solve/os_errors.txt", "solve/solve.json"]);
  });

  it("목표 기준·전략별 선정(목 선정기): abs 는 POS 모두 C_ref, rel 은 각자 C⁰ / B 모드 대표 / C k 군집", () => {
    const s = new MockServer();
    const es = s.entries.filter((e) => ["le-1", "le-2", "le-3", "le-9", "le-10", "le-11"].includes(e.id));
    const abs = makeSelection(es, "A", null, "abs");
    const sel = abs.rows.filter((r) => r.label);
    expect(new Set(sel.map((r) => r.pos))).toEqual(new Set([abs.C_ref]));
    expect(abs.C_ref).toBe(Math.max(...sel.map((r) => r.C0)));
    const rel = makeSelection(es, "A", null, "rel");
    expect(rel.rows.filter((r) => r.label).every((r) => r.pos === r.C0)).toBe(true);
    expect(rel.C_ref).toBeNull();
    const b = makeSelection(es, "B", null, "abs");
    expect(b.rows.filter((r) => r.status === "mode_rep").length).toBeLessThanOrEqual(3);
    const c = makeSelection(es, "C", 2, "abs");
    expect(c.clusters).toHaveLength(2);
    expect(c.rows.filter((r) => r.status === "cluster_rep")).toHaveLength(2);
  });
});
