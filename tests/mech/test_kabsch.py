"""T-KB-1·2 (esl.md V-KB-1·2, 전 노드 기준)."""
import numpy as np
import pytest

from esl.errors import EslError
from esl.mech import kabsch
from meshes import rect_quads, rot_matrix


def _nodes():
    X, _, _ = rect_quads(800.0, 500.0, 16, 10)
    X[:, 2] = 30 * np.sin(X[:, 0] / 200.0)
    return X + [1500.0, -300.0, 700.0]


@pytest.mark.parametrize("ang", [1e-7, 0.3, 2.5, np.pi - 1e-3])
def test_recover_deformation(ang):
    X0 = _nodes()
    rng = np.random.default_rng(1)
    c = X0.mean(0)
    # 알려진 변형: 강체 성분이 없도록 선형 강체를 최소제곱 제거해 둔다
    d = 2.0 * np.c_[np.sin(X0[:, 0] / 300), np.cos(X0[:, 1] / 250), (X0[:, 0] - c[0]) ** 2 / 4e5] + 0.1 * rng.standard_normal(X0.shape)
    d, *_ = kabsch.remove_linear_rigid(X0, d)
    # 유한 회전 기준으로도 강체 0 이 되도록: Kabsch 로 한 번 정규화
    d, *_ = kabsch.remove_rigid(X0, d)
    R = rot_matrix([0.3, -1.0, 0.7], ang)
    t = np.array([2000.0, -150.0, 45.0])
    x = (X0 + d) @ R.T + t
    u = x - X0
    u_rel, Rf, tf, info = kabsch.remove_rigid(X0, u)
    assert np.abs(u_rel - d).max() < 1e-9 * np.abs(u).max()
    assert np.allclose(Rf, R, atol=1e-10)
    assert abs(np.linalg.det(Rf) - 1) < 1e-12
    assert info["rot_deg"] == pytest.approx(np.degrees(ang), rel=1e-6, abs=1e-9)
    assert info["max_def"] == pytest.approx(np.linalg.norm(d, axis=1).max(), rel=1e-9)


def test_pure_rigid_zero_residual():
    X0 = _nodes()
    R = rot_matrix([1, 2, 3], 1.1)
    t = np.array([1e3, 2e3, -5e2])
    u = X0 @ R.T + t - X0
    u_rel, Rf, tf, info = kabsch.remove_rigid(X0, u)
    assert np.abs(u_rel).max() < 1e-12 * np.abs(u).max()
    R2, t2, inf2 = kabsch.fit(X0, X0 + u)
    assert np.allclose(R2, R, atol=1e-13) and np.allclose(t2, t, atol=1e-9)
    assert inf2["rms"] < 1e-9


def test_reflection_prevented():
    X0 = _nodes()
    M = np.diag([1.0, 1.0, -1.0])           # 반사
    x = X0 @ M.T
    R, t, info = kabsch.fit(X0, x)
    assert np.linalg.det(R) == pytest.approx(1.0)
    assert info["reflection_corrected"]
    Rr, _, inf = kabsch.fit(X0, x, allow_reflection=True)
    assert np.linalg.det(Rr) == pytest.approx(-1.0)
    assert inf["rms"] < 1e-9


def test_degenerate():
    with pytest.raises(EslError) as e:
        kabsch.fit(np.zeros((2, 3)), np.zeros((2, 3)))
    assert e.value.code == "KABSCH_DEGENERATE"
    line = np.outer(np.linspace(0, 1, 10), [1.0, 2.0, 3.0])
    with pytest.raises(EslError) as e:
        kabsch.fit(line, line + 1)
    assert e.value.code == "KABSCH_DEGENERATE"
    with pytest.raises(EslError) as e:
        kabsch.remove_rigid(line, np.zeros_like(line))
    assert e.value.code == "KABSCH_DEGENERATE"
