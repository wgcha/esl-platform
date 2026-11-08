"""V-SR-2~9 비드 바닥 안 형상(섬·구멍)·hold·판정 정책 (계약 esl_select_relax.md §5·§11, v0.16.1).

합성 메시 = ``synth_bead.generate(features=True)``: b1 단1 바닥에 관통 구멍·딤플 3개(하나 위로 볼록)·버링(구멍 + 칼라)·체결 구멍
(둘레 고정 노드). 정답 표지 'b1i'(섬), 반환 islands·hole_rims·fastener_rim. 같은 h 의 features=False 메시와 비교."""
import numpy as np
import pytest

import synth_bead as sb
from esl.doe import bead_select as bs
from esl.doe import settings
from esl.errors import EslError
from esl.mesh import features as ft

H = 5.0
CFG = settings({"bead_doe": {"enabled": True}})
SKIP = settings({"bead_doe": {"enabled": True, "select": {"fixed_policy": "skip", "quality": {"fail_policy": "skip"}}}})


def _derive(g, cfg=CFG, sel=None):
    sel = sel or sb.selection(g)
    return bs.derive_obj(g["mesh"], bs.normalize_input(sel, cfg), cfg, fixed_node_ids=g["fixed_ids"])


@pytest.fixture(scope="module")
def F():
    g = sb.generate(H, features=True)
    D = _derive(g)
    return g, D, bs.basis(g["mesh"], D, CFG)


@pytest.fixture(scope="module")
def P():
    g = sb.generate(H)
    D = _derive(g)
    return g, D, bs.basis(g["mesh"], D, CFG)


def _isl_sets(b):
    return sorted(tuple(sorted(i["elems"].tolist())) for i in b.islands)


# ---------------------------------------------------------------- V-SR-2 섬 판정
def test_islands_truth(F):
    g, D, _B = F
    b1 = D.bead("b1")
    truth = sorted(tuple(sorted(i["elems"].tolist())) for i in g["islands"])
    assert _isl_sets(b1) == truth and len(truth) == 4                     # 딤플 3 · 버링 1(체결·관통 구멍은 요소 없음)
    for i, t in zip(sorted(b1.islands, key=lambda x: int(x["elems"].min())),
                    sorted(g["islands"], key=lambda x: int(x["elems"].min()))):
        assert sorted(i["rim"].tolist()) == sorted(t["rim"].tolist())
        assert sorted(i["interior"].tolist()) == sorted(t["interior"].tolist())
        assert i["k"] == 1
    assert not any(w["code"] == "SELECT_TIER_MISSING" for w in b1.warnings)     # B3 해소
    assert D.bead("b2").islands == []                                       # 판 나머지(최대 성분)는 섬 아님
    s = D.summary(with_figures=False)
    b1s = next(b for b in s["beads"] if b["id"] == "b1")
    assert len(b1s["islands"]) == 4 and sum(x["free_loops"] for x in b1s["islands"]) == 1 and s["algo"] == 2
    assert sum(bs.elems_of(D.index, x["elems"]).sum() for x in b1s["islands"]) == (g["label"] == "b1i").sum()
    d = bs.derive(g["mesh"], bs.normalize_input(sb.selection(g), CFG), CFG, fixed_scan=g["fixed_ids"])
    assert bs.elems_of(D.index, d["islands_suggested"]["b1"]).sum() == (g["label"] == "b1i").sum()


def test_two_tier_wall_not_island(P):
    """단 사이 벽(2단 포개짐) = 두 단에 닿음 → 섬 아님. features 없는 메시는 섬 0."""
    _g, D, _B = P
    assert all(b.islands == [] for b in D.beads)


def test_island_too_large_and_exclude():
    g = sb.generate(H, features=True)
    cfg = settings({"bead_doe": {"enabled": True, "select": {"island": {"max_mm": 10.0}}}})
    D = _derive(g, cfg)
    b1 = D.bead("b1")
    tl = [w for w in b1.warnings if w["code"] == "SELECT_ISLAND_TOO_LARGE"]
    assert len(tl) == 4 and b1.islands == [] and all(w["size_mm"] > 10.0 for w in tl)
    assert any(w["code"] == "SELECT_INNER_LOOP" for w in b1.warnings)        # v0.16.0 동작(안쪽 고리)
    # 섬 요소를 exclude 층으로 → 섬 아님 + SELECT_INNER_LOOP
    sel = sb.selection(g)
    sel["exclude"] = sb.elemset(g["mesh"], g["label"] == "b1i")
    De = _derive(g, CFG, sel)
    b1e = De.bead("b1")
    assert b1e.islands == [] and b1e.inner_loops_n == 4
    assert [w["n"] for w in b1e.warnings if w["code"] == "SELECT_INNER_LOOP"] == [4]


