"""V-BG-2 H5 classification: ring 4 sides + 2 vertical beads + 2 T, no ring-labelled wall on V1/V2, zones = 4 + 2."""
from beadgraph.testing import conformance as c


def test_h5():
    r = c.h5_metrics()
    assert c.check_h5(r) == []
    assert r["zone_reasons"] == {"junction": 6}


def test_h5_entry_width():
    g, lab, _ = c.classified("h5")
    v = [s for s in g["segments"] if s["type"] == "channel"]
    assert len(v) == 2 and all(abs(s["entry_width"] - 30.0) < 1e-3 for s in v)
    assert all(abs(s["D"] - 8.0) < 1e-3 for s in v)
