"""v0.16.1 어려운 사례 H1~H4 회귀(esl_select_relax.md SR-D-35~43 — 시험 엔지니어 재현 자료 고정).

합성 = ``synth_hard.case(kind)``(높이장 구조 4각 h 2 mm, 사면 60°): H1 X 교차(얕은 S 15 · 깊은 Dp 25, 교차 바닥 보스, S 바닥 딤플 2),
H2 3단 계단(단마다 딤플, 단1→2 사면에 구멍), H3 근접·합류·플랜지, H4 밀집(보스 6·루버 2) + 비드 벽을 가로지르는 슬롯.
"""
import numpy as np
import pytest

import synth_hard as sh
from esl.doe import bead_select as bs
from esl.doe import mesh_quality as mq
from esl.doe import settings
from esl.errors import EslError

CFG = settings({"bead_doe": {"enabled": True}})
# v0.16.2 AD-D-6 V-SR-28 회귀 예외 목록: 판정(state)·기저 바이트가 같을 때 아래 경고가 더해지는 것은 회귀 실패가 아님
# (AD-D-9·SR-D-39 로 늘어난 경고). 사례: feat, edge_boss:G, 실 사례 1 전체 5(L), edge_boss B1_D1 7.0146, h5, 레일 A 단독.
REGRESS_WARN_EXCEPTIONS_V0162 = ("SELECT_RANGE_COMBO", "SELECT_W_RANGE_LIMIT", "SELECT_BASE_REFIT",
                                 "SELECT_SLOPE_ABOVE_PLATE", "SELECT_QUALITY_WARN", "SELECT_RANGE_INVERTS")


def _derive(g, beads, cfg=CFG, **extra):
    sel = sh.selection(g, beads, **extra)
    return bs.derive_obj(g["mesh"], bs.normalize_input(sel, cfg), cfg, fixed_node_ids=g["fixed_ids"])


def _codes(b):
    return [w["code"] for w in b.warnings]


def _state(g, D, B, vals, cfg=CFG):
    x0 = g["mesh"]["x0"]
    x = bs.morph(x0, B, vals)
    return x, bs.design_state(g["mesh"], x0, x, D.fixed_mask, cfg, checks=bs.design_checks(D, B), values=vals)


def _rigid_err(D, x0, x):
    e = 0.0
    for b in D.beads:
        for i in b.islands:
            if i["interior"].size and i["rim"].size:
                t = (x - x0)[i["rim"]].mean(axis=0)
                e = max(e, float(np.abs((x - x0)[i["interior"]] - t).max()))
    return e


@pytest.fixture(scope="module")
def h1():
    return sh.build(sh.case("H1"))


# ---------------------------------------------------------------- 1 섬 포함(조각 바닥·열린 고리) — SR-D-35
def test_h1_islands_in_every_floor_piece(h1):
    """교차하는 Dp 가 S 바닥을 두 조각으로 가름: 두 조각의 딤플이 모두 섬(전에는 큰 조각만 바깥 다각형 → 14 mm 딤플 TOO_LARGE)."""
    D = _derive(h1, [("S", 1), ("Dp", 1)])
    s, d = D.bead("b1"), D.bead("b2")
    assert len(s.islands) == 2 and "SELECT_ISLAND_TOO_LARGE" not in _codes(s)
    assert all(11.0 < i["size_mm"] < 15.0 for i in s.islands)
    assert len(d.islands) == 1 and d.islands[0]["free_loops"] == 1                   # 교차 보스(버링 구멍)
    B = bs.basis(h1["mesh"], D, CFG)
    nom = B.nominal()
    x0 = h1["mesh"]["x0"]
    x = bs.morph(x0, B, {"B1_D1": nom["B1_D1"] + 2.0, "B2_D1": nom["B2_D1"] + 3.0})
    assert _rigid_err(D, x0, x) < 1e-9


