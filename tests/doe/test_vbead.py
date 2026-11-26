"""V-0250-VB-3·5·6·7·8·9·10·15·16·19 — 가상 비드 derive·선택·기저·range guard(계약 esl_virtual_bead.md §2~7, §12).

세계 = ``synth_vbead.graph_world``(평판 300×200·h 5 + 실제 채널 비드(−z, y = 60) + 사각 구멍(240, 150 — 둘레 = fixed-scan)).
"""
import copy
import io
import json
import os
import re
import struct
import sys
import tempfile
from functools import lru_cache

import numpy as np
import pytest
import synth_guard as sg
import synth_vbead as sv
from _bg_util import CFG, bgr, bs

from esl.doe import DEFAULTS, matrix
from esl.doe import transfer_plan as tp
from esl.errors import EslError
from esl.morph import range_guard as rgm
from esl.morph import section as sec
from esl.morph import virtual_bead as vbm

BLK = {"schema": 1, **{k: DEFAULTS["virtual_bead"][k] for k in vbm.HASH_KEYS}}
RU = sg.rules()
FR = sv.frame_of()
VB_OK = {"id": "a1", "p0": [60.0, 140.0, 0.0], "p1": [180.0, 140.0, 0.0], "w_top": 10.0, "d_max": 6.0}


def push_z(vb) -> float:
    """가상 비드가 미는 방향의 z 성분(side × n_h — side 는 n_h 기준)."""
    return float(vb.side * vb.plane[1][2])


@lru_cache(maxsize=2)
def W(channel=True):
    return sv.graph_world(channel=channel)


def sel(vbs=(), beads=True, **kw):
    m, g, lab, _fx, _d = W()
    s = {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": int(g["rules"]), "edits": {}},
         "beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": int(g["segments"][1]["anchor"])}]}] if beads else [],
         "ties": []}
    if vbs is not None:
        s["virtual_beads"] = [dict(v) for v in vbs]
    s.update(kw)
    return s


def norm(s, cfg=CFG):
    m, g, lab, _fx, _d = W()
    return bgr.normalize_v2(s, g, cfg, labels=lab, mesh=m)


def derive(vbs=(VB_OK,), beads=True, rules=None, blk=BLK, plan="plate", frame=FR, tie=(), **kw):
    m, g, lab, fx, _d = W()
    n, _sha = norm(sel(vbs, beads, **kw))
    return bgr.derive_obj_v2(m, n, CFG, g, lab, fixed_node_ids=fx, shape_rules=rules, virtual_bead=blk, vb_plan=plan,
                             frame=frame, tie_node_ids=tie)


# ---------------------------------------------------------------- V-0250-VB-5 선택 문서
def test_selection_key_absent_or_empty_same_sha_v5():
    a = norm(sel(vbs=None))
    b = norm(sel(vbs=[]))
    assert a == b and "virtual_beads" not in a[0]


@pytest.mark.parametrize("bad,code", [
    ({"p1": [1, 2, 3], "length": 10.0}, "VB_INPUT_INVALID"),                       # 두 형식 함께
    ({"p1": None}, "VB_INPUT_INVALID"),                                             # p1·length 둘 다 없음
    ({"p1": [60.0, 140.0, 0.0]}, "VB_INPUT_INVALID"),                               # 길이 0
    ({"w_top": 0}, "VB_INPUT_INVALID"), ({"d_max": 31.0}, "VB_INPUT_INVALID"), ({"theta_deg": 80.0}, "VB_INPUT_INVALID"),
    ({"side": "up"}, "VB_INPUT_INVALID"), ({"end": "flat"}, "VB_INPUT_INVALID"), ({"r": -1}, "VB_INPUT_INVALID"),
    ({"id": "v1"}, "VB_INPUT_INVALID"), ({"id": "a5"}, "VB_INPUT_INVALID"), ({"foo": 1}, "VB_INPUT_INVALID"),
    ({"name": "x\ny"}, "VB_INPUT_INVALID"), ({"p0": [0, 0, float("nan")]}, "VB_INPUT_INVALID"),
    ({"w_top": True}, "VB_INPUT_INVALID")])
def test_selection_422_v5(bad, code):
    v = {**VB_OK, **bad}
    v = {k: x for k, x in v.items() if x is not None}
    with pytest.raises(EslError) as ei:
        norm(sel([v]))
    assert ei.value.code == code


