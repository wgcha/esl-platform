"""kind U (bead position — esl contract esl_bead_pos_u.md §1.1, V-0249-PU-1·2·3·4·5·8·9·21·22·24·25 package part)."""
from __future__ import annotations

import importlib

import numpy as np
import pytest

import beadgraph as bg
from beadgraph.testing import synth_oneside as so
from beadgraph.testing import synth_pos as sp

mo = importlib.import_module("beadgraph.morph")


def _cls(c):
    g, lab = bg.classify(c["nodes"], c["conn"], c["fixed"])
    return g, lab


def _segs(g, typ=None):
    return [s["id"] for s in g["segments"] if s["type"] != "base" and (typ is None or s["type"] == typ)]


def _U(c, g, lab, segs, rng, **kw):
    item = {"name": "u", "kind": "U", "segs": segs, "hold": 1, **kw}
    return bg.basis(g, lab, c["nodes"], [item], {"u": list(rng)} if rng is not None else None, fixed=c["fixed"],
                    elems=c["conn"])


@pytest.fixture(scope="module")
def CH():
    c = so.channel()
    g, lab = _cls(c)
    return c, g, lab


def _full(B, n):
    U = np.zeros((n, 3))
    U[B[0]["idx"]] = B[0]["vec"]
    return U


def test_straight_channel(CH):
    """V-0249-PU-1: D 10·W_open 40·45°, 600×300 aligned quads, U ±10."""
    c, g, lab = CH
    X, C = c["nodes"], c["conn"]
    B = _U(c, g, lab, _segs(g), (-10.0, 10.0))
    v = B[0]
    assert v["kind"] == "U" and v["nominal"] == 0.0
    t = np.array(v["info"]["dir"])
    assert abs(abs(t[1]) - 1.0) < 1e-12 and abs(t[0]) < 1e-12      # channel along x: t⊥ = ±y
    U = _full(B, len(X))
    n0 = np.asarray(g["frame"]["n0"])
    assert np.abs(U @ n0).max() <= 1e-12                          # normal component 0
    m = c["meta"]
    mid = (X[:, 0] > m["x_range"][0] + 80) & (X[:, 0] < m["x_range"][1] - 80)
    bead = mid & (X[:, 1] >= m["y_entry"][0] - 1e-6) & (X[:, 1] <= m["y_entry"][1] + 1e-6)
    t3 = t[0] * np.asarray(g["frame"]["e1"]) + t[1] * np.asarray(g["frame"]["e2"])
    for val in (10.0, -10.0):
        x = bg.morph(X, B, {"u": val})
        d = x - X
        assert np.abs(d[bead] - val * t3).max() <= 1e-3              # entry·walls·edge·floor = ΔU·t⊥
        r = bg.check(g, lab, X, x, B, {"u": val}, elems=C)
        assert r["achieved"]["u"] is not None and r["achieved"]["u"] <= 1e-3
        assert r["outside"]["max_mm"] <= 1e-9 and r["inverted"] == 0
        # width / depth / flank angle unchanged on the straight stretch
        ys = x[bead, 1]
        hz = x[bead, 2]
        assert abs((ys.max() - ys.min()) - (X[bead, 1].max() - X[bead, 1].min())) <= 1e-9
        assert abs((hz.max() - hz.min()) - (X[bead, 2].max() - X[bead, 2].min())) <= 1e-9
    assert v["info"]["band_mm"] == pytest.approx(80.0)            # R_w = k·ext = 8·10 both sides
    assert v["info"]["guard_left"] == 0 and v["info"]["straight_resid_mm"] == 0.0


