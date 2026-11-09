"""Mesh topology for shell meshes (quad / tri, 0-based node indices, tri rows padded with -1 or a repeated node).

numpy / scipy only — no platform imports (contract esl_beadgraph.md §8.1).

Frame (BG-D-1, V-BG-4): n0 = area-weighted dominant normal (refined on flat elements); its *sign* and the in-plane axes
(e1, e2) are fixed later by ``set_frame`` from part-intrinsic quantities so that the result does not depend on element
orientation, node / element numbering or a rigid transform of the input.
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse import csgraph


class Topo:
    def __init__(self, nodes, elems):
        X = np.asarray(nodes, dtype=np.float64)
        E = np.asarray(elems, dtype=np.int64)
        if E.ndim != 2 or E.shape[1] not in (3, 4) or X.ndim != 2 or X.shape[1] != 3:
            raise ValueError("nodes (n, 3) float, elems (m, 3|4) int")
        if E.shape[1] == 3:
            E = np.c_[E, -np.ones(E.shape[0], np.int64)]
        E = E.copy()
        tri = (E[:, 3] < 0) | (E[:, 3] == E[:, 2]) | (E[:, 3] == E[:, 0])
        E[tri, 3] = -1
        if E.size and (E[:, :3].min() < 0 or E.max() >= X.shape[0]):
            raise ValueError("element node index out of range")
        self.X, self.C = X, E
        self.n, self.m = X.shape[0], E.shape[0]
        self.k = np.where(tri, 3, 4)
        self.tri = tri
        # --- directed element edges
        nxt = E[:, [1, 2, 3, 0]].copy()
        nxt[tri, 2] = E[tri, 0]
        valid = np.ones((self.m, 4), bool)
        valid[tri, 3] = False
        a = E[valid]
        b = nxt[valid]
        el = np.repeat(np.arange(self.m), 4).reshape(self.m, 4)[valid]
        slot = np.tile(np.arange(4), self.m).reshape(self.m, 4)[valid]
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        key = lo * self.n + hi
        uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        self.edges = np.c_[uk // self.n, uk % self.n]
        self.edge_count = cnt
        self.EE = -np.ones((self.m, 4), np.int64)
        self.EE[el, slot] = inv
        o = np.argsort(inv, kind="stable")
        inv_s, el_s = inv[o], el[o]
        first = np.r_[0, np.flatnonzero(np.diff(inv_s)) + 1] if inv_s.size else np.zeros(0, np.int64)
        self.e2a = el_s[first]
        self.e2b = -np.ones(uk.size, np.int64)
        two = cnt >= 2
        self.e2b[two] = el_s[first[two] + 1]
        dir_s = (a < b)[o]
        self._dir_a = dir_s[first]
        self._dir_b = np.zeros(uk.size, bool)
        self._dir_b[two] = dir_s[first[two] + 1]
        self.free_edges = np.flatnonzero(cnt == 1)
        # --- element adjacency (manifold pairs)
        pa, pb = self.e2a[two], self.e2b[two]
        self.pairs = np.c_[pa, pb]
        self.pair_edge = np.flatnonzero(two)
        A = sparse.coo_matrix((np.ones(2 * pa.size), (np.r_[pa, pb], np.r_[pb, pa])), shape=(self.m, self.m)).tocsr()
        A.sum_duplicates()
        A.data[:] = 1.0
        self.adj = A
        self._geometry()
        self._orient()

    # ------------------------------------------------------------------ geometry
    def _geometry(self):
        X, C, q = self.X, self.C, ~self.tri
        p0, p1, p2 = X[C[:, 0]], X[C[:, 1]], X[C[:, 2]]
        nrm = np.cross(p1 - p0, p2 - p0)
        p3 = X[np.where(q, C[:, 3], C[:, 2])]
        nrm[q] = np.cross(p2[q] - p0[q], p3[q] - p1[q])
        area = 0.5 * np.linalg.norm(nrm, axis=1)
        self.area = area
        self.normal = nrm / np.maximum(2 * area, 1e-300)[:, None]
        c = p0 + p1 + p2
        c[q] += p3[q]
        self.centroid = c / np.where(q, 4.0, 3.0)[:, None]

    def _orient(self):
        """consistent normals over manifold pairs (BFS parity), then the unsigned reference normal n0."""
        cons = self._dir_a[self.pair_edge] != self._dir_b[self.pair_edge]       # opposite traversal = consistent
        pa, pb = self.pairs[:, 0], self.pairs[:, 1]
        ka = np.minimum(pa, pb) * self.m + np.maximum(pa, pb)
        ku, first = np.unique(ka, return_index=True)
        pa, pb, cons = pa[first], pb[first], cons[first]
        S = sparse.coo_matrix((np.ones(2 * pa.size), (np.r_[pa, pb], np.r_[pb, pa])), shape=(self.m, self.m)).tocsr()
        parity = np.zeros(self.m, np.int8)
        ncomp, lab = csgraph.connected_components(S, directed=False)
        # one BFS over all components through a virtual super-root linked to each component's smallest element
        roots = np.full(ncomp, -1, np.int64)
        order_all = np.argsort(lab, kind="stable")
        starts = np.r_[0, np.flatnonzero(np.diff(lab[order_all])) + 1]
        roots[lab[order_all[starts]]] = order_all[starts]
        m = self.m
        Sa = sparse.coo_matrix((np.ones(2 * pa.size + 2 * ncomp),
                                (np.r_[pa, pb, np.full(ncomp, m), roots], np.r_[pb, pa, roots, np.full(ncomp, m)])),
                               shape=(m + 1, m + 1)).tocsr()
        order, pred = csgraph.breadth_first_order(Sa, m, directed=False, return_predecessors=True)
        par1 = np.zeros(m + 1, np.int8)
        par1[m] = 1
        v = order[1:]
        p = pred[v]
        virt = p == m
        k = np.minimum(p, v) * self.m + np.maximum(p, v)
        pos = np.clip(np.searchsorted(ku, k), 0, max(ku.size - 1, 0))
        sgn = np.where(virt, 1, np.where(cons[pos] if ku.size else True, 1, -1)).astype(np.int8)
        pl = par1
        for vi, pi, si in zip(v.tolist(), p.tolist(), sgn.tolist()):
            pl[vi] = pl[pi] * si
        parity = par1[:m]
        self.normal *= parity[:, None]
        self.comp = lab
        self.ncomp = ncomp
        M = (self.normal * self.area[:, None]).T @ self.normal
        _w, V = np.linalg.eigh(M)
        n0 = V[:, -1]
        if (self.normal @ n0 * self.area).sum() < 0:
            n0 = -n0
        for _ in range(4):                      # refine on the (exactly parallel) flat elements only
            f = np.abs(self.normal @ n0) >= np.cos(np.radians(5.0))
            if f.sum() < 3:
                break
            nn = self.normal[f] * np.sign(self.normal[f] @ n0)[:, None]
            v = (nn * self.area[f, None]).sum(axis=0)
            n0 = v / np.linalg.norm(v)
        # per component: make the component's dominant facing agree with n0
        flip = self.normal @ n0 * self.area
        cs = np.bincount(lab, weights=flip, minlength=ncomp)
        self.normal *= np.where(cs[lab] < 0, -1.0, 1.0)[:, None]
        self.n0 = n0
        self._set_axes(*_any_axes(n0))

    def _set_axes(self, e1, e2, origin=None):
        self.e1, self.e2 = e1, e2
        self.h_node = self.X @ self.n0
        self.h = self.centroid @ self.n0
        o = np.zeros(2) if origin is None else origin
        self.P = np.c_[self.X @ e1, self.X @ e2] - o          # plan coords of nodes
        self.Pc = np.c_[self.centroid @ e1, self.centroid @ e2] - o

    def flip_n0(self):
        """reverse the reference normal (frame canonicalisation — features rise from the base)."""
        self.n0 = -self.n0
        self.normal *= -1.0
        self._set_axes(*_any_axes(self.n0))

    def set_frame(self):
        """part-intrinsic plan axes: e1 = principal (largest variance) in-plane direction of the nodes, sign = positive
        third moment (fallback: e2 skew, then the provisional axis); origin = node centroid. Invariant under rigid
        transforms and numbering (V-BG-4)."""
        e1p, e2p = _any_axes(self.n0)
        Q = np.c_[self.X @ e1p, self.X @ e2p]
        c = Q.mean(axis=0)
        Qc = Q - c
        M = Qc.T @ Qc
        w, V = np.linalg.eigh(M)
        a = V[:, -1]
        e1 = a[0] * e1p + a[1] * e2p
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(self.n0, e1)
        x = (self.X - self.X.mean(axis=0)) @ e1
        y = (self.X - self.X.mean(axis=0)) @ e2
        sx, sy = float(np.mean(x ** 3)), float(np.mean(y ** 3))
        scale = max(float(np.mean(x ** 2)) ** 1.5, 1e-30)
        if abs(sx) > 1e-6 * scale:
            s = np.sign(sx)
        elif abs(sy) > 1e-6 * scale:
            s = np.sign(sy)
        else:
            s = 1.0 if e1 @ e1p >= 0 else -1.0
        e1, e2 = e1 * s, e2 * s
        origin = np.array([self.X.mean(axis=0) @ e1, self.X.mean(axis=0) @ e2])
        self.origin = origin
        self._set_axes(e1, e2, origin)
        self.h_med = float(np.median(np.linalg.norm(self.X[self.edges[:, 0]] - self.X[self.edges[:, 1]], axis=1))) \
            if self.edges.size else 0.0

    def rank_key(self):
        """canonical element order (geometry only): (height, distance² from the plan origin, plan x, plan y)."""
        r2 = (self.Pc ** 2).sum(axis=1)
        o = np.lexsort((np.round(self.Pc[:, 1], 6), np.round(self.Pc[:, 0], 6), np.round(r2, 4), np.round(self.h, 6)))
        rank = np.empty(self.m, np.int64)
        rank[o] = np.arange(self.m)
        return rank

    # ------------------------------------------------------------------ helpers
    def _incT(self):
        if not hasattr(self, "_inc_t"):
            rows = np.repeat(np.arange(self.m), 4)
            cols = self.C.ravel()
            ok = cols >= 0
            self._inc_t = sparse.csr_matrix((np.ones(ok.sum()), (cols[ok], rows[ok])), shape=(self.n, self.m))
        return self._inc_t

    def elem_nodes(self, mask):
        mask = np.asarray(mask)
        if mask.dtype != bool:
            mm = np.zeros(self.m, bool)
            mm[mask] = True
            mask = mm
        return np.flatnonzero(self._incT() @ mask.astype(np.float64))

    def node_mask(self, emask):
        m = np.zeros(self.n, bool)
        m[self.elem_nodes(emask)] = True
        return m

    def tris(self, eidx):
        """triangulation (t, 3) of the given elements."""
        C = self.C[eidx]
        q = C[:, 3] >= 0
        t1 = C[:, :3]
        t2 = C[q][:, [0, 2, 3]]
        return np.r_[t1, t2]

    def tri_owner(self, eidx):
        eidx = np.asarray(eidx, np.int64)
        q = self.C[eidx, 3] >= 0
        return np.r_[eidx, eidx[q]]


def _any_axes(n0):
    t = np.array([1.0, 0, 0]) if abs(n0[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = t - n0 * (t @ n0)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(n0, e1)


def chain_loops(edges: np.ndarray) -> list[np.ndarray]:
    """undirected edge list (k, 2) -> list of closed node loops (open chains are returned as well)."""
    if len(edges) == 0:
        return []
    inc: dict[int, list[int]] = {}
    for i, (a, b) in enumerate(edges.tolist()):
        inc.setdefault(a, []).append(i)
        inc.setdefault(b, []).append(i)
    used = np.zeros(len(edges), bool)
    loops = []
    E = edges.tolist()
    for s in range(len(edges)):
        if used[s]:
            continue
        used[s] = True
        a, b = E[s]
        seq = [a, b]
        cur = b
        while cur != a:
            nxt = None
            for j in inc[cur]:
                if not used[j]:
                    nxt = j
                    break
            if nxt is None:
                break
            used[nxt] = True
            e = E[nxt]
            cur = e[1] if e[0] == cur else e[0]
            seq.append(cur)
        loops.append(np.array(seq[:-1] if seq[-1] == seq[0] else seq, np.int64))
    return loops


def loop_area(P: np.ndarray, loop: np.ndarray) -> float:
    x, y = P[loop, 0], P[loop, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def loop_len(P: np.ndarray, loop: np.ndarray) -> float:
    d = P[np.roll(loop, -1)] - P[loop]
    return float(np.linalg.norm(d, axis=1).sum())
