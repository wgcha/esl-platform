# release/v0.24.6 통합 진행 (끝나면 삭제)
- [x] 병합 c1 → b1 → f2 (충돌 없음)
- [x] 항목1 b1 시험 test_rank_v3d_mirrors_core_column 실제 대조로 강화
- [x] 항목2 backend/tests/test_doe_v0246_core_e2e.py(실제 코어 산출물 → API) 3개
- [x] jig_diag 끔 불일치 발견: 빈 탭 [다시 만들기] 버튼이 눌러도 무변화 → doeTabs.tabState no_view 이면 add 끔
- [x] 항목6 node_modules npm ci(실제 설치, gitignore 확인)
- [x] 항목8 일부: VERSION 0.24.6, 버전 시험 2곳
- [ ] 항목4 스크린샷 스크립트 testid, 항목3·5 check:api, 항목7 handoff→decisions, CHANGELOG·매뉴얼·field_check
- [ ] 시험 순서: pytest tests/ → backend → worker → vitest → typecheck/build/check:api/dump_openapi --check