def test_h1_boss_between_floor_pieces():
    """교차 보스가 벽까지 ~1요소(r_top 3.5) — 보스가 Dp 바닥을 두 조각으로 가름: 조각 사이 섬(닿은 조각 합 볼록 껍질 안)으로 흡수,
    D +3.7 은 READY(전에는 사면 보간 → FAILED_MESH 뒤집힘 16)."""
    old = sh.BOSS_R
    sh.BOSS_R = 3.5
    try:
        g = sh.build(sh.case("H1"))
    finally:
        sh.BOSS_R = old
    D = _derive(g, [("S", 1), ("Dp", 1)])
    d = D.bead("b2")
    assert len(d.islands) == 1 and len(d.holes) == 0 and "SELECT_ISLAND_TOO_LARGE" not in _codes(d)
    B = bs.basis(g["mesh"], D, CFG)
    x, st = _state(g, D, B, {"B2_D1": B.nominal()["B2_D1"] + 3.7})
    assert st["state"] == "READY" and _rigid_err(D, g["mesh"]["x0"], x) < 1e-9


def test_h2_tier_islands_with_hole_on_slope():
    """단1→2 사면에 걸친 구멍이 단2 바닥 가장자리를 끊어도 단2 딤플이 섬(조각 경계 = 자유 모서리 포함 → 고리 닫힘)."""
    g = sh.build(sh.case("H2"))
    D = _derive(g, [("T", 3)])
    b = D.bead("b1")
    assert sorted(i["k"] for i in b.islands) == [1, 2, 3] and len(b.holes) == 1
    assert "SELECT_ISLAND_TOO_LARGE" not in _codes(b) and b.w_enabled and not b.open


@pytest.fixture(scope="module")
def h4():
    g = sh.build(sh.case("H4"))
    D = _derive(g, [("G", 1)])
    return g, D, bs.basis(g["mesh"], D, CFG)


def test_h4_slot_is_hole_not_plate_edge(h4):
    """비드 벽을 가로지르는 슬롯(경계 노드에 닿는 구멍)은 판 가장자리가 아님 → OPEN_BOUNDARY 없음, 경계 고리는 슬롯을 건너 닫힘,
    W 켜짐. 보스 4묶음(겹침·맞닿음 포함)·루버 2 = 섬, TOO_LARGE 없음."""
    g, D, B = h4
    b = D.bead("b1")
    assert "SELECT_OPEN_BOUNDARY" not in _codes(b) and not b.open and b.w_enabled
    assert len(b.holes) == 1 and b.loops[0]["closed"] and b.loops[0].get("bridged") == 1
    assert len(b.islands) == 4 and "SELECT_ISLAND_TOO_LARGE" not in _codes(b)
    assert "B1_W" in B.by_name()
    # 슬롯 없는 대조와 W 공칭 같음
    sp = sh.case("H4")
    sp["holes"] = []
    g2 = sh.build(sp)
    b2 = _derive(g2, [("G", 1)]).bead("b1")
    assert b.W_nom == pytest.approx(b2.W_nom, abs=0.01) and len(b2.islands) == 4


def test_h4_depth_moves_features_rigidly(h4):
    """D 를 바꾸면 보스·루버(섬)는 강체 이동(바닥과 같은 변위) — 사면 보간으로 반쯤(보스3 +0.75)·제자리(루버) 남던 결함."""
    g, D, B = h4
    x0 = g["mesh"]["x0"]
    x, st = _state(g, D, B, {"B1_D1": B.nominal()["B1_D1"] + 1.5})
    assert st["code"] != "SELECT_FEATURE_DISTORTED"
    lab = g["label"]
    b = D.bead("b1")
    fl = np.zeros(g["mesh"]["x0"].shape[0], bool)
    fl[D.index.elem_nodes(b.floor_mask)] = True
    for i in b.islands:
        u = (x - x0)[i["interior"]]
        assert np.allclose(u, (x - x0)[i["rim"]].mean(axis=0), atol=1e-9)
        assert float(np.linalg.norm(u, axis=1).min()) == pytest.approx(1.5, abs=0.05)
    assert int(np.sum(np.isin(np.flatnonzero(lab == "isl"), np.concatenate([i["elems"] for i in b.islands])))) > 0


