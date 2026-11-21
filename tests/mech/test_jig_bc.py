"""v0.24.4 지그 경계 3방식·tie 구속 성분·3-2-1 면내·스프링·순위 지표 Π (계약 esl_jig_case.md §2.2·§2.3·§3·§4.2,
V-0244-JIG-2·3·5·6·7·10·15 일부 — 코어 순수 모듈 esl/mech/jig_bc.py).

합성 픽스처(이 파일 안):
- ``led``: 패널(300×200, 10 mm, t 1) + 같은 평면 LED 판(x 20..280·y 20..180, t 1.5 — 스크류 tie 12점에서만 노드 병합) 조립 모델에
  관성(−z, 질량 비례) + 양 끝 접촉(+z) + 패널 국부 덴트를 주고 → 패널만 추출·파트 Kabsch = 목표(u_rel). tie 노드가 함께 휨
  (지그 Kabsch 틀 tie_rel ≈ 0.61). 하중 기저 = 접촉 영역 2(양 끝) + 패치 6 + 체적력 + 모드 4.
- ``cyl``: 원통 패널(R 400·폭각 0.8·높이 200), tie 12점, 목표 = normal 경계(tie 법선 0 + 3-2-1 면내)의 기저 하중 조합 응답
  (기저 span 안 — 곡면이라 굽힘에 tie 접선 운동이 따름 = 막 운동이 있는 목표).

기록값(이 환경 — 맞춤 노드 MAC, 괄호 = 파트 Kabsch 재현 MAC vs u_rel):
- led normal: fixed 0.656(0.634) · prescribed 0.9997(0.9998) · spring(α=1) 0.9997(0.9998) / translation: 0.656 · 0.9998 · 0.9998.
  tie_rel 0.61(fixed 만 JIG_TIE_RELATIVE). 평판 조립이라 normal ≈ translation(선형 평판은 굽힘·막이 분리 — 차이는 곡면에서 남).
  normal 의 3-2-1 면내 반력비 fixed 0.05 · prescribed 1.19(맞춤 하중의 면내 불평형이 면내 지지로 감 — 정보 JIG_AUX_REACTION).
- cyl(곡면, 기저 span 안 목표): fixed normal 0.995 > translation 0.858, prescribed normal ≈ 1.0 > translation 0.949.
- α 민감도(led normal, 같은 F·바닥, ‖u_s − u_p‖/‖u_p‖): 0.01 → 2.3e-3, 0.1 → 2.4e-4, 1 → 2.4e-5, 10 → 2.4e-6, 100 → 2.4e-7,
  1e4 → 2.4e-9(k_auto 중앙값 ≈ 1.8e5 N/mm — 노드 자기 강성 d̂ᵀK₀[n]d̂ 는 패널 전체 강성보다 훨씬 커서 α = 1 이 이미 강제 변위와
  같음. 스프링 행이 "중간"이 되려면 α ≲ 1e-2 — Q-JIGC-1 참고).
- 영역 두께 ×0.8·1·1.25: s fixed 1.241·1·0.842, prescribed 1.177·1·0.706(normal). 비드 깊이 ×0.5·1·1.5(D 3 mm, 기준 ×1):
  s fixed 1.328·1·0.859, prescribed 1.504·1·0.342 — prescribed 의 umax 는 반대로 증가(5.50 → 5.68 → 5.90).
"""
from __future__ import annotations

import inspect
import os
import re

import numpy as np
import pytest
from meshes import cylinder_panel, rect_quads

from esl.errors import EslError
from esl.mech import jig, jig_bc, kabsch, supports
from esl.mech.shell import ShellModel

E, NU = 2.1e5, 0.3
P_FIT = {"ridge": 1e-8, "w_inplane": 0.1, "reg_force": 1e-3, "reg_modes": 0.0, "active_tol": 1e-3}
TH = {k: jig.JIG_DEFAULTS[k] for k in ("mac_min", "umax_err_max", "tie_rel_warn", "work_eff_min", "aux_reaction_warn")}
METHODS = tuple(jig_bc.METHODS)


# ====================================================================== 합성 도구
def mesh_of(P, C, et, t=1.0):
    C = np.asarray(C, dtype=np.int64)
    return {"x0": np.asarray(P, dtype=np.float64), "conn": C, "elem_type": np.asarray(et).astype(np.int64),
            "thickness": np.broadcast_to(np.asarray(t, dtype=np.float64), (len(C),)).copy(),
            "E": np.full(len(C), E), "nu": np.full(len(C), NU), "node_id": np.arange(1, len(P) + 1)}


def model(mesh, x=None):
    return ShellModel(mesh["x0"] if x is None else x, mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"],
                      mesh["nu"], backend="superlu")


def near(X, pts):
    return np.array(sorted({int(np.argmin(np.hypot(X[:, 0] - x, X[:, 1] - y))) for x, y in pts}), dtype=np.int64)


