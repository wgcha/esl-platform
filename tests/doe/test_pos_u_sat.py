"""v0.24.9 독립 검증 보정 INT-7·8(계약 esl_bead_pos_u.md §1.2·§1.3): range guard U 포화 U_SATURATED · 짧은 구간 U_SHORT_SEG.

- INT-7: range guard U 항목이 실제/요청 이동 비(``section.u_motion_ratio`` — 기저 ΔU 당 최대 노드 이동)를 재서 설정
  ``pos_u.sat_ratio_min`` 보다 작으면 정보만: 항목 u_sat{ratio, move_mm} + 비드 정보 U_SATURATED{ratio, move_mm, lo_mm, hi_mm}(이동 mm).
  guard state·usable(변수 단위)·기본 범위·feasible·기저 불변 → 기본 범위 끝 값에 RG_OUTSIDE_GUARD 없음(재검증 보정).
- INT-8: U 기저 달성 구간 없음(short)이 램프 때문(길이 < 2·램프)이면 정보 U_SHORT_SEG{length_mm, ramp_mm, ratio}.
- 실측(H6 — slow): B3·B4 비 0.102·0.100(36 mm < 램프 44·45 mm) → 정보 U_SATURATED(이동 ±1.5 mm)·U_SHORT_SEG, guard ok·usable = 범위,
  나머지 U = 정보 없음."""
from __future__ import annotations

import copy
import json
import os

import numpy as np
import pytest
import synth_pos_u as W
from _bg_util import CFG, esl_mesh

from esl.doe import DEFAULTS, load_messages
from esl.doe import bead_graph as bgr
from esl.doe import bead_select as bsel
from esl.morph import section as sec

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _derive(range_u=None):
    import beadgraph as bg
    from beadgraph.testing import synth_oneside as so
    c = so.channel()
    mesh = esl_mesh({"x0": c["nodes"], "conn": c["conn"]})
    g, lab = bg.classify(c["nodes"], c["conn"], c["fixed"])
    sel, _sp, _w = bgr.auto_seed(g, lab, CFG)
    from esl.doe import transfer_plan as tp
    sr = tp.resolve_shape({"schema": 1}, CFG)             # range guard 규칙(새 스냅샷)
    norm, _sha = bgr.normalize_v2(sel, g, CFG, mesh=mesh, labels=lab, shape_rules=sr)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=[], pos_u=W.pos_u_snap(), shape_rules=sr)
    if range_u is not None:                             # 기저 범위 강제(검증 스크립트 u_models 와 같은 방법 — 포화 재현)
        for b in D.beads:
            if "U" in b.range_basis:
                b.range_basis["U"] = list(range_u)
                b.range_default["U"] = list(range_u)
    return mesh, D


def _guard(mesh, D, cfg=None):
    B = bsel.basis(mesh, D, CFG)
    un = [v["name"] for v in B.vars if v["name"].endswith("_U")]
    assert un
    vec0 = {v["name"]: np.asarray(v["vec"]).copy() for v in B.vars}
    doc = bgr.guard_selection(mesh, D, B, cfg if cfg is not None else CFG, only=un)
    for v in B.vars:                                    # 기저 불변(보고만)
        assert np.array_equal(np.asarray(v["vec"]), vec0[v["name"]]), v["name"]
    return B, {e["var"]: e for e in doc["entries"]}


def _infos(D, code):
    return [w for b in D.beads for w in b.warnings if w.get("code") == code]


def test_pure_ratio_saturation_short():
    v = np.zeros((4, 3))
    v[1] = [0.3, 0.0, 0.0]
    v[2] = [0.0, 0.4, 0.0]
    assert sec.u_motion_ratio(v) == pytest.approx(0.4) and sec.u_motion_ratio(np.zeros((0, 3))) == 0.0
    assert sec.u_saturation(v, -10.0, 5.0, 0.4) is None                       # 비 = 기준 → 포화 아님
    s = sec.u_saturation(v, -10.0, 5.0, 0.9)
    assert s["ratio"] == pytest.approx(0.4) and s["usable"] == pytest.approx([-4.0, 2.0])
    assert sec.u_short_seg(True, 36.0, 44.0) and not sec.u_short_seg(True, 46.0, 8.9) and not sec.u_short_seg(False, 1, 9)
    assert sec.u_short_seg(True, 80.0, 44.0) == (80.0 < sec.U_SHORT_RAMP_ENDS * 44.0)


