// V-L3-10 · V-L3-6(프런트) · V-L3-5(프런트) · V-L3-13 · V-L3-14: 3D 하중 보기 순수 함수 시험(jsdom, three 없이).
import { describe, expect, it } from "vitest";
import {
  ARROW_COLOR, CLUSTER_COLOR, CLUSTER_STAGES, MIN_LEN_FRAC, NODE_STAGES, N_STAGES, arrowLength, buildArrowSpecs, nearestEnabledStage, nodeCount, stageEnabled, stageIndex, stageMode, stageText,
} from "../view3d/arrows";
import { BLUES9, LUT_LINEAR, LUT_SRGB, NAN_LINEAR, bluesSrgb, fillVertexColors, luminance, normalize, srgbToLinear } from "../view3d/colors";
import { applyDeform, defaultScale, defaultScaleExp, pointAt, scaleFromExp, scaleLabel } from "../view3d/deform";
import { parseGlb } from "../view3d/glb";
import { fileUrls, resolveFileUrl } from "../view3d/fetchFiles";
import { infoLine } from "../view3d/info";
import { nearestVertex, pickSegment, raySegmentDistance } from "../view3d/pick";
import { clusterRowSelected, nodeRowSelected, reconcile, sceneSelection, selectionFromPick, visibleKeys } from "../view3d/selection";
import { buildSupportSpecs, supportSymbol } from "../view3d/supports";
import { colorField, decodeValues, fmtQuant } from "../view3d/values";
import { makeMesh, mockView3d, nodeNormalsAndAreas, weightedClusters } from "../mock/view3dmock";

const man = () => mockView3d().manifest("esl-run-1");

describe("V-L3-10 단계 ↔ 모드·개수", () => {
  it("[100,50,20,10] 노드 → 군집 [5,4,3,2], 슬라이더 왼쪽 끝 = 100", () => {
    expect(NODE_STAGES).toEqual([100, 50, 20, 10]);
    expect(CLUSTER_STAGES).toEqual([5, 4, 3, 2]);
    expect(N_STAGES).toBe(8);
    const modes = Array.from({ length: N_STAGES }, (_, i) => stageMode(i));
    expect(modes.map((m) => (m.kind === "nodes" ? m.n : `C${m.k}`))).toEqual([100, 50, 20, 10, "C5", "C4", "C3", "C2"]);
    modes.forEach((m, i) => expect(stageIndex(m)).toBe(i));
    expect(stageText(0)).toBe("100 노드");
    expect(stageText(4)).toBe("군집 5");
    expect(stageMode(-3)).toEqual({ kind: "nodes", n: 100 });
    expect(stageMode(99)).toEqual({ kind: "cluster", k: 2 });
  });

  it("사용 가능 단계: 상위 행·k_actual 기준, 비활성이면 가장 가까운 단계", () => {
    const m = man();
    for (let i = 0; i < N_STAGES; i++) expect(stageEnabled(m, i)).toBe(true);
    const few = { top: m.top.slice(0, 30), clusters: { ...m.clusters, "5": { ...m.clusters["5"], k_actual: 4 } } };
    expect([0, 1, 2, 3, 4, 5].map((i) => stageEnabled(few, i))).toEqual([true, false, true, true, false, true]);
    expect(nearestEnabledStage(few, 4)).toBe(3);
    expect(nearestEnabledStage({ top: [], clusters: {} }, 0)).toBe(-1);
    expect(nodeCount(m, 100)).toBe(100);
    expect(nodeCount(few, 100)).toBe(30);
  });
});

