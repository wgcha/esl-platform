"""V-BS-5·6·9: 비드 직접 선택 derive(계약 esl_bead_select.md §4·§5.2·§5.7) — 사면·경계 자동, 경고(빠진 단·새는 사면·
열린 경계), ±1줄 편집, 공칭 치수·단면, 선택 검증·구간 정규화."""
import numpy as np
import pytest

import synth_bead as sb
from esl.doe import bead_select as bs
from esl.doe import settings
from esl.errors import EslError

CFG = settings({"bead_doe": {"enabled": True}})


@pytest.fixture(scope="module")
def G():
    g = sb.generate()
    D = bs.derive_obj(g["mesh"], bs.normalize_input(sb.selection(g), CFG), CFG, fixed_node_ids=g["fixed_ids"])
    return g, D


def _codes(bd):
    return {w["code"] for w in bd.warnings}


# ---------------------------------------------------------------- V-BS-5 사면·경계 자동
def test_slope_and_boundary_auto(G):
    g, D = G
    lab = g["label"]
    ix = D.index
    for bid, sl in (("b1", "b1s"), ("b2", "b2s")):
        bd = D.bead(bid)
        assert np.array_equal(bd.slope_mask, lab == sl), bid               # 사면 = 정답(요소 집합 동일)
        assert not bd.edited and bd.sense == "concave"
        assert len(bd.loops) == 1 and bd.loops[0]["closed"]
        nodes = bd.loops[0]["nodes"]
        assert ix.node_id[nodes[0]] == ix.node_id[nodes].min()             # 시작 = 최소 노드 ID
        # 순서: 이웃 노드는 경계 모서리를 공유
        keys = set(map(tuple, np.sort(ix.edge_nodes, axis=1).tolist()))
        pairs = np.sort(np.column_stack([nodes, np.roll(nodes, -1)]), axis=1)
        assert all(tuple(p) in keys for p in pairs.tolist())
        # 방향: n̂_b 기준 반시계(부호 있는 면적 > 0)
        P = ix.X[nodes] - bd.p_b
        u, v = P @ bd.e1, P @ bd.e2
        assert 0.5 * np.sum(u * np.roll(v, -1) - np.roll(u, -1) * v) > 0
        # 경계 노드 = 상판 높이(z = 0), 비드 밖 요소와 공유
        assert np.allclose(ix.X[bd.boundary_nodes, 2], 0.0)
        assert set(nodes.tolist()) == set(bd.boundary_nodes.tolist())
    s = D.summary()
    b1 = s["beads"][0]
    assert b1["slope"]["n_elems"] == int((lab == "b1s").sum()) == b1["slope"]["suggested_n"]
    assert b1["boundary"]["loops"][0]["closed"] and b1["tiers"][1]["D_nom"] == pytest.approx(14.0)
    assert bs.elems_of(ix, b1["slope"]["elems"]).sum() == b1["slope"]["n_elems"]
    assert set(D.slope_suggested()) == {"b1", "b2"}


def test_tier_missing_leak_open(G):
    g, _ = G
    m = g["mesh"]
    D1 = bs.derive_obj(m, bs.normalize_input(sb.selection(g, b1_tiers=(1,), b2=False), CFG), CFG)
    w = next(x for x in D1.bead("b1").warnings if x["code"] == "SELECT_TIER_MISSING")
    assert w["z_mm"] == pytest.approx(14.0, abs=0.05) and w["n_elems"] > 0
    gw = sb.generate(wavy=True)
    Dw = bs.derive_obj(gw["mesh"], bs.normalize_input(sb.selection(gw, b2=False), CFG), CFG)
    assert "SELECT_SLOPE_LEAK" in _codes(Dw.bead("b1"))
    go = sb.generate(open_end=True)
    Do = bs.derive_obj(go["mesh"], bs.normalize_input(sb.selection(go, b2=False), CFG), CFG)
    bo = Do.bead("b1")
    assert "SELECT_OPEN_BOUNDARY" in _codes(bo) and not bo.w_enabled and not bo.loops[0]["closed"]
    names = [r["name"] for r in bs.params_table(Do, CFG)]
    assert names == ["B1_D1", "B1_D2"]                                    # W 비활성, D 는 가능
    Bo = bs.basis(go["mesh"], Do, CFG)
    assert [v["name"] for v in Bo.vars] == names
    # 비드가 둘로 나뉜 선택 → SELECT_DISCONNECTED(허용)
    sel = sb.selection(g, b2=False)
    sel["beads"][0]["tiers"].append({"k": 3, "floor": sb.elemset(m, g["label"] == "b2t1")})
    Dd = bs.derive_obj(m, bs.normalize_input(sel, CFG), CFG)
    assert any(x["code"] == "SELECT_DISCONNECTED" and x["parts"] == 2 for x in Dd.bead("b1").warnings)


