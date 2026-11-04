// V-BS-12(esl_bead_select.md §16): 브라우저 순수 모듈 select/* — 인접·seed 확장(θ 경계 14.9/15.1°)·정답 바닥, 구간 압축(서버 정규화와 같은 JSON),
// 기저 합 u(float32 ≤ 1e-4 mm), 실행 취소, 층 규칙, 올가미·ID 버퍼 판정, select.bin 왕복.
// 픽스처: 목 합성 메시(mock/selectmock.ts — 정답 표지 포함). 워커 산출 픽스처(tests/fixtures/bead_select/small/*)와의 대조는 S1 코어 병합 후 추가.
import { describe, expect, it } from "vitest";
import { boundaryEdges, boundaryNodes, buildTopo, neighbors, ringStep } from "../view3d/select/adjacency";
import { grow, normalAngleDeg } from "../view3d/select/grow";
import { centroidsInMask, idToRgb, idsInMask, inCircle, pointInPolygon, polyBounds, rectOf, rgbToId } from "../view3d/select/lasso";
import { compress, elemIndex, elemSetCount, expand, fromElemSet, normalizeRanges, toElemSet } from "../view3d/select/ranges";
import { History, HISTORY_MAX } from "../view3d/select/history";
import { type LayerName, addBead, addTier, applyPatch, counts, effectiveSlope, elemColors, emptyState, fromSelectionIn, inBead, ownerBead, paint, toSelectionIn, toggleLink } from "../view3d/select/layers";
import { heightChange, maxAbs, morph, parseBasis, writeBasis } from "../view3d/select/basis";
import { fixedElems, parseSelectBin, writeSelectBin } from "../view3d/select/view";
import { LABEL, selBasis, selDefaultSelection, selDerive, selManifest, selMesh, selNormalize, selSha, selValidate } from "../mock/selectmock";
import { makeDoeSettings } from "../mock/doedata";
import { parseGlb } from "../view3d/glb";

/** 접힌 띠: 4각 2개(e0 평면, e1 = 공유 모서리에서 alpha° 꺾임) */
function folded(alpha: number) {
  const a = (alpha * Math.PI) / 180;
  const pos = [0, 0, 0, 10, 0, 0, 10, 10, 0, 0, 10, 0, 10 + 10 * Math.cos(a), 0, 10 * Math.sin(a), 10 + 10 * Math.cos(a), 10, 10 * Math.sin(a)];
  // e0 = 0,1,2,3 · e1 = 1,4,5,2
  const idx = [0, 1, 2, 0, 2, 3, 1, 4, 5, 1, 5, 2];
  return buildTopo(Float32Array.from(pos), Uint32Array.from(idx), Uint32Array.from([0, 0, 1, 1]), 2);
}

