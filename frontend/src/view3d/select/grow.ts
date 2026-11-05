// 클릭 + 확장(esl_bead_select.md 확정 3·§3-3-2·R-BS-1): seed 요소 법선 기준 BFS — 이웃 누적이 아니라 seed 법선과의 각으로 판정해
// 필렛·곡면에서 조금씩 새는 것을 막는다. 각 ≤ θ(기본 select.feature_angle_deg) 인 연결 요소만. 법선 부호(요소 연결 순서)는 무시(|cos|).
import { neighbors, type MeshTopo } from "./adjacency";

/** 두 단위 법선 사이 각(°, 부호 무시 0..90) */
export function normalAngleDeg(t: MeshTopo, a: number, b: number): number {
  const n = t.normals;
  const d = Math.abs(n[a * 3] * n[b * 3] + n[a * 3 + 1] * n[b * 3 + 1] + n[a * 3 + 2] * n[b * 3 + 2]);
  return (Math.acos(Math.min(1, d)) * 180) / Math.PI;
}

/**
 * seed 에서 연결·같은 법선(각 ≤ thetaDeg) 요소 집합(오름차순 요소 번호). blocked(e) = true 인 요소는 넣지도 지나가지도 않는다(다른 비드 층 등).
 * seed 가 blocked 면 빈 배열.
 */
export function grow(t: MeshTopo, seed: number, thetaDeg: number, blocked?: (e: number) => boolean): number[] {
  if (seed < 0 || seed >= t.nElems || blocked?.(seed)) return [];
  const cosT = Math.cos((thetaDeg * Math.PI) / 180);
  const n = t.normals;
  const sx = n[seed * 3];
  const sy = n[seed * 3 + 1];
  const sz = n[seed * 3 + 2];
  const seen = new Uint8Array(t.nElems);
  const queue = new Uint32Array(t.nElems);
  let head = 0;
  let tail = 0;
  queue[tail++] = seed;
  seen[seed] = 1;
  while (head < tail) {
    const e = queue[head++];
    for (const f of neighbors(t, e)) {
      if (seen[f]) continue;
      seen[f] = 1;
      if (blocked?.(f)) continue;
      // 각 ≤ θ ⇔ |cos| ≥ cos θ (작은 수치 여유 1e-12)
      if (Math.abs(sx * n[f * 3] + sy * n[f * 3 + 1] + sz * n[f * 3 + 2]) + 1e-12 < cosT) continue;
      queue[tail++] = f;
    }
  }
  return Array.from(queue.subarray(0, tail)).sort((a, b) => a - b);
}

// ---------------------------------------------------------------- v0.16.1 섬 자동 포함(esl_select_relax.md SR-D-14·§5.2 — 코어 esl.mesh.features.enclosed_components 거울)
// 섬 = 후보 요소(cand)의 연결 성분 K 중 (a) K 밖 이웃이 모두 한 주인(owner ≥ 0)이고, (b) 가장 큰 성분(요소 수 최대, 동률 = 최소 요소 번호)이 아니며,
// (c) K 노드의 평면(주인 법선에 수직) bbox 대각 ≤ maxMm, (d) (outerPoly 가 있으면) K 요소 중심 평균이 그 주인 바깥 고리 다각형 안(짝홀).
// (a)를 만족하고 (c)·(d) 를 못 넘으면 tooLarge. 성분 번호 = 최소 요소 번호 순(결정적). 표시용 — 저장 대상 아님(서버 derive 가 원본).

export type Vec3 = [number, number, number];

export interface Island {
  owner: number;
  /** 요소 번호(오름차순) */
  elems: number[];
  /** 둘레 노드 = 섬 노드 ∩ 주인 요소 노드 */
  rim: number[];
  interior: number[];
  sizeMm: number;
}
export interface EnclosedOut {
  islands: Island[];
  tooLarge: { owner: number; nElems: number; sizeMm: number }[];
}

/** 법선 n 에 수직인 평면의 정규 직교 기저(u, v) — u = n × (|n| 성분이 가장 작은 좌표축, 동률 = 앞 축) */
export function planeBasis(n: Vec3): [Vec3, Vec3] {
  const l = Math.hypot(n[0], n[1], n[2]) || 1;
  const z: Vec3 = [n[0] / l, n[1] / l, n[2] / l];
  const ax = [Math.abs(z[0]), Math.abs(z[1]), Math.abs(z[2])];
  const k = ax[0] <= ax[1] && ax[0] <= ax[2] ? 0 : ax[1] <= ax[2] ? 1 : 2;
  const a: Vec3 = [0, 0, 0];
  a[k] = 1;
  const cx = (p: Vec3, q: Vec3): Vec3 => [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]];
  const u = cx(z, a);
  const ul = Math.hypot(u[0], u[1], u[2]) || 1;
  const uu: Vec3 = [u[0] / ul, u[1] / ul, u[2] / ul];
  return [uu, cx(z, uu)];
}

