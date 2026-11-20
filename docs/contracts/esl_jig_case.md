# 계약: Case 지그 ESL 3방식(고정·강제 변위·스프링) · tie 법선 구속 · 하위 작업 출처 선택 (JIGC, v0.24.4)

- 상태: **초안 → 구현 기준**(2026-11-20). 브랜치 `release/v0.24.4`(main 75bfa321 = v0.24.3).
- 선행 계약: `esl_validate_sources.md` §12(P2·P3 개요) — **이 문서가 §12 를 상세 계약으로 확정·개정**한다(§12 본문은 그대로 두고, 충돌하면 이 문서 우선). 관계: `esl_jig_rank.md`(지그 정의 D-0.23.0-JIG-1~19 — 이 문서는 기존 fixed·translation 을 바꾸지 않고 방식·구속 성분을 더함, R-JIG-1 강제 변위를 닫음), `esl_jig_view.md`(스터디 출처 표 원칙), `esl_view3d_sources.md`(CASE_PLAN·SourceTabs), `esl_bforce.md`·`esl_fint.md`·`esl_bforce_ondemand.md`(질량 이름), `esl_opt_run.md`(OR-D-3·OR-D-14·OR-3 — 하중·지지 주입 지점).
- `docs/contracts/opt_native`·`opt_direct` 계약은 **이 저장소에 없음**(Projects 문서 — 이 작업 환경에서 읽을 수 없음). 비드 최적화 감사는 이 저장소의 `esl_opt_run.md`·코드로만 했다(§0.4).
- DB migration **없음**. 새 값 = Case 폴더 파일(`04_esl/jig*.{json,npz}`·`01_extract/jig_fixed/`·`01_extract/jig_surf.npz`·`05_val/jig*/`), 스터디 prep/post 새 파일(새 스냅샷만), API 선택 인자·새 행, 설정 선택 키.
- ID: 결정 `D-0.24.4-JIG-n`, 시험 `V-0244-JIG-n`(`esl_validate_sources.md` §14.2 V-0244-VAL-1~8 을 대체·확장), 후속 `R-JIGC-n`, 미결 `Q-JIGC-n`.

### 사용자 결정 (원문, 변경 금지)
1. (2026-11-20 10:21) "왜 지그 esl은 계산 안해,? 일단 다 하게 하고 다 검증 하게 하고 사용자가 선택해서 강성스터디 검토를 하던 비드최적화든 하지"
2. (2026-11-20 16:47) "지그 esl을 업그레이드 하자. 고정하지말고 상대 운동 했으니까 그만큼 변위를 주던지. 강체 변위빼고 순수변위로"
3. (2026-11-20 16:51, 메인 제안 ① fixed ② prescribed ③ spring(k) 에 대해) "둘다 해보자. 다 해보야지"
4. (2026-11-20 16:53) "지그 고정을 병진 말고 out of plane만 잡아보자"
5. (2026-11-20 16:54, 법선 구속의 면내 강체 모드에 대해) "321도 계속 포함한다면"
- 원칙(2026-11-18 16:26): "ESL 출처별 독립 비교, 나중에 맞는 것만 남기더라도" → 세 방식 = 출처 표의 **별도 행**(독립 탭·검증·순위).

---

## 0. 감사 (v0.24.3 = 75bfa321, 읽기만)

### 0.1 지금 지그 계산 (스터디 전용)

| 항목 | 지금 | 근거 |
|---|---|---|
| 계산 위치 | 강성 스터디 BD 준비 `stages._jig_baseline`(`esl/doe/stages.py:3806-3940`) → `prep/jig.json`(`esl/doe_jig/1`)·`prep/jig.npz`. 안 = `_jig_design`(`:3952`) → `jig.design_response`(안마다 분해 1). Case 에는 없음(`view3d_src.py:23` jig 행 `V3D_STUDY_ONLY`, `val_src.py:44` 같음) | D-0.23.0-JIG-7·9 |
| 순수 계산 | `esl/doe/jig.py`(1038줄) — import = numpy·scipy·`esl.errors`·`esl.mech.{kabsch,mass,shell}` 만(`:25-28`). **`esl.doe` 패키지 안**이라 `import esl.doe.jig` 가 `esl/doe/__init__.py`(DEFAULTS 448줄)를 끌어옴 | `jig.py:1-28` |
| 입력 — tie 노드 J | 계획 열 `jig_fix`: `fixed` = `prep/fixed/shell_scan.json`(paicad `shell fixed-scan`, 워커 `doe_jobs.py:485-492`) → `paicad_io.read_fixed`(`paicad_io.py:339`, `FIXED_KINDS` `:42`, `SCAN_JSON` `:25`) → `select_jig_nodes`(`fix_kinds` 비트, 기본 INTER_TYPE2 둘) | `stages.py:3667-3694` |
| 입력 — deck tie·접촉 영역 | `jig_surf.other_surfaces(rad, part, box)`(`jig_surf.py:105-218`) — Case starter 읽기만, `esl.doe.assem_full` 의 `ELEM_NODES`·`ELEM_TOTAL`·`_faces`·`_clean`·`_lead_ints` import(`jig_surf.py:18`). 누적 씬 = 파서 `_Deck.scan` 상태 파일(.str/.sta) 좌표 우선 규칙(`rad/parser.py:421-462`) | `stages.py:3697-3740` |
| 영역·패치 | 접촉 영역(틈 ≤ `contact_gap_mm` 2.0, 상대 파트별 연결 성분, 상위 `max_regions` 8) + 부족분 PCA 격자 패치(`patch_count` 6) — `select_regions` 한 곳 | `jig.py:397-438`, D-JIG-3·14 |
| 기저 | 영역마다 [법선, 접선 2](RBE3 등가 면적 가중) + 체적력 3 + 지그 구속 저차 모드 관성 g_k = Mφ_k(`n_modes` 4, σ = 0 지그 분해 재사용) → nb ≤ 8×3+3+4 = 31 | `jig.py:577-644`·`:481-550` |
| 구속 | **tie 노드 병진 123 고정**(`factor` `jig.py:694-705` → `ShellModel.factorize([(i,"123")])`), 회전 자유 | D-JIG-1 |
| 목표 | `target_disp`: sm_ref(전 노드 ESL 응답)에서 **지그 노드 Kabsch 유한 회전** 제거(`jig.py:157-173`) | D-JIG-2·16 |
| 맞춤 | 가중 최소제곱 W = A(nnᵀ + w_inplane(I−nnᵀ)) + 접선·체적력 Tikhonov + 법선 ≥ 0 BVLS(`fit_loads` `:729-789`), 맞춤 노드 = Ω∖J | D-JIG-4·5·17 |
| 판정·진단 | `fit_report`(`:854-912`): MAC·umax_err·err_p95·resid_rel(모드 포함/제외)·work_eff(D-JIG-18)·cancel_rel·영역 합력, `tie_rel` = max‖u_tgt,J‖/umax. 경고 `JIG_FIT_POOR`(mac_min 0.9·umax_err_max 0.2)·`JIG_TIE_RELATIVE`(tie_rel_warn 0.1)·`JIG_LOAD_CANCEL`(work_eff_min 0.05)·`JIG_SUPPORT_WEAK`(tie_spread_min 0.02) — 문구 `resources/doe_messages.json` | `stages.py` BD_POST |
| 설계 비교 지표 | C_jig = F·u(같은 J·같은 F_i — 하중 제어), umax_jig, 순위 = per_esl C 최악(`stiffness_metric.score`) | D-JIG-7, `stiffness_metric.py:239-255` |
| 설정 | `bead_doe.rank.jig`(`esl/doe/__init__.py:94-100`, pydantic `BeadDoeRankJigCfg` `backend/esl_platform/core/config.py:550-596`, yaml 2개), 해시 밖 `HASH_EXCLUDE`(`jig.py:35`) | D-JIG-11 |

### 0.2 Case 가 deck·tie 를 얻을 경로

| 무엇 | 경로 | 비고 |
|---|---|---|
| Case starter·include | Case 입력 `rad_path`(업로드 = 낙하 씬 전체 보존) + `case.include_path_map`·`rad_include_max_depth`(코어 설정 `case` 절) | 파서는 읽기만 |
| 누적 상태 파일 | starter 의 상태 파일 include(.str/.sta) — 파서가 좌표·요소를 같은 우선 규칙으로 읽음(model.npz x0 와 같음, `esl_cumulative_input.md`) | deck 표면·노드 좌표가 model 과 일치 |
| tie(체결) | paicad `shell fixed-scan`(워커만 실행 가능 — paicad 실행 파일·라이선스는 워커 쪽). 스터디는 `prep/fixed/`(Case 사본 `assem_full` 또는 A Case 제자리 `_a_case` `doe_jobs.py:363-393`) | Case 에는 지금 경로 없음 → §5.1 워커 `jig_prep` |
| paicad 범위 | `--assem-dir` 아래만 읽음 → include 가 Case 폴더 밖이면 `_stage_full` 사본(`doe_jobs.py:221-244`, 22만 요소 수 분) | 입력·SPDM 쓰기 없음 |

### 0.3 import 관계 (esl.pipeline → esl.doe 금지 원칙)

`esl.pipeline` 은 지금 `esl.doe` 를 import 하지 않는다(`pipeline.py:49-67`). 지그를 Case 에 넣으려면 `esl.doe.jig`·`jig_surf`·`assem_full`(면 계산)·`paicad_io.read_fixed` 를 `esl.doe` 밖으로 옮겨야 한다(§4). `jig_surf → assem_full`(`jig_surf.py:18`), `paicad_io → esl.doe.{FAILED,SKIPPED,commands,load_messages}`(`paicad_io.py:20`) — `read_fixed` 자체는 그 이름을 쓰지 않는다(이동 가능). 문구 `_cmp_text` 는 `esl.doe.load_messages` → Case 쪽은 같은 리소스를 읽는 중립 IO(§4.1 `esl/io/messages.py`).

### 0.4 하위 작업이 F_eq 를 쓰는 지점 (P3 주입 지점)

| 소비자 | 지점 | 지지 |
|---|---|---|
| 비드 최적화 OPT_LOAD | `core_adapter._opt_load.load_fn`(`worker/esl_worker/core_adapter.py:888-894`) → S1 `tg.entry_load(t, e.raw)`(`esl/opt/target.py:188-213` — raw `f` = F_eq 노드 직접, OR-D-3) / S2 `e.summary_for_mapping()` 셀 매핑 | – |
| 하중 선정(컴플라이언스) | `sl.run(t, …)`(`core_adapter.py:912`) — 자체 쉘 솔버 C_k = F·u, **지지 = `t.supports`**(OR-D-14) | `case_target` = 기준 ESL 3-2-1(`target.py:154`), S2 = `auto_supports`(`:167`) |
| 덱 OPT_DECK | `od.write(t.mesh, lcs, t.supports, …)`(`core_adapter.py:967`) → `SPC1`(3-2-1, `esl/library/optdeck.py:351-353`), 목적 minmax 컴플라이언스(OR-D-15) | 같음 |
| 스터디 | 출처 탭·순위 = `RANK_SOURCES`(`stages.py:4079-4091`), 노드 힘 출처 하중 = 엔트리 Case 04_esl(`_ns_find` `:4503`) | 스터디 자체 |
| 라이브러리 내보내기 | `optdeck_load_cases`(`core_adapter.py:593-595`) — F_eq·3-2-1 | R-VAL-1 그대로 |

### 0.5 현장 맥락 (메인 전달, 저장소 밖)

- 11-20 재해석 h3d(`/tmp/c82_field_20261120.txt`): 경계력 ESL Σ|F| = 전 노드 ×0.0023 인데 재현 umax 오차 **+4754 %**·MAC 0.002, 내력 ESL ×0.0010·**+145834 %**·MAC 0.000, 소성 면적 0.1 %(εᵖ max 0.0176), `BF_MASS_APPROX`(질량 결과 이름 미인식 → deck 근사), `BF_SIGN_SUSPECT`, `BF_FINT_CHECK` 12.3, `FINT_UNBALANCED` 0.0256. 작은 실제 힘이 선형 K₀(3-2-1) 에서 수십 배 변위 → 메인 가설: 처짐/두께 ≈ 20 의 기하 비선형(막) + 이웃 강성 부재 → **K₀ 단독이 실제 강성보다 훨씬 부드러움**. 지그 3방식(특히 변위·스프링)은 "이웃이 tie 운동을 지배·지지한다"를 경계로 넣는 시도다(§3.5 가정 표).
- 11-18 지그 현장(스터디): MAC 0.13~0.44, tie_rel 0.89~0.99, n_jig 4002 노드가 패널 전면에 분포(plate_led 스크류 tie 로 함께 휨) → 고정(u_J = 0)은 원리적으로 재현 불가(R-JIG-1). 병진 고정은 막 변형(면내)까지 막아 인공 강성 추가.
- 비용 실측(메인 전달 v0.23.x, 이 저장소 문서 기록 없음): deck 표면 **493만 삼각형·≈ 84 s 재읽기**, 스터디 지그 진단 3D ≈ **73 MB**. 합성 측정(v0.24.3, 2코어 SuperLU 32,761 노드): 분해 13.93 s·해 0.38 s → 194k 노드 외삽 분해 ≈ 200 s·해 ≈ 2.5 s·변형률 ≈ 6 s(`esl_validate_sources.md` §4.1).

