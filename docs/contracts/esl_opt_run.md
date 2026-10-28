# 계약: 비드 최적화 서버 실행 (OPT_RUN, v0.7.0)

- 상태: **확정** (2026-10-28, 사용자 확정 Q1~Q5 반영 — §17). 남은 미결 2개(§18)는 구현 전에 답을 받는다. 구현 코드 없음.
- 버전: **v0.7.0** (v0.6.0은 `esl_upload_speed.md`가 사용).
- 대체 범위: `esl_p2_library.md` §4 "실행은 사용자 측(Windows/HPC)… 결과 회수·후처리는 P3", `esl_p3_ux.md` §7 "OptiStruct 비드 덱 실행은 P4" 중 **서버 워커 실행** 부분. HPC/PBS 제출은 여전히 범위 밖. 충돌 시 이 문서 우선. 종합분석(LIB_ANALYZE)의 덱 생성은 **그대로 유지**(PC에서 직접 돌리는 사용자용).
- ID 규칙: 결정 `OR-D-n`, 요구 `OR-n`, 시험 `V-OR-n`, 리스크 `R-OR-n`.
- 사용자 확정 사항(2026-10-28, 변경 금지):
  1. 라이브러리에서 ESL 여러 개를 골라 비드 최적화에 넣는다(라이브러리·종합분석 화면 연결).
  2. 서버 워커에서 직접 실행(OPT_RUN, 기존 워커·작업 대기열 재사용, 사용자 PC 실행 아님).
  3. 시나리오 2개: **S1 기존 rad 형상 최적화**(케이스 대상 파트, 하중 노드 직접 적용, 같은 모델 ESL만), **S2 템플릿 최적화**(등록 템플릿 메시, 같은 크기 ESL, 정규화 좌표 (ξ,η) 24×14 셀 합력·합모멘트 매핑).
  4. S2 템플릿: `.fem` 또는 `.rad` 쉘 메시 등록(기존 청크 업로드), 모든 사용자에게 공개, 삭제는 등록자·관리자만, 실행이 참조 중이면 보관(soft delete). CAD/STEP 은 후속(§16).
  5. 크기(인치/치수)가 다른 ESL은 S2에서 사용 불가: 같은 인치 + 치수 ESL 간 ±2 %, 템플릿과 ±5 %. S1은 모델 동일성 판정으로 대체.
  6. 비드 방향 = 지금 덱과 같음(요소 법선 = +n 쪽, BOUNDS 0~1).
  7. 결과는 라이브러리에 넣지 않고 "최적화 실행" 목록에 보존.
  8. 라이선스 부족 = 3회 × 300 초 자동 재시도 후 실패.
  9. 저장소의 DTPG 덱 생성 코드(`esl/library/optdeck.py`)를 서버 실행으로 연결.
  10. UI 필수 버튼만, 2560×1440 기준(1920×1080 잘림 없음). 환경별 경로·솔버 경로는 설정 파일, 하드코딩 금지. **입력 폴더 쓰기 금지**.

## 0. 현황 조사 (main f44c2c5, v0.5.9)

| 항목 | 위치 | 현재 동작 |
|---|---|---|
| DTPG 덱 생성 | `esl/library/optdeck.py write(target_mesh, load_cases, support_321, design, out_dir)` | `.fem`(GRID/CQUAD4/CTRIA3/PSHELL/MAT1 + SUBCASE별 FORCE·SPC1 + DTPG + DRESP1 COMP + DESOBJ(MINMAX)/DOBJREF 또는 WCOMP) + `esl_loads.inc` + `run_optistruct.bat` + README. DTPG 방향 = 요소 법선(NORM 없음), `bounds [0,1]`, SKIP=BC 고정. **DOPTPRM·OUTPUT 카드 없음**. 3-2-1 rank 검사(`SUPPORT_DEGENERATE`). OptiStruct 실행 검증 이력 없음(확신도 표기) |
| 덱 실행 흐름 | `worker/esl_worker/core_adapter.py _lib_optdeck` | LIB_ANALYZE 의 OPTDECK step 이 `_analysis/<id>/opt/` 에 덱만 쓴다. **실행·회수 없음** |
| 대상 메시 | `esl/library/analysis.py run(entries, target)` | 대상 = 라이브러리 항목(`LibraryEntry`). 대상과 `mesh_sha256`(node_id·x0·conn·elem_type 해시 — **좌표 포함**)이 같은 항목만 원본 F_eq 직접, 나머지는 셀 매핑 |
| 매핑 | `esl/library/mapping.py to_target` | 셀 (기본 24×14) 합력·합모멘트 → 대상 셀 노드 최소노름 분배 + 평형 보정 |
| 정규화 좌표계 | `esl/library/normalize.py frame()` | 면적 가중 PCA 평면 + `axis_ref`, `L_xi`·`L_eta`·`z_range` |
| 크기 정보 | `library_entries.model.inch`, `library_entries.summary.frame.{L_xi,L_eta}` | DB에 있음. 분석 생성 시 크기 검사 없음 |
| 모델 동일성 규칙 | `esl/io/results_csv.py _check_conn`, `canon_conn`, 결정 0.5.5 | 노드 ID 집합 + 요소 연결(회전·반전·삼각형 표현 동치), 좌표는 Kabsch 정합 잔차 ≤ `coord_check.max_rel`(0.005)·bbox 개략 확인 |
| Case 입력 | `cases.rad_path`, `cases.part_title` | rad(+include)는 업로드 폴더 또는 input_roots(읽기 전용). 낙하 씬 전체 rad 가 수 GB 일 수 있음 |
| 업로드 | `api/services/uploads.py`, `core/uploads.py` | 청크·이어 올리기·sha256. complete 검사는 **Case 전용**. `upload.allowed_ext` 에 `.fem` 없음 |
| rad 파서/쓰기 | `esl/rad/parser.py parse_rad`, `esl/rad/writer.py write_rad` | 대상 파트만 숫자 해석(쉘, LAW1/2/36 E·ν, 두께), include 해석 / 쉘 메시 출력 |
| fem 파서 | – | **없음** |
| 3-2-1 | `esl/mech/supports.py pca_corners`, `pick_321`; 항목 `meta.esl.supports` | 자동 선택 / 항목 Case 의 지지 |
| 외부 실행 | `worker/esl_worker/h3d.py`, `executor._run_h3d` | LOCAL step, argv 템플릿, shell=False, 메타문자 거부, 프로세스 트리 종료, DB 세마포어 `altair.max_concurrent_hw` |
| 명령 규칙 원형 | `esl.md` §4.4 | `{optistruct}` → `altair.optistruct_path`, 키 `os_solve` 정의만, **미구현** |
| 작업·DB | `core/job_types.py`, migration 0001~0008 | 7종, stage 1~9. 0009 = MCP(`esl_mcp_ready.md`) **예약**(미구현) |
| 화면 | `pages/library/*` | 목록 행 선택 없음 |

## 1. 범위 / 비범위

| 범위 (v0.7.0) | 비범위 |
|---|---|
| S1 기존 rad 형상 최적화, S2 템플릿 최적화 | HPC/PBS 제출, 원격 실행 |
| 템플릿 등록·목록·상세·삭제(보관) — `.rad`·`.fem` 쉘 | CAD/STEP 템플릿(§16 후속), 템플릿 메시 자동 생성 |
| 라이브러리 목록 행 선택, 종합분석 상세 진입 | 형상(DSHAPE)·두께 최적화 |
| OPT_RUN(SLOT): 준비 → 하중 → 덱 → OptiStruct → 후처리 → 등록 | 비드 반영 모델의 Radioss 검증 낙하 자동 실행 |
| OptiStruct 경로·동시 수·라이선스 재시도 설정 | 3D 비드 보기(GLB) — v0.7.x 후보 |
| 결과: 비드 높이, 2D 맵 PNG, 수렴 이력, 비드 반영 메시(rad/fem), 보고서, 원본 h3d/out | 라이브러리 항목 등록(확정 7) |
| migration 0010, 시험, 가이드·CHANGELOG | 인치 정규화(`mass`·`inch2`) — S2 는 같은 크기만이라 `none` 고정 |

