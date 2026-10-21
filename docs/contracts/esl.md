# 계약: ESL 플랫폼 (P0)

- 상태: P0 초안 (2026-10-19). 구현 코드 없음. 이 문서가 구현·검증의 원본이다.
- 목적: Radioss 포장 낙하 결과(h3d)에서 대상 파트(기본 `/PART` title `chassis rear`)의 **등가정적하중(ESL)** 을 산출하고, OptiStruct 재해석으로 검증한 뒤 Radioss/OptiStruct 입력으로 내보낸다.
- 벤치마크: `physicsai-platform`(`docs/contracts/platform.md`, `AGENTS.md`)의 패턴(설정 로더, DB 큐 워커, lease, argv 템플릿, 대시보드 세션 인증)을 따르되 **코드는 복사하지 않고** 이 계약대로 새로 구현한다. 아래에서 "PAI §n"은 그 문서의 절을 뜻하며, 차이가 있으면 이 문서가 우선한다.

---

## 1. 범위·단계

### 1.1 처리 흐름

| 단계 | 이름 | 내용 | 실행 |
|---|---|---|---|
| S1 | 입력·추출 | `_0000.rad` 파싱(대상 파트 노드·요소·PROP·MAT), h3d → 프레임별 요소 등가 총변형률, 후보 프레임 노드 변위 | 작업 `CASE_EXTRACT` |
| S2 | t* 탐색 | 시간×요소 max ε_eq → t*, hotspot 요소(ID·좌표), 상위 N 후보 시점 | `CASE_EXTRACT` 마지막 step + 사용자 선택(동기 API) |
| S3 | 강체 제거 | BC 노드 기준 Kabsch 최소제곱 → `u_rel`, BC 잔차 | 작업 `ESL_SOLVE` 첫 step |
| S4 | ESL | OptiStruct 선형정적, 전 노드 강제변위(SPC+SPCD = `u_rel`) → SPCF: 비BC 노드 = `F_eq`, BC 노드 = 지지반력 | `ESL_SOLVE` |
| S5 | 검증 | `F_eq`(FORCE) + BC 고정 재해석 → 변위 RMS, hotspot ε_eq 오차 | 작업 `VALIDATE` |
| S6 | 하중 축약 | 패치별 합력·모멘트 | P3 |
| 출력 | 내보내기 | Radioss `/CLOAD`·`/BCS` inc, OptiStruct `.fem`, CSV, 요약 PPTX | 작업 `EXPORT` |

### 1.2 단계별 범위

| 구분 | 포함 |
|---|---|
| **P1** | 별도 repo·플랫폼 골격(설정·DB·워커·인증·셸 UI), S1·S2, BC 옵션 A(4꼭지점, PCA 자동탐지 + 사용자 수정), S3, S4(선형), S5, 출력 inc·.fem·CSV. 요소: 쉘(`/SHELL`, `/SH3N`). 재료: 선형 탄성 E·ν 추출(§6.1) |
| **P2** | BC 옵션 B(체결점 노드 집합: `/GRNOD` 선택 또는 노드 ID 입력), 요약 PPTX, 솔리드 요소(`/BRICK`, `/TETRA4`), 후보 시점 일괄 ESL |
| **P3** | BC 옵션 C(접지 스프링 CBUSH/CELAS), 비선형 정적 옵션, S6 하중 축약 |

### 1.3 비범위

- 파일 업로드(입력은 서버 측 공유경로 선택만), Radioss 해석 실행·HPC 제출, h3d 이외 결과 포맷, 대상 파트 외 파트의 ESL, 단위 변환(모델 단위계를 그대로 씀).

---

## 2. 설정 스키마 (`config/esl.example.yaml`)

- 실제 파일 `config/esl.yaml`(git 제외) 또는 `ESL_CONFIG` 경로. `ESL_PROFILE`이 `profile`보다 우선. 로더는 `load_config / validate_settings / redacted_settings` 3함수(PAI §14 패턴). 검증 실패 시 쓰기 API 503 `CONFIG_INVALID`.
- **하드코딩 금지 대상**: 실행 파일 경로, TCL 경로, argv, 루트 경로, 포트, 판정 기준값, 파트 title, ID 오프셋. 코드에는 키 이름과 기본값 없는 스키마만.
- 경로에 공백과 `& | < > ^ % ! "` 금지(argv[0] 실행 파일 경로만 공백 허용).

