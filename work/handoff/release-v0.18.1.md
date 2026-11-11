# release/v0.18.1 인계(진행 중 — 마지막 커밋에서 삭제)

목표: 동봉 paicad 0.14.1 → 0.15.4(physicsai release/v0.2.17 9b71cb7).

## 완료
- [x] 1. wheel 빌드(deploy/paicad_wheel.py collect --repo, Python 3.13·3.12 동일 sha 3c4cd456…) · paicad.lock 갱신 · deploy/wheels 교체

- [x] 2. 호환 감사: CLI 인자·종료코드 불변, options 새 키 모두 선택(esl 은 키를 넣지 않음), 보고 추가 키만.
  esl 수정 = SHELL_FEATURE_DISTORTED → FAILED_MORPH + 전용 문구(classify: messages[<paicad 코드>] 우선), min/pinned 0.15.4,
  fake_paicad 0.15.4(check 단계 규칙·checks.feature), 계약 §6.3·§6.6, admin·bead_doe_check·RESOURCES, 시험 버전 단언.
  GitHub 빌드 시험(ESL_TEST_NETWORK=1) = lock sha 일치.

## 남은 일
- [ ] 3. 시험: 실 paicad 레인(ESL_TEST_PAICAD=1), fake_paicad, scripts/test-all, regress(none/cad/auto)·sel_regress
- [ ] 4. #63 회귀(구면 딤플 STEP grid 셀)
- [ ] 5. VERSION 0.18.1·CHANGELOG·openapi·버전 단언·decisions.md·계약
- [ ] 6. push, 워크트리 제거