describe("V-L3-10 화살표 길이·사양", () => {
  it("길이 = L_max·|F|/F_ref, 최소 0.15·L_max", () => {
    expect(arrowLength(100, 100, 50)).toBeCloseTo(50, 12);
    expect(arrowLength(50, 100, 50)).toBeCloseTo(25, 12);
    expect(arrowLength(1, 100, 50)).toBeCloseTo(50 * MIN_LEN_FRAC, 12);
    expect(arrowLength(0, 100, 50)).toBeCloseTo(7.5, 12);
    expect(arrowLength(5, 0, 50)).toBeCloseTo(7.5, 12);
  });

  it("노드 모드: 개수·색·길이 규칙, F 방향 단위벡터, 군집 모드: 라벨·굵기 2배", () => {
    const m = man();
    const diag = m.bbox.diag;
    const a100 = buildArrowSpecs(m, { kind: "nodes", n: 100 }, null, 0);
    expect(a100.length).toBe(100);
    expect(a100[0].color).toBe(ARROW_COLOR);
    expect(a100[0].length).toBeCloseTo(0.1 * diag, 9); // 최대 |F| = F_ref
    for (const a of a100) {
      expect(Math.hypot(...a.dir)).toBeCloseTo(1, 9);
      expect(a.length).toBeGreaterThanOrEqual(0.1 * diag * MIN_LEN_FRAC - 1e-9);
      expect(a.headLen).toBeLessThanOrEqual(0.04 * diag + 1e-9);
      expect(a.shaftLen + a.headLen).toBeCloseTo(a.length, 9);
    }
    expect(buildArrowSpecs(m, { kind: "nodes", n: 10 }, null, 0).length).toBe(10);
    const c = buildArrowSpecs(m, { kind: "cluster", k: 3 }, null, 0);
    expect(c.length).toBe(3);
    expect(c[0].color).toBe(CLUSTER_COLOR);
    expect(c[0].label).toMatch(/^C1 [\d.]+ N$/);
    expect(c[0].shaftRadius).toBeCloseTo(2 * a100[0].shaftRadius, 12);
    expect(c[0].length).toBeCloseTo(0.1 * diag, 9);
  });

  it("변형 형상이면 꼬리가 x + k·u(정점) 로 이동", () => {
    const m = man();
    const u = new Float32Array(m.n_nodes * 3).fill(0);
    const v = m.top[0].vertex;
    u[v * 3 + 2] = 2;
    const a = buildArrowSpecs(m, { kind: "nodes", n: 10 }, u, 5)[0];
    expect(a.tail[2]).toBeCloseTo(m.top[0].z + 10, 9);
    expect(buildArrowSpecs(m, { kind: "nodes", n: 10 }, u, 0)[0].tail[2]).toBeCloseTo(m.top[0].z, 9);
  });
});

describe("V-L3-10 Blues 표", () => {
  it("끝값 #f7fbff → #08306b, 밝기 단조 감소, NaN 회색, 범위 밖은 끝색", () => {
    expect(bluesSrgb(0).map(Math.round)).toEqual([247, 251, 255]);
    expect(bluesSrgb(1).map(Math.round)).toEqual([8, 48, 107]);
    expect(BLUES9.length).toBe(9);
    let prev = Infinity;
    for (let i = 0; i <= 64; i++) {
      const L = luminance(bluesSrgb(i / 64));
      expect(L).toBeLessThan(prev);
      prev = L;
    }
    // 선형 표 = sRGB 표의 선형 변환
    expect(LUT_LINEAR[0]).toBeCloseTo(srgbToLinear(247), 6);
    expect(LUT_SRGB[0]).toBeCloseTo(247 / 255, 6);
    const out = new Float32Array(9);
    fillVertexColors([0, 100, NaN], 0, 50, out);
    expect([out[0], out[1], out[2]]).toEqual([LUT_LINEAR[0], LUT_LINEAR[1], LUT_LINEAR[2]]);
    const last = (256 - 1) * 3;
    expect(out[3]).toBeCloseTo(LUT_LINEAR[last], 6); // 100 > max → 가장 진함
    expect([out[6], out[7], out[8]].map((x, i) => x - NAN_LINEAR[i])).toEqual([0, 0, 0].map((x) => expect.closeTo(x, 6)));
    expect(normalize(5, 0, 10)).toBe(0.5);
    expect(normalize(5, 10, 10)).toBe(0);
    expect(Number.isNaN(normalize(Infinity, 0, 1))).toBe(true);
  });

  it("LOD src 로 원 정점 값을 모아 색을 채운다", () => {
    const out = new Float32Array(6);
    fillVertexColors([0, 10], 0, 10, out, [1, 0]);
    expect(out[0]).toBeCloseTo(LUT_LINEAR[255 * 3], 6);
    expect(out[3]).toBeCloseTo(LUT_LINEAR[0], 6);
  });
});