def assembly(mp, ties, t_led=1.5, box=(20.0, 280.0, 20.0, 180.0)):
    """패널 + 같은 평면 LED 판(별도 노드, tie 노드에서만 병합) → (조립 메시, 패널 노드 → 조립 노드)."""
    X = mp["x0"]
    Np = X.shape[0]
    inb = (X[:, 0] >= box[0] - 1e-9) & (X[:, 0] <= box[1] + 1e-9) & (X[:, 1] >= box[2] - 1e-9) & (X[:, 1] <= box[3] + 1e-9)
    led = np.flatnonzero(inb)
    newid = np.full(Np, -1)
    newid[led] = Np + np.arange(led.size)
    newid[ties] = ties
    C = mp["conn"]
    ec = inb[C].all(axis=1)
    Cl = newid[C[ec]]
    Xa = np.concatenate([X, X[led]])
    conn = np.concatenate([C, Cl])
    et = np.concatenate([mp["elem_type"], mp["elem_type"][ec]])
    th = np.concatenate([mp["thickness"], np.full(Cl.shape[0], t_led)])
    used = np.zeros(Xa.shape[0], bool)
    used[conn.ravel()] = True
    keep = np.flatnonzero(used)
    remap = np.full(Xa.shape[0], -1)
    remap[keep] = np.arange(keep.size)
    return mesh_of(Xa[keep], remap[conn], et, th), remap[:Np]


def bead(Xf, depth, cs=(70.0, 130.0), w=8.0):
    """x 방향 리브 비드 2줄(y = 70·130, 양 끝 20 mm 완화) — 깊이 증가 = 굽힘 강성 증가."""
    Y = Xf.copy()
    ramp = np.clip((Xf[:, 0] - 30.0) / 20.0, 0, 1) * np.clip((270.0 - Xf[:, 0]) / 20.0, 0, 1)
    Y[:, 2] += depth * sum(np.exp(-((Xf[:, 1] - c) / w) ** 2) for c in cs) * ramp
    return Y


def led_case(depth=0.0, dent=20.0, inplane=0.0):
    P, C, et = rect_quads(300.0, 200.0, 30, 20)
    mp = mesh_of(P, C, et)
    Xf = mp["x0"].copy()
    mp["x0"] = bead(Xf, depth)
    X = mp["x0"]
    N = X.shape[0]
    J = near(Xf, [(x, y) for x in (20.0, 100.0, 200.0, 280.0) for y in (30.0, 100.0, 170.0)])
    ma, pmap = assembly(mp, J)
    sa = model(ma)
    w = jig.node_weights(ma)
    m = w["area"] * w["thick"]
    Fa = np.zeros((ma["x0"].shape[0], 3))
    Fa[:, 2] = -m / m.sum() * 1000.0
    Fa[:, 0] = -m / m.sum() * inplane
    L_ = np.flatnonzero(Xf[:, 0] < 15.0)
    R_ = np.flatnonzero(Xf[:, 0] > 285.0)
    for cs in (L_, R_):
        Fa[cs, 2] += 500.0 / cs.size
        Fa[cs, 0] += 0.5 * inplane / cs.size
    dn = np.flatnonzero(np.hypot(Xf[:, 0] - 150.0, Xf[:, 1] - 70.0) < 18.0)
    Fa[dn, 2] += -dent / dn.size
    Fa[L_, 2] += 0.5 * dent / L_.size
    Fa[R_, 2] += 0.5 * dent / R_.size
    ua, _ = sa.solve(Fa, supports.pick_321(ma["x0"], supports.pca_corners(ma["x0"])["idx"]))
    u_rel = kabsch.remove_rigid(X, ua[pmap, :3])[0]
    wts = jig.node_weights(mp)
    fit = np.ones(N, bool)
    fit[J] = False
    regs = [jig._region(jig.REGION_CONTACT, 9, cs, X, wts["area"], np.array([0.0, 0.0, -1.0])) for cs in (L_, R_)]
    for r in regs:
        r["gap_mm"] = 2.0
    pr = jig.patch_regions(mp, fit, exclude_mask=np.isin(np.arange(N), np.r_[L_, R_, J]), n_fill=6, patch_count=6,
                           min_nodes=3, weights=wts)
    return {"mesh": mp, "Xf": Xf, "X": X, "N": N, "J": J, "u_rel": u_rel, "sm": model(mp), "wts": wts, "fit": fit,
            "omega": np.ones(N, bool), "regions": regs + pr["regions"],
            "sup321": supports.pick_321(X, supports.pca_corners(X)["idx"])}


def shared(c, tie_dofs):
    tie = jig_bc.tie_rows(c["mesh"], c["J"], tie_dofs, kink_deg=45.0)
    aux = jig_bc.aux_rows(c["X"], c["sup321"], tie, tie_dofs, dup_deg=10.0)
    return tie, aux


def run_methods(c, tie_dofs, *, alpha=1.0, n_modes=4, regions=None, methods=METHODS):
    """세 방식(공유: tie·3-2-1 면내·fixed 분해·모드·기저, spring = 자체 분해) → {방식: {r, BC, h, U, tgt}}."""
    tie, aux = shared(c, tie_dofs)
    tg = {m: jig_bc.target(jig_bc.METHODS[m]["frame"], c["X"], c["u_rel"], c["J"], c["fit"]) for m in methods}
    k = jig_bc.spring_k(c["sm"], tie, mode="auto", alpha=alpha)
    BC = {m: jig_bc.build_bc(jig_bc.METHODS[m], tie, aux, tg[m]["u_tgt"],
                             k=k if jig_bc.METHODS[m]["tie_stiff"] == "spring" else None) for m in methods}
    owners = jig_bc.factor_groups(methods)
    hs, basis = {}, None
    for owner in owners:                                      # 분해 주인(열 factor)마다 1회 — fixed 구속 집합 = fixed 값 0 BC
        bc0 = BC.get(owner) or jig_bc.build_bc(jig_bc.METHODS[owner], tie, aux, np.zeros((c["N"], 3)))
        hs[owner] = jig_bc.factorize(c["sm"], bc0)
    base_owner = next(iter(owners))
    if basis is None:
        md = jig_bc.modes(hs[base_owner], c["wts"], n_modes, 7.85e-9) if n_modes else None
        basis = jig.load_basis(c["mesh"], regions if regions is not None else c["regions"], c["wts"], c["omega"],
                               body_force=True, tangential=True, modes=None if md is None else md["g"])
    Us = {o: jig.basis_response(hs[o], basis, c["fit"])["U"] for o in owners}
    out = {}
    for owner, ms in owners.items():
        for m in ms:
            r = jig_bc.run_method(hs[owner], basis, Us[owner], tg[m]["u_tgt"], BC[m], c["fit"], c["wts"], jig_idx=c["J"],
                                  **P_FIT)
            out[m] = {"r": r, "BC": BC[m], "h": hs[owner], "U": Us[owner], "tgt": tg[m], "basis": basis}
    return out, tie, aux


