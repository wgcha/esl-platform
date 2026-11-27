// v0.25.1 F1a — 색 지도(V-0251-20·21·37·38·39 TS 쪽)·legendModel(22)·기억 v2(23)·공용 확인(30, 정적)·비드 높이 변화(40)·하중 영역 색표(46 색표).
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import CM from "../../../resources/colormaps.json";
import { buildLut, css, cssGradient, mapFor, special, srgb, srgbToLinear, table, validateColormaps, type ColorMap } from "../lib/colormap";
import { bandT } from "../view3d/colors";
import {
  COLOR_MODES,
  LEGEND_DEFAULTS,
  boundaries,
  colorPosition,
  countOut,
  effectiveRange,
  formatValue,
  fromT,
  levelsOf,
  logAllowed,
  normalizeLegend,
  ticks,
  toT,
} from "../view3d/legend/legendModel";
import { VIEWER_KEY_V1, VIEWER_KEY_V2, readLayerPrefs, readLegendPrefs, writeLegendPrefs } from "../view3d/legend/legendPrefs";
import { VIEWER_PLANS } from "../view3d/viewerPlan";
import { designViewData } from "../view3d/part/adapters";
import type { PartMesh } from "../view3d/part/types";

const sha = (b: Uint8Array) => createHash("sha256").update(b).digest("hex");
const RES = CM as unknown as { maps: Record<string, { stops: number[][]; check: string }>; roles: Record<string, string>; special: Record<string, number[]> };

describe("V-0251-20 레인보우", () => {
  const seq = mapFor("seq");
  it("t 0·0.25·0.5·0.75·1 = 파랑·청록·초록·노랑·빨강(기대값은 자원 파일에서 읽음)", () => {
    const stops = RES.maps[RES.roles.seq].stops;
    [0, 0.25, 0.5, 0.75, 1].forEach((t, i) => expect(srgb(seq, t)).toEqual(stops[i]));
    expect(srgb(seq, 0)).toEqual([0, 0, 255]);
    expect(srgb(seq, 1)).toEqual([255, 0, 0]);
  });
  it("띠 색 = 띠 중앙값의 색(bandT), 뒤집기, 선형 색표 변환", () => {
    const t = bandT(5, 0, 9, 9); // 칸 5 의 중앙
    expect(t).toBeCloseTo(5.5 / 9, 12);
    const g = cssGradient(seq, { levels: 9 });
    expect(g).toContain(css(seq, 5.5 / 9));
    const rev = buildLut(seq, { reversed: true });
    const fwd = buildLut(seq);
    for (let j = 0; j < 3; j++) {
      expect(rev[j]).toBe(fwd[255 * 3 + j]);
      expect(rev[255 * 3 + j]).toBe(fwd[j]);
    }
    expect(cssGradient(seq, { reversed: true })).toContain(`${css(seq, 1)} 0%`);
    const lin = buildLut(seq, { linear: true });
    expect(lin[2]).toBeCloseTo(srgbToLinear(255), 9);
    expect(lin[255 * 3]).toBeCloseTo(srgbToLinear(255), 9);
  });
});

describe("V-0251-21 발산", () => {
  const div = mapFor("div");
  it("0 = 흰색, −V 파랑 · +V 빨강, 대칭(t = 0.5 + v/2V)", () => {
    const stops = RES.maps[RES.roles.div].stops;
    expect(srgb(div, 0.5)).toEqual([247, 247, 247]);
    expect(srgb(div, 0)).toEqual(stops[0]);
    expect(srgb(div, 1)).toEqual(stops[stops.length - 1]);
    const lo = srgb(div, 0.0);
    const hi = srgb(div, 1.0);
    expect(lo[2]).toBeGreaterThan(lo[0]); // −V 파랑 쪽
    expect(hi[0]).toBeGreaterThan(hi[2]); // +V 빨강 쪽
    for (const v of [0.1, 0.3, 0.45]) {
      const a = srgb(div, 0.5 - v);
      const b = srgb(div, 0.5 + v);
      expect(a[2]).toBeGreaterThanOrEqual(a[0]);
      expect(b[0]).toBeGreaterThanOrEqual(b[2]);
    }
  });
});

