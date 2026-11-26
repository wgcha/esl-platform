# release/v0.24.9 C1 진행 handoff (코어 + beadgraph)

계약 docs/contracts/esl_bead_pos_u.md, 결정 D-0.24.9-PU-1~17·BM-1. 시험 환경 /tmp/c1_249/env.sh(= /tmp/rdenv_main.sh, REPO_ROOT=wt_v0249,
PYTHONPATH += packages/beadgraph/src). pytest --basetemp=/tmp/c1_249_bt -o tmp_path_retention_policy=failed.

## 계약면(백엔드·프런트가 맞출 것 — 첫 커밋에서 고정)
- 설정(DEFAULTS·pydantic·yaml 2, 같은 이름): `bead_doe.pos_u {enabled true, range_rel 0.25, max_rel 0.5, gap_rel 0.5, hold_frac_max 0.2}`,
  `bead_doe.load_follow {cell_mm 3.0, noise_floor_min 0.01}`(cell_mm 범위 load_transfer.cell_min_mm..CELL_MAX_MM, noise_floor_min 해시 밖).
- 스냅샷(새 select 그래프 스터디만): `doe.pos_u {schema 1, range_rel, max_rel, gap_rel, hold_frac_max, enabled}`,
  `doe.load_follow {schema 1, cell_mm}` (+ noise_floor_min 은 코어가 설정값으로 읽음). 복제 = 원 블록 그대로.
- params[] U 행: `{name "B<n>_U", type "U", bead, tier, nominal 0.0, unit "mm", feasible [lo,hi], feasible_source "estimate",
  default_range [lo,hi], use_default false, group_members, dir {xi, eta}, dir_text, w_ref, guard? (기존 형식 — usable 비대칭), group_signs? {이름: ±1}}`
- beads[](derive·params.json): `u_reason {code, text}` (U 행 없을 때만, U_OFF 는 키 없음).
- 사유 코드(순서 고정): U_OFF, U_NETWORK, U_AREA, U_CLOSED, U_ONE_SIDE, U_NO_ENTRY, U_HELD, U_TIE_MIXED. 문구 = resources/doe_messages.json
  (U_AREA 1점 골격 문구 = U_AREA_POINT). dir_text 코드 U_DIR_XI_POS·XI_NEG·ETA_POS·ETA_NEG·OUT·IN(문구 표).
- 422: type U 는 lo ≤ 0 ≤ hi 아니면 DOE_RANGE_INVALID(문구 U_RANGE_INVALID "위치 범위는 0 을 포함해야 합니다"), "> 0" 검사 제외.
- matrix.json `load_follow: "node"|"spatial"`(pos_u 블록 있는 스냅샷만 키), result.json `load_follow {mode, cell_mm, dF_max, dM_max,
  corr_rel_max, small_frac_max, d000_shift_rel}`(spatial 만), 정보 LOAD_FOLLOW_SPATIAL{cell_mm, n_pos_vars}·PU_LIN_SKIPPED·PU_PARTIAL·PU_GUARD.
  순위 정의 꼬리 문구 LOAD_FOLLOW_TAIL "하중 공간 고정({cell_mm} mm)".
- section(esl/morph/section.py): PLAN_COLUMNS += pos(graph pkg_u·elems none·paicad native·none none), `pos_plan(row)`, `u_reason(facts)`,
  `u_reason_doc(code, msgs, point)`, `u_feasible(W_ref, g+, g−, max_rel, gap_rel)`, `u_default(W_ref, feas, range_rel)`, `u_range_ok(lo, hi)`,
  `u_dir_code(dir2, turn_deg)`, `u_mirror_signs(members, h)`, `pos_u_hash_view(pos_u)`.
- 지그 표식(esl/mech/jig_bc.py): `support_marks_full(BC, x0, smax, method_row=None) -> [(node_idx, kind, dirs, val)]`,
  kind ∈ MARK_KINDS(tie_fixed·tie_disp·tie_spring·aux_inplane·support321), dirs = [[x,y,z]…](행 방향), val = tie_fixed [0…]·tie_disp [g…]·
  tie_spring {k:[…], g:[…]}·aux_inplane [값…]; `mark_rows(marks, node_id) -> [{node_id, dof, kind, dirs, val}]`(dof = 옛 문자열 "123"/"ij");
  `mark_kind_of(method_row)`; 옛 `support_marks(...)` 2튜플 = 어댑터(바이트 불변). 사이드카 manifest.json supports 행 += kind·dirs·val
  (esl.view3d.SUPPORT_EXTRA_KEYS — 있을 때만). 백엔드 Case 3D(_jig_supports)는 support_marks_full + mark_rows 를 써서 같은 값.
- beadgraph 1.3.0(U_RULES 1) — 루트 pyproject·deploy/requirements.lock 은 C1 이 1.3.0 으로 올림(B1 은 확인만).

## 끝난 일
- 골든 26410604, 계약면 45e4f3a9, 패키지 U 114bdd82, esl 통합 964ba911, 지그 표식·시험 a9c41bb2, findings·표(work/findings.md,
  work/v0249_u_table.md — H6·H5 U 가능 비드 15: 뒤집힘·오목·가드 left 0, range guard blocked 0)
- 시험: packages/beadgraph 117 passed·2 skipped(기존), selftest PASS, tests/doe/test_pos_u 11, test_pos_u_golden, tests/mech BM 10

## 남은 일
- tests/doe·morph·mech 전체, tests/ 전체 결과 확인(허용 실패 3 외 0)
- 백엔드 B1: derive_v2(pos_u=, tie_node_ids=) 호출, 스냅샷 pos_u·load_follow 블록, Case 3D support_marks 키워드 일반형
- 프런트 F1: U 행 표시·u_reason 툴팁·load_follow 결과 줄

## 다음 명령
source /tmp/c1_249/env.sh; cd /home/claude/wt_v0249; $PY -m pytest -q tests/ --basetemp=/tmp/c1_249_bt -o tmp_path_retention_policy=failed
