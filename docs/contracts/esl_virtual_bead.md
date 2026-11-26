# 계약: 가상 비드 추가 — 평판 위 선분 + 단면 입력 → 기존 노드 법선 모핑, 깊이 = 설계 변수 (VB, v0.25.0)

- 상태: 초안(2026-11-26) — 메인 설계 지침 14개를 코드 감사(§0)로 구체화. **개정 3**(같은 날 사용자 결정 2건 — §19.8 질문의 답 → D-0.25.0-VB-26~28: 변수 값 D = 실제 최대 깊이(보상 식)·방향 자동 + 뒤집기 `flip` — **§19.9 가 원본, 본문·§19.1~19.7 해당 줄에 반영**). **개정 2**(같은 날 사용자 결정 3건 — C1 측정 VB-C1-5·6·7 → D-0.25.0-VB-21~25: r 기본 = h·warp 정보화·평탄부 host·θ [15, 60] — **§19 가 원본, 본문 해당 절에 반영**). **개정 1**(같은 날 메인 결정 — 불일치 3건 확정 D-0.25.0-VB-13~15, 한쪽 범위 보정 승인 VB-16, 정확도 표·안내·툴팁 VB-17~19 — 본문 반영, §15). 구현 코드 없음 — 이 문서가 원본. 브랜치 `release/v0.25.0`(base main 6030b213 = v0.24.7). **v0.24.8(`esl_jig_grid_map.md`, origin `release/v0.24.8` 0e4264c7)·v0.24.9(`esl_bead_pos_u.md`, origin `release/v0.24.9` 6f05e34a)가 먼저 머지되므로 구현은 그 위에 재기반**(§11.2 겹침 표). 행 번호 = main 6030b213.
- 관계: `esl_bead_select.md` BS-D-9(선형 기저 합 — 이 계약이 "꺾인 선형" 1종을 더함)·§7.3(basis.bin), `esl_beadgraph.md` BG-D-34·36·38·39, `esl_bead_shape_v021.md` SH-10~16·SH-28(range guard), `esl_bead_depth_mode.md`(계획 표 `SECTION_PLANS`·판 고정 방식), `esl_bead_pos_u.md` §1.3 공칭 0 감사(A0-1)·§2 `load_follow`. 충돌하면 `virtual_beads` 가 있는 선택 문서에서 이 문서가 우선.
- 패키지 `beadgraph` **무변경**(분류 결과 labels·graph 만 읽음). `GRAPH_ALGO`·`bead_select.ALGO/RULES`·`PLAN_VERSION` 불변. DB migration 없음.
- ID: 결정 `D-0.25.0-VB-n`, 시험 `V-0250-VB-n`, 후속 `R-VB-n`, 미결 `Q-VB-n`, 현장 `F-VB-n`, 불일치 `X-VB-n`(개정 1 에서 모두 결정).
- 용어: 화면 = "추가 비드"(내부 = 가상 비드 virtual bead, vb). 중심선 = 평판 위 직선 선분 p0→p1. d = 노드에서 중심선(선분)까지 평면 거리. W_top = 깊이면 폭, θ = 사면 각(판 평면 기준), D = 깊이(변수), run = D·cotθ, **W_open(D) = W_top + 2D·cotθ**(v0.24.7 "깊이면 폭 유지"와 같은 뜻).

### 사용자 원문 (변경 금지)
- "모핑기반으로 형상변수 정의할때 비드를 추가하는건 가능해?? 사용자가 선길이 위치 각도 정하고 거기에 비드 단면정보 입력해서"
- "할수 있는건 하고 못하는건 알려주면 되지."
- "페이블 계약 구성, 구현은 오퍼스 지휘로 해바"
- 합의의 바탕(메인 설명): 기존 평판 노드를 법선 방향으로 밀어 비드를 만든다. 깊이 0 = 지금 형상, 깊이가 변수. 위치·각도·길이는 1차에서 후보 선을 여러 개 그려 각각의 깊이를 변수로 둔다. 한계 = 메시 크기(사면에 요소 1~2개면 모서리가 뭉개짐), 모서리가 요소 경계와 안 맞음, 사면 요소 늘어남, 구멍·보스·체결부·기존 비드와 겹치면 불가, 유리한 후보는 실제 형상으로 ④나 재낙하 확인.

---

## 0. 감사 (main 6030b213, 읽기만)

### 0.1 선택 문서 · derive · 변수 행
| 항목 | 지금 | 근거(파일:행) |
|---|---|---|
| 선택 schema 2 정규화 | `normalize_v2` — beads 1..max_beads 필수(빈 목록 = `SELECT_EMPTY_TIER`), 그래프 비드 vars ∈ {D, W}, 정규화 JSON → `selection_sha256`(그래프 sha 포함), 크기 상한 `max_selection_kb` | `esl/doe/bead_graph.py:563-686`(beads 개수 `:582-584`, vars `:632-640`, sha `:683-686`) |
| 선택 sha → 폴더 | `select/<sha12>/{basis.npz, basis.bin, basis.json, params.json, derived.*}`, 재사용 조건 = sha·mesh·basis sha·cfg_sha·algo·graph_algo·morph_rules·range_guard sha·depth_section·df/w1_rules | `esl/doe/stages.py:6802-6827`(재사용 `:6809-6823`) |
| 선택 해시 보기 | `_sel_cfg_sha` = select hash view + quality(+ shape·section — 새 스냅샷만) | `stages.py:7009-7025` |
| 백엔드 선택 모델 | `SelectGraphBeadIn.vars: list[Literal["D","W"]]` max 2, `SelectionInV2{schema_version 2, feature_angle_deg, graph, beads, ties, fixed_user, exclude}` — 그 밖 키는 `_Req` 가 422 | `backend/esl_platform/api/schemas.py:2516-2537`·`:2550-2559` |
| 백엔드 정규화·derive | `doe_select.normalize`(코어 `normalize_v2`) → `derive`(동기 풀, 캐시 키 = sha·mesh·graph·w_clamp·range_guard·shape·depth_section·section_rules, frame·fixed_scan 전달) | `backend/esl_platform/api/services/doe_select.py:417-438`·`:442-488`(캐시 키 `:449-454`), 입력 `:114-153`(frame = `t.frame`) |
| derive 응답 | `derive_v2` → summary·slope/islands_suggested·fixed_ab·`params`·`param_beads`·그림·w_reason | `bead_graph.py:795-818` |
| 변수 행 | `params_rows_v2` — 그래프 비드 `B<n>_<D|W>`(`var_name` = `bid.upper()_typ`), use_default = BG_SEGMENT_SHORT·blocked 아니면 true, guard 복사 | `bead_graph.py:1304-1306`·`:1316-1349` |
| 비드 행 | `param_beads` — kind "select" 고정 | `bead_graph.py:1017-1022` |
| 변수 종류 | `PARAM_TYPES = ("D","W","U","V")` — **V = paicad `BEAD_POS_V`(위치 V)**, 프런트 `TYPE_NAME.V = "위치 V"` | `esl/doe/__init__.py:37`, `esl/doe/paicad_io.py:48`, `frontend/src/api/doe.ts:405` |
| 분류 라벨 | `labels{cls, floor, segment, transition, island, junction_zone, tier}`, `CLS{floor 0, wall 1, island 2, lance 3}`, 부모 바닥(뿌리) = segments[s].type `"base"`(변수 없음), floors[].kind base·base_fragment·island·area | `packages/beadgraph/src/beadgraph/classify.py:22-23`·`:204-207`·`:383-385`·`:396` |
| ESL frame | `{origin, e_xi, e_eta, n, L_xi, L_eta}` | `esl/doe/scenario.py:133`·`:367-368` |

### 0.2 "기저 × 값" 선형 합을 가정하는 곳 (가상 비드 = 꺾인 선형 → 모두 감사)
| 곳 | 식 | 근거 | 가상 비드 영향 |
|---|---|---|---|
| 설계 좌표(BD_MATRIX 상태 판정·BD_EVAL·미리보기 셀) | `bead_select.morph`: X[idx] += (v − v_nom)·vec | `bead_select.py:1646-1656`, 호출 `stages.py:7070-7076`(`_sel_design` ← `:557`·`:614`), `:7113`·`:7129`(grid) | **변경 필요(한 곳)** |
| 고정 침범 원인 | dv·vec 크기 | `bead_select.py:1669-1693`(`:1689`) | 변경 필요(같은 항 함수) |
| elems 조합 점검 | `morph()` 재사용 | `bead_select.py:1769-1773` | 자동(morph 따라감) |
| range guard 탐침 | `_Prober.ok`: x[li] += dv·vec | `bead_graph.py:1847-1907`(`:1891-1893`), 호출 `:2090-2093`(준비 표)·`:2114-2133`(조합)·`:2287-2291`(BD_MATRIX 보충) | **변경 필요** |
| range guard 순수 모듈 | 공칭–끝 이분(단조 가정), `blocked` = 양쪽 keep | `esl/morph/range_guard.py:106-151` | 단조(꺾인 선형은 단조) OK, **한쪽 범위**(공칭 0 = lo) 처리 필요 |
| SH-28 막힘 규칙 | limited ∧ ¬(u_lo < nom < u_hi) → blocked | `bead_graph.py:2141-2172`(`:2155`) | **[0, D_max] 는 항상 blocked 로 오판** → 변경 필요 |
| w_clamp | W 만 | `bead_graph.py:332-340` | 무관 |
| 대칭 묶기 합 | full += vec | `bead_graph.py:1440-1450` | 무관(가상 비드 묶기 없음 — 1차) |
| 교차 점검 SR-D-38 | type W 만 \|Δv\|·‖B‖ | `esl/morph/core.py:255-275`·`:418-436` | 무관(겹침 금지 §3) |
| 바깥 이동 BG-D-34 | 허용 노드(zone/allowed 없으면 idx) | `bead_graph.py:1524-1564`, `core.py:438-462` | 자동(idx = 발자국) |
| basis.npz | names·types(U1)·beads(U4)·nominal·R·n_hat·ptr·idx·vec | `bead_select.py:1881-1898`·`:1901-1910` | 선택 키 추가(§4.2) |
| basis.bin·basis.json | [n][idx u32×n][vec f32×3n], vars{name,type,bead,nominal,n,R_mm} | `bead_select.py:1913-1929`, `doe_select.py:56`·`:1101-1125`, `routers/doe.py:253`·`:302` | 선택 꼬리 추가(§4.2) |
| 브라우저 미리보기 | `morph`·`heightChange` = Σ(x − nom)·vec, `parseBasis` 길이 엄격 검사, `BasisVar.type "D"\|"W"` | `frontend/src/view3d/select/basis.ts:5-12`·`:15-38`·`:58-73`·`:99-110` | **변경 필요** |
| 썸네일 색 | `node_direction`(n_hat) + 실제 xd 차 | `bead_select.py:1931-`, `stages.py:7111-7118` | 자동(실좌표) |
| 썸네일 색 범위 auto | D 변수만 | `esl/doe/matrix.py:233-242` | A 추가(§5.3) |
| 재낙하 zip | `run/designs/<did>/design.npz` 좌표 | `backend/.../services/redrop.py:213-215`·`:258`, `esl/verify/redrop.py` | **자동**(실좌표) |
| 형상 비교 3D(view3d) | `ev.load_design(dd)` 의 x | `stages.py:844-879`(`:868-871`) | **자동** |
| 안 해시 | `input_sha256(values, mesh, loads, cfg, "select:<sel>:<basis>")` | `stages.py:536-545` | 자동(기저 sha 가 바뀜) |
| 순위·민감도·보고서 | 값만 사용(v0.24.9 A0-1 확인) | `esl/doe/rank.py:327-366`, `report_doe.py:651-658` | 자동 — 공칭 0 OK |

### 0.3 공칭 0 · 한쪽 범위 (v0.24.9 §1.3 A0-1 재사용 + 가상 비드 추가분)
| 위치 | v0.24.9(U) | 가상 비드(A) | 근거 |
|---|---|---|---|
| 422 "> 0" | `_POSITIVE = ("D","W")` — U 제외 | A 도 제외(lo = 0 허용) — **코드 변경 없음** | `matrix.py:25`·`:106-108` |
| "공칭 ∈ [lo, hi]" | U 만 추가(`normalize_spec`) | A = **lo ≥ 0**(공칭 0 = 하한 쪽), lo < 0 → `DOE_RANGE_INVALID` "추가 비드 깊이 하한은 0 이상". **같은 분기 1곳에 종류별 규칙 표**(U: lo ≤ 0 ≤ hi, A: lo ≥ 0) — v0.24.9 구현과 중복 금지 | `matrix.py:100-112` |
| 프런트 행 오류 | `rowProblem` U 규칙 | 같은 함수에 A 규칙(같은 표) | `frontend/src/api/doe.ts:1121-1129` |
| 공칭 선택 `_nom` | 그래프 비드 행 6곳 | 가상 비드는 그래프 비드 행이 아님 → `_nom` 무관, 행 nominal = 0.0 직접 | `bead_graph.py:1092·1144·1642·1776·1902·1923`(v0.24.9 기준) |
| 썸네일 색 범위 | U \|ΔU\| 추가 | A \|hi\| 추가(같은 분기) | `matrix.py:237-241` |
| 기본 포함 | U use_default false · `default_types [D, W]` 불변 | A 기본 켬: `default_params`·프런트 `defaultRows` 의 조건 = `use_default ∧ (type ∈ default_types ∨ row.form = "hinge")`(§5.2) | `matrix.py:49-60`, `doe.ts:1112-1117` |
| range guard 한쪽 | U 는 양쪽 범위 | `blocked`·SH-28: **폭 0 인 쪽(from = 공칭)은 판정에서 뺌**(§6.2) | `range_guard.py:106-114`, `bead_graph.py:2155` |
| 하중 공간 고정 | U 있으면 spatial | A 는 **위치 변수 아님** — `has_pos_var` 에 넣지 않음(면내 이동 0 → 노드 하중 그대로 유효) | v0.24.9 §2.2 `load_follow_effective` |
| lin 보조 열 | spatial 에서 null | A = D 와 같음(노드 하중·노드 해 유효 — null 아님) | v0.24.9 §2.2 A0-2 |

### 0.4 화면 (3D 찍기 · 목록 · 변수 표 · 미리보기)
| 항목 | 지금 | 근거 |
|---|---|---|
| 3D 찍기 | `Select3D` → `sceneApi.pickElem(x, y) → {elem, point}`(보이는 면, 월드 좌표), 그래프 클릭 = `graphClick`, 드래그 ≤ 4 px 판정 | `frontend/src/components/BeadSelectCard.tsx:792-1010`(`:957-961`·`:964-973`), `view3d/sceneApi.ts:83`, `view3d/scene.ts:1015` |
| 그래프 도구 | `GraphTool = "pick" \| "split"`, 라디오 `bs-gtool-*` | `BeadSelectCard.tsx:123`·`:1069`·`:1138-1145` |
| 3D 겹쳐 그리기 | `setOverlayLines(segments)`(검정 선분)·`setMarkers(points)`(빨강 점) | `view3d/sceneApi.ts:75-76`·`:88-89` |
| 비드 목록 | ③ 카드 `BeadList`(목록·트리, 그래프 비드 행 `GraphBeadRow`, [+ 비드]) | `BeadSelectCard.tsx:1249-1251`, `components/BeadList.tsx:26-80`·`:206` |
| 변형 3D | `SelectDesign3D`(Card, glb + basis.bin → `morph` 변위·`heightChange` 색, [공칭↔안]·배율) — 저장·BD_MATRIX 뒤 기저만 | `BeadSelectCard.tsx:1258-1370`, `pages/doe/DoeStudy.tsx:2002-2011` |
| 선택 화면 슬라이더 | 없음(브러시 크기만) | `BeadSelectCard.tsx:1159` |
| 변수 표 | `DoeParamTable` select 가지 = `b.kind === "select"` 비드 묶음, 라벨 D 아니면 W, 계획 칩 `D…/W` | `components/DoeParamTable.tsx:205-262`(`:235`), `DoeStudy.tsx:1408`·`:1415` |

