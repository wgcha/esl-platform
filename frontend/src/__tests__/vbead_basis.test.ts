// V-0250-VB-8·31 (esl_virtual_bead.md §4.2·§19.9.1): 브라우저 basis.ts hinge = 코어 virtual_bead — 코어가 만든 기준 값(fixtures/vbead_hinge_core.json)과 대조.
// 입력 검사·요청 만들기·상태 연산(V-0250-VB-33 몫). 파이썬 에뮬레이터(tests/doe/test_vbead.py::_ts_morph)와 같은 식.
import { describe, expect, it } from "vitest";
import core from "./fixtures/vbead_hinge_core.json";
import { depthEff, heightChange, morph, parseBasis, ramp, termAt, writeBasis, type BasisVar } from "../view3d/select/basis";
import { addVBead, cloneState, emptyState, fromSelectionIn, removeVBead, resetAll, toSelectionAny } from "../view3d/select/layers";
import { buildVBead, emptyVbForm, fillFromPicks, formOf, nextVbId, previewVar, vbCfg, vbHeadText, vbProblem, vbRowText, vbStatus, vbOverlayLines, type VbForm, type VbFrame } from "../view3d/select/vbead";
import { defaultRows, rowProblem, vbRowTip, warpTag, VB_TEXT } from "../api/doe";
import { applyPatch } from "../view3d/select/layers";
import type { DoeParam, DoeSettingsOut, DoeVirtualBeadDerived, VirtualBeadIn } from "../api/types";

const hingeVar = (g: number[], c: number): BasisVar => ({
  name: "A1_A", bead: "a1", type: "A", nominal: 0, form: "hinge", c,
  idx: Uint32Array.from(g.map((_, i) => i)), vec: Float32Array.from(g.flatMap(() => [0, 0, 1])), g: Float32Array.from(g),
});

