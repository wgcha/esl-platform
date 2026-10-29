# 계약: 누적(CUMULATIVE) 낙하 씬 입력 — 이전 해석 상태 파일(.str·.sta) + OptiStruct 경로 자동 감지 (v0.8.0)

- 상태: **확정(가정 확정)** (2026-10-29). §17 Q1~Q3 는 사용자 답변 전 **권장안 A 가정으로 확정**하고 구현 진행(가정 확정 — 사용자가 다른 안을 고르면 변경 메모로 바꾼다).
- 버전: **v0.8.0** (기준 main a6587cf, v0.7.2).
- 근거: GitHub 이슈 #34 "str, sta" (실데이터 발췌), 사용자 확정 4건(아래 U1~U4, 변경 금지).
- 대체 범위: `esl_core.md` §3.1(parse_rad — 상태 파일 include 우선 규칙·헤더 파싱), §7.1·§7.4(t* 지표 — 누적 씬일 때만), `esl_disp_primary.md` §3.4(변형률 참고 비교 기준 — 누적 씬일 때만), decisions.md 0.7.2 "opt_run 누락은 자동 보충하지 않음"(§12 규칙으로 **완화**). 비누적 씬 동작은 전부 그대로(§10). 충돌 시 이 문서 우선.
- ID 규칙: 결정 `CI-D-n`, 시험 `V-CI-n`, 리스크 `R-CI-n`.

### 사용자 확정 (2026-10-29, 변경 금지)
- **U1 참조 방식** = rad 안 `#include`(또는 `/INCLUDE`)로 이전 런의 상태 파일을 읽는 덱 그대로. 파일 이름 규칙으로 짝짓기 하지 않는다.
- **U2 t\* 판정 변형률** = **누적 합계(이전 + 이번)** 기준. 화면에는 **증분(이번 낙하분)도** 함께 표시.
- **U3 기준 좌표** = `.str` 의 **변형된 좌표**(h3d 첫 프레임과 일치 — 모델 동일성 판정도 이 좌표). 상태 파일은 **대상 파트만** 숫자 해석(대용량). 업로드 허용 확장자에 `.sta`·`.str` 추가 + include 누락 검사.
- **U4 OptiStruct 경로 자동 감지**: update-repo / setup_config 가 기존 `altair.hw_exe_path` 에서 같은 Altair 설치의 `hwsolvers/scripts/optistruct.bat` 을 추정, **파일이 실제 있을 때만** `opt_run.enabled: true`·`altair.optistruct_path` 를 **추가**(기존 값 불변), 수정 전 yaml 백업(`_backup` 규칙), 추가 내용 콘솔 1줄.

---

## 0. 현황 조사 (main a6587cf)

| 항목 | 위치 | 현재 동작 | 누적 씬에서의 문제 |
|---|---|---|---|
| include 추적 | `esl/rad/parser.py _Deck.scan/_include` | `/INCLUDE`·`#include` 재귀(깊이 8), 포함 파일도 같은 키워드 규칙으로 스캔 | 상태 파일도 그냥 "덱 조각"으로 읽힘 — 아래 두 버그로 실패 |
| 블록 헤더 | `_Deck.scan` `head = line.split()[0]` | `/SHELL/2` 처럼 붙은 헤더만 인식 | **`.str` 헤더는 `/SHELL/         2`(ID 를 10자 칸에 오른쪽 정렬)** → `head="/SHELL/"` → `part_ID 가 없음` RAD_PARSE_ERROR. `/TETRA4/        22` 동일 |
| 중복 요소 | `parse_rad` | 대상 파트 요소 ID 중복이면 RAD_PARSE_ERROR | rad 본문과 `.str` 가 같은 요소를 다시 정의하면 실패 |
| 중복 노드 | `load_nodes` | 파일 읽기 순서상 **마지막 정의 우선** | `.str` 가 원래 `/NODE` 보다 **앞에** include 되면 원래 좌표가 이김 |
| 쉘 두께 | `_shell_row` `line[80:100]` | 요소 카드 두께 > 0 이면 우선 | `.str` /SHELL THK(81–100열, 실측 확인) 가 이미 이 열 → 자동으로 변형 두께 사용(의도와 일치, 통계 없음) |
| /INISHE | `_consume` | 모르는 키워드 → 건너뜀 | 초기 소성 변형률 미사용 → t* 가 증분 기준 |
| 업로드 확장자 | `UPLOAD_EXT_DEFAULT`, 예시 yaml `upload.allowed_ext`, PC 도구 `esl_upload_lib.ps1` | `.rad .inc .k .csv .json .txt .tcl .h3d .fem` | `.sta`·`.str` 업로드 거부(UPLOAD_EXT_NOT_ALLOWED). 기존 서버 yaml 은 목록을 **명시**하고 있어 기본값만 바꿔서는 안 풀림 |
| include 누락 | `uploads.complete` `scan_include_refs` → `missing_includes` | 일반 누락으로 표시 | 상태 파일임을 알려 주지 않음 |
| 좌표 검사 | `results_csv.pack_results` | model.csv x0 = frame0 coords − frame0 disp ↔ rad 좌표, Kabsch 잔차 ≤ 0.005·bbox | 누적 h3d 의 frame0 좌표 = 변형 좌표. rad 원좌표로 비교하면 변형이 작을 때 **조용히 통과**(원형상으로 K_L 계산) — 상태 include 가 있으면 x0 = `.str` 좌표라 정확히 일치 |
| OptiStruct 설정 | `deploy/setup_config.py opt_run_hint` | 꺼져 있으면 OPT_RUN_HINT 1줄, 자동 보충 없음(0.7.2 결정) | U4 로 완화 |

이슈 #34 실데이터 형식(요약):
- `.str`: 1행 `#RADIOSS STATE FILE <runname>_0002.sta`, `/BEGIN`(runname / `2024 0` / 단위 2행 `1.0000000610352E+03 1.0000000474975E-03 1.0000000000000E+00` = 숫자 배율), `/SHELL/<part>`(`SHELLID NOD1..4` I10×5 + THK F20 at 81–100), `/TETRA4/<part>`(I10×5), `/NODE`(I10 + F20×3, **공백 없이 붙음** `100001-4.4584247589111E+01-4.7285476684570E+01 2.00…`).
- `.sta`: `/BEGIN`(같은 형식) 뒤 `/INISHE/EPSP_F` 블록 여러 개(블록마다 `#` 주석 7행), 레코드 = 헤더 `SHELLID NPT NPG THK`(I10×3 + F20) + 값 `max(1,NPT)·NPG` 개를 **20자 필드 5개씩 흘려 씀**(IPG 가 빠른 쪽: `EPSP(IPG,IPT)` 순, NPT=5·NPG=4 → 20개 = 4행, NPT=0·NPG=4 → 4개 = 1행). 뒤에 `/INIBRI/STRA_F`, `/INIBRI/FAIL` 등 솔리드 블록.
  - ※ 위임 메모의 "NPT행×NPG값" 은 실제 형식과 다름 — **값 개수 기준 5개/행 흐름**이 맞다(NPT=5·NPG=4 가 5값×4행으로 보이는 것은 우연).