describe("V-0251-37·38·39 자원 하나 · 정점 일치 · 보간 규칙 (TS 쪽)", () => {
  it("38: 지도 3개 × table(map,256) 768바이트 sha256 == 자원 check", () => {
    for (const name of ["rainbow", "diverge", "blues"]) {
      const m = mapFor(name) as ColorMap;
      expect(table(m, 256).length).toBe(768);
      expect(sha(table(m, 256)), name).toBe(RES.maps[name].check);
      expect(m.check).toBe(RES.maps[name].check);
    }
    // 역할 → 지도
    expect(mapFor("seq").name).toBe("rainbow");
    expect(mapFor("div").name).toBe("diverge");
    expect(mapFor("region").name).toBe("blues");
    expect(special("nan")).toEqual(RES.special.nan);
    expect(special("out")).toEqual(RES.special.out);
    expect(special("none")).toEqual(RES.special.none);
  });
  it("39: t = 0·0.5·1 정확한 정점, 범위 밖 자름, NaN = 0, 반올림 = floor(x + 0.5)", () => {
    const seq = mapFor("seq");
    expect(srgb(seq, 0)).toEqual(RES.maps.rainbow.stops[0]);
    expect(srgb(seq, 0.5)).toEqual(RES.maps.rainbow.stops[2]);
    expect(srgb(seq, 1)).toEqual(RES.maps.rainbow.stops[4]);
    expect(srgb(seq, -3)).toEqual(srgb(seq, 0));
    expect(srgb(seq, 9)).toEqual(srgb(seq, 1));
    expect(srgb(seq, NaN)).toEqual(srgb(seq, 0));
    expect(srgb(mapFor("div"), 0.5)).toEqual([247, 247, 247]);
    // 경계값 x.5 — 정점 [0] → [5], t = 0.1 → 0.5 → floor(1.0) = 1 (파이썬 round 는 0 — 쓰지 않는다), t = 0.3 → 1.5 → 2
    const m: ColorMap = { name: "t", kind: "seq", stops: [[0, 0, 0], [5, 5, 5]], check: "" };
    expect(srgb(m, 0.1)).toEqual([1, 1, 1]);
    expect(srgb(m, 0.3)).toEqual([2, 2, 2]);
    expect(srgb(m, 0.5)).toEqual([3, 3, 3]); // 2.5 → 3 (짝수 반올림이면 2)
  });
  it("39: kind div 인데 정점 짝수·center 없음 = 검사 실패(빌드 시험)", () => {
    const base = JSON.parse(JSON.stringify(CM));
    expect(() => validateColormaps(base)).not.toThrow();
    const even = JSON.parse(JSON.stringify(CM));
    even.maps.diverge.stops.pop();
    expect(() => validateColormaps(even)).toThrow(/홀수/);
    const noc = JSON.parse(JSON.stringify(CM));
    delete noc.maps.diverge.center;
    expect(() => validateColormaps(noc)).toThrow(/center/);
    const noRole = JSON.parse(JSON.stringify(CM));
    noRole.roles.seq = "nope";
    expect(() => validateColormaps(noRole)).toThrow();
    expect(() => validateColormaps({ schema: "x" })).toThrow();
  });
  it("37(TS): colormaps.json 을 가져오는 곳 = lib/colormap.ts 1개(시험·목 제외), 옛 정점 상수는 F1c 파일·deprecated 블록에만", () => {
    const src = path.resolve(__dirname, "..");
    const files: string[] = [];
    const walk = (d: string) => {
      for (const n of readdirSync(d)) {
        const p = path.join(d, n);
        if (statSync(p).isDirectory()) {
          if (n === "__tests__" || n === "mock" || n === "test") continue;
          walk(p);
        } else if (/\.(ts|tsx)$/.test(n)) files.push(p);
      }
    };
    walk(src);
    const rel = (p: string) => path.relative(src, p).replace(/\\/g, "/");
    const importers = files.filter((f) => /from\s+["'][^"']*colormaps\.json["']/.test(readFileSync(f, "utf8"))).map(rel);
    expect(importers).toEqual(["lib/colormap.ts"]);
    const legacy = files.filter((f) => /\b(VIRIDIS|DIVERGING|BLUES9|RDBU11)\b/.test(readFileSync(f, "utf8"))).map(rel).sort();
    // F1c 가 병합하면 이 목록은 ["lib/colormap.ts"](deprecated 블록)도 사라져 비게 된다 — 통합 시험이 0건을 확인
    const allowed = ["components/BeadSelectCard.tsx", "components/DispOverlay.tsx", "components/FieldOverlay.tsx", "lib/colormap.ts", "pages/library/common.tsx", "view3d/colors.ts"];
    for (const f of legacy) expect(allowed, f).toContain(f);
  });
});

