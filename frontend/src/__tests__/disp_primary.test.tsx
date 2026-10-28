// V-DP-13·18~20·24~26: ⑤ 변위 주지표 판정 화면(계약 esl_disp_primary.md §9·§14·§15). 목 서버 기반.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../app/App";
import { MockServer, createMockFetch } from "../mock/server";
import { variantValidation } from "../mock/data";
import { ceil2 } from "../mock/dispdata";
import { legendKey, readLegend, validRange } from "../components/ColorLegend";
import { statusOf } from "../components/VerdictStatus";
import { renderApp } from "../test/render";

const STAGE5 = "/p/p-body/c/c-demo/stage/5";
type Kind = Parameters<typeof variantValidation>[1];

function renderWith(kind: Kind | null, path = STAGE5) {
  const server = new MockServer({ user: "power" });
  if (kind) server.validations[0] = variantValidation(server.validations[0], kind);
  const calls: string[] = [];
  const orig = server.handle.bind(server);
  server.handle = (m, p, q, b) => {
    calls.push(`${m} ${p}?${q.toString()}`);
    return orig(m, p, q, b);
  };
  globalThis.fetch = createMockFetch(server);
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  return { server, calls, ...view };
}

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* 무시 */
  }
});
afterEach(() => vi.restoreAllMocks());

const dispCard = () => screen.getByRole("region", { name: "변위 비교 (전 노드)" });