```yaml
schema_version: 1
profile: dev                         # dev | prod
server: {host: 127.0.0.1, port: 8110, base_path: /esl}   # API={base_path}/api, 프런트={base_path}/
database: {url_env: ESL_DATABASE_URL, pool_size: 5}       # 값이 아니라 env 변수명. DB 이름 esl
auth:                                # PAI §5와 동일 키
  mode: dashboard                    # dashboard | dev_static(dev+127.0.0.1만)
  dashboard_internal_url: "http://127.0.0.1:8000"
  dashboard_public_login_url: "/"
  cookie_name: analysis_canvas_session
  introspection_path: /api/auth/me
  projects_path: /api/projects
  cache_ttl_s: 30
  timeout_s: 3
  dev_static_principal: {user_id: dev-admin, username: dev, display_name: 개발자, is_global_admin: true, memberships: []}
storage:
  esl_root: "E:/shared/ESL_WORK"     # 산출물 루트(쓰기). input_roots·spdm_roots와 겹침 금지
  input_roots: []                    # rad·h3d 선택 허용 루트(읽기 전용). 비어 있으면 입력 불가
  spdm_roots: []                     # 겹침 검사용
altair:
  version_label: "2026.1"
  hw_exe_path: "C:/Program Files/Altair/2026.1/hwdesktop/hw/bin/win64/hw.exe"
  optistruct_path: "C:/Program Files/Altair/2026.1/hwsolvers/scripts/optistruct.bat"   # 사내 확인 후 교체
resources:
  h3d_extract_tcl: "D:/esl/resources/esl_h3d_extract.tcl"   # 저장소 밖. Radioss·OptiStruct h3d 공용(§6.2)
commands:                            # argv 템플릿. 허용 placeholder는 §4.4
  h3d_extract: ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{extract_tcl}", "-input", "{h3d_fwd}", "-config", "{request_json_fwd}", "-output", "{out_dir_fwd}"]
  os_solve: ["@cmd_c", "{optistruct}", "{fem}", "-nt", "{nt}", "-out"]   # 사내 확인 후 교체
  log_error_patterns: ['\*\*\* ERROR', 'Traceback \(most recent call last\):', '^\s*\[ERROR\]']
case:
  part_title: "chassis rear"         # 기본 대상 파트. Case별로 덮어쓰기 가능
  part_title_match: exact_ci         # exact | exact_ci (공백·_·- 정규화 후 대소문자 무시)
  rad_include_max_depth: 8
extract:
  strain_tensor: total               # h3d 결과 유형 키(TCL에 전달). 소성 없어도 total 사용
  shell_layer: max                   # max | top | bottom | mid  (max = 층별 ε_eq 중 큰 값)
  invariant: von_mises               # HyperView 불변량 이름(TCL에 전달)
  frame_stride: 1                    # 프레임 간격(1=전부)
  disp_candidate_frames: 5           # S1에서 변위를 뽑을 후보 프레임 수(= tstar.top_n_times)
tstar:
  top_n_times: 5
  top_k_hotspots: 10
  hotspot_min_dist: 20.0             # 모델 길이 단위. hotspot 간 최소 거리
  time_window: [null, null]          # [t_min, t_max] 탐색 구간(null=전체)
  exclude_elem_ids: []               # 특이점 제외용
bc:
  option_default: A                  # A(P1) | B(P2) | C(P3)
  dof: "123"                         # BC 노드 구속 자유도
  corner_radius: 0.0                 # >0이면 꼭지점 노드 주변 반경 내 노드를 BC에 포함
kabsch:
  allow_reflection: false            # det(R)<0 해 금지
  residual_warn_rel: 0.05            # BC 잔차 max / max|u_total| 초과 시 경고
  residual_fail_rel: 0.25            # 초과 시 FAILED(KABSCH_RESIDUAL_HIGH)
esl:
  analysis: linear_static            # linear_static | nonlinear_static(P3)
  bc_node_disp: zero                 # zero | residual  (S4에서 BC 노드 강제변위 값)
  rot_dof: free                      # free(P1 고정값). 회전 자유도 무구속
  material_override: {}              # {mat_id: {E:, nu:}} 파서 미지원 law 보완
  sid: {spc: 100, spcd: 200, force: 300}
  num_format: "{:.9E}"               # .fem·inc 실수 서식
  nt: 4                              # OptiStruct 스레드
validation:                          # 임시 값. 사내 확인 후 교체
  disp_rms_rel_max: 0.01             # RMS(u_os-u_rel)/max|u_rel|
  hotspot_strain_rel_err_max: 0.10   # |ε_os-ε_rad|/ε_rad (t* hotspot 1위)
  hotspot_eval_count: 3              # 오차 표에 보일 hotspot 수
export:
  radioss: {id_offset: 9000000, ramp_time: 1.0e-3, func_mode: ramp}   # ramp | constant
  force_zero_tol_rel: 1.0e-9         # |F|/max|F| 이하 성분은 /CLOAD 생략
  csv: {delimiter: ",", float_format: "{:.9E}"}
units: {label: "mm-ton-s", length: mm, force: N, stress: MPa, time: s}   # 표시용. 변환 없음
worker:                              # PAI §14 worker 키와 동일(limiter, max_logical_cores, max_memory_gb, priority,
  limiter: auto                      #  heartbeat_interval_s, lease_ttl_s, claim_interval_s, cancel_check_interval_s,
  max_logical_cores: 16              #  env_passthrough, state_dir). 실행 시간 한도 키 없음
  max_memory_gb: 32
  priority: below_normal
  heartbeat_interval_s: 10
  lease_ttl_s: 60
  claim_interval_s: 2
  cancel_check_interval_s: 2
  env_passthrough: []
  state_dir: "./state"
ui:
  max_artifact_bytes: 20971520
  max_preview_points: 20000          # BC 화면 2D 산점 최대 점 수
  poll_job_ms: 2000
  poll_queue_ms: 5000
logging: {level: INFO, mask_patterns: ['(?i)(password|passwd|token|secret)\s*[=:]\s*\S+']}
```

---

## 3. 데이터 모델 (PostgreSQL, DB `esl`, Alembic)

공통(PAI §6.1 준용): ID = UUID4 `VARCHAR(36)`, 시간 `TIMESTAMPTZ` UTC·DB 시계, 경로 컬럼 `*_rel`은 Case 폴더 기준 상대경로, **파일 본문·대용량 배열 저장 금지**(경로·sha256·수치 요약만), JSONB는 Pydantic 검증 후 저장, 갱신 행은 `version BIGINT`.