### 0.6 결론

지그 계산은 순수 함수로 이미 독립돼 있으나 `esl.doe` 패키지 안·`assem_full`·`paicad_io` 의존 때문에 Case 파이프라인이 쓸 수 없다. 구속은 병진 123 고정 한 가지, 강제 변위·스프링·법선 구속·Π 기반 지표는 없다. 하위 작업은 3곳(OPT_LOAD·선정·덱)이 F_eq·3-2-1 을 고정으로 쓴다.

---

## 1. 목표 · 범위 · 단계

1. 지그 ESL 을 **세 방식**(fixed 고정 · prescribed 강제 변위 · spring 스프링) × **tie 구속 성분**(normal 법선 — 새 기본 · translation 병진 — 옛)으로 정의하고 공용 순수 모듈 하나로 계산(§3·§4).
2. Case ③ ESL 이 세 방식을 모두 산출(출처 행 `jig`·`jig_disp`·`jig_spring`), ③ 3D·④ 검증이 출처마다 독립(§5·§6).
3. 강성 스터디가 같은 모듈로 세 방식 순위(옛 스냅샷 = 지금 결과 바이트 동일)(§7).
4. 하위 작업 출처 선택 `load_source`(스터디·비드 최적화) + 경고·확인 정책(§9).
5. 질량 결과 이름 미인식 대응을 설정으로 해결 가능한 범위만 정리(§10).

| 단계 | 내용 | 미룰 수 있나 |
|---|---|---|
| **P2a** | 공용 모듈 이동(심·바이트 동일) + `esl/mech/jig_bc.py`(3방식·법선·3-2-1 면내·스프링·지표) + `ShellModel` 경계 확장 | 아니오(모든 단계의 기반) |
| **P2b** | Case 통합: 워커 tie 준비·코어 `_jig_esl`·04_esl 산출·CASE_PLAN/VAL_PLAN 행·④ 검증·화면 그룹 탭·RANK_SOURCES 행(자리 — 스터디 미계산 사유) | 아니오(사용자 요청 1·3) |
| **P2c** | 스터디 세 방식 계산(새 스냅샷)·per_esl·순위·사이드카·CSV 끝 열 | **예** — 밀리면 스터디 jig_disp·jig_spring 탭은 비활성 사유 `JIG_METHOD_NOT_RUN`(R-JIGC-1). 스터디 3D(jig_disp·jig_spring)는 P2c 안에서도 마지막(R-JIGC-2 로 밀 수 있음) |
| **P3** | `load_source` 스터디·비드 최적화, 경고·확인, 지그 경계의 최적화 전달(병진 고정만) | 비드 최적화 지그 계열 = **예**(R-VAL-6 그대로), 스터디·full·bforce·fint 선택은 아니오 |
| 진단 | `jig.spring_alpha_scan`(α 민감도 현장 진단 — 기본 빈 목록) | **예**(설정 키만 먼저, 계산은 R-JIGC-3) |

---

## 2. 출처 키 · 이름 · 표

### 2.1 출처 키 (KEYS 6개 — 4개 표 공통)

`esl/view3d_src.KEYS = ("jig", "jig_disp", "jig_spring", "full", "bforce", "fint")` — `CASE_PLAN`(③ 3D)·`val_src.VAL_PLAN`(④, import)·`stages.RANK_SOURCES`(스터디)·`frontend/src/view3d/sources.ts:SOURCE_ROWS`(화면)이 같은 키·같은 순서(V-0241-V3D-4·V-0243-VAL-4 갱신 — 의도된 변경). 호출부는 **계획 열만** 읽고 출처 이름으로 분기하지 않는다(AGENTS.md — 소스 grep 시험 V-0244-JIG-10).

| 키 | 방식(`jig_bc.METHODS` 키) | 화면 이름(`label`) | 짧은 이름(`short`) | 그룹 | 04_esl 파일 | 05_val 폴더 |
|---|---|---|---|---|---|---|
| `jig` | `fixed` | 지그 고정 | 고정 | `jig` | `jig.json`·`jig.npz` | `jig` |
| `jig_disp` | `prescribed` | 지그 변위 | 변위 | `jig` | `jig_disp.json`·`jig_disp.npz` | `jig_disp` |
| `jig_spring` | `spring` | 지그 스프링 | 스프링 | `jig` | `jig_spring.json`·`jig_spring.npz` | `jig_spring` |

- 그룹 표 `GROUPS = {"jig": {"label": "지그 ESL"}}`(화면 `sources.ts`·보고서 `val_src.GROUP_LABEL` 같은 값). 공유 산출물 `04_esl/jig_basis.npz`(J·법선·3-2-1 면내·영역·기저·모드 — 세 방식 공통, §5.3).
- 기존 키 `jig` 는 그대로(스터디 옛 결과의 jig = fixed·translation — 바이트 동일). 이름만 "지그 ESL" → "지그 고정"(그룹 이름이 "지그 ESL") — 의도된 문구 변경(스터디 탭 글자 포함, V-0244-JIG-13).

### 2.2 방식 계획 표 `esl/mech/jig_bc.METHODS` (선언)

| 열 | `fixed` | `prescribed` | `spring` | 뜻 |
|---|---|---|---|---|
| `src` | `jig` | `jig_disp` | `jig_spring` | 출처 키 |
| `tie_value` | `zero` | `target` | `target` | tie 구속 값: 0 / 목표 변위의 구속 방향 성분 |
| `tie_stiff` | `hard` | `hard` | `spring` | tie 를 강제(라그랑주·제거) / 스프링(바닥 = 값) |
| `frame` | `jig_kabsch` | `part` | `part` | 목표 프레임(§3.2) |
| `factor` | `own` | `fixed` | `own` | 분해: 자체 / fixed 와 공유(같은 구속 집합) |
| `tie_rel_warn` | `True` | `False` | `False` | `JIG_TIE_RELATIVE` 판정 여부(값을 주는 방식은 tie_rel 이 입력) |
| `limits` | `()` | `("JIG_DISP_FROM_TARGET",)` | `()` | 출처 한계 코드(§6.4) |
| `name` | 고정 | 강제 변위 | 스프링 | 문구 |

### 2.3 tie 구속 성분 표 `esl/mech/jig_bc.TIE_DOFS` (선언)

| 열 | `normal`(새 기본) | `translation`(옛 — 비교용) |
|---|---|---|
| `dirs` | `normal_subspace`(§3.1 — 평판 1방향, 꺾임 2, 모서리 3) | `xyz`(전역 3축) |
| `aux321` | `inplane`(§3.3 — 3-2-1 면내 부분 항상) | `none` |
| `text` | "tie 면외(법선)" | "tie 병진 123" |

`tie_dofs` 는 출처 행이 아니라 **세 방식 공통 설정**(`jig.tie_dofs`) — 출처 행 수 6 유지. 값은 각 산출물 `bc.tie_dofs` 에 기록(탭 title·조건 줄에 표시).

---

## 3. 정의 · 수식

### 3.0 기호

X0 = 기준 형상, K₀ = 대상 파트 쉘 강성(6N×6N, 기준 형상 — 다른 출처와 같은 `ShellModel`), J = tie 노드(fixed-scan ∩ 파트, `fix_kinds`), Ω = 파트 전 노드(Case)·평가 영역(스터디 계획 열 그대로), 맞춤 노드 M = Ω∖J. 목표 기준 변위 u_ref: Case = S3 `u_rel`(04_esl/u_rel.npz, 파트 전 노드 Kabsch), 스터디 = 엔트리 sm_ref. 구속 행 c = (노드 n_c, 단위 방향 d̂_c, 값 v_c), 스프링 행 s = (n_s, d̂_s, k_s, g_s). 하중 기저 f_k(기존 `load_basis` — 세 방식 공유), 계수 a.

### 3.1 tie 법선(국부 면외) 정의 — `jig_bc.node_frames(mesh, nodes, *, kink_deg, valid_elem)`

- 노드 n 의 법선 산포 행렬 S_n = Σ_{e∋n, valid} A_e m̂_e m̂_eᵀ(기준 형상 요소 면적·단위 법선 — `esl.mech.mass.elem_area_normal` 와 같은 식, 부호 무관).
- valid = 두께 > 0 ∧ E > 0(null shell·void 제외). n 에 valid 요소가 없으면 인접 전 요소, 그래도 없으면(고립) 3방향(= 병진) + 카운트 `n_isolated`.
- 고유분해 λ₁ ≥ λ₂ ≥ λ₃, 구속 방향 = λ_k ≥ τ·λ₁ 인 고유벡터, **τ = tan²(kink_deg/2)**(기본 kink_deg 45° → τ ≈ 0.172). 근거: 두 면(같은 면적)이 각 θ 로 꺾인 노드는 λ₂/λ₁ = tan²(θ/2) → θ ≥ 45° 꺾임(플랜지·모서리)은 두 면 법선을 모두 구속(꺾임선 방향만 자유), 완만한 곡면은 1방향. 모서리(세 면) = 3방향.
- 방향 부호 = 최대 절댓값 성분 양수(결정적). 솔리드는 대상 파트 메시에 없음(쉘 전용 모델) — tie 상대가 솔리드여도 법선은 대상 쉘 기준.
- 진단 `normals = {kink_deg, rank_counts: {1, 2, 3}, n_isolated, n_null_excluded}`.
- 기존 `jig.node_weights` 의 `normal`(면적 가중 합 정규화 — 영역 기저용)은 **바꾸지 않는다**(바이트 동일). 구속 법선은 새 함수만.

### 3.2 목표 프레임 · 구속 값

| 방식 | 목표 u_tgt | tie 값 | 3-2-1 면내 값 |
|---|---|---|---|
| fixed | `target_disp(X0, u_ref, J)`(지그 Kabsch 유한 회전 — 기존 D-JIG-16, tie 를 0 에 가장 가깝게 두는 프레임) | 0 | d̂_c·u_tgt(n_c) |
| prescribed | u_ref 의 파트 Kabsch 프레임(Case = `u_rel` 그대로, 스터디 = `kabsch.remove_rigid(X, sm_ref)`) — 사용자 "강체 변위 빼고 순수 변위로", ④ 목표와 같은 프레임 | d̂_c·u_tgt(n_c) | d̂_c·u_tgt(n_c) |
| spring | prescribed 와 같음 | 스프링 바닥 g_s = d̂_s·u_tgt(n_s) | d̂_c·u_tgt(n_c) |

- 프레임이 결과를 바꾸는 크기: 값을 주는 방식에서 강체 성분은 선형 해에서 강체 응답만 만든다(K₀ r = 0, 미소 회전) → 프레임 차이는 유한 회전 2차항(O(θ²L))만. 그래서 값 방식은 공통 목표 프레임(u_rel), fixed 는 0 과 맞는 프레임(지그 Kabsch)을 쓴다.
- 3-2-1 면내 값 = 그 방식의 목표 값(**프레임 고정점** — §3.3 이 정정(면내 3자유도)이라 값은 면내 강체 이동만 바꾸고 변형·반력은 바꾸지 않는다; 0 으로 두면 목표와의 면내 강체 어긋남이 맞춤 잔차·MAC 에 섞임). 미결 Q-JIGC-3.

### 3.3 3-2-1 면내 부분 (tie_dofs = normal 일 때 항상 — 사용자 결정 5)

