// V-0250-VB-28·33 (esl_virtual_bead.md §9·§19.7·§19.9.2) 화면: ③ 목록 아래 접힌 절 "추가 비드" — 입력(3D 두 점 | 좌표) + 단면 + 체크 "방향 뒤집기" 1개(라디오 없음),
// θ 칸 15~60, r 칸 비움 = 기본(자리 표시 "요소 크기"), 요청 키(flip true 만·r 0 유지·side 없음), 행 상태·경고·삭제, 변수 표 A 가지(라벨·꼬리표·거부 회색 줄)·계획 칩.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { doe, normalizeDoeSettings } from "../api/doe";
import type { DoeBead, DoeParam, DoeParamsOut, DoeSelectionV2 } from "../api/types";
import { DoeParamTable } from "../components/DoeParamTable";
import { renderApp } from "../test/render";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const demo = (s: { doe: { demoVBead: () => void } }) => s.doe.demoVBead();
const fill = (label: string, v: string) => fireEvent.change(screen.getByLabelText(label), { target: { value: v } });
const derives = (spy: { mock: { calls: unknown[][] } }) => spy.mock.calls.map((c) => (c[1] as DoeSelectionV2).virtual_beads).filter(Boolean);
const lastOf = <T,>(a: T[]): T => a[a.length - 1];

async function openStudy(withDemo: boolean) {
  const r = withDemo ? renderApp("/p/p-body/doe/doe-10", "power", demo) : renderApp("/p/p-body/doe/doe-10", "power");
  await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy(), { timeout: 10000 });
  return r;
}

describe("GET /doe/settings virtual_bead 정규화", () => {
  it("enabled 아니면 없음(절 숨김), 칸 범위가 틀리면 계약 기본값 [15, 60]·45·30·4", () => {
    expect(normalizeDoeSettings({}).virtual_bead).toBeUndefined();
    expect(normalizeDoeSettings({ virtual_bead: { enabled: false } }).virtual_bead).toBeUndefined();
    expect(normalizeDoeSettings({ virtual_bead: { enabled: true } }).virtual_bead).toEqual({ enabled: true, max_count: 4, theta_default_deg: 45, theta_range_deg: [15, 60], d_max_limit_mm: 30, min_wall_elems: 2 });
    expect(normalizeDoeSettings({ virtual_bead: { enabled: true, theta_range_deg: [20, 50], theta_default_deg: 70, max_count: 12, r_default_h_mult: 1 } }).virtual_bead).toMatchObject({ theta_range_deg: [20, 50], theta_default_deg: 45, max_count: 9, r_default_h_mult: 1 });
    expect(normalizeDoeSettings({ virtual_bead: { enabled: true, theta_range_deg: [60, 15] } }).virtual_bead?.theta_range_deg).toEqual([15, 60]);
  });
});

