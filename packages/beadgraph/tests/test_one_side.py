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
        for v in (nom + 2.0, nom - 2.0):       # DM-C1-2: DF band = distance-weighted mix -> no flip between entry lines
            x = bg.morph(X, B, {"n": v})
            r = bg.check(g, lab, X, x, B, {"n": v}, elems=C)
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


def _cols(g, lab, X, C, x, segs, zones, dD):
    from scipy.spatial import cKDTree

    from beadgraph.zones import bead_zones
    M = Mesh(g, lab, X, C)
    Z = bead_zones(M, segs, zones, "D")
    E = np.flatnonzero(Z["E"])
    edge = np.flatnonzero(Z["nF"] & Z["nW"] & ~Z["E"])
    n0 = np.asarray(g["frame"]["n0"], float)
    _d, j = cKDTree(M.P[edge]).query(M.P[E])
    f = edge[j]
    s = np.sign(((x - X)[f] @ n0).sum()) or 1.0
    full = (np.abs((x - X)[f] @ n0 - s * abs(dD)) <= 1e-9) & (np.linalg.norm((x - X)[E], axis=1) > 1e-9)
    E, f = E[full], f[full]

    def ang(P):
        d = P[E] - P[f]
        hh = np.abs(d @ n0)
        pl = np.linalg.norm(d - np.outer(d @ n0, n0), axis=1)
        return np.degrees(np.arctan2(hh, pl))
    return ang(X), ang(x)


def _h6_df(key, dD):
    from beadgraph.testing import conformance as cf
    g, lab, _ = cf.classified("h6")
    fx = cf.load_fixture("h6")
    X, C, F = fx["x0"], fx["conn"], fx["fixed"]
    _n, _k, segs, zones, _dv = cf.h6_recipes(g, lab, fx)[key][0]
    bl = [{"name": "v", "kind": "DF", "segs": segs, "zones": zones, "hold": 1}]
    nom = bg.basis(g, lab, X, bl, None, fixed=F, elems=C)[0]["nominal"]
    B = bg.basis(g, lab, X, bl, {"v": [nom - abs(dD), nom + abs(dD)]}, fixed=F, elems=C)
    x = bg.morph(X, B, {"v": nom + dD})
    r = bg.check(g, lab, X, x, B, {"v": nom + dD}, elems=C)
    n0 = np.asarray(g["frame"]["n0"], float)
    du = (x - X)[B[0]["info"]["achieved_idx"]]
    return g, B[0]["info"], r, float(np.abs(du - np.outer(du @ n0, n0)).max())


def test_df_h6_pocket_v3d():
    """V-0247-DM-3 (d): DF on the H6 pocket C (+2) — no BG_CORNER_GUARD, no inversion, floor plan ≤ 1e-9."""
    _g, info, r, fp = _h6_df("d", 2.0)
    assert r["inverted"] == 0 and r["outside"]["max_mm"] <= 1e-9 and r["achieved"]["v"] <= 1e-6
    assert not any(w["code"] == "BG_CORNER_GUARD" for w in info["warnings"]) and fp <= 1e-9


def _h6_straight_angles(dD):
    """H6 ch1 직선 구간(y 260..470 — U 끝·flare 제외) 입구 기둥 각 변화(°): 입구 노드 ~ 평면 최근접 깊이면 가장자리."""
    from scipy.spatial import cKDTree

    from beadgraph.testing import conformance as cf
    from beadgraph.zones import bead_zones
    g, lab, _ = cf.classified("h6")
    fx = cf.load_fixture("h6")
    X, C, F = fx["x0"], fx["conn"], fx["fixed"]
    _n, _k, segs, zones, _dv = cf.h6_recipes(g, lab, fx)["b"][0]
    bl = [{"name": "v", "kind": "DF", "segs": segs, "zones": zones, "hold": 1}]
    nom = bg.basis(g, lab, X, bl, None, fixed=F, elems=C)[0]["nominal"]
    B = bg.basis(g, lab, X, bl, {"v": [nom - abs(dD), nom + abs(dD)]}, fixed=F, elems=C)
    x = bg.morph(X, B, {"v": nom + dD})
    M = Mesh(g, lab, X, C)
    Z = bead_zones(M, segs, zones, "D")
    E = np.flatnonzero(Z["E"])
    E = E[(X[E, 1] > 260.0) & (X[E, 1] < 470.0)]
    edge = np.flatnonzero(Z["nF"] & Z["nW"] & ~Z["E"])
    _d, j = cKDTree(M.P[edge]).query(M.P[E])
    f = edge[j]
    n0 = np.asarray(g["frame"]["n0"], float)

    def ang(P):
        d = P[E] - P[f]
        return np.degrees(np.arctan2(np.abs(d @ n0), np.linalg.norm(d - np.outer(d @ n0, n0), axis=1)))
    return np.abs(ang(x) - ang(X))


