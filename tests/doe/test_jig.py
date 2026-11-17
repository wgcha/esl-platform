"""지그 순위 공용 모듈 esl/doe/jig.py — 계약 esl_jig_rank.md §8 Core 소유 시험.

V-JIG-1 정확 재현, V-JIG-2 하중 위치·크기 복원·법선 제약, V-JIG-3 물리 방향(리브 비드), V-JIG-4 상쇄·무른 모드 무관(#63 꼴),
V-JIG-5 전부 패치, V-JIG-16 혼합 보충, V-JIG-6(모듈) 지그 없음·퇴화, V-JIG-8 대규모 거리 메모리(slow), V-JIG-15 모드 무관 모듈.

시험 설정값(JIG)은 계약 §6 기본값 거울 — 정확 재현 시험만 ridge 0(기본 ridge 1e-8 은 열 정규화 정규방정식에서 ~1e-7 편향).
"""
from __future__ import annotations

import ast
import os
import re
import time
import tracemalloc

import numpy as np
import pytest
import synth_jig as sj
import synth_sm as ss

from esl.doe import jig
from esl.doe import stiffness_metric as smm
from esl.errors import EslError
from esl.mech import kabsch

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
JIG_PY = os.path.join(ROOT, "esl", "doe", "jig.py")
STAGES_PY = os.path.join(ROOT, "esl", "doe", "stages.py")

JIG = {"contact_gap_mm": 2.0, "knn": 8, "chunk_nodes": 65536, "max_regions": 8, "min_regions": 2, "min_region_nodes": 3,
       "min_region_area_mm2": 25.0, "patch_count": 6, "body_force": True, "basis_tangential": True, "n_modes": 4,
       "rho_t_mm3": 7.85e-9, "modes_sigma": 0.0, "modes_tol": 1.0e-8, "modes_maxiter": 2000, "w_inplane": 0.1,
       "reg_force": 1.0e-3, "reg_modes": 0.0, "ridge": 1.0e-8, "active_tol": 1.0e-3, "cancel_warn": 0.5}
EXACT = {"ridge": 0.0, "reg_force": 0.0, "n_modes": 0}     # 정확 재현 시험(정규화 편향 없음)


def _sel(c, surf="default", jig_idx=None, cand=None, surf_reason=None, **over):
    p = dict(JIG, **over)
    return jig.select_regions(c["mesh"], c["fit"] if cand is None else cand, c["J"] if jig_idx is None else jig_idx,
                              c["surf"] if isinstance(surf, str) else surf, gap_mm=p["contact_gap_mm"], knn=p["knn"],
                              chunk_nodes=p["chunk_nodes"], max_regions=p["max_regions"], min_regions=p["min_regions"],
                              min_nodes=p["min_region_nodes"], min_area_mm2=p["min_region_area_mm2"],
                              patch_count=p["patch_count"], weights=c["w"], surf_reason=surf_reason)


def _contact(c, **over):
    p = dict(JIG, **over)
    return jig.contact_regions(c["mesh"], c["fit"], c["surf"], gap_mm=p["contact_gap_mm"], knn=p["knn"],
                               chunk_nodes=p["chunk_nodes"], max_regions=p["max_regions"], min_regions=p["min_regions"],
                               min_nodes=p["min_region_nodes"], min_area_mm2=p["min_region_area_mm2"], weights=c["w"])


def _wfit(c):
    a = c["w"]["area"][c["fit"]]
    return a / a.mean()


def _modes(c, h, n, **over):
    p = dict(JIG, **over)
    N = c["mesh"]["x0"].shape[0]
    mass = jig.lumped_mass(c["w"], p["rho_t_mm3"])
    fixed = np.array([6 * q + d for q, d in h.cons], dtype=np.int64)
    md = jig.jig_modes(h.model.K(), jig.mass_diag6(mass), fixed, n, p["modes_sigma"], opinv=jig.opinv_from(h, N),
                       tol=p["modes_tol"], maxiter=p["modes_maxiter"])
    return md, jig.mode_loads(md["phi"], mass)


def _pipeline(c, u_ref, sel, **over):
    """베이스라인 경로(§2): target → factor → [모드] → basis → U → fit(모드 포함·제외) → respond(keep_u) → fit_report.
    over = JIG 키 덮어쓰기(기본 = 계약 §6 기본값)."""
    p = dict(JIG, **over)
    m, J, N = c["mesh"], c["J"], c["mesh"]["x0"].shape[0]
    fit, w = c["fit"], c["w"]
    td = jig.target_disp(m["x0"], u_ref, J, fit)
    h = jig.factor(m, J, sj.SOLVER)
    md, g = (None, None)
    if p["n_modes"] > 0:
        md, g = _modes(c, h, p["n_modes"], **over)
    B = jig.load_basis(m, sel["regions"], w, c["omega"], body_force=p["body_force"], tangential=p["basis_tangential"],
                       modes=g)
    br = jig.basis_response(h, B, fit)
    kw = {"ridge": p["ridge"], "w_inplane": p["w_inplane"], "reg_force": p["reg_force"], "reg_modes": p["reg_modes"]}
    args = (br["U"], td["u_tgt"][fit], w["area"][fit], w["normal"][fit], B)
    fl = jig.fit_loads(*args, **kw)
    unm = None
    if g is not None:
        fl0 = jig.fit_loads(*args, drop_kinds=(jig.COL_MODE,), **kw)
        unm = np.einsum("k,kmi->mi", fl0["a"], br["U"])
    F = jig.forces(B, fl["a"], N)
    row = jig.respond(h, [("E1", F)], keep_u=True)[0]
    rep = jig.fit_report(row["u"], td["u_tgt"], fit, w, B, fl["a"], jig_idx=J, active_tol=p["active_tol"],
                         u_fit_nomodes=unm)
    return {"td": td, "B": B, "h": h, "U": br, "fit": fl, "F": F, "row": row, "rep": rep, "modes": md}


def _rot(axis, deg):
    k = np.asarray(axis, float) / np.linalg.norm(axis)
    th = np.radians(deg)
    Kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * Kx + (1 - np.cos(th)) * Kx @ Kx


def _finite(x, u_el, deg=10.0, move=50.0, axis=(0.3, 1.0, -0.4)):
    """유한 강체 운동: u = R(x + u_el) + t − x (회전 deg°, 이동 |t| = move)."""
    R = _rot(axis, deg)
    t = move * np.array([0.6, -0.48, 0.64])
    return (x + u_el) @ R.T + t - x


