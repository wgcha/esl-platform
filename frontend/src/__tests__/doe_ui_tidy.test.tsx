// v0.23.1 강성 스터디 화면 정리(esl_doe_ui_tidy.md §11 V-UI-1~9): Card 접기 · 단계 초점 · 진행 띠 · 한 정보 한 자리 · 상태 띠 · 버튼 두 묶음 · ⓘ 지표 정의 · 새 스터디 2열
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Card } from "../components/ui";
import { openCard, renderApp } from "../test/render";

const cardBtn = (title: string) => screen.getByRole("button", { name: new RegExp(`^${title}`) });
const region = (name: RegExp) => screen.getByRole("region", { name });
const bodyOf = (sec: HTMLElement) => sec.querySelector(".card-body") as HTMLElement;

describe("V-UI-1 Card 접기 속성", () => {
  it("fold 없음 = 기존 마크업(단추 없음), fold = aria-expanded·hidden 본문(DOM 유지)·sessionStorage 기억, locked = 단추 없음", () => {
    const a = render(<Card title="가" right={<span>오른쪽</span>}>본문</Card>);
    expect(a.container.innerHTML).toBe('<section class="card" aria-label="가"><header class="card-head"><h3>가</h3><span>오른쪽</span></header><div class="card-body">본문</div></section>');
    a.unmount();
    const b = render(<Card title="나" right={<span>요약</span>} fold={{ storeKey: "t:1", defaultOpen: false }}>본문 나</Card>);
    const btn = screen.getByRole("button", { name: "나" });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(bodyOf(b.container.querySelector("section")!).hidden).toBe(true);
    expect(screen.getByText("본문 나")).toBeTruthy(); // 언마운트 안 함
    expect(screen.getByText("요약")).toBeTruthy(); // 접힌 막대 = 제목 + 기존 right
    expect(screen.getByRole("heading", { name: "나" })).toBeTruthy();
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(window.sessionStorage.getItem("esl.cardfold.t:1")).toBe("1");
    b.unmount();
    // 같은 세션 다시 그림 → 펼친 상태 유지(defaultOpen false 여도)
    const c = render(<Card title="나" fold={{ storeKey: "t:1", defaultOpen: false }}>본문 나</Card>);
    expect(bodyOf(c.container.querySelector("section")!).hidden).toBe(false);
    c.unmount();
    const d = render(<Card title="다" fold={{ storeKey: "t:2", defaultOpen: false, locked: true }}>본문 다</Card>);
    expect(screen.queryByRole("button", { name: "다" })).toBeNull();
    expect(bodyOf(d.container.querySelector("section")!).hidden).toBe(false);
  });
});

describe("V-UI-2 단계 초점", () => {
  it("doe-1(결과): ①·②·③·미리보기 접힘, 결과 펼침 / 펼친 카드는 같은 세션 다시 열어도 유지", async () => {
    renderApp("/p/p-body/doe/doe-1");
    await screen.findByRole("table", { name: "순위표" });
    for (const t of ["① 입력", "② 비드·변수", "③ 평면도", "④ 미리보기"]) await waitFor(() => expect(cardBtn(t).getAttribute("aria-expanded")).toBe("false"));
    expect(bodyOf(region(/^⑤ 결과/)).hidden).toBe(false);
    expect(within(region(/^⑤ 결과/)).queryByRole("button", { name: /^⑤ 결과/ })).toBeNull(); // 결과 카드는 접기 없음
    fireEvent.click(cardBtn("① 입력"));
    cleanup();
    renderApp("/p/p-body/doe/doe-1");
    await screen.findByRole("table", { name: "순위표" });
    await waitFor(() => expect(cardBtn("① 입력").getAttribute("aria-expanded")).toBe("true"));
  }, 20000);
  it("doe-5(설정): ① 펼침 · doe-6(미리보기): 미리보기 펼침·①② 접힘", async () => {
    renderApp("/p/p-body/doe/doe-5");
    await waitFor(() => expect(cardBtn("① 입력").getAttribute("aria-expanded")).toBe("true"));
    await waitFor(() => expect(cardBtn("② 비드 선택").getAttribute("aria-expanded")).toBe("true"));
    cleanup();
    renderApp("/p/p-body/doe/doe-6");
    await waitFor(() => expect(cardBtn("⑥ 미리보기").getAttribute("aria-expanded")).toBe("true"));
    expect(cardBtn("① 입력").getAttribute("aria-expanded")).toBe("false");
    expect(cardBtn("② 비드 선택").getAttribute("aria-expanded")).toBe("false");
  }, 20000);
});

