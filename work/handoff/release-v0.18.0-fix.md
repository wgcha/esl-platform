# release/v0.18.0 Verifier fix — handoff (delete in final commit)
Base 388cbf5. Worktree /tmp/claude-0/-home-claude/b31e30b1-6347-515a-8f7b-a9260713e285/scratchpad/wt-fix180.
## Done
- HIGH: hole-feature frame_check + Kabsch xyz_fitted + per-cluster validation (resid_mm/feature/via); config keys; contract SG-D-13 revised, decisions D-0.18.0-XFER-HOLES.
- MED: tests/doe/test_step_graph_perf.py (600k classify 170 s, RSS 900 MB, derive 2.1 s); SG-X-2 tied to V-SG-R1 + STEP_GRAPH_ISLAND_AS_WALL warning (bead_graph.wall_islands).
- LOW: A_SCAN_FAILED (worker empty prep/a_fixed + core dir rule), fixed_seed_v2 cfg, mock B8, mesh-note nowrap, screenshots re-shot.
- regress none/cad/auto + sel_regress vs origin/main baseline: byte identical.
- targeted: test_step_graph_fixed 20, slow H6-STEP 4, backend/worker/config 221, vitest doe_step_graph 11, perf 2.
## Todo
- test-all (running; config/esl_platform.example.yaml min_free_gb lowered to 5 for the run only — revert before commit), final commit, ff push, remove worktree.
