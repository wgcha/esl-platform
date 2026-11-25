"""V-0247-DM-4·6·12·13·22·27·30(esl 부분)·DM-C1-3·5: floor_fixed 코어 — elems 조합(§1.2.2), θ(§1.3), range guard 후보
DF·W1·ds 키(§2.2), 침범·DS_HOLD_PINCH(§2.4), 대칭 W1 거울(§4.4), one_side 비용, 평행 채널 압축, paicad DS_ENGINE_NATIVE."""
import math
import os
import tempfile
import time

import numpy as np
import pytest
import synth_bead as sb
import synth_guard as sg
from _bg_util import CFG, esl_mesh

from esl.doe import DEFAULTS
from esl.doe import bead_graph as bgr
from esl.doe import bead_select as bs
from esl.doe import paicad_io as pio
from esl.morph import section as sec

RULES = dict(DEFAULTS["depth_section_rules"])
FF = {"depth_section": "floor_fixed", "section_rules": RULES}


# ---------------------------------------------------------------- V-0247-DM-4 elems 조합
@pytest.fixture(scope="module")
def SB():
    g = sb.generate()
    norm = bs.normalize_input(sb.selection(g), CFG)
    return g, norm


@pytest.mark.parametrize("dD", [2.0, -2.0])
def test_elems_floor_fixed_v4(SB, dD):
    g, norm = SB
    X0 = g["mesh"]["x0"]
    D = bs.derive_obj(g["mesh"], norm, CFG, fixed_node_ids=g["fixed_ids"], **FF)
    B = bs.basis(g["mesh"], D, CFG)
    b2 = D.bead("b2")
    assert b2.depth_kind == "DF" and b2.ds_section["applied"] is True
    x = bs.morph(X0, B, {"B2_D1": 6.0 + dD})
    du = x - X0
    fl = b2.tiers[0]["nodes"]
    assert np.abs(du[fl, :2]).max() <= 1e-9 and np.allclose(du[fl, 2], -dD, atol=1e-9)      # 깊이면 평면 0
    c = np.array([560.0, 345.0])
    bn = b2.boundary_nodes
    dr = np.linalg.norm(x[bn, :2] - c, axis=1) - np.linalg.norm(X0[bn, :2] - c, axis=1)
    cot = 1.0 / math.tan(math.radians(60.0))
    h = 5.0
    assert np.abs(dr - dD * cot).max() <= 0.02 * h                                              # 경계 cotθ·ΔD
    # 사면 각 ±1°: 사면 요소(정답 표지 b2s) 법선 기울기 — 변형 전 각 그대로(중앙값)
    ix0, ix1 = D.index, bs.mesh_index({**g["mesh"], "x0": x})
    pick = np.flatnonzero(g["label"] == "b2s")
    a0 = np.degrees(np.arccos(np.abs(ix0.normal[pick, 2])))
    a1 = np.degrees(np.arccos(np.abs(ix1.normal[pick, 2])))
    assert pick.size >= 8 and abs(float(np.median(a1)) - float(np.median(a0))) <= 1.0
    rows = {r["name"]: r for r in bs.params_table(D, CFG)}
    assert rows["B2_D1"]["section"]["applied"] is True and "section" in rows["B1_D1"]
    # 2단 경로형 = DS_FALLBACK SELECT_MULTI_TIER, 기저 바이트 = entry_fixed
    b1 = D.bead("b1")
    assert {w["reason"] for w in b1.warnings if w["code"] == "DS_FALLBACK"} == {"SELECT_MULTI_TIER"}
    D0 = bs.derive_obj(g["mesh"], norm, CFG, fixed_node_ids=g["fixed_ids"])
    B0 = bs.basis(g["mesh"], D0, CFG)
    v0 = {v["name"]: v for v in B0.vars}
    for v in B.vars:
        if v["bead"] == "b1":
            assert np.array_equal(v["idx"], v0[v["name"]]["idx"]) and np.array_equal(v["vec"], v0[v["name"]]["vec"])
    assert "section" not in {k for r in bs.params_table(D0, CFG) for k in r}                     # entry_fixed 행 불변
    # 그림: 조합 기저 평면 성분(ds_dD) — floor_fixed 비드만
    Ds = bs.derive_obj(g["mesh"], norm, CFG, fixed_node_ids=g["fixed_ids"], **FF)
    assert "ds_dD" in (Ds.bead("b2").section or {}) and "ds_dD" not in (Ds.bead("b1").section or {})


