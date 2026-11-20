# 이어받기 — v0.24.3 묶음 A(코어) — 작업 트리 /home/claude/wt_v0243 (release/v0.24.3)

계약: docs/contracts/esl_validate_sources.md (P1), 결정 D-0.24.3-VAL-1~17. 시험 환경: /tmp/rdenv_v0243a.sh (REPO_ROOT 바꾼 사본).

## 상태: 묶음 A 완료(시험 통과) — B(백엔드)·C(프런트)·통합 남음
- 골든 기록(V-1) — 커밋 b1dd9225(코어 변경 전), tests/fixtures/val_src/golden_v0242.json
- esl/val_src.py(계획 표·문구·row_status·limit_info·src_block·sources.json 행), esl/val_metrics.py(순수 지표 + evaluate)
- pipeline: _field_base 분리, stage_validate 출처별(05_val/<dir>/, sources.json), _val_solve
- esl/mech/shell.py: ShellModel.keep_factor/kept_factor(선택, 기본 끔)
- config: VALIDATION_SOURCES_DEFAULTS·SCHEMA validation.sources·OPTIONAL_KEYS·validation_sources_settings, esl.example.yaml 주석 줄
- 07_report 5절 끝 출처 표(<!--val-src--> 표식으로 감쌈 — 골든 비교가 떼어 냄)
- core_adapter: val_src_plan·val_row_status·val_reason_text
- 시험: tests/test_val_src.py, tests/pipeline/test_validate_sources.py, tests/report/test_report_val_src.py,
  tests/cumulative/golden_util.py(v0.7.2 골든 비교에서 v0.24.3 추가 산출물 제외 — v0.12.1 ADDED_KEYS 와 같은 원칙)

## 계약과 다른 점(통합 때 계약 부록에 적을 것)
1. legacy 해 = `ShellModel.solve` 그대로 + `keep_factor` 로 그 분해를 출처 해에 재사용(계약 §4.1 의 `sm.factorize` 대신).
   이유: 기존 tests/pipeline/test_disp_primary.py 가 ShellModel.solve 를 monkeypatch(응답 주입·호출 1회 계수) — 무수정 통과.
   분해 1회·legacy 산술 v0.24.2 그대로·단계 요약 solver 키 그대로(n_factorizations 없음). 출처 해 = 따로 푼 sm.solve 와 비트 동일(V-3).
2. sources.json: 행 status 가 done 이 아니면 dir = null(폴더 없음). solve.groups[] 에 assembly_s, solve.eval_s{key: s} 추가.
   legacy 해 solve_s = 전체 − factor_s − assembly_s, eval_s = 변형률 회복 + 지표 + 파일 쓰기.
3. 판정 불가 출처(fallback None): noise_hotspot_strain_rel 은 S4 공통 값 그대로(ε_val 에 의존하지 않음), hotspot·제외·field·
   strain_ref·disp = 빈 목록/null, 파일 = validation.json·validation.csv 만.
4. hotspots_excluded "full 과 같음"(V-3) = 제외 요소·사유·ε_rad 가 같음(ε_val 은 출처 응답 값 — hotspot_rows 정의 그대로).
5. tests/cumulative/golden_util.py 수정(새 파일·보고서 표 블록 제외) — "기존 시험 무수정"의 예외(의도된 산출물 추가).

## 측정(합성 평판 21,901 노드·2코어·SuperLU, 저장소 밖 /tmp/v0243a_scratch/bench.py)
검증 출처 끔 9.5 s → 켬 12.2~12.4 s(+2.7~2.9 s, +29~30 %). 분해 6.9 s 공유, 출처당 해 0.24 s + 지표·쓰기 1.07 s.
05_val 5.2 MB → 15.5 MB(출처당 루트와 같은 크기). 194k 노드 외삽(분해 ~N^1.5, 나머지 ~N): +≈ 11~12 %.
