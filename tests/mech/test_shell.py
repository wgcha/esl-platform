"""T-SH-1~3: 쉘 솔버 검증."""
import numpy as np
import pytest
import scipy.sparse.linalg as spla

from esl.errors import EslError
from esl.mech import kabsch, supports
from esl.mech.shell import ShellModel
from meshes import (cylinder_panel, macneal_patch, quads_to_trias, rect_quads, rigid_modes,
                    rot_matrix, spherical_cap)

E, NU = 2.1e5, 0.3
Q3 = rot_matrix([1.0, -2.0, 0.5], 0.9)     # 기울인 평면 (국부→전역)
SHIFT = np.array([120.0, -40.0, 33.0])


def tilt(X):
    return X @ Q3.T + SHIFT


def solve_prescribed(m, presc_nodes, U_presc):
    """presc_nodes 의 6 dof 를 U_presc(전 노드 (N,6) 중 해당 행)로 강제, 나머지 무하중 → u (N,6)."""
    K = m.K()
    n = 6 * m.n_nodes
    fixed = (np.asarray(presc_nodes)[:, None] * 6 + np.arange(6)).ravel()
    free = np.setdiff1d(np.arange(n), fixed)
    u = np.zeros(n)
    u[fixed] = U_presc.ravel()[fixed]
    u[free] = spla.spsolve(K[free][:, free].tocsc(), -K[free][:, fixed] @ u[fixed])
    return u.reshape(-1, 6)


def check_patch(m, bnd, U):
    """patch test: (1) 정확해의 내부 dof 잔차 ≈ 0 (정식화 정확성), (2) 직접해 = 정확해.

    병진은 1e-10, 회전은 1e-8: 회전(특히 드릴링, k_d ∝ drill_factor) 블록의 조건수 때문에
    직접해의 반올림 증폭이 ~1e-10 수준으로 나타난다. 정식화 자체의 정확성은 (1)로 판정한다.
    """
    K = m.K()
    inner = np.setdiff1d(np.arange(m.n_nodes), bnd)
    r = (K @ U.ravel()).reshape(-1, 6)[inner]
    assert np.abs(r).max() < 1e-13 * spla.norm(K, np.inf) * np.abs(U).max()
    u = solve_prescribed(m, bnd, U)
    s = np.abs(U).max()
    assert np.abs(u[:, :3] - U[:, :3]).max() < 1e-10 * s
    assert np.abs(u[:, 3:] - U[:, 3:]).max() < 1e-8 * s


def elem_frames(X, conn, et):
    out = []
    for c, t in zip(conn, et):
        P = X[c[:t]]
        n = np.cross(P[2] - P[0], P[3] - P[1]) if t == 4 else np.cross(P[1] - P[0], P[2] - P[0])
        n /= np.linalg.norm(n)
        a = P[1] - P[0]
        a -= a.dot(n) * n
        e1 = a / np.linalg.norm(a)
        out.append((e1, np.cross(n, e1), n))
    return out


def rel_rigid_residual(m):
    K = m.K()
    r = rigid_modes(m.x0)
    return np.max(np.linalg.norm(K @ r, axis=0) / (spla.norm(K) * np.linalg.norm(r, axis=0)))


# ---------------------------------------------------------------- T-SH-1
@pytest.mark.parametrize("kind", ["quad", "tria", "mixed"])
def test_symmetry_and_rigid_modes_flat(kind):
    X, c, t = rect_quads(2.0, 1.0, 5, 3, distort=0.25)
    if kind == "tria":
        c, t = quads_to_trias(c)
    elif kind == "mixed":
        ct, tt = quads_to_trias(c[:6])
        c = np.vstack([c[6:], ct])
        t = np.concatenate([t[6:], tt])
    m = ShellModel(tilt(X), c, t, 0.05, E, NU)
    K = m.K()
    assert spla.norm(K - K.T) <= 1e-14 * spla.norm(K)
    assert rel_rigid_residual(m) < 1e-10
    # 정확히 6개 영 고유값
    w = np.linalg.eigvalsh(K.toarray())
    assert np.sum(np.abs(w) < 1e-9 * np.abs(w).max()) == 6