def test_selection_max_count_and_dups_v5():
    many = [{**VB_OK, "id": f"a{i}"} for i in range(1, 6)]
    with pytest.raises(EslError) as ei:
        norm(sel(many))
    assert ei.value.code == "VB_MAX_COUNT"
    with pytest.raises(EslError) as ei:
        norm(sel([VB_OK, dict(VB_OK)]))
    assert ei.value.code == "VB_INPUT_INVALID"


def test_selection_forms_and_defaults_v5():
    b = {"id": "a2", "p0": [60.0, 100.00004, 0.0], "length": 120.0, "angle_deg": 0.0, "w_top": 10.0, "d_max": 4.0,
         "theta_deg": 45.0, "end": "round", "r": 0.0, "name": "추가 비드 2"}
    n, _ = norm(sel([b, VB_OK]))
    vb = n["virtual_beads"]
    assert [x["id"] for x in vb] == ["a1", "a2"]                                    # id 정렬
    assert vb[1] == {"id": "a2", "p0": [60.0, 100.0, 0.0], "length": 120.0, "angle_deg": 0.0, "w_top": 10.0,
                     "d_max": 4.0}                                                   # (b) 그대로·기본값 키 생략·1e-4
    assert vb[0]["p1"] == [180.0, 140.0, 0.0] and "length" not in vb[0]              # (a) 그대로
    n2, _ = norm(sel([{**b, "side": "+", "end": "square", "r": 1.0, "theta_deg": 60.0}]))
    assert {k: n2["virtual_beads"][0][k] for k in ("side", "end", "r", "theta_deg")} == \
        {"side": "+", "end": "square", "r": 1.0, "theta_deg": 60.0}


def test_selection_virtual_only_and_empty_v5():
    n, sha = norm(sel([VB_OK], beads=False))                                        # VB-15: 가상 비드만 허용
    assert n["beads"] == [] and n["virtual_beads"][0]["id"] == "a1"
    with pytest.raises(EslError) as ei:
        norm(sel([], beads=False))
    assert ei.value.code == "SELECT_EMPTY_TIER" and "beads 는 1.." in ei.value.message   # 기존 오류 그대로
    with pytest.raises(EslError) as ei:
        norm(sel([VB_OK], ties=[["b1", "a1"]]))
    assert ei.value.code == "BG_TIE_NOMINAL"


# ---------------------------------------------------------------- V-0250-VB-6 계획 표
def test_plan_tables_v6():
    sec.validate_plans()
    assert set(sec.PLAN_COLUMNS) >= {"form", "vb_host"}
    for r, p in sec.SECTION_PLANS.items():
        assert set(p) == set(sec.PLAN_COLUMNS) and all(p.values()), r
    assert {r: sec.form_plan(r) for r in sec.SECTION_PLANS} == {"graph": "linear", "elems": "linear", "paicad": "native",
                                                                "none": "none", "virtual": "hinge"}
    bad = {**sec.SECTION_PLANS, "graph": {**sec.SECTION_PLANS["graph"], "vb_host": ""}}
    with pytest.raises(EslError):
        sec.plan("graph", bad)
    truth = {(pid, row): sec.vb_allowed(tp.PLANS[pid]["vbead"], row) for pid in tp.PLANS for row in sec.SECTION_PLANS}
    assert {k for k, v in truth.items() if v} == {("case_once", "graph"), ("bmesh_once", "graph"), ("step_once", "graph")}
    assert len(truth) == 25
    assert not sec.vb_allowed(tp.plan_for("same")["vbead"], "paicad")              # paicad same(case_once) = 불가
    for k in tp.PLAN_OF:
        assert tp.plan_for(*k)["vbead"] in tp.VBEAD
    bad = copy.deepcopy(tp.PLANS)
    with pytest.raises(EslError):
        sec.vb_allowed("plates", "graph")
    _ = bad


def test_no_scenario_branch_static_v6():
    """호출 쪽 시나리오 이름 분기 0(가상 비드 코드 — bead_graph VB 절·virtual_bead 모듈)."""
    src = open(bgr.__file__, encoding="utf-8").read()
    vb_part = src[src.index("# ====================================================================== v0.25.0 VB"):]
    for name in ("same", "mesh", "step", "compare", "select", "case_once", "step_once", "bmesh_once"):
        assert not re.search(rf"==\s*[\"']{name}[\"']", vb_part), name
    assert "scenario" not in open(vbm.__file__, encoding="utf-8").read()


