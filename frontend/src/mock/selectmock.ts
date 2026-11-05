// v0.15.0 비드 직접 선택 목(esl_bead_select.md) — 합성 메시·derive·변수·평면도·기저·미리보기 셀. DoeMock(doedata.ts) 이 select 경로에서 부른다.
// 600×400 판(5 mm 4각), 경로형 2단 비드 b1(꺾인 경로 3 구간, 폭 50 → 70 mm 선형, 단1 깊이 22 · 단2 깊이 14 — 경로 뒤쪽만, 사면 60°),
// 원형 1단 비드 b2(D 6 · W 40), 체결 고정 노드 고리 5개(하나는 b1 경계에서 18 mm). 요소별 정답 표지(label). 결정적(난수 없음).
// v0.16.1: b1 단2 바닥 (450, 180) 에 작은 딤플(위로 3 mm, 요소 12개 — 섬 정답 LABEL.b1i), derive 가 섬·구멍·hold 를 돌려줌(esl_select_relax.md §4.2).
// 서버 알고리즘(§5)의 단순 흉내다 — 공칭 치수·단면·기저는 합성 해석식으로 만든다(화면 개발용).
import type {
  DoeCellWarning,
  DoeFixedViol,
  DoeBasisMeta, DoeBead, DoeBeadDerived, DoeDeriveOut, DoeDesignStatus, DoeElemSet, DoeParam, DoeParamsOut, DoePlanOut, DoeSelectViewManifest, DoeSelectionDerived, DoeSelectionIn,
  DoeSettingsOut, DoeWarning, XY,
} from "../api/types";
import { boundaryNodes, buildTopo, type MeshTopo } from "../view3d/select/adjacency";
import { enclosedComponents, outerPolygons, type Vec3 } from "../view3d/select/grow";
import { writeBasis } from "../view3d/select/basis";
import { EMPTY_SET, elemIndex, fromElemSet, normalizeElemSet, toElemSet } from "../view3d/select/ranges";
import { writeSelectBin } from "../view3d/select/view";
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
// eslint-disable-next-line no-control-regex
const CTRL_RE = /[\u0000-\u001f\u007f]/;
const MAX_SELECTION_KB = 4096;

export const SEL_H = 5;
export const SEL_NX = 121;
export const SEL_NY = 81;
const SEL_NODE0 = 100001;
const SEL_ELEM0 = 500001;
const SEL_PATH: XY[] = [[80, 300], [260, 300], [380, 180], [520, 180]];
const SLOPE_TAN = Math.tan((60 * Math.PI) / 180);
const CIRC = { c: [470, 80] as XY, W: 40, D: 6 };
export const SEL_FIXED_CENTERS: XY[] = [[30, 30], [570, 30], [30, 370], [570, 370], [150, 344], [200, 300]]; // 마지막 = b1 단1 바닥 안 체결 구멍(v0.16.1)
/** 정답 표지: 0 상판 · 1 b1 단1 바닥 · 2 b1 단2 바닥 · 3 사면·전이 · 4 b2 바닥 · 5 b1 단2 섬(딤플, v0.16.1) */
export const LABEL = { plate: 0, b1t1: 1, b1t2: 2, slope: 3, b2: 4, b1i: 5 } as const;
/** v0.16.1 딤플(섬): 중심·반경 안 노드를 위로 3 mm */
export const SEL_DIMPLE = { c: [450, 180] as XY, r: 5.1, up: 3 };
const inDimple = (x: number, y: number) => Math.hypot(x - SEL_DIMPLE.c[0], y - SEL_DIMPLE.c[1]) <= SEL_DIMPLE.r;

const PATH_L = (() => {
  const L = [0];
  for (let i = 1; i < SEL_PATH.length; i++) L.push(L[i - 1] + Math.hypot(SEL_PATH[i][0] - SEL_PATH[i - 1][0], SEL_PATH[i][1] - SEL_PATH[i - 1][1]));
  return L;
})();
const LTOT = PATH_L[PATH_L.length - 1];

function nearestOnPath(x: number, y: number): { d: number; t: number; dir: XY } {
  let best = { d: Infinity, t: 0, dir: [0, 1] as XY };
  for (let i = 1; i < SEL_PATH.length; i++) {
    const [ax, ay] = SEL_PATH[i - 1];
    const [bx, by] = SEL_PATH[i];
    const vx = bx - ax;
    const vy = by - ay;
    const l = Math.hypot(vx, vy);
    const u = Math.max(0, Math.min(1, ((x - ax) * vx + (y - ay) * vy) / (l * l)));
    const px = ax + u * vx;
    const py = ay + u * vy;
    const d = Math.hypot(x - px, y - py);
    if (d < best.d) best = { d, t: (PATH_L[i - 1] + u * l) / LTOT, dir: d ? [(x - px) / d, (y - py) / d] : [-vy / l, vx / l] };
  }
  return best;
}
export const selWidth = (t: number) => 50 + 20 * t;
export const selDepth = (t: number) => (t < 0.64 ? 22 : t > 0.67 ? 14 : 22 - (8 * (t - 0.64)) / 0.03);
/** 깊이(+ = 아래, 상판 0) */
function depthAt(x: number, y: number): number {
  const h = nearestOnPath(x, y);
  const a = selWidth(h.t) / 2;
  const D = selDepth(h.t);
  const z1 = D * Math.max(0, Math.min(1, (a - h.d) / (D / SLOPE_TAN)));
  const dc = Math.hypot(x - CIRC.c[0], y - CIRC.c[1]);
  const z2 = CIRC.D * Math.max(0, Math.min(1, (CIRC.W / 2 - dc) / (CIRC.D / SLOPE_TAN)));
  return Math.max(z1, z2);
}