| 테이블 | 주요 컬럼 | 비고 |
|---|---|---|
| `cases` | id, project_id(대시보드, FK 없음), folder_name UNIQUE(`^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$`, 불변), title, status(`ACTIVE`\|`ARCHIVED`), rad_path, h3d_path(원본 절대경로, 표시·감사), input_fingerprint JSONB `{rad:{size,mtime,sha256}, h3d:{size,mtime}, includes:[...]}`, part_title, part_id NULL, extract_summary JSONB NULL `{n_nodes,n_elems,elem_types:{},n_frames,t_end,units_label,mat:[{id,law,E,nu,source}]}`, tstar JSONB NULL `{frame_index,time,elem_id,eps_eq,source:"auto"\|"user"}`, current_bc_set_id, current_esl_run_id, created_by/_name/at, updated_at, version | 1 Case = rad 1 + h3d 1 |
| `bc_sets` | id, case_id FK, option(`A`\|`B`\|`C`), node_ids JSONB(≤ 1000개, 초과는 파일 `03_bc/<id>.json` + count만), dof, auto_suggested BOOL, edited BOOL, params JSONB(`{corner_radius, plane:{origin,e1,e2,n}}`), created_by/at | 불변(수정 = 새 행) |
| `esl_runs` | id, case_id, job_id, frame_index, time, bc_set_id, analysis, kabsch JSONB `{R:[[3x3]], t:[3], rms_res, max_res, max_u_total, res_rel, quality:"OK"\|"WARN"}`, forces JSONB `{n_nodes_loaded, sum_feq:[3], sum_rbc:[3], equilibrium_rel, max_feq:{node_id,mag}}`, dir_rel, status(`READY`\|`FAILED`), inputs_hash(frame+bc_set+설정 해시), created_at | S3+S4 결과 |
| `validations` | id, esl_run_id, job_id, disp_rms_rel, disp_max_rel, hotspots JSONB `[{elem_id, eps_rad, eps_os, rel_err}]`, verdict(`PASS`\|`FAIL`), criteria JSONB(판정 당시 기준값 스냅샷), dir_rel, created_at | S5 |
| `jobs` / `job_steps` | PAI §6.6·§6.7과 같은 컬럼. 차이: `stage` 1~6, `lane` `SLOT`\|`LIGHT`, HPC 관련 컬럼·상태 없음, `case_id`(study_id 대신) | 부분 unique `(case_id, job_type) WHERE 비종료` → 409 `CASE_JOB_BUSY` |
| `artifacts` | id, case_id, job_id, kind(§8), rel, size, sha256, created_at | |
| `notifications` | PAI §13 준용(JOB_STARTED/SUCCEEDED/FAILED) | |
| `worker_slot` / `worker_heartbeats` | PAI §6.10 그대로(단일 슬롯 CAS lease) | |

- **최신성 규칙**: `cases.tstar` 또는 `current_bc_set_id`가 바뀌면 그 이후 단계 결과는 `stale`로 표시(삭제 안 함). 판정 = `esl_runs.inputs_hash ≠ 현재 해시`. `validations`는 소속 run이 stale이면 stale.

### 3.1 폴더 스키마

```text
<esl_root>/<case_folder>/
  case.json                         # {id, project_id, title, rad_path, h3d_path, created_at} 사람용
  01_extract/  model.npz, model_meta.json, frames.json, strain_eq.npz, disp_f<frame>.npz, raw/ (TCL CSV)
  02_tstar/    tstar.json, history.csv, hotspots.csv
  03_bc/       <bc_set_id>.json
  04_esl/<run_id>/   u_rel.npz, u_rel.csv, esl.fem, esl.out, esl.pch, esl.h3d, f_eq.npz, f_eq.csv, reactions_bc.csv
  05_val/<val_id>/   val.fem, val.pch, val.h3d, strain_os.npz, compare.csv
  06_export/<export_id>/  esl_cload.inc, esl_bcs.inc, esl_force.fem, *.csv, (P2) summary.pptx
  logs/<job_id>/step_<NN>_<key>.log
```

입력 파일은 복사하지 않고 읽기만 한다. 사용자 산출물 삭제 금지(덮어쓸 때 `_backup/`으로 이동).

---

## 4. Job / Step 정의·상태 전이

### 4.1 상태 (PAI §7 축소판, HPC 상태 없음)

`QUEUED` → `RUNNING` → `SUCCEEDED` | `FAILED` | `CANCELED` | `INTERRUPTED`(종료 4종 불변, `FAILED`·`INTERRUPTED`는 `failure_code` 필수).

| ID | 전이 | 주체·조건 |
|---|---|---|
| E1 | ∅ → QUEUED | API 작업 생성(사전조건 통과), `queue_seq` 발급 |
| E2 | QUEUED → RUNNING | 워커 claim(SLOT: worker_slot CAS, LIGHT: 동시 1개), lease 발급 |
| E3 | QUEUED → CANCELED | 취소 API |
| E4 | RUNNING → RUNNING | step 진행 갱신 |
| E5 | RUNNING → SUCCEEDED | 마지막 step 성공, lease·슬롯 해제 |
| E6 | RUNNING → FAILED | step 실패 |
| E7 | RUNNING → CANCELED | 취소 플래그 감지 → 프로세스 트리 종료 |
| E8 | RUNNING → INTERRUPTED | 리퍼: lease 만료(`WORKER_LOST`) |

표 밖 전이는 `IllegalTransition`. 실행 시간 한도 없음(timeout 키·코드 없음). 재시도 = 실패 step부터 새 작업(`retry_of_job_id`, `resume_from_step`), 이전 성공 산출물 재사용.

### 4.2 작업 유형

| job_type | stage | lane | steps (key: kind) | 사전조건 |
|---|---|---|---|---|
| `CASE_EXTRACT` | 1 | SLOT | `RAD_PARSE`:INTERNAL → `H3D_STRAIN`:LOCAL(hw) → `STRAIN_PACK`:INTERNAL → `TSTAR_SCAN`:INTERNAL → `H3D_DISP`:LOCAL(hw, 후보 프레임) → `DISP_PACK`:INTERNAL | 입력 fingerprint 확인 |
| `ESL_SOLVE` | 4 | SLOT | `KABSCH`:INTERNAL → `FEM_WRITE`:INTERNAL → `OS_RUN`:LOCAL → `PCH_PARSE`:INTERNAL → `ESL_REGISTER`:INTERNAL | `cases.tstar`, `current_bc_set_id`, 해당 프레임 `disp_f*.npz` |
| `VALIDATE` | 5 | SLOT | `VAL_FEM_WRITE`:INTERNAL → `OS_RUN`:LOCAL → `PCH_PARSE`:INTERNAL → `H3D_STRAIN`:LOCAL(hw, OS h3d) → `VAL_COMPARE`:INTERNAL | READY·비stale `esl_run` |
| `EXPORT` | 6 | LIGHT | `EXP_RADIOSS`:INTERNAL → `EXP_FEM`:INTERNAL → `EXP_CSV`:INTERNAL → (P2)`EXP_PPTX`:INTERNAL | READY `esl_run`(검증 FAIL이어도 허용, 경고 기록) |

