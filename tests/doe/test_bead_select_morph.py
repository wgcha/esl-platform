"""V-BS-1·2·3·4·8: 비드 직접 선택 선형 기저 모핑(계약 esl_bead_select.md §5) — 깊이·폭 정확도, 블렌딩 연속·선형 합,
고정 노드 침범·반경 자르기, 선형성·결정성(basis.npz 바이트·sha)."""
import math

import numpy as np
import pytest

import synth_bead as sb
from esl.doe import bead_select as bs
from esl.doe import settings
from esl.library import _util as U

CFG = settings({"bead_doe": {"enabled": True}})
SKIP = settings({"bead_doe": {"enabled": True, "select": {"fixed_policy": "skip", "quality": {"fail_policy": "skip"}}}})


@pytest.fixture(scope="module")
def G():
    g = sb.generate()
    norm = bs.normalize_input(sb.selection(g), CFG)
    D = bs.derive_obj(g["mesh"], norm, CFG, fixed_node_ids=g["fixed_ids"])
    B = bs.basis(g["mesh"], D, CFG)
    return g, norm, D, B


def _nodes_by_x(g, idx, lo, hi):
    x = g["mesh"]["x0"][idx, 0]
    return idx[(x > lo) & (x < hi)]


def _cfg_ff(f):
    return settings({"bead_doe": {"enabled": True, "select": {"width": {"floor_follow": f}}}})


# ---------------------------------------------------------------- V-BS-1 깊이
@pytest.mark.parametrize("dlt", [3.0, -3.0])
def test_depth_accuracy(G, dlt):
    g, norm, D, B = G
    X0 = g["mesh"]["x0"]
    b1 = D.bead("b1")
    x = bs.morph(X0, B, {"B1_D1": 22.0 + dlt})
    t1, t2 = b1.tiers[0]["nodes"], b1.tiers[1]["nodes"]
    du = x - X0
    assert np.allclose(du[t1, 2], -dlt, atol=1e-9) and np.allclose(du[t1, :2], 0.0, atol=1e-9)   # 깊어짐 = −z
    assert np.array_equal(x[t2], X0[t2])                                                    # 단2 바이트 불변
    assert np.array_equal(x[b1.boundary_nodes], X0[b1.boundary_nodes])                     # 경계 바이트 불변
    moved = np.zeros(len(X0), bool)
    moved[b1.bead_nodes] = True
    assert np.array_equal(x[~moved], X0[~moved])                                            # 상판·다른 비드 불변
    # 사면(경사로 구간에서 먼 곳): z 변화 = s·Δ, s = 높이 비율(정답 zcode/22)
    sn = b1.slope_nodes
    far = sn[(np.abs(X0[sn, 0] - 350.0) > 80.0)]
    s_true = (-X0[far, 2]) / 22.0
    assert far.size > 50
    assert np.allclose(du[far, 2], -s_true * dlt, atol=1e-9) and np.allclose(du[far, :2], 0.0, atol=1e-9)
    # 사면 각 = atan((22 + Δ)/run) (곧은 구간 아래쪽 사면 요소)
    ix = D.index
    lab = g["label"]
    cen = ix.centroid
    pick = np.flatnonzero((lab == "b1s") & (cen[:, 0] > 150) & (cen[:, 0] < 200) & (cen[:, 1] < 160))
    assert pick.size >= 4
    ix2 = bs.mesh_index({**g["mesh"], "x0": x})
    ang = np.degrees(np.arccos(np.abs(ix2.normal[pick, 2])))
    assert np.allclose(ang, math.degrees(math.atan((22.0 + dlt) / (22.0 / math.tan(math.radians(60))))), atol=0.1)


def test_depth_tier2_and_link(G):
    g, norm, D, B = G
    X0 = g["mesh"]["x0"]
    b1 = D.bead("b1")
    x = bs.morph(X0, B, {"B1_D2": 14.0 + 2.0})
    t1, t2 = b1.tiers[0]["nodes"], b1.tiers[1]["nodes"]
    assert np.allclose((x - X0)[t2, 2], -2.0, atol=1e-9) and np.array_equal(x[t1], X0[t1])
    # 묶음: D1·D2 를 같은 값 변화로
    sel = sb.selection(g, links=[[1, 2]])
    Dl = bs.derive_obj(g["mesh"], bs.normalize_input(sel, CFG), CFG)
    Bl = bs.basis(g["mesh"], Dl, CFG)
    names = [v["name"] for v in Bl.vars]
    assert "B1_D1" in names and "B1_D2" not in names
    xl = bs.morph(X0, Bl, {"B1_D1": 22.0 + 1.5})
    assert np.allclose((xl - X0)[np.concatenate([t1, t2]), 2], -1.5, atol=1e-9)
    row = next(r for r in bs.params_table(Dl, CFG) if r["name"] == "B1_D1")
    assert row["group_members"] == ["B1_D1", "B1_D2"]