@pytest.mark.parametrize("mesh", ["cylinder", "sphere_warped"])
def test_rigid_modes_curved(mesh):
    """곡면: 원통(평면 쿼드)·구면(뒤틀린 쿼드, 강체 링크 warp 보정)에서도 강체 6모드 무에너지."""
    if mesh == "cylinder":
        X, c, t = cylinder_panel(300.0, 1.2, 200.0, 12, 8)
    else:
        X, c, t = spherical_cap(300.0, 1.0, 10)
    m = ShellModel(X, c, t, 1.0, E, NU)
    assert rel_rigid_residual(m) < 1e-10


def _patch(kind):
    X, c, t, bnd, inner = macneal_patch()
    if kind == "tria":
        c, t = quads_to_trias(c)
    return X, c, t, bnd


@pytest.mark.parametrize("kind", ["quad", "tria"])
def test_membrane_patch(kind):
    X, c, t, bnd = _patch(kind)
    Xg = tilt(X)
    m = ShellModel(Xg, c, t, 0.001, E, NU)
    a = np.array([1e-3, 2e-3, -1.5e-3, 0.7e-3, 0.4e-3, -0.9e-3])
    x, y = X[:, 0], X[:, 1]
    ul = np.c_[a[0] + a[1] * x + a[2] * y, a[3] + a[4] * x + a[5] * y, np.zeros_like(x)]
    omega = 0.5 * (a[4] - a[2])
    U = np.zeros((len(X), 6))
    U[:, :3] = ul @ Q3.T
    U[:, 3:] = omega * Q3[:, 2]
    check_patch(m, bnd, U)
    u = solve_prescribed(m, bnd, U)
    # 변형률: 전역 면내 텐서를 요소 국부계로
    G = np.array([[a[1], a[2], 0], [a[4], a[5], 0], [0, 0, 0]])
    Eps = Q3 @ (0.5 * (G + G.T)) @ Q3.T
    eps = m.strains(u)
    for k, (e1, e2, n) in enumerate(elem_frames(Xg, c, t)):
        ex = [e1 @ Eps @ e1, e2 @ Eps @ e2, e1 @ Eps @ e2]
        for layer in (0, 1):
            assert np.allclose(eps[k, layer], ex, rtol=0, atol=1e-10 * np.abs(a).max())


@pytest.mark.parametrize("kind", ["quad", "tria"])
def test_bending_patch_constant_curvature(kind):
    X, c, t, bnd = _patch(kind)
    Xg = tilt(X)
    th = 0.01
    m = ShellModel(Xg, c, t, th, E, NU)
    A, B, C = 0.8, -0.5, 0.3
    x, y = X[:, 0], X[:, 1]
    w = 0.5 * (A * x ** 2 + B * y ** 2 + 2 * C * x * y)
    thx = B * y + C * x          # w,y
    thy = -(A * x + C * y)       # −w,x
    U = np.zeros((len(X), 6))
    U[:, :3] = w[:, None] * Q3[:, 2]
    U[:, 3:] = np.c_[thx, thy, np.zeros_like(x)] @ Q3.T
    check_patch(m, bnd, U)
    u = solve_prescribed(m, bnd, U)
    Kap = Q3 @ np.array([[-A, -C, 0], [-C, -B, 0], [0, 0, 0]]) @ Q3.T   # κ 텐서(전역)
    eps = m.strains(u)
    for k, (e1, e2, n) in enumerate(elem_frames(Xg, c, t)):
        kap = np.array([e1 @ Kap @ e1, e2 @ Kap @ e2, e1 @ Kap @ e2])
        assert np.allclose(eps[k, 1], 0.5 * th * kap, rtol=0, atol=1e-10 * th)
        assert np.allclose(eps[k, 0], -0.5 * th * kap, rtol=0, atol=1e-10 * th)


