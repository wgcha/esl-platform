// V-LT-11(esl_load_transfer.md §7·§8): ④ 하중 전달 화면 — 고급 설정 select(선택지·기본 표기·요청 생략 규칙), 결과 요약 1줄·접힘 표(새 결과),
// legacy 결과 = 줄·표 없음, 3D 좌측 = view3d_ref·ESL 이름. 화면 크기(2560×1440·1920×1080)는 scripts 스크린샷으로 확인.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { ltChoiceLabel, ltKey, ltRequest, ltSummaryLine, ltVariantLabel, normalizeDoeSettings } from "../api/doe";
import type { DoeLoadTransferCfg } from "../api/types";
import { MockServer } from "../mock/server";

const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const radio = (name: RegExp | string) => screen.getByRole("radio", { name }) as HTMLInputElement;
const DROP = "비교할 STEP·메시 끌어다 놓기(여러 개)";
const file = (name: string) => new File([new Uint8Array(4096)], name);

async function openCompare(mut?: (s: MockServer) => void) {
  const r = renderApp("/p/p-body/doe/new?entries=le-1,le-2,le-9", "power", mut);
  await waitFor(() => expect(radio(/③ 다른 모델\(STEP만\)/).checked || radio(/① 같은 모델/).checked).toBe(true));
  fireEvent.click(radio(/④ 형상 직접 비교/));
  return r;
}
async function drop(names: string[], rows: number) {
  fireEvent.change(screen.getByLabelText(DROP), { target: { files: names.map((n) => file(n)) } });
  await waitFor(() => expect(screen.getByTestId(`shape-row-${rows}`)).toBeTruthy(), { timeout: 5000 });
}

const CFG: DoeLoadTransferCfg = { method: "work", cell_size_mm: null, cell_choices_mm: [null, 10, 5, 3], cell_min_mm: 3 };

describe("하중 전달 규칙(화면 쪽 함수)", () => {
  it("키·문구·요청 생략 규칙", () => {
    expect(ltKey("work", null)).toBe("work");
    expect(ltKey("cell", null)).toBe("cell:legacy");
    expect(ltKey("cell", 3)).toBe("cell:3");
    expect(ltVariantLabel("work")).toBe("일 등가");
    expect(ltVariantLabel("cell:legacy")).toBe("셀 기존 24×14");
    expect(ltVariantLabel("cell:3")).toBe("셀 3 mm");
    expect(ltChoiceLabel("work", null, { def: true })).toBe("일 등가(권장) (기본)");
    // 기본(work)과 같거나 선택 없음 = 요청에 안 넣음
    expect(ltRequest(CFG, null)).toEqual({});
    expect(ltRequest(CFG, "work")).toEqual({});
    // work 에는 cell_size_mm 을 붙이지 않음(422 LOAD_TRANSFER_INVALID), cell 은 크기(null = 기존 격자) 명시
    expect(ltRequest({ ...CFG, method: "cell", cell_size_mm: 5 }, "work")).toEqual({ load_transfer: "work" });
    expect(ltRequest(CFG, "cell:3")).toEqual({ load_transfer: "cell", cell_size_mm: 3 });
    expect(ltRequest(CFG, "cell:legacy")).toEqual({ load_transfer: "cell", cell_size_mm: null });
    expect(ltRequest({ ...CFG, method: "cell", cell_size_mm: 5 }, "cell:legacy")).toEqual({ load_transfer: "cell", cell_size_mm: null });
    expect(ltRequest(undefined, "cell:3")).toEqual({});
  });

  it("settings 보정: 옛 서버 = 키 없음, 새 서버 = 그대로", () => {
    expect(normalizeDoeSettings({})).not.toHaveProperty("load_transfer");
    // §13.6 최상위 칸(compare.load_transfer 는 이동되어 읽지 않음)
    expect(normalizeDoeSettings({ compare: { load_transfer: { method: "work" } } })).not.toHaveProperty("load_transfer");
    const n = normalizeDoeSettings({ load_transfer: { method: "work", cell_size_mm: null, cell_choices_mm: [null, 10, 3], cell_min_mm: 3 } });
    expect(n.load_transfer).toEqual({ method: "work", cell_size_mm: null, cell_choices_mm: [null, 10, 3], cell_min_mm: 3 });
  });

  it("요약 줄: 주 방식 + 다른 방식 최대 2개", () => {
    const line = ltSummaryLine({
      method: "work", cell_size_mm: null, support: "transfer", region_mode: "auto", alt: null, truth: "direct_nodal", rank_alt_same: true, warnings_n: 0,
      summary: [
        { variant: "work", umax_ratio: [1.01, 1.06], C_ratio: [0.98, 1.04], mac_min: 0.995, load_corr_min: 0.98 },
        { variant: "cell:3", umax_ratio: [1.4, 1.9], C_ratio: [1.3, 1.7], mac_min: 0.85, load_corr_min: 0.8 },
        { variant: "cell:10", umax_ratio: [8, 11], C_ratio: [6, 9], mac_min: 0.2, load_corr_min: 0.2 },
        { variant: "cell:5", umax_ratio: [3, 4], C_ratio: [2, 3], mac_min: 0.5, load_corr_min: 0.5 },
      ],
    });
    expect(line).toBe("하중 전달: 일 등가 · 기준 대비 ①: umax ×1.01~1.06 · C ×0.98~1.04 · MAC ≥ 0.99  |  셀 3 mm: umax ×1.40~1.90 · C ×1.30~1.70 · MAC ≥ 0.85  |  셀 10 mm: umax ×8.00~11.00 · C ×6.00~9.00 · MAC ≥ 0.20");
  });
});