## 2. 결정

| ID | 결정 | 근거 |
|---|---|---|
| OR-D-1 | 작업 **`OPT_RUN`**(SLOT, stage **10** "비드 최적화"), 대상 테이블 **`opt_runs`**(`scenario` S1/S2). LIB_ANALYZE 확장 안 함 | 덱만 만드는 분석과 솔버 실행은 수명·실패 양상이 달라 상태·재시도·권한 분리 |
| OR-D-2 | 하중·덱은 코어 함수 재사용: `analysis.run(entries, target, opts)` → `analysis.optdeck_load_cases` → `optdeck.write`. 대상은 `LibraryEntry` 와 같은 인터페이스 어댑터 — S1 `CaseTarget`, S2 `TemplateTarget` | 매핑 알고리즘 변경 0(확정 3) |
| OR-D-3 | **S1 하중 = 노드 직접 적용**: `analysis.run` 옵션 `direct_nodal: true` → 각 ESL 원본 F_eq 를 node_id 로 대상 노드 순서에 재배열(셀 매핑·평형 보정 없음). 조건 = 모델 동일(OR-D-4) | 확정 3. 현재 `mesh_sha256`(좌표 포함) 일치 규칙은 버전 간 좌표 미세차로 너무 엄격 |
| OR-D-4 | **모델 동일성(S1)** = 결정 0.5.5 규칙 재사용: 노드 ID 집합 동일 + 요소 연결 `canon_conn` 동일 + 좌표 Kabsch 잔차 ≤ `coord_check.max_rel`·bbox. 빠른 판정용 `topo_sha256`(정렬 node_id + 요소 ID별 canon 연결, 좌표 제외) | 사용자 결정 0.5.5 "동일성은 노드 ID + 요소 연결" |
| OR-D-5 | **S1 다른 모델 ESL = 선택 불가**(자동 S2 전환 없음). 새 최적화 화면 S1 탭에서 기준과 `topo_sha256` 이 다른 행은 "다른 모델" 표시, 실행 버튼 비활성, [다른 모델 빼기] 1개 + 안내 "다른 모델 ESL은 템플릿 최적화로". 서버는 422 `MODEL_MISMATCH` | 자동 전환보다 상태·결과 해석이 단순(한 실행 = 한 하중 방식) |
| OR-D-6 | **S1 대상** = 기준 ESL(선택 첫 행)의 Case 입력 rad(+include)를 `parse_rad(case.part_title)`로 **제자리 읽기**(복사 안 함 — 낙하 씬 rad 가 수 GB). 읽은 대상 파트만 `_opt/<id>/target/target.npz` 로 저장 + 원본 파일 sha256·크기·mtime 기록. 지지 = 기준 ESL 항목의 3-2-1(`meta.esl.supports`) | 확정 10 입력 폴더 읽기만. 대상 파트 배열만으로 재현 가능 |
| OR-D-7 | **S2 크기** = 같은 인치(양쪽 다 있을 때) **AND** `L_xi`·`L_eta` 상대차 ESL 간 ≤ `opt_run.size.tol_rel`(0.02), 템플릿↔ESL 대표(중앙값) ≤ `plate_tol_rel`(0.05). 화면·API·워커에서 강제(422 `SIZE_MISMATCH`), 덮어쓰기 없음 | 확정 5(Q2 A) |
| OR-D-8 | **템플릿** = 전역 자원(프로젝트 무관, 모든 사용자 조회·사용). 등록 = 어느 프로젝트든 power 이상. 삭제 = 등록자 또는 전역 관리자. `opt_runs` 가 참조하면 `ARCHIVED`(목록 숨김, 기존 실행 재시도 가능), 미참조면 행 삭제 + 폴더 `_templates/_backup/<UTC>_<id>/` 로 이동(파일 삭제 없음) | 확정 4 |
| OR-D-9 | 템플릿 파일은 등록 시 `<esl_root>/_templates/<id>/input/` 로 **복사**(sha256), 업로드 폴더는 읽기만. 형식 `.rad`(+include, `parse_rad`) 또는 `.fem`(신규 `esl/opt/femread.py`: GRID·CQUAD4·CTRIA3·PSHELL·MAT1, 자유/소형/대형 필드, INCLUDE 미지원 → 오류) | 확정 4·10. 템플릿은 작다(≤ `plate.max_elems`) |
| OR-D-10 | 비드 방향(확정 6): DTPG 기본(요소 법선, NORM 없음), `bounds [0,1]` 유지. **S2** 는 템플릿 요소 법선을 정규화 좌표 n 쪽으로 연결 순서 정렬(뒤집힌 요소 수 기록). **S1** 은 §18 Q1 답에 따름(권장: 그대로 + 경고) | 평판 법선 불일치 시 비드가 요소마다 반대로 생김 |
| OR-D-11 | OptiStruct = 워커 LOCAL step, argv 템플릿 `commands.os_check`·`os_solve`(argv[0] `{optistruct}` → `altair.optistruct_path`), shell=False, 메타문자 거부, DB 세마포어 `altair.max_concurrent_os`. `-check` 후 본 실행 | `esl.md` §4.4 원형 구현, 카드 확신도(중상) 사전 확인 |
| OR-D-12 | 라이선스 부족 = 3회 × 300 초 자동 재시도 후 `OS_LICENSE_UNAVAILABLE`(확정 8) | Q5 A |
| OR-D-13 | 재시도(기존 `POST /jobs/{id}/retry`) 시 `solve/solve.json` 덱 sha256 동일 + 성공 표식 → OS_SOLVE **SKIPPED(재사용)** | 후처리 실패로 수 시간 해석 반복 방지 |
| OR-D-14 | 후처리 = HyperView 배치 TCL(`resources/tcl/esl_bead_post.tcl`)이 `<deck>_des.h3d` 마지막 반복 Shape Change → CSV, Python 이 비드 높이·PNG(표준 라이브러리 zlib 인코딩)·비드 반영 메시·보고서 | h3d 비공개 포맷, 서버 HyperView 있음 |
| OR-D-15 | 결과는 라이브러리 미등록, 라이브러리 화면 "최적화 실행" 탭·실행 이력에 보존(확정 7) | Q4 A |
| OR-D-16 | migration **0010**(0009 MCP 예약). 0009 부재 시 0010 `down_revision="0008"`, 이후 MCP 는 revision id `"0009"`·`down_revision="0010"` | 두 migration 모두 멱등, 파일 번호 ≠ 적용 순서(decisions 기록) |

## 3. 사용 시나리오

### 3.1 S1 기존 rad 형상 최적화
1. 라이브러리 목록에서 ESL 행 체크(첫 행 = 기준). S1 에 쓸 수 있는 행은 목록의 "모델" 열 아이콘(같은 모델 묶음)으로 보인다 — 목록 체크 자체는 S2 규칙(같은 크기)만 적용.
2. [선택한 ESL로 비드 최적화 (n)] → 새 최적화 화면 `/esl/p/:pid/opt/new?entries=…`, 탭 **[기존 형상 | 템플릿]**. 모든 선택이 기준과 같은 모델이면 기본 탭 = 기존 형상, 아니면 템플릿.
3. 기존 형상 탭: ① 대상 카드 — 기준 Case 이름·대상 파트(`part_title`)·노드·요소 수·rad 파일명(읽기 전용), PID 표(설계 체크, 기본 전부), 3-2-1(기준 ESL 지지, 표시만). ② ESL 카드 — 행마다 "같은 모델 ✓/다른 모델 ✗", 다른 모델이 있으면 [다른 모델 빼기]·안내.
4. ③ 옵션(목적·하중 케이스·비드 폭/높이/각도·제목) → 주 버튼 [최적화 실행].
5. 진행·결과는 §3.3.

