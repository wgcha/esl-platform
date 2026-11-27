"""v0.25.2 B — 체결부 아닌 곳 강제 부여(계약 esl_tstar_manual_jig_force.md §3, V-0252-11~17 코어·물리).

세계 = synth_jig_grid(A 판 200×150 · 볼트 6곳 와셔 tie 반지름 9 mm · 가짜 Case 지그 prescribed·spring). 형상 = 다른 메시 판,
체결부 면이 없는 형상 = 볼트 둘레 요소를 뺀 판(G.holes), 좌표 통째 어긋남 = 형상 A 좌표를 판 법선으로 δ 옮김.
측정값은 ``-s`` 로 출력(GRIDFORCE 줄).
"""
from __future__ import annotations

import copy
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests", "doe"))
sys.path.insert(0, os.path.join(ROOT, "tests", "mech"))
import synth_jig_grid as G  # noqa: E402
import test_grid_map as TG  # noqa: E402

from esl.doe import DEFAULTS, check_tie_force, settings  # noqa: E402
from esl.doe import stages as stg  # noqa: E402
from esl.errors import EslError  # noqa: E402
from esl.mech import grid_map as gm  # noqa: E402
from esl.mech import jig_bc  # noqa: E402

FORCE = {"enabled": True, "max_dist_mm": None, "normal_deg": 90.0}
CFG_F = {**G.GRID_CFG, "tie_force": dict(FORCE), "tie_force_far_warn_mm": 10.0}
CFG_STG = {**DEFAULTS["rank"]["jig_grid"], **CFG_F}          # 경고 문구 함수(stages) 용 전체 격자 설정
M2 = ("prescribed", "spring")


@pytest.fixture(scope="module")
def world():
    A = G.plate(5.0)
    us, Fs, cjs = TG._case(A, M2)
    grp = G.grid_group(A, us, cjs, M2, 3.0)
    return {"A": A, "us": us, "Fs": Fs, "cjs": cjs, "grp": grp}


def _run(w, S, cfg, **kw):
    return TG._run(w["A"], S, w["us"], w["Fs"], w["cjs"], M2, cfg=cfg, grp=w["grp"], **kw)


def _cap(w, S, force=FORCE, Xs=None, **kw):
    a = {"capture_rel": 0.25, "snap_rel": 0.75, "normal_deg": 30.0, **kw}
    return gm.capture(w["grp"]["skel"], S, S["x0"] if Xs is None else Xs, np.eye(3), force=force, **a)


def _rows(res):
    return {s: {e: {k: v for k, v in r.items()} for e, r in m["rows"].items()} for s, m in res["methods"].items()}


# ------------------------------------------------------------------ V-0252-11 항등
def test_v0252_11_identity_no_force(world):
    A = world["A"]
    r0, _i, _g = _run(world, A, G.GRID_CFG)
    r1, _i, _g = _run(world, A, CFG_F)
    t1 = r1["map"]["tie"]
    assert t1["n_force"] == 0 and t1["n_far"] == 0 and t1["ref"] is False and t1["marks"] == []
    assert t1["force"]["dist_max_mm"] is None and t1["force"]["limit_mm"] is None and t1["force"]["far_mm"] == 10.0
    assert "n_force" not in r0["map"]["tie"]                                    # 끔 = 옛 map.tie 키 그대로
    assert {k: v for k, v in t1.items() if k in r0["map"]["tie"]} == r0["map"]["tie"]
    assert _rows(r1) == _rows(r0)                                               # 값 같음
    assert r1["force_nodes"].size == 0 and "force_nodes" not in r0


