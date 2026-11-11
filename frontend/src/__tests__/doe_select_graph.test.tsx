// v0.17.0 BEADGRAPH 화면(esl_beadgraph.md §6.2·V-BG-17): 그래프 seed(doe-10) — 목록/트리 토글, 트리 노드 종류, 트리 행 ↔ 목록 칩 강조,
// 체크로 세그먼트 더하기/빼기, 우클릭 섬↔비드·병합·네트워크 묶기, 대칭 묶기 제안 → 저장 본문, seed 초기화·미저장 배지 유지,
// GRAPH_FAILED(doe-11) 띠 + 칠하기 비드로 계속, BG_GRAPH_STALE 띠.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { doe, isInfoWarn, warnText } from "../api/doe";
import type { DoeSelectionV2 } from "../api/types";
import { AUTO_BADGE } from "../components/BeadSelectCard";
import { renderApp } from "../test/render";

const primaries = (c: HTMLElement) => [...c.querySelectorAll("button[data-primary]")] as HTMLButtonElement[];
const nseg = (id: string) => Number(/세그먼트 (\d+)/.exec(screen.getByTestId(`bead-nseg-${id}`).textContent ?? "")?.[1] ?? -1);

afterEach(() => vi.restoreAllMocks());

async function openGraph() {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const r = renderApp("/p/p-body/doe/doe-10", "power");
  await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy(), { timeout: 10000 });
  return r;
}