# ---------------------------------------------------------------- V-BS-2 폭
def _local_width(g, x, D0, nodes):
    """모핑 좌표에서 같은 선택으로 다시 derive → 같은 경계 노드의 국부 폭."""
    m = {**g["mesh"], "x0": x}
    D1 = bs.derive_obj(m, D0.norm, CFG, with_section=False)
    b = D1.bead("b1")
    w = dict(zip(b.w_jnodes.tolist(), b.w_j.tolist()))
    return np.array([w.get(int(n), np.nan) for n in nodes])


@pytest.mark.parametrize("dw", [6.0, -6.0])
def test_width_floor_follow_1(G, dw):
    g, norm, D, B = G
    X0 = g["mesh"]["x0"]
    h = g["h"]
    b1 = D.bead("b1")
    x = bs.morph(X0, B, {"B1_W": B.nominal()["B1_W"] + dw})
    # 국부 폭 변화 = ΔW (꺾임·끝단·경사로에서 먼 곳)
    xx = X0[b1.w_jnodes, 0]
    ok = (((xx > 140) & (xx < 210)) | ((xx > 430) & (xx < 470))) & (np.abs(X0[b1.w_jnodes, 1] - 185) < 60)
    nodes, w0 = b1.w_jnodes[ok], b1.w_j[ok]
    w1 = _local_width(g, x, D, nodes)
    assert nodes.size > 20 and np.all(np.isfinite(w1))
    assert np.allclose(w1 - w0, dw, atol=0.02 * h)
    # 사면 각 불변(±0.1°) — 곧은 구간
    ix = D.index
    cen = ix.centroid
    pick = np.flatnonzero((g["label"] == "b1s") & (cen[:, 0] > 150) & (cen[:, 0] < 200))
    ix2 = bs.mesh_index({**g["mesh"], "x0": x})
    a0 = np.degrees(np.arccos(np.abs(ix.normal[pick, 2])))
    a1 = np.degrees(np.arccos(np.abs(ix2.normal[pick, 2])))
    assert np.allclose(a0, a1, atol=0.1)
    # 바닥 가장자리 = ±ΔW/2 (y), 바닥 폭 +ΔW
    fe = np.intersect1d(np.concatenate([t["nodes"] for t in b1.tiers]), ix.elem_nodes(b1.slope_mask))
    fe = fe[(X0[fe, 0] > 150) & (X0[fe, 0] < 200)]
    side = np.sign(X0[fe, 1] - 170.0)
    assert np.allclose((x - X0)[fe, 1], side * dw / 2.0, atol=0.02 * h)
    # 끝단 이동 = ΔW/2 (x = 100 끝단 가운데 경계 노드)
    bn = b1.boundary_nodes
    end = bn[(np.abs(X0[bn, 0] - 100.0) < 1e-6) & (np.abs(X0[bn, 1] - 170.0) < 8.0)]
    assert end.size >= 1 and np.allclose((x - X0)[end, 0], -dw / 2.0, atol=1e-6)
    # 면외 성분: 비드 노드 = n̂_b 방향 0, 블렌딩 노드 = 노드 법선 방향 0
    u = x - X0
    assert np.max(np.abs(u[b1.bead_nodes] @ b1.n_hat)) <= 1e-9
    from esl.view3d import node_geometry
    nu = node_geometry(X0, g["mesh"]["conn"], g["mesh"]["elem_type"]).n
    bl = b1.blend_nodes
    assert np.max(np.abs(np.einsum("ij,ij->i", u[bl], nu[bl]))) <= 1e-9


def test_width_floor_follow_0(G):
    g, _, _, _ = G
    cfg = _cfg_ff(0)
    D = bs.derive_obj(g["mesh"], bs.normalize_input(sb.selection(g), cfg), cfg, fixed_node_ids=g["fixed_ids"])
    B = bs.basis(g["mesh"], D, cfg)
    X0 = g["mesh"]["x0"]
    b1 = D.bead("b1")
    dw = 6.0
    x = bs.morph(X0, B, {"B1_W": B.nominal()["B1_W"] + dw})
    fl = np.concatenate([t["nodes"] for t in b1.tiers])
    assert np.array_equal(x[fl], X0[fl])                                  # 바닥 불변
    sn = b1.slope_nodes
    sn = sn[(X0[sn, 0] > 150) & (X0[sn, 0] < 200)]
    s = -X0[sn, 2] / 22.0
    side = np.sign(X0[sn, 1] - 170.0)
    assert np.allclose((x - X0)[sn, 1], side * (1.0 - s) * dw / 2.0, atol=0.05)   # (1 − s')·w
    # 사면 각이 식대로 변함: run' = run − ΔW/2 → atan(22 / run')
    ix = D.index
    cen = ix.centroid
    pick = np.flatnonzero((g["label"] == "b1s") & (cen[:, 0] > 150) & (cen[:, 0] < 200) & (cen[:, 1] < 160))
    ix2 = bs.mesh_index({**g["mesh"], "x0": x})
    run = 22.0 / math.tan(math.radians(60))
    a1 = np.degrees(np.arccos(np.abs(ix2.normal[pick, 2])))
    assert np.allclose(a1, math.degrees(math.atan(22.0 / (run + dw / 2.0))), atol=0.3)