describe("V-0251-22 legendModel", () => {
  const R = { min: 0, max: 100 };
  it("선형·로그 toT, 범위 밖 끝, 퇴화·NaN", () => {
    expect(toT(50, R)).toBe(0.5);
    expect(toT(-5, R)).toBe(0);
    expect(toT(500, R)).toBe(1);
    expect(Number.isNaN(toT(NaN, R))).toBe(true);
    expect(toT(1, { min: 3, max: 3 })).toBe(0);
    const L = { min: 1, max: 1000 };
    expect(toT(10, L, "log")).toBeCloseTo(1 / 3, 12);
    expect(toT(100, L, "log")).toBeCloseTo(2 / 3, 12);
    expect(toT(0, L, "log")).toBe(0);
    expect(toT(-1, L, "log")).toBe(0);
    for (const t of [0, 0.2, 0.5, 1]) expect(toT(fromT(t, L, "log"), L, "log")).toBeCloseTo(t, 12);
  });
  it("로그 최소 보정(최소 ≤ 0 → 최대/10^logDecades), 최대 ≤ 0 이면 선형", () => {
    expect(effectiveRange({ min: 0, max: 1000 }, "log", 3)).toEqual({ range: { min: 1, max: 1000 }, scale: "log" });
    expect(effectiveRange({ min: 0.5, max: 8 }, "log", 3)).toEqual({ range: { min: 0.5, max: 8 }, scale: "log" });
    expect(effectiveRange({ min: -2, max: 0 }, "log", 3).scale).toBe("linear");
    expect(effectiveRange({ min: 0, max: 8 }, "linear", 3)).toEqual({ range: { min: 0, max: 8 }, scale: "linear" });
  });
  it("부호 있는 모드(C 기여도·차이)·분류는 로그 불가, 변위·하중은 가능", () => {
    expect(logAllowed(COLOR_MODES.c, { min: -1, max: 2 })).toBe(false);
    expect(logAllowed(COLOR_MODES.dc, { min: -1, max: 1 })).toBe(false);
    expect(logAllowed(COLOR_MODES.disp, { min: 0, max: 2 })).toBe(true);
    expect(logAllowed(COLOR_MODES.load, { min: 0, max: 0 })).toBe(false);
    expect(logAllowed(COLOR_MODES.region, { min: 0, max: 1 })).toBe(false);
  });
  it("눈금(5개·경계 L+1개), 선형·로그 모두 색 위치 등간격", () => {
    expect(ticks(R, "linear", 5)).toEqual([0, 25, 50, 75, 100]);
    const t = ticks({ min: 1, max: 10000 }, "log", 5);
    expect(t.map((x) => +x.toPrecision(6))).toEqual([1, 10, 100, 1000, 10000]);
    expect(boundaries(R, "linear", 4)).toEqual([0, 25, 50, 75, 100]);
    expect(boundaries({ min: 1, max: 100 }, "log", 2).map((x) => +x.toPrecision(6))).toEqual([1, 10, 100]);
  });
  it("숫자 형식: 자동(유효 4자리) · 고정 · 지수 × 자릿수", () => {
    expect(formatValue(1234.5678, "auto", 3)).toBe("1235");
    expect(formatValue(0.00001234, "auto", 3)).toBe("0.00001234".replace("0.00001234", (0.00001234).toExponential(3)));
    expect(formatValue(1234.5678, "fixed", 0)).toBe("1235");
    expect(formatValue(1234.5678, "fixed", 3)).toBe("1234.568");
    expect(formatValue(1234.5678, "exp", 2)).toBe("1.23e+3");
    expect(formatValue(1234.5678, "exp", 0)).toBe("1e+3");
    expect(formatValue(NaN)).toBe("–");
    expect(formatValue(1.5, "fixed", 99)).toBe("1.500000"); // 자릿수 0~6 으로 자름
  });
  it("범위 밖: 개수·끝색/회색 색 위치(회색 = null 표지)", () => {
    expect(countOut([-1, 0, 50, 100, 101, NaN, Infinity], R)).toEqual({ above: 1, below: 1 });
    expect(colorPosition(150, R, "linear", 0, "clamp")).toBe(1);
    expect(colorPosition(150, R, "linear", 0, "gray")).toBeNull();
    expect(colorPosition(-1, R, "linear", 0, "gray")).toBeNull();
    expect(colorPosition(100, R, "linear", 0, "gray")).toBe(1);
    expect(colorPosition(50, R, "linear", 4, "clamp")).toBeCloseTo(2.5 / 4, 12); // 칸 중앙
    expect(Number.isNaN(colorPosition(NaN, R, "linear", 0, "clamp") as number)).toBe(true);
  });
  it("normalizeLegend: 레벨 2~20·자릿수 0~6 으로 자르고 틀린 필드는 기본값, 연속이면 levelsOf = 0", () => {
    expect(normalizeLegend({ levels: 99, digits: 99 })).toMatchObject({ levels: 20, digits: 6 });
    expect(normalizeLegend({ levels: 0, digits: -4 })).toMatchObject({ levels: 2, digits: 0 });
    expect(normalizeLegend({ levels: "x", out: "nope", reversed: 1 })).toEqual(LEGEND_DEFAULTS);
    expect(levelsOf({ levels: 9, continuous: true })).toBe(0);
    expect(levelsOf({ levels: 9, continuous: false })).toBe(9);
    expect(LEGEND_DEFAULTS).toEqual({ levels: 9, continuous: false, scale: "linear", format: "auto", digits: 3, out: "clamp", reversed: false, minMark: false, upin: true, logDecades: 3 });
  });
});

