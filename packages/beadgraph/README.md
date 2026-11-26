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
one_side(graph, labels, nodes, elems, segs, *, min_nodes=3) -> dict         # 1.2.0: one-sided entry measurement
```

- input: `nodes (n,3)` float64 mm, `elems (m,4)` 0-based (triangle 4th = -1), optional fixed node indices. Inches: convert
  before calling. Mesh source (gmsh, .rad/.inc, remesh), numbering, element orientation and rigid placement do not
  change the result (V-BG-4).
- `labels` = `{cls (0 floor, 1 wall, 2 island, 3 lance), floor, segment, transition, island, junction_zone, tier}` int32,
  input element order, -1 = none.
- `beads` for `basis` = `[{name, kind: "D"|"W"|"DF"|"W1"|"U", segs: [segment id…], zones?: [junction-zone id…], hold: 0|1}]`
  (1.2.0: `DF` = depth with the floor width and each wall's flank angle kept — the entry widens by cotθ·ΔD per wall;
  `W1` = one-sided entry width — the open side moves ΔW, the fixed side stays; `ramp: "end"`, `min_nodes`); grouping,
  ties and names are the caller's job. `ranges` = default range per variable (fixes the ramp length and corner guard).
  1.3.0: `U` = bead position perpendicular to the path, nominal 0 mm, + = left of the bead's travel direction (one
  direction for a segment chain — `u_orient`). Item keys `hold_nodes` (extra held nodes, e.g. jig ties — U always holds),
  `range_rel` (ext without a range = range_rel·W_ref), `gap_rel` (neighbour-gap limit), `guard_jac_min`,
  `guard_tri_angle_min_deg`. Every segment needs entry lines on both sides and an open skeleton (`u_closed`). The bead
  (entry, walls, floor, children, owned islands) follows a smoothed t⊥ field; the parent floor band (both sides) fades
  to 0 at other zones, the plate edge, held nodes / islands (gap fraction); a smooth quality guard keeps the default
  range ends free of inverted / concave elements. `beadgraph.morph.u_gaps(...)` gives the feasible inputs (W_ref,
  g±, dir).
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

1.2.0 (esl v0.24.7, contract esl_bead_depth_mode.md §5.1) = RULES 1, MORPH_RULES 2, new `DF_RULES` 1 (kind DF),
`W1_RULES` 1 (kind W1), new function `one_side`. `OUTPUT_VERSION` = "1.1.0" is written into graph.json (`version`) and
only moves when RULES or MORPH_RULES move — graph.json and the D·W basis bytes of 1.1.0 are unchanged, so a consumer's
graph sha (and esl `BG_GRAPH_STALE`) does not change with this MINOR. `python -m beadgraph version` prints
`version`, `output_version`, `rules`, `morph_rules`, `df_rules`, `w1_rules`, `u_rules`.

1.3.0 (esl v0.24.9, contract esl_bead_pos_u.md §1.1) = 1.2.0 + kind U (`U_RULES` 1). `OUTPUT_VERSION`, RULES,
MORPH_RULES, DF_RULES, W1_RULES unchanged — graph.json and the D·W·DF·W1 basis bytes are the 1.2.0 bytes.

## Checks

`python -m beadgraph selftest [--json]` (exit 0 = pass) or `pytest --pyargs beadgraph.testing`: H6 / H5 classification
accuracy, determinism against `expected.json`, numbering / orientation / rigid-transform invariance, morph metrics,
import purity, DF·W1 on the synthetic aligned-quad fixtures (`testing/synth_oneside.py` — numpy only), U on the
straight channel / R 150 arc / T junction (`testing/synth_pos.py`). No gmsh needed.
The generators `testing/synth_h5.py`, `testing/synth_h6.py`, `testing/synth_stepboss.py` need the `[synth]` extra.

## physicsai-platform

Wheel `beadgraph-<ver>-py3-none-any.whl` from the esl-platform release in `vendor/wheels/`, pinned
`beadgraph==<ver> --hash=sha256:<…>`. Do not fork or patch a copy: report problems as an esl-platform issue with the
mesh (npz) and the expected result. Do not import physicsai code from the package or depend on global settings.
