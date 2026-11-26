# wip v0.25.0 B1 (백엔드 — 가상 비드 kind A)

브랜치 wip/v0.25.0-b1 (기준 release/v0.25.0 59c81863). 환경 /tmp/rdenv_b1v25.sh, pytest --basetemp=/tmp/b1v25_bt -o tmp_path_retention_policy=failed.

## 끝난 일
- config.py `BeadDoeVirtualBeadCfg`(11키) + BeadDoeCfg 검증이 코어 `esl.doe.check_virtual_bead` 호출(opt_core `doe_check_virtual_bead`), yaml 2개 거울.
- doe.py: `vbead_snapshot`(HASH_KEYS 한 곳 = opt_core `morph_virtual_bead`), 새 select 스터디 doe·inputs 블록, 옛 = 응답 null, settings `virtual_bead`(7키). 복제 = 원 블록(코드 변경 없음, 시험으로 고정).
- schemas.py: `VirtualBeadIn`(side 없음, StrictBool flip), `SelectionInV2.virtual_beads`, `SelectionDerived.virtual_beads/vb_frame`(없으면 키 없음 — wrap serializer), settings·inputs 주석. main.py FIELD_ERROR_CODES virtual_beads → VB_INPUT_INVALID.
- doe_select.py: `vbead_of`, 블록·vb_plan(계획 열 vbead)·tie 전달(가상 비드 있는 선택만), 캐시 키, `_vb_norm_cfg`(스냅샷 θ 기본·범위 덮어쓰기), selection_in(빈 목록·flip false 제외), sel_error VB_* 통과, summary 에서 preview 제외, `with_vb_text`(guard.warp text·vb 행 문구).
- openapi 재생성. 시험 backend/tests/test_doe_v0250_b1_api.py 59 passed.
## 남은 일
- backend 전체 시험 1회(/tmp ≥ 21.5 GB·가용 메모리 ≥ 3 GB 일 때), 최종 반환.
## 코어에 필요한 것
- `stages.pos_u_tie_ids_at` 가 pos_u 블록 없으면 빈 배열 → pos_u 끈(enabled false) 스터디에서 가상 비드 VB_FIXED 지그 tie 가 워커와 달라짐.
- `normalize_v2` 가 스냅샷 virtual_bead 블록을 직접 받지 않아 백엔드가 cfg 덮어쓰기로 전달.
