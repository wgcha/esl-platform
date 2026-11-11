"""V-BG-9 (esl part) edits / stale / anchors, V-BG-10 auto seed (H6), V-BG-11 schema 2 elems beads = schema 1 bytes."""
import hashlib

import numpy as np
import pytest
from _bg_util import CFG, bgr, bs, prepared, seg_x

from esl.errors import EslError


@pytest.fixture(scope="module")
def h6():
    return prepared("h6")


def _codes(exc):
    return exc.value.code


def test_auto_seed_h6(h6):
    mesh, g, lab, fixed, _d = h6
    sel, sym, warns = bgr.auto_seed(g, lab, CFG)
    norm, sha = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    segs = {s["id"]: s for s in g["segments"]}
    groups = [[bgr._bg().resolve(g, lab, x) for x in b["segs"]] for b in norm["beads"]]
    sides = sorted(segs[gr[0]]["side"] for gr in groups if segs[gr[0]]["side"])
    assert sides == ["bottom", "left", "right", "top"]                      # ring sides, one bead each
    bottom = [gr for gr in groups if segs[gr[0]]["side"] == "bottom"][0]
    assert len(bottom) == 3
    legs = [gr for gr in groups if segs[gr[0]]["type"] == "leg"]
    assert len(legs) == 4 and all(len(gr) == 1 for gr in legs)              # 2 legs + 2 comb teeth
    chans = [gr for gr in groups if any(segs[s]["type"] == "channel" for s in gr)]
    assert len(chans) == 2 and all(sorted(segs[s]["type"] for s in gr) == ["channel", "flare"] for gr in chans)
    plateau = [gr for gr in groups if segs[gr[0]]["type"] == "plateau"]
    assert len(plateau) == 1
    assert all(segs[s]["type"] not in ("corner", "base") for gr in groups for s in gr)
    assert norm["ties"] == [] and len(norm["beads"]) <= CFG["select"]["max_beads"]
    ch = sorted(chans, key=lambda gr: seg_x(mesh, lab, gr[0]))
    a1 = min(segs[s]["anchor"] for s in ch[0] if segs[s]["type"] == "channel")
    a2 = min(segs[s]["anchor"] for s in ch[1] if segs[s]["type"] == "channel")
    assert sorted([a1, a2]) in [sorted(p) for p in sym]
    sel2, _sym, _w = bgr.auto_seed(g, lab, CFG)
    assert bs.canonical_json(bs.normalize(sel2, CFG, mesh=mesh, graph=g, labels=lab)[0]) == bs.canonical_json(norm)
    manual = {"schema_version": 2, "graph": {"sha256": norm["graph"]["sha256"], "rules": 1},
              "beads": [{"id": b["id"], "segs": list(reversed(b["segs"])), "src": "graph", "name": b["name"]}
                        for b in norm["beads"]]}
    assert bs.normalize(manual, CFG, mesh=mesh, graph=g, labels=lab)[1] == sha     # seed save sha == manual sha
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed)
    tab = bs.params_table(D, CFG)
    pl = [r for r in tab if r["bead"] == norm["beads"][[i for i, gr in enumerate(groups) if gr == plateau[0]][0]]["id"]]
    assert [r["type"] for r in pl] == ["D"]                                  # plateau: D only