def test_h4_feature_safety_net_small_island_limit():
    """섬 크기 상한을 작게(8 mm) 해 보스·루버가 섬이 못 되면 D 변경 안 = FAILED_MESH(SELECT_FEATURE_DISTORTED) — 경고로 READY 통과 안 함."""
    cfg = settings({"bead_doe": {"enabled": True, "select": {"island": {"max_mm": 8.0}}}})
    g = sh.build(sh.case("H4"))
    D = _derive(g, [("G", 1)], cfg)
    b = D.bead("b1")
    assert "SELECT_ISLAND_TOO_LARGE" in _codes(b) and b.features
    B = bs.basis(g["mesh"], D, cfg)
    _x, st = _state(g, D, B, {"B1_D1": B.nominal()["B1_D1"] + 1.5}, cfg)
    assert st["state"] == "FAILED_MESH" and st["code"] in ("SELECT_FEATURE_DISTORTED", "SELECT_MORPH_INVERTED")
    if st["code"] == "SELECT_FEATURE_DISTORTED":
        w = st["warnings"][0]
        assert w["code"] == "SELECT_FEATURE_DISTORTED" and w["dev_mm"] > 0.1


def test_h4_boss_at_wall_is_caught():
    """벽에서 요소 1개 안 보스(바닥 둘레가 끊겨 벽 성분에 이어짐 — 섬 인식 한계): 윗면이 안쪽 고리로 남아 제자리 → 안전망
    SELECT_FEATURE_DISTORTED(FAILED_MESH). 공칭 안은 READY."""
    sp = sh.case("H4")
    sp.update(holes=[], louvers=[], bosses=[{"c": (200.0, 91.0), "r_top": 2.0, "z_top": -7.0, "hole_r": 0.0}])
    g = sh.build(sp)
    D = _derive(g, [("G", 1)])
    b = D.bead("b1")
    assert any(f.get("stuck") for f in b.features)
    B = bs.basis(g["mesh"], D, CFG)
    _x, st = _state(g, D, B, {"B1_D1": B.nominal()["B1_D1"] + 1.5})
    assert st["state"] == "FAILED_MESH" and st["code"] == "SELECT_FEATURE_DISTORTED"
    _x, st0 = _state(g, D, B, B.nominal())
    assert st0["state"] == "READY"
    # checks 없이(v0.16.1 첫 판 호출) = 검사 없음
    x0 = g["mesh"]["x0"]
    st1 = bs.design_state(g["mesh"], x0, bs.morph(x0, B, {"B1_D1": B.nominal()["B1_D1"] + 1.5}), D.fixed_mask, CFG)
    assert st1["code"] != "SELECT_FEATURE_DISTORTED"


# ---------------------------------------------------------------- 2 교차 비드 하나만 — 기준 평면(SR-D-36)
@pytest.mark.parametrize("name,truth", [("S", 15.0), ("Dp", 25.0)])
def test_h1_single_crossing_bead_depth(h1, name, truth):
    """교차 비드 중 하나만 선택: 기준 평면 = 판 쪽 경계 노드만(다른 비드 벽·바닥 노드 뺌) → D_nom = 참값(전에는 0.21·21.8)."""
    b = _derive(h1, [(name, 1)]).bead("b1")
    assert b.tiers[0]["D_nom"] == pytest.approx(truth, abs=0.2)
    assert "SELECT_BASE_REFIT" in _codes(b) and "SELECT_NONPLANAR_BASE" not in _codes(b)
    w = next(x for x in b.warnings if x["code"] == "SELECT_BASE_REFIT")
    assert w["level"] == "info" and w["n_excluded"] > 0


