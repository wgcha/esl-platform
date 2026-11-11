"""User edits on a classified graph (BG-D-37): toggle (island <-> bead), merge (adjacent segments), split (segment at a
plan point); anchor resolution (BG-D-12·30) and mirror-pair suggestions (BG-D-21). Deterministic: the same graph,
labels and edits give the same bytes. Order = toggle -> merge -> split (each list sorted)."""
from __future__ import annotations

import copy

import numpy as np

from . import _util as U
from .classify import CLS, BeadgraphError


class EditError(BeadgraphError):
    def __init__(self, code: str, msg: str, **detail):
        ValueError.__init__(self, f"{code}: {msg}")
        self.code = code
        self.detail = detail


def resolve(graph, labels, ref) -> int:
    """{anchor: elem} -> segment id containing that element; {network: elem} -> network id of the element's floor.
    KeyError when the anchor no longer resolves (esl: BG_SEG_UNKNOWN)."""
    if not isinstance(ref, dict):
        raise KeyError(ref)
    seg = labels["segment"]
    n = seg.size
    if "network" in ref:
        a = int(ref["network"])
        if not 0 <= a < n:
            raise KeyError(ref)
        f = int(labels["floor"][a])
        if f < 0 and seg[a] >= 0:
            f = graph["segments"][int(seg[a])]["floor"]
        for net in graph["networks"]:
            if net["floor"] == f:
                return int(net["id"])
        raise KeyError(ref)
    a = int(ref.get("anchor", -1))
    if not 0 <= a < n or seg[a] < 0:
        raise KeyError(ref)
    s = int(seg[a])
    if graph["segments"][s]["type"] == "base":
        raise KeyError(ref)
    return s


def _floor_of_anchor(graph, labels, a):
    """element id (any element of a segment, island or floor — e.g. the segment / island anchor the UI sends) -> floor:
    island element -> the island's root floor (lowest tier); floor element -> its floor; wall / zone element -> the
    floor of its segment."""
    if not 0 <= a < labels["floor"].size:
        raise KeyError({"anchor": a})
    i = int(labels["island"][a])
    if i >= 0:
        isl = graph["islands"][i]
        fl = sorted(isl["floors"], key=lambda x: (graph["floors"][x]["tier"], x))
        if fl:
            return fl[0]
    f = int(labels["floor"][a])
    if f >= 0:
        return f
    s = int(labels["segment"][a])
    if s >= 0:
        return graph["segments"][s]["floor"]
    z = int(labels["junction_zone"][a])
    if z >= 0:
        adj = graph["junction_zones"][z]["adj_segments"]
        if adj:
            return graph["segments"][adj[0]]["floor"]
    raise KeyError({"anchor": a})


def _subtree(graph, f):
    kids = {}
    for fl in graph["floors"]:
        kids.setdefault(fl["parent"], []).append(fl["id"])
    out, st = [f], list(kids.get(f, []))
    while st:
        q = st.pop()
        if graph["floors"][q]["kind"] in ("base", "base_fragment"):
            continue
        out.append(q)
        st += kids.get(q, [])
    return out


def apply(graph, labels, edits, nodes=None, elems=None):
    g = copy.deepcopy(graph)
    lab = {k: np.array(v, np.int32, copy=True) for k, v in labels.items()}
    edits = edits or {}
    tog = sorted(edits.get("toggle") or [], key=lambda e: (int(e["anchor"]), str(e.get("as"))))
    for e in tog:
        _toggle(g, lab, int(e["anchor"]), e.get("as"))
    if tog:
        _renumber(g, lab)
    mer = sorted([sorted(int(x["anchor"]) for x in grp) for grp in (edits.get("merge") or [])])
    for grp in mer:
        _merge(g, lab, grp)
    if mer:
        _renumber(g, lab)
    spl = sorted(edits.get("split") or [], key=lambda e: (int(e["anchor"]), tuple(e["at"])))
    for e in spl:
        if nodes is None or elems is None:
            raise EditError("BG_EDIT_INVALID", "split needs the mesh (nodes, elems)", edit=e)
        _split(g, lab, int(e["anchor"]), np.asarray(e["at"], float), nodes, elems)
    if spl:
        _renumber(g, lab)
    return g, lab


