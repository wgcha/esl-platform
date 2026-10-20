"""P2 §12.2 설계 버전 비교(ESLSO 수렴 판정) 단위·CLI 시험: 합성 버전 쌍.

- 같은 패턴(메시·크기만 다른 새 버전) → cos ≈ 1, 대표 동일 → CONVERGED
- 한 씬의 패턴 변경 → cos 미달 → ITERATE + 바뀐 씬 목록
- 짝 없음 → NO_PAIRED_SCENES
- 보고서 자체 완결(외부 URL 0)·inline JSON 이스케이프, CLI compare(기본 버전 = 최신, 기준 = 직전)
"""
import json
import os
import re

import numpy as np
import pytest

import synth_lib
from esl.errors import EslError
from esl.library import _util as U
from esl.library import cli as lcli
from esl.library import compare as cmp
from esl.library import normalize as nz
from esl.library import store
from esl.library.entry import LibraryEntry

LCFG = os.path.join(synth_lib.ROOT, "config", "library.example.yaml")
GRID = (8, 6)
# 씬 번호 → (주 패턴, 섞을 패턴, 섞는 비율): 클러스터 A = S1(중심)·S2·S3, 클러스터 B = S4(중심)·S5·S6
SCENES = {1: ("A", "B", 0.0), 2: ("A", "B", 0.25), 3: ("A", "B", -0.25),
          4: ("B", "A", 0.0), 5: ("B", "A", 0.25), 6: ("B", "A", -0.25)}


def _entry(eid, version, scene, mix, amp=1.0, mesh=(24, 16), with_raw=False, grid=GRID):
    X0, conn, et, thk = synth_lib.plate_xz(mesh[0], mesh[1], 1.0)
    fr = nz.frame(X0, None, conn, et)
    p, q, w = mix
    f = amp * (synth_lib.pattern_load(X0, conn, et, p, fr) + w * synth_lib.pattern_load(X0, conn, et, q, fr))
    gs = nz.grid_summary(X0, f, grid[0], grid[1], fr)
    hx = 0.2 + 0.1 * scene + (0.0 if version == "v001" else 0.01)
    meta = {"entry_id": eid, "status": "active", "mesh_sha256": f"m{mesh}", "frame": fr,
            "grid": {"nx": grid[0], "ny": grid[1], "top_n": 10},
            "model": {"product": "50QX10A", "inch": 50, "version": version, "mass": {"value": 10.0}},
            "scene": {"scenario": "FREE", "seq": scene, "drop_type": "Corner" if scene < 4 else "Face",
                      "drop_class": "Corner" if scene < 4 else "Face", "orient": "3", "scene": scene, "round": None,
                      "suffix": "comp"},
            "quality": {"verdict": "PASS", "hotspot1_rel_err": 0.02,
                        "hotspots": [{"rank": 1, "elem_id": 1, "xi": hx, "eta": 0.5, "eps_rad": 0.01 * amp}],
                        "field": {"abs_err_pct": {"p90": 3.0}}},
            "tstar": {"frame_index": 6, "eps_max": 0.01 * amp},
            "summary": {"sum_abs_f": float(np.linalg.norm(f, axis=1).sum())}}
    raw = None
    if with_raw:
        N, Ne = X0.shape[0], conn.shape[0]
        raw = {"node_id": np.arange(1, N + 1), "x0": X0, "elem_id": np.arange(1, Ne + 1), "elem_type": et,
               "conn": conn, "elem_pid": np.ones(Ne, dtype=np.int64), "elem_mid": np.ones(Ne, dtype=np.int64),
               "thickness": thk, "E": np.full(Ne, 7e4), "nu": np.full(Ne, 0.3), "f": f, "u_rel": np.zeros((N, 3)),
               "is_bc": np.zeros(N, dtype=bool), "support_node_id": np.array([1, 2, 3]),
               "support_dof": np.array(["123", "23", "3"])}
    return LibraryEntry(meta=U.jsonable(meta), summary=gs, raw=raw)


def _version(version, mesh, amp, changed=None, with_raw=False, scenes=SCENES, grid=GRID):
    out = []
    for s, mix in scenes.items():
        if changed and s in changed:
            mix = changed[s]
        out.append(_entry(f"{version}_s{s}", version, s, mix, amp * (1 + 0.1 * s), mesh, with_raw, grid))
    return out


