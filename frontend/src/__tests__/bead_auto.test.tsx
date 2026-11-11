// v0.16.2 BEAD_AUTO(esl_bead_auto.md AD-D-1·4·8·13, §7·§8): 자동 탐지 seed = 선택 화면 기본 상태(되돌리기·비드별/전체 초기화 = seed),
// 미저장 배지, seed 없음(404 AUTO_NOT_AVAILABLE · AUTO_DETECT_FAILED) → 안내 1줄 + 직접 선택 도구, AUTO_* 경고, 순위 ⚠ MORPH_EXTREME_ELEMENTS,
// ①② 하위 라디오(bead_source)·② select_base mesh. 화면 크기(2560×1440·1920×1080)는 mock 스크린샷으로 확인.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../test/render";
import { isInfoWarn, selectSubBlocked, warnText } from "../api/doe";
import { makeDoeSettings } from "../mock/doedata";
import { cloneState, counts, emptyState, paint, resetAllTo, resetBeadTo, addBead, deleteBead } from "../view3d/select/layers";
import { AUTO_BADGE } from "../components/BeadSelectCard";

const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const radio = (name: RegExp | string) => screen.getByRole("radio", { name }) as HTMLInputElement;
/** 단1 바닥 요소 수(derive 뒤 붙는 D 값은 뺌) */
const floorText = (id: string) => /단1 바닥 (\d[\d,]*)/.exec(within(screen.getByTestId(`bead-${id}`)).getByText(/단1 바닥/).textContent ?? "")?.[1] ?? "";

afterEach(() => vi.restoreAllMocks());

describe("seed 기준 초기화(layers)", () => {
  it("resetBeadTo: 그 비드만 seed 요소·단 수로(이름 유지, 다른 비드 요소는 덮지 않음), resetAllTo: 비드 목록·층 전부 seed", () => {
    const seed = emptyState(10);
    addBead(seed);
    addBead(seed);
    seed.beads[0].nTiers = 2;
    paint(seed, [0, 1], { kind: "tier", bead: 0, k: 1 }, "add");
    paint(seed, [2], { kind: "tier", bead: 0, k: 2 }, "add");
    paint(seed, [5, 6], { kind: "tier", bead: 1, k: 1 }, "add");
    const s = cloneState(seed);
    // 편집: b1 이름 바꾸고 단 2 지우고 요소 1 을 b2 가 차지, b1 바닥 0 비움
    s.beads[0].name = "내 비드";
    s.owner[0] = -1;
    s.owner[1] = 16 + 1; // b2 단1
    s.owner[2] = -1;
    s.beads[0].nTiers = 1;
    const p = resetBeadTo(s, 0, seed)!;
    expect(p.meta).toBeTruthy();
    expect(s.beads[0].name).toBe("내 비드");
    expect(s.beads[0].nTiers).toBe(2);
    expect(counts(s, 0).tiers).toEqual([1, 1]); // 요소 1 은 b2 가 가져서 덮지 않음
    expect(s.owner[1]).toBe(17);
    // seed 를 바꾸지 않음
    expect(counts(seed, 0).tiers).toEqual([2, 1]);
    // 전체 초기화 = seed
    deleteBead(s, 1);
    expect(s.beads).toHaveLength(1);
    resetAllTo(s, seed);
    expect(s.beads.map((b) => b.id)).toEqual(["b1", "b2"]);
    expect(Array.from(s.owner)).toEqual(Array.from(seed.owner));
    // seed 에 없는 비드는 빈 선택으로
    addBead(s);
    paint(s, [8], { kind: "tier", bead: 2, k: 1 }, "add");
    resetBeadTo(s, 2, seed);
    expect(counts(s, 2).tiers).toEqual([0]);
  });

  it("경고 문구(§8): AUTO_* 인자·정보 수준, SELECT_BRIDGE_SKIPPED, MORPH_EXTREME_ELEMENTS, ①② 하위 비활성 사유", () => {
    expect(warnText({ code: "AUTO_DETECT_FAILED", step: "tag" } as never)).toMatch(/자동 탐지 실패\(메시 대응\).*직접 선택/);
    expect(warnText({ code: "AUTO_TOO_MANY_BEADS", n: 25, max: 20 } as never)).toBe("자동 탐지 비드 25개 — 상한 20개까지만 가져왔습니다");
    expect(warnText({ code: "AUTO_BEAD_UNMAPPED", bead: "b3" } as never)).toMatch(/^B3: 바닥 요소를/);
    expect(warnText({ code: "SELECT_BRIDGE_SKIPPED", eq_d_mm: 31.24, gap_mm: 4 } as never)).toBe("등가 지름 31.2 mm 구멍은 건너 잇지 않았습니다(틈 4 mm)");
    expect(warnText({ code: "MORPH_EXTREME_ELEMENTS" })).toMatch(/극단 요소/);
    expect(warnText({ code: "AUTO_GROUP_DROPPED", message: "서버 문구" })).toBe("서버 문구");
    expect(isInfoWarn({ code: "AUTO_SLOPE_DIFF" })).toBe(true);
    expect(isInfoWarn({ code: "AUTO_BEAD_UNMAPPED" })).toBe(false);
    const st = makeDoeSettings();
    expect(selectSubBlocked(st, "case", "auto")).toBeNull();
    st.scenarios.select_auto = false;
    expect(selectSubBlocked(st, "mesh", "auto")).toMatch(/자동 분류가 꺼져/); // v0.17.0: paicad 무관(BG §5.5)
    expect(selectSubBlocked(st, "mesh", "manual")).toBeNull();
    st.scenarios.select_mesh = false;
    expect(selectSubBlocked(st, "mesh", "manual")).toMatch(/B 메시/);
  });
});