# ---------------------------------------------------------------------------------------------------- toggle
def _toggle(g, lab, anchor, as_):
    if as_ not in ("bead", "island"):
        raise EditError("BG_EDIT_INVALID", f"toggle as {as_!r}", edit={"anchor": anchor, "as": as_})
    f = _floor_of_anchor(g, lab, anchor)
    fl = g["floors"][f]
    if fl["kind"] in ("base", "base_fragment"):
        raise EditError("BG_EDIT_INVALID", "the base cannot be toggled", edit={"anchor": anchor, "as": as_})
    trans = {t["id"]: t for t in g["transitions"]}
    if as_ == "bead":
        iid = fl["island"]
        if iid < 0:
            return
        isl = g["islands"][iid]
        tids = [t["id"] for t in g["transitions"] if t["child"] == f or
                (t["type"] == "parent-child" and f in (t["upper"], t["lower"]) and fl["parent"] in (t["upper"], t["lower"]))]
        fe = (lab["floor"] == f) & (lab["island"] == iid)
        we = np.isin(lab["transition"], tids) & (lab["island"] == iid)
        sid = len(g["segments"])
        par = fl["parent"]
        nid = len(g["networks"])
        lab["cls"][fe] = CLS["floor"]
        lab["cls"][we] = CLS["wall"]
        lab["island"][fe | we] = -1
        lab["segment"][fe | we] = sid
        lab["tier"][fe] = fl["tier"]
        lab["tier"][we] = fl["tier"]
        g["segments"].append({"id": sid, "anchor": int(np.flatnonzero(fe | we)[0]), "floor": f, "parent": par,
                              "tier": fl["tier"], "network": nid, "type": "area", "side": None,
                              "rel_depth": fl["rel_height"], "D": U.f3(abs(fl["rel_height"])), "entry_width": None,
                              "floor_width": None, "length": None, "open_end": False, "junctions": [], "children": [],
                              "islands": [], "fixed_n": 0, "n_elems": int((fe | we).sum()), "skeleton": None,
                              "toggled": "bead"})
        g["networks"].append({"id": nid, "floor": f, "segments": [sid], "junction_zones": []})
        fl.update(kind="area", island=-1, network=nid)
        isl["floors"] = [x for x in isl["floors"] if x != f]
        isl["n_elems"] = int((lab["island"] == iid).sum())
        if not isl["floors"] or isl["n_elems"] == 0:
            isl["_dead"] = True
        else:                                      # remaining pieces (e.g. a boss on the toggled emboss) stay an island
            isl["parent"] = f
        _ = trans
        return
    # bead -> island: the whole subtree becomes one rigid island (size ignored)
    if fl["island"] >= 0:
        return
    sub = _subtree(g, f)
    subs = set(sub)
    tids = [t["id"] for t in g["transitions"] if (t["upper"] in subs or t["lower"] in subs)]
    el = (np.isin(lab["floor"], sub) & (lab["cls"] == CLS["floor"])) | np.isin(lab["transition"], tids)
    isl_in = [i["id"] for i in g["islands"] if i["parent"] in subs or set(i["floors"]) & subs]
    el |= np.isin(lab["island"], isl_in) & (lab["island"] >= 0)
    for i in isl_in:
        g["islands"][i]["_dead"] = True
    iid = len(g["islands"])
    lab["island"][el] = iid
    lab["cls"][el] = CLS["island"]
    lab["segment"][el] = -1
    lab["junction_zone"][el] = -1
    lab["tier"][el] = -1
    dead_s = {s["id"] for s in g["segments"] if s["floor"] in subs}
    for s in g["segments"]:
        if s["id"] in dead_s:
            s["_dead"] = True
    for z in g["junction_zones"]:
        if set(z["adj_segments"]) and set(z["adj_segments"]) <= dead_s or \
                (z["reason"] == "step" and set(z["adj_segments"]) & dead_s) or \
                (z["network"] >= 0 and g["networks"][z["network"]]["floor"] in subs):
            z["_dead"] = True
            lab["junction_zone"][lab["junction_zone"] == z["id"]] = -1
    for n in g["networks"]:
        if n["floor"] in subs:
            n["_dead"] = True
    for x in sub:
        g["floors"][x].update(kind="island", island=iid, network=-1)
    owner = -1
    pf = fl["parent"]
    cand = [s for s in g["segments"] if s["floor"] == pf and not s.get("_dead")]
    if cand:
        owner = cand[0]["id"]
    g["islands"].append({"id": iid, "anchor": int(np.flatnonzero(el)[0]), "floors": sorted(sub), "parent": pf,
                         "owner_segment": owner, "size_mm": 0.0, "rel_height": fl["rel_height"], "lance": False,
                         "straddle": False, "touch": [], "fixed": False, "plan": [0.0, 0.0],
                         "n_elems": int(el.sum()), "toggled": "island"})