## 1. 용어

| 용어 | 정의 |
|---|---|
| 누적 씬 | rad 의 include 그래프에 상태 파일(§2)이 하나 이상 있는 Case |
| 형상 상태 | `/NODE`·`/SHELL`·`/SH3N` 을 담은 상태 파일(보통 `.str`) |
| 초기 상태 | `/INISHE/*` 를 담은 상태 파일(보통 `.sta`). 한 파일이 둘 다일 수 있음 |
| prev(e) | 요소 e 의 이전 런 소성 변형률(초기 상태 EPSP_F 를 §6.1 규칙으로 요소값 1개로 집계) |
| raw(f,e) | 이번 h3d 의 값(Max_Strain ε_eq 또는 Plastic Strain, max-hold) |
| cum(f,e) / inc(f,e) | 누적값 / 증분값(§6.3) |

## 2. 상태 파일 식별 (CI-D-1)

- 대상: include 그래프(깊이 제한 기존 `rad_include_max_depth`)의 각 파일. 이름 규칙 짝짓기 없음(U1).
- 판정(둘 중 하나면 상태 파일): ① 첫 비어 있지 않은 행이 `#RADIOSS STATE FILE`(대소문자 무시)로 시작 ② 확장자 `.sta`·`.str`(대소문자 무시).
- 종류는 **내용으로** 정함: 스캔 중 `/NODE`·`/SHELL`·`/SH3N` 이 있으면 `geometry`, `/INISHE/` 가 있으면 `initial`(둘 다 가능). 확장자는 종류를 정하지 않는다(실데이터 `.str` 헤더가 `.sta` 이름을 담고 있음).
- `RadModel.state.files[] = {path, spec(원문), kinds:[geometry|initial], has_begin, sha256(지문 단계에서)}`.
- 상태 파일 안의 `#include`·`/INCLUDE` 도 기존 규칙으로 따라간다(실데이터엔 없음).

## 3. 파서 사양

### 3.1 숫자 필드 (공통, CI-D-2)
- 정수 I10, 실수 F20 고정폭 우선(`int(raw[a:b])`, `float(...)`), 실패 시 기존 `_i`·`_f` 규칙(Fortran 지수 `1.0-3`, `D` 지수).
- 고정폭 해석이 실패하고 행이 공백 구분 형식이면(같은 행 토큰 수가 기대 개수와 같음) 토큰 해석으로 대체: 정규식 `[+-]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][+-]?\d+)?` 로 **붙은 실수도 분리**(`-4.45E+01-4.72E+01` → 2개). 대체 경로를 쓴 행 수는 `state.parse.fallback_rows` 로 기록(정보).
- 실측: `/NODE` 행 길이 70(I10+F20×3), `.str` /SHELL 행 길이 100 — THK 는 `line[80:100]`(앞 공백 1 포함) → 기존 열 규칙과 같다.

### 3.2 블록 헤더 (parser.py 전체에 적용 — 비누적 rad 에도 영향, CI-D-3)
- `/` 로 시작하는 행에서 `#` 이후를 버리고, **첫 토큰이 `/` 로 끝나면 뒤따르는 정수 토큰을 이어 붙인다**: `/SHELL/         2` → `/SHELL/2`, `/TETRA4/        22` → `/TETRA4/22`. 그 외(제목 문자열 등)는 기존대로 첫 토큰만.
- 기존 rad 에서 첫 토큰이 `/` 로 끝나는 헤더는 지금까지 part_ID 누락 오류였으므로 결과가 바뀌는 정상 입력은 없다(V-CI-P2 로 기존 fixture 불변 확인).

### 3.3 형상 상태(`.str`) 블록
- `/BEGIN`: §3.5. `/SHELL/<part>`·`/SH3N/<part>`: 기존 `_shell_row`(THK 81–100). `/TETRA4` 등 비쉘: 기존 `_consume_elems`(행 수·최대 ID만). `/NODE`: 기존 `load_nodes`(대상 요소 참조 노드만 좌표 해석).
- 상태 파일 출처를 세그먼트에 표시(`_Seg.state = True`) → §4 우선 규칙에 사용.

### 3.4 초기 상태(`.sta`) `/INISHE/EPSP_F` (신규 `esl/rad/state.py`)
- 1차 스캔(`_Deck.scan`)은 `/INISHE/<sub>` 블록의 위치(파일·오프셋·행 수·sub)만 `inishe_segs` 에 기록(본문 해석 없음). `/INIBRI/*`, 기타 `/INI*` 는 기존대로 건너뜀(종류만 `state.files[].other_blocks` 에 이름 기록).
- 2차(`parse_rad` 가 대상 요소 ID 를 확정한 뒤): `read_epsp_f(segs, elem_id_sorted) -> EpspInit` — 블록마다 상태기계:
  1. `#` 행 무시, 빈 행 무시.
  2. 헤더 행: `SHELLID(I10) NPT(I10) NPG(I10) THK(F20, 31–50)`. `NPG ≥ 1`, `NPT ≥ 0` 아니면 `STATE_PARSE_ERROR`(파일:행).
  3. 값 `k = max(1,NPT)·NPG` 개: 다음 행들에서 20자 필드로 읽음(행당 `ceil(len(rstrip)/20)` 개, 마지막 행 나머지). 개수가 맞지 않게 다음 헤더(정수 I10 3개 + 실수 패턴)가 나오면 `STATE_PARSE_ERROR`.
  4. **대상 요소가 아니면 숫자 해석 없이 행만 건너뜀**(값 행 수 = 헤더의 k 로 계산, 행 길이로 개수 확인).
  5. 대상 요소면 값 배열을 `EPSP[IPT][IPG]`(IPG 빠름) 로 보관.
- 같은 SHELLID 가 여러 번 나오면 마지막 우선 + 경고 `STATE_DUP_DEFINITION`(개수).
- 반환 `EpspInit{elem_id(E,), has(E,) bool, npt(E,) i2, npg(E,) i2, thk(E,) f8, agg:{mid_mean, mid_max, max, mean}(E,) f8}` — 원값 배열은 보관하지 않음(메모리).
- `/INISHE/` 의 다른 sub(`STRS_F`, `STRA_F`, `THICK` 등)는 P1 에서 해석하지 않고 존재만 기록(`state.inishe_subs`). `STRA_F` 가 있으면 정보 메시지 "이전 총변형률 카드가 있으나 사용하지 않음(Q1)".