def test_elems_theta_v6(SB):
    """θ < theta_min → DS_FALLBACK THETA_UNMEASURED, 퍼짐 > theta_spread → DS_THETA_SPREAD(elems 만)."""
    g, norm = SB
    D = bs.derive_obj(g["mesh"], norm, CFG, fixed_node_ids=g["fixed_ids"], depth_section="floor_fixed",
                      section_rules={**RULES, "theta_min_deg": 70.0})
    b2 = D.bead("b2")
    assert b2.depth_kind == "D" and b2.ds_section["reason"] == "THETA_UNMEASURED"
    assert any(w["code"] == "DS_FALLBACK" and w["reason"] == "THETA_UNMEASURED" for w in b2.warnings)
    D = bs.derive_obj(g["mesh"], norm, CFG, fixed_node_ids=g["fixed_ids"], depth_section="floor_fixed",
                      section_rules={**RULES, "theta_spread_deg": 0.0})
    assert any(w["code"] == "DS_THETA_SPREAD" for w in D.bead("b2").warnings)
    D = bs.derive_obj(g["mesh"], norm, CFG, fixed_node_ids=g["fixed_ids"], **FF)
    assert not any(w["code"] == "DS_THETA_SPREAD" for w in D.bead("b2").warnings)


def test_elems_open_boundary_reason():
    g = sb.generate(open_end=True)
    norm = bs.normalize_input(sb.selection(g, b1_tiers=(1,), b2=False), CFG)
    D = bs.derive_obj(g["mesh"], norm, CFG, fixed_node_ids=g["fixed_ids"], **FF)
    b1 = D.bead("b1")
    assert b1.ds_section["reason"] == "W_OPEN_BOUNDARY" and b1.w_reason == "W_OPEN_BOUNDARY"
    D0 = bs.derive_obj(g["mesh"], norm, CFG, fixed_node_ids=g["fixed_ids"])
    assert bgr.w_reason_of(D0, D0.bead("b1")) == "W_OPEN_BOUNDARY"                              # 옛 스터디 응답 계산


# ---------------------------------------------------------------- 그래프 합성(평행 채널 · 한쪽 입구)
def _prep(c):
    mesh = esl_mesh({"x0": c["nodes"], "conn": c["conn"], "fixed": c["fixed"]})
    d = tempfile.mkdtemp(prefix="ds_c1_")
    assert bgr.prep_graph(mesh, c["fixed"] + 1, CFG, d)["ok"]
    g, lab = bgr.load_graph(d)
    return mesh, g, lab, tuple((c["fixed"] + 1).tolist())


@pytest.fixture(scope="module")
def PAR():
    from beadgraph.testing import synth_oneside as so
    return _prep(so.parallel(gap=20.0))


@pytest.fixture(scope="module")
def ONEB():
    from beadgraph.testing import synth_oneside as so
    return _prep(so.oneside("b"))


def _entries(doc):
    return {e["var"] or str(e["key"]["segs"]) + e["key"]["kind"]: e for e in doc["entries"]}


