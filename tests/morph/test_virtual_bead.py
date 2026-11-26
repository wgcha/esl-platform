"""V-0250-VB-1·2·3·4 — 가상 비드 순수 모듈(esl/morph/virtual_bead.py)·기저 항(core.basis_term) 단위 시험
(계약 esl_virtual_bead.md §3·§4·§12)."""
import ast
import math
import os
import sys

import numpy as np
import pytest

from esl.morph import core as mcore
from esl.morph import virtual_bead as vbm

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "doe"))
import synth_vbead as sv  # noqa: E402

NH = np.array([0.0, 0.0, 1.0])


def _plate_field(theta, end="round", r=0.0, d_max=6.0, w=20.0):
    m = sv.uniform(2.0, (300.0, 200.0))
    X = m["x0"]
    p0, p1 = np.array([90.0, 100.0, 0.0]), np.array([210.0, 100.0, 0.0])
    line = vbm.resolve_line(p0, p1, None, None, None, (p0, NH))
    fp = vbm.footprint(X, (*line, NH), w, theta, d_max, end, r, 3.0)
    idx = np.flatnonzero(fp["move_mask"])
    nrm = vbm.node_normals(X, m["conn"], m["elem_type"], np.ones(m["conn"].shape[0], bool), NH)[idx]
    fd = vbm.field(fp["d"][idx], nrm, 1, w, theta, r, idx=idx)
    return m, fp, fd


@pytest.mark.parametrize("theta", [45.0, 60.0])
@pytest.mark.parametrize("end", ["round", "square"])
def test_field_exact_r0_v1(theta, end):
    """V-0250-VB-1: 면내 0, 깊이면 = D, 사면 = D − (d − W/2)tanθ(> 0), 입구 밖 0, D = 0 → 0(정확), D 단조."""
    m, fp, fd = _plate_field(theta, end)
    d = fp["d"][fd["idx"]]
    tn = math.tan(math.radians(theta))
    prev = None
    for D in (0.0, 3.0, 6.0):
        u = vbm.displacement(fd, D)
        assert np.abs(u[:, :2]).max() <= 1e-12
        if D == 0.0:
            assert not np.any(u)                                     # 정확히 0
        top = d <= 10.0
        assert np.allclose(u[top, 2], D, atol=1e-12, rtol=0)
        want = np.maximum(0.0, D - np.maximum(0.0, d - 10.0) * tn)
        assert np.allclose(u[:, 2], want, atol=1e-12, rtol=0)
        if prev is not None:
            assert np.all(u[:, 2] >= prev - 1e-15)                    # 단조
        prev = u[:, 2]
    # 발자국 밖 노드는 기저에 없음 = 0, 경계(d_move) 노드 값 0
    assert np.all(fp["d"][fd["idx"]] < fp["d_move"])
    assert fp["d_move"] == pytest.approx(10.0 + 6.0 / tn)                            # r 0 = c 0 → 보상 없음(개정 1 식)


def test_field_rounded_c1_v1():
    """r > 0: D = 0 → 0 정확, 둥글림 구간 연속(C¹ — 수치 미분 차 ≤ 1e-6)."""
    for theta in (45.0, 60.0):
        _m, _fp, fd = _plate_field(theta, r=2.0)
        assert not np.any(vbm.displacement(fd, 0.0))
        a, c = vbm.edge_a(2.0, theta), vbm.edge_c(2.0, theta)
        assert a > 0 and c > 0
        for fn, k in ((vbm.ramp, c), (vbm.q_round, a)):
            for t0 in (-k, k):
                e = 1e-7
                left = (fn(t0, k) - fn(t0 - e, k)) / e
                right = (fn(t0 + e, k) - fn(t0, k)) / e
                assert abs(float(left) - float(right)) <= 1e-6
                assert abs(float(fn(t0 + 1e-12, k)) - float(fn(t0 - 1e-12, k))) <= 1e-9
        # 단조(D)
        u = [vbm.displacement(fd, D)[:, 2] for D in (0.0, 1.0, 3.0, 6.0)]
        assert all(np.all(b >= a - 1e-15) for a, b in zip(u, u[1:]))