# ---------------------------------------------------------------- V-BS-3 블렌딩
def test_blending_continuity_and_linear_sum(G):
    g, norm, D, B = G
    X0 = g["mesh"]["x0"]
    b1 = D.bead("b1")
    R = b1.blend_mm
    dw = 6.0
    x = bs.morph(X0, B, {"B1_W": B.nominal()["B1_W"] + dw})
    u = x - X0
    from scipy.spatial import cKDTree
    out = np.setdiff1d(np.arange(len(X0)), np.concatenate([b1.bead_nodes, D.bead("b2").bead_nodes]))
    d, _ = cKDTree(X0[b1.boundary_nodes]).query(X0[out], k=1)
    far = out[d >= R]
    assert np.array_equal(x[far], X0[far])                                  # d ≥ R 바이트 불변
    ix = D.index
    E = ix.edge_nodes
    inb = np.zeros(len(X0), bool)
    inb[b1.bead_nodes] = True
    pl = ~inb[E[:, 0]] | ~inb[E[:, 1]]                                       # 상판(또는 경계 첫 줄) 모서리
    du = np.linalg.norm(u[E[pl, 0]] - u[E[pl, 1]], axis=1)
    lim = (dw / 2.0) * (ix.edge_len[pl] / R) * 3.0
    assert np.all(du <= lim + 1e-9)
    # 두 비드 블렌딩 겹침 = 선형 합
    sel = sb.selection(g)
    sel["beads"][1]["blend_mm"] = 150.0
    D2 = bs.derive_obj(g["mesh"], bs.normalize_input(sel, CFG), CFG)
    assert any(w["code"] == "SELECT_BLEND_OVERLAP" for w in D2.bead("b1").warnings)
    B2 = bs.basis(g["mesh"], D2, CFG)
    nom = B2.nominal()
    va = {"B1_W": nom["B1_W"] + 4.0}
    vb = {"B2_W": nom["B2_W"] - 3.0}
    xa, xb, xab = bs.morph(X0, B2, va), bs.morph(X0, B2, vb), bs.morph(X0, B2, {**va, **vb})
    both = np.intersect1d(B2.by_name()["B1_W"]["idx"], B2.by_name()["B2_W"]["idx"])
    assert both.size > 0
    assert np.allclose(xab - X0, (xa - X0) + (xb - X0), atol=1e-12, rtol=0)