# ---------------------------------------------------------------- T-SH-2
def _cantilever(kind, L, B, th, nx, ny, nu=0.0):
    X, c, t = rect_quads(L, B, nx, ny)
    if kind == "tria":
        c, t = quads_to_trias(c)
    Xg = tilt(X)
    m = ShellModel(Xg, c, t, th, E, nu)
    root = np.flatnonzero(np.isclose(X[:, 0], 0))
    tip = np.flatnonzero(np.isclose(X[:, 0], L))
    wts = np.ones(tip.size)
    wts[[0, -1]] = 0.5
    wts /= wts.sum()
    return m, Xg, root, tip, wts


def _clamped_tip(m, root, tip, wts, direction):
    U = np.zeros((m.n_nodes, 6))
    K = m.K()
    n = 6 * m.n_nodes
    fixed = (root[:, None] * 6 + np.arange(6)).ravel()
    free = np.setdiff1d(np.arange(n), fixed)
    f = np.zeros(n)
    for k, wk in zip(tip, wts):
        f[6 * k:6 * k + 3] += wk * direction
    U.ravel()[free] = spla.spsolve(K[free][:, free].tocsc(), f[free])
    return U


@pytest.mark.parametrize("kind,nx,ny", [("quad", 10, 2), ("tria", 20, 2)])
@pytest.mark.parametrize("ratio", [1 / 10.0 * 0.5, 1 / 100.0, 1 / 1000.0])
def test_cantilever_plate_bending(kind, nx, ny, ratio):
    L, B = 100.0, 10.0
    th = L * ratio
    m, Xg, root, tip, wts = _cantilever(kind, L, B, th, nx, ny)
    U = _clamped_tip(m, root, tip, wts, Q3[:, 2])
    d = U[tip, :3] @ Q3[:, 2]
    d_eb = L ** 3 / (3 * E * B * th ** 3 / 12)
    assert abs(d.mean() / d_eb - 1) < 0.03


def test_cantilever_membrane_inplane_qm6():
    L, B, th = 100.0, 10.0, 1.0
    m, Xg, root, tip, wts = _cantilever("quad", L, B, th, 10, 2, nu=0.3)
    U = _clamped_tip(m, root, tip, wts, Q3[:, 1])
    d = U[tip, :3] @ Q3[:, 1]
    d_eb = L ** 3 / (3 * E * th * B ** 3 / 12)
    assert abs(d.mean() / d_eb - 1) < 0.03


# ---------------------------------------------------------------- T-SH-3
def _plate_model(kind="quad", curved=False):
    if curved:
        X, c, t = cylinder_panel(150.0, 1.4, 120.0, 14, 10)
        Xg = X
    else:
        X, c, t = rect_quads(200.0, 120.0, 14, 9, distort=0.2)
        Xg = tilt(X)
    if kind == "tria":
        c, t = quads_to_trias(c)
    return ShellModel(Xg, c, t, 1.2, E, NU), Xg


def _smooth_field(X):
    s = (X - X.mean(0)) / np.ptp(X, axis=0).max()
    return 0.3 * np.c_[np.sin(2 * s[:, 0]) * s[:, 1], s[:, 0] ** 2 - s[:, 1] * s[:, 2], np.cos(3 * s[:, 1]) * s[:, 0] + s[:, 2]]


@pytest.mark.parametrize("kind,curved", [("quad", False), ("tria", False), ("quad", True)])
def test_roundtrip_condensed_solve(kind, curved):
    m, Xg = _plate_model(kind, curved)
    u = _smooth_field(Xg)
    F = m.condensed_forces(u)
    # 자기평형
    ctr = Xg.mean(0)
    sF = np.abs(F).sum()
    assert np.linalg.norm(F.sum(0)) < 1e-10 * sF
    assert np.linalg.norm(np.cross(Xg - ctr, F).sum(0)) < 1e-10 * sF * np.ptp(Xg, axis=0).max()
    cand = supports.pca_corners(Xg)["idx"]
    spc = supports.pick_321(Xg, cand)
    uv, R = m.solve(F, spc)
    assert np.abs(R).sum() < 1e-9 * sF
    d = uv[:, :3] - u
    # 미소 강체 (a + ω×X) 최소제곱 제거
    res, a, om = kabsch.remove_linear_rigid(Xg, d)
    umax = np.abs(u).max()
    assert np.sqrt(np.mean(np.sum(res ** 2, 1))) / umax < 1e-9
    assert np.abs(res).max() / umax < 1e-9


