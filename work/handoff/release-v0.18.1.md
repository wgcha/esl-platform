# release/v0.18.1 인계(진행 중 — 마지막 커밋에서 삭제)

목표: 동봉 paicad 0.14.1 → 0.15.4(physicsai release/v0.2.17 9b71cb7).

## 완료
- [x] 1. wheel 빌드(deploy/paicad_wheel.py collect --repo, Python 3.13·3.12 동일 sha 3c4cd456…) · paicad.lock 갱신 · deploy/wheels 교체

## 남은 일
- [ ] 2. 호환 감사(명령 템플릿·options 키·보고 스키마·코드) + esl 수정 + doe_messages.json
- [ ] 3. 시험: 실 paicad 레인(ESL_TEST_PAICAD=1), fake_paicad, scripts/test-all, regress(none/cad/auto)·sel_regress
- [ ] 4. #63 회귀(구면 딤플 STEP grid 셀)
- [ ] 5. VERSION 0.18.1·CHANGELOG·openapi·버전 단언·decisions.md·계약
- [ ] 6. push, 워크트리 제거
