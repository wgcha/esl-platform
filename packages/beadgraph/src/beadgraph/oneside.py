"""One-sided entry measurement (esl contract esl_bead_depth_mode.md §1.6.2, DM-13·22): per segment, the entry nodes
E_s (segment wall nodes ∩ parent floor nodes — the same set as ``absorb`` / ``zones``), their side of the skeleton
(``absorb.polyline_dist`` / ``interior_mask``), the open side (the side with more interior entry nodes, tie = +), and the
plan distances to the skeleton of the open-side entry line, the open-side floor edge and the fixed-side floor boundary.
Deterministic, values rounded to 1e-3. Used for the W1 variable (``morph`` kind W1) and the esl W reason only."""
from __future__ import annotations

import numpy as np

from . import _util as U
from .absorb import interior_mask, polyline_dist
from .zones import Mesh, bead_zones

AREA_TYPES = ("area", "plateau")


def outer_edge_nodes(M: Mesh) -> np.ndarray:
    """node mask of the plate's outer free edge (mesh boundary edges used by one element; the boundary loop with the
    largest plan extent — hole loops excluded, BG-D-10)."""
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components
    lo, hi = np.minimum(M.ea, M.eb), np.maximum(M.ea, M.eb)
    key = lo * M.n + hi
    u, cnt = np.unique(key, return_counts=True)
    fe = u[cnt == 1]
    out = np.zeros(M.n, bool)
    if fe.size == 0:
        return out
    a, b = fe // M.n, fe % M.n
    G = sparse.coo_matrix((np.ones(a.size), (a, b)), shape=(M.n, M.n))
    ncomp, comp = connected_components(G, directed=False)
    nodes = np.unique(np.r_[a, b])
    best, bc = -1.0, -1
    for c in np.unique(comp[nodes]):
        nd = nodes[comp[nodes] == c]
        ext = float(np.ptp(M.P[nd], axis=0).max()) if nd.size > 1 else 0.0
        if ext > best + 1e-9:
            best, bc = ext, int(c)
    out[nodes[comp[nodes] == bc]] = True
    return out


def _med(d):
    return U.f3(float(np.median(d))) if d.size else None


def measure(M: Mesh, segs, *, min_nodes: int, edge_nodes=None) -> dict:
    lab = M.lab
    seg = lab["segment"]
    edge_n = outer_edge_nodes(M) if edge_nodes is None else edge_nodes
    out = {}
    for s in sorted({int(x) for x in segs}):
        sg = M.segs[s]
        res = {"side": None, "n_open": 0, "n_other": 0, "d_open": None, "d_edge_open": None, "d_fixed": None,
               "width": None, "floor": None, "run": None,
               "fixed": {"child": 0, "shared": 0, "junction": 0, "edge": 0, "own_wall": 0}, "ok": False,
               "reason": None}
        out[s] = res
        if sg["type"] in AREA_TYPES or not sg.get("skeleton"):
            res["reason"] = "AREA"
            continue
        if sg.get("merged"):
            res["reason"] = "MERGED"
            continue
        Z = bead_zones(M, [s], (), "D")
        pts = np.asarray(sg["skeleton"], float)
        closed = bool(sg.get("closed"))
        ZFs = Z["ZF"] & (seg == s)
        ZWs = Z["ZW"] & (seg == s)
        nWs = M.nmask(ZWs)
        nFs = M.nmask(ZFs)
        E = nWs & M.nmask(Z["parent_floor"])
        ent = np.flatnonzero(E)
        if ent.size:
            d, side, cp, _n = polyline_dist(M.P[ent], pts)
            mid = interior_mask(cp, pts, closed)
        else:
            d = side = np.zeros(0)
            mid = np.zeros(0, bool)
        npos, nneg = int((side[mid] > 0).sum()), int((side[mid] < 0).sum())
        so = 1.0 if npos >= nneg else -1.0
        n_o, n_x = max(npos, nneg), min(npos, nneg)
        res["side"] = int(so)
        res["n_open"], res["n_other"] = n_o, n_x
        # open side: entry line + floor edge (Z_F ∩ Z_W nodes − E); fixed side: floor boundary nodes
        om = mid & (side == so)
        res["d_open"] = _med(d[om])
        edg = np.flatnonzero(nFs & nWs & ~E)
        bnd_el = ~ZFs
        bnd = nFs & (M.nmask(bnd_el) | edge_n)
        bidx = np.flatnonzero(bnd)
        if edg.size:
            de, se, ce, _ = polyline_dist(M.P[edg], pts)
            me = interior_mask(ce, pts, closed) & (se == so)
            res["d_edge_open"] = _med(de[me])
        if bidx.size:
            db, sb, cb, _ = polyline_dist(M.P[bidx], pts)
            mb = interior_mask(cb, pts, closed) & (sb == -so)
            res["d_fixed"] = _med(db[mb])
            fb = np.zeros(M.n, bool)
            fb[bidx[mb]] = True
            nC, nSC = M.nmask(Z["ZC"]), M.nmask(Z["ZSC"])
            others = ~(ZFs | ZWs | Z["ZC"] | Z["ZSC"] | Z["ZI"] | Z["parent_floor"])
            fx = res["fixed"]
            fx["child"] = int((fb & nC).sum())
            fx["shared"] = int((fb & nSC).sum())
            fx["junction"] = int((fb & M.nmask(others)).sum())
            fx["edge"] = int((fb & edge_n).sum())
            fx["own_wall"] = int((fb & nWs & ~nC & ~nSC).sum())
        if res["d_open"] is not None and res["d_fixed"] is not None:
            res["width"] = U.f3(res["d_open"] + res["d_fixed"])
        if res["d_edge_open"] is not None and res["d_fixed"] is not None:
            res["floor"] = U.f3(res["d_edge_open"] + res["d_fixed"])
        if res["d_open"] is not None and res["d_edge_open"] is not None:
            res["run"] = U.f3(res["d_open"] - res["d_edge_open"])
        if n_o >= min_nodes and n_x >= min_nodes:
            res["reason"] = "TWO_SIDED"
        elif n_o < min_nodes:
            res["reason"] = "NONE"
        elif res["fixed"]["edge"] >= min_nodes:
            res["reason"] = "EDGE"
        elif res["width"] is None or res["floor"] is None:
            res["reason"] = "NONE"
        res["ok"] = res["reason"] is None
    return out


def one_side(graph, labels, nodes, elems, segs, *, min_nodes: int = 3) -> dict:
    """-> {seg id: {side ±1, n_open, n_other, d_open, d_edge_open, d_fixed, width = d_open + d_fixed,
    floor = d_edge_open + d_fixed, run = d_open − d_edge_open, fixed{child, shared, junction, edge, own_wall}, ok,
    reason None|NONE|EDGE|TWO_SIDED|AREA|MERGED}}."""
    M = Mesh(graph, labels, nodes, elems)
    return measure(M, segs, min_nodes=int(min_nodes))
