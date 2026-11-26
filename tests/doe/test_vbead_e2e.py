"""V-0250-VB-13·19 결과 경로 e2e(계약 esl_virtual_bead.md §10·§12-13·19): 합성 그래프 스터디(채널 비드 b1 + 가상 비드 a1, 새 스냅샷
virtual_bead·shape_rules 블록) → BD_MATRIX → BD_EVAL → BD_POST. 변수 행·기저·안 좌표(= morph)·바뀐 노드(발자국 ∪ b1 지지)·결과 정보
VB_VERIFY_HINT·d000 = 가상 비드 없는 같은 스터디 d000. 가상 비드만 있는 선택도 행렬·평가 정상."""
import json
import os
import sys

import numpy as np
import pytest
import synth_vbead as sv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden_v0247_c1"))
import golden as G7  # noqa: E402

from esl.doe import DEFAULTS  # noqa: E402
from esl.morph import virtual_bead as vbm  # noqa: E402

pytestmark = pytest.mark.slow

BLK = {"schema": 1, **{k: DEFAULTS["virtual_bead"][k] for k in vbm.HASH_KEYS}}
VB = {"id": "a1", "p0": [60.0, 140.0, 0.0], "p1": [180.0, 140.0, 0.0], "w_top": 10.0, "d_max": 6.0, "r": 10.0}


def _rd(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def study(tmp, vbs, graph_beads=True, block=True):
    mesh = sv.graph_mesh()
    extra = {"shape_rules": {"schema": 1}}
    if block:
        extra["virtual_bead"] = dict(BLK)
    doe = G7._study(str(tmp), mesh, "V1", select_schema=2, bead_source="auto", **extra)
    doe["base"]["case_dir"] = os.path.join(str(tmp), "case", "input")
    out, run = G7._runner(str(tmp), doe)
    run("bd_input")
    run("bd_loads")
    auto = _rd(os.path.join(out, "prep", "select", "auto_selection.json"))
    inp = dict(auto["selection"])
    if not graph_beads:
        inp["beads"] = []
    if vbs:
        inp["virtual_beads"] = [dict(v) for v in vbs]
    doe["selection"] = {"rev": 1, "input": inp}
    return doe, out, run, mesh


def _post(out, run, params, n=3):
    run("bd_matrix", rev=1, spec={"method": "lhs", "n": n, "seed": 2, "params": params})
    m = _rd(os.path.join(out, "doe", "1", "matrix.json"))
    for x in m["designs"]:
        r = run("bd_eval", rev=1, design=x["id"])
        assert r["status"] == "OK", (x["id"], r)
    run("bd_post", rev=1)
    return m


def _sel_dir(out):
    d = os.path.join(out, "select")
    return os.path.join(d, sorted(os.listdir(d))[0])


def test_e2e_graph_plus_virtual_v13(tmp_path):
    from esl.doe import bead_select as bs
    doe, out, run, mesh = study(tmp_path / "a", [VB])
    m = _post(out, run, [{"name": "B1_D", "lo": 5.0, "hi": 7.0}, {"name": "A1_A", "lo": 0.0, "hi": 3.0}])
    sd = _sel_dir(out)
    pj = _rd(os.path.join(sd, "params.json"))
    rows = {r["name"]: r for r in pj["params"]}
    assert rows["A1_A"]["type"] == "A" and rows["A1_A"]["form"] == "hinge"
    assert [b["kind"] for b in pj["beads"]][-1] == "virtual"
    bj = _rd(os.path.join(sd, "basis.json"))
    assert bj["vb_rules"] == vbm.VB_RULES and bj["virtual_beads"][0]["id"] == "a1"
    assert next(v for v in bj["vars"] if v["name"] == "A1_A")["form"] == "hinge"
    B = bs.load_basis(os.path.join(sd, "basis.npz"))
    x0 = np.asarray(mesh["x0"])
    a = next(v for v in B.vars if v["name"] == "A1_A")
    b1 = np.unique(np.concatenate([v["idx"] for v in B.vars if v["bead"] == "b1"]))
    for x in m["designs"]:
        dz = np.load(os.path.join(out, "run", "designs", x["id"], "design.npz"))
        xd = dz["x"]
        assert np.allclose(xd, bs.morph(x0, B, x["values"]), atol=1e-9)               # view3d·재낙하 = 실좌표
        moved = np.flatnonzero(np.linalg.norm(xd - x0, axis=1) > 1e-12)
        assert set(moved.tolist()) <= set(a["idx"].tolist()) | set(b1.tolist())
    res = _rd(os.path.join(out, "post", "result.json"))
    assert any(str(w).startswith("VB_VERIFY_HINT") for w in res["warnings"])
    assert any("A1_A" in json.dumps(r) for r in res["ranking"])
    # d000 = 가상 비드 없는 같은 스터디의 d000(공칭 0 = 지금 형상)
    _d, out0, run0, _m = study(tmp_path / "b", [])
    _post(out0, run0, [{"name": "B1_D", "lo": 5.0, "hi": 7.0}], n=2)
    ra = _rd(os.path.join(out, "run", "designs", "d000", "result.json"))
    rb = _rd(os.path.join(out0, "run", "designs", "d000", "result.json"))
    assert ra["status"] == "OK" and ra["C_max"] is not None
    for k in ("C_max", "score", "per_esl", "worst_entry_id", "status"):
        assert ra[k] == rb[k], k
    xa = np.load(os.path.join(out, "run", "designs", "d000", "design.npz"))
    xb = np.load(os.path.join(out0, "run", "designs", "d000", "design.npz"))
    for k in xa.files:
        if xa[k].dtype.kind == "f" and k in xb.files:
            assert np.array_equal(xa[k], xb[k]), k


def test_e2e_virtual_only_v19(tmp_path):
    doe, out, run, mesh = study(tmp_path, [VB], graph_beads=False)
    m = _post(out, run, [{"name": "A1_A", "lo": 0.0, "hi": 2.0}], n=2)
    assert [d["id"] for d in m["designs"]][:2] == ["d000", "d001"]
    rg = os.path.join(_sel_dir(out), "range_guard.json")
    doc = _rd(rg)
    assert [e["var"] for e in doc["entries"]] == ["A1_A"] and doc["combos"] == []


def test_old_study_without_block_scope_v19(tmp_path):
    """블록 없는 옛 스터디 + 가상 비드 = VB_SCOPE(변수 행 없음 — 비드 행 사유)."""
    doe, out, run, mesh = study(tmp_path, [VB], block=False)
    run("bd_matrix", rev=1, spec={"method": "lhs", "n": 2, "seed": 2, "params": [{"name": "B1_D", "lo": 5.0, "hi": 7.0}]})
    pj = _rd(os.path.join(_sel_dir(out), "params.json"))
    assert not any(r["name"] == "A1_A" for r in pj["params"])
    vb = [b for b in pj["beads"] if b["kind"] == "virtual"][0]
    assert vb["vb_reason"]["code"] == "VB_SCOPE"
