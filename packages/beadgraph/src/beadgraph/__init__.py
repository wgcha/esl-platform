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

__version__ = "1.0.0"
SCHEMA = "beadgraph/1"
RULES = 1                 # classification output rules (graph.json bytes) — bump = MINOR + expected.json update
MORPH_RULES = 1           # morph basis numerics — bump = MINOR, esl recomputes bases

# submodules first: the API functions below share names with two submodules (classify, morph) and must win the
# package attribute (a later ``from .morph import x`` does not rebind it once the module is loaded)
from . import checks as _checks  # noqa: E402,F401
from . import classify as _classify_mod  # noqa: E402,F401
from . import morph as _morph_mod  # noqa: E402,F401
from .classify import CLS, LABEL_KEYS, BeadgraphError  # noqa: E402
from .defaults import DEFAULTS  # noqa: E402

__all__ = ["classify", "apply_edits", "resolve", "basis", "morph", "check", "validate", "graph_bytes", "DEFAULTS",
           "SCHEMA", "RULES", "MORPH_RULES", "__version__", "BeadgraphError", "CLS", "LABEL_KEYS"]


def classify(nodes, elems, fixed=None, cfg=None):
    """shell mesh (nodes (n,3) mm, elems (m,4) 0-based, tri 4th = -1, optional fixed node indices) -> (graph, labels).
    graph = ``beadgraph/1`` JSON dict (no per-element arrays), labels = {cls, floor, segment, transition, island,
    junction_zone, tier} int32 arrays in input element order (-1 = none). Raises BeadgraphError(code)."""
    from .classify import classify_full
    g, lab, _aux = classify_full(nodes, elems, fixed, cfg)
    return g, lab


def apply_edits(graph, labels, edits, nodes=None, elems=None):
    from .edits import apply
    return apply(graph, labels, edits, nodes=nodes, elems=elems)


def resolve(graph, labels, ref):
    from .edits import resolve as _r
    return _r(graph, labels, ref)


def basis(graph, labels, nodes, beads, ranges, cfg=None, fixed=None, elems=None):
    from .morph import basis as _b
    return _b(graph, labels, nodes, beads, ranges, cfg=cfg, fixed=fixed, elems=elems)


def morph(nodes, basis, values):
    from .morph import morph as _m
    return _m(nodes, basis, values)


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