### 0.5 발견
1. 선형 가정은 **좌표 생성 1곳(`bead_select.morph`) + 탐침 1곳(`_Prober.ok`) + 고정 원인 1곳 + 브라우저 2곳**뿐이다. 그 밖(재낙하·3D·순위·썸네일 색)은 실좌표·값만 쓴다 → "변수 1개 항의 평가 함수"를 한 곳에 두면 최소 변경으로 비선형 1종이 들어간다(§4).
2. 사면 각 고정형 u = n·max(0, D − g(d)) 는 노드마다 **D 와 무관한 상수 g(d)** 와 방향 n 만으로 정확히 표현된다(꺾인 선형 "힌지"). 미리보기 표·보간 불필요 — basis 에 노드별 g 1개를 더하면 브라우저도 정확히 같은 식(V-BS-12 float32 오차 기준 그대로).
3. `PARAM_TYPES` 의 "V" 는 이미 paicad 위치 V·v0.24.9 R-PU-1 의 자리다 → 가상 비드 종류 = 새 문자 **"A"**(D-0.25.0-VB-13, V 자리 불변).
4. 선택 문서는 그래프 비드 ≥ 1 을 요구한다 → 가상 비드만 있는 선택을 허용하려면 규칙 변경(§2.1).
5. SH-28 은 공칭 = 범위 끝인 변수를 항상 막는다 → 한쪽 범위 예외 필요(§6.2).
6. 선택 화면에는 변형 미리보기가 없다(저장·BD_MATRIX 뒤 `SelectDesign3D` 만) → derive 응답에 미리보기 자료를 싣고 `SelectDesign3D` 의 그리기 부분을 떼어 재사용(§9).

## 1. 범위 · 계획 표 (지침 1)

### 1.1 적용 범위
- select 시나리오 · 그래프 분류 있음(schema 2, `graph` 블록 있음 — GRAPH_FAILED 아님) · 같은 메시 계획(case_once·bmesh_once·step_once). 선택(요소)만 있는 schema 1·paicad(①②옛③)·옛 ③ step_per_design·④ = 범위 밖(`VB_SCOPE`).
- 스냅샷에 `doe.virtual_bead` 블록이 있는 스터디만(§7.2). 블록 없는 옛 스터디에서 가상 비드를 넣으면 422 `VB_SCOPE`(새 스터디 안내).

### 1.2 계획 표 (AGENTS.md — 시나리오 이름 분기 금지)
- `esl/doe/transfer_plan.py` `PLANS` 열 추가 **`vbead`**: case_once·bmesh_once·step_once = `"plate"`, step_per_design·compare_per_shape = `"none"`. `PLAN_COLS` += vbead. PLAN_VERSION·`hash_view` 불변(값 검사 `VBEAD = ("plate","none")`).
  - 주의: case_once·bmesh_once 는 paicad `same`·`mesh` 도 쓴다(`PLAN_OF` `transfer_plan.py:72-74`) → 계획 열만으로는 출처를 못 가른다. 그래서 **두 표의 곱**으로 판정한다.
- `esl/morph/section.py` `SECTION_PLANS` 에 **열 `form`·`vb_host`** 와 **행 `virtual`** 추가(빈 칸 = `CONFIG_INVALID`):

| 행 | compose | one_side | theta | feasible | fig | na | **form** | **vb_host** |
|---|---|---|---|---|---|---|---|---|
| graph | pkg_df | pkg_w1 | none | open_cap | floor_center | none | linear | plate |
| elems | select_w_f0 | none | run_med | open_cap | stretch | none | linear | none |
| paicad | none | none | none | none | none | DS_ENGINE_NATIVE | native | none |
| none | none | none | none | none | none | none | none | none |
| **virtual** | none | none | none | none | none | none | **hinge** | none |

- `form` = 그 출처 변수 행의 평가 형식(linear = (v − v₀)·B, hinge = §4.1, native = paicad 엔진). `vb_host` = 그 출처의 분류 결과 위에 가상 비드를 놓을 수 있는가(plate = 부모 바닥 판 라벨).
- 판정 한 곳 `section.vb_allowed(plan_vbead, host_row) -> bool` = `plan_vbead == "plate" and SECTION_PLANS[host_row]["vb_host"] == "plate"`, host_row = 선택 문서가 그래프 블록을 가지면 "graph" 그 밖 "none"(행 결정은 `bead_graph` 가 이미 아는 값 — 시나리오 이름 아님). v0.24.9 열 `pos` 와 같은 표에 나란히(§11.2).

## 2. 입력 · 저장 (지침 2·8)

### 2.1 선택 문서 키 (schema 2 에 선택 키 1개)
```
virtual_beads: [{id, name?, p0:[x,y,z], p1:[x,y,z]            # (a) 두 점
                 | p0:[x,y,z], length, angle_deg,             # (b) 시작점 + 길이 + 각도
                 w_top, theta_deg?, d_max, flip?, end?, r?}]
```
| 키 | 규칙 | 기본(생략 = 정규화에서 키 없음) |
|---|---|---|
| id | `^a[1-9]$`(a1, a2 … — 그래프 비드 `b1` 과 같은 소문자, 표시·변수 이름은 대문자 A1), 고유, ≤ `max_count` | – |
| name | 1..32자, 제어문자 금지 | "추가 비드 n" |
| p0·p1 | 모델 좌표(mm, 유한), p1 있으면 length·angle_deg 금지(둘 다 = 422 `VB_INPUT_INVALID`) | – |
| length·angle_deg | (b) 형식: length > 0, angle_deg ∈ (−180, 180] — **ESL frame 판 평면에서 +ξ 기준 +η 쪽으로 잰 각** | – |
| w_top | > 0 | – |
| theta_deg | `theta_range_deg`([15, 60]) 안 ∧ ≤ 스냅샷 flip_deg(§19.4) | `theta_default_deg`(45) |
| d_max | > 0, ≤ `d_max_limit_mm` — **모델의 실제 최대 깊이**(r > 0 이어도 변수 값 = 실제 깊이, §19.9.1) | – |
| flip | bool — true = 자동 방향(§2.3)의 **반대쪽**(개정 3, §19.9.2). 옛 키 `side` 는 받지 않음(주면 422 `VB_INPUT_INVALID` key side) | false(키 없음 = 자동 방향) |
| end | `"round"` \| `"square"` | round |
| r | 모서리 반경 ≥ 0, ≤ r_cap(§19.1 — 넘으면 422 `VB_INPUT_INVALID` key r) · **준 값은 0 이어도 키 유지**("r 0" = 각진 모서리) | **생략 = `r_default_h_mult`·h**(요소 크기 — derive 가 정함, §19.1) |
- 입력 형식은 받은 대로 저장(정규화가 (b)를 (a)로 바꾸지 않음 — 화면 복원). derived 에는 둘 다(`p1_resolved`).
- 정규화: 키 정렬, 숫자 1e-4 반올림, id 정렬, 기본값 키 생략(BG-D-36 선례 — **r 은 예외: 기본이 메시에 따라 정해지므로 준 값은 그대로 남김**, §19.1). **`virtual_beads` 가 없거나 빈 목록이면 키를 쓰지 않음** → 옛 선택 문서·sha·`select/<sha12>`·모든 산출물 바이트 불변.
- beads 개수 규칙: `len(beads) + len(virtual_beads) ≥ 1`(가상 비드만도 허용 — `bead_graph.py:582-584` 를 이렇게 바꿈, beads 만 있는 선택의 오류 문구·코드 불변).
  - 그래프 비드 0개일 때(가상 비드만): **자동 방향**(§2.3) = 그래프 비드 다수결 대상 없음 → ESL frame `n` 과 n_h 내적 부호의 반대(같은 함수의 동률 가지 — 값 결정적) · **fixed 집합**(§3.2 VB_FIXED) = fixed-scan ∪ fixed_user ∪ 지그 tie 그대로(그래프 비드와 무관한 스터디 입력 — `_sel_fixed_ids`·PU-14 함수) · **range guard**(§6) = carriers 가 A 변수만, 조합 묶음 상대 없음(단일 점검만), 준비 표 `range_guard_table` 은 지금처럼 그래프 분류 결과로 만들어지나 쓰이지 않음. 분류 결과(graph·labels)는 host 판 판정에 필수 — GRAPH_FAILED 면 VB_SCOPE(시험 V-0250-VB-19).
- 백엔드 `SelectionInV2 += virtual_beads: list[VirtualBeadIn] = Field(default_factory=list, max_length=9)`, `VirtualBeadIn(_Req)` = 위 키(정규화·기본값은 코어). `selection_in`(`doe_select.py:404-414`) 은 `exclude_none` dump 그대로 — 빈 목록은 dump 에서 빼서 코어에 넘김(옛 sha 불변).

### 2.2 기하 해석 (derive — 순수 `virtual_bead.resolve_line`)
- 판 평면: host 판(§3.1) 요소 중 p0 에서 가장 가까운 요소를 씨앗으로, 반경 `L/2 + W_open(d_max)/2 + margin` 안 host 요소 노드의 최소제곱 평면(`core.plane_fit`) → (p_h, n_h). p0·p1 을 이 평면에 사영.
- (b) 형식: t = cos(α)·ê_ξ' + sin(α)·ê_η', ê_ξ' = e_xi 를 판 평면에 사영·정규화, ê_η' = n_h × ê_ξ'(ê_eta 와 내적 < 0 이면 부호 반대로 — frame 손잡이 보존). p1 = p0 + length·t.
- p0 = p1(길이 < 1e-6) → `VB_INPUT_INVALID`. 사영 거리 > `margin_mm` + 2h 인 점(판에서 먼 점을 찍음) → `VB_NOT_ON_PLATE`.

### 2.3 방향 (자동 + 뒤집기 — 개정 3, §19.9.2)
- 자동 방향 s_auto(순서 고정): ① host 가 평탄 영역이고 |level 차| > 1e-6 mm → 평탄부가 들어간 쪽(§19.3-4) ② 그 밖 = 아래 다수결 ③ 동률·그래프 비드 없음 = frame n 반대. **적용 방향 s = `flip` 이면 −s_auto, 아니면 s_auto**(host 종류와 무관하게 같은 키). derived `side_resolved` = 적용 방향.
- 다수결: 선택의 그래프 비드 깊이 방향(`b.n_hat`) 중 n_h 와 내적 부호의 다수(동률·그래프 비드 없음 = ESL frame `n` 과 n_h 내적 부호의 반대 — 판에서 frame 법선 반대쪽으로 들어감; **메인 지침 "기본은 기존 비드 다수와 같은 쪽"**). derived `side_resolved`.

## 3. 놓을 수 있는 곳 · 메시 해상도 (지침 5·6)

### 3.1 host 판 · 발자국
- host 요소 H = `cls == floor` ∧ segments[`segment`].type ∈ **`VB_HOST_SEG_TYPES` = ("base", "area", "plateau")**(부모 바닥 + 평탄 영역 — 개정 2, §19.3) ∧ `junction_zone == −1` ∧ `island == −1` ∧ ¬exclude ∧ `wall_islands` floor 아님. 한 가상 비드의 host = 씨앗 요소와 **같은 floor** 요소만(VB-C1-9). (골격이 있는 기존 비드의 깊이면 위는 범위 밖 — R-VB-7.)
- 거리 d(x) = 판 평면 사영 x' 에서 선분 [p0', p1'] 까지 거리(end round), square = max(|y|, max(0, −s, s − L))(s = 선분 방향 좌표, y = 수직 좌표).
- 이동 띠 d_move = W_top/2 + (e(d_max) + c)·cotθ(e = 깊이 보상 §4.1 — r_cap 안에서는 = W_top/2 + d_max·cotθ + **1.25**·r·tan(θ/2), r = 해석된 r — §19.1; r 0 → W_top/2 + d_max·cotθ), 검사 띠 d_chk = d_move + `margin_mm`.
- 발자국 노드 N_fp = {d < d_move}, 검사 요소 E_chk = 노드 하나라도 d < d_chk 인 요소.

### 3.2 거부 사유 (그 가상 비드는 변수 없음 — 사유 목록 전부, 순서 고정)
| 코드 | 조건 | 화면 1줄 |
|---|---|---|
| VB_SCOPE | §1.1 밖(계획·출처·블록 없음) | 이 스터디에서는 추가 비드를 쓸 수 없음(그래프 방식 새 스터디만) |
| VB_INPUT_INVALID | §2.1 키 오류·길이 0 — **422**(저장 거부) | – (422 문구) |
| VB_MAX_COUNT | 개수 > `max_count` — **422** | – |
| VB_NOT_ON_PLATE | E_chk 중 H 아닌 요소(벽·다른 바닥·lance 포함) 또는 점 사영 거리 초과 | 선이 평판 밖(벽·다른 면)에 걸침 |
| VB_OVER_BEAD | E_chk ∋ host 종류가 아닌 세그먼트(골격 있는 비드)·접합 구역·**host 의 바깥 테두리가 아닌** transition 요소(§19.3-2) | 기존 비드와 겹침 |
| VB_OVER_ISLAND | E_chk ∋ island·lance 요소 | 보스·섬과 겹침 |
| VB_OVER_HOLE | E_chk 노드 ∋ 구멍 자유 모서리 노드(판 안쪽 고리) | 구멍과 겹침 |
| VB_PLATE_EDGE | E_chk 노드 ∋ 판 외곽 자유 모서리 노드 **또는 E_chk ∋ host floor 의 바깥 테두리 transition 요소**(평탄부 가장자리 벽 — §19.3-2) | 판·평탄부 가장자리에 닿음 |
| VB_FIXED | E_chk 노드 ∋ fixed(fixed-scan ∪ fixed_user ∪ 지그 tie — v0.24.9 PU-14 와 같은 집합 함수 재사용) | 체결부와 겹침 |
| VB_OVER_VBEAD | 다른 가상 비드의 E_chk 와 요소 공유 | 다른 추가 비드와 겹침 |
| VB_EXCLUDED | E_chk ∋ exclude 요소 | 제외 영역과 겹침 |
| VB_MESH_COARSE | run = d_max·cotθ < 1·h 또는 W_top < 1·h | 메시가 성겨 비드를 만들 수 없음(사면이 요소 하나 안) |
- 부분 겹침 허용 안 함(1차). 위반이 하나라도 있으면 변수 행 없음 + derive `virtual_beads[].reasons[]`(전부) + `vb_reason{code}`(첫 코드, 비드 행 회색 1줄).
- 422 는 형식 오류만(VB_INPUT_INVALID·VB_MAX_COUNT). 놓을 수 없는 곳은 저장 가능(화면에 사유) — 사용자가 고치거나 지우게.

### 3.3 메시 해상도 (지침 6)
- h = **r 0 발자국**(d < W_top/2 + d_max·cotθ) 요소(그 노드를 가진 H 요소) 변 길이 중앙값 — r 기본을 정하기 전에 한 번 구하고 다시 구하지 않음(§19.1).
- n_wall = run/h(사면 폭의 요소 수), n_top = W_top/h.

| 조건 | 판정 | 코드(경고, 행은 만듦) |
|---|---|---|
| run < h ∨ W_top < h | 거부 | VB_MESH_COARSE(§3.2) |
| h ≤ run < `min_wall_elems`·h | 경고 | `VB_WALL_COARSE{n_wall}` "사면 요소 {n} 개 — 모서리가 뭉개짐(실제 형상보다 완만)" |
| h ≤ W_top < 2h | 경고 | `VB_TOP_NARROW{n_top}` "깊이면 폭이 요소 2개 미만" |
- 정보(진단 — 실패 아님): `VB_EDGE_SMEAR{h}`(모서리가 요소 경계와 안 맞아 h 폭으로 퍼짐 — 늘 1건), `stretch_max`(D_max 에서 발자국 요소 넓이 비 최대 ≈ 1/cosθ_eff), `n_fp`, `n_elems_fp`.

## 4. 변형장 · 평가 함수 (지침 3·9) — 최소 변경안

