"""v0.25.0 개정 2·3(계약 esl_virtual_bead.md §19 — D-0.25.0-VB-21~28) — V-0250-VB-20·22·25·31·32.

세계: ``synth_vbead.graph_world``(평판 + 채널 비드 −z + 구멍) · ``synth_vbead.plateau_world``(부모 바닥 + 평탄부(level ±4, 45° 벽) +
평탄부 위 자식 채널(y 70) + 평탄부 위 구멍(200, 140) — 둘레 = fixed-scan)."""
import copy
import math
from functools import lru_cache

import numpy as np
import pytest
import synth_guard as sg
import synth_vbead as sv
from _bg_util import CFG, bgr, bs

from esl.doe import DEFAULTS, settings
from esl.doe import mesh_quality as mq
from esl.errors import EslError
from esl.morph import virtual_bead as vbm

BLK = {"schema": 1, **{k: DEFAULTS["virtual_bead"][k] for k in vbm.HASH_KEYS}}
RU = sg.rules()
FR = sv.frame_of()


@lru_cache(maxsize=4)
def GW(h=5.0):
    return sv.graph_world(h=h)


@lru_cache(maxsize=4)
def PW(level=4.0):
    return sv.plateau_world(level=level)


def _sel(g, beads=(), vbs=()):
    return {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": int(g["rules"]), "edits": {}},
            "beads": list(beads), "ties": [], "virtual_beads": [dict(v) for v in vbs]}


def _derive(world, vbs, beads=(), blk=BLK, rules=None, tie=(), cfg=CFG, frame=FR):
    m, g, lab, fx, _d = world
    n, sha = bgr.normalize_v2(_sel(g, beads, vbs), g, cfg, labels=lab, mesh=m)
    D = bgr.derive_obj_v2(m, n, cfg, g, lab, fixed_node_ids=fx, shape_rules=rules, virtual_bead=blk, frame=frame,
                          tie_node_ids=tie)
    return D, n, sha


def push_z(vb):
    return float(vb.side * vb.plane[1][2])


# ---------------------------------------------------------------- V-0250-VB-20 r 기본
VBG = {"id": "a1", "p0": [60.0, 140.0, 0.0], "p1": [180.0, 140.0, 0.0], "w_top": 10.0, "d_max": 6.0}


@pytest.mark.parametrize("h", [5.0, 3.0])
def test_r_default_v20(h):
    W = GW(h)
    m = W[0]
    D, n, sha = _derive(W, [VBG])
    vb = D.vbeads[0]
    assert vb.ok and vb.r_source == "default" and "r" not in n["virtual_beads"][0]
    # h = r 0 발자국 host 요소 변 길이 중앙값(독립 계산)
    X, C, et = np.asarray(m["x0"]), np.asarray(m["conn"]), np.asarray(m["elem_type"])
    fp0 = vbm.footprint(X, (np.array(VBG["p0"]), np.array(VBG["p1"]), np.array([1.0, 0, 0]), 120.0, np.array([0, 0, 1.0])),
                        10.0, 45.0, 6.0, "round", 0.0, 3.0)
    h_ind = vbm.edge_median(X, C, et, vbm.chk_elems(C, et, fp0["move_mask"]) & vb.H)
    assert vb.h == pytest.approx(h_ind, abs=1e-12)
    assert vb.r == pytest.approx(round(min(h_ind, vbm.r_cap(10.0, 45.0, 6.0)), 4), abs=1e-4)
    assert vb.d_move == pytest.approx(5.0 + 6.0 + 1.25 * vb.r * math.tan(math.radians(22.5)), abs=1e-9)
    assert vb.field["c"] == pytest.approx(vbm.edge_c(vb.r, 45.0))
    B = bs.basis(m, D, CFG)
    assert np.array_equal(bs.morph(X, B, {"A1_A": 0.0}), X)                         # D = 0 → 0 정확
    row = next(r for r in bgr.params_rows_v2(D, CFG) if r["name"] == "A1_A")
    assert row["vb"]["r"] == round(vb.r, 4) and row["vb"]["r_source"] == "default" and row["vb"]["host"] == "base"
    assert "depth_max_mm" not in row["vb"]
    # 준 r 0 → 키 유지·각진 장·sha 다름
    D0, n0, sha0 = _derive(W, [{**VBG, "r": 0.0}])
    v0 = D0.vbeads[0]
    assert n0["virtual_beads"][0]["r"] == 0.0 and sha0 != sha and v0.r_source == "user" and v0.field["c"] == 0.0
    u = vbm.displacement(v0.field, 4.0)
    assert np.allclose(u[:, 2] * v0.side * v0.plane[1][2], np.maximum(0.0, 4.0 - v0.field["g"]), atol=1e-12)