describe("그래프 seed 스터디(doe-10)", () => {
  it("seed = 그래프 비드(⑂ + 세그먼트 수), 배지, 목록/트리 토글 · 트리 위계·접합 구역·섬 묶음", async () => {
    const r = await openGraph();
    expect(screen.getByTestId("bs-auto-badge").textContent).toBe(AUTO_BADGE);
    expect(screen.getByTestId("bs-auto-badge").getAttribute("title")).toMatch(/메시 분류기/);
    expect(screen.getByTestId("bead-b1").textContent).toMatch(/⑂ B1/);
    const rows = r.server.doe.recs.find((x) => x.out.id === "doe-10")!.autoSel!.selection.beads;
    expect(screen.getAllByText(/^⑂ B\d+$/)).toHaveLength(rows.length);
    const bottom = rows.findIndex((b) => b.name === "고리 아래");
    expect(nseg(`b${bottom + 1}`)).toBe(3);
    await waitFor(() => expect(primaries(r.container).map((b) => b.textContent)).toEqual(["선택 저장"]));
    // 트리 보기
    fireEvent.click(screen.getByTestId("bs-view-tree"));
    const tree = await screen.findByTestId("sg-tree");
    expect(within(tree).getByRole("tree", { name: "세그먼트 트리" })).toBeTruthy();
    expect(tree.textContent).toMatch(/플랜지/);
    expect(tree.textContent).toMatch(/고리 띠/);
    expect(tree.textContent).toMatch(/플래토/);
    expect(tree.textContent).toMatch(/채널/);
    expect(tree.textContent).toMatch(/고리 변 아래/);
    expect(tree.querySelectorAll('[data-testid^="sg-zone-"]').length).toBeGreaterThan(5);
    expect(tree.textContent).toMatch(/변수 없음/);
    expect(tree.textContent).toMatch(/구멍 \d+/);
    // 섬 묶음 펼치기
    const grp = within(tree).getAllByRole("button", { name: /섬 \d+/ })[0];
    fireEvent.click(grp);
    expect(tree.querySelectorAll('[data-testid^="sg-isl-"]').length).toBeGreaterThan(0);
  }, 20000);

  it("트리 행 클릭 = 강조(aria-selected), 목록 칩 클릭(3D 쪽 강조) → 트리 행 강조 · 체크로 세그먼트 더하기/빼기 · 다른 비드 것은 잠김", async () => {
    await openGraph();
    // 목록: 첫 비드 칩 클릭 → 강조 대상 설정
    const chip = within(screen.getByTestId("bead-segs-b1")).getAllByText(/\d+/)[0].closest(".sg-chip") as HTMLElement;
    const segId = /(\d+)(?: \(\+\d+\))?$/.exec(chip.textContent!.replace("✕", "").trim())![1];
    fireEvent.click(chip);
    fireEvent.click(screen.getByTestId("bs-view-tree"));
    await waitFor(() => expect(screen.getByTestId(`sg-seg-${segId}`).getAttribute("aria-selected")).toBe("true"));
    // 트리 행 클릭 → 그 행만 강조
    const zone = screen.getAllByTestId(/^sg-zone-/)[0];
    fireEvent.click(zone);
    expect(zone.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId(`sg-seg-${segId}`).getAttribute("aria-selected")).toBe("false");
    // 체크: b1 의 세그먼트 = 체크됨(지금 비드), 다른 비드 것은 잠김
    const cb = within(screen.getByTestId(`sg-seg-${segId}`)).getByRole("checkbox") as HTMLInputElement;
    expect(cb.checked).toBe(true);
    expect(cb.disabled).toBe(false);
    const locked = [...document.querySelectorAll('[data-testid^="sg-seg-"]')].find((x) => x.querySelector(".badge")?.textContent === "B2")!;
    expect((within(locked as HTMLElement).getByRole("checkbox") as HTMLInputElement).disabled).toBe(true);
    // 빼기 → 목록 세그먼트 수 0 → 다시 더하기
    fireEvent.click(cb);
    fireEvent.click(screen.getByTestId("bs-view-list"));
    await waitFor(() => expect(nseg("b1")).toBe(0));
    fireEvent.click(screen.getByTestId("bs-view-tree"));
    fireEvent.click(within(screen.getByTestId(`sg-seg-${segId}`)).getByRole("checkbox"));
    fireEvent.click(screen.getByTestId("bs-view-list"));
    await waitFor(() => expect(nseg("b1")).toBe(1));
  }, 20000);

  it("우클릭 메뉴: 섬으로·병합·네트워크 묶기·섬 → 비드 · 편집 목록 ✕ · 대칭 묶기 제안 → [선택 저장] 본문(schema 2·edits·ties)", async () => {
    const r = await openGraph();
    const sel = r.server.doe.recs.find((x) => x.out.id === "doe-10")!.autoSel!.selection as DoeSelectionV2;
    const ch1 = sel.beads.findIndex((b) => b.name === "채널 1");
    // 채널 1 비드를 지금 비드로
    fireEvent.click(within(screen.getByTestId(`bead-b${ch1 + 1}`)).getByText(/⑂/));
    fireEvent.click(screen.getByTestId("bs-view-tree"));
    const tree = await screen.findByTestId("sg-tree");
    // 채널 행 우클릭 → 인접과 병합(나팔)
    const chRow = [...tree.querySelectorAll('[data-testid^="sg-seg-"]')].find((x) => /^채널/.test(x.querySelector(".sg-name")!.textContent!) && (x.querySelector("input") as HTMLInputElement).checked)! as HTMLElement;
    fireEvent.contextMenu(chRow);
    const menu = await screen.findByTestId("sg-menu");
    const merge = within(menu).getAllByRole("menuitem").find((b) => /인접과 병합: 나팔/.test(b.textContent!))!;
    fireEvent.click(merge);
    await waitFor(() => expect(within(chRow).getByText("병합")).toBeTruthy());
    // 플래토 행 우클릭 → 섬으로
    const plat = [...tree.querySelectorAll('[data-testid^="sg-seg-"]')].find((x) => x.querySelector(".sg-name")!.textContent === "플래토")! as HTMLElement;
    fireEvent.contextMenu(plat);
    fireEvent.click(await screen.findByTestId("sg-menu-island"));
    await waitFor(() => expect(within(plat).getByText("섬으로")).toBeTruthy());
    // 섬 → 비드
    fireEvent.click(within(tree).getAllByRole("button", { name: /섬 \d+/ })[0]);
    const isl = tree.querySelector('[data-testid^="sg-isl-"]') as HTMLElement;
    fireEvent.contextMenu(isl);
    fireEvent.click(await screen.findByTestId("sg-menu-bead"));
    await waitFor(() => expect(isl.textContent).toMatch(/섬 → 비드/));
    // 편집 목록: 전환 2 · 병합 1 → 플래토 전환 취소
    const edits = screen.getByTestId("sg-edits");
    expect(edits.textContent).toMatch(/전환 2/);
    expect(edits.textContent).toMatch(/병합 1/);
    fireEvent.click(edits);
    fireEvent.click(within(screen.getByTestId("sg-edit-list")).getAllByRole("button", { name: "전환 취소" })[1]); // 섬 → 비드 취소
    await waitFor(() => expect(screen.getByTestId("sg-edits").textContent).toMatch(/전환 1/));
    expect(isl.textContent).not.toMatch(/섬 → 비드/);
    // 대칭 묶기 제안: 채널 1 ↔ 채널 2(서로 다른 비드) 체크
    fireEvent.click(screen.getByTestId("sg-sym"));
    const list = await screen.findByTestId("sg-sym-list");
    await waitFor(() => expect(within(list).getAllByRole("checkbox").some((c) => !(c as HTMLInputElement).disabled)).toBe(true));
    const row = within(list).getAllByText(/채널/)[0].closest("label")!;
    fireEvent.click(within(row).getByRole("checkbox"));
    fireEvent.click(screen.getByTestId("bs-view-list"));
    expect(screen.getByTestId("bs-ties").textContent).toMatch(/B\d+ = B\d+/);
    // 플래토를 섬으로 바꿨으니 '플래토' 비드는 세그먼트 없음 → 저장 막힘 → 그 비드 삭제
    const pb = sel.beads.findIndex((b) => b.name === "플래토");
    await waitFor(() => expect(primaries(r.container)[0].disabled).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: `B${pb + 1} 삭제` }));
    // 저장 → 본문
    const save = primaries(r.container)[0];
    await waitFor(() => expect(save.disabled).toBe(false));
    fireEvent.click(save);
    await waitFor(() => expect(r.server.doe.recs.find((x) => x.out.id === "doe-10")!.sel).toBeTruthy());
    const saved = r.server.doe.recs.find((x) => x.out.id === "doe-10")!.sel!.input as DoeSelectionV2;
    expect(saved.schema_version).toBe(2);
    expect(saved.graph!.edits.merge).toHaveLength(1);
    expect(saved.graph!.edits.toggle).toEqual([expect.objectContaining({ as: "island" })]);
    expect(saved.beads.map((b) => b.name)).not.toContain("플래토");
    expect(saved.ties).toHaveLength(1);
    expect(saved.beads.every((b) => b.src === "graph")).toBe(true);
    await waitFor(() => expect(screen.queryByTestId("bs-auto-badge")).toBeNull());
  }, 30000);

  it("seed 초기화: 세그먼트 빼기 → 이 비드 초기화 = seed, 전체 초기화 = seed, 미저장 배지 유지 · 실행 취소 끝 = seed", async () => {
    await openGraph();
    const n1 = nseg("b1");
    within(screen.getByTestId("bead-segs-b1"))
      .getAllByRole("button", { name: /빼기/ })
      .forEach((b) => fireEvent.click(b));
    await waitFor(() => expect(nseg("b1")).toBe(0));
    fireEvent.click(screen.getByTestId("bead-reset-b1"));
    await waitFor(() => expect(nseg("b1")).toBe(n1));
    expect(screen.getByTestId("bs-auto-badge")).toBeTruthy();
    const all = screen.getAllByText(/^⑂ B\d+$/).length;
    fireEvent.click(screen.getByRole("button", { name: "B2 삭제" }));
    await waitFor(() => expect(screen.getAllByText(/^⑂ B\d+$/).length).toBe(all - 1));
    fireEvent.click(screen.getByRole("button", { name: "전체 초기화" }));
    await waitFor(() => expect(screen.getAllByText(/^⑂ B\d+$/).length).toBe(all));
    expect(screen.getByTestId("bs-auto-badge")).toBeTruthy();
    const undo = screen.getByRole("button", { name: "실행 취소" }) as HTMLButtonElement;
    while (!undo.disabled) fireEvent.click(undo);
    await waitFor(() => expect(nseg("b1")).toBe(n1));
    expect(screen.getByTestId("bs-auto-badge")).toBeTruthy();
  }, 20000);

  it("BG_GRAPH_STALE(409) → 띠 '분류 결과가 바뀌었습니다 — 다시 확인 후 저장' + 그래프 다시 받음", async () => {
    await openGraph();
    const spy = vi.spyOn(doe, "selectGraph");
    vi.spyOn(doe, "derive").mockRejectedValueOnce(new ApiError(409, { code: "BG_GRAPH_STALE", message: "stale", saved: "a", current: "b" } as never));
    fireEvent.click(screen.getByRole("button", { name: "다시 계산" }));
    expect(await screen.findByTestId("bs-graph-stale")).toBeTruthy();
    expect(screen.getByTestId("bs-graph-stale").textContent).toMatch(/분류 결과가 바뀌었습니다 — 다시 확인 후 저장/);
    await waitFor(() => expect(spy).toHaveBeenCalled());
  }, 20000);
});

