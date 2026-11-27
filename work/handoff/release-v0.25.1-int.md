# release/v0.25.1 통합 (메인) — 이어받기

계약 docs/contracts/esl_view3d_scene_legend.md(개정 1 + §15.2~§15.5 통합), D-0.25.1-VL-1~19·INT-2~6. 환경 /tmp/rdenv_v0251int.sh(= /tmp/rdenv_main.sh, REPO_ROOT=wt_v0251, PYTHONPATH += packages/beadgraph/src). frontend/node_modules = wt_v0251_f1b 에서 cp -a.

## 단계
| # | 내용 | 상태 |
|---|---|---|
| 1 | merge b1·c2·f1a·f1c·f1b | 완료 — 충돌 0 (INT-1) |
| 2a | stages.py select 썸네일 color_meta + test_select_stage_flow 단언 | 완료 83de2f67 |
| 2b | colormaps.json 배포 목록(install-common.ps1·collect-offline.ps1/.sh + 시험 2) | 완료 83de2f67 |
| 2c | 바이트 골든 19건 report.html 제외(VT-6·8 = 색 코드 되돌림 비교) | 완료 6149c422 — 19건 통과 |
| 2d | 진한 칸 흰 글자(자원 text 블록 — 화면·보고서 같은 규칙) | 완료 6149c422 |
| 2e | api/types.ts color.map + DoeThumbGrid 캐스트 제거 | 완료 6149c422 |
| 2f | 매뉴얼·CHANGELOG·field_check_v0251·VERSION·버전 시험 | 완료 2a7e218f |
| 2g | 계약 §15.2~§15.5 INT, decisions, handoff 6개·findings VL-C1 절 삭제 | 완료 |
| 3 | 시험 | 진행 — 결과는 아래 |

## 시험 결과
(채움)