def test_channel_default_no_saturation():
    """기본 범위 채널: 비 1 → guard ok·usable = 범위, U_SATURATED·U_SHORT_SEG 없음(골든 세계 바이트 그대로)."""
    mesh, D = _derive()
    B, ent = _guard(mesh, D)
    e = ent["B1_U"]
    assert sec.u_motion_ratio(next(v["vec"] for v in B.vars if v["name"] == "B1_U")) == pytest.approx(1.0, abs=1e-9)
    assert e["state"] == "ok" and "u_sat" not in e
    assert not _infos(D, "U_SATURATED") and not _infos(D, "U_SHORT_SEG")


def test_channel_forced_range_saturates_report_only():
    """기저 범위를 램프보다 긴 끝(±240)으로 강제: 이동 비 < sat_ratio_min → 정보 U_SATURATED(이동 mm = 끝 × 비)·항목 u_sat, guard state·
    usable(변수 단위)·기본 범위·feasible 그대로 → 범위 끝 값에 RG_OUTSIDE_GUARD 없음. 램프 원인 → U_SHORT_SEG(비 같음). 설정 비를 낮추면 포화 아님."""
    big = [-240.0, 240.0]
    mesh, D = _derive(big)
    b = next(x for x in D.beads if "U" in x.range_basis)
    fe0, de0 = list(b.range_feasible["U"]), list(b.range_default["U"])
    B, ent = _guard(mesh, D)
    r = sec.u_motion_ratio(next(v["vec"] for v in B.vars if v["name"] == "B1_U"))
    sat_min = float(DEFAULTS["pos_u"]["sat_ratio_min"])
    assert 0.0 < r < sat_min
    e = ent["B1_U"]
    assert e["state"] == "ok" and e["usable"] == pytest.approx(big)                # 품질 점검 결과 그대로(변수 단위)
    assert all(x["ok"] and x["reason"] != "U_SATURATED" for x in e["ends"])
    assert e["u_sat"]["ratio"] == pytest.approx(r, abs=1e-4)
    assert e["u_sat"]["move_mm"] == pytest.approx([big[0] * r, big[1] * r], abs=1e-3)
    assert b.range_default["U"] == de0 and b.range_feasible["U"] == fe0          # 보고만
    assert b.guard["U"]["state"] == "ok" and b.guard["U"]["usable"] == pytest.approx(big) and "u_sat" not in b.guard["U"]
    assert not [w for w in b.warnings if w.get("code") in ("RG_RANGE_LIMITED", "RG_VAR_BLOCKED") and w.get("var") == "B1_U"]
    (w,) = _infos(D, "U_SATURATED")
    assert w["var"] == "B1_U" and w["level"] == "info" and w["ratio"] == pytest.approx(r, abs=1e-4)
    assert [w["lo_mm"], w["hi_mm"]] == w["move_mm"] == e["u_sat"]["move_mm"] and "usable" not in w
    (s,) = _infos(D, "U_SHORT_SEG")
    assert s["var"] == "B1_U" and s["length_mm"] < sec.U_SHORT_RAMP_ENDS * s["ramp_mm"] and s["ratio"] == pytest.approx(r, abs=1e-4)
    rows = bgr.params_rows_v2(D, CFG)
    row = next(x for x in rows if x["name"] == "B1_U")
    assert row["default_range"] == de0 and row["guard"]["state"] == "ok"
    for val in (big[0], big[1], 0.5 * big[1]):                                   # 범위 안 값 = 경고 없음(포화 때문에 RG_OUTSIDE_GUARD 금지)
        assert bgr.outside_guard(rows, {"B1_U": val}) is None
    # 판단 기준 = 설정 키(pos_u.sat_ratio_min) — 비보다 낮추면 포화 아님
    mesh2, D2 = _derive(big)
    cfg = copy.deepcopy(CFG)
    cfg["pos_u"] = {**DEFAULTS["pos_u"], "sat_ratio_min": r / 2}
    _B2, ent2 = _guard(mesh2, D2, cfg)
    assert ent2["B1_U"]["state"] == "ok" and "u_sat" not in ent2["B1_U"] and not _infos(D2, "U_SATURATED")


