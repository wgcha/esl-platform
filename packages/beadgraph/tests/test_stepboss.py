"""BG-D-47 (issue #63 B10_D·B11_D BG_BASIS_LEAK): bosses straddling the step where a channel bead ends in a shallower
area. Rim nodes of the bosses shared only with the step's junction-zone walls are outside the check's allowed set; the
basis used to hold back only the foreign-floor contact and moved them with the boss. Basis and checks now use one node
rule (``zones.movable_nodes``)."""
import importlib

import numpy as np
import pytest

import beadgraph as bg
from beadgraph import checks as ck
from beadgraph import zones as zn
from beadgraph.testing import conformance as c

mo = importlib.import_module("beadgraph.morph")    # the package attribute ``beadgraph.morph`` is the function


@pytest.fixture(scope="module")
def sb():
    g, lab, _ = c.classified("stepboss")
    fx = c.load_fixture("stepboss")
    floors = {f["id"]: f for f in g["floors"]}
    segs = [s for s in g["segments"] if s["type"] != "base"]
    ch = max(segs, key=lambda s: (float(floors[s["floor"]]["rel_height"]), -s["id"]))
    return g, lab, fx, ch


def _basis(g, lab, fx, s, kind="D"):
    nom = float(s["D"]) if kind == "D" else float(s["entry_width"])
    return bg.basis(g, lab, fx["x0"], [{"name": "v", "kind": kind, "segs": [s["id"]], "hold": 1}],
                    {"v": [0.7 * nom, 1.3 * nom]}, fixed=fx["fixed"], elems=fx["conn"])


def test_geometry_is_the_issue_63_layout(sb):
    """single channel segment D, two straddling bosses touching the channel floor, the shallower area floor and the
    step junction-zone walls (zones between the area segments and the channel — none lists >= 2 channel segments)."""
    g, lab, fx, ch = sb
    X, C = fx["x0"], fx["conn"]
    B = _basis(g, lab, fx, ch)
    st = B[0]["info"]["straddle"]
    assert len(st) == 2
    jz, isl, cls = (np.asarray(lab[k]) for k in ("junction_zone", "island", "cls"))
    A = ck.allowed_elements(g, lab, X, C, [ch["id"]], (), "D")
    floor_out = ck._Conn(g, X, C).nmask(~A & (cls == 0))
    wall_out = ck._Conn(g, X, C).nmask(~A & (cls == 1) & (jz >= 0))
    for i in st:
        nd = np.unique(C[isl == i][C[isl == i] >= 0])
        assert (wall_out[nd] & ~floor_out[nd]).sum() >= 3          # rim nodes on a foreign junction-zone wall only
    zones = {z["id"]: z for z in g["junction_zones"]}
    inode = ck._Conn(g, X, C).nmask(np.isin(isl, st))
    near = (jz >= 0) & (cls == 1) & inode[np.where(C >= 0, C, 0)].any(axis=1)
    touched = {int(z) for z in np.unique(jz[near])}
    assert touched and all(ch["id"] in zones[z]["adj_segments"] and len(zones[z]["adj_segments"]) == 2
                           for z in touched)


def test_leak_reproduced_without_the_rule_and_fixed_with_it(sb, monkeypatch):
    """pre-fix basis (node rule switched off in the morph: foreign-floor hold only, zero outside the loose node zone)
    -> BG_BASIS_LEAK on every single-segment D variable that has a straddling boss; with the rule -> no leak."""
    g, lab, fx, ch = sb
    X, C = fx["x0"], fx["conn"]
    segs = [s for s in g["segments"] if s["type"] != "base"]
    for s in segs:
        assert ck.basis_leak(_basis(g, lab, fx, s), g, lab, X, C) == [], s["id"]
    monkeypatch.setattr(mo, "movable_nodes", lambda conn, allowed_el: np.ones(conn.n, bool))
    leaks = {s["id"]: ck.basis_leak(_basis(g, lab, fx, s), g, lab, X, C) for s in segs}
    assert all(leaks.values()), leaks
    w = leaks[ch["id"]][0]
    assert w["code"] == "BG_BASIS_LEAK" and w["n"] >= 6 and 0.3 < w["max_mm"] < 1.0


