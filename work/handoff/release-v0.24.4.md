# 이어받기 — release/v0.24.4 P2a (A2a 코어 공용)

- 계약: docs/contracts/esl_jig_case.md (계약 커밋 413620c1). 범위 = P2a 만(P2b·P2c·P3 밖).
- 시험 환경: /tmp/rdenv_v0244.sh (REPO_ROOT=/home/claude/wt_v0244), PG 54329.

## 진행
1. [x] 골든 먼저 — tests/doe/test_jig_move.py + tests/fixtures/jig_case/golden_v0243.json (study 41 파일, case 36 파일, 413620c1 코드로 기록)
2. [x] 모듈 이동(esl/mech/jig.py·esl/rad/surface.py·esl/rad/solid_faces.py·esl/io/fixed_scan.py·esl/io/messages.py + 심 = sys.modules 별칭) — 골든 통과
3. [~] jig_bc(3방식·tie_dofs·3-2-1 면내) + ShellModel 확장 — 코드·test_shell_bc 완료, test_jig_bc 작성 중
4. [ ] 지표 Π + 합성 시험

## 결정·계약과 다른 점(반환에 명시)
- DEFAULTS["rank"]["jig"] 는 JIG_DEFAULTS 를 import 하지 않고 **거울**(같은 이름·값 시험) — esl.doe 가 scipy 를 끌어오지 않게(백엔드 API 프로세스).
  새 키(JIG_NEW_KEYS)는 DEFAULTS·pydantic BeadDoeRankJigCfg·yaml 2·backend test RANK_DEFAULT 에 B2 가 함께 더함.
- HASH_EXCLUDE 확장은 P2c(기존 test_hash_view_drops_thresholds 기대값) — 값은 jig.HASH_EXCLUDE_V0244.
- 심 = 모듈 별칭(esl.doe.jig is esl.mech.jig) — monkeypatch 시험 무수정 통과.