- t* 선택·BC 자동탐지·BC 저장은 **동기 API**(파일 읽기·소규모 계산, 쓰기는 `03_bc/`·DB만).
- 사전조건 미충족 → 409 `PREREQUISITE_MISSING` + `missing:[...]`.
- 매 작업 시작 시 입력 fingerprint(size·mtime) 재확인, 다르면 FAILED `INPUT_CHANGED`.

### 4.3 실패 코드

`CONFIG_INVALID`, `INPUT_CHANGED`, `INPUT_INVALID`, `PART_NOT_FOUND`(title 0개), `PART_AMBIGUOUS`(2개 이상), `RAD_PARSE_ERROR`, `UNSUPPORTED_ELEMENT`, `MATERIAL_UNRESOLVED`(E·ν 없음, override 필요), `H3D_MISSING_RESULT`(변위 또는 총변형률 텐서 없음), `ID_MISMATCH`(rad↔h3d 노드·요소 불일치), `KABSCH_DEGENERATE`(BC 노드 3개 미만 또는 공선), `KABSCH_RESIDUAL_HIGH`, `TOOL_EXIT_NONZERO`, `TOOL_LOG_ERROR`, `TOOL_OUTPUT_MISSING`, `PCH_PARSE_ERROR`, `WORKER_LOST`, `CANCELED`.

### 4.4 명령 템플릿(외부 실행)

- 외부 실행은 **워커 LOCAL step만**, `subprocess` `shell=False` argv 배열. argv는 `commands.<key>`에서만 생성.
- argv[0] 허용 placeholder: `{hw}`→`altair.hw_exe_path`, `{optistruct}`→`altair.optistruct_path`, 또는 `@cmd_c` 다음 요소(.bat 실행용). 그 외 argv[0]는 설정 검증 실패.

| 키 | 허용 placeholder | 필수 |
|---|---|---|
| `h3d_extract` | `hw, extract_tcl, h3d, h3d_fwd, request_json, request_json_fwd, out_dir, out_dir_fwd` | 예 |
| `os_solve` | `optistruct, fem, nt, work_dir` | 예 |

- `*_fwd` = `/` 구분 경로(TCL용). 치환값의 제어문자·cmd 메타문자 `& | < > ^ % ! "`(.bat이면 `; , = ( )` 추가) 포함 시 실행 전 거부 `INPUT_INVALID`.
- 성공 판정: 종료코드 0 + `log_error_patterns` 불일치 + 기대 출력 파일 존재. 실행 직전 argv를 `job_steps.command`에 저장(전역 관리자만 조회).

---

## 5. API (접두 `/esl/api`)

공통: PAI §10.1 준용. 오류 `{"detail":{"code","message"(한국어),...}}`. 비GET은 헤더 `X-ESL-Request: 1` 필수(없으면 403 `CSRF_HEADER_REQUIRED`). 권한: 조회 = ACTIVE 로그인 사용자, 실행(Case 생성·작업 등록·t*/BC 저장) = 해당 project `power` 이상, 대기열 순서·남의 작업 취소 = 전역 관리자. 판정 순서 401 → 404 → 403 → 409. 응답에 `lease_*`·세션 토큰 금지. **업로드 엔드포인트 없음**(multipart 라우트 0개).

| 메서드·경로 | 요청 | 응답 | 주요 오류 |
|---|---|---|---|
| `GET /health` | – | `{status:"ok", version}` | |
| `GET /me` | – | `{user_id, username, display_name, is_global_admin, roles:{}}` | |
| `GET /projects` | – | `[{id, name, product_name}]` | 503 `DASHBOARD_UNREACHABLE` |
| `GET /status` | – | `{config:{ok, errors[]}, worker:{online, last_seen_at, limiter}, tools:[{key:"hw"\|"optistruct"\|"extract_tcl", ok}]}` | |
| `GET /queue` | – | `{running: JobSummary?, queued:[JobSummary], light:{running?, queued[]}}` | |
| `POST /paths/inspect` | `{purpose:"RAD"\|"H3D", path}` | RAD: `{normalized_path, ok, problems[], parts:[{id, title, n_elems}], includes:[{path, ok}], units_label?}` / H3D: `{normalized_path, ok, problems[], size, mtime}`. 읽기만 | 422 `PATH_OUTSIDE_ROOT`\|`PATH_UNSAFE`\|`PATH_NOT_FOUND` |
| `GET /cases?project_id=&status=` | – | `Case[]` | |
| `POST /cases` | `{project_id, folder_name, title, rad_path, h3d_path, part_title?}` | `201 Case` (폴더·case.json 생성) | 404 `PROJECT_NOT_FOUND`, 409 `CASE_NAME_EXISTS`\|`FOLDER_EXISTS`, 422 |
| `GET /cases/{id}` | – | `Case` + `stage_status:{1..6:{state:"none"\|"running"\|"done"\|"stale"\|"failed", job_id?}}` | |
| `PATCH /cases/{id}` | `{version, title?, part_title?}` | `Case` (part_title 변경 시 1단계부터 stale) | 409 `VERSION_CONFLICT` |
| `POST /cases/{id}/archive` | – | `Case` | 409 `CASE_HAS_ACTIVE_JOB` |
| `POST /cases/{id}/jobs` | `{job_type, params}` (§5.1) | `201 Job` | 409 `CASE_JOB_BUSY`\|`PREREQUISITE_MISSING`, 422 |
| `GET /jobs/{id}` | – | `Job{…, steps:[{step_no, step_key, state, progress_pct, exit_code, failure_code}]}` | |
| `POST /jobs/{id}/cancel` / `/retry` | – | `Job` | 409 `JOB_TERMINAL` |
| `GET /jobs/{id}/log?step=&cursor=` | – | `{lines[], next_cursor, eof}` | |
| `GET /cases/{id}/tstar` | – | `{selected:{frame_index,time,elem_id,eps_eq,source}, candidates:[{rank, frame_index, time, eps_max, elem_id}], hotspots:[{rank, elem_id, eps_eq, centroid:[x,y,z]}], history:{time[], eps_max[]}}` (history ≤ 2000점 간축) | 409 `PREREQUISITE_MISSING` |
| `PUT /cases/{id}/tstar` | `{version, frame_index}` (후보 목록 안의 프레임만) | `Case` | 422 `FRAME_NOT_CANDIDATE` |
| `GET /cases/{id}/preview` | `?frame_index=` | `{plane:{origin,e1,e2,n}, points:[[node_id, a, b, value]], decimated:bool}` (PCA 평면 좌표, value = 해당 프레임 |u|, ≤ `ui.max_preview_points`) | |
| `POST /cases/{id}/bc-sets/suggest` | `{option:"A", corner_radius?}` | `{node_ids:[4], coords:[[x,y,z]], plane:{…}, expanded_node_count}` (저장 안 함) | |
| `POST /cases/{id}/bc-sets` | `{option, node_ids[], dof?, corner_radius?}` | `201 BcSet` + `cases.current_bc_set_id` 갱신 | 422 `NODE_NOT_IN_PART`, `KABSCH_DEGENERATE`(사전검사) |
| `GET /cases/{id}/bc-sets` | – | `BcSet[]` | |
| `GET /cases/{id}/esl-runs` / `GET /esl-runs/{id}` | – | `EslRun{…, stale}` | |
| `GET /esl-runs/{id}/forces?top=50` | – | `{rows:[{node_id, x,y,z, fx,fy,fz, mag, is_bc}]}` (크기 내림차순) | |
| `GET /validations/{id}` | – | `Validation{…, stale}` | |
| `GET /cases/{id}/artifacts` / `GET /artifacts/{id}/download` | – | 목록 `{id, kind, rel, size}` / 파일 스트림(≤ `ui.max_artifact_bytes`, 초과 413 `ARTIFACT_TOO_LARGE`; 경로 표시 + 복사로 대체) | |