describe("V-L3-6 values.bin 복원", () => {
  it("복원 오차 ≤ s/2, 4바이트 정렬, 배열 키", () => {
    const m = man();
    const v = decodeValues(mockView3d().values, m);
    expect(v.n).toBe(m.n_nodes);
    for (const a of m.values.arrays) expect(a.offset % 4).toBe(0);
    expect(v.fn!.length).toBe(m.n_nodes);
    expect(v.u!.length).toBe(m.n_nodes * 3);
    // 상위 행의 정확 Fn·|F| 와 비교
    for (const r of m.top.slice(0, 20)) {
      expect(Math.abs(v.fn![r.vertex] - r.fn)).toBeLessThanOrEqual(v.scale.fn / 2 + 1e-9);
      expect(Math.abs(v.fmag![r.vertex] - r.mag)).toBeLessThanOrEqual(v.scale.fmag / 2 + 1e-9);
    }
    expect(Math.max(...Array.from(v.fmag!))).toBeCloseTo(m.ranges.fmag_max, 0);
    // 면압은 크기(≥ 0)
    expect(Math.min(...Array.from(v.pa!))).toBeGreaterThanOrEqual(0);
  });

  it("배율 0(전부 0)이면 0, 범위 초과·알 수 없는 dtype 은 오류, pa 없으면 |Fn| 폴백", () => {
    const buf = new ArrayBuffer(16);
    const base = { n_nodes: 2, values: { name: "values.bin", bytes: 16, arrays: [{ key: "fn" as const, dtype: "int16" as const, comps: 1, offset: 0, scale: 0 }] } };
    const v = decodeValues(buf, base);
    expect(Array.from(v.fn!)).toEqual([0, 0]);
    expect(() => decodeValues(buf, { ...base, values: { ...base.values, arrays: [{ ...base.values.arrays[0], offset: 14 }] } })).toThrow(/범위 초과/);
    expect(() => decodeValues(buf, { ...base, values: { ...base.values, arrays: [{ ...base.values.arrays[0], dtype: "float32" as never }] } })).toThrow(/dtype/);
    const dv = new DataView(buf);
    dv.setInt16(0, -300, true);
    const v2 = decodeValues(buf, { ...base, values: { ...base.values, arrays: [{ ...base.values.arrays[0], scale: 0.5 }] } });
    expect(colorField(v2)).toEqual({ values: Float32Array.from([150, 0]), unit: "N" });
    expect(colorField(decodeValues(mockView3d().values, man()))!.unit).toBe("MPa");
  });

  it("툴팁 유효숫자는 양자화 간격까지", () => {
    expect(fmtQuant(12.3456, 0.01)).toBe("12.35");
    expect(fmtQuant(12.3456, 1)).toBe("12");
    expect(fmtQuant(12.3456, 0.5)).toBe("12.3");
    expect(fmtQuant(12.3456, 0)).toBe("12.3456");
    expect(fmtQuant(NaN, 0.1)).toBe("–");
  });
});