# ---------------------------------------------------------------- derive · 사유(V-0250-VB-3 실제 분류)
def test_derive_ok_rows_v3():
    D = derive()
    vb = D.vbeads[0]
    assert vb.ok and vb.reasons == [] and push_z(vb) < 0                             # 채널(−z) 다수 = 같은 쪽
    rows = {r["name"]: r for r in bgr.params_rows_v2(D, CFG)}
    r = rows["A1_A"]
    assert r["type"] == "A" and r["form"] == "hinge" and r["nominal"] == 0.0 and r["feasible"] == [0.0, 6.0]
    assert r["default_range"] == [0.0, 6.0] and r["use_default"] is True and r["label"] == "추가 비드 1 · 깊이"
    assert r["feasible_source"] == "user" and r["group_members"] == ["A1_A"] and \
        r["vb"]["side"] == ("+" if vb.side > 0 else "-")
    assert r["vb"]["len_mm"] == pytest.approx(120.0) and r["wall_elems"] == pytest.approx(6.0 / vb.h, abs=0.01)
    pb = bgr.param_beads(D)
    assert pb[-1] == {"id": "a1", "name": "추가 비드 1", "kind": "virtual", "warnings": vb.warnings}
    codes = [w["code"] for w in vb.warnings]
    assert "VB_EDGE_SMEAR" in codes and "VB_WALL_COARSE" in codes                    # run 6 < 2h(h 5)
    # 면내 이동 0, 발자국 밖 0
    f = vb.field
    assert np.abs(f["vec"][:, :2]).max() < 1e-9


def _codes(vbs, **kw):
    D = derive(vbs, **kw)
    return [v.reasons for v in D.vbeads]


@pytest.mark.parametrize("over,code", [
    ({"p0": [60.0, 70.0, 0.0], "p1": [180.0, 70.0, 0.0]}, "VB_OVER_BEAD"),           # 채널 위
    ({"p0": [200.0, 150.0, 0.0], "p1": [225.0, 150.0, 0.0]}, "VB_OVER_HOLE"),
    ({"p0": [60.0, 194.0, 0.0], "p1": [180.0, 194.0, 0.0]}, "VB_PLATE_EDGE"),
    ({"p0": [60.0, 140.0, 0.0], "p1": [180.0, 140.0, 0.0], "d_max": 4.0}, "VB_MESH_COARSE"),
    ({"p0": [60.0, 140.0, 20.0], "p1": [180.0, 140.0, 20.0]}, "VB_NOT_ON_PLATE"),     # 판에서 먼 점(사영 > margin + 2h)
])
def test_reasons_on_classified_plate_v3(over, code):
    rs = _codes([{**VB_OK, **over}])[0]
    assert code in rs and rs == sorted(rs, key=vbm.REASONS.index)


def test_reasons_fixed_exclude_overlap_scope_v3():
    hole_vb = {**VB_OK, "p0": [200.0, 150.0, 0.0], "p1": [225.0, 150.0, 0.0]}
    assert "VB_FIXED" in _codes([hole_vb])[0]
    # 지그 tie 노드 = fixed 와 같은 집합(VB_FIXED)
    m = W()[0]
    near = m["node_id"][np.argmin(np.hypot(m["x0"][:, 0] - 120.0, m["x0"][:, 1] - 150.0))]
    assert _codes([VB_OK], tie=(int(near),)) == [["VB_FIXED"]]
    # exclude
    e = int(np.argmin(np.hypot(*(m["x0"][m["conn"]].mean(axis=1)[:, :2] - [120.0, 140.0]).T)))
    ex = {"q": [[int(m["elem_id"][e]), int(m["elem_id"][e])]], "t": []}
    assert _codes([VB_OK], exclude=ex) == [["VB_EXCLUDED"]]
    # 두 가상 비드 겹침 → 둘 다
    two = [VB_OK, {**VB_OK, "id": "a2", "p0": [100.0, 150.0, 0.0], "p1": [150.0, 150.0, 0.0]}]
    assert _codes(two) == [["VB_OVER_VBEAD"], ["VB_OVER_VBEAD"]]
    # 범위 밖: 블록 없음 · 계획 none · 분류 없음(GRAPH_FAILED)
    assert _codes([VB_OK], blk=None) == [["VB_SCOPE"]]
    assert _codes([VB_OK], plan="none") == [["VB_SCOPE"]]
    mm, g, lab, fx, _d = W()
    s = sel([VB_OK], beads=False)
    s.pop("graph")
    n, _ = bgr.normalize_v2(s, None, CFG, labels=None, mesh=mm)
    D = bgr.derive_obj_v2(mm, n, CFG, None, None, fixed_node_ids=fx, virtual_bead=BLK, frame=FR)
    assert [v.reasons for v in D.vbeads] == [["VB_SCOPE"]] and bgr.params_rows_v2(D, CFG) == []


