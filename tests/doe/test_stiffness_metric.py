"""V-SM-1~5(모듈 단위, 모드 무관 합성) — 계약 esl_stiffness_metric.md §8.

V-SM-1 K₁ = K₀ → lin = ritz = solve, V-SM-2 작은 ΔK 1차 일치·하한, V-SM-3 무른 모드 증폭 재현(solve 폭주·lin 안정),
V-SM-4 강체·전달·회전 carry, V-SM-5 순수 모듈(AST·결정성), V-SM-11 결정 A ②(다른 A 메시 → work 하중 → 기준 B 해 참조)."""
import ast
import itertools
import os

import numpy as np
import pytest
import scipy.sparse as sp
import synth_sm as ss

from esl.doe import stiffness_metric as smm
from esl.errors import EslError


def _ref(mesh, F):
    """기준(①·a_direct 같은 꼴): 3-2-1 풀이 → 강체 제거 u_ref, C_ref, 기준 C_solve·umax."""
    u0, C0, um0, _ = ss.solve(mesh, F)
    uref = smm.remove_rigid(mesh["x0"], u0)
    ref = smm.reference(smm.stiffness(mesh), uref, F)
    return uref, ref, C0, um0


def _target(mesh, x, uref, F, C_ref, **kw):
    return smm.metrics(smm.stiffness(dict(mesh, x0=x)), uref, F, C_ref, **kw)


# ---------------------------------------------------------------- V-SM-1
@pytest.fixture(scope="module")
def drop_case():
    m = ss.plate()
    F = ss.esl_force(m, ss.drop_u(m, amp=2.0))
    return m, F


def test_v_sm_1_same_K_lin_equals_solve(drop_case):
    m, F = drop_case
    uref, ref, C0, _ = _ref(m, F)
    assert ref["bal"] < 1e-10                                   # C_ref = F·u_ref (반력 일 0, 자기평형)
    r = _target(m, m["x0"], uref, F, ref["C_ref"])
    assert r["rho"] == pytest.approx(1.0, abs=1e-10)
    for k in ("C_lin", "C_ritz"):
        assert r[k] == pytest.approx(C0, rel=1e-10)
    assert smm.lin_value(ref["C_ref"], r["rho"], "taylor") == r["C_lin"]
    assert smm.lin_value(ref["C_ref"], r["rho"], "ritz") == r["C_ritz"]
    assert r["imbalance_rel"] <= 1e-9 and r["warnings"] == []


# ---------------------------------------------------------------- V-SM-2
@pytest.fixture(scope="module")
def small_dk():
    """휜 판 + 법선(Y) 하중(자기평형 — Y 모핑에도 모멘트 0) + 국부 비드 α(법선 이동)."""
    m = ss.plate()
    F = ss.y_load(m)
    uref, ref, C0, _ = _ref(m, F)
    out = {}
    for a in (-1e-4, 1e-4, 1e-3, 1e-2, 0.1, 1.0):
        x = ss.bead_x(m, a)
        r = _target(m, x, uref, F, ref["C_ref"])
        out[a] = dict(r, C_solve=ss.solve(m, F, x)[1], x=x)
    return m, F, uref, ref, out


