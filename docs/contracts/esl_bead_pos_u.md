# 계약: 비드 위치 변수 U(경로 수직 평행 이동) + 위치 변수 스터디의 하중 공간 고정 (PU, v0.24.9)

- 상태: 설계 확정 초안(2026-11-25) + A0 감사 보정(2026-11-25, 코드 = main 1d71d983 = v0.24.6 — v0.24.7·v0.24.8 코드 머지 전이라 `esl/morph/section.py`·`grid_map` 은 아직 없음, 행 번호는 이 코드 기준). 브랜치 `release/v0.24.9`(base release/v0.24.8 — v0.24.7·v0.24.8 머지 뒤 재기반). A0 감사의 불일치 9건은 메인 결정(2026-11-25, D-0.24.9-PU-7~15)으로 본문에 반영함.
- 관계: `esl_bead_depth_mode.md`(v0.24.7 — 패키지 띠·허용 구역 공용 함수, W1, 판 고정 `OUTPUT_VERSION`), `esl_jig_grid_map.md`(v0.24.8 — `_plan_loads(…, srcs=…)` 일반형, 기준도 같은 경로 원칙), `esl_beadgraph.md` BG-D-24·27·28·29·30·34, `esl_bead_select.md` BS-D-16(위치 보류 — 이 계약이 그래프 방식 U 만 해제), `esl_load_transfer.md` LT-4·LT-6.
- ID: 결정 `D-0.24.9-PU-n`, 시험 `V-0249-PU-n`, 후속 `R-PU-n`, 미결 `Q-PU-n`, 현장 `F-PU-n`.
- 용어: 화면 = "위치(U)". 내부 = U(경로에 수직인 평면 이동, mm, 공칭 0). V(경로 방향) 는 범위 밖.

### 사용자 요청 (원문, 변경 금지)
- "비드 위치 변화는?? 많이는 아니더라도 조금씩 한 비드 폭 크기 대비 50%이하라도 움직엿음 하는데 어려울려나"
- "응넣어줘. 페이블 네가 이 3가지 버전 업그레이드 검토 하고 계약 보완 까지 해줘. 구현은 오퍼스 가 지휘하게하고"
- 합의(2026-11-25 대화): 경로 수직 방향만, 기본 범위 ±0.25·W, 상한 0.5·W, 비드마다 실제 가능 범위는 범위 점검이 줄여 표시, 위치 변수를 켠 스터디는 하중을 3 mm 격자로 공간에 고정.

배경: #88 에서 B8 은 깊을수록 불리(깊이 1 mm 증가당 score −1.98 % — 안 결과에서 직접 계산한 값) — 하중 경로를 가로지르는 비드일 가능성. 깊이·폭으로는 못 바꾸는 "어디에 두느냐"를 보려면 위치 변수가 필요하다.

---

## 0. 감사 (계약 = release/v0.24.8 기준, 코드 행 번호 = main 1d71d983 — A0 완료 2026-11-25)

| 항목 | 지금 | 근거 |
|---|---|---|
| 변수 종류 자리 | `PARAM_TYPES = ("D", "W", "U", "V")` — U·V 는 paicad(STEP) 변수 이름에만 쓰임, 그래프·선택 방식은 D·W 만 | `esl/doe/__init__.py:37`, BS-D-16, BD-D-7 |
| W 기저 이동 규칙 | 이동 노드 = E ∪ 벽 ∪ 깊이면 가장자리, u = ½·n_out(골격에서 바깥 — 양쪽이 반대 방향), 방향장 평활 `_smooth_dirs`, 깊이면 = 평면 조화 확장(자식·공유 자식 벽·섬·J = 0), 부모 바닥 띠 R_w = max(blend.min_mm, blend.k·ext/2, 3h), 띠가 다른 형상에 닿으면 smoothstep 으로 자름 + `SELECT_BLEND_CLIPPED` | `packages/beadgraph/src/beadgraph/morph.py:269-305`·`:306-322` |
| 쪽 정보 | `polyline_dist` 가 골격 기준 쪽(side ±, 진행 방향 왼쪽 +)을 이미 돌려줌 — W 는 버림(`_side`) | `morph.py:77-90`, `absorb.py:31-71` |
| 띠 크기 | `select.blend {min_mm 15, max_mm 200, k 8}` → 한쪽 이동량의 8배 | `esl/doe/__init__.py:260` |
| 같은 메시 모드 하중 | 계획 `reuse: once` — 기준 메시에서 1회 구한 노드 하중을 모든 안이 **노드 번호로** 그대로 씀(BD-D-3) → 노드가 평면으로 움직이면 하중도 따라 움직임 | `esl/doe/transfer_plan.py:19-20`·`:37-41` |
| 셀 하중 전달 | `load_transfer` 전략 `cell`(칸 합력·모멘트 → 대상 칸 노드 최소노름, 노드 < 3 칸은 일 등가 사영 W), LT-4 전체 합력·모멘트 보존. 선택지 `cell_choices_mm [None, 10, 5, 3]` | `esl/doe/load_transfer.py:1-18`·`:474-526`, `esl/doe/__init__.py:228` |
| 지그 안 평가 | 기준 npz 의 a·BC·k 고정, 노드 ID 로 위치 맞춤 | `esl/doe/stages.py` `_jig_design_multi`(v0.24.8 계약 §0.1) |
| A0-1 공칭 0 — 그대로 맞는 곳 | 범위 점검 순수 모듈은 공칭 상대식(`single`·`blocked`·`combo`·`inward` 모두 v₀ 기준, 비대칭 usable 그대로) · 모핑 x = x0 + (v − v_nom)·B · 422 "> 0" 은 `_POSITIVE = ("D","W")` 만 · 프런트 행 오류도 D·W 만 · 축소 판정 `u[0] < nom < u[1]`(공칭 0·비대칭 OK) · 램프 부족 경고는 W 만 ½(U 는 D 처럼 ext 그대로 = §1.1 L 식과 같음) · 달성 허용 D 아닌 것 1e-3(U = 1e-3, §1.1 과 같음) · 민감도·보고서·재낙하는 값만 씀(공칭·% 계산 없음) · `_r(0)`·`round_to(−0)=0` | `esl/morph/range_guard.py:92-151`·`:193-235`, `bead_select.py:1584`·`:1616`, `packages/beadgraph/.../morph.py:453-463`, `matrix.py:25`·`:107`, `frontend/src/api/doe.ts:1086`, `bead_graph.py:1842`·`:1925`, `:1252-1268`, `:1177`·`:1675`, `rank.py:327-366`, `report_doe.py:651-658`, `esl/verify/redrop.py:94-130`, `matrix.py:33-39` |
| A0-1 공칭 0 — 고쳐야 할 곳(§1.3 반영) | (a) 공칭 선택 `D_nom if D else W_nom` 4곳(U 가 W_nom 을 받음) · (b) 기본·feasible 범위 = 비율 × 공칭(D·W 전용 식) · (c) 패키지 `_one` 공칭 = D 아니면 entry_width 평균, `ext` 없을 때 `0.3·nominal`(U = 0), `ext_eff = ½ext`(W 전용), R_w = k·ext/2 · (d) 행렬에 "공칭 ∈ [lo, hi]" 검사 없음 · (e) 썸네일 자동 색 범위 = D 변수만 · (f) 백엔드 옛 문서 대체 경로 `vars ∈ (D, W)`·묶기 `("D","W")`(새 스냅샷은 코어 params 그대로라 무영향) · (g) SR-D-38 교차 점검 W 만 · (h) 프런트 라벨: 그래프 비드 행은 D 아니면 "W"/"폭 W", 계획 칩도 같음 | (a) `bead_graph.py:1092`·`:1144`·`:1642`·`:1776`·`:1902`·`:1923` · (b) `:1006-1017` · (c) `morph.py:219-229`·`:279` · (d) `matrix.py:100-112` · (e) `matrix.py:237-241` · (f) `backend/.../services/doe_select.py:716`·`:722`·`:788` · (g) `esl/morph/core.py:259-261` · (h) `frontend/src/components/DoeParamTable.tsx:244`·`:252`, `pages/doe/DoeStudy.tsx:1406` |
| A0-2 lin 보조 열 | 베이스라인 `u_ref = remove_rigid(u6)`(그 안의 해) → `prep/sm_ref.npz u` 를 노드 ID 로 저장, 안은 같은 노드 ID 의 u 를 그대로 u_t 로(`sm_disp ("I","I")`) → ρ = u_tᵀK_d u_t / C_ref, C_ritz = C_ref/ρ, imbalance = F_d − K_d u_t. 즉 "기준 해를 **노드에 붙여** 옮긴 시험 변위장 + 기준 하중 F₀(노드 번호)" 에 대한 Ritz 추정 → spatial(F_d ≠ F₀ 노드 번호) 에서는 다른 하중 문제의 추정이라 **무효**(C_lin·C_ritz·rho·imbalance_rel 모두) | `stages.py:3604-3606`·`:3644-3645`·`:3659-3664`·`:3679-3686`, `stiffness_metric.py:6-12` |
| A0-2 그대로 유효 | solve(안마다 K_d u = F_d 재풀이 — 하중만 바뀜) · umax_def(u3 강체 제거) · 지그 안(`_jig_design_multi` — a·BC 값·k 기준 고정, 하중 = Σa·기저를 노드 ID 로 배치 → 이 배열만 전달본으로 바꾸면 됨) · v0.24.1 재현 진단(d000 만, X_d = X₀) | `stages.py:3686`, `:4421-4491`(하중 `:4474-4476`), `:5494-5504` |
| A0-2 기준 변위를 쓰는 지그 준비 | 베이스라인 지그 목표 u_tgt = `prep/sm_ref.npz u`(그 스터디 d000 해) → 맞춤 a·g·Cmix_ref·E_ref | `stages.py:3954-3960`, `:4291`·`:4312-4319`·`:4342-4352` |
| A0-3 hold 집합 | ψ = 0(ring_mm 안)·Wendland(blend_mm) — 대상 P = 허용 구역 노드 ∩ fixed, **비드 `hold_fixed = 1` 일 때만**(0 이면 ψ ≡ 1). fixed = `prep/fixed` fixed-scan **모든 종류** 노드 ID ∪ fixed_user 요소 노드. select_base step(새 ③) 은 fixed-scan 없음(빈 집합) → fixed_user(A 이전 seed) 만. fixed 노드가 있는 섬은 강체 이동 안 함(`BG_ISLAND_HELD`) | `morph.py:56-66`·`:323`·`:373-380`, `bead_graph.py:966-971`·`:1126`, `stages.py:6261-6273` |
| A0-3 tie·3-2-1 집합 | tie(지그 노드) = case·bmesh_once: `prep/fixed` 를 `rank.jig.fix_kinds` 로 거른 것(⊂ hold 의 fixed-scan), step_once: `prep/select/fixed_transfer.json`(fixed_user 와 같다는 보장 없음). 3-2-1 = 기준 메시 PCA 꼭짓점 `auto_supports`(판 모서리 — fixed 집합과 무관, `base.json supports` 노드 ID 로 모든 안 공유) | `stages.py:3767-3791`, `esl/opt/target.py:97-102`, `scenario.py:192-210` |
| A0-4 변수 표 UI | 종류 필터 없음 · 비드별 접기 없음(카드 전체 접기 `Card fold` 만 — "④ 변수" `fold4`) · 표 감싸개 `.table-wrap`(가로 스크롤만, **max-height 없음**). 높이 제한 유틸 `.table-wrap.scroll { max-height: var(--tbl-max) }` 는 있으나 이 표는 안 씀 · 비드 머리 행에 툴팁 없음(`b.name` 평문) | `DoeParamTable.tsx:196-198`·`:220-240`, `DoeStudy.tsx:1416`·`:1426-1434`, `frontend/src/styles.css:736-742`·`:29`, `components/ui.tsx:44-59` |
| 추가 — F_jig,0 | 저장 배열 없음. 안마다 `jg.forces(basis, a[k], N₀)`(기준 npz 의 기저 `_jig_basis_of(z)` + `z["a"]`)로 기준 노드 순서 하중 Fb 를 만들고 `F[pos] = Fb` 로 노드 ID 배치. 베이스라인은 `run_method` 가 같은 기저로 맞춤 | `stages.py:4468`·`:4474-4476`, `:3843-3847`, `:4312`·`:4342` |
| 추가 — `_plan_loads` | `_plan_loads(c, plan, did, dst, variant=None, cache=None, srcs=None)` — `reuse once ∧ did ≠ d000 ∧ variant None ∧ srcs None` 일 때만 노드 재사용, 그 밖 `run_transfer_plan`. **배치는 안에서 `_lt_placement(c, plan)` 고정**(인수 없음 — case_once global, bmesh·step_once auto = BD_LOADS 가 정한 A→B rigid/frame). 셀 칸은 각 쪽 frame 정규화 좌표(src = `src_load(frame)`, dst = `dst_mesh(frame)`). method cell 이면 같은 메시여도 identity 아님 | `stages.py:2766-2775`·`:2732-2738`, `load_transfer.py:58-73`·`:611-623`·`:661-688` |
| 추가 — 배타 자식 강체 | D 는 조화 확장 전에 `Uv[nC] = s·n0` 로 값을 넣고 Dirichlet(`dir_zero ∋ nC`)로 고정. 섬 블록(`:368-406`)은 조화 확장 **뒤** 둘레(rim = nF ∪ band) 평균인데 섬 노드도 `dir_zero ∋ nI` 라 면내 Dirichlet 값 0 → W·D 의 섬 면내 이동은 0 | `morph.py:257`·`:306-314`·`:368-406` |
| 추가 — 끝단 방향 | `polyline_dist` 반환 = (d, side, 최근접점 cp, n_out) — 선분 번호 없음, 끝 꼭짓점 투영이면 n_out 이 방사 방향. `interior_mask(cp, pts, closed)` 는 끝 꼭짓점 여부(bool, 어느 끝인지는 cp 와 pts[0]/pts[−1] 비교). `_skeleton_dist` 는 side 를 버리고 `closed` 없이 부름 | `absorb.py:31-62`·`:65-72`, `morph.py:77-90` |

