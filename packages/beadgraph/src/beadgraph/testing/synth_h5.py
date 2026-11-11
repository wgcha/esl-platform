"""H5 synthetic case ([synth] extra: gmsh — tests use fixtures/h5.npz): plate 400x300, ring bead ("ㅁ") 15 mm inboard + two vertical beads V1/V2 T-joined to the ring bottom.

Bead section: depth 8, entry width 30, flank 45 deg (floor width 14).
Geometry = OCC slab minus groove tools (like synth_hard.h4_step), top shell meshed with gmsh (quad-dominant, h = 3).
"""
from __future__ import annotations

import math
import os

import numpy as np

LX, LY = 400.0, 300.0
D0, A, B0 = 8.0, 15.0, 7.0            # depth, entry half width, floor half width
RING_IN = 15.0                         # entry edge inset from plate edge
XC = (LX / 3.0, 2.0 * LX / 3.0)        # V1, V2 centre lines
Y_FLOOR_BOT = 30.0                     # V floor bottom end (inside ring floor 23..37)
Y_ENTRY_TOP = 235.0                    # V entry top end (ring inner entry at 255)
# derived lines
RING_FLOOR = (RING_IN + D0, RING_IN + 2 * A - D0)        # 23 .. 37 inset (floor band)
RING_ENTRY_IN = RING_IN + 2 * A                          # 45 inset
Y_J0 = RING_FLOOR[1]                                     # 37: V1 floor meets ring floor (bottom side)
Y_J1 = RING_ENTRY_IN                                     # 45: mitre zone end (ring inner entry)


def _inset_rect(P, x0, y0, x1, y1):
    return np.minimum(np.minimum(P[:, 0] - x0, x1 - P[:, 0]), np.minimum(P[:, 1] - y0, y1 - P[:, 1]))


def h_ring(P):
    """ring groove height (z <= 0)."""
    outer = _inset_rect(P, RING_IN, RING_IN, LX - RING_IN, LY - RING_IN)       # >0 inside outer entry
    inner = _inset_rect(P, RING_ENTRY_IN, RING_ENTRY_IN, LX - RING_ENTRY_IN, LY - RING_ENTRY_IN)
    # depth = min(D0, outer, -inner)  (inside the annulus)
    d = np.minimum(D0, np.minimum(outer, -inner))
    return -np.maximum(d, 0.0)


def h_v(P, xc, D=D0, a=A, y_top=Y_ENTRY_TOP, y_bot=Y_FLOOR_BOT - D0):
    """vertical bead groove: 45 deg flanks, entry half width a, entry y range [y_bot, y_top]."""
    ins = np.minimum(a - np.abs(P[:, 0] - xc), np.minimum(P[:, 1] - y_bot, y_top - P[:, 1]))
    return -np.clip(ins, 0.0, D)


def height(P):
    return np.minimum(h_ring(P), np.minimum(h_v(P, XC[0]), h_v(P, XC[1])))


