"""Core stages with select_schema 2 (BG-D-35..42): BD_INPUT records select_schema, BD_LOADS writes graph.json /
graph_labels.npz / graph.bin + graph auto seed (paicad hints only), BD_MATRIX derives / bases the schema 2 selection
(graph_algo · morph_rules in basis.json, chk_o* in derived.npz), preview grid + one design evaluation; schema 1 studies
get no graph files and no new input.json keys."""
import json

import numpy as np
from _bg_util import CFG, cf, esl_mesh  # noqa: F401

from esl.doe import bead_auto as ba
from esl.doe import bead_graph as bgr
from esl.doe import bead_select as bs
from esl.doe import stages as stg


def _study(tmp_path, mesh, **extra):
    import synth_doe as sd
    cd = tmp_path / "case" / "input"
    cd.mkdir(parents=True, exist_ok=True)
    rad = sd.write_mesh_rad(str(cd / "model.rad"), mesh)
    dirs = [sd.save_entry(str(tmp_path / "lib"), "E0", mesh, "bend", 1.0, seed=0)[0]]
    return {"id": "G1", "scenario": "select", "title": "t",
            "cfg": {"bead_doe": {"enabled": True}, "opt_run": {"solver": {"backend": "superlu"}}},
            "entries": [{"id": "E0", "dir": dirs[0]}],
            "base": {"entry_id": "E0", "rad_path": rad, "part_title": sd.PART_TITLE, "case_dir": str(cd)}, **extra}


def test_schema2_stages(tmp_path):
    mesh = esl_mesh(cf.load_fixture("h5"))
    doe = _study(tmp_path, mesh, select_schema=2, bead_source="auto")
    out = tmp_path / "_doe" / "G1"
    msgs = []

    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": str(out), "doe": {**doe, **kw}}, msgs.append)
    run("bd_input")
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    assert inp["select_schema"] == 2
    r = run("bd_loads")
    sd_ = out / "prep" / "select"
    for f in (bgr.GRAPH_JSON, bgr.GRAPH_LABELS, bgr.GRAPH_BIN, ba.AUTO_SELECTION_JSON):
        assert (sd_ / f).is_file(), f
    assert r["graph"]["ok"] and r["auto"]["ok"] and r["auto"]["source"] == "graph"
    assert any(w["code"] == "AUTO_HINT_UNAVAILABLE" for w in r["auto"]["warnings"])     # no paicad: hints only
    b1 = (sd_ / bgr.GRAPH_JSON).read_bytes()
    a1 = (sd_ / ba.AUTO_SELECTION_JSON).read_bytes()
    run("bd_loads")
    assert (sd_ / bgr.GRAPH_JSON).read_bytes() == b1 and (sd_ / ba.AUTO_SELECTION_JSON).read_bytes() == a1
    auto = json.loads(a1)
    assert auto["schema"] == bgr.AUTO_SCHEMA_V2 and auto["source"] == "graph"
    assert ba.read_auto_selection(str(sd_ / ba.AUTO_SELECTION_JSON)) == auto      # Backend GET …/select/auto reader
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    assert inp["graph"]["ok"] and inp["graph"]["sha256"] == bgr.graph_sha256(str(out / "prep"))
    sel = auto["selection"]
    g, lab = bgr.load_graph(str(out / "prep"))
    norm, sha = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    assert sha == auto["sha256"]
    doe["selection"] = {"rev": 1, "sha256": sha, "input": sel}
    spec = {"method": "lhs", "n": 3, "seed": 1, "params": [{"name": "B1_D", "lo": 6.0, "hi": 10.0}]}
    r1 = run("bd_matrix", rev=1, spec=spec)
    sdir = out / "select" / sha[:12]
    bj = json.loads((sdir / "basis.json").read_text(encoding="utf-8"))
    assert bj["graph_algo"] == bgr.GRAPH_ALGO and bj["morph_rules"] == bgr._bg().MORPH_RULES == 2 and bj["algo"] == bs.ALGO
    z = np.load(sdir / "derived.npz", allow_pickle=False)
    assert any(k.startswith("chk_o") for k in z.files)
    assert r1["selection_sha256"] == sha
    msgs.clear()
    run("bd_matrix", rev=2, spec=spec)
    assert any("재사용" in s for s in msgs)
    r3 = run("bd_matrix", rev=3, spec={**spec, "params": [{"name": "B1_D", "lo": 2.0, "hi": 14.0}]})
    assert any(w.startswith("BG_RAMP_SHORT") for w in r3["warnings"])
    g1 = run("bd_select_grid", rev=1)
    man = json.loads((out / "doe" / "1" / "grid" / "grid_manifest.json").read_text(encoding="utf-8"))
    assert man["graph_rules"] == bgr.GRAPH_RULES and man["rules"] == bs.RULES
    assert g1["counts"]["ok"] >= 1
    m = json.loads((out / "doe" / "1" / "matrix.json").read_text(encoding="utf-8"))
    did = next(x["id"] for x in m["designs"] if x["id"] != "d000")
    e = run("bd_eval", rev=1, design=did)
    assert e["status"] in ("OK", "FAILED_SOLVE") or e.get("reused")


def test_schema1_no_graph(tmp_path):
    """schema 1 study: no select_schema key, no graph files (BG-D-40, V-BG-12)."""
    mesh = esl_mesh(cf.load_fixture("h5"))
    doe = _study(tmp_path, mesh)
    out = tmp_path / "_doe" / "G1"

    def run(stage, **kw):
        return stg.run_stage({"stage": stage, "out": str(out), "doe": {**doe, **kw}}, lambda s: None)
    run("bd_input")
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    assert "select_schema" not in inp
    r = run("bd_loads")
    assert "graph" not in r and not (out / "prep" / "select" / bgr.GRAPH_JSON).exists()
    assert "graph" not in json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))


def test_graph_failed_structured_warning(tmp_path):
    """통합 v0.17.0(§12 BG-X-6): 분류 실패(graph.enabled false = DISABLED) → 준비 계속, prep/input.json warnings 에
    {code: GRAPH_FAILED, message, detail} 1개 + graph.code(옛 문자열 'GRAPH_FAILED: code=…' 없음), 작업 경고 줄은 detail=."""
    mesh = esl_mesh(cf.load_fixture("h5"))
    doe = _study(tmp_path, mesh, select_schema=2)
    doe["cfg"]["bead_doe"]["select"] = {"graph": {"enabled": False}}
    out = tmp_path / "_doe" / "G1"

    def run(stage):
        return stg.run_stage({"stage": stage, "out": str(out), "doe": doe}, lambda s: None)
    run("bd_input")
    r = run("bd_loads")
    inp = json.loads((out / "prep" / "input.json").read_text(encoding="utf-8"))
    assert inp["graph"]["ok"] is False and inp["graph"]["code"] == "DISABLED" and "warnings" not in inp["graph"]
    gw = [w for w in inp["warnings"] if isinstance(w, dict) and w.get("code") == "GRAPH_FAILED"]
    assert len(gw) == 1 and gw[0]["detail"] == "DISABLED" and set(gw[0]) == {"code", "message", "detail"}
    assert "DISABLED" in gw[0]["message"]
    assert not any(isinstance(w, str) and w.startswith("GRAPH_FAILED") for w in inp["warnings"])
    assert "GRAPH_FAILED: detail=DISABLED" in r["warnings"]
    assert not (out / "prep" / "select" / bgr.GRAPH_JSON).exists()