## 1. 위치 변수 U — 패키지 kind `U`

### 1.1 정의(변수 ΔU 당 변위, 공칭 0)
- 대상 = 그래프 비드의 세그먼트 집합 S_U = **양쪽 입구가 있는 세그먼트**(v0.24.7 의 S_2 — `entry_width` 있음).
- 방향장 t⊥(x) = 최근접 골격 선분의 **왼쪽 법선**(쪽과 무관한 한 방향 — `polyline_dist` 의 n_out × side). 끝단(골격 끝 투영 밖) 노드는 끝 선분의 t⊥(방사 방향 아님). W 와 같은 `_smooth_dirs` 평활(반복 수 `w_smooth_iters`).
  - 구현(A0): 안쪽 노드 = n_out × side(`absorb.py:31-62` 반환 그대로). 끝단 노드 = `interior_mask` 가 거짓인 노드에서 cp 가 pts[0] 이면 (pts[1] − pts[0]), pts[−1] 이면 (pts[−1] − pts[−2]) 의 왼쪽 법선(선분 번호 반환 불필요 — 패키지 함수 시그니처 불변). U 전용 거리 함수가 side 도 돌려준다(`_skeleton_dist` 는 W 바이트 때문에 그대로 둠).
  - 닫힌 골격(`segments[].closed` 인 세그먼트가 S_U 에 있음): 왼쪽 법선이 루프 전체에서 한 방향(안/바깥)이라 옮기면 고리 크기가 변함 → **U 없음**, 사유 `U_CLOSED`(§1.2, D-0.24.9-PU-7). 고리 강체 이동은 후속 R-PU-7.
  - 1점 골격(`len(pts) == 1` — 방향 없음): **U 없음**, 사유 = `U_AREA`(§1.2, D-0.24.9-PU-8).
- 이동:
  | 노드 | 변위 |
  |---|---|
  | 입구 E·벽·깊이면 가장자리(양쪽 모두) | t⊥ (W 의 ±½·n_out 대신 양쪽 같은 방향 1) |
  | 깊이면 안 | 평면 조화 확장 — 양쪽 가장자리 값이 같으므로 직선 구간은 강체 평행 이동 |
  | 배타 자식(그 비드 깊이면 안 플래토)·그 섬 | 비드와 함께 강체 이동(자식 둘레 평균값) — W 의 "자식 제자리"와 다름. 구현(A0): 섬 블록(`morph.py:368-406`)만으로는 안 됨 — 섬·자식 노드가 조화 확장 Dirichlet 0(`dir_zero ∋ nC, nI`, `:308`)이라 둘레 평균 면내 = 0. D 의 `:257` 방식으로 조화 확장 **전에** nC·(그 비드 섬) nI 노드에 그 자식/섬 중심의 t⊥ 를 넣고 Dirichlet 값으로 쓴다(U 만 — `dir_zero` 를 0 고정 집합(nSC·J·바깥)과 값 고정 집합(nC·nI)으로 나눔). 그 뒤 섬 블록은 그대로(둘레 평균 = 넣은 값) |
  | 공유 자식 벽·접합 구역 J·다른 비드 | 0 (J 에서 램프 φ, L = max(ramp_k·ext, ramp_k·h), ext = 범위 끝 최대 \|ΔU\|) |
  | 부모 바닥 띠(양쪽) | 가까운 입구 값 × (1 − smoothstep(d/R_w)), R_w = max(blend.min_mm, blend.k·ext, 3h) — 이동 쪽은 압축, 반대쪽은 늘어남. 자름 규칙·`SELECT_BLEND_CLIPPED` = W 와 같음 |
  | 섬(보스)·hold | 강체(BG-D-29)·걸친 섬(BG-D-27)·ψ(BG-D-28) = W 규칙. fixed 노드가 있는 섬은 제자리. **U 만**(D-0.24.9-PU-14): 비드 `hold_fixed` 와 무관하게 hold 를 강제로 켜고(`morph.py:323` 의 `b.get("hold", 1)` 대신 kind U 는 늘 1), 패키지에 넘기는 fixed = fixed-scan ∪ fixed_user ∪ 그 스터디 지그 tie 노드(계획 `jig_fix` 출처 — fixed: `prep/fixed` 를 `rank.jig.fix_kinds` 로 거른 것, xfer(step_once): `prep/select/fixed_transfer.json`, 지그 꺼짐·none = 추가 없음). D·W·DF·W1 기저의 hold·fixed 는 지금 그대로 |