def test_step_walls_stay_and_boss_top_rigid(sb):
    """candidate A of #63: the step walls do not move (no junction-zone auto-inclusion), the boss top translates
    rigidly by the same amount as before the fix (only the rim contact band changes)."""
    g, lab, fx, ch = sb
    X, C = fx["x0"], fx["conn"]
    jz, isl, cls = (np.asarray(lab[k]) for k in ("junction_zone", "island", "cls"))
    zw = np.unique(C[(jz >= 0) & (cls == 1)])
    B = _basis(g, lab, fx, ch)
    nom = float(ch["D"])
    for v in (0.7 * nom, 1.3 * nom):
        x = bg.morph(X, B, {"v": v})
        u = x - X
        assert np.abs(u[zw[zw >= 0]]).max() == 0.0
        for i in B[0]["info"]["straddle"]:
            nd = np.unique(C[isl == i][C[isl == i] >= 0])
            top = nd[X[nd, 2] >= X[nd, 2].max() - 1e-3]
            assert np.linalg.norm(u[top] - u[top].mean(axis=0), axis=1).max() <= 1e-9
            assert abs(abs(u[top, 2].mean()) - 0.3 * nom) < 0.3 * nom     # follows the channel, partially
        r = bg.check(g, lab, X, x, B, {"v": v}, elems=C)
        assert not r["outside_failed"]


def test_basis_and_check_share_one_node_rule():
    """the morph and the checks call the same function; on the fixtures the basis-side element set (bead_zones +
    W parent floor / its islands) equals the label-based one for every single-segment variable."""
    assert mo.movable_nodes is zn.movable_nodes and ck.movable_nodes is zn.movable_nodes
    for nm in ("h5", "stepboss"):
        g, lab, _ = c.classified(nm)
        fx = c.load_fixture(nm)
        X, C = fx["x0"], fx["conn"]
        M = zn.Mesh(g, lab, X, C)
        K = ck._Conn(g, X, C)
        for s in g["segments"]:
            if s["type"] == "base":
                continue
            for kind in ("D", "W"):
                if kind == "W" and s.get("entry_width") is None:
                    continue
                Z = zn.bead_zones(M, [s["id"]], [], kind)
                A = Z["allowed_el"]
                if kind == "W":
                    on_par = [i["id"] for i in g["islands"] if i["parent"] == Z["parent"] and not i["straddle"]]
                    A = A | Z["parent_floor"] | (np.isin(M.lab["island"], on_par) & (M.lab["island"] >= 0))
                A2 = ck.allowed_elements(g, lab, X, C, [s["id"]], (), kind, conn=K)
                assert np.array_equal(A, A2), (nm, s["id"], kind)
                assert np.array_equal(zn.movable_nodes(M, A), zn.movable_nodes(K, A2))


def test_stepboss_conformance():
    assert c.stepboss_morph()["bad"] == []


def test_generator_reproduces_fixture():
    gmsh = pytest.importorskip("gmsh")
    pytest.importorskip("shapely")
    if gmsh.__version__ != "4.15.2":
        pytest.skip(f"gmsh {gmsh.__version__} != lock 4.15.2")
    from beadgraph.testing import synth_stepboss
    m = synth_stepboss.build()
    fx = c.load_fixture("stepboss")
    assert np.array_equal(m["x0"], fx["x0"]) and np.array_equal(m["fixed_nodes"].astype(np.int32), fx["fixed"])
    # gmsh element tag order can differ by process history (a few elements) — compare the element set
    a, b = m["conn"].astype(np.int32), fx["conn"]
    assert np.array_equal(a[np.lexsort(a.T[::-1])], b[np.lexsort(b.T[::-1])])
