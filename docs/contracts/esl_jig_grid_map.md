# 계약: 다른 메시 강성 스터디(④ 형상 직접 비교 · 옛 ③ STEP 안마다)의 지그 ESL — Case 지그를 3 mm 공통 격자로 형상마다 매핑 (JG, v0.24.8)

- 상태: 초안 → 구현 기준(2026-11-25) → 검토 개정 1 본문 반영(2026-11-25, §14 — 결정 JG-14·15). 브랜치 `release/v0.24.8`(base `release/v0.24.7` 74ab65ba = main 1d71d983 + v0.24.7 계약). 구현 코드 없음 — 이 문서가 원본. **v0.24.7(`esl_bead_depth_mode.md`)이 먼저 머지되므로 구현은 그 머지 위에 재기반**한다(§10.2 겹침 표).
- 관계: `esl_jig_rank.md`(D-0.23.0-JIG-1~19 — §5.2 계획 열 중 ④·옛 ③ 행의 `jig_fix`·`jig_ctx` 값만 바꿈), `esl_jig_case.md`(D-0.24.4-JIG — 3방식 `METHODS`·`TIE_DOFS`·§3.3 3-2-1 면내·§3.8 Π 지표를 그대로 재사용), `esl_validate_tiers.md` §12(v0.24.5 기본 방식 [prescribed, spring]·고정 숨김), `esl_viewer_hv.md` §8·§9(jd·js 3D·탭 사유), `esl_load_transfer.md`(LT-4 보존·LT-6 셀·LT-23 배치), `esl_stiffness_metric.md`(결정 A). 충돌하면 **새 스냅샷(`doe.rank.jig_grid` 있음)의 ④·옛 ③** 에서 이 문서가 우선.
- DB migration 없음. 새 값 = 스냅샷 `doe.rank.jig_grid`, 스터디 폴더 새 파일(`prep/jig_grid.json`·`prep/jig_grid/g<k>.npz`·`run/designs/<did>/jig_grid.json`), result.json `jig` 블록 새 키, API 응답 새 키(옛 결과 = null).
- ID: 결정 `D-0.24.8-JG-n`, 시험 `V-0248-JG-n`, 후속 `R-JG-n`, 미결 `Q-JG-n`.

### 사용자 원문 (변경 금지)
- "지그 esl이 모든 강성스터디에도 적용하라고 햇는데 왜 4번 형상직접비교는 안돼??"
- "메시옮긴다기 보다 매핑은 안되나 3mm 격자정도로"
- 확정(2026-11-25 "그래"): v0.24.7(깊이 동작) 다음에 v0.24.8로 ④·옛 ③에 지그 ESL을 3 mm 격자 매핑으로 넣는다.

배경(메인 전달): 현장 결론(11-24) — 하중만으로는 변형을 맞출 수 없고 변위·연결 경계가 필요(지그 변위 MAC 0.994, 스프링 0.994). 새 스터디 기본 지그 방식 [prescribed, spring], 지그 고정은 계산·표시 안 함(v0.24.5).

---

## 0. 감사 (release/v0.24.7 74ab65ba, 읽기만)

### 0.1 지그 계산 경로 (같은 메시 — 계획 `sm_jig = base`)
| 단계 | 지금 | 근거 |
|---|---|---|
| 게이트 | `_jig(c)` = 스냅샷 rank.jig ∧ enabled ∧ 계획 `sm_jig == "base"`. ④·옛 ③ 행 = `sm_jig/jig_fix/jig_ctx = none` → 모든 지그 함수 비활성 | `stages.py:3730-3735`, `transfer_plan.py:52-62`·`:151` |
| 공유 단계 | `_jig_stage`: J = `_jig_nodes`(fixed = `prep/fixed`, xfer = `prep/select/fixed_transfer.json`) → 참조 u = `prep/sm_ref.npz`(같은 노드 ID searchsorted) → deck 표면·영역 → 분해(TIE_DOFS 열: translation = `jig.factor`, normal = `jig_bc.tie_rows`·`aux_rows(t.supports)`·`build_bc`·`rigid_free`·`factorize`) → 모드 → 기저 → 기저 응답 | `stages.py:3935-4001`(sm_ref `:3954-3960`, 분해 `:3978-3989`) |
| 방식 | `_jig_methods_base` → `_jig_method_base`: 목표 frame 열(part = `jig_bc.kabsch_part(sm_ref)`), k = `spring_k(기준 K₀)` 1회, BC = `build_bc`, pattern_sha 같으면 분해 공유, `run_method` → per_esl `C_<pe> = per_esl_C(C_mix, C_mix, E)` = E_0, `prep/<src>.{npz,json}`(BC 배열·a·Cmix_ref·E_ref) | `stages.py:4381-4418`, `:4275-4378`(k `:4294-4296`, 공유 `:4298-4306`, 저장 `:4342-4352`) |
| 안 | `_jig_design_multi`: 기준 npz 의 a·BC·k 고정, **노드 ID 로 위치 맞춤**(다르면 `OUTPUT_INCONSISTENT`), 패턴 묶음당 분해 1, `C_<pe> = E_0 + (C_mix,d − C_mix,0)` | `stages.py:4421-4491`(`:4453-4459`, `:4480`) |
| 순수 모듈 | `jig_bc`: `tie_rows` 224 · `aux321_inplane` 245(형상 PCA 판 평면, n₁ 2 + n₂ 1 면내) · `build_bc` 320(u_tgt 의 tie·3-2-1 노드 값만 읽음) · `spring_k` 343(α·d̂ᵀK₀[n]d̂) · `rigid_free` 387 · `factorize` 466(축 방향만 = SpcSolve, 그 밖 `factorize_bc`, node_mmd) · `mixed_compliance` 558 · `per_esl_C` 584 · `respond` 647 · `support_marks` 670 · `pattern_sha` 706. `jig`: `node_weights` 104 · `target_disp` 210 · `support_sample` 1050 | `esl/mech/jig_bc.py`, `esl/mech/jig.py` |

→ 모든 단계가 "같은 노드 ID·같은 위상"을 가정(sm_ref·a·BC 인덱스) — 다른 메시에 그대로 쓸 수 없다(결정 A).

### 0.2 Case 지그 — 재사용할 출처
- Case ③ `pipeline._jig_esl`(`pipeline.py:1802`)·`_jig_method`(`:1703-1780`): `04_esl/<src>.npz` = {node_id, **f**(F_jig, A 노드), a, u_val(파트 Kabsch), **bc_node·bc_dir·bc_val·bc_kind·sp_node·sp_dir·sp_k·sp_g**(노드 인덱스), jig_idx, basis_sha}(`:1761-1763`), `<src>.json` = {tie_dofs, fit{mac, umax_err…}, recon{mac, umax_err}(vs u_rel), energy{C_mix, E…}, spring{k_mode, **alpha**, k_value}}(`:1742-1760`). 목표 = u_rel(S3 파트 Kabsch — part 프레임).
- 스터디가 Case 산출물을 찾는 공용 함수 `esl.library.source_load.find(key, meta, raw)`(`source_load.py:117-169`): 엔트리 스냅샷 → runs → 04_esl 순, raw `u_rel` 일치(`:140-153`) → f(엔트리 raw 노드 순서)·bc(노드 ID, `:162-164`). 스터디 선례 = 경계력·내력 `_ns_prep`(`stages.py:5263-5317` — find → `_plan_loads(srcs=…)` `:5300-5301` 로 기준 메시 전달).
- → Case 지그(맞춤 하중·tie 집합·구속 방향·g·α)는 이미 A 메시 위에 있고 같은 find 로 읽힌다. **새 맞춤 없이 사상만** 하면 된다.

### 0.3 체결점 이전 xfer (새 ③ step_once)
- `_jig_nodes` xfer(`stages.py:3786-3791`): `prep/select/fixed_transfer.json` node_id ∩ 기준 메시 → `select_jig_nodes`(종류 필터 없음, `JIG_FIX_UNFILTERED`). 생성 = `step_graph.fixed_transfer`(`step_graph.py:589-`): A fixed-scan(`prep/a_fixed`) 클러스터 → frame_check(구멍) ok = `_xyz_nearest`(`:485-529`: A 노드마다 B **최근접 1 노드** ≤ h, 클러스터 구멍 고리 검증) | 강체 맞춤 | 구멍 스냅. 출력 = B 노드 ID 합집합(노드별 방향·값 없음).
- 재사용 판단: **본 계산에 쓰지 않음** — (a) `esl.doe`·설정(DEFAULTS select.step_graph) 의존이라 순수 모듈 불가, (b) A 노드당 최근접 1개 → 형상이 더 촘촘하면 tie 띠가 성김, (c) 방향·값(g) 없음, (d) ④·옛 ③ 은 `prep/a_fixed` 를 준비하지 않음 — Case 지그가 실제 쓴 tie 집합이 더 정확. 구멍 고리 `hole_rings`(`:350`) 는 잡기 진단으로 재사용 가능(R-JG-2).

### 0.4 하중 셀 전달
- `load_transfer.cell_loads`(`load_transfer.py:474-526`): A ESL frame 정규화 칸 nx = max(1, round(L_ξ/s)), `nz.grid_summary`(칸 합력·모멘트) → 대상 frame 같은 (i,j) 칸 노드 최소노름(6 제약), 노드 < 3·공선 칸 = 그 칸 A 하중을 W(일 등가 사영)로. `transfer`(`:611-651`) 후 LT-4 `conserve`(`:417-431` 전체 합력·모멘트 = 원본). cell 은 같은 메시여도 셀(identity 경로는 work 만 `:619`). 공용 실행기 `run_transfer_plan`(`:661-688`), W 캐시 키(`:539-553`).
- 설정: `load_transfer.cell_choices_mm [None, 10, 5, 3]`·`cell_min_mm 3.0`·`diag.alt_cell_size_mm 3.0`(`esl/doe/__init__.py:228-236`), 범위 검사 `tp.resolve`(`transfer_plan.py:124-127`, CELL_MAX_MM 200).
- 배치: `place`(`:131-150`)·`unplace_points`(`:345-358`)·`placement_rotation`(`:361-368`) = global | rigid | frame. ④ 계획 placement global, 옛 ③ auto(BD_LOADS `_lt_decide_placement` `stages.py:2740` → `prep/input.json load_transfer.placement`).
- 주의: 셀 칸 대응은 **각 쪽 frame 정규화 좌표**(대상 = `dst.frame`)로 하고 배치를 쓰지 않는다(`_s_cell` `:584-588`). BC 표본은 배치 좌표를 써야 하므로 두 사상의 차를 진단한다(§1.5 frame_shift).