def test_side_default_v19():
    """§2.3: 그래프 비드 없음 = frame n 반대(n +z → −z 로 밂, n −z → +z), side 지정이 우선(n_h 기준)."""
    assert push_z(derive(beads=False).vbeads[0]) < 0
    assert push_z(derive(beads=False, frame=sv.frame_of((0.0, 0.0, -1.0))).vbeads[0]) > 0
    v = derive([{**VB_OK, "side": "+"}]).vbeads[0]
    assert v.side == 1 and push_z(v) == pytest.approx(float(v.plane[1][2]))


def test_derive_doc_v8():
    m, g, lab, fx, _d = W()
    n, _ = norm(sel([VB_OK]))
    doc = bgr.derive_v2(m, n, CFG, g, lab, frame=FR, fixed_scan=fx, virtual_bead=BLK)
    v = doc["virtual_beads"][0]
    assert v["ok"] and v["side_resolved"] in ("+", "-") and v["len_mm"] == pytest.approx(120.0) and v["angle_deg"] == 0.0
    assert v["p1_resolved"] == [180.0, 140.0, 0.0] and v["outline_ab"][0] == v["outline_ab"][-1]
    assert set(doc["vb_frame"]) == {"origin", "e_xi", "e_eta", "n_h"}
    pv = v["preview"]
    D = bgr.derive_obj_v2(m, n, CFG, g, lab, fixed_node_ids=fx, virtual_bead=BLK, frame=FR)
    B = bs.basis(m, D, CFG)
    a = next(x for x in B.vars if x["name"] == "A1_A")
    assert pv["idx"] == a["idx"].tolist() and np.allclose(pv["g"], a["g"], atol=1e-6) and pv["c"] == a["c"]
    assert any(r["name"] == "A1_A" for r in doc["params"]) and doc["param_beads"][-1]["kind"] == "virtual"
    # 상한 넘으면 preview 생략 + 정보
    cfg2 = copy.deepcopy(CFG)
    cfg2["virtual_bead"]["preview_max_nodes"] = 5
    doc2 = bgr.derive_v2(m, n, cfg2, g, lab, frame=FR, fixed_scan=fx, virtual_bead=BLK)
    v2 = doc2["virtual_beads"][0]
    assert "preview" not in v2 and any(w["code"] == "VB_PREVIEW_SKIPPED" for w in v2["warnings"])
    # 가상 비드 없는 선택 = 키 없음
    n0, _ = norm(sel(vbs=None))
    assert "virtual_beads" not in bgr.derive_v2(m, n0, CFG, g, lab, frame=FR, fixed_scan=fx, virtual_bead=BLK)


# ---------------------------------------------------------------- V-0250-VB-7·8 기저 형식 · 브라우저 식
def _parse_bin(blob, meta):
    """basis.ts parseBasis 와 같은 규칙(float32, hinge 꼬리 g, 길이 엄격)."""
    off, out = 0, []
    for v in meta["vars"]:
        n = struct.unpack_from("<I", blob, off)[0]
        off += 4
        idx = np.frombuffer(blob, "<u4", n, off)
        off += 4 * n
        vec = np.frombuffer(blob, "<f4", 3 * n, off).reshape(n, 3)
        off += 12 * n
        g = None
        if v.get("form") == "hinge":
            g = np.frombuffer(blob, "<f4", n, off)
            off += 4 * n
        out.append((v, idx, vec, g))
    if off != len(blob):
        raise ValueError("length")
    return out


