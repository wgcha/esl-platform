"""Segment typing, junction-zone absorption (corner / short strip / spur — BG-D-13, D7), ring sides, per-segment
nominal values (D, entry width), children and island owners."""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

SKEL_J = ("T", "X", "L", "W", "Y")


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if repr(ra) < repr(rb):
                self.p[rb] = ra
            else:
                self.p[ra] = rb


def polyline_dist(Q: np.ndarray, pts: np.ndarray):
    """distance of points Q (k, 2) to the polyline pts (n, 2) + side sign (+1 left of the travel direction) + the
    closest point + the unit outward direction (from the closest point to the query)."""
    Q = np.asarray(Q, float)
    pts = np.asarray(pts, float)
    if len(pts) == 1:
        d = Q - pts[0]
        n = np.linalg.norm(d, axis=1)
        return n, np.ones(len(Q)), np.repeat(pts[:1], len(Q), 0), d / np.maximum(n, 1e-12)[:, None]
    A, B = pts[:-1], pts[1:]
    tree = cKDTree(0.5 * (A + B))
    k = min(8, len(A))
    _d, cand = tree.query(Q, k=k)
    cand = np.asarray(cand).reshape(len(Q), k)
    best = np.full(len(Q), np.inf)
    cp = np.zeros((len(Q), 2))
    side = np.ones(len(Q))
    for c in range(k):
        s = cand[:, c]
        a, b = A[s], B[s]
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(axis=1), 1e-24)
        u = np.clip(((Q - a) * ab).sum(axis=1) / L2, 0.0, 1.0)
        p = a + u[:, None] * ab
        dd = np.linalg.norm(Q - p, axis=1)
        m = dd < best - 1e-12
        best[m] = dd[m]
        cp[m] = p[m]
        cr = ab[:, 0] * (Q[:, 1] - a[:, 1]) - ab[:, 1] * (Q[:, 0] - a[:, 0])
        side[m] = np.where(cr[m] >= 0, 1.0, -1.0)
    nout = (Q - cp) / np.maximum(best, 1e-12)[:, None]
    return best, side, cp, nout


def interior_mask(cp, pts, closed=False):
    """closest point not on an open polyline's end vertex (end-cap nodes are not on a perpendicular — BG-D-16)."""
    if closed or len(pts) < 2:
        return np.ones(len(cp), bool)
    e0 = np.linalg.norm(cp - pts[0], axis=1) < 1e-9
    e1 = np.linalg.norm(cp - pts[-1], axis=1) < 1e-9
    return ~(e0 | e1)


def _cycle_flags(segs, juncs, sids):
    """segment on a cycle of its floor's skeleton graph (junction nodes, segment edges; bridges are not)."""
    edges = {}
    for s in sids:
        ends = [j for j in segs[s]["ends"] if juncs[j]["type"] in SKEL_J]
        if segs[s].get("closed"):
            edges[s] = ("loop", s)
        elif len(ends) == 2:
            edges[s] = (ends[0], ends[1])
    out = {}
    for s in sids:
        if s not in edges:
            out[s] = False
            continue
        a, b = edges[s]
        if a == "loop" or a == b:
            out[s] = True
            continue
        uf = _UF()
        for s2, (x, y) in edges.items():
            if s2 != s and x != "loop":
                uf.union(x, y)
        out[s] = uf.find(a) == uf.find(b)
    return out


