"""Synthetic aligned-quad shell meshes for the depth-section / one-sided entry checks (esl contract
esl_bead_depth_mode.md §8 V-0247-DM-1·18·19·28·29). Deterministic, numpy only (no gmsh): a height field on a tensor
grid whose lines include every slope break, so flanks are planar strips and floors / plates are flat.

Rectangles use the Chebyshev inset depth: inset(x, y) = min(x − x0, x1 − x, y − y0, y1 − y) (> 0 inside).
A feature (rect, depth, run_lo, run_hi) adds depth·clip(inset / run, 0, 1) — with separate runs per side when the
flank angles differ (``runs`` = (x0 side, x1 side, y0 side, y1 side)).
"""
from __future__ import annotations

import numpy as np


def _axis(lo, hi, h, breaks):
    """uniform points (step h) + the slope breaks; uniform points closer than 0.2·h to a break are dropped."""
    br = np.array(sorted({round(float(b), 9) for b in breaks if lo <= b <= hi}))
    uni = np.linspace(lo, hi, int(round((hi - lo) / h)) + 1)
    if br.size:
        d = np.abs(uni[:, None] - br[None, :]).min(axis=1)
        uni = uni[d > 0.2 * h]
    return np.array(sorted(set(np.round(np.r_[uni, br], 9).tolist())))


def grid_mesh(xs, ys, zfun):
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    Z = zfun(X, Y)
    nx, ny = len(xs), len(ys)
    nodes = np.c_[X.ravel(), Y.ravel(), Z.ravel()].astype(np.float64)
    i, j = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1), indexing="ij")
    a = (i * ny + j).ravel()
    conn = np.c_[a, a + ny, a + ny + 1, a + 1].astype(np.int64)
    return nodes, conn


def _ramp(inset, run):
    return np.clip(inset / max(run, 1e-12), 0.0, 1.0)


def _rect_t(X, Y, rect, runs):
    """flank fraction 0 (outside / top) .. 1 (floor) of a rectangle with per-side runs (x0, x1, y0, y1)."""
    x0, x1, y0, y1 = rect
    r0, r1, r2, r3 = runs
    return np.minimum.reduce([_ramp(X - x0, r0), _ramp(x1 - X, r1), _ramp(Y - y0, r2), _ramp(y1 - Y, r3)])


def _breaks(rect, runs):
    x0, x1, y0, y1 = rect
    r0, r1, r2, r3 = runs
    return [x0, x0 + r0, x1 - r1, x1], [y0, y0 + r2, y1 - r3, y1]


def channel(*, D=10.0, W_open=40.0, theta=(45.0, 45.0), L=400.0, plate=(600.0, 300.0), h=5.0, end_theta=45.0):
    """straight trapezoid channel along x (sunk −D), entry width W_open at the plate, flank angles theta = (y0 side,
    y1 side) in degrees, end flanks at end_theta. -> dict(nodes, conn, fixed, meta)."""
    Px, Py = plate
    yc = Py / 2.0
    x0, x1 = (Px - L) / 2.0, (Px + L) / 2.0
    y0, y1 = yc - W_open / 2.0, yc + W_open / 2.0
    ra, rb = D / np.tan(np.radians(theta[0])), D / np.tan(np.radians(theta[1]))
    re = D / np.tan(np.radians(end_theta))
    runs = (re, re, ra, rb)
    rect = (x0, x1, y0, y1)
    bx, by = _breaks(rect, runs)
    xs, ys = _axis(0.0, Px, h, bx), _axis(0.0, Py, h, by)

    def z(X, Y):
        return -D * _rect_t(X, Y, rect, runs)
    nodes, conn = grid_mesh(xs, ys, z)
    fixed = _corner_fixed(nodes)
    meta = {"D": D, "W_open": W_open, "theta": list(theta), "run": [ra, rb], "x_range": [x0, x1], "y_entry": [y0, y1],
            "y_floor": [y0 + ra, y1 - rb], "h": h, "end_run": re}
    return {"nodes": nodes, "conn": conn, "fixed": fixed, "meta": meta}


def parallel(*, gap=20.0, D=10.0, W_open=40.0, theta=45.0, L=400.0, plate=(600.0, 300.0), h=5.0):
    """two parallel channels with ``gap`` mm of plate between their entry lines (V-0247-DM-30)."""
    Px, Py = plate
    run = D / np.tan(np.radians(theta))
    x0, x1 = (Px - L) / 2.0, (Px + L) / 2.0
    ya0 = Py / 2.0 - gap / 2.0 - W_open
    yb0 = Py / 2.0 + gap / 2.0
    ra = (x0, x1, ya0, ya0 + W_open)
    rb = (x0, x1, yb0, yb0 + W_open)
    runs = (run, run, run, run)
    bx, by = _breaks(ra, runs)
    _bx, by2 = _breaks(rb, runs)
    xs, ys = _axis(0.0, Px, h, bx), _axis(0.0, Py, h, by + by2)

    def z(X, Y):
        return -D * np.maximum(_rect_t(X, Y, ra, runs), _rect_t(X, Y, rb, runs))
    nodes, conn = grid_mesh(xs, ys, z)
    return {"nodes": nodes, "conn": conn, "fixed": _corner_fixed(nodes),
            "meta": {"D": D, "W_open": W_open, "gap": gap, "run": run}}