def test_plus_minus_one_line(G):
    g, D = G
    m = g["mesh"]
    ix = D.index
    b1 = D.bead("b1")
    plus = bs.edit_line(ix, b1.bead_mask, "+")
    assert plus.any() and not (plus & b1.bead_mask).any()
    assert np.all(g["label"][plus] == "plate")
    sel = sb.selection(g, b2=False)
    sel["beads"][0]["slope"] = {"mode": "edited", "add": sb.elemset(m, plus)}
    Dp = bs.derive_obj(m, bs.normalize_input(sel, CFG), CFG)
    bp = Dp.bead("b1")
    assert bp.edited and bp.slope_mask.sum() == b1.slope_mask.sum() + plus.sum()
    assert np.array_equal(bp.slope_auto, b1.slope_auto)                   # 자동 결과 재계산 + 편집
    assert bp.loops[0]["closed"] and bp.W_nom > b1.W_nom + 5.0            # 경계가 바깥으로 1줄
    minus = bs.edit_line(ix, b1.bead_mask, "-") & ~b1.floor_mask
    assert np.all(g["label"][minus] == "b1s")
    sel["beads"][0]["slope"] = {"mode": "edited", "remove": sb.elemset(m, minus)}
    Dm = bs.derive_obj(m, bs.normalize_input(sel, CFG), CFG)
    bm = Dm.bead("b1")
    assert bm.slope_mask.sum() == b1.slope_mask.sum() - minus.sum() and bm.W_nom < b1.W_nom - 2.0
    # 제외 층: 사면 자동에서 빠짐
    sel = sb.selection(g, b2=False)
    sel["exclude"] = sb.elemset(m, minus)
    De = bs.derive_obj(m, bs.normalize_input(sel, CFG), CFG)
    assert not (De.bead("b1").slope_mask & minus).any()


# ---------------------------------------------------------------- V-BS-6 공칭 치수·단면
def test_nominal_dimensions_and_section(G):
    g, D = G
    h = g["h"]
    b1, b2 = D.bead("b1"), D.bead("b2")
    assert b1.tiers[0]["D_nom"] == pytest.approx(22.0, abs=0.05)
    assert b1.tiers[1]["D_nom"] == pytest.approx(14.0, abs=0.05)
    assert b2.tiers[0]["D_nom"] == pytest.approx(6.0, abs=0.05)
    tw = g["truth"]["b1"]["W_cols"]
    assert abs(b1.W_nom - np.median(tw)) <= h / 2
    assert abs(b1.W_min - np.percentile(tw, 5)) <= h / 2 and abs(b1.W_max - np.percentile(tw, 95)) <= h / 2
    assert abs(b2.W_nom - 40.0) <= h / 2
    assert b1.tiers[0]["planarity"] == pytest.approx(0.0, abs=1e-9)
    assert np.allclose(b1.tiers[0]["normal"], [0.0, 0.0, -1.0])
    # 기본 범위: 깊이 ±30 %, 단 2 하한 > 상판 + 1, 폭 ±20 %(f = 1 바닥 최소 폭)
    rd = b1.range_default
    assert rd["D"]["1"] == [pytest.approx(15.4), pytest.approx(28.6)] and rd["D"]["2"][0] == pytest.approx(9.8)
    assert rd["W"][0] == pytest.approx(b1.W_nom * 0.8, abs=1e-3) and rd["W"][1] == pytest.approx(b1.W_nom * 1.2,
                                                                                                 abs=1e-3)
    # 단면: 해석적 단면(상판 0 · 바닥 22 · 60° 사면) ± 0.1 mm, 미분 = 기저
    sec = b1.section
    s, z = np.array(sec["s"]), np.array(sec["z"])
    W = b1.W_nom
    j0 = int(np.flatnonzero(D.index.node_id == sec["at_node_id"])[0])
    Dsec = g["depth_fn"](float(D.index.X[j0, 0]))                            # 단면 위치의 정답 깊이(22 또는 14)
    tier = "1" if Dsec == 22.0 else "2"
    run = Dsec / np.tan(np.radians(60))
    assert np.all(np.abs(z[s < -0.5]) < 0.1)                                 # 상판
    fl = (s > run + 1.0) & (s < W - run - 1.0)
    assert fl.sum() >= 3 and np.allclose(z[fl], Dsec, atol=0.1)               # 바닥
    sl = (s > 0.5) & (s < run - 0.5)
    if sl.any():
        assert np.allclose(z[sl], s[sl] * np.tan(np.radians(60)), atol=0.6)   # 사면(격자 각도 근사)
    dz = np.array(sec["dz_dD"][tier])
    assert np.allclose(dz[fl], 1.0, atol=1e-6) and np.allclose(dz[s < -0.5], 0.0)
    assert np.allclose(np.array(sec["ds_dW"])[s < -0.5] <= 0.5 + 1e-9, True)
    B = bs.basis(g["mesh"], D, CFG)
    bw = B.by_name()["B1_W"]
    full = np.zeros((D.index.n_nodes, 3))
    full[bw["idx"]] = bw["vec"]
    j = int(np.flatnonzero(D.index.node_id == sec["at_node_id"])[0])
    k = int(np.flatnonzero(b1.wb_nodes == j)[0])
    assert np.allclose(full[j], 0.5 * b1.wb_e[k])                            # 단면 기준 경계 노드 = ½ê
    # summary JSON 직렬화 가능 + plan
    import json
    from esl.library import normalize as nz
    frame = nz.frame(g["mesh"]["x0"], None, g["mesh"]["conn"], g["mesh"]["elem_type"])
    js = json.dumps(D.summary(frame, rev=3), allow_nan=False)
    assert '"rev": 3' in js
    pd = bs.plan_data(g["mesh"], D.norm, D, CFG, frame=frame)
    assert len(pd["beads"]) == 2 and len(pd["beads"][0]["ring_ab"]) == 1 and pd["beads"][0]["tiers"][1]["k"] == 2
    assert len(pd["fixed"]) == g["fixed_ids"].size and len(pd["nodes_ab"]) == D.index.n_nodes
    db = D.summary(with_figures=False)
    assert "section" not in db["beads"][0] and "plan" not in db["beads"][0]