describe("basis.ts hinge = 코어 (V-0250-VB-8·31)", () => {
  it("depthEff = 코어 depth_eff ± 1e-12, F_c(e(D)) − F_c(0) = D, 3c/4 에서 C¹, c 0 이면 항등", () => {
    for (const k of core.cases)
      for (const [v, e] of k.depth_eff) {
        expect(Math.abs(depthEff(v, k.c) - e), `c ${k.c} v ${v}`).toBeLessThanOrEqual(1e-12);
        expect(Math.abs(ramp(depthEff(v, k.c), k.c) - ramp(0, k.c) - v)).toBeLessThanOrEqual(1e-9);
      }
    const c = 1.2426;
    const h = 1e-6;
    expect(Math.abs(depthEff(0.75 * c - h, c) - depthEff(0.75 * c + h, c))).toBeLessThan(1e-5);
    expect(Math.abs((depthEff(0.75 * c + 2 * h, c) - depthEff(0.75 * c + h, c)) / h - (depthEff(0.75 * c - h, c) - depthEff(0.75 * c - 2 * h, c)) / h)).toBeLessThan(1e-3);
    expect(depthEff(0, c)).toBe(0);
    expect(depthEff(3, 0)).toBe(3);
    expect(depthEff(-2, c)).toBe(-2);
  });
  it("termAt·morph = 코어 hinge(float32 g) — 5 칸 × 값 11개, 차 ≤ 1e-4 mm(작은 D 가지·선형 가지 모두)", () => {
    for (const k of core.cases) {
      const v = hingeVar(k.g, k.c);
      const n = k.g.length;
      expect(k.c === 0 || k.values.some((x) => x < 0.75 * k.c)).toBe(true);
      k.values.forEach((val, vi) => {
        const u = morph([v], { A1_A: val }, n);
        let worst = 0;
        for (let i = 0; i < n; i++) {
          worst = Math.max(worst, Math.abs(termAt(v, val, i) - k.expected[vi][i]), Math.abs(u[i * 3 + 2] - k.expected[vi][i]));
          expect(u[i * 3]).toBe(0);
          expect(u[i * 3 + 1]).toBe(0);
        }
        expect(worst, `h ${k.h} θ ${k.theta} r ${k.r} D ${val}`).toBeLessThanOrEqual(1e-4);
      });
    }
  });
  it("D = 0 → 변위 0 정확, 깊이면 노드(g = 0) 변위 = D(실제 깊이), 단조", () => {
    const k = core.cases[0];
    const v = hingeVar(k.g, k.c);
    const z0 = morph([v], { A1_A: 0 }, k.g.length);
    expect(Array.from(z0).every((x) => x === 0)).toBe(true);
    const top = k.g.findIndex((g) => g === 0);
    let prev = 0;
    for (const D of [0.2, 0.5, 1, 2, 4, 6]) {
      const z = morph([v], { A1_A: D }, k.g.length)[top * 3 + 2];
      expect(Math.abs(z - D)).toBeLessThanOrEqual(1e-5);
      expect(z).toBeGreaterThan(prev);
      prev = z;
    }
  });
  it("linear 변수는 옛 식 그대로((x − nominal)·vec), form 없음", () => {
    const lin: BasisVar = { name: "B1_D", bead: "b1", type: "D", nominal: 2, idx: Uint32Array.from([1, 2]), vec: Float32Array.from([0, 0, 1, 0, 0, -1]) };
    const u = morph([lin], { B1_D: 5 }, 3);
    expect(Array.from(u)).toEqual([0, 0, 0, 0, 0, 3, 0, 0, -3]);
    expect(termAt(lin, 5, 0)).toBe(3);
  });
  it("heightChange: A 변수도 vec 합 방향으로 색 값(깊어짐 +), 값 없으면 0", () => {
    const k = core.cases[1];
    const v = hingeVar(k.g, k.c);
    const c = heightChange([v], { A1_A: 3 }, k.g.length);
    const top = k.g.findIndex((g) => g === 0);
    expect(Math.abs(c[top] - 3)).toBeLessThanOrEqual(1e-5);
    expect(Math.max(...Array.from(heightChange([v], {}, k.g.length)))).toBe(0);
  });
  it("basis.bin 형식: hinge 변수 = vec 뒤 g 꼬리 — 왕복 같음, 꼬리 빠짐·남음·c 없음 = 오류", () => {
    const lin = { idx: [0, 1], vec: [0, 0, 1, 0, 0, 1] };
    const k = core.cases[0];
    const n = 5;
    const g = k.g.slice(0, n);
    const buf = writeBasis([lin, { idx: [3, 4, 5, 6, 7], vec: Array.from({ length: n * 3 }, (_, i) => (i % 3 === 2 ? 1 : 0)), g }]);
    const meta = { sha256: "x", selection_sha256: "y", n_nodes: 10, vars: [
      { name: "B1_D", type: "D" as const, bead: "b1", nominal: 1, n: 2, R_mm: null },
      { name: "A1_A", type: "A" as const, bead: "a1", nominal: 0, n, R_mm: null, form: "hinge" as const, c: k.c },
    ] };
    const out = parseBasis(buf, meta);
    expect(out[0].form).toBeUndefined();
    expect(out[1].form).toBe("hinge");
    expect(Array.from(out[1].g!)).toEqual(g.map((x) => Math.fround(x)));
    expect(out[1].c).toBe(k.c);
    expect(() => parseBasis(buf.slice(0, buf.byteLength - 4), meta)).toThrow(/짧/);
    expect(() => parseBasis(buf, { ...meta, vars: [meta.vars[0], { ...meta.vars[1], form: undefined }] })).toThrow(/길이/); // g 꼬리가 남음
    expect(() => parseBasis(buf, { ...meta, vars: [meta.vars[0], { ...meta.vars[1], c: undefined }] })).toThrow(/c 가 없/);
    expect(() => parseBasis(writeBasis([lin]), { ...meta, vars: [meta.vars[0], meta.vars[1]] })).toThrow(/짧/);
  });
});

const CFG = vbCfg({ virtual_bead: { enabled: true, max_count: 4, theta_default_deg: 45, theta_range_deg: [15, 60], d_max_limit_mm: 30, min_wall_elems: 2 } } as DoeSettingsOut);
const okForm = (): VbForm => ({ ...emptyVbForm(45), mode: "coord", xi: "10", eta: "20", length: "120", angle: "30", dMax: "5", wTop: "20" });
const FR: VbFrame = { o: [100, 50, 0], ex: [1, 0, 0], ey: [0, 1, 0], n: [0, 0, 1], dn: 0 };

