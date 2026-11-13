"""Morph zones of one bead (contract §4.1): Z_F, Z_W, Z_C, Z_SC, Z_I, J, E, A_v — element / node masks from the graph +
labels + connectivity. numpy / scipy only."""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.spatial import cKDTree

from .classify import CLS


class Mesh:
    """connectivity helpers shared by all variables of one ``basis`` call."""

    def __init__(self, graph, labels, nodes, elems):
        self.X = np.asarray(nodes, np.float64)
        C = np.asarray(elems, np.int64)
        if C.shape[1] == 3:
            C = np.c_[C, -np.ones(C.shape[0], np.int64)]
        C = C.copy()
        tri = (C[:, 3] < 0) | (C[:, 3] == C[:, 2]) | (C[:, 3] == C[:, 0])
        C[tri, 3] = -1
        self.C, self.tri = C, tri
        self.n, self.m = self.X.shape[0], C.shape[0]
        fr = graph["frame"]
        self.n0 = np.asarray(fr["n0"], float)
        self.e1 = np.asarray(fr["e1"], float)
        self.e2 = np.asarray(fr["e2"], float)
        self.origin = np.asarray(fr.get("origin", [0.0, 0.0]), float)
        self.h_mm = float(fr["h_mm"])
        self.P = np.c_[self.X @ self.e1, self.X @ self.e2] - self.origin
        self.hn = self.X @ self.n0
        rows = np.repeat(np.arange(self.m), 4)
        cols = C.ravel()
        ok = cols >= 0
        self.inc = sparse.csr_matrix((np.ones(ok.sum()), (rows[ok], cols[ok])), shape=(self.m, self.n))
        self.incT = self.inc.T.tocsr()
        cnt = np.where(tri, 3.0, 4.0)
        self.Pc = np.asarray(self.inc @ self.P) / cnt[:, None]
        self.hc = np.asarray(self.inc @ self.hn).ravel() / cnt
        a = C
        nxt = C[:, [1, 2, 3, 0]].copy()
        nxt[tri, 2] = C[tri, 0]
        valid = np.ones((self.m, 4), bool)
        valid[tri, 3] = False
        self.ea, self.eb = a[valid], nxt[valid]
        self.e_el = np.repeat(np.arange(self.m), 4).reshape(self.m, 4)[valid]
        self.lab = {k: np.asarray(v, np.int64) for k, v in labels.items()}
        self.graph = graph
        self.floors = {f["id"]: f for f in graph["floors"]}
        self.segs = {s["id"]: s for s in graph["segments"]}
        self.zones = {z["id"]: z for z in graph["junction_zones"]}
        self.trans = {t["id"]: t for t in graph["transitions"]}
        self.islands = {i["id"]: i for i in graph["islands"]}
        self.children = {}
        for f in graph["floors"]:
            if f["parent"] is not None and f["parent"] >= 0 and f["kind"] not in ("base", "base_fragment"):
                self.children.setdefault(f["parent"], []).append(f["id"])
        self._lap = None

    def nmask(self, emask) -> np.ndarray:
        e = np.asarray(emask, bool).astype(np.float64)
        return np.asarray(self.incT @ e).ravel() > 0

    def emask_of_nodes(self, nmask) -> np.ndarray:
        return np.asarray(self.inc @ np.asarray(nmask, float)).ravel() > 0

    def descendants(self, f):
        out, st = [], list(self.children.get(f, []))
        while st:
            q = st.pop()
            out.append(q)
            st += self.children.get(q, [])
        return out

    def laplacian(self, emask):
        """edge-weighted (1/length) graph Laplacian over the edges of the given elements (n x n, csr)."""
        sel = np.asarray(emask, bool)[self.e_el]
        a, b = self.ea[sel], self.eb[sel]
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        k = np.unique(lo * self.n + hi)
        a, b = k // self.n, k % self.n
        w = 1.0 / np.maximum(np.linalg.norm(self.X[a] - self.X[b], axis=1), 1e-9)
        W = sparse.coo_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(self.n, self.n)).tocsr()
        return (sparse.diags(np.asarray(W.sum(axis=1)).ravel()) - W).tocsr()


def movable_nodes(conn, allowed_el) -> np.ndarray:
    """BG-D-47: the one node rule of a variable — a node may move only when **every** element it belongs to is in the
    allowed element set A_v (a node shared with an element outside A_v stays at 0). ``conn`` = any object with
    ``nmask(emask)`` (``Mesh`` here, ``checks._Conn`` in the checks). The basis (``morph``: straddling-island hold +
    final zero) and the outside checks (``checks.strict_allowed_nodes`` — BG-D-32·34) both use this function; the
    element sets themselves stay computed independently (BG-X-9). Free nodes (no element) are movable."""
    return ~np.asarray(conn.nmask(~np.asarray(allowed_el, bool)), bool)


