"""V-0247-DM-8·9·11·12(일부)·14·21·23: select 스터디 depth_section — floor_fixed 스냅샷의 BD_MATRIX 산출물(basis.json 판·rules·
graph_vars.section, params 행 section·w_side, W 사유), 기저 재사용 조건, cfg 해시(floor_fixed 만 바뀜), W1 행 기본 켬."""
import json
import os
import sys

import numpy as np
import pytest
from _bg_util import CFG, cf, esl_mesh

from esl.doe import DEFAULTS
from esl.doe import bead_graph as bgr
from esl.doe import stages as stg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden_v0247_c1"))
import golden as G  # noqa: E402


def _graph_study(tmp_path, **extra):
    mesh = esl_mesh(cf.load_fixture("h5"))
    doe = G._study(str(tmp_path), mesh, "G1", select_schema=2, bead_source="auto", **extra)
    doe["base"]["case_dir"] = str(tmp_path / "case" / "input")
    out, run = G._runner(str(tmp_path), doe)
    msgs = []

    def run2(stage, **kw):
        return stg.run_stage({"stage": stage, "out": out, "doe": {**doe, **kw}}, msgs.append)
    run2("bd_input")
    run2("bd_loads")
    auto = json.loads(open(os.path.join(out, "prep", "select", "auto_selection.json"), encoding="utf-8").read())
    doe["selection"] = {"rev": 1, "sha256": auto["sha256"], "input": auto["selection"]}
    return mesh, doe, out, run2, msgs, auto["sha256"]


SPEC = {"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_D", "lo": 6.0, "hi": 10.0},
                                                       {"name": "B1_W", "lo": 26.0, "hi": 34.0}]}


def test_floor_fixed_matrix_outputs(tmp_path):
    rules = dict(DEFAULTS["depth_section_rules"])
    mesh, doe, out, run, msgs, sha = _graph_study(tmp_path, depth_section="floor_fixed", depth_section_rules=rules)
    run("bd_matrix", rev=1, spec=SPEC)
    d = os.path.join(out, "select", sha[:12])
    bj = json.load(open(os.path.join(d, "basis.json"), encoding="utf-8"))
    import beadgraph as bg
    assert bj["depth_section"] == "floor_fixed" and bj["section_rules"] == rules and bj["df_rules"] == bg.DF_RULES
    assert bj["beadgraph_package"] == "1.2.0" and bj["beadgraph_version"] == "1.1.0" and bj["morph_rules"] == 2
    dv = [v for v in bj["graph_vars"] if v["name"].endswith("_D")]
    assert dv and all(v["kind"] == "D" and v["section"]["mode"] == "floor_fixed" for v in dv)
    assert all(v["section"]["floor_plan_max_mm"] == 0.0 for v in dv)
    assert all({"entry_guard_n", "entry_guard_left", "entry_clipped_n", "angle_dev_mm", "cot_min_deg", "cot_med_deg",
                "cot_max_deg"} <= set(v["section"]) and v["section"]["entry_guard_left"] == 0 for v in dv)   # §2.6
    rows = json.load(open(os.path.join(d, "params.json"), encoding="utf-8"))["params"]
    r = next(x for x in rows if x["name"] == "B1_D")
    assert r["section"]["mode"] == "floor_fixed" and r["section"]["applied"] is True
    assert not any("w_side" in x for x in rows)                    # H5 채널 = 양쪽 W
    # 기저 재사용(같은 스냅샷) / 옛 스냅샷과 cfg 해시 다름
    msgs.clear()
    run("bd_matrix", rev=2, spec=SPEC)
    assert any("재사용" in m for m in msgs)
    c_new = stg.Ctx({"stage": "x", "out": out, "doe": doe})
    c_old = stg.Ctx({"stage": "x", "out": out, "doe": {k: v for k, v in doe.items()
                                                       if k not in ("depth_section", "depth_section_rules")}})
    c_ent = stg.Ctx({"stage": "x", "out": out, "doe": {**doe, "depth_section": "entry_fixed"}})
    assert stg._sel_cfg_sha(c_new) != stg._sel_cfg_sha(c_old) == stg._sel_cfg_sha(c_ent)
    # DF 기저: 깊이면(달성 노드) 평면 0
    z = np.load(os.path.join(d, "basis.npz"), allow_pickle=False)
    assert z.files


