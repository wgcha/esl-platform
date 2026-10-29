// v0.8.0 라이브러리 항목 메타 수정: 대화상자(모델·씬·메모) 입력 검사·바꾼 필드만 PATCH·권한(등록자·관리자)·409 최신 값 불러오기·
// 저장 후 목록·필터 반영·인치 변경 시 선택(크기 판정) 해제.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { NO_PERMISSION } from "../app/AppContext";
import { buildPatch, editBlock, formOf } from "../pages/library/EntryEdit";
import { makeEntries } from "../mock/p2data";
import { USERS } from "../mock/data";
import type { EntryOut } from "../api/types";

const LIB = "/p/p-body/library";
const rowsOf = () => within(screen.getByRole("table", { name: "라이브러리 항목" })).getAllByRole("row").slice(1);
const rowWith = (...t: string[]) => rowsOf().find((r) => t.every((x) => r.textContent!.includes(x)))!;

describe("buildPatch·editBlock(순수 함수)", () => {
  const e: EntryOut = makeEntries("p-body")[0]; // 75QN80H 75" Corner 146, 등록 u-power
  it("바뀐 필드만, 빈칸 = null, 바뀐 것 없으면 null", () => {
    const f = formOf(e);
    expect(buildPatch(e, f, 3).patch).toBeNull();
    const p = buildPatch(e, { ...f, name: " 75QN90X ", inch: "76", scenario: "", orient: "12", note: "메모" }, 3);
    expect(p.errors).toEqual({});
    expect(p.patch).toEqual({ version: 3, model: { name: "75QN90X", inch: 76 }, scene: { scenario: null, orient: "12" }, note: "메모" });
  });
  it("입력 검사: 인치·질량·순번·씬 번호·orient·모델명 비움", () => {
    const f = formOf(e);
    const er = buildPatch(e, { ...f, inch: "0", product_mass: "-1", seq: "1.5", scene_no: "-2", orient: "17", name: "" }, 1).errors;
    expect(Object.keys(er).sort()).toEqual(["inch", "name", "orient", "product_mass", "scene_no", "seq"]);
    expect(buildPatch(e, { ...f, inch: "1001" }, 1).errors.inch).toMatch(/1~1000/);
    expect(buildPatch(e, { ...f, version: "x".repeat(65) }, 1).errors.version).toMatch(/64자/);
  });
  it("권한: 조회 → 실행 권한, 다른 power → 등록자 안내, 등록자·관리자 → 가능", () => {
    expect(editBlock(USERS.general, e)).toBe(NO_PERMISSION);
    expect(editBlock(USERS.power, e)).toBeNull();
    expect(editBlock(USERS.admin, e)).toBeNull();
    expect(editBlock(USERS.power, { ...e, registered_by: "u-x", registered_by_name: "박다른" })).toMatch(/등록자\(박다른\) 또는 관리자/);
  });
});

