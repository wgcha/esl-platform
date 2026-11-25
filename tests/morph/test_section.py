"""V-0247-DM-7·10·14·16·24(vii)·26: esl.morph.section 순수 함수 — 계획 표, 사유 순서, 복제 결정, 해시 보기, feasible, 그림."""
import ast
import math
import os

import pytest

from esl.errors import EslError
from esl.morph import section as sec

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RULES = {"theta_min_deg": 15.0, "theta_spread_deg": 5.0, "one_side_min_nodes": 3}


def test_plans_complete_and_mutation():
    sec.validate_plans()
    for r in sec.SECTION_PLANS:
        assert set(sec.SECTION_PLANS[r]) == set(sec.PLAN_COLUMNS)
    bad = {**sec.SECTION_PLANS, "graph": {**sec.SECTION_PLANS["graph"], "fig": ""}}
    with pytest.raises(EslError) as ei:
        sec.validate_plans(bad)
    assert ei.value.code == "CONFIG_INVALID"
    assert sec.row_plan(None, "graph") == sec.SECTION_PLANS["none"]           # 키 없음 = entry_fixed
    assert sec.row_plan("entry_fixed", "graph") == sec.SECTION_PLANS["none"]
    assert sec.row_plan("floor_fixed", "graph")["compose"] == "pkg_df"
    assert sec.row_plan("floor_fixed", "paicad")["na"] == "DS_ENGINE_NATIVE"


