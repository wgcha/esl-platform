// V-SR-12(esl_select_relax.md §11): 브라우저 섬 enclosedIslands — 코어 esl.mesh.features.enclosed_components 와 같은 위상 규칙(§5.2 1~3단계).
// (1) 합성 소형 격자(정답 손계산): 한 단에만 둘러싸인 성분 = 섬, 두 단·다른 층·제외에 닿으면 섬 아님, 가장 큰 성분은 섬 아님, 크기 상한 → tooLarge.
// (2) 목 메시(딤플 = LABEL.b1i) 기본 선택에서 섬 = 정답 요소 집합, 섬은 toSelectionIn 출력에 없음.
// (3) 22만 요소: 클릭 확장 + 섬 ≤ 150 ms. (4) 코어 픽스처 tests/fixtures/bead_select/features/*(make_fixture.py --features)가 있으면 코어 islands 와 같은 요소 집합.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildTopo } from "../view3d/select/adjacency";
import { enclosedComponents, grow, inPoly2, maskLoops, planeBasis } from "../view3d/select/grow";
import { elemColors, emptyState, enclosedIslands, fromSelectionIn, islandColor, ownerCode, paint, toSelectionIn } from "../view3d/select/layers";
import { elemIndex, fromElemSet } from "../view3d/select/ranges";
import { LABEL, selDefaultSelection, selDerive, selMesh } from "../mock/selectmock";
import { makeDoeSettings } from "../mock/doedata";
import { parseSelectBin } from "../view3d/select/view";
import { parseGlb } from "../view3d/glb";
import type { DoeSelectViewManifest, DoeSelectionIn } from "../api/types";

/** nx×ny 평면 4각 격자(간격 h). 요소 번호 e = j·nx + i */
function grid(nx: number, ny: number, h = 1) {
  const pos: number[] = [];
  for (let j = 0; j <= ny; j++) for (let i = 0; i <= nx; i++) pos.push(i * h, j * h, 0);
  const idx: number[] = [];
  const t2e: number[] = [];
  for (let j = 0; j < ny; j++)
    for (let i = 0; i < nx; i++) {
      const a = j * (nx + 1) + i;
      const q = [a, a + 1, a + nx + 2, a + nx + 1];
      idx.push(q[0], q[1], q[2], q[0], q[2], q[3]);
      t2e.push(j * nx + i, j * nx + i);
    }
  const X = Float64Array.from(pos);
  return { X, topo: buildTopo(X, Uint32Array.from(idx), Uint32Array.from(t2e), nx * ny), nx, ny };
}
const E = (nx: number, i: number, j: number) => j * nx + i;

