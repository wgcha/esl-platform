# HANDOFF release/v0.24.8 — C1 코어(격자 지그, 계약 docs/contracts/esl_jig_grid_map.md)

## 끝난 일
1. 골든(옛 바이트, 코드 변경 전): tests/doe/golden_v0248_c1/ + test_jig_grid_golden.py, 합성 세계 tests/doe/synth_jig_grid.py
   (④ 메시 입력 형상·옛 ③ 가짜 gmsh — gmsh 없이 전 파이프라인).
2. esl/mech/grid_map.py(순수): grid_frame·vox_key·build_field·tie_skeleton·case_tie·skel_spring·build_group/group_arrays/
   group_from_arrays·capture·sample_tie·sample_field·shape_spring_k·shape_bcs·run_shape·recon·hash_view(HASH_EXCLUDE + schema·enabled 고정).
3. transfer_plan: jig_fix grid·jig_ctx shape(④·옛 ③), 불변식, jig_kind(plan, grid_snap — bool 또는 스냅샷 블록 dict), metric_effective(kind).
4. stages: _jg_kind/_jg_cfg/_jg_prep(_safe)/_jg_shape/_jg_apply/_jg_ready/_jg_rank_src/_jg_nf/_jg_post/_jg_view3d_src/_jg_mesh_of/
   _jg_warn_rows/_jg_cfg_hash + 훅(bd_eval·_cmp_loads_lt·bd_loads·_sm_post·_sm_post_warn·_jig_post·_jig_csv_arg·_cmp_ranking_csv·
   _cmp_post·bd_post·_jig_extras·_jig_v3d_sidecar·_rank_view_one·_src_need·_post_view3d·_cfg_hash).
5. DEFAULTS rank.jig_grid(§7.1 = 백엔드 BeadDoeRankJigGridCfg 와 같음), resources/doe_messages.json JIG_GRID_* 9개, report_doe 1줄.
6. 시험: tests/mech/test_grid_map.py(14 — 2 xfail strict: 측정 초과), tests/doe/test_jig_grid_plan.py(23), test_jig_grid_e2e.py(15),
   test_jig_grid_golden.py(3). work/findings.md = 계약 보정 필요 2건.

## 남은 일(순서)
- 메인 결정: findings 1(§1.3-3 골격 밖 띠 노드 외삽 — jd 다른 메시 ΔΠ 0.54 → 0.021), 2(§4.2 ΔΠ_5 ≤ 0.02 → 측정 2.5~3.5e-2).
- 통합: CHANGELOG·user.md·decisions 확정(메인).

## 시험 상태
- 새 시험 전부 통과(2 xfail strict). 전체 tests/ = 허용 실패 3건(test_large_model_cad_share·test_v0160_bytes_skip_policy[h8]·[h5open]) 외 0(골든 모듈 이름 충돌 golden → golden_jg 수정 후).

## 다음 명령
source /tmp/rdenv_v0248c1.sh (= /tmp/rdenv_v0247.sh 의 REPO_ROOT 를 /home/claude/wt_v0248 로)
$PY -m pytest -q tests/doe/test_jig_grid*.py tests/mech/test_grid_map.py --basetemp=/tmp/c1_bt -o tmp_path_retention_policy=failed
