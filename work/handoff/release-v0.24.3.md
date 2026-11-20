# 이어받기 — v0.24.3 묶음 A(코어) — 작업 트리 /home/claude/wt_v0243 (release/v0.24.3)

계약: docs/contracts/esl_validate_sources.md (P1), 결정 D-0.24.3-VAL-1~17. 시험 환경: /tmp/rdenv_v0243a.sh (REPO_ROOT 바꾼 사본).

## 진행
- [x] 골든 기록(V-1) — 커밋 b1dd9225, tests/fixtures/val_src/golden_v0242.json (코어 변경 전)
- [x] esl/val_src.py(계획 표·문구·row_status·limit_info·src_block·sources.json 행), esl/val_metrics.py(순수 지표 + evaluate)
- [x] pipeline: _field_base 분리, stage_validate 출처별(05_val/<dir>/, sources.json), _val_solve(legacy = sm.solve + keep_factor 로 분해 재사용)
- [x] esl/mech/shell.py: ShellModel.keep_factor/kept_factor(선택, 기본 끔 — 기존 test_disp_primary 가 ShellModel.solve 를 monkeypatch 하므로 legacy 해는 sm.solve 그대로)
- [x] config: VALIDATION_SOURCES_DEFAULTS·SCHEMA validation.sources·OPTIONAL_KEYS·validation_sources_settings, esl.example.yaml 주석 줄
- [x] 07_report 5절 끝 출처 표(<!--val-src--> 표식으로 감쌈 — 골든이 떼어 내고 비교)
- [x] core_adapter: val_src_plan·val_row_status·val_reason_text
- [ ] 시험: tests/test_val_src.py, tests/pipeline/test_validate_sources.py(V-2~9·11·시간), tests/report/test_report_val_src.py(V-10)
- [ ] pytest tests/ 전체, ruff·mypy

## 계약과 다른 점(부록 후보)
- 출처 행 상태가 done 이 아니면 sources.json 행 dir = null(폴더 없음).
- solve.groups[] 에 assembly_s 추가, solve.eval_s{key: s}(지표·파일 쓰기 시간) 추가.
- legacy 해 = ShellModel.solve 그대로 + keep_factor 로 같은 분해를 출처 해에 재사용(계약 §4.1 의 sm.factorize 대신 — 기존 시험 무수정).