### 3.2 S2 템플릿 최적화
1. (최초 1회) 템플릿 등록: 라이브러리 화면 탭 "템플릿" → [템플릿 등록] → `.rad`(+include) 또는 `.fem` 끌어다 놓기 → 청크 업로드 → 자동 검사(§7.2) → 제목·인치(선택)·설명 입력 → [등록]. 목록: 제목·형식·인치·크기(mm)·노드/요소·등록자·사용 횟수, 행 메뉴 [삭제](등록자·관리자만).
2. ESL 선택(같은 크기 규칙으로 체크 제한) → 새 최적화 화면 템플릿 탭: ① 템플릿 선택(드롭다운, ESL 크기와 맞는 템플릿만 활성, 크기 차 표시) → PID 표(설계 체크)·자동 3-2-1 표시·품질 경고 요약. ② ESL 카드(크기 그룹 요약). ③ 옵션 → [최적화 실행].
3. 대안 진입: 종합분석 상세의 보조 버튼 "이 분석의 씬으로 비드 최적화" → 분석 `entry_ids` 로 채움(크기 혼합이면 가장 많은 그룹만 남기고 경고).

### 3.3 공통 진행·결과
- 상세 `/esl/p/:pid/opt/:id`: step 진행(6), OptiStruct 반복 n/DESMAX·목적값, 라이선스 대기, 로그, 취소. 완료 후 비드 맵 PNG, 수렴 그래프, subcase 컴플라이언스 초기/최종, 다운로드(비드 반영 메시 rad/fem, 비드 노드 CSV, h3d·out, 덱, 보고서, zip), [보고서 보기].
- 다음 단계 안내 문구: 비드 반영 메시로 낙하 해석 → 새 Case → 라이브러리 등록 → 버전 비교. (S1 결과 `bead_mesh.rad` 는 원 노드·요소 ID 그대로라 제품 모델 include 교체로 바로 쓸 수 있음.)

## 4. 데이터 흐름

```
S1: library_entries(같은 모델) + 기준 Case rad(제자리 읽기) ─┐
S2: library_entries(같은 크기) + opt_templates(_templates/<id>) ┴─ POST /opt/runs → opt_runs + OPT_RUN(QUEUED)
                                           ▼ 워커(SLOT), <esl_root>/_opt/<id>/
 1 OPT_PREP   (INTERNAL) S1 parse_rad(case) → 동일성 재검사 / S2 template.npz → 크기 재검사·법선 정렬
                         → 3-2-1(S1 기준 ESL 지지 / S2 자동) → target/target.npz, target.json
 2 OPT_LOAD   (INTERNAL) analysis.run(entries, target, S1 direct_nodal | S2 셀 매핑, normalization=none)
                         → load/analysis.json, mapped_loads.npz
 3 OPT_DECK   (INTERNAL) optdeck.write(+server 카드) → deck/esl_bead.fem, esl_loads.inc, optdeck.json
 4 OS_SOLVE   (LOCAL)    세마포어 → solve/ 로 덱 복사 → -check → 본 실행(라이선스 재시도) → solve.json
 5 OPT_POST   (LOCAL+INTERNAL) hw TCL → post/shape.csv → bead.npz·bead_nodes.csv·bead_map.png·history.csv·
                         bead_mesh.rad·bead_mesh.fem → report.html
 6 OPT_REGISTER (DB)     opt_runs.result·report_rel, artifacts, 알림
```
- 각 step 은 자기 하위 폴더를 `fresh_dir`(이전 내용 `_backup/<UTC>/`, 삭제 없음). 코어는 DB를 모르고 워커 `core_adapter` 가 spec 으로 경로·옵션 전달.
- 템플릿 폴더: `<esl_root>/_templates/<tid>/{input/<원본 파일>, template.npz, template.json}` (`core/paths.py TEMPLATE_DIR = "_templates"`).

## 5. API (접두 `/esl/api`, 기존 오류 형식, 비GET `X-ESL-Request: 1`)

### 5.1 엔드포인트

| 메서드·경로 | 요청 | 응답 | 오류 |
|---|---|---|---|
| `GET /opt/settings` | – | `OptSettingsOut` | – |
| `POST /opt/templates/check` | `{project_id, upload_id, part_title?}` | `200 MeshCheckOut` | 404 `UPLOAD_NOT_FOUND`, 409 `UPLOAD_NOT_READY`, 422 `MESH_INVALID`·`MESH_FORMAT_UNSUPPORTED`·`PART_NOT_FOUND`·`PART_AMBIGUOUS` |
| `POST /opt/templates` | `TemplateIn` | `201 TemplateOut` | 위 + 409 `PLATE_CHANGED`(check 이후 업로드 변경), 422 `INVALID_PARAMS` |
| `GET /opt/templates?status=active|archived&q=` | – | `[TemplateOut]` | – |
| `GET /opt/templates/{tid}` | – | `TemplateOut` | 404 `TEMPLATE_NOT_FOUND` |
| `DELETE /opt/templates/{tid}` | – | `200 {deleted: bool, archived: bool}` | 403 `NOT_TEMPLATE_OWNER`, 404 |
| `POST /opt/s1-check` | `{project_id, entry_ids}` | `200 S1CheckOut` | 422 `ENTRY_NOT_FOUND`, 409 `PREREQUISITE_MISSING`(기준 Case rad 없음) |
| `POST /opt/runs` | `OptRunIn` | `201 OptRunOut`(+`job`) | 422 `ENTRY_NOT_FOUND`·`MODEL_MISMATCH`·`SIZE_MISMATCH`·`TEMPLATE_NOT_FOUND`·`TEMPLATE_ARCHIVED`·`INVALID_PARAMS`, 409 `PREREQUISITE_MISSING`, 503 `SOLVER_NOT_CONFIGURED` |
| `GET /opt/runs?project_id=&scenario=&limit=&cursor=` | – | `[OptRunOut]` | 404 `PROJECT_NOT_FOUND` |
| `GET /opt/runs/{id}` | – | `OptRunOut` | 404 `OPT_RUN_NOT_FOUND` |
| `GET /opt/runs/{id}/files` · `/download?rel=` · `/bundle?parts=` · `/report` · `/bead-map.png` | – | 목록 / 첨부 / zip / HTML(분석 보고서 CSP) / PNG(ETag) | 404 `FILE_NOT_FOUND`·`REPORT_NOT_READY`·`RESULT_NOT_READY`, 413 |
| 기존 `POST /jobs/{id}/cancel`·`/retry`, 로그 | – | OPT_RUN 에도 적용 | – |
| 기존 `GET /library/entries` | – | `size:{inch, L_xi, L_eta}`, `topo_sha256` 추가 | – |

### 5.2 스키마