### 5.1 작업 params

| job_type | params |
|---|---|
| `CASE_EXTRACT` | `{}` (설정 `extract.*`·`tstar.*` 스냅샷을 `jobs.params.settings`에 저장) |
| `ESL_SOLVE` | `{frame_index?(기본 cases.tstar), bc_set_id?(기본 current), material_override?:{mat_id:{E,nu}}}` |
| `VALIDATE` | `{esl_run_id}` |
| `EXPORT` | `{esl_run_id, targets:["radioss_inc","fem","csv"(,"pptx")]}` |

---

## 6. 중간 파일 포맷·규약

### 6.1 포맷 원칙

- 배열 = **`.npz`**(`numpy.savez_compressed`, 숫자 dtype만, 저장·로드 모두 `allow_pickle=False` 강제). 객체 배열 금지. 메타 = 같은 이름 `.json`(UTF-8). **pickle 금지**.
- 대안(정책상 npz 불가 시): 같은 배열을 `.npy`(allow_pickle=False) 개별 파일 또는 CSV로. 키 이름·shape 계약은 동일하게 유지 → 리더 1곳만 교체.
- TCL 출력(HyperView 원시)은 CSV(`raw/`), INTERNAL `*_PACK` step이 npz로 변환. 모든 npz는 `meta.json`에 `{schema:"esl/<name>/1", units_label, source_sha256?, created_at}`.

### 6.2 HyperView 추출 인터페이스 (`h3d_extract`)

- 입력 `request.json`: `{mode:"strain"|"disp", part:{id, title}, frames:"all"|[idx...], stride, strain_tensor, shell_layer, invariant, subcase?}`. Radioss h3d와 OptiStruct h3d에 같은 TCL·같은 불변량을 쓴다(정의 일치).
- 출력(`out_dir`):
  - `frames.csv`: `frame_index,time`
  - `strain.csv`(mode=strain): `frame_index,elem_id,eps_eq` (shell_layer 적용 후 값)
  - `disp_f<idx>.csv`(mode=disp): `node_id,ux,uy,uz`
  - `model.csv`(첫 실행만): `node_id,x0,y0,z0` (대상 파트 노드 초기좌표)
  - `done.json`: `{ok:true, n_frames, n_elems, n_nodes, warnings[]}`. 없으면 `TOOL_OUTPUT_MISSING`.

### 6.3 npz 키

| 파일 | 키(shape, dtype) |
|---|---|
| `model.npz` | `node_id(N,)i8`, `x0(N,3)f8`, `elem_id(E,)i8`, `elem_type(E,)i1`(3=TRIA,4=QUAD), `conn(E,4)i8`(TRIA는 4번째 -1), `elem_pid(E,)i8`, `thickness(E,)f8`, `elem_mid(E,)i8` |
| `model_meta.json` | `{part_id, part_title, n_nodes, n_elems, mats:[{id, law, E, nu, rho?, source:"rad"\|"override"}], props:[{id, type, t}], includes:[...]}` |
| `strain_eq.npz` | `time(F,)f8`, `frame_index(F,)i4`, `elem_id(E,)i8`, `eps_eq(F,E)f4` |
| `disp_f<idx>.npz` | `node_id(N,)i8`, `u(N,3)f8`, `time()f8` |
| `u_rel.npz` | `node_id(N,)i8`, `u_rel(N,3)f8`, `u_total(N,3)f8`, `R(3,3)f8`, `t(3,)f8`, `bc_node_id(B,)i8`, `bc_residual(B,3)f8` |
| `f_eq.npz` | `node_id(N,)i8`, `f(N,3)f8`, `is_bc(N,)?`(bool) — 비BC 행 = F_eq, BC 행 = 지지반력 |
| `strain_os.npz` | `elem_id(E,)i8`, `eps_eq(E,)f4` |

### 6.4 S2 t* 규약

