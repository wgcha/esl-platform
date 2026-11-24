# 계약: 3D 컨투어 뷰어 강화(HyperView 참조) + 강성 스터디 결과 3행 배치 + 스터디 지그 변위·스프링 3D + 지그 방식 탭 사유 (VW, v0.24.6)

- 상태: **초안 → 구현 기준**(2026-11-24). 브랜치 `release/v0.24.6`(release/v0.24.5 24614db3 에서 분기 — v0.24.5 머지 뒤 rebase 해서 구현). 구현 코드 없음 — 이 문서가 원본.
- 관계: `esl_3d_load.md`(③ 3D 카드·색·화살표·성능 §11), `esl_view_unify.md`(공용 PartStage·시점 툴바), `esl_view3d_sources.md`(출처 탭·보기 세그먼트·재현), `esl_jig_view.md`(지그 진단·사이드카 `post/jig_view.json`·3D 다시 만들기), `esl_jig_case.md`(지그 3방식 — R-JIGC-2 를 §8 로 **이번에 포함**), `esl_validate_tiers.md` §11(화면 출처 숨김). 충돌하면 이 문서 범위에서 이 문서가 우선.
- DB migration **없음**, 새 설정 키 **없음**(값은 기존 `view3d.jig`·`view3d.jig_support_max`·계획 표 열). 3D 뷰어(§1~§6)는 **백엔드 변경 없음**. §8(스터디 지그 3D)은 코어·백엔드 추가, §9(탭 사유)는 응답 필드 노출만.
- ID: 결정 `D-0.24.6-VW-n`, 시험 `V-0246-VW-n`, 후속 `R-VW-n`, 미결 `Q-VW-n`.

### 사용자 요청 (원문, 변경 금지)
1. (2026-11-24) "3d 컨투어에서 경계조건이랑 하중을 각 보엿다 안보엿다 하게 해줘. 컨투어 기능들을 하이퍼뷰어 참조해서 뷰어기능 강화"
2. (2026-11-24 12:57·12:58) "강성스터디 형상비교가 하나의 행을 차지하도록 키우자. 넘 작다. 표랑 개선율을 좌우로 놓게 하고. 민감도는 맨밑 행에 차지하게 해서 가독성 개선 하자"
3. (2026-11-24) "지그 esl이 고정만 강성스터디햇자나. 스프링이랑 변위는 왜안돼?"
4. (2026-11-24 13:00 현장 보고 — 메인 요약) v0.24.4 에서 만든 스터디의 지그 변위·스프링 탭이 "이 스터디에서 계산하지 않은 방식입니다"로 비활성 — 실제로는 계산했지만 실패한 경우도 같은 문구.

사용자 원칙(공통): 사용성 우선 · 필수 버튼만("필수인가?"를 먼저, 아니면 제안만) · 가독성 높은 배치 · 2560×1440 기준 세로 스크롤 증가 없음(요청 2 는 사용자가 3D 확대를 원해 예외 — 각 행이 한 화면) · 정보 삭제 금지 · 하드코딩 금지 · 같은 기능은 공용 컴포넌트 하나.

---

## 0. 감사 (24614db3, 읽기만)

### 0.1 3D 보기 목록 — 누가 무엇을 쓰나

| 화면 | 컴포넌트(파일:행) | 카드 | 색 | 화살표 | 지지 표식 | 범위 공유 | 변형 공유 |
|---|---|---|---|---|---|---|---|
| Case ③ 3D | `stages/Stage4.tsx:158` → `view3d/CaseView3D.tsx:20` → `View3DCard` | 1 | 하중(면압·법선·크기 `CaseView3D.tsx:96-104`) / 목표·응답·오차 변위 | manifest top·군집(단계 슬라이더) | manifest supports(3-2-1 dof·지그 tie '123'·면내 'ij'·스프링 노드) | 출처마다 따로(수동 범위 출처 바꾸면 초기화 `CaseView3D.tsx:32-37`, 하중 범위 키 `${runId}:${src}` `useLoadView.ts:100`) | — |
| ④ 검증 비교 | `stages/Stage5.tsx:398·429` → `components/DispOverlay.tsx`·`FieldOverlay.tsx` | — | **2D canvas PCA 평면 컨투어**(3D 뷰어 아님) | — | 원 표식(2D) | 출처·레이어별 localStorage | — |
| 강성 스터디 설계 비교 | `pages/doe/DoeStudy.tsx:1066` `Compare3D` → `View3DCard` ×2 (`:1178-1179`) | 2 | 응답 변위 / 하중(`:1094-1117`) | manifest top·군집 | DOE 지지(3-2-1)·지그 tie '123' 샘플 | 두 카드 같은 범위(`:1089-1091`) | **없음**(카드마다 따로) |
| 지그 진단 | `DoeStudy.tsx:876` `JigDiag` ×2 (`:971-982`) | 2 | 목표·오차·영역 색(fieldOverride) | 영역 합력(arrowsOverride) | tie 상대 부품별 색(`:925-929`) | 있음 | deformSync(`:896`) |
| 재현 진단 | `DoeStudy.tsx` `ReconDiag` ×2 (`:1057-1058`) | 2 | 목표·재현·오차 | manifest top | supd | 있음 | deformSync(`:1003`) |
| (범위 밖) 비드 선택 3D·PartView | `components/BeadSelectCard.tsx:992·1330`, `view3d/part/PartView.tsx:103` | — | 요소 색(편집) | — | — | — | — |

결론: 3D 결과 보기 4종(③·스터디 설계 비교·지그 진단·재현 진단)은 모두 `View3DCard` + `PartStage`(칸·시점 툴바) 한 벌을 쓴다 → 강화는 이 한 벌에만 넣으면 모든 보기에 같이 들어간다. **④ 검증 비교는 3D 가 아니다**(2D PCA 평면) — Q-VW-2.

### 0.2 기능 × 현재 상태

| 기능(HyperView 대응) | 현재 | 위치 |
|---|---|---|
| 표준 시점 ±X·±Y·±Z·등각·꽉 차게·선택 맞춤, 단축키 1·3·7·0·F | **있음** | `ViewToolbar.tsx:9·93-104` |
| 원근/직교(브라우저 기억 `esl.v3d.projection.v1`) | **있음** | `View3DCard.tsx:302-305`, `projection.ts:14` |
| 변형 형상·배율(자동 10^0~10^4 슬라이더)·실제 크기 ×1 | **있음** | `View3DCard.tsx:283-301`, `deform.ts:9-14` |
| 화살표 개수(100·50·20·10 노드 → 군집 5~2) | **있음** | `View3DCard.tsx:256-281`, `arrows.ts:23-25` |
| 하중 색 성분(면압 \|Fn\|/A · 법선 \|Fn\| · 크기 \|F\|) | **있음**(③) | `CaseView3D.tsx:96-104` |
| 범례: 0~최대(최대 입력)·[자동]·범위 밖 개수 ▲▼·단위 문구 | **있음**(연속 Blues 9 만) | `ColorLegend.tsx:148-183`, `colors.ts:5-9` |
| 범위 공유(설계안 비교) | **있음**(스터디 2카드) / ③ 출처 전환 땐 **없음** | §0.1 |
| 클릭 탐침 | **일부** — 노드 ID·하중 값(면압·Fn·\|F\|)만, **변위 값·성분·좌표 없음** | `info.ts:10-38` |
| 표 ↔ 3D 선택·더블클릭 중심 이동 | **있음** | `selection.ts`, `View3DCard.tsx:240-249` |
| LOD(조작 중 저해상도) | **있음** | `scene.ts:244-262` |
| 지지 표식(▲◭△ + 축 선분) | **있음 — 항상 표시, 끌 수 없음** | `supports.ts`, `View3DCard.tsx:225-238` |
| 하중 화살표 | **있음 — 항상 표시, 끌 수 없음** | `View3DCard.tsx:220-232` |
| 원형(undeformed) 겹쳐 보기 | **없음** | — |
| 요소 경계선(메시 선)·특징선 | **없음**(편집 보기 `setOverlayLines` 만) | `sceneApi.ts:76` |
| 최대·최소 위치 표식·값·노드 ID | **3D 없음**(④ 2D 는 e 최대 표식 있음 `DispOverlay.tsx:163-168`) | — |
| 범례 구간(레벨 수)·눈금 값 | **없음** | — |
| 범위 밖 색(회색)·최솟값 입력 | **없음**(끝색 + ▲▼ 개수) | — |
| 비교 카드 시점 동기화 | **없음**(변형만 진단 보기에서 공유) | — |
| 단면·부품 표시/투명·측정·애니메이션·캡처·시점 저장 | **없음** | — |
| 범례 변경 비용 | **CPU 정점 루프 전체**(`fillVertexColors` → 색 버퍼 재업로드) | `colors.ts:52-70`, `scene.ts:212-216·629-637` |