def test_h1_single_crossing_bead_ambiguous_error(h1):
    """판 쪽 노드로 다시 맞춰도 잔차가 크면(판이 평평하지 않음) derive 오류 SELECT_BASE_AMBIGUOUS(교차 비드 함께 선택 안내)."""
    g = {**h1, "mesh": dict(h1["mesh"])}
    X = np.array(h1["mesh"]["x0"], copy=True)
    plate = np.abs(X[:, 2]) < 1e-9
    X[plate, 2] += 0.6 * np.sin(X[plate, 0] / 7.0) * np.cos(X[plate, 1] / 5.0)
    g["mesh"]["x0"] = X
    cfg = settings({"bead_doe": {"enabled": True, "select": {"plane_rms_mm": 0.2}}})
    with pytest.raises(EslError) as ei:
        _derive(g, [("S", 1)], cfg)
    assert ei.value.code == "SELECT_BASE_AMBIGUOUS" and ei.value.extra["bead"] == "b1"
    assert "함께 선택" in ei.value.message


# ---------------------------------------------------------------- 4 다른 비드 침범(SR-D-38)
def test_h3_cross_bead_move_warn_and_skip():
    """P 의 W 상한이 A 의 경계·바닥을 움직임 → warn = READY + SELECT_CROSS_BEAD_MOVE{n, max_mm}, skip = SKIPPED_COLLISION."""
    g = sh.build(sh.case("H3"))
    beads = [("A", 1), ("B", 1), ("P", 1), ("C", 1)]
    D = _derive(g, beads)
    B = bs.basis(g["mesh"], D, CFG)
    chk = bs.design_checks(D, B)
    assert any(c["var"] == "B3_W" and c["other"] == "b1" for c in chk["cross"])
    v = {"B3_W": 72.0}
    _x, st = _state(g, D, B, v)
    w = next(x for x in st["warnings"] if x["code"] == "SELECT_CROSS_BEAD_MOVE")
    assert st["state"] in ("READY", "FAILED_MESH") and w["n"] > 0 and w["max_mm"] > 1.0 and ["B3_W", "b1"] in w["beads"]
    cfg = settings({"bead_doe": {"enabled": True, "select": {"cross_bead_policy": "skip"}}})
    x0 = g["mesh"]["x0"]
    st2 = bs.design_state(g["mesh"], x0, bs.morph(x0, B, v), D.fixed_mask, cfg, checks=chk, values=v)
    if st["state"] == "READY":
        assert st2["state"] == "SKIPPED_COLLISION" and st2["code"] == "SELECT_CROSS_BEAD_VIOLATION"
    # D 만 바꾼 안 = 침범 검사 대상 아님
    _x, st3 = _state(g, D, B, {"B1_D1": 9.0})
    assert not any(x["code"] == "SELECT_CROSS_BEAD_MOVE" for x in st3["warnings"])
    # 저장·읽기 왕복(derived.npz chk_*)
    back = bs.checks_from_arrays(bs.checks_arrays(chk))
    assert [(c["var"], c["other"]) for c in back["cross"]] == [(c["var"], c["other"]) for c in chk["cross"]]
    assert all(np.array_equal(a["idx"], b["idx"]) and np.array_equal(a["mag"], b["mag"]) for a, b in zip(back["cross"], chk["cross"]))
    assert bs.checks_arrays({}) == {} and bs.checks_from_arrays({}) == {}


# ---------------------------------------------------------------- 5 범위 — 조합 검증·다단/이웃 제약(SR-D-39)
def test_h1_range_combo_and_usable(h1):
    """변수별 usable 끝의 모서리 조합(4 변수 = 16 전부)에 뒤집힘이 있으면 SELECT_RANGE_COMBO{scale, usable} — 그 usable 조합은
    표본 모두 뒤집힘 없음."""
    D = _derive(h1, [("S", 1), ("Dp", 1)])
    B = bs.basis(h1["mesh"], D, CFG)
    ws = bs.range_check(h1["mesh"], D, B, CFG)
    w = next(x for x in ws if x["code"] == "SELECT_RANGE_COMBO")
    assert w in D.warnings and w["corners"] == 16 and w["inverted_n"] > 0 and 0 <= w["scale"] < 1
    x0 = h1["mesh"]["x0"]
    import itertools
    names = w["vars"]
    for bits in itertools.product([0, 1], repeat=len(names)):
        vals = {n: w["usable"][n][k] for n, k in zip(names, bits)}
        st = bs.design_state(h1["mesh"], x0, bs.morph(x0, B, vals), D.fixed_mask, CFG)
        assert st["code"] != "SELECT_MORPH_INVERTED", vals
    cfg0 = settings({"bead_doe": {"enabled": True, "select": {"range": {"combo_samples": 0}}}})
    D0 = _derive(h1, [("S", 1), ("Dp", 1)], cfg0)
    assert not any(x["code"] == "SELECT_RANGE_COMBO" for x in bs.range_check(h1["mesh"], D0, bs.basis(h1["mesh"], D0, cfg0), cfg0))