def test_rigid_rotation_strains_zero():
    m, Xg = _plate_model("quad")
    m2, _ = _plate_model("tria")
    for mm in (m, m2):
        th = np.array([2e-4, -3e-4, 1e-4])
        u = np.zeros((mm.n_nodes, 6))
        u[:, :3] = np.cross(th, Xg - 37.0) + [0.5, -0.2, 0.1]
        u[:, 3:] = th
        assert np.abs(mm.strains(u)).max() < 1e-12
        # 유한 회전(정확한 회전행렬) → 변형률은 O(θ²)
        Rr = rot_matrix([1, 1, 0.3], 1e-4)
        u2 = np.zeros((mm.n_nodes, 6))
        u2[:, :3] = Xg @ Rr.T - Xg
        u2[:, 3:] = 1e-4 * np.array([1, 1, 0.3]) / np.linalg.norm([1, 1, 0.3])
        assert np.abs(mm.strains(u2)).max() < 1e-8
        # condensed_forces(강체) ≈ 0
        F = mm.condensed_forces(u[:, :3])
        assert np.abs(F).max() < 1e-9 * np.abs(mm.condensed_forces(_smooth_field(Xg))).max()


def test_solve_singular():
    m, Xg = _plate_model("quad")
    F = np.zeros((m.n_nodes, 3))
    F[0, 2] = 1.0
    with pytest.raises(EslError) as ei:
        m.solve(F, [(0, "123"), (5, "12")])          # 5 dof 뿐
    assert ei.value.code == "SOLVER_SINGULAR"
    # 공선 3점 (같은 행의 노드들)
    with pytest.raises(EslError) as ei:
        m.solve(F, [(0, "123"), (1, "123"), (2, "123")])
    assert ei.value.code == "SOLVER_SINGULAR"


def test_strain_layer_convention():
    """순수 굽힘에서 bottom/top 부호: w = ½ a x² (국부) → top 압축 exx = −a t/2."""
    X, c, t = rect_quads(1.0, 1.0, 2, 2)
    m = ShellModel(X, c, t, 0.02, E, NU)
    a = 0.1
    u = np.zeros((m.n_nodes, 6))
    u[:, 2] = 0.5 * a * X[:, 0] ** 2
    u[:, 4] = -a * X[:, 0]
    eps = m.strains(u)
    assert np.allclose(eps[:, 1, 0], -a * 0.01) and np.allclose(eps[:, 0, 0], a * 0.01)


# ---------------------------------------------------------------- 백엔드 (esl_core §7.5)
from esl.mech import shell as _shell  # noqa: E402


@pytest.mark.parametrize("backend", ["cholmod", "pardiso", "superlu"])
@pytest.mark.parametrize("kind,curved", [("quad", False), ("tria", False), ("quad", True)])
def test_roundtrip_backend(backend, kind, curved):
    """T-SH-3 왕복을 백엔드별로 + SuperLU 결과와 일치 (미설치 백엔드는 skip)."""
    if backend not in _shell.available_backends():
        pytest.skip(f"{backend} 미설치")
    m, Xg = _plate_model(kind, curved)
    m.backend = backend
    ref, _ = _plate_model(kind, curved)
    ref.backend = "superlu"
    u = _smooth_field(Xg)
    F = m.condensed_forces(u)
    Fr = ref.condensed_forces(u)
    assert np.abs(F - Fr).max() < 1e-10 * np.abs(Fr).max()
    spc = supports.pick_321(Xg, supports.pca_corners(Xg)["idx"])
    uv, R = m.solve(F, spc)
    res, _, _ = kabsch.remove_linear_rigid(Xg, uv[:, :3] - u)
    umax = np.abs(u).max()
    assert np.sqrt(np.mean(np.sum(res ** 2, 1))) / umax < 1e-9
    assert np.abs(R).sum() < 1e-9 * np.abs(F).sum()
    assert m.stats["K_rr"]["backend_used"] == backend and m.stats["K_ff"]["backend_used"] == backend
    for k in ("factor_s", "nnz_L", "mem_est_mb"):
        assert k in m.stats["K_ff"]