describe("추가 비드 입력 검사·요청 만들기", () => {
  it("설정 기본: θ 15~60, 기본 45, 한도 30, 최대 4개(설정이 없으면 숨김 = enabled false)", () => {
    expect(CFG).toMatchObject({ enabled: true, thetaRange: [15, 60], thetaDefault: 45, dMaxLimit: 30, maxCount: 4 });
    expect(vbCfg(null).enabled).toBe(false);
    expect(vbCfg(null).thetaRange).toEqual([15, 60]);
  });
  it("검사: θ 15~60 경계, 길이 > 0, 각도 (−180, 180], 깊이 한도, 폭, r ≥ 0(비움 = 통과), 점 두 개, 개수", () => {
    const P = (f: Partial<VbForm>, picks: [number, number, number][] = [], n = 0) => vbProblem({ ...okForm(), ...f }, CFG, picks, n);
    expect(P({})).toBeNull();
    expect(P({ theta: "15" })).toBeNull();
    expect(P({ theta: "60" })).toBeNull();
    expect(P({ theta: "14.9" })).toMatch(/15~60/);
    expect(P({ theta: "61" })).toMatch(/15~60/);
    expect(P({ theta: "75" })).toMatch(/15~60/);
    expect(P({ length: "0" })).toMatch(/길이/);
    expect(P({ angle: "-180" })).toMatch(/각도/);
    expect(P({ angle: "180" })).toBeNull();
    expect(P({ angle: "181" })).toMatch(/각도/);
    expect(P({ dMax: "0" })).toMatch(/깊이/);
    expect(P({ dMax: "30.5" })).toMatch(/30/);
    expect(P({ wTop: "0" })).toMatch(/폭/);
    expect(P({ r: "" })).toBeNull();
    expect(P({ r: "0" })).toBeNull();
    expect(P({ r: "-1" })).toMatch(/r/);
    expect(P({ xi: "" })).toMatch(/ξ/);
    expect(P({}, [], 4)).toMatch(/4개/);
    expect(P({ mode: "pick" }, [[0, 0, 0]])).toMatch(/두 점/);
    expect(P({ mode: "pick" }, [[0, 0, 0], [0, 0, 0]])).toMatch(/같습니다/);
    expect(P({ mode: "pick" }, [[0, 0, 0], [5, 0, 0]])).toBeNull();
  });
  it("요청: (b) 좌표 = p0·length·angle_deg(frame 환산), (a) 두 점 = p0·p1, flip 은 true 만 키, r 은 준 값이면 0 도 키, side 키 없음", () => {
    const b = buildVBead(okForm(), [], FR, "a1")!;
    expect(b).toEqual({ id: "a1", p0: [110, 70, 0], length: 120, angle_deg: 30, w_top: 20, d_max: 5, theta_deg: 45 });
    expect("flip" in b).toBe(false);
    expect("r" in b).toBe(false);
    expect("side" in b).toBe(false);
    expect("end" in b).toBe(false);
    const f = buildVBead({ ...okForm(), flip: true, r: "0", end: "square" }, [], FR, "a2")!;
    expect(f).toMatchObject({ flip: true, r: 0, end: "square" });
    const a = buildVBead({ ...okForm(), mode: "pick", r: "2.5" }, [[1, 2, 3], [4, 6, 3]], null, "a3")!;
    expect(a.p1).toEqual([4, 6, 3]);
    expect(a.p0).toEqual([1, 2, 3]);
    expect("length" in a).toBe(false);
    expect(a.r).toBe(2.5);
    expect(buildVBead(okForm(), [], null, "a1")).toBeNull();
  });
  it("id: 빈 a1..a9 중 가장 작은 것 — 상한이면 null", () => {
    expect(nextVbId([], 4)).toBe("a1");
    expect(nextVbId([{ id: "a1" }, { id: "a3" }], 4)).toBe("a2");
    expect(nextVbId([{ id: "a1" }, { id: "a2" }, { id: "a3" }, { id: "a4" }], 4)).toBeNull();
  });
  it("행 클릭 복원: flip·r·단면·좌표가 입력 칸으로(두 점 항목은 길이·각도 환산), 찍은 점 → 칸 자동 채움", () => {
    const v: VirtualBeadIn = { id: "a1", p0: [110, 70, 0], p1: [110, 170, 0], w_top: 20, d_max: 5, theta_deg: 30, flip: true, r: 0, end: "square" };
    const f = formOf(v, FR, 45);
    expect(f).toMatchObject({ xi: "10", eta: "20", length: "100", angle: "90", dMax: "5", wTop: "20", theta: "30", flip: true, r: "0", end: "square" });
    expect(formOf({ id: "a2", p0: [0, 0, 0], w_top: 5, d_max: 2, length: 50, angle_deg: -10 }, FR, 45)).toMatchObject({ flip: false, r: "", theta: "45", length: "50", angle: "-10" });
    const g = fillFromPicks(emptyVbForm(45), [[110, 70, 0], [140, 110, 0]], FR);
    expect(g).toMatchObject({ xi: "10", eta: "20", length: "50", angle: "53.13" });
  });
  it("표시: 목록 행·묶음 머리 문구, 상태(OK | 첫 사유 + 툴팁 전부)", () => {
    const v: VirtualBeadIn = { id: "a1", p0: [0, 0, 0], p1: [120, 0, 0], w_top: 20, d_max: 5, theta_deg: 45 };
    expect(vbRowText(v, { len_mm: 120, angle_deg: 30 } as DoeVirtualBeadDerived)).toBe("A1 추가 비드 1 · L 120 mm · 30° · D≤5 W 20 θ45");
    expect(vbHeadText("a1", "추가 비드 1", { w_top: 20, theta_deg: 45, len_mm: 120 })).toBe("A1 추가 비드 1 · W 20 · θ 45° · L 120");
    const bad = { ok: false, reasons: [{ code: "VB_OVER_HOLE", text: "구멍과 겹침" }, { code: "VB_FIXED", text: "체결부와 겹침" }] } as DoeVirtualBeadDerived;
    expect(vbStatus(bad)).toEqual({ ok: false, text: "구멍과 겹침", tip: "구멍과 겹침\n체결부와 겹침" });
    expect(vbStatus({ ok: true } as DoeVirtualBeadDerived)?.text).toBe("OK");
    expect(vbStatus(null)).toBeNull();
  });
  it("미리보기: derive preview → BasisVar{hinge, g f32, c}, 길이 불일치·ok 아님 = null, 윤곽 → 3D 선분", () => {
    const d = { id: "a1", ok: true, p0: [0, 0, 0], p1_resolved: [10, 0, 0], outline_ab: [{ a: 0, b: 0 }, { a: 1, b: 0 }, { a: 1, b: 1 }], preview: { idx: [4, 7], vec: [[0, 0, -1], [0, 0, -1]], g: [0, 1.5], c: 1.24 } } as unknown as DoeVirtualBeadDerived;
    const v = previewVar(d)!;
    expect(v).toMatchObject({ name: "A1_A", type: "A", form: "hinge", nominal: 0, c: 1.24, bead: "a1" });
    expect(Array.from(v.idx)).toEqual([4, 7]);
    expect(Array.from(v.vec)).toEqual([0, 0, -1, 0, 0, -1]);
    expect(Array.from(v.g!)).toEqual([0, 1.5]);
    expect(previewVar({ ...d, preview: { ...d.preview!, g: [0] } } as DoeVirtualBeadDerived)).toBeNull();
    expect(previewVar({ ...d, ok: false } as DoeVirtualBeadDerived)).toBeNull();
    const l = vbOverlayLines(d, FR)!;
    expect(l.length).toBe((2 + 1) * 6); // 윤곽 꺾은선 3점 = 2 선분 + 중심선 1
    expect(Array.from(l.slice(0, 6))).toEqual([100, 50, 0, 101, 50, 0]);
  });
});

