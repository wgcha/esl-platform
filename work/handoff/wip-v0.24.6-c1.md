# 핸드오프 — wip/v0.24.6-c1 (C1 코어: 스터디 지그 변위·스프링 3D, R-JIGC-2)

계약 `docs/contracts/esl_viewer_hv.md` §8.1·§8.2·§10·§11·§12(V-0246-VW-17~19)·§14 C1, 결정 D-0.24.6-VW-13·16.
base = release/v0.24.6 04618506(= main 8c4f3477 코드 + 계약). 백엔드·화면은 B1·F1·F2 담당(이 브랜치는 코어만).

## 상태
- [x] `jig_bc.support_marks` + `MARK_TIE`·`MARK_AUX`("123"·"ij" — 백엔드 JIG_TIE_DOF·JIG_AUX_DOF 와 같은 값)
- [x] `RANK_SOURCES` 열 `v3d`·`v3d_tag`·`v3d_store`(모든 행)
- [x] `_jig_view3d_src`·공용 `_jig_v3d_build`(고정 `_jig_view3d` 도 이 본문 사용 — 바이트 동일 골든 확인)
- [x] `_jig_v3d_sidecar`·`_jig_src_carry`, `_jig_extras(v3_src=, echo=)`, `_post_view3d` 옮겨 적기
- [x] 시험 `tests/doe/test_jig_view3d_src.py`(V-17~19) + 골든 `tests/fixtures/jig_case/golden_v0246_c1.json`(main 8c4f3477 코드로 기록)
- [x] tests/doe 전체 · pytest tests/ 실행(아래)

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

## 시험(2026-11-24, 환경 Linux-x86_64-numpy2.5.3-scipy1.18.1 — 골든 기록과 같은 환경 서명)
- `tests/doe/test_jig_view3d_src.py` 13 passed(V-17 골든·사이드카·표식·실패 격리 2, V-18 옮겨 적기·준비 안 됨·view3d.jig 끔, 계획 열·이름 분기,
  V-19 support_marks = 백엔드 _jig_supports(노드·순서·dof), 비용 분해 횟수).
- `pytest tests/` : 3 failed(허용 test_large_model_cad_share·test_v0160_bytes_skip_policy[h8]·[h5open]), 1614 passed, 192 skipped(19:41).
  tests/doe 597 수집 — 실패는 허용 1건뿐. 골든 golden_v0243(옛 스냅샷)·golden_v0246_c1(main 8c4f3477 — v0243·v0244·v0245 시나리오) 통과.
- 골든 "바이트 동일" = test_jig_move 규칙(JSON 정규화 — 시각·seconds* 제외, npz 배열 해시, 그 밖 파일 sha). 사이드카는 새 키 7개를 뺀 정규 JSON.
- 골든 다시 기록 방법: main 8c4f3477 worktree 에 시험 파일을 복사해 `ESL_GOLDEN_RECORD_V0246C1=1 pytest -k golden`(다시 기록 금지가 원칙).

## 비용(R-VW-4 현장 실측 전 합성 측정 — 같은 함수 직접 호출, 3회 중 최소 시간·최대 피크, 다른 에이전트 시험과 CPU 공유 → 시간은 ±30% 잡음)
| 판(노드) | 3D | 분해 | 시간 s | tracemalloc 피크 MB | RSS 피크 증가 MB |
|---|---|---|---|---|---|
| 60×40(2,501) | 고정 jig | 3 | 2.10 | 105.8 | 41.6 |
| | jd | 3 | 1.73 | 105.8 | 38.6 |
| | js | 3 | 1.97 | 105.9 | 38.7 |
| 120×80(9,801) | 고정 jig | 3 | 7.18 | 501.1 | 504.7 |
| | jd | 3 | 9.67 | 501.1 | 504.6 |
| | js | 3 | 7.08 | 501.3 | 505.5 |
- 분해 = 표시 안 2 + 기준 1(고정과 같음, 시험 test_src_3d_cost_same_factorizations_as_fixed 가 단언). 피크는 분해 1개(차례로 놓음) —
  방식을 더해도 피크 불변, BD_POST 시간만 방식 수만큼 더해짐(두 방식 켜면 고정 3D 시간 ≈ ×2 추가). 피크의 대부분은 jig_bc.factorize
  (기존 경로 — 고정 3D 와 같음, 이번 변경 아님).
- 사이드카 view3d_src_seconds(BD_POST 실측, 9,801 노드): jd 13.2 s · js 15.7 s(동시 시험 부하 중).
- 측정 방법 = 시험 test_src_3d_cost_same_factorizations_as_fixed 와 같은 직접 호출을 큰 판(test_jig_stages NX·NY 바꿈, 세 방식 스터디)에 적용 + /proc/self/clear_refs 로 RSS 피크 초기화.
