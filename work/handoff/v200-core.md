# v200-core 인계 (esl_load_transfer.md core-geom)

- 상태: WIP. 신규 esl/doe/load_transfer.py, scenario.compare_target(supports, region)·shape_check(region),
  stages.py ④ 분기(_lt, _cmp_loads_lt, _cmp_eval_lt, _lt_post, _lt_view3d_ref, _lt_mesh_loads, CSV 끝 열),
  report_doe 하중 전달 절, DEFAULTS compare.load_transfer, doe_messages LT_* 코드, synth_compare lt_* 함수.
- 남음: tests/doe/test_load_transfer.py(V-LT-1~7·12), regress 대조(reg200/run.sh wt-191=main 기준 완료), 합성 비교 수치.
- 회귀 기준: scratchpad/reg200/out/main_* (wt-191 = 40dcc6d 트리 동일).
