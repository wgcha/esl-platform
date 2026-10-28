// V-L3-5 · V-L3-6(프런트): 백엔드 고정 fixture(tests/fixtures/view3d/small)를 읽어 glb.ts 해석·values 복원이 expected.json 과 일치하는지.
// GLTFLoader 결과와도 대조하고, mock 이 같은 형식(키 집합·배열 순서·정렬)인지 확인한다.
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { View3dOut } from "../api/types";
import { mockView3d } from "../mock/view3dmock";
import { fileUrls } from "../view3d/fetchFiles";
import { parseGlb } from "../view3d/glb";
import { colorField, decodeValues } from "../view3d/values";

const DIR = path.resolve(__dirname, "../../../tests/fixtures/view3d/small");
const bin = (name: string): ArrayBuffer => {
  const b = readFileSync(path.join(DIR, name));
  const out = new ArrayBuffer(b.byteLength);
  new Uint8Array(out).set(b);
  return out;
};
const manifest = JSON.parse(readFileSync(path.join(DIR, "manifest.json"), "utf8")) as View3dOut;
const expected = JSON.parse(readFileSync(path.join(DIR, "expected.json"), "utf8")) as {
  n_nodes: number;
  positions: number[][];
  pa: number[];
  fn: number[];
  fmag: number[];
  u: number[][];
};

describe("V-L3-5 fixture GLB ↔ expected.positions", () => {
  const g = parseGlb(bin("part.glb"));
  it("정점 수·위치(≤1e-4 mm)·인덱스", () => {
    expect(g.positions.length).toBe(expected.n_nodes * 3);
    expect(g.nodeIds!.length).toBe(expected.n_nodes);
    for (let i = 0; i < expected.n_nodes; i++) for (let c = 0; c < 3; c++) expect(Math.abs(g.positions[i * 3 + c] - expected.positions[i][c])).toBeLessThan(1e-4);
    expect(g.indices.length / 3).toBe(manifest.n_tris);
    expect(Math.max(...Array.from(g.indices))).toBeLessThan(manifest.n_nodes);
    expect(g.extras).toMatchObject({ units: manifest.units, up: manifest.up });
    expect(bin("part.glb").byteLength).toBe(manifest.geometry.bytes);
  });

  it("GLTFLoader.parseAsync 와 같은 위치 (KHR_mesh_quantization)", async () => {
    const THREE = await import("three");
    const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
    const gltf = await new GLTFLoader().parseAsync(bin("part.glb"), "");
    let mesh: import("three").Mesh | undefined;
    gltf.scene.traverse((o) => {
      if ((o as import("three").Mesh).isMesh) mesh = o as import("three").Mesh;
    });
    expect(mesh).toBeTruthy();
    mesh!.updateMatrixWorld(true);
    const pos = mesh!.geometry.getAttribute("position");
    expect(pos.count).toBe(expected.n_nodes);
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
      v.set(pos.getX(i), pos.getY(i), pos.getZ(i)).applyMatrix4(mesh!.matrixWorld);
      expect(v.x).toBeCloseTo(g.positions[i * 3], 3);
      expect(v.y).toBeCloseTo(g.positions[i * 3 + 1], 3);
      expect(v.z).toBeCloseTo(g.positions[i * 3 + 2], 3);
    }
    expect(mesh!.geometry.getIndex()!.count).toBe(g.indices.length);
  });

  it("LOD: 정점 수 = manifest.lod.n_vertices, _SRC 가 가리키는 원 정점 위치와 같음", () => {
    const lod = parseGlb(bin("part_lod.glb"));
    expect(manifest.lod).toBeTruthy();
    expect(lod.positions.length / 3).toBe(manifest.lod!.n_vertices);
    expect(lod.src!.length).toBe(manifest.lod!.n_vertices);
    expect(bin("part_lod.glb").byteLength).toBe(manifest.lod!.bytes);
    for (let i = 0; i < lod.src!.length; i++) for (let c = 0; c < 3; c++) expect(Math.abs(lod.positions[i * 3 + c] - g.positions[lod.src![i] * 3 + c])).toBeLessThan(1e-3);
  });
});

