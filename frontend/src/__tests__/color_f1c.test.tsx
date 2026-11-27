// v0.25.1 F1c — 2D·썸네일·높이 변화 범례 색 통일(계약 esl_view3d_scene_legend.md §5.7·§9.5: V-0251-37 정적·41·42)
import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { dispColor } from "../components/DispOverlay";
import { cellColor } from "../components/FieldOverlay";
import { HeightLegend } from "../components/BeadSelectCard";
import { DoeThumbGrid } from "../components/DoeThumbGrid";
import { css, cssGradient, mapFor, specialCss } from "../lib/colormap";
import { selThumbSvg } from "../mock/selectmock";
import type { DoePreviewOut } from "../api/types";

const src = path.resolve(__dirname, "..");
const read = (p: string) => readFileSync(path.join(src, p), "utf8");
const F1C_FILES = ["components/DispOverlay.tsx", "components/FieldOverlay.tsx", "components/BeadSelectCard.tsx", "components/DoeThumbGrid.tsx", "pages/library/common.tsx", "mock/selectmock.ts"];

describe("V-0251-37 F1c 몫 — TS 정적", () => {
  it("F1c 파일에 정점 리터럴·옛 상수 없음", () => {
    for (const f of F1C_FILES) {
      const t = read(f);
      expect(t, f).not.toMatch(/\b(VIRIDIS|DIVERGING|DIVERGING_GRADIENT|NA_COLOR)\b/);
      expect(t, f).not.toMatch(/\[\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\]\s*,\s*\[\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\]/);
    }
  });
});

describe("V-0251-41 2D 색", () => {
  const range = { min: 2, max: 10 };
  it("변위·ε: 최소 = seq t0(파랑), 최대 = seq t1(빨강)", () => {
    expect(dispColor(2, range)).toBe(css(mapFor("seq"), 0));
    expect(dispColor(10, range)).toBe(css(mapFor("seq"), 1));
    expect(cellColor("esl", 2, "OK", range)).toBe(css(mapFor("seq"), 0));
    expect(cellColor("esl", 10, "OK", range)).toBe(css(mapFor("seq"), 1));
    const rgb = (s: string) => s.match(/\d+/g)!.map(Number);
    expect(rgb(css(mapFor("seq"), 0))[2]).toBeGreaterThan(rgb(css(mapFor("seq"), 0))[0]);
    expect(rgb(css(mapFor("seq"), 1))[0]).toBeGreaterThan(rgb(css(mapFor("seq"), 1))[2]);
  });
  it("오차 %: −R 파랑 · 0 중립 · +R 빨강, 회색 = null", () => {
    const e = { min: -5, max: 5 };
    expect(cellColor("err", -5, "OK", e)).toBe(css(mapFor("div"), 0));
    expect(cellColor("err", 0, "OK", e)).toBe(css(mapFor("div"), 0.5));
    expect(cellColor("err", 5, "OK", e)).toBe(css(mapFor("div"), 1));
    expect(cellColor("err", 1, "NO_REF", e)).toBeNull();
    expect(specialCss("nan")).toMatch(/^rgb\(/);
  });
});

describe("V-0251-42 높이 변화 범례", () => {
  it("새: 빨강 = 깊어짐, 띠 = div(왼쪽 −V 파랑 → 오른쪽 +V 빨강)", () => {
    const { container } = render(<HeightLegend vmax={2} />);
    expect(screen.getByTestId("height-legend").textContent).toContain("빨강 = 깊어짐 · 파랑 = 얕아짐");
    const style = container.querySelector("i")!.getAttribute("style")!;
    expect(style).toContain("linear-gradient");
    expect(style.replace(/\s/g, "")).toContain(cssGradient(mapFor("div")).replace(/\s/g, "").slice(0, 40));
  });
  it("옛(legacy): 옛 문구 · 반전 띠", () => {
    const { container } = render(<HeightLegend vmax={2} legacy />);
    expect(container.textContent).toContain("빨강 = 얕아짐 · 파랑 = 깊어짐");
    expect(container.querySelector("i")!.getAttribute("style")!.replace(/\s/g, "")).toContain(cssGradient(mapFor("div"), { reversed: true }).replace(/\s/g, "").slice(0, 40));
  });
  const prev = (color: Record<string, unknown> | null) => ({ ok: 1, skipped: { collision: 0, fixed: 0, geom: 0, mesh: 0 }, cells: [], color }) as unknown as DoePreviewOut;
  it("DoeThumbGrid: color.map diverge = 새 문구, 키 없음 = 옛 문구", () => {
    const a = render(<DoeThumbGrid preview={prev({ v_max: 1, unit: "mm", map: "diverge" })} params={[]} thumbUrl={() => ""} select />);
    expect(a.container.textContent).toContain("빨강 = 깊어짐");
    a.unmount();
    const b = render(<DoeThumbGrid preview={prev({ v_max: 1, unit: "mm" })} params={[]} thumbUrl={() => ""} select />);
    expect(b.container.textContent).toContain("빨강 = 얕아짐");
  });
  it("목 썸네일: + 깊어짐 = 빨강쪽", () => {
    const params = [{ name: "B1_D1", type: "D", bead: "B1", nominal: 1 }] as never;
    const svg = selThumbSvg({ B1_D1: 2 }, params, 1, "READY");
    expect(svg).toContain(css(mapFor("div"), 1));
  });
});