@pytest.fixture(scope="module")
def led():
    return led_case()


@pytest.fixture(scope="module")
def led_runs(led):
    return {td: run_methods(led, td)[0] for td in jig_bc.TIE_DOFS}


# ====================================================================== V-10 계획 표 · V-15 옛 스냅샷
def test_plan_tables_all_columns_and_values():
    jig_bc.check_plan()
    assert tuple(jig_bc.METHODS) == ("fixed", "prescribed", "spring")
    assert [r["src"] for r in jig_bc.METHODS.values()] == ["jig", "jig_disp", "jig_spring"]
    for row in jig_bc.METHODS.values():
        assert set(row) == set(jig_bc.METHOD_COLS)
    for row in jig_bc.TIE_DOFS.values():
        assert set(row) == set(jig_bc.TIE_COLS)
    assert jig_bc.factor_groups(["fixed", "prescribed", "spring"]) == {"fixed": ["fixed", "prescribed"], "spring": ["spring"]}
    assert jig_bc.factor_groups(["prescribed"]) == {"fixed": ["prescribed"]}   # fixed 산출 없이도 fixed 구속 분해
    assert jig_bc.METHODS["prescribed"]["limits"] == ("JIG_DISP_FROM_TARGET",)
    assert [m for m, r in jig_bc.METHODS.items() if r["tie_rel_warn"]] == ["fixed"]


def test_no_method_or_source_name_branch_in_module():
    """방식·출처·구속 성분 이름 문자열 비교 없음(열 값만 — AGENTS.md). 표 선언·문구는 제외."""
    src = inspect.getsource(jig_bc)
    names = "|".join(list(jig_bc.METHODS) + list(jig_bc.TIE_DOFS) + [r["src"] for r in jig_bc.METHODS.values()])
    pat = re.compile(rf"""(==|!=|\bin\b)\s*\(?\s*["']({names})["']""")
    assert not pat.findall(src)


def test_legacy_absent_and_cfg_check():
    assert jig_bc.LEGACY_ABSENT == {"tie_dofs": "translation", "methods": ("fixed",)}
    assert jig_bc.tie_dofs_of({}) == "translation" and jig_bc.methods_of({}) == ("fixed",)
    assert jig.JIG_DEFAULTS["tie_dofs"] == "normal" and jig.JIG_DEFAULTS["methods"] == ["fixed", "prescribed", "spring"]
    assert jig_bc.tie_dofs_of(jig.JIG_DEFAULTS) == "normal" and jig_bc.methods_of(jig.JIG_DEFAULTS) == METHODS
    jig_bc.check_cfg(jig.JIG_DEFAULTS)
    for bad in ({"tie_dofs": "xyz"}, {"methods": []}, {"methods": ["fixed", "fixed"]}, {"methods": ["rigid"]},
                {"spring_alpha": 5e-4}, {"spring_k_mode": "value"}, {"spring_k_mode": "value", "spring_k_value": 0},
                {"spring_k_mode": "abs"}, {"normal_kink_deg": 0}, {"aux321_dup_deg": 90}, {"spring_alpha_scan": [1e-4]},
                {"aux_reaction_warn": -1}):
        with pytest.raises(EslError) as ei:
            jig_bc.check_cfg({**jig.JIG_DEFAULTS, **bad})
        assert ei.value.code == "CONFIG_INVALID", bad
    jig_bc.check_cfg({"spring_k_mode": "value", "spring_k_value": 5.0e3, "methods": ["prescribed"]})


# ====================================================================== V-2 법선
def _strip(theta_deg, n=4, h=10.0, extra=None):
    """두 면(x<0 평면 · x>0 쪽이 꺾임선 y 축 기준 θ 꺾임) 쿼드 띠. 꺾임선 노드 = x = 0."""
    th = np.radians(theta_deg)
    P = []
    for i in range(-n, n + 1):
        for j in range(n + 1):
            s = i * h
            x, z = (s, 0.0) if s <= 0 else (s * np.cos(th), s * np.sin(th))
            P.append((x, j * h, z))
    P = np.array(P)
    def idx(i, j):
        return (i + n) * (n + 1) + j
    C = [[idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)] for i in range(-n, n) for j in range(n)]
    kink = np.array([idx(0, j) for j in range(n + 1)])
    return mesh_of(P, C, np.full(len(C), 4)), kink