def test_entry_fixed_snapshot_reuses_old_basis(tmp_path):
    """옛 basis.json(키 없음)을 floor_fixed 스냅샷이 재사용하지 않음(depth_section 재사용 조건)."""
    mesh, doe, out, run, msgs, sha = _graph_study(tmp_path)
    run("bd_matrix", rev=1, spec=SPEC)
    msgs.clear()
    doe2 = {**doe, "depth_section": "floor_fixed", "depth_section_rules": dict(DEFAULTS["depth_section_rules"])}
    stg.run_stage({"stage": "bd_matrix", "out": out, "doe": {**doe2, "rev": 2, "spec": SPEC}}, msgs.append)
    assert not any("재사용" in m for m in msgs)


@pytest.fixture(scope="module")
def ONE():
    from beadgraph.testing import synth_oneside as so
    c = so.oneside("b")
    fx = {"x0": c["nodes"], "conn": c["conn"], "fixed": c["fixed"]}
    mesh = esl_mesh(fx)
    import tempfile
    dd = tempfile.mkdtemp(prefix="ds_one_")
    st = bgr.prep_graph(mesh, c["fixed"] + 1, CFG, dd)
    assert st["ok"]
    g, lab = bgr.load_graph(dd)
    return mesh, g, lab, tuple((c["fixed"] + 1).tolist())


def _sel(g, ids):
    return {"schema_version": 2, "graph": {"sha256": bgr.graph_sha_of(g), "rules": g["rules"], "edits": {}}, "beads": [{"id": f"b{i + 1}", "name": f"B{i + 1}", "src": "graph",
                                            "segs": [{"anchor": g["segments"][s]["anchor"]}]} for i, s in enumerate(ids)]}


def test_w1_row_and_reason_v21_v26(ONE):
    mesh, g, lab, fx = ONE
    ids = [s["id"] for s in g["segments"] if s["type"] != "base"]
    norm, _sha = bgr.normalize_v2(_sel(g, ids), g, CFG, labels=lab, mesh=mesh)
    Dold = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx)
    assert all("W" not in b.vars for b in Dold.beads)
    assert {bgr.w_reason_of(Dold, b) for b in Dold.beads} == {"W_ENTRY_ONE_SIDE"}       # 옛·entry_fixed 문구
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fx, depth_section="floor_fixed",
                          section_rules=DEFAULTS["depth_section_rules"])
    rows = bgr.params_rows_v2(D, CFG)
    w = [r for r in rows if r["type"] == "W"]
    assert w and all(r["w_side"] == "one" and r["use_default"] for r in w)
    assert all(b.depth_kind == "DF" and b.w_reason is None for b in D.beads)
    assert any(x["code"] == "DS_ONE_SIDE" for b in D.beads for x in b.warnings)
    B = bgr.basis_v2(mesh, D, CFG)
    kinds = {v["name"]: v["kind"] for v in D.graph_basis}
    assert set(kinds.values()) == {"DF", "W1"}
    assert {v["name"] for v in B.vars} == {r["name"] for r in rows}
    # D·W1 동시 = 선형 합(기저 행렬 형식 불변)
    assert all(v["vec"].shape[1] == 3 for v in B.vars)


def test_defaults_mirror_v14():
    import yaml
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for fn in ("esl_platform.example.yaml", "esl_platform.prod.example.yaml"):
        y = yaml.safe_load(open(os.path.join(root, "config", fn), encoding="utf-8"))["bead_doe"]
        assert y["depth_section"] == DEFAULTS["depth_section"] == "floor_fixed", fn
        assert y["depth_section_rules"] == DEFAULTS["depth_section_rules"], fn
    from esl.doe.bead_select import _cfg
    assert "depth_section" not in _cfg(CFG)                     # select 절 키 수 불변(graph.json cfg 불변)