# ------------------------------------------------------------------ V-0252-12 강제 단계 규칙
def _brute(w, S, cap, q):
    """기대 선택(정의 그대로 — 형상 전 노드 정확 거리 정렬): 앞 단계가 안 잡은 노드, (d, 노드) 오름차순, 면적 합 ≥ A_q 첫 노드까지."""
    sk = w["grp"]["skel"]
    taken = np.zeros(S["x0"].shape[0], bool)
    taken[cap["idx"][cap["via"] != gm.VIA_FORCE]] = True
    cand = np.flatnonzero(~taken)
    Pq = np.flatnonzero(sk["q"] == q)
    segq = np.flatnonzero(sk["q"][sk["seg"][:, 0]] == q)
    triq = np.flatnonzero(sk["q"][sk["tri"][:, 0]] == q)
    _k, _e, d, _p, _w = gm._closest_cluster(sk, S["x0"][cand], Pq, segq, triq)
    o = np.lexsort((cand, d))
    a = cap["area_S"][cand[o]]
    m = int(np.flatnonzero(np.cumsum(a) >= sk["area"][Pq].sum())[0]) + 1
    return np.sort(cand[o][:m]), float(d[o][m - 1])


def test_v0252_12_force_rule_holes(world, capsys):
    S = G.holes(G.plate(3.0, node_base=900001), [1])                          # 볼트 1(100, 20) 둘레 r 13 요소 없음
    c0 = _cap(world, S, force=None)
    assert sum(c["miss"] for c in c0["clusters"]) == 1 and "force" not in c0  # 옛 경로 = 못 잡음
    cap = _cap(world, S)
    cl = {c["q"]: c for c in cap["clusters"]}
    fq = [q for q, c in cl.items() if c["via"] == "force"]
    assert len(fq) == 1 and not any(c["miss"] for c in cap["clusters"])
    q = fq[0]
    exp, dmax = _brute(world, S, cap, q)
    got = np.sort(cap["idx"][(cap["q"] == q) & (cap["via"] == gm.VIA_FORCE)])
    assert np.array_equal(got, exp)                                             # 거리순 · 면적 합 첫 노드까지
    c = cl[q]
    assert c["dist"] == pytest.approx(dmax) and c["dist"] >= 13.0 - 9.0 - 1.0 and c["shift"] >= 0.0
    assert c["area_s"] >= c["area_a"] and c["area_s"] == pytest.approx(float(cap["area_S"][got].sum()))
    # 값 = 골격 최근접점(클립 — 외삽 없음): 무게 합 1·모두 ≥ 0
    sel = (cap["q"] == q) & (cap["via"] == gm.VIA_FORCE)
    assert np.allclose(cap["w"][sel].sum(axis=1), 1.0) and np.all(cap["w"][sel] >= -1e-12)
    assert np.array_equal(cap["w"][sel], cap["w_clip"][sel])
    # 결정적(두 번 같은 노드) · 다른 묶음(band·snap)은 끔과 같음
    cap2 = _cap(world, S)
    assert np.array_equal(cap2["idx"], cap["idx"]) and np.array_equal(cap2["w"], cap["w"])
    keep = cap["via"] != gm.VIA_FORCE
    assert np.array_equal(cap["idx"][keep], c0["idx"]) and np.array_equal(cap["w"][keep], c0["w"])
    with capsys.disabled():
        print(f"\nGRIDFORCE holes q{q}: n {got.size} dist {c['dist']:.3f} shift {c['shift']:.3f} "
              f"area {c['area_s']:.1f}/{c['area_a']:.1f}")


def test_v0252_12_limit_and_normal(world):
    S = G.holes(G.plate(3.0, node_base=900001), [1])
    c1 = _cap(world, S, force={**FORCE, "max_dist_mm": 1.0})                   # 한도 = max(1, r_snap) < 4 mm → 못 붙임
    assert sum(c["miss"] for c in c1["clusters"]) == 1 and c1["force_limit"] == pytest.approx(0.75 * 5.0)
    c2 = _cap(world, S, force={**FORCE, "max_dist_mm": 50.0})
    assert sum(c["via"] == "force" for c in c2["clusters"]) == 1
    c3 = _cap(world, S, force={**FORCE, "normal_deg": 30.0})                   # 평판 — 법선 맞음(같은 결과)
    assert np.array_equal(c3["idx"], _cap(world, S)["idx"])
    c4 = _cap(world, S, force={**FORCE, "enabled": False})                     # 끔 = 못 붙임
    assert sum(c["miss"] for c in c4["clusters"]) == 1