export interface SelMesh {
  n: number;
  x: Float64Array;
  nodeIds: Uint32Array;
  indices: Uint32Array;
  quads: number[][];
  tri2elem: Uint32Array;
  elemId: Uint32Array;
  elemType: Uint8Array;
  fixed: Uint8Array;
  label: Uint8Array;
  topo: MeshTopo;
  glb: ArrayBuffer;
  bin: ArrayBuffer;
  /** select_manifest.json 의 bin 항목(섹션 배치) */
  binInfo: DoeSelectViewManifest["bin"];
}
let MESH: SelMesh | null = null;
export function selMesh(): SelMesh {
  if (MESH) return MESH;
  const n = SEL_NX * SEL_NY;
  const x = new Float64Array(n * 3);
  const nodeIds = new Uint32Array(n);
  const fixed = new Uint8Array(n);
  for (let j = 0; j < SEL_NY; j++)
    for (let i = 0; i < SEL_NX; i++) {
      const k = j * SEL_NX + i;
      const px = i * SEL_H;
      const py = j * SEL_H;
      x[k * 3] = px;
      x[k * 3 + 1] = py;
      x[k * 3 + 2] = -depthAt(px, py) + (inDimple(px, py) ? SEL_DIMPLE.up : 0);
      nodeIds[k] = SEL_NODE0 + k;
      if (SEL_FIXED_CENTERS.some(([cx, cy]) => Math.hypot(px - cx, py - cy) <= 8)) fixed[k] = 1;
    }
  const quads: number[][] = [];
  const tri: number[] = [];
  const t2e: number[] = [];
  for (let j = 0; j < SEL_NY - 1; j++)
    for (let i = 0; i < SEL_NX - 1; i++) {
      const a = j * SEL_NX + i;
      const q = [a, a + 1, a + SEL_NX + 1, a + SEL_NX];
      const e = quads.length;
      quads.push(q);
      tri.push(q[0], q[1], q[2], q[0], q[2], q[3]);
      t2e.push(e, e);
    }
  const nE = quads.length;
  const indices = Uint32Array.from(tri);
  const tri2elem = Uint32Array.from(t2e);
  const elemId = Uint32Array.from({ length: nE }, (_, e) => SEL_ELEM0 + e);
  const elemType = new Uint8Array(nE).fill(4);
  const label = new Uint8Array(nE);
  for (let e = 0; e < nE; e++) {
    const zs = quads[e].map((v) => -x[v * 3 + 2]);
    const cx = quads[e].reduce((s, v) => s + x[v * 3], 0) / 4;
    const cy = quads[e].reduce((s, v) => s + x[v * 3 + 1], 0) / 4;
    const flat = Math.max(...zs) - Math.min(...zs) < 1e-6;
    if (quads[e].some((v) => inDimple(x[v * 3], x[v * 3 + 1]))) label[e] = LABEL.b1i;
    else if (flat && zs[0] < 1e-6) label[e] = LABEL.plate;
    else if (flat && Math.hypot(cx - CIRC.c[0], cy - CIRC.c[1]) < CIRC.W / 2) label[e] = LABEL.b2;
    else if (flat && Math.abs(zs[0] - 22) < 1e-6) label[e] = LABEL.b1t1;
    else if (flat && Math.abs(zs[0] - 14) < 1e-6) label[e] = LABEL.b1t2;
    else label[e] = LABEL.slope;
  }
  const topo = buildTopo(x, indices, tri2elem, nE);
  const mm = { n, x, nodeIds, indices, quads };
  MESH = { ...mm, tri2elem, elemId, elemType, fixed, label, topo, glb: writeGlb(mm), ...selBin(writeSelectBin({ tri2elem, elemId, elemType, fixed })) };
  return MESH;
}

function selBin(w: ReturnType<typeof writeSelectBin>) {
  return { bin: w.buf, binInfo: w.bin };
}

export function selManifest(): DoeSelectViewManifest {
  const m = selMesh();
  return { schema: "esl/bead_select_view/1", n_nodes: m.n, n_elems: m.elemId.length, n_tris: m.tri2elem.length, mesh_sha256: "5e1ec7".padEnd(64, "0"), h_med: SEL_H, plate_normal: [0, 0, 1], fixed: { scan_n: m.fixed.reduce((s, v) => s + v, 0), source: "scan" }, glb: { name: "part.glb", bytes: m.glb.byteLength }, bin: m.binInfo };
}

/** 정답 표지로 만든 기본 선택(b1 = 단1·단2, b2 = 단1) — 목 시드·시험용 */
export function selDefaultSelection(): DoeSelectionIn {
  const m = selMesh();
  const pick = (lab: number) => toElemSet([...m.label.keys()].filter((e) => m.label[e] === lab), m.elemId, m.elemType);
  const bead = (id: string, name: string, tiers: DoeElemSet[]) => ({
    id,
    name,
    tiers: tiers.map((floor, i) => ({ k: i + 1, floor })),
    slope: { mode: "auto" as const, add: EMPTY_SET(), remove: EMPTY_SET() },
    blend_mm: "auto" as const,
    floor_follow: 1 as const,
    links: [] as number[][],
  });
  return { schema_version: 1, feature_angle_deg: 15, beads: [bead("b1", "좌 경로 비드", [pick(LABEL.b1t1), pick(LABEL.b1t2)]), bead("b2", "원형 비드", [pick(LABEL.b2)])], fixed_user: EMPTY_SET(), exclude: EMPTY_SET() };
}

/** 정규화(구간 병합·기본값) — sha 입력 */
export function selNormalize(sel: DoeSelectionIn): DoeSelectionIn {
  const ns = (x: DoeElemSet | undefined) => normalizeElemSet(x ?? EMPTY_SET());
  return {
    schema_version: 1,
    feature_angle_deg: sel.feature_angle_deg ?? 15,
    beads: sel.beads.map((b) => ({
      id: b.id,
      name: b.name,
      tiers: b.tiers.map((t) => ({ k: t.k, floor: ns(t.floor) })),
      slope: { mode: b.slope?.mode ?? "auto", add: ns(b.slope?.add), remove: ns(b.slope?.remove) },
      blend_mm: b.blend_mm ?? "auto",
      floor_follow: b.floor_follow ?? 1,
      links: (b.links ?? []).map((g) => [...g].sort((p, q) => p - q)),
      ...(b.hold_fixed === 1 ? { hold_fixed: 1 as const } : {}), // SR-D-13a: 0 은 생략
    })),
    fixed_user: ns(sel.fixed_user),
    exclude: ns(sel.exclude),
  };
}
const sortKeys = (v: unknown): unknown =>
  Array.isArray(v) ? v.map(sortKeys) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys((v as Record<string, unknown>)[k])])) : v;
export function selSha(sel: DoeSelectionIn): string {
  const j = JSON.stringify(sortKeys(selNormalize(sel)));
  return (fnv(j) + fnv(`sel:${j}`) + fnv(`${j}:2`)).padEnd(64, "5");
}

