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


def _entry(eid, version, scene, mix, amp=1.0, mesh=(24, 16), with_raw=False):
    X0, conn, et, thk = synth_lib.plate_xz(mesh[0], mesh[1], 1.0)
    fr = nz.frame(X0, None, conn, et)
    p, q, w = mix
    f = amp * (synth_lib.pattern_load(X0, conn, et, p, fr) + w * synth_lib.pattern_load(X0, conn, et, q, fr))
    gs = nz.grid_summary(X0, f, GRID[0], GRID[1], fr)
    hx = 0.2 + 0.1 * scene + (0.0 if version == "v001" else 0.01)
    meta = {"entry_id": eid, "status": "active", "mesh_sha256": f"m{mesh}", "frame": fr,
            "grid": {"nx": GRID[0], "ny": GRID[1], "top_n": 10},
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


def _version(version, mesh, amp, changed=None, with_raw=False, scenes=SCENES):
    out = []
    for s, mix in scenes.items():
        if changed and s in changed:
            mix = changed[s]
        out.append(_entry(f"{version}_s{s}", version, s, mix, amp * (1 + 0.1 * s), mesh, with_raw))
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
    assert res["criteria"] == {"cos_min": 0.9, "rep_same": True}
    assert os.path.isfile(os.path.join(d, "report.html"))
    rc = lcli.main(["compare", "--root", root, "--config", LCFG, "--model", "50QX10A", "--new-version", "v001"],
                   echo=lines.append)
    assert rc == 1 and "NO_PAIRED_SCENES" in capsys.readouterr().err
    rc = lcli.main(["compare", "--root", root, "--config", LCFG, "--model", "50QX10A", "--base-version", "v001",
                    "--new-version", "v002", "--filter", "scene=9"], echo=lines.append)
    assert rc == 1 and "NO_PAIRED_SCENES" in capsys.readouterr().err
