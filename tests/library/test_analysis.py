"""P2 §3·§8 분석 단위 시험: 정규화 계수, k-medoids 재현성, SVD 모드 수, 대상 없는 격자 분석·포락·최악 케이스."""
import json
import re

import numpy as np
import pytest

import synth_lib
from esl.errors import EslError
from esl.library import analysis as an
from esl.library import normalization as nm
from esl.library import normalize as nz
from esl.library import report_analysis as ra
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
    Fs = an.load_case_forces(res, arr)
    for lc, f in zip(res["load_cases"], Fs):                                      # 대상 자체 = 원본 그대로
        if lc["case_index"] == 0:
            assert np.allclose(f, tgt.raw["f"])
    assert res["cases"][1]["scale_factor"] == pytest.approx(1 / 1.44)              # mass 정규화
    assert res["mapping"]["conservation_rel_max"] < 1e-10
    worst = [lc for lc in res["load_cases"] if lc["role"] == "worst"]
    for lc in worst:
        cl = res["clusters"][lc["cluster"]]
        sums = [res["cases"][m]["sum_abs_f"] for m in cl["members"]]
        assert res["cases"][lc["case_index"]]["sum_abs_f"] == max(sums)
    lab = {c["entry_id"]: c["cluster"] for c in res["cases"]}
    assert lab["a1"] == lab["a2"] == lab["a3"] != lab["b1"] == lab["b2"]
    # 덱 기본 all(§12.1): mapped_F = 모든 씬(덱 순서 = 씬 순서)
    assert res["deck"]["mode"] == "all" and not res["deck"]["reduced"] and res["deck"]["n_subcases"] == 5
    assert arr["outline"].shape[1:] == (2, 2) and arr["mapped_F"].shape == (5, tgt.raw["x0"].shape[0], 3)
    assert arr["load_case_index"].tolist() == [0, 1, 2, 3, 4]


def test_saved_loads_only_representative_and_worst(entries):
    """cases=representative+worst: mapped_loads 는 대표+최악 케이스만; 포락·Σ|f| 는 전 케이스 스트리밍 결과와 일치."""
    tgt = entries[0]
    opts = {"n_representative": 1, "worst_case": True, "deck_cases": "representative+worst"}
    res, arr = an.run(entries, tgt, opts)
    roles = [lc["role"] for lc in res["load_cases"]]
    assert roles == ["medoid", "worst"]
    assert arr["mapped_F"].shape[0] == len(res["load_cases"]) == 2 < res["n_cases"]
    assert arr["load_case_index"].tolist() == [lc["case_index"] for lc in res["load_cases"]]
    assert arr["load_case_entry_id"].tolist() == [lc["entry_id"] for lc in res["load_cases"]]
    o = dict(an.DEFAULT_OPTS, **opts)
    mo = {"moment_scale": o["moment_scale"], "equilibrate": o["equilibrate"]}
    tx = np.asarray(tgt.raw["x0"], dtype=np.float64)
    full = np.stack([an._target_case_force(e, tgt, tx, tgt.meta["frame"], 1.0, mo)[0] for e in entries])
    mag = np.linalg.norm(full, axis=2)
    assert np.allclose(arr["node_env_mag"], mag.max(axis=0))
    assert np.array_equal(arr["node_env_case"], np.argmax(mag, axis=0))
    assert np.allclose([c["sum_abs_f"] for c in res["cases"]], mag.sum(axis=1))
    for lc, f in zip(res["load_cases"], an.load_case_forces(res, arr)):
        assert np.allclose(f, full[lc["case_index"]])
    bad = {k: v for k, v in arr.items() if k != "load_case_index"}
    with pytest.raises(EslError):
        an.load_case_forces(res, bad)
    assert [x["label"] for x in res["deck"]["cases"]] == ["REP1", "WORST1"]
    assert len(res["deck"]["excluded"]) == 3 and not res["deck"]["reduced"]


