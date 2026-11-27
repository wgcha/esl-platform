// V-0252-28·29 (F1 몫): ② 곡선 클릭 → 가장 가까운 프레임, "직접" 행(입력·변위 칸 3가지), 확정 비활성 사유, 권한 없으면 클릭 무시,
// "현재 t*" 줄(직접 고름 · 자동 대비 %)·경고색, frame_stride 2 에서 세로선 위치. (화면 높이 증가 0 은 scripts/screenshots-v0252-f1.mjs)
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/endpoints";
import type { TstarView } from "../api/types";
import { MaxHoldChart } from "../components/MaxHoldChart";
import { curvePoints, dispState, manualFromCurve, manualNotes, parseManual } from "../lib/tstarFrames";
import { renderApp } from "../test/render";

const url = "/p/p-body/c/c-demo/stage/2";

afterEach(() => vi.restoreAllMocks());

async function openStage2(user: "power" | "general" = "power") {
  const r = renderApp(url, user);
  await screen.findByTestId("manual-row");
  return r;
}
/** 곡선 svg 에 x(시간) 위치를 클릭 — jsdom 은 좌표가 0 이라 getBoundingClientRect 를 고정한다 */
function clickCurve(svg: Element, frameTime: number, W = 600) {
  (svg as SVGSVGElement).getBoundingClientRect = () => ({ left: 0, top: 0, right: W, bottom: 300, width: W, height: 300, x: 0, y: 0, toJSON() {} }) as DOMRect;
  // 폭 600 · 여백 l 58 r 14 → plot 528 px. 전체 시간 0..0.125
  const px = 58 + (frameTime / 0.125) * (W - 58 - 14);
  fireEvent.click(svg, { clientX: px, clientY: 100 });
}

describe("lib/tstarFrames", () => {
  const pts = [0, 1, 2, 3, 4].map((f) => ({ frame: f * 2, time: f * 0.002, value: f }));
  it("직접 칸 해석: 정수 = 프레임, 소수점·s = 시간(가장 가까운 프레임), 범위 밖", () => {
    expect(parseManual("4", pts)).toEqual({ ok: true, frame: 4 });
    expect(parseManual("5", pts)).toEqual({ ok: false, reason: "range" }); // stride 2 — 5 는 h3d 에 없음
    expect(parseManual("0.0039", pts)).toEqual({ ok: true, frame: 4 });
    expect(parseManual("0.003", pts)).toEqual({ ok: true, frame: 2 }); // 동률 = 앞 프레임
    expect(parseManual("0.004s", pts)).toEqual({ ok: true, frame: 4 });
    expect(parseManual("12s", pts)).toEqual({ ok: false, reason: "range" });
    expect(parseManual("", pts)).toEqual({ ok: false, reason: "empty" });
    expect(parseManual("abc", pts)).toEqual({ ok: false, reason: "format" });
  });
  it("자동 대비 %·rel·경고 문구(LOW 는 임계가 있을 때만)", () => {
    const m = manualFromCurve(pts, 2, 6)!;
    expect(m.rel).toBe("before");
    expect(m.ratio).toBeCloseTo(1 / 3);
    const notes = manualNotes(m, 2, 0.002, 0.5);
    expect(notes.map((n) => n.code)).toEqual(["TSTAR_MANUAL", "TSTAR_MANUAL_LOW"]);
    expect(notes[0].text).toContain("33 %");
    expect(manualNotes(m, 2, 0.002, undefined).map((n) => n.code)).toEqual(["TSTAR_MANUAL"]);
    const after = manualFromCurve(pts, 8, 4)!;
    expect(manualNotes(after, 8, 0.008, 0.5).map((n) => n.code)).toEqual(["TSTAR_MANUAL", "TSTAR_MANUAL_AFTER"]);
  });
  it("변위 칸 3가지", () => {
    const v = { frames_D: [1], frames_have: [1, 5], fill: { available: true, code: null, text: null } } as unknown as TstarView;
    expect(dispState(5, v)).toBe("have");
    expect(dispState(7, v)).toBe("fill");
    expect(dispState(7, { ...v, fill: { available: false, code: "DUMP_MODE", text: "덤프" } })).toBe("blocked");
    expect(dispState(7, { frames_D: [1] } as unknown as TstarView)).toBe("blocked"); // 옛 서버
  });
});