### 0.5 ④·옛 ③ 형상별 흐름 · 기준 · 순위 (지금)
- ④: BD_MESH0 `_cmp_mesh0`(`stages.py:2417`) → BD_LOADS `_cmp_loads_lt`(`:2962` — 기준 frame 고정, 형상 영역 LT-8 `prep/shapes/<did>/region.npz`, 지지 이전 LT-7 `prep/load_transfer.json shapes[].supports`) → BD_EVAL `_cmp_design_mesh`(`:2648`) → `_lt_design`(`:2928` 메시·영역·지지·`_plan_loads` per_target) → `_lt_eval`(`:3124` 3-2-1 해) → `_sm_apply`(sm_ref none → umax_def 만 `:3587-3589`). BD_POST `_cmp_post`(`:6038`): `rk.rank(metric_effective)`, `_jig_post`(`:6092`) = unsupported, **`_jig_extras` 호출 없음**(사이드카·rank_views·jd/js 3D 없음), matrix 없음(민감도 COMPARE_NO_PARAMS).
- 옛 ③(scn step): BD_LOADS `bd_loads`(`:349`) → `_lt_base_loads`(`:2834` 배치 auto) → BD_EVAL `_design_mesh`(`:574-589` paicad update BREP → gmsh → `sc.design_target` 자동 3-2-1 → `_lt_target_loads`) → `bd_post`: `_jig_post`(`:1037`) unsupported, `_jig_view3d`(`:1055`)·`_jig_extras`(`:1057`) = 미준비라 쓰지 않음.
- 기준·순위: 계획 sm_ref none·sm_rank solve → `tp.metric_effective`(`transfer_plan.py:242-247`) = solve, `cross_mesh` 참 → 경고 `SM_CROSS_MESH`(`stages.py:3466-3468`). 순위 값 = per_esl C(형상마다 전달 하중·자기 3-2-1 재풀이), score = max_i C_d,i / C_d000,i(BD-D-6 정규화 = 기준 d000). metric jig 이면 `JIG_UNSUPPORTED`(`:5724-5726`) + solve.
- 이어하기 해시: `_cfg_hash`(`:506-520`)가 compare 를 jig·sm 에서 뺌(`:509-515`), ④ 안 해시 = `_cmp_sha`(`:2597-2626`, cfg = `_cfg_hash`).
- API·화면: `services/doe.py:_plan_sm_jig`(`:1868-1876`) = 계획 sm_jig → `jig_plan` "none"(`:1975`) → `doeTabs.jigMethodState`(`doeTabs.ts:155`) "이 모드는 지그 ESL 을 계산하지 않습니다 … 복제해도 같습니다"(`JIG_STATE_TEXT.not_planned.whyMode` `:125-127`). `jig_on_clone` 은 지그 블록이 없을 때만(`services/doe.py:1973-1974`).

### 0.6 3D(v0.24.6 jd·js) 가 이 모드에서
- `_jig_v3d_sidecar`(`stages.py:5046`) → `_jig_view3d_src`(`:4593`) → `_jig_src_ready`(`:4242`, `_jig(c)` 필요) 거짓 → 키 없음. ④ 는 `_cmp_post` 가 `_jig_extras` 를 부르지도 않음.
- 본문 `_jig_v3d_build`(`:4613-4683`)·`_jig_view_mesh`(`:4566-4571` = t.mesh 위상 + 안 좌표)·`_jig_resp_rows`(`:4541-4551` = 저장 BC 를 노드 ID 로 옮겨 재풀이)는 같은 위상 가정 — 다른 메시엔 못 씀. 다른 메시 3D 선례 = `_view3d`(`:836-872`: 형상 메시·지지·하중을 **실행과 같은 함수**로 다시 만들어 해).
- 3D 다시 만들기 `_post_view3d`(`:5121-`)는 `_matrix(c)`·`_jig_extras(v3_src=…)` — ④ 는 matrix 가 없다.

### 0.7 결론
1. ④·옛 ③ 은 계획 표가 지그를 막고(sm_jig none) 화면이 "계산하지 않음"을 정직하게 보인다. 막힌 이유 = 노드 ID 기반 재사용.
2. 재료(Case 지그 F_jig·tie·g·α, A 메시·u_rel, 셀 하중 전달, 배치, 3방식 해·Π, 3D 사이드카)는 다 있다. 없는 것 = **메시 독립 사상**(tie 를 형상 노드로 잡기, g·3-2-1 값을 형상 좌표에서 읽기)과 형상마다 실행·기준 E_0.

---

## 1. 공통 격자 정의 (D-0.24.8-JG-2~4)

### 1.1 좌표계 · 배치
- 격자 frame G = 엔트리 ESL frame F_A(`e.meta.frame` — 원 Case 메시 A 기준 `nz.frame`: origin, e_ξ, e_η, n, a/b/z_range, L_ξ, L_η). **A 기준 정규화**.
- 칸: nx = max(1, round(L_ξ/s)), ny = max(1, round(L_η/s)), Δξ = L_ξ/nx, Δη = L_η/ny(≈ s) — 기존 셀 하중 칸과 **같은 수식**(`cell_loads:481-482`) → 하중 칸 = 격자 칸. 층 Δζ = s, k = floor((ζ − z_range[0])/s). 복셀 키 (i, j, k): i·j = `nz.cell_index` 와 같은 floor(+BOUNDARY_EPS)·clip, k 는 clip 없음.
- 배치(LT-23 값 한 곳 — 그 모드 하중 전달과 같은 값 `_lt_placement(c, plan)`: ④ global, 옛 ③ `prep/input.json`): 형상 점 y → A 좌표 ŷ = `unplace_points(y)`, 벡터(변위·법선) 회전 R_pl = `placement_rotation`(global = I). **global 이면 형상 좌표 = A 좌표**.
- 하중 = 기존 셀 규칙(각 쪽 frame 정규화 칸, 배치 무관), BC 표본 = ŷ. 두 사상 차 frame_shift_mm = max_{tie·3-2-1 노드} ‖ŷ − to_global(F_A, local(F_dst, y))‖ → 정보 `JIG_GRID_FRAME_SHIFT`(> frame_shift_warn·s). ④(같은 frame·global) ≈ 0.

### 1.2 격자에 올리는 값 (A 쪽 — BD_LOADS 1회, 원천 묶음 g 마다)
원천 = 엔트리마다 Case 지그 `source_load.find(src, meta, raw)`(src = `METHODS[m].src`, m ∈ 스냅샷 rank.jig.methods — 기본 jig_disp·jig_spring), A 메시·u_rel = 엔트리 raw. 묶음 g = (mesh_sha(raw), tie 집합 sha, tie_dofs, 스프링 파라미터(Case json spring{k_mode, alpha, k_value} — 스프링 출처가 있을 때, 없으면 null)) 가 같은 엔트리. 파라미터가 다른 엔트리는 다른 묶음.

| 값 | 정의 | npz 키 |
|---|---|---|
| 맞춤 하중 | Case `<src>.npz f`(엔트리 raw 노드 순서) — 형상 사상은 §1.3-1 | `f_<src>` (K_g, N_A, 3) |
| 셀 합력·모멘트 | `nz.grid_summary(X_A, f, nx, ny, F_A)` cell_F_loc·cell_M_loc(기존 셀과 같은 함수) — 진단 | `cellF_<src>`·`cellM_<src>` |
| 복셀 변위장 | U_v = Σ_{n∈v} A_n u_n / Σ A_n, u = 프레임 열(`METHODS.frame`)마다: part = u_rel, jig_kabsch = `jig.target_disp(X_A, u_rel, J_A, fit).u_tgt`(fixed 가 방식에 있을 때만) | `vox_u_<frame>` (K_g, V, 3) |
| 복셀 기하 | 중심 X_v = ΣA·x/ΣA, 법선 N_v = Σ A m mᵀ 최대 고유벡터(부호 = 최대 절댓값 성분 +), 면적 A_v(A_n·m = `jig.node_weights(A)`) | `vox_key`(V,3)·`vox_x`·`vox_n`·`vox_a` |
| tie 골격 | 점 P = Case tie 노드(bc_kind = KIND_TIE 의 bc_node ∪ sp_node, 정렬·중복 제거), 변 = 양 끝이 P 인 A 요소 변, 면 = 꼭짓점이 모두 P 인 A 요소(쿼드 → (0,1,2)(0,2,3)), 클러스터 q = P 의 요소 변 연결 성분, 노드 면적 | `tie_x`·`tie_seg`(S,2)·`tie_tri`(T,3)·`tie_q`·`tie_area` |
| tie 방향·값 | Case 구속 방향(노드당 ≤ 3, bc_dir/sp_dir)·랭크, u(프레임 열마다) | `tie_dir`(P,3,3)·`tie_rank`·`tie_u_<frame>`(K_g,P,3) |
| 스프링 면적 밀도 | 스프링 출처(`METHODS.tie_stiff = spring` 열 — 지금 jig_spring)만: 골격 점마다 κ_P = Σ_{행 r: sp_node_r = P} sp_k_r / A_P(N/mm³, A_P = `tie_area`) | `tie_kappa_<src>` (P) |
| 스프링 클러스터 합 | K_q = Σ_{P∈q} Σ_행 sp_k(N/mm) — 형상에서 보존할 값 | `tie_kq_<src>` (Q) |
| 척도 | h_T = P 에 닿는 A 변 길이 중앙값 | `h_T` |
| A 3-2-1 점 | Case 3-2-1 위치(진단만 — 형상은 재선정) | `sup_x`(3,3) |
| 방식 파라미터 | Case json tie_dofs·spring{k_mode, alpha, k_value}(**기록만** — 격자 경로는 k 를 다시 계산하지 않음, §1.3-6)·fit{mac, umax_err}·recon{mac, umax_err}·energy{C_mix, E}·npz sha256 | `prep/jig_grid.json` |

