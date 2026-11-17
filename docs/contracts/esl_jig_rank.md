# 계약: 지그 순위 — 체결부 고정 + 맞춤 가압 하중으로 설계안 비교 · 기준 재현 진단 (JIG_RANK, v0.23.0)

- 상태: **확정 대기 없음 — 결정 질문 2개 확정(2026-11-17 사용자, §12)**: Q-JIG-1 기본안, Q-JIG-2 대안(접촉 영역 유지 + 부족분 패치 보충). **보완 2026-11-17 17:44**(사용자 — 모드 관성 기저 D-JIG-15) · **보완 2026-11-17**(메인 — Impl-Core af0385b 보고: 유한 회전 목표·법선 가중·하중 정규화·상쇄 경고 D-JIG-16). 2026-11-17 작성(main 685df7d = v0.22.0 기준, 브랜치 release/v0.23.0).
- 버전: **v0.23.0**. migration **불필요**(새 값은 `bead_does.doe` 스냅샷·`result` JSONB·작업 폴더 파일만 — §11).
- 관계: `esl_stiffness_metric.md` 의 **순위 지표 선택지에 `jig` 를 더한다**(BD-D-6 구조 = 최악 ESL 비·오름차순·동률 규칙 그대로, 값만 바뀜). 참조 변위는 같은 계약의 `prep/sm_ref.npz`(once 계획의 베이스라인 해) 를 그대로 읽는다. 결정 A(같은 메시 안에서만)·계획 표 원칙(AGENTS.md)을 따른다. 충돌 시 순위 지표 `jig` 범위에서 이 문서 우선.
- ID 규칙: 결정 `D-0.23.0-JIG-n`, 시험 `V-JIG-n`(1~16), 리스크 `R-JIG-n`, 결정 질문 `Q-JIG-n`.
- 근거: 이슈 #63 (2026-11-16·17 진단) — 현 순위(ESL F = K₀u₀ 전 노드 하중, 3-2-1 지지, K₁ 재풀이 C·umax)는 30안 모두 `SM_IMBALANCE` 3~15 %, umax 300~4 300 mm, score~imbalance R² 0.507 → 순위가 모핑량에 지배됨. 원인: u₀ 대회전이 만든 거대 상쇄 하중 + 3-2-1 지지의 0.75 Hz 인공 무른 모드가 잔차 r = −(K₁−K₀)u₀ 를 K₁⁻¹ 로 증폭.

### 사용자 확정 (2026-11-17, 변경 금지)
1. 대안 B(모드 필터)·E(공회전 ESL) **기각**. **지그안**: 실물 지그 시험처럼 chassis rear 를 체결부(tie)에서 물리고 몇 곳을 눌러 낙하 변형을 재현 → 설계안 비교는 **같은 지그·같은 하중으로 하중 제어 재풀이**(umax·C 작을수록 강함). 하중이 몇 곳뿐이고 실제 체결로 지지하므로 상쇄·무른 모드 문제가 원리적으로 없다.
2. **사내 서버 실험 없이** 플랫폼에 구현해 서버에서 바로 결과를 보며 판단 → 플랫폼이 기준 재현 지표(MAC·umax 오차)를 스스로 보고한다.
3. 모델 현황: 제품 입력에는 tie(`/INTER/TYPE2`)와 일반 접촉만 있다. 업로드 결과는 h3d(ANIM 없음)·T01. 일반 접촉이라 T01 합력은 분포 정보가 없어 **T01 은 쓰지 않는다**. h3d 는 대상 파트만 덤프되어 다른 부품 변위가 없다.
4. 새 스터디 기본 순위 지표 = `jig`(현 지표 신뢰 불가). 기존 스터디는 스냅샷 값 유지(동작·바이트 불변).
5. 값 하드코딩 금지(DEFAULTS·pydantic·예시 yaml 2 같은 이름), 코드 구조 원칙(공용 계산 독립 모듈, 모드 차이 = 계획 표 열, 진단 스키마 1개).
6. 화면은 필수 정보만(정의 문구 + 기준 재현 한 줄), 화면 길이 늘리지 않음, 2560×1440 기준.
7. (2026-11-17 17:44) 설계 활용이 주목적 — **지그 ESL 주력, 시간 증분 ESL(DiESL식)은 보류**(§3.1). 덴팅 = TV 대형 박판 섀시 전체가 휘청이는 전역 굽힘·비틀림(처짐 ≫ 두께) → 균일 체적력만으로는 휘청 관성 분포를 못 담으므로 **지그 구속 저차 모드의 관성 하중 기저**를 더한다(§1(4b)).

## 0. 조사 결과 (근거, main 685df7d)

| 항목 | 위치·시그니처 | 이 계약에서 |
|---|---|---|
| 순위 | `esl/doe/rank.py:rank(results, *, noise_floor, tol, extra_failed, metric="solve", lin_form, lin_valid)` — `sm.metric_key(metric, lin_form)` 로 per_esl 키 선택, 키 ≠ `C` 이면 `_sm_new`(per_esl 에 `C_lin`) 필수, 값 null 안 = `n_failed["sm"]` | `metric_key("jig") = "C_jig"`, 보조 `score_jig`·`umax_jig` |
| 지표 모듈 | `esl/doe/stiffness_metric.py` — `METRICS = ("lin","solve")`, `metric_key`(모르는 값 = `CONFIG_INVALID`), `score`, `remove_rigid`, `umax_def` | `METRICS` 에 `jig` 추가, `metric_key` 1줄 |
| 참조 변위 | `stages.py:3264` `SM_REF_NPZ = "sm_ref.npz"`, `SM_REF_SCHEMA = "esl/doe_sm_ref/1"` — 베이스라인 `bd_eval` 의 `_sm_eval` 이 once 계획(`sm_disp[1] == "I"`)에서 `node_id (N,)`·`u (K,N,6)`(전 노드 최소제곱 강체 제거 후)·`entry_ids`·`C_ref`·`ref_kind` 저장 | u_tgt 출처(병진 3성분만) |
| 순위 훅 | `stages.py:588 bd_eval` → (`_lt_eval` \| `_ev` \| `ev.evaluate`) → `_sm_apply`(3539) → `result.json` `sm{…}`(677). `bd_post`(908) `_sm_post` → `rk.rank(metric=metric_effective…)`. `_ranking_csv`(755) 가운데 열 `SM_CSV_MID`(732), 끝 열 `LT_CSV_COLS`(2584). ④ CSV(3601) 끝 열 `MESH_CSV_COLS·LT_CSV_COLS·MQ_CSV_COLS` | 훅 `_jig_apply` 1개 + post 블록·끝 열 |
| 스냅샷 | backend `services/doe.py:rank_snapshot(c)`(317) → 작업 spec `params.doe.rank{metric, lin_form, lin_valid, imbalance_warn, schema 1}`, `inputs.rank_metric`(1191·1263). 코어 `stages.py:_sm(c)`(3270) — 키 없음 = None(옛 = solve, 지표 계산 없음), 빠진 키는 `settings()["rank"]` 기본 | `rank.jig` 블록 + `schema 2` |
| 설정 4곳 | `esl/doe/__init__.py:DEFAULTS["rank"]`(83) ↔ `backend/esl_platform/core/config.py:BeadDoeRankCfg`(514) ↔ `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml` `bead_doe.rank` | `metric` 기본 `jig`, 새 절 `rank.jig` |
| 이어하기 해시 | `stages.py:_cfg_hash`(505) — 스냅샷에 키가 있을 때만 `load_transfer`·`stiffness` 를 keep 에 추가(legacy 해시 불변), `rank.metric` 은 해시 밖(SM-6) | 같은 방식으로 `jig` |
| 계획 표 | `esl/doe/transfer_plan.py:PLANS`·`PLAN_COLS`·`plan_for`(빈 칸 = `CONFIG_INVALID`, `BS_VALUES`·`RD_VALUES` 값 검사), `metric_effective(plan, metric)`·`cross_mesh(plan)` | 열 3개(§5.2), `metric_effective` 키워드 1개 |
| tie 노드 | `esl/doe/paicad_io.py:read_fixed(d, max_mb) -> {doc, node_id, part, kind_mask, cluster, xyz, clusters}`, `FIXED_KINDS = ("INTER_TYPE2_SECONDARY","INTER_TYPE2_MAIN","RBE2","RBE3","RBODY","BCS","SHARED")`(비트 = 순서). ①·select case·② = 워커 BD_GEOM fixed-scan(대상 파트) → `prep/fixed/`(`shell_scan.json`+`fixed_nodes.npz`), 없음·실패 = `FIXED_INFO_MISSING`(`stages.py:_sel_fixed_ids` 4001). 새 ③(step) = `prep/fixed` 없음, A 체결점 이전 `prep/select/fixed_transfer.json`(`node_id[]` = B 노드 ID 합집합, 노드별 kind 없음 — `step_graph.py:31`) | 지그 노드 출처 열 `jig_fix` |
| 다른 부품 deck | ①·select case: 원 Case starter `D.base.rad_path` + `c.parse_kw()`(include_path_map·깊이·줄 길이) 제자리 읽기(`_sel_rad_files` 4825 선례), 대상 파트 id = `prep/input.json part_id`. ② = `input/mesh/<input.json mesh.main>` 사본(업로드 그대로 — 다른 부품이 있을 수도 없을 수도), `part_id` 같음. 새 ③ = STEP 만(원 rad 없음, A Case 는 A 좌표 — 배치 다를 수 있음). `prep/assem_full/` 사본은 paicad 준비분일 때만 있고 `bd_input` 마다 지워지는 파생물(`assem_full.drop_derived`) → **의존하지 않는다** | 원 deck 재파싱(①②), ③ = 패치 |
| rad 파서 | `esl/rad/parser.py:_Deck` — `scan` 1차(위치만): `node_segs`·`shell_segs`(모든 파트, `hid` = 파트 id) 기록, 솔리드 등 `_OTHER_ELEM_KW` 블록은 **행 수만 세고 위치를 버림**(`other_elem_parts`). `_seg_iter(fh, seg)`·`load_nodes(node_id)` | 가산 변경 2개(§5.4) |
| 솔리드 외곽 면 | `esl/doe/assem_full.py`: `ELEM_NODES`·`ELEM_TOTAL`(여러 줄 카드 BRIC20 20·TETRA10 10)·`SOLID_FACES`·`_faces`·`_clean`·`_lead_ints`·`solid_segments`(EXT = 공유되지 않는 면) | import 재사용(복제 없음) |
| 쉘 해석 | `esl/mech/shell.py:ShellModel(x0, conn, elem_type, thickness, E, nu, drill_factor, backend, …)` — `.factorize(spc)` → `FactorizedSolve.solve(F (N,3)) -> (u (N,6), R (N,3))`(분해 재사용), spc 병진 `"123"` 만(회전 고정 불가), `_check_restraint` = 연결 성분마다 구속 dof ≥ 6·비퇴화 아니면 `SOLVER_SINGULAR`. `.area`(요소 면적). 노드 면적·법선 함수 없음. `solve_many` 는 호출마다 다시 분해 → 쓰지 않고 `factorize` 1회 + `solve` 반복 | 지그 = 노드 병진 123 |
| 강체 | `esl/mech/kabsch.py:remove_linear_rigid(X0, u) -> (u_rel, a(3), ω(3))`(미소 강체, P = X0 − 평균, 3점 미만·공선 = `KABSCH_DEGENERATE`) — 선형 해의 강체 성분은 미소 회전이라 Kabsch(유한 회전)보다 이쪽이 정확 | u_tgt 의 지그 기준 강체 제거 |
| scipy | `pyproject.toml` 의존성 `scipy`(현 1.18.1): `scipy.optimize.lsq_linear`(bvls)·`scipy.spatial.cKDTree`·`scipy.sparse.csgraph.connected_components` 사용 가능. 저장소에 lsq_linear·eigsh 선례 없음, cKDTree 선례 다수(`load_transfer.py` 등) | 대체 경로 불필요(D-0.23.0-JIG-9) |
| 결과 스키마 | `schemas.py:DoeResultOut`(1879) `metric`·`metric_effective: Literal["lin","solve"]`, `rank: dict`. `types.ts` `DoeRankMetric = "lin" \| "solve"`(3091), `DoeRankCfg`(2367), `DoeRankRow`(3046) | Literal·union 에 `jig`, 새 `DoeJigOut` |
| 화면 | `frontend/src/components/DoeRanking.tsx`(345줄) — `result.rank.metric_effective`·`score`·`score_lin`·`score_solve`·`imbalance_max`·`umax_def` 를 읽고 정의 문구(`<li>`)·주 열 이름 하드코딩(100~143행). 문구 맵 `api/doe.ts:SM_CODE_TEXT` | jig 분기 + 한 줄 |
| 픽스처 | `tests/doe/synth_sm.py`: `plate(nx,ny,Lx,Lz,t,bow,n_tria_cols)`(XZ 판, 법선 Y), `spc`, `model`, `drop_u`, `esl_force`, `bead_x(mesh, alpha, depth, center, r)`, `solve`. `tests/doe/synth_doe.py`: `plate`, `write_mesh_rad`, `write_fixed(d, mesh, node_idx_groups, kinds)`(kinds = `FIXED_KINDS` 이름), `features_doc`, `write_grid`, `PART_ID` | 새 `synth_jig.py` 가 감쌈 |

## 1. 정의 (D-0.23.0-JIG-1~6)

단위 = 모델 단위(mm, N, MPa). 기호: 기준 메시(베이스라인 d000, once 계획 — 모든 안이 같은 노드 ID·순서) 노드 N 개, 좌표 x (N,3), ESL 엔트리 i = 1..K, 참조 변위 u_ref,i = `sm_ref.npz["u"][i, :, :3]`(병진). 평가 노드 Ω = 계획 열 `sm_omega` 영역 노드(`all` 이면 전체 — `_sm_eval` 의 `om_nodes` 와 같은 것).

