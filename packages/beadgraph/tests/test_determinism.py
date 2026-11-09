"""V-BG-3 same input twice -> graph.json / labels bytes identical and equal to expected.json."""
import pytest

from beadgraph.testing import conformance as c


@pytest.mark.parametrize("name", ["h5", "h6"])
def test_determinism(name):
    d = c.determinism(name)
    exp = c.expected()[name]
    assert d["same_graph"] and d["same_labels"]
    assert d["graph_sha"] == exp["graph_sha256"]
    assert d["labels_sha"] == exp["labels_sha256"]


def test_cfg_changes_sha():
    from beadgraph import classify
    fx = c.load_fixture("h5")
    g1, _ = classify(fx["x0"], fx["conn"], fx["fixed"])
    g2, _ = classify(fx["x0"], fx["conn"], fx["fixed"], {"bead": {"absorb_len_mm": 61.0}})
    assert g1["cfg_sha256"] != g2["cfg_sha256"]