@pytest.fixture(scope="module")
def base():
    return sj.case()


@pytest.fixture(scope="module")
def exact(base):
    """V-JIG-1·2: u_ref = K_jig⁻¹F(a_true)(접촉 3 + 체적력) + 임의 미소 강체."""
    c = base
    sel = _sel(c)
    assert sel["regions_from"] == "contact" and sel["n_contact"] == 3 and sel["n_patch"] == 0
    B = jig.load_basis(c["mesh"], sel["regions"], c["w"], c["omega"], body_force=True)
    a_true = np.zeros(B["nb"])
    a_true[[0, 1, 2]] = (50.0, 5.0, -3.0)          # 영역 0: 법선 + 접선
    a_true[[6, 8]] = (20.0, 4.0)                   # 영역 2
    a_true[-3:] = (1.5, -10.0, 0.5)                # 체적력 (영역 1 = 0)
    N = c["mesh"]["x0"].shape[0]
    u_true = sj.solve_jig(c["mesh"], c["J"], jig.forces(B, a_true, N))[0][:, :3]
    u_ref = _finite(c["mesh"]["x0"], u_true)                     # 회전 10°·이동 50 mm (u_el[J] = 0)
    assert np.abs(u_true[c["J"]]).max() == 0.0
    return {"c": c, "sel": sel, "a_true": a_true, "u_true": u_true, "u_ref": u_ref}


# ---------------------------------------------------------------- 기초
def test_node_weights_match_shell_area(base):
    m, w = base["mesh"], base["w"]
    sm = ss.model(m)
    sm.K()
    assert np.allclose(w["elem_area"], sm.area, rtol=1e-12, atol=0)
    assert w["area"].sum() == pytest.approx(sm.area.sum(), rel=1e-12)
    assert np.allclose(np.abs(w["normal"][:, 1]), 1.0) and np.allclose(w["thick"], 1.0)


def test_hash_view_drops_thresholds():
    cfg = dict(JIG, enabled=True, fix_kinds=list(jig.TIE_KINDS), mac_min=0.9, umax_err_max=0.2, tie_rel_warn=0.1,
               modes_ref321=True)
    hv = jig.hash_view(cfg)
    assert set(cfg) - set(hv) == set(jig.HASH_EXCLUDE) == {"mac_min", "umax_err_max", "tie_rel_warn", "cancel_warn",
                                                         "rho_t_mm3", "modes_ref321"}
    for k in ("n_modes", "modes_sigma", "modes_tol", "modes_maxiter", "w_inplane", "reg_force", "basis_tangential", "ridge"):
        assert hv[k] == cfg[k]
    assert "mac_min" in cfg                                              # 원본 불변


# ---------------------------------------------------------------- V-JIG-1
def test_v_jig_1_exact_reproduction(exact):
    c = exact["c"]
    r = _pipeline(c, exact["u_ref"], exact["sel"], **EXACT)
    um = np.abs(exact["u_true"]).max()
    assert r["td"]["rot_deg"] == pytest.approx(10.0, abs=1e-9)
    assert np.abs(r["td"]["u_tgt"] - exact["u_true"]).max() <= 1e-10 * um          # 미소 강체 제거
    rep = r["rep"]
    assert rep["mac"] >= 1 - 1e-10
    assert rep["umax_err"] <= 1e-8 and rep["err_p95"] <= 1e-8 and rep["resid_rel"] <= 1e-8
    assert r["row"]["react_rel"] <= 1e-9
    assert rep["tie_rel"] == pytest.approx(r["td"]["tie_rel"]) and rep["tie_rel"] <= 1e-9
    # 기본 ridge(1e-8)도 MAC 은 정확, umax 오차는 편향 수준
    rd = _pipeline(c, exact["u_ref"], exact["sel"], **dict(EXACT, ridge=JIG["ridge"]))["rep"]
    assert rd["mac"] >= 1 - 1e-10 and rd["umax_err"] <= 1e-6


# ---------------------------------------------------------------- V-JIG-2
def test_v_jig_2_load_recovery(exact):
    c, a_true = exact["c"], exact["a_true"]
    r = _pipeline(c, exact["u_ref"], exact["sel"], **EXACT)
    a = r["fit"]["a"]
    assert np.abs(a - a_true).max() <= 1e-6 * np.abs(a_true).max()
    act = [f["active"] for f in r["rep"]["forces"]]
    assert act == [True, False, True] and r["rep"]["n_active"] == 2
    assert r["fit"]["n_bound_active"] == 1 and r["fit"]["a"][3] == 0.0          # 0 영역 법선 = 경계
    # 영역 합력·몸체력 보고 = a
    f0 = r["rep"]["forces"][0]
    assert (f0["F_n"], f0["F_t1"], f0["F_t2"]) == pytest.approx((50.0, 5.0, -3.0), rel=1e-6)
    assert r["rep"]["body"] == pytest.approx([1.5, -10.0, 0.5], rel=1e-6)
    fs = sum(np.linalg.norm(f["F"]) for f in r["rep"]["forces"]) + np.linalg.norm(r["rep"]["body"])
    assert r["rep"]["F_sum_abs"] == pytest.approx(fs)
    # 상쇄비(D-JIG-17) = 1 − Σ_n‖Σ_k a_k f_k(n)‖ / Σ_kΣ_n‖a_k f_k(n)‖ — 열마다 하중을 만들어 직접 계산
    B, N = r["B"], c["mesh"]["x0"].shape[0]
    cols = [jig.forces(B, a[k] * np.eye(B["nb"])[k], N) for k in range(B["nb"])]
    den = sum(np.linalg.norm(f, axis=1).sum() for f in cols)
    num = np.linalg.norm(sum(cols), axis=1).sum()
    assert r["rep"]["F_col_abs"] == pytest.approx(den, rel=1e-12) and r["rep"]["F_node_abs"] == pytest.approx(num, rel=1e-12)
    assert r["rep"]["cancel_rel"] == pytest.approx(1 - num / den, abs=1e-12)


