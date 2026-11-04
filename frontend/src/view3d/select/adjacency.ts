// 요소 위상(esl_bead_select.md §5.1·§11.2): 삼각형(part.glb 인덱스) + 삼각형→요소(select.bin)에서 요소별 노드·모서리·이웃 CSR.
// 서버 §5.1 과 같은 규칙: 이웃 = 모서리(정렬 노드 쌍) 공유, 비다양체(3개 이상 공유)도 모두 이웃. 4각의 대각선(같은 요소 두 삼각형이 공유)은 모서리가 아님.
// three 에 의존하지 않는 순수 함수(typed array, 22만 요소 ≤ 수백 ms).

export interface MeshTopo {
  nElems: number;
  nNodes: number;
  /** 요소 e 의 노드(정점 번호) = elemNodes[elemNodesPtr[e] .. elemNodesPtr[e+1]) — 중복 없음 */
  elemNodesPtr: Uint32Array;
  elemNodes: Uint32Array;
  /** 요소 이웃 CSR(정렬·중복 없음) */
  nbrPtr: Uint32Array;
  nbr: Uint32Array;
  /** 모서리(대각선 제외) 노드 쌍 a < b — 2·nEdges */
  edges: Uint32Array;
  /** 모서리 i 를 쓰는 요소 = edgeElems[edgePtr[i] .. edgePtr[i+1]) */
  edgePtr: Uint32Array;
  edgeElems: Uint32Array;
  /** 요소 단위 법선(면적 가중 — 4각 = 대각선 외적과 같음), 면적, 중심(노드 평균) */
  normals: Float32Array;
  areas: Float32Array;
  centroids: Float32Array;
}

/** 삼각형 인덱스(3·nTris)·삼각형→요소(nTris)·좌표(3·nNodes) → 위상 */
export function buildTopo(positions: ArrayLike<number>, indices: ArrayLike<number>, tri2elem: ArrayLike<number>, nElems: number): MeshTopo {
  const nTris = tri2elem.length;
  const nNodes = Math.floor(positions.length / 3);
  // ---- 요소별 노드(중복 제거)
  const cnt = new Uint32Array(nElems + 1);
  for (let t = 0; t < nTris; t++) cnt[tri2elem[t] + 1] += 3;
  for (let e = 0; e < nElems; e++) cnt[e + 1] += cnt[e];
  const raw = new Uint32Array(cnt[nElems]);
  const fill = cnt.slice(0, nElems);
  for (let t = 0; t < nTris; t++) {
    const e = tri2elem[t];
    for (let j = 0; j < 3; j++) raw[fill[e]++] = indices[t * 3 + j];
  }
  const elemNodesPtr = new Uint32Array(nElems + 1);
  const tmp: number[] = [];
  const out: number[] = [];
  for (let e = 0; e < nElems; e++) {
    tmp.length = 0;
    for (let k = cnt[e]; k < cnt[e + 1]; k++) if (!tmp.includes(raw[k])) tmp.push(raw[k]);
    for (const v of tmp) out.push(v);
    elemNodesPtr[e + 1] = out.length;
  }
  const elemNodes = Uint32Array.from(out);

  // ---- 법선·면적·중심
  const normals = new Float32Array(nElems * 3);
  const areas = new Float32Array(nElems);
  const centroids = new Float32Array(nElems * 3);
  const acc = new Float64Array(nElems * 3);
  for (let t = 0; t < nTris; t++) {
    const a = indices[t * 3] * 3;
    const b = indices[t * 3 + 1] * 3;
    const c = indices[t * 3 + 2] * 3;
    const ux = positions[b] - positions[a];
    const uy = positions[b + 1] - positions[a + 1];
    const uz = positions[b + 2] - positions[a + 2];
    const vx = positions[c] - positions[a];
    const vy = positions[c + 1] - positions[a + 1];
    const vz = positions[c + 2] - positions[a + 2];
    const e = tri2elem[t] * 3;
    acc[e] += (uy * vz - uz * vy) / 2;
    acc[e + 1] += (uz * vx - ux * vz) / 2;
    acc[e + 2] += (ux * vy - uy * vx) / 2;
  }
  for (let e = 0; e < nElems; e++) {
    const l = Math.hypot(acc[e * 3], acc[e * 3 + 1], acc[e * 3 + 2]);
    areas[e] = l;
    for (let c = 0; c < 3; c++) normals[e * 3 + c] = l > 0 ? acc[e * 3 + c] / l : 0;
    const p0 = elemNodesPtr[e];
    const p1 = elemNodesPtr[e + 1];
    for (let k = p0; k < p1; k++) for (let c = 0; c < 3; c++) centroids[e * 3 + c] += positions[elemNodes[k] * 3 + c] / (p1 - p0);
  }

  // ---- 모서리: 작은 노드 번호로 계수 정렬(버킷) → 버킷 안에서 큰 노드 번호로 묶음
  const m = nTris * 3;
  const ea = new Uint32Array(m);
  const eb = new Uint32Array(m);
  const ee = new Uint32Array(m);
  const bucket = new Uint32Array(nNodes + 1);
  for (let t = 0; t < nTris; t++)
    for (let j = 0; j < 3; j++) {
      const p = indices[t * 3 + j];
      const q = indices[t * 3 + ((j + 1) % 3)];
      const i = t * 3 + j;
      ea[i] = p < q ? p : q;
      eb[i] = p < q ? q : p;
      ee[i] = tri2elem[t];
      bucket[ea[i] + 1]++;
    }
  for (let v = 0; v < nNodes; v++) bucket[v + 1] += bucket[v];
  const ord = new Uint32Array(m);
  const bf = bucket.slice(0, nNodes);
  for (let i = 0; i < m; i++) ord[bf[ea[i]]++] = i;

  const edges: number[] = [];
  const edgePtr: number[] = [0];
  const edgeElems: number[] = [];
  const pairs: number[] = [];
  const grp: number[] = [];
  for (let v = 0; v < nNodes; v++) {
    const s0 = bucket[v];
    const s1 = bucket[v + 1];
    if (s0 === s1) continue;
    const seg = Array.from(ord.subarray(s0, s1)).sort((x, y) => eb[x] - eb[y] || ee[x] - ee[y]);
    for (let i = 0; i < seg.length; ) {
      let j = i;
      while (j + 1 < seg.length && eb[seg[j + 1]] === eb[seg[i]]) j++;
      grp.length = 0;
      for (let k = i; k <= j; k++) if (!grp.includes(ee[seg[k]])) grp.push(ee[seg[k]]);
      // 같은 요소의 두 삼각형만 쓰는 모서리 = 4각 대각선 → 모서리 아님
      const internal = grp.length === 1 && j > i;
      if (!internal) {
        edges.push(v, eb[seg[i]]);
        for (const g of grp) edgeElems.push(g);
        edgePtr.push(edgeElems.length);
        for (let x = 0; x < grp.length; x++) for (let y = 0; y < grp.length; y++) if (x !== y) pairs.push(grp[x], grp[y]);
      }
      i = j + 1;
    }
  }
  // ---- 이웃 CSR(정렬·중복 제거)
  const nc = new Uint32Array(nElems + 1);
  for (let i = 0; i < pairs.length; i += 2) nc[pairs[i] + 1]++;
  for (let e = 0; e < nElems; e++) nc[e + 1] += nc[e];
  const nb = new Uint32Array(nc[nElems]);
  const nf = nc.slice(0, nElems);
  for (let i = 0; i < pairs.length; i += 2) nb[nf[pairs[i]]++] = pairs[i + 1];
  const nbrPtr = new Uint32Array(nElems + 1);
  const nbrOut: number[] = [];
  for (let e = 0; e < nElems; e++) {
    const list = Array.from(nb.subarray(nc[e], nc[e + 1])).sort((x, y) => x - y);
    for (let k = 0; k < list.length; k++) if (k === 0 || list[k] !== list[k - 1]) nbrOut.push(list[k]);
    nbrPtr[e + 1] = nbrOut.length;
  }
  return {
    nElems,
    nNodes,
    elemNodesPtr,
    elemNodes,
    nbrPtr,
    nbr: Uint32Array.from(nbrOut),
    edges: Uint32Array.from(edges),
    edgePtr: Uint32Array.from(edgePtr),
    edgeElems: Uint32Array.from(edgeElems),
    normals,
    areas,
    centroids,
  };
}

