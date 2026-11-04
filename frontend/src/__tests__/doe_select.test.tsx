// V-BS-17(esl_bead_select.md §16): 비드 직접 선택 화면(mock) — ① 하위 선택(비활성 사유)·STEP 칸 숨김, 도구 4종·층·보이는 면만, 비드 목록 경고 배지,
// 주 버튼 전환(선택 저장 ↔ 미리보기), 평면도 노드 토글·라벨 칩·폭 점선·단면 미니 그림, 썸네일 범례·품질 실패 배지·클릭 3D, SELECTION_DROPPED 처리.
// 화면 크기(2560×1440·1920×1080 잘림·가로 스크롤)는 scripts/screenshots-v0150.mjs.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { doeBlockedReason, normalizeDoeSettings, scenarioBlocked } from "../api/doe";
import { makeDoeSettings } from "../mock/doedata";
import { blendSmall } from "../components/DoeParamTable";
import { offsetRing } from "../components/BoundaryPlan";
import { sectionLine } from "../components/SectionMini";

const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const reasonOf = (b: HTMLButtonElement) => b.closest(".primary-wrap")?.getAttribute("title") ?? null;
const radio = (name: RegExp | string) => screen.getByRole("radio", { name }) as HTMLInputElement;

describe("select 규칙(화면 쪽 함수)", () => {
  it("활성: paicad 없어도 select 는 막지 않음, 꺼짐 사유, settings 보정", () => {
    const st = makeDoeSettings();
    st.enabled = false;
    st.reason = "PAICAD_NOT_CONFIGURED";
    expect(doeBlockedReason(st, "select")).toBeNull();
    st.scenarios.select = false;
    expect(scenarioBlocked(st, "select")).toMatch(/직접 선택.*꺼져/);
    const n = normalizeDoeSettings({ enabled: true, scenarios: { select: true }, select_reason: null });
    expect(n.select?.enabled).toBe(true);
    expect(n.select?.feature_angle_deg).toBe(15);
    expect(normalizeDoeSettings({}).select?.enabled).toBe(false);
  });
  it("R 작음 배지·폭 윤곽 오프셋·단면 범위 선", () => {
    expect(blendSmall(15, 8, 60, 48, 72)).toBe(true); // 15 < 8·12/2
    expect(blendSmall(60, 8, 60, 48, 72)).toBe(false);
    expect(blendSmall(15, null, 60, 48, 72)).toBe(false);
    expect(offsetRing([[0, 0], [10, 0]], [[0, -1], [1, 0]], 2)).toEqual([[0, -2], [12, 0]]);
    const sec = { s: [-10, 0, 10], z: [0, 5, 0], dz_dD: { "1": [0, 1, 0] }, ds_dW: [-0.5, 0, 0.5], dz_dW: [0, 0, 0] };
    expect(sectionLine(sec, { type: "D", tier: 1, nominal: 5, lo: 3, hi: 7 }, 7)).toEqual([[-10, 0], [0, 7], [10, 0]]);
    expect(sectionLine(sec, { type: "W", nominal: 20, lo: 16, hi: 24 }, 24)).toEqual([[-12, 0], [0, 5], [12, 0]]);
  });
});