- 지지 집합 = **다른 출처와 같은 3-2-1**(Case `03_bc/support.json`, 스터디 `t.supports`) 노드 n₁(`123`)·n₂(2성분)·n₃(1성분).
- 판 평면 = 파트 PCA 1·2축 e₁·e₂, 법선 e₃(`esl.mech.supports.pca_corners` 와 같은 축 — 3-2-1 을 고른 그 축).
- 면내 구속 행: n₁ → e₁, e₂(2), n₂ → ê = e₃ × (x_{n₂} − x_{n₁})/‖·‖(면내, n₁–n₂ 선에 수직 — 면내 회전을 막음)(1). **n₃ 의 성분과 모든 면외 성분은 뺀다** — 면외는 tie 법선이 받고, tie 아닌 노드의 면외 지지는 인공 지지(사용자 결정 5 근거 기록).
- 중복 제거: n₁·n₂ 가 tie 노드면 그 노드의 tie 구속 부분공간에 대해 Gram–Schmidt, 남은 노름 < sin(`aux321_dup_deg`, 기본 10°) 이면 그 행을 뺌(`aux321.n_dup`). 3-2-1 노드가 tie 가 아니면 면내 행만 새 지지.
- 결과: 평판에서 면내 정정 3자유도(2 병진 + 면 회전). 진단 `aux321 = {nodes, dirs, n_dup, reaction_rel = Σ‖r_aux‖/Σ‖F‖, rigid_free}`. 면내 맞춤 하중이 평형이면 reaction_rel ≈ 0 — `aux_reaction_warn`(기본 0.05) 초과 = 정보 `JIG_AUX_REACTION`(경고 아님 — 결과 계속).
- **남은 강체 모드 수 `rigid_free`** = 연결 성분마다 6 − rank(A), A 행 = d̂ᵀ[I | −[x − c]×]/L(구속 행 + 스프링 행) — `ShellModel._check_restraint` 일반화(§4.2). **0 이어야 함**, > 0 = `JIG_SUPPORT_DEGENERATE`{rigid_free, comp}(그 방식들 unavailable). 분기 없이 확인만(사용자 결정 5 — 검출 분기 대신 항상 3-2-1).
- 세 방식 공통(prescribed·spring 도 같은 규칙): 법선만 잡으면 방식과 무관하게 면내 강체 3모드가 남고, 같은 지지여야 방식 간 비교가 공정. spring 에서도 3-2-1 면내는 **강제(hard)**(물리 체결이 아니라 프레임 고정점이므로 스프링으로 두지 않음).
- tie_dofs = translation: 3-2-1 없음(tie 123 + J ≥ 3 비공선 = 강체 6모드 구속, spring 은 3축 스프링이 PD) — 옛 동작 그대로.

### 3.4 세 방식 — 평형 · 응답 분해 · 맞춤

공통 정식화(모든 방식): 구속 d̂_cᵀu_{n_c} = v_c (∀c), 최소화

  Π(u) = ½ uᵀK₀u + ½ Σ_s k_s (d̂_sᵀu_{n_s} − g_s)² − Fᵀu

- 반력 r_c = 구속이 파트에 주는 힘(d̂_c 방향, 라그랑주 승수), 스프링 힘 f_s = k_s(g_s − d̂_sᵀu_{n_s})(파트에 작용). 평형 F + Σ r_c d̂_c + Σ f_s d̂_s = 0(병진 합 — `_check_equilibrium` 일반화).
- **응답 분해**: u = u_g + Σ_k a_k U_k. u_g = F = 0·값/바닥만 준 해(fixed·translation 은 0 → 계산 생략·옛 경로), U_k = 하중 f_k·값 0·바닥 0 해(동차). 선형이라 정확.
- **맞춤**: a* = 기존 `fit_loads(U, (u_tgt − u_g)[M], w, n, basis, …)`(가중·정규화·BVLS 그대로), F_jig = Σ a*_k f_k, u_fit = u_g + U a*. 품질(`fit_report`)은 u_fit vs u_tgt(기존 함수 — 맞춤 노드 M).

| 방식 | 행렬 | 우변 | 분해 | 3-2-1 필요 |
|---|---|---|---|---|
| fixed | K₀ 의 자유 dof(구속 방향 제거) | F − K_fc v(v = 0 이면 F) | 1 | normal = 면내 3(§3.3), translation = 불필요 |
| prescribed | **fixed 와 같은 K_ff**(같은 구속 집합) | F − K_fc v | **0(fixed 공유)** + u_g 해 1 | 같음 |
| spring | K₀ + K_s(K_s = Σ_s k_s d̂_s d̂_sᵀ 노드 병진 블록), 3-2-1 면내만 구속 | F + Σ k_s g_s d̂_s − K_fc v_aux | 1 | normal = 면내 3, translation = 불필요(스프링 3축) |

- k → ∞ 이면 spring → prescribed, k → 0 이면 tie 자유(normal 은 면외 강체가 스프링으로만 막혀 조건수 악화 — α 하한 1e-3 검사).
- 모드 기저(D-JIG-15)는 **fixed 구속(값 0)으로 1회** 계산해 세 방식이 공유(기저 = 하중 모양 — 방식 간 차이가 경계 조건에서만 나오게). normal 구속에서 고유치 문제는 변환 공간 K̃·고정 dof̃ 로 같은 `jig_modes`(M 은 노드 병진 등방 m·I₃ 이라 회전 변환 불변 — §4.2).

### 3.5 spring 의 k

- **auto(기본)**: k_s = α · d̂_sᵀ K₀[n_s] d̂_s, K₀[n] = 노드 n 의 병진 3×3 대각 블록(기준 설계 K₀ — 파트 자기 국부 강성), **α 기본 1.0**. 단위 N/mm.
- value: k_s = `spring_k_value`(N/mm, 모든 행 같은 값).
- 기본 근거: (1) α = 1 = "tie 상대 부재의 국부 강성 = 대상 국부 강성"(plate_led 같은 판재 체결의 1차 가정), (2) 양 극한(α→∞ = 지그 변위 행, α→0 = 자유)이 따로 있으므로 스프링 행은 중간(로그 중앙)을 보여야 의미, (3) 자기 대각 대비 배율이라 메시 크기·두께에 따라 스케일이 같이 움직임(절대 N/mm 은 부품마다 다시 정해야 함). 미결 Q-JIGC-1.
- **설계안 간 고정**: k_s 는 기준 설계 K₀ 로 한 번 계산해 `jig_spring.npz sp_k` 에 저장, 안은 재계산하지 않음(안의 비드가 K_nn 을 바꿔도 지지 강성은 같게 — 하중·지지 고정 비교).
- 민감도: 시험 V-0244-JIG-7(α ∈ {0.01, 0.1, 1, 10, 100, 1e4} — 1e4 에서 prescribed 와 ‖Δu‖/‖u‖ < 1e-3, α 증가에 따라 단조 수렴). 현장 진단 `jig.spring_alpha_scan`(예 [0.1, 1, 10] — 값마다 분해 1·기저 해 nb, `jig_spring.json alpha_scan[]` = {alpha, mac, umax_err, C_mix, E} 정보만, 출처 행 아님, 기본 빈 목록 — 계산 구현은 R-JIGC-3 으로 밀 수 있음).

### 3.6 가정 표 (방식이 뜻하는 물리)

| 방식 | 경계 가정 | 맞을 때 |
|---|---|---|
| fixed | 이웃이 tie 를 정지 상태로 강하게 잡음 | tie_rel 작음 |
| prescribed | 이웃이 훨씬 강해 tie 운동(낙하 변형)을 지배 — 설계가 바뀌어도 tie 변위 같음 | tie_rel 큼·이웃 강함(plate_led 함께 휨) |
| spring | 이웃 국부 강성 = α × 대상 국부 강성, 이웃이 낙하 변형만큼 움직임 | 중간 |
| normal(성분) | 체결이 면외만 지배적으로 잡고 면내(막) 운동은 허용 | 큰 처짐의 막 변형(처짐/두께 ≈ 20) |

### 3.7 설계안 비교 — 고정·재사용

| 방식 | J·방향(법선·3-2-1 면내) | 값 v·바닥 g | k | 맞춤 하중 F_i | 안마다 분해 |
|---|---|---|---|---|---|
| fixed | 기준 J·**기준 형상 방향 고정**(안에서 재계산 안 함) | 0(면내 = 기준 목표값) | – | 기준 a_i → F_i 고정(D-JIG-7) | 1(K_d) |
| prescribed | 같음 | **기준 g 고정** | – | 같음 | 0(fixed 공유) + 해 |
| spring | 같음 | 기준 g 고정 | **기준 k 고정** | 같음 | 1(K_d + K_s) |

### 3.8 순위 지표 — 정규화 혼합 컴플라이언스 (Π 기반)

정의(엔트리 i, 안 d — 위 고정 표대로 F·v·g·k 고정):

  C_mix = Fᵀu − Σ_c v_c r_c − Σ_s g_s f_s  ( = −2Π*, Π* = 평형의 전 퍼텐셜 에너지)
  E = 2U_tot = Fᵀu + Σ_c v_c r_c + Σ_s f_s d̂_sᵀu_{n_s} + Σ_s f_s²/k_s  (파트 + 스프링 변형 에너지 2배)
  점수 s_d = 1 + (C_mix,d − C_mix,0)/E_0,  per_esl 저장 `C_<pe>` = E_0 + (C_mix,d − C_mix,0), `C_ref` = E_0 → 기존 비(C/C_ref)·최악 엔트리(`stiffness_metric.score`) 그대로.

근거:
1. **단조성 정리**: 같은 구속 집합·값·바닥·k·F 에서 Π*(K) = min_u Π(u; K) 이고, K_d ⪰ K₀(Loewner)이면 모든 u 에서 Π(u; K_d) ≥ Π(u; K₀) → Π*_d ≥ Π*_0 → **C_mix,d ≤ C_mix,0 → s_d ≤ 1**. 강성 증가가 하중 제어 부분에선 일(F·u) 감소, 변위 제어 부분에선 반력·에너지 증가(−v·r 감소)로 나타나도 C_mix 하나가 같은 방향("작을수록 강함")으로 묶는다.
2. **기존과 일치**: 값·바닥이 없으면(fixed·translation, g = 0) C_mix = E = F·u → s_d = C_d/C_0(지금 지그 컴플라이언스 비). fixed·translation 은 옛 코드 경로로 C_jig = F·u 를 그대로 저장(바이트 동일 — 이 식을 거치지 않음).
3. **순수 변위 제어**(F = 0): s_d = 2 − U_d/U_0 — 에너지(반력) 증가가 곧 강성 증가.
4. 다른 후보를 쓰지 않는 이유: F·u(혼합 경계에서 강성 증가가 tie 근처 변위를 키워 증가할 수 있음 — 비단조), umax(prescribed 는 변위를 주므로 둔감), U 단독·반력 합(혼합 경계에서 하중 부분과 변위 부분이 반대 방향 — 비단조). C_mix 는 spring 경계를 OptiStruct 로 옮길 때(접지 스프링 + 등가 하중 F + K_s g 의 컴플라이언스)와 상수 ½gᵀK_s g 차이로 같은 목적 → 비드 최적화와 같은 잣대(R-VAL-7).
5. 주의: 변위 제어가 지배하는 아주 강한 안은 s < 0 가능(정렬은 유효, 화면 = Δ% = s − 1).

정보 지표(순위 아님): W_F = Fᵀu(하중 일), W_g = Σ v r + Σ g f_s(지지 일), R_sum 비 = (Σ|r| + Σ|f_s|)_d/(·)_0, umax(Ω — prescribed 는 강제 변위라 참고), 3-2-1 면내 반력비. per_esl 키 = `C_<pe>`·`umax_<pe>`·`umax_<pe>_ev`·`WF_<pe>`·`Wg_<pe>`(pe = `jig`(기존 `C_jig`) | `jd` | `js`).

### 3.9 ④ 검증 정의 (v0.24.3 VAL_PLAN 행)

- 응답 = 검증 단계에서 **같은 경계(행 load 파일의 bc 배열)로 재풀이**(`esl_validate_sources.md` D-0.24.3-VAL-3 원칙): `_SUPPORT_FN["jig"](ctx, model, row)` = `jig_bc.load_bc(npz)` → `BcSolve`. 지표·정의 = 다른 출처와 같음(목표 u_rel, 양쪽 `remove_linear_rigid`, 판정 = 변위 3지표).
- **reaction_role = info**(지그 반력 = 지지력, 0 이 아님 — D-0.24.3-VAL-5), 값 = Σ‖r‖+Σ|f_s| / Σ‖F‖ 과 3-2-1 면내 반력비(정보).
- 분해 묶음: 구속 패턴(bc_node·bc_dir·sp_node·sp_dir·sp_k 의 sha256)이 같은 행끼리 분해 1회 — jig·jig_disp(같은 구속 집합, 값만 다름) = 1묶음, jig_spring = 1묶음. 패턴이 다르면(예 한쪽만 실패해 다른 계산) 따로.
- note = `VAL_NOTE_RECON`. prescribed 행은 한계 `JIG_DISP_FROM_TARGET`(caution — "tie 노드 변위를 낙하 결과에서 그대로 강제 — 재현 지표가 유리하게 나옴(쓰는 정보량이 다름)").

---

## 4. 모듈 구조

### 4.1 공용 모듈 이동 (Case 가 esl.doe 를 import 하지 않게)