describe("auto 스터디(doe-8): seed 불러오기·편집·seed 로 초기화·미저장 배지", () => {
  it("seed = 기본 상태(실행 취소 비활성), 배지·AUTO 정보, 층 비우기 → 이 비드 초기화 = seed, 비드 삭제 → 되돌리기 = seed, 전체 초기화 = seed, 저장하면 배지 사라짐", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const r = renderApp("/p/p-body/doe/doe-8", "power");
    await waitFor(() => expect(screen.getByTestId("bead-b2")).toBeTruthy(), { timeout: 8000 });
    expect(screen.getByTestId("bs-auto-badge").textContent).toBe(AUTO_BADGE);
    expect(screen.getByTestId("bs-auto-info").textContent).toMatch(/B2: 자동 탐지 사면 폭이 계산값과 27 % 다릅니다/);
    expect(screen.queryByTestId("bs-dirty")).toBeNull(); // 배지가 대신 알림
    const n0 = floorText("b1");
    expect(Number(n0.replace(/,/g, ""))).toBeGreaterThan(0);
    expect(within(screen.getByTestId("bead-b1")).queryByText(/단2 바닥/)).toBeNull(); // seed = 비드당 1단
    expect((screen.getByRole("button", { name: "실행 취소" }) as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect(primaries(r.container).map((b) => b.textContent)).toEqual(["선택 저장"]));
    expect(screen.getByRole("button", { name: "이 비드 초기화" }).getAttribute("title")).toMatch(/자동 탐지 결과로/);
    expect(screen.getByRole("button", { name: "전체 초기화" }).getAttribute("title")).toMatch(/자동 탐지 결과로/);

    // 편집(층 비우기) → 이 비드 초기화 = seed(빈 선택 아님)
    fireEvent.click(screen.getByRole("button", { name: "층 비우기" }));
    await waitFor(() => expect(floorText("b1")).toBe("0"));
    fireEvent.click(screen.getByRole("button", { name: "이 비드 초기화" }));
    await waitFor(() => expect(floorText("b1")).toBe(n0));

    // 비드 삭제 → 되돌리기를 끝까지 = seed
    fireEvent.click(screen.getByRole("button", { name: "B2 삭제" }));
    await waitFor(() => expect(screen.queryByTestId("bead-b2")).toBeNull());
    const undo = screen.getByRole("button", { name: "실행 취소" }) as HTMLButtonElement;
    while (!undo.disabled) fireEvent.click(undo);
    await waitFor(() => expect(screen.getByTestId("bead-b2")).toBeTruthy());
    expect(floorText("b1")).toBe(n0);

    // 비드 삭제 + 층 비우기 → 전체 초기화 = seed
    fireEvent.click(screen.getByRole("button", { name: "B2 삭제" }));
    await waitFor(() => expect(screen.queryByTestId("bead-b2")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "층 비우기" }));
    fireEvent.click(screen.getByRole("button", { name: "전체 초기화" }));
    await waitFor(() => expect(screen.getByTestId("bead-b2")).toBeTruthy());
    expect(floorText("b1")).toBe(n0);
    expect(screen.getByTestId("bs-auto-badge")).toBeTruthy();

    // [선택 저장] → 배지 사라짐, 주 버튼 미리보기
    const save = primaries(r.container)[0];
    await waitFor(() => expect(save.disabled).toBe(false));
    fireEvent.click(save);
    await waitFor(() => expect(screen.queryByTestId("bs-auto-badge")).toBeNull());
    await waitFor(() => expect(primaries(r.container)[0].textContent).toBe("미리보기"));
    expect(r.server.doe.recs.find((x) => x.out.id === "doe-8")!.sel!.input.beads.map((b) => b.id)).toEqual(["b1", "b2"]);
  }, 20000);

  it("수동 스터디(doe-5)는 전체 초기화 = 빈 선택(배지 없음)", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderApp("/p/p-body/doe/doe-5", "power");
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy(), { timeout: 8000 });
    expect(screen.queryByTestId("bs-auto")).toBeNull();
    expect(screen.getByRole("button", { name: "전체 초기화" }).getAttribute("title")).not.toMatch(/자동 탐지/);
    fireEvent.click(screen.getByRole("button", { name: "전체 초기화" }));
    await waitFor(() => expect(screen.queryByTestId("bead-b1")).toBeNull());
    expect(screen.getByText(/비드가 없습니다/)).toBeTruthy();
  }, 15000);
});

