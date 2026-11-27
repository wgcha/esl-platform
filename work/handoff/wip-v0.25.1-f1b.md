# wip v0.25.1 F1b — 강성 스터디 결과 화면 (씬 선택·C 기여도·차이·umax 핀·씬 요약·개선율 칸 색·[씬 3D 만들기])

브랜치 `wip/v0.25.1-f1b`. 계약 `docs/contracts/esl_view3d_scene_legend.md` 개정 1 §4·§5.7(L10)·§15.1.

## 바뀐 파일
- `api/types.ts` — `View3dSceneOut`·`View3dSceneRanges`·`DoeSceneViewOut`·`DoeSceneAddOut` 등, `DoeResultOut.scene_view/scene_add` (check:api 통과). `api/doe.ts` — `sceneManifestPath`·`addScenes`.
- `pages/doe/doeScene.ts`(새) — 순수 함수·문구표 `SCENE_TEXT`·`COLOR_SEL_BUTTONS`: `hasScenePair`·`skippedFor`·`sceneChoices`·`sceneSummary`·`colorDisabled`·`toggleScene`.
- `pages/doe/DoeStudy.tsx` — 씬 상태 `scene`(페이지 1곳, 스터디 id 바뀌면 null), `useDoeView(…, scene?)`, `Compare3D`(선택 칸·색 4버튼·씬 요약·안내·[씬 3D 만들기] `SceneAddButton`), JigDiag·ReconDiag 엔트리 기본값 = scene.
- `components/DoePerEslTable.tsx` — 열 머리 버튼·셀 클릭·선택 열 강조, 칸 색 = `css(mapFor("div"), …)` 변화율(`PER_ESL_HEAT_SPAN` 0.5 한 곳), 설명 문구. `components/DoeRanking.tsx` — 최악 ESL 칸 버튼.
- 시험 `__tests__/doe_v0251_scene.test.tsx`(V-0251-25·26·27·45), `doe.test.tsx` heatStyle 단언 갱신. 목 `mock/scenemock.ts`(새)·`doedata.ts demoScene()`(doe-60 씬 있음·doe-61 옛 결과)·`server.ts`(씬 파일)·`install.ts`(?demoScene=1).
- `scripts/screenshots-v0251-f1b.mjs` — 높이 측정(base doe-40 vs 새 doe-40/doe-60·C·차이 모드).

## 동작 요약
- 자료 고르기: `scene_view.packs[탭 출처 키].designs[did]` 에 (안·d000 둘 다) 엔트리 있으면 씬 manifest API, 자동인데 없으면 기존 폴더, 직접 고른 씬인데 없으면 안내(+ 한도·실패는 버튼).
- 선택 3곳 = 3D 바 select(`v3d-scene-select`)·ESL 표(`per-esl-col-<eid>`·`per-esl-cell-<did>-<eid>`)·순위표(`rank-worst-<did>`). 옛 결과(scene_view null) = 3곳 모두 클릭·선택 칸 없음.
- 색: 차이 = 안 카드 `colorMode dc`, 기준 카드 `c` + 제목 꼬리 " — 기준 C 기여도(참고)". c/dc 범위는 저장소(`range` 안 넘김).
