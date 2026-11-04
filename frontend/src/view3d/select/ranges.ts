// 요소 집합 구간 압축(esl_bead_select.md §4.1·BS-D-4): 서버 정규화와 같은 규칙 — 정렬·중복 제거·인접(+1)·겹침 병합, 닫힌 구간 [first, last].
// ElemSet = {q: 4각, t: 3각} — 두 ID 공간이 따로일 수 있어 종류별로 압축한다.
import type { DoeElemSet, DoeRanges } from "../../api/types";

/** 정수 ID 목록 → 정규화 구간 */
export function compress(ids: ArrayLike<number>): DoeRanges {
  const a = Array.from(ids).sort((x, y) => x - y);
  const out: DoeRanges = [];
  for (const v of a) {
    const last = out[out.length - 1];
    if (last && v <= last[1] + 1) last[1] = Math.max(last[1], v);
    else out.push([v, v]);
  }
  return out;
}

/** 구간(정렬·겹침 여부 무관) → 정규화 구간 */
export function normalizeRanges(r: DoeRanges): DoeRanges {
  const a = r.map(([x, y]) => [Math.min(x, y), Math.max(x, y)] as [number, number]).sort((p, q) => p[0] - q[0] || p[1] - q[1]);
  const out: DoeRanges = [];
  for (const [x, y] of a) {
    const last = out[out.length - 1];
    if (last && x <= last[1] + 1) last[1] = Math.max(last[1], y);
    else out.push([x, y]);
  }
  return out;
}

export function expand(r: DoeRanges): number[] {
  const out: number[] = [];
  for (const [x, y] of r) for (let v = x; v <= y; v++) out.push(v);
  return out;
}

export const rangesCount = (r: DoeRanges) => r.reduce((s, [x, y]) => s + y - x + 1, 0);
export const EMPTY_SET = (): DoeElemSet => ({ q: [], t: [] });
export const elemSetCount = (s: DoeElemSet) => rangesCount(s.q) + rangesCount(s.t);
export const normalizeElemSet = (s: DoeElemSet): DoeElemSet => ({ q: normalizeRanges(s.q), t: normalizeRanges(s.t) });

/** 요소 번호(select.bin 순서) 목록 → ElemSet. elemId[e]·elemType[e](4 = /SHELL, 3 = /SH3N) */
export function toElemSet(elems: ArrayLike<number>, elemId: ArrayLike<number>, elemType: ArrayLike<number>): DoeElemSet {
  const q: number[] = [];
  const t: number[] = [];
  for (let i = 0; i < elems.length; i++) {
    const e = elems[i];
    (elemType[e] === 3 ? t : q).push(elemId[e]);
  }
  return { q: compress(q), t: compress(t) };
}

/** (종류, ID) → 요소 번호 표 */
export interface ElemIndex {
  q: Map<number, number>;
  t: Map<number, number>;
}
export function elemIndex(elemId: ArrayLike<number>, elemType: ArrayLike<number>): ElemIndex {
  const q = new Map<number, number>();
  const t = new Map<number, number>();
  for (let e = 0; e < elemId.length; e++) (elemType[e] === 3 ? t : q).set(elemId[e], e);
  return { q, t };
}
/** ElemSet → 요소 번호(오름차순). 메시에 없는 ID 는 unknown 으로 */
export function fromElemSet(s: DoeElemSet, idx: ElemIndex): { elems: number[]; unknown: number } {
  const out: number[] = [];
  let unknown = 0;
  for (const kind of ["q", "t"] as const)
    for (const [x, y] of s[kind])
      for (let v = x; v <= y; v++) {
        const e = idx[kind].get(v);
        if (e === undefined) unknown++;
        else out.push(e);
      }
  return { elems: out.sort((a, b) => a - b), unknown };
}