# ---------------------------------------------------------------------------------------------------- merge
def _merge(g, lab, anchors):
    ids = sorted({resolve(g, lab, {"anchor": a}) for a in anchors})
    if len(ids) < 2:
        raise EditError("BG_EDIT_INVALID", "merge needs >= 2 distinct segments", edit=anchors)
    segs = [g["segments"][i] for i in ids]
    if len({s["floor"] for s in segs}) != 1:
        raise EditError("BG_EDIT_INVALID", "merge: segments on different floors", edit=anchors)
    idset = set(ids)
    # connectivity through zones adjacent to >= 2 group members
    links = [z for z in g["junction_zones"] if len(set(z["adj_segments"]) & idset) >= 2 and not z.get("_dead")]
    comp = {i: i for i in ids}

    def find(a):
        while comp[a] != a:
            a = comp[a]
        return a
    for z in links:
        m = sorted(set(z["adj_segments"]) & idset)
        for a, b in zip(m, m[1:]):
            comp[find(b)] = find(a)
    if len({find(i) for i in ids}) != 1:
        raise EditError("BG_EDIT_INVALID", "merge: segments are not adjacent", edit=anchors)
    keep = ids[0]
    k = g["segments"][keep]
    for z in links:                                 # absorb zones between members only
        if set(z["adj_segments"]) <= idset and z["reason"] != "step":
            lab["segment"][lab["junction_zone"] == z["id"]] = keep
            lab["junction_zone"][lab["junction_zone"] == z["id"]] = -1
            z["_dead"] = True
    lens = np.array([float(s["length"] or 0.0) for s in segs])
    w = lens / lens.sum() if lens.sum() > 0 else np.ones(len(segs)) / len(segs)
    for s in segs[1:]:
        lab["segment"][lab["segment"] == s["id"]] = keep
        s["_dead"] = True
    k["D"] = U.f3(sum(float(s["D"]) * wi for s, wi in zip(segs, w)))
    ews = [s["entry_width"] for s in segs]
    k["entry_width"] = None if any(e is None for e in ews) else U.f3(sum(float(e) * wi for e, wi in zip(ews, w)))
    k["length"] = U.f3(lens.sum()) if lens.sum() > 0 else None
    k["type"] = max(segs, key=lambda s: (float(s["length"] or 0.0), -s["id"]))["type"]
    sides = {s["side"] for s in segs}
    k["side"] = sides.pop() if len(sides) == 1 else None
    k["skeleton"] = _chain([s["skeleton"] for s in segs if s["skeleton"]])
    for key in ("children", "islands", "junctions"):
        k[key] = sorted(set().union(*[set(s[key]) for s in segs]))
    k["open_end"] = any(s["open_end"] for s in segs)
    for i in g["islands"]:
        if i["owner_segment"] in idset:
            i["owner_segment"] = keep
    k["merged"] = ids


def _chain(sks):
    """concatenate skeleton polylines end-to-end (greedy nearest end), <= 256 points."""
    if not sks:
        return None
    parts = [np.asarray(s, float) for s in sks]
    cur = parts.pop(0)
    while parts:
        best = None
        for i, p in enumerate(parts):
            for rev_c in (False, True):
                for rev_p in (False, True):
                    a = cur[0] if rev_c else cur[-1]
                    b = p[-1] if rev_p else p[0]
                    d = float(np.hypot(*(a - b)))
                    if best is None or d < best[0]:
                        best = (d, i, rev_c, rev_p)
        _d, i, rc, rp = best
        p = parts.pop(i)
        c = cur[::-1] if rc else cur
        q = p[::-1] if rp else p
        cur = np.r_[c, q]
    if len(cur) > 256:
        cur = cur[np.unique(np.round(np.linspace(0, len(cur) - 1, 256)).astype(int))]
    return [[U.f3(a), U.f3(b)] for a, b in cur.tolist()]