```text
OptSettingsOut { enabled, solver_ready, solver_reason|null, size:{tol_rel, plate_tol_rel, require_inch},
                 bead_defaults:{min_width, height, angle}, objectives:["minmax","weighted"],
                 deck_cases:["all","representative+worst"], max_cases, max_entries, template_max_elems,
                 template_ext:[".rad",".inc",".fem"] }

MeshCheckOut   { ok, sha256, format:"rad"|"fem", file_name, parts:[{part_id,title,n_elems}] (rad만), part_title|null,
                 mesh:{n_nodes, n_elems, n_quad, n_tria, unsupported:{type:count}},
                 pids:[{pid, title, n_elems, thickness, E, nu}],
                 frame:{L_xi, L_eta, z_range, warnings[]},
                 quality:{errors:[{code,message}], warnings:[{code,message,value?,limit?}], metrics:{…§7.2}},
                 supports_auto:[{node_id, dof}] (3) }
TemplateIn     { project_id (권한 확인용), upload_id, sha256, part_title?, title(1..200), inch?: int, description?(≤2000) }
TemplateOut    { id, title, inch|null, description, format, file_name, part_title, sha256, n_nodes, n_elems,
                 L_xi, L_eta, z_range, pids, quality_warnings[], status:"ACTIVE"|"ARCHIVED", n_runs,
                 created_by_name, created_at, can_delete: bool }

S1CheckOut     { base:{entry_id, case_id, case_title, part_title, rad_file_name, n_nodes, n_elems, pids[], supports[]},
                 entries:[{entry_id, same_model: bool, reason|null}] }   # reason: NODE_IDS|CONNECTIVITY|COORDS

OptRunIn       { project_id, scenario:"S1"|"S2", title?, entry_ids:[id] (1..max_entries), analysis_id?,
                 template_id? (S2 필수), design:{nondesign_pids?:[int], bead?:{min_width,height,angle}},
                 options:{objective?, deck_cases?, supports?:[{node_id,dof}] (S2만, 3)} }
OptRunOut      { id, project_id, scenario, title, entry_ids, analysis_id, base (S1: {entry_id, case_id, part_title,
                 rad_sha256}) | template (S2: {id, title, sha256}), size (S2), design, options, job|null, state,
                 created_by_name, created_at, result: OptResult|null, report_ready }
OptResult      { converged, iterations, desmax, objective:{initial, final, history[]},
                 subcases:[{label, entry_id, comp_initial, comp_final}], n_subcases, deck_reduced,
                 bead:{height_max, area_frac, n_design_elems}, normals_flipped,
                 solve:{seconds, license_waits, reused}, warnings[] }
```
- 응답 경로는 `DisplayJSONResponse` 규칙, 서버 절대경로 없음(`file_name`·`rel` 만).

### 5.3 오류 코드 (신규)

| 코드 | HTTP/작업 | 의미 |
|---|---|---|
| `MODEL_MISMATCH` | 422 / OPT_PREP | S1: 선택 ESL 또는 기준 Case rad 대상 파트가 기준 모델과 다름(`reason`, 상위 10개 ID) |
| `SIZE_MISMATCH` | 422 / OPT_PREP | S2: ESL 간·템플릿↔ESL 크기 불일치(`reason`: inch|xi|eta, 값·한도) |
| `MESH_INVALID` | 422 | 템플릿 검사 오류 ≥1(`quality.errors` 동봉: `MESH_ELEM_UNSUPPORTED`, `MESH_TOO_LARGE`, `MESH_THICKNESS`, `MESH_MATERIAL`, `MESH_EMPTY`, `SUPPORT_DEGENERATE`) |
| `MESH_FORMAT_UNSUPPORTED` | 422 | `.rad`/`.fem` 아님, fem INCLUDE·비지원 카드만 있는 파일 |
| `PLATE_CHANGED` | 409 | check 이후 업로드 내용 sha256 변경 |
| `UPLOAD_NOT_READY` | 409 | 업로드 미완료·취소·stale |
| `TEMPLATE_NOT_FOUND` / `TEMPLATE_ARCHIVED` | 404·422 | 없는 템플릿 / 보관된 템플릿으로 새 실행 |
| `NOT_TEMPLATE_OWNER` | 403 | 등록자·전역 관리자 아님 |
| `SOLVER_NOT_CONFIGURED` | 503 | `altair.optistruct_path` 없음·실행 파일 없음·`opt_run.enabled: false` |
| `INPUT_CHANGED` | 작업(경고) | S1 재시도 시 Case rad sha256 이 실행 생성 때와 다름 → 경고 기록 후 진행(동일성은 재검사) |
| `OS_DECK_INVALID` / `OS_LICENSE_UNAVAILABLE` / `OS_SOLVE_FAILED` / `OS_TIMEOUT` / `BEAD_POST_FAILED` | 작업 | §8·§9 |
| 기존 재사용 | | `ENTRY_NOT_FOUND`, `SUPPORT_DEGENERATE`, `MAPPING_DEGENERATE`, `GRID_MISMATCH`, `SOLVER_OUT_OF_MEMORY`, `PREREQUISITE_MISSING`, `CONFIG_INVALID` |

- 미수렴(DESMAX 도달)은 실패가 아님: SUCCEEDED + `converged=false` + 경고.

## 6. 작업 종류 · 워커 단계 · 진행률/로그

### 6.1 `job_types.py`
```python
"OPT_RUN": JobTypeDef("OPT_RUN", 10, "SLOT", (
    StepDef("OPT_PREP", "opt_prep"), StepDef("OPT_LOAD", "opt_load"), StepDef("OPT_DECK", "opt_deck"),
    StepDef("OS_SOLVE", None, kind="LOCAL"), StepDef("OPT_POST", "opt_post", kind="LOCAL"),
    StepDef("OPT_REGISTER", None))),
```
- 작업 대상 = `jobs.opt_run_id`. 같은 opt_run 에 활성 작업이 있으면 retry 409 `JOB_ACTIVE`(기존).

### 6.2 단계별 요구
- OR-1 **OPT_PREP**
  - S1: 기준 Case `rad_path`·include 를 `parse_rad(part_title, include_path_map)`로 읽음(쓰기 없음) → 기준 ESL raw 와 동일성(OR-D-4) → 선택 ESL 전부 동일성(파일 기준 재검사) → 지지 = 기준 ESL `meta.esl.supports`(rank 검사) → 비설계 PID → `target/target.npz`(node_id, x0(rad), elem_id, elem_type, conn, elem_pid, thickness, E, nu, design) + `target.json`(rad 파일 sha256·size·mtime, topo_sha256, 법선 검사 결과).
  - S2: `template.npz` → 크기 재검사(§7.1, 항목 `entry.json` frame 기준) → 법선 정렬 → 3-2-1(`options.supports` 또는 템플릿 자동) → 비설계 PID → 같은 파일 형식으로 저장 + frame·grid(라이브러리 grid).
- OR-2 **OPT_LOAD**: `analysis.run(entries, target, {normalization:"none", deck_cases, max_cases, direct_nodal: S1})`. S1 은 node_id 재배열만(누락 노드 → `MODEL_MISMATCH`), S2 는 셀 매핑 + 평형 보정, 셀당 노드 중앙값 < 64 경고. 대표·최악 군집(덱 축소용)은 두 경우 모두 기존 그대로.
- OR-3 **OPT_DECK**: `optdeck.write` + 서버 카드(§8.2). `run_optistruct.bat`·README 도 생성(PC 실행용). `optdeck.json` 에 덱 sha256.
- OR-4 **OS_SOLVE**: §8. OR-5 **OPT_POST**: §9.
- OR-6 **OPT_REGISTER**: `opt_runs.result`, `report_rel`, `artifacts`(`optdeck`, `opt_result`, `opt_solve`, `report`), 알림.

### 6.3 진행률·로그