def test_v_jig_2_normal_bound(exact):
    """a_true 의 접촉 법선이 음수(당김)면 법선 ≥ 0 제약으로 해당 성분 = 0(경계 활성)·MAC < 1."""
    c, sel = exact["c"], exact["sel"]
    B = jig.load_basis(c["mesh"], sel["regions"], c["w"], c["omega"], body_force=True)
    assert list(B["reg_sign"]) == [1, 1, 1]
    a_bad = exact["a_true"].copy()
    a_bad[0] = -50.0
    N = c["mesh"]["x0"].shape[0]
    u = sj.solve_jig(c["mesh"], c["J"], jig.forces(B, a_bad, N))[0][:, :3]
    r = _pipeline(c, u, sel, **EXACT)
    assert r["fit"]["a"][0] == 0.0 and r["fit"]["n_bound_active"] >= 1
    assert r["rep"]["mac"] < 1 - 1e-6 and r["fit"]["resid_rel"] > 1e-6
    for k in (3, 6):                                                 # 다른 법선 열도 제약 만족
        assert r["fit"]["a"][k] >= 0.0


def test_v_jig_2_contact_normal_direction(base):
    """접촉 법선 = 상대 부품 → 대상(+Y 판 2개는 −Y, −Y 브릭은 +Y)."""
    c = base
    sel = _sel(c)
    B = jig.load_basis(c["mesh"], sel["regions"], c["w"], c["omega"], body_force=True)
    parts = [r["part"] for r in sel["regions"]]
    ny = dict(zip(parts, B["reg_dir"][:, 0, 1]))
    assert ny[sj.NEIGHBOR_PARTS["shell_a"]] == pytest.approx(-1.0) and ny[sj.NEIGHBOR_PARTS["shell_b"]] == pytest.approx(-1.0)
    assert ny[sj.NEIGHBOR_PARTS["brick"]] == pytest.approx(1.0)
    for r in range(B["reg_dir"].shape[0]):                           # 정규 직교 틀
        assert np.allclose(B["reg_dir"][r] @ B["reg_dir"][r].T, np.eye(3), atol=1e-12)
    for r in range(len(parts)):
        s, e = B["reg_ptr"][r], B["reg_ptr"][r + 1]
        assert B["reg_w"][s:e].sum() == pytest.approx(1.0, abs=1e-14)
    assert B["body_w"].sum() == pytest.approx(1.0, abs=1e-14) and B["nb"] == 3 * len(parts) + 3


# ---------------------------------------------------------------- V-JIG-3
def test_v_jig_3_rib_monotone(exact):
    c = exact["c"]
    r = _pipeline(c, exact["u_ref"], exact["sel"])                 # 기본 설정(모드 4·정규화)
    loads = [("E1", r["F"])]
    rows = {}
    for al in (0.0, 0.5, 1.0):
        md = dict(c["mesh"], x0=sj.rib_x(c["mesh"], al))
        rows[al] = jig.design_response(md, c["J"], loads, sj.SOLVER)
    base = r["row"]
    d0 = rows[0.0]["rows"][0]
    assert d0["C_jig"] == base["C_jig"] and d0["umax_jig"] == base["umax_jig"]      # 같은 경로 → score(d000) = 1 정확
    sc = {al: rows[al]["rows"][0]["C_jig"] / base["C_jig"] for al in rows}
    um = {al: rows[al]["rows"][0]["umax_jig"] / base["umax_jig"] for al in rows}
    assert sc[1.0] < sc[0.5] < 1.0 and um[1.0] < um[0.5] < 1.0
    for al in rows:
        assert rows[al]["rows"][0]["react_rel"] <= 1e-9 and rows[al]["rows"][0]["u"] is None
        st = rows[al]["stats"]
        assert st["n_solves"] == 1 and st["backend"] == "superlu" and st["seconds"] >= 0


# ---------------------------------------------------------------- V-JIG-4
@pytest.fixture(scope="module")
def soft_amp():
    """#63 꼴(V-SM-3·11): 긴 얇은 판(600×100, t 0.8) — 낙하 변위 = 중앙 가압(아래 부품이 밂) 지그 응답 + 국부 막 압축(s = −0.5,
    #63 의 거대 상쇄 하중원), F_ESL = K₀u_drop. 국부 비드(막 압축 위치) α 0.1/0.5/1.
    재풀이(3-2-1): 같은 F_ESL. 지그: 기준 맞춤 하중 F_jig(접촉 2 = pusher·shell_b, 체적력) 하중 제어 재풀이."""
    m = ss.plate(nx=60, ny=10, Lx=600.0, Lz=100.0, t=0.8, bow=0.0, n_tria_cols=6)
    N = m["x0"].shape[0]
    J = sj.jig_of(sj.tie_groups(m, n_groups=4))
    omega = np.ones(N, bool)
    fit = omega.copy()
    fit[J] = False
    c = {"mesh": m, "J": J, "omega": omega, "fit": fit, "w": jig.node_weights(m),
         "surf": sj.surface(sj.neighbors(m, gap=1.0, which=("pusher", "shell_b")))}
    sel = _sel(c)
    assert sel["regions_from"] == "contact" and sel["n_contact"] == 2
    B = jig.load_basis(m, sel["regions"], c["w"], omega, body_force=True)
    a0 = np.zeros(B["nb"])
    a0[0] = 20.0                                                   # pusher 법선 20 N
    u_push = sj.solve_jig(m, J, jig.forces(B, a0, N))[0][:, :3]
    u_in = ss.drop_u(m, amp=5.0, dent=(-0.5, 0.0), w=0.05)
    u_in[:, 1] = 0.0
    F_esl = ss.esl_force(m, u_push + u_in)
    u0, C0, um0, _ = ss.solve(m, F_esl)
    uref = smm.remove_rigid(m["x0"], u0)
    r = _pipeline(c, uref[:, :3], sel)                             # 기본 설정(모드 4·w_inplane 0.1·reg_force 1e-3)
    rows = []
    for al in (0.1, 0.5, 1.0):
        x = ss.bead_x(m, al, depth=10.0, center=(-0.5, 0.0), r=0.15)
        _, C1, um1, _ = ss.solve(m, F_esl, x)
        imb = smm.metrics(smm.stiffness(dict(m, x0=x)), uref, F_esl, C0)["imbalance_rel"]
        d = jig.design_response(dict(m, x0=x), J, [("E1", r["F"])], sj.SOLVER)["rows"][0]
        rows.append({"alpha": al, "solve": C1 / C0, "umax": um1 / um0, "imb": imb,
                     "score_jig": d["C_jig"] / r["row"]["C_jig"], "umax_jig": d["umax_jig"] / r["row"]["umax_jig"],
                     "react": d["react_rel"]})
    ud = u_push + u_in
    oop = float(np.sum(ud[:, 1] ** 2) / np.sum(ud ** 2))           # 면외(Y) 성분 비(에너지 아닌 변위 제곱합)
    return {"r": r, "rows": rows, "esl_abs": float(np.linalg.norm(F_esl, axis=1).sum()), "oop_frac": oop}


