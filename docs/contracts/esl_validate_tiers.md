# 계약: ④ 검증 판정 단계화(PASS · 조건부 PASS · FAIL) + MAC 판정 (VT, v0.24.5)

- 상태: **초안 → 구현 기준**(2026-11-24). 브랜치 `release/v0.24.5`(main 9b6b2587 = v0.24.4). 구현 코드 없음 — 이 문서가 원본.
- 관계: `esl_disp_primary.md` §3(지표 정의 — **계산은 그대로**, 판정 역할만 단계로), `esl_validate_sources.md`(출처별 같은 정의 — §3.3 반력 역할·D-0.24.3-VAL-18 반력 주의는 §1.4 로 **개정**), `esl_jig_case.md`(지그 3행·P3 등급). 충돌하면 이 문서 범위에서 이 문서가 우선.
- DB migration **1개**(`0017_validation_tiers` — §4.2). 근거: `validations.verdict`·`run_alls.verdict` CHECK 제약이 값을 PASS|FAIL|UNDETERMINED 로 막음(§0.2). D-0.24.3-VAL-17 "migration 없음" 원칙의 예외.
- ID: 결정 `D-0.24.5-VT-n`, 시험 `V-0245-VT-n`, 후속 `R-VT-n`.

### 사용자 요청 (원문, 변경 금지)
1. (2026-11-24) "검증에서 스프링 변위 rms가 0.01이더라고 그럼 1%인데 너무 기준이 낮아. 5% 기준이 패스이고 10%기준이 조건부 패스 였던거로 기억함. 변위 최대 오차는 0.05 기준이긴 하네."
2. (2026-11-24) "검증에서 정보가 많은건 좋지만 여기선 mac이 없음." → "mac 판정 넣자"
3. (2026-11-24, 메인 제안 수용) MAC 기본 ≥ 0.95 PASS, ≥ 0.90 조건부 PASS, < 0.90 FAIL. 모든 출처(jig·jig_disp·jig_spring·full·bforce·fint)에 같은 정의.

---

## 0. 감사 (v0.24.4 = 9b6b2587, 읽기만)

### 0.1 판정 경로 (코어)

| 단계 | 위치 | 지금 |
|---|---|---|
| 지표 계산 | `esl/val_metrics.py:31-52` `disp_metrics` | 양쪽 `remove_linear_rigid` → e = ‖d_val − d_rel‖, `disp_rms_rel`·`disp_max_rel` = /U, 반력 2정의. **MAC 없음** |
| 행 판정 | `val_metrics.py:126-129` `_judged` | `pass = v <= c` 한 기준(단일). None = skipped(pass None) |
| 지표 행 | `val_metrics.py:144-166` `metric_rows` | judge 4(disp_rms·disp_max·reaction·disp_noise) · reference 4 · info 3, 순서 고정 |
| 종합 | `val_metrics.py:169-175` `verdict_of` | 판정 불가 사유 → UNDETERMINED, judge 전부 pass → PASS, 아니면 FAIL + `FAIL_REASON`(`:25`) 코드 |
| 문서 | `val_metrics.py:23-24`·`:178-190` | `esl/validation/3`, `verdict_scheme` `disp_primary/1`, 키 순서 고정 |
| 기준 조립 | `esl/pipeline.py:2360-2369` `crit` | `vcfg` 의 `disp_rms_rel_max`·`disp_max_rel_max`·`reaction_rel_max`·`disp_noise_rel_max` … |
| 출처 반력 | `pipeline.py:2438-2448` | `reaction_tol_key`·`reaction_warn_key` → `crit_s`(fint tol 0.10·warn 0.05) |
| 반력 주의 | `esl/val_src.py:42`·`:331-349` `done_row` | warn < r ≤ tol → **PASS 유지** + 한계 `REACTION_ABOVE_WARN`(caution) + `reaction_warned` |
| echo·경고 | `pipeline.py:2400-2409`(full)·`:2462-2466`(출처) | FAIL 이면 경고 1줄, echo "… (≤기준) → verdict" |
| 산출 | `pipeline.py:2397-2398`·`:2445-2452`·`:2477-2479` | 05_val 루트·`05_val/<dir>/` 같은 세트 + `sources.json`(행 `ROW_METRICS` `val_src.py:327`) |
| 단계 요약 | `pipeline.py:2489-2497` | verdict·지표·`sources` 요약(`:2471-2473`) |
| 설정 | `esl/config.py:299-314`(스키마)·`:410`(`VALIDATION_DEFAULTS` — setdefault 주입 `:630-633`)·`:415`(`VALIDATION_SOURCES_DEFAULTS` — 주입 안 함)·`:464-471`(OPTIONAL_KEYS) | `disp_rms_rel_max` = **필수 키**(기본값 없음) |
| 예시 | `config/esl.example.yaml:70-85` | `disp_rms_rel_max: 0.01` ("임시 값. 사내 확인 후 교체") |

같은 이름 MAC: ③ 재현 `esl/mech/bforce.py:207-212` `mac(u, v)` = (u·v)²/((u·u)(v·v)), 3N 평탄화, 0 벡터 → None. ③ 은 u_val 만 Kabsch 제거(`pipeline.py:1219-1235`, 지그 `:1745-1753`) — ④ 와 강체 제거 규칙이 다르다(§1.3).

### 0.2 verdict 값 · 저장

