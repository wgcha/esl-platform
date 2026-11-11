# Handoff: feat/v0180-backend (Impl-Backend, esl-platform v0.18.0 STEP_GRAPH)

## Goal
Contract docs/contracts/esl_step_graph.md, Backend ownership (§11): select_base "step" (③ on beadgraph/select), config
select.step_graph, settings scenarios.select_step, worker _geom_select/run_step step branch, register prep summary, tests.

## Done
- core/config.py: BeadDoeSelectStepGraphCfg (+FixedTransfer, Region) under select.step_graph; yaml x2 mirrored.
- schemas.py: select_base Literal += step; DoeCheckOut.step_graph; DoeSelectAutoOut.source += fixed_transfer.
- services/doe.py: status scenarios.select_step (select ok AND gmsh ready), settings select.step_graph,
  _mesh_mode_ladder helper (shared with ④, behaviour unchanged), _select_step_check, create (inputs/snapshot
  select_base step, mesh_mode, mesh_refine, mesh_ladder; no mesh_size_mm), clone guard (schema 2, gmsh), study_out prep
  passthrough (select_base step, mesh, region).
- doe_select.py: GET select/auto for step base regardless of bead_source; source from file.
- worker doe_jobs.py: run_step skipped text via skipped_text(); _geom_select step plan [a_fixed]+(auto) extract.
- worker register.py: _select_step_prep (mesh, fixed.xfer, region).
- tests: backend/tests/test_doe_step_graph_api.py (32 pass), worker/tests/test_doe_step_graph_jobs.py (8 pass, 1 skip core).
  Updated test_doe_api scenarios dicts, test_doe_select_api defaults, doe_support SELECT_KEYS (step_graph).

## Remaining
- Full backend + worker suites (sequential), openapi regen (scripts/dump_openapi.py), final commit removing this file.

## Next commands
- Temporarily set config/esl_platform.example.yaml line 59 min_free_gb 0 for runs, restore after.
- TMPDIR=/tmp python -m pytest -q backend/tests -p no:cacheprovider ; then worker/tests
