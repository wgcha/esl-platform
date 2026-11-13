# 계약: ④ 형상 비교 하중 전달 — 일 등가(W) · 셀(C) · 진단 (LOAD_TRANSFER, v0.20.0)

- 상태: **초안(Plan)** — 2026-11-13. 사용자 결정(아래 "사용자 결정")은 확정, §12 의 3개 항목은 권고안으로 진행하되 사용자 답에 따라 기본값만 바뀐다(구조 불변).
- 버전: **v0.20.0** (origin/main 40dcc6d = v0.19.1 기준). migration **불필요**(새 값은 `bead_does.inputs`·`prep`·`result` JSONB 와 작업 폴더 파일에만).
- 관계: `esl_step_compare.md`(STEP_COMPARE ④)의 **SC-D-2·SC-D-6(하중·지지)·확정 4 를 새 스터디에 한해 대체**한다. 메시(`esl_compare_mesh_options.md`)·순위·결과 화면 규칙은 그대로. 평가 영역은 ③ `esl_step_graph.md` SG-D-19·20 의 함수를 재사용. 충돌 시 ④ 하중·지지·영역·3D 비교 범위에서 이 문서가 우선.
- ID 규칙: 결정 `D-0.20.0-LT-n`, 시험 `V-LT-n`, 리스크 `R-LT-n`.
- 근거: 이슈 #63 마지막 진단 코멘트(2026-11-13) — ④ 기준 d000(Case 메시 = ESL 원본 메시 A, t 0.8·E 167 477·ν 0.33 까지 ① 과 같음)에서 셀 매핑 하중은 ① direct_nodal 대비 Σ|F| ≈ 1/50, max|F| 44 850 → 231 N, 하중 상관 0.02~0.04, umax ×18~58(Edge 15 ×40, Corner 13 ×19, Edge 11 ×58, Corner 17 ×18), 반력 비 1e-12(지지 원인 아님).

### 사용자 결정 (2026-11-13, 변경 금지)
1. 모핑(변위장·메시 모핑으로 A 메시를 형상에 맞추는 방식)은 **제외** — 위상이 다른 모델에서 실패 위험이 큼.
2. **방식 W(일 등가 전달)** 와 **방식 C(셀 매핑, 셀 크기 선택)** 를 **둘 다 구현**하고 같은 스터디 안에서 비교한 뒤 선택한다.
3. **공정성**: 기준과 비교 형상에 반드시 **같은 규칙**. d000 만 direct_nodal 로 푸는 것은 금지.
4. 사내 서버는 읽기 전용 진단만 하므로 **비교 판단 자료(하중 전달 진단)를 플랫폼이 스스로 산출**한다.

## 0. 현황 (40dcc6d, 근거 파일:행)