- 복셀 = A 노드가 있는 칸만(V ≈ 면적/s²), 키 사전순 — 결정적. 골격 = 노드 인덱스 순.
- **Case 스프링 행 형식**(읽는 쪽 근거 — `pipeline._jig_method` 저장 `pipeline.py:1761-1763` = `jig_bc.save_bc(BC)`, BC = `jig_bc.build_bc` `jig_bc.py:320-340`): 스프링 방식은 tie 행이 구속(bc_*)이 아니라 스프링 행 `sp_node (r,) int64`(A 노드 인덱스)·`sp_dir (r,3)`·`sp_k (r,)`(N/mm, 행마다 > 0)·`sp_g (r,)`(바닥 = d̂·u_tgt)이고, bc_* 에는 3-2-1 면내(KIND_AUX) 행만 있다. 행은 `tie_rows` 순서 그대로 = 정렬된 tie 노드마다 연속 r_n 행(`node_frames` `jig_bc.py:209-216`): tie_dofs normal → r_n = 그 노드 법선 랭크(평판 1·꺾임 2·모서리 3, λ_k ≥ τλ₁, τ = tan²(kink_deg/2); 고립 = 3축), translation → r_n = 3(전역 3축). Case k = `spring_k(sm, tie, mode, alpha, value)`(`pipeline.py:1869-1870`): auto = 행마다 α·d̂ᵀK₀[n]d̂ — **같은 노드의 행끼리도 값이 다름**, value = 모든 행 같은 값.
- prescribed(jig_disp)·fixed(jig) 출처는 tie_stiff hard → `sp_*` 길이 0(`jig_bc.py:334`) — **k 가 없다**. 그 출처에는 `tie_kappa_*`·`tie_kq_*` 키를 두지 않고, 격자 경로도 k 를 만들지 않는다(build_bc k = None).
- κ·K_q 는 묶음마다 1벌((P)·(Q)) — 묶음 키에 스프링 파라미터가 있어 같은 묶음 안 sp_k 는 같아야 한다. 묶음의 첫 엔트리(엔트리 순서) sp_k 로 κ·K_q 를 만들고, 다른 엔트리 sp_k 가 행마다 상대 1e-9 를 넘게 다르면(같은 sp_node·sp_dir 순서 비교) **그 엔트리만** 그 방식 fallback — 경고 코드 `JIG_GRID_SOURCE_MISSING`(같은 등급, 새 코드 없음), reason = "같은 묶음인데 Case 스프링 k 가 다름(최대 상대차 {d:.2e})". 묶음 키의 tie 집합 = 스프링 출처는 unique(sp_node), 그 밖 bc_node[bc_kind = KIND_TIE](같은 Case 에서 둘은 같은 집합).

### 1.3 형상이 격자에서 값을 가져가는 규칙 (형상 S — BD_EVAL 마다, 기준 d000 포함 같은 규칙)
1. **맞춤 하중**(합력·모멘트 보존): F_S = 기존 하중 자리 `_plan_loads(c, plan, did, dst_S, ("cell", s), cache, srcs=[ltm.src_load(eid, raw, f_<src>[i], F_A)])` — `cell_loads` + LT-4 `conserve`(합력·모멘트 = A 값). dst_S = 그 형상 ESL 하중과 같은 dst(영역 마스크·frame·h — `c._lt_last`), W 캐시 공유(같은 원본 메시 sha). s ≈ 형상 h(3 mm)이면 칸 대부분 노드 < 3 → 그 칸 A 하중은 W(일 등가) — 기존 셀 규칙 그대로(`small_frac` 로 보임). 보존 후 dF_rel 또는 dM_rel > `load_resid_warn` = 경고 `JIG_GRID_LOAD_RESID`(계산 계속).
2. **tie 잡기**(구멍 가장자리·반경·법선): 형상 노드 ŷ 의 골격 거리 d = min(점·변·면 정확 거리 — 후보 = cKDTree(P) 반경 r_cap + 최대 골격 변 길이, 점-삼각형 = Ericson).
   - r_cap = `tie_capture_rel` × max(h_T, h_S), h_S = 골격 점에서 2·h_T 안 형상 노드에 닿는 형상 변 길이 중앙값.
   - 띠(band): d ≤ r_cap ∧ 법선 맞음 → 잡음. 법선 맞음 = 형상 노드 법선(`node_weights(S).normal`, R_plᵀ 로 A 좌표)이 최근접 골격 점 구속 방향 중 하나와 |·| ≥ cos(`tie_normal_deg`) — 옆 플랜지·벽 노드 제외(`n_reject_normal`).
   - 클러스터 q 에 띠 노드 0 → 법선 맞는 형상 노드 중 q 점까지 최근접 1개(≤ `tie_snap_rel` × max(h_T, h_S)) 잡음(snap). 그래도 0 = miss.
   - 형상 tie 행 = `jig_bc.tie_rows(mesh_S, idx, td, kink_deg)` — **구속 방향 = 형상 자기 법선**(td = Case tie_dofs, kink_deg = 스냅샷 rank.jig.normal_kink_deg). A 법선은 잡기 판정에만.
   - 클러스터 진단: n_a·n_s·면적비 a_q = Σ_S A / Σ_A A·via(band|snap|miss)·스프링 배율 c_q(6.). a_q ∉ [1/`area_ratio_warn`, `area_ratio_warn`] = 정보 `JIG_GRID_AREA_RATIO`. miss ≥ 1 = 경고 `JIG_GRID_TIE_MISS`, miss 클러스터 비 > `tie_miss_frac_max` = **그 형상 그 묶음 방식 실패**(per_esl null, 같은 코드).
3. **강제 변위 g**(Kabsch 강체 제거 u_rel 의 tie 구속 방향 성분): ũ(ŷ) = 골격 보간(최근접 골격 요소: 면 = 무게중심, 변 = 선형, 점·snap = 그 값) of `tie_u_<frame>`, g_r = d̂_r · R_pl ũ(형상 tie 행 r). A 를 형상으로 넣으면 tie 노드 = 골격 점 → g 정확.
4. **3-2-1 재선정**: 형상 자기 3-2-1 = 그 형상 순위 해에 쓴 지지(④ `_lt_design` 지지 — d000 auto·형상 LT-7 이전, 옛 ③ `design_target`) → `jig_bc.aux_rows(X_S, spc_of(mesh_S, sup_S), tie_S, td, dup_deg)`(판 평면 = 형상 PCA — 다른 출처와 같은 3-2-1, esl_jig_case §3.3). 값 = d̂·R_pl ũ(ŷ)(5. 복셀 표본 — 면내 강체 위치만 정하고 변형·에너지는 불변). A 3-2-1 점과 거리 = 진단 `sup_shift_mm`.
5. **복셀 표본(노드 보간)** ũ(ŷ): 이웃 (2·`sample_nbr`+1)³ 복셀 중 |N_v·m_S| ≥ cos(`sample_normal_deg`)(없으면 법선 조건 없이 + `n_normal_relax`), w_v = A_v·exp(−(‖X_v − ŷ‖/s)²), 접평면(m_S ⊥ 의 t1, t2) 2D 선형 가중 최소제곱 u ≈ c + B·[(X_v−ŷ)·t1, (X_v−ŷ)·t2] → c. 후보 < 3 이거나 모멘트 행렬 최소 고유값 < (0.1·s)²·Σw = 가중 평균(`n_const`). 후보 0 = 이웃 ×2 한 번(`n_expand`), 그래도 0 = **격자 밖**(값 0, `n_outside`, 정보 `JIG_GRID_OUTSIDE`).
6. **스프링 k = 설계 무관**(D-0.24.8-JG-14 — 스프링 = 이웃 부품 강성이라 설계가 바꿀 수 없는 값; 같은 메시 스터디가 k 를 기준 K₀ 로 1회 구해 모든 안에 고정하는 규칙 `stages.py:4294-4296` 과 같은 뜻). 스프링 출처만, 엔트리마다:
   - 형상 tie 행 = 2.의 `tie_rows(mesh_S, idx, td, kink_deg)` — 잡힌 노드 n 의 행 수 r_n = **형상 자기** 랭크(형상이 꺾인 곳이면 2, A 의 랭크와 무관).
   - 1차 값: k̃_{n,r} = κ(ŷ_n)·A_S,n / r_n(그 노드 행에 **균등 분배**). κ(ŷ) = 3.의 ũ 와 같은 골격 보간(같은 cap.elem·bary — 면 = 무게중심, 변 = 선형, 점·snap = κ_P), A_S,n = `jig.node_weights(mesh_S).area`.
   - 클러스터 합 보존: 클러스터 q(잡힌 노드의 cap 클러스터)마다 c_q = K_q / Σ_{n∈q} Σ_r k̃_{n,r}, k_{n,r} = c_q·k̃_{n,r} → Σ_S k = K_q(정확, 고정 합 순서). snap 1노드 클러스터 = K_q 전부(그 노드 r_n 행에 K_q/r_n). miss 클러스터 = 행 없음(K_q 버림 — 2.의 실패 규칙이 판정).
   - `jig_bc.spring_k` 는 격자 경로에서 **부르지 않는다**(형상 강성 K_S 불필요 — `shape_bcs` 인수에 sm_S 없음). Case k_mode·α·k_value 는 기록만(F_jig·sp_k 가 이미 그 값으로 만들어짐).
   - 항등: A 를 형상으로 넣으면 c_q = 1, 노드 행 합 Σ_r k_{n,r} = Case Σ_r sp_k(≤ 1e-12 상대). **행별 같음은 노드의 Case 행 k 가 서로 같을 때만**(r_n = 1 노드, k_mode value) — auto 모드의 r_n ≥ 2 노드는 Case 행 k 가 방향마다 다르고 형상 쪽은 균등 분배라 행별 값이 다르다(노드 합은 같음, §4.1).
   - 진단 `k_scale_min/max` = min/max_q c_q(방식·엔트리 최악) — §1.5 tie 줄(`JIG_GRID_AREA_RATIO` 와 같은 줄).
   - prescribed·fixed = k 없음(k = None).
