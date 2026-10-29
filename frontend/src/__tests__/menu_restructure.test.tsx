// v0.10.0 메뉴 재구성(계약 esl_menu_restructure.md §4~§8, V-MR-17~23): 라우트 리다이렉트·최상단 메뉴·4단계·
// ② 지지 요약(BLOCKED 때만 고급 칸)·④ 등록 규칙·라이브러리 탭·선택 줄·내보내기 창·LEGACY 재검증.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { App } from "../app/App";
import { MockServer, createMockFetch } from "../mock/server";
import { renderApp } from "../test/render";
import { linkPath } from "../api/history";
import { STEP_OF_STAGE, stepOfStage } from "../shell/StageStepper";
import { isLibraryPath } from "../shell/Shell";
import { MOVED_EXPORT_TEXT } from "../pages/CasePage";
import { SUPPORT_ADVANCED_LABEL, SUPPORT_BLOCKED_TITLE } from "../components/SupportSummary";
import { SUPPORT_BLOCKED_REASON } from "../stages/common";
import { LIB_TABS, PROMOTED_TEXT, actionBlocks } from "../pages/library/LibraryList";
import { legacyBlockText } from "../pages/library/common";
import { BUNDLE_LABEL } from "../components/BundleButton";
import { NO_PERMISSION } from "../app/AppContext";
import type { EntryOut } from "../api/types";

function LocProbe() {
  const l = useLocation();
  return <div data-testid="loc">{l.pathname + l.search + l.hash}</div>;
}
function renderAt(path: string, setup?: (s: MockServer) => void) {
  const server = new MockServer({ user: "power" });
  setup?.(server);
  globalThis.fetch = createMockFetch(server);
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <LocProbe />
    </MemoryRouter>,
  );
  return { server, ...view };
}
const loc = () => screen.getByTestId("loc").textContent;
const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const C = "/p/p-body/c/c-demo";

describe("V-MR-17 라우트 리다이렉트", () => {
  it("옛 /stage/1..6 → /step/1,2,2,3,4,4 (replace, query 유지), ⑥은 ?moved=export 안내", async () => {
    const cases: [string, string][] = [
      ["/stage/1", "/step/1"],
      ["/stage/2", "/step/2"],
      ["/stage/3", "/step/2"],
      ["/stage/4?run=run-1", "/step/3?run=run-1"],
      ["/stage/5?val=val-1", "/step/4?val=val-1"],
      ["/stage/6", "/step/4?moved=export"],
    ];
    for (const [from, to] of cases) {
      const { unmount } = renderAt(C + from);
      await waitFor(() => expect(loc()).toBe(C + to));
      unmount();
    }
    renderAt(`${C}/stage/6`);
    expect((await screen.findByTestId("moved-export")).textContent).toContain(MOVED_EXPORT_TEXT);
    expect(within(screen.getByTestId("moved-export")).getByRole("link", { name: "ESL 라이브러리 열기" }).getAttribute("href")).toBe("/p/p-body/library");
    expect(await screen.findByRole("heading", { level: 2, name: "④ 검증" })).toBeTruthy();
  });

  it("/p/:pid/c/:cid → step/1, 잘못된 번호 → step/1", async () => {
    const { unmount } = renderAt(C);
    await waitFor(() => expect(loc()).toBe(`${C}/step/1`));
    unmount();
    renderAt(`${C}/step/5`);
    await waitFor(() => expect(loc()).toBe(`${C}/step/1`));
  });

  it("라이브러리 옛 탭·경로: ?tab=doe → study, ?tab=comparisons → analyses#comparisons, /doe·/opt → 탭", async () => {
    const cases: [string, string][] = [
      ["/p/p-body/library?tab=doe", "/p/p-body/library?tab=study"],
      ["/p/p-body/library?tab=comparisons", "/p/p-body/library?tab=analyses#comparisons"],
      ["/p/p-body/doe", "/p/p-body/library?tab=study"],
      ["/p/p-body/opt", "/p/p-body/library?tab=opt"],
    ];
    for (const [from, to] of cases) {
      const { unmount } = renderAt(from);
      await waitFor(() => expect(loc()).toBe(to));
      unmount();
    }
  });

  it("이력 링크: 서버 links.stage(옛 1..6) → stepOfStage 매핑", () => {
    expect(STEP_OF_STAGE).toEqual({ 1: 1, 2: 2, 3: 2, 4: 3, 5: 4, 6: 4 });
    expect(stepOfStage(undefined)).toBe(1);
    expect(linkPath("p", "c", { stage: 4, query: { run: "r1" } })).toBe("/p/p/c/c/step/3?run=r1");
    expect(linkPath("p", "c", { stage: 5, query: { val: "v1" } })).toBe("/p/p/c/c/step/4?val=v1");
    expect(linkPath("p", "c", { stage: 3 })).toBe("/p/p/c/c/step/2");
    expect(linkPath("p", "c", { stage: 6 })).toBe("/p/p/c/c/step/4");
  });
});