# ------------------------------------------------------------------ V-0252-13 스프링 강성 합 보존
def test_v0252_13_spring_sum_preserved(world, capsys):
    S = G.holes(G.plate(3.0, node_base=900001), [1, 4])
    res, _i, grp = _run(world, S, CFG_F)
    assert res["methods"]["jig_spring"]["status"] == "ok", res["methods"]["jig_spring"]
    cap = _cap(world, S)
    BC = res["bc"]["jig_spring"]
    q_of = cap["q"][np.searchsorted(cap["idx"], BC["sp_node"])]
    kq = grp["spring"]["jig_spring"][1]
    got = np.bincount(q_of, weights=BC["sp_k"], minlength=kq.size)
    rel = np.abs(got / kq - 1.0)
    fq = sorted({int(q) for q in cap["q"][cap["via"] == gm.VIA_FORCE]})
    assert len(fq) == 2 and rel.max() <= 1e-12, rel
    case_total = float(np.sum(world["cjs"][0]["jig_spring"][0]["sp_k"]))
    assert float(BC["sp_k"].sum()) == pytest.approx(case_total, rel=1e-12)
    with capsys.disabled():
        print(f"\nGRIDFORCE spring Σk/K_q−1 max {rel.max():.2e} (강제 묶음 {fq}) total {BC['sp_k'].sum():.6g} = case {case_total:.6g}")


# ------------------------------------------------------------------ V-0252-14 합력·모멘트 보존(물리)
def _solve(world, S, m, cfg):
    """run_shape 와 같은 조립(capture → shape_bcs → factorize → respond)으로 반력 R (N,3)·하중 F·C_mix."""
    grp = world["grp"]
    cap = gm.capture(grp["skel"], S, S["x0"], np.eye(3), capture_rel=0.25, snap_rel=0.75, normal_deg=30.0,
                     force=cfg.get("tie_force"))
    p = {**TG.PARAMS, "sample_nbr": 1, "sample_normal_deg": 45.0}
    bcs = gm.shape_bcs(S, G.sup321(S), cap, grp["skel"], grp["field"], grp["GF"], np.eye(3), S["x0"], methods=[m],
                       entries=["E0"], params=p, kink_deg=45.0, dup_deg=10.0, spring=grp["spring"])
    (_sha, items), = bcs["groups"].items()
    BC = items[0][2]
    L, info = G.shape_loads(world["A"], S, world["Fs"], 3.0, h=3.0)
    F = L[0][1]
    h = jig_bc.factorize(gm._shell(S, G.SOLVER), BC)
    r = jig_bc.respond(h, F, BC)
    R = np.asarray(r["R"], dtype=np.float64)[:, :3].copy()          # 구속 반력 + 스프링 힘(f_s·d̂ — 구조에 걸리는 지지력)
    fs = np.asarray(r["fs"], dtype=np.float64).reshape(-1)
    if fs.size:
        np.add.at(R, np.asarray(BC["sp_node"], dtype=np.int64), fs[:, None] * np.asarray(BC["sp_dir"], dtype=np.float64))
    return {"R": R, "F": np.asarray(F, dtype=np.float64), "cap": cap,
            "C_mix": float(r["energy"]["C_mix"]), "X": np.asarray(S["x0"], dtype=np.float64)}