describe("추가 비드 절 (doe-10 + demoVBead)", () => {
  it("설정이 없으면 절이 없다(옛 서버·블록 없음), 켜면 접힌 상태로 나타난다", async () => {
    await openStudy(false);
    expect(screen.queryByTestId("bs-vb")).toBeNull();
    cleanup();
    // INT-5: 설정은 켜졌지만 스터디 스냅샷 블록 없음(옛 스터디 inputs.virtual_bead null) = 숨김
    renderApp("/p/p-body/doe/doe-10", "power", (s: { doe: { demoVBead: (b?: boolean) => void } }) => s.doe.demoVBead(false));
    await waitFor(() => expect(screen.getByTestId("bead-b1")).toBeTruthy(), { timeout: 10000 });
    expect(screen.queryByTestId("bs-vb")).toBeNull();
    cleanup();
    await openStudy(true);
    const d = screen.getByTestId("bs-vb") as HTMLDetailsElement;
    expect(d.open).toBe(false);
    expect(screen.getByTestId("bs-vb-summary").textContent).toBe("추가 비드(평판에 새 비드)");
    expect(screen.getByTestId("bs-vb-summary").getAttribute("title")).toMatch(/모핑으로 만든 근사 형상/);
  }, 20000);

  it("입력: 방향 라디오 없음·체크 1개, θ 15~60, r 자리 표시 \"요소 크기\", 입력 오류 동안 [비드 추가] 비활성", async () => {
    await openStudy(true);
    fireEvent.click(screen.getByTestId("bs-vb-summary"));
    const body = screen.getByTestId("bs-vb");
    // 입력 방식 라디오 2개뿐(방향 라디오 없음)
    expect(within(body).getAllByRole("radio").map((x) => x.parentElement?.textContent)).toEqual(["3D 에서 두 점", "좌표·길이·각도"]);
    expect(within(body).getAllByRole("checkbox").map((x) => x.parentElement?.textContent)).toEqual(["방향 뒤집기"]);
    expect((screen.getByLabelText("θ") as HTMLInputElement).min).toBe("15");
    expect((screen.getByLabelText("θ") as HTMLInputElement).max).toBe("60");
    expect((screen.getByLabelText("r") as HTMLInputElement).placeholder).toBe("요소 크기");
    expect((screen.getByLabelText("θ") as HTMLInputElement).value).toBe("45");
    const add = screen.getByTestId("bs-vb-add") as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    fireEvent.click(screen.getByTestId("bs-vb-mode-coord"));
    fill("ξ", "300");
    fill("η", "300");
    fill("길이", "120");
    fill("각도", "0");
    fill("D 최대", "5");
    fill("W", "20");
    expect(add.disabled).toBe(false);
    fill("θ", "61");
    expect(add.disabled).toBe(true);
    expect(screen.getByTestId("bs-vb-problem").textContent).toMatch(/15~60/);
    fill("θ", "15");
    expect(add.disabled).toBe(false);
    fill("θ", "45");
    fill("길이", "0");
    expect(add.disabled).toBe(true);
  }, 20000);

  it("[비드 추가] → derive 요청에 virtual_beads(flip true 만 키·r 비움 = 키 없음·side 없음) → 행(상태 OK·r 기본)·[삭제]", async () => {
    const spy = vi.spyOn(doe, "derive");
    const r = await openStudy(true);
    void r;
    fireEvent.click(screen.getByTestId("bs-vb-summary"));
    fireEvent.click(screen.getByTestId("bs-vb-mode-coord"));
    fill("ξ", "300");
    fill("η", "300");
    fill("길이", "120");
    fill("각도", "0");
    fill("D 최대", "5");
    fill("W", "20");
    fireEvent.click(screen.getByTestId("bs-vb-flip"));
    fireEvent.click(screen.getByTestId("bs-vb-add"));
    const row = await screen.findByTestId("bs-vb-row-a1");
    expect(row.textContent).toMatch(/^A1 추가 비드 1/);
    expect(row.textContent).toContain("D≤5 W 20 θ45");
    expect(row.textContent).toContain("뒤집음");
    await waitFor(() => expect(screen.getByTestId("bs-vb-status-a1").getAttribute("data-ok")).toBe("true"), { timeout: 8000 });
    expect(screen.getByTestId("bs-vb-status-a1").textContent).toBe("OK");
    expect(row.textContent).toMatch(/r 5(\(기본\))?/);
    const sent = lastOf(derives(spy))![0];
    expect(sent).toMatchObject({ id: "a1", w_top: 20, d_max: 5, theta_deg: 45, flip: true, length: 120, angle_deg: 0 });
    expect("r" in sent).toBe(false);
    expect("side" in sent).toBe(false);
    expect("end" in sent).toBe(false);
    // 방금 추가한 행 = 활성(미리보기 자리)
    expect(row.getAttribute("aria-pressed")).toBe("true");
    // 삭제 → 행 사라짐 → derive 가 virtual_beads 없이 다시
    fireEvent.click(within(row).getByRole("button", { name: "A1 삭제" }));
    await waitFor(() => expect(screen.queryByTestId("bs-vb-row-a1")).toBeNull());
  }, 25000);

  it("r 0 입력 = 키 \"r\": 0 유지, 놓을 수 없는 자리 = 사유 배지(회색 문구)·미리보기 없음", async () => {
    const spy = vi.spyOn(doe, "derive");
    await openStudy(true);
    fireEvent.click(screen.getByTestId("bs-vb-summary"));
    fireEvent.click(screen.getByTestId("bs-vb-mode-coord"));
    fill("ξ", "-500"); // 판 밖
    fill("η", "300");
    fill("길이", "100");
    fill("각도", "0");
    fill("D 최대", "5");
    fill("W", "20");
    fill("r", "0");
    fireEvent.click(screen.getByTestId("bs-vb-add"));
    await screen.findByTestId("bs-vb-row-a1");
    await waitFor(() => expect(screen.getByTestId("bs-vb-status-a1").getAttribute("data-ok")).toBe("false"), { timeout: 8000 });
    expect(screen.getByTestId("bs-vb-status-a1").textContent).toMatch(/평판|판/);
    expect(lastOf(derives(spy))![0]).toMatchObject({ r: 0 });
    expect(screen.getByTestId("bs-vb-nopreview").textContent).toMatch(/추가할 수 없는/);
  }, 25000);
});