# ---------------------------------------------------------------- V-BS-9 선택 검증
def _err(sel, cfg=CFG, mesh=None):
    with pytest.raises(EslError) as ei:
        n = bs.normalize_input(sel, cfg)
        if mesh is not None:
            bs.derive_obj(mesh, n, cfg)
    return ei.value


def test_selection_validation(G):
    g, D = G
    m = g["mesh"]
    base = sb.selection(g)
    s = sb.selection(g)
    s["beads"][1]["tiers"][0]["floor"] = s["beads"][0]["tiers"][0]["floor"]
    e = _err(s)
    assert e.code == "SELECT_OVERLAP" and e.extra["elems_n"] > 0
    s = sb.selection(g)
    s["beads"][0]["tiers"][0]["floor"]["q"].append([10 ** 8, 10 ** 8])
    e = _err(s, mesh=m)
    assert e.code == "SELECT_ELEM_UNKNOWN" and e.extra == {"n": 1, "first": 10 ** 8}
    s = sb.selection(g)
    s["beads"][0]["tiers"][1]["floor"] = {"q": [], "t": []}
    assert _err(s).code == "SELECT_EMPTY_TIER"
    s = sb.selection(g)
    s["beads"][0]["tiers"][1]["k"] = 3
    assert _err(s).code == "SELECT_TIERS_GAP"
    for links in ([[1, 3]], [[1]], [[1, 2], [2, 1]]):
        s = sb.selection(g, links=links)
        assert _err(s).code == "SELECT_LINK_INVALID", links
    for bid in ("b0", "B1", "b21", "x"):
        s = sb.selection(g)
        s["beads"][0]["id"] = bid
        assert _err(s).code == "SELECT_BEAD_ID_INVALID", bid
    s = sb.selection(g)
    s["beads"][1]["id"] = "b1"
    assert _err(s).code == "SELECT_BEAD_ID_INVALID"
    for name in ("", "x" * 33, "a\nb"):
        s = sb.selection(g)
        s["beads"][0]["name"] = name
        assert _err(s).code == "SELECT_NAME_INVALID"
    small = settings({"bead_doe": {"enabled": True, "select": {"max_selection_kb": 1}}})
    s = sb.selection(g)
    s["beads"][0]["tiers"][0]["floor"]["q"] = [[k, k] for k in range(1, 4000, 2)]
    assert _err(s, small).code == "SELECT_TOO_LARGE"
    # 구간 정규화: 인접·겹침 병합, 기본값 채움
    n = bs.normalize_input({"beads": [{"id": "b3", "tiers": [{"k": 1, "floor": {"q": [[7, 9], [1, 3], [4, 5], [8, 12]]}}]}]},
                     CFG)
    b = n["beads"][0]
    assert b["tiers"][0]["floor"] == {"q": [[1, 5], [7, 12]], "t": []}
    assert b["name"] == "B3" and b["blend_mm"] == "auto" and b["floor_follow"] == 1 and b["links"] == []
    assert n["feature_angle_deg"] == 15.0 and n["fixed_user"] == {"q": [], "t": []}
    assert bs.ranges_from_ids([5, 1, 2, 3, 9]) == [[1, 3], [5, 5], [9, 9]]
    assert bs.ids_from_ranges([[1, 3], [5, 5]]).tolist() == [1, 2, 3, 5]
    # 3각 ID 공간 분리(t)
    tri = np.asarray(m["elem_type"]) == 3
    es = sb.elemset(m, tri)
    assert es["t"] and not es["q"] and bs.elems_of(D.index, es).sum() == tri.sum()
    assert bs.normalize_input(base, CFG) == bs.normalize_input(bs.normalize_input(base, CFG), CFG)     # 멱등