def test_v_jig_4_solve_amplified_jig_stable(soft_amp):
    r, rows = soft_amp["r"], soft_amp["rows"]
    rep = r["rep"]
    assert r["row"]["react_rel"] <= 1e-9 and rep["mac"] >= 0.99
    for x in rows:
        assert x["umax"] >= 10 and x["imb"] >= 0.05                   # 재풀이(3-2-1) 증폭 재현
        assert x["react"] <= 1e-9
        assert x["umax_jig"] <= 3
        assert abs(x["score_jig"] - 1) <= abs(x["solve"] - 1) / 5
    # 면외 지배 목표(u_drop 면외 ≥ 90 %) → 상쇄 없음·작은 하중
    assert soft_amp["oop_frac"] >= 0.9
    assert rep["cancel_rel"] <= 0.5
    assert rep["F_sum_abs"] / soft_amp["esl_abs"] <= 0.1


# ---------------------------------------------------------------- V-JIG-17~21 공용 픽스처
def _wide(which=("shell_a", "shell_b", "brick")):
    """§1(5) 근거 합성: synth_sm.plate 600×300 t 0.8, 짧은 두 변 tie 6 묶음."""
    m = ss.plate(nx=30, ny=15, Lx=600.0, Lz=300.0, t=0.8, bow=0.0, n_tria_cols=4)
    N = m["x0"].shape[0]
    J = sj.jig_of(sj.tie_groups(m, n_groups=6, z_pos=(0.15, 0.5, 0.85)))
    omega = np.ones(N, bool)
    fit = omega.copy()
    fit[J] = False
    surf = sj.surface(sj.neighbors(m, gap=1.0, which=which)) if which else None
    return {"mesh": m, "J": J, "omega": omega, "fit": fit, "w": jig.node_weights(m), "surf": surf}


@pytest.fixture(scope="module")
def wide():
    return _wide()


class _NoEigsh:
    calls = 0

    def __call__(self, *a, **k):
        type(self).calls += 1
        raise AssertionError("eigsh 호출 금지")


# ---------------------------------------------------------------- V-JIG-17
def test_v_jig_17_mode_inertia(wide, monkeypatch):
    c = wide
    m, J, N = c["mesh"], c["J"], c["mesh"]["x0"].shape[0]
    h = jig.factor(m, J, sj.SOLVER)
    md, _ = _modes(c, h, JIG["n_modes"])
    assert md["ok"] and md["n_conv"] == 4 and np.all(np.diff(md["lam"]) > 0) and md["phi"].shape == (4, N, 6)
    assert np.allclose(md["hz"], np.sqrt(md["lam"]) / (2 * np.pi))
    mass = jig.lumped_mass(c["w"], JIG["rho_t_mm3"])
    md2 = jig.jig_modes(h.model.K(), jig.mass_diag6(mass), np.array([6 * q + d for q, d in h.cons]), 4, 0.0,
                        tol=JIG["modes_tol"], maxiter=JIG["modes_maxiter"])            # splu 경로 = 분해 재사용 경로
    assert np.allclose(md2["lam"], md["lam"], rtol=1e-8)
    g = jig.mode_loads(md["phi"], mass)
    assert np.allclose(np.linalg.norm(g, axis=2).sum(axis=1), 1.0, rtol=1e-12)
    for k in range(4):
        v = g[k].ravel()
        assert v[np.argmax(np.abs(v))] > 0
    cmix = (0.0, 0.5, 1.0, 0.0)                                          # 모드 2·3 섞음
    Ft = sum(ck * mass[:, None] * md["phi"][k, :, :3] for k, ck in enumerate(cmix))
    u = h.solve(Ft)[0][:, :3]
    sel = _sel(c)
    r = _pipeline(c, u, sel)                                            # 기본 설정(reg_modes 0 — D-JIG-17)
    wm, wo = r["rep"]["with_modes"], r["rep"]["without_modes"]
    assert wm["mac"] >= 1 - 1e-10 and wm["umax_err"] <= 1e-6 and r["rep"]["mac"] == wm["mac"]
    # 단일 열의 자기평형(고차 모드 합력 ≈ 0)은 상쇄 아님
    assert r["rep"]["cancel_rel"] <= 0.5
    rp = _pipeline(c, u, sel, reg_modes=1e-3)["rep"]                     # 모드 정규화를 켜면 고차 모드 열이 줄어 손실
    assert rp["mac"] < wm["mac"]
    assert wo["mac"] <= 0.95 and wm["mac"] - wo["mac"] >= 0.05
    assert [x["k"] for x in r["rep"]["modes"]] == [0, 1, 2, 3]
    B = r["B"]
    assert list(B["col_kind"][-4:]) == [4] * 4 and B["mode_f"].shape == (4, N, 3)
    # jig.npz 밀도 키(§5.5)
    dn = jig.load_density(B, c["w"])
    R = B["reg_dir"].shape[0]
    assert dn["node_area"].shape == (N,) and dn["reg_area"].shape == (R,) and dn["reg_q"].shape == (R, 3, 3)
    assert dn["body_q"].shape == (N,) and dn["mode_q"].shape == (4, N, 3)
    assert np.abs(dn["mode_q"] * dn["node_area"][None, :, None] - B["mode_f"]).max() <= 1e-12 * np.abs(B["mode_f"]).max()
    assert np.allclose(dn["body_q"] * dn["node_area"], B["body_w"], rtol=0, atol=1e-15)
    for q in range(R):
        s0, e0 = B["reg_ptr"][q], B["reg_ptr"][q + 1]
        assert dn["reg_area"][q] == pytest.approx(c["w"]["area"][B["reg_node"][s0:e0]].sum())
        assert np.allclose(dn["reg_q"][q] * dn["reg_area"][q], B["reg_dir"][q])
    # 안 평가 = 고정 하중 벡터 재풀이(모드 재계산 없음)
    monkeypatch.setattr(jig, "eigsh", _NoEigsh())
    _NoEigsh.calls = 0
    d = jig.design_response(dict(m, x0=sj.rib_x(m, 0.5)), J, [("E1", r["F"])], sj.SOLVER)
    assert _NoEigsh.calls == 0 and d["rows"][0]["C_jig"] > 0