/** 요소 e 의 이웃 */
export function neighbors(t: MeshTopo, e: number): Uint32Array {
  return t.nbr.subarray(t.nbrPtr[e], t.nbrPtr[e + 1]);
}

/** 집합 경계 모서리(한쪽 요소만 집합 안, 또는 자유 모서리) — 경계선 표시용 노드 쌍 */
export function boundaryEdges(t: MeshTopo, inSet: (e: number) => boolean): Uint32Array {
  const out: number[] = [];
  const nE = t.edgePtr.length - 1;
  for (let i = 0; i < nE; i++) {
    let a = 0;
    let b = 0;
    for (let k = t.edgePtr[i]; k < t.edgePtr[i + 1]; k++) (inSet(t.edgeElems[k]) ? a++ : b++);
    if (a > 0 && (b > 0 || t.edgePtr[i + 1] - t.edgePtr[i] === 1)) out.push(t.edges[i * 2], t.edges[i * 2 + 1]);
  }
  return Uint32Array.from(out);
}

/** 경계 노드(집합 안 요소와 밖 요소가 함께 쓰는 노드, §5.2-5) */
export function boundaryNodes(t: MeshTopo, inSet: (e: number) => boolean): Uint8Array {
  const inside = new Uint8Array(t.nNodes);
  const outside = new Uint8Array(t.nNodes);
  for (let e = 0; e < t.nElems; e++) {
    const mark = inSet(e) ? inside : outside;
    for (let k = t.elemNodesPtr[e]; k < t.elemNodesPtr[e + 1]; k++) mark[t.elemNodes[k]] = 1;
  }
  const out = new Uint8Array(t.nNodes);
  for (let v = 0; v < t.nNodes; v++) out[v] = inside[v] & outside[v];
  return out;
}

/** ±1줄(§5.2-6): +1 = 비드 밖 요소 중 경계 노드를 쓰는 요소, −1 = 사면 요소 중 경계 노드를 쓰는 요소 */
export function ringStep(t: MeshTopo, inBead: (e: number) => boolean, dir: 1 | -1, candidate: (e: number) => boolean): number[] {
  const bn = boundaryNodes(t, inBead);
  const out: number[] = [];
  for (let e = 0; e < t.nElems; e++) {
    if (inBead(e) !== (dir === -1) || !candidate(e)) continue;
    for (let k = t.elemNodesPtr[e]; k < t.elemNodesPtr[e + 1]; k++)
      if (bn[t.elemNodes[k]]) {
        out.push(e);
        break;
      }
  }
  return out;
}