def test_v2_flat_plate_rank1_sign_rule_deterministic():
    P, C, et = rect_quads(100.0, 60.0, 5, 3)
    m = mesh_of(P, C[:, ::-1], et)                                           # 요소 법선 −z(감김 반대) → 부호 규칙으로 +z
    fr = jig_bc.node_frames(m, np.arange(P.shape[0]), kink_deg=45.0)
    assert fr["rank_counts"] == {1: P.shape[0], 2: 0, 3: 0} and fr["n_isolated"] == 0 and fr["n_null_excluded"] == 0
    assert np.allclose(fr["dir"], [0.0, 0.0, 1.0], atol=1e-14)
    fr2 = jig_bc.node_frames(m, np.arange(P.shape[0])[::-1], kink_deg=45.0)
    assert np.array_equal(fr["node"], fr2["node"]) and np.array_equal(fr["dir"], fr2["dir"])   # 결정적(정렬)


def test_v2_kink_rank_by_angle_and_null_shell():
    m90, k90 = _strip(90.0)
    fr = jig_bc.node_frames(m90, k90, kink_deg=45.0)
    assert set(fr["rank"].tolist()) == {2}                                     # 90° 꺾임 = 두 면 법선
    for n in k90:
        D = fr["dir"][fr["node"] == n]
        span = D.T @ D                                                         # 구속 부분공간 = span{e_z, e_x}(두 면 법선)
        assert np.allclose(span @ np.array([0, 0, 1.0]), [0, 0, 1.0], atol=1e-12)
        assert np.allclose(span @ np.array([1.0, 0, 0]), [1.0, 0, 0], atol=1e-12)
    assert jig_bc.node_frames(m90, k90, kink_deg=120.0)["rank_counts"][1] == k90.size   # τ = tan²60° > 1 → 1방향
    m30, k30 = _strip(30.0)
    assert jig_bc.node_frames(m30, k30, kink_deg=45.0)["rank_counts"][1] == k30.size     # 30° < 45° → 1방향
    t = m90["thickness"].copy()
    t[np.asarray(m90["x0"])[m90["conn"]].mean(axis=1)[:, 2] > 1e-9] = 0.0     # 꺾인 쪽(z > 0) = null shell(두께 0)
    fr0 = jig_bc.node_frames(dict(m90, thickness=t), k90, kink_deg=45.0)
    assert fr0["rank_counts"][1] == k90.size and fr0["n_null_excluded"] == k90.size
    assert np.allclose(np.abs(fr0["dir"]), [0.0, 0.0, 1.0], atol=1e-12)        # 유효 면 법선만


def test_v2_corner_rank3_and_isolated():
    P = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [0, 0, 10], [10, 0, 10], [0, 10, 10],
                  [50, 50, 50]], dtype=float)
    C = [[0, 3, 2, 1], [0, 1, 5, 4], [0, 4, 6, 3]]                            # 상자 모서리(세 면) + 고립 노드 7
    m = mesh_of(P, C, [4, 4, 4])
    fr = jig_bc.node_frames(m, [0, 7], kink_deg=45.0)
    assert fr["rank"].tolist() == [3, 3] and fr["n_isolated"] == 1
    assert np.allclose(fr["dir"][fr["node"] == 7], np.eye(3))


# ====================================================================== V-3 3-2-1 면내 · 남은 강체 모드
def test_v3_aux321_axis_and_tilted_plate():
    P, C, et = rect_quads(300.0, 200.0, 12, 8)
    for tilt in (0.0, 30.0):
        Rx = kabsch.fit(np.eye(3), np.eye(3))[0] if tilt == 0 else np.array(
            [[1, 0, 0], [0, np.cos(np.radians(tilt)), -np.sin(np.radians(tilt))],
             [0, np.sin(np.radians(tilt)), np.cos(np.radians(tilt))]])
        X = P @ Rx.T
        m = mesh_of(X, C, et)
        s321 = supports.pick_321(X, supports.pca_corners(X)["idx"])
        tie = jig_bc.tie_rows(m, [0, 8, 100, 116], "normal", kink_deg=45.0)
        a = jig_bc.aux321_inplane(X, s321, tie, dup_deg=10.0)
        n1, n2, n3 = a["nodes"]
        e3 = np.asarray(a["plane"]["n"])
        assert a["node"].tolist() == [n1, n1, n2] and n3 not in a["node"] and a["n_dup"] == 0
        assert np.allclose(a["dir"] @ e3, 0.0, atol=1e-12)                    # 모두 판 평면 안
        assert abs(a["dir"][2] @ (X[n2] - X[n1])) <= 1e-9 * np.linalg.norm(X[n2] - X[n1])   # ê ⟂ n₁–n₂
        assert np.allclose(np.abs(e3), np.abs(Rx @ [0, 0, 1.0]), atol=1e-12)


def test_v3_aux321_dedup_against_tie_subspace():
    P = rect_quads(300.0, 200.0, 12, 8)[0]
    s321 = supports.pick_321(P, supports.pca_corners(P)["idx"])
    n1 = next(p for p, d in s321 if len(d) == 3)
    a = jig_bc.aux321_inplane(P, s321, {"node": np.array([n1]), "dir": np.array([[0, 0, 1.0]])}, dup_deg=10.0)
    assert a["n_dup"] == 0 and a["node"].size == 3                             # tie 법선 = 면외 → 면내 행 그대로
    kinked = {"node": np.array([n1, n1]), "dir": np.array([[0, 0, 1.0], [1.0, 0, 0]])}   # 꺾임 tie(법선 2) — e_x 겹침
    b = jig_bc.aux321_inplane(P, s321, kinked, dup_deg=10.0)
    assert b["n_dup"] == 1 and b["node"].size == 2
    assert np.allclose(b["dir"][0], [0, 1.0, 0], atol=1e-12) or np.allclose(b["dir"][0], [0, -1.0, 0], atol=1e-12)
    trans = {"node": np.full(3, n1), "dir": np.eye(3)}
    assert jig_bc.aux321_inplane(P, s321, trans, dup_deg=10.0)["n_dup"] == 2   # 병진 tie 노드 = n₁ 면내 2행 모두 중복


