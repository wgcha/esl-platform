"""Verifier fix v0.17.0 (BG-D-32·34): the outside-zero checks use an allowed set computed from the graph labels
(``checks.allowed_elements``), not the basis zone, and count a node shared with an outside element as outside.

Probe origin: vprobe/outside.py, vprobe/shared.py (H6 ring left / right D moved 2 shared-child wall nodes of the
neighbouring segment 0.13-0.15 mm and the design stayed READY)."""
import numpy as np
import pytest

import beadgraph as bg
from beadgraph import checks as ck
from beadgraph.testing import conformance as c
from beadgraph.zones import Mesh, bead_zones


def _ring(g, side):
    return next(s for s in g["segments"] if s["type"] == "ring" and s["side"] == side)


@pytest.fixture(scope="module")
def h6():
    g, lab, _ = c.classified("h6")
    fx = c.load_fixture("h6")
    return g, lab, fx


@pytest.mark.parametrize("side", ["left", "right"])
def test_h6_ring_side_outside_zero(h6, side):
    """H6 ring left / right D (shared child = the plateau): every node of an element outside A_v stays at 0 (1e-6)
    at the default-range ends and at ΔD = 2 mm; the label-based basis-leak check is clean."""
    g, lab, fx = h6
    X, C = fx["x0"], fx["conn"]
    s = _ring(g, side)
    nom = float(s["D"])
    for dv in (0.3 * nom, 2.0):
        ext = max(dv, 0.3 * nom)
        B = bg.basis(g, lab, X, [{"name": "v", "kind": "D", "segs": [s["id"]], "hold": 1}],
                     {"v": [nom - ext, nom + ext]}, fixed=fx["fixed"], elems=C)
        assert ck.basis_leak(B, g, lab, X, C) == []
        assert any(w["code"] == "BG_SHARED_CHILD" for w in B[0]["info"]["warnings"])
        A = ck.allowed_elements(g, lab, X, C, [s["id"]], (), "D")
        out_nodes = np.zeros(X.shape[0], bool)
        out_nodes[np.unique(C[~A][C[~A] >= 0])] = True
        for v in (nom - dv, nom + dv):
            x = bg.morph(X, B, {"v": v})
            u = np.linalg.norm(x - X, axis=1)
            assert float(u[out_nodes].max()) <= 1e-6, (side, v)
            r = bg.check(g, lab, X, x, B, {"v": v}, elems=C)
            assert not r["outside_failed"] and r["outside"]["n"] == 0, r["outside"]


def test_shared_child_wall_boundary_nodes_are_ramp_zero(h6):
    """the fix in the zone: shared-child wall nodes (Z_SC) that touch the rest of that wall (owned by the neighbouring
    segment) are in the Dirichlet-zero set J."""
    g, lab, fx = h6
    M = Mesh(g, lab, fx["x0"], fx["conn"])
    for side in ("left", "right"):
        Z = bead_zones(M, [_ring(g, side)["id"]], [], "D")
        assert Z["shared"]
        nsc = M.nmask(Z["ZSC"])
        rest = M.nmask(~Z["allowed_el"] & (M.lab["cls"] == 1))
        both = nsc & rest
        assert both.any() and Z["J"][both].all()


def test_strict_check_is_independent_of_the_basis_zone(h6):
    """a basis whose zone wrongly covers outside nodes: the legacy zone check passes, the label-based checks catch it."""
    g, lab, fx = h6
    X, C = fx["x0"], fx["conn"]
    s = _ring(g, "left")
    nom = float(s["D"])
    B = bg.basis(g, lab, X, [{"name": "v", "kind": "D", "segs": [s["id"]], "hold": 1}],
                 {"v": [0.7 * nom, 1.3 * nom]}, fixed=fx["fixed"], elems=C)
    allowed = ck.strict_allowed_nodes(g, lab, X, C, B)["v"]
    zone = np.zeros(X.shape[0], bool)
    zone[B[0]["zone"]] = True
    gap = np.flatnonzero(zone & ~allowed)               # in the basis zone, but a node of an outside element
    assert gap.size
    k = gap[0]
    bad = dict(B[0])
    bad["idx"] = np.r_[B[0]["idx"], k].astype(np.int64)
    bad["vec"] = np.r_[B[0]["vec"], [[0.0, 0.0, 0.1]]]
    assert ck.basis_leak([bad]) == []                                   # zone-only check: blind
    leak = ck.basis_leak([bad], g, lab, X, C)
    assert leak and leak[0]["n"] == 1
    x = bg.morph(X, [bad], {"v": nom + 1.0})
    assert not ck.outside_moved(X, x, [bad], {"v": nom + 1.0}, 1e-6)["failed"]
    om = ck.outside_moved(X, x, [bad], {"v": nom + 1.0}, 1e-6, graph=g, labels=lab, elems=C)
    assert om["failed"] and om["n"] == 1 and abs(om["max_mm"] - 0.1) < 1e-9


@pytest.mark.parametrize("name", ["h5", "h6"])
def test_every_variable_outside_zero(name):
    """all single-segment D / W variables and every network D at the default-range ends: label-based outside max 0
    (W includes the parent-floor blend band and its islands, BG-D-30) and no basis leak."""
    g, lab, _ = c.classified(name)
    fx = c.load_fixture(name)
    X, C = fx["x0"], fx["conn"]
    fixed = fx.get("fixed", np.zeros(0, np.int64))
    beads = [([s["id"]], s, []) for s in g["segments"] if s["type"] != "base"]
    beads += [(list(nw["segments"]), None, list(nw["junction_zones"])) for nw in g["networks"]]
    n = 0
    for segs, s, zones in beads:
        for kind in ("D", "W"):
            if kind == "W" and (s is None or s.get("entry_width") is None):
                continue
            nom = float(np.mean([g["segments"][q]["D"] for q in segs])) if kind == "D" else float(s["entry_width"])
            ext = (0.3 if kind == "D" else 0.2) * nom
            B = bg.basis(g, lab, X, [{"name": "v", "kind": kind, "segs": segs, "hold": 1, "zones": zones}],
                         {"v": [nom - ext, nom + ext]}, fixed=fixed, elems=C)
            assert ck.basis_leak(B, g, lab, X, C) == [], (segs, kind)
            allowed = ck.strict_allowed_nodes(g, lab, X, C, B)["v"]
            for v in (nom - ext, nom + ext):
                u = np.linalg.norm(bg.morph(X, B, {"v": v}) - X, axis=1)
                assert float(u[~allowed].max(initial=0.0)) <= 1e-9, (segs, kind, v)
            n += 1
    assert n >= (6 if name == "h5" else 30)