def test_v_sm_2_first_order_and_bounds(small_dk):
    _, _, _, ref, out = small_dk
    d = {a: out[a]["C_solve"] - out[a]["C_lin"] for a in (1e-4, 1e-3, 1e-2)}
    assert all(v > 0 for v in d.values())
    for a, b in ((1e-4, 1e-3), (1e-3, 1e-2)):                    # (a) 차 = O(α²): 기울기 2 ± 0.2
        assert np.log10(d[b] / d[a]) == pytest.approx(2.0, abs=0.2)
    h = 1e-4                                                    # (b) 중심 차분 dC/dα(α=0): lin = solve
    dlin = (out[h]["C_lin"] - out[-h]["C_lin"]) / (2 * h)
    dsol = (out[h]["C_solve"] - out[-h]["C_solve"]) / (2 * h)
    assert abs(dlin) > 1e-3 * ref["C_ref"]                      # 1차 항이 실제로 있음(자명하지 않음)
    assert dlin == pytest.approx(dsol, rel=1e-3)
    for a, r in out.items():                                    # (c) S = I 하한
        assert r["C_lin"] <= r["C_ritz"] * (1 + 1e-12) and r["C_ritz"] <= r["C_solve"] * (1 + 1e-12), a
        # 차 C_ritz − C_lin = C_ref(ρ−1)²/ρ
        assert r["C_ritz"] - r["C_lin"] == pytest.approx(ref["C_ref"] * (r["rho"] - 1) ** 2 / r["rho"],
                                                          rel=1e-6, abs=1e-12 * ref["C_ref"])
    assert any(w["code"] == "SM_LIN_RANGE" for w in out[1.0]["warnings"])
    assert not any(w["code"] == "SM_LIN_RANGE" for w in out[1e-3]["warnings"])


# ---------------------------------------------------------------- V-SM-3
@pytest.fixture(scope="module")
def soft_amp():
    """#63 재현: 긴 얇은 판(t 0.8, 600×100, 3-2-1) + 큰 F = K₀u_drop(국부 막 압축) + 국부 비드 α."""
    m = ss.plate(nx=60, ny=10, Lx=600.0, Lz=100.0, t=0.8, bow=0.0, n_tria_cols=6)
    ud = ss.drop_u(m, amp=5.0, dent=(0.0, 0.0), w=0.05)
    ud[:, 1] = 0.0
    F = ss.esl_force(m, ud)
    uref, ref, C0, um0 = _ref(m, F)
    rows = []
    for a in (0.1, 0.5, 1.0):
        x = ss.bead_x(m, a, depth=10.0, center=(0.1, 0.0), r=0.15)
        r = _target(m, x, uref, F, ref["C_ref"])
        u1, C1, um1, _ = ss.solve(m, F, x)
        rows.append({"alpha": a, "taylor": r["C_lin"] / C0, "ritz": r["C_ritz"] / C0, "solve": C1 / C0,
                     "imb": r["imbalance_rel"], "umax": um1 / um0, "umax_def": smm.umax_def(x, u1) / um0,
                     "warn": [w["code"] for w in r["warnings"]]})
    return rows


def test_v_sm_3_soft_mode_amplification(soft_amp):
    rows = soft_amp
    for r in rows:
        a = r["alpha"]
        assert r["umax"] >= 10.0                                # solve 폭주(#63 umax ×50~270 이상)
        assert abs(r["taylor"] - 1.0) <= 0.2 * a and abs(r["ritz"] - 1.0) <= 0.2 * a   # lin 안정
        assert r["umax_def"] < r["umax"] and r["umax_def"] >= 10.0     # 강체 제거 한계(무른 굽힘은 남음)
        assert abs(r["solve"] - 1.0) > 10 * abs(r["ritz"] - 1.0)
    for p, q in itertools.pairwise(rows):                            # α 에 단조(연속)
        assert q["umax"] > p["umax"] and q["imb"] > p["imb"] and q["solve"] > p["solve"]
        assert q["taylor"] >= p["taylor"] and q["ritz"] >= p["ritz"]
    assert rows[-1]["imb"] >= 0.05 and "SM_IMBALANCE" in rows[-1]["warn"]


# ---------------------------------------------------------------- V-SM-4
def _rigid(x, a, om, c):
    return a + np.cross(om, x - c)


