# 계약: 경계력 ESL — 낙하 해석이 계산한 힘을 하중으로 (BFORCE, v0.24.0)

- 상태: **확정**(2026-11-18, 사용자 결정 2026-11-18 "경계력 ESL 추가" + 18:50 "그냥 현재 접촉력으로만 해보자"). main 39084b88(v0.23.3) 위 브랜치 `release/v0.24.0`.
- 버전: **v0.24.0**(기능). migration **없음** — 새 값은 Case 폴더 새 파일(`01_extract/bforce.*`, `04_esl/bforce.*`)·ESL 실행 `forces` JSON 의 새 키·스터디 폴더 새 파일(`prep/bforce*`, `run/designs/<did>/bforce.json`, `post/bforce_view.json`, `post/view3d/*_bf*`)·결과 응답 새 필드·작업 params 만. 새 작업 유형 없음.
- 관계: `esl_core.md`(TCL·pack·S4), `esl_jig_rank.md`(지그 — 같은 메시 비교 구조), `esl_jig_view.md`(하중 출처 표 RANK_SOURCES ↔ LOAD_SOURCES, 3D 다시 만들기 경로)를 보완. 충돌하면 경계력 ESL 범위에서 이 문서가 우선.
- ID: 결정 `D-0.24.0-BF-n`, 시험 `V-0240-n`, 후속 `R-BF-n`.
- 근거(#63·#82): 전 노드 ESL F = K₀u₀ 는 대회전이 섞인 낙하 변위에 선형 강성을 곱해 1e8 N 급 가짜 상쇄 하중을 만들고 설계안 재풀이가 팽창(umax 128~2417 mm). 지그 ESL(v0.23.x)은 현장에서 기준 재현 실패(MAC 0.13~0.44, tie_rel 0.89~0.99 — chassis rear 가 구조 중심이고 plate_led 등이 다수 스크류 tie 로 함께 휨). 낙하 해석이 실제로 계산한 노드 힘은 물리적 크기이고 상쇄 폭주가 원리적으로 없다.

### 사용자 확정 (변경 금지)
1. (2026-11-18) 새 ESL 종류 "경계력 ESL": F = 접촉력(CONT) + tie 체결력(CONT2) − M·a. 이 합 = 노드 내력(M a = F_ext − F_int). 지지는 강체 운동 제거만, 맞춤 없음.
2. (18:50) 현장 h3d 는 CONT·ACC·변위만 → **접촉력만으로 계산**: F = CONT − M_deck·ACC(관성 포함 기본), tie 하중 누락으로 생긴 불평형은 **관성 이완**으로 처리, 결과·탭에 데이터 등급과 한계 문구. full·fint 등급은 설계대로 두되 합성 시험만.
3. 결과 유형 이름은 하드코딩 금지 — 설정 목록(대체 이름 허용). 현장 확인 이름 "Contact Forces"·"Acceleration" 은 기본 목록에 포함.

## 0. 데이터 등급 (D-0.24.0-BF-1)

| 등급 | 필요 결과 | 하중(전역계, 노드 n) | 비고 |
|---|---|---|---|
| `full` | CONT + CONT2 (+ ACC, MASS 또는 deck 질량) | F = s_c·CONT + s_t·CONT2 − M·ACC | FINT 있으면 검산 ‖F − s_f·FINT‖/‖s_f·FINT‖ |
| `fint` | FINT (CONT2 없음) | F = s_f·FINT | 분해 정보 없음(`decomposed: false`) |
| `contact` | CONT (+ ACC) (CONT2·FINT 없음) | F = s_c·CONT − M·ACC | **tie 체결력 미포함 — 조립 부품 하중 누락**(한계 문구 `BF_TIE_MISSING`), 불평형은 관성 이완(§3.4) |
| `none` | CONT·FINT 모두 없음 | 계산 안 함 | 진단 코드 `BF_NO_DATA`(추출 자료 없음) |

- 우선순위 full > fint > contact > none. 관성 항 −M·ACC 는 `use_inertia`(기본 true) ∧ ACC 있음일 때만(없으면 경고 `BF_NO_ACC`, 관성 없이).
- M = h3d MASS(있으면, `mass_source: "h3d"`) | deck 근사(§3.3, `mass_source: "deck"` + 경고 `BF_MASS_APPROX` — 질량 스케일링 추가 질량 미포함 위험).

## 1. TCL 덤프 (`resources/tcl/esl_h3d_extract.tcl` 패스 C 확장 — D-0.24.0-BF-2)

- 시점: 패스 C 의 후보 프레임 D(변위 `disp.csv` 와 같은 프레임 — t* 는 Python 이 D 중에서 고름, 기존 선택 그대로). 노드 = 대상 파트 노드 청크(`disp.csv` 와 같은 청크).
- 종류 k ∈ {`cont`, `cont2`, `acc`, `mass`, `fint`} 마다 결과 유형 이름 후보(`bf_names_<k>`, `|` 구분)를 `GetDataTypeList` 에서 `match_name` 규칙(정확 → 대소문자·공백·밑줄 무시)으로 찾는다. 벡터 성분 = `bf_vec_comps`(기본 `X Y Z`, 각 성분 후보 `|` 구분 가능), 스칼라(mass) 성분 = `scalar_comps` 후보.
- 출력: 찾은 종류마다 `bf_<k>.csv` — 벡터 `frame_index,node_id,x,y,z`, 스칼라 `frame_index,node_id,v`. 값 없는 노드는 행을 쓰지 않음(Python 이 0 으로 채우고 수를 기록).
- 없는 유형·쿼리 실패는 **실패가 아님**: done.json `bforce = {"on": true, "frames": D, "kinds": {k: …}}`, 없는 종류 `{"type": null, "reason": "..."}`, 찾은 종류 `{"type", "comps", "rows"}`(쿼리 실패 = 그 CSV 삭제 + type null). `bf_on 0` → done.json 에 `bforce` 없음(이전과 같음). done.json 에 `bforce` 키가 없으면(이전 TCL) Python 은 등급 none(`BF_NO_DATA`).
- request.txt 새 키: `bf_on`(TCL 기본 **0 = 끔** — request 에 bf 키가 없으면 done.json·CSV 가 이전 버전과 바이트 동일(v0.7.2 TCL 골든 V-CI-B1), 워커는 설정 `bforce.enabled` 로 1, PC 수동 실행은 request.txt 에 `bf_on<TAB>1`), 이름 목록 기본 = 설정 기본과 같은 값: `bf_names_cont`, `bf_names_cont2`, `bf_names_acc`, `bf_names_mass`, `bf_names_fint`, `bf_vec_comps`. 워커 `h3d.bforce_request(core_settings)` 가 설정 `bforce.result_names`·`vec_comps`·`enabled` 에서 만든다.
- dump 모드(strain_tensor 원시 덤프 경로)는 이번 범위 밖(R-BF-5) — `bforce` 키 없음 = none.

## 2. 패킹 (`esl/io/bforce_csv.py:pack_bforce(results_dir, node_id, out_dir) -> dict`)

- `stage_extract` 가 `pack_results` 다음에 부른다. done.json 에 `bforce` 키가 없으면 아무것도 쓰지 않는다(옛 추출물 = `01_extract` 바이트 동일).
- `01_extract/bforce.npz`: `frame_index(D,)i4`, `node_id(N,)i8`(model 순서), 있는 종류만 `cont|cont2|acc|fint (D,N,3) f8`, `mass (D,N) f8`. `01_extract/bforce.json`(`esl/bforce_extract/1`): `{kinds: {k: {type, comps, rows, n_missing} | {type: null, reason}}, frames: [...]}`. 대상 파트 밖 노드 행은 무시, 모르는 프레임 행은 무시.

## 3. 하중 조립 (공용 순수 모듈 `esl/mech/bforce.py` — D-0.24.0-BF-3)

- 독립 모듈: `esl.doe`·`esl.pipeline` import 금지, 파일 IO·설정 해석 없음(값은 인수). import 허용 = numpy, `esl.errors`, `esl.mech.kabsch`, `esl.mech.mass`.
- 질량 공식은 `esl/mech/mass.py` 한 곳: 요소 면적·법선 `elem_area_normal`(지그 `jig.node_weights` 와 같은 식 — jig 가 이 함수를 import, 결과 비트 동일), 집중질량 `lumped_mass(mesh, rho_e)` = Σ_e ρ_e t_e A_e / nn_e(질량 합 = Σρ t A 정확).

### 3.1 단위·좌표계·부호
- 단위 = 모델 단위계 그대로(mm-ton-s 이면 힘 N, 질량 t, 가속도 mm/s², g = 설정 `g_mm_s2` 9810). 변환 없음.
- 좌표계 = Radioss 전역계. h3d 벡터는 t* 변형 형상의 전역 성분.
- **부호**: CONT·CONT2 = **그 노드에 작용하는 힘**(접촉·tie 가 대상 파트 노드를 미는 힘), FINT = 설정 부호 s_f(`auto`: full 등급이면 ‖F_full − s·FINT‖ 최소인 s, 아니면 Σ s·FINT_ref·u_rel > 0 인 s — 내력이 변형에 일을 하는 방향). 설정 `signs: {cont: 1, cont2: 1, fint: auto}` 로 뒤집을 수 있다.
- 기준 형상으로 회전: S4 Kabsch(`remove_rigid(X0, u)` 의 R) 로 F_ref,n = Rᵀ F_n (선형 풀이 K₀ u = F 는 기준 형상 X0, u_rel 기준계).

### 3.2 함수
| 함수 | 입출력 |
|---|---|
| `grade_of(have: set) -> str` | 있는 종류 → full·fint·contact·none |
| `assemble(data, m_deck, *, use_inertia, signs, u_rel_ref=None, R=None) -> dict` | data = `{cont, cont2, acc, mass, fint}`(N,3)/(N,) 또는 None. 반환 `{grade, F (전역), F_ref, parts {cont, cont2, inertia}, m, mass_source, fint_sign, fint_check_rel, decomposed, warnings}` |
| `equilibrium(X, F) -> {sum_f[3], sum_m[3], center, sum_abs, max_f, force_rel, moment_rel, L_bbox}` | 합력·합모멘트(점 X 의 질량 중심 대신 산술 중심) |
| `rigid_modes(X, c) -> (N,3,6)` | 병진 3 + 회전 3(e_k × (X − c)) |
| `inertia_relief(X, m, F) -> {F_bal, abar[6], center, corr_rel}` | ā = (RᵀMR)⁻¹RᵀF, F_bal = F − M R ā, c = 질량 중심. corr_rel = Σ‖M R ā‖ / Σ‖F‖ |
| `mac(u, v)`, `recon_report(u_rel, u_val_rel, R, F) -> {mac, umax_ref, umax_val, umax_err, reaction_rel, reaction_max_rel}` | 재현 비교 |

### 3.3 질량 (deck 근사)
- ρ_e = 요소 재료(`model_meta.mats[mid].rho`), 없거나 ≤ 0 → 설정 `default_rho`(7.85e-9 t/mm³) + 경고 `BF_RHO_DEFAULT`(재료 id 목록). t_e = 모델 두께(요소 카드 > /PROP/SHELL — `parse_rad` 규칙).
- MASS(h3d) 가 있으면 그것을 쓰고 deck 근사는 비교 정보만(`mass_deck_total`).

### 3.4 균형(balance, 설정 `balance: inertia_relief | none`, 기본 inertia_relief)
- 관성 이완: 기준 형상 X0·질량 M 으로 F_bal = F_ref − M R ā. tie 가 빠진 contact 등급의 순 불평형(= 생략된 tie 하중의 순 합력 −ΣF)을 전체 강체 가속도로 돌린다. full·fint 는 원래 자기평형이라 ā ≈ 0(보정률 진단).
- `none` = F_ref 그대로(3-2-1 반력 = 불평형).
- 진단(이완 전): 합력·합모멘트(기준 형상·변형 형상 두 가지), 생략 tie 합력 추정 `omitted_f = −ΣF_ref`·`omitted_m`, ā 병진 크기 g 단위 `abar_g`, 회전 `abar_rot`(rad/s²), 보정률 `corr_rel`, 최대 노드력, Σ|F| 와 전 노드 ESL Σ|F_eq| 비(`sum_abs_ratio_full`).

### 3.5 진단 스키마 `04_esl/bforce.json` (`esl/bforce/1`, 1개)
```text
{ schema, grade, decomposed, formula, kinds{k: bool}, mass_source, mass_total, mass_deck_total, rho_default_mats[],
  use_inertia, balance, signs{cont, cont2, fint}, sign_check{suspect, force_rel, force_rel_flip, abar_g, abar_g_flip}|null, fint_sign_source, fint_check_rel|null,
  frame{frame_index, time}, rot_deg,
  eq_raw {def: {sum_f, sum_m, force_rel, moment_rel}, ref: {...}}, eq_bal {ref: {...}},
  omitted_f[3], omitted_m[3], abar[6], abar_g, abar_rot, corr_rel,
  sum_abs, sum_abs_full, sum_abs_ratio_full, max_f{node_id, mag}, n_nodes_loaded,
  parts_sum_abs{cont, cont2, inertia},
  recon {status: ok|poor|skipped|failed, mac, umax_ref, umax_val, umax_err, reaction_rel, reaction_max_rel, reason?},
  limits[]: ["BF_TIE_MISSING", ...], warnings[] }
```
- `sign_check`(D-0.24.0-BF-11, 진단 전용 — 결과 불변): contact·full 등급에서 접촉 항(CONT·CONT2)의 설정 부호 F 와 반전 부호 F′(관성 항은 그대로)의 불평형 `force_rel = ‖ΣF‖/Σ‖F‖`(기준 형상)·관성 이완 ā(g)를 비교. 설정 쪽 force_rel 이 더 크고 ∧(질량이 있으면) ā 도 더 크면 `suspect` + 경고 `BF_SIGN_SUSPECT`(값 4개 포함). fint 등급·접촉력 없음 = `null`. 순수 함수 `bforce.sign_check(X0, data, m_deck, *, use_inertia, signs, R, g)`, `build()` 가 호출.
- 등급 none = `{schema, grade: "none", code: "BF_NO_DATA", reason, kinds}` 만.
- `04_esl/bforce.npz`: `node_id`, `f`(= 풀이 하중 F_bal, 기준계), `f_raw`(전역 F), `m`, `u_val`(재현 변위, 강체 제거), 등급 none 이면 파일 없음.

## 4. ESL 생성 단계 (Case `stage_esl` — D-0.24.0-BF-4)
- 기존 전 노드 ESL 계산·파일은 그대로(바이트 동일 — `esl_summary.json` 불변). 그다음 `bforce` 설정 `enabled`(기본 true) 이면 `01_extract/bforce.npz` 의 선택 프레임 자료로 §3 → `04_esl/bforce.json`·`bforce.npz`. 추출물에 경계력 자료가 아예 없으면(이전 추출·bf_on 0) 04_esl 에 아무것도 쓰지 않고(산출물 집합 불변 — V-CI-B1) 단계 요약만 `{grade: none, code: BF_NO_DATA}`, 경계력 추출은 했는데 접촉력·내력 유형이 없으면 등급 none json 만.
- 기준 재현: 같은 3-2-1 지지(S4 `pick_321`)로 K₀ u = F_bal(직접법 메모리 규칙 = `full_solve_decision` — 안 되면 `recon.status skipped`), u_val → 파트 전 노드 Kabsch 강체 제거 → u_rel 과 MAC·umax 오차, 반력 크기. MAC < `recon_mac_min`(0.9) 또는 |umax 오차| > `recon_umax_err_max`(0.2) = 경고 `BF_RECON_POOR`(실패 아님), 반력 비 > `reaction_warn_rel`(1e-3) = 경고 `BF_REACTION`.
- 경계력 단계 예외는 ESL 단계를 실패시키지 않는다(경고 `BF_FAILED` + json `{grade, code, reason}`).
- 단계 요약(반환·ESL 실행 `forces.bforce`): `{grade, mass_source, sum_abs, sum_abs_ratio_full, abar_g, corr_rel, mac, umax_err, reaction_rel, limits}` → ESL 화면 결과 카드 한 줄(`data-testid="esl-bforce-line"`). 3D·OptiStruct 내보내기는 후속(R-BF-1·2).
- 라이브러리 항목은 바꾸지 않는다(`raw.npz` 키 불변) — DOE 가 Case 폴더에서 찾는다(§5.2).

## 5. 강성 스터디 (DOE — D-0.24.0-BF-5~9)

### 5.1 계획 표 열 `bf` (`transfer_plan.PLANS`)
| 계획 | bf |
|---|---|
| case_once · bmesh_once · step_once | `base`(베이스라인 1회 하중 → 같은 메시 안 비교, 지그와 같은 결정 A) |
| step_per_design · compare_per_shape | `none`(다른 메시 — `BF_UNSUPPORTED`) |

### 5.2 하중 찾기·전달 (`stages._bf_loads`)
- 엔트리마다 경계력 하중 찾기(읽기만): ① 엔트리 `source.snapshot_dir/04_esl/bforce.npz` ② 없으면 같은 Case 의 `runs/*/04_esl/` 과 현재 `04_esl/` 중 `bforce.npz` 가 있고 노드 ID·좌표(sha)·프레임이 엔트리와 같은 것 — 가장 최근(mtime). 등급 = 그 `bforce.json` grade. 못 찾음 = none(사유 `BF_NOT_FOUND`).
- 사용 등급 = 설정 `bead_doe.bforce.grades`(기본 full·fint·contact) 안. 한 엔트리라도 밖이면 스터디 경계력 = `unavailable`(탭 비활성 + 사유, 엔트리별 등급·사유 표시).
- 베이스라인 하중: 하중 전달 스냅샷이 있으면 같은 `run_transfer_plan`(계획 identity·배치·주 방식 — work 등)으로 엔트리 메시 → 기준 메시, legacy(전달 없음)는 노드 ID 가 같을 때만(아니면 `BF_UNSUPPORTED`). 저장 `prep/bforce_loads.npz`(`node_id`, `entry_ids`, `f (K,N,3)`) + `prep/bforce.json`(`esl/doe_bforce_prep/1`: 엔트리별 `{entry_id, grade, source, sha256, frame_index, recon, limits}`).
- 설계안: once 계획 = 베이스라인 하중을 노드 ID 로 그대로(지그와 같음).

### 5.3 설계안 풀이 (BD_EVAL 훅 `_bf_apply` · 추가 계산 공용 `_bf_design`)
- 같은 3-2-1 지지(그 안의 지지 — 전 노드 ESL 풀이와 같음)로 `evaluate.evaluate(mesh, sup, F_bf)` (분해 +1/안, 지그와 같은 방식). C_bf = Σ F·u, umax_bf = max‖u‖(전 노드 ESL 과 같은 규칙), epsmax_bf, reaction_rel.
- 결과는 **사이드카** `run/designs/<did>/bforce.json`(`esl/doe_bforce_design/1`: `{did, status, loads_sha, per_esl[{entry_id, C_bf, umax_bf, epsmax_bf, reaction_rel}], warnings, solve}`) — 안 `result.json`·`design.npz`·`done.json` 은 바꾸지 않는다. BD_EVAL 훅은 예외를 삼키고(안 평가 무영향), BD_POST 가 사이드카 없는(이어하기 재사용 안 포함)·하중 sha 가 다른 안을 다시 푼다. 그래도 실패 = 그 안 경계력만 null(`BF_DESIGN_FAILED`, 순위 밖 n_failed["bf"]).
- 3D 대상(베이스라인 + `view3d` 목록 안)은 변위를 남겨 BD_POST 에서 3D(§5.5).

### 5.4 순위 보기 (BD_POST · 추가 계산 공용 `_bf_post`)
- 하중 출처 표 `RANK_SOURCES` 행 추가: `{key: "bforce", metric: "bf", drop: VIEW_DROP_BF, drop_pe: (C_solve, rho, imbalance_rel, umax_def), umax_pe: "umax_bf", eps_pe: "epsmax_bf", need: "C_bf", sidecar: "bforce"}`. 기존 행에 열 `eps_pe`(None)·`need`(C_jig)·`sidecar`(jig) 추가(동작 불변).
- `rank.rank(metric="bf")`: `sm.metric_key("bf") = "C_bf"`, 옛 스냅샷(C_lin 없음)도 허용, 값 null 안 = 순위 밖 `n_failed["bf"]`. 순위 구조(최악 ESL 비·오름차순·동률) 그대로.
- 보기 = 결과 목록 사본의 per_esl 에 사이드카 C_bf·umax_bf·epsmax_bf 를 붙여 rank → `_view_rows`(출처 행 열만) → `post/bforce_view.json`(`esl/doe_bforce_view/1`): `{schema, source: bd_post|add, settings, bforce (§5.6 블록), rank_views: {bforce: 보기}, per_esl?: {bforce: {...}}, view3d_bf?, view3d_bf_esl?, view3d_bf_ref?, warnings}`. 베이스라인 C_bf 가 모두 양수일 때만 보기.
- ranking.csv·result.json·per_esl.json·report.html 불변.

### 5.5 3D (설계 비교 = 응답 컨투어 + 하중 화살표)
- `post/view3d/<did>_bf/`(안, 순위 행 worst 엔트리 — `rank._agg(per_esl, "C_bf")`) · `post/view3d/d000_bf_e<kk>/`(기준 같은 엔트리) = `build_view(mesh, f = F_bf, u_rel = u_bf, supports = 3-2-1)` — 기존 view3d 형식(화살표 = manifest top/clusters). 설정 `bead_doe.bforce.view3d`(true).

### 5.6 블록 `bforce`(응답 `DoeResultOut.bforce`)
`{status: ok|unavailable|unsupported, code|null, reason|null, grade_min, entries: [{entry_id, label, grade, mass_source, source, eq_force_rel, eq_moment_rel, abar_g, corr_rel, recon_mac, recon_umax_err, reaction_rel, limits[]}], limits[] (합집합), n_designs, n_failed}`.

## 6. 기존 스터디 추가 계산 (D-0.24.0-BF-10)
- API `POST /doe/studies/{sid}/sources/bforce` → 202 `DoeStudyOut`. 권한·조건 = 3D 다시 만들기와 같음(실행 권한 ∧ (admin ∨ 작성자), DONE, 진행 중 작업 없음, 성공한 DOE_RUN). 계획 열 bf none = 409 `BF_UNSUPPORTED`.
- 작업: 기존 DOE_RUN 큐, params = 마지막 성공 DOE_RUN params 사본 + `kind: "BFORCE"` + `doe.post_mode: "bforce"` + `doe.bforce_cfg`(지금 설정 `bead_doe.bforce`), resume = BD_POST. 코어 `bd_post` → `_post_bforce`: §5.2 하중 → OK 안마다 `design.npz` 좌표(형상 생성 없음)로 §5.3 → §5.4·§5.5. 쓰는 곳 = `prep/bforce*`·`run/designs/<did>/bforce.json`·`post/bforce_view.json`·`post/view3d/*_bf*` 만(기존 결과 파일 바이트 불변 — V-0240-g). 워커 BD_REGISTER `kind BFORCE` = DB 무변경(`register_doe_view3d` 와 같은 함수).
- 응답 `DoeResultOut.bforce_add: {available, allowed, reason}` — available = 계획 bf base(다시 계산 가능 — 매번 prep 하중을 새로 찾고 하중 sha 가 바뀐 안만 다시 풀이), allowed = 3D 다시 만들기와 같은 권한·작업 조건; 화면 버튼 `data-testid="v3d-bf-add"`(활성 탭 3D 머리) = available ∧ `rank_views.bforce` 없음.

## 7. API · 고정 필드 (schemas.py ↔ types.ts)
| 스키마 | 필드 |
|---|---|
| `DoeResultOut` (+) | `bforce: DoeBforceOut \| None`, `bforce_add: DoeView3dRegenOut \| None`, `view3d_bf`, `view3d_bf_esl`, `view3d_bf_ref: dict[str,str] \| None`, `rank_views.bforce: DoeRankViewOut \| None` |
| `DoeBforceOut` | `status: str`, `code, reason: str \| None`, `grade_min: str \| None`, `entries: list[DoeBforceEntryOut]`, `limits: list[str]`, `limit_text: list[str]`(문구 원본 = `bforce.LIMIT_TEXT` 1곳), `recon_mac_min: float \| None`(재현 MAC 경고 기준 — 엔트리 Case 가 쓴 `recon.mac_min` 중 가장 엄격한 값, 없으면 설정 기본), `n_designs: int`, `n_failed: int` |
| `DoeBforceEntryOut` | `entry_id, label, grade: str`, `mass_source: str \| None`, `source: str \| None`, `eq_force_rel, eq_moment_rel, abar_g, corr_rel, recon_mac, recon_umax_err, reaction_rel: float \| None`, `sign_suspect: bool \| None`, `limits: list[str]`, `reason: str \| None` |
| per-esl | `?view=bforce` (사이드카 `bforce_view.json` per_esl) |
| ESL 실행 | `EslRunOut.forces.bforce`(JSON — 스키마 변경 없음; 키 `limit_text`·`sign_suspect` 추가, 화면은 문구 표를 갖지 않고 이 값을 그대로 씀) |

## 8. 화면
- 강성 스터디 결과 카드 탭 세그먼트에 `[경계력 ESL]` 1개(높이 불변). `LOAD_SOURCES` 행 `bforce`: label 경계력 ESL, primaryFor [] (기본 탭 아님), drop = 코어 거울, warnPrefixes `BF_`, hide = 지그·전 노드 3D·블록, chips `bf`·`best_clean`, view3d `pair`(`pairKeys` = view3d_bf·view3d_bf_esl·view3d_bf_ref), unavailable = 블록 사유(데이터 등급·미계산 → "추가 계산" 안내).
- 칩 `bf`(`data-testid="bf-chip"`): `경계력 ESL · 등급 contact · 재현 MAC 0.xx · umax 오차 x% · 평형 보정 x%` + 한계 문구(contact = "tie 체결력 미포함 — 조립 부품 하중 누락", 경고색), 툴팁 = 엔트리별 등급·질량 출처·ā(g)·반력.
- 3D: 기준 | 안 응답 컨투어(같은 범위) + 하중 화살표(기존). 머리 조건 줄 "하중: 경계력 ESL(등급) · 지지: 3-2-1 · 엔트리".
- Case ESL 화면: 결과 카드 아래 한 줄 `esl-bforce-line` — `경계력 ESL: 등급 · Σ|F| (전 노드 ESL 대비 ×r) · 관성 이완 ā = x g(보정 y%) · 재현 MAC · umax 오차 · 반력`, contact 이면 한계 문구, none 이면 "경계력 ESL 자료 없음 — h3d 추출을 다시 실행(v0.24.0 TCL)".

## 9. 설정
| 위치 | 키(기본) |
|---|---|
| Case 코어 `esl/config.py:BFORCE_DEFAULTS` + `config/esl.example.yaml` `bforce:`(선택 절 — cfg 에 주입 안 함, 설정 해시 불변) | `enabled` true, `result_names{cont: ["Contact Forces","Contact Force","CONT"], cont2: ["Tied Contact Forces","Contact Forces (TYPE2)","CONT2"], acc: ["Acceleration","ACC"], mass: ["Nodal Mass","Mass","MASS"], fint: ["Internal Forces","Internal Force","FINT"]}`, `vec_comps` ["X","Y","Z"], `use_inertia` true, `balance` inertia_relief, `signs{cont 1, cont2 1, fint auto}`, `default_rho` 7.85e-9, `g_mm_s2` 9810, `recon_mac_min` 0.9, `recon_umax_err_max` 0.2, `reaction_warn_rel` 1e-3, `fint_check_warn_rel` 0.05 |
| DOE `esl/doe/__init__.py:DEFAULTS["bforce"]` · `BeadDoeBforceCfg` · yaml 2(`esl_platform*.example.yaml` `bead_doe.bforce`) | `enabled` true, `grades` [full, fint, contact], `view3d` true |

## 10. 시험 (V-0240-n)
| id | 내용 | 위치 |
|---|---|---|
| a | 합성 평판: F_true(자기평형) 선형 풀이 u → CONT/CONT2/ACC/MASS 분해 합성 → full 조립 F = F_true(1e-9), FINT 검산, 재현 MAC ≥ 0.9999 | `tests/mech/test_bforce.py` |
| b | 대회전 강체 운동(회전 40°+병진)을 얹은 변위·회전된 힘에서도 재현 MAC ≥ 0.999(파트 Kabsch) | 같은 파일 |
| c | 비드(두께) 강화 → umax_bf·C_bf 단조 감소 | `tests/doe/test_bforce_doe.py` |
| d | #63 사례 대비: 대처짐 기하 비선형 성분이 섞인 u₀ 로 전 노드 ESL Σ|F| ≫ 경계력 Σ|F|, 설계안 재풀이 umax 비 — 경계력 ≤ 1.05, 전 노드 ≫ | 같은 파일 |
| e | contact 등급: tie 힘을 뺀 합성 — omitted_f = 뺀 tie 합력, ā·M_total = ΣF, 관성 이완 후 반력 ≈ 0(1e-9) | `tests/mech/test_bforce.py` |
| f | 결과 유형 이름 설정 대체(TCL mock: 다른 이름 목록으로 찾음·없는 유형 = type null 실패 아님), pack | `tests/io/test_tcl_bforce.py` |
| g | 기존 스터디 추가 계산: ranking.csv·result.json·per_esl.json·designs.json·report.html·안 result.json 해시 불변, 사이드카·보기 생김 | `tests/doe/test_bforce_doe.py` |
| h | 탭 독립: bforce 보기 행에 C_jig·score_solve·umax_jig 없음, 지그·전 노드 보기에 C_bf 없음, 화면 탭 DOM 섞임 0 | 같은 파일 + `frontend/src/__tests__/doe_v0240.test.tsx` |
| i | use_inertia false/true 비교(관성 항 0 / 포함), 밀도 미지정 → `BF_RHO_DEFAULT` + default_rho 질량 | `tests/mech/test_bforce.py` |
| j | Case 파이프라인 E2E(합성 CSV + bf CSV → stage_esl → bforce.json·npz, 옛 추출물 = none, esl_summary 불변) | `tests/pipeline/test_bforce_stage.py` |
| k | API: 결과 병합(bforce·rank_views.bforce·view3d_bf), per-esl view=bforce, sources/bforce 202·403·409, 워커 kind BFORCE = DB 무변경, 설정 거울 | `backend/tests/test_doe_bforce_api.py`, `worker/tests/test_doe_bforce_add.py` |
| l | 회귀·스크린샷 `/home/claude/shots/v0240_{tab_bforce,esl_line,contact_diag}.png` | – |

## 11. 결정 (decisions.md D-0.24.0-BF-n)
| ID | 결정 |
|---|---|
| BF-1 | 데이터 등급 full > fint > contact > none, contact 도 계산(관성 포함 기본), 한계 문구 `BF_TIE_MISSING` |
| BF-2 | TCL 패스 C(후보 프레임 D·대상 파트 노드)에 종류별 `bf_<k>.csv`, 이름 후보 목록 설정, 없는 유형 = type null(실패 아님) |
| BF-3 | 공용 순수 모듈 `esl/mech/bforce.py`·`esl/mech/mass.py`(지그 면적 식 공유), 부호 = 노드에 작용하는 힘, 기준 형상 회전 Rᵀ |
| BF-4 | 균형 = 관성 이완(기본) + 3-2-1, 반력 크기 진단, 재현 = 파트 전 노드 Kabsch MAC·umax 오차 |
| BF-5 | 계획 표 열 `bf`(base \| none), 같은 메시 비교만(결정 A) |
| BF-6 | DOE 하중 = Case 폴더에서 찾아(엔트리 스냅샷 → 같은 메시·프레임의 최신 run) 스터디 prep 에 사본, 전달 = 기존 run_transfer_plan |
| BF-7 | 설계안 값 = 안 사이드카(result.json 불변), 보기 = `post/bforce_view.json`, 출처 표 행 1개 + 열 eps_pe·need·sidecar |
| BF-8 | rank metric `bf`(C_bf) — 옛 스냅샷 허용, 순위 밖 n_failed["bf"] |
| BF-9 | 3D = 기존 view3d 형식 `<did>_bf`·`d000_bf_e<kk>`(하중 화살표 = 기존 manifest) |
| BF-10 | 추가 계산 = DOE_RUN resume BD_POST + kind BFORCE·post_mode bforce, DB 무변경 |
| BF-11 | 시나리오 이름 분기 제거(`_bf_on` 한 곳, 계획 열 bf 만), CONT 부호 점검 `sign_check`·경고 `BF_SIGN_SUSPECT`(결과 불변), 재현 MAC 기준·한계 문구는 백엔드 값 1곳(화면 하드코딩 없음), 비활성 탭 사유는 `.seg` 밖 |

## 12. 후속 (R-BF-n)
- R-BF-1 Case 화면 경계력 3D(하중 화살표·재현 비교) — 기존 `useLoadView` 는 run 의 f_eq 고정이라 별도 경로 필요.
- R-BF-2 OptiStruct·Radioss 내보내기(`06_export`) 경계력 하중 선택.
- R-BF-3 설계안 경계력 풀이를 전 노드 풀이와 같은 분해로(분해 +1 제거).
- R-BF-4 CONT2·MASS·FINT 출력 재해석 후 full·fint 현장 검증(결과 유형 표시명 확인 → 설정 목록 갱신).
- R-BF-5 dump 모드(strain_tensor) 경계력 덤프.
- R-BF-6 contact 등급의 생략 tie 하중을 tie 노드 분포로 추정(지금은 관성 이완으로 전체에 분산).

## 부록 A. 낙하 해석 Engine 파일 출력 카드 예시 (사용자 안내)
기준 모델 재해석 시 Engine 파일(`<run>_0001.rad`)에 아래를 더한다(이미 있는 CONT·ACC 는 그대로). 키워드 철자·열 형식은 사용 중인 Radioss 2026 Reference Guide 의 `/H3D/NODA` 와 `/H3D/PART` 항목으로 확인한다.
```text
/H3D/DT
#       Tstart     Tfreq
        0.0        0.001
/H3D/NODA/DISP
/H3D/NODA/ACC
/H3D/NODA/CONT
/H3D/NODA/CONT2
/H3D/NODA/MASS
/H3D/NODA/FINT
/H3D/PART
#  part_ID1  part_ID2  part_ID3 ...       (대상 파트 chassis_rear id, 한 줄 10개까지 — 전 부품이면 생략)
        10
```
- 추출 후 HyperView 결과 유형 표시명(예: "Contact Forces", "Acceleration")을 확인해 다르면 설정 `bforce.result_names` 에 이름을 더한다(코드 변경 불필요). 결과 유형이 없으면 그 종류는 '없음'으로 기록되고 등급이 내려간다(contact → full 은 CONT2 가 생기면 자동).

## 부록 B. 구현 반영 (2026-11-18, 계약과 다른 점·보충)
- B-1 화면 출처 표 `LOAD_SOURCES` 에 열 `pairKeys`(응답 쌍 3D 키 + 조건 줄 하중 문구)를 더했다 — 지그(view3d_jig*)·경계력(view3d_bf*)·전 노드(null). `View3dKind` += `pair`(진단 세그먼트 없는 응답 쌍), 칩 종류 += `bf`.
- B-2 순위표 주 열 이름: metric_effective `bf` = "경계력 C"(지그 = "지그 C" 와 같은 방식, DoeRanking).
- B-3 경계력 탭 비활성 사유 = 블록 사유(엔트리별 등급·`BF_NOT_FOUND`·`BF_GRADE_EXCLUDED`) 또는 "미계산 — Case 에서 h3d 추출·ESL 을 다시 실행한 뒤 [경계력 ESL 계산]", 다른 메시 계획 = 미지원 문구. 경계력 미계산 칩은 띠에 넣지 않는다(옛 스터디 띠 불변).
- B-4 하중 찾기 일치 조건 = 노드 ID 동일 ∧ u_rel 동일(atol 1e-9·max|u|) — 같은 Case·같은 t*·같은 모델의 ESL 다시 실행이면 성립.
- B-5 `pack_bforce` 는 CSV 형식 오류도 그 종류만 type null(추출 실패 아님).
- B-6 Case 단계 경계력 예외·재현 미달은 ESL 단계 경고 문자열(`BF_*: …`)로, 한계(`BF_TIE_MISSING`)는 경고가 아니라 요약 줄 문구.
- B-7 (BF-11) 비활성 탭 사유 줄(`doe-load-tab-why`)은 `.seg{overflow:hidden}` 밖 래퍼 `.doe-load-tabwrap`(relative) 안 절대 위치 — 높이 불변(2560×1440 결과 카드 높이 동일). 경고 `BF_SIGN_SUSPECT` 는 DOE 칩에서 엔트리 `sign_suspect` 로 경고색.
