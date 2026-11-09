"""Segments of a floor piece (BG-D-11): raster (plan) -> Zhang-Suen skeleton -> branch graph -> split at junctions (T/X),
bends (L) and width jumps (W: flare / widened corner).  numpy / scipy only."""
from __future__ import annotations

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

_K = np.array([[128, 1, 2], [64, 0, 4], [32, 16, 8]], np.int32)
_K8 = np.ones((3, 3), np.int32)


def _bits(c):
    return [(c >> i) & 1 for i in range(8)]       # P2 N, P3 NE, P4 E, P5 SE, P6 S, P7 SW, P8 W, P9 NW


def _luts():
    l1 = np.zeros(256, bool)
    l2 = np.zeros(256, bool)
    cross = np.zeros(256, np.int8)
    for c in range(256):
        p = _bits(c)
        B = sum(p)
        A = sum(1 for i in range(8) if p[i] == 0 and p[(i + 1) % 8] == 1)
        cross[c] = A
        P2, P3, P4, P5, P6, P7, P8, P9 = p
        base = 2 <= B <= 6 and A == 1
        l1[c] = base and P2 * P4 * P6 == 0 and P4 * P6 * P8 == 0
        l2[c] = base and P2 * P4 * P8 == 0 and P2 * P6 * P8 == 0
    return l1, l2, cross


_L1, _L2, _CROSS = _luts()


_OFFS = ((-1, 0, 1), (-1, 1, 2), (0, 1, 4), (1, 1, 8), (1, 0, 16), (1, -1, 32), (0, -1, 64), (-1, -1, 128))
_POP = np.array([bin(c).count("1") for c in range(256)], np.int8)


def _codes(P: np.ndarray, r: np.ndarray, c: np.ndarray) -> np.ndarray:
    """8-neighbour bit code (same bits as correlating with _K) of pixels (r, c) of the 1-padded image P."""
    code = np.zeros(r.size, np.int32)
    for dr, dc, bit in _OFFS:
        code += P[r + dr, c + dc].astype(np.int32) * bit
    return code


def thin(img: np.ndarray) -> np.ndarray:
    """Zhang–Suen thinning + L-staircase clean-up, evaluated on the foreground pixels only (same result as the
    full-image correlation version — O(foreground) per sweep)."""
    P = np.zeros((img.shape[0] + 2, img.shape[1] + 2), np.uint8)
    P[1:-1, 1:-1] = img.astype(bool)
    r, c = np.nonzero(P)
    while True:
        changed = False
        for lut in (_L1, _L2):
            keep = P[r, c] == 1
            r, c = r[keep], c[keep]
            rem = lut[_codes(P, r, c)]
            if rem.any():
                P[r[rem], c[rem]] = 0
                changed = True
        if not changed:
            break
    keep = P[r, c] == 1
    r, c = r[keep], c[keep]
    for b0, b1 in ((1, 4), (4, 16), (16, 64), (64, 1)):
        code = _codes(P, r, c)
        cand = ((code & b0) > 0) & ((code & b1) > 0) & (_CROSS[code] == 1) & (_POP[code] >= 2)
        par = ((r - 1) + (c - 1)) & 1
        for pp in (0, 1):
            sub = cand & (par == pp) & (P[r, c] == 1)
            if sub.any():
                rs, cs = r[sub], c[sub]
                code2 = _codes(P, rs, cs)
                ok = (_CROSS[code2] == 1) & ((code2 & b0) > 0) & ((code2 & b1) > 0)
                P[rs[ok], cs[ok]] = 0
        keep = P[r, c] == 1
        r, c = r[keep], c[keep]
    return P[1:-1, 1:-1].astype(bool)


