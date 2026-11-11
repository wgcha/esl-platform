"""Floor hierarchy (parent-child by enclosure), islands, lances, holes — BG-D-9·10 (H6 prototype, productionised)."""
from __future__ import annotations

import numpy as np

from .topo import Topo, chain_loops, loop_area, loop_len


def piece_loops(t: Topo, piece: np.ndarray, npc: int):
    """per piece: (list of (loop nodes, signed plan area)), outer loop index."""
    ea, eb = t.e2a, t.e2b
    pa = piece[ea]
    pb = np.where(eb >= 0, piece[np.maximum(eb, 0)], -2)
    out: dict[int, list] = {}
    for side, own, oth in ((0, pa, pb), (1, pb, pa)):
        m = (own >= 0) & (own != oth)
        if side == 1:
            m &= eb >= 0
        idx = np.flatnonzero(m)
        for p, e in zip(own[idx].tolist(), idx.tolist()):
            out.setdefault(p, []).append(e)
    loops = {}
    for p in range(npc):
        E = np.array(out.get(p, []), np.int64)
        if E.size == 0:
            loops[p] = ([], -1)
            continue
        ls = chain_loops(t.edges[E])
        rec = [(lp, loop_area(t.P, lp)) for lp in ls]
        outer = int(np.argmax([abs(a) for _, a in rec])) if rec else -1
        loops[p] = (rec, outer)
    return loops


def edge_lookup(t: Topo):
    n = t.n
    key = t.edges[:, 0] * n + t.edges[:, 1]
    return key, n


def loop_neighbours(t: Topo, loop: np.ndarray, inside: np.ndarray, key, n):
    """for each loop edge: (edge length, element across (-1 = free edge)) where `inside` marks the piece's elements."""
    a, b = loop, np.roll(loop, -1)
    k = np.minimum(a, b) * n + np.maximum(a, b)
    eid = np.clip(np.searchsorted(key, k), 0, key.size - 1)
    good = key[eid] == k
    L = np.linalg.norm(t.P[a] - t.P[b], axis=1)
    ea, eb = t.e2a[eid], t.e2b[eid]
    across = np.where(inside[ea], eb, ea)
    across[~good] = -1
    return L, across


def outer_free(t: Topo, piece: np.ndarray, npc: int, loops=None):
    """free-edge fraction of each piece's outer loop (sign / frame independent) -> (fractions, loops)."""
    loops = loops if loops is not None else piece_loops(t, piece, npc)
    key, n = edge_lookup(t)
    fr = np.zeros(npc)
    for p in range(npc):
        rec, oidx = loops[p]
        if oidx < 0:
            continue
        L, across = loop_neighbours(t, rec[oidx][0], piece == p, key, n)
        fr[p] = float(L[across < 0].sum()) / max(float(L.sum()), 1e-9)
    return fr, loops


def find_root(level, parea, free, cfg):
    rf = cfg["root_free_frac"]
    cands = [p for p in range(level.size) if free[p] >= rf]
    if cands:
        root = int(max(cands, key=lambda p: (parea[p], -p)))
    else:
        root = int(np.argmax(parea))
    tol = cfg["level_tol_mm"]
    rg = sorted({root} | {p for p in cands if abs(level[p] - level[root]) <= tol})
    return root, rg


