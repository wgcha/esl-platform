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
| 7 | 골든 갱신·V-43·44·45 시험 | 진행 |
| 8 | main 대비 비교(43 픽셀·44 HTML) · tests/ 전체 | 남음 |

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