def rasterize(P2: np.ndarray, tris: np.ndarray, origin, res: float, shape) -> np.ndarray:
    img = np.zeros(shape, bool)
    if tris.size == 0:
        return img
    A, B, C = P2[tris[:, 0]], P2[tris[:, 1]], P2[tris[:, 2]]
    lo = np.minimum(np.minimum(A, B), C)
    hi = np.maximum(np.maximum(A, B), C)
    i0 = np.floor((lo - origin) / res - 0.5).astype(int)
    i1 = np.ceil((hi - origin) / res - 0.5).astype(int)
    w = int(max(1, (i1 - i0).max() + 1))
    v0, v1 = B - A, C - A
    den = v0[:, 0] * v1[:, 1] - v0[:, 1] * v1[:, 0]
    good = np.abs(den) > 1e-12
    A, v0, v1, den, i0 = A[good], v0[good], v1[good], den[good], i0[good]
    for dx in range(w + 1):
        for dy in range(w + 1):
            ix = i0[:, 0] + dx
            iy = i0[:, 1] + dy
            px = origin[0] + (ix + 0.5) * res - A[:, 0]
            py = origin[1] + (iy + 0.5) * res - A[:, 1]
            u = (px * v1[:, 1] - py * v1[:, 0]) / den
            v = (v0[:, 0] * py - v0[:, 1] * px) / den
            ins = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
            ins &= (ix >= 0) & (iy >= 0) & (ix < shape[1]) & (iy < shape[0])
            img[iy[ins], ix[ins]] = True
    return img


def _order_chain(pix: np.ndarray) -> np.ndarray:
    """order 8-connected chain pixels (k, 2) [row, col].  Open chains: BFS double sweep -> path between the two ends
    (staircase side pixels are skipped).  Closed loops (no end pixel): greedy walk."""
    if len(pix) <= 2:
        return pix
    s = {(int(r), int(c)): i for i, (r, c) in enumerate(pix)}
    nbs = []
    for r, c in pix:
        lst = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if (dr or dc) and (r + dr, c + dc) in s:
                    lst.append(s[(r + dr, c + dc)])
        nbs.append(lst)
    deg = np.array([len(x) for x in nbs])

    def bfs(src):
        dist = -np.ones(len(pix), np.int64)
        pred = -np.ones(len(pix), np.int64)
        dist[src] = 0
        q = [src]
        h = 0
        while h < len(q):
            u = q[h]
            h += 1
            for v in nbs[u]:
                if dist[v] < 0:
                    dist[v] = dist[u] + 1
                    pred[v] = u
                    q.append(v)
        return dist, pred
    if (deg <= 1).any():
        d0, _ = bfs(int(np.flatnonzero(deg <= 1)[0]))
        a = int(np.argmax(d0))
        d1, pr = bfs(a)
        b = int(np.argmax(d1))
        path = [b]
        while path[-1] != a:
            path.append(int(pr[path[-1]]))
        return pix[np.array(path[::-1])]
    start = 0
    seq = [start]
    seen = {start}
    cur = start
    while True:
        cand = [j for j in nbs[cur] if j not in seen]
        if not cand:
            break
        cand.sort(key=lambda j: abs(pix[j][0] - pix[cur][0]) + abs(pix[j][1] - pix[cur][1]))
        cur = cand[0]
        seen.add(cur)
        seq.append(cur)
    return pix[np.array(seq)]