def test_h2_multi_tier_w_limit_warning():
    """3단 계단: W 기본 범위 끝의 경계 이동(10 mm) > 이웃 단 바닥 간격 → SELECT_W_RANGE_LIMIT{by tier}(범위·기저 불변)."""
    g = sh.build(sh.case("H2"))
    b = _derive(g, [("T", 3)]).bead("b1")
    w = next(x for x in b.warnings if x["code"] == "SELECT_W_RANGE_LIMIT")
    assert w["by"] == "tier" and w["move_mm"] > w["lim_mm"] > 0
    assert b.range_default["W"] == [80.0, 120.0]


def test_inverted_count_matches_affected_quality(h1):
    D = _derive(h1, [("S", 1), ("Dp", 1)])
    B = bs.basis(h1["mesh"], D, CFG)
    x0 = h1["mesh"]["x0"]
    m = h1["mesh"]
    for vals in ({"B1_W": 31.0}, {"B2_D1": 18.0}, {"B1_D1": 16.0}):
        x = bs.morph(x0, B, vals)
        am = bs.affected_elems(m, x0, x)
        q = mq.affected_quality(m, x, am, {}, flip_deg=60.0, max_fail_ratio=1.0)
        assert mq.inverted_count(x0, x, m["conn"], m["elem_type"], np.flatnonzero(am), flip_deg=60.0) == q["inverted"]


# ---------------------------------------------------------------- 6 요소 극단값(SR-D-40)
def test_h1_extreme_elements_not_silent(h1):
    """동시 변수 조합(usable 양 끝 2^4): READY 안은 넓이 비 ≥ area_ratio_min ∧ 법선 회전 ≤ rot_warn_deg 이거나 SELECT_QUALITY_WARN
    (극단값 포함) — 넓이 비 0.11·법선 52~59° 가 경고 없이 READY 로 통과하던 결함. fail_policy skip 은 v0.16.0 판정 그대로."""
    import itertools
    D = _derive(h1, [("S", 1), ("Dp", 1)])
    B = bs.basis(h1["mesh"], D, CFG)
    ws = bs.range_check(h1["mesh"], D, B, CFG)
    use = {r["name"]: tuple(r["default_range"]) for r in bs.params_table(D, CFG)}
    for w in ws:
        if w["code"] == "SELECT_RANGE_INVERTS":
            use[w["var"]] = tuple(w["usable"])
    x0 = h1["mesh"]["x0"]
    m = h1["mesh"]
    n_ext = 0
    for bits in itertools.product([0, 1], repeat=len(use)):
        vals = {k: use[k][i] for k, i in zip(use, bits)}
        x = bs.morph(x0, B, vals)
        st = bs.design_state(m, x0, x, D.fixed_mask, CFG)
        if st["state"] != "READY":
            continue
        am = bs.affected_elems(m, x0, x)
        C = np.asarray(m["conn"])[am]

        def area(X):
            a, b, c, d = (X[C[:, i]] for i in range(4))
            return 0.5 * np.linalg.norm(np.cross(c - a, d - b), axis=1)
        amin = float((area(x) / area(x0)).min())
        rot = float(st["quality"]["max_flip_deg"])
        if amin < 0.2 or rot > 45.0:
            n_ext += 1
            q = next(w for w in st["warnings"] if w["code"] == "SELECT_QUALITY_WARN")
            assert q["area_ratio_min"] == pytest.approx(amin, abs=1e-3) and q["rot_max_deg"] == pytest.approx(rot, abs=0.01)
            cs = settings({"bead_doe": {"enabled": True, "select": {"quality": {"fail_policy": "skip"}}}})
            s2 = bs.design_state(m, x0, x, D.fixed_mask, cs)        # skip 정책 = v0.16.0 판정(극단값 조건 없음, 경고 없음)
            assert not s2["warnings"] and s2["code"] in (None, "SELECT_QUALITY_FAIL")
    assert n_ext > 0
    # 끔(0) → 극단값 조건 없음
    c0 = settings({"bead_doe": {"enabled": True, "select": {"quality": {"rot_warn_deg": 0, "area_ratio_min": 0}}}})
    assert bs._extremes(m, x0, x0 + 0.0, np.ones(m["conn"].shape[0], bool), {"max_flip_deg": 59.0},
                        bs._cfg(c0)["quality"]) is None