### 3.5 `/BEGIN` (상태 파일)
- 행: runname / `Invers Irun` / 입력 단위 / 작업 단위(각 F20×3 숫자 배율 또는 문자열). 상태 파일의 `/BEGIN` 은 `units_label` 을 바꾸지 않는다(첫 `/BEGIN` = 주 rad 우선, 기존 규칙).
- 비교: 주 rad·상태 파일 둘 다 숫자 배율이면 상대 1e-6 로 비교, 다르면 경고 `STATE_UNIT_MISMATCH`(값 병기). 어느 한쪽이 문자열이면 비교 생략, `state.begin` 에 원문 기록.
- 상태 파일 runname 은 `state.files[].runname` 으로 기록(화면 표시, 판정 아님).

### 3.6 대용량·스트리밍
- 모든 읽기는 `rb` 행 단위(전체 텍스트 적재 금지), 2차는 오프셋 seek. 대상 파트 밖 행은 int 변환 1회 이하.
- 성능 목표(V-CI-P5): 합성 `.sta` 1 GB(쉘 100만, NPT=5·NPG=4, 대상 20 %) `read_epsp_f` ≤ 15 s, 추가 메모리 ≤ 150 MB. `.str` 은 기존 parse_rad 성능 기준(0.5.2) 유지.

### 3.7 오류·경고 코드 (esl.errors, 코어)
| 코드 | 종류 | 조건 |
|---|---|---|
| `STATE_INCLUDE_MISSING` | 오류 | include 대상이 상태 파일로 보이는데(§2 ② 확장자) 찾을 수 없음 — 기존 RAD_PARSE_ERROR "인클루드 파일을 찾을 수 없음" 대신. 메시지에 원문·후보 경로 |
| `STATE_PARSE_ERROR` | 오류 | 대상 파트 레코드 형식 오류(§3.4), 대상 요소 THK ≤ 0 |
| `STATE_UNIT_MISMATCH` | 경고 | §3.5 |
| `STATE_DUP_DEFINITION` | 경고 | 같은 노드·요소·SHELLID 가 rad 와 상태 파일(또는 상태 파일끼리)에 중복 — 사용한 쪽 명시 |
| `STATE_PARTIAL` | 경고 | 형상 상태가 있는데 대상 파트 노드·요소 일부만 정의 / 초기 상태가 있는데 대상 요소 일부에 EPSP_F 없음(없는 요소 prev = 0) — 개수·상위 10개 |

## 4. 좌표·요소 결정 규칙 (CI-D-4)

- **우선순위: 상태 파일 정의 > rad(비상태) 정의**, 파일 읽기 순서와 무관. 상태 파일끼리는 include 순서상 마지막 우선. 중복이 있으면 `STATE_DUP_DEFINITION`.
  - 노드: 대상 요소가 참조하는 노드 좌표 = 상태 파일 `/NODE` 값(있으면), 없으면 rad 값(`STATE_PARTIAL`).
  - 대상 파트 쉘 요소: 상태 파일 `/SHELL/<part>` 에 있는 요소 ID 는 그 행(연결·THK)을 쓰고 rad 본문의 같은 ID 행은 버림(중복 요소 오류 대신). 상태 파일에 없고 rad 에만 있는 요소는 rad 행(`STATE_PARTIAL`).
  - 대상 파트 판정(/PART title)·/PROP·/MAT 는 rad 그대로(상태 파일엔 없음).
- Radioss 의미론: Starter 는 같은 ID 의 /NODE·요소 재정의를 허용하지 않는 것으로 알고 있음(**확인 필요 — V-CI-R1 실기 starter 출력**). 그렇다면 Radioss 가 실제로 돈 누적 덱에는 중복이 없고(원래 /NODE·/SHELL 을 빼고 상태 파일을 include), 위 우선 규칙은 **방어 규칙**(편집 중 덱·순서 차이)이다. 실기에서 Radioss 가 중복을 "마지막 우선"으로 받는 것이 확인되면 rad 본문이 상태 파일 **뒤**에서 재정의하는 경우만 결과가 달라지며, 그때는 이 절을 Radioss 순서 규칙으로 바꾼다(변경 메모로).
- 모델 동일성(`esl_core.md` §3.3, 0.5.5)은 규칙 그대로: 노드 ID 집합 + 요소 연결 + 좌표 개략(Kabsch 잔차 ≤ 0.005·bbox). 비교 좌표 = 위에서 정한 `x0`(변형 좌표) ↔ h3d model.csv `x0`(frame0 coords − frame0 disp; 누적 런 frame0 disp ≈ 0). `coord_deviation.coord_source` 에 `rad:state` 를 기록.
- 계산 좌표(K_L·형상·3-2-1·내보내기·view3d) = 이 `x0`(변형 좌표). 설정으로 바꾸지 않는다(U3).

## 5. 두께 (CI-D-5)

- K_L 쉘 두께 = 상태 파일 `/SHELL` THK(변형 두께) — 기존 "요소 카드 두께 > 0 우선" 규칙이 그대로 적용되며, 이제 출처를 기록한다. THK 가 없거나 ≤ 0 이면 /PROP/SHELL Thick(기존 규칙).
- 원두께 t₀ = 대상 파트 `/PROP/SHELL` Thick(없으면 rad 본문 요소 카드 두께, 그것도 없으면 통계 생략).
- 통계 `state.thickness = {source:"state"|"rad", n_elems, t0, ratio:{min,p01,mean,p99,max} (t/t₀), n_changed (|t/t₀−1| > 1 %), max_thinning_pct, elem_max_thinning}`.
- 교차 확인: 초기 상태 EPSP_F 헤더 THK 와 형상 상태 THK 상대차 > 1e-4 인 요소 수를 정보로(`thk_sta_mismatch`).
- 설정 `cumulative.thickness_source: state | prop`(기본 state). `prop` 은 교차검증용(원두께로 K_L).

## 6. 변형률

### 6.1 prev 집계 (CI-D-6)
- 요소별 IPT·IPG 값에서 4가지를 모두 계산: `mid_mean`(중앙 IPT — NPT 홀수 (NPT+1)/2, 짝수 두 중앙 평균, NPT=0 은 그 1층 — 의 IPG 평균), `mid_max`(중앙 IPT 의 IPG 최대), `max`(전체 최대), `mean`(전체 평균).
- 사용 값 = 설정 `cumulative.epsp_agg: auto | mid_mean | mid_max | max | mean`(기본 auto). auto: §6.2 에서 h3d 가 누적값으로 판정되면 **h3d frame0 epsp 와 가장 잘 맞는 집계**(대상 집합 S 에서 `median |h3d0 − agg| / agg` 최소)를 고름 — 기존 지표(h3d Plastic Strain, Mid layer)와 정의 일치. 누적 아님·판정 불가면 `mid_mean`.
- 표시용으로 `max` 는 항상 병기(`prev_max`).

