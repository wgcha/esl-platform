# 형상 보기 통일 — 공통 PartView (v0.17.3)

사용자 요청: "UI 통일. ① 같은 모델의 3D와 평면도는 개선됐는데 다른 곳(다른 시나리오·화면)에는 예전 평면도만 보인다. 이걸 공통 컴포넌트로 만들고 다른 곳에서 가져다 쓰게 횡전개하라."

프런트 우선 판. 백엔드는 ② B 메시 select `plan-view` 한 곳만(추가만). DB migration·설정 변경 없음.

## 1. 현황 조사(v0.17.1 기준)

| 자리 | 쓰던 컴포넌트 | 가진 자료 | v0.17.3 |
|---|---|---|---|
| ①② select ② 비드 선택 3D(편집) | Select3D + ViewToolbar(새) | 메시(part.glb·select.bin)·요소 색·그래프·섬 | 칸·툴바 = PartStage(편집 입력은 그대로) |
| ①② select ⑤ 평면도·단면 | SelectPlan(새 평면도) + 노드 체크 | plan-view select(외곽·메시 점·노드·비드 고리·단·W 법선·고정 노드), 3D 메시 | **PartView**(selectViewData): 평면도 + [3D] |
| ② select B 메시 ⑤ | SelectPlan — 링크·A 체결·하중 없음(AD-D-18) | 위 + 경계 경고 수 | **PartView** + A 체결·하중·경고선·경고 표(백엔드 VU-D-7) |
| 이전 방식 ①②③(same·mesh·step) ③ 평면도 | BoundaryPlan + BoundaryLegend(예전 평면도) | plan-view(외곽·구멍·메시 점·비드 고리·B 고정·A 체결·하중·링크), 실행 뒤 view3d d000 | **PartView**(legacyViewData): 평면도 + (실행 뒤) [3D] |
| 미리보기 격자(썸네일) | DoeThumbGrid(서버 PNG) | 썸네일 그림 | 그대로(그림) — 클릭 3D 는 아래 |
| select 미리보기 안 3D | SelectDesign3D + ViewToolbar | 메시·기저(안 변위·높이 색)·고정 침범 노드 | **PartView**(designViewData, 3D 만) |
| 결과 3D 비교(①②③④ 공통 Compare3D) | View3DCard + ViewToolbar | view3d manifest(변위 색·화살표) | 칸·툴바 = PartStage(카드 동작 그대로) |
| ④ 형상 비교 준비·결과 | 평면도 없음(plan-view 409) | 형상 표, 결과 view3d | 그대로 — 평면도 자료 없음(VU-F-3) |
| Case ④ 3D 하중 보기(Stage4) | View3DCard | view3d | 칸·툴바 = PartStage |
| Case ⑤ 겹쳐보기·변위 지도(Stage5) | FieldOverlay·DispOverlay(캔버스 컨투어) | 요소 값 지도 | 범위 밖 — 형상 그림이 아닌 값 지도(VU-F-4) |
| 최적화 금지 영역(OptNew) | KeepoutPlan(예전 SVG, 편집기) | opt plan-view | 좌표·여백 = planGeom 공유(편집 동작 그대로) |
| (안 씀) PlaneScatter | — | — | 삭제 |

## 2. 결정

- **VU-D-1** 형상 3D·평면도는 `frontend/src/view3d/part/` 한 곳: `PartView`(한 칸, [3D | 평면도]), `PartPlan`(평면도), `PartStage`·`usePartScene`(3D 칸·장면), `BoundaryWarnList`(경계 경고 표), `planGeom`(좌표), `adapters`(화면별 자료 변환), `types`.
- **VU-D-2** 시점 툴바는 같은 자리·모양(오른쪽 위 `v3d-view-bar`). 3D = 기존 ViewToolbar(±X·±Y·±Z·등각·꽉 차게·선택 맞춤, 단축키 1·3·7·0·F). 평면도 = 꽉 차게·선택 맞춤(고른 비드, 없으면 모든 비드) + 휠 확대(커서 기준)·끌기 이동·더블클릭/F = 꽉 차게. 평면도 버튼 이름은 "평면도 꽉 차게"·"평면도 선택 맞춤"(3D 툴바와 이름 겹침 없음).
- **VU-D-3** 평면도 좌표(a = ξ, b = η, 여백 3.5 %, 축 글자)는 `planGeom` 하나 — PartPlan·KeepoutPlan 이 같이 씀. 그림 크기·비율은 v0.17.1 과 같다.
- **VU-D-4** 층(`LayerKey`): mesh·boundary·beads·fixed·loads·apoints(경고 연결선 포함, 하중 선은 loads)·nodes(기본 꺼짐) = 평면도, graph·islands = 3D 요소 색, 안 변위·빨간 점 = 3D 자료(화면 고유 조작 — 안 3D 의 공칭/안·배율 — 이 정함). 층 칩이 범례를 겸한다(따로 범례 없음).
- **VU-D-5** 자료가 없는 층·보기는 숨긴다. 어댑터는 자료를 지어내지 않는다(예: 이전 방식 준비 단계에는 3D 파일이 없어 [3D] 없음).
- **VU-D-6** 시나리오별 사본 없음: BoundaryPlan·SelectPlan·BoundaryLegend 삭제, 시험은 PartView 로. 3D 를 처음 고를 때만 장면을 만든다(평면도만 볼 때 WebGL 0).
- **VU-D-7** 백엔드(추가만): select `GET …/plan-view` 는 코어 plan_data 가 비운 `a_points`·`load_points`·`links` 를 `prep/plan.json`(② B 메시 경계 매핑) 값으로 채운다. 링크 끝 좌표는 plan.json B 고정 클러스터 라벨로 찾고, 응답 `fixed` 는 select 고정 노드 그대로. ① select 는 plan.json 에 경계 매핑이 없어 변화 없음.
- **VU-D-8** 화면 규칙: 주 버튼 1개는 페이지 머리(변화 없음), PartView 안에는 주 버튼 없음. 2560×1440 기준, 1920 에서 잘림·가로 스크롤 없음. 라벨 한국어.
- **VU-D-9** ① 의 보기 동작은 공유 부분만 바뀐다: ⑤ 평면도 '노드 점 숨김' 체크 → '노드 점' 층 칩, 범례 → 층 칩, 평면도에 η 축 글자·확대 툴바, [3D] 보기 추가. 비드 선택 3D 편집·안 3D 조작은 그대로.

