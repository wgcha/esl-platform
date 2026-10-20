"""P2 §1 정규화 좌표계·격자 요약: 축 부호 고정, 메시 무관성, 합력·합모멘트 항등식, 메시 밀도 수렴."""
import numpy as np
import pytest

import synth_lib
from esl.library import normalize as nz


def _rot(axis, ang):
    return synth_lib.synth_case.rot(axis, ang)


def test_frame_axes_signs_and_orthonormal():
    X0, conn, et, _ = synth_lib.plate_xz(24, 16)
    fr = nz.frame(X0, None, conn, et)
    R = nz.rotation(fr)
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-12)
    assert np.allclose(np.cross(R[0], R[1]), R[2], atol=1e-12)
    assert R[0] @ [1, 0, 0] > 0.99 and R[1] @ [0, 0, 1] > 0.99      # ξ≈+X, η≈+Z
    assert R[2] @ [0, -1, 0] > 0.99                                  # n = ξ×η = −Y
    assert abs(fr["L_xi"] - 300.0) < 1e-9 and abs(fr["L_eta"] - 200.0) < 1e-9
    loc = nz.local_coords(fr, X0)
    assert loc[:, 0].min() == pytest.approx(0, abs=1e-12) and loc[:, 0].max() == pytest.approx(1, abs=1e-12)


@pytest.mark.parametrize("ang", [0.0, 0.6, 2.8, -2.2])
def test_frame_sign_fixed_under_rotation_and_permutation(ang):
    """기울어진(평면 안 회전 ±160° 포함) 모델에서도 ξ 는 +X 쪽, η 는 +Z 쪽 (PCA 부호 뒤집힘 없음)."""
    X0, conn, et, _ = synth_lib.plate_xz(20, 12)
    Q = _rot([0, 1, 0], ang * 0.3) @ _rot([1, 0, 0], 0.15)          # 큰 각은 평면 안(Y축) 회전을 줄여 적용
    Xr = X0 @ Q.T
    fr = nz.frame(Xr, None, conn, et)
    assert np.asarray(fr["e_xi"]) @ [1, 0, 0] > 0 and np.asarray(fr["e_eta"]) @ [0, 0, 1] > 0
    perm = np.random.default_rng(1).permutation(X0.shape[0])
    inv = np.argsort(perm)
    fr2 = nz.frame(Xr[perm], None, inv[conn.clip(0)] * (conn >= 0) - (conn < 0), et)
    for k in ("origin", "e_xi", "e_eta", "n", "a_range", "b_range"):
        assert np.allclose(fr[k], fr2[k], atol=1e-9)


def test_frame_area_weighted_is_mesh_independent():
    """면적 가중 PCA: 같은 형상, 다른 메시 밀도 → 같은 좌표계 (절점 균등 가중은 다를 수 있음)."""
    frs = []
    for nx, ny, tc in ((12, 8, 1), (40, 26, 7)):
        X0, conn, et, _ = synth_lib.plate_xz(nx, ny, n_tria_cols=tc)
        # 판의 곡면은 메시 밀도에 따라 다각형 근사가 달라지므로 평판으로 비교(곡률 0)
        X0[:, 1] = 800.0
        frs.append(nz.frame(X0, None, conn, et))
    for k in ("origin", "e_xi", "e_eta", "n", "a_range", "b_range"):
        assert np.allclose(frs[0][k], frs[1][k], atol=1e-9), k


def test_grid_summary_identities():
    X0, conn, et, _ = synth_lib.plate_xz(30, 20)
    rng = np.random.default_rng(3)
    f = rng.normal(size=X0.shape)
    fr = nz.frame(X0, None, conn, et)
    gs = nz.grid_summary(X0, f, 7, 5, fr, top_n=10, node_id=np.arange(X0.shape[0]) + 100)
    R = nz.rotation(fr)
    assert np.allclose(gs["cell_F"].sum(axis=(0, 1)), f.sum(axis=0), atol=1e-10)
    o = np.asarray(fr["origin"])
    C = gs["cell_center"].reshape(-1, 3)
    Mtot = gs["cell_M"].reshape(-1, 3).sum(axis=0) + np.cross(C - o, gs["cell_F"].reshape(-1, 3)).sum(axis=0)
    assert np.allclose(Mtot, gs["total_M"], atol=1e-9 * np.abs(gs["total_M"]).max())
    assert np.allclose(gs["cell_F_loc"], gs["cell_F"] @ R.T, atol=1e-12)
    assert np.allclose(gs["cell_M_loc"], gs["cell_M"] @ R.T, atol=1e-12)
    assert gs["cell_n"].sum() == X0.shape[0]
    mag = np.linalg.norm(f, axis=1)
    assert np.allclose(gs["top_mag"], np.sort(mag)[::-1][:10])
    assert gs["top_node_id"][0] == 100 + int(np.argmax(mag))
    # 셀 중심은 정규화 좌표 (i+½)/nx, (j+½)/ny 의 평면 위 점
    loc = nz.local_coords(fr, gs["cell_center"].reshape(-1, 3)).reshape(7, 5, 3)
    assert np.allclose(loc[:, 0, 0], (np.arange(7) + 0.5) / 7) and np.allclose(loc[0, :, 1], (np.arange(5) + 0.5) / 5)
    assert np.allclose(loc[..., 2], 0.0, atol=1e-9)


def _flat_case(nx, ny, n_tria_cols=0):
    X0, conn, et, _ = synth_lib.plate_xz(nx, ny, n_tria_cols=n_tria_cols)
    X0[:, 1] = 800.0
    fr = nz.frame(X0, None, conn, et)
    loc = nz.local_coords(fr, X0)
    A = nz.node_areas(X0, conn, et)
    xi, eta = loc[:, 0], loc[:, 1]
    q = np.stack([np.sin(2 * np.pi * eta) * (1 + xi), 0.5 * np.cos(np.pi * xi), 1 + 2 * xi * eta], axis=1)
    return X0, fr, (q @ nz.rotation(fr)) * A[:, None]


def test_mesh_independence_cell_resultants_converge():
    """같은 형상·매끄러운 하중장, 메시 밀도만 다름 → 셀 합력이 기준(매우 조밀)으로 수렴."""
    gx, gy = 6, 4
    ref = None
    errs = []
    for nx, ny in ((240, 160), (30, 20), (60, 40), (120, 80)):
        X0, fr, f = _flat_case(nx, ny, n_tria_cols=nx // 6)
        gs = nz.grid_summary(X0, f, gx, gy, fr)
        if ref is None:
            ref = gs
            continue
        scale = np.abs(ref["cell_F_loc"]).max()
        errs.append(np.abs(gs["cell_F_loc"] - ref["cell_F_loc"]).max() / scale)
    assert errs[1] < 0.7 * errs[0] and errs[2] < 0.7 * errs[1], errs
    assert errs[2] < 0.03, errs
    # 같은 밀도·다른 요소 구성(QUAD/TRIA 혼합 비율)도 같은 셀 합력 (기여 면적 균등 분배라 1차 수렴)
    X1, fr1, f1 = _flat_case(120, 80, 0)
    X2, fr2, f2 = _flat_case(120, 80, 60)
    a = nz.grid_summary(X1, f1, gx, gy, fr1)["cell_F_loc"]
    b = nz.grid_summary(X2, f2, gx, gy, fr2)["cell_F_loc"]
    assert np.abs(a - b).max() / np.abs(a).max() < 0.02
