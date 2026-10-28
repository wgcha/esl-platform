// mock 3D 하중 보기 자료(계약 esl_3d_load.md §3.3·§3.5·§3.6): 합성 굽은 판(플랜지) GLB(≤100 KB) + values.bin + manifest.
// 서버 쪽 Python(esl/view3d.py)과 같은 배치·양자화 규칙을 TS 로 흉내 낸다. 결정적(난수 없음).
import type { View3dClusterRow, View3dOut, View3dTopRow, View3dValuesArray } from "../api/types";

const NX = 48;
const NY = 30;
const LX = 620; // mm
const LY = 380;
const X0 = 1480;
const NODE0 = 3001;

type V3 = [number, number, number];
const SUPPORT_VERTS = [0, NX - 1, (NY - 1) * NX + Math.floor(NX / 2)];
const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: V3) => Math.hypot(a[0], a[1], a[2]);

export interface MockMesh {
  n: number;
  x: Float64Array; // 3n
  nodeIds: Uint32Array;
  indices: Uint32Array; // 삼각형
  quads: number[][];
}

export function makeMesh(): MockMesh {
  const n = NX * NY;
  const x = new Float64Array(n * 3);
  const nodeIds = new Uint32Array(n);
  for (let j = 0; j < NY; j++)
    for (let i = 0; i < NX; i++) {
      const k = j * NX + i;
      const a = i / (NX - 1);
      const b = j / (NY - 1);
      // 가장자리(y)에 위로 꺾인 플랜지, 가운데 완만한 볼록
      const fl = Math.max(0, Math.abs(b - 0.5) - 0.36) / 0.14;
      const z = 410 + 70 * fl * fl + 9 * Math.sin(Math.PI * a) * Math.sin(Math.PI * b);
      x[k * 3] = X0 + a * LX;
      x[k * 3 + 1] = (b - 0.5) * LY;
      x[k * 3 + 2] = z;
      nodeIds[k] = NODE0 + k;
    }
  const quads: number[][] = [];
  const tri: number[] = [];
  for (let j = 0; j < NY - 1; j++)
    for (let i = 0; i < NX - 1; i++) {
      const a = j * NX + i;
      const b = a + 1;
      const c = a + NX + 1;
      const d = a + NX;
      quads.push([a, b, c, d]);
      tri.push(a, b, c, a, c, d);
    }
  return { n, x, nodeIds, indices: Uint32Array.from(tri), quads };
}

/** 노드 법선(면적 가중, 판 법선 +z 쪽으로 통일) 과 노드 대표 면적(인접 요소 면적/절점 수 합, mm²) */
export function nodeNormalsAndAreas(m: MockMesh): { nrm: Float64Array; area: Float64Array } {
  const nrm = new Float64Array(m.n * 3);
  const area = new Float64Array(m.n);
  const p = (i: number): V3 => [m.x[i * 3], m.x[i * 3 + 1], m.x[i * 3 + 2]];
  for (const q of m.quads) {
    const [a, b, c, d] = q.map(p);
    let ne = cross(sub(c, a), sub(d, b));
    const A = norm(ne) / 2;
    ne = [ne[0] / (2 * A), ne[1] / (2 * A), ne[2] / (2 * A)];
    if (ne[2] < 0) ne = [-ne[0], -ne[1], -ne[2]];
    for (const v of q) {
      for (let c3 = 0; c3 < 3; c3++) nrm[v * 3 + c3] += A * ne[c3];
      area[v] += A / 4;
    }
  }
  for (let i = 0; i < m.n; i++) {
    const l = Math.hypot(nrm[i * 3], nrm[i * 3 + 1], nrm[i * 3 + 2]) || 1;
    for (let c = 0; c < 3; c++) nrm[i * 3 + c] /= l;
  }
  return { nrm, area };
}

