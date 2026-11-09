"""V-BG-5 H6 morph recipes (a)-(g): no inversion, outside 0, achieved exact, islands rigid, fixed held, D6 boss follows,
shared child stays (BG_SHARED_CHILD), descendants rigid, corner guard."""
import pytest

from beadgraph.testing import conformance as c


@pytest.mark.parametrize("key", list("abcdefg"))
def test_recipe(key):
    g, lab, _ = c.classified("h6")
    fx = c.load_fixture("h6")
    r = c.run_recipe(g, lab, fx, c.h6_recipes(g, lab, fx)[key])
    assert c.check_h6_morph(key, r, g, lab, fx) == []


def test_linear_and_frozen_ramp():
    """V-BG-8 (package part): at ΔD_ext the linear basis equals a direct computation with the ramp set for that ΔD."""
    import numpy as np

    from beadgraph import basis, morph
    g, lab, _ = c.classified("h6")
    fx = c.load_fixture("h6")
    seg = c.h6_recipes(g, lab, fx)["b"][0][2]
    b = [{"name": "v", "kind": "D", "segs": seg, "hold": 1}]
    B = basis(g, lab, fx["x0"], b, {"v": [5.6, 10.4]}, fixed=fx["fixed"], elems=fx["conn"])
    Bd = basis(g, lab, fx["x0"], b, {"v": [8.0 - 2.4, 8.0 + 2.4]}, fixed=fx["fixed"], elems=fx["conn"])
    for v in (10.4, 5.6, 9.0):
        x1 = morph(fx["x0"], B, {"v": v})
        x2 = morph(fx["x0"], Bd, {"v": v})
        assert np.abs(x1 - x2).max() <= 1e-9
    assert abs(B[0]["info"]["ramp_mm"] - max(3 * 2.4, 3 * g["frame"]["h_mm"])) < 1e-9
