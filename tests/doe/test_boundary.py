"""V-BD-10: 경계 매핑 경고 — 정규화 옮김 식, A 체결점·B 구멍 거리 9.9/10.1 mm 경계, 하중 집중 비율 경계,
B 후보 0, A 체결 정보 없음 → A_FASTENERS_UNKNOWN, 3-2-1 이동 정보, 평면도 자료 = 판정 결과 그대로."""
import numpy as np

import synth_doe as sd
from esl.doe import boundary as bnd
from esl.doe import settings
from esl.library import normalize as nz
from esl.opt.keepout import project_ab

CFG = settings()


def frame(a0, a1, b0, b1):
    return {"origin": [0, 0, 0], "e_xi": [1, 0, 0], "e_eta": [0, 0, 1], "n": [0, -1, 0],
            "a_range": [a0, a1], "b_range": [b0, b1], "L_xi": a1 - a0, "L_eta": b1 - b0}


def test_transfer_formula():
    fa, fb = frame(0, 1000, 0, 600), frame(-50, 1050, 10, 640)
    out = bnd.transfer(fa, fb, [[250.0, 150.0], [1000.0, 600.0]])
    assert np.allclose(out[0], [-50 + 0.25 * 1100, 10 + 0.25 * 630])
    assert np.allclose(out[1], [1050, 640])
    assert np.allclose(bnd.to_unit(fb, bnd.from_unit(fb, [[0.3, 0.7]])), [[0.3, 0.7]])


def test_fastener_distance_boundary():
    fa = fb = frame(0, 1000, 0, 600)
    cands = [{"label": "B 구멍 1", "kind": "HOLE", "ab": [500.0, 300.0]}]
    a_pts = [{"label": "A RBE2#0", "kind": "RBE2", "ab_a": [509.9, 300.0]},
             {"label": "A RBE2#1", "kind": "RBE2", "ab_a": [500.0, 310.1]}]
    r = bnd.check(fa, fb, a_pts, [], cands, CFG)
    assert [w["label"] for w in r["warnings"]] == ["A RBE2#1"]
    assert abs(r["warnings"][0]["d_mm"] - 10.1) < 1e-9
    assert [lk["warn"] for lk in r["links"]] == [False, True]
    assert r["n_warn"] == 1 and abs(r["a_points"][0]["a"] - 509.9) < 1e-9
    r0 = bnd.check(fa, fb, a_pts, [], [], CFG)                         # B 후보 0 → 전부 경고
    assert r0["n_warn"] == 2 and r0["warnings"][0]["d_mm"] is None and r0["links"] == []
    ri = bnd.check(fa, fb, [], [], cands, CFG, a_fastener_known=False)
    assert ri["info"] == [{"code": "A_FASTENERS_UNKNOWN"}] and ri["n_info"] == 1


def test_load_points_share_and_distance():
    mesh = sd.plate(nx=20, ny=10, Lx=400.0, Lz=200.0)
    fr = nz.frame(mesh["x0"], None, mesh["conn"], mesh["elem_type"])
    X = mesh["x0"]
    f = np.zeros_like(X)
    i1 = int(np.argmin(np.linalg.norm(X - [40, 0, 40], axis=1)))
    i2 = int(np.argmin(np.linalg.norm(X - [360, 0, 160], axis=1)))
    i3 = int(np.argmin(np.linalg.norm(X - [200, 0, 100], axis=1)))
    f[i1, 1], f[i2, 1], f[i3, 1] = 70.0, -21.0, -9.0                    # 비율 0.70 / 0.21 / 0.09
    lp = bnd.load_points([("E1", mesh["node_id"], X, f)], fr, 0.2, 5)
    assert sorted(round(p["share"], 6) for p in lp) == [0.21, 0.7]
    lp_hi = bnd.load_points([("E1", mesh["node_id"], X, f)], fr, 0.22, 5)
    assert [round(p["share"], 6) for p in lp_hi] == [0.7]
    p70 = next(p for p in lp if round(p["share"], 2) == 0.7)
    a, b = project_ab(fr, X[i1])[0]
    assert np.allclose(p70["ab_a"], [a, b])
    cands = [{"label": "B 구멍", "kind": "HOLE", "ab": [a + 19.9, b]}]
    r = bnd.check(fr, fr, [], lp_hi, cands, CFG)
    assert r["n_warn"] == 0
    cands[0]["ab"] = [a + 20.1, b]
    r = bnd.check(fr, fr, [], lp_hi, cands, CFG)
    assert r["warnings"][0]["code"] == "BOUNDARY_LOAD_UNSUPPORTED" and abs(r["warnings"][0]["d_mm"] - 20.1) < 1e-6
    assert r["load_points"][0]["entry_id"] == "E1"


def test_holes_supports_and_plan(tmp_path):
    mesh = sd.plate(nx=12, ny=8, holes=[(5, 7, 3, 5)])
    fr = nz.frame(mesh["x0"], None, mesh["conn"], mesh["elem_type"])
    ocfg = sd.so.settings()
    hc = bnd.hole_centers(mesh, fr, ocfg["keepout"]["hole_min_perimeter_mm"])
    assert len(hc) == 1
    c = project_ab(fr, [150.0, 0.0, 100.0])[0]
    assert np.allclose(hc[0]["ab"], c)
    fx = [{"label": "RBE2#0", "kind": "RBE2", "xyz": [0.0, 0.0, 0.0]}]
    cands = bnd.b_candidates(fr, mesh, fx, ocfg["keepout"]["hole_min_perimeter_mm"])
    assert [x["kind"] for x in cands] == ["RBE2", "HOLE"]
    sup = [{"xyz": [0.0, 0.0, 0.0], "dof": "123"}]
    ap = bnd.a_fastener_points(fr, fx, sup)
    assert [p["kind"] for p in ap] == ["RBE2", "S321"]
    r = bnd.check(fr, fr, ap, [], cands, CFG, a_supports_ab=[[0.0, 0.0]], b_supports_ab=[[15.0, 0.0]])
    assert r["info"][0]["code"] == "SUPPORT_SHIFT" and r["n_warn"] == 0
    doc = sd.features_doc(mesh, 2)
    pl = bnd.plan(mesh, fr, ocfg["keepout"], 1000, features_doc=doc, result=r)
    assert pl["holes"] and pl["outline"] and len(pl["beads"]) == 2 and len(pl["beads"][0]["ring"]) == 4
    assert pl["fixed"] == r["fixed"] and pl["a_points"] == r["a_points"] and pl["links"] == r["links"]