def test_v3_rigid_free_and_degenerate():
    P, C, et = rect_quads(300.0, 200.0, 12, 8)
    m = mesh_of(P, C, et)
    s321 = supports.pick_321(P, supports.pca_corners(P)["idx"])
    J = np.array([14, 22, 100, 110], dtype=np.int64)
    tie = jig_bc.tie_rows(m, J, "normal", kink_deg=45.0)
    aux = jig_bc.aux_rows(P, s321, tie, "normal", dup_deg=10.0)
    comp = jig_bc.components(m)
    bc = jig_bc.build_bc(jig_bc.METHODS["fixed"], tie, aux, np.zeros_like(P))
    assert jig_bc.rigid_free(P, comp, bc)["rigid_free"] == 0                   # 법선 + 3-2-1 면내 = 6모드
    no_aux = jig_bc.build_bc(jig_bc.METHODS["fixed"], tie, jig_bc.aux_rows(P, s321, tie, "translation", dup_deg=10.0),
                             np.zeros_like(P))
    assert jig_bc.rigid_free(P, comp, no_aux)["rigid_free"] == 3               # 법선만 = 면내 강체 3모드(사용자 결정 5 근거)
    # 두 번째 성분(지그 없음) → rigid_free 6 + 분해 = JIG_SUPPORT_DEGENERATE
    P2 = np.concatenate([P, P + [0, 0, 50.0]])
    m2 = mesh_of(P2, np.concatenate([C, C + P.shape[0]]), np.r_[et, et])
    rf = jig_bc.rigid_free(P2, jig_bc.components(m2), bc)
    assert rf["rigid_free"] == 6 and [c["free"] for c in rf["per_comp"]] == [0, 6]
    with pytest.raises(EslError) as ei:
        jig_bc.factorize(model(m2), bc)
    assert ei.value.code == "JIG_SUPPORT_DEGENERATE"


# ====================================================================== V-5 재현(합성 3방식)
def test_v5_led_three_methods(led_runs):
    for td, runs in led_runs.items():
        mac = {m: runs[m]["r"]["report"]["mac"] for m in METHODS}
        assert mac["prescribed"] >= 0.95, (td, mac)
        assert mac["prescribed"] >= mac["spring"] - 1e-6 and mac["spring"] >= mac["fixed"], (td, mac)
        assert mac["fixed"] < 0.8                                                # 고정 = 함께 휘는 tie 를 0 으로 — 재현 불가(R-JIG-1)
        rep = {m: runs[m]["r"]["report"] for m in METHODS}
        assert rep["fixed"]["tie_rel"] >= 0.5
        fl = {m: jig_bc.flags(m, rep[m], aux_rel=runs[m]["r"]["aux_reaction_rel"], th=TH) for m in METHODS}
        assert "JIG_TIE_RELATIVE" in fl["fixed"]["warnings"]
        assert all("JIG_TIE_RELATIVE" not in fl[m]["warnings"] for m in ("prescribed", "spring"))
        assert fl["prescribed"]["limits"] == ["JIG_DISP_FROM_TARGET"] and fl["fixed"]["limits"] == []
        for m in METHODS:
            sm_ = runs[m]["h"].model
            comp = jig_bc.components({"x0": sm_.x0, "conn": sm_.conn, "elem_type": sm_.elem_type})
            assert jig_bc.rigid_free(sm_.x0, comp, runs[m]["BC"])["rigid_free"] == 0
        # prescribed·spring: tie 행 값 = 목표 법선(병진) 성분, spring 바닥 = 같은 값
        bp, bs = runs["prescribed"]["BC"], runs["spring"]["BC"]
        tp = bp["bc_kind"] == jig_bc.KIND_TIE
        assert np.allclose(bp["bc_val"][tp], bs["sp_g"]) and np.array_equal(bp["bc_node"][tp], bs["sp_node"])
        assert np.all(runs["fixed"]["BC"]["bc_val"][runs["fixed"]["BC"]["bc_kind"] == jig_bc.KIND_TIE] == 0)


def test_v5_response_split_linear(led, led_runs):
    """응답 분해 u = u_g + Σ a_k U_k(맞춤 노드) — BC 값·바닥 해 + 동차 기저 해의 선형 합 = BC 로 푼 전체 해."""
    fm = led["fit"]
    for td in jig_bc.TIE_DOFS:
        for m in METHODS:
            x = led_runs[td][m]
            r = x["r"]
            comb = r["u_g"][fm] + np.einsum("k,kmi->mi", r["a"], np.asarray(x["U"]))
            assert np.abs(comb - r["u_fit"][fm]).max() <= 1e-8 * np.abs(r["u_fit"]).max(), (td, m)
            assert jig_bc.needs_ground(x["BC"]) == bool(np.any(r["u_g"])), (td, m)


