"""P2 §3 매핑: 셀(그룹)별 합력·합모멘트 보존 1e-10, 최소노름, 병합(노드<3·공선·빈 셀), 평형 보정, 회전 불변."""
import numpy as np
import pytest

import synth_lib
from esl.errors import EslError
from esl.library import mapping as mp
from esl.library import normalize as nz

TOL = 1e-10


def _case(nx, ny, scale=1.0, pattern="A", tc=2):
    X0, conn, et, _ = synth_lib.plate_xz(nx, ny, scale, n_tria_cols=tc)
    fr = nz.frame(X0, None, conn, et)
    f = synth_lib.pattern_load(X0, conn, et, pattern, fr)
    return X0, conn, et, fr, f


def _summary(X0, f, fr, gx, gy):
    gs = nz.grid_summary(X0, f, gx, gy, fr)
    return {**gs, "nx": gx, "ny": gy, "frame": fr}


def _check_cells(src, Xt, frt, Fcells, merged, tol=TOL):
    """병합되지 않은 셀: 대상에서 다시 잰 셀 합력·합모멘트(국부) = 원본. 반환 비교한 셀 수."""
    gx, gy = src["nx"], src["ny"]
    tg = nz.grid_summary(Xt, Fcells, gx, gy, frt)
    skip = {tuple(c) for g in merged for c in g["cells"]}
    n = 0
    Lc = np.sqrt(frt["L_xi"] * frt["L_eta"] / (gx * gy))
    scale = np.abs(src["cell_F_loc"]).max() + np.abs(src["cell_M_loc"]).max() / Lc
    for i in range(gx):
        for j in range(gy):
            if (i, j) in skip:
                continue
            dF = np.abs(tg["cell_F_loc"][i, j] - src["cell_F_loc"][i, j]).max()
            dM = np.abs(tg["cell_M_loc"][i, j] - src["cell_M_loc"][i, j]).max() / Lc
            assert (dF + dM) / scale < tol, (i, j, dF, dM)
            n += 1
    return n


def test_self_mapping_reproduces_cells():
    X0, conn, et, fr, f = _case(40, 28)
    src = _summary(X0, f, fr, 8, 6)
    F, info = mp.to_target(src, X0, fr, {"equilibrate": False})
    assert info["conservation_rel_max"] < TOL and info["merged_groups"] == []
    assert _check_cells(src, X0, fr, F, []) == 48
    # 최소노름: 각 셀 해는 제약 행렬 행공간 안 (영공간 성분 0)
    i, j, _ = nz.cell_index(fr, X0, 8, 6)
    sel = np.flatnonzero((i == 3) & (j == 2))
    C = nz.cell_centers(fr, 8, 6)[3, 2]
    f2, _ = mp.min_norm_forces(X0[sel], src["cell_F"][3, 2], src["cell_M"][3, 2], C)
    assert np.allclose(f2, F[sel], atol=1e-12 * np.abs(F).max())
    assert np.linalg.norm(F[sel]) <= np.linalg.norm(f[sel]) + 1e-12      # 원본도 같은 제약을 만족 → 최소노름 ≤


def test_cross_mesh_and_size_conservation():
    """원본(조밀, 1.2배) → 대상(성긴, 1.0배): 셀 합력·합모멘트 보존 1e-10, 병합 셀은 그룹 보존."""
    Xs, cs, es, frs, fs = _case(48, 32, 1.2, "B", tc=6)
    Xt, ct, et, frt, _ = _case(26, 17, 1.0, "A", tc=3)
    src = _summary(Xs, fs, frs, 12, 7)
    F, info = mp.to_target(src, Xt, frt, {"equilibrate": True})
    assert info["conservation_rel_max"] < TOL
    assert _check_cells(src, Xt, frt, info["F_cells"], info["merged_groups"]) >= 40
    # 평형 보정 후 전체 합력·합모멘트 ≈ 0 (원본 자기평형)
    assert info["equilibrium_after"]["force_rel"] < 1e-12 and info["equilibrium_after"]["moment_rel"] < 1e-12
    assert info["equilibrate_correction_rel"] < 1e-2
    # 전체 합력은 보정 전에도 보존(셀 합력 합 = 원본 합 ≈ 0)
    assert np.linalg.norm(info["F_cells"].sum(axis=0)) <= 1e-10 * np.abs(fs).sum()


