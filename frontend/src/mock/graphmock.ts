// v0.17.0 BEADGRAPH 목(esl_beadgraph.md §6.1): H6 합성 TV 후면 샤시(이슈 #63 근사, 104 439 요소) 분류 결과를 5 mm 격자로 줄인 고정자료(h6graph.json)로
// select 보기 파일(part.glb·select.bin·graph.bin)·GET …/select/graph·자동 seed(BG-D-20)·schema 2 derive·변수·평면도·기저를 흉내 낸다(화면 개발·스크린샷용).
// h6graph.json = H6 시제품 출력(mesh_h6.npz + h6_graph.json)을 칸 중심 최근접 요소로 표본(라벨)·노드 최근접 높이로 만든 것 + beadgraph/1 형 그래프
// (코너·짧은 띠·spur → 접합 구역(D7), 고리 변 side, 앵커 = 격자 요소 최소 index). 결정적(난수 없음).
import type {
  BeadGraph, BgSegment, DoeBasisMeta, DoeBead, DoeBeadDerived, DoeBeadSelGraph, DoeDeriveOut, DoeDerivedGraph, DoeParam, DoeParamsOut, DoePlanOut, DoeSelectAutoOut, DoeSelectGraphOut,
  DoeSelectViewManifest, DoeSelectionV2, DoeWarning, XY,
} from "../api/types";
import { writeBasis } from "../view3d/select/basis";
import { writeGraphBin, type GraphLabels } from "../view3d/select/graph";
import { EMPTY_SET, compress } from "../view3d/select/ranges";
import { writeSelectBin } from "../view3d/select/view";
import fx from "./h6graph.json";
import { writeGlb } from "./view3dmock";

interface MockResponse {
  status: number;
  body?: unknown;
}
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResponse => ({ status, body: { detail: { code, message, ...extra } } });
function fnv(s: string) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}
const unrle = (a: number[]): number[] => {
  const out: number[] = [];
  for (let i = 0; i < a.length; i += 2) for (let k = 0; k < a[i + 1]; k++) out.push(a[i]);
  return out;
};

const NODE0 = 200001;
const ELEM0 = 700001;

export interface GraphMesh {
  n: number;
  x: Float64Array;
  nodeIds: Uint32Array;
  indices: Uint32Array;
  quads: number[][];
  tri2elem: Uint32Array;
  elemId: Uint32Array;
  elemType: Uint8Array;
  fixed: Uint8Array;
  labels: GraphLabels;
  graph: BeadGraph;
  sha256: string;
  glb: ArrayBuffer;
  bin: ArrayBuffer;
  binInfo: DoeSelectViewManifest["bin"];
  graphBin: ArrayBuffer;
}

let MESH: GraphMesh | null = null;
/** 고정자료 → 메시·라벨·그래프(1회) */
export function graphMesh(): GraphMesh {
  if (MESH) return MESH;
  const { nx, ny, h, x0, y0 } = fx.grid;
  const keep = unrle(fx.keep);
  const z4 = unrle(fx.z4);
  const nid = new Int32Array((nx + 1) * (ny + 1)).fill(-1);
  const xs: number[] = [];
  const quads: number[][] = [];
  const node = (gi: number, gj: number) => {
    const k = gj * (nx + 1) + gi;
    if (nid[k] < 0) {
      nid[k] = xs.length / 3;
      xs.push(x0 + gi * h, y0 + gj * h, z4[k] / 4);
    }
    return nid[k];
  };
  for (let j = 0; j < ny; j++)
    for (let i = 0; i < nx; i++) if (keep[j * nx + i]) quads.push([node(i, j), node(i + 1, j), node(i + 1, j + 1), node(i, j + 1)]);
  const n = xs.length / 3;
  const x = Float64Array.from(xs);
  const tri: number[] = [];
  const t2e: number[] = [];
  quads.forEach((q, e) => {
    tri.push(q[0], q[1], q[2], q[0], q[2], q[3]);
    t2e.push(e, e);
  });
  const nE = quads.length;
  const fixed = new Uint8Array(n);
  for (const k of fx.fixed) if (nid[k] >= 0) fixed[nid[k]] = 1;
  const lab = (k: keyof typeof fx.labels) => Int32Array.from(unrle(fx.labels[k]));
  const labels: GraphLabels = { cls: lab("cls"), segment: lab("segment"), junction_zone: lab("junction_zone"), island: lab("island"), floor: lab("floor"), tier: lab("tier") };
  if (labels.cls.length !== nE) throw new Error(`h6graph: 라벨 ${labels.cls.length} ≠ 요소 ${nE}`);
  const graph = { ...(fx.graph as unknown as BeadGraph), input: { ...(fx.graph as unknown as BeadGraph).input, n_nodes: n, n_elems: nE } };
  const sha256 = (fnv(JSON.stringify(graph)) + fnv(`g:${nE}`)).padEnd(64, "9");
  const nodeIds = Uint32Array.from({ length: n }, (_, i) => NODE0 + i);
  const indices = Uint32Array.from(tri);
  const tri2elem = Uint32Array.from(t2e);
  const elemId = Uint32Array.from({ length: nE }, (_, e) => ELEM0 + e);
  const elemType = new Uint8Array(nE).fill(4);
  const sb = writeSelectBin({ tri2elem, elemId, elemType, fixed });
  MESH = { n, x, nodeIds, indices, quads, tri2elem, elemId, elemType, fixed, labels, graph, sha256, glb: writeGlb({ n, x, nodeIds, indices, quads }), bin: sb.buf, binInfo: sb.bin, graphBin: writeGraphBin(labels) };
  return MESH;
}