# ---------------------------------------------------------------- 9 교차부 동률 규칙(SR-D-43)
def test_tie_rule_smaller_bead_id(h1):
    """교차부 사면 Voronoi 거리 동률 = 비드 id 작은 쪽 — 전체 derive 와 단일 비드 derive(only) 의 사면이 같은 요소를 두 번 갖지 않음."""
    sel = bs.normalize_input(sh.selection(h1, [("S", 1), ("Dp", 1)]), CFG)
    D = bs.derive_obj(h1["mesh"], sel, CFG)
    s1, s2 = D.bead("b1").slope_mask, D.bead("b2").slope_mask
    assert not (s1 & s2).any()
    D2 = bs.derive_obj(h1["mesh"], sel, CFG, only="b2")
    assert not (D2.bead("b2").slope_mask & s1).any()


# ---------------------------------------------------------------- SR-D-44 메시 출처 무관(공통 모핑 코어)
def _rad_inc_roundtrip(g, tmp):
    """같은 메시를 사용자 입력 형식(.rad 주 파일 + #include .inc 메시)으로 쓰고 parse_rad_part 로 다시 읽은 메시 dict + 같은 표지."""
    import os

    from esl.doe import export_mesh
    from esl.rad.parser import parse_rad_part
    d = str(tmp)
    export_mesh.write(d, g["mesh"], part_title="ch_r")
    os.replace(os.path.join(d, export_mesh.RAD_NAME), os.path.join(d, "part.inc"))
    with open(os.path.join(d, "main.rad"), "w", encoding="ascii") as fh:
        fh.write("#RADIOSS STARTER\n/BEGIN\nmain\n      2019         0\n                  Mg                  mm                   s\n"
                 "                  Mg                  mm                   s\n#include part.inc\n/END\n")
    rm = parse_rad_part(os.path.join(d, "main.rad"), None)
    nid = np.asarray(rm.node_id, np.int64)
    pos = {int(v): i for i, v in enumerate(nid.tolist())}
    eid = np.asarray(rm.elem_id, np.int64)
    m = {"node_id": nid, "x0": np.asarray(rm.x0, np.float64), "elem_id": eid,
         "elem_type": np.where(np.asarray(rm.elem_type).astype(int) == 4, 4, 3).astype(np.int8),
         "conn": np.asarray(rm.conn, np.int64)}
    # 표지·고정 노드는 ID 로 옮김(요소·노드 순서가 달라도 같은 요소)
    eo = {int(v): i for i, v in enumerate(np.asarray(g["mesh"]["elem_id"]).tolist())}
    lab = np.array([g["label"][eo[int(e)]] for e in eid.tolist()])
    assert len(pos) == nid.size
    return {**g, "mesh": m, "label": lab}