- 띠 값 = v0.24.7 구현 보정 DM-C1-2 의 **거리 가중 혼합**(R_w 안 입구 노드 최대 8개, w = 1/(d² + (0.1h)²), × (1 − smoothstep(d_min/R_w)))을 DF·W1 과 같이 쓴다 — 최근접 입구 복사는 마주 보는 입구 선 사이에서 불연속(H5 네트워크 뒤집힘 2 실측). 이웃 비드 쪽으로 옮기는 U 가 이 경우에 해당한다.
- 법선 성분 0(깊이 불변). 직선 구간·φ = ψ = 1 에서 **깊이·폭·사면 각 변화 0**, 비드 전체가 ΔU 이동.
- 띠·허용 구역·`movable_nodes`·바깥 0 점검 = v0.24.7 에서 뺀 공용 내부 함수(W 규칙). 달성 = 직선 표본 입구 노드의 골격 수직 변위 중앙값 = ΔU ± 1e-3(양쪽 각각), 폭 변화 ≤ 1e-3.
- 판: `U_RULES = 1`, 패키지 `__version__` 1.3.0(MINOR). RULES·MORPH_RULES·`OUTPUT_VERSION`("1.1.0")·GRAPH_ALGO 불변 → 옛 graph.json·D·W·DF·W1 기저 바이트 불변.

### 1.2 쓸 수 없는 경우(변수 행 없음 — `beads[].u_reason{code, text}`, 순서 고정 첫 일치)
| 코드 | 조건 | 문구 |
|---|---|---|
| U_OFF | 스냅샷에 `pos_u` 블록 없음(옛 스터디)·설정 꺼짐 | (표시 없음) |
| U_NETWORK | 네트워크 묶기 | 네트워크 묶기는 위치를 옮길 수 없음 |
| U_AREA | 모든 세그먼트 area·plateau(골격 없음) 또는 1점 골격(방향 없음 — PU-8) | 면형 바닥 — 경로가 없어 위치 이동 불가(1점 골격: "경로가 없어 위치 이동 불가") |
| U_CLOSED | S_U 에 닫힌 골격 세그먼트(PU-7) | 닫힌 고리 비드 — 옆으로 옮기면 크기가 변함 |
| U_ONE_SIDE | S_2 = ∅ ∧ 한쪽 입구(S_1) | 한쪽 입구 비드 — 위치 대신 한쪽 W 를 쓰세요 |
| U_NO_ENTRY | 입구 선 없음 | 입구 선을 찾지 못함 |
| U_HELD | S_U 입구 노드 중 ψ < 1(hold) 비율 > `hold_frac_max`, 또는 지그 tie 노드의 U 기저 변위 최대 > 1e-6·ext(PU-14 — 강제 hold 뒤에도 남는 경우) | 체결부에 묶여 옮길 수 없음 |
| U_TIE_MIXED | 대칭 묶기 구성원 중 U 불가가 있거나 \|거울(t⊥_대표)·t⊥_m\| < cos 30°(PU-11) — 묶음 전체 U 없음 | 대칭 묶기 비드의 위치 방향이 맞지 않음 |
- S_2 ⊂ S(일부만 양쪽): S_U = S_2 구간만 이동, 나머지와 사이 접합에서 램프(정보 `PU_PARTIAL{bead, cover}`).
- 선택(요소) 방식·paicad·④: 이번 범위 밖(§1.5 계획 표 `none`, R-PU-2·3). paicad 의 BEAD_POS_U 는 그대로.

### 1.3 변수 행 · 범위
- 이름 `B<n>_U`(`var_name(bid, "U")`), `type: "U"`, `nominal: 0.0`, 단위 mm, `use_default: false`(기본 꺼짐 — 사용자가 비드마다 켬, BD-D-7 과 같은 정책. `doe.default_types [D, W]` 불변).
- 부호: + = 골격 진행 방향의 왼쪽. 행에 `dir{xi, eta}`(ESL frame 에서 평균 t⊥ 성분)·`dir_text`("+ξ 쪽"·"−η 쪽" — 큰 성분 기준, 곡선 비드는 "바깥쪽"/"안쪽"(골격 곡률 중심 반대/쪽)).
- W_ref = S_U 의 entry_width 길이 가중 평균.
- feasible(추정, `source: estimate`) — 부호별: hi = min(`max_rel`·W_ref, `gap_rel`·g₊), lo = −min(`max_rel`·W_ref, `gap_rel`·g₋), g± = 그 쪽 입구 선에서 가장 가까운 "다른 형상"(다른 비드 구역·섬·fixed·판 외곽) 노드까지 평면 거리의 5 % 분위(직선 표본).
- 기본 범위 = [max(−`range_rel`·W_ref, lo), min(+`range_rel`·W_ref, hi)]. 사용자 범위가 feasible 밖 = 경고 배지(막지 않음), lo ≥ hi·0 을 포함하지 않는 범위 = 422(공칭 0 이 범위 안이어야 함 — 기준 d000 = 지금 형상).
- range guard(SH-13~16): U 후보를 ±ext 에서 조합 포함 점검(같은 비드 D·W·U 자동 묶음, 이웃 비드와는 띠가 영향 요소를 공유하면 `interacting` 이 묶음) → usable 범위를 줄여 표에 표시(`RG_OUTSIDE_GUARD`·`RG_VAR_BLOCKED` 기존 코드). **부호별 비대칭 usable** 을 그대로 표시.
- 공칭 0 대응(A0-1 확정 — 근거 §0):
  1. 공칭 선택을 한 함수로: `_nom(b, typ)` = D → D_nom, W → W_nom, U → 0.0. `bead_graph.py:1092·1144·1642·1776·1902·1923` 의 `D_nom if D else W_nom` 를 모두 이것으로(D·W 값·바이트 불변).
  2. 기본·feasible: `derive_obj_v2`(`:1006-1017`)에 U 가지 — 위 식(W_ref·g±). `range_default/range_feasible/range_basis["U"]` 는 pos_u 블록이 있고 U 가 가능한 비드만(없으면 키 없음 — 옛 summary 바이트 불변).
  3. 패키지 `_one`(`morph.py:219-229`·`:279`): kind U 공칭 0, `ext` = 범위 끝 최대 |ΔU|(범위 없을 때 대체값 = `range_rel`·W_ref — `0.3·nominal` 금지), `ext_eff = ext`, R_w = k·ext(§1.1). D·W 가지 불변.
  4. 범위 점검: 순수 모듈 변경 없음(공칭 상대식). 그래프 쪽 후보 key `_var_key`(`:1533-1538`)에 U 는 `kind: "U"` + `u_segs`(S_U) — W 의 `w_segs` 와 같은 방식. 준비 표(`range_guard_table`)의 seed·단일 세그먼트 후보에 U 는 넣지 않음(기본 꺼짐 — BD_MATRIX `guard_selection` 이 켜진 U 만 점검, unchecked → 점검).
  5. 422: `matrix.normalize_spec`(`:100-112`)에 **type U 만** "lo ≤ 공칭 ≤ hi"(공칭 = 변수 표 nominal 0) 아니면 `DOE_RANGE_INVALID`(문구 "위치 범위는 0 을 포함해야 합니다"). 프런트 `rowProblem`(`doe.ts:1080-1088`) 같은 규칙. D·W 는 지금 그대로(바이트·문구 불변).
  6. 썸네일 자동 색 범위(`matrix.py:237-241`): type U 도 |ΔU| 를 넣는다(U 가 행렬에 있을 때만 값이 바뀜).
  7. SR-D-38 교차(`esl/morph/core.py:259-261`): `type in ("W", "U")`(U 띠가 이웃 비드 경계를 건드림 — D·W 출력 불변).
  8. 표시: 공칭 "0", 범위·feasible mm 그대로(지금도 % 표시 없음).
  9. 민감도(D-0.24.9-PU-9): 기존 지표 그대로(정규화 SRC·Spearman ρ, −1..1, 단위 없음 — `rank.py:327-366`, `Sensitivity.tsx:39`, `report_doe.py:77-100`). U 변수도 같은 표에 행으로 들어갈 뿐 새 단위·새 계산 없음.
- 켜고 끄는 곳(D-0.24.9-PU-10): 선택 `vars`(`backend/esl_platform/api/schemas.py:2506` `Literal["D","W"]`, max 2)는 건드리지 않는다 — U 는 선택 문서로 켜고 끄지 않는다. **U 행 유무 = 스냅샷 `pos_u` + 형상 조건(§1.2)**, **켜기 = 변수 표(spec params)뿐**. 코어는 `b.vars`(`bead_graph.py:992`·`:1091`)와 별도로 U 행을 붙인다. `_possible_vars`(`:479-483`)·`normalize_v2`·선택 sha256 불변.
- 대칭 묶기(D-0.24.9-PU-11): 묶음 변수 `B<대표>_U` 1개 = 구성원 기저의 부호 합 Σ s_m·B_m, s_m = sign(거울(t⊥_대표)·t⊥_m)(t⊥ = 비드 평균 방향 `dir`, 대표 s = +1) → 거울 대칭으로 움직임. 거울 연산(대표·구성원 **쌍마다**, 구성원 셋 이상도 대표와의 쌍별 판정): c = 그 비드 S_U 골격 점들의 길이 가중 도심(판 평면 성분만), 대칭면 법선 m = (c_m − c_대표)/‖·‖, 거울(v) = v − 2(v·m)m. ‖c_m − c_대표‖ < h 이면 판정 불가 → `U_TIE_MIXED`. |거울(t⊥_대표)·t⊥_m| < cos 30° 이거나 구성원 중 U 불가(§1.2 사유)가 있으면 그 묶음은 U 없음 + 대표 비드 `u_reason = U_TIE_MIXED`. D·W 묶음은 그대로(같은 Δ, `bead_graph.py:1088-1090`·`:1184-1198`). 행에 `group_signs{이름: ±1}`(U 묶음만).

### 1.4 D·W·U 동시
- 선형 합(기저는 공칭 형상에서 계산): U 이동 뒤의 D·W 는 이동 전 위치의 기저를 쓴다 — 범위가 0.5·W 이하이고 띠 변형이 작다는 근사. 조합 점검은 range guard combo 가 한다(뒤집힘·넓이 비·바깥 이동 기준 그대로).
- 진단 `basis.json graph_vars[] += pos{dir, w_ref, band_mm, clipped, hold_n, straight_resid_mm}`(U 변수만).

