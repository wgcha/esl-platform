"""Verifier fix v0.17.0 (contract §8.2): the public API raises BeadgraphError(code, detail) — never a raw IndexError /
LinAlgError / ValueError — for empty, non-finite or bad-index meshes and for internal failures.

Probe origin: vprobe/edge.py (empty -> IndexError, NaN coordinate -> LinAlgError, bad index -> ValueError)."""
import numpy as np
import pytest

import beadgraph as bg
from beadgraph import BeadgraphError
from beadgraph.testing import conformance as c

QUAD = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.0]])


def _grid(n=20, h=2.0):
    xs = np.arange(n + 1) * h
    X, Y = np.meshgrid(xs, xs, indexing="ij")
    nodes = np.c_[X.ravel(), Y.ravel(), np.zeros(X.size)]
    idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)
    E = np.c_[idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()]
    return nodes, E


@pytest.mark.parametrize("nodes,elems,detail", [
    (np.zeros((0, 3)), np.zeros((0, 4), np.int64), "EMPTY_MESH"),
    (QUAD, np.zeros((0, 4), np.int64), "EMPTY_MESH"),
    (np.zeros((4, 2)), np.array([[0, 1, 2, 3]]), "BAD_SHAPE"),
    (QUAD, np.array([0, 1, 2, 3]), "BAD_SHAPE"),
    (np.zeros((4, 3)), np.array([[0, 1, 2, 9]]), "BAD_INDEX"),
    (np.zeros((4, 3)), np.array([[0, -1, 2, 3]]), "BAD_INDEX"),
    (np.zeros((4, 3)), np.array([[0.5, 1, 2, 3]]), "BAD_INDEX"),
])
def test_classify_invalid_input(nodes, elems, detail):
    with pytest.raises(BeadgraphError) as e:
        bg.classify(nodes, elems)
    assert type(e.value) is BeadgraphError and e.value.code == "INVALID_INPUT"
    assert str(e.value.detail).startswith(detail) and isinstance(e.value, ValueError)


def test_classify_nan_and_inf():
    for bad in (np.nan, np.inf):
        X, E = _grid()
        X[5, 2] = bad
        with pytest.raises(BeadgraphError) as e:
            bg.classify(X, E)
        assert e.value.code == "INVALID_INPUT" and e.value.detail.startswith("NON_FINITE") and "index 5" in e.value.detail


def test_classify_bad_fixed():
    X, E = _grid()
    with pytest.raises(BeadgraphError) as e:
        bg.classify(X, E, fixed=[X.shape[0] + 3])
    assert e.value.code == "INVALID_INPUT" and e.value.detail.startswith("BAD_FIXED")


def test_internal_failure_is_wrapped(monkeypatch):
    """an exception raised inside the package becomes BeadgraphError("ERROR") chained to the original."""
    import importlib
    cmod = importlib.import_module("beadgraph.classify")

    def boom(*a, **k):
        raise np.linalg.LinAlgError("Eigenvalues did not converge")
    monkeypatch.setattr(cmod, "floor_pieces", boom)
    X, E = _grid()
    with pytest.raises(BeadgraphError) as e:
        bg.classify(X, E)
    assert e.value.code == "ERROR" and e.value.detail.startswith("LinAlgError")
    assert isinstance(e.value.__cause__, np.linalg.LinAlgError)


def test_valid_mesh_still_classifies():
    X, E = _grid()
    g, lab = bg.classify(X, E)
    assert [s["type"] for s in g["segments"]] == ["base"] and lab["cls"].shape == (E.shape[0],)


@pytest.fixture(scope="module")
def h5():
    g, lab, _ = c.classified("h5")
    return g, lab, c.load_fixture("h5")


def test_basis_morph_check_errors(h5):
    g, lab, fx = h5
    X, C = fx["x0"], fx["conn"]
    seg = next(s for s in g["segments"] if s["type"] == "channel")["id"]
    b = [{"name": "v", "kind": "D", "segs": [seg], "hold": 1}]
    with pytest.raises(BeadgraphError) as e:
        bg.basis(g, lab, X, b, {"v": [5.0, 9.0]})                            # BG-X-4: elems required
    assert e.value.code == "INVALID_INPUT"
    Xn = X.copy()
    Xn[0, 0] = np.nan
    with pytest.raises(BeadgraphError) as e:
        bg.basis(g, lab, Xn, b, {"v": [5.0, 9.0]}, elems=C)
    assert e.value.code == "INVALID_INPUT" and e.value.detail.startswith("NON_FINITE")
    Cb = C.copy()
    Cb[0, 0] = X.shape[0] + 7
    with pytest.raises(BeadgraphError) as e:
        bg.basis(g, lab, X, b, {"v": [5.0, 9.0]}, elems=Cb)
    assert e.value.code == "INVALID_INPUT" and e.value.detail.startswith("BAD_INDEX")
    with pytest.raises(BeadgraphError) as e:
        bg.basis(g, lab, X, [{"name": "v", "kind": "D", "segs": [10 ** 6], "hold": 1}], {"v": [1, 2]}, elems=C)
    assert e.value.code == "ERROR"
    B = bg.basis(g, lab, X, b, {"v": [5.0, 9.0]}, elems=C)
    v = B[0]["nominal"] + 1.0
    with pytest.raises(BeadgraphError) as e:
        bg.morph(X[:10], B, {"v": v})                                       # basis rows beyond a short node array
    assert e.value.code == "ERROR" and e.value.detail.startswith("IndexError")
    with pytest.raises(BeadgraphError) as e:
        bg.check(g, lab, X, X[:10], B, {"v": v}, elems=C)
    assert e.value.code == "ERROR"


def test_edit_errors_keep_their_codes(h5):
    from beadgraph.edits import EditError
    g, lab, fx = h5
    with pytest.raises(KeyError):                                           # unknown anchor: documented KeyError
        bg.resolve(g, lab, {"anchor": -5})
    with pytest.raises(KeyError):
        bg.apply_edits(g, lab, {"toggle": [{"anchor": 10 ** 7, "as": "island"}]})
    with pytest.raises(EditError) as e:
        bg.apply_edits(g, lab, {"split": [{"anchor": g["segments"][1]["anchor"], "at": [0, 0]}]})
    assert e.value.code == "BG_EDIT_INVALID" and isinstance(e.value, BeadgraphError)