# ---------------------------------------------------------------------------------------------------- split
def _split(g, lab, anchor, at, nodes, elems):
    sid = resolve(g, lab, {"anchor": anchor})
    s = g["segments"][sid]
    if not s["skeleton"] or len(s["skeleton"]) < 5:
        raise EditError("BG_EDIT_INVALID", "split needs a segment skeleton", edit={"anchor": anchor})
    sk = np.asarray(s["skeleton"], float)
    k = int(np.argmin(np.hypot(sk[:, 0] - at[0], sk[:, 1] - at[1])))
    if k < 2 or k > len(sk) - 3:
        raise EditError("BG_EDIT_INVALID", "split point at a segment end", edit={"anchor": anchor})
    fr = g["frame"]
    X = np.asarray(nodes, float)
    C = np.asarray(elems, np.int64)
    e1, e2 = np.asarray(fr["e1"], float), np.asarray(fr["e2"], float)
    o = np.asarray(fr.get("origin", [0.0, 0.0]), float)
    el = np.flatnonzero(lab["segment"] == sid)
    cc = C[el]
    cnt = (cc >= 0).sum(axis=1)
    cen = np.where(cc[..., None] >= 0, X[np.maximum(cc, 0)], 0.0).sum(axis=1) / cnt[:, None]
    P = np.c_[cen @ e1, cen @ e2] - o
    a_pts, b_pts = sk[:k + 1], sk[k:]
    from .absorb import polyline_dist
    da, *_ = polyline_dist(P, a_pts)
    db, *_ = polyline_dist(P, b_pts)
    new = len(g["segments"])
    to_b = db < da
    lab["segment"][el[to_b]] = new
    h = float(fr["h_mm"])
    near = np.hypot(P[:, 0] - sk[k, 0], P[:, 1] - sk[k, 1]) <= max(h, 1e-6)
    zid = len(g["junction_zones"])
    jid = len(g["junctions"])
    lab["segment"][el[near]] = -1
    lab["junction_zone"][el[near]] = zid
    L = float(s["length"] or 0.0)
    la = float(np.linalg.norm(np.diff(a_pts, axis=0), axis=1).sum())
    lb = float(np.linalg.norm(np.diff(b_pts, axis=0), axis=1).sum())
    b = copy.deepcopy(s)
    b.update(id=new, skeleton=[[U.f3(x), U.f3(y)] for x, y in b_pts.tolist()], length=U.f3(lb * L / max(la + lb, 1e-9)),
             junctions=[jid])
    s.update(skeleton=[[U.f3(x), U.f3(y)] for x, y in a_pts.tolist()], length=U.f3(la * L / max(la + lb, 1e-9)))
    s["junctions"] = sorted(set(s["junctions"]) | {jid})
    g["segments"].append(b)
    lv = float(g["floors"][s["floor"]]["level"])
    pos = e1 * (sk[k, 0] + o[0]) + e2 * (sk[k, 1] + o[1]) + np.asarray(fr["n0"], float) * lv
    g["junctions"].append({"id": jid, "type": "split", "plan": [U.f3(v) for v in sk[k]], "pos": [U.f3(v) for v in pos],
                           "radius": U.f3(h), "segments": [sid, new], "floors": [s["floor"]], "zone": zid})
    g["junction_zones"].append({"id": zid, "anchor": int(el[near][0]) if near.any() else -1, "network": s["network"],
                                "reason": "split", "junctions": [jid], "adj_segments": [sid, new],
                                "n_elems": int(near.sum())})