def test_same_pattern_converges():
    base = _version("v001", (24, 16), 1.0)
    new = _version("v002", (30, 20), 1.1)              # 비드 반영(메시 변경)·크기 10% 증가, 패턴 같음
    r = cmp.compare(base, new, {"cos_min": 0.9, "rep_same": True}, {"n_representative": 2})
    assert r["n_paired"] == 6 and r["unpaired"] == {"base_only": [], "new_only": []}
    assert r["aggregate"]["cos_min"] > 0.95                 # 메시 해상도 차이만
    assert r["representatives"]["rep_same"] and r["representatives"]["partition_same"]
    assert sorted(m["base_medoid_label"] for m in r["representatives"]["matching"]) == \
        ["FREE #1 Corner3 S1 comp", "FREE #4 Face3 S4 comp"]
    cv = r["convergence"]
    assert cv["verdict"] == "CONVERGED" and cv["label"] == "수렴(반복 불필요)" and cv["changed_scenes"] == []
    s = r["scenes"][0]
    assert s["force_ratio"] == pytest.approx(1.1, rel=0.05) and s["eps_ratio"] == pytest.approx(1.1)
    assert s["hotspot_shift"] == pytest.approx(0.01) and not s["verdict_changed"]
    env = r["envelope"]
    assert np.asarray(env["diff"]).shape == GRID
    assert np.allclose(np.asarray(env["new"]) - np.asarray(env["base"]), np.asarray(env["diff"]))


def test_pattern_change_recommends_iteration():
    base = _version("v001", (24, 16), 1.0)
    new = _version("v002", (30, 20), 1.0, changed={2: ("B", "A", 0.3)})     # S2: 굽힘 → 막 지배로 바뀜
    r = cmp.compare(base, new, {"cos_min": 0.9, "rep_same": True}, {"n_representative": 2})
    cv = r["convergence"]
    assert cv["verdict"] == "ITERATE" and cv["label"] == "추가 반복 권장" and not cv["converged"]
    by = {s["label"]: s for s in r["scenes"]}
    s2 = by["FREE #2 Corner3 S2 comp"]
    assert s2["cos"] < 0.9 and s2["changed"] and "하중 패턴 변화" in s2["reasons"][0]
    assert r["aggregate"]["argmin_cos"] == s2["label"] and r["aggregate"]["n_below_cos"] == 1
    assert any(c["label"] == s2["label"] for c in cv["changed_scenes"])
    assert any("cos 최소" in x for x in cv["reasons"])
    # cos 기준만 낮추면 패턴 기준은 통과 — 판정은 대표 동일 여부에 달림
    r2 = cmp.compare(base, new, {"cos_min": 0.05, "rep_same": False}, {"n_representative": 2})
    assert r2["convergence"]["verdict"] == "CONVERGED"


def test_no_paired_scenes_and_partial_pairs():
    base = _version("v001", (24, 16), 1.0, scenes={1: SCENES[1], 2: SCENES[2]})
    new = _version("v002", (24, 16), 1.0, scenes={4: SCENES[4], 5: SCENES[5]})
    with pytest.raises(EslError) as e:
        cmp.compare(base, new)
    assert e.value.code == "NO_PAIRED_SCENES"
    new2 = _version("v002", (24, 16), 1.0, scenes={1: SCENES[1], 2: SCENES[2], 5: SCENES[5]})
    r = cmp.compare(base, new2, None, {"n_representative": 5})
    assert r["n_paired"] == 2 and r["representatives"]["k"] == 2
    assert [x["label"] for x in r["unpaired"]["new_only"]] == ["FREE #5 Face3 S5 comp"]
    assert any("짝 없는 씬" in w for w in r["warnings"])
    other = _entry("x", "v002", 1, SCENES[1])
    other.meta["model"]["product"] = "60QX10A"
    with pytest.raises(EslError):
        cmp.compare(base, [other])


def test_versions_sorting():
    assert cmp.sort_versions(["v10", "v2", "v001", None]) == ["v001", "v2", "v10"]
    assert cmp.previous_version(["v001", "v002", "v010"], "v010") == "v002"
    assert cmp.previous_version(["v001"], "v001") is None
    # §12.4 자연 순서 동률(v100·v0100, V1·v1) → 원문 사전순(결정적)
    assert cmp.sort_versions(["v100", "v0100", "v99", "v1", "V1"]) == ["V1", "v1", "v99", "v0100", "v100"]
    assert cmp.previous_version(["v0100", "v100", "v99"], "v100") == "v0100"
    assert cmp.previous_version(["v0100", "v100", "v99"], "v0100") == "v99"


def test_versions_sorting_hash_seed_independent():
    """집합 순회 순서(PYTHONHASHSEED)와 무관하게 같은 결과."""
    import subprocess
    import sys

    code = ("from esl.library import compare as c; vs = ['v100', 'v0100', 'v100a', 'V100', 'v2', 'v02', 'v010', 'v10'];"
            "print(c.sort_versions(vs), c.previous_version(vs, 'v100'))")
    outs = set()
    for seed in ("1", "2", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=synth_lib.ROOT)
        outs.add(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                                check=True).stdout)
    assert len(outs) == 1, outs


