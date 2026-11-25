"""beadgraph 1.2.0 — kind DF (depth, floor width kept, flank angle kept), kind W1 (one-sided entry width) and
``one_side`` (esl contract esl_bead_depth_mode.md §1.2.1·§1.6, V-0247-DM-1·2·5·18·19·20·23·28·29)."""
import json
import subprocess
import sys

import numpy as np
import pytest

import beadgraph as bg
from beadgraph.checks import basis_leak
from beadgraph.oneside import measure
from beadgraph.testing import synth_oneside as so
from beadgraph.zones import Mesh


def _cls(c):
    g, lab = bg.classify(c["nodes"], c["conn"], c["fixed"])
    return g, lab


def _basis(c, g, lab, kind, segs, ext, zones=()):
    X, C, F = c["nodes"], c["conn"], c["fixed"]
    bl = [{"name": "v", "kind": kind, "segs": segs, "zones": list(zones), "hold": 1, "ramp": "end"}]
    nom = bg.basis(g, lab, X, bl, None, fixed=F, elems=C)[0]["nominal"]
    return bg.basis(g, lab, X, bl, {"v": [nom - ext, nom + ext]}, fixed=F, elems=C)


def _run(c, g, lab, B, vals):
    X, C = c["nodes"], c["conn"]
    vv = {b["name"]: b["nominal"] + vals[b["name"]] for b in B}
    x = bg.morph(X, B, vv)
    return x, bg.check(g, lab, X, x, B, vv, elems=C)


def _section(c, x):
    """mid-channel medians (straight, full ramp): entry lines y0 / y1, floor edges y0 / y1, depth."""
    X, m = c["nodes"], c["meta"]
    xm = (X[:, 0] > m["x_range"][0] + 80) & (X[:, 0] < m["x_range"][1] - 80)
    at = lambda y, z: xm & (np.abs(X[:, 1] - y) < 1e-6) & (np.abs(X[:, 2] - z) < 1e-9)  # noqa: E731
    e0, e1 = at(m["y_entry"][0], 0.0), at(m["y_entry"][1], 0.0)
    f0, f1 = at(m["y_floor"][0], -m["D"]), at(m["y_floor"][1], -m["D"])
    fl = xm & (np.abs(X[:, 2] + m["D"]) < 1e-9)
    y = lambda k: float(np.median(x[k, 1]))  # noqa: E731
    dep = -float(np.median(x[fl, 2]))
    return {"W_open": y(e1) - y(e0), "W_top": y(f1) - y(f0), "D": dep,
            "th0": float(np.degrees(np.arctan2(dep, y(f0) - y(e0)))),
            "th1": float(np.degrees(np.arctan2(dep, y(e1) - y(f1)))), "floor": fl}


@pytest.mark.parametrize("theta", [(45.0, 45.0), (60.0, 60.0), (45.0, 60.0)])
@pytest.mark.parametrize("dD", [3.0, -3.0])
def test_df_channel_v1_v28(theta, dD):
    """V-0247-DM-1·28: floor plan 0, entry = W_open + ΔD·(cotθ0 + cotθ1), each wall keeps its own angle."""
    c = so.channel(theta=theta)
    g, lab = _cls(c)
    sid = [s["id"] for s in g["segments"] if s["type"] != "base"]
    B = _basis(c, g, lab, "DF", sid, 3.0)
    x, r = _run(c, g, lab, B, {"v": dD})
    X = c["nodes"]
    sec = _section(c, x)
    cot = [1.0 / np.tan(np.radians(t)) for t in theta]
    assert np.abs((x - X)[sec["floor"]][:, :2]).max() <= 1e-12
    assert abs(sec["W_open"] - (40.0 + dD * sum(cot))) <= 1e-3
    assert abs(sec["W_top"] - (40.0 - 10.0 * sum(cot))) <= 1e-6
    assert abs(sec["th0"] - theta[0]) <= 0.05 and abs(sec["th1"] - theta[1]) <= 0.05
    assert abs(sec["D"] - (10.0 + dD)) <= 1e-6
    assert r["achieved"]["v"] <= 1e-6 and r["outside"]["max_mm"] <= 1e-9 and r["inverted"] == 0
    assert basis_leak(B, g, lab, X, c["conn"]) == []
    info = B[0]["info"]
    assert info["floor_plan_max_mm"] == 0.0
    assert not any(w["code"] == "BG_CORNER_GUARD" for w in info["warnings"])
    assert abs(np.degrees(np.arctan(1.0 / info["cot_med"])) - (theta[0] if theta[0] == theta[1] else 45.0)) <= 1.0