def build_tree(t: Topo, piece, level, parea, up, dn, cfg, root, root_group, loops):
    npc = level.size
    key, n = edge_lookup(t)
    free_loops = chain_loops(t.edges[t.free_edges])
    if free_loops:
        areas = [abs(loop_area(t.P, lp)) for lp in free_loops]
        oi = int(np.argmax(areas))
        outline_nodes = set(free_loops[oi].tolist())
    else:
        oi = -1
        outline_nodes = set()
    info = []
    for p in range(npc):
        rec, oidx = loops[p]
        if oidx < 0:
            info.append({"free": 0.0, "cand": {}, "outer_area": 0.0, "perim": 0.0})
            continue
        lp = rec[oidx][0]
        inside = piece == p
        L, across = loop_neighbours(t, lp, inside, key, n)
        cand: dict[int, float] = {}
        free = 0.0
        for l, e in zip(L.tolist(), across.tolist()):
            if e < 0:
                free += l
                continue
            if piece[e] >= 0:
                o = int(piece[e])
            else:
                u, d = int(up[e]), int(dn[e])
                o = d if u == p else (u if d == p else (u if u >= 0 else d))
            if o == p or o < 0:
                continue
            cand[o] = cand.get(o, 0.0) + l
        tot = float(L.sum())
        info.append({"free": free / max(tot, 1e-9), "cand": cand, "outer_area": abs(rec[oidx][1]), "perim": tot})
    rgs = set(root_group)
    parent = -np.ones(npc, np.int64)

    def pick(c):
        return max(c, key=lambda k: (round(c[k], 6), -abs(level[k]), -k))
    for p in range(npc):
        if p in rgs:
            continue
        c = dict(info[p]["cand"])
        for g in root_group:              # fragments of the base count as the base
            if g in c and g != root:
                c[root] = c.get(root, 0.0) + c.pop(g)
        parent[p] = pick(c) if c else root
    for p in range(npc):                  # break cycles: re-parent the member with the larger outer area
        seen = []
        q = p
        while q >= 0 and q not in seen and q not in rgs:
            seen.append(q)
            q = int(parent[q])
        if q in seen:
            cyc = seen[seen.index(q):]
            big = max(cyc, key=lambda r: (info[r]["outer_area"], -r))
            alt = {k: v for k, v in info[big]["cand"].items() if k not in cyc}
            parent[big] = pick(alt) if alt else root
    for g in root_group:
        if g != root:
            parent[g] = -2                    # fragment marker
    children = {p: [] for p in range(npc)}
    for p in range(npc):
        if parent[p] >= 0:
            children[int(parent[p])].append(p)
    tier = -np.ones(npc, np.int64)
    tier[root_group] = 0
    stack = [root]
    while stack:
        q = stack.pop()
        for c in children[q]:
            tier[c] = tier[q] + 1
            stack.append(c)
    for p in range(npc):
        if tier[p] < 0:                       # unreachable -> attach to root
            if parent[p] >= 0 and p in children.get(int(parent[p]), []):
                children[int(parent[p])].remove(p)
            parent[p] = root
            children[root].append(p)
            tier[p] = 1
    return {"parent": parent, "children": children, "tier": tier, "root": root, "root_group": root_group,
            "info": info, "loops": loops, "free_loops": free_loops, "outline_loop": oi, "outline_nodes": outline_nodes}


def descendants(children, p):
    out = []
    st = list(children[p])
    while st:
        q = st.pop()
        out.append(q)
        st += children[q]
    return out


