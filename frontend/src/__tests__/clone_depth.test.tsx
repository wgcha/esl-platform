// V-0247-DM-25 (esl_bead_depth_mode.md §6.1·§7·§8): 복제 창(select 스터디만) — 라디오 기본 = 원 값(키 없음 = 입구 고정), 바꾸면 안내 1줄·같으면 없음,
// 요청 본문 {depth_section}, 그 밖 시나리오는 지금처럼 즉시 복제, 복제 스터디 변수 표 = spec_prefill(원 변수만 체크·원 범위).
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MockServer } from "../mock/server";
import { renderApp } from "../test/render";

/** doe-6(select, 변수 spec 있음)을 복제 가능(FAILED) 상태로 */
const failed = (key?: "entry_fixed" | "floor_fixed") => (s: MockServer) => {
  const r = s.doe.recs.find((x) => x.out.id === "doe-6")!;
  r.out.phase = "FAILED";
  if (key) r.out.inputs.depth_section = key;
};
const cloneBtn = async () => (await screen.findByRole("button", { name: "복제" }, { timeout: 10000 })) as HTMLButtonElement;
const radios = () => within(screen.getByTestId("clone-window")).getAllByRole("radio") as HTMLInputElement[];

describe("복제 창", () => {
  it("select 스터디: [복제] → 작은 창(라디오 2·[복제]·[취소]), 기본 = 원 값(키 없음 = 입구 고정), 안내 줄 없음, 요청 전에는 복제 안 됨", async () => {
    const r = renderApp("/p/p-body/doe/doe-6", "power", failed());
    const n0 = r.server.doe.recs.length;
    fireEvent.click(await cloneBtn());
    const w = await screen.findByTestId("clone-window");
    expect(radios().map((x) => [x.value, x.checked])).toEqual([["entry_fixed", true], ["floor_fixed", false]]);
    expect(within(w).getAllByRole("button").map((b) => b.textContent)).toEqual(["복제", "취소"]);
    expect(screen.queryByTestId("clone-note")).toBeNull();
    expect(r.server.doe.recs.length).toBe(n0);
  }, 30000);

  it("원 값과 다르게 고르면 DS_CLONE_NOTE 문구(서버 text) 1줄, 도로 같게 하면 사라짐", async () => {
    const r = renderApp("/p/p-body/doe/doe-6", "power", failed());
    fireEvent.click(await cloneBtn());
    await screen.findByTestId("clone-window");
    fireEvent.click(radios()[1]);
    expect(screen.getByTestId("clone-note").textContent).toBe(r.server.doe.settings.depth_section_notes!.DS_CLONE_NOTE);
    expect(screen.getByTestId("clone-note").textContent).toMatch(/깊이 동작만 바뀝니다/);
    fireEvent.click(radios()[0]);
    expect(screen.queryByTestId("clone-note")).toBeNull();
  }, 30000);

  it("[취소] 와 Esc = 창 닫힘, 복제 없음", async () => {
    const r = renderApp("/p/p-body/doe/doe-6", "power", failed());
    const n0 = r.server.doe.recs.length;
    fireEvent.click(await cloneBtn());
    fireEvent.click(within(await screen.findByTestId("clone-window")).getByRole("button", { name: "취소" }));
    expect(screen.queryByTestId("clone-window")).toBeNull();
    fireEvent.click(await cloneBtn());
    fireEvent.keyDown(await screen.findByTestId("clone-window"), { key: "Escape" });
    expect(screen.queryByTestId("clone-window")).toBeNull();
    expect(r.server.doe.recs.length).toBe(n0);
  }, 30000);

  it("입구 고정(키 없음) → 깊이면 폭 유지 복제: 본문 {depth_section: floor_fixed}, 새 스터디 inputs 에 키·spec_prefill = 원 spec", async () => {
    const r = renderApp("/p/p-body/doe/doe-6", "power", failed());
    const orig = r.server.doe.recs.find((x) => x.out.id === "doe-6")!;
    const n0 = r.server.doe.recs.length;
    fireEvent.click(await cloneBtn());
    await screen.findByTestId("clone-window");
    fireEvent.click(radios()[1]);
    fireEvent.click(within(screen.getByTestId("clone-window")).getByRole("button", { name: "복제" }));
    await waitFor(() => expect(r.server.doe.recs.length).toBe(n0 + 1), { timeout: 10000 });
    const c = r.server.doe.recs[n0];
    expect(c.out.inputs.depth_section).toBe("floor_fixed");
    expect(c.out.inputs.spec_prefill).toEqual(orig.out.doe!.spec);
  }, 30000);

  it("같은 값으로 복제 = 본문에 depth_section 없음(지금 복제와 같음 — 키 없음 유지)", async () => {
    const r = renderApp("/p/p-body/doe/doe-6", "power", failed());
    const n0 = r.server.doe.recs.length;
    fireEvent.click(await cloneBtn());
    await screen.findByTestId("clone-window");
    fireEvent.click(within(screen.getByTestId("clone-window")).getByRole("button", { name: "복제" }));
    await waitFor(() => expect(r.server.doe.recs.length).toBe(n0 + 1), { timeout: 10000 });
    expect("depth_section" in r.server.doe.recs[n0].out.inputs).toBe(false);
  }, 30000);

  it("floor_fixed 스터디 → 입구 고정 복제: 기본 라디오 = 깊이면 폭 유지, 입구 고정 선택 시 키 entry_fixed", async () => {
    const r = renderApp("/p/p-body/doe/doe-6", "power", failed("floor_fixed"));
    const n0 = r.server.doe.recs.length;
    fireEvent.click(await cloneBtn());
    await screen.findByTestId("clone-window");
    expect(radios().map((x) => x.checked)).toEqual([false, true]);
    fireEvent.click(radios()[0]);
    fireEvent.click(within(screen.getByTestId("clone-window")).getByRole("button", { name: "복제" }));
    await waitFor(() => expect(r.server.doe.recs.length).toBe(n0 + 1), { timeout: 10000 });
    expect(r.server.doe.recs[n0].out.inputs.depth_section).toBe("entry_fixed");
  }, 30000);

  it("select 가 아닌 스터디(④ 형상 비교)는 창 없이 즉시 복제", async () => {
    const r = renderApp("/p/p-body/doe/doe-20", "power");
    const n0 = r.server.doe.recs.length;
    fireEvent.click(await cloneBtn());
    expect(screen.queryByTestId("clone-window")).toBeNull();
    await waitFor(() => expect(r.server.doe.recs.length).toBe(n0 + 1), { timeout: 10000 });
  }, 30000);

  it("복제된 스터디 변수 표 = s.doe?.spec ?? inputs.spec_prefill(원 spec 변수만 체크·원 lo/hi, 나머지 해제)", async () => {
    const prefill = { method: "halton" as const, n: 12, seed: 7, params: [{ name: "B1_D1", lo: 2.5, hi: 7.5 }] };
    const r = renderApp("/p/p-body/doe/doe-5", "power", (s) => {
      const x = s.doe.recs.find((q) => q.out.id === "doe-5")!;
      x.out.doe = null;
      x.out.inputs.spec_prefill = prefill;
    });
    const lo = (await screen.findByLabelText("B1 D1 하한", {}, { timeout: 15000 })) as HTMLInputElement;
    expect(lo.value).toBe("2.5");
    expect((screen.getByLabelText("B1 D1 상한") as HTMLInputElement).value).toBe("7.5");
    expect((screen.getByLabelText("B1 D1 포함") as HTMLInputElement).checked).toBe(true);
    const others = (screen.getAllByRole("checkbox") as HTMLInputElement[]).filter((c) => /포함$/.test(c.getAttribute("aria-label") ?? "") && c.getAttribute("aria-label") !== "B1 D1 포함");
    expect(others.length).toBeGreaterThan(0);
    expect(others.every((c) => !c.checked)).toBe(true);
    expect((screen.getByLabelText("시드") as HTMLInputElement).value).toBe("7");
    expect(r.server.doe.recs.find((q) => q.out.id === "doe-5")!.out.doe).toBeNull();
  }, 40000);
});