@pytest.mark.parametrize("dD", [2.0, -2.0])
def test_df_h6_ch1_v3_parts(dD):
    """V-0247-DM-3(DM-30·31 기준, 뒤집힘 제외 부분): H6 ch1 DF ±2 — 깊이면 평면 ≤ 1e-9, 허용 구역 밖 ≤ 1e-9, 직선 구간 각 ±1°,
    angle_dev_mm 기록."""
    _g, info, r, fp = _h6_df("b", dD)
    assert r["outside"]["max_mm"] <= 1e-9 and r["achieved"]["v"] <= 1e-6 and fp <= 1e-9
    da = _h6_straight_angles(dD)
    assert da.size > 50 and da.max() <= 1.0
    assert info["angle_dev_mm"] is not None and "entry_wave_mm" not in info
    print(f"\n[V-0247-DM-3] ch1 ΔD {dD:+} angle_dev_mm {info['angle_dev_mm']} entry_clipped_n {info['entry_clipped_n']} "
          f"inverted {r['inverted']}")


@pytest.mark.parametrize("dD", [2.0, -2.0])
def test_df_h6_unaligned_v3(dD):
    """V-0247-DM-3: H6 ch1 DF ±2 — 뒤집힘 0(DM-32 입구 가드 — DF_ENTRY_GUARD 정보)."""
    _g, info, r, _fp = _h6_df("b", dD)
    assert r["inverted"] == 0
    assert info["entry_guard_n"] > 0 and any(w["code"] == "DF_ENTRY_GUARD" for w in info["warnings"])


@pytest.mark.parametrize("dD", [2.0, -2.0])
def test_parallel_neighbours_v30(dD):
    """V-0247-DM-30 (package part): two parallel channels 20 mm apart, both DF at ±ΔD — SELECT_BLEND_CLIPPED, no
    leak; the inversion count is reported (range guard limits the usable range in esl — tests/doe)."""
    c = so.parallel(gap=20.0)
    g, lab = _cls(c)
    X, C, F = c["nodes"], c["conn"], c["fixed"]
    sid = [s["id"] for s in g["segments"] if s["type"] != "base"]
    assert len(sid) == 2
    bl = [{"name": f"v{i}", "kind": "DF", "segs": [s], "hold": 1} for i, s in enumerate(sid)]
    B = bg.basis(g, lab, X, bl, {"v0": [7.0, 13.0], "v1": [7.0, 13.0]}, fixed=F, elems=C)
    assert all(any(w["code"] == "SELECT_BLEND_CLIPPED" for w in b["info"]["warnings"]) for b in B)
    assert basis_leak(B, g, lab, X, C) == []
    x = bg.morph(X, B, {"v0": 10.0 + dD, "v1": 10.0 + dD})
    r = bg.check(g, lab, X, x, B, {"v0": 10.0 + dD, "v1": 10.0 + dD}, elems=C)
    assert r["outside"]["max_mm"] <= 1e-9 and r["achieved"]["v0"] <= 1e-6


def test_cost_df_w1_v17_v27(ONE):
    """V-0247-DM-17·27 (package part): DF basis time ≤ 1.2 × W basis time (same band, no harmonic) on the synthetic
    channel; W1 basis ≤ 1.2 × W basis on synth_oneside (W reference = the two-sided channel of the same size). Best of 3."""
    import time

    def best(fn):
        t = []
        for _ in range(3):
            t0 = time.perf_counter()
            fn()
            t.append(time.perf_counter() - t0)
        return min(t)
    c = so.channel(theta=(45.0, 45.0))
    g, lab = _cls(c)
    sid = [s["id"] for s in g["segments"] if s["type"] != "base"]
    X, C, F = c["nodes"], c["conn"], c["fixed"]
    tw = best(lambda: bg.basis(g, lab, X, [{"name": "v", "kind": "W", "segs": sid, "hold": 1}], {"v": [36.0, 44.0]},
                               fixed=F, elems=C))
    tdf = best(lambda: bg.basis(g, lab, X, [{"name": "v", "kind": "DF", "segs": sid, "hold": 1}], {"v": [7.0, 13.0]},
                                fixed=F, elems=C))
    cb, gb_, lb = ONE["b"]
    tw1 = best(lambda: bg.basis(gb_, lb, cb["nodes"], [{"name": "v", "kind": "W1", "segs": [2], "hold": 1}],
                                {"v": [36.0, 44.0]}, fixed=cb["fixed"], elems=cb["conn"]))
    print(f"\n[V-0247-DM-17/27] W {tw:.3f}s DF {tdf:.3f}s W1 {tw1:.3f}s")
    assert tdf <= 1.2 * tw + 0.05
    assert tw1 <= 1.2 * tw + 0.05


