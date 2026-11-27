# wip v0.25.1 F1a — 공용 3D 뷰어 색 지도·범례 편집 (F1b·F1c 가 쓸 공용 API)

브랜치 `wip/v0.25.1-f1a`. 계약 `docs/contracts/esl_view3d_scene_legend.md` 개정 1 §5.2~§5.6·§5.8. 소유 = `frontend/src/lib/colormap.ts`·`view3d/**`·`components/ColorLegend.tsx`·`styles.css` 의 view3d 범례 부분.

## 1. 색 지도 함수 — `frontend/src/lib/colormap.ts` (F1c 가 씀)
정점은 `resources/colormaps.json` 에서만(빌드 import). 역할(role)로 고른다: `"seq"`(레인보우 — 낮음 파랑 → 높음 빨강) · `"div"`(0 중심 발산 — − 파랑 · + 빨강) · `"region"`(분류, Blues).

| 내보냄 | 쓰임 |
|---|---|
| `mapFor(role) → ColorMap` | 지도. `mapFor("seq")` |
| `srgb(map, t) → [r,g,b]` · `css(map, t) → "rgb(r,g,b)"` | t 0~1(범위 밖 자름, NaN = 0). 2D 칸 색 = `css(mapFor("seq"), (v-min)/(max-min))` |
| `cssGradient(map, {reversed?, levels?, angle?})` | 범례 띠. 기본 90deg(왼쪽 낮음 → 오른쪽 높음). L4·L5·L7 = `cssGradient(mapFor("seq"))`, L6 오차·L9 높이 변화 = `cssGradient(mapFor("div"))`(왼쪽 −V 파랑 → 오른쪽 +V 빨강) |
| `special("nan"|"out"|"none")` · `specialCss(name)` · `specialLinear(name)` | 특수색 — NaN 회색 = `specialCss("nan")`(옛 `NA_COLOR` 대체), 썸네일 영향 없음 = `none` |
| `table(map, n=256)` · `buildLut(map, {reversed, linear})` | 256색 uint8 표(자원 `check` 와 맞대는 값) · 셰이더 색표 |
| `f3`, `srgbToLinear`, `validateColormaps` | 그대로 |

2D 부호 있는 값(오차 %): `css(mapFor("div"), (value / R + 1) / 2)` — −R 파랑 · 0 흰 · +R 빨강. 높이 변화(L9): + = 깊어짐 = 빨강 → 문구 "빨강 = 깊어짐 · 파랑 = 얕아짐"(옛 썸네일은 `color.map` 없음 → 옛 띠·옛 문구).

**@deprecated(F1c 병합 때 삭제)**: `VIRIDIS`·`DIVERGING`·`NA_COLOR`·`lerp`·`gradient`·`DIVERGING_GRADIENT`(lib/colormap.ts 맨 아래 블록) + `view3d/colors.ts` 의 `DIVERGING_GRADIENT` 재내보냄 1줄. F1c 파일(DispOverlay·FieldOverlay·library/common·BeadSelectCard)이 아직 import — 바꾼 뒤 두 곳을 지우면 통합 시험 V-0251-37 이 0건. (`lib/colormap.ts` 의 deprecated 블록과 `colors.ts` 재내보냄 1줄만 정점 리터럴/옛 이름이 남은 곳.)

## 2. 3D 카드 — `View3DCard` / `View3DOptions` (F1b 가 씀)
새 선택 키(접점):
- `colorMode?: "disp" | "load" | "c" | "dc"` — `c` = C 기여도(씬 값 `c`, 레인보우, 자동 범위 [min(p01,0), max(p99,0)]), `dc` = 차이(씬 값 `dc`, 발산 ±abs_p99, **범례 범위·동기 안 함**). 주면 `colorBy` 보다 앞선다.
  - 값 파일에 `c`/`dc` 배열이 없으면 색을 안 칠하고 `data-testid="v3d-no-c"` 안내 문구(`NO_C_TEXT`·`NO_DC_TEXT`). 버튼 비활성은 호출부 몫(`sceneExtras(manifest).c`/`.dc` 가 null 이면 비활성 — 사유 문구 상수 `NO_C_TEXT`).
