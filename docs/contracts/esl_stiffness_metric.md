# 계약: 강성 지표 1차 섭동 — 재풀이 없는 순위 지표 · 강체 제거 표시 · 불평형 진단 (STIFFNESS_METRIC, v0.20.0)

- 상태: **초안(Plan)** — 2026-11-13 17:26 사용자 결정(아래)은 확정, §11 항목은 권고안으로 진행(답에 따라 기본값만 바뀜, 구조 불변).
- 버전: **v0.20.0**(release/v0.20.0, `esl_load_transfer.md` 와 같은 릴리스). migration **불필요**(새 값은 `bead_does.doe`·`result` JSONB, 작업 폴더 파일).
- 관계: `esl_bead_doe.md` **BD-D-6(순위 지표)의 '지표'만 새 스냅샷에 한해 교체**(구조 = 최악 ESL 비, 오름차순, 동률 규칙 그대로). 하중 전달·전달 계획 표·진단 스키마는 `esl_load_transfer.md` §13 을 그대로 쓰고 열을 더한다(§4). 충돌 시 순위·표시 지표는 이 문서 우선.
- ID: 결정 `D-0.20.0-SM-n`, 시험 `V-SM-n`, 리스크 `R-SM-n`.
- 근거: 이슈 #63 마지막 진단 코멘트(2026-11-13, ① 20안) — ESL F = K₀·u_drop(Σ|F| 0.7~2.8e8 N, 노드 최대 45 kN, t 0.8 mm)을 강성이 바뀐 모핑 메시에 고정 적용 → 불평형 r = F − K₁u₀ 가 Σ|F| 의 5~27 % → 3-2-1 지지 판의 무른 전역 모드를 ≈ 1/λ_soft 로 증폭 → umax ×50~270, C ×1.0~1.9 오염. 모핑량에 비례(d009 α 0.1 → umax ×14.5)·문턱 없음. 매핑·ID·반력(≤ 3.4e-13)·뒤집힘 버그 아님, 법선 회전 가설 기각, 강체 성분 제거 후에도 umax 2,021 mm(d009 E11).

### 사용자 결정 (2026-11-13 17:26, 변경 금지)
1. #63 ① 진단 대책을 v0.20.0 에 포함한다.
2. **안 A** — 재풀이 없는 1차 섭동 지표 dC = −uᵀdK u 를 새 스터디 기본 순위 지표로(설정 `rank.metric: lin | solve`, 옛 스냅샷 = solve 바이트 동일). 재풀이 C 는 보조 열로 계속 표시, 불평형 진단 |F − K_t u_t| / Σ|F| 추가.
3. **안 B** — umax·εmax 는 순위·대표 표시에서 빼고, 표시할 때는 최소제곱 강체 6자유도 성분을 뺀 값(3D 색도 같은 기준).
4. 실제 낙하 재검증은 상위 k 안 확인용 안내만.
5. 코드 구조 원칙 유지: 모드 무관 독립 모듈, 모드 차이는 계획 표, 진단 스키마 1개.

## 0. 현황 (ed2c719, 근거 파일:행)

| 항목 | 위치 | 현재 |
|---|---|---|
| 안 해석 | `esl/doe/evaluate.py:36` `evaluate` | 안마다 `ShellModel(...).factorize(spc)` → ESL 마다 `solve` → C = Σ F·u[:, :3], umax = max‖u[:, :3]‖, εmax = max `eps_eq_max_layer`, 반력비 |
| 순위 | `esl/doe/rank.py:83` `rank`·`_agg`:29 | C_ref = max_i C_{d000,i}, score = max_i C_{d,i} / C_ref, ESL별 비·pareto 도 C |
| 쉘 요소 | `esl/mech/shell.py` | 노드당 6 dof(전역계 병진 + 회전벡터), 강체 6모드 정확히 무에너지(투영 + 강체 링크), 드릴링 스프링 k = drill_factor·E·t·A, 하중은 병진만(`:842`), `K()`(조립만, 분해 없음)·`condensed_forces`(ESL 생성 = 회전 자유 응축) |
| ESL 원본 | `esl/library/entry.py:33` `RAW_KEYS` | `f`, `u_rel`, `x0`·`conn`·`elem_type`, `thickness`·`E`·`nu`, `support_node_id`·`support_dof`(ESL 자기 3-2-1) |
| 하중 전달 | `esl_load_transfer.md` §13 | 계획 표 5행(case_once·bmesh_once·step_once·step_per_design·compare_per_shape), 진단 `load_transfer_diag`, ②③ 참값 `a_direct` 인수분해 |

## 1. 범위 / 비범위

