"""V-OR-5: 초기 컴플라이언스(분해 1회) + 하중 선정 전략 A/B/C, 결정성, C ≤ 0 제외, 목표 기준 POS."""
import numpy as np
import pytest

import synth_opt as so
from esl.errors import EslError
from esl.mech.shell import ShellModel
from esl.opt import select as sl
from esl.opt import settings

LC = settings()["loads"]


# ---------------------------------------------------------------- 초기 컴플라이언스
@pytest.fixture(scope="module")
def plate_case():
    m = so.plate(16, 10, Lx=320, Lz=200)
    sup = so.supports_321(m)
    t = so.s1_target(m, sup)
    loads = {"Eb": so.load(m, "bend"), "Et": so.load(m, "twist", amp=2.0), "Er": so.load(m, "rand", seed=2)}
    return m, sup, t, loads


def test_compliance_matches_independent_solve_and_one_factorization(plate_case, tmp_path):
    m, sup, t, loads = plate_case
    ids = sorted(loads)
    res = sl.initial_compliance(t, ids, loads.__getitem__, {"drill_factor": 1e-4, "backend": "superlu"},
                                u_store=str(tmp_path / "u_cand.npy"))
    assert res["stats"]["n_factorizations"] == 1 and res["stats"]["n_solves"] == 3
    assert isinstance(res["U"], np.memmap) and res["U"].shape == (3, 3 * m["node_id"].size)
    for k, e in enumerate(ids):
        sm = ShellModel(m["x0"], m["conn"], m["elem_type"], m["thickness"], m["E"], m["nu"], backend="superlu")
        spc = [(int(np.searchsorted(m["node_id"], n)), d) for n, d in sup]
        u, _ = sm.solve(loads[e], spc)
        C = float(np.sum(loads[e] * u[:, :3]))
        um = float(np.max(np.linalg.norm(u[:, :3], axis=1)))
        assert abs(res["C"][k] - C) <= 1e-9 * abs(C)
        assert abs(res["umax"][k] - um) <= 1e-9 * um


def test_run_end_to_end_merges_sign_flip(plate_case):
    m, sup, t, loads = plate_case
    L = dict(loads)
    L["Eneg"] = -loads["Eb"]                 # 반대 방향 = 같은 C, |MAC| = 1
    L["E2x"] = 2.0 * loads["Et"]             # 같은 형상, 큰 하중 → 이쪽이 남음
    cands = [{"entry_id": e, "mode": None, "scene": e} for e in sorted(L)]
    sel, forces, info = sl.run(t, cands, L.__getitem__, strategy="A", objective_norm="abs", k=None,
                               cfg=so.cfg(), sources_ref="opt_method_sources/x")
    st = {r["entry_id"]: r for r in sel["rows"]}
    assert st["Et"]["status"] == "merged" and st["Et"]["merged_into"] == "E2x" and st["Et"]["sign"] == 1
    neg = [st["Eb"], st["Eneg"]]
    kept = [r for r in neg if r["status"] == "included"]
    merged = [r for r in neg if r["status"] == "merged"]
    assert len(kept) == 1 and len(merged) == 1 and merged[0]["sign"] == -1
    assert merged[0]["entry_id"] == "Eneg" and kept[0]["entry_id"] == "Eb"     # C 동률 → entry_id 사전순
    assert set(forces) == {r["entry_id"] for r in sel["rows"] if r["label"]}
    assert info["stats"]["n_factorizations"] == 1
    assert sel["sources_ref"] == "opt_method_sources/x"


# ---------------------------------------------------------------- 합성 U 로 규칙 시험
def unit(n, i):
    v = np.zeros(n)
    v[i] = 1.0
    return v


def cands_U(vecs, Cs, modes=None):
    ids = [f"E{k:03d}" for k in range(len(vecs))]
    U = np.asarray(vecs, dtype=np.float32)
    cands = [{"entry_id": e, "C0": float(c), "umax": 1.0, "mode": (modes[k] if modes else None), "scene": f"s{k}"}
             for k, (e, c) in enumerate(zip(ids, Cs))]
    return cands, U, {e: k for k, e in enumerate(ids)}