describe("새 스터디 — ① 비드 정의 하위 선택", () => {
  it("직접 선택(메시): STEP 칸 숨김 → 입력 검사 → [입력 준비] → 준비 후 비드 선택 카드", async () => {
    const r = renderApp("/p/p-body/doe/new?entries=le-1,le-2", "power");
    await waitFor(() => expect(radio(/① 같은 모델/).checked).toBe(true));
    expect(screen.getByTestId("doe-beaddef")).toBeTruthy();
    expect(radio("자동 탐지(STEP)").checked).toBe(true);
    fireEvent.click(radio("직접 선택(메시)"));
    expect(screen.queryByTestId("doe-step-drop")).toBeNull();
    expect(screen.getByTestId("doe-select-note")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("doe-check").textContent).toMatch(/기준 Case/));
    const [p] = primaries(r.container);
    expect(p.textContent).toBe("입력 준비");
    await waitFor(() => expect(p.disabled).toBe(false));
    fireEvent.click(p);
    await waitFor(() => expect(screen.getByRole("heading", { name: "강성 평가 스터디" })).toBeTruthy());
  });

  it("select 꺼짐: 하위 라디오 비활성 + 사유", async () => {
    renderApp("/p/p-body/doe/new?entries=le-1,le-2", "power", (s) => {
      s.doe.settings.scenarios.select = false;
      s.doe.settings.select!.enabled = false;
    });
    await waitFor(() => expect(radio("직접 선택(메시)").disabled).toBe(true));
    expect(radio("직접 선택(메시)").closest("label")?.getAttribute("title")).toMatch(/꺼져/);
  });
});

describe("상세(doe-5: 선택 저장됨, READY)", () => {
  it("도구 4종·층·보이는 면만·비드 목록(경고 배지)·주 버튼 미리보기, 블렌딩을 바꾸면 [선택 저장] → 저장 후 미리보기", async () => {
    const r = renderApp("/p/p-body/doe/doe-5", "power");
    await waitFor(() => expect(screen.getByRole("toolbar", { name: "선택 도구" })).toBeTruthy());
    const tb = screen.getByRole("toolbar", { name: "선택 도구" });
    for (const t of ["클릭+확장", "브러시", "사각", "올가미"]) expect(within(tb).getByRole("radio", { name: t })).toBeTruthy();
    expect((within(tb).getByLabelText("보이는 면만") as HTMLInputElement).checked).toBe(true);
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy());
    const layer = screen.getByLabelText("대상 층") as HTMLSelectElement;
    expect([...layer.options].map((o) => o.textContent)).toEqual(["좌 경로 비드 · 단 1 바닥", "좌 경로 비드 · 단 2 바닥", "좌 경로 비드 · 사면", "원형 비드 · 단 1 바닥", "원형 비드 · 사면", "고정", "제외(사면 자동에서 뺌)"]);
    fireEvent.click(within(tb).getByRole("radio", { name: "브러시" }));
    expect(screen.getByLabelText("브러시 크기(px)")).toBeTruthy();
    expect(screen.getByTestId("bs-hint").textContent).toMatch(/Shift = 더하기 · Alt 또는 지우개 = 빼기/);
    // derive(저장본 불러올 때 1회) → 경고 배지(블렌딩 자르기)·공칭 D
    await waitFor(() => expect(screen.getByTestId("bead-warn-b1")).toBeTruthy());
    expect(screen.getByTestId("bead-b1").textContent).toMatch(/D 22\.0/);
    expect(screen.getByTestId("bs-fixed").textContent).toMatch(/fixed-scan/);
    await waitFor(() => expect(primaries(r.container)[0].textContent).toBe("미리보기"));
    expect(primaries(r.container)).toHaveLength(1);
    // 변수 표(④) — 블렌딩을 숫자로 바꾸면 선택 변경 → [선택 저장]
    await waitFor(() => expect(screen.getByTestId("param-B1_W")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("B1 블렌딩 반경"), { target: { value: "num" } });
    await waitFor(() => expect(primaries(r.container)[0].textContent).toBe("선택 저장"));
    expect(screen.getByTestId("bs-dirty")).toBeTruthy();
    const save = primaries(r.container)[0];
    await waitFor(() => expect(save.disabled).toBe(false));
    fireEvent.click(save);
    await waitFor(() => expect(primaries(r.container)[0].textContent).toBe("미리보기"));
    expect(r.server.doe.recs.find((x) => x.out.id === "doe-5")!.sel!.rev).toBe(2);
  });

  it("[+ 비드] 후 빈 단이면 저장 불가 사유, 묶기", async () => {
    const r = renderApp("/p/p-body/doe/doe-5", "power");
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "묶기" }));
    await waitFor(() => expect(screen.getByTestId("bead-b1").textContent).toMatch(/묶음 D1\+D2/));
    fireEvent.click(screen.getByRole("button", { name: "+ 비드" }));
    await waitFor(() => expect(screen.getByTestId("bead-b3")).toBeTruthy());
    const p = primaries(r.container)[0];
    expect(p.textContent).toBe("선택 저장");
    expect(reasonOf(p)).toMatch(/B3: 단 1 바닥이 비었습니다/);
  });

  it("평면도: 노드 점 숨김 토글·라벨 칩·폭 행 → 최소·최대 점선, 깊이 행 → 단면 점선", async () => {
    renderApp("/p/p-body/doe/doe-5", "power");
    await waitFor(() => expect(screen.getByTestId("plan-chip-b1")).toBeTruthy());
    expect(screen.getByTestId("plan-chip-b1").textContent).toMatch(/B1 · D1 22\.0 · D2 14\.0 · W 60\.0/);
    expect(screen.queryByTestId("plan-nodes")).toBeNull();
    const tg = screen.getByTestId("plan-nodes-toggle") as HTMLInputElement;
    fireEvent.click(tg);
    await waitFor(() => expect(screen.getByTestId("plan-nodes")).toBeTruthy());
    fireEvent.click(screen.getByTestId("param-B1_W"));
    await waitFor(() => expect(screen.getByTestId("plan-w-range-b1")).toBeTruthy());
    fireEvent.click(screen.getByTestId("param-B1_D1"));
    await waitFor(() => expect(screen.getByTestId("section-lo")).toBeTruthy());
    expect(screen.getByTestId("section-mini").textContent).toMatch(/D1 22\.0 \(15\.4–28\.6\)/);
  });

  it("SELECTION_DROPPED: 기준 메시가 바뀌면 안내 + [선택 저장]", async () => {
    const r = renderApp("/p/p-body/doe/doe-5", "power", (s) => {
      s.doe.recs.find((x) => x.out.id === "doe-5")!.selDropped = true;
    });
    await waitFor(() => expect(screen.getByTestId("selection-dropped").textContent).toMatch(/기준 메시가 바뀌어/));
    await waitFor(() => expect(primaries(r.container)[0].textContent).toBe("선택 저장"));
  });
});