# ---------------------------------------------------------------- V-JIG-18 (모듈)
def test_v_jig_18_modes_off_identical(exact, monkeypatch):
    c = exact["c"]
    monkeypatch.setattr(jig, "eigsh", _NoEigsh())
    _NoEigsh.calls = 0
    r = _pipeline(c, exact["u_ref"], exact["sel"], n_modes=0)
    assert _NoEigsh.calls == 0 and r["rep"]["without_modes"] is None and r["rep"]["modes"] == []
    assert r["B"]["mode_f"] is None and jig.COL_MODE not in r["B"]["col_kind"]
    # 모드 인수 없는 옛 호출 경로와 비트 동일
    m, J, N = c["mesh"], c["J"], c["mesh"]["x0"].shape[0]
    B0 = jig.load_basis(m, exact["sel"]["regions"], c["w"], c["omega"], body_force=True)
    B1 = jig.load_basis(m, exact["sel"]["regions"], c["w"], c["omega"], body_force=True, tangential=True,
                        modes=np.zeros((0, N, 3)))
    for k in B0:
        v0, v1 = B0[k], B1[k]
        assert (v0 is None and v1 is None) or np.array_equal(v0, v1), k
    for k in ("reg_ptr", "reg_node", "reg_w", "reg_dir", "col_kind"):
        assert np.array_equal(B0[k], r["B"][k])
    assert np.array_equal(jig.forces(B0, r["fit"]["a"], N), r["F"])
    assert jig.load_density(B0, c["w"])["mode_q"] is None


# ---------------------------------------------------------------- V-JIG-19 (모듈)
def test_v_jig_19_modes_failure(wide, monkeypatch):
    from scipy.sparse.linalg import ArpackNoConvergence
    c = wide
    m, J, N = c["mesh"], c["J"], c["mesh"]["x0"].shape[0]
    h = jig.factor(m, J, sj.SOLVER)
    mass = jig.lumped_mass(c["w"], JIG["rho_t_mm3"])
    M6 = jig.mass_diag6(mass)
    fixed = np.array([6 * q + d for q, d in h.cons])
    md, _ = _modes(c, h, 4)
    free = np.setdiff1d(np.arange(6 * N), fixed)
    v1 = md["phi"][0].ravel()[free][:, None]
    real = jig.eigsh

    def partial(*a, **k):
        raise ArpackNoConvergence("no conv", np.array([md["lam"][0]]), v1)

    monkeypatch.setattr(jig, "eigsh", partial)
    r1 = jig.jig_modes(h.model.K(), M6, fixed, 4, 0.0, opinv=jig.opinv_from(h, N))
    assert not r1["ok"] and r1["n_conv"] == 1 and r1["err"] == "ARPACK_NO_CONVERGENCE"
    assert np.allclose(np.abs(r1["phi"][0]), np.abs(md["phi"][0]))
    g1 = jig.mode_loads(r1["phi"], mass)                                 # 수렴분만으로 진행
    B = jig.load_basis(m, _sel(c)["regions"], c["w"], c["omega"], body_force=True, modes=g1)
    assert int((B["col_kind"] == jig.COL_MODE).sum()) == 1

    def none(*a, **k):
        raise ArpackNoConvergence("no conv", np.zeros(0), np.zeros((free.size, 0)))

    monkeypatch.setattr(jig, "eigsh", none)
    with pytest.raises(EslError) as e:
        jig.jig_modes(h.model.K(), M6, fixed, 4, 0.0, opinv=jig.opinv_from(h, N))
    assert e.value.code == "JIG_MODES_FAILED" and e.value.detail["n_conv"] == 0
    monkeypatch.setattr(jig, "eigsh", real)
    # OPinv 회전 우변: 회전 질량이 있으면 M·x 에 회전 성분 → 지그 분해 재사용 불가
    op = jig.opinv_from(h, N)
    b = np.zeros(free.size)
    rot = np.flatnonzero(free % 6 >= 3)
    b[rot[0]] = 1.0
    with pytest.raises(EslError) as e:
        op.matvec(b)
    assert e.value.code == "JIG_MODES_FAILED"
    M6r = M6.copy()
    M6r[3::6] = mass
    with pytest.raises(EslError) as e:
        jig.jig_modes(h.model.K(), M6r, fixed, 4, 0.0, opinv=jig.opinv_from(h, N))
    assert e.value.code == "JIG_MODES_FAILED" and e.value.detail["n_conv"] == 0


# ---------------------------------------------------------------- V-JIG-20
def test_v_jig_20_finite_rotation_target(exact):
    c = exact["c"]
    x, J, fit = c["mesh"]["x0"], c["J"], c["fit"]
    u_el = exact["u_true"]

    def linear(u):
        _, a, w = kabsch.remove_linear_rigid(x[J], u[J])
        return u - a - np.cross(w, x - x[J].mean(axis=0))

    # (a) 작은 회전: 두 경로 일치. 차 = O(θ·umax + θ²L)(선형 경로는 탄성분도 회전된 채 남김) → 1e-6·umax 는 θ ≲ 1e-6 rad
    L = float(np.ptp(x, axis=0).max())
    for deg in (5e-5, 0.01, 0.1):
        u_s = _finite(x, u_el, deg=deg, move=2.0)
        ts = jig.target_disp(x, u_s, J, fit)
        th = np.radians(deg)
        diff = np.abs(ts["u_tgt"] - linear(u_s)).max()
        assert diff <= 2 * (th * ts["umax_tgt"] + th ** 2 * L)
        assert ts["rot_deg"] == pytest.approx(deg, rel=1e-6)
        if deg == 5e-5:
            assert diff <= 1e-6 * ts["umax_tgt"]
    # (b) 회전 10° 순수 강체 + 면외 굽힘
    u_b = _finite(x, u_el, deg=10.0, move=50.0)
    tb = jig.target_disp(x, u_b, J, fit)
    assert np.abs(tb["u_tgt"] - u_el).max() <= 1e-10 * np.abs(u_el).max()
    assert np.abs(linear(u_b) - u_el).max() >= 1e-3 * L                # 선형 경로 = O(θ²L) 면내 잔여
    # (c) 보고
    assert tb["rot_deg"] == pytest.approx(10.0, abs=1e-9) and np.allclose(tb["R"], _rot((0.3, 1.0, -0.4), 10.0))
    assert tb["tie_rel"] <= 1e-10 and tb["t"].shape == (3,)