### 0.3 3D 자료(백엔드 → 화면) — P1 에 충분한가

| 자료 | 내용 | P1 쓰임 |
|---|---|---|
| `part.glb`(·`part_lod.glb`) | int16 양자화 위치·`_NODE_ID`(또는 `_SRC`)·삼각형(사각형 → (a,b,c),(a,c,d) — `esl/view3d.py:257-266`) | 특징선(원형 외곽선)·노드 ID(최대 표식·탐침) |
| `values.bin` | pa·fn·fmag·u(u_rel 3n), int16/uint16 양자화(`values.ts:52-66`) | 최대/최소·탐침 값 |
| `manifest.json` | bbox·supports[{node_id, vertex, dof, x0}]·top·clusters·ranges | 층 토글(표식 유무), 범례 자동 범위 |
| `recon.bin`(③·재현 진단) | tgt·fit·err 3n | 같은 규칙 |

지지 표식은 `dof` 문자열만 있고 종류(tie·3-2-1·스프링) 열이 없다(백엔드 `api/services/view3d.py:48`·`:305-322`, 코어 `stages.py:4609`) — 종류별 토글은 백엔드 변경이 필요해 P2(VW-P8). **결론: P1 은 기존 자료만으로 된다(백엔드 변경 0).**

### 0.4 강성 스터디 결과 배치 (지금)

`DoeStudy.tsx:2034-2074` `.doe-result-2col`(왼 1.35fr | 오른 1fr, `styles.css:3178-3192`):
- 왼쪽: `DoeRanking`(순위 표) → "ESL별 개선율" `DoePerEslTable`.
- 오른쪽: 선택 머리 줄(`doe-pick-bar` — 선택 안·재낙하·검증 낙하 버튼) → "3D 비교" `Compare3D`(2카드) → "민감도" `Sensitivity`(또는 숨김 사유 한 줄 `sens-hidden`).
- 높이 예산(≥ 2201px, `styles.css:3199-3221`): `--doe-res-h = 100vh − topbar − 21rem`, 3D 칸 = `0.26 × --doe-res-h` → **2560×1440 에서 ≈ 268 px**(카드 폭 ≈ 520 px). ≤ 2200px 는 1열로 쌓이고 3D 칸 = `clamp(260px, 36vh, 560px)`(1920×1080 ≈ 389 px, `styles.css:2768-2770`).
- 사용자 지적 "넘 작다" = 2560 에서 3D 칸 268 px.

### 0.5 스터디 지그 3D (지금)

- 지그 3D 는 **지그 고정(src `jig`) 한 방식만**: `stages.py:4565` `_jig_view3d` — 조건 `prep/jig.json` ok ∧ `prep/jig.npz`, 키 `view3d_jig·_esl·_ref`(BD_POST = result.json, 다시 만들기 = 사이드카 `post/jig_view.json`, `:5016`).
- 지그 변위(`jig_disp`)·스프링(`jig_spring`)은 순위·사이드카 rank_views 만 있고 **3D 없음** — 화면 행 `view3d: "pair"`·`pairKeys: null`(`doeTabs.ts:164-202`, 주석 "3D 칸 = 후속(R-JIGC-2)").
- v0.24.5 기본 `rank.jig.methods = [prescribed, spring]`(D-0.24.5-VT-13) → 고정을 계산하지 않아 `prep/jig.json` 이 없음 → **새 스터디는 지그 3D 가 하나도 없다**.
- 응답 재풀이는 이미 새 npz(BC 배열) 경로가 있다: `stages.py:4532-4542` `_jig_resp_rows`(저장 BC — 엔트리 값·바닥·k 로 재풀이). 방식 산출물 `prep/<src>.json·.npz`(`:4224-4240`).
- 다시 만들기: `POST /doe/studies/{sid}/sources/{src}` 표 `SOURCE_ADD`(`api/services/doe.py:100-106`)에 `jig` 행만(need `jig_ok` = result `jig.status ∈ {ok, poor}` `:2019-2021`) — 고정을 안 한 스터디는 지그 3D 를 다시 만들 수도 없다.

### 0.6 지그 방식 탭 사유 (지금)

| 단계 | 위치 | 지금 |
|---|---|---|
| 탭 가능 | `doeTabs.ts:331-346` `tabState` | `rank_views[key]` 있음 ∨ 주 출처 |
| 보기 생성 조건 | `stages.py:4665-4672` RANK_SOURCES `need` = 베이스라인 per_esl 의 `C_jd`·`C_js` | 방식이 실패하면 키가 없음 → 보기 없음 |
| 실패 기록 | `stages.py:4495-4507`(공유 단계 실패 → 모든 방식 `_jig_fallback_src`, code JIG_NO_TIE·JIG_SUPPORT_DEGENERATE·JIG_SKIPPED + detail), `:4402-4408`(방식 단계 실패 → 그 방식만), `:4242-4248`(`prep/<src>.json` status fallback·code·detail) | 코어는 상태를 안다 |
| 결과 블록 | `stages.py:5556-5582` `_jig_post` → result.json `jig.methods{src: {method, method_name, tie_dofs, status, code, detail, fit_mac_min, fit_umax_err_max, warnings, limits, n_jig, bc, spring}}`·`jig.tie_dofs` | 코어는 쓴다(`esl_jig_case.md:609`) |
| **API** | `api/schemas.py:30-31`(`_Out extra="ignore"`)·`:2063-2086` `DoeJigOut` 에 `methods`·`tie_dofs` **필드 없음** | **응답에서 떨어짐** |
| 화면 사유 | `doeTabs.ts:106-110` `jigMethodUnavailable` | 무조건 "이 스터디에서 계산하지 않은 방식입니다" |

현장 증상(요청 4)의 원인: 계산했지만 실패(fallback)한 방식도 보기가 없으니 화면은 '계산 안 함'으로 표시. 백엔드가 `jig.methods` 를 떨어뜨려 화면은 구분할 자료가 없다.

---

## 1. 기능 목록 — P1 / P2 / 제외

### 1.1 판정 기준
- **P1(이번 구현)** = 사용자 명시 요구, 또는 이 플랫폼 용도(ESL 하중·응답 비교, 설계안·출처 비교)에서 지금 **읽을 수 없는 정보**를 읽게 하는 것 중 새 보이는 버튼이 2개 이하이고 백엔드가 필요 없는 것.
- **P2(제안만)** = 쓸모는 있으나 OS 기능·기존 기능으로 대체되거나 버튼·비용이 늘어나는 것. 사용자가 고르면 같은 묶음(W-F1)에 더한다(Q-VW-1).
- **제외** = 자료가 없거나(백엔드 대공사) 용도 밖·기존 화면이 이미 하는 것.

### 1.2 P1 (8개 — 보이는 새 버튼 2개 + ⚙ 1개)

