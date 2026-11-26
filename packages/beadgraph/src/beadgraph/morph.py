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
BAND_MIX_K_U = 64                               # U band mix: nearest sources considered (gaussian weights — U_RULES 1)
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


def _qual_new_bad(M: Mesh, C: np.ndarray, Ud: np.ndarray, ext: float, qual: dict, vals=None) -> np.ndarray:
    """elements (rows of C) that turn newly bad at ±ext: quad Gauss Jacobian ≥ jac_min at rest and < at ±ext, triangle
    min angle ≥ tri_angle_min_deg at rest and < at ±ext (esl range guard criteria — values given by the caller).
    ``vals`` (U): the variable values to check instead of ±ext (None = ±ext — as before)."""
    ends = (ext, -ext) if vals is None else tuple(float(v) for v in vals)
    from .checks import _quad_jacobian
    bad = np.zeros(len(C), bool)
    q = C[:, 3] >= 0
    jm, tm = qual.get("jac_min"), qual.get("tri_angle_min_deg")
    if jm is not None and q.any():
        j0 = _quad_jacobian(M.X, C[q])
        for v in ends:
            bad[q] |= (j0 >= jm) & (_quad_jacobian(M.X + v * Ud, C[q]) < jm)
    if tm is not None and (~q).any():
        T = C[~q][:, :3]

        def mina(P):
            p = P[T]
            out = np.full(len(T), 180.0)
            for i in range(3):
                v1, v2 = p[:, (i + 1) % 3] - p[:, i], p[:, (i + 2) % 3] - p[:, i]
                cs_ = np.einsum("ij,ij->i", v1, v2) / np.maximum(np.linalg.norm(v1, axis=1) * np.linalg.norm(v2, axis=1),
                                                                1e-300)
                out = np.minimum(out, np.degrees(np.arccos(np.clip(cs_, -1.0, 1.0))))
            return out
        a0 = mina(M.X)
        for v in ends:
            bad[~q] |= (a0 >= tm) & (mina(M.X + v * Ud) < tm)
    return bad


def _df_entry_guard(M: Mesh, el: np.ndarray, U: np.ndarray, moved: np.ndarray, wall: np.ndarray, entry: np.ndarray,
                    ext: float, cg: dict, flip_deg: float, qual: dict | None = None):
    """DF entry guard (esl contract §1.2.1 — DM-32·34·35). Pass k (up to ``cg["iters"]``): ``_corner_guard`` one pass
    (its criteria — area ratio of parent-floor elements, normal flip, Gauss-point quad Jacobian) + concave quads (a corner
    Jacobian <= 0 at ±ext on the element's own plane or about its rest normal, > 0 at rest — ``checks.quad_corner_min``)
    + ``qual`` {jac_min, tri_angle_min_deg} (the caller's range-guard criteria, None = off): elements newly bad at ±ext
    (``_qual_new_bad``). Flagged elements: plan part of their moving nodes × ``shrink``; concave ones and quality ones
    touching an ``entry`` node also the normal part of their ``wall`` nodes (a flat fillet corner on the entry line folds
    when the wall node below only drops — the element plane turns about the entry line); deeper wall nodes keep the depth.
    Pass 2.. re-checks only elements with a node whose factor changed (the others are as in pass 1 — exact). If passes run
    out with elements still flagged by inversion / area / concave (a corner flat to ~1e-5 at rest folds under any
    motion): their moving nodes are frozen (plan 0; normal 0 only for wall nodes next to the entry — the shrink limit)
    and re-checked. -> (plan factor c, normal factor cn, (elements still flagged by inversion / area / concave — 0
    normal, elements still newly bad by ``qual``)). Same plan factors as ``_corner_guard`` where no quad turns concave and
    ``qual`` is off."""
    from .checks import quad_corner_min
    c = np.ones(M.n)
    cn = np.ones(M.n)
    el = np.asarray(el, bool)
    if not el.any() or ext <= 0:
        return c, cn, (0, 0)
    un = (U @ M.n0)[:, None] * M.n0[None, :]
    upl = U - un
    shrink, iters = float(cg["shrink"]), int(cg["iters"])
    one = dict(cg, iters=1)
    ne = M.nmask(M.emask_of_nodes(entry))               # nodes of elements touching the entry

    def flagged(sub):
        idx = np.flatnonzero(sub)
        C = M.C[idx]
        Ud = un * cn[:, None] + upl * c[:, None]
        cs = _corner_guard(M, sub, Ud, moved, ext, one, flip_deg)
        bc = np.zeros(idx.size, bool)
        qi = np.flatnonzero(C[:, 3] >= 0)
        if qi.size:
            Cq = C[qi]
            nq0 = np.cross(M.X[Cq[:, 2]] - M.X[Cq[:, 0]], M.X[Cq[:, 3]] - M.X[Cq[:, 1]])
            cq0 = (quad_corner_min(M.X, Cq) > 0.0) & (quad_corner_min(M.X, Cq, nq0) > 0.0)
            for sgn in (1.0, -1.0):
                X1 = M.X + sgn * ext * Ud
                bc[qi] |= cq0 & (np.minimum(quad_corner_min(X1, Cq), quad_corner_min(X1, Cq, nq0)) <= 0.0)
        nd = np.unique(C[bc][C[bc] >= 0])
        bq = _qual_new_bad(M, C, Ud, ext, qual) if qual else np.zeros(idx.size, bool)
        ndq = np.unique(C[bq][C[bq] >= 0])
        bqe = bq & (entry[np.where(C >= 0, C, 0)] & (C >= 0)).any(axis=1)       # entry-fillet elements: wall normal too
        ndqe = np.unique(C[bqe][C[bqe] >= 0])
        ndq_w = ndqe[moved[ndqe] & wall[ndqe]]
        sn = cs < 1.0
        left = bc | (sn[np.where(C >= 0, C, 0)] & (C >= 0)).any(axis=1)
        return cs, nd[moved[nd]], ndq[moved[ndq]], ndq_w, (int(left.sum()), int(bq.sum()))
    sub = el
    for _ in range(iters):
        cs, nd, ndq, ndq_w, _left = flagged(sub)
        if (cs >= 1.0).all() and nd.size == 0 and ndq.size == 0:
            return c, cn, (0, 0)
        pl = cs < 1.0
        pl[nd] = True
        pl[ndq] = True
        c[pl] *= shrink
        cn[nd[wall[nd]]] *= shrink
        cn[ndq_w] *= shrink
        sub = el & M.emask_of_nodes((c < 1.0) | (cn < 1.0))
    # shrink^iters did not settle (a corner flat to ~1e-5 at rest folds under any motion): freeze the moving nodes of
    # the elements still flagged by the inversion / area / concave criteria (the limit of the shrink), re-check
    for _ in range(iters):
        cs, nd, _ndq, _w, (left, _ql) = flagged(sub)
        if left == 0:
            break
        c[cs < 1.0] = 0.0
        c[nd] = 0.0
        cn[nd[wall[nd] & ne[nd]]] = 0.0                  # depth frozen only next to the entry (fillet slivers)
        sub = el & M.emask_of_nodes((c < 1.0) | (cn < 1.0))
    return c, cn, flagged(sub)[4]