describe("adjacency·grow", () => {
  it("4각 대각선은 모서리가 아님, 공유 모서리 이웃, 법선·면적", () => {
    const t = folded(0);
    expect(t.edges.length / 2).toBe(7); // 4 + 4 − 공유 1
    expect([...neighbors(t, 0)]).toEqual([1]);
    expect(t.areas[0]).toBeCloseTo(100, 4);
    expect([...t.normals.subarray(0, 3)].map((v) => Math.round(v))).toEqual([0, 0, 1]);
    expect(t.elemNodesPtr[1] - t.elemNodesPtr[0]).toBe(4);
  });

  it("θ 경계: 14.9° 꺾임은 확장, 15.1° 는 멈춤(seed 법선 기준)", () => {
    expect(normalAngleDeg(folded(14.9), 0, 1)).toBeCloseTo(14.9, 3);
    expect(grow(folded(14.9), 0, 15)).toEqual([0, 1]);
    expect(grow(folded(15.1), 0, 15)).toEqual([0]);
    expect(grow(folded(14.9), 0, 15, (e) => e === 1)).toEqual([0]);
    expect(grow(folded(0), 0, 15, (e) => e === 0)).toEqual([]);
  });

  it("합성 메시: 바닥 한 요소 클릭 + 15° 확장 ⊇ 정답 바닥, 더한 것은 바닥 가장자리 걸친 요소뿐(상판·다른 단·다른 비드 없음)", () => {
    // 목 메시는 바닥 가장자리가 격자와 맞지 않아 걸친 요소(기울기 < 15°)가 생긴다 — 워커 픽스처(격자 정렬)에서는 같음으로 대조(S1 후)
    const m = selMesh();
    for (const lab of [LABEL.b1t1, LABEL.b1t2, LABEL.b2]) {
      const truth = [...m.label.keys()].filter((e) => m.label[e] === lab);
      const seed = truth[Math.floor(truth.length / 2)];
      const got = grow(m.topo, seed, 15);
      const set = new Set(got);
      expect(truth.every((e) => set.has(e))).toBe(true);
      const D = -m.x[m.quads[seed][0] * 3 + 2];
      for (const e of got) {
        if (m.label[e] === lab) continue;
        expect(m.label[e]).toBe(LABEL.slope);
        expect(m.quads[e].some((v) => Math.abs(-m.x[v * 3 + 2] - D) < 1e-6)).toBe(true);
        expect(normalAngleDeg(m.topo, seed, e)).toBeLessThanOrEqual(15);
      }
      expect(got.length).toBeLessThan(truth.length * 1.5);
    }
  });

  it("경계 모서리·노드, ±1줄(바깥 요소 추가 / 안쪽 요소 제거)", () => {
    const m = selMesh();
    const floor = new Set([...m.label.keys()].filter((e) => m.label[e] === LABEL.b2));
    const inSet = (e: number) => floor.has(e);
    const bn = boundaryNodes(m.topo, inSet);
    const be = boundaryEdges(m.topo, inSet);
    expect(be.length / 2).toBeGreaterThan(8);
    for (let i = 0; i < be.length; i++) expect(bn[be[i]]).toBe(1);
    const plus = ringStep(m.topo, inSet, 1, () => true);
    expect(plus.every((e) => !floor.has(e))).toBe(true);
    const minus = ringStep(m.topo, inSet, -1, () => true);
    expect(minus.every((e) => floor.has(e))).toBe(true);
    expect(minus.length).toBeLessThan(floor.size);
  });
});

describe("ranges(서버 정규화와 같은 규칙)", () => {
  it("정렬·중복 제거·인접 병합·닫힌 구간", () => {
    expect(compress([5, 3, 4, 9, 10, 12, 3])).toEqual([[3, 5], [9, 10], [12, 12]]);
    expect(normalizeRanges([[9, 10], [3, 5], [6, 6], [11, 11], [20, 18]])).toEqual([[3, 6], [9, 11], [18, 20]]);
    expect(expand([[3, 5], [9, 9]])).toEqual([3, 4, 5, 9]);
    expect(compress([])).toEqual([]);
  });

  it("요소 번호 ↔ ElemSet(4각·3각 ID 공간 분리), 없는 ID 수", () => {
    const id = [101, 102, 103, 7, 8];
    const ty = [4, 4, 4, 3, 3];
    const s = toElemSet([0, 2, 1, 4], id, ty);
    expect(s).toEqual({ q: [[101, 103]], t: [[8, 8]] });
    expect(elemSetCount(s)).toBe(4);
    const idx = elemIndex(id, ty);
    expect(fromElemSet({ q: [[101, 102], [500, 501]], t: [[7, 8]] }, idx)).toEqual({ elems: [0, 1, 3, 4], unknown: 2 });
  });

  it("화면 → SelectionIn 이 서버 정규화(selNormalize) 결과와 같은 JSON, 같은 선택 = 같은 sha", () => {
    const m = selMesh();
    const sel = selDefaultSelection();
    const { state } = fromSelectionIn(sel, elemIndex(m.elemId, m.elemType), m.elemId.length);
    const back = toSelectionIn(state, m.elemId, m.elemType, 15);
    expect(JSON.stringify(back)).toBe(JSON.stringify(selNormalize(back)));
    expect(JSON.stringify(back)).toBe(JSON.stringify(selNormalize(sel)));
    // 구간 표기(쪼갠 구간)·순서를 바꿔도 sha 같음(V-BS-8)
    const split = structuredClone(sel);
    const r = split.beads[0].tiers[0].floor.q;
    const [a, b] = r[0];
    if (b > a) split.beads[0].tiers[0].floor.q = [[a + 1, b], [a, a], ...r.slice(1)];
    expect(selSha(split)).toBe(selSha(sel));
  });
});