def test_deck_all_default_and_max_cases_reduction(entries, tmp_path):
    """§12.1: 기본 all = 모든 씬 subcase(mapped_F 전부, 스트리밍 결과와 같음), max_cases 초과면 대표+최악 자동 축소
    + 경고 + 제외 표, representative 는 medoid 만."""
    tgt = entries[0]
    res, arr = an.run(entries, tgt, {"n_representative": 2})
    d = res["deck"]
    assert (d["requested"], d["mode"], d["reduced"], d["n_subcases"], d["excluded"]) == ("all", "all", False, 5, [])
    assert [x["label"] for x in d["cases"]] == ["S001", "S002", "S003", "S004", "S005"]
    full = an.deck_case_forces(res, arr)
    lcs = an.optdeck_load_cases(res, arr)
    assert len(full) == len(lcs) == 5 and lcs[0]["label"] == "S001_Corner3"
    assert np.allclose(full[0], tgt.raw["f"])
    for lc, f in zip(res["load_cases"], an.load_case_forces(res, arr)):       # 대표 = 덱 안의 같은 하중
        assert np.allclose(f, full[lc["case_index"]])
    assert all(c["deck_label"] == f"S{c['index'] + 1:03d}" for c in res["cases"])

    red, rarr = an.run(entries, tgt, {"n_representative": 2, "max_cases": 3})
    d = red["deck"]
    assert d["requested"] == "all" and d["mode"] == "representative+worst" and d["reduced"] is True
    assert any("max_cases 3" in w for w in red["warnings"])
    inc = {x["case_index"] for x in d["cases"]}
    assert d["n_subcases"] == len(inc) < 5 and len(d["excluded"]) == 5 - len(inc)
    assert all("자동 축소" in x["reason"] and x["case_index"] not in inc for x in d["excluded"])
    roles = sorted({x["role"] for x in d["cases"]})
    assert roles in (["medoid"], ["medoid", "worst"])
    assert rarr["mapped_F"].shape[0] == len(set(inc) | {lc["case_index"] for lc in red["load_cases"]})
    for lc, f in zip(d["cases"], an.deck_case_forces(red, rarr)):
        assert np.allclose(f, full[lc["case_index"]])
    out = str(tmp_path / "r.html")
    ra.write(red, out, rarr, None, {"analysis_id": "A1"})
    doc = open(out, encoding="utf-8").read()
    assert "제외된 씬과 사유" in doc and "자동 축소" in doc and "대표+최악" in doc

    rep, _ = an.run(entries, tgt, {"n_representative": 2, "deck_cases": "representative", "worst_case": True})
    assert [x["role"] for x in rep["deck"]["cases"]] == ["medoid", "medoid"] and not rep["deck"]["reduced"]
    with pytest.raises(EslError):
        an.run(entries, tgt, {"deck_cases": "everything"})

@pytest.mark.parametrize("max_cases, n_rep", [(1, 5), (2, 5), (3, 2), (4, 5), (4, 2)])
def test_deck_reduction_never_exceeds_max_cases(entries, max_cases, n_rep):
    """§12.4: 자동 축소(대표+최악) 후 subcase ≤ max_cases — 대표 수 자동 조정 + 경고(max_cases 1 이면 대표만)."""
    res, _ = an.run(entries, entries[0], {"n_representative": n_rep, "max_cases": max_cases})
    d = res["deck"]
    assert d["reduced"] is True and d["n_subcases"] <= max_cases and d["n_subcases"] == len(d["cases"])
    assert d["n_subcases"] + len(d["excluded"]) == 5
    k = len(res["clusters"])
    if 2 * min(n_rep, 5) > max_cases:
        assert k == max(1, max_cases // 2)
        assert any("대표 수" in w and f"max_cases {max_cases}" in w for w in res["warnings"])
    if max_cases == 1:
        assert d["mode"] == "representative" and [x["role"] for x in d["cases"]] == ["medoid"]
    else:
        assert d["mode"] == "representative+worst"


def test_run_errors(entries):
    with pytest.raises(EslError):
        an.run([], None)
    other = _entry("g", "A", 20, 12, 1.0, 1.0, "Face", 50, grid=(6, 4))
    with pytest.raises(EslError) as e:
        an.run(entries[:2] + [other], None)
    assert e.value.code == "GRID_MISMATCH"


def test_report_inline_json_escaped(entries, tmp_path):
    """분석 보고서 inline JSON 블롭: </script·<script·<!-- 가 블록을 깨지 않음(Case 보고서와 같은 헬퍼)."""
    evil = "A</script><script>alert(1)</script><!--x</SCRIPT"
    res, arr = an.run(entries, entries[0], {"n_representative": 2})
    res["analysis_id"] = evil
    out = str(tmp_path / "report.html")
    ra.write(res, out, arr, None, {"analysis_id": evil})
    doc = open(out, encoding="utf-8").read()
    m = re.search(r"<script type='application/json' id='esl-data'>(.*?)</script>", doc, re.S)
    blob = m.group(1)
    assert not re.search(r"</script|<script|<!--", blob, re.I)
    assert json.loads(blob)["analysis_id"] == evil
    assert doc.count("<script") == 2 and "<script>alert(1)" not in doc
