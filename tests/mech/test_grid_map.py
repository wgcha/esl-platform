"""v0.24.8 격자 지그 순수 모듈 esl.mech.grid_map(계약 esl_jig_grid_map.md §1·§2.1·§4 — V-0248-JG-2·3·4·6·7·9·19·21).

측정값(허용 오차 표 §4.1·§4.2·§4.3 은 "측정 후 확정")은 ``-s`` 로 출력한다(GRIDMAP 줄)."""
from __future__ import annotations

import ast
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests", "doe"))
import synth_jig_grid as G  # noqa: E402

from esl.mech import grid_map as gm  # noqa: E402
from esl.mech import jig_bc, kabsch  # noqa: E402

PARAMS = {"tie_dofs": "normal", "kink_deg": 45.0, "dup_deg": 10.0}


def _case(A, methods=("prescribed", "spring"), n=1, **kw):
    us = [G.u_drop(A, k) for k in range(n)]
    Fs = [G.forces(A, u) for u in us]
    cjs = [G.case_jig(A, u, F, methods=methods, **kw) for u, F in zip(us, Fs)]
    return us, Fs, cjs


def _run(A, S, us, Fs, cjs, methods, *, cell=3.0, hS=None, keep_u=True, values=None, sup=None, R=None, Xs=None, cfg=None,
         grp=None):
    grp = grp or G.grid_group(A, us, cjs, methods, cell)
    L, info = G.shape_loads(A, S, Fs, cell, h=hS or 3.0)
    srcs = [jig_bc.METHODS[m]["src"] for m in methods]
    loads = {s: [(f"E{k}", F) for k, (_e, F) in enumerate(L)] for s in srcs}
    res = gm.run_shape(S, sup if sup is not None else G.sup321(S), loads, grp["skel"], grp["field"], grp["GF"],
                       np.eye(3) if R is None else R, S["x0"] if Xs is None else Xs, methods=list(methods),
                       entries=[f"E{k}" for k in range(len(Fs))], params=PARAMS, cfg=cfg or G.GRID_CFG,
                       solver_cfg=G.SOLVER, spring=grp["spring"], keep_u=keep_u, values=values)
    return res, info, grp


def _mac(u, v):
    return float(gm.mac(u, v))


