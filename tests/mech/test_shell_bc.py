"""v0.24.4 ShellModel 경계 확장(계약 esl_jig_case.md §4.2, V-0244-JIG-4): FactorizedSolve.solve(F, values) · factorize_bc(국부 틀
구속 + 접지 스프링) · BcSolve(반력·스프링 힘·평형·변환 공간 모드 연산자). 기존 경로(values None)는 산술 불변."""
from __future__ import annotations

import numpy as np
import pytest
from meshes import cylinder_panel, rect_quads

from esl.errors import EslError
from esl.mech import jig
from esl.mech.shell import ShellModel

E, NU = 2.1e5, 0.3


def _sm(P, C, et, t=1.0):
    return ShellModel(P, C, et, np.full(len(C), t), np.full(len(C), E), np.full(len(C), NU), backend="superlu")


@pytest.fixture(scope="module")
def plate():
    P, C, et = rect_quads(300.0, 200.0, 12, 8)
    sm = _sm(P, C, et)
    N = P.shape[0]
    J = np.array([0, 1, 9, 10, N - 1, N - 2, N - 10, N - 11], dtype=np.int64)
    J = np.unique(J)
    F = np.zeros((N, 3))
    F[N // 2, 2] = 10.0
    F[N // 3, 0] = 3.0
    F[N // 4, 1] = -2.0
    return {"sm": sm, "N": N, "J": J, "F": F, "P": P}


def _dense_reduced(sm, cons, F, v):
    """참조: 축소 연립 K_ff u_f = f_f − K_fc v 를 조밀 행렬로 직접 풂."""
    K = sm.K().toarray()
    N = sm.n_nodes
    fixed = np.array([6 * p + d for p, d in cons])
    free = np.setdiff1d(np.arange(6 * N), fixed)
    f = np.zeros(6 * N)
    f[(np.arange(N)[:, None] * 6 + np.arange(3)).ravel()] = F.ravel()
    u = np.zeros(6 * N)
    u[fixed] = v
    u[free] = np.linalg.solve(K[np.ix_(free, free)], f[free] - K[np.ix_(free, fixed)] @ v)
    R = (K @ u - f).reshape(N, 6)[:, :3]
    return u.reshape(N, 6), R


def test_factorized_values_none_is_old_path(plate):
    sm, J, F = plate["sm"], plate["J"], plate["F"]
    spc = [(int(i), "123") for i in J]
    h = sm.factorize(spc)
    u0, R0 = sm.solve(F, spc)
    u1, R1 = h.solve(F)
    assert np.array_equal(u0, u1) and np.array_equal(R0, R1)                 # 옛 경로 = 같은 비트
    u2, _ = h.solve(F, values=np.zeros(len(h.cons)))                        # 값 0 = 같은 해(반올림)
    assert np.allclose(u2, u1, rtol=0, atol=1e-12 * np.abs(u1).max())


def test_factorized_values_matches_dense_reduced(plate):
    sm, J, F = plate["sm"], plate["J"], plate["F"]
    h = sm.factorize([(int(i), "123") for i in J])
    v = np.random.default_rng(0).normal(size=len(h.cons)) * 0.1
    u, R = h.solve(F, values=v)
    ur, Rr = _dense_reduced(sm, h.cons, F, v)
    K = sm.K()
    fixed_ = np.array([6 * p + d for p, d in h.cons])
    free_ = np.setdiff1d(np.arange(6 * sm.n_nodes), fixed_)
    f6 = np.zeros(6 * sm.n_nodes)
    f6[(np.arange(sm.n_nodes)[:, None] * 6 + np.arange(3)).ravel()] = F.ravel()
    rhs = f6 - K @ np.where(np.isin(np.arange(6 * sm.n_nodes), fixed_), u.ravel(), 0.0)
    res = (K @ np.where(np.isin(np.arange(6 * sm.n_nodes), free_), u.ravel(), 0.0) - rhs)[free_]
    assert np.linalg.norm(res) <= 1e-12 * np.linalg.norm(rhs[free_])       # 축소 연립 K_ff u_f = f_f − K_fc v 잔차
    # 조밀 직접 해와의 차 = 문제 조건수 수준(옛 경로 solve(F, spc) 도 조밀 해와 ~1e-10 차) — 1e-9 상대
    assert np.abs(u - ur).max() <= 1e-9 * np.abs(ur).max()
    assert np.abs(R - Rr).max() <= 1e-9 * np.abs(Rr).max()
    fixed = np.array([6 * p + d for p, d in h.cons])
    assert np.allclose(u.ravel()[fixed], v, rtol=0, atol=1e-15)
    assert np.abs(F.sum(axis=0) + R.sum(axis=0)).max() <= 1e-8 * np.abs(R).sum()
    h.solve(np.zeros_like(F), values=v)                                      # F = 0 순수 변위(반력끼리 평형) — 평형 검사 통과
    with pytest.raises(EslError):
        h.solve(F, values=v[:-1])


def test_factorize_bc_axis_equals_spc(plate):
    sm, J, F = plate["sm"], plate["J"], plate["F"]
    h = sm.factorize([(int(i), "123") for i in J])
    hb = sm.factorize_bc((np.repeat(J, 3), np.tile(np.eye(3), (J.size, 1))))
    v = np.random.default_rng(1).normal(size=3 * J.size) * 0.05
    u0, R0 = h.solve(F, values=v)
    u1, R1, rc, fs = hb.solve(F, values=v)
    assert np.abs(u1 - u0).max() <= 1e-12 * np.abs(u0).max() and np.abs(R1 - R0).max() <= 1e-12 * np.abs(R0).max()
    assert np.allclose(rc, R0[np.repeat(J, 3), np.tile(np.arange(3), J.size)], rtol=0, atol=1e-12 * np.abs(R0).max())
    assert fs.size == 0 and hb.fixed_t.size == 3 * J.size and hb.free_t.size == 6 * plate["N"] - 3 * J.size


def test_factorize_bc_tilted_constraint_and_equilibrium(plate):
    sm, J, F = plate["sm"], plate["J"], plate["F"]
    rng = np.random.default_rng(2)
    D = rng.normal(size=(3 * J.size, 3))
    hb = sm.factorize_bc((np.repeat(J, 3), D))
    v = rng.normal(size=3 * J.size) * 0.01
    u, R, rc, _ = hb.solve(F, values=v)
    Dn = D / np.linalg.norm(D, axis=1)[:, None]
    assert np.abs(np.einsum("ri,ri->r", Dn, u[np.repeat(J, 3), :3]) - v).max() <= 1e-12 * max(np.abs(v).max(), 1.0)
    assert np.abs(F.sum(axis=0) + R.sum(axis=0)).max() <= 1e-8 * (np.abs(F).sum() + np.abs(R).sum())
    Rr = np.zeros_like(R)
    np.add.at(Rr, np.repeat(J, 3), rc[:, None] * Dn)                         # 행 반력 rc(d̂ 방향) 합 = 노드 반력
    assert np.abs(Rr - R).max() <= 1e-10 * np.abs(R).max()


def test_factorize_bc_spring_large_k_equals_prescribed(plate):
    sm, J, F = plate["sm"], plate["J"], plate["F"]
    rows = (np.repeat(J, 3), np.tile(np.eye(3), (J.size, 1)))
    h = sm.factorize([(int(i), "123") for i in J])
    g = np.random.default_rng(3).normal(size=3 * J.size) * 0.05
    up, Rp = h.solve(F, values=g)
    kd = sm._diag_blocks(0, 3)[J][:, np.arange(3), np.arange(3)].ravel()   # 노드 병진 대각 = diag
    hs = sm.factorize_bc((np.zeros(0, np.int64), np.zeros((0, 3))), springs=(rows[0], rows[1], 1e8 * kd))
    us, Rs, rc, fs = hs.solve(F, ground=g)
    assert np.abs(us - up).max() <= 1e-6 * np.abs(up).max()
    assert np.abs(fs - Rp[rows[0], np.tile(np.arange(3), J.size)]).max() <= 1e-6 * np.abs(Rp).max()   # 스프링 힘 → 반력
    assert not np.any(Rs) and rc.size == 0
    Ft = F.copy()
    np.add.at(Ft, rows[0], fs[:, None] * rows[1])
    assert np.abs(Ft.sum(axis=0)).max() <= 1e-8 * np.abs(Ft).sum()           # F + Σ f_s d̂ = 0(구속 없음)


def test_factorize_bc_rigid_prescribed_motion_passes_equilibrium(plate):
    """강체 이동만 강제(반력 ≈ 0) — 평형 검사 규모 = ‖K‖·max|u|(강제 운동 힘 규모)."""
    sm, P = plate["sm"], plate["P"]
    rows = (np.array([0, 0, 12], dtype=np.int64), np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, 0]]))
    Jn = np.unique(np.r_[plate["J"]])
    nd = np.r_[np.repeat(Jn, 1), rows[0]]
    dd = np.concatenate([np.tile([0.0, 0.0, 1.0], (Jn.size, 1)), rows[1]])
    hb = sm.factorize_bc((nd, dd))
    w = 1e-3                                                                 # 면내 회전 + 병진
    rig = np.c_[-w * P[:, 1] + 0.2, w * P[:, 0] - 0.1, np.zeros(P.shape[0])]
    v = np.einsum("ri,ri->r", dd, rig[nd])
    u, _, rc, _ = hb.solve(np.zeros((P.shape[0], 3)), values=v)
    assert np.abs(u[:, :3] - rig).max() <= 1e-9 * np.abs(rig).max()
    assert np.abs(rc).max() <= 1e-6 * hb.norm_K * np.abs(rig).max()