export function graphManifest(): DoeSelectViewManifest {
  const m = graphMesh();
  return { schema: "esl/bead_select_view/1", n_nodes: m.n, n_elems: m.elemId.length, n_tris: m.tri2elem.length, mesh_sha256: "4e6".padEnd(64, "0"), h_med: fx.grid.h, plate_normal: [0, 0, 1], fixed: { scan_n: m.fixed.reduce((s, v) => s + v, 0), source: "scan" }, glb: { name: "part.glb", bytes: m.glb.byteLength }, bin: m.binInfo };
}

export function graphOut(): DoeSelectGraphOut {
  const m = graphMesh();
  return { graph: m.graph, sha256: m.sha256, edits_applied: null, warnings: m.graph.warnings ?? [], beadgraph_version: "1.0.0", rules: 1, morph_rules: 1 };
}

// ---------------------------------------------------------------- 자동 seed(BG-D-20)
const SIDE_KO = { top: "위", bottom: "아래", left: "왼쪽", right: "오른쪽" } as const;
/** 고리 변 4개(아래 변 = 세그먼트 3개) · 다리 각각 · 채널(+ 같은 바닥 나팔) 각각 · 포켓 각각 · 플래토(D 만). 순서 (tier, 앵커) */
export function graphAutoSeed(): DoeSelectAutoOut {
  const m = graphMesh();
  const g = m.graph;
  const groups: { name: string; segs: BgSegment[]; tier: number }[] = [];
  const sides = new Map<string, BgSegment[]>();
  for (const s of g.segments) if (s.type === "ring" && s.side) sides.set(s.side, [...(sides.get(s.side) ?? []), s]);
  for (const [side, ss] of sides) groups.push({ name: `고리 ${SIDE_KO[side as keyof typeof SIDE_KO]}`, segs: ss, tier: ss[0].tier });
  let nLeg = 0;
  let nCh = 0;
  let nPk = 0;
  for (const s of g.segments) {
    if (s.type === "leg") groups.push({ name: `다리 ${++nLeg}`, segs: [s], tier: s.tier });
    else if (s.type === "channel") groups.push({ name: `채널 ${++nCh}`, segs: [s, ...g.segments.filter((f) => f.type === "flare" && f.floor === s.floor)], tier: s.tier });
    else if (s.type === "pocket") groups.push({ name: `포켓 ${++nPk}`, segs: [s], tier: s.tier });
    else if (s.type === "plateau" || s.type === "area") groups.push({ name: "플래토", segs: [s], tier: s.tier });
  }
  const minA = (x: { segs: BgSegment[] }) => Math.min(...x.segs.map((s) => s.anchor));
  groups.sort((a, b) => a.tier - b.tier || minA(a) - minA(b));
  const beads: DoeBeadSelGraph[] = groups.slice(0, 20).map((x, i) => ({ id: `b${i + 1}`, name: x.name, src: "graph", segs: x.segs.map((s) => ({ anchor: s.anchor })).sort((a, b) => a.anchor - b.anchor) }));
  const selection: DoeSelectionV2 = { schema_version: 2, feature_angle_deg: 15, graph: { sha256: m.sha256, rules: 1, edits: { toggle: [], merge: [], split: [] } }, beads, ties: [], fixed_user: EMPTY_SET(), exclude: EMPTY_SET() };
  return { selection, sha256: graphSelSha(selection), map: [], warnings: [{ code: "AUTO_HINT_UNAVAILABLE", level: "info", step: null, detail: "NO_STEP", message: "STEP 이 없어 비드 인식 힌트 없이 분류했습니다" }], paicad_version: null, source: "graph", hints: [] };
}