def _type_segments(segs, juncs, sids, cyc):
    for s in sids:
        sg = segs[s]
        if sg["type"] is not None:
            continue
        jt = [juncs[j]["type"] for j in sg["ends"]]
        nbw = [segs[x]["floor_w"] for j in sg["ends"] for x in juncs[j]["segs"] if x != s and segs[x]["floor_w"]]
        wprof = sg["w_profile"] if sg["w_profile"] is not None else np.zeros(0)
        grow = len(wprof) > 6 and (np.median(wprof[-3:]) > 1.35 * np.median(wprof[:3]) or
                                   np.median(wprof[:3]) > 1.35 * np.median(wprof[-3:]))
        if sg["open_end"]:
            ty = "leg"
        elif sg.get("flare") or ("W" in jt and grow and jt.count("W") == 1):
            ty = "flare"
        elif "W" in jt and nbw and sg["floor_w"] > 1.3 * min(nbw):
            ty = "corner"
        elif sg["length"] is not None and sg["floor_w"] and sg["length"] / max(sg["floor_w"], 1e-9) < 6 and not \
                any(x in ("T", "X", "L") for x in jt):
            ty = "pocket"
        elif cyc.get(s):
            ty = "ring"
        else:
            ty = "channel"
        sg["type"] = ty
    for j in juncs:
        if j["type"] == "W" and any(segs[s]["type"] == "flare" for s in j["segs"]):
            j["type"] = "Y"


