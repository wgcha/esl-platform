# 계약: 지그 진단 뷰 · 하중 정의 탭 · 3D 다시 만들기 (JIG_VIEW, v0.23.3)

- 상태: **확정**(2026-11-18, 메인 지시 + 사용자 추가 15:47 하중 정의 탭). main bd38df35(v0.23.2) 위 브랜치 `release/v0.23.3`.
- 버전: **v0.23.3**(패치). migration **없음** — 새 값은 `post/` 새 파일(`post/jig_view.json`, `post/view3d/d000_jigdiag_*`)·결과 응답 새 필드·작업 params 만. 새 작업 유형 없음(기존 `DOE_RUN` + `resume_from_step`).
- 관계: `esl_jig_rank.md`(v0.23.0)·`esl_v0232_fixes.md`(v0.23.2 지그 3D)·`esl_doe_ui_tidy.md`·`docs/design/doe_study_ui_v0231.md`(v0.23.1 화면)를 보완. 충돌하면 이 문서가 우선(해당 항목 범위).
- ID: 결정 `D-0.23.3-n`, 시험 `V-0233-n`.
- 근거(현장 2026-11-18, v0.23.1 서버 새 스터디 75R9J chassis_rear 4엔트리 20안): ranking.csv metric=jig, `jig_fit_mac 0.159`·`jig_umax_err 0.839`(목표 MAC ≥ 0.9·오차 ≤ 0.2 — 기준 재현 실패), C_jig 0.998~1.022, umax_jig 비 0.9994~1.0005. 사용자: "컨투어가 3-2-1 고정만 보여서 지그 ESL 이 어떻게 구해졌는지 눈으로 확인이 안 된다", "예전 ESL 이 섞여 보여 헷갈린다 — 어떤 ESL 로 비교하는지 탭으로 표와 컨투어를 분리하라".

## 0. 조사 결과 (bd38df35)

| 항목 | 위치 | 확인 |
|---|---|---|
| jig.npz | `stages._jig_baseline` → `prep/jig.npz` | `node_id·jig_idx·omega·col_kind·reg_*·body_w·mode_f·entry_ids·a·C_ref·umax_ref` + 밀도 키. **u_tgt·u_fit 없음** |
| jig.json | 같은 곳 → `prep/jig.json` | 엔트리 `tie_rel·rot_deg·forces[{region,F_n,F_t1,F_t2,F,active}]·body·modes·with/without_modes·work_eff`, `fix.n_jig·tie_spread·n_contact·n_patch·regions[{id,kind,part,n_nodes,area_mm2,center,normal,sign}]`. **없음**: 기저 종류별 기여, u_tgt 면외/면내 비 |
| u_tgt 재현 | `jig.target_disp(X, sm_ref u[:3], J, fit)` | 순수·결정적 → BD_POST 에서 같은 값 재계산 가능(`prep/sm_ref.npz` 는 남아 있음) |
| u_fit 재현 | `forces(basis, a)` → 지그 분해 → solve | 선형 → 종류별 하중 F_reg·F_body·F_mode 를 따로 풀면 합 = u_fit |
| 후처리 재실행 | 백엔드·워커·화면 | **없음**. DOE 작업 유형 3개(PREP·PREVIEW·RUN), DB check 제약에 유형 목록 고정(새 유형 = migration). `jobs_repo.insert_job(resume_from_step=k)` = 앞 step SKIPPED. `retry_job` 은 DONE 스터디 거부. 워커 `register._study` 는 DONE 스터디에 DOE_RUN 등록 거부(DOE_PHASE_STALE) |
| 결과 읽기 | `services/doe.py:_result_doc` | `post/result.json` 파일 우선(DB result 는 대체) → 새 키는 파일만으로 응답 가능 |
| view3d 파일 | `VIEW3D_FILES = part.glb·part_lod.glb·values.bin` | 새 이름은 목록 추가 필요 |
| 화면 | `DoeStudy.tsx` 결과 카드: StatusBand · 2열(DoeRanking·DoePerEslTable | Compare3D·Sensitivity), Compare3D 의 v0.23.2 토글 [지그 하중 | 전 노드 ESL] | 지그·전 노드 값이 한 표·한 띠·한 3D 에 섞임 |
| View3DCard | `F/view3d/View3DCard.tsx` | 화살표 = manifest top/clusters(K-means), 색 = 하중·변위, 변형 배율 = 카드마다 따로 |

