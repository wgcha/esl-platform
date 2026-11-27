# wip v0.25.2 B1 (backend + worker) — 이어받기

브랜치 wip/v0.25.2-b1. 소유: backend/**, worker/**, config/esl_platform*.yaml, docs/contracts/openapi_p1b.json, backend/tests·worker/tests.

## 진행
- [x] 설정 pydantic(AltairCfg frame_fill_*, BeadDoeRankJigGridForceCfg·tie_force·tie_force_far_warn_mm, view3d.jig_force_marks_max, compare.double_sheet) + yaml 2개 + test_doe_config 거울 가드
- [x] core_adapter frame_fill_*·frame_point 래퍼, worker/esl_worker/frame_fill.py(facts·fill_state·request_extra·evaluate·LOG·CAUSE_TEXT)
- [x] backend GET/PUT /tstar(frames·frames_have·fill·history.frame_index, 후보 밖 manual 저장, FRAME_NOT_FOUND·FRAME_NOT_EXTRACTABLE), ESL 작업 사전 점검(fill_settings)
- [x] executor._frame_fill 훅(경계력 보충 바로 앞) — 단위 시험은 worker/tests/test_frame_fill.py(다음)
- [x] 스키마 통과 n_ref·counts·via·tie_marks·n_forced_shapes·n_ref_shapes(없으면 키 없음) + OpenAPI 재생성
- [x] worker 시험 worker/tests/test_frame_fill.py(17, 가짜 hw fr_only — backend/tests/h3d_support.py 에 모드 추가), backend/tests/test_v0252_b1_api.py(16)
- [x] 관련 파일 통과: worker test_bf_ondemand·p1b_e2e·menu_tstar·run_all_chain·h3d_extract, backend test_run_all·menu_restructure·p3_ux·doe_config·doe_v0251_b1_api·view3d_api·doe_jig_view_api
- [ ] backend 전체 1회 · worker 전체 1회 — /tmp 여유 20.36 GiB(21.35e9 B) < 게이트 21.5 GB 라 보류(예비 20 GB 때문에 INSUFFICIENT_STORAGE 오탐). 여유가 생기면 `-o tmp_path_retention_policy=failed` 로 1회씩