| ID | 기능 | 근거 |
|---|---|---|
| VW-F1 | **경계조건 층 켜기/끄기**(지지 ▲◭△·축 선분·tie·3-2-1 면내·스프링 표식 전부) | 사용자 명시 |
| VW-F2 | **하중 층 켜기/끄기**(노드 화살표·군집 합력·영역 합력·라벨) | 사용자 명시 |
| VW-F3 | **원형 겹쳐 보기**(변형 형상일 때 원형 외곽선 회색) | HV Deformed 의 기본. 배율 ×100 대에서 "어디서 얼마나 움직였나"를 기준 없이 못 읽음. 자료 = 이미 있는 x0·삼각형 |
| VW-F4 | **최대(·최소) 위치 표식 + 값 + 노드 ID** | 설계안·출처 비교의 핵심 숫자. 지금 3D 에서 최대 위치를 알 길 없음(탐침으로 더듬어야 함) |
| VW-F5 | **범례 구간(레벨 수) + 겹침 범례 값 눈금** | HV Contour 기본(구간). 지금 연속 띠 + 0·최대 숫자만이라 중간 값을 못 읽음 |
| VW-F6 | **탐침 보강**: 현재 색 값·u 성분·좌표 | 변위 색에서 클릭해도 변위 값이 안 나옴(§0.2) — 정보 결손 |
| VW-F7 | **수동 범위 유지**: ③ 출처·하중 성분을 바꿔도 같은 수동 범위(범위 고정) | 출처 비교 시 같은 색 척도가 필요한데 지금 출처를 바꾸면 수동 범위가 초기화. 새 버튼 0 |
| VW-F8 | **비교 쌍 동기화**: 2카드 보기에서 시점·변형·층·범례 레벨 공유 | 설계 비교 2카드를 따로 돌려야 함(시점 없음·설계 비교는 변형도 따로). 새 버튼 0 |

### 1.3 P2 (제안 — 이번 기본 가정 = 구현 안 함, R-VW-1)

| ID | 기능 | 판정 근거 |
|---|---|---|
| VW-P1 | 메시 선(요소 경계) | 30만 노드면 칸 전체가 선으로 덮임(확대해야 의미). 사각형 대각선 제거는 `triangulate` 순서 규칙으로 가능. 비드 윤곽은 F3 특징선이 더 잘 보임 |
| VW-P2 | 범위 밖 색(회색)·최솟값 입력·Iso(문턱 이상만 색) | 지금 끝색 + ▲▼ 개수로 범위 밖을 알 수 있음. 크기 필드라 최소 0 고정이 자연스러움 |
| VW-P3 | 변형 0→1 애니메이션 | 선형 정적 결과 — 배율 슬라이더로 대체 |
| VW-P4 | 화면 캡처 PNG(범례·제목 합성) | OS 캡처(Win+Shift+S)로 대체. F5 겹침 범례가 캔버스 위라 OS 캡처에 같이 찍힘 |
| VW-P5 | 화살표 길이 배율 | 길이는 L_max = 0.10·diag 고정 + 최소 길이로 이미 보임 |
| VW-P6 | 변위 성분 컨투어(u_n 부호·ux·uy·uz, 발산 색) | 판정·순위 지표가 \|u\| — 성분은 보조 |
| VW-P7 | 시점 저장(브라우저) | 표준 시점·단축키로 충분 |
| VW-P8 | 경계조건 종류별 토글(tie·3-2-1 면내·스프링) | manifest supports 에 kind 열 필요 → 백엔드·3D 다시 만들기(§0.3). F1 하나로 사용자 요구 충족 |
| VW-P9 | 비교 쌍 탐침 동기(같은 노드 두 카드 값) | F6 으로 각 카드 값은 읽힘 |

### 1.4 제외

| 기능 | 근거 |
|---|---|
| 단면(section cut) | 대상이 셸 한 부품 — 3D 단면은 선 하나. ④ `SectionChart`(2D 단면 그래프)가 이미 있음 |
| 부품별 표시/숨김·투명 | 3D 자료 = 대상 부품 메시 1개(주변 부품 형상 없음). 지그 진단의 상대 부품은 tie 표식 색으로만 있음 |
| Measure(거리·각도) | 용도 밖 — F6 좌표로 대체 |
| 변위 벡터 플롯 | 변형 형상으로 충분, 화살표는 하중 전용(혼동 방지) |
| 텐서·주응력·Iso 곡면 | 자료 없음(셸 변위·하중만) |
| 시점 공유(URL) | 공유 필요 없음(메인 지시) |
| ④ 2D 겹쳐보기를 3D 로 | 범위 밖 — Q-VW-2 기본 가정 |

---

## 2. P1 동작 상세

### 2.1 층 토글 (VW-F1·F2)
- 층 = `bc`(지지 표식 전부 — 스프라이트·축 선분), `load`(화살표 선·원뿔·라벨). 켜고 끄기 = 장면 객체 `visible` 만 바꾼다(다시 만들기·요청 없음). 데이터가 없으면(supports 0개 / 화살표 0개) 칩 비활성 + title "이 보기에 경계조건 표식이 없습니다"/"…하중 화살표가 없습니다".
- 끈 층은 클릭 선택(pick)에서 빠진다: `load` 끔 → 화살표 pick 없음, `bc` 끔 → 지지 pick 없음·지지 선택 해제.
- `load` 끔 + 표(③ LoadTable) 행 선택 → 화살표 강조 대신 노드 표식(주황 점, `selMarker`)으로 위치를 보인다. 화살표 단계 슬라이더는 그대로 켜 둔다(표 행 수를 정함).
- 바닥 줄 `v3d-note` 는 그대로 + 끔이면 끝에 " · 화살표 숨김"(정보 삭제 없음 — 문구만 더함, 같은 줄).
- 단축키(3D 칸 초점, 기존 1·3·7·0·F 와 같은 규칙): **B** = 경계조건, **L** = 하중.

### 2.2 원형 겹쳐 보기 (VW-F3)
- 변형 형상이 켜졌을 때만 활성(꺼져 있으면 ⚙ 항목 비활성 + 사유). 그리는 것 = 원형(기준 x0) **특징선**: 자유 경계 모서리(인접 삼각형 1개) + 이면각 > `FEATURE_DEG`(30°, `edges.ts` 상수 한 곳) 모서리. 동일 평면 사각형 대각선은 이면각 0 이라 자연히 빠진다.
- 색 회색 `#8a93a0`, 1 px `LineSegments`(깊이 검사 켬). 전체 해상도 기하로 1회 계산(처음 켤 때, 기하가 바뀔 때만 — 캐시), LOD 표시 중에도 같은 선(기준 위치라 변하지 않음).

### 2.3 최대·최소 표식 (VW-F4)
- 대상 = **지금 칠한 색 필드**(하중 성분·목표/응답/오차·설계 응답) — 표식 값·범례·탐침이 같은 배열을 본다.
- 최대 = 유한값 중 최대 정점(같으면 작은 정점 번호), 노드 ID = glb `_NODE_ID`. 표식 = 화면 크기 고정 점 + 라벨 "최대 4.56 mm · N12345"(스프라이트, 흰 바탕). 위치 = 변형 위치(x0 + k·u, 지지 표식과 같은 식).
- 최소 표식은 범례 종류가 `zero`(0 이상 크기 필드 — 지금 3D 의 모든 필드)가 **아닐 때만**(0 노드가 많아 위치가 무의미). P2 성분 컨투어가 들어오면 자동으로 최소도 보인다(종류 열로 결정 — 이름 분기 없음).
- `fieldOverride`(지그 진단 영역 색)는 표식 없음(영역 구분 색 — 최대가 의미 없음).
- 표식은 pick 대상 아님. 범위를 줄여도 값은 실제 최대(범위 밖이어도 표시).

### 2.4 범례 구간 + 겹침 범례 (VW-F5)
- 레벨 선택지 `LEVEL_CHOICES = [0, 6, 9, 12]`(0 = 연속, `viewerPlan.ts` 한 곳). 기본 = 연속(지금 화면 그대로 — Q-VW-3).
- 색 규칙(셰이더·CPU 기준 함수 공통 `colors.bandT`): t = clamp((v − min)/(max − min), 0, 1), 레벨 L > 0 이면 t ← (min(⌊t·L⌋, L−1) + 0.5)/L, 퇴화 범위(max ≤ min) = 0, NaN = 회색 `NAN_RGB`. 색표 = 지금 Blues 256 칸(`LUT_SIZE`) 의 round(t·255) 칸 — 연속 모드는 지금 CPU 결과와 같다.
- 구간 모드(L > 0)일 때만 **겹침 범례**(`LegendOverlay`, 3D 칸 왼쪽 위 겹침): 제목(범례 문구 줄임 + 단위) · 위 = 최대, 아래 = 최소 순 L 칸 · 경계값 L+1 개(f3) · 범위 밖 ▲/▼ 개수(있을 때) · 최대 표식이 켜졌으면 "최대 v @N id" 한 줄. 칸 높이가 모자라면(경계값 간격 < 0.9rem) 경계값을 한 칸 걸러 표시. pointer-events 없음. 폭 ≤ 10rem.
- 바닥 `ColorLegend`(최대 입력·[자동]·▲▼)는 그대로, 색 띠만 구간이면 계단 그라디언트(`colors.bandedGradient(L)`, 기존 `gradient` prop). 연속이면 지금 띠.

