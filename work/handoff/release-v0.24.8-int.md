# INT v0.24.8 진행
- [x] merge b1, merge f1 (충돌 없음)
- [x] 1. conv_warn 0.05·noise_floor_min 0.03 거울(DEFAULTS·pydantic·yaml 2), JG-20, 시험 1개 추가(코어 e2e)
- [x] 2. 백엔드 jig_kind = 코어 함수 호출 + 대체 계산 동일 시험, e2e backend/tests/test_doe_v0248_core_e2e.py(6) 통과; JIG_GRID_* message 머리·영문 꼬리 응답 때 제거
- [x] 4. JIG_GRID_ON_CLONE(doe_messages.json·응답 warnings level info·프런트 정보 코드)
- [x] 5·7·8 문서(decisions INT-1~7, 계약 §5·§16, CHANGELOG, user/admin/field_check), 버전 0.24.8, handoff·findings 삭제, npm ci, openapi 재생성
- [ ] 스위트: tests/ · beadgraph · backend · worker · vitest · typecheck/build/check:api/dump_openapi --check