7. **BC** = `jig_bc.build_bc(METHODS[m], tie_S, aux_S, u_tgt_S, k = 6.의 k(스프링 출처) | None)`(u_tgt_S = tie·3-2-1 노드에만 R_pl ũ, 그 밖 0 — build_bc 는 그 노드만 읽음, 함수 불변). k 길이 = tie_S 행 수(build_bc 검사 `jig_bc.py:336-337`).
8. **해**: `rigid_free(X_S, components(mesh_S), BC)` > 0 = `JIG_SUPPORT_DEGENERATE`(그 형상 그 방식 실패). 같은 pattern_sha 방식끼리 분해 1(`jig_bc.factorize` — fixed·prescribed 공유, spring 자체), 엔트리마다 `jig_bc.respond(h, F_S, BC)` → C_mix·E·W_F·W_g·R_sum, umax(Ω = 계획 sm_omega)·umax_ev, `aux_reaction_rel`. 다음 패턴 전에 분해를 놓음(피크 = 분해 1).

### 1.4 실패 · 경고 · 정보 코드 (새 9개 = JIG_GRID_* 8 + 정보 JIG_GRID_RANK — 원본 `resources/doe_messages.json`, 화면 대체 `api/doe.ts`)
| 코드 | 등급 | 위치 | 조건 → 결과 |
|---|---|---|---|
| `JIG_GRID_SOURCE_MISSING` | 경고 | prep | 엔트리 Case 지그(그 방식) 없음·status ≠ ok(find 사유 그대로 detail) → 그 방식 fallback(전 형상 null). 같은 묶음 안 스프링 k 불일치(§1.2)도 이 코드 — 그 엔트리만 fallback, reason 문자열로 구분. 문구(조치 포함): "엔트리 <이름> 의 Case 에 {방식} 지그 결과가 없습니다 — 그 Case 에서 ③ ESL 을 다시 실행(v0.24.4 이후)한 뒤 스터디를 복제하세요. 지금은 재풀이(solve) 순위입니다". 방식 일부만 없으면 있는 방식으로 진행, 순위 출처 = ok 인 첫 방식(§3) — 모든 방식이 없을 때만 solve |
| `JIG_GRID_TIE_MISS` | 경고 | 형상 | 골격 클러스터를 형상에서 못 잡음(n_miss/n_clusters). 비 > tie_miss_frac_max = 그 형상 그 방식 실패 |
| `JIG_GRID_OUTSIDE` | 정보 | 형상 | 3-2-1 표본이 격자 밖(값 0 — 면내 강체 위치만 영향) |
| `JIG_GRID_LOAD_RESID` | 경고 | 형상 | 보존 후 합력·모멘트 오차 > load_resid_warn(계산 계속) |
| `JIG_GRID_AREA_RATIO` | 정보 | 형상 | tie 잡힌 면적비가 [1/r, r] 밖 |
| `JIG_GRID_FRAME_SHIFT` | 정보 | 형상 | 하중 칸(frame 정규화)과 BC 표본(배치) 위치 차 > frame_shift_warn·s |
| `JIG_GRID_CONV` | 정보 | post | d000 격자 크기 민감도 |ΔΠ|/E_0 > conv_warn(§4.2) |
| `JIG_GRID_NO_REF` | 경고 | 형상·post | d000 격자 지그 실패·없음 → 그 방식 C_<pe> 기준 없음(안 null) |
| (재사용) `JIG_SUPPORT_DEGENERATE`·`JIG_DESIGN_FAILED`·`JIG_FIT_POOR`(Case fit 값으로)·`JIG_LOAD_CANCEL` | 기존 | | 기존 뜻(실행기 예외 = `JIG_DESIGN_FAILED{did, err}`, 그 형상만) |
| `JIG_GRID_RANK` | 정보 | post | 순위 = 격자 지그(다른 메시 — 매핑 진단 참고). 이때 `SM_CROSS_MESH`(solve 문구) 대신 |

### 1.5 매핑 오차 진단 (결과에 둠 — 실패 아님)
형상마다 `run/designs/<did>/jig_grid.json map{…}`, 스터디 요약 = result.json `jig.grid`(최악값):
- load: 방식·엔트리마다 dF_rel_before·dM_rel_before·dF_rel·dM_rel·corr_rel·small_frac·n_cells_loaded(ltm 행 그대로).
- tie: n_clusters·n_miss·n_snap·n_reject_normal·r_cap_mm·h_S·면적비 min/max·k_scale_min/max(스프링 출처만, §1.3-6 c_q)·잡힌 노드 수.
- sample: n_pts·n_const·n_expand·n_outside·n_normal_relax·max_dist_mm, frame_shift_mm·sup_shift_mm.
- d000 만: recon(기준 재현) = u_S(파트 Kabsch 제거)와 ũ_rel(형상 노드 복셀 표본)의 MAC·umax_err(`bforce.recon_report` 와 같은 정의) + Case recon MAC 나란히, conv(§4.2).

---

## 2. 모듈 구조 (AGENTS.md — D-0.24.8-JG-5·6)

### 2.1 순수 모듈 `esl/mech/grid_map.py` (신규, 모드 무관)
- import 허용: numpy · scipy.spatial(cKDTree) · scipy.sparse.csgraph · `esl.errors` · `esl.library.normalize`(frame·local_coords — numpy·esl.errors 만) · `esl.mech.{jig, jig_bc, kabsch, shell, bforce}`(bforce = recon_report 만). **금지**: `esl.doe.*`(load_transfer 포함), 파일 IO, 설정 해석(값은 키워드 인수), 시나리오·계획 이름. 정적 import 그래프 시험(V-0248-JG-19).
- 상수: `SCHEMA = "esl/doe_jig_grid/1"`, `RUN_SCHEMA = "esl/doe_jig_grid_run/1"`, `VIA_BAND, VIA_SNAP = 1, 2`, `HASH_EXCLUDE = ("area_ratio_warn", "conv_warn", "frame_shift_warn", "load_resid_warn", "conv_mm", "noise_floor_min")`.

| 함수 | 시그니처 · 뜻 |
|---|---|
| `grid_frame` | `(frame_A, cell_mm) -> GF{origin, e_xi, e_eta, n, a0, b0, z0, nx, ny, dxi, deta, dz}` §1.1 |
| `vox_key` | `(GF, X) -> (N,3) int64` |
| `build_field` | `(GF, X_A, weights_A, U: {frame: (K,N,3)}) -> Field{key, x, n, a, u{frame}}` §1.2 |
| `tie_skeleton` | `(mesh_A, tie_idx, tie_dir, tie_rank, U_tie: {frame: (K,P,3)}) -> Skel{x, seg, tri, q, area, dir, rank, u, h_T}` |
| `skel_spring` | `(skel, sp_node, sp_k) -> {kappa (P,), kq (Q,)}` — 묶음 대표 엔트리의 Case 스프링 행(A 노드 인덱스, 행마다 k)을 골격 점별 합 / A_P · 클러스터 합으로(§1.2). sp_node 가 골격 점 밖이면 INPUT_INVALID |
| `shape_spring_k` | `(skel, cap, tie_S, area_S, kappa, kq) -> {k (r,), c_q (Q,), k_scale_min, k_scale_max}` — §1.3-6(κ 골격 보간 → κ·A_S,n / r_n → 클러스터 배율 c_q, snap = K_q/r_n). r = tie_S 행 수, 행 순서 = tie_S |
| `capture` | `(skel, mesh_S, Xs_A, R_pl, *, capture_rel, snap_rel, normal_deg) -> Cap{idx, elem_kind, elem, bary, dist, via, clusters[{q, n_a, n_s, area_a, area_s, via, miss}], n_reject_normal, r_cap, h_S}` §1.3-2 |
| `sample_tie` | `(skel, cap, frame, k) -> (m,3)` A 좌표 값(골격 보간) |
| `sample_field` | `(field, GF, Xq_A, mq_A, frame, k, *, nbr, normal_deg) -> {u (q,3), n_const, n_expand, n_outside, n_normal_relax, max_dist}` §1.3-5 |
| `shape_bcs` | `(mesh_S, sup321_idx, cap, skel, field, GF, R_pl, Xs_A, *, methods, entries, params, kink_deg, dup_deg) -> {groups{sha: [(m, k, BC)]}, tie, aux, diag}` §1.3-2~7 (값 = build_bc 그대로; 스프링 k = `shape_spring_k` — 형상 자기 강성 경로 없음, sm_S 인수 없음) |
| `run_shape` | **공용 실행기** `(mesh_S, sup321_idx, loads: {src: [(eid, F)]}, skel, field, GF, R_pl, Xs_A, *, methods, params, cfg, solver_cfg, spring: {src: (kappa, kq)} | None = None, omega=None, ev_mask=None, keep_u=False, values=None) -> {methods{src: {status, code, rows{eid: {C_mix, E, W_F, W_g, R_sum, umax, umax_ev?, aux_reaction_rel}}, pattern_sha, shared}}, map{tie, sample}, factor{n, seconds}, u?{src:{eid}}, bc{src}}` — 분해는 패턴 묶음마다 1, `values` = 같은 BC 패턴에 다른 값·하중 묶음(수렴 진단 — 분해 재사용) |
| `recon` | `(X_S, u_S, ut_S, omega) -> {mac, umax_err}` — `esl.mech.bforce.recon_report` 호출(재구현 금지) |
| `hash_view` | `(grid_cfg_raw) -> dict`(HASH_EXCLUDE 뺀 사본 — **스냅샷 원본 키만**, 설정 병합 전: D-0.24.5-VT-16 교훈) |

