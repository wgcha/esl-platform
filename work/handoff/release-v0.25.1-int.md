# release/v0.25.1 통합 (메인) — 이어받기

계약 docs/contracts/esl_view3d_scene_legend.md(개정 1), D-0.25.1-VL-1~19. 환경 /tmp/rdenv_v0251int.sh(= /tmp/rdenv_main.sh, REPO_ROOT=wt_v0251, PYTHONPATH += packages/beadgraph/src).

## 단계
| # | 내용 | 상태 |
|---|---|---|
| 1 | merge b1·c2·f1a·f1c·f1b | 완료 — 충돌 0 |
| 2a | stages.py select 썸네일 color_meta + test_select_stage_flow 단언 | |
| 2b | colormaps.json 배포 목록(install-common.ps1·collect-offline.ps1/.sh + 시험 2) | |
| 2c | 바이트 골든 19건 비교 집합에서 report.html 제외 + §5.9 INT | |
| 2d | 진한 칸 흰 글자(휘도 기준 한 곳 — 화면·보고서 같은 규칙) | |
| 2e | api/types.ts color.map + DoeThumbGrid 캐스트 제거 | |
| 2f | 매뉴얼·CHANGELOG·field_check_v0251·VERSION·버전 시험 | |
| 2g | 계약 §15 INT-n, handoff 삭제 | |
| 3 | 시험 | |