# ---------------------------------------------------------------- V-0248-JG-2 항등(§4.1) — A 를 형상으로(격자 경로 그대로)
@pytest.mark.parametrize("h", [5.0, 1.5])
def test_identity_table(h, capsys):
    A = G.plate(h)
    methods = ("prescribed", "spring")
    us, Fs, cjs = _case(A, methods)
    res, info, grp = _run(A, A, us, Fs, cjs, methods, hS=h)
    P = grp["skel"]["idx"]
    umax_ref = float(np.linalg.norm(us[0], axis=1).max())
    # 하중 ΣF·ΣM ≤ 1e-9(LT-4)
    p0 = info["per_esl"][0]
    assert p0["dF_rel"] <= 1e-9 and p0["dM_rel"] <= 1e-9
    tie = res["map"]["tie"]
    assert tie["n_snap"] == 0 and tie["n_miss"] == 0
    out = {}
    for m in methods:
        src = jig_bc.METHODS[m]["src"]
        z, doc = cjs[0][src]
        r = res["methods"][src]
        assert r["status"] == "ok", r
        cb, BC = jig_bc.load_bc(z), res["bc"][src]
        capt = np.unique(np.r_[BC["bc_node"][BC["bc_kind"] == jig_bc.KIND_TIE], BC["sp_node"]])
        assert np.array_equal(capt, P)                                         # tie 집합 같음
        if src == "jig_spring":
            dd = np.abs(BC["sp_dir"] - cb["sp_dir"]).max()
            gg = np.abs(BC["sp_g"] - cb["sp_g"]).max()
            ns = np.bincount(np.searchsorted(P, BC["sp_node"]), BC["sp_k"])
            nc = np.bincount(np.searchsorted(P, cb["sp_node"]), cb["sp_k"])
            ksum = float(np.abs(ns / nc - 1.0).max())
            assert ksum <= 1e-12 and tie["k_scale_min"] == pytest.approx(1.0, abs=1e-12) \
                and tie["k_scale_max"] == pytest.approx(1.0, abs=1e-12)
        else:
            t1, t2 = BC["bc_kind"] == jig_bc.KIND_TIE, cb["bc_kind"] == jig_bc.KIND_TIE
            dd = np.abs(BC["bc_dir"][t1] - cb["bc_dir"][t2]).max()
            gg = np.abs(BC["bc_val"][t1] - cb["bc_val"][t2]).max()
            ksum = None
            assert BC["sp_node"].size == 0 and BC["sp_k"].size == 0                 # prescribed = k 없음
        assert dd <= 1e-12 and gg <= 1e-9 * umax_ref
        aux_c = cb["bc_node"][cb["bc_kind"] == jig_bc.KIND_AUX]
        aux_s = BC["bc_node"][BC["bc_kind"] == jig_bc.KIND_AUX]
        assert np.array_equal(aux_c, aux_s)                                     # 3-2-1 노드 같음(Case 지지를 넘김)
        row = r["rows"]["E0"]
        E = doc["energy"]["E"]
        uS = kabsch.remove_rigid(A["x0"], res["u"][src]["E0"])[0]
        umc, ums = np.linalg.norm(z["u_val"], axis=1).max(), np.linalg.norm(uS, axis=1).max()
        o = {"dPi": abs(row["C_mix"] - doc["energy"]["C_mix"]) / E, "dE": abs(row["E"] - E) / E,
             "dumax": abs(ums - umc) / umc, "mac": _mac(uS, z["u_val"]), "dir": float(dd), "g": float(gg) / umax_ref,
             "ksum": ksum}
        out[src] = o
        assert o["dPi"] <= 1e-2 and o["dE"] <= 1e-2 and o["dumax"] <= 1e-2 and o["mac"] >= 0.999, o
    with capsys.disabled():
        print(f"\nGRIDMAP identity h={h} load dF {p0['dF_rel']:.1e} dM {p0['dM_rel']:.1e} small {p0['small_frac']:.2f} {out}")


def test_identity_value_mode_and_fixed_shares_factor():
    """k_mode value(모든 행 같은 k → 행별 같음 ≤ 1e-12) + fixed 있는 Case: [fixed, prescribed, spring] 분해 2(V-9)."""
    A = G.plate(5.0)
    methods = ("fixed", "prescribed", "spring")
    us, Fs, cjs = _case(A, methods, k_mode="value", k_value=800.0)
    res, _info, _grp = _run(A, A, us, Fs, cjs, methods, hS=5.0)
    assert res["factor"]["n"] == 2
    BC, cb = res["bc"]["jig_spring"], jig_bc.load_bc(cjs[0]["jig_spring"][0])
    assert np.abs(BC["sp_k"] / cb["sp_k"] - 1.0).max() <= 1e-12                 # 행별(value)
    for src in ("jig", "jig_disp", "jig_spring"):
        doc = cjs[0][src][1]
        row = res["methods"][src]["rows"]["E0"]
        assert abs(row["C_mix"] - doc["energy"]["C_mix"]) / doc["energy"]["E"] <= 1e-2
    assert res["methods"]["jig"]["shared"] and res["methods"]["jig_disp"]["shared"]


