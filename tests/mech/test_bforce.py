"""v0.24.0 경계력 ESL 조립(계약 esl_bforce.md §3, V-0240-a·b·e·i) — 합성 평판."""
import ast
import os

import numpy as np
import pytest

from esl.errors import EslError
from esl.mech import bforce as bf
from esl.mech import kabsch, supports
from esl.mech.mass import lumped_mass
from esl.mech.shell import ShellModel

E_MOD, NU, RHO = 2.1e5, 0.3, 7.85e-9


def rot(axis, ang):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K


def plate(nx=16, ny=10, Lx=300.0, Ly=200.0):
    xs, ys = np.linspace(0, Lx, nx + 1), np.linspace(0, Ly, ny + 1)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    Z = 10.0 * (1 - ((X - Lx / 2) / (Lx / 2)) ** 2)
    P = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1) + np.array([1000.0, 500.0, 200.0])
    nid = lambda i, j: i * (ny + 1) + j                                   # noqa: E731
    conn, et = [], []
    for i in range(nx):
        for j in range(ny):
            a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
            if i < 2:
                conn += [[a, b, c, -1], [a, c, d, -1]]
                et += [3, 3]
            else:
                conn.append([a, b, c, d])
                et.append(4)
    conn = np.array(conn, dtype=np.int64)
    et = np.array(et, dtype=np.int8)
    thk = np.full(conn.shape[0], 1.5)
    return {"x0": P, "conn": conn, "elem_type": et, "thickness": thk}


@pytest.fixture(scope="module")
def case():
    mesh = plate()
    X = mesh["x0"]
    N = X.shape[0]
    sm = ShellModel(X, mesh["conn"], mesh["elem_type"], mesh["thickness"], np.full(len(mesh["conn"]), E_MOD),
                    np.full(len(mesh["conn"]), NU))
    m = lumped_mass(mesh, RHO)
    rng = np.random.default_rng(7)
    # 매끈한 하중(면외 굽힘 + 약간의 면내) → 관성 이완으로 자기평형 F_true
    s = (X[:, 0] - X[:, 0].mean()) / 150.0
    t = (X[:, 1] - X[:, 1].mean()) / 100.0
    F0 = np.stack([2.0 * t, -1.0 * s, 30.0 * np.cos(np.pi * s) * np.cos(0.5 * np.pi * t)], axis=1)
    F_true = bf.inertia_relief(X, m, F0)["F_bal"]
    sup = supports.pick_321(X, np.asarray(supports.pca_corners(X)["idx"]))
    u6, _ = sm.solve(F_true, sup)
    u_def, _, _, _ = kabsch.remove_rigid(X, u6[:, :3])
    # 분해: tie(가장자리 노드 일부) + 관성(강체 감속 + 잡음) + 접촉 = 나머지
    edge = np.flatnonzero(np.isclose(X[:, 0], X[:, 0].min()) | np.isclose(X[:, 0], X[:, 0].max()))
    cont2 = np.zeros((N, 3))
    cont2[edge] = rng.normal(size=(edge.size, 3)) * 5.0 + np.array([0.0, 0.0, 20.0])
    acc = np.array([0.0, 0.0, -9810.0 * 200]) + rng.normal(size=(N, 3)) * 1e4
    cont = F_true - cont2 + m[:, None] * acc
    return {"mesh": mesh, "X": X, "sm": sm, "m": m, "F_true": F_true, "u_def": u_def, "sup": sup,
            "cont": cont, "cont2": cont2, "acc": acc, "N": N}


def _recon(c, F, u_rel):
    u6, Rr = c["sm"].solve(F, c["sup"])
    uv, _, _, _ = kabsch.remove_rigid(c["X"], u6[:, :3])
    return bf.recon_report(u_rel, uv, Rr, F)


def test_v0240_a_full_assembly_and_recon(case):
    c = case
    data = {"cont": c["cont"], "cont2": c["cont2"], "acc": c["acc"], "mass": c["m"], "fint": -c["F_true"]}
    a = bf.assemble(data, None, use_inertia=True)
    assert a["grade"] == "full" and a["mass_source"] == "h3d" and a["decomposed"]
    assert np.allclose(a["F"], c["F_true"], rtol=0, atol=1e-9 * np.abs(c["F_true"]).max())
    assert a["fint_sign"] == -1.0 and a["fint_sign_source"] == "full_match" and a["fint_check_rel"] < 1e-9
    out = bf.build(c["X"], None, data, None, use_inertia=True, balance="inertia_relief")
    d = out["doc"]
    assert d["corr_rel"] < 1e-9 and d["eq_raw"]["ref"]["force_rel"] < 1e-9 and d["limits"] == []
    rep = _recon(c, out["F_bal"], c["u_def"])
    assert rep["mac"] > 0.9999 and abs(rep["umax_err"]) < 1e-6 and rep["reaction_rel"] < 1e-9


