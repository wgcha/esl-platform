# 이어받기 — v0.25.1 C2 파이썬 그림 색 (wip/v0.25.1-c2)

- 기준 e9745958(계약 개정 1 + resources/colormaps.json). 계약 `docs/contracts/esl_view3d_scene_legend.md` §5.7 L12~L18 · §5.8 · §5.9 · §9.5 37~39·43·44·45(보고서 쪽).
- 환경: `/tmp/rdenv_c2.sh`(= `/tmp/rdenv_main.sh` + REPO_ROOT 이 worktree + PYTHONPATH packages/beadgraph/src). `source` 후 `$PY -m pytest …`.

## 단계
| # | 내용 | 상태 |
|---|---|---|
| 1 | `esl/io/colormaps.py`(새) — load·map_for·rgb·css·table·special·as_json, 검사 = CONFIG_INVALID | 완료 |
| 2 | L12 `esl/opt/png.py`(`_SEQ` 삭제 → seq), L13 `esl/doe/select_render.py`(BLUE·RED·WHITE·GRAY 삭제 → div·special none, `color_meta()`) | 완료 |
| 3 | L14·L15 `esl/report/case_report.py`(JS `VIR`·`DIV` 삭제 → 데이터 JSON `cmap` = as_json(seq, div)) | 완료 |
| 4 | L16·L17 `esl/library/report_analysis.py` `heatmap`(불투명 css 색) + 문구 :142, `esl/library/compare.py` 문구 :565 | 완료 |
| 5 | L18 `esl/doe/report_doe.py` `_ratio_cell`(C 변화율 div, ±0.5) + 표 설명 문구 | 완료 |
| 6 | 시험 `tests/io/test_colormaps.py`(37·38·39) | 완료 |
| 7 | 골든 갱신·V-43·44·45 시험 | 완료 |
| 8 | main 대비 비교(43 픽셀·44 HTML) | 완료 — 아래 |
| 9 | tests/ 전체 1회 | 완료 — 아래 |

## 통합 때 메인이 넣을 것
- `esl/doe/stages.py:8528`(bd_select_grid manifest) 한 줄:
  `"color": {"v_max": V, "unit": "mm", **sr.color_meta()}, "selection_sha256": L["rev"]["selection_sha256"],`
  (`sr` = 같은 함수 안 `from esl.doe import select_render as sr` 이미 있음)
- **배포 묶음 목록에 `resources/colormaps.json` 추가 필요**(계약 §5.8 "설치 스크립트 변경 없음" 가정과 다름 — 목록이 파일별로 적혀 있음):
  `deploy/install-common.ps1:28` `$EslAppItems`, `deploy/collect-offline.ps1:144`, `deploy/collect-offline.sh:117`(+ 머리 주석 :20),
  시험 `tests/deploy/test_bead_doe_deploy.py:217·251·252`·`tests/deploy/test_deploy_collect.py:61` 기대 목록. 빠지면 서버에서
  bead_map.png·썸네일·보고서 생성이 `CONFIG_INVALID`(colormaps 를 읽을 수 없음)로 실패.

## 메모
- main 구조 픽셀 골든(V-43): 썸네일 BG·EDGE 라벨 마스크 sha `c2617a10…`, 평면도 BG·EDGE_GRAY·HATCH·ORANGE·GREEN·BLACK 라벨 마스크 sha `26e2b031…`
  (생성 스크립트 = 저장소 밖 `/tmp/c2work/golden_masks.py`, main 코드로 계산 → 새 코드도 같은 값 확인).

## main(e9745958) 대비 독립 비교 (저장소 밖 `/tmp/c2work/gen_reports.py`·`cmp_out.py` — main 트리는 `git archive e9745958 esl resources`)
- 같은 입력으로 main·새 코드 각각 생성: `keepout.png`·공칭 썸네일 = **바이트 동일**. `bead_map.png`(1600×900)·썸네일 3종 = 크기 같음,
  구조 픽셀(바탕·외곽선·빗금·주황·초록·글자 / 바탕·경계선) 라벨 마스크 동일, 바뀐 픽셀은 모두 색 칸. 썸네일 깊어짐 → R>B 4038 px·B>R 0, 얕아짐 → B>R 3896·R>B 0.