describe("seed 없음 → 안내 1줄 + 직접 선택 도구", () => {
  it("doe-9: 404 AUTO_NOT_AVAILABLE + 준비 경고 AUTO_DETECT_FAILED → 안내·경고 문구, 빈 선택, [+ 비드] 가능", async () => {
    const r = renderApp("/p/p-body/doe/doe-9", "power");
    expect((await screen.findByTestId("bs-auto-notice")).textContent).toBe("비드 자동 탐지에 실패했습니다 — 직접 선택 도구로 비드를 고르세요");
    expect(screen.queryByTestId("bs-auto-badge")).toBeNull();
    expect(screen.getByText(/비드 자동 탐지 실패\(비드 인식 · EXTRACT_NO_BEAD\)/)).toBeTruthy(); // ① 입력 카드 준비 경고
    await waitFor(() => expect(screen.getByText(/비드가 없습니다/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "+ 비드" }));
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy());
    expect(primaries(r.container)[0].textContent).toBe("선택 저장");
  });

  it("빈 seed(선택 0 + AUTO_DETECT_FAILED 경고)도 안내 후 직접 선택", async () => {
    renderApp("/p/p-body/doe/doe-8", "power", (s) => {
      const rec = s.doe.recs.find((x) => x.out.id === "doe-8")!;
      rec.autoSel = { ...rec.autoSel!, selection: { ...rec.autoSel!.selection, beads: [] }, warnings: [{ code: "AUTO_DETECT_FAILED", step: "tag" }] };
    });
    expect((await screen.findByTestId("bs-auto-notice")).textContent).toMatch(/자동 탐지에 실패했습니다/);
    await waitFor(() => expect(screen.getByText(/비드가 없습니다/)).toBeTruthy());
    expect(screen.queryByTestId("bs-auto-badge")).toBeNull();
  });

  it("AUTO_* 경고(⚠ 줄): AUTO_TOO_MANY_BEADS·AUTO_BEAD_UNMAPPED", async () => {
    renderApp("/p/p-body/doe/doe-8", "power", (s) => {
      const rec = s.doe.recs.find((x) => x.out.id === "doe-8")!;
      rec.autoSel = { ...rec.autoSel!, warnings: [{ code: "AUTO_TOO_MANY_BEADS", n: 24, max: 20 }, { code: "AUTO_BEAD_UNMAPPED", bead: "b3" }] };
    });
    const w = await screen.findByTestId("bs-auto-warn");
    expect(w.textContent).toMatch(/자동 탐지 비드 24개 — 상한 20개/);
    expect(w.textContent).toMatch(/B3: 바닥 요소를 메시에서 찾지 못했습니다/);
  });
});