def test_range_guard_floor_fixed_v12_v30(PAR):
    """V-0247-DM-12·30: floor_fixed 후보 = DF(+ds 키), 머리 cfg_sha 다름, entry_fixed 표 바이트 불변(키 안 넘김 = 같은 표),
    평행 채널 동시 +ΔD = SELECT_BLEND_CLIPPED·같은 비드 D·W 조합 묶음, usable 상한 축소는 표에 표시(막지 않음)."""
    import json
    mesh, g, lab, fx = PAR
    RU = sg.rules()
    t_old = bgr.range_guard_table(mesh, g, lab, fx, CFG, RU)
    t_ent = bgr.range_guard_table(mesh, g, lab, fx, CFG, RU)
    t_ff = bgr.range_guard_table(mesh, g, lab, fx, CFG, RU, **FF)
    dump = lambda d: json.dumps(d, sort_keys=True)  # noqa: E731
    assert dump(t_old) == dump(t_ent)
    assert t_ff["cfg_sha256"] != t_old["cfg_sha256"]
    assert all(e["key"].get("ds") == "floor_fixed" for e in t_ff["entries"])
    assert not any("ds" in e["key"] for e in t_old["entries"])
    dd = [e for e in t_ff["entries"] if e["key"]["kind"] == "D"]
    assert len(dd) >= 2
    # derive 가 floor_fixed 표를 적용(키 일치), entry_fixed 표는 floor_fixed derive 에 적용 안 됨(unchecked)
    sel, _s, _w = bgr.auto_seed(g, lab, CFG)
    norm, _ = bgr.normalize_v2(sel, g, CFG, labels=lab, mesh=mesh, shape_rules=RU)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx, range_guard=t_ff, shape_rules=RU, **FF)
    assert all(b.guard["D"]["state"] != "unchecked" for b in D.beads if b.src == "graph")
    D2 = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx, range_guard=t_old, shape_rules=RU, **FF)
    assert all(b.guard["D"]["state"] == "unchecked" for b in D2.beads if b.src == "graph")
    # 평행 채널 압축: 동시 +ΔD — 블렌딩 자름 경고, 조합 점검 묶음(이웃 비드 영향 요소 공유)
    B = bgr.basis_v2(mesh, D, CFG)
    assert any(w.get("code") == "SELECT_BLEND_CLIPPED" for b in D.beads for w in b.warnings)
    assert B.vars
    print(f"\n[V-0247-DM-30] usable D = {[e['usable'] for e in dd]} from {[e['from'] for e in dd]}; "
          f"combos {[c.get('scale') for c in t_ff['combos']]}")


def test_range_guard_w1_candidate_v12(ONEB):
    mesh, g, lab, fx = ONEB
    RU = sg.rules()
    t = bgr.range_guard_table(mesh, g, lab, fx, CFG, RU, **FF)
    kinds = {e["key"]["kind"] for e in t["entries"]}
    assert "W1" in kinds and "D" in kinds
    t0 = bgr.range_guard_table(mesh, g, lab, fx, CFG, RU)
    assert "W1" not in {e["key"]["kind"] for e in t0["entries"]}
    wc = bgr.w_clamp_table(mesh, g, lab, fx, CFG, **FF)
    assert wc["cfg_sha256"] != bgr.w_clamp_table(mesh, g, lab, fx, CFG)["cfg_sha256"]


def _sel(g, ids):
    return {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": g["rules"], "edits": {}},
            "beads": [{"id": f"b{i + 1}", "name": f"B{i + 1}", "src": "graph",
                       "segs": [{"anchor": g["segments"][s]["anchor"]}]} for i, s in enumerate(ids)]}