def _var_ext(rng, nominal):
    lo, hi = (float(v) for v in rng)
    return max(abs(hi - nominal), abs(lo - nominal))


def basis(graph, labels, nodes, beads, ranges, cfg=None, fixed=None, elems=None) -> list[dict]:
    """-> [{name, kind, nominal, idx (int64), vec (float64 (k,3)), zone (int64 allowed nodes), info{…}}].
    beads = [{name, kind 'D'|'W'|'DF'|'W1'|'U', segs [segment id…], zones? [junction-zone id…], hold 0|1}] (DF = depth
    with the floor width kept and the flank angle kept — the entry widens; W1 = one-sided entry width — esl contract
    esl_bead_depth_mode.md §1.2.1·§1.6.3; W1 items may carry ``ramp: "end"`` and ``min_nodes``; U = bead position
    perpendicular to the path, nominal 0 — esl contract esl_bead_pos_u.md §1.1, item keys in ``_one_u``);
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
        elif k == "U":
            if edge_n is None:
                from .oneside import outer_edge_nodes
                edge_n = outer_edge_nodes(M)
            out.append(_one_u(M, b, ranges, cfg, fixed_mask, edge_n))
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
    band, _on_par = _band(M, Z, Rw, ent_idx, Uv, info, mix_h=h, isl_obstacle=True)
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
    info["entry_guard_left"] = 0
    info["entry_guard_qual_left"] = 0
    if gmov.any() and gel.any():
        qual = {"jac_min": b.get("guard_jac_min"), "tri_angle_min_deg": b.get("guard_tri_angle_min_deg")}
        qual = {k: float(v) for k, v in qual.items() if v is not None} or None
        cE, cN, (info["entry_guard_left"], info["entry_guard_qual_left"]) = _df_entry_guard(
            M, gel, Uv, gmov, walln, E, ext, mc["corner"], float(cfg["quality"]["flip_deg"]), qual)
        if (cE < 1.0).any():
            un = (Uv @ M.n0)[:, None] * M.n0[None, :]
            Uv = un * cN[:, None] + (Uv - un) * cE[:, None]
            info["entry_guard_n"] = int((cE < 1.0).sum())
            info["entry_guard_wall_n"] = int((cN < 1.0).sum())
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
    n_oth = M.nmask(_others_el(M, Z, True))           # DM-33: parent-floor islands are obstacles (same set as the band)
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
    band, on_par = _band(M, Z, Rw, ent_o, Uv, info, mix_h=h, isl_obstacle=True)
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


def _others_el(M: Mesh, Z: dict, isl_obstacle: bool) -> np.ndarray:
    """"other shapes" element mask of the parent-floor band / DF entry gap: everything outside the parent floor, the bead
    floor / walls and the bead's islands. W (``isl_obstacle`` False): the parent's non-straddling islands are not
    others (they move rigidly with the band). DF·W1 (True — esl contract §1.2.1·§1.6.3, DM-33): every island on the
    parent floor is an obstacle (stays, the band fades next to it, the entry gap d_o sees it)."""
    others = ~(Z["parent_floor"] | Z["ZF"] | Z["ZW"] | Z["ZI"])
    if not isl_obstacle:
        isl = M.lab["island"]
        on_par = [i["id"] for i in M.graph["islands"] if i["parent"] == Z["parent"] and not i["straddle"]]
        others &= ~np.isin(isl, on_par)
    return others


def _band(M: Mesh, Z: dict, Rw: float, src_idx: np.ndarray, Uv: np.ndarray, info: dict, mix_h: float | None = None,
          isl_obstacle: bool = False, extra_oth: np.ndarray | None = None, gap_clip: bool = False,
          mix_rho: float | None = None):
    """parent-floor blend band (W·DF·W1 — one internal function, contract esl_bead_depth_mode §9): parent-floor nodes
    within R_w of the source entry nodes ``src_idx`` copy the nearest source displacement × (1 − smoothstep(d/R_w)),
    or — ``mix_h`` given (DF·W1, DM-C1-2) — the distance-weighted mix of the up to ``BAND_MIX_K`` nearest sources
    within R_w, w_k = 1/(d_k² + (0.1h)²) (continuous between facing entry lines; W keeps the nearest copy),
    clipped near other zones (SELECT_BLEND_CLIPPED); parent-floor islands touched by the band move rigidly with it (W) or
    — ``isl_obstacle`` (DF·W1, DM-33) — are other zones (stay, the band fades next to them; no ``band_islands``).
    ``extra_oth`` (U — node mask, e.g. the plate's outer edge): more obstacles of the same kind (None = as before).
    ``gap_clip`` (U): the clip next to other zones is the gap fraction d_o/(d_o + d_e) (1 at the entry, 0 at the
    obstacle — the motion fades linearly across the gap, so with the entry gap factor κ ≤ gap_rel·d_o/ext the band
    gradient stays ≤ gap_rel) instead of smoothstep(d_o/R_w) (False = as before). ``mix_rho`` (U): the mix weights are
    exp(−((d_k − d_min)/ρ)²) over up to BAND_MIX_K_U nearest sources (smooth at the motion scale ρ where sources of
    different directions meet — outside of bends) instead of 1/(d² + (0.1h)²).
    -> (band node mask, ids of the parent's non-straddling islands). Uv / info updated in place."""
    lab = M.lab
    p = Z["parent"]
    E, nF, nW = Z["E"], Z["nF"], Z["nW"]
    band = np.zeros(M.n, bool)
    pf = M.nmask(Z["parent_floor"]) & ~E & ~nF & ~nW
    isl = lab["island"]
    on_par = [i["id"] for i in M.graph["islands"] if i["parent"] == p and not i["straddle"]]
    n_oth = M.nmask(_others_el(M, Z, isl_obstacle))
    if extra_oth is not None:
        n_oth = n_oth | (np.asarray(extra_oth, bool) & ~E)
    pf &= ~n_oth
    info["blend_mm"] = Rw
    if src_idx.size and pf.any():
        cand = np.flatnonzero(pf)
        tree = cKDTree(M.P[src_idx])
        de, je = tree.query(M.P[cand])
        sel = de < Rw
        bidx = cand[sel]
        w = 1.0 - U.smoothstep(de[sel] / Rw)
        if mix_rho is not None and bidx.size:
            kk = min(BAND_MIX_K_U, int(src_idx.size))
            dk, jk = tree.query(M.P[bidx], k=kk)
            dk = dk.reshape(bidx.size, kk)
            jk = jk.reshape(bidx.size, kk)
            wk = np.exp(-((dk - dk[:, :1]) / mix_rho) ** 2)
            umix = np.einsum("ik,ikj->ij", wk, Uv[src_idx[np.minimum(jk, src_idx.size - 1)]]) / wk.sum(axis=1)[:, None]
        elif mix_h is not None and bidx.size:
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
            if gap_clip:
                w = w * np.where(do < Rw, do / np.maximum(do + de[sel], 1e-300), 1.0)
            else:
                w = w * U.smoothstep(do / Rw)
        if (mix_h is not None or mix_rho is not None) and bidx.size:
            Uv[bidx] = umix * w[:, None]
        else:
            Uv[bidx] = Uv[src_idx[je[sel]]] * w[:, None]
        band[bidx] = True
        if not isl_obstacle:
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


# ====================================================================== kind U (bead position — esl_bead_pos_u.md §1.1)
U_RANGE_REL = 0.25                              # ext without a range = U_RANGE_REL·W_ref (esl passes pos_u.range_rel)
U_GAP_REL = 0.5                                 # neighbour-gap limit (esl passes pos_u.gap_rel — same value as feasible)
U_DIR_RHO_H = 3.0                               # t⊥ gaussian smoothing radius ρ = max(U_DIR_RHO_H·h, ext) (U_RULES 1)
U_ACH_RAD = 0.005                               # achieved sample: motion within 0.005 rad of t⊥ (ext·(1 − cos) ≤ 2.5e-4 mm at 20 mm)
U_GAP_K = 64                                    # obstacle candidates per entry node (gap factor)
U_GAP_CONE_DEG = 45.0                           # obstacles within ±45° of the motion direction limit it
U_GUARD_CUT = 2.0                               # guard bump support = U_GUARD_CUT·ρ (exp(−4) step ≈ 0.4 % of the shrink)
U_SKEL_RHO_EXT = 4.0                            # skeleton-normal smoothing radius ρ_s = max(U_DIR_RHO_H·h, 4·ext) (U_RULES 1)


def _u_field(M, S, orient: dict, Q: np.ndarray, rho_s: float) -> np.ndarray:
    """t⊥ field from the bead's skeleton vertices (all segments of S, chain orientation σ): vertex left normals (central
    tangent; end vertices = end segment) smoothed by a plan gaussian of radius ρ_s over every vertex of S (cross-segment:
    kinks / channel–flare joins turn over ~ρ_s instead of one element), the query points take the smoothed normal of
    their nearest vertex. Straight stretches keep the exact perpendicular; a circular arc keeps the radial direction."""
    V, T = [], []
    for s in S:
        P = np.asarray(M.segs[s].get("skeleton") or [], float).reshape(-1, 2)
        if P.shape[0] < 2:
            continue
        t = np.empty_like(P)
        t[1:-1] = P[2:] - P[:-2]
        t[0], t[-1] = P[1] - P[0], P[-1] - P[-2]
        t *= float(orient.get(int(s), 1))
        n = np.c_[-t[:, 1], t[:, 0]]
        nn = np.linalg.norm(n, axis=1)
        ok = nn > 1e-12
        V.append(P[ok])
        T.append(n[ok] / nn[ok, None])
    if not V:
        return np.zeros((len(Q), 2))
    V, T = np.concatenate(V), np.concatenate(T)
    tv = cKDTree(V)
    if rho_s > 0 and V.shape[0] > 1:
        pr = tv.sparse_distance_matrix(tv, ENTRY_SMOOTH_CUT * rho_s, output_type="coo_matrix")
        W = sparse.coo_matrix((np.exp(-(pr.data / rho_s) ** 2), (pr.row, pr.col)), shape=(V.shape[0],) * 2).tocsr()
        W = W + sparse.identity(V.shape[0], format="csr") - sparse.diags(W.diagonal())
        Ts = np.asarray(W @ T)
        ns = np.linalg.norm(Ts, axis=1)
        same = np.linalg.norm(Ts / np.maximum(ns, 1e-12)[:, None] - T, axis=1) < 1e-12
        T = np.where(((ns > 1e-12) & ~same)[:, None], Ts / np.maximum(ns, 1e-12)[:, None], T)
    _d, j = tv.query(Q)
    return T[j]


def _u_smooth(M, idx: np.ndarray, t: np.ndarray, rho: float) -> np.ndarray:
    """t⊥ of the moving nodes relaxed by a plan gaussian (weights exp(−(d/ρ)²), support ENTRY_SMOOTH_CUT·ρ, self weight
    1) over the moving nodes, renormalised: continuous across skeleton kinks / segment joins at the motion scale; a
    straight stretch (all t⊥ equal) keeps the exact perpendicular."""
    n = idx.size
    if n < 2 or rho <= 0:
        return t
    tree = cKDTree(M.P[idx])
    pr = tree.sparse_distance_matrix(tree, ENTRY_SMOOTH_CUT * rho, output_type="coo_matrix")
    W = sparse.coo_matrix((np.exp(-(pr.data / rho) ** 2), (pr.row, pr.col)), shape=(n, n)).tocsr()
    W = W + sparse.identity(n, format="csr") - sparse.diags(W.diagonal())
    v = np.asarray(W @ t)
    nn = np.linalg.norm(v, axis=1)
    v = np.where(nn[:, None] > 1e-12, v / np.maximum(nn, 1e-12)[:, None], t)
    same = np.linalg.norm(v - t, axis=1) < 1e-12              # exact where the neighbourhood is uniform
    v[same] = t[same]
    return v


U_CLOSED_H = 2.0                                # closed skeleton: no junctions and |end − start| ≤ U_CLOSED_H·h


def u_closed(seg: dict, h: float) -> bool:
    """closed (loop) skeleton — graph.json segments carry no ``closed`` flag: no junction nodes and the skeleton's last
    point within U_CLOSED_H·h of its first (U_CLOSED — moving a loop sideways changes its size)."""
    P = np.asarray(seg.get("skeleton") or [], float).reshape(-1, 2)
    if P.shape[0] < 3 or seg.get("junctions"):
        return False
    return float(np.linalg.norm(P[-1] - P[0])) <= U_CLOSED_H * float(h)


def u_orient(segs_by_id: dict, S) -> dict:
    """one travel direction for the bead's skeleton chain: σ_s = ±1 per segment (+1 = as stored). Reference = the longest
    segment (ties: smallest id); the next segment is always the unassigned one with the nearest skeleton end to an assigned
    one, end→start / start→end = same direction, end→end / start→start = reversed (a straight ring side split into
    segments stored in opposite directions moves one way)."""
    ends = {}
    for s in S:
        P = np.asarray(segs_by_id[s].get("skeleton") or [], float).reshape(-1, 2)
        if P.shape[0] >= 2:
            ends[s] = (P[0], P[-1])
    if not ends:
        return {int(s): 1 for s in S}
    ref = sorted(ends, key=lambda s: (-float(segs_by_id[s].get("length") or 0.0), int(s)))[0]
    sig = {ref: 1}
    while len(sig) < len(ends):
        best = None
        for a, sa in sig.items():
            a0, a1 = ends[a] if sa > 0 else ends[a][::-1]
            for b in ends:
                if b in sig:
                    continue
                b0, b1 = ends[b]
                for d, sb in ((np.linalg.norm(a1 - b0), 1), (np.linalg.norm(a0 - b1), 1), (np.linalg.norm(a1 - b1), -1),
                              (np.linalg.norm(a0 - b0), -1)):
                    key = (float(d), int(b))
                    if best is None or key < best[0]:
                        best = (key, b, sb)
        sig[best[1]] = best[2]
    return {int(s): int(sig.get(s, 1)) for s in S}


def _u_skel(M, S: list[int], Q: np.ndarray, orient: dict | None = None):
    """U direction (U only — ``_skeleton_dist`` keeps its W bytes): nearest skeleton over S -> (distance, t⊥ (k,2) = the
    nearest skeleton segment's left normal × its chain orientation σ (``u_orient``), interior, segment id). Interior
    nodes: n_out × side (``polyline_dist``); end nodes (closest point = an open polyline's end vertex): the left normal of
    the end segment (not the radial n_out)."""
    best = np.full(len(Q), np.inf)
    tp = np.zeros((len(Q), 2))
    inner = np.zeros(len(Q), bool)
    sid = -np.ones(len(Q), np.int64)
    for s in S:
        sk = M.segs[s].get("skeleton")
        if not sk or len(sk) < 2:
            continue
        pts = np.asarray(sk, float)
        d, sd, cp, n = polyline_dist(Q, pts)
        im = interior_mask(cp, pts)
        t = n * sd[:, None]
        if (~im).any():
            for a, b, e in ((pts[0], pts[1], pts[0]), (pts[-2], pts[-1], pts[-1])):
                tt = b - a
                ln = float(np.linalg.norm(tt))
                if ln <= 1e-12:
                    continue
                left = np.array([-tt[1], tt[0]]) / ln
                at = (~im) & (np.linalg.norm(cp - e, axis=1) < 1e-9)
                t[at] = left
        if orient is not None and int(orient.get(int(s), 1)) < 0:
            t = -t
        m = d < best
        best[m], tp[m], inner[m], sid[m] = d[m], t[m], im[m], s
    nn = np.linalg.norm(tp, axis=1)
    tp = np.where(nn[:, None] > 1e-12, tp / np.maximum(nn, 1e-12)[:, None], tp)
    return best, tp, inner, sid


def u_dir(graph, segs, orient: dict | None = None) -> list[float] | None:
    """mean t⊥ of the segments' skeletons (length-weighted left normals × chain orientation, plan e1·e2 unit) — None for
    none / a loop."""
    num, tot = np.zeros(2), 0.0
    sg = {s["id"]: s for s in graph["segments"]}
    for s in segs:
        P = np.asarray(sg[s].get("skeleton") or [], float).reshape(-1, 2)
        if P.shape[0] < 2:
            continue
        t = np.diff(P, axis=0) * float((orient or {}).get(int(s), 1))
        num += np.c_[-t[:, 1], t[:, 0]].sum(axis=0)
        tot += float(np.linalg.norm(t, axis=1).sum())
    nv = float(np.linalg.norm(num))
    if tot <= 0.0 or nv <= 1e-9 * tot:
        return None
    return [float(x) for x in num / nv]


def _u_gap(M: Mesh, eI: np.ndarray, mI: np.ndarray, oth: np.ndarray, ends, tE: np.ndarray, gap: float, rho: float,
           phiE: np.ndarray | None = None):
    """neighbour-gap factor (DF ``_entry_fix`` κ_o rule, U motion = ext along t⊥): raw κ_e = min(1, gap·d_o/ext) at the
    entry nodes eI, d_o = plan distance to the other shapes ``oth`` (node mask); eroded (min over entries within
    U_GUARD_CUT·ρ) then the moving nodes mI get the gaussian mean of it (weights exp(−(d/ρ)²), same support — nearest
    entry where none in range): one smooth factor for the whole cross-section (walls / floor edge / entry move together),
    never above the raw factor of an entry within the support. -> (κ over mI, n raw κ < 1)."""
    n = mI.size
    lo, hi = (float(v) for v in ends)
    if eI.size == 0 or not oth.any() or max(abs(lo), abs(hi)) <= 0:
        return np.ones(n), 0
    oi = np.flatnonzero(oth)
    kk = min(U_GAP_K, oi.size)
    dk, jk = cKDTree(M.P[oi]).query(M.P[eI], k=kk)
    dk, jk = dk.reshape(eI.size, kk), jk.reshape(eI.size, kk)
    vec = M.P[oi[jk]] - M.P[eI][:, None, :]
    cs = np.einsum("ikj,ij->ik", vec, tE) / np.maximum(dk, 1e-12)
    cone = float(np.cos(np.radians(U_GAP_CONE_DEG)))
    d_p = np.where(cs >= cone, dk, np.inf).min(axis=1)       # obstacle ahead of the + motion
    d_m = np.where(cs <= -cone, dk, np.inf).min(axis=1)      # … of the − motion
    ph = np.ones(eI.size) if phiE is None else np.maximum(np.asarray(phiE, float), 1e-300)
    raw = np.minimum.reduce([np.ones(eI.size), gap * d_p / (max(abs(hi), 1e-300) * ph),
                             gap * d_m / (max(abs(lo), 1e-300) * ph)])
    n_clip = int((raw < 1.0).sum())
    if not n_clip:
        return np.ones(n), 0
    te = cKDTree(M.P[eI])
    R = U_GUARD_CUT * rho
    pe = te.sparse_distance_matrix(te, R, output_type="coo_matrix")
    ero = raw.copy()                                    # erosion (min over entries within R) — the smoothed factor
    np.minimum.at(ero, pe.row, raw[pe.col])              # below stays ≤ the raw factor of every entry within R
    pr = cKDTree(M.P[mI]).sparse_distance_matrix(te, R, output_type="coo_matrix")
    W = sparse.coo_matrix((np.exp(-(pr.data / rho) ** 2), (pr.row, pr.col)), shape=(n, eI.size)).tocsr()
    den = np.asarray(W.sum(axis=1)).ravel()
    kap = np.asarray(W @ ero).ravel() / np.maximum(den, 1e-300)
    none = den <= 1e-300
    if none.any():
        _dn, jn = te.query(M.P[mI[none]])
        kap[none] = ero[jn]
    return np.minimum(kap, 1.0), n_clip


def u_gaps(graph, labels, nodes, elems, segs, zones=(), fixed=None, hold_nodes=(), q: float = 0.05,
           range_rel: float = U_RANGE_REL, cfg=None) -> dict:
    """U feasible inputs (esl contract esl_bead_pos_u.md §1.3): for the S_U segments -> {w_ref, dir [e1, e2], orient,
    g_plus, g_minus (mm | None — the q-quantile of the plan distance from that side's straight entry nodes to the nearest
    "other shape" node: other zones, the plate's outer edge, fixed / held nodes, held islands — the same obstacle set as
    the basis gap factor), n_plus, n_minus}. + side = left of the oriented travel direction. Straight sample = interior
    entry nodes (skeleton perpendicular) at least the full ramp L = ramp_k·max(h, range_rel·W_ref) from the junction
    nodes J (the default-range ramp)."""
    from .oneside import outer_edge_nodes
    M = Mesh(graph, labels, np.asarray(nodes, np.float64), elems)
    Z = bead_zones(M, list(segs), zones or (), "D")
    S = Z["S"]
    lens = np.array([float(M.segs[x]["length"] or 1.0) for x in S])
    ws = [M.segs[x]["entry_width"] for x in S]
    w_ref = None if any(w is None for w in ws) else float(np.sum(lens * np.array(ws, float)) / lens.sum())
    orient = u_orient(M.segs, S)
    fx = np.zeros(M.n, bool)
    for arr in (fixed, hold_nodes):
        a = np.asarray(arr if arr is not None else [], np.int64)
        fx[a[(a >= 0) & (a < M.n)]] = True
    isl = M.lab["island"]
    held = [i for i in Z["islands"] if fx[M.nmask(isl == i)].any()]
    E = Z["E"]
    obst = outer_edge_nodes(M) | fx | (M.nmask(np.isin(isl, held)) if held else np.zeros(M.n, bool))
    oth = (M.nmask(_others_el(M, Z, True) & ~Z["ZC"]) | obst) & ~E
    out = {"w_ref": w_ref, "orient": {int(k): int(v) for k, v in orient.items()}, "dir": u_dir(graph, S, orient),
           "g_plus": None, "g_minus": None, "n_plus": 0, "n_minus": 0}
    ei = np.flatnonzero(E)
    if ei.size == 0 or not oth.any():
        return out
    _d, tp, inner, sid = _u_skel(M, S, M.P[ei], orient)
    ok = inner & (sid >= 0)
    if Z["J"].any() and w_ref is not None:
        c = _cfg(cfg)
        L0 = float(c["morph"]["ramp_k"]) * max(M.h_mm, float(range_rel) * w_ref)
        dj, _ = cKDTree(M.P[Z["J"]]).query(M.P[ei])
        ok &= dj >= L0
    ei, tp = ei[ok], tp[ok]
    if ei.size == 0:
        return out
    cp = np.zeros((ei.size, 2))
    for s in set(int(x) for x in sid[ok]):
        m = sid[ok] == s
        cp[m] = polyline_dist(M.P[ei[m]], np.asarray(M.segs[s]["skeleton"], float))[2]
    side = np.sign(np.einsum("ij,ij->i", M.P[ei] - cp, tp))
    d_o, _ = cKDTree(M.P[oth]).query(M.P[ei])
    for sg, k in ((1.0, "plus"), (-1.0, "minus")):
        m = side == sg
        out[f"n_{k}"] = int(m.sum())
        if m.any():
            out[f"g_{k}"] = float(np.quantile(d_o[m], q))
    return out


def _u_flags(M: Mesh, eidx: np.ndarray, Ud: np.ndarray, ends, cg: dict, flip_deg: float, qual: dict | None):
    """elements (rows eidx) bad at the range ends (values ``ends`` — the default range, asymmetric) under Ud — the DF entry guard criteria (``_df_entry_guard``): floor plan triangle
    area ratio < area_ratio_min, normal turned > flip_deg, quad Gauss Jacobian ≤ 0 (> 0 at rest), concave quad corner
    (``quad_corner_min`` on the element plane or about its rest normal, > 0 at rest), ``qual`` newly bad. -> (bad,
    concave-or-inverted only)."""
    from .checks import _quad_jacobian, quad_corner_min
    C = M.C[eidx]
    q = C[:, 3] >= 0
    isfloor = M.lab["cls"][eidx] == CLS["floor"]
    T = np.r_[C[:, :3], C[q][:, [0, 2, 3]]]
    Tow = np.r_[np.arange(eidx.size), np.flatnonzero(q)]

    def parea(P):
        a, b, d = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        return 0.5 * ((b[:, 0] - a[:, 0]) * (d[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (d[:, 0] - a[:, 0]))

    def normals(X):
        a, b, d = X[C[:, 0]], X[C[:, 1]], X[C[:, 2]]
        n = np.cross(b - a, d - a)
        e = X[np.where(q, C[:, 3], C[:, 2])]
        n[q] = np.cross(d[q] - a[q], e[q] - b[q])
        return n / np.maximum(np.linalg.norm(n, axis=1), 1e-300)[:, None]
    a0 = parea(M.P)
    ok0 = np.abs(a0) > 1e-9
    n0 = normals(M.X)
    Cq = C[q]
    if q.any():
        j0 = _quad_jacobian(M.X, Cq)
        nq0 = np.cross(M.X[Cq[:, 2]] - M.X[Cq[:, 0]], M.X[Cq[:, 3]] - M.X[Cq[:, 1]])
        cq0 = (quad_corner_min(M.X, Cq) > 0.0) & (quad_corner_min(M.X, Cq, nq0) > 0.0)
    bad = np.zeros(eidx.size, bool)
    hard = np.zeros(eidx.size, bool)
    for v in ends:
        X1 = M.X + float(v) * Ud
        P1 = np.c_[X1 @ M.e1, X1 @ M.e2] - M.origin
        r = parea(P1) / np.where(ok0, a0, 1.0)
        bt = np.zeros(eidx.size, bool)
        np.logical_or.at(bt, Tow[ok0 & (r < float(cg["area_ratio_min"]))], True)
        bad |= bt & isfloor
        inv = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", n0, normals(X1)), -1, 1))) > flip_deg
        if q.any():
            inv[q] |= (_quad_jacobian(X1, Cq) <= 0.0) & (j0 > 0.0)
            inv[q] |= cq0 & (np.minimum(quad_corner_min(X1, Cq), quad_corner_min(X1, Cq, nq0)) <= 0.0)
        hard |= inv
    bad |= hard
    if qual:
        bad |= _qual_new_bad(M, C, Ud, 1.0, qual, vals=ends)
    return bad, hard


def _u_guard(M: Mesh, Uv: np.ndarray, ends, cg: dict, flip_deg: float, qual: dict | None, rho: float):
    """U quality guard: the DF entry guard criteria (``_u_flags``) on every element the variable moves; a flagged
    element shrinks the plan motion by a smooth bump c ×= 1 − (1 − shrink)·exp(−(d/ρ)²) around its centroid (d = plan
    distance, support U_GUARD_CUT·ρ) — per-node shrinking (DF) cascades under the U motion (a 20 % step between
    neighbours of 1 mm under 9 mm of motion folds the next element). Up to ``cg["iters"]`` passes; the factor is frozen
    in the basis (linear). -> (factor c, flagged elements left, of which inverted / concave)."""
    c = np.ones(M.n)
    shrink = float(cg["shrink"])
    left = (0, 0)
    for _ in range(int(cg["iters"])):
        Ud = Uv * c[:, None]
        mvd = np.any(Ud != 0.0, axis=1)
        eidx = np.flatnonzero(M.emask_of_nodes(mvd))
        if eidx.size == 0:
            return c, (0, 0)
        bad, hard = _u_flags(M, eidx, Ud, ends, cg, flip_deg, qual)
        left = (int(bad.sum()), int(hard.sum()))
        if not bad.any():
            return c, (0, 0)
        ctr = M.Pc[eidx[bad]]
        nd = np.flatnonzero(mvd)
        pr = cKDTree(M.P[nd]).sparse_distance_matrix(cKDTree(ctr), U_GUARD_CUT * rho, output_type="coo_matrix")
        bump = np.zeros(nd.size)
        np.maximum.at(bump, pr.row, np.exp(-(pr.data / rho) ** 2))
        # nodes of a flagged element itself get the full step (a bump of 1 at their element centroid ~ 1)
        own = np.unique(M.C[eidx[bad]][M.C[eidx[bad]] >= 0])
        pos = -np.ones(M.n, np.int64)
        pos[nd] = np.arange(nd.size)
        po = pos[own]
        bump[po[po >= 0]] = 1.0
        c[nd] *= 1.0 - (1.0 - shrink) * bump
    return c, left


def _one_u(M: Mesh, b: dict, ranges: dict, cfg: dict, fixed_mask: np.ndarray, edge_n: np.ndarray) -> dict:
    """kind U (esl contract esl_bead_pos_u.md §1.1, PU-1·14): the whole bead moves along t⊥ (left normal of the nearest
    skeleton segment — end segments' normal at the ends). Item keys: name, kind "U", segs (S_U — every segment needs
    entry lines on both sides), zones?, hold_nodes? (extra held nodes — jig tie), range_rel?, gap_rel?, guard_jac_min?,
    guard_tri_angle_min_deg?. Nominal 0, ext = range end max |ΔU| (else range_rel·W_ref).
    Entry ∪ walls ∪ floor edge = t⊥ (both sides the same way — ``_smooth_dirs`` relaxed), floor interior = in-plane
    harmonic extension, exclusive children (+ their islands) and the bead's owned islands = rigid with the bead (Dirichlet
    value = t⊥ at their centroid, PU-A0), shared-child walls / J / other beads = 0 (ramp φ, L = ramp_k·max(ext, h)), parent
    floor band both sides = distance-weighted mix of the entry values × (1 − smoothstep(d/R_w)), R_w = max(min_mm, k·ext,
    3h), parent-floor islands + the plate's outer edge = obstacles; hold ψ always on (fixed ∪ hold_nodes); neighbour-gap
    factor κ (gap_rel); quality guard (``_df_entry_guard`` — inversion · area ratio · concave quads · range-guard
    criteria) on every element the variable moves. Normal component 0."""
    Z = bead_zones(M, b["segs"], b.get("zones") or (), "D")
    lab = M.lab
    S = Z["S"]
    ws = [M.segs[x]["entry_width"] for x in S]
    if any(w is None for w in ws):
        raise ValueError(f"bead {b['name']}: U needs entry lines on both sides for every segment")
    bad = [x for x in S if len(M.segs[x].get("skeleton") or []) < 2 or u_closed(M.segs[x], M.h_mm)]
    if bad:
        raise ValueError(f"bead {b['name']}: U needs an open skeleton with a direction ({bad}: closed / one point)")
    lens = np.array([float(M.segs[x]["length"] or 1.0) for x in S])
    w_ref = float(np.sum(lens * np.array(ws, float)) / lens.sum())
    mc = cfg["morph"]
    h = max(M.h_mm, 1e-6)
    rng = ranges.get(b["name"]) if ranges else None
    ends = (float(rng[0]), float(rng[1])) if rng else (-float(b.get("range_rel", U_RANGE_REL)) * w_ref,
                                                         float(b.get("range_rel", U_RANGE_REL)) * w_ref)
    ext = max(abs(ends[0]), abs(ends[1]))
    L = max(float(mc["ramp_k"]) * ext, float(mc["ramp_k"]) * h)
    info = {"ramp_mm": L, "ext": ext, "ends": [ends[0], ends[1]], "sign": 1.0, "warnings": [], "shared_children": Z["shared"],
            "children": Z["exclusive"], "islands": Z["islands"], "straddle": list(Z["straddle"]),
            "zones_in": Z["zones_in"], "w_ref": w_ref, "u_segs": list(S)}
    orient = u_orient(M.segs, S)
    info["orient"] = {int(k): int(v) for k, v in orient.items()}
    info["dir"] = u_dir(M.graph, S, orient)
    nF, nW, E, J = Z["nF"], Z["nW"], Z["E"], Z["J"]
    ZF, ZW, ZC, ZSC, ZI = Z["ZF"], Z["ZW"], Z["ZC"], Z["ZSC"], Z["ZI"]
    nC, nSC = M.nmask(ZC), M.nmask(ZSC)
    isl = lab["island"]
    hold_n = np.asarray(b.get("hold_nodes") or [], np.int64)
    fx_u = fixed_mask.copy()                            # U hold set = fixed ∪ hold_nodes (jig tie — PU-14)
    if hold_n.size:
        fx_u[hold_n[(hold_n >= 0) & (hold_n < M.n)]] = True
    held_isl = [i for i in Z["islands"] if fx_u[M.nmask(isl == i)].any()]       # stay (BG_ISLAND_HELD)
    # the bead's islands (owned and straddling — U moves the whole bead, flanks included) are rigid with the bead unless
    # held; they are band sources too (the parent floor next to them follows them)
    own_isl = [i for i in Z["islands"] if i not in held_isl and not M.islands[i]["straddle"]]
    st_isl = [i for i in Z["islands"] if i not in held_isl and M.islands[i]["straddle"]]
    Uv = np.zeros((M.n, 3))
    edge = nF & nW & ~E
    walln = nW & ~E & ~nF
    hm = edge | walln
    mv = E | hm
    idx = np.flatnonzero(mv)
    _d, traw, inner_mv, _sid = _u_skel(M, S, M.P[idx], orient)
    tref = _u_field(M, S, orient, M.P[idx], max(U_DIR_RHO_H * h, U_SKEL_RHO_EXT * ext))
    tref = np.where((np.linalg.norm(tref - traw, axis=1) < 1e-9)[:, None], traw, tref)   # exact where straight
    tsm = _u_smooth(M, idx, tref, max(U_DIR_RHO_H * h, ext))     # ρ = max(3h, ext)
    Uv[idx] = _plan3(M, tsm)
    straight = np.zeros(M.n, bool)
    # straight sample: the motion direction within U_ACH_RAD of the skeleton perpendicular (projection error at ext ≤
    # ext·(1 − cos) ≤ the achieved tolerance share)
    straight[idx[np.einsum("ij,ij->i", tsm, traw) >= np.cos(U_ACH_RAD)]] = True
    # rigid followers: exclusive children (each subtree) and owned islands — t⊥ at their plan centroid (Dirichlet value)
    val = np.zeros(M.n, bool)
    groups = []
    for c in Z["exclusive"]:
        sub = [c] + M.descendants(c)
        ge = ZC & (np.isin(lab["floor"], sub) | M.emask_of_nodes(M.nmask(np.isin(lab["floor"], sub) & ZC)))
        groups.append(M.nmask(ge) & nC & ~mv)
    rest = nC & ~mv
    for g_ in groups:
        rest &= ~g_
    if rest.any():
        groups.append(rest)
    isl_n = np.zeros(M.n, bool)
    for i_ in own_isl:
        gi = M.nmask(isl == i_) & ~mv
        groups.append(gi)
        isl_n |= gi
    rho = max(U_DIR_RHO_H * h, ext)
    fol = np.zeros(M.n, bool)
    for g_ in groups:
        fol |= g_
    if fol.any():                                       # followers take the smoothed t⊥ field at their own position
        fi = np.flatnonzero(fol)
        tm_ = cKDTree(M.P[idx])
        kk = min(BAND_MIX_K_U, idx.size)
        dk, jk = tm_.query(M.P[fi], k=kk)
        dk, jk = dk.reshape(fi.size, kk), jk.reshape(fi.size, kk)
        wk = np.exp(-((dk - dk[:, :1]) / rho) ** 2)
        tf = np.einsum("ik,ikj->ij", wk, tsm[jk]) / wk.sum(axis=1)[:, None]
        tf /= np.maximum(np.linalg.norm(tf, axis=1), 1e-12)[:, None]
        Uv[fi] = _plan3(M, tf)
        val |= fol
    # neighbour-gap factor κ (entry, same value along each column: walls / floor edge follow their nearest entry node)
    ent_idx = np.flatnonzero(E)
    gap = float(b.get("gap_rel", U_GAP_REL))
    # obstacles: other zones (not the bead's own children), the plate's outer edge, held nodes and held islands
    obst = edge_n | fx_u | (M.nmask(np.isin(isl, held_isl)) if held_isl else np.zeros(M.n, bool))
    oth = M.nmask(_others_el(M, Z, True) & ~ZC) | (obst & ~E)
    kap = np.ones(M.n)
    info["gap_clip_n"] = 0
    if ent_idx.size:
        pe = -np.ones(M.n, np.int64)
        pe[idx] = np.arange(idx.size)
        phiE = _ramp(M, J, ent_idx, L)[ent_idx] if J.any() else None
        kap[idx], info["gap_clip_n"] = _u_gap(M, ent_idx, idx, oth, ends, tsm[pe[ent_idx]], gap, rho, phiE)
        Uv[idx] *= kap[idx, None]
    # parent blend band (both sides, distance-weighted mix, islands + outer edge = obstacles)
    bl = cfg["blend"]
    Rw = max(float(bl["min_mm"]), float(bl["k"]) * ext, 3.0 * h)
    pre = Uv[isl_n].copy()
    band, _on_par = _band(M, Z, Rw, np.flatnonzero(E | isl_n), Uv, info, mix_h=h, isl_obstacle=True, extra_oth=obst,
                          gap_clip=True, mix_rho=rho)
    Uv[isl_n] = pre
    band &= ~isl_n
    info["clipped"] = any(w.get("code") == "SELECT_BLEND_CLIPPED" for w in info["warnings"])
    info["band_mm"] = Rw
    # in-plane harmonic extension over the floor: Dirichlet 0 (shared-child walls, J, outside) / values (edges, children,
    # owned islands)
    Lf = M.laplacian(ZF)
    # J is not a Dirichlet 0 here (the ramp φ takes the motion to 0 at J smoothly — a harmonic 0 at J plus φ doubles the
    # gradient next to junctions)
    zero = (nSC | M.nmask(~(ZF | ZW)) & ~E) & ~val & ~(J & nF)
    free = nF & ~hm & ~E & ~zero & ~val
    Up = np.c_[Uv @ M.e1, Uv @ M.e2, np.zeros(M.n)]
    Up[zero & ~mv] = 0.0
    Up[free] = 0.0
    Up = _harmonic(Lf, free, Up, cols=(0, 1))
    Uv[free] = _plan3(M, Up[free, :2])
    Uv[zero & ~mv & ~band] = 0.0
    A_el = _allowed_wide(M, Z)
    allowed_n = M.nmask(A_el) | band
    mov = movable_nodes(M, A_el)
    psi, n_hold = _hold(M, allowed_n, fx_u, cfg)        # U: hold always on (PU-14)
    phi = _ramp(M, J, np.flatnonzero(allowed_n), L)
    Uv *= (phi * psi)[:, None]
    Uv[J] = 0.0
    # straddling islands (bead flank ↔ foreign floor / step): the island rule BG-D-27·47 (rigid core, contact band to 0);
    # held islands: BG_ISLAND_HELD (they stay — obstacles above)
    _islands(M, dict(Z, islands=sorted(st_isl + held_isl)), dict(b, hold=1), Uv, info, nF | band | mv, nW, mov, fx_u)
    Uv[~(allowed_n & mov)] = 0.0
    Uv -= (Uv @ M.n0)[:, None] * M.n0[None, :]          # normal component 0 (depth unchanged)
    # quality guard (DF entry guard device, every element the variable moves)
    gmov = np.any(Uv != 0.0, axis=1)
    info["guard_n"] = info["guard_left"] = info["guard_qual_left"] = 0
    info["guard_frac"] = 0.0
    cE = np.ones(M.n)
    if gmov.any() and ext > 0:
        qual = {"jac_min": b.get("guard_jac_min"), "tri_angle_min_deg": b.get("guard_tri_angle_min_deg")}
        qual = {k: float(v) for k, v in qual.items() if v is not None} or None
        cE, (n_left, n_hard) = _u_guard(M, Uv, ends, mc["corner"], float(cfg["quality"]["flip_deg"]), qual, rho)
        info["guard_left"], info["guard_qual_left"] = n_hard, n_left - n_hard
        if (cE < 1.0).any():
            Uv *= cE[:, None]
            info["guard_n"] = int((cE < 1.0).sum())
            info["guard_frac"] = float(info["guard_n"] / max(int(gmov.sum()), 1))
            info["warnings"].append({"code": "PU_GUARD", "level": "info", "n_nodes": info["guard_n"],
                                     "frac": U.f3(info["guard_frac"])})
    # achieved: entry nodes on straight interior stretches at full ramp / hold / κ / guard (both sides)
    ai = np.flatnonzero(E & straight & (phi >= 1.0) & (psi >= 1.0) & (kap >= 1.0) & (cE >= 1.0))
    mid = np.zeros(M.n, bool)
    if ai.size:
        _da, _ta, inn, _sa = _u_skel(M, S, M.P[ai], orient)
        mid[ai[inn]] = True
    info["achieved_idx"] = np.flatnonzero(mid)
    if not mid.any():
        info["warnings"].append({"code": "BG_SEGMENT_SHORT", "length_mm": U.f3(lens.sum()), "ramp_mm": U.f3(L)})
        info["short"] = True
        info["straight_resid_mm"] = None
    else:
        mi = np.flatnonzero(mid)
        _dm, tm, _im, _sm = _u_skel(M, S, M.P[mi], orient)
        info["straight_resid_mm"] = U.f3(float(np.linalg.norm(Uv[mi] - _plan3(M, tm), axis=1).max()) * ext)
    info["hold_n_fixed"] = n_hold
    ne = int(E.sum())
    info["hold_frac"] = float(((E & (psi < 1.0)).sum()) / max(ne, 1))
    info["tie_max"] = float(np.linalg.norm(Uv[hold_n[(hold_n >= 0) & (hold_n < M.n)]], axis=1).max()) \
        if hold_n.size else 0.0
    info["band_n"] = int(band.sum())
    info["corner_n"] = 0
    nz = np.flatnonzero(np.any(Uv != 0.0, axis=1))
    return {"name": b["name"], "kind": "U", "nominal": 0.0, "idx": nz.astype(np.int64), "vec": Uv[nz],
            "zone": np.flatnonzero(allowed_n).astype(np.int64), "info": info, "segs": list(S),
            "zones": sorted(int(z) for z in (b.get("zones") or ()))}