- 결정적: 같은 입력 → 비트 동일(정렬 키·동률 = 작은 인덱스, cKDTree 결과 정렬, 고정 합 순서). 메모리 O(N_S + P + V + 청크·k) — N_S×P 배열 금지.

### 2.2 계획 표 (`esl/doe/transfer_plan.py`) — 모드 차이는 열 값으로
| 계획 행 | sm_jig | jig_fix | jig_ctx | 뜻 |
|---|---|---|---|---|
| case_once·bmesh_once·step_once | base | fixed·fixed·xfer | case·mesh·none | **그대로(값·산출물 바이트 불변)** |
| step_per_design(옛 ③) | none | none → **grid** | none → **shape** | 형상마다 격자 지그 |
| compare_per_shape(④) | none | none → **grid** | none → **shape** | 형상마다 격자 지그 |

- `JIG_VALUES` 확장: jig_fix += "grid", jig_ctx += "shape". 새 뜻: `jig_fix = grid` = tie 출처가 Case 지그 골격을 형상에서 잡기(§1.3-2), `jig_ctx = shape` = 가압 하중 문맥이 Case 맞춤 하중의 형상 셀 전달(deck·영역 재계산 없음).
- `plan_for` 불변식(위반 = CONFIG_INVALID): `jig_fix = grid ⇔ jig_ctx = shape`, `jig_fix = grid ⇒ sm_jig = none ∧ sm_ref = none ∧ dst ∈ {design, shape}`, `sm_jig = base ⇒ jig_fix ∈ {fixed, xfer} ∧ jig_ctx ∈ {case, mesh, none}`. PLAN_VERSION·hash_view 불변.
- 새 함수 한 곳 `jig_kind(plan, grid_snap: bool) -> "base" | "grid" | "none"`: base = sm_jig base, grid = jig_fix grid ∧ grid_snap(스냅샷 rank.jig enabled ∧ rank.jig_grid enabled), 그 밖 none. 코어 `_jg_kind(c)`·백엔드 jig_plan 이 이 함수만 부름.
- `metric_effective(plan, metric, jig_ok=True, kind=None)`: kind None = 지금 식(기존 호출 바이트 동일), kind "grid" ∧ metric jig ∧ jig_ok → "jig", 아니면 기존 식. `cross_mesh` 불변.
- 호출부(stages)는 열·`jig_kind` 값만 읽음 — 시나리오 이름 분기 0(정적 시험).

### 2.3 stages 통합 (공용 실행기 1개 + 훅)
- `_jg_kind(c)` = `tp.jig_kind(_lt_plan(c), grid_snap)`, `_jg_cfg(c)` = 스냅샷 rank.jig_grid(원본)를 설정 기본 위에 병합(계산용), 해시는 원본.
- **`_jg_prep(c, t, bmeta)`**(BD_LOADS — ④ `_cmp_loads_lt` 끝·옛 ③ `bd_loads` 끝, `_jg_kind == grid` 일 때만): 엔트리·방식마다 find → 묶음 → `grid_frame`·`build_field`·`tie_skeleton`(+ 스프링 출처 묶음마다 `skel_spring` 1회·묶음 안 sp_k 일치 검사 §1.2) → `prep/jig_grid/g<k>.npz` + `prep/jig_grid.json`. 예외·없음 = 그 방식 fallback(`JIG_GRID_SOURCE_MISSING`) — BD_LOADS 실패로 만들지 않음.
- **`_jg_shape(c, t, did, mesh, sup, region, *, sizes=(s,), keep_u=False)` = 공용 실행기 어댑터 1개**(평가·d000 수렴·3D·다시 만들기 모두 이것만): 배치·R_pl·ŷ(`ltm` 함수), 방식·엔트리 하중(`_plan_loads(…, ("cell", s), srcs=…)` — 크기마다), `grid_map.run_shape`. 형상 메시·지지·영역은 호출자가 그 모드의 실행 함수로 준 값(④ `_cmp_design_mesh`, 옛 ③ `_design_mesh`/저장 design) — 3D 도 같은 함수(`_view3d` 선례).
- 훅: `bd_eval`(`:655-659`) `if _jig(c) … elif _jg_kind(c) == "grid": r["warnings"] += _jg_apply(c, t, did, mesh, sup, loads, reg_e, r)` — per_esl 키(§3), `run/designs/<did>/jig_grid.json`, d000 이면 `c._jig_status`(result.json sm.jig, 방식별). 예외 = 그 형상 키 null + `JIG_DESIGN_FAILED`(d000 = 경고 + 방식 fallback — `BASELINE_FAILED` 금지).
- 준비 판정 `_jg_ready(c, src)` = prep 방식 ok ∧ d000 jig_grid.json 그 방식 ok. `_sm_post`(`:3405`)·`_jig_any_ready`·`_jig_extras` 의 `_jig(c)` 조건을 `_jg_kind(c) != "none"` 분기로(지그 종류 열 값 — 이름 분기 아님).
- BD_POST: `_jig_post`(`:5682`) 앞에서 `_jg_kind == grid` 면 `_jg_post`(§6 블록). `_cmp_post` 에 `_jig_extras` 호출 추가(**grid 일 때만** — 옛 ④ 바이트 불변), ④ matrix 없음 → `_jig_extras`·`_rank_views`·`_post_view3d` 는 m = None 을 받아 민감도 null·사유 COMPARE_NO_PARAMS, 형상 이름 = `rk.attach_shapes`. `_jig_v3d_sidecar` 는 지그 종류 값으로 빌더를 고름(base = `_jig_view3d_src`, grid = `_jg_view3d_src`).
- CSV: `_jig_csv_arg`(`:807-819`) 조건 `sm_jig != base` → `_jg_kind(c) == "none"` 로, `_cmp_ranking_csv`(`:5846`) 에 pes 끝 열(C_jd·umax_jd·C_js·umax_js) — grid 스냅샷만.
- 보고서 `report_doe.py` 강성 지표 절 1줄(격자 크기·기준 d000·d000 재현 MAC·잡기 miss 최대).

---

## 3. 순위 (D-0.24.8-JG-7)
- **기준 E_0**: 기준 형상(④ = 기준 shape d000, 옛 ③ = d000)에 같은 격자 지그를 풀어 엔트리·방식마다 C_mix,0·E_0 → `run/designs/d000/jig_grid.json`. 안 = 그 값을 읽어 per_esl `C_<pe> = E_0 + (C_mix,d − C_mix,0)`(`jig_bc.per_esl_C` — esl_jig_case §3.8 그대로), d000 은 C_<pe> = E_0(score 정확히 1). 키 = `C_<pe>·umax_<pe>·WF_<pe>·Wg_<pe>(·umax_<pe>_ev)`(pe = jd·js·jig — 격자는 항상 새 에너지 경로 키).
- 순위 = 기존 BD-D-6(`stiffness_metric.score` 최악 엔트리 비) 그대로. 단조성 정리(같은 이산화)는 다른 메시에서 근사 — 수렴·매핑 진단으로 보임(§4).
- **순위 출처 = ok 인 첫 방식**(D-0.24.8-JG-15): 지금 `_jig_rank_src(c)`(`stages.py:4202-4208`)는 스냅샷 방식 목록의 첫 방식 출처를 상태와 무관하게 돌려준다 — base 모드는 그대로 둔다(바이트 불변). grid 일 때만 출처 = 스냅샷 방식 순서에서 `_jg_ready(c, src)` 가 참인 첫 방식(기본 [prescribed, spring] → jig_disp, 없으면 jig_spring), 하나도 없으면 None → solve. 같은 값을 `_sm_post`(`:3405`)와 출처 행 need 조회(`:4977`)가 함께 쓴다(분기 = `_jg_kind` 값).
- `_sm_post`: metric jig ∧ kind grid → jsrc = 위 출처, jig_ok = jsrc is not None, `metric_effective(plan, metric, jig_ok, kind="grid")` → "jig" → 출처 행 metric(jd 또는 js). 실패 = solve(지금 규칙).
- **불확실 구간 표식**(D-0.24.8-JG-15): 격자 순위(metric_effective = jig ∧ kind grid)일 때 `rk.rank(noise_floor=nf)`, nf = max(방식·엔트리 최악 ΔΠ_5(§4.2 — conv_mm 중 가장 작은 크기, 기본 5 mm), `noise_floor_min`, 옛 ③ 의 기존 메시 잡음 바닥(NOISE 안 C_max 비 `stages.py:998-1004` — 있을 때만)). d000 수렴 진단이 없으면(conv_mm 빈 값·실패) ΔΠ_5 항을 뺀다. 이 값이 n_improved·all_improved 판정 tol 도 바꾸는 것은 의도(정렬 불변). 기존 장치 그대로: 행 `noise = |improvement| < nf`(`rank.py:224`), ESL별 개선 판정 tol = max(ratio_tol, nf)(`rank.py:102-105`·`:177` — n_improved·all_improved 도 같은 tol), 최상위 `noise_floor`·`ratio_tol`(`:253`). 정렬(score)은 불변. 같은 nf 를 격자 출처 보기(jd·js `_rank_view_one` `:4997`)에도 넘긴다. solve 대체 순위·base 모드·옛 스냅샷 = 지금 인수 그대로(④ `noise_floor=None` `:6055`, 옛 ③ 메시 잡음 바닥 `:998-1004`).
- 경고: grid 순위면 `SM_CROSS_MESH` 대신 정보 `JIG_GRID_RANK`, solve 면 `SM_CROSS_MESH` 그대로(옛 스냅샷 바이트 동일). 기존 solve 지표(per_esl C·score_solve·전 노드 탭)는 그대로 산출·표시(**함께 표시**).
- 방식끼리 분해 공유 = 형상 안 pattern_sha 묶음(fixed·prescribed 1, spring 1 — 묶음 안 sp_k 는 같으므로(§1.2) 엔트리 수와 무관; 형상 tie 는 묶음 골격마다 잡으므로 묶음이 여럿이면 묶음마다 분해). ShellModel 조립·잡기·표본·하중 W 는 형상 안 모든 방식·엔트리 공유.
- d000 지그 실패 → 그 방식 안 전부 null + `JIG_GRID_NO_REF` 1건, 첫 방식이면 순위 = solve.