@pytest.mark.parametrize("m", ["prescribed", "spring"])
def test_v0252_14_force_moment_conservation(world, m, capsys):
    base = G.plate(3.0, node_base=900001)
    r0 = _solve(world, base, m, CFG_F)
    assert r0["cap"]["via"].tolist().count(gm.VIA_FORCE) == 0
    ctr = r0["X"].mean(axis=0)
    rows = []
    for delta in (3.0, 8.0):
        # 체결부 면을 snap 한도(0.75·5 mm) + 요소 1개(3 mm) + δ 밖으로(모든 볼트 — 구멍 둘레 노드가 강제 자리)
        S = G.holes(base, list(range(len(G.BOLTS))), r=G.R_WASHER + 0.75 * 5.0 + 3.0 + delta)
        r = _solve(world, S, m, CFG_F)
        cap = r["cap"]
        assert sum(c["via"] == "force" for c in cap["clusters"]) == len(G.BOLTS)
        F, R, X = r["F"], r["R"], r["X"]
        sF = float(np.linalg.norm(F, axis=1).sum())
        Lb = float(np.linalg.norm(X.max(0) - X.min(0)))
        tot = F + R
        e_f = float(np.linalg.norm(tot.sum(0))) / sF
        e_m = float(np.linalg.norm(np.cross(X - ctr, tot).sum(0))) / (sF * Lb)
        assert e_f <= 1e-9 and e_m <= 1e-9, (e_f, e_m)                           # ① 전체 평형
        R0s, Rs = r0["R"].sum(0), R.sum(0)
        # 맞춤 하중이 자기평형(ΣF ≈ 0)이라 합력 자체가 0 근처 — 차이를 반력 크기 합 Σ‖R_n‖(옮기지 않은 형상)로 나눔(TM-C1-3)
        dR = float(np.linalg.norm(Rs - R0s) / np.linalg.norm(r0["R"], axis=1).sum())
        assert dR <= 0.01, dR                                                    # ② 반력 합력 차 ≤ 1 %
        M0 = np.cross(r0["X"] - ctr, r0["R"]).sum(0)
        M1 = np.cross(X - ctr, R).sum(0)
        dq = {c["q"]: c["dist"] for c in cap["clusters"]}
        bound = 0.0
        for q, d in dq.items():
            nn = cap["idx"][cap["q"] == q]
            bound += float(np.linalg.norm(R[nn].sum(0))) * d
        dM = float(np.linalg.norm(M1 - M0))
        assert dM <= bound + 0.01 * float(np.linalg.norm(M0)), (dM, bound)      # ③ 모멘트 차 ≤ Σ|R_q|·δ_q + 1 %
        rows.append((delta, e_f, e_m, dR, dM, bound, r["C_mix"] / r0["C_mix"] - 1.0,
                     min(dq.values()), max(dq.values())))
    with capsys.disabled():
        for x in rows:
            print(f"\nGRIDFORCE phys {m} δ {x[0]:g}: 평형 F {x[1]:.1e} M {x[2]:.1e} · ΔΣR {x[3]:.1e} · ΔM {x[4]:.3g} ≤ "
                  f"{x[5]:.3g} · ΔC_mix {x[6] * 100:+.2f} % · dist {x[7]:.2f}~{x[8]:.2f} mm")