/** 점 → 평면 좌표 */
const proj = (X: ArrayLike<number>, v: number, b: [Vec3, Vec3]): [number, number] => {
  const x = X[v * 3];
  const y = X[v * 3 + 1];
  const z = X[v * 3 + 2];
  return [x * b[0][0] + y * b[0][1] + z * b[0][2], x * b[1][0] + y * b[1][1] + z * b[1][2]];
};

/** 짝홀 규칙 점-다각형(평면 좌표 [x0,y0,x1,y1,…]) */
export function inPoly2(px: number, py: number, poly: ArrayLike<number>): boolean {
  let inside = false;
  const n = poly.length / 2;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = poly[i * 2];
    const yi = poly[i * 2 + 1];
    const xj = poly[j * 2];
    const yj = poly[j * 2 + 1];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/**
 * 마스크 요소 집합의 경계 고리(노드 순서) — 경계 모서리 = 마스크 요소 1개만 쓰는 모서리. 닫힘 = 시작 노드로 돌아옴.
 * 분기 노드(차수 > 2)는 쓰지 않은 모서리를 번호 순으로 따라간다(결정적).
 */
export function maskLoops(t: MeshTopo, mask: (e: number) => boolean): { nodes: number[]; closed: boolean }[] {
  const nE = t.edgePtr.length - 1;
  const ea: number[] = [];
  for (let i = 0; i < nE; i++) {
    let c = 0;
    for (let k = t.edgePtr[i]; k < t.edgePtr[i + 1]; k++) if (mask(t.edgeElems[k])) c++;
    if (c === 1) ea.push(i);
  }
  const adj = new Map<number, number[]>();
  for (const i of ea) {
    const a = t.edges[i * 2];
    const b = t.edges[i * 2 + 1];
    (adj.get(a) ?? adj.set(a, []).get(a)!).push(i);
    (adj.get(b) ?? adj.set(b, []).get(b)!).push(i);
  }
  const used = new Set<number>();
  const loops: { nodes: number[]; closed: boolean }[] = [];
  for (const i0 of ea) {
    if (used.has(i0)) continue;
    used.add(i0);
    const start = t.edges[i0 * 2];
    let cur = t.edges[i0 * 2 + 1];
    const nodes = [start, cur];
    let closed = false;
    for (;;) {
      if (cur === start) {
        closed = true;
        nodes.pop();
        break;
      }
      const nx = (adj.get(cur) ?? []).find((j) => !used.has(j));
      if (nx === undefined) break;
      used.add(nx);
      cur = t.edges[nx * 2] === cur ? t.edges[nx * 2 + 1] : t.edges[nx * 2];
      nodes.push(cur);
    }
    loops.push({ nodes, closed });
  }
  return loops;
}

/** 볼록 껍질(평면 좌표, 단조 사슬) */
function hull2(pts: [number, number][]): number[] {
  const p = [...pts].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return p.flat();
  const cr = (o: number[], a: number[], b: number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo: [number, number][] = [];
  for (const q of p) {
    while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop();
    lo.push(q);
  }
  const up: [number, number][] = [];
  for (let i = p.length - 1; i >= 0; i--) {
    const q = p[i];
    while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop();
    up.push(q);
  }
  return [...lo.slice(0, -1), ...up.slice(0, -1)].flat();
}

/** 주인 요소 집합의 바깥 고리 다각형(평면 좌표): 닫힌 고리 중 |넓이| 최대, 닫힌 고리가 없으면 노드 볼록 껍질(§5.2-3d) */
export function outerPolygon(t: MeshTopo, X: ArrayLike<number>, mask: (e: number) => boolean, n: Vec3): number[] {
  const b = planeBasis(n);
  let best: number[] | null = null;
  let bestA = -1;
  for (const lp of maskLoops(t, mask)) {
    if (!lp.closed || lp.nodes.length < 3) continue;
    const poly = lp.nodes.flatMap((v) => proj(X, v, b));
    let a = 0;
    for (let i = 0, m = poly.length / 2; i < m; i++) {
      const j = (i + 1) % m;
      a += poly[i * 2] * poly[j * 2 + 1] - poly[j * 2] * poly[i * 2 + 1];
    }
    if (Math.abs(a) > bestA) {
      bestA = Math.abs(a);
      best = poly;
    }
  }
  if (best) return best;
  const pts: [number, number][] = [];
  const seen = new Uint8Array(t.nNodes);
  for (let e = 0; e < t.nElems; e++) {
    if (!mask(e)) continue;
    for (let k = t.elemNodesPtr[e]; k < t.elemNodesPtr[e + 1]; k++) {
      const v = t.elemNodes[k];
      if (!seen[v]) {
        seen[v] = 1;
        pts.push(proj(X, v, b));
      }
    }
  }
  return hull2(pts);
}

/**
 * §5.2 일반형(코어 enclosed_components 거울). cand = 후보 요소(1), owner = 요소별 주인(≥ 0 주인, −1 후보, −2 막힘),
 * X = 노드 좌표(3·nNodes), nRef(owner) = 그 주인의 평면 법선, outerPoly(owner) = 그 주인 바깥 고리(평면 좌표, null = 검사 안 함).
 */
export function enclosedComponents(
  t: MeshTopo,
  cand: Uint8Array,
  owner: Int32Array,
  X: ArrayLike<number>,
  nRef: (owner: number) => Vec3,
  opts: { maxMm: number; outerPoly?: (owner: number) => ArrayLike<number> | null },
): EnclosedOut {
  const nE = t.nElems;
  const comp = new Int32Array(nE).fill(-1);
  const queue = new Uint32Array(nE);
  const sizes: number[] = [];
  const starts: number[] = [];
  // 요소 번호 순으로 BFS 시작 → 성분 번호 = 최소 요소 번호 순
  for (let s = 0; s < nE; s++) {
    if (!cand[s] || comp[s] >= 0) continue;
    const c = sizes.length;
    let head = 0;
    let tail = 0;
    queue[tail++] = s;
    comp[s] = c;
    while (head < tail) {
      const e = queue[head++];
      for (let k = t.nbrPtr[e]; k < t.nbrPtr[e + 1]; k++) {
        const f = t.nbr[k];
        if (cand[f] && comp[f] < 0) {
          comp[f] = c;
          queue[tail++] = f;
        }
      }
    }
    sizes.push(tail);
    starts.push(s);
  }
  let largest = -1;
  for (let c = 0; c < sizes.length; c++) if (largest < 0 || sizes[c] > sizes[largest]) largest = c; // 동률 = 앞(최소 요소 번호)
  // (a) 이웃 주인: −1 미정, ≥ 0 하나, −2 둘 이상·막힘
  const nbOwner = new Int32Array(sizes.length).fill(-1);
  for (let e = 0; e < nE; e++) {
    const c = comp[e];
    if (c < 0 || nbOwner[c] === -2) continue;
    for (let k = t.nbrPtr[e]; k < t.nbrPtr[e + 1]; k++) {
      const f = t.nbr[k];
      if (cand[f]) continue;
      const o = owner[f];
      if (o < 0) {
        nbOwner[c] = -2;
        break;
      }
      if (nbOwner[c] === -1) nbOwner[c] = o;
      else if (nbOwner[c] !== o) {
        nbOwner[c] = -2;
        break;
      }
    }
  }
  const members = new Map<number, number[]>();
  for (let e = 0; e < nE; e++) {
    const c = comp[e];
    if (c >= 0 && c !== largest && nbOwner[c] >= 0) (members.get(c) ?? members.set(c, []).get(c)!).push(e);
  }
  const out: EnclosedOut = { islands: [], tooLarge: [] };
  const polyCache = new Map<number, ArrayLike<number> | null>();
  const ownerNodes = new Map<number, Uint8Array>();
  const nodesOfOwner = (o: number) => {
    let m = ownerNodes.get(o);
    if (!m) {
      m = new Uint8Array(t.nNodes);
      for (let e = 0; e < nE; e++) if (owner[e] === o) for (let k = t.elemNodesPtr[e]; k < t.elemNodesPtr[e + 1]; k++) m[t.elemNodes[k]] = 1;
      ownerNodes.set(o, m);
    }
    return m;
  };
  for (const c of [...members.keys()].sort((a, b) => a - b)) {
    const o = nbOwner[c];
    const elems = members.get(c)!;
    const b = planeBasis(nRef(o));
    const nodes = new Set<number>();
    for (const e of elems) for (let k = t.elemNodesPtr[e]; k < t.elemNodesPtr[e + 1]; k++) nodes.add(t.elemNodes[k]);
    let x0 = Infinity;
    let x1 = -Infinity;
    let y0 = Infinity;
    let y1 = -Infinity;
    for (const v of nodes) {
      const [px, py] = proj(X, v, b);
      x0 = Math.min(x0, px);
      x1 = Math.max(x1, px);
      y0 = Math.min(y0, py);
      y1 = Math.max(y1, py);
    }
    const sizeMm = Math.hypot(x1 - x0, y1 - y0);
    let ok = sizeMm <= opts.maxMm;
    if (ok && opts.outerPoly) {
      if (!polyCache.has(o)) polyCache.set(o, opts.outerPoly(o));
      const poly = polyCache.get(o);
      if (poly && poly.length >= 6) {
        let cx = 0;
        let cy = 0;
        let cz = 0;
        for (const e of elems) {
          cx += t.centroids[e * 3];
          cy += t.centroids[e * 3 + 1];
          cz += t.centroids[e * 3 + 2];
        }
        const m = elems.length;
        const p = proj([cx / m, cy / m, cz / m], 0, b);
        ok = inPoly2(p[0], p[1], poly);
      }
    }
    if (!ok) {
      out.tooLarge.push({ owner: o, nElems: elems.length, sizeMm });
      continue;
    }
    const on = nodesOfOwner(o);
    const sorted = [...nodes].sort((a, b2) => a - b2);
    out.islands.push({ owner: o, elems, rim: sorted.filter((v) => on[v]), interior: sorted.filter((v) => !on[v]), sizeMm });
  }
  return out;
}
