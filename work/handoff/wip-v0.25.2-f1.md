# wip v0.25.2 F1 (프런트) — 이어받기

브랜치 wip/v0.25.2-f1 · 소유 frontend/** · 계약 docs/contracts/esl_tstar_manual_jig_force.md

## 진행
- [x] A ② 곡선 클릭·직접 행·경고·불가 사유 (Stage2·MaxHoldChart·lib/tstarFrames.ts·mock·시험 tstar_manual_v0252.test.tsx)
- [x] B 3D 지그 강제 표식 (supportMarks TIE_TABLE · supports.buildTieMarks · scene.setTieMarks · 탐침 kind tie)
- [x] C #96 (countTail·기본 탭·빈 탭 링크·참고 꼬리표·SHAPE_DOUBLE_SHEET 배지) — 시험 doe_v0252.test.tsx
- [ ] 높이 측정(scripts/screenshots-v0252-f1.mjs) · 전체 vitest 1회

## B1 과 맞출 키 (types.ts 는 손으로 맞춤 — 통합 때 대조)
- GET /tstar: frames[{frame_index,time}] · frames_have[] · fill{available,code,text} · metrics[m].history.frame_index[] (계약 §6.1)
- **제안 추가 키** `manual_ratio_warn`(GET /tstar 최상위, tstar.manual_ratio_warn 값) — 계약에 없음. 없으면 화면은 LOW 경고색 판정 생략.
- cases.tstar.manual{auto_frame,auto_time,auto_value,ratio,rel,in_D,have}
- 3D manifest: `tie_marks[{q,via,x,dist,n,far}]`(§4.3) · supports[].via · **제안 키** `tie_far_mm`(manifest 최상위 — 범례의 "{far} mm 넘음" 숫자. 없으면 "먼 곳")
- 결과·보기: n_ref · counts[{key,label,n}] · 순위 행 jig_ref · jig.grid.n_forced_shapes/n_ref_shapes · prep 형상 행 double_sheet{frac,gap_mm}
- 경고 필드 이름 가정(대체 문구용 — 서버 message 가 오면 불필요): did,n_force,n_clusters,pct,dmin,dmed,dmax,far,n_far,n_miss. "참고" 꼬리표 title 은 JIG_GRID_TIE_FORCED 경고를 did(또는 id·name·문구 "형상 {did}")로 찾음
- 다음: 높이 측정 스크립트(screenshots-v0252-f1.mjs) → check:api → 전체 vitest 1회