## 3. 자료 형식(types.ts)

`PartViewData = { plan: PartPlanData | null, scene: Part3DData | null, layers: LayerKey[], warnings: PartWarnings | null, active?: PlanVar | null, initialMode? }`

- `PartPlanData`: style(select | legacy)·frame·outline·holes + 층 자료(points·nodes·beads{rings, e, tiers, label, chip}·fixed·loads·apoints·links).
- `Part3DData`: mesh{positions, indices, tri2elem?, nElems?} + elemColors(on)·design{u, c, vmax, scale}·markers·selectionBbox·colorMap.
- `PartWarnings`: links·nWarn(prep.boundary.n_warn)·st(기준 mm).

## 4. 어댑터별 층

| 어댑터(자리) | 평면도 층 | 3D | 경고 표 |
|---|---|---|---|
| legacyViewData — same | boundary·mesh·beads·fixed | 실행 뒤 d000 형상 | 없음 |
| legacyViewData — mesh·step | + apoints·loads(경고선) | 실행 뒤 d000 형상 | 있음 |
| selectViewData — ① select | boundary·mesh·beads(단·칩·W 범위)·fixed·nodes | 선택 형상 + graph(schema 2)·islands | 없음 |
| selectViewData — ② B 메시 select | 위 + apoints·loads(경고선) | 위와 같음 | 있음 |
| designViewData — 안 3D | (없음) | 안 변위·높이 색·빨간 점 | 없음 |

## 5. 백엔드 후속(지어내지 않음)

- **VU-F-1** 이전 방식(same·mesh·step) 준비 단계 3D: `prep/select/part.glb` 같은 형상 파일이 없다(실행 뒤 d000 만). 워커 BD_LOADS 가 기준 메시 glb 를 쓰면 legacyViewData 에 mesh 만 넘기면 됨.
- **VU-F-2** 평면도의 섬·그래프 세그먼트 고리: select plan-view 에 섬·세그먼트 고리(ring_ab)가 없다 — 지금은 3D 요소 색으로만.
- **VU-F-3** ④ 형상 비교 평면도: plan-view 가 compare 를 409 로 막음(형상별 frame 없음).
- **VU-F-4** 안별 평면 변위(미리보기 썸네일의 평면 버전)·Case ⑤ 값 지도: 서버 PNG·캔버스 컨투어라 PartView 층 자료가 없다.
- **VU-F-5** select plan-view `fixed` 는 {a, b} 만(라벨 없음) — B 고정 클러스터 라벨 툴팁은 이전 방식만.

## 6. 시험

- **V-VU-1** legacy same: 평면도만, 층 = 외곽·메시·비드·고정, 보기 전환·경고 표 없음.
- **V-VU-2** legacy ②③: A 체결·하중 층, 경고선 수 = 경고 수, 층 끄면 선·기호 숨김.
- **V-VU-3** ① select: 단 색·라벨 칩, 노드 층 기본 꺼짐 → 켜면 점, W 행 = 범위 점선.
- **V-VU-4** ② select B 메시: 백엔드 링크 → A 체결·하중 층·경고 표, 같은 자료라도 ① 이면 숨김.
- **V-VU-5** 평면도 툴바: 선택 맞춤 → viewBox 확대, 꽉 차게·F → 원래대로.
- **V-VU-6** [3D] 고를 때만 장면, 3D 툴바(X 보기 → setView), 3D 전용 층 칩(세그먼트 색 끄면 다시 칠함).
- **V-VU-7** 안 3D: 3D 만(전환·층 칩 없음), 빨간 점, 툴바.
- **V-VU-8** 화면: 이전 방식 완료(doe-1) ③ = PartView + [3D](d000).
- **V-VU-9** 화면: ② B 메시 select(mock doe-14, `?demoMeshSel=1`) ⑤ = A 체결·하중·경고 표, ① select(doe-5) 는 없음 + [3D] 요소 색.
- **V-VU-10**(백엔드) `test_plan_view_keeps_boundary_links_v0173`: select plan-view 가 plan.json a_points·load_points·links 를 넘기고 링크 좌표·종류를 붙임, fixed 는 select 것.
- 기존 시험 유지: doe(경계 경고선 = 경고 수), doe_select(칩·노드·W 점선·단면), select_save_vars(안 3D 빨간 점), stage4_3d(3D 하중 보기 칸·툴바), keepout(드래그 좌표).
- 화면 증적: `frontend/scripts/screenshots-v0173.mjs` → /home/claude/screens/v0173 (①·②·③ 이전 방식·④·미리보기·결과, 2560·1920).