def test_backend_selection():
    X, c, t = rect_quads(10.0, 5.0, 4, 2)
    m = ShellModel(X, c, t, 1.0, E, NU)
    assert m.backend == _shell.available_backends()[0] and m.stats["backend"] == m.backend
    with pytest.raises(EslError) as ei:
        ShellModel(X, c, t, 1.0, E, NU, backend="mumps")
    assert ei.value.code == "INPUT_INVALID"
    assert ShellModel(X, c, t, 1.0, E, NU, backend="superlu").backend == "superlu"


def test_not_pd_fallback_and_singular(monkeypatch):
    """비양정치 → 메모리 여유 있으면 SuperLU 폴백 + 경고, 없으면 SOLVER_SINGULAR (규모 상한 없음)."""
    import scipy.sparse as sps
    A = sps.csr_matrix(np.array([[1.0, 2.0], [2.0, 1.0]]))
    for b in _shell.available_backends():
        if b == "superlu":
            continue
        st = {}
        with pytest.warns(RuntimeWarning):
            f = _shell._factorize(A, b, st, "A")
        assert st["A"]["backend_used"] == "superlu" and "fallback" in st["A"]
        assert np.allclose(A @ f.solve(np.array([1.0, 0.0])), [1.0, 0.0])
        monkeypatch.setattr(_shell, "available_memory_bytes", lambda: 1)
        with pytest.raises(EslError) as ei:
            with pytest.warns(RuntimeWarning):
                _shell._factorize(A, b, {}, "A")
        assert ei.value.code == "SOLVER_SINGULAR"
        monkeypatch.undo()


def test_available_memory():
    m = _shell.available_memory_bytes()
    assert m is None or m > 0


@pytest.mark.parametrize("kind,curved", [("quad", False), ("tria", False), ("quad", True)])
def test_roundtrip_iterative(kind, curved):
    """반복법(CG): K_rr 블록 야코비, K_ff pyamg(없으면 skip). rtol 1e-12 에서 T-SH-3 왕복."""
    if _shell._pyamg() is None:
        pytest.skip("pyamg 미설치")
    m, Xg = _plate_model(kind, curved)
    m.backend = "iterative"
    m.iter_opts = {"rtol": 1e-12, "maxiter": None}
    ref, _ = _plate_model(kind, curved)
    ref.backend = "superlu"
    u = _smooth_field(Xg)
    F = m.condensed_forces(u)
    Fr = ref.condensed_forces(u)
    assert np.abs(F - Fr).max() < 1e-8 * np.abs(Fr).max()
    assert m.stats["K_rr"]["backend_used"] == "iterative" and m.stats["K_rr"]["iterations"][-1] > 0
    spc = supports.pick_321(Xg, supports.pca_corners(Xg)["idx"])
    uv, R = m.solve(Fr, spc)
    res, _, _ = kabsch.remove_linear_rigid(Xg, uv[:, :3] - u)
    assert np.sqrt(np.mean(np.sum(res ** 2, 1))) / np.abs(u).max() < 1e-7
    assert m.stats["K_ff"]["precond"].startswith("pyamg")


def test_iterative_not_converged():
    m, Xg = _plate_model("quad")
    m.backend = "iterative"
    m.iter_opts = {"rtol": 1e-14, "maxiter": 2}
    with pytest.raises(EslError) as ei:
        m.condensed_forces(_smooth_field(Xg))
    assert ei.value.code == "SOLVER_NOT_CONVERGED"


def test_auto_switches_to_iterative_on_low_memory(monkeypatch):
    if _shell._pyamg() is None:
        pytest.skip("pyamg 미설치")
    m, Xg = _plate_model("quad")
    u = _smooth_field(Xg)
    ref, _ = _plate_model("quad")
    ref.backend = "superlu"
    Fr = ref.condensed_forces(u)
    monkeypatch.setattr(_shell, "available_memory_bytes", lambda: 1000)
    with pytest.warns(RuntimeWarning, match="반복법"):
        F = m.condensed_forces(u)
    assert m.stats["K_rr"]["backend_used"] == "iterative"
    assert np.abs(F - Fr).max() < 1e-7 * np.abs(F).max()


