# release/v0.19.1 인계 (완료 시 삭제) — #63 BG_BASIS_LEAK(B10_D·B11_D)
- 결정: 후보 A(걸친 섬의 바깥 벽 접촉 노드도 hold) + 기저·검사 공용 노드 규칙 `zones.movable_nodes`(BG-D-47).
- 완료: morph.py·checks.py·zones.py, 합성 `testing/synth_stepboss.py`·`fixtures/stepboss.npz`(gmsh 4.15.2 = scratchpad/gmsh415),
  `tests/test_stepboss.py`, conformance V-BG-19(selftest). H5·H6 모든 단일 세그먼트 D·W 기저·레시피 바이트 동일 확인.
- 남은 일: 전체 시험(코어 tests/doe·backend·worker 관련) 결과 확인, regress none·cad 모드별 재비교(scratchpad/reg191/run2.sh), 핸드오프 삭제·최종 커밋.
- 비교 자료: scratchpad/b191/cmp.py, regress 기준 scratchpad/reg191(main191 = origin/main 워크트리).