### 2.5 탐침 (VW-F6)
- 노드 클릭 정보 줄(`v3d-info`, 칸 왼쪽 아래 겹침 — 자리·높이 그대로) 내용 순서: `노드 {id} · {색 필드 짧은 이름} {값} {단위} · u ({ux}, {uy}, {uz}) mm · 면압·|Fn|·|F|(값이 있으면 지금 그대로) · ({x}, {y}, {z}) mm`. 넘치면 말줄임, 전체 = title.
- 값 표기: values.bin 은 지금처럼 양자화 간격까지(`fmtQuant`), recon 배열(float32)은 f3. u 는 지금 보이는 u(`dispOverride` 우선, 없으면 values.bin u). 좌표 = 기준 x0(변형 전 — 원 모델 위치를 찾는 용도).
- 화살표·군집·지지 선택 문구는 지금 그대로.

### 2.6 수동 범위 유지 (VW-F7, 의도 변경)
- ③ `CaseView3D`: 수동 범위를 **보기(목표·응답 공통 | 오차)·하중 성분 단위로 Case 안에서 유지** — 출처 탭을 바꿔도 같은 수동 범위로 칠한다. [자동] = 그 출처의 자동 범위로 되돌림(지금과 같음). Case(runId)가 바뀌면 초기화(지금과 같음).
- 하중 수동 범위의 기억 키: `esl.legend.v1:<runId>:load:<layer>`(출처 접미 없음). 옛 출처별 키 `<runId>:<src>` 는 읽지 않고 그대로 둔다(저장소 정리 없음).
- 스터디 2카드 보기는 지금도 공유 — 그대로.

### 2.7 비교 쌍 동기화 (VW-F8)
- 2카드 보기(스터디 설계 비교·지그/출처 응답 쌍·지그 진단·재현 진단)는 쌍 하나가 `ViewerSync` 1개를 공유: **시점**(카메라 위치·타깃·up·직교 zoom·투영), **변형**(켜기·배율·×1 — 지금 `deformSync` 를 이것으로 흡수), **층**(bc·load·ghost·marks), **범례 레벨**. 색 범위는 지금 규칙 그대로(이미 공유).
- 한 카드에서 회전·줌·팬·시점 버튼 → 같은 프레임(rAF)에 상대 카드 적용. 적용 중에는 다시 내보내지 않음(핑퐁 금지 — 출처 id 가드).
- 설계 비교(`Compare3D`)의 변형이 지금은 카드마다 따로 → 공유로 바뀜(의도 변경). Case ③(카드 1개)은 동기화 없음.

---

## 3. 화면 배치 (3D 카드 — 2560·1920 모두 세로 증가 0)

| 자리 | 지금 | 이후 |
|---|---|---|
| 카드 머리 줄 | 제목 · 출처 탭(③) | **그대로** |
| 도구 줄 `v3d-tools` | 보기 세그먼트·하중 색·화살표 단계·변형·배율·×1·원근·재현 줄 | **그대로**(새 요소 0 — 좁은 카드에서 줄바꿈이 늘지 않게) |
| 칸 오른쪽 위 겹침 `v3d-view-bar` | X · Y · Z · 등각 · 꽉 차게 · (선택 맞춤) | **[경계조건] [하중]** ┃ X · Y · Z · 등각 · 꽉 차게 · (선택 맞춤) ┃ **[⚙]** — 같은 겹침 막대 한 줄(높이 1.7rem 그대로). 칩 = 글자 토글(aria-pressed, 켬 = 지금 `.on` 색) |
| ⚙ 팝오버 `v3d-viewer-pop` | — | 막대 아래 절대 위치(레이아웃 영향 0, Esc·바깥 클릭 닫힘, 키보드 순회): ☐ 원형 겹쳐 보기(변형 켤 때만) · ☐ 최대 표식 · 범례 [연속 \| 6 \| 9 \| 12] 세그먼트 · 작은 안내 "이 브라우저에 기억됩니다" |
| 칸 왼쪽 위 겹침 | — | 구간 모드일 때만 `LegendOverlay`(§2.4) |
| 칸 왼쪽 아래 겹침 `v3d-info` | 탐침 줄 | 같은 자리, 내용만 §2.5 |
| 바닥 줄 `v3d-foot` | 화살표 문구 · ColorLegend | **그대로**(띠만 구간 계단, 문구 끝 " · 화살표 숨김"은 같은 줄) |

- 막대 폭 ≈ 22rem(2560: ≈ 375 px, 1920: ≈ 330 px). 가장 좁은 칸 = 1920 스터디 2카드(§7 이후 ≈ 900 px) — 겹침 범례(≤ 10rem)와 겹치지 않음. 막대가 칸 폭의 60 % 를 넘으면(카드 < 620 px) 칩 글자를 "경계"·"하중"으로 줄임(title 전체).
- 비드 선택 3D·PartView(편집 보기)는 `PartStage` 를 같이 쓰지만 `controls` 를 안 넘기므로 막대가 지금 그대로(칩·⚙ 없음).
- **세로 증가 0**: 새 요소는 모두 칸 위 겹침·팝오버(절대 위치). Playwright 로 ③ 페이지 `scrollHeight`·3D 카드 높이를 v0.24.5 와 같은 값(±0 px)으로 확인(2560×1440·1920×1080).

---

## 4. 상태 저장

- 기억함: 층(bc·load·ghost·marks)·범례 레벨을 **보기 종류(계획 표 키)별**로 이 브라우저에 — `localStorage["esl.v3d.viewer.v1"]` = JSON `{<planKey>: {bc, load, ghost, marks, levels}}`(키 1개). Case·스터디마다가 아니라 보기 종류마다(같은 습관을 모든 Case 에).
- 읽기·쓰기 모두 try/catch, 형식이 틀리거나 저장소가 없으면 계획 표 기본값(오류 표시 없음, 이번 화면에서만 유지). 공유·서버 저장 없음.
- 기억 안 함: 시점(VW-P7)·탐침·선택. 수동 범위는 지금 규칙(`esl.legend.v1:…`, §2.6).
- 쌍 동기화 상태는 메모리(쌍 생성 때 그 계획 키의 기억값으로 시작).

---

## 5. 성능 (30만 노드, 기존 §11 목표 유지)

| 동작 | 목표 | 방법 |
|---|---|---|
| 층 토글(F1·F2) | 다음 프레임 1회 렌더, 네트워크 0, 정점 루프 0 | 장면 객체 `visible` 만 |
| 범례 변경(범위·레벨) | 다음 프레임 1회 렌더, **정점 루프 0·버퍼 업로드 0** | GPU 재색칠: 정점 스칼라 속성 `aValue` + 색표 텍스처, 범위·레벨 = uniform(`uMin·uMax·uLevels`) — `MeshLambertMaterial.onBeforeCompile` 패치(조명 그대로). NaN = 큰 값 표지(3.0e38 초과 → `uNaN` 색) |
| 색 필드 변경(보기·성분 전환) | ≤ 10 ms | `aValue` 1회 업로드(LOD 층은 `_SRC` 로 모음 1회) — 지금 색 루프와 같은 수준 |
| 원형 외곽선 처음 켬 | ≤ 300 ms(1회·기하 캐시), 이후 토글 = visible | `edges.ts` 타입 배열 해시(Map 금지) |
| 최대·최소 계산 | ≤ 5 ms(필드 바뀔 때만) | 단일 루프, 변형 배율 변경은 위치만 다시 |
| 시점 동기화 | 상대 카드 같은 rAF, 렌더 1회 | 컨트롤 change 이벤트 |
| 조작 | ≥ 30 fps(지금 목표) | 선 객체 수 ≤ 2(특징선·지지), 스프라이트 ≤ 2(최대·최소) 추가 |
| 메모리(카드당 추가) | ≤ 10 MB | aValue 1.2 MB + 특징선 색인 ≤ 8 MB |