describe("enclosedComponents(코어 §5.2 거울) — 합성 격자 정답", () => {
  // 12×12 격자: 단1 바닥 = 2..9 사각 고리(폭 2), 안쪽 4..7 중 (5,5)-(6,6) 2×2 = 섬 후보, 나머지 안쪽 = 단1 바닥
  const g = grid(12, 12);
  const n = g.nx * g.ny;
  const owner = new Int32Array(n).fill(-1);
  for (let j = 2; j <= 9; j++) for (let i = 2; i <= 9; i++) owner[E(12, i, j)] = 1;
  for (const [i, j] of [[5, 5], [6, 5], [5, 6], [6, 6]]) owner[E(12, i, j)] = -1;
  const cand = Uint8Array.from(owner, (o) => (o === -1 ? 1 : 0));
  const nz = () => [0, 0, 1] as [number, number, number];

  it("한 단에 둘러싸인 작은 성분 = 섬(둘레·내부 노드), 바깥 판(가장 큰 성분)은 섬 아님", () => {
    const r = enclosedComponents(g.topo, cand, owner, g.X, nz, { maxMm: 40 });
    expect(r.islands).toHaveLength(1);
    const il = r.islands[0];
    expect(il.owner).toBe(1);
    expect(il.elems).toEqual([E(12, 5, 5), E(12, 6, 5), E(12, 5, 6), E(12, 6, 6)]);
    expect(il.rim).toHaveLength(8); // 3×3 노드 중 가운데 1개만 내부
    expect(il.interior).toHaveLength(1);
    expect(il.sizeMm).toBeCloseTo(Math.SQRT2 * 2, 9);
    expect(r.tooLarge).toEqual([]);
  });

  it("크기 상한 넘으면 tooLarge(섬 아님)", () => {
    const r = enclosedComponents(g.topo, cand, owner, g.X, nz, { maxMm: 2 });
    expect(r.islands).toEqual([]);
    expect(r.tooLarge).toEqual([{ owner: 1, nElems: 4, sizeMm: Math.SQRT2 * 2 }]);
  });

  it("두 단에 닿음·막힘(다른 층·제외)에 닿음 → 섬 아님", () => {
    const o2 = owner.slice();
    o2[E(12, 4, 5)] = 2; // 섬 이웃 하나를 단2 로
    expect(enclosedComponents(g.topo, cand, o2, g.X, nz, { maxMm: 40 }).islands).toEqual([]);
    const o3 = owner.slice();
    o3[E(12, 7, 6)] = -2;
    expect(enclosedComponents(g.topo, cand, o3, g.X, nz, { maxMm: 40 }).islands).toEqual([]);
  });

  it("ringFrac(코어 ring_frac 거울, SR-D-26): 판 높이까지 솟은 둔덕 = 섬 아님(rings), 낮은 딤플 = 섬", () => {
    // 바닥(단1) 노드 z −10, 판 0. 후보 2×2 의 가운데 노드 높이: 0(판 높이 = 고리형 둔덕) | −8(딤플 높이 2 < 0.9·10)
    const make = (zc: number) => {
      const X = Float64Array.from(g.X);
      for (let e = 0; e < n; e++)
        if (e % 12 >= 2 && e % 12 <= 9 && Math.floor(e / 12) >= 2 && Math.floor(e / 12) <= 9) for (let k = g.topo.elemNodesPtr[e]; k < g.topo.elemNodesPtr[e + 1]; k++) X[g.topo.elemNodes[k] * 3 + 2] = -10;
      const mid = 6 * 13 + 6; // 노드 (6, 6)
      X[mid * 3 + 2] = zc;
      const idx: number[] = [];
      const t2e: number[] = [];
      for (let j = 0; j < 12; j++)
        for (let i = 0; i < 12; i++) {
          const a = j * 13 + i;
          idx.push(a, a + 1, a + 14, a, a + 14, a + 13);
          t2e.push(j * 12 + i, j * 12 + i);
        }
      return { X, topo: buildTopo(X, Uint32Array.from(idx), Uint32Array.from(t2e), n) };
    };
    const up = make(0);
    const r1 = enclosedComponents(up.topo, cand, owner, up.X, nz, { maxMm: 40, ringFrac: 0.9 });
    expect(r1.islands).toEqual([]);
    expect(r1.rings).toEqual([{ owner: 1, nElems: 4, sizeMm: Math.SQRT2 * 2 }]);
    expect(enclosedComponents(up.topo, cand, owner, up.X, nz, { maxMm: 40 }).islands).toHaveLength(1); // 규칙 끔 = v0.16.0
    const dn = make(-8);
    const r2 = enclosedComponents(dn.topo, cand, owner, dn.X, nz, { maxMm: 40, ringFrac: 0.9 });
    expect(r2.islands).toHaveLength(1);
    expect(r2.rings).toEqual([]);
  });

  it("가장 큰 성분이 둘러싸여도 섬 아님(동률 = 최소 요소 번호가 '가장 큼')", () => {
    // 판 전체를 바닥으로 덮고 두 성분(같은 크기 4)만 후보
    const o = new Int32Array(n).fill(1);
    for (const [i, j] of [[2, 2], [3, 2], [2, 3], [3, 3], [8, 8], [9, 8], [8, 9], [9, 9]]) o[E(12, i, j)] = -1;
    const c = Uint8Array.from(o, (v) => (v === -1 ? 1 : 0));
    const r = enclosedComponents(g.topo, c, o, g.X, nz, { maxMm: 40 });
    expect(r.islands.map((x) => x.elems[0])).toEqual([E(12, 8, 8)]);
  });

  it("outerPoly(d): 중심이 주인 바깥 고리 밖이면 tooLarge", () => {
    const poly = [0, 0, 3, 0, 3, 3, 0, 3]; // (5.5..6.5) 를 포함하지 않는 다각형
    const r = enclosedComponents(g.topo, cand, owner, g.X, nz, { maxMm: 40, outerPoly: () => poly });
    expect(r.islands).toEqual([]);
    expect(r.tooLarge[0].nElems).toBe(4);
  });

  it("경계 고리·평면 기저·짝홀", () => {
    const loops = maskLoops(g.topo, (e) => owner[e] === 1);
    expect(loops.filter((l) => l.closed).map((l) => l.nodes.length).sort((a, b) => a - b)).toEqual([8, 32]); // 섬 둘레 8 · 바깥 8×4
    const [u, v] = planeBasis([0, 0, -1]);
    expect(Math.abs(u[0] * v[0] + u[1] * v[1] + u[2] * v[2])).toBeLessThan(1e-12);
    expect(inPoly2(1, 1, [0, 0, 2, 0, 2, 2, 0, 2])).toBe(true);
    expect(inPoly2(3, 1, [0, 0, 2, 0, 2, 2, 0, 2])).toBe(false);
  });
});