describe("GRAPH_FAILED(doe-11)", () => {
  it("띠 + 트리 토글 없음, [+ 비드] = 칠하기 비드(단 층) — 빈 단이면 저장 막힘", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const r = renderApp("/p/p-body/doe/doe-11", "power");
    expect(await screen.findByTestId("bs-graph-failed", undefined, { timeout: 10000 })).toBeTruthy();
    // Verifier fix v0.17.0: 띠 한 곳에만(준비 경고 목록에서 빠짐), 사유 = 준비 경고 detail(TIMEOUT → 시간 초과)
    expect(screen.getByTestId("bs-graph-failed").textContent).toBe("자동 분류 실패(시간 초과) — 직접 칠하기(요소 비드)로 계속");
    expect(r.container.textContent?.match(/자동 분류 실패/g) ?? []).toHaveLength(1);
    expect(screen.queryByTestId("bs-view-tree")).toBeNull();
    expect(screen.queryByTestId("bs-add-elems")).toBeNull();
    fireEvent.click(screen.getByTestId("bs-add-bead"));
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy());
    expect(screen.getByTestId("bead-b1").textContent).not.toMatch(/⑂/);
    expect((screen.getByRole("combobox", { name: "대상 층" }) as HTMLSelectElement).value).toBe("t:0:1");
    // 빈 단이면 저장 사유로 막힘(저장 본문 형식 = select_graph_bin.test 의 schema 2 직렬화)
    await waitFor(() => expect(primaries(r.container)[0].textContent).toBe("선택 저장"));
    expect(primaries(r.container)[0].disabled).toBe(true);
  }, 20000);
});