/** §4.1 검증 → 오류 응답 또는 null */
export function selValidate(sel: DoeSelectionIn | undefined, st: DoeSettingsOut): MockResponse | null {
  const m = selMesh();
  const cfg = st.select!;
  if (!sel || !Array.isArray(sel.beads) || !sel.beads.length) return err(422, "SELECT_EMPTY_TIER", "비드가 없습니다.");
  if (sel.beads.length > cfg.max_beads) return err(422, "SELECT_BEAD_ID_INVALID", `비드는 최대 ${cfg.max_beads}개입니다.`);
  if (JSON.stringify(selNormalize(sel)).length > MAX_SELECTION_KB * 1024) return err(413, "SELECT_TOO_LARGE", "선택이 너무 큽니다.");
  const idx = elemIndex(m.elemId, m.elemType);
  const owner = new Set<number>();
  const ids = new Set<string>();
  for (const b of sel.beads) {
    if (!/^b[1-9][0-9]?$/.test(b.id) || ids.has(b.id)) return err(422, "SELECT_BEAD_ID_INVALID", `비드 id 가 올바르지 않습니다: ${b.id}`, { bead: b.id });
    ids.add(b.id);
    if (!b.name || b.name.length > 32 || CTRL_RE.test(b.name)) return err(422, "SELECT_NAME_INVALID", "비드 이름은 1~32자, 제어문자 없음입니다.", { bead: b.id });
    if (!b.tiers.length || b.tiers.length > cfg.max_tiers) return err(422, "SELECT_EMPTY_TIER", `${b.name}: 단이 없습니다.`, { bead: b.id });
    const hf = (b as { hold_fixed?: unknown }).hold_fixed;
    if (hf !== undefined && hf !== null && hf !== 0 && hf !== 1) return err(422, "SELECT_HOLD_INVALID", `${b.name}: '체결 구멍 둘레 고정' 값은 0 또는 1 입니다.`, { bead: b.id });
    if (b.tiers.some((t, i) => t.k !== i + 1)) return err(422, "SELECT_TIERS_GAP", `${b.name}: 단 번호가 건너뜁니다.`, { bead: b.id });
    const seenK = new Set<number>();
    for (const g of b.links ?? [])
      for (const k of g) {
        if (seenK.has(k) || k < 1 || k > b.tiers.length) return err(422, "SELECT_LINK_INVALID", `${b.name}: 단 묶음이 올바르지 않습니다.`, { bead: b.id });
        seenK.add(k);
      }
    const sets = [...b.tiers.map((t) => t.floor), b.slope?.add ?? EMPTY_SET()];
    for (let i = 0; i < sets.length; i++) {
      const r = fromElemSet(sets[i], idx);
      if (r.unknown) return err(422, "SELECT_ELEM_UNKNOWN", `기준 메시에 없는 요소 ${r.unknown}개`, { n: r.unknown });
      if (i < b.tiers.length && !r.elems.length) return err(422, "SELECT_EMPTY_TIER", `${b.name} 단 ${i + 1}: 바닥 요소가 없습니다.`, { bead: b.id, k: i + 1 });
      let over = 0;
      for (const e of r.elems) {
        if (owner.has(e)) over++;
        owner.add(e);
      }
      if (over) return err(422, "SELECT_OVERLAP", `${b.name}: 다른 층·비드와 겹치는 요소 ${over}개`, { bead: b.id, elems_n: over });
    }
  }
  return null;
}

interface BeadGeo {
  kind: "path" | "circle";
  hit: (x: number, y: number) => { d: number; a: number; D: number; dir: XY; t: number };
}
const GEO_PATH: BeadGeo = {
  kind: "path",
  hit: (x, y) => {
    const h = nearestOnPath(x, y);
    return { d: h.d, a: selWidth(h.t) / 2, D: selDepth(h.t), dir: h.dir, t: h.t };
  },
};
const GEO_CIRC: BeadGeo = {
  kind: "circle",
  hit: (x, y) => {
    const dx = x - CIRC.c[0];
    const dy = y - CIRC.c[1];
    const d = Math.hypot(dx, dy) || 1;
    return { d, a: CIRC.W / 2, D: CIRC.D, dir: [dx / d, dy / d], t: 0 };
  },
};

export interface DeriveBead {
  floors: number[][];
  slope: Uint8Array;
  suggested: number[];
  geo: BeadGeo;
  derived: DoeBeadDerived;
  /** v0.16.1 섬 요소(바닥과 같이 이동 — 기저 흉내에서 바닥과 같은 변위) */
  islands: number[];
}

function pathAt(tt: number): { p: XY; nrm: XY } {
  const s = tt * LTOT;
  let i = 1;
  while (i < PATH_L.length - 1 && PATH_L[i] < s) i++;
  const u = (s - PATH_L[i - 1]) / (PATH_L[i] - PATH_L[i - 1]);
  const [ax, ay] = SEL_PATH[i - 1];
  const [bx, by] = SEL_PATH[i];
  const l = Math.hypot(bx - ax, by - ay);
  return { p: [ax + u * (bx - ax), ay + u * (by - ay)], nrm: [-(by - ay) / l, (bx - ax) / l] };
}
/** 해석 경계 고리(평면) + 바깥 단위 방향 */
function ringOf(geo: BeadGeo, off: (a: number, D: number) => number, tMin = 0, tMax = 1): { ring: XY[]; e: XY[] } {
  const ring: XY[] = [];
  const e: XY[] = [];
  const r2 = (v: number) => +v.toFixed(2);
  if (geo === GEO_CIRC) {
    const R = off(CIRC.W / 2, CIRC.D);
    for (let i = 0; i < 48; i++) {
      const a = (2 * Math.PI * i) / 48;
      ring.push([r2(CIRC.c[0] + R * Math.cos(a)), r2(CIRC.c[1] + R * Math.sin(a))]);
      e.push([+Math.cos(a).toFixed(4), +Math.sin(a).toFixed(4)]);
    }
    return { ring, e };
  }
  const N = 48;
  const left: { p: XY; n: XY }[] = [];
  const right: { p: XY; n: XY }[] = [];
  for (let i = 0; i <= N; i++) {
    const tt = tMin + ((tMax - tMin) * i) / N;
    const { p, nrm } = pathAt(tt);
    const R = off(selWidth(tt) / 2, selDepth(tt));
    left.push({ p: [p[0] + R * nrm[0], p[1] + R * nrm[1]], n: nrm });
    right.push({ p: [p[0] - R * nrm[0], p[1] - R * nrm[1]], n: [-nrm[0], -nrm[1]] });
  }
  const cap = (tt: number, sgn: 1 | -1) => {
    const { p, nrm } = pathAt(tt);
    const R = off(selWidth(tt) / 2, selDepth(tt));
    const tang: XY = [-nrm[1] * sgn, nrm[0] * sgn];
    const pts: { p: XY; n: XY }[] = [];
    for (let i = 1; i < 8; i++) {
      const a = (Math.PI * i) / 8;
      const dir: XY = [Math.cos(a) * nrm[0] * sgn + Math.sin(a) * tang[0] * -1, Math.cos(a) * nrm[1] * sgn + Math.sin(a) * tang[1] * -1];
      pts.push({ p: [p[0] + R * dir[0], p[1] + R * dir[1]], n: dir });
    }
    return pts;
  };
  const loop = [...left, ...cap(tMax, 1), ...right.reverse(), ...cap(tMin, -1)];
  for (const x of loop) {
    ring.push([r2(x.p[0]), r2(x.p[1])]);
    e.push([+x.n[0].toFixed(4), +x.n[1].toFixed(4)]);
  }
  return { ring, e };
}

