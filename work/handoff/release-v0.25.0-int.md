# release/v0.25.0 통합 handoff (INT)

환경 /tmp/rdenv_int250.sh(= rdenv_main, REPO_ROOT=wt_v0250, PYTHONPATH += packages/beadgraph/src). pytest --basetemp=/tmp/int250_bt -o tmp_path_retention_policy=failed.

## 끝난 단계
1. merge origin/release/v0.24.9 04a7dba1 — 충돌 docs/decisions.md(v0.24.9 INT-5~8 줄 + v0.25.0 절 둘 다), esl/doe/bead_graph.py guard_selection(U 포화 `_u_sat_entry` + A warp 정보 둘 다). 빠른 시험 79 passed.

## 남은 단계
2. merge wip/v0.25.0-b1·f1 3. 코어 보완(tie 출처·normalize_v2 블록·VB_SCOPE INT) 4. F1 보정(vb_frame·절 표시) 5. openapi·types 6. 문서 7. 전체 시험