def test_stale_unknown_and_edits(h6):
    mesh, g, lab, _fixed, _d = h6
    ch = [s for s in g["segments"] if s["type"] == "channel"][0]
    fl = [s for s in g["segments"] if s["type"] == "flare" and s["floor"] == ch["floor"]][0]
    sha = bgr.graph_sha_of(g)
    base = {"schema_version": 2, "graph": {"sha256": sha, "rules": 1}, "beads": [
        {"id": "b1", "src": "graph", "segs": [{"anchor": ch["anchor"]}]}]}
    with pytest.raises(EslError) as e:
        bs.normalize(dict(base, graph={"sha256": "0" * 64, "rules": 1}), CFG, mesh=mesh, graph=g, labels=lab)
    assert _codes(e) == "BG_GRAPH_STALE" and e.value.extra["current"] == sha
    with pytest.raises(EslError) as e:
        bs.normalize(dict(base, beads=[{"id": "b1", "src": "graph", "segs": [{"anchor": 0}]}]), CFG, mesh=mesh,
                     graph=g, labels=lab)                                      # element 0 = base flange
    assert _codes(e) == "BG_SEG_UNKNOWN"
    pocket = [s for s in g["segments"] if s["type"] == "pocket"][0]
    with pytest.raises(EslError) as e:
        bs.normalize(dict(base, beads=[{"id": "b1", "src": "graph", "segs": [{"anchor": ch["anchor"]},
                                                                             {"anchor": pocket["anchor"]}]}]),
                     CFG, mesh=mesh, graph=g, labels=lab)
    assert _codes(e) == "BG_GROUP_NOT_CONNECTED"
    # merge channel + flare (Y zone absorbed) -> one segment, bytes stable
    ed = {"merge": [[{"anchor": fl["anchor"]}, {"anchor": ch["anchor"]}]]}
    sel = dict(base, graph={"sha256": sha, "rules": 1, "edits": ed})
    n1, s1 = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    n2, s2 = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    assert s1 == s2 and n1["graph"]["edits"]["merge"] == [[{"anchor": min(ch["anchor"], fl["anchor"])},
                                                           {"anchor": max(ch["anchor"], fl["anchor"])}]]
    D = bgr.derive_obj_v2(mesh, n1, CFG, g, lab)
    assert len(D.beads[0].seg_ids) == 1
    with pytest.raises(EslError) as e:
        bs.normalize(dict(base, graph={"sha256": sha, "rules": 1, "edits": {"merge": [[{"anchor": ch["anchor"]}]]}}),
                     CFG, mesh=mesh, graph=g, labels=lab)
    assert _codes(e) == "BG_EDIT_INVALID"
    # emboss island -> bead: a new D variable
    emb = [i for i in g["islands"] if 30 < i["size_mm"] < 45 and not i["lance"] and not i["straddle"]][0]
    ed2 = {"toggle": [{"anchor": emb["anchor"], "as": "bead"}]}
    sel2 = {"schema_version": 2, "graph": {"sha256": sha, "rules": 1, "edits": ed2},
            "beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": emb["anchor"]}]}]}
    n3, _ = bs.normalize(sel2, CFG, mesh=mesh, graph=g, labels=lab)
    D3 = bgr.derive_obj_v2(mesh, n3, CFG, g, lab)
    assert [r["type"] for r in bs.params_table(D3, CFG)] == ["D"]
    # channel -> island: rigid, the channel can no longer be selected
    sel3 = {"schema_version": 2, "graph": {"sha256": sha, "rules": 1,
                                           "edits": {"toggle": [{"anchor": ch["anchor"], "as": "island"}]}},
            "beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": ch["anchor"]}]}]}
    with pytest.raises(EslError) as e:
        bs.normalize(sel3, CFG, mesh=mesh, graph=g, labels=lab)
    assert _codes(e) == "BG_SEG_UNKNOWN"


def test_ties(h6):
    mesh, g, lab, fixed, _d = h6
    sha = bgr.graph_sha_of(g)
    chans = sorted([s for s in g["segments"] if s["type"] == "channel"], key=lambda s: seg_x(mesh, lab, s["id"]))
    beads = [{"id": f"b{k + 1}", "src": "graph", "segs": [{"anchor": c["anchor"]}]} for k, c in enumerate(chans)]
    sel = {"schema_version": 2, "graph": {"sha256": sha, "rules": 1}, "beads": beads, "ties": [["b2", "b1"]]}
    norm, _ = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    assert norm["ties"] == [["b1", "b2"]]
    D = bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed)
    tab = bs.params_table(D, CFG)
    assert [r["name"] for r in tab] == ["B1_D", "B1_W"] and tab[0]["group_members"] == ["B1_D", "B2_D"]
    pocket = [s for s in g["segments"] if s["type"] == "pocket"][0]
    bad = {"schema_version": 2, "graph": {"sha256": sha, "rules": 1}, "ties": [["b1", "b2"]],
           "beads": [beads[0], {"id": "b2", "src": "graph", "segs": [{"anchor": pocket["anchor"]}]}]}
    with pytest.raises(EslError) as e:
        bs.normalize(bad, CFG, mesh=mesh, graph=g, labels=lab)
    assert e.value.code == "BG_TIE_NOMINAL"