# ---------------------------------------------------------------- 메모리 부족(SOLVER_OUT_OF_MEMORY, §12.4 Verifier v6)
def test_out_of_memory_pardiso_code_minus2(monkeypatch):
    """PARDISO error -2(메모리 부족) → SOLVER_OUT_OF_MEMORY (SOLVER_SINGULAR 아님). 그 밖 오류는 SOLVER_SINGULAR."""
    import scipy.sparse as sps

    class _Err(Exception):
        def __init__(self, value):
            super().__init__(f"PARDISO error {value}")
            self.value = value

    def fake_cls(code):
        class S:
            def __init__(self, mtype):
                pass

            def set_iparm(self, i, v):
                pass

            def factorize(self, A):
                raise _Err(code)

            def free_memory(self, everything=False):
                pass
        return S

    A = sps.csr_matrix(np.eye(3))
    monkeypatch.setattr(_shell, "_pardiso_solver_cls", lambda: fake_cls(-2))
    with pytest.raises(EslError) as ei:
        _shell._Pardiso(A)
    assert ei.value.code == "SOLVER_OUT_OF_MEMORY" and "error -2" in ei.value.message
    monkeypatch.setattr(_shell, "_pardiso_solver_cls", lambda: fake_cls(-3))
    with pytest.raises(EslError) as ei:
        _shell._Pardiso(A)
    assert ei.value.code == "SOLVER_SINGULAR"


def test_out_of_memory_cholmod(monkeypatch):
    """CHOLMOD out-of-memory(CholmodError 하위 — 이전 판의 비양정치 기반 클래스)도 비양정치 폴백이 아니라 OOM."""
    import types

    import scipy.sparse as sps

    class CholmodError(Exception):
        pass

    class CholmodOutOfMemoryError(CholmodError):
        pass

    def cholesky(A):
        raise CholmodOutOfMemoryError("CHOLMOD out of memory")

    ch = types.SimpleNamespace(CholmodError=CholmodError, CholmodOutOfMemoryError=CholmodOutOfMemoryError,
                               cholesky=cholesky)
    monkeypatch.setattr(_shell, "_cholmod_module", lambda: ch)
    with pytest.raises(EslError) as ei:
        _shell._factorize(sps.csr_matrix(np.eye(3)), "cholmod", {}, "A")
    assert ei.value.code == "SOLVER_OUT_OF_MEMORY"
    # 메시지로만 알리는 판(CholmodError("... out of memory ..."))
    ch.CholmodOutOfMemoryError = None

    def cholesky2(A):
        raise CholmodError("CHOLMOD error: out of memory")

    ch.cholesky = cholesky2
    with pytest.raises(EslError) as ei:
        _shell._factorize(sps.csr_matrix(np.eye(3)), "cholmod", {}, "A")
    assert ei.value.code == "SOLVER_OUT_OF_MEMORY"


def test_out_of_memory_memoryerror_anywhere(monkeypatch):
    """조립·분해·해 어디서든 MemoryError → SOLVER_OUT_OF_MEMORY (Verifier v6: RLIMIT_AS 아래 numpy 할당 실패)."""
    m, Xg = _plate_model("quad")
    m.backend = "superlu"

    def boom(A):
        raise MemoryError("Unable to allocate 222. MiB for an array")

    monkeypatch.setitem(_shell._IMPL, "superlu", boom)
    spc = supports.pick_321(Xg, supports.pca_corners(Xg)["idx"])
    with pytest.raises(EslError) as ei:
        m.solve(np.ones((m.n_nodes, 3)) * 0.0 + np.eye(1, 3, 2), spc)
    assert ei.value.code == "SOLVER_OUT_OF_MEMORY" and "MemoryError" in ei.value.message
    with pytest.raises(EslError) as ei:
        m.condensed_forces(_smooth_field(Xg))
    assert ei.value.code == "SOLVER_OUT_OF_MEMORY"
    m2, _ = _plate_model("quad")
    monkeypatch.setattr(type(m2), "_block_K", lambda self: (_ for _ in ()).throw(MemoryError("K")))
    with pytest.raises(EslError) as ei:
        m2.K()
    assert ei.value.code == "SOLVER_OUT_OF_MEMORY" and "강성 조립" in ei.value.message