def test_arc_parallel_curves():
    """V-0249-PU-2: arc R 150 channel, U ±5 → inner / outer parallel curves (radius ±ΔU ±0.05h), width ≤ 0.02h."""
    c = sp.arc()
    g, lab = _cls(c)
    X, C = c["nodes"], c["conn"]
    h = float(g["frame"]["h_mm"])
    B = _U(c, g, lab, _segs(g), (-5.0, 5.0))
    cc = np.asarray(c["meta"]["c"])
    a0, a1 = c["meta"]["span"]
    r0 = np.hypot(X[:, 0] - cc[0], X[:, 1] - cc[1])
    ph = np.arctan2(X[:, 1] - cc[1], X[:, 0] - cc[0])
    am = 0.5 * (a0 + a1)
    mid = np.abs(ph - am) < 0.25 * (a1 - a0)
    E = np.zeros(len(X), bool)
    from beadgraph.zones import Mesh, bead_zones
    M = Mesh(g, lab, X, C)
    E = bead_zones(M, _segs(g), (), "D")["E"]
    inner = mid & E & (r0 < 150.0)
    outer = mid & E & (r0 > 150.0)
    assert inner.sum() > 5 and outer.sum() > 5
    for val in (5.0, -5.0):
        x = bg.morph(X, B, {"u": val})
        r1 = np.hypot(x[:, 0] - cc[0], x[:, 1] - cc[1])
        s = np.sign(np.median((r1 - r0)[outer])) if val else 1.0
        dr_o, dr_i = np.median((r1 - r0)[outer]), np.median((r1 - r0)[inner])
        assert abs(abs(dr_o) - abs(val)) <= 0.05 * h and abs(abs(dr_i) - abs(val)) <= 0.05 * h
        assert np.sign(dr_o) == np.sign(dr_i) == s
        assert abs(dr_o - dr_i) <= 0.02 * h                           # width kept
        r = bg.check(g, lab, X, x, B, {"u": val}, elems=C)
        assert r["inverted"] == 0 and r["outside"]["max_mm"] <= 1e-9
    # t⊥ = left normal of a counter-clockwise (or clockwise) arc → inward / outward is a property of the skeleton
    turn = mo.u_dir(g, _segs(g), B[0]["info"]["orient"])
    assert turn is not None


def test_end_cap_direction(CH):
    """V-0249-PU-3: closed channel end, U +5: end-cap nodes move along the end segment t⊥ (no radial part), bead length
    unchanged."""
    c, g, lab = CH
    X = c["nodes"]
    B = _U(c, g, lab, _segs(g), (-5.0, 5.0))
    x = bg.morph(X, B, {"u": 5.0})
    d = x - X
    m = c["meta"]
    cap = (X[:, 0] <= m["x_range"][0] + m["end_run"] + 1e-6) & (X[:, 1] > m["y_entry"][0] + 1) & \
        (X[:, 1] < m["y_entry"][1] - 1) & (np.linalg.norm(d, axis=1) > 1e-9)
    assert cap.any()
    assert np.abs(d[cap, 0]).max() <= 1e-6                          # radial (x) component 0 at the end
    bead = (X[:, 1] >= m["y_entry"][0] - 1e-6) & (X[:, 1] <= m["y_entry"][1] + 1e-6) & (X[:, 2] < -1e-9)
    assert abs((x[bead, 0].max() - x[bead, 0].min()) - (X[bead, 0].max() - X[bead, 0].min())) <= 1e-6