### 6.2 h3d 가 이미 누적값인지 진단 (CI-D-7)
- 입력: prev(사용 집계), h3d frame0 값(`frame0.csv`, §6.5 F0 패스; 없으면 history.csv frame 0 — H 요소만), h3d 최종값(final.csv, 전 요소).
- S = {e : prev(e) > max(`detect.prev_floor` 1e-6, 1e-3·max prev)}. |S| < `detect.min_elems`(10) → 모드 `trivial`(이전 소성 거의 없음 — 누적 = h3d, 증분 = h3d, 경고 없음).
- `r0 = median_{e∈S} h3d0(e)/prev(e)`, `mono = frac_{e∈S}[final(e) ≥ prev(e)·(1−1e-3)]`.
  - `cumulative`: |r0 − 1| ≤ `detect.rel_tol`(0.05) 이고 mono ≥ `detect.mono_frac`(0.99).
  - `incremental`: r0 ≤ `detect.rel_tol`.
  - 그 외 `ambiguous` → 경고 `CUMULATIVE_AMBIGUOUS`(r0·mono·|S|) + **incremental 로 취급**(합이 더 큼 = 보수적).
- 같은 진단을 Plastic Strain(`epsp_mode`)과 Max_Strain ε_eq(`eq_mode`, 비교 대상 prev_eq = §6.3)에 **각각** 적용. 예상: epsp = cumulative(INISHE 로 상태변수 초기화), eq = incremental(총변형률은 상태 형상 기준 0 에서 시작) — 예상과 다르면 정보 메시지.
- 설정 `cumulative.h3d_epsp_mode`·`h3d_eq_mode: auto | cumulative | incremental`(기본 auto) 로 강제 가능(강제 시 진단은 기록만).
- 비누적 씬 안전망: 상태 include 가 없는데 history.csv frame 0 의 epsp 최대 > 1e-6 이면 경고 `CUMULATIVE_STATE_NOT_INCLUDED`("h3d 시작 시점에 소성 변형률이 있음 — 누적 씬이면 rad 에 이전 런 상태 파일 include 필요"). 결과는 바꾸지 않음.

### 6.3 누적·증분 산출 (CI-D-8)
| 지표 | prev 항 | cum(f,e) | inc(f,e) |
|---|---|---|---|
| plastic_strain | prev(e) | mode=cumulative: raw · incremental/ambiguous: prev + raw | cum − prev |
| max_strain (ε_eq) | prev_eq(e) = prev(e) (**Q1 권장안 A**: 이전 소성 = 잔류 변형률 대용) | mode=cumulative: raw · 그 외: prev_eq + raw | cum − prev_eq |
- max-hold 성질은 상수 더하기로 유지된다. trivial 모드는 cum = inc = raw.
- 산출 위치: 코어 `esl/cumulative.py`(순수 함수: `aggregate`, `diagnose`, `series(raw, prev, mode)`), pipeline tstar·validate 가 사용. npz 원본(final/history/strain_frames)은 **h3d 원값 그대로** 저장(재해석 가능), 누적 보정은 읽을 때 적용.

### 6.4 t* 규칙 (누적 씬) (CI-D-9)
- **순위 = cum 최종값**(U2), **first-reach 프레임 = inc 계열**로 계산(`inc[f,e] ≥ inc[F−1,e]·(1−rtol)`): 상수 prev 를 더한 cum 에 rtol 을 걸면 큰 prev 가 작은 증분을 가려 first-reach 가 앞당겨지기 때문.
- **증분이 없는 요소 제외(Q2 권장안 A)**: `inc_final(e) ≤ cumulative.min_increment`(기본 1e-5) 인 요소는 t* 후보·hotspot 에서 제외(이번 낙하에서 늘지 않음 — first-reach 가 frame 0 으로 퇴화). 제외 수는 `tstar.json metrics.<m>.cumulative.n_excluded_no_increment`, 화면에 "이전 손상만(이번 증가 없음) n개".
- hotspot "상승 중"(§7.4) 판정도 inc 계열. 거리 필터·top_k 기존.
- 후보 프레임이 추출 프레임 D 에 없으면(PC 추출본 등 §6.5 미지원) 경고 `CUMULATIVE_FRAME_NOT_EXTRACTED` 후 다음 순위 후보로(기존 `in_D` 처리와 같은 방식). 하나도 없으면 기존 t* 실패 코드.
- `tstar.json`(schema `esl/tstar/2` 유지, 키 추가만): `cumulative:{enabled, epsp_mode, eq_mode, agg, n_prev_elems}`, `metrics.<m>.tstar` 에 `value`(= cum) + `value_inc` + `value_prev`, candidates 행 동일 3값.

### 6.5 TCL 변경 (`resources/tcl/esl_h3d_extract.tcl`, Tcl 8.5 호환 유지)
- request.txt 선택 키(없으면 기존 동작 그대로):
  - `prev_file<TAB><경로>`: CSV `elem_id,prev_epsp,prev_eq`(대상 파트, 워커가 작성 — §15 Worker). 읽어서 dict.
  - `frame0_pass<TAB>1`: **F0 패스** — frame 0, 대상 파트 전 요소, `frame0.csv`(`elem_id,vm_hv,epsp`). 청크 규칙 기존.
  - `cum_min_incr<TAB>1e-5`.
- pass A 순위(prev_file 이 있을 때만): 기존 top hot_k(vm·ep) **∪** "+prev" top hot_k(`vm+prev_eq`, `ep+prev_epsp`, 단 최종 raw > cum_min_incr 인 요소만) → H ≤ 4·hot_k. D = 두 순위 각각의 first-reach 후보(지표별 top_n) 합집합(≤ 4·top_n = 20). 두 순위를 모두 쓰는 이유: TCL 은 §6.2 모드를 모름 — 기존 순위는 "h3d 가 이미 누적"일 때, +prev 순위는 "증분"일 때 정확하다.
- done.json 추가: `cumulative:{prev_file_sha256, prev_n, frame0:true|false, rank_sets:["raw","raw+prev"]}`, `n_frames_D` 증가는 경고 아님.
- progress.log 마커 `frame0.csv: …` / `frame0.csv done: N elements`.
- PC 추출(ESL_extract.bat)은 prev_file 을 만들지 않음 → 기존 순위만, Python 이 §6.4 로 보완·경고. 사용 가이드: 누적 씬은 서버 추출(h3d 또는 압축 h3d 업로드) 권장.