def skeleton_graph(sk: np.ndarray):
    """-> junction label image, list of branches {pix (ordered), ends: [node or None]*2, closed}."""
    code = ndimage.correlate(sk.astype(np.int32), _K, mode="constant")
    jpx = sk & (_CROSS[code] >= 3)
    jpx = ndimage.binary_dilation(jpx, structure=np.ones((3, 3)), iterations=2) & sk   # branches break apart, short bridges absorbed
    jl, nj = ndimage.label(jpx, structure=np.ones((3, 3)))
    rest = sk & ~jpx
    bl, nbr = ndimage.label(rest, structure=np.ones((3, 3)))
    if nj:
        jd, ji = ndimage.distance_transform_edt(jl == 0, return_indices=True)
    else:
        jd, ji = None, None
    jdil = [None]
    branches = []
    objs = ndimage.find_objects(bl)
    for i, sl in enumerate(objs):
        if sl is None:
            continue
        sub = bl[sl] == i + 1
        rr, cc = np.nonzero(sub)
        pix = np.c_[rr + sl[0].start, cc + sl[1].start]
        pix = _order_chain(pix)
        ends = []
        for end in (pix[0], pix[-1]):
            r, c = int(end[0]), int(end[1])
            if jd is not None and jd[r, c] <= 2.5:
                ends.append(int(jl[ji[0][r, c], ji[1][r, c]]))
            else:
                ends.append(None)
        closed = False
        if len(pix) > 3 and ends[0] is None and ends[1] is None:
            if abs(pix[0] - pix[-1]).max() <= 1:
                closed = True
        branches.append({"pix": pix, "ends": ends, "closed": closed})
    del jdil
    # merge branches through degree-2 junction clusters (pass-through), and close loops
    changed = True
    while changed:
        changed = False
        cnt = {}
        for i, b in enumerate(branches):
            for side, e in enumerate(b["ends"]):
                if e is not None:
                    cnt.setdefault(e, []).append((i, side))
        for j, lst in cnt.items():
            if len(lst) == 1:
                i, side = lst[0]
                jp = np.argwhere(jl == j)
                b = branches[i]
                if side == 1:
                    b["pix"] = np.r_[b["pix"], _order_tail(jp, b["pix"][-1])]
                else:
                    b["pix"] = np.r_[_order_tail(jp, b["pix"][0])[::-1], b["pix"]]
                b["ends"][side] = None
                jl[jl == j] = 0
                changed = True
                break
            if len(lst) != 2:
                continue
            (i1, s1), (i2, s2) = lst
            jp = np.argwhere(jl == j)
            if i1 == i2:
                b = branches[i1]
                b["pix"] = np.r_[b["pix"], _order_tail(jp, b["pix"][-1])]
                b["ends"] = [None, None]
                b["closed"] = True
            else:
                a, c = branches[i1], branches[i2]
                pa = a["pix"] if s1 == 1 else a["pix"][::-1]
                pc = c["pix"] if s2 == 0 else c["pix"][::-1]
                ea = a["ends"][1 - s1]
                ec = c["ends"][1 - s2]
                mid = _order_tail(jp, pa[-1])
                branches[i1] = {"pix": np.r_[pa, mid, pc], "ends": [ea, ec], "closed": False}
                branches.pop(i2)
            jl[jl == j] = 0
            changed = True
            break
    nj_out = nj
    return jl, nj_out, branches


def _order_tail(jp: np.ndarray, start) -> np.ndarray:
    """order junction-cluster pixels greedily from the pixel nearest to `start`."""
    if len(jp) == 0:
        return jp.reshape(0, 2)
    rem = [tuple(p) for p in jp]
    out = []
    cur = np.asarray(start)
    while rem:
        d = [abs(p[0] - cur[0]) + abs(p[1] - cur[1]) for p in rem]
        k = int(np.argmin(d))
        cur = np.asarray(rem.pop(k))
        out.append(cur)
    return np.array(out)


def prune(sk: np.ndarray, dt: np.ndarray, open_mask: np.ndarray, k: float, max_iter: int = 12):
    sk = sk.copy()
    for _ in range(max_iter):
        jl, nj, br = skeleton_graph(sk)
        removed = False
        for b in br:
            e0, e1 = b["ends"]
            if b["closed"] or (e0 is None and e1 is None):
                continue
            if e0 is not None and e1 is not None:
                continue
            free_end = b["pix"][-1] if e1 is None else b["pix"][0]
            jend = b["pix"][0] if e1 is None else b["pix"][-1]
            r, c = int(free_end[0]), int(free_end[1])
            if open_mask[max(r - 2, 0):r + 3, max(c - 2, 0):c + 3].any():
                continue
            L = len(b["pix"])
            if L < k * dt[int(jend[0]), int(jend[1])]:
                sk[b["pix"][:, 0], b["pix"][:, 1]] = False
                removed = True
        # isolated short fragments
        lab, n = ndimage.label(sk, structure=np.ones((3, 3)))
        if n > 1:
            sizes = ndimage.sum(sk, lab, range(1, n + 1))
            small = np.flatnonzero(sizes < 3) + 1
            if small.size:
                sk[np.isin(lab, small)] = False
        if not removed:
            break
        sk = thin(sk)
    return sk


