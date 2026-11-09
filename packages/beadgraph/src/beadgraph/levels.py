"""Floor pieces (flat patches by normal angle + height level) and wall ownership (drainage up / down) — BG-D-1·4·6."""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse import csgraph

from .topo import Topo


def floor_pieces(t: Topo, cfg: dict):
    """-> piece id per element (-1 = wall), piece levels (median height), piece areas. Sign-agnostic (BG-D-4)."""
    fa = np.radians(cfg["feature_angle_deg"])
    cosang = t.normal @ t.n0
    is_floor = np.abs(cosang) >= np.cos(fa)
    pa, pb = t.pairs[:, 0], t.pairs[:, 1]
    tol = cfg["level_tol_mm"]
    dih = np.abs(np.einsum("ij,ij->i", t.normal[pa], t.normal[pb])) >= np.cos(fa)
    ok = is_floor[pa] & is_floor[pb] & (np.abs(t.h[pa] - t.h[pb]) <= tol) & dih
    G = sparse.coo_matrix((np.ones(ok.sum()), (pa[ok], pb[ok])), shape=(t.m, t.m))
    _n, lab = csgraph.connected_components(G, directed=False)
    piece = np.where(is_floor, lab, -1)
    ids, inv = np.unique(piece[piece >= 0], return_inverse=True)
    area = np.bincount(inv, weights=t.area[piece >= 0])
    keep = area >= cfg["min_floor_area_mm2"]
    remap = -np.ones(ids.size, np.int64)
    remap[keep] = np.arange(keep.sum())
    out = -np.ones(t.m, np.int64)
    out[piece >= 0] = remap[inv]
    npc = int(keep.sum())
    level, parea = piece_levels(t, out, npc)
    return out, level, parea


def piece_levels(t: Topo, piece: np.ndarray, npc: int):
    level = np.zeros(npc)
    parea = np.zeros(npc)
    order = np.argsort(piece, kind="stable")
    o = order[piece[order] >= 0]
    if o.size == 0:
        return level, parea
    starts = np.r_[0, np.flatnonzero(np.diff(piece[o])) + 1, o.size]
    for i in range(npc):
        e = o[starts[i]:starts[i + 1]]
        level[i] = float(np.median(t.h[e]))
        parea[i] = float(t.area[e].sum())
    return level, parea


def wall_ownership(t: Topo, piece: np.ndarray, rank: np.ndarray, eps: float = 1e-6):
    """Each wall element -> (upper floor, lower floor) by steepest ascent / descent through the element graph (BG-D-6).
    Ties are broken by the canonical geometric rank (not by element index — V-BG-4)."""
    A = t.adj
    ip, ix = A.indptr, A.indices
    h = t.h
    walls = np.flatnonzero(piece < 0)
    up = np.where(piece >= 0, piece, -1)
    dn = np.where(piece >= 0, piece, -1)
    hl = h.tolist()
    rk = rank.tolist()

    def best(ns, sign):
        # max of sign*h, ties -> larger rank (sign 1) / smaller rank (sign -1): deterministic, numbering-free
        bj, bk = -1, None
        for j in ns:
            k = (sign * hl[j], sign * rk[j])
            if bk is None or k > bk:
                bj, bk = j, k
        return bj
    nbrs = {}
    for e in walls.tolist():
        nbrs[e] = ix[ip[e]:ip[e + 1]].tolist()
    for e in walls[np.lexsort((-rank[walls], -h[walls]))].tolist():
        ns = nbrs[e]
        if ns:
            j = best(ns, 1.0)
            if hl[j] > hl[e] + eps:
                up[e] = up[j]
    for e in walls[np.lexsort((rank[walls], h[walls]))].tolist():
        ns = nbrs[e]
        if ns:
            j = best(ns, -1.0)
            if hl[j] < hl[e] - eps:
                dn[e] = dn[j]
    # fill pending (local extrema: V-grooves, moats) from labelled neighbours, lowest (highest) neighbour first and
    # preferring a label different from the opposite end, so a moat around a boss still reaches the deeper floor
    for arr, other, sign in ((dn, up, 1.0), (up, dn, -1.0)):
        for strict in (True, False):
            for _ in range(200):
                pend = np.flatnonzero((arr < 0) & (piece < 0))
                if pend.size == 0:
                    break
                ch = False
                for e in pend[np.lexsort((sign * rank[pend], sign * h[pend]))].tolist():
                    ns = [j for j in nbrs.get(e, []) if arr[j] >= 0 and (piece[j] < 0 or not strict)]
                    if strict:
                        ns = [j for j in ns if arr[j] != other[e]]
                    if ns:
                        j = best(ns, -sign)
                        arr[e] = arr[j]
                        ch = True
                if not ch:
                    break
    up[piece >= 0] = -1
    dn[piece >= 0] = -1
    return up, dn