describe("V-L3-5 GLB (프런트 해석)", () => {
  it("위치 복원 오차 ≤ 양자화 상한, _NODE_ID 왕복, 인덱스 수, extras", () => {
    const mesh = makeMesh();
    const g = parseGlb(mockView3d().glb);
    expect(g.positions.length).toBe(mesh.n * 3);
    expect(Array.from(g.nodeIds!)).toEqual(Array.from(mesh.nodeIds));
    expect(g.indices.length).toBe(mesh.indices.length);
    expect(g.indices.length / 3).toBe(2 * mesh.quads.length);
    expect(g.extras).toMatchObject({ units: "mm", up: "Z" });
    const m = man();
    for (let c = 0; c < 3; c++) {
      const tol = (m.bbox.max[c] - m.bbox.min[c]) / 65534 / 2 + 1e-4;
      for (let i = 0; i < mesh.n; i++) expect(Math.abs(g.positions[i * 3 + c] - mesh.x[i * 3 + c])).toBeLessThanOrEqual(tol * 1.001 + 1e-3);
    }
    expect(mockView3d().glb.byteLength).toBeLessThan(100 * 1024);
  });

  it("GLTFLoader.parseAsync 결과와 같은 위치(정규화 정수 × scale + translation)", async () => {
    const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
    const buf = mockView3d().glb;
    const gltf = await new GLTFLoader().parseAsync(buf.slice(0), "");
    let mesh: import("three").Mesh | undefined;
    gltf.scene.traverse((o) => {
      if ((o as import("three").Mesh).isMesh) mesh = o as import("three").Mesh;
    });
    expect(mesh).toBeTruthy();
    mesh!.updateMatrixWorld(true);
    const pos = mesh!.geometry.getAttribute("position");
    const mine = parseGlb(buf);
    expect(pos.count * 3).toBe(mine.positions.length);
    const v = { x: 0, y: 0, z: 0, set(x: number, y: number, z: number) { this.x = x; this.y = y; this.z = z; return this; } };
    for (const i of [0, 1, 47, 500, pos.count - 1]) {
      v.set(pos.getX(i), pos.getY(i), pos.getZ(i));
      const p = new (await import("three")).Vector3(v.x, v.y, v.z).applyMatrix4(mesh!.matrixWorld);
      expect(p.x).toBeCloseTo(mine.positions[i * 3], 2);
      expect(p.y).toBeCloseTo(mine.positions[i * 3 + 1], 2);
      expect(p.z).toBeCloseTo(mine.positions[i * 3 + 2], 2);
    }
  });

  it("헤더·청크 오류는 한국어 오류", () => {
    expect(() => parseGlb(new ArrayBuffer(8))).toThrow(/GLB/);
    const bad = new ArrayBuffer(32);
    new DataView(bad).setUint32(0, 0x46546c67, true);
    new DataView(bad).setUint32(4, 1, true);
    expect(() => parseGlb(bad)).toThrow(/2\.0/);
  });
});