# ---------------------------------------------------------------- V-SR-3 구멍
def test_holes_not_open(F):
    g, D, B = F
    b1 = D.bead("b1")
    assert len(b1.holes) == 2 and not b1.open and b1.w_enabled                # 관통 + 체결
    assert sorted(sorted(h["nodes"].tolist()) for h in b1.holes) == sorted(sorted(r.tolist()) for r in g["hole_rims"])
    assert not any(w["code"] == "SELECT_OPEN_BOUNDARY" for w in b1.warnings)
    assert "B1_W" in B.by_name()
    s = next(b for b in D.summary(with_figures=False)["beads"] if b["id"] == "b1")
    assert s["holes"] == {"n": 2, "n_nodes": 16}
    go = sb.generate(H, open_end=True, features=True)                        # 판 가장자리 비드는 그대로 열린 경계
    bo = _derive(go).bead("b1")
    assert bo.open and any(w["code"] == "SELECT_OPEN_BOUNDARY" for w in bo.warnings) and len(bo.holes) == 2


# ---------------------------------------------------------------- V-SR-4 경계 고리
def test_boundary_loops_same_as_plain(F, P):
    gf, Df, _ = F
    gp, Dp, _ = P
    bf, bp = Df.bead("b1"), Dp.bead("b1")
    assert len(bf.loops) == len(bp.loops) == 1 and bf.inner_loops_n == 0
    nf = gf["mesh"]["node_id"][bf.loops[0]["nodes"]]
    npl = gp["mesh"]["node_id"][bp.loops[0]["nodes"]]
    xf = gf["mesh"]["x0"][bf.loops[0]["nodes"]]
    xp = gp["mesh"]["x0"][bp.loops[0]["nodes"]]
    assert nf.size == npl.size and np.allclose(xf, xp, atol=1e-12)           # 같은 경계(노드 번호는 재번호)
    for k in ("W_nom", "W_min", "W_max"):
        assert getattr(bf, k) == pytest.approx(getattr(bp, k), abs=1e-9)


# ---------------------------------------------------------------- V-SR-5 섬 강체 이동
def test_island_rigid_depth(F):
    g, D, B = F
    X0 = g["mesh"]["x0"]
    x = bs.morph(X0, B, {"B1_D1": B.nominal()["B1_D1"] + 3.0})
    u = x - X0
    b1 = D.bead("b1")
    for i in b1.islands:
        t = u[i["rim"]].mean(axis=0)
        assert np.allclose(u[i["interior"]], t, atol=1e-12, rtol=0)
        assert np.allclose(u[i["rim"]], u[i["rim"]][0], atol=1e-9)          # 평면 바닥 = 바닥 변위
        el = i["elems"]
        C = g["mesh"]["conn"][el]
        for a in range(4):                                                   # 섬 요소 모서리 길이 불변(벽 길이·각)
            L0 = np.linalg.norm(X0[C[:, a]] - X0[C[:, (a + 1) % 4]], axis=1)
            L1 = np.linalg.norm(x[C[:, a]] - x[C[:, (a + 1) % 4]], axis=1)
            assert np.allclose(L0, L1, atol=1e-9)
    up = next(i for i in b1.islands if np.all(X0[i["interior"], 2] > X0[i["rim"][0], 2]))   # 위로 볼록 딤플도 같음
    assert np.allclose(u[up["interior"]], u[up["rim"]].mean(axis=0), atol=1e-12)


def test_island_width_parallel(F):
    g, D, B = F
    X0 = g["mesh"]["x0"]
    x = bs.morph(X0, B, {"B1_W": B.nominal()["B1_W"] + 6.0})
    u = x - X0
    n = D.bead("b1").n_hat
    for i in D.bead("b1").islands:
        ui = u[i["interior"]]
        assert np.allclose(ui, ui[0], atol=1e-12)                            # 평행 이동(V-SR-7 상대 형상 불변)
        assert abs(float(ui[0] @ n)) <= 1e-9                                  # 면외 0


