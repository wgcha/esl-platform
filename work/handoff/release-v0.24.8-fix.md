# v0.24.8 독립 검증 수정 진행 (끝나면 삭제)
- [x] 1 옛 ④·③ jig_on_clone/ON_CLONE (unsupported 블록) — backend doe.py, 시험 core_e2e 3건, 목 withOldGridSnapshot doe-62/63, vitest jig_grid
- [x] 2 stages.py _post_view3d 분기 → 계획 dst design, 정적 시험 2건(v0.24.7 비교 줄 동결·git diff 추가 줄)
- [x] 3 MESH_MISMATCH: grid_map.mesh_stats·mesh_mismatch, run jig_grid.json mesh, _jg_nf·_jg_post grid.mesh, 설정 3키(DEFAULTS·pydantic·yaml2·HASH_EXCLUDE), 스키마·types·openapi. 측정 Case h5 쿼드 ↔ Delaunay 전삼각 h3/h4: 개선 4.21/4.77 % → nf 0.05·noise 표식
- [x] 4 JIG_GRID_TIE_SNAP(스터디)·JIG_GRID_TIE_SNAP_SHAPE(형상 경고 = 순위 행 warnings_n)·TIE_MISS/AREA_RATIO 최악 1건 → result warnings + jig.grid.warnings
- [x] 5 문구: rank_note·JIG_GRID_RANK "방식으로"(messages.json 이동), AREA_RATIO 배율 3자리, 격자 정의 GRID_TEXT.jigDef
- [ ] 6 계약·decisions·CHANGELOG·manual
## 스위트