describe("V-MR-18 최상단 메뉴·스텝퍼·케이스 헤더", () => {
  it("활성 규칙: /library·/opt·/doe = 라이브러리, 그 외 = 생성", () => {
    for (const p of ["/p/x/library", "/p/x/library/analyses/new", "/p/x/opt/new", "/p/x/doe/d1"]) expect(isLibraryPath(p)).toBe(true);
    for (const p of ["/p/x", "/p/x/cases/new", "/p/x/c/c1/step/2", "/p/x/history", "/p/x/jobs/j1"]) expect(isLibraryPath(p)).toBe(false);
  });

  it("케이스: 메뉴 [ESL 생성](활성)·[ESL 라이브러리], 경로 막대 ESL 생성 › 케이스 › ② t*·지지점, 스텝퍼 4단계, 헤더 [결과 받기(zip)]", async () => {
    renderApp(`${C}/step/2`);
    const menu = await screen.findByRole("navigation", { name: "전역 메뉴" });
    expect(within(menu).getByRole("link", { name: "ESL 생성" }).getAttribute("aria-current")).toBe("page");
    expect(within(menu).getByRole("link", { name: "ESL 라이브러리" }).getAttribute("aria-current")).toBeNull();
    const crumbs = screen.getByRole("navigation", { name: "경로" });
    await within(crumbs).findByText("후방 충돌 40kph");
    expect(crumbs.textContent).toMatch(/ESL 생성›후방 충돌 40kph›② t\*·지지점$/);
    const steps = screen.getByRole("navigation", { name: "단계" });
    expect([...steps.querySelectorAll(".step-name")].map((x) => x.textContent)).toEqual(["입력", "t*·지지점", "ESL", "검증"]);
    expect(within(steps).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([1, 2, 3, 4].map((n) => `${C}/step/${n}`));
    expect(within(screen.getByRole("navigation", { name: "Case 메뉴" })).getByRole("button", { name: BUNDLE_LABEL })).toBeTruthy();
  });

  it("라이브러리: 탭 5개 이름, 경로 막대 ESL 라이브러리 › 탭 이름", async () => {
    renderApp("/p/p-body/library");
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["ESL 목록", "강성 평가 스터디", "비드 최적화", "종합분석·버전 비교", "템플릿"]);
    expect(LIB_TABS.map((t) => t.id)).toEqual(["items", "study", "opt", "analyses", "templates"]);
    expect(screen.getByRole("navigation", { name: "경로" }).textContent).toMatch(/ESL 라이브러리›ESL 목록$/);
    fireEvent.click(screen.getByRole("tab", { name: "강성 평가 스터디" }));
    await waitFor(() => expect(screen.getByRole("navigation", { name: "경로" }).textContent).toMatch(/ESL 라이브러리›강성 평가 스터디$/));
  });
});