const sortKeys = (v: unknown): unknown =>
  Array.isArray(v) ? v.map(sortKeys) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys((v as Record<string, unknown>)[k])])) : v;
export function graphSelSha(sel: DoeSelectionV2): string {
  const j = JSON.stringify(sortKeys(sel));
  return (fnv(j) + fnv(`g2:${j}`) + fnv(`${j}:v2`)).padEnd(64, "7");
}

// ---------------------------------------------------------------- derive(schema 2)
interface Resolved {
  id: string;
  name: string;
  segs: BgSegment[];
  D: number;
  W: number | null;
  tier: number;
  vars: ("D" | "W")[];
}

/** 422·409 또는 해석 결과 */
function resolve(sel: DoeSelectionV2): { bad: MockResponse } | { beads: Resolved[]; segsOut: DoeDerivedGraph["segments"] } {
  const m = graphMesh();
  const g = m.graph;
  if (sel.graph && sel.graph.sha256 !== m.sha256) return { bad: err(409, "BG_GRAPH_STALE", "분류 결과가 바뀌었습니다 — 다시 확인 후 저장", { saved: sel.graph.sha256, current: m.sha256 }) };
  const ed = sel.graph?.edits ?? { toggle: [], merge: [], split: [] };
  const segOf = (a: number): BgSegment | null => g.segments.find((s) => s.anchor === a) ?? (a >= 0 && a < m.labels.segment.length && m.labels.segment[a] >= 0 ? g.segments.find((s) => s.id === m.labels.segment[a]) ?? null : null);
  // 편집 적용(목 근사): 섬 → 비드 = area 세그먼트, 병합 = 대표(최소 앵커)로, 분할 = 대표 세그먼트 수 + 1
  const islandSegs: BgSegment[] = [];
  for (const t of ed.toggle) {
    const il = m.labels.island[t.anchor] ?? -1;
    if (t.as === "bead" && il >= 0) {
      const I = g.islands.find((x) => x.id === il);
      if (I) islandSegs.push({ id: 1000 + I.id, anchor: I.anchor, floor: I.floors[0], parent: I.parent, tier: 2, network: -1, type: "area", side: null, rel_depth: I.rel_height, D: Math.abs(I.rel_height), entry_width: null, floor_width: null, length: I.size_mm, open_end: false, junctions: [], children: [], islands: [], fixed_n: 0, n_elems: I.n_elems, skeleton: [] });
    } else if (t.as === "bead" || (t.as === "island" && !segOf(t.anchor))) return { bad: err(422, "BG_EDIT_INVALID", "전환 대상이 없습니다", { edit: t }) };
  }
  const rep = new Map<number, number>();
  for (const grp of ed.merge) {
    const ss = grp.map((r) => segOf(r.anchor));
    if (ss.some((x) => !x) || new Set(ss.map((x) => x!.floor)).size > 1) return { bad: err(422, "BG_EDIT_INVALID", "병합은 같은 바닥의 이웃 세그먼트만", { edit: grp }) };
    const a = Math.min(...ss.map((x) => x!.anchor));
    for (const x of ss) rep.set(x!.id, a);
  }
  const asIsland = new Set(ed.toggle.filter((t) => t.as === "island").map((t) => segOf(t.anchor)?.id));
  const segsOut: DoeDerivedGraph["segments"] = [];
  const seen = new Set<number>();
  for (const s of [...g.segments, ...islandSegs]) {
    if (asIsland.has(s.id) || s.type === "base") continue;
    const a = rep.get(s.id) ?? s.anchor;
    if (seen.has(a)) continue;
    seen.add(a);
    segsOut.push({ id: segsOut.length, anchor: a, type: s.type, side: s.side, tier: s.tier, D: s.D, entry_width: s.entry_width, length: s.length, network: s.network });
    for (let k = 0; k < ed.split.filter((x) => (rep.get(segOf(x.anchor)?.id ?? -1) ?? segOf(x.anchor)?.anchor) === a).length; k++)
      segsOut.push({ id: segsOut.length, anchor: a + 1 + k, type: s.type, side: s.side, tier: s.tier, D: s.D, entry_width: s.entry_width, length: s.length != null ? s.length / 2 : null, network: s.network });
  }
  const beads: Resolved[] = [];
  for (const b of sel.beads) {
    if (b.src !== "graph") continue;
    const ss: BgSegment[] = [];
    for (const r of b.segs) {
      if ("network" in r) {
        const net = g.networks.find((n) => Math.min(...n.segments.map((id) => g.segments.find((s) => s.id === id)!.anchor)) === r.network);
        if (!net) return { bad: err(422, "BG_SEG_UNKNOWN", "세그먼트를 찾지 못했습니다", { anchor: r.network }) };
        ss.push(...g.segments.filter((s) => net.segments.includes(s.id)));
        continue;
      }
      const s = segOf(r.anchor) ?? islandSegs.find((x) => x.anchor === r.anchor) ?? null;
      if (!s) return { bad: err(422, "BG_SEG_UNKNOWN", "세그먼트를 찾지 못했습니다", { anchor: r.anchor }) };
      ss.push(s, ...g.segments.filter((o) => o.id !== s.id && rep.has(o.id) && rep.get(o.id) === rep.get(s.id)));
    }
    if (new Set(ss.map((s) => (s.network >= 0 ? `n${s.network}` : `f${s.floor}`))).size > 1) return { bad: err(422, "BG_GROUP_NOT_CONNECTED", "한 비드의 세그먼트가 접합 구역으로 이어져 있지 않습니다", { bead: b.id }) };
    const len = (s: BgSegment) => s.length ?? 1;
    const L = ss.reduce((a, s) => a + len(s), 0) || 1;
    const D = ss.reduce((a, s) => a + s.D * len(s), 0) / L;
    const hasW = ss.length > 0 && ss.every((s) => s.entry_width != null && !["plateau", "area"].includes(s.type));
    const W = hasW ? ss.reduce((a, s) => a + (s.entry_width ?? 0) * len(s), 0) / L : null;
    const vars = (b.vars ?? ["D", "W"]).filter((v) => v === "D" || hasW) as ("D" | "W")[];
    beads.push({ id: b.id, name: b.name ?? b.id.toUpperCase(), segs: ss, D: +D.toFixed(3), W: W != null ? +W.toFixed(3) : null, tier: ss[0]?.tier ?? 0, vars });
  }
  for (const t of sel.ties ?? []) {
    const bs = t.map((id) => beads.find((x) => x.id === id));
    if (bs.some((x) => !x)) return { bad: err(422, "BG_TIE_NOMINAL", "대칭 묶기 비드가 없습니다", { beads: t }) };
    const Ds = bs.map((x) => x!.D);
    const Ws = bs.map((x) => x!.W);
    if (Math.max(...Ds) - Math.min(...Ds) > 0.5 || new Set(Ws.map((w) => w == null)).size > 1 || (Ws[0] != null && Math.max(...(Ws as number[])) - Math.min(...(Ws as number[])) > 1.0))
      return { bad: err(422, "BG_TIE_NOMINAL", "대칭으로 묶은 비드의 공칭 치수가 너무 다릅니다", { beads: t }) };
  }
  return { beads, segsOut };
}