| step | 진행률 | 로그 |
|---|---|---|
| OPT_PREP | 파싱 60·검사 30·저장 10 (S1 대형 rad 는 parse_rad 2단계 진행 메시지) | 노드·요소·PID·동일성/크기·법선 |
| OPT_LOAD | 항목 k/K | 항목별 직접 적용 합력 / 매핑 잔차·보정량 |
| OPT_DECK | 0→100 | subcase 수·축소·설계/비설계 요소 |
| OS_SOLVE | check 5 % + 반복 n/DESMAX × 95 % (`.out` 꼬리 읽기, `cancel_check_interval_s` 주기) | argv(관리자만), `.out` 새 줄 중계(≤ `log_tail_lines`), 세마포어·라이선스 대기 "(1/3) 300초 후 다시 시도" |
| OPT_POST | hw 50·후처리 50 | Shape Change 노드 수·비드 최대 높이 |

- 작업 progress 가중 1·1·1·85·10·2 %.

## 7. 입력 검증

### 7.1 S2 크기 일치 (OR-7)
- 기준 = 선택 첫 ESL. (가) `require_inch: true` 이고 양쪽 `model.inch` 가 있으면 같아야 함, 한쪽 null 이면 치수만 + 경고 `INCH_UNKNOWN`. (나) `L_xi`·`L_eta` 상대차 ≤ `tol_rel`.
- 템플릿: ESL 대표 = 선택 ESL 치수 중앙값, ξ·η 각각 ≤ `plate_tol_rel`. 템플릿 `inch` 가 있으면 ESL 인치와 같아야 함(없으면 치수만, §18 Q2).
- ESL 격자(nx×ny) 다르면 `GRID_MISMATCH`.
- 검사 시점: 화면(즉시) / `POST /opt/runs`(DB `summary.frame`) / OPT_PREP(항목 파일).

### 7.2 메시 검사 (S2 템플릿 등록·S1 대상 공통 함수 `esl.opt.mesh_check`) (OR-8)

| 검사 | 오류(실행·등록 불가) | 경고 |
|---|---|---|
| 형식 | `.rad` 0/2개 이상·include 누락·파싱 실패, `.fem` INCLUDE·파싱 실패 | 파트 2개 이상(rad, 선택 필요), fem 비지원 카드 무시 수 |
| 요소 | QUAD4/TRIA3 외(`MESH_ELEM_UNSUPPORTED`), 요소 수 > `template.max_elems`(500 000, S2만) | TRIA3 비율 > 20 % |
| 재료·두께 | 두께 ≤ 0, E·ν 해석 불가 | – |
| 연결 | 요소 0 | 연결 성분 > 1, 일치 노드 |
| 평탄도 | – | S2: `z_range/max(L)` > `flat_tol_rel`(0.02) "평판 아님" |
| 법선 | – | n 과 반대 요소 수(S2 자동 정렬 / S1 §18 Q1) |
| 요소 크기 | – | 비드 MW < 2 × 요소 크기 중앙값 |
| 매핑 해상도 | – | S2: 셀당 노드 중앙값 < 64 |
| 형상 | – | 최대 종횡비 > 10, 뒤틀림 > 15° |
| 3-2-1 | rank < 6(`SUPPORT_DEGENERATE`) | – |

- 비설계 PID 제외 후 설계 요소 0 → `MESH_INVALID`.
- 템플릿 check 결과는 `uploads.result`(`{"purpose":"template", …}`)에 저장하고 업로드를 COMPLETED 로(Case 화면 목록은 purpose 있는 업로드 제외). 업로드 폴더에 쓰지 않음.

### 7.3 S1 모델 동일성 (OR-9)
- `topo_sha256` 비교로 1차 판정(목록·s1-check), OPT_PREP 에서 전체 규칙(노드 ID 집합·`canon_conn`·Kabsch 잔차)으로 확정.
- `library_entries.topo_sha256`: 새 등록 시 계산. 기존 항목은 migration 0010 후 첫 조회 때 API 가 항목 `raw.npz` 로 계산해 채움(지연 백필, 실패 시 null → S1 선택 불가 + 사유 "모델 정보 없음").
- 기준 Case 입력이 없거나(업로드 정리·경로 변경) 읽기 실패 → `PREREQUISITE_MISSING`("기준 Case 입력 rad 가 없습니다 — Case 입력을 다시 올리거나 템플릿 최적화 사용").

## 8. 솔버 실행 (OS_SOLVE)

### 8.1 실행 규칙 (OR-10)
- `solve/` fresh_dir 후 `deck/` 의 `esl_bead.fem`·`esl_loads.inc` 복사, 스크래치 `solve/tmp/`.
- argv: `commands.os_check` → 성공 시 `commands.os_solve`. argv[0] = `{optistruct}` 만, placeholder `optistruct, fem, fem_fwd, nt, work_dir, scratch, mem_mb`. 치환값 검사·shell=False·트리 종료·작업 제한기는 `h3d.py` 와 같은 공통 함수(`localproc.py`).
- `cwd = solve/`, env = `worker.env_passthrough` + `opt_run.solve.env`(허용 키 `ALTAIR_LICENSE_PATH`, `ALTAIR_HOME`, `OMP_*`). argv 를 `job_steps.command`에 저장.
- 동시 실행: `acquire_os`(advisory lock 신규 키, step outputs `os_acquired`, `altair.max_concurrent_os` 기본 1). 대기 중 lease 갱신·취소 확인.
- 성공: 종료코드 0 + `error_patterns` 불일치 + `<deck>.out`·`<deck>_des.h3d` 존재. 수렴 = `converged_patterns` 일치, 반복 = 마지막 `ITERATION n`.
- `solve/solve.json` `{deck_sha256, argv, exit_code, seconds, iterations, converged, license_waits, ok}`. `solve/tmp/` 는 다음 실행 fresh_dir 때 `_backup` 으로(삭제 없음).

### 8.2 덱 서버 카드 (OR-11, `optdeck.write(design={"server": {...}})`)
- `server` 키가 있을 때만: `DOPTPRM, DESMAX, <desmax>`(30) [확신도 상], `OUTPUT, H3D, ALL` [중상 — V-OR-R1], S2 법선 정렬 연결 순서, 헤더 `opt_run <id> <scenario>`. `server` 없으면 기존 LIB_ANALYZE 덱 바이트 불변.

### 8.3 라이선스·실패·재시도 (OR-12)
- 라이선스 감지: 종료코드≠0 + stdout/`.out` 에 `license_patterns` 일치. 재시도 3회 × 300 초(대기 중 세마포어 반납, 취소 즉시), outputs `license_waits`. 소진 → `OS_LICENSE_UNAVAILABLE`.
- `-check` 실패 → `OS_DECK_INVALID`(ERROR 줄 앞 20줄). 그 밖 → `OS_SOLVE_FAILED`. `timeout_h`(12) → `OS_TIMEOUT`. 메모리 → `SOLVER_OUT_OF_MEMORY`.
- 사용자 재시도 = `POST /jobs/{id}/retry`(power 이상). OR-D-13 해석 재사용. 워커 재시작·lease 상실은 기존 INTERRUPTED + 트리 종료.

## 9. 결과물 (OPT_POST) (OR-13)
- `commands.bead_post`(argv[0] `{hw}`, placeholder `hw, post_tcl_fwd, h3d_fwd, out_dir_fwd, request_fwd`) → `post/shape.csv`(node_id, dx, dy, dz)·`done.json`. hw 세마포어 공유. node_id 집합 ≠ 대상 → `BEAD_POST_FAILED`.

