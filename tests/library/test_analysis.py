"""P2 §3·§8 분석 단위 시험: 정규화 계수, k-medoids 재현성, SVD 모드 수, 대상 없는 격자 분석·포락·최악 케이스."""
import numpy as np
import pytest

import synth_lib
from esl.errors import EslError
from esl.library import analysis as an
from esl.library import normalization as nm
from esl.library import normalize as nz
from esl.library.entry import LibraryEntry


def test_normalization_modes():
    F = np.ones((4, 3))
    meta = {"source": {"mass": 10.0, "inch": 50}, "target": {"mass": 15.0, "inch": 60}}
    assert nm.scale(F, "none", None)[1] == 1.0
    G, k = nm.scale(F, "mass", meta)
    assert k == pytest.approx(1.5) and np.allclose(G, 1.5)
    assert nm.scale(F, "inch2", meta)[1] == pytest.approx(1.44)
    with pytest.raises(EslError) as e:
        nm.scale(F, "mass", {"source": {"mass": None}, "target": {"mass": 1.0}})
    assert e.value.code == "NORMALIZATION_META_MISSING"
    with pytest.raises(EslError):
        nm.scale(F, "inch3", meta)


def test_kmedoids_reproducible_and_optimal():
    rng = np.random.default_rng(0)
    pts = np.concatenate([rng.normal([0, 0], 0.3, (12, 2)), rng.normal([5, 0], 0.3, (9, 2)),
                          rng.normal([0, 6], 0.3, (7, 2))])
    D = an.distance_matrix(pts)
    m1, l1, c1 = an.kmedoids(D, 3, seed=7)
    m2, l2, c2 = an.kmedoids(D, 3, seed=7)
    assert m1 == m2 and np.array_equal(l1, l2) and c1 == c2
    assert sorted(np.bincount(l1).tolist()) == [7, 9, 12]
    # 각 medoid 는 자기 클러스터 안에서 비용 최소(실제 점 = 실제 씬)
    for ci, m in enumerate(m1):
        mem = np.flatnonzero(l1 == ci)
        assert D[mem][:, m].sum() == pytest.approx(D[mem][:, mem].sum(axis=0).min())
    # k > K 는 K 로 잘림
    m3, l3, _ = an.kmedoids(D[:2, :2], 5)
    assert m3 == [0, 1]


def _entry(eid, pattern, nx, ny, scale, amp, drop, inch, grid=(8, 6), verdict="PASS"):
    X0, conn, et, _ = synth_lib.plate_xz(nx, ny, scale)
    fr = nz.frame(X0, None, conn, et)
    f = amp * synth_lib.pattern_load(X0, conn, et, pattern, fr)
    gs = nz.grid_summary(X0, f, grid[0], grid[1], fr)
    meta = {"entry_id": eid, "mesh_sha256": f"m{nx}x{ny}s{scale}", "frame": fr, "grid": {"nx": grid[0], "ny": grid[1]},
            "model": {"product": f"{inch}X", "inch": inch, "mass": {"value": 10.0 * scale ** 2}},
            "scene": {"drop_type": drop, "drop_class": drop, "orient": "3", "scene": 1, "scenario": "FREE"},
            "quality": {"verdict": verdict, "hotspot1_rel_err": 0.01}, "summary": {"sum_abs_f": float(
                np.linalg.norm(f, axis=1).sum())}}
    raw = {"node_id": np.arange(X0.shape[0]), "x0": X0, "conn": conn, "elem_type": et, "f": f}
    return LibraryEntry(meta=meta, summary=gs, raw=raw)


@pytest.fixture(scope="module")
def entries():
    return [_entry("a1", "A", 24, 16, 1.0, 1.0, "Corner", 50), _entry("a2", "A", 36, 24, 1.2, 2.0, "Corner", 60),
            _entry("b1", "B", 30, 20, 1.0, 1.0, "Edge", 50), _entry("b2", "B", 24, 16, 1.2, 0.5, "Face", 60),
            _entry("a3", "A", 30, 20, 1.0, 1.5, "Edge", 50)]


def test_run_without_target_groups_patterns(entries):
    res, arr = an.run(entries, None, {"n_representative": 2, "svd_energy": 0.95})
    lab = {c["entry_id"]: c["cluster"] for c in res["cases"]}
    assert lab["a1"] == lab["a2"] == lab["a3"] != lab["b1"] == lab["b2"]
    assert {lc["role"] for lc in res["load_cases"]} == {"medoid"} and len(res["load_cases"]) == 2
    cum = np.asarray(res["svd"]["cum_energy"])
    r = res["svd"]["n_modes"]
    assert cum[r - 1] >= 0.95 and (r == 1 or cum[r - 2] < 0.95)
    # 포락 = 케이스별 셀 |F| 의 최대
    G = arr["cell_F_loc"]
    assert np.allclose(arr["env_mag"], np.linalg.norm(G, axis=3).max(axis=0))
    assert res["stats"]["groups"]["drop_class"]["Corner"]["n"] == 2
    assert res["mapping"] is None and res["target"] is None


def test_run_with_target_self_and_worst(entries):
    tgt = entries[0]
    res, arr = an.run(entries, tgt, {"n_representative": 2, "worst_case": True, "normalization": "mass"})
    c0 = res["cases"][0]
    assert c0["self"] is True and c0["scale_factor"] == 1.0
    assert np.allclose(arr["mapped_F"][0], tgt.raw["f"])                          # 대상 자체 = 원본 그대로
    assert res["cases"][1]["scale_factor"] == pytest.approx(1 / 1.44)              # mass 정규화
    assert res["mapping"]["conservation_rel_max"] < 1e-10
    worst = [lc for lc in res["load_cases"] if lc["role"] == "worst"]
    for lc in worst:
        cl = res["clusters"][lc["cluster"]]
        sums = [res["cases"][m]["sum_abs_f"] for m in cl["members"]]
        assert res["cases"][lc["case_index"]]["sum_abs_f"] == max(sums)
    lab = {c["entry_id"]: c["cluster"] for c in res["cases"]}
    assert lab["a1"] == lab["a2"] == lab["a3"] != lab["b1"] == lab["b2"]
    assert arr["outline"].shape[1:] == (2, 2) and arr["mapped_F"].shape == (5, tgt.raw["x0"].shape[0], 3)


def test_run_errors(entries):
    with pytest.raises(EslError):
        an.run([], None)
    other = _entry("g", "A", 20, 12, 1.0, 1.0, "Face", 50, grid=(6, 4))
    with pytest.raises(EslError) as e:
        an.run(entries[:2] + [other], None)
    assert e.value.code == "GRID_MISMATCH"