def test_tee_branch():
    """V-0249-PU-4: T junction, branch U: J = 0, ramp 0 → ΔU inside L, the other branches' own nodes 0."""
    c = sp.tee()
    g, lab = _cls(c)
    X, C = c["nodes"], c["conn"]
    branch = [s["id"] for s in g["segments"] if s["type"] != "base" and
              np.ptp(np.asarray(s["skeleton"])[:, 1]) > np.ptp(np.asarray(s["skeleton"])[:, 0])]
    assert len(branch) == 1
    B = _U(c, g, lab, branch, (-5.0, 5.0))
    U = _full(B, len(X))
    from beadgraph.zones import Mesh, bead_zones
    M = Mesh(g, lab, X, C)
    Z = bead_zones(M, branch, (), "D")
    assert np.abs(U[Z["J"]]).max() == 0.0
    others = [s for s in _segs(g) if s not in branch]
    on = M.nmask(np.isin(lab["segment"], others) | (lab["junction_zone"] >= 0))
    own = M.nmask(np.isin(lab["segment"], branch))
    assert np.abs(U[on & ~own]).max() <= 1e-9
    L = B[0]["info"]["ramp_mm"]
    from scipy.spatial import cKDTree
    dJ, _ = cKDTree(M.P[Z["J"]]).query(M.P)
    E = Z["E"]
    ramp = E & (dJ < L)
    full = E & (dJ > L + 5.0)
    assert np.linalg.norm(U[full], axis=1).min() > 0.999
    assert np.linalg.norm(U[ramp], axis=1).max() < 1.0
    assert not any(w["code"] == "PU_PARTIAL" for w in B[0]["info"]["warnings"])


def test_owned_island_rigid_and_held():
    """V-0249-PU-5·24: an owned boss island moves with the bead (in-plane = t⊥ ±1e-9); a fixed node on it = held."""
    c = sp.boss()
    g, lab = _cls(c)
    X = c["nodes"]
    B = _U(c, g, lab, _segs(g, "channel"), (-6.0, 6.0))
    U = _full(B, len(X))
    t = np.array(B[0]["info"]["dir"])
    t3 = t[0] * np.asarray(g["frame"]["e1"]) + t[1] * np.asarray(g["frame"]["e2"])
    from beadgraph.zones import Mesh
    M = Mesh(g, lab, X, c["conn"])
    isl = M.nmask(lab["island"] == 0)
    assert np.abs(U[isl] - t3).max() <= 1e-9
    # held: a fixed node on the boss
    k = int(np.flatnonzero(isl)[0])
    c2 = dict(c, fixed=np.r_[c["fixed"], k])
    g2, lab2 = _cls(c2)
    B2 = _U(c2, g2, lab2, _segs(g2, "channel"), (-6.0, 6.0))
    U2 = _full(B2, len(X))
    assert np.abs(U2[M.nmask(lab2["island"] == 0)]).max() == 0.0
    assert any(w["code"] == "BG_ISLAND_HELD" for w in B2[0]["info"]["warnings"])
    x = bg.morph(X, B2, {"u": 6.0})
    assert bg.check(g2, lab2, X, x, B2, {"u": 6.0}, elems=c["conn"])["inverted"] == 0


def test_hold_nodes_tie(CH):
    """V-0249-PU-25 (package part): hold_nodes (jig tie) inside the band do not move; tie_max reported."""
    c, g, lab = CH
    X = c["nodes"]
    m = c["meta"]
    k = int(np.argmin(np.hypot(X[:, 0] - 300.0, X[:, 1] - (m["y_entry"][1] + 20.0)) + 1e3 * np.abs(X[:, 2])))
    B = _U(c, g, lab, _segs(g), (-10.0, 10.0), hold_nodes=[k])
    U = _full(B, len(X))
    assert np.abs(U[k]).max() == 0.0 and B[0]["info"]["tie_max"] == 0.0
    B0 = _U(c, g, lab, _segs(g), (-10.0, 10.0))
    assert np.linalg.norm(_full(B0, len(X))[k]) > 0.1               # without it the band moves that node


