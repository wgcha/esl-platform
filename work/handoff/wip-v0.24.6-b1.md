# wip v0.24.6 B1 (백엔드) 핸드오프

브랜치 wip/v0.24.6-b1. 계약 esl_viewer_hv.md §8.2·§8.3·§9.2·V-0246-VW-20.

## 변경
- schemas.py: `DoeJigMethodOut`(새), `DoeJigOut` += tie_dofs·methods, `DoeResultOut` += view3d_jd·_jd_esl·_jd_ref·view3d_js·_js_esl·_js_ref(없으면 null).
- api/services/doe.py: `RANK_V3D`(코어 열 v3d 거울, 키 = RANK_VIEWS 순서), 사이드카 병합을 RANK_V3D 열로 일반화(result.json 우선 유지),
  `SOURCE_ADD` += jig_disp·jig_spring(need `jig_src_ok` = result jig.methods[src].status=="ok", legacy None, 열 `src`), `NEED["jig_src_ok"]`.
- OpenAPI 덤프 갱신. 시험: tests/test_doe_v0246_b1_api.py(새 11), test_doe_rank_metric_api.py 2곳(새 키 허용).

## 통합 메모 (C1·F2)
- C1: 사이드카 post/jig_view.json 에 view3d_jd*·view3d_js* 키를 계약 §8.1 형식({did: 폴더}·{did: entry}·{entry: 폴더})으로. RANK_SOURCES 에 `v3d` 열이 생기면
  test_rank_v3d_mirrors_core_column 이 RANK_V3D 와 자동 대조(지금은 키 목록만).
- F2 types.ts: DoeJigMethodOut 13필드·DoeJigOut.tie_dofs·methods, DoeResultOut 6키. source_add 에 jig_disp·jig_spring 행이 추가됨(조건 만족 시).
- "지그 고정 꺼짐" 공백: 상위 jig.status(fallback)와 무관하게 jd·js 행은 methods[src].status 만 본다. `jig` 행 자체는 v0.24.5 그대로(고정 안 하면 409).
