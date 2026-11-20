# 이어받기 — release/v0.24.4 P2a (A2a 코어 공용)

- 계약: docs/contracts/esl_jig_case.md (계약 커밋 413620c1). 범위 = P2a 만(P2b·P2c·P3 밖).
- 시험 환경: /tmp/rdenv_v0244.sh (REPO_ROOT=/home/claude/wt_v0244), PG 54329.

## 진행
1. [x] 골든 먼저 — tests/doe/test_jig_move.py + tests/fixtures/jig_case/golden_v0243.json (study 41 파일, case 36 파일, 413620c1 코드로 기록)
2. [ ] 모듈 이동(esl/mech/jig.py·esl/rad/surface.py·esl/rad/solid_faces.py·esl/io/fixed_scan.py·esl/io/messages.py + 심)
3. [ ] jig_bc(3방식·tie_dofs·3-2-1 면내) + ShellModel 확장
4. [ ] 지표 Π + 합성 시험