def _turning(pts: np.ndarray, w: int, closed: bool):
    n = len(pts)
    th = np.zeros(n)
    if n < 2 * w + 1:
        return th
    idx = np.arange(n)
    if closed:
        a, b = pts[(idx - w) % n], pts[(idx + w) % n]
    else:
        a, b = pts[np.clip(idx - w, 0, n - 1)], pts[np.clip(idx + w, 0, n - 1)]
    u, v = pts - a, b - pts
    nu, nv = np.linalg.norm(u, axis=1), np.linalg.norm(v, axis=1)
    c = np.einsum("ij,ij->i", u, v) / np.maximum(nu * nv, 1e-12)
    th = np.degrees(np.arccos(np.clip(c, -1, 1)))
    if not closed:
        th[:w] = 0
        th[-w:] = 0
    return th


def _zones(mask: np.ndarray, closed: bool):
    """contiguous True runs -> list of (start, end) inclusive (wrap merged when closed)."""
    if not mask.any():
        return []
    d = np.diff(np.r_[0, mask.astype(int), 0])
    s = np.flatnonzero(d == 1)
    e = np.flatnonzero(d == -1) - 1
    z = list(zip(s, e))
    if closed and len(z) > 1 and z[0][0] == 0 and z[-1][1] == len(mask) - 1:
        z = [(z[-1][0], z[0][1] + len(mask))] + z[1:-1]
    return z


def split_branch(b, dt_px, res, cfg, node_r):
    """split indices along the branch: [(i, type)] where type L (bend) or W (width jump)."""
    pix = b["pix"]
    n = len(pix)
    pts = pix[:, ::-1].astype(float) * res
    d = dt_px * res
    closed = b["closed"]
    # ignore the zone near junction ends (the inscribed circle grows at T / X)
    ign = np.zeros(n, bool)
    for j, e in enumerate(b["ends"]):
        if e is not None:
            r = node_r.get(e, 0.0) * 1.6
            ss = np.cumsum(np.r_[0, np.linalg.norm(np.diff(pts, axis=0), axis=1)])
            if j == 0:
                ign |= ss <= r
            else:
                ign |= ss[-1] - ss <= r
    core = d[~ign] if (~ign).sum() > 5 else d
    dmed = float(np.median(core))
    splits = []
    # width jumps
    wj = cfg["bead"]["width_jump"]
    big = (d > (1 + wj) * dmed) & ~ign
    minlen = max(cfg["bead"]["min_zone_mm"], dmed) / res
    for s, e in _zones(big, closed):
        if e - s + 1 < minlen:
            continue
        for i in (s, e + 1):
            ii = i % n
            if (not closed) and (i <= 1 or i >= n - 2):
                continue
            splits.append((int(ii), "W"))
    # bends
    w = int(max(4, round(1.5 * dmed / res)))
    th = _turning(pts, w, closed)
    for s, e in _zones((th > cfg["bead"]["bend_deg"]) & ~ign, closed):
        rng = np.arange(s, e + 1) % n
        i = int(rng[np.argmax(th[rng])])
        splits.append((i, "L"))
    # merge close splits (keep W)
    splits.sort()
    out = []
    gap = 2.0 * dmed / res
    for i, ty in splits:
        if out and abs(i - out[-1][0]) < gap:
            if ty == "W" and out[-1][1] == "L":
                out[-1] = (i, ty)
            continue
        out.append((i, ty))
    if closed and len(out) > 1 and (out[0][0] + n - out[-1][0]) < gap:
        if out[-1][1] == "W" and out[0][1] == "L":
            out[0] = out[-1]
        out.pop()
    return out, dmed


