"""classify(): shell mesh -> bead-network graph ``beadgraph/1`` + per-element labels (contract §2, BG-D-1..14).

Pipeline (BG-D-1, order fixed): topology / normals -> floor pieces -> base + frame -> wall ownership -> hierarchy,
islands, lances, holes -> skeleton segments / junctions -> junction-zone absorption, ring sides (``absorb``) ->
canonical numbering (BG-D-12) -> JSON.
"""
from __future__ import annotations

import time

import numpy as np
from scipy.sparse import coo_matrix, csgraph
from scipy.spatial import cKDTree

from . import _util as U
from .absorb import absorb_and_sides
from .levels import floor_pieces, piece_levels, wall_ownership
from .skeleton import assign_nearest, segment_piece
from .topo import Topo
from .tree import build_tree, find_root, islands_and_holes, outer_free, piece_loops

CLS = {"floor": 0, "wall": 1, "island": 2, "lance": 3}
LABEL_KEYS = ("cls", "floor", "segment", "transition", "island", "junction_zone", "tier")


class BeadgraphError(ValueError):
    """public-API error ``BeadgraphError(code, detail)`` (contract §8.2): code in TOO_LARGE | TIMEOUT | NO_FLOOR |
    INVALID_INPUT (empty / non-finite / bad-index mesh, bad arguments) | ERROR (any other failure inside the package —
    the original exception is chained as ``__cause__``) | BG_EDIT_INVALID (``edits.EditError``). esl: GRAPH_FAILED{code}
    (codes outside its list -> ERROR). Subclass of ValueError (callers catching ValueError keep working)."""

    def __init__(self, code: str, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class _Clock:
    def __init__(self, timeout_s):
        self.t0 = time.perf_counter()
        self.limit = float(timeout_s) if timeout_s else None

    def check(self, where: str):
        if self.limit is not None and time.perf_counter() - self.t0 > self.limit:
            raise BeadgraphError("TIMEOUT", f"classification exceeded {self.limit:g} s ({where})")


def _smooth_chain(pts: np.ndarray, closed: bool, win: int = 2) -> np.ndarray:
    """moving average of a pixel chain (removes the raster staircase; end points kept for open chains)."""
    n = len(pts)
    if n < 3:
        return pts.copy()
    out = np.zeros_like(pts)
    if closed:
        for k in range(-win, win + 1):
            out += np.roll(pts, k, axis=0)
        return out / (2 * win + 1)
    for i in range(n):
        w = min(win, i, n - 1 - i)
        out[i] = pts[i - w:i + w + 1].mean(axis=0)
    return out


def _decimate(pts: np.ndarray, nmax: int = 256) -> np.ndarray:
    if len(pts) <= nmax:
        return pts
    idx = np.unique(np.round(np.linspace(0, len(pts) - 1, nmax)).astype(int))
    return pts[idx]


def input_sha256(nodes, elems, fixed) -> str:
    import hashlib
    X = np.round(np.asarray(nodes, np.float64), 6) + 0.0
    E = np.asarray(elems, np.int64)
    if E.shape[1] == 3:
        E = np.c_[E, -np.ones(E.shape[0], np.int64)]
    E = E.copy()
    tri = (E[:, 3] < 0) | (E[:, 3] == E[:, 2]) | (E[:, 3] == E[:, 0])
    E[tri, 3] = -1
    F = np.sort(np.asarray(fixed if fixed is not None else [], np.int64).ravel())
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(X, "<f8").tobytes())
    h.update(np.ascontiguousarray(E, "<i4").tobytes())
    h.update(np.ascontiguousarray(F, "<i4").tobytes())
    return h.hexdigest()


def _display_axes(n0):
    """world-referenced plan axes for the ring side names only (screen up / down / left / right — BG-D-13)."""
    n = np.asarray(n0, float)
    n = n * (1.0 if n[int(np.argmax(np.abs(n)))] >= 0 else -1.0)
    t = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = t - n * (t @ n)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(n, e1)


