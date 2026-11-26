# release/v0.24.9 통합 handoff (C1 + B1 + F1 + v0.24.8 최종)

계약 docs/contracts/esl_bead_pos_u.md(§10.6 통합 보정 INT-1~4), 결정 D-0.24.9-PU-1~17·BM-1·PU-C1-1·INT-1~3.
시험 환경 /tmp/int249/env.sh(= /tmp/rdenv_main.sh, REPO_ROOT=wt_v0249, PYTHONPATH += packages/beadgraph/src).

## 끝난 일
- 병합: release/v0.24.8 971147ea(a1ac691b — decisions·stages.bd_post 충돌 둘 다 보존), wip/v0.24.9-b1(deploy 시험 docstring), wip/v0.24.9-f1(doe.ts 문구 표·DoeRanking 꼬리 둘 다)
- 5b9c1809: 표식 형식 하나(코어 jig_bc.support_rows/method_row_of, 어댑터 core_adapter.jig_support_rows, 백엔드 자체 계산·manifest 덧쓰기 제거,
  프런트 dirs 벡터만·스프링 k 목록·옛 안내 INT-3), 백엔드 derive tie_node_ids = 코어 stages.pos_u_tie_ids_at, load_follow = 코어 판정, U 422 중복 제거,
  types.ts pos_u·load_follow(check:api), 계약 §5-13·§10.6, decisions
- 문서: CHANGELOG [0.24.9], user(위치 변수 U 절·3D 지그 기호), admin §4.9, field_check_v0249.md

## 남은 일
- 전체 시험(tests/·beadgraph·backend·worker·frontend typecheck·build·check:api·vitest)
- 완료 시 이 파일 삭제

## 다음 명령
source /tmp/int249/env.sh; cd /home/claude/wt_v0249; $PY -m pytest -q tests/ --basetemp=/tmp/int249/bt -o tmp_path_retention_policy=failed