def test_messages_and_settings_mirror():
    """문구 = resources/doe_messages.json(자리 표시자 = 정보 필드), 설정 키 sat_ratio_min = DEFAULTS·pydantic·yaml 2 같은 값."""
    import re

    import yaml
    from esl_platform.core.config import BeadDoePosUCfg
    msgs = load_messages()["messages"]
    fields = {"U_SATURATED": {"var", "ratio", "lo_mm", "hi_mm", "bead", "move_mm", "from", "level", "code"},
              "U_SHORT_SEG": {"var", "ratio", "length_mm", "ramp_mm", "bead", "level", "code"}}
    for code, ok in fields.items():
        assert set(re.findall(r"\{(\w+)\}", msgs[code])) <= ok, code
    v = DEFAULTS["pos_u"]["sat_ratio_min"]
    assert BeadDoePosUCfg().sat_ratio_min == v
    for y in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        with open(os.path.join(ROOT, "config", y), encoding="utf-8") as fh:
            assert yaml.safe_load(fh)["bead_doe"]["pos_u"]["sat_ratio_min"] == v, y
    with pytest.raises(ValueError):
        BeadDoePosUCfg(sat_ratio_min=0.0)
    with pytest.raises(ValueError):
        BeadDoePosUCfg(sat_ratio_min=1.5)
    assert "sat_ratio_min" not in sec.pos_u_hash_view({**DEFAULTS["pos_u"]})     # 해시 밖(기저 캐시·sha 불변)
    json.dumps(msgs["U_SATURATED"])


@pytest.mark.slow
def test_h6_short_beads_saturated_and_short_seg():
    """실측 H6(기본 범위): B3·B4 = 세그먼트 36 mm < 램프 2×44·45 mm → 비 ≈ 0.10, 정보 U_SATURATED(이동 ±1.5 mm)·U_SHORT_SEG, guard ok·
    usable = 기본 범위(기본 범위 끝 값에 RG_OUTSIDE_GUARD 없음). 나머지 U(B6·B7 비 0.956 ≥ 0.9, B10~B14 비 1) = 정보 없음."""
    from _bg_util import prepared

    from esl.doe import transfer_plan as tp
    mesh, g, lab, fixed, _d = prepared("h6")
    sel, _sp, _w = bgr.auto_seed(g, lab, CFG)
    sr = tp.resolve_shape({"schema": 1}, CFG)
    norm, _sha = bgr.normalize_v2(sel, g, CFG, mesh=mesh, labels=lab, shape_rules=sr)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=list(fixed), shape_rules=sr,
                          depth_section=DEFAULTS["depth_section"], section_rules=DEFAULTS["depth_section_rules"],
                          pos_u=W.pos_u_snap())
    de0 = {b.id: list(b.range_default["U"]) for b in D.beads if "U" in b.range_basis}
    B, ent = _guard(mesh, D)
    sat = {w["var"]: w for w in _infos(D, "U_SATURATED")}
    short = {w["var"]: w for w in _infos(D, "U_SHORT_SEG")}
    assert set(sat) == set(short) == {"B3_U", "B4_U"}
    rows = {r["name"]: r for r in bgr.params_rows_v2(D, CFG)}
    for n in ("B3_U", "B4_U"):
        assert sat[n]["ratio"] == pytest.approx(0.10, abs=0.005) and ent[n]["state"] == "ok"
        assert sat[n]["move_mm"] == pytest.approx([-1.5, 1.5], abs=0.01) and ent[n]["u_sat"]["move_mm"] == sat[n]["move_mm"]
        assert ent[n]["usable"] == pytest.approx(ent[n]["from"])
        assert short[n]["length_mm"] == pytest.approx(36.0, abs=0.5) and short[n]["ramp_mm"] > short[n]["length_mm"]
        lo, hi = rows[n]["default_range"]
        for val in (lo, hi):                            # 재검증 Fail: 기본 범위 끝 값(예 B3_U 14.685)에 RG_OUTSIDE_GUARD 없음
            assert bgr.outside_guard(list(rows.values()), {n: val}) is None, (n, val)
    for n, e in ent.items():
        if n not in sat:
            assert e["state"] == "ok" and "u_sat" not in e, (n, e["state"])
    by = {b.id: b for b in D.beads}
    for bid in ("b3", "b4"):                            # 포화만 = 기본 범위 그대로(B10~B14 는 기존 조합 축소 — 변경 없음)
        assert list(by[bid].range_default["U"]) == de0[bid]