## 1. 지그 진단 산출 (코어 BD_POST — D-0.23.3-1)

### 1.1 조건 · 위치
- 조건: 스냅샷 지그 계산됨(`_jig(c)` ∧ `prep/jig.json` status ok ∧ `prep/jig.npz`) ∧ 설정 `bead_doe.view3d.jig_diag` 참. 아니면 아무것도 쓰지 않음(지그 없는 스터디 결과 바이트 동일).
- 위치: BD_POST(새 실행) **와** 3D 다시 만들기(§3) 가 같은 함수 `stages._jig_extras` 를 부른다. 베이스라인 계산(BD_BASELINE·`prep/jig.*`)은 바꾸지 않는다 — 진단은 jig.npz 값을 재사용하고 u_tgt·u_fit 만 다시 푼다(분해 1 + solve 3 × 엔트리).
- 기준 재현 계산(맞춤·순위)은 **바꾸지 않는다**(보고만).

### 1.2 공용 순수 함수 (`esl/doe/jig.py`, 가산)
| 함수 | 입출력 |
|---|---|
| `kind_forces(basis, a, n_nodes) -> {"region": (N,3), "body": (N,3), "mode": (N,3)}` | 열 종류별 하중(영역 = col_kind 1·2, 체적력 = 3, 모드 = 4). 합 = `forces(basis, a)`(같은 누적 순서 — 비트 동일 아님, 1e-12 상대) |
| `kind_response(h, parts) -> {"u": (N,3), "parts": {k: (N,3)}}` | 종류별 하중을 같은 분해로 풀고 u = Σ parts(선형 중첩). 하중 0 종류는 solve 생략·0 |
| `diag_report(u_tgt, u_fit, parts, weights, fit_mask) -> dict` | `contrib{region, body, mode}` = ‖u_k‖_F / ‖u_fit‖_F(맞춤 노드 F, 병진 L2 — 상쇄가 있으면 합 > 1), `tgt_out_frac` = Σ_F A‖(n̂·u_tgt)n̂‖² / Σ_F A‖u_tgt‖²(면외 에너지 비, 면내 = 1 − 이 값), `err_max` = max_F ‖u_fit − u_tgt‖, `umax_tgt`, `umax_fit` |
| `region_vertices(basis) -> list[np.ndarray]` | 영역마다 노드 인덱스(정렬) — `reg_ptr·reg_node` 그대로 |

### 1.3 파일 (엔트리 kk = 스냅샷 엔트리 순서 2자리, jig.npz 에 있는 엔트리만)
- `post/view3d/d000_jigdiag_e<kk>_tgt/` = `build_view(기준 mesh, f = F_e(맞춘 전체 하중), u_rel = u_tgt, supports = tie 부분집합(view3d.jig_support_max, dof 123), esl_run_id = e)`
- `post/view3d/d000_jigdiag_e<kk>_fit/` = 같고 `u_rel = u_fit` + `regions.json`(§1.4)
- `post/view3d/d000_jigdiag_e<kk>_err/` = 같고 `u_rel = u_fit − u_tgt`(|·| = 오차장)
- did 규칙은 기존 `^[0-9a-z_]{1,64}$` 안. 파일 제공 목록 `VIEW3D_FILES` 에 `regions.json`(application/json) 추가.

### 1.4 `regions.json` (`esl/doe_jig_regions/1`)
`{schema, regions: [{id, kind: "contact"|"patch", part|null, n_nodes, area_mm2, center[3], normal[3], vertices: [int]}], jig_vertices: [int](tie 부분집합 정점)}` — vertices = 기준 메시 노드 인덱스 = view3d 정점 번호.

