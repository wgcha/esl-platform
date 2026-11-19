# 이어받기 — release/v0.24.2 묶음 A (TCL·코어, 계약 esl_bforce_ondemand.md)

작업 트리 `/home/claude/wt_v0242`(브랜치 `release/v0.24.2`, 계약 커밋 faa9b764). 묶음 B·C 는 `/home/claude/wt_v0242_wk` 에서 — worker/** backend/** frontend/** 는 건드리지 않음.
시험 환경: `/tmp/rdenv_v0242a.sh`(REPO_ROOT=/home/claude/wt_v0242, PG16 54329 `/tmp/rdpg/data`, `$PY`=/tmp/rdvenv/bin/python).

## 회귀 골든 (변경 전, faa9b764)
- 스크립트 `/tmp/v0242a/gold.py <work> <out.json>` → `/tmp/v0242a/gold_before.json`(두 번 실행 동일 확인).
  TCL mock: default·bf_on·bf_on_chunk·dump·dump_bf_on 출력 CSV sha + done.json(시간·경로·핸들 제외).
  파이프라인 Case: 비덤프+bf·plain·덤프(strain_tensor) 01_extract·04_esl 지문 + ESL 요약 forces.bforce/fint.
- TCL 골든 값은 `tests/io/test_tcl_bforce_only.py:GOLD_V0241` 에 박음(V-0242-BFD-3).

## 진행
- [x] 1. TCL bf 전용 모드(`bf_only`·`bf_frames`, `run_bf_only`, 공용 `bf_open`·`bf_chunk`·`bf_close`), hwmock 호출 기록, 시험 1~3.
- [ ] 2. `esl/io/backup.py`, `esl/io/bforce_csv.py`(has_frame·_pack_kinds·frame_data kinds.frames), `esl/io/bforce_ondemand.py`, 시험 4.
- [ ] 3. pipeline(BF_EXTRACT_* · BF_NO_DATA 사유), config on_demand, 시험 5·6·12.
- [ ] 4. pytest tests/ 전체, 골든 after 비교.
