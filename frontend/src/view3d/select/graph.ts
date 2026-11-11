// v0.17.0 비드 네트워크 그래프(esl_beadgraph.md §2.5·§6.1·§6.2): graph.bin 디코드 · 앵커 해석 · 편집 보기(toggle·merge·split) ·
// 3D 색(세그먼트·tier·섬) · 트리 구성 · 강조 마스크(트리 ↔ 3D). 계산은 브라우저 표시용이고, 편집 결과의 정답은 서버 derive(apply_edits)다.
import type { BeadGraph, BgEdits, BgIsland, BgSegRef, BgSegment, BgSegType, BgSide, BgZoneReason, BgJunctionType } from "../../api/types";

// ---------------------------------------------------------------- graph.bin
/** 요소별 정수 배열(−1 = 없음). 요소 순서 = select.bin */
export interface GraphLabels {
  cls: Int32Array;
  segment: Int32Array;
  junction_zone: Int32Array;
  island: Int32Array;
  floor: Int32Array;
  tier: Int32Array;
}
export const GRAPH_BIN_ARRAYS: (keyof GraphLabels)[] = ["cls", "segment", "junction_zone", "island", "floor", "tier"];
/** cls 값(BG §2.5) */
export const CLS = { floor: 0, wall: 1, island: 2, lance: 3 } as const;

/**
 * graph.bin = 머리 JSON 길이 L(uint32 LE) + 머리 JSON(L 바이트, ASCII){n_elems, arrays[{name, offset}]} + int32 LE 배열.
 * offset = **머리 끝(바이트 4 + L)부터 잰 바이트** — 코어 esl/doe/bead_graph.py graph_bin 규칙 하나만 쓴다(정렬 채움 없음 —
 * 배열이 4바이트 정렬이 아닐 수 있어 DataView 로 읽음).
 */
export function parseGraphBin(buf: ArrayBuffer, nElems: number): GraphLabels {
  if (buf.byteLength < 4) throw new Error("graph.bin 이 비었습니다");
  const dv = new DataView(buf);
  const hlen = dv.getUint32(0, true);
  if (4 + hlen > buf.byteLength) throw new Error("graph.bin 머리 길이가 파일보다 깁니다");
  let head: { n_elems: number; arrays: { name: string; offset: number }[] };
  try {
    head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hlen)));
  } catch {
    throw new Error("graph.bin 머리 JSON 을 읽지 못했습니다");
  }
  if (head.n_elems !== nElems) throw new Error(`graph.bin 요소 수 ${head.n_elems} ≠ ${nElems}(select.bin)`);
  const dataStart = 4 + hlen;
  const out = {} as GraphLabels;
  for (const name of GRAPH_BIN_ARRAYS) {
    const a = head.arrays?.find((x) => x.name === name);
    if (!a) throw new Error(`graph.bin: 배열 ${name} 이 없습니다`);
    if (!Number.isInteger(a.offset) || a.offset < 0) throw new Error(`graph.bin: 배열 ${name} offset 이 올바르지 않습니다`);
    const off = dataStart + a.offset;
    if (off + nElems * 4 > buf.byteLength) throw new Error(`graph.bin: 배열 ${name} 이 파일 밖입니다`);
    const arr = new Int32Array(nElems);
    for (let i = 0; i < nElems; i++) arr[i] = dv.getInt32(off + i * 4, true);
    out[name] = arr;
  }
  return out;
}

/** graph.bin 쓰기(목·시험용) — 코어 graph_bin 과 같은 바이트: 머리 = 키 정렬·공백 없는 JSON, offset = 머리 끝 기준, 채움 없음 */
export function writeGraphBin(l: GraphLabels): ArrayBuffer {
  const n = l.cls.length;
  const head = JSON.stringify({ arrays: GRAPH_BIN_ARRAYS.map((name, k) => ({ name, offset: k * n * 4 })), n_elems: n });
  const hb = new TextEncoder().encode(head);
  const start = 4 + hb.length;
  const buf = new ArrayBuffer(start + GRAPH_BIN_ARRAYS.length * n * 4);
  const dv = new DataView(buf);
  dv.setUint32(0, hb.length, true);
  new Uint8Array(buf, 4, hb.length).set(hb);
  GRAPH_BIN_ARRAYS.forEach((name, k) => {
    const a = l[name];
    for (let i = 0; i < n; i++) dv.setInt32(start + (k * n + i) * 4, a[i], true);
  });
  return buf;
}