describe("V-UI-3 진행 띠", () => {
  it("미리보기 진행 중: 진행 띠 1개(미리보기 진행 1줄 + 단계 목록 1개), 미리보기 카드 locked", async () => {
    const { server } = renderApp("/p/p-body/doe/doe-2");
    await openCard("② 비드·변수");
    await screen.findByRole("table", { name: "비드 변수" });
    fireEvent.change(screen.getByRole("spinbutton", { name: "안 수" }), { target: { value: "12" } });
    await waitFor(() => expect(screen.getByTestId("doe-count").textContent).toMatch(/실제 13안/));
    fireEvent.click(await screen.findByRole("button", { name: "미리보기" }));
    const band = await screen.findByTestId("doe-progress");
    expect(within(band).getByTestId("preview-progress").textContent).toMatch(/미리보기 진행 중/);
    expect(screen.getAllByTestId("doe-progress")).toHaveLength(1);
    expect(document.querySelectorAll('ol[aria-label="DOE 단계"]').length).toBeLessThanOrEqual(1);
    expect(screen.queryByRole("button", { name: /^④ 미리보기/ })).toBeNull(); // locked = 접기 단추 없음
    server.drain();
    await waitFor(() => expect(screen.queryByTestId("doe-progress")).toBeNull(), { timeout: 6000 });
  }, 15000);
});

describe("V-UI-4·5·6·7 결과 카드(한 정보 한 자리 · 상태 띠 · 버튼 묶음 · ⓘ)", () => {
  it("doe-1: 받기 = 카드 머리(파일 ▾ 안 링크), 선택 안 작업 = 오른쪽 열 머리, 정렬·ESL별 설명은 ⓘ 안 1번, 결과 하단 안내 줄 없음", async () => {
    renderApp("/p/p-body/doe/doe-1");
    await screen.findByRole("table", { name: "순위표" });
    const res = region(/^⑤ 결과/);
    const head = res.querySelector(".card-head") as HTMLElement;
    const dl = within(head).getByTestId("doe-downloads");
    expect(within(dl).getByRole("button", { name: /결과 받기/ })).toBeTruthy();
    expect(within(dl).getByRole("link", { name: "순위 CSV" })).toBeTruthy();
    const menu = within(dl).getByTestId("doe-files-menu");
    expect(within(menu).getByRole("link", { name: /include inc_mesh\.inc/ })).toBeTruthy();
    expect(menu.textContent).toMatch(/받기 · 최적 d\d{3}/);
    const right = res.querySelector(".doe-result-right") as HTMLElement;
    const acts = within(right).getByTestId("doe-pick-actions");
    expect(within(acts).getByTestId("vd-open")).toBeTruthy();
    expect(within(acts).getByTestId("redrop")).toBeTruthy();
    expect(screen.getAllByTestId("vd-open")).toHaveLength(1);
    expect(within(right).getByText("3D 비교")).toBeTruthy();
    expect(within(right).getByText("민감도")).toBeTruthy();
    const left = res.querySelector(".doe-result-left") as HTMLElement;
    expect(within(left).getByRole("table", { name: "ESL별 개선율" })).toBeTruthy();
    // 한 정보 한 자리(§9)
    const txt = document.body.textContent ?? "";
    expect(txt.split("정렬:").length - 1).toBe(1);
    expect(screen.getByTestId("rank-sort").closest("[data-testid=metric-defs]")).toBeTruthy();
    expect(txt.split("셀 = 개선율").length - 1).toBe(1);
    expect(screen.getByTestId("per-esl-note").textContent).toMatch(/상위 10개/);
    expect(document.querySelectorAll("ul.reasons").length).toBe(0);
    expect(txt).not.toMatch(/최적 안은 검증 낙하 1회로 확인하세요/); // → 검증 낙하 툴팁
    await waitFor(() => expect(screen.getByTestId("vd-open").closest(".primary-wrap")!.getAttribute("title")).toMatch(/최적 안은 검증 낙하 1회로 확인하세요/));
    // 안 고르면 오른쪽 머리에 선택 안·변수값
    fireEvent.click(within(left).getAllByTestId(/^rank-d/)[0]);
    await waitFor(() => expect(screen.getByTestId("doe-pick-head").textContent).toMatch(/^선택 안 d\d{3} · /));
  }, 20000);

  it("doe-40(지그)·doe-21(LT): 상태 띠 칩 탭별(지그 탭 = 지그, 전 노드 탭 = 하중 전달), 칩 testid 1개씩, LT 펼침 = 진단 표", async () => {
    renderApp("/p/p-body/doe/doe-40", "power", (s) => s.doe.demoJig());
    await screen.findByRole("table", { name: "순위표" });
    const band = await screen.findByTestId("doe-status");
    const ids = [...band.querySelectorAll("[data-testid]")].map((e) => e.getAttribute("data-testid")).filter((x) => ["jig-line", "lt-summary", "best-clean", "best-clean-mq", "mq-base-strip", "result-warn"].includes(x!));
    // v0.23.3 하중 정의 탭: 지그 탭 = 지그 칩만, 하중 전달 칩은 전 노드 탭으로(D-0.23.3-4)
    expect(ids[0]).toBe("jig-line");
    expect(ids).not.toContain("lt-summary");
    expect(document.querySelectorAll("[data-testid=jig-line]").length).toBe(1);
    fireEvent.click(screen.getByTestId("doe-load-tab").querySelector("[data-tab=full]")!);
    await waitFor(() => expect(document.querySelectorAll("[data-testid=lt-summary]").length).toBe(1));
    expect(document.querySelectorAll("[data-testid=jig-line]").length).toBe(0);
    const det = screen.getByTestId("lt-details") as HTMLDetailsElement;
    det.open = true;
    fireEvent(det, new Event("toggle"));
    await screen.findByRole("table", { name: "하중 전달 베이스라인 참값 대비" });
    expect(screen.getByTestId("lt-full").textContent).toBe(screen.getByTestId("lt-summary").getAttribute("title"));
  }, 20000);

  it("doe-20(④): 검증 낙하 없음, 결과 안내문은 ⓘ 지표 정의 안(result-note), 경계 경고 = ① 머리 1곳", async () => {
    renderApp("/p/p-body/doe/doe-20");
    await screen.findByRole("table", { name: "순위표" });
    expect(screen.queryByTestId("vd-open")).toBeNull();
    expect(screen.getByTestId("result-note").closest("[data-testid=metric-defs]")).toBeTruthy();
    expect(screen.getByTestId("result-note").textContent).toMatch(/형상마다 새 메시/);
    expect((document.body.textContent ?? "").split("형상마다 새 메시라").length - 1).toBe(1);
    const heads = [...document.querySelectorAll(".card-head")].filter((h) => /경계 경고/.test(h.textContent ?? ""));
    expect(heads.length).toBeLessThanOrEqual(1);
  }, 20000);

  it("doe-2(② mesh 이전 방식): 경계 경고 수는 ① 머리에만(③ 평면도 머리에 없음)", async () => {
    renderApp("/p/p-body/doe/doe-2");
    const head = await screen.findByTestId("input-head");
    expect(head.textContent).toMatch(/경계 경고 \d+/);
    expect(region(/^③ 평면도/).querySelector(".card-head")!.textContent).not.toMatch(/경고/);
  }, 15000);
});