| 파일 | 내용 |
|---|---|
| `post/bead.npz` | node_id, shape (N,3), h = shape·노드 법선, design |
| `post/bead_nodes.csv` | node_id, x0, y0, z0, h, dx, dy, dz |
| `post/bead_map.png` | (ξ,η) 평면 투영, 요소 평균 h(0→BH 순차 색), 비설계 회색, 3-2-1 기호, 범례·mm 축, `png_px`(1600×900), 순수 Python + zlib |
| `post/history.csv` | iteration, objective, subcase별 comp |
| `post/bead_mesh.rad` | x0 + shape 좌표, 원 노드·요소·PID·두께·재료 유지(`write_rad`). S1 은 제품 모델 대상 파트 include 교체용 |
| `post/bead_mesh.fem` | 같은 메시 OptiStruct bulk |
| `report.html` | 자체 완결: 시나리오·입력 ESL 표·대상(Case/템플릿)·동일성/크기·품질·하중(S1 직접/S2 셀 포락)·덱 설정·수렴(SVG)·비드 맵(SVG)·subcase 표·한계 |
| `opt.json` | OptResult 원본 |

- 다운로드 목록: 위 + `deck/*` + `solve/<deck>.out·.h3d·_des.h3d·.hist·.stat`. `solve/` 원본은 수정하지 않음.
- 라이브러리 반영 없음(OR-D-15).

## 10. 화면 (2560×1440 기준, 1920×1080 잘림·가로 스크롤 없음, 화면당 주 버튼 1개)

### 10.1 라이브러리 (변경)
```
[라이브러리]  탭: [항목 | 종합분석 | 버전 비교 | 최적화 실행 | 템플릿]
필터: 모델[▼] 크기[75형 1662×948 ▼] 씬유형[…] 판정[PASS만▼]
선택 3개 · 기준 75형 1662×948 · 같은 모델 3/3     [선택한 ESL로 비드 최적화 (3)]  [종합분석 만들기](주)
┌☐┬모델────┬인치┬크기(mm)──┬씬──────────────┬판정┐
│☑│75QN80H ⓜ│75 │1662×948 │17 Corner 146 2nd│PASS│   ⓜ = 기준과 같은 모델(S1 가능)
│☐̸│65QN80H │65 │1452×826 │… (비활성: 크기 다름)    │
```
### 10.2 템플릿 탭
```
템플릿 (모든 사용자 공개)                                                   [템플릿 등록](주)
┌제목──────────┬형식┬인치┬크기(mm)──┬노드/요소─────┬등록자┬사용┬───┐
│75형 평판 v1  │fem │75 │1660×950 │48 210/47 600│차완기│ 3  │[삭제]│  (삭제: 등록자·관리자만, 사용 중이면 "보관됨")
등록 패널: [.rad/.fem 끌어다 놓기] ███ 100% · 검사: 오류 0 경고 1 [펼치기] · 제목[  ] 인치[  ] 설명[  ]  [등록]
```
### 10.3 새 비드 최적화 `/opt/new`
```
새 비드 최적화   탭 [● 기존 형상(S1) | ○ 템플릿(S2)]                       [최적화 실행](주, 비활성 사유 툴팁)
S1 ┌① 대상──────────────────────────────┐┌② ESL (3)──────────────────────────────┐
   │ Case 75QN80H_v072 · chassis rear   ││ 75QN80H v072 17 Corner 146   같은 모델 ✓│
   │ 노드 222 924 · 요소 223 415 (rad)   ││ 75QN80H v073 05 Edge 12      다른 모델 ✗│
   │ PID 표 [설계 ☑] · 3-2-1 기준 ESL 지지 ││ [다른 모델 빼기] 다른 모델은 템플릿 최적화로│
   └────────────────────────────────────┘└───────────────────────────────────────┘
S2 ┌① 템플릿 [75형 평판 v1 ▼] 크기 −0.1 %/+0.2 % ✓ · PID 표 · 자동 3-2-1 · 경고 1┐┌② ESL (크기 그룹 요약)┐
공통 ┌③ 옵션: 목적(●minmax ○weighted) 하중(●모든 씬 ○대표+최악) 비드 폭 10 높이 3 각도 60° 제목[ ]┐
솔버 미설정 시 상단 경고 띠 "서버 OptiStruct 경로가 설정되지 않았습니다(관리자 문의)"
```
### 10.4 최적화 상세 `/opt/:id`
```
비드 최적화 · S1 · 75형 강건 비드 1차   상태 실행 중 (반복 12/30)              [보고서 보기](주, 완료 후)
┌진행: ✓대상 준비 ✓하중 ✓덱 ●OptiStruct ○후처리 ○등록 · 목적 1.00→0.62 · 라이선스 대기 0 [로그] [취소]┐
┌결과: [bead_map.png] 수렴 그래프 · 수렴 ✓ 반복 18 · 비드 면적 34 % · subcase 표 · 받기 [.rad] [.fem] [zip]┐
```
- 실패 시 결과 카드 자리에 오류 코드·메시지 + [다시 시도](power 이상).

## 11. 설정 키 (하드코딩 금지)

```yaml
altair:
  optistruct_path: "C:/Program Files/Altair/2026.1/hwsolvers/scripts/optistruct.bat"   # 예시, 없으면 503
  max_concurrent_os: 1
commands:
  os_check: ["{optistruct}", "{fem}", "-check", "-tmpdir", "{scratch}"]
  os_solve: ["{optistruct}", "{fem}", "-nt", "{nt}", "-tmpdir", "{scratch}"]
  bead_post: ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{post_tcl_fwd}", "-input", "{h3d_fwd}", "-output", "{out_dir_fwd}", "-config", "{request_fwd}"]
opt_run:                                # 섹션 없으면 enabled: false
  enabled: true
  max_entries: 200
  size: {tol_rel: 0.02, plate_tol_rel: 0.05, require_inch: true}
  template: {max_elems: 500000, flat_tol_rel: 0.02, max_tria_frac: 0.2}
  solve:
    nt: 4                               # 작업 제한기 코어를 넘으면 줄임(경고)
    desmax: 30
    timeout_h: 12
    log_tail_lines: 2000
    error_patterns: ["(?m)^\\s*\\*\\*\\* ERROR"]
    converged_patterns: ["OPTIMIZATION HAS CONVERGED"]
    license_patterns: ["(?i)license.*(not available|checkout failed|insufficient|exceeded)", "(?i)ALM_\\w+_ERROR"]
    license_retry: {max: 3, wait_s: 300}
    env: {}
  post: {png_px: [1600, 900]}
upload:
  allowed_ext: [..., .fem]              # .fem 추가(.rad/.inc 기존)
```
- 비드 기본값·목적·subcase 상한·id_offset 은 기존 `library.yaml optdeck`. 모델 동일성 좌표 허용은 기존 `coord_check.max_rel`.
- 환경 점검(`check.py`): `optistruct_path` 존재·실행 가능, `esl_bead_post.tcl` 존재, `_templates` 쓰기 가능. TCL 경로는 코드 스냅샷 `resources/tcl/`(설정 아님).

## 12. DB 변경 — migration `0010_opt_runs`