### 6.6 ⑤ 검증·참고 비교 (CI-D-10)
- ESL 하중 F_eq = K_L·u_rel, u_rel 은 **이번 런 변위**(상태 형상 기준) → 자체 솔버 변형률도 증분이다. 따라서 `esl_disp_primary.md` §3.4 변형률 참고 비교(hotspot·최대 요소·P90 오차, 기준 초과 요소)는 **inc 기준**(Q3 권장안 A). 판정(변위 4지표)은 변화 없음.
- `strain_ref` 추가: `basis:"increment"`, `n_plastic_cum`(cum epsp > 0), `n_plastic_inc`(inc epsp > 1e-6), `cum_max`, `inc_max`.

## 7. 산출물 (01_extract 등, 파일 계약)

| 파일 | 내용 |
|---|---|
| `01_extract/state.npz` (누적 씬만) | `elem_id(E,)i8, has(E,)bool, npt(E,)i2, npg(E,)i2, thk_sta(E,)f8, prev_mid_mean, prev_mid_max, prev_max, prev_mean (E,)f8, thk_state(E,)f8, t0(E,)f8, node_from_state(N,)bool` — allow_pickle=False |
| `01_extract/state_summary.json` | `{schema:"esl/state/1", files[], begin, coord:{source, n_nodes_state, n_nodes_rad, n_dup}, elems:{n_state, n_rad, n_dup}, thickness(§5), epsp_init:{n_has, n_missing, max, p99, n_pos, inishe_subs}, diagnosis:{epsp:{mode, r0, mono, n_S, forced}, eq:{...}}, agg, warnings[]}` |
| `01_extract/model_meta.json` | 키 추가 `cumulative: bool`, `state_summary` 경로 |
| `01_extract/frames.json` | `cumulative` 요약(위 diagnosis 축약), `frame0_source: "frame0.csv"|"history"|null` |
| `run.json` | 입력 지문 `includes[]` 에 상태 파일 포함(기존 규칙), `inputs.state_files[]`(경로·sha256·kinds) 추가 |
| `02_tstar/tstar.json`·`candidates.csv`·`hotspots.csv` | §6.4 키·열 추가(`value_inc`, `value_prev`) — 비누적 씬은 열 없음 |
| `05_val/validation.json` | §6.6 `strain_ref` 키 추가 |

- 진단은 extract 단계 끝에서(pack 후, final/frame0 사용) 한 번 하고 state_summary.json 에 기록 → tstar·validate 는 파일만 읽음(단계 재개 규칙).

## 8. 화면·보고서 (Frontend, 2560×1440 기준, 필수 UI 만)

- 새 Case ① 업로드: 파일 선택 `accept` 에 `.sta,.str`. 누락 include 목록에서 상태 파일 행은 배지 "이전 런 상태"(+ 안내 "이전 낙하 해석 폴더의 .sta/.str 를 함께 올리세요").
- Case 상단 배지 "누적 씬"(state_summary 존재 시). 툴팁: 상태 파일 이름·runname.
- ① 추출 결과(검증 탭 위 요약 카드) **"누적 입력"** 카드 1개: 상태 파일 목록(이름·종류·크기), 좌표 출처(상태 n / rad n), 두께 변화 통계(t/t₀ 최소·평균·최대, 변화 >1 % 요소 수, 최대 감육 %·요소 ID), 초기 소성 변형률(최대·P99·양수 요소 수, 집계 방식), h3d 판정(소성: 누적/증분/판정 불확실, 총변형률: 동일, r0·일치 비율 툴팁), 경고 코드 목록.
- ② t\*: 값 표기 `누적 0.123 (이전 0.080 + 이번 0.043)`, 후보 표·hotspot 표에 열 `누적 | 이전 | 이번(증분)`, "이전 손상만(이번 증가 없음) n개 제외" 한 줄. 이력 그래프는 누적 곡선 기본 + 범례 클릭으로 증분 곡선(기존 범례 토글 규칙).
- ⑤ 변형률 카드: 제목 옆 "(이번 낙하 증분 기준)" 표기, 소성 영역 Stat 에 `누적 n / 이번 n`.
- 보고서 HTML(`esl/report/case_report.py`): "누적 낙하 입력" 절(위 카드와 같은 표 + t\* 3값). 비누적 씬은 절 없음.
- 3D 보기(view3d): 좌표가 변형 좌표임을 범례 아래 한 줄("형상: 이전 런 변형 상태"). 기능 변화 없음.

## 9. 업로드·include 검사

### 9.1 확장자 (CI-D-11)
- `UPLOAD_EXT_DEFAULT`, `config/esl_platform*.example.yaml` `upload.allowed_ext`, `scripts/windows/esl_upload_lib.ps1` `$EslResultExt`·`$EslAllowedExt` 에 `.sta`, `.str` 추가.
- 기존 서버 yaml 이 목록을 명시한 경우: setup_config 가 `upload.allowed_ext` 에 `.sta`·`.str` 만 **덧붙임**(다른 항목·순서 불변, 사용자가 일부러 뺀 것과 구분 불가하므로 이 두 확장자에 한해 1회 — 설치 상태 파일 `state/ext_supplement.json` 에 `{"0.8.0":[".sta",".str"]}` 기록, 기록이 있으면 다시 넣지 않음). 백업·콘솔 1줄은 §12 와 같은 방식.
- 업로드 크기 제한·청크 규칙 불변(상태 파일은 수 GB 가능 — 기존 상한 64 GB 안).

### 9.2 complete 검사
- `scan_include_refs` 결과에 상태 파일 표시(`state: true` — §2 ② 확장자 또는 이미 받은 파일이면 ① 헤더). `missing_includes` 는 기존 형식 유지 + 응답 `state_includes:[{rel, kinds, found}]` 추가, 누락 상태 파일은 problems 에 `STATE_INCLUDE_MISSING: 누적 해석 상태 파일 include 가 업로드에 없습니다: <원문>`.
- 상태 파일이 업로드 밖 경로면 기존 "업로드에 포함되지 않은 include" 규칙 그대로(밖 파일 읽지 않음).
- PC 도구 include 수집(`ESL_extract.bat`·`ESL_upload.bat`)은 `#include` 를 이미 따라감 — 확장자 목록만 추가, 상태 파일 크기가 크면 콘솔에 크기 표시.
- 워커 CASE_EXTRACT·OPT_PREP 의 `check_includes`(input_roots 안) 는 상태 파일에도 그대로 적용(변경 없음, 시험만 추가).