| 위치 | 허용값 |
|---|---|
| DB `validations.verdict` CHECK `ck_validations_verdict` | `backend/esl_platform/core/db/tables.py:320` PASS·FAIL·UNDETERMINED (migration 0008) |
| DB `validations.scheme` CHECK | `tables.py:321` NULL·`disp_primary/1` |
| DB `run_alls.verdict` CHECK | `tables.py:676` NULL·PASS·FAIL·UNDETERMINED |
| 워커 등록 | `worker/esl_worker/register.py:24`(VERDICT_SCHEMES)·`:238`(verdict 검사)·`:243-252`(insert) |
| 문서 → 행 변환 한 곳 | `backend/esl_platform/core/core_outputs.py:262-282` `validation_fields`(워커·백엔드 출처 공용) |
| 표시 상태 | `api/services/common.py:156-158` `validation_status`(scheme 없음 = LEGACY) |

### 0.3 소비자 (verdict·등급을 읽는 곳)

| 구분 | 위치 | 지금 규칙 |
|---|---|---|
| API 스키마 | `api/schemas.py:170`(CaseLibraryOut)·`:206`(RunAll)·`:576`·`:585`(ValidationOut)·`:599`(ValidationSourceRow)·`:630`(LoadGradeLit)·`:654`(EntrySourceEntry) | Literal PASS·FAIL·UNDETERMINED(·LEGACY) |
| TS | `frontend/src/api/types.ts:267`·`:312`·`:747`·`:770`(ValidationStatus)·`:1952`(LoadGrade) | 같음 |
| 라이브러리 등록 게이트 | `api/services/library.py:402-408` | verdict ≠ PASS → 422 VALIDATION_NOT_PASS |
| 등록 품질 | `library.py:333-346` | ≠ PASS → confirmed_fail/undetermined |
| 적격(DOE·비드 최적화·Case 목록) | `library.py:186-195` `eligibility` → `doe.py:1210·1277·1703`, `opt.py:385·487`, `cases.py:233` | status PASS ∧ scheme |
| 재검증 승격 | `register.py:306` | status ≠ PASS → KEPT_LEGACY |
| CLI 등록 | `esl/library/cli.py:112-117` | ≠ PASS → --confirm-fail 필요 |
| 묶음 등급 | `library.py:791-792`(LOAD_GRADES·GRADE_OF_STATUS)·`:845-857` `_row_grade`·`:918-922` `needs_confirm = worst ≠ PASS` | PASS<caution<not_comparable<UNDETERMINED<FAIL<NO_RESULT, `reaction_warned` → caution |
| load_source 확인 | `library.py:935-968` `check_load_source` | grade ≠ PASS 항목 있으면 ack 없이 422 LOAD_SOURCE_UNCONFIRMED |
| 스냅샷 | `doe.py:1335·1369`·`opt.py:437` `load_source_check.worst` | 생성 때 등급 기록 |
| 전체 실행 | `core/run_all.py:136-143`·`:405-407` | PASS → DONE(verdict PASS), FAIL·UNDETERMINED → STOP |
| 이력 | `api/services/history.py:327-339`(설정 요약 criteria)·`:538-539`(판정·기준 diff) | 키 4개 고정 나열 |
| 출처 행 | `api/services/results.py:249-293` `_source_rows`·`_fill` | sources.json 행 → API 행 |
| 화면 판정 | `frontend/src/components/VerdictStatus.tsx:6-37`·`stages/Stage5.tsx:28-36`(사유 문구)·`:176-189`(JudgeStat)·`:296-321`(판정 카드 4 stat·반력 주의 줄)·`:332`(DispHistogram 기준선) | tone = value > crit |
| 탭 표식 | `view3d/sources.ts:119-130` `markOf`·`reactionTolText` | PASS·FAIL·판정 불가·이전 판정 |
| 출처 선택 | `view3d/loadSource.ts:125-145`(gradeMark·chip)·`components/LoadSourcePicker.tsx:70` | LoadGrade 6값 |
| 기타 화면 | `components/LibraryRegister.tsx:23`·`shell/RunAllBar.tsx:53·164`·`pages/history/CaseHistory.tsx:19`·`pages/library/common.tsx:70·90`·`LibraryList.tsx:52·252·561-565`·`AnalysisNew.tsx:25·53·222`·`pages/CaseList.tsx:11·21` | `=== "PASS"` |
| 보고서 | `esl/report/case_report.py:267`(지표 문구)·`:282-300`(상태·배지)·`:337-358`(판정 표)·`:385-430`(출처별 판정 표)·`esl/report/html.py:198-203`(badge) | PASS·FAIL 배지 |
| 라이브러리 분석 보고서 | `esl/library/report_analysis.py:411-412`·`:491`·`:631` | PASS 비율 |
| 내보내기 | `pipeline.py:2536-2537`·`esl/export/from_entry.py:140-141`(≠ PASS → 경고)·`esl/export/csvout.py:64-65`(verdict 행 pass) | |

### 0.4 해시 · stale (판정 기준이 들어가는가)

| 항목 | 위치 | 들어가는 값 | 기준 변경 영향 |
|---|---|---|---|
| ESL `inputs_hash` | `core/inputs.py:91-114` | 추출 작업·part_title·t*·지지 세트 | **없음** |
| 검증 `stale` | `common.py:164` | esl_run_stale ∨ 현재 실행 아님 | **없음** |
| 코어 run.json `config.sha256` | `pipeline.py:2738-2740` | cfg 스냅샷 전체 | 주입한 키만 바뀜. 비교하는 소비자 없음(기록만 — grep `config_sha256`) |
| `run_alls.core_settings` | `tables.py:669` | 스냅샷 | 기록만 |
| `load_source_check`·라이브러리 `quality` | §0.3 | 생성·등록 때 값 | 다시 계산 안 함 |