@pytest.mark.parametrize("delta,merged", [(+1e-4, True), (-1e-4, False)])
def test_A_mac_boundary(delta, merged):
    c2 = 0.95 + delta                                   # cos²θ = mac
    v1 = unit(4, 0)
    v2 = np.sqrt(c2) * unit(4, 0) + np.sqrt(1 - c2) * unit(4, 1)
    cands, U, rows = cands_U([v1, v2], [2.0, 1.0])
    s = sl.select(cands, "A", loads_cfg=LC, U=U, u_rows=rows)
    r = {x["entry_id"]: x for x in s["rows"]}
    assert (r["E001"]["status"] == "merged") is merged
    if merged:
        assert abs(r["E001"]["mac_to_target"] - c2) < 1e-6 and r["E001"]["merged_into"] == "E000"


def test_A_cluster_threshold_25_vs_19():
    rng = np.random.default_rng(0)
    for n, want_cluster in ((25, True), (19, False)):
        V = rng.normal(size=(n, 400))
        cands, U, rows = cands_U(V, np.linspace(10, 1, n))
        s = sl.select(cands, "A", loads_cfg=LC, U=U, u_rows=rows)
        st = [r["status"] for r in s["rows"]]
        if want_cluster:
            assert s["n_cases"] <= 20 and st.count("cluster_rep") == s["n_cases"] and "clustered" in st
            assert len(s["clusters"]) == s["n_cases"]
            reps = [c["rep_entry_id"] for c in s["clusters"]]
            Cs = {c["entry_id"]: c["C0"] for c in cands}
            assert [Cs[x] for x in reps] == sorted((Cs[x] for x in reps), reverse=True)   # 대표 C 내림차순 번호
            for c in s["clusters"]:                                           # 대표 = 군집 내 C 최대
                assert Cs[c["rep_entry_id"]] == max(Cs[x] for x in c["members"])
        else:
            assert st == ["included"] * n and s["clusters"] == [] and s["n_cases"] == 19


def test_B_modes():
    rng = np.random.default_rng(1)
    V = rng.normal(size=(5, 10))
    modes = ["bend", "bend", "twist", None, "twist"]
    cands, U, rows = cands_U(V, [5, 4, 3, 2, 1], modes)
    s = sl.select(cands, "B", loads_cfg=LC)
    st = {r["entry_id"]: r["status"] for r in s["rows"]}
    assert st == {"E000": "mode_rep", "E001": "not_selected", "E002": "mode_rep", "E003": "not_selected",
                  "E004": "not_selected"}
    assert s["excluded_modes"] == ["dent"] and s["n_cases"] == 2
    assert all(r["mac_to_target"] is None for r in s["rows"])
    cands[4]["mode"] = "dent"                                 # 모드 수정 반영
    s2 = sl.select(cands, "B", loads_cfg=LC)
    assert s2["n_cases"] == 3 and s2["excluded_modes"] == []
    for c in cands:
        c["mode"] = None
    with pytest.raises(EslError) as ei:
        sl.select(cands, "B", loads_cfg=LC)
    assert ei.value.code == "NO_MODE_CANDIDATES"


def test_C_k_values_and_range():
    rng = np.random.default_rng(2)
    V = rng.normal(size=(7, 50))
    cands, U, rows = cands_U(V, np.arange(7, 0, -1))
    assert sl.select(cands, "C", loads_cfg=LC, k=1, U=U, u_rows=rows)["n_cases"] == 1
    s5 = sl.select(cands, "C", loads_cfg=LC, k=5, U=U, u_rows=rows)
    assert s5["n_cases"] <= 5 and s5["k"] == 5 and s5["mac_merge"] is None
    s20 = sl.select(cands, "C", loads_cfg=LC, k=20, U=U, u_rows=rows)
    assert s20["n_cases"] == 7                                 # 후보 수 초과 → 후보 수
    for bad in (0, 21, None, True, 2.5):
        with pytest.raises(EslError) as ei:
            sl.select(cands, "C", loads_cfg=LC, k=bad, U=U, u_rows=rows)
        assert ei.value.code == "INVALID_PARAMS"
    with pytest.raises(EslError):
        sl.select(cands, "D", loads_cfg=LC)
    with pytest.raises(EslError) as ei:
        sl.select(cands, "A", loads_cfg=LC, objective_norm="max", U=U, u_rows=rows)
    assert ei.value.code == "INVALID_PARAMS"