### 1.5 계획 표 — 변수 출처별(v0.24.7 `esl/morph/section.py` `SECTION_PLANS` 에 열 추가)
| 행 | pos | 뜻 |
|---|---|---|
| graph | pkg_u | 패키지 kind U |
| elems | none | 범위 밖(R-PU-2) |
| paicad | native | paicad BEAD_POS_U 그대로(이 계약 무관) |
| none | none | – |
- 빈 칸 = `CONFIG_INVALID`. 호출 쪽은 열 값만 읽는다.

## 2. 하중 공간 고정 `load_follow`

### 2.1 문제
- 같은 메시 모드(계획 `reuse: once`)는 하중이 노드 번호에 붙어 있다. 깊이·폭은 평면 이동이 작아(≤ cotθ·ΔD ≈ 수 mm, 국부) 문제가 드러나지 않았지만, U 는 비드와 양옆 띠 노드를 최대 0.5·W(예 15 mm) 옮긴다 → 그 위의 하중(전 노드 ESL·지그 맞춤 가압 하중)이 비드와 함께 끌려가 "하중은 그대로인데 비드만 옮겼을 때"의 비교가 아니게 된다.
- 하중(관성·이웃 부품 접촉)은 공간에 고정된 장으로 보는 것이 맞다.

### 2.2 규칙
- 계획 표 `transfer_plan.PLANS` 에 열 `load_follow` 추가:
  | 계획 행 | load_follow | 뜻 |
  |---|---|---|
  | case_once·bmesh_once·step_once | `var` | 행렬에 U 변수가 있으면 spatial, 없으면 node(지금) |
  | step_per_design·compare_per_shape | `na` | 이미 대상마다 전달(변수 없음·형상별) |
  - 값 검사 `LOAD_FOLLOW = ("var", "na")`, PLAN_VERSION·hash_view 불변(옛 스냅샷은 U 변수가 없으므로 항상 node).
- 판정 한 곳 `tp.load_follow_effective(plan, has_pos_var: bool) -> "node" | "spatial"`(순수). has_pos_var = 그 스터디 행렬 변수 중 type U 가 하나라도 있음(BD_MATRIX 에서 확정 → `matrix.json load_follow`).
- spatial 일 때(그 스터디의 **모든 안, 기준 d000 포함** — 같은 경로 원칙):
  1. 원본 = 기준 메시 공칭 좌표 X0 위의 노드 하중(전 노드 ESL 은 지금의 once 결과 f0, 지그는 기준 맞춤 하중 F_jig,0 = Σ a·기저 하중, 경계력·내력을 켠 스냅샷도 같은 방식).
     - 위치(A0): f0 = `prep/loads.npz`(`sc.load_loads`, `stages.py:2772`). F_jig,0 은 저장 배열이 없다 — `jg.forces(_jig_basis_of(z), z["a"][k], N₀)`(`stages.py:4468`·`:4474`)가 기준 노드 순서 배열을 만든다. spatial 은 이 배열을 원본으로 쓰고 `F[pos] = Fb`(`:4475-4476`) 대신 전달본을 넣는다.
  2. 안 d 의 하중 = `_plan_loads` 셀 전달(방법 `("cell", s)`, s = 스냅샷 `load_follow.cell_mm` 기본 3.0, srcs = 원본(X0, f) — v0.24.8 의 srcs 일반형) → 대상 = 안 좌표 X_d 의 같은 위상 메시, 배치 global, LT-4 합력·모멘트 보존.
     - srcs 구성(A0): `ltm.src_load(eid, 기준 메시(x0 = X0), f, frame = t.frame)`, dst = `ltm.dst_mesh(안 메시(x0 = X_d), t.frame, 계획 mask, h)` — **양쪽 frame 을 기준 frame 하나로**(셀 칸 = 각 쪽 frame 정규화 좌표라 같은 frame 이어야 칸이 공간에 고정, `load_transfer.py:58-73`, v0.24.8 §0.4).
     - 배치(D-0.24.9-PU-12): `_plan_loads`(`stages.py:2766-2775`)에 키워드 인수 `placement=None` 추가 — None = 지금(`_lt_placement(c, plan)`, 바이트 불변). spatial 경로는 원본이 그 기준 메시 자신이므로 계획 placement(bmesh·step_once 의 auto = A→B rigid/frame, `transfer_plan.py:42`·`:47`)와 무관하게 **항상 `{"kind": "global"}`** 을 넘긴다. v0.24.8 이 같은 함수의 srcs 경로를 쓰므로 §6 겹침에 적음.
  3. d000 도 같은 전달(X_d = X0) → 기준 값(C_ref·E_0·C_mix,0)은 이 경로의 d000 값. 지그 `_jig_design_multi` 는 a·BC·k 를 기준에서 고정하는 것은 그대로, **하중 벡터만** 전달된 것으로 바꾼다.
     - 준비·평가 구분(D-0.24.9-PU-13): **준비 단계**(기준 해 sm_ref, 지그 맞춤 a·BC·k — `prep/sm_ref.npz`·`prep/<src>.{npz,json}`)는 **node 경로 그대로 두고 다시 하지 않는다**(산출물 불변). 맞춤 목표 u_tgt 도 node 경로 기준 해(`stages.py:3954-3960`). spatial 은 **평가 단계만** 바꾼다: 안마다(d000 포함) F = 전달(X0 의 `jg.forces(basis, a)` → X_d) **1회**, 기준 값 C_mix,0·E_0 = spatial d000 평가값. 준비 단계 지그 재현 지표(fit MAC·umax_err 등)는 node 경로 값 그대로 표시.
     - d000 순서(PU-16): BD_EVAL 의 d000 단계에서 (1) 먼저 **node 경로로 한 번** 푼다 → 이 풀이로 `prep/sm_ref.npz`·지그 맞춤(a·BC·k, `prep/<src>.{npz,json}`)을 지금과 같은 내용으로 만들고, 같은 풀이를 `d000_shift_rel` 의 node 쪽 값으로 재사용(추가 풀이 없음). (2) 그 다음 d000 을 다른 안과 같은 spatial 경로로 평가(분해 재사용, 해만 추가).
     - 저장(PU-17): `run/designs/d000/result.json` per_esl = 다른 안과 같은 spatial 평가값(순위는 평소처럼 d000 결과를 읽음). node 경로 값과 spatial 기준 값은 새 파일 `prep/load_follow.json` = `{schema: "esl/doe_load_follow/1", mode, cell_mm, node: {per_esl: {…C…}}, d000_shift_rel, jig: {<src>: {<entry_id>: {C_mix, E}}}, transfer: {dF_max, dM_max, corr_rel_max, small_frac_max}}`. `prep/<src>.json`·`.npz` 의 Cmix_ref·E_ref 는 node 경로 맞춤 값 그대로, spatial 일 때 `_jig_design_multi` 의 기준 C_mix,0·E_0 는 `prep/load_follow.json jig` 에서 읽는다. node 스터디에는 이 파일이 없다(바이트 불변).
     - bmesh_once·step_once 의 ESL 하중이 A→B 로 이미 한 번 전달된 것(`_lt_base_loads`)은 그대로 — 공간 고정 전달은 B(X0) → B(X_d) 의 별개 단계다.
  4. tie 강제 변위 g·스프링 k·3-2-1 = 노드 번호 그대로(tie·fixed 노드는 hold 로 안 움직임 — A0-3 확인. 3-2-1 지지 노드가 띠 안에서 움직여도 면내 강체 위치만 정하므로 에너지 불변).
     - A0-3 결과: (i) case·bmesh_once 의 tie = fixed-scan 의 부분집합(종류 필터) ⊂ hold 대상 → 비드 `hold_fixed = 1` 이면 ψ = 0 으로 안 움직임(`morph.py:56-66`, `stages.py:3780-3785`). (ii) 3-2-1 = 기준 PCA 꼭짓점(판 모서리 — `esl/opt/target.py:97-102`)이라 fixed 와 무관; 띠 안에 들 수 있으나 가정 성립 조건 = 하중 합력·모멘트 ≈ 0(반력 ≈ 0 — LT-4 보존이 원본 합력을 그대로 두므로 node 경로와 같은 크기, `LT_ESL_UNBALANCED` 기준 이내).
     - tie 고정(D-0.24.9-PU-14): 지금 코드로는 (a) 비드 `hold_fixed = 0` 이면 ψ ≡ 1(`morph.py:323`), (b) step_once 는 hold 대상 = fixed_user 뿐(`stages.py:6264-6265`)이고 tie = `fixed_transfer.json`(`:3786-3791`)이라 tie 가 움직일 수 있다. 그래서 **kind U 기저만** hold 강제 + fixed 집합에 지그 tie 노드를 더한다(§1.1 표 "섬·hold" 행). 그래도 tie 노드의 U 기저 변위 > 1e-6·ext 면 그 U 행 없음(`U_HELD`). D·W·DF·W1 hold 규칙 불변.