/** 목 derive(§5.2): 바닥 바깥 이웃에서 평행하지 않은 요소로 BFS → 사면, 평행 요소에서 멈춤. 공칭 치수·단면·평면 자료는 합성 해석식 */
export function selDerive(sel: DoeSelectionIn, st: DoeSettingsOut): { out: DoeDeriveOut; beads: DeriveBead[] } {
  const m = selMesh();
  const t = m.topo;
  const idx = elemIndex(m.elemId, m.elemType);
  const theta = sel.feature_angle_deg ?? st.select?.feature_angle_deg ?? 15;
  const cosT = Math.cos((theta * Math.PI) / 180);
  const taken = new Int32Array(t.nElems).fill(-1);
  sel.beads.forEach((b, bi) => {
    for (const tr of b.tiers) for (const e of fromElemSet(tr.floor, idx).elems) taken[e] = bi;
    for (const e of fromElemSet(b.slope?.add ?? EMPTY_SET(), idx).elems) taken[e] = bi;
  });
  const excl = new Uint8Array(t.nElems);
  for (const e of fromElemSet(sel.exclude ?? EMPTY_SET(), idx).elems) excl[e] = 1;
  const fixedUser = new Uint8Array(m.n);
  for (const e of fromElemSet(sel.fixed_user ?? EMPTY_SET(), idx).elems) for (const v of m.quads[e]) fixedUser[v] = 1;
  const isFixed = (v: number) => !!(m.fixed[v] || fixedUser[v]);
  const blendCfg = st.select?.blend ?? { min_mm: 15, max_mm: 200, k: 8 };
  const warnings: DoeWarning[] = [];
  // v0.16.1 섬 판정(§5.2) — 브라우저 enclosedComponents 와 같은 함수(서버 흉내). 주인 = bead·16 + k
  const own = new Int32Array(t.nElems).fill(-1);
  const cand = new Uint8Array(t.nElems);
  sel.beads.forEach((b, bi) => {
    for (const tr of b.tiers) for (const e of fromElemSet(tr.floor, idx).elems) own[e] = bi * 16 + tr.k;
    for (const e of fromElemSet(b.slope?.add ?? EMPTY_SET(), idx).elems) own[e] = -2;
  });
  for (let e = 0; e < t.nElems; e++) {
    if (own[e] === -1 && excl[e]) own[e] = -2;
    if (own[e] === -1) cand[e] = 1;
  }
  const nb = new Map<number, Vec3>();
  const nOf = (o: number): Vec3 => {
    const bi = Math.floor(o / 16);
    if (!nb.has(bi)) {
      const a: Vec3 = [0, 0, 0];
      for (let e = 0; e < t.nElems; e++) if (own[e] >= 0 && Math.floor(own[e] / 16) === bi) for (let c = 0; c < 3; c++) a[c] += t.normals[e * 3 + c] * t.areas[e];
      const l = Math.hypot(...a) || 1;
      nb.set(bi, [a[0] / l, a[1] / l, a[2] / l]);
    }
    return nb.get(bi)!;
  };
  const islandMax = st.select?.island?.max_mm ?? 40;
  const enc = enclosedComponents(t, cand, own, m.x, nOf, { maxMm: islandMax, ringFrac: st.select?.island?.ring_frac ?? 0.9, outerPoly: (o) => outerPolygons(t, m.x, (e) => own[e] === o, nOf(o)) });
  const isl = new Uint8Array(t.nElems);
  for (const il of enc.islands) for (const e of il.elems) isl[e] = 1;
  const beads: DeriveBead[] = sel.beads.map((b, bi) => {
    const floors = b.tiers.map((tr) => fromElemSet(tr.floor, idx).elems);
    const all = floors.flat();
    const F = new Uint8Array(t.nElems);
    all.forEach((e) => (F[e] = 1));
    let nx = 0;
    let ny = 0;
    let nz = 0;
    for (const e of all) {
      nx += t.normals[e * 3] * t.areas[e];
      ny += t.normals[e * 3 + 1] * t.areas[e];
      nz += t.normals[e * 3 + 2] * t.areas[e];
    }
    const nl = Math.hypot(nx, ny, nz) || 1;
    const depths = floors.map((fl) => (fl.length ? -t.centroids[fl[0] * 3 + 2] : 0));
    const Dmin = Math.min(...depths);
    const S = new Uint8Array(t.nElems);
    const q = [...all];
    const bwarn: DoeWarning[] = [];
    let missZ = 0;
    let missN = 0;
    for (let h = 0; h < q.length; h++) {
      const e = q[h];
      for (const f of t.nbr.subarray(t.nbrPtr[e], t.nbrPtr[e + 1])) {
        if (F[f] || S[f] || excl[f] || isl[f] || (taken[f] >= 0 && taken[f] !== bi)) continue;
        const c = Math.abs((t.normals[f * 3] * nx + t.normals[f * 3 + 1] * ny + t.normals[f * 3 + 2] * nz) / nl);
        if (c + 1e-12 >= cosT) {
          const z = -t.centroids[f * 3 + 2];
          if (z > 1 && z < Dmin - 1) {
            missZ = +z.toFixed(1);
            missN++;
          }
          continue;
        }
        S[f] = 1;
        q.push(f);
      }
    }
    const suggested = [...S.keys()].filter((e) => S[e]);
    const add = fromElemSet(b.slope?.add ?? EMPTY_SET(), idx).elems;
    const rem = fromElemSet(b.slope?.remove ?? EMPTY_SET(), idx).elems;
    for (const e of add) S[e] = 1;
    for (const e of rem) S[e] = 0;
    for (let e = 0; e < t.nElems; e++) if (excl[e]) S[e] = 0;
    const myIsl = enc.islands.filter((il) => Math.floor(il.owner / 16) === bi);
    const I = new Uint8Array(t.nElems);
    for (const il of myIsl) for (const e of il.elems) I[e] = 1;
    for (const x of enc.tooLarge.filter((y) => Math.floor(y.owner / 16) === bi))
      bwarn.push({ code: "SELECT_ISLAND_TOO_LARGE", bead: b.id, n_elems: x.nElems, size_mm: +x.sizeMm.toFixed(1), message: `${b.name}: 둘러싸인 영역(요소 ${x.nElems}개, ${x.sizeMm.toFixed(1)} mm)이 섬 크기 상한보다 커서 섬으로 보지 않았습니다` });
    if (missN) bwarn.push({ code: "SELECT_TIER_MISSING", bead: b.id, z_mm: missZ, n_elems: missN, message: `${b.name}: 고르지 않은 단이 있습니다(깊이 ${missZ} mm, 요소 ${missN}개)` });
    const inB = (e: number) => !!(F[e] || S[e] || I[e]);
    const bn = boundaryNodes(t, inB);
    const nodes = new Set<number>();
    for (let e = 0; e < t.nElems; e++) if (inB(e)) for (const v of m.quads[e]) nodes.add(v);
    const nBoundary = bn.reduce((s, v) => s + v, 0);
    const f0 = all[0] ?? 0;
    const geo = Math.hypot(t.centroids[f0 * 3] - CIRC.c[0], t.centroids[f0 * 3 + 1] - CIRC.c[1]) < CIRC.W ? GEO_CIRC : GEO_PATH;
    const W_nom = geo === GEO_CIRC ? CIRC.W : 60;
    const W_min = geo === GEO_CIRC ? CIRC.W : 51;
    const W_max = geo === GEO_CIRC ? CIRC.W : 69;
    const tiers = floors.map((fl, i) => {
      const zs = fl.flatMap((e) => m.quads[e].map((v) => -m.x[v * 3 + 2])).sort((p, r) => p - r);
      const D = zs.length ? zs[Math.floor(zs.length / 2)] : 0;
      const pl = zs.length ? zs[Math.floor((zs.length - 1) * 0.95)] - zs[Math.floor((zs.length - 1) * 0.05)] : 0;
      return { k: i + 1, n_elems: fl.length, D_nom: +D.toFixed(2), normal: [0, 0, -1] as [number, number, number], planarity_mm: +pl.toFixed(3) };
    });
    // 블렌딩 반경(§5.6)
    const auto = Math.max(blendCfg.min_mm, (blendCfg.k ?? 8) * ((W_nom * 1.2 - W_nom) / 2), 3 * SEL_H);
    let df = Infinity;
    for (let v = 0; v < m.n; v++) {
      if (!isFixed(v) || nodes.has(v)) continue;
      const h = geo.hit(m.x[v * 3], m.x[v * 3 + 1]);
      df = Math.min(df, h.d - h.a);
    }
    let blend = typeof b.blend_mm === "number" ? b.blend_mm : auto;
    let clipped = false;
    if (b.blend_mm === "auto" && blend > df - 3) {
      blend = Math.max(blendCfg.min_mm / 2, df - 3);
      clipped = true;
      bwarn.push({ code: "SELECT_BLEND_CLIPPED", bead: b.id, message: `${b.name}: 체결부(경계에서 ${df.toFixed(1)} mm) 앞에서 블렌딩 반경을 ${blend.toFixed(1)} mm 로 줄였습니다` });
    }
    let inBlend = 0;
    let inBeadN = 0;
    for (let v = 0; v < m.n; v++) {
      if (!isFixed(v)) continue;
      if (nodes.has(v)) inBeadN++;
      else {
        const h = geo.hit(m.x[v * 3], m.x[v * 3 + 1]);
        if (h.d - h.a < blend) inBlend++;
      }
    }
    const warnPolicy = (st.select?.fixed_policy ?? "warn") === "warn";
    if (inBeadN) bwarn.push({ code: "SELECT_FIXED_IN_BEAD", bead: b.id, n: inBeadN, message: warnPolicy ? `${b.name}: 비드 안에 고정 노드 ${inBeadN}개 — 바닥과 같이 움직입니다(경고). 제자리에 두려면 '체결 구멍 둘레 고정'` : `${b.name}: 비드 안에 고정 노드 ${inBeadN}개 — 그 비드 변수는 기본 제외` });
    if (inBlend) bwarn.push({ code: "SELECT_FIXED_IN_BLEND", bead: b.id, n: inBlend, message: warnPolicy ? `${b.name}: 블렌딩 범위 안 고정 노드 ${inBlend}개 — 폭을 바꾼 안에 '체결 위치 어긋남' 경고가 붙습니다` : `${b.name}: 블렌딩 범위 안 고정 노드 ${inBlend}개 — 폭을 바꾼 안은 고정 침범으로 제외됩니다` });
    const holdOn = b.hold_fixed === 1;
    const nFix = inBeadN + inBlend;
    if (holdOn && !nFix) bwarn.push({ code: "SELECT_HOLD_NO_FIXED", bead: b.id, message: `${b.name}: '체결 구멍 둘레 고정'을 켰지만 이 비드에 고정 노드가 없습니다` });
    const outer = ringOf(geo, (a) => a);
    // 단면(§7.1): 경로 t = 0.3 의 폭 방향, s = 중심 기준(−: 왼쪽), z = 깊이(+ 아래)
    const tt = 0.3;
    const a0 = geo === GEO_CIRC ? CIRC.W / 2 : selWidth(tt) / 2;
    const D0 = geo === GEO_CIRC ? CIRC.D : selDepth(tt);
    const r0 = D0 / SLOPE_TAN;
    const fl0 = a0 - r0;
    const sec = { s: [] as number[], z: [] as number[], dzd: [] as number[], dsw: [] as number[] };
    for (let i = 0; i <= 40; i++) {
      const sv = -(a0 + 15) + (2 * (a0 + 15) * i) / 40;
      const as = Math.abs(sv);
      const frac = Math.max(0, Math.min(1, (a0 - as) / r0));
      const tq = Math.max(0, (as - a0) / blend);
      const ds = as <= fl0 ? (0.5 * sv) / fl0 : as <= a0 ? 0.5 * Math.sign(sv) : tq < 1 ? 0.5 * Math.sign(sv) * (1 - tq) ** 4 * (4 * tq + 1) : 0;
      sec.s.push(+sv.toFixed(2));
      sec.z.push(+(D0 * frac).toFixed(3));
      sec.dzd.push(+frac.toFixed(4));
      sec.dsw.push(+ds.toFixed(4));
    }
    const range_default: DoeBeadDerived["range_default"] = {
      D: Object.fromEntries(tiers.map((tr) => [String(tr.k), [+Math.max(1, tr.D_nom * 0.7).toFixed(1), +(tr.D_nom * 1.3).toFixed(1)] as XY])),
      W: [+(W_nom * 0.8).toFixed(1), +(W_nom * 1.2).toFixed(1)],
    };
    const slopeN = S.reduce((s, v) => s + v, 0);
    const derived: DoeBeadDerived = {
      id: b.id,
      name: b.name,
      n_elems: all.length + slopeN + I.reduce((s2, v) => s2 + v, 0),
      n_nodes: nodes.size,
      tiers,
      slope: { n_elems: slopeN, elems: toElemSet([...S.keys()].filter((e) => S[e]), m.elemId, m.elemType), suggested_n: suggested.length, edited: add.length + rem.length > 0 },
      boundary: { loops: [{ closed: true, n_nodes: nBoundary, length_mm: +outer.ring.reduce((s, p, i) => s + Math.hypot(p[0] - outer.ring[(i + 1) % outer.ring.length][0], p[1] - outer.ring[(i + 1) % outer.ring.length][1]), 0).toFixed(1) }], n_nodes: nBoundary },
      W_nom,
      W_min,
      W_max,
      sense: "concave",
      blend_mm: +blend.toFixed(1),
      blend_clipped: clipped,
      fixed_in_bead_n: inBeadN,
      fixed_in_blend_n: inBlend,
      plan: { ring_ab: [outer.ring], e_ab: [outer.e] },
      section: { s: sec.s, z: sec.z, dz_dD: Object.fromEntries(tiers.map((tr) => [String(tr.k), tr.k === 1 ? sec.dzd : sec.dzd.map(() => 0)])), ds_dW: sec.dsw, dz_dW: sec.dsw.map(() => 0) },
      range_default,
      warnings: bwarn,
      islands: myIsl.map((il) => ({ k: il.owner % 16, n_elems: il.elems.length, n_nodes: il.rim.length + il.interior.length, elems: toElemSet(il.elems, m.elemId, m.elemType), rim_n: il.rim.length, size_mm: +il.sizeMm.toFixed(1), free_loops: 0 })),
      holes: { n: 0, n_nodes: 0 },
      inner_loops_n: 0,
      hold_fixed: holdOn ? 1 : 0,
      hold: holdOn && nFix ? { n_ring_nodes: nFix * 2, n_blend_nodes: nFix * 6, n_fixed: nFix } : null,
    };
    warnings.push(...bwarn);
    return { floors, slope: S, suggested, geo, derived, islands: myIsl.flatMap((il) => il.elems) };
  });
  const scanN = m.fixed.reduce((s, v) => s + v, 0);
  const userN = fixedUser.reduce((s, v) => s + v, 0);
  const out: DoeDeriveOut = {
    sha256: selSha(sel),
    mesh_sha256: selManifest().mesh_sha256,
    beads: beads.map((x) => x.derived),
    fixed: { scan_n: scanN, user_n: userN, source: scanN && userN ? "scan+user" : scanN ? "scan" : userN ? "user" : "none" },
    warnings,
    slope_suggested: Object.fromEntries(sel.beads.map((b, i) => [b.id, toElemSet(beads[i].suggested, m.elemId, m.elemType)])),
    islands_suggested: Object.fromEntries(sel.beads.map((b, i) => [b.id, toElemSet(beads[i].islands, m.elemId, m.elemType)])),
    algo: 2,
  };
  return { out, beads };
}