def _concave_n(X, x, C):
    """moved quads whose corner Jacobian is <= 0 at x (own diagonal plane or the rest normal) and > 0 at rest, with a
    positive Gauss-point Jacobian (concave, not inverted)."""
    from beadgraph.checks import _quad_jacobian, quad_corner_min
    C = np.asarray(C, np.int64)
    q = np.flatnonzero(C[:, 3] >= 0)
    Cq = C[q]
    n0 = np.cross(X[Cq[:, 2]] - X[Cq[:, 0]], X[Cq[:, 3]] - X[Cq[:, 1]])
    ok0 = (quad_corner_min(X, Cq) > 0) & (quad_corner_min(X, Cq, n0) > 0)
    c1 = np.minimum(quad_corner_min(x, Cq), quad_corner_min(x, Cq, n0))
    mv = np.linalg.norm(x - X, axis=1) > 1e-9
    return int(((c1 <= 0) & ok0 & (_quad_jacobian(x, Cq) > 0) & mv[Cq].any(1)).sum())


@pytest.mark.parametrize("qual", [None, {"guard_jac_min": 0.3, "guard_tri_angle_min_deg": 10.0}])
def test_df_h6_ch1_default_range_ends_v3(qual):
    """V-0247-DM-3 (DM-33·34·35, 현장 위험): H6 ch1 DF 기저를 기본 범위 ±30 %(±2.4)로 만들고 ±2.4 에서 — 뒤집힘 0, 오목 사각형 0,
    entry_guard_left 0, 부모 바닥 섬 제자리(band_islands 없음 · 섬 노드 변위 0). esl 품질 기준(guard_*)을 넘겨도 같음."""
    from beadgraph.testing import conformance as cf
    g, lab, _ = cf.classified("h6")
    fx = cf.load_fixture("h6")
    X, C, F = fx["x0"], fx["conn"], fx["fixed"]
    _n, _k, segs, zones, _dv = cf.h6_recipes(g, lab, fx)["b"][0]
    bl = [{"name": "v", "kind": "DF", "segs": segs, "zones": zones, "hold": 1, **(qual or {})}]
    nom = bg.basis(g, lab, X, bl, None, fixed=F, elems=C)[0]["nominal"]
    ext = 0.3 * nom
    B = bg.basis(g, lab, X, bl, {"v": [nom - ext, nom + ext]}, fixed=F, elems=C)
    info = B[0]["info"]
    assert info["entry_guard_left"] == 0 and info["entry_guard_n"] > 0 and "band_islands" not in info
    u = np.zeros_like(X)
    u[B[0]["idx"]] = B[0]["vec"]
    isl = np.asarray(lab["island"])
    own = set(info["islands"])
    others = [i["id"] for i in g["islands"] if i["id"] not in own]
    pn = np.unique(C[np.isin(isl, others)])
    pn = pn[pn >= 0]
    from beadgraph.zones import Mesh, bead_zones
    M = Mesh(g, lab, X, C)
    Z = bead_zones(M, segs, zones, "D")
    pn = pn[~(Z["nF"] | Z["nW"] | Z["E"])[pn]]                 # island nodes off the bead (parent-floor islands)
    assert pn.size > 0 and np.abs(u[pn]).max() == 0.0
    for dv in (ext, -ext):
        x = bg.morph(X, B, {"v": nom + dv})
        r = bg.check(g, lab, X, x, B, {"v": nom + dv}, elems=C)
        assert r["inverted"] == 0 and r["outside"]["max_mm"] <= 1e-9 and r["achieved"]["v"] <= 1e-6
        assert _concave_n(X, x, C) == 0
