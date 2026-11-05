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

def _cfg(h: float, policy: str = "skip") -> dict:
    """합성 메시 h mm(이슈 #53 기준은 3 mm 메시) → 길이 기준만 h/3 배로 맞춘 시험 설정(나머지 기준 = 기본값).
    v0.16.1: 기본 정책은 warn — 이 파일의 v0.15.0 기대값(V-BS-7)은 quality.fail_policy skip 으로(V-SR-9 skip 경로)."""
    q = copy.deepcopy(DEFAULTS["compare"]["quality"])
    for k in ("min_length", "max_length"):
        q[k] = {kk: vv * h / 3.0 for kk, vv in q[k].items()}
    return settings({"bead_doe": {"enabled": True, "compare": {"quality": q},
                                  "select": {"fixed_policy": policy, "quality": {"fail_policy": policy}}}})


CFG = _cfg(5.0)


def _make(h: float, cfg: dict):
    g = sb.generate(h)
    D = bs.derive_obj(g["mesh"], bs.normalize_input(sb.selection(g), cfg), cfg, fixed_node_ids=g["fixed_ids"])
    return g, D, bs.basis(g["mesh"], D, cfg)


@pytest.fixture(scope="module")
def G():
    return _make(5.0, CFG)


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
    cfg2 = settings({"bead_doe": {"enabled": True, "select": {"quality": {"fail_policy": "skip"}}, "compare": {"quality": {
        "max_length": {"warn": 50.0, "fail": 60.0}, "aspect": {"warn": 50.0, "fail": 60.0},
        "skew": {"warn": 80.0, "fail": 89.0}, "quad_max_angle": {"warn": 170.0, "fail": 179.0},
        "quad_min_angle": {"warn": 2.0, "fail": 1.0}, "jacobian": {"warn": 0.1, "fail": 0.05},
        "warpage": {"warn": 80.0, "fail": 89.0}}}}})
    st2 = bs.design_state(m, X0, x, Ds.fixed_mask, cfg2)
    assert st2["state"] == "READY", st2["quality"]
    # select.quality.max_fail_ratio 상한도 반영
    cfg3 = settings({"bead_doe": {"enabled": True, "select": {"quality": {"max_fail_ratio": 0.99, "fail_policy": "skip"}}}})
    assert bs.design_state(m, X0, x, Ds.fixed_mask, cfg3)["state"] == "READY"
    # V-SR-9 warn 정책(기본): 같은 안 = READY + SELECT_QUALITY_WARN, 뒤집힘 안은 여전히 FAILED_MESH
    W = _cfg(5.0, "warn")
    st = bs.design_state(m, X0, x, Ds.fixed_mask, W)
    assert st["state"] == "READY" and st["code"] is None
    qw = [w for w in st["warnings"] if w["code"] == "SELECT_QUALITY_WARN"]
    assert qw and qw[0]["new_fail"] == st["quality"]["new_fail"] > 0
    xi = bs.morph(X0, B, {"B1_W": 0.6 * B.nominal()["B1_W"]})
    assert bs.design_state(m, X0, xi, D.fixed_mask, W)["code"] == "SELECT_MORPH_INVERTED"


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


@pytest.mark.parametrize("h", [5.0, 2.5])
def test_degradation_failed_by_mesh_size(h):
    """품질 열화(V-BS-7)는 메시 크기와 무관: h 5·2.5 mm 모두 b1 깊이 3.5 배·블렌딩 R = 1 mm(폭 −6) → FAILED_MESH.
    (h 2.5 는 원형 비드 b2 중심 노드가 격자점 — synth_bead 중심 노드 z = −D 수정 회귀도 겸함)"""
    cfg = _cfg(h)
    g, D, B = _make(h, cfg)
    m = g["mesh"]
    X0 = m["x0"]
    ctr = int(np.argmin(np.hypot(X0[:, 0] - 560.0, X0[:, 1] - 345.0)))
    if np.hypot(X0[ctr, 0] - 560.0, X0[ctr, 1] - 345.0) < 1e-9:
        assert X0[ctr, 2] == pytest.approx(-g["truth"]["b2"]["D"][1])
    nom = B.nominal()
    st = bs.design_state(m, X0, bs.morph(X0, B, {"B1_D1": 3.5 * nom["B1_D1"], "B1_D2": 3.5 * nom["B1_D2"]}),
                         D.fixed_mask, cfg)
    assert st["state"] == "FAILED_MESH", st["quality"]
    assert st["quality"]["new_fail_ratio"] > cfg["select"]["quality"]["max_fail_ratio"] or st["quality"]["inverted"] > 0
    sel = sb.selection(g)
    sel["beads"][0]["blend_mm"] = 1.0
    Ds = bs.derive_obj(m, bs.normalize_input(sel, cfg), cfg)
    Bs = bs.basis(m, Ds, cfg)
    st = bs.design_state(m, X0, bs.morph(X0, Bs, {"B1_W": Bs.nominal()["B1_W"] - 6.0}), Ds.fixed_mask, cfg)
    assert st["state"] == "FAILED_MESH", st["quality"]
    assert st["code"] in ("SELECT_QUALITY_FAIL", "SELECT_MORPH_INVERTED")


def test_summarize_unchanged():
    """v0.14.0 summarize: 정사각 4각·직각 3각 판 = Fail 0, 같은 키(함수 불변)."""
    mesh = sd.plate(nx=10, ny=10, Lx=30.0, Lz=30.0, n_tria_cols=2)
    s = mq.summarize(mesh, DEFAULTS["compare"]["quality"])
    assert set(s) == {"n_elems", "fail_elems", "fail_ratio", "warn_elems", "warn_ratio", "tria_pct", "tria_level",
                      "fail_by", "warn_by", "worst", "max_fail_ratio", "over_limit"}
    assert s["n_elems"] == 120 and s["fail_by"]["min_length"] == 0 and s["worst"]["quad_min_angle"] == pytest.approx(90.0)
    assert s["tria_pct"] == pytest.approx(100.0 * 40 / 120)
