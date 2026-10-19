"""T-SUP-1."""
import numpy as np
import pytest

from esl.errors import EslError
from esl.mech import supports
from esl.mech.shell import ShellModel
from meshes import rect_quads, rot_matrix


def _tilted_plate():
    X, c, t = rect_quads(600.0, 250.0, 24, 10, distort=0.2, seed=3)
    R = rot_matrix([0.4, 1.0, -0.6], 0.8)
    return X, X @ R.T + [100.0, 200.0, -50.0], c, t


def test_pca_corners_tilted_plate():
    X, Xg, c, t = _tilted_plate()
    res = supports.pca_corners(Xg)
    L, B = 600.0, 250.0
    corners = {int(np.flatnonzero(np.isclose(X[:, 0], a) & np.isclose(X[:, 1], b))[0])
               for a in (0, L) for b in (0, B)}
    assert set(res["idx"]) == corners and len(res["idx"]) == 4
    pl = res["plane"]
    n = np.array(pl["n"])
    assert np.allclose(np.cross(pl["e1"], pl["e2"]), n)
    assert np.abs((Xg - pl["origin"]) @ n).max() < 1e-9


def test_pick_321_nonsingular_and_solves():
    X, Xg, c, t = _tilted_plate()
    idx = supports.pca_corners(Xg)["idx"]
    spc = supports.pick_321(Xg, idx)
    assert [len(d) for _, d in spc] == [3, 2, 1]
    assert len({p for p, _ in spc}) == 3
    m = ShellModel(Xg, c, t, 1.0, 2.1e5, 0.3)
    F = np.zeros((m.n_nodes, 3))
    F[5] = Xg[-7] - Xg[5]           # 두 점을 잇는 방향의 맞힘 → 자기평형
    F[-7] = -F[5]
    u, R = m.solve(F, spc)
    assert np.isfinite(u).all()
    assert np.abs(R).max() < 1e-9 * np.abs(F).max()       # 자기평형 하중 → 반력≈0


def test_pick_321_degenerate():
    X, Xg, c, t = _tilted_plate()
    row = np.flatnonzero(np.isclose(X[:, 1], 0.0))[:6]      # 공선 후보
    with pytest.raises(EslError) as e:
        supports.pick_321(Xg, row)
    assert e.value.code == "SUPPORT_DEGENERATE"
    with pytest.raises(EslError) as e:
        supports.pick_321(Xg, [0, 1])
    assert e.value.code == "SUPPORT_DEGENERATE"


def test_pca_duplicate_corner_fallback():
    # 삼각형 꼴 점군: 한 노드가 두 방향의 극점 → 차순위로 대체, 4개 서로 다름
    P = np.array([[0, 0, 0], [10, 0, 0], [5, 8, 0], [5, 1, 0], [4, 4, 0], [6, 4, 0]], float)
    res = supports.pca_corners(P)
    assert len(set(res["idx"])) == 4
