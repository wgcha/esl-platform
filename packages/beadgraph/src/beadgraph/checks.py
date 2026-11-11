"""Design checks on a morphed node array (BG-D-32..34): outside-zero, achieved depth / width, island residual, and the
inverted-element count (normal flip > flip_deg or a non-positive quad corner — same rule as esl quality)."""
from __future__ import annotations

import numpy as np

from . import _util as U
from .morph import _skeleton_dist


def changed(basis, values) -> list:
    out = []
    for v in basis:
        if v["name"] in values and float(values[v["name"]]) != float(v["nominal"]):
            out.append(v)
    return out


class _Conn:
    """element -> node incidence + plan coordinates (connectivity only — no zone logic)."""

    def __init__(self, graph, nodes, elems):
        from scipy import sparse
        X = np.asarray(nodes, np.float64)
        C = np.asarray(elems, np.int64)
        if C.ndim != 2 or C.shape[1] not in (3, 4):
            raise ValueError("elems must be (m, 3|4)")
        if C.shape[1] == 3:
            C = np.c_[C, -np.ones(C.shape[0], np.int64)]
        self.n, self.m, self.C = X.shape[0], C.shape[0], C
        ok = C.ravel() >= 0
        rows = np.repeat(np.arange(self.m), 4)[ok]
        self.inc = sparse.csr_matrix((np.ones(int(ok.sum())), (rows, C.ravel()[ok])), shape=(self.m, self.n))
        fr = graph["frame"]
        P = np.c_[X @ np.asarray(fr["e1"], float), X @ np.asarray(fr["e2"], float)]
        cnt = np.maximum(np.asarray(self.inc.sum(axis=1)).ravel(), 1.0)
        self.Pc = np.asarray(self.inc @ P) / cnt[:, None]

    def nmask(self, emask) -> np.ndarray:
        return np.asarray(self.inc.T @ np.asarray(emask, bool).astype(np.float64)).ravel() > 0

    def emask_of_nodes(self, nmask) -> np.ndarray:
        return np.asarray(self.inc @ np.asarray(nmask, bool).astype(np.float64)).ravel() > 0


def allowed_elements(graph, labels, nodes, elems, segs, zones=(), kind: str = "D", conn=None) -> np.ndarray:
    """Verifier fix (v0.17.0): the allowed element set A_v of one variable computed **from the graph labels only** —
    independent of the basis zone (``zones.bead_zones``), so a wrong basis zone is caught by BG-D-32/34.

    D: the segments' own elements (floor + walls, segment label ∈ S), their junction zones (``zones`` + every zone
    between >= 2 of the segments — BG-D-19), exclusive child subtrees (children listed only by segments of S — floors,
    walls, islands), the shared children's wall part on the S side (wall whose nearest F-floor element is an S element —
    BG-D-23 Z_SC), owned islands and straddling islands touching an S floor element (D6).
    W: S elements + junction zones + owned / straddling islands + the parent floor and its non-straddling islands (blend
    band R_w, BG-D-30) — children stay (not allowed)."""
    lab = {k: np.asarray(v, np.int64) for k, v in labels.items()}
    cls, seg, jz, tr, isl, fl = (lab[k] for k in ("cls", "segment", "junction_zone", "transition", "island", "floor"))
    K = conn or _Conn(graph, nodes, elems)
    S = sorted({int(s) for s in segs})
    sg = {s["id"]: s for s in graph["segments"]}
    F = sg[S[0]]["floor"]
    floors = {f["id"]: f for f in graph["floors"]}
    p = floors[F]["parent"]
    zin = {int(z) for z in zones or ()}
    zin |= {z["id"] for z in graph["junction_zones"] if len(set(z["adj_segments"]) & set(S)) >= 2}
    inS = np.isin(seg, S) | (np.isin(jz, sorted(zin)) & (jz >= 0))
    floor_el, wall_el = cls == 0, cls == 1
    A = inS.copy()
    kids = {}
    for f in graph["floors"]:
        if f["parent"] is not None and f["parent"] >= 0 and f["kind"] not in ("base", "base_fragment"):
            kids.setdefault(f["parent"], []).append(f["id"])

    def subtree(c):
        out, st = {c}, list(kids.get(c, []))
        while st:
            q = st.pop()
            out.add(q)
            st += kids.get(q, [])
        return out
    children = [c for c in kids.get(F, []) if floors[c]["kind"] != "island"]
    listed = {c: {s["id"] for s in graph["segments"] if c in (s.get("children") or [])} for c in children}
    F_S = floor_el & (fl == F) & inS
    Ffloor = floor_el & (fl == F)
    excl: set = set()
    for c in children:
        tids = [t["id"] for t in graph["transitions"] if t["type"] == "parent-child" and t["child"] == c]
        cw = wall_el & np.isin(tr, tids)
        if kind != "D" or not cw.any():
            continue
        if listed[c] and listed[c] <= set(S):          # exclusive child: whole subtree rigid with the bead
            sub = subtree(c)
            excl |= sub
            tsub = [t["id"] for t in graph["transitions"] if t["child"] in sub or
                    (t["upper"] in sub and t["lower"] in sub)]
            A |= (floor_el & np.isin(fl, sorted(sub))) | (wall_el & np.isin(tr, tsub)) | cw
            A |= np.isin(isl, [i["id"] for i in graph["islands"] if i["parent"] in sub]) & (isl >= 0)
        elif F_S.any():                                 # shared child: its wall part on the S side only
            from scipy.spatial import cKDTree
            fidx, widx = np.flatnonzero(Ffloor), np.flatnonzero(cw)
            _d, j = cKDTree(K.Pc[fidx]).query(K.Pc[widx])
            A[widx[F_S[fidx[j]]]] = True
    if excl:                                           # sibling steps between exclusive children move with them
        A |= wall_el & np.isin(tr, [t["id"] for t in graph["transitions"] if t["upper"] in excl and t["lower"] in excl])
    touchS = K.nmask(floor_el & inS)
    for i in graph["islands"]:
        e = isl == i["id"]
        if not e.any():
            continue
        if i["owner_segment"] in S:
            A |= e
        elif i["straddle"] and touchS[K.C[e][K.C[e] >= 0]].any():
            A |= e
    if kind == "W":
        if p is not None and p >= 0:
            A |= floor_el & (fl == p)
            A |= np.isin(isl, [i["id"] for i in graph["islands"] if i["parent"] == p and not i["straddle"]]) & (isl >= 0)
    return A


