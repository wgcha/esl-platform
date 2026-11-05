"""메시(요소) 단계 위상 공통 모듈 — 섬·구멍 분류 (계약 docs/contracts/esl_select_relax.md §5B.2, SR-D-23, v0.16.1).

numpy/scipy 만(gmsh 불필요). 노드·요소 **인덱스** 기반(ID 아님).
- ``MeshIndex``·``mesh_index``·``node_graph``·``boundary_loops`` = v0.16.0 ``bead_select`` 의 ``MeshIndex``·``mesh_index``·
  ``_node_graph``·``_loops`` 본문 그대로(``bead_select`` 는 재노출).
- ``split_outer_inner``·``free_edge_components``·``enclosed_components``·``feature_segments``·``diagnose`` = v0.16.1 신규
  (select derive §5.2·§5.3, (예약) v0.16.2 P3 자동 탐지 초기 선택, ④ 메시 입력 진단 SR-D-24).
의존 방향: esl.mesh.features ← esl.doe.bead_select·esl.doe.mesh_input(역방향 import 금지).
"""
from __future__ import annotations

import numpy as np
from scipy import sparse

_EPS = 1e-12


class MeshIndex:
    """요소 인접 CSR(int32)·모서리 표·요소 기하. 노드 인덱스 기반(ID 아님)."""

    def __init__(self, mesh: dict):
        X = np.asarray(mesh["x0"], dtype=np.float64)
        C = np.asarray(mesh["conn"], dtype=np.int64)
        et = np.asarray(mesh["elem_type"]).astype(np.int64)
        self.n_nodes, self.n_elems = int(X.shape[0]), int(C.shape[0])
        self.is_quad = et == 4
        self.nv = np.where(self.is_quad, 4, 3)
        self.elem_id = np.asarray(mesh["elem_id"], dtype=np.int64)
        self.node_id = np.asarray(mesh["node_id"], dtype=np.int64)
        c4 = C[:, :4].copy() if C.shape[1] >= 4 else np.column_stack([C, C[:, :1]])
        c4[~self.is_quad, 3] = c4[~self.is_quad, 0]
        self.conn = c4
        # 모서리
        e_list, own = [], []
        for i in range(4):
            m = np.ones(self.n_elems, bool) if i < 3 else self.is_quad     # 3각: (0,1)(1,2)(2,0=열3)
            e_list.append(np.column_stack([c4[m, i], c4[m, (i + 1) % 4]]))
            own.append(np.flatnonzero(m))
        E = np.concatenate(e_list)
        O = np.concatenate(own)
        lo, hi = np.minimum(E[:, 0], E[:, 1]), np.maximum(E[:, 0], E[:, 1])
        key = lo * (1 << 32) + hi
        order = np.lexsort((O, key))
        key, O, lo, hi = key[order], O[order], lo[order], hi[order]
        start = np.flatnonzero(np.concatenate([[True], key[1:] != key[:-1]]))
        self.edge_nodes = np.column_stack([lo[start], hi[start]])          # (U,2)
        self.edge_ptr = np.concatenate([start, [key.size]]).astype(np.int64)
        self.edge_elems = O.astype(np.int64)                               # 모서리별 요소(CSR)
        cnt = np.diff(self.edge_ptr)
        self.edge_count = cnt
        # 요소 인접(공유 모서리 — 3개 이상 공유도 이웃)
        rows, cols = [], []
        two = np.flatnonzero(cnt == 2)
        a0, a1 = O[self.edge_ptr[two]], O[self.edge_ptr[two] + 1]
        rows += [a0, a1]
        cols += [a1, a0]
        for u in np.flatnonzero(cnt > 2):
            g = O[self.edge_ptr[u]:self.edge_ptr[u + 1]]
            ii, jj = np.meshgrid(g, g)
            m = ii != jj
            rows.append(ii[m])
            cols.append(jj[m])
        r = np.concatenate(rows) if rows else np.zeros(0, np.int64)
        cc = np.concatenate(cols) if cols else np.zeros(0, np.int64)
        A = sparse.csr_matrix((np.ones(r.size, np.int8), (r, cc)), shape=(self.n_elems, self.n_elems))
        A.sum_duplicates()
        A.indices = A.indices.astype(np.int32)
        A.indptr = A.indptr.astype(np.int32) if A.nnz < 2 ** 31 else A.indptr
        self.adj = A
        self.refresh(X)

    def refresh(self, X: np.ndarray) -> None:
        """기하 갱신(좌표만 — 위상 불변)."""
        self.X = np.asarray(X, dtype=np.float64)
        c4 = self.conn
        a, b, c, d = (self.X[c4[:, i]] for i in range(4))
        w = np.cross(b - a, c - a)
        q = self.is_quad
        if q.any():
            w[q] = np.cross(c[q] - a[q], d[q] - b[q])
        nrm = np.linalg.norm(w, axis=1)
        self.area = 0.5 * nrm
        self.normal = w / np.maximum(nrm, 1e-300)[:, None]
        cen = (a + b + c)
        cen[q] += d[q]
        self.centroid = cen / self.nv[:, None]
        el = np.linalg.norm(self.X[self.edge_nodes[:, 0]] - self.X[self.edge_nodes[:, 1]], axis=1)
        self.edge_len = el
        self.h_med = float(np.median(el)) if el.size else 1.0

    # ------------------------------------------------------------------ 집합 도구
    def elem_nodes(self, mask: np.ndarray) -> np.ndarray:
        """요소 마스크 → 노드 인덱스(정렬 unique)."""
        e = np.flatnonzero(mask)
        if e.size == 0:
            return np.zeros(0, np.int64)
        c = self.conn[e]
        return np.unique(np.concatenate([c[:, :3].ravel(), c[self.is_quad[e], 3]]))

    def node_count(self, mask: np.ndarray) -> np.ndarray:
        """노드별 마스크 요소 수."""
        e = np.flatnonzero(mask)
        cnt = np.zeros(self.n_nodes, np.int64)
        c = self.conn[e]
        for i in range(3):
            cnt += np.bincount(c[:, i], minlength=self.n_nodes)
        cnt += np.bincount(c[self.is_quad[e], 3], minlength=self.n_nodes)
        return cnt

    def edge_in_count(self, mask: np.ndarray) -> np.ndarray:
        """모서리별 마스크 요소 수."""
        v = mask[self.edge_elems].astype(np.int64)
        return np.add.reduceat(v, self.edge_ptr[:-1]) if v.size else np.zeros(0, np.int64)