/** 합성 자기평형 하중 F(3n): 두 접촉 패치(+면외/−면외) + 면내 성분, 평균 제거로 ΣF = 0 */
function makeForces(m: MockMesh): Float64Array {
  const f = new Float64Array(m.n * 3);
  const patches: { c: [number, number]; r: number; f: V3 }[] = [
    { c: [X0 + 0.28 * LX, -0.1 * LY], r: 70, f: [180, -60, 1450] },
    { c: [X0 + 0.74 * LX, 0.12 * LY], r: 85, f: [-120, 90, -980] },
    { c: [X0 + 0.5 * LX, 0.4 * LY], r: 40, f: [-70, 0, 520] },
    { c: [X0 + 0.9 * LX, -0.36 * LY], r: 38, f: [40, 70, -410] },
  ];
  for (let i = 0; i < m.n; i++) {
    const px = m.x[i * 3];
    const py = m.x[i * 3 + 1];
    for (const p of patches) {
      const d2 = ((px - p.c[0]) ** 2 + (py - p.c[1]) ** 2) / (p.r * p.r);
      if (d2 < 4) {
        const w = Math.exp(-d2 * 1.6);
        for (let c = 0; c < 3; c++) f[i * 3 + c] += p.f[c] * w * 0.1;
      }
    }
  }
  // 지지점이 반력으로 합을 0 으로 맞춘다(자유물체 F_eq: ΣF ≈ 0)
  const mean = [0, 0, 0];
  for (let i = 0; i < m.n; i++) for (let c = 0; c < 3; c++) mean[c] += f[i * 3 + c];
  for (const v of SUPPORT_VERTS) for (let c = 0; c < 3; c++) f[v * 3 + c] -= mean[c] / SUPPORT_VERTS.length;
  return f;
}

function makeU(m: MockMesh): Float64Array {
  const u = new Float64Array(m.n * 3);
  for (let i = 0; i < m.n; i++) {
    const a = (m.x[i * 3] - X0) / LX;
    const b = m.x[i * 3 + 1] / LY + 0.5;
    const w = 2.4 * Math.sin(Math.PI * a) ** 2 * Math.sin(Math.PI * b) * (0.6 + 0.4 * a);
    u[i * 3] = 0.25 * (a - 0.5) * w;
    u[i * 3 + 1] = 0.2 * (b - 0.5) * w;
    u[i * 3 + 2] = w;
  }
  return u;
}

// ---------------------------------------------------------------- 양자화·GLB·values.bin
function pad4(n: number) {
  return (n + 3) & ~3;
}

export function writeGlb(m: MockMesh): ArrayBuffer {
  const n = m.n;
  const mn = [Infinity, Infinity, Infinity];
  const mx = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++)
    for (let c = 0; c < 3; c++) {
      mn[c] = Math.min(mn[c], m.x[i * 3 + c]);
      mx[c] = Math.max(mx[c], m.x[i * 3 + c]);
    }
  const ctr = mn.map((v, c) => (v + mx[c]) / 2);
  const half = mn.map((v, c) => (mx[c] - v) / 2 || 1);
  const posBytes = n * 8;
  const idBytes = n * 4;
  const idxBytes = m.indices.length * 4;
  const bin = new ArrayBuffer(pad4(posBytes) + pad4(idBytes) + pad4(idxBytes));
  const dv = new DataView(bin);
  for (let i = 0; i < n; i++)
    for (let c = 0; c < 3; c++) dv.setInt16(i * 8 + c * 2, Math.round(((m.x[i * 3 + c] - ctr[c]) / half[c]) * 32767), true);
  for (let i = 0; i < n; i++) dv.setUint32(pad4(posBytes) + i * 4, m.nodeIds[i], true);
  for (let i = 0; i < m.indices.length; i++) dv.setUint32(pad4(posBytes) + pad4(idBytes) + i * 4, m.indices[i], true);
  const json = {
    asset: { version: "2.0", generator: "esl view3d mock", extras: { units: "mm", up: "Z", generator: "esl view3d mock" } },
    extensionsUsed: ["KHR_mesh_quantization"],
    extensionsRequired: ["KHR_mesh_quantization"],
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0, translation: ctr, scale: half }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, _NODE_ID: 1 }, indices: 2, mode: 4 }] }],
    accessors: [
      { bufferView: 0, componentType: 5122, normalized: true, count: n, type: "VEC3", min: [-32767, -32767, -32767], max: [32767, 32767, 32767] },
      { bufferView: 1, componentType: 5125, count: n, type: "SCALAR" },
      { bufferView: 2, componentType: 5125, count: m.indices.length, type: "SCALAR" },
    ],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: posBytes, byteStride: 8, target: 34962 },
      { buffer: 0, byteOffset: pad4(posBytes), byteLength: idBytes, target: 34962 },
      { buffer: 0, byteOffset: pad4(posBytes) + pad4(idBytes), byteLength: idxBytes, target: 34963 },
    ],
    buffers: [{ byteLength: bin.byteLength }],
  };
  const jb = new TextEncoder().encode(JSON.stringify(json));
  const jlen = pad4(jb.length);
  const total = 12 + 8 + jlen + 8 + bin.byteLength;
  const out = new ArrayBuffer(total);
  const o = new DataView(out);
  o.setUint32(0, 0x46546c67, true);
  o.setUint32(4, 2, true);
  o.setUint32(8, total, true);
  o.setUint32(12, jlen, true);
  o.setUint32(16, 0x4e4f534a, true);
  const u8 = new Uint8Array(out);
  u8.fill(0x20, 20, 20 + jlen);
  u8.set(jb, 20);
  o.setUint32(20 + jlen, bin.byteLength, true);
  o.setUint32(24 + jlen, 0x004e4942, true);
  u8.set(new Uint8Array(bin), 28 + jlen);
  return out;
}