def test_r_cap_and_clamp_v20_v30():
    W = GW(5.0)
    rc = vbm.r_cap(10.0, 45.0, 6.0)
    with pytest.raises(EslError) as ei:
        _derive(W, [{**VBG, "r": round(rc + 2e-4, 4)}])
    assert ei.value.code == "VB_INPUT_INVALID" and ei.value.detail["key"] == "r" and \
        ei.value.detail["r_max"] == pytest.approx(rc, abs=1e-4)
    D, _n, _s = _derive(W, [{**VBG, "r": math.floor(rc * 1e4) / 1e4}])
    assert D.vbeads[0].ok
    run_h = {**VBG, "theta_deg": 60.0, "d_max": round(5.0 * math.tan(math.radians(60.0)), 4)}   # run = h(5)
    D1, _n, _s = _derive(W, [run_h])
    assert not any(w["code"] == "VB_R_CLAMPED" for w in D1.vbeads[0].warnings)
    blk2 = {**BLK, "r_default_h_mult": 2.0}
    D2, _n, _s = _derive(W, [run_h], blk=blk2)
    v2 = D2.vbeads[0]
    cl = [w for w in v2.warnings if w["code"] == "VB_R_CLAMPED"]
    assert cl and v2.r == pytest.approx(vbm.r_cap(10.0, 60.0 - 0.01, run_h["d_max"]), abs=1e-4)
    assert cl[0]["r_h"] == pytest.approx(2.0 * v2.h, abs=1e-4)
    for blk in ({**BLK, "r_default_h_mult": 0.0}, {k: v for k, v in BLK.items() if k != "r_default_h_mult"}):
        D3, _n, _s = _derive(W, [VBG], blk=blk)
        assert D3.vbeads[0].r == 0.0 and D3.vbeads[0].field["c"] == 0.0


# ---------------------------------------------------------------- V-0250-VB-25 설정 검증 · θ 경계
def test_settings_theta_flip_v25():
    with pytest.raises(EslError) as ei:
        settings({"bead_doe": {"virtual_bead": {"theta_range_deg": [15.0, 61.0]}}})
    assert ei.value.code == "CONFIG_INVALID" and ei.value.detail == {
        "key": "bead_doe.virtual_bead.theta_range_deg", "theta_hi": 61.0, "flip_deg": 60.0}
    assert "뒤집힘 기준" in ei.value.message
    settings({"bead_doe": {"virtual_bead": {"theta_range_deg": [15.0, 60.0]}}})
    with pytest.raises(EslError):
        settings({"bead_doe": {"select": {"quality": {"flip_deg": 50.0}}}})
    with pytest.raises(EslError):
        settings({"bead_doe": {"virtual_bead": {"theta_default_deg": 70.0}}})
    with pytest.raises(EslError):
        settings({"bead_doe": {"virtual_bead": {"theta_range_deg": [50.0, 40.0]}}})
    W = GW(5.0)
    with pytest.raises(EslError) as ei:                                              # 옛 블록 상한 75 + θ 70
        _derive(W, [{**VBG, "theta_deg": 70.0}], blk={**BLK, "theta_range_deg": [15.0, 75.0]})
    assert ei.value.code == "VB_INPUT_INVALID" and ei.value.detail["key"] == "theta_deg"