def test_entry_fixed_d_v2():
    """V-0247-DM-2: kind D (entry_fixed) unchanged — entry kept, floor narrows by 2ΔD·cotθ, angle kept."""
    c = so.channel(theta=(60.0, 60.0))
    g, lab = _cls(c)
    sid = [s["id"] for s in g["segments"] if s["type"] != "base"]
    B = _basis(c, g, lab, "D", sid, 3.0)
    x, _r = _run(c, g, lab, B, {"v": 3.0})
    sec = _section(c, x)
    cot = 1.0 / np.tan(np.radians(60.0))
    assert abs(sec["W_open"] - 40.0) <= 1e-9
    assert abs(sec["W_top"] - (40.0 - 20.0 * cot - 6.0 * cot)) <= 1e-6
    assert abs(sec["th0"] - 60.0) <= 0.05


def test_df_w_sum_v5():
    """V-0247-DM-5: D (DF) + W together — W_top' = W_top + ΔW, W_open' = W_open + ΔW + 2ΔD·cotθ, linear sum exact."""
    c = so.channel(theta=(45.0, 45.0))
    g, lab = _cls(c)
    sid = [s["id"] for s in g["segments"] if s["type"] != "base"]
    X, C, F = c["nodes"], c["conn"], c["fixed"]
    bl = [{"name": "d", "kind": "DF", "segs": sid, "hold": 1}, {"name": "w", "kind": "W", "segs": sid, "hold": 1}]
    B = bg.basis(g, lab, X, bl, {"d": [7.0, 13.0], "w": [36.0, 44.0]}, fixed=F, elems=C)
    vals = {"d": 13.0, "w": 44.0}
    x = bg.morph(X, B, vals)
    sec = _section(c, x)
    assert abs(sec["W_top"] - (20.0 + 4.0)) <= 1e-3 and abs(sec["W_open"] - (40.0 + 4.0 + 6.0)) <= 1e-3
    assert abs(sec["th0"] - 45.0) <= 0.05
    xd = bg.morph(X, B, {"d": 13.0})
    xw = bg.morph(X, B, {"w": 44.0})
    assert np.abs((xd - X) + (xw - X) - (x - X)).max() <= 1e-12


@pytest.fixture(scope="module")
def ONE():
    out = {}
    for k in "abd":
        c = so.oneside(k)
        g, lab = _cls(c)
        out[k] = (c, g, lab)
    return out


SEG = {"a": 1, "b": 2, "d": 1}
FIXED = {"a": "shared", "b": "junction", "d": "child"}


@pytest.mark.parametrize("case", "abd")
def test_one_side_measure_v18(ONE, case):
    c, g, lab = ONE[case]
    r = bg.one_side(g, lab, c["nodes"], c["conn"], [SEG[case]], min_nodes=3)[SEG[case]]
    h = c["meta"]["h"]
    run = c["meta"]["run"]
    assert r["ok"] and r["reason"] is None and r["n_other"] < 3 <= r["n_open"]
    assert abs(r["d_open"] - r["d_edge_open"] - run) <= 0.5 * h
    assert r["fixed"][FIXED[case]] >= 3
    assert r["width"] == pytest.approx(r["d_open"] + r["d_fixed"], abs=1e-3)
    json.dumps(r)                                   # JSON-able


