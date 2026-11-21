// V-0244-JIG-13(esl_jig_case.md §6.2·§12): 지그 3방식 그룹 탭 — 펼침(≥2201)·접힘(≤2200 팝오버·키보드·mark·사유),
// group 없으면 DOM 동일, 옛 응답(새 행 없음) = 이전 화면, 출처 이름 비교 없음.
import { useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TABS_SRC from "../view3d/SourceTabs.tsx?raw";
import SOURCES_SRC from "../view3d/sources.ts?raw";
import { SourceTabs } from "../view3d/SourceTabs";
import { GROUPS, SOURCE_ROWS, caseTabItems, groupFieldsOf, tabItemsOf, valTabItems, type SourceTabItem } from "../view3d/sources";
import { LOAD_SOURCES, tabState } from "../pages/doe/doeTabs";
import { valSourceRows } from "../mock/valsrcmock";
import type { DoeResultOut, ValidationOut, View3dSourcesOut } from "../api/types";

function setWide(wide: boolean) {
  const mm = (q: string) => ({ matches: q.includes("min-width: 2201px") ? wide : !wide, media: q, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, onchange: null, dispatchEvent: () => false });
  vi.stubGlobal("matchMedia", mm);
  window.matchMedia = mm as unknown as typeof window.matchMedia;
}
afterEach(() => {
  vi.unstubAllGlobals();
  // @ts-expect-error 시험 정리
  delete window.matchMedia;
});

const row = (key: string, available: boolean, reason: string | null = null) => ({ key, available, reason });
const SIX = [row("jig", true), row("jig_disp", true), row("jig_spring", false, "이 ESL 결과에는 지그 스프링 계산이 없습니다"), row("full", true), row("bforce", true), row("fint", false, "없음")];
const FOUR = SIX.filter((r) => !r.key.startsWith("jig_"));

function Harness({ items, initial = "full", onSet }: { items: readonly SourceTabItem[]; initial?: string; onSet?: (k: string) => void }) {
  const [tab, setTab] = useState(initial);
  return <SourceTabs items={items} tab={tab} setTab={(k) => { onSet?.(k); setTab(k); }} label="3D 하중 출처" prefix="v3d-src" testId="v3d-src-tab" whyTestId="v3d-src-tab-why" />;
}
const items6 = () => caseTabItems({ esl_run_id: "r", default: "full", rows: SIX.map((r) => ({ ...r, code: null, resp: r.available, resp_code: null, resp_reason: null, rigid: null })) } as unknown as View3dSourcesOut)!;

describe("출처 표 열(소스)", () => {
  it("SOURCE_ROWS 6행 — jig 3행은 group·short 열, 옛 3행은 group 없음; GROUPS.jig = 지그 ESL", () => {
    expect(SOURCE_ROWS.map((r) => r.key)).toEqual(["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]);
    expect(SOURCE_ROWS.filter((r) => r.group).map((r) => [r.key, r.short, r.group])).toEqual([["jig", "고정", "jig"], ["jig_disp", "변위", "jig"], ["jig_spring", "스프링", "jig"]]);
    expect(GROUPS.jig.label).toBe("지그 ESL");
    expect(SOURCE_ROWS.find((r) => r.key === "jig_disp")!.caution).toContain("낙하 결과에서 그대로 강제");
  });
  it("새 응답(6행) = 그룹 속성 + 이름, 사유 문구는 이름 포함", () => {
    const it = items6();
    expect(it.map((i) => [i.key, i.label, i.group ?? null, i.short ?? null])).toEqual([["jig", "지그 고정", "jig", "고정"], ["jig_disp", "지그 변위", "jig", "변위"], ["jig_spring", "지그 스프링", "jig", "스프링"], ["full", "전 노드 ESL", null, null], ["bforce", "경계력 ESL", null, null], ["fint", "내력 ESL", null, null]]);
    expect(it[2].why).toBe("지그 스프링 불가 — 이 ESL 결과에는 지그 스프링 계산이 없습니다");
    expect(it[1].caution).toBeTruthy();
  });
  it("옛 응답(새 행 없음) = 4행·group 없음·jig 탭 이름 '지그 ESL'(v0.24.3 화면)", () => {
    const it = tabItemsOf(FOUR)!;
    expect(it.map((i) => [i.key, i.label, i.group ?? null])).toEqual([["jig", "지그 ESL", null], ["full", "전 노드 ESL", null], ["bforce", "경계력 ESL", null], ["fint", "내력 ESL", null]]);
    expect(it[0].title).toBe(GROUPS.jig.title);
  });
  it("스터디 LOAD_SOURCES 6행(키 = SOURCE_ROWS) · 새 방식 탭은 옛 스냅샷에서 JIG_METHOD_NOT_RUN 사유로 비활성", () => {
    expect(LOAD_SOURCES.map((s) => s.key)).toEqual(SOURCE_ROWS.map((r) => r.key));
    const r = { rank_views: { jig: {} }, metric_effective: "jig", warnings: [], ranking: [], baseline: {} } as unknown as DoeResultOut;
    const ts = tabState(r);
    expect(ts.ok.jig).toBe(true);
    expect(ts.ok.jig_disp).toBe(false);
    expect(ts.reason.jig_disp).toBe("이 스터디에서 계산하지 않은 방식입니다: 지그 변위 — 새 스터디·복제에서 계산(rank.jig.methods)");
    expect(ts.reason.jig_spring).toContain("지그 스프링");
    expect(groupFieldsOf("jig_disp")).toMatchObject({ group: "jig", short: "변위" });
    expect(groupFieldsOf("full")).toEqual({});
  });
});

describe("SourceTabs 그룹 — ≥2201px 한 줄 펼침", () => {
  it("머리 글자(비대화형) + 하위 탭 3 + 나머지, 글자 = short · aria-label = 전체 이름 · title(툴팁) · 비활성 사유", () => {
    setWide(true);
    render(<Harness items={items6()} />);
    const tl = screen.getByRole("tablist");
    const head = tl.querySelector(".seg-group") as HTMLElement;
    expect(head.textContent).toBe("지그 ESL");
    expect(head.tagName).toBe("SPAN");
    const tabs = within(tl).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["고정", "변위⚠", "스프링", "전 노드 ESL", "경계력 ESL", "내력 ESL"]);
    expect(tabs[0].getAttribute("aria-label")).toBe("지그 ESL 지그 고정");
    expect(tabs[3].getAttribute("aria-label")).toBeNull();
    expect(tabs[1].title).toContain("낙하 결과에서 그대로 강제");
    expect(tabs[2].getAttribute("aria-disabled")).toBe("true");
    expect(tabs[2].title).toContain("지그 스프링 불가");
    expect(tl.querySelector("#v3d-src-why-jig_spring")!.textContent).toContain("지그 스프링 불가");
    // 높이 불변: 줄바꿈·새 버튼 없음(탭 6 + 비대화형 머리 1)
    expect(tl.querySelectorAll("button").length).toBe(6);
    expect(screen.queryByRole("listbox")).toBeNull();
  });
  it("화살표 = 하위 탭도 최상위처럼 순서대로, 비활성 탭 포커스 = 사유 줄, Enter = 선택(사용 가능만)", () => {
    setWide(true);
    const onSet = vi.fn();
    render(<Harness items={items6()} onSet={onSet} />);
    const t = (k: string) => document.getElementById(`v3d-src-tab-${k}`) as HTMLElement;
    act(() => t("jig").focus());
    fireEvent.keyDown(t("jig"), { key: "ArrowRight" });
    expect(document.activeElement).toBe(t("jig_disp"));
    fireEvent.keyDown(t("jig_disp"), { key: "ArrowRight" });
    expect(document.activeElement).toBe(t("jig_spring"));
    expect(screen.getByTestId("v3d-src-tab-why").textContent).toContain("지그 스프링 불가");
    fireEvent.click(t("jig_spring"));
    expect(onSet).not.toHaveBeenCalled();
    fireEvent.click(t("jig_disp"));
    expect(onSet).toHaveBeenCalledWith("jig_disp");
  });
});

describe("SourceTabs 그룹 — ≤2200px 접힘 + 팝오버", () => {
  it("탭 1개 '지그 ESL · 고정 ▾'(선택이 그룹 안) / 그룹 밖이면 '지그 ESL ▾' — 새 버튼 0, 팝오버는 닫혀 있음", () => {
    setWide(false);
    const { rerender } = render(<Harness items={items6()} initial="jig" />);
    const tl = screen.getByRole("tablist");
    const tabs = within(tl).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["지그 ESL · 고정 ▾", "전 노드 ESL", "경계력 ESL", "내력 ESL"]);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    expect(tabs[0].getAttribute("aria-haspopup")).toBe("listbox");
    expect(tl.querySelector(".seg-group")).toBeNull();
    expect(screen.queryByRole("listbox")).toBeNull();
    rerender(<Harness items={items6()} initial="full" />);
  });
  it("그룹 밖 선택이면 머리 글자만 '지그 ESL ▾'", () => {
    setWide(false);
    render(<Harness items={items6()} initial="full" />);
    expect(within(screen.getByRole("tablist")).getAllByRole("tab")[0].textContent).toBe("지그 ESL ▾");
  });
  it("클릭·Enter = 팝오버(listbox/option) — 항목 = short + 비활성 사유 문구, 위아래 화살표, Enter 선택 후 닫힘, Esc 닫고 포커스 복귀", async () => {
    setWide(false);
    const onSet = vi.fn();
    render(<Harness items={items6()} initial="full" onSet={onSet} />);
    const g = screen.getAllByRole("tab")[0];
    g.focus();
    fireEvent.keyDown(g, { key: "Enter" });
    const lb = await screen.findByRole("listbox");
    const opts = within(lb).getAllByRole("option");
    expect(opts.map((o) => o.getAttribute("data-tab"))).toEqual(["jig", "jig_disp", "jig_spring"]);
    expect(g.getAttribute("aria-expanded")).toBe("true");
    expect(opts[0].textContent).toBe("고정");
    expect(opts[1].textContent).toContain("변위");
    expect(opts[1].textContent).toContain("⚠");
    expect(opts[2].textContent).toContain("지그 스프링 불가 — 이 ESL 결과에는 지그 스프링 계산이 없습니다"); // 마우스 없이 보이는 사유
    expect(opts[2].getAttribute("aria-disabled")).toBe("true");
    await waitFor(() => expect(document.activeElement).toBe(opts[0]));
    fireEvent.keyDown(opts[0], { key: "ArrowDown" });
    expect(document.activeElement).toBe(opts[1]);
    fireEvent.keyDown(opts[1], { key: "ArrowDown" });
    fireEvent.keyDown(opts[2], { key: "Enter" }); // 비활성 — 선택 안 됨, 열려 있음
    expect(onSet).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeTruthy();
    fireEvent.keyDown(opts[2], { key: "ArrowUp" });
    expect(document.activeElement).toBe(opts[1]);
    fireEvent.keyDown(opts[1], { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(g);
    fireEvent.click(g);
    fireEvent.click(within(await screen.findByRole("listbox")).getAllByRole("option")[1]);
    expect(onSet).toHaveBeenCalledWith("jig_disp");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getAllByRole("tab")[0].textContent).toBe("지그 ESL · 변위⚠ ▾");
  });
  it("좌우 화살표 = 최상위(그룹 1탭 + 나머지), 팝오버는 절대 위치 CSS(높이 불변)", () => {
    setWide(false);
    render(<Harness items={items6()} initial="full" />);
    const tabs = screen.getAllByRole("tab");
    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(document.activeElement).toBe(tabs[1]);
    fireEvent.keyDown(tabs[1], { key: "ArrowLeft" });
    expect(document.activeElement).toBe(tabs[0]);
  });
  it("④ mark: 그룹 탭 = 선택 하위의 mark, 팝오버 항목마다 mark(testid 구분)", async () => {
    setWide(false);
    const val = { id: "v", esl_run_id: "e", verdict: "PASS", status: "PASS", fail_reasons: [], undetermined_reason: null } as unknown as ValidationOut;
    const rows = valSourceRows(val, "ok", true, true);
    const items = valTabItems({ validation_id: "v", default: "full", rows }, false)!;
    expect(items.map((i) => i.key)).toEqual(["jig", "jig_disp", "jig_spring", "full", "bforce", "fint"]);
    render(<Harness items={items} initial="jig_disp" />);
    const g = screen.getAllByRole("tab")[0];
    expect(g.textContent).toBe("지그 ESL · 변위PASS ⚠ ▾");
    expect(within(g).getByTestId("v3d-src-mark-jig_disp").textContent).toBe("PASS ⚠");
    fireEvent.click(g);
    const lb = await screen.findByRole("listbox");
    expect(within(lb).getByTestId("v3d-src-opt-mark-jig").textContent).toBe("PASS");
    expect(within(lb).getByTestId("v3d-src-opt-mark-jig_disp").textContent).toBe("PASS ⚠");
    expect(within(lb).getByTestId("v3d-src-opt-why-jig_spring").textContent).toContain("지그 스프링 불가");
    // ④ 조건 툴팁: 서버 cond_text + 한계 문구
    expect(items[1].title).toContain("값 낙하 변위");
    expect(items[1].title).toContain("tie 변위를 낙하 결과에서 그대로 강제");
  });
});

describe("DOM 동일·이름 비교 없음", () => {
  it("group 속성이 없는 항목 = 폭과 무관하게 같은 DOM(머리 글자·팝오버 없음)", () => {
    const base: SourceTabItem[] = [{ key: "a", label: "에이", title: "ta", ok: true, why: null }, { key: "b", label: "비", title: "tb", ok: false, why: "비 불가 — 사유" }];
    setWide(true);
    const wide = render(<SourceTabs items={base} tab="a" setTab={() => {}} label="L" prefix="p" testId="t" whyTestId="w" />).container.innerHTML;
    document.body.innerHTML = "";
    setWide(false);
    const narrow = render(<SourceTabs items={base} tab="a" setTab={() => {}} label="L" prefix="p" testId="t" whyTestId="w" />).container.innerHTML;
    expect(narrow).toBe(wide);
    expect(wide).not.toContain("seg-group");
    expect(wide).not.toContain("aria-label=\"지그");
  });
  it("소스 grep: SourceTabs·sources 가 출처 키 리터럴(\"jig\" 등)로 비교·분기하지 않는다(열 group·optional·caution 만 읽음)", () => {
    for (const [f, raw] of [["SourceTabs.tsx", TABS_SRC], ["sources.ts(함수 부분)", SOURCES_SRC.slice(SOURCES_SRC.indexOf("export const SOURCE_KEYS"))]] as const) {
      const code = raw.split("\n").filter((l) => !l.trim().startsWith("//") && !l.trim().startsWith("*") && !l.trim().startsWith("/**")).join("\n");
      expect(code, f).not.toMatch(/(===|!==|==|!=)\s*"(jig|jig_disp|jig_spring|full|bforce|fint)"/);
      expect(code, f).not.toMatch(/"(jig|jig_disp|jig_spring|full|bforce|fint)"\s*(===|!==|==|!=)/);
    }
  });
});