| 범위 (v0.20.0) | 비범위 |
|---|---|
| 1차 섭동 지표 C_lin(ESL별)·변형에너지 비 ρ·Ritz 형 C_ritz(정보) | 안마다 ESL 재생성(ESLSO 반복·비선형 재해석) — 진단 제안 1 |
| 순위 `rank.metric` lin(새 기본)·solve(옛), 재풀이 C 보조 열 | 하중 영역 제한 방식(진단 제안 2) |
| 불평형 진단 imbalance_rel(ESL별) | 회전 자유도 응축(condense) 방식 — §3 SM-4 기각, 후속 선택지 |
| umax·εmax 순위 제외, 표시값 = 강체 제거(umax_def), 3D 색 같은 기준 | 지표 계산을 위한 재풀이 생략(속도 이득) — solve 는 보조 열로 계속 |
| 상위 k 안 실제 낙하 재검증 안내(문구만) | 검증 낙하 자동 실행(`esl_scx_relay.md` 범위 밖 그대로) |

## 2. 정의 (D-0.20.0-SM-1~3)

기호: ESL i 의 원본 메시 A, 원본 하중 F_{A,i}(병진, 3N_A), 쉘 강성 K_A(6N_A×6N_A, 지지 없음). 대상 메시 t(베이스라인 d000 또는 안), 강성 K_t(6N_t, 지지 없음, 안 좌표로 조립), 해석 하중 F_{t,i}(하중 전달 계획으로 옮긴 값 — 지금 solve 에 쓰는 값 그대로).

**(1) 참조 변위 u_ref,i (6N_A)** — 계획 표 열 `sm.ref`(§4):
- `base`(①): 베이스라인 d000 의 solve 해 그대로(d000 = A, identity — 추가 풀이 0).
- `a_direct`(②③④ 중 d000 ≠ A): A 메시·ESL raw 물성(`thickness·E·nu`)·ESL 자기 지지(`support_node_id·dof`, rank < 6 이면 A auto 3-2-1 + 정보 `LT_TRUTH_AUTO_SUPPORT`)에서 K_A u = F_A 1회 풀이 — **`esl_load_transfer.md` LT-10/§13.7 참값 `a_direct` 와 같은 인수분해·같은 해를 공유**(추가 인수분해 0).
- 회전 성분 포함 6 dof(병진 + 회전). **강체 제거**: u_ref ← u_ref − P_rig(x_A) u_ref(§2(5) 정의, A 좌표 기준). 근거: 강체 운동은 A 좌표에서만 무에너지이고, 안 좌표(모핑·다른 메시)로 옮기면 ω×(x_t − x_A) 만큼 가짜 변형이 된다. K_A 는 강체를 정확히 소거하므로 C_ref 는 불변.

**(2) 변위 전달 S_t (N_t×N_A, 성분 공통)** — 계획 표 열 `sm.disp`:
- `I`: 같은 노드(① 모든 안, ②③ 베이스라인 이후의 모핑 안 — node_id 불변) → u_t = u_ref(노드 값 그대로, 순서 = node_id 재배열).
- `interp`: **하중 전달 W(LT-2)의 쌍대**. W 는 "대상 변위 → A 노드 위치 변위" 보간 T_t(행 = A 노드)이고 하중은 f_t = T_tᵀ f_A. 변위는 반대 방향 보간 S_t(행 = 대상 노드): 대상 노드 x_n 을 배치(LT-23)의 역변환으로 A 좌표에 놓고, **LT-2 와 같은 사영 알고리즘(knn·Ericson·QUAD Newton·clamp·동률 규칙)으로 A 요소의 최근접점을 찾아 그 형상함수 행** — 역할만 바꾼 같은 코드(`load_transfer.build_disp`). 같은 메시면 S_t = T_tᵀ = 순열(identity 경로와 비트 동일). 거리 > `work.proj_tol_mm` 인 대상 노드 = clamp 값 그대로 + `sm_far_frac`(노드 수 비) 기록.
- 6 성분(병진 3 + 회전 3)을 **같은 형상함수로 전역 성분 보간**(Reissner–Mindlin 쉘의 독립 회전장과 같은 보간), 배치가 `rigid`·`frame` 이면 보간 후 두 3-벡터를 배치 회전 R 로 돌림(크기 비례 없음 — 하중 배치와 같은 가정).
- 일관성 진단 `ts_err_i` = |F_Aᵀ(T_t S_t u_ref − u_ref)| / C_ref(`interp` 이고 T_t 가 있을 때만, 같은 메시 = 0).