def test_intrusion_hold_pinch_v13(ONEB):
    """V-0247-DM-13: DF 단독 BG_OUTSIDE_MOVED 없음·고정 노드 이동 0(hold 1), 입구 근처 체결 노드 → DS_HOLD_PINCH."""
    mesh, g, lab, fx = ONEB
    sid = [s["id"] for s in g["segments"] if s["type"] != "base"]
    norm, _ = bgr.normalize_v2(_sel(g, sid), g, CFG, labels=lab, mesh=mesh)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx, **FF)
    B = bgr.basis_v2(mesh, D, CFG)
    for v in B.vars:
        assert not set(np.flatnonzero(D.fixed_mask)) & set(v["idx"].tolist())
    assert not any(w.get("code") == "BG_OUTSIDE_MOVED" for b in D.beads for w in b.warnings)
    # 열린 쪽 입구 노드 하나를 체결로 → 그 둘레 입구 노드 ψ < 1
    from beadgraph.zones import Mesh, bead_zones
    M = Mesh(g, lab, mesh["x0"], bgr._conn(mesh))
    b0 = next(b for b in D.beads if b.depth_kind == "DF")
    E = np.flatnonzero(bead_zones(M, b0.seg_ids, b0.zone_ids, "D")["E"])
    pick = int(E[E.size // 2])
    fx2 = tuple(sorted(set(fx) | {pick + 1}))
    D2 = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx2, **FF)
    bgr.basis_v2(mesh, D2, CFG)
    hp = [w for b in D2.beads for w in b.warnings if w.get("code") == "DS_HOLD_PINCH"]
    assert hp and all(w["n"] > 0 for w in hp)


def test_tie_mirror_unit_v22():
    """V-0247-DM-22·DM-C1-5: 거울 W1 쌍 = 통과, 같은 방향(거울 아님) = 실패, 도심 거리 < h = 판정 불가(실패)."""
    a = ([0.0, -50.0], [0.0, -1.0])
    b = ([0.0, 50.0], [0.0, 1.0])                       # y = 0 대칭면 거울
    assert sec.tie_mirror_ok([a, b], h=3.0)
    assert not sec.tie_mirror_ok([a, ([0.0, 50.0], [0.0, -1.0])], h=3.0)
    assert not sec.tie_mirror_ok([a, ([0.0, -49.0], [0.0, 1.0])], h=3.0)
    assert not sec.tie_mirror_ok([a, ([1.0, -50.0], [0.0, 1.0])], h=3.0)
    c, v = sec.open_side_geo([([[0.0, 0.0], [10.0, 0.0]], 1)])
    assert c == [5.0, 0.0] and v == [0.0, 1.0] and sec.open_side_deg(v) == 90.0
    assert sec.open_side_geo([([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], 1)])[1] is None       # 고리 = 방향 없음


@pytest.fixture(scope="module")
def ONEA():
    from beadgraph.testing import synth_oneside as so
    return _prep(so.oneside("a"))


def _ring_sides(g):
    """고리 띠 4 변(골격 도심) → {top, bottom, left, right} 세그먼트 id."""
    out = {}
    for s in g["segments"]:
        sk = np.asarray(s.get("skeleton") or [], float).reshape(-1, 2)
        if s["type"] == "base" or sk.shape[0] < 2:
            continue
        c = sk.mean(axis=0)
        horiz = np.ptp(sk[:, 0]) >= np.ptp(sk[:, 1])
        out.setdefault("h" if horiz else "v", []).append((float(c[1] if horiz else c[0]), int(s["id"])))
    h, v = sorted(out["h"]), sorted(out["v"])
    return {"bottom": h[0][1], "top": h[-1][1], "left": v[0][1], "right": v[-1][1]}


def test_tie_w1_mirror_v22(ONEA, ONEB):
    """V-0247-DM-22: 거울 W1 비드 2개(고리 위·아래 변 — 열린 쪽 = 바깥) → 묶음 W 1개(구성원 합), W 종류 다름(W1 + 양쪽 없음
    한쪽은 측정 거울 아님) → 422 없음·W 없음·W_TIE_MIXED·D 묶음 유지."""
    mesh, g, lab, fx = ONEA
    rs = _ring_sides(g)
    sel = _sel(g, [rs["bottom"], rs["top"]])
    sel["ties"] = [["b1", "b2"]]
    norm, _ = bgr.normalize_v2(sel, g, CFG, labels=lab, mesh=mesh)
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx, **FF)
    by = {b.id: b for b in D.beads}
    assert by["b1"].w_side == by["b2"].w_side == "one" and by["b1"].w_reason is None
    rows = {r["name"]: r for r in bgr.params_rows_v2(D, CFG)}
    assert rows["B1_W"]["group_members"] == ["B1_W", "B2_W"] and "B2_W" not in rows
    B = bgr.basis_v2(mesh, D, CFG)
    bv = {v["name"]: v for v in B.vars}
    gv = {v["name"]: v for v in D.graph_basis}
    n = mesh["x0"].shape[0]
    full = np.zeros((n, 3))
    for m in ("B1_W", "B2_W"):
        full[gv[m]["idx"]] += gv[m]["vec"]
    tot = np.zeros((n, 3))
    tot[bv["B1_W"]["idx"]] = bv["B1_W"]["vec"]
    assert np.abs(tot - full).max() <= 1e-12
    # 거울 아님(같은 방향으로 돌린 대표 방향) → W_TIE_MIXED, D 묶음 유지
    by["b2"].open_v = list(by["b1"].open_v)
    for b in D.beads:
        b.vars = sorted(set(b.vars) | {"W"})
    bgr._tie_mixed(D, bgr.select_cfg(CFG))
    assert all("W" not in by[x].vars and by[x].w_reason == "W_TIE_MIXED" for x in ("b1", "b2"))
    assert any(r["name"] == "B1_D" and r["group_members"] == ["B1_D", "B2_D"] for r in bgr.params_rows_v2(D, CFG))


