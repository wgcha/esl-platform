# release/v0.24.9 독립 검증 수정 — 이어받기
- 환경: /tmp/rdenv_v0249fix.sh (REPO_ROOT=/home/claude/wt_v0249, + beadgraph src). 검증 근거 /tmp/verif_v0249/progress.md·scripts/.
- 항목: 1 스터디 지그 고정 3D 표식 한 경로(INT-5) · 2 §5-13 정정 + 채널 골든 · 3 U_SATURATED · 4 U_SHORT_SEG · 5 문서.
## 상태
- [x] 1: stages `_jig_support_rows`(코어 jig_bc.support_rows) — `_jig_view3d`·`_jig_view3d_src`·`_jg_view3d_src` 모두. 시험
  tests/doe/test_jig_view3d_src.py::test_fixed_3d_marks_int5(세 방식 × 스터디 3D post·regen × Case 3D = npz BC), 골든은 v0244 고정 3D manifest 만 제외.
- [ ] 2 · [ ] 3 · [ ] 4 · [ ] 5 · [ ] 전체 시험