def test_factorize_bc_errors(plate):
    sm, J = plate["sm"], plate["J"]
    with pytest.raises(EslError) as ei:                                      # 한 노드 종속 방향
        sm.factorize_bc((np.array([0, 0, 1, 9, 10, 40, 41]), np.array([[0, 0, 1.0], [0, 0, 2.0], [0, 0, 1.0], [0, 0, 1.0],
                                                                         [1.0, 0, 0], [0, 1.0, 0], [1.0, 0, 0]])))
    assert ei.value.code == "INPUT_INVALID"
    with pytest.raises(EslError) as ei:                                      # 면외만 → 면내 강체 3모드 남음
        sm.factorize_bc((J, np.tile([0, 0, 1.0], (J.size, 1))))
    assert ei.value.code == "SOLVER_SINGULAR"
    with pytest.raises(EslError):
        sm.factorize_bc((J[:2], np.zeros((2, 3))))
    with pytest.raises(EslError):
        sm.factorize_bc((np.zeros(0, np.int64), np.zeros((0, 3))), springs=(J, np.tile([0, 0, 1.0], (J.size, 1)),
                                                                             -np.ones(J.size)))


def test_bcsolve_transform_roundtrip_and_modes_match_spc():
    """곡면(원통) 패널: 국부 틀 왕복 항등, 축 방향 구속 BcSolve 모드 = spc 분해 모드(변환 공간 K̃·fixed_t, φ = to_global)."""
    P, C, et = cylinder_panel(400.0, 0.6, 200.0, 12, 6)
    sm = _sm(P, C, et)
    N = P.shape[0]
    J = np.array([0, 1, 2, 7 * 7 - 1, 7 * 7 - 2, N - 1, N - 2, N - 3], dtype=np.int64)
    J = np.unique(J)
    rng = np.random.default_rng(4)
    Q = np.linalg.qr(rng.normal(size=(3, 3)))[0]
    hb = sm.factorize_bc((np.repeat(J, 3), np.tile(Q.T, (J.size, 1))))     # 회전된 3방향 = 병진 고정과 같은 구속
    x = rng.normal(size=(2, N, 6))
    assert np.allclose(hb.to_global(hb.to_local(x)), x, rtol=0, atol=1e-13)
    h = sm.factorize([(int(i), "123") for i in J])
    w = jig.node_weights({"x0": P, "conn": C, "elem_type": et, "thickness": np.ones(len(C))})
    m = jig.lumped_mass(w, 7.85e-9)
    M6 = jig.mass_diag6(m)
    fixed = np.array([6 * p + d for p, d in h.cons])
    a = jig.jig_modes(sm.K(), M6, fixed, 4, 0.0, opinv=jig.opinv_from(h, N))
    b = jig.jig_modes(hb.K_t, M6, hb.fixed_t, 4, 0.0, opinv=jig.opinv_from(hb, N))
    assert np.allclose(a["lam"], b["lam"], rtol=1e-8)
    pb = hb.to_global(b["phi"])
    for k in range(4):
        ca = a["phi"][k, :, :3].ravel()
        cb = pb[k, :, :3].ravel()
        assert abs(ca @ cb) / (np.linalg.norm(ca) * np.linalg.norm(cb)) == pytest.approx(1.0, abs=1e-6)
    F = np.zeros((N, 3))
    F[N // 2] = [1.0, -2.0, 3.0]
    u0, _ = h.solve(F)
    u1 = hb.solve(F)[0]
    assert np.abs(u1 - u0).max() <= 1e-10 * np.abs(u0).max()


def test_factorize_bc_iterative_backend_matches_direct(plate):
    """반복법(CG, 변환 공간 블록 야코비·근사 영공간 = Tᵀ 강체 모드) = 직접법(1e-9)."""
    P = plate["P"]
    sm_i = ShellModel(P, plate["sm"].conn, plate["sm"].elem_type, 1.0, E, NU, backend="iterative", iter_rtol=1e-12)
    J, F = plate["J"], plate["F"]
    D = np.random.default_rng(5).normal(size=(3 * J.size, 3))
    sp_ = (J[:2], np.tile([0, 0, 1.0], (2, 1)), np.full(2, 50.0))
    v = np.linspace(-0.01, 0.01, 3 * J.size)
    g = np.array([0.1, -0.1])
    ud = plate["sm"].factorize_bc((np.repeat(J, 3), D), springs=sp_).solve(F, values=v, ground=g)[0]
    hi = sm_i.factorize_bc((np.repeat(J, 3), D), springs=sp_)
    ui = hi.solve(F, values=v, ground=g)[0]
    assert type(hi.lu).__name__ == "_CG"
    assert np.abs(ui - ud).max() <= 1e-9 * np.abs(ud).max()