### 4.1 정의 (사면 각 고정형 — 기본)
- 노드 i ∈ N_fp 의 변위: **u_i(D) = s·n_i · [F_c(e(D) − g_i) − F_c(0 − g_i)]**, s = 적용 방향(±1, §2.3), n_i = host 요소만으로 만든 노드 법선(면적 가중, n_h 쪽으로 부호 맞춤 — 평판이면 n_h), 면내 성분 0.
- g_i = tanθ·Q_a(d_i − W_top/2), Q_a(t) = 0 (t ≤ −a) · (t + a)²/(4a) (|t| < a) · t (t ≥ a), a = r·tan(θ/2)·(1 + cosθ)/2 (r = 0 → a = 0, Q = max(0, t)) — 깊이면 가장자리 모서리 둥글림(D 와 무관).
- **깊이 보상 e(D)**(개정 3, D-0.25.0-VB-26 — `virtual_bead.depth_eff(v, c)`): **e(D) = D + c/4 (D ≥ 3c/4) · c·(√(1 + 4D/c) − 1) (0 < D < 3c/4) · D (D ≤ 0 또는 c = 0)** — F_c(e) − F_c(0) = D 의 정확한 역함수(e(0) = 0, D = 3c/4 에서 값 c·기울기 1 로 이어짐 — C¹, 단조 증가). 보정하는 양 = 힌지 항에 넣는 **변수 값 한 개**(노드 상수 g·c·vec 는 그대로).
- F_c(t) = 0 (t ≤ −c) · (t + c)²/(4c) (|t| < c) · t (t ≥ c), c = r·tan(θ/2)·tanθ (r = 0 → F = max(0, t)) — 입구 모서리 둥글림(D 와 같이 움직임, t = D − g 만의 함수라 형식 유지).
- r = 0 이면 **u(d, D) = s·n·max(0, D − g(d)), g(d) = max(0, d − W_top/2)·tanθ** — 지침 식 그대로. D ↑ → W_top·θ 그대로, 입구 W_open = W_top + 2D·cotθ(r > 0 이면 보상 때문에 W_top + 2(D + c/4)·cotθ — 한쪽 r·tan(θ/2)/4 넓음).
- 성질: D = 0 → u = 0(정확 — e(0) = 0, F_c(−g) 를 뺌), D 에 대해 단조 증가, 깊이면(d ≤ W_top/2 − a, g = 0) 노드 = s·n·(F_c(e(D)) − c/4) = **s·n·D — 모든 D ∈ [0, d_max] 에서 변수 값 = 실제 최대 깊이**(g ≥ 0·F 단조라 깊이면이 최대). 작은 D(< 3c/4)는 단면 전체가 둥글림 구간 안의 얕은 홈(깊이 D 정확). 보상 없는 옛 식(개정 2)은 실제 깊이가 c/4 얕았음 — 철회.
- 면내 이동 0 → **하중 공간 고정 불필요**(노드 하중의 면내 위치 불변, v0.24.9 `has_pos_var` 에 넣지 않음), 지그 tie·fixed 는 발자국 밖(§3.2 VB_FIXED)이라 움직이지 않음.

### 4.2 형식 일반화 — 변수 항 1개의 평가 함수 (한 곳)
- basis 변수 항목 키 추가: `form`("linear" 기본 — 키 없음 | "hinge"), hinge 만 `g`(idx 와 같은 길이 float64)·`c`(스칼라). vec = s·n_i(단위).
- 항 함수 **`esl.morph.core.basis_term(var, value) -> (idx, du)`**: linear = (v − v₀)·vec(지금 식 — 바이트 동일), hinge = vec·[F_c(e(v) − g) − F_c(e(v₀) − g)][:, None], e = `virtual_bead.depth_eff(·, c)`(§4.1 — 저장 키 추가 없음: 변수별 `c` 만으로 계산). `F_c` 원본 = `esl.morph.virtual_bead.ramp(t, c)`(순수, numpy).
- 이 함수를 쓰는 곳(전부 — 그 밖 선형 가정 없음, §0.2):