describe("② 곡선 클릭·직접 행", () => {
  it("곡선 클릭 → 가장 가까운 프레임이 직접 행에 들어가고 세로선이 따라간다", async () => {
    await openStage2();
    const svg = screen.getByTestId("maxhold-svg");
    clickCurve(svg, 0.0301); // 프레임 30 근처(후보 아님)
    await waitFor(() => expect((screen.getByTestId("manual-input") as HTMLInputElement).value).toBe("30"));
    const row = screen.getByTestId("manual-row");
    expect(row.textContent).toContain("0.030");
    expect(screen.getByTestId("manual-disp").textContent).toContain("ESL 때 읽음");
    expect((screen.getByLabelText("직접") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByTestId("tstar-marker").textContent).toContain("0.030");
    expect(screen.getByTestId("manual-value").textContent).toMatch(/\(\d+ %\)/);
  });
  it("입력 12(프레임) · 0.012 · 12s(시간)", async () => {
    await openStage2();
    const inp = screen.getByTestId("manual-input") as HTMLInputElement;
    for (const [text, frame] of [["12", "12"], ["0.020", "20"], ["30s", "-"]] as const) {
      fireEvent.change(inp, { target: { value: text } });
      fireEvent.keyDown(inp, { key: "Enter" });
      if (frame === "-") {
        // 30 s 는 범위 밖(0..0.125) — 빨간 테두리, 선택 불변
        await waitFor(() => expect(inp.getAttribute("aria-invalid")).toBe("true"));
        expect(inp.title).toBe("h3d 에 없는 프레임");
      } else {
        await waitFor(() => expect(screen.getByTestId("manual-row").textContent).toContain(`${frame}`));
        expect((screen.getByLabelText("직접") as HTMLInputElement).checked).toBe(true);
      }
    }
  });
  it("후보 점 클릭 = 그 후보(직접 행 아님) · 후보 표 선택 동작 그대로", async () => {
    await openStage2();
    const cand = screen.getAllByRole("radio").filter((r) => /^프레임 \d+$/.test(r.getAttribute("aria-label") ?? ""))[1] as HTMLInputElement;
    fireEvent.click(cand);
    expect(cand.checked).toBe(true);
    expect((screen.getByLabelText("직접") as HTMLInputElement).checked).toBe(false);
  });
  it("불가 프레임: 라디오 비활성 + 변위 칸 불가(사유 title) + [t* 확정] 비활성 사유", async () => {
    const real = api.tstar;
    vi.spyOn(api, "tstar").mockImplementation(async (id: string) => ({ ...(await real(id)), fill: { available: false, code: "DUMP_MODE", text: "변형률을 순간값으로 받은 Case(덤프 방식)는 후보 프레임만 고를 수 있습니다" } }));
    await openStage2();
    clickCurve(screen.getByTestId("maxhold-svg"), 0.0301);
    await waitFor(() => expect(screen.getByTestId("manual-disp").textContent).toBe("불가"));
    expect(screen.getByTestId("manual-disp").querySelector("[title]")?.getAttribute("title")).toContain("덤프 방식");
    expect((screen.getByLabelText("직접") as HTMLInputElement).disabled).toBe(true);
    const confirm = screen.getByRole("button", { name: "t* 확정" }) as HTMLButtonElement;
    expect(confirm.disabled || confirm.getAttribute("aria-disabled") === "true").toBe(true);
    expect(document.body.textContent + (confirm.title ?? "") + (confirm.getAttribute("aria-label") ?? "")).toContain("이 시점은 고를 수 없습니다");
  });
  it("권한 없음(general): 곡선 클릭 무시·입력 비활성", async () => {
    await openStage2("general");
    expect((screen.getByTestId("manual-input") as HTMLInputElement).disabled).toBe(true);
    clickCurve(screen.getByTestId("maxhold-svg"), 0.0301);
    expect((screen.getByTestId("manual-input") as HTMLInputElement).value).toBe("");
  });
  it("확정 → 현재 t* 줄 '직접 고름 · 자동 대비 %' + 경고색(임계 미만)", async () => {
    await openStage2();
    clickCurve(screen.getByTestId("maxhold-svg"), 0.0101); // 프레임 10 — 값이 자동 t* 의 절반 미만
    await waitFor(() => expect((screen.getByTestId("manual-input") as HTMLInputElement).value).toBe("10"));
    fireEvent.click(screen.getByRole("button", { name: "t* 확정" }));
    const line = await screen.findByText(/직접 고름 · 자동 대비/, undefined, { timeout: 5000 });
    expect(line.textContent).toMatch(/직접 고름 · 자동 대비 \d+ %/);
    const m = /자동 대비 (\d+) %/.exec(line.textContent ?? "")!;
    expect(line.closest("[data-testid=current-tstar]")?.className.includes("warn-text")).toBe(Number(m[1]) < 50);
  });
});

describe("MaxHoldChart frame_stride 2", () => {
  it("세로선 = 그 프레임의 시각(프레임 번호 ≠ 배열 위치)", () => {
    const time = [0, 0.002, 0.004, 0.006];
    render(<MaxHoldChart time={time} value={[0, 1, 2, 3]} candidates={[]} selectedFrame={4} label="x" frames={[0, 2, 4, 6]} />);
    expect(screen.getByTestId("tstar-marker").textContent).toContain("0.004");
  });
  it("hover: 프레임·시간·값 글자(그림 안)", () => {
    const time = [0, 0.002, 0.004, 0.006];
    render(<MaxHoldChart time={time} value={[0, 1, 2, 3]} candidates={[]} selectedFrame={null} label="x" frames={[0, 2, 4, 6]} onPick={() => {}} />);
    const svg = screen.getByTestId("maxhold-svg") as unknown as SVGSVGElement;
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, right: 600, bottom: 300, width: 600, height: 300, x: 0, y: 0, toJSON() {} }) as DOMRect;
    fireEvent.mouseMove(svg, { clientX: 58 + 528 * 0.66, clientY: 100 });
    expect(screen.getByTestId("chart-hover").textContent).toContain("프레임 4");
  });
  it("curvePoints: history.frame_index 우선, 없으면 frames, 없으면 위치", () => {
    const blk = { history: { time: [0, 1], value: [0, 1], frame_index: [0, 2] } } as never;
    expect(curvePoints(blk, null).map((p) => p.frame)).toEqual([0, 2]);
    const blk2 = { history: { time: [0, 1], value: [0, 1] } } as never;
    expect(curvePoints(blk2, { frames: [{ frame_index: 3, time: 0 }, { frame_index: 5, time: 1 }] } as TstarView).map((p) => p.frame)).toEqual([3, 5]);
    expect(curvePoints(blk2, null).map((p) => p.frame)).toEqual([0, 1]);
  });
});