장면 `stats()` 에 `valueUploads`(aValue 업로드 수)·`colorLoops`(CPU 색 루프 수 — 이후 0)를 더해 시험이 "범례 변경 = 업로드 0"을 확인한다. 요소 모드(편집 보기 `setElemColors`)는 그대로.

---

## 6. 공용 모듈 · 계획 표

### 6.1 모듈 (새 = ★)

| 파일 | 역할 |
|---|---|
| ★`view3d/viewerPlan.ts` | `VIEWER_PLANS` 계획 표·`LEVEL_CHOICES`·`ViewerState` 타입·`planOf(key)` |
| ★`view3d/viewerPrefs.ts` | `readViewerPrefs(planKey)`·`writeViewerPrefs(planKey, s)`(try/catch) |
| ★`view3d/viewerSync.ts` | `useViewerSync(planKey)` → `ViewerSync`(쌍 공유 상태 + 카메라 브로드캐스트) |
| ★`view3d/ViewerControls.tsx` | 겹침 막대의 칩 2개 + ⚙ 팝오버(층·레벨). `ViewToolbar` 의 `lead`/`tail` 자리로 들어감 |
| ★`view3d/LegendOverlay.tsx` | 구간 겹침 범례(§2.4) |
| ★`view3d/edges.ts` | `featureEdges(positions, indices, deg)` → Uint32Array(정점 쌍) — 순수 |
| ★`view3d/marks.ts` | `extremes(values)` → {max:{vertex,value}, min:…}(NaN 무시) — 순수 |
| `view3d/colors.ts` | += `bandT(v, min, max, levels)`·`bandedGradient(levels)`(CSS 계단) |
| `view3d/sceneApi.ts`·`scene.ts` | §6.3 메서드 |
| `view3d/ViewToolbar.tsx`·`part/PartStage.tsx` | `controls?: ReactNode`(막대 앞뒤 자리) — 안 주면 DOM 동일 |
| `view3d/View3DCard.tsx` | 옵션 `plan`(계획 키)·`viewerSync`(쌍 공유 — 없으면 카드 자체 상태), `deformSync` 는 `viewerSync` 가 있으면 무시(호환 유지) |
| `view3d/info.ts` | §2.5 |
| `view3d/CaseView3D.tsx`·`useLoadView.ts` | §2.6(수동 범위 유지·하중 범위 키) |

### 6.2 계획 표 `VIEWER_PLANS` (보기 종류 → 선언, 모든 열 필수 — 빈 칸 = 시험 실패)

| key | 쓰는 곳 | layers(쓸 수 있는 층) | sync | 기본 bc | 기본 load | 기본 ghost | 기본 marks | 기본 levels |
|---|---|---|---|---|---|---|---|---|
| `case_load` | ③ 하중 보기 | bc·load·ghost·marks | none | 켬 | 켬 | 끔 | 켬 | 0 |
| `case_disp` | ③ 목표·응답·오차 | bc·load·ghost·marks | none | 켬 | 켬 | 끔 | 켬 | 0 |
| `study_design` | 스터디 설계 비교·응답 쌍(지그·지그 변위·스프링·경계력·내력) | bc·load·ghost·marks | pair | 켬 | 켬 | 끔 | 켬 | 0 |
| `study_jigdiag` | 지그 진단 | bc·load·ghost·marks | pair | 켬 | 켬 | 끔 | 켬 | 0 |
| `study_recon` | 재현 진단 | bc·load·ghost·marks | pair | 켬 | 켬 | 끔 | 켬 | 0 |

- 카드는 계획 열만 읽는다(보기 이름 분기 없음). 층이 데이터상 없으면(표식 0개) 열이 켜져 있어도 칩 비활성(§2.1).
- 새 3D 보기를 더할 때는 행 하나를 더한다(모든 열 채움).

### 6.3 SceneApi 추가 (three 무관 인터페이스 — 시험 mock 이 흉내, 선택 메서드)

```ts
setLayerVisible?(layer: "supports" | "arrows" | "ghost" | "marks", on: boolean): void; // visible 만, pick 도 따름
setField?(values: Float32Array): void;                 // aValue 업로드(필드 바뀔 때만)
setLegend?(l: { min: number; max: number; levels: number }): void; // uniform 만
setValueMarks?(marks: { vertex: number; position: V3; text: string }[]): void;
cameraState?(): CameraState; applyCameraState?(s: CameraState): void; onCameraChange?(cb: (s: CameraState) => void): void;
stats(): { renders: number; valueUploads?: number; colorLoops?: number };
```
`setColors(values, min, max)` 는 호환 래퍼(= `setField` + `setLegend({min, max, levels: 0})`) — 편집 보기·옛 호출부 그대로.

---

## 7. 강성 스터디 결과 3행 배치 (요청 2)

### 7.1 배치 (정보는 이동만 — 삭제 0)

```
[카드 머리: 제목 · 출처 탭(LoadTabSeg) · 받기]            ← 그대로
[상태 띠(칩)·숨김 출처 알림·노드 힘 사유 줄·지그 방식 사유 줄(§9)] ← 그대로(§9 줄만 조건부 추가)
[행 1 · 전체 폭] 선택 머리 줄(doe-pick-bar) → "3D 비교" → Compare3D(2카드 · 지그 진단 · 재현 진단)
[행 2] 순위 표 DoeRanking (왼 1.35fr) | "ESL별 개선율" DoePerEslTable (오른 1fr)
[행 3 · 전체 폭] "민감도" Sensitivity  (또는 숨김 사유 한 줄 sens-hidden)
```
- 컨테이너 `.doe-result-rows`(testid `doe-result-rows`, id `doe-load-panel`·role tabpanel 이동), 행 `doe-row-3d`·`doe-row-tables`·`doe-row-sens`. `.doe-result-2col`·`solo`·`--doe-res-h` 규칙은 삭제(시험 `doe_v0233.test.tsx:67·80` 선택자 갱신 — 의도 변경).
- 선택 머리 줄(선택 안 이름·재낙하·검증 낙하)·3D 머리 줄(비교 안 select·모드·색 세그먼트·조건 줄)·출처 탭·칩 위치 규칙은 그대로(3D 위). 순위 표에서 행을 고르면 위 3D 가 바뀐다 — 화면을 옮기지 않음(스크롤 점프 금지). 3D 행 머리 "비교 안" select 로 표를 안 보고도 고를 수 있음(지금 있음).

### 7.2 높이·폭 (각 행이 한 화면 — 세로 스크롤 증가는 허용)

| | 2560×1440 (rem 17 px) | 1920×1080 (rem 15 px) | 규칙 |
|---|---|---|---|
| 3D 칸(카드당) | 폭 ≈ 1210 px · 높이 **820 px**(지금 268) | 폭 ≈ 900 px · 높이 **702 px**(지금 389) | `.doe-row-3d .doe-compare-grid .v3d-host { height: clamp(360px, calc(100vh − var(--topbar-h) − 22rem), 820px) }` |
| 행 1 전체 | ≤ 1386 px(= 1440 − topbar 54) | ≤ 1032 px | 머리·도구·바닥·여백 ≈ 22rem 예산 |
| 행 2 열 | ≈ 1400 \| 1035 px | ≈ 1045 \| 775 px | `grid-template-columns: minmax(0,1.35fr) minmax(0,1fr)` — 1500px 이하만 1열 |
| 행 2 표 최대 높이 | 1080 px | 762 px | 두 표 `--tbl-max: calc(100vh − var(--topbar-h) − 18rem)`, 넘치면 표 안 스크롤·셀 줄바꿈 금지(지금 규칙) |
| 행 3 민감도 | svg 폭 ≤ 64rem(1088 px)·왼쪽 정렬 | ≤ 64rem(960 px) | `max-height: calc(100vh − var(--topbar-h) − 8rem)` (전체 폭으로 늘이면 viewBox 640 비율로 너무 커짐) |