describe("④ 새 연구 — 고급 설정 하중 전달 select", () => {
  it("기본 일 등가(기본 표기) · 선택지 순서 · 기본이면 요청 키 없음", async () => {
    const { container, server } = await openCompare();
    const adv = screen.getByTestId("compare-adv");
    expect(within(adv).getByText(/하중 일 등가/)).toBeTruthy();
    const sel = within(adv).getByTestId("lt-select") as HTMLSelectElement;
    expect([...sel.options].map((o) => o.textContent)).toEqual(["일 등가(권장) (기본)", "셀 기존 24×14", "셀 10 mm", "셀 5 mm", "셀 3 mm"]);
    expect(sel.value).toBe("work");
    await drop(["chr_base.step", "chr_rib_A.step"], 2);
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false), { timeout: 4000 });
    fireEvent.click(primaries(container)[0]);
    await screen.findByRole("heading", { level: 1, name: "강성 평가 스터디" });
    const rec = server.doe.recs[server.doe.recs.length - 1];
    // 해석된 기본 = work·transfer·auto(LT-11)
    expect(rec.out.inputs.load_transfer).toEqual({ method: "work", cell_size_mm: null, support: "transfer", region_mode: "auto" });
  }, 15000);

  it("셀 3 mm 선택 → 요청 load_transfer cell + cell_size_mm 3, 요약 줄 '· 하중 셀 3 mm'", async () => {
    const { container, server } = await openCompare();
    const sel = screen.getByTestId("lt-select") as HTMLSelectElement;
    fireEvent.change(sel, { target: { value: "cell:3" } });
    expect(within(screen.getByTestId("compare-adv")).getByText(/하중 셀 3 mm/)).toBeTruthy();
    await drop(["chr_base.step", "chr_rib_A.step"], 2);
    await waitFor(() => expect(primaries(container)[0].disabled).toBe(false), { timeout: 4000 });
    fireEvent.click(primaries(container)[0]);
    await screen.findByRole("heading", { level: 1, name: "강성 평가 스터디" });
    const rec = server.doe.recs[server.doe.recs.length - 1];
    expect(rec.out.inputs.load_transfer).toMatchObject({ method: "cell", cell_size_mm: 3 });
    await waitFor(() => expect(screen.getByTestId("doe-input-summary").textContent).toMatch(/· 하중 셀 3 mm/));
  }, 15000);

  it("메시 형상만이어도 고급 설정(하중 전달)은 보이고 메시 방식 줄은 숨김 · 옛 서버(설정 칸 없음)는 select 없음", async () => {
    await openCompare();
    await drop(["only_0000.rad", "x.inc"], 1);
    const adv = screen.getByTestId("compare-adv");
    expect(within(adv).getByTestId("lt-select")).toBeTruthy();
    expect(within(adv).queryByRole("radiogroup", { name: "메시 방식" })).toBeNull();
  }, 10000);

  it("옛 서버: settings 에 load_transfer 없음 → select 없음", async () => {
    await openCompare((s) => {
      delete s.doe.settings.load_transfer;
    });
    expect(screen.queryByTestId("lt-select")).toBeNull();
    expect(within(screen.getByTestId("compare-adv")).getByRole("radiogroup", { name: "메시 방식" })).toBeTruthy();
  }, 10000);
});

