# HANDOFF release/v0.24.8 — C1 코어(격자 지그, 계약 docs/contracts/esl_jig_grid_map.md)

## 끝난 일
1. 골든(옛 바이트, 코드 변경 전 v0.24.7 머지 헤드): tests/doe/golden_v0248_c1/{golden.py, golden.json} + tests/doe/test_jig_grid_golden.py,
   합성 세계 tests/doe/synth_jig_grid.py(④ 메시 입력 형상·옛 ③ 가짜 gmsh — gmsh 없이 전 파이프라인).

## 남은 일(순서)
2. grid_map 시그니처·jig_kind·코드 표·사이드카/결과 스키마 뼈대 커밋(백엔드·프런트가 맞출 수 있게)
3. grid_map 본 구현 + tests/mech/test_grid_map.py(항등 h 5·1.5)
4. stages 통합(_jg_prep/_jg_shape/_jg_apply/_jg_post/3D/CSV/해시) + e2e 시험
5. report_doe 1줄, 측정(항등·수렴·다른 메시·비용) → 반환

## 시험 상태
- tests/doe/test_jig_grid_golden.py 3 passed

## 다음 명령
source /tmp/rdenv_v0248c1.sh (= /tmp/rdenv_v0247.sh 의 REPO_ROOT 를 /home/claude/wt_v0248 로)
$PY -m pytest -q tests/doe/test_jig_grid*.py tests/mech/test_grid_map.py --basetemp=/tmp/c1_bt -o tmp_path_retention_policy=failed