**(1) 지그 노드 J (D-JIG-1)** — 계획 열 `jig_fix`:
- `fixed`: `read_fixed(prep/fixed)` 에서 `kind_mask & kind_bits(jig.fix_kinds) ≠ 0` 인 노드 ID ∩ 기준 메시 node_id(정렬·중복 제거). 기본 `fix_kinds = [INTER_TYPE2_SECONDARY, INTER_TYPE2_MAIN]`(사용자 확정 3 — 제품 모델 체결 = tie 만).
- `xfer`: `prep/select/fixed_transfer.json` `node_id[]` ∩ 기준 메시 node_id(노드별 kind 가 파일에 없어 **종류 필터 없음** — 정보 `JIG_FIX_UNFILTERED` 1개).
- `none`: 지그 없음(계획이 지그 불가).
- 구속 = J 의 병진 123(회전 자유 — `ShellModel` spc 제약). **검사**(분해 전, `select_jig_nodes`): J = ∅ → `JIG_NO_TIE`; 기준 메시 요소 그래프의 연결 성분마다 그 성분의 J 노드 ≥ 3 이고 비공선(중심화 좌표 특이값 s₂/s₁ ≥ `kabsch.DEGENERATE_RATIO`)이 아니면 → `JIG_SUPPORT_DEGENERATE`(detail: 성분 수·부족 성분 노드 수). 둘 다 순위 fallback(§1(7)).