describe("상세(doe-6: 미리보기 완료)", () => {
  it("썸네일 범례 1개·OK/고정 침범/품질 실패 배지·클릭 → 3D 보기, 선택 바꾸면 '선택 변경됨'", async () => {
    const r = renderApp("/p/p-body/doe/doe-6", "power");
    await waitFor(() => expect(screen.getByTestId("height-legend")).toBeTruthy());
    expect(screen.getAllByTestId("height-legend")).toHaveLength(1);
    const thumbs = screen.getByRole("list", { name: "미리보기 썸네일" });
    expect(within(thumbs).getAllByText(/⨯품질 실패/).length).toBeGreaterThan(0);
    expect(within(thumbs).getAllByText(/⨯고정 침범/).length).toBeGreaterThan(0);
    expect(within(thumbs).getAllByText("OK").length).toBeGreaterThan(0);
    await waitFor(() => expect(primaries(r.container)[0].textContent).toBe("강성 평가 실행"));
    fireEvent.click(screen.getByTestId("thumb-d001"));
    await waitFor(() => expect(screen.getByRole("region", { name: "안 d001 3D 보기" })).toBeTruthy());
    expect(screen.getByRole("radio", { name: "공칭" })).toBeTruthy();
    // 선택 편집 → 미리보기 무효
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "묶기" }));
    await waitFor(() => expect(screen.getByTestId("selection-stale")).toBeTruthy());
    expect(primaries(r.container)[0].textContent).toBe("선택 저장");
  });
});
