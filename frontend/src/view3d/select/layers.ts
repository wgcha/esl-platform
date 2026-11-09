// 선택 층(esl_bead_select.md §4.1·§11.2): 층 = 비드 b 의 단 k 바닥 | 비드 b 사면(자동 결과에 더하기·빼기) | 고정 | 제외.
// 규칙: 한 요소는 최대 1 개 비드·1 개 층(단 바닥|사면 더하기) — 다른 비드 요소는 덮어쓰지 않는다. 고정·제외는 비드 층과 겹칠 수 있다.
// 상태는 요소 번호(select.bin 순서) 색인 Int32Array — 칠하기 1획 = History 패치 1개.
import type { BgEdits, BgSegRef, DoeBeadSel, DoeBeadSelElems, DoeBeadSelGraph, DoeSelectionAny, DoeSelectionIn, DoeSelectionV2 } from "../../api/types";
import type { MeshTopo } from "./adjacency";
import { networkAnchor, refKey, repOf, resolveRef, sortRefs, editView, type GraphIndex } from "./graph";
import { enclosedComponents, outerPolygons, type Island, type Vec3 } from "./grow";
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
  /** v0.16.1 체결 구멍 둘레 고정(SR-D-9) — 0 이면 SelectionIn 에 키를 쓰지 않음(SR-D-13a). v0.17.0 그래프 비드 기본 1 */
  holdFixed: 0 | 1;
  /** v0.17.0 schema 2 출처(없음 = elems — 칠하기 비드) */
  src?: "graph";
  /** v0.17.0 그래프 비드 세그먼트 참조(앵커 | 네트워크) */
  segs?: BgSegRef[];
  /** v0.17.0 변수(없음 = 가능한 것 전부) */
  vars?: ("D" | "W")[];
}

/** v0.17.0 그래프 편집 빈 값 */
export const emptyEdits = (): BgEdits => ({ toggle: [], merge: [], split: [] });
const cloneEdits = (e: BgEdits): BgEdits => ({ toggle: e.toggle.map((x) => ({ ...x })), merge: e.merge.map((g) => g.map((x) => ({ ...x }))), split: e.split.map((x) => ({ anchor: x.anchor, at: [x.at[0], x.at[1]] })) });

export interface SelState {
  nElems: number;
  beads: BeadMeta[];
  owner: Int32Array;
  /** 자동 사면에서 빼라고 한 요소 → 비드 번호(−1 없음) */
  remove: Int32Array;
  fixed: Int32Array;
  exclude: Int32Array;
  /** v0.17.0 선택 schema(없음 = 1) */
  schema?: 1 | 2;
  /** v0.17.0 그래프 기준(sha·rules) — schema 2 + 그래프 있음(GRAPH_FAILED 면 null) */
  graphRef?: { sha256: string; rules: number } | null;
  /** v0.17.0 그래프 편집(toggle·merge·split) */
  edits?: BgEdits;
  /** v0.17.0 대칭 묶기(비드 id 묶음) */
  ties?: string[][];
}

export function emptyState(nElems: number, schema: 1 | 2 = 1, graphRef: { sha256: string; rules: number } | null = null): SelState {
  const s: SelState = { nElems, beads: [], owner: new Int32Array(nElems).fill(-1), remove: new Int32Array(nElems).fill(-1), fixed: new Int32Array(nElems), exclude: new Int32Array(nElems) };
  if (schema === 2) Object.assign(s, { schema: 2, graphRef, edits: emptyEdits(), ties: [] });
  return s;
}

/** 비드 목록·그래프 편집·대칭 묶기 스냅숏(실행 취소 meta) */
interface Snap {
  beads: BeadMeta[];
  edits?: BgEdits;
  ties?: string[][];
}
const snap = (s: SelState): Snap => ({ beads: cloneBeads(s.beads), ...(s.edits ? { edits: cloneEdits(s.edits) } : {}), ...(s.ties ? { ties: s.ties.map((g) => [...g]) } : {}) });
function restore(s: SelState, m: unknown) {
  if (Array.isArray(m)) {
    s.beads = cloneBeads(m as BeadMeta[]);
    return;
  }
  const x = m as Snap;
  s.beads = cloneBeads(x.beads);
  if (x.edits) s.edits = cloneEdits(x.edits);
  if (x.ties) s.ties = x.ties.map((g) => [...g]);
}

export const MAX_BEADS = 20;