describe("layers·history", () => {
  it("한 요소 한 비드 층, 사면 빼기 = 자동 사면 remove, 실행 취소·다시", () => {
    const s = emptyState(10);
    const h = new History<LayerName>();
    expect(addBead(s)).toBe(0);
    expect(addBead(s)).toBe(1);
    expect(s.beads.map((b) => [b.id, b.name])).toEqual([["b1", "B1"], ["b2", "B2"]]);
    expect(addTier(s, 0, 2)).toBe(2);
    expect(addTier(s, 0, 2)).toBeNull();
    h.push(paint(s, [0, 1, 2], { kind: "tier", bead: 0, k: 1 }, "add"));
    h.push(paint(s, [2, 3], { kind: "tier", bead: 1, k: 1 }, "add")); // 2 는 b1 것 — 그대로
    expect(ownerBead(s.owner[2])).toBe(0);
    expect(ownerBead(s.owner[3])).toBe(1);
    const sug = new Uint8Array(10);
    sug[5] = 1;
    sug[6] = 1;
    h.push(paint(s, [5], { kind: "slope", bead: 0 }, "remove", (b) => (b === 0 ? sug : null)));
    expect(s.remove[5]).toBe(0);
    expect([...effectiveSlope(s, 0, sug)].map((v, i) => (v ? i : -1)).filter((i) => i >= 0)).toEqual([6]);
    h.push(paint(s, [5], { kind: "slope", bead: 0 }, "add"));
    expect(s.remove[5]).toBe(-1);
    expect(counts(s, 0)).toEqual({ tiers: [3, 0], slopeAdd: 1, slopeRemove: 0 });
    h.push(paint(s, [9], { kind: "fixed" }, "add"));
    expect(s.fixed[9]).toBe(1);
    // 실행 취소 3번 → slope add·remove·fixed 되돌림
    for (let i = 0; i < 3; i++) applyPatch(s, h.undo()!, "undo");
    expect(s.fixed[9]).toBe(0);
    expect(s.owner[5]).toBe(-1);
    expect(s.remove[5]).toBe(-1);
    applyPatch(s, h.redo()!, "redo");
    expect(s.remove[5]).toBe(0);
    expect(inBead(s, 0)(1)).toBe(true);
  });

  it("History 상한 50·빈 패치 무시·새 패치는 다시 실행 목록을 비움", () => {
    const h = new History();
    const p = () => ({ changes: [{ layer: "owner", idx: Uint32Array.of(0), before: Int32Array.of(-1), after: Int32Array.of(1) }] });
    for (let i = 0; i < 60; i++) h.push(p());
    expect(h.size).toBe(HISTORY_MAX);
    h.push({ changes: [] });
    expect(h.size).toBe(HISTORY_MAX);
    h.undo();
    expect(h.canRedo).toBe(true);
    h.push(p());
    expect(h.canRedo).toBe(false);
  });

  it("단 묶기·풀기(겹침 없음), 요소 색(단 파랑·사면 주황·고정 진회색·다른 비드 흐림)", () => {
    const s = emptyState(4);
    addBead(s);
    addTier(s, 0, 6);
    addTier(s, 0, 6);
    const b = s.beads[0];
    toggleLink(b, 1, 2);
    expect(b.links).toEqual([[1, 2]]);
    toggleLink(b, 3, 2);
    expect(b.links).toEqual([[1, 2, 3]]);
    toggleLink(b, 2, 1);
    expect(b.links).toEqual([[1, 3]]);
    addBead(s);
    paint(s, [0], { kind: "tier", bead: 0, k: 1 }, "add");
    paint(s, [1], { kind: "slope", bead: 0 }, "add");
    paint(s, [2], { kind: "tier", bead: 1, k: 1 }, "add");
    paint(s, [3], { kind: "fixed" }, "add");
    const c = elemColors(s, 0, () => null);
    const rgb = (e: number) => [...c.subarray(e * 4, e * 4 + 3)];
    expect(rgb(0)[2]).toBeGreaterThan(rgb(0)[0]); // 파랑
    expect(rgb(1)[0]).toBeGreaterThan(rgb(1)[2]); // 주황
    expect(rgb(3)).toEqual([84, 90, 100]);
    expect(Math.abs(rgb(2)[0] - rgb(2)[2])).toBeLessThan(Math.abs(rgb(0)[0] - rgb(0)[2])); // 흐림
  });
});