def test_v5_membrane_target_normal_beats_translation():
    """원통 패널: 목표 = normal 경계의 기저 하중 응답(굽힘에 tie 접선 운동이 따름 — 막 운동). normal MAC ≥ 0.99(기저 span 안),
    fixed MAC normal > translation(엄격, 병진 고정은 tie 접선 운동을 막아 인공 강성)."""
    P, C, et = cylinder_panel(400.0, 0.8, 200.0, 24, 12)
    mp = mesh_of(P, C, et)
    N = P.shape[0]
    def nid(i, j):
        return i * 13 + j
    J = np.array(sorted({nid(i, j) for i in (1, 8, 16, 23) for j in (2, 6, 10)}), dtype=np.int64)
    c = {"mesh": mp, "X": P, "N": N, "J": J, "sm": model(mp), "wts": jig.node_weights(mp), "omega": np.ones(N, bool),
         "sup321": supports.pick_321(P, supports.pca_corners(P)["idx"])}
    c["fit"] = np.ones(N, bool)
    c["fit"][J] = False
    rs = jig.select_regions(mp, c["fit"], J, None, gap_mm=2.0, knn=8, chunk_nodes=65536, max_regions=8, min_regions=2,
                            min_nodes=3, min_area_mm2=25.0, patch_count=6, weights=c["wts"], surf_reason="no_deck")
    c["regions"] = rs["regions"]
    tie, aux = shared(c, "normal")
    assert jig_bc.node_frames(mp, J, kink_deg=45.0)["rank_counts"][1] == J.size
    bc0 = jig_bc.build_bc(jig_bc.METHODS["fixed"], tie, aux, np.zeros((N, 3)))
    b0 = jig.load_basis(mp, rs["regions"], c["wts"], c["omega"], body_force=True, tangential=True, modes=None)
    a0 = np.zeros(b0["nb"])
    a0[0:3 * len(rs["regions"]):3] = np.random.default_rng(3).uniform(0.5, 2.0, len(rs["regions"])) * 100.0
    a0[-3:] = [5.0, -3.0, 40.0]
    u0 = jig_bc.solve(jig_bc.factorize(c["sm"], bc0), jig.forces(b0, a0, N), bc0)[0][:, :3]
    c["u_rel"] = kabsch.remove_rigid(P, u0)[0]
    mac = {td: {m: x["r"]["report"]["mac"] for m, x in run_methods(c, td, n_modes=0)[0].items()}
           for td in jig_bc.TIE_DOFS}
    assert all(v >= 0.99 for v in mac["normal"].values()), mac
    assert mac["normal"]["fixed"] > mac["translation"]["fixed"] + 0.05, mac
    assert mac["normal"]["prescribed"] > mac["translation"]["prescribed"], mac


def test_v5_q3_aux_values_only_shift_rigid(led, led_runs):
    """Q-JIGC-3: 3-2-1 면내 값(프레임 고정점)은 isostatic 이라 같은 F 에서 면내 강체 이동만 바꿈 — 변형·tie 반력·E·안 점수 무관."""
    x = led_runs["normal"]["fixed"]
    bc = x["BC"]
    bc0 = dict(bc, bc_val=np.where(bc["bc_kind"] == jig_bc.KIND_AUX, 0.0, bc["bc_val"]))
    assert np.any(bc["bc_val"][bc["bc_kind"] == jig_bc.KIND_AUX] != 0)
    F = x["r"]["F"]
    a = jig_bc.respond(x["h"], F, bc)
    b = jig_bc.respond(x["h"], F, bc0)
    du = a["u"][:, :3] - b["u"][:, :3]
    X = led["X"]
    A = np.c_[np.ones(X.shape[0]), X[:, 0], X[:, 1]]                         # 면내 강체: (t_x − ω y, t_y + ω x, 0)
    assert np.abs(du[:, 2]).max() <= 1e-9 * np.abs(a["u"]).max()
    cx = np.linalg.lstsq(A, du[:, 0], rcond=None)[0]
    cy = np.linalg.lstsq(A, du[:, 1], rcond=None)[0]
    assert abs(cx[1]) <= 1e-12 and abs(cy[2]) <= 1e-12 and cx[2] == pytest.approx(-cy[1], rel=1e-8)
    assert np.abs(du[:, 0] - A @ cx).max() <= 1e-9 * np.abs(du).max()
    assert np.allclose(a["rc"], b["rc"], rtol=0, atol=1e-8 * np.abs(a["rc"]).max())
    assert a["energy"]["E"] == pytest.approx(b["energy"]["E"], rel=1e-9)
    smd = model(dict(led["mesh"], thickness=led["mesh"]["thickness"] * 1.25))
    hd = jig_bc.factorize(smd, bc)
    sa = jig_bc.score(jig_bc.respond(hd, F, bc)["energy"]["C_mix"], a["energy"]["C_mix"], a["energy"]["E"])
    sb = jig_bc.score(jig_bc.respond(hd, F, bc0)["energy"]["C_mix"], b["energy"]["C_mix"], b["energy"]["E"])
    assert sa == pytest.approx(sb, abs=1e-9) and sa < 1.0


# ====================================================================== V-6 지표 Π
def _scores(c_mesh, x, designs):
    """안 목록(mesh 변경 함수) → [(s, energy, umax)] — 같은 BC(값·바닥·k)·같은 F(§3.7)."""
    r, bc = x["r"], x["BC"]
    e0 = r["energy"]
    out = []
    for mk in designs:
        hd = jig_bc.factorize(model(mk(c_mesh)), bc)
        rd = jig_bc.respond(hd, r["F"], bc)
        out.append((jig_bc.score(rd["energy"]["C_mix"], e0["C_mix"], e0["E"]), rd["energy"],
                    float(np.linalg.norm(rd["u"][:, :3], axis=1).max())))
    return out


def _region_thick(fac):
    def mk(m):
        ctr = m["x0"][m["conn"]].mean(axis=1)
        sel = (ctr[:, 0] > 80) & (ctr[:, 0] < 220) & (ctr[:, 1] > 50) & (ctr[:, 1] < 150)
        t = m["thickness"].copy()
        t[sel] *= fac
        return dict(m, thickness=t)
    return mk