interface Packed {
  buf: ArrayBuffer;
  arrays: View3dValuesArray[];
}
function packValues(n: number, fn: Float64Array, fmag: Float64Array, pa: Float64Array, u: Float64Array): Packed {
  const maxAbs = (a: ArrayLike<number>, stride: number, c: number) => {
    let mm = 0;
    for (let i = 0; i < n; i++) mm = Math.max(mm, Math.abs(a[i * stride + c]));
    return mm;
  };
  const sFn = maxAbs(fn, 1, 0) / 32767;
  const sMag = maxAbs(fmag, 1, 0) / 65535;
  const sPa = maxAbs(pa, 1, 0) / 65535;
  const sU = [0, 1, 2].map((c) => maxAbs(u, 3, c) / 32767);
  const sizes = [n * 2, n * 2, n * 2, n * 6].map(pad4);
  const offs = [0, sizes[0], sizes[0] + sizes[1], sizes[0] + sizes[1] + sizes[2]];
  const buf = new ArrayBuffer(sizes.reduce((a, b) => a + b, 0));
  const dv = new DataView(buf);
  for (let i = 0; i < n; i++) {
    dv.setUint16(offs[0] + i * 2, sPa ? Math.round(pa[i] / sPa) : 0, true);
    dv.setInt16(offs[1] + i * 2, sFn ? Math.round(fn[i] / sFn) : 0, true);
    dv.setUint16(offs[2] + i * 2, sMag ? Math.round(fmag[i] / sMag) : 0, true);
    for (let c = 0; c < 3; c++) dv.setInt16(offs[3] + i * 6 + c * 2, sU[c] ? Math.round(u[i * 3 + c] / sU[c]) : 0, true);
  }
  return {
    buf,
    arrays: [
      { key: "pa", dtype: "uint16", comps: 1, offset: offs[0], scale: sPa },
      { key: "fn", dtype: "int16", comps: 1, offset: offs[1], scale: sFn },
      { key: "fmag", dtype: "uint16", comps: 1, offset: offs[2], scale: sMag },
      { key: "u", dtype: "int16", comps: 3, offset: offs[3], scale: sU },
    ],
  };
}