- 번호·체인: OR-D-16. 멱등(`IF NOT EXISTS`/`checkfirst`), downgrade 미지원.
- **`opt_templates`**(전역): `id` PK, `title` varchar(200) NOT NULL, `description` varchar(2000), `inch` int NULL, `format` (`rad`|`fem`) CHECK, `file_name`, `part_title` NULL, `sha256` char(64), `n_nodes`, `n_elems`, `L_xi`, `L_eta`, `z_range` double, `pids` JSONB, `quality` JSONB, `dir_rel` NOT NULL(`_templates/<id>`, 상대·`..` 금지 CHECK), `status` (`ACTIVE`|`ARCHIVED`) CHECK, `origin_project_id` (등록 화면 프로젝트, 정보용), `created_by`, `created_by_name`, `created_at`, `archived_by`, `archived_at`(CHECK `(status='ARCHIVED') = (archived_at IS NOT NULL)`), `updated_at`. Index `(status, created_at desc)`.
- **`opt_runs`**: `id` PK, `project_id` NOT NULL, `scenario` (`S1`|`S2`) CHECK, `title`, `entry_ids` JSONB(≥1), `analysis_id` FK NULL, `base` JSONB NULL(S1: entry_id, case_id, part_title, rad_sha256, topo_sha256), `template_id` FK opt_templates NULL, `size` JSONB NULL(S2), `design`·`options` JSONB, `job_id`, `result` JSONB, `report_rel`, `dir_rel`(`_opt/<id>`), `created_by(_name)`, `created_at`, `updated_at`. CHECK `(scenario='S1' AND base IS NOT NULL AND template_id IS NULL) OR (scenario='S2' AND template_id IS NOT NULL)`. Index `(project_id, created_at desc)`, `(template_id)`.
- `library_entries.topo_sha256` char(64) NULL + Index(지연 백필, §7.3).
- `jobs.opt_run_id` FK NULL + Index. 제약 교체: `ck_jobs_job_type`(+OPT_RUN), `ck_jobs_stage` 1~10, `ck_jobs_subject`(OPT_RUN 분기, 기존 분기에 `opt_run_id IS NULL`).
- `ARTIFACT_KINDS` += `opt_result`, `opt_solve`. `uploads` 변경 없음(`result.purpose`).

## 13. 보안 · 권한

- 조회: ACTIVE 로그인 + 프로젝트 조회 권한(opt_runs). 템플릿 목록·상세는 ACTIVE 로그인 누구나(확정 4 공개).
- 실행·템플릿 check/등록·retry·cancel = power 이상(템플릿은 요청 `project_id` 의 power). 템플릿 삭제 = 등록자 또는 전역 관리자(`NOT_TEMPLATE_OWNER`). 남의 작업 취소·대기열 = 전역 관리자. 판정 순서 401→404→403→409.
- S1: 선택 ESL·기준 Case 모두 요청 프로젝트 소속이어야 함(아니면 404). Case 입력 경로는 기존 `check_includes`·input_roots 검사를 통과한 것만 읽음.
- 입력 보호: 업로드 폴더·Case 입력 폴더 **읽기만**(S1 제자리 읽기, S2 템플릿은 복사본 사용). 쓰기는 `_opt/<id>/`·`_templates/<id>/` 만.
- 업로드: 본인 업로드만, 본인 폴더 격리·`_backup`·심링크 거부. 템플릿 업로드 밖 include 거부.
- 외부 실행: LOCAL step, argv 템플릿·허용 argv[0]·메타문자 거부·shell=False. 덱 이름·경로는 서버 생성값만(제목은 덱 주석에 ASCII 이스케이프).
- 다운로드 `rel` 은 files 목록 일치 + realpath 가 `_opt/<id>/` 안. `job_steps.command` 는 전역 관리자만. 디스크 여유 < `upload.min_free_gb` → 507.
- 보고서 CSP·inline JSON 이스케이프 기존 규칙, 로그 마스킹 유지.

## 14. 검증 계획

| ID | 시험 | 위치 |
|---|---|---|
| V-OR-1 | S2 크기 규칙: 같은 인치·±2 % 통과, 2.1 % 거부, 인치 null 경고, 템플릿 ±5 % 경계·템플릿 인치 불일치, 화면·API·OPT_PREP 일치 | `tests/opt/test_size.py`, `backend/tests/test_opt_api.py`, `frontend/__tests__/opt.test.tsx` |
| V-OR-2 | S1 동일성: topo_sha256 같음/노드 ID 다름/연결 다름(회전·반전 동치는 같음)/좌표 큰 이동, 지연 백필, `MODEL_MISMATCH`·`PREREQUISITE_MISSING` | `tests/opt/test_identity.py`, `backend/tests/test_opt_api.py` |
| V-OR-3 | S1 직접 적용: 노드 순서가 다른 같은 모델 ESL → 재배열 후 F 노드별 일치(정확), 합력·합모멘트 보존, 셀 매핑 미호출 | `tests/opt/test_load.py` |
| V-OR-4 | S2 매핑: TemplateTarget 로 `analysis.run` — 셀 합력·합모멘트 보존(1e-9), 평형 보정, 같은 메시를 항목/템플릿 두 경로로 같은 결과 | `tests/opt/test_load.py` |
| V-OR-5 | 메시 검사: rad·fem 각각 — 비지원 요소·두께 0·상한·연결 성분·일치 노드·평탄도·법선·MW/요소 크기·셀당 노드·3-2-1 퇴화, fem 자유/소형/대형 필드·INCLUDE 거부 | `tests/opt/test_mesh_check.py`, `tests/opt/test_femread.py` |
| V-OR-6 | 템플릿 API: 등록(복사·sha), 공개 목록(다른 사용자·다른 프로젝트에서 보임), 삭제 권한(등록자·관리자 허용, 그 외 403), 사용 중 → ARCHIVED·미사용 → 행 삭제 + `_backup` 이동, 보관 템플릿 새 실행 거부·기존 실행 retry 허용, `PLATE_CHANGED` | `backend/tests/test_opt_templates.py` |
| V-OR-7 | 덱: `server` 없을 때 기존 골든 바이트 불변, 있을 때 DOPTPRM·OUTPUT·S2 법선 정렬 골든 | `tests/library/test_optdeck*.py` |
| V-OR-8 | OS_SOLVE 가짜 솔버(`tests/fake_optistruct.py`: 정상·check 실패·라이선스 2회 후 성공·소진·종료코드 1·타임아웃·취소) → 상태·코드·재시도 횟수·세마포어 반납 | `worker/tests/test_opt_solve.py` |
| V-OR-9 | argv: 허용 argv[0] 외 `CONFIG_INVALID`, 메타문자·.bat 추가 문자 거부, command 관리자만 | `worker/tests/test_opt_solve.py` |
| V-OR-10 | 세마포어 `max_concurrent_os=1` 동시 2개 → 대기, lease 만료 해제 (PG) | `worker/tests/test_opt_solve.py` |
| V-OR-11 | 재시도 재사용: 후처리 실패 → retry → OS_SOLVE SKIPPED, 덱 sha 다르면 재실행, S1 rad 변경 시 `INPUT_CHANGED` 경고 | `worker/tests/test_opt_e2e.py` |
| V-OR-12 | 후처리: 가짜 shape.csv → bead.npz·csv·PNG(시그니처·결정적 바이트)·bead_mesh.rad 재파싱(좌표 = x0+shape, ID 동일)·bead_mesh.fem | `tests/opt/test_post.py` |
| V-OR-13 | 입력 보호: S1 Case 입력 폴더·S2 업로드 폴더 파일 목록·mtime·sha256 실행 전후 불변, 템플릿 업로드 stale 이동 후에도 실행·retry 성공 | `worker/tests/test_opt_e2e.py` |
| V-OR-14 | API 공통: 권한(viewer 403, 다른 프로젝트 404), `SOLVER_NOT_CONFIGURED`, 다운로드 rel 탈출·symlink, bundle 상한, 보고서 CSP | `backend/tests/test_opt_api.py` |
| V-OR-15 | migration 0010: 빈 DB·0008 DB 업그레이드, 재실행 멱등, `tables.py` 일치, 기존 작업 행 제약 통과, 0009 존재/부재 두 체인 | `backend/tests/test_migrations.py` |
| V-OR-16 | E2E(가짜 솔버·hw): S1(Case → 등록 ESL 2개 → 실행 → SUCCEEDED), S2(템플릿 등록 → 실행 → SUCCEEDED) → 결과·파일·이력·알림 | `worker/tests/test_opt_e2e.py` |
| V-OR-17 | UI: 행 선택·크기 비활성·같은 모델 표시, S1/S2 탭 기본값, 다른 모델 빼기, 템플릿 등록·삭제 권한 표시, 주 버튼 비활성 사유, 진행·결과·재시도, 2560×1440·1920×1080 잘림 없음(Playwright) | `frontend/__tests__/opt.test.tsx`, mock |
| V-OR-18 | 환경 점검: optistruct_path·TCL·`_templates` 쓰기 ↔ `/opt/settings.solver_ready` | `backend/tests/test_check.py` |
| V-OR-R1 | **실기**(운영 서버): S2 작은 평판(약 5 000 요소)·ESL 3개, S1 실제 chassis rear(22만 요소)·ESL 2개로 `-check`·본 실행 수렴·Shape Change 추출·비드 맵이 HyperView 화면과 일치. DTPG·DOBJREF·OUTPUT 확신도 해소 기록 | `docs/manual/opt_run_check.md`(구현 단계) |
| V-OR-R2 | 실기: 실제 라이선스 부족 메시지로 `license_patterns` 확인 | 수동 |

