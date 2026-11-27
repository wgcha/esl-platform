# release/v0.25.2 통합 — 이어받기

위치 /home/claude/wt_v0252 (release/v0.25.2). 다른 worktree 는 읽기만(/home/claude/wt_v0251 은 다른 에이전트 작업 중 — 건드리지 않음).

## 진행
- [x] 1. merge wip/v0.25.2-b1(a2f45b84, 충돌 없음) · wip/v0.25.2-f1(63de3332, 충돌 없음)
- [x] 2. merge release/v0.25.1(d578b0df — INT-10~12). 충돌 2곳(docs/decisions.md·resources/doe_messages.json 끝 덧붙임) 양쪽 보존
- [x] 3. 맞춤(커밋 'v0.25.2 통합 3'): test_doe_config v0.25.2 분기 제거(새 키 존재 단언 + 전체 대조) · 워커 test_frame_fill 가짜 merge·코어 가로채기 →
  실제 코어 merge·ESL(가짜 hw FAKE_HW_FR_SRC = 전 프레임 D 합성 CSV 의 f·f−1 행, 실제 MISMATCH 는 FAKE_HW_FR_NFRAMES) 34 통과 ·
  check:api 11건 → 0(TS n_ref null 허용, tie_far_mm 백엔드 추가) · GET /tstar manual_ratio_warn(코어 설정 값) · manifest tie_far_mm(= map.tie.force.far_mm) ·
  marks[].to → 3D 선 끝(없으면 가장 가까운 강제 지지), miss dist null 타입 · 화면 countItems 계산 = 코어 count_items(같은 키 합·표 순서)
- [x] 4. 문서(커밋 4a·4b): CHANGELOG·admin §4.12·VERSION·버전 시험 / user.md·field_check_v0252.md·계약 §15.1~§15.4(INT-1~9 — INT-9 시험 결과는 끝나면)·decisions INT·handoff 3개·findings TM-C1 절 삭제
- [ ] 5. 시험(/tmp/int252/run_all.sh — nohup 실행 중, 진행 /tmp/int252/progress.log, 단계 rc /tmp/int252/<step>.rc, 다시 돌리면 끝난 단계 건너뜀). 끝나면 허용 실패·시간 의존 단독 재실행 → 계약 §15.4 INT-9·decisions 에 기록

## 메모