// ---------------------------------------------------------------- 색인 · 앵커
export interface GraphIndex {
  graph: BeadGraph;
  labels: GraphLabels;
  nElems: number;
  segById: Map<number, BgSegment>;
  segByAnchor: Map<number, number>;
  netByAnchor: Map<number, number>;
  islandById: Map<number, BgIsland>;
}

export function graphIndex(graph: BeadGraph, labels: GraphLabels): GraphIndex {
  const segById = new Map(graph.segments.map((s) => [s.id, s]));
  const segByAnchor = new Map(graph.segments.map((s) => [s.anchor, s.id]));
  const netByAnchor = new Map<number, number>();
  for (const n of graph.networks) {
    const a = Math.min(...n.segments.map((id) => segById.get(id)?.anchor ?? Infinity));
    if (Number.isFinite(a)) netByAnchor.set(a, n.id);
  }
  return { graph, labels, nElems: labels.cls.length, segById, segByAnchor, netByAnchor, islandById: new Map(graph.islands.map((i) => [i.id, i])) };
}

/** 네트워크 앵커 = 그 네트워크 세그먼트 앵커 최소값(바닥 조각 최소 요소와 같음 — 목은 세그먼트 기준) */
export function networkAnchor(gi: GraphIndex, net: number): number | null {
  for (const [a, id] of gi.netByAnchor) if (id === net) return a;
  return null;
}

/** 앵커 → 세그먼트 id(정확히 앵커이거나, 그 요소가 속한 세그먼트). 없으면 null(BG_SEG_UNKNOWN) */
export function segOfAnchor(gi: GraphIndex, anchor: number): number | null {
  const s = gi.segByAnchor.get(anchor);
  if (s != null) return s;
  if (anchor < 0 || anchor >= gi.nElems) return null;
  const v = gi.labels.segment[anchor];
  return v >= 0 && gi.segById.has(v) ? v : null;
}

/** 참조 → 세그먼트 id 목록(네트워크 = 그 네트워크 전부). 해석 실패 = [] */
export function resolveRef(gi: GraphIndex, ref: BgSegRef): number[] {
  if ("network" in ref) {
    const n = gi.netByAnchor.get(ref.network);
    return n == null ? [] : gi.graph.networks.find((x) => x.id === n)?.segments ?? [];
  }
  const s = segOfAnchor(gi, ref.anchor);
  return s == null ? [] : [s];
}

export const refKey = (r: BgSegRef) => ("network" in r ? `n${r.network}` : `a${r.anchor}`);

/** 정규화(BG-D-36 앵커 정렬): 앵커 참조 먼저 오름차순, 그다음 네트워크 */
export function sortRefs(refs: BgSegRef[]): BgSegRef[] {
  const k = (r: BgSegRef) => ("network" in r ? [1, r.network] : [0, r.anchor]);
  return [...refs].sort((a, b) => k(a)[0] - k(b)[0] || k(a)[1] - k(b)[1]);
}

// ---------------------------------------------------------------- 편집 보기(브라우저 근사)
export interface EditView {
  /** 원 세그먼트 → 표시 그룹 대표(병합 = 그룹 최소 앵커 세그먼트) */
  group: Map<number, number>;
  /** 비드로 바꾼 섬 id */
  islandAsBead: Set<number>;
  /** 섬으로 바꾼 세그먼트 id */
  segAsIsland: Set<number>;
  /** 분할된 세그먼트 → 분할 점 수 */
  splits: Map<number, number>;
}

export function editView(gi: GraphIndex, edits: BgEdits | null | undefined): EditView {
  const group = new Map<number, number>();
  const islandAsBead = new Set<number>();
  const segAsIsland = new Set<number>();
  const splits = new Map<number, number>();
  for (const t of edits?.toggle ?? []) {
    const isl = gi.labels.island[t.anchor] ?? -1;
    const seg = segOfAnchor(gi, t.anchor);
    if (t.as === "bead" && isl >= 0) islandAsBead.add(isl);
    else if (t.as === "island" && seg != null) segAsIsland.add(seg);
  }
  for (const m of edits?.merge ?? []) {
    const ids = m.map((r) => segOfAnchor(gi, r.anchor)).filter((x): x is number => x != null);
    if (ids.length < 2) continue;
    const rep = ids.reduce((a, b) => ((gi.segById.get(a)?.anchor ?? 0) <= (gi.segById.get(b)?.anchor ?? 0) ? a : b));
    for (const id of ids) group.set(id, rep);
  }
  for (const sp of edits?.split ?? []) {
    const id = segOfAnchor(gi, sp.anchor);
    if (id != null) splits.set(id, (splits.get(id) ?? 0) + 1);
  }
  return { group, islandAsBead, segAsIsland, splits };
}
export const repOf = (v: EditView, seg: number) => v.group.get(seg) ?? seg;

