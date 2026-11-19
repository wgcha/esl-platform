# HANDOFF — v0.24.1 묶음 A(코어)·B(백엔드) (3D 보기 하중 출처 일반화)

- 작업 트리 `/home/claude/wt_v0241`(브랜치 release/v0.24.1). 계약 `docs/contracts/esl_view3d_sources.md`. 프런트(묶음 C)는 다른 트리.
- 시험 환경: `/tmp/rdenv_v0241.sh`(= rdenv_main.sh, REPO_ROOT 만 바꿈) source → `$PY -m pytest …`. PG16 꺼져 있으면
  `su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/rdpg/data -o '-p 54329 -h 127.0.0.1' -l /tmp/rdpg/restart.log start"`.

## 진행
1. [x] v0.24.0 바이트 골든 기록(변경 전, f29eeec0 코드):
   - `tests/test_view3d_golden.py` → `tests/fixtures/view3d/golden_v0240.json`(build_view·pack_values sha256)
   - `backend/tests/test_view3d_src_api.py::test_legacy_view3d_bytes_equal_v0240_golden` → `backend/tests/fixtures/view3d_case_v0240.json`
   - `backend/tests/test_doe_v3d_src_api.py::test_regenerate_equals_v0240_golden` → `backend/tests/fixtures/doe_regen_v0240.json`
   - `tests/doe/test_v3d_recon_doe.py::test_existing_view3d_files_equal_v0240_golden` → `tests/fixtures/view3d/doe_view3d_v0240.json`(환경 서명 일치 시만)
   - 골든은 다시 기록 금지(`ESL_GOLDEN_RECORD=1` 은 파일이 없을 때만 씀).
2. [ ] A 코어: esl/view3d.py(recon_fields·pack_disp·build_recon), esl/view3d_src.py, core_adapter 래퍼, stages._ns_view3d 재현, DEFAULTS view3d.recon
3. [ ] B 백엔드: services/view3d.py ?src·sources·recon, routers, services/doe.py SOURCE_ADD, schemas, config, yaml, openapi
