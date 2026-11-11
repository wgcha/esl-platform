"""Package conformance checks (contract §9 V-BG-1..7·14, package part) on the frozen fixtures — no gmsh / shapely.
Used by ``python -m beadgraph selftest`` and ``pytest --pyargs beadgraph.testing`` (physicsai CI)."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from functools import lru_cache

import numpy as np

HERE = os.path.dirname(__file__)
FIXTURES = os.path.join(HERE, "fixtures")
EXPECTED = os.path.join(HERE, "expected.json")
MAX_FIXTURE_BYTES = 6 * 1024 * 1024

# V-BG-1 thresholds
H6_MIN = {"class_acc": 0.99, "class_rp": 0.985, "floor_piece_acc": 0.995, "wall_owner_acc": 0.985, "tier_acc": 0.995,
          "segment_elem_acc": 0.985}


def load_fixture(name: str) -> dict:
    with np.load(os.path.join(FIXTURES, f"{name}.npz"), allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


@lru_cache(maxsize=4)
def classified(name: str):
    from ..classify import classify_full
    fx = load_fixture(name)
    return classify_full(fx["x0"], fx["conn"], fx["fixed"], None)


def labels_sha(labels) -> str:
    h = hashlib.sha256()
    for k in sorted(labels):
        h.update(k.encode())
        h.update(np.ascontiguousarray(labels[k], "<i4").tobytes())
    return h.hexdigest()


def graph_sha(graph) -> str:
    from .. import graph_bytes
    return hashlib.sha256(graph_bytes(graph)).hexdigest()


def expected() -> dict:
    with open(EXPECTED, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------------------------------- V-BG-1 / 2 / 3
def h6_metrics() -> dict:
    from .evaluate import evaluate_h6
    g, lab, aux = classified("h6")
    return evaluate_h6(g, lab, load_fixture("h6"), aux["seg_raw"])


def check_h6(r: dict) -> list[str]:
    bad = []
    if r["class_acc"] < H6_MIN["class_acc"]:
        bad.append(f"class_acc {r['class_acc']:.4f}")
    for k, v in r["class"].items():
        if v["recall"] < H6_MIN["class_rp"] or v["precision"] < H6_MIN["class_rp"]:
            bad.append(f"class {k} {v}")
    for k in ("floor_piece_acc", "wall_owner_acc", "tier_acc", "segment_elem_acc"):
        if r[k] < H6_MIN[k]:
            bad.append(f"{k} {r[k]:.4f}")
    if r["segments"]["found_iou50"] != r["segments"]["expected"]:
        bad.append(f"segments {r['segments']['found_iou50']}/{r['segments']['expected']}")
    j = r["junctions"]
    if j["found"] != j["expected"] or j["type_ok"] != j["expected"]:
        bad.append(f"junctions {j['found']}/{j['expected']} types ok {j['type_ok']}")
    i = r["islands"]
    if i["found_iou50"] != i["expected"] or i["lances_found"] != i["lances_expected"] or \
            i["straddle_found"] != i["straddle_expected"]:
        bad.append(f"islands {i}")
    h = r["holes"]
    if h["found"] != h["expected"] or h["fixed_flag_ok"] != h["expected"] or \
            h["lance_slots_found"] != h["lance_slots_expected"]:
        bad.append(f"holes {h}")
    g, lab, aux = classified("h6")
    extra = set(r["segments"]["extra_units"])
    absorbed_spur = {z["id"] for z in g["junction_zones"] if z["reason"] == "spur"}
    if extra and not absorbed_spur:
        bad.append(f"extra segments {sorted(extra)} not absorbed as spur zones")
    return bad


def h5_metrics() -> dict:
    from .evaluate import evaluate_h5
    g, lab, _aux = classified("h5")
    return evaluate_h5(g, lab, load_fixture("h5"))


def check_h5(r: dict) -> list[str]:
    bad = []
    if r["sides"] != ["bottom", "left", "right", "top"]:
        bad.append(f"sides {r['sides']}")
    if len(set(r["v_beads"])) != 2 or -1 in r["v_beads"]:
        bad.append(f"vertical beads {r['v_beads']}")
    if r["ring_label_on_v_walls"]:
        bad.append(f"ring-labelled walls on V1/V2: {r['ring_label_on_v_walls']}")
    if r["junction_types"].get("T") != 2 or r["junction_types"].get("L") != 4:
        bad.append(f"junctions {r['junction_types']}")
    if r["n_zones"] != 6:
        bad.append(f"zones {r['zone_reasons']}")
    return bad


def determinism(name: str) -> dict:
    from ..classify import classify_full
    fx = load_fixture(name)
    g1, l1, _ = classified(name)
    g2, l2, _ = classify_full(fx["x0"], fx["conn"], fx["fixed"], None)
    exp = expected().get(name, {})
    return {"same_graph": graph_sha(g1) == graph_sha(g2), "same_labels": labels_sha(l1) == labels_sha(l2),
            "graph_sha": graph_sha(g1), "labels_sha": labels_sha(l1),
            "expected_graph_sha": exp.get("graph_sha256"), "expected_labels_sha": exp.get("labels_sha256")}


# ------------------------------------------------------------------------------------------- V-BG-4 (a, c, d)
def _partition_equal(a: np.ndarray, b: np.ndarray) -> bool:
    """same partition of elements up to relabelling (-1 = none must match exactly)."""
    if a.shape != b.shape or not np.array_equal(a < 0, b < 0):
        return False
    m = a >= 0
    pairs = np.unique(np.c_[a[m], b[m]], axis=0)
    return len(np.unique(pairs[:, 0])) == len(pairs) == len(np.unique(pairs[:, 1]))


def compare_labels(l0, l1, perm) -> list[str]:
    """l1 is the classification of the permuted mesh (new element i = old element perm[i])."""
    bad = []
    for k in ("cls", "tier"):
        if not np.array_equal(l0[k][perm], l1[k]):
            bad.append(f"{k}: {int((l0[k][perm] != l1[k]).sum())} elements differ")
    for k in ("floor", "segment", "island", "junction_zone", "transition"):
        if not _partition_equal(l0[k][perm], l1[k]):
            bad.append(f"{k}: partition differs")
    return bad


def _kinds(g):
    return {"segments": sorted(s["type"] for s in g["segments"]), "junctions": sorted(j["type"] for j in g["junctions"]),
            "zones": sorted(z["reason"] for z in g["junction_zones"]), "islands": len(g["islands"]),
            "lances": sum(i["lance"] for i in g["islands"]), "holes": len(g["holes"])}


def permuted(fx, seed: int = 7):
    """(c): node + element renumbering, element order shuffle, element node cycling and direction reversal."""
    rng = np.random.default_rng(seed)
    X, C, F = fx["x0"], fx["conn"].astype(np.int64), fx["fixed"].astype(np.int64)
    n, m = X.shape[0], C.shape[0]
    nperm = rng.permutation(n)                     # new node j = old node nperm[j]
    inv = np.empty(n, np.int64)
    inv[nperm] = np.arange(n)
    eperm = rng.permutation(m)                     # new element i = old element eperm[i]
    C2 = C[eperm].copy()
    q = C2[:, 3] >= 0
    shift = rng.integers(0, 4, m)
    rev = rng.random(m) < 0.5
    for i in range(m):
        k = 4 if q[i] else 3
        row = list(C2[i, :k])
        s = int(shift[i]) % k
        row = row[s:] + row[:s]
        if rev[i]:
            row = row[::-1]
        C2[i, :k] = row
    C2 = np.where(C2 >= 0, inv[np.maximum(C2, 0)], -1)
    return X[nperm], C2, inv[F], eperm, nperm


def rigid(fx, seed: int = 11):
    rng = np.random.default_rng(seed)
    ax = rng.normal(size=3)
    ax /= np.linalg.norm(ax)
    th = float(rng.uniform(0.3, 2.5))
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    R = np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K
    t = rng.normal(size=3) * 500.0
    return fx["x0"] @ R.T + t, R, t


def invariance(name: str, with_basis: bool = True) -> dict:
    from .. import basis as _basis
    from ..classify import classify_full
    fx = load_fixture(name)
    g0, l0, _ = classified(name)
    out = {}
    X2, C2, F2, eperm, nperm = permuted(fx)
    g1, l1, _ = classify_full(X2, C2, F2, None)
    out["permuted"] = compare_labels(l0, l1, eperm) + ([] if _kinds(g0) == _kinds(g1) else ["kinds differ"])
    X3, R, _t = rigid(fx)
    g2, l2, _ = classify_full(X3, fx["conn"], fx["fixed"], None)
    out["rigid"] = compare_labels(l0, l2, np.arange(l0["cls"].size)) + ([] if _kinds(g0) == _kinds(g2) else
                                                                         ["kinds differ"])
    if with_basis and not out["rigid"]:
        segs0 = _recipe_segments(g0, l0, fx, name)
        a0 = [g0["segments"][s]["anchor"] for s in segs0]
        segs2 = [int(l2["segment"][a]) for a in a0]
        b0 = _basis(g0, l0, fx["x0"], [{"name": "v", "kind": "D", "segs": segs0, "hold": 1}], {"v": [4.0, 12.0]},
                    fixed=fx["fixed"], elems=fx["conn"])[0]
        b2 = _basis(g2, l2, X3, [{"name": "v", "kind": "D", "segs": segs2, "hold": 1}], {"v": [4.0, 12.0]},
                    fixed=fx["fixed"], elems=fx["conn"])[0]
        V0 = np.zeros_like(fx["x0"])
        V0[b0["idx"]] = b0["vec"]
        V2 = np.zeros_like(fx["x0"])
        V2[b2["idx"]] = b2["vec"] @ R
        err = float(np.abs(V0 - V2).max())
        out["basis_err"] = err
        if err > 1e-9:
            out["rigid"].append(f"basis differs {err:.3g}")
    out["ok"] = not out["permuted"] and not out["rigid"]
    return out


def _recipe_segments(g, lab, fx, name):
    if name == "h5":                                # V1 = left vertical bead (smaller world x)
        v = [s for s in g["segments"] if s["type"] == "channel"]
        v.sort(key=lambda s: _seg_x(fx, lab, s["id"]))
        return [v[0]["id"]]
    ch = [s for s in g["segments"] if s["type"] == "channel"]
    ch.sort(key=lambda s: _seg_x(fx, lab, s["id"]))
    return [ch[0]["id"]] + [s["id"] for s in g["segments"] if s["type"] == "flare" and s["floor"] == ch[0]["floor"]]


def _seg_x(fx, lab, sid):
    C = fx["conn"]
    m = lab["segment"] == sid
    nd = np.unique(C[m][:, :3])
    return float(fx["x0"][nd, 0].mean())


# ------------------------------------------------------------------------------------------- V-BG-5 / 6 (morph)
def h6_recipes(g, lab, fx):
    S = g["segments"]
    plateau = [s["id"] for s in S if s["type"] == "plateau"][0]
    chans = sorted([s for s in S if s["type"] == "channel"], key=lambda s: _seg_x(fx, lab, s["id"]))
    ch = [[c["id"]] + [s["id"] for s in S if s["type"] == "flare" and s["floor"] == c["floor"]] for c in chans]
    pockets = sorted([s for s in S if s["type"] == "pocket"], key=lambda s: abs(_seg_x(fx, lab, s["id"]) - 600.0))
    top = [s["id"] for s in S if s["side"] == "top"]
    band = S[top[0]]["floor"]
    net = [n for n in g["networks"] if n["floor"] == band][0]
    return {"a": [("a", "D", [plateau], [], 2.0)], "b": [("b", "D", ch[0], [], 2.0)], "c": [("c", "W", ch[0], [], 3.0)],
            "d": [("d", "D", [pockets[0]["id"]], [], 2.0)],
            "e": [("e1", "D", ch[0], [], -2.0), ("e2", "D", ch[-1], [], -2.0)],
            "f": [("f", "D", top, [], 2.0)], "g": [("g", "D", net["segments"], net["junction_zones"], 2.0)]}


def run_recipe(g, lab, fx, beads, cfg=None):
    from .. import basis as _basis
    from .. import check as _check
    from .. import morph as _morph
    from ..checks import basis_leak
    X, C, F = fx["x0"], fx["conn"], fx["fixed"]
    bl = [{"name": n, "kind": k, "segs": s, "zones": z, "hold": 1} for n, k, s, z, _dv in beads]
    B0 = _basis(g, lab, X, bl, None, cfg=cfg, fixed=F, elems=C)
    dv = {n: d for n, _k, _s, _z, d in beads}
    rng = {b["name"]: [b["nominal"] - abs(dv[b["name"]]), b["nominal"] + abs(dv[b["name"]])] for b in B0}
    B = _basis(g, lab, X, bl, rng, cfg=cfg, fixed=F, elems=C)
    vals = {b["name"]: b["nominal"] + dv[b["name"]] for b in B}
    x = _morph(X, B, vals)
    r = _check(g, lab, X, x, B, vals, cfg=cfg, elems=C)
    r["leak"] = basis_leak(B)
    r["fixed_mm"] = float(np.linalg.norm(x[F] - X[F], axis=1).max()) if len(F) else 0.0
    r["warnings"] = sorted({w["code"] for b in B for w in b["info"]["warnings"]})
    r["achieved_ratio"] = [b["info"].get("achieved_ratio") for b in B]
    r["basis"] = B
    r["x"] = x
    return r


def descendants_rigid(g, lab, fx, x, B) -> float:
    """max change of node-pair distances inside each exclusive child subtree (vs its own centroid) — rigid = 0."""
    from ..zones import Mesh, bead_zones
    M = Mesh(g, lab, fx["x0"], fx["conn"])
    worst = 0.0
    for b in B:
        if b["kind"] != "D":
            continue
        Z = bead_zones(M, b["segs"], b["info"]["zones_in"], "D")
        nd = np.flatnonzero(M.nmask(Z["ZC"]))
        if nd.size:
            u = x[nd] - fx["x0"][nd]
            worst = max(worst, float(np.linalg.norm(u - u.mean(axis=0), axis=1).max()))
    return worst


def check_h6_morph(name, r, g, lab, fx) -> list[str]:
    bad = []
    if r["inverted"]:
        bad.append(f"{name}: inverted {r['inverted']}")
    if r["outside"]["max_mm"] > 1e-9:
        bad.append(f"{name}: outside {r['outside']}")
    if r["leak"]:
        bad.append(f"{name}: leak {r['leak']}")
    for k, v in r["achieved"].items():
        tol = 1e-3 if name == "c" else 1e-6
        if v is None or v > tol:
            bad.append(f"{name}: achieved {k} {v}")
    if r["island_residual_mm"] > 1e-9:
        bad.append(f"{name}: island residual {r['island_residual_mm']}")
    if r["fixed_mm"] > 1e-12:
        bad.append(f"{name}: fixed moved {r['fixed_mm']}")
    if name in ("b", "e") and any((v or 0) < 0.9 for v in r["achieved_ratio"]):
        bad.append(f"{name}: achieved ratio {r['achieved_ratio']}")
    if name in ("a", "g"):
        d = descendants_rigid(g, lab, fx, r["x"], r["basis"])
        if d > 1e-9:
            bad.append(f"{name}: descendants not rigid {d}")
    if name == "f":
        if "BG_SHARED_CHILD" not in r["warnings"]:
            bad.append("f: no BG_SHARED_CHILD")
        plat = [s["floor"] for s in g["segments"] if s["type"] == "plateau"][0]
        pe = (lab["floor"] == plat) & (lab["cls"] == 0)
        nd = np.unique(fx["conn"][pe][:, :3])
        if float(np.abs(r["x"][nd] - fx["x0"][nd]).max()) > 1e-12:
            bad.append("f: plateau moved")
    if name == "d" and "BG_CORNER_GUARD" not in r["warnings"]:
        bad.append("d: no BG_CORNER_GUARD")
    if name == "b":
        b = r["basis"][0]
        n0 = np.asarray(g["frame"]["n0"], float)
        for iid in b["info"]["straddle"]:
            e = lab["island"] == iid
            nd = np.unique(fx["conn"][e][:, :3])
            h = fx["x0"][nd] @ n0
            top = nd[h >= h.max() - 1e-6]
            err = float(np.abs((r["x"][top] - fx["x0"][top]) @ n0 - b["info"]["sign"] * 2.0).max())
            if err > 1e-9:
                bad.append(f"b: straddling boss {iid} top {err}")
        if not b["info"]["straddle"]:
            bad.append("b: no straddling boss followed the channel")
    return bad


def h5_morph() -> dict:
    """V-BG-6: V1 D ±2, W +4, D default-range end: ring / ring∩V1 / V2 nodes do not move, no inversion, depth exact,
    no new element with aspect > 10, ramp = max(3·ΔD_ext, 3h)."""
    from .evaluate import _gt, centroids
    g, lab, _aux = classified("h5")
    fx = load_fixture("h5")
    X, C = fx["x0"], fx["conn"]
    v1 = _recipe_segments(g, lab, fx, "h5")
    labs = _gt(fx, "lab")
    nodes_of = {k: np.unique(C[np.isin(labs, ks)][:, :3]) for k, ks in
                (("ring", ["ring_f", "ring_s"]), ("v1", ["v1_f", "v1_s"]), ("v2", ["v2_f", "v2_s"]))}
    ring_only = np.setdiff1d(nodes_of["ring"], nodes_of["v1"])
    inter = np.intersect1d(nodes_of["ring"], nodes_of["v1"])
    out, bad = {}, []
    h = float(g["frame"]["h_mm"])
    D = float(g["segments"][v1[0]]["D"])
    for key, kind, dv in (("D+2", "D", 2.0), ("D-2", "D", -2.0), ("W+4", "W", 4.0), ("Dhi", "D", 0.3 * D)):
        r = run_recipe(g, lab, fx, [("v", kind, v1, [], dv)])
        x = r["x"]
        mv = np.linalg.norm(x - X, axis=1)
        a0 = _aspect(X, C)
        a1 = _aspect(x, C)
        moved = mv[C[:, :3]].max(axis=1) > 1e-9
        new_bad = int((moved & (a1 > 10) & (a0 <= 10)).sum())
        ext = abs(dv) if kind == "D" else abs(dv) / 2.0
        ramp_ok = abs(r["basis"][0]["info"]["ramp_mm"] - max(3 * ext, 3 * h)) < 1e-9
        row = {"ring_mm": float(mv[ring_only].max()), "ring_v1_mm": float(mv[inter].max()),
               "v2_mm": float(mv[nodes_of["v2"]].max()), "inverted": r["inverted"], "achieved": r["achieved"],
               "new_aspect_gt10": new_bad, "ramp_ok": ramp_ok, "outside": r["outside"]["max_mm"]}
        out[key] = row
        if row["ring_mm"] > 0 or row["ring_v1_mm"] > 0 or row["v2_mm"] > 0:
            bad.append(f"{key}: ring / V2 moved {row}")
        if row["inverted"] or new_bad or not ramp_ok or row["outside"] > 1e-9:
            bad.append(f"{key}: {row}")
        tol = 1e-3 if kind == "W" else 1e-6
        if any(v is None or v > tol for v in r["achieved"].values()):
            bad.append(f"{key}: achieved {r['achieved']}")
    _ = centroids
    out["bad"] = bad
    return out


def _aspect(X, C):
    q = C[:, 3] >= 0
    P = [X[C[:, i]] for i in range(3)] + [X[np.where(q, C[:, 3], C[:, 0])]]
    L = []
    for i in range(4):
        L.append(np.linalg.norm(P[(i + 1) % 4] - P[i], axis=1))
    L = np.stack(L, 1)
    L[~q, 3] = L[~q, 2]
    L[~q, 2] = np.linalg.norm(P[2][~q] - P[0][~q], axis=1)
    return L.max(1) / np.maximum(L.min(1), 1e-300)


# ------------------------------------------------------------------------------------------- V-BG-14 purity
ALLOWED_IMPORTS = {"numpy", "scipy", "__future__"}
STDLIB = {"copy", "hashlib", "json", "math", "time", "os", "sys", "ast", "functools", "argparse", "collections",
          "struct", "re", "typing", "dataclasses"}


def purity() -> list[str]:
    """package modules (testing generators excepted) import only stdlib / numpy / scipy."""
    root = os.path.dirname(HERE)
    bad = []
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root)
            if rel.startswith("testing" + os.sep) and fn in ("synth_h5.py", "synth_h6.py", "_gmsh.py",
                                                            "test_conformance.py"):
                continue                               # [synth] extra (gmsh, shapely) generators / pytest cases
            with open(p, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for nm in names:
                    top = nm.split(".")[0]
                    if top not in ALLOWED_IMPORTS | STDLIB and top != "beadgraph":
                        bad.append(f"{rel}: import {nm}")
    return bad


def fixtures_size() -> int:
    return sum(os.path.getsize(os.path.join(FIXTURES, f)) for f in os.listdir(FIXTURES))


# ------------------------------------------------------------------------------------------- report
def selftest(full: bool = True) -> dict:
    from .. import RULES, __version__, validate
    rep = {"beadgraph_version": __version__, "rules": RULES, "checks": {}}

    def put(name, bad, **extra):
        rep["checks"][name] = {"ok": not bad, "problems": bad, **extra}
    try:
        r6 = h6_metrics()
        put("V-BG-1 h6 classification", check_h6(r6),
            metrics={k: r6[k] for k in ("class_acc", "floor_piece_acc", "wall_owner_acc", "tier_acc",
                                        "segment_elem_acc", "label_acc_all")})
        r5 = h5_metrics()
        put("V-BG-2 h5 classification", check_h5(r5), metrics=r5)
        exp = expected()
        bad = []
        for nm in ("h5", "h6"):
            d = determinism(nm)
            if not (d["same_graph"] and d["same_labels"]):
                bad.append(f"{nm}: not deterministic")
            if d["graph_sha"] != exp.get(nm, {}).get("graph_sha256") or \
                    d["labels_sha"] != exp.get(nm, {}).get("labels_sha256"):
                bad.append(f"{nm}: sha differs from expected.json (RULES {exp.get('rules')})")
        put("V-BG-3 determinism", bad)
        bad = []
        for nm in (("h5", "h6") if full else ("h5",)):
            inv = invariance(nm)
            bad += [f"{nm}: {p}" for p in inv["permuted"] + inv["rigid"]]
        put("V-BG-4 numbering / orientation / rigid-transform invariance", bad)
        g, lab, _ = classified("h6")
        fx = load_fixture("h6")
        bad = []
        recipes = h6_recipes(g, lab, fx)
        for k in (sorted(recipes) if full else ["b", "d", "f"]):
            r = run_recipe(g, lab, fx, recipes[k])
            bad += check_h6_morph(k, r, g, lab, fx)
        put("V-BG-5 h6 morph", bad)
        m5 = h5_morph()
        put("V-BG-6 h5 morph", m5.pop("bad"), metrics=m5)
        bad = purity()
        try:
            validate(g)
        except ValueError as exc:
            bad.append(str(exc))
        try:
            validate(dict(g, schema="beadgraph/2"))
            bad.append("schema major 2 accepted")
        except ValueError:
            pass
        if fixtures_size() > MAX_FIXTURE_BYTES:
            bad.append(f"fixtures {fixtures_size()} B > 6 MB")
        put("V-BG-14 purity / schema", bad)
    except Exception as exc:                      # noqa: BLE001 — report, exit code 1
        rep["checks"]["error"] = {"ok": False, "problems": [f"{type(exc).__name__}: {exc}"]}
    rep["ok"] = all(v["ok"] for v in rep["checks"].values())
    return rep


def write_expected() -> dict:
    """maintainers: refresh expected.json after a RULES bump (MINOR) — never for a PATCH."""
    from .. import MORPH_RULES, RULES, __version__
    out = {"rules": RULES, "morph_rules": MORPH_RULES, "version": __version__}
    for nm in ("h5", "h6"):
        g, lab, _ = classified(nm)
        out[nm] = {"graph_sha256": graph_sha(g), "labels_sha256": labels_sha(lab),
                   "n_segments": len(g["segments"]), "n_junctions": len(g["junctions"]),
                   "n_zones": len(g["junction_zones"]), "n_islands": len(g["islands"]), "n_holes": len(g["holes"])}
    with open(EXPECTED, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return out