def mesh_index(mesh: dict) -> MeshIndex:
    return MeshIndex(mesh)


def node_graph(index: MeshIndex, emask: np.ndarray) -> sparse.csr_matrix:
    """요소 마스크의 모서리 그래프(가중 = 모서리 길이, 노드 인덱스 전체 크기)."""
    nin = index.edge_in_count(emask)
    sel = nin >= 1
    E = index.edge_nodes[sel]
    w = np.maximum(index.edge_len[sel], 1e-9)
    n = index.n_nodes
    G = sparse.csr_matrix((np.concatenate([w, w]), (np.concatenate([E[:, 0], E[:, 1]]),
                                                    np.concatenate([E[:, 1], E[:, 0]]))), shape=(n, n))
    return G


def boundary_loops(index: MeshIndex, bead_mask: np.ndarray, *,
                   edge_nodes: np.ndarray | None = None) -> tuple[list[dict], bool]:
    """경계 모서리(비드 1 + 밖 1 이상) 고리(= v0.16.0 ``bead_select._loops``). 반환 ([{nodes(idx 순서), closed}], 자유 모서리 존재).
    edge_nodes(판 가장자리 자유 모서리 성분 노드 — ``free_edge_components``)를 주면 두 번째 반환 = '판 가장자리 자유 모서리 있음'
    (§5.3 — 관통 구멍은 열린 경계 아님), None 이면 v0.16.0 의미(자유 모서리 하나라도). 호출자별 의미 고정."""
    nin = index.edge_in_count(bead_mask)
    nout = index.edge_count - nin
    bedge = (nin >= 1) & (nout >= 1)
    free = (nin >= 1) & (index.edge_count == 1)
    if edge_nodes is not None:
        on = np.zeros(index.n_nodes, bool)
        on[np.asarray(edge_nodes, dtype=np.int64)] = True
        free = free & (on[index.edge_nodes[:, 0]] | on[index.edge_nodes[:, 1]])
    E = index.edge_nodes[bedge]
    if E.size == 0:
        return [], bool(free.any())
    # 노드 → 이웃(경계 그래프)
    nodes = np.unique(E.ravel())
    pos = {int(v): i for i, v in enumerate(nodes.tolist())}
    nbr: list[list[int]] = [[] for _ in nodes]
    for a, b in E.tolist():
        nbr[pos[a]].append(b)
        nbr[pos[b]].append(a)
    for lst in nbr:
        lst.sort()
    used_edge = set()
    loops = []
    # 시작 = 끝점(차수 1) 먼저(열린 사슬), 그다음 최소 노드
    deg = np.array([len(x) for x in nbr])
    order = list(nodes[deg == 1]) + list(nodes[deg != 1])
    for s in order:
        s = int(s)
        avail = [b for b in nbr[pos[s]] if (min(s, b), max(s, b)) not in used_edge]
        if not avail:
            continue
        chain = [s]
        cur, nxt = s, avail[0]
        closed = False
        while True:
            used_edge.add((min(cur, nxt), max(cur, nxt)))
            if nxt == s:
                closed = True
                break
            chain.append(nxt)
            cand = [b for b in nbr[pos[nxt]] if (min(nxt, b), max(nxt, b)) not in used_edge]
            if not cand:
                break
            cur, nxt = nxt, cand[0]
        loops.append({"nodes": np.asarray(chain, np.int64), "closed": closed})
    return loops, bool(free.any())
