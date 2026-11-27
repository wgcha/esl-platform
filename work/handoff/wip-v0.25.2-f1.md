# wip v0.25.2 F1 (프런트) — 이어받기

브랜치 wip/v0.25.2-f1 · 소유 frontend/** · 계약 docs/contracts/esl_tstar_manual_jig_force.md

## 진행
- [x] A ② 곡선 클릭·직접 행·경고·불가 사유 (Stage2·MaxHoldChart·lib/tstarFrames.ts·mock·시험 tstar_manual_v0252.test.tsx)
- [ ] B 3D 지그 강제 표식
- [ ] C #96 결과 화면
- [ ] 높이 측정(scripts/screenshots-v0252-f1.mjs) · 전체 vitest 1회

## B1 과 맞출 키 (types.ts 는 손으로 맞춤 — 통합 때 대조)
- GET /tstar: frames[{frame_index,time}] · frames_have[] · fill{available,code,text} · metrics[m].history.frame_index[] (계약 §6.1)
- **제안 추가 키** `manual_ratio_warn`(GET /tstar 최상위, tstar.manual_ratio_warn 값) — 계약에 없음. 없으면 화면은 LOW 경고색 판정 생략.
- cases.tstar.manual{auto_frame,auto_time,auto_value,ratio,rel,in_D,have}