# ------------------------------------------------------------------ V-0252-15 거리 무관(좌표 통째 어긋남)
@pytest.mark.parametrize("delta", [50.0, 200.0])
def test_v0252_15_distance_independent(world, delta, capsys):
    S = G.plate(3.0, node_base=900001)
    Xs = np.asarray(S["x0"], dtype=np.float64) + np.array([0.0, delta, 0.0])   # 판 법선으로 δ(좌표 어긋남)
    res, _i, grp = _run(world, S, CFG_F, Xs=Xs)
    t = res["map"]["tie"]
    nq = grp["skel"]["n_q"]
    assert t["n_force"] == nq and t["n_miss"] == 0 and t["n_far"] == nq and t["ref"] is True
    assert all(m["status"] == "ok" for m in res["methods"].values()), res["methods"]   # 형상이 순위에 들어감
    f = t["force"]
    hb = np.hypot(delta, 2.0 * 3.0)                                            # 면적 채움 노드 = 판 위 골격 둘레(면내 ≤ 2 h)
    assert delta - 1e-9 <= f["dist_min_mm"] <= f["dist_max_mm"] <= hb
    assert f["limit_mm"] is None and len(t["marks"]) == nq and all(mk["far"] and mk["via"] == "force" for mk in t["marks"])
    for mk in t["marks"]:                                                       # 선 = 형상 좌표: Case 자리 x → 붙인 곳 to
        assert np.linalg.norm(np.subtract(mk["to"], mk["x"])) == pytest.approx(delta, rel=0.05)
    w = stg._jg_force_warns("d001", t, CFG_STG)
    codes = [x.split(":", 1)[0] for x in w]
    assert codes == ["JIG_GRID_TIE_FORCED", "JIG_GRID_TIE_FAR"]
    assert f"{nq}/{nq}곳(100 %)" in w[0] and "지그 순위는 참고용입니다" in w[0] and "10 mm 넘는 곳 6곳" in w[0]
    assert "먼 순 상위 5곳" in w[1] and w[1].count(",") == 4
    # 관리자 한도 20 mm → 전부 못 붙임 → 비율 > tie_miss_frac_max = 형상 제외(코드 JIG_GRID_TIE_MISS)
    cfg20 = {**CFG_F, "tie_force": {**FORCE, "max_dist_mm": 20.0}}
    r2, _i, _g = _run(world, S, cfg20, Xs=Xs)
    t2 = r2["map"]["tie"]
    assert t2["n_miss"] == nq and t2["n_force"] == 0 and t2["force"]["limit_mm"] == 20.0
    assert all(m["status"] == "failed" and m["code"] == "JIG_GRID_TIE_MISS" for m in r2["methods"].values())
    w2 = stg._jg_force_warns("d001", t2, {**CFG_STG, "tie_force": cfg20["tie_force"]})
    assert [x.split(":", 1)[0] for x in w2] == ["JIG_GRID_TIE_UNPLACED"]
    assert "(거리 한도 20 mm)" in w2[0] and "순위에서 빠집니다" in w2[0] and all(mk["via"] == "miss" for mk in t2["marks"])
    with capsys.disabled():
        print(f"\nGRIDFORCE far δ {delta:g}: force {t['n_force']}/{nq} dist {f['dist_min_mm']:.3f}~{f['dist_max_mm']:.3f} "
              f"shift {f['shift_max_mm']:.3f}")


# ------------------------------------------------------------------ V-0252-16 참고용 판정 · 표시 임계 해시 밖
def test_v0252_16_ref_rule(world):
    S = G.holes(G.plate(3.0, node_base=900001), [1])                           # 1/6 강제(17 % > 10 %) · 거리 ≈ 4 mm
    t = _run(world, S, CFG_F)[0]["map"]["tie"]
    assert t["n_force"] == 1 and t["n_far"] == 0 and t["ref"] is True
    w = stg._jg_force_warns("d001", t, CFG_STG)
    assert w[0].endswith(" — 지그 순위는 참고용입니다") and len(w) == 1
    c2 = {**CFG_F, "tie_miss_frac_max": 0.5}                                    # 비율 아래 · 먼 강제 없음 = 참고용 아님
    t2 = _run(world, S, c2)[0]["map"]["tie"]
    assert t2["ref"] is False and not stg._jg_force_warns("d001", t2, {**CFG_STG, **c2})[0].endswith("참고용입니다")
    c3 = {**c2, "tie_force_far_warn_mm": 2.0}                                   # 먼 강제 ≥ 1 = 참고용
    r3 = _run(world, S, c3)[0]
    assert r3["map"]["tie"]["n_far"] == 1 and r3["map"]["tie"]["ref"] is True
    assert _rows(r3) == _rows(_run(world, S, c2)[0])                            # 표시 임계 = 계산 불변
    raw = {**DEFAULTS["rank"]["jig_grid"]}
    assert gm.hash_view({**raw, "tie_force_far_warn_mm": 2.0}) == gm.hash_view(raw)


# ------------------------------------------------------------------ V-0252-17 설정 · 해시
@pytest.mark.parametrize("tf", [{"enabled": 1}, {"max_dist_mm": 0.0}, {"max_dist_mm": -3.0}, {"normal_deg": 0.0},
                                {"normal_deg": 91.0}, {"max_dist_mm": "x"}, {"bogus": 1}])