# ---------------------------------------------------------------- 백엔드(S2) API 시그니처
def test_backend_api(G):
    import json
    g, _ = G
    m = g["mesh"]
    from esl.library import normalize as nz
    frame = nz.frame(g["mesh"]["x0"], None, g["mesh"]["conn"], g["mesh"]["elem_type"])
    sel = sb.selection(g)
    sel["feature_angle_deg"] = None
    sel["beads"][0]["name"] = None
    sel["beads"][0]["floor_follow"] = None
    norm, sha = bs.normalize(sel, CFG, mesh=m)
    assert norm["feature_angle_deg"] == 15.0 and norm["beads"][0]["name"] == "B1" and norm["beads"][0]["floor_follow"] == 1
    assert sha == bs.selection_sha256(norm) and bs.normalize(norm, CFG) == (norm, sha)
    bad = sb.selection(g)
    bad["exclude"] = {"q": [[10 ** 7, 10 ** 7 + 2]]}
    with pytest.raises(EslError) as ei:
        bs.normalize(bad, CFG, mesh=m)
    assert ei.value.code == "SELECT_ELEM_UNKNOWN" and ei.value.extra == {"n": 3, "first": 10 ** 7}
    fx = np.asarray(g["fixed_ids"], dtype=np.int64)
    d = bs.derive(m, norm, CFG, frame=frame, fixed_scan=fx)
    assert set(d) == {"beads", "fixed", "warnings", "slope_suggested", "fixed_ab"}
    assert d["fixed"]["source"] == "scan" and len(d["fixed_ab"]) == fx.size
    b1 = d["beads"][0]
    assert {"section", "plan", "range_default", "tiers", "slope", "boundary", "W_nom"} <= set(b1)
    json.dumps(d, allow_nan=False)
    d1 = bs.derive(m, norm, CFG, frame=frame, fixed_scan=fx, bead="b2")
    assert [b["id"] for b in d1["beads"]] == ["b2"] and d1["beads"][0]["W_nom"] == d["beads"][1]["W_nom"]
    pd = bs.plan_data(m, norm, d, CFG, frame=frame)
    assert {"frame", "outline", "holes", "elems", "beads", "fixed", "nodes_ab", "warnings"} <= set(pd)
    assert pd["beads"][0]["ring_ab"] == b1["plan"]["ring_ab"] and len(pd["fixed"]) == fx.size
    json.dumps(pd, allow_nan=False)


def test_width_end_ratio_from_settings(G):
    """§5.7 끝단 반직선 제외 배수: 코어 WIDTH_END_RATIO = DEFAULTS(백엔드 BeadDoeSelectWidthCfg.end_ratio 거울) —
    설정 select.width.end_ratio 가 있으면 그 값, 키가 없을 때만 모듈 기본값."""
    import copy

    from esl.doe import DEFAULTS
    g, D = G
    assert bs.WIDTH_END_RATIO == DEFAULTS["select"]["width"]["end_ratio"] == CFG["select"]["width"]["end_ratio"]
    sel = sb.selection(g)
    tight = settings({"bead_doe": {"enabled": True, "select": {"width": {"end_ratio": 1.05}}}})
    Dt = bs.derive_obj(g["mesh"], bs.normalize_input(sel, tight), tight, fixed_node_ids=g["fixed_ids"])
    w0, wt = D.bead("b1").w_j, Dt.bead("b1").w_j
    assert 0 < wt.size < w0.size
    assert wt.max() <= 1.05 * np.median(w0[np.isfinite(w0)]) * 1.2
    nokey = copy.deepcopy(CFG)
    nokey["select"]["width"].pop("end_ratio")
    Dn = bs.derive_obj(g["mesh"], bs.normalize_input(sel, nokey), nokey, fixed_node_ids=g["fixed_ids"])
    assert np.array_equal(Dn.bead("b1").w_j, w0)