def test_basis_term_v2():
    """V-0250-VB-2: linear 항 = (v − v₀)·vec(같은 바이트), hinge 항 = §4.1 식, 여러 변수 합 = 개별 합."""
    rng = np.random.default_rng(1)
    vec = rng.normal(size=(50, 3))
    idx = np.arange(50, dtype=np.int32)
    lin = {"name": "B1_D", "nominal": 2.5, "idx": idx, "vec": vec}
    i, du = mcore.basis_term(lin, 3.7)
    assert du.tobytes() == ((3.7 - 2.5) * vec).tobytes() and i is idx
    g = rng.uniform(0, 5, size=50)
    nv = np.tile([0.0, 0.0, -1.0], (50, 1))
    hv = {"name": "A1_A", "nominal": 0.0, "idx": idx, "vec": nv, "form": "hinge", "g": g, "c": 0.0}
    _i, du = mcore.basis_term(hv, 3.0)
    assert np.allclose(du[:, 2], -np.maximum(0.0, 3.0 - g), atol=1e-12, rtol=0)
    from esl.doe import bead_select as bs
    B = bs.Basis([dict(lin), dict(hv)], 50, "x")
    x0 = np.zeros((50, 3))
    both = bs.morph(x0, B, {"B1_D": 3.7, "A1_A": 3.0})
    sep = bs.morph(x0, B, {"B1_D": 3.7}) + bs.morph(x0, B, {"A1_A": 3.0})
    assert np.allclose(both, sep, atol=1e-12)


def _grid_masks():
    m = sv.uniform(5.0, (200.0, 100.0))
    ne, nn = m["conn"].shape[0], m["x0"].shape[0]
    return m, {"host": np.ones(ne, bool), "bead": np.zeros(ne, bool), "island": np.zeros(ne, bool),
               "exclude": np.zeros(ne, bool), "other_vb": np.zeros(ne, bool), "hole_nodes": np.zeros(nn, bool),
               "edge_nodes": np.zeros(nn, bool), "fixed_nodes": np.zeros(nn, bool)}


def test_host_check_each_code_v3():
    """V-0250-VB-3: 사유마다 위반 1개 → 그 코드만(순서 고정), 위반 없음 → [], 여러 개 → 전부 HOST_REASONS 순서."""
    m, base = _grid_masks()
    X = m["x0"]
    p0, p1 = np.array([60.0, 50.0, 0.0]), np.array([140.0, 50.0, 0.0])
    line = vbm.resolve_line(p0, p1, None, None, None, (p0, NH))
    fp = vbm.footprint(X, (*line, NH), 10.0, 45.0, 4.0, "round", 0.0, 3.0)
    chk = vbm.chk_elems(m["conn"], m["elem_type"], fp["chk_mask"])
    e_in = int(np.flatnonzero(chk)[0])
    n_in = int(np.flatnonzero(fp["chk_mask"])[0])
    assert vbm.host_check(m["conn"], chk, base) == []
    cases = {"VB_NOT_ON_PLATE": ("host", e_in, False), "VB_OVER_BEAD": ("bead", e_in, True),
             "VB_OVER_ISLAND": ("island", e_in, True), "VB_OVER_HOLE": ("hole_nodes", n_in, True),
             "VB_PLATE_EDGE": ("edge_nodes", n_in, True), "VB_FIXED": ("fixed_nodes", n_in, True),
             "VB_OVER_VBEAD": ("other_vb", e_in, True), "VB_EXCLUDED": ("exclude", e_in, True)}
    for code, (k, i, val) in cases.items():
        mk = {kk: v.copy() for kk, v in base.items()}
        mk[k][i] = val
        if k in ("bead", "island", "exclude"):
            mk["host"][i] = False                            # 비드·섬·제외 요소는 host 아님 — 그래도 구체 사유 1개만
        assert vbm.host_check(m["conn"], chk, mk) == [code], code
    mk = {kk: v.copy() for kk, v in base.items()}
    mk["fixed_nodes"][n_in] = mk["hole_nodes"][n_in] = True
    mk["bead"][e_in], mk["host"][e_in] = True, False
    assert vbm.host_check(m["conn"], chk, mk) == ["VB_OVER_BEAD", "VB_OVER_HOLE", "VB_FIXED"]
    assert list(vbm.HOST_REASONS) == [c for c in vbm.REASONS if c in vbm.HOST_REASONS]


