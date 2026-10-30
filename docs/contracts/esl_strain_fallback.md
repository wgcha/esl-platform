# 계약: h3d 변형률 결과 대체 (strain fallback, v0.12.1)

- 상태: **확정** (2026-10-30, 대체 순서·공식·표시 사용자 합의). 구현 코드 없음. 이 문서가 구현·검증 원본이다.
- 기준: origin/main d0d4c57 (v0.12.0 머지). 최소 범위 — 실서버 ESL 추출 막힘 해소가 목적.
- 대체 범위: `esl_core.md` §7.2(TCL 3패스·max-hold 가정), `esl_p2_library.md` §7.1~7.3 의 "ε_rad = Max_Strain" 정의. 충돌 시 이 문서 우선.

## 0. 근거 (실서버 실패)

`H3D_EXTRACT_FAILED`, done.json `failed_step=check_results`, `code=H3D_MISSING_RESULT`:
`result type 'Max_Strain' not in subcase 1 (available: Displacement Acceleration {Contact Forces} Velocity Max_Stress Min_Stress Strain Stress {Erosion Status} {Mass Change})`.
덱에서 `/H3D/ELEM/TENS/STRAIN/TMAX`·`EPSP` 는 주석, `/H3D/SHELL/TENS/STRAIN`(LAYER=ALL, NPT=LOWER/UPPER)·`STRESS/TMAX` 만 출력.
현재 `esl_h3d_extract.tcl` `::esl::check_result` 는 `strain_type`(기본 Max_Strain)·`epsp_type`(Plastic Strain) 이 없으면 즉시 실패한다.

## 1. 대체 순서와 선택 규칙

| 순위 | source 키 | h3d 결과(이름 후보, 설정) | 성질 | 지표 ε_rad | 표시 |
|---|---|---|---|---|---|
| 1 | `max_strain` | `Max_Strain` | max-hold 텐서 | ε_eq(텐서) — 현행 그대로 | 없음 |
| 2 | `plastic_strain` | `Plastic Strain`, `Plastic_Strain` | max-hold 스칼라(단조) | epsp | "대체: 소성 변형률 기준" |
| 3 | `strain_tensor` | `Strain` | **순간값** 텐서(층별) | 프레임별 ε_eq → 층 최대 → 시간 누적 최대(=TMAX 재현) | "대체: Strain 텐서 기준" |
| 4 | `max_stress` | `Max_Stress` | max-hold 응력 텐서 | σ_vM(HV vonMises) — 순위·t* 용 | 경고 "응력 기준 대체, 판정 신뢰 낮음" |

- 설정 `extract.strain_sources` = 순서 목록(기본 `[max_strain, plastic_strain, strain_tensor, max_stress]`). 하드코딩 금지 — TCL 은 request 로 받은 순서만 본다. 목록에서 빼면 그 대체는 쓰지 않는다.
- 선택 = 목록 순서대로 **첫 번째로 결과 유형·필수 성분·층이 모두 있는 source** 하나. 여러 source 혼용 없음.
- 같은 규칙이 ESL 생성 추출(CASE_EXTRACT `H3D_EXTRACT` → `extract`) 과 검증 낙하 추출(VERIFY_POST `H3D_EXTRACT` → `VD_EXTRACT`) 양쪽에 적용된다(둘 다 `executor._run_h3d` 공용 — 설정은 job params.settings).
- 보조 소성(epsp 열): source 와 별개로 `plastic_strain` 이름 후보가 있으면 읽고, 없으면 **실패 대신** epsp=0 + 경고 `H3D_NO_EPSP` (현행 `epsp_type ""` 동작 재사용). source=2 이면 epsp 가 곧 지표.

## 2. 설정 키 (esl/config.py SCHEMA `extract`, 모두 OPTIONAL_KEYS — 없으면 기본값)