describe("V-L3-10 지지 기호·변형·최근접 정점", () => {
  it("dof → 기호(3 ▲ · 2 ◭ · 1 △), 라벨 = dofText, 구속 축 선분", () => {
    expect(supportSymbol("123")).toMatchObject({ kind: "filled", axes: [0, 1, 2], count: 3, label: "123 (x·y·z)" });
    expect(supportSymbol("13")).toMatchObject({ kind: "half", axes: [0, 2], label: "13 (x·z)" });
    expect(supportSymbol("3")).toMatchObject({ kind: "empty", axes: [2], label: "3 (z)" });
    expect(supportSymbol("ij")).toMatchObject({ kind: "half", axes: [], label: "ij" });
    const m = man();
    const specs = buildSupportSpecs(m.supports, null, 0, m.bbox.diag);
    expect(specs.map((s) => s.symbol.kind)).toEqual(["filled", "half", "empty"]);
    expect(specs.map((s) => s.segments.length)).toEqual([3, 2, 1]);
    const [a, b] = specs[2].segments[0];
    expect(b[2] - a[2]).toBeCloseTo(0.08 * m.bbox.diag, 9);
  });

  it("기본 k·표기 문자열 \"변형 확대 배율 ×k (실제 최대 X mm)\"", () => {
    expect(defaultScaleExp(1000, 2)).toBe(Math.round(Math.log10(25) * 100) / 100);
    expect(defaultScale(1000, 2)).toBeCloseTo(25, 0);
    expect(defaultScale(1000, 0)).toBe(1);
    expect(defaultScale(10, 100)).toBe(1); // clamp 하한 1
    expect(defaultScale(1e6, 0.001)).toBeCloseTo(1e4, 6); // 상한 1e4
    expect(scaleFromExp(2)).toBeCloseTo(100, 9);
    expect(scaleFromExp(9)).toBeCloseTo(1e4, 6);
    expect(scaleLabel(25.12, 2.81)).toBe("변형 확대 배율 ×25.12 (실제 최대 2.81 mm)");
    expect(scaleLabel(1, 0)).toBe("변형 확대 배율 ×1 (실제 최대 – mm)");
  });

  it("위치 = base + k·u, 최근접 정점, 광선-선분", () => {
    const out = new Float32Array(3);
    expect(Array.from(applyDeform([1, 2, 3], [1, 1, 1], 10, out))).toEqual([11, 12, 13]);
    expect(Array.from(applyDeform([1, 2, 3], null, 10, out))).toEqual([1, 2, 3]);
    expect(pointAt([0, 0, 0, 1, 1, 1], [0, 0, 0, 1, 0, 0], 1, 2)).toEqual([3, 1, 1]);
    const P = [0, 0, 0, 10, 0, 0, 0, 10, 0];
    expect(nearestVertex(P, [9, 1, 0])).toBe(1);
    expect(nearestVertex(P, [0, 9, 0], [0, 1])).toBe(0);
    expect(nearestVertex([], [0, 0, 0])).toBe(-1);
    const r = raySegmentDistance([0, 0, 10], [0, 0, -1], [-5, 1, 0], [5, 1, 0]);
    expect(r.dist).toBeCloseTo(1, 9);
    expect(r.t).toBeCloseTo(10, 9);
    const segs = [
      { a: [-5, 3, 0] as [number, number, number], b: [5, 3, 0] as [number, number, number] },
      { a: [-5, 0.2, 0] as [number, number, number], b: [5, 0.2, 0] as [number, number, number] },
    ];
    expect(pickSegment([0, 0, 10], [0, 0, -1], segs, 0.5)).toBe(1);
    expect(pickSegment([0, 0, 10], [0, 0, -1], segs, 0.1)).toBe(-1);
  });
});