def test_v_sm_4a_rigid_invariance(small_dk):
    m, F, uref, ref, out = small_dk
    x = out[1e-2]["x"]
    Kt = smm.stiffness(dict(m, x0=x))
    rng = np.random.default_rng(3)
    u2 = uref.copy()
    om = rng.normal(size=3) * 1e-2
    u2[:, :3] += _rigid(m["x0"], rng.normal(size=3) * 5, om, np.array([10.0, 0, 20.0]))
    u2[:, 3:] += om
    u3 = smm.remove_rigid(m["x0"], u2)
    r0 = smm.metrics(Kt, uref, F, ref["C_ref"])
    r1 = smm.metrics(Kt, u3, F, smm.reference(smm.stiffness(m), u3)["C_ref"])
    assert r1["rho"] == pytest.approx(r0["rho"], rel=1e-10) and r1["C_lin"] == pytest.approx(r0["C_lin"], rel=1e-10)
    # 강체를 안 빼면 안 좌표에서 가짜 변형(제거가 필요한 이유)
    assert abs(smm.metrics(Kt, u2, F, ref["C_ref"])["rho"] - r0["rho"]) > 1e-6


def test_v_sm_4b_rigid_fit_exact():
    rng = np.random.default_rng(0)
    x = rng.uniform(-300, 300, size=(500, 3))
    a, om = rng.normal(size=3) * 10, rng.normal(size=3) * 0.05
    u = np.zeros((500, 6))
    u[:, :3] = _rigid(x, a, om, np.zeros(3))
    u[:, 3:] = om
    a2, om2, xb = smm.rigid_fit(x, u)
    sc = np.abs(u[:, :3]).max()
    assert np.abs(a2 + np.cross(om2, x - xb) - u[:, :3]).max() <= 1e-12 * sc
    assert np.abs(om2 - om).max() <= 1e-12 * np.abs(om).max()
    assert np.abs(smm.remove_rigid(x, u)).max() <= 1e-12 * sc
    mask = np.zeros(500, bool)
    mask[:40] = True                                            # Ω 만으로 맞춰도 순수 강체는 그대로 복원
    assert np.abs(smm.remove_rigid(x, u, mask)).max() <= 1e-12 * sc
    assert smm.umax_def(x, u, np.arange(40)) <= 1e-12 * sc
    line = np.column_stack([np.arange(5.0), np.zeros(5), np.zeros(5)])
    with pytest.raises(EslError):
        smm.rigid_fit(line, np.zeros((5, 3)))