---

## 4. 항등 · 정확도 검사 (D-0.24.8-JG-8)

### 4.1 항등 — A 메시를 형상으로 넣으면 Case 지그 결과와 같아야 함 (V-0248-JG-2, s = 3 mm, 격자 경로 그대로 — 지름길 없음)
| 항목 | 허용 오차 | 근거 |
|---|---|---|
| tie 잡힌 노드 집합 | Case tie 와 **같음**(n_snap 0·miss 0) | 골격 점 거리 0, 이웃 비 tie 노드는 ≥ 요소 높이 > 0.25 h |
| tie 구속 방향 | ≤ 1e-12 | 같은 메시·같은 `node_frames` |
| g | ≤ 1e-9·umax | 골격 점 값 그대로 |
| 스프링 k(spring) | c_q = 1, 노드 행 합 Σ_r k ≤ 1e-12(상대) vs Case Σ_r sp_k; 행별 ≤ 1e-12 = r_n = 1 노드·k_mode value 만(auto 의 r_n ≥ 2 노드 = 균등 분배라 행별 차이 허용) | 골격 점 κ_P 그대로·A_S = A_P, §1.3-6 |
| 3-2-1 노드 | 같음(Case 지지를 넘김) | 시험 입력 |
| 하중 ΣF·ΣM | ≤ 1e-9(상대) | LT-4 |
| Π: \|C_mix − C_mix,Case\| / E_Case | ≤ 1.0e-2 | 오차원 = 셀 재분배(≤ 3 mm)·3-2-1 값 표본 |
| \|E − E_Case\| / E_Case | ≤ 1.0e-2 | 같음 |
| umax: \|umax − umax_Case\| / umax_Case(u_val, Ω) | ≤ 1.0e-2 | 같음 |
| MAC(u 파트 Kabsch, Case u_val) | ≥ 0.999 | 같음 |
- 두 A 밀도로 확인: h = 5 mm(칸 대부분 W 경로 — 거의 항등)·h = 1.5 mm(칸 노드 ~4 — 최소노름 재분배). 측정값이 표를 넘으면 Impl-Core 가 수치와 함께 보고하고 메인이 결정(조용한 완화 금지).