### 1.5 결과 `jig_diag` (사이드카 §4, 응답 `DoeResultOut.jig_diag`)
```text
{ schema: "esl/doe_jig_diag/1", n_jig, tie_spread, n_contact, n_patch, regions_from,
  regions: [{id, kind, part, n_nodes, area_mm2, center[3]}],
  entries: [{ entry_id, label, kk, dirs: {tgt, fit, err},
              mac, mac_nomodes, umax_err, umax_err_nomodes, work_eff, tie_rel, rot_deg,
              umax_tgt, umax_fit, err_max, contrib: {region, body, mode}, tgt_out_frac,
              forces: [{region, kind, F[3], F_mag, F_n, F_t1, F_t2, active}], F_region_sum[3],
              body: [3]|null, modes: [{k, a}] }] }
```
- 값 출처: mac·umax_err·work_eff·tie_rel·rot_deg·forces·body·modes = `prep/jig.json` 엔트리 그대로(재사용), contrib·tgt_out_frac·err_max·umax_* = §1.2 재계산. `F_region_sum` = Σ_r forces[r].F(화살표 합 검사용). `F_mag = ‖F‖`.
- 항목 4 점검표(빠짐 없음): tie_rel ✓(jig.json → jig_diag), rot_deg ✓, 영역 수 contact/patch ✓, 영역별 합력 ✓, 기저 종류별 기여 **추가**(contrib), u_tgt 면외/면내 비 **추가**(tgt_out_frac), 지그 노드 수·tie_spread ✓. jig.json 자체는 바꾸지 않는다(옛 스터디도 같은 정보를 얻도록 계산 위치 = BD_POST 한 곳).

## 2. 하중 정의 탭 자료 `rank_views` (코어 BD_POST — D-0.23.3-2)

- 조건: 베이스라인 per_esl 에 C_jig 가 모두 있음(`rank._jig_ref` 성립 — 지그 status ok/poor). 아니면 키 없음(탭 = 전 노드 하나).
- 두 보기: `jig` = `rk.rank(metric="jig")`, `full` = `rk.rank(metric = metric_effective if metric_effective != "jig" else "solve")`(같은 noise·tol·lin_form·lin_valid). 순위·score·개선율·최악 ESL·pareto·ESL별 비가 **그 보기 지표로 일관**. select 경고 행 `warn`·형상 경고는 주 순위와 같은 규칙으로(공용 `_annotate`).
- 행 정리(섞임 금지):
  - `jig` 보기: 행에서 `C, C_solve, C_jig, score_solve, score_jig, score_lin, imbalance_max, rho_min, rho_max, umax_def, basis, sm_warn` 제거. `umax`·`umax_all` = 그 안 지그 재풀이 umax(mm, 최악 ESL·전 ESL 최대 — per_esl `umax_jig`), `epsmax`·`epsmax_all` = null(지그 재풀이는 변형률을 내지 않음), `umax_jig`(비)는 유지. per_esl 항목 = `{entry_id, C, ratio, umax(=umax_jig), epsmax: null}`. 베이스라인 같은 규칙.
  - `full` 보기: 행에서 `C, C_jig, score_jig, umax_jig` 제거(나머지 = 기존 행 그대로).
- 보기 필드: `{metric, C_ref, baseline, n_ok, n_skipped, n_failed, ranking, per_esl_inline, sensitivity, sensitivity_reason, best_clean?}`. `per_esl_inline` = 기존 규칙(행 수 × ESL 수 ≤ `rank.per_esl_inline_max`), 아니면 행의 per_esl 을 빼고 사이드카에 `per_esl{id: [...]}` → `GET …/results/per-esl?view=jig|full`.
- 민감도: 보기마다 `rk.sensitivity`(표본 score = 그 보기 행 score, 베이스라인 1, 순위 밖 안 제외 — 기존 bd_post 와 같은 식, 공용 `_sens`).
- ranking.csv·result.json·per_esl.json·report.html 은 **바꾸지 않는다**(CSV 열 추가도 하지 않음).

## 3. 3D 다시 만들기 (D-0.23.3-3)