def test_v6_thickness_monotone_three_methods(led, led_runs):
    """정리 시험: 영역 두께 ×0.8·1·1.25(K_d ⪰ K₀ Loewner) → 세 방식·두 구속 성분 모두 s 엄격 단조 감소, ×1 = 1."""
    for td, runs in led_runs.items():
        for m in METHODS:
            s = [v[0] for v in _scores(led["mesh"], runs[m], [_region_thick(f) for f in (0.8, 1.0, 1.25)])]
            assert s[0] > s[1] > s[2], (td, m, s)
            assert s[1] == pytest.approx(1.0, abs=1e-9)


def test_v6_g_zero_equals_compliance_ratio(led, led_runs):
    """값·바닥 0(fixed·translation): C_mix = E = F·u, s = C_d/C_0(1e-12), per_esl C/C_ref = s."""
    x = led_runs["translation"]["fixed"]
    assert not jig_bc.needs_ground(x["BC"])
    e0 = x["r"]["energy"]
    assert e0["C_mix"] == pytest.approx(e0["W_F"], rel=1e-12) and e0["E"] == pytest.approx(e0["W_F"], rel=1e-9)
    for s, en, _ in _scores(led["mesh"], x, [_region_thick(1.25), _region_thick(0.8)]):
        assert s == pytest.approx(en["W_F"] / e0["W_F"], rel=1e-12, abs=1e-12)
        C = jig_bc.per_esl_C(en["C_mix"], e0["C_mix"], e0["E"])
        assert C / e0["E"] == pytest.approx(s, rel=1e-12)


def test_v6_pure_displacement_energy_and_umax_insensitive(led, led_runs):
    """F = 0 순수 변위(prescribed): 강해지면 Σ|r|·E 증가, s = 2 − U_d/U_0 감소, umax 변화 |Δumax/umax| < |Δs|(지표 선택 근거)."""
    x = led_runs["normal"]["prescribed"]
    bc = x["BC"]
    F0 = np.zeros((led["N"], 3))
    a = jig_bc.respond(x["h"], F0, bc)
    hd = jig_bc.factorize(model(_region_thick(1.25)(led["mesh"])), bc)
    b = jig_bc.respond(hd, F0, bc)
    s = jig_bc.score(b["energy"]["C_mix"], a["energy"]["C_mix"], a["energy"]["E"])
    assert b["energy"]["R_sum"] > a["energy"]["R_sum"] and b["energy"]["E"] > a["energy"]["E"] and s < 1.0
    assert s == pytest.approx(2.0 - b["energy"]["E"] / a["energy"]["E"], rel=1e-9)
    assert a["energy"]["W_F"] == 0.0 and b["energy"]["W_F"] == 0.0               # F·u = 0 — 강성 변화에 둔감
    ua = np.linalg.norm(a["u"][:, :3], axis=1).max()
    ub = np.linalg.norm(b["u"][:, :3], axis=1).max()
    assert abs(ub - ua) / ua < abs(s - 1.0)


def test_v6_bead_depth_direction_and_prescribed_umax_not_consistent():
    """비드 깊이 ×0.5·1·1.5(기준 = ×1, 굽힘 하중 합성 비드 판 + LED tie): 세 방식 s 감소 방향 일정. prescribed 는 umax 가 반대
    방향(깊을수록 패널이 tie 운동을 더 따라 커짐) — umax·F·u 가 지표가 될 수 없는 근거."""
    D0 = 3.0
    c = led_case(depth=D0)
    runs, _, _ = run_methods(c, "normal")

    def depth(f):
        return lambda m: dict(m, x0=bead(c["Xf"], D0 * f))
    for m in METHODS:
        res = _scores(c["mesh"], runs[m], [depth(f) for f in (0.5, 1.0, 1.5)])
        s = [v[0] for v in res]
        assert s[0] > s[1] > s[2] and s[1] == pytest.approx(1.0, abs=1e-9), (m, s)
        if m == "prescribed":
            um = [v[2] for v in res]
            assert um[0] < um[1] < um[2], um                                    # 강해지는데 umax 증가(방향 반대)


# ====================================================================== V-7 스프링
def test_v7_alpha_sweep_converges_to_prescribed(led, led_runs):
    x = led_runs["normal"]["prescribed"]
    tie, aux = shared(led, "normal")
    up = x["r"]["u"][:, :3]
    errs = []
    for a in (0.01, 0.1, 1.0, 10.0, 100.0, 1e4):
        k = jig_bc.spring_k(led["sm"], tie, mode="auto", alpha=a)
        bcs = jig_bc.build_bc(jig_bc.METHODS["spring"], tie, aux, x["tgt"]["u_tgt"], k=k)
        us = jig_bc.solve(jig_bc.factorize(led["sm"], bcs), x["r"]["F"], bcs)[0][:, :3]
        errs.append(float(np.linalg.norm(us - up) / np.linalg.norm(up)))
    assert all(errs[i] > errs[i + 1] for i in range(len(errs) - 1)), errs
    assert errs[-1] < 1e-3
    with pytest.raises(EslError) as ei:
        jig_bc.spring_k(led["sm"], tie, mode="auto", alpha=5e-4)
    assert ei.value.code == "CONFIG_INVALID"