def test_module_purity():
    tree = ast.parse(open(os.path.join(ROOT, "esl", "morph", "section.py"), encoding="utf-8").read())
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] + \
        [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(str(m).startswith(("esl.doe", "beadgraph")) for m in names)
    src = open(os.path.join(ROOT, "esl", "morph", "section.py"), encoding="utf-8").read()
    assert "open(" not in src


def test_resolve():
    assert sec.resolve(None) == sec.LEGACY_DEPTH_SECTION == "entry_fixed"
    assert sec.resolve("floor_fixed") == "floor_fixed"
    with pytest.raises(EslError):
        sec.resolve("bogus")


def test_theta():
    assert sec.cot_from_run(10.0, 10.0, RULES) == (1.0, None)
    assert sec.cot_from_run(0.0, 10.0, RULES) == (None, "THETA_UNMEASURED")
    assert sec.cot_from_run(50.0, 10.0, RULES)[1] == "THETA_UNMEASURED"       # θ = 11.3° < 15
    assert sec.theta_spread(5.0, 10.0, 10.0, RULES) is not None
    d = sec.cot_from_df({"cot_min": 0.577, "cot_med": 1.0, "cot_max": 1.0})
    assert d["cot_med_deg"] == 45.0 and abs(d["cot_max_deg"] - 60.0) < 0.05


@pytest.mark.parametrize("facts,code", [
    ({"user_off": True, "network": True}, "W_USER_OFF"),
    ({"network": True, "area": True}, "W_NETWORK"),
    ({"area": True, "merged": True}, "W_AREA"),
    ({"merged": True}, "W_EDIT_MERGED"),
    ({"floor_fixed": True, "tie_mixed": True, "s1": 1}, "W_TIE_MIXED"),
    ({"floor_fixed": True, "s1_edge": True}, "W_ONE_SIDE_EDGE"),
    ({"floor_fixed": True}, "W_ENTRY_NONE"),
    ({}, "W_ENTRY_ONE_SIDE"),
    ({"s2": 1, "partial": True}, "W_PARTIAL_OLD"),
    ({"floor_fixed": True, "s1": 1, "partial": True}, "W_PARTIAL_OLD"),
    ({"floor_fixed": True, "s1": 2}, None),
    ({"s2": 2}, None),
    ({"s2": 1, "partial": True, "w_partial": True}, None),
    ({"src": "elems", "open_boundary": True}, "W_OPEN_BOUNDARY"),
    ({"src": "elems", "width_undefined": True}, "W_WIDTH_UNDEFINED"),
    ({"src": "paicad", "paicad_none": True}, "W_PAICAD_NONE"),
])
def test_w_reason_order(facts, code):
    assert sec.w_reason(facts) == code
    if code:
        assert code in sec.W_REASON_ORDER


def test_w_reason_messages_exist():
    import json
    m = json.load(open(os.path.join(ROOT, "resources", "doe_messages.json"), encoding="utf-8"))["messages"]
    for c in sec.W_REASON_ORDER + sec.W_DEFAULT_OFF + (sec.W_ONE_SIDE, "DS_FALLBACK", "DS_ONE_SIDE",
                                                     "DS_ENGINE_NATIVE", "DS_CLONE_NOTE", "DS_CLONE_NOTE_ENTRY",
                                                     "DS_THETA_SPREAD", "DS_HOLD_PINCH"):
        assert c in m, c
    assert sec.w_reason_doc("W_AREA", m) == {"code": "W_AREA", "text": m["W_AREA"]}


def test_clone_depth_table():
    spec = {"params": [{"name": "B1_D"}, {"name": "B3_W"}]}
    # (1) 원 키 없음 + 요청 없음 / entry_fixed = 키 없음
    for req in (None, "entry_fixed"):
        r = sec.clone_depth({"spec": spec}, req, rules_now=RULES)
        assert r["keys"] is None and not r["changed"] and r["dropped"] == []
    # (2) 원 키 없음 + floor_fixed = 키 + 지금 rules
    r = sec.clone_depth({"spec": spec}, "floor_fixed", rules_now=RULES)
    assert r["keys"] == {"depth_section": "floor_fixed", "depth_section_rules": RULES} and r["changed"]
    # (3) 원 floor + entry = 두 키 삭제 + W1 dropped
    o = {"depth_section": "floor_fixed", "depth_section_rules": {**RULES, "one_side_min_nodes": 4}, "spec": spec}
    r = sec.clone_depth(o, "entry_fixed", rules_now=RULES, w1_names=["B3_W"])
    assert r["keys"] is None and r["dropped"] == ["B3_W"] and r["from"] == "floor_fixed"
    # (4) 같은 값 = 원 블록 그대로(원 rules 유지)
    r = sec.clone_depth(o, None, rules_now=RULES)
    assert r["keys"] == {"depth_section": "floor_fixed", "depth_section_rules": o["depth_section_rules"]}
    with pytest.raises(EslError) as ei:
        sec.clone_depth(o, "bogus", rules_now=RULES)
    assert ei.value.code == "INVALID_PARAMS"
    assert sec.spec_without(spec, ["B3_W"])["params"] == [{"name": "B1_D"}]


def test_hash_view():
    assert sec.hash_view(None, RULES, True) is None and sec.hash_view("entry_fixed", RULES, True) is None
    assert sec.hash_view("floor_fixed", RULES, False) == {"ds": "floor_fixed", "one_side_min_nodes": 3}
    assert set(sec.hash_view("floor_fixed", RULES, True)) == {"ds", "one_side_min_nodes", "theta_min_deg",
                                                              "theta_spread_deg"}


def test_feasible():
    assert sec.feasible_open_cap(10.0, [], 1.0, 0.5, 0.5) == 15.0
    assert sec.feasible_open_cap(10.0, [(20.0, 2.0)], 1.0, 0.5, 0.5) == 15.0
    assert sec.feasible_open_cap(10.0, [(8.0, 2.0)], 1.0, 0.5, 0.5) == 12.0
    assert sec.feasible_open_cap(10.0, [(8.0, 1.0)], 1.0, 0.5, 0.5) == 14.0
    assert sec.w_lo_floor_fixed(40.0, 10.0, 1.0, 6.0) == 40.0 - (20.0 - 6.0)
    assert sec.w1_feasible(40.0, 30.0, 6.0, 0.5) == [16.0, 60.0]


def test_fig_v16():
    s = [-30, -20, -10, 0, 10, 20, 30]
    z = [0, 0, 10, 10, 10, 0, 0]               # entry at ±20, floor ±10 (45°)
    df = sec.fig_ds_dD(s, z, 10.0, 1.0, "floor_center", floor_mode=True)
    assert df[2] == 0.0 and df[3] == 0.0 and df[4] == 0.0          # 깊이면 0
    d = sec.fig_ds_dD(s, z, 10.0, 1.0, "floor_center", floor_mode=False)
    assert d[2] > 0 and d[4] < 0                                   # entry_fixed: 깊이면 가장자리 안쪽
    assert sec.fig_ds_dD(s, z, 10.0, 1.0, "stretch", floor_mode=False) == [0.0] * 7
    w1 = sec.fig_ds_dW1(s, z, 10.0, 1)
    assert w1[4] == 1.0 and w1[2] == 0.0 and w1[0] == 0.0
    assert math.isclose(sec.compose([0, 2], [[1, 0, 0], [0, 1, 0]], [([2, 3], [[0, 1, 0], [1, 0, 0]], 2.0)])[1][1][1],
                        3.0)