def absorb_and_sides(ctx):
    t, cfg = ctx["t"], ctx["cfg"]
    segs, juncs = ctx["segs"], ctx["juncs"]
    elem_seg, isl_m = ctx["elem_seg"], ctx["isl_m"]
    piece, eff_piece = ctx["piece"], ctx["eff_piece"]
    absorb_len = float(cfg["bead"]["absorb_len_mm"])
    by_floor: dict[int, list[int]] = {}
    for i, s in enumerate(segs):
        if s["type"] == "base":
            continue
        by_floor.setdefault(s["floor"], []).append(i)
    cyc_all = {}
    for p, sids in by_floor.items():
        cyc = _cycle_flags(segs, juncs, sids)
        cyc_all.update(cyc)
        _type_segments(segs, juncs, sids, cyc)
    # ------------------------------------------------------------ absorption candidates (BG-D-13)
    reason_of: dict[int, str] = {}
    for p, sids in by_floor.items():
        bead_sids = [s for s in sids if segs[s]["pts"] is not None]
        if len(bead_sids) < 2:
            continue
        cand = {}
        for s in bead_sids:
            sg = segs[s]
            skel_ends = sorted({j for j in sg["ends"] if juncs[j]["type"] in SKEL_J})
            L = sg["length"] or 0.0
            if sg["type"] == "corner":
                cand[s] = "corner"
            elif len(skel_ends) == 2 and L < absorb_len:
                cand[s] = "short_strip"
            elif (not sg["open_end"] and len(skel_ends) <= 1 and L < absorb_len and sg["type"] != "flare"
                  and any((segs[o]["length"] or 0.0) >= 2.0 * L for o in bead_sids if o != s)):
                cand[s] = "spur"
        if len(cand) >= len(bead_sids):            # never absorb a whole floor: keep the longest
            keep = max(bead_sids, key=lambda s: (segs[s]["length"] or 0.0, -s))
            cand.pop(keep, None)
        reason_of.update(cand)
    for s, r in reason_of.items():
        segs[s]["absorbed"] = r
    # ------------------------------------------------------------ zones: union skeleton junctions through absorbed segs
    uf = _UF()
    for j, jj in enumerate(juncs):
        if jj["type"] in SKEL_J:
            uf.find(("j", j))
    for s in reason_of:
        uf.find(("s", s))
        for j in segs[s]["ends"]:
            if juncs[j]["type"] in SKEL_J:
                uf.union(("s", s), ("j", j))
    groups: dict = {}
    for key in list(uf.p.keys()):
        groups.setdefault(uf.find(key), []).append(key)
    zones = []
    rank_r = {"corner": 0, "short_strip": 1, "spur": 2, "junction": 3}
    glist = sorted(groups.values(), key=lambda g: min((0 if k[0] == "j" else 1, k[1]) for k in g))
    for g in glist:
        js = sorted(k[1] for k in g if k[0] == "j")
        ss = sorted(k[1] for k in g if k[0] == "s")
        reasons = [reason_of[s] for s in ss] or ["junction"]
        reason = min(reasons, key=lambda r: rank_r[r])
        fl = juncs[js[0]]["floor"] if js else segs[ss[0]]["floor"]
        zones.append({"floor": fl, "reason": reason, "junctions": js, "absorbed": ss})
    for j, jj in enumerate(juncs):
        if jj["type"] == "step":
            zones.append({"floor": -1, "reason": "step", "junctions": [j], "absorbed": []})
    elem_jz = -np.ones(t.m, np.int64)
    Pc = t.Pc
    tree_c = cKDTree(Pc)
    for z, zz in enumerate(zones):
        for j in zz["junctions"]:
            jj = juncs[j]
            jj["zone"] = z
            if jj["type"] == "step":
                ii = np.asarray(jj["elems"], np.int64)
            else:
                ii = np.asarray(tree_c.query_ball_point(jj["plan"], r=1.2 * jj["r"]), np.int64)
                if ii.size:
                    ok = ((eff_piece[ii] == jj["floor"]) & (piece[ii] >= 0)) | \
                         ((piece[ii] < 0) & (elem_seg[ii] >= 0) & np.isin(elem_seg[ii], jj["segs"]))
                    ii = ii[ok & ~isl_m[ii]]
            if ii.size:
                elem_jz[ii[elem_jz[ii] < 0]] = z
        for s in zz["absorbed"]:
            ii = np.flatnonzero((elem_seg == s) & ~isl_m)
            elem_jz[ii[elem_jz[ii] < 0]] = z
    # post-zone segment label (internal)
    seg_post = np.where(elem_jz >= 0, -1, elem_seg)
    seg_post[isl_m] = -1
    ctx["seg_post"] = seg_post
    # zone adjacency: segments of the same floor touching the zone's elements (element pairs) + junction links
    pa, pb = t.pairs[:, 0], t.pairs[:, 1]
    adj_sets = [set() for _ in zones]
    for a, b in ((pa, pb), (pb, pa)):
        m = (elem_jz[a] >= 0) & (seg_post[b] >= 0)
        for z, s in zip(elem_jz[a][m].tolist(), seg_post[b][m].tolist()):
            if zones[z]["floor"] < 0 or segs[s]["floor"] == zones[z]["floor"]:
                adj_sets[z].add(s)
    for z, zz in enumerate(zones):
        for j in zz["junctions"]:
            adj_sets[z] |= {s for s in juncs[j]["segs"] if s not in reason_of}
        zz["adj"] = sorted(s for s in adj_sets[z] if not segs[s].get("absorbed") and segs[s]["type"] != "base")
    # ------------------------------------------------------------ ring sides (BG-D-13)
    e1w, e2w = ctx["display_axes"]
    for p, sids in by_floor.items():
        cyc_s = [s for s in sids if cyc_all.get(s) and not segs[s].get("absorbed")]
        if not cyc_s:
            continue
        all_cyc = [s for s in sids if cyc_all.get(s)]
        uf2 = _UF()
        for s in cyc_s:
            uf2.find(s)
        cut_any = False
        for zz in zones:
            if zz["floor"] != p:
                continue
            on = [s for s in zz["adj"] if s in cyc_s]
            types = {juncs[j]["type"] for j in zz["junctions"]}
            passthru = zz["reason"] == "junction" and types <= {"T", "X"}
            if passthru:
                for a, b in zip(on, on[1:]):
                    uf2.union(a, b)
            elif any(cyc_all.get(s) for s in zz["absorbed"]) or (types & {"L", "W", "Y"} and len(on) >= 1):
                cut_any = True
        chains: dict = {}
        for s in cyc_s:
            chains.setdefault(uf2.find(s), []).append(s)
        if not cut_any or len(chains) < 2:
            continue
        cen = np.concatenate([segs[s]["pts"] for s in all_cyc]).mean(axis=0)

        def world(pl):
            return (t.e1 * (pl[0] + t.origin[0]) + t.e2 * (pl[1] + t.origin[1]))
        cw = world(cen)
        for ch in chains.values():
            mid = np.concatenate([segs[s]["pts"] for s in ch]).mean(axis=0)
            v = world(mid) - cw
            dx, dy = float(v @ e1w), float(v @ e2w)
            side = ("right" if dx > 0 else "left") if abs(dx) >= abs(dy) else ("top" if dy > 0 else "bottom")
            for s in ch:
                segs[s]["side"] = side
    # ------------------------------------------------------------ per-segment nominal values, children, islands
    _segment_props(ctx, zones, elem_jz)
    return zones, elem_jz