- HTML: case = 데이터 `map`·`sec` 동일, 다른 줄 = `cmap` 추가 + JS lerp·변수 이름뿐. analysis·compare·doe = 색 문자열(rgb/rgba/var(--seq|pos|neg)/fill-opacity)과
  §5.7 문구(compare "빨강 증가, 파랑 감소"·설명 "빨강 = 늘어남, 파랑 = 줄어듦"·doe 표 설명 `<p>` 1줄)를 지우면 **문자열 동일**.
- Case 보고서 JS lerp 를 node 로 실행 = 파이썬 `colormaps.css` 256색 + NaN·범위 밖 일치(V-0251-44 시험 안, node 있을 때).

## 시험에 추가하면 좋은 것(통합 뒤 — stages.py 한 줄이 들어간 다음)
- `tests/doe/test_select_render.py::test_select_stage_flow` 의 `assert gm["color"]["unit"] == "mm" …` 줄 뒤에
  `assert gm["color"]["map"] == sr.color_meta()["map"] == "diverge"` (지금은 stages.py 가 C1 소유라 넣지 않음 — 넣으면 이 브랜치에서 실패).

## 시험 결과
- C2 범위(test_colormaps·select_render·opt/test_post·opt/test_report·case_report·report_doe·library analysis·compare): **82 passed**.
- tests/ 전체 1회(35:56): 1896 passed · 192 skipped · **23 failed** =
  - 허용 3: `test_large_model_cad_share`(gmsh 없음)·`test_v0160_bytes_skip_policy[h8]`·`[h5open]`.
  - 시간 경계 흔들림 1: `test_validate_tiers.py::test_v0245_vt_12_report_new_rows_and_old_render`(보고서 생성 시각 초 차이 — 다시 돌리면 통과).
  - **report.html 바이트 고정 골든 19**(main e9745958 트리에서는 50개 모두 통과 — 이 변경 때문): 차이 목록이 모두 `report.html`·`07_report/report.html`
    **하나뿐**(다른 결과 파일은 바이트 동일 = "나머지 바이트 불변" 확인).
    `tests/cumulative/test_cumulative_e2e.py::test_b1_noncumulative_outputs_identical_to_v072`,
    `tests/doe/test_jig_grid_golden.py::test_old_snapshot_bytes[cmp_old|cmp_norank|step_old]`,
    `tests/doe/test_jig_move.py::test_v0244_jig_1_golden_bytes`,
    `tests/doe/test_pos_u_golden.py::test_old_snapshot_bytes[sel_case_jig|sel_step_jig]`·`test_pos_u_block_without_u_vars_is_node_path[sel_case_jig|sel_step_jig]`,
    `tests/doe/test_vbead_golden.py::test_no_virtual_beads_bytes[old|vb_block × sel_case_jig|sel_step_jig|sel_step_jig_pu]`(6),
    `tests/pipeline/test_validate_sources.py::test_v0243_val_1_golden_full_bytes`,
    `tests/pipeline/test_validate_tiers.py::test_v0245_vt_6_golden_v0244_plus_intended_only`·`test_v0245_vt_8_old_results_report_stage_reads_only[jig|never]`.
  - 원인 = 계약 §7.2·V-0251-10(개정 1)은 그림 3종(report.html 등)을 "같은 입력 → 같은 바이트" 목록에서 뺐지만 §5.9 골든 갱신 목록에 이 19개가 빠짐.
    지시대로 §5.9 목록 밖 골든은 고치지 않음 → **통합 때 메인 결정 필요**: 이 시험들의 비교 집합에서 report.html 을 빼거나(권장 — V-0251-10 개정과 같은 뜻)
    report.html 해시만 새로 기록.