## 10. 하위 호환 (CI-D-12)
- 상태 include 가 없는 Case: 파서 결과(§3.2 헤더 규칙 제외 — 기존 정상 입력엔 영향 없음)·TCL 출력(request 키 없음 → frame0.csv 없음, H·D 동일)·npz·tstar.json·validation.json·보고서가 **바이트 단위로 v0.7.2 와 같다**(타임스탬프·버전 문자열 제외). 새 키는 누적 씬에서만 쓴다(빈 키를 넣지 않음).
- `cumulative.enabled: off` 이면 상태 파일을 일반 include 로 취급(§3.2·§4 형상 규칙은 적용 — 그래야 파싱됨, §6 변형률 보정·state.npz 생략). 비교·회귀 조사용.
- 과거 Case·이력·라이브러리 항목은 재계산하지 않는다. 라이브러리 항목은 원 Case 의 `extract_summary.cumulative` 로 "누적 씬" 배지만 표시(새 저장 칸 없음) — 목록 필터는 후속.
- OPT_RUN S1(기존 rad 형상): 기준 Case 가 누적 씬이면 형상 = 변형 좌표임을 S1 검사 결과에 정보 경고 `S1_BASE_CUMULATIVE`(실행은 허용).

## 11. 설정 키 (`config/esl.example.yaml` 코어, 기본값은 `esl/config.py` 한 곳)

```yaml
cumulative:
  enabled: auto            # auto(상태 파일 include 가 있으면 켬) | off(§10)
  thickness_source: state  # state(상태 파일 THK, 기본) | prop(원두께 — 교차검증용)
  epsp_agg: auto           # auto | mid_mean | mid_max | max | mean (§6.1)
  h3d_epsp_mode: auto      # auto | cumulative | incremental (§6.2)
  h3d_eq_mode: auto        # auto | cumulative | incremental
  min_increment: 1.0e-5    # 이번 증분이 이 이하인 요소는 t* 후보 제외 (§6.4, Q2)
  detect: {prev_floor: 1.0e-6, min_elems: 10, rel_tol: 0.05, mono_frac: 0.99}
```
- 좌표 출처는 설정 없음(U3). 플랫폼 설정(`esl_platform.yaml`) 추가 키 없음(§12 는 기존 키를 채움). Case 단위 덮어쓰기는 기존 core 설정 병합 규칙.

## 12. OptiStruct 경로 자동 감지 (U4, `deploy/setup_config.py`, CI-D-13)

- 시점: `plan()`(setup.ps1·update-repo.ps1·install.ps1 공통). 새 설정 파일(예시에서 생성) 은 예시 값이 이미 있으므로 **기존 설정 파일일 때만** 동작.
- 조건·순서:
  1. 최종 설정의 `altair.hw_exe_path` 가 비어 있지 않은 문자열이고 그 파일이 있음 — 아니면 아무것도 안 함(기존 OPT_RUN_HINT).
  2. 후보: hw 실행 파일의 상위 폴더를 최대 6단계 올라가며 `<조상>/hwsolvers/scripts/optistruct.bat` 을 검사, **처음 존재하는 것**(예 `C:/Program Files/Altair/2026.1/hwdesktop/hw/bin/win64/hw.exe` → `C:/Program Files/Altair/2026.1/hwsolvers/scripts/optistruct.bat`; 구형 배치 `<root>/hw/bin/win64/hw.exe` 도 같은 규칙으로 `<root>`). 드라이브 루트에서 멈춤. 경로는 `/` 로 기록(fwd).
  3. `altair.optistruct_path`: 키가 없거나 값이 null·빈 문자열일 때만 후보를 **추가**(기존 값은 파일이 없어도 불변 — 그 경우 기존 503 사유 그대로).
  4. `opt_run.enabled`: 유효한 OptiStruct 경로(3 에서 추가했거나 기존 값의 파일이 있음)가 있을 때만, `opt_run` 섹션이 없으면 `opt_run:` + `enabled: true` 만 추가(나머지 키는 로더 기본값), 섹션은 있는데 `enabled` 키가 없으면 그 키만 추가. **`enabled: false` 가 명시돼 있으면 불변**(사용자 선택) — 안내 1줄만.
  5. 편집은 기존 `set_yaml_value`(주석 `setup이 보충 — v0.8.0 OptiStruct 자동 감지`) + 기존 "편집 결과 검증"(바꾼 키 외 불변, 흐름 표기 등 실패 시 쓰지 않고 수동 안내).
- 백업: 바뀌면 `write()` 가 기존 규칙으로 `<런타임>/_backup/<UTC>/esl_platform.yaml` 복사 후 씀.
- 콘솔 1줄(plan 결과 `opt_autodetect:{added:{key:value}, backup}` → install-common.ps1 이 출력): `비드 최적화 자동 설정: altair.optistruct_path = C:/…/optistruct.bat, opt_run.enabled = true 추가 (백업 …\_backup\<UTC>\esl_platform.yaml)`. 후보가 없으면 기존 OPT_RUN_HINT 에 `(자동 감지: hw 경로 기준 hwsolvers/scripts/optistruct.bat 없음)` 를 덧붙인 1줄.
- 모듈 docstring 의 0.7.2 규칙 문단을 이 규칙으로 갱신, decisions.md 0.7.2 항목은 "0.8.0 에서 완화" 기록.
- 라이선스·실행 가능 여부는 검사하지 않는다(환경 점검 `opt_run ready` 가 기존대로 판단).

## 13. DB
- **변경 없음(migration 없음)**. 누적 정보는 Case 산출물 파일(§7)과 기존 JSON 칸(`cases.extract_summary` — 워커가 extract 결과로 채우는 dict, `validations.strain_ref`)에 둔다. API 는 추가 키로 노출(`CaseOut.extract_summary.cumulative` = state_summary 축약, `ValidationOut.strain_ref` 내부 키) — 스키마 타입은 이미 `dict` 라 openapi 형태 불변. 목록 검색·필터(누적 씬만)가 필요해지면 그때 별도 계약.

## 14. 검증 목록

