# 비드 최적화 서버 실행 — 실기 체크리스트 (v0.7.0)

계약 `docs/contracts/esl_opt_run.md` §14 V-OR-R1·R2. 클라우드 시험은 가짜 OptiStruct(`tests/fake_optistruct.py`)·가짜 후처리로만 돌았으므로,
**OptiStruct·HyperView 가 있는 Windows 서버에서 처음 돌릴 때** 이 순서로 확인한다. 순서: **R1 S2 작은 평판 먼저 → R2 S1 실제 chassis rear(약 22만 요소)**.
결과(통과/실패·메모)는 각 칸 오른쪽에 적어 두고, 고친 설정은 `config/esl_platform.yaml` 에만 반영한다(코드·하드코딩 수정 없음).

## 0. 서버 설정 키 (먼저)

| 키 | 값 / 확인 |
|---|---|
| `altair.optistruct_path` | `…/hwsolvers/scripts/optistruct.bat`(Windows) — 파일이 있어야 `GET /opt/settings` 의 `solver_ready = true`. 없으면 화면 상단 경고 띠·503 `SOLVER_NOT_CONFIGURED` |
| `altair.hw_exe_path` | 후처리(HyperView 배치) — 서버 h3d 추출과 같은 hw.exe |
| `altair.max_concurrent_os` | 동시 OptiStruct 수(라이선스 한도). 기본 1 |
| `commands.os_check` / `os_solve` | `["{optistruct}", "{fem}", "-check", "-tmpdir", "{scratch}"]` / `["{optistruct}", "{fem}", "-nt", "{nt}", "-tmpdir", "{scratch}"]`. 메모리를 지정하려면 `"-len", "{mem_mb}"` 추가 |
| `commands.bead_post` | `["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{post_tcl_fwd}", "-input", "{h3d_fwd}", "-output", "{out_dir_fwd}", "-config", "{request_fwd}"]` |
| `opt_run.enabled` | `true`(섹션이 없으면 꺼짐) |
| `opt_run.solve.nt`·`desmax`·`timeout_h` | 4 · 30 · 12 (R1 은 desmax 10 으로 줄여도 됨) |
| `opt_run.solve.env` | 허용 키 `ALTAIR_LICENSE_PATH`·`ALTAIR_HOME`·`OMP_*` 만. 워커 서비스 계정에 라이선스 환경변수가 없으면 여기 넣는다 |
| `worker.env_passthrough` | 워커 환경에서 자식(OptiStruct)으로 넘길 키(예 `SystemRoot`, `TEMP`, `TMP`, `PATH`) — §3 Windows 참고 |
| `worker.per_job_memory_gb` | `{mem_mb}` = 이 값(없으면 `max_memory_gb`) × 1024 |

- 환경 점검: `python -m esl_platform.check`(또는 관리자 화면) → `altair.optistruct_path`·`esl_bead_post.tcl`·`_templates`·`_opt` 쓰기 OK.
- `GET /esl/api/opt/settings` 응답에서 `enabled: true`, `solver_ready: true`, `solver_reason: null` 확인.

## V-OR-R1 — S2 작은 평판(먼저)

