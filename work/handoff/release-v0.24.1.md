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
2. [x] A 코어: esl/view3d.py(recon_fields·pack_disp·build_recon·unpack_disp 추가만), esl/view3d_src.py(새 — KEYS·CASE_PLAN·REASON_TEXT·
   plan·case_status·check_plan·reason_text·has_load), core_adapter 래퍼(view3d_recon_build·view3d_src_plan·view3d_case_status),
   stages._ns_recon_ref·_ns_recon_one·_ns_view3d(기준 폴더 recon + view3d_<pe>_recon), DEFAULTS bead_doe.view3d.recon=True.
   시험: tests/test_view3d_src.py(V-1·2·4·5), tests/doe/test_v3d_recon_doe.py(V-13 + 골든).
3. [x] B 백엔드: services/view3d.py(RunLoc·row_status·Inputs 행 열 기반·sources·recon·recon_file), routers/results.py(?src·/view3d/sources·
   /view3d/recon·/view3d/recon.bin), services/doe.py(SOURCE_ADD·NEED·add_source 일반화·regenerate 별칭·source_add·v3d recon 키·VIEW3D_FILES),
   routers/doe.py(문서), schemas(View3dSourceRow·View3dSourcesOut·View3dReconArray·View3dReconRanges·View3dReconOut·DoeResultOut 3키),
   config(View3dCfg.case_src_default 검증·BeadDoeView3dCfg.recon), yaml 2개, OpenAPI docs/contracts/openapi_p1b.json.
   시험: backend/tests/test_view3d_src_api.py(V-6~12), backend/tests/test_doe_v3d_src_api.py(V-14 + 골든).
4. [x] 전체 시험: pytest tests/ = 1366 passed·192 skipped·3 failed(허용 3건만), backend/tests+worker/tests = 1285 passed·6 skipped
   (test_view3d_cfg_mirror 기대 dict 에 v0.24.1 키 recon:true 추가 후 통과). OpenAPI --check 최신, gen_view3d_fixture --check 최신.
5. 남은 일(코디네이터·C): 프런트 types.ts 에 새 스키마 반영 후 check:api, CHANGELOG·VERSION·계약 부록(아래 '다른 점'), 스크린샷.

## 계약과 다른 점(코디네이터가 부록에 기록)
- 409 V3D_SOURCE_UNAVAILABLE·V3D_RECON_UNAVAILABLE detail = {code(오류), message, src, **reason_code**, reason} — detail.code 가
  오류 코드라 계약의 출처 사유 `code` 는 `reason_code` 로.
- SOURCE_ADD 행에 열 3개 추가: plan(계획 열 이름 — need plan 용), block(막힘 코드 접미 _UNAVAILABLE|_ADD_UNAVAILABLE), verb(문구 동사구).
  NEED 표 = (판정 함수, need 실패 접미 _UNAVAILABLE|_UNSUPPORTED, 문구).
- source_add = need 를 만족하는 행만(없으면 null) — 옛 키와 정확한 거울. 404 SOURCE_NOT_FOUND 문구의 가능 목록 = SOURCE_ADD 키(jig 포함).
- 코어 추가 공개 함수: view3d.unpack_disp(시험·검증용), view3d_src.reason_text·has_load·legacy_key·COLUMNS. recon.json 에 created_at 없음.

