# release/v0.25.0 통합 handoff (INT)

환경 /tmp/rdenv_int250.sh(= rdenv_main, REPO_ROOT=wt_v0250, PYTHONPATH += packages/beadgraph/src). pytest --basetemp=/tmp/int250_bt -o tmp_path_retention_policy=failed.

## 끝난 단계
1. merge origin/release/v0.24.9 04a7dba1 — 충돌 docs/decisions.md(v0.24.9 INT-5~8 줄 + v0.25.0 절 둘 다), esl/doe/bead_graph.py guard_selection(U 포화 `_u_sat_entry` + A warp 정보 둘 다). 빠른 시험 79 passed.

2. merge wip/v0.25.0-b1(충돌 없음)·f1(충돌 DoeParamTable import·graphmock — U 포화 목 + 추가 비드 목 둘 다). node_modules = wt_v0250_f1 복사.
3. 코어 보완 INT-1~3(계약 §20) 7ff3eb3d. 4. F1 보정 INT-4·5(계약 §20). 5. openapi 재생성 = 변화 없음(B1 이 이미 생성), check:api·check-api.test 통과.

## 남은 단계
6. 문서(CHANGELOG·매뉴얼·field_check_v0250·VERSION) 7. 전체 시험 → handoff 삭제(내용 = 계약 §20·decisions)