- API: `POST /doe/studies/{sid}/view3d/regenerate`(body 없음) → 202 `DoeStudyOut`(작업 포함). 권한 = 실행 권한(power 이상) ∧ (프로젝트 admin ∨ 스터디 작성자) 아니면 403. 조건: 스터디 DONE ∧ 진행 중 작업 없음(409 JOB_ACTIVE) ∧ 지그 블록 status ok/poor ∧ 성공한 DOE_RUN 작업 있음(아니면 409 `VIEW3D_REGEN_UNAVAILABLE`).
- 작업: 기존 큐 · 기존 유형 `DOE_RUN`, params = 마지막 성공 DOE_RUN params 사본 + `kind: "VIEW3D"` + `doe.post_mode: "view3d"`, `resume_from_step = BD_POST 번호(3)` → BD_BASELINE·BD_DESIGNS SKIPPED, BD_POST = 코어 `bd_post` 가 `post_mode == "view3d"` 면 `_post_view3d` 만, BD_REGISTER = 워커가 `kind == "VIEW3D"` 면 `register_doe_view3d`(스터디 존재 확인만, **DB 변경 없음** — phase DONE 유지). 스터디 phase 는 바꾸지 않는다(결과 계속 보임).
- `_post_view3d(c)`: `post/result.json` 필요(없으면 `RESULT_NOT_READY`). 결과 목록 `_collect`(읽기만), 표시 안 = result.json `view3d` 목록. result.json 에 `view3d_jig` 가 없으면(v0.23.1 실행) `_jig_view3d` 로 지그 응답 3D 생성 → 사이드카에. 그다음 §1·§2 (`_jig_extras`). **쓰는 곳 = `post/view3d/<새 폴더>`·`post/jig_view.json` 만**(fresh_dir 백업은 `_backup/`). ranking.csv·result.json·per_esl.json·designs.json·report.html·best/·안 result.json 은 바이트 불변(V-0233-4).
- 응답 `DoeResultOut.view3d_regen: {available: bool, allowed: bool, reason: str|null}` — available = 지그 블록 status ok/poor; allowed = 위 권한·작업 조건; reason = 막힌 이유 문구. 화면 버튼은 available 일 때만, allowed 아니면 비활성 + title.

## 4. 사이드카 `post/jig_view.json` (`esl/doe_jig_view/1`)
`{schema, source: "bd_post"|"view3d_regen", view3d_jig?, view3d_jig_esl?, view3d_jig_ref?, jig_diag?, rank_views?: {jig, full}, per_esl?: {jig?: {id: [...]}, full?: {...}}, warnings: [str]}`
- BD_POST 는 `view3d_jig*` 를 지금처럼 result.json 에 쓰고(불변) 사이드카에는 넣지 않음. 다시 만들기는 result.json 에 없을 때만 사이드카에.
- `results()` 병합: `view3d_jig*` = result.json 우선, 없으면 사이드카. `jig_diag`·`rank_views` = 사이드카. 사이드카 없음 = null(옛 결과 응답 키 그대로 + 새 키 null).
- 사이드카 실패(예외)는 경고 `VIEW3D_FAILED: jigdiag <code>` 를 사이드카 warnings 에(BD_POST 결과·순위 무영향).

## 5. API · 고정 필드명 (schemas.py ↔ types.ts)

| 스키마 | 필드 |
|---|---|
| `DoeResultOut` (+) | `jig_diag: DoeJigDiagOut \| None`, `rank_views: DoeRankViewsOut \| None`, `view3d_regen: DoeView3dRegenOut \| None` |
| `DoeJigDiagOut` | `n_jig: int`, `tie_spread: float \| None`, `n_contact: int`, `n_patch: int`, `regions_from: str \| None`, `regions: list[DoeJigDiagRegionOut]`, `entries: list[DoeJigDiagEntryOut]` |
| `DoeJigDiagRegionOut` | `id: int`, `kind: Literal["contact","patch"]`, `part: int \| None`, `n_nodes: int`, `area_mm2: float`, `center: list[float]` |
| `DoeJigDiagEntryOut` | `entry_id, label: str`, `kk: int`, `dirs: dict[str,str]`(tgt·fit·err), `mac, umax_err: float`, `mac_nomodes, umax_err_nomodes: float \| None`, `work_eff, tie_rel, rot_deg, umax_tgt, umax_fit, err_max, tgt_out_frac: float`, `contrib: dict[str, float]`, `forces: list[DoeJigDiagForceOut]`, `F_region_sum: list[float]`, `body: list[float] \| None`, `modes: list[dict]` |
| `DoeJigDiagForceOut` | `region: int`, `kind: str`, `F: list[float]`, `F_mag, F_n, F_t1, F_t2: float`, `active: bool` |
| `DoeRankViewsOut` | `jig: DoeRankViewOut \| None`, `full: DoeRankViewOut \| None` |
| `DoeRankViewOut` | `metric: str`, `C_ref: float`, `baseline: dict`, `n_ok: int`, `n_skipped: dict[str,int]`, `n_failed: dict[str,int]`, `ranking: list[dict]`, `per_esl_inline: bool`, `sensitivity: dict \| None`, `sensitivity_reason: str \| None`, `best_clean: str \| None` |
| `DoeView3dRegenOut` | `available: bool`, `allowed: bool`, `reason: str \| None` |
| 쿼리 | `GET …/results/per-esl?design=…&view=jig\|full`(없으면 기존) |
| 새 경로 | `POST /doe/studies/{sid}/view3d/regenerate` → 202 `DoeStudyOut` |