def test_identity_kink_rank2_auto():
    """꺾임 r_n = 2 노드 포함(auto — 행 k 가 방향마다 다름): 노드 행 합 = Case Σ_r sp_k(≤ 1e-12), c_q = 1, 행별은 다를 수 있음."""
    A = G.fold_plate(5.0, xf=150.0, deg=60.0)
    X = np.asarray(A["x0"])
    J = np.flatnonzero(np.hypot(X[:, 0] - 150.0, X[:, 2] - 75.0) <= 10.0)
    J = np.union1d(J, G.tie_idx(A, bolts=((30.0, 25.0), (30.0, 125.0), (100.0, 20.0))))
    u = G.u_drop(A, 0)
    F = G.forces(A, u)
    cj = G.case_jig(A, u, F, methods=("prescribed", "spring"), J=J)
    res, _i, grp = _run(A, A, [u], [F], [cj], ("prescribed", "spring"), hS=5.0)
    BC, cb = res["bc"]["jig_spring"], jig_bc.load_bc(cj["jig_spring"][0])
    P = grp["skel"]["idx"]
    rn = np.bincount(np.searchsorted(P, cb["sp_node"]))
    assert (rn == 2).any()                                                      # 꺾임 노드 있음
    ns = np.bincount(np.searchsorted(P, BC["sp_node"]), BC["sp_k"])
    nc = np.bincount(np.searchsorted(P, cb["sp_node"]), cb["sp_k"])
    assert np.abs(ns / nc - 1.0).max() <= 1e-12
    assert res["map"]["tie"]["k_scale_min"] == pytest.approx(1.0, abs=1e-12)
    assert not np.allclose(BC["sp_k"], cb["sp_k"], rtol=1e-12, atol=0)         # auto r_n ≥ 2 = 균등 분배라 행별 차이(허용)


# ---------------------------------------------------------------- V-0248-JG-3 수렴(§4.2) · V-9 분해 재사용
# D-0.24.8-JG-17: ΔΠ_s = 격자 크기 민감도(3 mm 오차 아님 — 오차 근거 §4.1·§4.3), 기준 ΔΠ_5 ≤ 0.05·ΔΠ_10 ≤ 0.07·MAC ≥ 0.995.
def test_convergence_remesh_and_no_extra_factor(capsys):
    A = G.plate(5.0)
    S = G.plate(3.0, tri_cols=6, node_base=200001)
    methods = ("prescribed", "spring")
    us, Fs, cjs = _case(A, methods)
    grp = G.grid_group(A, us, cjs, methods, 3.0)
    values = []
    for s2 in (5.0, 10.0):
        L2, _ = G.shape_loads(A, S, Fs, s2)
        f2 = gm.build_field(gm.grid_frame(G.frame_of(A), s2), A["x0"], gm.jig.node_weights(A), {"part": np.stack(us)})
        values.append({"key": s2, "loads": {s: [("E0", L2[0][1])] for s in ("jig_disp", "jig_spring")}, "field": f2,
                       "GF": gm.grid_frame(G.frame_of(A), s2)})
    res0, _i, _g = _run(A, S, us, Fs, cjs, methods, grp=grp)
    res, _i, _g = _run(A, S, us, Fs, cjs, methods, values=values, grp=grp)
    assert res["factor"]["n"] == res0["factor"]["n"] == 2                       # 수렴 진단 분해 0 추가
    meas = {}
    for src in ("jig_disp", "jig_spring"):
        r0 = res["methods"][src]["rows"]["E0"]
        for s2 in (5.0, 10.0):
            rv = res["values"][s2][src]["E0"]
            meas[(src, s2)] = (abs(rv["C_mix"] - r0["C_mix"]) / r0["E"], _mac(rv["u"], res["u"][src]["E0"]))
    with capsys.disabled():
        print(f"\nGRIDMAP conv {({f'{k[0]}@{k[1]:g}': (f'{v[0]:.2e}', f'{v[1]:.6f}') for k, v in meas.items()})}")
    for (src, s2), (dpi, mc) in meas.items():
        assert dpi <= (0.05 if s2 == 5.0 else 0.07) and mc >= 0.995, (src, s2, dpi, mc)