- 지그 진단·재현 진단(행 1 안)은 같은 3D 칸 규칙. 3D 카드 안 도구 줄은 넓어져 줄바꿈이 줄어든다(늘지 않음).
- Playwright: 각 행 boundingBox 높이 ≤ `innerHeight − topbar`(2560·1920), 3D 칸 높이 = 위 값 ±2 px, 정보 요소 testid 전부 존재(이동 전후 같은 목록).

---

## 8. 스터디 지그 변위·스프링 3D (요청 3 — R-JIGC-2 포함, 코어 변경)

### 8.1 코어 (`esl/doe/stages.py`, 출처 계획 표 열)
- `RANK_SOURCES` 열 추가(모든 행 채움): `v3d`(응답 키 3개 또는 None)·`v3d_tag`(폴더 꼬리표)·`v3d_store`(`result`|`sidecar`|None).

  | key | v3d | v3d_tag | v3d_store |
  |---|---|---|---|
  | jig | (view3d_jig, view3d_jig_esl, view3d_jig_ref) | jig | result(지금 `_jig_view3d` — 바이트 동일) |
  | jig_disp | (view3d_jd, view3d_jd_esl, view3d_jd_ref) | jd | sidecar |
  | jig_spring | (view3d_js, view3d_js_esl, view3d_js_ref) | js | sidecar |
  | full | None | None | None |
  | bforce | (view3d_bf, view3d_bf_esl, view3d_bf_ref) | bf | None(노드 힘 경로가 만듦 — 정보 열) |
  | fint | (view3d_fi, view3d_fi_esl, view3d_fi_ref) | fi | None(같음) |
- 새 함수 `_jig_view3d_src(c, t, results, shown, row)` — `v3d_store == "sidecar"` 행마다(호출부는 열만 읽음):
  - 조건: `view3d.jig` 켬 ∧ `_jig_src_ready(c, row.key)`(`prep/<src>.json` ok ∧ npz). 아니면 키 없음(사유는 §9).
  - 비교 안: `shown`(≠ d000) 중 per_esl 이 모두 `C_<pe>` 를 가진 안, worst = `rk._agg(…, f"C_{pe}")["worst"]`(순위 표 '최악 ESL'과 같은 함수).
  - 응답: `_jig_view_mesh`(기준 위상 + 안 좌표) + `jg.forces(basis, a[k])` → `_jig_resp_rows`(저장 BC 재풀이 — 강제 변위 값·스프링 바닥·k 포함). 기준(d000)은 쓰인 엔트리마다.
  - 표식: 새 순수 함수 `esl/mech/jig_bc.support_marks(bc_node, bc_kind, sp_node, x0, smax)` = tie(KIND_TIE) ∪ 스프링 노드 → `jg.support_sample` ≤ `view3d.jig_support_max` 개 '123' + 3-2-1 면내(KIND_AUX) 전부 'ij'(겹치면 tie 우선). 백엔드 Case `_jig_supports` 와 같은 규칙(백엔드 위임 통일은 R-VW-3).
  - 폴더: `post/view3d/<did>_<tag>`·`post/view3d/d000_<tag>_e<kk>`(DID_RE 안), 키 `view3d_<tag>{did: 폴더}`·`_esl{did: entry}`·`_ref{entry: 폴더}`.
  - 실패 격리: 안·기준마다 try — 경고 `VIEW3D_FAILED: <did>_<tag> <code>`, BD_POST·다시 만들기는 실패하지 않음.
- 저장: BD_POST·다시 만들기 모두 **사이드카 `post/jig_view.json`**(`_jig_extras(…, v3_src=…)`) → **result.json 바이트 불변**(새 실행 포함). 다시 만들기(`_post_view3d`)는 사이드카에 이미 그 키가 있으면 옮겨 적고(덮지 않음), 없고 준비됐으면 새로 만든다(고정 `view3d_jig` 규칙은 지금 그대로).
- 비용: 방식마다 고정 지그 3D 와 같은 분해 횟수(안 top_k + 기준 엔트리 수, 노드 MMD 순서 — D-0.24.4-JIG-34). 현장 시간은 사이드카 `view3d_src_seconds{tag: s}`·작업 로그 한 줄로 기록(R-VW-4 실측).
- 설정 키 없음(`view3d.jig`·`jig_support_max` 재사용).

### 8.2 다시 만들기로 기존 스터디에 추가
- 조건 = 그 방식이 계산된 스터디(result `jig.methods[src].status == "ok"`) — **v0.24.4 P2c 이후 스냅샷**(methods 에 그 방식) + v0.24.5 기본 스터디 가능. 옛 스냅샷(methods 없음 = 고정만)·실패한 방식 = 불가(§9 사유).
- 백엔드 `SOURCE_ADD` 행 += `jig_disp`·`jig_spring`(kind VIEW3D·post_mode view3d — 지그 행과 같은 작업, need 새 `jig_src_ok`, code VIEW3D_REGEN·block _UNAVAILABLE, name "지그 3D", legacy None). 한 작업이 빠진 방식 3D 를 모두 만든다(멱등).

### 8.3 API · 화면
- `DoeResultOut` += `view3d_jd·view3d_jd_esl·view3d_jd_ref·view3d_js·view3d_js_esl·view3d_js_ref: dict[str,str] | None` — 사이드카에서 병합(백엔드 거울 표 `RANK_V3D` = 코어 열 `v3d` 와 같음, 거울 시험). result.json 우선 규칙(지그 행)은 그대로.
- 화면 `LOAD_SOURCES` jig_disp·jig_spring: `pairKeys` = 위 키 + `load`("지그 변위"/"지그 스프링") + 새 열 `support`(조건 줄 지지 문구 틀 "지그 tie {tie} 강제 변위 + 3-2-1 면내"/"지그 tie {tie} 스프링 + 3-2-1 면내", {tie} = `jig.tie_dofs` → 법선|병진)·`disp`(변위 라벨). 경계력·내력 행은 지금 문구를 열로 옮김("3-2-1"·"변위 |u| (mm) — 3-2-1(자기평형 하중)" — 화면 글자 불변). `v3dPairCondText(load, grade, names, support)` 의 고정 "지지: 3-2-1" 을 열 값으로. `add` = `{src: "jig_disp"|"jig_spring", label: "지그 3D 다시 만들기", testid: "v3d-regen-jd"|"v3d-regen-js", …, legacy: null}`.
- 3D 가 없으면 지금 규칙("지그 응답 3D 가 없습니다 — [지그 3D 다시 만들기]로 만드세요" + 버튼, 화면에 최대 1개).

---

## 9. 지그 방식 탭 사유 (요청 4)

### 9.1 상태 4가지 (순수 함수 `jigMethodState(r, key)` — `doeTabs.ts`, 문구 표 `JIG_STATE_TEXT` 한 곳)

| 상태 | 판정(응답만 읽음) | 탭 사유(why) | 마우스 없이 보이는 줄 |
|---|---|---|---|
| `no_jig` | `r.jig` 없음 | "이 스터디는 지그를 계산하지 않았습니다" + (`jig_on_clone` 참이면) " — 복제하면 지그를 계산합니다" | 없음(설계상 없음) |
| `not_planned` | `r.jig` 있음 ∧ (`r.jig.methods` 없음 = 옛 단일 경로(고정만) ∨ key 가 methods 에 없음) | "이 스터디에서 계산하지 않은 방식입니다: {label} — 복제(현재 설정 rank.jig.methods)로 다시 계산" | 없음 |
| `failed` | `methods[key].status ≠ "ok"` | "{label} 계산 실패: {code} — {detail 120자}"(전체 = title) | **있음** `jig-unavail-note`(role status, data-src) — 노드 힘 사유 줄과 같은 자리·규칙, 3D 다시 만들기로는 못 고침을 덧붙임("원인을 고친 뒤 복제로 다시 계산") |
| `no_view` | status ok ∧ `rank_views[key]` 없음 | "{label}: 계산됐지만 기준(d000) 값 C_{pe} 가 없어 순위를 만들지 못했습니다 — {warnings 첫 항목}" | **있음**(같은 줄) |