def raster_grid(lo, hi, res: float, pad_mm: float, max_px: int):
    """centre-anchored raster grid (mirror / point-reflection invariant pixel centres — V-BG-4). The resolution doubles
    while the pixel count exceeds ``max_px`` (§7, GRAPH_RASTER_COARSE). -> (origin, shape, res, coarse)."""
    coarse = False
    while True:
        pad = pad_mm + 4 * res
        nx = int(np.ceil((hi[0] - lo[0] + 2 * pad) / res)) + 1
        ny = int(np.ceil((hi[1] - lo[1] + 2 * pad) / res)) + 1
        if nx * ny <= max_px:
            break
        res *= 2.0
        coarse = True
    c = 0.5 * (lo + hi)
    origin = c - 0.5 * res * np.array([nx, ny], float)
    return origin, (ny, nx), res, coarse


def segment_piece(t, eidx: np.ndarray, cfg: dict, free_edge_ext: list):
    """floor piece elements -> dict(kind, segments, junctions, elem_seg (local), skeleton)."""
    P = t.P
    nodes = t.elem_nodes(np.isin(np.arange(t.m), eidx))
    lo = P[nodes].min(axis=0)
    hi = P[nodes].max(axis=0)
    ext = cfg["bead"]["open_ext_mm"]
    origin, shape, res, coarse = raster_grid(lo, hi, float(cfg["raster_mm"]), ext,
                                             int(cfg.get("limits", {}).get("max_raster_px", 4_000_000)))
    cfg = dict(cfg, raster_mm=res)
    img = rasterize(P, t.tris(eidx), origin, res, shape)
    img = ndimage.binary_closing(img, structure=np.ones((3, 3)), iterations=1) | img
    # fill small inner holes (islands / holes footprints)
    bg, nbg = ndimage.label(~img)
    if nbg > 1:
        sl = ndimage.find_objects(bg)
        border = set(np.unique(np.r_[bg[0], bg[-1], bg[:, 0], bg[:, -1]]).tolist())
        imax = cfg["island"]["max_mm"] + 6.0
        for i, s in enumerate(sl):
            if s is None or (i + 1) in border:
                continue
            hh = (s[0].stop - s[0].start) * res
            ww = (s[1].stop - s[1].start) * res
            if max(hh, ww) <= imax:
                img[s][bg[s] == i + 1] = True
    floor = img.copy()
    dt0 = ndimage.distance_transform_edt(floor) * res
    p90 = float(np.percentile(dt0[floor], 90)) if floor.any() else 0.0
    area_mm2 = float(floor.sum()) * res * res
    if 2 * dt0.max() > cfg["bead"]["max_width_mm"] and 2 * p90 > 0.5 * cfg["bead"]["max_width_mm"]:
        return {"kind": "area", "p90_half_width": p90, "area": area_mm2, "res": res, "coarse": coarse}
    # open-end extension across free outline edges
    openm = np.zeros(shape, bool)
    for a, b in free_edge_ext:
        pa, pb = P[a], P[b]
        c = P[nodes].mean(axis=0)
        tvec = pb - pa
        nvec = np.array([tvec[1], -tvec[0]])
        nvec /= max(np.linalg.norm(nvec), 1e-12)
        # outward = away from the element interior: test with the floor raster just inside
        mid = 0.5 * (pa + pb)
        probe = ((mid - 1.5 * res * nvec - origin) / res - 0.5).round().astype(int)
        if 0 <= probe[1] < shape[0] and 0 <= probe[0] < shape[1] and not floor[probe[1], probe[0]]:
            nvec = -nvec
        L = np.linalg.norm(tvec)
        su = np.linspace(0, 1, max(2, int(L / (0.5 * res)) + 1))
        sv = np.arange(0, ext, 0.5 * res)
        pts = pa[None, None, :] + su[:, None, None] * tvec[None, None, :] + sv[None, :, None] * nvec[None, None, :]
        ij = ((pts.reshape(-1, 2) - origin) / res - 0.5).round().astype(int)
        ok = (ij[:, 0] >= 0) & (ij[:, 1] >= 0) & (ij[:, 0] < shape[1]) & (ij[:, 1] < shape[0])
        openm[ij[ok, 1], ij[ok, 0]] = True
        del c
    openm &= ~floor
    full = floor | openm
    dt = ndimage.distance_transform_edt(full)
    sk = thin(full)
    sk &= floor
    sk = prune(sk, dt, openm, cfg["bead"]["prune_k"])
    jl, nj, br = skeleton_graph(sk)
    # junction node radii / positions
    node_pos, node_r = {}, {}
    for j in range(1, nj + 1):
        rr, cc = np.nonzero(jl == j)
        if rr.size == 0:
            continue
        node_pos[j] = np.array([origin[0] + (cc.mean() + 0.5) * res, origin[1] + (rr.mean() + 0.5) * res])
        node_r[j] = float(dt[rr, cc].max()) * res
    segs, juncs = [], []
    jmap = {}
    for j in node_pos:
        deg = sum((b["ends"][0] == j) + (b["ends"][1] == j) for b in br)
        if deg < 3:
            continue
        jmap[j] = len(juncs)
        juncs.append({"type": "T" if deg == 3 else "X", "pos": node_pos[j], "r": node_r[j], "deg": int(deg), "segs": []})
    # merge degree-2 junction pass-throughs: handled implicitly (their branches stay separate segments, linked)
    for j in node_pos:
        if j not in jmap:
            jmap[j] = len(juncs)
            juncs.append({"type": "pass", "pos": node_pos[j], "r": node_r[j], "deg": 2, "segs": []})
    for b in br:
        pix = b["pix"]
        if len(pix) < 2:
            continue
        dpx = dt[pix[:, 0], pix[:, 1]]
        sp, dmed = split_branch(b, dpx, res, cfg, node_r)
        n = len(pix)
        cuts = [i for i, _ in sp]
        if b["closed"]:
            if not cuts:
                pieces = [np.arange(n)]
            else:
                pieces = []
                for k in range(len(cuts)):
                    a, c = cuts[k], cuts[(k + 1) % len(cuts)]
                    pieces.append(np.arange(a, c + (n if c <= a else 0) + 1) % n)
        else:
            bounds = [0] + cuts + [n - 1]
            pieces = [np.arange(bounds[k], bounds[k + 1] + 1) for k in range(len(bounds) - 1)]
        sid0 = len(segs)
        for k, ii in enumerate(pieces):
            pp = pix[ii]
            pts = np.c_[origin[0] + (pp[:, 1] + 0.5) * res, origin[1] + (pp[:, 0] + 0.5) * res]
            L = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
            dd = dt[pp[:, 0], pp[:, 1]] * res
            segs.append({"pts": pts, "length": L, "floor_w": 2 * float(np.median(dd)), "w_profile": dd,
                         "ends": [], "open_end": False, "closed": bool(b["closed"] and not cuts)})
        # split junctions
        for k, (i, ty) in enumerate(sp):
            p = pix[i]
            pos = np.array([origin[0] + (p[1] + 0.5) * res, origin[1] + (p[0] + 0.5) * res])
            jid = len(juncs)
            if b["closed"]:
                a_s, b_s = sid0 + (k - 1) % len(pieces), sid0 + k
            else:
                a_s, b_s = sid0 + k, sid0 + k + 1
            juncs.append({"type": ty, "pos": pos, "r": float(dt[p[0], p[1]]) * res, "deg": 2, "segs": [a_s, b_s]})
            segs[a_s]["ends"].append(jid)
            segs[b_s]["ends"].append(jid)
        for side, e in ((0, b["ends"][0]), (1, b["ends"][1])):
            s_id = sid0 if side == 0 else sid0 + len(pieces) - 1
            if e is not None:
                juncs[jmap[e]]["segs"].append(s_id)
                segs[s_id]["ends"].append(jmap[e])
            else:
                endp = pix[0] if side == 0 else pix[-1]
                r, c = int(endp[0]), int(endp[1])
                if openm[max(r - 2, 0):r + 3, max(c - 2, 0):c + 3].any():
                    segs[s_id]["open_end"] = True
    segs, juncs = _merge_y(segs, juncs)
    return {"kind": "bead", "segments": segs, "junctions": juncs, "skeleton_px": int(sk.sum()), "origin": origin,
            "res": res, "p90_half_width": p90, "area": area_mm2, "coarse": coarse}


