"""v0.24.0 보완 내력 ESL(계약 esl_fint.md §1·§4, V-0240-F-a·b·c·h) — 합성 평판 요소 내력."""
import numpy as np
import pytest

from esl.mech import bforce as bf
from esl.mech import kabsch, supports
from esl.mech.mass import elem_area_normal, lumped_mass
from esl.mech.shell import ShellModel

from tests.mech.test_bforce import E_MOD, NU, RHO, plate, rot


def _model(mesh, sel=None):
    conn = mesh["conn"] if sel is None else mesh["conn"][sel]
    et = mesh["elem_type"] if sel is None else mesh["elem_type"][sel]
    thk = mesh["thickness"] if sel is None else mesh["thickness"][sel]
    return ShellModel(mesh["x0"], conn, et, thk, np.full(len(conn), E_MOD), np.full(len(conn), NU))


@pytest.fixture(scope="module")
def fx():
    mesh = plate()
    X = mesh["x0"]
    sm = _model(mesh)
    m = lumped_mass(mesh, RHO)
    s = (X[:, 0] - X[:, 0].mean()) / 150.0
    t = (X[:, 1] - X[:, 1].mean()) / 100.0
    F0 = np.stack([2.0 * t, -1.0 * s, 3.0 * np.cos(np.pi * s) * np.cos(0.5 * np.pi * t)], axis=1)
    F_ext = bf.inertia_relief(X, m, F0)["F_bal"]                              # 자기평형 외력
    sup = supports.pick_321(X, np.asarray(supports.pca_corners(X)["idx"]))
    u6, _ = sm.solve(F_ext, sup)
    Fint6 = (sm.K() @ u6.reshape(-1)).reshape(-1, 6)                          # Σ_e K_e u_e (요소 내력 조립)
    u_rel, _, _, _ = kabsch.remove_rigid(X, u6[:, :3])
    return {"mesh": mesh, "X": X, "sm": sm, "m": m, "F_ext": F_ext, "sup": sup, "u6": u6, "Fint6": Fint6, "u_rel": u_rel}


def _recon(c, F):
    u6, Rr = c["sm"].solve(F, c["sup"])
    uv, _, _, _ = kabsch.remove_rigid(c["X"], u6[:, :3])
    return bf.recon_report(c["u_rel"], uv, Rr, F)


def test_v0240_f_a_element_internal_forces_self_equilibrated(fx):
    c = fx
    Fint = c["Fint6"][:, :3]
    assert np.abs(c["Fint6"][:, 3:]).max() < 1e-6 * np.abs(Fint).max()     # 외부 모멘트 없는 노드 = 노드 모멘트 ≈ 0
    # 대회전(35°)·병진 강체 운동을 얹은 t* 변형 형상: FINT 전역 = Q·F, 파트 Kabsch R 로 기준계 복원
    Q = rot([0.2, 0.9, -0.4], np.radians(35.0))
    ctr = c["X"].mean(axis=0)
    xdef = (c["X"] - ctr + c["u_rel"]) @ Q.T + ctr + np.array([5.0, -12.0, 300.0])
    u_tot = xdef - c["X"]
    _, R, _, _ = kabsch.remove_rigid(c["X"], u_tot)
    out = bf.fint_build(c["X"], u_tot, Fint @ Q.T, R=R, u_rel=c["u_rel"])
    d = out["doc"]
    assert d["source"] == "fint" and d["grade"] == "fint" and d["signs"]["fint"] == 1.0
    assert d["fint"]["residual"]["force_rel"] < 1e-9 and d["fint"]["unbalanced"] is False
    assert d["fint"]["balance_applied"] == "none" and d["corr_rel"] == 0.0 and out["m"] is None
    assert np.allclose(out["F_bal"], Fint, rtol=0, atol=1e-9 * np.abs(Fint).max())
    assert np.allclose(Fint, c["F_ext"], rtol=0, atol=1e-6 * np.abs(Fint).max())   # K u = F_ext(반력 ≈ 0)
    rep = _recon(c, out["F_bal"])
    assert rep["mac"] > 0.9999 and abs(rep["umax_err"]) < 1e-6 and rep["reaction_rel"] < 1e-9
    print(f"[V-0240-F-a] 잔차 {d['fint']['residual']['force_rel']:.2e}/{d['fint']['residual']['moment_rel']:.2e}, "
          f"재현 MAC {rep['mac']:.6f}, umax 오차 {rep['umax_err']:.1e}")


def test_v0240_f_c_sign_flip_auto(fx):
    c = fx
    Fint = c["Fint6"][:, :3]
    out = bf.fint_build(c["X"], None, -Fint, u_rel=c["u_rel"])              # Radioss 부호 반대 출력 가정
    assert out["doc"]["signs"]["fint"] == -1.0 and out["doc"]["fint_sign_source"] == "work_positive"
    assert np.allclose(out["F_bal"], Fint, rtol=0, atol=0)
    cfg = bf.fint_build(c["X"], None, -Fint, u_rel=c["u_rel"], sign=1)      # 설정 고정 = 그대로(복원 안 함)
    assert cfg["doc"]["fint_sign_source"] == "config" and np.array_equal(cfg["F_bal"], -Fint)


