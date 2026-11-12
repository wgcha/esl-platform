# release/v0.18.2 인계 (진행 중 — 완료 시 삭제)
목적: 이슈 #63 2026-11-12 06:40Z 진단 — ④/③ 메시 사다리(cad_relaxed 분리·freeform 비다양체·tria 상한) + ① 그래프 방식 평면도 자료.
워크트리: scratchpad/wt-182, 기준 origin/main 3e9f35f(v0.18.1).
## 상태
- [x] 1 cad_relaxed 분리(isolate·timeout_s·fidelity_samples, interrupted 기록, 부모 재실행) — [ ] 파라미터 재검토 측정(scratchpad/rxparam.py)
- [x] 2 freeform 면별 discrete surface(compare.freeform.surfaces occ_faces, 실패 시 classify)
- [ ] 3 tria 300 s 검토
- [x] 4 derive_v2 plan 자료(bead_graph._graph_figures, BG-D-46) — [ ] 스크린샷(frontend/scripts/screenshots-v0182.mjs)
- [x] 5 회귀 시험 tests/doe/test_mesh_v0182.py — [ ] 그래프 plan 시험
- [ ] 계약·decisions·VERSION·CHANGELOG·openapi
- [ ] test-all·regress·sel_regress·1915면 비교

## 측정
- 1915면 main 3e9f35f: 669.5 s(cad 491.6 시간 초과 → cad_relaxed 18.7 실패 → freeform 72.9 REMESH_CLASSIFY_FAILED → tria 85.8 READY 234,721) — scratchpad/b182/main.log