- node 일 때: 지금 경로 그대로(바이트 동일).
- 스냅샷 키 `doe.load_follow{schema: 1, cell_mm}` — 설정 `bead_doe.load_follow` 사본, **`pos_u` 블록이 있는 새 스냅샷에만**. 안 해시: spatial 일 때만 `load_follow` 를 `_cfg_hash` 에(같은 스터디에 U 변수를 넣고 빼면 모든 안 다시 평가 — 경로가 달라지므로 의도).
- 보조 지표: sm_ref 를 노드 번호로 쓰는 선형 보조 열(lin ritz·taylor — A0-2)은 spatial 스터디에서 null + 정보 `PU_LIN_SKIPPED` 1건. 순위 지표(solve·jig) 는 영향 없음.
  - A0-2 확정: null 로 할 키 = `SM_ROW_KEYS`(`stages.py:3361`) 중 C_lin·C_ritz·rho·imbalance_rel(imbalance 도 F_d − K_d u_t 라 무효 — `:3679-3686`). umax_def·solve C·지그 C_<pe>·umax_<pe> 는 유효. `prep/sm_ref.npz` 는 그대로 쓴다(지그 목표·재현 진단이 읽음 — `:3954`·`:5494`).
  - rank.metric = lin(D-0.24.9-PU-15): `rank.metric` 선택지에 lin 이 있다(`stiffness_metric.py:24`, 기본 jig `esl/doe/__init__.py:95`). `tp.metric_effective(plan, metric, jig_ok=True, spatial=False)` 에 인수 추가 — spatial ∧ metric lin → "solve"(기존 호출은 인수 없음 = 바이트 불변). 정보 `PU_LIN_SKIPPED` 1건 문구에 "순위는 재풀이로 대체". metric jig·solve 는 그대로.

### 2.3 알림 · 진단
- 정보 1건 `LOAD_FOLLOW_SPATIAL{cell_mm, n_pos_vars}`(결과 경고 줄): "위치 변수가 있어 하중을 공간에 고정했습니다({cell_mm} mm 셀) — 기준 포함 모든 안이 같은 경로".
- result.json `load_follow{mode, cell_mm, dF_max, dM_max, corr_rel_max, small_frac_max, d000_shift_rel}` — d000_shift_rel = |C_d000(spatial) − C_d000(node)| / C_d000(node)(엔트리 최악 — node 쪽 = d000 의 node 경로 풀이(§2.2-3 PU-16) 재사용, 추가 풀이 없음). 같은 값이 `prep/load_follow.json` 에도 있음(PU-17).
- 순위 noise: `rk.rank(noise_floor = max(d000_shift_rel, load_follow.noise_floor_min))`(v0.24.8 §14.3 과 같은 장치) — 전달 오차 이내 차이를 행 noise 로 표시.

## 3. 설정 · 스냅샷 · 해시 · 하위 호환
- 설정(같은 이름 4곳: `esl/doe/__init__.py` DEFAULTS·backend pydantic·`config/esl_platform.example.yaml`·`.prod.example.yaml`):
  - `bead_doe.pos_u: {enabled: true, range_rel: 0.25, max_rel: 0.5, gap_rel: 0.5, hold_frac_max: 0.2}`
  - `bead_doe.load_follow: {cell_mm: 3.0, noise_floor_min: 0.01}`(cell_mm 범위 = load_transfer.cell_min_mm..CELL_MAX_MM, noise_floor_min 은 해시 밖)
- 스냅샷: 새 스터디(select 시나리오·그래프)만 `doe.pos_u{schema: 1, …}`·`doe.load_follow`. 복제 = 원 블록 그대로(없던 스터디에 주입하지 않음 — v0.24.7 §6.1 "깊이 동작만 바뀌게"와 같은 원칙). 옛 스터디에서 U 를 쓰려면 새 스터디.
- 하위 호환: `pos_u` 없는 스냅샷 = U 행 없음·load_follow node → prep·basis·params·matrix·design·result·ranking·보고서·view3d·input_sha256 바이트 동일(골든 = v0.24.8 머지 헤드 기록). `pos_u` 있는 스냅샷이라도 U 변수를 하나도 안 켜면 계산 경로 = node(바뀌는 것은 params.json 의 U 행·`u_reason` 뿐).
- 기저 재사용 조건 += `bj.get("u_rules")` 일치(키 있을 때).
- `_sel_cfg_sha` += pos_u 해시 보기(range_rel·max_rel·gap_rel·hold_frac_max — 블록 있을 때만).
- 선택 문서(PU-10): U 는 선택 `vars` 로 켜고 끄지 않으므로 선택 스키마(`SelectGraphBeadIn.vars`)·`_possible_vars`·선택 sha256·`normalize_v2` 출력 불변. U 켜기는 spec params 에만 남는다(행렬 sha 에 반영).

## 4. API · 화면(새 버튼 0)
| 위치 | 키 |
|---|---|
| params[] | U 행 `{name B<n>_U, type "U", nominal 0, unit "mm", feasible[lo,hi], default_range, use_default false, dir, dir_text, w_ref}` |
| beads[](params·derive) | `u_reason{code, text}`(행 없을 때) |
| DoeStudyOut.inputs | `pos_u`(블록 유무), `load_follow` |
| DoeResultOut | `load_follow{…}`(§2.3), 경고 `LOAD_FOLLOW_SPATIAL`·`PU_*` |
| matrix | `load_follow: "node" \| "spatial"` |
- 변수 표: 비드 묶음의 D·W 행 아래 U 행(체크 해제, 이름 옆 `dir_text`, 범위 mm, usable 비대칭 표시). 행 없음 = 비드 이름 툴팁에 `u_reason` 문구(새 줄 없음). A0-4 결과 종류 필터가 있으면 "U" 를 그 필터에 더한다(없으면 추가하지 않음).
  - A0-4 확정(실제 구조): 종류 필터 **없음** → 추가하지 않음. 접기는 카드 전체("④ 변수" `fold4`)뿐 → 그대로. 그래프 비드는 select 가지(`DoeParamTable.tsx:213-270`)로 그려지므로 그 가지에서:
    1. 라벨: `:244`(aria "B<n> W")·`:252`("폭 W")의 `D 아니면 W` 를 종류별로 — U = "위치 U" + `dir_text`(`TYPE_NAME.U` = "위치 U", `doe.ts:399` 재사용). 계획 칩(`DoeStudy.tsx:1406`)도 U = "U 0.0" 대신 "U"(공칭 0 표시 생략). 평면도 활성 변수(`:1399` planVar)는 D·W 만 — U 행을 골라도 평면 겹침 없음(지금 동작 유지, 3D 미리보기로 봄).
    2. U 행 순서: 비드의 D·W 행 뒤(`ps` 는 서버 params 순서 = 이름 정렬이라 `B<n>_D`·`B<n>_U`·`B<n>_W` 가 됨 → 프런트에서 비드 안 정렬 D·W·U 로 고정).
    3. 툴팁: 비드 머리 행 `<span>{b.name}</span>`(`:223`)에 `title = u_reason.text`(u_reason 있을 때만 — 옛 스터디 DOM 불변).
    4. 비대칭 usable: 지금 guard 꼬리표(`ShapeTags`·`guardTag`, `:163-181`)가 usable 을 툴팁으로 보임 → U 도 같은 꼬리표(새 요소 없음).
- 3D 미리보기(basis.bin): 형식 불변 — U 를 켜고 값을 움직이면 비드가 옆으로 이동, 띠 압축이 보임.
- 스터디 결과: 경고 줄 1개(§2.3), 순위 정의 문구 같은 줄 끝 "· 하중 공간 고정({cell_mm} mm)". 민감도 표에 U 변수 행(기존 SRC·ρ 그대로 — §1.3-9).
- 2560·1920: 새 스터디 변수 표는 U 를 쓸 수 있는 비드 수 × 행 높이만큼 늘어남(표 안 스크롤 — 페이지 scrollHeight 증가 0 이 되도록 표 max-height 유지).
  - A0-4: 지금 이 표에는 max-height 가 **없다**(`.table-wrap` 가로 스크롤만, `DoeParamTable.tsx:197`, `styles.css:736-738`). 기존 유틸 `.table-wrap.scroll`(`styles.css:739-742`, max-height `--tbl-max` = clamp(10rem, 30vh, 24rem) `:29`, 머리 sticky `:757`)을 **params 에 type U 행이 있을 때만** 붙인다 → U 행이 없는 스터디(옛 스터디 포함)는 DOM·높이 불변, U 행이 있는 스터디는 표 안 스크롤. 시험 §5-18 의 "scrollHeight ±0" 기준 = 같은 스터디에서 U 행 유무(같은 D·W 행 수).