# ---------------------------------------------------------------- V-SR-6 구멍 둘레
def test_hole_rim_follows_floor(F):
    g, D, B = F
    X0 = g["mesh"]["x0"]
    b1 = D.bead("b1")
    x = bs.morph(X0, B, {"B1_D1": B.nominal()["B1_D1"] + 3.0})
    t1 = next(t for t in b1.tiers if t["k"] == 1)
    for hl in b1.holes:
        u = (x - X0)[hl["nodes"]]
        assert np.allclose(u @ t1["normal"], 3.0, atol=1e-6)                 # n_i^k 식 그대로
    xw = bs.morph(X0, B, {"B1_W": B.nominal()["B1_W"] + 6.0})
    uw = xw - X0
    ix = D.index
    Lf = b1.W_nom - 2.0 * b1.run_med                                        # 바닥 폭(조화 확장 기울기 기준)
    for hl in b1.holes:                                                      # 조화 확장 연속: 이웃 바닥 노드와 차 ≤ (ΔW/2)(h/L)c
        G = bs._node_graph(ix, b1.floor_mask)
        for v in hl["nodes"].tolist():
            nb = G.indices[G.indptr[v]:G.indptr[v + 1]]
            assert np.max(np.linalg.norm(uw[nb] - uw[v], axis=1)) <= 3.0 * (ix.h_med / Lf) * 3.0


# ---------------------------------------------------------------- V-SR-8 hold
def test_hold_fixed_boss(F):
    g, D0, B0 = F
    m = g["mesh"]
    X0 = m["x0"]
    sel = sb.selection(g)
    sel["beads"][0]["hold_fixed"] = 1
    norm = bs.normalize_input(sel, CFG)
    assert norm["beads"][0]["hold_fixed"] == 1 and "hold_fixed" not in bs.normalize_input(sb.selection(g), CFG)["beads"][0]
    assert bs.selection_sha256(norm) != bs.selection_sha256(bs.normalize_input(sb.selection(g), CFG))
    D = bs.derive_obj(m, norm, CFG, fixed_node_ids=g["fixed_ids"])
    B = bs.basis(m, D, CFG)
    b1 = D.bead("b1")
    assert b1.hold["n_fixed"] == 8 and b1.hold["n_ring_nodes"] >= 8
    rho, bw = CFG["select"]["hold"]["ring_mm"], CFG["select"]["hold"]["blend_mm"]
    dD = 3.0
    vals = {"B1_D1": B.nominal()["B1_D1"] + dD}
    x = bs.morph(X0, B, vals)
    x0h = bs.morph(X0, B0, vals)
    P = g["fastener_rim"]
    d = np.min(np.linalg.norm(X0[:, None, :] - X0[P][None, :, :], axis=2), axis=1)
    ring = d <= rho
    assert np.array_equal(x[ring], X0[ring])                                 # 고정 노드·링 제자리
    far = (d >= rho + bw) & np.isin(np.arange(X0.shape[0]), b1.bead_nodes)
    assert np.array_equal(x[far], x0h[far])                                  # 멀리는 hold 0 과 바이트 동일
    t1 = next(t for t in b1.tiers if t["k"] == 1)
    fl = np.intersect1d(t1["nodes"], np.flatnonzero(far))
    assert np.allclose((x[fl] - X0[fl]) @ t1["normal"], dD, atol=1e-9)     # 보스 높이 = ΔD
    st = bs.design_state(m, X0, x, D.fixed_mask, CFG)
    assert not any(w["code"] == "SELECT_FIXED_MOVED" for w in st["warnings"])
    st0 = bs.design_state(m, X0, x0h, D0.fixed_mask, CFG)                   # hold 0 → 정답 n·max
    dv = np.linalg.norm(x0h[D0.fixed_mask] - X0[D0.fixed_mask], axis=1)
    w = next(w for w in st0["warnings"] if w["code"] == "SELECT_FIXED_MOVED")
    assert w["n"] == int(np.sum(dv > CFG["select"]["fixed_tol_mm"])) and w["max_mm"] == pytest.approx(dv.max(), abs=1e-4)
    # φ 연속: ρ·ρ+b 양쪽 첫 줄 차가 작음(C¹ — 끝 기울기 0)
    tt = np.linspace(0, 1, 201)
    phi = 1.0 - bs._wendland(tt)
    assert phi[0] == 0.0 and phi[-1] == 1.0 and abs(phi[1] - phi[0]) < 1e-3 and abs(phi[-1] - phi[-2]) < 1e-3
    with pytest.raises(EslError) as ei:
        bad = sb.selection(g)
        bad["beads"][0]["hold_fixed"] = True
        bs.normalize_input(bad, CFG)
    assert ei.value.code == "SELECT_HOLD_INVALID"