/** 변수 표(§9 params select). 이름 = <비드 id 대문자>_D<k>·_W, 묶음 대표 = 가장 작은 k */
/** 변수 표(§9). v0.16.1: feasible = 기하 한계(D 하한 = 위 수준 + 1, 상한 ×2.0 · W 상한 ×1.6, SR-D-10), warn 정책이면 비드 안 고정이어도 기본 체크(SR-D-8) */
export function selParams(sel: DoeSelectionIn, d: DoeSelectionDerived, policy: "warn" | "skip" = "warn"): DoeParamsOut {
  const beads: DoeBead[] = [];
  const params: DoeParam[] = [];
  sel.beads.forEach((b, bi) => {
    const x = d.beads[bi];
    const up = b.id.toUpperCase();
    const fixedIn = x.fixed_in_bead_n > 0;
    const off = fixedIn && policy === "skip";
    beads.push({
      id: b.id, k: bi + 1, shape: "select", sense: x.sense, center_ab: x.plan?.ring_ab[0]?.[0] ?? [0, 0], nominal: { depth: x.tiers[0]?.D_nom ?? 0, width: x.W_nom ?? 0 }, fixed_overlap: fixedIn, png: null,
      kind: "select", name: b.name, n_tiers: b.tiers.length, W_nom: x.W_nom, W_min: x.W_min, W_max: x.W_max, blend_mm: x.blend_mm, warnings: x.warnings, islands_n: x.islands?.length ?? 0,
    });
    const linked = new Set<number>();
    for (const tr of x.tiers) {
      if (linked.has(tr.k)) continue;
      const g = (b.links ?? []).find((l) => l.includes(tr.k));
      g?.forEach((k) => linked.add(k));
      const r = x.range_default.D[String(tr.k)];
      const above = tr.k > 1 ? x.tiers.find((y) => y.k === tr.k - 1)?.D_nom ?? 0 : 0;
      const feas: XY = [+(above + 1).toFixed(1), +(tr.D_nom * 2).toFixed(1)];
      params.push({ name: `${up}_D${tr.k}`, type: "D", bead: b.id, tier: tr.k, nominal: tr.D_nom, feasible: tr.k > 1 ? [Math.min(feas[0], r[0]), feas[1]] : [Math.min(1, r[0]), feas[1]], feasible_source: "estimate", default_range: r, use_default: !off, group_members: g ? g.filter((k) => k !== tr.k).map((k) => `${up}_D${k}`) : [] });
    }
    if (x.range_default.W && x.W_nom != null)
      params.push({ name: `${up}_W`, type: "W", bead: b.id, nominal: x.W_nom, feasible: [x.range_default.W[0], +(x.W_nom * 1.6).toFixed(1)], feasible_source: "estimate", default_range: x.range_default.W, use_default: !off, group_members: [] });
  });
  return { beads, params, warnings: d.warnings ?? [] };
}