describe("lasso·ID 버퍼", () => {
  it("점-다각형·사각·원·ID 색 왕복", () => {
    const sq: [number, number][] = [[0, 0], [10, 0], [10, 10], [0, 10]];
    expect(pointInPolygon(5, 5, sq)).toBe(true);
    expect(pointInPolygon(15, 5, sq)).toBe(false);
    expect(rectOf([10, 2], [3, 8])).toEqual({ x: 3, y: 2, w: 7, h: 6 });
    expect(polyBounds([[1.2, 3.7], [5.5, 2.1]])).toEqual({ x: 1, y: 2, w: 6, h: 3 });
    expect(inCircle(3, 4, 0, 0, 5)).toBe(true);
    for (const e of [0, 255, 65535, 16777214]) expect(rgbToId(...idToRgb(e)) - 1).toBe(e);
  });
  it("보이는 면만 = ID 버퍼 픽셀, 관통 = 중심 투영", () => {
    const ids = new Uint32Array([0, 1, 1, 0, 3, 3, 0, 0, 5]);
    expect(idsInMask({ rect: { x: 10, y: 10, w: 3, h: 3 }, ids }, () => true)).toEqual([0, 2, 4]);
    expect(idsInMask({ rect: { x: 0, y: 0, w: 3, h: 3 }, ids }, (x) => x > 1 && x < 2)).toEqual([0, 2]);
    const px = Float32Array.from([1, 1, NaN, NaN, 50, 50, 5, 5]);
    expect(centroidsInMask(px, (x, y) => x < 10 && y < 10)).toEqual([0, 3]);
  });
});