## 5. 시험(V-0249-PU-n)
1. 패키지 직선 채널(D 10·W_open 40·45°, 판 600×300, 정렬 quad) U ±10: 입구·벽·가장자리·깊이면 평면 변위 = ΔU·t⊥ ±1e-3(φ = ψ = 1 구역), 법선 성분 ≤ 1e-12, 폭·깊이·사면 각 변화 ≤ 1e-9·0.01°, 달성 ±1e-3, 허용 구역 밖 ≤ 1e-9, 뒤집힘 0, 띠 양쪽 R_w = 80 mm.
2. 곡선(원호 R 150) 채널 U ±5: 바깥/안쪽 평행 곡선(반지름 ±ΔU ±0.05h), 폭 변화 ≤ 0.02h, `dir_text` = 바깥쪽/안쪽.
3. 끝단: 닫힌 끝 비드 U +5 — 끝단 노드 변위 방향 = 끝 선분 t⊥(방사 성분 ≤ 1e-6), 비드 길이 변화 ≤ 1e-6.
4. 접합: T 접합 가지 U — J 0, 램프 L 안에서 0→ΔU, 다른 가지 노드 |u| ≤ 1e-9, `PU_PARTIAL` 없음.
5. 자식·섬: 깊이면 위 배타 플래토 = 비드와 강체 이동(자식 안 상대 변형 ≤ 1e-9), fixed 가 있는 보스 = 제자리 + 주변 hold, `U_HELD` 임계.
6. 불가 사유: 네트워크·면형·한쪽 입구·입구 없음 합성 1개씩 → 행 없음 + 코드, 순서 고정. 옛 스냅샷 = U_OFF·표시 없음.
7. 범위: feasible 부호별(이웃 비드 간격 20 mm → 그 쪽 hi = 10), 기본 범위 클립, 공칭 0 이 범위 밖이면 422, type U 는 "> 0" 검사 제외, range guard 가 부호별 usable 을 줄임(이웃 쪽만).
8. D·W·U 동시: 세 기저 합 = 동시 모핑 ±1e-12, 조합 점검이 같은 비드 묶음, 달성 깊이·폭 ±1e-3(U 가 깊이·폭을 바꾸지 않음).
9. 판 불변: graph.json·D·W·DF·W1 기저 바이트 = v0.24.8, `python -m beadgraph version` = {version 1.3.0, output_version 1.1.0, …, u_rules 1}.
10. 계획 표: `SECTION_PLANS.pos`·`PLANS.load_follow` 모든 행 채움(빈 칸 CONFIG_INVALID), `load_follow_effective` 진리표, 호출 쪽 시나리오 이름 분기 0(정적).
11. **하중이 따라가지 않음**: 평판 + 채널, 비드 깊이면 위 한 점 근처 집중 하중. U +10 안에서 (a) node 경로 = 하중 도심이 10 mm 이동(지금 동작 확인), (b) spatial 경로 = 하중 도심 이동 ≤ cell_mm/2, ΣF·ΣM 오차 ≤ 1e-9.
12. 기준 같은 경로: spatial 스터디 d000 score = 1 정확, C_ref = d000(spatial), `d000_shift_rel` 기록, noise 표식.
13. 경로 선택: U 변수 0개 = node 경로·안·순위·결과·prep·3D·done input_sha256 바이트 = `pos_u` 없는 스냅샷과 같음 — 단 **선택 단위 파일**(select/<sha12>/basis.npz·basis.bin·basis.json·derived.npz — U 가능 비드의 U 기저가 들어감, basis.json cfg_sha256 은 `_sel_cfg_sha += pos_u`)·params.json·derived.json(U 행·`u_reason`)·`matrix.json load_follow: "node"` 키는 달라짐(통합 보정 PU-C1-1·PU-C1-8 — 비교는 이 키·행을 뺀 내용), U 변수 ≥ 1 = spatial·`matrix.json load_follow`·정보 `LOAD_FOLLOW_SPATIAL`.
14. 지그: spatial 에서 jd·js 의 a·BC·k = 기준 값(노드 번호), 하중 벡터만 전달본, 단조성(같은 위치에서 깊이↑ → s 변화 방향이 node 경로와 같음), U 로 비드를 하중 밖/안으로 옮기면 Π 변화 부호가 해석 예상과 같음(합성: 비드가 하중선 아래로 오면 강성↑).
15. 옛 바이트: v0.24.8 머지 헤드 골든(그래프 select 스터디·①②③④ regress) — `pos_u` 없는 스냅샷 전 산출물·input_sha256 동일.
16. 해시: spatial 일 때만 `_cfg_hash` 에 load_follow, 해시 밖 키 변경 = 불변, 복제 = 원 블록.
17. 설정 거울: DEFAULTS = pydantic = yaml 2, 범위 검사.
18. API·화면: U 행 필드·`u_reason`, 변수 표 U 행(체크 해제·dir_text·mm), 툴팁 사유, 경고 줄·문구 꼬리, 2560·1920 페이지 scrollHeight ±0, mock.
19. 비용: 합성 120×80(9,801 노드)·엔트리 4 — U 기저 시간 ≤ W 기저 × 1.2, spatial 안마다 추가 시간·피크 메모리 기록(목표 ≤ 기존 안 평가 시간 × 1.5).
20. e2e: 새 그래프 스터디(U 1개 켬) → BD_MATRIX → BD_EVAL → BD_POST → API → 프런트 픽스처, 재낙하 zip(노드 좌표만 — U 포함 안에서 정상).
21. (A0) 닫힌 골격·1점 골격: 고리 채널 = U 행 없음 + `U_CLOSED`(순서: U_AREA 뒤·U_ONE_SIDE 앞), 1점 골격 = `U_AREA`. 열린 골격 끝단 방향 = 끝 선분 t⊥(시험 3).
22. (A0) 공칭 0 경로: `_nom(b, "U") = 0` 이 기저·후보·range guard·조합 적용 6곳 모두에 쓰임(D·W 결과 바이트 = v0.24.8), 패키지 kind U 범위 없음 호출의 ext = `range_rel`·W_ref(0 아님), U 의 `ext_eff = ext`·R_w = k·ext, `BG_RAMP_SHORT` 는 U 에 ½ 없음.
23. (A0) 422: type U `lo > 0` 또는 `hi < 0` = `DOE_RANGE_INVALID`(코어·프런트 `rowProblem` 같은 판정), lo < 0 < hi 비대칭 = 통과, D·W 의 기존 문구·코드 불변. 썸네일 `disp_range_mm` auto 에 U |ΔU| 반영(U 없는 행렬 = 바이트 불변).
24. (A0) 배타 자식·섬 Dirichlet: 깊이면 위 배타 플래토 + 비드 소유 섬 — U 기저에서 자식·섬 노드 면내 변위 = 그 중심 t⊥ ±1e-9(섬 블록 둘레 평균과 같음), 공유 자식 벽 = 0, D·W 기저 바이트 불변(`dir_zero` 분리가 D·W 에 영향 없음).
25. (A0) tie·hold(PU-14): 띠 안 지그 tie 노드의 U 기저 변위 = 0 — (a) case_once·hold_fixed 1, (b) **hold_fixed 0 비드**, (c) **step_once**(fixed_transfer ⊄ fixed_user 합성). 같은 비드 D·W 기저는 hold_fixed 0 에서 지금처럼 움직임(바이트 = v0.24.8). tie 변위 > 1e-6·ext 합성 = `U_HELD`. 3-2-1 노드가 띠 안일 때 합력 0 하중에서 solve C 변화 ≤ 1e-9(상대).
26. (A0) 배치·frame(PU-12): `_plan_loads(placement=None)` = 기존 호출 바이트 불변, bmesh_once·step_once(placement auto 가 rigid/frame 인 합성)에서 spatial 전달이 global 을 넘김(하중 도심 이동 ≤ cell_mm/2 — 시험 11 과 같은 기준), src·dst frame = 기준 frame(안 좌표로 frame 을 다시 계산하지 않음).
27. (A0) 지표: spatial 에서 C_lin·C_ritz·rho·imbalance_rel = null, umax_def·solve·C_<pe> 값 있음. 스냅샷 `rank.metric = lin` 인 spatial 스터디 = solve 순위 + `PU_LIN_SKIPPED` 1건("순위는 재풀이로 대체"), node 스터디·metric jig·solve 는 `metric_effective` 결과 불변(PU-15).
28. (A0) 지그 기준(PU-13): spatial 스터디의 `prep/sm_ref.npz`·`prep/<src>.{npz,json}` = 같은 입력 node 스터디와 바이트 동일(fit MAC 등 표시도 같음), 안마다(d000 포함) 지그 하중 전달 1회(X0 → X_d), C_mix,0·E_0 = spatial d000 평가값, d000 C_<pe> = E_0 정확(score 1). bmesh·step_once 의 A→B ESL 전달 결과(prep/loads.npz) 불변. `prep/load_follow.json` 스키마·키(PU-17), node 스터디에 파일 없음, d000 풀이 수 = node 1 + spatial 1(분해 1회 공유), `d000_shift_rel` 의 node 값 = 그 node 풀이.
29. (A0) 화면: 그래프 비드 U 행 라벨 "위치 U"(`W` 로 안 나옴)·aria, 계획 칩 U 표기, 비드 안 순서 D·W·U, `u_reason` 툴팁(없으면 title 속성 없음), U 행 있을 때만 `.table-wrap.scroll`(U 없는 스터디 DOM 스냅숏 불변), SR-D-38 교차 점검에 U 포함.
30. (A0) 대칭 묶기 U(PU-11): 거울 쌍(진행 방향 반대·같음 합성 2개) → `B<대표>_U` 1개, 구성원 부호 s_m 로 거울 대칭 이동(대칭면 반사 오차 ≤ 1e-9), |내적| < cos 30° 합성·구성원 1개 U 불가·도심 거리 < h 합성 = 묶음 U 없음 + `U_TIE_MIXED`, 구성원 3개 묶음 = 대표와 쌍별 판정, D·W 묶음 바이트 불변. `vars` 생략·["D"]·["D","W"] 모두 U 행 유무 같음, 선택 sha256 불변(PU-10).