describe("V-UI-8 새 스터디", () => {
  it("① 안 2열(왼쪽 ESL·업로드 / 오른쪽 필드), 설명 첫 문장 상시 + 나머지 ⓘ", async () => {
    renderApp("/p/p-body/doe/new?entries=le-1,le-2");
    const cols = await screen.findByTestId("doe-inputs-cols");
    const [l, r] = [cols.querySelector(".doe-inputs-left")!, cols.querySelector(".doe-inputs-right")!];
    expect(within(l as HTMLElement).getByLabelText("선택한 ESL")).toBeTruthy();
    expect(within(r as HTMLElement).getByRole("textbox", { name: "제목" })).toBeTruthy();
    const note = screen.getByTestId("new-note");
    expect(note.textContent).toMatch(/^입력 준비/);
    const more = within(note).getByTestId("new-note-more") as HTMLDetailsElement;
    expect(more.open).toBe(false);
    expect(more.textContent).toMatch(/입력 폴더는 읽기만 합니다\./);
  }, 15000);
});

describe("V-UI-9 상태 띠 칩 키보드·터치 펼침(D-0.23.1-UI-8)", () => {
  it("지그 칩: 포커스 가능 · aria-expanded · Enter 로 하중 영역·지그 노드 전체 문구가 DOM 텍스트로 보임, 칩 1개 유지", async () => {
    renderApp("/p/p-body/doe/doe-40", "power", (s) => s.doe.demoJig());
    await screen.findByRole("table", { name: "순위표" });
    const chip = await screen.findByTestId("jig-line");
    expect(chip.tagName).toBe("SUMMARY");
    expect(chip.getAttribute("title")).toMatch(/하중 영역/); // 툴팁 유지
    expect(chip.getAttribute("aria-expanded")).toBe("false");
    expect(chip.tabIndex).toBe(0);
    chip.focus();
    expect(document.activeElement).toBe(chip);
    fireEvent.keyDown(chip, { key: "Enter" });
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    expect((screen.getByTestId("jig-line-details") as HTMLDetailsElement).open).toBe(true);
    const full = screen.getByTestId("jig-line-full").textContent ?? "";
    expect(full).toMatch(/하중 영역 \d+개/);
    expect(full).toMatch(/지그 노드 \d+/);
    expect(document.querySelectorAll("[data-testid=jig-line]").length).toBe(1);
    fireEvent.keyDown(chip, { key: " " });
    expect(chip.getAttribute("aria-expanded")).toBe("false");
  }, 20000);
});
