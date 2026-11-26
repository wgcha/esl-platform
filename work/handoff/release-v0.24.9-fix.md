# release/v0.24.9 독립 검증 수정 — 이어받기
- 환경: /tmp/rdenv_v0249fix.sh (REPO_ROOT=/home/claude/wt_v0249, + beadgraph src). 검증 근거 /tmp/verif_v0249/progress.md·scripts/.
- 항목: 1 스터디 지그 고정 3D 표식 한 경로(INT-5) · 2 §5-13 정정 + 채널 골든 · 3 U_SATURATED · 4 U_SHORT_SEG · 5 문서.
## 상태
- [x] 1: stages `_jig_support_rows`(코어 jig_bc.support_rows) — `_jig_view3d`·`_jig_view3d_src`·`_jg_view3d_src` 모두. 시험
  tests/doe/test_jig_view3d_src.py::test_fixed_3d_marks_int5(세 방식 × 스터디 3D post·regen × Case 3D = npz BC), 골든은 v0244 고정 3D manifest 만 제외.
- [x] 2: 계약 §5-13·§11 PU-C1-1 정정(INT-6), decisions INT-5·6, 시험 test_pos_u_golden.py::test_channel_pos_u_block_u0_allowed_diffs(80 s).
- [x] 3: section.u_motion_ratio·u_saturation, bead_graph._u_sat_entry(guard_selection U)·_apply_single(포화만 = 기본 범위 그대로 + 정보 U_SATURATED),
  설정 pos_u.sat_ratio_min 0.9(DEFAULTS·pydantic·yaml 2, 해시·스냅샷·settings API 밖). 실측 H6 B3 0.102·B4 0.100 → limited ±1.5.
- [x] 4: U_SHORT_SEG(short ∧ 길이 < 2·램프) — H6 B3·B4 만(36 mm < 44·45). 문구 doe_messages, 백엔드 DS_TEXT_CODES, 프런트 posUTags 회색 꼬리표.
  시험 tests/doe/test_pos_u_sat.py(+slow H6), frontend pos_u.test.tsx, backend b1_api 거울. 골든 test_pos_u_golden 7 통과.
- [ ] 5 문서 · [ ] 전체 시험