- `m(f) = max_e eps_eq[f,e]` (time_window·exclude 적용). `t* = time[argmax m]`, 동률은 이른 프레임.
- 후보 시점: `m(f)`의 국소 최대 중 상위 `top_n_times`(t* 포함, rank 1 = t*).
- hotspot: t*에서 ε_eq 내림차순, 요소 중심(초기좌표 기준) 간 거리 ≥ `hotspot_min_dist`로 거르며 상위 `top_k_hotspots`.
- `history.csv`: `time,eps_max,eps_hotspot1`.

### 6.5 좌표계·단위·부호

- 좌표계: Radioss 전역 직교좌표(skew 미적용 기본계). 모든 벡터는 전역계 성분.
- 단위: 모델 단위계 그대로(rad `/BEGIN` 입력 단위를 `units_label`로 기록만, 변환 없음). 기본 표시 mm-ton-s → 힘 N, 응력 MPa.
- 변위: `u = x(t) − X0`(h3d 변위 그대로).
- **S3 Kabsch**: BC 노드 집합 B에 대해 `min_{R∈SO(3), t} Σ_{i∈B} |R·X0_i + t − x_i|²` (x = X0 + u). 중심화 + SVD, `det(R)<0`이면 부호 보정(`allow_reflection=false`).
  - `u_rel_i = Rᵀ(x_i − t) − X0_i` (초기 형상 기준계로 되돌린 변형 변위).
  - BC 잔차 = `u_rel_i, i∈B`. 품질: `rms_res`, `max_res`, `res_rel = max_res / max_i|u_total_i|`. `> residual_warn_rel` 경고, `> residual_fail_rel` 실패.
  - |B| < 3 또는 B 공선(특이값 비 < 1e-9) → `KABSCH_DEGENERATE`.
- 힘 부호: `F_eq` = 구조물에 **가해지는 외력**(OptiStruct SPCF 부호 그대로 = 구속이 구조물에 작용하는 힘). 따라서 S5 FORCE 값 = SPCF 값 그대로. 평형 검사 `|ΣF_eq + ΣR_bc| / Σ|F| ≤ 1e-6`.
- 회전 자유도: 추출·구속·하중 모두 병진 3성분만(P1). 쉘 회전은 S4·S5 모두 자유.

### 6.6 BC 옵션 A 자동탐지

- 대상 파트 노드 초기좌표의 PCA: 평균 o, 주축 e1,e2(면내), n=e3.
- 투영 a=(X−o)·e1, b=(X−o)·e2 를 각 범위로 정규화(â, b̂ ∈ [−1,1]). 4꼭지점 = `argmax(s1·â + s2·b̂)`, (s1,s2)∈{(+,+),(+,−),(−,+),(−,−)}. 중복 노드면 차순위.
- `corner_radius > 0`이면 각 꼭지점 반경 내 노드 포함. 사용자는 노드 ID를 직접 수정(파트 소속 검사).

---

## 7. OptiStruct 덱 템플릿 규약

- 생성: Python INTERNAL step(Jinja 등 템플릿 엔진 없이 고정 규칙). 자유형식(콤마) 카드, 실수는 `esl.num_format`. 대상 파트만 포함(인접 파트 제외).
- 노드·요소·PID·MID는 **Radioss ID 그대로** 사용(추적성). 충돌 없음(단일 파트).

### 7.1 공통 bulk

```text
GRID,<nid>,,<x0>,<y0>,<z0>
CQUAD4,<eid>,<pid>,<n1>,<n2>,<n3>,<n4>      | CTRIA3,<eid>,<pid>,<n1>,<n2>,<n3>
PSHELL,<pid>,<mid>,<t>,<mid>,,<mid>
MAT1,<mid>,<E>,,<nu>
```
- 요소별 두께가 다르면 PID를 (원PID, 두께) 조합별로 새로 매김 → 매핑을 `model_meta.json`에 기록. 솔리드는 P2(CHEXA/CTETRA + PSOLID).

### 7.2 S4 ESL 덱 (`esl.fem`)

```text
$ ESL S4  case=<case_id> run=<run_id> frame=<idx> time=<t*>
SUBCASE 1
  LABEL ESL_ENFORCED
  SPC = 100
  LOAD = 200
  DISPLACEMENT(PUNCH,H3D) = ALL
  SPCFORCE(PUNCH,H3D) = ALL
  STRAIN(H3D) = ALL
BEGIN BULK
SPC1,100,123,<nid...>            $ 전 노드(BC 포함) 병진 구속, 8개/줄 + continuation
SPCD,200,<nid>,1,<u_rel_x>       $ 비BC 노드: 성분 1,2,3 각각 1줄(0인 성분도 기록)
SPCD,200,<nid>,2,<u_rel_y>
SPCD,200,<nid>,3,<u_rel_z>
$ BC 노드: bc_node_disp=zero → SPCD 없음(0 구속) / residual → 잔차를 SPCD로
<공통 bulk>
ENDDATA
```
- SID는 `esl.sid.*`. 출력 해석: `.pch` `$SPCF` 블록 → 노드별 (T1,T2,T3). 비BC = `F_eq`, BC = 지지반력.

### 7.3 S5 검증 덱 (`val.fem`)

```text
SUBCASE 1
  LABEL ESL_VERIFY
  SPC = 100
  LOAD = 300
  DISPLACEMENT(PUNCH,H3D) = ALL
  SPCFORCE(PUNCH) = ALL
  STRAIN(H3D) = ALL
BEGIN BULK
SPC1,100,<bc.dof>,<bc nid...>
FORCE,300,<nid>,0,1.0,<fx>,<fy>,<fz>   $ 비BC 노드, |F| ≤ force_zero_tol_rel·max|F| 은 생략
<공통 bulk>
ENDDATA
```
- `.pch` `$DISPLACEMENTS` → `u_os`. ε_eq는 `val.h3d`를 §6.2 TCL(mode=strain, 같은 layer·invariant)로 추출.
- PUNCH 파서: 고정 80칸 small-field, `$TITLE/$LABEL/$<블록명>` 헤더, `-CONT-` 연속행. 미지원 블록은 무시. 형식 오류 `PCH_PARSE_ERROR`.