def _segment_props(ctx, zones, elem_jz):
    t = ctx["t"]
    segs, piece, eff_piece = ctx["segs"], ctx["piece"], ctx["eff_piece"]
    seg_post, isl_m = ctx["seg_post"], ctx["isl_m"]
    level, par = ctx["level"], ctx["par"]
    islands, island_of_piece = ctx["islands"], ctx["island_of_piece"]
    rgs = set(ctx["rg"])
    hn = t.h_node
    floor_el = (piece >= 0) & ~isl_m
    for s, sg in enumerate(segs):
        if sg.get("absorbed") or sg["type"] == "base":
            sg["D"] = 0.0
            continue
        p = sg["floor"]
        pp = par(p)
        fe = (seg_post == s) & floor_el
        nodes = t.elem_nodes(fe)
        sg["D"] = abs(float(np.median(hn[nodes])) - float(level[pp])) if nodes.size else abs(level[p] - level[pp])
        sg["entry_width"] = None
        if sg["pts"] is None:
            continue
        walls = (seg_post == s) & (piece < 0)
        pn = t.node_mask(floor_el & (eff_piece == (ctx["root"] if pp in rgs else pp)))
        ent = t.elem_nodes(walls)
        ent = ent[pn[ent]]
        if ent.size < 6:
            continue
        d, side, cp, _n = polyline_dist(t.P[ent], sg["pts"])
        mid = interior_mask(cp, sg["pts"], sg.get("closed"))
        if (side[mid] > 0).sum() >= 3 and (side[mid] < 0).sum() >= 3:
            sg["entry_width"] = 2.0 * float(np.median(d[mid]))
    # children (touching segments) and island owners
    by_child: dict[int, list[int]] = {}
    for ti, trn in enumerate(ctx["trans"]):
        if trn["type"] == "parent-child" and trn["child"] >= 0:
            by_child.setdefault(trn["child"], []).append(ti)
    tr_raw = ctx["trans_raw"]
    for c in sorted(by_child):
        if island_of_piece[c] >= 0 or c in rgs:
            continue
        p = par(c)
        kids_walls = np.isin(tr_raw, by_child[c]) & (tr_raw >= 0)
        if not kids_walls.any():
            continue
        cn = t.node_mask(kids_walls)
        near = floor_el & (eff_piece == p) & cn[t.C[:, :3]].any(axis=1)
        for s in np.unique(seg_post[near & (seg_post >= 0)]).tolist():
            segs[s].setdefault("children", []).append(c)
    Pc = t.Pc
    trees: dict = {}
    ei = ctx["elem_island"]
    order = np.argsort(ei, kind="stable")
    cut = np.searchsorted(ei[order], np.arange(len(islands) + 1))
    for i in islands:
        ip = ctx["root"] if i["parent"] in rgs or i["parent"] < 0 else i["parent"]
        el = order[cut[i["id"]]:cut[i["id"] + 1]]
        if ip not in trees:
            fl_ = np.flatnonzero(floor_el & (eff_piece == ip) & (seg_post >= 0))
            trees[ip] = (fl_, cKDTree(Pc[fl_]) if fl_.size else None)
        fl, tree_ip = trees[ip]
        if el.size == 0 or fl.size == 0:
            i["owner_segment"] = -1
            continue
        _d, j = tree_ip.query(Pc[el].mean(axis=0))
        i["owner_segment"] = int(seg_post[fl[j]])
        segs[i["owner_segment"]].setdefault("islands", []).append(i["id"])