def _ts_morph(x0, parsed, values):
    x = np.asarray(x0, np.float32).copy()
    for v, idx, vec, g in parsed:
        if v["name"] not in values:
            continue
        val = np.float32(values[v["name"]])
        if g is None:
            x[idx] += (val - np.float32(v["nominal"])) * vec
        else:
            c = np.float32(v["c"])
            f = vbm.ramp(val - g.astype(np.float64), float(c)) - vbm.ramp(float(v["nominal"]) - g.astype(np.float64), float(c))
            x[idx] += vec * f.astype(np.float32)[:, None]
    return x


def test_basis_format_roundtrip_v7_v8(tmp_path):
    m, g, lab, fx, _d = W()
    D = derive()
    B = bs.basis(m, D, CFG)
    names = [v["name"] for v in B.vars]
    assert "A1_A" in names and "B1_D" in names
    p = str(tmp_path / "basis.npz")
    bs.save_basis(p, B)
    with np.load(p) as z:
        assert {"form", "g", "c"} <= set(z.files) and z["form"].dtype.str.endswith("U6")
    L = bs.load_basis(p)
    la = next(v for v in L.vars if v["name"] == "A1_A")
    assert la["form"] == "hinge" and la["g"].tobytes() == next(v for v in B.vars if v["name"] == "A1_A")["g"].tobytes()
    x0 = np.asarray(m["x0"])
    vals = {"A1_A": 3.0, "B1_D": 7.0}
    assert bs.morph(x0, L, vals).tobytes() == bs.morph(x0, B, vals).tobytes()
    meta = bs.basis_meta(B, "x")
    am = next(v for v in meta["vars"] if v["name"] == "A1_A")
    assert am["form"] == "hinge" and "form" not in next(v for v in meta["vars"] if v["name"] == "B1_D")
    blob = bs.basis_bin(B)
    parsed = _parse_bin(blob, meta)
    with pytest.raises(ValueError):
        _parse_bin(blob[:-4], meta)                                                  # 꼬리 빠짐
    with pytest.raises(ValueError):
        _parse_bin(blob + b"\0\0\0\0", meta)                                         # 남음
    for vv in ({"A1_A": 3.0}, {"A1_A": 4.0, "B1_D": 5.0}, {"A1_A": 0.7}):
        d = np.abs(_ts_morph(x0, parsed, vv).astype(np.float64) - bs.morph(x0, B, vv)).max()
        assert d <= 1e-4, d
    # 모핑 = §4.1(평판·r 0): 깊이면 노드 = −D(z)
    a = next(v for v in B.vars if v["name"] == "A1_A")
    x = bs.morph(x0, B, {"A1_A": 3.0})
    top = a["idx"][a["g"] <= 0.0]
    assert np.allclose(x[top, 2] - x0[top, 2], -3.0, atol=1e-12)                    # 채널과 같은 쪽(−z)
    moved = np.flatnonzero(np.any(x != x0, axis=1))
    assert set(moved.tolist()) <= set(a["idx"].tolist())