def test_dwu_superposition(CH):
    """V-0249-PU-8: D·W·U bases add (morph = x0 + ΣΔ·B ±1e-12); U changes neither depth nor width."""
    c, g, lab = CH
    X, C = c["nodes"], c["conn"]
    sg = _segs(g)
    B = bg.basis(g, lab, X, [{"name": "d", "kind": "D", "segs": sg, "hold": 1},
                             {"name": "w", "kind": "W", "segs": sg, "hold": 1},
                             {"name": "u", "kind": "U", "segs": sg, "hold": 1}],
                 {"d": [8.0, 12.0], "w": [36.0, 44.0], "u": [-5.0, 5.0]}, fixed=c["fixed"], elems=C)
    vals = {"d": 11.0, "w": 42.0, "u": 4.0}
    x = bg.morph(X, B, vals)
    ref = X.copy()
    for v in B:
        ref[v["idx"]] += (vals[v["name"]] - v["nominal"]) * v["vec"]
    assert np.abs(x - ref).max() <= 1e-12
    xdw = bg.morph(X, B, {"d": 11.0, "w": 42.0})
    m = c["meta"]
    mid = (X[:, 0] > m["x_range"][0] + 80) & (X[:, 0] < m["x_range"][1] - 80)
    e0 = mid & (np.abs(X[:, 1] - m["y_entry"][0]) < 1e-6) & (np.abs(X[:, 2]) < 1e-9)
    e1 = mid & (np.abs(X[:, 1] - m["y_entry"][1]) < 1e-6) & (np.abs(X[:, 2]) < 1e-9)
    w_u = np.median(x[e1, 1]) - np.median(x[e0, 1])
    w_0 = np.median(xdw[e1, 1]) - np.median(xdw[e0, 1])
    assert abs(w_u - w_0) <= 1e-3
    assert np.abs((x - xdw)[:, 2]).max() <= 1e-12


def test_closed_and_point_skeleton_refused():
    """V-0249-PU-21 (package part): a closed loop skeleton (annulus) is detected (``u_closed``) and kind U refuses it."""
    c = sp.annulus()
    g, lab = _cls(c)
    s = [x for x in g["segments"] if x["type"] != "base"][0]
    assert mo.u_closed(s, g["frame"]["h_mm"])
    with pytest.raises(bg.BeadgraphError):
        _U(c, g, lab, [s["id"]], (-5.0, 5.0))
    g2, _l = _cls(so.channel())
    assert not mo.u_closed([x for x in g2["segments"] if x["type"] != "base"][0], g2["frame"]["h_mm"])


def test_ext_without_range_and_ramp(CH):
    """V-0249-PU-22 (package part): no range → ext = range_rel·W_ref (not 0), R_w = k·ext, L = ramp_k·ext."""
    c, g, lab = CH
    B = _U(c, g, lab, _segs(g), None, range_rel=0.25)
    i = B[0]["info"]
    assert i["ext"] == pytest.approx(0.25 * 40.0) and i["w_ref"] == pytest.approx(40.0)
    assert i["band_mm"] == pytest.approx(8.0 * i["ext"]) and i["ramp_mm"] == pytest.approx(3.0 * i["ext"])


def test_gaps_feasible_inputs():
    """u_gaps: + / − side gaps of the straight entry samples (parallel channels 20 mm apart → the near side g = 20)."""
    c = so.parallel(gap=20.0)
    g, lab = _cls(c)
    sg = sorted(_segs(g), key=lambda s: np.mean(np.asarray(g["segments"][s]["skeleton"])[:, 1]))
    gp = mo.u_gaps(g, lab, c["nodes"], c["conn"], [sg[0]], fixed=c["fixed"])
    near = [gp["g_plus"], gp["g_minus"]]
    assert min(x for x in near if x is not None) == pytest.approx(20.0, abs=1.0)


def test_deterministic(CH):
    c, g, lab = CH
    a = _U(c, g, lab, _segs(g), (-8.0, 6.0))[0]
    b = _U(c, g, lab, _segs(g), (-8.0, 6.0))[0]
    assert np.array_equal(a["idx"], b["idx"]) and np.array_equal(a["vec"], b["vec"])


def test_version_constants():
    """V-0249-PU-9: package 1.3.0, U_RULES 1, output version / RULES / MORPH_RULES / DF / W1 unchanged."""
    assert bg.__version__ == "1.3.0" and bg.U_RULES == 1 and bg.OUTPUT_VERSION == "1.1.0"
    assert (bg.RULES, bg.MORPH_RULES, bg.DF_RULES, bg.W1_RULES) == (1, 2, 1, 1)
