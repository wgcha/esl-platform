"""V-BS-7: 모핑 안 품질 판정(``mesh_quality.affected_quality`` — v0.15.0 추가, 계약 esl_bead_select.md §6).

정상 범위 안 새 Fail 0 → READY, W −40 %(사면 겹침) → SELECT_MORPH_INVERTED, 블렌딩 R 아주 작게 → 새 Fail 비율 > 0.01 →
SELECT_QUALITY_FAIL, 공칭에서 이미 Fail 인 요소는 세지 않음, ``bead_doe.compare.quality`` 값 변경이 그대로 반영(복제 없음),
v0.14.0 ``summarize`` 결과 불변."""
import copy

import numpy as np
import pytest

import synth_bead as sb
import synth_doe as sd
from esl.doe import DEFAULTS
from esl.doe import bead_select as bs
from esl.doe import mesh_quality as mq
from esl.doe import settings

# 합성 메시 h = 5 mm(이슈 #53 기준은 3 mm 메시) → 길이 기준만 5/3 배로 맞춘 시험 설정(나머지 기준 = 기본값)
_Q = copy.deepcopy(DEFAULTS["compare"]["quality"])
for _k in ("min_length", "max_length"):
    _Q[_k] = {kk: vv * 5.0 / 3.0 for kk, vv in _Q[_k].items()}
CFG = settings({"bead_doe": {"enabled": True, "compare": {"quality": _Q}}})


@pytest.fixture(scope="module")
def G():
    g = sb.generate()
    D = bs.derive_obj(g["mesh"], bs.normalize_input(sb.selection(g), CFG), CFG, fixed_node_ids=g["fixed_ids"])
    return g, D, bs.basis(g["mesh"], D, CFG)


def test_normal_range_ready(G):
    g, D, B = G
    X0 = g["mesh"]["x0"]
    nom = B.nominal()
    for v in ({"B1_D1": 24.0, "B1_D2": 13.0}, {"B1_W": nom["B1_W"] + 5.0}, {"B2_D1": 7.0, "B2_W": 42.0}):
        x = bs.morph(X0, B, v)
        st = bs.design_state(g["mesh"], X0, x, D.fixed_mask, CFG)
        assert st["state"] == "READY", st
        assert st["quality"]["new_fail"] == 0 and st["quality"]["inverted"] == 0
        assert st["quality"]["n_affected"] > 0


def test_inverted_and_quality_fail(G):
    g, D, B = G
    X0 = g["mesh"]["x0"]
    m = g["mesh"]
    W = B.nominal()["B1_W"]
    x = bs.morph(X0, B, {"B1_W": 0.6 * W})                   # 사면·바닥 겹침
    st = bs.design_state(m, X0, x, D.fixed_mask, CFG)
    assert st["state"] == "FAILED_MESH" and st["code"] == "SELECT_MORPH_INVERTED", st["quality"]
    # 블렌딩 R 아주 작게 → 상판 첫 줄이 늘어남(max_length Fail)
    sel = sb.selection(g)
    sel["beads"][0]["blend_mm"] = 1.0
    Ds = bs.derive_obj(m, bs.normalize_input(sel, CFG), CFG)
    Bs = bs.basis(m, Ds, CFG)
    x = bs.morph(X0, Bs, {"B1_W": Bs.nominal()["B1_W"] - 6.0})
    st = bs.design_state(m, X0, x, Ds.fixed_mask, CFG)
    assert st["state"] == "FAILED_MESH" and st["code"] == "SELECT_QUALITY_FAIL", st["quality"]
    assert st["quality"]["new_fail_ratio"] > CFG["select"]["quality"]["max_fail_ratio"]
    assert st["quality"]["fail_by"]["max_length"] > 0
    # compare.quality 기준값 변경이 그대로 반영(한 곳)
    cfg2 = settings({"bead_doe": {"enabled": True, "compare": {"quality": {
        "max_length": {"warn": 50.0, "fail": 60.0}, "aspect": {"warn": 50.0, "fail": 60.0},
        "skew": {"warn": 80.0, "fail": 89.0}, "quad_max_angle": {"warn": 170.0, "fail": 179.0},
        "quad_min_angle": {"warn": 2.0, "fail": 1.0}, "jacobian": {"warn": 0.1, "fail": 0.05},
        "warpage": {"warn": 80.0, "fail": 89.0}}}}})
    st2 = bs.design_state(m, X0, x, Ds.fixed_mask, cfg2)
    assert st2["state"] == "READY", st2["quality"]
    # select.quality.max_fail_ratio 상한도 반영
    cfg3 = settings({"bead_doe": {"enabled": True, "select": {"quality": {"max_fail_ratio": 0.99}}}})
    assert bs.design_state(m, X0, x, Ds.fixed_mask, cfg3)["state"] == "READY"


def test_nominal_fail_not_counted(G):
    g, D, B = G
    m = g["mesh"]
    X0 = m["x0"]
    q = copy.deepcopy(DEFAULTS["compare"]["quality"])
    q["aspect"] = {"warn": 1.05, "fail": 1.1}                 # 공칭에서도 대부분 Fail
    x = bs.morph(X0, B, {"B1_D1": 22.01})
    am = bs.affected_elems(m, X0, x)
    r = mq.affected_quality(m, x, am, q, flip_deg=60.0)
    nominal_fail = mq.affected_quality(m, X0 + 0.0, am, q, flip_deg=60.0)
    assert r["n_affected"] == int(am.sum()) > 0
    assert r["new_fail"] == 0 and nominal_fail["new_fail"] == 0
    m0 = mq.element_metrics(X0, m["conn"][am], m["elem_type"][am])
    assert int(np.sum(m0["aspect"] > 1.1)) > 0                # 공칭 Fail 이 있는데도 세지 않음
    assert mq.affected_quality(m, x, np.zeros(len(am), bool), q, flip_deg=60.0)["n_affected"] == 0


def test_summarize_unchanged():
    """v0.14.0 summarize: 정사각 4각·직각 3각 판 = Fail 0, 같은 키(함수 불변)."""
    mesh = sd.plate(nx=10, ny=10, Lx=30.0, Lz=30.0, n_tria_cols=2)
    s = mq.summarize(mesh, DEFAULTS["compare"]["quality"])
    assert set(s) == {"n_elems", "fail_elems", "fail_ratio", "warn_elems", "warn_ratio", "tria_pct", "tria_level",
                      "fail_by", "warn_by", "worst", "max_fail_ratio", "over_limit"}
    assert s["n_elems"] == 120 and s["fail_by"]["min_length"] == 0 and s["worst"]["quad_min_angle"] == pytest.approx(90.0)
    assert s["tria_pct"] == pytest.approx(100.0 * 40 / 120)
