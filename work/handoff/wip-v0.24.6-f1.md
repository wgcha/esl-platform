# wip v0.24.6 W-F1 (3D 뷰어 P1 8개) — 완료
브랜치 wip/v0.24.6-f1. 구현: frontend/src/view3d/{viewerPlan,viewerPrefs,viewerSync,edges,marks,LegendOverlay,ViewerControls}, colors(bandT·bandedGradient), scene(GPU 재색칠·층·ghost·marks·camera), View3DCard, info, CaseView3D·useLoadView(수동 범위 유지), styles.css 끝 블록, mock/view3dmock(plate300k), __tests__/view3d_viewer.test.tsx(37).
측정: frontend/scripts/screenshots-v0246-f1.mjs (BASE_DIST·NEW_DIST = vite build --mode mock --outDir). 스크린샷 /home/claude/shots/v0246_viewer_*.png.
의도 변경 시험: v0241 rangeKey "r1:bforce"→"r1", stage4_3d 탐침 줄(u·좌표 추가).
F2 에 필요: View3DOptions.plan·viewerSync, useViewerSync(planKey) — 이미 export.
미룸: 없음(P1 8개 전부). 비교 쌍 탐침 동기·P2 는 계약대로 안 함.
주의: jsdom 시험은 셰이더 컴파일을 못 잡는다(vColor vec4 사고) — 셰이더 바꾸면 Playwright 로 확인.