const range = (v: number, rel: number): XY => [+(v * (1 - rel)).toFixed(2), +(v * (1 + rel)).toFixed(2)];

export function graphDerive(sel: DoeSelectionV2): MockResponse {
  const m = graphMesh();
  const g = m.graph;
  const r = resolve(sel);
  if ("bad" in r) return r.bad;
  const warnings: DoeWarning[] = [];
  const beads: DoeBeadDerived[] = r.beads.map((b) => {
    const w: DoeWarning[] = [];
    if (b.segs.some((s) => s.side === "top" || s.side === "bottom")) w.push({ code: "BG_SHARED_CHILD", level: "info", bead: b.id, child: g.floors.find((f) => f.tier === 2)?.id ?? 27, n_nodes: 214 });
    if (b.segs.some((s) => s.type === "pocket" && (s.entry_width ?? 0) > 70)) w.push({ code: "BG_CORNER_GUARD", level: "info", bead: b.id, n_nodes: 12, flank_max_deg: 58 });
    const ds = b.segs.map((s) => s.D);
    if (Math.max(...ds) - Math.min(...ds) > 0.5) w.push({ code: "BG_GROUP_NOMINAL_SPREAD", bead: b.id, min: Math.min(...ds), max: Math.max(...ds) });
    const nEl = b.segs.reduce((a, s) => a + s.n_elems, 0);
    return {
      id: b.id, name: b.name, n_elems: nEl, n_nodes: nEl, tiers: [{ k: 1, n_elems: nEl, D_nom: b.D, normal: [0, 0, 1], planarity_mm: 0 }],
      slope: { n_elems: 0, elems: EMPTY_SET(), suggested_n: 0, edited: false }, boundary: { loops: [], n_nodes: 0 },
      W_nom: b.W, W_min: b.W, W_max: b.W, sense: b.segs[0]?.rel_depth < 0 ? "concave" : "convex", blend_mm: b.W ? 12 : 0, blend_clipped: false, fixed_in_bead_n: 0, fixed_in_blend_n: 0,
      range_default: { D: { "1": range(b.D, 0.3) }, W: b.W != null ? range(b.W, 0.2) : null }, warnings: w, hold_fixed: 1,
    };
  });
  const sym = (fx.sym_pairs as number[][]).map((p) => [p[0], p[1]] as [number, number]);
  const graph: DoeDerivedGraph = {
    sha256: m.sha256,
    graph_algo: 1,
    edits_applied: { toggle: sel.graph?.edits.toggle.length ?? 0, merge: sel.graph?.edits.merge.length ?? 0, split: sel.graph?.edits.split.length ?? 0 },
    segments: r.segsOut,
    junction_zones: g.junction_zones.map((z) => ({ id: z.id, anchor: z.anchor, reason: z.reason })),
    beads: r.beads.map((b) => ({ id: b.id, src: "graph", segs: b.segs.map((s) => s.anchor), vars: b.vars, D_nom: b.D, W_nom: b.W, tier: b.tier })),
    sym_pairs: sym,
  };
  const out: DoeDeriveOut = { sha256: graphSelSha(sel), beads, fixed: { scan_n: m.fixed.reduce((s, v) => s + v, 0), user_n: 0, source: "scan" }, warnings, graph_algo: 1, graph };
  return { status: 200, body: out };
}