/** 평면도(§7.1 select) */
export function selPlan(sel: DoeSelectionIn, st: DoeSettingsOut): DoePlanOut {
  const m = selMesh();
  const t = m.topo;
  const { out, beads } = selDerive(sel, st);
  const points: [number, number, number][] = [];
  for (let e = 0; e < t.nElems; e += 2) points.push([+t.centroids[e * 3].toFixed(1), +t.centroids[e * 3 + 1].toFixed(1), 1]);
  const nodes_ab: XY[] = [];
  for (let v = 0; v < m.n; v += 2) nodes_ab.push([m.x[v * 3], m.x[v * 3 + 1]]);
  const fixed: DoePlanOut["fixed"] = [];
  for (let v = 0; v < m.n; v++) if (m.fixed[v]) fixed.push({ a: m.x[v * 3], b: m.x[v * 3 + 1] });
  const Lx = (SEL_NX - 1) * SEL_H;
  const Ly = (SEL_NY - 1) * SEL_H;
  return {
    frame: { a_range: [0, Lx], b_range: [0, Ly] },
    outline: [[0, 0], [Lx, 0], [Lx, Ly], [0, Ly]],
    holes: [],
    elems: { n_total: t.nElems, decimated: true, points },
    beads: sel.beads.map((b, i) => {
      const x = out.beads[i];
      const ring = x.plan?.ring_ab ?? [[]];
      const geo = beads[i].geo;
      const c = ring[0].reduce<XY>((s, p) => [s[0] + p[0] / ring[0].length, s[1] + p[1] / ring[0].length], [0, 0]);
      const tierRings = x.tiers.map((tr) => ({
        k: tr.k,
        ring_ab: [geo === GEO_CIRC ? ringOf(geo, (a, D) => a - D / SLOPE_TAN).ring : tr.k === 1 ? ringOf(geo, (a, D) => a - D / SLOPE_TAN, 0, 0.635).ring : ringOf(geo, (a, D) => a - D / SLOPE_TAN, 0.675, 1).ring],
      }));
      return { id: b.id, name: b.name, ring: ring[0], ring_ab: ring, e_ab: x.plan?.e_ab ?? [[]], label_ab: geo === GEO_PATH ? ([180, 352] as XY) : ([c[0], c[1] + 34] as XY), tiers: tierRings, section: x.section ?? null };
    }),
    nodes_ab,
    fixed,
    a_points: [],
    load_points: [],
    links: [],
  };
}