def classify_full(nodes, elems, fixed=None, cfg=None, *, toggles=None):
    """-> (graph, labels, aux). aux carries internal arrays (topology, raw piece ids) for edits / morph / tests."""
    cfg = U.merged_cfg(cfg)
    lim = cfg.get("limits") or {}
    E = np.asarray(elems)
    if lim.get("max_elems") and E.shape[0] > int(lim["max_elems"]):
        raise BeadgraphError("TOO_LARGE", f"{E.shape[0]} elements > limits.max_elems {lim['max_elems']}")
    clk = _Clock(lim.get("timeout_s"))
    fixed_arr = np.unique(np.asarray(fixed if fixed is not None else [], np.int64).ravel())
    t = Topo(nodes, elems)
    piece, level, parea = floor_pieces(t, cfg)
    npc = level.size
    if npc == 0:
        raise BeadgraphError("NO_FLOOR", "no floor element within the feature angle")
    free, loops = outer_free(t, piece, npc)
    root, rg = find_root(level, parea, free, cfg)
    rg = _base_level_plates(t, piece, level, root, rg, cfg, toggles)
    rgs = set(rg)
    # frame: features rise from the base (sign of the area-weighted mean relative level) — orientation-free (V-BG-4)
    nr = np.array([p not in rgs for p in range(npc)])
    s = float((parea[nr] * (level[nr] - level[root])).sum()) if nr.any() else 0.0
    if s < 0:
        t.flip_n0()
    t.set_frame()
    level, parea = piece_levels(t, piece, npc)
    loops = piece_loops(t, piece, npc)
    rank = t.rank_key()
    clk.check("levels")
    up, dn = wall_ownership(t, piece, rank)
    clk.check("walls")
    tr = build_tree(t, piece, level, parea, up, dn, cfg, root, rg, loops)
    islands, elem_island, island_of_piece, holes, upE, dnE = islands_and_holes(t, piece, level, up, dn, tr, cfg,
                                                                                fixed_arr, toggles=toggles)
    clk.check("tree")
    parent = tr["parent"]
    eff_piece = np.where(np.isin(piece, rg), root, piece)

    def par(p):
        return root if p in rgs else int(parent[p])
    # ------------------------------------------------------------ transitions (all walls, island walls included)
    wall = piece < 0
    base = npc + 2
    keys = (upE + 1) * base + (dnE + 1)               # -1 (no floor reached) encoded as 0
    trans_raw = -np.ones(t.m, np.int64)
    uk, inv = np.unique(keys[wall], return_inverse=True)
    trans_raw[wall] = inv
    trans = []
    for i, k in enumerate(uk.tolist()):
        u, d = int(k // base) - 1, int(k % base) - 1
        if u >= 0 and d >= 0 and d != root and d not in rgs and par(d) == u:
            ty, child = "parent-child", d
        elif u >= 0 and d >= 0 and u != root and u not in rgs and par(u) == d:
            ty, child = "parent-child", u
        elif u == d:
            ty, child = "self", u
        elif u >= 0 and d >= 0 and u not in rgs and d not in rgs and par(u) == par(d):
            ty, child = "junction", -1
        else:
            ty, child = "other", -1
        trans.append({"upper": u, "lower": d, "type": ty, "child": child})
    isl_m = elem_island >= 0
    # ------------------------------------------------------------ segments per floor
    outline = tr["outline_nodes"]
    fe = t.edges[t.free_edges]
    fe_el = t.e2a[t.free_edges]
    on_out = np.array([(a in outline) and (b in outline) for a, b in fe.tolist()]) if fe.size else np.zeros(0, bool)
    segs: list[dict] = []
    juncs: list[dict] = []
    elem_seg = -np.ones(t.m, np.int64)
    floor_kind: dict[int, str] = {}
    warnings: list[dict] = []
    coarse_res = []
    for p in range(npc):
        if island_of_piece[p] >= 0 or p in rgs:
            continue
        clk.check("skeleton")
        eidx = np.flatnonzero(piece == p)
        ports = [tuple(x) for x in fe[on_out & (piece[fe_el] == p)].tolist()]
        res = segment_piece(t, eidx, cfg, ports)
        if res.get("coarse"):
            coarse_res.append(float(res["res"]))
        if res["kind"] == "bead" and not res["segments"]:
            res = {"kind": "area"}
        floor_kind[p] = "bead" if res["kind"] == "bead" else "area"
        if res["kind"] == "area":
            sid = len(segs)
            kids = [c for c in tr["children"][p] if island_of_piece[c] < 0]
            segs.append({"floor": p, "type": "plateau" if kids else "area", "pts": None, "length": None,
                         "floor_w": None, "ends": [], "open_end": False, "closed": False, "w_profile": None})
            elem_seg[eidx] = sid
            continue
        j0, s0 = len(juncs), len(segs)
        for j in res["junctions"]:
            juncs.append({"type": j["type"], "plan": np.asarray(j["pos"], float), "r": float(j["r"]), "floor": p,
                          "segs": [s0 + s for s in j["segs"]]})
        for sg in res["segments"]:
            segs.append({"floor": p, "type": None, "pts": _smooth_chain(np.asarray(sg["pts"], float), sg["closed"]),
                         "length": sg["length"], "floor_w": sg["floor_w"], "ends": [j0 + e for e in sg["ends"]],
                         "open_end": sg["open_end"], "closed": sg["closed"], "w_profile": sg["w_profile"],
                         "flare": sg.get("flare", False)})
        lab, _d = assign_nearest([sg["pts"] for sg in segs[s0:]], t.Pc[eidx])
        elem_seg[eidx] = s0 + lab
    if coarse_res:
        warnings.append({"code": "GRAPH_RASTER_COARSE", "level": "info", "raster_mm": U.f3(max(coarse_res))})
    # base segment (flange + fragments)
    base_sid = len(segs)
    segs.append({"floor": root, "type": "base", "pts": None, "length": None, "floor_w": None, "ends": [],
                 "open_end": False, "closed": False, "w_profile": None})
    elem_seg[np.isin(piece, rg)] = base_sid
    floor_kind[root] = "base"
    # drop pass-through junction records (degree 2 clusters) — schema types are T X L W Y step
    keep_j = [i for i, j in enumerate(juncs) if j["type"] != "pass"]
    jmap = {o: n for n, o in enumerate(keep_j)}
    juncs = [juncs[i] for i in keep_j]
    for sg in segs:
        sg["ends"] = [jmap[e] for e in sg["ends"] if e in jmap]
    clk.check("segments")
    # ------------------------------------------------------------ wall -> segment (nearest child-floor element, BG-D-7)
    Pc = t.Pc
    for ti, trn in enumerate(trans):
        w = np.flatnonzero((trans_raw == ti) & ~isl_m)
        if w.size == 0:
            continue
        if trn["type"] == "parent-child":
            src = trn["child"]
        elif trn["type"] == "self":
            src = trn["upper"]
        else:
            continue
        fl = np.flatnonzero((eff_piece == src) & (piece >= 0) & ~isl_m)
        if fl.size == 0:
            continue
        elem_seg[w] = _nearest_label(Pc[fl], elem_seg[fl], Pc[w])
    # ------------------------------------------------------------ step junctions (sibling walls)
    pa, pb = t.pairs[:, 0], t.pairs[:, 1]
    for ti, trn in enumerate(trans):
        if trn["type"] != "junction":
            continue
        w = np.flatnonzero((trans_raw == ti) & ~isl_m)
        if w.size == 0:
            continue
        inw = np.zeros(t.m, bool)
        inw[w] = True
        m = inw[pa] & inw[pb]
        G = coo_matrix((np.ones(m.sum()), (pa[m], pb[m])), shape=(t.m, t.m))
        _n, lab = csgraph.connected_components(G, directed=False)
        for comp in np.unique(lab[w]).tolist():
            ww = w[lab[w] == comp]
            pos = Pc[ww].mean(axis=0)
            linked = []
            for fl_id in (trn["upper"], trn["lower"]):
                fl = np.flatnonzero((piece == fl_id) & ~isl_m)
                if fl.size:
                    _d, j = cKDTree(Pc[fl]).query(pos)
                    sid = int(elem_seg[fl[j]])
                    if sid >= 0 and sid not in linked:
                        linked.append(sid)
            juncs.append({"type": "step", "plan": pos, "r": float(np.ptp(Pc[ww], axis=0).max() / 2), "floor": -1,
                          "segs": linked, "elems": ww,
                          "step_mm": abs(float(level[trn["upper"]] - level[trn["lower"]]))})
            for sid in linked:
                segs[sid]["ends"].append(len(juncs) - 1)
    clk.check("steps")
    ctx = {"t": t, "cfg": cfg, "piece": piece, "eff_piece": eff_piece, "level": level, "tr": tr, "rg": rg, "root": root,
           "par": par, "trans": trans, "trans_raw": trans_raw, "elem_island": elem_island, "isl_m": isl_m,
           "island_of_piece": island_of_piece, "islands": islands, "elem_seg": elem_seg, "segs": segs, "juncs": juncs,
           "floor_kind": floor_kind, "display_axes": _display_axes(t.n0)}
    zones, elem_jz = absorb_and_sides(ctx)
    clk.check("absorb")
    graph, labels, aux = _assemble(ctx, zones, elem_jz, holes, upE, dnE, fixed_arr, nodes, elems, warnings)
    return graph, labels, aux


def _base_level_plates(t, piece, level, root, rg, cfg, toggles):
    """root group += pieces at the base level (± level_tol) larger than an island (plan extent > island.max_mm): a base
    plate enclosed by a groove network (H5 ring interior) is base, not a raised child of the groove floor — otherwise the
    groove flanks would be owned by the plate and the groove would lose its walls (W)."""
    tol = cfg["level_tol_mm"]
    imax = cfg["island"]["max_mm"]
    out = set(rg)
    for p in np.flatnonzero(np.abs(level - level[root]) <= tol).tolist():
        if p in out or (toggles or {}).get(p) == "island":
            continue
        nodes = t.elem_nodes(piece == p)
        if nodes.size < 3:
            continue
        P = t.P[nodes] - t.P[nodes].mean(axis=0)
        _u, _s, Vt = np.linalg.svd(P, full_matrices=False)
        Q = P @ Vt.T
        if float((Q.max(axis=0) - Q.min(axis=0)).max()) > imax:
            out.add(p)
    return sorted(out)


def _nearest_label(P_src, lab_src, Q):
    """nearest source point label; equal distances (1e-9) -> the smaller label (BG-D-7)."""
    k = min(4, len(P_src))
    d, j = cKDTree(P_src).query(Q, k=k)
    if k == 1:
        return lab_src[j]
    d = np.asarray(d)
    j = np.asarray(j)
    labs = lab_src[j]
    near = d <= d[:, :1] + 1e-6
    big = np.iinfo(np.int64).max
    return np.where(near, labs, big).min(axis=1)


def _assemble(ctx, zones, elem_jz, holes, upE, dnE, fixed_arr, nodes, elems, warnings):
    t, cfg = ctx["t"], ctx["cfg"]
    piece, eff_piece, level, tr = ctx["piece"], ctx["eff_piece"], ctx["level"], ctx["tr"]
    root, rg, par = ctx["root"], ctx["rg"], ctx["par"]
    rgs = set(rg)
    segs, juncs = ctx["segs"], ctx["juncs"]
    elem_seg, elem_island, isl_m = ctx["elem_seg"], ctx["elem_island"], ctx["isl_m"]
    islands, island_of_piece = ctx["islands"], ctx["island_of_piece"]
    trans, trans_raw = ctx["trans"], ctx["trans_raw"]
    npc = level.size
    m = t.m
    # ------------------------------------------------------------ canonical numbering (BG-D-12)
    eidx = np.arange(m)
    first_el = np.full(npc, m, np.int64)
    np.minimum.at(first_el, piece[piece >= 0], eidx[piece >= 0])
    ftier = np.array([0 if p in rgs else int(tr["tier"][p]) for p in range(npc)])
    forder = sorted(range(npc), key=lambda p: (int(ftier[p]), int(first_el[p])))
    fmap = {o: n for n, o in enumerate(forder)}
    fmap[-1] = -1

    def F(p):
        return fmap[int(p)] if p is not None else -1
    alive = [i for i, s in enumerate(segs) if not s.get("absorbed")]
    sfirst = {}
    for i in alive:
        mm = elem_seg == i
        sfirst[i] = int(np.flatnonzero(mm)[0]) if mm.any() else m

    def skey(i):
        s = segs[i]
        p0 = s.get("pts")
        st = tuple(np.round(p0[0], 3).tolist()) if p0 is not None and len(p0) else (0.0, 0.0)
        return (F(s["floor"]), st, sfirst[i])
    sorder = sorted(alive, key=skey)
    smap = {o: n for n, o in enumerate(sorder)}
    jorder = sorted(range(len(juncs)), key=lambda j: (round(float(juncs[j]["plan"][0]), 3),
                                                      round(float(juncs[j]["plan"][1]), 3), juncs[j]["type"]))
    jmap = {o: n for n, o in enumerate(jorder)}
    zfirst = []
    for z in range(len(zones)):
        mm = elem_jz == z
        zfirst.append(int(np.flatnonzero(mm)[0]) if mm.any() else m)
    zorder = sorted(range(len(zones)), key=lambda z: zfirst[z])
    zmap = {o: n for n, o in enumerate(zorder)}
    ifirst = []
    for i in range(len(islands)):
        mm = elem_island == i
        ifirst.append(int(np.flatnonzero(mm)[0]) if mm.any() else m)
    iorder = sorted(range(len(islands)), key=lambda i: ifirst[i])
    imap = {o: n for n, o in enumerate(iorder)}
    imap[-1] = -1
    horder = sorted(range(len(holes)), key=lambda h: (round(float(holes[h]["center"][0]), 3),
                                                      round(float(holes[h]["center"][1]), 3),
                                                      round(float(holes[h]["center"][2]), 3)))
    torder = sorted(range(len(trans)), key=lambda i: (F(trans[i]["upper"]), F(trans[i]["lower"])))
    tmap = {o: n for n, o in enumerate(torder)}
    # ------------------------------------------------------------ labels
    fl_lut = np.array([fmap[p] for p in range(npc)] + [-1], np.int64)
    lab_floor = np.where(piece >= 0, fl_lut[np.where(eff_piece >= 0, eff_piece, npc)], -1)
    seg_lut = -np.ones(len(segs) + 1, np.int64)
    for o, n in smap.items():
        seg_lut[o] = n
    lab_seg = np.where(elem_seg >= 0, seg_lut[np.where(elem_seg >= 0, elem_seg, len(segs))], -1)
    lab_seg[isl_m] = -1
    lab_jz = np.where(elem_jz >= 0, np.array([zmap.get(int(z), -1) for z in elem_jz.tolist()]), -1)
    lab_seg[lab_jz >= 0] = -1
    lab_isl = np.where(isl_m, np.array([imap[int(i)] for i in elem_island.tolist()]), -1)
    lab_tr = np.where(trans_raw >= 0, np.array([tmap.get(int(x), -1) for x in trans_raw.tolist()]), -1)
    cls = np.where(piece >= 0, CLS["floor"], CLS["wall"])
    lance_ids = np.array([i["lance"] for i in islands], bool) if islands else np.zeros(0, bool)
    cls[isl_m] = np.where(lance_ids[elem_island[isl_m]], CLS["lance"], CLS["island"])
    tier_e = np.where(piece >= 0, ftier[np.maximum(eff_piece, 0)], -1)
    for ti, trn in enumerate(trans):
        w = trans_raw == ti
        c = trn["child"] if trn["child"] >= 0 else trn["lower"]
        tier_e[w] = ftier[c] if c >= 0 else -1
    tier_e[isl_m] = -1
    labels = {"cls": cls.astype(np.int32), "floor": lab_floor.astype(np.int32), "segment": lab_seg.astype(np.int32),
              "transition": lab_tr.astype(np.int32), "island": lab_isl.astype(np.int32),
              "junction_zone": lab_jz.astype(np.int32), "tier": tier_e.astype(np.int32)}
    # ------------------------------------------------------------ JSON parts
    f3 = U.f3
    fixed_mask = np.zeros(t.n, bool)
    fixed_mask[fixed_arr[(fixed_arr >= 0) & (fixed_arr < t.n)]] = True
    floors = []
    networks_by_floor: dict[int, int] = {}
    net_list = sorted({s["floor"] for i, s in enumerate(segs) if i in smap and s["type"] != "base"}, key=F)
    for k, p in enumerate(net_list):
        networks_by_floor[p] = k
    for p in forder:
        kind = ("base" if p == root else "base_fragment" if p in rgs else "island" if island_of_piece[p] >= 0
                else ctx["floor_kind"].get(p, "area"))
        floors.append({"id": fmap[p], "anchor": int(first_el[p]), "level": f3(level[p]),
                       "rel_height": f3(level[p] - level[par(p)]) if p not in rgs else 0.0,
                       "parent": F(par(p)) if p != root and p not in rgs else (-1 if p == root else F(root)),
                       "tier": int(ftier[p]), "kind": kind, "island": imap[int(island_of_piece[p])],
                       "area": f3(np.round(float(t.area[piece == p].sum()), 1)), "n_elems": int((piece == p).sum()),
                       "outer_free_frac": f3(tr["info"][p]["free"]),
                       "network": networks_by_floor.get(p, -1)})
    transitions = []
    for o in torder:
        trn = trans[o]
        d = {"id": tmap[o], "upper": F(trn["upper"]), "lower": F(trn["lower"]), "type": trn["type"],
             "child": F(trn["child"]), "n_elems": int((trans_raw == o).sum())}
        if trn["type"] == "junction":
            d["step_mm"] = f3(abs(level[trn["upper"]] - level[trn["lower"]]))
        transitions.append(d)
    out_segments = []
    for o in sorder:
        s = segs[o]
        sid = smap[o]
        p = s["floor"]
        mm = lab_seg == sid
        pp = par(p) if p != root else -1
        skel = None
        if s.get("pts") is not None:
            skel = [[f3(a), f3(b)] for a, b in _decimate(np.asarray(s["pts"])).tolist()]
        out_segments.append({
            "id": sid, "anchor": int(np.flatnonzero(mm)[0]) if mm.any() else -1, "floor": F(p),
            "parent": F(pp) if p != root else -1, "tier": int(ftier[p]),
            "network": networks_by_floor.get(p, -1), "type": s["type"], "side": s.get("side"),
            "rel_depth": f3(level[p] - level[pp]) if p != root else 0.0,
            "D": f3(s.get("D", 0.0)), "entry_width": None if s.get("entry_width") is None else f3(s["entry_width"]),
            "floor_width": None if s.get("floor_w") is None else f3(s["floor_w"]),
            "length": None if s.get("length") is None else f3(s["length"]),
            "open_end": bool(s.get("open_end")), "junctions": sorted(jmap[j] for j in s["ends"] if j in jmap),
            "children": sorted({F(c) for c in s.get("children", [])}),
            "islands": sorted({imap[i] for i in s.get("islands", [])}),
            "fixed_n": int(fixed_mask[t.elem_nodes(mm)].sum()) if mm.any() else 0, "n_elems": int(mm.sum()),
            "skeleton": skel})
    out_j = []
    for o in jorder:
        j = juncs[o]
        lv = level[j["floor"]] if j["floor"] >= 0 else (level[segs[j["segs"][0]]["floor"]] if j["segs"] else 0.0)
        pos = t.e1 * (j["plan"][0] + t.origin[0]) + t.e2 * (j["plan"][1] + t.origin[1]) + t.n0 * lv
        d = {"id": jmap[o], "type": j["type"], "plan": [f3(v) for v in j["plan"]], "pos": [f3(v) for v in pos],
             "radius": f3(j["r"]), "segments": sorted(smap[s] for s in j["segs"] if s in smap),
             "floors": sorted({F(segs[s]["floor"]) for s in j["segs"]} | ({F(j["floor"])} if j["floor"] >= 0 else set())),
             "zone": zmap.get(j.get("zone", -1), -1)}
        if j["type"] == "step":
            d["step_mm"] = f3(j["step_mm"])
        out_j.append(d)
    out_z = []
    for o in zorder:
        z = zones[o]
        mm = lab_jz == zmap[o]
        out_z.append({"id": zmap[o], "anchor": int(np.flatnonzero(mm)[0]) if mm.any() else -1,
                      "network": networks_by_floor.get(z["floor"], -1), "reason": z["reason"],
                      "junctions": sorted(jmap[j] for j in z["junctions"] if j in jmap),
                      "adj_segments": sorted(smap[s] for s in z["adj"] if s in smap), "n_elems": int(mm.sum())})
    networks = []
    for p in net_list:
        k = networks_by_floor[p]
        networks.append({"id": k, "floor": F(p), "segments": sorted(sg["id"] for sg in out_segments if sg["network"] == k),
                         "junction_zones": sorted(z["id"] for z in out_z if z["network"] == k)})
    out_isl = []
    for o in iorder:
        i = islands[o]
        e = lab_isl == imap[o]
        c = t.Pc[e].mean(axis=0) if e.any() else np.zeros(2)
        ip_ = root if (i["parent"] in rgs or i["parent"] < 0) else int(i["parent"])
        out_isl.append({"id": imap[o], "anchor": int(np.flatnonzero(e)[0]) if e.any() else -1,
                        "floors": sorted(F(x) for x in i["pieces"]), "parent": F(ip_),
                        "owner_segment": smap.get(i.get("owner_segment", -1), -1),
                        "size_mm": f3(i["size_mm"]), "rel_height": f3(max(level[x] for x in i["pieces"]) - level[ip_]),
                        "lance": bool(i["lance"]), "straddle": bool(i["straddle"]),
                        "touch": [{"kind": x["kind"], "ids": _touch_ids(x, F, imap, tmap_pair=(F,)), "n": x["n"]}
                                  for x in i["touch"][:6]],
                        "fixed": bool(fixed_mask[t.elem_nodes(e)].any()) if e.any() else False,
                        "plan": [f3(v) for v in c], "n_elems": int(e.sum())})
    out_h = []
    for k, o in enumerate(horder):
        h = holes[o]
        out_h.append({"id": k, "plan": [f3(v) for v in h["center_plan"]], "center": [f3(v) for v in h["center"]],
                      "d_eq": f3(h["d_eq"]), "area": f3(h["area"]), "circularity": f3(h["circularity"]),
                      "owner_floor": F(eff_piece_of(h["owner_floor"], rgs, root)), "owner_island": imap[h["owner_island"]],
                      "lance_slot": bool(h["lance_slot"]), "fixed": bool(h["fixed"]), "n_nodes": int(len(h["nodes"]))})
    from . import MORPH_RULES, RULES, SCHEMA, __version__
    graph = {
        "schema": SCHEMA, "version": __version__, "rules": RULES, "morph_rules": MORPH_RULES,
        "input": {"n_nodes": int(t.n), "n_elems": int(t.m), "n_tri": int(t.tri.sum()), "n_fixed": int(fixed_arr.size),
                  "sha256": input_sha256(nodes, elems, fixed_arr)},
        "cfg": cfg, "cfg_sha256": U.sha256_json(cfg),
        "frame": {"n0": [U.f(v, 15) for v in t.n0], "e1": [U.f(v, 15) for v in t.e1], "e2": [U.f(v, 15) for v in t.e2],
                  "origin": [f3(v) for v in t.origin], "h_mm": f3(t.h_med),
                  "bbox_center": [f3(v) for v in 0.5 * (t.P.min(axis=0) + t.P.max(axis=0))]},
        "root": F(root), "root_group": sorted(F(x) for x in rg),
        "floors": floors, "transitions": transitions, "networks": networks, "segments": out_segments,
        "junctions": out_j, "junction_zones": out_z, "islands": out_isl, "holes": out_h,
        "warnings": warnings,
    }
    aux = {"topo": t, "piece": piece, "fmap": fmap, "smap": smap, "level": level,
           "seg_raw": np.where(isl_m, -1, elem_seg)}
    return graph, labels, aux


def eff_piece_of(p, rgs, root):
    return root if p in rgs else p


def _touch_ids(x, F, imap, tmap_pair=None):
    if x["kind"] == "floor":
        return [F(x["ids"][0])]
    if x["kind"] == "island":
        return [imap.get(x["ids"][0], -1)]
    return [F(v) if v >= 0 else -1 for v in x["ids"]]