def assign_nearest(seg_pts: list, Q: np.ndarray, tie_mm: float = 1e-6):
    """nearest segment for query plan points; distances equal within ``tie_mm`` -> the smaller segment index (robust
    to floating-point noise from numbering / rigid transforms — V-BG-4)."""
    if not seg_pts:
        return np.zeros(len(Q), np.int64), np.zeros(len(Q))
    P = np.concatenate(seg_pts)
    lab = np.concatenate([np.full(len(p), i) for i, p in enumerate(seg_pts)])
    k = min(8, len(P))
    d, j = cKDTree(P).query(Q, k=k)
    if k == 1:
        return lab[j], d
    d, j = np.asarray(d), np.asarray(j)
    near = d <= d[:, :1] + tie_mm
    big = np.iinfo(np.int64).max
    out = np.where(near, lab[j], big).min(axis=1)
    return out, d[:, 0]


def _merge_y(segs, juncs):
    """T junction with two short terminal arms (flare into two neighbours) -> one 'flare' segment, junction type Y."""
    dead = set()
    for jid, j in enumerate(juncs):
        if j["type"] != "T" or len(j["segs"]) != 3:
            continue
        term = [s for s in j["segs"] if len(segs[s]["ends"]) == 1 and not segs[s]["open_end"]]
        if len(term) == 3:
            term = sorted(term, key=lambda s: segs[s]["length"])[:2]
        stem = [s for s in j["segs"] if s not in term]
        if len(term) != 2 or len(stem) != 1:
            continue
        if segs[stem[0]]["length"] < 2.0 * max(segs[t]["length"] for t in term):
            continue
        w = segs[stem[0]]["floor_w"]
        if max(segs[t]["length"] for t in term) > 4.0 * w:
            continue
        a, b = term
        pa, pb = segs[a]["pts"], segs[b]["pts"]
        # orient both away from the junction
        jp = j["pos"]
        if np.hypot(*(pa[0] - jp)) > np.hypot(*(pa[-1] - jp)):
            pa = pa[::-1]
        if np.hypot(*(pb[0] - jp)) > np.hypot(*(pb[-1] - jp)):
            pb = pb[::-1]
        segs[a]["pts"] = np.r_[pb[::-1], pa]
        segs[a]["length"] += segs[b]["length"]
        segs[a]["w_profile"] = np.r_[segs[b]["w_profile"][::-1], segs[a]["w_profile"]]
        segs[a]["floor_w"] = 2 * float(np.median(segs[a]["w_profile"]))
        segs[a]["flare"] = True
        j["type"] = "Y"
        j["segs"] = [stem[0], a]
        dead.add(b)
    if not dead:
        return segs, juncs
    keep = [i for i in range(len(segs)) if i not in dead]
    remap = {o: n for n, o in enumerate(keep)}
    segs = [segs[i] for i in keep]
    for j in juncs:
        j["segs"] = [remap[s] for s in j["segs"] if s in remap]
    return segs, juncs