/** 비어 있는 가장 작은 b<n> 으로 비드 추가(이름 기본 "B<n>"). 상한이면 null */
export function addBead(s: SelState, maxBeads = MAX_BEADS, floorFollow: 0 | 1 = 1): number | null {
  if (s.beads.length >= maxBeads) return null;
  let n = 1;
  while (s.beads.some((b) => b.id === `b${n}`)) n++;
  s.beads.push({ id: `b${n}`, name: `B${n}`, nTiers: 1, blend: "auto", floorFollow, links: [], holdFixed: 0 });
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

/** 패치 되돌리기(undo = before) / 다시(redo = after). 비드 목록 스냅숏(meta)이 있으면 함께 */
export function applyPatch(s: SelState, p: Patch<LayerName>, dir: "undo" | "redo") {
  for (const c of p.changes) {
    const arr = s[c.layer as LayerName];
    const v = dir === "undo" ? c.before : c.after;
    for (let i = 0; i < c.idx.length; i++) arr[c.idx[i]] = v[i];
  }
  if (p.meta) restore(s, dir === "undo" ? p.meta.before : p.meta.after);
}

const cloneBeads = (b: BeadMeta[]): BeadMeta[] =>
  b.map((x) => ({ ...x, links: x.links.map((g) => [...g]), ...(x.segs ? { segs: x.segs.map((r) => ({ ...r })) } : {}), ...(x.vars ? { vars: [...x.vars] } : {}) }));

/** 배열 변경 기록기(바뀐 값만) → 패치 */
function recorder(s: SelState) {
  const ch: Record<LayerName, { idx: number[]; before: number[]; after: number[] }> = {
    owner: { idx: [], before: [], after: [] },
    remove: { idx: [], before: [], after: [] },
    fixed: { idx: [], before: [], after: [] },
    exclude: { idx: [], before: [], after: [] },
  };
  return {
    set(name: LayerName, e: number, v: number) {
      const arr = s[name];
      if (arr[e] === v) return;
      ch[name].idx.push(e);
      ch[name].before.push(arr[e]);
      ch[name].after.push(v);
      arr[e] = v;
    },
    patch(meta?: Patch<LayerName>["meta"]): Patch<LayerName> {
      return {
        changes: (Object.keys(ch) as LayerName[])
          .filter((k) => ch[k].idx.length)
          .map((k) => ({ layer: k, idx: Uint32Array.from(ch[k].idx), before: Int32Array.from(ch[k].before), after: Int32Array.from(ch[k].after) })),
        ...(meta ? { meta } : {}),
      };
    },
  };
}

/** 지금 층의 요소(층 비우기 대상): 단 = 그 바닥, 사면 = 최종 사면(자동 포함), 고정·제외 = 칠한 요소 */
export function layerElems(s: SelState, layer: Layer, suggested?: (bead: number) => Uint8Array | null): number[] {
  const out: number[] = [];
  if (layer.kind === "fixed" || layer.kind === "exclude") {
    const a = s[layer.kind];
    for (let e = 0; e < s.nElems; e++) if (a[e]) out.push(e);
  } else if (layer.kind === "tier") {
    const code = ownerCode(layer.bead, layer.k);
    for (let e = 0; e < s.nElems; e++) if (s.owner[e] === code) out.push(e);
  } else {
    const m = effectiveSlope(s, layer.bead, suggested?.(layer.bead) ?? null);
    for (let e = 0; e < s.nElems; e++) if (m[e]) out.push(e);
  }
  return out;
}

/** 층 비우기 = 그 층 요소를 모두 빼기(사면 자동 요소는 '빼기' 표시) — 패치 1개 */
export function clearLayer(s: SelState, layer: Layer, suggested?: (bead: number) => Uint8Array | null): Patch<LayerName> {
  return paint(s, layerElems(s, layer, suggested), layer, "remove", suggested);
}

/** 기본 이름(B<n>)이면 새 번호로 따라 바꿈 */
const DEFAULT_NAME = /^B\d+$/;

/**
 * 비드 삭제: 그 비드 요소·사면 빼기 표시를 지우고, 뒤 비드 번호를 앞으로 당긴다(id b<n> 을 1 부터 다시, 기본 이름 B<n> 도 따라감).
 * 묶음·블렌딩은 비드 정보와 함께 사라진다(변수 = 저장 후 서버가 다시 만듦). 패치 1개(비드 목록 스냅숏 포함).
 */
export function deleteBead(s: SelState, bead: number): Patch<LayerName> | null {
  if (!s.beads[bead]) return null;
  const before = snap(s);
  const oldIds = s.beads.map((b) => b.id);
  const r = recorder(s);
  for (let e = 0; e < s.nElems; e++) {
    const o = s.owner[e];
    const b = ownerBead(o);
    if (b === bead) r.set("owner", e, -1);
    else if (b > bead) r.set("owner", e, ownerCode(b - 1, ownerLayer(o)));
    const rm = s.remove[e];
    if (rm === bead) r.set("remove", e, -1);
    else if (rm > bead) r.set("remove", e, rm - 1);
  }
  const next = cloneBeads(s.beads.filter((_, i) => i !== bead));
  next.forEach((b, i) => {
    const id = `b${i + 1}`;
    if (b.id !== id && DEFAULT_NAME.test(b.name) && b.name === b.id.toUpperCase()) b.name = id.toUpperCase();
    b.id = id;
  });
  s.beads = next;
  if (s.ties) {
    // 대칭 묶기: 지운 비드는 빼고 id 를 새 번호로(2개 미만 묶음은 없앰)
    const map = new Map<string, string>();
    oldIds.forEach((id, i) => i !== bead && map.set(id, `b${i < bead ? i + 1 : i}`));
    s.ties = s.ties.map((g) => g.filter((id) => map.has(id)).map((id) => map.get(id)!)).filter((g) => g.length > 1);
  }
  return r.patch({ before, after: snap(s) });
}

/** 이 비드 초기화: 그 비드의 바닥·사면 더하기·사면 빼기 표시를 비움(이름·단 수·묶음·블렌딩 유지). 패치 1개 */
export function resetBead(s: SelState, bead: number): Patch<LayerName> | null {
  if (!s.beads[bead]) return null;
  const r = recorder(s);
  for (let e = 0; e < s.nElems; e++) {
    if (ownerBead(s.owner[e]) === bead) r.set("owner", e, -1);
    if (s.remove[e] === bead) r.set("remove", e, -1);
  }
  const b = s.beads[bead];
  if (b.src === "graph" && b.segs?.length) {
    // v0.17.0 그래프 비드(seed 없음): 세그먼트 참조를 비움
    const before = snap(s);
    b.segs = [];
    return r.patch({ before, after: snap(s) });
  }
  return r.patch();
}

/** 전체 초기화: 비드 목록·모든 층(바닥·사면·고정·제외)을 비움. 패치 1개(비드 목록 스냅숏 포함) */
export function resetAll(s: SelState): Patch<LayerName> {
  const before = snap(s);
  const r = recorder(s);
  for (let e = 0; e < s.nElems; e++) {
    r.set("owner", e, -1);
    r.set("remove", e, -1);
    r.set("fixed", e, 0);
    r.set("exclude", e, 0);
  }
  s.beads = [];
  if (s.edits) s.edits = emptyEdits();
  if (s.ties) s.ties = [];
  return r.patch({ before, after: snap(s) });
}

/** 상태 깊은 복사(v0.16.2 seed 기준 상태 — 편집이 seed 를 바꾸지 않게) */
export function cloneState(s: SelState): SelState {
  const c: SelState = { nElems: s.nElems, beads: cloneBeads(s.beads), owner: s.owner.slice(), remove: s.remove.slice(), fixed: s.fixed.slice(), exclude: s.exclude.slice() };
  if (s.schema === 2) Object.assign(c, { schema: 2, graphRef: s.graphRef ? { ...s.graphRef } : null, edits: cloneEdits(s.edits ?? emptyEdits()), ties: (s.ties ?? []).map((g) => [...g]) });
  return c;
}

/**
 * v0.16.2 이 비드 초기화 = seed 로(esl_bead_auto.md AD-D-4): 그 비드의 바닥·사면 표시를 비운 뒤 seed 의 같은 id 비드 요소를 되돌린다
 * (다른 비드가 차지한 요소는 덮지 않음). 단 수·묶음·블렌딩·hold 도 seed 값(이름은 유지). seed 에 그 비드가 없으면 빈 선택(resetBead 와 같음). 패치 1개
 */
export function resetBeadTo(s: SelState, bead: number, seed: SelState): Patch<LayerName> | null {
  const b = s.beads[bead];
  if (!b) return null;
  const si = seed.beads.findIndex((x) => x.id === b.id);
  const before = snap(s);
  const r = recorder(s);
  for (let e = 0; e < s.nElems; e++) {
    if (ownerBead(s.owner[e]) === bead) r.set("owner", e, -1);
    if (s.remove[e] === bead) r.set("remove", e, -1);
  }
  if (si < 0) return r.patch();
  for (let e = 0; e < s.nElems; e++) {
    const o = seed.owner[e];
    if (ownerBead(o) === si && s.owner[e] < 0) r.set("owner", e, ownerCode(bead, ownerLayer(o)));
    if (seed.remove[e] === si && s.remove[e] < 0) r.set("remove", e, bead);
  }
  const sb = seed.beads[si];
  // v0.17.0 그래프 비드: 세그먼트·변수·hold 도 seed 값(출처가 다르면 seed 출처로)
  const next: BeadMeta = cloneBeads([{ ...b, nTiers: sb.nTiers, blend: sb.blend, floorFollow: sb.floorFollow, links: sb.links, holdFixed: sb.holdFixed, src: sb.src, segs: sb.segs, vars: sb.vars }])[0];
  if (!sb.src) delete next.src;
  if (!sb.segs) delete next.segs;
  if (!sb.vars) delete next.vars;
  if (JSON.stringify(next) === JSON.stringify(b)) return r.patch();
  s.beads = cloneBeads(s.beads.map((x, i) => (i === bead ? next : x)));
  return r.patch({ before, after: snap(s) });
}

/** v0.16.2 전체 초기화 = seed 로: 비드 목록·모든 층을 seed 그대로. 패치 1개(비드 목록 스냅숏 포함) */
export function resetAllTo(s: SelState, seed: SelState): Patch<LayerName> {
  const before = snap(s);
  const r = recorder(s);
  for (let e = 0; e < s.nElems; e++) {
    r.set("owner", e, seed.owner[e]);
    r.set("remove", e, seed.remove[e]);
    r.set("fixed", e, seed.fixed[e]);
    r.set("exclude", e, seed.exclude[e]);
  }
  s.beads = cloneBeads(seed.beads);
  if (s.schema === 2) {
    s.edits = cloneEdits(seed.edits ?? emptyEdits());
    s.ties = (seed.ties ?? []).map((g) => [...g]);
  }
  return r.patch({ before, after: snap(s) });
}

/** 마지막 단 삭제(단 1 개면 null — 비드 삭제를 쓴다): 그 바닥 요소를 비우고 묶음에서 뺀다. 패치 1개 */
export function deleteLastTier(s: SelState, bead: number): Patch<LayerName> | null {
  const b = s.beads[bead];
  if (!b || b.nTiers <= 1) return null;
  const before = snap(s);
  const r = recorder(s);
  const k = b.nTiers;
  const code = ownerCode(bead, k);
  for (let e = 0; e < s.nElems; e++) if (s.owner[e] === code) r.set("owner", e, -1);
  b.nTiers = k - 1;
  b.links = b.links.map((g) => g.filter((x) => x !== k)).filter((g) => g.length > 1);
  return r.patch({ before, after: snap(s) });
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

/** 화면 상태 → SelectionIn(§4.1). 빈 단도 그대로 넣는다(서버가 SELECT_EMPTY_TIER 로 거름). v0.17.0 schema 2 상태 = SelectionIn v2(BG-D-36) */
export function toSelectionAny(s: SelState, elemId: ArrayLike<number>, elemType: ArrayLike<number>, featureAngle: number): DoeSelectionAny {
  const v1 = toSelectionIn(s, elemId, elemType, featureAngle);
  if (s.schema !== 2) return v1;
  const beads = s.beads.map((b, bi): DoeBeadSelGraph | DoeBeadSelElems => {
    if (b.src !== "graph") return { ...v1.beads[bi], src: "elems" };
    return {
      id: b.id,
      name: b.name,
      src: "graph",
      segs: sortRefs(b.segs ?? []),
      ...(b.vars && b.vars.length < 2 ? { vars: [...b.vars] } : {}),
      ...(b.holdFixed === 0 ? { hold_fixed: 0 as const } : {}),
    };
  });
  const out: DoeSelectionV2 = {
    schema_version: 2,
    feature_angle_deg: featureAngle,
    ...(s.graphRef ? { graph: { sha256: s.graphRef.sha256, rules: s.graphRef.rules, edits: normalizeEdits(s.edits ?? emptyEdits()) } } : {}),
    beads,
    ties: (s.ties ?? []).map((g) => [...g].sort(byBeadId)).sort((a, b) => byBeadId(a[0], b[0])),
    fixed_user: v1.fixed_user,
    exclude: v1.exclude,
  };
  return out;
}
const byBeadId = (a: string, b: string) => Number(a.slice(1)) - Number(b.slice(1));
/** 편집 정규화(BG-D-37 각 목록 정렬 순) */
export function normalizeEdits(e: BgEdits): BgEdits {
  return {
    toggle: [...e.toggle].sort((a, b) => a.anchor - b.anchor),
    merge: e.merge.map((g) => [...g].sort((a, b) => a.anchor - b.anchor)).sort((a, b) => a[0].anchor - b[0].anchor),
    split: [...e.split].sort((a, b) => a.anchor - b.anchor || a.at[0] - b.at[0] || a.at[1] - b.at[1]),
  };
}

/** schema 1 SelectionIn(그래프 비드는 빈 단으로 — schema 2 상태는 toSelectionAny) */
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
      ...(b.holdFixed ? { hold_fixed: 1 as const } : {}),
    };
  });
  return { schema_version: 1, feature_angle_deg: featureAngle, beads, fixed_user: lists((e) => !!s.fixed[e]), exclude: lists((e) => !!s.exclude[e]) };
}

