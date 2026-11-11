# Handoff: feat/v0180-core (Impl-Core, esl-platform v0.18.0 STEP_GRAPH)

- Goal: new ③ = select + select_base "step": STEP → ④ ladder shell mesh (prep/mesh0) → beadgraph → select flow;
  loads mapped once (region nodes), A fixed transfer (xyz_nearest → ab_hole_snap → none), main-sheet region.
- Contract: docs/contracts/esl_step_graph.md SG-D-1..20, V-SG-*, R-SG-*; O-SG-1..3 resolved.
- Base: origin/release/v0.18.0 (134ecfb). Worktree: scratchpad/wt-core180.

## Done
- DEFAULTS select.step_graph; bead_select HASH_NEW_KEYS_V0180 + select_hash_view(step=)
- doe_messages: STEP_GRAPH_TRIA(_BLOCKED), STEP_GRAPH_REGION(_SMALL), FIXED_XFER_NONE/UNMATCHED
- bead_graph: prep_graph(limits=), auto_seed(exclude_segs=), auto_doc_v2(source=, fixed=), fixed_seed_v2, region_marks
- new esl/doe/step_graph.py (interface doc at top): cfg_of, region_mask, frame_check, fixed_transfer, seed_fixed_user,
  tria_check, region_loads, load_region, mesh0
- scenario.template_base(region=), evaluate.evaluate(region=) (None = byte-identical)
- stages: mesh_dir kw on _cmp_mesh_shape/_cmp_ladder/_cmp_mesh_one/_cmp_defeature_stage/_cmp_relaxed_parent;
  select_base "step", _is_step_base, bd_mesh0 step branch, _sel_input_step, _sel_fixed_ids step, hash step view,
  bd_eval region, _design_mesh TODO comment

- stages._sel_loads step branch (region loads, _boundary region, fixed_transfer.json, graph limits, graph_region.json,
  seeds auto/manual with fixed_user), _sel_auto_v2 kwargs, _sel_best/_sel_part_title/_sel_rad_files step
- smoke E2E (plate STEP, scratchpad/smoke/run.py): input→mesh0→loads→matrix→eval→post→best OK

## Remaining
- tests: synth_step_graph.py (H6/H5 STEP), test_step_graph.py, test_step_graph_fixed.py, test_step_graph_region.py,
  test_bead_graph_cfg.py additions; regress.py (none/cad/auto) + sel_regress.py vs origin/main
- final: remove this file, push, remove worktree

## Files touched
esl/doe/{__init__,bead_graph,bead_select,evaluate,scenario,stages,step_graph}.py, resources/doe_messages.json

## Test status
- tests: step_graph 7 fast + 4 slow pass (H6 STEP known miss: 2 wall bosses), _fixed 8, _region 4, cfg 7; regress none/cad/auto + sel_regress IDENTICAL vs origin/main
- tests/doe/synth_step_graph.py: h6_step (STEP gen, slow), add_extra, LightEntry, tri_split

## Next commands
1. edit stages._sel_loads (see Remaining)
2. python -m pytest tests/doe/test_bead_graph_stages.py -q
3. write tests/doe/test_step_graph*.py