// ---------------------------------------------------------------- 군집 (계약 §3.6 L3-7: 가중 최원점 초기화 + Lloyd, 난수 없음)
export function weightedClusters(x: ArrayLike<number>, f: ArrayLike<number>, u: ArrayLike<number>, nodeIds: ArrayLike<number>, K: number): { k_actual: number; rows: View3dClusterRow[] } {
  const n = nodeIds.length;
  const idx: number[] = [];
  const w: number[] = [];
  for (let i = 0; i < n; i++) {
    const mg = Math.hypot(f[i * 3], f[i * 3 + 1], f[i * 3 + 2]);
    if (mg > 0) (idx.push(i), w.push(mg));
  }
  const m = idx.length;
  if (m === 0) return { k_actual: 0, rows: [] };
  const k = Math.min(K, m);
  const P = (t: number, c: number) => x[idx[t] * 3 + c];
  const d2 = (t: number, c: V3) => (P(t, 0) - c[0]) ** 2 + (P(t, 1) - c[1]) ** 2 + (P(t, 2) - c[2]) ** 2;
  const better = (a: number, b: number, sa: number, sb: number) => sa > sb || (sa === sb && nodeIds[idx[a]] < nodeIds[idx[b]]);
  const cent: V3[] = [];
  let first = 0;
  for (let t = 1; t < m; t++) if (better(t, first, w[t], w[first])) first = t;
  cent.push([P(first, 0), P(first, 1), P(first, 2)]);
  while (cent.length < k) {
    let bt = -1;
    let bs = -1;
    for (let t = 0; t < m; t++) {
      const s = w[t] * Math.min(...cent.map((c) => d2(t, c)));
      if (bt < 0 || better(t, bt, s, bs)) (bt = t), (bs = s);
    }
    cent.push([P(bt, 0), P(bt, 1), P(bt, 2)]);
  }
  let asg = new Array<number>(m).fill(-1);
  for (let it = 0; it < 50; it++) {
    const next = idx.map((_, t) => {
      let b = 0;
      let bd = Infinity;
      cent.forEach((c, j) => {
        const dd = d2(t, c);
        if (dd < bd) (bd = dd), (b = j);
      });
      return b;
    });
    const same = next.every((v, i) => v === asg[i]);
    asg = next;
    if (same) break;
    cent.forEach((_, j) => {
      let sw = 0;
      const s: V3 = [0, 0, 0];
      asg.forEach((a, t) => {
        if (a !== j) return;
        sw += w[t];
        for (let c = 0; c < 3; c++) s[c] += w[t] * P(t, c);
      });
      if (sw > 0) cent[j] = [s[0] / sw, s[1] / sw, s[2] / sw];
    });
  }
  const rows = cent.map((_, j) => {
    let sw = 0;
    const r: V3 = [0, 0, 0];
    const cc: V3 = [0, 0, 0];
    const uc: V3 = [0, 0, 0];
    let cnt = 0;
    let minId = Infinity;
    asg.forEach((a, t) => {
      if (a !== j) return;
      const i = idx[t];
      cnt++;
      sw += w[t];
      minId = Math.min(minId, nodeIds[i]);
      for (let c = 0; c < 3; c++) {
        r[c] += f[i * 3 + c];
        cc[c] += w[t] * x[i * 3 + c];
        uc[c] += w[t] * u[i * 3 + c];
      }
    });
    const ctr: V3 = [cc[0] / sw, cc[1] / sw, cc[2] / sw];
    const mm: V3 = [0, 0, 0];
    asg.forEach((a, t) => {
      if (a !== j) return;
      const i = idx[t];
      const cr = cross([x[i * 3] - ctr[0], x[i * 3 + 1] - ctr[1], x[i * 3 + 2] - ctr[2]], [f[i * 3], f[i * 3 + 1], f[i * 3 + 2]]);
      for (let c = 0; c < 3; c++) mm[c] += cr[c];
    });
    const rm = norm(r);
    return { label: "", n_nodes: cnt, center: ctr, u_center: [uc[0] / sw, uc[1] / sw, uc[2] / sw], r: [...r], r_mag: rm, sum_abs: sw, cancel: 1 - rm / sw, m: [...mm], m_mag: norm(mm), min_node_id: minId };
  });
  rows.sort((a, b) => b.r_mag - a.r_mag || a.min_node_id - b.min_node_id);
  rows.forEach((r, i) => (r.label = `C${i + 1}`));
  return { k_actual: rows.length, rows };
}

export interface MockView3d {
  glb: ArrayBuffer;
  values: ArrayBuffer;
  manifest: (runId: string) => View3dOut;
}

let cache: MockView3d | null = null;