/** SelectionIn → 화면 상태(저장된 선택 불러오기). 메시에 없는 ID 수 = unknown */
export function fromSelectionIn(sel: DoeSelectionAny, idx: ElemIndex, nElems: number): { state: SelState; unknown: number } {
  const v2 = sel.schema_version === 2;
  const s = emptyState(nElems, v2 ? 2 : 1, v2 && sel.graph ? { sha256: sel.graph.sha256, rules: sel.graph.rules } : null);
  if (v2) {
    if (sel.graph?.edits) s.edits = cloneEdits({ toggle: sel.graph.edits.toggle ?? [], merge: sel.graph.edits.merge ?? [], split: sel.graph.edits.split ?? [] });
    s.ties = (sel.ties ?? []).map((g) => [...g]);
  }
  let unknown = 0;
  const take = (set: DoeBeadSel["slope"]["add"] | undefined, fn: (e: number) => void) => {
    const r = fromElemSet(set ?? EMPTY_SET(), idx);
    unknown += r.unknown;
    r.elems.forEach(fn);
  };
  sel.beads.forEach((bb, bi) => {
    if ("src" in bb && bb.src === "graph") {
      s.beads.push({ id: bb.id, name: bb.name ?? bb.id.toUpperCase(), nTiers: 1, blend: "auto", floorFollow: 1, links: [], holdFixed: bb.hold_fixed === 0 ? 0 : 1, src: "graph", segs: (bb.segs ?? []).map((r) => ({ ...r })), ...(bb.vars ? { vars: [...bb.vars] } : {}) });
      return;
    }
    const b = bb as DoeBeadSel;
    // 생략 가능한 칸(서버 SelectionIn 기본값 — links [], floor_follow 설정값)은 없어도 읽음(코어 정규화 사본·픽스처는 기본값을 생략)
    s.beads.push({ id: b.id, name: b.name, nTiers: Math.max(1, b.tiers.length), blend: b.blend_mm ?? "auto", floorFollow: b.floor_follow, links: (b.links ?? []).map((g) => [...g]), holdFixed: b.hold_fixed === 1 ? 1 : 0 });
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

/** 섬 색 = 그 단 색의 밝은 단계(새 층 아님, §8) */
export const islandColor = (k: number): [number, number, number] => mix(tierColor(k), [255, 255, 255], 0.55);

/**
 * 요소별 RGBA(길이 4·nElems). active = 지금 고치는 비드(그 밖 비드는 흐리게), suggested(b) = 비드 b 자동 사면,
 * islands = 요소별 섬 주인 코드(ownerCode(b, k), 없음 −1 — 표시 전용, 저장 안 함)
 */
export function elemColors(s: SelState, active: number, suggested: (bead: number) => Uint8Array | null, islands?: Int32Array | null): Uint8Array {
  const out = new Uint8Array(s.nElems * 4);
  const sug = s.beads.map((_, b) => suggested(b));
  for (let e = 0; e < s.nElems; e++) {
    const o = s.owner[e];
    let c = COLOR_NONE;
    let bead = ownerBead(o);
    const il = o < 0 && !s.exclude[e] ? islands?.[e] ?? -1 : -1;
    if (o >= 0) c = ownerLayer(o) === SLOPE ? COLOR_SLOPE : tierColor(ownerLayer(o));
    else if (il >= 0) {
      c = islandColor(ownerLayer(il));
      bead = ownerBead(il);
    } else {
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

// ---------------------------------------------------------------- v0.16.1 섬(SR-D-4·14, §5.2)
/** 비드 b 단 바닥 전체의 평균 법선(면적 가중, 첫 요소 법선 쪽으로 부호 맞춤) — 섬 판정 평면 n̄_b */
export function beadMeanNormal(t: MeshTopo, s: SelState, bead: number): Vec3 {
  // 법선 부호 기준 = 면적 최대 요소(동률 = 최소 요소 번호) — 코어 bead_select._mean_normal 과 같음(v0.16.1 통합)
  let ref = -1;
  for (let e = 0; e < s.nElems; e++) {
    const o = s.owner[e];
    if (o < 0 || ownerBead(o) !== bead || ownerLayer(o) === SLOPE) continue;
    if (ref < 0 || t.areas[e] > t.areas[ref]) ref = e;
  }
  const acc: Vec3 = [0, 0, 0];
  for (let e = 0; e < s.nElems; e++) {
    const o = s.owner[e];
    if (o < 0 || ownerBead(o) !== bead || ownerLayer(o) === SLOPE) continue;
    const sg = t.normals[e * 3] * t.normals[ref * 3] + t.normals[e * 3 + 1] * t.normals[ref * 3 + 1] + t.normals[e * 3 + 2] * t.normals[ref * 3 + 2] < 0 ? -1 : 1;
    for (let c = 0; c < 3; c++) acc[c] += sg * t.areas[e] * t.normals[e * 3 + c];
  }
  const l = Math.hypot(acc[0], acc[1], acc[2]);
  return l > 0 ? [acc[0] / l, acc[1] / l, acc[2] / l] : [0, 0, 1];
}

/** select.island.ring_frac 기본(코어 DEFAULTS·백엔드 BeadDoeSelectIslandCfg 거울 — 설정이 오면 그 값) */
export const RING_FRAC = 0.9;

export interface SelIslands {
  /** 요소별 섬 주인 코드 ownerCode(b, k), 없음 −1 */
  owner: Int32Array;
  islands: Island[];
  tooLarge: { owner: number; nElems: number; sizeMm: number }[];
}

/**
 * 화면 선택의 섬(SR-D-14 enclosedIslands): 후보 = 어느 비드 층에도 없고 제외도 아닌 요소, 주인 = 각 비드 단 바닥(코드 bead·16 + k),
 * 사면 더하기·제외 = 막힘. 모든 비드를 한 번에(후보는 비드와 무관하게 같음). X = 노드 좌표. 저장 대상 아님.
 */
export function enclosedIslands(t: MeshTopo, s: SelState, X: ArrayLike<number>, maxMm: number, ringFrac: number | null = RING_FRAC): SelIslands {
  const n = s.nElems;
  const cand = new Uint8Array(n);
  const owner = new Int32Array(n);
  for (let e = 0; e < n; e++) {
    const o = s.owner[e];
    if (o >= 0) owner[e] = ownerLayer(o) === SLOPE ? -2 : o;
    else if (s.exclude[e]) owner[e] = -2;
    else {
      owner[e] = -1;
      cand[e] = 1;
    }
  }
  const normals = new Map<number, Vec3>();
  const nOf = (o: number) => {
    const b = ownerBead(o);
    if (!normals.has(b)) normals.set(b, beadMeanNormal(t, s, b));
    return normals.get(b)!;
  };
  const r = enclosedComponents(t, cand, owner, X, nOf, { maxMm, ringFrac, outerPoly: (o) => outerPolygons(t, X, (e) => s.owner[e] === o, nOf(o)) });
  const io = new Int32Array(n).fill(-1);
  for (const il of r.islands) for (const e of il.elems) io[e] = il.owner;
  return { owner: io, islands: r.islands, tooLarge: r.tooLarge };
}

/** 비드별 섬 수(표시용) */
export function islandCount(isl: SelIslands | null, bead: number): number {
  return isl ? isl.islands.filter((x) => ownerBead(x.owner) === bead).length : 0;
}

// ---------------------------------------------------------------- v0.17.0 그래프 비드·편집(esl_beadgraph.md §5.1·§6.2) — 모두 실행 취소 가능(패치 meta)
/** 비드 목록·편집·묶기만 바꾸는 연산 → 패치(바뀐 것 없으면 null) */
function metaOp(s: SelState, fn: () => boolean | void): Patch<LayerName> | null {
  const before = snap(s);
  if (fn() === false) return null;
  const after = snap(s);
  if (JSON.stringify(before) === JSON.stringify(after)) return null;
  return { changes: [], meta: { before, after } };
}

/** 그래프 비드 추가(세그먼트 없음, hold 기본 1 — BG-D-28). 상한이면 null */
export function addGraphBead(s: SelState, maxBeads = MAX_BEADS): { bead: number; patch: Patch<LayerName> } | null {
  if (s.beads.length >= maxBeads) return null;
  let bead = -1;
  const patch = metaOp(s, () => {
    let n = 1;
    while (s.beads.some((b) => b.id === `b${n}`)) n++;
    s.beads.push({ id: `b${n}`, name: `B${n}`, nTiers: 1, blend: "auto", floorFollow: 1, links: [], holdFixed: 1, src: "graph", segs: [] });
    bead = s.beads.length - 1;
  });
  return patch ? { bead, patch } : null;
}

/** 비드의 세그먼트 집합(원 세그먼트 id — 병합 그룹 전체 포함) */
export function beadSegs(s: SelState, gi: GraphIndex, bead: number): Set<number> {
  const b = s.beads[bead];
  const out = new Set<number>();
  if (!b || b.src !== "graph") return out;
  const v = editView(gi, s.edits);
  const reps = new Set<number>();
  for (const r of b.segs ?? []) for (const id of resolveRef(gi, r)) reps.add(repOf(v, id));
  for (const sg of gi.graph.segments) if (reps.has(repOf(v, sg.id))) out.add(sg.id);
  return out;
}

/** 세그먼트를 가진 비드 번호(없으면 −1) */
export function beadOfSeg(s: SelState, gi: GraphIndex, seg: number): number {
  for (let i = 0; i < s.beads.length; i++) if (beadSegs(s, gi, i).has(seg)) return i;
  return -1;
}

/**
 * 트리 체크·3D 클릭: 세그먼트를 지금 비드에 더하기/빼기. 다른 비드 것이면 바꾸지 않음(겹침 금지 — 칠하기와 같은 규칙).
 * 네트워크 묶음에서 빼면 묶음을 풀어 나머지 세그먼트 앵커로 바꾼다.
 */
export function toggleSeg(s: SelState, gi: GraphIndex, bead: number, seg: number): { patch: Patch<LayerName> | null; reason: string | null } {
  const b = s.beads[bead];
  if (!b || b.src !== "graph") return { patch: null, reason: "그래프 비드가 아닙니다 — [+ 비드]로 만드세요" };
  const sg = gi.segById.get(seg);
  if (!sg || sg.type === "base") return { patch: null, reason: "플랜지(뿌리)는 변수가 없습니다" };
  const owner = beadOfSeg(s, gi, seg);
  if (owner >= 0 && owner !== bead) return { patch: null, reason: `${s.beads[owner].name} 에 들어 있습니다` };
  const v = editView(gi, s.edits);
  const rep = repOf(v, seg);
  const patch = metaOp(s, () => {
    const cur = s.beads[bead];
    if (owner === bead) {
      const next: BgSegRef[] = [];
      for (const r of cur.segs ?? []) {
        const ids = resolveRef(gi, r);
        if (!ids.some((id) => repOf(v, id) === rep)) next.push(r);
        else if ("network" in r) for (const id of ids) if (repOf(v, id) !== rep) next.push({ anchor: gi.segById.get(id)!.anchor });
      }
      cur.segs = dedupeRefs(next);
    } else cur.segs = dedupeRefs([...(cur.segs ?? []), { anchor: gi.segById.get(rep)?.anchor ?? sg.anchor }]);
  });
  return { patch, reason: null };
}

/** 네트워크 전체로 묶기(BG-D-18): 그 네트워크 세그먼트 참조를 {network} 하나로. 다른 비드가 그 네트워크 세그먼트를 가지면 null */
export function groupNetwork(s: SelState, gi: GraphIndex, bead: number, seg: number): { patch: Patch<LayerName> | null; reason: string | null } {
  const b = s.beads[bead];
  const sg = gi.segById.get(seg);
  if (!b || b.src !== "graph" || !sg || sg.network < 0) return { patch: null, reason: "네트워크가 없는 세그먼트입니다" };
  const na = networkAnchor(gi, sg.network);
  if (na == null) return { patch: null, reason: "네트워크 앵커를 찾지 못했습니다" };
  const members = new Set(gi.graph.networks.find((n) => n.id === sg.network)?.segments ?? []);
  for (const id of members) {
    const o = beadOfSeg(s, gi, id);
    if (o >= 0 && o !== bead) return { patch: null, reason: `${s.beads[o].name} 에 이 네트워크 세그먼트가 있습니다` };
  }
  const patch = metaOp(s, () => {
    const keep = (b.segs ?? []).filter((r) => !resolveRef(gi, r).some((id) => members.has(id)));
    s.beads[bead].segs = dedupeRefs([...keep, { network: na }]);
  });
  return { patch, reason: null };
}

function dedupeRefs(r: BgSegRef[]): BgSegRef[] {
  const seen = new Set<string>();
  return sortRefs(r.filter((x) => (seen.has(refKey(x)) ? false : (seen.add(refKey(x)), true))));
}

/** 섬 ↔ 비드 전환(D8, BG-D-9): 원래 종류로 되돌리면 편집 항목을 지움 */
export function toggleIsland(s: SelState, anchor: number, as: "bead" | "island", original: "bead" | "island"): Patch<LayerName> | null {
  if (!s.edits) return null;
  return metaOp(s, () => {
    const e = s.edits!;
    e.toggle = e.toggle.filter((t) => t.anchor !== anchor);
    if (as !== original) e.toggle.push({ anchor, as });
    // 섬으로 바꾼 세그먼트는 비드에서 뺌
    if (as === "island") for (const b of s.beads) if (b.segs) b.segs = b.segs.filter((r) => !("anchor" in r) || r.anchor !== anchor);
  });
}

/** 인접 세그먼트 병합(BG-D-37): 이미 병합 묶음에 있으면 그 묶음을 넓힘. 비드 참조는 묶음 대표(최소 앵커)로 */
export function mergeSegs(s: SelState, gi: GraphIndex, a: number, b: number): Patch<LayerName> | null {
  const sa = gi.segById.get(a);
  const sb = gi.segById.get(b);
  if (!s.edits || !sa || !sb || sa.floor !== sb.floor || a === b) return null;
  return metaOp(s, () => {
    const e = s.edits!;
    const hit = e.merge.filter((g) => g.some((r) => r.anchor === sa.anchor || r.anchor === sb.anchor));
    const anchors = new Set<number>([sa.anchor, sb.anchor, ...hit.flatMap((g) => g.map((r) => r.anchor))]);
    e.merge = [...e.merge.filter((g) => !hit.includes(g)), [...anchors].sort((x, y) => x - y).map((anchor) => ({ anchor }))];
    const rep = Math.min(...anchors);
    for (const bd of s.beads) if (bd.segs) bd.segs = dedupeRefs(bd.segs.map((r) => ("anchor" in r && anchors.has(r.anchor) ? { anchor: rep } : r)));
  });
}

/** 세그먼트 분할(BG-D-37): 골격에서 at 에 가장 가까운 점 — 계산은 서버, 화면은 편집만 기록 */
export function splitSeg(s: SelState, anchor: number, at: [number, number]): Patch<LayerName> | null {
  if (!s.edits) return null;
  return metaOp(s, () => {
    if (s.edits!.split.some((x) => x.anchor === anchor && x.at[0] === at[0] && x.at[1] === at[1])) return false;
    s.edits!.split.push({ anchor, at });
  });
}

/** 편집 1개 취소(목록의 ✕) */
export function removeEdit(s: SelState, kind: "toggle" | "merge" | "split", i: number): Patch<LayerName> | null {
  if (!s.edits) return null;
  return metaOp(s, () => {
    (s.edits![kind] as unknown[]).splice(i, 1);
  });
}

/** 대칭 묶기(BG-D-21) 켜기/끄기: 같은 묶음이 있으면 풂, 아니면 그 비드들을 다른 묶음에서 빼고 새 묶음 */
export function toggleTie(s: SelState, ids: string[]): Patch<LayerName> | null {
  if (!s.ties || ids.length < 2) return null;
  const key = [...ids].sort(byBeadId).join(",");
  return metaOp(s, () => {
    const t = s.ties!;
    const same = t.findIndex((g) => [...g].sort(byBeadId).join(",") === key);
    if (same >= 0) t.splice(same, 1);
    else {
      s.ties = t.map((g) => g.filter((x) => !ids.includes(x))).filter((g) => g.length > 1);
      s.ties.push([...ids].sort(byBeadId));
    }
  });
}

/** 비드 변수(D·W) 켜기/끄기 — 둘 다 끌 수는 없음 */
export function setBeadVars(s: SelState, bead: number, vars: ("D" | "W")[]): Patch<LayerName> | null {
  const b = s.beads[bead];
  if (!b || b.src !== "graph" || !vars.length) return null;
  return metaOp(s, () => {
    if (vars.length >= 2) delete b.vars;
    else b.vars = [...vars];
  });
}

/**
 * BG_GRAPH_STALE 뒤 다시 해석(BG-D-38): 앵커가 가리키는 요소가 새 그래프의 어느 세그먼트에 있는지로 바꿈. 못 찾은 앵커 목록을 돌려줌
 * (그 참조는 남겨 두고 화면에 BG_SEG_UNKNOWN 으로 표시 — 사용자가 지움).
 */
export function reresolve(s: SelState, gi: GraphIndex, sha256: string, rules: number): { unknown: number[]; patch: Patch<LayerName> | null } {
  const unknown: number[] = [];
  const patch = metaOp(s, () => {
    s.graphRef = { sha256, rules };
    for (const b of s.beads) {
      if (b.src !== "graph" || !b.segs) continue;
      b.segs = dedupeRefs(
        b.segs.map((r) => {
          if ("network" in r) {
            if (!gi.netByAnchor.has(r.network)) unknown.push(r.network);
            return r;
          }
          const id = resolveRef(gi, r)[0];
          if (id == null) {
            unknown.push(r.anchor);
            return r;
          }
          return { anchor: gi.segById.get(id)!.anchor };
        }),
      );
    }
  });
  return { unknown, patch };
}

/** 비드로 바꾼 섬(앵커 참조)을 지금 비드에 더하기/빼기 — 다른 비드 것이면 사유 */
export function toggleAnchorRef(s: SelState, bead: number, anchor: number): { patch: Patch<LayerName> | null; reason: string | null } {
  const b = s.beads[bead];
  if (!b || b.src !== "graph") return { patch: null, reason: "그래프 비드를 고르거나 [+ 비드]로 만드세요" };
  const has = (x: BeadMeta) => !!x.segs?.some((r) => "anchor" in r && r.anchor === anchor);
  const owner = s.beads.findIndex(has);
  if (owner >= 0 && owner !== bead) return { patch: null, reason: `${s.beads[owner].name} 에 들어 있습니다` };
  const patch = metaOp(s, () => {
    b.segs = owner === bead ? (b.segs ?? []).filter((r) => !("anchor" in r) || r.anchor !== anchor) : dedupeRefs([...(b.segs ?? []), { anchor }]);
  });
  return { patch, reason: null };
}
