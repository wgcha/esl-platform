// 선택 층(esl_bead_select.md §4.1·§11.2): 층 = 비드 b 의 단 k 바닥 | 비드 b 사면(자동 결과에 더하기·빼기) | 고정 | 제외.
// 규칙: 한 요소는 최대 1 개 비드·1 개 층(단 바닥|사면 더하기) — 다른 비드 요소는 덮어쓰지 않는다. 고정·제외는 비드 층과 겹칠 수 있다.
// 상태는 요소 번호(select.bin 순서) 색인 Int32Array — 칠하기 1획 = History 패치 1개.
import type { DoeBeadSel, DoeSelectionIn } from "../../api/types";
import type { Patch } from "./history";
import { EMPTY_SET, fromElemSet, toElemSet, type ElemIndex } from "./ranges";

export type LayerName = "owner" | "remove" | "fixed" | "exclude";
export type Layer = { kind: "tier"; bead: number; k: number } | { kind: "slope"; bead: number } | { kind: "fixed" } | { kind: "exclude" };

/** owner 값 = bead·16 + (0 = 사면 더하기, k = 단 k 바닥), 없음 = −1 */
export const SLOPE = 0;
export const ownerCode = (bead: number, code: number) => bead * 16 + code;
export const ownerBead = (v: number) => (v < 0 ? -1 : Math.floor(v / 16));
export const ownerLayer = (v: number) => (v < 0 ? -1 : v % 16);

export interface BeadMeta {
  id: string;
  name: string;
  nTiers: number;
  blend: "auto" | number;
  floorFollow: 0 | 1;
  links: number[][];
}

export interface SelState {
  nElems: number;
  beads: BeadMeta[];
  owner: Int32Array;
  /** 자동 사면에서 빼라고 한 요소 → 비드 번호(−1 없음) */
  remove: Int32Array;
  fixed: Int32Array;
  exclude: Int32Array;
}

export function emptyState(nElems: number): SelState {
  return { nElems, beads: [], owner: new Int32Array(nElems).fill(-1), remove: new Int32Array(nElems).fill(-1), fixed: new Int32Array(nElems), exclude: new Int32Array(nElems) };
}

export const MAX_BEADS = 20;

/** 비어 있는 가장 작은 b<n> 으로 비드 추가(이름 기본 "B<n>"). 상한이면 null */
export function addBead(s: SelState, maxBeads = MAX_BEADS, floorFollow: 0 | 1 = 1): number | null {
  if (s.beads.length >= maxBeads) return null;
  let n = 1;
  while (s.beads.some((b) => b.id === `b${n}`)) n++;
  s.beads.push({ id: `b${n}`, name: `B${n}`, nTiers: 1, blend: "auto", floorFollow, links: [] });
  return s.beads.length - 1;
}

/** 단 추가(연속 번호, 상한 maxTiers). 새 단 번호 또는 null */
export function addTier(s: SelState, bead: number, maxTiers: number): number | null {
  const b = s.beads[bead];
  if (!b || b.nTiers >= maxTiers) return null;
  b.nTiers += 1;
  return b.nTiers;
}

/** 단 묶기·풀기(같은 깊이 값 — 묶음 겹침 없음). 이미 같은 묶음이면 a 를 묶음에서 뺀다 */
export function toggleLink(b: BeadMeta, a: number, c: number) {
  if (a === c) return;
  const ga = b.links.find((g) => g.includes(a));
  const gc = b.links.find((g) => g.includes(c));
  if (ga && ga === gc) {
    const rest = ga.filter((k) => k !== a);
    b.links = b.links.filter((g) => g !== ga);
    if (rest.length > 1) b.links.push(rest);
  } else {
    const merged = [...new Set([...(ga ?? [a]), ...(gc ?? [c])])].sort((x, y) => x - y);
    b.links = [...b.links.filter((g) => g !== ga && g !== gc), merged].sort((x, y) => x[0] - y[0]);
  }
}

/**
 * 칠하기: elems 를 층에 더하기(add) 또는 빼기(remove). suggested(bead) = 그 비드 자동 사면(요소 번호 1 = 자동 사면) — 사면 층 빼기에서
 * 자동 사면 요소는 remove 로 표시한다. 바뀐 값만 담은 패치를 돌려준다(상태는 바로 바뀜).
 */