## 6. 작업 분해(파일 소유 겹침 없음)
| 묶음 | 모델 | 파일 |
|---|---|---|
| A0 감사 | opus(읽기만) | **완료**(2026-11-25) — §0 근거, §1.1·§1.2·§1.3·§2.2·§3·§4 보정, 시험 21~30 추가. 불일치 9건 = 메인 결정 D-0.24.9-PU-7~15, 후속 의문 3건 = PU-11 보정·PU-16·17 로 반영 |
| C1 코어 + 패키지 | opus | `packages/beadgraph/**`(`morph.py` kind U, `checks.py` 달성·허용 구역, `conformance.py`·`testing/` 합성(곡선·끝단·T), `__init__.py` 1.3.0·`U_RULES`, tests), 루트 `pyproject.toml`, `esl/morph/section.py`(pos 열·`u_reason`·feasible), `esl/doe/bead_graph.py`(U 행·기저), `esl/doe/range_guard.py`(U 후보·부호별), `esl/doe/matrix.py`(공칭 0·U 422·썸네일 색 범위), `esl/morph/core.py`(SR-D-38 교차에 U — A0), `esl/doe/transfer_plan.py`(load_follow), `esl/doe/stages.py`(spatial 경로·지그 하중·해시·진단), `esl/doe/__init__.py`, `resources/doe_messages.json`, `tests/doe/test_pos_u*.py`·`test_load_follow*.py`, 골든 |
| B1 백엔드 | sonnet | `backend/esl_platform/core/config.py`, yaml 2, `api/schemas.py`, `api/services/doe.py`·`doe_select.py`, openapi, `deploy/requirements.lock`(beadgraph 1.3.0), `backend/tests/test_doe_v0249_*.py` |
| F1 프런트 | sonnet | `frontend/src/api/types.ts`·`doe.ts`, `components/DoeParamTable.tsx`, `pages/doe/DoeStudy.tsx`(경고 줄·문구), `components/DoeRanking.tsx`(문구 꼬리), `mock/*.ts`, `__tests__/pos_u*.test.tsx`, Playwright |
- 순서: A0 → C1 이 패키지 kind U 항목 키·section 시그니처·코드 표 첫 커밋 → B1·F1 병렬 → 통합 → 독립 Verifier(쓰기 안전·경로 처리·옛 바이트·물리 시험 11·14 독립 재현).
- v0.24.7·v0.24.8 과 겹치는 파일: `morph.py`·`section.py`·`bead_graph.py`·`stages.py`·`transfer_plan.py`·`doe_messages.json`·schemas·types — 두 버전 머지 뒤 재기반, openapi 재생성.
- 겹치는 함수(PU-12): `stages._plan_loads` — v0.24.8 이 srcs 경로(지그 맞춤 하중의 형상 셀 전달)를 쓰고 이 계약이 키워드 `placement=None` 을 더한다. 재기반 때 두 인수가 함께 있는 시그니처 `(c, plan, did, dst, variant=None, cache=None, srcs=None, placement=None)` 로 맞추고 v0.24.8 호출은 placement 를 넘기지 않는다. `tp.metric_effective` 도 v0.24.8 `kind=` 와 이 계약 `spatial=` 이 함께 붙음(둘 다 기본값 = 지금).

## 7. 미결(결과를 바꾸는 것만 — 기본 가정으로 진행)
- **Q-PU-1 하중 공간 고정 범위** — 기본: U 변수가 있는 스터디만. 대안: 새 스터디 전부(깊이·폭만 있는 스터디도 — 기존 스터디와 수치가 달라짐).
- **Q-PU-2 한쪽 입구 비드의 위치** — 기본: U 없음(한쪽 W 를 쓰라고 안내). 대안: 열린 쪽만 이동하는 U(= 한쪽 W 와 같은 형상 변화라 중복).
- **Q-PU-3 U 기본 체크** — 기본: 꺼짐(비드마다 사용자가 켬). 대안: 쓸 수 있는 비드 모두 켬(변수 수·안 수 증가).

## 8. 후속(R-PU-n)
- R-PU-1 경로 방향 V(끝단 늘이기·줄이기).
- R-PU-2 선택(요소) 방식 U. R-PU-3 ④·옛 ③ 에서의 위치(형상 자체가 입력이라 해당 없음 — 문서화만).
- R-PU-4 면형 바닥(골격 없음)의 위치(방향을 사용자가 지정).
- R-PU-5 비드 방향(회전) 변수 — B8 을 하중 경로와 나란히 돌리는 시험용.
- R-PU-7 닫힌 고리 비드의 강체 이동(고리 전체를 한 방향으로 평행 이동 — U_CLOSED 해제, PU-7).
- R-PU-6 띠 배수 `blend.k` 를 U 전용으로 줄일지(8 → 4~5: 이웃이 가까운 곳의 usable 범위 확대 vs 요소 변형률 증가) — 현장 usable 범위 통계(F-PU-2)를 본 뒤.

## 9. 현장 확인(F-PU-n — `docs/manual/field_check_v0249.md` 는 통합 때)
- F-PU-1 #88 모델로 새 그래프 스터디: 비드별 U 가능 여부·사유(`u_reason`), W_ref, feasible·usable 부호별 범위.
- F-PU-2 usable 이 0.25·W 에 못 미치는 비드 수와 원인(이웃 간격·체결부) — R-PU-6 판단 자료.
- F-PU-3 B8_U 만 켠 스터디: 위치 민감도(SRC·ρ), `LOAD_FOLLOW_SPATIAL`·`d000_shift_rel`, 3D 에서 비드 이동·띠 변형 눈 확인.
- F-PU-4 좋은 안·나쁜 안 재낙하로 소성 변형률 순서 대조(v0.24.5 재낙하 묶음).

## 10. 지그 경계조건 표식(BM — 2026-11-26 사용자 요청, 이 버전에 함께)

### 사용자 원문 (변경 금지)
- "지그 esl 스프링에서 경계조건 컨투어 표시할때 1,2,3방향 다 잡히는걸로보여."
- "스프링 경계조건 표시할때 오해가 없게 컨투어 표시도 스프링 추가를 표시해줘야하지 않을까?? 아님 기호를 다르게 준다던지"
- 확인된 실제 모델(코드 `esl/mech/jig_bc.build_bc`): 스프링 방식 tie 노드 = 면내 1·2 자유, 법선 3 = 스프링(강성 k)으로 가상 받침점에 연결, 받침점 법선 = 낙하 변위 g 지정. 면내 강체 운동은 지지점 n₁(면내 2)·n₂(면내 1)만 고정. 지그 고정 = tie 법선 0 지정, 지그 변위 = tie 법선 g 지정.

### 10.1 문제(감사 — 구현 전 파일:행 확인)
- 3D 지지 표식이 dof 문자열 하나뿐: tie = `MARK_TIE = "123"`(세 방식 공통·실제 구속 방향 무관), 면내 지지 = `MARK_AUX = "ij"`(`esl/mech/jig_bc.py:47`, `support_marks` `:670-686`, 백엔드 Case `api/services/view3d._jig_supports`·`JIG_TIE_DOF`·`JIG_AUX_DOF`). 화면은 "123" 을 세 방향 고정으로 그려 스프링·강제 변위가 고정처럼 보인다.

### 10.2 표식 자료(코어·백엔드 공통 1개 함수 — 순수)
- `support_marks` 반환을 `[(node, kind, dirs, val)]` 로 일반화(옛 2튜플 호출부는 어댑터로 바이트 불변):
  | kind | 대상 | dirs | val |
  |---|---|---|---|
  | `tie_fixed` | 지그 고정 tie | 구속 방향(법선 1개, 꺾임 2개) | 0 |
  | `tie_disp` | 지그 변위 tie | 같음 | g(방향별, mm) |
  | `tie_spring` | 지그 스프링 tie | 스프링 방향 | {k, g} |
  | `aux_inplane` | 3-2-1 면내 지지 n₁·n₂ | 면내 방향(2 또는 1) | 지정값 |
  | `support321` | 지그 아닌 출처(전 노드 ESL 등)의 3-2-1 지지 | 기존 dof | – |
- 사이드카·3D 파일의 지지 표식 필드에 `kind`·`dirs`·`val` 추가(기존 `dof` 문자열은 그대로 남김 — 옛 뷰어·옛 파일 호환). 값은 BC 배열(`bc_*`·`sp_*`)에서 직접 만든다(새 계산 없음). 표식 수 상한 `view3d.jig_support_max` 그대로(샘플링 규칙 불변).

### 10.3 화면 기호(공용 뷰어 `frontend/src/view3d/` — Case ③ 3D·스터디 3D 모두, [경계조건] 층)
| kind | 기호 | 색 |
|---|---|---|
| `tie_fixed` | 법선 방향 짧은 막대 + 바닥 빗금(고정) | 회색 |
| `tie_disp` | 법선 방향 화살표(길이 = g × 표시 배율, 방향 = g 부호) + 끝 막대 | 청록 |
| `tie_spring` | 노드에서 법선 방향 지그재그 스프링 + 끝에 받침 막대(받침 위치 = g × 표시 배율) | 주황 |
| `aux_inplane` | 판 면내 방향 짧은 양방향 화살표(n₁ 2개·n₂ 1개) + 작은 삼각 받침 | 보라 |
| `support321` | 기존 표식 그대로 | 기존 |
- 기호 크기 = 모델 대각 길이 비례(기존 표식과 같은 규칙), 표시 배율은 변형 배율과 연동.
- 범례: [경계조건] 칩 툴팁(새 줄·새 버튼 없음)에 이 표의 기호·한 줄 뜻 — 예 "주황 스프링 = tie 법선만 스프링(면내 자유) · 받침 = 낙하 변위 g".
- 탐침(v0.24.6)으로 표식을 누르면: 노드 번호·kind 이름·방향·val(k·g 또는 지정값).
- 옛 파일(kind 없음): dof 문자열로 그리던 지금 방식 그대로 + 툴팁 "이전 형식 — 다시 만들기를 누르면 방식별 기호로 표시".
- 화면 높이 ±0(2560·1920).

