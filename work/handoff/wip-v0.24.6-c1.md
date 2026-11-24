# 핸드오프 — wip/v0.24.6-c1 (C1 코어: 스터디 지그 변위·스프링 3D, R-JIGC-2)

계약 `docs/contracts/esl_viewer_hv.md` §8.1·§8.2·§10·§11·§12(V-0246-VW-17~19)·§14 C1, 결정 D-0.24.6-VW-13·16.
base = release/v0.24.6 04618506(= main 8c4f3477 코드 + 계약). 백엔드·화면은 B1·F1·F2 담당(이 브랜치는 코어만).

## 상태
- [x] `jig_bc.support_marks` + `MARK_TIE`·`MARK_AUX`("123"·"ij" — 백엔드 JIG_TIE_DOF·JIG_AUX_DOF 와 같은 값)
- [x] `RANK_SOURCES` 열 `v3d`·`v3d_tag`·`v3d_store`(모든 행)
- [x] `_jig_view3d_src`·공용 `_jig_v3d_build`(고정 `_jig_view3d` 도 이 본문 사용 — 바이트 동일 골든 확인)
- [x] `_jig_v3d_sidecar`·`_jig_src_carry`, `_jig_extras(v3_src=, echo=)`, `_post_view3d` 옮겨 적기
- [x] 시험 `tests/doe/test_jig_view3d_src.py`(V-17~19) + 골든 `tests/fixtures/jig_case/golden_v0246_c1.json`(main 8c4f3477 코드로 기록)
- [ ] tests/doe 전체 · pytest tests/ 범위 실행 — 아래 "시험" 갱신

## 사이드카 `post/jig_view.json` 새 키(B1 병합용 — 계약 §8 그대로)
- `view3d_jd{did: "<did>_jd"}`·`view3d_jd_esl{did: entry}`·`view3d_jd_ref{entry: "d000_jd_e<kk>"}`, 같은 형식 `view3d_js*`(키 = RANK_SOURCES 열 v3d).
- `view3d_src_seconds{tag: s}` — 이번 실행에서 새로 만든 행만(옮겨 적은 행은 옛 값). 만든 것이 없으면 키 없음.
- 위치: `schema`·`source`·(다시 만들기 고정 3D `view3d_jig*`) 다음, `jig_diag`·`rank_views` 앞. 경고 `VIEW3D_FAILED: <did>_<tag> <code>`·
  기준 실패 `VIEW3D_FAILED: d000_<tag> <code>`·행 예외 `VIEW3D_FAILED: <tag> <code>` 는 사이드카 `warnings` 에만(result.json 불변).
- 지지 표식(manifest supports): tie ∪ 스프링 노드 최원점 샘플 ≤ view3d.jig_support_max '123' + 3-2-1 면내 'ij'(샘플된 tie 와 겹치면 tie).

## 계약과 다르게 / 최종 v0.24.5 와 맞춘 점
- 계약 §8.1 은 "_jig_extras(…, v3_src=…)" — 여기서 v3_src = **다시 만들기가 옛 사이드카에서 옮겨 적을 키**(`_jig_src_carry`), 3D 생성은
  `_jig_extras` 안 `_jig_v3d_sidecar` 가 함(사이드카를 쓰지 않는 조건 — view3d.jig_diag 끔·지그 미계산 — 이면 폴더도 만들지 않음).
- 조건에 view3d.jig_diag 도 들어감(사이드카 자체 조건, v0.24.5 그대로) — 끄면 rank_views 도 없어 jd·js 탭이 없음.
- 고정 3D(`_jig_view3d`)는 v3d_store = result 행을 열로 찾고 공용 본문 `_jig_v3d_build` 사용 — 표식만 옛 규칙(지그 노드 샘플 '123')
  (support_marks 로 통일 = R-VW-3, 바이트 변화).
- 기존 시험 1곳 수정: `tests/doe/test_jig_methods.py::test_factor_sharing_and_spring_k_reuse` 분해 횟수에 jd·js 3D(사이드카) 몫 추가(의도 변경).
- jig_plan·need_rank·LEGACY_JIG_MERGE·hidden_sources(v0.24.5) 는 건드리지 않음.

## 시험
(갱신 예정)

## 비용
(갱신 예정)