def test_out_of_memory_superlu_malloc(monkeypatch):
    """SuperLU 할당 실패(Verifier v6 RLIMIT_AS 1.6 GB: RuntimeError 'SUPERLU_MALLOC fails ...') → OOM, 특이는 그대로."""
    import scipy.sparse as sps

    def splu_oom(*a, **k):
        raise RuntimeError("SUPERLU_MALLOC fails for buf in mxCallocInt() at line 68")

    monkeypatch.setattr(_shell.spla, "splu", splu_oom)
    with pytest.raises(EslError) as ei:
        _shell._SuperLU(sps.csc_matrix(np.eye(2)))
    assert ei.value.code == "SOLVER_OUT_OF_MEMORY"

    def splu_sing(*a, **k):
        raise RuntimeError("Factor is exactly singular")

    monkeypatch.setattr(_shell.spla, "splu", splu_sing)
    with pytest.raises(EslError) as ei:
        _shell._SuperLU(sps.csc_matrix(np.eye(2)))
    assert ei.value.code == "SOLVER_SINGULAR"


def test_resid_check_backward_error():
    """v0.14.0 해 잔차 판정: ‖r‖/‖F‖ ≤ 1e-8(옛 판정) 또는 후방 오차 η = ‖r‖/(‖K‖∞‖u‖+‖F‖) ≤ 1e-9 이면 수용."""
    import scipy.sparse as sps_

    st = {}
    rhs = np.ones(4)
    uf = np.full(4, 1e6)                                     # 조건수 큰 문제: ‖u‖ ≫ ‖F‖/‖K‖
    res = np.full(4, 3e-8)                                   # ‖r‖/‖F‖ 3e-8 > 1e-8
    assert _shell._check_resid(None, uf, res, rhs, 1.0, st) == pytest.approx(3e-8)
    assert st["solve_backward_err"] == pytest.approx(3e-8 * 2 / (1e6 * 2 + 2))
    with pytest.raises(EslError) as ei:                      # η 도 큼(‖u‖ 작음) → 특이
        _shell._check_resid(None, np.ones(4), np.full(4, 3e-8), rhs, 1.0, {})
    assert ei.value.code == "SOLVER_SINGULAR"
    with pytest.raises(EslError) as ei:                      # 유한하지 않은 해
        _shell._check_resid(None, np.array([np.nan, 0, 0, 0]), np.zeros(4), rhs, 1.0, {})
    assert ei.value.code == "SOLVER_SINGULAR"
    assert _shell._check_resid(None, np.ones(4), np.full(4, 1e-9), rhs, 1.0, {}) == pytest.approx(1e-9)   # 옛 판정 통과

    class FakeCG(_shell._CG):                                # 반복법은 옛 판정(max(1e-8, 100·rtol)) 그대로
        def __init__(self):
            self.rtol = 1e-10
    with pytest.raises(EslError):
        _shell._check_resid(FakeCG(), uf, res, rhs, 1.0, {})
    assert _shell._norm_inf(sps_.csr_matrix(np.array([[2.0, -1.0], [-1.0, 3.0]]))) == 4.0


def _plate_321(nx=40, ny=30):
    X, c, et = rect_quads(400.0, 300.0, nx, ny)
    X = np.c_[X, np.zeros(len(X))] if X.shape[1] == 2 else X
    m = ShellModel(X, c, et, 0.8, 210000.0, 0.3, backend="superlu")
    a = int(np.argmin(X[:, 0] + X[:, 1]))
    b = int(np.argmin(-X[:, 0] + X[:, 1]))
    cc = int(np.argmin(X[:, 0] - X[:, 1]))
    return m, X, a, b, cc