def test_margin_boundary_flips_v3():
    """margin 경계(d_chk ± 0.1)에서 판정이 뒤집힘(고정 노드 1개를 경계 안·밖에)."""
    m, base = _grid_masks()
    X = m["x0"].copy()
    p0, p1 = np.array([60.0, 50.0, 0.0]), np.array([140.0, 50.0, 0.0])
    line = vbm.resolve_line(p0, p1, None, None, None, (p0, NH))
    fp0 = vbm.footprint(X, (*line, NH), 10.0, 45.0, 4.0, "round", 0.0, 3.0)
    k = int(np.argmin(np.abs(X[:, 1] - 80.0) + np.abs(X[:, 0] - 100.0)))   # (100, 80) 노드를 옮김
    out = []
    for dy in (-0.1, 0.1):
        Xk = X.copy()
        Xk[k, 1] = 50.0 + fp0["d_chk"] + dy
        fp = vbm.footprint(Xk, (*line, NH), 10.0, 45.0, 4.0, "round", 0.0, 3.0)
        mk = {kk: v.copy() for kk, v in base.items()}
        mk["fixed_nodes"][k] = True
        chk = vbm.chk_elems(m["conn"], m["elem_type"], fp["chk_mask"])
        out.append(vbm.host_check(m["conn"], chk, mk))
    assert out == [["VB_FIXED"], []]


def test_resolution_v4():
    """V-0250-VB-4: run 4(d_max 4·θ 45) — h 5 = COARSE, h 3 = WALL_COARSE n_wall 1.33, h 1.5 = 경고 없음; W_top 경계."""
    r5 = vbm.resolution(5.0, 20.0, 45.0, 4.0, 2.0)
    assert r5["codes"] == ["VB_MESH_COARSE"]
    r3 = vbm.resolution(3.0, 20.0, 45.0, 4.0, 2.0)
    assert r3["codes"] == [] and r3["warns"] == [{"code": "VB_WALL_COARSE", "n_wall": 1.33}]
    r15 = vbm.resolution(1.5, 20.0, 45.0, 4.0, 2.0)
    assert r15["codes"] == [] and r15["warns"] == []
    assert vbm.resolution(3.0, 2.99, 45.0, 9.0, 2.0)["codes"] == ["VB_MESH_COARSE"]       # W_top < h
    assert vbm.resolution(3.0, 3.0, 45.0, 9.0, 2.0)["warns"] == [{"code": "VB_TOP_NARROW", "n_top": 1.0}]
    assert vbm.resolution(3.0, 6.0, 45.0, 9.0, 2.0)["warns"] == []                         # W_top = 2h 경고 없음
    assert vbm.resolution(3.0, 5.99, 45.0, 9.0, 2.0)["warns"][0]["code"] == "VB_TOP_NARROW"


def test_resolve_line_forms():
    """(a) 두 점 · (b) 시작점 + 길이 + 각도(+ξ 기준 +η 쪽) — 같은 선, 길이 0 = VB_INPUT_INVALID."""
    ph = np.zeros(3)
    a = vbm.resolve_line([0, 0, 0.3], [30, 40, -0.2], None, None, None, (ph, NH))
    b = vbm.resolve_line([0, 0, 0.3], None, 50.0, math.degrees(math.atan2(40, 30)), ([1, 0, 0], [0, 1, 0]), (ph, NH))
    assert np.allclose(a[1], b[1], atol=1e-9) and a[3] == pytest.approx(50.0) and a[0][2] == 0.0
    c = vbm.resolve_line([0, 0, 0], None, 10.0, 90.0, ([1, 0, 0], [0, -1, 0]), (ph, NH))   # frame 손잡이 보존
    assert np.allclose(c[2], [0, -1, 0], atol=1e-12)
    with pytest.raises(ValueError):
        vbm.resolve_line([1, 1, 0], [1, 1, 0], None, None, None, (ph, NH))