# ---------------------------------------------------------------- V-0248-JG-4 다른 메시 정확도(§4.3)
# D-0.24.8-JG-16: 골격 밖 띠 노드 g = 최근접 골격 요소 선형 외삽, 면적비 기준 = [1/area_ratio_warn, area_ratio_warn] = [0.5, 2].
def test_cross_mesh_accuracy(capsys):
    A = G.plate(5.0)
    S = G.plate(3.0, tri_cols=10, node_base=300001)
    methods = ("prescribed", "spring")
    us, Fs, cjs = _case(A, methods)
    res, _i, _g = _run(A, S, us, Fs, cjs, methods)
    tie = res["map"]["tie"]
    meas = {"tie": {k: tie[k] for k in ("n_miss", "n_snap", "area_ratio_min", "area_ratio_max", "k_scale_min", "k_scale_max")}}
    for src in ("jig_disp", "jig_spring"):
        z, doc = cjs[0][src]
        row = res["methods"][src]["rows"]["E0"]
        uS = kabsch.remove_rigid(S["x0"], res["u"][src]["E0"])[0]
        ut = kabsch.remove_rigid(S["x0"], G.u_drop(S, 0))[0]                   # 같은 형상 → 같은 해석 변위장
        uc = kabsch.remove_rigid(A["x0"], z["u_val"])[0]
        meas[src] = {"dPi": abs(row["C_mix"] - doc["energy"]["C_mix"]) / doc["energy"]["E"],
                     "dumax": abs(np.linalg.norm(uS, axis=1).max() / np.linalg.norm(uc, axis=1).max() - 1.0),
                     "mac_vs_field": _mac(uS, ut)}
    with capsys.disabled():
        print(f"\nGRIDMAP cross-mesh {meas}")
    assert tie["n_miss"] == 0 and 0.5 <= tie["area_ratio_min"] and tie["area_ratio_max"] <= 2.0
    for src in ("jig_disp", "jig_spring"):
        m = meas[src]
        assert m["dPi"] <= 3e-2 and m["dumax"] <= 3e-2 and m["mac_vs_field"] >= 0.99, (src, m)


# ---------------------------------------------------------------- V-0248-JG-6 잡기
def _skel(A, J, us=None):
    us = us or [G.u_drop(A, 0)]
    td, tr = gm.tie_dirs_of(J, *(lambda t: (t["node"], t["dir"], np.zeros(0, np.int64), np.zeros((0, 3))))(
        jig_bc.tie_rows(A, J, "normal", kink_deg=45.0)))
    return gm.tie_skeleton(A, np.asarray(J), td, tr, {"part": np.stack(us)[:, J]})


def _cap(skel, S, Xs=None, R=None, **kw):
    a = {"capture_rel": 0.25, "snap_rel": 0.75, "normal_deg": 30.0, **kw}
    return gm.capture(skel, S, S["x0"] if Xs is None else Xs, np.eye(3) if R is None else R, **a)


def test_capture_ring_washer_isolated_and_missing():
    A = G.plate(5.0)
    X = np.asarray(A["x0"])
    r = np.hypot(X[:, 0] - 100.0, X[:, 2] - 75.0)
    ring = np.flatnonzero((r >= 8.0) & (r <= 13.0))                               # 구멍 고리 모양 tie(환형 띠)
    washer = G.tie_idx(A, bolts=((30.0, 25.0),))
    iso = np.flatnonzero(np.hypot(X[:, 0] - 170.0, X[:, 2] - 125.0) < 1e-9)       # 고립 점 1개
    J = np.unique(np.r_[ring, washer, iso])
    sk = _skel(A, J)
    S = G.plate(3.0, tri_cols=4, node_base=400001, offset=(1.0, 0.0, 1.0))        # 노드가 A 와 어긋난 다른 메시
    cap = _cap(sk, S)
    via = {c["q"]: c["via"] for c in cap["clusters"]}
    assert sk["n_q"] >= 3 and set(via.values()) <= {"band", "snap"} and not any(c["miss"] for c in cap["clusters"])
    q_iso = int(sk["q"][np.searchsorted(sk["idx"], iso[0])])
    assert via[q_iso] == "snap" and next(c for c in cap["clusters"] if c["q"] == q_iso)["n_s"] == 1
    q_ring = np.unique(sk["q"][np.searchsorted(sk["idx"], ring)])               # 고리(5 mm 격자에선 여러 조각)
    rs = np.hypot(S["x0"][cap["idx"], 0] - 100.0, S["x0"][cap["idx"], 2] - 75.0)[np.isin(cap["q"], q_ring)]
    assert rs.size > 5 and rs.min() >= 8.0 - 1.0 and rs.max() <= 13.0 + 1.0       # 고리 띠 안(가장자리 r_cap 여유)
    # 구멍 없는 형상(그 클러스터 영역이 형상에 없음) → miss
    S2 = G.plate(3.0, node_base=500001)
    keep = np.hypot(S2["x0"][:, 0] - 30.0, S2["x0"][:, 2] - 25.0) > 20.0
    S2c = _crop(S2, keep)
    cap2 = _cap(sk, S2c)
    assert sum(c["miss"] for c in cap2["clusters"]) == 1


