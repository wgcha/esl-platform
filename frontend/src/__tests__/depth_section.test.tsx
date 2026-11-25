// V-0247-DM-15·16·26 (esl_bead_depth_mode.md §7·§8): 깊이 단면 동작 화면(목) — 새 스터디 라디오·스터디 머리 칩·변수 표 D 배지·W 사유 줄·W1 꼬리표·SectionMini ds_dD.
// 문구는 API text(w_reason·DS_FALLBACK message·settings.depth_section_notes)를 그대로 쓴다 — 시험도 같은 값을 비교한다.
// 화면 크기(2560·1920 scrollHeight)는 scripts/screenshots-v0247-f1.mjs.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DEPTH_SECTION_LABEL, DEPTH_SECTION_TIP, cloneDepthNote, depthSectionChip, droppedOneSide } from "../api/doe";
import type { DoeParam, DoeParamsOut, DoeSection } from "../api/types";
import { DoeParamTable } from "../components/DoeParamTable";
import { SectionMini, sectionLine } from "../components/SectionMini";
import { MOCK_MESSAGES, mockWReason } from "../mock/graphmock";
import { renderApp } from "../test/render";

const P = (name: string, type: "D" | "W", bead: string, extra: Partial<DoeParam> = {}): DoeParam => ({
  name, type, bead, nominal: 10, feasible: [1, 20], feasible_source: "estimate", default_range: [8, 12], use_default: true, group_members: [], ...extra,
});
const B = (id: string, extra: Record<string, unknown> = {}) => ({ id, k: 1, shape: "select", sense: "concave", center_ab: [0, 0] as [number, number], nominal: { depth: 6, width: 30 }, fixed_overlap: false, png: null, kind: "select" as const, name: `비드 ${id}`, n_tiers: 1, W_nom: 30, warnings: [], ...extra });
const wtext = (c: string) => mockWReason(c).text;

function table(data: DoeParamsOut, onChange: (r: unknown) => void = () => undefined) {
  const rows = data.params.map((p) => ({ name: p.name, on: p.use_default, lo: String(p.default_range[0]), hi: String(p.default_range[1]) }));
  return render(
    <DoeParamTable data={data} rows={rows} setRows={onChange} readOnly={false} beadPngUrl={() => ""} select={{ blendOf: () => "auto", setBlend: () => undefined, kBlend: null, blendMax: 200, active: null, onActive: () => undefined }} />,
  );
}

describe("순수 함수·상수(라벨은 api/doe.ts 한 곳)", () => {
  it("스터디 머리 칩 3종: 깊이면 폭 유지 | 입구 고정 | 키 없음 = 입구 고정(이전)", () => {
    expect(depthSectionChip("floor_fixed")).toEqual({ text: "깊이면 폭 유지", legacy: false });
    expect(depthSectionChip("entry_fixed")).toEqual({ text: "입구 고정", legacy: false });
    expect(depthSectionChip(undefined)).toEqual({ text: "입구 고정(이전)", legacy: true });
    expect(depthSectionChip(null).legacy).toBe(true);
  });

  it("복제 안내: 같으면 없음, 입구→깊이면 = DS_CLONE_NOTE, 깊이면→입구 = {n}·{names} 치환(0개면 _NONE 문구)", () => {
    const notes = { DS_CLONE_NOTE: "깊이 동작만 바뀝니다", DS_CLONE_NOTE_ENTRY: "변수 {n}개({names})가 빠집니다", DS_CLONE_NOTE_ENTRY_NONE: "빠지는 변수 없음" };
    expect(cloneDepthNote(notes, "entry_fixed", "entry_fixed", [])).toBeNull();
    expect(cloneDepthNote(notes, "floor_fixed", "floor_fixed", ["B3_W"])).toBeNull();
    expect(cloneDepthNote(notes, "entry_fixed", "floor_fixed", [])).toBe("깊이 동작만 바뀝니다");
    expect(cloneDepthNote(notes, "floor_fixed", "entry_fixed", ["B3_W", "B5_W"])).toBe("변수 2개(B3_W, B5_W)가 빠집니다");
    expect(cloneDepthNote(notes, "floor_fixed", "entry_fixed", [])).toBe("빠지는 변수 없음");
    expect(cloneDepthNote(undefined, "entry_fixed", "floor_fixed", [])).toBeNull();
  });

  it("droppedOneSide: 원 spec 변수 중 w_side one 만", () => {
    const ps = [P("B1_D", "D", "b1"), P("B3_W", "W", "b3", { w_side: "one" }), P("B4_W", "W", "b4")];
    const spec = { method: "lhs" as const, n: 10, seed: 1, params: [{ name: "B1_D", lo: 1, hi: 2 }, { name: "B3_W", lo: 1, hi: 2 }] };
    expect(droppedOneSide(spec, ps)).toEqual(["B3_W"]);
    expect(droppedOneSide(null, ps)).toEqual([]);
    expect(droppedOneSide(spec, null)).toEqual([]);
  });
});