@pytest.mark.parametrize("case", "abd")
@pytest.mark.parametrize("dW", [4.0, -4.0])
def test_w1_basis_v18(ONE, case, dW):
    """V-0247-DM-18: open side moves ΔW (entry + walls + floor edge), fixed side 0, floor width +ΔW, achieved ≤ 1e-3."""
    c, g, lab = ONE[case]
    X, C = c["nodes"], c["conn"]
    B = _basis(c, g, lab, "W1", [SEG[case]], 4.0)
    x, r = _run(c, g, lab, B, {"v": dW})
    assert r["achieved"]["v"] is not None and r["achieved"]["v"] <= 1e-3
    assert r["outside"]["max_mm"] <= 1e-9 and r["inverted"] == 0 and basis_leak(B, g, lab, X, C) == []
    M = Mesh(g, lab, X, C)
    from beadgraph.morph import _skel_full
    from beadgraph.zones import bead_zones
    Z = bead_zones(M, [SEG[case]], (), "W")
    u = np.linalg.norm(x - X, axis=1)
    side = B[0]["info"]["open_side"][SEG[case]]
    fx = np.flatnonzero(Z["nW"] | (Z["nF"] & M.nmask(~Z["ZF"])))
    _d, _n, inner, sd, _sid = _skel_full(M, [SEG[case]], M.P[fx])
    fixed_side = fx[(sd == -side) & inner]
    assert fixed_side.size and u[fixed_side].max() <= 1e-12
    ent = np.flatnonzero(Z["E"])
    _d, _n, inn, sde, _s = _skel_full(M, [SEG[case]], M.P[ent])
    ent = ent[inn & (sde == side)]
    mid = ent[np.abs(u[ent] - abs(dW)) <= 1e-3]
    assert mid.size >= 0.5 * ent.size


@pytest.mark.parametrize("case", "abd")
def test_df_one_side_v19(ONE, case):
    """V-0247-DM-19: DF on one-sided segments — achieved depth, floor plan 0 at full ramp, no inversion; (a) shared
    child fixed side steepens -> steep_deg = [θ_f, atan((h_f + ΔD_ext)/r_f)]."""
    c, g, lab = ONE[case]
    X, C = c["nodes"], c["conn"]
    B = _basis(c, g, lab, "DF", [SEG[case]], 3.0)
    x, r = _run(c, g, lab, B, {"v": 3.0})
    assert r["achieved"]["v"] <= 1e-6 and r["inverted"] == 0 and r["outside"]["max_mm"] <= 1e-9
    assert basis_leak(B, g, lab, X, C) == []
    idx = B[0]["info"]["achieved_idx"]
    assert np.abs((x - X)[idx][:, :2]).max() <= 1e-12
    if case == "a":
        m = c["meta"]
        sd = B[0]["info"]["steep_deg"]
        assert sd is not None and abs(sd[0] - np.degrees(np.arctan2(m["h_f"], m["r_f"]))) <= 0.05
        assert abs(sd[1] - np.degrees(np.arctan2(m["h_f"] + 3.0, m["r_f"]))) <= 0.05


def test_df_w1_sum_v20(ONE):
    c, g, lab = ONE["b"]
    X, C, F = c["nodes"], c["conn"], c["fixed"]
    bl = [{"name": "d", "kind": "DF", "segs": [2], "hold": 1}, {"name": "w", "kind": "W1", "segs": [2], "hold": 1}]
    B = bg.basis(g, lab, X, bl, {"d": [7.0, 13.0], "w": [36.0, 44.0]}, fixed=F, elems=C)
    x = bg.morph(X, B, {"d": 13.0, "w": 44.0})
    xd, xw = bg.morph(X, B, {"d": 13.0}), bg.morph(X, B, {"w": 44.0})
    assert np.abs((xd - X) + (xw - X) - (x - X)).max() <= 1e-12