describe("기저 합·select.bin", () => {
  it("u = Σ (v − v_nom)·B_v — float32 파일에서 float64 기준과 ≤ 1e-4 mm, 공칭 = 0, 선형(합 = 개별 합)", () => {
    const m = selMesh();
    const st = makeDoeSettings();
    const { meta, bin, params } = selBasis(selDefaultSelection(), st);
    const vars = parseBasis(bin, meta);
    expect(vars.map((v) => v.name)).toEqual(params.map((p) => p.name));
    const vals = Object.fromEntries(params.map((p, i) => [p.name, p.nominal + (i % 2 ? -1.7 : 2.3)]));
    const u = morph(vars, vals, m.n);
    // float64 기준: 같은 식을 float64 로
    const ref = new Float64Array(m.n * 3);
    for (const v of vars) for (let i = 0; i < v.idx.length; i++) for (let c = 0; c < 3; c++) ref[v.idx[i] * 3 + c] += (vals[v.name] - v.nominal) * v.vec[i * 3 + c];
    let err = 0;
    for (let i = 0; i < u.length; i++) err = Math.max(err, Math.abs(u[i] - ref[i]));
    expect(err).toBeLessThanOrEqual(1e-4);
    expect(maxAbs(morph(vars, Object.fromEntries(params.map((p) => [p.name, p.nominal])), m.n))).toBe(0);
    const only = (name: string) => morph(vars, { [name]: vals[name] }, m.n);
    const sum = new Float64Array(m.n * 3);
    for (const p of params) {
      const o = only(p.name);
      for (let i = 0; i < o.length; i++) sum[i] += o[i];
    }
    let lin = 0;
    for (let i = 0; i < u.length; i++) lin = Math.max(lin, Math.abs(u[i] - sum[i]));
    expect(lin).toBeLessThanOrEqual(1e-4);
    // 색 = 비드 방향 성분: D 를 깊게(+) 하면 양수
    const c = heightChange(vars, { B1_D1: params.find((p) => p.name === "B1_D1")!.nominal + 3 }, m.n);
    expect(maxAbs(c)).toBeCloseTo(3, 4);
    expect(Math.min(...c)).toBeGreaterThanOrEqual(-1e-6);
    expect(() => parseBasis(bin.slice(0, bin.byteLength - 4), meta)).toThrow(/짧|길이/);
    expect(writeBasis(vars).byteLength).toBe(bin.byteLength);
  });

  it("select.bin 왕복·길이 검사, GLB 정점 수 = manifest, 고정 요소", () => {
    const m = selMesh();
    const mf = selManifest();
    const b = parseSelectBin(m.bin, mf);
    expect(b.tri2elem.length).toBe(mf.n_tris);
    expect(b.elemId[0]).toBe(m.elemId[0]);
    expect(b.fixed.reduce((s, v) => s + v, 0)).toBe(mf.fixed.scan_n);
    expect(() => parseSelectBin(m.bin.slice(1), mf)).toThrow(/길이/);
    const w = writeSelectBin(b);
    expect(w.buf.byteLength).toBe(m.bin.byteLength);
    expect(w.bin).toEqual(mf.bin);
    for (const L of mf.bin.layout) expect(L.offset % 4).toBe(0);
    expect(parseGlb(m.glb).positions.length / 3).toBe(mf.n_nodes);
    const fe = fixedElems(b.fixed, m.topo.elemNodesPtr, m.topo.elemNodes);
    expect(fe.reduce((s, v) => s + v, 0)).toBeGreaterThan(0);
  });
});

describe("목 derive·검증(화면 개발용 서버 흉내)", () => {
  it("바닥만 넣으면 사면 자동 제안, 단2 빼면 SELECT_TIER_MISSING, 고정 18 mm → 블렌딩 자르기", () => {
    const st = makeDoeSettings();
    const sel = selDefaultSelection();
    const { out } = selDerive(sel, st);
    expect(out.beads[0].tiers.map((t) => t.D_nom)).toEqual([22, 14]);
    expect(out.beads[0].slope.suggested_n).toBeGreaterThan(50);
    expect(out.beads[0].blend_clipped).toBe(true);
    expect(out.beads[0].warnings.map((w) => w.code)).toContain("SELECT_BLEND_CLIPPED");
    const one = structuredClone(sel);
    one.beads[0].tiers = one.beads[0].tiers.slice(0, 1);
    expect(selDerive(one, st).out.beads[0].warnings.map((w) => w.code)).toContain("SELECT_TIER_MISSING");
    // 검증: 겹침·빈 단·이름
    const ov = structuredClone(sel);
    ov.beads[1].tiers[0].floor = ov.beads[0].tiers[0].floor;
    expect((selValidate(ov, st)?.body as { detail: { code: string } }).detail.code).toBe("SELECT_OVERLAP");
    const nm = structuredClone(sel);
    nm.beads[0].name = "a\u0001";
    expect((selValidate(nm, st)?.body as { detail: { code: string } }).detail.code).toBe("SELECT_NAME_INVALID");
    expect(selValidate(sel, st)).toBeNull();
  });
});
