# 이어받기 — release/v0.24.2 묶음 A (TCL·코어, 계약 esl_bforce_ondemand.md)

작업 트리 `/home/claude/wt_v0242`(브랜치 `release/v0.24.2`, 계약 커밋 faa9b764). 묶음 B·C 는 `/home/claude/wt_v0242_wk` 에서 — worker/** backend/** frontend/** 는 건드리지 않음.
시험 환경: `/tmp/rdenv_v0242a.sh`(REPO_ROOT=/home/claude/wt_v0242, PG16 54329 `/tmp/rdpg/data`, `$PY`=/tmp/rdvenv/bin/python).

## 회귀 골든 (변경 전, faa9b764)
- 스크립트 `/tmp/v0242a/gold.py <work> <out.json>` → `/tmp/v0242a/gold_before.json`(두 번 실행 동일 확인).
  TCL mock: default·bf_on·bf_on_chunk·dump·dump_bf_on 출력 CSV sha + done.json(시간·경로·핸들 제외).
  파이프라인 Case: 비덤프+bf·plain·덤프(strain_tensor) 01_extract·04_esl 지문 + ESL 요약 forces.bforce/fint.
- TCL 골든 값은 `tests/io/test_tcl_bforce_only.py:GOLD_V0241` 에 박음(V-0242-BFD-3).

## 진행
- [x] 1. TCL bf 전용 모드(`bf_only`·`bf_frames`, `run_bf_only`, 공용 `bf_open`·`bf_chunk`·`bf_close`), hwmock 호출 기록, 시험 1~3. (a6603f96)
- [x] 2. `esl/io/backup.py`, `esl/io/bforce_csv.py`(has_frame·read_doc·doc_frames·_pack_kinds·frame_data kinds.frames), `esl/io/bforce_ondemand.py`, pipeline·config, 시험 4. (27f4d668)
- [x] 3. 시험 5·6·12(코어). (1f4cd21d)
- [x] 4. pytest tests/ 전체 = 3 failed(허용: test_large_model_cad_share·test_v0160_bytes_skip_policy[h8]·[h5open]) / 1404 passed / 192 skipped.
  관련 worker·backend 시험(test_doe_bforce_add·test_h3d_extract·view3d_src·doe_bforce·doe_fint·doe_v3d_src) 48 passed.
  골든 after(`/tmp/v0242a/gold_after3.json`) = before 와 같음: TCL 5개 시나리오 전부, 파이프라인 bf·plain·dump 의 01_extract·04_esl 전부.
  다른 것 1개(의도): 덤프 Case(기록 없음) ESL 요약 BF_NO_DATA·FINT_NO_DATA reason 문구.

## B(워커)가 쓰는 서명·형식 (계약 §2.4·§4.1 그대로, 다른 점만 표시)
- `esl.io.bforce_csv.has_frame(extract_dir, frame) -> bool`
- `esl.io.bforce_ondemand.merge(case_dir, fill_out, frames, *, tag, names) -> {frames_before, frames_after, added, dup, kinds, rows, backup, warnings}`
  오류 EslError: `BF_FILL_OUTPUT`(bf 전용 성공 출력 아님·요청 프레임 없음), `BF_FILL_MISMATCH`(n_frames·시간 불일치), **추가** `BF_FILL_MERGE`(01_extract frames.json·model.npz 읽기 실패·병합 중 bforce.json 계속 바뀜). OSError 그대로.
  dup 만이면 아무것도 쓰지 않고 반환(added []). 새 프레임 종류 0 = json 만(npz 그대로). backup = `_backup/<UTC>/01_extract`(case 기준).
- `record(extract_dir, attempt)` — attempt 필수 `frame_index`·`status`(ok|failed|skipped), `code` 없으면 status 로(failed→BF_EXTRACT_FAILED, skipped→BF_EXTRACT_SKIPPED, ok→null), `at` 없으면 지금. 깨진 기존 파일은 `<Case>/_backup/<UTC>/01_extract/` 로 옮기고 새로.
- `note(extract_dir, frame, tag)` — `str(job_id) == str(tag)` 비교, tag None = None.
- `no_types_before(extract_dir, names)` — 같은 names(정렬 json 비교)의 가장 최근 ok 시도가 kinds 전부 null 이면 그 시도 dict(`at` 포함).
- TCL request: `bf_on 1`·`bf_only 1`·`bf_frames "37"`(공백 구분). done.json: `mode "bf_only"`, `n_frames`, `n_nodes`, `frames`, `frame_times`, `bforce{on,frames,kinds}`, `passes.BF{frames,node_chunks,rows,seconds}`, + `value_format`(추가). 실패 json 은 기존 형식 + `mode` (bf_only 1 을 읽은 뒤).
- 코어 설정 `bforce.on_demand`(BFORCE_DEFAULTS true) — `esl.config.bforce_settings(cfg)["on_demand"]`.

## 계약과 다른 점(보고)
- BF_NO_DATA·FINT_NO_DATA 사유: 기록 없음 + 비덤프 옛 추출 = v0.24.1 문구 그대로, 덤프 방식 = "덤프 방식 추출(변형률 텐서 전 프레임)에는 경계력 결과가 없음 — … 보충(bforce.on_demand)", 병합 뒤 다른 프레임 = "선택 프레임 f 의 경계력 결과가 추출물에 없음(있는 프레임 […])"(04_esl 파일 없음). 코디네이터 지시(실제 원인 문구).
- 병합 백업: 이전 파일을 "이동" 대신 하드 링크(안 되면 복사)로 `_backup` 에 남기고 tmp → replace(원래 자리에 늘 완전한 파일 — 중간 실패 시 옛 자료 유지). 결과 상태는 이동과 같음.