### 10.4 시험(V-0249-BM-n)
1. `support_marks` 일반형: 세 방식 × tie_dofs(normal·translation) × 꺾임 노드 → kind·dirs·val 이 BC 배열과 일치, 옛 2튜플 어댑터 결과 = v0.24.8 바이트.
2. 사이드카·Case 3D 파일: 새 필드 실재, 기존 `dof` 필드 값 불변, 표식 수·샘플 순서 불변.
3. 백엔드 Case 3D 표식 = 코어 함수 결과(같은 함수 호출 또는 같은 값 단언).
4. 프런트: kind 별 기호 렌더(목 픽스처 4종), 범례 툴팁 문구, 탐침 내용, 옛 파일 대체 표시, Playwright 2560·1920 높이 ±0·스크린샷.
5. 문구는 `resources/doe_messages.json`(또는 기존 뷰어 문구 표 한 곳) — 하드코딩 금지.

### 10.5 작업 분해 추가
- C1: `esl/mech/jig_bc.py`(support_marks 일반형), stages 사이드카 쓰기. B1: `api/services/view3d.py`(Case 3D 표식 — 코어 함수 사용), schemas. F1: `frontend/src/view3d/`(기호·범례·탐침), mock.

### 10.6 통합 보정(INT-n — v0.24.9 통합 2026-11-26, C1·B1·F1 병합 때 세 층 형식이 달라 맞춤)
- **INT-1 표식 형식 한 개(코어 = 원천)**: 행 = `{node_id, dof, kind, dirs, val}` — 코어 `esl.mech.jig_bc.support_rows(bc 배열, x0, smax, node_id, src)`
  (= `support_marks_full` + `mark_rows`, kind 판정 = 출처 키 src 의 METHODS 행 `method_row_of(src)`, 방향·값 배열 없는 옛 npz = 옛 `{node_id, dof}`).
  `dirs` = 행 방향 단위 벡터 `[[x, y, z], …]`(소수 6자리, 법선 1·꺾임 2·translation 3·면내 1~2), `val` = tie_fixed `0`(수 하나) · tie_disp
  `[g…]`(mm, dirs 순서) · tie_spring `{"k": [N/mm…], "g": [mm…]}`(스프링 행마다 — **목록**) · aux_inplane `[지정값…]`(mm). `dof` 문자열은 옛 값 그대로.
  백엔드 Case 3D(`services/view3d._jig_supports`)는 어댑터 `core_adapter.jig_support_rows` 로 이 함수만 부르고(자체 계산·manifest 덧쓰기 없음 —
  B1 `jig_marks_general`·`_enrich_manifest_supports` 제거, `build_view` 가 kind·dirs·val 을 씀), 스터디 사이드카는 같은 `support_marks_full`·`mark_rows`.
  프런트는 이 형식만 읽음(`dirVectors` 축 번호 해석 삭제, 스프링 `k` 도 방향별 목록 — F1 의 `k` 수 하나 가정 수정). B1 은 값만으로 kind 를 정해
  강제 변위 g 가 모두 0 이면 tie_fixed 로 보였음 → 출처 키로 판정.
- **INT-2 백엔드 = 코어 호출**: derive_v2 `tie_node_ids` = 코어 `stages.pos_u_tie_ids_at(준비 스냅샷 doe, 스터디 폴더, mesh)`(워커 `_pos_u_tie_ids` 와 같은
  함수 — 읽기 전용 Ctx, opt_core `doe_pos_u_tie_ids`), 미리보기 `load_follow` = `tp.load_follow_effective(계획 행, U 변수 ≥ 1)`, type U 범위 422 =
  코어 `matrix.normalize_spec` 한 곳(B1 중복 검사 제거).
- **INT-3 옛 파일 안내**: "이전 형식 — 다시 만들기…" 는 kind 없는 행이 있고 (Case 출처 표 group = jig 보기 ∨ kind 없는 면내 `dof "ij"` 행)일 때만 —
  전 노드 ESL 등 지그 아닌 출처의 3-2-1(kind 없음, 숫자 dof)에는 붙이지 않음. `support321` kind 는 정의(`support321_rows`)만 두고 지금 내보내지 않음
  (지그 아닌 출처 manifest 바이트 불변 — kind 없음 = 기존 기호 그대로, 표의 support321 행과 같은 그림).
- **INT-4 §5-13**: 위 13 문구(PU-C1-1·PU-C1-8).
- 시험: `tests/mech/test_jig_marks_v0249.py::test_support_rows_is_the_one_format`(세 방식 — 스프링 tie = 스프링 행 방향만·구속 행 없음, 받침점 면내 1·2,
  "123" 세 방향 고정으로 돌아가지 않음), `backend/tests/test_doe_v0249_b1_view3d.py`(BC 배열 대비·응답 = 코어 결과·백엔드 자체 계산 없음),
  `tests/doe/test_pos_u_int.py`, `frontend/src/__tests__/jig_marks.test.ts`(통합 형식·스프링 k 목록·INT-3).

## 11. C1 구현 보정 기록(PU-C1-1~10 — work/findings.md 에서 옮김, 통합 2026-11-26)
- PU-C1-1 (§3·§5-13) U 기저는 선택 단위(select/<sha12>/basis.npz·basis.bin·basis.json·derived.npz)에 U 가능한 비드마다 들어간다(프런트 3D
  미리보기 basis.bin 이 U 를 보여야 하므로 — §4). 그래서 pos_u 블록이 있는 스냅샷은 U 변수 0개여도 이 선택 파일들과 params.json·derived.json
  이 달라진다(basis.json cfg_sha256 은 §3 `_sel_cfg_sha += pos_u` 로도 달라짐). 안·순위·결과·prep·3D·done input_sha256 은 골든과 같음(시험
  test_pos_u_golden — 선택 파일은 pos_u 키·U 행을 뺀 내용이 같은 세계와 같음). 계약 §5-13 문구를 "선택 단위 파일 + params.json" 으로 보정 필요.
- PU-C1-2 (§1.1·§1.2) graph.json segments 에 `closed` 필드가 없다 → U_CLOSED 판정 = 패키지 `morph.u_closed`(접합 없음 ∧ 골격 끝-시작 ≤ 2h).
- PU-C1-3 (§1.3) params U 행 dir{xi, eta} 는 그래프 판 평면 frame(e1·e2) 성분 — params_rows_v2 에는 ESL frame 이 없음. dir_text 의 곡선 판정 =
  골격 누적 회전 ≥ 30°(section.U_CURVE_DEG, 계약에 기준 없음).
- PU-C1-4 (§1.1) "W 규칙 그대로" 로는 H6 기본 범위 끝에서 뒤집힘(최대 86)·오목·가드 cascade(가드 노드 60 %·left 334)가 났다. U 는 W 의 2배
  이동(전 단면)이라 다음 장치로 바꿈(U_RULES 1 에 고정, D·W·DF·W1 바이트 불변):
  (a) 방향장 = 비드 골격 꼭짓점 왼쪽 법선을 가우스 평활(ρ_s = max(3h, 4·ext), 세그먼트 넘어) → 노드 가우스 평활(ρ = max(3h, ext)),
  (b) 여러 세그먼트 비드는 골격 진행 방향을 사슬로 통일(u_orient — H5 링 한 변이 반대 방향 세그먼트로 저장돼 서로 마주 움직였음),
  (c) 띠 = 가우스 혼합(최근접 기준 상대 거리) + 다른 형상 근처는 간격 비례 d_o/(d_o+d_e) 로 자름, 장애물 = 다른 구역·판 외곽·fixed·tie·
      묶인 섬, (d) 이웃 간격 κ = 이동 방향 ±45° 안 장애물까지 거리·부호별 끝(lo/hi)·램프 φ 반영, 침식 후 평활(raw 넘지 않음),
  (e) 품질 가드 = DF 기준(넓이 비·뒤집힘·Jacobian·오목·range guard 품질) 그대로, 줄임만 부드러운 bump(c ×= 1−0.2·exp(−(d/ρ)²), 지지 2ρ),
  (f) 자식·소유 섬 = 방향장 따라 이동(직선 = 강체), 걸친 섬 = BG-D-27 섬 규칙, (g) 조화 확장에서 J 는 Dirichlet 0 아님(φ 가 0 으로).
- PU-C1-5 (§1.3-4) 선택 기저가 선택 단위로 캐시되므로 BD_MATRIX guard_selection 은 "켜진 U" 가 아니라 U 행 전부를 점검(이후 행렬 재사용).
- PU-C1-6 (§1.2 U_HELD) tie 변위는 ψ = 0(ring 안)으로 구조적으로 0 — basis 때 tie_max > 1e-6 이면 BG_ACHIEVED_MISMATCH(행 제거 대신 오류).
  hold 비율 판정은 derive 에서 기하로(입구 노드 중 fixed∪tie 로부터 ring+blend 안 비율 > hold_frac_max).
- PU-C1-7 (§2.2 PU-16) spatial d000 = node 경로(_lt_eval 진단 포함) 1회 + spatial 1회 — 분해 공유 안 함(풀이 수 node 1 + spatial 1 은 같음).
- PU-C1-8 (§4·§5-13) matrix.json load_follow 는 pos_u 블록 있는 스냅샷이면 "node" 도 씀(§4 표). §5-13 "산출물 바이트 동일" 과 충돌.
- PU-C1-9 (§4) derive_v2 beads[].u_reason = {code, text}(U_OFF·pos_u 없음 = 키 없음), params.json beads[].u_reason = {code}.
- PU-C1-10 (§3) 하중 전달 스냅샷(doe.load_transfer) 없는 스터디의 spatial 셀 전달은 설정 load_transfer(work·cell_min_mm)로(_lt_method 대체).
- 통합 상태: PU-C1-1·PU-C1-8 = §5-13 문구 반영(INT-4). 나머지는 구현 기록(계약 규칙과 충돌 없음 — 근거·측정은 work/v0249_u_table.md).