describe("V-L3-10 선택 연동(순수)", () => {
  it("보이는 키·사라진 선택 해제·3D 선택 변환·행 선택 판정", () => {
    const m = man();
    expect(visibleKeys(m, { kind: "nodes", n: 10 })).toEqual(Array.from({ length: 10 }, (_, i) => String(i + 1)));
    expect(visibleKeys(m, { kind: "cluster", k: 3 })).toEqual(["C1", "C2", "C3"]);
    expect(reconcile({ kind: "arrow", key: "50" }, visibleKeys(m, { kind: "nodes", n: 10 }))).toBeNull();
    expect(reconcile({ kind: "arrow", key: "5" }, visibleKeys(m, { kind: "nodes", n: 10 }))).toEqual({ kind: "arrow", key: "5" });
    expect(reconcile({ kind: "vertex", vertex: 3 }, [])).toEqual({ kind: "vertex", vertex: 3 });
    const keys = ["1", "2", "3"];
    expect(selectionFromPick({ type: "arrow", index: 1 }, keys)).toEqual({ kind: "arrow", key: "2" });
    expect(selectionFromPick({ type: "arrow", index: 9 }, keys)).toBeNull();
    expect(selectionFromPick({ type: "vertex", vertex: 7 }, keys)).toEqual({ kind: "vertex", vertex: 7 });
    expect(selectionFromPick({ type: "support", index: 0 }, keys)).toEqual({ kind: "support", index: 0 });
    expect(selectionFromPick({ type: "none" }, keys)).toBeNull();
    const row = m.top[2];
    expect(nodeRowSelected({ kind: "arrow", key: "3" }, row)).toBe(true);
    expect(nodeRowSelected({ kind: "vertex", vertex: row.vertex }, row)).toBe(true);
    expect(nodeRowSelected({ kind: "support", index: 0 }, row)).toBe(false);
    expect(nodeRowSelected(null, row)).toBe(false);
    expect(clusterRowSelected({ kind: "arrow", key: "C2" }, "C2")).toBe(true);
    const arrows = buildArrowSpecs(m, { kind: "nodes", n: 10 }, null, 0);
    expect(sceneSelection({ kind: "arrow", key: "3" }, arrows, m.supports, m.top)).toEqual({ arrowIndex: 2, vertex: row.vertex });
    expect(sceneSelection({ kind: "vertex", vertex: row.vertex }, arrows, m.supports, m.top)).toEqual({ arrowIndex: 2, vertex: row.vertex });
    expect(sceneSelection({ kind: "support", index: 1 }, arrows, m.supports, m.top)).toEqual({ arrowIndex: null, vertex: m.supports[1].vertex });
    expect(sceneSelection(null, arrows, m.supports, m.top)).toEqual({ arrowIndex: null, vertex: null });
  });

  it("정보 줄: 노드 클릭 툴팁(면압 MPa · |Fn| N), 군집, 지지", () => {
    const m = man();
    const v = decodeValues(mockView3d().values, m);
    const t = infoLine({ kind: "arrow", key: "1" }, m, v, null)!;
    expect(t).toMatch(new RegExp(`^노드 ${m.top[0].node_id} · 면압 [\\d.]+ MPa · \\|Fn\\| [\\d.,]+ N \\(Fn -?[\\d.,]+\\) · \\|F\\| [\\d.,]+ N$`));
    const vt = infoLine({ kind: "vertex", vertex: 5 }, m, v, mockNodeIds())!;
    expect(vt).toMatch(/^노드 3006 · 면압 /);
    expect(infoLine({ kind: "arrow", key: "C1" }, m, v, null)).toMatch(/^군집 C1 · 노드 .* · \|R\| .* N · 상쇄율 \d+ % · \|M\|/);
    expect(infoLine({ kind: "support", index: 2 }, m, v, null)).toBe(`지지 ${m.supports[2].node_id} · dof 3 (z)`);
    expect(infoLine(null, m, v, null)).toBeNull();
  });
});

function mockNodeIds() {
  return parseGlb(mockView3d().glb).nodeIds!;
}

describe("manifest·mock 정합(백엔드와 맞춰볼 형태)", () => {
  it("상위 100행 정렬(|F| 내림, 동률 node_id), vertex·is_support, 군집 K=2..5 불변식", () => {
    const m = man();
    expect(m.top.length).toBe(100);
    for (let i = 1; i < m.top.length; i++) expect(m.top[i - 1].mag > m.top[i].mag || (m.top[i - 1].mag === m.top[i].mag && m.top[i - 1].node_id < m.top[i].node_id)).toBe(true);
    expect(m.top.every((r) => m.supports.some((s) => s.vertex === r.vertex) === r.is_support)).toBe(true);
    for (const K of [2, 3, 4, 5]) {
      const c = m.clusters[String(K)];
      expect(c.k_actual).toBe(K);
      expect(c.rows.map((r) => r.label)).toEqual(Array.from({ length: K }, (_, i) => `C${i + 1}`));
      const sum = [0, 0, 0];
      c.rows.forEach((r) => r.r.forEach((x, i) => (sum[i] += x)));
      sum.forEach((x, i) => expect(x).toBeCloseTo(m.sum_f[i], 6));
      for (let i = 1; i < K; i++) expect(c.rows[i - 1].r_mag).toBeGreaterThanOrEqual(c.rows[i].r_mag);
      c.rows.forEach((r) => {
        expect(r.cancel).toBeGreaterThanOrEqual(0);
        expect(r.cancel).toBeLessThanOrEqual(1);
      });
    }
    expect(Math.hypot(...m.sum_f)).toBeLessThan(1e-6); // 자기평형
  });

  it("법선·면적: XY 평판 → n = +z", () => {
    const mesh = makeMesh();
    const { nrm, area } = nodeNormalsAndAreas(mesh);
    expect(nrm.length).toBe(mesh.n * 3);
    expect(Math.hypot(nrm[0], nrm[1], nrm[2])).toBeCloseTo(1, 9);
    expect(area.every((a) => a > 0)).toBe(true);
    const c = weightedClusters(mesh.x, new Float64Array(mesh.n * 3), new Float64Array(mesh.n * 3), mesh.nodeIds, 3);
    expect(c.k_actual).toBe(0); // 하중 노드 없음
  });

  it("파일 URL 해석: 상대 이름 / 절대 경로 / 기본값", () => {
    expect(resolveFileUrl("r1", "part.glb")).toBe("/esl/api/esl-runs/r1/view3d/part.glb");
    expect(resolveFileUrl("r1", "./values.bin")).toBe("/esl/api/esl-runs/r1/view3d/values.bin");
    expect(resolveFileUrl("r1", "/esl/api/x/part.glb")).toBe("/esl/api/x/part.glb");
    const m = man();
    expect(fileUrls({ ...m, geometry_url: undefined, values_url: undefined })).toEqual({
      geometry: "/esl/api/esl-runs/esl-run-1/view3d/part.glb",
      lod: null,
      values: "/esl/api/esl-runs/esl-run-1/view3d/values.bin",
    });
  });
});