describe("④ 결과 — doe-20(하중 전달 work, 새 결과)", () => {
  it("요약 1줄 + 접힘 표 2개(진단 파일) + 입력 요약 '· 하중 일 등가'", async () => {
    renderApp("/p/p-body/doe/doe-20");
    const line = await screen.findByTestId("lt-summary");
    expect(line.textContent).toMatch(/^하중 전달: 일 등가 · 기준 대비 A 메시 직접 풀이: umax ×1\.03~1\.09 · C ×1\.02~1\.08/);
    expect(line.textContent).toMatch(/\|\s+셀 3 mm: umax ×/);
    expect(screen.getByTestId("doe-input-summary").textContent).toMatch(/· 하중 일 등가/);
    const det = screen.getByTestId("lt-details") as HTMLDetailsElement;
    expect(det.open).toBe(false);
    det.open = true;
    fireEvent(det, new Event("toggle"));
    const t1 = await screen.findByRole("table", { name: "하중 전달 베이스라인 참값 대비" });
    // 기준이 STEP → 참값 = A 직접, 상관·MAC = –
    const first = within(t1).getAllByRole("row")[1];
    expect(within(first).getAllByRole("cell").map((c) => c.textContent)).toEqual(["일 등가", "le-1", "–", "1.03", "1.02", "–"]);
    expect(within(t1).getAllByRole("row").length).toBe(1 + 5 * 3);
    const t2 = screen.getByRole("table", { name: "하중 전달 형상별" });
    expect(within(t2).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(["형상", "점수", "점수(다른 방식)", "먼 노드 최대", "지지"]);
    expect(within(t2).getAllByRole("row").length).toBe(1 + 3);
    expect(within(t2).getByText("자동(이전 실패)")).toBeTruthy();
  }, 15000);

  it("3D 비교: 좌측 = view3d_ref(같은 ESL), 두 카드 머리·안내에 ESL 이름", async () => {
    const { server } = renderApp("/p/p-body/doe/doe-20");
    const urls: string[] = [];
    const inner = globalThis.fetch;
    globalThis.fetch = (i, init) => (urls.push(typeof i === "string" ? i : i instanceof URL ? i.href : i.url), inner(i, init));
    await screen.findByTestId("lt-summary");
    const rec = server.doe.recs.find((r) => r.out.id === "doe-20")!;
    const res = rec.result!;
    expect(Object.keys(res.view3d_ref!).length).toBeGreaterThan(0);
    expect(res.view3d.some((d) => d.startsWith("d000_e"))).toBe(false);
    const did = res.view3d.filter((d) => d !== "d000")[0];
    const esl = res.view3d_esl![did];
    const label = res.esl!.find((e) => e.entry_id === esl)!.label;
    await waitFor(() => expect(screen.getByText(new RegExp(`ESL ${label}\\(선택 형상의 최악\\)`))).toBeTruthy());
    expect(screen.getAllByText(new RegExp(`· ESL ${label}$`)).length).toBeGreaterThanOrEqual(2);
    // 좌측 manifest = view3d_ref(d000_e<kk>) — 기본 d000 이 아님
    await waitFor(() => expect(urls.some((u) => new RegExp(`/view3d/${res.view3d_ref![esl]}/manifest\\.json`).test(u))).toBe(true));
    expect(urls.some((u) => /\/view3d\/d000\/manifest\.json/.test(u))).toBe(false);
  }, 15000);
});

describe("①②③ 공통 — 고급 설정 하중 전달(§13.8)", () => {
  async function openRadio(r: RegExp) {
    renderApp("/p/p-body/doe/new?entries=le-1,le-2,le-9");
    await waitFor(() => expect(radio(/① 같은 모델/)).toBeTruthy());
    fireEvent.click(radio(r));
  }
  it("①②③ 모두 고급 설정 칸에 같은 select, 메시 방식 줄은 ③ 만", async () => {
    await openRadio(/① 같은 모델/);
    let adv = screen.getByTestId("compare-adv");
    expect((within(adv).getByTestId("lt-select") as HTMLSelectElement).value).toBe("work");
    expect(within(adv).queryByRole("radiogroup", { name: "메시 방식" })).toBeNull();
    fireEvent.click(radio(/② 다른 모델\(B 메시\)/));
    adv = screen.getByTestId("compare-adv");
    expect(within(adv).getByTestId("lt-select")).toBeTruthy();
    expect(within(adv).queryByRole("radiogroup", { name: "메시 방식" })).toBeNull();
    fireEvent.click(radio(/③ 다른 모델\(STEP만\)/));
    adv = screen.getByTestId("compare-adv");
    expect(within(adv).getByTestId("lt-select")).toBeTruthy();
    expect(within(adv).getByRole("radiogroup", { name: "메시 방식" })).toBeTruthy();
  }, 15000);

  it("① 에서 셀 선택 → 안내 줄(비교용), ② 에서는 안내 없음", async () => {
    await openRadio(/① 같은 모델/);
    expect(screen.queryByTestId("lt-same-note")).toBeNull();
    fireEvent.change(screen.getByTestId("lt-select"), { target: { value: "cell:5" } });
    expect(screen.getByTestId("lt-same-note").textContent).toBe("같은 모델 — 일 등가 = 노드 직접. 셀은 비교용");
    fireEvent.click(radio(/② 다른 모델\(B 메시\)/));
    expect(screen.queryByTestId("lt-same-note")).toBeNull();
  }, 15000);
});

describe("② 결과 — doe-21(plan once)", () => {
  it("요약 줄 끝 '(모델 차 포함)', 베이스라인 표만(형상 표 생략), 3D 안내 불변", async () => {
    renderApp("/p/p-body/doe/doe-21");
    const line = await screen.findByTestId("lt-summary");
    expect(line.textContent).toMatch(/^하중 전달: 일 등가 · 기준 대비 A 메시 직접 풀이:/);
    expect(line.textContent).toMatch(/\(모델 차 포함\)$/);
    const det = screen.getByTestId("lt-details") as HTMLDetailsElement;
    det.open = true;
    fireEvent(det, new Event("toggle"));
    await screen.findByRole("table", { name: "하중 전달 베이스라인 참값 대비" });
    expect(screen.queryByRole("table", { name: "하중 전달 형상별" })).toBeNull();
  }, 15000);
});

describe("④ 결과 — legacy(진단 없음)", () => {
  it("doe-3: 줄·표 없음, 3D 안내 문구 불변", async () => {
    renderApp("/p/p-body/doe/doe-3");
    await screen.findByRole("table", { name: "순위표" });
    expect(screen.queryByTestId("lt-block")).toBeNull();
    expect(screen.queryByTestId("lt-summary")).toBeNull();
    expect(screen.getByText(/색 = 변위 \|u\|\(최악 ESL\)/)).toBeTruthy();
    expect(screen.getByTestId("doe-input-summary").textContent).not.toMatch(/하중/);
  }, 15000);
});