def build(h: float = 3.0, cache: str | None = None) -> dict:
    if cache and os.path.exists(cache):
        z = np.load(cache, allow_pickle=False)
        return {k: z[k] for k in z.files}
    import gmsh

    from ._gmsh import clean, extract
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        occ = gmsh.model.occ
        zb, e = -30.0, 2.0
        slab = occ.addBox(0, 0, zb, LX, LY, -zb)

        def rect_wire(x0, y0, x1, y1, z):
            p = [occ.addPoint(x0, y0, z), occ.addPoint(x1, y0, z), occ.addPoint(x1, y1, z), occ.addPoint(x0, y1, z)]
            return occ.addCurveLoop([occ.addLine(p[i], p[(i + 1) % 4]) for i in range(4)])

        def frustum(x0, y0, x1, y1, grow):
            """floor rect at z=-D0, widening 45 deg up to z=+e (grow = +1 outward) — planar faces (ThruSections BSpline
            faces were meshed one element across the flank)."""
            g = grow * (D0 + e)
            pb = [occ.addPoint(x, y, -D0) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
            pt = [occ.addPoint(x, y, e) for x, y in ((x0 - g, y0 - g), (x1 + g, y0 - g), (x1 + g, y1 + g), (x0 - g, y1 + g))]
            lb = [occ.addLine(pb[i], pb[(i + 1) % 4]) for i in range(4)]
            lt = [occ.addLine(pt[i], pt[(i + 1) % 4]) for i in range(4)]
            lv = [occ.addLine(pb[i], pt[i]) for i in range(4)]
            fs = [occ.addPlaneSurface([occ.addCurveLoop(lb)]), occ.addPlaneSurface([occ.addCurveLoop(lt)])]
            for i in range(4):
                j = (i + 1) % 4
                fs.append(occ.addPlaneSurface([occ.addCurveLoop([lb[i], lv[j], -lt[i], -lv[i]])]))
            return [(3, occ.addVolume([occ.addSurfaceLoop(fs)]))]

        f0, f1 = RING_FLOOR
        outer = frustum(f0, f0, LX - f0, LY - f0, 1)
        inner = frustum(f1, f1, LX - f1, LY - f1, -1)                   # island narrows upward
        ring, _ = occ.cut(outer, inner)
        vs = []
        for xc in XC:
            vs += frustum(xc - B0, Y_FLOOR_BOT, xc + B0, Y_ENTRY_TOP - D0, 1)
        tools, _ = occ.fuse(ring, vs)
        body, _ = occ.cut([(3, slab)], tools)
        occ.synchronize()
        vols = [t for d_, t in body if d_ == 3]
        faces = gmsh.model.getBoundary([(3, v) for v in vols], oriented=False, combined=True)
        keep, drop = [], []
        for _d, f in faces:
            bb = gmsh.model.getBoundingBox(2, abs(f))
            (drop if bb[2] <= zb + 1e-6 else keep).append(abs(f))
        occ.remove([(3, v) for v in vols])
        occ.remove([(2, f) for f in drop], recursive=True)
        occ.synchronize()
        opts = {"Mesh.MeshSizeMax": h, "Mesh.MeshSizeMin": 0.5 * h, "Mesh.MeshSizeFromCurvature": 0,
                "Mesh.MeshSizeExtendFromBoundary": 1, "Mesh.Algorithm": 8, "Mesh.RecombineAll": 1,
                "Mesh.RecombinationAlgorithm": 1, "Mesh.SubdivisionAlgorithm": 0, "Mesh.ElementOrder": 1,
                "Mesh.Smoothing": 3}
        for k, v in opts.items():
            gmsh.option.setNumber(k, v)
        gmsh.model.mesh.generate(2)
        X, conn = extract(gmsh)
    finally:
        gmsh.finalize()
    X, conn = clean(X, conn)
    mesh = {"x0": X, "conn": conn, "elem_type": np.where(conn[:, 3] >= 0, 4, 3).astype(np.int8)}
    if cache:
        np.savez(cache, **mesh)
    return mesh


def centroids(mesh):
    C = mesh["conn"]
    X = mesh["x0"]
    q = C[:, 3] >= 0
    c = X[C[:, :3]].sum(axis=1)
    c[q] += X[C[q, 3]]
    return c / np.where(q, 4.0, 3.0)[:, None]


def labels(mesh):
    """element labels: plate | ring_f | ring_s | v1_f | v1_s | v2_f | v2_s (f = floor, s = flank); junction floor -> ring_f."""
    X = mesh["x0"]
    c = centroids(mesh)
    P = c[:, :2]
    hr = h_ring(P)
    hv = [h_v(P, xc) for xc in XC]
    z = c[:, 2]
    lab = np.full(c.shape[0], "plate", dtype=object)
    flat = np.abs(z + D0) < 0.05
    tol = 0.05
    own_r = hr <= np.minimum(*hv) + tol
    deep = z < -1e-6
    for i, xc in enumerate(XC):
        mine = deep & (hv[i] < hr - tol) | (deep & (np.abs(P[:, 0] - xc) < A) & (P[:, 1] > Y_J0 - 1e-6) & ~(hr < hv[i] - tol))
        lab[mine & flat] = f"v{i + 1}_f"
        lab[mine & ~flat] = f"v{i + 1}_s"
    rmask = deep & (lab == "plate")
    lab[rmask & flat] = "ring_f"
    lab[rmask & ~flat] = "ring_s"
    return lab


def node_owner(mesh):
    """per-node: 'ring' (ring strictly lower than V), 'v1'/'v2' (V strictly lower), 'shared' (equal and < 0), 'plate'."""
    X = mesh["x0"]
    P = X[:, :2]
    hr = h_ring(P)
    hv = [h_v(P, xc) for xc in XC]
    own = np.full(X.shape[0], "plate", dtype=object)
    tol = 1e-4
    deep = X[:, 2] < -1e-6
    own[deep & (hr < np.minimum(*hv) - tol)] = "ring"
    for i in range(2):
        own[deep & (hv[i] < np.minimum(hr, hv[1 - i]) - tol)] = f"v{i + 1}"
    sh = deep & (own == "plate")
    own[sh] = "shared"
    return own


def fixture_arrays(mesh) -> dict:
    lab = labels(mesh)
    own = node_owner(mesh)
    out = {"x0": np.asarray(mesh["x0"], np.float64), "conn": np.asarray(mesh["conn"], np.int32),
           "fixed": np.zeros(0, np.int32)}
    for k, v in (("lab", lab), ("own", own)):
        names, codes = np.unique(np.asarray(v, dtype=object).astype(str), return_inverse=True)
        out[f"gt_{k}_names"] = names.astype("U")
        out[f"gt_{k}"] = codes.astype(np.int16)
    return out


if __name__ == "__main__":
    import sys
    m = build(3.0)
    np.savez_compressed(sys.argv[1], **fixture_arrays(m))
    et = np.asarray(m["elem_type"])
    print("nodes", m["x0"].shape[0], "elems", et.size, "quads", int((et == 4).sum()), "trias", int((et == 3).sum()))
    dz = m["x0"][:, 2] - height(m["x0"][:, :2])
    print("max |z - heightfield|", float(np.abs(dz).max()))
    lab = labels(m)
    for k in sorted(set(lab)):
        print(k, int((lab == k).sum()))