def test_one_side_edge_forced_mask_v18c():
    """DM-C1-3: §8-18(c) W_ONE_SIDE_EDGE — 합성 판 외곽 채널은 분류기가 area 로 둠 → 강제 외곽 마스크로 EDGE 판정 + 사유 순서."""
    from beadgraph.oneside import measure
    from beadgraph.testing import synth_oneside as so
    from beadgraph.zones import Mesh
    import beadgraph as bg
    c = so.oneside("d")
    gg, ll = bg.classify(c["nodes"], c["conn"], c["fixed"])
    M = Mesh(gg, ll, c["nodes"], c["conn"])
    assert measure(M, [1], min_nodes=3, edge_nodes=np.ones(M.n, bool))[1]["reason"] == "EDGE"
    assert sec.w_reason({"src": "graph", "floor_fixed": True, "s2": 0, "s1": 0, "s1_edge": True}) == "W_ONE_SIDE_EDGE"


def test_one_side_cost_h6_v27():
    """V-0247-DM-27: H6 전 세그먼트 one_side ≤ 0.3 s(최선 3회)."""
    from _bg_util import prepared
    mesh, g, lab, _fx, _d = prepared("h6")
    best = 1e9
    for _ in range(3):
        t0 = time.perf_counter()
        osd = bgr._one_side_all(mesh, g, lab, RULES)
        best = min(best, time.perf_counter() - t0)
    print(f"\n[V-0247-DM-27] H6 one_side {len(osd)} segs {best:.3f}s")
    assert osd and best <= 0.3


def test_derive_v2_w_reason_and_ds(ONEB):
    """derive_v2(API 진입): depth_section 통과 + beads[].w_reason{code, text}(옛 스터디도)."""
    mesh, g, lab, fx = ONEB
    sid = [s["id"] for s in g["segments"] if s["type"] != "base"]
    norm, _ = bgr.normalize_v2(_sel(g, sid), g, CFG, labels=lab, mesh=mesh)
    old = bgr.derive_v2(mesh, norm, CFG, g, lab, fixed_scan=fx)
    assert all(r["w_reason"]["code"] == "W_ENTRY_ONE_SIDE" and r["w_reason"]["text"] for r in old["beads"])
    new = bgr.derive_v2(mesh, norm, CFG, g, lab, fixed_scan=fx, **FF)
    assert any(r.get("w_side") == "one" for r in new["params"])
    assert any(r.get("section", {}).get("mode") == "floor_fixed" for r in new["params"])


def test_paicad_engine_native_v10():
    assert pio.section_info(None) == [] and pio.section_info("entry_fixed") == []
    info = pio.section_info("floor_fixed")
    assert [w["code"] for w in info] == ["DS_ENGINE_NATIVE"] and info[0]["message"] != "DS_ENGINE_NATIVE"
    doc = {"beads": [{"id": "b1"}, {"id": "b2"}],
           "features": [{"name": "B1_D", "type": "BEAD_DEPTH", "bead": "b1", "nominal": 5.0, "range": [4, 6]},
                        {"name": "B2_D", "type": "BEAD_DEPTH", "bead": "b2", "nominal": 5.0, "range": [4, 6]},
                        {"name": "B2_W", "type": "BEAD_WIDTH", "bead": "b2", "nominal": 20.0, "range": [18, 22],
                         "use_default": False}]}
    assert pio.w_reasons(doc) == {"b1": "W_PAICAD_NONE", "b2": "W_PAICAD_DEFAULT_OFF"}
