"""shared helpers for the v0.17.0 BEADGRAPH esl tests (frozen package fixtures -> esl mesh dicts)."""
from __future__ import annotations

import os
import sys
from functools import lru_cache

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "packages", "beadgraph", "src")
if PKG not in sys.path:
    sys.path.insert(0, PKG)

from beadgraph.testing import conformance as cf  # noqa: E402

from esl.doe import bead_graph as bgr  # noqa: E402
from esl.doe import bead_select as bs  # noqa: E402,F401  (re-exported to the tests)
from esl.doe import settings  # noqa: E402

CFG = settings({"bead_doe": {"enabled": True}})


def esl_mesh(fx: dict) -> dict:
    n, m = fx["x0"].shape[0], fx["conn"].shape[0]
    C = np.asarray(fx["conn"], np.int64)
    return {"node_id": np.arange(1, n + 1, dtype=np.int64), "x0": np.asarray(fx["x0"], np.float64),
            "elem_id": np.arange(1, m + 1, dtype=np.int64), "elem_type": np.where(C[:, 3] >= 0, 4, 3).astype(np.int8),
            "conn": C, "elem_pid": np.ones(m, np.int64), "elem_mid": np.ones(m, np.int64), "thickness": np.ones(m),
            "E": np.full(m, 205000.0),
            "nu": np.full(m, 0.3)}


@lru_cache(maxsize=4)
def prepared(name: str):
    """(mesh, graph, labels, fixed node ids) — classification through ``bead_graph.prep_graph`` into a temp dir."""
    import tempfile
    fx = cf.load_fixture(name)
    mesh = esl_mesh(fx)
    d = tempfile.mkdtemp(prefix=f"bg_{name}_")
    st = bgr.prep_graph(mesh, fx["fixed"] + 1, CFG, d)
    assert st["ok"], st
    g, lab = bgr.load_graph(d)
    return mesh, g, lab, tuple((fx["fixed"] + 1).tolist()), d


def seg_x(mesh, lab, sid):
    C = mesh["conn"]
    nd = np.unique(C[lab["segment"] == sid][:, :3])
    return float(mesh["x0"][nd, 0].mean())