# ---------------------------------------------------------------- V-0250-VB-9 range guard
def test_one_sided_rules_unit_v9():
    assert rgm.all_blocked(0.0, [0.0, 6.0], [0.0, 0.5], 0.25) is True
    assert rgm.all_blocked(0.0, [0.0, 6.0], [0.0, 3.0], 0.25) is False
    assert rgm.all_blocked(5.0, [4.0, 6.0], [4.9, 5.1], 0.25) is True                # 양쪽 = 두 값 and
    assert rgm.all_blocked(5.0, [4.0, 6.0], [4.0, 5.1], 0.25) is False
    assert rgm.side_stuck(0.0, [0.0, 6.0], [0.0, 0.0]) and rgm.side_stuck(0.0, [0.0, 6.0], [0.0, 0.0001])
    assert not rgm.side_stuck(0.0, [0.0, 6.0], [0.0, 2.0])
    assert rgm.side_stuck(5.0, [4.0, 6.0], [5.0, 5.5]) and not rgm.side_stuck(5.0, [4.0, 6.0], [4.5, 5.5])
    vb = bgr.VirtualBead({"id": "a1", "p0": [0, 0, 0], "w_top": 10.0, "d_max": 6.0}, BLK)
    e = {"state": "limited", "usable": [0.0, 2.5], "ends": [{"side": "lo", "ok": True}, {"side": "hi", "ok": False,
                                                                                         "reason": "warp", "value": 30.0}]}
    bgr._apply_single(vb, "A", e, 0.0)
    assert vb.guard["A"]["state"] == "limited" and vb.range_default["A"] == [0.0, 2.5]
    assert vb.warnings[-1]["code"] == "RG_RANGE_LIMITED"
    vb2 = bgr.VirtualBead({"id": "a2", "p0": [0, 0, 0], "w_top": 10.0, "d_max": 6.0}, BLK)
    bgr._apply_single(vb2, "A", {**e, "usable": [0.0, 0.0]}, 0.0)
    assert vb2.guard["A"]["state"] == "blocked" and vb2.warnings[-1]["code"] == "RG_VAR_BLOCKED"
    r = bgr.vb_row(type("X", (), {**vb2.__dict__, "ok": True, "h": 5.0, "n_wall": 1.0, "n_top": 2.0, "side": -1,
                                  "L": 1.0, "angle": 0.0})(), CFG)
    assert r["use_default"] is False


def _guard(vbs, beads=True):
    m, g, lab, fx, _d = W()
    n, _ = norm(sel(vbs, beads))
    D = bgr.derive_obj_v2(m, n, CFG, g, lab, fixed_node_ids=fx, shape_rules=RU, virtual_bead=BLK, frame=FR)
    rows = {r["name"]: r for r in bgr.params_rows_v2(D, CFG)}
    B = bs.basis(m, D, CFG)
    doc = bgr.guard_selection(m, D, B, CFG, only=[r["name"] for r in rows.values()
                                                  if (r.get("guard") or {}).get("state") == "unchecked"])
    return D, doc


def test_guard_selection_a_v9():
    """d_max 끝 위반 → limited(usable_hi < d_max, blocked 아님 — SH-28 보정) · warp crit = A 항목만 · W 띠 겹침 = 조합·정보.
    측정(VB-C1-5): r 0 모서리는 꺾임이 요소 안에 들어가 warpage > 15° 가 작은 D 에서 생김(h 5: usable 0.75 — blocked),
    θ 75° 는 사면 회전 > flip_deg 60° = 뒤집힘(blocked). limited 사례는 r 10(둥글린 모서리)."""
    rounded = {**VB_OK, "r": 10.0}
    near = {"id": "a2", "p0": [70.0, 95.0, 0.0], "p1": [200.0, 95.0, 0.0], "w_top": 6.0, "d_max": 3.0, "theta_deg": 15.0}
    D, doc = _guard([rounded, near])
    assert [v.reasons for v in D.vbeads] == [[], []]
    ea = {e["var"]: e for e in doc["entries"]}
    a1 = ea["A1_A"]
    assert a1["state"] == "limited" and 0.0 < a1["usable"][1] < 6.0 and a1["usable"][0] == 0.0
    assert [x["reason"] for x in a1["ends"] if not x["ok"]] == ["warp"]
    assert a1["crit"] == {"warp_max_deg": BLK["warp_max_deg"]}
    assert all("crit" not in e for k, e in ea.items() if not k.startswith("A"))
    rows = {r["name"]: r for r in bgr.params_rows_v2(D, CFG)}
    assert rows["A1_A"]["guard"]["state"] == "limited" and rows["A1_A"]["default_range"] == [0.0, a1["usable"][1]]
    assert rows["A1_A"]["use_default"] is True
    assert any(w["code"] == "RG_RANGE_LIMITED" for w in D.vbeads[0].warnings)
    crit = bgr._crit(RU["range_guard"], CFG)
    assert doc["crit"] == {k: (None if crit.get(k) is None else float(crit[k])) for k in rgm.CRIT_KEYS}   # 문서 crit 불변
    ov = [w for w in D.vbeads[1].warnings if w["code"] == "VB_BAND_OVERLAP"]
    assert ov and any(v.startswith("B1_") for v in ov[0]["vars"])
    assert any("A2_A" in c["vars"] for c in doc["combos"]) or any("A2_A" in (s.get("detail") or {}).get("vars", [])
                                                                   for s in doc["skipped"]) or \
        not [c for c in doc["combos"]]                                               # 조합 위반 없으면 combos 없음