# ---------------------------------------------------------------- V-JIG-21 (모듈)
@pytest.fixture(scope="module")
def reg_case():
    """§1(5) 근거 재현: 패치 6 + 체적력(+ 모드 4 기본), 정확 목표 = 법선 가압 3 + 면외 체적력."""
    c = _wide(which=None)
    m, J, N = c["mesh"], c["J"], c["mesh"]["x0"].shape[0]
    sel = _sel(c, surf=None)
    assert sel["regions_from"] == "patch" and sel["n_patch"] == 6
    B = jig.load_basis(m, sel["regions"], c["w"], c["omega"], body_force=True)
    R = len(sel["regions"])
    a_true = np.zeros(B["nb"])
    a_true[[0, 3, 9]] = (60.0, 25.0, 40.0)
    a_true[3 * R + 1] = -30.0
    u_ex = sj.solve_jig(m, J, jig.forces(B, a_true, N))[0][:, :3]
    X = m["x0"]
    s = 2 * (X[:, 0] - X[:, 0].min()) / np.ptp(X[:, 0]) - 1
    t = 2 * (X[:, 2] - X[:, 2].min()) / np.ptp(X[:, 2]) - 1
    g = np.exp(-(s ** 2 + t ** 2) / 0.1)
    u_in = np.zeros((N, 3))
    u_in[:, 0], u_in[:, 2] = -s * g, -t * g                             # 면내 자기평형(수렴) 잔여
    u_in *= 0.05 * np.abs(u_ex[:, 1]).max() / np.linalg.norm(u_in, axis=1).max()
    return {"c": c, "sel": sel, "u_ex": u_ex, "u_in": u_in, "F_exact": float(np.abs(a_true).sum())}


def test_v_jig_21_normal_weight_regularization(reg_case):
    c, sel = reg_case["c"], reg_case["sel"]
    # (a) 정확 목표 — reg 1e-3 손실 없음
    ra = _pipeline(c, reg_case["u_ex"], sel)["rep"]
    assert 1 - ra["mac"] <= 1e-3 and ra["umax_err"] <= 1e-3
    # (b) + 면내 자기평형 잔여: 기본 = 상쇄 없음, 정규화 끔·면내 가중 1 = 상쇄
    u = reg_case["u_ex"] + reg_case["u_in"]
    rb = _pipeline(c, u, sel)["rep"]
    assert rb["cancel_rel"] <= JIG["cancel_warn"] and rb["F_sum_abs"] <= 1.1 * reg_case["F_exact"]
    r0 = _pipeline(c, u, sel, reg_force=0.0, w_inplane=1.0)["rep"]
    assert r0["F_sum_abs"] > 100 * reg_case["F_exact"]                  # 정규화 끔 = 면내 하중 폭주(정보 지표로 보임)
    # D-JIG-17 상쇄비는 같은 노드에서 열끼리 지우는 것만 잼 — 서로 다른 패치의 반대 방향 면내 하중은 노드가 달라 잡히지 않음
    assert r0["cancel_rel"] < rb["cancel_rel"] + 0.5 and r0["F_node_abs"] > 100 * reg_case["F_exact"]
    # (c) 법선만
    rc = _pipeline(c, u, sel, basis_tangential=False)
    B = rc["B"]
    assert jig.COL_TANGENT not in B["col_kind"] and B["nb"] == len(sel["regions"]) + 3 + JIG["n_modes"]
    assert all(f["F_t1"] == 0.0 and f["F_t2"] == 0.0 for f in rc["rep"]["forces"])
    assert rc["row"]["react_rel"] <= 1e-9


def test_fit_loads_g_N_and_drop(reg_case):
    """ḡ_N = 법선 열 G_kk 평균, drop_kinds 열 a = 0."""
    c, sel = reg_case["c"], reg_case["sel"]
    r = _pipeline(c, reg_case["u_ex"], sel)
    fit = c["fit"]
    U = r["U"]["U"]
    aw = c["w"]["area"][fit] / c["w"]["area"][fit].mean()
    n = c["w"]["normal"][fit]
    ck = r["B"]["col_kind"]
    Gd = [float(np.sum(aw[:, None] * (0.1 * U[k] + 0.9 * np.sum(U[k] * n, axis=1)[:, None] * n) * U[k]))
          for k in np.flatnonzero(ck == jig.COL_NORMAL)]
    assert r["fit"]["g_N"] == pytest.approx(np.mean(Gd), rel=1e-12)
    td = r["td"]
    f0 = jig.fit_loads(U, td["u_tgt"][fit], c["w"]["area"][fit], n, r["B"], ridge=JIG["ridge"], w_inplane=0.1,
                       reg_force=1e-3, drop_kinds=(jig.COL_MODE, jig.COL_BODY))
    assert np.all(f0["a"][np.isin(ck, (jig.COL_MODE, jig.COL_BODY))] == 0.0)


# ---------------------------------------------------------------- V-JIG-5
def test_v_jig_5_all_patch(base):
    c = base
    for surf, reason, want in ((None, None, "no_deck"), (None, "surf_failed", "surf_failed"),
                               (sj.surface([]), None, "few_contact")):
        s1 = _sel(c, surf=surf, surf_reason=reason)
        s2 = _sel(c, surf=surf, surf_reason=reason)
        assert s1["regions_from"] == "patch" and s1["fill_reason"] == want and s1["n_contact"] == 0
        assert s1["n_patch"] == min(JIG["patch_count"], JIG["max_regions"], s1["n_cells"]) == len(s1["regions"]) > 0
        for a, b in zip(s1["regions"], s2["regions"]):                # 비트 동일
            assert np.array_equal(a["nodes"], b["nodes"]) and a["area"] == b["area"]
            assert np.array_equal(a["center"], b["center"])
        allp = np.concatenate([r["nodes"] for r in s1["regions"]])
        assert np.intersect1d(allp, c["J"]).size == 0 and np.unique(allp).size == allp.size
        assert all(r["kind"] == jig.REGION_PATCH and r["part"] == -1 for r in s1["regions"])
        B = jig.load_basis(c["mesh"], s1["regions"], c["w"], c["omega"], body_force=True)
        assert not B["reg_sign"].any() and set(B["reg_kind"]) == {jig.REGION_PATCH}
        for r in range(B["reg_dir"].shape[0]):                       # 부호 자유 = 최대 절댓값 성분 양수
            n = B["reg_dir"][r, 0]
            assert n[np.argmax(np.abs(n))] > 0
    # 패치 크기 격자는 P 고정 → 정렬 키 (−면적, 최소 노드)
    ar = [r["area"] for r in s1["regions"]]
    assert ar == sorted(ar, reverse=True)