def _bilinear_S(nx, ny, Lx, Lz, pts):
    """시험용 S: 직교 격자(XZ, (nx+1)(ny+1) 노드, 노드 = i(ny+1)+j) 의 쌍선형 형상함수 행."""
    hx, hz = Lx / nx, Lz / ny
    i = np.minimum((pts[:, 0] // hx).astype(int), nx - 1)
    j = np.minimum((pts[:, 2] // hz).astype(int), ny - 1)
    xi, eta = pts[:, 0] / hx - i, pts[:, 2] / hz - j
    rows, cols, vals = [], [], []
    for di, dj, w in ((0, 0, (1 - xi) * (1 - eta)), (1, 0, xi * (1 - eta)), (1, 1, xi * eta), (0, 1, (1 - xi) * eta)):
        rows.append(np.arange(pts.shape[0]))
        cols.append((i + di) * (ny + 1) + j + dj)
        vals.append(w)
    return sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                         shape=(pts.shape[0], (nx + 1) * (ny + 1)))


def test_v_sm_4c_apply_disp():
    A = ss.plate(nx=6, ny=4, Lx=300.0, Lz=200.0, bow=0.0, n_tria_cols=0)
    rng = np.random.default_rng(1)
    pts = np.column_stack([rng.uniform(0, 300, 200), np.zeros(200), rng.uniform(0, 200, 200)])
    S = _bilinear_S(6, 4, 300.0, 200.0, pts)
    G = rng.normal(size=(3, 6))
    c = rng.normal(size=6)
    lin = lambda X: c + X @ G
    ut = smm.apply_disp(S, lin(A["x0"]))
    assert np.abs(ut - lin(pts)).max() <= 1e-12 * np.abs(lin(pts)).max()
    u = rng.normal(size=(A["x0"].shape[0], 6))
    idx = rng.permutation(u.shape[0])
    P = sp.csr_matrix((np.ones(idx.size), (np.arange(idx.size), idx)), shape=(idx.size, idx.size))
    a1, a2 = smm.apply_disp(idx, u), smm.apply_disp(P, u)
    assert a1.tobytes() == a2.tobytes() == u[idx].tobytes()     # 순열 S = identity 경로 비트 동일
    assert smm.apply_disp(None, u).tobytes() == u.tobytes()
    th = 0.3
    R = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    ur = smm.apply_disp(None, u, R)
    assert np.allclose(ur[:, :3], u[:, :3] @ R.T) and np.allclose(ur[:, 3:], u[:, 3:] @ R.T)
    with pytest.raises(EslError):
        smm.apply_disp(sp.csr_matrix((3, 5)), u)


def test_v_sm_4d_rotation_carry_vs_condense(small_dk):
    m, F, uref, ref, out = small_dk
    d0 = smm.metrics(smm.stiffness(m), uref, None, ref["C_ref"])["U2"] - ss.condensed_U2(m, m["x0"], uref)
    assert abs(d0) <= 1e-9 * ref["C_ref"]                        # α=0: u_ref 회전 = K_A 최적
    d = {}
    for a in (1e-3, 1e-2):
        x = out[a]["x"]
        d[a] = out[a]["U2"] - ss.condensed_U2(m, x, uref)
        assert d[a] >= -1e-9 * ref["C_ref"]                      # carry ≥ 응축(회전 최적)
    assert np.log10(d[1e-2] / d[1e-3]) == pytest.approx(2.0, abs=0.3)   # C_lin 차 = O(α²)


# ---------------------------------------------------------------- V-SM-5 (모듈)
def test_v_sm_5_pure_module_ast():
    with open(os.path.join(os.path.dirname(smm.__file__), "stiffness_metric.py"), encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    banned_calls = {"factorize", "solve", "solve_many", "condensed_forces", "rotations_for", "spsolve", "splu",
                    "factorized", "open", "cholesky", "inv"}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            assert not (n.module or "").startswith("esl.doe"), n.module
            assert n.module in ("__future__", "esl.errors", "esl.mech.shell"), n.module
        if isinstance(n, ast.Import):
            for a in n.names:
                assert a.name in ("numpy", "scipy.sparse"), a.name
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            assert name not in banned_calls, name
    assert smm.LIN_FORM_DEFAULT == "ritz"                        # Q-SM-1 확정


def test_v_sm_5_deterministic_and_errors(small_dk):
    m, F, uref, ref, out = small_dk
    Kt = smm.stiffness(dict(m, x0=out[1e-2]["x"]))
    r1 = smm.metrics(Kt, uref.copy(), F.copy(), ref["C_ref"])
    r2 = smm.metrics(Kt.copy(), np.array(uref), np.array(F), float(ref["C_ref"]))
    assert r1 == r2 and np.float64(r1["U2"]).tobytes() == np.float64(r2["U2"]).tobytes()
    with pytest.raises(EslError):
        smm.metrics(Kt, uref, F, 0.0)
    with pytest.raises(EslError):
        smm.metrics(Kt, uref[:, :3], F, 1.0)
    for bad in (("lin", "x"), ("foo", "ritz")):
        with pytest.raises(EslError) as e:
            smm.metric_key(*bad)
        assert e.value.code == "CONFIG_INVALID"
    assert smm.metric_key("solve") == "C" and smm.metric_key("lin") == "C_ritz"
    assert smm.metric_key("lin", "taylor") == "C_lin"


def test_stiffness_region_mask(small_dk):
    """Ω(영역 요소) 조립 = 영역 요소 강성만(노드 번호 그대로): 전체 = 영역 + 여집합."""
    m = small_dk[0]
    ne = m["conn"].shape[0]
    mask = np.zeros(ne, bool)
    mask[: ne // 3] = True
    K = smm.stiffness(m)
    K1, K2 = smm.stiffness(m, elem_mask=mask), smm.stiffness(m, elem_mask=~mask)
    assert K1.shape == K.shape and abs(K - K1 - K2).max() <= 1e-9 * abs(K).max()
    sc = smm.score([{"entry_id": "E1", "C": 2.0, "C_ritz": 3.0, "C_lin": 1.0},
                    {"entry_id": "E2", "C": 5.0, "C_ritz": None, "C_lin": 4.0}], "lin")
    assert sc["worst"] == "E1" and sc["missing"] == ["E2"] and sc["M_max"] == 3.0


# ---------------------------------------------------------------- V-SM-11 결정 A(2026-11-13) ② 합성
@pytest.fixture(scope="module")
def bmesh_amp():
    """② 꼴: ESL 원본 A(600×100, t 0.8, F = K₀u_drop) → 다른 메시 B(같은 기하, 성긴 45×8)에 work 하중(W, LT-2) →
    참조 u_ref = B 에서 그 하중으로 직접 푼 해(강체 제거), 안 = B 모핑(같은 노드 S = I)."""
    from esl.doe import DEFAULTS
    from esl.doe import load_transfer as ltm
    a = ss.plate(nx=60, ny=10, Lx=600.0, Lz=100.0, t=0.8, bow=0.0, n_tria_cols=6)
    ud = ss.drop_u(a, amp=5.0, dent=(0.0, 0.0), w=0.05)
    ud[:, 1] = 0.0
    b = ss.plate(nx=45, ny=8, Lx=600.0, Lz=100.0, t=0.8, bow=0.0, n_tria_cols=6)
    W = ltm.build_work(a["x0"], b, None, DEFAULTS["load_transfer"]["work"], 10.0)
    FB = ltm.apply_work(W, ss.esl_force(a, ud), b["x0"].shape[0])
    uref, ref, C0, um0 = _ref(b, FB)
    base = _target(b, b["x0"], uref, FB, ref["C_ref"])
    rows = []
    for al in (0.1, 0.5, 1.0):
        x = ss.bead_x(b, al, depth=10.0, center=(0.1, 0.0), r=0.15)
        r = _target(b, x, uref, FB, ref["C_ref"])
        u1, C1, um1, _ = ss.solve(b, FB, x)
        rows.append({"alpha": al, "ritz": r["C_ritz"] / ref["C_ref"], "solve": C1 / C0, "umax": um1 / um0,
                     "imb": r["imbalance_rel"]})
    return ref, C0, base, rows


def test_v_sm_11_bmesh_baseline_reference(bmesh_amp):
    """결정 A ②: 베이스라인 자체 ρ = 1·C_ritz = C_ref = C_solve(같은 하중·같은 K), 안의 #63 꼴 재풀이 증폭(C ×3~130,
    umax ×10³~10⁴, 불평형 1.7~14 %)이 지표(ritz)에서는 ≤ 9 % 로 억제."""
    ref, C0, base, rows = bmesh_amp
    assert base["rho"] == pytest.approx(1.0, abs=1e-10) and ref["C_ref"] == pytest.approx(C0, rel=1e-10)
    assert base["C_ritz"] == pytest.approx(C0, rel=1e-10) and base["imbalance_rel"] <= 1e-9
    for r in rows:
        assert r["solve"] >= 3.0 and r["umax"] >= 1e3                    # 재풀이: #63 꼴 증폭
        assert abs(r["ritz"] - 1.0) <= 0.1 * r["alpha"]                  # 지표: 억제
        assert abs(r["solve"] - 1.0) > 20 * abs(r["ritz"] - 1.0)
    for p, q in itertools.pairwise(rows):
        assert q["ritz"] >= p["ritz"] and q["solve"] > p["solve"] and q["imb"] > p["imb"]
