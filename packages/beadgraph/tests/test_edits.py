"""V-BG-9 (package part) edits: toggle island -> bead (D variable), channel -> island (rigid, no variable), merge channel
+ flare (Y zone absorbed), split at the channel midpoint (2 segments + split zone), determinism, anchor resolution."""
import numpy as np
import pytest

import beadgraph as bg
from beadgraph.edits import EditError, sym_pairs
from beadgraph.testing import conformance as c


@pytest.fixture(scope="module")
def h6():
    g, lab, _ = c.classified("h6")
    return g, lab, c.load_fixture("h6")


def _ch1(g, lab, fx):
    ids = c.h6_recipes(g, lab, fx)["b"][0][2]
    return g["segments"][ids[0]], g["segments"][ids[1]]


def test_toggle_island_to_bead(h6):
    g, lab, fx = h6
    emb = [i for i in g["islands"] if 30 < i["size_mm"] < 45 and not i["lance"] and not i["straddle"]][0]
    g2, l2 = bg.apply_edits(g, lab, {"toggle": [{"anchor": emb["anchor"], "as": "bead"}]})
    bg.validate(g2)
    new = [s for s in g2["segments"] if s.get("toggled") == "bead"]
    assert len(new) == 1 and new[0]["D"] > 0 and len(g2["islands"]) == len(g["islands"]) - 1
    B = bg.basis(g2, l2, fx["x0"], [{"name": "t", "kind": "D", "segs": [new[0]["id"]], "hold": 1}],
                 {"t": [new[0]["D"] - 1, new[0]["D"] + 1]}, fixed=fx["fixed"], elems=fx["conn"])
    x = bg.morph(fx["x0"], B, {"t": new[0]["D"] + 1})
    r = bg.check(g2, l2, fx["x0"], x, B, {"t": new[0]["D"] + 1}, elems=fx["conn"])
    assert r["outside"]["max_mm"] <= 1e-9 and r["inverted"] == 0 and r["achieved"]["t"] <= 1e-6


def test_toggle_channel_to_island(h6):
    g, lab, fx = h6
    ch, fl = _ch1(g, lab, fx)
    g2, l2 = bg.apply_edits(g, lab, {"toggle": [{"anchor": ch["anchor"], "as": "island"}]})
    bg.validate(g2)
    assert not [s for s in g2["segments"] if s["floor"] == ch["floor"]]
    isl = [i for i in g2["islands"] if i.get("toggled") == "island"]
    assert len(isl) == 1 and (l2["island"] == isl[0]["id"]).sum() > ch["n_elems"]
    with pytest.raises(KeyError):
        bg.resolve(g2, l2, {"anchor": ch["anchor"]})        # BG_SEG_UNKNOWN for a saved selection


def test_merge_channel_flare(h6):
    g, lab, fx = h6
    ch, fl = _ch1(g, lab, fx)
    e = {"merge": [[{"anchor": ch["anchor"]}, {"anchor": fl["anchor"]}]]}
    g2, l2 = bg.apply_edits(g, lab, e)
    bg.validate(g2)
    assert len(g2["segments"]) == len(g["segments"]) - 1
    assert len(g2["junction_zones"]) == len(g["junction_zones"]) - 1          # the Y zone is absorbed
    assert bg.graph_bytes(g2) == bg.graph_bytes(bg.apply_edits(g, lab, e)[0])
    with pytest.raises(EditError):
        other = [s for s in g["segments"] if s["type"] == "pocket"][0]
        bg.apply_edits(g, lab, {"merge": [[{"anchor": ch["anchor"]}, {"anchor": other["anchor"]}]]})


def test_split_midpoint(h6):
    g, lab, fx = h6
    ch, _fl = _ch1(g, lab, fx)
    sk = np.asarray(ch["skeleton"])
    g2, l2 = bg.apply_edits(g, lab, {"split": [{"anchor": ch["anchor"], "at": sk[len(sk) // 2].tolist()}]},
                            fx["x0"], fx["conn"])
    bg.validate(g2)
    assert len(g2["segments"]) == len(g["segments"]) + 1
    assert [z["reason"] for z in g2["junction_zones"]].count("split") == 1
    with pytest.raises(EditError):
        bg.apply_edits(g, lab, {"split": [{"anchor": ch["anchor"], "at": sk[0].tolist()}]})


def test_sym_pairs(h6):
    g, lab, fx = h6
    ch1 = c.h6_recipes(g, lab, fx)["e"]
    a, b = ch1[0][2][0], ch1[1][2][0]
    assert sorted([a, b]) in [sorted(p) for p in sym_pairs(g, g["cfg"]["sym_tol_mm"])]


def test_resolve_network(h6):
    g, lab, _fx = h6
    top = [s for s in g["segments"] if s["side"] == "top"][0]
    n = bg.resolve(g, lab, {"network": top["anchor"]})
    assert g["networks"][n]["floor"] == top["floor"]