/** 변수(BG-D-22): B<n>_D · B<n>_W(k 없음). 대칭 묶기 = 작은 id 변수 1개 + group_members */
export function graphParams(sel: DoeSelectionV2): DoeParamsOut {
  const r = resolve(sel);
  if ("bad" in r) return { beads: [], params: [], warnings: [] };
  const tieOf = (id: string) => (sel.ties ?? []).find((t) => t.includes(id)) ?? null;
  const beads: DoeBead[] = [];
  const params: DoeParam[] = [];
  r.beads.forEach((b, i) => {
    const sk = b.segs[0]?.skeleton?.[1] ?? [0, 0];
    beads.push({ id: b.id, k: i + 1, shape: "select", sense: b.segs[0]?.rel_depth < 0 ? "concave" : "convex", center_ab: [sk[0], sk[1]], nominal: { depth: b.D, width: b.W ?? 0 }, fixed_overlap: false, png: null, kind: "select", name: b.name, n_tiers: 1, W_nom: b.W, W_min: b.W, W_max: b.W, blend_mm: b.W ? 12 : 0, warnings: [], islands_n: 0 });
    const t = tieOf(b.id);
    if (t && t[0] !== b.id) return;
    const up = b.id.toUpperCase();
    const others = (k: "D" | "W") => (t ? t.filter((x) => x !== b.id).map((x) => `${x.toUpperCase()}_${k}`) : []);
    const Wf = b.W != null ? Math.max(10, 6) : 6;
    if (b.vars.includes("D"))
      params.push({ name: `${up}_D`, type: "D", bead: b.id, tier: b.tier, nominal: b.D, feasible: [0.5, +Math.min(b.D * 2, b.W != null ? (b.W - Wf) / 2 : b.D * 2).toFixed(2)], feasible_source: "estimate", default_range: range(b.D, 0.3), use_default: true, group_members: others("D") });
    if (b.vars.includes("W") && b.W != null)
      params.push({ name: `${up}_W`, type: "W", bead: b.id, nominal: b.W, feasible: [+(2 * b.D + Wf).toFixed(2), +(b.W * 1.5).toFixed(2)], feasible_source: "estimate", default_range: range(b.W, 0.2), use_default: true, group_members: others("W") });
  });
  return { beads, params, warnings: [] };
}