describe("라이브러리 항목 수정 대화상자", () => {
  it("모델명·인치·씬·메모 저장 → 서버 값·목록·모델 필터 반영", async () => {
    const { server } = renderApp(LIB);
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    fireEvent.click(within(rowWith("75QN80H", "146")).getByRole("button", { name: "수정" }));
    const dlg = screen.getByRole("dialog", { name: /라이브러리 항목 수정/ });
    const put = (label: string, v: string) => fireEvent.change(within(dlg).getByLabelText(label, { selector: "input,select,textarea" }), { target: { value: v } });
    put("모델명", "75QN90X");
    put("인치", "76");
    put("모델 버전", "v080");
    put("날짜", "2026-10-29");
    put("시나리오", "STACK");
    put("씬 번호", "4");
    put("낙하 유형", "Edge");
    put("orient", "12");
    put("메모", "수정 메모");
    fireEvent.click(within(dlg).getByRole("button", { name: "저장" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const e = server.entries.find((x) => x.id === "le-1")!;
    expect(e.model).toMatchObject({ name: "75QN90X", inch: 76, version: "v080", date: "2026-10-29" });
    expect(e.scene).toMatchObject({ scenario: "STACK", scene_no: 4, drop_type: "Edge", orient: "12", drop_class: "Edge" });
    expect(e.note).toBe("수정 메모");
    await waitFor(() => expect(rowWith("75QN90X", "76")).toBeTruthy());
    const model = screen.getByRole("combobox", { name: "모델" });
    await waitFor(() => expect(within(model).getByRole("option", { name: "75QN90X" })).toBeTruthy());
    fireEvent.change(model, { target: { value: "75QN90X" } });
    await waitFor(() => expect(rowsOf()).toHaveLength(1));
  });

  it("바뀐 것 없음·잘못된 값 → 저장 비활성, 취소", async () => {
    renderApp(LIB);
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    fireEvent.click(within(rowsOf()[0]).getByRole("button", { name: "수정" }));
    const dlg = screen.getByRole("dialog");
    const save = within(dlg).getByRole("button", { name: "저장" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(within(dlg).getByRole("spinbutton", { name: "인치" }), { target: { value: "0" } });
    expect(save.disabled).toBe(true);
    expect(within(dlg).getByText("인치는 1~1000 정수")).toBeTruthy();
    fireEvent.click(within(dlg).getByRole("button", { name: "취소" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("409(다른 사용자가 먼저 수정) → 오류 문구 + 최신 값 불러오기 → 다시 저장", async () => {
    const { server } = renderApp(LIB);
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    fireEvent.click(within(rowWith("75QN80H", "146")).getByRole("button", { name: "수정" }));
    const dlg = screen.getByRole("dialog");
    const e = server.entries.find((x) => x.id === "le-1")!;
    e.version += 1;
    e.note = "먼저 수정";
    fireEvent.change(within(dlg).getByRole("textbox", { name: "메모" }), { target: { value: "늦은 수정" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "저장" }));
    const alert = await within(dlg).findByRole("alert");
    expect(alert.textContent).toMatch(/다른 사용자가 먼저 수정/);
    expect((within(dlg).getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(alert).getByRole("button", { name: "최신 값 불러오기" }));
    await waitFor(() => expect((within(dlg).getByRole("textbox", { name: "메모" }) as HTMLTextAreaElement).value).toBe("먼저 수정"));
    fireEvent.change(within(dlg).getByRole("textbox", { name: "메모" }), { target: { value: "다시 수정" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "저장" }));
    await waitFor(() => expect(e.note).toBe("다시 수정"));
  });

  it("다른 사용자 항목: 수정 비활성 + 등록자 사유, 조회 사용자: 실행 권한 사유", async () => {
    const v = renderApp(LIB, "power", (s) => {
      s.entries[0].registered_by = "u-x";
      s.entries[0].registered_by_name = "박다른";
    });
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    const b = within(rowWith("75QN80H", "146")).getByRole("button", { name: "수정" }) as HTMLButtonElement;
    expect(b.disabled).toBe(true);
    expect(b.parentElement!.getAttribute("title")).toMatch(/등록자\(박다른\) 또는 관리자/);
    v.unmount();
    renderApp(LIB, "general");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    const g = within(rowsOf()[0]).getByRole("button", { name: "수정" }) as HTMLButtonElement;
    expect(g.disabled).toBe(true);
    expect(g.parentElement!.getAttribute("title")).toBe(NO_PERMISSION);
  });

  it("관리자는 남의 항목도 수정", async () => {
    const { server } = renderApp(LIB, "admin");
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    fireEvent.click(within(rowWith("75QN80H", "146")).getByRole("button", { name: "수정" }));
    const dlg = screen.getByRole("dialog");
    fireEvent.change(within(dlg).getByRole("textbox", { name: "모델 버전" }), { target: { value: "v9" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "저장" }));
    await waitFor(() => expect(server.entries.find((x) => x.id === "le-1")!.model.version).toBe("v9"));
  });

  it("인치를 바꾸면 그 항목은 비드 최적화 선택에서 빠짐(기준이면 선택 해제)", async () => {
    renderApp(LIB);
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    const box = within(rowWith("75QN80H", "146")).getByRole("checkbox");
    await waitFor(() => expect((box as HTMLInputElement).disabled).toBe(false));
    fireEvent.click(box);
    expect(await screen.findByTestId("pick-bar")).toBeTruthy();
    fireEvent.click(within(rowWith("75QN80H", "146")).getByRole("button", { name: "수정" }));
    const dlg = screen.getByRole("dialog");
    fireEvent.change(within(dlg).getByRole("spinbutton", { name: "인치" }), { target: { value: "77" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "저장" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(screen.queryByTestId("pick-bar")).toBeNull());
  });

  it("저장 실패(서버 오류) → 대화상자에 오류 문구, 닫히지 않음", async () => {
    const { server } = renderApp(LIB);
    await waitFor(() => expect(rowsOf()).toHaveLength(10));
    server.entries.find((x) => x.id === "le-1")!.status = "RETIRED"; // 다른 곳에서 폐기됨 → 409 ENTRY_RETIRED
    fireEvent.click(within(rowWith("75QN80H", "146")).getByRole("button", { name: "수정" }));
    const dlg = screen.getByRole("dialog");
    fireEvent.change(within(dlg).getByRole("textbox", { name: "메모" }), { target: { value: "x" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "저장" }));
    expect((await within(dlg).findByRole("alert")).textContent).toMatch(/retired|폐기/);
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});