describe("선택 상태 virtual_beads (V-0250-VB-5·33)", () => {
  const A1: VirtualBeadIn = { id: "a1", p0: [1, 2, 3], p1: [4, 5, 3], w_top: 10, d_max: 4, theta_deg: 45 };
  const A2: VirtualBeadIn = { id: "a2", p0: [1, 2, 3], length: 50, angle_deg: 10, w_top: 10, d_max: 4, flip: true, r: 0 };
  const sel = (s: ReturnType<typeof emptyState>) => toSelectionAny(s, new Int32Array(0), new Uint8Array(0), 15);
  it("없음·빈 목록 = 키 없음(옛 문서·sha 불변), 있으면 id 순 + flip·r 그대로, 되돌릴 수 있음", () => {
    const s = emptyState(0, 2, { sha256: "g", rules: 1 });
    expect("virtual_beads" in sel(s)).toBe(false);
    const p2 = addVBead(s, A2)!;
    const p1 = addVBead(s, A1)!;
    expect(addVBead(s, A1)).toBeNull(); // 같은 id
    const out = sel(s);
    const vbs = (out as { virtual_beads?: VirtualBeadIn[] }).virtual_beads!;
    expect(vbs.map((x) => x.id)).toEqual(["a1", "a2"]);
    expect(vbs[1]).toMatchObject({ flip: true, r: 0, length: 50 });
    expect(JSON.stringify(out)).not.toContain('"side"');
    applyPatch(s, p1, "undo");
    expect(s.vbeads!.map((x) => x.id)).toEqual(["a2"]);
    applyPatch(s, p1, "redo");
    expect(s.vbeads!.length).toBe(2);
    void p2;
    const rm = removeVBead(s, "a1")!;
    expect(s.vbeads!.map((x) => x.id)).toEqual(["a2"]);
    expect(removeVBead(s, "a9")).toBeNull();
    applyPatch(s, rm, "undo");
    expect(s.vbeads!.length).toBe(2);
  });
  it("저장본 복원: fromSelectionIn 이 virtual_beads 를 읽고 cloneState·전체 초기화가 따라감", () => {
    const s = emptyState(0, 2, { sha256: "g", rules: 1 });
    addVBead(s, A2);
    const back = fromSelectionIn(sel(s), { q: new Map(), t: new Map() } as never, 0).state;
    expect(back.vbeads).toEqual([A2]);
    const c = cloneState(back);
    c.vbeads![0].d_max = 99;
    expect(back.vbeads![0].d_max).toBe(4);
    resetAll(back);
    expect(back.vbeads).toEqual([]);
    // schema 1 상태에는 키 없음
    expect(emptyState(0, 1).vbeads).toBeUndefined();
  });
});

