# release/v0.25.2 통합 — 이어받기

위치 /home/claude/wt_v0252 (release/v0.25.2). 다른 worktree 는 읽기만(/home/claude/wt_v0251 은 다른 에이전트 작업 중 — 건드리지 않음).

## 진행
- [x] 1. merge wip/v0.25.2-b1(a2f45b84, 충돌 없음) · wip/v0.25.2-f1(63de3332, 충돌 없음)
- [x] 2. merge release/v0.25.1(d578b0df — INT-10~12). 충돌 2곳(docs/decisions.md·resources/doe_messages.json 끝 덧붙임) 양쪽 보존
- [ ] 3. 맞춤: B1 가드(test_doe_config 코어 거울·워커 가짜 merge) → 실제 코어 · types.ts ↔ OpenAPI 재생성 check:api · 제안 키 2개(manual_ratio_warn·tie_far_mm)
- [ ] 4. 문서: CHANGELOG·user.md·admin.md·field_check_v0252.md·VERSION·계약 §INT·decisions INT·handoff 삭제
- [ ] 5. 시험(/tmp/int252/run_all.sh)

## 메모