준비: 평판 쉘 메시(예 1000×600 mm, 요소 1~5만, 구멍 2~3개) `.fem` 또는 `.rad`, 그 크기와 맞는 ESL 3개(모드 3종 — 덴팅·뒤틀림·굽힘이 하나씩이면 좋음).

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 1 | 템플릿 등록 | 라이브러리 → 템플릿 → 등록: 검사 오류 0, 크기(L_xi×L_eta)가 CAD 와 ±1 mm | |
| 2 | 평면도·금지 영역 | 새 최적화(S2) ② 카드: 외곽·구멍 위치가 맞고, 자동 구멍(15 mm)·가장자리(10 mm) 빗금이 구멍·외곽을 따라감. 사각형 1개 추가 | |
| 3 | `-check` 종료코드 | `_opt/<id>/solve/` 로그(작업 로그 step 4): `-check` 가 **종료코드 0** 으로 끝나는지. 0 이 아니면 `OS_DECK_INVALID` — `.out` 의 `*** ERROR` 줄(카드 이름)을 확인 | |
| 4 | `.out` 반복 줄 | `solve/esl_bead.out` 에서 반복마다 `ITERATION   n` 줄이 있고(`opt_run.solve.iteration_pattern` 기본 `^\s*ITERATION\s+(\d+)`), 화면 진행률이 n/DESMAX 로 오르는지 | |
| 5 | `.out` 목적값 줄 | `Objective Function … = 값` 줄(기본 `objective_pattern`)이 반복마다 있는지. 대소문자·문구가 다르면 실제 줄을 복사해 `opt_run.solve.objective_pattern` 정규식(값 1개 캡처)으로 덮어씀 | |
| 6 | `.out` 컴플라이언스 표 | 응답 표에 `| id | … | COMPLIANCE | … | … | subcase |` 형식 줄(기본 `compliance_pattern`)이 subcase 마다 있는지 → 결과 '케이스별 C⁰→C' 가 채워짐. 비어 있으면 표 줄을 복사해 `compliance_pattern` 조정 | |
| 7 | 수렴 판정 | 끝에 `OPTIMIZATION HAS CONVERGED`(`converged_patterns`). DESMAX 도달은 실패가 아니라 '미수렴' 경고 | |
| 8 | `_des.h3d` 이름 | `solve/` 에 `esl_bead_des.h3d` 가 생기는지(성공 판정 = 종료코드 0 + `.out` + `<deck>_des.h3d`). 이름이 다르면(버전에 따라 `_des.h3d` 대신 다른 접미) 결과 메모 후 보고 | |
| 9 | 덱 카드 확신도 | `deck/esl_bead.fem` 의 `DTPG`(방향 = 요소 법선, BOUNDS 0~1)·`DOBJREF`(abs: 모든 subcase POS 같은 값)·`DOPTPRM DESMAX`·`OUTPUT,H3D,ALL` 이 오류·경고 없이 받아들여지는지(.out 경고 줄) | |
| 10 | 후처리 Shape Change | 작업 step 5 로그: `esl_bead_post.tcl` 이 `Shape Change` 결과를 찾아 `post/shape.csv`(node_id,dx,dy,dz) 를 씀. `done.json` 의 `shape_type`·`n_nodes` = 템플릿 노드 수. 결과 이름이 다르면 TCL request 의 `shape_type` 로 지정 | |
| 11 | 비드 맵 = HyperView | 상세의 비드 맵과 HyperView 에서 `_des.h3d` Shape Change 컨투어 모양이 같고, **금지 영역(빗금·사각형)에 비드가 없음** | |
| 12 | C⁰ 일치 | 결과 경고에 'OptiStruct 초기 컴플라이언스 … 와 자체 솔버 … 차 > 5 %' 가 없거나 작음(`opt_run.loads.c0_tol`) | |
| 13 | 라이선스 메시지 | 라이선스를 일부러 막고(또는 다른 사용자가 점유 중일 때) 실행 → `.out`/로그의 실제 문구를 기록. `license_patterns` 기본 `license.*(not available|checkout failed|insufficient|exceeded)`·`ALM_\w+_ERROR` 와 맞는지 → 맞으면 '라이선스 대기 n회'(300 초 × 3), 안 맞으면 바로 `OS_SOLVE_FAILED` — 문구를 `license_patterns` 에 추가 | |
| 14 | 취소·트리 종료 | OptiStruct 실행 중 **취소** → 작업 관리자에서 `optistruct.bat` 아래 자식(solver exe·`cmd.exe`)까지 모두 사라지는지 | |
| 15 | 재시도 재사용 | 완료된 실행을 **다시 시도** → OS_SOLVE 가 '재사용(SKIPPED)'으로 바로 넘어감 | |

## V-OR-R2 — S1 실제 chassis rear(약 22만 요소)