def test_report_self_contained_and_escaped(tmp_path):
    base = _version("v001", (24, 16), 1.0)
    new = _version("v002", (30, 20), 1.0, changed={2: ("B", "A", 0.3)})
    r = cmp.compare(base, new, None, {"n_representative": 2})
    evil = "C</script><script>alert(1)</script><!--x"
    r.update(comparison_id=evil, model="50QX10A", base_version="v001", new_version="v002")
    w = U.Writer(str(tmp_path))
    files = cmp.save(r, str(tmp_path), w)
    assert files == ["compare.json", "report.html"]
    doc = open(tmp_path / "report.html", encoding="utf-8").read()
    m = re.search(r"<script type='application/json' id='esl-data'>(.*?)</script>", doc, re.S)
    assert not re.search(r"</script|<script|<!--", m.group(1), re.I)
    assert json.loads(m.group(1))["comparison_id"] == evil
    assert doc.count("<script") == 2 and "<script>alert(1)" not in doc
    assert not re.search(r"https?:|//[a-z0-9]|\bsrc\s*=|@import|url\(", doc, re.I)
    assert "추가 반복 권장" in doc and "셀 포락 차이" in doc and doc.count("<svg") >= 2
    assert json.load(open(tmp_path / "compare.json", encoding="utf-8"))["convergence"]["verdict"] == "ITERATE"


def test_cli_compare(tmp_path, capsys):
    root = str(tmp_path / "root")
    w = U.Writer(root)
    for e in _version("v001", (24, 16), 1.0, with_raw=True) + _version("v002", (30, 20), 1.05, with_raw=True):
        store.register(root, e, w)
    lines = []
    rc = lcli.main(["compare", "--root", root, "--config", LCFG, "--model", "50QX10A", "--id", "C1",
                    "--n-representative", "2"], echo=lines.append)
    assert rc == 0, capsys.readouterr().err
    assert "v001 → v002" in lines[0] and "수렴(반복 불필요)" in lines[0]
    d = store.compare_dir(root, "C1")
    res = json.load(open(os.path.join(d, "compare.json"), encoding="utf-8"))
    assert (res["base_version"], res["new_version"], res["n_paired"]) == ("v001", "v002", 6)
    assert res["criteria"] == {"cos_min": 0.95, "rep_same": True, "min_nodes_per_cell": 64, "coarsen": False}
    assert res["resolution"]["level"] == "low" and any("셀당 노드" in x for x in lines)
    assert os.path.isfile(os.path.join(d, "report.html"))
    rc = lcli.main(["compare", "--root", root, "--config", LCFG, "--model", "50QX10A", "--new-version", "v001"],
                   echo=lines.append)
    assert rc == 1 and "NO_PAIRED_SCENES" in capsys.readouterr().err
    rc = lcli.main(["compare", "--root", root, "--config", LCFG, "--model", "50QX10A", "--base-version", "v001",
                    "--new-version", "v002", "--filter", "scene=9"], echo=lines.append)
    assert rc == 1 and "NO_PAIRED_SCENES" in capsys.readouterr().err


def _v3b_scenes(K, seed=3):
    """Verifier v3b: 두 패턴 계열(A 주·B 주) 의 연속적 섞음 비율 — k-medoids 분할이 거의 같은 비용으로 뒤집히기 쉬움."""
    rng = np.random.default_rng(seed)
    return {s: (("A", "B") if s % 2 else ("B", "A")) + (float(rng.uniform(-.5, .5)),) for s in range(1, K + 1)}


@pytest.mark.parametrize("K", [12, 24])
def test_rep_same_relaxed_same_pattern_converges(K):
    """§12.4: 같은 패턴(메시·크기만 변경)은 k 와 무관하게 CONVERGED — medoid 씬 ID 가 달라도 짝 medoid cos ≥ cos_min
    이면 같은 대표, 연속 분포에서 분할이 뒤집히면 기준 대표 유지 규칙."""
    sc = _v3b_scenes(K)
    base = _version("v001", (24, 16), 1.0, scenes=sc)
    for mesh in ((30, 20), (48, 32)):
        new = _version("v002", mesh, 1.1, scenes=sc)
        for k in (2, 3, 5, 8):
            r = cmp.compare(base, new, None, {"n_representative": k})        # 기본 cos_min 0.95
            assert r["criteria"]["cos_min"] == 0.95
            assert r["convergence"]["verdict"] == "CONVERGED", (K, mesh, k, r["convergence"]["reasons"])
            reps = r["representatives"]
            assert reps["rep_same"] and reps["rep_basis"] in ("medoid_cos", "base_kept")
            assert all("medoid_cos" in m for m in reps["matching"])
    # 메시 변경 + k=2: medoid 씬 ID 는 바뀌지만(구 규칙이면 ITERATE) 짝 medoid cos 로 같은 대표
    r = cmp.compare(base, _version("v002", (30, 20), 1.1, scenes=sc), None, {"n_representative": 2})
    if not r["representatives"]["medoid_id_same"]:
        assert r["representatives"]["rep_same"]