describe("V-0251-23 기억 v2", () => {
  beforeEach(() => localStorage.clear());
  it("v1 → v2: planKey 별 층만 옮기고 levels 는 버림, v1 키는 지우지 않음", () => {
    localStorage.setItem(VIEWER_KEY_V1, JSON.stringify({ case_load: { bc: false, load: true, ghost: true, marks: false, levels: 12 }, study_design: { bc: true, load: false, ghost: false, marks: true, levels: 6 } }));
    expect(readLayerPrefs("case_load")).toEqual({ bc: false, load: true, ghost: true, marks: false });
    expect(readLayerPrefs("study_design")).toEqual({ bc: true, load: false, ghost: false, marks: true });
    expect(readLegendPrefs()).toEqual(LEGEND_DEFAULTS); // levels 12 는 버림 → 새 기본 9
    expect(localStorage.getItem(VIEWER_KEY_V1)).not.toBeNull();
    expect(localStorage.getItem(VIEWER_KEY_V2)).toBeNull(); // 읽기만으로는 안 씀
  });
  it("깨진 JSON·저장소 오류 = 기본값, 범위·로그는 저장하지 않음", () => {
    localStorage.setItem(VIEWER_KEY_V2, "{broken");
    expect(readLegendPrefs()).toEqual(LEGEND_DEFAULTS);
    expect(readLayerPrefs("case_load")).toEqual({});
    localStorage.clear();
    writeLegendPrefs({ ...LEGEND_DEFAULTS, levels: 12, scale: "log", reversed: true, minMark: true, out: "gray" });
    const raw = JSON.parse(localStorage.getItem(VIEWER_KEY_V2)!);
    expect(raw.legend).toEqual({ levels: 12, continuous: false, format: "auto", digits: 3, out: "gray", reversed: true, minMark: true, upin: true });
    expect(JSON.stringify(raw)).not.toMatch(/scale|log|manMin|manMax|range/);
    expect(readLegendPrefs()).toMatchObject({ levels: 12, reversed: true, out: "gray", scale: "linear" }); // 로그는 다음에 선형으로 시작
    localStorage.setItem(VIEWER_KEY_V2, JSON.stringify({ legend: { levels: "x", digits: 9 } }));
    expect(readLegendPrefs()).toMatchObject({ levels: 9, digits: 6 });
  });
});