describe("SectionMini — 깊이 점선 (s + ΔD·ds_dD, z + ΔD·dz_dD)", () => {
  const sec: DoeSection = { s: [-20, -10, 10, 20], z: [0, 5, 5, 0], dz_dD: { "1": [0, 1, 1, 0] }, ds_dD: { "1": [-1, 0, 0, 1] }, ds_dW: [-0.5, -0.5, 0.5, 0.5], dz_dW: [0, 0, 0, 0] };
  const v = { type: "D" as const, tier: 1, nominal: 5, lo: 4, hi: 7 };
  it("ds_dD 있으면 입구(바깥)만 벌어지고 깊이면 가로는 그대로", () => {
    expect(sectionLine(sec, v, 7)).toEqual([[-22, 0], [-10, 7], [10, 7], [22, 0]]);
    expect(sectionLine(sec, v, 4)).toEqual([[-19, 0], [-10, 4], [10, 4], [19, 0]]);
  });
  it("ds_dD 없음(옛 응답·입구 고정 elems) = 0 — 지금 그림 그대로", () => {
    const { ds_dD: _x, ...old } = sec;
    expect(sectionLine(old, v, 7)).toEqual([[-20, 0], [-10, 7], [10, 7], [20, 0]]);
    expect(sectionLine({ ...sec, ds_dD: null }, v, 7)[0]).toEqual([-20, 0]);
  });
  it("한쪽 비드 = 열린 쪽만 값(고정 쪽 0) → 한쪽만 벌어진 그림, W1 ds_dW 열린 쪽 +1·고정 쪽 0", () => {
    const one: DoeSection = { ...sec, ds_dD: { "1": [0, 0, 0, 1] }, ds_dW: [0, 0, 1, 1] };
    expect(sectionLine(one, v, 7).map((p) => p[0])).toEqual([-20, -10, 10, 22]);
    const w = { type: "W" as const, nominal: 20, lo: 18, hi: 24 };
    expect(sectionLine(one, w, 24).map((p) => p[0])).toEqual([-20, -10, 14, 24]);
  });
  it("그려진다(점선 2·실선 1)", () => {
    render(<SectionMini sec={sec} v={v} title="B1" />);
    expect(screen.getByTestId("section-lo")).toBeTruthy();
    expect(screen.getByTestId("section-hi")).toBeTruthy();
  });
});

