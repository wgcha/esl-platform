"""V-BG-14 (package part): imports = stdlib / numpy / scipy only, schema validation, fixtures <= 6 MB, selftest CLI."""
import subprocess
import sys

import pytest

from beadgraph import validate
from beadgraph.testing import conformance as c


def test_imports():
    assert c.purity() == []


def test_schema():
    g, _lab, _ = c.classified("h5")
    validate(g)
    with pytest.raises(ValueError):
        validate(dict(g, schema="beadgraph/2"))
    with pytest.raises(ValueError):
        validate({k: v for k, v in g.items() if k != "segments"})


def test_fixture_size():
    assert c.fixtures_size() <= c.MAX_FIXTURE_BYTES


def test_errors():
    import numpy as np

    from beadgraph import BeadgraphError, classify
    fx = c.load_fixture("h5")
    with pytest.raises(BeadgraphError) as e:
        classify(fx["x0"], fx["conn"], None, {"limits": {"max_elems": 100}})
    assert e.value.code == "TOO_LARGE"
    X = np.array([[0, 0, 0], [1, 0, 1], [0, 1, 1]], float)
    with pytest.raises(BeadgraphError) as e:
        classify(X, np.array([[0, 1, 2, -1]]), None, {"feature_angle_deg": 1.0})
    assert e.value.code == "NO_FLOOR"


def test_generator_reproduces_fixture():
    gmsh = pytest.importorskip("gmsh")
    pytest.importorskip("shapely")
    if gmsh.__version__ != "4.15.2":
        pytest.skip(f"gmsh {gmsh.__version__} != lock 4.15.2")
    from beadgraph.testing import synth_h5
    import numpy as np
    m = synth_h5.build(3.0)
    fx = c.load_fixture("h5")
    assert np.array_equal(m["x0"], fx["x0"]) and np.array_equal(m["conn"].astype(np.int32), fx["conn"])


@pytest.mark.slow
def test_selftest_cli():
    import os
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(os.path.dirname(__file__), "..", "src"),
                                                       os.environ.get("PYTHONPATH", "")]))
    r = subprocess.run([sys.executable, "-m", "beadgraph", "selftest", "--quick"], capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0, r.stdout + r.stderr