| ID | 기준 | 종류 |
|---|---|---|
| V-CI-P1 | 이슈 #34 발췌로 만든 fixture(`.str` 패딩 헤더 `/SHELL/         2`·`/TETRA4/        22`, 붙은 /NODE 실수, `.sta` EPSP_F NPT=5·NPG=4 와 NPT=0·NPG=4, 주석 7행, `/INIBRI/STRA_F`·`/INIBRI/FAIL` 뒤따름) → 노드 좌표·THK·EPSP 집계 4종 정확값 | 단위 |
| V-CI-P2 | §3.2 헤더 규칙 도입 후 기존 rad fixture 전부(T-RAD-1~2, legacy_parser 비교) 결과 불변 | 회귀 |
| V-CI-P3 | 공백 구분·붙은 실수 혼합 행, Fortran 지수(`1.0-3`), D 지수, 값 개수 불일치 → STATE_PARSE_ERROR(파일:행), 대상 밖 레코드 형식 오류는 무시 | 단위 |
| V-CI-P4 | 상태 파일 include 순서 4종(앞/뒤 × rad 에 원 /NODE·/SHELL 있음/없음) → 좌표·요소 = 상태 파일, STATE_DUP_DEFINITION 개수, 일부 누락 → STATE_PARTIAL | 단위 |
| V-CI-P5 | §3.6 성능(합성 1 GB .sta, 대상 20 %) 시간·메모리 | 성능 |
| V-CI-P6 | `/BEGIN` 숫자 배율 동일·상이(STATE_UNIT_MISMATCH)·문자열 혼합(비교 생략) | 단위 |
| V-CI-S1 | §6.2 진단: 합성 h3d 가 cumulative(frame0 = prev) / incremental(frame0 = 0) / ambiguous(r0 = 0.5) / trivial(prev = 0) → 모드·경고, 강제 설정 우선 | 단위 |
| V-CI-S2 | §6.1 auto 집계: h3d0 = mid_mean·max 로 합성 → 각각 선택 | 단위 |
| V-CI-S3 | §6.4: 큰 prev + 작은 증분 요소가 cum 순위 1위일 때 t* = 그 요소 inc first-reach(cum rtol 아님), 증분 0 요소 제외 수, D 밖 후보 → CUMULATIVE_FRAME_NOT_EXTRACTED 후 다음 후보 | 단위 |
| V-CI-S4 | ⑤ strain_ref basis=increment, 판정(변위 4지표) 불변 | 단위 |
| V-CI-E1 | 합성 누적 E2E: 1차 런 변형 형상·두께·EPSP 를 상태 파일로 쓰고 2차 런(상태 형상 기준 변위 + raw 변형률) CSV → `run --stage all` → F_eq 자기평형·disp_rms_rel < 1e-8(상태 형상 K_L), t* 누적 기준, state_summary·tstar 키 | E2E |
| V-CI-E2 | 같은 2차 런을 상태 include 없이(원 rad) → CUMULATIVE_STATE_NOT_INCLUDED 경고, 결과는 기존 규칙 | E2E |
| V-CI-B1 | 비누적 fixture 전 단계 산출물 v0.7.2 와 바이트 동일(시간·버전 제외), TCL request 키 없으면 출력 동일(정적 검토) | 회귀 |
| V-CI-T1 | TCL 정적: prev_file 읽기·F0 패스·H/D 합집합, Tcl 8.5 문법(dict·lsort 옵션), request 키 없을 때 분기 없음 | 정적 |
| V-CI-U1 | 업로드 `.sta`·`.str` 허용, 기존 목록 명시 yaml 에 보충 1회(기록 후 재실행 시 재추가 없음, 사용자가 뺀 뒤 재실행 시 재추가 없음) | 단위 |
| V-CI-U2 | complete: 상태 include 누락 → STATE_INCLUDE_MISSING problems + state_includes, 업로드 밖 상태 include → 기존 메시지(밖 파일 미열람) | 단위 |
| V-CI-W1 | 워커 H3D_EXTRACT: 누적 씬이면 prev.csv 작성(대상 요소 수 = parse_rad E)·request 키 3개, 비누적이면 request 불변, check_includes 가 상태 파일에도 적용 | 단위 |
| V-CI-D1 | 자동 감지: hw 2026.1 배치(hwdesktop) / 구형 배치 / 후보 없음 / hw 파일 없음 → 추가 여부 | 단위 |
| V-CI-D2 | 기존 `altair.optistruct_path` 값 있음(파일 없음 포함) → 불변, null·"" → 채움 | 단위 |
| V-CI-D3 | `opt_run` 없음 → `enabled: true` 만 추가·로더 검증 통과, `enabled` 키 없음 → 키만, `enabled: false` → 불변 + 안내 | 단위 |
| V-CI-D4 | 백업 파일 생성·다른 키·주석·BOM·줄 끝 보존, 흐름 표기 설정은 쓰지 않고 수동 안내 | 단위 |
| V-CI-D5 | 콘솔 1줄 문구(plan 결과 `opt_autodetect` → install-common.ps1 출력, PS 5.1·CRLF·BOM) | 정적+단위 |
| V-CI-F1 | 화면: 누적 배지·누적 입력 카드·t* 3값·표 열·⑤ 증분 표기, 비누적 Case 화면 불변(Playwright mock 스냅샷) | UI |
| V-CI-R1 | **실기**(사용자): 이슈 #34 씬(Scene07 Edge23 2nd) — Radioss starter 출력에서 중복 /NODE·요소 처리 확인(§4), 서버 추출 → 모델 동일성 통과(coord_source rad:state), h3d 진단 결과(epsp·eq 모드), t* 3값, 두께 통계 | 실기 |

## 15. 구현 분해 (파일 소유권 — 겹치지 않게)

| 담당 | 파일 | 내용 |
|---|---|---|
| **Core** | `esl/rad/parser.py` | §3.2 헤더, 상태 파일 식별·세그먼트 표시, §4 우선 규칙(노드·요소), INISHE 세그먼트 기록, STATE_INCLUDE_MISSING, `RadModel.state`(dict\|None) |
| Core | `esl/rad/state.py`(신규) | `read_epsp_f`, `/BEGIN` 비교, 두께 통계 |
| Core | `esl/cumulative.py`(신규) | `aggregate`, `diagnose`, `series`, prev.csv 작성 함수(`write_prev_csv(model, path)` — 워커가 호출) |
| Core | `esl/io/results_csv.py` | `frame0.csv`(선택) 읽기 → `frame0.npz`, done.json `cumulative` 통과 |
| Core | `esl/pipeline.py`, `esl/config.py`, `config/esl.example.yaml`, `esl/errors.py` | extract(state.npz·state_summary·진단), tstar(§6.4), validate(§6.6), 설정 키·기본값, 오류 코드 |
| Core | `esl/report/case_report.py` | 보고서 절 |
| Core | `resources/tcl/esl_h3d_extract.tcl`, `resources/tcl/README.md` | §6.5 |
| Core | `tests/rad/test_state_*.py`, `tests/cumulative/*`, `tests/e2e/test_cumulative_e2e.py`, fixture `tests/fixtures/cumulative/` | V-CI-P*, S*, E*, B1, T1 |
| **Backend** | `backend/esl_platform/core/config.py`, `config/esl_platform*.example.yaml` | 확장자 기본값 |
| Backend | `backend/esl_platform/api/services/uploads.py`, core_adapter | §9.2 state_includes·STATE_INCLUDE_MISSING |
| Backend | 워커 결과 등록(extract_summary 에 `cumulative` 축약 복사), OPT S1 검사 | `S1_BASE_CUMULATIVE`, 프런트용 타입 주석(`types.ts` 의 extract_summary 하위 타입) |
| Backend | `backend/tests/test_cumulative_*.py` | V-CI-U1(로더)·U2 |
| **Worker** | `worker/esl_worker/h3d.py`, `worker/esl_worker/executor.py` | 누적 씬 판정(parse_rad 의 state) → `<esl_root>/_h3d/<Case>/prev.csv`(raw 출력 폴더 밖, 재추출 시 _backup), request 키 3개, 입력 지문에 상태 파일 |
| Worker | `worker/tests/test_cumulative_*.py` | V-CI-W1 |
| **Frontend** | `frontend/src/api/types.ts`(openapi 그대로), 새 Case 업로드·누락 include 표, Case 배지, 추출 요약 카드, t* 카드·표, ⑤ 변형률 카드 | §8, V-CI-F1 |
| **Deploy** | `deploy/setup_config.py`, `deploy/install-common.ps1`, `scripts/windows/esl_upload_lib.ps1`, `deploy/tests` 또는 `backend/tests/test_setup_config*.py` | §12, §9.1 보충, V-CI-D*, U1(보충) |
| 메인(통합) | `VERSION` 0.8.0, `CHANGELOG.md`, `docs/manual/user.md`(누적 씬 절·서버 추출 권장), `docs/decisions.md` | 계약 확정 후 |