def _crop(m, keep_nodes):
    conn = np.asarray(m["conn"])
    q = np.asarray(m["elem_type"]) == 4
    ok = np.where(q, np.all(keep_nodes[np.maximum(conn, 0)], axis=1), np.all(keep_nodes[np.maximum(conn[:, :3], 0)], axis=1))
    used = np.zeros(len(keep_nodes), bool)
    used[conn[ok][q[ok]].ravel()] = True
    used[conn[ok][~q[ok]][:, :3].ravel()] = True
    new = -np.ones(len(keep_nodes), np.int64)
    new[used] = np.arange(used.sum())
    c2 = np.where(conn[ok] >= 0, new[np.maximum(conn[ok], 0)], -1)
    out = {k: np.asarray(m[k])[used] for k in ("node_id", "x0")}
    out.update({k: np.asarray(m[k])[ok] for k in ("elem_id", "elem_type", "elem_pid", "elem_mid", "thickness", "E", "nu")})
    out["conn"] = c2
    return out


def test_capture_rejects_perpendicular_flange_and_placement_invariant():
    A = G.plate(5.0)
    J = G.tie_idx(A, bolts=((145.0, 75.0),))
    sk = _skel(A, J)
    S = G.fold_plate(3.0, xf=150.0, deg=90.0, node_base=600001)                   # tie 끝(x = 150)에서 수직 플랜지
    cap = _cap(sk, S)
    assert cap["n_reject_normal"] > 0
    assert np.all(np.abs(cap["normal_A"][cap["idx"], 1]) > 0.8)                    # 잡힌 노드 = 판 법선(y)만
    # 배치 rigid(회전 불변 — 같은 집합): 형상을 돌려 놓고 unplace 좌표·R_pl 로 잡기
    S0 = G.plate(3.0, node_base=700001)
    c0 = _cap(sk, S0)
    th = np.radians(25.0)
    R = np.array([[np.cos(th), 0.0, np.sin(th)], [0.0, 1.0, 0.0], [-np.sin(th), 0.0, np.cos(th)]])
    t = np.array([40.0, 5.0, -20.0])
    Sr = dict(S0)
    Sr["x0"] = S0["x0"] @ R.T + t
    Xs = (Sr["x0"] - t) @ R                                                         # ltm.unplace_points(rigid)
    cr = _cap(sk, Sr, Xs=Xs, R=R)
    assert np.array_equal(c0["idx"], cr["idx"])
    # 배치 frame: 정규화 사상(같은 형상 — 항등) = 같은 집합
    from esl.doe import load_transfer as ltm
    fr = G.frame_of(S0)
    Xf = ltm.unplace_points(S0["x0"], {"kind": "frame", "src_frame": G.frame_of(A), "dst_frame": fr})
    cf = _cap(sk, S0, Xs=Xf, R=ltm.placement_rotation({"kind": "frame", "src_frame": G.frame_of(A), "dst_frame": fr}))
    assert np.array_equal(c0["idx"], cf["idx"])


def test_tie_miss_fraction_fails_shape():
    A = G.plate(5.0)
    us, Fs, cjs = _case(A)
    S = _crop(G.plate(3.0, node_base=800001), np.asarray(G.plate(3.0)["x0"])[:, 2] > 60.0)   # 아래쪽 볼트 3개 영역 없음
    res, _i, _g = _run(A, S, us, Fs, cjs, ("prescribed", "spring"))
    assert res["map"]["tie"]["n_miss"] == 3
    assert all(m["status"] == "failed" and m["code"] == "JIG_GRID_TIE_MISS" for m in res["methods"].values())