| 옛 위치 | 새 위치 | 내용 |
|---|---|---|
| `esl/doe/jig.py` | **`esl/mech/jig.py`** | 전체(+ `JIG_DEFAULTS` 사전 — 지금 `DEFAULTS["rank"]["jig"]` 값 + §11 새 키) |
| `esl/doe/jig_surf.py` | **`esl/rad/surface.py`** | `other_surfaces` 등 |
| `esl/doe/assem_full.py` 의 `ELEM_NODES`·`ELEM_TOTAL`·`_faces`·`_clean`·`_lead_ints` | **`esl/rad/solid_faces.py`** | 면 계산 순수 부분(assem_full 은 이 모듈에서 import) |
| `esl/doe/paicad_io.py` 의 `read_fixed`·`FIXED_KINDS`·`SCAN_JSON` | **`esl/io/fixed_scan.py`** | 읽기 |
| (문구) `esl.doe.load_messages` | **`esl/io/messages.py`**(새 — `resources/doe_messages.json` 읽기 전용 `text(code, **kw)`) | Case 지그 경고 문구 = 스터디와 같은 원본 |

- 옛 경로 = **재수출 심**(같은 객체: `esl.doe.jig.X is esl.mech.jig.X` — 공개·사용 이름 전부), `stages.py`·워커·백엔드 import 불변. `esl/doe/__init__.py` DEFAULTS `rank.jig` = `copy.deepcopy(JIG_DEFAULTS)`(값 동일 — 시험이 사전 동일 확인).
- **스터디 기존 결과 바이트 동일**: 이동만으로 산술 불변(V-0244-JIG-1 골든 — 이동 **전** 커밋에서 `ESL_GOLDEN_RECORD=1` 로 `tests/fixtures/jig_case/golden_v0243.json`: 합성 스터디 prep/jig.json(`seconds*` 제외)·jig.npz·per_esl·ranking.csv·post/jig_view.json sha256).
- import 그래프 시험: `esl.pipeline`·`esl.mech.*`·`esl.rad.*`·`esl.io.*`·`esl.val_src`·`esl.view3d_src` → `esl.doe` 0.

### 4.2 새 순수 모듈 `esl/mech/jig_bc.py` + `ShellModel` 경계 확장

`jig_bc`(import = numpy·`esl.errors`·`esl.mech.{shell,kabsch,supports,jig}`; 파일 IO·설정 해석 없음):

```
METHODS, TIE_DOFS, LEGACY_ABSENT = {"tie_dofs": "translation", "methods": ("fixed",)}
node_frames(mesh, nodes, *, kink_deg, valid_elem=None) -> {dirs: [(n, d̂)], rank_counts, n_isolated, n_null_excluded}
aux321_inplane(X0, sup321, tie_dirs, *, dup_deg) -> {rows: [(n, d̂)], n_dup}
build_bc(method_row, tie_rows, aux_rows, u_tgt, *, k=None) -> BC{bc_node, bc_dir, bc_val, bc_kind(1 tie·2 aux), sp_node, sp_dir, sp_k, sp_g}
spring_k(K0, tie_rows, *, mode, alpha, value) -> k (m,)
rigid_free(X0, mesh_components, BC) -> {rigid_free, per_comp}
mixed_compliance(F, u, BC, rc, fs) -> {C_mix, E, W_F, W_g, R_sum}
score(C_mix_d, C_mix_0, E_0) -> float;  pattern_sha(BC) -> str;  save_bc(dict)/load_bc(npz) -> BC
```

`esl/mech/shell.py`(추가만 — 기존 `solve`·`factorize`·`FactorizedSolve.solve(F)` 산술 불변):
- `FactorizedSolve.solve(F, values=None)`: `values`(len(cons), cons 순서) 가 있으면 우변 −K_fc v·u[fixed] = v. **None = 지금 코드 경로 그대로**(바이트 동일).
- `ShellModel.factorize_bc(dirs, *, springs=None) -> BcSolve`: 구속 노드마다 국부 정규직교 틀 Q_n(첫 열들 = 구속 방향, 순서대로 Gram–Schmidt)으로 병진 dof 회전 T(블록 대각), K̃ = Tᵀ(K₀ + K_s)T, 구속 dof̃ 제거 후 `_factorize`(같은 백엔드·반복 개선 1회·`_check_resid`). 사전검사 = `_check_restraint` 일반화(방향 행·스프링 행).
- `BcSolve.solve(F, values=None, ground=None) -> (u (N,6), R (N,3), rc (m,), fs (ms,))`: 반력 = Q_n r̃(전역), 스프링 힘 f_s, 평형 검사 F + R + Σ f_s d̂_s = 0. 속성 `K_t`·`free_t`·`to_local`·`to_global`(모드용 opinv — `jig.opinv_from` 이 이 속성이 있으면 변환 공간에서 동작, 없으면 지금 그대로).
- translation·fixed 는 `jig.factor`(옛 `sm.factorize`)를 계속 쓴다 — **옛 산술 경로 유지**. translation·prescribed 는 같은 FactorizedSolve 에 `values`(분해 공유). normal 은 세 방식 모두 `factorize_bc`.

### 4.3 계획 표 원칙

방식·구속 성분 차이는 `METHODS`·`TIE_DOFS` 열로만. 호출부(`pipeline._jig_esl`·`stages._jig_*`·`val` `_SUPPORT_FN`)는 열 값으로 함수를 고르고 방식 이름·출처 이름으로 분기하지 않는다.

---

## 5. Case 통합 (P2b)

### 5.1 워커 — tie 준비 `worker/esl_worker/jig_prep.py` (새, DECIDE 표)

- 위치: ESL_SOLVE 의 ESL step 안, **코어 자식 시작 전**(v0.24.2 `_bf_ondemand` 다음, `executor.py:358-360` 같은 자리) — 새 작업 유형·step 없음.
- DECIDE(위에서 첫 일치): 1 `bead_doe.case_jig.enabled` 거짓 → none · 2 코어 `jig.enabled` 거짓 → none · 3 캐시 있음(`01_extract/jig_fixed/fixed_nodes.json` 의 키 일치) → none("have") · 4 paicad 준비 안 됨 → skip `JIG_FIXED_SKIPPED` · 5 그 밖 → fill.
- fill: assem_dir = Case 폴더 제자리(starter·include·상태 파일이 모두 Case 폴더 안 — `doe_jobs._a_case` 와 같은 검사) 아니면 `<case>/_jig/assem_full/`(`_stage_full` 공용 함수 — `doe_jobs.py` 에서 추출만). paicad `fixed-scan`(대상 파트) → `<case>/01_extract/jig_fixed/`(`shell_scan.json`·`fixed_nodes.json`). 시간 한도 `bead_doe.case_jig.timeout_s`(null = `bead_doe.paicad.timeout_s.fixed_scan` 3600).
- 캐시 키 = starter 포함 include 트리 매니페스트(파일 크기·mtime_ns·sha256 — `assem_full` 매니페스트 함수 재사용) + part id + `fix_kinds`. 시도 기록 `01_extract/jig_prep.json`(작업 tag·status·code·detail — bf_ondemand 기록과 같은 형식). 01_extract 를 다시 추출하면 EXTRACT 가 백업하므로 캐시도 같이 비워짐(정상).
- 실패·시간 초과·paicad 없음 = 기록 후 ESL 계속(코어가 지그 세 행 unavailable + 같은 code·reason). 상태 파일을 paicad 가 못 읽는 경우 = `JIG_FIXED_FAILED`(reason 에 paicad 메시지) — 위험 R-JIGC-4.
- 쓰기 = Case 폴더 안만(입력·SPDM 쓰기 없음 — 사본은 Case 안 `_jig/`).

### 5.2 코어 — `pipeline._jig_esl(ctx, model, d, sel, u_rel, sm)`

`stage_esl` 끝(bforce·fint 다음, `pipeline.py:1113-1114` 뒤 — 반환 사전에 `jig`·`jig_disp`·`jig_spring` 키 추가)에 호출. 순서:
1. 설정 `jig_settings(cfg)`(§11) — `enabled` 거짓 → 요약 3행 `JIG_DISABLED`.
2. J: `fixed_scan.read_fixed(01_extract/jig_fixed)` → `jig.select_jig_nodes`(코드 `JIG_NO_TIE`·`JIG_SUPPORT_DEGENERATE`), 기록 없음 = `jig_prep.json` code(`JIG_FIXED_SKIPPED`·`JIG_FIXED_FAILED`) 또는 `JIG_NOT_PREPARED`.
3. 공유 단계(실패 = 세 행 같은 code): 법선(§3.1)·3-2-1 면내(§3.3, 03_bc/support.json)·deck 표면(`surface.other_surfaces` — 캐시 `01_extract/jig_surf.npz`, 키 = include 트리 stat + part id + 상자 + pad + `max_surf_tris`; 실패·상한 = 패치 + `JIG_REGION_FALLBACK`)·영역·fixed 분해(구속 = TIE_DOFS 열)·모드·기저·U → `04_esl/jig_basis.npz`.
4. 방식마다(설정 `methods` 순서, 각자 `try` — 예외 = 그 행만 `JIG_FAILED`): BC(값·스프링)·u_g·맞춤·F_jig·u_fit·`fit_report`·C_mix·E → `04_esl/<file>.json`·`<file>.npz`. prescribed 는 fixed 분해 재사용(fixed 행이 실패해도 공유 분해가 있으면 계속). spring = 자체 분해, 끝나면 `del`(메모리 피크 = 분해 1개).
5. 재현(③ 3D·요약): u_fit 의 파트 Kabsch 제거(`kabsch.remove_rigid`) vs u_rel → MAC·umax_err(`bforce.recon_report` 정의 — 다른 출처와 같은 수치), `npz u_val` = 그 3성분(bforce 와 같은 규칙).
6. 요약 `forces.jig`·`forces.jig_disp`·`forces.jig_spring` = {status, code, reason, method, tie_dofs, n_jig, n_regions, n_contact, n_patch, mac, umax_err, work_eff, rigid_free, aux_reaction_rel, C_mix, E, limits, limit_text}. echo 1줄/방식.

### 5.3 산출물 스키마

- `04_esl/jig_basis.npz`(`esl/case_jig_basis/1`): node_id·jig_idx·omega·tie_node·tie_dir·tie_kind·aux_node·aux_dir·reg_*·col_kind·body_w·mode_f·mode_lam·node_area 등(스터디 prep/jig.npz 와 같은 이름) + `sha256`(내용).
- `04_esl/<file>.npz`(방식마다): node_id·`f`(F_jig 기준 형상)·`a`·`u_val`(파트 Kabsch 제거 3성분)·`bc_node`·`bc_dir`·`bc_val`·`bc_kind`·`sp_node`·`sp_dir`·`sp_k`·`sp_g`(없으면 길이 0)·`jig_idx`·`basis_sha`.
- `04_esl/<file>.json`(`esl/case_jig/1`): {schema, source(key), method, tie_dofs, status, code, reason, fix{source, kinds, n_jig, n_comp, n_missing, jig_std, part_std}, tie_spread, normals{…}, aux321{…}, rigid_free, regions_from, n_contact, n_patch, surf{…}, regions[], nb, fit{mac, umax_tgt, umax_fit, umax_err, err_p95, resid_rel, work_eff, cancel_rel, tie_rel(fixed 만), with_modes, without_modes, forces[], body, modes}, recon{mac, umax_err, mac_min}, energy{C_mix, E, W_F, W_g, R_sum, aux_reaction_rel}, spring{k_mode, alpha, k_value, k_stats{min, median, max}, alpha_scan[]}(spring 만), limits[], warnings[], info[], seconds{…}}. 스터디 `esl/doe_jig/1` 와 같은 이름은 같은 뜻.

### 5.4 ③ 3D — `CASE_PLAN` 행 (jig 행 갱신 + 2행 추가)

| key | load | target | resp | recon_tgt | rigid | support | summary | doc | dir | recon_dir | na | resp_na |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| jig | esl `jig.npz` f | esl u_rel | esl `jig.npz` u_val | esl u_rel | kabsch | `jig` | jig | esl `jig.json` | view3d_jig | view3d_jig_recon | `JIG_NOT_RUN` | V3D_RESP_SKIPPED |
| jig_disp | `jig_disp.npz` … | 〃 | `jig_disp.npz` u_val | 〃 | kabsch | `jig` | jig_disp | `jig_disp.json` | view3d_jig_disp | view3d_jig_disp_recon | 〃 | 〃 |
| jig_spring | `jig_spring.npz` … | 〃 | `jig_spring.npz` u_val | 〃 | kabsch | `jig` | jig_spring | `jig_spring.json` | view3d_jig_spring | view3d_jig_spring_recon | 〃 | 〃 |

- `JIG_NOT_RUN` 문구를 `view3d_src.REASON_TEXT` 로 옮김(val_src 는 그것을 재사용 — 순환 import 없음).
- 백엔드 `services/view3d.py:SUPPORT_FILES["jig"]` = 행 load npz 의 `bc_node`(tie + 3-2-1 면내) → `support_sample(…, view3d.jig_support_max)` 표식(3-2-1 면내 노드는 별도 색 — 기존 supportColor 속성).

