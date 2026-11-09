"""Segment morph: per-variable linear basis B_v (contract §4, BG-D-23..34), x = x0 + Σ (v − v_nom)·B_v.

Values that would depend on the variable value (ramp length, corner-guard factors) are fixed once at the default range
ends and frozen in the basis (BG-D-24·26), so the morph stays linear.

D (relative depth, D1/D3): walls + floor edge = 3D homothety about the nearest entry node (45° flank kept, entry fixed,
the floor narrows by ΔD per side); floor interior = s·ΔD·n0 with an in-plane harmonic extension; exclusive children
(Z_C) follow rigidly; shared children stay and their walls on the bead side absorb the height change (BG_SHARED_CHILD);
owned / straddling islands rigid (straddling: contact band to a foreign floor smoothed to 0 — D6).
W (entry width): walls + floor edge + entry translate ΔW/2 along the outward skeleton normal; floor interior harmonic
(children stay); parent-floor blend band R_w.
All displacements × junction ramp φ = smoothstep(d_J / L), L = max(ramp_k·ΔD_ext, ramp_k·h) (D4) × fixed-node hold ψ
(SR-D-9 ring + Wendland blend, D6). Outside the allowed zone A_v the basis is exactly 0 (BG-D-32·34).
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu
from scipy.spatial import cKDTree

from . import _util as U
from .absorb import interior_mask, polyline_dist
from .classify import CLS
from .defaults import MORPH_EXTRA
from .zones import Mesh, bead_zones


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
    best = np.full(len(Q), np.inf)
    nout = np.zeros((len(Q), 2))
    inner = np.zeros(len(Q), bool)
    for s in S:
        sk = M.segs[s].get("skeleton")
        if not sk:
            continue
        pts = np.asarray(sk, float)
        d, _side, cp, n = polyline_dist(Q, pts)
        im = interior_mask(cp, pts)
        m = d < best
        best[m], nout[m], inner[m] = d[m], n[m], im[m]
    return best, nout, inner


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
    beads = [{name, kind 'D'|'W', segs [segment id…], zones? [junction-zone id…], hold 0|1}];
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
    for b in beads:
        out.append(_one(M, b, ranges, cfg, fixed_mask))
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
        pf = M.nmask(Z["parent_floor"]) & ~E & ~nF & ~nW
        others = ~(Z["parent_floor"] | ZF | ZW | ZI)
        isl = lab["island"]
        on_par = [i["id"] for i in M.graph["islands"] if i["parent"] == p and not i["straddle"]]
        others &= ~np.isin(isl, on_par)
        n_oth = M.nmask(others)
        pf &= ~n_oth
        info["blend_mm"] = Rw
        if ent_idx.size and pf.any():
            cand = np.flatnonzero(pf)
            de, je = cKDTree(M.P[ent_idx]).query(M.P[cand])
            sel = de < Rw
            bidx = cand[sel]
            w = 1.0 - U.smoothstep(de[sel] / Rw)
            if n_oth.any():
                do, _ = cKDTree(M.P[n_oth]).query(M.P[bidx])
                clip = do < Rw
                if clip.any():
                    info["warnings"].append({"code": "SELECT_BLEND_CLIPPED", "R_mm": U.f3(Rw),
                                             "d_other_mm": U.f3(float(do.min()))})
                w = w * U.smoothstep(do / Rw)
            Uv[bidx] = Uv[ent_idx[je[sel]]] * w[:, None]
            band[bidx] = True
            # parent-floor islands touched by the band move rigidly with it
            bi = np.unique(isl[M.emask_of_nodes(band) & (isl >= 0)])
            info["band_islands"] = [int(x) for x in bi if int(x) in on_par]
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
    # islands rigid (BG-D-29) — straddling ones with the foreign contact band (BG-D-27)
    isl = lab["island"]
    island_ids = list(Z["islands"]) + list(info.get("band_islands", []))
    rim_src = nF | band
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
            fn = M.nmask(foreign_floor)
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
    # exact zero outside A_v (structural — BG-D-32 checks the same)
    Uv[~allowed_n] = 0.0
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
            "zone": np.flatnonzero(allowed_n).astype(np.int64), "info": info, "segs": list(S)}


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