결론: 판정 기준은 어느 해시·stale 판단에도 들어가지 않는다. 현장 `esl.yaml` 은 배포가 **없을 때만 복사**(`deploy/install.ps1:11`) → 현장 파일에 `disp_rms_rel_max: 0.01` 이 명시돼 있다.

### 0.5 현장 맥락 (2026-11-24, ③ 재현 값 — ④ 아님)

| 출처 | ③ 재현 MAC | umax 오차 | MAC 기본 기준으로 본 예상 |
|---|---|---|---|
| 지그 고정 | ≤ 0.5 | −50 % | FAIL |
| 내력 | 0.002 | +19406 % | FAIL |
| 경계력 | 0.231 | +308 % | FAIL |
| 지그 변위 | 0.994 | −6.6 % | MAC PASS |
| 지그 스프링 | 0.994 | −5.7 % | MAC PASS |

④ MAC 는 강체 제거 규칙이 달라(§1.3) 값이 조금 다를 수 있다 — 현장 ④ 값으로 확인(완료 기준 6).

---

## 1. 판정 규칙

### 1.1 항목 등급 (judge 행마다)

순수 함수 `val_metrics.tier(v, pass_, cond, sense)` → `PASS | CONDITIONAL | FAIL | None`:
- sense `max`(작을수록 좋음): v ≤ pass_ → PASS, cond 있고 v ≤ cond → CONDITIONAL, 아니면 FAIL.
- sense `min`(클수록 좋음, MAC): v ≥ pass_ → PASS, cond 있고 v ≥ cond → CONDITIONAL, 아니면 FAIL.
- v None → None(skipped), 비유한 값 → FAIL(지금 `v <= c` 와 같음). 경계 포함(≤·≥).

| judge 행(순서) | sense | PASS 기준 | 조건부 기준 | 코드 |
|---|---|---|---|---|
| `disp_rms_rel` | max | `disp_rms_rel_max`(예시 0.05) | `disp_rms_rel_cond_max`(0.10) | DISP_RMS |
| `disp_max_rel` | max | `disp_max_rel_max`(0.05) | 없음(단일) | DISP_MAX |
| `mac` (**새**) | min | `mac_min`(0.95) | `mac_cond_min`(0.90) | MAC |
| `reaction_rel` | max | 출처 `reaction_warn` 있으면 그 값, 없으면 `reaction_rel_max` | 출처 `reaction_warn` 있으면 `reaction_tol`, 없으면 없음 | REACTION |
| `disp_noise_rel` | max | `disp_noise_rel_max` | 없음(단일) | DISP_NOISE |

reference·info 행·`reaction_role = info`(지그 3행) 규칙은 그대로. 행 순서 = judge 5 · reference 4 · info 3(MAC 은 `disp_max_rel` 다음).

### 1.2 종합 판정

1. 판정 불가 사유(NO_FULL_SOLVE·ZERO_DISP) → **UNDETERMINED**(지금과 같음).
2. judge 행 중 FAIL 또는 skipped(None)가 하나라도 → **FAIL**(skipped = FAIL 은 지금 규칙 그대로). `fail_reasons` = 그 행 코드.
3. 아니고 CONDITIONAL 이 하나라도 → **CONDITIONAL**. `cond_reasons`(새) = 그 행 코드.
4. 나머지 → **PASS**.

명칭·문구: 값 `CONDITIONAL`, 화면·보고서·echo 문구 **"조건부 PASS"**. 행 `pass` = (grade == PASS) — 옛 읽기 쪽에 보수적(조건부 행은 pass false).

### 1.3 MAC

- 정의: `mac = esl.mech.bforce.mac(d_val, d_rel)` — d_val·d_rel = `disp_metrics` 가 이미 만든 **양쪽 선형 강체 제거** 변위(N,3 → 3N), cos²θ. 식 복제 없음(`view3d.py:453` 선례). `val_metrics` import 허용에 `esl.mech.bforce`(순수 — numpy·errors·kabsch·mass) 추가, V-4 import 그래프 시험 유지.
- 모든 출처 같은 정의·같은 기준(계획 표 열 없음 — 분기 없음). 풀이 없음 → None(UNDETERMINED 가 우선), 응답 0 벡터 → None → FAIL(MAC).
- ③ 재현 MAC(Kabsch 제거·ESL 단계 rtol)과 숫자가 다를 수 있음 — 이름 구분: ④ 화면·보고서 라벨 "MAC(검증)", ③ 은 그대로.

### 1.4 fint 반력 주의와 등급 통합 (D-0.24.3-VAL-18 개정)

- 기존 키 그대로: `validation.sources.reaction_warn`(fint 0.05) = **PASS 상한**, `reaction_tol`(fint 0.10) = **조건부 상한**. 5 % < r ≤ 10 % = 지금 "PASS + 주의" → **CONDITIONAL**(cond_reasons REACTION).
- 새 결과의 sources.json 행: `reaction_warned` 는 같은 뜻으로 유지(정보 보존), `REACTION_ABOVE_WARN` 은 limits 에 **붙이지 않음**(판정에 들어갔으므로 이중 표식 금지). 문구("반력 x % — 5 % 초과, 받침점 주변 국부 변형 확인")는 조건부 사유 문구로 옮김(§4.5).
- 옛 결과(disp_primary/1)는 저장된 limits·표시 그대로(§3.2).

