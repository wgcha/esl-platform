"""H6 synthetic TV back chassis (issue #63 approximation), 1200 x 675 mm mid-surface shell.

Construction: feature tree (root flange -> raises / depressions with 45 deg flanks, heights RELATIVE to the parent floor).
Height field z(x, y) is evaluated analytically (shapely distances); the 2D domain (plate + tabs - holes) is partitioned by
all crease curves (entry / floor outlines) with shapely.polygonize and meshed with gmsh built-in kernel (quad-dominant),
then lifted.  Ground truth per element comes from the same feature tree (owner feature at the centroid).

Coordinates: features are written in "y_down" (% of H measured from the top, as in the issue) and converted to mesh
y = H - y_down.  Generator-only deps: shapely, gmsh ([synth] extra).  The classifier does NOT import this module;
tests use the frozen fixture ``fixtures/h6.npz`` (``fixture_arrays``).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box
from shapely.ops import polygonize, unary_union

W, H = 1200.0, 675.0
HMESH = 3.0
EPS = 1e-6


# ------------------------------------------------------------------------------------------------ geometry helpers
def T(g):
    """y_down -> mesh y."""
    return affinity.affine_transform(g, [1, 0, 0, -1, 0, H])


def qs(r, h=HMESH):
    return int(max(2, math.ceil(0.5 * math.pi * r / (0.9 * h))))


def circ(x, y, r):
    return T(Point(x, y).buffer(r, quad_segs=qs(r)))


def rect(x0, y0, x1, y1, r=0.0):
    b = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    if r > 0:
        b = b.buffer(-r, join_style="mitre").buffer(r, quad_segs=qs(r))
    return T(b)


def poly(pts, r=0.0):
    p = Polygon(pts)
    if r > 0:
        p = p.buffer(-r, join_style="mitre").buffer(r, quad_segs=qs(r))
    return T(p)


def mx(g):
    """mirror about x = W/2 (already in mesh coords)."""
    return affinity.affine_transform(g, [-1, 0, 0, 1, W, 0])


def inset(g, d):
    return g.buffer(-d, quad_segs=4, join_style="round") if d > 0 else g


# ------------------------------------------------------------------------------------------------ feature tree
@dataclass
class Feat:
    name: str
    kind: str                     # root | raise | depress
    D: float = 0.0                # relative height (>0); raise up, depress down
    entry: object = None          # entry polygon (mesh coords)
    parent: "Feat | None" = None
    gt: str = "floor"             # floor | island | lance
    unclamped: bool = False       # raise cone continues below the parent level (wall-straddling boss)
    holes: list = field(default_factory=list)   # [(polygon, type, fixed)]
    children: list = field(default_factory=list)
    level: float = 0.0
    extra_creases: list = field(default_factory=list)

    @property
    def top(self):
        """floor (depress) / top (raise) polygon."""
        return inset(self.entry, self.D) if self.kind != "root" else self.entry

    def add(self, f):
        f.parent = self
        f.level = self.level + (f.D if f.kind == "raise" else -f.D)
        self.children.append(f)
        return f

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    @property
    def tier(self):
        return 0 if self.parent is None else self.parent.tier + 1


def build_tree():
    feats = {}
    plate = box(0, 0, W, H)
    tabs = [rect(285, -20, 315, 0.5), rect(885, -20, 915, 0.5), rect(-20, 325, 0.5, 355), rect(1199.5, 325, 1220, 355)]
    domain = unary_union([plate] + tabs)
    root = Feat("flange", "root", entry=domain)
    root.holes += [(circ(300, -10, 4), "fasten", True), (circ(900, -10, 4), "fasten", True),
                   (circ(-10, 340, 4), "fasten", True), (circ(1210, 340, 4), "fasten", True)]
    for cx, cy in ((27, 21), (1173, 21), (27, 656), (1173, 656)):
        b = root.add(Feat(f"cboss_{int(cx)}_{int(cy)}", "raise", 3.0, circ(cx, cy, 8), gt="island"))
        b.holes.append((circ(cx, cy, 2.5), "fasten", True))
    # ---- perimeter ring: tier-1 band (raise 6) with legs / comb teeth to the bottom edge
    band_out = unary_union([
        rect(54, 42, 1146, 400, 40), rect(54, 300, 1146, 642, 30),
        rect(96, 600, 156, 700), rect(1044, 600, 1104, 700),          # legs (x 8-13 %, 87-92 %)
        rect(462, 600, 498, 700), rect(702, 600, 738, 700)])          # comb teeth between the pockets
    band = root.add(Feat("band", "raise", 6.0, band_out))
    for cx in (69, 1131):
        b = band.add(Feat(f"sboss_{cx}", "raise", 3.0, circ(cx, 101, 8), gt="island"))
        b.holes.append((circ(cx, 101, 2.0), "boss", False))
    for x in (250, 375, 500, 600, 700, 825, 950):
        band.holes.append((circ(x, 61, 3), "band", False))
    for y in (220, 320, 420, 520):
        band.holes += [(circ(70, y, 3), "band", False), (circ(1130, y, 3), "band", False)]
    for x in (480, 720):
        band.holes += [(circ(x, 652, 2.5), "comb", False), (circ(x, 664, 2.5), "comb", False)]
    # ---- plateau (tier 2 of the ring, rel +4 over the band)
    P2 = poly([(84, 155), (165, 74), (1035, 74), (1116, 155), (1116, 612), (84, 612)], 10)
    plat = band.add(Feat("plateau", "raise", 4.0, P2))
    # channels (depress 8): U cap at y 15 %, straight to 74 %, flare into pockets; bulge around the straddling bosses
    ch_l = unary_union([rect(450, 119, 486, 500), circ(468, 119, 18),
                        poly([(450, 499), (486, 499), (540, 548), (410, 548)]),
                        circ(448, 175, 16), circ(448, 466, 16)])
    ch_l = ch_l.buffer(-3, quad_segs=2).buffer(3, quad_segs=2)
    chs = [plat.add(Feat("ch1", "depress", 8.0, ch_l)), plat.add(Feat("ch2", "depress", 8.0, mx(ch_l)))]
    pk = {"pL": rect(156, 525, 444, 600, 8), "pC": rect(516, 525, 684, 600, 8), "pR": rect(756, 525, 1044, 600, 8)}
    pks = {k: plat.add(Feat(k, "depress", 6.0, v)) for k, v in pk.items()}
    pks["pL"].holes.append((rect(225, 556, 255, 574, 2), "opening", False))
    pks["pC"].holes += [(rect(565, 556, 595, 574, 2), "opening", False), (rect(605, 556, 635, 574, 2), "opening", False)]
    pks["pR"].holes.append((rect(933, 556, 963, 574, 2), "opening", False))
    # step creases where the 8-deep channel floor ends inside a 6-deep pocket floor
    for c in chs:
        for p in pks.values():
            c.extra_creases.append(inset(c.entry, 6.0).boundary.intersection(p.top))
    # wall-straddling bosses on the outer channel walls (top r 6, h 3 over the plateau, cone runs into the channel)
    for sgn, ch in ((1, chs[0]), (-1, chs[1])):
        for y in (175, 466):
            cx = 448 if sgn > 0 else W - 448
            yb = H - y
            b = plat.add(Feat(f"wboss_{int(cx)}_{y}", "raise", 3.0, Point(cx, yb).buffer(9, quad_segs=qs(9)), gt="island",
                              unclamped=True))
            b.holes.append((Point(cx, yb).buffer(2.5, quad_segs=qs(2.5)), "boss", False))
            rr = 6.0 + 3.0 + 8.0
            b.extra_creases.append(Point(cx, yb).buffer(rr, quad_segs=qs(rr)).boundary.intersection(ch.top))
    # rect embosses with square hole beside the channels
    for cx in (410, 790):
        for cy in (175, 459):
            e = plat.add(Feat(f"remb_{cx}_{cy}", "raise", 3.0, rect(cx - 8, cy - 18, cx + 8, cy + 18, 4), gt="island"))
            e.holes.append((rect(cx - 3, cy - 3, cx + 3, cy + 3), "square", False))
    # large concentric 2-tier bosses
    for cx in (168, 1032):
        b1 = plat.add(Feat(f"cb2_{cx}", "raise", 3.0, circ(cx, 148, 19), gt="island"))
        b2 = b1.add(Feat(f"cb2_{cx}_t2", "raise", 3.0, circ(cx, 148, 11), gt="island"))
        b2.holes.append((circ(cx, 148, 4), "boss", False))
    # lances (half-shear hooks: raised tab, slot on +x side = free edge touching the floor)
    lances = [(540, y) for y in (215, 270, 325, 380, 435)] + [(666, y) for y in (215, 270, 325, 380, 435)] + \
             [(x, y) for x in (880, 940) for y in (260, 330, 400)]
    for i, (cx, cy) in enumerate(lances):
        f = plat.add(Feat(f"lance_{i}", "raise", 2.0, rect(cx - 8, cy - 10, cx + 4, cy + 10), gt="lance"))
        f.holes.append((rect(cx + 2, cy - 8, cx + 5, cy + 8), "slot", False))
    tt = unary_union([rect(898, 455, 932, 465), rect(910, 464, 920, 485)])
    plat.add(Feat("temb", "raise", 2.0, tt.buffer(-1, quad_segs=2).buffer(1, quad_segs=2), gt="island"))
    for cy in (250, 420):
        e = plat.add(Feat(f"hemb_{cy}", "raise", 3.0, rect(982, cy - 7, 1018, cy + 7, 3), gt="island"))
        e.holes.append((rect(997.5, cy - 2.5, 1002.5, cy + 2.5), "square", False))
    se = plat.add(Feat("slotemb", "raise", 2.0, rect(829, 311, 841, 349, 6), gt="island"))
    se.holes.append((rect(833.5, 317, 836.5, 343, 1.2), "slot", False))
    # openings in the plateau, large round holes
    for cx in (240, 540, 654, 948):
        plat.holes.append((rect(cx - 20, 109, cx + 20, 133, 2), "opening", False))
    plat.holes += [(circ(300, 330, 15), "round", False), (circ(1050, 330, 15), "round", False)]
    # dimple grid (5 % W x 9 % H pitch) on the free plateau floor; every 7th point -> small hole
    occupied = unary_union([c.entry.buffer(8) for c in plat.children] + [h[0].buffer(8) for h in plat.holes])
    free = plat.top.buffer(-10).difference(occupied)
    k = 0
    for i, x in enumerate(np.arange(30, W, 60)):
        for j, y in enumerate(np.arange(30.5, H, 61)):
            if not free.contains(circ(x, y, 6)):
                continue
            k += 1
            if k % 7 == 0:
                plat.holes.append((circ(x, y, 3), "small", False))
            else:
                plat.add(Feat(f"dimple_{i}_{j}", "depress", 1.0, circ(x, y, 5), gt="island"))
    for f in root.walk():
        feats[f.name] = f
    return root, feats


# ------------------------------------------------------------------------------------------------ height field
def _dist_in(poly_, x, y):
    """distance to the boundary for points inside poly_, 0 outside."""
    inside = shapely.contains_xy(poly_, x, y)
    d = np.zeros(x.size)
    if inside.any():
        d[inside] = shapely.distance(shapely.points(x[inside], y[inside]), poly_.boundary)
    return d


def _dist_out(poly_, x, y):
    inside = shapely.contains_xy(poly_, x, y)
    d = np.zeros(x.size)
    o = ~inside
    if o.any():
        d[o] = shapely.distance(shapely.points(x[o], y[o]), poly_)
    return d


def evaluate(root, P):
    """z, owner feature index, flat flag, lower/upper feature index for each point (n, 2)."""
    feats = list(root.walk())
    idx = {f.name: i for i, f in enumerate(feats)}
    n = P.shape[0]
    x, y = P[:, 0].copy(), P[:, 1].copy()
    z = np.zeros(n)
    own = np.zeros(n, np.int64)          # root
    flat = np.ones(n, bool)
    lower = np.full(n, -1)
    upper = np.full(n, -1)

    def sel(g, margin):
        b = g.bounds
        return np.flatnonzero((x >= b[0] - margin) & (x <= b[2] + margin) & (y >= b[1] - margin) & (y <= b[3] + margin))

    def apply(f):
        fi = idx[f.name]
        dep = [c for c in f.children if c.kind == "depress"]
        ras = [c for c in f.children if c.kind == "raise"]
        if dep:
            best = np.zeros(n)
            bi = np.full(n, -1)
            for c in dep:
                ii = sel(c.entry, 0.0)
                ii = ii[own[ii] == fi]
                if ii.size == 0:
                    continue
                d = np.minimum(_dist_in(c.entry, x[ii], y[ii]), c.D)
                upd = d > best[ii] + 1e-9
                best[ii[upd]] = d[upd]
                bi[ii[upd]] = idx[c.name]
            m = bi >= 0
            z[m] -= best[m]
            for k in np.unique(bi[m]):
                mk = m & (bi == k)
                full = best[mk] >= feats[k].D - 1e-6
                own[mk] = k
                flat[mk] = full
                lower[mk] = np.where(full, -1, k)
                upper[mk] = np.where(full, -1, -2)
        if ras:
            for c in ras:
                top = c.top
                margin = c.D + (12.0 if c.unclamped else 0.0)
                ii = sel(top, margin)
                if c.unclamped:
                    allowed = np.isin(own[ii], [fi] + [idx[d.name] for d in dep])
                else:
                    allowed = (own[ii] == fi) & flat[ii]
                    allowed &= shapely.contains_xy(c.entry, x[ii], y[ii])
                ii = ii[allowed]
                if ii.size == 0:
                    continue
                r = c.level - _dist_out(top, x[ii], y[ii])
                hit = r > z[ii] + 1e-9
                jj = ii[hit]
                prev = own[jj].copy()
                z[jj] = r[hit]
                own[jj] = idx[c.name]
                full = r[hit] >= c.level - 1e-6
                flat[jj] = full
                upper[jj] = np.where(full, -1, idx[c.name])
                lower[jj] = np.where(full, -1, prev)
        for c in f.children:
            apply(c)

    apply(root)
    # fix "-2" (step upper = second best sibling): recompute as the deepest sibling that is full at the point
    st = np.flatnonzero(upper == -2)
    if st.size:
        for k in np.unique(own[st]):
            c = feats[k]
            ii = st[own[st] == k]
            for s in c.parent.children:
                if s is c or s.kind != "depress":
                    continue
                d = _dist_in(s.entry, x[ii], y[ii])
                hit = d >= s.D - 1e-6
                upper[ii[hit]] = idx[s.name]
            upper[ii[upper[ii] == -2]] = idx[c.parent.name]
    return z, own, flat, lower, upper, feats


# ------------------------------------------------------------------------------------------------ meshing
def domain_and_creases(root):
    holes = []
    for f in root.walk():
        holes += [h[0] for h in f.holes]
    dom = root.entry.difference(unary_union(holes))
    lines = [dom.boundary]
    for f in root.walk():
        if f.kind == "root":
            continue
        lines.append(f.entry.boundary)
        lines.append(f.top.boundary)
        lines += [g for g in f.extra_creases if not g.is_empty]
    L = unary_union([shapely.set_precision(g, 0.02) for g in lines])
    L = L.intersection(dom.buffer(1e-3))
    L = unary_union([shapely.set_precision(L, 0.02), shapely.set_precision(dom.boundary, 0.02)])
    return dom, L


def faces_of(dom, L):
    out = []
    for p in polygonize(list(L.geoms)):
        if p.area < 1e-4:
            continue
        if dom.contains(p.representative_point()):
            out.append(p)
    return out


def gmsh_mesh(faces, h=HMESH):
    import gmsh
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("General.NumThreads", 1)
    geo = gmsh.model.geo
    pid, lid = {}, {}

    def P(c):
        k = (round(c[0], 3), round(c[1], 3))
        if k not in pid:
            pid[k] = geo.addPoint(k[0], k[1], 0.0, h)
        return pid[k]

    def loop(coords):
        cs = list(coords)[:-1]
        ids = [P(c) for c in cs]
        segs = []
        for a, b in zip(ids, ids[1:] + ids[:1]):
            if a == b:
                continue
            key = (min(a, b), max(a, b))
            if key not in lid:
                lid[key] = geo.addLine(key[0], key[1])
            segs.append(lid[key] if a == key[0] else -lid[key])
        return geo.addCurveLoop(segs)

    for f in faces:
        f = shapely.geometry.polygon.orient(f, 1.0)
        try:
            loops = [loop(f.exterior.coords)] + [loop(r.coords) for r in f.interiors]
            geo.addPlaneSurface(loops)
        except Exception as e:  # pragma: no cover
            print("face fail", e, f.area)
    geo.synchronize()
    opts = {"Mesh.MeshSizeMax": h, "Mesh.MeshSizeMin": 0.3 * h, "Mesh.MeshSizeFromCurvature": 0,
            "Mesh.MeshSizeExtendFromBoundary": 0, "Mesh.MeshSizeFromPoints": 0, "Mesh.Algorithm": 8, "Mesh.RecombineAll": 1,
            "Mesh.RecombinationAlgorithm": 1, "Mesh.SubdivisionAlgorithm": 0, "Mesh.ElementOrder": 1,
            "Mesh.Smoothing": 3}
    for k, v in opts.items():
        gmsh.option.setNumber(k, v)
    gmsh.model.mesh.generate(2)
    from ._gmsh import extract
    X, conn = extract(gmsh)
    gmsh.finalize()
    return X, conn


def build(h=HMESH, cache=None):
    """generate the H6 mesh -> {x0, conn (tri 4th = -1), elem_type, fixed_nodes, n_faces} (gmsh + shapely)."""
    if cache and os.path.exists(cache):
        z = np.load(cache, allow_pickle=False)
        return {k: z[k] for k in z.files}
    root, feats = build_tree()
    dom, L = domain_and_creases(root)
    faces = faces_of(dom, L)
    X, conn = gmsh_mesh(faces, h)
    from beadgraph.topo import Topo

    from ._gmsh import clean
    # drop gmsh flaps at convex hole corners (element folded into the hole: 2 free edges, inconsistent winding)
    X, conn = clean(X, conn)
    for _ in range(3):
        tp = Topo(X, conn)
        nfree = np.zeros(tp.m, int)
        np.add.at(nfree, tp.e2a[tp.free_edges], 1)
        raw = np.cross(X[conn[:, 1]] - X[conn[:, 0]], X[conn[:, 2]] - X[conn[:, 0]])
        bad = (raw[:, 2] < 0) & (nfree >= 2)
        if not bad.any():
            break
        X, conn = clean(X, conn[~bad])
    z, *_ = evaluate(root, X[:, :2])
    X = X.copy()
    X[:, 2] = z
    fx = []
    pts = shapely.points(X[:, 0], X[:, 1])
    for f in root.walk():
        for g, t, fixed in f.holes:
            if fixed:
                fx.append(np.flatnonzero(shapely.distance(pts, g.boundary) < 0.05))
    mesh = {"x0": X, "conn": conn, "elem_type": np.where(conn[:, 3] >= 0, 4, 3).astype(np.int8),
            "fixed_nodes": np.unique(np.concatenate(fx)), "n_faces": np.array(len(faces))}
    if cache:
        np.savez(cache, **mesh)
    return mesh


def fixture_arrays(mesh) -> dict:
    """mesh + ground truth as npz-safe arrays (categorical codes + name tables; no pickle)."""
    gt = ground_truth(mesh)
    out = {"x0": np.asarray(mesh["x0"], np.float64), "conn": np.asarray(mesh["conn"], np.int32),
           "fixed": np.asarray(mesh["fixed_nodes"], np.int32), "gt_tier": gt["tier"].astype(np.int8)}
    for k in ("cls", "piece", "trans", "island", "seg"):
        vals = np.array(["" if v is None else str(v) for v in gt[k]], dtype=object)
        names, codes = np.unique(vals, return_inverse=True)
        out[f"gt_{k}_names"] = names.astype("U")
        out[f"gt_{k}"] = codes.astype(np.int16)
    names = list(EXP_JUNCTIONS)
    out["exp_junction_names"] = np.array(names, dtype="U")
    out["exp_junction_xy"] = np.array([(EXP_JUNCTIONS[k][0], H - EXP_JUNCTIONS[k][1]) for k in names], np.float64)
    eh = expected_holes()
    out["exp_hole_xy"] = np.array([(h["x"], h["y"]) for h in eh], np.float64)
    out["exp_hole_fixed"] = np.array([h["fixed"] for h in eh], bool)
    out["exp_hole_lance_slot"] = np.array([h["type"] == "slot" and h["owner"].startswith("lance") for h in eh], bool)
    return out


def centroids(mesh):
    C = np.asarray(mesh["conn"])
    X = mesh["x0"]
    q = C[:, 3] >= 0
    c = X[C[:, :3]].sum(axis=1)
    c[q] += X[C[q, 3]]
    return c / np.where(q, 4.0, 3.0)[:, None]


# ------------------------------------------------------------------------------------------------ ground truth
BAND_LINES = {   # y_down centrelines of the band segments
    "band_top": [(165, 61), (1035, 61)], "band_TL": [(72, 155), (165, 61)], "band_TR": [(1128, 155), (1035, 61)],
    "band_L": [(72, 155), (72, 624)], "band_R": [(1128, 155), (1128, 624)],
    "strip_a": [(72, 624), (126, 624)], "leg_L": [(126, 624), (126, 680)], "strip_b": [(126, 624), (480, 624)],
    "comb_1": [(480, 624), (480, 680)], "strip_c": [(480, 624), (720, 624)], "comb_2": [(720, 624), (720, 680)],
    "strip_d": [(720, 624), (1074, 624)], "leg_R": [(1074, 624), (1074, 680)], "strip_e": [(1074, 624), (1128, 624)],
}
EXP_JUNCTIONS = {  # y_down
    "TL_side": (72, 155), "TL_top": (165, 61), "TR_side": (1128, 155), "TR_top": (1035, 61),
    "BL_corner": (72, 624), "BR_corner": (1128, 624), "T_legL": (126, 624), "T_comb1": (480, 624), "T_comb2": (720, 624),
    "T_legR": (1074, 624), "ch1_flare": (468, 500), "ch2_flare": (732, 500),
    "step_ch1_pL": (428, 538), "step_ch1_pC": (528, 538), "step_ch2_pC": (672, 538), "step_ch2_pR": (772, 538),
}


def _seg_of_band(P):
    names = list(BAND_LINES)
    best = np.full(P.shape[0], np.inf)
    out = np.empty(P.shape[0], dtype=object)
    pts = shapely.points(P[:, 0], P[:, 1])
    for k in names:
        d = shapely.distance(pts, T(LineString(BAND_LINES[k])))
        m = d < best
        best[m] = d[m]
        out[m] = k
    return out


def ground_truth(mesh, root=None):
    if root is None:
        root, _ = build_tree()
    c = centroids(mesh)
    z, own, flat, lower, upper, feats = evaluate(root, c[:, :2])
    names = np.array([f.name for f in feats], dtype=object)
    ne = c.shape[0]

    def island_root(f):
        r = None
        while f is not None:
            if f.gt in ("island", "lance"):
                r = f
            f = f.parent
        return r
    isl = [island_root(f) for f in feats]
    cls = np.empty(ne, dtype=object)
    piece = np.empty(ne, dtype=object)
    trans = np.empty(ne, dtype=object)
    island = np.empty(ne, dtype=object)
    tier = np.zeros(ne, np.int64)
    for k in np.unique(own):
        m = own == k
        f = feats[k]
        ir = isl[k]
        if ir is not None:
            cls[m] = "lance" if ir.gt == "lance" else "island"
            island[m] = ir.name
            piece[m] = None
            tier[m] = ir.tier
            continue
        fm = m & flat
        cls[fm] = "floor"
        piece[fm] = f.name
        tier[fm] = f.tier
        wm = m & ~flat
        cls[wm] = "wall"
        tier[wm] = f.tier
    # wall elements whose owner is an island but lower is a plain floor stay island; walls of plain features:
    w = cls == "wall"
    up = upper[w]
    lo = lower[w]
    trans[w] = [f"{names[u]}|{names[l]}" for u, l in zip(up, lo)]
    # raise walls: upper = the raise, lower = prev owner -> already (feat, prev); depress walls: (parent|sibling, feat)
    # pieces at root level touching the outline (bottom flange fragments) are flange
    seg = np.empty(ne, dtype=object)
    tr = np.array([t if t is not None else "" for t in trans], dtype=object)
    up_ = np.array([t.split("|")[0] if t else "" for t in tr], dtype=object)
    lo_ = np.array([t.split("|")[1] if t else "" for t in tr], dtype=object)
    yd = H - c[:, 1]
    for k in ("ch1", "ch2"):
        m = (piece == k) | ((cls == "wall") & (lo_ == k) & (up_ == "plateau"))
        seg[m & (yd < 500)] = f"{k}_straight"
        seg[m & (yd >= 500)] = f"{k}_flare"
    for k in ("pL", "pC", "pR"):
        seg[(piece == k) | ((cls == "wall") & (lo_ == k) & (up_ == "plateau"))] = k
    seg[(piece == "plateau") | ((cls == "wall") & (tr == "plateau|band"))] = "plateau"
    seg[piece == "flange"] = "flange"
    jw = (cls == "wall") & np.isin(up_, ["ch1", "ch2", "pL", "pC", "pR"]) & np.isin(lo_, ["ch1", "ch2", "pL", "pC", "pR"])
    seg[jw] = np.array(["J:" + t for t in tr[jw]], dtype=object)
    mb = (piece == "band") | ((cls == "wall") & np.array([t == "band|flange" for t in trans]))
    seg[mb] = _seg_of_band(c[mb, :2])
    return {"cls": cls, "piece": piece, "trans": trans, "island": island, "tier": tier, "seg": seg,
            "owner": names[own], "z": z, "feats": feats}


def expected_holes(root=None):
    if root is None:
        root, _ = build_tree()
    out = []
    for f in root.walk():
        for g, t, fixed in f.holes:
            if g.is_empty:
                continue
            cc = g.centroid
            out.append({"owner": f.name, "type": t, "fixed": fixed, "x": cc.x, "y": cc.y, "area": g.area})
    return out


if __name__ == "__main__":
    import sys
    import time
    t0 = time.time()
    m = build(float(sys.argv[2]) if len(sys.argv) > 2 else HMESH)
    np.savez_compressed(sys.argv[1], **fixture_arrays(m))
    et = np.asarray(m["elem_type"])
    print("nodes", m["x0"].shape[0], "elems", et.size, "quads", int((et == 4).sum()), "trias", int((et == 3).sum()),
          "faces", int(m["n_faces"]), "fixed", m["fixed_nodes"].size, f"{time.time() - t0:.1f}s")