| 항목 | 위치 | 현재 | 이 계약에서 |
|---|---|---|---|
| ④ 하중 | `esl/doe/stages.py` `_cmp_loads`(2212)·`_cmp_design_mesh`(2299)·`_view3d`(721, compare 분기)·`_cmp_refine_bias`(2425) → `scenario.entry_loads` → `target.entry_load` S2(`esl/opt/target.py:203-211`) → `mapping.to_target` | 모든 형상(d000 포함)이 ESL 요약 24×14 셀 합력·합모멘트(`entry.summary`, ESL 자기 frame) → 대상 노드 최소노름 분배 + 전체 평형 보정(합 0) | 새 모듈 `esl/doe/load_transfer.py` 한 함수로 모든 호출 자리 통일, 방식 W·C·legacy |
| ESL 원본 | `esl/library/entry.py:33` `RAW_KEYS` | `f` (N,3) 절점력만, **모멘트 없음**. `x0`·`conn`·`elem_type`·`node_id` 원본 메시 A | W 의 원본 |
| 솔버 하중 | `esl/mech/shell.py:842·984` | 하중은 자유도 0..2(병진)에만, 회전 자유도 하중 0 | 그대로(LT-3) |
| ④ 지지 | `scenario.compare_target`(397) → `design_target`(192) → `target.auto_supports`(97, PCA 4꼭지점 → 3-2-1) | 형상마다 따로 고름 | 기준 d000 지지점을 형상 최근접 노드로 이전(LT-7) |
| 평가 영역 | `step_graph.region_mask`(244)·`region_loads`(314)·`submesh`·`evaluate(region=)`(`evaluate.py:36`) | ③ select_base step 만 사용, ④ 는 전체 | ④ 에 같은 함수 적용(LT-8) |
| 3D 비교 | `_view3d` = 형상마다 **자기 최악 ESL**, 화면 `Compare3D`(`DoeStudy.tsx:526`) 좌 d000·우 선택 형상 | 좌우 ESL 이 다를 수 있음(#63: Corner 13 vs Edge 11) | 좌우 같은 ESL(선택 형상의 최악), 카드에 ESL 이름(LT-9) |
| 정규화 요약 | `normalize.grid_summary`(165), `mapping.min_norm_forces`(39)·`_rank_ok`(31) | 24×14 고정(`library.grid`) | C 의 새 격자는 이 함수들을 **가져다 쓰기만**(코드 변경 0) |

## 1. 범위 / 비범위

| 범위 (v0.20.0) | 비범위 (후속) |
|---|---|
| ④ 하중 전달 방식 W·C(셀 크기 선택)·legacy, 모든 형상 같은 규칙 | 모핑·변위장 매핑(사용자 결정 1) |
| 하중 전달 진단 `load_transfer_diag`(형상·ESL별 하중 지표, d000 에서 참값 대비 지표, 다른 방식 점수, d000 셀 크기 훑기) | ①②③ 하중 경로 변경(바이트 불변) |
| 지지 이전(기준 d000 지지 → 형상 최근접 노드) | 회전 자유도 하중(오프셋 모멘트) — LT-3 |
| ④ 평가 영역(주 시트) — ③ 함수 재사용 | 영역 밖 형상 메시에서 제거(해석은 전체 메시, ③ 과 같음) |
| 3D 비교 좌우 같은 ESL + ESL 이름 | 3D 화면에서 ESL 직접 고르기 |
| 화면: ④ 고급 설정 select 1개, 결과 진단 요약 1줄 + 접힘 표 | 진단 그래프·셀 크기 훑기 화면 조작 |

## 2. 흐름 (④ 단계는 그대로, 각 단계 안의 하중·지지만 바뀜)

```
DOE_PREP
  BD_MESH0   (불변) 형상 메시
  BD_LOADS   ① 영역(LT-8): 형상마다 region_mask → prep/shapes/<did>/region.npz (영역 = 전체면 파일 없음)
             ② 기준 frame = d000 영역 요소로(영역 = 전체면 지금과 바이트 같음)
             ③ 지지(LT-7): d000 = auto_supports(영역 노드) / 형상 = 이전(실패 시 auto + 경고)
             ④ 하중 전달 연산자(LT-2·6): W = 형상마다 사영 → prep/shapes/<did>/transfer.npz (ESL 원본 메시 sha 별)
             ⑤ 하중 지표(진단 하중 부분 — 해석 없음) → prep/load_transfer.json, 먼 노드 과다 → 그 형상 FAILED_SIZE LT_TRANSFER_FAILED
             ⑥ d000 하중 → prep/loads.npz (방식 = 스터디 방식)
DOE_RUN
  BD_BASELINE d000: 인수분해 1회 → [주 방식 K개] + [참값 K개] + [다른 방식 K개] + [셀 훑기 K×m] 풀이
              → result.json(주 방식만, 지금 형식) + run/designs/d000/load_transfer.json(진단)
  BD_DESIGNS  형상: 인수분해 1회 → [주 방식 K] + [다른 방식 K] → result.json(주) + load_transfer.json(다른 방식)
  BD_POST     순위(주 방식, 불변) + post/load_transfer_diag.json + ranking.csv 끝 열 + result.json.load_transfer
              view3d: 형상 = 자기 최악 ESL(불변), d000 = 표시 형상들의 최악 ESL 마다 1개(인수분해 1회) → post/view3d/d000_e<kk>/
```
- legacy 스터디(스냅샷에 `load_transfer` 없음)는 위 ①~⑤·진단·d000_e* 를 **모두 건너뛰고** 지금 코드 경로 그대로(LT-11).

## 3. 결정

| ID | 결정 | 근거 |
|---|---|---|
| D-0.20.0-LT-1 | **하중 전달 = 스터디 단위 1방식 `method ∈ {work, cell}`**, d000 포함 모든 형상에 같은 함수 `load_transfer.shape_loads(target, entries, spec, ctx)`. 호출 자리 4곳(`_cmp_loads`·`_cmp_design_mesh`·`_view3d` compare·`_cmp_refine_bias`) 모두 이 함수(`_view3d` compare 분기는 `_cmp_design_mesh` 를 그대로 호출 — 하중·지지가 실행과 바이트 같음). 진단용으로 **다른 방식(alt)** 도 같은 인수분해로 풀어 형상별 다른 방식 점수를 낸다(순위는 주 방식만) | 사용자 결정 2·3. 인수분해가 비용의 대부분이라 K 개 추가 풀이는 싸다 |
| D-0.20.0-LT-2 | **방식 W(일 등가)**: f_t = T_tᵀ f_A. T_t(3N_A × 3N_t) = "대상 메시 t 변위 → A 노드 위치 변위" 보간. A 노드 x_a 마다 (1) 후보 = 대상 요소(영역 요소만, LT-8) 중심 cKDTree k = `work.knn`(8) 개, (2) 요소별 최근접점: TRIA = 점-삼각형 최근접(Ericson, 경계 clamp), QUAD = 두 삼각형(0,1,2)(0,2,3) 최근접점 → 쌍선형 자연좌표 (r,s) Newton 역사상(≤ `work.newton_iter` 10회, 잔차 ≤ 1e-10·h, [-1,1]² clamp; 수렴 실패 = 그 삼각형의 선형 형상함수, 횟수 기록), (3) 거리 최소 요소(동률 ≤ 1e-12·h 는 작은 요소 번호 — 결정적), (4) 행 = 형상함수 N_i(Σ N_i = 1) × I₃. **좌표 = 전역 원좌표**(정규화 frame 변환 없음 — ④ 는 같은 좌표계 STEP 이 전제, SC-D-7b 정렬 검사가 관문). **동일 메시 빠른 경로**: 대상 node_id 집합 = A node_id 집합이고 좌표 차 ≤ `core.coord_check.max_rel` 이면 T = 순열(= `target.entry_load` S1 재배열과 같은 코드) → **① 과 비트 동일**. ESL 들의 원본 메시가 여러 개면 원본 메시 sha 별로 T 를 따로 만듦(`transfer.npz` 키 = sha 앞 16자) | 일 등가(가상일 Σ f_A·u(x_a) = Σ f_t·u_t)라 K_A u_drop 의 이웃 간 상쇄 구조가 대상 노드로 그대로 넘어감. 같은 메시면 T = I(사용자 검증 기준) |
| D-0.20.0-LT-3 | **회전 자유도**: ESL 은 절점력만(`RAW_KEYS` 에 모멘트 없음), 솔버 하중은 병진 3자유도만(`shell.py:842`) → **T 는 병진만 보간, 대상 회전 자유도 하중 0**. A 노드가 대상 면에서 법선 거리 d 떨어진 만큼의 오프셋 모멘트 Σ d·n×f 는 회전 자유도로 옮기지 않고 LT-4 합력·합모멘트 보정으로 되돌리며 보정 전 값을 `dM_rel_before` 로 기록. 오프셋 강체 연결(u_a = N(u + θ×d n))은 솔버 모멘트 하중·드릴링 강성 민감도 때문에 기각(후속) | 코드 사실(모멘트 없음). d ≤ `proj_tol_mm` 라 오프셋 모멘트는 작음 — 진단으로 확인 |
| D-0.20.0-LT-4 | **합력·합모멘트 보존(W·새 C 공통)**: 전달 후 f_t 의 합력·합모멘트(A 노드 중심 기준)를 **원본 f_A 의 값**으로 맞추는 전 노드 최소노름 보정(`mapping.min_norm_forces(X_t, F_A − F_t, M_A − M_t, c)`, 영역 노드만). 합 0 강제 아님 — ESL 이 자기평형이 아니면 그 불평형을 그대로 넘겨 ① 과 같게 함(T = I 이면 보정 0 → 비트 동일). ESL 자체 불평형 ‖ΣF_A‖/Σ|F_A| > 1e-6 이면 경고 `LT_ESL_UNBALANCED`(진행). legacy C 는 지금 보정(합 0) 그대로 | W 는 분할 1(Σ N = 1)이라 합력은 정확히 보존, 모멘트만 오프셋만큼 어긋남 |
| D-0.20.0-LT-5 | **먼 노드(사영 실패) 규칙**: 거리 > `work.proj_tol_mm`(기본 3.0 = 요소 1개, null = 1.0 × h) 인 A 노드도 **버리지 않고** clamp 된 최근접점으로 그대로 전달(합력 보존), `far_n`·`far_frac` = 먼 노드 Σ|f| / 전체 Σ|f| 기록. `far_frac > work.far_warn_frac`(0.01) → 형상 경고 `LT_FAR_NODES`(최대 거리·개수·bbox), `> work.far_fail_frac`(0.2) → 준비에서 그 형상 `FAILED_SIZE` 코드 `LT_TRANSFER_FAILED`(d000 이면 준비 실패 `BASELINE_FAILED`). 최대 거리는 ESL 마다가 아니라 원본 메시 마다 1개 | 형상에 없는 국부 형상(지운 보스 등)의 하중도 총량 보존. 실패 상태를 새로 만들지 않고 기존 FAILED_SIZE(순위 `extra_failed` 이미 있음) 재사용 |
| D-0.20.0-LT-6 | **방식 C(셀)**: `cell_size_mm` = null → **legacy 격자**(ESL 저장 요약 24×14, 지금 `to_target` 병합 규칙 그대로 — 바이트 동일). 값 s(`cell_min_mm` 3.0 ≤ s ≤ 200) → ESL raw 로 **새 요약**: ESL 자기 frame(`entry.meta.frame`)에서 nx = max(1, round(L_ξ/s)), ny = max(1, round(L_η/s)), `normalize.grid_summary(raw.x0, raw.f, nx, ny, fr=ESL frame)`; 대상 노드는 기준 frame(t.frame) 같은 (i,j) 셀로. 셀(병합 없음)별: 대상 노드 ≥ 3 이고 `_rank_ok(min_spread 0.2)` → 지금과 같은 최소노름 6 제약 분배, **아니면(노드 0~2 개·공선) 그 셀에 든 A 원본 노드 힘을 W 연산자(LT-2)로 전달**(일 등가 분배 — 셀 합력·합모멘트는 오프셋만큼만 어긋남). 끝에 LT-4 보정. 정보 `n_cells_loaded`·`n_cells_small`·`small_frac`(작은 셀 Σ|F| 비). 셀 1만 개 이상은 6×6 정규방정식 일괄 풀이(`np.linalg.solve` batched) — 결과는 lstsq 와 1e-10 안 | 셀 크기를 줄이면 C → W 로 연속 수렴(작은 셀은 W), 키우면 legacy 에 가까움 — "셀을 얼마나 줄이면 되나" 를 같은 규칙 위에서 비교. 병합은 셀이 작을수록 거의 모든 셀에서 일어나 의미가 없어 새 C 에서 뺌 |
| D-0.20.0-LT-7 | **지지(공정 비교 필수 범위로 포함)** `support ∈ {transfer, auto}`: d000 = `auto_supports`(영역 노드, LT-8) 그대로. `transfer` = 형상마다 d000 지지 노드 좌표 3점의 **최근접 형상 노드**(영역 노드, 결정적 동률 = 작은 번호)에 같은 dof. 거리 > `support_tol_mm`(null = 2h) 또는 `support_check` rank < 6 → 그 형상만 `auto_supports` + 경고 `LT_SUPPORT_FALLBACK`(거리·이유). `auto` = 지금 규칙. 하중이 자기평형이면 3-2-1 정정 지지는 강체 운동만 바꾸므로 **C(컴플라이언스)·점수는 지지와 무관**, umax·3D 변형 그림이 같은 기준점에서 측정되게 하는 것이 목적 | #63 진단 3: 형상마다 다른 기준점이라 변형 그림 비교가 어려움. 비용 ≈ 0 |
| D-0.20.0-LT-8 | **평가 영역(포함 — 기존 함수 재사용, 범위 작음)** `region.mode ∈ {auto, a_bbox, largest, all}`(③ SG-D-19 와 같은 값·뜻): 형상마다 `step_graph.region_mask(mesh, a_xyz = 첫 ESL raw x0, {region: …}, h)`. 쓰임 = (a) 기준 frame·형상 크기·정렬 검사(`shape_check`)를 영역 요소 submesh 로, (b) 지지 후보 노드, (c) W 사영 후보 요소·C 대상 노드(영역 밖 하중 0 — `region_loads` 와 같은 결과 형식), (d) `evaluate(…, region=mask)` 로 umax·epsmax 영역만(C = F·u 는 하중이 영역에만 있어 자동). 해석 메시는 전체(③ SG-D-20e 와 같음). 영역 ≠ 전체 = 정보 `COMPARE_REGION{n_in, n_out, out_bbox}`, 영역 < `min_frac` = 경고 `COMPARE_REGION_SMALL`. d000 = A 메시이면 a_bbox = 전체 → 영역 = 전체(지금과 같음) | #63 d001 의 주 시트 밖 ≈ 7만 요소(z 16.9~29.6)가 umax·지지·frame 을 오염. ③ 은 이미 같은 함수로 뺌 |
| D-0.20.0-LT-9 | **3D 비교 같은 ESL**: 형상 view3d(`post/view3d/<did>/`)는 지금처럼 자기 최악 ESL. d000 은 지금 `d000/`(자기 최악) 외에 **표시 대상 형상(상위 k)의 최악 ESL 집합마다** `post/view3d/d000_e<kk>/`(kk = 선택 ESL 순서 2자리, `DID_RE` 통과)를 인수분해 1회 + keep_u 로 만든다. `result.view3d` 목록은 **불변**(d000_e* 넣지 않음 — 화면 후보 목록 오염 방지), 새 키 `view3d_ref{entry_id: "d000_e<kk>"}`·`view3d_esl{did: entry_id}`. 화면 = 선택 형상 ESL 의 `view3d_ref` 가 있으면 그것을 좌측에, 없으면(legacy) `d000`. 두 카드 머리에 "ESL <label>" | #63 진단 1. 같은 하중·같은 지지(LT-7)·같은 영역에서만 변형 모드 비교가 의미 있음 |
| D-0.20.0-LT-10 | **하중 전달 진단 `load_transfer_diag`(§5)**: (a) 준비 = 형상·ESL별 하중 지표(Σ|F|, max|F|, 합력·합모멘트 오차 보정 전후, 보정량, 먼 노드, 작은 셀) — 해석 없음, (b) d000 = 참값 대비: d000 이 A 와 같은 메시(LT-2 빠른 경로 성립)면 참값 = direct_nodal → 하중 상관(코사인), umax 배율, C 배율, 변위 MAC; 다른 메시(기준 STEP)면 참값 = **A 메시 direct_nodal 별도 풀이**(같은 물성·A 영역 auto_supports, 인수분해 1회) → umax·C 배율만(상관·MAC = null). 변형 비교 variant = 주 방식 + 다른 방식 + `diag.cell_sweep_mm`(기본 [null, 10, 5, 3] — null = legacy) 각각, (c) 형상 = 다른 방식 점수 `score_alt`·ESL별 C_alt·umax_alt. 진단 실패는 결과를 막지 않음(경고 `LT_DIAG_SKIPPED: <단계> <코드>`) | 사용자 결정 4. 셀 크기 훑기가 "셀을 얼마나 줄여야 하나" 질문의 직접 답 |
| D-0.20.0-LT-11 | **기본값·호환**: 새 스터디 기본 `method: work`, `support: transfer`, `region.mode: auto`, `diag.enabled: true`(§12 Q1~3 권고). 요청으로 `method`·`cell_size_mm` 만 덮어씀(나머지는 설정). **스냅샷**: 생성 시 해석한 전체 값을 `doe.load_transfer`(작업 spec)·`inputs.load_transfer` 에 고정, 워커는 spec 만 읽음(설정 변경 무관). **옛 스터디(키 없음) = legacy** = `{method: cell, cell_size_mm: null, support: auto, region: all, diag: off}` 와 같은 코드 경로 → 준비·실행·결과 바이트 동일. 복제 = 원 스터디의 method·cell_size_mm·support·region 유지(없으면 legacy 값을 명시적으로 기록), diag 는 현재 설정 | 기존 결과 재현성. "기존 동작 보존" 대신 새 기본을 work 로 바꾸는 근거 = #63 수치(셀 매핑은 d000 에서도 ① 과 무관한 하중) |
| D-0.20.0-LT-12 | **이어하기 해시**: `_cmp_sha` 의 keep 에 `load_transfer`(spec 의 method·cell_size_mm·work·support·support_tol_mm·region 해시) 를 **스냅샷에 키가 있을 때만** 추가(diag 는 해시 밖 — 진단 설정만 바꿔 재실행해도 주 결과 재사용). legacy 해시 불변 | C2-D-15 와 같은 방식 |
| D-0.20.0-LT-13 | **산출물 형식 최소 추가**: result.json(형상)·순위·per_esl·CSV 기존 열 **불변**. 추가 = `run/designs/<did>/load_transfer.json`, `post/load_transfer_diag.json`, `post/result.json.load_transfer`(요약)·`view3d_ref`·`view3d_esl`, `ranking.csv` **끝 열** `lt_method, lt_far_frac, lt_dM_rel, score_alt`(새 스냅샷만), report.html 절 1개(방식·d000 참값 대비 표). 화면 = 요약 1줄 + 접힘 표(§7) | 서버는 읽기만 — zip·CSV 로도 판단 가능해야 함 |
| D-0.20.0-LT-14 | **성능 상한**: W 사영 = 원본 A 194k 노드 × 대상 380k 요소에서 ≤ 20 s·형상(cKDTree + 벡터화), C 3 mm 새 요약·분배 ≤ 60 s·ESL·형상. 넘으면 진행하되 `stage_times` 기록. d000 추가 풀이 수 = K × (1 참값 + 1 alt + m 훑기) — 인수분해 1회 공유, 메모리는 keep_u 를 MAC 계산 직후 버림 | 실행 시간이 셀 매핑 대비 크게 늘지 않게 |

## 4. 설정 · 요청 · 스냅샷

### 4.1 설정 키 (`bead_doe.compare.load_transfer` — `esl/doe/__init__.py DEFAULTS`·pydantic `BeadDoeCompareLoadTransferCfg`·`config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml` **4곳 거울**)

```yaml
bead_doe:
  compare:
    load_transfer:                 # v0.20.0 ④ 하중 전달(계약 esl_load_transfer.md) — 섹션 없으면 아래 기본
      method: work                 # work(일 등가 f_t = Tᵀ f_A) | cell(셀 매핑) — 새 스터디 기본(요청 load_transfer 로 덮어씀)
      cell_size_mm: null           # cell 셀 크기(null = 기존 ESL 요약 24×14 격자·병합 규칙 그대로)
      cell_choices_mm: [null, 10.0, 5.0, 3.0]   # 화면 select 의 셀 선택지(null = 기존 격자)
      cell_min_mm: 3.0             # 셀 크기 하한(요청 검사)
      work: {knn: 8, proj_tol_mm: 3.0, newton_iter: 10, far_warn_frac: 0.01, far_fail_frac: 0.2}
      support: transfer            # transfer(기준 d000 지지 → 형상 최근접 노드) | auto(형상마다 PCA 3-2-1, 예전)
      support_tol_mm: null         # 이전 거리 허용(null = 2h) — 넘거나 rank < 6 이면 그 형상만 auto + LT_SUPPORT_FALLBACK
      region: {mode: auto, pad_mm: null, min_frac: 0.5}   # 평가 영역(③ SG-D-19 와 같은 규칙) auto | a_bbox | largest | all
      diag:
        enabled: true              # 하중 전달 진단(LT-10)
        alt: true                  # 다른 방식도 풀어 score_alt(work ↔ cell)
        alt_cell_size_mm: 3.0      # 주 방식이 work 일 때 alt cell 의 셀 크기(null = 기존 격자)
        cell_sweep_mm: [null, 10.0, 5.0, 3.0]   # d000 셀 크기 훑기(참값 대비 변형만, 0 개 = 끔)
```
- pydantic 검사: `method` Literal; `cell_size_mm`·`alt_cell_size_mm` null 또는 `cell_min_mm`..200; `cell_min_mm` 1..200; `cell_choices_mm`·`cell_sweep_mm` 원소 null 또는 ≥ `cell_min_mm`, 길이 ≤ 8, 중복 금지; `knn` 1..64; `proj_tol_mm` null 또는 > 0; `newton_iter` 1..50; `0 ≤ far_warn_frac ≤ far_fail_frac ≤ 1`; `support` ∈ {transfer, auto}; `support_tol_mm` null 또는 > 0; `region.mode` ∈ {auto, a_bbox, largest, all}, `pad_mm` null 또는 > 0, `min_frac` (0,1].
- `GET /doe/settings` `compare` += `load_transfer{method, cell_size_mm, cell_choices_mm, cell_min_mm}`.

### 4.2 요청 (`DoeCheckIn`·`DoeStudyIn`, compare 만)

```text
DoeCheckIn(compare) += { load_transfer?: "work"|"cell", cell_size_mm?: float|null }     # 없으면 설정값
DoeCheckOut(compare) += { load_transfer:{method, cell_size_mm, support, region_mode} }   # 해석된 값
DoeStudyOut.inputs(compare) += { load_transfer:{method, cell_size_mm, support, region_mode} }   # 옛 스터디 = 키 없음
```
- 검사(기존 §3 순서 뒤): compare 아닌 시나리오에 두 키 → 422 `INVALID_PARAMS`; `load_transfer` 값 → 422(pydantic); `work` + `cell_size_mm` 값 있음 → 422 `LOAD_TRANSFER_INVALID`; `cell_size_mm` < `cell_min_mm` 또는 > 200 → 422 `LOAD_TRANSFER_INVALID`(detail `min`·`max`). `cell` + `cell_size_mm` 생략 = 설정 `cell_size_mm`.
- 작업 spec `params.doe.load_transfer` = 4.1 전체를 요청으로 덮은 **해석된 dict**(+ `schema: 1`). 워커는 이 dict 만 읽음.

## 5. 진단 파일 형식

`run/designs/<did>/load_transfer.json`(형상마다) 과 이를 모은 `post/load_transfer_diag.json`:

```text
{ schema: "esl/doe_load_transfer_diag/1", method, cell_size_mm, alt:{method, cell_size_mm}|null,
  reference:{did:"d000", source:"case"|"step", identity: bool, truth:"direct_nodal"|"a_direct"|null},
  shapes:[{ id, status, supports:{mode:"transfer"|"auto"|"fallback", max_dist_mm, reason?},
            region:{mode, n_in, n_out}, transfer:{max_dist_mm, far_n, newton_fallback_n, seconds},
            per_esl:[{ entry_id, label,
                       primary:{sum_abs_f, max_abs_f, dF_rel, dM_rel_before, dM_rel, corr_rel, far_frac, small_frac?},
                       alt?:{… 같은 키, C, umax} }],
            score_alt? }],
  d000:{ truth, rows:[{ entry_id, label, variant:"work"|"cell:legacy"|"cell:<s>",
                        load_corr|null, sum_abs_ratio, max_abs_ratio, umax_ratio, C_ratio, mac|null }] },
  warnings:[…], seconds }
```
- 정의: Σ|F| = Σ_i ‖f_i‖, max|F| = max_i ‖f_i‖; `dF_rel` = ‖ΣF_t − ΣF_A‖ / Σ|F_A|; `dM_rel` = ‖M_t − M_A‖ / (Σ|F_A|·L_b)(A 노드 중심 기준, L_b = A bbox 대각) — `_before` = LT-4 보정 전; `corr_rel` = 보정 Σ|d| / Σ|F_t|; `load_corr` = (f_m·f_ref)/(‖f_m‖‖f_ref‖)(3N 성분, 같은 노드 순서 — d000 identity 일 때만); `umax_ratio` = umax_m / umax_ref, `C_ratio` = C_m / C_ref(같은 d000 지지·물성·영역); `mac` = (u_m·u_ref)² / ((u_m·u_m)(u_ref·u_ref))(병진 3N, identity 일 때만); `score_alt` = 다른 방식으로 같은 점수 식(최악 ESL C ÷ d000 최악 C).
- `post/result.json.load_transfer` = `{method, cell_size_mm, support, region_mode, alt:{method, cell_size_mm}|null, truth, summary:[{variant, umax_ratio:[min,max], C_ratio:[min,max], mac_min|null, load_corr_min|null}], rank_alt_same: bool|null, warnings_n}`. legacy = 키 없음.
- `ranking.csv` 끝 열(새 스냅샷만): `lt_method`(예 `work`·`cell:3`), `lt_far_frac`(ESL 최대), `lt_dM_rel`(ESL 최대, 보정 전), `score_alt`.

## 6. 오류 · 경고 코드 (신규, 문구 원본 `resources/doe_messages.json`)

| 코드 | 위치 | 의미 |
|---|---|---|
| `LOAD_TRANSFER_INVALID` | 422 | work + cell_size_mm, 셀 크기 범위 밖 |
| `LT_TRANSFER_FAILED` | 형상 `FAILED_SIZE`(d000 = 준비 실패 `BASELINE_FAILED`) | 먼 노드 Σ|f| 비 > far_fail_frac — "ESL 원본 메시를 이 형상에 옮길 수 없음(최대 거리 x mm)" |
| 경고 `LT_FAR_NODES` | prep·결과 형상 행 | far_frac > far_warn_frac |
| 경고 `LT_SUPPORT_FALLBACK` | prep·결과 형상 행 | 지지 이전 실패 → 그 형상 auto 3-2-1(공정성 예외 표시) |
| 경고 `LT_ESL_UNBALANCED` | prep | ESL 자체 불평형 > 1e-6 |
| 경고 `LT_DIAG_SKIPPED` | 결과 | 진단 단계 실패(주 결과 영향 없음) |
| 정보 `COMPARE_REGION` / 경고 `COMPARE_REGION_SMALL` | prep·결과 | LT-8 |
| 재사용 | | `MAPPING_DEGENERATE`(새 C 6 제약 실패 — 그 셀은 W 로 넘기므로 정상 경로에서는 없음), `SUPPORT_DEGENERATE`, `BASELINE_FAILED`, `INVALID_PARAMS` |

## 7. 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음 — 필수만)

- **필수성 검토**: (1) 방식 선택 select = 필수(사용자 결정 2 — 두 방식을 고를 수 있어야 함). (2) 진단 요약 = 필수(사용자 결정 4 — 서버에서 판단할 수 없음). (3) 지지·영역·훑기 목록 = 화면 칸 없음(설정만, 결과 줄에 표시). (4) 3D ESL 이름 = 필수(같은 ESL 임을 보여야 함).
- ④ 고급 설정(`CompareMeshAdvanced`) 안에 **select 1개** "하중 전달": `일 등가(권장)` | `셀 <s> mm` … (`cell_choices_mm` 순서, null = `셀 기존 24×14`). 기본 = 설정값 "(기본)" 표기, 기본과 같으면 요청에 안 보냄. 요약 줄에 "· 하중 일 등가" 추가. 준비 후 형상 표 상태 배지에 `LT_TRANSFER_FAILED`·`LT_SUPPORT_FALLBACK` 문구(기존 배지 칸).
- 결과 카드 순위 아래 **요약 1줄**: `하중 전달: 일 등가 · 기준 대비 ①: umax ×a~b · C ×c~d · MAC ≥ e  |  셀 3 mm: umax ×… · MAC …` (summary 의 주 방식 + 다른 방식 최대 2개). 그 아래 `<details>` 표 2개: d000 variant × ESL(상관·umax·C·MAC), 형상 × (주 점수·score_alt·far_frac·지지 mode). legacy = 줄·표 없음.
- 3D 비교: 좌측 = `view3d_ref[view3d_esl[선택 형상]]` ?? `d000`, 두 카드 머리 "ESL <label>", 기존 안내 "색 = 변위 |u|(최악 ESL)" → "색 = 변위 |u| · ESL <label>(선택 형상의 최악)".

## 8. 시험 (V-LT-*)

| ID | 시험 | 위치 |
|---|---|---|
| V-LT-1 | **같은 메시 W = ①**: 합성 A(400×300 판 + 비드 1, 3 mm quad·tria 혼합) + 합성 ESL f_A = K_A u_drop(자유-자유 K, 굽힘 + 국부 모드 → 이웃 상쇄 Σ|F|/‖ΣF‖ 큼) → d000 = A: (a) 빠른 경로 하중 = direct_nodal **비트 동일**, (b) 빠른 경로를 끈 일반 사영 경로 max‖ΔF‖ ≤ 1e-9·max|F|, umax·C 상대차 ≤ 1e-9, (c) 진단 `load_corr` = `mac` = `umax_ratio` = `C_ratio` = 1(1e-9) | `tests/doe/test_load_transfer.py` |
| V-LT-2 | **재메시에서 W 가 C 보다 ① 에 가까움**: 같은 판 STEP 을 gmsh h 2.5·3.5 mm 로 메시(d001·d002) + 기준 = A Case 메시 → 시험이 형상마다 A direct(같은 물성·영역 지지) 대비 직접 계산: W 의 umax_ratio·C_ratio ∈ [0.7, 1.3], `cell:legacy` 는 둘 다 > 3, `cell:3` 은 W 와 legacy 사이; d000(=A) 진단에서 MAC_W ≥ 0.999, MAC_legacy < 0.5(이슈 #63 증상 재현) | `tests/doe/test_load_transfer.py`(gmsh 없으면 skip) |
| V-LT-3 | **평형·합력 보존**: 임의 사영(대상 = A 를 법선 0.5 mm·면내 1 mm 이동 + 재메시) → W: ΣF_t = ΣF_A(1e-12 상대, 보정 전), `dM_rel_before` = 해석값 ‖Σ d n×f‖ 과 1e-9 일치, 보정 후 dF·dM ≤ 1e-10; 새 C(s = 10·3): 같은 기준, 셀 노드 0~2 개 셀은 W 경로(`n_cells_small` > 0)·셀 합력 보존 1e-9; legacy C = 지금 `to_target` 결과와 비트 동일 | 같은 파일 |
| V-LT-4 | **공정성**: (a) d000 과 d001 = 같은 STEP 같은 메시 → 두 방식 모두 score = 1(1e-12)·지지 이전 거리 0, (b) d000 만 다른 규칙을 쓰는 경로가 없음 — `shape_loads` 호출 인자에 did 분기 없음(코드 검사: d000·형상이 같은 spec), (c) d000 = Case 메시여도 하중 method 기록 = 스터디 method(direct_nodal 은 빠른 경로 표기 `fast_path: identity` 로만), (d) 지지 이전: d001 = d000 을 0.4 mm 평행 이동 → 이전 노드 = 최근접, C 상대차 ≤ 1e-9(자기평형 → 지지 무관), umax 는 auto 보다 d000 에 가까움, 이전 거리 > tol → `LT_SUPPORT_FALLBACK` | 같은 파일 |
| V-LT-5 | **먼 노드**: A 에 보스 1개가 있고 d001 에 없음 → 보스 노드 far, 합력 보존, `far_frac` 경계(0.0099/0.0101 → 경고 없음/`LT_FAR_NODES`, 0.199/0.201 → 진행/`FAILED_SIZE LT_TRANSFER_FAILED`), d000 이면 `BASELINE_FAILED` | 같은 파일 |
| V-LT-6 | **영역**: ③ 합성 H6 + 주 시트와 이어진 추가 형상(`synth_step_graph`) → auto 영역 = 주 시트, 영역 밖 노드 하중 0(W·C), umax·epsmax 영역만, 지지 노드 영역 안, frame·정렬 = 추가 형상 없는 STEP 과 1e-9, `COMPARE_REGION` 정보; mode all = 지금과 같은 값 | 같은 파일 |
| V-LT-7 | **진단 파일**: §5 키·정의(상관·MAC 수식 단위 시험), d000 이 STEP 이면 truth = a_direct·상관·MAC null, `cell_sweep_mm` 0개 = 훑기 없음, alt 끔 = score_alt 없음, 진단 단계 예외 → `LT_DIAG_SKIPPED` 이고 순위 불변 | 같은 파일 + `worker/tests/test_doe_compare_lt_jobs.py` |
| V-LT-8 | **3D 같은 ESL**: 형상 2개의 최악 ESL 이 다를 때 `view3d_ref` 에 ESL 2개(`d000_e00`·`d000_e02`), 각 manifest `esl_run_id` = 그 ESL, `result.view3d` 목록 불변, d000 인수분해 1회(stats) | `worker/tests/test_doe_compare_lt_jobs.py` |
| V-LT-9 | **E2E**: 합성 STEP 3개 + 합성 ESL 2개, method work·cell 각 1 스터디 → 준비·실행·결과·CSV 끝 열·report 절, 이어하기(같은 spec 재실행 = 재사용, method 바꾸면 재계산, diag 설정만 바꾸면 주 결과 재사용) | `worker/tests/test_doe_compare_lt_jobs.py` |
| V-LT-10 | **API·설정**: 4.1 검사 전부(경계값), 4곳 거울 일치(DEFAULTS = pydantic 기본 = 두 yaml), 요청 검사 순서·코드, 스냅샷 `doe.load_transfer`·`inputs.load_transfer`, 옛 스터디 응답(키 없음), 복제 규칙(LT-11), settings 블록 | `backend/tests/test_doe_load_transfer_api.py`, `backend/tests/test_config*.py`(거울) |
| V-LT-11 | **UI**: select 선택지·기본 표기·요청 생략 규칙, 요약 줄·접힘 표(새 결과), legacy 결과 = 줄 없음, 3D 좌측 = view3d_ref, ESL 이름, 2560×1440·1920×1080 잘림 없음 | `frontend/src/__tests__/doe_load_transfer.test.tsx`, mock |
| V-LT-12 | **회귀(바이트 동일)**: legacy spec(키 없음)으로 `scripts/regress.py`(작업 폴더, V-C2-30 방식) ④ mode 없음·cad·auto × h5·h3 × step·case 준비·loads.npz·result.json·ranking.csv·순위·view3d **main 과 바이트 동일**; ①②③ `sel_regress`·`selreg` 바이트 동일; `esl/library/mapping.py`·`esl/opt/target.py`·`evaluate.py` diff 0; 기존 `tests/doe/*`·`worker/tests/test_doe_*`·`backend/tests/test_doe_*` 통과(새 스터디 기본이 work 로 바뀌어 셀 매핑을 전제한 ④ 시험은 spec/요청에 `cell` 을 명시하도록 고침 — 기대값 변경 금지) | 기존 + 작업 폴더 |
| V-LT-R1 | (수동, 이슈 #63) ④ ed2b971b 입력 재실행(work·cell 3 mm): d000 = A → 진단 umax_ratio·C_ratio·MAC(work = 1), 셀 훑기 표가 "셀 크기 → ① 근접도" 답, d001 지지 이전·영역(주 시트 밖 ≈ 7만 요소 제외) | 현장 |

## 9. 파일 소유권 (겹침 0)

| 담당 | 파일(소유) | 시험 |
|---|---|---|
| **core-geom** | 신규 `esl/doe/load_transfer.py`(`build_work(a_mesh, t_mesh, region, cfg) → W`, `apply_work`, `cell_loads(entry, t, s, W, cfg)`, `shape_loads(target, entries, spec, ctx)`, `transfer_supports(ref_t, mesh, region, tol)`, `diag_rows(...)`, MAC·상관 함수); `esl/doe/scenario.py`(`compare_target` 선택 인자 `supports`·`region` — 없으면 바이트 불변, `shape_check` 선택 인자 `region`); `esl/doe/stages.py`(④ 분기만: `_cmp_loads`·`_cmp_design_mesh`·`_view3d` compare 분기·`_cmp_refine_bias` 하중 호출·`_cmp_sha` keep·BD_BASELINE/BD_DESIGNS 진단 풀이·`_cmp_post` 진단 모음·view3d_ref·`_cmp_ranking_csv` 끝 열); `esl/doe/report_doe.py`(④ 절 1개); `esl/doe/__init__.py`(DEFAULTS `compare.load_transfer`); `resources/doe_messages.json`(§6 코드); 신규 `tests/doe/test_load_transfer.py`, `tests/doe/synth_compare.py`(합성 ESL·보스 판 함수 추가만) | V-LT-1~7, 12 |
| **backend** (`backend/**`, `worker/**`, `config/*.yaml`) | `backend/esl_platform/core/config.py`(`BeadDoeCompareLoadTransferCfg`·`BeadDoeCompareCfg.load_transfer`·settings 거울); `api/schemas.py`(`DoeCheckIn`·`DoeStudyIn` 두 키, `DoeCheckOut`·`DoeStudyOut.inputs`·`DoeResultOut.load_transfer`·`view3d_ref`·`view3d_esl`·settings `compare.load_transfer`); `api/services/doe.py`(검사·스냅샷·복제·settings·결과 통과); `worker/esl_worker/doe_jobs.py`(spec 전달만 — 필요 시), `worker/esl_worker/register.py`(prep 요약 형상 행 lt 경고); `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`; `docs/contracts/openapi_p1b.json`(dump); 신규 `backend/tests/test_doe_load_transfer_api.py`·`worker/tests/test_doe_compare_lt_jobs.py` | V-LT-8~10 |
| **frontend** (`frontend/**`) | `src/api/types.ts`·`src/api/doe.ts`(요청 키·결과 타입); `src/pages/doe/DoeStudy.tsx`(`CompareMeshAdvanced` select, 결과 요약 줄·접힘 표, `Compare3D` view3d_ref·ESL 이름); `src/components/DoeInputs.tsx`(요약 줄 "· 하중 …"); `src/mock/doedata.ts`·`src/mock/server.ts`; 신규 `src/__tests__/doe_load_transfer.test.tsx` | V-LT-11 |
| 통합(Plan) | `VERSION`·`CHANGELOG.md` 0.20.0, `docs/decisions.md`(LT-1~14 옮김), `docs/manual/user.md`(④ 하중 전달·진단 읽는 법), 이 문서 | – |

- 순서: core-geom(`load_transfer.py` 시그니처·§5 형식 먼저 고정) ∥ backend(§4 스키마·설정) ∥ frontend(mock) → 통합 E2E(V-LT-9) → 회귀(V-LT-12) → 현장(V-LT-R1).
- 공동 수정 금지: `stages.py`·`scenario.py`·`report_doe.py`·`doe_messages.json` = core-geom 단독, `schemas.py`·`config.py`·`config/*.yaml`·`worker/**` = backend 단독, `types.ts` = frontend(backend 스키마 거울). `esl/library/mapping.py`·`esl/opt/target.py`·`esl/doe/evaluate.py`·`esl/doe/step_graph.py` = **변경 금지**(가져다 쓰기만).

## 10. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-LT-1 | 형상 메시가 A 보다 훨씬 성기면(h ≫ A 요소) T 가 이웃 상쇄를 한 요소 안에서 평균 → 일부 모드 손실 | ④ 메시 h 3 mm ≈ A 와 같음. d000 a_direct 대비 진단으로 드러남(V-LT-2) |
| R-LT-2 | 얇은 이중 벽·보스 벽처럼 가까운 두 면에서 사영이 다른 면으로 감 | 최근접 거리 기준 + 먼 노드 진단, 영역으로 주 시트 밖 제외. 법선 일치 조건은 후속(진단으로 확인 후) |
| R-LT-3 | 형상 좌표계가 A 와 다름(정렬 허용 0.05·L 안에서 원점이 수 mm 이동) — W 는 전역 좌표라 이동이 먼 노드로 나타남 | SC-D-7b 정렬 검사 유지 + `LT_FAR_NODES`·`LT_TRANSFER_FAILED`. 강체 맞춤은 비범위 |
| R-LT-4 | C 3 mm 의 새 요약·셀 루프 시간 | 일괄 정규방정식(LT-6), 상한 LT-14, `stage_times` |
| R-LT-5 | 진단 풀이(d000 K×(2+m))로 BD_BASELINE 시간 증가 | 인수분해 1회 공유, `diag.cell_sweep_mm` 줄이기로 조절 |

## 11. esl_step_compare.md 와의 관계

- SC-D-2(기준 미지정 = Case 메시도 셀 매핑)·SC-D-6(하중 = 셀 매핑, 지지 = 형상별 auto_supports)은 **legacy 스냅샷에만** 적용. 새 스터디는 LT-1~8.
- SC-D-10 한계 절 문구에 "하중 전달 방식·진단 요약"을 덧붙임(report_doe).

## 12. 사용자에게 물을 결정 (권고안으로 진행, 답에 따라 기본값만 변경)

| Q | 질문 | 선택지 | 권고 |
|---|---|---|---|
| Q1 | 새 스터디 기본 하중 전달 | A `work`(일 등가) / B `cell` 3 mm / C 기존 셀(24×14, 지금 동작) | **A** — 같은 메시에서 ① 과 비트 동일, 셀 매핑은 #63 에서 d000 에서도 상관 0.02~0.04. 진단에 alt(cell 3 mm)·셀 훑기가 같이 나오므로 같은 스터디 안에서 비교 가능 |
| Q2 | 지지 기본 | A `transfer`(기준 지지 → 최근접 노드) / B `auto`(형상마다 PCA 3-2-1) | **A** — 점수(C)는 지지와 무관하고 umax·3D 그림만 같은 기준점이 됨, 실패 시 형상별 auto + 경고 |
| Q3 | ④ 평가 영역 기본 | A `auto`(A bbox 와 겹치는 최대 연결 성분 = 주 시트) / B `all`(지금) | **A** — #63 d001 주 시트 밖 ≈ 7만 요소가 umax·지지·frame 을 오염, ③ 과 같은 함수·규칙 |