def test_schema2_elems_equals_schema1():
    """V-BG-11: a schema 1 bead body as src elems in schema 2 -> same derive / basis bytes (no 40..60 mm island)."""
    import synth_bead as sb
    g0 = sb.generate()
    sel1 = sb.selection(g0)
    mesh = g0["mesh"]
    import tempfile
    d = tempfile.mkdtemp(prefix="bg_sb_")
    st = bgr.prep_graph(mesh, g0.get("fixed_ids", ()), CFG, d)
    assert st["ok"], st
    gr, lab = bgr.load_graph(d)
    n1 = bs.normalize_input(sel1, CFG)
    D1 = bs.derive_obj(mesh, n1, CFG, fixed_node_ids=g0.get("fixed_ids", ()))
    B1 = bs.basis(mesh, D1, CFG)
    sel2 = {"schema_version": 2, "feature_angle_deg": sel1.get("feature_angle_deg"),
            "graph": {"sha256": bgr.graph_sha_of(gr), "rules": 1},
            "beads": [dict(b, src="elems") for b in sel1["beads"]], "fixed_user": sel1.get("fixed_user"),
            "exclude": sel1.get("exclude")}
    n2, _ = bs.normalize(sel2, CFG, mesh=mesh, graph=gr, labels=lab)
    D2 = bgr.derive_obj_v2(mesh, n2, CFG, gr, lab, fixed_node_ids=g0.get("fixed_ids", ()))
    B2 = bs.basis(mesh, D2, CFG)
    assert hashlib.sha256(bs.basis_bin(B1)).hexdigest() == hashlib.sha256(bs.basis_bin(B2)).hexdigest()
    s1 = D1.summary(with_figures=False)["beads"]
    s2 = [{k: v for k, v in b.items() if k != "src"} for b in D2.summary(with_figures=False)["beads"]]
    assert s1 == s2
    assert bs.params_table(D1, CFG) == bs.params_table(D2, CFG)


def test_schema1_untouched():
    """schema 1 normalize refuses nothing new and never needs a graph; schema 2 without a graph is refused."""
    import synth_bead as sb
    g0 = sb.generate()
    n1, sha = bs.normalize(sb.selection(g0), CFG)
    assert n1["schema_version"] == 1 and "src" not in n1["beads"][0]
    with pytest.raises(EslError) as e:
        bs.normalize({"schema_version": 2, "beads": []}, CFG)
    assert e.value.code == "GRAPH_NOT_AVAILABLE"


def test_graph_bin_layout(h6):
    mesh, g, lab, _f, d = h6
    import os
    blob = open(os.path.join(d, bgr.GRAPH_BIN), "rb").read()
    arr = bgr.read_graph_bin(blob)
    assert list(arr) == list(bgr.GRAPH_BIN_ARRAYS)
    for k, v in arr.items():
        assert v.size == mesh["elem_id"].size and np.array_equal(v, lab[k])


