"""beadgraph — shared bead-network classifier + segment morph for shell meshes (esl-platform + physicsai-platform).

Contract: esl-platform docs/contracts/esl_beadgraph.md (BEADGRAPH, v0.17.0) §8. numpy / scipy only, no platform
imports, no file / network I/O (fixtures in ``beadgraph.testing`` excepted), no global state, no randomness.

Stable API (changing a signature or the schema major number = MAJOR):
    classify(nodes, elems, fixed=None, cfg=None) -> (graph, labels)
    apply_edits(graph, labels, edits, nodes=None, elems=None) -> (graph, labels)
    resolve(graph, labels, ref) -> int
    basis(graph, labels, nodes, beads, ranges, cfg=None, fixed=None) -> list[dict]
    morph(nodes, basis, values) -> ndarray
    check(graph, labels, nodes, x, basis, values, cfg=None) -> dict
    validate(graph) -> None
"""
from __future__ import annotations

__version__ = "1.1.0"
SCHEMA = "beadgraph/1"
RULES = 1                 # classification output rules (graph.json bytes) — bump = MINOR + expected.json update
MORPH_RULES = 2           # morph basis numerics — bump = MINOR, esl recomputes bases

# submodules first: the API functions below share names with two submodules (classify, morph) and must win the
# package attribute (a later ``from .morph import x`` does not rebind it once the module is loaded)
from . import checks as _checks  # noqa: E402,F401
from . import classify as _classify_mod  # noqa: E402,F401
from . import morph as _morph_mod  # noqa: E402,F401
from .classify import CLS, LABEL_KEYS, BeadgraphError  # noqa: E402
from .defaults import DEFAULTS  # noqa: E402

__all__ = ["classify", "apply_edits", "resolve", "basis", "morph", "check", "validate", "graph_bytes", "DEFAULTS",
           "SCHEMA", "RULES", "MORPH_RULES", "__version__", "BeadgraphError", "CLS", "LABEL_KEYS"]


def _mesh_input(nodes, elems, fixed=None):
    """validate the shell mesh at the API boundary -> (X float64 (n,3), C int64 (m,3|4), fixed int64 | None).
    BeadgraphError("INVALID_INPUT", detail) for an empty / non-finite / wrongly shaped / bad-index mesh."""
    import numpy as np
    try:
        X = np.asarray(nodes, dtype=np.float64)
        C = np.asarray(elems)
    except (TypeError, ValueError) as exc:
        raise BeadgraphError("INVALID_INPUT", f"BAD_ARRAY: {exc}") from exc
    if X.ndim != 2 or X.shape[1] != 3:
        raise BeadgraphError("INVALID_INPUT", f"BAD_SHAPE: nodes must be (n, 3), got {X.shape}")
    if C.ndim != 2 or C.shape[1] not in (3, 4):
        raise BeadgraphError("INVALID_INPUT", f"BAD_SHAPE: elems must be (m, 3|4), got {C.shape}")
    if X.shape[0] == 0 or C.shape[0] == 0:
        raise BeadgraphError("INVALID_INPUT", f"EMPTY_MESH: {X.shape[0]} nodes, {C.shape[0]} elements")
    if not np.issubdtype(C.dtype, np.integer):
        if not np.all(np.isfinite(C)) or np.any(C != np.round(C)):
            raise BeadgraphError("INVALID_INPUT", "BAD_INDEX: element node indices must be integers")
    C = C.astype(np.int64)
    bad = ~np.isfinite(X).all(axis=1)
    if bad.any():
        raise BeadgraphError("INVALID_INPUT", f"NON_FINITE: {int(bad.sum())} node(s) with NaN/inf coordinates "
                                              f"(first index {int(np.flatnonzero(bad)[0])})")
    lo = C[:, :3].min()
    if lo < 0 or C.max() >= X.shape[0] or (C.shape[1] == 4 and C[:, 3].min() < -1):
        raise BeadgraphError("INVALID_INPUT", f"BAD_INDEX: element node index outside [0, {X.shape[0] - 1}] "
                                              "(4th = -1 for triangles)")
    F = None
    if fixed is not None:
        try:
            F = np.asarray(fixed, dtype=np.int64).ravel()
        except (TypeError, ValueError) as exc:
            raise BeadgraphError("INVALID_INPUT", f"BAD_FIXED: {exc}") from exc
        if F.size and (F.min() < 0 or F.max() >= X.shape[0]):
            raise BeadgraphError("INVALID_INPUT", f"BAD_FIXED: fixed node index outside [0, {X.shape[0] - 1}]")
    return X, C, F


def _guard(fn=None, *, passthrough=()):
    """public API boundary (contract §8.2): BeadgraphError (and its EditError subclass) pass through, as do the
    documented ``passthrough`` types (KeyError = unknown anchor for resolve / apply_edits); any other exception raised
    inside the package (IndexError, LinAlgError, ValueError, ...) becomes BeadgraphError("ERROR", "<type>: <message>")
    chained to the original."""
    import functools

    def deco(f):
        @functools.wraps(f)
        def run(*a, **kw):
            try:
                return f(*a, **kw)
            except (BeadgraphError, *passthrough):
                raise
            except Exception as exc:  # noqa: BLE001 — the boundary converts every internal failure
                raise BeadgraphError("ERROR", f"{type(exc).__name__}: {exc}"[:500]) from exc
        return run
    return deco(fn) if fn is not None else deco


@_guard
def classify(nodes, elems, fixed=None, cfg=None):
    """shell mesh (nodes (n,3) mm, elems (m,4) 0-based, tri 4th = -1, optional fixed node indices) -> (graph, labels).
    graph = ``beadgraph/1`` JSON dict (no per-element arrays), labels = {cls, floor, segment, transition, island,
    junction_zone, tier} int32 arrays in input element order (-1 = none). Raises BeadgraphError(code, detail)."""
    from .classify import classify_full
    X, C, F = _mesh_input(nodes, elems, fixed)
    g, lab, _aux = classify_full(X, C, F, cfg)
    return g, lab


@_guard(passthrough=(KeyError,))
def apply_edits(graph, labels, edits, nodes=None, elems=None):
    from .edits import apply
    if nodes is not None and elems is not None:
        nodes, elems, _f = _mesh_input(nodes, elems)
    return apply(graph, labels, edits, nodes=nodes, elems=elems)


@_guard(passthrough=(KeyError,))
def resolve(graph, labels, ref):
    """{anchor}|{network} -> id; KeyError when unknown (contract §8.2), other failures BeadgraphError."""
    from .edits import resolve as _r
    return _r(graph, labels, ref)


@_guard
def basis(graph, labels, nodes, beads, ranges, cfg=None, fixed=None, elems=None):
    from .morph import basis as _b
    if elems is None:
        raise BeadgraphError("INVALID_INPUT", "basis(): elems (connectivity) is required")
    nodes, elems, fixed = _mesh_input(nodes, elems, fixed)
    return _b(graph, labels, nodes, beads, ranges, cfg=cfg, fixed=fixed, elems=elems)


@_guard
def morph(nodes, basis, values):
    from .morph import morph as _m
    return _m(nodes, basis, values)


@_guard
def check(graph, labels, nodes, x, basis, values, cfg=None, elems=None):
    from .checks import check as _c
    return _c(graph, labels, nodes, x, basis, values, cfg=cfg, elems=elems)


def validate(graph):
    from .schema import validate as _v
    return _v(graph)


def graph_bytes(graph) -> bytes:
    """canonical graph.json bytes (sorted keys, compact, ASCII) — BG-D-12 determinism."""
    from ._util import canonical_bytes
    return canonical_bytes(graph)
