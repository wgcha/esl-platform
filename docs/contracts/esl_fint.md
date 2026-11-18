# 계약: 내력 ESL — 낙하 해석 노드 내력(FINT)을 하중으로 · 평가 영역 umax · 소성 진단 (FINT, v0.24.0 보완)

- 상태: **확정**(2026-11-18, 사용자 결정 22:34 "내력 ESL 버전도 만들어 봐 — 내일 출근해서 한 번에 다 확인" + 지표 제안 수용 "주 지표 = 컴플라이언스, 보조 = 평가 영역 안 최대 변위"). 브랜치 `release/v0.24.0`(PR #83, 8ccb6d1d 위).
- 버전: **v0.24.0 유지**(같은 릴리스 보완). migration **없음** — 새 값은 Case 폴더 새 파일(`04_esl/fint.json`·`fint.npz`)·ESL 실행 `forces` JSON 새 키(`fint`·`plastic`)·스터디 폴더 새 파일(`prep/fint*`, `run/designs/<did>/fint.json`, `post/fint_view.json`, `post/view3d/*_fi*`)·결과 응답 새 필드·작업 params·새 스냅샷 `doe.rank` 키만. 새 작업 유형 없음.
- 관계: `esl_bforce.md`(경계력 ESL — 데이터 등급·조립·관성 이완·DOE 경로)·`esl_jig_view.md`(하중 출처 표 RANK_SOURCES ↔ LOAD_SOURCES)·`esl_stiffness_metric.md`(순위 지표)를 보완. 충돌하면 이 문서 범위에서 이 문서가 우선. `esl_bforce.md` §0 등급 표의 `fint` 행은 이 문서 §0 으로 **대체**(경계력 ESL 은 접촉력 전용).
- ID: 결정 `D-0.24.0-BF-12~`, 시험 `V-0240-F-n`, 후속 `R-FI-n`.

### 사용자 확정 (변경 금지)
1. (22:34) 내력 ESL 을 별도 하중 출처 `fint`(화면 이름 "내력 ESL")로 분리 — 탭 [지그 ESL | 전 노드 ESL | 경계력 ESL | 내력 ESL]. 경계력 ESL 은 접촉력 기반 전용(FINT 가 있어도 접촉력으로 계산 — 두 방식 나란히 비교).
2. 내력 ESL F = s·FINT(부호 auto = 일 양수), 힘 방향 Rᵀ 회전(파트 Kabsch), 지지 3-2-1. 자기평형이어야 하므로 관성 이완은 기본으로 하지 않음(설정), 잔차를 진단·허용치 초과 경고, 그때만 관성 이완 옵션. 질량 불필요.
3. 지표: 주 순위 = 컴플라이언스 비(엔트리 최악), 보조 = 평가 영역 안 최대 변위. 옛 스냅샷 동일.

## 0. 출처 정리 (D-0.24.0-BF-12)

| 출처 키 | 화면 | Case 산출 | 하중 | 등급 |
|---|---|---|---|---|
| `bforce` | 경계력 ESL | `04_esl/bforce.{json,npz}` | full: CONT + CONT2 − M·ACC · contact: CONT − M·ACC | `full` > `contact` > `none` — **FINT 는 등급에 쓰지 않음**(full 이면 FINT 검산 `fint_check_rel` 만, contact 이면 검산 없음) |
| `fint` | 내력 ESL | `04_esl/fint.{json,npz}` | F = s·FINT | `fint` \| `none`(FINT 없음 — 탭 비활성 사유 "내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가") |

- 데이터는 같은 추출물(`01_extract/bforce.npz` — `esl_bforce.md` §1·§2, TCL 변경 없음)에서 읽는다. CONT 만 있고 FINT 없음 = bforce contact · fint none, FINT 만 있음 = bforce none · fint fint, 둘 다 = 둘 다 계산.
- 옛 결과(v0.24.0 이전·사이드카 없음)는 바이트 동일. 같은 v0.24.0 안에서 `bforce.json` 의 등급 규칙만 바뀐다(FINT 있고 CONT2 없던 경우 fint → contact).

## 1. 내력 ESL 정의 (공용 순수 함수 `esl/mech/bforce.py:fint_build` — D-0.24.0-BF-13)

```
F_n = s · FINT_n (전역, t* 변형 형상)       s = 설정 bforce.signs.fint(auto: Σ s·(FINT Rᵀ)·u_rel ≥ 0 → 일 양수 부호, fint_sign_source "work_positive")
F_ref,n = Rᵀ F_n (기준 형상 — S4 Kabsch R, 파트 전 노드)
잔차(진단): 변형 형상 x_def = X0 + u_total 에서 force_rel = ‖ΣF‖/Σ‖F‖, moment_rel = ‖Σ(x−c)×F‖/(Σ‖F‖·L_bbox)   (eq_raw.def)
          기준 형상 같은 값(eq_raw.ref — 선형화로 생기는 모멘트 잔차 ~ u/L, 반력으로 흡수)
unbalanced = def.force_rel > fint.unbalanced_force_rel ∨ def.moment_rel > fint.unbalanced_moment_rel → 경고 FINT_UNBALANCED{force_rel, moment_rel, tol}
균형 = 설정 bforce.fint.balance: none(기본 — F_ref 그대로) | inertia_relief(unbalanced 일 때만 관성 이완 §esl_bforce 3.4, 질량 = h3d MASS > deck 근사)
지지 = 같은 3-2-1(S4 pick_321), 기준 재현(MAC·umax 오차·반력)은 경계력 ESL 과 같은 규칙·같은 설정(recon_mac_min·recon_umax_err_max·reaction_warn_rel)
```
- 근거: 부품 요소 내력은 요소마다 자기평형(병진 합 0, 노드 모멘트 포함 모멘트 합 0) → 노드 합도 0. 잔차가 크면 공유 노드 혼입(§2)·추출 누락 의심. 질량·가속도 불필요(관성 이완을 쓸 때만 질량).
- 반환 `{F_bal, F_raw, m, doc}` — doc 는 `esl/bforce/1` 과 같은 필드(grade "fint", formula "F = s·FINT", decomposed false, `kinds`, `signs{fint}`, `fint_sign_source`, `eq_raw{def, ref}`, `eq_bal`, `abar*`·`corr_rel`(이완 안 하면 0), `sum_abs*`, `max_f`, `limits`(회전 연결 노드가 있으면 `FINT_ROT_LINKS` — 문구 "회전 연결 노드(RBODY·스프링·빔) 노드 모멘트 미사용", 원본 `bforce.LIMIT_TEXT`), `warnings`) + **`source: "fint"`** + 블록 `fint{residual{force_rel, moment_rel}, tol{force_rel, moment_rel}, unbalanced, balance, balance_applied, shared_nodes, rot_nodes}`.

## 2. 공유 노드 · 회전 연결 노드 진단 (`esl/rad/shared.py:node_links` — D-0.24.0-BF-14)

- 원 Case deck(`ctx.rad` + include, 파서 `_Deck.scan` 재사용)에서 **대상 파트 노드 중 다른 부품 요소가 참조하는 노드**(= FINT 에 다른 부품 요소 힘이 섞이는 노드)를 찾는다. 대상 = /SHELL·/SH3N(대상 파트 제외)·쉘 아닌 요소 블록(BRICK·TETRA4·PENTA6·SPRING·BEAM·TRUSS·RIVET·QUAD·TRIA — 카드 첫 줄 노드 칸, BEAM 방향 노드 n3 제외; 여러 줄 카드 TETRA10·BRIC20 은 첫 줄 노드만).
- 회전 연결 노드(노드 모멘트가 크게 남을 수 있는 노드): SPRING·BEAM 요소 노드 + `/RBODY` 주 노드(node_ID) + 종속 노드(grnd_ID 가 `/GRNOD/NODE` 이면 그 목록, 그 밖 그룹 형식 = `unresolved` 수만).
- 반환 `{status: ok|failed, n_shared, by_part{pid: n}, by_kw{kw: n}, node_ids[:cap], bbox|null, n_rot, rot{spring, beam, rbody_main, rbody_secondary}, rot_node_ids[:cap], rbody_unresolved, reason?}` (cap = 50 — 위치 요약). TYPE2 tie 는 노드가 분리돼 해당 없음.
- 진단 필드 `fint.shared_nodes`·`fint.rot_nodes`, 경고 `FINT_SHARED_NODES{n}`(n > 0). 해당 노드 내력은 **그대로 쓴다**(표시만). deck 을 읽지 못하면 status failed(경고 없음 — 사유만).
- 설정 `bforce.fint.shared_nodes`(기본 true) — false 면 deck 을 읽지 않음(status skipped).

## 3. Case ESL 단계 (`stage_esl` — D-0.24.0-BF-12·13)
- `_bforce_esl`(경계력 — 접촉력 전용) 다음 `_fint_esl`. 추출물에 경계력 자료가 없으면(이전 TCL·bf_on 0) 둘 다 04_esl 에 쓰지 않음(산출물 집합 불변). 추출은 했는데 FINT 없음 = `fint.json {schema, source: fint, grade: none, code: FINT_NO_DATA, reason: "내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가", kinds}` 만. 예외 = 경고 `FINT_FAILED` + json `{grade, code, reason}`(ESL 단계 실패 아님).
- `04_esl/fint.npz`: `node_id`, `f`(풀이 하중, 기준계), `f_raw`(전역), `m`(이완 안 하면 0), `u_val`(재현 변위).
- 단계 요약(ESL 실행 `forces.fint`): bforce 요약과 같은 키 + `res_force_rel`·`res_moment_rel`(변형 형상)·`unbalanced`·`n_shared`·`n_rot`·`balance_applied`. 경고 문자열 `FINT_*:` 는 ESL 단계 경고로.

## 4. 소성 진단 (D-0.24.0-BF-17 — 계산 변경 없음)
- `01_extract/strain_frames.npz` 의 `epsp`(선택 프레임 t* = 최대 변형 시점, 요소별 소성 변형률 — 기존 덤프) → 면적 가중 소성 비율 `frac = Σ_{εᵖ > eps_min} A_e / Σ A_e`, 최대 `max = max εᵖ`, `n = #{εᵖ > eps_min}`, `eps_min` = 설정 `bforce.plastic_eps_min`(0.002). 없음(키 없음·`epsp_available` false) = `{status: "none"}`("없음").
- 공용 순수 함수 `bforce.plastic_diag(epsp, area, eps_min)`, 면적 = `esl/mech/mass.elem_area_normal`.
- 위치: 단계 요약 `forces.plastic`, `bforce.json`·`fint.json` 의 `plastic`(DOE 칩이 읽음 — 엔트리 `plastic_frac`·`plastic_max`). 누적 씬도 h3d 총 εᵖ 그대로(증분 아님).

## 5. DOE — 노드 힘 출처 표 (D-0.24.0-BF-15)

### 5.1 표 `stages.NODAL_SOURCES` (행 = 출처, 호출부는 열만 읽음 — 출처 이름 분기 없음)
| 열 | bforce | fint | 뜻 |
|---|---|---|---|
| `key` | bforce | fint | rank_views·응답 블록·추가 계산 경로 키 |
| `file` | bforce | fint | Case `04_esl/<file>.{json,npz}`, `prep/<file>.json`·`prep/<file>_loads.npz`, `run/designs/<did>/<file>.json`, `post/<file>_view.json` |
| `pe` | bf | fi | per_esl 키 `C_<pe>`·`umax_<pe>`·`epsmax_<pe>`·`umax_<pe>_ev`, rank metric `<pe>`, n_failed 키, 3D `<did>_<pe>`·`d000_<pe>_e<kk>`, 응답 `view3d_<pe>`·`view3d_<pe>_esl`·`view3d_<pe>_ref` |
| `cfg` | bforce | fint | DOE 설정 `bead_doe.<cfg>`·작업 params `doe.<cfg>_cfg` |
| `code` | BF | FINT | 코드 접두(`<code>_NOT_FOUND`·`_GRADE_EXCLUDED`·`_UNSUPPORTED`·`_TRANSFER_FAILED`·`_DESIGN_FAILED`·`_BASELINE_FAILED`) |
| `kind` | BFORCE | FINT | 추가 계산 작업 params.kind(등록 = DB 무변경) |
| `plan` | bf | bf | 계획 표 열(base = 같은 메시 비교만 — 두 출처 공통) |
| `name` | 경계력 ESL | 내력 ESL | 로그·사유 문구 |

- 기존 `_bf_*` 함수는 행 `ns` 를 인수로 받는 공용 함수(`_ns_find`·`_ns_prep`·`_ns_loads`·`_ns_design`·`_ns_apply`·`_ns_post`·`_ns_view3d`·`post_mode` 분기 = 표의 `key`). bforce 의 파일·키·스키마 이름은 그대로(바이트 동일 경로).
- 스키마: 두 출처 공통 `esl/doe_bforce_prep/1`·`esl/doe_bforce_design/1`·`esl/doe_bforce_view/1`(진단 스키마 1개). 문서에 `source`(출처 키) 추가.
- 블록(§esl_bforce 5.6)은 두 출처 같은 형식 `DoeBforceOut` + `source`, 엔트리 += `plastic_frac`·`plastic_max`·`n_shared`·`unbalanced`·`res_force_rel`·`res_moment_rel`(내력 — 경계력은 null).
- RANK_SOURCES 행 추가 `{key: fint, metric: fi, drop: VIEW_DROP_NODAL, drop_pe: (…, C_bf, umax_bf, epsmax_bf), umax_pe: umax_fi, eps_pe: epsmax_fi, need: C_fi, sidecar: fint, uev_pe: umax_fi_ev}` — 탭 독립(내력 보기에 C_bf·C_jig 없음, 다른 보기에 C_fi 없음).
- `rank.rank(metric="fi")`: `stiffness_metric.VIEW_METRICS = {bf: C_bf, fi: C_fi}` 표 1곳, 옛 스냅샷 허용·n_failed["fi"].

### 5.2 추가 계산 경로 일반화 (결정: 출처 인자)
- `POST /doe/studies/{sid}/sources/{src}`, src ∈ NODAL_SOURCES 키(bforce | fint), 그 밖 = 404 `SOURCE_NOT_FOUND`. 권한·조건·작업 형식은 `esl_bforce.md` §6 그대로(params kind = 행 `kind`, `doe.post_mode` = 행 `key`, `doe.<cfg>_cfg` = 지금 설정). 기존 `/sources/bforce` URL 은 같은 경로로 계속 동작.
- 응답 `DoeResultOut.<key>_add`(bforce_add·fint_add): available = 계획 열 bf base, allowed = 3D 다시 만들기와 같은 조건.

## 6. 순위 지표 — 주 = 컴플라이언스, 보조 = 평가 영역 umax (D-0.24.0-BF-16)

### 6.1 출처별 현황 (주 순위)
| 출처 | 주 순위 값 | 컴플라이언스 비(엔트리 최악)? | 조치 |
|---|---|---|---|
| 지그 ESL | C_jig = F·u(지그 고정·맞춤 하중) | 예 | 유지 |
| 전 노드 ESL | solve: C = F·u · lin: C_ritz/C_lin(1차 컴플라이언스 근사) | 예(lin 은 근사) | 유지 |
| 경계력 ESL | C_bf = F_bf·u(3-2-1) | 예 | 유지 |
| 내력 ESL | C_fi = F_fi·u(3-2-1) | 예 | 새 행(같은 구조) |

### 6.2 보조 — umax(평가 영역)
- 설정(DEFAULTS `rank`·`BeadDoeRankCfg`·yaml 2): `eval_region` = `part`(기본 — 대상 파트 전 노드) | `exclude_free_edges`(자유 경계 노드에서 거리 ≤ `eval_free_edge_mm`(10.0) 인 노드 제외) | `box`(`eval_boxes` = `[{lo: [x,y,z], hi: [x,y,z]}, …]` 합집합 안 노드만, 기준 좌표). 
- **새 스냅샷만**: `rank_snapshot` 이 `eval_region{mode, free_edge_mm, boxes}` 를 고정. 스냅샷에 키 없음 = 계산 안 함(옛 결과·CSV·result.json 바이트 동일).
- 공용 순수 함수 `esl/doe/eval_region.py:eval_mask(x0, conn, elem_type, mode, free_edge_mm, boxes) -> bool(N)`(독립 모듈 — stiffness_metric 은 import 제한 유지)(자유 경계 = 한 요소에만 속한 변). 같은 메시 계획 = 기준 메시 마스크를 노드 ID 로, 다른 메시 = 그 메시 좌표로 계산. 빈 마스크 = 전 노드 + 경고 `RANK_EVAL_EMPTY`.
- per_esl 키(출처별): 전 노드 `umax_ev`(`_solve6`), 지그 `umax_jig_ev`(`jig.respond` ev_mask), 경계력 `umax_bf_ev`·내력 `umax_fi_ev`(사이드카). 출처 표 열 `uev_pe`.
- 순위 행·기준 += `umax_ev`(최악 엔트리)·`umax_ev_all`(전 엔트리 최대), 행 per_esl += `umax_ev`. result.json 최상위 += `eval_region{mode, free_edge_mm, boxes, n_nodes, n_total}`. ranking.csv 열은 늘리지 않음.
- 화면: 순위표 열 "umax(평가 영역)"(값 있는 결과만), ⓘ 지표 정의에 "주 순위 = 컴플라이언스 비(엔트리 최악) · 보조 = 평가 영역 안 최대 변위 — 영역: …" 한 줄.

## 7. API · 고정 필드 (schemas.py ↔ types.ts)
| 스키마 | 필드 |
|---|---|
| `DoeResultOut` (+) | `fint: DoeBforceOut \| None`, `fint_add: DoeView3dRegenOut \| None`, `view3d_fi`·`view3d_fi_esl`·`view3d_fi_ref: dict[str,str] \| None`, `eval_region: dict \| None`, `rank_views.fint` |
| `DoeBforceOut` (+) | `source: str \| None` |
| `DoeBforceEntryOut` (+) | `plastic_frac, plastic_max, res_force_rel, res_moment_rel: float \| None`, `n_shared: int \| None`, `unbalanced: bool \| None` |
| 순위 행·기준(dict) | `umax_ev`, `umax_ev_all`(새 스냅샷만) |
| per-esl | `?view=fint` |
| 새 경로 | `POST /doe/studies/{sid}/sources/{src}`(bforce·fint) → 202 `DoeStudyOut` |
| ESL 실행 | `EslRunOut.forces.fint`·`forces.plastic`(JSON — DB 스키마 불변) |

## 8. 화면
- 탭 세그먼트 [지그 ESL | 전 노드 ESL | 경계력 ESL | 내력 ESL](버튼 1개 추가 — 높이 불변). `LOAD_SOURCES` 행 `fint`: label 내력 ESL, primaryFor [], warnPrefixes `FINT_`, hide = 다른 출처 블록·3D, chips `nodal`·`best_clean`, view3d `pair`(view3d_fi*), 열 `nodal{block, add, addLabel, gradeText, chipName}` — 칩·[계산] 버튼·비활성 사유는 이 열만 읽음(bforce 행도 같은 열로 바뀜 — 출처 이름 분기 없음).
- 내력 칩 `data-testid="nodal-chip-fint"`(경계력 = `bf-chip` 유지): `내력 ESL · 재현 MAC · umax 오차 · 잔차 ‖ΣF‖/Σ‖F‖ · 공유 노드 n · 소성 x%`, 경고색 = unbalanced ∨ 공유 노드 > 0 ∨ MAC < 기준. 두 칩 모두 소성 비율 표시.
- 비활성 사유: 블록 없음 ∧ add available = "내력 ESL 미계산 — …[내력 ESL 계산]", 블록 unavailable = 엔트리 사유(FINT_NOT_FOUND·FINT_NO_DATA 문구 = "내력 출력 없음 — 낙하 Engine 에 /H3D/NODA/FINT 추가").
- 순위표: 주 열 이름 = 보기 지표 표 `VIEW_METRIC_TEXT{bf: 경계력 C, fi: 내력 C}`, 열 "umax(평가 영역)".
- Case ESL 화면: `esl-bforce-line` 아래 `esl-fint-line`(내력 ESL: 등급 · Σ|F| · 잔차(힘·모멘트) · 공유 노드 · 재현 MAC · umax 오차 · 반력 · 경고) + `esl-plastic-line`(소성: 면적 x%(εᵖ > eps_min) · 최대 εᵖ | 없음).

## 9. 설정
| 위치 | 키(기본) |
|---|---|
| Case `BFORCE_DEFAULTS` + `config/esl.example.yaml` `bforce:` | `fint{enabled true, balance none, unbalanced_force_rel 1e-3, unbalanced_moment_rel 1e-3, shared_nodes true}`, `plastic_eps_min` 0.002 |
| DOE `DEFAULTS["fint"]`·`BeadDoeFintCfg`·yaml 2 `bead_doe.fint` | `enabled` true, `grades` [fint], `view3d` true |
| DOE `DEFAULTS["bforce"]` | `grades` 기본 [full, contact](fint 등급은 경계력에 없음) |
| DOE `DEFAULTS["rank"]`·`BeadDoeRankCfg`·yaml 2 | `eval_region` part, `eval_free_edge_mm` 10.0, `eval_boxes` [] |

## 10. 시험 (V-0240-F-n)
| id | 내용 | 위치 |
|---|---|---|
| a | 요소 내력 합성: 쉘 K u(3-2-1 해, 자기평형 하중)의 병진 성분 = FINT → ΣF ≈ 0(1e-9)·재현 MAC ≥ 0.9999·unbalanced false | `tests/mech/test_fint.py` |
| b | 공유 노드 합성: 다른 부품 요소가 노드를 공유(FINT = K_A u + K_B u 대상 노드 행) → 잔차 > 허용치 FINT_UNBALANCED, deck 합성(두 파트 + SPRING + RBODY/GRNOD) `node_links` 공유 노드 수·회전 노드·FINT_SHARED_NODES, balance inertia_relief = 이완 적용 | `tests/mech/test_fint.py`, `tests/rad/test_shared_nodes.py` |
| c | 부호 반전 FINT(−K u) → auto s = −1 로 복원(F 동일) | `tests/mech/test_fint.py` |
| d | 탭 독립: fint 보기 행에 C_bf·C_jig·umax_jig 없음, bforce·jig·full 보기에 C_fi 없음, 화면 탭 DOM 섞임 0 | `tests/doe/test_fint_doe.py`, `frontend/src/__tests__/doe_v0240_fint.test.tsx` |
| e | bforce 는 FINT 가 있어도 접촉력 기반(contact 등급, F = CONT − M·ACC), fint 는 F = s·FINT | `tests/mech/test_fint.py`, `tests/pipeline/test_bforce_stage.py` |
| f | eval_region 3모드(part = 전 노드, exclude_free_edges = 경계 d 안 제외, box = 상자 안만), umax_ev ≤ umax | `tests/doe/test_fint_doe.py` |
| g | 옛 결과 바이트 동일: 스냅샷에 eval_region 없음 = result.json·ranking.csv·per_esl.json 동일, 추가 계산(fint) 후 기존 결과 파일·bforce 사이드카 해시 불변 | `tests/doe/test_fint_doe.py` |
| h | 소성 진단 값(면적 비율·최대·없음) | `tests/mech/test_fint.py`, `tests/pipeline/test_bforce_stage.py` |
| i | API: fint 블록·rank_views.fint·view3d_fi 병합, per-esl view=fint, sources/fint 202·sources/xxx 404, 워커 kind FINT = DB 무변경, 설정 거울 | `backend/tests/test_doe_fint_api.py`, `worker/tests/test_doe_bforce_add.py` |
| j | 스크린샷 `/home/claude/shots/v0240_{tab_fint,tabs4}.png` | – |

## 11. 결정
| ID | 결정 |
|---|---|
| BF-12 | 내력 ESL = 별도 출처 fint, 경계력 ESL = 접촉력 전용(등급 full·contact·none — FINT 는 full 검산만) |
| BF-13 | F = s·FINT(auto 일 양수)·Rᵀ·3-2-1, 균형 기본 none, 변형 형상 잔차 진단·FINT_UNBALANCED(허용치 설정), 그때만 inertia_relief 옵션 |
| BF-14 | 공유 노드·회전 연결 노드 진단 `esl/rad/shared.py` — 내력은 그대로 쓰고 표시, FINT_SHARED_NODES |
| BF-15 | DOE 노드 힘 출처 표 NODAL_SOURCES(파일·키·코드 열) + RANK_SOURCES fint 행, 추가 계산 경로 `sources/{src}` 일반화 |
| BF-16 | 주 순위 = 컴플라이언스 비(전 출처 이미 해당 — 유지), 보조 umax(평가 영역) rank.eval_region 3모드, 새 스냅샷만 |
| BF-17 | 소성 진단(εᵖ 면적 비율·최대) Case 요약·출처 json·DOE 칩, 계산 변경 없음 |
| BF-18 | 화면 출처 표 열 `nodal`(칩·추가 계산·사유) — 경계력·내력 공용, 보기 지표 문구 표 VIEW_METRIC_TEXT |

## 12. 한계 (사용자 안내 — 결과 문구·문서)
- **노드 모멘트 미사용**: FINT 는 병진 힘만. 외부 모멘트가 없는 노드에서 노드 내부 모멘트 합 = −I·ω̇(회전 관성)으로 작다고 보고 버린다. RBODY 주·종속 노드, SPRING·BEAM 연결 노드는 회전 연결이 있어 모멘트가 크게 남을 수 있음 → 진단 `rot_nodes` 에 표시(값은 그대로 사용).
- 공유 노드의 FINT 는 다른 부품 요소 힘을 포함(분리 불가) → 잔차·FINT_SHARED_NODES 로 표시만.
- 기준 형상 모멘트 잔차(선형화, ~u/L)는 3-2-1 반력으로 흡수 — 재현 반력 비(BF_REACTION 과 같은 기준)로 보임.
- FINT 결과 유형 표시명은 현장 미확인(R-BF-4) — `bforce.result_names.fint` 로 대체 이름 추가.

## 13. 후속 (R-FI-n)
- R-FI-1 공유 노드 내력 분리(다른 부품 요소 힘을 요소 응력에서 다시 계산해 빼기).
- R-FI-2 노드 모멘트 출력(/H3D/NODA/… 회전 성분)이 있으면 회전 자유도 하중으로.
- R-FI-3 /GRNOD 그룹 형식(PART·BOX·GRNOD 조합) 해석.

## 부록 A. 구현 반영 (2026-11-18, 계약과 다른 점·보충)
- A-1 버튼 testid: 경계력 `v3d-bf-add`(유지)·내력 `v3d-fi-add` — 3D 머리에 보기가 없는 노드 힘 출처마다 버튼 1개(표 행 순회).
- A-2 내력 Case 경고 문자열 코드: `FINT_UNBALANCED`·`FINT_SHARED_NODES`·`FINT_NO_MASS`·`FINT_RECON_POOR`·`FINT_REACTION`·`FINT_FAILED`(재현 판정은 경계력과 같은 공용 `_nodal_recon`, 접두만 다름).
- A-3 사이드카 문서 키: `post/<file>_view.json` 에 `load_source`(출처 키) 추가(기존 `source` = bd_post|add 의미 유지), prep·design 문서에 `source`(출처 키).
- A-4 평가 영역 스냅샷 형식: `doe.rank.eval_region = {mode, free_edge_mm, boxes}`(코어는 문자열 + `eval_*` 평면 키도 허용).
- A-5 합성 검증 수치(V-0240-F): (a) 요소 내력(K u) 대회전 35° 얹은 FINT — 잔차 힘 3.4e-12·모멘트 6.5e-5(선형 u×F), 재현 MAC 1.000000·umax 오차 −6.5e-12. (b) 경계 공유 11노드 혼입 — 잔차 힘 0.289·모멘트 0.168(FINT_UNBALANCED), A 요소만 힘 1.4e-12(모멘트는 경계 굽힘 전달로 남음 — 한계 근거).