# ---------------------------------------------------------------- V-0248-JG-7 표본
def test_sample_linear_exact_const_outside_deterministic():
    A = G.plate(2.0)                                                               # A 가 격자보다 촘촘(복셀 빈칸 없음)
    X = np.asarray(A["x0"])
    a = np.array([[1e-3, 2e-3, -1e-3], [0.0, 0.0, 0.0], [5e-4, -1e-3, 3e-3]])
    U = (X @ a + np.array([0.1, -0.2, 0.3]))[None]
    GF = gm.grid_frame(G.frame_of(A), 3.0)
    f = gm.build_field(GF, X, gm.jig.node_weights(A), {"part": U})
    S = G.plate(3.0, node_base=900001, offset=(0.0, 0.0, 0.0))
    inside = (S["x0"][:, 0] > 10) & (S["x0"][:, 0] < 190) & (S["x0"][:, 2] > 10) & (S["x0"][:, 2] < 140)
    q = np.flatnonzero(inside)[::37]
    m = np.tile([0.0, 1.0, 0.0], (q.size, 1))
    r = gm.sample_field(f, GF, S["x0"][q], m, "part", 0, nbr=1, normal_deg=45.0)
    ex = S["x0"][q] @ a + np.array([0.1, -0.2, 0.3])
    assert np.abs(r["u"] - ex).max() <= 1e-9 and r["n_const"] == 0
    r2 = gm.sample_field(f, GF, S["x0"][q], m, "part", 0, nbr=1, normal_deg=45.0)
    assert r2["u"].tobytes() == r["u"].tobytes()                                   # 결정적(비트 동일)
    far = np.array([[100.0, 80.0, 75.0]])                                          # 판에서 80 mm 위 = 격자 밖
    ro = gm.sample_field(f, GF, far, np.array([[0.0, 1.0, 0.0]]), "part", 0, nbr=1, normal_deg=45.0)
    assert ro["n_outside"] == 1 and np.all(ro["u"] == 0.0)
    # 후보 부족 = 상수(가중 평균): 복셀 1개만 남긴 장
    f1 = {k: (v[:1] if k != "u" else {kk: vv[:, :1] for kk, vv in v.items()}) for k, v in f.items()}
    rc = gm.sample_field(f1, GF, f1["x"][:1] + [0.3, 0.0, 0.2], np.array([[0.0, 1.0, 0.0]]), "part", 0, nbr=1, normal_deg=45.0)
    assert rc["n_const"] == 1 and np.allclose(rc["u"][0], f1["u"]["part"][0, 0])


# ---------------------------------------------------------------- V-0248-JG-9 분해 공유
def test_factor_count_two_methods():
    A = G.plate(5.0)
    S = G.plate(4.0, node_base=1000001)
    us, Fs, cjs = _case(A, n=2)
    res, _i, _g = _run(A, S, us, Fs, cjs, ("prescribed", "spring"), keep_u=False)
    assert res["factor"]["n"] == 2 and set(res["methods"]["jig_disp"]["rows"]) == {"E0", "E1"}