def _corner_fixed(nodes):
    """four plate corners (bolt stand-ins) — far from every bead."""
    P = nodes[:, :2]
    out = []
    for cx in (P[:, 0].min(), P[:, 0].max()):
        for cy in (P[:, 1].min(), P[:, 1].max()):
            out.append(int(np.argmin(np.hypot(P[:, 0] - cx, P[:, 1] - cy))))
    return np.array(sorted(set(out)), np.int64)


def oneside(case: str, *, theta=45.0, h=5.0):
    """one-sided entry fixtures (V-0247-DM-18):
    a  ring band (floor −10, plate 0) around a shared-child plateau (−4) — each ring side: open = outer entry,
       fixed = the plateau wall (shared child);
    b  channel (−10) with a sibling pocket (−5) along one side — step junction (neighbour bead) on the fixed side;
    c  channel running along the plate edge (floor reaches the free edge on the fixed side);
    d  wide channel (−10) with an exclusive child plateau (−4) along one side (only this segment touches it)."""
    D = 10.0
    run = D / np.tan(np.radians(theta))
    Px, Py = 600.0, 300.0
    if case == "a":
        ro = (150.0, 450.0, 60.0, 240.0)
        ri = (150.0 + 40.0, 450.0 - 40.0, 60.0 + 40.0, 240.0 - 40.0)
        rr = 6.0 / np.tan(np.radians(theta))
        runs_o = (run,) * 4
        runs_i = (rr,) * 4
        bx, by = _breaks(ro, runs_o)
        bx2, by2 = _breaks(ri, runs_i)
        xs, ys = _axis(0.0, Px, h, bx + bx2), _axis(0.0, Py, h, by + by2)

        def z(X, Y):
            return -D * _rect_t(X, Y, ro, runs_o) + 6.0 * _rect_t(X, Y, ri, runs_i)
        meta = {"open": "outer", "fixed_kind": "shared", "h_f": 6.0, "r_f": rr}
    elif case == "b":
        rc = (100.0, 500.0, 110.0, 150.0)            # channel
        rp = (100.0, 500.0, 150.0, 200.0)            # pocket beside it (shallower, shares the y = 150 line)
        runs_c = (run, run, run, 0.0)
        runs_p = (5.0 / np.tan(np.radians(theta)),) * 2 + (0.0, 5.0 / np.tan(np.radians(theta)))
        bx, by = _breaks(rc, (run, run, run, 1e-9))
        bx2, by2 = _breaks(rp, (runs_p[0], runs_p[1], 1e-9, runs_p[3]))
        xs, ys = _axis(0.0, Px, h, bx + bx2), _axis(0.0, Py, h, by + by2)

        def z(X, Y):
            tc = np.minimum.reduce([_ramp(X - rc[0], run), _ramp(rc[1] - X, run), _ramp(Y - rc[2], run),
                                    np.where(Y <= rc[3] + 1e-9, 1.0, 0.0)])
            tp = np.minimum.reduce([_ramp(X - rp[0], runs_p[0]), _ramp(rp[1] - X, runs_p[1]),
                                    np.where(Y >= rp[2] - 1e-9, 1.0, 0.0), _ramp(rp[3] - Y, runs_p[3])])
            # step between the channel floor (−10) and the pocket floor (−5) on y ∈ [150, 150 + 5]
            st = _ramp(Y - rc[3], 5.0) * np.minimum(_ramp(X - rp[0], runs_p[0]), _ramp(rp[1] - X, runs_p[1]))
            return np.where(Y <= rc[3], -D * tc, -5.0 * tp - 5.0 * (1.0 - st) * (tp > 0))
        ys = _axis(0.0, Py, h, by + by2 + [rc[3] + 5.0])
        meta = {"open": "y0", "fixed_kind": "junction"}
    elif case == "c":
        rc = (100.0, 500.0, -1.0, 40.0)              # floor runs to the y = 0 free edge
        runs_c = (run, run, 1e-9, run)
        bx, by = _breaks(rc, runs_c)
        xs, ys = _axis(0.0, Px, h, bx), _axis(0.0, Py, h, [b for b in by if b >= 0])

        def z(X, Y):
            return -D * np.minimum.reduce([_ramp(X - rc[0], run), _ramp(rc[1] - X, run), _ramp(rc[3] - Y, run)])
        meta = {"open": "y1", "fixed_kind": "edge"}
    elif case == "d":
        rc = (100.0, 500.0, 100.0, 200.0)            # wide channel
        rp = (100.0 + run, 500.0 - run, 160.0, 200.0 - run)   # child plateau strip along the y1 side
        rr = 6.0 / np.tan(np.radians(theta))
        runs_c = (run,) * 4
        bx, by = _breaks(rc, runs_c)
        xs_b = [rp[0], rp[1]]
        ys_b = [rp[2], rp[2] + rr]
        xs, ys = _axis(0.0, Px, h, bx + xs_b), _axis(0.0, Py, h, by + ys_b)

        def z(X, Y):
            tch = _rect_t(X, Y, rc, runs_c)
            tp = np.where((X >= rp[0]) & (X <= rp[1]) & (Y <= rp[3] + run), _ramp(Y - rp[2], rr), 0.0)
            return -D * tch + 6.0 * np.minimum(tp, tch)
        meta = {"open": "y0", "fixed_kind": "child"}
    else:
        raise ValueError(case)
    nodes, conn = grid_mesh(xs, ys, z)
    meta.update(D=D, theta=theta, run=run, h=h)
    return {"nodes": nodes, "conn": conn, "fixed": _corner_fixed(nodes), "meta": meta}