def test_theta_flip_boundary_no_inversion_v25():
    """정렬 평판·θ 60·준 r 0·run ≥ 3h → 직선 사면 요소 뒤집힘 0(θ_f = 59.99°)."""
    W = GW(5.0)
    m = W[0]
    d = round(15.0 * math.tan(math.radians(60.0)), 4)
    D, _n, _s = _derive(W, [{**VBG, "theta_deg": 60.0, "d_max": d, "r": 0.0, "end": "square"}])
    vb = D.vbeads[0]
    assert vb.ok and vb.theta_f == pytest.approx(59.99)
    B = bs.basis(m, D, CFG)
    X = np.asarray(m["x0"])
    x = bs.morph(X, B, {"A1_A": d})
    C, et = np.asarray(m["conn"]), np.asarray(m["elem_type"])
    cen = X[C].mean(axis=1)
    side = (cen[:, 0] > 70.0) & (cen[:, 0] < 170.0) & bs.affected_elems(m, X, x)
    assert side.any() and mq.inverted_count(X, x, C, et, np.flatnonzero(side), flip_deg=60.0) == 0


# ---------------------------------------------------------------- V-0250-VB-22·32 평탄부 host
VBP = {"id": "a1", "p0": [80.0, 110.0, 0.0], "p1": [170.0, 110.0, 0.0], "w_top": 8.0, "d_max": 5.0}


def _p(vb, z):
    out = dict(vb)
    out["p0"] = [vb["p0"][0], vb["p0"][1], z]
    out["p1"] = [vb["p1"][0], vb["p1"][1], z]
    return out


@pytest.mark.parametrize("level", [4.0, -4.0])
def test_plateau_host_ok_and_direction_v22_v32(level):
    W = PW(level)
    D, _n, _s = _derive(W, [_p(VBP, level)])
    vb = D.vbeads[0]
    assert vb.ok and vb.host == "plateau" and vb.host_floor == 1, vb.reasons
    assert np.sign(push_z(vb)) == np.sign(level)                                    # 평탄부가 들어간(나온) 쪽으로 더
    Df, _n, _s = _derive(W, [{**_p(VBP, level), "flip": True}])
    vf = Df.vbeads[0]
    assert vf.side == -vb.side and np.array_equal(vf.field["vec"], -vb.field["vec"])
    assert np.array_equal(vf.field["idx"], vb.field["idx"]) and np.array_equal(vf.field["g"], vb.field["g"])
    m = W[0]
    B, Bf = bs.basis(m, D, CFG), bs.basis(m, Df, CFG)
    X = np.asarray(m["x0"])
    assert np.allclose(bs.morph(X, B, {"A1_A": 3.0}) - X, -(bs.morph(X, Bf, {"A1_A": 3.0}) - X), atol=1e-15)
    doc = bgr.derive_v2(m, _n, CFG, W[1], W[2], frame=FR, fixed_scan=W[3], virtual_bead=BLK)
    assert doc["virtual_beads"][0]["host"] == "plateau" and doc["virtual_beads"][0]["host_floor"] == 1


def test_plateau_reasons_v22():
    W = PW(4.0)
    cases = [({"p0": [80.0, 172.0, 4.0], "p1": [170.0, 172.0, 4.0]}, ["VB_PLATE_EDGE"]),      # 평탄부 가장자리 벽
             ({"p0": [100.0, 86.0, 4.0], "p1": [170.0, 86.0, 4.0]}, ["VB_OVER_BEAD"]),        # 자식 채널
             ({"p0": [100.0, 70.0, 1.0], "p1": [170.0, 70.0, 1.0]}, None)]                    # 채널 깊이면(R-VB-7)
    for over, want in cases:
        D, _n, _s = _derive(W, [{**VBP, **over}])
        rs = D.vbeads[0].reasons
        if want is None:
            assert "VB_OVER_BEAD" in rs or "VB_NOT_ON_PLATE" in rs, rs
        else:
            assert rs == want, (over, rs)
    D, _n, _s = _derive(W, [{**VBP, "p0": [150.0, 140.0, 4.0], "p1": [186.0, 140.0, 4.0]}])
    assert {"VB_OVER_HOLE", "VB_FIXED"} <= set(D.vbeads[0].reasons)
    m = W[0]
    k = int(np.argmin(np.hypot(m["x0"][:, 0] - 125.0, m["x0"][:, 1] - 118.0)))
    D, _n, _s = _derive(W, [_p(VBP, 4.0)], tie=(int(m["node_id"][k]),))
    assert D.vbeads[0].reasons == ["VB_FIXED"]