# ---------------------------------------------------------------- V-0248-JG-21 스프링 k 메시·설계 무관
def test_spring_k_mesh_and_design_invariant(monkeypatch):
    A = G.plate(5.0)
    us, Fs, cjs = _case(A, ("prescribed", "spring"))
    grp = G.grid_group(A, us, cjs, ("prescribed", "spring"))
    kq = grp["spring"]["jig_spring"][1]
    X = np.asarray(A["x0"])
    iso = np.flatnonzero(np.hypot(X[:, 0] - 170.0, X[:, 2] - 125.0) < 1e-9)
    J = np.unique(np.r_[G.tie_idx(A, bolts=((30.0, 25.0),)), iso])
    cj = G.case_jig(A, us[0], Fs[0], methods=("spring",), J=J)                    # Case 쪽(spring_k 사용)은 막기 전에

    def boom(*a, **k):
        raise AssertionError("격자 경로에서 jig_bc.spring_k 호출")
    monkeypatch.setattr(jig_bc, "spring_k", boom)
    for h, nb in ((5.0, 1), (3.0, 1100001), (1.5, 1200001)):
        S = G.plate(h, node_base=nb)
        cap = _cap(grp["skel"], S)
        tie = jig_bc.tie_rows(S, cap["idx"], "normal", kink_deg=45.0)
        k = gm.shape_spring_k(grp["skel"], cap, tie, cap["area_S"], *grp["spring"]["jig_spring"])
        qr = cap["q"][np.searchsorted(cap["idx"], tie["node"])]
        sq = np.bincount(qr, weights=k["k"], minlength=kq.size)
        assert np.abs(sq / kq - 1.0).max() <= 1e-12, h
    # 비드 모핑(tie 근처, 같은 위상) — 클러스터 Σk 불변
    Sb = G.plate(3.0, bead=(30.0, 45.0, 3.0), node_base=1300001)
    cap = _cap(grp["skel"], Sb)
    tie = jig_bc.tie_rows(Sb, cap["idx"], "normal", kink_deg=45.0)
    k = gm.shape_spring_k(grp["skel"], cap, tie, cap["area_S"], *grp["spring"]["jig_spring"])
    qr = cap["q"][np.searchsorted(cap["idx"], tie["node"])]
    assert np.abs(np.bincount(qr, weights=k["k"], minlength=kq.size) / kq - 1.0).max() <= 1e-12
    # snap 1노드 클러스터 = K_q 전부
    g2 = G.grid_group(A, [us[0]], [cj], ("spring",))
    S = G.plate(3.0, node_base=1400001, offset=(1.0, 0.0, 1.0))
    cap = _cap(g2["skel"], S)
    tie = jig_bc.tie_rows(S, cap["idx"], "normal", kink_deg=45.0)
    k = gm.shape_spring_k(g2["skel"], cap, tie, cap["area_S"], *g2["spring"]["jig_spring"])
    q_iso = int(g2["skel"]["q"][np.searchsorted(g2["skel"]["idx"], iso[0])])
    rows = cap["q"][np.searchsorted(cap["idx"], tie["node"])] == q_iso
    assert cap["via"][cap["q"] == q_iso].tolist() == [gm.VIA_SNAP]
    assert k["k"][rows].sum() == pytest.approx(g2["spring"]["jig_spring"][1][q_iso], rel=1e-12)


# ---------------------------------------------------------------- V-0248-JG-19 모듈 순수
def test_module_pure_static():
    src = open(os.path.join(ROOT, "esl", "mech", "grid_map.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods |= {f"{n.module}.{a.name}" for a in n.names}
    assert not any(m.startswith("esl.doe") for m in mods), mods
    allowed = ("numpy", "scipy.spatial", "scipy.sparse", "esl.errors", "esl.library.normalize", "esl.mech",
               "__future__", "itertools", "time", "typing")
    assert all(m.startswith(allowed) for m in mods), sorted(m for m in mods if not m.startswith(allowed))
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attrs = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "open" not in calls and not ({"savez", "savez_compressed", "load", "save", "write_json", "read_json"} & attrs)
    for name in ("same", "mesh", "step", "compare", "select", "case_once", "compare_per_shape", "step_per_design"):
        assert f'"{name}"' not in src                                              # 시나리오·계획 이름 없음


def test_values_reuse_factor_no_extra():
    """V-0248-JG-9: 수렴 진단(values — 다른 크기 하중·3-2-1 값)은 분해를 다시 하지 않는다(형상당 분해 2 그대로)."""
    A = G.plate(5.0)
    S = G.plate(4.0, node_base=1500001)
    methods = ("prescribed", "spring")
    us, Fs, cjs = _case(A, methods)
    grp = G.grid_group(A, us, cjs, methods, 3.0)
    values = []
    for s2 in (5.0, 10.0):
        L2, _ = G.shape_loads(A, S, Fs, s2, h=4.0)
        GF2 = gm.grid_frame(G.frame_of(A), s2)
        values.append({"key": s2, "loads": {s: [("E0", L2[0][1])] for s in ("jig_disp", "jig_spring")},
                       "field": gm.build_field(GF2, A["x0"], gm.jig.node_weights(A), {"part": np.stack(us)}), "GF": GF2})
    res, _i, _g = _run(A, S, us, Fs, cjs, methods, hS=4.0, values=values, grp=grp)
    assert res["factor"]["n"] == 2 and set(res["values"]) == {5.0, 10.0}
    assert all(res["values"][s2][src]["E0"]["E"] > 0 for s2 in (5.0, 10.0) for src in ("jig_disp", "jig_spring"))