준비: 같은 모델(같은 Case 입력 rad 계열) ESL 3~10개, 기준 ESL 의 Case 입력 rad 가 서버에 남아 있어야 함(업로드 폴더·input_roots — 서버는 읽기만).

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 1 | 같은 모델 판정 | 라이브러리 ⓜ 표시·새 최적화 ③ 카드 '같은 모델 ✓'. 다른 버전 모델은 ✗(사유: 노드 ID·요소 연결 다름) | |
| 2 | 대상 준비 | step 1 로그: 대상 파트 노드·요소 수 = Case 의 대상 파트, 반대 법선 요소 수 경고(원 연결 유지 — 위치 확인) | |
| 3 | 하중·선정 시간·메모리 | step 2: 22만 노드 × ESL n 개 초기 컴플라이언스(분해 1회). 소요 시간·워커 메모리 기록, `SOLVER_OUT_OF_MEMORY` 없음 | |
| 4 | 모드 자동 분류 | 라이브러리 '모드' 열을 사람이 판단한 모드와 비교해 오분류 수/전체를 기록(아래 §4 조정) | |
| 5 | OptiStruct 메모리·시간 | step 4: `-len {mem_mb}` 를 쓰는 경우 값이 충분한지(.out 의 메모리 추정 줄), 총 해석 시간, `timeout_h` 12 안 | |
| 6 | 사각형 금지 영역 | PCB 등 사각형 1~2개 → 비드 맵·HyperView 에서 그 안에 비드 없음 | |
| 7 | 비드 반영 메시 | `post/bead_mesh.rad` 를 HyperMesh/Radioss 로 열어 원 노드·요소 ID·PID 유지, 대상 파트 교체로 낙하 해석이 시작되는지 | |
| 8 | 입력 보호 | 실행 전후 Case 입력 폴더·업로드 폴더 파일 변경 없음(수정 시각·크기) | |

## 3. Windows 실행 환경 메모

- `optistruct.bat` 은 **배치 파일**이라 내부에서 `cmd.exe` → solver exe 를 띄운다. 워커는 shell 없이(argv) 실행하고, 취소·시간 초과 때 작업별 Job Object 종료 + `taskkill /T /F` 로 트리 전체를 끈다(R1 #14 로 확인).
- 자식 환경변수는 `worker.env_passthrough` 에 적은 키 + `opt_run.solve.env` 만 넘어간다. `optistruct.bat` 이 `SystemRoot`·`TEMP`·`TMP`·`PATH`·`ALTAIR_HOME` 등을 요구하면 `env_passthrough` 에 추가한다(증상: `-check` 가 바로 종료코드 ≠ 0, `.out` 없음).
- 스크래치 `solve/tmp/`(`-tmpdir {scratch}`)는 다음 실행 때 `_backup` 으로 옮겨진다(삭제 없음) — 디스크 여유 확인.

## 4. 임시 기준값 조정 방법

| 항목 | 키 | 기본 | 조정 |
|---|---|---|---|
| 자동 금지 영역 — 구멍 주변 | `opt_run.keepout.hole_radius_mm` | 15 | 마운트 보스·나사 주변 실제 비드 금지 폭에 맞춤 |
| 자동 금지 영역 — 가장자리 띠 | `opt_run.keepout.edge_band_mm` | 10 | 플랜지·접합부 폭에 맞춤 |
| 결함 루프 무시 | `opt_run.keepout.hole_min_perimeter_mm` | 5 | 메시 결함 작은 구멍이 '구멍'으로 잡히면 올림 |
| 덴팅 판정 — 잔차 비율 | `opt_run.mode.dent_resid_min` | 0.5 | 덴팅이 굽힘/뒤틀림으로 나오면 낮춤 |
| 덴팅 판정 — 국부 집중도 | `opt_run.mode.dent_conc_min` | 0.6 | 넓은 굴곡이 덴팅으로 나오면 올림 |
| 집중도 면적 | `opt_run.mode.dent_area_frac` | 0.05 | 덴트 크기(면적 비)에 맞춤 |
| 분류 불가 기준 | `opt_run.mode.min_energy_rel` | 1e-6 | – |
| 규칙 버전 | `opt_run.mode.rule_version` | 1 | **위 mode 값을 바꾸면 반드시 1 올림** → 자동 분류(auto)만 다시 계산, 사용자 수정은 유지 |

- 바꾼 뒤 백엔드·워커 재시작(`deploy\esl-restart.bat`). 화면의 자동 금지 영역 숫자(설정값)와 평면도 빗금이 새 값으로 바뀌는지 확인.
- 저장된 금지 영역 세트·과거 실행은 영향 없음(실행은 생성 시점 값의 스냅샷).