describe("V-DP-13 ⑤ 화면 구성", () => {
  it("PASS: 판정 Stat 4개·배지, 변위 카드 안에 단면 차트, 변형률 카드는 참고(배지만, 경고 문구 없음)", async () => {
    renderApp(STAGE5);
    const judge = await screen.findByTestId("judge-stats");
    for (const l of ["변위 RMS (상대)", "변위 최대 오차 (상대)", "반력 (상대)", "변위 잡음 바닥"]) expect(within(judge).getByText(l)).toBeTruthy();
    expect(within(judge).getByText("기준 ≤ 5.00e-2")).toBeTruthy();
    expect(within(judge).getByText("기준 ≤ 1.00e-3")).toBeTruthy();
    expect(screen.getByText("PASS")).toBeTruthy();
    // 단면 차트·히스토그램·상위 노드는 변위 카드 안
    const dc = dispCard();
    expect(await within(dc).findByTestId("section-card")).toBeTruthy();
    expect(within(dc).getByRole("img", { name: "변위 오차 히스토그램" })).toBeTruthy();
    expect(within(dc).getByRole("table", { name: "변위 오차 상위 노드" })).toBeTruthy();
    expect(await within(dc).findByTestId("disp-canvas")).toBeTruthy();
    // 축·배율 문구
    expect(within(dc).getByRole("button", { name: "길이 방향 단면" })).toBeTruthy();
    expect(within(dc).getByRole("button", { name: "폭 방향 단면" })).toBeTruthy();
    await waitFor(() => expect(within(dc).getByTestId("sec-scale-label").textContent).toMatch(/변형 확대 배율 ×[\d.]+ \(실제 최대 면외 변위 [\d.]+ mm\)/));
    expect(within(dc).queryByText(/PCA|ξ|η =/)).toBeNull();
    // 변형률 카드: 참고 초과 배지만
    const sc = screen.getByRole("region", { name: "변형률 (참고 — 판정 아님)" });
    expect(within(sc).getByText("참고 초과")).toBeTruthy();
    expect(within(sc).queryByText(/경고|비율이 높|초과 비율/)).toBeNull();
    expect(within(sc).queryByTestId("section-card")).toBeNull();
    expect(within(sc).getByText("기준 초과 요소")).toBeTruthy();
    expect(within(sc).getByText("소성 영역 요소")).toBeTruthy();
    expect(within(sc).getByRole("checkbox", { name: /기준 초과 요소/ })).toBeTruthy();
    expect(within(sc).getByRole("checkbox", { name: /소성 영역/ })).toBeTruthy();
  });

  it("FAIL: 배지·DISP_RMS 사유", async () => {
    renderWith("FAIL");
    expect(await screen.findByText("FAIL")).toBeTruthy();
    expect(screen.getByText(/DISP_RMS — 변위 RMS 오차가 기준 초과/)).toBeTruthy();
  });

  it("UNDETERMINED: '판정 불가' 배지·사유 한 줄·변위 컨투어 없음·변형률 참고는 표시", async () => {
    renderWith("UNDETERMINED");
    expect(await screen.findByText("판정 불가")).toBeTruthy();
    expect((await screen.findByTestId("undetermined-reason")).textContent).toBe("전체 재해석 생략(full_solve=never) — 변위 비교가 없어 판정하지 않음");
    expect(screen.queryByTestId("disp-canvas")).toBeNull();
    expect(screen.getAllByText("생략").length).toBe(3);
    expect(screen.getByTestId("disp-note").textContent).toMatch(/변위 비교를 표시할 수 없습니다/);
    expect(screen.getByRole("region", { name: "변형률 (참고 — 판정 아님)" })).toBeTruthy();
    // 단면은 Radioss·초기만(ESL·Δw 숨김), 최대 변위 오차 추천은 비활성
    await screen.findByTestId("sec-rad");
    expect(screen.queryByTestId("sec-esl")).toBeNull();
    expect(screen.queryByTestId("sec-dw")).toBeNull();
    expect(screen.queryByTestId("sec-lg-esl")).toBeNull();
    expect(screen.queryByTestId("sec-stats")).toBeNull();
    expect((screen.getByRole("option", { name: /최대 변위 오차 노드/ }) as HTMLOptionElement).disabled).toBe(true);
    expect((screen.getByRole("option", { name: /hotspot 1위/ }) as HTMLOptionElement).disabled).toBe(false);
  });

  it("LEGACY: '이전 판정 체계' + 당시 verdict, 변위 카드 대신 안내 한 줄", async () => {
    renderWith("LEGACY_FAIL");
    expect(await screen.findByText("이전 판정 체계")).toBeTruthy();
    expect(screen.getByText("당시 FAIL")).toBeTruthy();
    expect((await screen.findByTestId("disp-note")).textContent).toBe("이전 판정 체계 결과 — 다시 검증하면 변위 분석이 나옵니다");
    expect(screen.queryByText("참고 초과")).toBeNull();
    expect(statusOf({ status: undefined, scheme: null, verdict: "PASS" })).toBe("LEGACY");
  });

  it("LibraryRegister: UNDETERMINED 는 사유 필수(대화상자) → 등록 시 quality.status·confirmed_undetermined", async () => {
    const { server } = renderWith("UNDETERMINED");
    fireEvent.click(await screen.findByRole("button", { name: "라이브러리 등록" }));
    const dlg = screen.getByRole("dialog");
    expect(within(dlg).getByText("판정 불가 결과를 라이브러리에 등록")).toBeTruthy();
    const ok = within(dlg).getByRole("button", { name: "확정 등록" }) as HTMLButtonElement;
    expect(ok.disabled).toBe(true);
    fireEvent.change(within(dlg).getByRole("textbox", { name: /확정 사유/ }), { target: { value: "메모리 한도 — 반력 평형 확인" } });
    fireEvent.click(ok);
    expect(await screen.findByText("라이브러리 등록됨")).toBeTruthy();
    const e = server.entries.find((x) => x.esl_run_id === "run-1")!;
    expect(e.quality.status).toBe("UNDETERMINED");
    expect(e.quality.confirmed_undetermined?.reason).toBe("메모리 한도 — 반력 평형 확인");
  });
});

