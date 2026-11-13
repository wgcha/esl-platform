# 계약: 공통 비드 네트워크 분류기(beadgraph) · 세그먼트 모핑 · select 자동 탐지 출처 전환 (BEADGRAPH, v0.17.0)

- 상태: **확정** (2026-11-09). D1~D10 = 사용자 확정(아래, 변경 금지)을 코드·실험(H5·H6) 조사로 구체화. 사용자 결정이 더 필요한 항목 3개는 §10.1 열린 항목(권장안을 기본값으로 적었고, 답이 다르면 그 값만 바꾼다 — 구조 불변).
- 버전: **v0.17.0** (기준 main 1f7dcdd = v0.16.2). migration **불필요**(§5.6).
- 관계: `esl_bead_auto.md`(BEAD_AUTO, v0.16.2 — 이하 "AD")·`esl_select_relax.md`(SELECT_RELAX, v0.16.1 — 이하 "SR")·`esl_bead_select.md`(BEAD_SELECT, v0.15.0 — 이하 "BS")의 **변경 계약**. SR-D-44(모핑 코어는 메시 출처와 무관)를 그대로 따르고 확장한다. 이 문서에 없는 규칙은 AD → SR → BS 순서로 따르고, 충돌 시 이 문서가 우선. 단 **선택 schema 1 스터디(v0.16.2 이전에 만든 select 스터디)는 이 문서의 영향을 받지 않는다**(§5).
- 근거 실험: H5(`results_H5.md` — 고리 + T 접합, 현 esl 이 이웃 비드로 사면을 새어 1.65~2 mm 움직이고도 READY), H6(`results_H6.md` — 이슈 #63 합성 TV 후면 샤시 104 439 요소, 분류기 시제품 99.9 %·15 s·122 MB, 그래프 기반 부분 모핑).
- ID 규칙: 결정 `BG-D-n`, 시험 `V-BG-n`, 리스크 `R-BG-n`, 열린 항목 `O-BG-n`.

### 사용자 확정 (2026-11-09, 변경 금지)
1. **D1 깊이 = 부모 바닥 대비 상대값**: 위계 플랜지 → 고리 띠 → 플래토 → 채널·포켓. 자식은 부모를 강체로 따라간다.
2. **D2 공통 모듈**: 분류기·세그먼트 모핑 = esl-platform 과 physicsai-platform(paicad)이 함께 쓰는 모듈. 순수 numpy/scipy, 플랫폼 import 없음. 입력 = 메시 노드·요소·(선택) 고정 노드, 출력 = JSON 그래프. 패키지 위치·소비 방식·버전/호환 정책은 이 계약이 정한다(§8).
3. **D3 단면**: 사면 45° 유지, 입구 폭 고정 → 깊어지면 바닥이 좁아짐. 코너 가드: 바닥 코너에서 코너 반경이 ΔD 가 요구하는 값보다 작아지면 그 곳만 사면이 가팔라져도 됨(H6 d_g: 뒤집힘 0).
4. **D4 접합 램프** 길이 = max(3·ΔD, 3·h), smoothstep. 바뀐 세그먼트와 그 자식 밖은 0 mm — 밖이 움직이면 실패.
5. **D5 세로 채널**은 기본 각각 별도 변수. 대칭 묶기는 옵션.
6. **D6 벽에 걸친 보스는 채널을 따라감**. 실제 체결·고정 노드만 기존 hold 블렌딩으로 제자리. 보스 전체 고정을 대체.
7. **D7 고리 윗변의 넓어진 코너·코너와 다리 사이 짧은 띠**는 변수 없는 접합 구역으로 흡수. 고리 변수 = 4변(위·아래·왼쪽·오른쪽).
8. **D8 `island.max_mm` = 60**. 화면에서 어떤 조각이든 섬 ↔ 비드 전환 가능.
9. **D9 자동 탐지 seed 출처 = 이 메시 분류기**(paicad B-rep 인식 대신). paicad flanks 는 힌트만. paicad 는 고리 + ㅛ 같은 네트워크를 `BEAD_IRREGULAR` 로 버린다(사용자 관찰).
10. **D10 기존 화면 흐름 재사용**: 자동 seed → 편집(같은 BeadSelectCard/BeadList + 세그먼트 트리/그래프 보기). 새 화면 없음.

## 0. 현황 (1f7dcdd, 근거 파일:행 · 실험)

| # | 항목 | 근거 | 현재 동작 | 이 계약에서 |
|---|---|---|---|---|
| G1 | 자동 탐지 seed | `esl/doe/bead_auto.py`(AD-D-3·AD-X-1), `worker/esl_worker/doe_jobs.py` `_geom_select`(extract0→extract→tag) | paicad extract 가 인식한 비드의 bottom 면 tag 노드 → 1단/비드 | 메시 분류기 그래프 → seed(BG-D-20). paicad 는 힌트 |
| G2 | paicad 네트워크 탈락 | 사용자 관찰(#63) | 고리 + ㅛ 네트워크를 `BEAD_IRREGULAR` 로 버림 → seed 없음 | 분류기는 네트워크를 세그먼트·접합으로 나눔(§2) |
| G3 | 이웃 비드로 사면 누수 | H5 A 행, `bead_select.py` `_derive_bead` 사면 BFS·SR-D-29 Voronoi | V1 만 바꿔도 고리 노드 1.65~2.00 mm 이동, `SELECT_SLOPE_LEAK`·`SELECT_BEAD_NETWORK` 경고만, 판정 READY | 벽 소유(§2.3) + 바깥 0 강제(BG-D-34) |
| G4 | 깊이 = 기준 평면 대비 절대 | `bead_select.py` `_slope_levels`·`_depth_basis:1381`(단 바닥 n_i^k, 경계 고정) | 부모가 판이 아니면(플래토 위 채널) 기준 평면 맞춤이 기울거나 `SELECT_BASE_AMBIGUOUS` | 부모 바닥 대비 상대(D1, BG-D-15) |
| G5 | 섬 상한 | `esl/doe/__init__.py:155` `island.max_mm` 40, `backend/.../core/config.py:902` | 36~55 mm 엠보스가 섬/단 사이에서 흔들림(H6 열린 문제 5) | 그래프 경로 60(D8, BG-D-9), schema 1 은 40 유지(O-BG-1) |
| G6 | 벽 걸친 보스 | H6 (b)(e): 채널 바닥 노드 17.6 % 가 보스 hold 영역에 남아 깊이 7.18/10 | 보스 전체 hold | 보스는 채널 따라감, 고정 노드만 hold(D6, BG-D-27) |
| G7 | 바닥 코너 붕괴 | H6 (d): 포켓 C +2 → 뒤집힘 24(입구 코너 R8 − 새 깊이 8 = 0) | — | 코너 가드(D3, BG-D-26) |
| G8 | 45° 램프 < 요소 크기 | H5 C D−2: 길이 0 띠 → 조각 요소 3(aspect 43, warp 180) | — | 램프 = smoothstep, 최소 3h(D4, BG-D-24) |
| G9 | derive 시간 상한 | `esl/doe/__init__.py:162` `derive_timeout_s` 20 | API 요청 안 동기 derive | 분류는 DOE_PREP 작업에서 1회, derive 는 캐시만 읽음(BG-D-40) |
| G10 | 선택 형식 | `bead_select.py:52` `SCHEMA_VERSION = 1`, `normalize_input:187` | 비드 = 단별 바닥 요소 집합(ElemSet) | schema 2 = 세그먼트 참조(§5.1) |

## 1. 목적 · 범위

| 범위 (v0.17.0) | 비범위 |
|---|---|
| 공통 패키지 `packages/beadgraph/`(분류기 + 세그먼트 모핑 + 점검 + 합성 픽스처, §8) | 요소 단위 재배정 편집(reassign — 분류 오류 요소를 다른 세그먼트로 옮기기). 지금은 `exclude`·섬↔비드 전환·병합·분할·`src: elems` 비드로 대신 |
| ① `select`(case)·② `select`(mesh) 의 **수동·자동** 모두: DOE_PREP 에서 그래프 계산, 자동 = 그래프 seed, 수동 = 빈 seed + 같은 트리 | ④ 형상 비교(영향 없음 — 그래프 미사용, 해시·바이트 불변) |
| 선택 schema 2(세그먼트 참조 비드 + 요소 집합 비드 혼용) | ③ STEP 스터디·STEP 모핑(보류 — 같은 모듈을 쓸 호출 지점만 예약, BG-D-45) |
| 세그먼트 변수 D(상대)·W, 네트워크 묶기·대칭 묶기, 접합 구역 무변수 | 곡면 바닥(feature angle 10° 밖으로 휜 바닥)의 세그먼트 인식 — `src: elems` 비드로 |
| 모핑 규칙 D1·D3~D7, 섬·랜스 강체, hold 블렌딩, 바깥 0 강제 | 비드 경로 자체를 옮기는 변수(위치·길이), 섬 자체 변수 |
| 화면 최소 변경: 트리 보기, 섬↔비드 전환, 세그먼트 병합·분할, 대칭 묶기 | 새 화면·새 시나리오 |
| physicsai 인계 절(§8.5) | physicsai 쪽 구현(그 팀 작업) |

## 2. 그래프 모델

### 2.1 개념

| 개념 | 정의 |
|---|---|
| 바닥 조각(floor piece) | 법선이 기준 법선 n0 와 `feature_angle_deg` 안(부호 무관)인 요소의 연결 성분 중 같은 높이 수준(± `level_tol_mm`)인 것. 넓이 < `min_floor_area_mm2` 는 벽으로 |
| 벽(wall) | 바닥 아닌 요소. 각 벽 요소는 **정확히 하나의 전이(transition)** `(upper, lower)` 에 속함(§2.3) |
| 위계(tree) · tier | 바닥 조각의 부모 = 그 조각의 **바깥 경계 고리** 건너편 바닥(둘러쌈). 뿌리(base) = 바깥 고리 자유 모서리 비율 ≥ `root_free_frac` 인 최대 바닥(+ 외곽에 닿는 같은 높이 조각 = `root_group`). tier = 뿌리부터 깊이(플랜지 0 → 고리 띠 1 → 플래토 2 → 채널·포켓 3) |
| 상대 높이 | `rel_height` = 조각 높이 − 부모 높이(n0 방향, 부호 있음). 변수 D = \|rel_height\|(D1) |
| 세그먼트(segment) | 비드형 바닥 조각을 골격으로 나눈 조각(접합·굽힘·폭 급변에서 끊음, §2.4). 면형 바닥(플래토 등)은 조각 전체 = 세그먼트 1개 |
| 네트워크(network) | 같은 바닥 조각에 속한 세그먼트·접합 구역 전체(예: 고리 띠 + 다리 4개 = 하나의 네트워크) |
| 접합(junction) | `T`(가지 3)·`X`(4)·`L`(굽힘 > `bend_deg`)·`W`(폭 급변 > `width_jump`)·`Y`(짧은 끝 가지 2개를 가진 T = 나팔)·`step`(같은 부모의 두 자식 바닥 사이 벽 — 형제 단차) |
| 접합 구역(junction zone) | 접합 노드 반경 안의 바닥·벽 요소 + 흡수된 코너·짧은 띠(D7). **변수 없음, 0 mm**(묶음에 포함될 때만 움직임 — BG-D-19) |
| 섬(island) | 크기(PCA 장축) ≤ `island.max_mm` 인 부분 트리(바닥 + 자손 + 벽). 강체. `straddle` = 접촉 중 부모 아닌 바닥 비율 > `straddle_frac` |
| 랜스(lance) | 자유 모서리 고리가 부모 바닥에도 닿는(**열린 고리**) 섬. 강체, 변수 없음 |
| 구멍(hole) | 자유 모서리 고리(판 외곽 제외). 둘레는 주인(바닥·섬)과 함께 이동(SR-D-6) |
| 고정(fixed) | 입력 고정 노드(fixed-scan + `fixed_user`). 구멍·섬·노드에 `fixed` 표지 |

### 2.2 분류 파이프라인 · 규칙 · 임계

| ID | 결정 | 근거 |
|---|---|---|
| BG-D-1 | **파이프라인 4단계**(H6 시제품 그대로, 순서 고정): (1) 위상·법선 — 모서리·인접, BFS 일관 법선, n0 = 평평한 요소 넓이 가중 평균 법선(정련), 평면 좌표 (e1, e2) ⊥ n0. (2) 수준 — 바닥 요소 → 바닥 조각, 벽 소유(§2.3). (3) 위계 — 부모·뿌리·tier, 섬·랜스·구멍. (4) 골격 — 비드형 바닥 래스터 → 세선화 → 가지 그래프 → 세그먼트·접합(§2.4) | H6 정확도 99.88 %(126 요소 오분류/104 439) |
| BG-D-2 | **feature angle 기본 10°** = 이슈 #53 HyperMesh param 파일 `feature_angle 10`. select 칠하기 확장 각(`select.feature_angle_deg` 15)과 **별개 키** `select.graph.feature_angle_deg` | #53 기준과 같은 각으로 바닥을 정의 |
| BG-D-3 | **임계 기본값**(모두 설정 키, §5.5): `level_tol_mm` 0.3, `min_floor_area_mm2` 12, `root_free_frac` 0.2, `raster_mm` 1.0, `island{max_mm 60, straddle_frac 0.15}`, `bead{max_width_mm 80, prune_k 2.2, bend_deg 50, width_jump 0.35, min_zone_mm 12, open_ext_mm 90, absorb_len_mm 60}` | H6 값. `island.max_mm` 만 40 → 60(D8), `absorb_len_mm` 신규(D7) |
| BG-D-4 | **분류는 부호 무관**: 바닥 판정은 \|n·n0\| 로, 뒤집힌 작은 요소(gmsh flap)가 있어도 결과 불변. 요소 법선 방향·노드 순서·번호 체계와 무관(BG-D-12) | H6: 남은 작은 뒤집힘 5개 영향 없음 |
| BG-D-5 | **입력 = 메시만**(D2·SR-D-44): `nodes (n,3) float64 mm`, `elems (m,4) int 0-based`(삼각형은 4번째 = −1), `fixed (k,) int`(선택), `cfg`. 노드 ID·파트·STEP·출처(gmsh·.rad/.inc·재메시)를 모름. 인치 입력은 호출자가 mm 로 바꿔 넘김 | 메시 출처 무관 |

### 2.3 벽 소유 (각 벽은 정확히 하나의 전이)

| ID | 결정 | 근거 |
|---|---|---|
| BG-D-6 | **배수(drainage) 규칙**: 벽 요소를 높이 내림차순으로 처리 — upper = 가장 높은 이웃의 upper 바닥(바닥 이웃이면 그 바닥), lower = 가장 낮은 이웃의 lower 바닥. 국소 최저(보스 둘레 도랑 등)는 가장 낮은 표지 이웃에서 채우되 반대 끝과 다른 표지 우선. 결과: 벽 요소마다 `(upper, lower)` 1쌍 → 전이 id 1개 | H6: 채널 위 고리 표지 벽 0(H5 누수 제거), `band\|flange`·`plateau\|band` 소유 100 % |
| BG-D-7 | **전이 종류**: `parent-child`(한쪽이 다른 쪽 부모, `child` 기록) · `junction`(같은 부모의 두 형제 — step) · `self`(양 끝 같은 바닥) · `other`. 벽의 세그먼트 = 그 벽 전이의 자식 바닥 쪽 **가장 가까운 자식 바닥 요소의 세그먼트**(평면 거리, 동률 = 작은 세그먼트 id) | 변수가 움직일 벽을 한 곳으로 |
| BG-D-8 | **보스 둘레 도랑**(H6 오분류 1위 — 채널 벽 46·채널 바닥 ≈ 21 요소가 섬으로)은 v0.17.0 에서 규칙을 바꾸지 않는다: D6 로 걸친 보스가 채널을 따라가므로 도랑이 섬으로 표지돼도 같은 변위(채널 → 보스 강체)를 받는다. 정확도 기준(V-BG-1)은 이 오분류를 포함한 값 | 결과 형상 영향이 작고 규칙 변경은 RULES 상승 |

### 2.4 섬 · 랜스 · 구멍 · 세그먼트 · 접합

| ID | 결정 | 근거 |
|---|---|---|
| BG-D-9 | **섬** = 부분 트리 중 PCA 장축 ≤ `island.max_mm`(**60**, D8). 섬은 변수 없음·강체(주인 바닥 둘레 평균 변위, SR-D-5). 섬 안의 다단(보스 2단)은 한 섬. **사용자 전환**(D8): 어떤 바닥 조각이든 `toggle{as: bead|island}` 로 바꿈 — 섬 → 비드 = 그 조각이 세그먼트(변수 가능), 비드 → 섬 = 그 부분 트리 강체(크기 무관) | D8 |
| BG-D-10 | **랜스** = 섬 중 자유 모서리 고리가 부모 바닥에도 닿는 것(열린 고리, 한쪽이 슬롯). 강체, 변수 없음, 슬롯 구멍 `lance_slot: true`. **구멍** = 판 외곽이 아닌 자유 모서리 고리, `d_eq` = 4A/P, `owner_floor`/`owner_island`, 고정 노드가 있으면 `fixed: true` | H6: 랜스 16/16, 구멍 78/78 |
| BG-D-11 | **세그먼트**: 비드형 바닥(뿌리·섬 아님, 폭 ≤ `bead.max_width_mm`)을 `raster_mm` 로 래스터 → 작은 구멍·섬 채움 → 외곽에 닿는 열린 끝은 `open_ext_mm` 까지 연장 → Zhang–Suen 세선화 → 가지 가지치기(국부 반경 × `prune_k`, 열린 끝 보호) → 가지 그래프 → 차수 ≥ 3 에서 T/X, 회전 > `bend_deg` 에서 L, 폭 급변 > `width_jump` 에서 W, 구간 < `min_zone_mm` 은 이웃과 합침. 끝 가지 2개가 짧은 T = **Y**(나팔). 폭이 큰 바닥(플래토)은 `area` 세그먼트 1개(자식이 있으면 `type: plateau`). 세그먼트 `type`(ring·leg·channel·pocket·flare·corner·tooth·spur·plateau·area·base)은 **휴리스틱 표지**이고 규칙에 쓰지 않는다 — 단 `corner`·`spur` 는 BG-D-13 흡수 규칙에 씀 | H6: 세그먼트 23/23, 접합 16/16(T4·L2·W4·Y2·step4) |
| BG-D-12 | **결정성·ID**: 같은 입력 + 같은 cfg → `graph.json` 바이트 동일. id 순서 = 바닥 조각 (tier, 최소 요소 index), 세그먼트 (바닥 id, 골격 시작점 평면 좌표 1e-3 반올림 사전순), 접합 (평면 좌표), 섬 (최소 요소 index), 구멍 (중심 좌표). 실수는 1e-3 mm(각 1e-3°) 반올림해 JSON 에 쓴다. 각 세그먼트·섬·조각은 **앵커 요소**(`anchor` = 그 집합의 최소 요소 index)를 가진다 — 선택은 id 가 아니라 앵커로 참조(BG-D-30) | 저장된 선택이 규칙 판 상승 뒤에도 같은 조각을 가리키게 |
| BG-D-13 | **접합 구역 흡수**(D7): (a) `type: corner`(W 로 끊긴 넓어진 코너), (b) 양 끝이 모두 접합이고 길이 < `absorb_len_mm`(60)인 띠(코너와 다리 사이 ≈ 50 mm 띠), (c) `spur`(가지치기 뒤 남은 짧은 가지 — H6 포켓 R 2개)는 세그먼트가 아니라 **접합 구역**으로(`junction_zone` id, 변수 없음). **고리 변**: 닫힌 골격 순환을 L·W 접합(코너 구역)에서 끊은 사슬. 사슬 안의 T 접합(셋째 가지가 고리가 아닌 다리·빗살)은 끊지 않는다 → 고리 변수 = 위·아래·왼쪽·오른쪽 4변. 변 이름 = 그 변 골격 중점의 평면 위치(n0 기준 화면 위/아래/왼/오른 — `side: top\|bottom\|left\|right`, 고리가 아니면 null) | D7. H6 의 아래 변 = 세그먼트 11+13+12(T2·T3 포함) |
| BG-D-14 | **step 접합**: `junction` 전이의 벽(형제 바닥 사이 단차, 예: 나팔 바닥이 포켓 안으로 2 mm 더 깊음) = 접합 구역. `step_mm` 기록 | H6 step 4/4 |

### 2.5 JSON 스키마 `beadgraph/1`

`classify()` 는 **(graph, labels)** 를 돌려준다. graph = JSON(요소별 배열 없음), labels = 요소별 정수 배열 dict(esl 은 `graph_labels.npz` — `allow_pickle=False`, int32).

```text
graph = {
  schema: "beadgraph/1", version: "<패키지 semver>", rules: <int RULES>, morph_rules: <int MORPH_RULES>,
  input: {n_nodes, n_elems, n_tri, n_fixed, sha256},        # sha256 = (nodes float64 LE 1e-6 반올림 ‖ elems int32 LE ‖ fixed int32 LE 정렬) — 결정적
  cfg: {…병합된 전체 cfg…}, cfg_sha256,
  frame: {n0[3], e1[3], e2[3], h_mm},                         # h_mm = 바닥 요소 모서리 길이 중앙값
  root: <floor id>, root_group: [floor id…],
  floors: [{id, anchor, level, rel_height, parent, tier, kind: base|base_fragment|bead|area|island, island: <id>|-1,
            area, n_elems, outer_free_frac, network: <id>|-1}],
  transitions: [{id, upper, lower, type: parent-child|junction|self|other, child, n_elems, step_mm?}],
  networks: [{id, floor, segments[], junction_zones[]}],
  segments: [{id, anchor, floor, parent, tier, network, type, side: top|bottom|left|right|null, rel_depth, D, entry_width|null,
              floor_width|null, length|null, open_end, junctions[], children[floor id], islands[], fixed_n, n_elems,
              skeleton: [[x, y]…] (평면, ≤ 256 점, 1e-3)}],
  junctions: [{id, type: T|X|L|W|Y|step, plan[2], pos[3], radius, segments[], floors[], zone: <junction_zone id>, step_mm?}],
  junction_zones: [{id, anchor, network, reason: junction|corner|short_strip|spur|step, junctions[], adj_segments[], n_elems}],
  islands: [{id, anchor, floors[], parent, owner_segment, size_mm, rel_height, lance, straddle, touch:[{kind, ids[], n}],
             fixed, plan[2], n_elems}],
  holes: [{id, plan[2], center[3], d_eq, area, circularity, owner_floor, owner_island, lance_slot, fixed, n_nodes}],
  warnings: [{code, level, …}]                                 # GRAPH_* 경고(§6.4)
}
labels = {cls (0 floor, 1 wall, 2 island, 3 lance), floor, segment, transition, island, junction_zone, tier}   # 없으면 −1
```
- 소비자 규칙: `schema` 주 번호가 다르면 거부, 모르는 필드는 무시. labels 배열 길이 = n_elems, 순서 = 입력 elems 순서.

## 3. 변수

| ID | 결정 | 근거 |
|---|---|---|
| BG-D-15 | **세그먼트 D** = 그 세그먼트 바닥의 부모 바닥 대비 상대 높이 크기 \|rel_height\|(mm). 공칭 = 바닥 노드(접합 구역 반경 밖) 높이 중앙값 − 부모 수준. 값을 키우면 부모에서 멀어짐(내려간 채널은 더 깊게, 올라간 플래토는 더 높게). **자손은 강체로 따라감**(D1, BG-D-23) | D1 |
| BG-D-16 | **세그먼트 W** = 입구 폭(부모 바닥과 벽이 만나는 두 선 사이 거리): 골격 표본점마다 수직 반직선이 두 입구 선과 만나는 거리의 중앙값(접합 반경 안 표본 제외). 입구 선이 양쪽 모두 있는 세그먼트만(ring 변·leg·channel·pocket·flare·tooth). `area`·`plateau` 는 D 만 | D3: 입구 폭이 단면의 기준 |
| BG-D-17 | **비드(화면 목록 1행) = 변수 묶음**: `segs`(앵커 목록 — 같은 네트워크·연결된 세그먼트, 접합 구역으로 이어져야 함 → 아니면 422 `BG_GROUP_NOT_CONNECTED`). 묶음의 D = 하나의 변수(모든 구성 세그먼트에 같은 ΔD), W = 구성 세그먼트가 모두 W 를 가질 때만. 공칭 D 가 구성 사이에서 `sym_tol_mm` 넘게 다르면 D 공칭 = 길이 가중 평균 + 경고 `BG_GROUP_NOMINAL_SPREAD{bead, min, max}`(ΔD 는 같음 — 상대 변화) | 고리 아래 변(세그먼트 3개)이 변수 1개 |
| BG-D-18 | **네트워크 묶기**: `segs: [{network: <앵커>}]` = 그 네트워크의 모든 세그먼트 + 모든 접합 구역 = 바닥 조각 전체 → D 1개(바닥 조각 전체 깊이 — 자손 모두 따라감). W 없음 | 고리 전체 높이 변경 |
| BG-D-19 | **접합 구역 = 변수 없음**: 기본 0 mm. 단 그 구역에 붙은 세그먼트 중 **2개 이상이 같은 비드**이면 그 구역은 그 비드와 함께 움직이고(사이 구역), 비드 밖 세그먼트·구역과 공유하는 노드가 램프 기준 J(BG-D-24). 네트워크 묶기는 모든 구역 포함 | D7 + 고리 변 안 T 구역 |
| BG-D-20 | **자동 seed 규칙**(D5·D7·D9): 비드 1개 = (a) 고리 변 1개(4변 각각), (b) 다리·빗살·채널·포켓 세그먼트 각각(세로 채널 각각 — D5), (c) 나팔(Y)은 같은 바닥의 채널과 같은 비드(사이 Y 구역 포함), (d) 면형 바닥(플래토)은 D 만, (e) 섬·랜스·접합 구역·뿌리 = 비드 없음. 순서 = (tier, 앵커). `max_beads` 초과분은 버리고 `AUTO_TOO_MANY_BEADS`(AD 그대로). 대칭 묶기는 seed 에 넣지 않고 **제안**만(`sym_pairs`, BG-D-21) | H6 seed ≈ 16 비드 ≤ `max_beads` 20 |
| BG-D-21 | **대칭 묶기(옵션, D5)**: 최상위 `ties: [["b2","b3"], …]` — 묶인 비드는 D·W 각각 변수 1개(이름 = 작은 id, `group_members` = 모두). 조건 = 같은 W 유무, \|D_nom 차\| ≤ `sym_tol_mm`(0.5), \|W_nom 차\| ≤ 2·`sym_tol_mm` → 아니면 422 `BG_TIE_NOMINAL`. 제안 `sym_pairs` = 같은 tier·같은 type 세그먼트 쌍 중 부품 중심 평면(e1 또는 e2 축, 노드 bbox 중앙) 거울 위치의 골격 Hausdorff ≤ 5·`sym_tol_mm` | D5 옵션 |
| BG-D-22 | **기존 select 파이프라인에 그대로 얹기**: 변수 행 = `params_table` 행 형식 그대로(`{name, type, bead, tier, nominal, feasible, feasible_source, default_range, use_default, group_members}`), 이름 = `var_name(bid, "D"\|"W")` = `B<n>_D`·`B<n>_W`(k 없음 — schema 1 의 `B<n>_D<k>` 와 겹치지 않음), `tier` = 그래프 tier(표시만). 기본 범위 = `select.range`(D ±30 %, W ±20 %) 그대로. feasible(45° 입구 고정 → 바닥 폭 = W_entry − 2·D, 바닥 최소 폭 `W_floor_min` = max(2h, 6 mm)): D = [`min_step_mm`, min(D_nom·(1 + `depth_max_rel`), (W_entry − W_floor_min)/2)](W 없는 면형 바닥은 앞 항만), W = [2·D_nom + W_floor_min, W_nom·(1 + `width_max_rel`)]. 코너는 BG-D-26 이 따로 막음. 기저 = `bead_select.Basis`(같은 npz·bin 형식 → `morph()`·`basis.bin`·브라우저 미리보기 불변). 판정 = `esl/morph/core.py` 공통 코어 그대로(SR-D-37 피처 왜곡 — features = 그래프 섬 {rim, interior}, SR-D-38 다른 비드 침범 — 다른 비드 허용 구역, SR-D-33 `range_check`, SR-D-39 `range_combo`, SR-D-40 극단값) + BG-D-34 바깥 이동 | 새 판정기를 만들지 않음 |

## 4. 모핑 규칙

모든 규칙은 **변수별 선형 기저** B_v 로 만든다(x = x0 + Σ (v − v_nom)·B_v, BS-D-9). 값에 따라 달라지는 양(램프 길이·코너 가드 계수)은 기본 범위 끝에서 한 번 정해 기저에 고정한다(BG-D-24·26). 기저는 패키지 `beadgraph.morph.basis(graph, labels, X, beads, cfg)` 가 만들고 esl 은 `Basis` 로 감싼다.

### 4.1 구역 (변수 v, 비드의 세그먼트 집합 S, 부모 바닥 p)

| 기호 | 정의 |
|---|---|
| Z_F | S 의 바닥 요소(사이 접합 구역 포함, BG-D-19) |
| Z_W | S 에 속한 벽(BG-D-7) |
| Z_C | **S 에만 붙은** 자식 부분 트리(자식 바닥 + 그 벽 + 자손 + 그 위 섬) — 자식과 부모 사이 전이 벽이 Z_F 요소에만 닿는 것 |
| Z_SC | **공유 자식**의 전이 벽 중 Z_F 쪽 부분 — 자식이 S 밖 세그먼트·접합 구역에도 닿는 경우(예: 고리 띠 위 플래토는 4변 모두에 닿음) |
| Z_I | 주인 세그먼트가 S 인 섬·랜스 + **S 바닥에 닿는 걸친 섬**(D6) |
| J | Z_F ∪ Z_W 노드 중 S 밖 요소(다른 세그먼트·접합 구역·공유 자식 바닥)와 공유하는 노드 |
| E | 입구 노드(Z_W ∩ 부모 바닥 p) |
| A_v | 허용 구역 = D: Z_F ∪ Z_W ∪ Z_C ∪ Z_SC ∪ Z_I, W: Z_F ∪ Z_W ∪ Z_I ∪ 부모 블렌딩 띠 R_w |

### 4.2 결정

| ID | 결정 | 근거 |
|---|---|---|
| BG-D-23 | **D: 자손 강체**(D1): Z_C ∪ (Z_C 위 섬) 노드 u = s·ΔD·n0(s = 부모에서 멀어지는 부호) — 평면 성분 0. **공유 자식**은 움직이지 않고(0), 그 전이 벽 Z_SC 노드는 높이 비 t(자식 입구 = 1, S 바닥 = 0)로 u = (1 − t)·u_floor_edge(선형) → 그 변에서만 자식 상대 높이가 ΔD 바뀜 + 정보 `BG_SHARED_CHILD{bead, child, n_nodes}`(O-BG-2) | D1, 고리 한 변 변경 시 플래토 찢어짐 방지 |
| BG-D-24 | **접합 램프**(D4): φ(x) = smoothstep(d_J(x)/L), smoothstep(u) = 3u² − 2u³(u ∈ [0,1]), d_J = J 까지 평면 거리, **L = max(`ramp_k`·ΔD_ext, `ramp_k`·h)**, `ramp_k` 3, h = 그래프 `frame.h_mm`, ΔD_ext = 기본 범위 양 끝 중 \|끝 − 공칭\| 최대(W 는 ΔW_ext/2). 모든 변위에 φ 를 곱하고 J·E 노드는 0. 사용자 범위 끝이 ΔD_ext 를 넘으면 기저는 그대로 두고 경고 `BG_RAMP_SHORT{var, L_mm, need_mm}`(실행 막지 않음 — 최소 3h 는 지켜짐). 램프 밖(φ = 1) 바닥 노드가 없으면(세그먼트가 2L 보다 짧음) 그 D·W 는 `use_default: false` + `BG_SEGMENT_SHORT{bead, length_mm, ramp_mm}` | H5 B: smoothstep 램프 최선, C: 45° 램프 < h 는 조각 요소 |
| BG-D-25 | **D 단면 45°·입구 고정**(D3): Z_W 노드와 바닥 가장자리 노드 = 가장 가까운 입구 노드 x_e 를 중심으로 한 3D 닮음 u = (x − x_e)·ΔD/D(선형 — k = (D+ΔD)/D). 사면 각 보존(설계 45°), 바닥은 한쪽당 ΔD 만큼 좁아짐. 바닥 안쪽: 법선 성분 u_n = s·ΔD, 평면 성분 = 바닥 조화 확장(Dirichlet: 가장자리 = 닮음의 평면 성분, 자손 둘레·섬 둘레·J = 0) | D3. H6 (a)(b)(e) 뒤집힘 0 |
| BG-D-26 | **코너 가드**(D3): 기본 범위의 양 끝(±ΔD_ext)에서 닮음을 적용해 Z_F ∪ Z_W 요소의 평면 넓이 비 < `corner.area_ratio_min`(0.35)인 요소가 있으면, 그 요소 노드 중 움직이는 노드의 평면 성분에 `corner.shrink`(0.8)를 곱하길 ≤ `corner.iters`(40)회 반복 → 노드별 평면 계수 c_i ∈ (0, 1] 를 **기저에 고정**(선형 유지). 그 곳 사면은 45° 보다 가팔라짐. 정보 `BG_CORNER_GUARD{bead, n_nodes, flank_max_deg}`. 반복 후에도 남으면 그 끝은 `range_check` 가 잡음(SR-D-33) | H6 d → d_g: 뒤집힘 24 → 0 |
| BG-D-27 | **걸친 보스는 채널을 따라감**(D6): Z_I 의 걸친 섬 = 핵심(남의 바닥에 닿지 않은 요소의 노드) 강체 u = 채널 쪽 둘레 노드 변위 평균. **남의 바닥 접촉 띠**(섬 벽 요소 중 S 밖 바닥 노드를 가진 요소의 노드) u = smoothstep(d_f/b_s)·u_island(d_f = 남의 바닥 접촉 노드까지 평면 거리, b_s = 그 띠 폭, ≥ h) — 남의 바닥 노드는 0(BG-D-34). 보스 전체 hold(H6) 폐지 | D6. H6 (b) 의 미달 패치(7.18/10) 제거 |
| BG-D-28 | **고정 노드 hold**(D6): 그래프 비드는 `hold_fixed` **기본 1** — A_v 안 고정 노드에서 SR-D-9 링 계수 ψ(거리 ≤ `select.hold.ring_mm` 3 → 0, 3..3+`blend_mm` 8 Wendland, 밖 1)를 모든 변위에 곱함(선형). 비드별 0 으로 끄면 SR 규칙(`fixed_policy` warn = 고정 노드도 움직임 + `SELECT_FIXED_MOVED`) | D6 "실제 체결 노드만 기존 hold 블렌딩" |
| BG-D-29 | **섬·랜스 강체**: φ·ψ 를 곱한 뒤 각 섬·랜스 노드 u = 그 둘레(주인 바닥과 공유) 노드 변위 평균(SR-D-5, 평행 이동). 구멍 둘레는 주인과 같은 식(SR-D-6). 섬 안 고정 노드는 ψ 가 이미 적용된 둘레 평균을 따름 — 섬 안 고정 노드가 있으면 그 섬은 강체 대신 ψ 직접 적용 + 정보 `BG_ISLAND_HELD{island}` | H6 섬 잔차 0.000 |
| BG-D-30 | **W**: Z_W·바닥 가장자리·입구 노드를 바깥 평면 법선(가장 가까운 골격 표본의 법선) 방향으로 ΔW/2 평행 이동(깊이·사면 각 유지 → 바닥 폭도 ΔW). 바닥 안쪽 평면 = 조화 확장(자손·섬 둘레 0 — 자식은 제자리). 부모 바닥 블렌딩 띠: 입구에서 거리 d < R_w 인 부모 바닥 노드 u = (ΔW/2)·n_out·(1 − smoothstep(d/R_w)), R_w = BS R_auto 규칙(`select.blend`)을 다른 비드·다른 세그먼트·접합 구역에 닿지 않게 자름(잘리면 `SELECT_BLEND_CLIPPED` 재사용). φ(BG-D-24)·ψ(BG-D-28) 적용 | H6 (c): W 37.28 → 40.28 정확, 바깥 0.038 은 블렌딩 띠 안 |
| BG-D-31 | **변수 합성**: 한 안에서 여러 변수가 바뀌면 기저 합(선형). 같은 노드에 두 비드 기저가 겹치는 곳(공유 자식 벽·블렌딩 띠)은 SR-D-38 `cross_move` 로 보고(`cross_bead_policy`) | BS-D-9 |

### 4.3 바깥 0 강제 · 달성 깊이

| ID | 결정 | 근거 |
|---|---|---|
| BG-D-32 | **기저 지지 점검**(BD_MATRIX): 모든 v 에 대해 supp(B_v) ⊆ nodes(A_v). 위반 = 기저 오류 `BG_BASIS_LEAK{var, n, max_mm}` → BD_MATRIX 실패(구현 결함 — 실행하지 않음) | 구조적으로 0 이어야 함 |
| BG-D-33 | **달성 깊이**: D 변수의 달성 노드 = Z_F 바닥 노드 중 φ = 1 ∧ ψ = 1 ∧ c_i = 1 ∧ 섬 아님. 그 노드의 상대 높이(n0 방향, 부모 수준 기준) = 목표 ± `achieved_tol_mm`(1e-6). W 는 φ = 1 골격 표본의 입구 폭 = 목표 ± 1e-3 mm(측정 이산화). 기저 생성 직후 범위 양 끝에서 점검 → 어긋나면 `BG_BASIS_LEAK` 와 같은 실패(`BG_ACHIEVED_MISMATCH{var, err_mm}`) | 사용자 기준 "achieved depth exact" |
| BG-D-34 | **안 판정 = 바깥 이동 실패**(D4): 안마다 바뀐 변수 집합 V' 의 허용 구역 합 A = ∪ A_v 밖 노드의 max ‖x − x0‖ > `outside_tol_mm`(1e-6) → **FAILED_MESH `BG_OUTSIDE_MOVED{n, max_mm, vars}`**(정책 무관). 판정 순서 = 뒤집힘 → **바깥 이동** → 피처 왜곡(SR-D-37) → 고정(skip) → 침범(skip) → 품질(skip). 자료 = `design_checks` 에 `chk_o*`(허용 노드 마스크 비트열, 변수별) — schema 1 기저에는 키 없음(바이트 불변) | D4 "밖이 움직이면 실패" |

## 5. 이전 · 호환

### 5.1 선택 schema 2

| ID | 결정 | 근거 |
|---|---|---|
| BG-D-35 | **SelectionIn schema 2 신규**, schema 1 은 그대로 받음. v0.17.0 이후 만든 select 스터디 = `inputs.select_schema: 2`(키 없음 = 1). schema 1 스터디에 schema 2 저장 → 422 `SELECT_SCHEMA_MISMATCH`, 반대도 같음. 복제 = 원 스터디 schema 유지 | 기존 선택 sha·기저·판정 바이트 불변 |
| BG-D-36 | **schema 2 형식**: 아래. `src: "graph"` 비드 = 세그먼트 앵커 참조, `src: "elems"` 비드 = schema 1 비드 본문 그대로(분류가 못 잡은 곳·곡면 바닥 — v0.16.2 derive 경로, 단 섬 상한은 그래프 값 60). 두 종류 요소 겹침 → 422 `SELECT_OVERLAP`(기존 코드). 정규화 = 키 정렬·앵커 정렬·기본값 키 생략(`hold_fixed` 는 그래프 비드에서 0 일 때만, elems 비드에서 1 일 때만 씀) | D10: 같은 목록에 두 출처 |
| BG-D-37 | **편집**(`graph.edits`): `toggle[{anchor, as: bead\|island}]`, `merge[[{anchor}, {anchor}…]]`(인접 세그먼트를 한 세그먼트로 — 사이 접합 구역 흡수), `split[{anchor, at: [x, y]}]`(골격에서 at 에 가장 가까운 점으로 끊고 그 자리 반경 h 의 `split` 접합 구역 — 변수 없음). 적용 순서 = toggle → merge → split(각 목록 정렬 순). 결과 그래프 = `beadgraph.edits.apply(graph, labels, edits)`(결정적) | 사용자 수정을 그래프 위에서 |
| BG-D-38 | **선택 sha** = schema 2 정규화 JSON 의 sha256(그래프 sha 포함 → 같은 메시·같은 분류 cfg 에서만 같은 sha). 저장된 `graph.sha256` 이 현재 `prep/select/graph.json` sha 와 다르면(cfg 변경·RULES 상승) derive·저장 409 `BG_GRAPH_STALE{saved, current}` — 화면은 "분류 결과가 바뀌었습니다 — 다시 확인 후 저장" 띠 + 앵커로 다시 해석한 선택을 미리 채움(해석 실패 앵커 = `BG_SEG_UNKNOWN{anchor}` 표시) | 앵커 참조(BG-D-12)로 재해석 가능 |

```text
SelectionIn (schema 2) = {
  schema_version: 2,
  feature_angle_deg: 1..45,                       # elems 비드 칠하기 확장각(schema 1 의미 그대로)
  graph: { sha256: <prep/select/graph.json sha>, rules: <int>,
           edits: { toggle: [{anchor, as}], merge: [[{anchor}…]], split: [{anchor, at:[x,y]}] } },
  beads: [ { id: "b1".."b20", name?, src: "graph", segs: [{anchor} | {network: anchor}], vars?: ["D","W"] (기본 가능한 것 전부),
             hold_fixed?: 0 }
         | { id, name?, src: "elems", tiers, slope, blend_mm, floor_follow, links, hold_fixed? } ],   # schema 1 BeadSel 그대로
  ties: [[bead id, bead id, …]],                  # 대칭 묶기(BG-D-21)
  fixed_user: NodeSet, exclude: ElemSet            # 의미 그대로. exclude 요소는 그래프 비드 Z_F 에서도 빠짐(그 요소 노드 0)
}
```

### 5.2 판·해시·바이트 불변

| ID | 결정 | 근거 |
|---|---|---|
| BG-D-39 | **schema 1 경로 판 불변**: `bead_select.ALGO` 3·`RULES` 3 **그대로**(schema 1 계산·판정 규칙이 안 바뀜 → 옛 미리보기에 `rules_outdated` 띠 없음, 기저 재계산 없음). 그래프 경로는 따로 `GRAPH_ALGO = 1`(`basis.json.graph_algo`, `SelectionDerived.graph_algo`)·`grid_manifest.graph_rules = 1` 과 패키지 `RULES`·`MORPH_RULES` 를 기록. **올림 정책**: schema 1 출력이 바뀌면 ALGO/RULES, 그래프 기저가 바뀌면 GRAPH_ALGO, 그래프 판정이 바뀌면 graph_rules, 패키지 출력이 바뀌면 패키지 RULES/MORPH_RULES(§8.3). 기저 재사용 조건 += `graph_algo`·`morph_rules` 같음 | 판 하나가 무관한 경로를 다시 계산시키지 않게 |
| BG-D-40 | **그래프 계산 위치**: DOE_PREP BD_LOADS(코어, 기준 메시 확정 뒤 — ① case·② mesh 같음, SR-D-44) 에서 `select_schema == 2` 일 때만 → `prep/select/graph.json`(결정적 바이트)·`prep/select/graph_labels.npz`·`prep/select/graph.bin`(브라우저용, §6.1). 실패(분류 예외·시간/요소 상한) = 준비 **READY** 유지 + 경고 `GRAPH_FAILED{code}` + 빈 seed(수동은 `src: elems` 로 계속). schema 1 스터디의 준비 재실행은 그래프 단계를 건너뜀(산출물 바이트 불변) | AD-D-2 와 같은 원칙 |
| BG-D-41 | **설정 해시**: 새 절 `select.graph` 는 `HASH_NEW_KEYS_V0170 = ("graph",)` — 기본값이면 `select_hash_view` 에서 빠짐 → `_cfg_hash`·`_sel_cfg_sha` 는 v0.16.2 와 같음. 기본값이 아니면 들어감(그래프·기저 재계산 근거). 기존 `select.island.max_mm` 40 은 **바꾸지 않음**(schema 1 바이트 불변 — O-BG-1) | SR-D-13b 방식 |
| BG-D-42 | **v0.16.2 자동 스터디**(schema 1, paicad seed)는 그대로: `bead_auto.auto_selection`(paicad 경로) 유지, 그 스터디 준비·seed·결과 바이트 불변. 새 스터디의 자동 seed = 그래프(BG-D-20) → `prep/select/auto_selection.json` 의 `schema: "esl/doe_auto_selection/2"`, `source: "graph"`, `hints`(paicad flanks 비교 — 있으면) | D9 |

### 5.3 자동 탐지 준비 변경 (D9)
- BD_GEOM(worker `_geom_select`, schema 2 + auto): plan = `[a_fixed](②)` + `fixed` + (STEP 이 있으면) `extract0 → extract`(**힌트만** — tag 제거). extract 실패·paicad 없음 = 정보 `AUTO_HINT_UNAVAILABLE{step, code}`(seed 와 무관). schema 1 auto 스터디 plan 은 v0.16.2 그대로.
- 힌트 = `AUTO_SLOPE_DIFF{bead, rel}`(AD-D-12 와 같은 비교 — paicad 비드 bottom 면 중심에 가장 가까운 그래프 비드와 사면 폭 비교), 미리 채우지 않음.
- ①② auto 의 **STEP 필수 해제**: `bead_source: auto` + STEP 없음 = 허용(힌트 없음). AD-D-14 의 "auto + STEP 없음 422" 는 schema 2 스터디에서 폐지.

### 5.4 이미 끝난 스터디
- schema 1 스터디: 결과·보고서·받기·미리보기·해시 변경 없음(V-BG-12). DB `selection.derived` 지연 갱신 없음(ALGO 그대로).

### 5.5 설정 키 (`DEFAULTS["select"]["graph"]` = `BeadDoeSelectGraphCfg` = `config/*.example.yaml` 2개 거울, 하드코딩 금지)
```yaml
bead_doe:
  select:
    graph:                          # v0.17.0 BEADGRAPH — 기본값이면 해시 제외(HASH_NEW_KEYS_V0170)
      enabled: true                 # false = 새 스터디도 schema 2 이지만 그래프 계산 안 함(GRAPH_FAILED{code: DISABLED}, elems 비드만)
      feature_angle_deg: 10.0       # BG-D-2 (#53 param feature_angle)
      level_tol_mm: 0.3
      min_floor_area_mm2: 12.0
      root_free_frac: 0.2
      raster_mm: 1.0
      island: {max_mm: 60.0, straddle_frac: 0.15}          # D8
      bead: {max_width_mm: 80.0, prune_k: 2.2, bend_deg: 50.0, width_jump: 0.35, min_zone_mm: 12.0,
             open_ext_mm: 90.0, absorb_len_mm: 60.0}      # absorb_len_mm = D7 짧은 띠 흡수
      morph: {ramp_k: 3.0, outside_tol_mm: 1.0e-6, achieved_tol_mm: 1.0e-6,
              corner: {area_ratio_min: 0.35, shrink: 0.8, iters: 40},
              w_smooth_iters: 3}            # 통합 추가(§12 BG-X-5): W 바깥 방향장 완화 반복(꺾임·연결부 연속, 0 = 끔)
      sym_tol_mm: 0.5               # BG-D-17·21
      limits: {max_elems: 250000, timeout_s: 180, max_raster_px: 4000000}
```
| 위치 | 추가 | 검사 |
|---|---|---|
| `esl/doe/__init__.py` DEFAULTS | `select.graph` 위 그대로 | — |
| `backend/esl_platform/core/config.py` | `BeadDoeSelectGraphCfg`(+ `…IslandCfg`·`…BeadCfg`·`…MorphCfg`·`…CornerCfg`·`…LimitsCfg`): `feature_angle_deg` (0, 45], `level_tol_mm` gt 0, `island.max_mm` gt 0, `straddle_frac` (0, 1), `bend_deg` (0, 180), `width_jump` gt 0, `ramp_k` ≥ 1, `outside_tol_mm` gt 0 ≤ 1e-3, `corner.area_ratio_min` (0, 1), `shrink` (0, 1), `iters` 1..200, `max_elems` 1..2e6, `timeout_s` gt 0, `max_raster_px` ≥ 1e5 | 섹션 없으면 기본 |
| `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml` | 위 yaml 그대로 | — |
| `GET /doe/settings` | `select.graph{enabled, island.max_mm, sym_tol_mm}`, `scenarios.select_auto` = select 가능 ∧ graph.enabled(paicad 무관) | — |
| 패키지 `beadgraph.DEFAULTS` | 분류·모핑 키 같은 값. esl 은 항상 병합 cfg 전체를 넘김(패키지 기본값에 기대지 않음). 두 기본값 일치 = V-BG-14 | 이중 정의 드리프트 방지 |

### 5.6 버전 · migration
- `VERSION` 0.17.0, `CHANGELOG.md`, openapi info.version. migration **없음**: `inputs.select_schema`(JSONB), `selection` JSONB 안 schema 2, 시나리오·CHECK 불변.

## 6. API · 화면 (최소 변경)

### 6.1 API (`/esl/api`)
```
GET  /doe/studies/{sid}/select/graph       → {graph (beadgraph/1 — 편집 적용 전), sha256, edits_applied: null, warnings,
                                              beadgraph_version, rules, morph_rules}
       404 GRAPH_NOT_AVAILABLE (schema 1 스터디·GRAPH_FAILED), 409 PREP_NOT_READY
GET  /doe/studies/{sid}/select/view/graph.bin   (기존 select/view 라우트 허용 파일에 추가 — SELECT_VIEW_FILES)
       = 머리 JSON 길이 L(uint32 LE) + 머리 JSON(L 바이트, ASCII — 키 정렬·공백 없음){n_elems, arrays[{name, offset}]} + int32 LE 배열
         cls·segment·junction_zone·island·floor·tier (요소 순서 = select.bin 요소 순서). offset = **머리 끝(바이트 4 + L)부터 잰 바이트**,
         정렬 채움 없음(배열이 4바이트 정렬이 아닐 수 있음 — 읽기는 DataView). 원본 = esl/doe/bead_graph.py graph_bin(통합 확정 §12 BG-X-7)
POST /doe/studies/{sid}/select/derive      schema 2 수용. 응답 SelectionDerived += graph{sha256, graph_algo, edits_applied{toggle,merge,split},
                                              segments[{id, anchor, type, side, tier, D, entry_width, length, network}],
                                              junction_zones[{id, anchor, reason}], beads[{id, src, segs[anchor], vars, D_nom, W_nom, tier}],
                                              sym_pairs[[anchor, anchor]]}, warnings += BG_*
       409 BG_GRAPH_STALE, 422 BG_GROUP_NOT_CONNECTED·BG_TIE_NOMINAL·BG_SEG_UNKNOWN·BG_EDIT_INVALID·SELECT_SCHEMA_MISMATCH
PUT  /doe/studies/{sid}/selection          schema 검사(BG-D-35), 409 BG_GRAPH_STALE
GET  /doe/studies/{sid}/select/auto        schema 2 스터디 = {selection(schema 2), sha256, source: "graph", hints, warnings}
DoeCheckIn/DoeStudyIn(select)              auto 의 step_upload_id 선택(BG §5.3)
```

### 6.2 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음, 새 화면 없음 — D10)
- **BeadSelectCard / BeadList**: 목록 위 토글 `목록 | 트리`. 목록 행 = 비드(그래프 비드는 아이콘 ⑂ + 구성 세그먼트 수, elems 비드는 지금 그대로). seed 배지·되돌리기·초기화 = AD-D-4 그대로.
- **트리 보기**(신규 컴포넌트 `SegmentTree.tsx`): 바닥 위계(플랜지 → 고리 띠 → 플래토 → 채널·포켓) 아래에 세그먼트(타입·변·D·W), 접합 구역(회색, "변수 없음"), 섬·랜스(아이콘, 크기 mm), 구멍 수. 행 클릭 = 3D 강조, 체크 = 현재 비드에 추가/빼기, 우클릭 메뉴 = [섬으로]/[비드로](D8), [인접과 병합], [네트워크 전체로 묶기]. [대칭 묶기 제안] 버튼 = `sym_pairs` 목록에서 골라 `ties` 추가.
- **3D 보기**: 세그먼트별 색(그래프 모드), 접합 구역 빗금 회색, 섬 기존 섬 색. 클릭 = 그 요소의 세그먼트 선택(칠하기 도구는 elems 비드에서만). [분할] 도구 = 세그먼트 위 한 점 클릭 → `split{anchor, at}`.
- 띠 문구: `GRAPH_FAILED`("자동 분류 실패 — 직접 칠하기(요소 비드)로 계속"), `BG_GRAPH_STALE`.

### 6.3 SelectionDerived 추가 형식 · 판정 셀
- 셀 `warnings` += `BG_SHARED_CHILD`·`BG_CORNER_GUARD`(info)·`BG_RAMP_SHORT`. 실패 코드 `BG_OUTSIDE_MOVED`(FAILED_MESH).
- 보고서 select 절: 그래프 비드는 "세그먼트 n·접합 구역 m·묶음 출처(그래프)" 1줄.

### 6.4 오류·경고 코드 (문구 원본 `resources/doe_messages.json`)

| 코드 | 수준 | 위치 |
|---|---|---|
| `GRAPH_FAILED{code: ERROR\|TIMEOUT\|TOO_LARGE\|DISABLED\|NO_FLOOR}` — 형식은 §12 BG-X-6 `{code: "GRAPH_FAILED", message, detail}` | 경고 | 준비(BG-D-40) |
| `GRAPH_RASTER_COARSE{raster_mm}` | info | 분류(래스터 픽셀 상한으로 해상도 2배 — §7) |
| `AUTO_HINT_UNAVAILABLE{step, code}` | info | 준비(§5.3) |
| `BG_GROUP_NOT_CONNECTED{bead}` · `BG_TIE_NOMINAL{beads}` · `BG_SEG_UNKNOWN{anchor}` · `BG_EDIT_INVALID{edit}` · `SELECT_SCHEMA_MISMATCH` | 422 | derive·저장 |
| `BG_GRAPH_STALE{saved, current}` | 409 | derive·저장 |
| `BG_GROUP_NOMINAL_SPREAD{bead, min, max}` · `BG_SEGMENT_SHORT{bead, length_mm, ramp_mm}` · `BG_RAMP_SHORT{var, L_mm, need_mm}` | 경고 | derive·params |
| `BG_SHARED_CHILD{bead, child, n_nodes}` · `BG_CORNER_GUARD{bead, n_nodes, flank_max_deg}` · `BG_ISLAND_HELD{island}` | info | derive |
| `BG_RANGE_CLAMPED{bead, var, from[lo, hi], to[lo, hi], inverted[lo, hi]}` (통합 추가, §12 BG-X-1) | info | BD_MATRIX params |
| `BG_BASIS_LEAK{var, n, max_mm}` · `BG_ACHIEVED_MISMATCH{var, err_mm}` | 오류 | BD_MATRIX 실패 |
| `BG_OUTSIDE_MOVED{n, max_mm, vars}` | FAILED_MESH | 안 판정 |
| `GRAPH_NOT_AVAILABLE` | 404 | `GET …/select/graph` |

## 7. 성능 한계

| 항목 | 한계(220 000 요소) | 근거 · 장치 |
|---|---|---|
| 분류 `classify` | ≤ 60 s, tracemalloc 최대 ≤ 300 MB(프로세스 RSS 증가 ≤ 600 MB) | H6 104k = 15 s·122 MB → 선형 외삽 32 s·260 MB. DOE_PREP 작업 안(API 요청 아님), `limits.timeout_s` 180 초과 = `GRAPH_FAILED{TIMEOUT}` |
| 요소 상한 | `limits.max_elems` 250 000 초과 = 분류 안 함 `GRAPH_FAILED{TOO_LARGE}` | 큰 B 메시 보호 |
| 래스터 | 바닥별 bbox/`raster_mm` 픽셀 > `max_raster_px` 4e6 이면 그 바닥만 raster_mm × 2(반복, 결정적) + `GRAPH_RASTER_COARSE` | 1200×675 플래토 = 0.81 Mpx(1 mm) |
| derive(schema 2) | ≤ 3 s(그래프·labels 캐시 읽기 + 편집 적용 + 구역 집합) | `derive_timeout_s` 20 안 |
| 기저 | 변수당 ≤ 5 s, 20 변수 ≤ 60 s(조화 확장 = 세그먼트 바닥별 희소 LU 1회 — 같은 바닥 변수끼리 재사용) | BS V-BS-11 기저 30 s 기준을 변수 수 비례로 |
| 기저 메모리 | `_compact` 형식 그대로(지지 노드만) — 20 변수 × 지지 ≤ 30k 노드 ≈ 15 MB | |
| graph.bin · 트리 | 6 × 220k × 4 B = 5.3 MB, 디코드·트리 구성 ≤ 200 ms | 브라우저 |

## 8. 공통 패키지 `beadgraph`

### 8.1 위치 · 구성 (D2)
```
packages/beadgraph/
  pyproject.toml                # name "beadgraph", version = __version__, requires-python ">=3.11",
                                # dependencies ["numpy>=1.26,<3", "scipy>=1.11"], optional [synth] = ["gmsh==<lock 값>", "shapely>=2"]
  README.md                     # API·호환 정책 요약(이 절의 사본 — 원본은 이 계약)
  src/beadgraph/
    __init__.py                 # classify, apply_edits, basis, morph, check, DEFAULTS, SCHEMA="beadgraph/1", RULES, MORPH_RULES, __version__
    topo.py levels.py tree.py skeleton.py      # 분류(H6 시제품 이식)
    absorb.py                   # 접합 구역 흡수·고리 변(BG-D-13)
    edits.py                    # toggle·merge·split(BG-D-37)
    zones.py                    # 구역 Z_F…A_v·J·E(§4.1)
    morph.py                    # D·W 선형 기저, 램프, 코너 가드, hold ψ, 섬 강체(§4.2)
    checks.py                   # outside_moved, achieved, island_residual, inverted_count(넘파이 — esl 품질 지표와 같은 식의 뒤집힘만)
    schema.py                   # beadgraph/1 JSON 스키마 dict + validate(graph)
    testing/                    # 휠에 포함 — physicsai 도 같은 시험을 돌림
      synth_h5.py synth_h6.py   # 생성기(gmsh·shapely 필요 = [synth] extra)
      fixtures/h5.npz h6.npz    # 생성 결과 고정(메시 + 정답 라벨, ≤ 6 MB, savez_compressed) — 시험은 gmsh 없이 이것만 씀
      expected.json             # 픽스처별 graph.json sha256·지표(RULES 별)
      conformance.py            # V-BG-1~7 의 패키지 부분
    __main__.py                 # python -m beadgraph selftest [--json] → 적합성 보고(종료 코드 0/1)
  tests/                        # pytest — conformance 호출 + 단위 시험 + import 순수성 검사
```
- 금지: `esl`·`backend`·`worker`·`paicad`·`physicsai` import, 파일·네트워크 입출력(픽스처 읽기 `testing` 제외), 전역 상태, 난수(필요하면 시드 고정 인자).

### 8.2 API 표면 (안정 — 바꾸면 MAJOR)
```python
classify(nodes, elems, fixed=None, cfg=None) -> tuple[dict, dict[str, np.ndarray]]      # (graph, labels)
apply_edits(graph, labels, edits) -> tuple[dict, dict]                                    # BG-D-37, 결정적
resolve(graph, labels, ref) -> int                                                        # {anchor}|{network} → 세그먼트/네트워크 id, 없으면 KeyError
basis(graph, labels, nodes, beads, ranges, cfg=None, fixed=None) -> list[dict]           # [{name, nominal, idx(int64), vec(float64 n×3), zone(int64), info{…}}]
morph(nodes, basis, values) -> np.ndarray                                                 # x0 + Σ dv·vec
check(graph, labels, nodes, x, basis, values, cfg=None) -> dict                           # {outside{n, max_mm, vars}, achieved{var: err_mm}, island_residual_mm}
validate(graph) -> None                                                                   # 스키마 위반 ValueError
```
- `beads` = `[{name, kind: "D"|"W", segs: [segment id…], hold: 0|1}]`(정규화·묶기·tie 는 호출자 몫 — esl 은 `esl/doe/bead_graph.py`, physicsai 는 자기 쪽).

### 8.3 버전 · 호환 정책
| 변경 | 올림 | 조건 |
|---|---|---|
| API 시그니처·`schema` 주 번호 변경 | **MAJOR**(`beadgraph/2`) | 소비자 둘 다 동시 갱신 |
| 분류 출력 변경(같은 입력·cfg 에서 graph.json 바이트가 달라짐) | **MINOR** + `RULES` +1 | `expected.json` 갱신, esl 은 `BG_GRAPH_STALE` 로 재확인 |
| 모핑 기저 수치 변경 | **MINOR** + `MORPH_RULES` +1 | esl 기저 재계산(BG-D-39) |
| 필드 추가(선택)·새 함수 | MINOR | 소비자는 모르는 필드 무시 |
| 출력 불변 수정(성능·리팩터) | PATCH | 픽스처 sha 바이트 동일 필수 |
- 1.1.0(v0.19.1) = RULES 1·MORPH_RULES 2 — BG-D-47(걸친 섬 바깥 벽 접촉 hold). 분류 출력 불변(labels sha 같음, graph.json 은 머리의 `version`·`morph_rules` 만 바뀜).
- 버전 원본 = `packages/beadgraph/src/beadgraph/__init__.py` `__version__`. v0.17.0 출시 = **beadgraph 1.0.0**(RULES 1, MORPH_RULES 1).
- 배포물: esl-platform 릴리스 때 `beadgraph-<ver>-py3-none-any.whl`(순수 파이썬)을 빌드해 GitHub 릴리스 자산 + 태그 `beadgraph-v<ver>` 로 올리고 sha256 을 릴리스 노트에 적는다.
- **esl 소비**: 저장소 안 경로 설치(루트 `pyproject.toml` dependencies += `beadgraph`(== 같은 판), 개발 = `pip install -e packages/beadgraph`, pytest `pythonpath` += `packages/beadgraph/src`), 오프라인 묶음 = `collect-offline` 이 같은 휠을 빌드해 `wheels/` 에 넣고 `deploy/requirements.lock` 에 `beadgraph==<ver>`.
- **physicsai 소비**: 휠을 `vendor/wheels/` 에 넣고 `beadgraph==<ver> --hash=sha256:<…>` 로 **정확히 고정**(O-BG-3). 포크·사본 수정 금지 — 고칠 것은 esl-platform 이슈(픽스처 첨부)로.
- 두 플랫폼은 산출물(esl: `graph.json`·`basis.json`, physicsai: 자기 결과)에 `beadgraph_version`·`rules`·`morph_rules` 를 기록.

### 8.4 physicsai 가 돌릴 수 있는 시험
- `python -m beadgraph selftest --json` = 픽스처 H5·H6 분류 정확도(V-BG-1·2 기준), 결정성(V-BG-3), 순열·강체 변환 불변(V-BG-4 의 패키지 부분), 모핑 지표(V-BG-5·6), 단차에 걸친 보스(V-BG-19, 1.1.0), import 순수성(V-BG-14). gmsh 불필요. Windows·Linux, Python 3.11/3.12.
- `pytest --pyargs beadgraph.testing`(같은 내용, CI 용).

### 8.5 physicsai 팀 인계 (그대로 전달)
> **beadgraph 1.0.0 — physicsai-platform(paicad) 적용 안내**
> 1. 설치: esl-platform 릴리스 자산 `beadgraph-1.0.0-py3-none-any.whl` 을 `vendor/wheels/` 에 두고 requirements 에 `beadgraph==1.0.0 --hash=sha256:<릴리스 노트 값>`. 의존성 = numpy·scipy 만.
> 2. 호출: 쉘 메시(노드 mm, 0-based 4절점 요소 — 삼각형 4번째 −1, 선택 고정 노드 index)로 `graph, labels = beadgraph.classify(nodes, elems, fixed)`. STEP·B-rep 불필요. 인치면 mm 로 바꿔서.
> 3. 비드 인식: B-rep 인식이 `BEAD_IRREGULAR` 로 버리는 네트워크(고리 + ㅛ 등)를 `graph["segments"]`·`junctions` 로 받는다. 깊이는 부모 바닥 대비 상대값(`rel_depth`), 고리 변은 `side`, 접합 구역은 변수 없음.
> 4. 모핑(쓸 경우): `beadgraph.basis(...)` → `beadgraph.morph(...)` → `beadgraph.check(...)`. `check()["outside"]["max_mm"] > 1e-6` 이면 그 안은 실패로 처리(esl 과 같은 규칙).
> 5. 검증: 설치 직후·CI 에서 `python -m beadgraph selftest` 가 0 으로 끝나야 함.
> 6. 버전: 정확 고정. MINOR 이상 올리면 `rules`/`morph_rules` 가 바뀌어 결과가 달라질 수 있음 — 변경 기록은 esl-platform `CHANGELOG.md` 의 beadgraph 절.
> 7. 고칠 것: 사본을 고치지 말고 esl-platform 이슈에 재현 메시(npz)와 기대 결과를 올림.
> 8. 금지: 패키지 안에서 physicsai 코드 import, 전역 설정 의존.

### 8.6 esl 통합 지점
- 신규 `esl/doe/bead_graph.py`: `prep_graph(mesh, fixed_ids, cfg, out_dir, guard)`(BD_LOADS), `normalize_v2(sel, graph, cfg)`, `derive_v2(mesh, norm, cfg, graph, labels)` → `Derived`(그래프 비드 + elems 비드는 `bead_select._derive_bead` 그대로, 섬 상한 60), `basis_v2(...)` → `bead_select.Basis`, `params_rows_v2`, `auto_seed(graph, labels, cfg)`(BG-D-20), `graph_bin(...)`.
- `bead_select.py`: `SCHEMA_VERSIONS = (1, 2)`, `normalize`·`derive`·`basis`·`params_table`·`design_checks`·`design_state` 에서 schema 2 를 `bead_graph` 로 보냄(schema 1 경로 코드 불변), `HASH_NEW_KEYS_V0170`.
- `esl/morph/core.py`: `outside_moved(x0, x, allowed_masks, changed, tol)` 추가, `checks_arrays`/`checks_from_arrays` 에 `chk_o*`(없으면 키 없음).
- ③ STEP 모핑(보류): `stages._design_mesh` TODO 줄에 "beadgraph.classify → basis" 호출 예약(BG-D-45).

| ID | 결정 | 근거 |
|---|---|---|
| BG-D-43 | 패키지 = **`packages/beadgraph/` 이 저장소 안, 독립 semver, 순수 파이썬 휠** — esl 은 경로 설치, physicsai 는 휠 고정(위) | 원본 1곳 + 소비자 고정 |
| BG-D-44 | 합성 생성기(H5·H6)와 고정 픽스처는 **패키지 `testing/` 에**(휠 포함) — esl `tests/doe` 는 그것을 import | 두 플랫폼이 같은 시험 자료 |
| BG-D-45 | ③ STEP 모핑은 이번 범위 밖, 같은 모듈 사용 예약(SR-D-44 TODO 확장) | 사용자 범위 |
| BG-D-46 | **(v0.18.2, 이슈 #63 ① 진단) 그래프 비드 평면도·단면 자료**: `derive_v2` 문서의 그래프 비드 행에 코어 `plan_data` 가 읽는 `plan{ring_ab, e_ab, label_ab, tiers}`(frame 이 있을 때 — schema 1 `_plan_bead` 와 같은 함수: 윤곽 = 비드 요소 경계 고리, 라벨 = 비드 요소 중심 평균, 단 = `[{k: tier, ring_ab: 바닥(cls 0) 요소 고리}]`)과 `section{s, z, dz_dD, ds_dW, dz_dW, at_node_id: null, at_ab: null}` 를 붙임(`bead_graph._graph_figures`). 단면 = 대표 세그먼트(길이 최대, 같으면 작은 id)의 skeleton 호 길이 중점 접선 ê_L 에 수직인 평면(점 = 그 중점에 가장 가까운 비드 바닥 요소 중심, skeleton 없음 = 비드 요소 중심 평면 주축)과 메시 교선, s = ê_W = n̂0 × ê_L 방향, z = 부모 바닥 level 기준 비드 바닥 쪽 +(깊어짐 +), 범위 = 그 점을 지나는 비드 요소 교선 연속 구간(틈 ≤ 3 h) ± 3 h. **미분은 그림용 기하 근사**(그래프 기저를 풀지 않음 — 실측 H6 104k 요소 `bg.basis` 3.9 s 가 derive 를 0.3 → 4.3 s 로, 현장 267k 요소면 `derive_timeout_s` 20 s 에 가까움): 비드 구간 안 `dz_dD[tier] = clip(z/D_nom, 0, 1)`, W 변수면 `ds_dW = ½·clip((s − s_c)/(½ 바닥 폭), −1, 1)`·`dz_dW = 0`. 그림 자료 계산 실패 = 그 비드 `plan` 빈 값·`section` null(저장·평면도를 막지 않음). DB 요약(`summary(with_figures=False)`, 백엔드 `SUMMARY_DROP`)·기저·판정·`GRAPH_ALGO`·sel 회귀 요약은 그대로 | 평면도 응답 비드 13개 모두 `ring_ab`·`label_ab`·`tiers`·`section` 비어 있음(코어 `plan_data` 는 비드별 plan 을 기대 — `bead_select.py` plan_data, `derive_v2` 가 만들지 않음) |
| BG-D-47 | **(v0.19.1, 이슈 #63 B10_D·B11_D `BG_BASIS_LEAK`) 걸친 섬의 바깥 벽 접촉 노드 hold + 기저 = 검사 단일 노드 규칙**: (1) **노드 규칙 1개** — 변수가 움직여도 되는 노드 = 그 노드를 가진 요소가 **모두** 허용 요소 집합 A_v 안인 노드(바깥 요소와 공유하는 노드 = 0). `beadgraph.zones.movable_nodes(conn, A_v)` 한 함수를 기저(`morph`)와 검사(`checks.strict_allowed_nodes` → BG-D-32 `BG_BASIS_LEAK`·BG-D-34 `BG_OUTSIDE_MOVED`)가 함께 쓴다. A_v 요소 집합은 BG-X-9 대로 두 곳에서 따로 계산(기저 = `bead_zones.allowed_el`, W 는 + 부모 바닥·그 위 비걸침 섬; 검사 = `checks.allowed_elements` 라벨 기반) — 검증 독립성 유지, 픽스처 H5·stepboss 모든 단일 세그먼트 D·W 에서 두 집합 같음(시험). (2) **걸친 섬(BG-D-27) 접촉 = 바닥이든 벽이든 바깥 요소**: 섬 노드 중 `movable_nodes` 밖(남의 바닥 + 접합 구역 단차 벽 등 A_v 밖 벽)인 노드 u = 0, 그 노드를 가진 섬 요소의 노드 = 기존 접촉 띠 smoothstep(d_f/b_s)·u_island(BG-D-27 식 그대로, d_f = 접촉 노드까지 평면 거리). 섬 핵심 강체·채널 쪽 둘레 평균·고정 노드 hold(BG-D-28)는 그대로. (3) 마지막 바깥 0 = `allowed_n ∧ movable_nodes`(구조적 — 노드 규칙이 어긋나는 기저는 만들어지지 않음, A_v 요소 집합이 어긋날 때만 BG-D-32 가 잡음). **접합 구역 자동 포함(후보 B)은 하지 않음**: 단차 벽이 비드와 함께 움직여 의도하지 않은 형상 변화(합성 stepboss 채널 D ±30 %: 단차 벽 최대 3.90 mm 이동, 뒤집힘 22, 단일 세그먼트 포켓 D 는 여전히 누출). 출력 변화 = 걸친 섬이 A_v 밖 벽에 닿는 변수만(그 밖 H5·H6 모든 단일 세그먼트 D·W 기저·레시피 (a)~(g) 결과 바이트 동일) — 패키지 **1.1.0·`MORPH_RULES` 2**(§8.3, esl 기저 1회 재계산). 새 설정 키 없음 | 현장: B10(단일 channel seg 21, D 9.548) 끝 단차에 걸친 보스 섬 26·50 의 테두리 노드 30개가 접합 구역 30·36·50 벽과만 공유 — 검사는 바깥, 기저는 강체 이동(최대 0.762), B11_D 28개·0.773. 기저(바닥 접촉만 hold)와 검사(모든 바깥 요소)가 따로 판정하던 구조 결함 |

## 9. 시험 (V-BG-*)

**합성 자료**: `beadgraph.testing.synth_h5`(고리 ㅁ + 고리 아래에 T 로 붙은 세로 비드 2개, gmsh OCC, h 3, 15 280 요소)·`synth_h6`(이슈 #63 근사 샤시, 104 439 요소, 정답 라벨)·`synth_stepboss`(v0.19.1 BG-D-47: 300×200 판, 깊이 12 채널이 깊이 6 영역으로 끝나는 6 mm 단차(접합 구역 벽)에 걸친 보스 2개, 7 949 요소). 생성 결과는 `fixtures/*.npz` 로 고정. 생성기 재현 시험(gmsh 가 lock 판과 같을 때만, 아니면 skip) = 재생성 메시 sha = 픽스처 sha.

| ID | 시험 | 위치 |
|---|---|---|
| V-BG-1 | **H6 분류 정확도**(전체 요소, 정답 대비): 요소 class 정확도 ≥ **99.0 %**(floor/wall/island/lance 재현율·정밀도 각각 ≥ 98.5 %), 바닥 identity ≥ 99.5 %, 벽 소유 ≥ 98.5 %, tier ≥ 99.5 %, 세그먼트 라벨(접합 10 mm 밖) ≥ 98.5 %; **세그먼트 23/23(IoU ≥ 0.5) = 100 %**, 남는 것은 `spur` → 접합 구역(변수 0); **접합 16/16 = 100 %**(T 4·L 2·W 4·Y 2·step 4, 종류 일치); 섬 97/97·랜스 16/16·걸침 4/4·구멍 78/78·고정 구멍 78/78·랜스 슬롯 16/16 | `packages/beadgraph/tests/test_h6.py` |
| V-BG-2 | **H5 분류**: 고리 4변(side 4종) + 세로 비드 2개 + T 2개, 세로 비드 위 고리 표지 벽 0(누수 없음), 접합 구역 = 코너 4 + T 2 | `packages/beadgraph/tests/test_h5.py` |
| V-BG-3 | **결정성**: 같은 입력 2회 → graph.json·labels 바이트 동일, `expected.json` sha 와 같음 | 같은 폴더 `test_determinism.py` |
| V-BG-4 | **메시 출처 무관**(SR-D-44): H5·H6 각각 (a) 메모리 메시, (b) `.rad` + `#include .inc` 왕복(esl 리더), (c) 노드·요소 번호 재부여 + 요소 순서 섞음 + 요소 노드 순환(시작점 이동·방향 뒤집기), (d) 강체 변환(임의 축 회전 + 평행 이동), (e) H5 gmsh STEP 메시 ↔ .rad 왕복 → 요소 대응 매핑 후 labels 동일, 세그먼트·접합·섬 수·종류·앵커 대응 동일, 기저 벡터 = 회전 역변환 후 ± 1e-9, 안 판정·경고 코드 동일 | `packages/beadgraph/tests/test_invariance.py`(a,c,d), `tests/doe/test_bead_graph_source.py`(b,e — esl 리더 필요) |
| V-BG-5 | **모핑 지표 H6**(레시피 (a) 플래토 +2, (b) ch1 D +2, (c) ch1 W +3, (d) 포켓 C D +2 코너 가드, (e) ch1+ch2 대칭 묶음 −2, (f) 고리 위 변 D +2, (g) 고리 네트워크 D +2): 모두 **뒤집힘 0**; **바깥 max\|u\| ≤ 1e-9 mm**(허용 구역 A_v 밖 — W 는 블렌딩 띠 포함); **달성 D = 목표 ± 1e-6 mm**(달성 노드 ≥ 1, (b) 에서 보스 주변 미달 패치 없음 — 달성 노드 비율 ≥ 90 %), W = 목표 ± 1e-3; 섬 잔차 ≤ 1e-9; 고정 노드 이동 ≤ 1e-12(hold 1); 걸친 보스 윗면 변위 = 채널 ΔD ± 1e-9(D6); (f) 플래토 0 이동 + `BG_SHARED_CHILD`; (a)(g) 자손 강체(노드 쌍 거리 불변 1e-9); (d) `BG_CORNER_GUARD` | `packages/beadgraph/tests/test_morph_h6.py` + `tests/doe/test_bead_graph_morph.py`(esl Basis·design_state 경유) |
| V-BG-6 | **H5 레시피**: V1 D ±2·W +4·D 기본 범위 끝 → 고리 노드·고리∩V1·V2 이동 **0**(현 esl A = 1.65~2.00), 뒤집힘 0, 중간 깊이 = 목표 정확, 새 요소 aspect > 10 없음(H5 C D−2 조각 미재현), 램프 L = max(3·ΔD_ext, 3h) | `packages/beadgraph/tests/test_morph_h5.py` |
| V-BG-7 | **바깥 0 강제**: 기저에 의도적 누수 주입(monkeypatch) → `BG_BASIS_LEAK`; 안 좌표에 바깥 노드 1e-3 mm 주입 → FAILED_MESH `BG_OUTSIDE_MOVED`(판정 순서: 뒤집힘 다음), 1e-7 주입 → 통과 | `tests/doe/test_bead_graph_morph.py` |
| V-BG-8 | **선형성·고정 램프**: 범위 양 끝·중간 안 = 패키지 직접 계산(비선형 기준식 — 그 값에서 L 을 다시 정한 결과)과 기본 범위 안에서 ± 1e-9 동일(ΔD_ext 에서), 사용자 범위가 기본 끝을 넘으면 `BG_RAMP_SHORT`, 세그먼트 < 2L 이면 `BG_SEGMENT_SHORT`·`use_default false` | 같은 파일 |
| V-BG-9 | **편집**: H6 에서 엠보스(섬) → 비드 전환 = 새 세그먼트 D 변수, 채널 → 섬 전환 = 강체(변수 0), 병합(ch1 + flare) = 세그먼트 1·사이 Y 구역 흡수, 분할(ch1 중점) = 세그먼트 2 + `split` 구역; 같은 편집 2회 바이트 동일; RULES 모의 상승(cfg 바꿔 sha 변경) → `BG_GRAPH_STALE`, 앵커 재해석 성공·실패(`BG_SEG_UNKNOWN`) | `packages/beadgraph/tests/test_edits.py`, `tests/doe/test_bead_graph_select.py` |
| V-BG-10 | **자동 seed**(H6): 비드 = 고리 4변(top·bottom·left·right 각 1) + 다리 4 + 채널 2(각각, 나팔 포함) + 포켓들 + 플래토(D 만), 코너·짧은 띠·spur 변수 없음, `ties` 없음·`sym_pairs` ⊇ {ch1, ch2}, 결정적 바이트, seed 그대로 저장 sha = 같은 선택 수동 저장 sha | `tests/doe/test_bead_graph_select.py` |
| V-BG-11 | **schema 2 elems 비드**: schema 1 비드 본문을 `src: elems` 로 넣은 schema 2 → derive·기저 = schema 1 결과와 바이트 동일(섬 상한만 60 — 40 ~ 60 섬 없는 합성에서), 그래프 비드와 요소 겹침 422 | 같은 파일 |
| V-BG-12 | **schema 1 회귀(바이트)**: 기존 시험 전부 통과 — V-BS-*, V-SR-1~28(V-SR-1 픽스처 바이트), V-AD-1~15, 어려운 사례 **H1~H4**(상태·코드·수치 그대로), **실 사례 7건**(`tests/doe/test_bead_select_real.py`·`test_bead_select_relax.py` 고정값), 기본 설정 `_cfg_hash`·`_sel_cfg_sha` = v0.16.2 상수, `ALGO`·`RULES` = 3, schema 1 준비 재실행 산출물에 graph 파일 없음 | `tests/doe/*`, `worker/tests/test_doe_select_relax_jobs.py` |
| V-BG-13 | **성능(slow, perf)**: 220k 요소 합성(H6 h 2.1 재생성 픽스처 또는 H6 2× 타일) — classify ≤ 60 s·tracemalloc ≤ 300 MB, derive(schema 2) ≤ 3 s, 기저 20 변수 ≤ 60 s, 250 001 요소 → `GRAPH_FAILED{TOO_LARGE}` | `tests/doe/test_bead_graph_perf.py` |
| V-BG-14 | **패키지 순수성·호환**: 패키지 모듈 import = 표준 라이브러리·numpy·scipy 뿐(AST 검사), `beadgraph.DEFAULTS` 의 분류·모핑 키 = esl `DEFAULTS["select"]["graph"]` 같은 값, `validate(graph)` 통과, `schema` 주 번호 다른 문서 거부, `python -m beadgraph selftest` 종료 0 | `packages/beadgraph/tests/test_purity.py`, `tests/doe/test_bead_graph_cfg.py` |
| V-BG-15 | **API**: graph·graph.bin(머리·배열 길이·요소 순서 = select.bin), 404 `GRAPH_NOT_AVAILABLE`·409 `PREP_NOT_READY`·`BG_GRAPH_STALE`, 422 코드 5종, schema 혼용 422, auto + STEP 없음 허용(schema 2), settings `select.graph`·`select_auto`(paicad 무관), 설정 pydantic 검사 | `backend/tests/test_doe_select_graph_api.py` |
| V-BG-16 | **워커 E2E**: ① case·② mesh 각각 schema 2 auto → seed 편집(병합·전환·tie) → 저장 → 미리보기 → 실행 — `BG_OUTSIDE_MOVED` 없음, 결과·순위·보고서 생성, 같은 선택 수동 스터디와 결과 바이트 동일(AD-X-2 예외 동일 적용), `GRAPH_FAILED` 주입 시 준비 READY + elems 비드로 실행 | `worker/tests/test_doe_select_graph_e2e.py` |
| V-BG-17 | **화면**: 목록/트리 토글, 트리 노드 종류 표시, 섬↔비드·병합·분할·대칭 묶기 → 요청 본문, 3D 세그먼트 클릭 선택, `GRAPH_FAILED`·`BG_GRAPH_STALE` 띠, 2560·1920 잘림 없음, 220k graph.bin 디코드 ≤ 200 ms | `frontend/src/__tests__/doe_select_graph.test.tsx`, `src/__tests__/select_graph_bin.test.ts`, mock |
| V-BG-18 | (v0.18.2 BG-D-46) 그래프 방식 plan-view: H6 auto seed 비드마다 `ring_ab`(고리 ≥ 3 점)·`label_ab`·`tiers[0].k = tier`·`section`(s·z ≥ 5 점, 바닥 z ≈ D_nom, `dz_dD[tier]` 0..1, W 변수면 `ds_dW` ±½) 비어 있지 않음, `DoePlanOut` 검증, DB 요약에 plan·section 없음 | `tests/doe/test_bead_graph_select.py::test_graph_plan_view_fields_filled`, 화면 `frontend/scripts/screenshots-v0182.mjs`(1920·2560) |
| V-BG-19 | (v0.19.1 BG-D-47) **단차에 걸친 보스**(stepboss): 수정 전 규칙(기저 노드 규칙 끔)으로 단일 세그먼트 D 4개 모두 `BG_BASIS_LEAK` 재현(채널 13노드·0.559 mm), 수정 후 모든 단일 세그먼트 D + 채널 W 기본 범위 끝(±30 %) 누출 0·바깥 0·접합 구역 단차 벽 이동 0·보스 윗면 강체(편차 ≤ 1e-9); 기저·검사 공용 `movable_nodes` 와 A_v 요소 집합 일치(H5·stepboss); 생성기 재현(gmsh 4.15.2, 요소 순서 무관) | `packages/beadgraph/tests/test_stepboss.py`, selftest `V-BG-19`, `tests/doe/test_bead_graph_verifier.py::test_step_straddling_boss_no_leak` |
| V-BG-R1 | **실기**: 실 Ch/R 와 이슈 #63 실제 부품 메시 — 세그먼트·접합 수, 자동 seed 비드 수, paicad 가 버리던 네트워크 인식 여부, 변수별 기본 범위 끝 안 판정(뒤집힘·바깥 이동 0), 분류 시간·메모리 | `docs/manual/bead_doe_check.md` 절 추가 |

## 10. 열린 항목 · 리스크

### 10.1 열린 항목 (사용자 결정 필요 — 권장안을 기본값으로 작성)

| ID | 항목 | 권장안(현재 계약 값) | 다른 답이면 |
|---|---|---|---|
| O-BG-1 | **D8 의 60 을 schema 1(기존 v0.16.x select 스터디)에도 적용?** `select.island.max_mm` 40 → 60 이면 40~60 mm 섬이 있는 기존 스터디의 derive·기저·sha 가 바뀜 | **적용 안 함**: 그래프 경로·schema 2 elems 비드만 60, schema 1 은 40(바이트 불변) | `select.island.max_mm` 기본 60 + 기존 스터디 기저 재계산(ALGO 3→4, V-BG-12 기대값 갱신) |
| O-BG-2 | **공유 자식이 있는 세그먼트 D**(예: 고리 위 변만 깊이 변경 — 플래토가 4변에 모두 닿음) | **허용 + 정보**: 플래토 제자리, 그 변의 플래토 벽이 높이 차를 흡수(BG-D-23, `BG_SHARED_CHILD`) | (b) 금지: 공유 자식이 있으면 변 D 를 끄고 네트워크 D 만 허용 |
| O-BG-3 | **physicsai 소비 방식** | **휠 정확 고정 + vendor**(`beadgraph==1.0.0 --hash`, §8.3) | (b) physicsai 저장소에 git subtree/서브모듈로 `packages/beadgraph` 사본 — 갱신 쉬움, 고정·검증 약함 |

### 10.2 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-BG-1 | 실 부품에서 분류 오류(바닥이 10° 넘게 기운 드래프트, 곡면 바닥, 평평하지 않은 뿌리) | `src: elems` 비드로 직접 칠하기, `GRAPH_FAILED{NO_FLOOR}`, feature angle 설정, V-BG-R1 |
| R-BG-2 | 1 mm 래스터로 폭 < 4 mm 좁은 비드의 골격 불안정 | `raster_mm` 설정, 좁은 바닥은 `area` 세그먼트 1개로(골격 실패 시 대체), 시험 자료에 폭 8 mm 비드 포함 |
| R-BG-3 | 고정 램프·코너 가드(기본 범위 끝 기준)로 사용자가 범위를 넓히면 램프가 3·ΔD 보다 짧음 | `BG_RAMP_SHORT` 경고, 최소 3h 유지, `range_check`(SR-D-33) 가 뒤집힘 끝을 알림 |
| R-BG-4 | 공유 자식 벽이 한 변에서만 늘어나 품질 저하 | `BG_SHARED_CHILD`, SR-D-40 극단값 경고, O-BG-2 |
| R-BG-5 | 걸친 보스 접촉 띠(남의 바닥 쪽)가 큰 ΔD 에서 찌그러짐 | 띠 폭 ≥ h, SR-D-37 피처 왜곡 검사(섬 rim/interior), V-BG-5 |
| R-BG-6 | 보스 둘레 도랑 오분류(H6 46 + 21 요소)로 W 변경 시 도랑이 보스와 같이 움직이지 않음 | BG-D-8(D 는 같은 변위), W 블렌딩 안이면 조화 확장이 흡수, 다음 RULES 에서 도랑 규칙 개선 |
| R-BG-7 | DEFAULTS 이중 정의(esl·패키지) 드리프트 | esl 은 항상 전체 cfg 전달, V-BG-14 일치 시험 |
| R-BG-8 | physicsai 버전 어긋남 → 같은 메시에서 다른 그래프 | 정확 고정, 산출물에 version·rules 기록, selftest |
| R-BG-9 | RULES 상승 때 저장된 선택 재확인 부담 | 앵커 참조로 자동 재해석, `BG_GRAPH_STALE` 띠, 해석 실패만 사용자에게 |
| R-BG-10 | 220k 이상 큰 B 메시에서 준비 시간 증가 | 작업 안 계산·상한·`GRAPH_FAILED{TIMEOUT}` 시 elems 비드로 계속 |
| R-BG-11 | H6 픽스처 크기(≤ 6 MB)로 저장소·휠 증가 | savez_compressed, 좌표 float64 유지(결정성), 6 MB 넘으면 시험 실패로 알림 |

## 11. 파일 소유권 · 작업 분해 (겹침 없음)

| 담당 | 파일(소유) | 시험 |
|---|---|---|
| **Impl-Core** (패키지 + esl 통합) | 신규 `packages/beadgraph/**`(pyproject·src·testing·tests 전부); 신규 `esl/doe/bead_graph.py`; `esl/doe/bead_select.py`(schema 2 분기·`SCHEMA_VERSIONS`·`HASH_NEW_KEYS_V0170`·`var_name` k 없음 사용 — schema 1 코드 불변); `esl/doe/bead_auto.py`(schema 2 seed 연결·paicad 힌트 `AUTO_SLOPE_DIFF` — paicad seed 경로 불변); `esl/morph/core.py`(`outside_moved`·`chk_o*`); `esl/doe/stages.py`(BD_LOADS 그래프 단계·auto seed 출처·basis/판정 schema 2 분기·`graph_algo` 재사용 조건·`grid_manifest.graph_rules`); `esl/doe/paicad_io.py`(힌트 읽기만); `esl/doe/report_doe.py`; `esl/doe/__init__.py`(DEFAULTS `select.graph`); `resources/doe_messages.json`; 루트 `pyproject.toml`(beadgraph 의존·pytest pythonpath); `tests/doe/*`(신규 `test_bead_graph_*.py`) | V-BG-1~14 |
| **Impl-Backend** (`backend/**`, `worker/**`, `config/*.yaml`, `deploy/**`) | `backend/esl_platform/core/config.py`(`BeadDoeSelectGraphCfg` 등·settings 거울·`select_auto`); `api/schemas.py`(SelectionIn v2·SelectionDerived.graph·graph 응답·DoeCheckIn auto STEP 선택); `api/services/doe_select.py`(graph 응답·`SELECT_VIEW_FILES` += graph.bin·schema/stale 검사); `api/services/doe.py`(검사 분기·`inputs.select_schema`·settings); `api/routers/doe.py`(`GET …/select/graph`); `worker/esl_worker/doe_jobs.py`(`_geom_select` schema 2 plan — tag 제거·힌트); `worker/esl_worker/register.py`(준비 요약 graph 상태·`GRAPH_FAILED`); `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`; `deploy/requirements.lock`·`deploy/collect-offline.ps1`·`deploy/collect-offline.sh`(beadgraph 휠 빌드·묶음); `requirements-platform.txt`; `backend/tests/*`·`worker/tests/*` | V-BG-12(워커 부분)·15·16 |
| **Impl-Frontend** (`frontend/**`) | `src/components/BeadSelectCard.tsx`·`BeadList.tsx`(목록/트리 토글·그래프 비드 행); 신규 `src/components/SegmentTree.tsx`; 신규 `src/view3d/select/graph.ts`(graph.bin 디코드·세그먼트 선택·색); `src/view3d/select/layers.ts`(schema 2 상태·`toSelectionIn` v2·seed 기준); `src/view3d/select/view.ts`(세그먼트 색·분할 도구); `src/components/DoeInputs.tsx`(auto STEP 선택 표시); `src/api/types.ts`·`src/api/doe.ts`(`getSelectGraph`); `src/mock/doedata.ts`·`src/mock/server.ts`; `src/__tests__/*`(신규 `doe_select_graph.test.tsx`·`select_graph_bin.test.ts`) | V-BG-17 |

- 순서: Core(패키지 `classify`·`apply_edits`·`basis` 시그니처 + `bead_graph` 함수 시그니처 먼저, §8.2 고정) ∥ Backend(스키마·graph.bin 형식은 §2.5·§6.1 고정) ∥ Frontend(mock) → 통합 E2E(V-BG-16) → 실기(V-BG-R1).
- 공동 수정 금지: `stages.py`·`bead_select.py`·`packages/beadgraph/**` = Core 단독, `schemas.py`·`config.py`·`config/*.yaml` = Backend 단독, `types.ts` = Frontend(Backend 스키마 거울). `VERSION`·`CHANGELOG.md`·`docs/**` = 통합 담당(어느 Impl 도 아님).

## 12. 통합 결정 · 수용한 편차 (v0.17.0 통합, 2026-11-10)

Impl-Core·Backend·Frontend 병합 때 계약 본문과 다르게(또는 본문에 없이) 들어간 규칙을 **수용**하고 여기 고정한다. 본문과 충돌하면 이 절이 우선.

| ID | 규칙 | 계약 본문 대비 | 근거 · 위치 |
|---|---|---|---|
| BG-X-1 | **그래프 W 기본 범위 = 뒤집힘 없는 범위로 줄임**: schema 2 BD_MATRIX 에서 `range_check`(SR-D-33)가 그래프 비드(`src: graph`) **W** 변수의 기본 범위 끝 뒤집힘을 찾으면, 기본 범위(`default_range`)를 그 `usable` 로 줄이고 그 비드의 `SELECT_RANGE_INVERTS` 를 정보 `BG_RANGE_CLAMPED{bead, var, from, to, inverted, level info}` 로 바꾼다. 기저·램프 L(원래 기본 범위 끝에서 고정 — BG-D-24)·`feasible` 은 그대로. usable 이 공칭을 품지 못하면 줄이지 않고 `SELECT_RANGE_INVERTS` 유지. D 변수·elems 비드·**schema 1 은 손대지 않음(바이트 불변)**. 줄인 범위는 첫 BD_MATRIX 뒤 `select/<sha12>/params.json` 부터 보임(API derive 의 params 는 기저 전이라 원래 범위) | BG-D-22 "기본 범위 = `select.range` 그대로" 의 예외 | H6 auto seed: 포켓 W(±15 mm) 위 끝 뒤집힘 118~144 요소, 채널 W −20 % 끝 19~52 요소 → 줄인 범위로 다시 점검하면 뒤집힘 0. `esl/doe/bead_graph.py` `clamp_w_ranges`, `tests/doe/test_bead_graph_morph.py` |
| BG-X-2 | **둘러싸인 바닥 수준 판 = 뿌리**: 뿌리 수준(± `level_tol_mm`)인 바닥 조각 중 평면 크기(PCA 장축) > `island.max_mm`(60) 인 것은 `root_group` 에 넣는다(비드 네트워크에 둘러싸여 바깥 자유 모서리가 없어도). 섬으로 전환(`toggle as island`)한 조각은 제외 | §2.1 뿌리 정의(바깥 고리 자유 모서리 비율)에 추가 | H5 고리 안쪽 판이 고리 바닥의 솟은 자식이 되면 고리 사면을 판이 소유해 고리가 W 를 잃음. `beadgraph/classify.py` `_base_level_plates` |
| BG-X-3 | **W 는 입구 선이 양쪽 모두 있을 때만**: 세그먼트 `entry_width` = 골격 양쪽(side ±) 에 입구 노드가 각각 ≥ 3 일 때만 계산, 아니면 null → 그 세그먼트(묶음에 하나라도 있으면 그 비드)는 **D 만**. 안쪽에 플래토가 있는 고리 변(안쪽 입구가 부모 바닥이 아님)은 D 만 | BG-D-16 "ring 변·leg·… 는 W" 를 좁힘 | 한쪽 입구만으로 정한 폭은 BG-D-30 의 대칭 평행 이동과 맞지 않음. `beadgraph/absorb.py`, `esl/doe/bead_graph.py` `_possible_vars` |
| BG-X-4 | **기저·분할에는 요소 연결이 필요**: `beadgraph.basis(…, elems=)`·`check(…, elems=)` 는 `elems` 필수(없으면 ValueError), `apply_edits` 의 `split` 은 `nodes`·`elems` 필수(없으면 `BG_EDIT_INVALID`). §8.2 시그니처에 키워드 인자 `elems=None`(·`nodes=None`) 추가 — 소비자는 `classify` 에 준 같은 배열을 넘긴다 | §8.2 API 표면 확장(MINOR 범위 — 키워드 추가) | 연결 없이 노드만으로는 벽·바닥 구역과 분할 위치를 정할 수 없음. physicsai 인계(§8.5 4)에도 같은 인자 |
| BG-X-5 | **설정 키 `select.graph.morph.w_smooth_iters` = 3**(코어 구현 키): W 바깥 방향장(골격 법선)을 W 이동 노드 사이 모서리로 Jacobi 평균 3회 — 꺾임·연결부에서 연속, 곧은 구간은 수직 그대로(W 정확). 0 = 끔. pydantic `BeadDoeSelectGraphMorphCfg.w_smooth_iters`(0..200)·예시 yaml 2개·`beadgraph.DEFAULTS` 거울, 해시는 다른 graph 키와 같음(`HASH_NEW_KEYS_V0170` — 기본값이면 제외). 화면 설정에는 노출 안 함 | §5.5 키 추가 | `beadgraph/morph.py` `_smooth_dirs` |
| BG-X-6 | **`GRAPH_FAILED` 경고 형식 하나**: 코어·워커·화면 모두 `{code: "GRAPH_FAILED", message, detail}`(detail = ERROR\|TIMEOUT\|TOO_LARGE\|DISABLED\|NO_FLOOR) — `AUTO_DETECT_FAILED{…, detail}` 와 같은 꼴. 코어는 `prep/input.json` `warnings` 에 이 dict 1개 + `graph.code`, 워커는 `graph.code` → 그 경고 detail → ERROR 순으로 읽어 준비 경고 1개, 화면은 `detail` 만 읽음. 옛 문자열 `GRAPH_FAILED: code=…`·`reason`·`graph_code` 키는 읽지 않음 | §6.4 `GRAPH_FAILED{code}` 의 필드 이름 확정 | 세 층이 서로 다른 키를 읽던 것을 통합 |
| BG-X-7 | **graph.bin offset = 머리 끝(4 + L) 기준, 채움 없음**(§6.1 갱신) — 화면 파서는 이 규칙 하나만(파일 시작 기준 추정 제거) | §6.1 확정 | 코어 `graph_bin`·`read_graph_bin` 그대로. 화면 시험에 코어 바이트 고정값 |
| BG-X-8 | **설치**: `deploy/requirements.lock` 의 `beadgraph==<ver>` 는 인덱스 설치 목록에서 빼고(`Get-EslLockPackages` → `Local`), `Install-EslBeadgraph` 가 저장소 설치(`setup.ps1`·`update-repo.ps1` = `pip install --no-deps packages\beadgraph`)·오프라인 묶음(`install.ps1`·`update.ps1` = `wheels\beadgraph-<ver>-py3-none-any.whl`)에서 설치하고 판을 대조 | §8.3 esl 소비 보강 | 사내 인덱스에 beadgraph 가 없어 lock 그대로 `pip install` 하면 비드 DOE 의존성 설치 전체가 실패 |
| BG-X-9 | **바깥 0 점검 = 그래프 라벨로 정한 허용 구역(기저 구역과 독립)**: BG-D-32 `BG_BASIS_LEAK`·BG-D-34 `BG_OUTSIDE_MOVED` 의 허용 집합 A_v 는 `beadgraph.checks.allowed_elements`(세그먼트 라벨 ∈ S, 접합 구역(묶음 사이·네트워크), 배타 자식 = `segments[].children` 이 모두 S 인 자식 부분 트리 + 형제 step 벽, 공유 자식 벽 중 가장 가까운 F 바닥이 S 인 쪽, 소유·걸친 섬, W 는 + 부모 바닥·그 위 비걸침 섬)로 계산하고, **노드는 그 노드를 가진 요소가 모두 A_v 일 때만 허용**(바깥 요소와 공유하는 노드 = 바깥). esl `design_checks_v2` 의 `chk_o*` = 이 노드 집합(묶음 = 구성 변수 합). `zones.bead_zones`: 공유 자식 벽 노드(Z_SC) 중 그 벽의 나머지(이웃 세그먼트 소유)·남의 바닥 요소와 공유하는 노드는 J(Dirichlet 0·램프 원점) — 공유 자식 자기 바닥은 J 원점 아님 | BG-D-32·34 "zone(v)" 을 기저 구역에서 라벨 구역으로 | Verifier: H6 고리 left/right D 에서 이웃 세그먼트(11, 전이 7) 벽 노드 2개가 0.13~0.15 mm 움직이고 READY(같은 구역으로 기저를 만들고 점검해 못 잡음). 수정 후 H6·H5 모든 단일 세그먼트 D·W·네트워크 D 바깥 max 0. `packages/beadgraph/tests/test_outside_strict.py`, `tests/doe/test_bead_graph_verifier.py` |
| BG-X-10 | **혼합 선택(graph + elems 비드)의 바깥 이동 판정**: 그래프 변수가 하나라도 있으면 elems 변수도 `chk_o*` 항목을 가짐(허용 = 그 변수 기저 지지 노드) → 두 종류를 함께 바꾼 안은 합집합으로 판정(가짜 `BG_OUTSIDE_MOVED` 없음). elems 비드만인 schema 2 = 항목 없음(바이트 그대로) | BG-D-34 의 V' 에 elems 변수 포함 | Verifier: 혼합 안 FAILED_MESH n 49·1.8 mm. `tests/doe/test_bead_graph_verifier.py::test_mixed_graph_and_elems_selection` |
| BG-X-11 | **BG-X-1 을 첫 행렬 전에**: BD_LOADS 가 `prep/select/w_clamp.json`(`esl/bg_w_clamp/1` — 그래프 sha·select 설정 sha·후보 = W 가능 세그먼트 각각 + 자동 seed W 묶음, 기본 범위 끝 뒤집힘이면 `range.check_steps` 이분으로 찾은 usable, 공칭 쪽으로 1e-4 반올림)을 쓰고, derive(API·BD_MATRIX 같음)가 일치하는 그래프 비드(같은 세그먼트 [앵커, 요소 수]·hold 1·같은 기본 범위, toggle 편집·fixed_user·exclude 없음)의 **W 기본 범위와 뒤집힌 쪽 feasible** 을 줄이고 `BG_RANGE_CLAMPED`(info). 묶음(ties) = 대표 범위를 구성원 공통 Δ 로. 기저 램프는 원래 기본 범위(`range_basis`)에 고정. 표가 없거나 맞지 않으면 BD_MATRIX `clamp_w_ranges`(BG-X-1) 그대로. schema 1 = 파일·키 없음(바이트 불변) | BG-X-1 "첫 BD_MATRIX 뒤부터" 를 "준비 직후부터" 로 | Verifier: 첫 행렬(API 기본 범위)에 뒤집히는 W 안. H6 자동 seed W 31 안: 표 없음 30 뒤집힘 → 표 있음 0. `tests/doe/test_bead_graph_verifier.py::test_h6_first_matrix_has_no_inverting_w_design` |
| BG-X-12 | **패키지 API 오류 = `BeadgraphError(code, detail)`**(§8.2): 공개 함수(`classify`·`apply_edits`·`resolve`·`basis`·`morph`·`check`)가 입력 검사 `INVALID_INPUT`(detail 앞 `EMPTY_MESH`·`NON_FINITE`·`BAD_SHAPE`·`BAD_INDEX`·`BAD_FIXED`), 그 밖 내부 예외 = `ERROR`("<형식>: <문구>", 원 예외는 `__cause__`). `EditError` 는 `BeadgraphError` 하위(코드 `BG_EDIT_INVALID`), 모르는 앵커는 계속 `KeyError`, `validate` 는 `ValueError`. `BeadgraphError` 는 `ValueError` 하위(기존 호출자 그대로). esl `prep_graph` = 목록 밖 코드는 `GRAPH_FAILED{ERROR}` + `error` 에 원 문구 | §8.2 오류 형식 확정 | Verifier: 빈 메시 IndexError, NaN LinAlgError, 잘못된 index ValueError. `packages/beadgraph/tests/test_api_errors.py` |
| BG-X-13 | **분할 좌표 = 코어 평면**: 화면 `planXY` = (p·e1 − origin[0], p·e2 − origin[1])(`frame.origin`, 없으면 [0, 0]) — 코어 `zones.Mesh.P`·`edits._split` 과 같은 식 | §6.2 [분할] 도구 좌표 확정 | Verifier: H6 에서 화면이 (434.8, 491.1)을 보냄(코어 기대 (−164.9, 150.3)). `frontend/src/__tests__/select_graph_bin.test.ts`(코어 값 고정), `tests/doe/test_bead_graph_verifier.py::test_split_round_trip` |

### Verifier fixes (2026-11-10)

v0.17.0 Verifier 지적 8건의 처리. High 3·Med 3 = 위 BG-X-9~13 + BG-X-8 보강, Low 2 = 시험·화면.

| 지적 | 수정 | 시험 |
|---|---|---|
| H1 바깥 0 점검이 순환 | BG-X-9 | `test_outside_strict.py`(H6 고리 left/right D 바깥 max ≤ 1e-6, 독립성, H5·H6 전 변수), `test_bead_graph_verifier.py` |
| H2 혼합 선택 가짜 실패 | BG-X-10 | `test_mixed_graph_and_elems_selection` |
| H3 분할 좌표 origin 누락 | BG-X-13 | vitest `분할 평면 좌표`, `test_split_round_trip`·`test_split_plane_matches_vitest_constants` |
| M4 BG-X-1 이 첫 행렬에 없음 | BG-X-11 | `test_h6_first_matrix_has_no_inverting_w_design`, `test_w_clamp_not_applied_when_it_does_not_match` |
| M5 시연 저장소 설치 실패 | `deploy/demo/demo-python.ps1` 이 `install-common.ps1` 의 `Get-EslLockPackages`(Core + BeadDoe)만 pip, beadgraph 는 `Install-EslBeadgraph`(저장소 `-Repo` / 묶음 `-Wheels`) — BG-X-8 과 같은 규칙 | `tests/deploy/test_bead_doe_deploy.py::test_demo_venv_installs_beadgraph_like_setup` |
| M6 패키지 원시 예외 | BG-X-12 | `test_api_errors.py` |
| L7 V-BG-16 범위 | ① auto seed → 네트워크 묶기·분할·전환 + ties → 저장·미리보기·실행 = 같은 선택 수동 스터디 순위, ② mesh(B 메시) 그래프 선택 실행 | `worker/tests/test_doe_select_graph_jobs.py::test_e2e_case_edits_ties_and_mesh_base` |
| L8 화면 | 제목 칸 한 줄(`.field.doe-title`, 최대 34rem — 예시 문구 잘림 없음), `GRAPH_FAILED` 는 ② 띠 한 곳(준비 경고 목록에서 뺌, 사유 = 준비 경고 detail) | vitest `GRAPH_FAILED(doe-11)`·`새 스터디 제목 칸`, 스크린샷 `int_3`·`int_4`(2560·1920) |

- `scripts/test-all` 에 `packages/beadgraph/tests` 단계 추가(패키지 시험이 전체 시험에서 빠져 있었음).
- 패키지 판(`__version__` 1.0.0·`RULES` 1·`MORPH_RULES` 1)은 올리지 않음: 미출시 판 안의 수정이고 픽스처 `expected.json` 분류 sha 불변(모핑 수치는 공유 자식 벽 경계 노드 J 만 바뀜).