describe("GRAPH_FAILED 경고 형식(통합 v0.17.0)", () => {
  it("{code, message, detail} 하나 — 사유는 detail 만 읽음", () => {
    expect(warnText({ code: "GRAPH_FAILED", detail: "TIMEOUT" } as never)).toBe("자동 분류 실패(시간 초과) — 직접 칠하기(요소 비드)로 계속");
    expect(warnText({ code: "GRAPH_FAILED", reason: "TIMEOUT" } as never)).toBe("자동 분류 실패 — 직접 칠하기(요소 비드)로 계속");
    expect(warnText({ code: "GRAPH_FAILED", detail: "TIMEOUT", message: "서버 문구" } as never)).toBe("서버 문구");
  });
});

describe("BG_RANGE_CLAMPED(통합 v0.17.0 — 기본 W 범위를 뒤집힘 없는 범위로)", () => {
  it("정보(ⓘ) + 줄인 범위 문구", () => {
    const w = { code: "BG_RANGE_CLAMPED", bead: "b10", var: "B10_W", from: [60, 90], to: [60, 76.875], inverted: [0, 118] };
    expect(isInfoWarn(w)).toBe(true);
    expect(isInfoWarn({ ...w, level: "info" })).toBe(true);
    expect(warnText(w as never)).toBe("B10_W: 기본 범위 60~90 mm 끝에서 뒤집혀 60~76.9 mm 로 줄였습니다");
  });
});

describe("GRAPH_FAILED 띠 문구 1줄(Verifier fix v0.17.0)", () => {
  it("준비 경고 detail 이 있으면 그 사유, 없으면 받기 오류를 괄호로", async () => {
    const { graphFailBand } = await import("../components/BeadSelectCard");
    expect(graphFailBand([{ code: "FIXED_INFO_MISSING" }, { code: "GRAPH_FAILED", detail: "NO_FLOOR" }] as never, "404")).toBe("자동 분류 실패(바닥을 찾지 못함) — 직접 칠하기(요소 비드)로 계속");
    expect(graphFailBand([], "네트워크 오류")).toBe("자동 분류 실패 — 직접 칠하기(요소 비드)로 계속 (네트워크 오류)");
    expect(graphFailBand(null, null)).toBe("자동 분류 실패 — 직접 칠하기(요소 비드)로 계속");
  });
});

describe("새 스터디 제목 칸(Verifier fix v0.17.0)", () => {
  it("제목 칸 = 한 줄 전체(doe-title) — 예시 문구가 10rem 칸에 잘리지 않게", async () => {
    renderApp("/p/p-body/doe/new?entries=le-1,le-2,le-3", "power");
    const t = (await screen.findByRole("textbox", { name: "제목" }, { timeout: 10000 })) as HTMLInputElement;
    expect(t.closest(".field")?.classList.contains("doe-title")).toBe(true);
    expect(t.placeholder).toMatch(/^예: 75형 Ch\/R /);
  }, 20000);
});
