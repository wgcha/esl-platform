"""Synthetic shell meshes for the bead-position variable U (esl contract esl_bead_pos_u.md §5 V-0249-PU-1..5·21·24).
Deterministic, numpy only. Straight channel = ``synth_oneside.channel``; here: a circular-arc channel, a T junction,
a closed ring channel and a channel with an exclusive child plateau + an owned island on its floor."""
from __future__ import annotations

import numpy as np

from .synth_oneside import _axis, _breaks, _corner_fixed, _ramp, _rect_t, grid_mesh


def arc(*, R=150.0, W_open=40.0, D=10.0, theta=45.0, span_deg=90.0, plate=(500.0, 400.0), h=4.0):
    """channel along a circular arc (centre c, radius R, entry width W_open, depth D, flank angle theta; ends at the
    arc angles ±span/2 about +y with theta end flanks). Polar inset = min(r − (R − W/2), (R + W/2) − r, R·(φ − φ0),
    R·(φ1 − φ)). -> dict(nodes, conn, fixed, meta{c, R, W_open, D, run})."""
    Px, Py = plate
    c = np.array([Px / 2.0, 40.0])
    run = D / np.tan(np.radians(theta))
    a0, a1 = np.radians(90.0 - span_deg / 2.0), np.radians(90.0 + span_deg / 2.0)
    xs = _axis(0.0, Px, h, [])
    ys = _axis(0.0, Py, h, [])

    def z(X, Y):
        dx, dy = X - c[0], Y - c[1]
        r = np.hypot(dx, dy)
        ph = np.arctan2(dy, dx)
        ins = np.minimum.reduce([r - (R - W_open / 2.0), (R + W_open / 2.0) - r, R * (ph - a0), R * (a1 - ph)])
        return -D * _ramp(ins, run)
    nodes, conn = grid_mesh(xs, ys, z)
    return {"nodes": nodes, "conn": conn, "fixed": _corner_fixed(nodes),
            "meta": {"c": c.tolist(), "R": R, "W_open": W_open, "D": D, "run": run, "span": [a0, a1], "h": h}}


def tee(*, D=10.0, W_open=40.0, theta=45.0, plate=(600.0, 400.0), h=5.0):
    """T junction: a main channel along x (y centre 120) and a branch along y from the main channel to y = 340
    (x centre 300), same depth / width / flank angle (one floor — the classifier makes 3 segments + a junction zone)."""
    Px, Py = plate
    run = D / np.tan(np.radians(theta))
    rm = (100.0, 500.0, 120.0 - W_open / 2.0, 120.0 + W_open / 2.0)
    rb = (300.0 - W_open / 2.0, 300.0 + W_open / 2.0, 120.0 - W_open / 2.0, 340.0)
    runs = (run,) * 4
    bx, by = _breaks(rm, runs)
    bx2, by2 = _breaks(rb, runs)
    xs, ys = _axis(0.0, Px, h, bx + bx2), _axis(0.0, Py, h, by + by2)

    def z(X, Y):
        return -D * np.maximum(_rect_t(X, Y, rm, runs), _rect_t(X, Y, rb, runs))
    nodes, conn = grid_mesh(xs, ys, z)
    return {"nodes": nodes, "conn": conn, "fixed": _corner_fixed(nodes),
            "meta": {"main": rm, "branch": rb, "D": D, "W_open": W_open, "run": run}}


def ring(*, D=10.0, W_open=40.0, theta=45.0, plate=(600.0, 400.0), h=5.0):
    """closed rectangular ring channel (outer 100..500 × 80..320, band W_open) — U_CLOSED / ring segments."""
    Px, Py = plate
    run = D / np.tan(np.radians(theta))
    ro = (100.0, 500.0, 80.0, 320.0)
    ri = (100.0 + W_open, 500.0 - W_open, 80.0 + W_open, 320.0 - W_open)
    runs = (run,) * 4
    bx, by = _breaks(ro, runs)
    bx2, by2 = _breaks((ri[0] - run, ri[1] + run, ri[2] - run, ri[3] + run), runs)
    xs, ys = _axis(0.0, Px, h, bx + bx2), _axis(0.0, Py, h, by + by2)

    def z(X, Y):
        outer = _rect_t(X, Y, ro, runs)
        inner = _rect_t(X, Y, (ri[0] - run, ri[1] + run, ri[2] - run, ri[3] + run), runs)
        return -D * np.minimum(outer, 1.0 - inner)
    nodes, conn = grid_mesh(xs, ys, z)
    return {"nodes": nodes, "conn": conn, "fixed": _corner_fixed(nodes), "meta": {"D": D, "W_open": W_open}}


def boss(*, D=10.0, W_open=60.0, theta=45.0, plate=(600.0, 300.0), h=5.0, b=3.0, at=(300.0, 150.0), size=12.0):
    """straight channel (−D, W_open) with a raised boss island (+b, size × size) on its floor at ``at`` — V-0249-PU-5·24
    (owned island rigid with the bead; with a fixed node on it = held)."""
    Px, Py = plate
    run = D / np.tan(np.radians(theta))
    yc = Py / 2.0
    rc = (100.0, 500.0, yc - W_open / 2.0, yc + W_open / 2.0)
    rb = (at[0] - size / 2.0, at[0] + size / 2.0, at[1] - size / 2.0, at[1] + size / 2.0)
    rbb = b / np.tan(np.radians(theta))
    bx, by = _breaks(rc, (run,) * 4)
    bx3, by3 = _breaks(rb, (rbb,) * 4)
    xs, ys = _axis(0.0, Px, h, bx + bx3), _axis(0.0, Py, h, by + by3)

    def z(X, Y):
        return -D * _rect_t(X, Y, rc, (run,) * 4) + b * _rect_t(X, Y, rb, (rbb,) * 4)
    nodes, conn = grid_mesh(xs, ys, z)
    return {"nodes": nodes, "conn": conn, "fixed": _corner_fixed(nodes),
            "meta": {"channel": rc, "boss": rb, "D": D, "W_open": W_open}}


def annulus(*, R=120.0, W_open=40.0, D=10.0, theta=45.0, plate=(400.0, 400.0), h=4.0):
    """circular ring channel (closed skeleton — U_CLOSED)."""
    Px, Py = plate
    c = np.array([Px / 2.0, Py / 2.0])
    run = D / np.tan(np.radians(theta))
    xs, ys = _axis(0.0, Px, h, []), _axis(0.0, Py, h, [])

    def z(X, Y):
        r = np.hypot(X - c[0], Y - c[1])
        return -D * _ramp(np.minimum(r - (R - W_open / 2.0), (R + W_open / 2.0) - r), run)
    nodes, conn = grid_mesh(xs, ys, z)
    return {"nodes": nodes, "conn": conn, "fixed": _corner_fixed(nodes), "meta": {"c": c.tolist(), "R": R}}