**(2) 목표 변형 u_tgt,i (D-JIG-2, D-JIG-16 개정)** — 지그 노드 기준 **유한 회전** 강체 제거(Kabsch):
```
(R, t, info) = kabsch.fit(x[J], x[J] + u_ref,i[J])            R ∈ SO(3) (반사 보정), R·x0 + t ≈ x0 + u  (지그 노드 균등 가중)
c0 = mean(x[J]),  ū = mean(u_ref,i[J])                          (t = c0 + ū − R c0)
u_tgt,i,n = Rᵀ(x_n + u_ref,i,n − t) − x_n = (Rᵀ − I)(x_n − c0) + Rᵀ(u_ref,i,n − ū)     (모든 노드, 중심화 식 — kabsch.remove_rigid 와 같은 정밀도 처리)
umax_tgt,i = max_{n∈F} ‖u_tgt,i,n‖,    F = 맞춤 노드 = Ω \ J
tie_rel,i  = max_{n∈J} ‖u_tgt,i,n‖ / umax_tgt,i                      (지그 노드끼리의 잔여 상대 변위 — 진단)
rot_deg,i  = kabsch.rotation_deg(R)                                   (진단)
```
- 개정 근거(Impl-Core af0385b 보고, 메인 판단): 섀시 휘청은 면외 굽힘·비틀림 지배인데, 미소 강체 제거(a + ω×x)는 큰 회전에서 O(θ²L) 의 **가짜 면내 잔여**(막 압축·인장)를 목표에 남기고, 맞춤이 이를 따라가려 면내 접선력·체적력을 서로 상쇄하게 쓴다(cancel ≈ 0.76, 면내 하중이 법선력의 10²~10³ 배 — #63 상쇄 하중 재발). 유한 회전 제거는 이 잔여를 만들지 않는다. 지그 노드 회전이 작으면 두 방식은 O(θ²) 안에서 일치(V-JIG-20).
- `kabsch.fit` 의 3점 미만·퇴화(`KABSCH_DEGENERATE`)는 (1) 의 지그 검사가 먼저 막는다(남으면 `JIG_SKIPPED{stage target}`).
- tie_rel > `jig.tie_rel_warn` → 경고 `JIG_TIE_RELATIVE`(BD_POST 판정, 순위 계속). 이번 버전은 **고정만**(지그 노드 강제 변위는 후속 — R-JIG-1).

**(3) 가압 후보 영역 (D-JIG-3)** — 계획 열 `jig_ctx`:
- 후보 노드 C = F(맞춤 노드 = Ω \ J).
- `case`·`mesh`: deck 에서 **대상 파트 밖** 모든 파트의 표면 삼각형 S(쉘 = 요소 자체, 쿼드 = 삼각형 2개 (0,1,2)(0,2,3); 솔리드 = 파트 안에서 공유되지 않는 외곽 면 — `assem_full.SOLID_FACES`·`_faces`·`_clean`, EXT 규칙)를 **변형 전 좌표**로 읽는다(§5.4). 노드 n ∈ C 의 접촉 판정: d_n = min_{s∈S} dist(x_n, s) ≤ `jig.contact_gap_mm`. 최근접 삼각형(동률 ≤ 1e-12·gap 은 작은 삼각형 번호)의 파트 p_n·최근접점 q_n 기록.
- 영역 = 같은 p_n 을 가진 접촉 노드의 **대상 메시 연결 성분**(요소 변 그래프, 양 끝이 모두 집합 안인 변만). 노드 수 < `jig.min_region_nodes` 또는 면적 Σ A_n < `jig.min_region_area_mm2` 인 성분은 버림. 정렬 키 (−면적, p, 최소 노드 인덱스) 로 상위 `jig.max_regions` 개.
- **패치 보충(Q-JIG-2 확정 — 접촉 영역 유지 + 부족분만 패치)**: 접촉 영역 수 n_c(위 규칙으로 남은 것) < `jig.min_regions` 이면 n_fill 개를 공간 패치로 보충한다. `jig_ctx = none`·deck 읽기 실패(`JIG_SURF_UNAVAILABLE`)·삼각형 상한 초과(`JIG_SURF_TOO_LARGE`)는 n_c = 0 으로 본다.
  - n_c ≥ min_regions → 보충 없음(영역 = 접촉만).
  - 1 ≤ n_c < min_regions → n_fill = min_regions − n_c(**혼합**). n_c = 0 → n_fill = min(`jig.patch_count`, `max_regions`)(**전부 패치** = 옛 fallback 과 같음).
  - 패치 후보 노드 C_p = C \ (접촉 영역 노드 ∪ J) — 접촉 영역에 이미 속한 노드·지그 노드는 패치에 넣지 않음(영역끼리 노드 겹침 0).
  - 패치 = C_p 를 C_p 의 PCA 주축 2개(1·2축, 부호 = 각 축 최대 절댓값 성분이 양수)의 격자 g₁ × g₂ 로 분할(g₁ = max(1, round(√(P·L₁/L₂))), g₂ = max(1, ceil(P/g₁)), P = `jig.patch_count`(보충 수와 무관하게 같은 격자 — 패치 크기가 혼합·전부 패치에서 같음), L = 축 방향 폭), 셀(행 우선) 중 노드 ≥ `min_region_nodes` 인 것만, 정렬 키 (−면적, −1, 최소 노드 인덱스) 로 상위 n_fill 개.
  - 최종 영역 순서 = 접촉 영역(위 정렬) 뒤에 패치(위 정렬), 합계 ≤ `max_regions`. 영역마다 출처 `kind = contact | patch` 를 jig.npz(`reg_kind`)·jig.json(`regions[].kind`)·진단에 기록, 영역 묶음 출처 `regions_from = contact | mixed | patch`.
  - 보충이 일어나면(n_fill > 0) 경고 `JIG_REGION_FALLBACK{reason, n_contact, n_patch}`(reason = `few_contact`(1 ≤ n_c, 또는 deck 은 읽었으나 접촉 0) \| `no_deck`(`jig_ctx = none`) \| `surf_failed`(읽기 실패·상한 초과)). C_p 가 비어 n_fill 을 다 못 채워도 진행(있는 영역으로 보정, `n_patch` 에 실제 수).
- 거리 계산(대규모): 삼각형 중심 cKDTree + 노드 청크(`jig.chunk_nodes`)마다 `query(k = min(jig.knn, T), distance_upper_bound = gap + R_max)`(R_max = 삼각형 중심→꼭짓점 최대 거리) → 후보 삼각형만 정확 점-삼각형 거리(Ericson, `load_transfer` LT-2 와 같은 식). 메모리 O(T + chunk·knn) — **N×T 배열 금지**(V-JIG-8). knn 근사는 LT-2 와 같은 수준(후보 밖 더 가까운 삼각형을 놓칠 수 있음 — 판정 경계에서만 영향).

**(4) 하중 기저 (D-JIG-4)** — 영역 r = 1..R, 노드 집합 N_r:
- 노드 면적 A_n = Σ_{e∋n} A_e / nn_e(`ShellModel.area`, quad 4·tria 3 등분), 노드 두께 t_n = 이웃 요소 두께의 면적 가중 평균, 요소 단위 법선 m_e(코너 0,1,2 외적 — 쿼드는 대각선 외적).
- 영역 틀: n_r = 산포 행렬 Σ_{n∈N_r} A_n m̂_n m̂_nᵀ 의 최대 고유벡터(요소 법선 방향 뒤집힘에 무관; m̂_n = 이웃 요소 법선의 면적 가중 합 정규화). 접촉 영역 부호: s_r = Σ A_n n_r·(x_n − q_n); s_r < 0 이면 n_r ← −n_r(**힘은 상대 부품에서 대상 쪽으로 미는 방향**), |s_r| ≤ 1e-9·Σ A_n·max(gap, 1) 이면 부호 자유(`reg_sign = 0`, 정보 `JIG_NORMAL_FREE`). 패치 = 부호 자유, n_r 부호는 최대 절댓값 성분이 양수. 접선 t1 = normalize(e_k × n_r)(e_k = |n_r·e_k| 최소인 전역 축, 동률 = 작은 k), t2 = n_r × t1.
- 기저 열 순서 = 영역마다 [n_r, t1, t2](`jig.basis_tangential = false` 면 [n_r] 만 — 비교용) → (`jig.body_force` 참이면) 체적력 [e_x, e_y, e_z] → (`jig.n_modes` > 0 이고 모드 성공이면) 모드 관성 [g_1 … g_m](§1(4b)). nb = (3 또는 1)·R + 3·body + m ≤ 3·max_regions + 3 + n_modes. 열 종류 `col_kind` = 1 법선 · 2 접선 · 3 체적력 · 4 모드.
- 영역 기저 k(방향 d): f_k,n = w_r,n · d (n ∈ N_r), w_r,n = A_n / Σ_{N_r} A — **단위 합력 1 N 을 면적 가중 분산(RBE3 등가)**. 체적력: f_k,n = b_n e, b_n = A_n t_n / Σ_{Ω} A t (n ∈ Ω — 지그 노드 몫은 반력으로 감; 밀도는 보정 크기에 흡수되어 불필요).
- 하중은 병진 3자유도만(회전 하중 0 — LT-3 과 같음).
- **열 크기 = 물리 합력 단위**: 영역·체적력 열은 단위 합력 1 N, 모드 열은 Σ_n ‖g_k,n‖ = 1 N(전역 합력이 0 에 가까울 수 있어 절댓값 합으로 정규화) → 계수 a_k 는 모두 N(§1(5) 정규화 항의 D = I).

**(4b) 모드 관성 기저 (D-JIG-15)** — 기준 설계(d000) 1회:
```
m_n  = A_n · t_n · ρ_t        (ρ_t = jig.rho_t_mm3, 기본 7.85e-9 t/mm³; 집중질량 — 병진 3자유도 같은 값, 회전 자유도 질량 0)
M    = diag(m ⊗ [1,1,1,0,0,0])  (6N)
K₀ φ = λ M φ,  spc = J 병진 123 (지그 구속)   — λ_1 ≤ … ≤ λ_m 최저 m = jig.n_modes 개 (0 이면 끔)
     eigsh(K_ff, k=m, M=M_ff, sigma=σ, which="LM", v0 = 자유 dof 전부 1/√n_f(결정적), tol=jig.modes_tol, maxiter=jig.modes_maxiter)
     σ = jig.modes_sigma(기본 0.0): σ = 0 이면 OPinv = 지그 정적 분해(§1(5) 의 분해) 재사용 — 추가 분해 0 (ARPACK mode 3·bmat G 는 OPinv 를
     항상 M·x 에만 적용 → 우변 회전 성분 = 0 이라 FactorizedSolve.solve(F (N,3)) 로 충분, 회전 성분 ≠ 0 이면 JIG_MODES_FAILED),
     σ ≠ 0 이면 (K − σM)_ff 를 scipy splu 로 1회 분해(추가 비용).
g_k,n = m_n · φ_k,n[:3] / Σ_n ‖m_n φ_k,n[:3]‖     (관성 하중 = M φ, Σ‖·‖ = 1 N 정규화; 부호 = 최대 절댓값 성분이 양수)
hz_k  = √λ_k / (2π)            (ρ_t 기준 — 보고용. ρ_t 는 균일 배율이라 φ·g 에 영향 없음, λ ∝ 1/ρ_t)
```
- 크기 a_k 는 **부호 자유**(법선 제약 없음). 모드 열도 §1(5) 하중 정규화 대상.
- 고유치 실패(수렴 안 됨·λ ≤ 0·OPinv 오류·예외) → 정보 `JIG_MODES_FAILED{err, n_conv}`, **모드 기저 없이 진행**(m = 0, 나머지 동일). 일부만 수렴하면 수렴한 것만(n_conv).
- 비교 정보 `hz_321`: 같은 M 으로 3-2-1 지지(스터디 `t.supports`, 기존 해석과 같은 spc) 최저 m 개(`jig.modes_ref321` 참일 때, 별도 splu 분해 1회 — 베이스라인만), `hz_ratio = hz_jig_1 / hz_321_1`. 실패는 null + 같은 정보 코드(stage 321).
- **설계 비교에서 모드 재계산 금지**: g_k 는 기준에서 1회 계산한 **고정 노드 하중 벡터**(같은 메시·같은 노드 ID)로 F_i 에 들어가고 안마다 그대로 쓴다(하중 제어 유지, §1(7)).


**(5) 보정 (D-JIG-5, D-JIG-16 개정)** — 엔트리 i 마다, 기저 공통:
```
U_k = 지그 정적해(K₀, spc = J 병진 123) 의 u[F, :3]  (k = 1..nb; 분해 1회 + nb 회 solve)
n̂_n = 노드 법선(node_weights.normal),  P_n = n̂_n n̂_nᵀ
W_n = (A_n / mean_F A) · (P_n + w_ip (I − P_n))     (w_ip = jig.w_inplane, 기본 0.1 — 면외 성분 우선, 면내 잔여 경시)
G = Σ_{n∈F} U_k,nᵀ W_n U_j,n (nb×nb),  h_i,k = Σ_{n∈F} U_k,nᵀ W_n u_tgt,i,n,  s_k = √G_kk (s_k = 0 열은 a_k = 0 고정 + 정보 JIG_BASIS_NULL)
ḡ_N = mean_{k: col_kind = 1} G_kk                    (단위 법선 가압의 가중 응답 제곱 — 정규화 척도)
목적: min_a (U a − u_tgt)ᵀ W (U a − u_tgt) + reg_force · ḡ_N · Σ_{k: col_kind ∈ {2,3,4}} a_k²     (D = I — 열이 이미 1 N 단위, §1(4))
정규화 좌표 b = D_s a (D_s = diag(s)):  Ĝ = D_s⁻¹ G D_s⁻¹ + λ I + diag(reg_force · ḡ_N / G_kk · [col_kind_k ≠ 1])   (λ = jig.ridge)
L = chol(Ĝ),  b* = argmin ‖Lᵀ b − L⁻¹ D_s⁻¹ h_i‖²  s.t.  b_k ≥ 0 (접촉 영역 법선 열, reg_sign = +1), 그 밖 자유
a_i = D_s⁻¹ b*   [N]          scipy.optimize.lsq_linear(method="bvls", tol=1e-12) — 결정적
F_i = Σ_k a_i,k f_k  (N,3)
```
- 법선 열은 정규화하지 않는다(가압 = 이 방법의 주 하중). 접선·체적력·모드 열은 "같은 크기의 법선 가압이 내는 응답" 척도로 벌점 → 면내(막) 응답만 내는 열은 크게 억제되고, 면외 굽힘을 내는 열(면외 체적력·모드)은 거의 그대로.
- **`reg_force` 기본 1.0e-3 근거(합성 측정, 2026-11-17 계약자, synth_sm.plate 600×300 t 0.8, 짧은 두 변 tie 6 묶음, 패치 6 + 체적력)**: 열별 G_kk / ḡ_N = 접선(가로) 6.4e-7 · 접선(세로) 5.8e-4 · 면내 체적력 8.3e-6·1.1e-5 · 면외 체적력 0.68. 축소 계수 ≈ 1/(1 + reg·ḡ_N/G_kk) → 면외 체적력 0.9985(reg 1e-3), 면내 열 ≤ 0.37~6e-4. 측정: (a) 법선 + 면외 체적력으로 만든 정확 목표 — reg ∈ {1e-4, 1e-3, 1e-2} 모두 MAC 1 − <1e-6, umax 오차 < 1e-6(손실 없음); (b) 같은 목표 + 면내 자기평형 잔여(최대 면외 변위의 5 %) — reg 0 이면 cancel 0.73·Σ|R| 20 234 N(w_ip 1) / 0.69·2 608 N(w_ip 0.1), reg ≥ 1e-4 이면 cancel 0.03·Σ|R| 206 N(정확 목표 하중 205.6 N 과 같음)·MAC 0.9941 그대로. → 1e-3 은 억제 하한(1e-4)과 손실 시작 위(1e-2 에서도 손실 없음) 사이 가운데 자릿수. Impl-Core 가 V-JIG-21 에서 같은 수치를 재확인한다.
- 메모리 = U(nb × |F| × 3 float64) 1벌(R-JIG-4), W_n 은 노드마다 즉석 계산(3×3 저장 안 함).

**(6) 기준 재현 진단 (D-JIG-6)** — u_fit,i = 같은 분해로 F_i 를 다시 푼 해(정확 = Σ a_k U_k):
```
mac,i      = (Σ_F u_fit·u_tgt)² / (Σ_F ‖u_fit‖² · Σ_F ‖u_tgt‖²)            (병진, 가중 없음)
umax_err,i = | max_F ‖u_fit‖ − umax_tgt | / umax_tgt
err_p95,i  = P95_F ‖u_fit − u_tgt‖ / umax_tgt                               (numpy percentile linear)
resid_rel,i= √( Σ_F A‖u_fit − u_tgt‖² / Σ_F A‖u_tgt‖² )
R_r = 영역 r 합력 벡터 = Σ_d a_{r,d} d  [N],  (F_n, F_t1, F_t2) = 영역 틀 성분,  R_b = 체적력 합력 [N],  R_m,k = a_k Σ_n g_k,n [N](모드 열 합력)
F_sum_abs,i = Σ_r ‖R_r‖ + ‖R_b‖ + Σ_k |a_k|(모드 — 1 N 정규화라 |a_k| = 그 열의 Σ‖f‖)
cancel_rel,i = 1 − ‖Σ_r R_r + R_b + Σ_k R_m,k‖ / F_sum_abs   (0 = 모두 같은 방향, 1 = 완전 상쇄 — 하중이 서로 지우는 정도)
active_r   = ‖R_r‖ > jig.active_tol · max_r ‖R_r‖,   n_active,i = Σ active
react_rel,i= ‖Σ F_i + Σ_J 반력‖ / Σ_n ‖F_i,n‖                               (정적 평형 확인 ≤ 1e-9)
```
- **모드 포함/제외 두 번 보고**(D-JIG-15): `with_modes` = 위 맞춤(주 결과 — 순위 하중 F_i 는 이것), `without_modes` = 같은 G·h 에서 모드 열을 뺀 부분 문제를 같은 방법으로 다시 풀어 mac·umax_err·err_p95·resid_rel 만(추가 solve 없음 — u_fit = U a). 모드 m = 0 이면 without_modes = null(같은 값). 화면·JIG_FIT_POOR 판정은 with_modes.
- cancel_rel > `jig.cancel_warn`(기본 0.5) 인 엔트리 → 경고 `JIG_LOAD_CANCEL{label, cancel_rel, F_sum_abs}`(BD_POST 판정, 순위 계속). 단, 지그 사이를 S 자로 굽히는 목표처럼 정당한 반대 방향 가압도 값이 커질 수 있어 경고만.
- `mac < jig.mac_min` 또는 `umax_err > jig.umax_err_max` 인 엔트리가 하나라도 있으면 경고 `JIG_FIT_POOR`(BD_POST 판정, **순위는 계속 산출**, 화면 ④ 한 줄에 표시). 임계값은 해시 밖(설정만 바꿔 BD_POST 재실행으로 판정 갱신).

**(7) 설계 비교 (D-JIG-7)** — 같은 메시 계획(once, sm_ref base)에서만:
```
안 d: K_d(안 좌표) · spc = 같은 지그 노드 ID(J) · 하중 F_i 그대로(같은 노드 ID·같은 a — 하중 제어; 모드 관성 열도 기준 g_k 고정 벡터, 안마다 모드 재계산 금지)
u_d,i = K_d⁻¹ F_i,   C_jig,d,i = Σ_n F_i,n·u_d,i,n [N·mm],   umax_jig,d,i = max_{n∈Ω} ‖u_d,i,n‖ [mm]  (지그 노드 = 0)
```
- 베이스라인 d000 도 같은 함수(`respond`, 같은 분해 경로) → C_jig,d000,i = 기준값, score_jig(d000) = 1 정확.
- **순위(metric = jig)**: BD-D-6 그대로 M_{d,i} = C_jig,d,i — M_ref = max_i M_{d000,i}, score_d = max_i M_{d,i} / M_ref, 개선율 = 1 − score, 최악 ESL = argmax, 오름차순·동률 id 사전순, ESL별 비·pareto 같은 값. 엔트리 가중 = 기존 score 와 동일(가중 없음, 최악 ESL).
- 보조: `umax_jig`(행) = max_i umax_jig,d,i / max_i umax_jig,d000,i, `score_jig`(행) = 위 score(metric 과 무관하게 지그 값이 있으면 항상 — 비교용).
- **fallback**: metric = jig 인데 (계획 `sm_jig = none`) 또는 (베이스라인 지그 status = fallback) → 순위 지표 = `solve`(`metric_effective = "solve"`), 결과 `jig.status` = `unsupported` | `fallback` + 코드 1개. 규칙은 모드 무관 고정(D-JIG-8) — 계획 표에는 지그 가능 여부(`sm_jig`)만 둔다.
- 기존 C(=solve)·score_solve·C_lin·C_ritz·rho·imbalance·umax_def 는 **그대로 산출**(정보·비교용, 사용자 지시 11).

## 2. 흐름

```
DOE_RUN
  BD_BASELINE d000  (기존) 주 해석 + _sm_apply → prep/sm_ref.npz
                    (신규) _jig_apply(base):  jig_fix → J → select_jig_nodes 검사
                           → u_tgt(sm_ref u) → [jig_ctx 면 deck 표면 읽기(jig_surf)] → select_regions(접촉 + 부족분 패치 보충)
                           → factor(K₀, J) → [n_modes > 0: lumped_mass → jig_modes(σ = 0 이면 같은 분해) → mode_loads; modes_ref321 이면 3-2-1 모드(정보)]
                           → load_basis(…, modes) → U(nb solves) → fit_loads(K 엔트리, 모드 포함·제외) → respond(F_i) = u_fit·C_jig_ref
                           → prep/jig.npz + prep/jig.json(진단), per_esl += C_jig·umax_jig
                           실패 = jig.json status fallback + code(베이스라인 실패로 만들지 않음 — BASELINE_FAILED 금지)
  BD_DESIGNS 안     (기존) 주 해석 + _sm_apply
                    (신규) _jig_apply(design): jig.npz 읽기 → forces(basis, a_i) → design_response(K_d, J) → per_esl += C_jig·umax_jig
                           (jig.npz 없음·status fallback = 키 null, 실패 = null + JIG_DESIGN_FAILED)
  BD_POST           (기존) rank(metric = metric_effective) …
                    (신규) jig 블록(jig.json + 임계값 판정 JIG_FIT_POOR·JIG_TIE_RELATIVE·JIG_LOAD_CANCEL, hz = ρ_t 환산) → post/result.json.jig, ranking.csv 끝 열 4개
```
- 계산 위치는 sm_ref 와 같이 **베이스라인 평가 1회**(파일은 `prep/`), 안은 `design_response` 만. 워커 변경 없음(지그 노드 출처 `prep/fixed`·`fixed_transfer.json` 은 이미 있음).
- 지그는 스냅샷에 `rank.jig` 가 있고 `jig.enabled` 이고 계획 `sm_jig = base` 이면 **metric 과 무관하게 항상 계산**(Q-JIG-1 확정 — SM-6 과 같은 이유: metric 은 해시 밖, BD_POST 만 바꿔 비교).

## 3. 결정

| ID | 결정 | 근거 |
|---|---|---|
| D-0.23.0-JIG-1 | 지그 = tie 노드(`fix_kinds`, 기본 INTER_TYPE2 둘) 병진 123 고정, 회전 자유. 출처 = 계획 열 `jig_fix`(fixed\|xfer\|none). 노드 0 = `JIG_NO_TIE`, 성분마다 ≥ 3 비공선 아님 = `JIG_SUPPORT_DEGENERATE` | 사용자 확정 1·3. ShellModel spc 는 병진만 |
| D-0.23.0-JIG-2 | u_tgt = sm_ref 병진에서 지그 노드 기준 강체 제거(**D-JIG-16 으로 유한 회전 Kabsch 로 개정** — 처음 안은 미소 강체 `remove_linear_rigid`). tie_rel 진단·경고만, 강제 변위는 후속 | 지그 노드 기준 비교 |
| D-0.23.0-JIG-3 | 가압 후보 = 대상 파트 밖 deck 표면(쉘 + 솔리드 외곽 면, 변형 전) 까지 거리 ≤ gap 인 비지그 노드, 상대 파트별 연결 성분, 면적 상위 max_regions. 부족·deck 없음 = **접촉 영역 유지 + 부족분(min_regions − n_c)만 PCA 격자 패치로 보충**(패치 후보 = 접촉 영역·지그 노드 제외, 접촉 0 = 전부 패치 — Q-JIG-2 확정). 영역마다 kind 기록. 거리 = cKDTree 청크(메모리 O(T + chunk·knn)) | h3d 에 다른 부품 없음(사용자 확정 3), T01 분포 없음 |
| D-0.23.0-JIG-4 | 기저 = 영역마다 법선 1 + 접선 2 단위 합력(면적 가중 분산 = RBE3 등가) + 체적력 3(면적×두께). 접촉 법선은 상대 부품 → 대상 방향 | 접촉은 밀기만, 몇 곳 하중 = 상쇄 없음 |
| D-0.23.0-JIG-5 | 보정 = 면적 가중 최소제곱, 접촉 법선 ≥ 0, ridge λ, 정규방정식 + BVLS(결정적) | nb ≤ 3·max_regions + 3 작음, 메모리 = U 1벌 |
| D-0.23.0-JIG-6 | 기준 재현 진단 MAC·umax 오차·P95·잔차비·영역 합력·활성 수·상쇄비·반력 평형을 플랫폼이 보고. 임계 미달 = `JIG_FIT_POOR` 경고(순위 계속) | 사용자 확정 2 |
| D-0.23.0-JIG-7 | 설계 비교 = 같은 J·같은 노드 하중 F_i(하중 제어)로 K_d 재풀이, C_jig = F·u, umax_jig; 순위 구조 BD-D-6 그대로(metric_key jig → C_jig). 같은 메시 계획만(결정 A) | 사용자 확정 1 |
| D-0.23.0-JIG-8 | `rank.metric` 값 `jig` 추가, **새 스터디 기본 jig**(DEFAULTS·pydantic·yaml 2). 지그 불가·실패 → 순위 = solve(모드 무관 고정 규칙), `jig.status` 로 표시. 옛 스냅샷 = 스냅샷 값 그대로(`rank` 키에 metric 이 없으면 **solve 명시** — 새 DEFAULTS 를 따라가지 않게 `_sm` 수정) | 사용자 확정 4 |
| D-0.23.0-JIG-9 | 공용 순수 모듈 `esl/doe/jig.py`(§5.1). deck 표면 읽기 = IO 모듈 `esl/doe/jig_surf.py`(파서·assem_full 재사용). scipy(lsq_linear·cKDTree·csgraph) 필수 — pyproject 이미 의존, 대체 경로 없음 | AGENTS.md 코드 구조 원칙 |
| D-0.23.0-JIG-10 | 계획 표 열 3개 `sm_jig`·`jig_fix`·`jig_ctx`(§5.2), `PLAN_VERSION` 불변. 시나리오 이름 분기 없음 | 결정 A·AGENTS.md |
| D-0.23.0-JIG-11 | 이어하기: 스냅샷에 `rank.jig` 가 있을 때만 `_cfg_hash` keep 에 `jig = config_hash(jig_hash_view(jig))`(해시 밖 = `HASH_EXCLUDE` §6 — 임계값 `mac_min`·`umax_err_max`·`tie_rel_warn`·`cancel_warn`, 보고용 `rho_t_mm3`·`modes_ref321`). legacy 해시 불변 | LT-12·SM-6 선례 |
| D-0.23.0-JIG-12 | 결과: per_esl `C_jig`·`umax_jig`, 행 `score_jig`·`umax_jig`·`C_jig{}`, result.json 최상위 `jig{…}`, ranking.csv 끝 열 `C_jig, umax_jig, jig_fit_mac, jig_umax_err`(새 스냅샷만 — 기존 열 순서 불변). 화면 = 정의 문구 + 기준 재현 한 줄 | 사용자 지시 10·필수 정보만 |
| D-0.23.0-JIG-13 | (Q-JIG-1 확정 2026-11-17) 새 스냅샷은 metric 과 무관하게 항상 지그 재풀이(안마다 분해 +1) | metric 만 BD_POST 에서 바꿔 같은 실행으로 비교(SM-6 원칙) |
| D-0.23.0-JIG-14 | (Q-JIG-2 확정 2026-11-17) 접촉 영역 유지 + 부족분(min_regions − n_c)만 PCA 격자 패치 보충, 패치 후보 = 비지그 ∖ 접촉 영역 노드, 영역 kind contact\|patch·묶음 regions_from contact\|mixed\|patch 기록, 접촉 0 = 전부 패치, 보충 시 `JIG_REGION_FALLBACK`. 규칙 = `jig.select_regions` 한 곳 | 물리 접촉 영역 보존(사용자 확정) |
| D-0.23.0-JIG-15 | (2026-11-17 17:44 사용자) **모드 관성 기저**: 기준 설계 지그 구속 집중질량(A·t·ρ_t) 저차 탄성 모드 φ_k(k ≤ n_modes, 기본 4) 를 eigsh shift-invert(σ = 0 = 지그 분해 재사용)로 구하고 g_k = Mφ_k(Σ‖·‖ = 1 N, 부호 자유)를 기저에 추가. 설계마다 재계산 금지(고정 노드 하중). 실패 = `JIG_MODES_FAILED` 후 모드 없이. 진단 = 모드 포함/제외 MAC·umax 오차, 지그·3-2-1 고유진동수(Hz). jig.npz 에 영역·체적력·모드 하중을 노드 면적당 밀도(N/mm²)로도 저장(v0.24.0 메시 독립 전달용, §5.5 키 고정) | 덴팅 = 섀시 전역 굽힘·비틀림 휘청(처짐 ≫ 두께) — 균일 체적력은 휘청 관성 분포를 못 담음 |
| D-0.23.0-JIG-16 | (2026-11-17 메인, Impl-Core af0385b 보고) **유한 회전 목표·법선 가중·하중 정규화·상쇄 경고**: u_tgt = 지그 노드 Kabsch 유한 회전 제거(§1(2)), 맞춤 가중 W_n = A(nnᵀ + w_inplane(I − nnᵀ))(기본 0.1), 접선·체적력·모드 계수에 Tikhonov reg_force·ḡ_N·Σa²(기본 1e-3 — §1(5) 합성 근거), cancel_rel > cancel_warn(0.5) = `JIG_LOAD_CANCEL`(순위 계속), `basis_tangential` false = 법선만(비교용) | 면내 자기평형 잔여 목표에서 맞춤이 면내 하중을 상쇄시켜 씀(cancel 0.76, 면내 하중 = 법선력 10²~10³ 배, ridge 로 불변) — #63 상쇄 하중 재발 위험 |

### 3.1 보류(후속, 이번 범위 아님)

| 항목 | 내용 | 상태 |
|---|---|---|
| 시간 증분 ESL(DiESL식) | 낙하 시간 구간마다 증분 ESL 을 만들어 같은 메시에서 기준 재현을 참조하는 방식 | **보류**(2026-11-17 17:44 사용자 — 설계 활용 목적상 지그 ESL 주력) |
| 지그 노드 강제 변위 | u_tgt[J] 를 강제 변위 열로(R-JIG-1) | 후속 |
| 메시 독립 하중 전달 | jig.npz 밀도(N/mm²)로 다른 메시에 하중 전달(④·옛 ③ 지그) | v0.24.0 후보 |

## 4. API · 스키마 · 고정 필드명

새 경로 없음. 결과 응답(`GET /doe/studies/{sid}/results`, `DoeResultOut`)과 설정(`GET /doe/settings` 의 `rank`)만 바뀜.

**고정 필드명 (schemas.py ↔ types.ts, `npm run check:api` 대조 — 이름 바꾸지 말 것)**

| 스키마 | 필드 |
|---|---|
| `DoeResultOut` (변경) | `metric: Literal["lin","solve","jig"] \| None`, `metric_effective: Literal["lin","solve","jig"] \| None`, **`jig: DoeJigOut \| None = None`**(옛 스터디·지그 블록 없는 스냅샷 = null) |
| `DoeJigOut` (신규) | `status: Literal["ok","poor","fallback","unsupported"]`, `code: str \| None`(fallback·unsupported 사유 코드 1개, ok·poor = null), `region_source: Literal["contact","mixed","patch"] \| None`(= jig.json `regions_from`), `n_jig: int`, `n_regions: int`, `n_contact: int`, `n_patch: int`, `fit_mac_min: float \| None`(엔트리 최솟값, **모드 포함**), `fit_umax_err_max: float \| None`(엔트리 최댓값, 모드 포함), `fit_mac_min_nomodes: float \| None`, `fit_umax_err_max_nomodes: float \| None`(모드 제외 맞춤 — 모드 0 이면 null), `cancel_rel_max: float \| None`, `tie_rel_max: float \| None`, `n_modes: int`(실제 쓴 모드 수, 실패·끔 = 0), `hz_jig: list[float]`(지그 구속 1..n_modes 고유진동수 Hz, ρ_t 기준 — 끔·실패 = []), `hz_321: list[float] \| None`(3-2-1 기준, `modes_ref321` 거짓·실패 = null), `hz_ratio: float \| None`(hz_jig[0] / hz_321[0]), `th: DoeJigThOut`, `entries: list[DoeJigEntryOut]` |
| `DoeJigThOut` (신규) | `mac_min: float`, `umax_err_max: float`, `tie_rel_warn: float`, `cancel_warn: float`(스냅샷 값) |
| `DoeJigEntryOut` (신규) | `entry_id: str`, `label: str`, `mac: float`(모드 포함), `umax_err: float`(모드 포함), `mac_nomodes: float \| None`, `umax_err_nomodes: float \| None`, `err_p95: float`, `n_active: int`, `F_sum_abs: float`(N), `cancel_rel: float`, `rot_deg: float`(지그 노드 Kabsch 회전각) |
| ranking 행 dict(통과, `DoeRankRow` 문서화) | `score_jig?: number \| null`, `umax_jig?: number \| null`(비), `C_jig?: Record<entry_id, number> \| null`(N·mm) — 지그 값이 있을 때만 |
| per_esl 행(통과) | `C_jig: float \| null`(N·mm), `umax_jig: float \| null`(mm) |
| `DoeRankMetric`(types.ts) | `"lin" \| "solve" \| "jig"` |
| 설정 `BeadDoeRankCfg` | `metric: Literal["lin","solve","jig"] = "jig"`, `jig: BeadDoeRankJigCfg`(§6) |

- `status` 판정(BD_POST): `unsupported` = 계획 `sm_jig = none`(코드 `JIG_UNSUPPORTED`) · `fallback` = jig.json status fallback(코드 = 그 코드) · `poor` = JIG_FIT_POOR 조건(모드 포함 값) · 그 밖 `ok`. `JIG_LOAD_CANCEL`·`JIG_TIE_RELATIVE` 는 status 를 바꾸지 않음(경고만). hz 는 jig.json `lam`·`rho_t_used` 에서 hz = √(λ·ρ_used/ρ_now)/(2π) 로 BD_POST 가 현재 스냅샷 ρ_t 로 환산(λ ∝ 1/ρ_t 정확). `metric_effective = "jig"` ⇔ metric = jig ∧ status ∈ {ok, poor}.
- `rank{…}`(스냅샷 출력 `_rank_snapshot_out`)는 키 4개 그대로 + `metric_effective`·`cross_mesh`(기존). 임계값은 `jig.th` 로만.
- `rank_snapshot(c)`: `{metric, lin_form, lin_valid, imbalance_warn, jig{…설정 전체}, schema: 2}`(jig 블록이 있으면 schema 2, `jig.enabled = false` 면 jig 키 없음·schema 1). `inputs.rank_metric` 그대로.
- pydantic 검사: `metric == "jig"` 인데 `jig.enabled = false` → 설정 로드 실패(`CONFIG_INVALID`). 새 요청 키 없음(설정만, SM 선례).
- openapi(`docs/contracts/openapi_p1b.json`) 재생성.

### 오류 · 경고 · 정보 코드 (문구 원본 `resources/doe_messages.json` `messages`, 화면 대체 문구 `api/doe.ts:JIG_CODE_TEXT`)

| 코드 | 등급 | 위치 | 조건 · 결과 |
|---|---|---|---|
| `JIG_UNSUPPORTED` | 정보 | post | 계획 `sm_jig = none`(옛 ③·④) 인데 metric jig → solve 순위 |
| `JIG_NO_TIE` | 경고 | baseline | 지그 노드 0(tie 없음·`prep/fixed` 없음·FIXED_INFO_MISSING·xfer 0) → fallback solve |
| `JIG_SUPPORT_DEGENERATE` | 경고 | baseline | 성분별 지그 노드 < 3 또는 공선 → fallback solve. detail `n_comp`, `bad_comp_nodes` |
| `JIG_SKIPPED` | 경고 | baseline·design | 지그 계산 예외(`stage`, `err` 코드) — 베이스라인이면 fallback solve |
| `JIG_SURF_UNAVAILABLE` | 경고 | baseline | `jig_ctx` 가 deck 인데 읽기 실패(파일 없음·`RAD_PARSE_ERROR`·`PATH_OUTSIDE_ROOT`) → 패치 |
| `JIG_SURF_TOO_LARGE` | 경고 | baseline | 상자 안 표면 삼각형 > `jig.max_surf_tris` → 패치 |
| `JIG_REGION_FALLBACK` | 경고 | baseline | 접촉 영역 < min_regions 라 패치로 보충함(혼합 또는 전부 패치 — `reason` = few_contact \| no_deck \| surf_failed, `n_contact`, `n_patch`). 보충 없으면 없음 |
| `JIG_FIX_UNFILTERED` | 정보 | baseline | `jig_fix = xfer`(종류 필터 없음) |
| `JIG_NORMAL_FREE` | 정보 | baseline | 접촉 영역 법선 부호 모호(간격 0) → 부호 자유 영역 수 |
| `JIG_BASIS_NULL` | 정보 | baseline | 응답 0 기저 열(a = 0 고정) 수 |
| `JIG_MODES_FAILED` | 정보 | baseline | 지그(또는 3-2-1 정보) 고유치 실패(`stage` jig\|321, `err`, `n_conv`) → 수렴한 모드만·없으면 모드 기저 없이 진행 |
| `JIG_LOAD_CANCEL` | 경고 | post | cancel_rel > cancel_warn 인 엔트리(라벨·값·F_sum_abs) — 맞춤 하중이 서로 상쇄(#63 꼴 위험), 순위 계속 |
| `JIG_FIT_POOR` | 경고 | post | MAC < mac_min 또는 umax 오차 > umax_err_max 인 엔트리(라벨·값) — 순위 계속 |
| `JIG_TIE_RELATIVE` | 경고 | post | tie_rel > tie_rel_warn — 지그 노드끼리도 변형(고정 지그 한계) |
| `JIG_DESIGN_FAILED` | 경고 | design | 안 지그 재풀이 실패(`err`) → 그 안 C_jig null(metric jig 이면 순위 밖 `n_failed["jig"]`) |

## 5. 구조 — 공용 모듈 / 계획 표 / 독립성

### 5.1 공용 순수 모듈 `esl/doe/jig.py` (신규, Impl-Core)

- import 허용: `numpy`, `scipy.sparse`, `scipy.sparse.csgraph`, `scipy.spatial`, `scipy.optimize`, `esl.errors`, `esl.mech.shell`(ShellModel·solver_check_kwargs), `esl.mech.kabsch`. **금지**: `esl.doe.*`(stiffness_metric·load_transfer 포함), 파일 IO, 설정 해석(설정 dict 는 호출자가 해석해 키워드로 넘김), 시나리오·계획 이름.
- 상수: `SCHEMA = "esl/doe_jig/1"`, `TIE_KINDS = ("INTER_TYPE2_SECONDARY", "INTER_TYPE2_MAIN")`(문서용 — 비트 변환은 호출자), `REGION_CONTACT = 1`, `REGION_PATCH = 2`.
- mesh dict = 기존 해석 mesh(`node_id (N,) int64`, `x0 (N,3)`, `conn (E,4) int64`(tria 는 `elem_type == 3`, 4번째 칸 무시), `elem_type (E,)`, `thickness·E·nu (E,)`).

| 함수 | 시그니처 · 입출력 |
|---|---|
| `node_weights` | `node_weights(mesh) -> {"area": (N,) float64 mm², "normal": (N,3) 단위(부호 = 이웃 요소 법선 면적 가중 합), "thick": (N,) mm, "elem_area": (E,), "elem_normal": (E,3)}` — 고립 노드 area 0·normal 0 |
| `lumped_mass` | `lumped_mass(weights, rho_t) -> (N,) float64` — m_n = area·thick·ρ_t [t] (`node_weights` 결과 재사용). 6N 대각은 호출부에서 `np.repeat` 대신 `mass_diag6(m) -> (6N,)`(병진 m, 회전 0) |
| `jig_modes` | `jig_modes(K, M, fixed, n, sigma, *, opinv=None, tol=0.0, maxiter=None) -> {"lam": (m,) float64 오름차순, "phi": (m, N, 6), "hz": (m,), "n_conv": int}` — K = `ShellModel.K()` (6N csr), M = (6N,) 대각, fixed = 구속 dof 인덱스(6·node + d), n = 요청 수, sigma = shift(ω² 단위). `opinv` = `LinearOperator`(n_f) 주면 그것(σ = 0 지그 분해 재사용), 없으면 `(K − σM)_ff` splu. v0 결정적, 부호 = φ 병진 최대 절댓값 성분 양수. 실패 = `EslError("JIG_MODES_FAILED")`(n_conv detail) |
| `opinv_from` | `opinv_from(h, n_nodes) -> LinearOperator` — FactorizedSolve `h` 로 자유 dof 우변 b → K_ff⁻¹ b(우변 회전 성분 ≠ 0(> 1e-14·‖b‖) 이면 `JIG_MODES_FAILED`) |
| `mode_loads` | `mode_loads(phi, m) -> (m_modes, N, 3) float64` — g_k = m·φ_k[:, :3], Σ_n ‖g_k,n‖ = 1, 부호 규칙 §1(4b) |
| `select_jig_nodes` | `select_jig_nodes(mesh, node_id, *, kind_mask=None, kind_bits=0) -> {"idx": (J,) int64 정렬, "node_id": (J,), "n_comp": int, "code": None \| "JIG_NO_TIE" \| "JIG_SUPPORT_DEGENERATE", "detail": dict}` — `kind_mask is None` = 필터 없음(xfer), 아니면 `kind_mask & kind_bits ≠ 0`. 메시에 없는 ID 는 버림(`detail.n_missing`) |
| `target_disp` | `target_disp(x, u3, jig_idx, fit_mask) -> {"u_tgt": (N,3), "R": (3,3), "t": (3,), "rot_deg": float, "umax_tgt": float, "tie_rel": float}` — §1(2) 유한 회전(D-JIG-16, `kabsch.fit` + 중심화 식). `fit_mask (N,) bool` = F |
| `contact_regions` | `contact_regions(mesh, cand_mask, surf, *, gap_mm, knn, chunk_nodes, max_regions, min_regions, min_nodes, min_area_mm2, weights) -> {"regions": [Region], "n_contact_nodes": int, "n_found": int, "ok": bool}` — 접촉 영역만(보충 없음, 순서 = 정렬 키 상위 max_regions). `surf = {"x": (P,3), "tri": (T,3) int64, "tri_part": (T,) int64}`, `ok = len(regions) ≥ min_regions`(정보용 — 보충 판단은 `select_regions`). `Region = {"kind": 1, "part": int, "nodes": (m,) int64 정렬, "area": float, "center": (3,), "sign_ref": (3,) = Σ A(x − q)}` |
| `patch_regions` | `patch_regions(mesh, cand_mask, *, exclude_mask, n_fill, patch_count, min_nodes, weights) -> {"regions": [Region(kind 2, part −1, sign_ref 0)], "n_cells": int}` — 후보 = `cand_mask & ~exclude_mask`(exclude = 접촉 영역 노드 ∪ J), 격자 P = `patch_count`, 상위 `n_fill` 개(§1(3)). `n_fill = 0` → 빈 목록 |
| `select_regions` | `select_regions(mesh, cand_mask, jig_idx, surf, *, gap_mm, knn, chunk_nodes, max_regions, min_regions, min_nodes, min_area_mm2, patch_count, weights, surf_reason=None) -> {"regions": [Region], "regions_from": "contact"\|"mixed"\|"patch", "n_contact": int, "n_patch": int, "fill_reason": None\|"few_contact"\|"no_deck"\|"surf_failed", "n_contact_nodes": int}` — **보충 규칙의 유일한 구현**: `surf is None`(no_deck·surf_failed = `surf_reason`) → n_c = 0, 아니면 `contact_regions`; n_fill = 0 (n_c ≥ min_regions) \| min_regions − n_c (1 ≤ n_c) \| min(patch_count, max_regions) (n_c = 0); `patch_regions(exclude_mask = 접촉 노드 ∪ J)`; 결과 = 접촉 + 패치(합계 ≤ max_regions). stages 는 이 함수만 부름 |
| `load_basis` | `load_basis(mesh, regions, weights, omega_mask, *, body_force: bool, tangential: bool = True, modes=None) -> Basis` — `modes` = `mode_loads` 결과 (m,N,3) 또는 None. `Basis = {"col_kind": (nb,) int8(1 법선·2 접선·3 체적력·4 모드), "mode_f": (m,N,3) \| None, "reg_ptr": (R+1,) int64, "reg_node": (Σm,) int64, "reg_w": (Σm,) float64(영역마다 합 1), "reg_dir": (R,3,3)(행 = n, t1, t2), "reg_sign": (R,) int8(+1 = 법선 ≥ 0 제약, 0 = 자유), "reg_kind": (R,) int8, "reg_part": (R,) int64, "body_w": (N,) float64(합 1, Ω 밖 0) \| None, "nb": int, "n_normal_free": int}` |
| `forces` | `forces(basis, a, n_nodes) -> (N,3) float64` — a (nb,), §1(4) 선형 조합(희소 합, 결정적 순서) |
| `factor` | `factor(mesh, jig_idx, solver_cfg) -> FactorizedSolve` — `ShellModel(…, drill_factor, backend, **solver_check_kwargs(solver_cfg)).factorize([(i,"123") for i in jig_idx])`. `SOLVER_SINGULAR` → `EslError("JIG_SUPPORT_DEGENERATE")`. 모드용 K 는 `h.model.K()`(같은 조립) |
| `basis_response` | `basis_response(h, basis, fit_mask) -> {"U": (nb, M, 3) float64, "null_cols": [k]}` — M = fit_mask 수, solve nb 회 |
| `fit_loads` | `fit_loads(U, u_tgt_fit, w_fit, n_fit, basis, *, ridge, w_inplane, reg_force, drop_kinds=()) -> {"a": (nb,) N, "resid_rel": float, "n_bound_active": int, "g_N": float}` — §1(5). u_tgt_fit (M,3), w_fit (M,) 면적, n_fit (M,3) 노드 법선. `drop_kinds=(4,)` = 모드 제외 맞춤(그 열 a = 0) |
| `respond` | `respond(h, loads, *, umax_mask=None) -> [{"entry_id", "C_jig", "umax_jig", "react_rel", "u": (N,3) \| None}]` — loads = [(entry_id, F (N,3))], keep_u 는 베이스라인 진단에만(`keep_u=True` 키워드) |
| `fit_report` | `fit_report(u_fit, u_tgt, fit_mask, weights, basis, a, *, jig_idx, active_tol, u_fit_nomodes=None) -> {"with_modes": {"mac", "umax_err", "err_p95", "resid_rel"}, "without_modes": {같은 4키} \| None, "modes": [{"k", "a"}], "mac", "umax_tgt", "umax_fit", "umax_err", "err_p95", "resid_rel", "F_sum_abs", "cancel_rel", "n_active", "body": [3] \| None, "forces": [{"region", "kind", "part", "F_n", "F_t1", "F_t2", "F": [3], "active"}]}` — §1(6) |
| `design_response` | `design_response(mesh, jig_idx, loads, solver_cfg, *, umax_mask=None) -> {"rows": respond 행(u 없음), "stats": {"seconds", "n_solves", "backend"}}` = `respond(factor(…), …)` |
| `hash_view` | `hash_view(jig_cfg: dict) -> dict` — `HASH_EXCLUDE = ("mac_min", "umax_err_max", "tie_rel_warn", "cancel_warn", "rho_t_mm3", "modes_ref321")` 뺀 사본(해시용, D-JIG-11) |

- 구현 가산(Core 2026-11-17, 시그니처 불변·키만 추가): `select_regions` 반환 += `n_fill`(규칙상 보충 수)·`n_found`(필터 통과 접촉 영역 수 — jig.json `surf.n_found`)·`n_cells`(비어 있지 않은 패치 셀 수); 접촉 Region += `gap_mm`(법선 부호 자유 판정용 — `load_basis` 가 읽음); `Basis` += `n_nodes`; `fit_report` += `tie_rel`; 공개 보조 `nearest_tri(xq, surf, *, gap_mm, knn, chunk_nodes) -> {dist, tri, q}`(거리 계산 본체, 후보 없음 = inf·−1). `regions_from` 은 실제 결과 기준(1 ≤ n_c < min_regions 인데 패치 후보 소진으로 n_patch = 0 이면 `contact`, `fill_reason` 은 그대로 기록). `factor` 의 `solver_cfg` 키 = `drill_factor`·`backend`(+ 해 검사 키), 없으면 1e-4·auto.
- 결정성: 같은 입력 → 비트 동일(정렬 키·동률 규칙 고정, BVLS, numpy 결정적 합 순서). 진단은 순수 dict(파일 쓰기는 stages).
- 성능 예산: 베이스라인 = 분해 1 + solve (nb + K) 회 + 거리 계산 1회 + 모드(σ = 0: 추가 분해 0, ARPACK solve ≈ 수십 회; `modes_ref321` = splu 분해 1 + 수십 회). 안 = 분해 **1 추가** + solve K 회(기존 3-2-1 해석과 별도 — R-JIG-3). 거리 계산 N_c = 30만·T = 200만에서 ≤ 60 s·추가 피크 ≤ 400 MB(V-JIG-8).
- 참고 스킬: 대규모 최근접 구현은 `geom-proximity-scaling` 지침(청크·KD-tree·비트 동일)을 따른다.

### 5.2 계획 표 열 (`esl/doe/transfer_plan.py`, Impl-Backend)

| 계획 행 | `sm_jig` | `jig_fix` | `jig_ctx` | 이유 |
|---|---|---|---|---|
| `case_once` (same, select+case) | `base` | `fixed` | `case` | 기준 메시 = 원 Case 파트, 같은 좌표 deck |
| `bmesh_once` (mesh, select+mesh) | `base` | `fixed` | `mesh` | B 메시 fixed-scan(`prep/fixed`), 업로드 사본 deck(다른 부품 없으면 패치) |
| `step_once` (select+step) | `base` | `xfer` | `none` | B fixed-scan 없음 → A 체결점 이전, rad 없음 → 패치 |
| `step_per_design` (옛 ③) | `none` | `none` | `none` | 다른 메시(결정 A — sm_ref 없음) |
| `compare_per_shape` (④) | `none` | `none` | `none` | 다른 메시 |

- `PLAN_COLS` 끝에 `"sm_jig", "jig_fix", "jig_ctx"` 추가, 값 검사 `JIG_VALUES = {"sm_jig": ("base","none"), "jig_fix": ("fixed","xfer","none"), "jig_ctx": ("case","mesh","none")}` 를 `plan_for` 에서(`BS_VALUES` 와 같은 방식, 빈 칸 = `CONFIG_INVALID`). 불변식: `sm_jig = base ⇒ sm_ref = base ∧ sm_disp[1] = "I" ∧ sm_rank = metric`(시험으로 고정).
- `metric_effective(plan, metric, jig_ok: bool = True) -> str`: `metric == "jig"` 이면 `"jig" if plan["sm_jig"] == "base" and plan["sm_rank"] == "metric" and jig_ok else "solve"`, 그 밖 기존 그대로(기존 호출 바이트 동일). `cross_mesh` 불변. `PLAN_VERSION` 불변.

### 5.3 stages 통합 (`esl/doe/stages.py`, Impl-Backend)

- `_sm(c)`: `out["metric"]` 은 스냅샷 값, **스냅샷 `rank` 에 metric 키가 없으면 `"solve"`**(DEFAULTS 기본이 jig 로 바뀌어도 옛 동작 유지 — D-JIG-8). 허용 값 `smm.METRICS`(jig 포함). 반환에 `jig`(스냅샷 `rank.jig` 를 `settings()["rank"]["jig"]` 위에 합친 해석값, 없으면 None) 추가.
- `_jig(c) -> dict | None` = `_sm(c)["jig"]` 이 있고 `enabled` 이고 계획 `sm_jig == "base"` 일 때 그 설정, 아니면 None.
- `_cfg_hash`: `_jig(c)` 가 있으면 `keep["jig"] = ev.config_hash(jig.hash_view(...))`.
- `bd_eval`: `_sm_apply` 바로 뒤 `if _jig(c) is not None: r["warnings"] += _jig_apply(c, t, did, mesh, loads, reg_e, r)`. `_jig_apply` 는 예외를 잡아 per_esl `C_jig`·`umax_jig` = null + `JIG_SKIPPED`/`JIG_DESIGN_FAILED`(베이스라인 실패 금지).
  - 베이스라인: 지그 노드(계획 `jig_fix`: `fixed` = `pio.read_fixed(prep/fixed)` + 비트 = `FIXED_KINDS.index(k)` 합, `xfer` = `step_graph` 의 `fixed_transfer.json node_id`), u_ref = `prep/sm_ref.npz` `u[:, :, :3]`(node_id 순서 맞춤 — `_sm_eval` 과 같은 searchsorted), Ω = `_sm_omega` 노드, 표면 = `jig_surf.other_surfaces`(계획 `jig_ctx`), 이후 §2 순서. 산출 `prep/jig.npz`(§5.5)·`prep/jig.json`.
  - 베이스라인 모드: `jig.n_modes > 0` 이면 `lumped_mass(node_weights, rho_t_mm3)` → `jig_modes(h.model.K(), mass_diag6(m), 지그 dof, n_modes, modes_sigma, opinv = opinv_from(h) if σ == 0)` → `mode_loads` → `load_basis(…, modes=g)`. `modes_ref321` 이면 같은 M 으로 3-2-1 spc(`ev.spc_of(mesh, t.supports)`) 모드(정보). 실패 = `JIG_MODES_FAILED` 정보 후 계속.
  - 안: `prep/jig.npz` → `jig.forces`(모드 열 = 저장한 `mode_f` 그대로) → `jig.design_response`(안 mesh, 같은 J 를 node_id 로 찾음 — once 라 인덱스 동일, 다르면 searchsorted).
- `result.json`(안) 행 밖 `sm{…}` 에 `jig: {"status": "ok"|"fallback", "code"}`(베이스라인만) 추가 — 기존 키 불변.
- `bd_post`(①②③)·④ post: `S_["metric_effective"] = tp.metric_effective(plan, metric, jig_ok)`(jig_ok = `prep/jig.json` status ok), `rk.rank(...)` 그대로, `post/result.json` += `jig{DoeJigOut}`(스냅샷에 jig 있을 때만 — ④ 는 `unsupported`), 경고 `JIG_FIT_POOR`·`JIG_TIE_RELATIVE`·`JIG_UNSUPPORTED` 를 결과 warnings 에. `ranking.csv` 끝 열 `JIG_CSV_COLS = ["C_jig", "umax_jig", "jig_fit_mac", "jig_umax_err"]`(기존 마지막 열 뒤, 스냅샷에 jig 있을 때만): `C_jig` = 행 `score_jig`(비), `umax_jig` = 행 `umax_jig`(비), `jig_fit_mac` = `fit_mac_min`, `jig_umax_err` = `fit_umax_err_max`(뒤 두 열은 스터디 공통 — 모든 행 같은 값, 지그 없음 = 빈 칸).
- `report_doe.py`: 강성 지표 절에 1줄(지표 정의 + 기준 재현 MAC·umax 오차·영역 출처). 그 밖 보고서 불변.

### 5.4 deck 표면 읽기 (IO — Impl-Backend)

- `esl/rad/parser.py`(가산 2개, 기존 출력 불변): (a) `_Deck.elem_segs: list[_Seg]` — 1차 스캔에서 `_OTHER_ELEM_KW` 블록(cnt > 0)의 `_Seg` 도 기록(지금 버리는 위치만 보관), (b) `_Deck.load_nodes_box(lo (3,), hi (3,)) -> (node_id (n,) int64 정렬, xyz (n,3))` — 모든 `/NODE` 행을 `load_nodes` 와 같은 규칙(중복 = 마지막·상태 우선)으로 읽되 상자 안 노드만 보관. `parse_rad`·`parse_rad_part` 결과·속도 불변(V-JIG-13).
- `esl/doe/jig_surf.py`(신규 IO, `esl.doe` 안이므로 `esl.doe.assem_full` import 허용): `other_surfaces(rad_path, target_part_id, box_lo, box_hi, *, include_path_map, max_include_depth, max_line_bytes, max_tris) -> {"x": (P,3), "node_id": (P,), "tri": (T,3) int64(로컬), "tri_part": (T,), "n_parts": int, "n_shell": int, "n_solid_faces": int, "seconds": float}`.
  1. `_Deck.scan`(위치만) → 2. `load_nodes_box(box ⊕ (gap + h_max))`(상자 = 대상 Ω 노드 bbox, 여유 = `contact_gap_mm` + 대상 최대 요소 크기) → 3. 대상 파트 밖 `shell_segs`·`elem_segs` 를 `_seg_iter` + `assem_full._lead_ints`(여러 줄 카드 = `ELEM_TOTAL`, 코너 = `ELEM_NODES`) 로 읽어 **상자 안 노드가 1개 이상인 요소만** 보관 → 4. 솔리드는 파트마다 `_faces`+`_clean` 의 EXT(공유 안 된 면) — 보관 규칙상 상자 안 면의 이웃 솔리드는 모두 보관되므로 외곽 판정이 전체 deck 기준과 같음 → 5. 면·쉘 → 삼각형(쿼드 (0,1,2)(0,2,3), 퇴화 제거), 상자 밖 노드 참조 삼각형은 그 노드를 `load_nodes` 로 보충 → 6. T > `max_tris` → `EslError("JIG_SURF_TOO_LARGE")`.
  - 지원 요소: SHELL·SH3N·BRICK·BRIC20·TETRA4·TETRA10·PENTA6. 그 밖(BEAM·SPRING…)은 무시(개수 `n_skipped`).
  - deck 경로: `jig_ctx = case` → `c.D["base"]["rad_path"]` + `c.parse_kw()`, `mesh` → `c.p("input","mesh", inp["mesh"]["main"])`. 대상 파트 id = `prep/input.json part_id`. 읽기만(입력 무쓰기), 허용 루트 검사는 기존 `parse_kw` 경로 그대로.
- `assem_full.py`·`paicad_io.py` 는 **import 만**(바이트 불변).

### 5.5 진단 파일 (스키마 1개 `esl/doe_jig/1`)

`prep/jig.npz`(`mg.save_npz_det`, 고정 키): `schema`, `node_id (N,)`, `jig_idx (J,)`, `omega (N,) bool`, `col_kind (nb,) int8`, `reg_ptr`, `reg_node`, `reg_w`, `reg_dir`, `reg_sign`, `reg_kind`, `reg_part`, `body_w`(없으면 키 없음), `mode_f (m,N,3)`(모드 하중 N — m = 0 이면 키 없음), `entry_ids (K,)`, `a (K, nb)`, `C_ref (K,)`(C_jig 기준, N·mm), `umax_ref (K,)`(mm). status fallback 이면 npz 없음.
- **노드 면적당 밀도 키(v0.24.0 메시 독립 전달용, 이름 고정)** — 단위 계수 1 N 당 표면 밀도 [N/mm²]: `node_area (N,)`(mm², `node_weights.area`), `reg_q (R,3,3)` = `reg_dir / area_r`(영역 r 의 [n, t1, t2] 단위 하중이 영역 위에 균일하게 내는 밀도 — 면적 가중 분산이라 영역 안 상수), `reg_area (R,)`(mm²), `body_q (N,)` = `body_w / node_area`(면적 0 노드 = 0; 방향 = 열 축), `mode_q (m,N,3)` = `mode_f / node_area[:,None]`(면적 0 노드 = 0). 엔트리 하중 밀도는 q_i = Σ_k a_i,k q_k 로 재구성(따로 저장 안 함). 이번 버전에서 읽는 쪽은 없음(저장·시험만).
- 모드 진단 키: `mode_lam (m,)`(λ = ω², ρ_t_used 기준), `mode_rho_t (1,)`(ρ_t_used), `mode_lam_321 (m₃,)`(정보, 없으면 키 없음).

`prep/jig.json`(`c.write_json`):
```text
{ schema: "esl/doe_jig/1", status: "ok"|"fallback", code: null|<코드>, detail?,
  fix: {source: "fixed"|"xfer", kinds: [..]|null, n_jig, n_comp, n_missing},
  regions_from: "contact"|"mixed"|"patch", n_contact, n_patch, fill_reason?: "few_contact"|"no_deck"|"surf_failed",
  surf: {source: "case"|"mesh", n_tris, n_parts, n_shell, n_solid_faces, n_contact_nodes, n_found, seconds} | null,
  regions: [{id, kind: "contact"|"patch", part|null, n_nodes, area_mm2, center[3], normal[3], sign: 1|0}],
  nb, body_force: bool, tangential: bool, ridge, w_inplane, reg_force, g_N,
  modes: {n_req, n_conv, sigma, lam[], hz[], rho_t_used, hz_321[]|null, hz_ratio|null, ok: bool, err?} ,
  entries: [{entry_id, mac, umax_tgt, umax_fit, umax_err, err_p95, resid_rel, tie_rel, rot_deg, n_active, F_sum_abs, cancel_rel,
             with_modes{mac, umax_err, err_p95, resid_rel}, without_modes{…}|null, modes[{k, a}],
             react_rel, body[3]|null, forces[{region, F_n, F_t1, F_t2, F[3], active}], C_ref, umax_ref}],
  info: [..], warnings: [..], seconds: {surf, regions, basis, fit, respond} }
```
- `post/result.json.jig` = `DoeJigOut`(§4 — jig.json 요약 + 임계값 판정). 새 파일은 위 2개뿐.

## 6. 설정 (`bead_doe.rank` — DEFAULTS · `BeadDoeRankCfg` · yaml 2 = 4곳 거울)

```yaml
  rank:
    ratio_tol: 1.0e-6
    per_esl_inline_max: 2000
    metric: jig            # jig(지그 순위 — v0.23.0 새 스터디 기본) | solve(재풀이 C) | lin(1차 지표). 옛 스터디 = 스냅샷 값
    lin_form: ritz
    lin_valid: 0.3
    imbalance_warn: 0.02
    jig:                   # v0.23.0 지그 순위(계약 esl_jig_rank.md) — 새 스냅샷 doe.rank.jig 로 고정
      enabled: true
      fix_kinds: [INTER_TYPE2_SECONDARY, INTER_TYPE2_MAIN]   # 지그 노드 = 이 종류 체결 노드(FIXED_KINDS 이름)
      contact_gap_mm: 2.0           # 다른 부품 표면까지 거리 ≤ 이 값 = 가압 후보
      knn: 8                        # 거리 후보 삼각형 수
      chunk_nodes: 65536            # 거리 계산 노드 청크(메모리 상한)
      max_surf_tris: 20000000       # 상자 안 표면 삼각형 상한(넘으면 패치)
      max_regions: 8
      min_regions: 2                # 접촉 영역이 이보다 적으면 패치 fallback
      min_region_nodes: 3
      min_region_area_mm2: 25.0
      patch_count: 6
      body_force: true              # 체적력 3성분 기저
      basis_tangential: true        # 영역 접선 2성분(false = 법선만 — 비교용)
      n_modes: 4                    # 지그 구속 저차 모드 관성 기저 수(0 = 끔) — D-JIG-15
      rho_t_mm3: 7.85e-9            # 집중질량 밀도 [t/mm³] — Hz 환산 보고에만 영향(모드 형상·하중 불변, 해시 밖)
      modes_sigma: 0.0              # shift-invert σ(ω² 단위). 0 = 지그 정적 분해 재사용(추가 분해 0)
      modes_tol: 1.0e-8             # eigsh tol
      modes_maxiter: 2000           # eigsh maxiter
      modes_ref321: true            # 3-2-1 지지 고유진동수 비교 정보(베이스라인 분해 1 추가, 해시 밖)
      w_inplane: 0.1                # 맞춤 가중의 면내 성분 비(법선 성분 = 1) — D-JIG-16
      reg_force: 1.0e-3             # 접선·체적력·모드 계수 Tikhonov(ḡ_N 배) — §1(5) 근거
      ridge: 1.0e-8                 # 수치 안정 λ(열 정규화 후)
      active_tol: 1.0e-3            # 활성 영역 판정(최대 합력 대비)
      mac_min: 0.9                  # 미달 → JIG_FIT_POOR (해시 밖)
      umax_err_max: 0.2             # 초과 → JIG_FIT_POOR (해시 밖)
      tie_rel_warn: 0.1             # 초과 → JIG_TIE_RELATIVE (해시 밖)
      cancel_warn: 0.5              # cancel_rel 초과 → JIG_LOAD_CANCEL (해시 밖)
```
- pydantic `BeadDoeRankJigCfg`: `fix_kinds` 원소 ∈ `FIXED_KINDS`·1..7개·중복 금지, `contact_gap_mm` > 0, `knn` 1..64, `chunk_nodes` 1024..2²⁰, `max_surf_tris` ≥ 1, `max_regions` 1..32, `1 ≤ min_regions ≤ max_regions`, `min_region_nodes` ≥ 1, `min_region_area_mm2` ≥ 0, `patch_count` 1..32, `n_modes` 0..20, `rho_t_mm3` > 0, `modes_sigma` 실수(≤ 0 권장 — > 0 이면 경고 없이 허용), `modes_tol` ≥ 0, `modes_maxiter` 1..100000, `0 ≤ w_inplane ≤ 1`, `reg_force` ≥ 0, `0 < cancel_warn ≤ 1`, `ridge` ≥ 0, `0 < active_tol < 1`, `0 < mac_min ≤ 1`, `umax_err_max` > 0, `tie_rel_warn` > 0. `metric == "jig"` ∧ `not jig.enabled` → 오류.
- **해시**: `jig.hash_view` 의 `HASH_EXCLUDE`(`mac_min`·`umax_err_max`·`tie_rel_warn`·`cancel_warn`·`rho_t_mm3`·`modes_ref321`) 밖의 모든 키는 해시 안(`n_modes`·`modes_sigma`·`modes_tol`·`modes_maxiter`·`w_inplane`·`reg_force`·`basis_tangential` 포함 — 하중이 바뀜). ρ_t 는 모드 형상·정규화 하중을 바꾸지 않고(균일 배율) Hz 는 BD_POST 가 환산, `modes_ref321` 은 정보만.
- `GET /doe/settings` `rank`: 기존 4키 그대로(`metric` 값에 jig 가능). 화면 임계값은 결과 `jig.th` 로만.

## 7. 화면 (Impl-Frontend, `DoeRanking.tsx` — 2560×1440, 높이 늘리지 않음)

- 판정: `jigOn = (result.rank?.metric_effective ?? result.metric_effective) === "jig"`.
- **jigOn**: 주 열 이름 "지그 C", 정렬 표시 "score(지그 C)", 주 열 title "max_i C_jig / C_ref — 체결부(tie) 고정 + 맞춤 가압 하중으로 안마다 재풀이(하중 제어), 작을수록 좋음". 정의 `<li>` 1개: "score: max(C_jig 안) / max(C_jig 기준) — 기준 낙하 변형을 재현하도록 맞춘 몇 곳의 가압 하중(영역 n개, 접촉|패치)을 같은 지그·같은 하중으로 안마다 재풀이한 컴플라이언스. 작을수록 좋음". 보조 토글 열 = 기존 "재풀이 C 비"(`score_solve`)·불평형(기존 컴포넌트 그대로) + umax(지그) 비(`umax_jig`).
- **기준 재현 한 줄**(jig 블록이 있으면 항상, 순위 표 바로 위 기존 안내 줄과 같은 `muted` 줄 — 새 줄 1개만): `기준 재현(지그): MAC(모드 포함) ≥ {fit_mac_min}{n_modes > 0 이면 ' (제외 ' + fit_mac_min_nomodes + ')'} · umax 오차 ≤ {fit_umax_err_max %} · 하중 영역 {n_regions}개(접촉 {n_contact} · 패치 {n_patch}) · 지그 노드 {n_jig}` + status `poor` 이면 경고색 + `JIG_FIT_POOR` 문구 title, 경고 `JIG_LOAD_CANCEL` 이 있으면 같은 줄 끝 ⚠ 아이콘 1개(title = 문구·cancel_rel_max), 지그 1차 고유진동수 `hz_jig[0]`(3-2-1 대비 `hz_ratio`)는 title 툴팁에만, `fallback`·`unsupported` 이면 "지그 순위 불가 — {JIG_CODE_TEXT[code]}, 재풀이 C 로 순위". 엔트리별 값은 title 툴팁(줄 늘리지 않음).
- metric_effective ≠ jig 이고 행에 `score_jig` 가 있으면 보조 토글에 "지그 C 비" 열 1개.
- legacy·지그 블록 없는 결과 = 지금 화면 그대로(바이트 단위 DOM 스냅샷 동일).
- `api/doe.ts`: `JIG_CODE_TEXT`(§4 표 코드 문구), `isJigResult(r)`. `api/types.ts`: §4 고정 필드.
- mock: `mock/doedata.ts` 결과 3종(지그 ok ②·지그 poor·fallback `JIG_NO_TIE`) — 기존 목 결과는 그대로.

## 8. 시험 (V-JIG-n)

픽스처 `tests/doe/synth_jig.py`(신규, Impl-Core): `synth_sm.plate` 위에 tie 노드 묶음(두 짧은 변 근처 노드 3~5개씩 2~4 묶음), 인접 부품 = 대상 판에서 법선으로 g 떨어진 작은 쉘 판 2개 + 솔리드 블록 1개(브릭 2×2×1 — 외곽 면 삼각형), 리브 비드 `rib_x(mesh, alpha, depth)`(지그 선 사이 스팬 방향 — 굽힘 강성 증가가 확실한 형상), 표면 dict 생성기. `write_rad_with_neighbors(path, …)`(V-JIG-12·13 용 rad: 대상 파트 + 인접 쉘 파트 + BRICK·TETRA10·BRIC20 파트 각 1, `/INTER/TYPE2` 카드).

| ID | 시험 | 위치 |
|---|---|---|
| V-JIG-1 | **정확 재현**: u_ref = K_jig⁻¹F(a_true)(접촉 영역 3개 + 체적력) + 임의 **유한** 강체 운동(u = R(x+u_el)+t−x, 회전 10°·이동 50 mm; u_el[J] = 0) → target_disp 가 강체 제거(1e-10), fit → MAC ≥ 1 − 1e-10, umax_err ≤ 1e-8, err_p95 ≤ 1e-8, react_rel ≤ 1e-9 | `tests/doe/test_jig.py` |
| V-JIG-2 | **하중 위치·크기 복원**: V-JIG-1 의 a_true(일부 영역 0) → 복원 a 상대오차 ≤ 1e-6, 0 영역 = 비활성(active false), 법선 ≥ 0 제약에서 a_true 법선 음수 영역을 넣으면 해당 성분 = 0(경계 활성)·MAC < 1 | 같은 파일 |
| V-JIG-3 | **물리 방향**: 리브 비드 α ∈ {0, 0.5, 1}(깊이 증가) → C_jig·umax_jig 단조 감소(score_jig(α=1) < score_jig(0.5) < 1), 같은 F·같은 J | 같은 파일 |
| V-JIG-4 | **상쇄·무른 모드 무관(D-JIG-16 개정)**: V-SM-11 꼴(긴 얇은 판, F = K₀u_drop) + 국부 비드 α 0.1/0.5/1 → 재풀이 C(3-2-1) umax ×≥ 10·imbalance ≥ 5 %(재현) ↔ 지그(기본 설정): react_rel ≤ 1e-9, umax_jig 비 ≤ 3, |score_jig − 1| ≤ 재풀이 C 변화의 1/5. **면외 지배 목표**(u_drop 면외 성분 ≥ 90 %)에서 hard assert cancel_rel ≤ 0.5·F_sum_abs / Σ‖F_ESL‖ ≤ 0.1. 면내 자기평형 목표 사례는 V-JIG-21 로(경고 확인) | 같은 파일 |
| V-JIG-5 | **패치 전부(접촉 0)**: surf None(no_deck)·접촉 0 → `regions_from patch`·`fill_reason`·패치 수 = min(patch_count, max_regions, 비어 있지 않은 셀), 지그 노드가 어느 패치에도 없음, 두 번 실행 비트 동일, 부호 자유, `JIG_REGION_FALLBACK` | 같은 파일 |
| V-JIG-16 | **혼합 보충**: 인접 부품 1개(접촉 영역 1) + min_regions 3 → `regions_from mixed`·n_contact 1·n_patch 2, 접촉 영역 노드·kind contact·part 가 접촉만일 때와 비트 동일, 패치 노드 ∩ (접촉 노드 ∪ J) = ∅, 영역 순서 접촉 → 패치, reg_kind·jig.json `regions[].kind` 기록, `JIG_REGION_FALLBACK{few_contact, n_contact 1, n_patch 2}`; 접촉 ≥ min_regions → 보충 없음·경고 없음; 후보 소진(C_p 비어 있음) → n_patch < n_fill 로 진행; 보충 영역 포함 V-JIG-1 식 정확 재현(MAC ≥ 1 − 1e-10) | 같은 파일 |
| V-JIG-17 | **모드 관성 재현**: 합성 평판(600×300, t 0.8, 짧은 두 변 tie)·m 4 — 목표 u_tgt = K_jig⁻¹(Σ c_k M φ_k)(c 임의, 모드 2~3 개 섞음) → 모드 기저 포함 MAC ≥ 1 − 1e-8·umax_err ≤ 1e-6, **모드 제외**(영역 + 균일 체적력만) MAC ≤ 0.95 이고 with − without ≥ 0.05; jig.npz `mode_f`·`mode_q`·`node_area`·`reg_q`·`body_q` 키·모양·`mode_q·node_area = mode_f`(1e-12); 안 평가가 모드를 다시 풀지 않음(eigsh 호출 0 — 모의 객체) | `tests/doe/test_jig.py` |
| V-JIG-18 | **모드 끔 = 바이트 동일**: `n_modes 0` → a·F_i·C_jig·jig.json(모드 키 제외 영역)·jig.npz(모드 키 없음)가 모드 기능 이전 경로와 비트 동일, without_modes null, `hz_jig []`, eigsh 호출 0 | 같은 파일 + `tests/doe/test_jig_stages.py` |
| V-JIG-19 | **고유치 실패**: eigsh 가 ArpackNoConvergence(일부 수렴 1개)·전부 실패·OPinv 회전 우변 → `JIG_MODES_FAILED{n_conv}` 정보, 수렴분만(또는 모드 없이) 진행·순위 산출, status ok/poor(실패 아님), `modes.ok false`; `modes_ref321` 실패는 hz_321 null 만 | 같은 파일 |
| V-JIG-20 | **유한 회전 목표**: (a) 지그 노드 회전 ≤ 0.1° → `kabsch.fit` 경로와 `remove_linear_rigid` 경로 u_tgt 차 ≤ 1e-6·umax_tgt (b) 회전 10° 의 순수 강체 + 면외 굽힘 → u_tgt = 굽힘 성분(1e-10), 선형 경로는 O(θ²L) 면내 잔여가 남음(차 ≥ 1e-3·L) (c) `rot_deg` 보고 | 같은 파일 |
| V-JIG-21 | **법선 가중·하중 정규화·상쇄 경고**: §1(5) 합성 사례 재현 — (a) 법선 + 면외 체적력 정확 목표: reg_force 1e-3 MAC 손실 ≤ 1e-3(측정 < 1e-6)·umax_err ≤ 1e-3 (b) 같은 목표 + 면내 자기평형 잔여: 기본(w_inplane 0.1·reg 1e-3) cancel_rel ≤ 0.5·F_sum_abs ≤ 1.1 × 정확 하중 합, `reg_force 0`·`w_inplane 1` → cancel_rel > 0.5 이고 BD_POST 경고 `JIG_LOAD_CANCEL` 1개(순위 계속) (c) `basis_tangential false` → col_kind 에 2 없음·nb = R + 3 + m | 같은 파일 + `tests/doe/test_jig_stages.py` |
| V-JIG-22 | **필드·설정(모드·정규화)**: DoeJigOut 새 필드(`fit_mac_min_nomodes`·`fit_umax_err_max_nomodes`·`cancel_rel_max`·`n_modes`·`hz_jig`·`hz_321`·`hz_ratio`, th.`cancel_warn`, 엔트리 `mac_nomodes`·`umax_err_nomodes`·`rot_deg`) 통과·`check:api`, 설정 4곳 거울(새 9키), `HASH_EXCLUDE` 키 변경은 해시 불변·그 밖 새 키 변경은 해시 변경, `rho_t_mm3` 4배 → hz_jig ½(BD_POST 환산, 재실행 없음) | `backend/tests/test_doe_config.py` · `backend/tests/test_doe_rank_metric_api.py` · `tests/doe/test_jig_stages.py` |
| V-JIG-6 | **지그 없음·퇴화**: RBE2 만 → `JIG_NO_TIE`; 공선 tie 3점·성분 하나에 지그 없음 → `JIG_SUPPORT_DEGENERATE`(분해 전 판정). 통합: metric jig 스터디가 fallback → `metric_effective` solve, `jig.status` fallback·code, ranking 순위·score 열이 metric solve 스터디와 같음 | `test_jig.py` + `tests/doe/test_jig_stages.py` |
| V-JIG-7 | **regress 바이트 동일**: (a) 스냅샷 `rank` 없음 (b) `rank` 있음·`jig` 없음(v0.20~0.22 스냅샷) → result.json·ranking.csv·report.html·done.json 해시가 main 685df7d 와 같음(기존 regress 골든). (c) `rank` 에 metric 키 없음 → solve | `tests/doe/test_jig_stages.py` + 기존 regress |
| V-JIG-8 | **대규모 거리 메모리**: 후보 노드 25만 × 삼각형 200만(평행 격자) → 결과 = 전수 brute(표본 2 000 노드) 와 일치, tracemalloc 추가 피크 ≤ 400 MB, 노드 2배 → 피크 증가 ≤ 10 %, ≤ 60 s(`@pytest.mark.slow`) | `tests/doe/test_jig.py` |
| V-JIG-9 | **프런트**: 지그 ok 결과 → 주 열 "지그 C"·정의 문구·기준 재현 한 줄(MAC(모드 포함)·제외 값·umax 오차·영역 수)·`JIG_LOAD_CANCEL` 있으면 ⚠ 1개(줄 수 불변)·보조 토글 umax(지그) 비; poor → 경고색 + title; fallback → "지그 순위 불가" + 주 열 재풀이 C; solve 결과 + score_jig → 보조 "지그 C 비"; legacy 결과 DOM 불변; 1920×1080 잘림·가로 스크롤 없음, `check:api` 통과 | `frontend/src/__tests__/doe_jig.test.tsx` |
| V-JIG-10 | **계획 열**: 5행 모두 `sm_jig`·`jig_fix`·`jig_ctx` 가 §5.2 표와 같음, 값 ∈ `JIG_VALUES`, 열 지우면 `CONFIG_INVALID`, 불변식 `sm_jig base ⇒ sm_ref base ∧ sm_disp[1] I ∧ sm_rank metric`, `metric_effective(plan, "jig", jig_ok)` 4조합, 기존 호출 결과 불변 | `tests/doe/test_transfer_plan.py` |
| V-JIG-11 | **설정 거울·스냅샷**: `DEFAULTS["rank"]` == `BeadDoeRankCfg()` == 두 yaml(jig 포함), metric 기본 jig, `metric jig ∧ enabled false` 거부, `rank_snapshot` schema 2·jig 블록, enabled false = jig 키 없음·schema 1, `_cfg_hash` 는 jig 있을 때만 변하고 임계값 3개를 바꿔도 불변 | `backend/tests/test_doe_config.py` · `tests/doe/test_jig_stages.py` |
| V-JIG-12 | **통합 ①②③④**: ① case(인접 쉘·솔리드 rad, tie fixed-scan 픽스처) → regions_from contact·영역 part 일치·jig.npz/json 스키마·d000 score_jig = 1·CSV 끝 열 4개; ② 업로드 deck 에 인접 부품 없음 → patch + `JIG_REGION_FALLBACK{few_contact}`; ③ step(xfer) → `JIG_FIX_UNFILTERED`·패치; ④·옛 ③ → `unsupported`·`JIG_UNSUPPORTED`·solve 순위·jig.npz 없음; metric solve 스냅샷도 jig 계산(score_jig 보조) | `tests/doe/test_jig_stages.py` |
| V-JIG-13 | **deck 표면**: 쉘·SH3N·BRICK·TETRA10(여러 줄)·BRIC20·PENTA6 외곽 면 = `assem_full.solid_segments(EXT)` 와 같은 면 집합, 대상 파트 제외, 상자 밖 요소 제외(상자 경계 걸친 면 보존), `max_tris` 초과 = `JIG_SURF_TOO_LARGE`; 파서 가산 변경 후 `parse_rad`·`parse_rad_part` 결과 바이트 동일(기존 시험 + 골든 1건), `scan` 시간 증가 ≤ 5 % | `tests/doe/test_jig_surf.py` |
| V-JIG-14 | **API·순위**: `rank(metric="jig")` = C_jig 키 순위·ESL별 비·pareto, C_jig null 안 = `n_failed["jig"]`, 행 `score_jig`·`umax_jig`·`C_jig{}`; 결과 응답 `jig`(DoeJigOut)·`metric_effective "jig"` 통과·옛 결과 jig null; openapi 갱신 | `tests/doe/test_rank_metric.py` · `backend/tests/test_doe_rank_metric_api.py` |
| V-JIG-15 | **모드 무관 모듈**: `jig.py` AST 검사(esl.doe·파일 IO·`open(` 없음), 같은 배열 입력 → 어느 계획에서 불러도 비트 동일, `stages.py` 에 시나리오 이름으로 지그 분기 없음(정적 grep `jig` 주변) | `tests/doe/test_jig.py` |

- V-JIG-4 구현 관찰(Core 2026-11-17, **결정 대기**): 목표에 막(면내) 자기평형 변형(#63 의 원인 — V-SM-3·11 꼴 국부 막 압축)이 있으면 맞춤이 면내 접선·체적력 상쇄 하중을 써서(막 강성 ≫ 굽힘 강성 → 면내 맞춤 하중이 가압 법선 하중보다 10²~10³배) `cancel_rel` ≈ 0.76 이 되어 `≤ 0.5` 를 원리적으로 못 맞춘다(ridge 1e-8~1e-2 무관). 시험 픽스처 = 중앙 가압(지그 응답) + 가압 영역 밖 국부 막 압축, 나머지 상한(반력·F_sum_abs 비 0.076·umax_jig 비 ≤ 1.96·score 변화 ≤ 재풀이의 1/5)은 통과, `cancel_rel` 단정만 `xfail(strict)`. 순수 막 압축 목표(V-SM-11 그대로)는 umax_jig 비도 56~615(면내 하중이 비드에서 굽힘으로 전환).

## 9. 리스크

- R-JIG-1 **tie 상대 부품도 변형**: 실제 낙하에서 tie 노드끼리 상대 변위가 있으면 고정 지그는 기준 변형을 완전히 재현 못함(MAC 상한). `tie_rel`·`JIG_TIE_RELATIVE` 로 보이고, 크면 후속(지그 노드 강제 변위 u_tgt[J] — 같은 기저에 강제 변위 열 추가).
- R-JIG-2 **대변형 u₀ vs 선형 정적**: ESL u_rel 의 국부 접힘·대회전은 몇 곳 하중의 선형 응답으로 다 못 맞춤 → MAC·umax 오차로 판단(사용자 확정 2). JIG_FIT_POOR 여도 순위는 냄 — "같은 지그·같은 하중 비교"라는 순위 의미는 맞춤 품질과 무관하게 성립하나, 기준 낙하 대표성은 낮아짐.
- R-JIG-3 **비용**: 안마다 분해 1회 추가(3-2-1 해석과 지그 해석 둘) → 실행 시간 ≈ ×1.6~2(Q-JIG-1). 베이스라인 + nb(≤ 27) solve.
- R-JIG-4 **메모리**: U = nb × |F| × 3 × 8 B(30만 노드·27 기저 ≈ 194 MB) + 표면 상자 안 삼각형. 분해 메모리보다 작음.
- R-JIG-5 **deck 읽기 시간**: 대형 TV 모델(수백 MB include, 요소 수백만)에서 `/NODE` 전체 스캔 + 상자 안 요소 해석 = 베이스라인 1회 수십 초. 상한 `max_surf_tris` 초과 = 패치.
- R-JIG-6 **법선 부호**: 간격 0(겹친 면)·접촉 상대가 대상 양쪽에 있는 영역은 부호 자유 — 당김 하중이 허용될 수 있음(`JIG_NORMAL_FREE` 수 보고).
- R-JIG-7 **비유일·상쇄 조합**: 이웃 영역 접선력끼리 상쇄하는 해가 잔차를 조금 줄이면 BVLS 가 고를 수 있음 → ridge·`cancel_rel` 보고. V-JIG-4 상한으로 감시.
- R-JIG-8 **순위 의미 변경**: 새 스터디의 순위가 옛 스터디(solve)와 다른 지표 → 같은 화면에서 직접 비교 불가. 정의 문구·`metric_effective` 로 구분.
- R-JIG-9 **③ xfer 종류 미필터**: A 의 RBE2·RBODY 체결점도 지그가 됨(정보 `JIG_FIX_UNFILTERED`).
- R-JIG-11 **모드 하중 고정**: 안의 강성이 바뀌어도 관성 분포(g_k)는 기준 모드 그대로 — 하중 제어 비교의 정의상 의도(D-JIG-15)이나, 모드 형상이 크게 바뀌는 안에서는 실제 관성과 차이. 진단은 기준에서만.
- R-JIG-12 **eigsh 비용·수렴**: σ = 0 재사용으로 분해는 없지만 대형 모델(180만 dof)에서 ARPACK 반복 solve 수십 회 = 베이스라인 수십 초~분. 근접 고유치·강체 유사 모드(지그가 약한 방향)는 수렴이 느림 → maxiter·`JIG_MODES_FAILED`.
- R-JIG-13 **정규화 과억제**: 면외 굽힘을 정말 면내 하중으로만 낼 수 있는 목표(예: 지그 근처 국부 좌굴)는 reg_force 가 맞춤을 낮춤 → MAC 로 보임, 설정으로 조정.
- R-JIG-10 **영역 근처 설계 변경**: 비드가 가압 영역·지그 노드와 겹치면 하중 제어 비교가 국부 효과에 민감. 화면 툴팁에 영역 수·출처만 표시(이번 범위), 겹침 진단은 후속.

## 10. 제약

- 입력·SPDM 무쓰기(deck 은 읽기만), 쓰기는 `_doe/<sid>/prep/jig.*`·안 result.json·post 만.
- 계약 외 파일 수정 금지(§13 소유 밖). `assem_full.py`·`paicad_io.py`·`step_graph.py`·`load_transfer.py`·`evaluate.py`·`kabsch.py`·`shell.py` 는 import 만.
- 하드코딩 금지: §6 키만. 파일명·스키마 문자열은 코드 상수(`JIG_NPZ = "jig.npz"`, `JIG_JSON = "jig.json"`, `jig.SCHEMA`).

## 11. 버전 · migration

- **v0.23.0**: 새 순위 지표·새 설정 절·계획 표 새 열·결과 스키마 추가(사용자 기능) → 마이너 올림(v0.20.0·v0.22.0 관례).
- **migration 불필요**: DB 열·테이블 변경 없음(스냅샷 JSONB `doe.rank.jig`, result JSONB, 작업 폴더 파일).
- decisions.md: D-0.23.0-JIG-1~16(§3) + Q-JIG 확정 결과 + 보류 목록(§3.1: 시간 증분 ESL(DiESL식) — 같은 메시 기준 재현 참조, 보류).

## 12. 결정 질문 — **확정** (2026-11-17 사용자)

1. **Q-JIG-1 지그 계산 시점** — **확정: 기본안**(D-0.23.0-JIG-13). 새 스냅샷은 metric 과 무관하게 항상 지그 재풀이(안마다 분해 +1, 실행 시간 ≈ ×1.6~2; metric 을 BD_POST 에서만 바꿔 solve·lin·jig 를 같은 실행으로 비교, SM-6 과 같은 원칙). 채택 안 함: metric = jig 일 때만.
2. **Q-JIG-2 접촉 영역 부족 시 대체** — **확정: 대안**(D-0.23.0-JIG-14). 찾은 접촉 영역은 유지하고 부족분(min_regions − n_c)만 공간 패치로 보충, 패치는 접촉 영역 노드·지그 노드를 뺀 나머지 비지그 노드에서(§1(3)), 영역 출처 kind = contact | patch 를 jig.npz·jig.json·진단에 기록, 접촉 0 = 전부 패치(옛 fallback 과 같음), 보충 발생 시 경고 `JIG_REGION_FALLBACK`. 구현 = `jig.select_regions` 한 곳. 채택 안 함: 패치만(접촉 영역 버림).

## 13. 파일 소유권 (겹침 0)

경로는 저장소 루트 기준. `B = backend/esl_platform`, `F = frontend/src`.

| 갈래 | 파일(소유) | 시험 |
|---|---|---|
| **Impl-Core** | `esl/doe/jig.py`(신규), `tests/doe/synth_jig.py`(신규), `tests/doe/test_jig.py`(신규) | V-JIG-1~5, 6(모듈 부분), 8, 15, 16, 17, 18(모듈), 19, 20, 21(모듈) |
| **Impl-Backend** | `esl/rad/parser.py`(`elem_segs`·`load_nodes_box` 가산만), `esl/doe/jig_surf.py`(신규), `esl/doe/transfer_plan.py`(열 3·`JIG_VALUES`·`metric_effective` 키워드), `esl/doe/stiffness_metric.py`(`METRICS`·`metric_key` jig 만), `esl/doe/rank.py`(jig 보조 열·`n_failed["jig"]`), `esl/doe/stages.py`(§5.3), `esl/doe/report_doe.py`(1줄), `esl/doe/__init__.py`(`DEFAULTS["rank"]`), `resources/doe_messages.json`(JIG_ 코드), `B/core/config.py`(`BeadDoeRankCfg`·`BeadDoeRankJigCfg`), `B/api/services/doe.py`(`rank_snapshot`·결과 통과 `jig`), `B/api/schemas.py`(§4), `config/esl_platform.example.yaml`·`config/esl_platform.prod.example.yaml`, `docs/contracts/openapi_p1b.json`(재생성), `tests/doe/test_jig_surf.py`(신규), `tests/doe/test_jig_stages.py`(신규), `tests/doe/test_transfer_plan.py`·`tests/doe/test_rank_metric.py`(추가), `backend/tests/test_doe_config.py`·`backend/tests/test_doe_rank_metric_api.py`(추가) | V-JIG-6(통합)·7·10~14·18(통합)·21(BD_POST 경고)·22 |
| **Impl-Frontend** | `F/api/types.ts`(§4), `F/api/doe.ts`(`JIG_CODE_TEXT`·`isJigResult`), `F/components/DoeRanking.tsx`(§7), `F/mock/doedata.ts`, `F/__tests__/doe_jig.test.tsx`(신규) | V-JIG-9 |
| **통합(메인)** | `VERSION`(0.23.0), `CHANGELOG.md`, `docs/decisions.md`(D-0.23.0-JIG-n), 이 계약 문서 | – |

- **고정 접점 3개**: ① `jig.py` 함수 시그니처·반환 키(§5.1 — Core ↔ Backend), ② `DoeResultOut.jig`·`DoeJigOut`·`DoeJigThOut`·`DoeJigEntryOut`·`DoeRankMetric`·행 키(§4 — Backend ↔ Frontend, `check:api`), ③ 계획 열 이름·값(§5.2).
- 순서: Core(jig.py + 합성 시험) ∥ Backend(계획 열·설정·파서 가산·jig_surf 먼저, stages 는 Core 시그니처 기준 — Core 머지 뒤 통합 시험) ∥ Frontend(mock) → openapi 재생성 → `check:api` → 통합.
- 워커(`worker/`)·`evaluate.py`·`shell.py` 변경 없음.