describe("AD-D-8 순위 ⚠ MORPH_EXTREME_ELEMENTS", () => {
  it("1위 warn = 극단 요소 → ⚠ 배지(툴팁) + '경고 없는 최상위' 줄", async () => {
    renderApp("/p/p-body/doe/doe-1", "power", (s) => {
      const res = s.doe.recs.find((x) => x.out.id === "doe-1")!.result!;
      const top = res.ranking.find((x) => x.rank === 1)!;
      top.warn = ["MORPH_EXTREME_ELEMENTS"];
    });
    const line = await screen.findByTestId("best-clean");
    expect(line.textContent).toMatch(/1위가 경고 안입니다\(극단 요소\) — 경고 없는 최상위: d\d{3}/);
    const badge = screen.getAllByTestId(/^rank-warn-/)[0];
    expect(badge.getAttribute("title")).toBe("극단 요소");
  });
});

describe("① ② 하위 라디오(bead_source) — ② 자동 탐지", () => {
  it("v0.17.0 ② + 자동 탐지: B 메시만 필요(STEP 은 선택 힌트) → select + select_base mesh + bead_source auto + STEP", async () => {
    const r = renderApp("/p/p-body/doe/new?entries=le-1,le-9", "power");
    await waitFor(() => expect(radio(/③/).checked).toBe(true));
    fireEvent.click(radio(/② 다른 모델\(B 메시\)/));
    expect(screen.getByTestId("doe-beaddef")).toBeTruthy();
    fireEvent.click(radio("자동 탐지"));
    expect(screen.getByTestId("doe-step-drop")).toBeTruthy();
    expect(screen.getByTestId("doe-mesh-drop")).toBeTruthy();
    await waitFor(() => expect(primaries(r.container)[0].closest(".primary-wrap")?.getAttribute("title")).toMatch(/B 메시/), { timeout: 4000 });
    fireEvent.change(screen.getByLabelText("B 메시(.rad + include 또는 .inc) 끌어다 놓기"), { target: { files: [new File([new Uint8Array(4096)], "QN80J_chr.rad")] } });
    // STEP 없이도 입력 검사(BG §5.3)
    expect(await screen.findByTestId("doe-check", undefined, { timeout: 4000 })).toBeTruthy();
    expect(primaries(r.container)[0].closest(".primary-wrap")?.getAttribute("title") ?? "").not.toMatch(/STEP/);
    fireEvent.change(screen.getByLabelText("(선택) Ch/R 중립면 STEP 끌어다 놓기"), { target: { files: [new File([new Uint8Array(4096)], "QN80J_mid.stp")] } });
    await waitFor(() => expect(screen.getByTestId("doe-check").textContent).toMatch(/STEP QN80J_mid/), { timeout: 4000 });
    const chk = screen.getByTestId("doe-check");
    expect(chk.textContent).toMatch(/STEP QN80J_mid\.stp .*B 메시 QN80J_chr\.rad/);
    await waitFor(() => expect(primaries(r.container)[0].disabled).toBe(false));
    fireEvent.click(primaries(r.container)[0]);
    expect(await screen.findByRole("heading", { level: 1, name: "강성 평가 스터디" })).toBeTruthy();
    const rec = r.server.doe.recs[r.server.doe.recs.length - 1];
    expect(rec.out.scenario).toBe("select");
    expect(rec.out.inputs).toMatchObject({ bead_source: "auto", select_base: "mesh" });
    expect(rec.stepUpload).toBeTruthy();
    // 상세: ② 위치·하위 라디오 자동 탐지(읽기만)·기준 칩
    expect(radio(/② 다른 모델\(B 메시\)/).checked).toBe(true);
    expect(radio("자동 탐지").checked).toBe(true);
    expect(screen.getByTestId("doe-base-chip").textContent).toBe("기준 B 메시 · 셀 매핑");
  }, 15000);

  it("기존 same·mesh 스터디는 열리고 ①·② 위치에 '이전 방식'", async () => {
    renderApp("/p/p-body/doe/doe-2", "power");
    await waitFor(() => expect(radio(/② 다른 모델\(B 메시\)/).checked).toBe(true));
    expect(screen.getByTestId("doe-legacy").textContent).toMatch(/이전 방식/);
    expect(screen.queryByTestId("doe-beaddef")).toBeNull();
  });
});