### 1.5 문서 스키마 (새 결과만)

- `validation.json`: `schema` `esl/validation/4`, `verdict_scheme` `disp_primary/2`, `verdict` 4값, `fail_reasons` 다음에 `cond_reasons`(새 키), `criteria` += `disp_rms_rel_cond_max`·`mac_min`·`mac_cond_min`(실제 적용값), judge 행 += `grade`·`criterion_cond`(없으면 null)·`sense`, `metrics` 에 `mac` 행. 나머지 키·값·파일 세트(`compare_*.npz`·csv)는 그대로.
- `sources.json`(`esl/val_sources/1` 유지 — 키 추가만): 행 += `verdict_scheme`·`cond_reasons`, `metrics` += `mac`(ROW_METRICS 끝).
- run.json 검증 요약: += `mac`·`cond_reasons`, `sources.<key>` += `mac`·`cond_reasons`.
- echo: `변위 RMS=… (PASS ≤0.05 · 조건부 ≤0.1), … MAC=… (PASS ≥0.95 · 조건부 ≥0.9) → 조건부 PASS [DISP_RMS]`. FAIL 경고 줄(`pipeline.py:2400`)은 grade FAIL 행만, CONDITIONAL 은 echo 만(새 ctx 경고 없음).

---

## 2. 설정 (값은 `esl/config.py` 한 곳)

| 키 | 지위 | 기본 | 비고 |
|---|---|---|---|
| `validation.disp_rms_rel_max` | 필수(지금 그대로) | 예시 yaml 0.01 → **0.05** | **이름 유지, 뜻 = PASS 상한**(옛 키 = 새 PASS 키 — 별명·이중 이름 없음) |
| `validation.disp_rms_rel_cond_max` | 선택(새) | 0.10 | 없으면 `max(0.10, disp_rms_rel_max)` → PASS 상한이 0.10 이상인 옛 설정도 오류 없음(조건부 구간 0) |
| `validation.mac_min` | 선택(새) | 0.95 | (0, 1] |
| `validation.mac_cond_min` | 선택(새) | 0.90 | 없으면 `min(0.90, mac_min)` |
| `disp_max_rel_max`·`disp_noise_rel_max`·`reaction_rel_max`·`sources.reaction_tol/warn` | 그대로 | | 단일(반력은 §1.4) |

- `VALIDATION_TIER_DEFAULTS = {"disp_rms_rel_cond_max": 0.10, "mac_min": 0.95, "mac_cond_min": 0.90}` — OPTIONAL_KEYS, **cfg 에 주입 안 함**(설정 해시 불변 — `VALIDATION_SOURCES_DEFAULTS` 선례). 읽기 = `config.validation_tier_settings(cfg)`(위 없을 때 규칙 포함) → `pipeline` `crit`.
- 명시값 역전(`disp_rms_rel_cond_max < disp_rms_rel_max`, `mac_cond_min > mac_min`) = `CONFIG_INVALID`(키 경로). 범위: cond_max > 0, mac 둘 (0, 1].
- `config/esl.example.yaml`: `disp_rms_rel_max: 0.05` + 새 키 3줄 주석(선택 키 선례). `docs/manual/user.md:105`·admin 판정 기준 문단 갱신. 백엔드 pydantic 거울 없음(코어 설정은 `validate_core_settings` 경유).

---

## 3. 하위 호환 · 캐시

### 3.1 stale · 재실행 정책
- 판정 기준은 지금처럼 어느 해시에도 넣지 않는다(§0.4) → 기준·기본값을 바꿔도 ESL·검증이 stale 이 되지 않는다. 새 키는 주입하지 않으므로 키 없는 설정의 `config.sha256` 도 불변.
- 새 기준·MAC 은 **④ [검증 다시 실행]**(기존 VALIDATE — ESL 재실행 불필요, 비용 = 기존 ④ 시간, 지그 포함 +≈ 8~9 분)으로만 생긴다. 저장 지표로 재판정만 하는 작업은 만들지 않음 → R-VT-1.

### 3.2 옛 결과 표시 = 저장 판정 그대로 (재판정 안 함)
- 옛 `05_val`(루트·출처 폴더·`runs/<id>/05_val` 스냅샷)·07_report·06_export 파일은 **바이트 불변**(다시 쓰지 않음).
- 화면·API·보고서 재생성은 옛 검증의 **저장 verdict·criteria** 를 그대로 보인다(disp_primary/1 → PASS·FAIL·UNDETERMINED, 단일 기준, MAC 없음 "–").
- 근거: ① DB 행·라이브러리 항목 quality·run_all verdict·보고서가 같은 판정을 가리켜야 함(표시만 바꾸면 등록 근거와 화면이 어긋남), ② 옛 결과엔 MAC 값이 없음(재계산하면 파일·DB 와 다른 숫자), ③ 0.5.7 선례(scheme 없음 = LEGACY, 백필 없음).
- 표시 구분: 옛 체계 행은 MAC stat "–" + 툴팁 "v0.24.5 이전 검증 — 단일 기준·MAC 없음, [검증 다시 실행]하면 새 기준"(새 줄 없음). 옛 `REACTION_ABOVE_WARN` 표식·문구 그대로.