def test_merge_sparse_collinear_and_empty_cells():
    """대상 메시가 성겨 셀에 노드 <3·한 줄 + 구멍(빈 셀) → 인접 병합, 그룹 합력·합모멘트 보존, 총량 보존."""
    Xs, cs, es, frs, fs = _case(60, 40, 1.0, "A", tc=0)
    src = _summary(Xs, fs, frs, 24, 14)
    Xt, ct, et, frt, _ = _case(12, 8, 1.0, "A", tc=0)                   # 셀 336 > 노드 117
    F, info = mp.to_target(src, Xt, frt, {"equilibrate": False})
    assert len(info["merged_groups"]) > 0 and info["conservation_rel_max"] < TOL
    tot = np.abs(src["cell_F"]).sum()
    assert np.linalg.norm(F.sum(axis=0) - src["cell_F"].reshape(-1, 3).sum(axis=0)) < 1e-10 * tot
    o = np.asarray(frt["origin"])
    Mt = np.cross(Xt - o, F).sum(axis=0)
    C = nz.cell_centers(frt, 24, 14).reshape(-1, 3)
    Ms = (src["cell_M_loc"].reshape(-1, 3) @ nz.rotation(frt)
          + np.cross(C - o, src["cell_F_loc"].reshape(-1, 3) @ nz.rotation(frt))).sum(axis=0)
    assert np.linalg.norm(Mt - Ms) < 1e-10 * tot * frt["L_xi"]
    # 구멍: 대상 가운데 노드를 지운 메시(요소 연결은 매핑에 쓰지 않음 — 노드 좌표만)
    loc = nz.local_coords(frt, Xt)
    keep = ~((np.abs(loc[:, 0] - 0.5) < 0.2) & (np.abs(loc[:, 1] - 0.5) < 0.2))
    F2, info2 = mp.to_target(src, Xt[keep], frt, {"equilibrate": False})
    assert info2["n_cells_empty_loaded"] > 0 and info2["conservation_rel_max"] < TOL
    assert np.linalg.norm(F2.sum(axis=0) - src["cell_F"].reshape(-1, 3).sum(axis=0)) < 1e-10 * tot


def test_collinear_cell_is_merged():
    fr = nz.frame(np.array([[0, 0, 0], [10, 0, 0], [0, 0, 10], [10, 0, 10.0]]))
    # 2×1 격자: 셀 0 에는 한 줄(공선) 노드, 셀 1 에는 2D 분포 노드
    X = np.array([[1, 0, 2], [2, 0, 2], [3, 0, 2], [4, 0, 2],
                  [6, 0, 1], [9, 0, 1], [6, 0, 9], [9, 0, 9.0]])
    src = {"nx": 2, "ny": 1, "cell_F_loc": np.array([[[1.0, 2.0, 3.0]], [[0.0, 0.0, 0.0]]]),
           "cell_M_loc": np.array([[[0.5, -1.0, 2.0]], [[0.0, 0.0, 0.0]]]), "frame": fr}
    F, info = mp.to_target(src, X, fr, {"equilibrate": False})
    assert len(info["merged_groups"]) == 1 and info["conservation_rel_max"] < TOL
    assert np.allclose(F.sum(axis=0), np.array([1.0, 2.0, 3.0]) @ nz.rotation(fr), atol=1e-12)


def test_degenerate_whole_target_raises():
    X = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0.0], [3, 0, 1e-3]])
    fr = nz.frame(np.array([[0, 0, 0], [3, 0, 0], [0, 0, 1], [3, 0, 1.0]]))
    src = {"nx": 1, "ny": 1, "cell_F_loc": np.ones((1, 1, 3)), "cell_M_loc": np.ones((1, 1, 3)), "frame": fr}
    with pytest.raises(EslError) as e:
        mp.to_target(src, X[:2], fr)
    assert e.value.code == "MAPPING_DEGENERATE"


def test_geometric_moment_scale_keeps_equilibrium_for_similar_shapes():
    Xs, cs, es, frs, fs = _case(36, 24, 1.2, "A")
    Xt, ct, et, frt, _ = _case(30, 20, 1.0, "A")
    src = _summary(Xs, fs, frs, 6, 4)
    _, ip = mp.to_target(src, Xt, frt, {"equilibrate": False, "moment_scale": "preserve"})
    _, ig = mp.to_target(src, Xt, frt, {"equilibrate": False, "moment_scale": "geometric"})
    assert ig["moment_factor"] == pytest.approx(1 / 1.2, rel=1e-12)
    assert ig["equilibrium_before"]["moment_rel"] < 1e-10 < ip["equilibrium_before"]["moment_rel"]


def test_rotation_invariance():
    Xs, cs, es, frs, fs = _case(30, 20, 1.0, "B")
    src = _summary(Xs, fs, frs, 6, 4)
    Xt, ct, et, frt, _ = _case(22, 15, 1.1, "A")
    F1, _ = mp.to_target(src, Xt, frt)
    Q = synth_lib.synth_case.rot([0.3, 0.2, 0.9], 0.4)
    Xr = Xt @ Q.T + np.array([50.0, -20.0, 7.0])
    frr = nz.frame(Xr, {"xi": (Q @ [1, 0, 0]).tolist(), "eta": (Q @ [0, 0, 1]).tolist()}, ct, et)
    F2, _ = mp.to_target(src, Xr, frr)
    assert np.allclose(F2, F1 @ Q.T, atol=1e-10 * np.abs(F1).max())