describe("enclosedIslands(화면 선택) — 목 메시 딤플", () => {
  const m = selMesh();
  const idx = elemIndex(m.elemId, m.elemType);
  const truth = [...m.label.keys()].filter((e) => m.label[e] === LABEL.b1i);

  it("기본 선택: 섬 = b1 단2 딤플 정답 요소, 서버 흉내 derive 의 islands 와 같음", () => {
    const { state } = fromSelectionIn(selDefaultSelection(), idx, m.elemId.length);
    const r = enclosedIslands(m.topo, state, m.x, 40);
    expect(truth.length).toBe(12);
    expect(r.islands).toHaveLength(1);
    expect(r.islands[0].owner).toBe(ownerCode(0, 2));
    expect(r.islands[0].elems).toEqual(truth);
    const d = selDerive(selDefaultSelection(), makeDoeSettings()).out;
    expect(d.algo).toBe(2);
    expect(d.beads[0].islands?.map((x) => x.k)).toEqual([2]);
    expect(fromElemSet(d.beads[0].islands![0].elems, idx).elems).toEqual(truth);
    expect(fromElemSet(d.islands_suggested!.b1, idx).elems).toEqual(truth);
    // 섬은 사면 제안에 없음(§4.2)
    const sug = new Set(fromElemSet(d.slope_suggested!.b1, idx).elems);
    expect(truth.some((e) => sug.has(e))).toBe(false);
    // 제외 층으로 칠하면 섬 아님(SR-D-15)
    paint(state, truth.slice(0, 1), { kind: "exclude" }, "add");
    expect(enclosedIslands(m.topo, state, m.x, 40).islands).toHaveLength(0);
  });

  it("클릭 확장 뒤 섬 즉시 표시(밝은 단 색), 섬은 toSelectionIn 출력에 없음", () => {
    const s = emptyState(m.elemId.length);
    s.beads.push({ id: "b1", name: "B1", nTiers: 1, blend: "auto", floorFollow: 1, links: [], holdFixed: 0 });
    const b1t2 = [...m.label.keys()].filter((e) => m.label[e] === LABEL.b1t2);
    const got = grow(m.topo, b1t2[Math.floor(b1t2.length / 2)], 15);
    expect(got.some((e) => truth.includes(e))).toBe(false); // 딤플 벽은 확장에서 빠짐 = 빈 구멍(C13)
    paint(s, got, { kind: "tier", bead: 0, k: 1 }, "add");
    const r = enclosedIslands(m.topo, s, m.x, 40);
    expect(r.islands.flatMap((x) => x.elems)).toEqual(truth);
    const col = elemColors(s, 0, () => null, r.owner);
    const c = islandColor(1);
    expect([col[truth[0] * 4], col[truth[0] * 4 + 1], col[truth[0] * 4 + 2]]).toEqual(c.map(Math.round));
    const sel = toSelectionIn(s, m.elemId, m.elemType, 15);
    const inSel = new Set(fromElemSet(sel.beads[0].tiers[0].floor, idx).elems);
    expect(truth.some((e) => inSel.has(e))).toBe(false);
    expect(JSON.stringify(sel)).not.toMatch(/island/);
  });

  it("hold_fixed: 1 일 때만 키, 왕복", () => {
    const s = emptyState(m.elemId.length);
    s.beads.push({ id: "b1", name: "B1", nTiers: 1, blend: "auto", floorFollow: 1, links: [], holdFixed: 0 });
    expect("hold_fixed" in toSelectionIn(s, m.elemId, m.elemType, 15).beads[0]).toBe(false);
    s.beads[0].holdFixed = 1;
    const sel = toSelectionIn(s, m.elemId, m.elemType, 15);
    expect(sel.beads[0].hold_fixed).toBe(1);
    expect(fromSelectionIn(sel, idx, m.elemId.length).state.beads[0].holdFixed).toBe(1);
  });
});