/** 기저(§5 의 단순 흉내 — 해석 형상 기준): 변수 순서 = params 순서 */
export function selBasis(sel: DoeSelectionIn, st: DoeSettingsOut): { meta: DoeBasisMeta; bin: ArrayBuffer; params: DoeParam[] } {
  const m = selMesh();
  const { out, beads } = selDerive(sel, st);
  const ps = selParams(sel, out);
  const vars: { idx: number[]; vec: number[] }[] = [];
  const meta: DoeBasisMeta = { schema: "esl/bead_select_basis/1", sha256: "", selection_sha256: out.sha256, n_nodes: m.n, vars: [] };
  for (const p of ps.params) {
    const bi = sel.beads.findIndex((b) => b.id === p.bead);
    const B = beads[bi];
    const der = out.beads[bi];
    const idx: number[] = [];
    const vec: number[] = [];
    const nodeTier = new Int32Array(m.n);
    B.floors.forEach((fl, i) => fl.forEach((e) => m.quads[e].forEach((v) => (nodeTier[v] = i + 1))));
    // v0.16.1 섬 = 그 단 바닥과 같은 변위(평면 바닥 → 둘레 평균 = 바닥 값, SR-D-5)
    for (const il of der.islands ?? []) for (const e of fromElemSet(il.elems, elemIndex(m.elemId, m.elemType)).elems) m.quads[e].forEach((v) => (nodeTier[v] ||= il.k));
    const slopeNode = new Uint8Array(m.n);
    for (let e = 0; e < m.topo.nElems; e++) if (B.slope[e]) m.quads[e].forEach((v) => (slopeNode[v] = 1));
    if (p.type === "D") {
      const ks = [p.tier!, ...p.group_members.map((g) => Number(g.split("_D")[1]))];
      for (let v = 0; v < m.n; v++) {
        let s = 0;
        if (nodeTier[v]) s = ks.includes(nodeTier[v]) ? 1 : 0;
        else if (slopeNode[v]) {
          const h = B.geo.hit(m.x[v * 3], m.x[v * 3 + 1]);
          const tierHere = B.geo === GEO_CIRC || h.t < 0.655 ? 1 : 2;
          if (h.d < h.a && ks.includes(tierHere)) s = Math.max(0, Math.min(1, -m.x[v * 3 + 2] / der.tiers[tierHere - 1].D_nom));
        }
        if (s > 0) {
          idx.push(v);
          vec.push(0, 0, -s);
        }
      }
    } else {
      const R = der.blend_mm;
      for (let v = 0; v < m.n; v++) {
        const h = B.geo.hit(m.x[v * 3], m.x[v * 3 + 1]);
        const fl = h.a - h.D / SLOPE_TAN;
        let w = 0;
        if (h.d <= fl) w = 0.5 * (h.d / Math.max(fl, 1e-9));
        else if (h.d <= h.a) w = 0.5;
        else if (h.d < h.a + R) {
          const tq = (h.d - h.a) / R;
          w = 0.5 * (1 - tq) ** 4 * (4 * tq + 1);
        }
        if (w > 1e-9) {
          idx.push(v);
          vec.push(w * h.dir[0], w * h.dir[1], 0);
        }
      }
    }
    vars.push({ idx, vec });
    meta.vars.push({ name: p.name, type: p.type as "D" | "W", bead: p.bead, nominal: p.nominal, n: idx.length, R_mm: p.type === "W" ? der.blend_mm : null });
  }
  meta.sha256 = (fnv(`basis:${out.sha256}`) + fnv(out.sha256)).padEnd(64, "b");
  return { meta, bin: writeBasis(vars), params: ps.params };
}