### 3.3 그 밖
- 라이브러리 옛 항목: quality 불변, 적격 규칙 불변(scheme 있음 ∧ PASS — §4.1 로 CONDITIONAL 만 더함).
- 스터디·비드 최적화 옛 `load_source_check` 스냅샷: 그대로(다시 계산 안 함).
- 옛 서버 + 새 화면: `cond_reasons`·`mac` 없음 → 옛 규칙(tone = value > crit). 새 서버 + 옛 캐시 화면: 같은 배포 묶음이라 일시적, 모르는 status 는 지금처럼 FAIL 색(VerdictStatus `:19`) — 보수적.

---

## 4. 소비자 반영

### 4.1 통과 판정 한 곳 (`PASSING = ("PASS", "CONDITIONAL")`)
- 코어 `val_metrics.PASSING`·`is_passing(v)`, 백엔드 `services/common.PASSING`(코어 값과 같음 시험), 프런트 `VerdictStatus.isPassing`. §0.3 게이트 지점은 `== "PASS"` 직접 비교 대신 이것만 쓴다(정적 시험 V-0245-VT-10).
- CONDITIONAL = **통과**(미결 Q-VT-2 기본 가정): 라이브러리 등록(422 아님·사유 불필요·confirmed_* 없음)·`eligibility` 적격(DOE·비드 최적화·Case 목록 배지)·재검증 PROMOTED·CLI 등록·run_all DONE(verdict CONDITIONAL, 문구 "④ 검증 조건부 PASS — 라이브러리 등록은 ④에서")·내보내기(경고 문구 "검증 조건부 PASS 상태로 내보냄" — 경고 유지, 막지 않음). csv `validation.csv` 열 불변(verdict 행 value CONDITIONAL, pass = PASS 일 때만).

### 4.2 DB · 등록 (migration `0017_validation_tiers`)
- `validations`: 컬럼 `mac` Float NULL, `cond_reasons` JSONB NOT NULL DEFAULT `'[]'`. CHECK 교체 `ck_validations_verdict` += CONDITIONAL, `ck_validations_scheme` += `disp_primary/2`, 추가 `ck_validations_conditional`: `verdict <> 'CONDITIONAL' OR (scheme = 'disp_primary/2') IS TRUE` (scheme NULL 이면 CONDITIONAL 불가 — NULL 에서 CHECK 가 통과로 새지 않도록 `IS TRUE`).
- `run_alls`: `ck_run_alls_verdict` += CONDITIONAL.
- 백필 없음(옛 행 mac NULL·cond_reasons []). downgrade = CONDITIONAL·`disp_primary/2` 행이 있으면 중단(데이터 보존 — 0008 선례).
- `core_outputs.validation_fields` += `mac`(metric_value)·`cond_reasons`. 워커 `register_validation`: verdict 4값·VERDICT_SCHEMES 2값 허용, mac·cond_reasons 저장, 응답·`_quality_from`·`QUALITY_FROM_VALIDATION` += mac·cond_reasons. 라이브러리 등록 quality(`library.py:333`) += 같은 두 키.

### 4.3 API · OpenAPI · TS
- verdict/status Literal 에 `CONDITIONAL`(§0.3 스키마 7곳·TS 5곳 — LEGACY 있는 곳은 유지).
- `ValidationOut` += `mac: float|None`, `cond_reasons: list[str] = []`(옛 행 null·[] — 응답 키 2개 증가는 의도 변경). `ValidationSourceRow` += `scheme`, `cond_reasons`.
- `LoadGradeLit` = PASS < **CONDITIONAL** < caution < not_comparable < UNDETERMINED < FAIL < NO_RESULT.
- 이력 `_settings_summary` criteria += 새 키 3개(스냅샷에 없으면 null). `scripts/dump_openapi.py --check`·`npm run check:api` 통과.

### 4.4 묶음 등급 · load_source 확인
- `GRADE_OF_STATUS` += CONDITIONAL. `_row_grade`: `reaction_warned` → caution 은 **status PASS(옛 체계 행)일 때만**(새 행은 CONDITIONAL 로 이미 표현).
- `needs_confirm = worst ∉ {PASS, CONDITIONAL}`, `check_load_source` 확인 대상 항목 = grade ∉ {PASS, CONDITIONAL}. → 조건부 PASS 출처 선택 = **확인 없이 진행**, 칩·표에 "조건부 PASS" 표식. caution(한계)·not_comparable·FAIL·UNDETERMINED 확인 규칙은 그대로.

### 4.5 화면 (2560×1440 세로 높이 불변·새 버튼 0·정보 삭제 없음)
- `STATUS_LABEL`·`MARK_STATUS_TEXT`·`GRADE_TEXT`·`LIB_STATUS` += CONDITIONAL "조건부 PASS", 배지·tone `warn`. 탭 mark "조건부 PASS"(2560 한 줄·1920 팝오버 — Playwright 확인).
- 판정 카드 stat 5개: 기존 4 + **"MAC(검증)"**(`disp_max_rel` 다음, `.stats` auto-fill 같은 줄). sub = "PASS ≤ 0.05 · 조건부 ≤ 0.1"(MAC 은 ≥), tone = 새 체계: 코드가 `fail_reasons` → bad, `cond_reasons` → warn, 아니면 ok / 옛 체계: 지금 규칙. 반력 stat 은 출처 `reaction_warn` 있으면 같은 2단 문구, `reactionTolText` 도 새 체계 행은 "반력 PASS ≤ 5 % · 조건부 ≤ 10 %".
- 사유: `fail_reasons` 목록 아래 `cond_reasons` 목록(`warn-text`, `COND_REASON_LABEL` — DISP_RMS "변위 RMS 오차가 PASS 기준 초과(조건부 구간)", MAC "변형 형상 일치(MAC)가 PASS 기준 미만(조건부 구간)", REACTION "반력이 PASS 기준 초과 — 받침점 주변 국부 변형 확인"). 목록은 사유 있을 때만(지금 fail 목록과 같은 자리 규칙). `FAIL_REASON_LABEL` += MAC "변형 형상 일치(MAC)가 기준 미만".
- `DispHistogram` 선택 속성 `rmsCondCrit`(점선 1개 추가, 없으면 DOM 동일). 등록 버튼·RunAllBar·라이브러리 배지·`isEligible` = `isPassing`. 라이브러리 목록 필터 += "조건부 PASS"(서버 필터는 대문자 일치라 그대로), 분석 새로 만들기 기본 필터 "PASS·조건부 PASS"(`["PASS","CONDITIONAL"]`) + "PASS만" 선택 유지.