### 5.5 ④ 검증 — `VAL_PLAN` 행 (jig 행 갱신 + 2행 추가)

| key | load | load_frame | balance | support | reaction_role | target | summary | doc | limits | dir | na | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| jig | esl `jig.npz` f | ref_basis | `jig` | `jig` | info | u_rel | jig | esl `jig.json` | ("limits",) | jig | JIG_NOT_RUN | VAL_NOTE_RECON |
| jig_disp | `jig_disp.npz` f | ref_basis | `jig_disp` | `jig` | info | 〃 | jig_disp | `jig_disp.json` | 〃 | jig_disp | 〃 | 〃 |
| jig_spring | `jig_spring.npz` f | ref_basis | `jig_spring` | `jig` | info | 〃 | jig_spring | `jig_spring.json` | 〃 | jig_spring | 〃 | 〃 |

나머지 열: legacy F, required F, reaction_tol_key·warn_key None, rigid linear, resp solve, fallback None, noise_force F. `SUPPORTS = ("bc321", "jig")` — `jig` 뜻을 "출처 load 파일의 bc 배열(지그 세 방식 공통)"으로 개정, 묶음 = (support, `pattern_sha`)(§3.9). 문구: `BALANCE_TEXT += {jig: "지그 지지(tie 구속·3-2-1 면내)가 받음", jig_disp: "tie 강제 변위·3-2-1 면내가 받음", jig_spring: "tie 스프링·3-2-1 면내가 받음"}`, `SUPPORT_TEXT["jig"] = "지그 경계({tie_text} {n_jig} + 3-2-1 면내 {n_aux})"`(doc 값으로 채움), `LIMIT_CLASS += {JIG_DISP_FROM_TARGET: caution, JIG_AUX_REACTION: caution}`, `LABEL`·`GROUP_LABEL` = §2.1.

### 5.6 실패 격리

- 워커 tie 준비 실패 → ESL 계속, 세 행 unavailable(code·reason).
- 공유 단계 예외 → 세 행 `JIG_FAILED`(같은 reason), 방식 단계 예외 → 그 행만. **ESL 단계·full·bforce·fint 산출 바이트 불변**(지그는 새 파일만, `_bforce_esl` 과 같은 규칙).
- ④: 출처 예외는 그 행 `VAL_SRC_FAILED`(v0.24.3 규칙 그대로). OOM = `_oom_guard` → 그 행만.

### 5.7 코드 · 문구 (원본 = `resources/doe_messages.json` — 스터디와 같은 문구, Case 는 `esl/io/messages.py` 로 읽음)

| 코드 | 상태 | 뜻 |
|---|---|---|
| `JIG_NOT_RUN` | unavailable(옛 ESL) | `view3d_src.REASON_TEXT`(문구 = `esl_validate_sources.md` §2.3 그대로) |
| `JIG_DISABLED` | unavailable | 설정에서 꺼짐(jig.enabled·bead_doe.case_jig.enabled·methods 에 없음) |
| `JIG_NOT_PREPARED`(새) | unavailable | tie 준비 기록 없음(워커 구버전·코어 단독 실행) |
| `JIG_FIXED_SKIPPED`·`JIG_FIXED_FAILED` | unavailable | 워커 tie 준비 생략·실패(reason = 기록 detail) |
| `JIG_NO_TIE`·`JIG_SUPPORT_DEGENERATE` | unavailable | 기존 코드(+ detail `rigid_free`) |
| `JIG_FAILED` | unavailable | 계산 예외(공유 단계 = 세 행, 방식 단계 = 그 행) |
| `JIG_METHOD_NOT_RUN`(새) | 스터디 탭 비활성 | 이 스터디 스냅샷에 그 방식 없음 |
| `JIG_AUX_REACTION`(새) | 정보·한계 caution | 3-2-1 면내 반력비 > aux_reaction_warn |
| `JIG_DISP_FROM_TARGET`(새) | 한계 caution | prescribed — tie 변위를 낙하 결과에서 강제 |
| 기존 `JIG_FIT_POOR`·`JIG_TIE_RELATIVE`(fixed 만 — METHODS 열)·`JIG_LOAD_CANCEL`·`JIG_SUPPORT_WEAK`·`JIG_REGION_FALLBACK`·`JIG_MODES_FAILED` | 경고·정보 | 같은 기준·같은 문구 |

---

## 6. 출처 표 · 화면

### 6.1 출처 표 행 (4곳 일관 — 계획 열만)

| 표 | 위치 | jig | jig_disp | jig_spring |
|---|---|---|---|---|
| CASE_PLAN | `esl/view3d_src.py` | §5.4 | §5.4 | §5.4 |
| VAL_PLAN | `esl/val_src.py` | §5.5 | §5.5 | §5.5 |
| RANK_SOURCES | `esl/doe/stages.py` | 그대로(metric jig, need C_jig, sidecar jig, umax_pe umax_jig, uev_pe umax_jig_ev) | metric `jd`, need `C_jd`, sidecar `jig`(post/jig_view.json `rank_views.jig_disp`), umax_pe `umax_jd`, eps_pe None, uev_pe `umax_jd_ev`, drop = VIEW_DROP_JIG + (C_jig, umax_jig, C_js, umax_js), drop_pe = jig 행 drop_pe | `js` 같은 규칙 |
| SOURCE_ROWS | `frontend/src/view3d/sources.ts` | label 지그 고정·short 고정·group jig | 지그 변위·변위·jig | 지그 스프링·스프링·jig |

- 스터디 화면 `doeTabs.LOAD_SOURCES` 에 같은 두 행(열: primaryFor·drop·warnPrefixes `JIG_`·view3d·perEslKey `C_jd`/`C_js`·unavailable 문구). `stiffness_metric.VIEW_METRICS += {"jd": "C_jd", "js": "C_js"}`(보기·P3 주 지표 허용).
- 스터디가 그 방식을 계산하지 않은 결과(옛 스냅샷·P2c 전) = need 없음 → 탭 비활성 사유 `JIG_METHOD_NOT_RUN`("이 스터디는 지그 <이름>을 계산하지 않았습니다 — 새 스터디·복제에서 계산(rank.jig.methods)").

### 6.2 화면 — 그룹 탭 (Case ③ 3D·④ 검증·스터디 결과 공통 `SourceTabs`)

- `SourceTabItem.group?`·`short?`(선택 속성 — 없으면 DOM 이 v0.24.3 과 같음, V-0244-JIG-13), 그룹 이름 = `GROUPS`.
- **≥ 2201px(2560×1440)**: 한 줄 펼침 — `.seg` 안에 그룹 머리 글자(비대화형 `span.seg-group` "지그 ESL") + 하위 탭 3개(글자 = short "고정 | 변위 | 스프링", aria-label = 전체 이름, title = 조건 툴팁) + 전 노드·경계력·내력. ④ 표식(mark)은 하위 탭마다(기존 말줄임 15rem 규칙).
- **≤ 2200px(1920 등)**: 그룹 접힘 — 탭 1개 "지그 ESL · <선택 하위 short> ▾"(+ 선택 하위 표식), 클릭·Enter = 하위 목록 팝오버(절대 위치 — **높이 불변**, role listbox·option, 위아래 화살표·Esc, 각 항목 = short + mark + 비활성 사유). 선택 탭이 그룹 밖이면 머리 글자 "지그 ESL ▾". 분기 = 미디어 질의(기존 2201px 경계 D-0.23.1-UI-6 와 같은 값), 출처 이름 비교 없음(열 `group` 만).
- 키보드: 좌우 = 최상위 항목(펼침에서는 하위 탭도 최상위처럼 순서대로), 비활성 탭 포커스 시 사유 줄(기존 절대 위치 줄).
- **③ 결과 카드에 새 줄 없음**: 지그 요약(지그 노드 수·구속 성분·영역 수·재현 MAC·한계)은 3D 카드의 선택 지그 탭 title(조건 툴팁)과 기존 '재현 한 줄'(선택 출처의 MAC·umax 오차)로 보임 — 세로 증가 0. 지그 경고(JIG_*)는 기존 결과 경고 목록 그대로. `esl_validate_sources.md` §12.1 의 `esl-jig-line` 계획은 이 규칙으로 대체(정보는 같은 화면에 있음).
- ④: 지그 탭 본문 = 같은 카드(반력 칸 = 정보 "지지 반력", v0.24.3 info 규칙), 조건 툴팁 `cond_text` = "하중 지그 맞춤 · 지지 tie <성분> <n> + 3-2-1 면내 <m> · 값 <0|낙하 변위|스프링 α> · 목표 u_rel · 응답 = 검증 풀이".
- 새 버튼 0(기존 [검증 다시 실행]·[계산] 패턴 그대로). 세로 증가 0 — Playwright 2560·1920 머리 높이 = v0.24.3(완료 기준 수동 측정).

---

## 7. 강성 스터디 (P2c — 미룰 수 있음)

- 같은 모듈: `_jig_baseline` 이 스냅샷 `rank.jig.methods`·`tie_dofs` 로 세 방식 계산 → `prep/jig.{npz,json}`(fixed) + `prep/jig_disp.*`·`prep/jig_spring.*` + `prep/jig_basis.npz`(공유). `_jig_design` 이 안마다 방식별 응답 → per_esl `C_jd`·`umax_jd`·`WF_jd`·`Wg_jd`(·`_ev`), `C_js`…, C_ref = E_0(§3.8).
- **바이트 동일 규칙**: 스냅샷에 `tie_dofs`·`methods` 가 없으면 `LEGACY_ABSENT`(translation·fixed 만) → 지금 코드 경로·파일 그대로(V-0244-JIG-11 골든). 새 스냅샷(지금 DEFAULTS 로 만든 새 스터디·복제 — D-0.23.2-1 규칙)부터 normal·세 방식. translation 을 고른 새 스냅샷의 fixed 결과도 옛 코드 경로라 같은 입력이면 같은 바이트.
- 해시: 새 키는 스냅샷에 있을 때만 해시 안(`HASH_EXCLUDE += ("aux_reaction_warn", "spring_alpha_scan")`) — 옛 스냅샷 해시 불변.
- 사이드카 `post/jig_view.json rank_views` 에 `jig_disp`·`jig_spring` 키(새 스냅샷만), ranking.csv 끝 열 `C_jd, umax_jd, C_js, umax_js`(새 스냅샷·방식 계산 시만). 3D(`<did>_jd`·`_js`) = P2c 마지막(밀리면 R-JIGC-2 — 탭 3D 칸 사유 "3D 는 후속").
- 비용: 안마다 spring 분해 +1(fixed 분해와 별도), prescribed 해 +엔트리 수. 지그만 보면 안마다 ≈ ×2.

---

## 8. 비용 (현장 194k 노드·193k 요소 추정 — §0.5 외삽값 기준)

| 단계 | 추가 | 첫 ESL | 같은 Case 다른 프레임 |
|---|---|---|---|
| tie 준비(워커 fixed-scan) | paicad 수 분(한도 3600 s) | 1회 | 0(캐시) |
| deck 표면 | ≈ 84 s | 1회 | 0(캐시) |
| 법선·3-2-1 면내 | < 5 s | ✓ | ✓ |
| fixed 분해 + 모드(σ=0, ARPACK 해 수십) + 기저 해 ≤ 31 | ≈ 200 + 50~150 + 80 s | ✓ | ✓ |
| prescribed(분해 공유) u_g 해 + 응답 | ≈ 10 s | ✓ | ✓ |
| spring 분해 + 기저 해 31 + 응답 | ≈ 200 + 80 + 10 s | ✓ | ✓ |
| 파일(npz 4개 압축) | ≈ 10~20 s | ✓ | ✓ |
| **합계** | | **≈ +11~15 분** | **≈ +9~12 분** |

- `methods` 에서 spring 을 빼면 ≈ −5 분. 메모리 피크 = 분해 1개(지금 ESL 과 같음 — 분해마다 `del`).
- ④ 검증: 지그 묶음 2개(jig+jig_disp 분해 1, jig_spring 분해 1) ≈ +2 × 200 s + 해 3 + 지표 3 × ≈ 20 s → **≈ +8~9 분**. 05_val 출처 폴더 +3개(각 루트와 같은 크기).
- 04_esl 디스크: jig_basis.npz(mode_f 4×N×3 등) ≈ 15~25 MB, 방식 npz ≈ 8~10 MB × 3. 3D 캐시 = 탭 첫 열기 때(bforce 와 같은 규모).
- 합성 실측은 완료 기준(§13)에서 `forces.jig*.seconds`·`sources.json solve` 로 기록.

---

## 9. P3 — 하위 작업 출처 선택