def test_rep_same_relaxed_pattern_change_iterates():
    sc = _v3b_scenes(24)
    base = _version("v001", (24, 16), 1.0, scenes=sc)
    chg = {2: ("A", "B", 0.3), 4: ("A", "B", 0.0), 6: ("A", "B", 0.1)}       # B 주 → A 주
    new = _version("v002", (30, 20), 1.1, scenes=sc, changed=chg)
    for k in (2, 5, 8):
        r = cmp.compare(base, new, None, {"n_representative": k})
        cv = r["convergence"]
        assert cv["verdict"] == "ITERATE" and r["aggregate"]["n_below_cos"] == 3
        assert {c["label"].split()[1] for c in cv["changed_scenes"]} >= {"#2", "#4", "#6"}


def test_resolution_warning_and_coarsen():
    """셀당 노드 중앙값 < 64 경고, < 16 "판정 신뢰 낮음", coarsen half 는 2×2 묶음(12×7 이하 격자에서는 무시)."""
    base = _version("v001", (24, 16), 1.0)              # 8×6 격자 → 셀당 약 9 노드
    new = _version("v002", (30, 20), 1.1)
    r = cmp.compare(base, new)
    rs = r["resolution"]
    assert rs["level"] == "low" and rs["label"] == "판정 신뢰 낮음" and rs["nodes_per_cell_min"] < 16
    assert r["convergence"]["reliability"] == "low" and any("판정 신뢰 낮음" in w for w in r["warnings"])
    r = cmp.compare(base, new, {"min_nodes_per_cell": 4})
    assert r["resolution"]["level"] == "ok" and not any("셀당 노드" in w for w in r["warnings"])
    r = cmp.compare(base, new, {"coarsen": "half"})
    assert not r["resolution"]["coarsen_applied"] and any("무시" in w for w in r["warnings"])
    with pytest.raises(EslError):
        cmp.compare(base, new, {"coarsen": "quarter"})
    # 24×14 격자(가로 48 요소 메시 → 셀당 약 4~5 노드): half 로 묶으면 셀당 노드 ×4, cos 회복
    g = (24, 14)
    b2 = _version("v001", (48, 32), 1.0, grid=g)
    n2 = _version("v002", (60, 40), 1.1, grid=g)
    raw = cmp.compare(b2, n2, None, {"n_representative": 2})
    half = cmp.compare(b2, n2, {"coarsen": "half"}, {"n_representative": 2})
    assert half["resolution"]["coarsen_applied"] and half["resolution"]["feature_grid"] == {"nx": 12, "ny": 7}
    assert half["resolution"]["nodes_per_cell_min"] >= 3.5 * raw["resolution"]["nodes_per_cell_min"]
    assert half["aggregate"]["cos_min"] > raw["aggregate"]["cos_min"]
    assert np.asarray(half["envelope"]["diff"]).shape == g           # 포락 히트맵은 원래 격자


def test_coarsen_half_conserves_resultants():
    rng = np.random.default_rng(0)
    for nx, ny in ((6, 4), (7, 5)):
        F, M = rng.normal(size=(nx, ny, 3)), rng.normal(size=(nx, ny, 3))
        C = np.stack(list(np.meshgrid(np.arange(nx) + .5, np.arange(ny) + .5, indexing="ij")) + [np.zeros((nx, ny))], -1)
        F2, M2, C2 = cmp.coarsen_half(F, M, C)
        assert F2.shape == ((nx + 1) // 2, (ny + 1) // 2, 3)
        assert np.allclose(F2.sum((0, 1)), F.sum((0, 1)))
        tm = (M + np.cross(C, F)).sum((0, 1))
        assert np.allclose((M2 + np.cross(C2, F2)).sum((0, 1)), tm)     # 원점 합모멘트 보존


def test_report_reliability_badge(tmp_path):
    r = cmp.compare(_version("v001", (24, 16), 1.0), _version("v002", (30, 20), 1.0), None, {"n_representative": 2})
    r.update(comparison_id="C1", model="50QX10A", base_version="v001", new_version="v002")
    cmp.save(r, str(tmp_path), U.Writer(str(tmp_path)))
    doc = open(tmp_path / "report.html", encoding="utf-8").read()
    assert doc.count("id='reliability'") == 1 and "판정 신뢰 낮음" in doc and "medoid cos" in doc
