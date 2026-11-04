// 선택 보기 자료(esl_bead_select.md §8.1): select.bin = 섹션 tri2elem(u32×n_tris) · elem_id(u32×n_elems) · elem_type(u8×n_elems, 4 = /SHELL, 3 = /SH3N) · fixed(u8×n_nodes).
// 리틀 엔디언, 각 섹션은 4바이트 경계로 0 채움. 섹션 위치는 코어(bead_select.view_files)가 쓴 manifest `bin.layout[{name, dtype, offset, count}]` 를 그대로 따른다.
import type { DoeSelectBinSection, DoeSelectViewManifest } from "../../api/types";

export interface SelectBin {
  tri2elem: Uint32Array;
  elemId: Uint32Array;
  elemType: Uint8Array;
  fixed: Uint8Array;
}

type Field = keyof SelectBin;
type Count = "n_tris" | "n_elems" | "n_nodes";
/** 섹션 이름 → 필드·dtype(numpy dtype.str, '|' 제거)·기대 개수(manifest 의 n_*) — 코어 view_files 순서 */
const SECTIONS: { name: string; field: Field; dtype: "<u4" | "u1"; count: Count }[] = [
  { name: "tri2elem", field: "tri2elem", dtype: "<u4", count: "n_tris" },
  { name: "elem_id", field: "elemId", dtype: "<u4", count: "n_elems" },
  { name: "elem_type", field: "elemType", dtype: "u1", count: "n_elems" },
  { name: "fixed", field: "fixed", dtype: "u1", count: "n_nodes" },
];
const ALIGN = 4;
const itemSize = (dtype: string) => (dtype === "<u4" ? 4 : 1);
const padded = (n: number) => n + ((ALIGN - (n % ALIGN)) % ALIGN);

export type SelectBinManifest = Pick<DoeSelectViewManifest, Count | "bin">;

export function parseSelectBin(buf: ArrayBuffer, m: SelectBinManifest): SelectBin {
  const layout = m.bin?.layout;
  if (!Array.isArray(layout)) throw new Error("select_manifest.json 에 bin.layout 이 없습니다");
  if (buf.byteLength !== m.bin.bytes) throw new Error(`select.bin 길이 ${buf.byteLength} ≠ ${m.bin.bytes}(manifest)`);
  const dv = new DataView(buf);
  const out = {} as Record<Field, Uint32Array | Uint8Array>;
  for (const s of SECTIONS) {
    const L = layout.find((x) => x.name === s.name);
    if (!L) throw new Error(`select.bin: 섹션 ${s.name} 이 manifest 에 없습니다`);
    if (L.dtype !== s.dtype) throw new Error(`select.bin: 섹션 ${s.name} 형식 ${L.dtype} ≠ ${s.dtype}`);
    if (L.count !== m[s.count]) throw new Error(`select.bin: 섹션 ${s.name} 개수 ${L.count} ≠ ${s.count} ${m[s.count]}`);
    const size = itemSize(L.dtype);
    if (L.offset % ALIGN !== 0 || L.offset + L.count * size > buf.byteLength) throw new Error(`select.bin 길이·위치가 섹션 ${s.name} 과 맞지 않습니다`);
    if (size === 4) {
      const a = new Uint32Array(L.count);
      for (let i = 0; i < L.count; i++) a[i] = dv.getUint32(L.offset + i * 4, true);
      out[s.field] = a;
    } else out[s.field] = new Uint8Array(buf.slice(L.offset, L.offset + L.count));
  }
  const b = out as unknown as SelectBin;
  for (const e of b.tri2elem) if (e >= m.n_elems) throw new Error("select.bin: 삼각형→요소 번호가 범위를 벗어납니다");
  return b;
}

/** select.bin 쓰기(목·시험용 — 코어 view_files 와 같은 배치: 섹션 순서·4바이트 채움) + manifest 의 bin 항목 */
export function writeSelectBin(b: SelectBin): { buf: ArrayBuffer; bin: DoeSelectViewManifest["bin"] } {
  const layout: DoeSelectBinSection[] = [];
  let off = 0;
  for (const s of SECTIONS) {
    const n = b[s.field].length;
    layout.push({ name: s.name, dtype: s.dtype, offset: off, count: n });
    off += padded(n * itemSize(s.dtype));
  }
  const buf = new ArrayBuffer(off);
  const dv = new DataView(buf);
  SECTIONS.forEach((s, k) => {
    const a = b[s.field];
    const o = layout[k].offset;
    if (itemSize(s.dtype) === 4) a.forEach((v, i) => dv.setUint32(o + i * 4, v, true));
    else new Uint8Array(buf, o, a.length).set(a);
  });
  return { buf, bin: { name: "select.bin", bytes: off, layout } };
}

/** 노드 고정 마스크 → 고정 노드를 하나라도 쓰는 요소(고정 층 표시용) */
export function fixedElems(fixed: Uint8Array, elemNodesPtr: Uint32Array, elemNodes: Uint32Array): Uint8Array {
  const n = elemNodesPtr.length - 1;
  const out = new Uint8Array(n);
  for (let e = 0; e < n; e++)
    for (let k = elemNodesPtr[e]; k < elemNodesPtr[e + 1]; k++)
      if (fixed[elemNodes[k]]) {
        out[e] = 1;
        break;
      }
  return out;
}