def _signature(g, beads):
    D = _derive(g, beads)
    B = bs.basis(g["mesh"], D, CFG)
    rc = bs.range_check(g["mesh"], D, B, CFG)
    sig = {"warn": {b.id: sorted(w["code"] for w in b.warnings) for b in D.beads}, "rc": sorted(w["code"] for w in rc),
           "islands": {b.id: len(b.islands) for b in D.beads}, "holes": {b.id: len(b.holes) for b in D.beads},
           "w": {b.id: b.w_enabled for b in D.beads}, "D": {b.id: [round(t["D_nom"], 2) for t in b.tiers] for b in D.beads}}
    st = []
    for row in bs.params_table(D, CFG):
        lo, hi = row["default_range"]
        for v in (lo, 0.5 * (lo + row["nominal"]), hi):
            _x, s = _state(g, D, B, {row["name"]: v})
            st.append((row["name"], s["state"], s["code"], sorted(w["code"] for w in s["warnings"])))
    sig["states"] = st
    return sig


@pytest.mark.parametrize("kind,beads", [("H1", [("S", 1), ("Dp", 1)]), ("H2", [("T", 3)]),
                                        ("H3", [("A", 1), ("B", 1), ("P", 1), ("C", 1)]), ("H4", [("G", 1)])])
def test_mesh_source_independent(kind, beads, tmp_path):
    """SR-D-44: 같은 메시를 (a) 메모리 메시(gmsh·합성 메시 dict)와 (b) .rad + #include .inc 사용자 메시로 읽어 derive·범위 점검·안 판정
    (피처 왜곡·침범·극단값 포함)의 판정·경고 코드가 같다 — 모핑 코어는 메시 출처를 모른다."""
    g = sh.build(sh.case(kind))
    assert _signature(g, beads) == _signature(_rad_inc_roundtrip(g, tmp_path), beads)


@pytest.mark.skipif(not __import__("esl.doe.mesh_gmsh", fromlist=["available"]).available()[0], reason="gmsh 없음")
def test_gmsh_mesh_vs_rad_inc_h4(tmp_path):
    """SR-D-44: H4 STEP 을 gmsh 로 메싱한 메시(비정형 4각·3각)와 그 메시를 .rad/.inc 로 내보내 다시 읽은 메시 — 판정·경고 같음.
    바닥 표지 = 높이장 바닥(z ≈ −10, 평평) 요소."""
    from esl.doe import mesh_gmsh as mg
    from esl.doe import scenario as sc
    src, _nf, _nd = sh.h4_step(str(tmp_path / "h4.step"))
    cfg = sc.compare_cfg(settings({"bead_doe": {"enabled": True, "mesh": {"occ_sew_faces": 1}}}))
    mesh, _meta = mg.run_isolated(src, str(tmp_path / "m"), 3.0, cfg, {"t": 1.0, "E": 205000.0, "nu": 0.3})
    X = np.asarray(mesh["x0"])
    C = np.asarray(mesh["conn"])
    et = np.asarray(mesh["elem_type"]).astype(int)
    cen = np.array([X[c[:4] if t == 4 else c[:3]].mean(axis=0) for c, t in zip(C, et)])
    zmax = np.array([np.abs(X[c[:4] if t == 4 else c[:3]][:, 2] + 10.0).max() for c, t in zip(C, et)])
    lab = np.where(zmax < 1e-6, "Gf1", "x")
    g = {"mesh": mesh, "label": lab, "fixed_ids": np.zeros(0, np.int64)}
    assert (lab == "Gf1").sum() > 100 and cen.shape[0] == C.shape[0]
    a = _signature(g, [("G", 1)])
    b = _signature(_rad_inc_roundtrip(g, tmp_path / "r"), [("G", 1)])
    assert a == b