export function mockView3d(): MockView3d {
  if (cache) return cache;
  const m = makeMesh();
  const { nrm, area } = nodeNormalsAndAreas(m);
  const f = makeForces(m);
  const u = makeU(m);
  const n = m.n;
  const fn = new Float64Array(n);
  const fmag = new Float64Array(n);
  const pa = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    fn[i] = f[i * 3] * nrm[i * 3] + f[i * 3 + 1] * nrm[i * 3 + 1] + f[i * 3 + 2] * nrm[i * 3 + 2];
    fmag[i] = Math.hypot(f[i * 3], f[i * 3 + 1], f[i * 3 + 2]);
    pa[i] = Math.abs(fn[i]) / area[i];
  }
  const packed = packValues(n, fn, fmag, pa, u);
  const glb = writeGlb(m);
  const p99 = (a: Float64Array) => {
    const s = Array.from(a).filter((v) => v > 0).sort((x, y) => x - y);
    return s.length ? s[Math.min(s.length - 1, Math.floor(0.99 * s.length))] : 0;
  };
  const mn = [Infinity, Infinity, Infinity];
  const mx = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++)
    for (let c = 0; c < 3; c++) {
      mn[c] = Math.min(mn[c], m.x[i * 3 + c]);
      mx[c] = Math.max(mx[c], m.x[i * 3 + c]);
    }
  const diag = Math.hypot(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]);
  const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => fmag[b] - fmag[a] || m.nodeIds[a] - m.nodeIds[b]);
  const supVerts = SUPPORT_VERTS;
  const supDof = ["123", "13", "3"];
  const supportSet = new Set(supVerts);
  const top: View3dTopRow[] = order.slice(0, 100).map((i, r) => ({
    rank: r + 1,
    node_id: m.nodeIds[i],
    vertex: i,
    x: +m.x[i * 3].toFixed(3),
    y: +m.x[i * 3 + 1].toFixed(3),
    z: +m.x[i * 3 + 2].toFixed(3),
    fx: f[i * 3],
    fy: f[i * 3 + 1],
    fz: f[i * 3 + 2],
    mag: fmag[i],
    fn: fn[i],
    pa: pa[i],
    is_support: supportSet.has(i),
  }));
  const sum_f = [0, 0, 0];
  const c0 = [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2];
  const sum_m = [0, 0, 0];
  for (let i = 0; i < n; i++) {
    const r = cross([m.x[i * 3] - c0[0], m.x[i * 3 + 1] - c0[1], m.x[i * 3 + 2] - c0[2]], [f[i * 3], f[i * 3 + 1], f[i * 3 + 2]]);
    for (let c = 0; c < 3; c++) {
      sum_f[c] += f[i * 3 + c];
      sum_m[c] += r[c];
    }
  }
  const clusters: View3dOut["clusters"] = {};
  for (const K of [2, 3, 4, 5]) clusters[String(K)] = weightedClusters(m.x, f, u, m.nodeIds, K);
  const umax = Math.max(...Array.from({ length: n }, (_, i) => Math.hypot(u[i * 3], u[i * 3 + 1], u[i * 3 + 2])));
  const built: MockView3d = {
    glb,
    values: packed.buf,
    manifest: (runId) => ({
      schema: "esl/view3d/1",
      builder_version: 1,
      key: "mock0123456789ab",
      esl_run_id: runId,
      n_nodes: n,
      n_elems: m.quads.length,
      n_tris: m.indices.length / 3,
      units: "mm",
      force_unit: "N",
      pressure_unit: "MPa",
      up: "Z",
      bbox: { min: mn, max: mx, diag },
      plate_normal: [0, 0, 1],
      geometry: { name: "part.glb", bytes: glb.byteLength },
      lod: null,
      values: { name: "values.bin", bytes: packed.buf.byteLength, arrays: packed.arrays },
      ranges: { fn_abs: { max: Math.max(...Array.from(fn).map(Math.abs)), p99: p99(fn.map(Math.abs)) }, fmag_max: fmag[order[0]], u_max: umax, pa: { max: Math.max(...pa), p99: p99(pa) } },
      sum_f,
      sum_m,
      moment_center: c0,
      supports: supVerts.map((v, k) => ({ node_id: m.nodeIds[v], vertex: v, dof: supDof[k], x0: [m.x[v * 3], m.x[v * 3 + 1], m.x[v * 3 + 2]] })),
      top,
      clusters,
      geometry_url: `/esl-runs/${runId}/view3d/part.glb`,
      lod_url: null,
      values_url: `/esl-runs/${runId}/view3d/values.bin`,
      created_at: "2026-10-28T03:00:00Z",
    }),
  };
  cache = built;
  return built;
}