export function paint(s: SelState, elems: ArrayLike<number>, layer: Layer, mode: "add" | "remove", suggested?: (bead: number) => Uint8Array | null): Patch<LayerName> {
  const ch: Record<LayerName, { idx: number[]; before: number[]; after: number[] }> = {
    owner: { idx: [], before: [], after: [] },
    remove: { idx: [], before: [], after: [] },
    fixed: { idx: [], before: [], after: [] },
    exclude: { idx: [], before: [], after: [] },
  };
  const set = (name: LayerName, e: number, v: number) => {
    const arr = s[name];
    if (arr[e] === v) return;
    ch[name].idx.push(e);
    ch[name].before.push(arr[e]);
    ch[name].after.push(v);
    arr[e] = v;
  };
  for (let i = 0; i < elems.length; i++) {
    const e = elems[i];
    if (e < 0 || e >= s.nElems) continue;
    if (layer.kind === "fixed" || layer.kind === "exclude") {
      set(layer.kind, e, mode === "add" ? 1 : 0);
      continue;
    }
    const code = ownerCode(layer.bead, layer.kind === "tier" ? layer.k : SLOPE);
    const cur = s.owner[e];
    const other = cur >= 0 && ownerBead(cur) !== layer.bead;
    if (mode === "add") {
      if (other) continue; // 다른 비드 요소는 그대로(겹침 금지)
      set("owner", e, code);
      if (s.remove[e] === layer.bead) set("remove", e, -1);
    } else if (layer.kind === "tier") {
      if (cur === code) set("owner", e, -1);
    } else {
      if (cur === code) set("owner", e, -1);
      else if (!other && cur < 0 && suggested?.(layer.bead)?.[e]) set("remove", e, layer.bead);
    }
  }
  return {
    changes: (Object.keys(ch) as LayerName[])
      .filter((k) => ch[k].idx.length)
      .map((k) => ({ layer: k, idx: Uint32Array.from(ch[k].idx), before: Int32Array.from(ch[k].before), after: Int32Array.from(ch[k].after) })),
  };
}

/** 패치 되돌리기(undo = before) / 다시(redo = after) */
export function applyPatch(s: SelState, p: Patch<LayerName>, dir: "undo" | "redo") {
  for (const c of p.changes) {
    const arr = s[c.layer as LayerName];
    const v = dir === "undo" ? c.before : c.after;
    for (let i = 0; i < c.idx.length; i++) arr[c.idx[i]] = v[i];
  }
}

/** 비드 b 에 속한 요소(바닥 전부 + 사면 더하기) */
export const inBead = (s: SelState, bead: number) => (e: number) => ownerBead(s.owner[e]) === bead;

/** 비드 b 의 최종 사면(§5.2-4) = (자동 ∪ 더하기) ∖ 빼기 ∖ 제외 — 다른 비드 요소·바닥은 빠짐 */
export function effectiveSlope(s: SelState, bead: number, suggested: Uint8Array | null): Uint8Array {
  const out = new Uint8Array(s.nElems);
  const code = ownerCode(bead, SLOPE);
  for (let e = 0; e < s.nElems; e++) {
    const o = s.owner[e];
    const auto = !!suggested?.[e] && o < 0;
    if ((o === code || auto) && s.remove[e] !== bead && !s.exclude[e]) out[e] = 1;
  }
  return out;
}

export function counts(s: SelState, bead: number): { tiers: number[]; slopeAdd: number; slopeRemove: number } {
  const b = s.beads[bead];
  const tiers = new Array<number>(b ? b.nTiers : 0).fill(0);
  let slopeAdd = 0;
  let slopeRemove = 0;
  for (let e = 0; e < s.nElems; e++) {
    const o = s.owner[e];
    if (ownerBead(o) === bead) {
      const l = ownerLayer(o);
      if (l === SLOPE) slopeAdd++;
      else if (l - 1 < tiers.length) tiers[l - 1]++;
    }
    if (s.remove[e] === bead) slopeRemove++;
  }
  return { tiers, slopeAdd, slopeRemove };
}