---

## 8. 출력 포맷 (`06_export/<export_id>/`)

| 파일 | 규약 |
|---|---|
| `esl_cload.inc` | Radioss 블록 포맷. `/FUNCT/<off+1>`(ramp: (0,0)→(ramp_time,1)→(1e30,1); constant: (0,1)→(1e30,1)). 비BC 노드마다 `/GRNOD/NODE/<off+1000+k>` 1개(노드 1개) + 0 아닌 성분별 `/CLOAD/<id>`(`fct_ID=off+1, Dir=X\|Y\|Z, skew=0, sens=0, grnd_ID`, `Ascale_x=1, Fscale_y=F 성분`). 헤더 주석에 case·run·t*·단위·ID 범위 |
| `esl_bcs.inc` | `/GRNOD/NODE/<off+2>` BC 노드 + `/BCS/<off+3>`: `Tx Ty Tz = bc.dof 반영 (예 111), Ωx Ωy Ωz = 000`, skew 0 |
| `esl_force.fem` | §7.3 S5 덱과 동일한 FORCE+SPC bulk(자체 실행 가능 단일 파일) |
| `f_eq.csv` | `node_id,x0,y0,z0,fx,fy,fz,mag,is_bc` (BC 행 = 지지반력) |
| `u_rel.csv` | `node_id,ux,uy,uz,ux_total,uy_total,uz_total` |
| `reactions_bc.csv` | `node_id,rx,ry,rz` + 마지막 `SUM` 행 |
| `tstar_candidates.csv`, `hotspots.csv` | §6.4 |
| `validation.csv` | `metric,value,criterion,pass` + hotspot 행 `elem_id,eps_rad,eps_os,rel_err` |
| `summary.pptx`(P2) | 표지·입력·t* 이력·BC·F_eq 상위·검증 표 6장 |

- ID 규칙: 모든 생성 ID ∈ `[id_offset, id_offset+999999]`. 범위가 rad의 기존 ID와 겹치면 EXPORT 실패 `ID_RANGE_COLLISION`(RAD_PARSE에서 수집한 최대 ID 비교).
- CSV: UTF-8(BOM 없음), 헤더 1줄, `export.csv` 서식.

---

## 9. UI 단계별 필수 요소

- 라우팅: `/esl/`(프로젝트 선택) → `/esl/p/:projectId`(Case 목록 + "새 Case") → `/esl/p/:projectId/c/:caseId/stage/:n`(n=1~6). React 18 + Vite 5 + TS, UI 킷 없음.
- 레이아웃: 상단 바(경로 `ESL > 프로젝트 > Case > 단계`, 사용자·역할, "대시보드로" `href="/"`), 6단계 스텝퍼(상태 점: 없음/실행/완료/stale/실패), 본문 + 우측 패널(대기열·워커 상태). 한국어 문구.
- 원칙: **단계당 주 버튼 1개**, 선택 입력은 "고급"(기본 닫힘), 권한 없으면 버튼 비활성 + 툴팁. stale 단계는 배너 "이전 단계가 바뀌었습니다 — 다시 실행".

| 단계 | 필수 입력·표시 | 주 버튼 |
|---|---|---|
| ① 입력 | rad 경로·h3d 경로(텍스트 + "확인" → inspect 요약: 파트 목록에서 대상 파트 강조, include 상태), 파트 title(기본값). 결과: 노드·요소 수, 프레임 수, 재료 E·ν | 추출 실행 |
| ② t*·hotspot | ε_max–시간 곡선(t* 표시), 후보 시점 표(선택 라디오), hotspot 표(요소 ID·ε_eq·좌표) | t* 확정 |
| ③ BC | PCA 평면 2D 산점(값 = |u|), 꼭지점 4개 표시·노드 ID 입력칸 4개(자동탐지값 채움). 고급: corner_radius, 옵션 B(P2) | BC 저장 |
| ④ ESL | 사용 t*·BC 요약, Kabsch 품질(잔차 RMS/max, OK·WARN 배지), 결과: ΣF_eq, ΣR_bc, 평형 오차, F_eq 상위 노드 표. 고급: 재료 override | ESL 계산 |
| ⑤ 검증 | 변위 RMS(상대)·hotspot ε_eq 오차 표, 기준값과 PASS/FAIL 배지 | 검증 실행 |
| ⑥ 내보내기 | 대상 체크(inc·fem·csv), 결과 폴더 경로(복사 버튼), 파일 목록·다운로드(크기 제한 내) | 내보내기 |

---

## 10. 검증 기준과 테스트 목록 (Verifier)

완료 = `scripts/test-all`이 Linux(Altair 없음, PG 있음)에서 통과 + 아래 항목별 자동 시험 이름 또는 수동 증적. Altair 의존 동작은 가짜 도구(`backend/tests/fake_tools/fake_hw`, `fake_optistruct`: 고정 fixture CSV·PCH·h3d 더미를 출력, 종료코드·로그 오류 시나리오 지원)로 시험. Windows 전용 skip은 "미수행 → 사용자 E2E".