def test_pure_imports():
    """§4.3: numpy 만 — esl.doe·beadgraph·esl.mesh import 금지, IO 없음."""
    src = open(vbm.__file__, encoding="utf-8").read()
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
    assert mods <= {"__future__", "math", "numpy"}, mods
    calls = {n.func.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "open" not in calls


def test_hash_view_keys():
    from esl.doe import DEFAULTS
    hv = vbm.hash_view({"schema": 1, **DEFAULTS["virtual_bead"]})
    assert set(hv) == set(vbm.HASH_KEYS) | {"vb_rules"} and hv["vb_rules"] == vbm.VB_RULES
    assert vbm.hash_view(None) is None


# ---------------------------------------------------------------- 개정 3 (§19.9.1) — V-0250-VB-29·30
@pytest.mark.parametrize("c", [0.0, 0.106, 1.243, 3.0])
def test_depth_eff_v29(c):
    """e(0) = 0 정확, 깊이면 노드 F_c(e(D)) − F_c(0) = D ± 1e-12, 3c/4 에서 값·기울기 연속, 단조, c 0 → e = D(비트 같음)."""
    assert vbm.depth_eff(0.0, c) == 0.0
    for D in ([0.1 * c, 0.5 * c, 0.75 * c, c, 6.0] if c else [0.3, 6.0]):
        top = float(vbm.ramp(vbm.depth_eff(D, c), c) - vbm.ramp(0.0, c))
        assert abs(top - D) <= 1e-12, (c, D, top)
        assert float(vbm.hinge(np.zeros(1), c, D)[0]) == pytest.approx(D, abs=1e-12)
    if c:
        k, e = 0.75 * c, 1e-7
        assert abs(vbm.depth_eff(k - 1e-12, c) - vbm.depth_eff(k + 1e-12, c)) <= 1e-9
        left = (vbm.depth_eff(k, c) - vbm.depth_eff(k - e, c)) / e
        right = (vbm.depth_eff(k + e, c) - vbm.depth_eff(k, c)) / e
        assert abs(left - right) <= 1e-6
        vs = np.linspace(0, 3 * c, 301)
        ev = [vbm.depth_eff(v, c) for v in vs]
        assert all(b > a for a, b in zip(ev, ev[1:]))
    else:
        for D in (0.1, 2.5, 6.0):
            assert vbm.depth_eff(D, 0.0) == D


@pytest.mark.parametrize("theta", [45.0, 60.0])
def test_field_compensated_plate_v29(theta):
    """합성 평판 h 3·r = h: 깊이면 노드 법선 변위 = D ± 1e-12, 최대 변위 = 깊이면, 직선 사면 기울기 = tanθ, 면내 0."""
    m = sv.uniform(3.0, (300.0, 200.0))
    X = m["x0"]
    p0, p1 = np.array([90.0, 100.0, 0.0]), np.array([210.0, 100.0, 0.0])
    line = vbm.resolve_line(p0, p1, None, None, None, (p0, NH))
    r = 3.0
    fp = vbm.footprint(X, (*line, NH), 20.0, theta, 6.0, "round", r, 3.0)
    idx = np.flatnonzero(fp["move_mask"])
    fd = vbm.field(fp["d"][idx], np.tile(NH, (idx.size, 1)), 1, 20.0, theta, r, idx=idx)
    d = fp["d"][idx]
    tn = math.tan(math.radians(theta))
    for D in (0.2, 3.0, 6.0):
        u = vbm.displacement(fd, D)
        assert np.abs(u[:, :2]).max() == 0.0
        top = fd["g"] == 0.0
        assert top.any() and np.allclose(u[top, 2], D, atol=1e-12, rtol=0)
        assert u[:, 2].max() <= D + 1e-12
    u = vbm.displacement(fd, 6.0)[:, 2]
    a, c = vbm.edge_a(r, theta), vbm.edge_c(r, theta)
    sl = (d > 10.0 + a + 1e-6) & (u > c + 1e-6) & (u < 6.0 - 1e-6)                 # 직선 사면(둥글림 밖)
    if sl.sum() >= 2:
        k = np.argsort(d[sl])
        dd, uu = d[sl][k], u[sl][k]
        slope = -(uu[-1] - uu[0]) / (dd[-1] - dd[0])
        assert slope == pytest.approx(tn, rel=1e-9)


def test_footprint_r_cap_v30():
    """d_move = W/2 + (e(d_max) + c)·cotθ ± 1e-9, D = d_max 에서 d ≥ d_move 변위 0·바로 안쪽 > 0, r₂ 계수 0.75."""
    for theta, r in ((45.0, 3.0), (60.0, 1.5)):
        m = sv.uniform(0.25, (60.0, 40.0))
        X = m["x0"]
        p0, p1 = np.array([20.0, 20.0, 0.0]), np.array([40.0, 20.0, 0.0])
        line = vbm.resolve_line(p0, p1, None, None, None, (p0, NH))
        c = vbm.edge_c(r, theta)
        want = 5.0 + (vbm.depth_eff(4.0, c) + c) / math.tan(math.radians(theta))
        fp = vbm.footprint(X, (*line, NH), 10.0, theta, 4.0, "round", r, 0.0)
        assert fp["d_move"] == pytest.approx(want, abs=1e-9)
        idx = np.arange(X.shape[0])
        fd = vbm.field(fp["d"], np.tile(NH, (idx.size, 1)), 1, 10.0, theta, r, idx=idx)
        u = vbm.displacement(fd, 4.0)[:, 2]
        assert np.all(u[fp["d"] >= fp["d_move"]] == 0.0)
        inner = (fp["d"] < fp["d_move"]) & (fp["d"] > fp["d_move"] - 0.3)
        assert inner.any() and np.all(u[inner] > 0.0)
    th = math.radians(45.0)
    r2 = 4.0 / math.tan(th) / (math.sin(th) / 2 + 0.75 * math.tan(th / 2))
    assert vbm.r_cap(100.0, 45.0, 4.0) == pytest.approx(r2) and vbm.r_cap(3.0, 45.0, 30.0) == pytest.approx(3.0 / math.sin(th))


def test_theta_field_and_consts():
    assert vbm.theta_field(60.0, 60.0) == pytest.approx(59.99) and vbm.theta_field(45.0, 60.0) == 45.0
    assert vbm.VB_RULES == 3 and vbm.VB_HOST_SEG_TYPES == ("base", "area", "plateau") and vbm.VB_FLIP_EPS_DEG == 0.01


def test_host_check_edge_skip_v22():
    """§19.3-2: 평탄부 테두리 transition 에 닿으면 VB_PLATE_EDGE 만(그 너머 부모 floor 는 다른 사유로 안 셈)."""
    m, base = _grid_masks()
    X = m["x0"]
    p0, p1 = np.array([60.0, 50.0, 0.0]), np.array([140.0, 50.0, 0.0])
    line = vbm.resolve_line(p0, p1, None, None, None, (p0, NH))
    fp = vbm.footprint(X, (*line, NH), 10.0, 45.0, 4.0, "round", 0.0, 3.0)
    chk = vbm.chk_elems(m["conn"], m["elem_type"], fp["chk_mask"])
    e = np.flatnonzero(chk)
    mk = {k: v.copy() for k, v in base.items()}
    edge = np.zeros_like(mk["host"])
    skip = np.zeros_like(mk["host"])
    edge[e[0]], skip[e[1]] = True, True
    mk["host"][e[:2]] = False
    mk["bead"][e[:2]] = True                                                          # 테두리 벽·부모 floor 가 비드 라벨이어도
    assert vbm.host_check(m["conn"], chk, {**mk, "edge": edge, "skip": skip}) == ["VB_PLATE_EDGE"]
    assert "VB_OVER_BEAD" in vbm.host_check(m["conn"], chk, {**mk, "edge": np.zeros_like(edge), "skip": skip})
