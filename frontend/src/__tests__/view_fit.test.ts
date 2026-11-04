// v0.15.1 시점 계산(viewFit — three 무관): 축·방향·up, 같은 축 토글, 맞춤 반높이(화면비), 요소 bbox.
import { describe, expect, it } from "vitest";
import { FIT_MARGIN, elemsBbox, fitView, nextSign, viewBasis, viewLabel } from "../view3d/viewFit";

describe("viewFit", () => {
  it("축·방향·up·이름", () => {
    expect(viewBasis("x", -1)).toEqual({ eye: [-1, 0, 0], up: [0, 0, 1] });
    expect(viewBasis("z", 1)).toEqual({ eye: [0, 0, 1], up: [0, 1, 0] });
    const iso = viewBasis("iso", 1).eye;
    expect(Math.hypot(...iso)).toBeCloseTo(1, 12);
    expect(viewLabel("y", -1)).toBe("−Y 보기");
    expect(nextSign(null, "x")).toBe(1);
    expect(nextSign({ axis: "x", sign: 1 }, "x")).toBe(-1);
    expect(nextSign({ axis: "x", sign: -1 }, "x")).toBe(1);
    expect(nextSign({ axis: "x", sign: -1 }, "y")).toBe(1);
  });
  it("맞춤: 위에서(+Z) 100×60 판 — 화면비 1 이면 반높이 = 50·여백, 2 면 30·여백(세로 기준)", () => {
    const b = { min: [0, 0, 0], max: [100, 60, 20] };
    const v = viewBasis("z", 1);
    const r1 = fitView(b, v.eye, v.up, 1, "ortho");
    expect(r1.halfH).toBeCloseTo(50 * FIT_MARGIN, 9);
    expect(r1.target).toEqual([50, 30, 10]);
    const r2 = fitView(b, v.eye, v.up, 2, "ortho");
    expect(r2.halfH).toBeCloseTo(30 * FIT_MARGIN, 9);
    const rp = fitView(b, v.eye, v.up, 2, "persp", 40);
    expect(rp.position[2] - 10).toBeCloseTo((30 * FIT_MARGIN) / Math.tan((20 * Math.PI) / 180) + 10, 6);
    // 크기 0 bbox → 최소 반높이
    expect(fitView({ min: [1, 1, 1], max: [1, 1, 1] }, v.eye, v.up, 1, "ortho").halfH).toBeCloseTo(FIT_MARGIN, 9);
  });
  it("요소 bbox: 고른 요소의 삼각형 꼭짓점만", () => {
    const pos = Float32Array.from([0, 0, 0, 1, 0, 0, 0, 1, 0, 5, 5, 5]);
    const idx = Uint32Array.from([0, 1, 2, 1, 3, 2]);
    const t2e = Uint32Array.from([0, 1]);
    expect(elemsBbox(pos, idx, t2e, (e) => e === 0)).toEqual({ min: [0, 0, 0], max: [1, 1, 0] });
    expect(elemsBbox(pos, idx, t2e, () => false)).toBeNull();
  });
});