// ---------------------------------------------------------------- 대상(트리 행 ↔ 3D 요소)
export type GraphTarget = { kind: "seg"; id: number } | { kind: "zone"; id: number } | { kind: "island"; id: number } | { kind: "floor"; id: number };
export const targetKey = (t: GraphTarget | null) => (t ? `${t.kind}:${t.id}` : "");

/** 요소 → 대상(섬 > 접합 구역 > 세그먼트 > 바닥) */
export function targetOfElem(gi: GraphIndex, e: number): GraphTarget | null {
  if (e < 0 || e >= gi.nElems) return null;
  const L = gi.labels;
  if (L.island[e] >= 0) return { kind: "island", id: L.island[e] };
  if (L.junction_zone[e] >= 0) return { kind: "zone", id: L.junction_zone[e] };
  if (L.segment[e] >= 0) return { kind: "seg", id: L.segment[e] };
  if (L.floor[e] >= 0) return { kind: "floor", id: L.floor[e] };
  return null;
}

/** 대상 → 요소 마스크(세그먼트 = 병합 그룹 전체) */
export function targetMask(gi: GraphIndex, t: GraphTarget, v?: EditView | null): Uint8Array {
  const L = gi.labels;
  const out = new Uint8Array(gi.nElems);
  if (t.kind === "seg") {
    const rep = v ? repOf(v, t.id) : t.id;
    for (let e = 0; e < gi.nElems; e++) {
      const s = L.segment[e];
      if (s >= 0 && (s === t.id || (v && repOf(v, s) === rep)) && L.island[e] < 0) out[e] = 1;
    }
  } else {
    const arr = t.kind === "zone" ? L.junction_zone : t.kind === "island" ? L.island : L.floor;
    for (let e = 0; e < gi.nElems; e++) if (arr[e] === t.id) out[e] = 1;
  }
  return out;
}

/** 세그먼트 집합 → 요소 마스크(섬 제외) */
export function segsMask(gi: GraphIndex, segs: Set<number>): Uint8Array {
  const out = new Uint8Array(gi.nElems);
  if (!segs.size) return out;
  for (let e = 0; e < gi.nElems; e++) if (segs.has(gi.labels.segment[e]) && gi.labels.island[e] < 0) out[e] = 1;
  return out;
}

// ---------------------------------------------------------------- 색
export type GraphColorMode = "segment" | "tier" | "island";
export const COLOR_MODE_NAME: Record<GraphColorMode, string> = { segment: "세그먼트", tier: "단계(tier)", island: "섬" };
type RGB = [number, number, number];
const NONE: RGB = [196, 200, 206];
const ZONE_A: RGB = [150, 154, 160];
const ZONE_B: RGB = [178, 182, 188];
const ISLAND: RGB = [150, 196, 238];
const LANCE: RGB = [120, 170, 120];
const HIGHLIGHT: RGB = [255, 196, 0];
/** 세그먼트 팔레트(서로 구분되는 12색 — 주황·파랑 강조색과 겹치지 않게 채도 중간) */
export const SEG_PALETTE: RGB[] = [
  [76, 114, 176], [221, 132, 82], [85, 168, 104], [196, 78, 82], [129, 114, 179], [147, 120, 96],
  [218, 139, 195], [140, 140, 60], [100, 181, 205], [204, 185, 116], [61, 145, 138], [170, 110, 150],
];
export const TIER_COLORS: RGB[] = [[205, 209, 214], [91, 140, 205], [124, 186, 128], [226, 150, 86], [176, 120, 196]];
export const segColor = (id: number): RGB => SEG_PALETTE[((id % SEG_PALETTE.length) + SEG_PALETTE.length) % SEG_PALETTE.length];
const mix = (a: RGB, b: RGB, t: number): RGB => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
const shade = (c: RGB, t: number): RGB => mix(c, [40, 40, 40], t);

export interface GraphEmphasis {
  /** 지금 비드 세그먼트(진하게) */
  active: Set<number>;
  /** 다른 비드 세그먼트(중간) */
  other: Set<number>;
  /** 트리 ↔ 3D 강조(노랑) */
  highlight: Uint8Array | null;
}