## 6. 설정 (DEFAULTS `view3d` · `BeadDoeView3dCfg` · yaml 2 — 같은 이름)
| 키 | 기본 | 뜻 |
|---|---|---|
| `bead_doe.view3d.jig_diag` | `true` | 지그 계산된 스터디의 BD_POST·다시 만들기에서 지그 진단 3D(엔트리별 목표·맞춤·오차)와 하중 정의 탭 자료(rank_views)를 만듦 |

## 7. 화면 (`DoeStudy.tsx`, D-0.23.3-4·5)

### 7.1 하중 정의 탭 (사용자 결정 2026-11-18 15:47 — v0.23.1 "탭 도입 안 함" 을 이 탭 하나에 한해 개정)
- 결과 카드 **머리 오른쪽**(받기 묶음 왼쪽, 같은 줄 — 높이 불변)에 `.seg` 1개 `data-testid="doe-load-tab"`: [지그 ESL | 전 노드 ESL]. 버튼 `data-tab="jig"|"full"`.
- 기본 탭 = `metric_effective == "jig"` 이면 jig, 아니면 full. 지그 탭 가능 = `rank_views.jig` 있음 ∨ (rank_views 없음 ∧ metric_effective jig — 옛 사이드카 없는 지그 스터디는 주 결과 그대로). 전 노드 탭 가능 = `rank_views.full` ∨ metric_effective ≠ jig. 불가 탭 = 비활성 + title(지그: 기존 칩 문구 — 미계산·fallback·unsupported, 전 노드: "3D 다시 만들기로 전 노드 순위를 만들 수 있습니다").
- 탭 투영 `tabResult(result, tab)`(순수 함수): rank_views[tab] 의 ranking·baseline·C_ref·n_*·per_esl_inline·sensitivity(_reason)·summary.best_clean 으로 바꾸고 `metric_effective`·`rank.metric_effective` = 그 보기 metric, 지그 탭은 jig 블록 유지, 전 노드 탭은 `jig = null`(지그 값·칩 숨김). 순위표·ESL별 표·민감도·3D·상태 띠는 투영 결과만 본다 → 다른 탭 값이 DOM 에 없음.
- 상태 띠: 지그 탭 = 지그 칩 + 지그 경고(코드 `JIG_*`) + 공통 경고; 전 노드 탭 = 지그 미계산 칩(지그 탭 불가일 때만 — v0.23.2 칩 유지)·하중 전달·기준 메시 품질·경고 없는 최상위 칩 + 전 노드 경고(`SM_*`·`LT_*`·`MESH_QUALITY_*`) + 공통 경고. 공통 = 그 밖 코드.
- 순위표: 지그 탭 umax 열 = 지그 umax(mm, 열 title "지그 재풀이 최대 변위(최악 ESL)"), εmax = "–". 보조 열 토글은 그 탭 값만(지그 탭 = umax(지그) 비, 전 노드 탭 = 기존 lin/solve 보조 열).
- ESL별 개선율 표: 투영 결과의 per_esl(지그 탭 = C_jig 비), 인라인이 아니면 `?view=` 로 읽음.
- 받기·재낙하·검증 낙하(선택 안 작업) = 탭 공통. 선택 안(pick)도 탭 공통.