def test_v0240_f_b_shared_nodes_unbalanced(fx):
    """다른 부품(B) 요소가 대상(A) 경계 노드를 공유 → A 노드 FINT = K_A u + K_B u 의 A 행(B 힘 혼입) → 잔차 경고."""
    c = fx
    mesh = c["mesh"]
    X = c["X"]
    cen = X[mesh["conn"][:, 0], 0]
    A_el = cen < np.median(cen)
    nA = np.unique(mesh["conn"][A_el][mesh["conn"][A_el] >= 0])
    nB = np.unique(mesh["conn"][~A_el][mesh["conn"][~A_el] >= 0])
    shared = np.intersect1d(nA, nB)
    assert shared.size > 0
    smA, smB = _model(mesh, A_el), _model(mesh, ~A_el)
    fA = (smA.K() @ c["u6"].reshape(-1)).reshape(-1, 6)[:, :3]
    fB = (smB.K() @ c["u6"].reshape(-1)).reshape(-1, 6)[:, :3]
    XA = X[nA]
    clean = bf.fint_build(XA, None, fA[nA])                                  # A 요소만: 병진 합 = 0
    assert clean["doc"]["fint"]["residual"]["force_rel"] < 1e-9
    # 경계(공유) 노드는 B 와 굽힘 모멘트를 주고받음 — 병진 FINT 만으로는 모멘트 합이 남음(노드 모멘트 미사용 한계, §12)
    assert clean["doc"]["fint"]["residual"]["moment_rel"] > 1e-3
    links = {"status": "ok", "n_shared": int(shared.size), "by_part": {"2": int(shared.size)}, "n_rot": 0}
    mixed = bf.fint_build(XA, None, (fA + fB)[nA], links=links, tol_force=1e-3, tol_moment=1e-3)
    d = mixed["doc"]
    codes = [w["code"] for w in d["warnings"]]
    assert d["fint"]["unbalanced"] is True and "FINT_UNBALANCED" in codes and "FINT_SHARED_NODES" in codes
    assert d["fint"]["residual"]["force_rel"] > 1e-3 and d["fint"]["shared_nodes"]["n_shared"] == shared.size
    assert np.array_equal(mixed["F_raw"], (fA + fB)[nA])                     # 공유 노드 내력은 그대로 사용
    mA = lumped_mass({"x0": X, "conn": mesh["conn"][A_el], "elem_type": mesh["elem_type"][A_el],
                      "thickness": mesh["thickness"][A_el]}, RHO)[nA]
    rel = bf.fint_build(XA, None, (fA + fB)[nA], mA, mass_source="deck", balance="inertia_relief", links=links)
    assert rel["doc"]["fint"]["balance_applied"] == "inertia_relief" and rel["doc"]["mass_source"] == "deck"
    assert rel["doc"]["eq_bal"]["ref"]["force_rel"] < 1e-12 and rel["doc"]["corr_rel"] > 0
    ok_ = bf.fint_build(X, None, c["Fint6"][:, :3], c["m"], balance="inertia_relief")   # 잔차 작으면 이완 안 함
    assert ok_["doc"]["fint"]["balance_applied"] == "none"
    nm = bf.fint_build(XA, None, (fA + fB)[nA], None, balance="inertia_relief")
    assert "FINT_NO_MASS" in [w["code"] for w in nm["doc"]["warnings"]]
    rot_l = bf.fint_build(XA, None, fA[nA], links={"status": "ok", "n_shared": 0, "n_rot": 3, "rot": {"spring": 3}})
    assert rot_l["doc"]["limits"] == [bf.LIMIT_ROT] and bf.limit_text(rot_l["doc"]["limits"])[0].startswith("회전 연결")
    print(f"[V-0240-F-b] 공유 노드 {shared.size}, 잔차(혼입) {d['fint']['residual']['force_rel']:.3e}"
          f" / 모멘트 {d['fint']['residual']['moment_rel']:.3e}, A 만 {clean['doc']['fint']['residual']['force_rel']:.1e}")


def test_v0240_f_h_plastic_diag():
    mesh = plate(nx=4, ny=2)
    A, _ = elem_area_normal(mesh["x0"], mesh["conn"], mesh["elem_type"])
    ep = np.zeros(A.size)
    ep[[0, 3, 5]] = [0.01, 0.0015, 0.05]
    r = bf.plastic_diag(ep, A, 0.002)
    assert r["status"] == "ok" and r["n"] == 2 and r["max"] == 0.05 and r["n_total"] == A.size
    assert r["frac"] == pytest.approx((A[0] + A[5]) / A.sum(), rel=1e-12)
    assert bf.plastic_diag(None, A, 0.002) == {"status": "none"}
    assert bf.plastic_diag(np.full(A.size, np.nan), A, 0.002) == {"status": "none"}
