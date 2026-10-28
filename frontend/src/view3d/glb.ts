// GLB 해석(계약 §3.3): glTF 2.0 바이너리, KHR_mesh_quantization(SHORT normalized POSITION, 노드 translation·scale), _NODE_ID/_SRC(UNSIGNED_INT), 인덱스 UNSIGNED_INT.
// 위치는 1회 float32 mm(전역 좌표, Z-up)로 복원한다. three 없이 동작하는 순수 함수 — GLTFLoader.parseAsync 와 같은 결과(시험에서 대조).
export interface ParsedGlb {
  /** float32 mm, 길이 3n */
  positions: Float32Array;
  indices: Uint32Array;
  /** _NODE_ID (정점 i = 노드 i) */
  nodeIds: Uint32Array | null;
  /** _SRC (LOD: 원 정점 번호) */
  src: Uint32Array | null;
  extras: { units?: string; up?: string; generator?: string } | null;
}

interface Json {
  asset?: { extras?: ParsedGlb["extras"] };
  accessors: { bufferView: number; byteOffset?: number; componentType: number; normalized?: boolean; count: number; type: string }[];
  bufferViews: { buffer: number; byteOffset?: number; byteLength: number; byteStride?: number }[];
  meshes: { primitives: { attributes: Record<string, number>; indices?: number }[] }[];
  nodes?: { mesh?: number; translation?: number[]; scale?: number[]; rotation?: number[]; matrix?: number[] }[];
}

const COMP_BYTES: Record<number, number> = { 5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4 };
const TYPE_COMPS: Record<string, number> = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };

export function parseGlb(buf: ArrayBuffer): ParsedGlb {
  const dv = new DataView(buf);
  if (buf.byteLength < 20 || dv.getUint32(0, true) !== 0x46546c67) throw new Error("GLB: 헤더(glTF)가 아닙니다");
  if (dv.getUint32(4, true) !== 2) throw new Error("GLB: glTF 2.0 이 아닙니다");
  let off = 12;
  let json: Json | null = null;
  let bin: { start: number; len: number } | null = null;
  while (off + 8 <= buf.byteLength) {
    const len = dv.getUint32(off, true);
    const type = dv.getUint32(off + 4, true);
    if (type === 0x4e4f534a) json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, off + 8, len)));
    else if (type === 0x004e4942 && !bin) bin = { start: off + 8, len };
    off += 8 + len;
  }
  if (!json || !bin) throw new Error("GLB: JSON/BIN 청크가 없습니다");
  const g = json;
  const b = bin;

  const read = (idx: number): { data: ArrayLike<number>; count: number; comps: number; normalized: boolean; ct: number } => {
    const a = g.accessors[idx];
    const bv = g.bufferViews[a.bufferView];
    const comps = TYPE_COMPS[a.type];
    const cb = COMP_BYTES[a.componentType];
    if (!comps || !cb) throw new Error("GLB: 지원하지 않는 accessor");
    const stride = bv.byteStride ?? comps * cb;
    const start = b.start + (bv.byteOffset ?? 0) + (a.byteOffset ?? 0);
    if (start + (a.count - 1) * stride + comps * cb > b.start + b.len) throw new Error("GLB: accessor 가 BIN 범위를 벗어납니다");
    const out = new Float64Array(a.count * comps);
    const d = new DataView(buf);
    for (let i = 0; i < a.count; i++)
      for (let c = 0; c < comps; c++) {
        const p = start + i * stride + c * cb;
        let v: number;
        switch (a.componentType) {
          case 5120: v = d.getInt8(p); break;
          case 5121: v = d.getUint8(p); break;
          case 5122: v = d.getInt16(p, true); break;
          case 5123: v = d.getUint16(p, true); break;
          case 5125: v = d.getUint32(p, true); break;
          default: v = d.getFloat32(p, true);
        }
        out[i * comps + c] = v;
      }
    return { data: out, count: a.count, comps, normalized: !!a.normalized, ct: a.componentType };
  };
  const readUint = (idx: number): Uint32Array => {
    const r = read(idx);
    const out = new Uint32Array(r.count * r.comps);
    for (let i = 0; i < out.length; i++) out[i] = r.data[i];
    return out;
  };

  const prim = g.meshes?.[0]?.primitives?.[0];
  if (!prim || prim.attributes.POSITION === undefined || prim.indices === undefined) throw new Error("GLB: POSITION/인덱스가 없습니다");
  const pos = read(prim.attributes.POSITION);
  // 정규화 정수 → [-1, 1] (glTF 규칙), 노드 변환(scale → translation)으로 mm 복원
  const node = g.nodes?.find((n) => n.mesh === 0) ?? g.nodes?.[0];
  const t = node?.translation ?? [0, 0, 0];
  const s = node?.scale ?? [1, 1, 1];
  const norm = (v: number): number => {
    if (!pos.normalized) return v;
    switch (pos.ct) {
      case 5122: return Math.max(v / 32767, -1);
      case 5123: return v / 65535;
      case 5120: return Math.max(v / 127, -1);
      case 5121: return v / 255;
      default: return v;
    }
  };
  const positions = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) for (let c = 0; c < 3; c++) positions[i * 3 + c] = norm(pos.data[i * pos.comps + c]) * s[c] + t[c];
  return {
    positions,
    indices: readUint(prim.indices),
    nodeIds: prim.attributes._NODE_ID !== undefined ? readUint(prim.attributes._NODE_ID) : null,
    src: prim.attributes._SRC !== undefined ? readUint(prim.attributes._SRC) : null,
    extras: g.asset?.extras ?? null,
  };
}
