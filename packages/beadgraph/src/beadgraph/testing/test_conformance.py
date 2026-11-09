"""pytest --pyargs beadgraph.testing — the selftest as pytest cases (no gmsh)."""
import pytest

from beadgraph.testing import conformance as c


def test_h6_classification():
    assert c.check_h6(c.h6_metrics()) == []


def test_h5_classification():
    assert c.check_h5(c.h5_metrics()) == []


@pytest.mark.parametrize("name", ["h5", "h6"])
def test_determinism(name):
    d = c.determinism(name)
    exp = c.expected()[name]
    assert d["same_graph"] and d["same_labels"]
    assert d["graph_sha"] == exp["graph_sha256"] and d["labels_sha"] == exp["labels_sha256"]


@pytest.mark.parametrize("name", ["h5", "h6"])
def test_invariance(name):
    r = c.invariance(name)
    assert r["permuted"] == [] and r["rigid"] == []


@pytest.mark.parametrize("key", list("abcdefg"))
def test_h6_morph(key):
    g, lab, _ = c.classified("h6")
    fx = c.load_fixture("h6")
    r = c.run_recipe(g, lab, fx, c.h6_recipes(g, lab, fx)[key])
    assert c.check_h6_morph(key, r, g, lab, fx) == []


def test_h5_morph():
    assert c.h5_morph()["bad"] == []


def test_purity():
    assert c.purity() == []
    assert c.fixtures_size() <= c.MAX_FIXTURE_BYTES