describe("성능: 22만 요소 클릭 확장 + 섬 ≤ 150 ms", () => {
  it("470×470 격자(220,900 요소), 바닥 영역 안 딤플 1개", () => {
    const N = 470;
    const g = grid(N, N, 3);
    const s = emptyState(N * N);
    s.beads.push({ id: "b1", name: "B1", nTiers: 1, blend: "auto", floorFollow: 1, links: [], holdFixed: 0 });
    // 바닥 = 100..300 정사각 영역, 그 안 (200,200) 2×2 를 기울여 섬으로(법선 변경 → 확장에서 빠짐)
    const tilt = new Set([E(N, 200, 200), E(N, 201, 200), E(N, 200, 201), E(N, 201, 201)]);
    for (const e of tilt) g.topo.normals[e * 3 + 2] = 0.5, g.topo.normals[e * 3] = Math.sqrt(0.75);
    // 바닥 밖은 법선을 바꿔 확장이 바닥에서 멈추게
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) if (i < 100 || i >= 300 || j < 100 || j >= 300) g.topo.normals[E(N, i, j) * 3 + 1] = 1, g.topo.normals[E(N, i, j) * 3 + 2] = 0;
    let best = Infinity;
    let r = null as ReturnType<typeof enclosedIslands> | null;
    for (let k = 0; k < 3; k++) {
      s.owner.fill(-1);
      const t0 = performance.now();
      const got = grow(g.topo, E(N, 150, 150), 15);
      paint(s, got, { kind: "tier", bead: 0, k: 1 }, "add");
      r = enclosedIslands(g.topo, s, g.X, 40);
      best = Math.min(best, performance.now() - t0);
    }
    expect(r!.islands.map((x) => x.elems)).toEqual([[...tilt].sort((a, b) => a - b)]);
    expect(best).toBeLessThanOrEqual(150);
  }, 60_000);
});

// ---- 코어 픽스처(R1 make_fixture.py --features 산출 후 자동 연결)
// 가정 형식: features/{select_manifest.json, select.bin, part.glb, selection.json(SelectionIn), expected.json{islands: {<bead>: [요소 번호…]}, island_max_mm?}}
const FDIR = path.resolve(__dirname, "../../../tests/fixtures/bead_select/features");
const hasFixture = ["select_manifest.json", "select.bin", "part.glb", "selection.json", "expected.json"].every((f) => existsSync(path.join(FDIR, f)));
describe.skipIf(!hasFixture)("V-SR-12 코어 픽스처 동일성(features)", () => {
  it("enclosedIslands = 코어 islands(비드별 요소 집합)", () => {
    const buf = (f: string) => {
      const b = readFileSync(path.join(FDIR, f));
      const out = new ArrayBuffer(b.byteLength);
      new Uint8Array(out).set(b);
      return out;
    };
    const js = <T,>(f: string) => JSON.parse(readFileSync(path.join(FDIR, f), "utf8")) as T;
    const mf = js<DoeSelectViewManifest>("select_manifest.json");
    const bin = parseSelectBin(buf("select.bin"), mf);
    const glb = parseGlb(buf("part.glb"));
    const topo = buildTopo(glb.positions, glb.indices, bin.tri2elem, mf.n_elems);
    const exp = js<{ islands: Record<string, number[]>; island_max_mm?: number }>("expected.json");
    const sel = js<DoeSelectionIn>("selection.json");
    const { state } = fromSelectionIn(sel, elemIndex(bin.elemId, bin.elemType), mf.n_elems);
    const r = enclosedIslands(topo, state, glb.positions, exp.island_max_mm ?? 40);
    for (const [bead, elems] of Object.entries(exp.islands)) {
      const bi = state.beads.findIndex((b) => b.id === bead);
      const got = r.islands.filter((x) => Math.floor(x.owner / 16) === bi).flatMap((x) => x.elems).sort((a, b) => a - b);
      expect(got).toEqual([...elems].sort((a, b) => a - b));
    }
  });
});