def strict_allowed_nodes(graph, labels, nodes, elems, basis, conn=None) -> dict:
    """{var name: bool node mask} — a node is allowed only when **every** element it belongs to is in A_v (a node shared
    with an outside element counts as outside). Free nodes (no element) are allowed."""
    K = conn or _Conn(graph, nodes, elems)
    out = {}
    for v in basis:
        A = allowed_elements(graph, labels, nodes, elems, v["segs"], v.get("zones") or (), v["kind"], conn=K)
        out[v["name"]] = ~K.nmask(~A)
    return out


def outside_moved(x0, x, basis, values, tol: float, graph=None, labels=None, elems=None) -> dict:
    """max displacement of nodes outside the union of the changed variables' allowed sets. With graph + labels + elems
    the allowed set is the label-based one (``strict_allowed_nodes`` — independent of the basis zone); without, the
    basis ``zone`` (legacy)."""
    x0 = np.asarray(x0, np.float64)
    ch = changed(basis, values)
    allowed = np.zeros(x0.shape[0], bool)
    if graph is not None and labels is not None and elems is not None and ch:
        for m in strict_allowed_nodes(graph, labels, x0, elems, ch).values():
            allowed |= m
    else:
        for v in ch:
            allowed[np.asarray(v["zone"], np.int64)] = True
    d = np.linalg.norm(np.asarray(x, np.float64) - x0, axis=1)
    d[allowed] = 0.0
    n = int((d > tol).sum())
    return {"n": n, "max_mm": float(d.max()) if d.size else 0.0, "vars": sorted(v["name"] for v in ch),
            "failed": n > 0}


def basis_leak(basis, graph=None, labels=None, nodes=None, elems=None) -> list[dict]:
    """BG-D-32: supp(B_v) ⊆ allowed(v) for every variable -> list of {var, n, max_mm} violations. With graph + labels +
    nodes + elems, allowed(v) = the label-based strict node set (independent of the basis zone); else the basis zone."""
    out = []
    strict = None
    if graph is not None and labels is not None and nodes is not None and elems is not None and basis:
        strict = strict_allowed_nodes(graph, labels, nodes, elems, basis)
    for v in basis:
        idx = np.asarray(v["idx"], np.int64)
        if strict is not None:
            bad = ~strict[v["name"]][idx]
        else:
            bad = ~np.isin(idx, np.asarray(v["zone"], np.int64))
        if bad.any():
            out.append({"code": "BG_BASIS_LEAK", "var": v["name"], "n": int(bad.sum()),
                        "max_mm": float(np.linalg.norm(np.asarray(v["vec"])[bad], axis=1).max())})
    return out


def achieved(graph, labels, nodes, x, basis, values, elems=None) -> dict:
    """D: max |Δh − s·Δv| over the achieved nodes; W: |ΔW_measured − Δv| (entry nodes at full ramp)."""
    x0 = np.asarray(nodes, np.float64)
    x = np.asarray(x, np.float64)
    n0 = np.asarray(graph["frame"]["n0"], float)
    out = {}
    M = None
    for v in changed(basis, values):
        dv = float(values[v["name"]]) - float(v["nominal"])
        idx = np.asarray(v["info"].get("achieved_idx", []), np.int64)
        if idx.size == 0:
            out[v["name"]] = None
            continue
        if v["kind"] == "D":
            dh = (x[idx] - x0[idx]) @ n0
            out[v["name"]] = float(np.abs(dh - v["info"]["sign"] * dv).max())
        else:
            if M is None:
                M = _PlanOnly(graph, x0)
            d0, _n, _i = _skeleton_dist(M, v["segs"], M.plan(x0[idx]))
            d1, _n, _i = _skeleton_dist(M, v["segs"], M.plan(x[idx]))
            out[v["name"]] = float(abs(2.0 * (np.median(d1) - np.median(d0)) - dv))
    return out