```yaml
extract:
  strain_sources: [max_strain, plastic_strain, strain_tensor, max_stress]   # 순서 = 우선순위, 원소 중복 금지, 비어 있으면 CONFIG_INVALID
  result_names:                     # h3d 결과 유형 이름 후보(정확 일치 → 대소문자·공백·밑줄 무시 일치 순)
    max_strain: [Max_Strain]
    plastic_strain: [Plastic Strain, Plastic_Strain]
    strain_tensor: [Strain]
    max_stress: [Max_Stress]
  tensor_comps: {xx: [XX], yy: [YY], zz: [ZZ], xy: [XY]}       # 성분 이름 후보
  vm_comps: [vonMises, von Mises]
  scalar_comps: [Scalar value, Scalar]
  tensor_layer_exclude: [Max, Min]  # strain_tensor 층 목록에서 뺄 HV 파생 층(물리 텐서 아님)
```

- 워커(`worker/esl_worker/h3d.py write_request`)가 request.txt 로 전달: `strain_sources`(공백 구분), `names_<source>`·`comp_xx`…`comp_xy`·`vm_comps`·`scalar_comps`·`layer_exclude`(후보는 `|` 구분 — 이름에 공백 있음). 기존 키 `strain_type`·`epsp_type` 이 request 에 명시되면 **source 1 강제(대체 없음)** — 하위 호환.

## 3. TCL 탐지 (`resources/tcl/esl_h3d_extract.tcl`)

- `check_results` 단계: `GetDataTypeList` 결과(available)를 Tcl 목록으로 받고(공백 포함 이름은 `{Contact Forces}` 형태로 이미 원소 분리됨), source 순서대로 이름 후보 매칭 → `GetDataComponentList` 로 성분 후보 매칭 → `GetLayerList` 로 층 결정.
  - 층: source 1·2·4 = 현행 `strain_layer`(Mid) 우선, 없으면 층 목록 첫 원소, 층 API 무응답이면 "". source 3 = 층 목록 전부 − `layer_exclude`(예: `Lower Upper`, LAYER=ALL 이면 `Layer 1..N` 포함). 층 목록이 비면 "" 하나.
  - 각 source 의 탈락 사유를 `tried` 에 남김(`{source, type|null, reason}`).
- 모드:
  - **maxhold**(source 1·2·4): 현행 3패스(A·B·C) 그대로. 필드 = source 의 결과 유형. source 2 는 vm_hv 자리에 epsp 스칼라, exx..exy=0. source 4 는 vm_hv=σ vonMises, exx..exy=응력 텐서 성분.
  - **dump**(source 3): 순간값이라 "최종 프레임=최대" 가정이 깨지므로 TCL 은 순위·D 선정을 하지 않는다. 전 프레임 × 대상 파트 전 요소 × 층 → `strain_raw.csv` `frame_index,elem_id,layer,vm_hv,exx,eyy,ezz,exy,epsp`(layer = 층 순번 0.., 이름은 done.json `strain_layers`), 전 프레임 × 노드 → `disp.csv`. `final.csv`·`history.csv`·`strain_frames.csv` 는 쓰지 않음. frames.csv·model.csv·elems.csv 현행. `prev_file`·`frame0_pass` 는 dump 모드에서 무시(코어가 처리, §6).
- done.json 추가: `strain_source`, `strain_source_type`(실제 이름), `strain_layers`(목록), `strain_mode`(`maxhold|dump`), `strain_tried`, `epsp_available`(bool). 기존 `strain_type`·`strain_layer` 는 실제 값으로 채움.
- 전부 없음 → `::esl::fail H3D_NO_STRAIN_SOURCE "no strain source in subcase N (tried: …; available: …)"`, failed_step=`check_results`. 워커 step 코드는 현행대로 `H3D_EXTRACT_FAILED`(done.json code 를 메시지에 포함). `esl/io/results_csv.py _DONE_CODES` 에 추가.

## 4. 등가 변형률 계산 (코어 numpy, `esl/io/results_csv.py`)