describe("V-L3-6 fixture values.bin ↔ expected", () => {
  const buf = bin("values.bin");
  const v = decodeValues(buf, manifest);
  it("manifest: 배열 순서 pa·fn·fmag·u, 오프셋 4바이트 정렬, 파일 길이 일치", () => {
    expect(manifest.values.arrays.map((a) => a.key)).toEqual(["pa", "fn", "fmag", "u"]);
    for (const a of manifest.values.arrays) expect(a.offset % 4).toBe(0);
    expect(buf.byteLength).toBe(manifest.values.bytes);
  });
  it("pa·fn·fmag·u 복원이 expected 와 양자화 간격 이내", () => {
    const n = expected.n_nodes;
    expect(v.n).toBe(n);
    for (let i = 0; i < n; i++) {
      expect(Math.abs(v.pa![i] - expected.pa[i])).toBeLessThanOrEqual(v.scale.pa * 1e-3 + Math.abs(expected.pa[i]) * 1e-6);
      expect(Math.abs(v.fn![i] - expected.fn[i])).toBeLessThanOrEqual(v.scale.fn * 1e-3 + Math.abs(expected.fn[i]) * 1e-6);
      expect(Math.abs(v.fmag![i] - expected.fmag[i])).toBeLessThanOrEqual(v.scale.fmag * 1e-3 + Math.abs(expected.fmag[i]) * 1e-6);
      for (let c = 0; c < 3; c++) expect(Math.abs(v.u![i * 3 + c] - expected.u[i][c])).toBeLessThanOrEqual(v.scale.u[c] * 1e-3 + Math.abs(expected.u[i][c]) * 1e-6);
    }
    expect(colorField(v)!.unit).toBe("MPa");
  });
  it("top 행의 pa·fn·mag 이 같은 정점의 복원값과 양자화 간격 이내", () => {
    for (const r of manifest.top) {
      expect(Math.abs(v.pa![r.vertex] - r.pa)).toBeLessThanOrEqual(v.scale.pa);
      expect(Math.abs(v.fn![r.vertex] - r.fn)).toBeLessThanOrEqual(v.scale.fn);
      expect(Math.abs(v.fmag![r.vertex] - r.mag)).toBeLessThanOrEqual(v.scale.fmag);
    }
    expect(manifest.ranges.pa.max).toBeGreaterThan(0);
  });
});

describe("URL 해석: 실제 manifest 의 API 루트 경로", () => {
  it("fixture manifest 에 URL 이 없으면 이름 기준, 있으면 접두 /esl/api + ?key=", () => {
    const m: View3dOut = { ...manifest, geometry_url: "/esl-runs/fixture-run/view3d/part.glb", lod_url: "/esl-runs/fixture-run/view3d/part_lod.glb", values_url: "/esl-runs/fixture-run/view3d/values.bin", created_at: "x" };
    expect(fileUrls(m)).toEqual({
      geometry: "/esl/api/esl-runs/fixture-run/view3d/part.glb?key=fixture0000000001",
      lod: "/esl/api/esl-runs/fixture-run/view3d/part_lod.glb?key=fixture0000000001",
      values: "/esl/api/esl-runs/fixture-run/view3d/values.bin?key=fixture0000000001",
    });
  });
});

describe("mock 이 같은 형식", () => {
  const mk = mockView3d();
  const mm = mk.manifest("r1");
  it("manifest 최상위·top 행·ranges 키 집합이 실제와 같다(URL 항목 추가분 제외)", () => {
    const real = new Set([...Object.keys(manifest), "geometry_url", "lod_url", "values_url", "created_at"]);
    expect(new Set(Object.keys(mm))).toEqual(real);
    expect(Object.keys(mm.top[0]).sort()).toEqual(Object.keys(manifest.top[0]).sort());
    expect(Object.keys(mm.ranges).sort()).toEqual(Object.keys(manifest.ranges).sort());
    expect(Object.keys(Object.values(mm.clusters)[0].rows[0]).sort()).toEqual(Object.keys(Object.values(manifest.clusters)[0].rows[0]).sort());
    expect(mm.geometry_url).toBe("/esl-runs/r1/view3d/part.glb");
  });
  it("values 배열 순서·정렬·dtype 이 같고 GLB 구조(양자화 SHORT, stride 8)가 같다", () => {
    expect(mm.values.arrays.map((a) => [a.key, a.dtype, a.comps])).toEqual(manifest.values.arrays.map((a) => [a.key, a.dtype, a.comps]));
    for (const a of mm.values.arrays) expect(a.offset % 4).toBe(0);
    const dv = new DataView(mk.glb);
    const jl = dv.getUint32(12, true);
    const j = JSON.parse(new TextDecoder().decode(new Uint8Array(mk.glb, 20, jl)));
    const r = JSON.parse(new TextDecoder().decode(new Uint8Array(bin("part.glb"), 20, new DataView(bin("part.glb")).getUint32(12, true))));
    expect(j.extensionsRequired).toEqual(r.extensionsRequired);
    expect(j.accessors.map((a: { componentType: number }) => a.componentType)).toEqual(r.accessors.map((a: { componentType: number }) => a.componentType));
    expect(j.bufferViews[0].byteStride).toBe(r.bufferViews[0].byteStride);
    expect(Object.keys(j.meshes[0].primitives[0].attributes)).toEqual(Object.keys(r.meshes[0].primitives[0].attributes));
  });
});