- 줄은 방식마다 1줄, `ui.hidden_sources` 로 숨긴 출처는 줄도 없음(D-0.24.5-VT-12 규칙). 탭 why 는 지금처럼 title·sr-only·초점 줄·≤ 2200px 팝오버 사유에 같은 문구.
- 탭 3D 칸(rank_views 있음 ∧ 3D 없음)은 §8.3 의 다시 만들기 안내.

### 9.2 백엔드 최소 추가
- `DoeJigOut` += `tie_dofs: Literal["normal","translation"] | None`, `methods: dict[str, DoeJigMethodOut] | None` — 코어 result.json 값 그대로 통과(옛 결과 = null). `DoeJigMethodOut` = method·method_name·tie_dofs·status(str)·code·detail·fit_mac_min·fit_umax_err_max·warnings[str]·limits[str]·n_jig·bc(dict|None)·spring(dict|None). `types.ts` 거울·check:api.
- 스냅샷 노출은 필요 없음(methods 키 목록 = 스냅샷 방식 목록 — `_jig_post` 가 계획의 모든 방식을 씀).

---

## 10. 백엔드 · 코어 변경 요약

| 범위 | 변경 |
|---|---|
| 3D 뷰어(§1~§6) | **없음** — 기존 manifest·glb·values·recon 만 |
| 스터디 결과 배치(§7) | 없음(화면만) |
| 스터디 jd·js 3D(§8) | 코어: RANK_SOURCES 열 3·`_jig_view3d_src`·`_jig_extras`/`_post_view3d` 옮겨 적기·`jig_bc.support_marks`. 백엔드: 응답 필드 6·사이드카 병합·SOURCE_ADD 2행·NEED `jig_src_ok` |
| 탭 사유(§9) | 백엔드: `DoeJigOut.methods·tie_dofs` 노출만 |
| DB·설정 | 없음 |

---

## 11. 하위 호환

- 옛 스터디(다시 만들기 안 함): result.json·사이드카·폴더 바이트 동일, 응답은 새 키 null. 옛 단일 경로 스터디 다시 만들기 = v0.24.5 다시 만들기와 같은 사이드카(새 키 없음).
- 새 실행: result.json 은 v0.24.5 와 같은 키·바이트(jd·js 3D 는 사이드카만). 고정 지그 3D(`view3d_jig*`)·지그 진단 바이트 동일(골든).
- 화면 의도 변경: ③ 수동 범위가 출처 전환에 유지(§2.6), 설계 비교 변형·시점 공유(§2.7), 스터디 결과 3행(§7), 지그 방식 탭 사유 문구(§9), 경계력·내력 pair 문구 열 이동(글자 불변).
- localStorage 새 키 1개(`esl.v3d.viewer.v1`), 옛 키 정리 없음.

---

## 12. 시험 (V-0246-VW-n)

| ID | 종류 | 내용 |
|---|---|---|
| 1 | vitest | `VIEWER_PLANS` 모든 행·열 채움, `LEVEL_CHOICES` 0 포함, 알 수 없는 키 = 오류 |
| 2 | vitest | 층 토글 → mock `setLayerVisible` 호출, fetch 호출 수 불변(재요청 0), 끈 층 pick 무시·지지 선택 해제, 데이터 없으면 칩 비활성 |
| 3 | vitest | 하중 끔 + LoadTable 행 선택 → 노드 표식, 바닥 문구 " · 화살표 숨김", 단축키 B·L(입력 칸 초점이면 무시) |
| 4 | vitest | `bandT`: v = max → 마지막 칸, v < min → 첫 칸, NaN, 퇴화 범위, L = 0 은 `normalize` 와 같음; `bandedGradient(9)` 계단 정지점 18개 |
| 5 | vitest | 범례 범위·레벨 변경 → `setLegend` 만(`setField` 0회, `stats().valueUploads` 불변, `colorLoops` 0) |
| 6 | vitest | `LegendOverlay`: L+1 경계값·높이 부족 시 한 칸 걸러, ▲▼ 개수, 연속이면 렌더 없음 |
| 7 | vitest | `extremes`: NaN 무시·동률 작은 정점, zero 종류 = 최대만, fieldOverride = 표식 없음, 변형 배율 바뀌면 위치만 |
| 8 | vitest | `featureEdges`: 고정 fixture(접힌 플랜지 판, `tests/fixtures/view3d/small`) 자유 경계·접힘선 포함, 평면 사각형 대각선 제외 |
| 9 | vitest | `infoLine` 변위 보기: 값·u 성분·좌표 순서, 양자화 표기, recon f3 |
| 10 | vitest | `CaseView3D`: 수동 범위 → 출처 탭 전환 후 유지, [자동] → 그 출처 자동, runId 바뀌면 초기화, 하중 범위 키에 출처 없음 |
| 11 | vitest | `viewerPrefs`: localStorage 가 던져도 기본값·쓰기 무시, 형식 오류 무시, 계획 키별 저장 |
| 12 | vitest | `ViewerSync`: 한 카드 카메라 변경 → 상대 `applyCameraState` 1회, 핑퐁 없음, 층·레벨·변형 공유, Case ③ 은 sync 없음 |
| 13 | vitest | 편집 보기(BeadSelectCard·PartView) 막대 DOM 이 v0.24.5 와 같음(`controls` 안 줌) |
| 14 | vitest | 스터디 3행 DOM 순서(행1 3D·행2 표\|개선율·행3 민감도), 정보 testid 목록 이동 전후 동일, `doe_v0233` 선택자 갱신 |
| 15 | vitest | `jigMethodState` 4상태 문구·보이는 줄(failed·no_view 만), hidden_sources 숨김, title 전체 detail |
| 16 | vitest | jd·js `pairKeys`·`support`·`disp` 열, 경계력·내력 조건 줄 글자 불변, add 버튼 1개 규칙 |
| 17 | pytest(코어) | `_jig_view3d_src`: 합성 스터디(prescribed·spring) → 폴더·사이드카 키·표식(tie '123' ≤ smax·면내 'ij'·스프링), result.json 바이트 불변, 고정 지그 3D·진단 골든 바이트 동일, 방식 실패 격리(경고만) |
| 18 | pytest(코어) | `_post_view3d`: 옛 단일 경로 스터디 사이드카 = v0.24.5 결과와 같음, 이미 있는 jd 키 옮겨 적기(덮지 않음), 준비 안 된 방식 = 키 없음 |
| 19 | pytest(코어) | `support_marks` 순수(같은 입력 같은 출력, 백엔드 `_jig_supports` 와 노드 집합 같음 — 샘플러 차이는 표로 기록) |
| 20 | pytest(백엔드) | `DoeJigOut.methods·tie_dofs` 통과(옛 결과 null), `view3d_jd*·js*` 사이드카 병합, `RANK_V3D` = 코어 `v3d` 열 거울, `SOURCE_ADD` jd·js 202·409(`jig_src_ok` 거짓)·404 없음, OpenAPI check:api |
| 21 | Playwright 2560×1440·1920×1080 | ③ 페이지 `scrollHeight`·3D 카드 높이 = v0.24.5 빌드(같은 mock) ±0 px, 막대가 칸 안·info 줄·겹침 범례와 안 겹침 |
| 22 | Playwright | 스크린샷: 층 켬/끔, 원형 겹침, 최대 표식, 구간 9 + 겹침 범례, ⚙ 팝오버, 스터디 3행(지그 변위 3D 포함), 지그 실패 사유 줄 |
| 23 | Playwright | 스터디 행마다 높이 ≤ innerHeight − topbar, 3D 칸 820/702 px ±2 |
| 24 | Playwright(성능) | mock 30만 노드 판(`?mockView3d=plate300k`, mock 전용 생성): 층 토글·범례 변경 → 다음 프레임 ≤ 33 ms·`valueUploads` 불변, 원형 첫 켬 ≤ 300 ms, 회전 ≥ 30 fps, 연속 모드 픽셀 = CPU 기준 색 ±1/255 |