/**
 * 요소별 RGBA(그래프 모드). segment = 세그먼트별 색(벽 = 어둡게, 접합 구역 = 빗금 회색, 섬 = 섬 색), tier = 단계별, island = 섬·랜스만.
 * 비드에 든 세그먼트는 진하게, 아무 비드에도 없으면 옅게. elemsColor(e) 가 있으면(요소 비드 칠하기) 그 색이 우선.
 */
export function graphColors(gi: GraphIndex, v: EditView, mode: GraphColorMode, emph: GraphEmphasis, elemsColor?: (e: number) => RGB | null): Uint8Array {
  const L = gi.labels;
  const n = gi.nElems;
  const out = new Uint8Array(n * 4);
  const anyBead = emph.active.size + emph.other.size > 0;
  for (let e = 0; e < n; e++) {
    let c: RGB = NONE;
    const isl = L.island[e];
    const seg = L.segment[e];
    const jz = L.junction_zone[e];
    const wall = L.cls[e] === CLS.wall;
    const asIsland = seg >= 0 && v.segAsIsland.has(seg);
    if (mode === "tier") c = L.tier[e] >= 0 ? TIER_COLORS[Math.min(L.tier[e], TIER_COLORS.length - 1)] : NONE;
    else if (mode === "island") c = isl >= 0 && !v.islandAsBead.has(isl) ? (L.cls[e] === CLS.lance ? LANCE : ISLAND) : asIsland ? ISLAND : NONE;
    else if (isl >= 0 && !v.islandAsBead.has(isl)) c = L.cls[e] === CLS.lance ? LANCE : ISLAND;
    else if (isl >= 0) c = segColor(1000 + isl);
    else if (jz >= 0) c = ((e * 7) >> 1) % 2 ? ZONE_A : ZONE_B;
    else if (asIsland) c = ISLAND;
    else if (seg >= 0 && gi.segById.get(seg)?.type !== "base") {
      const rep = repOf(v, seg);
      c = segColor(rep);
      if (anyBead && !emph.active.has(seg)) c = mix(c, NONE, emph.other.has(seg) ? 0.45 : 0.7);
      else if (!anyBead) c = mix(c, NONE, 0.15);
      if (wall) c = shade(c, 0.25);
    } else if (wall) c = shade(NONE, 0.12);
    const ec = elemsColor?.(e);
    if (ec) c = ec;
    if (emph.highlight?.[e]) c = mix(c, HIGHLIGHT, 0.75);
    out[e * 4] = Math.round(c[0]);
    out[e * 4 + 1] = Math.round(c[1]);
    out[e * 4 + 2] = Math.round(c[2]);
    out[e * 4 + 3] = 255;
  }
  return out;
}

// ---------------------------------------------------------------- 이름(화면 한국어)
export const SEG_TYPE_NAME: Record<BgSegType, string> = {
  ring: "고리 변", leg: "다리", channel: "채널", pocket: "포켓", flare: "나팔", corner: "코너", tooth: "빗살", spur: "짧은 가지", plateau: "플래토", area: "면", base: "플랜지",
};
export const SIDE_NAME: Record<BgSide, string> = { top: "위", bottom: "아래", left: "왼쪽", right: "오른쪽" };
export const ZONE_REASON_NAME: Record<BgZoneReason, string> = { junction: "접합", corner: "코너", short_strip: "짧은 띠", spur: "짧은 가지", step: "단차", split: "분할" };
export const JUNCTION_NAME: Record<BgJunctionType, string> = { T: "T", X: "X", L: "L", W: "폭 변화", Y: "Y", step: "단차", split: "분할" };
export const segLabel = (s: BgSegment) => (s.side ? `${SEG_TYPE_NAME[s.type]} ${SIDE_NAME[s.side]}` : SEG_TYPE_NAME[s.type]);

/** 바닥 이름(D1 위계 — 그 바닥 세그먼트 종류로) */
export function floorName(gi: GraphIndex, floor: number): string {
  if (floor === gi.graph.root) return "플랜지";
  const types = new Set(gi.graph.segments.filter((s) => s.floor === floor).map((s) => s.type));
  if (types.has("ring")) return "고리 띠";
  if (types.has("plateau")) return "플래토";
  if (types.has("channel") || types.has("flare")) return "채널";
  if (types.has("pocket")) return "포켓";
  if (types.has("area")) return "면";
  return `바닥 ${floor}`;
}

