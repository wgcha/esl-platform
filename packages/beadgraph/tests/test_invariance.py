"""V-BG-4 (a) in-memory, (c) renumbering / shuffling / node cycling / reversal, (d) rigid transform."""
import pytest

from beadgraph.testing import conformance as c


@pytest.mark.parametrize("name", ["h5", "h6"])
def test_invariance(name):
    r = c.invariance(name)
    assert r["permuted"] == [], r
    assert r["rigid"] == [], r
    assert r["basis_err"] <= 1e-9
