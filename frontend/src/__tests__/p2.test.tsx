// P2 UI(계약 esl_p2_library.md §7.3·§11): ⑤ 겹쳐보기·단면선·최대변형률 비교·라이브러리 등록, 라이브러리 목록·분석 생성·상세.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "../app/App";
import { MockServer, createMockFetch } from "../mock/server";
import { REPORT_MISSING } from "../components/ReportLink";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { NO_PERMISSION } from "../app/AppContext";
import { cellColor, isGrey } from "../components/FieldOverlay";
import { DEFAULT_FORM, validateForm } from "../pages/library/AnalysisNew";
import { makeEntries } from "../mock/p2data";

const primaries = (container: HTMLElement) => container.querySelectorAll("button[data-primary]");
const STAGE5 = "/p/p-body/c/c-demo/stage/5";

describe("⑤ 겹쳐보기 색·회색 규칙", () => {
  const rng = { min: 0, max: 0.2 };
  it("rad·esl: HOLD·EXCLUDED·NO_PREV·null 은 회색, LOW 는 색", () => {
    expect(isGrey("rad", 0.1, "HOLD")).toBe(true);
    expect(isGrey("esl", 0.1, "NO_PREV")).toBe(true);
    expect(isGrey("rad", null, "OK")).toBe(true);
    expect(isGrey("rad", 0.01, "LOW")).toBe(false);
    expect(cellColor("rad", 0.1, "OK", rng)).toMatch(/^rgb\(/);
    expect(cellColor("rad", 0.1, "HOLD", rng)).toBeNull();
  });
  it("err: OK 외(LOW 포함) 전부 회색, 0% 는 발산 색 중앙(노랑)", () => {
    expect(isGrey("err", 5, "LOW")).toBe(true);
    expect(cellColor("err", 0, "OK", { min: -20, max: 20 })).toBe("rgb(240,228,140)");
    // 범위 밖은 끝 색
    expect(cellColor("err", 99, "OK", { min: -20, max: 20 })).toBe("rgb(165,0,38)");
    // 공통 범위: 같은 값이면 같은 색
    expect(cellColor("rad", 0.15, "OK", rng)).toBe(cellColor("esl", 0.15, "OK", rng));
  });
});

describe("⑤ 검증 화면 P2", () => {
  it("최대변형률 비교 수치·분위수·히스토그램·FIELD 사유·보고서 링크, 주 버튼 1개 유지", async () => {
    const { container } = renderApp(STAGE5);
    const sc = await screen.findByTestId("strain-compare");
    expect(within(sc).getByText("최대 ε (Radioss)")).toBeTruthy();
    expect(within(sc).getByText("기준 ≤ 10%")).toBeTruthy();
    expect(within(sc).getByText("기준 ≤ 20%")).toBeTruthy();
    expect(screen.getByText(/FIELD_MAX_ERR — 최대변형률 요소의 ESL 오차가 기준 초과/)).toBeTruthy();
    expect(screen.getByRole("table", { name: "오차 분위수" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "오차 히스토그램" })).toBeTruthy();
    const rep = screen.getByRole("link", { name: "보고서 보기" });
    expect(rep.getAttribute("href")).toBe("/esl/api/cases/c-demo/report");
    expect(rep.getAttribute("target")).toBe("_blank");
    await waitFor(() => expect(primaries(container).length).toBe(1));
    expect(primaries(container)[0].textContent).toBe("검증 실행");
  });

  it("겹쳐보기: 레이어 전환·불투명도 슬라이더·회색 수·hotspot 표식", async () => {
    renderApp(STAGE5);
    const layer = await screen.findByRole("group", { name: "레이어" });
    await screen.findByTestId("ovl-box");
    const btn = (n: string) => within(layer).getByRole("button", { name: n });
    const slider = screen.getByRole("slider", { name: "ESL 불투명도" }) as HTMLInputElement;
    const esl = screen.getByTestId("ovl-esl") as HTMLCanvasElement;
    // 기본: Radioss, ESL 캔버스 숨김
    expect(btn("Radioss ε").getAttribute("aria-pressed")).toBe("true");
    expect(esl.style.visibility).toBe("hidden");
    const greyEps = Number(screen.getByTestId("grey-count").textContent!.replace(/,/g, ""));
    expect(greyEps).toBeGreaterThan(0);
    // 슬라이더 40% → 두 레이어 겹침(어느 레이어 버튼도 눌리지 않음)
    fireEvent.change(slider, { target: { value: "40" } });
    expect(esl.style.opacity).toBe("0.4");
    expect(esl.style.visibility).toBe("visible");
    expect(screen.getByTestId("ovl-op").textContent).toBe("40%");
    expect(btn("Radioss ε").getAttribute("aria-pressed")).toBe("false");
    expect(btn("ESL ε").getAttribute("aria-pressed")).toBe("false");
    // ESL 버튼 → 100%
    fireEvent.click(btn("ESL ε"));
    expect(slider.value).toBe("100");
    expect(esl.style.opacity).toBe("1");
    // 오차 레이어: 슬라이더 비활성, ESL 캔버스 숨김, 회색 증가(LOW 도 회색), 발산 범례
    fireEvent.click(btn("오차 %"));
    expect(slider.disabled).toBe(true);
    expect(esl.style.visibility).toBe("hidden");
    const greyErr = Number(screen.getByTestId("grey-count").textContent!.replace(/,/g, ""));
    expect(greyErr).toBeGreaterThan(greyEps);
    expect(screen.getByTestId("ovl-legend").textContent).toContain("오차 %");
    // 표식: hotspot 3개 + 최대변형률 요소
    expect(screen.getAllByTestId("hotspot-marker")).toHaveLength(3);
    expect(screen.getByTestId("max-marker")).toBeTruthy();
  });

  it("단면선: ξ/η 전환, 초기·Radioss·ESL 선, 배율 슬라이더", async () => {
    renderApp(STAGE5);
    const seg = await screen.findByRole("group", { name: "단면" });
    await screen.findByTestId("sec-rad");
    expect(screen.getByTestId("sec-init")).toBeTruthy();
    expect(screen.getByTestId("sec-esl")).toBeTruthy();
    const k = screen.getByRole("slider", { name: "변형 배율" }) as HTMLInputElement;
    const d0 = screen.getByTestId("sec-rad").getAttribute("d");
    fireEvent.change(k, { target: { value: "2" } });
    expect(screen.getByTestId("sec-k").textContent).toBe("×100");
    expect(screen.getByTestId("sec-rad").getAttribute("d")).not.toBe(d0);
    fireEvent.click(within(seg).getByRole("button", { name: "η = 0.5" }));
    expect(within(seg).getByRole("button", { name: "η = 0.5" }).getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(screen.getByRole("img", { name: "단면선" }).textContent).toContain("ξ (PCA 평면, mm)"));
  });

  it("라이브러리 등록: FAIL 이면 사유 대화상자 → 확정 등록 → '등록됨'", async () => {
    const { server } = renderApp(STAGE5);
    fireEvent.click(await screen.findByRole("button", { name: "라이브러리 등록" }));
    const dlg = screen.getByRole("dialog");
    const ok = within(dlg).getByRole("button", { name: "확정 등록" }) as HTMLButtonElement;
    expect(ok.disabled).toBe(true);
    expect(within(dlg).getByText(/FIELD_MAX_ERR/)).toBeTruthy();
    fireEvent.change(within(dlg).getByRole("textbox", { name: /확정 사유/ }), { target: { value: "누적 소성 — 오차 확인" } });
    expect(ok.disabled).toBe(false);
    fireEvent.click(ok);
    expect(await screen.findByText("라이브러리 등록됨")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    const e = server.entries.find((x) => x.esl_run_id === "run-1")!;
    expect(e.force_reason).toBe("누적 소성 — 오차 확인");
    expect(e.quality.verdict).toBe("FAIL");
  });

  it("보고서가 없으면(GET /cases/{id}/report 404) '보고서 보기' 비활성 + 사유", async () => {
    const server = new MockServer({ user: "power" });
    const orig = server.handle.bind(server);
    server.handle = (m, p, q, b) => (/\/report$/.test(p) ? { status: 404, body: { detail: { code: "REPORT_NOT_FOUND", message: "없음" } } } : orig(m, p, q, b));
    globalThis.fetch = createMockFetch(server);
    render(
      <MemoryRouter initialEntries={[STAGE5]}>
        <App />
      </MemoryRouter>,
    );
    await screen.findByTestId("strain-compare");
    const b = (await screen.findByRole("button", { name: "보고서 보기" })) as HTMLButtonElement;
    expect(b.disabled).toBe(true);
    expect(b.parentElement!.getAttribute("title")).toBe(REPORT_MISSING);
    expect(screen.queryByRole("link", { name: "보고서 보기" })).toBeNull();
  });

  it("라이브러리 등록: 대화상자 취소, 조회 사용자 비활성", async () => {
    const { unmount } = renderApp(STAGE5);
    fireEvent.click(await screen.findByRole("button", { name: "라이브러리 등록" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "취소" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    unmount();
    renderApp(STAGE5, "general");
    const b = (await screen.findByRole("button", { name: "라이브러리 등록" })) as HTMLButtonElement;
    expect(b.disabled).toBe(true);
    expect(b.parentElement!.getAttribute("title")).toBe(NO_PERMISSION);
  });
});

describe("전역 메뉴 '라이브러리'", () => {
  it("Case 화면 상단 바에 1개, 누르면 라이브러리 목록", async () => {
    renderApp(STAGE5);
    const menu = await screen.findByRole("navigation", { name: "전역 메뉴" });
    expect(within(menu).getAllByRole("link")).toHaveLength(1);
    fireEvent.click(within(menu).getByRole("link", { name: "라이브러리" }));
    expect(await screen.findByRole("heading", { level: 1, name: "라이브러리" })).toBeTruthy();
    expect(within(screen.getByRole("navigation", { name: "전역 메뉴" })).getByRole("link", { name: "라이브러리" }).getAttribute("aria-current")).toBe("page");
  });
});

describe("라이브러리 목록", () => {
  const rowsOf = () => within(screen.getByRole("table", { name: "라이브러리 항목" })).getAllByRole("row").slice(1);

  it("표·필터(모델·판정·폐기 포함), 주 버튼 1개", async () => {
    const { container } = renderApp("/p/p-body/library");
    await waitFor(() => expect(rowsOf()).toHaveLength(7)); // ACTIVE 7개
    expect(primaries(container)).toHaveLength(1);
    expect(primaries(container)[0].textContent).toBe("종합분석 만들기");
    fireEvent.change(screen.getByRole("combobox", { name: "모델" }), { target: { value: "65QN80H" } });
    await waitFor(() => expect(rowsOf()).toHaveLength(2));
    fireEvent.change(screen.getByRole("combobox", { name: "판정" }), { target: { value: "FAIL" } });
    await waitFor(() => expect(rowsOf()).toHaveLength(1));
    expect(within(rowsOf()[0]).getByText("FAIL")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "필터 지우기" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /폐기 포함/ }));
    await waitFor(() => expect(rowsOf()).toHaveLength(8));
    expect(screen.getByText("폐기")).toBeTruthy();
    // 씬 유형 필터
    fireEvent.change(screen.getByRole("combobox", { name: "씬 유형" }), { target: { value: "Corner" } });
    await waitFor(() => expect(rowsOf()).toHaveLength(3));
  });

  it("메타 수정(제품 질량) 저장·폐기", async () => {
    const { server } = renderApp("/p/p-body/library");
    await waitFor(() => expect(rowsOf()).toHaveLength(7));
    const row85 = rowsOf().find((r) => r.textContent!.includes("85QN80H") && r.textContent!.includes("Scene 2 "))!;
    fireEvent.click(within(row85).getByRole("button", { name: "수정" }));
    const edit = screen.getByTestId("edit-row");
    const mass = within(edit).getByRole("spinbutton", { name: "제품 질량 (kg)" });
    fireEvent.change(mass, { target: { value: "-3" } });
    expect((within(edit).getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(mass, { target: { value: "52.4" } });
    fireEvent.click(within(edit).getByRole("button", { name: "저장" }));
    await waitFor(() => expect(server.entries.find((e) => e.id === "le-6")!.model.product_mass).toBe(52.4));
    expect(await screen.findByText("52.4 kg")).toBeTruthy();
    // 폐기
    const row = rowsOf().find((r) => r.textContent!.includes("52.4 kg"))!;
    fireEvent.click(within(row).getByRole("button", { name: "수정" }));
    fireEvent.click(within(screen.getByTestId("edit-row")).getByRole("button", { name: "폐기…" }));
    fireEvent.click(within(screen.getByTestId("edit-row")).getByRole("button", { name: "폐기" }));
    await waitFor(() => expect(server.entries.find((e) => e.id === "le-6")!.status).toBe("RETIRED"));
    await waitFor(() => expect(rowsOf()).toHaveLength(6));
  });

  it("조회 사용자: 종합분석 만들기·수정 비활성", async () => {
    const { container } = renderApp("/p/p-body/library", "general");
    await waitFor(() => expect(rowsOf()).toHaveLength(7));
    await waitFor(() => expect((primaries(container)[0] as HTMLButtonElement).disabled).toBe(true));
    expect((within(rowsOf()[0]).getByRole("button", { name: "수정" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("종합분석 만들기", () => {
  it("폼 검증(순수 함수): 대표 수·정규화 질량 누락·필터 0개", () => {
    const es = makeEntries("p-body");
    expect(validateForm(DEFAULT_FORM, es).reason).toBeNull();
    expect(validateForm({ ...DEFAULT_FORM, nRep: "0" }, es).reason).toMatch(/대표 케이스 수/);
    expect(validateForm({ ...DEFAULT_FORM, nRep: "2.5" }, es).reason).toMatch(/대표 케이스 수/);
    expect(validateForm({ ...DEFAULT_FORM, svdEnergy: "1.5" }, es).reason).toMatch(/SVD/);
    expect(validateForm({ ...DEFAULT_FORM, normalization: "mass" }, es).reason).toMatch(/제품 질량이 없는 항목 2개/);
    // 항목 질량은 다 있지만 대상 값 없음 → 설계 대상(질량 있음) 또는 고급 입력으로 해결
    expect(validateForm({ ...DEFAULT_FORM, normalization: "mass", model: "75QN80H" }, es).reason).toMatch(/대상 제품 질량이 필요/);
    expect(validateForm({ ...DEFAULT_FORM, normalization: "mass", model: "75QN80H", target: "le-1" }, es).reason).toBeNull();
    expect(validateForm({ ...DEFAULT_FORM, normalization: "mass", model: "75QN80H", targetMass: "41" }, es).reason).toBeNull();
    expect(validateForm({ ...DEFAULT_FORM, normalization: "mass", model: "75QN80H", targetMass: "-1" }, es).reason).toMatch(/대상 값/);
    expect(validateForm({ ...DEFAULT_FORM, normalization: "inch2" }, es).reason).toMatch(/대상 인치/);
    expect(validateForm({ ...DEFAULT_FORM, model: "65QN80H", verdict: "PASS", drops: ["Edge"] }, es).reason).toMatch(/항목이 없습니다/);
    expect(validateForm(DEFAULT_FORM, null).reason).toBe("불러오는 중…");
  });

  it("주 버튼 1개 '분석 실행', 잘못된 값이면 비활성 + 사유, 고급은 접힘, 실행 → 상세", async () => {
    const { container, server } = renderApp("/p/p-body/library/analyses/new");
    expect(await screen.findByRole("heading", { level: 1, name: "새 종합분석" })).toBeTruthy();
    expect(primaries(container)).toHaveLength(1);
    const run = primaries(container)[0] as HTMLButtonElement;
    expect(run.textContent).toBe("분석 실행");
    await waitFor(() => expect(run.disabled).toBe(false));
    expect(screen.getByText("포함 항목 6개")).toBeTruthy(); // ACTIVE 7 중 PASS 6
    expect((container.querySelector("details.adv") as HTMLDetailsElement).open).toBe(false);
    // 대표 수 0 → 비활성
    const n = screen.getByRole("spinbutton", { name: "대표 케이스 수" });
    fireEvent.change(n, { target: { value: "0" } });
    expect(run.disabled).toBe(true);
    expect(run.parentElement!.getAttribute("title")).toMatch(/대표 케이스 수/);
    fireEvent.change(n, { target: { value: "3" } });
    // 질량 정규화: 85QN80H 질량 없음 → 비활성, 모델 필터로 해결
    fireEvent.click(within(screen.getByRole("group", { name: "정규화" })).getByRole("button", { name: "질량" }));
    expect(run.disabled).toBe(true);
    expect(run.parentElement!.getAttribute("title")).toMatch(/제품 질량/);
    fireEvent.change(screen.getByRole("combobox", { name: "필터 모델" }), { target: { value: "75QN80H" } });
    expect(screen.getByText("포함 항목 3개")).toBeTruthy();
    expect(run.parentElement!.getAttribute("title")).toMatch(/대상 제품 질량이 필요/);
    fireEvent.change(screen.getByRole("combobox", { name: "설계 대상 모델" }), { target: { value: "le-1" } });
    expect(run.disabled).toBe(false);
    // 씬 유형 체크 해제 → 필터
    fireEvent.click(screen.getByRole("checkbox", { name: "면" }));
    expect(screen.getByText("포함 항목 2개")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "제목" }), { target: { value: "75형 강건 비드" } });
    fireEvent.click(run);
    expect(await screen.findByRole("heading", { level: 1, name: "종합분석" })).toBeTruthy();
    const a = server.analyses[server.analyses.length - 1];
    expect(a.target_entry_id).toBe("le-1");
    expect(a.title).toBe("75형 강건 비드");
    expect(a.filters).toEqual({ model: ["75QN80H"], drop_type: ["Corner", "Edge"], verdict: ["PASS"] });
    expect(a.options).toEqual({ normalization: "mass", n_representative: 3, objective: "minmax", svd_energy: 0.9, worst_case: false });
    expect(a.entry_ids).toEqual(["le-1", "le-2"]);
    // 진행 표시, 보고서 버튼은 끝나야 활성
    expect(await screen.findByTestId("job-progress")).toBeTruthy();
    expect((primaries(container)[0] as HTMLButtonElement).disabled).toBe(true);
    server.drain();
    expect(await screen.findByRole("table", { name: "대표 케이스" }, { timeout: 6000 })).toBeTruthy();
    await waitFor(() => expect((primaries(container)[0] as HTMLButtonElement).disabled).toBe(false));
  }, 12000);
});

describe("종합분석 상세", () => {
  it("요약·대표 케이스·포락 미니맵·파일(큰 파일은 경로 복사), 주 버튼 '보고서 보기' 1개", async () => {
    const { container } = renderApp("/p/p-body/library/analyses/an-1");
    const reps = await screen.findByRole("table", { name: "대표 케이스" });
    expect(within(reps).getAllByRole("row").slice(1)).toHaveLength(4);
    expect(within(reps).getByText("REP1")).toBeTruthy();
    // 포락 미니맵: envelope.csv(다운로드 API) 24×14 격자
    expect((await screen.findByRole("img", { name: "셀 합력 포락 미니맵" })).querySelectorAll("rect").length).toBe(24 * 14 + 1);
    expect(primaries(container)).toHaveLength(1);
    expect(primaries(container)[0].textContent).toBe("보고서 보기");
    expect((primaries(container)[0] as HTMLButtonElement).disabled).toBe(false);
    const files = await screen.findByRole("table", { name: "분석 파일" });
    expect(within(files).getByText("opt/esl_bead.fem")).toBeTruthy();
    const links = within(files).getAllByRole("link", { name: "다운로드" });
    expect(links.length).toBe(7);
    expect(links[0].getAttribute("href")).toBe("/esl/api/library/analyses/an-1/download?rel=report.html");
    expect(within(files).getByTestId("too-large").textContent).toContain("esl_bead.fem");
  });
});
