"""v0.24.4 P2b — 지그 맞춤의 3-2-1 면내 반력 0 등식 제약 · spring α 기본 0.01 (메인 결정 2026-11-20, D-0.24.4-JIG-19·20,
계약 docs/contracts/esl_jig_case.md 부록 A2b).

P2a 관찰: normal tie 면의 면내 하중은 3-2-1 면내 3자유도만 받아 prescribed 반력비 1.19(기준 0.05). 맞춤에 r_aux(a) = 0 등식
(하한 없는 열 소거 — BVLS 경계 유지)을 넣어 반력비 ≈ 0. translation(3-2-1 면내 행 없음)·옛 스터디는 제약 없음 = 산술 불변.

기록값(led 픽스처, 맞춤 노드 MAC / 파트 Kabsch 재현 MAC): normal fixed 0.65582 → 0.65578 / 0.63424 그대로, prescribed 0.99973 →
0.99969 / 0.99981 그대로, spring(α=1) 같음. 반력비 fixed 0.051·prescribed 1.191·spring 1.191 → 세 방식 < 1e-10.
α = 0.01(기본): 같은 F 에서 ‖u_s − u_p‖/‖u_p‖ ≈ 2.3e-3(α = 1 은 2.4e-5 — 강제 변위와 구별 안 됨).
"""
from __future__ import annotations

import numpy as np
import pytest
import test_jig_bc as T

from esl.mech import jig, jig_bc


def _runs(c, tie_dofs, *, eq: bool, alpha=1.0):
    """세 방식(공유 기저·fixed 분해 공유, spring 자체 분해) — eq 이면 같은 분해의 기저 3-2-1 면내 반력으로 제약."""
    tie, aux = T.shared(c, tie_dofs)
    tg = {m: jig_bc.target(jig_bc.METHODS[m]["frame"], c["X"], c["u_rel"], c["J"], c["fit"]) for m in T.METHODS}
    k = jig_bc.spring_k(c["sm"], tie, mode="auto", alpha=alpha)
    BC = {m: jig_bc.build_bc(jig_bc.METHODS[m], tie, aux, tg[m]["u_tgt"],
                             k=k if jig_bc.METHODS[m]["tie_stiff"] != "hard" else None) for m in T.METHODS}
    bc0 = jig_bc.build_bc(jig_bc.METHODS[jig_bc.basis_method()], tie, aux, np.zeros((c["N"], 3)))
    h0 = jig_bc.factorize(c["sm"], bc0)
    basis = jig.load_basis(c["mesh"], c["regions"], c["wts"], c["omega"], body_force=True, tangential=True,
                           modes=jig_bc.modes(h0, c["wts"], 4, 7.85e-9)["g"])
    br0 = jig_bc.basis_response(h0, basis, c["fit"], bc0)
    out = {}
    for m in T.METHODS:
        if jig_bc.pattern_sha(BC[m]) == jig_bc.pattern_sha(bc0):
            h, br = h0, br0
        else:
            h = jig_bc.factorize(c["sm"], BC[m])
            br = jig_bc.basis_response(h, basis, c["fit"], BC[m])
        r = jig_bc.run_method(h, basis, br["U"], tg[m]["u_tgt"], BC[m], c["fit"], c["wts"], jig_idx=c["J"], **T.P_FIT,
                              rc_basis=br["rc_aux"] if eq else None)
        out[m] = {"r": r, "BC": BC[m], "h": h, "br": br, "basis": basis, "tgt": tg[m]}
    return out


@pytest.fixture(scope="module")
def led():
    return T.led_case()


@pytest.fixture(scope="module")
def runs(led):
    return {(td, eq): _runs(led, td, eq=eq) for td in jig_bc.TIE_DOFS for eq in (False, True)}


def test_aux_reaction_zero_with_constraint_normal(led, runs):
    from esl.mech import kabsch
    from esl.mech.bforce import mac
    before, after = runs[("normal", False)], runs[("normal", True)]
    assert before["prescribed"]["r"]["aux_reaction_rel"] > 0.5                    # P2a 관찰(1.19) 재현
    for m in T.METHODS:
        ra, rb = after[m]["r"], before[m]["r"]
        assert ra["aux_reaction_rel"] < 1e-8, m                                    # 기준 0.05 보다 훨씬 작음
        eq = ra["aux_eq"]
        assert eq["applied"] is True and eq["n"] == 3 and eq["resid"] < 1e-10
        # 실제 해의 3-2-1 면내 반력(BC 값·바닥 포함 전체 해) ≈ 0
        ia = jig_bc.aux_index(after[m]["BC"])
        assert np.abs(np.asarray(ra["rc"])[ia]).max() <= 1e-9 * np.abs(ra["F"]).sum()
        # 재현 저하 없음(맞춤 노드 MAC 차 < 1e-3, 파트 Kabsch 재현 MAC 차 < 1e-4)
        assert ra["report"]["mac"] > rb["report"]["mac"] - 1e-3, m
        ua = kabsch.remove_rigid(led["X"], ra["u"][:, :3])[0]
        ub = kabsch.remove_rigid(led["X"], rb["u"][:, :3])[0]
        assert mac(led["u_rel"], ua) > mac(led["u_rel"], ub) - 1e-4, m
    assert after["prescribed"]["r"]["report"]["mac"] >= 0.95