def bead_zones(M: Mesh, segs: list[int], zones_extra: list[int] = (), kind: str = "D") -> dict:
    """element masks of one bead (variable) — §4.1."""
    lab = M.lab
    cls, seg, jz, tr, isl = lab["cls"], lab["segment"], lab["junction_zone"], lab["transition"], lab["island"]
    S = sorted(set(int(s) for s in segs))
    floors = sorted({M.segs[s]["floor"] for s in S})
    if len(floors) != 1:
        raise ValueError(f"bead segments on several floors {floors}")
    F = floors[0]
    p = M.floors[F]["parent"]
    zin = set(int(z) for z in zones_extra)
    for z in M.graph["junction_zones"]:            # BG-D-19: zones between >= 2 segments of the bead move with it
        if len(set(z["adj_segments"]) & set(S)) >= 2:
            zin.add(z["id"])
    zin = sorted(zin)
    inS = np.isin(seg, S) | (np.isin(jz, zin) & (jz >= 0))
    ZF = inS & (cls == CLS["floor"])
    ZW = inS & (cls == CLS["wall"])
    floor_el = cls == CLS["floor"]
    fl = lab["floor"]
    parent_floor = floor_el & (fl == p) if p is not None and p >= 0 else np.zeros(M.m, bool)
    nF = M.nmask(ZF)
    # children of F: exclusive (Z_C) or shared (Z_SC)
    ZC = np.zeros(M.m, bool)
    ZSC = np.zeros(M.m, bool)
    shared, exclusive = [], []
    Ffloor = floor_el & (fl == F)
    for c in M.children.get(F, []):
        if M.floors[c]["kind"] == "island":
            continue
        tids = [t["id"] for t in M.graph["transitions"] if t["type"] == "parent-child" and t["child"] == c]
        cw = np.isin(tr, tids) & (cls == CLS["wall"])
        if not cw.any():
            continue
        cn = M.nmask(cw)
        touch = Ffloor & M.emask_of_nodes(cn)
        if not touch.any():
            continue
        if (touch & ~ZF).any():
            if (touch & ZF).any():
                shared.append(c)
                # walls of the shared child whose nearest F-floor element is in Z_F (the Z_F side part)
                fidx = np.flatnonzero(Ffloor)
                widx = np.flatnonzero(cw)
                _d, j = cKDTree(M.Pc[fidx]).query(M.Pc[widx])
                ZSC[widx[ZF[fidx[j]]]] = True
            continue
        exclusive.append(c)
        sub = [c] + M.descendants(c)
        subf = floor_el & np.isin(fl, sub)
        tsub = [t["id"] for t in M.graph["transitions"] if t["type"] in ("parent-child", "self", "junction", "other")
                and (t["child"] in sub or (t["upper"] in sub and t["lower"] in sub))]
        ZC |= subf | (np.isin(tr, tsub) & (cls == CLS["wall"])) | cw
        isl_sub = [i["id"] for i in M.graph["islands"] if i["parent"] in sub]
        ZC |= np.isin(isl, isl_sub) & (isl >= 0)
    if exclusive:                                   # sibling steps between two exclusive children move with them
        allsub = set()
        for c in exclusive:
            allsub |= {c, *M.descendants(c)}
        tj = [t["id"] for t in M.graph["transitions"] if t["upper"] in allsub and t["lower"] in allsub]
        ZC |= np.isin(tr, tj) & (cls == CLS["wall"])
    ZC &= ~(ZF | ZW)
    # islands: owned by S, or straddling the S floor (D6)
    ZI = np.zeros(M.m, bool)
    straddle = []
    owned = [i["id"] for i in M.graph["islands"] if i["owner_segment"] in S]
    touch_nodes = nF
    for i in M.graph["islands"]:
        e = isl == i["id"]
        if not e.any() or (ZC & e).any():
            continue
        if i["id"] in owned:
            ZI |= e
            continue
        if i["straddle"] and (touch_nodes[M.C[e][M.C[e] >= 0]]).any():
            ZI |= e
            straddle.append(i["id"])
    ZI &= ~ZC
    isl_ids = sorted(set(np.unique(isl[ZI & (isl >= 0)]).tolist()))
    allowed_el = ZF | ZW | ZI | (ZC if kind == "D" else False) | (ZSC if kind == "D" else False)
    nW = M.nmask(ZW)
    nP = M.nmask(parent_floor)
    E = nW & nP
    # J: Z_F u Z_W nodes shared with elements outside the bead (other segments / zones / shared-child floors / foreign
    # islands); the parent floor (entry, E) and the bead's own children / islands are not "outside".
    own = ZF | ZW | ZC | ZSC | ZI | parent_floor
    if kind == "W":
        own = own & ~ZC
    outside = ~own
    if kind == "W":
        outside &= ~ZC                             # children stay: their entry nodes are Dirichlet 0, not a ramp source
    J = (nF | nW) & M.nmask(outside)
    if kind == "D" and shared:
        # Verifier fix (v0.17.0): shared-child wall nodes (Z_SC) that also belong to an outside element — the rest of
        # the shared child's wall (owned by a neighbouring segment / junction zone) or a foreign floor — are Dirichlet 0
        # (J) so the ramp zeros them. The shared child's own subtree (its floor, which stays put) is not a trigger: its
        # edge nodes are already 0 by the height rule (t = 1), and treating it as J would ramp the whole bead floor.
        ssub = set()
        for c in shared:
            ssub |= {c, *M.descendants(c)}
        sub_el = (floor_el & np.isin(fl, sorted(ssub))) | (
            np.isin(isl, [i["id"] for i in M.graph["islands"] if i["parent"] in ssub]) & (isl >= 0))
        tin = [t["id"] for t in M.graph["transitions"] if t["upper"] in ssub and t["lower"] in ssub]
        sub_el |= np.isin(tr, tin) & (cls == CLS["wall"])
        J |= M.nmask(ZSC) & M.nmask(outside & ~ZSC & ~sub_el)
    return {"S": S, "floor": F, "parent": p, "zones_in": zin, "ZF": ZF, "ZW": ZW, "ZC": ZC, "ZSC": ZSC, "ZI": ZI,
            "parent_floor": parent_floor, "shared": shared, "exclusive": exclusive, "straddle": straddle,
            "islands": isl_ids, "E": E, "J": J, "nF": nF, "nW": nW, "allowed_el": allowed_el}
