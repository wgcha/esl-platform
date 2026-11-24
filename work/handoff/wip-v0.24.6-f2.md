# wip v0.24.6 W-F2 (스터디 3행·지그 방식 4상태·jd/js 3D 열) — 완료(통합 대기 1건)
브랜치 wip/v0.24.6-f2 (base wip/v0.24.6-f1). 변경: pages/doe/{DoeStudy.tsx,doeTabs.ts}, api/types.ts(DoeJigMethodOut·DoeJigOut.methods/tie_dofs·DoeResultOut.view3d_jd*·js*), styles.css §6 블록(.doe-result-rows/.doe-row-*), __tests__/doe_v0246.test.tsx(13, 새), 의도 변경 시험 갱신(doe_v0233·doe_ui_tidy 선택자, jig_modes·jig_group 사유 문구, v0241_study_sources add testid), scripts/screenshots-v0246-f2.mjs.
- 3행: .doe-result-rows(testid doe-result-rows, id doe-load-panel) > doe-row-3d | doe-row-tables(.doe-col-rank | .doe-col-pe) | doe-row-sens.
- 지그 방식: jigMethodState(r,key)·JIG_STATE_TEXT(문구 한 곳)·jigMethodNote, 열 LoadSource.jigMethod. 사유 줄 testid jig-unavail-note(data-src·data-state, title=전체).
- 쌍 3D: Compare3D·JigDiag·ReconDiag 가 useViewerSync(study_design|study_jigdiag|study_recon)+plan 사용(deformSync 제거).
- 열: pairKeys += support·disp(jd·js·jig·bf·fi), add 열 jd·js(legacy null).
통합 TODO: B1 이 OpenAPI 에 jig.methods·tie_dofs·view3d_jd*·js* 를 넣으면 check:api 와 scripts/check-api.test.mjs 통과(지금은 "스키마에 없는 키" 실패 — 백엔드 미병합 때문).
F1 필요 사항: 없음. 옛 스크립트 screenshots-v0233/v0240.mjs 는 testid doe-result-2col 을 찾음 — 갱신 필요(소유 밖).
측정(mock doe-40, 스크린샷 /home/claude/shots/v0246_f2_{2560,1920}[_rows23].png): 3D 칸 2560 = 1200x820, 1920 = 889x702. 행 높이 2560: 3D 1115 · 표 1117 · 민감도 407 (≤1386), 1920: 1021 · 796 · 359 (≤1032).