| 항목 | 결정 |
|---|---|
| 공통 키 | 요청 `load_source: KEYS | null` — `DoeCheckIn`(스터디 생성)·`OptRunIn`(비드 최적화). 스냅샷 `doe.load_source`·opt 스냅샷 `load_source` + `load_source_check{key, entries:[{entry_id, status, comparable, validation_id}], worst}` |
| 선택 시점 | 작업 생성 때 1개(esl_validate_sources Q2 가정 유지). 생성 화면 = 선택 항목들의 그 출처 ④ 판정 요약(최악) — 항목 `validation_id` 의 `/validations/{vid}/sources`(묶음 `/library/entries/sources?ids=`) |
| 없을 때 | 지금 동작: 스터디 = `rank.metric` → metric_effective, 비드 최적화 = `full`(설정 `bead_doe.load_source_default` null·`opt_run.load_source_default` "full") — 스냅샷·해시 불변 |
| 경고 | 검증 미통과(FAIL·판정 불가·결과 없음)·`not_comparable`·`caution`(JIG_DISP_FROM_TARGET 포함) = **경고 + 확인**: `load_source_ack: true` 없으면 422 `LOAD_SOURCE_UNCONFIRMED`{entries, worst}. 차단은 **하중 없음만** 422 `LOAD_SOURCE_UNAVAILABLE`{entry_ids, reasons}. 라이브러리 등록 게이트(full PASS) 그대로 |
| 스터디 | `load_source` → 기본 탭·report.html·ranking.csv 기준 = `RANK_SOURCES[key].metric`(jd·js·bf·fi 주 지표 허용 — D-0.24.0-BF-8 개정). 지그 계열이면 새 스냅샷 `rank.jig.methods` 에 그 방식 포함 보장. P2c 전이면 jig_disp·jig_spring = 422 `LOAD_SOURCE_UNAVAILABLE`(reason "스터디 지그 <이름> 계산은 후속") |
| 비드 최적화 — 주입 지점(§0.4) | ① OPT_LOAD `load_fn`: S1 = `esl/library/source_load.find(key, entry_meta, raw)`(`stages._ns_find` 이동 — 스터디·최적화 공용, 지그 계열은 `<file>.npz` + bc 배열) → 노드 직접 하중. S2(셀 매핑) = full·bforce·fint 는 출처 하중으로 셀 요약 재생성, 지그 계열 = 422 `LOAD_SOURCE_UNSUPPORTED`. ② 선정 `sl.run`·③ 덱 `od.write` = `Target.supports` 교체(아래) |
| 지그 경계 → 최적화 모델 | **이번 버전 = 전역 SPC 로 정확히 쓸 수 있는 경우만**: `tie_dofs = translation` ∧ `fixed` → `Target.supports = [(J 노드 ID, "123")]`(기존 `SPC1` 카드·자체 솔버 spc 형식 그대로 — 선정 컴플라이언스·덱 일치). 그 밖(normal 국부 구속·prescribed SPCD·spring) = 422 `LOAD_SOURCE_UNSUPPORTED`{reason} → R-VAL-7(아래 사상 고정): normal = GRID `CD` 국부 좌표(CORD2R)·SPC1 3 또는 MPC, spring = 접지 CBUSH/CELAS(국부 방향) + 등가 FORCE K_s g(컴플라이언스 목적이 C_mix 와 상수 차 — §3.8-4), prescribed = SPCD 컴플라이언스는 방향이 반대(강할수록 커짐)라 퍼텐셜 에너지 목적(DRESP2/3) 또는 강 스프링 벌점 필요(연구), 3-2-1 면내 값 = 덱에서 0(정정 → 강체 이동만) |
| 공용 | `esl/library/source_load.py`(새 — `find(key, meta, raw) -> (dir, doc, f, bc|None, why)`), `stages._ns_find` 는 이 함수 호출(스터디 결과 바이트 동일) |

---

## 10. 질량 결과 이름 미인식 (BF_MASS_APPROX) — 설정으로 되는 범위

- 원인: 경계력 관성 항 −M·ACC 의 M 이 h3d 결과에서 안 잡혀(`data["mass"]` None) deck 밀도·두께 근사(`esl/mech/bforce.py:103-128`) → 질량 스케일링 추가 질량 미포함. 이름 후보 = `bforce.result_names.mass`(기본 `["Nodal Mass", "Mass", "MASS"]`, `esl/config.py:386-388`), TCL `bf_resolve` 가 GetDataTypeList 와 `match_name`(정확 → 대소문자·공백·밑줄 무시)으로 고름(`esl_h3d_extract.tcl:1055-1062`). 현장 표시명 미확인(사용자에게 GetDataTypeList 요청 중 — `resources/tcl/esl_h3d_probe.tcl` 의 probe.json `subcases[].data_types[].name` 으로도 볼 수 있음).
- **설정으로 해결되는 경우**: h3d 에 노드 질량 결과가 있고 이름만 다를 때 → 코어 `esl.yaml` `bforce.result_names.mass` 앞에 현장 이름을 더함(코드 변경 없음, 선택 절이라 이 키만 두면 됨). 적용 시점 = **새 추출부터**: ① h3d 추출 다시(EXTRACT 가 01_extract 백업 후 전체 재추출) 또는 새 Case. **기존 Case 는 설정만으로 안 됨** — v0.24.2 보충 판정은 "선택 프레임이 01_extract 에 있음"이면 종류 누락과 무관하게 보충하지 않는다(`bf_ondemand.DECIDE` 행 4, D-0.24.2-BFD-3).
- **설정으로 안 되는 경우**: (a) 낙하 Engine 이 노드 질량을 출력하지 않음(h3d 에 없음) → Engine 출력 추가 필요, (b) h3d 에 '추가 질량'만 있고 전체 질량이 없음 → M = deck + ΔM 합성 식 필요(코드 — R-JIGC-5). 두 경우 모두 지그 3방식에는 영향 없음(지그는 질량을 쓰지 않음, 모드 질량 = `rho_t_mm3` 집중질량).
- 개선 후보(코드 — 이번 범위 아님): TCL `bf_resolve` 의 "not in h3d" 사유에 가용 이름 목록 기록, 이름 후보가 바뀌면 종류 단위 재보충(R-JIGC-6).

---

## 11. 설정 (하드코딩 금지 — 같은 이름)

| 키 | 기본 | 위치 | 해시 |
|---|---|---|---|
| 코어 `jig.*`(선택 절 — Case) | `JIG_DEFAULTS`(`esl/mech/jig.py` — 단일 원본) | `esl/config.py` `OPTIONAL_SECTIONS += {"jig"}`·SCHEMA·`jig_settings(cfg)`, `config/esl.example.yaml`(주석 절) | 절이 없으면 cfg 주입 없음 → 설정 해시 불변 |
| `tie_dofs` | `"normal"`(새 기본 — 사용자 결정 4) \| `"translation"` | JIG_DEFAULTS·`bead_doe.rank.jig`(DEFAULTS·pydantic `BeadDoeRankJigCfg`·yaml 2) | 스냅샷에 있을 때만 |
| `methods` | `["fixed", "prescribed", "spring"]` | 같음 | 〃 |
| `normal_kink_deg` | 45.0 | 같음 | 〃 |
| `aux321_dup_deg` | 10.0 | 같음 | 〃 |
| `aux_reaction_warn` | 0.05 | 같음 | HASH_EXCLUDE |
| `spring_k_mode` | `"auto"` \| `"value"` | 같음 | 〃(안) |
| `spring_alpha` | **0.01**(≥ 1e-3 — 원안 1.0, 부록 A.1·D-0.24.4-JIG-19) | 같음 | 〃 |
| `spring_k_value` | null(value 모드에서 필수 N/mm) | 같음 | 〃 |
| `spring_alpha_scan` | `[]` | 같음 | HASH_EXCLUDE |
| `bead_doe.case_jig.{enabled, timeout_s}` | `true`, `null` | `esl/doe/__init__.py` DEFAULTS·pydantic `BeadDoeCaseJigCfg`·`config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml` | – |
| `bead_doe.load_source_default`·`opt_run.load_source_default`(P3) | `null`·`"full"` | DEFAULTS·pydantic·yaml 2 | 새 스냅샷만 |

- 옛 스냅샷의 키 없음 = `LEGACY_ABSENT`(translation·fixed) — DEFAULTS 값(normal)과 다름을 코드 상수 한 곳에 둔다(V-0244-JIG-15).
- 스키마 검사: `tie_dofs` ∈ TIE_DOFS, `methods` ⊂ METHODS 비어 있지 않음·중복 없음·`prescribed` 는 `fixed` 없이도 가능(분해 공유는 내부 — fixed 산출을 안 써도 분해는 함), `spring_k_mode = value` ⇒ `spring_k_value > 0`. 모르는 키 = CONFIG_INVALID.

---

## 12. 하위 호환

1. 옛 Case(04_esl 에 jig* 없음): 05_val·3D·검증 API 바이트 동일, 세 지그 행 = `JIG_NOT_RUN`(탭 비활성 사유), ④ sources = 세 행 `VAL_SRC_NOT_RUN` 또는 `JIG_NOT_RUN`.
2. 새 ESL 의 full·bforce·fint 산출 = v0.24.3 바이트 동일(지그는 새 파일만), 새 검증의 05_val 루트·full = 바이트 동일(V-0243-VAL-1 골든 재사용).
3. 옛 스터디(스냅샷 tie_dofs·methods 없음): prep/jig.*·per_esl·ranking.csv·result.json·jig_view.json 바이트 동일(V-0244-JIG-11). 모듈 이동도 바이트 동일(V-0244-JIG-1).
4. DB migration 없음. API = 새 행·선택 인자만(`ValidationOut`·`EslRunOut` 불변). OpenAPI 덤프 갱신.
5. 화면: group 속성이 없는 SourceTabs 사용처 DOM 동일. 스터디 탭 글자 "지그 ESL" → 그룹 머리 "지그 ESL" + 하위 "고정"(의도 변경).
6. 의도된 시험 기대값 변경: V-0241-V3D-4·5(KEYS·jig 행), V-0243-VAL-4·5(jig 행 사유·KEYS 6), 스터디 탭 글자 시험.

---

## 13. 시험 (V-0244-JIG-n)과 완료 기준

