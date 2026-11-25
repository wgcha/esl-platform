"""Segment morph: per-variable linear basis B_v (contract §4, BG-D-23..34), x = x0 + Σ (v − v_nom)·B_v.

Values that would depend on the variable value (ramp length, corner-guard factors) are fixed once at the default range
ends and frozen in the basis (BG-D-24·26), so the morph stays linear.

D (relative depth, D1/D3): walls + floor edge = 3D homothety about the nearest entry node (45° flank kept, entry fixed,
the floor narrows by ΔD per side); floor interior = s·ΔD·n0 with an in-plane harmonic extension; exclusive children
(Z_C) follow rigidly; shared children stay and their walls on the bead side absorb the height change (BG_SHARED_CHILD);
owned / straddling islands rigid (straddling: contact band to a foreign floor or wall smoothed to 0 — D6, BG-D-47).
W (entry width): walls + floor edge + entry translate ΔW/2 along the outward skeleton normal; floor interior harmonic
(children stay); parent-floor blend band R_w.
All displacements × junction ramp φ = smoothstep(d_J / L), L = max(ramp_k·ΔD_ext, ramp_k·h) (D4) × fixed-node hold ψ
(SR-D-9 ring + Wendland blend, D6). Outside the allowed zone A_v the basis is exactly 0 (BG-D-32·34), with the checks' node rule ``zones.movable_nodes``
(BG-D-47).
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu
from scipy.spatial import cKDTree

from . import _util as U
from .absorb import interior_mask, polyline_dist
from .classify import CLS
from .defaults import DF_ENTRY, MORPH_EXTRA
from .zones import Mesh, bead_zones, movable_nodes

# DF·W1 parent-band mix (part of the DF_RULES / W1_RULES 1 definition, esl contract esl_bead_depth_mode §1.2.1·§1.6.3 —
# DM-C1-2): nearest sources mixed, weight 1/(d² + (BAND_MIX_EPS_H·h)²)
BAND_MIX_K = 8
BAND_MIX_EPS_H = 0.1
# DF entry smoothing / neighbour-gap limit (DM-30·31): gaussian support cut at ENTRY_SMOOTH_CUT·ρ
ENTRY_SMOOTH_CUT = 3.0


def _cfg(cfg):
    c = U.merged_cfg(cfg)
    for k, v in MORPH_EXTRA.items():
        c[k] = U.merge(v, (cfg or {}).get(k))
    return c


def _harmonic(L, free: np.ndarray, U0: np.ndarray, cols=(0, 1, 2)) -> np.ndarray:
    """solve L u = 0 on ``free`` nodes with Dirichlet values U0 elsewhere (rows of L restricted to the support)."""
    f = np.flatnonzero(free)
    out = U0.copy()
    if f.size == 0:
        return out
    Lf = L[f]
    Lff = Lf[:, f].tocsc()
    rhs = -(Lf @ U0) + Lff @ U0[f]
    deg = np.asarray(abs(Lff).sum(axis=1)).ravel()
    iso = deg == 0
    Lff = Lff + sparse.diags(np.where(iso, 1.0, 0.0) + 1e-12)
    lu = splu(Lff.tocsc())
    for c in cols:
        out[f, c] = lu.solve(np.ascontiguousarray(rhs[:, c]))
    out[f[iso]] = 0.0
    return out


def _hold(M: Mesh, allowed_n: np.ndarray, fixed_mask: np.ndarray, cfg: dict):
    psi = np.ones(M.n)
    P = np.flatnonzero(allowed_n & fixed_mask)
    if P.size == 0:
        return psi, 0
    rho, bw = float(cfg["hold"]["ring_mm"]), float(cfg["hold"]["blend_mm"])
    idx = np.flatnonzero(allowed_n)
    d, _ = cKDTree(M.X[P]).query(M.X[idx])
    psi[idx] = np.where(d <= rho, 0.0, np.where(d >= rho + bw, 1.0, 1.0 - U.wendland((d - rho) / bw)))
    return psi, int(P.size)


def _ramp(M: Mesh, J: np.ndarray, nodes: np.ndarray, L: float):
    phi = np.ones(M.n)
    if J.any() and nodes.size:
        d, _ = cKDTree(M.P[J]).query(M.P[nodes])
        phi[nodes] = U.smoothstep(d / L)
    phi[J] = 0.0
    return phi


def _skeleton_dist(M: Mesh, S: list[int], Q: np.ndarray):
    best, nout, inner, _side, _sid = _skel_full(M, S, Q)
    return best, nout, inner


def _skel_full(M: Mesh, S: list[int], Q: np.ndarray):
    """nearest skeleton over the segments S -> (distance, outward unit, interior, side ±1, segment id (−1 none))."""
    best = np.full(len(Q), np.inf)
    nout = np.zeros((len(Q), 2))
    inner = np.zeros(len(Q), bool)
    side = np.zeros(len(Q))
    sid = -np.ones(len(Q), np.int64)
    for s in S:
        sk = M.segs[s].get("skeleton")
        if not sk:
            continue
        pts = np.asarray(sk, float)
        d, sd, cp, n = polyline_dist(Q, pts)
        im = interior_mask(cp, pts)
        m = d < best
        best[m], nout[m], inner[m], side[m], sid[m] = d[m], n[m], im[m], sd[m], s
    return best, nout, inner, side, sid


def _smooth_dirs(M: Mesh, el_mask, node_mask, idx, nref, iters: int):
    """continuous outward direction field on the moving W nodes: the skeleton direction (piecewise, jumps at polyline
    kinks and between the bead's skeletons) relaxed by Jacobi averaging over the edges among those nodes; straight
    stretches keep the exact perpendicular (W achieved exactly there)."""
    if idx.size == 0 or iters <= 0:
        return nref
    sel = np.asarray(el_mask, bool)[M.e_el]
    a, b = M.ea[sel], M.eb[sel]
    keep = node_mask[a] & node_mask[b]
    a, b = a[keep], b[keep]
    pos = -np.ones(M.n, np.int64)
    pos[idx] = np.arange(idx.size)
    ia, ib = pos[a], pos[b]
    A = sparse.coo_matrix((np.ones(2 * ia.size), (np.r_[ia, ib], np.r_[ib, ia])), shape=(idx.size, idx.size)).tocsr()
    A.data[:] = 1.0
    deg = np.asarray(A.sum(axis=1)).ravel()
    v = nref.copy()
    for _ in range(iters):
        w = (A @ v + v) / (deg + 1.0)[:, None]
        nn = np.linalg.norm(w, axis=1)
        v = np.where(nn[:, None] > 1e-12, w / np.maximum(nn, 1e-12)[:, None], v)
    return v


def _plan3(M: Mesh, v2: np.ndarray) -> np.ndarray:
    return np.outer(v2[:, 0], M.e1) + np.outer(v2[:, 1], M.e2)


def _corner_guard(M: Mesh, el: np.ndarray, U: np.ndarray, moved: np.ndarray, ext: float, cg: dict, flip_deg: float):
    """BG-D-26: at ±ext, elements of the bead (floor + walls) whose plan area ratio < area_ratio_min (floor corners) or
    that invert (esl rule: quad Jacobian <= 0 or normal turned > flip_deg — wall slivers at mitres) get the in-plane part
    of their moving nodes multiplied by ``shrink``, up to ``iters`` times -> per-node factor c (frozen in the basis)."""
    from .checks import _quad_jacobian
    c = np.ones(M.n)
    idx = np.flatnonzero(el)
    if idx.size == 0 or ext <= 0:
        return c
    C = M.C[idx]
    q = C[:, 3] >= 0
    isfloor = M.lab["cls"][idx] == CLS["floor"]
    T = np.r_[C[:, :3], C[q][:, [0, 2, 3]]]
    Towner = np.r_[np.arange(idx.size), np.flatnonzero(q)]
    P0 = M.P

    def parea(P):
        a, b, d = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        return 0.5 * ((b[:, 0] - a[:, 0]) * (d[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (d[:, 0] - a[:, 0]))

    def normals(X):
        a, b, d = X[C[:, 0]], X[C[:, 1]], X[C[:, 2]]
        n = np.cross(b - a, d - a)
        e = X[np.where(q, C[:, 3], C[:, 2])]
        n[q] = np.cross(d[q] - a[q], e[q] - b[q])
        return n / np.maximum(np.linalg.norm(n, axis=1), 1e-300)[:, None]
    a0 = parea(P0)
    ok0 = np.abs(a0) > 1e-9
    n0 = normals(M.X)
    j0 = np.ones(idx.size)
    if q.any():
        j0[q] = _quad_jacobian(M.X, C[q])
    un = (U @ M.n0)[:, None] * M.n0[None, :]
    upl = U - un
    shrink, ratio, iters = float(cg["shrink"]), float(cg["area_ratio_min"]), int(cg["iters"])
    for _ in range(iters):
        bad_el = np.zeros(idx.size, bool)
        for sgn in (1.0, -1.0):
            Ud = un + upl * c[:, None]
            X1 = M.X + sgn * ext * Ud
            P1 = np.c_[X1 @ M.e1, X1 @ M.e2] - M.origin
            r = parea(P1) / np.where(ok0, a0, 1.0)
            badt = ok0 & (r < ratio)
            bt = np.zeros(idx.size, bool)
            np.logical_or.at(bt, Towner[badt], True)
            bad_el |= bt & isfloor
            rot = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", n0, normals(X1)), -1, 1)))
            inv = rot > flip_deg
            if q.any():
                jq = _quad_jacobian(X1, C[q])
                inv[q] |= (jq <= 0.0) & (j0[q] > 0.0)
            bad_el |= inv
        if not bad_el.any():
            break
        nd = np.unique(C[bad_el][C[bad_el] >= 0])
        nd = nd[moved[nd]]
        if nd.size == 0:
            break
        c[nd] *= shrink
    return c


def _var_ext(rng, nominal):
    lo, hi = (float(v) for v in rng)
    return max(abs(hi - nominal), abs(lo - nominal))


def basis(graph, labels, nodes, beads, ranges, cfg=None, fixed=None, elems=None) -> list[dict]:
    """-> [{name, kind, nominal, idx (int64), vec (float64 (k,3)), zone (int64 allowed nodes), info{…}}].
    beads = [{name, kind 'D'|'W'|'DF'|'W1', segs [segment id…], zones? [junction-zone id…], hold 0|1}] (DF = depth with
    the floor width kept and the flank angle kept — the entry widens; W1 = one-sided entry width — esl contract
    esl_bead_depth_mode.md §1.2.1·§1.6.3; W1 items may carry ``ramp: "end"`` and ``min_nodes``);
    ranges = {name: [lo, hi]} default ranges (fix the ramp / corner guard — BG-D-24·26). elems is required
    (connectivity; same array given to ``classify``)."""
    if elems is None:
        raise ValueError("basis(): elems (connectivity) is required")
    cfg = _cfg(cfg)
    M = Mesh(graph, labels, nodes, elems)
    fixed_mask = np.zeros(M.n, bool)
    if fixed is not None and len(fixed):
        fx = np.asarray(fixed, np.int64)
        fixed_mask[fx[(fx >= 0) & (fx < M.n)]] = True
    out = []
    edge_n = None
    for b in beads:
        k = b["kind"]
        if k == "DF":
            out.append(_one_df(M, b, ranges, cfg, fixed_mask))
        elif k == "W1":
            if edge_n is None:
                from .oneside import outer_edge_nodes
                edge_n = outer_edge_nodes(M)
            out.append(_one_w1(M, b, ranges, cfg, fixed_mask, edge_n))
        elif k in ("D", "W"):
            out.append(_one(M, b, ranges, cfg, fixed_mask))
        else:
            raise ValueError(f"bead {b.get('name')}: unknown kind {k!r}")
    return out


def _one(M: Mesh, b: dict, ranges: dict, cfg: dict, fixed_mask: np.ndarray) -> dict:
    kind = b["kind"]
    Z = bead_zones(M, b["segs"], b.get("zones") or (), kind)
    mc = cfg["morph"]
    h = max(M.h_mm, 1e-6)
    lab = M.lab
    cls = lab["cls"]
    S = Z["S"]
    F, p = Z["floor"], Z["parent"]
    rel = float(M.floors[F]["rel_height"])
    s = 1.0 if rel >= 0 else -1.0
    lens = np.array([float(M.segs[x]["length"] or 1.0) for x in S])
    if kind == "D":
        nominal = float(np.sum(lens * np.array([float(M.segs[x]["D"]) for x in S])) / lens.sum())
    else:
        ws = [M.segs[x]["entry_width"] for x in S]
        if any(w is None for w in ws):
            raise ValueError(f"bead {b['name']}: W needs entry lines on both sides for every segment")
        nominal = float(np.sum(lens * np.array(ws, float)) / lens.sum())
    rng = ranges.get(b["name"]) if ranges else None
    ext = _var_ext(rng, nominal) if rng else 0.3 * nominal
    ext_eff = ext if kind == "D" else 0.5 * ext
    L = max(float(mc["ramp_k"]) * ext_eff, float(mc["ramp_k"]) * h)
    info = {"ramp_mm": L, "ext": ext, "sign": s, "warnings": [], "shared_children": Z["shared"],
            "children": Z["exclusive"], "islands": Z["islands"], "straddle": list(Z["straddle"]), "zones_in": Z["zones_in"]}
    nF, nW, E, J = Z["nF"], Z["nW"], Z["E"], Z["J"]
    ZF, ZW, ZC, ZSC, ZI = Z["ZF"], Z["ZW"], Z["ZC"], Z["ZSC"], Z["ZI"]
    nC = M.nmask(ZC)
    nSC = M.nmask(ZSC)
    nI = M.nmask(ZI)
    Uv = np.zeros((M.n, 3))
    band = np.zeros(M.n, bool)
    edge = nF & nW & ~E
    walln = nW & ~E & ~nF
    hm = edge | walln
    ent_idx = np.flatnonzero(E)
    if kind == "D":
        D = max(nominal, 1e-9)
        if ent_idx.size and hm.any():
            _d, j = cKDTree(M.P[ent_idx]).query(M.P[hm])
            xe = M.X[ent_idx[j]]
            dx = M.X[hm] - xe
            dref = np.where(edge[hm], np.abs(dx @ M.n0), D)
            dref = np.where(dref > 1e-6, dref, D)
            Uv[hm] = dx / dref[:, None]
        elif hm.any():
            Uv[hm] = s * M.n0
        inner = nF & ~hm & ~E
        Uv[inner] = s * M.n0
        # exclusive children (+ their islands) rigid
        Uv[nC & ~hm & ~E] = s * M.n0
        # shared child walls on the bead side: linear in height between the S floor (1) and the child floor (0)
        if Z["shared"]:
            lvF = float(np.median(M.hn[nF])) if nF.any() else float(M.floors[F]["level"])
            for c in Z["shared"]:
                cf = M.nmask((lab["floor"] == c) & (cls == CLS["floor"]))
                lvc = float(np.median(M.hn[cf])) if cf.any() else float(M.floors[c]["level"])
                cn = M.nmask(ZSC) & ~nF & ~cf
                tt = np.clip(np.abs(M.hn - lvF) / max(abs(lvc - lvF), 1e-9), 0.0, 1.0)
                Uv[cn] = ((1.0 - tt[cn]) * s)[:, None] * M.n0
                info["warnings"].append({"code": "BG_SHARED_CHILD", "level": "info", "child": int(c),
                                         "n_nodes": int(cn.sum())})
    else:
        mv = E | hm
        idx = np.flatnonzero(mv)
        _d, nref, _in = _skeleton_dist(M, S, M.P[idx])
        nout = _smooth_dirs(M, ZW | ZF, mv, idx, nref, int(mc["w_smooth_iters"]))
        Uv[idx] = 0.5 * _plan3(M, nout)
        straight = np.zeros(M.n, bool)                # exact perpendicular kept (achieved-W measurement nodes)
        straight[idx[np.linalg.norm(nout - nref, axis=1) < 1e-9]] = True
        # parent blend band
        bl = cfg["blend"]
        Rw = max(float(bl["min_mm"]), float(bl["k"]) * ext / 2.0, 3.0 * h)
        band, on_par = _band(M, Z, Rw, ent_idx, Uv, info)
    # harmonic extension of the in-plane part over the floor (Dirichlet: edge / wall values, everything not interior)
    Lf = M.laplacian(ZF)
    dir_zero = (nC | nSC | nI | J | M.nmask(~(ZF | ZW)) & ~E)
    free = nF & ~hm & ~E & ~dir_zero
    if kind == "W":
        free &= ~band
    Up = np.c_[Uv @ M.e1, Uv @ M.e2, np.zeros(M.n)]
    Up[free] = 0.0
    Up = _harmonic(Lf, free, Up, cols=(0, 1))
    allowed_n = M.nmask(Z["allowed_el"]) | band
    if kind == "W" and info.get("band_islands"):
        allowed_n |= M.nmask(np.isin(lab["island"], info["band_islands"]))
    # BG-D-47: one node rule with the outside checks — a node shared with an element outside the allowed set stays
    A_el = Z["allowed_el"]
    if kind == "W":                                    # + parent floor and its non-straddling islands (blend band)
        A_el = A_el | Z["parent_floor"] | (np.isin(lab["island"], on_par) & (lab["island"] >= 0))
    mov = movable_nodes(M, A_el)
    psi, n_hold = (_hold(M, allowed_n, fixed_mask, cfg) if int(b.get("hold", 1)) else (np.ones(M.n), 0))
    phi = _ramp(M, J, np.flatnonzero(allowed_n), L)
    if kind == "D":
        # E nodes fixed (entry), in-plane from the harmonic solve on free nodes
        Uv[free] = (Uv[free] @ M.n0)[:, None] * M.n0 + _plan3(M, Up[free, :2])
        Uv[E] = 0.0
        # corner guard (BG-D-26) on the homothety plan components, then re-solve the interior once. Next to a
        # straddling island (D6 — the boss sits on the flank and moves rigidly) the flank does not narrow: the
        # homothety plan part fades in over b = 2·max(h, ext) from the island (frozen like the guard factors).
        c = np.ones(M.n)
        if hm.any():
            Uw = Uv * (phi * psi)[:, None]
            c = _corner_guard(M, ZF | ZW, Uw, hm, ext, mc["corner"], float(cfg["quality"]["flip_deg"]))
            cg_ = c.copy()
            st_ids = [i for i in Z["islands"] if M.islands[i]["straddle"]]
            if st_ids:
                sn = M.nmask(np.isin(lab["island"], st_ids))
                hidx = np.flatnonzero(hm)
                dI, _ = cKDTree(M.P[sn]).query(M.P[hidx])
                kap = U.smoothstep(dI / (2.0 * max(h, ext)))
                near = kap < 1.0
                hn_ = hidx[near]
                un = (Uv[hn_] @ M.n0)[:, None] * M.n0[None, :]
                Uv[hn_] = un + kap[near, None] * (Uv[hn_] - un)
                c[hn_] = np.minimum(c[hn_], np.maximum(kap[near], 1e-12))
                info["straddle_fade_n"] = int(near.sum())
            if (cg_ < 1).any():
                pl = _plan3(M, np.c_[Uv[hm] @ M.e1, Uv[hm] @ M.e2] * cg_[hm, None])
                Uv[hm] = (Uv[hm] @ M.n0)[:, None] * M.n0 + pl
                Up = np.c_[Uv @ M.e1, Uv @ M.e2, np.zeros(M.n)]
                Up[free] = 0.0
                Up = _harmonic(Lf, free, Up, cols=(0, 1))
                Uv[free] = (Uv[free] @ M.n0)[:, None] * M.n0 + _plan3(M, Up[free, :2])
                ncg = int((cg_ < 1).sum())
                fl_deg = _flank_max_deg(M, ZW, Uv, ext)
                info["warnings"].append({"code": "BG_CORNER_GUARD", "level": "info", "n_nodes": ncg,
                                         "flank_max_deg": U.f3(fl_deg)})
        info["corner_n"] = int((c < 1).sum())
    else:
        c = np.ones(M.n)
        Uv[free] = _plan3(M, Up[free, :2])
    Uv *= (phi * psi)[:, None]
    Uv[J] = 0.0
    if kind == "D":
        Uv[E] = 0.0
    _islands(M, Z, b, Uv, info, nF | band, nW, mov, fixed_mask)
    isl = lab["island"]
    # exact zero outside A_v (structural — BG-D-32 checks the same node rule, BG-D-47)
    Uv[~(allowed_n & mov)] = 0.0
    # achieved nodes (BG-D-33)
    island_nodes = M.nmask((isl >= 0))
    if kind == "D":
        ach = nF & (phi >= 1.0) & (psi >= 1.0) & (c >= 1.0) & ~island_nodes & ~E
        nf_full = nF & (phi >= 1.0) & ~island_nodes & ~E
        info["achieved_idx"] = np.flatnonzero(ach)
        info["achieved_ratio"] = float(ach.sum() / max(int(nf_full.sum()), 1))
        if not ach.any():
            info["warnings"].append({"code": "BG_SEGMENT_SHORT", "length_mm": U.f3(lens.sum()), "ramp_mm": U.f3(L)})
            info["short"] = True
    else:
        mid = np.zeros(M.n, bool)
        idx = np.flatnonzero(E & (phi >= 1.0) & (psi >= 1.0) & straight)
        if idx.size:
            _d, _n, inn = _skeleton_dist(M, S, M.P[idx])
            mid[idx[inn]] = True
        info["achieved_idx"] = np.flatnonzero(mid)
        if not mid.any():
            info["warnings"].append({"code": "BG_SEGMENT_SHORT", "length_mm": U.f3(lens.sum()), "ramp_mm": U.f3(L)})
            info["short"] = True
    info["hold_n_fixed"] = n_hold
    info["band_n"] = int(band.sum())
    nz = np.flatnonzero(np.any(Uv != 0.0, axis=1))
    return {"name": b["name"], "kind": kind, "nominal": nominal, "idx": nz.astype(np.int64), "vec": Uv[nz],
            "zone": np.flatnonzero(allowed_n).astype(np.int64), "info": info, "segs": list(S),
            "zones": sorted(int(z) for z in (b.get("zones") or ()))}


def _common(M: Mesh, b: dict, Z: dict, nominal: float, ranges: dict, cfg: dict, ext_band_k: float):
    """shared prelude of DF / W1: range ext, ramp length L (ext_eff = ext), info skeleton."""
    mc = cfg["morph"]
    h = max(M.h_mm, 1e-6)
    rng = ranges.get(b["name"]) if ranges else None
    ext = _var_ext(rng, nominal) if rng else 0.3 * nominal
    L = max(float(mc["ramp_k"]) * ext, float(mc["ramp_k"]) * h)
    rel = float(M.floors[Z["floor"]]["rel_height"])
    info = {"ramp_mm": L, "ext": ext, "sign": 1.0 if rel >= 0 else -1.0, "warnings": [],
            "shared_children": Z["shared"], "children": Z["exclusive"], "islands": Z["islands"],
            "straddle": list(Z["straddle"]), "zones_in": Z["zones_in"]}
    return h, ext, L, info


def _allowed_wide(M: Mesh, Z: dict):
    """A_DF / A_W1 element set = the zone's allowed elements ∪ parent floor ∪ the parent's non-straddling islands."""
    isl = M.lab["island"]
    on_par = [i["id"] for i in M.graph["islands"] if i["parent"] == Z["parent"] and not i["straddle"]]
    return Z["allowed_el"] | Z["parent_floor"] | (np.isin(isl, on_par) & (isl >= 0))


def _seg_nodes(M: Mesh, Z: dict) -> dict:
    """{segment id: node mask of that segment's Z_F ∪ Z_W elements} (junction-zone / island elements = −1, excluded)."""
    seg = M.lab["segment"]
    el = Z["ZF"] | Z["ZW"]
    return {s: M.nmask(el & (seg == s)) for s in Z["S"]}


def _one_df(M: Mesh, b: dict, ranges: dict, cfg: dict, fixed_mask: np.ndarray) -> dict:
    """kind DF (esl contract esl_bead_depth_mode.md §1.2.1, DM-21): floor = s·n0 (plan 0 — rigid, no harmonic, no corner
    guard), walls + entry about the nearest floor-edge node: normal s·(1 − clip(h/D_col)), plan r·n_out with
    r = (x − x_f)_plan·n_out / D_col (entry: D_col = h -> cotθ_local), so each column keeps its own flank angle and the
    entry widens by cotθ·ΔD; parent blend band from E, ramp / hold as D, E not zeroed."""
    Z = bead_zones(M, b["segs"], b.get("zones") or (), "D")
    lab = M.lab
    S = Z["S"]
    lens = np.array([float(M.segs[x]["length"] or 1.0) for x in S])
    nominal = float(np.sum(lens * np.array([float(M.segs[x]["D"]) for x in S])) / lens.sum())
    h, ext, L, info = _common(M, b, Z, nominal, ranges, cfg, 1.0)
    s = info["sign"]
    mc = cfg["morph"]
    nF, nW, E, J = Z["nF"], Z["nW"], Z["E"], Z["J"]
    ZF, ZW, ZC, ZSC = Z["ZF"], Z["ZW"], Z["ZC"], Z["ZSC"]
    nC = M.nmask(ZC)
    Uv = np.zeros((M.n, 3))
    edge = nF & nW & ~E
    walln = nW & ~E & ~nF
    hm = edge | walln
    D = max(nominal, 1e-9)
    # floor (+ exclusive children rigid): s·n0, plan 0
    Uv[nF] = s * M.n0
    Uv[nC & ~hm & ~E] = s * M.n0
    col = walln | E
    cidx = np.flatnonzero(col)
    rE = np.zeros(M.n)
    rS = np.zeros(M.n)
    rRaw = np.zeros(M.n)
    info["entry_clipped_n"] = 0
    eidx = np.flatnonzero(edge)
    if cidx.size and eidx.size:
        _d, j = cKDTree(M.P[eidx]).query(M.P[cidx])
        xf = M.X[eidx[j]]
        dx = M.X[cidx] - xf
        hh = np.abs(dx @ M.n0)
        isE = E[cidx]
        Dcol = np.where(isE, np.where(hh > 1e-6, hh, D), D)
        tt = 1.0 - np.clip(hh / Dcol, 0.0, 1.0)
        tt[isE] = 0.0
        # outward direction: own-segment interior skeleton normal, else the chord (x − x_f) in plan
        mv = E | edge | walln
        idx = np.flatnonzero(mv)
        _bd, nsk, inner, _sd, sid = _skel_full(M, S, M.P[idx])
        own = _seg_nodes(M, Z)
        ok = inner & (sid >= 0)
        for sg_, msk in own.items():
            sel = sid == sg_
            ok[sel] &= msk[idx[sel]]
        _de, je = cKDTree(M.P[eidx]).query(M.P[idx])
        ch = M.P[idx] - M.P[eidx[je]]
        chn = np.linalg.norm(ch, axis=1)
        chord = np.where(chn[:, None] > 1e-12, ch / np.maximum(chn, 1e-12)[:, None], 0.0)
        nref = np.where(ok[:, None], nsk, chord)
        nout = _smooth_dirs(M, ZW | ZF, mv, idx, nref, int(mc["w_smooth_iters"]))
        pos = -np.ones(M.n, np.int64)
        pos[idx] = np.arange(idx.size)
        no_c = nout[pos[cidx]]
        dpl = np.c_[dx @ M.e1, dx @ M.e2]
        r = np.einsum("ij,ij->i", dpl, no_c) / Dcol
        # columns without an own interior skeleton projection (segment ends, corners, junction sides) use the chord to
        # the nearest floor-edge node, which overshoots where the floor edge stops short (ring corners): cap their r at
        # the largest r of the interior entry columns (contract correction — work/findings.md DM-C1-1)
        okc = ok[pos[cidx]]
        ri = r[isE & okc]
        if ri.size and (~okc).any():
            cap = float(ri.max()) * np.where(isE, 1.0, np.maximum(1.0 - tt, 0.0))
            r = np.where(okc, r, np.minimum(r, cap))
            info["chord_capped_n"] = int(((~okc) & (r >= cap - 1e-15) & (cap > 0)).sum())
        # DM-30 entry r smoothed along the entry line (same-facing entry nodes only), DM-31 neighbour-gap factor κ_o;
        # walls follow their column's entry (plan-nearest E): plan = (1 − t)·r_e·n_out
        eI = cidx[isE]
        r_raw = r[isE]
        n_e = no_c[isE]
        r_s, kap_o, n_clip = _entry_fix(M, Z, eI, r_raw, n_e, h, ext, b)
        r_e = r_s * kap_o
        rr = np.zeros(cidx.size)
        rr[isE] = r_e
        wl = ~isE
        if wl.any() and eI.size:
            _dw, jw = cKDTree(M.P[eI]).query(M.P[cidx[wl]])
            rr[wl] = np.maximum(1.0 - tt[wl], 0.0) * r_e[jw]
        Uv[cidx] = (s * tt)[:, None] * M.n0 + _plan3(M, rr[:, None] * no_c)
        rE[eI] = r_e
        rS[eI] = r_s
        rRaw[eI] = r_raw
        info["entry_clipped_n"] = n_clip
    elif cidx.size:
        Uv[cidx] = 0.0
    # shared child walls on the bead side: height-linear, plan 0 (D rule, overrides — BG_SHARED_CHILD)
    steep = []
    if Z["shared"]:
        cls = lab["cls"]
        lvF = float(np.median(M.hn[nF])) if nF.any() else float(M.floors[Z["floor"]]["level"])
        for c in Z["shared"]:
            cf = M.nmask((lab["floor"] == c) & (cls == CLS["floor"]))
            lvc = float(np.median(M.hn[cf])) if cf.any() else float(M.floors[c]["level"])
            cn = M.nmask(ZSC) & ~nF & ~cf
            tt2 = np.clip(np.abs(M.hn - lvF) / max(abs(lvc - lvF), 1e-9), 0.0, 1.0)
            Uv[cn] = ((1.0 - tt2[cn]) * s)[:, None] * M.n0
            info["warnings"].append({"code": "BG_SHARED_CHILD", "level": "info", "child": int(c),
                                     "n_nodes": int(cn.sum())})
            foot = np.flatnonzero(M.nmask(ZSC) & nF)
            if foot.size and cf.any():
                dr, _ = cKDTree(M.P[cf]).query(M.P[foot])
                rf = float(np.median(dr))
                hf = abs(lvc - lvF)
                if rf > 1e-9:
                    steep.append([U.f3(np.degrees(np.arctan2(hf, rf))), U.f3(np.degrees(np.arctan2(hf + ext, rf)))])
    info["steep_deg"] = steep[0] if steep else None
    # straddling islands: fade the plan part of the walls / entry next to the island (residual R-DM-6)
    st_ids = [i for i in Z["islands"] if M.islands[i]["straddle"]]
    if st_ids and cidx.size:
        sn = M.nmask(np.isin(lab["island"], st_ids))
        dI, _ = cKDTree(M.P[sn]).query(M.P[cidx])
        kap = U.smoothstep(dI / (2.0 * max(h, ext)))
        near = kap < 1.0
        hn_ = cidx[near]
        un = (Uv[hn_] @ M.n0)[:, None] * M.n0[None, :]
        Uv[hn_] = un + kap[near, None] * (Uv[hn_] - un)
        info["straddle_fade_n"] = int(near.sum())
    # parent blend band from E (normal 0 -> plan only)
    bl = cfg["blend"]
    ent_idx = np.flatnonzero(E)
    r_max = float(rE[ent_idx].max()) if ent_idx.size else 0.0
    Rw = max(float(bl["min_mm"]), float(bl["k"]) * ext * r_max, 3.0 * h)
    band, _on_par = _band(M, Z, Rw, ent_idx, Uv, info, mix_h=h)
    A_el = _allowed_wide(M, Z)
    allowed_n = M.nmask(A_el) | band
    if info.get("band_islands"):
        allowed_n |= M.nmask(np.isin(lab["island"], info["band_islands"]))
    mov = movable_nodes(M, A_el)
    psi, n_hold = (_hold(M, allowed_n, fixed_mask, cfg) if int(b.get("hold", 1)) else (np.ones(M.n), 0))
    phi = _ramp(M, J, np.flatnonzero(allowed_n), L)
    Uv *= (phi * psi)[:, None]
    Uv[J] = 0.0
    _islands(M, Z, b, Uv, info, nF | band, nW, mov, fixed_mask)
    Uv[~(allowed_n & mov)] = 0.0
    # DF entry guard (DM-32 — BG-D-26 device on the entry side): elements DF moves in plan (walls + parent-floor
    # elements touching the entry or the band, floor excluded) — at ±ext an area ratio < area_ratio_min or an inverted
    # element shrinks the plan part of its moving nodes (entry ∪ walls ∪ band); factor frozen in the basis (linear)
    gmov = (E | walln | band) & allowed_n & mov
    gel = (ZW | M.emask_of_nodes(E | band)) & ~ZF
    info["entry_guard_n"] = 0
    if gmov.any() and gel.any():
        cE = _corner_guard(M, gel, Uv, gmov, ext, mc["corner"], float(cfg["quality"]["flip_deg"]))
        if (cE < 1.0).any():
            un = (Uv @ M.n0)[:, None] * M.n0[None, :]
            Uv = un + (Uv - un) * cE[:, None]
            info["entry_guard_n"] = int((cE < 1.0).sum())
            info["warnings"].append({"code": "DF_ENTRY_GUARD", "level": "info", "n_nodes": info["entry_guard_n"],
                                     "steep_max_deg": U.f3(_flank_change_deg(M, ZW & M.emask_of_nodes(cE < 1.0),
                                                                             Uv, ext))})
    isl = lab["island"]
    island_nodes = M.nmask((isl >= 0))
    ach = nF & (phi >= 1.0) & (psi >= 1.0) & ~island_nodes & ~E
    nf_full = nF & (phi >= 1.0) & ~island_nodes & ~E
    info["achieved_idx"] = np.flatnonzero(ach)
    info["achieved_ratio"] = float(ach.sum() / max(int(nf_full.sum()), 1))
    if not ach.any():
        info["warnings"].append({"code": "BG_SEGMENT_SHORT", "length_mm": U.f3(lens.sum()), "ramp_mm": U.f3(L)})
        info["short"] = True
    info["corner_n"] = 0
    # diagnostics (§2.6): cot of the full-ramp entry columns, floor plan max, entry wave, own walls without entry top
    full = E & (phi >= 1.0) & (psi >= 1.0)
    cots = rS[full]
    info["cot_min"] = U.f3(float(cots.min())) if cots.size else None
    info["cot_med"] = U.f3(float(np.median(cots))) if cots.size else None
    info["cot_max"] = U.f3(float(cots.max())) if cots.size else None
    plan = Uv - (Uv @ M.n0)[:, None] * M.n0[None, :]
    pn = np.linalg.norm(plan, axis=1)
    fl = nF & (phi >= 1.0) & (psi >= 1.0)
    info["floor_plan_max_mm"] = U.f3(float(pn[fl].max()) * ext) if fl.any() else 0.0
    dv = (rS - rRaw)[full]
    info["angle_dev_mm"] = U.f3(float(np.sqrt(np.mean(dv * dv))) * ext) if dv.size else 0.0
    info["wall_no_entry_n"] = int((walln & J).sum())
    info["hold_n_fixed"] = n_hold
    info["hold_pinch_n"] = int((E & (psi < 1.0)).sum())
    info["band_n"] = int(band.sum())
    nz = np.flatnonzero(np.any(Uv != 0.0, axis=1))
    return {"name": b["name"], "kind": "DF", "nominal": nominal, "idx": nz.astype(np.int64), "vec": Uv[nz],
            "zone": np.flatnonzero(allowed_n).astype(np.int64), "info": info, "segs": list(S),
            "zones": sorted(int(z) for z in (b.get("zones") or ()))}


def _entry_fix(M: Mesh, Z: dict, eI: np.ndarray, r_raw: np.ndarray, n_e: np.ndarray, h: float, ext: float, b: dict):
    """DF entry (esl contract §1.2.1 — DM-30·31): r_s = gaussian-weighted mean of r_raw over the bead's entry nodes
    facing the same way (n_out·n_out' > 0), ρ = entry_smooth_rel·h (0 = none); κ_o = min(1, entry_gap_rel·d_o/(r_s·ext))
    with d_o = plan distance to the other zones (the band's ``others``), smoothed with the same weights, frozen in the
    basis (linear). -> (r_s, κ_o, number of entry nodes with raw κ_o < 1)."""
    sm = float(b.get("entry_smooth_rel", DF_ENTRY["entry_smooth_rel"]))
    gap = float(b.get("entry_gap_rel", DF_ENTRY["entry_gap_rel"]))
    n = eI.size
    if n == 0:
        return r_raw.copy(), np.ones(0), 0
    rho = sm * h
    W = None
    if rho > 0.0 and n > 1:
        tree = cKDTree(M.P[eI])
        pairs = tree.sparse_distance_matrix(tree, ENTRY_SMOOTH_CUT * rho, output_type="coo_matrix")
        i, j, d = pairs.row, pairs.col, pairs.data
        keep = np.einsum("ij,ij->i", n_e[i], n_e[j]) > 0.0
        i, j, d = i[keep], j[keep], d[keep]
        from scipy import sparse as _sp
        W = _sp.coo_matrix((np.exp(-(d / rho) ** 2), (i, j)), shape=(n, n)).tocsr()
        W = W + _sp.identity(n, format="csr") - _sp.diags(W.diagonal())      # self weight exp(0) = 1 exactly

    def smooth(v):
        if W is None:
            return v.copy()
        return np.asarray(W @ v).ravel() / np.asarray(W.sum(axis=1)).ravel()
    r_s = smooth(r_raw)
    p = Z["parent"]
    others = ~(Z["parent_floor"] | Z["ZF"] | Z["ZW"] | Z["ZI"])
    isl = M.lab["island"]
    on_par = [x["id"] for x in M.graph["islands"] if x["parent"] == p and not x["straddle"]]
    others &= ~np.isin(isl, on_par)
    n_oth = M.nmask(others)
    kap = np.ones(n)
    if n_oth.any():
        d_o, _ = cKDTree(M.P[n_oth]).query(M.P[eI])
        m = np.abs(r_s) * ext
        lim = gap * d_o
        raw = np.where(m > lim, lim / np.maximum(m, 1e-300), 1.0)
        n_clip = int((raw < 1.0).sum())
        if n_clip:
            kap = np.minimum(smooth(raw), 1.0)
        return r_s, kap, n_clip
    return r_s, kap, 0


def _one_w1(M: Mesh, b: dict, ranges: dict, cfg: dict, fixed_mask: np.ndarray, edge_n: np.ndarray) -> dict:
    """kind W1 (esl contract §1.6.3, DM-13·22): one-sided entry width. Open side (entry ∪ walls ∪ floor edge on the
    open side of the skeleton) translates ΔW·n_out, fixed side (walls + floor boundary) = 0, floor interior harmonic,
    ramp ``end`` (fixed-side interior J nodes are not ramp origins), blend band from the open-side entry only."""
    from .oneside import measure
    if b.get("ramp", "end") != "end":
        raise ValueError(f"bead {b['name']}: W1 ramp must be 'end'")
    Z = bead_zones(M, b["segs"], b.get("zones") or (), "W")
    lab = M.lab
    S = Z["S"]
    mn = int(b.get("min_nodes", 3))
    osd = measure(M, S, min_nodes=mn, edge_nodes=edge_n)
    bad = [x for x in S if not osd[x]["ok"]]
    if bad:
        raise ValueError(f"bead {b['name']}: W1 needs a one-sided entry on every segment ({bad}: "
                         f"{[osd[x]['reason'] for x in bad]})")
    lens = np.array([float(M.segs[x]["length"] or 1.0) for x in S])
    nominal = float(np.sum(lens * np.array([float(osd[x]["width"]) for x in S])) / lens.sum())
    h, ext, L, info = _common(M, b, Z, nominal, ranges, cfg, 1.0)
    mc = cfg["morph"]
    nF, nW, E, J = Z["nF"], Z["nW"], Z["E"], Z["J"]
    ZF, ZW, ZC, ZSC, ZI = Z["ZF"], Z["ZW"], Z["ZC"], Z["ZSC"], Z["ZI"]
    nC, nSC, nI = M.nmask(ZC), M.nmask(ZSC), M.nmask(ZI)
    Uv = np.zeros((M.n, 3))
    edge = nF & nW & ~E
    walln = nW & ~E & ~nF
    hm = edge | walln
    sig = {x: float(osd[x]["side"]) for x in S}
    info["open_side"] = {int(x): int(sig[x]) for x in S}
    # sides of the bead's floor / wall nodes
    bnd = nF & (M.nmask(~ZF) | edge_n)
    cand = np.flatnonzero(hm | E | bnd)
    _bd, nsk, inner, sd, sid = _skel_full(M, S, M.P[cand])
    so = np.array([sig.get(int(x), 0.0) for x in sid])
    openm = np.zeros(M.n, bool)
    fixm = np.zeros(M.n, bool)
    is_open = (sd == so) & (sid >= 0)
    openm[cand[is_open]] = True
    fixm[cand[~is_open & (sid >= 0)]] = True
    mvo = (E | hm) & openm
    fx = (nW | bnd) & fixm & ~mvo
    idx = np.flatnonzero(mvo)
    pos = -np.ones(M.n, np.int64)
    pos[cand] = np.arange(cand.size)
    nref = nsk[pos[idx]]
    nout = _smooth_dirs(M, ZW | ZF, mvo, idx, nref, int(mc["w_smooth_iters"]))
    Uv[idx] = _plan3(M, nout)
    straight = np.zeros(M.n, bool)
    straight[idx[np.linalg.norm(nout - nref, axis=1) < 1e-9]] = True
    bl = cfg["blend"]
    Rw = max(float(bl["min_mm"]), float(bl["k"]) * ext, 3.0 * h)
    ent_o = np.flatnonzero(E & openm)
    band, on_par = _band(M, Z, Rw, ent_o, Uv, info, mix_h=h)
    Lf = M.laplacian(ZF)
    dir_zero = (nC | nSC | nI | J | M.nmask(~(ZF | ZW)) & ~E)
    free = nF & ~hm & ~E & ~dir_zero & ~band & ~fx
    Up = np.c_[Uv @ M.e1, Uv @ M.e2, np.zeros(M.n)]
    Up[fx] = 0.0
    Up[free] = 0.0
    Up = _harmonic(Lf, free, Up, cols=(0, 1))
    Uv[fx] = 0.0
    Uv[free] = _plan3(M, Up[free, :2])
    allowed_n = M.nmask(Z["allowed_el"]) | band
    if info.get("band_islands"):
        allowed_n |= M.nmask(np.isin(lab["island"], info["band_islands"]))
    A_el = Z["allowed_el"] | Z["parent_floor"] | (np.isin(lab["island"], on_par) & (lab["island"] >= 0))
    mov = movable_nodes(M, A_el)
    psi, n_hold = (_hold(M, allowed_n, fixed_mask, cfg) if int(b.get("hold", 1)) else (np.ones(M.n), 0))
    # ramp "end": fixed-side interior J nodes are Dirichlet 0 only, not ramp origins
    Jr = J.copy()
    jf = np.flatnonzero(J & fixm)
    if jf.size:
        _bj, _nj, inj, _sj, _ij = _skel_full(M, S, M.P[jf])
        Jr[jf[inj]] = False
    phi = _ramp(M, Jr, np.flatnonzero(allowed_n), L)
    Uv *= (phi * psi)[:, None]
    Uv[J] = 0.0
    _islands(M, Z, b, Uv, info, nF | band, nW, mov, fixed_mask)
    Uv[~(allowed_n & mov)] = 0.0
    mid = np.zeros(M.n, bool)
    ai = np.flatnonzero(E & openm & (phi >= 1.0) & (psi >= 1.0) & straight)
    if ai.size:
        _d, _n, inn = _skeleton_dist(M, S, M.P[ai])
        mid[ai[inn]] = True
    info["achieved_idx"] = np.flatnonzero(mid)
    if not mid.any():
        info["warnings"].append({"code": "BG_SEGMENT_SHORT", "length_mm": U.f3(lens.sum()), "ramp_mm": U.f3(L)})
        info["short"] = True
    info["one_side"] = {int(x): {k: osd[x][k] for k in ("side", "width", "floor", "fixed")} for x in S}
    info["floor_nominal"] = U.f3(float(np.sum(lens * np.array([float(osd[x]["floor"]) for x in S])) / lens.sum()))
    info["hold_n_fixed"] = n_hold
    info["hold_pinch_n"] = int((E & openm & (psi < 1.0)).sum())
    info["band_n"] = int(band.sum())
    nz = np.flatnonzero(np.any(Uv != 0.0, axis=1))
    return {"name": b["name"], "kind": "W1", "nominal": nominal, "idx": nz.astype(np.int64), "vec": Uv[nz],
            "zone": np.flatnonzero(allowed_n).astype(np.int64), "info": info, "segs": list(S),
            "zones": sorted(int(z) for z in (b.get("zones") or ()))}


def _band(M: Mesh, Z: dict, Rw: float, src_idx: np.ndarray, Uv: np.ndarray, info: dict, mix_h: float | None = None):
    """parent-floor blend band (W·DF·W1 — one internal function, contract esl_bead_depth_mode §9): parent-floor nodes
    within R_w of the source entry nodes ``src_idx`` copy the nearest source displacement × (1 − smoothstep(d/R_w)),
    or — ``mix_h`` given (DF·W1, DM-C1-2) — the distance-weighted mix of the up to ``BAND_MIX_K`` nearest sources
    within R_w, w_k = 1/(d_k² + (0.1h)²) (continuous between facing entry lines; W keeps the nearest copy),
    clipped near other zones (SELECT_BLEND_CLIPPED); parent-floor islands touched by the band move rigidly with it.
    -> (band node mask, ids of the parent's non-straddling islands). Uv / info updated in place."""
    lab = M.lab
    p = Z["parent"]
    E, nF, nW = Z["E"], Z["nF"], Z["nW"]
    ZF, ZW, ZI = Z["ZF"], Z["ZW"], Z["ZI"]
    band = np.zeros(M.n, bool)
    pf = M.nmask(Z["parent_floor"]) & ~E & ~nF & ~nW
    others = ~(Z["parent_floor"] | ZF | ZW | ZI)
    isl = lab["island"]
    on_par = [i["id"] for i in M.graph["islands"] if i["parent"] == p and not i["straddle"]]
    others &= ~np.isin(isl, on_par)
    n_oth = M.nmask(others)
    pf &= ~n_oth
    info["blend_mm"] = Rw
    if src_idx.size and pf.any():
        cand = np.flatnonzero(pf)
        tree = cKDTree(M.P[src_idx])
        de, je = tree.query(M.P[cand])
        sel = de < Rw
        bidx = cand[sel]
        w = 1.0 - U.smoothstep(de[sel] / Rw)
        if mix_h is not None and bidx.size:
            kk = min(BAND_MIX_K, int(src_idx.size))
            dk, jk = tree.query(M.P[bidx], k=kk)
            dk = dk.reshape(bidx.size, kk)
            jk = jk.reshape(bidx.size, kk)
            wk = np.where(dk < Rw, 1.0 / (dk * dk + (BAND_MIX_EPS_H * mix_h) ** 2), 0.0)
            umix = np.einsum("ik,ikj->ij", wk, Uv[src_idx[np.minimum(jk, src_idx.size - 1)]]) / wk.sum(axis=1)[:, None]
        if n_oth.any():
            do, _ = cKDTree(M.P[n_oth]).query(M.P[bidx])
            clip = do < Rw
            if clip.any():
                info["warnings"].append({"code": "SELECT_BLEND_CLIPPED", "R_mm": U.f3(Rw),
                                         "d_other_mm": U.f3(float(do.min()))})
            w = w * U.smoothstep(do / Rw)
        if mix_h is not None and bidx.size:
            Uv[bidx] = umix * w[:, None]
        else:
            Uv[bidx] = Uv[src_idx[je[sel]]] * w[:, None]
        band[bidx] = True
        bi = np.unique(isl[M.emask_of_nodes(band) & (isl >= 0)])
        info["band_islands"] = [int(x) for x in bi if int(x) in on_par]
    return band, on_par


def _islands(M: Mesh, Z: dict, b: dict, Uv: np.ndarray, info: dict, rim_src: np.ndarray, nW: np.ndarray,
             mov: np.ndarray, fixed_mask: np.ndarray):
    """islands rigid (BG-D-29) — straddling ones with the foreign contact band (BG-D-27). Uv / info in place."""
    lab = M.lab
    cls = lab["cls"]
    ZF, ZC = Z["ZF"], Z["ZC"]
    h = max(M.h_mm, 1e-6)
    isl = lab["island"]
    island_ids = list(Z["islands"]) + list(info.get("band_islands", []))
    held = []
    for iid in sorted(set(island_ids)):
        e = isl == iid
        nd = np.flatnonzero(M.nmask(e))
        if nd.size == 0:
            continue
        if (fixed_mask[nd]).any() and int(b.get("hold", 1)):
            held.append(iid)
            continue
        rim = nd[rim_src[nd]]
        t_ = Uv[rim].mean(axis=0) if rim.size else np.zeros(3)
        if iid in Z["straddle"] or M.islands[iid]["straddle"]:
            if iid not in info["straddle"]:
                info["straddle"] = sorted(set(info["straddle"]) | {iid})
            foreign_floor = (cls == CLS["floor"]) & ~ZF & ~ZC & ~e
            fn = M.nmask(foreign_floor) | ~mov          # BG-D-47: + rim nodes on a foreign wall (junction-zone step)
            contact = nd[fn[nd]]
            band_el = e & (cls != CLS["floor"]) & M.emask_of_nodes(fn)
            bn = np.flatnonzero(M.nmask(band_el))
            bn = bn[np.isin(bn, nd)]
            core = np.setdiff1d(nd, np.union1d(bn, contact))
            core = core[~(rim_src | nW)[core]]          # boss nodes on the bead flank keep the flank rule
            Uv[core] = t_
            fw = nd[nW[nd] & ~rim_src[nd]]
            if fw.size and core.size:                   # blend the rigid core into the flank-rule foot over h
                dW_, jW = cKDTree(M.P[fw]).query(M.P[core])
                wgt = 1.0 - U.smoothstep(dW_ / h)
                Uv[core] = t_ + wgt[:, None] * (Uv[fw[jW]] - t_)
            if bn.size and contact.size:
                df, _ = cKDTree(M.P[contact]).query(M.P[bn])
                bs = max(h, float(df.max()))
                Uv[bn] = U.smoothstep(df / bs)[:, None] * t_
            Uv[contact] = 0.0
        else:
            Uv[nd] = t_                                  # fully rigid (rim included — SR-D-5, residual 0)
    for iid in held:
        info["warnings"].append({"code": "BG_ISLAND_HELD", "level": "info", "island": int(iid)})


def _flank_change_deg(M: Mesh, el, Uv, ext) -> float:
    """max change of the wall angle (deg from the plane) at +ext over the elements ``el`` (DF_ENTRY_GUARD report)."""
    idx = np.flatnonzero(el)
    if idx.size == 0:
        return 0.0
    C = M.C[idx]

    def ang(X1):
        a, b2, d = X1[C[:, 0]], X1[C[:, 1]], X1[C[:, 2]]
        n = np.cross(b2 - a, d - a)
        n /= np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
        return np.degrees(np.arccos(np.clip(np.abs(n @ M.n0), 0, 1)))
    return float(np.abs(ang(M.X + ext * Uv) - ang(M.X)).max())


def _flank_max_deg(M: Mesh, ZW, Uv, ext):
    """max flank angle (deg from the plane) of the bead walls at +ext (report only)."""
    idx = np.flatnonzero(ZW)
    if idx.size == 0:
        return 45.0
    X1 = M.X + ext * Uv
    C = M.C[idx]
    a, b2, d = X1[C[:, 0]], X1[C[:, 1]], X1[C[:, 2]]
    n = np.cross(b2 - a, d - a)
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
    ang = np.degrees(np.arccos(np.clip(np.abs(n @ M.n0), 0, 1)))
    return float(ang.max())


def morph(nodes, basis, values) -> np.ndarray:
    """x = x0 + Σ (v − v_nom)·B_v; values missing or equal to the nominal are skipped (bytes unchanged)."""
    X = np.array(nodes, dtype=np.float64, copy=True)
    for v in basis:
        if v["name"] not in values:
            continue
        dv = float(values[v["name"]]) - float(v["nominal"])
        if dv == 0.0 or v["idx"].size == 0:
            continue
        X[v["idx"]] += dv * v["vec"]
    return X