describe("V-L3-13 번들 규칙", () => {
  // Vite 가 원문 문자열로 읽는다(Node 타입 없이)
  const raw = (g: Record<string, unknown>) => Object.entries(g).map(([k, v]) => [k, v as string] as const);
  const sources = raw(import.meta.glob("../**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true })).filter(([k]) => !k.includes("__tests__"));
  const text = (g: Record<string, unknown>) => raw(g)[0][1];

  it("package.json: three 정확 버전 0.186.1", () => {
    const pkg = JSON.parse(text(import.meta.glob("../../package.json", { query: "?raw", import: "default", eager: true })));
    expect(pkg.dependencies.three).toBe("0.186.1");
  });

  it("three 는 scene.ts 한 곳에서만 import, loadThree 는 동적 import, CDN 참조 없음", () => {
    expect(sources.length).toBeGreaterThan(40);
    const importers = sources.filter(([, t]) => /from\s+["']three(\/|["'])/.test(t)).map(([k]) => k.split("/").pop());
    expect(importers).toEqual(["scene.ts"]);
    const lt = sources.find(([k]) => k.endsWith("view3d/loadThree.ts"))![1];
    expect(lt).toMatch(/import\("\.\/scene"\)/);
    expect(lt).not.toMatch(/^import [^(]*from\s+["']\.\/scene["']/m);
    for (const [, t] of sources) expect(t).not.toMatch(/https?:\/\/(cdn|unpkg|cdnjs)/);
    expect(text(import.meta.glob("../../index.html", { query: "?raw", import: "default", eager: true }))).not.toMatch(/<script[^>]+src=["']https?:/);
  });
});

describe("V-L3-14 성능", () => {
  it("정점 위치 갱신 30만 ≤ 30 ms (측정값 기록)", () => {
    const n = 300_000;
    const base = new Float32Array(n * 3).map((_, i) => i * 0.001);
    const u = new Float32Array(n * 3).fill(0.01);
    const out = new Float32Array(n * 3);
    applyDeform(base, u, 10, out); // 예열
    const t0 = performance.now();
    applyDeform(base, u, 10, out);
    const ms = performance.now() - t0;
    console.info(`[perf] applyDeform 300k = ${ms.toFixed(2)} ms`);
    expect(ms).toBeLessThan(30);
    const col = new Float32Array(n * 3);
    const t1 = performance.now();
    fillVertexColors(base.subarray(0, n), 0, 100, col);
    console.info(`[perf] fillVertexColors 300k = ${(performance.now() - t1).toFixed(2)} ms`);
  });
});