**(3) 지표 (ESL i, 대상 t)**:
```
C_ref,i  = u_ref,iᵀ K_A u_ref,i                    (A 변형에너지의 2배; = F_Aᵀu_ref + 반력 일. 둘의 상대차를 bal_i 로 기록)
U2_t,i   = u_t,iᵀ K_t u_t,i,   u_t,i = S_t u_ref,i  (같은 변형을 대상에 줄 때 필요한 일의 2배 — 조립 K_t 와 SpMV 만, 분해 없음)
rho_t,i  = U2_t,i / C_ref,i                          (변형에너지 비 U_t/U_ref)
C_lin,t,i  = C_ref,i − (U2_t,i − C_ref,i) = C_ref,i (2 − rho_t,i)        ← 순위 지표(lin_form taylor, 기본)
C_ritz,t,i = C_ref,i / rho_t,i                                            ← 정보(lin_form ritz 이면 순위 지표)
imbalance_rel_t,i = Σ_n ‖(F_t,i − K_t u_t,i)_n,병진‖ / Σ_n ‖F_t,i,n‖      ← 불평형 진단(#63 의 r)
```
- **1차 섭동인 근거**: C(K) = Fᵀ K⁻¹ F, dC = −Fᵀ K⁻¹ dK K⁻¹ F = −uᵀ dK u. 메시가 다르면 공통 공간이 없으므로 대상 강성을 A 공간으로 당겨(Galerkin pullback) K̃_t = S_tᵀ K_t S_t, dK = K̃_t − K_A → C_lin = C_ref − u_refᵀ(K̃_t − K_A)u_ref = 2C_ref − U2_t(위 식과 같음). S_t = I 이면 dK = K_t − K_A 그대로. **K_t = K_A 이면 C_lin = C_ref 정확**.
- **하중 F_t 를 쓰지 않음**: C_lin 은 F_A 를 u_ref 로만 받는다 → 하중 전달 방식(work·cell)과 무관하고, 고정 하중 F 가 바뀐 K_t 와 맞지 않아 생기는 불평형(#63 원인)이 지표에 들어오지 않는다. 하중 전달은 solve 보조 열·불평형·변위 표시에만 쓰임.
- **하한 성질(S_t = I, F_t = F_A 일 때 — ①)**: 전 포텐셜 Π_t(v) = ½vᵀK_t v − Fᵀv ≥ Π_t(u_t*) = −½C_solve 이므로 임의 v 에 C_solve ≥ 2Fᵀv − vᵀK_t v. v = u_ref → **C_lin ≤ C_solve**, v = α u_ref 최적 α → **C_lin ≤ C_ritz ≤ C_solve**(차 = C_ref(ρ−1)²/ρ ≥ 0). 등호 ⇔ K_t = K_A(또는 K_t = αK_A 이면 C_ritz = C_solve 정확). 즉 lin 은 solve 의 1차 항과 일치하고 무른 모드 증폭(2차 이상 항)을 담지 않는다. 메시가 다르면 이 부등식은 `ts_err` 만큼만 근사.
- **해석**: 한 ESL 안에서는 C_lin·C_ritz 모두 ρ 의 단조 감소 함수 → 순위 = "ESL 원본 변형 u_ref 를 만들려면 더 많은 일이 드는 안이 강함". 여러 ESL 의 max 에서만 taylor·ritz 가 다를 수 있음.
- **유효 범위**: |ρ − 1| > `rank.lin_valid`(기본 0.3) 이면 ESL 행 경고 `SM_LIN_RANGE`(1차 근사 밖), C_lin ≤ 0(ρ ≥ 2) 도 같은 경고(값은 그대로 순위에 — 단조라 순서는 보존).

**(4) 순위 (D-0.20.0-SM-2)** — BD-D-6 구조 그대로, 지표만 metric 으로:
```
metric = lin : M_{d,i} = C_lin,d,i (lin_form ritz 이면 C_ritz)      metric = solve : M_{d,i} = C_{d,i}(지금 solve, 바이트 동일)
M_ref = max_i M_{d000,i},  score_d = max_i M_{d,i} / M_ref,  개선율 = 1 − score_d,  최악 ESL = argmax_i M_{d,i},  오름차순·동률 = id 사전순
```
- d000 도 같은 규칙(① d000 은 S = I·K_t = K_A → C_lin = C_ref, ρ = 1). ESL별 비(v0.10.0 `per_esl_metrics`)·pareto·민감도도 같은 metric 값으로. M_ref ≤ 0 → `BASELINE_FAILED`(지금과 같은 코드).
- 보조: `score_solve` = 지금 정의(max_i C_{d,i} / max_i C_{d000,i}) — 모든 새 결과에 열로 남김(비교용), `imbalance_max_d` = max_i imbalance_rel, `rho_min·rho_max`.
- noise_floor(③ 옛 NOISE 안): 같은 metric 으로 잰 비를 씀(ratio_tol 규칙 그대로).

**(5) 강체 제거 (D-0.20.0-SM-3)** — 표시 전용:
```
P_rig: 노드 집합 Ω(영역이 있으면 영역 노드, 없으면 전체), 무게 w_n = 1, x̄ = Ω 노드 평균
(a, ω) = argmin Σ_{n∈Ω} ‖u_n − a − ω × (x_n − x̄)‖²        (6×6 정규방정식, 결정적; 판 노드는 항상 rank 6)
u_def,n = u_n − a − ω × (x_n − x̄),   θ_def,n = θ_n − ω
umax_def = max_{n∈Ω} ‖u_def,n‖        εmax 는 강체 불변(요소가 강체 6모드 무에너지)이라 값 그대로
```
- "최저 몇 모드 제거"(고유모드)는 쓰지 않는다 — 고유해석 비용·모드 선택 임의성, 사용자 결정 3.
- **한계를 명시**: 강체 제거는 #63 의 강체 성분(≈ 94 %)만 없앤다. 불평형이 일으킨 무른 굽힘은 남는다(d009 E11 7,645 → 2,021 mm). 그래서 umax_def·εmax 는 **순위·대표 표시(최악 ESL 요약·카드)에서 빠지고 보조 열에만**, imbalance_rel > `rank.imbalance_warn` 인 행은 흐리게 + 경고 `SM_IMBALANCE`.
- 3D 컨투어(view3d): 색·변형 그림 = solve u 의 u_def(같은 Ω·같은 식), 범례 "변위 |u| — 강체 제거, 해석값(순위와 무관)". ④ LT-9 의 같은 ESL 맞춤은 그대로.

## 3. 결정

| ID | 결정 | 근거 |
|---|---|---|
| D-0.20.0-SM-1 | 지표 정의 §2(1)~(3): u_ref = 기준 해(①)·`a_direct`(그 밖), 강체 제거 후 S_t 로 전달, C_lin = C_ref(2 − ρ), ρ = U2_t/C_ref, C_ritz·imbalance_rel 함께 | 사용자 결정 2. 재풀이 없음(대상은 조립 + SpMV), F_t 와 K_t 불일치가 지표에 안 들어옴 |
| D-0.20.0-SM-2 | 순위 = BD-D-6 구조 + metric. 새 스터디 기본 `lin`(lin_form `taylor`), 옛 스냅샷(키 없음) = `solve` 바이트 동일. solve 는 보조 열 | 사용자 결정 2 |
| D-0.20.0-SM-3 | umax·εmax 순위·대표 표시 제외, 표시값 = 최소제곱 강체 6자유도 제거(§2(5)), 3D 색 같은 기준, 불평형 경고 | 사용자 결정 3, #63 강체 94 % |
| D-0.20.0-SM-4 | **회전 자유도 = 같은 형상함수로 보간해 전달(carry)**. 응축(K̂ = K_tt − K_tr K_rr⁻¹ K_rt) 은 기각: 대상마다 K_rr 분해(재풀이에 준하는 비용). carry 는 1차 일관 — u_ref 의 회전은 K_A 에서 에너지 정류점이고 K_t 의 최적 회전과 O(dK) 차이이므로 U2 오차는 O(dK²) | 재풀이 없는 원칙, 1차 정확 |
| D-0.20.0-SM-5 | **모드 무관 순수 모듈** `esl/doe/stiffness_metric.py`(§5), 모드 차이 = 계획 표 열 `sm.ref`·`sm.disp` 2개(§4) | 사용자 결정 5 |
| D-0.20.0-SM-6 | 지표는 새 스냅샷의 모든 안에서 항상 계산(metric 과 무관 — 비용 = 조립 1회 + K 회 SpMV), metric 은 BD_POST 순위만 바꿈 → `rank.metric` 은 이어하기 해시 밖(설정만 바꿔 후처리 재실행 가능). `stiffness` 스키마 번호는 해시 안(스냅샷에 키 있을 때만 — legacy 해시 불변) | 비교·재현성 |
| D-0.20.0-SM-7 | 실제 낙하 재검증: **코드 변경 없음**. 결과 화면 순위 아래 안내 1줄 + report 한계 절 + 사용자 설명서: "1차 강성 지표 순위 — 상위 k 안은 산출물(BD-D-18)로 Radioss 검증 낙하(`esl_scx_relay.md` B)를 돌려 확인" | 사용자 결정 4 |

## 4. 전달 계획 표 열 추가 (`esl_load_transfer.md` §13.3 표에 열 2개 — 같은 표, 같은 `transfer_plan.py`)

| plan id | `sm.ref` | `sm.disp` (베이스라인 / 안) | Ω(강체 제거·에너지 범위) |
|---|---|---|---|
| `case_once` ① | `base`(d000 해) | I / I | 전체 |
| `bmesh_once` ② | `a_direct` | interp(A → B 1회) / I(베이스라인의 u_t 를 노드 그대로) | 전체 |
| `step_once` ③ | `a_direct` | interp(A → B 영역 1회) / I | ③ 평가 영역(요소 마스크 — 에너지·불평형·강체 제거 모두 영역 요소·노드만) |
| `step_per_design` ③(옛) | `a_direct` | interp / interp(안마다, 같은 배치) | 전체 |
| `compare_per_shape` ④ | identity(d000 = A)면 `base`, 아니면 `a_direct` | interp(같은 메시면 순열) / interp(형상마다) | LT-8 영역 |

- 지시문의 "①② S = I, ③④ S_t" 를 실제 메시 관계로 정리: ② 의 B 베이스라인은 A 와 다른 메시라 **베이스라인에서 1회 interp**, 그 뒤 모핑 안은 같은 위상이라 I. 새 ③ 도 안 = 베이스라인 모핑(§13.1)이라 ② 와 같음. 안마다 S_t 는 옛 ③·④. (LT Q-LT-5 와 같은 판단, §11 Q-SM-3)
- `once` 모드의 베이스라인 u_t(6N_B)는 `prep/sm_ref.npz`(node_id, entry_ids, u (K,N,6) float64, schema `esl/doe_sm_ref/1`)에 1회 저장해 모든 안이 읽음. `per_target` 은 안 폴더 `run/designs/<did>/sm.npz` 를 쓰지 않고 메모리에서만(산출물 크기).
- 새 계획 행을 더하면 이 두 열도 채움(빈 칸 = `CONFIG_INVALID`).

## 5. 모듈 구조 (D-0.20.0-SM-5)

```
esl/doe/stiffness_metric.py   (신규 — 모드 무관 순수 모듈)
  import 허용: numpy, scipy.sparse, esl.errors, esl.mech.shell(ShellModel 조립 K() 만 — 분해 호출 금지)
  import 금지: esl.doe.*(load_transfer 포함 — S 는 입력으로 받음), 파일 IO, 설정 해석
  rigid_fit(x, u6, mask=None) -> (a, ω, x̄);  remove_rigid(x, u6, mask=None) -> u6
  apply_disp(S, u6, R=None) -> u6_t                     # S: scipy.sparse (N_t×N_A) | 순열 index 배열 | None(I)
  stiffness(mesh_t, solver_cfg, elem_mask=None) -> K_t   # ShellModel(..., drill_factor, backend).K(), 영역이면 submesh
  metrics(K_t, u_t6, F_t, C_ref, *, lin_valid, imbalance_warn) -> {U2, rho, C_lin, C_ritz, imbalance_rel, warnings[]}
  reference(K_A, u_ref6, F_A) -> {C_ref, bal}
  score(per_esl, metric, lin_form) -> 행 값(rank.py 가 씀)
esl/doe/load_transfer.py       += build_disp(a_mesh, t_x, placement, wcfg, h) -> (S, info{max_dist_mm, far_n})   # LT-2 사영 역할 바꿈
esl/doe/rank.py                rank(results, *, metric="solve", lin_form="taylor", ...) — metric 키로 per_esl 의 값 선택(기본 solve = 지금 바이트)
esl/doe/stages.py              eval: evaluate(keep_u = 모든 ESL) → u_def·umax_def / sm.metrics(K_t 조립, plan 의 S) → result.json per_esl 에 키 추가
```
- stages 는 계획 열만 읽음(`plan.sm_ref`·`plan.sm_disp`), 시나리오 이름 분기 없음(LT §13.3 `_plan_loads` 와 같은 규칙).
- `evaluate.py` **변경 없음**: 대상 K_t 는 stiffness_metric 이 따로 조립(조립 = 분해보다 훨씬 쌈, R-SM-2), solve 변위는 기존 `keep_u` 로 받음.

## 6. 산출물 · 설정

- `result.json`(안) per_esl 행 += `C_lin, C_ritz, rho, imbalance_rel, umax_def, ts_err?, sm_far_frac?`(새 스냅샷만), 행 밖 += `sm{metric, lin_form, ref, disp, C_ref{entry_id: …}}`. 기존 키 `C`(= solve)·`umax`(날 값)·`epsmax` 는 이름·값 그대로(옛 결과와 같은 뜻).
- `post/result.json` 순위 행 += `score_solve, imbalance_max, rho_min, rho_max, umax_def`(최악 ESL 기준), 최상위 += `metric, lin_form`. `score`·`improvement`·`worst_entry_id` 는 metric 기준.
- `ranking.csv`(새 스냅샷): `id, rank, status, <값들>, score, improvement, worst, metric, score_solve, imbalance_max, rho_min, rho_max, umax_def, epsmax, C_<i>…(metric 값), C_solve_<i>…` + LT 끝 열. 옛 스냅샷 = 지금 열 그대로.
- 진단: `esl_load_transfer.md` §5 스키마의 `shapes[].per_esl[]` 에 `sm{C_lin, rho, imbalance_rel, ts_err}` 선택 키(같은 스키마 1개), `d000.rows` 에 `sm` variant 행 1개(참조 대비 C_lin·ρ). 새 파일 없음.
- 설정 `bead_doe.rank`(DEFAULTS·pydantic·yaml 2 = 4곳 거울):
```yaml
  rank:
    ratio_tol: 1.0e-6
    per_esl_inline_max: 2000
    metric: lin            # lin(1차 섭동 C_lin, 새 스터디 기본) | solve(재풀이 C — 옛 동작)
    lin_form: taylor       # taylor(C_ref(2−ρ)) | ritz(C_ref/ρ)
    lin_valid: 0.3         # |ρ−1| 초과 → SM_LIN_RANGE
    imbalance_warn: 0.02   # imbalance_rel 초과 → SM_IMBALANCE(표시 흐림). #63 최소 4.5 % 에서 이미 umax ×65
```
- 스냅샷: 생성 시 `doe.rank{metric, lin_form, lin_valid, imbalance_warn, schema: 1}` 고정(요청 키 없음 — 설정만), `inputs.rank_metric`. 옛 스터디 = 키 없음 = solve. 복제 = 원 스터디 값 유지(없으면 solve 명시).
- 오류·경고 코드(`resources/doe_messages.json`): 경고 `SM_LIN_RANGE`, `SM_IMBALANCE`, 정보 `SM_REF_AUTO_SUPPORT`(= LT_TRUTH_AUTO_SUPPORT 재사용 가능하면 재사용), 진단 실패 = 그 안 지표 null + `SM_SKIPPED`(metric lin 이면 그 안 순위 밖 `extra_failed`, 사유 표시).

## 7. 화면

- 순위 표(새 결과): 주 열 = "강성 지표(1차)" score·개선율·최악 ESL. 보조 열(접힘 `<details>` 또는 "보조 열 보기" 토글 1개) = 재풀이 C 비(score_solve)·불평형 %·ρ 범위·umax(강체 제거)·εmax. 불평형 > imbalance_warn 행의 보조 값 흐림 + 아이콘 툴팁 `SM_IMBALANCE` 문구. 대표 카드(최적 안 요약)에서 umax·εmax 제거.
- 순위 아래 안내 1줄(SM-7). 3D 범례 문구(§2(5)). legacy 결과 = 지금 화면 그대로.
- 2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음.

## 8. 시험 (V-SM-n) — 모듈 단위(모드 무관 합성)와 계획·통합 분리

| ID | 시험 | 위치 |
|---|---|---|
| V-SM-1 | **K₁ = K₀ → lin = solve**: 합성 판(quad·tria 혼합, 3-2-1) + ESL F = K₀u_drop, S = I·같은 좌표 → C_lin = C_ritz = C_solve(1e-10 상대), ρ = 1, imbalance_rel = 반력비 수준(≤ 1e-9) | `tests/doe/test_stiffness_metric.py` |
| V-SM-2 | **작은 ΔK 에서 1차 일치**: 모핑 α ∈ {1e-4, 1e-3, 1e-2}(비드 법선 이동) — (a) C_solve − C_lin = O(α²)(α 10배 → 차 ≈ 100배, 기울기 2 ± 0.2), (b) dC_lin/dα = 유한차분 dC_solve/dα(1e-3 상대), (c) 모든 α 에서 C_lin ≤ C_ritz ≤ C_solve(S = I 하한) | 같은 파일 |
| V-SM-3 | **무른 모드 증폭 재현**: 긴 얇은 판(무른 전역 굽힘) + 큰 F = K₀u_drop + 국부 비드 모핑 α ∈ {0.1, 0.5, 1} → solve: umax 비 α 에 비례해 ≥ 10 배·imbalance_rel ≥ 0.05(#63 재현), lin: score 변화 연속·|score_lin − 1| ≤ 0.2·α 에 거의 선형, umax_def < umax 이지만 여전히 큼(한계 확인) | 같은 파일 |
| V-SM-4 | **강체·전달**: (a) u_ref 에 임의 강체 더함 → C_lin·ρ 불변(1e-10), (b) rigid_fit 이 순수 강체를 1e-12 로 복원, (c) apply_disp: 선형장 정확 재현(1e-12), 순열 S = identity 비트 동일, (d) 회전 carry 와 condense(시험 전용 참조 구현)의 C_lin 차 = O(α²) | 같은 파일 |
| V-SM-5 | **모드 무관**: 모듈 AST 검사(esl.doe import 없음·분해 호출 없음), 같은 입력 배열이면 어느 계획에서 불러도 결과 비트 동일, `rank(metric=solve)` = 지금 rank 바이트 동일, metric lin·ritz 순위·ESL별 비·pareto | 같은 파일 + `tests/doe/test_rank_metric.py` |
| V-SM-6 | **계획 열**: 5개 plan 의 `sm.ref`·`sm.disp`·Ω 가 §4 표와 같음, 빈 칸 = CONFIG_INVALID, `once` 는 sm_ref.npz 1회·안마다 S 생성 0(호출 계수), d000 도 같은 규칙(did 분기 없음) | `tests/doe/test_transfer_plan.py` |
| V-SM-7 | **통합 ①②③④**: 합성 각 모드 1 스터디 → result.json 키, ranking.csv 열, ① d000 C_lin = C_ref, ②③ a_direct 인수분해가 LT 참값과 공유(인수분해 수 불변), ④ identity d000, view3d 색 = u_def | `tests/doe/test_lt_modes.py`(+SM) · `worker/tests/test_doe_sm_jobs.py` |
| V-SM-8 | **API·설정**: 4곳 거울, 스냅샷 `doe.rank`·`inputs.rank_metric`, 옛 스터디 키 없음, 결과 필드 통과, openapi | `backend/tests/test_doe_rank_metric_api.py` |
| V-SM-9 | **UI**: 새 결과 주 열·보조 열 토글·흐림·안내 1줄·대표 카드 umax 없음, legacy 결과 지금 그대로, 3D 범례, 잘림 없음 | `frontend/src/__tests__/doe_stiffness_metric.test.tsx`, mock |
| V-SM-10 | **회귀**: 옛 스냅샷 ①②③④ 전 산출물 바이트 동일(`sel_regress`·`selreg`·④ regress), 새 스냅샷의 `C`·`umax`·`epsmax`·`score_solve` = 옛 값과 같음(보조 열이 지금 순위를 그대로 재현), `evaluate.py`·`mapping.py`·`target.py`·`shell.py` diff 0 | 기존 + 작업 폴더 |
| V-SM-R1 | (수동, #63) ① 20안 재실행: lin score 범위·ρ·imbalance_rel(5~27 % 재현)·umax_def, solve 순위와의 Spearman 기록, 상위 3안 Radioss 검증 낙하(SM-7 안내대로) | 현장 |

## 9. 파일 소유권 (겹침 0)

| 담당 | 파일(소유) | 시점 | 시험 |
|---|---|---|---|
| **(a) core-sm (새 core 에이전트, 지금 병렬)** | 신규 `esl/doe/stiffness_metric.py`, `esl/doe/rank.py`(metric·lin_form 인자, 보조 필드 — 기본 solve 바이트 동일), 신규 `tests/doe/test_stiffness_metric.py`·`tests/doe/test_rank_metric.py`(합성은 시험 파일 안 또는 신규 `tests/doe/synth_sm.py`). **금지**: `stages.py`·`report_doe.py`·`load_transfer.py`·`transfer_plan.py`·`__init__.py`·`doe_messages.json` | 지금 | V-SM-1~5 |
| **(b) core-geom (기존 core 에이전트, LT 작업 뒤)** | `load_transfer.py` += `build_disp`; `transfer_plan.py` 계획 열 `sm.ref`·`sm.disp`·Ω; `stages.py`(eval: keep_u 전체·u_def·sm.metrics 호출·sm_ref.npz·result 키, BD_POST rank(metric) 호출·CSV 열, view3d 색 u_def, `_cfg_hash` stiffness 스키마); `report_doe.py`(순위 지표 설명·보조 열·한계 절 낙하 재검증 안내); `esl/doe/__init__.py` DEFAULTS `rank.*`; `resources/doe_messages.json`(SM 코드); `tests/doe/test_transfer_plan.py`·`test_lt_modes.py` SM 분 | LT 뒤 | V-SM-6·7(코어분)·10 |
| **(c) backend** | `core/config.py` `BeadDoeRankCfg` += metric·lin_form·lin_valid·imbalance_warn; `config/*.example.yaml` 2개; `api/services/doe.py`(스냅샷 `doe.rank`·`inputs.rank_metric`·복제·결과 통과); `api/schemas.py`(`DoeStudyOut.inputs.rank_metric`, 순위 행 `score_solve·imbalance_max·rho_min·rho_max·umax_def`, 결과 `metric·lin_form`, per_esl 새 키); `docs/contracts/openapi_p1b.json`; 신규 `backend/tests/test_doe_rank_metric_api.py`·`worker/tests/test_doe_sm_jobs.py` | 지금(스키마) | V-SM-7(워커분)·8 |
| **(d) frontend** | `src/api/types.ts`·`doe.ts`(새 필드); `src/pages/doe/DoeStudy.tsx`(순위 표 주 열 교체·보조 열 토글·흐림·안내 1줄·대표 카드·3D 범례); mock(`doedata.ts`·`server.ts`); 신규 `src/__tests__/doe_stiffness_metric.test.tsx` | 지금(mock) | V-SM-9 |
| 통합(Plan) | 이 문서, `docs/decisions.md`, `esl_bead_doe.md` BD-D-6 각주, `esl_load_transfer.md` §14 참조, `CHANGELOG.md`, `docs/manual/user.md`(순위 지표 읽는 법·낙하 재검증) | – | – |

- 순서: (a) ∥ (c) ∥ (d) → (b)(LT 작업 뒤, (a) 의 모듈 시그니처 사용) → 통합 E2E(V-SM-7) → 회귀(V-SM-10) → 현장(V-SM-R1).
- 공동 수정 금지: `rank.py`·`stiffness_metric.py` = (a) 단독, `stages.py`·`report_doe.py`·`load_transfer.py`·`transfer_plan.py`·`__init__.py`·`doe_messages.json` = (b) 단독, `schemas.py`·`config.py`·yaml·`worker/**` = (c), `types.ts` = (d). `evaluate.py`·`shell.py`·`mapping.py`·`target.py` = 변경 금지.

## 10. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-SM-1 | 1차 근사 밖(큰 모핑 ρ ≪ 1 또는 ≫ 1)에서 순위가 실제와 어긋남 | `SM_LIN_RANGE`, lin_form ritz 선택지, solve 보조 열·Spearman, 상위 k 검증 낙하(SM-7) |
| R-SM-2 | 대상 K_t 조립이 solve 와 별도로 1번 더(380k 요소) | 조립은 분해 대비 작음 — `stage_times` 에 `sm_s` 기록. 후속: evaluate 와 조립 공유 |
| R-SM-3 | interp 의 사영 오차(얇은 이중 벽 등)가 U2 에 가짜 변형에너지 | `ts_err`·`sm_far_frac` 진단, LT R-LT-2 와 같은 대응 |
| R-SM-4 | lin 은 "ESL 원본 변형을 강제" 하는 관점 — 하중 재분배·국부 좌굴은 못 봄 | 한계 절 문구 + 검증 낙하 안내 |
| R-SM-5 | keep_u 전체로 메모리 K×N×3×8 B(5 ESL × 380k ≈ 46 MB/안) | 병렬 상한 BD-D-15 추정에 더함(stages) |

## 11. 사용자에게 물을 결정 (권고안으로 진행)

| Q | 질문 | 권고 |
|---|---|---|
| Q-SM-1 | 순위 식: taylor C_ref(2−ρ)(지시 그대로, 기본) vs ritz C_ref/ρ | **ritz 로 바꾸기를 권고** — 1차 항 같음, 항상 양수, solve 에 더 가까운 하한(C_lin ≤ C_ritz ≤ C_solve), 균일 강성 배율에서 정확. 한 ESL 안 순위는 둘이 같음. 답이 오기 전에는 지시대로 taylor |
| Q-SM-2 | ②③ 참조 변위 u_ref 를 A 원본 풀이(a_direct)로 할지, B 베이스라인 solve 로 할지 | **A 원본** — B 베이스라인 solve 도 옮긴 고정 하중 × 다른 강성이라 #63 과 같은 오염을 받음 |
| Q-SM-3 | 지금 ③(안 = 기준 메시 모핑)의 S: 베이스라인 1회 interp 후 I vs 안마다 interp | **1회 후 I**(LT Q-LT-5 와 같은 판단) |