def test_backend_derive_api(h6):
    """bead_select.derive (backend API) dispatches schema 2 -> SelectionDerived + graph block (§6.1)."""
    mesh, g, lab, fixed, _d = h6
    sel, _sym, _w = bgr.auto_seed(g, lab, CFG)
    norm, _ = bs.normalize(sel, CFG, mesh=mesh, graph=g, labels=lab)
    doc = bs.derive(mesh, norm, CFG, fixed_scan=fixed, graph=g, labels=lab)
    assert doc["graph_algo"] == bgr.GRAPH_ALGO and doc["schema_version"] == 2
    gb = doc["graph"]
    assert set(gb) >= {"sha256", "graph_algo", "edits_applied", "segments", "junction_zones", "beads", "sym_pairs"}
    assert len(gb["beads"]) == len(norm["beads"]) and all(b["src"] == "graph" for b in doc["beads"])
    with pytest.raises(EslError) as e:
        bs.derive(mesh, norm, CFG)
    assert e.value.code == "GRAPH_NOT_AVAILABLE"


def test_backend_signatures(h6):
    """Backend calls normalize_v2(sel, graph, cfg, mesh=, labels=) and derive_v2(mesh, norm, cfg, graph, labels,
    frame=, fixed_scan=, bead=) -> dict with params + param_beads."""
    mesh, g, lab, fixed, _d = h6
    sel, _sym, _w = bgr.auto_seed(g, lab, CFG)
    norm, sha = bgr.normalize_v2(sel, g, CFG, mesh=mesh, labels=lab)
    doc = bgr.derive_v2(mesh, norm, CFG, g, lab, frame=None, fixed_scan=fixed, bead=None)
    assert isinstance(doc, dict) and doc["params"] and len(doc["param_beads"]) == len(norm["beads"])
    assert {r["name"] for r in doc["params"]} == {r["name"] for r in bs.params_table(
        bgr.derive_obj_v2(mesh, norm, CFG, g, lab, fixed_node_ids=fixed), CFG)}


def test_graph_failed_elems_only():
    """GRAPH_FAILED (graph None): schema 2 with elems beads only normalizes / derives; a graph bead is refused."""
    import synth_bead as sb
    g0 = sb.generate()
    sel1 = sb.selection(g0)
    sel2 = {"schema_version": 2, "beads": [dict(b, src="elems") for b in sel1["beads"]]}
    norm, _ = bgr.normalize_v2(sel2, None, CFG, mesh=g0["mesh"])
    assert "graph" not in norm
    doc = bgr.derive_v2(g0["mesh"], norm, CFG, None, None, fixed_scan=g0.get("fixed_ids", ()))
    assert doc["params"] and all(b["src"] == "elems" for b in doc["beads"])
    with pytest.raises(EslError) as e:
        bgr.normalize_v2({"schema_version": 2, "beads": [{"id": "b1", "src": "graph", "segs": [{"anchor": 1}]}]},
                         None, CFG)
    assert e.value.code == "BG_SEG_UNKNOWN"


def test_toggle_by_ui_anchor(h6):
    """Frontend toggles with a segment / island anchor element id -> the core resolves it to the floor."""
    mesh, g, lab, _fixed, _d = h6
    ch = [s for s in g["segments"] if s["type"] == "channel"][0]
    wall_el = int(np.flatnonzero((lab["segment"] == ch["id"]) & (lab["cls"] == 1))[0])
    for a in (ch["anchor"], wall_el):
        g2, l2 = bgr.edited_graph(g, lab, {"toggle": [{"anchor": a, "as": "island"}]}, mesh)
        assert not [s for s in g2["segments"] if s["floor"] == ch["floor"]]
    boss = [i for i in g["islands"] if len(i["floors"]) >= 2 and not i["lance"]]
    isl = boss[0] if boss else [i for i in g["islands"] if not i["lance"]][0]
    inner = int(np.flatnonzero((lab["island"] == isl["id"]) & (lab["cls"] == 2))[-1])
    g3, _l3 = bgr.edited_graph(g, lab, {"toggle": [{"anchor": inner, "as": "bead"}]}, mesh)
    new = [s for s in g3["segments"] if s.get("toggled") == "bead"]
    root = sorted(isl["floors"], key=lambda x: (g["floors"][x]["tier"], x))[0]
    assert len(new) == 1 and new[0]["floor"] == root