- 순서: Deploy(§12·§9.1) 독립 → Core 파서(P1~P6) → Core 변형률·TCL → Worker·Backend → Frontend → 실기 V-CI-R1.

## 16. 리스크

| ID | 내용 | 대응 |
|---|---|---|
| R-CI-1 | Radioss 의 중복 정의·include 순서 의미론 미확인(§4) | 방어 규칙 + V-CI-R1 실기 starter 출력으로 확정, 다르면 §4 변경 메모 |
| R-CI-2 | 이전 총변형률이 상태 파일에 없음 → max_strain 누적 = prev epsp 대용(Q1). 탄성 성분·방향(텐서 합 아님 — 스칼라 합) 무시로 누적값 과대/과소 가능 | 화면·보고서에 "근사" 표기, 소성 지표 병기, STRA_F 사용은 후속 |
| R-CI-3 | h3d Plastic Strain(Mid) 이 IPT·IPG 를 어떻게 집계했는지 미확인 → prev 와 단위 불일치 시 누적 판정 ambiguous | §6.1 auto 집계 선택 + ambiguous 는 보수적(합) + 실기에서 집계 고정 |
| R-CI-4 | `.sta` 수 GB — 파싱 시간·업로드 시간 | 대상 파트만 해석(§3.6), 업로드는 기존 프로토콜 2(동시 4·64 MB) |
| R-CI-5 | §3.2 헤더 규칙이 비누적 rad 의 이상 헤더를 새로 받아들임 | 첫 토큰이 `/` 로 끝날 때만, 기존 fixture 회귀(V-CI-P2) |
| R-CI-6 | 자동 감지가 다른 버전 OptiStruct 를 잡음(상위 폴더 탐색) | hw 실행 파일의 조상 폴더로만 한정(같은 설치), 첫 일치, 기존 값 불변, 콘솔 1줄로 경로 공개 |

## 17. 미결 질문 → 가정 확정 (2026-10-29)

- **가정 확정**: Q1 = A(`누적 = ε_eq(이번) + εp(이전)`, 이전 소성 = 잔류), Q2 = A(이번 증분 ≤ `cumulative.min_increment` 1e-5 요소는 t* 후보·hotspot 제외, 개수만 표시), Q3 = A(⑤ 변형률 참고 비교는 증분끼리, 누적은 표시만). 사용자 확인 전 권장안 가정이며 바뀌면 §6.3·§6.4·§6.6 과 변경 메모를 고친다.

- **Q1 총변형률(Max_Strain, 기본 t\* 지표)의 "이전" 값** — `.sta` 에는 이전 런의 소성 변형률(EPSP_F)만 있고 총변형률은 없다(총변형률은 상태 형상 기준 0 에서 다시 시작).
  - A(권장): 이전 소성 변형률을 잔류 변형률로 보고 더함 — `cum = ε_eq(이번) + εp(이전)`. 소성 지표와 같은 기준, 탄성 회복분은 0 으로 봄.
  - B: max_strain 지표는 증분만(누적 합계는 plastic_strain 지표에만 적용). 기본 지표 t\* 가 이전 손상을 무시.
  - C: 이전 런에 `/INISHE/STRA_F`(총변형률) 출력을 요구하고 그 ε_eq 를 더함(없으면 A 로 대체). 해석 덱 변경 필요.
- **Q2 이번 낙하에서 늘지 않은 요소(이전 손상만 있는 요소)** — 누적 순위로는 상위인데 증분 ≈ 0 이면 first-reach 가 frame 0 으로 퇴화한다.
  - A(권장): t\* 후보·hotspot 에서 제외(`min_increment` 1e-5), 개수만 표시.
  - B: 포함(t\* = frame 0 후보가 나올 수 있음 — 사용자가 후보에서 고름).
- **Q3 ⑤ 변형률 참고 비교의 기준** — ESL 변위(u_rel)는 이번 낙하분이라 자체 솔버 변형률은 증분이다.
  - A(권장): Radioss 쪽도 증분으로 비교(누적은 표시만).
  - B: 누적으로 비교(이전 소성이 큰 요소가 모두 "참고 초과" 가 됨 — 판정에는 영향 없음).

## 18. 변경 메모
- (초안 2026-10-29) 작성. 이슈 #34 발췌·main a6587cf 코드 조사 기준.
- (2026-10-29) Q1~Q3 권장안 A 로 가정 확정, 상태 초안 → 확정(가정 확정). 구현 착수.
- (2026-10-29 구현) §8 Case 배지·카드 자료 = `extract_summary.cumulative`(state_summary 축약 + 판정 r0·일치 비율). §9.2 `state_includes[]` 원소에 원문 `spec` 추가, 종류 판정은 파일 앞 4 MB. §10 S1 정보 경고는 s1-check 응답 `warnings[]`. §3.4 값 행 대체 경로: 행 길이가 20 의 배수이고 토큰 수 ≤ 필드 수면 고정폭, 아니면 필드별 Fortran 해석 → 공백 토큰(붙은 실수는 정규식 분리). 대상 밖 레코드는 값이 모자라도 다음 헤더에서 다시 맞춘다(resync).