def test_w1_rejects_two_sided_and_edge():
    """W1 refuses a two-sided segment (TWO_SIDED); EDGE when the fixed-side floor boundary is on the plate edge."""
    c = so.channel()
    g, lab = _cls(c)
    sid = [s["id"] for s in g["segments"] if s["type"] != "base"]
    with pytest.raises(bg.BeadgraphError):
        bg.basis(g, lab, c["nodes"], [{"name": "v", "kind": "W1", "segs": sid, "hold": 1}], None,
                 fixed=c["fixed"], elems=c["conn"])
    assert bg.one_side(g, lab, c["nodes"], c["conn"], sid)[sid[0]]["reason"] == "TWO_SIDED"
    cc = so.oneside("d")
    g2, lab2 = _cls(cc)
    M = Mesh(g2, lab2, cc["nodes"], cc["conn"])
    every = np.ones(M.n, bool)                      # every node "on the outer edge" -> fixed side on the edge
    assert measure(M, [1], min_nodes=3, edge_nodes=every)[1]["reason"] == "EDGE"


@pytest.mark.xfail(strict=True, reason="계약 보정 필요 DM-C1-2: H5 network DF +2 — 2 parent-floor band elements invert "
                   "between two entry lines 20 mm apart (nearest-E band copy jump); measured, not relaxed")
def test_df_network_and_area_v29():
    """V-0247-DM-29 (package part): DF on the H5 network (ring + T, junction zones) and on the H6 area pocket (d) —
    floor plan 0 at full ramp, no inversion, no leak."""
    from beadgraph.testing import conformance as cf
    g, lab, _ = cf.classified("h5")
    fx = cf.load_fixture("h5")
    X, C, F = fx["x0"], fx["conn"], fx["fixed"]
    for n in g["networks"]:
        bl = [{"name": "n", "kind": "DF", "segs": n["segments"], "zones": n["junction_zones"], "hold": 1}]
        B = bg.basis(g, lab, X, bl, None, fixed=F, elems=C)
        nom = B[0]["nominal"]
        B = bg.basis(g, lab, X, bl, {"n": [nom - 2.0, nom + 2.0]}, fixed=F, elems=C)
        x = bg.morph(X, B, {"n": nom + 2.0})
        r = bg.check(g, lab, X, x, B, {"n": nom + 2.0}, elems=C)
        assert r["inverted"] == 0 and r["outside"]["max_mm"] <= 1e-9 and r["achieved"]["n"] <= 1e-6
        idx = B[0]["info"]["achieved_idx"]
        assert np.abs((x - X)[idx] - ((x - X)[idx] @ np.asarray(g["frame"]["n0"]))[:, None]
                      * np.asarray(g["frame"]["n0"])).max() <= 1e-9
        assert basis_leak(B, g, lab, X, C) == []


def test_version_cli_v23():
    out = subprocess.run([sys.executable, "-m", "beadgraph", "version"], capture_output=True, text=True, check=True)
    v = json.loads(out.stdout)
    assert {k: v[k] for k in ("version", "output_version", "rules", "morph_rules", "df_rules", "w1_rules")} == \
        {"version": "1.2.0", "output_version": "1.1.0", "rules": 1, "morph_rules": 2, "df_rules": 1, "w1_rules": 1}
    g, _lab = bg.classify(*(lambda c: (c["nodes"], c["conn"], c["fixed"]))(so.channel()))
    assert g["version"] == bg.OUTPUT_VERSION == "1.1.0"


def test_one_side_deterministic(ONE):
    c, g, lab = ONE["a"]
    a = bg.one_side(g, lab, c["nodes"], c["conn"], [1, 2, 3, 4])
    b = bg.one_side(g, lab, c["nodes"], c["conn"], [4, 3, 2, 1])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