- dump 모드 입력 감지 = done.json `strain_mode == "dump"`. `strain_raw.csv` 를 청크로 읽어 (F,E,L,3) 텐서.
- 프레임별 ε_eq = `esl.mech.strain.eps_eq_max_layer(tensor_eps(eps, factor))` — 평면응력 vM `2/√3·√(εx²+εy²+εxεy+(γxy/2)²)`, γ/2 규약은 기존 `decide_shear`(vm_hv vs 공식, 층별 자료 전부 사용)로 정함.
- 시간 누적 최대: `M[f,e] = max_{g≤f} ε_eq[g,e]`, 텐서 열은 최대를 만든 (프레임, 층)의 텐서를 함께 유지 → `eps_eq(텐서열) == M` 이 성립해 기존 하류(`_metric_series`, 비교, 보고서)가 수정 없이 max-hold 자료로 본다. vm_hv 열 = M.
- 그 뒤 H·D·P 는 TCL 과 같은 규칙(`esl.mech.tstar.hot_set`·`candidate_frames`; `write_results_csv` 와 같은 코드)으로 코어가 정하고 기존 `final.npz`·`history.npz`·`strain_frames.npz`(prev_* 포함)·`disp.npz`(D 프레임만)·`frames.json` 을 같은 형식으로 쓴다.
- 출력 간격 한계: Radioss TMAX 는 매 사이클 갱신이지만 재현값은 h3d 출력 프레임에서만 샘플 → **ε 과소평가 가능, t* 는 출력 프레임으로 양자화**. frames.json `strain_fallback.dt_out`(프레임 간격 중앙값) 기록, 경고 `STRAIN_TMAX_SAMPLED` 1회.
- ESL 비교 층 일치: source 3 에서 h3d 층이 외피(Lower/Upper·Layer n)이면 ε_esl 도 `extract.layers` 대신 `[bottom, top]` 최대로 계산(기록 `strain_fallback.esl_layers`). Mid 단독이면 현행 `[mid]`.
- source 2·4: 텐서 열이 0(2) 또는 응력(4)이라 텐서 의존 계산은 건너뜀 — `decide_shear` 생략(factor=1, 기록), 지표 이력 `max_strain` = vm_hv 열(2: epsp, 4: σ_vM). 변형률 참고 지표(`hotspot1_strain_rel_err`·전 요소 ε 비교·`noise_hotspot_strain_rel`)는 source 2 = ε_eq(ESL) vs epsp 참고값으로 계산, source 4 = **skipped(None)** + 경고 `STRAIN_FROM_STRESS`. 판정 주지표는 변위(esl_disp_primary.md)라 판정 규칙은 불변.

## 5. 메타데이터 `strain_source`

- frames.json `strain_fallback: {source, type, mode, layers, tried, epsp_available, dt_out, esl_layers}`; `results.strain_source` 키도 추가.
- 전파(기존 JSON 에 키 추가만, DB 마이그레이션 없음): `esl_summary.json`·Case 결과 응답 → 라이브러리 항목 `quality.strain_source`(`esl/library/entry.py`) → 검증 비교 `compare.json` 양쪽 source(`orig_strain_source`, `vd_strain_source`). 두 값이 다르면 경고 `VD_STRAIN_SOURCE_MISMATCH`(오류 아님).
- 없는 옛 자료 = `max_strain` 으로 간주.

## 6. 누적 입력과의 관계 (esl_cumulative_input.md)

- maxhold 모드(1·2·4): 현행 그대로(`prev_file`·`+prev` 순위·F0 패스).
- dump 모드(3): 코어가 `+prev` 순위(`tstar.scan_reach_cum` 과 같은 규칙, prev = rad 상태 파일 소성 — `cumulative.write_prev_csv` 와 같은 값)와 frame0 값(dump 프레임 0)을 직접 만든다. Strain 텐서는 런별 순간값이므로 `h3d_eq_mode: auto` 판정은 누적 최대 계열에 그대로 적용(대개 incremental 로 판정됨).

## 7. API·스키마·화면

- API: 결과·라이브러리·검증 비교 응답에 선택 필드 `strain_source: "max_strain"|"plastic_strain"|"strain_tensor"|"max_stress"` (없으면 null = max_strain). openapi 에 추가만.
- 화면(필수만): Case 추출 결과·⑤ 검증·라이브러리 상세·검증 비교 표 머리에 배지 1개 — source 2 "대체: 소성 변형률 기준", 3 "대체: Strain 텐서 기준", 4 경고색 "응력 기준 대체, 판정 신뢰 낮음". source 1 은 표시 없음. `H3D_NO_STRAIN_SOURCE` 는 기존 추출 실패 메시지 표시에 사람말 1줄 추가("h3d 에 변형률·응력 결과가 없음 — 덱 /H3D 출력 확인").