### 4.2 격자 크기 수렴 진단 (d000, 결과 정보)
- 크기 [s] + `conv_mm`(기본 [5, 10]) — **분해 재사용**(BC 패턴이 s 와 무관: 잡기·3-2-1 은 메시 척도로, k 는 골격 κ·K_q 로만 정함) → 크기마다 하중 재사상·값 재표본·해 K 회만.
- 보고(방식·엔트리 최악): ΔΠ_s = \|C_mix(s) − C_mix(3)\|/E_0, Δumax_s, MAC(u_s, u_3). `JIG_GRID_CONV` = ΔΠ_5 > `conv_warn`(0.02).
- 이 ΔΠ_5(방식·엔트리 최악)가 격자 순위의 noise_floor 하한 재료다(§3 불확실 구간 — 다른 메시 매핑·이산화 오차는 형상 간 차이와 같은 자릿수일 수 있음: §4.3 목표 Π 3e-2 vs 현장 #88 설계 차 ±5 %).
- 시험 기준(합성 — 같은 형상 다시 메시, V-0248-JG-3): ΔΠ_5 ≤ 0.02, ΔΠ_10 ≤ 0.05, MAC ≥ 0.995.

### 4.3 다른 메시 정확도 (V-0248-JG-4 — 수치는 측정 후 확정)
- A(h 5) Case 지그 → 같은 형상 다른 메시(h 3, 쿼드·삼각 섞음, 구멍 고리 다른 분할): Π ≤ 3e-2·E, MAC ≥ 0.99, umax ≤ 3e-2, 잡기 miss 0, 면적비 [0.67, 1.5].

---

## 5. 3D (D-0.24.8-JG-9)
- 이 모드에도 jd·js 3D(v0.24.6 사이드카·탭 재사용): 출처 표 RANK_SOURCES 행·키 `view3d_jd/_esl/_ref`·`view3d_js/…`·폴더 `<did>_<tag>`·`d000_<tag>_e<kk>`·`view3d_src_seconds` 그대로(백엔드 `RANK_V3D` 병합 불변).
- 빌더 `_jg_view3d_src(c, t, results, shown, row)`: 비교 안 = shown 중 per_esl 이 모두 row.need 를 가진 형상, worst = `rk._agg(…, need)`(순위와 같은 함수), 응답 = **`_jg_shape(…, keep_u=True)` 재실행**(결정적 — 평가 때 값과 같음, C_mix 일치 시험), 메시·지지·영역 = 그 모드 실행 함수(`_view3d` 선례). 표식 = `jig_bc.support_marks(bc_node, bc_kind, sp_node, x0, smax)`(형상 인덱스). 실패 격리 = `VIEW3D_FAILED: <did>_<tag>` 경고만.
- 다시 만들기(`_post_view3d`) = 같은 빌더(④ m = None). `jig_diag`(영역 진단 3D)는 없음(영역 없음 — 격자 모드 정상, R-JG-5).
- 탭 사유 문구(`JIG_STATE_TEXT.not_planned.whyMode` — jig_plan none = 옛 ④·옛 ③ 스냅샷만 남음) 갱신: 응답 `jig_on_clone`(아래) 참 = "이 스터디는 이 모드에서 지그 ESL 을 계산하지 않았습니다(v0.24.8 이전 스냅샷): {label} — 복제하면 Case 지그를 격자 매핑해 계산합니다", 거짓 = "… 설정 bead_doe.rank.jig_grid 가 꺼져 있어 복제해도 계산하지 않습니다". jig_plan "grid" = 지금 상태 판정(methods) 그대로. 탭 title(조건 툴팁) 지지 문구 끝에 " · 격자 {cell_mm} mm"(`jig.transfer == "grid"` 일 때만), 순위 정의 문구(DoeRanking — 같은 줄)에 "형상마다 Case 지그를 {cell_mm} mm 격자로 매핑(기준 d000) · 차이 {noise_floor·100} % 이내는 매핑 오차 범위"(뒤 구절 = 격자 순위일 때만, §3). 행 표식은 기존 `r.noise` 배지(`DoeRanking.tsx:232-236` "잡음 이내") 그대로 — 그 title 의 "③ 메시 잡음 바닥" 은 `jig.transfer == "grid"` 이면 "격자 매핑 오차 범위 {noise_floor}" 로(문구만). 새 버튼·새 줄 0.

---

## 6. 파일 · 스키마 · API (고정 필드명 — schemas.py ↔ types.ts `check:api`)
- `prep/jig_grid.json`(`esl/doe_jig_grid/1`): {schema, status ok|fallback, code, cell_mm, placement{kind}, frame_sha, methods{src: {status, code, reason, method, tie_dofs, spring{k_mode, alpha, k_value}|null(Case 기록), entries[{entry_id, source, npz_sha256, fit_mac, fit_umax_err, recon_mac, C_mix, E, k_sum(스프링 출처 = Σ sp_k, 그 밖 null)}]}}, groups[{g, mesh_sha, spring{k_mode, alpha, k_value}|null, entry_ids, n_tie, n_clusters, h_T, n_vox, npz, sha256}], warnings, info, seconds}. `prep/jig_grid/g<k>.npz` = §1.2 키(`mg.save_npz_det`).
- `run/designs/<did>/jig_grid.json`(`esl/doe_jig_grid_run/1`): {did, status, methods{src: {status, code, pattern_sha, shared_factor, entries[{entry_id, C_mix, E, W_F, W_g, R_sum, umax, umax_ev?, aux_reaction_rel, load{…}}]}}, map{tie(§1.5 — k_scale_min/max 포함), sample, frame_shift_mm, sup_shift_mm}, recon?(d000), conv?(d000), factor{n, seconds}, seconds}.
- result.json `jig`(grid 만 — base 결과 바이트 불변): 기존 DoeJigOut 필드(status ok|poor|fallback, code, n_jig = A tie 점 수, fit_mac_min·fit_umax_err_max = Case fit 최악, region_source null …) + **`transfer: "grid"`** + **`grid`**{cell_mm, n_groups, n_shapes, n_shapes_failed, tie_miss_max, tie_area_ratio_min, tie_area_ratio_max, k_scale_min, k_scale_max(스프링 없으면 null), noise_floor(격자 순위에 넘긴 nf — solve 대체면 null), load_dF_max, load_dM_max, corr_rel_max, small_frac_max, frame_shift_max_mm, sample_outside_max, warnings[]} + `tie_dofs` + `methods{src: {기존 DoeJigMethodOut 필드, grid{n_ok, n_failed, case_recon_mac_min, recon_mac_d000, recon_umax_err_d000, alpha, conv[{cell_mm, dpi_max, dumax_max, mac_min}]}}}`. status poor = Case fit 이 JIG_FIT_POOR 기준 미달(기존 기준).
- 스키마(B1): `DoeJigOut += transfer: Literal["base","grid"] | None = None`, `grid: DoeJigGridOut | None = None`; `DoeJigMethodOut += grid: DoeJigGridMethodOut | None = None`; `DoeResultOut.jig_plan: Literal["base","grid","none"] | None`. types.ts 같은 이름. openapi 재생성.
- `jig_plan` = `tp.jig_kind(plan, grid_snap)`(스냅샷 doe.rank 의 jig·jig_grid enabled) — **옛 스냅샷 = "none" 그대로**. `jig_on_clone`: 지금 규칙 + jig_plan none ∧ 계획 jig_fix grid 이면 = 설정 rank.jig.enabled ∧ rank.jig_grid.enabled(옛 ④·옛 ③ 응답에서 null → 참/거짓 — 의도된 API 변경, 산출물 불변).
- `rank_snapshot(c)`: rank.jig 가 있고 설정 `rank.jig_grid.enabled` 면 `jig_grid` = 설정 블록 사본(schema 값 불변 — 블록 안 `schema: 1`). 모든 시나리오에 넣고 코어가 계획으로 무시(base 모드 해시 불변).

---

## 7. 설정 · 해시 · 하위 호환 (D-0.24.8-JG-10·11)

### 7.1 설정 `bead_doe.rank.jig_grid` (DEFAULTS·pydantic `BeadDoeRankJigGridCfg`·`config/esl_platform.example.yaml`·`.prod.example.yaml` 같은 이름)
| 키 | 기본 | 검사 | 해시 |
|---|---|---|---|
| enabled | true | bool | (스냅샷 유무) |
| cell_mm | 3.0 | load_transfer.cell_min_mm..CELL_MAX_MM | 안 |
| conv_mm | [5.0, 10.0] | 각 같은 범위, cell_mm 와 다름, ≤ 3개 | 밖 |
| tie_capture_rel | 0.25 | (0, 1] | 안 |
| tie_snap_rel | 0.75 | [tie_capture_rel, 2] | 안 |
| tie_normal_deg | 30.0 | (0, 90) | 안 |
| tie_miss_frac_max | 0.1 | [0, 1] | 안 |
| sample_nbr | 1 | 1..3 | 안 |
| sample_normal_deg | 45.0 | (0, 90] | 안 |
| area_ratio_warn | 2.0 | > 1 | 밖 |
| conv_warn | 0.02 | > 0 | 밖 |
| frame_shift_warn | 0.5 | > 0(× cell_mm) | 밖 |
| load_resid_warn | 1.0e-6 | > 0 | 밖 |
| noise_floor_min | 0.01 | [0, 0.2] | 밖(표시 판정 — 정렬 불변, §3) |
- 방식 = 스냅샷 rank.jig.methods, kink·dup = rank.jig.normal_kink_deg·aux321_dup_deg, tie_dofs = **Case 값**(`prep/jig_grid.json` 기록, 스냅샷 rank.jig.tie_dofs 와 다르면 정보 문구 1줄 — 코드 없이 jig.grid.warnings). 스프링 k = Case sp_k(§1.3-6) — 스냅샷·설정의 spring_k_mode·spring_alpha·spring_k_value 는 격자 경로에서 읽지 않는다(Case 값은 기록만).

### 7.2 해시
- `_cfg_hash`(compare 포함 — `_cmp_sha` 가 cfg 로 받음): `_jg_kind(c) == "grid"` 일 때만 `keep["jig_grid"] = config_hash({grid: hash_view(스냅샷 원본), methods, kink, dup, prep: prep/jig_grid.json sha256})` — Case 지그를 다시 계산하면(npz sha) 안 전부 다시 평가. 옛 스냅샷·base 모드 = 키 없음(해시 불변).

### 7.3 하위 호환
1. 옛 스냅샷(rank.jig_grid 없음) ④·옛 ③: `jig_kind` none → result.json·ranking.csv·report·per_esl·input_sha256·view3d·사이드카(없음 그대로)·API jig_plan "none" **바이트 동일**(골든 = v0.24.7 머지 헤드에서 기록, 다시 기록 금지). 바뀌는 것 = 탭 사유 문구(화면)·응답 jig_on_clone 값.
2. base 모드(①②새 ③) — 옛·새 스냅샷 모두 계산·산출물·해시 불변(jig_grid 키는 무시).
3. 새 스냅샷 ④·옛 ③ 만 격자 지그(사이드카·3D·CSV 끝 열·result.json jig 새 키).

---

## 8. 비용 (D-0.24.8-JG-12)
기준 실측: 지그 분해(normal, node_mmd) 9.0 s / 2.7 GB @ 32,761 노드(esl_jig_case 부록 A.7 — 3-2-1 분해 대비 메모리 −14 %), jd·js 3D 방식당 7~10 s·피크 501 MB @ 9,801(D-0.24.6-INT-3). 외삽 = 시간 ∝ N^1.5(R-JG-4 실측).

| 단계 | 형상마다(방식 [prescribed, spring], 엔트리 K) | 50k 노드 | 100k | 150k |
|---|---|---|---|---|
| 분해 | **+2**(prescribed 1·spring 1; fixed 포함해도 +0 — 공유; 묶음 1개 기준 — 묶음(메시·tie·스프링 파라미터)이 여럿이면 묶음마다, §3) | 2×17 s | 2×48 s | 2×88 s |
| 해 | 2K(값·바닥은 같은 해 1회) | K=4: ≈ 2 s | ≈ 6 s | ≈ 10 s |
| 하중 사상 | 2K 셀 전달(W = 형상 ESL 전달 캐시 재사용) | ≈ 10 s | ≈ 15 s | ≈ 25 s |
| 잡기·표본·조립·스프링 k | 1회(k = 골격 보간·클러스터 합 O(행 수) — 형상 강성 대각 블록 추출 없음) | ≤ 3 s | ≤ 5 s | ≤ 8 s |
| **형상 합** | 기존 형상 평가(메시 + 3-2-1 분해 1 + 진단) 대비 ≈ +100~150 % | ≈ 50 s | ≈ 120 s | ≈ 220 s |
| 메모리 피크 | 분해 1개(순차·del) ≤ 기존 3-2-1 분해(같은 N), 상주 추가 = 하중 2K·N·24 B + 격자 | | | |
- d000 추가: 수렴 2 크기 × (2K 사상 + 2K 해), **분해 0** → +30~60 s.
- BD_LOADS 격자(1회): A 194k·K 4·방식 2 → 읽기·복셀·골격 ≈ 5~20 s, `prep/jig_grid` ≈ 30~60 MB(f_<src> 압축 + 복셀 장).
- BD_POST 3D: (top_k + d000) 형상 × 방식 분해 — top_k 3·100k = 8×48 s ≈ 6.4 분(R-JG-3). 30 형상 ④(100k) 평가 추가 ≈ 60 분(워커 병렬로 나눔), spring 을 빼면 ≈ 절반.

---

## 9. 시험 (V-0248-JG-n)
1. 계획 표: 모든 행·열 채움, JIG_VALUES·불변식 위반 = CONFIG_INVALID, `jig_kind` 진리표(3 계획 × grid_snap), `metric_effective` 기존 호출 바이트 동일·kind grid, 호출부 시나리오 이름 분기 0(정적).
2. 항등(§4.1 표 전부, k 행 포함) — prescribed·spring(+ fixed 있는 Case), A h 5·1.5 mm, spring 은 k_mode auto·value 둘 다(꺾임 r_n = 2 노드 포함).
3. 수렴(§4.2): 같은 형상 다시 메시 3/5/10 mm 기준 + 수렴 진단 분해 0 회(카운터).
4. 다른 메시 정확도(§4.3).
5. 단조성: 같은 형상 메시에 비드 모핑(강성↑ — 같은 위상) → s_d < 1(prescribed·spring), d000 s = 1 정확, C_ref = E_0.
6. 잡기: 구멍 고리 tie·와셔 면 tie·고립 점(snap)·구멍 없는 형상(miss → 경고, 비 초과 = 그 형상 실패)·tie 옆 수직 플랜지(법선 거부)·회전 배치 rigid(회전 불변 — 같은 집합)·frame 배치.
7. 표본: 평판 선형장 정확(≤ 1e-9), 후보 부족 = 상수, 격자 밖 = JIG_GRID_OUTSIDE·값 0, 결정성(두 번 비트 동일).
8. 하중: `_plan_loads` cell(s) 와 비트 동일, ΣF·ΣM ≤ 1e-9, 잔차 경고 코드.
9. 분해 공유: 형상당 분해 수 [prescribed, spring] = 2, [fixed, prescribed, spring] = 2, d000 수렴 = 0 추가.
10. 순위: d000 score 1, metric_effective jd, 실패 형상 = n_failed, d000 실패 = JIG_GRID_NO_REF·solve 대체, JIG_GRID_RANK ↔ SM_CROSS_MESH 배타, 첫 방식 Case 지그 없음 = 다음 ok 방식이 출처(js)·전부 없음 = solve + `JIG_GRID_SOURCE_MISSING` 조치 문구, base 모드 `_jig_rank_src` 바이트 불변.
11. 하위 호환: 옛 ④·옛 ③ 스냅샷 골든(v0.24.7 머지 헤드 기록) — result.json·ranking.csv·per_esl·input_sha256·API jig_plan 바이트 동일. base 모드 새 스냅샷에 jig_grid 넣어도 산출물·해시 동일.
12. 해시: 해시 밖 키 변경 = 불변, Case 지그 npz 교체 = 변함, 스냅샷 원본 해시(설정 기본에 키 추가해도 불변).
13. 3D: ④ 격자 — 사이드카 view3d_jd·js 키·폴더 실재, 재실행 C_mix = 평가 값, 백엔드 병합·탭 활성, 다시 만들기 ④ m = None, 실패 격리.
14. 문구: jig_plan none 2문구(jig_on_clone), grid title 꼬리, DoeRanking 정의 같은 줄 수.
15. 설정 거울: DEFAULTS = pydantic = yaml 2, 검사 범위 422/CONFIG_INVALID.
16. 비용: 합성 120×80 형상 분해 수·시간 비·피크 메모리(기존 형상 평가 대비 기록).
17. e2e: 합성 Case(지그 산출물) + ④ 3 형상 → BD_LOADS 격자 → BD_EVAL → BD_POST → API → 프런트 픽스처(jig_grid.test.ts).
18. 실패 격리: Case 지그 없음 = prep fallback·solve 순위·BASELINE_FAILED 없음, 실행기 예외 = 그 형상만 JIG_DESIGN_FAILED.
19. 모듈 순수: `esl.mech.grid_map` import 그래프에 esl.doe 0·파일 IO 0(정적).
20. 옛 ③(scn step) e2e 1개(배치 auto rigid 포함).
21. 스프링 k 메시 무관·설계 무관(§1.3-6): 같은 형상을 다른 크기(h 5·3·1.5)로 다시 메시 → 클러스터마다 Σk = K_q(≤ 1e-12 상대), snap 1노드 클러스터 = K_q, 비드 모핑(tie 근처) 안 = 클러스터 Σk 불변, `jig_bc.spring_k` 호출 0(격자 경로 — 정적·카운터), prescribed·fixed BC 의 sp_* 길이 0, 스프링 파라미터가 다른 엔트리 = 다른 묶음, 같은 묶음 안 sp_k 불일치(> 1e-9) = 그 엔트리만 `JIG_GRID_SOURCE_MISSING` fallback.
22. noise_floor(§3): ΔΠ_5 가 다른 합성 2개 → result.json jig.grid.noise_floor·rank noise_floor = max(ΔΠ_5, noise_floor_min), 행 noise 표식, conv_mm 빈 값 = noise_floor_min, 옛 ③ 메시 잡음 바닥이 더 크면 그 값(셋 중 최댓값), 옛 스냅샷·base 모드·solve 대체의 rank 호출 인수 불변(바이트), noise_floor_min 변경 = 해시 불변.

---

## 10. 작업 분해 · v0.24.7 겹침

### 10.1 묶음 (파일 소유 겹침 없음)
| 묶음 | 모델 | 파일 |
|---|---|---|
| C1 코어 | opus | `esl/mech/grid_map.py`(신규), `esl/doe/transfer_plan.py`, `esl/doe/stages.py`, `esl/doe/__init__.py`(DEFAULTS rank.jig_grid), `esl/doe/report_doe.py`, `resources/doe_messages.json`, `tests/mech/test_grid_map.py`, `tests/doe/synth_jig_grid.py`, `tests/doe/test_jig_grid*.py`, 골든 `tests/doe/golden_v0248_c1/` |
| B1 백엔드 | sonnet | `backend/esl_platform/core/config.py`(BeadDoeRankJigGridCfg), `config/esl_platform.example.yaml`·`.prod.example.yaml`, `backend/esl_platform/api/schemas.py`, `api/services/doe.py`(rank_snapshot·jig_plan·jig_on_clone), openapi, `backend/tests/test_doe_v0248_*.py` |
| F1 프런트 | sonnet | `frontend/src/api/types.ts`·`api/doe.ts`(코드 문구), `pages/doe/doeTabs.ts`, `components/DoeRanking.tsx`, `mock/*.ts`(격자 픽스처), `__tests__/jig_grid*.test.ts`, Playwright 2560·1920 높이 ±0 |
- 순서: C1 이 `grid_map` 시그니처·`jig_kind`·코드 표 첫 커밋 → B1·F1 병렬 → 통합(메인: CHANGELOG·user.md 격자 지그 절·admin 설정 키·decisions 확정).

### 10.2 v0.24.7(`esl_bead_depth_mode.md`)과 겹치는 파일 — v0.24.7 머지 위에 재기반
| 파일 | v0.24.7 | v0.24.8 | 충돌 위험 |
|---|---|---|---|
| `esl/doe/stages.py` | C1(depth_section 기저·스냅샷) | C1(지그 훅·_jg_*·_cmp_post·CSV) | 중 — 다른 함수, `bd_eval`·`_cfg_hash` 근처 |
| `esl/doe/__init__.py` | 최상위 depth_section·rules | rank.jig_grid | 낮음 |
| `resources/doe_messages.json` | DS_* 코드 | JIG_GRID_* 코드 | 낮음(끝에 추가) |
| `backend/.../core/config.py`·yaml 2 | depth_section | rank.jig_grid | 낮음 |
| `api/schemas.py`·`api/services/doe.py` | DoeStudyIn/Out·params | DoeJigOut·jig_plan·rank_snapshot | 낮음~중 |
| openapi | 재생성 | 재생성 | **두 번째 머지에서 다시 생성** |
| `frontend/src/api/types.ts`·`doe.ts`·`mock/*.ts` | depth_section 타입·픽스처 | 지그 격자 타입·픽스처 | 낮음 |
| CHANGELOG·VERSION | 0.24.7 | 0.24.8 | 통합 때 |
- v0.24.7 전용(겹침 없음): `esl/morph/section.py`·`bead_graph.py`·`bead_select.py`·`paicad_io.py`·`DoeStudy.tsx`·`DoeParamTable.tsx`·`SectionMini.tsx`. v0.24.8 전용: `grid_map.py`·`transfer_plan.py`·`report_doe.py`·`doeTabs.ts`·`DoeRanking.tsx`.
- 골든(옛 바이트) 은 v0.24.7 머지 헤드에서 기록(§7.3). 패키지 beadgraph 1.2.0 과 무관.

### 10.3 v0.24.9 접점 (`esl_bead_pos_u.md`)
- 같은 메시 모드의 "하중 공간 고정"은 `grid_map` 이 아니라 기존 `load_transfer` 셀 전달을 안마다 다시 하는 것(계획 표 새 열 `load_follow`) — 격자 크기 값은 이 계약의 `rank.jig_grid.cell_mm` 과 **다른 키**(같은 기본 3 mm)로 둔다.
- `_plan_loads(("cell", s), srcs=…)` 의 srcs 경로를 C1 이 지그 맞춤 하중에 처음 쓰므로(§2.3) 시그니처를 바꾸면 v0.24.9 가 재사용할 수 있게 일반형으로 둔다.

---

## 11. 미결 (결과를 바꾸는 것만 — 기본 가정으로 진행)
- ~~Q-JG-1 스프링 k 출처~~ — **닫음**(D-0.24.8-JG-14): Case sp_k 를 골격 면적 밀도 κ 로 올려 형상 노드 면적으로 내리고 클러스터 합 K_q 보존(§1.3-6). 형상 자기 강성 안은 채택 안 함(설계가 k 를 바꾸고 Σk 가 메시에 따라 변함).
- **Q-JG-2 지그 출처** — 기본: Case 04_esl 지그 결과(맞춤 하중·tie·α = Case 설정, 항등 기준과 같음, 추가 맞춤 비용 0). 대안: 스터디가 A 메시에서 rank.jig 설정으로 다시 맞춤(Case 와 다른 설정 반영 가능, A 분해·deck 읽기 +수 분).
- **Q-JG-3 ④·옛 ③ 새 스터디 기본 순위** — 기본: rank.metric jig 그대로 → 격자 지그(ok 인 첫 방식 — 기본 jd), 실패면 solve. 대안: solve 유지 + 지그는 탭 비교만(순위 불변).

## 12. 결정 요약 — 전문 `docs/decisions.md` 2026-11-25 D-0.24.8-JG-1~15(14·15 = 검토 개정 1).

## 13. 후속 (R-JG-n)
- R-JG-1 실행 중 A 왕복 자기 점검(A→격자→A 해, A 분해 +1 — 설정 끔 기본으로 추가 검토).
- R-JG-2 `step_graph.hole_rings` 로 잡기 진단 "구멍에 닿음" 추가(xfer 검증 규칙과 통일).
- R-JG-3 3D 비용 — 평가 때 u 저장 선택지(디스크 vs 분해).
- R-JG-4 현장 실측(Case 194k, ④ 형상 3 mm ~10만 노드 × 30) 시간·메모리 → 외삽 갱신.
- R-JG-5 격자 모드 잡기 표식 3D(골격·잡힌 노드·miss 클러스터).
- R-JG-6 비드 최적화(load_source 지그 계열)·라이브러리 내보내기로 격자 지그 경계 전달.
- R-JG-7 Q-JG-2 대안 구현(답에 따라 — 스터디가 A 메시에서 rank.jig 설정으로 다시 맞춤). Q-JG-1 대안(형상 자기 강성)은 채택 안 함 — 후속 없음.

## 14. 개정 1 — 본문 반영됨 (2026-11-25, 결정 D-0.24.8-JG-14·15 참조)
- 스프링 k = Case sp_k 의 골격 면적 밀도 κ·클러스터 합 K_q 보존(설계·메시 무관), `spring_k` 미사용 — §1.2·§1.3-6·§2.1·§4.1·§9-21, Q-JG-1 닫음.
- 격자 순위 noise_floor = max(ΔΠ_5, noise_floor_min 0.01) → 기존 rank noise 표식 — §3·§4.2·§5·§6·§7.1·§9-22.
- `JIG_GRID_SOURCE_MISSING` 조치 문구, 순위 출처 = ok 인 첫 방식 — §1.4·§3.
- 앞뒤 버전 접점 — §10.2(v0.24.7)·§10.3(v0.24.9).