@pytest.mark.parametrize("strategy,k", [("A", None), ("B", None), ("C", 4)])
def test_deterministic_under_shuffle(strategy, k):
    rng = np.random.default_rng(3)
    n = 30
    base = rng.normal(size=(6, 200))
    V = np.array([base[i % 6] * (1 + 0.01 * i) + 0.05 * rng.normal(size=200) * (i % 2) for i in range(n)])
    V[7] = -V[1]
    Cs = np.round(rng.uniform(1, 10, n), 1)
    Cs[3] = Cs[4]                                              # C 동률
    md = [("bend", "twist", "dent", None)[i % 4] for i in range(n)]
    cands, U, rows = cands_U(V, Cs, md)
    ref = sl.selection_bytes(sl.select(cands, strategy, loads_cfg=LC, k=k, U=U, u_rows=rows))
    for rep in range(10):
        p = np.random.default_rng(100 + rep).permutation(n)
        cs = [cands[i] for i in p]
        Up = U[p]
        rw = {cands[i]["entry_id"]: j for j, i in enumerate(p)}
        got = sl.selection_bytes(sl.select(cs, strategy, loads_cfg=LC, k=k, U=Up, u_rows=rw))
        assert got == ref


def test_A_C_ignore_modes():
    rng = np.random.default_rng(4)
    V = rng.normal(size=(8, 30))
    cands, U, rows = cands_U(V, np.arange(8, 0, -1), ["bend"] * 8)
    for strat, k in (("A", None), ("C", 3)):
        a = sl.select(cands, strat, loads_cfg=LC, k=k, U=U, u_rows=rows)
        c2 = [{**c, "mode": "twist"} for c in cands]
        b = sl.select(c2, strat, loads_cfg=LC, k=k, U=U, u_rows=rows)
        strip = lambda s: [{kk: v for kk, v in r.items() if kk != "mode"} for r in s["rows"]]   # noqa: E731
        assert strip(a) == strip(b)


def test_nonpositive_C_and_objective_pos():
    V = np.eye(4)
    cands, U, rows = cands_U(V, [10.0, 0.0, 3.0, -1.0])
    s = sl.select(cands, "A", loads_cfg=LC, U=U, u_rows=rows, objective_norm="abs")
    st = {r["entry_id"]: r for r in s["rows"]}
    assert st["E001"]["status"] == "not_selected" and st["E001"]["note"] == "C0<=0" and len(s["warnings"]) == 2
    assert s["C_ref"] == 10.0 and st["E000"]["pos"] == 10.0 and st["E002"]["pos"] == 10.0
    assert st["E000"]["label"] == "L01" and st["E002"]["label"] == "L02"
    r = sl.select(cands, "A", loads_cfg=LC, U=U, u_rows=rows, objective_norm="rel")
    st = {x["entry_id"]: x for x in r["rows"]}
    assert st["E000"]["pos"] == 10.0 and st["E002"]["pos"] == 3.0
    zero, U0, rows0 = cands_U(np.eye(2), [0.0, -2.0])
    with pytest.raises(EslError) as ei:
        sl.select(zero, "A", loads_cfg=LC, U=U0, u_rows=rows0)
    assert ei.value.code == "NO_LOAD_CASES"


def test_C_ref_after_merge_is_max_selected():
    """C_ref = 선정(병합·군집 후) 케이스 C⁰ 최대 — 10배 차 2하중 abs 는 POS 같음, rel 은 각자."""
    v = np.eye(3)
    cands, U, rows = cands_U([v[0], v[1], 0.999 * v[0] + 0.01 * v[2]], [100.0, 10.0, 50.0])
    s = sl.select(cands, "A", loads_cfg=LC, U=U, u_rows=rows)
    sel = [r for r in s["rows"] if r["label"]]
    assert [r["entry_id"] for r in sel] == ["E000", "E001"] and {r["pos"] for r in sel} == {100.0}
    r = sl.select(cands, "A", loads_cfg=LC, U=U, u_rows=rows, objective_norm="rel")
    assert [x["pos"] for x in r["rows"] if x["label"]] == [100.0, 10.0]