/** 평면도(목): 외곽 = 격자 bbox, 비드 = 구성 세그먼트 골격 */
export function graphPlan(sel: DoeSelectionV2): DoePlanOut {
  const m = graphMesh();
  const { nx, ny, h, x0, y0 } = fx.grid;
  const Lx = nx * h;
  const Ly = ny * h;
  const r = resolve(sel);
  const pts: [number, number, number][] = [];
  for (let e = 0; e < m.quads.length; e += 6) {
    const q = m.quads[e];
    pts.push([+(q.reduce((s, v) => s + m.x[v * 3], 0) / 4).toFixed(1), +(q.reduce((s, v) => s + m.x[v * 3 + 1], 0) / 4).toFixed(1), 1]);
  }
  const fixed: DoePlanOut["fixed"] = [];
  for (let v = 0; v < m.n; v++) if (m.fixed[v]) fixed.push({ a: m.x[v * 3], b: m.x[v * 3 + 1] });
  return {
    frame: { a_range: [x0, x0 + Lx], b_range: [y0, y0 + Ly] },
    outline: [[x0, y0], [x0 + Lx, y0], [x0 + Lx, y0 + Ly], [x0, y0 + Ly]],
    holes: [],
    elems: { n_total: m.quads.length, decimated: true, points: pts },
    beads: "bad" in r ? [] : r.beads.map((b) => {
      const rings = b.segs.map((s) => s.skeleton.map((p) => [p[0], p[1]] as XY)).filter((x) => x.length > 1);
      const mid = rings[0]?.[1] ?? ([0, 0] as XY);
      return { id: b.id, name: b.name, ring: rings[0] ?? [], ring_ab: rings, e_ab: [[]], label_ab: [mid[0], mid[1] + 18] as XY, tiers: [{ k: 1, ring_ab: rings }], section: null };
    }),
    nodes_ab: [],
    fixed,
    a_points: [],
    load_points: [],
    links: [],
  };
}

/** 기저(목): D = 그 세그먼트 바닥 노드를 부모에서 멀어지는 쪽 n0 로 1(자손 생략), W = 없음(0 변위) */
export function graphBasis(sel: DoeSelectionV2): { meta: DoeBasisMeta; bin: ArrayBuffer; params: DoeParam[] } {
  const m = graphMesh();
  const r = resolve(sel);
  const ps = graphParams(sel);
  const vars: { idx: number[]; vec: number[] }[] = [];
  const meta: DoeBasisMeta = { schema: "esl/bead_select_basis/1", sha256: "", selection_sha256: graphSelSha(sel), n_nodes: m.n, vars: [] };
  for (const p of ps.params) {
    const idx: number[] = [];
    const vec: number[] = [];
    if (p.type === "D" && !("bad" in r)) {
      const ids = [p.bead, ...p.group_members.map((x) => x.split("_")[0].toLowerCase())];
      const segs = new Set(r.beads.filter((b) => ids.includes(b.id)).flatMap((b) => b.segs.map((s) => s.id)));
      const sgn = new Map(r.beads.flatMap((b) => b.segs.map((s) => [s.id, s.rel_depth < 0 ? -1 : 1] as [number, number])));
      const seen = new Set<number>();
      m.quads.forEach((q, e) => {
        const s = m.labels.segment[e];
        if (!segs.has(s) || m.labels.cls[e] !== 0) return;
        for (const v of q)
          if (!seen.has(v)) {
            seen.add(v);
            idx.push(v);
            vec.push(0, 0, sgn.get(s) ?? 1);
          }
      });
    }
    vars.push({ idx, vec });
    meta.vars.push({ name: p.name, type: p.type as "D" | "W", bead: p.bead, nominal: p.nominal, n: idx.length, R_mm: p.type === "W" ? 12 : null });
  }
  meta.sha256 = (fnv(`gbasis:${meta.selection_sha256}`) + fnv(meta.selection_sha256)).padEnd(64, "c");
  return { meta, bin: writeBasis(vars), params: ps.params };
}