describe("변수 표 — D 배지·W 사유 줄·W1 꼬리표(문구 = API text)", () => {
  const fb = { code: "DS_FALLBACK", level: "info" as const, bead: "b3", var: "B3_D", reason: "W_ENTRY_NONE", message: "서버 DS_FALLBACK 문구" };
  const data = (): DoeParamsOut => ({
    beads: [
      B("b1", { w_reason: undefined }),
      B("b2", { w_reason: mockWReason("W_SHORT") }),
      B("b3", { w_reason: mockWReason("W_ENTRY_NONE") }),
      B("b4", { w_reason: mockWReason("W_NETWORK") }),
      B("b5"),
    ],
    params: [
      P("B1_D", "D", "b1", { section: { mode: "floor_fixed", cot_deg: 45, applied: true } }),
      P("B1_W", "W", "b1"),
      P("B2_D", "D", "b2"),
      P("B2_W", "W", "b2", { use_default: false }),
      P("B3_D", "D", "b3", { section: { mode: "floor_fixed", cot_deg: 45, applied: false, reason: "W_ENTRY_NONE" } }),
      P("B4_D", "D", "b4"),
      P("B5_D", "D", "b5"),
      P("B5_W", "W", "b5", { w_side: "one" }),
    ],
    warnings: [fb],
  });

  it("W 행 없음 = 회색 'W 사용 불가 · <API text>'(체크 칸 없음), 사유 없는 비드는 줄 없음", () => {
    table(data());
    for (const [id, code] of [["b3", "W_ENTRY_NONE"], ["b4", "W_NETWORK"]] as const) {
      const tr = screen.getByTestId(`w-na-${id}`);
      expect(tr.textContent).toBe(`W 사용 불가 · ${wtext(code)}`);
      expect(tr.classList.contains("doe-w-na")).toBe(true);
      expect(tr.querySelector("input")).toBeNull();
      expect(tr.getAttribute("data-code")).toBe(code);
    }
    expect(screen.queryByTestId("w-na-b1")).toBeNull();
    expect(screen.queryByTestId("w-na-b2")).toBeNull(); // W 행이 있으면 사용 불가 줄 아님
    expect(screen.queryByTestId("w-na-b5")).toBeNull();
  });

  it("기본 끔 = W 행 체크 해제 + 줄 끝 사유(use_default true 인 W 행은 사유 없음)", () => {
    table(data());
    const chk = screen.getByLabelText("B2 W 포함") as HTMLInputElement;
    expect(chk.checked).toBe(false);
    expect(screen.getByTestId("wreason-B2_W").textContent?.trim()).toBe(wtext("W_SHORT"));
    expect(screen.queryByTestId("wreason-B1_W")).toBeNull();
    expect(screen.queryByTestId("wreason-B5_W")).toBeNull();
  });

  it("D 행 DS_FALLBACK 배지 '입구 고정'(툴팁 = 서버 DS_FALLBACK message) — applied 인 D 행은 배지 없음", () => {
    table(data());
    const b = screen.getByTestId("dsfb-B3_D");
    expect(b.textContent).toBe("입구 고정");
    expect(b.getAttribute("title")).toBe("서버 DS_FALLBACK 문구");
    expect(b.getAttribute("data-reason")).toBe("W_ENTRY_NONE");
    expect(screen.queryByTestId("dsfb-B1_D")).toBeNull();
    expect(screen.queryByTestId("dsfb-B2_D")).toBeNull();
    expect(document.querySelectorAll('[data-testid^="dsfb-"]').length).toBe(1);
  });

  it("DS_FALLBACK 문구가 없으면 툴팁 = 사유 코드(문구 거울 없음)", () => {
    const d = data();
    d.warnings = [];
    table(d);
    expect(screen.getByTestId("dsfb-B3_D").getAttribute("title")).toBe("W_ENTRY_NONE");
  });

  it("W1 행 = 이름 옆 꼬리표 '한쪽'(툴팁 '한쪽 입구만 이동'), 양쪽 W 행은 꼬리표 없음, W1 행은 체크된 채", () => {
    table(data());
    const t = screen.getByTestId("w1-B5_W");
    expect(t.textContent).toBe("한쪽");
    expect(t.getAttribute("title")).toBe("한쪽 입구만 이동");
    expect(screen.queryByTestId("w1-B1_W")).toBeNull();
    expect((screen.getByLabelText("B5 W 포함") as HTMLInputElement).checked).toBe(true);
  });

  it("옛 응답(section·w_side·w_reason 없음) = 새 요소 0 — 지금 표 그대로", () => {
    const d: DoeParamsOut = { beads: [B("b1"), B("b2")], params: [P("B1_D", "D", "b1"), P("B1_W", "W", "b1"), P("B2_D", "D", "b2")], warnings: [] };
    table(d);
    expect(document.querySelectorAll('[data-testid^="dsfb-"],[data-testid^="w1-"],[data-testid^="w-na-"],[data-testid^="wreason-"]').length).toBe(0);
  });
});