def test_translation_no_constraint_bit_identical(runs):
    """3-2-1 면내 행 없음(translation) = 제약 없음 — rc_basis 를 줘도 a·F 비트 동일(옛 경로)."""
    a, b = runs[("translation", False)], runs[("translation", True)]
    for m in T.METHODS:
        assert b[m]["r"]["aux_eq"] is None and b[m]["br"]["rc_aux"].shape[1] == 0
        assert np.array_equal(a[m]["r"]["a"], b[m]["r"]["a"]) and np.array_equal(a[m]["r"]["F"], b[m]["r"]["F"])


def test_basis_response_equals_jig_basis_response(runs, led):
    """jig_bc.basis_response U = jig.basis_response U(같은 해 — 비트 동일) + 열마다 3-2-1 면내 반력."""
    for td in jig_bc.TIE_DOFS:
        x = runs[(td, True)]["fixed"]
        ref = jig.basis_response(x["h"], x["basis"], led["fit"])
        assert np.array_equal(ref["U"], x["br"]["U"]) and ref["null_cols"] == x["br"]["null_cols"]
        assert x["br"]["rc_aux"].shape == (x["basis"]["nb"], jig_bc.aux_index(x["BC"]).size)


def test_fit_loads_eq_none_unchanged_and_infeasible(runs, led):
    x = runs[("normal", True)]["prescribed"]
    U = x["br"]["U"]
    fm = led["fit"]
    area = led["wts"]["area"]
    args = (U, x["tgt"]["u_tgt"][fm] - x["r"]["u_g"][fm], area[fm] / area[fm].mean(), led["wts"]["normal"][fm],
            x["basis"])
    kw = {k: T.P_FIT[k] for k in ("ridge", "w_inplane", "reg_force", "reg_modes")}
    a0 = jig.fit_loads(*args, **kw)
    a1 = jig.fit_loads(*args, **kw, eq=None)
    assert np.array_equal(a0["a"], a1["a"]) and "eq" not in a0 and "eq" not in a1
    # 등식이 하한 있는 열(접촉 법선 ≥ 0)에만 걸리면 소거 불가(하한 없는 열의 계수 0 — rank) → 제약 없이(applied False·사유) — 결과는 무제약과 같음
    ck = np.asarray(x["basis"]["col_kind"])
    C = np.zeros((1, ck.size))
    lo_cols = [3 * r for r in range(int(x["basis"]["reg_ptr"].size - 1)) if int(x["basis"]["reg_sign"][r]) > 0]
    assert lo_cols
    C[0, lo_cols[0]] = 1.0
    f = jig.fit_loads(*args, **kw, eq=(C, np.zeros(1)))
    assert f["eq"]["applied"] is False and f["eq"]["reason"] == "rank" and np.array_equal(f["a"], a0["a"])


def test_spring_alpha_default_one_place(led):
    """α 기본 = JIG_DEFAULTS["spring_alpha"](0.01 — 한 곳), α = 0.01 에서 spring 이 prescribed 와 구별됨(같은 F)."""
    assert jig.JIG_DEFAULTS["spring_alpha"] == 0.01
    tie, _aux = T.shared(led, "normal")
    assert np.array_equal(jig_bc.spring_k(led["sm"], tie, mode="auto"), jig_bc.spring_k(led["sm"], tie, mode="auto",
                                                                                         alpha=0.01))
    x = _runs(led, "normal", eq=True, alpha=0.01)
    F = x["prescribed"]["r"]["F"]
    up = jig_bc.solve(x["prescribed"]["h"], F, x["prescribed"]["BC"])[0][:, :3]
    us = jig_bc.solve(x["spring"]["h"], F, x["spring"]["BC"])[0][:, :3]
    d = float(np.linalg.norm(us - up) / np.linalg.norm(up))
    assert 1e-3 < d < 1e-2, d
