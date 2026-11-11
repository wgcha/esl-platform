"""V-BG-1 H6 classification accuracy (frozen fixture, ground truth)."""
from beadgraph.testing import conformance as c


def test_h6_accuracy():
    r = c.h6_metrics()
    assert c.check_h6(r) == []
    assert r["class_acc"] >= 0.99 and r["wall_owner_acc"] >= 0.985 and r["segment_elem_acc"] >= 0.985
    assert r["junctions"]["types"] == {"T": 4, "L": 2, "W": 4, "Y": 2, "step": 4}


def test_h6_absorption_and_sides():
    g, lab, _ = c.classified("h6")
    reasons = sorted(z["reason"] for z in g["junction_zones"])
    assert reasons.count("corner") == 2 and reasons.count("short_strip") == 2 and "spur" in reasons
    sides = {}
    for s in g["segments"]:
        if s["side"]:
            sides.setdefault(s["side"], []).append(s["id"])
    assert sorted(sides) == ["bottom", "left", "right", "top"]
    assert len(sides["bottom"]) == 3                     # strip b + c + d through the comb T junctions (BG-D-13)
    for s in g["segments"]:
        assert s["type"] not in ("corner",)              # corners are junction zones (D7)
    assert all(lab["segment"][lab["junction_zone"] >= 0] == -1)


def test_h6_schema_and_labels():
    from beadgraph import LABEL_KEYS, validate
    g, lab, _ = c.classified("h6")
    validate(g)
    assert sorted(lab) == sorted(LABEL_KEYS)
    assert all(v.dtype.str == "<i4" and v.size == g["input"]["n_elems"] for v in lab.values())
    for s in g["segments"]:
        assert lab["segment"][s["anchor"]] == s["id"] and s["anchor"] == int((lab["segment"] == s["id"]).nonzero()[0][0])
