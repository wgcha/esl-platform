# 계약: 강성 평가 스터디 — 비드 직접 선택·규칙 모핑 DOE (BEAD_SELECT, v0.15.0)

- 상태: **초안** (2026-11-04, Plan). 사용자 확정 방향(아래) 반영, 결정 질문 3개(§19) — 권장안으로 작성, 답에 따라 해당 절만 고친다.
- 버전: **v0.15.0** (main a0ed2b2 = v0.13.0 기준 작성). **구현 착수 = v0.14.0(STEP_COMPARE, migration 0014) 이 main 에 병합된 뒤**(같은 파일을 고침 — §17). migration **필요**(§15 — `0015_bead_select`).
- 관계: `esl_bead_doe.md`(BEAD_DOE) 시나리오 ① `same` 의 **변수 출처를 바꾼 변형**. 기준 메시 읽기(`scenario.same_base`, 동일 모델 판정 `topo_sha256`)·하중(① 노드 직접, 모든 안 같은 노드 하중 BD-D-3)·지지(기준 ESL 3-2-1, BD-D-4)·DOE 생성(`esl.doe.matrix`, BD-D-8)·미리보기 필수(BD-D-9)·해석(`evaluate`, BD-D-5)·순위·민감도·ESL별 지표(§11·§11.4)·작업 3종(`DOE_PREP`·`DOE_PREVIEW`·`DOE_RUN`)·폴더(`_doe/<id>/`)·보안(§15)·이어하기(BD-D-16)를 **그대로 재사용**한다. `esl_step_compare.md`(v0.14.0)의 품질 판정(`esl/doe/mesh_quality.py`, `bead_doe.compare.quality` — 이슈 #53 criteria)을 재사용한다. 이 문서에 없는 규칙은 BEAD_DOE 를 따르고, 충돌 시 `select` 범위에서 이 문서가 우선.
- ID 규칙: 결정 `BS-D-n`, 요구 `BS-n`, 시험 `V-BS-n`, 리스크 `R-BS-n`.

### 사용자 확정 (2026-11-04, 변경 금지)
1. **배경**: ① 자동 비드 탐지(paicad `shell extract` — 평면 base 위 1단 4면 비드만 인식)는 실제 Ch/R 비드(깊이 ≈ 22 mm·밑변 폭 ≈ 60 mm·다단·경로를 따라 폭 가변·사면 연속 경로형)를 못 잡고 깊이 3.2 mm·폭 12 mm 보조 형상만 잡는다. HyperMorph 숙련이 필요한 방식 대신 **직관적이고 단순한 B 방식**.
2. **기준** = ① 같은 모델의 낙하 Radioss 메시(노드·요소 ID 불변, `/NODE` 좌표만 바뀜). 사용자가 3D 뷰어(기존 TrackballControls 뷰어)에서 비드 영역을 직접 고르고, 일반 모핑 규칙으로 형상 변수를 만들어 DOE.
3. **선택**: 요소 클릭·브러시·영역(사각/올가미) + 같은 법선·연결 요소 자동 확장(feature angle, 설정값). 다단이면 단(바닥 영역)마다 선택, 사면(바닥↔상판 전이)은 자동 추정 + 수정, 비드 경계(상판과 만나는 선) 자동 제안 + 수정. 결과 = 요소/노드 집합(노드 ID), 스터디에 저장.
4. **변수**: 단별 깊이 Δd(그 단 바닥 노드를 국부 평균 법선 방향으로, 사면 노드는 높이 비율 선형 보간, 경계 노드 고정), 폭 Δw(경계선을 평면 안에서 바깥/안쪽 오프셋, 사면 비례 재배치). 체결 고정 노드 침범 → 경고·안 제외. 변위 연속(경계 밖으로 감쇠하는 블렌딩 반경, 설정).
5. **품질**: 모핑 후 이슈 #53 criteria(v0.14.0 `bead_doe.compare.quality` 와 같은 판정 함수) → Fail 비율 상한 초과 안 = `FAILED_MESH` 제외.
6. **가시화**: 평면도 = 노드 점 숨김(토글), 고른 비드 강조·나머지 흐림, 변수 선택 시 범위(깊이 = 단면 미니 그림, 폭 = 최소·최대 윤곽 점선), 라벨 칩. 미리보기 = 실제 메시 3D 음영 + 공칭 대비 높이 변화 색(파랑 깊어짐·빨강 얕아짐, 모든 칸 같은 범위), **서버 렌더 = esl 워커 직접(paicad 비의존)**, 클릭 → 3D 뷰어.

## 0. 현황 (main a0ed2b2 v0.13.0 + origin/impl/step-compare-be v0.14.0)

| 항목 | 위치 | 현재 | 이 계약에서 |
|---|---|---|---|
| 기준 메시 | `esl/doe/scenario.same_base` → `prep/base_mesh.npz`(`MESH_KEYS` = node_id·x0·elem_id·elem_type·conn·elem_pid·thickness·E·nu) | ① Ch/R 파트만 | 그대로 — 선택·모핑 대상 = 이 파트 |
| 고정 노드 | paicad `shell fixed-scan`(v0.12.1 `prep/assem_full/` 모델 전체 사본) → `paicad_io.read_fixed`(node_id·part·kind_mask·cluster·xyz) | ①② 준비 | paicad 준비됨 → 그대로 실행, 없음 → 경고 + 사용자 수동 지정(BS-D-8) |
| 품질 판정 | v0.14.0 `esl/doe/mesh_quality.element_metrics·summarize`, 설정 `bead_doe.compare.quality` | ④ 경고만 | **같은 함수·같은 기준값**, 영향 요소 한정 + 차단(§6) |
| 3D 뷰어 | `frontend/src/view3d/scene.ts`(FreeRotateControls ⊂ TrackballControls, Raycaster 표면 pick → 정점), `sceneApi.ts`(`setColors`·`setDeform(u,k)`·`onPick`), `glb.ts`(_NODE_ID), `esl/view3d.triangulate`(사각 → 삼각 2개, 요소 순서 유지)·`write_glb` | ESL 하중 보기 | 같은 장면 + **요소 선택 모드**(§11.2) |
| 평면 래스터 | `esl/opt/png.py rasterize`(요소 번호 버퍼)·`encode_png`(결정적) | 평면도 PNG | 3D 썸네일 렌더(깊이 버퍼 추가, §7.2) |
| 미리보기 표시 | `api/services/doe.preview_cells` ← `doe/<rev>/grid/grid_manifest.json`·`cells/<id>/thumb.png` | paicad grid 형식 | **같은 형식으로 워커가 직접 씀**(BS-D-11) → 백엔드·`DoeThumbGrid` 재사용 |
| 시나리오 열 | `bead_does.scenario` v0.14.0 0014 = `String(8)`, CHECK `('same','mesh','step','compare')` | | `select` 추가(§15) |
| migration HEAD | v0.14.0 병합 후 `0014_step_compare` | | **0015** |

## 1. 범위 / 비범위

| 범위 (v0.15.0) | 비범위 (§20 후속) |
|---|---|
| 시나리오 `select`(① 같은 모델 + 비드 직접 선택), STEP 업로드 불필요 | 위치 이동 U/V(Q3 권장 = 보류) |
| 3D 요소 선택(클릭+확장·브러시·사각·올가미, 보이는 면만), 단·사면·경계 | 단별 폭(비드당 폭 변수 1개), 끝단만 늘이기·줄이기 |
| 사면 자동 추정·경계 자동 제안·±1줄 수정, 서버 검증 | 비드 추가·삭제(위상 변경), 리브·두께 변수 |
| 변수 D(단별)·W(비드별), 단 묶음(같은 값), 블렌딩 반경 | ③ STEP 스터디의 모핑 전환(Q2 권장 = 별도 계약) |
| 선형 기저 모핑(22만 노드), 고정 침범·품질 판정, 3D 썸네일 서버 렌더 | paicad extract 결과를 선택 출발점으로 가져오기(§12) |
| 평면도 범위 표시·단면 미니 그림·라벨 칩, 안 3D 보기 | 검증 낙하 자동 실행(① VD 는 그대로 사용 가능 — §8.4) |

## 2. 결정

| ID | 결정 | 근거 |
|---|---|---|
| BS-D-1 | **시나리오 키 `select`**(6자, 0014 의 `String(8)` 안). UI 는 ① 라디오 아래 하위 선택 "비드 정의 ○ 자동 탐지(STEP) ● 직접 선택(메시)" — 코드상 별도 시나리오라 `same` 경로(paicad extract·tag·run)와 분기가 섞이지 않는다. 동일 모델 판정·기준 Case·`ASSEM_TOO_LARGE`·`BD_BASE_CUMULATIVE` 는 ① 과 같음 | ④ `compare` 와 같은 확장 방식, 분기 단순 |
| BS-D-2 | **활성**: `scenarios.select = bead_doe.enabled ∧ bead_doe.select.enabled`. **paicad 무관**(없으면 고정 노드만 BS-D-8 대체). 사유 `DOE_DISABLED`·`SELECT_DISABLED` | 사용자 확정 6 "paicad 비의존" |
| BS-D-3 | **흐름** = [입력 준비] → (READY) **비드 선택·저장** → 변수 표 → [미리보기] → [DOE 실행]. 새 phase 없음: 선택은 READY·PREVIEW_READY 에서 편집 가능, 저장하면 `selection.rev+1` → 미리보기는 **선택 sha 까지 같아야** 유효(409 `PREVIEW_STALE`) | 기존 phase·주 버튼 규칙 재사용 |
| BS-D-4 | **선택 저장 = DB**(`bead_does.selection` JSONB, §4·§15). 요소 집합은 `(type, elem_id)` 정렬 구간 압축으로 저장, 노드·경계·사면 결과는 저장 시 서버가 **결정적으로 다시 계산**(클라이언트 값 불신). 상한 `select.max_selection_kb`(4096) | 백엔드는 `_doe/` 에 파일을 쓰지 않는 기존 규칙 유지, ID 불변이라 구간 압축 효과 큼 |
| BS-D-5 | **역할 분담**: 클릭·브러시·사각·올가미·feature angle 확장 = **브라우저**(즉시 반응). 사면 추정·경계·공칭 치수·단면·검증 = **서버 코어 `esl/doe/bead_select.py`**(백엔드 동기 호출, ≤ 3 s — §5.8). 모핑 기저·안 모핑·품질·썸네일 = **워커** | 같은 알고리즘을 두 언어로 두지 않음(확장만 TS) |
| BS-D-6 | **깊이 변수** = 단 k 마다 절대 깊이 `D_k`(상판 기준면에서 단 k 바닥까지, 공칭 = 측정값). 단끼리 같은 값으로 묶기(`link`) 가능 — 묶음은 변수 1개. 깊어짐 = +. 단 높이 차(상대)가 아니라 절대 깊이: 단이 나란히(경로를 따라 깊이가 바뀜) 있든 포개져 있든 같은 정의 | 다단 형태 모두 같은 규칙, 사용자 설명 "단별 깊이 Δd" |
| BS-D-7 | **폭 변수** = 비드마다 `W`(개구 폭 — 경계선 기준, 공칭 = 국부 폭 중앙값, 최소·최대 함께 표시). 변화 ΔW 는 **양쪽 ΔW/2 씩** 경계 법선 방향(평면 안) 오프셋 → 경로를 따라 폭이 다른 비드는 변화량만 같고 가변 모양 유지. 끝단도 같은 양 이동(길이 +ΔW). 단면 처리 = **바닥도 따라감**(`floor_follow 1`, 사면 각 유지) — **Q1** | 사용자 확정 4, 실설계의 폭 변경 = 비드 전체 넓힘 |
| BS-D-8 | **고정 노드** = (a) paicad 준비됨 → ① 과 같은 `fixed-scan`(`prep/assem_full/`, Ch/R 파트 노드만) ∪ (b) 사용자가 "고정" 층으로 칠한 요소의 노드. paicad 없음/실패 → (a) 없이 경고 `FIXED_INFO_MISSING`(준비 실패 아님, 화면 띠 "체결 정보 없음 — 체결부를 고정으로 칠하세요"). 3-2-1 지지 노드는 고정 아님(ESL 지지는 노드 ID 로 따라감) | 사용자 확정 4 "fixed-scan 결과 또는 RBE2/tie 노드", paicad 비의존 |
| BS-D-9 | **모핑 = 선형 기저 합** x_d = x0 + Σ_v (v − v_nom)·B_v. 기저 B_v(변수당 영향 노드 × 3, float64)는 선택 rev 마다 1회 계산(§5). 블렌딩 반경은 **변수 값과 무관한 비드 속성**(자동 = 범위로 정함) → 완전 선형, 안마다 행렬-벡터 곱만 | 22만 노드 × 200 안 성능, 결정적, 클라이언트 3D 미리보기도 같은 식 |
| BS-D-10 | **고정 침범** = 어떤 안에서 고정 노드 변위 ‖u_j‖ > `select.fixed_tol_mm`(0.01) → 안 `SKIPPED_FIXED`(코드 `SELECT_FIXED_VIOLATION`). 고정 노드를 억지로 0 으로 누르지 않는다(불연속 방지). 선택 저장 시 비드·블렌딩 안 고정 노드 수를 경고로 미리 알림, 블렌딩 반경 자동은 고정 노드 앞에서 잘림(§5.6) | 사용자 확정 4 "침범하면 경고·안 제외" |
| BS-D-11 | **미리보기(select)** = paicad grid 대신 워커 코어 `bd_select_grid`: 기저 → 안 모핑 → 고정·뒤집힘·품질 판정 → 3D 썸네일. 출력은 paicad grid 와 **같은 파일 형식**(`grid_manifest.json`, `cells/<id>/thumb.png`, 공칭 셀 `nominal`) — 셀 status `FAIL` + 코드 `SELECT_*` → 안 상태(§14) | 백엔드 `preview_cells`·썸네일 API·`DoeThumbGrid` 재사용 |
| BS-D-12 | **품질 차단**(§6): 영향 요소(노드 하나라도 ‖u‖ > 1e-9 mm) 중 **새 Fail**(공칭 Pass/Warn → 안 Fail) 비율 > `select.quality.max_fail_ratio`(0.01) 또는 뒤집힘(야코비안 ≤ 0·요소 법선 각 변화 > `select.quality.flip_deg` 60°) → `FAILED_MESH`. 기준값은 `bead_doe.compare.quality` 한 곳(복제 없음) | 사용자 확정 5, 낙하 메시 원래 Fail 은 안 탓이 아님 |
| BS-D-13 | **해석·하중·지지** = ① 그대로(노드 직접 하중, 기준 ESL 3-2-1, 분해 1회/안). 안 형상 = 기저 모핑 좌표(paicad 없음). `done.json.input_sha256` 의 paicad 자리 = 선택 sha + 기저 sha | 확정 2, BD-D-16 이어하기 |
| BS-D-14 | **산출물(순위 1 + 상위 k)**: 모델 rad/include 중 Ch/R 노드를 담은 파일의 사본(원본에서 **`/NODE` 좌표 칸만** 교체, 칸 폭·형식 유지 — `out_files/<rel>` 와 같은 규칙) + `ch_r.rad`·`ch_r.fem`(`export_mesh`) + `values.json` + `selection.json`. BREP/STEP 없음(CAD 없음, 보고서·화면에 명시) | ① BD-D-18 과 같은 받기 형태 |
| BS-D-15 | **paicad 자동 탐지와의 관계**: `select` 는 STEP·extract·tag·run 을 쓰지 않는다. 자동 후보를 출발점으로 가져오지 않음(§12) | 자동 후보는 실제 비드가 아님(확정 1), STEP 불필요 |
| BS-D-16 | **위치 이동 U/V 보류**(Q3): 데이터 모델에 `type` 자리만 둠(`"D"|"W"`, 후속 `"U"|"V"`) | 경로형 비드 이동은 블렌딩 범위가 커서 품질 실패·고정 침범이 많음, 1차 가치 = 깊이·폭 |
| BS-D-17 | **③ 모핑 전환은 별도 계약**(Q2, 권장 v0.16.0 `esl_step_morph.md`): 이 계약의 코어(`bead_select` 기저·모핑·품질)는 **메시 출처와 무관**하게(입력 = base_mesh.npz + 선택 + 고정) 만들어 재사용 가능하게 둔다 | §13 |

## 3. 사용 흐름 (단계별)

1. 라이브러리에서 같은 모델 ESL 체크 → [선택한 ESL로 강성 평가 스터디] → 시나리오 ① + **비드 정의 [직접 선택(메시)]**. 기준 Case·Ch/R 파트·노드/요소 수 표시(① s1-check 재사용). STEP 칸 숨김.
2. [입력 준비](주) → `DOE_PREP`: 기준 메시 읽기·동일성 → (paicad 준비됨) fixed-scan → 하중·지지 → **선택 보기 자료**(`prep/select/`, §8.1).
3. READY → **비드 선택 카드**(3D, §11.2):
   1. [+ 비드] → B1 생성(이름 편집). 대상 층 = "B1 · 단 1 바닥".
   2. 바닥 한 요소 **클릭** → 같은 법선(seed 법선과 각 ≤ feature angle, 기본 15°)·연결 요소로 자동 확장. 모자라면 브러시로 더하고 Alt(빼기)로 지움. 다단이면 [+ 단] → 단 2 바닥을 같은 방식으로.
   3. [사면·경계 자동] → 서버 `derive`: 사면 요소 제안(주황), 경계선(굵은 선), 공칭 D_k·W(최소~최대), 경고(빠진 단·새는 사면·열린 경계·고정 겹침). 사면이 넘치거나 모자라면 [경계 +1줄]/[−1줄] 또는 "사면" 층 브러시로 수정.
   4. 체결부가 비드 근처인데 고정 정보가 없으면(경고 띠) "고정" 층으로 칠함.
   5. 비드마다 반복 → [선택 저장](주) → 서버 재계산·검증 → 저장(rev).
4. **변수 표**(기존 `DoeParamTable` — 행 = B1 D1, B1 D2, B1 W …): 체크·범위(기본 = 추정 범위 §5.7)·단 묶음·블렌딩 반경(비드 행, 자동/숫자). 행을 고르면 평면도에 범위 표시(§7.1). 방식·안 수 → [미리보기](주).
5. `DOE_PREVIEW` → 썸네일 격자(3D 음영 + 높이 변화 색, 같은 범위, 범례 1개): OK / 고정 침범 / 품질 실패 배지. 썸네일 클릭 → 3D 뷰어(그 안 형상·색, 공칭과 전환).
6. [DOE 실행](주) → `DOE_RUN` → 기존 결과 카드(순위·개선율·ESL별 개선율·민감도·3D 비교·받기·보고서).
7. 선택을 고치면 미리보기 무효(배지 "선택 변경됨 — 다시 미리보기"). 실행 후 변경 = 복제(`clone`, 선택 포함 복사).

## 4. 데이터 모델

### 4.1 선택 입력 (`SelectionIn`, API·DB 공통, schema_version 1)

```text
Ranges      = [[first, last], …]          # 요소 ID 정렬·겹침 없음·닫힌 구간, 정수 ≥ 1
ElemSet     = { q: Ranges, t: Ranges }     # q = 4각(/SHELL), t = 3각(/SH3N) — ID 공간이 따로일 수 있음
SelectionIn { schema_version: 1,
              feature_angle_deg: float (1..45, 기본 select.feature_angle_deg) — 기록용(확장은 브라우저),
              beads: [BeadSel] (1..select.max_beads 20),
              fixed_user: ElemSet (기본 빈), exclude: ElemSet (사면 자동에서 빼라고 사용자가 칠한 요소, 기본 빈) }
BeadSel     { id: "b1".."b20" (^b[1-9][0-9]?$, 고유), name: str (1..32, 제어문자 금지, 기본 "B<n>"),
              tiers: [{ k: 1..select.max_tiers(6) (연속), floor: ElemSet (≥ 1 요소) }],
              slope: { mode: "auto" | "edited", add: ElemSet, remove: ElemSet },   # auto 결과에 대한 사용자 편집
              blend_mm: "auto" | float (0 .. select.blend.max_mm),
              floor_follow: 0 | 1 (기본 select.width.floor_follow — Q1),
              links: [[k, k, …]] (같은 깊이 값으로 묶을 단 번호들, 겹침 없음) }
```

- 요소 집합은 서로 겹치지 않아야 한다: 한 요소는 최대 1 개 비드·1 개 층(단 바닥|사면). 겹침 → 422 `SELECT_OVERLAP{bead, elems_n}`. 고정 층·제외 층은 비드 층과 겹칠 수 있음(겹치면 경고).
- 기준 메시에 없는 요소 ID → 422 `SELECT_ELEM_UNKNOWN{n, first}`.

### 4.2 서버 재계산 결과 (`SelectionDerived`, 응답·DB 요약)

```text
BeadDerived { id, name, n_elems, n_nodes,
              tiers: [{ k, n_elems, D_nom (mm, 깊어짐 +), normal: [3], planarity_mm }],
              slope: { n_elems, elems: ElemSet (최종), suggested_n, edited: bool },
              boundary: { loops: [{ closed: bool, n_nodes, length_mm }], n_nodes },
              W_nom, W_min, W_max (mm, §5.7 국부 폭), sense: "concave"|"convex" (상판 법선 기준),
              blend_mm (해석된 값), blend_clipped: bool,
              fixed_in_bead_n, fixed_in_blend_n,
              plan: { ring_ab: [[[a,b]…] 고리별], e_ab: [[[ea,eb]…] 경계 노드별 바깥 단위 방향] },
              section: { s: [mm], z: [mm], dz_dD: {k: [..]}, ds_dW: [..], dz_dW: [..] },   # 단면 미니 그림(§7.1)
              range_default: { D: {k: [lo, hi]}, W: [lo, hi] }, warnings: [{code, …}] }
SelectionDerived { rev, sha256, mesh_sha256, beads: [BeadDerived], fixed: { scan_n, user_n, source: "scan"|"user"|"scan+user"|"none" },
                   warnings: [...] }
```

- `sha256` = 정규화 SelectionIn(구간 병합·정렬·기본값 채움) JSON(정렬 키) 의 sha256. 같은 선택 = 같은 sha(V-BS-9).
- 노드 집합(바닥·사면·경계 노드 ID)은 응답에 넣지 않는다(크기) — 워커가 같은 함수로 다시 만든다(`bead_select.derive` 결정적). 화면 표시용 노드 강조는 브라우저가 요소 집합에서 직접 계산.

### 4.3 DB 필요 여부 — **필요**
- `bead_does.selection` JSONB NULL = `{rev, sha256, input: SelectionIn, derived: SelectionDerived(section·plan 제외 요약), updated_by_name, updated_at}`. section·plan(그림 자료)은 `GET …/selection` 때 서버가 다시 계산(≤ 3 s) 대신 **캐시**: 백엔드 프로세스 메모리 LRU(키 = sha256, `select.derive_cache_n` 8).
- `doe` JSONB 의 `preview` 에 `selection_sha256` 추가(열 아님). 시나리오 CHECK 에 `select`(§15).

## 5. 모핑 알고리즘 (`esl/doe/bead_select.py`, 순수 numpy·scipy)

기호: 노드 좌표 x_i, 요소 e 의 면적 A_e·단위 법선 n_e(요소 연결 순서, 4각 = 대각선 외적), 비드 b 의 집합 F_k(단 k 바닥 요소)·S(사면)·∂(경계 노드 = 비드 요소(∪F_k ∪ S)와 비드 밖 요소가 함께 쓰는 노드). 길이 mm, 각 °.

### 5.1 인접·법선
- 요소 인접 = 모서리(정렬 노드 쌍) 공유. 모서리 키 `min·2^32 + max` 정렬 후 같은 키 묶음(비다양체 T 접합 허용 — 3개 이상 공유도 이웃). CSR(int32).
- 노드 국부 평균 법선(단 k 바닥 노드 i): n_i^k = normalize(Σ_{e∈F_k, ‖c_e − x_i‖ ≤ r_n} A_e n_e), r_n = `select.normal_radius_mm`(10), cKDTree. 방향은 단 평균 법선 n̄_k(= normalize Σ_{F_k} A_e n_e) 과 같은 쪽으로 뒤집음.
- **비드 방향** n̂_b: 상판 기준면(경계 노드 최소자승 평면, 점 p_b·법선 m_b) 에서 단 바닥 무게중심 쪽을 + 로 한 m_b. 깊이 좌표 z(x) = (x − p_b)·n̂_b(바닥 쪽 +). n̄_k·n̂_b < 0 이면 n̄_k 뒤집음(바닥 법선도 "깊어지는 쪽" +). sense = n̂_b 가 부품 판 법선(`view3d.plate_normal`)과 같은 쪽이면 `convex`, 반대면 `concave`(표시용).
- 평면성: 경계 평면 RMS > `select.plane_rms_mm`(2.0) → 경고 `SELECT_NONPLANAR_BASE`(높이 비율 대신 거리 비율 사용 §5.3).

### 5.2 사면 자동 추정·경계 제안 (`derive`)
1. 시작 = 모든 단 바닥 요소 F = ∪F_k 의 바깥 가장자리 이웃.
2. BFS: 이웃 요소 e 가 F·제외·다른 비드가 아니고, **바닥과 평행하지 않으면**(∠(n_e, n̄_b) > θ, θ = feature angle) 사면 후보 S 에 넣고 계속. 평행(≤ θ)이면 멈춤 → 그 요소 = 상판 후보(같은 비드 단이 아님). 측지 거리(요소 중심 경로) > `select.slope_max_mm`(80) 이면 멈추고 경고 `SELECT_SLOPE_LEAK`.
3. 멈춘 평행 요소의 z 가 |z| ≤ `select.plate_tol_mm`(1.0) → 상판(정상). 0 < z < min D_k − tol(상판과 바닥 사이 높이의 평행 영역) → 경고 `SELECT_TIER_MISSING{z_mm, n_elems}`("고르지 않은 단이 있습니다").
4. 사용자 편집 적용: S ← (S_auto ∪ slope.add) ∖ slope.remove ∖ exclude. `mode: "edited"` 이어도 자동 결과를 다시 계산해 편집을 얹는다(결정적).
5. 경계 ∂ = 비드 요소와 비드 밖 요소가 함께 쓰는 노드. 경계 모서리(비드 요소 1 + 밖 요소 1)를 이어 고리로 정렬(시작 = 최소 노드 ID, 방향 = n̂_b 기준 반시계). 부품 자유 모서리에 닿으면 열린 고리 → 경고 `SELECT_OPEN_BOUNDARY`(그 비드 W 변수 비활성, D 는 가능).
6. ±1줄: [경계 +1줄] = 현재 비드 밖 요소 중 경계 노드를 쓰는 요소를 사면 add 로, [−1줄] = 사면 중 경계 노드를 쓰는 요소를 remove 로(브라우저가 계산 → derive 재호출).
7. 비드 요소 집합이 연결 아님 → 경고 `SELECT_DISCONNECTED{parts}`(허용 — 한 비드가 둘로 나뉜 선택일 수 있음).

### 5.3 깊이 기저 B_{D_k}
- 단 k 바닥 노드 i: B_{D_k}[i] = n_i^k(단위 Δd 당 변위).
- 경계 노드: 0(고정). 다른 단 바닥 노드: 0.
- 사면 노드 x: **앵커 수준** = {0: 경계, k: 단 k 바닥 노드}. 사면 + 앵커 노드 위 모서리 그래프(가중 = 모서리 길이)에서 수준마다 다중 출발 최단거리 g_ℓ(x)(`scipy.sparse.csgraph.dijkstra(min_only=True)`). 가까운 서로 다른 두 수준 a·b(g 오름차순, a 의 z_a < z_b 가 되도록 정렬; z_0 = 0, z_k = D_k).
  - 높이 비율 s = clip((z(x) − z_a)/(z_b − z_a), 0, 1). |z_b − z_a| < `select.level_eps_mm`(0.5) 또는 `SELECT_NONPLANAR_BASE` → 거리 비율 s = g_a/(g_a + g_b).
  - B_{D_k}[x] = (1 − s)·[a = k]·n^k(x) + s·[b = k]·n^k(x), n^k(x) = x 에 가장 가까운 단 k 바닥 노드의 n_i^k.
  - 예: 1단 비드 사면 = 경계(0)와 바닥(1) 사이 → B_{D_1} = s·n — 사면이 높이에 비례해 늘어남(사용자 확정 4). 나란한 두 단 사이 경사로 = 단1·단2 사이 보간.
- 묶음(`links`): 묶인 단들의 기저 합 = 변수 1개 기저.

### 5.4 폭 기저 B_W (닫힌 경계만)
- 경계 노드 j 의 바깥 방향 ê_j: 고리 접선 t_j = normalize(x_{j+1} − x_{j−1}), 상판 국부 법선 m_j(경계 노드에 붙은 비드 밖 요소 면적 가중), ê_j = normalize(t_j × m_j), 비드 무게중심 반대쪽이 되게 부호. 양 끝 120° 이상 꺾인 모서리는 이웃 2개 평균(구석 연속).
- 경계 변위장 w(x) = ½·Σ_j ω_j ê_j / Σ_j ω_j, ω_j = exp(−(d_j/σ)²), d_j = ‖x − x_j‖, j = x 에서 가까운 경계 노드 `select.width.knn`(8)개, σ = 경계 노드 간격 중앙값 × 2. (ΔW 당 한쪽 ½ 이동, 가중 평균으로 구석·간격 불균일에서도 매끈.)
- 경계 노드: B_W[j] = ½ ê_j.
- 사면 노드 x: B_W[x] = (1 − s')·w(x) + s'·f·w(x) = (1 − s'(1 − f))·w(x) — s' = §5.3 의 x 의 경계↔가장 가까운 바닥 수준 비율, f = `floor_follow`. f = 1 → 사면이 통째로 평행 이동(각 유지), f = 0 → 바닥 쪽으로 갈수록 0.
- 바닥 노드: f = 0 → 0. f = 1 → 바닥 가장자리 노드(사면 요소와 공유) = w(x) 를 디리클레로 두고 바닥 내부는 **조화 확장**(그래프 라플라시안 L u = 0, 모서리 가중 1/길이, 성분별 `scipy.sparse.linalg.splu` 1회) — 경로형 바닥이 양쪽 가장자리 사이에서 선형으로 늘어남.
- 모든 B_W 는 노드 국부 접평면으로 사영(u ← u − (u·ν_i)ν_i, ν_i = 기준 노드 법선 `view3d.node_geometry`) — 폭 변수는 면외로 판을 휘게 하지 않는다.

### 5.5 블렌딩 (폭 변수만 — 깊이는 경계 고정이라 불필요)
- 비드 밖 노드 x(상판), 경계까지 평면 거리 d(x) = 가장 가까운 경계 노드 거리(cKDTree), R = 블렌딩 반경:
  B_W[x] = β(d/R)·w(x)(접평면 사영), β(t) = (1 − t)⁴(4t + 1)(t < 1), 0(t ≥ 1) — Wendland C², β(0) = 1, β'(0) = 0 → 경계에서 변위·기울기 연속.
- 영향 노드 = d < R 인 노드 + 비드 노드. 다른 비드의 블렌딩·비드 영역과 겹치면 선형 합(경고 `SELECT_BLEND_OVERLAP{with}`).

### 5.6 블렌딩 반경 자동·고정 노드
- `blend_mm: auto` → R = max(`select.blend.min_mm`(15), `select.blend.k`(8) × max(|W_hi − W_nom|, |W_lo − W_nom|)/2, 3 × h_med) — 범위는 변수 표 기본 범위(§5.7) 기준(사용자가 범위를 넓혀도 R 은 저장된 선택 값 — 바꾸려면 숫자 입력; 표에 "R 이 범위에 비해 작음" 배지: R < k × 최대 한쪽 이동).
- 고정 노드 앞 자르기: d_f = 경계에서 가장 가까운 고정 노드(비드 밖)까지 평면 거리. R_auto > d_f − `select.blend.fixed_margin_mm`(3) 이면 R = max(min_mm 의 ½, d_f − margin), `blend_clipped: true` + 경고 `SELECT_BLEND_CLIPPED`. 그래도 고정 노드가 R 안 → 경고 `SELECT_FIXED_IN_BLEND{n}`(그 비드 W ≠ 공칭 안은 BS-D-10 으로 스킵됨).
- 비드 요소(바닥·사면·경계) 노드에 고정 노드 → 경고 `SELECT_FIXED_IN_BEAD{n, tiers}` + 그 비드 변수 기본 체크 해제(D_k 는 해당 단·사면만, W 는 전부).

### 5.7 공칭 치수·기본 범위
- D_nom,k = 단 k 바닥 노드 z 의 중앙값. planarity = 바닥 노드 z 의 (p95 − p5).
- 국부 폭: 경계 노드 j 에서 −ê_j 방향(평면 m_b 투영) 반직선이 맞은편 경계 고리 선분과 처음 만나는 거리 w_j(2D 선분 교차, 경계 노드 ≤ 수천 — O(n²) 블록). 끝단(맞은편이 같은 끝단)·교차 없음 제외. W_nom = median w_j, W_min·W_max = p5·p95.
- 기본 범위(추정, `source: estimate`): D_k ∈ [D_nom·(1 − r), D_nom·(1 + r)], r = `select.range.depth_rel`(0.3), 하한 > 위 수준 깊이 + `select.range.min_step_mm`(1)(단이 위 단·상판을 넘지 않게). W ∈ [W_nom·(1 − `width_rel` 0.2), W_nom·(1 + 0.2)], f = 1 이면 하한 ≥ 바닥 최소 폭 > 0 이 되게(가장자리 간 거리 − ΔW > h_med). 사용자 범위는 BD-D-7 처럼 경고만(D·W > 0 은 422).

### 5.8 성능·메모리 목표 (22만 노드·22만 요소, 비드 ≤ 20·단 ≤ 6)

| 단계 | 위치 | 목표 |
|---|---|---|
| 선택 보기 자료(GLB·select.bin) | 워커 BD_LOADS | ≤ 10 s, ≤ 1 GB |
| `derive`(인접 구성 + 사면 BFS + 경계 + 폭·단면) | 백엔드 동기 | p95 ≤ 3 s, 피크 ≤ 1.5 GB(인접 CSR int32 ≈ 15 MB, 좌표 5 MB) — 인접은 메시 sha 키로 프로세스 캐시 |
| 기저 B_v 전부 | 워커 BD_MATRIX | ≤ 30 s, ≤ 2 GB. 저장 = 영향 노드 인덱스(int32) + float32 3열, 변수당 ≤ 영향 노드 × 16 B |
| 안 1개 모핑 | 워커·브라우저 | ≤ 50 ms(희소 합) |
| 안 1개 품질(영향 요소만) | 워커 | ≤ 0.5 s |
| 썸네일 1장(640×480 내부 → 320×240) | 워커 | ≤ 1 s |
| 미리보기 200안 | 워커 | ≤ 5 분(병렬 없음, 결정적) |
| 브라우저 확장(BFS) | TS | ≤ 100 ms, 브러시 1획 프레임 ≤ 16 ms(ID 버퍼 부분 읽기) |

## 6. 품질 판정 (`esl/doe/mesh_quality.py` 에 함수 **추가만** — v0.14.0 함수 불변)

- `affected_quality(base_mesh, x_design, elem_mask, qcfg, *, flip_deg) -> dict`: 영향 요소(elem_mask)만 `element_metrics` 를 공칭·안 둘 다 계산 → 기준별 Fail 판정(`CRITERIA`, `bead_doe.compare.quality` 값) → `{n_affected, new_fail, new_fail_ratio, fail_by{기준: 수}, inverted, max_flip_deg, worst{기준: 값}, over_limit}`.
- 새 Fail = 공칭에서 그 요소가 Fail 아님 ∧ 안에서 Fail. 뒤집힘 = 안 야코비안 ≤ 0(4각) 또는 ∠(n_e^안, n_e^공칭) > `flip_deg`.
- 판정: inverted > 0 → `FAILED_MESH`(`SELECT_MORPH_INVERTED`), new_fail_ratio > `select.quality.max_fail_ratio` → `FAILED_MESH`(`SELECT_QUALITY_FAIL`). tria % 기준은 위상 불변이라 계산 안 함.
- 결과는 미리보기 셀·`result.json.mesh.quality` 에 기록, 보고서 안 표에 "새 Fail 수/영향 요소".

## 7. 가시화

### 7.1 평면도 (`DoePlanOut` select 판 + 프런트 `BoundaryPlan` 재사용)
- 자료(`GET …/plan-view`, select): 기존 형식(frame·outline·holes·elems) + `beads[{id, name, ring_ab, e_ab, label_ab, tiers[{k, ring_ab}]}]`, `fixed[{a, b}]`(고정 노드 점), `nodes_ab`(노드 점 — 표시 토글, 기본 숨김), 비드별 `section`.
- 표시: 노드 점 [숨김 ☑](기본 숨김), 고른 비드 = 진하게(단마다 명도 차), 나머지 요소 = 흐리게(불투명 0.25), **라벨 칩** "B1 · D1 22.0 · D2 14.5 · W 60.2"(비드 중심 근처, 겹치면 밀어냄).
- 변수 행 선택 시 범위:
  - **폭 W**: 최소·최대 윤곽 점선 = ring_ab + e_ab × (W_lo − W_nom)/2, (W_hi − W_nom)/2(브라우저 계산 — 표의 현재 범위 즉시 반영). 공칭 = 실선.
  - **깊이 D_k**: 평면도 옆 **단면 미니 그림**(SVG 240×120): 실제 단면 = 공칭 폭 중앙값 위치의 경계 노드에서 −ê 방향 평면(ê, n̂_b)과 메시의 교선(요소-평면 교차 폴리라인, 서버 `section`), 공칭 실선 + lo·hi 점선(z + (D − D_nom)·dz_dD[k], 브라우저 계산), 치수 글자 "22.0 (15.4–28.6)". 단면 위치는 평면도에 짧은 선으로 표시.

### 7.2 미리보기 썸네일 (워커 `esl/doe/select_render.py`, paicad 비의존)
- 입력: 기준 메시(삼각화 `view3d.triangulate`), 안 좌표, 색 값 c_i = (x_d,i − x0,i)·ν_i^b(비드 방향 성분: 비드 노드·블렌딩 노드는 그 비드 n̂_b 기준 깊어짐 +, 그 밖 0).
- 시점: `select.thumb.view` `auto` = 선택 비드 전체(+ 블렌딩) bbox 를 비드 평균 n̂ 반대쪽(깊어짐을 보는 쪽)에서 −η 로 `tilt_deg`(25°) 기울인 직교 투영, 여백 1.15. 모든 칸 **같은 시점·같은 축척**(공칭 bbox 기준).
- 래스터: 2배 내부 해상도(640×480) — `png.rasterize` 방식에 **깊이 버퍼** 추가(픽셀 중심 무게중심 보간 z, 가까운 것 유지, 동률 = 작은 삼각형 번호), 요소 법선 램버트(광원 = 시선 + 위 20°, 주변광 0.35) × 색, 2×2 평균 축소 → `encode_png`(결정적 바이트).
- 색: 발산 색(파랑 = 깊어짐 +, 흰 = 0, 빨강 = 얕아짐 −, 회색 음영 = 영향 없음), **모든 칸 같은 범위** ±V, V = max over READY 안 |c| (0 이면 1 mm), 격자 위 범례 1개(`grid_manifest.color{v_max, unit}`). 안 경계선(현재 위치) 진회색 1 px.
- 공칭 칸 `nominal` = 같은 시점 회색 음영(색 0).

### 7.3 3D 보기 (썸네일 클릭)
- 브라우저: 선택 보기 GLB(공칭) + `GET …/select/basis` (기저: 변수별 영향 노드 인덱스 + float32 변위) + 안 값(행렬) → u = Σ (v − v_nom)·B_v → 기존 `setDeform(u, 1)`·`setColors(c, −V, V)`(같은 발산 색표 — `colors.ts` 에 추가). [공칭 ↔ 안] 전환, 크게 보기(배율 1·2·5 — 표시만). 워커 계산과 같은 식이라 float32 오차(≤ 1e-4 mm) 외 동일(V-BS-12).

## 8. 파이프라인 · 작업 (job_types 변경 없음, step 내부 `select` 분기)

### 8.1 DOE_PREP
```
1 BD_INPUT   ① 와 같음(same_base: Case rad 제자리 읽기·동일성·누적 경고) → prep/base_mesh.npz, prep/input.json(STEP 없음)
2 BD_MESH0   SKIPPED
3 BD_GEOM    paicad 준비됨: assem_full 사본 → fixed-scan(Ch/R 파트) → prep/fixed/  (extract·tag 없음)
             paicad 없음·실패: SKIPPED + 경고 FIXED_INFO_MISSING (준비는 성공)
4 BD_LOADS   ① 와 같음(frame·3-2-1·노드 하중 prep/loads.npz) + 선택 보기 자료 prep/select/:
             part.glb(view3d.write_glb, _NODE_ID), select.bin(삼각형→요소 index uint32, elem_id·type, 노드 고정 마스크 uint8),
             select_manifest.json{schema "esl/bead_select_view/1", n_nodes, n_elems, n_tris, mesh_sha256, h_med, plate_normal, fixed{scan_n}}
5 BD_PREP_REGISTER  prep 요약 {n_nodes, n_elems, fixed{source, n}, warnings}
```
### 8.2 DOE_PREVIEW
```
1 BD_MATRIX  행렬(같은 함수) + 선택 rev 확인 → select/<sel_sha12>/{derived.npz(노드 집합·경계), basis.npz(변수별 idx·vec), basis.json(sha·변수·R)}
             (같은 sha 폴더가 있으면 재사용)
2 BD_GRID    (LOCAL, 코어 하위 프로세스 bd_select_grid) 안마다 모핑 → 고정 판정 → 품질 → 썸네일 → doe/<rev>/grid/{grid_manifest.json, cells/<id>/thumb.png}
3 BD_PREVIEW_REGISTER  셀 상태 요약 + doe.preview.selection_sha256
```
### 8.3 DOE_RUN
- BD_BASELINE = ① d000. BD_DESIGNS(LOCAL 단계 없음 — 코어 `bd_eval` 만, 스레드 풀 `run.parallel`): x_d = 기저 모핑(같은 basis.npz) → ① 하중·지지 → 해석. 품질·고정은 미리보기 결과를 다시 확인(같은 함수, 다르면 내부 오류).
- BD_POST = ① 그대로 + 산출물 BS-D-14(rad 사본은 `prep/assem_full` 매니페스트(있으면)·없으면 Case include 트리에서 Ch/R `/NODE` 블록을 가진 파일만 → `nodes.write_morphed`), `best/<did>/selection.json`. 정리(BD-D-17)는 대상 없음(paicad 폴더 없음).
### 8.4 검증 낙하
- `select` 최적 안은 ① 과 같은 형태(원 ID·/NODE 좌표만 바뀐 include)라 기존 검증 낙하(VD)가 `same` 과 같이 동작하도록 VD 의 시나리오 허용 목록에 `select` 추가(`verify*.py` 판정 1줄 — 파일 소스만 `best/<did>/` 로 같음).

## 9. API (`/esl/api`, 기존 오류 형식, 비GET `X-ESL-Request: 1`)

| 메서드·경로 | 요청 | 응답 | 오류 |
|---|---|---|---|
| `POST /doe/check-inputs`·`POST /doe/studies` (select) | `{project_id, scenario:"select", entry_ids, title?}` — `step_upload_id`·`mesh_upload_id`·`part_title`·`shapes` 금지 | ① 과 같음(`base`, step 없음) | ① 과 같음 + 503 `SELECT_DISABLED` |
| `GET /doe/studies/{id}/select/view/{file}` | file ∈ part.glb·select.bin·select_manifest.json | 바이너리/JSON(기존 view3d 파일 API 규칙, ETag = mesh_sha256) | 409 `PREP_NOT_READY`, 404 |
| `POST /doe/studies/{id}/select/derive` | `{selection: SelectionIn, bead?: id}`(bead 주면 그 비드만) | `SelectionDerived`(저장 안 함, rev 없음) + `slope_suggested: {bead: ElemSet}` | 422 `SELECT_*`(§14), 413 `SELECT_TOO_LARGE`, 409 `PREP_NOT_READY` |
| `GET /doe/studies/{id}/selection` | – | `{rev, sha256, input, derived, updated_by_name, updated_at}` 또는 `null` | 409 `PREP_NOT_READY` |
| `PUT /doe/studies/{id}/selection` | `{version, selection: SelectionIn}` | `DoeStudyOut`(version+1, selection 요약) | 위 + 409 `VERSION_CONFLICT`·`JOB_ACTIVE`·`ALREADY_RUN`, 403(power 미만) |
| `GET /doe/studies/{id}/params` (select) | – | `DoeParamsOut`: `beads[{id, name, kind:"select", n_tiers, W_nom, W_min, W_max, blend_mm, warnings}]`, `params[{name:"B1_D1"…"B1_W", type:"D"|"W", bead, tier?, nominal, feasible:[lo,hi], feasible_source:"estimate", default_range, use_default, group_members(links)}]` | 409 `SELECTION_MISSING` |
| `GET /doe/studies/{id}/plan-view` (select) | – | §7.1 | 409 `SELECTION_MISSING` |
| `POST …/matrix`·`…/preview` (select) | 기존 | 기존 + preview 응답 `doe.preview.selection_sha256` | + 409 `SELECTION_MISSING` |
| `GET /doe/studies/{id}/select/basis?rev=` | – | `basis.bin`(변수 순서 = basis.json: 각 변수 [n:u32][idx:u32×n][vec:f32×3n]) + 헤더 `X-ESL-Basis-Sha` / `?meta=1` → basis.json | 409 `PREVIEW_NOT_READY`, 404 |
| `POST …/run` (select) | `{version, matrix_sha256, solver?}` | 기존 | + 409 `PREVIEW_STALE`(matrix 또는 selection sha 불일치) |
| `POST …/clone` (select) | `{title?}` | 새 스터디 + 선택 복사(rev 1, 같은 sha — 메시 sha 같을 때만, 다르면 선택 없이 + 경고 `SELECTION_DROPPED`) | – |

- 변수 이름 `<bead id 대문자>_D<k>`·`_W`(예 `B1_D2`) — `matrix` 의 이름 규칙·값 파일과 같음. 묶음은 대표 = 가장 작은 k(`B1_D1` 이 D1·D2 를 함께 바꿈, `group_members`).
- `SelectionIn` 이름·사용자 문자열은 DB·응답·보고서(HTML 이스케이프)에만, 경로·argv 에 넣지 않음.
- `GET /doe/settings` += `scenarios.select`, `select:{enabled, reason, feature_angle_deg, max_beads, max_tiers, blend:{min_mm, max_mm}}`.

## 10. 설정 키 (`config/*.example.yaml`, 하드코딩 금지 — `esl/doe/__init__.DEFAULTS["select"]` 거울)

```yaml
bead_doe:
  select:
    enabled: true
    feature_angle_deg: 15.0     # 브라우저 확장·사면 BFS 평행 판정 기본
    max_beads: 20
    max_tiers: 6
    max_selection_kb: 4096
    normal_radius_mm: 10.0
    plane_rms_mm: 2.0
    plate_tol_mm: 1.0
    level_eps_mm: 0.5
    slope_max_mm: 80.0
    fixed_tol_mm: 0.01
    width: {floor_follow: 1, knn: 8}          # Q1
    blend: {min_mm: 15.0, max_mm: 200.0, k: 8.0, fixed_margin_mm: 3.0}
    range: {depth_rel: 0.3, width_rel: 0.2, min_step_mm: 1.0}
    quality: {max_fail_ratio: 0.01, flip_deg: 60.0}   # 기준값 = bead_doe.compare.quality(한 곳)
    thumb: {w: 320, h: 240, supersample: 2, view: auto, tilt_deg: 25.0, margin: 1.15, ambient: 0.35}
    derive_cache_n: 8
    derive_timeout_s: 20
```
- `BeadDoeSelectCfg`(pydantic) 범위 검사(feature_angle 1..45, max_tiers 1..9, floor_follow ∈ {0,1}, 0 < min_mm ≤ max_mm). 섹션 없으면 기본값.

## 11. 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음, 필수만, 화면당 주 버튼 1개)

### 11.1 배치
```
강성 평가 스터디 · 75형 Ch/R  [● ① 같은 모델 (비드: ○자동 탐지 ●직접 선택) ○② ○③ ○④]       [입력 준비 | 선택 저장 | 미리보기 | DOE 실행](주)
┌① 입력 ESL (3) … 기준 Case·Ch/R 22.1만 노드 ✓  고정: fixed-scan 412 노드 ✓ ──────────────────────────────────────┐
┌② 비드 선택 (준비 후) ─────────────────────────────────────────────────┐┌③ 비드 목록·도구 ─────────────────┐
│ [클릭+확장][브러시 ○20px][사각][올가미]  층[B1·단1 바닥 ▼]  ☑보이는 면만 ││ B1 "좌 경로 비드" ⚠1             │
│ feature [15°]  [사면·경계 자동] [경계 +1줄][−1줄]  [노드 점 숨김☑] ↶ ↷  ││  단1 바닥 1,284 · D 22.0          │
│ ┌───────────────────── 3D (TrackballControls) ────────────────────┐ ││  단2 바닥 402 · D 14.6  [묶기]    │
│ │  선택 = 단 색(파랑 계열) · 사면 주황 · 경계 굵은 선 · 고정 회색 빗금 │ ││  사면 2,010(자동+편집) · W 60.2  │
│ └──────────────────────────────────────────────────────────────────┘ ││  (52.1–71.8) 블렌딩 auto 24 mm    │
│ Shift = 더하기 · Alt = 빼기 · 더블클릭 = 중심                           ││ [+ 비드] [+ 단] [고정 칠하기]     │
└───────────────────────────────────────────────────────────────────────┘└──────────────────────────────────┘
┌④ 변수 (DoeParamTable) ┐┌⑤ 평면도 + 단면 미니 그림 (§7.1) ┐   ┌⑥ 미리보기 격자 (3D 썸네일·범례 1개) ┐  ┌⑦ 결과 (기존) ┐
```
- 2560: ②(1640 폭, 3D 1600×860) + ③(820). ④⑤ 나란히, ⑥ 8열. 1920: ②(1240, 3D 1200×640) + ③(600, 비드 목록은 접힘 카드), ④⑤ 위아래, ⑥ 6열. 도구 줄은 1920 에서 두 줄로 접힘(가로 스크롤 없음).
- 주 버튼: READY 에서 선택 미저장·변경 있음 → [선택 저장], 저장됨 → [미리보기]. 이후 기존 규칙.
- 사용자 경고 띠: `FIXED_INFO_MISSING`, `SELECT_FIXED_IN_*`(비드 목록 ⚠ 배지 툴팁).

### 11.2 3D 선택 구현 (`frontend/src/view3d/` 확장, 하중 보기 동작 불변)
- `sceneApi` 추가(선택 모드 전용, 기존 메서드 불변): `setElemColors(rgba: Uint8Array /* 요소별 */)`, `pickElem(ev) → elem index | -1`(Raycaster `faceIndex` → `tri2elem`), `idBuffer(rect) → Uint32Array`(요소 번호를 24비트 색으로 그린 오프스크린 렌더 — 보이는 면만 선택), `projectCentroids() → Float32Array`(보이는 면만 끔 = 관통 선택), `setOverlayLines(segs)`(경계선), 브러시·사각·올가미 오버레이는 DOM 캔버스(장면 밖).
- 순수 모듈 `select/`: `adjacency.ts`(요소 모서리 CSR — §5.1 같은 규칙), `grow.ts`(seed 법선 기준 BFS, θ), `lasso.ts`(점-다각형), `ranges.ts`(구간 압축·병합 — 서버와 같은 정규화), `history.ts`(실행 취소 50단계), `layers.ts`(층 = 단 k 바닥|사면 add/remove|고정|제외, 한 요소 한 비드 층 규칙).
- 요소 색: 비선택 = 회색 램버트, 단 k = 파랑 계열 명도 단계, 사면 = 주황, 고정 = 회색 빗금 대신 진회색, 비활성 비드 = 흐리게. 경계선 = 검정 2 px(`LineMaterial`).

## 12. 기존 자동 탐지(paicad)와의 관계
- `select` 는 paicad `shell extract/tag/run/update/view grid` 를 **쓰지 않는다**(BS-D-15). paicad 는 준비돼 있을 때 `fixed-scan` 에만(고정 노드, ① 과 같은 결과).
- **자동 후보를 출발점으로 쓰지 않음 — 권장 이유**: (1) extract 는 STEP 필요(B 는 메시만), (2) 인식 대상(평면 base 1단 4면)이 실제 비드와 달라 후보가 오히려 잘못된 출발점(확정 1: 3.2 mm·12 mm 보조 형상), (3) paicad tag 노드 매핑을 가져오려면 tag 단계 비용(대형 씬 수십 분)이 듦. 대신 브라우저 **클릭 + feature angle 확장**이 실제 비드 바닥 하나를 한 번에 잡는다.
- `same`(자동 탐지) 시나리오는 그대로 유지(평면 1단 비드가 많은 다른 모델용). 같은 기준 Case 로 두 스터디를 만들어 비교 가능.

## 13. ③ STEP 스터디 재메싱 → 모핑 전환 — **별도 계약 권장(Q2)**
- 이유: (1) ③ 의 변수는 paicad 가 STEP 에서 인식한 비드(D·U·V·W)라 형상 변화 → 메시 변위 대응에 paicad tag/morph(또는 새 CAD↔메시 사상)가 필요 — 이 계약의 "사용자 선택 + 규칙 모핑" 과 엔진 입력이 다름. (2) "품질 실패 안만 재메싱" 은 안별 BREP(paicad update)·gmsh·잡음 바닥(§7.2) 정책을 다시 정해야 함. (3) v0.14.0 ④ 가 같은 gmsh 경로를 바꾸는 중 — 한 번에 세 갈래를 고치면 회귀 범위가 큼.
- 이 계약이 남기는 연결점: `bead_select` 의 `derive`·`basis`·`affected_quality`·`select_render` 는 **입력 = (base_mesh.npz, 선택, 고정 노드)** 만 받는다(① Case 경로 의존 없음). 따라서 후속에서 (a) "③ + 직접 선택" = ③ 베이스라인 gmsh 메시 1회 → 이 엔진 → 하중 매핑 1회(ID 불변이라 ② BD-D-3 처럼 매핑 잡음 0), (b) "③ paicad 변수 모핑" = paicad morph(① 과 같은 `shell run`)을 gmsh 메시에 적용 + 품질 실패 안만 재메싱 — 둘 중 하나(또는 둘 다)를 별도 계약에서 고른다.

## 14. 오류·경고 코드 (신규, 사용자 문구 원본 `resources/doe_messages.json`)

| 코드 | HTTP/작업 | 의미 |
|---|---|---|
| `SELECT_DISABLED` | 503 | `bead_doe.select.enabled` false |
| `SELECTION_MISSING` | 409 | 선택 저장 전 params·plan-view·matrix·preview |
| `SELECT_OVERLAP`·`SELECT_ELEM_UNKNOWN`·`SELECT_EMPTY_TIER`·`SELECT_TIERS_GAP`·`SELECT_LINK_INVALID`·`SELECT_BEAD_ID_INVALID`·`SELECT_NAME_INVALID` | 422 | §4.1 검증(빈 단·단 번호 건너뜀·묶음 겹침·id/이름 규칙) |
| `SELECT_TOO_LARGE` | 413 | 정규화 JSON > `max_selection_kb` |
| `SELECT_DERIVE_TIMEOUT` | 503 | derive > `derive_timeout_s` |
| `PREVIEW_NOT_READY` | 409 | 기저 없음(미리보기 전) |
| 경고 `FIXED_INFO_MISSING` | 준비 | paicad 없음·fixed-scan 실패(BS-D-8) |
| 경고 `SELECT_SLOPE_LEAK`·`SELECT_TIER_MISSING`·`SELECT_OPEN_BOUNDARY`·`SELECT_DISCONNECTED`·`SELECT_NONPLANAR_BASE`·`SELECT_BLEND_OVERLAP`·`SELECT_BLEND_CLIPPED`·`SELECT_FIXED_IN_BEAD`·`SELECT_FIXED_IN_BLEND`·`SELECTION_DROPPED` | derive·저장·clone | §5 |
| 셀/안 `SELECT_FIXED_VIOLATION` | → `SKIPPED_FIXED` | BS-D-10 |
| 셀/안 `SELECT_QUALITY_FAIL`·`SELECT_MORPH_INVERTED` | → `FAILED_MESH` | §6 |
| 재사용 | | `MODEL_MISMATCH`·`ENTRY_NOT_FOUND`·`PREREQUISITE_MISSING`·`ASSEM_TOO_LARGE`·`PREP_NOT_READY`·`PREVIEW_STALE`·`ALREADY_RUN`·`VERSION_CONFLICT`·`JOB_ACTIVE`·`DOE_*`·`BASELINE_FAILED`·`NO_FEASIBLE_DESIGNS`·`SUPPORT_DEGENERATE` |

- `paicad_io.cell_state` 확장: 코드가 `SELECT_*` 면 위 표 상태 그대로(FAIL → `FAILED_MESH` 허용). 미리보기 요약 `skipped` += `mesh`(FAILED_MESH 수), 실행 대상 = READY 만(BD-D-9 그대로).

## 15. DB · 버전
- **migration `0015_bead_select`**(`down_revision "0014"` — v0.14.0 병합 후 HEAD 뒤, BD-D-21 규칙): `ck_bead_does_scenario` DROP IF EXISTS 후 `IN ('same','mesh','step','compare','select')`; `bead_does.selection` JSONB NULL(ADD COLUMN IF NOT EXISTS); CHECK `scenario = 'select' OR selection IS NULL`. 열 길이 변경 없음(0014 의 String(8)). 멱등, downgrade 미지원, 이전 migration 은 시점 고정 상수 유지. `tables.py` `DOE_SCENARIOS` 에 `select`, 열 추가.
- 판단 근거: CHECK 가 `select` 를 막음 + 선택은 사용자 편집 상태(rev·낙관적 잠금 `version` 재사용)라 DB 가 원본.
- `VERSION`·`CHANGELOG.md` 0.15.0.

## 16. 시험 (V-BS-*)

합성 시험 메시 생성기 `tests/doe/synth_bead.py`(순수 numpy, 시험 중 생성, 정답 표지 포함): 600×400 판 3 mm 4각(+ 3각 일부), **경로형 2단 비드**(꺾인 경로 3 구간, 폭 50 → 70 mm 선형 가변, 단1 깊이 22·단2 깊이 14(경로 일부 구간만 — 나란한 단), 사면 각 60°, 상·하 필렛 r 3), 1단 원형 비드 1개(D 6·W 40), 구멍 4·RBE2 고정 노드 고리 4(하나는 비드 경계에서 18 mm), 요소별 정답 표지(단 k·사면·상판). 22만 노드 판(`scale=big`)은 성능 시험만.

| ID | 시험 | 위치 |
|---|---|---|
| V-BS-1 | **깊이 정확도**: D1 +3 / −3 mm 후 단1 바닥 노드 z 증가 = Δ ± 1e-9(평면 바닥), 단2·상판 노드 불변(바이트), 사면 노드 z 변화 = s·Δ(정답 s 와 1e-9), 경계 노드 바이트 불변, 사면 각 변화가 식과 일치 | `tests/doe/test_bead_select_morph.py` |
| V-BS-2 | **폭 정확도**: W ±6 mm, f=1 → 모든 국부 폭 w_j 변화 = ΔW ± 0.02 h(경로 가변 폭 유지), 사면 각 불변 ±0.1°, 바닥 폭 +ΔW 선형 늘어남; f=0 → 바닥 노드 불변·사면 각 변화 식 일치; 끝단 이동 = ΔW/2; 면외 성분 ≤ 1e-9 | 같은 파일 |
| V-BS-3 | **블렌딩·연속**: d ≥ R 노드 바이트 불변, 이웃 노드 변위 차 ≤ (ΔW/2)·(h/R)·c, β 연속(경계 안·밖 첫 줄 차), 두 비드 블렌딩 겹침 = 선형 합(개별 합과 1e-12) | 같은 파일 |
| V-BS-4 | **고정 노드**: 모든 안에서 고정 노드 좌표 바이트 불변 또는 그 안 `SKIPPED_FIXED`(침범 = 18 mm 고정 고리 + R 24 → 스킵, R 자동 자르기 → `SELECT_BLEND_CLIPPED` 후 통과), `SELECT_FIXED_IN_BEAD` 기본 체크 해제 | `tests/doe/test_bead_select_morph.py` |
| V-BS-5 | **사면·경계 자동**: 바닥 정답만 넣고 derive → 사면 = 정답 사면(요소 집합 동일), 경계 고리 = 정답(닫힘·순서·시작 노드), 단2 빼고 넣으면 `SELECT_TIER_MISSING`, 상판 휜 판에서 `SELECT_SLOPE_LEAK`, 판 가장자리 비드 `SELECT_OPEN_BOUNDARY`, ±1줄 편집 결과 | `tests/doe/test_bead_select_derive.py` |
| V-BS-6 | **공칭 치수**: D_nom = 22·14 ± 0.05, W_nom·min·max = 정답(50·70 경로) ± h/2, 원형 비드 W = 40 ± h/2, 단면 폴리라인 = 해석적 단면 ± 0.1 mm, dz_dD·ds_dW 가 기저와 일치 | 같은 파일 |
| V-BS-7 | **품질**: 정상 범위 안 새 Fail 0 → READY, W −40 %(사면 겹침) → `SELECT_MORPH_INVERTED`, 블렌딩 R 아주 작게 → 새 Fail 비율 > 0.01 → `SELECT_QUALITY_FAIL`, 공칭에서 이미 Fail 인 요소는 세지 않음, `bead_doe.compare.quality` 값 변경이 그대로 반영(복제 없음), v0.14.0 `summarize` 결과 불변 | `tests/doe/test_mesh_quality.py`(추가) |
| V-BS-8 | **선형성·결정성**: x_d = x0 + Σ(v−v_nom)B_v 가 변수별 단독 모핑 합과 1e-12, 같은 선택 2회 → basis.npz·썸네일 PNG 바이트 동일, 행 순서·구간 표기 바꿔도 sha 동일 | `tests/doe/test_bead_select_morph.py`, `test_select_render.py` |
| V-BS-9 | **선택 검증**: 겹침·없는 요소·빈 단·단 번호 건너뜀·묶음 겹침·id/이름 규칙·크기 상한 → 422/413, 구간 정규화(인접 병합) | `tests/doe/test_bead_select_derive.py`, `backend/tests/test_doe_select_api.py` |
| V-BS-10 | **렌더**: 썸네일 크기·결정적 바이트, 색 부호(깊어짐 = 파랑 채널 우세), 모든 칸 같은 V(manifest), 같은 시점(공칭 bbox), 공칭 칸 회색 | `tests/doe/test_select_render.py` |
| V-BS-11 | **성능(slow 표지)**: 22만 노드 합성 — derive ≤ 3 s·≤ 1.5 GB, 기저 ≤ 30 s·≤ 2 GB, 안 모핑 ≤ 50 ms, 품질 ≤ 0.5 s, 썸네일 ≤ 1 s(tracemalloc·시간 기록, CI 는 기록만, 실기 체크리스트 판정) | `tests/doe/test_bead_select_perf.py` |
| V-BS-12 | **브라우저**: 인접·seed 확장(θ 경계 14.9/15.1°)이 합성 소형 픽스처에서 정답 바닥과 같음, 구간 압축이 서버 정규화와 같은 JSON, 기저 합 u 가 워커 x_d 와 ≤ 1e-4 mm, 실행 취소 | `frontend/__tests__/bead_select.test.ts`, 픽스처 `tests/fixtures/bead_select/small/*`(생성기로 만든 결과 커밋) |
| V-BS-13 | **API**: 권한(조회·power), 순서 409(PREP_NOT_READY·SELECTION_MISSING·PREVIEW_NOT_READY), 저장 version 충돌, 선택 바꾸면 run 409 `PREVIEW_STALE`, clone 선택 복사·`SELECTION_DROPPED`, select 에 step/mesh 필드 422, paicad 비활성이어도 select 활성, view 파일 경로 탈출 거부 | `backend/tests/test_doe_select_api.py` |
| V-BS-14 | **작업**: PREP(fixed-scan 있음/없음 → FIXED_INFO_MISSING), PREVIEW grid_manifest 가 paicad grid 형식과 같은 키, 셀 상태 매핑(SELECT_* → SKIPPED_FIXED/FAILED_MESH), RUN 이 READY 안만·이어하기(selection·basis sha 포함), 산출물 rad 사본 = 원본과 **`/NODE` 좌표 칸 외 바이트 동일**·ID 불변, 입력 폴더 불변 | `worker/tests/test_doe_select_jobs.py` |
| V-BS-15 | **E2E**: 합성 메시를 Case 로 등록 + 자기평형 ESL 2개 → 선택(API) → 미리보기 → 실행 → D1 깊어질수록 score 단조 감소, 보고서·받기·VD 진입 가능 | `worker/tests/test_doe_select_e2e.py` |
| V-BS-16 | **migration 0015**: 빈·0014 DB, 멱등, 기존 행 보존, 'select' 행·selection CHECK, `tables.py` 일치, 단일 head | `backend/tests/test_migrations.py` |
| V-BS-17 | **UI**: 하위 선택 라디오(비활성 사유), 도구 4종·층·Shift/Alt·보이는 면만, 사면·경계 자동 표시·±1줄, 비드 목록 경고 배지, 주 버튼 전환(선택 저장 ↔ 미리보기), 평면도 노드 토글·흐림·라벨 칩·폭 점선·단면 미니 그림, 썸네일 범례·클릭 3D, 2560×1440·1920×1080 잘림·가로 스크롤 없음 | `frontend/__tests__/doe_select.test.tsx`, mock |
| V-BS-18 | **회귀**: ①②③④ 기존 시험·하중 3D 보기(view3d) 동작 불변, `png.rasterize` 결과 불변 | 기존 |
| V-BS-R1 | **실기**: 실제 Ch/R(22만) Ch/R 비드(깊이 22·밑변 60·다단·경로) — 선택 소요 시간(목표 비드 1개 ≤ 5 분), derive·기저·미리보기 시간·메모리, 품질 실패 비율, 검증 낙하 1회로 순위 경향 확인 | `docs/manual/bead_doe_check.md`(절 추가) |

## 17. 파일 소유권 · 작업 단계

| 단계 | 담당 | 파일(소유) | 완료 조건 |
|---|---|---|---|
| S1 코어 | **Impl-Core** | `esl/doe/bead_select.py`(신규: 정규화·sha·인접·derive·기저·모핑·고정 판정·단면·plan 자료), `esl/doe/select_render.py`(신규: 3D 썸네일), `esl/doe/mesh_quality.py`(`affected_quality` **추가만**), `esl/doe/nodes.py`(`write_morphed` 추가), `esl/doe/stages.py`(bd_input·bd_loads·bd_matrix·bd_eval·bd_post `select` 분기 + `bd_select_grid`), `esl/doe/__init__.py`(SCENARIOS·DEFAULTS select), `esl/doe/paicad_io.py`(`cell_state` SELECT_* 분기), `esl/doe/report_doe.py`(선택 절), `resources/doe_messages.json`·`doe_method_sources.json`(모핑 규칙 출처), `tests/doe/synth_bead.py`·`test_bead_select_*.py`·`test_select_render.py`·`test_mesh_quality.py`(추가) | V-BS-1~11 |
| S2 백엔드 | **Impl-Backend** | `migrations/versions/0015_bead_select.py`, `core/db/tables.py`, `core/config.py`(`BeadDoeSelectCfg`), `api/schemas.py`(`DoeScenarioLit`·SelectionIn/Derived·응답 칸), `api/routers/doe.py`(select 경로 5개), `api/services/doe.py`(settings·require_enabled·check-inputs·studies·params·plan-view·preview·run sha 확인·clone), `api/services/doe_select.py`(신규: derive 캐시·저장·view/basis 파일), `api/services/verify*.py`(select 허용 1줄), `config/*.example.yaml`, `backend/tests/test_doe_select_api.py`·`test_migrations.py` | V-BS-9, 13, 16 |
| S3 워커 | **Impl-Worker** | `worker/esl_worker/doe_jobs.py`(select: BD_MESH0 SKIPPED, BD_GEOM fixed-scan 만/SKIPPED, BD_GRID = 코어 `bd_select_grid`, BD_DESIGNS paicad 생략), `worker/esl_worker/register.py`(preview selection_sha·skipped.mesh), `worker/tests/test_doe_select_*.py` | V-BS-14, 15 |
| S4 프런트 | **Impl-Frontend** | `src/view3d/scene.ts`·`sceneApi.ts`(선택 메서드 추가), `src/view3d/select/*`(신규 순수 모듈), `src/view3d/colors.ts`(발산 색), `src/pages/doe/DoeStudy.tsx`(하위 선택·카드·주 버튼), `src/components/BeadSelectCard.tsx`·`BeadList.tsx`·`SectionMini.tsx`(신규), `components/BoundaryPlan.tsx`(select 표시), `DoeParamTable.tsx`(묶음·블렌딩), `DoeThumbGrid.tsx`(범례·클릭 3D), `api/types.ts`·`api/doe.ts`, `mock/doedata.ts`, `__tests__/bead_select.test.ts`·`doe_select.test.tsx`, `pages/guide/*` | V-BS-12, 17 |
| S5 문서 | Plan/Impl | `VERSION`·`CHANGELOG.md` 0.15.0, `docs/manual/user.md`(선택 사용법·한계), `docs/manual/bead_doe_check.md`(V-BS-R1) | – |

- 순서: v0.14.0 병합 → S1(bead_select derive → 기저 → 품질 → 렌더) ∥ S2(스키마·migration·config) → S3(S1·S2 선행) → S4(mock 병행, select/* 순수 모듈 먼저) → E2E(V-BS-15) → 실기.
- 경계: 백엔드는 `bead_select.normalize·derive·plan_data`·`mesh_quality` 없이 동작(품질·기저·렌더는 워커). derive 는 numpy·scipy 만, 외부 명령 없음. 공동 수정 파일(`stages.py`·`doe.py`·`schemas.py`·`DoeStudy.tsx`·`doe_messages.json`·`mesh_quality.py`)은 v0.14.0 병합본 위에서만 고친다.

## 18. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-BS-1 | 실제 비드가 필렛·곡면이라 feature angle 확장이 새거나 모자람 | seed 법선 기준(이웃 누적 아님)·각도 칸·브러시 수정·서버 경고(LEAK/TIER_MISSING), 실기 V-BS-R1 로 기본각 조정 |
| R-BS-2 | 큰 ΔW·작은 R 에서 상판 요소 찌그러짐·뒤집힘 | R 자동 = k × 이동량, 품질 차단(§6), 표 배지 "R 작음" |
| R-BS-3 | 체결부가 비드 가까이 → W 안 대부분 스킵 | 선택 시 경고·R 자르기(BS-D-10), 결과에 스킵 수 |
| R-BS-4 | ESL 은 원 형상 K_L 정의 — 형상 변화 후 하중 재분배 미반영(BEAD_DOE R-BD-3) | 보고서 한계 절, 최적 안 검증 낙하(§8.4) |
| R-BS-5 | 브라우저 메모리·속도(22만 요소 ID 버퍼·인접) | typed array CSR, ID 버퍼는 브러시 영역만 readPixels, 선택 모드에서 LOD 끔(22만 < lod_min_nodes) |
| R-BS-6 | 백엔드 동기 derive 가 큰 선택에서 느림 | 인접 캐시(메시 sha), `derive_timeout_s`, bead 단위 호출(`bead` 인자) |
| R-BS-7 | v0.14.0 과 같은 파일 동시 수정 충돌 | 착수 = v0.14.0 병합 후(§17), `mesh_quality` 는 추가만 |
| R-BS-8 | 선형 기저(작은 변형 가정) — 큰 깊이 변화에서 법선 방향 고정 이동이 실제 설계 의도와 다를 수 있음 | 범위 기본 ±30 %, 단면 미니 그림으로 결과 형상을 사전 확인 |

## 19. 사용자에게 물을 결정 (≤ 3, 권장안으로 작성됨)

| # | 질문 | 선택지 | 권장 |
|---|---|---|---|
| Q1 | 폭 W 를 바꿀 때 단 바닥은? | **A** 바닥도 같이 넓어짐(단면 평행 이동, 사면 각 유지 — `floor_follow 1`) / B 바닥 고정(상판 개구만, 사면 각이 변함) | **A** — 설계 폭 변경 의미에 가깝고 사면 각이 유지돼 품질 실패가 적음. B 는 설정 키·비드별 칸으로 남김 |
| Q2 | ③ STEP 스터디의 재메싱 → 모핑 전환 | **A** 별도 계약(v0.16.0) — 이 엔진을 메시 출처 무관하게 만들어 둠 / B 이 계약에 포함 | **A** — 변수 출처(paicad)·재메싱 폴백·잡음 정책이 달라 범위가 두 배, v0.14.0 gmsh 변경과 겹침(§13) |
| Q3 | 위치 이동(U/V, 경로 수직 평행 이동) | **A** 보류(후속) / B v0.15.0 포함(경로 수직 방향 평행 이동 1변수, 블렌딩 = 폭과 같은 방식) | **A** — 경로형 비드 이동은 블렌딩 범위가 커서 품질·고정 침범 스킵이 많고, 1차 효과는 깊이·폭이 큼 |

## 20. 후속
- 위치 이동 U/V, 단별 폭, 끝단 길이 변수, 경로 일부 구간만 바꾸기(경로 매개변수 구간 변수).
- ③ 모핑 전환(§13), paicad tag 결과 가져오기(선택 출발점 — 다른 모델에서 1단 비드가 많을 때).
- 선택 템플릿(같은 계열 모델에 선택을 옮겨 쓰기 — 노드 ID 가 다르면 정규화 좌표 사상).