### 7.2 3D (오른쪽 열 "3D 비교" 자리 — 새 카드 없음)
- 전 노드 탭: 기존 전 노드 ESL 컨투어(3-2-1)만. v0.23.2 토글 [지그 하중 | 전 노드 ESL] **제거**.
- 지그 탭: 머리 줄 세그먼트 `data-testid="v3d-jig-mode"` [설계 비교 | 지그 진단].
  - 설계 비교 = v0.23.2 지그 응답 쌍(view3d_jig_ref | view3d_jig). 없으면 Empty "지그 응답 3D 가 없습니다" + [3D 다시 만들기].
  - 지그 진단(`JigDiag`): 엔트리 선택 `<select className="select small">`(재낙하 엔트리 선택과 같은 방식, `data-testid="jig-diag-entry"`, 기본 = 선택 안의 지그 최악 엔트리 → 없으면 첫 엔트리) + 세그먼트 `data-testid="jig-diag-view"` [목표·맞춤 | 오차 | 영역].
    - 목표·맞춤: 왼쪽 `_tgt`(목표 u_tgt — 지그 노드 기준 강체 제거) | 오른쪽 `_fit`(맞춤 u_fit + 영역 합력 화살표). 같은 색 범위(두 u_max 중 큰 값)·같은 변형 배율·같은 변형 켜기(공유 상태).
    - 오차: 왼쪽 `_err`(|u_fit − u_tgt|, 색 범위 = 목표·맞춤과 같은 범위) | 오른쪽 `_fit`.
    - 영역: 왼쪽 = `_fit` 형상에 영역 색(접촉 = 진한 파랑 계열, 패치 = 옅은 파랑 계열, 영역 밖 = 회색) + tie 마커 + 영역 합력 화살표 | 오른쪽 `_fit`.
    - 한 줄 `data-testid="jig-diag-line"`: `{엔트리} · MAC {mac}(모드 제외 {mac_nm}) · umax 오차 {%} · work_eff {} · tie_rel {}` — 목표 미달(mac < th.mac_min 또는 오차 > th.umax_err_max)은 warn-text. title(툴팁) = rot_deg·영역 수(접촉/패치)·지그 노드 수·tie_spread·기여(영역/체적력/모드)·면외 에너지 비·영역별 합력.
    - 체적력·모드 계수 = 같은 줄 끝 작은 글씨 `data-testid="jig-diag-coef"`(`체적력 (Fx, Fy, Fz) N · 모드 a1… N`).
  - 화살표 = 기존 3D 화살표(`buildArrow` 군집형, 길이 ∝ |F|, 라벨 `R{id} 접촉|패치 {|F|} N`) — View3DCard 선택 속성 `arrowsOverride`. 영역 색 = 선택 속성 `fieldOverride`. 공유 배율 = 선택 속성 `deformSync`. 속성을 안 주면 기존 동작 그대로.
  - [3D 다시 만들기] `data-testid="v3d-regen"`: 지그 탭 3D 머리 줄 끝, `view3d_regen.available` 이고 (지그 진단 없음 ∨ 선택 안 지그 응답 없음 ∨ rank_views 없음)일 때만. allowed 아니면 비활성 + title reason. 누르면 POST → 작업 진행 띠(기존).
- 높이: 머리 줄 1줄·두 그림 높이 그대로(2560×1440 결과 단계 높이 불변 — v0.23.1 예산).

## 8. 시험 (V-0233-n)

