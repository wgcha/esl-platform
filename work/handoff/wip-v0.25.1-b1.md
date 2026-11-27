# wip v0.25.1 B1 (백엔드) — 인수 메모
- 브랜치 wip/v0.25.1-b1 (기준 release/v0.25.1 2be518f1). 완료: 스키마·설정·문구·서비스·라우터·OpenAPI·시험 V-0251-16~19(`backend/tests/test_doe_v0251_b1_api.py`).
- 남은 것: 없음(관련 파일 시험 통과 후 반환). backend 전체는 /tmp 여유 < 21.5 GB 라 돌리지 않음.
- 결정: 씬 POST 작업 params.kind = "VIEW3D"(워커 POST_ONLY_KINDS 그대로), doe.post_mode = "scene", resume = BD_POST.
- 코어(C1)에 필요한 것: 사이드카 `esl/doe_scene_view/1` 필수 키(schema·entries[{entry_id,kk}]·packs[src]{tag,c_kind,designs{did:{dir,scenes[]}},skipped[]}·budget{max_mb,est_mb}),
  pack.json 필수 키(geometry{name}·lod|null{name}·scenes[{entry_id,kk,manifest,values}] — manifest·values = 파일 이름 문자열), 씬 manifest 에 values{name…} 포함, 코어 DEFAULTS["view3d"]["scene"] 추가.
