# beadgraph

Shared bead-network classifier and segment morph for shell meshes — used by **esl-platform** (in-repo path install)
and **physicsai-platform** (vendored wheel pinned by version and hash). Pure numpy / scipy, no platform imports, no
file or network I/O (fixture reading in `beadgraph.testing` excepted), no global state, no randomness.

Source of truth: esl-platform `docs/contracts/esl_beadgraph.md` (BEADGRAPH, v0.17.0) §2 (graph model), §4 (morph),
§8 (package). This file is a summary.

## API (stable — a signature or `schema` major change is a MAJOR release)

```python
classify(nodes, elems, fixed=None, cfg=None) -> (graph, labels)            # graph = beadgraph/1 JSON dict
apply_edits(graph, labels, edits, nodes=None, elems=None) -> (graph, labels)  # toggle -> merge -> split (split needs the mesh)
resolve(graph, labels, ref) -> int                                         # {anchor}|{network} -> id, KeyError if gone
basis(graph, labels, nodes, beads, ranges, cfg=None, fixed=None, elems=...) -> list[dict]
morph(nodes, basis, values) -> ndarray                                     # x0 + Σ dv·vec
check(graph, labels, nodes, x, basis, values, cfg=None, elems=None) -> dict  # outside / achieved / island residual / inverted
validate(graph) -> None                                                    # ValueError on schema violation
graph_bytes(graph) -> bytes                                                # canonical graph.json bytes
```

- input: `nodes (n,3)` float64 mm, `elems (m,4)` 0-based (triangle 4th = -1), optional fixed node indices. Inches: convert
  before calling. Mesh source (gmsh, .rad/.inc, remesh), numbering, element orientation and rigid placement do not
  change the result (V-BG-4).
- `labels` = `{cls (0 floor, 1 wall, 2 island, 3 lance), floor, segment, transition, island, junction_zone, tier}` int32,
  input element order, -1 = none.
- `beads` for `basis` = `[{name, kind: "D"|"W", segs: [segment id…], zones?: [junction-zone id…], hold: 0|1}]`; grouping,
  ties and names are the caller's job. `ranges` = default range per variable (fixes the ramp length and corner guard).
  `elems` is required by `basis` (connectivity).
- Classification errors raise `BeadgraphError` with `.code` in `TOO_LARGE | TIMEOUT | NO_FLOOR | ERROR`.

## Versions

| change | bump |
|---|---|
| API signature / `schema` major | MAJOR (`beadgraph/2`) |
| classification output (graph.json bytes for the same input + cfg) | MINOR + `RULES` + 1, refresh `testing/expected.json` |
| morph basis numerics | MINOR + `MORPH_RULES` + 1 |
| new optional field / function | MINOR |
| output-preserving fix (performance, refactor) | PATCH — fixture sha must stay byte-identical |

1.0.0 = RULES 1, MORPH_RULES 1. 1.1.0 (esl v0.19.1) = RULES 1, MORPH_RULES 2 — a straddling island's rim nodes on a
foreign wall are held like its foreign-floor contact; basis and checks share `zones.movable_nodes` (BG-D-47). Record `beadgraph_version`, `rules`, `morph_rules` with every product.

## Checks

`python -m beadgraph selftest [--json]` (exit 0 = pass) or `pytest --pyargs beadgraph.testing`: H6 / H5 classification
accuracy, determinism against `expected.json`, numbering / orientation / rigid-transform invariance, morph metrics,
import purity. No gmsh needed. The generators `testing/synth_h5.py`, `testing/synth_h6.py`, `testing/synth_stepboss.py` need the `[synth]` extra.

## physicsai-platform

Wheel `beadgraph-<ver>-py3-none-any.whl` from the esl-platform release in `vendor/wheels/`, pinned
`beadgraph==<ver> --hash=sha256:<…>`. Do not fork or patch a copy: report problems as an esl-platform issue with the
mesh (npz) and the expected result. Do not import physicsai code from the package or depend on global settings.
