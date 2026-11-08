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
from scipy.sparse import csgraph

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
    return loops_from_edges(E), bool(free.any())


def loops_from_edges(E: np.ndarray) -> list[dict]:
    """모서리 (m,2) 노드 쌍 → 고리 [{nodes(idx 순서), closed}] (``boundary_loops`` 본문 — 끝점(차수 1) 먼저, 그다음 최소 노드,
    작은 이웃 우선. 결정적)."""
    E = np.asarray(E, dtype=np.int64)
    if E.size == 0:
        return []
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
    return loops


# ====================================================================== v0.16.1 섬·구멍 분류 (§5.2·§5.3)
def _plane_basis(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """섬 크기·다각형 판정 평면 기저(브라우저 grow.ts enclosedIslands 와 같은 정의 — V-SR-12):
    u = n × e_a(a = |n| 성분이 가장 작은 좌표축, 동률 = 앞 축), v = n × u. 크기 = 이 평면 bbox 대각."""
    n = np.asarray(n, dtype=np.float64)
    n = n / max(float(np.linalg.norm(n)), 1e-300)
    ax = np.zeros(3)
    ax[int(np.argmin(np.abs(n)))] = 1.0
    u = np.cross(n, ax)
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def _uv(P: np.ndarray, n_ref: np.ndarray) -> np.ndarray:
    e1, e2 = _plane_basis(n_ref)
    return np.column_stack([P @ e1, P @ e2])


def _area2(uv: np.ndarray) -> float:
    """평면 다각형 부호 넓이(신발끈)."""
    u, v = uv[:, 0], uv[:, 1]
    return 0.5 * float(np.sum(u * np.roll(v, -1) - np.roll(u, -1) * v))


def _inside(pt: np.ndarray, poly: np.ndarray) -> bool:
    """짝홀 규칙(평면 2D)."""
    x, y = float(pt[0]), float(pt[1])
    u, v = poly[:, 0], poly[:, 1]
    u2, v2 = np.roll(u, -1), np.roll(v, -1)
    c = (v > y) != (v2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = u + (y - v) * (u2 - u) / (v2 - v)
    return bool(np.count_nonzero(c & (x < xi)) % 2)


def split_outer_inner(loops: list[dict], X: np.ndarray, n_ref: np.ndarray) -> tuple[int | None, list[int]]:
    """바깥 고리 = 평면 |넓이| 최대 닫힌 고리, 나머지 = 안쪽(SR-D-7). 닫힌 고리가 없으면 (None, [])."""
    closed = [i for i, lp in enumerate(loops) if lp.get("closed")]
    if not closed:
        return None, []
    ar = {i: abs(_area2(_uv(X[loops[i]["nodes"]], n_ref))) for i in closed}
    outer = max(closed, key=lambda i: (ar[i], -i))
    return outer, [i for i in closed if i != outer]


def outer_polygon(ix: MeshIndex, mask: np.ndarray, n_ref: np.ndarray) -> np.ndarray:
    """요소 마스크의 바깥 고리 노드 좌표(3D) — 닫힌 고리 |넓이| 최대, 없으면 노드 볼록 껍질(§5.2-3d)."""
    loops, _ = boundary_loops(ix, mask)
    o, _inner = split_outer_inner(loops, ix.X, n_ref)
    if o is not None:
        return ix.X[loops[o]["nodes"]]
    nodes = ix.elem_nodes(mask)
    if nodes.size < 3:
        return ix.X[nodes]
    from scipy.spatial import ConvexHull
    try:
        hull = ConvexHull(_uv(ix.X[nodes], n_ref))
    except Exception:                                   # noqa: BLE001 - 일직선 등 퇴화
        return ix.X[nodes]
    return ix.X[nodes[hull.vertices]]


def outer_polygons(ix: MeshIndex, mask: np.ndarray, n_ref: np.ndarray) -> list[np.ndarray]:
    """v0.16.1 SR-D-35 요소 마스크의 조각(요소 인접 연결 성분, 최소 요소 순)마다 바깥 고리 노드 좌표(3D) 목록.
    조각 경계 = 조각 요소 1개 ∧ (밖 요소 ≥ 1 ∨ 자유 모서리) — 구멍·슬롯이 바닥 가장자리를 끊어도 고리가 닫힌다. 바깥 고리 = 닫힌
    고리 |평면 넓이| 최대, 닫힌 고리가 없으면 조각 노드 볼록 껍질. 조각 1개 ∧ 자유 모서리 없음이면 ``outer_polygon`` 과 같은 고리."""
    m = np.asarray(mask, bool)
    e = np.flatnonzero(m)
    if e.size == 0:
        return []
    ncomp, lab = csgraph.connected_components(ix.adj[e][:, e], directed=False)
    first = np.full(ncomp, np.iinfo(np.int64).max)
    np.minimum.at(first, lab, e)
    out = []
    for c in np.argsort(first, kind="stable").tolist():
        pm = np.zeros(ix.n_elems, bool)
        pm[e[lab == c]] = True
        nin = ix.edge_in_count(pm)
        sel = (nin >= 1) & (((ix.edge_count - nin) >= 1) | (ix.edge_count == 1))
        loops = loops_from_edges(ix.edge_nodes[sel])
        o, _inner = split_outer_inner(loops, ix.X, n_ref)
        if o is not None:
            out.append(ix.X[loops[o]["nodes"]])
            continue
        out.append(_hull(ix, pm, n_ref))
    return out


def _hull(ix: MeshIndex, mask: np.ndarray, n_ref: np.ndarray) -> np.ndarray:
    nodes = ix.elem_nodes(mask)
    if nodes.size < 3:
        return ix.X[nodes]
    from scipy.spatial import ConvexHull
    try:
        hull = ConvexHull(_uv(ix.X[nodes], n_ref))
    except Exception:                                   # noqa: BLE001 - 일직선 등 퇴화
        return ix.X[nodes]
    return ix.X[nodes[hull.vertices]]


def plate_edge_nodes(ix: MeshIndex) -> np.ndarray:
    """v0.16.1 SR-D-35 판 가장자리 = 판 전체 외곽 자유 모서리: 메시 요소 연결 성분마다 자유 모서리 고리 성분 중 평면 투영
    |넓이| 최대(판 법선 = 그 성분 면적 가중 평균 법선, 동률 = 둘레 긴 쪽 → 최소 노드) 성분의 노드. 그 밖 자유 모서리 고리 = 관통
    구멍·슬롯·컷아웃. 결과는 ``ix`` 에 캐시(위상·좌표 불변 전제)."""
    got = getattr(ix, "_plate_edge", None)
    if got is not None:
        return got
    ncomp, lab = csgraph.connected_components(ix.adj, directed=False)
    parts = []
    for c in range(ncomp):
        pm = lab == c
        n_ref = (ix.normal[pm] * ix.area[pm][:, None]).sum(axis=0)
        if np.linalg.norm(n_ref) < _EPS:
            n_ref = np.array([0.0, 0.0, 1.0])
        fe = free_edge_components(ix, pm, np.zeros(0, np.int64), n_ref=n_ref)
        if not fe["holes"]:
            continue
        ar = [(lp["eq_d_mm"] * lp["perim_mm"] / 4.0, lp["perim_mm"]) for lp in fe["holes"]]
        k = max(range(len(ar)), key=lambda i: (ar[i][0], ar[i][1], -i))
        parts.append(np.unique(fe["holes"][k]["nodes"]))
    out = np.unique(np.concatenate(parts)) if parts else np.zeros(0, np.int64)
    ix._plate_edge = out
    return out


def _edge_owner_elems(ix: MeshIndex, eidx: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """모서리별 mask 안 첫 요소(자유 모서리 = mask 요소 1개)."""
    out = np.full(eidx.size, -1, np.int64)
    for k, u in enumerate(eidx.tolist()):
        g = ix.edge_elems[ix.edge_ptr[u]:ix.edge_ptr[u + 1]]
        g = g[mask[g]]
        if g.size:
            out[k] = int(g[0])
    return out


def _chain(E: np.ndarray) -> np.ndarray:
    """한 연결 성분 모서리들 → 노드 순서(닫힌 고리면 한 바퀴, 아니면 끝점부터). 결정적(최소 노드 시작·작은 이웃 우선)."""
    nbr: dict[int, list[int]] = {}
    for a, b in E.tolist():
        nbr.setdefault(a, []).append(b)
        nbr.setdefault(b, []).append(a)
    for v in nbr.values():
        v.sort()
    ends = sorted(v for v, l in nbr.items() if len(l) == 1)
    s = ends[0] if ends else min(nbr)
    used, chain, cur = set(), [s], s
    while True:
        nx = [b for b in nbr[cur] if (min(cur, b), max(cur, b)) not in used]
        if not nx:
            break
        used.add((min(cur, nx[0]), max(cur, nx[0])))
        if nx[0] == s:
            break
        chain.append(nx[0])
        cur = nx[0]
    return np.asarray(chain, np.int64)


def free_edge_components(ix: MeshIndex, mask: np.ndarray, boundary_nodes: np.ndarray, *,
                         n_ref: np.ndarray | None = None, plate_edge: np.ndarray | None = None) -> dict:
    """§5.3 자유 모서리(mask 요소 1개만 쓰는 모서리 — ``edge_count == 1 ∧ nin == 1``)의 노드 그래프 연결 성분.
    경계 노드(boundary_nodes)에 닿는 성분 = 판 가장자리(``edge`` 노드 합), 아니면 관통 구멍
    ``holes[{nodes(순서), elems(자유 모서리 주인 요소), perim_mm, eq_d_mm(4A/P, Newell 투영 넓이), center[3]}]``.
    성분 순서 = 최소 노드 번호 순(결정적).
    v0.16.1 SR-D-35: plate_edge(판 외곽 자유 모서리 노드 — ``plate_edge_nodes``)를 주면 판 가장자리 = 그 노드에 닿는 성분만
    (경계 노드에 닿는 구멍 — 비드 벽을 가로지르는 슬롯 — 도 관통 구멍, ``touch`` = 경계 노드에 닿음). None 이면 위 규칙."""
    m = np.asarray(mask, bool)
    nin = ix.edge_in_count(m)
    free = np.flatnonzero((nin == 1) & (ix.edge_count == 1))
    out = {"edge": np.zeros(0, np.int64), "holes": []}
    if free.size == 0:
        return out
    E = ix.edge_nodes[free]
    nodes = np.unique(E.ravel())
    pos = np.searchsorted(nodes, E)
    G = sparse.csr_matrix((np.ones(E.shape[0]), (pos[:, 0], pos[:, 1])), shape=(nodes.size, nodes.size))
    ncomp, lab = csgraph.connected_components(G, directed=False)
    bset = np.zeros(ix.n_nodes, bool)
    bset[np.asarray(boundary_nodes, dtype=np.int64)] = True
    eset = bset
    if plate_edge is not None:
        eset = np.zeros(ix.n_nodes, bool)
        eset[np.asarray(plate_edge, dtype=np.int64)] = True
    first = np.full(ncomp, np.iinfo(np.int64).max)
    np.minimum.at(first, lab, nodes)
    edge_parts = []
    for c in np.argsort(first, kind="stable").tolist():
        cn = nodes[lab == c]
        ce = lab[pos[:, 0]] == c
        if eset[cn].any():
            edge_parts.append(cn)
            continue
        chain = _chain(E[ce])
        P = ix.X[chain]
        seg = np.linalg.norm(np.roll(P, -1, axis=0) - P, axis=1)
        perim = float(seg.sum())
        nn = np.cross(P, np.roll(P, -1, axis=0)).sum(axis=0) * 0.5          # Newell 넓이 벡터
        if n_ref is not None:
            A = abs(float(nn @ (np.asarray(n_ref, float) / max(np.linalg.norm(n_ref), 1e-300))))
        else:
            A = float(np.linalg.norm(nn))
        hl = {"nodes": chain, "elems": np.unique(_edge_owner_elems(ix, free[ce], m)),
              "perim_mm": perim, "eq_d_mm": (4.0 * A / perim) if perim > 0 else 0.0, "center": P.mean(axis=0)}
        if plate_edge is not None:
            hl["touch"] = bool(bset[cn].any())
            hl["all_nodes"] = cn
        out["holes"].append(hl)
    if edge_parts:
        out["edge"] = np.unique(np.concatenate(edge_parts))
    return out


def enclosed_components(ix: MeshIndex, cand: np.ndarray, owner: np.ndarray, X: np.ndarray, n_ref: np.ndarray, *,
                        max_mm: float, outer_poly: dict[int, np.ndarray] | None = None,
                        ring_frac: float | None = None) -> dict:
    """§5.2 일반형. cand = 후보 요소 마스크, owner = 요소별 주인 번호(≥ 0 = 주인, −1 = 후보, −2 = 막힘).
    성분 K 가 섬 ⇔ 이웃(K 밖 인접 요소) 주인이 하나(≥ 0) ∧ 최대 성분 아님(요소 수 최대, 동률 = 최소 요소 번호) ∧ 노드 평면
    bbox 대각 ≤ max_mm ∧ (outer_poly 에 그 주인이 있으면) 요소 중심 평균이 그 다각형(3D 좌표 — n_ref 평면 투영) 안.
    반환 {islands: [{owner, elems, rim, interior, size_mm}], too_large: [{owner, n_elems, size_mm}]}, 성분 번호 = 최소 요소 순.
    rim = 섬 노드 ∩ 주인 요소 노드, interior = 그 밖 섬 노드.
    ring_frac(v0.16.1 고리형 비드): 주면 성분이 주인 바닥에서 판 쪽으로 ≥ ring_frac·D(D = 주인 바닥 ↔ 최대 성분 평행 요소의
    n_ref 높이 차 중앙값) 솟으면 섬 아님 = 고리형 비드의 안쪽 둔덕(진짜 경계) → ``rings`` [{owner, n_elems, size_mm}] 에(크기 판정
    전 — too_large 아님). None 이면 v0.16.0·R1 과 같음."""
    cand = np.asarray(cand, bool)
    owner = np.asarray(owner, dtype=np.int64)
    out = {"islands": [], "too_large": []}
    ce = np.flatnonzero(cand)
    if ce.size == 0:
        return out
    ncomp, lab = csgraph.connected_components(ix.adj[ce][:, ce], directed=False)
    first = np.full(ncomp, np.iinfo(np.int64).max)
    np.minimum.at(first, lab, ce)
    order = np.argsort(first, kind="stable")
    size = np.bincount(lab, minlength=ncomp)
    big = int(order[np.argmax(size[order])])               # 최대(동률 = 최소 요소 번호 — order 앞쪽 우선)
    A = ix.adj.tocsr()
    polys: dict = {}
    onodes: dict = {}
    nr = np.asarray(n_ref, np.float64) / max(float(np.linalg.norm(n_ref)), 1e-300)
    zfl: dict = {}
    zb = None
    if ring_frac is not None:
        Kb = ce[lab == big]
        pb = Kb[np.abs(ix.normal[Kb] @ nr) >= float(np.cos(np.radians(15.0)))]
        zb = float(np.median(ix.centroid[pb] @ nr)) if pb.size else None
        out["rings"] = []
    for c in order.tolist():
        if c == big:
            continue
        K = ce[lab == c]
        nb = np.unique(A[K].indices)
        nb = nb[~cand[nb]]
        own = np.unique(owner[nb])
        if own.size != 1 or own[0] < 0:
            continue
        k = int(own[0])
        km = np.zeros(ix.n_elems, bool)
        km[K] = True
        kn = ix.elem_nodes(km)
        uv = _uv(X[kn], n_ref)
        sz = float(np.linalg.norm(uv.max(axis=0) - uv.min(axis=0))) if kn.size else 0.0
        if zb is not None:                                  # 고리형 비드 안쪽 둔덕(판 높이까지 솟음) = 섬 아님
            if k not in zfl:
                zfl[k] = float(np.median(ix.centroid[owner == k] @ nr))
            D = zb - zfl[k]
            if abs(D) > _EPS and float(np.max((X[kn] @ nr - zfl[k]) * np.sign(D))) >= float(ring_frac) * abs(D):
                out["rings"].append({"owner": k, "n_elems": int(K.size), "size_mm": sz})
                continue
        ok = sz <= float(max_mm)
        if ok and outer_poly is not None and k in outer_poly and _npoly(outer_poly[k]):
            if k not in polys:                          # v0.16.1 SR-D-35: 목록이면 조각마다 바깥 고리 — 어느 하나 안이면 됨
                pk = outer_poly[k] if isinstance(outer_poly[k], list) else [outer_poly[k]]
                polys[k] = [_uv(np.asarray(p, float), n_ref) for p in pk if len(p) >= 3]
            c2 = _uv(ix.centroid[K].mean(axis=0)[None, :], n_ref)[0]
            ok = any(_inside(c2, p) for p in polys[k])
            if not ok and len(polys[k]) > 1:            # 바닥 조각 사이(조각을 가르는 섬): 닿은 조각 ≥ 2 의 합 볼록 껍질 안
                ok = _between_pieces(c2, uv, polys[k], 2.0 * ix.h_med)
        if not ok:
            out["too_large"].append({"owner": k, "n_elems": int(K.size), "size_mm": sz, "elems": K})
            continue
        if k not in onodes:
            onodes[k] = np.zeros(ix.n_nodes, bool)
            onodes[k][ix.elem_nodes(owner == k)] = True
        on = onodes[k]
        out["islands"].append({"owner": k, "elems": K, "rim": kn[on[kn]], "interior": kn[~on[kn]], "size_mm": sz})
    return out


def _between_pieces(c2: np.ndarray, uvK: np.ndarray, polys: list, gap: float) -> bool:
    """SR-D-35 섬 성분 노드(평면 uvK)에서 gap 안에 있는 바닥 조각 고리가 2개 이상이면 그 고리 점 합의 볼록 껍질 안에 c2 가 있는지."""
    from scipy.spatial import ConvexHull, cKDTree
    t = cKDTree(uvK)
    near = [p for p in polys if len(p) >= 3 and float(t.query(p, k=1)[0].min()) <= gap]
    if len(near) < 2:
        return False
    P = np.vstack(near)
    try:
        hull = ConvexHull(P)
    except Exception:                                   # noqa: BLE001 - 퇴화
        return False
    return _inside(c2, P[hull.vertices])


def _npoly(p) -> bool:
    if isinstance(p, list):
        return any(len(x) >= 3 for x in p)
    return len(p) >= 3


def feature_segments(ix: MeshIndex, feature_angle_deg: float) -> np.ndarray:
    """이면각 > 기준인 모서리(요소 2개 공유)로 나눈 요소 영역 번호(최소 요소 순 0..). 3개 이상 공유 모서리도 경계."""
    cos_t = float(np.cos(np.radians(float(feature_angle_deg))))
    two = np.flatnonzero(ix.edge_count == 2)
    a0, a1 = ix.edge_elems[ix.edge_ptr[two]], ix.edge_elems[ix.edge_ptr[two] + 1]
    keep = np.abs(np.einsum("ij,ij->i", ix.normal[a0], ix.normal[a1])) >= cos_t
    a0, a1 = a0[keep], a1[keep]
    G = sparse.csr_matrix((np.ones(2 * a0.size), (np.concatenate([a0, a1]), np.concatenate([a1, a0]))),
                          shape=(ix.n_elems, ix.n_elems))
    _n, lab = csgraph.connected_components(G, directed=False)
    first = np.full(_n, np.iinfo(np.int64).max)
    np.minimum.at(first, lab, np.arange(ix.n_elems))
    remap = np.empty(_n, np.int64)
    remap[np.argsort(first, kind="stable")] = np.arange(_n)
    return remap[lab]


def diagnose(mesh: dict, *, feature_angle_deg: float, hole_max_d_mm: float, island_max_mm: float,
             index: MeshIndex | None = None) -> dict:
    """SR-D-24 메시 입력 진단(보고만): {holes_n, holes_small_n, islands_n, free_loops_n, small_holes[{center, eq_d_mm}] ≤ 50}.
    구멍 = 판 전체 자유 모서리 고리 중 바깥 경계(평면 |넓이| 최대 — 판 법선 = 면적 가중 평균) 제외. 섬 = feature_segments 중
    bbox 대각 ≤ island_max_mm 인 영역을 cand, 그보다 큰 영역 번호를 owner 로 한 enclosed_components."""
    ix = index or mesh_index(mesh)
    allm = np.ones(ix.n_elems, bool)
    n_ref = (ix.normal * ix.area[:, None]).sum(axis=0)
    if np.linalg.norm(n_ref) < _EPS:
        n_ref = np.array([0.0, 0.0, 1.0])
    fe = free_edge_components(ix, allm, np.zeros(0, np.int64), n_ref=n_ref)
    loops = fe["holes"]
    if loops:                                          # 바깥 경계(평면 넓이 최대) 제외
        ar = [lp["eq_d_mm"] * lp["perim_mm"] / 4.0 for lp in loops]
        outer = int(np.argmax(ar))
        holes = [lp for i, lp in enumerate(loops) if i != outer]
    else:
        holes = []
    small = [lp for lp in holes if lp["eq_d_mm"] <= float(hole_max_d_mm)]
    seg = feature_segments(ix, feature_angle_deg)
    nseg = int(seg.max()) + 1 if seg.size else 0
    uv = _uv(ix.centroid, n_ref)
    cand = np.zeros(ix.n_elems, bool)
    owner = np.full(ix.n_elems, -2, np.int64)
    for s in range(nseg):
        m = seg == s
        nodes = ix.elem_nodes(m)
        p = _uv(ix.X[nodes], n_ref) if nodes.size else uv[m]
        sz = float(np.linalg.norm(p.max(axis=0) - p.min(axis=0)))
        if sz <= float(island_max_mm):
            cand |= m
            owner[m] = -1
        else:
            owner[m] = s
    isl = enclosed_components(ix, cand, owner, ix.X, n_ref, max_mm=island_max_mm)
    return {"holes_n": len(holes), "holes_small_n": len(small), "islands_n": len(isl["islands"]),
            "free_loops_n": len(loops),
            "small_holes": [{"center": [round(float(v), 3) for v in lp["center"]], "eq_d_mm": round(float(lp["eq_d_mm"]), 3)}
                            for lp in small[:50]]}