/** 미리보기 셀 상태(목·결정적): 폭을 공칭보다 15 % 넘게 줄이면 뒤집힘(제외), 안 번호 %13 = 5·%10 = 9 품질 FAIL, %11 = 4 고정 침범 — v0.16.1 기본 warn 정책이면 READY + 경고 */
export function selCellStatus(id: string, values: Record<string, number>, params: DoeParam[], policy: { fixed: "warn" | "skip"; quality: "warn" | "skip" } = { fixed: "warn", quality: "warn" }): { status: DoeDesignStatus; code: string | null; thumb: boolean; fixed_viol?: DoeFixedViol; warnings?: DoeCellWarning[] } {
  const i = Number(id.slice(1));
  const narrow = params.some((p) => p.type === "W" && values[p.name] != null && values[p.name] < p.nominal * 0.85);
  // SR-D-1 순서: 뒤집힘(항상 제외) → 고정(fixed_policy) → 품질(fail_policy)
  if (narrow) return { status: "FAILED_MESH", code: "SELECT_MORPH_INVERTED", thumb: true };
  const qFail = i % 13 === 5 || i % 10 === 9;
  if (i % 11 === 4) {
    // v0.15.1 코어 fixed_viol 흉내: 폭 변수가 고정 고리(b1 아래)를 37 노드 움직임
    const w = params.find((p) => p.type === "W") ?? params[0];
    const m = selMesh();
    const node_idx = [...m.fixed.keys()].filter((k) => m.fixed[k]).slice(0, 37);
    const mm = Math.round(Math.abs((values[w?.name ?? ""] ?? 0) - (w?.nominal ?? 0)) * 10) / 100 || 0.8;
    const fixed_viol = { n: node_idx.length, max_mm: mm, bead_vars: w ? [{ name: w.name, bead: w.bead, n: node_idx.length, max_mm: mm }] : [], node_idx };
    if (policy.fixed === "skip") return { status: "SKIPPED_FIXED", code: "SELECT_FIXED_VIOLATION", thumb: true, fixed_viol };
    const warnings: DoeCellWarning[] = [{ code: "SELECT_FIXED_MOVED", n: node_idx.length, max_mm: mm }];
    if (qFail && policy.quality === "warn") warnings.push({ code: "SELECT_QUALITY_WARN", new_fail: 412, new_fail_ratio: 0.019 });
    else if (qFail) return { status: "FAILED_MESH", code: "SELECT_QUALITY_FAIL", thumb: true, fixed_viol };
    return { status: "READY", code: null, thumb: true, fixed_viol, warnings };
  }
  if (qFail) return policy.quality === "skip" ? { status: "FAILED_MESH", code: "SELECT_QUALITY_FAIL", thumb: true } : { status: "READY", code: null, thumb: true, warnings: [{ code: "SELECT_QUALITY_WARN", new_fail: 412, new_fail_ratio: 0.019 }] };
  return { status: "READY", code: null, thumb: true };
}

/** 썸네일 색 범위 V = max |깊이 변화| (READY 안, 0 이면 1 mm) */
export function selColorMax(cells: { values: Record<string, number>; status: DoeDesignStatus }[], params: DoeParam[]): number {
  let v = 0;
  for (const c of cells) if (c.status === "READY") for (const p of params) if (p.type === "D" && c.values[p.name] != null) v = Math.max(v, Math.abs(c.values[p.name] - p.nominal));
  return +(v || 1).toFixed(2);
}

/** 목 썸네일(SVG — 실제는 워커 3D 음영 PNG): 비드를 깊이 변화(파랑 깊어짐·빨강 얕아짐, 같은 ±V) 로 칠함 */
export function selThumbSvg(values: Record<string, number> | null, params: DoeParam[], vmax: number, status: DoeDesignStatus | "NOMINAL") {
  const W = 320;
  const Hh = 240;
  const Lx = (SEL_NX - 1) * SEL_H;
  const Ly = (SEL_NY - 1) * SEL_H;
  const k = (W - 40) / Lx;
  const sx = (a: number) => 20 + a * k;
  const sy = (b: number) => 26 + (1 - b / Ly) * (Hh - 52) * 0.9;
  const dv = (name: string) => {
    const p = params.find((x) => x.name === name);
    return values && p && values[name] != null ? values[name] - p.nominal : 0;
  };
  const col = (v: number) => {
    if (!values) return "rgb(172,178,188)";
    const t2 = Math.max(-1, Math.min(1, v / (vmax || 1)));
    const c = t2 >= 0 ? [247 - 214 * t2, 247 - 145 * t2, 247 - 75 * t2] : [247 + 0 * t2, 247 + 160 * t2, 247 + 175 * t2];
    return `rgb(${c.map((x) => Math.round(x)).join(",")})`;
  };
  const path = SEL_PATH.map(([a, b]) => `${sx(a).toFixed(1)},${sy(b).toFixed(1)}`).join(" ");
  const w1 = (60 + dv("B1_W")) * k;
  const dim = status !== "NOMINAL" && status !== "READY" ? ' opacity="0.5"' : "";
  const plate = `${sx(0)},${sy(0)} ${sx(Lx)},${sy(0)} ${sx(Lx) - 14},${sy(Ly)} ${sx(0) + 14},${sy(Ly)}`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${Hh}" width="${W}" height="${Hh}"><rect width="${W}" height="${Hh}" fill="#eef0f3"/><g${dim}><polygon points="${plate}" fill="#c9ced6" stroke="#5c6470"/><polyline points="${path}" fill="none" stroke="#3d4450" stroke-width="${(w1 + 3).toFixed(1)}" stroke-linejoin="round" stroke-linecap="round"/><polyline points="${path}" fill="none" stroke="${col(dv("B1_D1"))}" stroke-width="${w1.toFixed(1)}" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${sx(CIRC.c[0])}" cy="${sy(CIRC.c[1])}" r="${(((CIRC.W + dv("B2_W")) / 2) * k).toFixed(1)}" fill="${col(dv("B2_D1"))}" stroke="#3d4450"/></g></svg>`;
}