describe("변수 행 규칙 (§0.3·§5.2)", () => {
  const A = (p: Partial<DoeParam> = {}): DoeParam => ({ name: "A1_A", type: "A", bead: "a1", form: "hinge", nominal: 0, feasible: [0, 5], feasible_source: "estimate", default_range: [0, 5], use_default: true, group_members: [], ...p } as DoeParam);
  it("A 하한 < 0 = 오류 문구, 0 = 통과(D·W 규칙 그대로)", () => {
    const r = (lo: string, hi: string) => ({ name: "A1_A", on: true, lo, hi });
    expect(rowProblem(A(), r("0", "5"))).toBeNull();
    expect(rowProblem(A(), r("-0.1", "5"))).toBe(VB_TEXT.rangeRule);
    expect(rowProblem(A(), r("3", "3"))).toBe("하한 < 상한이어야 합니다");
    expect(rowProblem({ type: "D" }, r("0", "5"))).toBe("깊이·폭 하한은 0보다 커야 합니다");
  });
  it("기본 켬: default_types [D, W] 그대로여도 hinge 형식 + use_default 면 포함", () => {
    const rows = defaultRows([A(), A({ name: "A2_A", use_default: false }), A({ name: "B1_D", type: "D", form: undefined })], ["D", "W"]);
    expect(rows.map((x) => x.on)).toEqual([true, false, true]);
    expect(rows[0]).toMatchObject({ lo: "0", hi: "5" });
    expect(defaultRows([{ ...A(), type: "U", form: undefined } as DoeParam], ["D", "W"])[0].on).toBe(false);
  });
  it("뒤틀림 꼬리표: n > 0 일 때만, 툴팁 = 서버 문구(없으면 수치) · 행 툴팁 = 사면 요소 수 + 예상 오차(표 밖 = 측정 범위 밖)", () => {
    const g = (n: number, text?: string) => ({ state: "ok" as const, from: [0, 5] as [number, number], usable: [0, 5] as [number, number], reason: null, value: null, combo_scale: null, warp: { limit_deg: 15, n, max_deg: 21.4, at: 5, ...(text ? { text } : {}) } });
    expect(warpTag(g(0))).toBeNull();
    expect(warpTag(null)).toBeNull();
    expect(warpTag({ ...g(0), warp: undefined })).toBeNull();
    expect(warpTag(g(7, "서버 문구"))).toEqual({ label: "뒤틀림 7", tip: "서버 문구" });
    expect(warpTag(g(2))!.tip).toMatch(/2 개/);
    expect(vbRowTip({ wall_elems: 3.33, acc_hint: { h: 3, d: 6, theta: 45, c_err_pct: -2.17, pi_err_pct: -1 } })).toBe("사면 요소 3.3개 · 예상 오차 ±2.2 %");
    expect(vbRowTip({ wall_elems: 3, acc_hint: null })).toBe("사면 요소 3.0개 · 예상 오차: 측정 범위 밖");
    expect(vbRowTip({ wall_elems: 3, acc_hint: null })).not.toMatch(/실제 깊이/);
  });
});