| # | 단위 | 내용 |
|---|---|---|
| 1 | 이동 | 골든(이동 전 기록) = 이동 후 스터디 prep/jig.*·per_esl·ranking.csv·jig_view.json sha256; `esl.doe.jig.X is esl.mech.jig.X`(전 이름)·`jig_surf`·`paicad_io.read_fixed`·`assem_full` 심; import 그래프(esl.pipeline·mech·rad·io·val_src·view3d_src → esl.doe 0); `DEFAULTS["rank"]["jig"]` 의 옛 키 값 = 변경 전 |
| 2 | 법선 | 평판 → rank 1·법선 ±e_z(부호 규칙), 90° 꺾임 → rank 2(두 면 법선), 30° 꺾임 → rank 1, 모서리 → 3, null shell(두께 0) 제외, 고립 → 3·카운트, 결정적 |
| 3 | 3-2-1 면내 | 축 정렬 평판: n₁ 2 + n₂ 1 = 3, n₃ 제외; 30° 기울인 평판: 같은 3(판 평면 기준); n₁ 이 tie 노드 → 법선 중복 없음(면내 유지), 꺾임 tie 노드에서 면내 행이 구속 부분공간과 겹치면 제거(n_dup); `rigid_free` = 0, 다중 성분 → JIG_SUPPORT_DEGENERATE{rigid_free} |
| 4 | 솔버 | `FactorizedSolve.solve(F)` = 변경 전 비트(values None); `solve(F, values)` = 축소 연립 직접 해(1e-12); `factorize_bc` 축 방향 구속 = `factorize(spc)` 해(1e-12); 기울인 법선 구속 해가 d̂·u = v 만족(1e-12)·평형 F+R+Σf_s = 0; 스프링 k = 1e8·diag → prescribed 해(1e-6) |
| 5 | 재현(합성 3방식) | 합성 "plate_led" 픽스처: 패널 + 위에 tie 된 강한 판(두 부품 조립 모델로 목표 생성 → 대상 파트만 추출·파트 Kabsch). 기대(픽스처 조건 = 상대 판 강성 ≫ 패널): MAC prescribed ≥ 0.95, prescribed ≥ spring(α=1) ≥ fixed(값은 시험 머리말에 기록); tie_rel ≥ 0.5 에서 fixed 는 `JIG_TIE_RELATIVE`, 나머지는 없음; 막(면내) 운동이 있는 목표에서 fixed MAC normal > translation(엄격), 목표가 기저 span 안이면 normal MAC ≥ 0.99 |
| 6 | 지표 | 두께 ×0.8·1·1.25(영역) → 세 방식 모두 s 단조 감소(정리 시험); 비드 깊이 ×0.5·1·1.5(굽힘 하중 합성 비드 판) → 세 방식 s 감소 방향; g = 0 이면 s = C_d/C_0(1e-12); F = 0 순수 변위 → Σ‖r‖·E 증가·s 감소·umax 변화 |Δumax/umax| < |Δs|(지표 선택 근거 재현); s 가 C_mix·E 식과 per_esl `C_<pe>/C_ref` 일치 |
| 7 | 스프링 | α ∈ {0.01, 0.1, 1, 10, 100, 1e4}: ‖u_s − u_p‖/‖u_p‖ α 증가에 단조 감소·1e4 에서 < 1e-3; α < 1e-3 = CONFIG_INVALID; 안 비교에서 k = 기준 값(안 K 변경에도 sp_k 동일); value 모드 |
| 8 | Case | 합성 Case(인접 쉘·tie fixed-scan 출력 픽스처): `04_esl/jig*.json·npz`·`jig_basis.npz` 스키마, translation·fixed = 같은 입력 스터디 `_jig_baseline`(엔트리 1개) a·F(1e-9); 캐시(다른 프레임 fixed-scan·deck 표면 0회, include stat 변경 → 재계산); 격리(paicad 없음·fixed-scan 실패·공유 단계 예외 → 세 행 같은 code·spring 만 예외 → 그 행만) + full·bforce·fint 파일 바이트 동일 |
| 9 | ④ | 지그 묶음 2개(jig+jig_disp 분해 1·jig_spring 1 — `sources.json solve.groups`), 응답 = ESL u_fit(1e-9 상대), reaction info·판정 = 변위 3지표, jig_disp 한계 JIG_DISP_FROM_TARGET(caution·탭 ⚠) |
| 10 | 계획 표 | KEYS 6 = CASE_PLAN = VAL_PLAN = RANK_SOURCES = SOURCE_ROWS = LOAD_SOURCES 키, check_plan(모든 열), METHODS·TIE_DOFS 모든 열; 소스 grep — 호출부에 출처·방식 이름 문자열 비교 없음 |
| 11 | 스터디 | 옛 스냅샷 바이트 = 골든; 새 스냅샷 = 세 방식 per_esl·ranking.csv 끝 열·jig_view rank_views; P2c 전 = 탭 비활성 `JIG_METHOD_NOT_RUN` |
| 12 | API | `/esl-runs/{id}/view3d/sources`·`/validations/{vid}/sources` 6행(옛 Case = JIG_NOT_RUN), `?src=jig_disp` 3D·검증, 지원 노드 표식, 모르는 src 404 |
| 13 | vitest | 그룹 펼침(≥2201)·접힘(≤2200 — 팝오버·키보드·mark·사유), group 없으면 DOM 동일(기존 시험 무수정), 출처 이름 비교 없음, 실제 응답 픽스처 `real_v0244.json` |
| 14 | P3 | load_source 없음 → 스냅샷·해시 v0.24.3; 미통과·caution → 422 UNCONFIRMED → ack 202; 하중 없음 422 UNAVAILABLE; 최적화 jig·translation·fixed → `Target.supports` = J 123·덱 SPC1·선정 C 가 같은 지지; normal·prescribed·spring·S2 지그 → 422 UNSUPPORTED; `source_load` 결과 = 스터디 `_ns_find` 바이트 동일 |
| 15 | 설정 | JIG_DEFAULTS = DEFAULTS rank.jig = pydantic = yaml 2(이름·값); 코어 jig 절 없음 → cfg·sha 불변; LEGACY_ABSENT; 스키마 오류 CONFIG_INVALID |
| 16 | 질량 이름 | `bforce.result_names.mass` 앞에 이름 추가 → TCL 요청 키 `bf_names_mass` 첫 후보(기존 함수 — 문서화 시험) |

완료 기준: 위 전부 + 기존 시험 무수정 통과(§12-6 의도 변경 제외), ruff·mypy·tsc·eslint·`check:api`·`dump_openapi.py --check`. 골든(V-1·V-11)이 코어 변경 **전** 커밋에 있음. Playwright 2560·1920 머리 높이 = v0.24.3. 합성 Case 시간(`forces.jig*.seconds`·`sources.json solve`) 이 문서 부록에 기록. `docs/decisions.md` D-0.24.4-JIG-1~18 반영, 계약과 다른 구현은 부록.

---

## 14. 작업 분해 (단계 안 소유 파일 겹침 없음)

| 단계 | 묶음 | 소유 파일 | 선행 |
|---|---|---|---|
| P2a | **A2a 코어 공용**(opus) | `esl/mech/jig.py`(이동+JIG_DEFAULTS)·`esl/mech/jig_bc.py`(새)·`esl/mech/shell.py`(추가만)·`esl/rad/surface.py`·`esl/rad/solid_faces.py`·`esl/io/fixed_scan.py`·`esl/io/messages.py`(새)·심 `esl/doe/{jig,jig_surf,paicad_io,assem_full,__init__}.py`·`resources/doe_messages.json`(새 코드 문구)·`tests/mech/test_jig_bc.py`·`tests/mech/test_shell_bc.py`·`tests/doe/test_jig_move.py`·`tests/fixtures/jig_case/golden_v0243.json`(**먼저**) | 없음 |
| P2b | **A2b 코어 Case** | `esl/pipeline.py`(_jig_esl·_SUPPORT_FN jig·묶음 키)·`esl/view3d_src.py`·`esl/val_src.py`·`esl/config.py`·`config/esl.example.yaml`·`esl/report/case_report.py`(필요 시 그룹 이름)·`tests/pipeline/test_jig_case.py`·`tests/test_val_src.py`·`tests/test_view3d_src.py`(기대값) | A2a |
| P2b | **W2 워커** | `worker/esl_worker/jig_prep.py`(새)·`executor.py`(ESL step 훅)·`doe_jobs.py`(`_stage_full`·fixed-scan 호출 공용 추출만)·`core_adapter.py`(지그 래퍼)·`worker/tests/test_jig_prep.py` | A2a(fixed_scan) |
| P2b | **B2 백엔드** | `api/services/view3d.py`(SUPPORT_FILES jig)·`core/config.py`(case_jig·rank.jig 새 키)·`api/schemas.py`(필요 시 출처 행 선택 필드)·`config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml`·`docs/contracts/openapi_p1b.json`·`backend/tests/test_jig_case_api.py` | A2b 행 형식(§5.4·5.5 — 병행) |
| P2b | **C2 프런트** | `view3d/sources.ts`·`view3d/SourceTabs.tsx`(group)·`pages/doe/doeTabs.ts`(LOAD_SOURCES 2행)·`styles.css`·`mock/server.ts`·`__tests__/jig_group.test.tsx` | §6.2(병행) |
| P2b | **S2-min 스터디 행** | `esl/doe/stages.py`(RANK_SOURCES 2행만)·`esl/doe/stiffness_metric.py`(VIEW_METRICS jd·js) | A2a |
| P2c | **S2 스터디 계산**(미룰 수 있음) | `esl/doe/stages.py`(_jig_baseline·_jig_design·사이드카·CSV)·`tests/doe/test_jig_methods.py` | S2-min |
| P3 | **A3 코어** | `esl/library/source_load.py`(새)·`esl/opt/target.py`(지그 지지)·`esl/doe/stages.py`(load_source → metric — S2 뒤) | P2b(S2) |
| P3 | **W3 워커** | `worker/esl_worker/core_adapter.py`(_opt_load·_opt_prep 출처 주입) | A3 |
| P3 | **B3 백엔드** | `api/schemas.py`(load_source·ack)·`services/doe.py`·`services/opt.py`·`services/library.py`(묶음 판정)·테스트 | A3 |
| P3 | **C3 프런트** | 스터디·비드 최적화 생성 화면(출처 선택·확인 대화)·결과 칩 | B3 형식 |
| 통합 | | `CHANGELOG.md`·`VERSION`·`docs/manual/user.md`(③ 지그 3방식·④ 지그 탭 한 단락)·이 문서 부록 | 전부 |

순서: A2a(골든 → 이동 → jig_bc·shell) → A2b·W2·B2·C2·S2-min 병행 → (S2) → A3 → W3·B3·C3 → 통합. 시간이 모자라면 미룸: **S2(P2c)** → R-JIGC-1, 스터디 3D → R-JIGC-2, `spring_alpha_scan` 계산 → R-JIGC-3, 비드 최적화 지그 계열(translation·fixed 제외) → R-VAL-7.

---

## 15. 미결 (결과를 바꾸는 것만 — 가정대로 진행)

- **Q-JIGC-1** spring 기본 α = 1(자기 국부 강성과 같은 이웃) — 대안: α 다른 값 또는 절대 k(N/mm). 지그 스프링 행의 하중·재현·순위가 직접 바뀜. 현장 첫 실행에 `spring_alpha_scan: [0.1, 1, 10]` 권장(R-JIGC-3 구현 시).
- **Q-JIGC-2** 꺾임 노드 규칙 kink_deg = 45°(넘으면 두 면 법선 모두 구속) — 대안 30°·60°·항상 1방향. 플랜지·모서리 tie 의 구속 성분 수가 바뀌어 normal 결과가 바뀜.
- **Q-JIGC-3** 3-2-1 면내 값 = 그 방식 목표값(프레임 고정점, fixed 포함) — 대안: fixed 는 0. fixed·normal 의 면내 강체 어긋남이 맞춤 잔차·MAC 에 들어가는지가 바뀜(정정이라 반력·변형 무관).

## 16. 결정 (요약 — 전문 `docs/decisions.md` 2026-11-20)

D-0.24.4-JIG-1 범위·단계 · (부록 A.1: -19 spring α 기본 0.01 · -20 맞춤 3-2-1 면내 반력 0 등식) · -2 세 방식 = 별도 출처 행·이름·공유 기저 · -3 tie 구속 성분 normal(새 기본)·translation · -4 법선 정의 · -5 3-2-1 면내 항상·중복·rigid_free · -6 prescribed · -7 spring·k · -8 설계 비교 고정 표 · -9 순위 지표 Π 기반 · -10 모듈 이동·jig_bc·ShellModel 확장 · -11 Case 통합·산출물·격리 · -12 출처 표 행·④ 묶음·한계 · -13 화면 그룹 탭·새 줄 없음 · -14 P3 · -15 질량 이름 · -16 설정 · -17 하위 호환 · -18 비용.

## 17. 후속 (R-JIGC-n)

- R-JIGC-1 (P2c 가 밀리면) 스터디 세 방식 계산. R-JIGC-2 스터디 jig_disp·jig_spring 3D. R-JIGC-3 `spring_alpha_scan` 계산·화면.
- R-JIGC-4 상태 파일(.str/.sta) include 를 paicad fixed-scan 이 못 읽는 경우 — 원본 include 만 사본(상태 파일 제외) 재시도.
- R-JIGC-5 h3d 에 추가 질량만 있을 때 M = deck + ΔM 합성. R-JIGC-6 bf_resolve 사유에 가용 이름 목록·종류 단위 재보충.
- R-JIGC-7 fixed·normal 목표 프레임을 점-면(법선 가중) Kabsch 로(지금 = 전 성분 Kabsch).
- R-JIGC-8 기하 비선형(막) 강성 K_σ(u_rel) 추가 연구(가설 검증 후).
- R-VAL-7(새) 비드 최적화 지그 경계 덱 전달(§9 사상). R-VAL-3(스터디가 Case 지그 재사용)·R-VAL-6 그대로.

---

## 부록 A. P2b A2b(코어 Case)·S2-min 구현 기록 (2026-11-20)

### A.1 메인 결정 반영 (계약 본문과 다른 값 — 결정 1줄씩)

- **spring 기본 α = 0.01**(§3.5·§11 의 1.0 대체, D-0.24.4-JIG-19): P2a 합성에서 α = 1 은 노드 자기 강성이라 패널 전체보다 훨씬 단단해
  spring ≈ prescribed(‖Δu‖/‖u‖ 2.4e-5), α ≲ 1e-2 에서야 구분됨(Q-JIGC-1 사용자 확인 대기). 키 이름 그대로, 값은 `esl.mech.jig.JIG_DEFAULTS`
  한 곳(`jig_bc.spring_k(alpha=None)` = 그 값). B2 의 DEFAULTS·pydantic·yaml 2 거울도 0.01.
- **맞춤의 3-2-1 면내 반력 0 등식 제약**(§3.3 "평형이면 ≈ 0" 을 강제, D-0.24.4-JIG-20): P2a 관찰 — normal tie 의 면내 하중은 3-2-1 면내
  3자유도만 받아 prescribed 반력비 1.19. 맞춤에 r_aux(a) = r_aux,g + Σ a_k r_aux,k = 0(같은 분해의 기저 열마다 3-2-1 면내 행 반력 —
  `jig_bc.basis_response` rc_aux, `jig_bc.aux_eq`)을 등식으로 넣음. 평판·정정이면 면내 합력 2·면내 모멘트 1 = 0 과 같고(면외 tie 반력은
  면내 강체 일을 하지 않음), 곡면에서도 반력 자체를 0 으로 둠. 풀이 = `jig.fit_loads(eq=(C, c))`: 등식 행 SVD 축소 → 하한 없는(접선·체적력·
  모드) 열 중 피벗 QR 앞 r 개를 종속 열로 소거 → 같은 BVLS(법선 ≥ 0 그대로). 소거 불가(하한 없는 열 부족·계수 0) = 제약 없이 + `fit.aux_eq
  {applied false, reason}`. 3-2-1 면내 행이 없으면(translation) 제약 없음 = 옛 산술 경로(시험 비트 동일). 스터디(P2c 전)는 jig_bc 를 쓰지
  않으므로 바이트 불변.