| ID | 기준 | 방법 |
|---|---|---|
| V-CFG-1 | 예시 설정 로드·검증 통과, 필수 키 누락·잘못된 placeholder·argv[0] 위반·루트 겹침 → `CONFIG_INVALID` | 단위 |
| V-CFG-2 | 정적: 코드에 `Program Files`, `.exe`/`.bat` 리터럴 경로, 판정 기준 숫자 리터럴(§2 키 대상) 없음 | 정적 |
| V-SEC-1 | 정적: `shell=True`, `os.system`, `pickle`, `allow_pickle=True` 0건 | 정적 |
| V-SEC-2 | 라우트 중 multipart/`UploadFile` 0개, input_roots 밖·`..`·메타문자 경로 422 | 정적·API |
| V-AUTH-1~4 | PAI V-AUTH-1~4와 동일 기준(가짜 대시보드, 캐시, 권한 표, `X-ESL-Request`) | API |
| V-DB-1~3 | alembic upgrade 성공, CHECK 위반 거부, 같은 Case·job_type 비종료 2개 → 409 | PG |
| V-SM-1 | §4.1 E1~E8 허용, 그 외 `IllegalTransition` | 표 기반 |
| V-LS-1~3 | lease 만료 → INTERRUPTED, 동시 claim 승자 1, lease_token 비노출 | PG |
| V-CMD-1 | `h3d_extract`·`os_solve` 펼침 결과가 기대 argv와 일치, 메타문자 치환값 거부 | 단위 |
| V-RAD-1 | fixture rad(include 2단, /PART 3개, 대소문자·공백 다른 title)에서 part_id 해석, `PART_NOT_FOUND`/`PART_AMBIGUOUS` | 단위 |
| V-RAD-2 | /NODE·/SHELL·/SH3N·/PROP/SHELL·/MAT(LAW1, LAW2, LAW36) 파싱값 일치, 미지원 law → `MATERIAL_UNRESOLVED`, override로 해소 | 단위 |
| V-EXT-1 | fake_hw CSV → npz 변환 shape·dtype·키 일치, 로드는 allow_pickle=False, `done.json` 없으면 `TOOL_OUTPUT_MISSING` | 가짜 |
| V-TS-1 | 합성 eps(F×E, 알려진 최대·국소최대)에서 t*, 후보 rank, hotspot 최소거리 필터 결과 일치 | 단위 |
| V-BC-1 | 회전·이동된 직사각 판 메시에서 자동 꼭지점 = 실제 4꼭지점, corner_radius 확장 수 | 단위 |
| V-KB-1 | 임의 강체(R,t) + 알려진 변형장 적용 → `u_rel` 복원 오차 < 1e-9·max|u|, 순수 강체면 잔차 ≈ 0 | 단위 |
| V-KB-2 | 반사 해 방지(det R = +1), 3점 미만·공선 → `KABSCH_DEGENERATE`, 잔차 임계 경고/실패 | 단위 |
| V-FEM-1 | S4 덱 골든 파일 일치: SPC1 노드 수 = N, SPCD 줄 수 = 3·(N−B)(zero 모드), SID·서식 | 골든 |
| V-FEM-2 | S5 덱: FORCE 노드 = 비BC 중 비영, BC SPC dof, 두께별 PID 분리 | 골든 |
| V-PCH-1 | fixture .pch에서 SPCF·DISP 파싱(continuation 포함), 손상 파일 → `PCH_PARSE_ERROR` | 단위 |
| V-EQ-1 | fixture SPCF에서 평형 오차 계산·기록, 부호 규약(§6.5) 확인 | 단위 |
| V-VAL-1 | 지표 계산: disp_rms_rel, hotspot rel_err, 기준값 스냅샷으로 PASS/FAIL | 단위 |
| V-EXP-1 | inc 골든: /CLOAD 수 = 비영 성분 수, ID 범위·`ID_RANGE_COLLISION`, /BCS 플래그, CSV 헤더 | 골든 |
| V-STALE-1 | t* 또는 BC 변경 후 esl_run·validation stale 표시, ESL_SOLVE 사전조건 | API |
| V-UI-1 | 6단계 라우트, 단계당 주 버튼 1개, 권한 없는 사용자 비활성, stale 배너 | 프런트 시험 |
| V-E2E-1 | (Windows, 사용자) 실제 rad+h3d로 ①~⑥ 완주. 기대: S5 `disp_rms_rel` ≈ 0(선형 일관성 — 1e-6 수준), hotspot 오차는 보고값(판정은 설정 기준) | 수동 증적 |

- 해석 의미: S5 변위 RMS는 **선형 왕복의 수치 일관성** 검사(이론상 0)이고, 물리적 등가성은 hotspot ε_eq 오차(선형 정적 vs Radioss 동적·비선형)로 판단한다.

---

## 11. 리스크·미결

| ID | 내용 | 대응 |
|---|---|---|
| R1 | HyperView 결과 유형·불변량 이름(총변형률 텐서, shell layer, von Mises 정의)이 Radioss h3d와 OptiStruct h3d에서 다를 수 있음 | 같은 TCL로 양쪽 추출, 이름은 설정. 실제 h3d로 E2E 전 확인(미결 Q1) |
| R2 | Radioss h3d에 총변형률 텐서 출력이 없을 수 있음(`/H3D/SHELL/TENS/STRAIN` 등 요청 필요) | `H3D_MISSING_RESULT` 안내 문구에 필요한 출력 카드 명시 |
| R3 | rad 파서 범위(블록 포맷, 고정 열, /INCLUDE, 재료 law 다양성) | P1은 쉘 + LAW1/2/36 + override. 미지원은 명확한 실패 |
| R4 | 4꼭지점 단일 노드 고정 → 국부 반력 집중, 꼭지점 부근 hotspot 왜곡 | corner_radius, 옵션 B(P2) |
| R5 | 소성·접촉·관성 영향으로 선형 ESL의 hotspot 오차 큼 | 오차를 지표로 보고, 비선형 옵션 P3 |
| R6 | 전 노드 /CLOAD 개수가 수만 개 → Radioss 입력 비대 | P3 S6 축약, P1은 비영 성분만 |
| R7 | OptiStruct 실행 래퍼(.bat 경로·인자·라이선스 대기) 미확인 | `os_solve` 템플릿 "사내 확인 후 교체" |
| R8 | 대시보드 측 `/esl/` 링크 등록·리버스 프록시 설정은 이 저장소 밖 | PAI §20과 같은 방식으로 요청 |

미결 질문:
- Q1. 판정 기준값(`disp_rms_rel_max`, `hotspot_strain_rel_err_max`)과 ε_eq 층 정의(max/top/bottom) 사내 기준.
- Q2. `esl.bc_node_disp` 기본값 zero(잔차 무시) vs residual(잔차를 강제변위로) — 지지반력 해석 관행.
- Q3. 요약 PPTX를 P2로 미룬 것 확정 여부(P1 필요 시 python-pptx 의존성 추가).