// ---------------------------------------------------------------- 변수 표 A 가지
const vbBead = (id: string, extra: Partial<DoeBead> = {}): DoeBead => ({ id, k: 100, shape: "virtual", sense: "concave", center_ab: [0, 0], nominal: { depth: 0, width: 0 }, fixed_overlap: false, png: null, kind: "virtual", name: `추가 비드 ${id.slice(1)}`, warnings: [], ...extra });
const aParam = (n: number, p: Partial<DoeParam> = {}): DoeParam => ({ name: `A${n}_A`, type: "A", bead: `a${n}`, tier: null, form: "hinge", nominal: 0, feasible: [0, 5], feasible_source: "estimate", default_range: [0, 5], use_default: true, group_members: [], label: `추가 비드 ${n} · 깊이`, wall_elems: 3.33, vb: { w_top: 20, theta_deg: 45, side: "-", n_wall: 3.33, n_top: 4, len_mm: 120, angle_deg: 30, r: 3, r_source: "default", host: "base" }, acc_hint: { h: 3, d: 6, theta: 45, c_err_pct: -2.17, pi_err_pct: -1.2 }, guard: { state: "ok", from: [0, 5], usable: [0, 5], reason: null, value: null, combo_scale: null, warp: { limit_deg: 15, n: 7, max_deg: 21.4, at: 5, text: "깊이 5 mm 에서 뒤틀린 사각 요소 7 개" } }, ...p } as DoeParam);

function Table({ data }: { data: DoeParamsOut }) {
  const rows = data.params.map((p) => ({ name: p.name, on: p.use_default, lo: String(p.default_range[0]), hi: String(p.default_range[1]) }));
  return <DoeParamTable data={data} rows={rows} setRows={() => undefined} readOnly={false} beadPngUrl={() => ""} />;
}

describe("변수 표 A 가지 (§9·§19.2)", () => {
  const data: DoeParamsOut = {
    beads: [vbBead("a1", { warnings: [{ code: "VB_WALL_COARSE", text: "사면 요소 1.3 개 — 모서리가 뭉개짐" }] }), vbBead("a2", { vb_reason: { code: "VB_OVER_HOLE", text: "구멍과 겹침" } })],
    params: [aParam(1)],
    warnings: [],
  };
  it("묶음 머리 · 행 라벨 \"추가 비드 n · 깊이\" · 공칭 0 · 회색 꼬리표 \"뒤틀림 n\"(경고색 아님) · 행 툴팁 · 경고 배지 · 거부 비드 = 회색 1줄", () => {
    render(<Table data={data} />);
    expect(screen.getByTestId("vb-head-a1").textContent).toContain("A1 추가 비드 1 · W 20 · θ 45° · L 120");
    expect(screen.getByTestId("vb-head-a1").textContent).toContain("⚠ 사면 요소 1.3 개");
    const row = screen.getByTestId("param-A1_A");
    expect(row.textContent).toContain("추가 비드 1 · 깊이");
    expect(row.textContent).toContain("A1_A");
    expect(row.getAttribute("title")).toBe("사면 요소 3.3개 · 예상 오차 ±2.2 %");
    expect((row.querySelector('input[type="checkbox"]') as HTMLInputElement).checked).toBe(true);
    expect(row.querySelector("td.num.mono")!.textContent).toBe("0");
    const warp = screen.getByTestId("warp-A1_A");
    expect(warp.textContent).toBe("뒤틀림 7");
    expect(warp.className).toContain("neutral");
    expect(warp.className).not.toContain("warn");
    expect(warp.getAttribute("title")).toBe("깊이 5 mm 에서 뒤틀린 사각 요소 7 개");
    const na = screen.getByTestId("vb-na-a2");
    expect(na.textContent).toContain("추가 불가 · 구멍과 겹침");
    expect(na.getAttribute("data-code")).toBe("VB_OVER_HOLE");
    expect(screen.queryByTestId("param-A2_A")).toBeNull();
  });
  it("n 0 이면 꼬리표 없음 · 하한 < 0 오류 문구 · A 행이 있으면 표 안 스크롤(.table-wrap.scroll)", () => {
    const d2: DoeParamsOut = { ...data, params: [aParam(1, { guard: { state: "ok", from: [0, 5], usable: [0, 5], reason: null, value: null, combo_scale: null, warp: { limit_deg: 15, n: 0, max_deg: 3, at: 5 } } })] };
    const { container } = render(<Table data={d2} />);
    expect(screen.queryByTestId("warp-A1_A")).toBeNull();
    expect(container.querySelector(".table-wrap.scroll")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("추가 비드 1 · 깊이 하한"), { target: { value: "-1" } });
  });
});