### A.2 계약과 다른 점·더한 것 (B2·C2·W2 가 맞출 것)

| 항목 | 구현 |
|---|---|
| `04_esl/<src>.json` 추가 키 | `method_name`, `bc{tie_dofs, tie_text, n_jig, n_tie_rows, n_aux}`(④ 지지 문구 자리 값), `recon{status ok·poor, mac_min, mac, umax_ref, umax_val, umax_err, reaction_rel, reaction_max_rel, support_rel}`, `fit.aux_eq{n, applied, reason, resid}`·`fit.n_bound_active`·`fit.rot_deg`, `limit_text[]`(limits 와 같은 순서 — 문구 원본 resources/doe_messages.json), `warning_text[]`·`info_text[]`, `shared_warnings[]`, `seconds{fit, total}`·`seconds_shared{tie, surf, regions, factor, modes, basis, factor_<src>}`, `fill_reason`, `basis_cfg{…}`, `aux321{nodes(node_id), rows[[node_id, dir]], n_dup, plane}` |
| 요약 `forces.<src>` | 계약 키 + `fit_mac`(맞춤 노드 MAC — `mac`·`umax_err` 는 재현 = 파트 Kabsch vs u_rel), `recon`(ok·poor), `seconds`·`seconds_shared`·`seconds_all`. 불가 = {status unavailable, code, reason, method, tie_dofs} |
| 불가 때 파일 | 준비 전 코드(JIG_DISABLED·JIG_NOT_PREPARED·JIG_FIXED_SKIPPED·JIG_FIXED_FAILED) = 04_esl 에 쓰지 않음(옛 Case 와 같은 산출물 집합), JIG_NO_TIE·JIG_SUPPORT_DEGENERATE·JIG_FAILED = `<src>.json` {status unavailable, code, reason, fix…}(npz 없음 — ④ 행 code 는 진단 json 우선) |
| `jig_basis.npz` | schema·node_id·jig_idx·omega·tie_node·tie_dir·aux_node·aux_dir·col_kind·reg_*·node_area·body_w·mode_f·mode_lam·mode_rho_t·sha256(앞 배열 이름순 내용 해시 = 방식 npz `basis_sha`). 계약의 tie_kind·reg_q·body_q·mode_q 는 저장 안 함(크기 — 스터디 전달용 밀도 키는 P2c 몫) |
| `JIG_AUX_REACTION` | 정보(info) + 한계(limits — LIMIT_CLASS caution)에 함께(④ 탭 ⚠) |
| 워커 기록 `01_extract/jig_prep.json` 읽기 | `{attempts: [{job_id, status ok·failed·skipped·disabled, code?, detail}]}`(bf_ondemand 형식, 단일 사전도 허용). 이 작업 tag 의 마지막 시도가 ok 아니면 code(없으면 status → JIG_FIXED_FAILED·JIG_FIXED_SKIPPED·JIG_DISABLED)·reason = 문구(detail). tag 시도 없음 = JIG_NOT_PREPARED. tie 자료 = `01_extract/jig_fixed/{shell_scan.json, fixed_nodes.npz}`(paicad 출력 그대로) |
| deck 표면 캐시 `01_extract/jig_surf.npz` | key = {starter·include 경로·size·mtime_ns, part, 상자 lo·hi, pad, max_tris, include_path_map, depth} JSON 문자열, 배열 x·node_id·tri·tri_part·tri_thick + meta. 쓰기 = tmp → replace, 실패해도 계산 계속 |
| ④ `sources.json solve.groups` | 지그 묶음에 `pattern`(구속 패턴 sha 앞 16자) 키(bc321 묶음엔 없음 — 옛 출력 불변). 지그 행 validation.json `reactions` = bc 노드(dof 표시 "tie"·"aux321"·"spring"), 반력 R = 구속 반력 + 스프링 힘 |
| `val_src` 더함 | `SHORT`·`GROUP`·`GROUP_LABEL`(§2.1), `SUPPORT_FIELDS`·`support_text(support, doc)`(SUPPORT_TEXT 자리 = doc.bc), `limit_doc_text(row, doc)`·`limit_info(codes, texts=None)`(LIMIT_TEXT 우선 → 진단 json 문구 — 기존 출처 불변). `REASON_TEXT["JIG_NOT_RUN"]` → `view3d_src.REASON_TEXT` 로 이동 |
| 스터디 S2-min | RANK_SOURCES jig_disp·jig_spring 행 = §6.1 그대로(drop 은 중복 제거 튜플 `VIEW_DROP_JD`·`VIEW_DROP_JS`), `_rank_views` 는 need 가 베이스라인에 없으면 그 행 보기를 만들지 않음(jig·full 은 기존 `_jig_ref` 와 같은 조건 — 옛 스터디 바이트 골든 통과) |
| 코어 설정 `jig` 절 | `esl/config.py SCHEMA["jig"]`(범위 = pydantic BeadDoeRankJigCfg + 새 키 §11), 모든 키 선택(OPTIONAL_KEYS), `jig_settings(cfg)`(JIG_DEFAULTS 지연 import — 설정 로더가 scipy 를 끌지 않음), 키 사이 조건 min_regions ≤ max_regions·value ⇒ spring_k_value |
| modes_ref321 | Case 도 계산(정보 hz_321·hz_ratio — 스터디와 같은 뜻) |
| 화면 이름 시험 | `tests/test_val_src.py::test_v4_labels_equal_frontend_source_rows` 는 sources.ts 에 jig_disp 행이 없으면(C2 병합 전 트리) skip — 병합 후 항상 비교. C2 SOURCE_ROWS 는 `{ key: "…", label: "…"` 순서 유지 필요 |

### A.3 합성 기록 (이 환경 — numpy·scipy 같은 서명)

- 시험 `tests/mech/test_jig_aux_eq.py`(led 픽스처): 3-2-1 면내 반력비 fixed 0.051·prescribed 1.191·spring 1.191 → 제약 후 세 방식 < 1e-10.
  맞춤 MAC fixed 0.65582 → 0.65578, prescribed 0.99973 → 0.99969, 파트 Kabsch 재현 MAC 0.63424·0.99981 그대로. α = 0.01 같은 F 에서
  ‖u_s − u_p‖/‖u_p‖ ≈ 2.3e-3(α = 1 = 2.4e-5).
- 시험 `tests/pipeline/test_jig_case.py`(synth_case 판 1107 노드 + 이웃 쉘 파트 9, tie 9, normal): 재현 MAC 고정 0.612 · 변위 0.997 ·
  스프링 0.997(제약 전 0.626·0.997·0.997), 3-2-1 면내 반력비 제약 전 0.399·0.154·0.217 → 후 ≤ 1.2e-12. α = 0.01 spring vs prescribed
  ‖Δu‖/‖u‖ = 3.9e-2(같은 F)·1.1e-2(각자 맞춤). 시간(2코어): 공유 단계 tie 0.003 s·표면 0.005·영역 0.005·분해 0.13·모드 0.12·기저 0.06,
  spring 분해+기저 0.23, 방식 맞춤 0.01~0.03 s, ESL 전체 ≈ 1.4 s. ④ 묶음 3(bc321 · jig+jig_disp 분해 0.16 s · jig_spring 0.16 s).
- 골든: 옛 스터디 41 파일·Case 36 파일 = v0.24.3 기록(`tests/doe/test_jig_move.py` — 새 코드 + 옛 출처 표 재실행 = 골든 전부, 새 출처 표 =
  의도된 05_val/sources.json·07_report/report.html 2파일만 다름). V-0243-VAL-1 골든(05_val 루트·full) 통과.

### A.4 P2b 통합 메모 (2026-11-20 — 코어 A2b+S2-min · 워커·백엔드 W2+B2 · 프런트 C2 병합 뒤)

고친 것
- 설정 일치: `esl.doe.DEFAULTS["rank"]["jig"]` 새 키 9개(JIG_NEW_KEYS, spring_alpha 0.01)·`DEFAULTS["case_jig"] = {enabled true, timeout_s null}` — pydantic·yaml 2개·`esl.example.yaml`·`esl.mech.jig.JIG_DEFAULTS` 와 같은 이름·값. `test_rank_defaults_mirror`·`test_defaults_mirror_core` 의 "코어에 없으면 건너뜀" 예외를 없애 전체 대조.
- 해시: `jig.HASH_EXCLUDE` 에 `HASH_EXCLUDE_V0244`(aux_reaction_warn·spring_alpha_scan)를 지금 더함. 옛 스냅샷(키 없음) 해시 불변(골든 41 파일 통과), 새 스냅샷은 이 둘 밖의 새 키 7개(계산을 바꾸는 값)가 해시 안. `test_hash_view_drops_thresholds` 기대 집합에 두 키 추가(근거 §7·§11).
- 백엔드: `doe.RANK_VIEWS` 에 jig_disp·jig_spring(사이드카는 jig_view.json 하나). `view3d.SUPPORT_FILES["jig"]` 은 B2 에 이미 있었음 — 스프링 행은 tie 가 구속이 아니라 스프링이라 `bc_node` 에 tie 가 없으므로 `sp_node` 도 tie 표식으로 더함(세 행 모두 tie "123"·3-2-1 면내 "ij").
- 워커: `register_esl` 이 `forces` 에 지그 세 행 요약을 옮기지 않던 것(bforce·fint·plastic 만) → 출처 표 `summary` 열이 정한 키를 모두 옮김. 이 누락으로 3D·검증 출처 행이 요약(사유 코드·recon)을 못 읽어 JIG_FIXED_SKIPPED 등이 JIG_NOT_RUN 으로 보였음.
- 시험 기대값: 출처 표 KEYS 4 → 6(worker test_val_src_e2e, backend test_view3d_src_api·test_val_src_api·test_jig_case_api 의 가짜 계획 표는 코어 표가 이미 지그 3행이면 덮어쓰지 않음), jig 행 사유 V3D_STUDY_ONLY → JIG_NOT_RUN(Case), `view3d.case_src_default` 에 jig* 허용.
- 형식 대조(실제 응답으로 확인): 워커 `jig_prep.json` 은 단일 사전 `{schema, job_id, status, code, cause, detail, …}`(코어 `_jig_prep_note` 가 attempts 목록·단일 사전 둘 다 읽음, job_id = 작업 id = 코어 tag), `jig_fixed/{shell_scan.json, fixed_nodes.npz}` 는 코어 `esl.io.fixed_scan.read_fixed` 가 그대로 읽음. 프런트 `supportSymbol("123")` = 채움 ▲, `("ij")` = 반 채움 ◭(글자 2개). 요약 fit_mac·recon·seconds*·JIG_AUX_REACTION(info+limits)·sources.json 지그 묶음 pattern·JIG_NOT_RUN 문구(view3d_src.REASON_TEXT 한 곳)를 B2·C2 가 읽음. 화면 이름 시험 `test_v4_labels_equal_frontend_source_rows` 는 skip 없이 비교.
- 실연동 시험 `worker/tests/test_jig_case_e2e.py`(가짜 paicad → ESL_SOLVE → 코어 지그 3방식 → VALIDATE → API) + 응답 픽스처 `frontend/src/__tests__/fixtures/real_v0244.json`(재생성 `JIG_E2E_DUMP=<경로>`)·`v0244_real_backend.test.ts`. paicad 없는 환경: ESL 성공·기존 산출물 그대로·세 행 JIG_FIXED_SKIPPED·`[esl-worker] 지그 tie 준비 생략` 로그 1줄·산출물 등록에 jig_prep.json.

남은 것
- P3(load_source)·P2c(스터디 세 방식 계산 — `_rank_views` 는 need 가 없으면 jd·js 보기를 만들지 않음, 지금 스터디는 jig 만).
- 가짜 paicad 는 RBE2 종류 클러스터를 돌려주므로 연동 시험은 코어 `jig.fix_kinds: [RBE2]` 로 연다(실제 paicad = INTER_TYPE2_*).
- Q-JIGC-1(α)·2(kink 45°)·3(3-2-1 면내 값) 사용자 확인 대기. A.2 의 `jig_prep.json` 형식 설명(attempts 목록)은 코어 읽기 쪽 허용 형식이고 워커는 단일 사전을 씀.