### 4.6 보고서
- 5절 판정 표: 열 그대로, "기준" 칸 = "≤ 0.05 / 조건부 ≤ 0.1"(단일은 지금 문구), "판정" 칸 = grade 배지(PASS·조건부 PASS·FAIL), 설명 문장 "판정 = 변위 4지표" → "판정 = 변위 지표 4 + MAC(검증), 단계 PASS·조건부 PASS·FAIL". `_METRIC_TEXT` += mac.
- 출처별 판정 표: 열 **"MAC(검증)"** 추가("변위 최대/U" 다음), 판정 칸 CONDITIONAL 배지 + `cond_reasons`. sources.json 에 mac 없으면 "—". 머리 설명에 MAC·조건부 한 문장.
- `html.badge` += CONDITIONAL(class `cond`), `STATUS_TEXT` += "조건부 PASS". 라이브러리 분석 보고서 `_verdict`·분포 라벨 += CONDITIONAL, "PASS 비율" → "PASS 비율(조건부 포함)".

---

## 5. 시험 (V-0245-VT-n)

1. `tier` 경계: max/min·경계 포함·cond None = 단일·None → None·inf/NaN → FAIL.
2. `verdict_of`·`cond_reasons`: UNDETERMINED 우선, FAIL 우선, CONDITIONAL, PASS, skipped judge = FAIL(불변), 빈 목록 PASS.
3. MAC: `val_metrics` 가 `bforce.mac` 같은 객체 사용, u_val 에 선형 강체 더해도 불변, 배율 불변, 같은 변위 = 1, 응답 0 → None → FAIL MAC.
4. 설정: 새 키 없음 → cfg 불변·`config.sha256` 불변(`tests/fixtures/cumulative/esl_v072.yaml`), 역전 = CONFIG_INVALID, PASS 0.2·cond 없음 → cond 0.2(오류 없음), mac_cond 없음·mac_min 0.85 → 0.85, 범위 오류.
5. fint 반력: 4 % PASS, 7 % CONDITIONAL(cond_reasons REACTION·`reaction_warned` true·limits 에 REACTION_ABOVE_WARN 없음), 12 % FAIL. full·bforce 반력 단일 그대로.
6. full 골든: 새 validation.json = v0.24.4 골든 + 의도 차이만(schema·verdict_scheme·cond_reasons·criteria 새 키·mac 행·judge 행 grade/criterion_cond/sense) — 나머지 값 비트 동일(`tests/cumulative/golden_util.py` 제외 목록에 새 키만 추가, D-0.24.3-VAL-8 보충 선례).
7. 출처 6행 모두 mac·grade·cond_reasons 가 sources.json 행·출처 validation.json·run.json 요약에서 같은 값.
8. 옛 결과: v0.24.4 05_val·sources.json 픽스처 → API 응답 verdict·status·limits 불변, mac null·cond_reasons [], 파일 바이트 불변(읽기 전후 sha).
9. migration 0017 up/down: CONDITIONAL 삽입 가능, scheme disp_primary/1 + CONDITIONAL 거부, CONDITIONAL 행 있으면 downgrade 중단, 옛 행 불변.
10. 게이트(Q-VT-2 가정): CONDITIONAL 등록 201·적격·재검증 PROMOTED·run_all DONE CONDITIONAL·CLI 등록·DOE/비드 최적화 적격 / 정적 시험: §0.3 게이트 파일에 verdict·status 와 `"PASS"` 직접 비교 0건, `common.PASSING == val_metrics.PASSING`.
11. 묶음 등급: 순서, CONDITIONAL 만 → needs_confirm false·ack 없이 진행, 옛 행 PASS + reaction_warned → caution(확인 필요 유지).
12. 보고서: 출처별 표 MAC 열·CONDITIONAL 배지·옛 sources.json "—", 5절 2단 기준 문구.
13. 프런트 vitest: StatusBadge·markOf·gradeMark·chip CONDITIONAL, JudgeStat tone(새=사유 기준·옛=값 기준), MAC stat·옛 "–" 툴팁, cond 사유 목록, isPassing 사용처, `real_v0245.json` 픽스처(워커 e2e 덤프) 대조.
14. Playwright 2560·1920: 판정 카드·탭 줄 높이 = v0.24.4 와 같음(수동 측정 — D-0.24.3-VAL-12 보충 선례).
15. `dump_openapi --check`·`check:api`·V-4 import 그래프.

## 6. 완료 기준