describe("V-0251-30 공용 확인(정적)", () => {
  const dir = path.resolve(__dirname, "../view3d");
  const walk = (d: string, out: string[] = []) => {
    for (const n of readdirSync(d)) {
      const p = path.join(d, n);
      if (statSync(p).isDirectory()) walk(p, out);
      else if (/\.(ts|tsx)$/.test(n)) out.push(p);
    }
    return out;
  };
  it("view3d/** 에 bluesSrgb·BLUES_GRADIENT·BLUES9·RDBU11·DIVERGING_GRADIENT 없음(F1c 용 재내보냄 1줄 제외), RGB 정점 리터럴 없음", () => {
    for (const f of walk(dir)) {
      if (/select\/(graph|layers)\.ts$/.test(f)) continue; // 세그먼트 12색·비드 단 색 = 연속값 색이 아님(계약 §0.5 예외 L11)
      const t = readFileSync(f, "utf8")
        .split("\n")
        .filter((l) => !(l.includes("DIVERGING_GRADIENT") && l.includes("@deprecated shim")) && !/export \{ DIVERGING_GRADIENT \} from/.test(l))
        .join("\n");
      expect(t, f).not.toMatch(/\b(bluesSrgb|BLUES_GRADIENT|BLUES9|RDBU11|DIVERGING_GRADIENT|LUT_LINEAR|LUT_DIV_LINEAR|VIRIDIS)\b/);
      expect(t, f).not.toMatch(/\[\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\]\s*,\s*\[\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\]/); // 정점 나열
    }
  });
  it("VIEWER_PLANS·COLOR_MODES 모든 열 채움, 하중 영역 행 region = 편집 불가", () => {
    for (const [k, p] of Object.entries(VIEWER_PLANS)) {
      for (const f of ["layers", "sync", "legendSync", "defaults"] as const) expect(p[f], `${k}.${f}`).toBeTruthy();
    }
    for (const [k, m] of Object.entries(COLOR_MODES)) {
      expect(["seq", "div", "region"], k).toContain(m.role);
      for (const f of ["signed", "logOk", "sym", "pairRange", "editable"] as const) expect(typeof m[f], `${k}.${f}`).toBe("boolean");
      expect(RES.roles[m.role], k).toBeTruthy();
    }
    expect(Object.keys(COLOR_MODES).sort()).toEqual(["c", "dc", "disp", "field", "load", "region"]);
    expect(COLOR_MODES.region).toMatchObject({ role: "region", editable: false });
    expect(COLOR_MODES.dc).toMatchObject({ role: "div", sym: true, pairRange: false });
    expect(COLOR_MODES.c.role).toBe("seq");
  });
});

describe("V-0251-40 비드 높이 변화(L8): + 깊어짐 = 빨강 쪽", () => {
  const mesh: PartMesh = { positions: new Float32Array(9), indices: new Uint32Array([0, 1, 2]) } as unknown as PartMesh;
  it("colorMap 값 = 역할 이름 div, c > 0 정점 = 빨강 쪽 · c < 0 = 파랑 쪽 · 0 = 흰", () => {
    const d = designViewData({ did: "d1", mesh, u: null, c: new Float32Array([1, -1, 0]), vmax: 1, scale: 1, markers: null, selectionBbox: () => null });
    expect(d.scene?.colorMap).toBe("div");
    const map = mapFor(d.scene!.colorMap!);
    const V = d.scene!.design!.vmax;
    const rgb = (c: number) => srgb(map, toT(c, { min: -V, max: V }));
    const red = rgb(1);
    const blue = rgb(-1);
    expect(red[0]).toBeGreaterThan(red[2]);
    expect(blue[2]).toBeGreaterThan(blue[0]);
    expect(rgb(0)).toEqual([247, 247, 247]);
  });
});

describe("V-0251-46(색표) 하중 영역 = blues(분류)", () => {
  it("region 역할 = blues, v0.25.0 과 같은 정점(옅음 → 진함)", () => {
    const m = mapFor("region");
    expect(m.name).toBe("blues");
    expect(srgb(m, 0)).toEqual([247, 251, 255]);
    expect(srgb(m, 1)).toEqual([8, 48, 107]);
    expect(m.stops.length).toBe(9);
  });
});