| id | 내용 | 위치 |
|---|---|---|
| 1 | 순수: `kind_forces` 합 = `forces`(1e-12), `kind_response` u = Σ a_k U_k(basis_response U 로 맞춤 노드 1e-9 상대), `diag_report` contrib·tgt_out_frac(순수 면외 목표 = 1, 순수 면내 = 0) | `tests/doe/test_jig.py` |
| 2 | 코어 진단: 지그 ok 합성 스터디 BD_POST → `d000_jigdiag_e<kk>_{tgt,fit,err}` manifest·values(u_fit 저장값 ≈ Σ a_k U_k — 양자화 허용), regions.json 영역 vertices = reg_node, 화살표 합 F_region_sum = Σ 영역 합력 = 영역 열 하중 합(`kind_forces.region` 합, 1e-9), jig_diag 키, `view3d.jig_diag false` → 없음, 지그 없는 스냅샷 → 사이드카 없음 | `tests/doe/test_jig_stages.py` |
| 3 | rank_views: jig 보기 순위 = `rank(metric jig)`, full 보기 = `rank(metric solve)`, 섞임 키 없음(jig 행에 score_solve·imbalance 없음, full 행에 score_jig·umax_jig·C_jig 없음), 민감도 보기별 | 같은 파일 |
| 4 | 다시 만들기: BD_POST 후 `post_mode view3d` 실행 → ranking.csv·result.json·per_esl.json·designs.json·report.html·안 result.json 해시 불변, 사이드카·진단 폴더 생김; v0.23.1 형(result.json 에 view3d_jig 없음) → 사이드카에 view3d_jig* | 같은 파일 |
| 5 | API: 사이드카 병합(jig_diag·rank_views·view3d_jig 대체), per-esl `view`, regenerate 202(DOE_RUN resume 3·kind VIEW3D·phase DONE 유지)·403(작성자 아님·admin 아님)·409(지그 없음·작업 중), view3d_regen 필드, `regions.json` 제공 | `backend/tests/test_doe_jig_view_api.py` |
| 6 | 워커: kind VIEW3D BD_REGISTER = DB 무변경 성공 | `worker/tests/test_doe_view3d_regen.py` |
| 7 | 설정 거울 `view3d.jig_diag` | `backend/tests/test_doe_config.py` 또는 rank 시험 |
| 8 | 화면: 탭 기본 규칙(jig/solve), 지그 미계산 = 지그 탭 비활성 + 사유, 탭별 DOM 섞임 0(지그 탭에 재풀이 C·불평형 열·LT 칩 없음, 전 노드 탭에 지그 C·지그 칩·지그 진단 없음), 민감도 탭별, 3D 지그 탭 세그먼트·진단 라벨·세그먼트 3종, 다시 만들기 버튼 조건 | `frontend/src/__tests__/doe_v0233.test.tsx` |
| 9 | 회귀·스크린샷: pytest 4묶음, vitest·typecheck·build·check:api, openapi `--check`; Playwright 2560×1440 mock `/home/claude/shots/v0233_{diag_tgtfit,diag_err,diag_regions,tab_jig,tab_full}.png` | – |

## 9. 결정 (decisions.md)

| ID | 결정 |
|---|---|
| D-0.23.3-1 | 지그 진단 3D = BD_POST(·다시 만들기)에서 기준 d000 엔트리별 u_tgt·u_fit·오차를 jig.npz 재사용으로 다시 풀어 기존 view3d 형식 `d000_jigdiag_e<kk>_{tgt,fit,err}` + regions.json. 진단 보강(기저 종류별 기여·u_tgt 면외 에너지 비·err_max)은 계산 불변·보고만, 위치 = BD_POST 한 곳(jig.json 불변 — 옛 스터디도 같은 정보). 설정 `view3d.jig_diag` |
| D-0.23.3-2 | 하중 정의 탭 자료 rank_views{jig, full} = BD_POST 에서 두 지표로 각각 rank + 민감도, 섞이는 키 제거(지그 보기 umax = 지그 umax, εmax 없음). ranking.csv·result.json 불변(사이드카 `post/jig_view.json`) |
| D-0.23.3-3 | 3D 다시 만들기 = 새 작업 유형 없이 기존 DOE_RUN 큐 + resume_from_step(BD_POST) + params kind VIEW3D/post_mode view3d, 등록은 DB 무변경, phase DONE 유지, 권한 admin ∨ 작성자. 쓰기 = post/view3d 새 폴더·사이드카만(기존 결과 파일 바이트 불변). migration 없음 |
| D-0.23.3-4 | (사용자 2026-11-18 15:47) 결과 카드 하중 정의 탭 [지그 ESL | 전 노드 ESL] 1개 — v0.23.1 '탭 도입 안 함'을 이 탭에 한해 개정. 기본 = metric_effective, 탭마다 순위표·ESL별 표·3D·민감도·상태 띠 칩이 그 하중 정의 값만. 받기·재낙하·검증 낙하는 공통. v0.23.2 3D 토글 제거 |
| D-0.23.3-5 | 지그 탭 3D = [설계 비교(지그 응답) | 지그 진단], 진단 = 엔트리 선택 + [목표·맞춤 | 오차 | 영역], 같은 색 범위·같은 배율, 영역 합력 화살표(기존 화살표·크기 비례), 체적력·모드 계수는 한 줄 글씨 |
