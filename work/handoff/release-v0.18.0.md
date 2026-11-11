# HANDOFF release/v0.18.0 integration (2026-11-12)
Worktree: scratchpad/wt-int180 (release/v0.18.0). Merged core fb0d525, backend bff2859, frontend 15338f8 (no conflicts).
Done:
- [1] mirror test: explicit DEFAULTS step_graph == STEP_GRAPH_DEFAULTS == pydantic (backend/tests/test_doe_select_api.py) — keys already equal
- [2] openapi regen (0.18.0) + types.ts (DoeCheckOut.step_graph → DoeCheckStepGraph, DoePlanOut.region_ab, settings step_graph widened)
- [3] doe_select._step_plan_extras: fixed[].src (fixed_transfer.json node_id) + region_ab (keepout.region_rings outer rings); DoePlanOut.region_ab; test test_step_plan_extras_fixed_src_and_region
- [6] VERSION/CHANGELOG/test asserts 0.18.0
- [4] V-SG-7 E2E now runs (fixtures exe/settings_dict/worker, select_schema2 marker, H5 A case) full flow prep→seed→preview→run→files, 9 passed
- [5] contract §12 + decisions done
- test-all EXIT 0: core 1047p/70s, beadgraph 49p/1s, backend 703p, worker 260p, deploy 156p/21s, vitest 572, typecheck/build/check:api ok; SCX 77+32 pass; H6-STEP slow 23 pass
TODO: regress (running, scratchpad/reg180), screenshots, final commit, push, remove worktrees
- temp min_free_gb yaml change reverted after test-all