# ---------------------------------------------------------------- V-BS-4 고정 노드
def test_fixed_nodes(G):
    g, norm, D, B = G
    X0 = g["mesh"]["x0"]
    m = g["mesh"]
    b1 = D.bead("b1")
    assert b1.blend_clipped and any(w["code"] == "SELECT_BLEND_CLIPPED" for w in b1.warnings)
    assert abs(b1.blend_mm - (b1.d_fixed - CFG["select"]["blend"]["fixed_margin_mm"])) < 1e-9
    assert 17.0 < b1.d_fixed < 21.0
    fm = D.fixed_mask
    for v in ({"B1_W": B.nominal()["B1_W"] + 6}, {"B1_D1": 25.0}, {"B1_W": B.nominal()["B1_W"] - 6, "B2_W": 44.0}):
        x = bs.morph(X0, B, v)
        st = bs.design_state(m, X0, x, fm, CFG)
        assert np.array_equal(x[fm], X0[fm]) and st["state"] != "SKIPPED_FIXED", st
    # 사용자 R 24 > 고정까지 거리 → 침범 → skip 정책 SKIPPED_FIXED (v0.16.0 V-BS-4 그대로 — V-SR-9 skip 경로)
    sel = sb.selection(g)
    sel["beads"][0]["blend_mm"] = 24.0
    Du = bs.derive_obj(m, bs.normalize_input(sel, CFG), CFG, fixed_node_ids=g["fixed_ids"])
    assert any(w["code"] == "SELECT_FIXED_IN_BLEND" for w in Du.bead("b1").warnings)
    Bu = bs.basis(m, Du, CFG)
    x = bs.morph(X0, Bu, {"B1_W": Bu.nominal()["B1_W"] + 6})
    st = bs.design_state(m, X0, x, Du.fixed_mask, SKIP)
    assert st["state"] == "SKIPPED_FIXED" and st["code"] == "SELECT_FIXED_VIOLATION"
    # warn 정책(기본, V-SR-9): READY + SELECT_FIXED_MOVED{n, max_mm} = 정답(고정 노드 변위)
    st = bs.design_state(m, X0, x, Du.fixed_mask, CFG)
    d = np.linalg.norm(x[Du.fixed_mask] - X0[Du.fixed_mask], axis=1)
    fmv = [w for w in st["warnings"] if w["code"] == "SELECT_FIXED_MOVED"]
    assert st["state"] == "READY" and fmv and fmv[0]["n"] == int(np.sum(d > CFG["select"]["fixed_tol_mm"]))
    assert fmv[0]["max_mm"] == pytest.approx(float(d.max()), abs=1e-4)
    x = bs.morph(X0, Bu, {"B1_D1": 24.0})                            # 깊이만 → 고정 불변
    assert bs.design_state(m, X0, x, Du.fixed_mask, CFG)["state"] == "READY"
    # 비드 안 고정(사용자 고정 층) → 경고 + 그 비드 변수 기본 체크 해제
    lab = g["label"]
    one = np.flatnonzero(lab == "b1t1")[:1]
    mask = np.zeros(lab.size, bool)
    mask[one] = True
    sel = sb.selection(g)
    sel["fixed_user"] = sb.elemset(m, mask)
    Df = bs.derive_obj(m, bs.normalize_input(sel, CFG), CFG)
    assert any(w["code"] == "SELECT_FIXED_IN_BEAD" for w in Df.bead("b1").warnings)
    assert Df.fixed["source"] == "user"
    tab = {r["name"]: r for r in bs.params_table(Df, SKIP)}             # skip 정책 = v0.16.0 기본 체크 해제
    assert not tab["B1_D1"]["use_default"] and not tab["B1_W"]["use_default"] and tab["B1_D2"]["use_default"]
    assert tab["B2_D1"]["use_default"]
    tab = {r["name"]: r for r in bs.params_table(Df, CFG)}              # warn(기본, SR-D-8) = 해제하지 않음
    assert all(r["use_default"] for r in tab.values())


# ---------------------------------------------------------------- V-BS-8 선형성·결정성
def test_linearity_determinism_sha(G, tmp_path):
    g, norm, D, B = G
    X0 = g["mesh"]["x0"]
    nom = B.nominal()
    vals = {"B1_D1": 24.0, "B1_D2": 12.5, "B1_W": nom["B1_W"] + 3.0, "B2_D1": 7.0, "B2_W": 42.0}
    x = bs.morph(X0, B, vals)
    acc = np.zeros_like(X0)
    for k, v in vals.items():
        acc += bs.morph(X0, B, {k: v}) - X0
    assert np.allclose(x - X0, acc, atol=1e-12, rtol=0)
    # 같은 선택 2회 → basis.npz 바이트 동일
    p1, p2 = str(tmp_path / "a.npz"), str(tmp_path / "b.npz")
    bs.save_basis(p1, B)
    D2 = bs.derive_obj(g["mesh"], bs.normalize_input(sb.selection(g), CFG), CFG, fixed_node_ids=g["fixed_ids"])
    bs.save_basis(p2, bs.basis(g["mesh"], D2, CFG))
    assert U.sha256_file(p1) == U.sha256_file(p2)
    B3 = bs.load_basis(p1)
    assert np.array_equal(bs.morph(X0, B3, vals), x)
    blob = bs.basis_bin(B3)
    n0 = int(np.frombuffer(blob[:4], "<u4")[0])
    assert n0 == B3.vars[0]["idx"].size and len(blob) == sum(4 + 16 * v["idx"].size for v in B3.vars)
    # 행 순서·구간 표기 바꿔도 sha 동일
    sel = sb.selection(g)
    sel2 = sb.selection(g)
    sel2["beads"] = sel2["beads"][::-1]
    r = sel2["beads"][1]["tiers"][0]["floor"]["q"]
    split = []
    for f, l in r:
        if l > f:
            split += [[f, f], [f + 1, l]]
        else:
            split.append([f, l])
    sel2["beads"][1]["tiers"][0]["floor"]["q"] = split[::-1]
    sel2["beads"][1]["tiers"] = sel2["beads"][1]["tiers"][::-1]
    assert bs.selection_sha256(bs.normalize_input(sel, CFG)) == bs.selection_sha256(bs.normalize_input(sel2, CFG))