class _PlanOnly:
    def __init__(self, graph, X):
        fr = graph["frame"]
        self.e1, self.e2 = np.asarray(fr["e1"], float), np.asarray(fr["e2"], float)
        self.origin = np.asarray(fr.get("origin", [0.0, 0.0]), float)
        self.segs = {s["id"]: s for s in graph["segments"]}

    def plan(self, X):
        return np.c_[X @ self.e1, X @ self.e2] - self.origin


def island_residual(labels, nodes, x, basis, values, elems) -> float:
    """max |u − mean u| over the nodes of each island moved by a changed variable (rigid translation)."""
    if elems is None:
        return 0.0
    x0 = np.asarray(nodes, np.float64)
    u = np.asarray(x, np.float64) - x0
    C = np.asarray(elems, np.int64)
    isl = np.asarray(labels["island"], np.int64)
    ids = set()
    held = set()
    for v in changed(basis, values):
        ids |= set(v["info"].get("islands", [])) - set(v["info"].get("straddle", []))
        ids |= set(v["info"].get("band_islands", []))
        held |= {w["island"] for w in v["info"]["warnings"] if w["code"] == "BG_ISLAND_HELD"}
    worst = 0.0
    for i in sorted(ids - held):
        nd = np.unique(C[isl == i])
        nd = nd[nd >= 0]
        if nd.size == 0:
            continue
        uu = u[nd]
        worst = max(worst, float(np.linalg.norm(uu - uu.mean(axis=0), axis=1).max()))
    return worst


def _quad_jacobian(X, Cq):
    """scaled bilinear Jacobian on the element's own projected plane (2x2 Gauss points) — min / max (same rule as esl
    ``mesh_quality.element_metrics``; negative = inverted)."""
    P = X[Cq]
    p0, p1, p2, p3 = (P[:, i] for i in range(4))
    n = np.cross(p2 - p0, p3 - p1)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
    e1 = (p1 - p0) - np.einsum("ij,ij->i", p1 - p0, n)[:, None] * n
    e1 /= np.maximum(np.linalg.norm(e1, axis=1, keepdims=True), 1e-300)
    e2 = np.cross(n, e1)
    R = P - P.mean(axis=1, keepdims=True)
    xy = np.stack([np.einsum("mkj,mj->mk", R, e1), np.einsum("mkj,mj->mk", R, e2)], axis=2)
    g = 1.0 / np.sqrt(3.0)
    dets = []
    for xi, eta in ((-g, -g), (g, -g), (g, g), (-g, g)):
        dxi = 0.25 * np.array([-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)])
        deta = 0.25 * np.array([-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)])
        a = np.einsum("k,mkj->mj", dxi, xy)
        b = np.einsum("k,mkj->mj", deta, xy)
        dets.append(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
    D = np.stack(dets, axis=1)
    return D.min(axis=1) / np.maximum(np.abs(D).max(axis=1), 1e-300)


def inverted_count(nodes, x, elems, flip_deg: float = 60.0) -> int:
    """elements with a moved node that are inverted: quad Jacobian <= 0 or element normal rotated > flip_deg."""
    X0 = np.asarray(nodes, np.float64)
    X1 = np.asarray(x, np.float64)
    C = np.asarray(elems, np.int64)
    q = C[:, 3] >= 0
    moved = np.linalg.norm(X1 - X0, axis=1) > 1e-9
    am = moved[C[:, 0]] | moved[C[:, 1]] | moved[C[:, 2]] | (q & moved[np.where(q, C[:, 3], 0)])
    C, q = C[am], q[am]
    if C.shape[0] == 0:
        return 0

    def normals(X):
        a, b, c = X[C[:, 0]], X[C[:, 1]], X[C[:, 2]]
        n = np.cross(b - a, c - a)
        d = X[np.where(q, C[:, 3], C[:, 2])]
        n[q] = np.cross(c[q] - a[q], d[q] - b[q])
        return n / np.maximum(np.linalg.norm(n, axis=1), 1e-300)[:, None]
    rot = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", normals(X0), normals(X1)), -1, 1)))
    inv = rot > flip_deg
    if q.any():
        inv[q] |= _quad_jacobian(X1, C[q]) <= 0.0
    return int(inv.sum())


def check(graph, labels, nodes, x, basis, values, cfg=None, elems=None) -> dict:
    c = U.merged_cfg(cfg)
    tol = float(c["morph"]["outside_tol_mm"])
    out = outside_moved(nodes, x, basis, values, tol, graph=graph, labels=labels, elems=elems)
    return {"outside": {k: out[k] for k in ("n", "max_mm", "vars")}, "outside_failed": out["failed"],
            "achieved": achieved(graph, labels, nodes, x, basis, values),
            "island_residual_mm": island_residual(labels, nodes, x, basis, values, elems),
            "inverted": inverted_count(nodes, x, elems) if elems is not None else None}
