# 계약: ⑤ 검증 — 변위 주지표 판정 (v0.5.7)

- 상태: **확정** (2026-10-28, 결정 2026-10-27~28 사용자 승인). 구현 코드 없음. 이 문서가 구현·검증의 원본이다.
- 대체 범위: `esl.md` §1.1 S5 판정·§3 `validations`·§9 ⑤·§10 V-VAL-1, `esl_core.md` §5 S5·§7.4 S5, `esl_p2_library.md` §7.2 판정 기준(`compare.max_err_pct_max`·`p90_err_max`)·§7.3 단면선 표기·§11 등록 규칙. 충돌 시 이 문서 우선. 지표 **계산**(전 요소 비교, hotspot, 잡음 섭동)은 그대로 두고 **판정에서의 역할**만 바꾼다.
- 버전: v0.5.7 (v0.5.6은 이슈 #24 수정이 사용).

## 0. 근거

- S4는 `F_eq = K·u_rel`, S5는 같은 K에 `F_eq` + 3-2-1 정정 구속으로 재해석 → `u_val ≈ u_rel`(수치 일관성 ~1e-6). 변위 비교는 계산·경계조건·h3d 정밀도의 일관성을 본다.
- ESL 정의가 "같은 변위장을 만드는 정적하중"이므로 **변위가 판정 주지표**다.
- 소성 힌지(국부 대회전·대변형)는 선형 소변형률로 원리적으로 맞출 수 없다. 실례: 278157 요소 중 605(0.22%)가 변형률 기준 초과 → 현재 "최대 요소 1개" 기준(FIELD_MAX_ERR)으로 FAIL. 이 요소들은 판정 대상이 아니라 **"선형 ESL을 믿으면 안 되는 위치"** 로 참고 지도에 표시한다.

## 1. 현황 (main d5db5ac, v0.5.5)

| 항목 | 위치 | 현재 동작 |
|---|---|---|
| 판정 계산 | `esl/pipeline.py` `stage_validate` | verdict = 아래 판정 지표 전부 pass → PASS, 아니면 FAIL. skipped(None) 지표는 제외 |
| 판정 지표 | 〃 `metrics` | `disp_rms_rel`(≤0.01), `hotspot1_strain_rel_err`(≤0.10), `reaction_rel`(≤1e-6), `noise_hotspot_strain_rel`(≤0.05), `field_max_err_pct`(≤10%), `field_p90_err_pct`(≤20%) |
| 정보 지표 | 〃 | `disp_max_rel`, `reaction_sum_rel`, `u_rel_linear_rigid_rel`, `noise_force_rel` (criterion 없음) |
| 변위 비교 | 〃 | `remove_linear_rigid`로 u_val·u_rel 각각 미소 강체 제거 → Δ = d_val − d_rel, 정규화 U = max\|u_rel\|. 전 노드(3-2-1 노드 포함). `compare.csv`(노드별)만 저장, 요약·분포 없음 |
| full_solve 생략 | 〃 `full_solve_decision` | `never` 또는 auto 메모리 부족 → disp·반력 skipped, **변형률만으로 PASS 가능** |
| 잡음 바닥 | `noise_floor`(S4에서 계산, `esl_summary.json noise`) | δ = 0.5·eps(precision)·max\|X0+u\|, 섭동 표본으로 `force_rel`·`hotspot_strain_rel`(변형률 기반)만. 변위 기반 지표 없음 |
| FAIL 코드 | `_FAIL_REASON` | DISP_RMS, HOTSPOT_STRAIN, REACTION, NOISE_FLOOR, FIELD_MAX_ERR, FIELD_P90_ERR |
| 전 요소 비교 | `_field_compare`, `esl/report/field.py summarize` | `compare_field.npz`, `field` 요약(mean·P50·P90·P95·max, ≤5/10/20% 비율, top, hist). P99·초과 요소 수·소성 영역 없음. epsp는 `strain_frames.npz`에 있으나 미사용 |
| 단면선 | `_field_compare` `sec_xi/sec_eta`, API `/section` | 요소 평균 면외 변위 w_rel·w_val. UI 축 "ξ/η (PCA 평면, mm)", 슬라이더 "배율", 변형률 겹쳐보기 아래 |
| 설정 | `config/esl.example.yaml` `validation`, `compare` | 위 기준값. `disp_max_rel`·변위 잡음 기준 키 없음 |
| DB | `tables.py validations`, migration 0001~0007 | `verdict CHECK IN ('PASS','FAIL')`, 컬럼 disp_rms_rel·reaction_rel·hotspots·excluded·fail_reasons·criteria·field. 최신 0007 |
| 등록(워커) | `worker/esl_worker/register.py register_validation` | verdict ∉ {PASS,FAIL} → OUTPUT_INVALID |
| API | `routers/results.py`, `schemas.py ValidationOut/FieldOut/SectionOut` | `/validations/{id}`, `/field?layer=rad\|esl\|err`, `/section?axis=xi\|eta` |
| 라이브러리 | `services/library.py` | PASS 아니면 `force_reason` 필수(422 VALIDATION_NOT_PASS). `quality.verdict` 저장, 목록·분석 필터 `verdict` |
| 화면 | `frontend/src/stages/Stage5.tsx`, `FieldOverlay`, `SectionChart`, `ErrHistogram`, `LibraryRegister` | 판정 카드(변위 RMS·반력·hotspot 1위 + 최대변형률 비교), 겹쳐보기, 단면선+오차분포, 상위 요소, hotspot·제외 표, 검증 이력 |
| 보고서 | `esl/report/case_report.py` | verdict 배지, 지표 표 |
| 이력 | `services/history.py` | summary `{verdict, disp_rms_rel}`, 비교 행 "판정" |

## 2. 범위 / 비범위

| 범위 | 비범위 |
|---|---|
| 판정 = 변위 4지표(§3.2), UNDETERMINED·LEGACY 상태 | 판정 기준값 사내 확정(임시값 유지) |
| 변형률 지표의 참고 전환 + 초과 요소 수·비율·P99·소성 영역 | 변형률 계산 방식·전 요소 비교 알고리즘 변경 |
| 변위 전 노드 분석(컨투어·히스토그램·상위 노드·단면선) | 추가 해석(잡음 바닥용 재해석, 비선형 해석) |
| migration 0008, API·스키마·라이브러리 규칙, ⑤ 화면·보고서 | 과거 검증 재계산·일괄 재판정(D5) |
| 설정 키 추가 | 3D 뷰, MCP(esl_mcp_ready) 구현 |

## 3. 지표 정의

### 3.1 공통 기호
- N = 대상 파트 노드 수(`model.npz` 순서), **노드 집합 = 전 노드**(3-2-1 지지 노드 포함, 제외 없음).
- `u_rel` (N,3): S4 입력(전 노드 Kabsch 강체 제거 변위). `u_val` (N,3): S5 `solve(F_eq, 3-2-1)` 병진 성분.
- `d_rel = remove_linear_rigid(X0, u_rel)`, `d_val = remove_linear_rigid(X0, u_val)` — **양쪽 독립** 최소제곱 미소 강체 제거(현행 그대로).
- Δ_i = d_val,i − d_rel,i, e_i = ‖Δ_i‖₂.
- 정규화 **U = max_i ‖u_rel,i‖₂** (강체 제거 전 u_rel, 현행 그대로). 모든 상대 변위 지표의 분모.
- **BC(3-2-1) 노드 처리**: 지지 dof에서 u_val = 0이고 u_rel ≠ 0일 수 있으나, 양쪽 모두 미소 강체 제거 후 비교하므로 같은 공간의 값이다 → 일반 노드와 똑같이 RMS·최대·분포에 포함. 별도로 `disp.support[]`에 노드별 e_i/U를 기록하고 상위 노드 표에서 `is_support` 표시.

### 3.2 판정 지표 (D1, 4개 — PASS/FAIL은 이것만)

| metric | 수식 | 기준 키 (기본) | FAIL 코드 |
|---|---|---|---|
| `disp_rms_rel` | sqrt( (1/N) Σ e_i² ) / U | `validation.disp_rms_rel_max` (0.01, 기존) | `DISP_RMS` |
| `disp_max_rel` | max_i e_i / U | `validation.disp_max_rel_max` (**0.05**, 신규·임시) | `DISP_MAX` |
| `reaction_rel` | Σ_s ‖R_s‖ / Σ_i ‖F_eq,i‖ (3-2-1 반력, 자기평형) | `validation.reaction_rel_max` (1e-6, 기존) | `REACTION` |
| `disp_noise_rel` | δ / U, δ = 0.5·eps(`extract.disp_precision`)·max_i ‖X0_i + u_total,i‖ | `validation.disp_noise_rel_max` (**1e-3**, 신규·임시) | `DISP_NOISE` |

- 판정은 `value ≤ criterion` 이면 pass. 값이 NaN·inf면 pass=false.
- `disp_noise_rel`: **추가 해석 없음**. δ는 S4 `esl_summary.json noise.delta`를 그대로 쓰고, 없으면(예전 S4) `model.npz x0` + t* 프레임 `disp.npz u`로 같은 식을 계산(`noise_source: "esl_summary" | "recomputed"` 기록). 의미: 저장 정밀도가 만드는 노드 변위 잡음(섭동 균일 ±δ의 노드 RMS = δ)이 변형 크기 대비 얼마인가. full_solve와 무관하게 항상 계산된다.
- 기존 S4 경고 `noise_force_rel_warn`(경고만)은 유지.

### 3.3 판정 상태

| 상태 | 조건 | `verdict`(DB) | `undetermined_reason` |
|---|---|---|---|
| PASS | §3.2 4지표 모두 pass | `PASS` | null |
| FAIL | 하나라도 pass=false | `FAIL` | null |
| UNDETERMINED (판정 불가) | full_solve 미수행(D4) → disp_rms_rel·disp_max_rel·reaction_rel 값 없음 | `UNDETERMINED` | `NO_FULL_SOLVE` |
| 〃 | U = 0 (변형 없음) | `UNDETERMINED` | `ZERO_DISP` |
| LEGACY (이전 판정 체계) | 0.5.7 이전에 만들어진 검증(DB `scheme IS NULL`) | 당시 값(PASS/FAIL) 그대로 | — |

- UNDETERMINED는 **변형률로 대신 판정하지 않는다**. `disp_noise_rel`이 기준을 넘더라도 UNDETERMINED가 우선(값과 pass는 기록). fail_reasons는 비움.
- LEGACY는 저장값이 아니라 표시 상태(API `status`). 재계산하지 않는다(D5).
- `status` = scheme이 null이면 `LEGACY`, 아니면 `verdict`.

### 3.4 참고 지표 (D2 — 판정 제외, "참고 초과" 배지)

| metric | 계산(현행 그대로) | 참고 기준 키 |
|---|---|---|
| `hotspot1_strain_rel_err` | hotspot 1위 \|ε_val−ε_rad\|/ε_rad | `validation.hotspot_strain_rel_err_max` (0.10) |
| `field_max_err_pct` | 최대변형률 요소 오차 % | `compare.max_err_pct_max` (10) |
| `field_p90_err_pct` | valid 요소 \|오차\| P90 % | `compare.p90_err_max` (20) |
| `noise_hotspot_strain_rel` | 섭동 hotspot ε 상대 변화 | `validation.noise_strain_rel_max` (0.05) |

추가 집계(`strain_ref`):
- `p99_err_pct` = valid 요소 abs_err_pct의 99 분위(`field.abs_err_pct.p99`도 추가).
- 초과 요소: `exceed_e = valid_e ∧ 100·|rel_err_e| > compare.max_err_pct_max`. `n_exceed`, `frac_exceed = n_exceed / n_elems`(전 요소 분모, 예 605/278157 = 0.22%), `frac_exceed_valid = n_exceed / n_valid`.
- 소성 영역: t* 프레임 `strain_frames.npz epsp`에서 `plastic_e = epsp_e > 0`(엄격 부등호, 설정 키 없음). `n_plastic`, `frac_plastic = n_plastic/n_elems`, `n_exceed_plastic = |exceed ∩ plastic|`. epsp가 없으면 `plastic: null`.
- `exceeded = 참고 기준 하나라도 초과` → UI "참고 초과" 배지. 경고 문구·ctx.warnings 추가 없음(D6).
- 참고 지표는 UNDETERMINED에서도 계산·표시한다(전체 해 없으면 현행처럼 u_rel + 응축 회전 막 변형률).

### 3.5 변위 전 노드 분석 (D3, full_solve 수행 시만)
- `r_i = e_i / U`. 요약 `disp`: `U`, `n_nodes`, `n_support`, `rms_rel`, `max_rel`, `max_node_id`, 분위 `p50·p90·p99·max`(r), `hist`, `top`, `support`, `plane`.
- 히스토그램: log10(r) 균등 bin `validation.disp_hist_bins`(20), 범위 [floor(log10 min r>0), ceil(log10 max r)], r=0 노드는 `n_zero`로 따로. 형식 `{edges_log10[], counts[], n, n_zero}`.
- 상위 노드 표: r 내림차순 `validation.disp_top_n`(20)행 `{node_id, r, e, u_rel_mag(‖d_rel‖), a, b, is_support}`.
- 2D 좌표: 노드를 `field.plane_coords`와 같은 PCA 평면(e1 = 최대 분산 = **판 길이 방향**, e2 = **판 폭 방향**)에 투영한 (a, b).
- 단면선: 기존 `sec_xi`·`sec_eta`(요소 평균 면외 변위) 그대로 — 화면 위치·표기만 변경(§8).

## 4. 산출물 (코어 `05_val/`)

- `validation.json` schema **`esl/validation/3`**: 기존 키 + `verdict`(PASS\|FAIL\|UNDETERMINED), `verdict_scheme: "disp_primary/1"`, `undetermined_reason`, `fail_reasons`(§3.2 코드만), `metrics[]` 각 행에 `role: "judge"|"reference"|"info"`(reference 행은 `pass: null`, `exceeded: bool`), `disp`(§3.5, 미수행 시 null), `strain_ref`(§3.4), `noise_source`. `criteria` 스냅샷에 신규 키 포함.
- `compare_disp.npz`(full_solve 수행 시만, allow_pickle=False): `node_id (N,) i8`, `ab (N,2) f8`, `d_rel (N,3) f8`, `d_val (N,3) f8`, `e (N,) f8`, `is_support (N,) bool`, `U () f8`, `plane_origin/e1/e2/n (3,)`. 기존 `compare.csv`는 유지.
- `compare_field.npz` 추가 키: `epsp (E,) f8`(없으면 NaN), `plastic (E,) bool`, `exceed (E,) bool`.
- `validation.csv`: 헤더 `metric,value,criterion,pass,role` (reference 행 pass 열 = 초과 여부 `exceeded`), 첫 행 `verdict`.
- 단계 반환 dict에 `disp_max_rel`, `disp_noise_rel`, `undetermined_reason`, `strain_ref`(n_exceed·frac·p99·n_plastic) 추가.

## 5. 설정 (`config/esl.example.yaml`, 기본값은 `esl/config.py` 한 곳)

| 키 | 기본 | 역할 |
|---|---|---|
| `validation.disp_rms_rel_max` | 0.01 | 판정 (기존) |
| `validation.disp_max_rel_max` | **0.05** | 판정 (신규, 임시) |
| `validation.reaction_rel_max` | 1.0e-6 | 판정 (기존) |
| `validation.disp_noise_rel_max` | **1.0e-3** | 판정 (신규, 임시) |
| `validation.disp_top_n` | 20 | 상위 노드 표 (신규) |
| `validation.disp_hist_bins` | 20 | 변위 히스토그램 (신규) |
| `validation.hotspot_strain_rel_err_max`, `validation.noise_strain_rel_max`, `compare.max_err_pct_max`, `compare.p90_err_max` | 0.10, 0.05, 10, 20 | **참고 기준**(주석 갱신, 판정 아님) |
| `validation.full_solve` | auto | 기존. 주석: "생략 시 판정 불가(UNDETERMINED)" |

- 기존 설정 파일에 신규 키가 없으면 기본값. 코드에 기준 숫자 리터럴 금지(V-CFG-2).

## 6. DB migration `0008_validation_disp_primary`

현재 HEAD 0007 → **0008**. (`esl_mcp_ready.md`가 예정한 0008은 미구현이므로 이 계약이 쓰고 MCP는 다음 번호 0009로 미룬다.)

- `validations` 컬럼 추가(전부 NULL 허용): `scheme VARCHAR`(새 행 `'disp_primary/1'`, 기존 행 NULL = LEGACY, 백필 없음), `disp_max_rel FLOAT`, `disp_noise_rel FLOAT`, `undetermined_reason VARCHAR`, `disp JSONB`(§3.5 요약), `strain_ref JSONB`(§3.4).
- CHECK 교체: `ck_validations_verdict` → `verdict IN ('PASS','FAIL','UNDETERMINED')`; 추가 `ck_validations_scheme`: `scheme IS NULL OR scheme IN ('disp_primary/1')`; `ck_validations_undetermined`: `verdict <> 'UNDETERMINED' OR (scheme IS NOT NULL AND undetermined_reason IS NOT NULL)`.
- 멱등: 0001이 `tables.metadata.create_all`을 하므로 `ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS` 후 생성.
- downgrade: `UNDETERMINED` 행이 있으면 오류로 중단(데이터 보존), 없으면 CHECK 복원·컬럼 삭제.
- `tables.py` 동기화. 라이브러리 `library_entries.quality` JSONB 키 추가만(스키마 변경 없음).

## 7. API·스키마

| 대상 | 변경 |
|---|---|
| `ValidationOut` | 추가 `scheme: str\|null`, `status: "PASS"\|"FAIL"\|"UNDETERMINED"\|"LEGACY"`, `disp_max_rel`, `disp_noise_rel: float\|null`, `undetermined_reason: str\|null`, `disp: dict\|null`, `strain_ref: dict\|null`. `verdict`에 `UNDETERMINED` 추가. 기존 키 유지 |
| 신규 `GET /validations/{id}/disp-field?layer=err\|rel\|val&max_points=` | `DispFieldOut {validation_id, layer, n_total, n_returned, decimated, cell, plane, color_range, U, points:[[node_id, a, b, value, is_support]]}`. err = e/U, rel = ‖d_rel‖, val = ‖d_val‖. 다운샘플 = 기존 2D 셀 격자(≤ `ui.max_preview_points`), 셀 대표 = **e 최대 노드**(최대 보존). `compare_disp.npz` 없으면(UNDETERMINED·LEGACY) 409 `PREREQUISITE_MISSING` `missing:["disp_compare"]`; 파일 소실은 기존 409 `VALIDATION_FILES_GONE` |
| `FieldOut.points` | 6번째 열 `flags`(int 비트: 1 = exceed, 2 = plastic) 추가. 예전 npz는 0 |
| `SectionOut` | 변경 없음(axis=xi: ξ=0.5 고정 → 판 폭 방향으로 그림, axis=eta: η=0.5 고정 → 판 길이 방향) |
| `EntryQuality` | 추가 `status`, `scheme`, `disp_max_rel`, `disp_noise_rel`, `strain_exceed_frac`, `undetermined_reason` |
| 목록·분석·비교 필터 `verdict` | 허용값 PASS\|FAIL\|UNDETERMINED\|LEGACY. LEGACY = `quality.scheme` 없음, 그 외 = `quality.status`(없으면 `quality.verdict`) 일치 |
| 이력(`services/history.py`) | summary `{status, verdict, disp_rms_rel, disp_max_rel}`, 비교 행 "판정" = status |
| 워커 `register_validation` | verdict ∈ {PASS,FAIL,UNDETERMINED}; `verdict_scheme` 있으면 `scheme`에 저장, 없으면 NULL. `disp_max_rel`·`disp_noise_rel`은 `metric_value`, `disp`·`strain_ref`·`undetermined_reason` 복사 |
| 오류 코드 | 신규 없음(VALIDATION_NOT_PASS 재사용) |

## 8. 라이브러리 등록 규칙

| status | 등록 |
|---|---|
| PASS | 허용, 사유 불필요 |
| FAIL | `force_reason` 필수(기존), 없으면 422 `VALIDATION_NOT_PASS` |
| UNDETERMINED | **`force_reason` 필수로 허용**(D6), 없으면 422 `VALIDATION_NOT_PASS`(`verdict: "UNDETERMINED"`). `quality.confirmed_fail`과 같은 형식 `quality.confirmed_undetermined{reason,by,at}` |
| LEGACY | 당시 verdict 기준 기존 규칙(PASS 사유 불필요, FAIL 사유 필수). `quality.scheme` 없음으로 저장되어 목록에 "이전 판정 체계" |

- 이미 등록된 항목은 바꾸지 않는다(목록에서 LEGACY 표시).

## 9. 화면 (⑤ 검증, 필수 UI만, 기준 2560×1440)

배치(위→아래, ≥2560px에서 `.wide2` 2열 규칙 유지):
1. **판정 카드**: 상태 배지 — PASS(ok) / FAIL(bad) / **판정 불가**(중립) / **이전 판정 체계**(중립, 옆에 작은 글씨 "당시 PASS|FAIL"). Stat 4개: 변위 RMS(상대)·변위 최대 오차(상대)·반력(상대)·변위 잡음 바닥 — 각 "기준 ≤ x", 초과 시 bad 톤. UNDETERMINED: 사유 한 줄 "전체 재해석 생략(full_solve=…) — 변위 비교가 없어 판정하지 않음". FAIL 사유 목록(DISP_RMS·DISP_MAX·REACTION·DISP_NOISE 라벨 추가, 예전 코드 라벨 유지). 보고서·라이브러리 등록 버튼(결과 카드 안 보조). 주 버튼 "검증 실행" 유지.
2. **변위 카드 "변위 비교 (전 노드)"** (full_solve 수행 시): 2D 노드 컨투어(레이어 오차 e/U · Radioss u_rel · ESL u_val, 지지 노드 표시), log 히스토그램, 상위 노드 표, **단면 차트(여기로 이동)**. UNDETERMINED·LEGACY: 카드 대신 한 줄 안내(LEGACY: "이전 판정 체계 결과 — 다시 검증하면 변위 분석이 나옵니다").
3. **변형률 카드 "변형률 (참고 — 판정 아님)"**: `strain_ref.exceeded`면 "참고 초과" 배지(문구 없음). Stat: 기준 초과 요소 `n_exceed / n_elems (frac %)`, P99, 최대변형률 오차, P90, hotspot 1위, 소성 영역 요소 수. 기존 겹쳐보기(FieldOverlay)에 표시 토글 2개 "기준 초과 요소"·"소성 영역(epsp>0)"(flags 사용), 오차 분포, 상위 요소, hotspot·제외 표. LEGACY는 기존 화면 그대로 이 카드 안에.
4. 검증 이력(status 표시).

단면 차트(D7): 토글 "길이 방향 중앙선"(axis=eta, 기본) / "폭 방향 중앙선"(axis=xi), x축 "판 길이 방향 (mm)" / "판 폭 방향 (mm)", 슬라이더 "변형 확대 배율", 선 "Radioss(u_rel)"·"ESL 재해석"·"초기". ξ·η·PCA 문구 제거.

높이 제한: 컨투어 캔버스 = 기존 FieldOverlay 규칙(clamp(240px, 36vh, 560px)), 히스토그램·단면 차트 ≤ 340px, 표는 `.table-wrap.scroll`(`--tbl-max`), 상위 노드 표 머리글 고정. 2560×1440에서 판정 카드 + 변위 컨투어 상단이 첫 화면(스크롤 없이)에 보일 것.

보고서(`case_report.py`): 상태 배지(4종), 판정 표 = §3.2 4지표, 변형률은 "참고" 표 + 초과 요소 수·비율·P99·소성 영역 수, 변위 히스토그램·상위 노드(full_solve 시).

## 10. 시험

| ID | 기준 | 방법 |
|---|---|---|
| V-DP-1 | 합성 Δ(알려진 e_i, 지지 노드 포함)에서 disp_rms_rel·disp_max_rel = 수식값(rel 1e-12), 분모 U = max‖u_rel‖ | 단위 |
| V-DP-2 | disp_noise_rel = noise.delta/U; noise 없는 esl_summary → 재계산값 동일, `noise_source` 기록, 추가 solve 호출 0회 | 단위 |
| V-DP-3 | 변형률 참고 기준 전부 초과 + 변위 4지표 pass → PASS, fail_reasons 비어 있음, `strain_ref.exceeded = true` | 단위 |
| V-DP-4 | 4지표 각각만 초과 → FAIL, 코드 DISP_RMS/DISP_MAX/REACTION/DISP_NOISE | 표 기반 |
| V-DP-5 | full_solve never → UNDETERMINED·NO_FULL_SOLVE, disp 지표 null, `disp` null, compare_disp.npz 없음, strain_ref 계산됨 | 단위 |
| V-DP-6 | u_rel = 0 → UNDETERMINED·ZERO_DISP | 단위 |
| V-DP-7 | fixture에서 n_exceed·frac_exceed(분모 n_elems)·frac_exceed_valid·p99·n_plastic·n_exceed_plastic 일치, epsp 없으면 plastic null | 단위 |
| V-DP-8 | compare_disp.npz 키·dtype·allow_pickle=False 로드, disp.hist(log bin·n_zero)·top(정렬·is_support) | 단위 |
| V-DP-9 | 0008: 0007 DB(기존 행 있음) upgrade → 기존 행 scheme NULL; create_all DB에서 멱등; UNDETERMINED+scheme NULL 거부; UNDETERMINED 행 있으면 downgrade 중단 | PG |
| V-DP-10 | 워커 등록: schema 3 → 신규 컬럼 저장, schema 2 json → scheme NULL(LEGACY) | PG |
| V-DP-11 | API: status(LEGACY/PASS/UNDETERMINED), `/disp-field` 3레이어·최대 보존 다운샘플·409 missing disp_compare, `/field` flags 열 | API |
| V-DP-12 | 라이브러리: UNDETERMINED 사유 없음 422, 사유 있음 201 + quality.status; 필터 LEGACY/UNDETERMINED | API |
| V-DP-13 | 프런트: 판정 Stat 4개, 배지 4종 문구, UNDETERMINED 사유, 단면 차트가 변위 카드 안 + 축 "판 길이 방향"/"판 폭 방향" + "변형 확대 배율", 변형률 카드 "참고 초과" 배지·초과 비율 경고 문구 없음, LibraryRegister UNDETERMINED 사유 필수 | 프런트 시험 |
| V-DP-14 | 보고서: 상태 배지·판정 4지표·참고 표 | 단위 |
| V-DP-15 | 설정: 신규 키 기본값, 예시 yaml 로드, V-CFG-2 정적 통과 | 단위·정적 |
| V-DP-E2E | (사용자) 실모델 278157 요소: PASS(disp ~1e-6), 변형률 참고 초과 605/278157 = 0.22% 표시, 2560×1440 첫 화면에 판정 카드 + 변위 컨투어 | 수동 증적 |

기존 시험 중 "변형률 FAIL → verdict FAIL"을 기대하는 것(V-VAL-1, P2 field 판정, T-NOISE-1 NOISE_FLOOR FAIL)은 이 계약 기준(참고 초과)으로 고친다.

## 11. 파일 소유 (병렬)

| 소유 | 파일 |
|---|---|
| **Impl-Backend** | `esl/pipeline.py`(stage_validate·noise 재계산), `esl/report/field.py`(p99·노드 평면 좌표·disp 요약), `esl/report/case_report.py`, `esl/export/csvout.py`(validation.csv), `esl/config.py`, `config/esl.example.yaml`, `migrations/versions/0008_validation_disp_primary.py`, `backend/esl_platform/core/db/tables.py`, `core/repositories/{cases,library,history}.py`, `api/schemas.py`, `api/routers/results.py`, `api/services/{results,library,history,comparisons}.py`, `worker/esl_worker/{register,core_adapter}.py`, `tests/**`, `backend/tests/test_disp_primary*.py`, `worker/tests/**`, `docs/contracts/openapi_p1b.json`(있으면 재생성), `VERSION`(0.5.7)·`CHANGELOG.md` |
| **Impl-Frontend** | `frontend/src/stages/Stage5.tsx`, `components/{FieldOverlay,SectionChart,ErrHistogram,LibraryRegister,PastBadge}.tsx`, 신규 `components/{DispOverlay,DispHistogram,DispTopTable}.tsx`, `pages/history/JobReview.tsx`, `pages/library/*`(status 배지·필터), `api/{types,endpoints}.ts`, `mock/**`, `__tests__/disp_primary.test.tsx`, `styles.css` |

- 접점은 이 문서 §4·§7의 JSON 형태뿐. 프런트는 mock으로 먼저 구현한다. `esl/report/field.py`의 축 명칭 상수는 백엔드 소유(보고서용), 화면 문구는 프런트 소유.

## 12. 결정

- DP-1 판정 = 변위 4지표(RMS, 최대 5%, 반력, 잡음 바닥 1e-3), 변형률은 판정 제외 참고(D1·D2).
- DP-2 노드 집합 = 전 노드(3-2-1 포함), 분모 U = max‖u_rel‖, 양쪽 독립 미소 강체 제거(현행 유지).
- DP-3 변위 잡음 바닥 = δ/U(저장값, 추가 해석 없음).
- DP-4 full_solve 미수행 → UNDETERMINED, 변형률 대체 판정 없음(D4).
- DP-5 과거 검증은 재계산 없이 LEGACY(scheme NULL)(D5).
- DP-6 UNDETERMINED 라이브러리 등록은 사유 필수 허용, 초과 비율 경고 문구 없음(D6). LEGACY 등록은 당시 verdict의 기존 규칙.
- DP-7 초과 요소 = valid ∧ |오차| > `compare.max_err_pct_max`, 비율 분모 = 전 요소(보조로 valid 분모 병기).
- DP-8 migration 0008을 이 계약이 사용, MCP는 0009.
- DP-9 단면 축 = 판 길이 방향(e1)/판 폭 방향(e2), "변형 확대 배율", 변위 카드로 이동(D7).
- DP-10 컨투어 레전드 범위 편집 + 견고한 자동 범위(`color_range_robust`, P99) — §14(사용자 요구 2026-10-28 08:05).

## 13. 리스크

| ID | 내용 | 대응 |
|---|---|---|
| R1 | Δ ~1e-6이라 변위 컨투어는 물리 차이가 아니라 수치 오차 지도 | 카드 제목·보고서에 "수치 일관성" 의미 한 줄, log 히스토그램 |
| R2 | 변위 판정만으로는 소성 힌지 부위의 응력·변형률 신뢰도를 보장하지 않음 | 참고 지도(초과·소성 영역) 상시 표시, 라이브러리에 strain_exceed_frac 저장 |
| R3 | 메모리 부족 auto 생략이 잦으면 UNDETERMINED 증가 | 사유에 full_solve 모드·메모리 추정 표시, 운영 서버(512 GB)는 대부분 수행 |
| R4 | 605/278157의 원 집계 정의(분모·valid 조건)가 DP-7과 다를 수 있음 | E2E에서 실모델 값으로 확인, 다르면 정의만 조정 |
| R5 | epsp>0 엄격 기준이 미세 소성까지 넓게 표시 | 표시 전용, 필요 시 후속 설정 키 |
| R6 | LEGACY·신규 항목이 라이브러리 분석에 섞임 | 필터 LEGACY, 목록 배지 |
| R7 | 0008 번호를 MCP 계약이 예정 | decisions 메모, MCP 0009 |

## 14. DP-10 컨투어 레전드 범위 편집 (2026-10-28 추가)

사용자 요구: "겹쳐보기에서 '오차'를 누르면 컨투어 레전드가 -500~500이다. 편집 가능하게."

### 14.1 원인 (코드 확인 결과)
- 화면 `FieldOverlay.errRangeOf`는 서버 `/field?layer=err`의 `color_range`에서 R = max(|min|, |max|)를 받아 ±R로 칠한다.
- 서버 `services/results.field`의 err `color_range`는 이미 max가 아니라 `core_adapter.field_err_range` = `esl.report.field.histogram`의 `range_pct` = **`_nice_ceil(P99 |오차|)`**(1·2·2.5·5×10^k 계단, 최소 1%)이다.
- 따라서 ±500%는 (a) valid 요소 중 큰 오차 요소(소성 힌지 주변)가 1%를 넘어 P99 자체가 수백 %이고, (b) 계단 올림으로 더 커진 결과다(예: P99 = 260% → 500%). 예 605개 초과 요소는 전 요소의 0.22%지만 valid 요소(상승 중 ∧ ε ≥ min_rel·max) 대비 비율은 더 크다.
- 결론: 자동 범위를 조금 고치는 것만으로는 부족하다 → **레전드 범위를 사용자가 편집**하는 것이 주 대책이고, 자동 범위는 계단 올림을 없애 덜 부풀린다.

### 14.2 자동 범위 `color_range_robust` (서버, 기존 `color_range` 유지)
- 공통 올림: `ceil2(x)` = 유효숫자 2자리 올림(예 263.4 → 270, 0.01234 → 0.013), x ≤ 0 이나 비유한이면 null.
- `/validations/{id}/field` 응답 추가 키 `color_range_robust: {min, max, basis: "p99", raw}` (`raw` = 올림 전 분위값):
  - `layer=err`: R = ceil2(P99 |100·rel_err|, valid 요소), `{min: −R, max: +R}`. valid 없으면 null 값.
  - `layer=rad|esl`: rad·esl 유한값 합집합 기준 `{min: 그 최소, max: ceil2(P99)}` (두 레이어 같은 값 — 공통 범위 유지).
- `/validations/{id}/disp-field` 응답 추가 키 `color_range_robust`(같은 형식): `layer=err` `{min: 0, max: ceil2(P99 e/U)}`, `layer=rel|val` rel·val 합집합 `{min: 0, max: ceil2(P99 ‖d‖)}`. 기존 `color_range`(min/max)도 함께 준다.
- 분위는 다운샘플 전 전체 집합으로 계산. `histogram.range_pct`(보고서·오차 분포 차트)는 바꾸지 않는다.
- 계산 함수: `esl.report.field.robust_range(values, kind: "sym"|"zero"|"minmax", pct=99) -> {min,max,basis,raw}` (Impl-Backend). 분위값 99는 함수 기본 인자이며 판정 기준이 아니므로 설정 키를 두지 않는다.

### 14.3 화면 (Impl-Frontend, 겹쳐보기·변위 컨투어 공통)
- 공용 컴포넌트 `components/ColorLegend.tsx`: 색 띠 양 끝의 숫자를 **입력 칸**(type=number, 레전드에 붙임)으로 바꾼다. 새 버튼은 **"자동" 하나**(수동 값이 있을 때만 활성).
  - 대칭 레이어(변형률 오차 %): 입력 1칸 `±R`(R > 0).
  - 0 기준 레이어(변위 오차 e/U, ‖d_rel‖, ‖d_val‖): 입력 1칸 최대(> 0), 최소 0 고정.
  - 변형률 rad/esl(공통 범위): 최소·최대 2칸(min < max).
  - 잘못된 값(비유한·순서 역전·≤0)은 입력 칸 오류 표시 후 직전 유효 범위 유지.
- 기본 = 자동 = `color_range_robust`(없으면 기존 `color_range`, 예전 서버 대비).
- 범위 밖 값: 끝색으로 칠함(clamp). 범위 밖 점이 있으면 레전드 해당 끝에 **▲**(최대 초과)·**▼**(최소 미만)와 개수 툴팁("범위 밖 n개").
- 기억: `localStorage` 키 `esl.legend.v1:<validation_id>:<view>:<layer>`(view = `field`|`disp`, 변형률 rad/esl은 layer `eps` 하나), 값 JSON `{min,max}`. 읽기·쓰기·삭제 모두 try/catch, 실패하면 메모리 상태만으로 동작(오류 표시 없음). "자동"은 키 삭제 + 자동 범위 복귀.
- 높이·배치는 §9 규칙 그대로(레전드 한 줄, 줄바꿈 시에도 컨투어 높이 규칙 불변).

### 14.4 API 변경 요약 추가
| 대상 | 변경 |
|---|---|
| `FieldOut` | `color_range_robust: {min, max, basis, raw} \| null` 추가 |
| `DispFieldOut` | 같은 키 추가 |

### 14.5 시험
| ID | 기준 | 방법 |
|---|---|---|
| V-DP-16 | `robust_range`: sym/zero/minmax 결과 = 수식(ceil2·P99), 이상치 1% 미만 섞인 합성 오차에서 R ≪ max, 빈 입력·비유한 → null | 단위 |
| V-DP-17 | `/field` err·rad·esl, `/disp-field` err·rel·val 응답에 `color_range_robust`, 다운샘플과 무관(전체 집합) | API |
| V-DP-18 | ColorLegend: 입력 반영(캔버스 범위 변경), 잘못된 값 무시, "자동" → 서버 robust 범위 복귀·키 삭제 | 프런트 |
| V-DP-19 | 범위 밖 점 있을 때 ▲/▼ 표시와 개수, 없으면 미표시 | 프런트 |
| V-DP-20 | localStorage 저장·복원(검증 id·view·layer별 분리), `getItem`/`setItem` throw 시에도 입력·자동 동작 | 프런트 |

### 14.6 파일 소유
- Impl-Backend: `esl/report/field.py`(`robust_range`, `ceil2`), `api/services/results.py`(`field`·`disp_field` 응답), `api/schemas.py`(`FieldOut`·`DispFieldOut`), `worker/esl_worker/core_adapter.py`(래퍼), 해당 시험.
- Impl-Frontend: `components/ColorLegend.tsx`(신규), `components/FieldOverlay.tsx`(`errRangeOf`·`rangeOf` → robust 기본 + 수동 범위), `components/DispOverlay.tsx`, `api/types.ts`, 해당 시험.