| 곳 | 변경 |
|---|---|
| `bead_select.morph`(`:1646-1656`) | `X[idx] += basis_term(v, value)` — linear 경로 산술 순서 그대로(바이트 동일) |
| `fixed_violation_detail`(`:1686-1690`) | 같은 항 |
| `bead_graph._Prober.local/ok`(`:1867-1907`) | `vs` 항목에 (li, vec, g, c, v₀) — ok(L, dvs) 가 hinge 면 v = v₀ + dv 로 항 계산 |
| `save_basis/load_basis`(`:1881-1910`) | **hinge 변수가 있을 때만** 배열 `form`(U6, 변수별)·`g`(float64, idx 와 같은 ptr — linear 변수 구간 0)·`c`(float64, 변수별). 없으면 지금 키·바이트 그대로. load 는 키 없으면 linear |
| `basis_bin`·`basis_meta`(`:1913-1929`) | hinge 변수만 vec 뒤에 `[g:f32×n]` 꼬리, basis.json vars[] 그 변수에 `form:"hinge"`·`c`. linear 변수·옛 파일 바이트 불변(schema 문자열 그대로 — 선택 키) |
| 프런트 `basis.ts` | `BasisVar += form?: "hinge"; g?: Float32Array; c?: number`, `parseBasis` 가 meta form 을 보고 꼬리 읽음(길이 검사 포함), `morph`·`heightChange` 가 항 함수 `termAt(v, x, i)` 1개 사용, `ramp(t, c)`·`depthEff(v, c)` = 코어와 같은 식(V-0250-VB-8·31 대조) |
- 대안(비교 — 채택 안 함): (i) 선형형 u = D·p(d)(입구 폭 고정, D_max 에서만 지정 각) — 변경 0 이나 D 마다 각이 변하고(v0.24.7 entry_fixed 와 같은 결함 — #88 B8 기울기 혼동의 원인), 입구 고정이라 "깊이면 폭 유지" 아님. (ii) 미리보기 D 수준 표 보간 — 정확하지 않고 파일·형식이 늘어남. **힌지는 정확·추가 저장 = 노드당 float 1개**라 채택(D-0.25.0-VB-3).

### 4.3 순수 모듈 `esl/morph/virtual_bead.py` (지침 9)
- numpy 만, `esl.doe`·`beadgraph`·`esl.mesh` import 금지, IO·설정 해석 없음(값은 인수).
- `resolve_line(p0, p1|None, length, angle_deg, frame_axes, plane) -> (p0', p1', t̂, L)`
- `footprint(Xp, line, w_top, theta_deg, d_max, end, r, margin) -> {d, move_mask, chk_mask}`
- `host_check(elem_nodes, chk_elems, masks{host, bead, island, hole_nodes, edge_nodes, fixed_nodes, exclude, other_vb}) -> [codes]`
- `resolution(h, w_top, theta_deg, d_max, min_wall_elems) -> {codes, warns, n_wall, n_top}`
- `field(d, normals, side, w_top, theta_deg, r) -> {idx, vec, g, c}`, `ramp(t, c)`, `q_round(t, a)`, **`depth_eff(v, c)`**(깊이 보상 e — §4.1), `hinge(g, c, v, v0)` = ramp(e(v) − g, c) − ramp(e(v0) − g, c)
- `diag(X, conn, et, field, d_max) -> {stretch_max, n_fp, n_elems_fp}`
- 호출 쪽 = `esl/doe/bead_graph.py`(derive·basis — labels·graph·fixed·exclude 에서 마스크를 만들어 넘김). beadgraph 패키지 코드 수정 없음.

## 5. 변수 행 · 기본 · 범위 (지침 4)

### 5.1 행
- `{name: var_name("a<n>", "A") = "A<n>_A"(내부 이름 — 기존 `var_name` 그대로), type: "A", bead: "a<n>", form: "hinge", nominal: 0.0, unit "mm", feasible: [0, d_max], feasible_source: "user", default_range: [0, d_max], use_default: virtual_bead.default_on(true), group_members: [name], label: "추가 비드 n · 깊이", wall_elems(= run/h), acc_hint?{code}(정확도 표 칸 — §9), vb{w_top, theta_deg, side(적용 방향 — §2.3), n_wall, n_top, len_mm, angle_deg}}`. `PARAM_TYPES += "A"`(`esl/doe/__init__.py:37`, 프런트 `DoeParamType`·`TYPE_NAME.A = "추가 비드 깊이"`) — paicad V·v0.24.9 R-PU-1 의 V 는 그대로(D-0.25.0-VB-13). basis.npz types U1 에 1글자라 dtype 불변.
- 비드 행(`param_beads`): `{id: "a<n>", name, kind: "virtual", warnings, vb_reason?}` — 거부된 가상 비드도 행(사유 1줄).
- 설계값 0 = 비드 없음. d000 = 공칭(모든 A = 0 = 지금 형상).
- 묶기(ties) 대상 아님(1차) — ties 에 a<n> 있으면 422 `BG_TIE_NOMINAL`(기존 코드).

### 5.2 기본 켬
- `matrix.default_params`(`:49-60`)·프런트 `defaultRows`(`doe.ts:1112-1117`): 조건 = `use_default ∧ (type ∈ doe.default_types ∨ form == "hinge")` — `default_types` 설정 불변(v0.24.9 U 는 use_default false 라 무영향).

### 5.3 공칭 0 보정 (v0.24.9 §1.3 재사용 — 중복 구현 금지)
- v0.24.9 가 넣는 "종류별 범위 규칙" 분기(`matrix.normalize_spec`·`rowProblem`·썸네일 색 범위)에 **행 1개(A 규칙)** 만 더한다. v0.24.9 머지 전이면 그 분기를 이 버전이 만들지 않고 재기반 뒤 추가(§11.2).
- range guard: §6.2. 민감도·보고서·재낙하 = 변경 없음(§0.2).

## 6. 품질 · range guard (지침 7)

### 6.1 점검
- BD_MATRIX `guard_selection`(`bead_graph.py:2248-`) carriers 에 켜진 A 변수 추가(가상 비드는 준비 표 `range_guard_table` 후보 아님 — 선택마다 생김). range guard 꺼진 스냅샷이면 `range_check` 경로(`stages.py:6857`)가 같은 morph 로 끝값 뒤집힘만 경고.
- 단일: [0, d_max] 를 `rgm.single` 로 — 끝 d_max 판정 + 위반이면 [0, d_max] 이분(중간값 판정 = 이분 단계, `steps` 기존 값). 기준 = 기존 accept(뒤집힘·jac·tri·넓이 비·새 fail 비율) **만**. **warpage 는 판정에서 뺌(개정 2, §19.2)**: A 항목 crit 에 `warp_max_deg` 를 넣지 않고(= 모든 항목 crit 이 문서 머리와 같음), usable 끝에서 `mesh_quality.guard_probe(…, warp_max_deg=)`(선택 인수 — 그대로) 로 `warp_bad_new`·`warp_max` 를 **재서 정보 `VB_WARP_INFO` 로만** 싣는다. `rgm.accept` 의 reason `"warp"` 가지는 crit 키가 없어 어느 항목에서도 타지 않음(코드 남겨도 됨).
- 조합: 같은 비드 안 변수 1개라 자체 조합 없음. **기존 그래프 비드 변수(D·DF·W·W1·U)의 띠·영향 요소가 A 지지 요소와 겹치면** `rgm.interacting(supports)` 가 자동 묶음(기존 코드 그대로 — supports 에 A 지지 요소만 넣으면 됨). 정보 `VB_BAND_OVERLAP{vbead, vars}`(겹침 있을 때).

### 6.2 한쪽 범위 보정
- `range_guard.blocked`(`:106-114`): 폭 0 인 쪽(|from − v₀| = 0)은 "막힘 아님"이 지금 동작 — 그대로. 대신 **"모든 쪽이 막힘" = 폭 > 0 인 쪽이 모두 막힘**으로(양쪽 범위 결과 동일 — 바이트 불변).
- SH-28(`bead_graph.py:2155`): `limited ∧ ¬(u_lo < nom < u_hi)` → `limited ∧ 폭 > 0 인 쪽 중 usable 이 공칭에 붙은 쪽이 있음`(D·W·U 결과 동일 — 공칭이 범위 안이므로). A: usable_hi ≤ 0 + 1e-4 일 때만 blocked. **기존 D·W(·v0.24.9 U) 범위 판정 표(준비 `range_guard.json`·`select/<sha12>/range_guard.json`·params guard)가 바이트 그대로임을 시험 V-0250-VB-9 로 고정**(D-0.25.0-VB-16).
- usable 상한 < d_max → `default_range = [0, usable_hi]`·`RG_RANGE_LIMITED`(기존 코드), blocked → use_default false·`RG_VAR_BLOCKED`.

## 7. 설정 · 스냅샷 · 해시 · 하위 호환 (지침 8·13)

### 7.1 설정 `bead_doe.virtual_bead` (같은 이름 4곳: `esl/doe/__init__.py` DEFAULTS·backend pydantic `BeadDoeVirtualBeadCfg`·`config/esl_platform.example.yaml`·`.prod.example.yaml`)
| 키 | 기본 | 범위 | 해시 |
|---|---|---|---|
| enabled | true | bool | 밖(새 스터디 블록 생성 여부) |
| max_count | 4 | 1..9 | 밖(422) |
| min_wall_elems | 2.0 | 1..10 | 안 |
| margin_mm | 3.0 | 0..50 | 안 |
| theta_default_deg | 45.0 | theta_range 안 | 안 |
| theta_range_deg | **[15.0, 60.0]** | 1..89 ∧ **상한 ≤ `select.quality.flip_deg`**(§19.4 — 어기면 `CONFIG_INVALID`) | 안 |
| **r_default_h_mult** | **1.0** | 0..4 | 안 |
| d_max_limit_mm | 30.0 | (0, 200] | 밖(422) |
| default_on | true | bool | 밖 |
| warp_max_deg | 15.0 | (0, 90) | 안 — **판정 기준이 아니라 정보 `VB_WARP_INFO` 의 세는 기준**(§19.2, 이름 유지) |
| preview_max_nodes | 50000 | 1000..10⁶ | 밖 |

### 7.2 스냅샷
- 새 select 그래프 스터디(설정 enabled)만 `doe.virtual_bead{schema: 1, min_wall_elems, margin_mm, theta_default_deg, theta_range_deg, warp_max_deg, r_default_h_mult}`(해시 안 키 사본 — `r_default_h_mult` 없는 블록 = 0.0, §19.1-7). 복제 = 원 블록 그대로(없던 스터디에 주입 안 함 — v0.24.7 §6.1·v0.24.9 §3 원칙).
- `_sel_cfg_sha`(`stages.py:7009-7025`) += `virtual_bead` 해시 보기 — **선택 문서에 virtual_beads 가 있을 때만**. 기저 재사용 조건 += `bj.get("vb_rules") == VB_RULES`(키 있을 때만), **`VB_RULES = 3`**(`virtual_bead.py` 상수 — 수치 바뀌면 +1; 개정 2 = 2, 개정 3 깊이 보상·방향 규칙 = 3. 코드 상수는 지금 1 — 개정 2·3 을 함께 구현해 3 으로).
- basis.json += `virtual_beads[{id, n_fp, h, n_wall, n_top, stretch_max, side, reasons}]`·`vb_rules`(가상 비드 있을 때만).

### 7.3 하위 호환 (지침 13)
- `virtual_beads` 없는 선택(옛·새 스터디 모두): 선택 sha·`select/<sha12>/{basis.npz, basis.bin, basis.json, params.json, derived.*}`·range_guard 문서·matrix·design.npz·result.json·ranking.csv·보고서·view3d·input_sha256·`_sel_cfg_sha`·derive 응답 바이트 동일. 골든 = **구현 직전 main 헤드**(v0.24.9 머지 뒤)에서 기록, 다시 기록 금지.
- 블록 있는 새 스냅샷이라도 가상 비드 0개면 위와 같음(블록은 스냅샷에만 — 해시·산출물 무관).

## 8. API · 스키마
| 위치 | 키 |
|---|---|
| `SelectionInV2` | `virtual_beads: list[VirtualBeadIn]`(§2.1) |
| derive 응답(`DoeDeriveOut`) | `virtual_beads[{id, name, p0, p1_resolved, len_mm, angle_deg(frame), side_resolved(**적용 방향** "+" \| "-" — 자동 규칙 + `flip` 뒤, §2.3), ok, reasons[{code, text}], warnings[], h, n_wall, n_top, outline_ab?, preview?{idx[], vec[[3]], g[], c}}]`, `vb_frame{origin, e_xi', e_eta', n_h}`(입력 칸 ξ·η ↔ 모델 좌표 변환용) — 가상 비드 있을 때만 키. preview = ok 인 비드만, 노드 수 > preview_max_nodes 면 생략 + `VB_PREVIEW_SKIPPED` |
| derive 캐시 키(`doe_select.py:449-454`) | 선택 sha 가 virtual_beads 를 포함하므로 추가 불필요(스냅샷 블록 sha 만 += — 블록 있을 때) |
| params[] | A 행(§5.1 — `wall_elems`·`acc_hint{h, d, theta, c_err_pct, pi_err_pct}`(정확도 표 `resources/vbead_accuracy.json` 에서 API 가 고름 — 표 밖 null)) |
| beads[](params·derive) | kind "virtual" 행, `vb_reason{code, text}` |
| basis.json·basis.bin | §4.2 선택 키·꼬리 |
| `GET /doe/settings` | `virtual_bead{enabled, max_count, theta_default_deg, theta_range_deg, d_max_limit_mm, min_wall_elems}` |
| 문구 | `resources/doe_messages.json` — VB_* 코드 문구(§3.2·§3.3·§6.1), 영문 꼬리 없음, API 가 text 동봉 |
- 백엔드 → 코어: `normalize_v2(…)` 시그니처 불변(문서 안 키), `derive_v2(…, virtual_bead=<스냅샷 블록>)`(`_graph_call` 이 받는 키만 넘김 — SH 선례), `fixed_tie_ids`(v0.24.9 PU-14 함수)를 derive 입력에 포함.
- openapi 재생성, `api/types.ts` `check:api`.

## 9. 화면 (지침 10 — 새 버튼 = [비드 추가]·[삭제]만, 2560×1440 가로 스크롤 없음)
- 위치: ③ 비드 목록·도구 카드(`BeadList`, 그래프 모드일 때만 — `ctrl.graphMode`) 목록 아래 접힌 절 "추가 비드(평판에 새 비드)"(기존 `<details>` 접기 — 버튼 아님). 블록 없는 스터디·범위 밖이면 절 숨김.
- 입력 줄 1(입력 방식 라디오 — 기존 `seg` 라디오 형식): ○ 3D 에서 두 점 ● 좌표·길이·각도.
  - 두 점: 라디오를 고르면 `Select3D` 클릭이 그래프 클릭 대신 점 찍기(`GraphTool` 에 `"vb"` 값 — 라디오 값이지 버튼 아님, `graphClick` 앞에서 분기). 첫 클릭 = p0(빨강 점 `setMarkers`), 둘째 = p1, 셋째 = 다시 p0. `pickElem` 이 host 판 밖 요소면 알림 "평판 위를 찍으세요"(`ctrl.notice`).
  - 좌표·길이·각도: ξ·η(mm, `vb_frame` 기준)·길이(mm)·각도(°, +ξ 기준) 칸 4개. 두 점으로 찍으면 이 칸이 자동으로 채워짐(같은 상태).
- 입력 줄 2(단면): 최대 깊이 D_max·깊이면 폭 W_top·사면 각 θ(기본 설정값)·**체크 칸 "방향 뒤집기" 1개**(기본 꺼짐 = 자동 방향 — 개정 3, 옛 라디오 ○ 기본 ○ + ○ − 는 없앰)·끝(반원|사각, select)·r(선택 — 비움 = 요소 크기) 칸. 칸 너비 ≤ 6em, 한 줄(2560)·두 줄 접힘(1920).
- [비드 추가] → 지금 선택 상태에 virtual_beads 항목 추가 → 기존 derive 흐름(디바운스) → 응답 사유·경고. [선택 저장]은 기존 버튼.
- 목록: 가상 비드마다 1행 — `A1 추가 비드 1 · L 120 mm · 30° · D≤5 W 20 θ45` + 상태(OK | 사유 배지 = 첫 사유 문구, 툴팁 = 전부) + 경고 배지 + [삭제]. 목록 머리(절 제목 "추가 비드") 툴팁 1곳(새 줄 없음): "추가 비드는 모핑으로 만든 근사 형상 — 유리한 후보는 실제 형상으로 ④ 비교나 재낙하로 확인"(문구 `doe_messages.json` `VB_LIST_TIP`, D-0.25.0-VB-18). 행 클릭 = 활성(3D 강조: `setOverlayLines` 로 중심선·발자국 윤곽 `outline_ab`).
- 미리보기: 활성 행 아래 깊이 슬라이더(0..D_max, `input type=range` — 버튼 아님) + 3D 변형. `SelectDesign3D` 의 그리기 부분을 **`MorphStage({glb, vars, values, vmax})`** 로 떼어(SelectDesign3D 는 이것을 감싸 동작·DOM 불변), 선택 화면은 derive `preview` 를 `BasisVar{form:"hinge"}` 로 바꿔 같은 `morph`·`heightChange` 로 그림(§4.2 — 워커와 같은 식). 슬라이더 위치 = 미리보기 패널 상단(가로 스크롤 없음).
- 변수 표(`DoeParamTable`): `b.kind === "virtual"` 가지 — 묶음 머리 `A1 추가 비드 1 · W 20 · θ 45° · L 120`, 행 라벨 = `label`("추가 비드 1 · 깊이"), 행 툴팁 = "사면 요소 {wall_elems:.1f}개 · 예상 오차 {acc}"(acc = 정확도 표에서 이 행의 h·D_max·θ 에 가장 가까운 칸의 C 차 — 원본 = `resources/vbead_accuracy.json`(문구 자료, 설정 아님 — 구현 때 V-0250-VB-11 측정값으로 채움, 행 `acc_hint{h, d, theta, c_err_pct, pi_err_pct}` 는 API 가 표에서 골라 동봉, 표 밖이면 "측정 범위 밖"), D-0.25.0-VB-19, 공칭 "0", 범위 mm, 경고(VB_WALL_COARSE 등) 배지, guard 꼬리표 기존 `ShapeTags`. 거부 비드 = 회색 1줄 "추가 불가 · <문구>". 계획 칩(`DoeStudy.tsx:1415`) = `A1 0`. 평면도 활성 변수(`:1408`)는 D·W 만(그대로).
- 2560·1920: 접힌 절 기본 = 접힘 → 페이지 scrollHeight ±0(가상 비드 없는 스터디), 펼침 시 표 안 스크롤 없이 ≤ 4줄 + 목록.

## 10. 결과 (지침 11)
- 변수 행·순위·민감도·보고서·재낙하 zip·형상 비교 3D·썸네일: 기존 경로 그대로(§0.2 — 실좌표·값만). 감사로 깨지는 곳 = 없음, 확인 시험 V-0250-VB-13.
- 표시 이름: 결과 표·민감도·보고서의 변수 이름 = `A<n>_A`(내부), 화면 라벨 = `label`("추가 비드 n · 깊이" — 없으면 이름). 재낙하 README 변수 값 줄 그대로(`A1_A = 3.2`).
- 재낙하 확인 권장 문구(결과 경고 줄 정보 1건 `VB_VERIFY_HINT`): "추가 비드 안은 모핑 근사입니다 — 유리한 안은 실제 형상(④ 또는 재낙하)으로 확인하세요"(가상 비드 변수가 있는 스터디만).

## 11. 작업 분해 (파일 소유 겹침 없음)

### 11.1 묶음
| 묶음 | 모델 | 파일 |
|---|---|---|
| C1 코어 | opus | `esl/morph/virtual_bead.py`(신규), `esl/morph/core.py`(`basis_term`), `esl/morph/section.py`(열 form·vb_host, 행 virtual, `vb_allowed`), `esl/morph/range_guard.py`(blocked 한쪽), `esl/doe/bead_select.py`(morph·fixed_violation_detail·save/load_basis·basis_bin·basis_meta), `esl/doe/bead_graph.py`(normalize_v2 키·개수, derive·`virtual_beads` 블록·V 행·`param_beads` kind virtual·basis_v2 V 항목·_Prober hinge·guard carriers·SH-28 보정), `esl/doe/matrix.py`(V 범위 규칙 행·default_params·썸네일 색), `esl/doe/mesh_quality.py`(guard_probe warp — 선택 인수), `esl/doe/transfer_plan.py`(열 vbead), `esl/doe/stages.py`(_sel_cfg_sha·재사용 조건·basis.json 키·VB_VERIFY_HINT), `esl/doe/__init__.py`(DEFAULTS·`PARAM_TYPES += "A"`), `resources/doe_messages.json`(VB_* · `VB_LIST_TIP`), `resources/vbead_accuracy.json`(정확도 표 — V-0250-VB-11 측정값), `tests/morph/test_virtual_bead*.py`·`tests/doe/test_vbead*.py`·`tests/doe/synth_vbead.py`, 골든 `tests/doe/golden_v0250_c1/` |
| B1 백엔드 | sonnet | `backend/esl_platform/core/config.py`(BeadDoeVirtualBeadCfg), yaml 2, `api/schemas.py`(VirtualBeadIn·SelectionInV2·derive 출력·settings), `api/services/doe_select.py`(selection_in·derive 인수·캐시 키), `api/services/doe.py`(스냅샷 블록·복제 보존·settings), openapi, `backend/tests/test_doe_v0250_*.py`(코어 e2e 1개 포함) |
| F1 프런트 | sonnet | `frontend/src/api/types.ts`·`api/doe.ts`(rowProblem A 행·defaultRows·TYPE 라벨), `view3d/select/basis.ts`(hinge), `components/BeadList.tsx`(추가 비드 절)·신규 `components/VirtualBeadPanel.tsx`, `components/BeadSelectCard.tsx`(GraphTool "vb"·찍기·overlay·`MorphStage` 추출), `components/DoeParamTable.tsx`(kind virtual 가지), `pages/doe/DoeStudy.tsx`(계획 칩), `mock/*.ts`, `__tests__/vbead*.test.ts(x)`, Playwright |
- 순서: C1 이 `virtual_bead.py` 시그니처·basis 형식(§4.2)·코드 표 첫 커밋 → B1·F1 병렬 → 통합(메인: CHANGELOG·user.md "추가 비드" 절(정확도 표 "얼마나 믿을 수 있나" 포함)·계약 §20 구현 메모(정확도 표)·admin 설정·`docs/manual/field_check_v0250.md`) → 독립 Verifier(옛 바이트·정확도 표 V-0250-VB-11 독립 재현).

### 11.2 v0.24.8 · v0.24.9 와 겹치는 파일 (두 버전 머지 뒤 재기반)
| 파일 | v0.24.8 | v0.24.9 | v0.25.0 | 접점 |
|---|---|---|---|---|
| `esl/doe/transfer_plan.py` | 계획 열 jig_fix·jig_ctx 값, `metric_effective(kind=)` | 열 `load_follow`, `load_follow_effective`, `metric_effective(spatial=)` | 열 `vbead` | 열 추가만 — `PLAN_COLS` 병합. V 는 `has_pos_var` 에 안 들어감 |
| `esl/doe/stages.py` | 지그 격자 실행기, `_plan_loads(srcs=)` | spatial 경로·`_plan_loads(placement=)`·해시 | `_sel_cfg_sha`·재사용 조건·basis.json | 함수 다름 — `_sel_cfg_sha` 는 v0.24.9 pos_u 해시 보기 뒤에 vb 보기 |
| `esl/morph/section.py` | – | 열 `pos`·`u_reason` | 열 form·vb_host·행 virtual | 같은 표 — 새 행 virtual 의 pos = none |
| `esl/doe/bead_graph.py` | – | U 행·`_nom`·`_var_key` U·guard U | A 행·normalize 키·_Prober hinge·SH-28 | `_Prober` 항 계산을 `basis_term` 으로 바꿀 때 U(선형)는 그대로 통과 |
| `esl/doe/matrix.py` | – | U 범위 규칙·썸네일 U | A 범위 행·default_params·썸네일 A | **같은 종류별 규칙 표에 행만 추가**(§5.3) |
| `esl/morph/core.py` | – | SR-D-38 `("W","U")` | `basis_term` | 다른 함수 |
| `esl/morph/range_guard.py` | – | 변경 없음 | blocked 한쪽 | – |
| `esl/doe/__init__.py`·config·yaml 2 | `rank.jig_grid` | `pos_u`·`load_follow` | `virtual_bead` | 다른 절 |
| `resources/doe_messages.json`·schemas·types·openapi | JIG_GRID_* | U_*·PU_*·LOAD_FOLLOW_* | VB_* | 키 병합, openapi 재생성 |
| `frontend/.../DoeParamTable.tsx`·`doe.ts`·`DoeStudy.tsx` | (DoeRanking 만) | U 행 라벨·순서·`.table-wrap.scroll` | kind virtual 가지·A 규칙 | v0.24.9 의 `.table-wrap.scroll` 조건 = "U 행 있음" → "U 또는 A 행 있음" |
| `packages/beadgraph/**` | – | kind U(1.3.0) | **무변경** | – |

## 12. 시험 (V-0250-VB-n)
1. 순수 `field`: 합성 평판(정렬 quad h 2, 판 300×200) 선분 L 120·W_top 20·θ 45°·60°·r 0: D ∈ {0, 0.5·d_max, d_max}(d_max 6)에서 면내 성분 ≤ 1e-12, 깊이면 노드(d ≤ W_top/2) 법선 변위 = D ± 1e-12, 사면 노드 = D − (d − W_top/2)tanθ ± 1e-12(> 0 일 때), 입구 밖 0, D = 0 → 전 노드 0(정확), D 단조. end square·round 각 1. r > 0: D = 0 → 0 정확, 둥글림 구간 연속(C¹ — 수치 미분 차 ≤ 1e-6).
2. `basis_term`: linear 항 = 지금 `(v − v₀)·vec` 와 바이트 같음(H5·H6 골든 기저로 morph 결과 sha), hinge 항 = §4.1 식 ± 1e-12, 여러 변수 합 = 개별 합.
3. 놓을 곳: 합성(평판 + 채널 비드 + 보스 섬 + 구멍 + 판 외곽 + fixed 노드 + exclude) — 사유 코드마다 위반 1개씩 → 그 코드(순서 고정, 전부 목록), 위반 없음 → ok, 두 가상 비드 겹침 → VB_OVER_VBEAD 둘 다, margin 경계(d_chk ± 0.1)에서 판정 뒤집힘.
4. 해상도: h 5·3·1.5 에 run 4 → h 5 = VB_MESH_COARSE, h 3 = VB_WALL_COARSE(n_wall 1.33), h 1.5 = 경고 없음(min_wall_elems 2), W_top 경계 각 1.
5. 선택 문서: 키 없음·빈 목록 → 정규화 JSON·sha = main(옛 골든 3개), 형식 오류·개수 초과 422, (a)/(b) 형식 정규화, 가상 비드만 있는 선택 허용, beads 0 + virtual 0 = 기존 오류 그대로, ties 에 v1 → 422.
6. 계획 표: 새 열·행 모든 칸(빈 칸 CONFIG_INVALID), `vb_allowed` 진리표(5 계획 × 5 행), paicad same(case_once) = 불가, 호출 쪽 시나리오 이름 분기 0(정적).
7. basis 형식: hinge 없는 basis.npz·basis.bin·basis.json 바이트 = main, hinge 있음 → npz 키 form·g·c, bin 꼬리, 왕복(save→load) 같음, 브라우저 `parseBasis` 길이 검사(꼬리 빠짐·남음 = 오류).
8. 브라우저 = 워커: 같은 values 로 `basis.ts morph` 와 `bead_select.morph` 차 ≤ 1e-4 mm(float32, V-BS-12 기준), derive preview 로 만든 BasisVar 결과 = basis.bin 결과(같은 선택).
9. range guard(**개정 2: θ 75° 는 입력 불가 — 위반 세계는 V-0250-VB-21 의 것으로 바꿈, warp 문장은 §19.2 로 대체**): 합성 평판에 끝 위반이 나는 가상 비드 → d_max 끝 위반 → usable_hi < d_max·`RG_RANGE_LIMITED`(blocked 아님 — SH-28 보정), usable_hi = 0 → blocked, A 항목 crit 키 없음(모든 항목 crit = 문서 머리 — §19.2), **기존 D·W·U 범위 판정 표 바이트 = 골든**(준비 range_guard.json·선택 range_guard.json·params guard — H5·H6·synth, v0.24.9 U 스터디 포함; 한쪽 보정이 양쪽 범위에 영향 없음), W 띠가 A 지지와 겹치면 조합 묶음·`VB_BAND_OVERLAP`.
10. 기본 켬·범위 규칙: A 행 use_default true → default_params 에 포함(`default_types [D, W]` 그대로), lo < 0 → 422 문구, lo = 0 통과, `_POSITIVE` 경로 불변, U 규칙(v0.24.9)과 같은 표.
11. **정확도(지침 12 — 사용자 신뢰 기준, D-0.25.0-VB-17)**: 합성 평판 400×300·t 1.0·E 210 GPa(합성 `synth_vbead` — 정렬 quad, gmsh 없음, 결정적), 비드 L 200·W_top 20. (A) **실제 메시 비드** = 사면 각·깊이면 폭·깊이가 같은 **사다리꼴 단면, 모서리 반경 0**(노드 행이 깊이면 가장자리·입구 선에 정확히 놓인 구조 격자 — 요소 경계 = 모서리), (B) **가상 비드** = 같은 h 균일 평판 격자 + 힌지 모핑(r 0). 두 모형 **같은 하중(균일 압력 1·집중 하중 1)·같은 지지**에서 컴플라이언스 C(solve)와 지그 Π(v0.24.4 `METHODS` 강제 변위 prescribed·스프링 spring 둘 다)를 비교. 표 = h 5·3·1.5 mm × D 3·6 mm × θ 45·60° (12칸 × 지표 3) — C_B/C_A − 1·Π_B/Π_A − 1(%)·wall_elems. **h 3 에서 |차| ≤ 5 %(초안 — 측정 후 확정)**, h 1.5 차 ≤ h 3 차(수렴 방향), run < h 칸은 VB_MESH_COARSE 로 표에 "불가" 표기·run < 2h 칸은 VB_WALL_COARSE 표기. 표는 `tests/doe/vbead_accuracy.md`(시험이 대조)·`resources/vbead_accuracy.json`(화면 툴팁 자료)·**계약 구현 메모(§20 — 구현 때 추가)·사용자 매뉴얼 `docs/manual/user.md` "추가 비드 — 얼마나 믿을 수 있나" 절**에 같은 값으로 싣는다(사용자가 모핑 비드 신뢰도를 이 표로 판단).
12. (**개정 2: 평탄부 = plateau host 로 실제 derive — V-0250-VB-23 이 대체, 측정 기록 work/vbead_h6.md 는 r 0·warp 판정 시절 값으로 보존**) **비정렬 실제 모형 H6**(v0.24.7 교훈 — 기본 범위 끝까지 독립 측정): H6 평탄부(부모 바닥 판)에 가상 비드 2개(ξ 방향 1·30° 1, W_top 15·θ 45°·d_max 5)를 놓아 ok 확인 → D = d_max·0.5·d_max 에서 뒤집힘 0, 품질 위반 수(jac < jac_min·tri < 기준·warp > 기준 새 요소 수) 기록, range guard usable 기록(blocked 아님), 허용 구역(발자국) 밖 이동 ≤ 1e-12. 위반이 있으면 시험은 완화하지 않고 측정값을 계약 §15 에 적어 메인 결정.
13. 결과 경로 e2e: 합성 그래프 스터디(그래프 비드 1 + 가상 비드 1 켬) → BD_MATRIX → 미리보기 grid → BD_EVAL → BD_POST → API: 변수 행·순위·민감도(V1_D 행)·보고서·view3d(design.npz 좌표 = morph 결과)·재낙하 zip(바뀐 노드 = 발자국 노드만, max_disp = d_max 안 값) 정상, d000 = 가상 비드 없는 같은 스터디 d000 결과와 같음(공칭 0 = 지금 형상).
14. 하위 호환(지침 13): 구현 직전 main 헤드 골든(sel_regress·selreg ①②③, v0.24.6 그래프 스터디, v0.24.9 U 스터디, ④ regress) — virtual_beads 없는 선택·블록 있는 새 스냅샷 + 가상 비드 0 두 경우 §7.3 파일 전부·input_sha256·`_sel_cfg_sha`·derive 응답 동일.
15. 하중: A 변수 있는 스터디 `load_follow_effective` = node(v0.24.9), lin 보조 열 null 아님, 지그 tie 노드 변위 0.
16. 설정 거울: DEFAULTS = pydantic = yaml 2(**11키** — 개정 2 `r_default_h_mult`), 범위 검사, 해시 안 키만 `_sel_cfg_sha`(virtual_beads 있을 때만), 복제 = 원 블록.
17. API·화면: 422 2종, derive `virtual_beads`·`vb_frame`·preview(상한 넘으면 생략 + 정보), 두 점 찍기(mock pickElem)·좌표 칸 자동 채움·각도 ξ 기준 왕복(±1e-3°), [비드 추가]·[삭제]·사유 배지·슬라이더 미리보기 변위 = §4.1, `SelectDesign3D` DOM 스냅숏 불변(`MorphStage` 추출 뒤), 변수 표 kind virtual 가지·라벨·거부 1줄, 2560·1920 가로 스크롤 없음·접힘 상태 scrollHeight ±0, mock.
18. 비용: 합성 120×80(9,801 노드) 가상 비드 1·4개 — derive 추가 시간·BD_MATRIX 기저 추가 시간·guard 추가 평가 수·안 1개 morph 추가 시간·basis.npz 크기 증가 기록, 목표 = §13 추정 이내.
19. **가상 비드만 있는 선택**(그래프 비드 0, D-0.25.0-VB-15): 합성 평판(분류 결과 있음·fixed 노드·지그 tie 있음)에 A1 1개 → 정규화 통과·sha, `flip` 없음 = frame n 반대쪽(결정적), fixed·tie 노드에 겹치게 놓으면 VB_FIXED, range guard 단일 점검 실행(조합 0)·usable 기록, BD_MATRIX → BD_EVAL d000·d001 정상, GRAPH_FAILED 스터디 = VB_SCOPE, beads 0 + virtual 0 = 기존 SELECT_EMPTY_TIER 그대로.

## 13. 비용 추정 (가상 비드 1개당 — 측정 V-0250-VB-18 로 확정)
| 단계 | 추가 | 추정(10만 노드 판, 발자국 3천 노드) |
|---|---|---|
| derive(API, 저장 전 매번) | 선분 거리(bbox 안 노드만)·마스크 검사·법선·h·preview JSON | 20~60 ms, 응답 + 3천 × 7 수(≈ 100 KB) |
| BD_MATRIX 기저 | 같은 계산 + 저장(노드당 float 4개) | 30~80 ms, basis.npz + 약 100 KB |
| range guard | 단일 1개 = 끝 1 + 이분 `steps` 회 국부 탐침(발자국 요소 ~3천) | 0.1~0.5 s(조합 있으면 묶음당 + 꼭짓점 수 × 같은 탐침) |
| 안 평가 | morph 항 1개(O(n_fp)) | < 1 ms — 풀이 시간 대비 무시(풀이 횟수 불변) |
| 미리보기 셀 | 같은 morph + 썸네일(기존) | 변화 없음 |

## 14. 미결 (결과를 바꾸는 것만 — 기본 가정으로 진행)
- **Q-VB-1 메시 해상도 거부 기준** — 기본: run < 1·h 거부, 1·h ≤ run < 2·h 경고(VB_WALL_COARSE). 대안: run < 2·h 거부(정확도 기준 V-0250-VB-11 측정 결과로 다시 정함).
- **Q-VB-2 host 범위** — **결정(개정 2, D-0.25.0-VB-23): 부모 바닥 + 평탄 영역(area·plateau)**. 골격 있는 기존 비드의 깊이면 위는 계속 범위 밖(R-VB-7).
- **Q-VB-3 방향 기본** — **결정(개정 3, D-0.25.0-VB-27): 자동(평탄부 = 들어간 쪽, 그 밖 = 그래프 비드 다수 쪽, 없으면 frame n 반대) + 사용자 뒤집기 `flip`**(§19.9.2).

## 15. 불일치 — 메인 결정 완료 (2026-11-26, 본문 반영)
- **X-VB-1 → D-0.25.0-VB-13**: 변수 종류 = 새 문자 **"A"**(added — 추가 비드 깊이, hinge 형식). 가상 비드 id `a<n>`(소문자 — 그래프 비드 `b1` 과 맞춤, D-0.25.0-VB-20), 변수 이름 = 기존 `var_name(bid, type)` 그대로(`A1_A` — 내부 이름), 화면 "추가 비드 n · 깊이". `PARAM_TYPES += "A"`, paicad V·v0.24.9 R-PU-1 의 V 자리는 그대로. 지침 4 의 `V<n>_D` 표기는 대체됨(§5.1).
- **X-VB-2 → D-0.25.0-VB-14**: 미리보기 = D 수준 표 보간 대신 basis·derive preview 에 노드별 g 를 실어 정확히 계산(§4.2·§9).
- **X-VB-3 → D-0.25.0-VB-15**: 선택 필수 조건 = `beads + virtual_beads ≥ 1`(가상 비드만 있는 스터디 허용, §2.1 — 그래프 비드 0개일 때 방향 기본·fixed·range guard 동작 명시, 시험 V-0250-VB-19).
- 승인(D-0.25.0-VB-16): SH-28·`range_guard.blocked` = "폭 > 0 인 쪽만 판정"(§6.2), 기존 D·W·U 표 바이트 불변을 시험으로 고정(V-0250-VB-9). Q-VB-1~3 기본 가정 그대로.

## 16. 결정 요약 — 전문 `docs/decisions.md` 2026-11-26 D-0.25.0-VB-1~12(초안)·VB-13~20(개정 1)·**VB-21~25(개정 2 — §19)**·**VB-26~28(개정 3 — §19.9)**.

## 17. 후속 (R-VB-n)
- R-VB-1 위치·각도·길이 연속 변수(안마다 발자국·g 재계산 — 기저 고정 불가, 안 평가 비용 + 발자국 검사 안마다).
- R-VB-2 곡선·꺾인 중심선(폴리라인 거리 — `field` 일반화).
- R-VB-3 노드를 모서리 선에 맞추는 r-적응(국부 노드 재배치 → 모서리 뭉개짐 감소, 하중 공간 고정 필요 — v0.24.9 spatial 재사용).
- R-VB-4 기존 비드와 교차·접합(부분 겹침 허용, 접합 구역 규칙).
- R-VB-5 폭 W_top 변수(g 가 W 에 따라 바뀜 — 2변수 힌지 항).
- R-VB-6 선택(요소)·paicad·④ 에서의 추가 비드(④ 는 형상 자체가 입력 — 문서화만).
- R-VB-7 골격 있는 기존 비드의 깊이면 위 host(비드 안 비드). 평탄 영역(area·plateau) 몫은 개정 2 에서 이번 버전으로 옮김(§19.3).
- R-VB-8 가상 비드 대칭 묶기.

## 18. 현장 확인 (F-VB-n — `docs/manual/field_check_v0250.md` 는 통합 때)
- F-VB-1 #88 모델 평탄부(부모 바닥)에 후보 비드 2~3개(하중 경로를 가로·나란히·대각): derive 사유·경고(n_wall·n_top·h), 화면 두 점 찍기·좌표 입력 왕복.
- F-VB-2 그 스터디 실행: A<n>_A 민감도(SRC·ρ)·순위, 미리보기 3D 로 입구 넓어짐·깊이면 폭 유지 눈 확인, range guard usable.
- F-VB-3 가장 유리한 후보 1개를 실제 형상(④ 형상 직접 비교 또는 재낙하)으로 확인 — 가상 비드 안 대비 C·Π·재낙하 소성 변형률 순서 일치 여부(정확도 표 V-0250-VB-11 과 대조).

## 19. C1 보정 — 사용자 결정 11-26 (개정 2, D-0.25.0-VB-21~25)

C1 측정(work/findings.md VB-C1-5·6·7, work/vbead_h6.md)에 대한 사용자 결정 3건을 구현 가능한 수준으로 적는다. **본문과 다르면 이 절이 우선**. 코드 기준 = release/v0.25.0 7dfc71d6. **개정 3(§19.9)이 이 절의 §19.1-3·4·6, §19.3-4, §19.5-3·4 를 고쳤다 — 해당 줄에 표시.** 이 절로 바뀌는 수치 규칙은 `VB_RULES 1 → 2`(개정 3 까지 = 3 — 가상 비드가 있는 선택의 기저만 다시 만듦 — 가상 비드 없는 선택은 §7.3 그대로 바이트 불변). v0.25.0 은 출시 전이라 `VB_RULES 1`·`2` 산출물을 가진 운영 스터디는 없다.

### 사용자 결정 원문 (변경 금지)
1. VB-C1-5: 모서리 둥글기 r 기본 = h(대상 메시 요소 크기; 사용자 입력 r 이 있으면 그 값). 근거(사용자 확인): 낙하 메시는 h 미만 r 을 표현 못 하므로 r = h 가 직접 메시한 비드의 단순화 수준. 가상 비드(A) 항목의 warp 는 range guard 에서 막지 않고 정보로만; 뒤집힘·jac·tri 위반은 계속 막음. 기존 D/W/U 판정·결과 바이트 불변.
2. VB-C1-6: 평탄 영역(plateau, floor kind area)도 host 로 허용(Q-VB-2 대안 채택, R-VB-7 을 이번 버전으로). H6 넓은 평탄부·#88 유사 모형에 놓을 수 있어야 함.
3. VB-C1-7: θ 입력 범위 [15, 60]°, select.quality.flip_deg 와의 관계를 설정 검증 규칙으로 명시.

### 19.1 r 기본 = 요소 크기 (D-0.25.0-VB-21)
1. **설정 키** `bead_doe.virtual_bead.r_default_h_mult` — 기본 **1.0**, 범위 [0, 4], 해시 안(`HASH_KEYS` += 이 키, 스냅샷 블록에 복사). 0 = 기본 r 0(개정 1 동작). 4곳 같은 이름(§7.1).
2. **h 의 정의(하나로 확정)**: h = **r 0 발자국** {d < W_top/2 + d_max·cotθ} 의 노드를 가진 host 요소의 **변 길이 중앙값**(`virtual_bead.edge_median` — 지금 §3.3 의 h 와 같은 함수·같은 값). r 을 정한 뒤 넓어진 발자국으로 h 를 다시 구하지 않는다(한 번 — 결정적). §3.3 해상도 판정·`wall_elems`·`acc_hint` 의 h 도 이 값.
   - 결정 근거: 중앙값은 지금 코드가 이미 쓰는 대표 크기이고, 되풀이 계산을 없애면 같은 입력 → 같은 r.
3. **해석 순서**(derive·basis 같은 함수): ① r 0 발자국 → h ② r 생략이면 `r = round(min(r_default_h_mult·h, r_cap), 1e-4)`, 준 값이면 그 값(0 포함) ③ 그 r 로 발자국(d_move = W_top/2 + (e(d_max) + c)·cotθ = W_top/2 + d_max·cotθ + 1.25·r·tan(θ/2) — 개정 3 깊이 보상 몫 포함, §3.1)·검사 띠·host 검사·장(`field`) 계산. h 가 없으면(발자국 요소 없음) 지금처럼 `VB_NOT_ON_PLATE`.
4. **기하 유효 조건** `virtual_bead.r_cap(w_top, theta_deg, d_max)` = min(r₁, r₂):
   - r₁ = W_top / sinθ — 깊이면 양쪽 둥글림이 가운데서 만나지 않음(2a ≤ W_top, a = r·sinθ/2 — §4.1 의 a 와 같은 값).
   - r₂ = d_max·cotθ / (sinθ/2 + **0.75**·tan(θ/2)) — d_max 에서 깊이면 쪽 둥글림(폭 a)과 입구 쪽 둥글림이 사면에서 겹치지 않음: (e(d_max) − c)·cotθ ≥ a, e(d_max) = d_max + c/4(**개정 3** — 보상으로 입구 둥글림이 c/4·cotθ 바깥으로 가서 옛 계수 1 → 0.75). 이 조건이면 d_max ≥ 3c/4 + a·tanθ 라 d_max 는 늘 보상의 선형 가지(e = D + c/4)에 있다.
   - **준 r > r_cap + 1e-4 → 422 `VB_INPUT_INVALID`**(detail `{vbead, key: "r", r_max}` — 입력만으로 판정되므로 정규화에서). 기본 r 은 거부하지 않고 r_cap 으로 줄임 + 정보 `VB_R_CLAMPED{r, r_h}`(r_h = r_default_h_mult·h). 참고(개정 3 계수): §3.2 `VB_MESH_COARSE`(run ≥ h, W_top ≥ h)를 통과한 비드는 θ ∈ [15, 60]·`r_default_h_mult` 1 에서 줄임이 일어나지 않는다(r₂ ≥ 1.155·run, r₁ ≥ 1.155·W_top) — `VB_R_CLAMPED` 는 mult > 1 일 때만.
   - 결정 근거: 조건을 넘는 r 은 지정한 W_top·θ 가 단면에 나타나지 않는다(이름과 다른 형상) — 조용히 받는 것보다 막는 편이 변수 의미를 지킨다.
5. **정규화**: r 은 "기본값 키 생략" 대상에서 뺀다 — 준 값은 0 이어도 키를 남긴다(`"r": 0.0` = 각진 모서리, 키 없음 = 요소 크기 기본). 그래서 r 없는 문서와 r 0 문서는 sha 가 다르다.
6. **실제 깊이 = 변수 값(개정 3 — 옛 "표시만" 철회)**: 깊이 보상 e(D)(§4.1·§19.9.1)로 비드 가운데 실제 깊이 = D. **`depth_max_mm` 키는 삭제**(derive·변수 행·`vb`·정확도 표 어디에도 싣지 않음 — 늘 d_max 와 같은 값). 보상량 예: h 3·θ 45° → c 1.243, c/4 0.31 mm; h 3·θ 60° → c 3.0, c/4 0.75 mm.
7. **호환**:
   - 가상 비드 없는 선택(옛·새 스터디): 변화 없음(§7.3).
   - `r_default_h_mult` 없는 스냅샷 블록(개정 2 전 개발 중에 만든 스터디): **0.0 으로 읽음**(없던 규칙을 주입하지 않는 원칙 — 복제도 원 블록 그대로). 새 스터디만 설정값 복사.
   - 개정 2 전 문서의 가상 비드는 r 0 이 정규화에서 빠져 있었다 → 다시 읽으면 "기본"으로 해석된다(블록 키가 없으면 0.0 이라 결과 같음, 새 블록이면 r = h). 출시 전이라 이행 처리 없음.
   - 옛 A 없는 스터디(`doe.virtual_bead` 블록 없음) = 지금처럼 `VB_SCOPE`.

### 19.2 warp 는 정보로만 (D-0.25.0-VB-22)
1. **판정에서 제외**: A 항목 range guard 의 state(ok | limited | blocked)·usable·`RG_RANGE_LIMITED`·`RG_VAR_BLOCKED`·SH-28(`side_stuck`)·조합 묶음(`interacting` 꼭짓점 판정) 모두 **기존 accept 기준만**으로 정한다 — 뒤집힘(flip_deg)·jac_min·tria 각·넓이 비·새 fail 비율(D·W·U 와 같은 crit, 같은 함수). A 전용으로 더했던 `crit.warp_max_deg` 는 싣지 않는다(선택 `range_guard.json` A 항목에 `crit` 키 없음). 기존 accept 안에 이미 들어 있는 품질 항목은 건드리지 않는다(D·W·U 표 바이트 불변 — V-0250-VB-9 골든 그대로).
2. **측정**: A 항목마다 **usable 상한**(막힘이면 d_max)에서 그 변수만 움직인 형상의 `guard_probe(…, warp_max_deg=블록 warp_max_deg)` → `warp_bad_new`(공칭 ≤ 기준 ∧ 안 > 기준인 quad 수)·`warp_max`(°). 이미 평가한 점이면 그 값을 쓰고 아니면 평가 1회 추가(비용 V-0250-VB-18 다시 기록).
3. **자료**: 선택 `range_guard.json` A 항목 += `warp{limit_deg, n, max_deg, at}`(늘 있음 — n 0 가능), params A 행 `guard.warp` = 같은 값(+ API 가 n > 0 일 때 `text`). range guard 꺼진 스냅샷(`range_check` 경로)은 키 없음.
4. **정보 코드** `VB_WARP_INFO{n, max, d}`(level info — 경고·실패 아님, 기본 켬·범위에 영향 없음). `resources/doe_messages.json` 문구:
   - `"VB_WARP_INFO": "깊이 {d} mm 에서 뒤틀린 사각 요소 {n} 개(최대 {max}°) — 꺾인 모서리가 요소를 비스듬히 지나서 생김. 범위는 줄이지 않음"`
   - `"VB_R_CLAMPED": "모서리 둥글기를 {r} mm 로 줄임(요소 크기 {r_h} mm 는 이 단면에 들어가지 않음)"`
   - `"VB_PLATE_EDGE": "판·평탄부 가장자리에 닿음"`(문구만 바뀜 — §19.3)
   - `"VB_THETA_FLIP": "추가 비드 사면 각 상한({theta_hi}°)이 뒤집힘 기준 select.quality.flip_deg({flip}°)보다 큼"`(§19.4)
5. **화면(F1)**: 변수 표 A 행의 guard 꼬리표(`ShapeTags`) 옆 **회색 정보 꼬리표 "뒤틀림 {n}"**(n > 0 일 때만, 툴팁 = `guard.warp.text`). 색·아이콘은 정보 단계(경고 색 금지), 새 줄 없음. 추가 비드 목록(선택 화면)에는 없음 — derive 는 range guard 를 돌리지 않는다. B1 은 `guard.warp` 를 그대로 전달 + text 동봉.
6. **정확도 표와의 관계**: warp 는 요소 모양 지표이고, 강성 결과를 얼마나 믿을지는 정확도 표(§19.5)가 답한다. 정확도 표 칸에 같은 방법으로 잰 `warp_n`·`warp_max_deg` 를 함께 싣어 "뒤틀림이 이 정도일 때 오차 몇 %"를 한 표에서 본다. 행 툴팁의 예상 오차(`acc_hint`)는 그대로.
7. `warp_max_deg` 설정 키는 이름·기본(15)·해시 안 그대로 — 뜻만 "세는 기준".
   - 결정 근거: 키 이름을 바꾸면 4곳 거울·스냅샷·B1 이 함께 바뀐다. 뜻은 이 절과 §7.1 표에 적는다.

### 19.3 평탄 영역 host (D-0.25.0-VB-23)
1. **host 종류**: `virtual_bead.VB_HOST_SEG_TYPES = ("base", "area", "plateau")`(상수 한 곳 — 호출 쪽 문자열 비교 금지). host 요소 = `cls == floor` ∧ 세그먼트 종류 ∈ 이 표 ∧ `junction_zone < 0` ∧ `island < 0` ∧ ¬exclude ∧ **`wall_islands()` 가 고른 floor 아님**(벽에 먹힌 보스 — `VB_OVER_ISLAND` 로 셈). 골격이 있는 비드(세그먼트 종류 없음 = 채널 비드)의 깊이면은 host 아님(`VB_OVER_BEAD` — R-VB-7). 계획 표(`vb_host`·`vbead`)는 값·판정 그대로.
   - **놓이는 면**: 평탄 영역의 floor 라벨 요소 = 부모 바닥에서 들어간(또는 올라온) **평탄면 자체**(벽·transition 제외). 평면 (p_h, n_h) 는 지금처럼 그 floor 요소의 국부 최소제곱(§2.2 — 씨앗과 같은 floor 만).
2. **가장자리**: host floor f 의 **바깥 테두리 transition** = graph `transitions[]` 중 `child == f` 인 것(f 와 그 부모 floor 사이 벽). 검사 띠 E_chk 가
   - 바깥 테두리 transition 요소를 포함 → **`VB_PLATE_EDGE`**(평탄부 가장자리 벽에 닿음). 이때 그 벽 너머 부모 floor 요소는 `VB_NOT_ON_PLATE` 로 세지 않는다(같은 원인 — VB-C1-1 "설명되지 않는 것만" 원칙).
   - 그 밖 transition 요소(f 위의 자식 비드 벽, 접합) → `VB_OVER_BEAD`(지금과 같음).
   - transition 라벨이 없는 벽·다른 floor → `VB_NOT_ON_PLATE`(지금과 같음).
   - host = base 는 `child == root` transition 이 없으므로 결과가 개정 1 과 같다(판 외곽 자유 모서리 = `VB_PLATE_EDGE` 그대로).
3. **거리 규칙**(새 설정 없음 — 모두 검사 띠 d_chk = d_move + `margin_mm` 한 가지): 가장자리 벽·이웃 비드·섬·구멍·체결부(fixed-scan ∪ fixed_user ∪ 지그 tie)·제외 영역·다른 추가 비드까지 **발자국 끝에서 margin_mm(기본 3) 이상**. 평탄부 위의 구멍 = `VB_OVER_HOLE`, 평탄부 위 체결부 = `VB_FIXED`(base 와 같은 마스크). 사유 순서(`REASONS`)·"전부 목록" 그대로.
   - 결정 근거: host 종류마다 다른 여유를 두면 계획 표 열이 늘어난다. 벽 발치는 transition 라벨이 이미 덮는다.
4. **방향(어느 쪽으로 눌리나)**: n_h = host 평면 법선(그래프 frame n0 쪽으로 맞춤 — VB-C1-2), side "+" = n_h 쪽. **생략 기본**: host 가 평탄 영역이면 **그 평탄부가 부모 바닥에서 들어간 방향과 같은 쪽**(= sign(floors[f].level − floors[parent(f)].level) 을 n0 기준으로 — 더 깊어지는 쪽), level 차가 0(|차| ≤ 1e-6 mm)이면 §2.3 다수결. host = base 는 §2.3 그대로. **`flip` true 면 이 자동 방향의 반대(개정 3 — §19.9.2, 사용자 결정 "자동 + 사용자 뒤집기")**.
   - 결정 근거: 평탄부 평면을 기준으로 하면 기존 비드 바닥이 양쪽에 섞여 다수결이 뜻을 잃는다. "기존 형상과 같은 쪽"이라는 메인 지침의 최소 해석(사용자 확정 — §19.8-2).
5. **기존 기저와 겹침**: 평탄 영역이 선택된 그래프 비드(D 변수 — area floor 는 D 만)이면 발자국 노드는 그 D 기저의 지지 안에 있다.
   - 좌표 = 항의 합(§4.2 `basis_term` — 순서 무관): 평탄부가 D 로 움직인 위에 추가 비드가 얹힌다. A 의 g·방향은 공칭 형상 기준 고정.
   - range guard: `rgm.interacting(supports)` 가 A 와 그 D(및 띠가 닿는 이웃 변수)를 **항상 조합 묶음**으로 점검(기존 코드 — supports 에 A 지지 요소만 넣으면 됨), 정보 `VB_BAND_OVERLAP{vbead, vars}`.
   - 평탄부를 선택하지 않았으면(변수 없음) 단일 점검만.
   - 고정 침범·바깥 이동(BG-D-34)은 변수별 idx 기준 그대로.
6. **load_follow · U**: A 는 면내 이동 0 → host 종류와 무관하게 `has_pos_var` 아님(node 하중 유효). 평탄 영역은 U 불가(`U_AREA`)라 host 자신의 U 는 없다. 이웃 비드의 U 띠가 발자국과 겹치면 ⑤ 와 같은 조합 점검 + `VB_BAND_OVERLAP` — 그 스터디는 U 때문에 이미 spatial 이고, 추가 비드 노드는 U 만큼 면내로 함께 움직인다(g 는 노드에 붙은 값 — 허용, 막지 않음).
7. basis.json `virtual_beads[]`·derive `virtual_beads[]`·변수 행 `vb` += `host: "base" | "area" | "plateau"`·`host_floor`(floor id).

### 19.4 θ 범위 · 설정 검증 (D-0.25.0-VB-24)
1. `theta_range_deg` 기본 **[15.0, 60.0]**.
2. **설정 검증 규칙**(설정을 읽을 때 — 코어 `esl.doe` 설정 로더와 backend pydantic 모델 검증 둘 다, 같은 식): `1 ≤ lo < hi ≤ 89`, `theta_default_deg ∈ [lo, hi]`, **`theta_range_deg[1] ≤ select.quality.flip_deg`**(같아도 통과). 어기면 **`CONFIG_INVALID`**, 문구 = `VB_THETA_FLIP`(§19.2-4), detail `{key: "bead_doe.virtual_bead.theta_range_deg", theta_hi, flip_deg}`.
   - 결정 근거: 사면 요소는 θ 만큼 법선이 돈다 → θ > flip_deg 이면 늘 "뒤집힘"으로 막힌다(VB-C1-7 측정). 새 오류 코드 대신 기존 `CONFIG_INVALID` + 전용 문구(설정 오류 코드는 하나라는 지금 관례).
3. **스냅샷 쪽**(설정이 바뀐 뒤의 옛 블록 대비): 가상 비드 θ 의 유효 상한 = min(블록 `theta_range_deg[1]`, 그 스냅샷의 flip_deg — `_crit` 가 읽는 값). 넘는 `theta_deg` → 422 `VB_INPUT_INVALID`(key theta_deg).
4. **경계 θ = flip_deg**: 뒤집힘 판정은 `cos(각) < cos(flip_deg)`(`mesh_quality.inverted_count`)라 정확히 같은 각에서 부동소수 오차로 걸릴 수 있다 → 장 계산에 쓰는 각만 **θ_f = min(θ, flip_deg − `VB_FLIP_EPS_DEG`)**, `VB_FLIP_EPS_DEG = 0.01`(`virtual_bead.py` 상수, VB_RULES 에 포함). 표시·저장·발자국의 θ 는 입력값. `mesh_quality` 판정식은 바꾸지 않는다(D·W·U 바이트 불변).
5. `GET /doe/settings` `virtual_bead.theta_range_deg` 는 설정값 그대로(화면 칸 min·max).

### 19.5 정확도 표 다시 재기 (D-0.25.0-VB-25)
1. **결정: 다시 잰다.** 기본 동작이 r = h 로 바뀌어 지금 표(r 0)는 사용자가 실제로 돌리는 형상의 오차가 아니다.
2. 비교: (A) 그대로 — 모서리 정렬 실제 메시 사다리꼴(모서리 반경 0, 같은 W_top·θ·D) = "그 요소 크기로 직접 메시한 비드". (B) 균일 격자 + 힌지 모핑 **r 생략(기본 = min(h, r_cap))**. h → 0 이면 r → 0 이라 (A) 로 수렴해야 한다.
3. 칸: h 5·3·1.5 × D 3·6 × θ 45·60°(12칸 — 그대로), 지표 C 압력·C 집중·Π 강제 변위·Π 스프링 + **추가 열 `r`(해석된 값)·`warp_n`·`warp_max_deg`(§19.2-6)**(`depth_mm` 열 없음 — 개정 3: 칸의 D 가 (A)·(B) 공통의 **실제 깊이**).
4. 기준(그대로, 완화 금지): h 3 에서 |차| ≤ 5 %, h 1.5 최대 |차| ≤ h 3 최대 |차|, run < h 칸 "불가". 넘으면 시험을 고치지 않고 측정값을 findings 에 적어 메인 결정(**개정 3: 비교 기준 = 실제 깊이** — (B) 의 변수 값 D = 실제 최대 깊이 = (A) 의 깊이라 깊이 차로 생기는 치우침은 없다. 남는 차 = 모서리 둥글림과 입구가 한쪽 r·tan(θ/2)/4 넓은 것).
5. 파일: `resources/vbead_accuracy.json` schema `esl/vbead_accuracy/2` — `cells`(r 기본) + **`cells_r0`(지금 값 그대로 보존 — 다시 계산하지 않음)** + `world.r_mm: "default"`. `tests/doe/vbead_accuracy.md` 는 두 표. `acc_hint` 고르기: r 생략 → `cells`, 준 r 0 → `cells_r0`, 그 밖의 준 r → 해석된 r 이 가장 가까운 칸 r 의 1/1.25..1.25 배 안일 때만 `cells`, 아니면 null("측정 범위 밖").
6. 실행 계획: h 1.5 네 칸은 칸당 약 135 s·메모리 약 3.9 GB(전체 약 12 분) — **다른 무거운 작업·전체 pytest 와 동시에 돌리지 않는다**, pytest 는 h 5·3 칸만 다시 계산해 대조(지금과 같음).

### 19.6 시험 추가 (V-0250-VB-20~28)
20. **r 기본**: 합성 h 5·3·1.5 — r 생략 → `r_resolved` = min(mult·h, r_cap) ± 1e-4, h = r 0 발자국 중앙값(발자국 다시 잡은 뒤에도 같은 값), 발자국 d_move 에 r·tan(θ/2) 포함. 준 r 0 → 키 유지·각진 장(§4.1 r 0 식 ± 1e-12)·sha 가 r 없는 문서와 다름. 준 r > r_cap → 422(key r, r_max), r = r_cap 통과. θ 60·run = h → `VB_R_CLAMPED`. `r_default_h_mult` 0 또는 블록에 키 없음 → r 0 과 같은 장. D = 0 → 0 정확, 응답·행에 `depth_max_mm` 키 없음(개정 3 — 깊이 시험은 V-0250-VB-29). **개정 3 으로 이 번호의 d_move·r_cap·`VB_R_CLAMPED` 세계는 V-0250-VB-30 의 식·세계를 따른다**(θ 60·run = h 는 더 이상 줄지 않음).
21. **r = h 일 때 guard · warp 정보**: 합성 h 5·W 10·θ 45·d_max 6(VB-C1-5 세계) r 생략 → state·usable **측정값 기록**(warp 로 막히지 않음 — 뒤집힘·jac·tri 새 위반 0 이면 ok·usable = d_max), A 항목에 `crit` 없음·`warp{limit_deg, n, max_deg, at}` 있음. 같은 세계 준 r 0 → warp n > 0 이어도 state 가 warp 로 줄지 않음 + `guard.warp.text`. **뒤집힘은 계속 막음**: flip_deg 30 인 스냅샷에 θ 30 근처 가파른 단면(또는 좁은 W_top) → limited/blocked reason inverted. 기존 D·W·U 표 바이트 = 골든(V-0250-VB-9 그대로).
22. **평탄 영역 host(합성)**: 부모 바닥 + 평탄부(벽 있음) + 평탄부 위 자식 채널 비드 + 평탄부 위 구멍·fixed — 평탄부 가운데 = ok(`host: "plateau"`), 가장자리 벽에 닿음 = `VB_PLATE_EDGE` **만**, 자식 비드에 닿음 = `VB_OVER_BEAD` 만, 구멍 = `VB_OVER_HOLE`, fixed = `VB_FIXED`, margin 경계(± 0.1) 판정 뒤집힘, 방향 기본 = 평탄부가 들어간 쪽(level 부호 양쪽 세계 각 1), `wall_islands` floor = `VB_OVER_ISLAND`. 평탄부를 D 변수로 선택 → 좌표 = D 항 + A 항(개별 합 ± 1e-12), 조합 묶음 1개·`VB_BAND_OVERLAP`, tie 노드 변위 0. 채널 비드 깊이면 위 = `VB_OVER_BEAD`(R-VB-7 유지).
23. **H6 평탄부(실제 derive — host 덮어쓰기 없이)**: (125, 300) ξ L 120 계약 단면(W_top 15·θ 45·d_max 5, r 생략)·(250, 300) **30°** L 100 같은 단면·같은 자리 **θ 60**(W_top 15·d_max 5) — 셋 다 derive ok·`host` 값 기록, D = d_max·0.5 d_max 에서 뒤집힘 0·jac·tri 새 위반 0, 발자국 밖 이동 ≤ 1e-12, range guard state **blocked 아님**(usable·warp n·max 기록). 위반이 있으면 완화하지 않고 측정값을 findings 에 적어 메인 결정. 기록 = work/vbead_h6.md 에 새 표(옛 표 보존). ※ 시험 자리는 §20 INT-9 의 대체 자리로 바꿈(계약 자리는 정당한 거부).
24. **띠(base host) 회귀**: H6 위 띠 y 654 x 400→600 = derive ok(사유·경고 코드 개정 1 과 같음 — `VB_WALL_COARSE`), 위 띠 30° = `VB_PLATE_EDGE`, V-0250-VB-3 합성 세계의 사유 코드 전부 개정 1 과 같음(host = base 는 §19.3 으로 코드가 바뀌지 않음). r 생략으로 바뀌는 수치(n_fp·usable)는 새로 기록.
25. **설정 검증**: `theta_range_deg` 상한 61 ∧ flip_deg 60 → `CONFIG_INVALID`(문구 VB_THETA_FLIP, detail 키), 상한 60 통과, flip_deg 를 50 으로 내리면 기본 [15, 60] 이 `CONFIG_INVALID`, default 가 범위 밖 = `CONFIG_INVALID` — 코어·pydantic 같은 결과, yaml 2 기본값 통과. 블록 상한 75 인 옛 스냅샷 + θ 70 → 422 key theta_deg. **경계**: 정렬 평판·θ 60·준 r 0·run ≥ 3h → 사면 요소 뒤집힘 0(θ_f = 59.99°).
26. **골든 유지**: `tests/doe/golden_v0250_c1/`(c35b8ac1) 다시 기록 금지 — 가상 비드 없는 선택·블록 있는 새 스냅샷 + 가상 비드 0 이 §7.3 파일 전부 바이트 동일(블록에 `r_default_h_mult` 가 늘어도 가상 비드 없으면 `_sel_cfg_sha` 불변). `VB_RULES`(개정 3 = 3) 는 가상 비드 있는 basis.json 에만.
27. **정확도 다시 재기**(§19.5): 새 `cells` 12칸 + `cells_r0` = f238144d 값과 같음, md = json, h 3 ≤ 5 %·수렴 방향, `acc_hint` 세 갈래(r 생략·r 0·그 밖).
28. **B1·F1**(개정 3 몫은 V-0250-VB-33): 설정 거울 11키·settings 응답, derive·params 새 키(§19.7) 전달, r 칸 비움 = 키 없음·0 입력 = `"r": 0`, 정보 꼬리표 "뒤틀림 n"(n 0 이면 없음), 목록 행 host·r 표시, θ 칸 min·max = 설정, 2560·1920 가로 스크롤 없음.

### 19.7 B1 · F1 인터페이스 변화 요약
| 곳 | 변화 |
|---|---|
| 설정(4곳 거울) | `theta_range_deg` 기본 [15, 60] · 새 키 `r_default_h_mult` 1.0(0..4) · 검증 `theta_range_deg[1] ≤ select.quality.flip_deg`(`CONFIG_INVALID`) · `warp_max_deg` 뜻 = 정보 기준 |
| 스냅샷 `doe.virtual_bead` | += `r_default_h_mult`(없으면 0.0), schema 1 그대로, 복제 = 원 블록 |
| `GET /doe/settings` `virtual_bead` | += `r_default_h_mult` |
| 선택 문서 | **`flip: true`**(생략 = false = 자동 방향, false 는 정규화에서 키 없음) · **`side` 키 삭제(주면 422 key side)** — B1 `VirtualBeadIn.flip: bool \| None`(None·false 는 코어에 넘기지 않음), `side` 필드 없음(개정 3) · `r`: 준 값은 0 도 키 유지(생략 = 기본) · 준 r > r_cap → 422 `VB_INPUT_INVALID{key r, r_max}` · θ > min(범위 상한, flip_deg) → 422. B1 `VirtualBeadIn.r: float \| None`(None 은 dump 에서 빠짐, 0 은 남김) |
| derive `virtual_beads[]` | += `r_resolved`·`r_source`("default" \| "user")·`host`·`host_floor`, warnings += `VB_R_CLAMPED`(info). preview `g`·`c` 는 해석된 r 기준(형식 그대로 — F1 이 `depthEff` 로 보상). `side_resolved` = 적용 방향(뒤집기 뒤). **`depth_max_mm` 없음(개정 3)** |
| params A 행 | `vb` += `r`·`r_source`·`host`(`depth_max_mm` 없음, `vb.side` = 적용 방향) · `guard.warp{limit_deg, n, max_deg, at, text?}` · `acc_hint` 고르기 §19.5-5 |
| 선택 `range_guard.json` | A 항목 `crit` 없어짐, `warp{…}` 추가(D·W·U 항목 불변) |
| basis.json | `vb_rules` **3**, `virtual_beads[]` += `r`·`host`(`side` = 적용 방향). basis.npz·bin 형식 그대로(g·c — 보상은 평가 식) |
| 브라우저 `basis.ts`(F1) | `termAt` hinge = vec·[ramp(depthEff(x, c) − g, c) − ramp(depthEff(nominal, c) − g, c)], `depthEff` = 코어 `depth_eff` 와 같은 식(§4.1) |
| 문구 `doe_messages.json` | 새 `VB_WARP_INFO`·`VB_R_CLAMPED`·`VB_THETA_FLIP`, 바뀜 `VB_PLATE_EDGE` |
| 화면(F1) | r 칸: 비움 = 기본, 자리 표시 "요소 크기", 목록 행에 `r 3.0(기본)`·평탄부 host 면 "평탄부" · 3D 찍기의 "평판 위를 찍으세요" 판정에 평탄 영역 포함 · 변수 표 A 행 회색 정보 꼬리표 "뒤틀림 n" · (개정 3: 행 툴팁의 "실제 깊이" 구절 없음 — 변수 값이 실제 깊이) · 방향 = 체크 칸 "방향 뒤집기" 1개(라디오 3개 없앰, 목록·툴팁에 방향 표시 추가 없음) · θ 칸 범위 15~60 |
| `resources/vbead_accuracy.json` | schema 2 — `cells`(r 기본)·`cells_r0`(보존) |

### 19.8 사용자 질문 → 결정 (2026-11-26, 개정 3 — 상세 §19.9)
1. r > 0 일 때 변수 값 D 와 실제 깊이의 차 c/4. **결정 "D = 실제 깊이로 보정"**(D-0.25.0-VB-26): 변수 값 D = 모델 실제 최대 깊이. 옛 가정 "식 그대로 두고 `depth_max_mm` 표시만"은 **철회**.
2. 평탄부 위 추가 비드의 방향. **결정 "자동 + 사용자 뒤집기"**(D-0.25.0-VB-27): 기본 = 평탄부가 들어간 쪽으로 더 깊게(floors level 부호, 차 0 이면 기존 다수결), 비드 입력에 방향 뒤집기 선택 1개.

### 19.9 개정 3 — D = 실제 깊이 · 방향 자동 + 뒤집기 (D-0.25.0-VB-26~28)

#### 19.9.1 깊이 보상 (D-0.25.0-VB-26)
1. **식**: u_i(D) = s·n_i·[F_c(e(D) − g_i) − F_c(−g_i)], **e(D) = D + c/4 (D ≥ 3c/4) · c·(√(1 + 4D/c) − 1) (0 < D < 3c/4) · D (D ≤ 0 ∨ c = 0)**, c = r·tan(θ/2)·tanθ(§4.1 — θ 는 §19.4-4 의 θ_f). g·a·c·vec·F_c·Q_a 는 그대로.
   - **보정하는 양 = 힌지 항에 들어가는 변수 값**(D → e(D)). 깊이면 노드(g = 0)의 변위 F_c(e) − c/4 가 정확히 D 가 되게 하는 역함수라 근사·반복 없음.
   - 결정 근거: g 나 c 를 옮기는 방식은 D 가 작을 때 정확하지 않고 저장 형식이 바뀐다. 변수 값 변환은 노드 상수를 건드리지 않아 basis.npz·bin·derive preview 형식이 그대로다.
2. **작은 D**(D < 3c/4 — 깊이면이 아직 입구 둥글림 구간 안): 제곱근 가지로 **같은 보장(실제 깊이 = D)**. 한계·거부·경고 없음. D = 0 → e = 0 → u = 0 정확(공칭 = 지금 형상, d000 불변), D = 3c/4 에서 값·기울기 연속(C¹), 전 구간 단조 증가. D < 0 은 범위 규칙(lo ≥ 0)으로 오지 않으며 식은 e = D(변화 없음).
3. **쓰는 곳 한 곳**: `virtual_bead.depth_eff(v, c)` → `virtual_bead.hinge` → `core.basis_term`(§4.2 표의 모든 호출 쪽이 이 항 함수만 씀 — morph·fixed 침범·Prober·diag `stretch_max`). 브라우저 `basis.ts` `depthEff` 같은 식. v₀(공칭)에도 e 를 적용(지금 0 → 0).
4. **발자국 · r_cap · range guard · d_max 관계**:
   - d_move = W_top/2 + (e(d_max) + c)·cotθ = W_top/2 + d_max·cotθ + 1.25·r·tan(θ/2)(옛 계수 1 → 1.25; 이 밖 노드는 D ≤ d_max 에서 변위 0). 검사 띠 = d_move + margin_mm(규칙 그대로 — 수치만 넓어짐).
   - r_cap = min(r₁, r₂), r₁ = W_top/sinθ(그대로), **r₂ = d_max·cotθ/(sinθ/2 + 0.75·tan(θ/2))**(§19.1-4). 준 r > r_cap = 422, 기본 r 은 줄임 + `VB_R_CLAMPED`(그대로).
   - h(§3.3)·`VB_MESH_COARSE`·`VB_WALL_COARSE`·n_wall = run/h, run = d_max·cotθ — **그대로**(r 0 발자국 기준, 보상과 무관).
   - range guard: 범위 [0, d_max]·usable·이분 값·`warp.at`·`default_range` 는 모두 **변수 값 = 실제 깊이** 단위. 판정은 `basis_term` 으로 만든 형상에 하므로 따로 바꿀 곳 없음. `d_max_limit_mm`(30) 도 실제 깊이 한도.
   - 사면 각 θ·깊이면 폭 W_top 은 그대로, 입구만 한쪽 r·tan(θ/2)/4 넓어짐(h 3: θ 45° 0.31 mm, θ 60° 0.43 mm).
5. **`depth_max_mm` 응답 키 = 삭제**(derive `virtual_beads[]`·params `vb`·행 툴팁·정확도 표 `depth_mm` 열). 결정 근거: 늘 d_max 와 같은 값 — 화면·응답은 필요한 것만.
6. **정확도 표**(§19.5): 칸의 D = (A) 실제 메시 사다리꼴의 깊이 = (B) 가상 비드 변수 값 = (B) 실제 최대 깊이 — **실제 깊이 기준 비교**. 12칸·기준(h 3 ≤ 5 %·수렴 방향·완화 금지)·`cells_r0` 보존 그대로(r 0 은 c = 0 → e = D 라 옛 값이 그대로 유효).
7. **호환(확인)**: 종류 A 는 v0.25.0 신규 — 옛 버전 스냅샷·결과에 A 변수·hinge 기저 없음(이행 처리 없음). 가상 비드 없는 선택 = §7.3 바이트 불변(linear 항 경로 무변경, 골든 c35b8ac1 다시 기록 금지). 준 r 0·`r_default_h_mult` 0 블록 = c 0 → 보상 없음(개정 1 식과 같은 값).
8. **`VB_RULES = 3`**(§7.2): 개발 중 만든 `vb_rules` 1·2 기저는 재사용 조건에서 걸러져 다시 만들어진다. 새 설정 키·스냅샷 키 없음(보상은 끌 수 없음 — c 0 이면 저절로 없음).

#### 19.9.2 방향: 자동 + 뒤집기 (D-0.25.0-VB-27·28)
1. **선택 문서 키** `virtual_beads[].flip`(bool). 기본 false = 자동 방향. 정규화: true 만 키로 남기고 false 는 생략(기본값 키 생략 원칙 — `flip` 없는 문서의 sha 불변). bool 아님 → 422 `VB_INPUT_INVALID` key flip.
2. **해시**: 선택 문서 안 키라 선택 sha(→ `select/<sha12>`·derive 캐시)에 들어간다 — true 일 때만 sha 가 달라짐. 설정·스냅샷 블록 `doe.virtual_bead`·`HASH_KEYS` 에는 키 없음(비드마다의 입력이지 스터디 규칙이 아님).
3. **옛 키 `side`("+" | "-") 삭제**(D-0.25.0-VB-28): 주면 422 `VB_INPUT_INVALID` key side. 결정 근거: 사용자 결정은 "자동 + 뒤집기 1개" — 절대 방향 키를 함께 두면 같은 결과를 내는 입력이 둘이 되고(sha 다름) 두 키 조합 규칙이 필요하다. 출시 전이라 이행 없음.
4. **자동 방향 s_auto**(§2.3 순서): ① host ∈ {area, plateau} ∧ |floors[f].level − floors[parent(f)].level| > 1e-6 mm → 그 부호 쪽(더 깊어지는 쪽, §19.3-4) ② 그래프 비드 다수결(VB-C1-2 방식) ③ 동률·없음 → frame n 반대. **적용 s = flip ? −s_auto : s_auto.** 띠(base host)·평탄부 **같은 키·같은 뜻**("자동의 반대").
   - 결정 근거(1e-6): level 은 부동소수 — "차 0" 을 `_LEN_EPS` 와 같은 값으로 고정해 결과를 결정적으로.
5. **뒤집었을 때 검사**: 발자국·d·g·c·h·검사 띠·host 검사 사유(가장자리 `VB_PLATE_EDGE`·이웃 `VB_OVER_BEAD`·`VB_OVER_VBEAD`·구멍·체결부·제외)·해상도 경고는 **방향과 무관 — 바뀌지 않음**(vec 부호만 반대). 방향에 따라 달라지는 것 = range guard 판정·usable·warp 정보·평탄부 D 변수와의 조합 점검·`stretch_max`(모두 적용 방향의 실제 형상으로 평가 — 코드 분기 없음). 평탄부에서 뒤집어 D 가 level 차보다 크면 부모 바닥 면 너머로 나오지만 **새 검사·새 코드 없음**(막을 근거는 메시 품질뿐 — range guard 몫).
6. **응답**: 실제 적용 방향 = derive `virtual_beads[].side_resolved`("+" | "-", n_h 기준 — 기존 키, 뒤집기 뒤 값)·params `vb.side`·basis.json `virtual_beads[].side`. 새 응답 키 없음(자동 방향은 `flip` 과 `side_resolved` 로 알 수 있음).
7. **화면(F1)**: 단면 입력 줄의 방향 라디오(○ 기본 ○ + ○ −)를 없애고 **체크 칸 "방향 뒤집기" 1개**(기본 꺼짐 → 키 없음, 켬 → `flip: true`). 그 밖 표시(목록 행·배지·툴팁) 추가 없음 — 결과는 미리보기 3D 에서 본다. 저장된 비드를 다시 열면 `flip` 값으로 복원.

#### 19.9.3 시험 추가 (V-0250-VB-29~33)
29. **깊이 보상(순수)**: `depth_eff` — c ∈ {0, 0.106, 1.243, 3.0}: e(0) = 0 정확, F_c(e(D)) − F_c(0) = D ± 1e-12 (D ∈ {0.1c, 0.5c, 3c/4, c, d_max}), D = 3c/4 좌우 값·수치 기울기 연속(차 ≤ 1e-6), 단조, c = 0 → e = D(비트 같음 — V-0250-VB-1·2 의 r 0 기대값 그대로). 합성 평판 h 3·θ 45·60·r 생략: 깊이면 노드 법선 변위 = D ± 1e-12(D ∈ {0.2, 0.5 d_max, d_max}), 최대 변위 노드 = 깊이면, 직선 사면 구간 기울기 = tanθ, 면내 성분 0.
30. **발자국·r_cap(개정 3 식)**: d_move = W_top/2 + (e(d_max) + c)·cotθ ± 1e-9, D = d_max 에서 d ≥ d_move 노드 변위 0·d_move 바로 안쪽 노드 변위 > 0(띠가 남지도 모자라지도 않음), r₂ 계수 0.75(준 r = r_cap 통과·+2e-4 → 422 key r, r_max), `r_default_h_mult` 1·θ 15·45·60·run = h 세계 → `VB_R_CLAMPED` 없음, mult 2·θ 60·run = h → `VB_R_CLAMPED`·r = r_cap.
31. **경로 일치·규칙 판**: 브라우저 `basis.ts`(`depthEff`) morph = 워커 `bead_select.morph` 차 ≤ 1e-4 mm(r 생략·D 작은 가지와 선형 가지 각 1 — V-0250-VB-8 방식), derive preview 로 만든 결과 = basis.bin 결과. range guard usable 끝 값에서 깊이면 변위 = usable ± 1e-9(실제 깊이 단위). derive·params·`vb` 에 `depth_max_mm` 없음. `VB_RULES == 3`, `vb_rules` 2 인 basis.json = 재사용 안 함(다시 만듦), 가상 비드 없는 선택 골든 바이트 불변(V-0250-VB-26 그대로).
32. **방향**: (a) 평탄부 host level 부호 양쪽 세계 — `flip` 없음 = 들어간 쪽, `flip: true` = 반대(`side_resolved` 뒤바뀜) (b) level 차 0 평탄부·base host = 다수결 쪽 / 그 반대 (c) 그래프 비드 0 = frame n 반대 / 그 반대. 각 세계에서 flip 유무 두 derive 의 idx·g·c·h·reasons·warnings 코드 같음, vec = −vec(± 0), D = d_max 변위 = 부호만 반대. 정규화: `flip: false` = 키 없음·sha = `flip` 없는 문서, `flip: true` sha 다름, `flip: 1`(bool 아님)·`side: "+"` → 422(key). 가장자리·이웃 비드에 닿는 비드는 flip 과 무관하게 같은 사유. 평탄부 D 변수 + A(flip) → 조합 묶음·좌표 = 항 합.
33. **B1·F1(개정 3)**: `VirtualBeadIn.flip`(false·None = 코어에 키 없음)·`side` 필드 없음(422), openapi·`check:api`. 화면: 체크 칸 1개만(라디오 없음), 켬 → 요청 `flip: true`·끔 → 키 없음, 다시 열기 복원, 미리보기 변위 부호 반대, 행 툴팁에 "실제 깊이" 구절 없음, 정확도 표 json·md 에 `depth_mm` 열 없음, 2560·1920 가로 스크롤 없음.

## 20. 통합 보정 INT-n (release/v0.25.0 통합 — 사실 기록, 설계 변경 없음)
- **INT-1 지그 tie 집합 한 출처**: 백엔드 derive `tie_node_ids` = 코어 `stages.jig_tie_ids_at(준비 스냅샷 doe, 스터디 폴더, mesh)`(opt_core `doe_jig_tie_ids`) — 워커 BD_MATRIX 가상 비드 분기와 같은 `_pos_u_tie_ids`, **pos_u 블록 유무·enabled 와 무관**(옛 `pos_u_tie_ids_at` 은 pos_u 블록 없으면 빈 배열 → pos_u 없는·꺼진 스터디에서 VB_FIXED 가 워커와 달랐음). `pos_u_tie_ids_at` = 같은 함수 별칭(v0.24.9 계약 이름). 백엔드는 pos_u·virtual_bead 블록이 모두 없으면 그대로 None(호출 불변). 시험 tests/doe/test_pos_u_int.py(세 경우 백엔드 원천 = 워커)·backend test_doe_v0250_b1_api.py::test_tie_ids_same_as_worker_regardless_of_pos_u.
- **INT-2 normalize_v2 블록 인수**: §8 "normalize_v2 시그니처 불변" 대신 키워드 `virtual_bead=<스냅샷 블록>` 추가(`normalize_vbeads(…, block=)` → `vb_block` 해석 — derive 와 같은 함수). 백엔드의 cfg 덮어쓰기(`_vb_norm_cfg`) 제거, 워커 BD_MATRIX 선택 재정규화도 같은 블록 전달. 블록 없음 = 설정값(옛 동작).
- **INT-3 VB_SCOPE = derive 사유**: §1.1 의 "블록 없는 옛 스터디에서 가상 비드 → 422 VB_SCOPE" 와 §3.2(사유 표)가 달랐음 — 코어 현재 동작(저장 가능, derive `virtual_beads[].reasons` 에 VB_SCOPE, 변수 행 없음)을 따름. 422 는 §3.2 그대로 형식 오류(VB_INPUT_INVALID·VB_MAX_COUNT)만. 화면은 블록 없는 스터디에서 절을 숨기므로(INT-5) 사용자가 보는 경로는 API 직접 호출뿐.
- **INT-4 vb_frame 첫 비드 전에도**: 블록 있는(켜진) 스터디 ∧ `vb_allowed(계획, 출처)` 이면 derive 응답(selection 조회 포함)이 가상 비드 0개여도 `vb_frame` 을 준다 — 코어 `bead_graph.vb_frame_base`(판 법선 = 그래프 frame n0, 높이 = 부모 바닥 노드 n0 성분 중앙값 — 없으면 host 종류 → floor 전체), 비드가 있으면 첫 비드 판(`vb.plane`) 기준(기존). 두 경우 모두 `origin` = ESL frame 원점(없으면 판 점)을 그 판 평면에 사영(ξ·η 값 불변, 판 위 점 법선 성분 0) — §8 의 "가상 비드 있을 때만 키" 를 이렇게 넓힘. 백엔드는 블록이 있으면 블록·계획 열을 derive_v2 에 늘 넘김(derive_obj_v2 호출은 비드 있을 때만 — 그 밖 응답·워커 산출물 불변), DB 선택 요약은 비드 0개면 `vb_frame` 을 빼 옛 모양 유지. 프런트는 `vb_frame` 만 쓰고 그래프 frame 대체·판 높이 추정(`plateLevelOf`)·두 frame 이 같다는 가정 제거(평탄부 비드 겹쳐 그리기는 그 비드 p0 높이로 올림). 시험 tests/doe/test_vbead.py::test_vb_frame_before_first_bead_int4, backend test_core_e2e_derive_response_shape·test_derive_passes_block_plan_and_tie_only_with_virtual_beads, frontend vbead_basis.test.ts.
- **INT-5 절 표시 조건**: 추가 비드 절 = `GET /doe/settings` `virtual_bead.enabled` ∧ 스터디 `inputs.virtual_bead`(스냅샷 블록) 있음 — 옛 스터디(null)는 숨김(§9 "블록 없는 스터디 … 절 숨김" 구현). θ 칸 기본·범위도 블록 값(INT-2 와 같은 출처, 없으면 설정). types.ts `DoeVbBlock`·`DoeStudyOut.inputs.virtual_bead`(openapi inputs 는 자유 객체라 check:api 대상 밖). 목 `demoVBead(withBlock)`.
- **INT-6 묶음 구현 사실(handoff 이관)**: C1 — 골든 c35b8ac1(가상 비드 0개 = 옛·블록 스냅샷 모두 바이트 동일), H6 측정 `work/vbead_h6.md`, 정확도 표 재생성 `python tests/doe/synth_vbead.py OUT.json`(h 1.5 칸 약 3.9 GB — 다른 무거운 작업과 동시 금지), findings VB-C1-1~21. B1 — `BeadDoeVirtualBeadCfg`(11키, 검증 = 코어 `check_virtual_bead`), `vbead_snapshot`(HASH_KEYS 한 곳 = `morph.virtual_bead`), `GET /doe/settings` `virtual_bead` 7키(enabled·max_count·theta_default_deg·theta_range_deg·d_max_limit_mm·min_wall_elems·r_default_h_mult), `VirtualBeadIn`(side 없음·StrictBool flip), `with_vb_text`(guard.warp text·vb_reason 문구), DB 요약에 preview 없음(조회 = 지금 derive). F1 — `basis.ts` hinge(`ramp`·`depthEff`·`termAt`, 코어 fixture 동등), `vbead.ts`(입력 검사·요청·ξη 환산), `VirtualBeadPanel`·`MorphStage` 추출(SelectDesign3D DOM 불변), 행 클릭 = 활성 + 입력 칸 복원(편집 버튼 없음), 추가·삭제 뒤 250 ms 디바운스 derive, 목 `?demoVBead=1`, 증적 `frontend/scripts/screenshots-v0250-f1.mjs`(설정 끔 = 화면 높이 ±0, 켬 = 접힌 절 +21 px(2560)·+18 px(1920) — ③ 카드 안 스크롤, 가로 스크롤 없음).
- **INT-7 통합 시험(2026-11-27, 0.25.0 — release/v0.24.9 7d99c017 merge 뒤)**: tests/ 1884 passed·192 skipped·실패 3(허용: test_large_model_cad_share, test_v0160_bytes_skip_policy[h8]·[h5open]), packages/beadgraph(저장소 루트에서 `pytest packages/beadgraph` — 119 수집) 117 passed·2 skipped, backend 1300 passed(첫 실행 실패 2 = VERSION 0.25.0 뒤 openapi info.version 미갱신 → 재덤프 뒤 8 passed), worker 416 passed·6 skipped, frontend typecheck·build·check:api 통과, vitest 78 파일 962 passed. openapi 스키마 변화 없음(info.version 만).
- **INT-8 좌표 입력 높이(독립 검증 결함, 2026-11-27)**: 좌표·길이·각도 입력의 p0 는 프런트가 `vb_frame` 판 높이(0개 = 부모 바닥, 있으면 첫 비드 판)로 만들어 보내므로, 판 높이와 차 > margin + 2h 인 평탄부에서 `VB_NOT_ON_PLATE` 였다(H6: 평탄부 z 10 vs 부모 바닥 z 0 → 세 자리 모두 거부, 3D 두 점은 정상). 수정 = **높이는 코어 한 곳** `virtual_bead.seat_point(p, host 요소 중심, 그래프 frame n0, tol = 그래프 frame h_mm)` 을 `bead_graph.virtual_beads` 가 씨앗 찾기 전에 p0(·(a) 형식 p1)에 적용 — 백엔드 derive·워커 BD_MATRIX 같은 함수. 규칙: host 후보(VB_HOST_SEG_TYPES 의 host 요소 전체) 중 면내(n0 에 수직) 거리 ≤ 최소 면내 거리 + tol 인 요소들에서 **입력 점과 n0 방향 높이 차가 가장 작은 요소**(같으면 앞 번호), 그 차 ≤ tol 이면 점 그대로(3D 찍기 — 바이트 불변), 최소 면내 거리 > 2·tol 이면 그대로(판 밖 — host 검사가 사유), 그 밖은 n0 방향으로 그 요소 중심 높이까지 옮김. 같은 (ξ, η) 에 높이 후보가 여럿이면 입력(= 화면 판) 높이에 가까운 면. 선택 문서 키 변화 없음, derive `virtual_beads[]` 에 **`p0_resolved`**(판 평면 사영 시작점) 추가 — 프런트 겹쳐 그리기는 이 점 높이(없으면 p0). 프런트는 높이를 추측하지 않음(ξ·η → vb_frame 판 위 점 그대로). 측정(H6): 평탄부 (150, 180) ξ L 120·(113, 182) ξ L 60·(250, 180) 30° L 60 을 z 0·z −0.0008(vb_frame 높이)로 넣으면 모두 ok·host plateau 11·맞춘 거리 10.0(요소 중심 9.99999), z 10 입력 대비 발자국 idx 같음·g 차 1.47e-5 mm·vec 차 0. 띠(base) 두 점 = 맞춤 0, 띠 좌표를 z 10 으로 넣어도 base·같은 발자국. 시험 tests/morph/test_virtual_bead.py::test_seat_point_int8, tests/doe/test_vbead_h6.py::test_plateau_coordinate_input_seated_int8·test_band_coordinate_and_pick_regression_int8, frontend vbead_basis(겹쳐 그리기 높이), 가상 비드 0개 골든(test_vbead_golden) 그대로.
- **INT-9 H6 평탄부 시험 자리(메인 결정 — VB-C1-17)**: §19.6-23 의 계약 자리 (125, 300) ξ L 120 은 VB_OVER_BEAD + VB_OVER_ISLAND(섬 요소 8), (250, 300) 30° L 100 은 VB_OVER_HOLE 로 **정당한 거부**(독립 검증 재측정 같음) — 시험·측정 자리를 닿지 않는 대체 자리 (150, 180) ξ L 120 θ 45·(250, 180) 30° L 60 θ 45·(200, 480) 30° L 60 θ 60 으로 바꾼 것을 메인 결정으로 확정(계약 자리는 거부 고정 시험 test_contract_plateau_spots_rejected_v23 으로 남김).