# ---------------------------------------------------------------- V-JIG-16
def test_v_jig_16_mixed_fill(base):
    c = dict(base, surf=sj.surface(sj.neighbors(base["mesh"], gap=1.0, which=("shell_a",))))
    only = _contact(c, min_regions=3)
    assert len(only["regions"]) == 1 and not only["ok"]
    s = _sel(c, min_regions=3)
    assert s["regions_from"] == "mixed" and s["n_contact"] == 1 and s["n_patch"] == 2 and s["fill_reason"] == "few_contact"
    rc = s["regions"][0]
    ro = only["regions"][0]
    assert rc["kind"] == jig.REGION_CONTACT and rc["part"] == sj.NEIGHBOR_PARTS["shell_a"]
    for k in ("nodes", "center", "sign_ref"):                        # 접촉만일 때와 비트 동일
        assert np.array_equal(rc[k], ro[k])
    assert rc["area"] == ro["area"]
    assert [r["kind"] for r in s["regions"]] == [1, 2, 2]             # 순서 접촉 → 패치
    pn = np.concatenate([r["nodes"] for r in s["regions"][1:]])
    assert np.intersect1d(pn, np.union1d(rc["nodes"], c["J"])).size == 0
    B = jig.load_basis(c["mesh"], s["regions"], c["w"], c["omega"], body_force=True)
    assert list(B["reg_kind"]) == [1, 2, 2] and list(B["reg_sign"]) == [1, 0, 0]
    assert list(B["reg_part"]) == [sj.NEIGHBOR_PARTS["shell_a"], -1, -1]
    # 접촉 ≥ min_regions → 보충 없음
    s3 = _sel(base)
    assert s3["regions_from"] == "contact" and s3["n_patch"] == 0 and s3["fill_reason"] is None
    # 후보 소진: 후보 = 접촉 노드 + 일부 → 패치 후보 비어 n_patch < n_fill
    cand = np.zeros(c["fit"].size, bool)
    cand[rc["nodes"]] = True
    se = _sel(c, cand=cand, min_regions=3)
    assert se["n_contact"] == 1 and se["n_fill"] == 2 and se["n_patch"] == 0 and se["regions_from"] == "contact"
    assert se["fill_reason"] == "few_contact"
    # 보충 영역 포함 정확 재현
    N = c["mesh"]["x0"].shape[0]
    a_true = np.zeros(B["nb"])
    a_true[[0, 3, 4, 7, 8]] = (30.0, 6.0, -2.0, -4.0, 1.0)
    a_true[-2] = -3.0
    u = _finite(c["mesh"]["x0"], sj.solve_jig(c["mesh"], c["J"], jig.forces(B, a_true, N))[0][:, :3], deg=3.0, move=5.0)
    r = _pipeline(c, u, s, **EXACT)
    assert r["rep"]["mac"] >= 1 - 1e-10 and np.abs(r["fit"]["a"] - a_true).max() <= 1e-6 * np.abs(a_true).max()
    assert [f["kind"] for f in r["rep"]["forces"]] == ["contact", "patch", "patch"]
    assert r["rep"]["forces"][1]["part"] is None


# ---------------------------------------------------------------- V-JIG-6 (모듈)
def test_v_jig_6_no_tie_and_degenerate(base):
    from esl.doe.paicad_io import FIXED_KINDS
    m = base["mesh"]
    ids = m["node_id"][base["J"]]
    tie_bits = sum(1 << FIXED_KINDS.index(k) for k in jig.TIE_KINDS)
    rbe2 = np.full(ids.size, 1 << FIXED_KINDS.index("RBE2"))
    r = jig.select_jig_nodes(m, ids, kind_mask=rbe2, kind_bits=tie_bits)
    assert r["code"] == "JIG_NO_TIE" and r["idx"].size == 0
    km = np.where(np.arange(ids.size) % 2 == 0, 1 << FIXED_KINDS.index("INTER_TYPE2_MAIN"), rbe2)
    r = jig.select_jig_nodes(m, ids, kind_mask=km, kind_bits=tie_bits)
    assert r["code"] is None and np.array_equal(r["node_id"], ids[::2])
    r = jig.select_jig_nodes(m, np.concatenate([ids, [10 ** 9, 10 ** 9 + 1]]))   # 메시에 없는 ID 버림
    assert r["code"] is None and np.array_equal(r["idx"], base["J"]) and r["detail"]["n_missing"] == 2
    assert jig.select_jig_nodes(m, [])["code"] == "JIG_NO_TIE"
    # 공선 3점
    X = m["x0"]
    line = np.flatnonzero(np.isclose(X[:, 2], X[:, 2].min()))[:3]
    r = jig.select_jig_nodes(m, m["node_id"][line])
    assert r["code"] == "JIG_SUPPORT_DEGENERATE" and r["detail"]["bad_comp_nodes"] == [X.shape[0]]
    with pytest.raises(EslError) as e:                               # 분해 시도 시에도 같은 코드
        jig.factor(m, line, sj.SOLVER)
    assert e.value.code == "JIG_SUPPORT_DEGENERATE"
    # 성분 하나에 지그 없음(판 2장)
    m2 = sj.plate(nx=6, ny=4)
    n2 = m2["x0"].shape[0]
    two = {"node_id": np.concatenate([m2["node_id"], m2["node_id"] + 1000]),
           "x0": np.concatenate([m2["x0"], m2["x0"] + [0.0, 50.0, 0.0]]),
           "conn": np.concatenate([m2["conn"], np.where(m2["conn"] >= 0, m2["conn"] + n2, -1)]),
           "elem_type": np.concatenate([m2["elem_type"]] * 2), "thickness": np.concatenate([m2["thickness"]] * 2)}
    g = sj.jig_of(sj.tie_groups(m2, n_groups=2))
    r = jig.select_jig_nodes(two, two["node_id"][g])
    assert r["code"] == "JIG_SUPPORT_DEGENERATE" and r["n_comp"] == 2 and r["detail"]["bad_comp_nodes"] == [n2]
    r = jig.select_jig_nodes(two, two["node_id"][np.concatenate([g, g + n2])])
    assert r["code"] is None and r["n_comp"] == 2


# ---------------------------------------------------------------- V-JIG-8 (slow)
def _grid(n, L, y, off=0.0):
    xs = np.linspace(0.0, L, n + 1) + off
    X = np.zeros(((n + 1) ** 2, 3))
    X[:, 0] = np.repeat(xs, n + 1)
    X[:, 2] = np.tile(xs, n + 1)
    X[:, 1] = y
    i, j = (a.ravel() for a in np.meshgrid(np.arange(n), np.arange(n), indexing="ij"))
    Q = np.stack([i * (n + 1) + j, (i + 1) * (n + 1) + j, (i + 1) * (n + 1) + j + 1, i * (n + 1) + j + 1], 1)
    return X, Q.astype(np.int64)