describe("V-MR-19 ② t*·지지점", () => {
  it("지지 세트가 없으면 같은 t*라도 't* 확정' 활성 → 자동 3-2-1 저장(OK) → 카드 3행·자동 배지", async () => {
    const { container, server } = renderApp(`${C}/step/2`, "power", (s) => {
      s.findCase("c-demo")!.current_support_set_id = null;
      s.findCase("c-demo")!.tstar = { ...s.findCase("c-demo")!.tstar!, support_auto: null };
    });
    expect((await screen.findByTestId("support-summary")).textContent).toContain("t* 확정 시 자동으로 정합니다");
    await screen.findByRole("img", { name: /max-hold 곡선/ });
    const btn = primaries(container)[0];
    await waitFor(() => expect(btn.disabled).toBe(false));
    fireEvent.click(btn);
    await waitFor(() => expect(server.findCase("c-demo")!.current_support_set_id).toBeTruthy());
    expect(server.findCase("c-demo")!.tstar!.support_auto!.status).toBe("OK");
    const card = screen.getByTestId("support-summary");
    await waitFor(() => expect(within(card).getAllByRole("row")).toHaveLength(4));
    expect(screen.getByText("자동")).toBeTruthy();
    expect(screen.queryByTestId("support-advanced")).toBeNull();
    // 지지 세트가 생기고 t*가 같으면 다시 비활성
    await waitFor(() => expect(primaries(container)[0].parentElement!.title).toBe("현재 확정된 t*와 같습니다"));
  });

  it("사용자 지정(이전 버전에서 편집) 배지 — 편집 칸 없음", async () => {
    renderApp(`${C}/step/2`, "power", (s) => {
      s.supportSets.find((x) => x.id === "ss-1")!.source = "user";
    });
    expect(await screen.findByText("사용자 지정(이전 버전에서 편집)")).toBeTruthy();
    expect(screen.queryAllByRole("textbox", { name: /지지 노드/ })).toHaveLength(0);
  });

  it("BLOCKED: 사유 목록 + 접힌 '고급' 칸 → 검사 실패 422 problems 표시 → 통과하면 MANUAL·② 완료, ③ 차단 사유", async () => {
    const { server } = renderApp(`${C}/step/2`, "power", (s) => s.demoSupportBlocked("c-demo"));
    const box = await screen.findByTestId("support-blocked");
    expect(box.textContent).toContain(SUPPORT_BLOCKED_TITLE);
    expect(within(box).getByTestId("support-problems").textContent).toContain("지지 3점이 거의 한 줄입니다(면적비 0.04 < 0.10)");
    const dots = screen.getByRole("navigation", { name: "단계" }).querySelectorAll("[data-state]");
    expect(dots[1].getAttribute("data-state")).toBe("failed");
    const adv = screen.getByTestId("support-advanced") as HTMLDetailsElement;
    expect(adv.open).toBe(false);
    expect(within(adv).getByText(SUPPORT_ADVANCED_LABEL)).toBeTruthy();
    const ins = within(adv).getAllByRole("textbox", { name: /지지 노드/ });
    expect(ins).toHaveLength(3);
    const save = within(adv).getByRole("button", { name: "지정 저장" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    ["10", "11", "12"].forEach((v, k) => fireEvent.change(ins[k], { target: { value: v } }));
    fireEvent.click(save);
    expect((await within(adv).findByTestId("support-problems")).textContent).toContain("지지 두 점이 너무 가깝습니다");
    expect(server.findCase("c-demo")!.current_support_set_id).toBeNull();
    ["1", "40", "3200"].forEach((v, k) => fireEvent.change(ins[k], { target: { value: v } }));
    fireEvent.click(save);
    await waitFor(() => expect(server.findCase("c-demo")!.current_support_set_id).toBeTruthy());
    expect(server.findCase("c-demo")!.tstar!.support_auto!.status).toBe("MANUAL");
    expect(await screen.findByText("사용자 지정(고급)")).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId("support-advanced")).toBeNull());
  });

  it("BLOCKED Case 의 ③ ESL 계산 비활성 사유 = '② 지지점 자동 선택 실패', 서버 409 support_blocked", async () => {
    const { container, server } = renderApp(`${C}/step/3`, "power", (s) => s.demoSupportBlocked("c-demo"));
    await screen.findByRole("heading", { level: 2, name: "③ ESL" });
    await waitFor(() => expect(primaries(container)[0].parentElement!.title).toBe(SUPPORT_BLOCKED_REASON));
    const r = server.handle("POST", "/cases/c-demo/jobs", new URLSearchParams(), { job_type: "ESL_SOLVE", params: {} });
    expect(r.status).toBe(409);
    expect((r.body as { detail: { missing: string[]; support_blocked: boolean } }).detail).toMatchObject({ missing: ["support_set"], support_blocked: true });
  });

  it("조회 사용자: BLOCKED 여도 고급 칸 숨김", async () => {
    renderApp(`${C}/step/2`, "general", (s) => s.demoSupportBlocked("c-demo"));
    await screen.findByTestId("support-blocked");
    expect(screen.queryByTestId("support-advanced")).toBeNull();
  });
});