/** 세그먼트를 가질 수 있는(비드형·면형) 세그먼트인가 — base 는 아님 */
export const selectableSeg = (s: BgSegment | undefined) => !!s && s.type !== "base";

// ---------------------------------------------------------------- 트리
export interface TreeFloor {
  floor: number;
  name: string;
  tier: number;
  network: number;
  segs: BgSegment[];
  zones: { id: number; reason: BgZoneReason; label: string }[];
  islands: BgIsland[];
  holes: number;
  children: TreeFloor[];
}

/** 바닥 위계 트리: 뿌리(root + root_group) → 자식 바닥(세그먼트가 있는 것). 섬은 부모 바닥 아래 묶음 */
export function buildTree(gi: GraphIndex): TreeFloor | null {
  const g = gi.graph;
  const rootSet = new Set([g.root, ...(g.root_group ?? [])]);
  const segFloors = new Set(g.segments.map((s) => s.floor));
  const floorById = new Map(g.floors.map((f) => [f.id, f]));
  const nodeOf = (fid: number): TreeFloor => {
    const f = floorById.get(fid);
    const segs = g.segments.filter((s) => (fid === g.root ? rootSet.has(s.floor) : s.floor === fid)).sort((a, b) => a.anchor - b.anchor);
    const net = f?.network ?? -1;
    const zones = net >= 0 ? g.junction_zones.filter((z) => z.network === net).sort((a, b) => a.anchor - b.anchor) : [];
    const zoneLabel = (z: (typeof zones)[number]) => {
      const js = z.junctions.map((j) => g.junctions.find((x) => x.id === j)?.type).filter(Boolean) as BgJunctionType[];
      return `${ZONE_REASON_NAME[z.reason]}${js.length ? ` (${[...new Set(js)].map((t) => JUNCTION_NAME[t]).join("·")})` : ""}`;
    };
    const fl = fid === g.root ? rootSet : new Set([fid]);
    const islands = g.islands.filter((i) => fl.has(i.parent)).sort((a, b) => a.anchor - b.anchor);
    const holes = g.holes.filter((h) => fl.has(h.owner_floor)).length;
    const kids = g.floors
      .filter((c) => !rootSet.has(c.id) && fl.has(c.parent) && c.island < 0 && c.kind !== "island" && segFloors.has(c.id))
      .sort((a, b) => a.tier - b.tier || a.anchor - b.anchor)
      .map((c) => nodeOf(c.id));
    return { floor: fid, name: floorName(gi, fid), tier: f?.tier ?? 0, network: net, segs, zones: zones.map((z) => ({ id: z.id, reason: z.reason, label: zoneLabel(z) })), islands, holes, children: kids };
  };
  return floorById.has(g.root) ? nodeOf(g.root) : null;
}

/** 같은 네트워크에서 접합 구역을 공유하는 이웃 세그먼트(병합 후보) */
export function adjacentSegs(gi: GraphIndex, seg: number): number[] {
  const s = gi.segById.get(seg);
  if (!s) return [];
  const out = new Set<number>();
  for (const z of gi.graph.junction_zones)
    if (z.adj_segments.includes(seg)) for (const o of z.adj_segments) if (o !== seg && gi.segById.get(o)?.floor === s.floor) out.add(o);
  return [...out].sort((a, b) => a - b);
}

/**
 * 평면 좌표(분할 at) = (p·e1 − origin[0], p·e2 − origin[1]), 1e-3 반올림 — 코어 beadgraph 평면(골격·split at)과 정확히 같은 식
 * (zones.Mesh.P = [X·e1, X·e2] − frame.origin, edits._split). origin 이 없는 옛 그래프는 [0, 0].
 * Verifier fix v0.17.0: origin 을 빼지 않아 H6 에서 (434.8, 491.1)을 보냈음(코어 기대 (−164.9, 150.3)).
 */
export function planXY(gi: GraphIndex, p: ArrayLike<number>): [number, number] {
  const { e1, e2 } = gi.graph.frame;
  const o = gi.graph.frame.origin ?? [0, 0];
  const r = (v: number) => Math.round(v * 1000) / 1000;
  return [r(p[0] * e1[0] + p[1] * e1[1] + p[2] * e1[2] - o[0]), r(p[0] * e2[0] + p[1] * e2[1] + p[2] * e2[2] - o[1])];
}