1. 시험 1~15 통과, 기존 시험은 의도 변경(예시 yaml 0.05·judge 5행·스키마 문자열·LoadGrade 7값)만 기대값 갱신.
2. 새 검증의 모든 출처 행에 MAC·등급, 종합 = 최악 등급, 문구 "조건부 PASS".
3. fint 반력 5~10 % = CONDITIONAL(이전 PASS + 주의).
4. 옛 05_val·보고서 바이트 불변, 옛 결과 화면·API 판정 불변.
5. migration 0017 왕복, CHANGELOG·admin 매뉴얼에 "현장 esl.yaml `disp_rms_rel_max` 를 0.05 로"(Q-VT-1) 안내.
6. 현장 1 Case [검증 다시 실행] 후 출처별 ④ MAC·등급을 §0.5 표 옆에 기록(구현 메모).

## 7. 작업 분해 (파일 소유 겹침 없음)

| 묶음 | 파일 |
|---|---|
| **C 코어** | `esl/val_metrics.py`(tier·PASSING·MAC·행·verdict·cond_reasons·문서), `esl/val_src.py`(done_row 반력 통합·ROW_METRICS·verdict_scheme·cond_reasons), `esl/config.py`(스키마·TIER 기본·읽기·역전 검사), `esl/pipeline.py`(crit·echo·요약·내보내기 문구), `config/esl.example.yaml`, `esl/report/{case_report,html}.py`, `esl/library/{cli,report_analysis}.py`, `esl/export/from_entry.py`(문구), 코어 시험·골든 |
| **B 백엔드** | `migrations/versions/0017_validation_tiers.py`, `core/db/tables.py`, `core/core_outputs.py`, `worker/esl_worker/register.py`, `api/schemas.py`, `api/services/{common,library,results,history,cases}.py`, `core/run_all.py`, `docs/contracts/openapi_p1b.json`, 백엔드·워커 시험(픽스처 덤프 `real_v0245.json` 생성 포함) |
| **F 프런트** | `api/types.ts`, `components/{VerdictStatus,DispHistogram,LibraryRegister,LoadSourcePicker}.tsx`, `stages/Stage5.tsx`, `view3d/{sources,loadSource}.ts`, `shell/RunAllBar.tsx`, `pages/{CaseList,history/CaseHistory,library/common,library/LibraryList,library/AnalysisNew}.tsx`, mock·vitest |

순서: C → B(코어 문서 형식 의존) → F(B 응답 픽스처 의존). 문서(`docs/manual/*`·CHANGELOG)는 통합 때.

## 8. 미결 (결과를 바꾸는 것만 — 기본 가정으로 진행)

- **Q-VT-1 현장 `esl.yaml` 의 `disp_rms_rel_max: 0.01`**: 기본 가정 = **명시값 존중**(설정 = 단일 원본) → 현장은 업데이트만 하면 PASS ≤ 1 %·조건부 ≤ 10 %(1~10 % 가 FAIL 대신 조건부 PASS), 현장 yaml 1줄을 0.05 로 고치면 사용자 기준 5/10 %. 대안(채택 안 함): 코드가 0.01 을 "옛 예시값"으로 보고 무시.
- **Q-VT-2 CONDITIONAL 의 게이트**: 기본 가정 = **통과**(라이브러리 등록·적격·재검증 승격·하위 작업 출처 선택 확인 없음, 표식만). 대안: 라이브러리 등록만 막기(FAIL 과 같게) 또는 등록 때 확인.

## 9. 결정 (요약 — 전문 `docs/decisions.md` 2026-11-24)

D-0.24.5-VT-1 항목 등급·종합(§1.1·§1.2), VT-2 MAC 정의·위치(§1.3), VT-3 설정 키(§2), VT-4 fint 반력 통합(§1.4), VT-5 스키마(§1.5), VT-6 해시·stale·옛 결과 표시(§3), VT-7 migration 0017(§4.2), VT-8 통과 판정 한 곳·게이트(§4.1), VT-9 등급 순서·확인(§4.4), VT-10 화면(§4.5), VT-11 보고서(§4.6), VT-12 화면 출처 숨김(§11), VT-13 출처 계산 제외(§12).

## 10. 후속 (R-VT-n)

- R-VT-1 저장 지표로 재판정만 하는 작업(다시 풀지 않음 — 옛 `compare_disp.npz` 에 d_rel·d_val 이 있어(`esl/report/field.py:357`) MAC 재계산 가능. 새 검증 행으로 등록할지·옛 행을 둘지 결정 필요).
- R-VT-2 ③ 재현 MAC·umax 오차를 ④ 와 같은 강체 제거 규칙으로 맞출지(지금은 이름만 구분).

## 11. 화면 출처 숨김 (사용자 결정 2026-11-24 — D-0.24.5-VT-12)

사용자 원문: "경계력이랑 내력은 참고로도 쓰기 어려우니 웹에서 숨겨놓자. 지그 esl도 고정은 숨기자".