- `colorLabel?: string` — 범례 제목 직접 지정. 기본 `C_LABEL`("C 기여도 F·u (N·mm) — 합 = C")·`DC_LABEL`("C 기여도 차이 안 − 기준 (N·mm) — 합 = ΔC") — View3DCard 가 export.
- `pins?: { umax?: ScenePin | null } | null` — umax 위치 핀. **안 주면 씬 manifest 의 `pins.umax`(`{node_id, vertex, value, kind}`) 를 읽는다**(F1b 는 manifest 만 올바로 넘기면 됨). `null`·`{umax:null}` = 핀 없음. 라벨 `umax <값> mm @N <노드 ID>`, 기호 ◆(파랑), 최대 표식과 같은 정점이면 최대 표식 라벨 숨김. 켬·끔 = 범례 편집의 `umax 위치`(`legend.upin`, 기본 켬).
- `fieldOverride.role?: "region" | "seq"` — 기본 `region`(분류 = Blues, 범례 편집 없음, 연속·끝색 고정). 옛 호출(하중 영역 L3)은 그대로 동작.
- `range` / `rangeManual` / `onRangeChange` — 호출부가 범위를 정하는 옛 방식 그대로(주면 호출부가 정함; 최소 직접 입력은 `onRangeChange({min,max})`). **안 주면 저장소가 범위를 정한다 — 쌍은 두 카드 자동 범위의 합집합 + 직접 입력 공유**(`useViewerSync` 확장). F1b 는 DoeStudy 의 `range` 계산을 이 방식으로 바꿔도 되고 그대로 둬도 된다.

씬 manifest 새 키 읽기: `view3d/sceneManifest.ts` — `sceneExtras(manifest) → {c, dc, umaxPin, cRange, dcRange}`(없으면 null — 옛 자료 안전), `cAutoRange`·`dcAutoRange`. 값 복원 `decodeValues` 는 `c`·`dc` 배열(int16)을 `vals.c`·`vals.dc` 로 줌. `api/types.ts` 는 안 건드림(F1b 가 `View3dSceneOut` 로) — 이쪽은 구조만 본다.

## 3. 범례 상태 공유 — `useViewerSync(planKey)` (F1b)
- `sync.state.legend`(레벨·연속·눈금·숫자·범위 밖·뒤집기·표식·핀) · `sync.state.manMin/manMax`(직접 입력 범위) · `sync.setLegend(patch)` · `sync.reportRange`·`sync.pairAuto`(카드가 자동 범위를 알림 — 카드가 알아서 호출, 호출부는 `viewerSync: sync` 만 넘기면 됨).
- 계획 표 `VIEWER_PLANS` 열 `legendSync`(study_* = pair, case_* = none)·`layers` 에 `upin`. 모든 3D 보기 범례 모양 1벌(`esl.v3d.viewer.v2`.legend). 범위·로그는 기억 안 함.
- 색 모드 표 `COLOR_MODES`(`view3d/legend/legendModel.ts`): disp·load·c·dc·field·region × role·signed·logOk·sym·pairRange·editable.

## 4. 범례 편집 UI
`LegendOverlay`(항상 표시, 클릭 = 팝오버) · `legend/LegendEditor.tsx`(팝오버·⚙ 팝오버 `범례` 절 같은 컴포넌트) · `legend/legendPrefs.ts`(v1→v2). data-testid: `v3d-legend-ov`(범례) · `v3d-legend-pop`(팝오버) · 편집 칸 `v3d-leg-{levels,cont,max,min,scale,format,digits,out,rev,maxmark,minmark,pin,reset}`(⚙ 안 = `v3d-gleg-*`).

## 5. 비드 높이 변화 (L8)
`view3d/part/*` 의 `colorMap` 값 = 역할 이름(`"div"`). 비드 설계 3D 는 `scene.setColorMap("div")` — +V(깊어짐) 빨강. `SceneApi.setColorMap(role, reversed?)`. **F1c**: `BeadSelectCard.HeightLegend`·`DoeThumbGrid`·`mock/selectmock.ts` 는 새 의미(빨강 = 깊어짐)로 — 3D 쪽은 이미 바뀜.

## 6. 이후 단계 메모
- umax 핀·C 기여도·차이는 F1b 의 씬 선택(토글)과 같이 쓰면 끝. `View3DOptions` 외에 F1a 가 요구하는 것 없음.
