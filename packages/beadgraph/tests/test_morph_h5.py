"""V-BG-6 H5: V1 D ±2, W +4, D default-range end -> ring / ring∩V1 / V2 do not move, no inversion, exact depth."""
from beadgraph.testing import conformance as c


def test_h5_morph():
    r = c.h5_morph()
    assert r.pop("bad") == []
    for k, row in r.items():
        assert row["ring_mm"] == 0.0 and row["ring_v1_mm"] == 0.0 and row["v2_mm"] == 0.0, k
