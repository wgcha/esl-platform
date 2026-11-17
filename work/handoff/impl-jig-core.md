# impl-jig-core 이어받기 (브랜치 impl/jig-core)

- 계약: docs/contracts/esl_jig_rank.md v0.23.0 §5.1·§8 (Core 소유: esl/doe/jig.py, tests/doe/synth_jig.py, tests/doe/test_jig.py)
- 완료: jig.py 전 함수(계약 시그니처), synth_jig.py(plate·tie_groups·neighbors·surface·rib_x·write_rad_with_neighbors·case)
- 남음: tests/doe/test_jig.py (V-JIG-1~5, 6 모듈, 8 slow, 15, 16) → 회귀 → 계약 정정(필요 시)
- 관찰: V-JIG-1 정확 재현은 ridge 0 에서만 umax_err ≤ 1e-8 (기본 1e-8 은 ~1.6e-8). V-JIG-4 cancel_rel ≤ 0.5 는 막(면내) 자기평형
  목표가 있으면 원리적으로 불가(면내 맞춤 하중이 굽힘 하중보다 10³배) — 반환에 보고.
- 실험 스크립트: /tmp/jigx/e*.py (임시)