def _brute(xq, surf, gap):
    """전수(knn 제한 없음): 중심 거리 ≤ gap + R_max 인 모든 삼각형(엄밀 필터, x 정렬 창) → 정확 거리 → 동률 작은 번호."""
    P, T = surf["x"], surf["tri"]
    C = P[T].mean(axis=1)
    ub = gap + np.sqrt(((P[T] - C[:, None]) ** 2).sum(-1)).max()
    o = np.argsort(C[:, 0], kind="stable")
    cx = C[o, 0]
    d_out, t_out = np.full(xq.shape[0], np.inf), np.full(xq.shape[0], -1)
    for i, p in enumerate(xq):
        c = o[np.searchsorted(cx, p[0] - ub, "left"):np.searchsorted(cx, p[0] + ub, "right")]
        c = np.sort(c[np.linalg.norm(C[c] - p, axis=1) <= ub])
        if not c.size:
            continue
        d = np.linalg.norm(jig._closest_tri(p[None], P[T[c, 0]], P[T[c, 1]], P[T[c, 2]]) - p, axis=1)
        k = c[d <= d.min() + jig.TIE_REL * gap].min()
        d_out[i], t_out[i] = d[c == k][0], k
    return d_out, t_out


@pytest.mark.slow
def test_v_jig_8_large_distance_memory():
    L, gap = 1000.0, 2.0
    Xs, Qs = _grid(1000, L * 1.0003, 0.8, off=-0.137)              # 삼각형 200만(평행 격자, 어긋난 간격)
    surf = {"x": Xs, "tri": np.concatenate([Qs[:, [0, 1, 2]], Qs[:, [0, 2, 3]]]),
            "tri_part": np.full(2 * Qs.shape[0], 5, dtype=np.int64)}
    peaks = {}
    for n in (500, 707):                                          # 후보 노드 25만 → 50만
        Xt, Qt = _grid(n, L, 0.0)
        mesh = {"node_id": np.arange(Xt.shape[0]) + 1, "x0": Xt, "conn": Qt, "elem_type": np.full(Qt.shape[0], 4),
                "thickness": np.ones(Qt.shape[0])}
        w = jig.node_weights(mesh)
        cand = np.ones(Xt.shape[0], bool)
        tracemalloc.start()
        t0 = time.monotonic()
        r = jig.contact_regions(mesh, cand, surf, gap_mm=gap, knn=JIG["knn"], chunk_nodes=JIG["chunk_nodes"],
                                max_regions=8, min_regions=2, min_nodes=3, min_area_mm2=25.0, weights=w)
        dt = time.monotonic() - t0
        peaks[n] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        assert dt <= 60.0 and r["n_contact_nodes"] == Xt.shape[0] and len(r["regions"]) == 1
        if n == 500:
            smp = np.sort(np.random.default_rng(1).choice(Xt.shape[0], 2000, replace=False))
            near = jig.nearest_tri(Xt[smp], surf, gap_mm=gap, knn=JIG["knn"], chunk_nodes=JIG["chunk_nodes"])
            bd, bt = _brute(Xt[smp], surf, gap)
            assert np.array_equal(near["tri"], bt) and np.array_equal(near["dist"], bd)
    assert peaks[500] <= 400 * 2 ** 20
    assert peaks[707] <= 1.10 * peaks[500]


def test_v_jig_8_chunk_invariance(base):
    """청크 크기·knn 무관 비트 동일(작은 사례) + 후보 없음 = inf/−1."""
    c = base
    X = c["mesh"]["x0"]
    ref = jig.nearest_tri(X, c["surf"], gap_mm=2.0, knn=8, chunk_nodes=65536)
    for ch in (1, 7, 100):
        r = jig.nearest_tri(X, c["surf"], gap_mm=2.0, knn=8, chunk_nodes=ch)
        for k in ("dist", "tri", "q"):
            assert np.array_equal(r[k], ref[k])
    hit = ref["dist"] <= 2.0
    assert hit.sum() == _contact(c)["n_contact_nodes"] + np.isin(np.flatnonzero(hit), c["J"]).sum()
    bd, bt = _brute(X, c["surf"], 2.0)
    fin = np.isfinite(bd) & (bd <= 2.0)
    assert np.array_equal(ref["tri"][fin], bt[fin]) and np.allclose(ref["dist"][fin], bd[fin], rtol=0, atol=1e-12)
    e = jig.nearest_tri(X, sj.surface([]), gap_mm=2.0, knn=8, chunk_nodes=10)
    assert np.all(np.isinf(e["dist"])) and np.all(e["tri"] == -1)


# ---------------------------------------------------------------- V-JIG-15
def test_v_jig_15_pure_module():
    tree = ast.parse(open(JIG_PY, encoding="utf-8").read())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            assert n.func.id not in ("open", "exec", "eval", "__import__")
    allowed = ("numpy", "scipy", "esl.errors", "esl.mech.shell", "esl.mech.kabsch", "esl.mech", "__future__", "time")
    for m in mods:
        assert any(m == a or m.startswith(a + ".") for a in allowed), m
    assert not any(m.startswith("esl.doe") for m in mods)
    assert not ({"os", "io", "json", "pathlib", "pickle", "shutil"} & mods)


def test_v_jig_15_deterministic(exact):
    c = exact["c"]
    r1 = _pipeline(c, exact["u_ref"], _sel(c))
    r2 = _pipeline(dict(c, w=jig.node_weights(c["mesh"])), exact["u_ref"].copy(), _sel(c))
    assert np.array_equal(r1["fit"]["a"], r2["fit"]["a"]) and np.array_equal(r1["F"], r2["F"])
    assert r1["row"]["C_jig"] == r2["row"]["C_jig"] and r1["rep"] == r2["rep"]


def test_v_jig_15_stages_no_scenario_branch():
    from esl.doe.transfer_plan import PLANS
    if not os.path.exists(STAGES_PY):
        pytest.skip("stages.py 없음")
    names = list(PLANS) + ["scenario"]
    for ln in open(STAGES_PY, encoding="utf-8").read().splitlines():
        if re.search(r"jig", ln, re.I):
            assert not any(n in ln for n in names), ln