---

## 13. 완료 기준

1. 모든 3D 결과 보기 4종에서 경계조건·하중을 각각 한 번 클릭으로 켜고 끔(재요청 0).
2. P1 8개 동작(§2), P2·제외는 문서로만.
3. ③ 2560·1920 세로 높이 불변(V-21), 새 보이는 버튼 = 칩 2 + ⚙ 1.
4. 범례 변경 GPU 재색칠만(V-5·24).
5. 스터디 결과 3행, 행마다 한 화면(V-23), 정보 이동만(V-14).
6. 새 스터디(prescribed·spring)에서 지그 변위·스프링 3D 표시, v0.24.4 P2c 이후·v0.24.5 스터디는 [지그 3D 다시 만들기]로 추가(V-17·18·20).
7. 현장 v0.24.4 스터디 탭 사유가 실제 상태(failed 면 코드·사유 줄) — 현장 응답으로 확인.
8. 옛 결과·고정 지그 3D 바이트 동일(V-17·18), vitest·pytest·check:api 통과.

---

## 14. 작업 분해 (파일 소유 겹침 없음 — 병행 후 통합)

| 묶음 | 담당(모델) | 파일 | 내용 |
|---|---|---|---|
| **C1 코어** | Impl-Backend(sonnet) — 핵심 판단은 계약대로 | `esl/doe/stages.py`(RANK_SOURCES 열·`_jig_view3d_src`·`_jig_extras`/`_post_view3d`), `esl/mech/jig_bc.py`(`support_marks`), `tests/doe/test_jig_view3d_src.py`(새)·골든 | §8.1·§8.2 코어, V-17~19 |
| **B1 백엔드** | Impl-Backend(sonnet) | `backend/esl_platform/api/schemas.py`(DoeJigOut·DoeJigMethodOut·DoeResultOut 6필드), `api/services/doe.py`(사이드카 병합·`RANK_V3D`·SOURCE_ADD 2행·NEED), OpenAPI 덤프, `backend/tests/…` | §8.2·§8.3·§9.2, V-20 |
| **F1 뷰어** | Impl-Frontend(sonnet) | `frontend/src/view3d/`(scene·sceneApi·colors·info·View3DCard·ViewToolbar·part/PartStage·CaseView3D·useLoadView + ★viewerPlan·viewerPrefs·viewerSync·ViewerControls·LegendOverlay·edges·marks), `styles.css` **맨 끝 새 블록 `/* v0.24.6 VW 뷰어 */` 만**, `src/__tests__/view3d_viewer.test.tsx`(새) | §2~§6, V-1~13 |
| **F2 스터디** | Impl-Frontend(sonnet) | `pages/doe/DoeStudy.tsx`(3행·쌍에 `viewerSync`·`plan` 넘김·pair 문구 열), `pages/doe/doeTabs.ts`(jigMethodState·jd/js 열·add), `api/types.ts`, `styles.css` **§6 결과 블록(3178-3222)·`.doe-compare-grid .v3d-host`(2768) 만**, `__tests__/doe_v0233.test.tsx` 갱신·`doe_v0246.test.tsx`(새) | §7·§8.3·§9.1, V-14~16 |
| **V 검증** | Verifier(opus) | `scripts/e2e_viewer.mjs`(새 — 기존 e2e 파일 안 건드림)·mock `plate300k` 는 F1 이 `mock/` 에 | V-21~24, 현장 확인 목록 |

- F1↔F2 계약면: `View3DOptions.plan: string`·`viewerSync: ViewerSync | null`(§6.1), `useViewerSync(planKey)` 시그니처 — F1 이 먼저 타입만 커밋하면 F2 병행 가능.
- 순서: C1·B1·F1·F2 병행 → 통합(B1 응답 ↔ F2 types, C1 사이드카 ↔ B1 병합) → V. 시간이 모자라면 미룸: VW-F8 시점 동기화(변형·층 공유는 유지) → R-VW-2.

---

## 15. 미결 (결과를 바꾸는 것만 — 기본 가정으로 진행)

- **Q-VW-1** P2(§1.3)를 이번에 같이 넣을지 — **기본 가정: 안 함**(P1 만). 고르면 F1 에 더하고 ⚙ 팝오버 안에만 둔다(보이는 버튼 증가 0 원칙).
- **Q-VW-2** ④ 검증 비교(지금 2D PCA 평면)에 3D 보기를 더할지 — **기본 가정: 안 함**(③ 3D 목표·응답·오차와 스터디 3D 가 같은 정보를 줌). 더하면 R-VW-5(④ 판정 카드 아래 같은 뷰어 — 세로 증가 발생).
- **Q-VW-3** 기본 표시값 — **기본 가정: 범례 연속(지금 그대로)·최대 표식 켬·원형 끔**. 9구간 기본을 원하면 계획 표 기본 열 한 곳만 바꿈(스크린샷 기대값 갱신).

---

## 16. 결정 (요약 — 전문 `docs/decisions.md` 2026-11-24)

D-0.24.6-VW-1 범위·판정 기준, VW-2 층 토글, VW-3 원형 겹침, VW-4 최대·최소 표식, VW-5 범례 구간·GPU 재색칠, VW-6 탐침, VW-7 수동 범위 유지, VW-8 쌍 동기화, VW-9 화면 배치, VW-10 상태 저장, VW-11 공용 모듈·계획 표·SceneApi, VW-12 스터디 3행, VW-13 스터디 jd·js 3D(코어·사이드카), VW-14 jd·js 3D API·화면·다시 만들기, VW-15 지그 방식 탭 사유·DoeJigOut 노출, VW-16 하위 호환.

## 17. 후속 (R-VW-n)

- R-VW-1 P2 항목(Q-VW-1). R-VW-2 시점 동기화가 밀리면. R-VW-3 백엔드 Case `_jig_supports` → 코어 `support_marks` 위임 통일(표식 노드 바이트 변화 — 3D 다시 만들기 필요). R-VW-4 jd·js 3D 현장 소요 실측. R-VW-5 ④ 3D(Q-VW-2).

---

## 18. 구현 메모 (2026-11-24, v0.24.6 통합)

- 통합 결과·결정 전문: `docs/decisions.md` D-0.24.6-INT-1~3(핸드오프 이관 포함). 현장 확인표 `docs/manual/field_check_v0246.md`.
- §8.1 `v3_src` = 다시 만들기가 옛 사이드카에서 옮겨 적을 키. 3D 생성은 `_jig_extras` 안 `_jig_v3d_sidecar`. 조건에 `view3d.jig_diag` 포함 — 끄면 jd·js 3D·rank_views 없음(사이드카 자체 조건, v0.24.5 그대로).
- §8.3 백엔드 거울 `RANK_V3D` ↔ 코어 열 v3d 는 `test_rank_v3d_mirrors_core_column` 이 실제 대조, 코어→사이드카→API 전 구간은 `backend/tests/test_doe_v0246_core_e2e.py`.
- §9.1 `no_view` 에서는 빈 탭 [다시 만들기] 를 두지 않는다(`tabState` — 다시 만들기가 순위 보기를 못 만듦). 백엔드 `source_add` 판정(§8.2)은 그대로. 원인 구분 문구는 R-VW-6.
- §17 에 R-VW-6 추가: 응답에 jig_diag 끔·기준 값 없음 원인을 구분하는 키(no_view 문구 정밀화).
- 검증 수정(D-0.24.6-VW-17): 계획 표 열 sync·layers 를 카드가 읽음(`usesPairSync`·`effectiveLayers`), 쌍 기본 변형 배율 = `pairScaleExp`(쌍 최대 대각선·최대 변위, §2.7 — 적재 순서 무관), no_view 는 `sourceNoView` 한 판정으로 탭·3D 행 [다시 만들기] 모두 끔(§9).
