# release/v0.18.0 Verifier fix — handoff (delete in final commit)
Base 388cbf5. Worktree /tmp/claude-0/-home-claude/b31e30b1-6347-515a-8f7b-a9260713e285/scratchpad/wt-fix180.
## Done
- core step_graph: hole-feature frame_check + Kabsch fit (xyz_fitted) + per-cluster validation (resid_mm, feature, via); config keys frame_min_holes/frame_match_mm/frame_resid_mm (origin_tol_mm/axis_tol_deg removed) in DEFAULTS, backend, yaml.
- tests: test_step_graph_fixed.py (probe p1 parametrized, p2 #63-like, fallback), test_step_graph.py plate expectations (hole-less → NO_MATCH), A_SCAN_FAILED, feature_angle.
- worker: paicad missing + A Case → empty prep/a_fixed → core A_SCAN_FAILED; register whitelist xyz_fitted. frontend xyz_fitted text.
## Todo
- slow H6-STEP, perf test V-SG-12, SG-X-2 straddle warning + contract V-SG-R1, contract SG-D-13 revised + decisions.md, mock B8, int_1 CSS, screenshots, regress, test-all.