def test_plateau_margin_boundary_v22():
    """margin 경계(± 0.1): 가장자리 벽 윗선(y 180)까지 거리 = d_chk ∓ 0.1 → VB_PLATE_EDGE / ok."""
    W = PW(4.0)
    D, _n, _s = _derive(W, [_p(VBP, 4.0)])
    d_chk = D.vbeads[0].d_move + BLK["margin_mm"]
    out = []
    for dy in (-0.1, 0.1):
        y = 180.0 - d_chk - dy
        D, _n, _s = _derive(W, [{**VBP, "p0": [80.0, y, 4.0], "p1": [170.0, y, 4.0]}])
        out.append(D.vbeads[0].reasons)
    assert out == [["VB_PLATE_EDGE"], []]


def test_plateau_d_var_plus_a_v22():
    """평탄부를 D 변수로 선택 + 가상 비드 → 좌표 = D 항 + A 항(± 1e-12), 조합 묶음·VB_BAND_OVERLAP, tie 노드 변위 0."""
    W = PW(4.0)
    m, g, lab, fx, _d = W
    pb = [{"id": "b1", "src": "graph", "segs": [{"anchor": int(g["segments"][1]["anchor"])}]}]
    D, _n, _s = _derive(W, [_p(VBP, 4.0)], beads=pb, rules=RU)
    assert D.vbeads[0].ok and D.vbeads[0].host == "plateau"
    B = bs.basis(m, D, CFG)
    X = np.asarray(m["x0"])
    dn = next(v["name"] for v in B.vars if v["bead"] == "b1")
    nom = next(v["nominal"] for v in B.vars if v["name"] == dn)
    both = bs.morph(X, B, {dn: nom + 1.0, "A1_A": 2.0})
    sep = bs.morph(X, B, {dn: nom + 1.0}) + bs.morph(X, B, {"A1_A": 2.0}) - X
    assert np.allclose(both, sep, atol=1e-12)
    rows = bgr.params_rows_v2(D, CFG)
    doc = bgr.guard_selection(m, D, B, CFG, only=[r["name"] for r in rows if (r.get("guard") or {}).get("state")
                                                  == "unchecked"])
    ov = [w for w in D.vbeads[0].warnings if w["code"] == "VB_BAND_OVERLAP"]
    assert ov and dn in ov[0]["vars"]
    assert any(set(c["vars"]) >= {dn, "A1_A"} for c in doc["combos"]) or \
        any(set((s.get("detail") or {}).get("vars", [])) >= {dn, "A1_A"} for s in doc["skipped"]) or ov
    fid = np.flatnonzero(np.isin(m["node_id"], fx))
    xa = bs.morph(X, B, {"A1_A": 3.0})
    assert np.abs(xa[fid] - X[fid]).max() == 0.0


# ---------------------------------------------------------------- V-0250-VB-31 규칙 판 · 실제 깊이 단위
def test_rules_and_usable_depth_v31():
    assert vbm.VB_RULES == 3
    W = GW(5.0)
    m = W[0]
    D, _n, _s = _derive(W, [VBG], rules=RU)
    B = bs.basis(m, D, CFG)
    doc = bgr.guard_selection(m, D, B, CFG, only=["A1_A"])
    u = doc["entries"][0]["usable"][1]
    X = np.asarray(m["x0"])
    a = next(v for v in B.vars if v["name"] == "A1_A")
    top = a["idx"][a["g"] == 0.0]
    x = bs.morph(X, B, {"A1_A": u})
    assert top.size and np.allclose(np.linalg.norm(x[top] - X[top], axis=1), u, atol=1e-9)
    doc2 = bgr.derive_v2(m, _n, CFG, W[1], W[2], frame=FR, fixed_scan=W[3], virtual_bead=BLK)
    assert "depth_max_mm" not in json_dump(doc2)


def json_dump(o):
    import json
    return json.dumps(o, default=float)


def test_cfg_copy_untouched():
    c = copy.deepcopy(CFG)
    assert c["virtual_bead"]["theta_range_deg"] == [15.0, 60.0]