## 8. 시험 (가짜 h3d 결과 목록별)

| ID | available(subcase 1) | 기대 |
|---|---|---|
| T1 | Max_Strain, Plastic Strain, … | source=max_strain, 출력 현행과 바이트 동일(회귀) |
| T2 | Plastic Strain, Strain, Max_Stress | plastic_strain, 배지 2 |
| T3 | 실서버 목록(§0) | strain_tensor, dump 모드, `H3D_NO_EPSP` 경고, layers=Lower Upper |
| T4 | Max_Stress, Displacement | max_stress, 변형률 참고 지표 None, `STRAIN_FROM_STRESS` |
| T5 | Displacement 만 | `H3D_NO_STRAIN_SOURCE`, failed_step=check_results, tried 4개 |
| T6 | 실서버 목록 + `strain_sources: [max_strain]` | `H3D_NO_STRAIN_SOURCE`(설정 순서 준수) |
| T7 | request 에 `strain_type Max_Strain` 명시 + 실서버 목록 | `H3D_MISSING_RESULT`(하위 호환 강제) |
| C1 | 합성 순간 Strain(진동, 마지막 프레임 < 최대) | 코어 M = 시간 최대, t* = 최대 첫 도달 프레임, eps_eq(텐서열)==M, 층 최대 |
| C2 | C1 + engineering 전단 | decide_shear → factor 0.5, 공식 일치 |
| C3 | dump + 누적 prev | +prev D 가 maxhold 경로 결과와 같은 규칙 |
| V1 | 원 Case=max_strain, 검증=strain_tensor | compare 완료 + `VD_STRAIN_SOURCE_MISMATCH` |

- TCL: `tests/io/fixtures/hwmock.tcl` 에 available·성분·층 목록 주입 + `tests/io/test_tcl_mock.py`. 코어: `tests/io/test_io_results.py`(dump 합성 생성기 추가), 워커: `worker/tests/test_h3d_extract.py`·`test_verify_post.py`(request 키·코드 전달), FE: `frontend/src/__tests__/ui.test.tsx` 배지.

## 9. 파일 소유권

| 담당 | 파일 |
|---|---|
| Impl-Core | `esl/config.py`, `config/esl.example.yaml`, `esl/io/results_csv.py`(dump 읽기·누적 최대·H/D·메타·`_DONE_CODES`, 합성 생성기), `esl/pipeline.py`(지표 이력·참고 지표 skip·비교 층), `esl/verify/compare.py`, `esl/library/entry.py`, `esl/report/case_report.py`(배지 문구), `tests/io/test_io_results.py`, `tests/pipeline/*` |
| Impl-Worker | `resources/tcl/esl_h3d_extract.tcl`, `tests/io/fixtures/hwmock.tcl`, `tests/io/test_tcl_mock.py`, `worker/esl_worker/h3d.py`, `worker/esl_worker/executor.py`, `worker/esl_worker/verify_post.py`, `worker/tests/*`, `backend/esl_platform/api/schemas.py`·관련 services(필드 통과), `docs/contracts/openapi_p1b.json` |
| Impl-FE | `frontend/src/lib/format.ts`(라벨), 결과·⑤·라이브러리·검증 비교 화면 배지, `frontend/src/__tests__/ui.test.tsx` |

## 10. 리스크·결정 (권장안 확정)

1. **dump 모드 비용**(확정: 전 프레임 원시 덤프, 계산은 코어만): 추출 시간·용량이 대략 프레임 수/|D∪P| 배(노드 변위 포함). TCL 에서 공식을 중복 구현하지 않기 위한 선택. 완화 = 덱에 `/H3D/SHELL/TENS/STRAIN/TMAX` 출력 권고 문구를 경고 `STRAIN_TMAX_SAMPLED` 에 포함.
2. **응력 대체 비교**(확정: 변형률 참고 지표 skip, 판정은 변위 주지표 그대로): σ→ε 탄성 역산은 소성 영역에서 무의미하므로 하지 않음.
3. **라이브러리 등록**(확정: source 3·4 도 등록 허용, `quality.strain_source` 저장·배지로만 구분): 차단하지 않음.
