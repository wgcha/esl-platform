"""Step-straddling bosses (issue #63 B10_D / B11_D BG_BASIS_LEAK, BG-D-47) — [synth] extra: gmsh, shapely; tests use
the frozen fixture ``fixtures/stepboss.npz``.

Plate 300 x 200, flat flange (level 0) with 4 fixed fastener holes. A channel (depress ``CH_D`` 12, entry 190 x 64,
45 deg flanks) runs into a shallower pocket (depress ``PK_D`` 6): inside the pocket only the lower part of the channel
flank remains = a 6 mm step whose walls the classifier labels as junction-zone walls between the channel segment and
the pocket segments. Two bosses (raise 3 over the flange, top r 4, unclamped 45 deg cones — the same construction as
the H6 wall-straddling bosses) sit on the channel end step at y = 100 -/+ 20: each touches the channel floor, the
pocket floor and the step's junction-zone walls ("straddle" islands). Built from the H6 feature-tree machinery
(``synth_h6.Feat`` / ``evaluate`` / ``gmsh_mesh``)."""
from __future__ import annotations

import numpy as np

W, H = 300.0, 200.0
CH_D, PK_D = 12.0, 6.0              # channel / pocket depth (step = CH_D - PK_D)
CH_W = 64.0                         # channel entry width (centre line y = 100, x 40 .. 230)
BOSS_X, BOSS_DY, BOSS_R = 221.0, 20.0, 4.0
HMESH = 3.0


def build_tree():
    from shapely.geometry import Point, box

    from . import synth_h6 as s6
    root = s6.Feat("flange", "root", entry=box(0, 0, W, H))
    for cx, cy in ((12, 12), (288, 12), (12, 188), (288, 188)):
        root.holes.append((Point(cx, cy).buffer(3, quad_segs=6), "fasten", True))
    ch = root.add(s6.Feat("ch", "depress", CH_D, box(40, 100 - CH_W / 2, 230, 100 + CH_W / 2)
                          .buffer(-6, join_style="mitre").buffer(6, quad_segs=4)))
    pk = root.add(s6.Feat("pk", "depress", PK_D, box(180, 30, 280, 170).buffer(-8, join_style="mitre")
                          .buffer(8, quad_segs=4)))
    ch.extra_creases.append(s6.inset(ch.entry, PK_D).boundary.intersection(pk.top))      # step foot / top creases
    for y in (100 - BOSS_DY, 100 + BOSS_DY):
        rb = BOSS_R + 3.0
        b = root.add(s6.Feat(f"sboss_{int(y)}", "raise", 3.0, Point(BOSS_X, y).buffer(rb, quad_segs=s6.qs(rb)),
                             gt="island", unclamped=True))
        for f, d in ((ch, CH_D), (pk, PK_D)):
            rr = rb + d
            b.extra_creases.append(Point(BOSS_X, y).buffer(rr, quad_segs=s6.qs(rr)).boundary.intersection(f.top))
    return root


def build(h=HMESH) -> dict:
    """-> {x0, conn (tri 4th = -1), fixed_nodes} (gmsh + shapely)."""
    import shapely

    from . import synth_h6 as s6
    from ._gmsh import clean
    root = build_tree()
    dom, L = s6.domain_and_creases(root)
    X, conn = s6.gmsh_mesh(s6.faces_of(dom, L), h)
    X, conn = clean(X, conn)
    z, *_ = s6.evaluate(root, X[:, :2])
    X = X.copy()
    X[:, 2] = z
    pts = shapely.points(X[:, 0], X[:, 1])
    fx = [np.flatnonzero(shapely.distance(pts, g.boundary) < 0.05) for f in root.walk() for g, _t, fixed in f.holes
          if fixed]
    return {"x0": X, "conn": conn, "fixed_nodes": np.unique(np.concatenate(fx))}


def fixture_arrays(mesh) -> dict:
    return {"x0": np.asarray(mesh["x0"], np.float64), "conn": np.asarray(mesh["conn"], np.int32),
            "fixed": np.asarray(mesh["fixed_nodes"], np.int32)}


if __name__ == "__main__":
    import sys
    m = build(HMESH)
    np.savez_compressed(sys.argv[1], **fixture_arrays(m))
    print("nodes", m["x0"].shape[0], "elems", m["conn"].shape[0], "fixed", m["fixed_nodes"].size)