const rowsOf = () => within(screen.getByRole("table", { name: "라이브러리 항목" })).getAllByRole("row").slice(1);
const box = (label: string) => screen.getByRole("checkbox", { name: label }) as HTMLInputElement;
const btn = (name: string | RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;

describe("V-MR-21 ESL 목록 선택 줄", () => {
  it("동작별 비활성 사유(순수 함수): LEGACY → 강성·최적화·종합분석, 크기 → 강성·최적화, 내보내기 = 최대 개수만", () => {
    const e = (id: string, inch: number, L: number, eligible = true) => ({ id, status: "ACTIVE", model: { inch }, size: { inch, L_xi: L, L_eta: L / 2 }, quality: {}, eligible }) as unknown as EntryOut;
    const b = actionBlocks([e("a", 75, 1660), e("b", 75, 1661, false)], 0.02);
    expect(b).toMatchObject({ nBad: 1, export: null, study: legacyBlockText(1), opt: legacyBlockText(1), analysis: legacyBlockText(1) });
    const s = actionBlocks([e("a", 75, 1660), e("c", 65, 1440)], 0.02);
    expect(s.study).toMatch(/크기 다름\(기준 75형/);
    expect(s.analysis).toBeNull();
    expect(actionBlocks(Array.from({ length: 51 }, (_, k) => e(`x${k}`, 75, 1660)), 0.02, 50).export).toMatch(/최대 50개/);
    // 상한은 서버 설정(ui.library_export_max_entries) — 모르면 화면 검사 없음(서버 422 TOO_MANY_ENTRIES)
    expect(actionBlocks(Array.from({ length: 51 }, (_, k) => e(`x${k}`, 75, 1660)), 0.02, null).export).toBeNull();
    expect(actionBlocks(Array.from({ length: 4 }, (_, k) => e(`x${k}`, 75, 1660)), 0.02, 3).export).toMatch(/최대 3개/);
  });

  it("머리 체크 = 보이는 활성 행 전체, LEGACY 포함 선택 → 요약 'LEGACY 1' + 강성·최적화·종합분석 비활성, 내보내기 가능, 선택 해제", async () => {
    const { container } = renderApp("/p/p-body/library");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    fireEvent.change(screen.getByRole("combobox", { name: "모델" }), { target: { value: "85QN80H" } });
    await waitFor(() => expect(rowsOf()).toHaveLength(2));
    fireEvent.click(box("보이는 항목 모두 선택"));
    expect(screen.getByTestId("pick-bar").textContent).toMatch(/선택 2개 · LEGACY 1/);
    for (const n of ["강성 평가 스터디 (2)", "비드 최적화 (2)", "종합분석 (2)"]) {
      expect(btn(n).disabled).toBe(true);
      expect(btn(n).parentElement!.title).toBe(legacyBlockText(1));
    }
    expect(screen.getByTestId("pick-why").textContent).toContain(legacyBlockText(1));
    expect(primaries(container)[0].textContent).toBe("내보내기 (2)");
    expect(primaries(container)[0].disabled).toBe(false);
    fireEvent.click(btn("선택 해제"));
    expect(screen.queryByTestId("pick-bar")).toBeNull();
  });

  it("[종합분석 (n)] → /library/analyses/new?entries=… → 선택한 ESL n개로 채움(filters.entry_ids)", async () => {
    const { server } = renderAt("/p/p-body/library");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    fireEvent.click(box("75QN80H v072 146 선택"));
    fireEvent.click(box("75QN80H v072 14 선택"));
    fireEvent.click(btn("종합분석 (2)"));
    await waitFor(() => expect(loc()).toBe("/p/p-body/library/analyses/new?entries=le-1,le-2"));
    expect((await screen.findByTestId("picked-entries")).textContent).toContain("선택한 ESL 2개");
    expect(await screen.findByText("포함 항목 2개")).toBeTruthy();
    const run = screen.getByRole("button", { name: "분석 실행" }) as HTMLButtonElement;
    await waitFor(() => expect(run.disabled).toBe(false));
    fireEvent.click(run);
    await screen.findByRole("heading", { level: 1, name: "종합분석" });
    expect(server.analyses[server.analyses.length - 1].filters).toEqual({ entry_ids: ["le-1", "le-2"] });
  });

  it("종합분석 지정 항목에 LEGACY 가 있으면 화면 비활성 + 서버 422 ENTRY_NOT_ELIGIBLE", async () => {
    const { server } = renderApp("/p/p-body/library/analyses/new?entries=le-1,le-7");
    const run = (await screen.findByRole("button", { name: "분석 실행" })) as HTMLButtonElement;
    await waitFor(() => expect(run.parentElement!.title).toBe(legacyBlockText(1)));
    const r = server.handle("POST", "/library/analyses", new URLSearchParams(), { project_id: "p-body", filters: { entry_ids: ["le-1", "le-7"] } });
    expect((r.body as { detail: { code: string } }).detail.code).toBe("ENTRY_NOT_ELIGIBLE");
  });
});

describe("V-MR-22 내보내기 창", () => {
  it("형식·ID 옵션 → 요청 본문, 진행(폴링) → [zip 받기], LEGACY 경고", async () => {
    const { server, container } = renderApp("/p/p-body/library");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    ["75QN80H v072 146 선택", "75QN80H v072 14 선택", "85QN80H v072 245 선택"].forEach((l) => fireEvent.click(box(l)));
    fireEvent.click(primaries(container)[0]);
    const dlg = screen.getByRole("dialog", { name: "내보내기 — ESL 3개" });
    expect(within(dlg).getByTestId("export-legacy").textContent).toBe("LEGACY 1개 포함 — 하중은 같고 판정 체계만 이전입니다");
    const checks = within(dlg).getAllByRole("checkbox") as HTMLInputElement[];
    expect(checks.map((c) => c.checked)).toEqual([true, true, true]);
    fireEvent.click(within(dlg).getByRole("checkbox", { name: "CSV" }));
    fireEvent.click(within(dlg).getByRole("radio", { name: "지정" }));
    const start = within(dlg).getByRole("button", { name: "내보내기 시작" }) as HTMLButtonElement;
    fireEvent.change(within(dlg).getByRole("textbox", { name: "ID 시작 값" }), { target: { value: "x" } });
    expect(start.disabled).toBe(true);
    expect(start.parentElement!.title).toMatch(/0 이상 정수/);
    fireEvent.change(within(dlg).getByRole("textbox", { name: "ID 시작 값" }), { target: { value: "8000000" } });
    expect(within(dlg).getAllByRole("button").filter((b) => b.hasAttribute("data-primary"))).toHaveLength(1);
    fireEvent.click(start);
    const prog = await within(dlg).findByTestId("export-progress");
    const b = server.exportBatches[0].batch;
    expect(b.targets).toEqual(["radioss_inc", "fem"]);
    expect(b.options).toMatchObject({ id_offset: 8000000, id_policy: "per_model_sequential" });
    expect(b.items.map((x) => x.entry_id)).toEqual(["le-1", "le-2", "le-7"]);
    // 같은 Case 별 EXPORT 작업 1개(origin library) — 목 항목은 Case 가 모두 달라 3개
    expect(server.jobs.filter((j) => j.job_type === "EXPORT" && j.params.origin === "library")).toHaveLength(3);
    expect((within(dlg).getByRole("button", { name: "zip 받기" }) as HTMLButtonElement).disabled).toBe(true);
    server.drain();
    await waitFor(() => expect(prog.textContent).toMatch(/완료 · 완료 3\/3/), { timeout: 6000 });
    const zip = within(dlg).getByRole("button", { name: "zip 받기" }) as HTMLButtonElement;
    expect(zip.disabled).toBe(false);
    expect(zip.hasAttribute("data-primary")).toBe(true);
    // 같은 모델(le-1·le-2 topo 같음)은 ID 가 이어진다
    const it1 = server.exportBatches[0].batch.items[0].id_range!;
    const it2 = server.exportBatches[0].batch.items[1].id_range!;
    expect(it2[0]).toBe(it1[1] + 1);
    expect(it1[0]).toBe(8000000);
    expect(prog.textContent).toContain(`ID ${it1[0]}–${it1[1]}`);
  }, 12000);

  it("일부 실패 → 실패 사유 표 + zip 가능(일부 실패), 최근 내보내기에서 다시 받기", async () => {
    const { server, container } = renderApp("/p/p-body/library", "power", (s) => s.failExportEntries.add("le-2"));
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    ["75QN80H v072 146 선택", "75QN80H v072 14 선택"].forEach((l) => fireEvent.click(box(l)));
    fireEvent.click(primaries(container)[0]);
    const dlg = screen.getByRole("dialog");
    fireEvent.click(within(dlg).getByRole("button", { name: "내보내기 시작" }));
    await within(dlg).findByTestId("export-progress");
    server.drain();
    const fail = await within(dlg).findByRole("table", { name: "실패 항목" }, { timeout: 6000 });
    expect(fail.textContent).toContain("항목 파일(raw.npz)이 없습니다");
    expect(within(dlg).getByTestId("export-progress").textContent).toMatch(/일부 실패/);
    expect((within(dlg).getByRole("button", { name: "zip 받기" }) as HTMLButtonElement).disabled).toBe(false);
    // 닫았다 다시 열면 '최근 내보내기'
    fireEvent.click(within(dlg).getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(primaries(container)[0]);
    const dlg2 = screen.getByRole("dialog");
    const recent = dlg2.querySelector("details.export-recent") as HTMLDetailsElement;
    recent.open = true;
    fireEvent(recent, new Event("toggle"));
    const list = await within(dlg2).findByRole("list", { name: "최근 내보내기" });
    expect(list.textContent).toMatch(/ESL 2개 · inc·fem·csv · 일부 실패/);
    expect(within(list).getByRole("button", { name: "zip 받기" })).toBeTruthy();
  }, 12000);

  it("서버 오류: 같은 Case 에 진행 중 EXPORT → 409 CASE_JOB_BUSY 안내, Esc 로 닫기", async () => {
    const { container } = renderApp("/p/p-body/library", "power", (s) => {
      s.handle("POST", "/library/exports", new URLSearchParams(), { project_id: "p-body", entry_ids: ["le-1"], targets: ["csv"], options: { id_offset: "auto" } });
    });
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    fireEvent.click(box("75QN80H v072 146 선택"));
    fireEvent.click(primaries(container)[0]);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "내보내기 시작" }));
    expect((await within(screen.getByRole("dialog")).findByRole("alert")).textContent).toMatch(/실행 중입니다\. 잠시 후 다시 시도하세요\./);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("V-MR-23 LEGACY 재검증", () => {
  it("LEGACY 배지(당시 PASS) + [재검증] → 진행 칩 → PROMOTED: 배지 사라짐 + 안내", async () => {
    const { server } = renderApp("/p/p-body/library");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    const row = () => box("85QN80H v072 245 선택").closest("tr")!;
    expect(within(row()).getByText("LEGACY")).toBeTruthy();
    expect(within(row()).getByText("당시 PASS")).toBeTruthy();
    // PASS 행에는 재검증 없음
    expect(within(box("75QN80H v072 146 선택").closest("tr")!).queryByRole("button", { name: "재검증" })).toBeNull();
    fireEvent.click(within(row()).getByRole("button", { name: "재검증" }));
    expect(await within(row()).findByTestId("reval-chip")).toBeTruthy();
    const j = server.jobs.find((x) => x.params.origin === "library_revalidate")!;
    expect(j.params).toMatchObject({ entry_id: "le-7", esl_run_id: "run-lib-7" });
    server.drain();
    expect((await screen.findByTestId("reval-toast", undefined, { timeout: 6000 })).textContent).toBe(PROMOTED_TEXT);
    await waitFor(() => expect(within(row()).queryByText("LEGACY")).toBeNull());
    expect(within(row()).getByText("PASS")).toBeTruthy();
    expect(server.entries.find((e) => e.id === "le-7")!.quality.revalidated?.from_status).toBe("LEGACY");
  }, 12000);

  it("사유와 함께 등록된 FAIL(Q1 A) 재검증 → KEPT_LEGACY 안내 + 폐기", async () => {
    const { server } = renderApp("/p/p-body/library");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    const row = () => box("65QN80H v072 26 선택").closest("tr")!;
    fireEvent.click(within(row()).getByRole("button", { name: "재검증" }));
    await within(row()).findByTestId("reval-chip");
    server.drain();
    const kept = await within(row()).findByTestId("reval-kept", undefined, { timeout: 6000 });
    expect(kept.textContent).toMatch(/현재 기준 FAIL\(DISP_RMS\) — LEGACY로 유지하거나 폐기하세요/);
    expect(within(row()).getByText("LEGACY")).toBeTruthy();
    fireEvent.click(within(kept).getByRole("button", { name: "폐기" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
  }, 12000);

  it("재검증 불가(revalidate_block) → 버튼 비활성 + 사유 툴팁, 조회 사용자 비활성", async () => {
    const reason = "추출이 바뀌었습니다 — Case를 다시 계산해 새로 등록하세요";
    const { unmount } = renderApp("/p/p-body/library", "power", (s) => {
      s.entries.find((e) => e.id === "le-7")!.revalidate_block = { code: "REVALIDATE_NOT_POSSIBLE", reason: "EXTRACT_CHANGED", message: reason };
    });
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    const b = within(box("85QN80H v072 245 선택").closest("tr")!).getByRole("button", { name: "재검증" }) as HTMLButtonElement;
    expect(b.disabled).toBe(true);
    expect(b.parentElement!.title).toBe(reason);
    unmount();
    renderApp("/p/p-body/library", "general");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    await waitFor(() => expect(screen.getByTestId("user").textContent).toContain("조회"));
    const g = within(box("85QN80H v072 245 선택").closest("tr")!).getByRole("button", { name: "재검증" }) as HTMLButtonElement;
    expect(g.disabled).toBe(true);
    expect(g.parentElement!.title).toBe(NO_PERMISSION);
  });
});

describe("통합 정합(v0.10.0)", () => {
  it("ESL_SOLVE 409 detail.support_blocked → '② 지지점 자동 선택 실패' 문구", async () => {
    const { ApiError, errorText } = await import("../api/client");
    const e = new ApiError(409, { code: "PREREQUISITE_MISSING", message: "x", missing: ["support_set"], support_blocked: true, problems: [] });
    expect(errorText(e)).toContain("② 지지점 자동 선택 실패");
    const e2 = new ApiError(409, { code: "PREREQUISITE_MISSING", message: "x", missing: ["support_set"] });
    expect(errorText(e2)).toContain("② 지지점");
    expect(errorText(e2)).not.toContain("자동 선택 실패");
  });
});


describe("라이브러리 내보내기 기본 숨김(ui.library_export_enabled)", () => {
  it("false 면 선택 줄 [내보내기] 없음·강성 평가 스터디가 주 버튼, true 면 [내보내기](주)", async () => {
    const { MOCK_VERSION } = await import("../mock/p3mock");
    const ui = MOCK_VERSION.ui as { library_export_enabled?: boolean };
    ui.library_export_enabled = false;
    try {
      const { unmount } = renderApp("/p/p-body/library", "power");
      const boxes = await screen.findAllByRole("checkbox", { name: / 선택$/ });
      fireEvent.click(boxes.find((b) => !(b as HTMLInputElement).disabled && b.getAttribute("aria-label") !== "보이는 항목 모두 선택")!);
      const bar = await screen.findByTestId("pick-bar");
      await waitFor(() => expect(within(bar).getByRole("button", { name: /강성 평가 스터디/ }).getAttribute("data-primary")).toBe("true"));
      expect(within(bar).queryByRole("button", { name: /내보내기/ })).toBeNull();
      unmount();
    } finally {
      ui.library_export_enabled = true;
    }
    renderApp("/p/p-body/library", "power");
    const boxes = await screen.findAllByRole("checkbox", { name: / 선택$/ });
    fireEvent.click(boxes.find((b) => !(b as HTMLInputElement).disabled && b.getAttribute("aria-label") !== "보이는 항목 모두 선택")!);
    const bar = await screen.findByTestId("pick-bar");
    expect(await within(bar).findByRole("button", { name: /내보내기 \(1\)/ })).toBeTruthy();
  });
});