# ---------------------------------------------------------------------------------------------------- renumber
def _renumber(g, lab):
    """drop dead records, re-number by the BG-D-12 keys and remap every reference + label array."""
    def first(arr, i):
        w = np.flatnonzero(arr == i)
        return int(w[0]) if w.size else 1 << 60
    segs = [s for s in g["segments"] if not s.get("_dead")]
    for s in segs:
        s["anchor"] = first(lab["segment"], s["id"])

    def skey(s):
        st = tuple(s["skeleton"][0]) if s["skeleton"] else (0.0, 0.0)
        return (s["floor"], st, s["anchor"])
    segs.sort(key=skey)
    smap = {s["id"]: n for n, s in enumerate(segs)}
    zones = [z for z in g["junction_zones"] if not z.get("_dead")]
    for z in zones:
        z["anchor"] = first(lab["junction_zone"], z["id"])
    zones.sort(key=lambda z: z["anchor"])
    zmap = {z["id"]: n for n, z in enumerate(zones)}
    isl = [i for i in g["islands"] if not i.get("_dead")]
    for i in isl:
        i["anchor"] = first(lab["island"], i["id"])
        i["n_elems"] = int((lab["island"] == i["id"]).sum())
    isl.sort(key=lambda i: i["anchor"])
    imap = {i["id"]: n for n, i in enumerate(isl)}
    nets = [n for n in g["networks"] if not n.get("_dead")]
    nets.sort(key=lambda n: n["floor"])
    nmap = {n["id"]: k for k, n in enumerate(nets)}
    js = list(g["junctions"])
    js.sort(key=lambda j: (j["plan"][0], j["plan"][1], j["type"]))
    jmap = {j["id"]: n for n, j in enumerate(js)}

    def remap_arr(a, m):
        lut = {int(k): v for k, v in m.items()}
        out = np.full(a.shape, -1, np.int32)
        for k, v in lut.items():
            out[a == k] = v
        return out
    lab["segment"] = remap_arr(lab["segment"], smap)
    lab["junction_zone"] = remap_arr(lab["junction_zone"], zmap)
    lab["island"] = remap_arr(lab["island"], imap)
    for n, s in enumerate(segs):
        s["id"] = n
        s["network"] = nmap.get(s["network"], -1)
        s["junctions"] = sorted(jmap[j] for j in s["junctions"] if j in jmap)
        s["islands"] = sorted(imap[i] for i in s["islands"] if i in imap)
        s["n_elems"] = int((lab["segment"] == n).sum())
        s.pop("_dead", None)
    for n, z in enumerate(zones):
        z["id"] = n
        z["adj_segments"] = sorted({smap[a] for a in z["adj_segments"] if a in smap})
        z["junctions"] = sorted(jmap[j] for j in z["junctions"] if j in jmap)
        z["network"] = nmap.get(z["network"], -1)
        z["n_elems"] = int((lab["junction_zone"] == n).sum())
    for n, i in enumerate(isl):
        i["id"] = n
        i["owner_segment"] = smap.get(i["owner_segment"], -1)
    for k, net in enumerate(nets):
        net["id"] = k
        net["segments"] = sorted(s["id"] for s in segs if s["network"] == k)
        net["junction_zones"] = sorted(z["id"] for z in zones if z["network"] == k)
    for n, j in enumerate(js):
        j["id"] = n
        j["segments"] = sorted(smap[s] for s in j["segments"] if s in smap)
        j["zone"] = zmap.get(j["zone"], -1)
    for f in g["floors"]:
        f["island"] = imap.get(f["island"], -1) if f["island"] >= 0 else -1
        f["network"] = nmap.get(f["network"], -1) if f["network"] >= 0 else -1
    for h in g["holes"]:
        h["owner_island"] = imap.get(h["owner_island"], -1) if h["owner_island"] >= 0 else -1
    g["segments"], g["junction_zones"], g["islands"], g["networks"], g["junctions"] = segs, zones, isl, nets, js


# ---------------------------------------------------------------------------------------------------- suggestions
def sym_pairs(graph, tol_mm: float) -> list[list[int]]:
    """BG-D-21: same tier + type segment pairs whose skeletons mirror about the part centre line (plan x = 0 or y = 0
    of the graph frame through the node bbox centre) within Hausdorff <= 5·tol."""
    from scipy.spatial import cKDTree
    out = []
    c0 = np.asarray(graph["frame"].get("bbox_center", [0.0, 0.0]), float)
    segs = [s for s in graph["segments"] if s["skeleton"] and s["type"] not in ("base",)]
    for i, a in enumerate(segs):
        pa = np.asarray(a["skeleton"], float)
        for b in segs[i + 1:]:
            if a["tier"] != b["tier"] or a["type"] != b["type"]:
                continue
            pb = np.asarray(b["skeleton"], float)
            for ax in (0, 1):
                m = pb.copy()
                m[:, ax] = 2.0 * c0[ax] - m[:, ax]
                d1 = cKDTree(m).query(pa)[0].max()
                d2 = cKDTree(pa).query(m)[0].max()
                if max(d1, d2) <= 5.0 * tol_mm:
                    out.append([a["id"], b["id"]])
                    break
    return out