def test_guard_blocked_measured_v9():
    """측정 고정(VB-C1-5): r 0·θ 45(h 5) = warp 로 blocked(usable < min_keep), θ 75 = 뒤집힘 blocked → use_default false·
    RG_VAR_BLOCKED. θ 15 = ok."""
    for v, reason in ((VB_OK, "warp"), ({**VB_OK, "w_top": 5.0, "theta_deg": 75.0, "d_max": 20.0}, "inverted")):
        D, doc = _guard([v], beads=False)
        e = doc["entries"][0]
        assert e["state"] == "blocked" and [x["reason"] for x in e["ends"] if not x["ok"]] == [reason]
        r = next(r for r in bgr.params_rows_v2(D, CFG) if r["name"] == "A1_A")
        assert r["use_default"] is False and D.vbeads[0].warnings[-1]["code"] == "RG_VAR_BLOCKED"
    D, doc = _guard([{**VB_OK, "theta_deg": 15.0}], beads=False)
    assert doc["entries"][0]["state"] == "ok"


# ---------------------------------------------------------------- V-0250-VB-10·15·16 범위 규칙·기본 켬·하중·설정
def test_default_on_and_range_rules_v10():
    D = derive()
    tab = bgr.params_rows_v2(D, CFG)
    dp = matrix.default_params(tab, CFG)
    assert any(p["name"] == "A1_A" and p["lo"] == 0.0 and p["hi"] == 6.0 for p in dp)
    assert CFG["doe"]["default_types"] == ["D", "W"]
    spec = {"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "A1_A", "lo": 0.0, "hi": 4.0}]}
    matrix.normalize_spec(spec, tab, CFG)                                            # lo = 0 통과
    with pytest.raises(EslError) as ei:
        matrix.normalize_spec({**spec, "params": [{"name": "A1_A", "lo": -0.5, "hi": 4.0}]}, tab, CFG)
    assert ei.value.code == "DOE_RANGE_INVALID" and "추가 비드 깊이 하한은 0 이상" in ei.value.message
    assert matrix._POSITIVE == ("D", "W") and matrix._NOMINAL_RULES["U"][0] == "in"
    gen = matrix.generate(spec, tab, CFG)
    assert gen["designs"][0]["values"] == {"A1_A": 0.0}
    th = matrix.thumb_options(CFG, {"n": [0, 0, 1], "e_eta": [0, 1, 0]}, gen["spec"], tab)
    assert th["disp_range_mm"][1] >= 4.0                                             # A |hi| 포함


def test_load_follow_not_position_v15():
    p = tp.plan_for("select", "case")
    assert tp.load_follow_effective(p, False) == "node"                              # A 는 위치 변수 아님(has_pos_var 거짓)


def test_settings_defaults_v16():
    vc = DEFAULTS["virtual_bead"]
    assert set(vc) == {"enabled", "max_count", "min_wall_elems", "margin_mm", "theta_default_deg", "theta_range_deg",
                       "d_max_limit_mm", "default_on", "warp_max_deg", "preview_max_nodes"}
    assert vc["max_count"] == 4 and vc["theta_range_deg"] == [15.0, 75.0] and vc["warp_max_deg"] == 15.0
    assert "A" in __import__("esl.doe", fromlist=["PARAM_TYPES"]).PARAM_TYPES


# ---------------------------------------------------------------- V-0250-VB-19 가상 비드만
def test_virtual_only_guard_single_v19():
    m, g, lab, fx, _d = W()
    n, _ = norm(sel([VB_OK], beads=False))
    D = bgr.derive_obj_v2(m, n, CFG, g, lab, fixed_node_ids=fx, shape_rules=RU, virtual_bead=BLK, frame=FR)
    B = bs.basis(m, D, CFG)
    assert [v["name"] for v in B.vars] == ["A1_A"]
    doc = bgr.guard_selection(m, D, B, CFG, only=["A1_A"])
    assert [e["var"] for e in doc["entries"]] == ["A1_A"] and doc["combos"] == []     # 단일 점검만(조합 상대 없음)
    assert doc["entries"][0]["state"] in ("ok", "limited", "blocked")
