// 선택 보기 자료(esl_bead_select.md §8.1): select.bin = [tri2elem u32×n_tris][elem_id u32×n_elems][elem_type u8×n_elems(4 = /SHELL, 3 = /SH3N)][fixed u8×n_nodes].
// 리틀 엔디언, 사이 채움 없음(u32 배열이 앞이라 정렬 문제 없음). manifest(select_manifest.json) 의 n_tris·n_elems·n_nodes 로 길이를 검사한다.
import type { DoeSelectViewManifest } from "../../api/types";

export interface SelectBin {
  tri2elem: Uint32Array;
  elemId: Uint32Array;
  elemType: Uint8Array;
  fixed: Uint8Array;
}

export function parseSelectBin(buf: ArrayBuffer, m: Pick<DoeSelectViewManifest, "n_tris" | "n_elems" | "n_nodes">): SelectBin {
  const need = m.n_tris * 4 + m.n_elems * 5 + m.n_nodes;
  if (buf.byteLength !== need) throw new Error(`select.bin 길이 ${buf.byteLength} ≠ ${need}(manifest)`);
  const dv = new DataView(buf);
  const tri2elem = new Uint32Array(m.n_tris);
  for (let i = 0; i < m.n_tris; i++) tri2elem[i] = dv.getUint32(i * 4, true);
  let off = m.n_tris * 4;
  const elemId = new Uint32Array(m.n_elems);
  for (let i = 0; i < m.n_elems; i++) elemId[i] = dv.getUint32(off + i * 4, true);
  off += m.n_elems * 4;
  const elemType = new Uint8Array(buf.slice(off, off + m.n_elems));
  off += m.n_elems;
  const fixed = new Uint8Array(buf.slice(off, off + m.n_nodes));
  for (const e of tri2elem) if (e >= m.n_elems) throw new Error("select.bin: 삼각형→요소 번호가 범위를 벗어납니다");
  return { tri2elem, elemId, elemType, fixed };
}

export function writeSelectBin(b: SelectBin): ArrayBuffer {
  const buf = new ArrayBuffer(b.tri2elem.length * 4 + b.elemId.length * 5 + b.fixed.length);
  const dv = new DataView(buf);
  b.tri2elem.forEach((v, i) => dv.setUint32(i * 4, v, true));
  let off = b.tri2elem.length * 4;
  b.elemId.forEach((v, i) => dv.setUint32(off + i * 4, v, true));
  off += b.elemId.length * 4;
  new Uint8Array(buf, off, b.elemType.length).set(b.elemType);
  off += b.elemType.length;
  new Uint8Array(buf, off, b.fixed.length).set(b.fixed);
  return buf;
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