- **표시만**: 웹 화면에서 출처 `bforce`·`fint`·`jig`(지그 고정)를 숨긴다. 계산·API 응답·저장 산출물(sources.json·05_val 폴더·스냅샷)·보고서(07_report·DOE 보고서)는 전 출처 그대로 — 정보 삭제 없음, 설정 한 줄로 되돌림. 보이는 출처 = `jig_disp`·`jig_spring`·`full`.
- **설정 한 키**(하드코딩 금지): `ui.hidden_sources`(backend `UiCfg.hidden_sources`, 기본 `["bforce","fint","jig"]`, `config/esl_platform*.example.yaml`). `GET /version` 의 `ui.hidden_sources` 로 전달. 코어 설정 아님(코어 변경 불필요). 키가 없거나(옛 서버) `[]` 이면 v0.24.4 화면과 같다(탭·높이 동일 — Playwright 확인).
- **거르는 곳 한 곳**: 화면 출처 표 `view3d/sources.ts`(`setHiddenSources`·`isHiddenSource`)를 읽는 `tabItemsOf`(Case ③ 3D 탭·④ 검증 탭·판정 표식), `loadSourceOptions`(스터디·비드 최적화 하중 출처 드롭다운 — 숨긴 출처 선택 불가), `doeTabs.visibleLoadSources`(스터디 하중 정의 탭·순위·3D·사유 줄·칩), `loadSourceChipOf`(결과 칩). 출처 이름 분기 없음. AppProvider 가 `/version` 을 받으면 설정을 넣고 화면을 한 번 다시 세운다.
- 지그 그룹은 보이는 행이 2개(변위·스프링)이면 그대로 그룹 [변위|스프링](2560 펼침·1920 팝오버 규칙 유지). 기본 탭은 보이는 첫 출처(숨긴 출처가 응답 default·스냅샷 기본이어도).
- 스터디 순위 기준(`metric_effective`)이 숨긴 출처이면 결과 카드에 한 줄 알림("순위 기준 출처(…)는 화면에서 숨겼습니다 …", `data-testid=hidden-primary-note`) — 정보 손실 없음(계산·저장 그대로).
- 시험: 기본 설정에서 숨김 3출처가 어떤 탭·드롭다운에도 안 보임, `[]` 이면 v0.24.4 화면과 같음(vitest `validate_tiers.test.tsx` §11, Playwright 높이·탭 `/home/claude/shots/v0245h_*`).

## 12. 출처 계산 제외 (사용자 결정 2026-11-24 — 범위 추가)

### 12.1 사용자 요청 (원문, 변경 금지)
1. (2026-11-24 10:48) "경계력이랑 내력은 참고로도 쓰기 어려우니 웹에서 숨겨놓자. 지그 esl도 고정은 숨기자"
2. (2026-11-24 11:16) "강성스터디랑 esl계산에서도 제외하는거지?" — 예.

### 12.2 결정 (D-0.24.5-VT-13)
화면 숨김(`ui.hidden_sources`)은 B·F, **계산 제외는 코어 기본값**(설정으로 되돌릴 수 있음 — 하드코딩 없음, 출처 이름 분기 없음).

| 대상 | 키(기본값 원본) | v0.24.4 → v0.24.5 | 끈 효과 |
|---|---|---|---|
| Case 경계력·내력 | `bforce.enabled`(`esl/config.py` BFORCE_DEFAULTS, 예시 yaml 주석) | true → **false** | ③ `bforce`·`fint` 산출 없음(요약 code BF_DISABLED·FINT_DISABLED), ① 추출 request `bf_on 0`(워커 `h3d.bforce_request` — TCL 이 경계력 결과를 읽지 않음), ③ 보충 추출(on_demand) 판정 = 끔, ① `pack_bforce` 없음 |
| Case 지그 고정 | `jig.methods`(`esl/mech/jig.py` JIG_DEFAULTS, 예시 yaml 주석) | [fixed, prescribed, spring] → **[prescribed, spring]** | ③ `jig.json/npz` 없음(요약 JIG_DISABLED, detail jig.methods). jig_disp·jig_spring 그대로 |
| 스터디 경계력·내력 | `bforce.enabled`·`fint.enabled`(`esl/doe/__init__.py` DEFAULTS) | true → **false** | 새 스터디 노드 힘 출처 사이드카·보기 계산 없음 |
| 스터디 지그 고정 | `rank.jig.methods`(DEFAULTS — JIG_DEFAULTS 거울) | 같음 → **[prescribed, spring]** | 새 스냅샷 C_jig 계산 없음 |
| 스터디 기본 순위 | `rank.metric = jig` 해석 | C_jig 고정 | **스냅샷 방식 목록 첫 방식의 출처 지표**(`_jig_rank_src` — fixed 첫째 = jig 그대로, 새 기본 = jig_disp → `jd`). 준비 안 됨 = 지금처럼 solve |

- ④ 검증: 계산하지 않은 출처는 지금 규칙대로 `row_status` unavailable(code = ESL 요약 BF_DISABLED·FINT_DISABLED·JIG_DISABLED) → 풀이 0(분해 묶음에서 빠짐).
- full(전 노드)·jig_disp·jig_spring 은 그대로 계산.
- 옛 스냅샷(rank.jig 키 없음 = LEGACY_ABSENT translation·fixed, v0.24.4 스냅샷의 명시 methods)·옛 Case 결과 = 바이트 동일(값을 스냅샷·설정에서 읽음).
- 되돌림: `bforce: {enabled: true}` + `jig: {methods: [fixed, prescribed, spring]}` = v0.24.4 와 같은 산출물(골든 V-0245-VT-6 이 이 설정으로 비교).
- 백엔드 거울(B): pydantic `BeadDoeBforceCfg/FintCfg.enabled`·`BeadDoeRankJigCfg.methods` 기본값과 `config/esl_platform*.example.yaml` 2개 — 같은 이름·값.
- 시험 V-0245-VT-16: 기본 설정에서 끈 출처 산출물·풀이·bf_on 0, 되돌린 설정 = 골든, 옛 스냅샷 바이트 동일, 소요 시간 비교(합성).
