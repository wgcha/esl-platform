# v200-core 인계 (esl_load_transfer.md §13 + esl_stiffness_metric.md (b))

- LT 완료(커밋): load_transfer.py 순수 모듈(전략 identity·work·cell, run_transfer_plan, place, build_disp), transfer_plan.py(계획 표 +
  sm 열), compare_lt.py(④ 지지·영역·W 파일 캐시), stages `_plan_loads` 단일 하중 자리·모든 모드 진단·post·CSV·report.
- 시험: test_load_transfer.py(모듈), test_transfer_plan.py, test_lt_modes.py(①②③④). tests/doe 전체 통과(392 + 4 skip).
- 회귀: scratchpad/reg200 (wt-191 = 40dcc6d) — regress none·cad·auto·sel_regress·selreg 바이트 동일(경로·시각만 다름).
- 남음 (b): v200-sm merge, stages SM(eval·post·view3d u_def), DEFAULTS rank.*, messages SM_*, report, 시험.