describe("V-DP-18~20 ColorLegend", () => {
  const legend = async () => within(await screen.findByTestId("disp-color-legend"));
  const canvas = async () => (await screen.findByTestId("disp-canvas")) as HTMLCanvasElement;

  it("V-DP-18: 입력 반영(캔버스 범위), 잘못된 값 무시, '자동' → 서버 robust 범위 복귀·키 삭제", async () => {
    renderApp(STAGE5);
    const cv = await canvas();
    const auto = Number(cv.dataset.rangeMax);
    expect(auto).toBeGreaterThan(0);
    const lg = await legend();
    const input = lg.getByRole("spinbutton", { name: "범위 최대" }) as HTMLInputElement;
    const autoBtn = lg.getByRole("button", { name: "자동" }) as HTMLButtonElement;
    expect(autoBtn.disabled).toBe(true);
    fireEvent.change(input, { target: { value: "2e-6" } });
    await waitFor(() => expect(Number(cv.dataset.rangeMax)).toBe(2e-6));
    expect(autoBtn.disabled).toBe(false);
    // 잘못된 값(음수·0·빈 값)은 직전 범위 유지 + 오류 표시
    fireEvent.change(input, { target: { value: "-1" } });
    expect(Number(cv.dataset.rangeMax)).toBe(2e-6);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(input, { target: { value: "0" } });
    expect(Number(cv.dataset.rangeMax)).toBe(2e-6);
    fireEvent.change(input, { target: { value: "" } });
    expect(Number(cv.dataset.rangeMax)).toBe(2e-6);
    const key = legendKey("val-1", "disp", "err");
    expect(window.localStorage.getItem(key)).toBe(JSON.stringify({ min: 0, max: 2e-6 }));
    fireEvent.click(autoBtn);
    await waitFor(() => expect(Number(cv.dataset.rangeMax)).toBe(auto));
    expect(window.localStorage.getItem(key)).toBeNull();
    expect(autoBtn.disabled).toBe(true);
  });

  it("겹쳐보기: 오차 레이어는 ±R 한 칸, rad·esl 은 최소·최대 두 칸(최소 ≥ 최대 거부)", async () => {
    renderApp(STAGE5);
    await screen.findByTestId("ovl-box");
    const box = within(screen.getByTestId("ovl-legend"));
    const mn = box.getByRole("spinbutton", { name: "범위 최소" }) as HTMLInputElement;
    const mxi = box.getByRole("spinbutton", { name: "범위 최대" }) as HTMLInputElement;
    const cv = screen.getByLabelText("Radioss 컨투어") as HTMLCanvasElement;
    fireEvent.change(mxi, { target: { value: "0.1" } });
    await waitFor(() => expect(Number(cv.dataset.rangeMax)).toBe(0.1));
    fireEvent.change(mn, { target: { value: "0.5" } }); // 최소 > 최대 → 거부
    expect(Number(cv.dataset.rangeMin)).not.toBe(0.5);
    expect(mn.getAttribute("aria-invalid")).toBe("true");
    fireEvent.click(within(screen.getByRole("group", { name: "레이어" })).getByRole("button", { name: "오차 %" }));
    const r = box.getByRole("spinbutton", { name: "범위 ±R" }) as HTMLInputElement;
    fireEvent.change(r, { target: { value: "30" } });
    await waitFor(() => expect(Number(screen.getByLabelText("오차 컨투어").getAttribute("data-range-max"))).toBe(30));
    expect(Number(screen.getByLabelText("오차 컨투어").getAttribute("data-range-min"))).toBe(-30);
    expect(window.localStorage.getItem(legendKey("val-1", "field", "err"))).toBe(JSON.stringify({ min: -30, max: 30 }));
    expect(JSON.parse(window.localStorage.getItem(legendKey("val-1", "field", "eps"))!).max).toBe(0.1);
  });

  it("V-DP-19: 범위 밖 점이 있으면 ▲ + 개수 툴팁, 없으면 미표시", async () => {
    renderApp(STAGE5);
    const lg = await legend();
    // 자동(P99) 범위: 1% 미만이 밖 — ▲ 가 있을 수 있으나 큰 값으로 넓히면 없어야 한다
    fireEvent.change(lg.getByRole("spinbutton", { name: "범위 최대" }), { target: { value: "1e-9" } });
    const dl = within(screen.getByTestId("disp-legend"));
    const up = await dl.findByTestId("lg-above");
    expect(up.getAttribute("title")).toMatch(/^범위 밖 [\d,]+개$/);
    expect(dl.queryByTestId("lg-below")).toBeNull(); // 0 기준 레이어는 ▼ 없음
    fireEvent.change(lg.getByRole("spinbutton", { name: "범위 최대" }), { target: { value: "1" } });
    await waitFor(() => expect(dl.queryByTestId("lg-above")).toBeNull());
  });

  it("V-DP-20: 저장 복원(검증·view·layer 별 분리) + getItem/setItem 이 던져도 입력·자동 동작", async () => {
    const first = renderApp(STAGE5);
    let lg = await legend();
    fireEvent.change(lg.getByRole("spinbutton", { name: "범위 최대" }), { target: { value: "3e-6" } });
    expect(readLegend(legendKey("val-1", "disp", "err"), "zero")).toEqual({ min: 0, max: 3e-6 });
    expect(readLegend(legendKey("val-1", "disp", "rel"), "zero")).toBeNull(); // layer 별 분리
    expect(readLegend(legendKey("val-1", "field", "err"), "sym")).toBeNull(); // view 별 분리
    expect(readLegend(legendKey("val-2", "disp", "err"), "zero")).toBeNull(); // 검증 별 분리
    first.unmount();
    renderApp(STAGE5);
    expect(Number(((await canvas()) as HTMLCanvasElement).dataset.rangeMax)).toBe(3e-6);
    expect(validRange("zero", { min: 1, max: 2 })).toBe(false);
    expect(ceil2(263.4)).toBe(270);
  });

  it("V-DP-20: 저장소가 던져도 오류 표시 없이 메모리로 동작", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderApp(STAGE5);
    const cv = await canvas();
    const lg = await legend();
    fireEvent.change(lg.getByRole("spinbutton", { name: "범위 최대" }), { target: { value: "4e-6" } });
    await waitFor(() => expect(Number(cv.dataset.rangeMax)).toBe(4e-6));
    fireEvent.click(lg.getByRole("button", { name: "자동" }));
    await waitFor(() => expect(Number(cv.dataset.rangeMax)).not.toBe(4e-6));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("V-DP-24~26 단면선 개선", () => {
  const at = () => screen.getByTestId("sec-at").textContent;

  it("V-DP-24: 슬라이더·지도 클릭·추천이 at 을 바꾸고 단면 요청(디바운스)·그래프 갱신, 축 전환 시 추천 좌표 적용", async () => {
    const { calls } = renderWith(null);
    await screen.findByTestId("sec-rad");
    const sectionCalls = () => calls.filter((c) => c.includes("/section")).length;
    expect(calls.find((c) => c.includes("/section"))).toMatch(/axis=eta&at=0.5/); // 기본 길이 방향
    const slider = screen.getByRole("slider", { name: "단면 위치" });
    const d0 = screen.getByTestId("sec-rad").getAttribute("d");
    const n0 = sectionCalls();
    fireEvent.change(slider, { target: { value: "0.2" } });
    fireEvent.change(slider, { target: { value: "0.3" } });
    fireEvent.change(slider, { target: { value: "0.8" } });
    expect(at()).toBe("0.80");
    await waitFor(() => expect(screen.getByTestId("sec-rad").getAttribute("d")).not.toBe(d0));
    expect(sectionCalls() - n0).toBe(1); // 디바운스: 마지막 값만 요청
    expect(calls.filter((c) => c.includes("/section")).pop()).toMatch(/at=0.8/);
    // 지도 클릭 → 위치 변경(두 지도 공통 상태)
    const box = screen.getByTestId("disp-box");
    fireEvent.click(box, { clientX: 300, clientY: 12 });
    await waitFor(() => expect(Number(at())).toBeGreaterThan(0.9));
    // 추천 선택 → 길이 방향 단면이면 at = η
    const sel = screen.getByRole("combobox", { name: "단면 추천" }) as HTMLSelectElement;
    fireEvent.change(sel, { target: { value: "hotspot1" } });
    const etaAt = at();
    expect(sel.value).toBe("hotspot1");
    // 축 전환 → 폭 방향 단면은 at = ξ
    fireEvent.click(screen.getByRole("button", { name: "폭 방향 단면" }));
    await waitFor(() => expect(at()).not.toBe(etaAt));
    expect(sel.value).toBe("hotspot1");
    // 슬라이더로 바꾸면 "직접 지정"
    fireEvent.change(slider, { target: { value: "0.1" } });
    expect(sel.value).toBe("manual");
    await waitFor(() => expect(screen.getByTestId("sec-xlabel").textContent).toBe("판 폭 방향 (mm)"));
  });

  it("V-DP-25: 두 지도에 단면선·띠가 있고 위치 변경 시 이동", async () => {
    renderApp(STAGE5);
    await screen.findByTestId("sec-rad");
    await screen.findByTestId("ovl-box");
    const marks = await screen.findAllByTestId("sec-marks");
    expect(marks).toHaveLength(2);
    expect(screen.getAllByTestId("sec-band")).toHaveLength(2);
    const y0 = screen.getAllByTestId("sec-line")[0].getAttribute("y1");
    fireEvent.change(screen.getByRole("slider", { name: "단면 위치" }), { target: { value: "0.9" } });
    await waitFor(() => expect(screen.getAllByTestId("sec-line")[0].getAttribute("y1")).not.toBe(y0));
    expect(screen.getAllByTestId("sec-marks")[1].getAttribute("data-at")).toBe("0.90");
    expect(screen.getAllByTestId("sec-suggest-marker").length).toBeGreaterThanOrEqual(2);
  });

  it("V-DP-26: Δw 곡선·보조 축 없음(v0.5.9)·수치 줄, 배율 라벨·툴팁, '실제 크기(×1)' 토글", async () => {
    renderApp(STAGE5);
    await screen.findByTestId("sec-esl");
    expect(screen.queryByTestId("sec-dw")).toBeNull();
    expect(screen.queryByTestId("sec-dw-axis")).toBeNull();
    expect(screen.getByTestId("sec-stats").textContent).toMatch(/Δw 최대 .* mm \(U 대비 .*\) · RMS .* mm \(U 대비 .*\) · 요소 \d+개/);
    const label = screen.getByTestId("sec-scale-label");
    expect(label.closest("label")!.getAttribute("title")).toBe("배율은 화면 표시용이며 값·판정에 영향 없음");
    const k0 = screen.getByTestId("sec-k").textContent;
    expect(k0).not.toBe("×1");
    const slider = screen.getByRole("slider", { name: "변형 확대 배율" }) as HTMLInputElement;
    const toggle = screen.getByRole("button", { name: "실제 크기(×1)" });
    fireEvent.click(toggle);
    expect(screen.getByTestId("sec-k").textContent).toBe("×1");
    expect(slider.disabled).toBe(true);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(toggle);
    expect(screen.getByTestId("sec-k").textContent).toBe(k0);
    expect(slider.disabled).toBe(false);
  });

  // ---- v0.5.9 단면 그래프: 축 편집 · 범례 선택 (계약 §15.6)
  const inp = (id: string) => screen.getByTestId(id) as HTMLInputElement;
  const edit = (id: string, v: string) => fireEvent.change(inp(id), { target: { value: v } });

  it("V-DP-27: 축 입력이 그래프에 반영되고 '자동'으로 복귀, 잘못된 값은 직전 범위 유지, 범위 밖은 클리핑", async () => {
    window.localStorage.clear();
    renderApp(STAGE5);
    await screen.findByTestId("sec-esl");
    const ymin0 = inp("sec-ax-y-min").value;
    const ymax0 = inp("sec-ax-y-max").value;
    const yAuto = screen.getByRole("button", { name: "Y축 자동" }) as HTMLButtonElement;
    expect(yAuto.disabled).toBe(true);
    const tick0 = [...document.querySelectorAll("svg[aria-label='단면선'] .chart-tick")].map((t) => t.textContent).join("|");
    edit("sec-ax-y-min", "-2");
    expect(inp("sec-ax-y-min").value).toBe("-2");
    expect(screen.getByTestId("sec-ax-y").getAttribute("data-manual")).toBe("true");
    expect([...document.querySelectorAll("svg[aria-label='단면선'] .chart-tick")].map((t) => t.textContent).join("|")).not.toBe(tick0);
    expect(document.querySelector("svg[aria-label='단면선'] clipPath rect")).toBeTruthy(); // 범위 밖 데이터는 clipPath 로 자름
    expect(document.querySelector("svg[aria-label='단면선'] g[clip-path]")).toBeTruthy();
    // 최소 ≥ 최대 는 거부(직전 유효 범위 유지)
    edit("sec-ax-y-min", "1000");
    expect(inp("sec-ax-y-min").getAttribute("aria-invalid")).toBe("true");
    // X 축도 같은 방식
    edit("sec-ax-x-max", "0.5");
    expect(screen.getByTestId("sec-ax-x").getAttribute("data-manual")).toBe("true");
    // 자동 복귀
    fireEvent.click(yAuto);
    expect(inp("sec-ax-y-min").value).toBe(ymin0);
    expect(inp("sec-ax-y-max").value).toBe(ymax0);
    expect(yAuto.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "X축 자동" }));
    expect(screen.getByTestId("sec-ax-x").getAttribute("data-manual")).toBe("false");
  });

  it("V-DP-27b: 축 범위는 (검증 id·축 방향)별 localStorage 에 기억되고, 저장소 오류에도 동작", async () => {
    window.localStorage.clear();
    const { unmount } = renderApp(STAGE5);
    await screen.findByTestId("sec-esl");
    edit("sec-ax-y-max", "1");
    const keys = Object.keys(window.localStorage).filter((x) => x.startsWith("esl.secaxis.v1:"));
    expect(keys).toHaveLength(1);
    expect(keys[0]).toMatch(/:eta$/);
    expect(JSON.parse(window.localStorage.getItem(keys[0])!).y.max).toBe(1);
    unmount();
    renderApp(STAGE5); // 새로 열어도 복원
    await screen.findByTestId("sec-esl");
    await waitFor(() => expect(inp("sec-ax-y-max").value).toBe("1"));
    // 폭 방향 단면은 별도 키 → 자동
    fireEvent.click(screen.getByRole("button", { name: "폭 방향 단면" }));
    await waitFor(() => expect(screen.getByTestId("sec-xlabel").textContent).toBe("판 폭 방향 (mm)"));
    await waitFor(() => expect(screen.getByTestId("sec-ax-y").getAttribute("data-manual")).toBe("false"));
    // 자동 복귀 시 키 삭제
    fireEvent.click(screen.getByRole("button", { name: "길이 방향 단면" }));
    await waitFor(() => expect(inp("sec-ax-y-max").value).toBe("1"));
    fireEvent.click(screen.getByRole("button", { name: "Y축 자동" }));
    expect(window.localStorage.getItem(keys[0])).toBeNull();
  });

  it("V-DP-27c: localStorage 읽기·쓰기가 모두 던져도 화면은 메모리 상태로 동작", async () => {
    const getSpy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const setSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      renderApp(STAGE5);
      await screen.findByTestId("sec-esl");
      edit("sec-ax-y-max", "1");
      expect(screen.getByTestId("sec-ax-y").getAttribute("data-manual")).toBe("true");
      expect(inp("sec-ax-y-max").value).toBe("1");
    } finally {
      getSpy.mockRestore();
      setSpy.mockRestore();
    }
  });

  it("V-DP-28: 범례 클릭으로 계열 숨김·표시, 최소 1개 유지, 숨긴 항목 흐리게, 자동 범위는 보이는 계열 기준으로 재계산", async () => {
    window.localStorage.clear();
    renderApp(STAGE5);
    await screen.findByTestId("sec-esl");
    const lg = (k: string) => screen.getByTestId(`sec-lg-${k}`);
    const range = () => `${inp("sec-ax-y-min").value}~${inp("sec-ax-y-max").value}`;
    const r0 = range();
    fireEvent.click(lg("rad"));
    expect(screen.queryByTestId("sec-rad")).toBeNull();
    expect(lg("rad").getAttribute("aria-pressed")).toBe("false");
    expect(lg("rad").className).toMatch(/off/);
    expect(screen.getByTestId("sec-esl")).toBeTruthy();
    fireEvent.click(lg("esl"));
    expect(screen.queryByTestId("sec-esl")).toBeNull();
    expect(screen.getByTestId("sec-init")).toBeTruthy();
    const rInit = range();
    expect(rInit).not.toBe(r0); // 초기 형상만 → 범위 재계산
    // 마지막 하나는 숨길 수 없음
    fireEvent.click(lg("init"));
    expect(screen.getByTestId("sec-init")).toBeTruthy();
    expect(lg("init").getAttribute("aria-pressed")).toBe("true");
    // 다시 표시
    fireEvent.click(lg("rad"));
    fireEvent.click(lg("esl"));
    expect(screen.getByTestId("sec-rad")).toBeTruthy();
    expect(screen.getByTestId("sec-esl")).toBeTruthy();
    expect(range()).toBe(r0);
    // 수동 범위는 계열 토글로 바뀌지 않음
    edit("sec-ax-y-max", "1");
    fireEvent.click(lg("rad"));
    expect(inp("sec-ax-y-max").value).toBe("1");
  });
});