def islands_and_holes(t: Topo, piece, level, up, dn, tr, cfg, fixed_nodes, toggles=None):
    """islands (subtrees <= island.max_mm, rigid), lances (islands with a slot touching the parent floor), holes.
    toggles: {piece: 'bead'|'island'} user overrides (BG-D-9 / D8)."""
    parent, children, root = tr["parent"], tr["children"], tr["root"]
    rg = np.array(tr["root_group"])
    rgs = set(tr["root_group"])
    toggles = toggles or {}

    def eff(p):
        return root if p in rgs else p
    upE = np.where(np.isin(up, rg), root, up)
    dnE = np.where(np.isin(dn, rg), root, dn)
    imax = cfg["island"]["max_mm"]
    npc = level.size
    island_of_piece = -np.ones(npc, np.int64)
    islands = []
    wall = piece < 0

    def cluster_elems(p):
        mem = [p] + descendants(children, p)
        ms = np.isin(piece, mem)
        mw = wall & (np.isin(upE, mem) | np.isin(dnE, mem))
        return mem, ms | mw

    def extent(mask):
        nodes = t.elem_nodes(mask)
        if nodes.size < 3:
            return 0.0
        P = t.P[nodes]
        P = P - P.mean(axis=0)
        _u, _s, Vt = np.linalg.svd(P, full_matrices=False)
        Q = P @ Vt.T
        return float((Q.max(axis=0) - Q.min(axis=0)).max())
    elem_island = -np.ones(t.m, np.int64)
    stack = sorted(children[root])
    while stack:
        p = stack.pop()
        mem, mask = cluster_elems(p)
        ext = extent(mask)
        tg = toggles.get(p)
        is_isl = (tg == "island") or (tg != "bead" and ext <= imax)
        if is_isl:
            iid = len(islands)
            island_of_piece[mem] = iid
            free = mask & (elem_island < 0)
            elem_island[free] = iid
            islands.append({"id": iid, "pieces": sorted(mem), "parent": int(parent[p]), "size_mm": ext, "lance": False,
                            "straddle": False, "touch": [], "root_piece": p, "toggled": tg == "island"})
        else:
            stack += sorted(children[p])
    # straddle: island elements adjacent to foreign walls or to floors other than the parent
    pa, pb = t.pairs[:, 0], t.pairs[:, 1]
    nb: list[dict] = [dict() for _ in islands]
    for a, b in ((pa, pb), (pb, pa)):
        m = (elem_island[a] >= 0) & (elem_island[b] != elem_island[a])
        for e_i, e_o in zip(a[m].tolist(), b[m].tolist()):
            if piece[e_o] >= 0:
                o = ("floor", int(eff(piece[e_o])))
            elif elem_island[e_o] >= 0:
                o = ("island", int(elem_island[e_o]))
            else:
                o = ("wall", int(upE[e_o]), int(dnE[e_o]))
            d = nb[elem_island[e_i]]
            d[o] = d.get(o, 0) + 1
    for isl, d in zip(islands, nb):
        par = isl["parent"]
        par = root if par in rgs else par
        tot = sum(d.values()) or 1
        foreign = {k: v for k, v in d.items() if not (k[0] == "floor" and k[1] == par)}
        isl["touch"] = [{"kind": k[0], "ids": [int(x) for x in k[1:]], "n": int(v)}
                        for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))]
        isl["straddle"] = sum(foreign.values()) / tot > cfg["island"]["straddle_frac"]
    # holes = free loops except the outline
    holes = []
    fx = set(np.asarray(fixed_nodes if fixed_nodes is not None else [], np.int64).tolist())
    key, n = edge_lookup(t)
    for i, lp in enumerate(tr["free_loops"]):
        if i == tr["outline_loop"]:
            continue
        a, b = lp, np.roll(lp, -1)
        k = np.minimum(a, b) * n + np.maximum(a, b)
        eid = np.clip(np.searchsorted(key, k), 0, key.size - 1)
        els = t.e2a[eid]
        isl_ids = elem_island[els]
        floors = np.array([eff(int(f)) if f >= 0 else -1 for f in piece[els].tolist()])
        if (isl_ids >= 0).any():
            vals, cnt = np.unique(isl_ids[isl_ids >= 0], return_counts=True)
            own_isl = int(vals[np.argmax(cnt)])
        else:
            own_isl = -1
        fl = floors[(floors >= 0) & (isl_ids < 0)]
        own_floor = int(np.bincount(fl).argmax()) if fl.size else -1
        if own_floor < 0:
            ww = els[(piece[els] < 0) & (isl_ids < 0)]
            if ww.size:
                own_floor = int(np.bincount(np.maximum(upE[ww], 0)).argmax())
        lance = False
        if own_isl >= 0 and own_floor >= 0:
            par = islands[own_isl]["parent"]
            par = root if par in rgs else par
            frac_isl = float((isl_ids >= 0).mean())
            if own_floor == par and 0.15 < frac_isl < 0.95:
                lance = True
                islands[own_isl]["lance"] = True
        area = abs(loop_area(t.P, lp))
        per = loop_len(t.P, lp)
        holes.append({"nodes": lp, "center_plan": t.P[lp].mean(axis=0), "center": t.X[lp].mean(axis=0), "area": area,
                      "perimeter": per, "d_eq": 4.0 * area / max(per, 1e-9),
                      "circularity": 4 * np.pi * area / max(per * per, 1e-9),
                      "owner_floor": own_floor if own_isl < 0 or lance else -1, "owner_island": own_isl,
                      "lance_slot": lance, "fixed": bool(fx & set(lp.tolist()))})
    return islands, elem_island, island_of_piece, holes, upE, dnE