def test_v0240_b_large_rotation(case):
    c = case
    Rot = rot([0.3, 1.0, 0.4], np.radians(40.0))
    tr = np.array([12.0, -300.0, 55.0])
    X = c["X"]
    u_tot = (X + c["u_def"]) @ Rot.T + tr - X
    u_rel, R, _, info = kabsch.remove_rigid(X, u_tot)
    assert info["rot_deg"] > 39.0
    g = lambda v: v @ Rot.T                                               # noqa: E731 — 변형 형상(회전) 전역 성분
    data = {"cont": g(c["cont"]), "cont2": g(c["cont2"]), "acc": g(c["acc"]), "mass": c["m"]}
    out = bf.build(X, u_tot, data, None, R=R, u_rel=u_rel)
    d = out["doc"]
    # 합성 F_true 는 기준 형상에서 평형 → 변형 형상 모멘트 잔차 = Σ u_def × F (기하 비선형 크기, 작음)
    assert d["eq_raw"]["def"]["force_rel"] < 1e-9 and d["eq_raw"]["def"]["moment_rel"] < 1e-3
    assert d["eq_raw"]["ref"]["moment_rel"] < 1e-3 and d["eq_bal"]["ref"]["moment_rel"] < 1e-12
    rep = _recon(c, out["F_bal"], u_rel)
    assert rep["mac"] > 0.999 and abs(rep["umax_err"]) < 0.02


def test_v0240_e_contact_grade_inertia_relief(case):
    c = case
    data = {"cont": c["cont"], "acc": c["acc"]}                          # tie(CONT2)·MASS 없음 = 현장 상태
    out = bf.build(c["X"], None, data, c["m"], use_inertia=True, balance="inertia_relief", g=9810.0)
    d = out["doc"]
    assert d["grade"] == "contact" and d["mass_source"] == "deck" and bf.LIMIT_TIE in d["limits"]
    assert any(w["code"] == "BF_MASS_APPROX" for w in d["warnings"])
    tie_sum = c["cont2"].sum(axis=0)
    assert np.allclose(d["omitted_f"], tie_sum, rtol=1e-9, atol=1e-9)    # 생략 tie 합력 = −ΣF
    M = c["m"].sum()
    assert np.allclose(np.asarray(d["abar"][:3]) * M, -tie_sum, rtol=1e-9, atol=1e-9)   # ā = ΣF/M
    assert d["abar_g"] == pytest.approx(np.linalg.norm(tie_sum) / M / 9810.0)
    assert d["eq_raw"]["ref"]["force_rel"] > 1e-3 and d["eq_bal"]["ref"]["force_rel"] < 1e-12
    assert d["eq_bal"]["ref"]["moment_rel"] < 1e-12 and d["corr_rel"] > 0
    rep = _recon(c, out["F_bal"], c["u_def"])
    assert rep["reaction_rel"] < 1e-9                                    # 관성 이완 후 3-2-1 반력 ≈ 0
    # balance none = 불평형이 반력으로
    o2 = bf.build(c["X"], None, data, c["m"], balance="none")
    assert _recon(c, o2["F_bal"], c["u_def"])["reaction_rel"] > 1e-3


def test_v0240_i_inertia_toggle_and_density(case):
    c = case
    data = {"cont": c["cont"], "acc": c["acc"]}
    on = bf.assemble(data, c["m"], use_inertia=True)
    off = bf.assemble(data, c["m"], use_inertia=False)
    assert off["parts"]["inertia"] is None and np.array_equal(off["F"], c["cont"])
    assert np.allclose(on["F"], c["cont"] - c["m"][:, None] * c["acc"])
    assert not any(w["code"] == "BF_MASS_APPROX" for w in off["warnings"])
    nacc = bf.assemble({"cont": c["cont"]}, c["m"], use_inertia=True)
    assert any(w["code"] == "BF_NO_ACC" for w in nacc["warnings"]) and np.array_equal(nacc["F"], c["cont"])
    rho, miss = bf.rho_per_elem([1, 1, 2, 3], [{"id": 1, "rho": 2.7e-9}, {"id": 2, "rho": None}, {"id": 3, "rho": 0.0}],
                                7.85e-9)
    assert rho.tolist() == [2.7e-9, 2.7e-9, 7.85e-9, 7.85e-9] and miss == [2, 3]
    m = lumped_mass(c["mesh"], 7.85e-9)
    from esl.mech.mass import elem_area_normal
    A, _ = elem_area_normal(c["X"], c["mesh"]["conn"], c["mesh"]["elem_type"])
    assert m.sum() == pytest.approx(float(np.sum(7.85e-9 * 1.5 * A)), rel=1e-12)


def test_v0240_grades_and_fint():
    n = 4
    z = np.zeros((n, 3))
    assert bf.grade_of({"cont", "cont2", "acc"}) == "full"
    assert bf.grade_of({"cont", "fint"}) == "fint"
    assert bf.grade_of({"cont", "acc", "mass"}) == "contact"
    assert bf.grade_of({"acc", "mass"}) == "none"
    with pytest.raises(EslError) as e:
        bf.assemble({"acc": z}, None)
    assert e.value.code == "BF_NO_DATA"
    Fi = np.arange(12.0).reshape(n, 3)
    a = bf.assemble({"fint": Fi}, None, u_rel=-Fi)                       # 일 양수 규칙 → s = −1
    assert a["grade"] == "fint" and a["fint_sign"] == -1.0 and a["fint_sign_source"] == "work_positive"
    assert bf.LIMIT_DECOMP in a["limits"]
    a2 = bf.assemble({"fint": Fi}, None, signs={"fint": 1})
    assert a2["fint_sign_source"] == "config" and np.array_equal(a2["F"], Fi)


def test_v0240_module_independent():
    p = os.path.join(os.path.dirname(bf.__file__), "bforce.py")
    tree = ast.parse(open(p, encoding="utf-8").read())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
    assert not any(m.startswith(("esl.doe", "esl.pipeline", "esl.io", "esl.library")) for m in mods)
    assert not ({"os", "io", "json", "pathlib", "pickle", "shutil", "yaml"} & mods)
