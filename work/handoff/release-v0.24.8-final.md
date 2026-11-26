# release/v0.24.8 마무리 진행 (끝나면 삭제)
- [x] 1 merge fix/scx-path-segments (3b5a327d, 충돌 없음, push)
- [x] 2 형상별 오차 범위(JG-26) 코드: rank.noise_floor_by_id, stages _jg_nf(nf_base)·_jg_nf_shapes·_jg_post applied·_rank_view_one·_post_view3d, 문구 doe_messages(JG_RANK_NOISE·_MISMATCH·MESH_MISMATCH_SHAPE), report 1줄, schemas·types·openapi, 프런트 GRID_TEXT·gridOf·정보 코드
  - 측정(Case h5 쿼드): 비드 3.71 mm 같은 메시 4.15 % → nf 0.03 noise False·n_improved 2; 전삼각 Delaunay h3 4.21 % → nf 0.05 noise True
- [x] 3 문서(계약 §1.4·§3·§6·§17, JG-26, CHANGELOG, user.md, field_check_v0248.md)
- [ ] 4 스위트: tests/ → backend → worker → vitest 단독 → typecheck·build·check:api·openapi