/** schema 2 저장 검사(요소 비드 + GRAPH_FAILED 스터디 포함 — 목은 그래프 비드만 해석) */
export function graphValidate(sel: DoeSelectionV2 | undefined, graphAvailable: boolean): MockResponse | null {
  if (!sel || sel.schema_version !== 2) return err(422, "SELECT_SCHEMA_MISMATCH", "이 스터디는 선택 schema 2 입니다.");
  if (!Array.isArray(sel.beads) || !sel.beads.length) return err(422, "SELECT_EMPTY_TIER", "비드가 없습니다.");
  if (!graphAvailable && sel.beads.some((b) => b.src === "graph")) return err(422, "BG_SEG_UNKNOWN", "분류 결과가 없어 그래프 비드를 쓸 수 없습니다.", { anchor: -1 });
  for (const b of sel.beads) if (b.src === "graph" && !b.segs.length) return err(422, "BG_GROUP_NOT_CONNECTED", "세그먼트 없는 비드가 있습니다.", { bead: b.id });
  if (!graphAvailable) return null;
  const r = resolve(sel);
  return "bad" in r ? r.bad : null;
}

// ---------------------------------------------------------------- v0.18.0 ③ STEP 기준 select(esl_step_graph.md SG-D-14·16·19)
/** A 고정 이전 seed fixed_user(목): 고정 노드를 2개 이상 가진 요소(요소 ID) */
export function stepFixedUser(): DoeSelectionV2["fixed_user"] {
  const m = graphMesh();
  const ids: number[] = [];
  m.quads.forEach((q, e) => {
    if (q.filter((v) => m.fixed[v]).length >= 2) ids.push(m.elemId[e]);
  });
  return { q: compress(ids), t: [] };
}
/** ③ seed: auto = 그래프 seed + fixed_user, manual = 빈 비드 + fixed_user(source fixed_transfer) */
export function stepAutoSeed(auto: boolean): DoeSelectAutoOut {
  const g = graphAutoSeed();
  const fixed_user = stepFixedUser();
  if (auto) {
    const selection: DoeSelectionV2 = { ...(g.selection as DoeSelectionV2), fixed_user };
    return { ...g, selection, sha256: graphSelSha(selection), warnings: [] };
  }
  const selection: DoeSelectionV2 = { ...(g.selection as DoeSelectionV2), beads: [], fixed_user };
  return { selection, sha256: graphSelSha(selection), map: [], warnings: [], paicad_version: null, source: "graph", hints: [] };
}
/** ③ plan-view: 그래프 평면도 + 고정 = A 이전 표시(src) + 주 시트 영역 외곽(목: 판 위쪽 18 % 는 추가 형상) */
export function stepPlan(sel: DoeSelectionV2): DoePlanOut {
  const p = graphPlan(sel);
  const [a0, a1] = p.frame.a_range;
  const [b0, b1] = p.frame.b_range;
  const bt = b0 + (b1 - b0) * 0.82;
  return {
    ...p,
    fixed: p.fixed.map((f) => ({ ...f, src: "a_transfer" as const })),
    region_ab: [[[a0, b0], [a1, b0], [a1, bt], [a0, bt], [a0, b0]]],
  };
}