def test_resid_check_rejects_rigid_mode_unbalanced_load():
    """검증 반례 1(v0.14.0 수정): 강체 x 병진이 남은 K_ff(구속 검사 우회) + 평형 안 맞는 Fx — η 9.6e-18 이지만
    ‖r‖/‖F‖ 6.8 → 상대 잔차 상한(resid_rel_cap)으로 거부. 상한을 풀어도 반력 평형 검사가 거부."""
    from esl.config import SOLVER_CHECK_DEFAULTS
    m, X, a, b, cc = _plate_321()
    spc = [(a, "23"), (b, "23"), (cc, "3")]
    m._check_restraint = lambda cons: None
    F = np.zeros((m.n_nodes, 3))
    F[:, 0] = 1.0
    with pytest.raises(EslError) as ei:
        m.solve(F, spc)
    assert ei.value.code == "SOLVER_SINGULAR" and "잔차" in ei.value.message
    assert m.resid_rel_cap == SOLVER_CHECK_DEFAULTS["resid_rel_cap"]
    m2, *_ = _plate_321()
    m2._check_restraint = lambda cons: None
    m2.resid_rel_cap = 1.0e3                                  # 잔차 상한 해제 → 평형 검사가 막아야 함
    with pytest.raises(EslError) as ei:
        m2.solve(F, spc)
    assert ei.value.code == "SOLVER_SINGULAR" and "평형" in ei.value.message


def test_resid_check_rejects_pivot_perturbation():
    """검증 반례 2(v0.14.0 수정): 대각 1e-8 섭동한 K_ff 로 푼 해 — η 1.3e-10 ≤ 1e-9 이지만 ‖r‖/‖F‖ 1e-2 → 거부."""
    import scipy.sparse as sps_

    m, X, a, b, cc = _plate_321()
    K = m.K()
    cons = sorted({(a, 0), (a, 1), (a, 2), (b, 1), (b, 2), (cc, 2)})
    fixed = np.array([6 * p + d for p, d in cons])
    free = np.setdiff1d(np.arange(6 * m.n_nodes), fixed)
    Kff = _shell._principal_submatrix(K, free).tocsc()
    nK = _shell._norm_inf(Kff)
    rng = np.random.default_rng(0)
    rhs = rng.normal(size=free.size)
    D = sps_.diags(Kff.diagonal() * 1e-8 * rng.uniform(-1, 1, free.size))
    uf = spla.spsolve((Kff + D).tocsc(), rhs)
    st = {}
    with pytest.raises(EslError) as ei:
        _shell._check_resid(None, uf, Kff @ uf - rhs, rhs, nK, st)
    assert ei.value.code == "SOLVER_SINGULAR"
    uf0 = spla.spsolve(Kff, rhs)                               # 섭동 없는 해는 그대로 통과
    _shell._check_resid(None, uf0, Kff @ uf0 - rhs, rhs, nK, st)


def test_equilibrium_check_and_settings():
    """반력 평형 |ΣR+ΣF|/max(|ΣF|,Σ|F|) 검사·설정 키(solver.resid_rel_cap·equilibrium_tol_rel, 없으면 기본값)."""
    from esl.config import SOLVER_CHECK_DEFAULTS, solver_check_settings
    from esl.mech.shell import solver_check_kwargs
    m, X, a, b, cc = _plate_321(20, 15)
    F = np.zeros((m.n_nodes, 3))
    F[:, 2] = -1.0
    u, R = m.solve(F, [(a, "123"), (b, "23"), (cc, "3")])
    assert m.stats["solve_equilibrium_rel"] < 1e-8
    F2 = np.zeros((2, 3)); F2[0, 0] = 1.0; F2[1, 0] = -1.0     # 자기평형 하중도 Σ|F| 로 규모
    assert _shell._check_equilibrium(F2, np.zeros((2, 3)), {}) == 0.0
    with pytest.raises(EslError) as ei:
        _shell._check_equilibrium(F2, np.array([[0.1, 0, 0], [0, 0, 0]]), {})
    assert ei.value.code == "SOLVER_SINGULAR"
    assert solver_check_settings(None) == SOLVER_CHECK_DEFAULTS
    assert solver_check_kwargs({"drill_factor": 1e-4, "resid_rel_cap": 1e-3, "equilibrium_tol_rel": None}) == {
        "resid_rel_cap": 1e-3, "equil_tol_rel": SOLVER_CHECK_DEFAULTS["equilibrium_tol_rel"]}