def test_v7_spring_k_fixed_across_designs_and_value_mode(led, led_runs):
    x = led_runs["normal"]["spring"]
    tie, _ = shared(led, "normal")
    bc = x["BC"]
    k0 = jig_bc.spring_k(led["sm"], tie, mode="auto", alpha=1.0)
    assert np.array_equal(bc["sp_k"], k0)
    smd = model(_region_thick(1.25)(led["mesh"]))
    assert not np.allclose(jig_bc.spring_k(smd, tie, mode="auto", alpha=1.0), k0)   # 안 K 로 다시 구하면 달라짐
    hd = jig_bc.factorize(smd, bc)                                                # 안 = 기준 k 그대로(BC.sp_k)
    assert np.array_equal(hd.sp_k, k0)
    kv = jig_bc.spring_k(led["sm"], tie, mode="value", value=2.5e3)
    assert np.all(kv == 2.5e3)
    for bad in ({"mode": "value", "value": None}, {"mode": "value", "value": -1.0}, {"mode": "abs"}):
        with pytest.raises(EslError):
            jig_bc.spring_k(led["sm"], tie, **bad)
    Kcsr = led["sm"].K()                                                          # 희소 행렬 입력 = ShellModel 입력
    assert np.allclose(jig_bc.spring_k(Kcsr, tie, mode="auto", alpha=1.0), k0, rtol=1e-12)


# ====================================================================== 저장 형식 · 패턴
def test_save_load_bc_and_pattern(led_runs, tmp_path):
    runs = led_runs["normal"]
    p = os.path.join(str(tmp_path), "bc.npz")
    np.savez(p, **jig_bc.save_bc(runs["spring"]["BC"]))
    with np.load(p) as z:
        back = jig_bc.load_bc(z)
    for k in jig_bc.BC_KEYS:
        assert np.array_equal(back[k], runs["spring"]["BC"][k]), k
    assert back["bc_kind"].dtype == np.int8 and back["sp_node"].dtype == np.int64
    shas = {m: jig_bc.pattern_sha(runs[m]["BC"]) for m in METHODS}
    assert shas["fixed"] == shas["prescribed"] != shas["spring"]                  # ④ 묶음 = jig+jig_disp · jig_spring
    assert jig_bc.load_bc({})["bc_node"].size == 0


# ====================================================================== v0.24.4 검증 수정 — 분해 순서(solver.jig_factor_order)
def _order_case(n=14, tie_dofs="normal"):
    P, C, et = rect_quads(300.0, 200.0, n, n)
    P = np.asarray(P, dtype=np.float64).copy()
    P[:, 2] = 8.0 * np.sin(np.pi * P[:, 0] / 300.0) * np.sin(np.pi * P[:, 1] / 200.0)
    mesh = mesh_of(P, C, et)
    N = len(P)
    J = np.unique(np.random.default_rng(3).choice(N, size=max(8, N // 20), replace=False))
    ny = n + 1
    sup = [(0, "123"), (n * ny, "23"), (n, "3")]
    tie = jig_bc.tie_rows(mesh, J, tie_dofs, kink_deg=45.0)
    aux = jig_bc.aux_rows(P, sup, tie, tie_dofs, dup_deg=10.0)
    BC = jig_bc.build_bc(jig_bc.METHODS["fixed"], tie, aux, np.zeros((N, 3)))
    F = np.random.default_rng(1).standard_normal((N, 3))
    F -= F.mean(axis=0)
    return mesh, BC, F


@pytest.mark.parametrize("tie_dofs", ["normal", "translation"])
def test_jig_factor_order_same_result_both_branches(tie_dofs):
    """node_mmd = default 결과(≤5e-11 상대 — 반올림 수준, 합성 스프링 최대 1.28e-11 관측) — factorize_bc(법선) 와 spc 가지(병진) 모두. 순서만 다르다."""
    mesh, BC, F = _order_case(tie_dofs=tie_dofs)
    out = {}
    for order in ("default", "node_mmd"):
        sm = ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"],
                        backend="superlu", jig_factor_order=order)
        h = jig_bc.factorize(sm, BC)
        out[order] = jig_bc.solve(h, F, BC)[0]
        lu = (h.h if hasattr(h, "h") else h).lu                       # SpcSolve(.h = FactorizedSolve) 또는 BcSolve
        assert (lu._perm is None) == (order == "default")
    a, b = out["default"], out["node_mmd"]
    assert np.abs(a - b).max() <= 5e-11 * np.abs(a).max()


def test_jig_factor_order_does_not_touch_old_paths_and_validates():
    from esl import config
    from esl.mech.shell import JIG_FACTOR_ORDERS, solver_check_kwargs

    mesh, _BC, F = _order_case()
    sm = ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"], backend="superlu")
    assert sm.jig_factor_order == config.SOLVER_JIG_DEFAULTS["jig_factor_order"] == JIG_FACTOR_ORDERS[0]
    h = sm.factorize([(0, "123"), (14 * 15, "23"), (14, "3")])          # 옛 3-2-1 호출 — order 안 줌 = 순열 없음(예전 MMD, 바이트 불변)
    assert h.lu._perm is None
    with pytest.raises(EslError) as ei:
        ShellModel(mesh["x0"], mesh["conn"], mesh["elem_type"], mesh["thickness"], mesh["E"], mesh["nu"], jig_factor_order="x")
    assert ei.value.code == "CONFIG_INVALID"
    assert "jig_factor_order" not in solver_check_kwargs({"drill_factor": 1e-4})          # 지정 안 하면 인자 없음
    assert solver_check_kwargs({"jig_factor_order": "default"})["jig_factor_order"] == "default"
    assert "solver.jig_factor_order" in config.OPTIONAL_KEYS