def test_v0252_17_tie_force_ranges(tf):
    with pytest.raises(EslError) as ei:
        check_tie_force(tf)
    assert ei.value.code == "CONFIG_INVALID"
    with pytest.raises(EslError):
        settings({"bead_doe": {"rank": {"jig_grid": {"tie_force": tf}}}})
    g = {**copy.deepcopy(DEFAULTS["rank"]["jig_grid"]), "tie_force": {**FORCE, **tf}}
    with pytest.raises(EslError) as ei:
        stg._jg_cfg(_ctx(g))
    assert ei.value.code == "CONFIG_INVALID"


def _ctx(grid):
    d = {"id": "P", "scenario": "compare", "cfg": copy.deepcopy(G.CFG_FULL), "entries": [], "rank": G.rank_snap(grid=grid),
         "load_transfer": dict(G.LT)}
    return stg.Ctx({"stage": "bd_post", "out": "/tmp/_jg_force_unused", "doe": d})


def test_v0252_17_defaults_snapshot_and_hash():
    assert DEFAULTS["rank"]["jig_grid"]["tie_force"] == {"enabled": True, "max_dist_mm": None, "normal_deg": 90.0}
    assert DEFAULTS["rank"]["jig_grid"]["tie_force_far_warn_mm"] == 10.0 and "tie_force_far_warn_mm" in gm.HASH_EXCLUDE
    assert DEFAULTS["view3d"]["jig_force_marks_max"] == 512
    assert check_tie_force({"max_dist_mm": 20}) == {"enabled": True, "max_dist_mm": 20.0, "normal_deg": 90.0}
    assert check_tie_force({}) == DEFAULTS["rank"]["jig_grid"]["tie_force"]               # null 허용(기본)
    # 옛 스냅샷(tie_force 키 없음) = 끔(DEFAULTS 에서 채우지 않음), 새 스냅샷 = 그 값
    old = G.rank_snap(grid=True)["jig_grid"]
    assert "tie_force" not in old
    assert stg._jg_cfg(_ctx(old))["tie_force"] is None and not stg._jg_force_on(_ctx(old))
    new = G.rank_snap(grid=True, force=True)["jig_grid"]
    assert stg._jg_cfg(_ctx(new))["tie_force"] == FORCE and stg._jg_force_on(_ctx(new))
    # 해시 = 키 있으면 포함, max_dist_mm null ↔ 값 = 바뀜, 표시 임계 = 불변
    h_old, h_new = gm.hash_view(old), gm.hash_view(new)
    assert h_old != h_new and "tie_force" in h_new and "tie_force_far_warn_mm" not in h_new
    assert gm.hash_view({**new, "tie_force": {**FORCE, "max_dist_mm": 20.0}}) != h_new
    assert gm.hash_view({**new, "tie_force_far_warn_mm": 25.0}) == h_new
    assert settings({"bead_doe": {"rank": {"jig_grid": {"tie_force": {"max_dist_mm": 15}}}}})["rank"]["jig_grid"][
        "tie_force"]["max_dist_mm"] == 15.0
    with pytest.raises(EslError):
        settings({"bead_doe": {"rank": {"jig_grid": {"tie_force_far_warn_mm": 0}}}})
    with pytest.raises(EslError):
        settings({"bead_doe": {"view3d": {"jig_force_marks_max": 0}}})


def test_v0252_marks_truncated(world):
    S = G.plate(3.0, node_base=900001)
    Xs = np.asarray(S["x0"], dtype=np.float64) + np.array([0.0, 30.0, 0.0])
    res = TG._run(world["A"], S, world["us"], world["Fs"], world["cjs"], M2, cfg=CFG_F, grp=world["grp"], Xs=Xs)[0]
    full = res["map"]["tie"]["marks"]
    cap = _cap(world, S, Xs=Xs)
    d = gm.force_diag(cap, world["grp"]["skel"], Xs, S["x0"], np.eye(3), far_mm=10.0, frac_max=0.1, marks_max=2)
    assert d["marks_truncated"] is True and len(d["marks"]) == 2
    top2 = sorted(full, key=lambda m: (-m["dist"], m["q"]))[:2]
    assert [m["q"] for m in d["marks"]] == sorted(m["q"] for m in top2)
    assert "marks_truncated" not in res["map"]["tie"]