## 15. 단계적 구현 분해 (파일 소유권)

| 단계 | 담당 | 파일(소유) | 완료 조건 |
|---|---|---|---|
| O1 코어 | Impl-Core | `esl/opt/__init__.py`, `mesh_check.py`(공통 검사·frame·법선), `femread.py`(신규 fem 파서), `identity.py`(topo_sha256·동일성 — `results_csv.canon_conn` 재사용), `size.py`(S2 크기 — 백엔드 import), `target.py`(CaseTarget·TemplateTarget), `osout.py`(.out 파싱·라이선스/수렴), `post.py`, `png.py`, `report_opt.py`; `esl/library/analysis.py`(`direct_nodal` 옵션만), `esl/library/optdeck.py`(`server` 옵션만), `esl/library/entry.py`(등록 시 topo_sha256 메타); `resources/tcl/esl_bead_post.tcl`; `tests/opt/*` | V-OR-1~5, 7, 12 |
| O2 백엔드 | Impl-Backend | `migrations/versions/0010_opt_runs.py`, `core/db/tables.py`, `core/job_types.py`, `core/config.py`(OptRunCfg·altair·commands), `core/paths.py`(`OPT_DIR`·`TEMPLATE_DIR`), `core/repositories/opt.py`(runs·templates), `core/repositories/jobs.py`(`acquire_os`), `api/routers/opt.py`, `api/services/opt.py`(runs·s1-check), `api/services/opt_templates.py`, `api/schemas.py`, `api/services/library.py`(entries size·topo 지연 백필), `api/services/uploads.py`(purpose 제외), `api/services/history.py`, `check.py`, `config/*.example.yaml`, `backend/tests/test_opt_api.py`·`test_opt_templates.py`·`test_migrations.py` | V-OR-2(API), 6, 14, 15, 18 |
| O3 워커 | Impl-Worker | `worker/esl_worker/localproc.py`(h3d 공통화 — `h3d.py` 최소 수정), `os_solve.py`, `opt_jobs.py`(S1 Case 경로 해석·S2 템플릿 경로), `executor.py`(OPT_RUN 디스패치), `core_adapter.py`(opt_prep/opt_load/opt_deck/opt_post), `register.py`(OPT_REGISTER), `worker/tests/test_opt_*.py`, `tests/fake_optistruct.py` | V-OR-8~11, 13, 16 |
| O4 프런트 | Impl-Frontend | `api/opt.ts`, `api/types.ts`, `api/history.ts`, `pages/opt/OptNew.tsx`(S1/S2 탭), `OptDetail.tsx`, `OptList.tsx`, `pages/opt/Templates.tsx`(목록·등록·삭제), `pages/library/LibraryList.tsx`(행 선택·크기 필터·같은 모델 표시·탭), `pages/library/AnalysisDetail.tsx`(진입), `app/App.tsx`, `mock/optdata.ts`, `__tests__/opt.test.tsx`, `pages/guide/*` | V-OR-17 |
| O5 문서 | Plan/Impl | `CHANGELOG.md`·`VERSION` 0.7.0, `docs/decisions.md`, `docs/manual/user.md`, `docs/manual/opt_run_check.md` | V-OR-R1 체크리스트 |

- 순서: O1 → (O2 ∥ O3, O3 는 O2 의 job_types·tables·config 선행) → O4(mock 병행) → 통합 E2E → 실기 V-OR-R1. S2(평판) 먼저 실기 → S1(대형) 실기.
- 경계: 백엔드는 코어 `esl.opt.size`·`identity`·`mesh_check`·`femread`(템플릿 check 동기, 요소 상한 안에서 수 초)만 import. S1 대형 rad 파싱은 워커에서만(s1-check 는 DB topo_sha256 와 Case 입력 존재만 확인).

## 16. 후속 (v0.7.0 범위 밖)
- **CAD/STEP 템플릿**: STEP 업로드 → 서버 메싱(HyperMesh 배치 또는 별도 메셔, argv 템플릿) → 쉘 메시 템플릿 등록. 메셔·요소 크기·중립면 추출 방식은 별도 계약.
- 3D 비드 보기(view3d GLB 재사용), HPC 제출, 비드 반영 메시 자동 검증 낙하.

## 17. 확정 사항 (2026-10-28, 사용자)

| 질문 | 확정 | 반영 |
|---|---|---|
| Q1 평판 메시 형식 | 시나리오 2개로 재구성: S1 Case rad 대상 파트, S2 템플릿 `.rad`·`.fem`(CAD/STEP 후속) | §3, OR-D-3~9, §16 |
| Q2 같은 크기 기준 | A — 같은 인치 + 치수 ESL 간 ±2 %, 평판/템플릿 ±5 %. S2 에 적용, S1 은 모델 동일성 | OR-D-4·7, §7 |
| Q3 비드 방향 | 지금 덱과 같음(+n, BOUNDS 0~1) | OR-D-10, §8.2 |
| Q4 라이브러리 반영 | A — 넣지 않음, "최적화 실행" 목록에 보존 | OR-D-15 |
| Q5 라이선스 부족 | A — 3회 × 300 초 자동 재시도 후 실패 | OR-D-12, §8.3 |
| 템플릿 공개·삭제 | 모든 사용자 공개(C), 삭제 = 등록자·관리자, 사용 중이면 보관 | OR-D-8, §12·§13 |
| S1 다른 모델 ESL | 선택 불가 + 템플릿 최적화 안내(자동 전환 없음) — 계약 결정 | OR-D-5 |

## 18. 미결 질문

- **Q1 S1 요소 법선 처리**: (A) 원 모델 연결 순서 그대로(반대 법선 요소 수·위치 경고만) (B) 법선이 n 과 충분히 평행(|cos| ≥ 0.5)한 요소만 +n 쪽으로 정렬해 덱·`bead_mesh` 에 반영. **권장 A** — S1 결과 메시는 제품 모델에 그대로 넣으므로 원 연결 순서를 바꾸지 않는 편이 안전, chassis 측벽처럼 n 과 수직인 면은 정렬 기준이 없음.
- **Q2 템플릿 인치 입력**: (A) 선택 입력(없으면 치수 ±5 % 만 검사) (B) 등록 시 필수. **권장 A** — 평판 템플릿은 특정 인치에 묶이지 않을 수 있고, 치수 검사만으로 크기 불일치는 걸러짐.
