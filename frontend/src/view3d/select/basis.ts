// 선형 기저 모핑(esl_bead_select.md BS-D-9·§7.3·§9): u = Σ_v (v − v_nom)·B_v. 워커와 같은 식이라 float32 오차(≤ 1e-4 mm) 외 같다(V-BS-12).
// basis.bin = 변수 순서(basis.json `vars`) 대로 [n:u32][idx:u32×n][vec:f32×3n] 이어 붙임(리틀 엔디언).
import type { DoeBasisMeta } from "../../api/types";

export interface BasisVar {
  name: string;
  bead: string;
  type: "D" | "W";
  nominal: number;
  idx: Uint32Array;
  vec: Float32Array;
}

export function parseBasis(buf: ArrayBuffer, meta: DoeBasisMeta): BasisVar[] {
  const dv = new DataView(buf);
  let off = 0;
  const out: BasisVar[] = [];
  for (const v of meta.vars) {
    if (off + 4 > buf.byteLength) throw new Error("기저 파일이 짧습니다");
    const n = dv.getUint32(off, true);
    off += 4;
    if (n !== v.n) throw new Error(`기저 ${v.name}: 노드 수가 basis.json 과 다릅니다`);
    if (off + n * 16 > buf.byteLength) throw new Error("기저 파일이 짧습니다");
    const idx = new Uint32Array(n);
    for (let i = 0; i < n; i++) idx[i] = dv.getUint32(off + i * 4, true);
    off += n * 4;
    const vec = new Float32Array(n * 3);
    for (let i = 0; i < n * 3; i++) vec[i] = dv.getFloat32(off + i * 4, true);
    off += n * 12;
    out.push({ name: v.name, bead: v.bead, type: v.type, nominal: v.nominal, idx, vec });
  }
  if (off !== buf.byteLength) throw new Error("기저 파일 길이가 basis.json 과 다릅니다");
  return out;
}

/** basis.bin 쓰기(목·시험용 — 워커와 같은 형식) */
export function writeBasis(vars: { idx: ArrayLike<number>; vec: ArrayLike<number> }[]): ArrayBuffer {
  const size = vars.reduce((s, v) => s + 4 + v.idx.length * 16, 0);
  const buf = new ArrayBuffer(size);
  const dv = new DataView(buf);
  let off = 0;
  for (const v of vars) {
    dv.setUint32(off, v.idx.length, true);
    off += 4;
    for (let i = 0; i < v.idx.length; i++) dv.setUint32(off + i * 4, v.idx[i], true);
    off += v.idx.length * 4;
    for (let i = 0; i < v.idx.length * 3; i++) dv.setFloat32(off + i * 4, v.vec[i], true);
    off += v.idx.length * 12;
  }
  return buf;
}

/** u(3·nNodes, float32) = Σ (values[v] − nominal)·B_v. 값이 없는 변수 = 공칭(기여 0) */
export function morph(vars: BasisVar[], values: Record<string, number>, nNodes: number): Float32Array {
  const u = new Float64Array(nNodes * 3);
  for (const v of vars) {
    const x = values[v.name];
    if (x === undefined) continue;
    const d = x - v.nominal;
    if (d === 0) continue;
    for (let i = 0; i < v.idx.length; i++) {
      const j = v.idx[i] * 3;
      u[j] += d * v.vec[i * 3];
      u[j + 1] += d * v.vec[i * 3 + 1];
      u[j + 2] += d * v.vec[i * 3 + 2];
    }
  }
  return Float32Array.from(u);
}

/**
 * 비드 방향 n̂_b(깊어짐 +): basis.json 에 n̂_b 가 없으므로 그 비드 깊이 기저(B_D, 바닥 노드 = 단 법선)의 3D 벡터 합을 정규화한다.
 * 깊이 변수가 없는 비드는 없음(색 0).
 */
export function beadDirections(vars: BasisVar[]): Map<string, [number, number, number]> {
  const acc = new Map<string, [number, number, number]>();
  for (const v of vars) {
    if (v.type !== "D") continue;
    const a = acc.get(v.bead) ?? [0, 0, 0];
    for (let i = 0; i < v.idx.length; i++) for (let c = 0; c < 3; c++) a[c] += v.vec[i * 3 + c];
    acc.set(v.bead, a);
  }
  const out = new Map<string, [number, number, number]>();
  for (const [b, a] of acc) {
    const L = Math.hypot(a[0], a[1], a[2]);
    if (L > 0) out.set(b, [a[0] / L, a[1] / L, a[2] / L]);
  }
  return out;
}

/**
 * 색 값(§7.2): c_i = 비드 방향 n̂_b 성분(깊어짐 +). 비드 b 기저의 영향 노드에서만 그 비드 방향으로 재고, 그 밖 노드는 0.
 * 여러 비드가 겹치는 노드는 비드별 성분 합.
 */
export function heightChange(vars: BasisVar[], values: Record<string, number>, nNodes: number): Float32Array {
  const c = new Float64Array(nNodes);
  const dirs = beadDirections(vars);
  for (const v of vars) {
    const x = values[v.name];
    const nb = dirs.get(v.bead);
    if (x === undefined || !nb) continue;
    const d = x - v.nominal;
    for (let i = 0; i < v.idx.length; i++) c[v.idx[i]] += d * (v.vec[i * 3] * nb[0] + v.vec[i * 3 + 1] * nb[1] + v.vec[i * 3 + 2] * nb[2]);
  }
  return Float32Array.from(c);
}

export function maxAbs(a: ArrayLike<number>): number {
  let m = 0;
  for (let i = 0; i < a.length; i++) m = Math.max(m, Math.abs(a[i]));
  return m;
}