# ---------------------------------------------------------------- V-AD-5 구멍 건너 잇기 상한(v0.16.2 AD-D-7)
def test_bridge_cap_skips_large_opening(h4):
    """H4 슬롯(등가 지름 ≤ 20 mm)은 기본 상한에서 v0.16.1 그대로 건너 이음(상한 없음과 기저·요약 바이트 동일, 경고 없음).
    상한을 슬롯 등가 지름보다 작게 하면 건너 잇지 않고 SELECT_BRIDGE_SKIPPED{eq_d_mm, gap_mm}(고리 열림)."""
    g, D, B = h4
    b = D.bead("b1")
    eq = float(b.holes[0]["eq_d_mm"])
    assert eq <= CFG["select"]["hole"]["bridge_max_mm"] == 20.0
    assert "SELECT_BRIDGE_SKIPPED" not in _codes(b) and b.loops[0].get("bridged") == 1
    big = settings({"bead_doe": {"enabled": True, "select": {"hole": {"bridge_max_mm": 1e9}}}})
    Db = _derive(g, [("G", 1)], big)
    assert bs.basis_bin(bs.basis(g["mesh"], Db, big)) == bs.basis_bin(B)
    assert Db.summary(with_figures=False) == D.summary(with_figures=False)
    small = settings({"bead_doe": {"enabled": True, "select": {"hole": {"bridge_max_mm": 0.5 * eq}}}})
    Ds = _derive(g, [("G", 1)], small)
    bsk = Ds.bead("b1")
    w = [x for x in bsk.warnings if x["code"] == "SELECT_BRIDGE_SKIPPED"]
    assert len(w) == 1 and w[0]["eq_d_mm"] == pytest.approx(eq, abs=1e-3) and w[0]["gap_mm"] > 0
    assert all(lp.get("bridged", 0) == 0 for lp in bsk.loops)
    # 해시: 기본값이면 select_hash_view 에서 빠짐(v0.16.1 해시 불변), 값을 바꾸면 남음
    assert "hole" not in bs.select_hash_view(CFG["select"]) and "auto" not in bs.select_hash_view(CFG["select"])
    assert bs.select_hash_view(small["select"])["hole"] == {"bridge_max_mm": 0.5 * eq}
    tweak = settings({"bead_doe": {"enabled": True, "select": {"auto": {"slope_diff_rel": 0.5}}}})
    assert bs.select_hash_view(tweak["select"]) == bs.select_hash_view(CFG["select"])


def test_bridge_holes_core_cap_unit():
    """공통 코어 ``bridge_holes``: 같은 구멍 양 끝 열린 고리 — 상한 이하 = 닫힘(bridged 1), 상한 초과 = 열린 채 + 경고 1개."""
    from esl.morph import core as mc

    class IX:
        X = np.array([[0.0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [0, 1, 0]])
    loops = [{"nodes": np.array([0, 1, 2, 3]), "closed": False}]
    hole = [{"nodes": np.array([3, 4, 0]), "eq_d_mm": 30.0}]
    out = mc.bridge_holes(IX, loops, hole)
    assert out[0]["closed"] and out[0]["bridged"] == 1
    sk: list = []
    out2 = mc.bridge_holes(IX, loops, hole, max_d_mm=20.0, skipped=sk)
    assert not out2[0]["closed"] and out2[0]["bridged"] == 0
    assert sk == [{"code": "SELECT_BRIDGE_SKIPPED", "eq_d_mm": 30.0, "gap_mm": 10.0}]
    assert mc.bridge_holes(IX, loops, hole, max_d_mm=30.0)[0]["closed"]


def test_regress_exception_list_codes_have_messages():
    """AD-D-6 예외 목록 = 계약 그대로 6개, 모두 문구가 있는 경고 코드(새 코드 SELECT_BRIDGE_SKIPPED 는 예외 아님 — 상한 이하 바이트 불변)."""
    from esl.doe import load_messages
    msgs = load_messages()["messages"]
    assert len(set(REGRESS_WARN_EXCEPTIONS_V0162)) == 6 and all(c in msgs for c in REGRESS_WARN_EXCEPTIONS_V0162)
    assert "SELECT_BRIDGE_SKIPPED" not in REGRESS_WARN_EXCEPTIONS_V0162
    for c in ("AUTO_DETECT_FAILED", "AUTO_TOO_MANY_BEADS", "AUTO_GROUP_DROPPED", "AUTO_BEAD_UNMAPPED", "AUTO_SLOPE_DIFF",
              "SELECT_BRIDGE_SKIPPED", "MORPH_EXTREME_ELEMENTS", "AUTO_NOT_AVAILABLE", "PREP_NOT_READY"):
        assert c in msgs, c