def test_hold_no_fixed():
    g = sb.generate(H)
    sel = sb.selection(g)
    sel["beads"][1]["hold_fixed"] = 1                                       # b2 근처 고정 없음
    D = _derive(g, CFG, sel)
    assert any(w["code"] == "SELECT_HOLD_NO_FIXED" for w in D.bead("b2").warnings)
    assert D.bead("b2").hold == {"n_ring_nodes": 0, "n_blend_nodes": 0, "n_fixed": 0}


# ---------------------------------------------------------------- V-SR-9 판정·정책·feasible·해시
def test_policies_and_order(P):
    g, D, B = P
    m = g["mesh"]
    X0 = m["x0"]
    sel = sb.selection(g)
    sel["beads"][0]["blend_mm"] = 24.0                                      # 블렌딩이 고정 노드에 닿음
    Du = _derive(g, CFG, sel)
    Bu = bs.basis(m, Du, CFG)
    W = Bu.nominal()["B1_W"]
    x = bs.morph(X0, Bu, {"B1_W": W + 6})
    assert bs.design_state(m, X0, x, Du.fixed_mask, CFG)["state"] == "READY"
    assert bs.design_state(m, X0, x, Du.fixed_mask, SKIP)["state"] == "SKIPPED_FIXED"
    xi = bs.morph(X0, Bu, {"B1_W": 0.6 * W})                                # 뒤집힘(W −40 %) + 침범
    for cfg in (CFG, SKIP):
        st = bs.design_state(m, X0, xi, Du.fixed_mask, cfg)
        assert (st["state"], st["code"]) == ("FAILED_MESH", "SELECT_MORPH_INVERTED") and st["fixed"]["violated"]
    bad = settings({"bead_doe": {"enabled": True, "select": {"fixed_policy": "nope"}}})
    with pytest.raises(EslError):
        bs.design_state(m, X0, x, Du.fixed_mask, bad)


def test_feasible_wider_than_default(P):
    _g, D, _B = P
    tab = {r["name"]: r for r in bs.params_table(D, CFG)}
    for r in tab.values():
        lo, hi = r["default_range"]
        flo, fhi = r["feasible"]
        assert flo <= lo and fhi >= hi and flo > 0
    b1 = D.bead("b1")
    t2 = next(t for t in b1.tiers if t["k"] == 2)
    assert tab["B1_D2"]["feasible"][1] == pytest.approx(2.0 * t2["D_nom"], abs=1e-3)
    assert tab["B1_W"]["feasible"][1] == pytest.approx(1.6 * b1.W_nom, abs=1e-3)
    zs = sorted(t["D_nom"] for t in b1.tiers)
    assert tab["B1_D1"]["feasible"][0] == pytest.approx(zs[0] + 1.0, abs=1e-3)   # 위 수준 + min_step
    s = next(b for b in D.summary(with_figures=False)["beads"] if b["id"] == "b1")
    assert s["range_feasible"]["W"] == tab["B1_W"]["feasible"] and s["range_feasible"]["D"]["1"] == tab["B1_D1"]["feasible"]


def test_select_hash_view_v0160():
    """기본 설정 해시 사본 = v0.16.0 select 절(새 키 없음), 바꾼 새 키만 남음(SR-D-13b)."""
    import json
    import os
    v0160 = json.load(open(os.path.join(os.path.dirname(__file__), "..", "fixtures", "bead_select",
                                        "v0160_select_cfg.json"), encoding="utf-8"))
    assert bs.select_hash_view(CFG["select"]) == v0160
    hv = bs.select_hash_view(SKIP["select"])
    assert hv["fixed_policy"] == "skip" and hv["quality"]["fail_policy"] == "skip" and "island" not in hv


# ---------------------------------------------------------------- V-SR-22 공통 모듈(정답)
def test_features_module_truth(F):
    g, D, _B = F
    ix = D.index
    b1 = D.bead("b1")
    fe = ft.free_edge_components(ix, b1.bead_mask, b1.boundary_nodes)
    assert len(fe["holes"]) == 3                                            # 관통·체결·버링 칼라 끝
    dg = ft.diagnose(g["mesh"], feature_angle_deg=30.0, hole_max_d_mm=8.0, island_max_mm=40.0, index=ix)
    assert dg["holes_n"] == 3 and dg["free_loops_n"] == 4
    assert dg["holes_small_n"] == sum(1 for h in fe["holes"] if h["eq_d_mm"] <= 8.0)
    gp = sb.generate(H)
    dp = ft.diagnose(gp["mesh"], feature_angle_deg=30.0, hole_max_d_mm=8.0, island_max_mm=40.0)
    assert dp["holes_n"] == 0 and dp["holes_small_n"] == 0