describe("새 스터디 라디오(select 만) · 스터디 머리 칩", () => {
  it("select 새 스터디: 라디오 2개, 기본 = GET /doe/settings.depth_section, 툴팁 = 계약 문구, 요청에 선택값", async () => {
    const r = renderApp("/p/p-body/doe/new?entries=le-1", "power");
    const g = await screen.findByRole("radiogroup", { name: "깊이 동작" }, { timeout: 10000 });
    expect(g.getAttribute("title")).toBe(DEPTH_SECTION_TIP);
    expect(DEPTH_SECTION_TIP).toBe("선택(요소) 비드는 입구 고정에서 사면이 가팔라짐 · 한쪽 입구 비드는 입구가 한쪽만 넓어짐(중심선 치우침)");
    const rs = within(g).getAllByRole("radio") as HTMLInputElement[];
    expect(rs.map((x) => x.value)).toEqual(["entry_fixed", "floor_fixed"]);
    expect(within(g).getByLabelText(DEPTH_SECTION_LABEL.floor_fixed)).toBeTruthy();
    expect(DEPTH_SECTION_LABEL.entry_fixed).toBe("입구 고정(깊이면 좁아짐)");
    expect(DEPTH_SECTION_LABEL.floor_fixed).toBe("깊이면 폭 유지(입구 넓어짐)");
    expect(r.server.doe.settings.depth_section).toBe("floor_fixed");
    expect(rs.map((x) => x.checked)).toEqual([false, true]);
    fireEvent.click(rs[0]);
    expect(rs.map((x) => x.checked)).toEqual([true, false]);
    const prep = await screen.findByRole("button", { name: "입력 준비" });
    await waitFor(() => expect((prep as HTMLButtonElement).disabled).toBe(false), { timeout: 10000 });
    const n0 = r.server.doe.recs.length;
    fireEvent.click(prep);
    await waitFor(() => expect(r.server.doe.recs.length).toBe(n0 + 1), { timeout: 10000 });
    expect(r.server.doe.recs[n0].out.inputs.depth_section).toBe("entry_fixed");
  }, 30000);

  it("설정에 depth_section 이 없으면(옛 서버) 라디오 숨김", async () => {
    renderApp("/p/p-body/doe/new?entries=le-1", "power", (s) => {
      delete s.doe.settings.depth_section;
    });
    await screen.findByRole("radiogroup", { name: "시나리오" }, { timeout: 10000 });
    await screen.findByRole("button", { name: "입력 준비" });
    expect(screen.queryByRole("radiogroup", { name: "깊이 동작" })).toBeNull();
  }, 20000);

  it("④ 형상 비교로 바꾸면 라디오 숨김", async () => {
    renderApp("/p/p-body/doe/new?entries=le-1", "power");
    await screen.findByRole("radiogroup", { name: "깊이 동작" }, { timeout: 10000 });
    const cmp = within(screen.getByRole("radiogroup", { name: "시나리오" })).getAllByRole("radio").find((x) => /④/.test(x.closest("label")?.textContent ?? "")) as HTMLInputElement;
    fireEvent.click(cmp);
    await waitFor(() => expect(screen.queryByRole("radiogroup", { name: "깊이 동작" })).toBeNull());
  }, 20000);

  it("스터디 머리 칩: 키 없음 = 입구 고정(이전) · floor_fixed = 깊이면 폭 유지 · entry_fixed = 입구 고정 · ④ 는 칩 없음", async () => {
    const r = renderApp("/p/p-body/doe/doe-6", "power");
    const chip = await screen.findByTestId("ds-chip", {}, { timeout: 10000 });
    expect(chip.textContent).toBe("입구 고정(이전)");
    r.unmount();
    const r2 = renderApp("/p/p-body/doe/doe-6", "power", (s) => {
      s.doe.recs.find((x) => x.out.id === "doe-6")!.out.inputs.depth_section = "floor_fixed";
    });
    expect((await screen.findByTestId("ds-chip", {}, { timeout: 10000 })).textContent).toBe("깊이면 폭 유지");
    r2.unmount();
    const r3 = renderApp("/p/p-body/doe/doe-6", "power", (s) => {
      s.doe.recs.find((x) => x.out.id === "doe-6")!.out.inputs.depth_section = "entry_fixed";
    });
    expect((await screen.findByTestId("ds-chip", {}, { timeout: 10000 })).textContent).toBe("입구 고정");
    r3.unmount();
    renderApp("/p/p-body/doe/doe-20", "power");
    await screen.findByRole("heading", { name: "강성 평가 스터디" }, { timeout: 10000 });
    await screen.findByRole("button", { name: "복제" }, { timeout: 10000 });
    await waitFor(() => expect(screen.queryByTestId("ds-chip")).toBeNull());
  }, 40000);
});

describe("목 서버 floor_fixed 스터디의 변수 표(통합)", () => {
  it("DS_FALLBACK 배지·W 사유 줄·W1 꼬리표가 params 응답 그대로 그려진다", async () => {
    const r = renderApp("/p/p-body/doe/doe-30", "power", (s) => {
      s.doe.demoShape();
      s.doe.recs.find((x) => x.out.id === "doe-30")!.out.inputs.depth_section = "floor_fixed";
    });
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy(), { timeout: 10000 });
    const rec = r.server.doe.recs.find((x) => x.out.id === "doe-30")!;
    const ps = r.server.doe.paramsOf(rec);
    await waitFor(() => expect(document.querySelectorAll('[data-testid^="param-"]').length).toBeGreaterThan(0), { timeout: 10000 });
    const one = ps.filter((p) => p.w_side === "one");
    const fb = ps.filter((p) => p.type === "D" && p.section && !p.section.applied);
    expect(one.length).toBe(1);
    expect(fb.length).toBe(1);
    for (const p of one) expect(screen.getByTestId(`w1-${p.name}`).textContent).toBe("한쪽");
    for (const p of fb) {
      expect(screen.getByTestId(`dsfb-${p.name}`).getAttribute("title")).toBe(MOCK_MESSAGES.DS_FALLBACK.replace(/\s*\(Info[^)]*\)\s*$/, "").replace("{bead}", p.bead).replace("{var}", p.name).replace("{reason}", p.section!.reason!));
    }
    expect(document.querySelectorAll('[data-testid^="w-na-"]').length).toBeGreaterThan(0);
  }, 40000);
});