/** 화면 상태 → SelectionIn(§4.1). 빈 단도 그대로 넣는다(서버가 SELECT_EMPTY_TIER 로 거름) */
export function toSelectionIn(s: SelState, elemId: ArrayLike<number>, elemType: ArrayLike<number>, featureAngle: number): DoeSelectionIn {
  const lists = (pred: (e: number) => boolean) => {
    const out: number[] = [];
    for (let e = 0; e < s.nElems; e++) if (pred(e)) out.push(e);
    return toElemSet(out, elemId, elemType);
  };
  const beads: DoeBeadSel[] = s.beads.map((b, bi) => {
    const add = lists((e) => s.owner[e] === ownerCode(bi, SLOPE));
    const remove = lists((e) => s.remove[e] === bi);
    const edited = add.q.length + add.t.length + remove.q.length + remove.t.length > 0;
    return {
      id: b.id,
      name: b.name,
      tiers: Array.from({ length: b.nTiers }, (_, i) => ({ k: i + 1, floor: lists((e) => s.owner[e] === ownerCode(bi, i + 1)) })),
      slope: { mode: edited ? "edited" : "auto", add, remove },
      blend_mm: b.blend,
      floor_follow: b.floorFollow,
      links: b.links.map((g) => [...g]),
    };
  });
  return { schema_version: 1, feature_angle_deg: featureAngle, beads, fixed_user: lists((e) => !!s.fixed[e]), exclude: lists((e) => !!s.exclude[e]) };
}

/** SelectionIn → 화면 상태(저장된 선택 불러오기). 메시에 없는 ID 수 = unknown */
export function fromSelectionIn(sel: DoeSelectionIn, idx: ElemIndex, nElems: number): { state: SelState; unknown: number } {
  const s = emptyState(nElems);
  let unknown = 0;
  const take = (set: DoeBeadSel["slope"]["add"] | undefined, fn: (e: number) => void) => {
    const r = fromElemSet(set ?? EMPTY_SET(), idx);
    unknown += r.unknown;
    r.elems.forEach(fn);
  };
  sel.beads.forEach((b, bi) => {
    s.beads.push({ id: b.id, name: b.name, nTiers: Math.max(1, b.tiers.length), blend: b.blend_mm, floorFollow: b.floor_follow, links: b.links.map((g) => [...g]) });
    for (const t of b.tiers) take(t.floor, (e) => (s.owner[e] = ownerCode(bi, t.k)));
    take(b.slope.add, (e) => (s.owner[e] = ownerCode(bi, SLOPE)));
    take(b.slope.remove, (e) => (s.remove[e] = bi));
  });
  take(sel.fixed_user, (e) => (s.fixed[e] = 1));
  take(sel.exclude, (e) => (s.exclude[e] = 1));
  return { state: s, unknown };
}

// ---------------------------------------------------------------- 요소 색(sRGB 8비트, §11.2)
export const COLOR_NONE: [number, number, number] = [196, 200, 206];
export const COLOR_SLOPE: [number, number, number] = [240, 140, 0];
export const COLOR_SLOPE_AUTO: [number, number, number] = [247, 190, 110];
export const COLOR_FIXED: [number, number, number] = [84, 90, 100];
export const COLOR_EXCLUDE: [number, number, number] = [226, 222, 214];
/** 단 k 파랑 계열 명도 단계(1 = 가장 진함) */
export function tierColor(k: number): [number, number, number] {
  const steps: [number, number, number][] = [[29, 91, 191], [66, 133, 214], [107, 168, 230], [150, 196, 238], [41, 72, 140], [90, 150, 200]];
  return steps[(k - 1) % steps.length];
}
const mix = (a: [number, number, number], b: [number, number, number], t: number): [number, number, number] => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

/** 요소별 RGBA(길이 4·nElems). active = 지금 고치는 비드(그 밖 비드는 흐리게), suggested(b) = 비드 b 자동 사면 */
export function elemColors(s: SelState, active: number, suggested: (bead: number) => Uint8Array | null): Uint8Array {
  const out = new Uint8Array(s.nElems * 4);
  const sug = s.beads.map((_, b) => suggested(b));
  for (let e = 0; e < s.nElems; e++) {
    const o = s.owner[e];
    let c = COLOR_NONE;
    let bead = ownerBead(o);
    if (o >= 0) c = ownerLayer(o) === SLOPE ? COLOR_SLOPE : tierColor(ownerLayer(o));
    else {
      const b = sug.findIndex((m, bi) => !!m?.[e] && s.remove[e] !== bi);
      if (b >= 0 && !s.exclude[e]) {
        c = COLOR_SLOPE_AUTO;
        bead = b;
      } else if (s.exclude[e]) c = COLOR_EXCLUDE;
    }
    if (s.fixed[e]) c = COLOR_FIXED;
    if (bead >= 0 && bead !== active && !s.fixed[e]) c = mix(c, COLOR_NONE, 0.55);
    out[e * 4] = Math.round(c[0]);
    out[e * 4 + 1] = Math.round(c[1]);
    out[e * 4 + 2] = Math.round(c[2]);
    out[e * 4 + 3] = 255;
  }
  return out;
}
