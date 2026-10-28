# 계약: 비드 최적화 서버 실행 (OPT_RUN, v0.7.0)

- 상태: **초안** (2026-10-28, Plan). 구현 코드 없음. 맨 끝 "미결 질문" 답을 받은 뒤 확정한다.
- 버전: **v0.7.0** (v0.6.0은 `esl_upload_speed.md`가 사용).
- 대체 범위: `esl_p2_library.md` §4 "실행은 사용자 측(Windows/HPC)… 결과 회수·후처리는 P3", `esl_p3_ux.md` §7 "OptiStruct 비드 덱 실행은 P4" 중 **서버 워커 실행** 부분. HPC/PBS 제출은 여전히 범위 밖. 충돌 시 이 문서 우선. 종합분석(LIB_ANALYZE)의 덱 생성은 **그대로 유지**한다(PC에서 직접 돌리는 사용자용).
- ID 규칙: 결정 `OR-D-n`, 요구 `OR-n`, 시험 `V-OR-n`, 리스크 `R-OR-n`.
- 사용자 확정 사항(2026-10-28, 변경 금지): ① 라이브러리에서 ESL 여러 개 선택(라이브러리·종합분석 화면 연결) ② 서버 워커에서 직접 실행(OPT_RUN, 기존 워커·작업 대기열 재사용, 사용자 PC 실행 아님) ③ 하중 매핑은 현재 방식 — 정규화 좌표 (ξ,η) 24×14 셀 합력·합모멘트 ④ 설계 대상은 새 평판 메시 업로드(기존 청크 업로드 재사용) ⑤ 크기(인치/치수)가 다른 ESL은 사용 불가, 기본은 같은 크기만 선택 가능 ⑥ 저장소의 DTPG 덱 생성 코드(`esl/library/optdeck.py`)를 서버 실행으로 연결 ⑦ UI 필수 버튼만, 2560×1440 기준(1920×1080 잘림 없음), 환경별 경로·솔버 경로는 설정 파일, 하드코딩 금지, 입력 폴더 쓰기 금지.

## 0. 현황 조사 (main f44c2c5, v0.5.9)

| 항목 | 위치 | 현재 동작 |
|---|---|---|
| DTPG 덱 생성 | `esl/library/optdeck.py write(target_mesh, load_cases, support_321, design, out_dir)` | `.fem`(GRID/CQUAD4/CTRIA3/PSHELL/MAT1 + SUBCASE별 FORCE·SPC1 + DTPG + DRESP1 COMP + DESOBJ(MINMAX)/DOBJREF 또는 WCOMP) + `esl_loads.inc` + `run_optistruct.bat` + README. DTPG 방향 = 요소 법선(NORM 없음), `bounds [0,1]`, SKIP=BC 고정. **DOPTPRM·OUTPUT 카드 없음**. 3-2-1 rank 검사(`SUPPORT_DEGENERATE`). 이 환경에서 OptiStruct 실행 검증 이력 없음(확신도 표기) |
| 덱 실행 흐름 | `worker/esl_worker/core_adapter.py _lib_optdeck` | LIB_ANALYZE 의 OPTDECK step 이 `_analysis/<id>/opt/` 에 덱만 쓴다. **실행·회수 없음** |
| 대상 메시 | `esl/library/analysis.py run(entries, target)` | 대상 = 라이브러리 항목(`LibraryEntry`: raw node_id·x0·conn·elem_type·elem_pid·thickness·E·nu, meta frame·grid·mesh_sha256). 대상 지지 = 그 항목 Case 의 3-2-1. **업로드 메시 대상 없음** |
| 매핑 | `esl/library/mapping.py to_target(summary, mesh, frame)` | 셀 (nx×ny, 기본 24×14) 합력·합모멘트 → 대상 셀 노드 최소노름 분배 + 전체 평형 보정(`equilibrate`) |
| 정규화 좌표계 | `esl/library/normalize.py frame()` | 면적 가중 PCA 평면 + `axis_ref`(ξ≈+X, η≈+Z) 부호 고정, `L_xi`·`L_eta`·`z_range` |
| 크기 정보 | `library_entries.model.inch`, `library_entries.summary.frame.{L_xi,L_eta}` | DB에 이미 있음. 분석 생성 시 크기 검사 없음(`normalization` 옵션으로 인치 차 보정) |
| 업로드 | `api/services/uploads.py`, `core/uploads.py` | 청크·이어 올리기·sha256, `<upload_root>/<user>/<UTC>_<name>/`. complete 검사는 **Case 전용**(rad + h3d|결과 폴더 필수) |
| rad 파서 | `esl/rad/parser.py parse_rad(path, part_title, …)`, `list_parts` | 대상 파트만 숫자 해석(쉘 QUAD4/TRIA3, LAW1/2/36 E·ν, 두께), include 해석 |
| rad 쓰기 | `esl/rad/writer.py write_rad(…)` | 쉘 메시 + PART/PROP/MAT 출력 |
| 3-2-1 자동 | `esl/mech/supports.py pca_corners`, `pick_321` | 면내 PCA 극점 4개 → 3-2-1 dof 배정 |
| 외부 실행 | `worker/esl_worker/h3d.py`, `executor._run_h3d` | LOCAL step, argv 템플릿(argv[0] `{hw}`), shell=False, 메타문자 거부, 프로세스 트리 종료(POSIX killpg / Windows Job), DB 세마포어 `altair.max_concurrent_hw`(step outputs `hw_acquired`) |
| 명령 규칙 원형 | `esl.md` §4.4 | `{optistruct}` → `altair.optistruct_path`, 템플릿 키 `os_solve`(placeholder `optistruct, fem, nt, work_dir`) 정의만 있고 **미구현** |
| 작업 | `core/job_types.py` | 7종(CASE_EXTRACT…LIB_COMPARE), stage 1~9, `jobs.case_id|analysis_id|comparison_id` 중 하나 |
| DB | `migrations/versions` 0001~0008 | 0009 = MCP(`esl_mcp_ready.md`) **예약**(미구현). 0006·0007·0008 모두 멱등 `IF NOT EXISTS`, downgrade 미지원 관례 |
| 화면 | `pages/library/LibraryList.tsx`, `AnalysisNew.tsx`, `AnalysisDetail.tsx` | 목록에 행 선택 없음. 분석 생성은 필터로 항목 선정 |

## 1. 범위 / 비범위

| 범위 (v0.7.0) | 비범위 |
|---|---|
| 라이브러리 목록 행 선택 + 크기 그룹 제한, 종합분석 상세에서 진입 | HPC/PBS 제출, 원격 서버 실행 |
| 평판 메시 업로드(기존 청크 업로드) + 평판 검사 API | 평판 메시 자동 생성(CAD), 형상 최적화(DSHAPE)·두께 최적화 |
| 작업 `OPT_RUN`(SLOT): 평판 준비 → 매핑 → 덱 → OptiStruct 실행 → 후처리 → 등록 | 비드 반영 모델로 Radioss 검증 낙하 자동 실행(사용자가 새 Case로) |
| OptiStruct 경로·동시 실행 수·라이선스 재시도 설정 | 3D 비드 보기(GLB) — v0.7.x 후보 |
| 결과: 비드 높이 노드값, 2D 맵 PNG, 수렴 이력, 비드 반영 메시(rad/fem), HTML 보고서, 원본 h3d/out 다운로드 | 라이브러리 항목으로 자동 등록(§9.4, 미결 Q4) |
| migration 0010, 시험, 사용 가이드·CHANGELOG | 인치 간 정규화(`mass`·`inch2`) — 같은 크기만 허용하므로 `none` 고정 |

## 2. 결정

| ID | 결정 | 근거 |
|---|---|---|
| OR-D-1 | 새 작업 종류 **`OPT_RUN`**(lane SLOT, stage **10** "비드 최적화"), 대상 테이블 **`opt_runs`**. LIB_ANALYZE 를 확장하지 않는다 | 분석(덱만)과 실행(솔버·라이선스·수 시간)은 수명·실패 양상이 달라 상태·재시도·권한을 분리해야 함. 분석 코드는 함수 단위로 재사용 |
| OR-D-2 | 매핑·덱은 기존 코어 함수 재사용: `analysis.run(entries, target=PlateTarget)` → `analysis.optdeck_load_cases` → `optdeck.write`. 평판은 `LibraryEntry`와 같은 인터페이스(`raw`·`meta.frame`·`meta.grid`·`mesh()`)의 어댑터 `PlateTarget` | 확정 ③ "현재 방식 유지" — 매핑 알고리즘 변경 0 |
| OR-D-3 | 크기 일치 = **같은 인치**(양쪽 다 있을 때) **AND** `L_xi`·`L_eta` 상대차 ≤ `opt_run.size.tol_rel`(기본 0.02, 선택 ESL 간) / 평판↔ESL 대표 ≤ `opt_run.size.plate_tol_rel`(기본 0.05). 서버가 생성 시 강제(422 `SIZE_MISMATCH`), 화면은 같은 규칙으로 미리 막음. 덮어쓰기 옵션 없음 | 확정 ⑤. 값은 미결 Q2 |
| OR-D-4 | 인치 정규화 = `none` 고정(옵션 숨김) | 같은 크기만 들어오므로 정규화가 필요 없음, 결과 해석 단순 |
| OR-D-5 | 평판 형식 = Radioss `.rad`(+include) 1개, 대상 파트는 `/PART` title(파트가 1개면 자동). 기존 `parse_rad` 재사용 | 미결 Q1(권장안). E·ν·두께·PID 를 같은 규칙으로 얻음 |
| OR-D-6 | 평판 3-2-1 지지 = `pca_corners` + `pick_321` 자동(평판 꼭지점 근처). API 로 노드 지정 가능(화면엔 표시만) | 자기평형 하중 + 정정 구속(결정 P1a 자유물체 규약)과 동일 |
| OR-D-7 | 비드 방향: 평판 요소 법선을 정규화 좌표 n(=ξ×η, 후면 바깥) 쪽으로 **연결 순서 정렬**(뒤집힌 요소는 덱에서 연결 순서 반전, 수 기록) 후 DTPG 기본(요소 법선), `bounds [0,1]` | 법선 불일치 시 비드가 요소마다 반대로 생김. 방향 선택은 미결 Q3 |
| OR-D-8 | OptiStruct 실행 = 워커 LOCAL step, argv 템플릿 `commands.os_check`·`commands.os_solve`(argv[0] `{optistruct}` → `altair.optistruct_path`), shell=False, 메타문자 거부, 동시 실행 수 DB 세마포어 `altair.max_concurrent_os`. 먼저 `-check`(문법) 후 본 실행 | `esl.md` §4.4 원형 구현. 덱 카드 확신도(중상)를 실행 전에 걸러 라이선스·시간 낭비 방지 |
| OR-D-9 | 라이선스 부족은 자동 대기 재시도(`opt_run.solve.license_retry` max 3 × 300 s) 후 `OS_LICENSE_UNAVAILABLE` 실패 | 미결 Q5(권장안) |
| OR-D-10 | 재시도(기존 `POST /jobs/{id}/retry`) 시 `solve/solve.json`의 덱 sha256 이 같고 성공 표식이 있으면 OS_SOLVE 를 **SKIPPED(재사용)** 로 두고 후처리만 다시 | 후처리 실패로 수 시간 해석을 다시 돌리지 않음 |
| OR-D-11 | 후처리 = HyperView 배치 TCL(`resources/tcl/esl_bead_post.tcl`, 기존 `{hw}` 템플릿 규칙)이 `<deck>_des.h3d` 마지막 반복의 Shape Change(노드 벡터)를 CSV 로 → Python 이 비드 높이·PNG·비드 반영 메시·보고서. PNG 는 표준 라이브러리(zlib)로 직접 인코딩(새 의존성 없음) | h3d 는 비공개 포맷(결정 P1a), 서버에 HyperView 있음(P3-UX §6) |
| OR-D-12 | 입력 보호: 업로드 폴더는 읽기만. 실행 생성 시 평판 rad(+include)를 `<esl_root>/_opt/<id>/plate/input/`로 **복사**(sha256 기록)해 이후 업로드 정리와 무관하게 재현 | 확정 ⑦ "입력 폴더 쓰기 금지", 업로드 stale 정리(72 h) 대비 |
| OR-D-13 | 결과는 라이브러리 항목으로 등록하지 않는다. 라이브러리 화면에 "최적화 실행" 목록(보조 탭)으로만 노출, 비드 반영 메시로 검증 낙하 후 새 Case → 등록 → 버전 비교(기존 §12.2) | 라이브러리 = 낙하 ESL 저장소 의미 유지. 미결 Q4 |
| OR-D-14 | migration **0010**(0009 는 MCP 예약). 0009 가 아직 없으면 0010 `down_revision="0008"`, 이후 MCP migration 은 revision id `"0009"`·`down_revision="0010"`으로 체인에 붙인다(파일명 번호 ≠ 적용 순서, decisions.md 기록) | 사용자 지시 "0009 는 MCP 예약". 두 migration 모두 멱등이라 순서 무관 |

## 3. 사용 시나리오 (단계별)

1. **ESL 고르기** — 라이브러리 목록(`/esl/p/:pid/library`)에서 행 체크박스로 ESL 선택. 첫 선택 행이 기준이 되어 크기가 다른 행은 체크박스가 비활성(툴팁 "크기 다름: 65형 1452×826 — 기준 75형 1662×948"). 상단 "크기" 필터로 그룹만 보기 가능. 선택 ≥1 이면 목록 위 보조 버튼 **"선택한 ESL로 비드 최적화 (n)"** 활성.
   - 대안 진입: 종합분석 상세(`/library/analyses/:id`)의 보조 버튼 "이 분석의 씬으로 비드 최적화" → 분석의 `entry_ids` 로 채워짐(크기 혼합이면 가장 많은 크기 그룹만 남기고 제외 목록 경고).
2. **새 최적화 화면**(`/esl/p/:pid/opt/new?entries=<id,…>` 또는 `?analysis=<id>`) — ① ESL 카드: 선택 목록·크기 그룹 요약(인치·L_xi×L_eta·씬 수), 행 빼기만 가능.
3. **평판 메시 올리기** — ② 평판 카드: `.rad`(+include) 끌어다 놓기 또는 파일 선택 → 기존 청크 업로드(`POST /uploads` … `PUT …/files/{i}`) → 완료 시 자동 `POST /opt/plate-check`. 결과: 파트 선택(2개 이상일 때만 드롭다운), 노드·요소 수, 크기 비교(평판 vs ESL, 통과/불일치), 품질 표(경고·오류), PID 표(설계 체크박스, 기본 전부 설계), 자동 3-2-1 노드 표시.
4. **옵션** — ③ 옵션 카드(필수만): 목적 `minmax`(기본)/`weighted`, 하중 케이스 "모든 씬(기본)/대표+최악", 비드 최소폭·높이·각도(설정 기본값 채움). 제목(선택).
5. **실행** — 주 버튼 **"최적화 실행"**(검사 오류 0, 크기 통과, 솔버 준비됨일 때만 활성) → `POST /opt/runs` → 상세 화면으로 이동.
6. **진행 확인** — 상세(`/esl/p/:pid/opt/:id`): step 진행 막대(6 step), OptiStruct 반복 n/DESMAX·목적값, 라이선스 대기 표시, 로그(기존 작업 로그 뷰어), 취소(기존 작업 취소).
7. **결과** — 비드 높이 2D 맵(PNG), 수렴 그래프, 요약 표(반복 수·수렴 여부·subcase 별 컴플라이언스 초기/최종·비드 면적 비율), 다운로드(비드 반영 메시 rad/fem, 비드 노드 CSV, h3d·out, 덱, 보고서, 전체 zip), "보고서 보기"(새 탭).
8. **다음 단계(안내 문구만)** — 비드 반영 메시(`bead_mesh.rad`)를 제품 모델에 반영해 낙하 해석 → 새 Case → 라이브러리 등록 → 버전 비교(수렴 판정).

## 4. 데이터 흐름

```
library_entries(선택, 같은 크기) ─┐
                                  ├─ POST /opt/runs ─ opt_runs 행 + OPT_RUN 작업(QUEUED)
uploads(평판 rad) ─ plate-check ──┘        │  (평판 rad → _opt/<id>/plate/input/ 복사, sha256)
                                           ▼ 워커(SLOT)
 1 OPT_PREP   (INTERNAL) parse_rad → 품질·frame·크기 재검사·법선 정렬·3-2-1 → plate/plate.npz, plate.json
 2 OPT_MAP    (INTERNAL) analysis.run(entries, PlateTarget, normalization=none) → map/analysis.json, mapped_loads.npz
 3 OPT_DECK   (INTERNAL) optdeck.write(+server 카드) → deck/esl_bead.fem, esl_loads.inc, optdeck.json
 4 OS_SOLVE   (LOCAL)    세마포어 → deck 복사 solve/ → optistruct -check → optistruct (라이선스 재시도) → solve.json
 5 OPT_POST   (LOCAL+INTERNAL) hw TCL: _des.h3d Shape Change → post/shape.csv → bead.npz·bead_nodes.csv·
                          bead_map.png·history.csv·bead_mesh.rad·bead_mesh.fem → report.html
 6 OPT_REGISTER (DB)     opt_runs.result 요약·report_rel, artifacts
```

- 폴더: `<esl_root>/_opt/<opt_run_id>/` (`core/paths.py OPT_DIR = "_opt"`, `esl_subdir` 안전 경로). 하위 `plate/ map/ deck/ solve/ post/ report.html opt.json`. 각 step 은 시작 시 자기 하위 폴더를 `fresh_dir`(이전 내용 `_backup/<UTC>/`로 이동, 삭제 없음).
- 코어(esl)는 DB를 모른다: 워커 `core_adapter` 가 spec 으로 경로·옵션을 넘김(기존 lib 단계와 같은 방식).

## 5. API (접두 `/esl/api`, 기존 오류 형식 `{"detail":{"code","message",...}}`, 비GET `X-ESL-Request: 1`)

### 5.1 엔드포인트

| 메서드·경로 | 요청 | 응답 | 오류 |
|---|---|---|---|
| `GET /opt/settings` | – | `OptSettingsOut` | – |
| `POST /opt/plate-check` | `PlateCheckIn` | `200 PlateCheckOut` | 404 `UPLOAD_NOT_FOUND`, 409 `UPLOAD_NOT_READY`, 422 `PLATE_INVALID`·`PART_NOT_FOUND`·`PART_AMBIGUOUS` |
| `POST /opt/runs` | `OptRunIn` | `201 OptRunOut`(+`job`) | 422 `ENTRY_NOT_FOUND`·`SIZE_MISMATCH`·`PLATE_INVALID`·`INVALID_PARAMS`, 409 `PLATE_CHANGED`·`UPLOAD_NOT_READY`, 503 `SOLVER_NOT_CONFIGURED` |
| `GET /opt/runs?project_id=&limit=&cursor=` | – | `[OptRunOut]`(최신 순) | 404 `PROJECT_NOT_FOUND` |
| `GET /opt/runs/{id}` | – | `OptRunOut`(result 포함) | 404 `OPT_RUN_NOT_FOUND` |
| `GET /opt/runs/{id}/files` | – | `[{rel, kind, size, too_large}]` | 404 |
| `GET /opt/runs/{id}/download?rel=` | – | 파일(첨부). `rel` 은 files 목록 안만 | 404 `FILE_NOT_FOUND`, 413 |
| `GET /opt/runs/{id}/bundle?parts=result,deck,solve` | – | 스트리밍 zip(`ui.max_bundle_bytes`) | 413 `BUNDLE_TOO_LARGE` |
| `GET /opt/runs/{id}/report` | `?download=1` | HTML, CSP 는 분석 보고서와 같음 | 404 `REPORT_NOT_READY` |
| `GET /opt/runs/{id}/bead-map.png` | – | `image/png`(ETag) | 404 `RESULT_NOT_READY` |
| 기존 `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retry`, `GET /jobs/{id}`·로그 | – | OPT_RUN 에도 동일 적용 | – |
| 기존 `GET /library/entries` | – | 응답에 `size:{inch, L_xi, L_eta}` 추가(DB 기존 값, 계산 없음) | – |

### 5.2 스키마

```text
OptSettingsOut  { enabled: bool, solver_ready: bool, solver_reason: str|null,
                  size: {tol_rel, plate_tol_rel, require_inch},
                  bead_defaults: {min_width, height, angle}, objectives: ["minmax","weighted"],
                  deck_cases: ["all","representative+worst"], max_cases, plate_max_elems, allowed_ext: [".rad",".inc"] }

PlateCheckIn    { project_id, upload_id, part_title?: str, entry_ids: [id] (1..max_entries) }
PlateCheckOut   { ok: bool, plate_sha256,                  # 업로드 rad+include 내용 sha256(정렬 결합)
                  rad_rel, parts: [{part_id, title, n_elems}], part_title,
                  mesh: {n_nodes, n_elems, n_quad, n_tria, unsupported: {type: count}},
                  pids: [{pid, title, n_elems, thickness, E, nu, design_default: true}],
                  frame: {L_xi, L_eta, z_range, warnings[]},
                  size: {ok, esl: {inch, L_xi, L_eta}, plate: {L_xi, L_eta}, rel_diff: {xi, eta}, reason?},
                  quality: {errors: [{code, message}], warnings: [{code, message, value?, limit?}],
                            metrics: {elem_size_median, min_width_over_elem, nodes_per_cell_median,
                                      flatness_rel, normals_flipped, components, dup_nodes, max_aspect, max_warp_deg}},
                  supports_auto: [{node_id, dof}] (3) }

OptRunIn        { project_id, title?: str(≤200), entry_ids: [id] (1..max_entries), analysis_id?: id,
                  plate: {upload_id, part_title?, plate_sha256},
                  design: {nondesign_pids?: [int], bead?: {min_width, height, angle}},
                  options: {objective?: "minmax"|"weighted", deck_cases?: "all"|"representative+worst",
                            supports?: [{node_id, dof}] (3)} }
OptRunOut       { id, project_id, title, entry_ids, analysis_id, size, plate: {part_title, sha256, n_nodes, n_elems,
                  file_name}, design, options, job: JobOut|null, state (= 작업 상태), created_by_name, created_at,
                  result: OptResult|null, report_ready: bool }
OptResult       { converged: bool, iterations, desmax, objective: {initial, final, history: [..]},
                  subcases: [{label, entry_id, comp_initial, comp_final}], n_subcases, deck_reduced: bool,
                  bead: {height_max, area_frac (|h| ≥ 0.1·BH 인 설계 면적 비율), n_design_elems},
                  solve: {seconds, license_waits, reused: bool}, warnings: [str] }
```

- `max_entries` = `opt_run.max_entries`(기본 200). 덱 subcase 상한은 기존 `optdeck.max_cases`(60) 자동 축소 규칙 그대로.
- 모든 응답 경로는 기존 `DisplayJSONResponse` 규칙(표시용 정규화). 업로드 절대경로는 응답에 넣지 않는다(`file_name`만).

### 5.3 오류 코드 (신규)

| 코드 | HTTP/작업 | 의미 |
|---|---|---|
| `SIZE_MISMATCH` | 422 / OPT_PREP | 선택 ESL 간 또는 평판↔ESL 크기 불일치(`reason`: inch|xi|eta, 값·한도) |
| `PLATE_INVALID` | 422 / OPT_PREP | 평판 검사 오류 1개 이상(quality.errors 동봉) |
| `PLATE_ELEM_UNSUPPORTED` | quality.errors 코드 | QUAD4/TRIA3 외 요소 |
| `PLATE_TOO_LARGE` | quality.errors 코드 | 요소 수 > `opt_run.plate.max_elems` |
| `PLATE_CHANGED` | 409 / OPT_PREP | plate-check 이후 업로드 내용 sha256 변경 |
| `UPLOAD_NOT_READY` | 409 | 업로드 파일 미완료·취소·stale |
| `SOLVER_NOT_CONFIGURED` | 503 | `altair.optistruct_path` 없음·실행 파일 없음·`opt_run.enabled: false` |
| `OS_DECK_INVALID` | 작업 | `-check` 실패(.out 의 ERROR 줄 앞 20줄 메시지) |
| `OS_LICENSE_UNAVAILABLE` | 작업 | 라이선스 패턴 감지 + 재시도 소진 |
| `OS_SOLVE_FAILED` | 작업 | 종료코드≠0, 오류 패턴, 필수 출력 없음 |
| `OS_TIMEOUT` | 작업 | `opt_run.solve.timeout_h` 초과(프로세스 트리 종료) |
| `BEAD_POST_FAILED` | 작업 | Shape Change 추출 실패·노드 불일치 |
| 기존 재사용 | | `ENTRY_NOT_FOUND`, `SUPPORT_DEGENERATE`, `MAPPING_DEGENERATE`, `GRID_MISMATCH`, `SOLVER_OUT_OF_MEMORY`, `INPUT_INVALID`, `CONFIG_INVALID`, `PREREQUISITE_MISSING` |

- 미수렴(DESMAX 도달)은 **실패가 아님**: 작업 SUCCEEDED + `result.converged=false` + 경고 "최대 반복 도달 — 결과는 마지막 반복".

## 6. 작업 종류 · 워커 단계 · 진행률/로그

### 6.1 `job_types.py`

```python
"OPT_RUN": JobTypeDef("OPT_RUN", 10, "SLOT", (
    StepDef("OPT_PREP", "opt_prep"), StepDef("OPT_MAP", "opt_map"), StepDef("OPT_DECK", "opt_deck"),
    StepDef("OS_SOLVE", None, kind="LOCAL"), StepDef("OPT_POST", "opt_post", kind="LOCAL"),
    StepDef("OPT_REGISTER", None))),
```
- `OPT_JOB_TYPES = ("OPT_RUN",)`, `OPT_STAGES = ("opt_prep","opt_map","opt_deck","opt_post")`. 작업 대상 = `jobs.opt_run_id`(case_id·analysis_id·comparison_id NULL).
- 같은 opt_run 에 QUEUED/RUNNING 작업이 있으면 retry 409 `JOB_ACTIVE`(기존 규칙).

### 6.2 단계별 요구

- OR-1 **OPT_PREP**: `plate/input/` 의 rad 로 `parse_rad(part_title)` → 품질 검사(§7.2) 재실행(생성 시점 검사와 같은 함수) → `frame()`(라이브러리 `axis_ref`) → 크기 재검사(§7.1, DB 가 아니라 항목 `entry.json` 의 frame 으로) → 법선 정렬(OR-D-7) → 3-2-1(`options.supports` 또는 자동, rank 검사) → 비설계 PID 반영 → `plate.npz`(node_id, x0, elem_id, elem_type, conn(정렬 후), elem_pid, thickness, E, nu, design) + `plate.json`(frame, grid = 라이브러리 grid, mesh_sha256, supports, quality, flipped 수).
- OR-2 **OPT_MAP**: `PlateTarget(plate.npz, plate.json)` 로 `analysis.run(entries, target, opts={normalization:"none", deck_cases, max_cases, 나머지 library 설정})`. 대상 자신의 항목이 없으므로 모든 ESL 이 셀 매핑. 셀당 노드 중앙값 < `convergence.min_nodes_per_cell`(64)이면 경고. 산출 `map/analysis.json`·`mapped_loads.npz`·`envelope.csv`.
- OR-3 **OPT_DECK**: `optdeck.write(mesh, load_cases, supports, design, deck/)` + 서버 실행 카드(§8.2). `run_optistruct.bat`·README 는 그대로 생성(다운로드한 사용자가 PC에서도 돌릴 수 있게). `optdeck.json` 에 덱 sha256.
- OR-4 **OS_SOLVE**(LOCAL): §8.
- OR-5 **OPT_POST**(LOCAL+INTERNAL): §9.
- OR-6 **OPT_REGISTER**: `opt_runs.result`(OptResult), `report_rel`, `artifacts` 등록(`kind`: `optdeck`, `opt_result`, `opt_solve`, `report`), 알림(기존 notifications) "비드 최적화 완료/실패".

### 6.3 진행률·로그

| step | 진행률 산정 | 로그(기존 step 로그 파일, 마스킹 유지) |
|---|---|---|
| OPT_PREP | 0→100 (파싱 60·검사 30·저장 10) | 노드·요소·PID·크기·품질 경고 |
| OPT_MAP | 항목 k/K | 항목별 매핑 잔차·평형 보정량 |
| OPT_DECK | 0→100 | subcase 수·축소 여부·설계/비설계 요소 |
| OS_SOLVE | check 5% + 반복 `n/DESMAX` × 95% (`.out` 을 `cancel_check_interval_s` 마다 꼬리 읽기, `ITERATION n` 줄) | argv(관리자만 command 열람), `.out` 새 줄 중계(최대 `opt_run.solve.log_tail_lines`), 세마포어 대기·라이선스 대기 "라이선스 부족 — 300초 후 다시 시도 (1/3)" |
| OPT_POST | hw 50 · 후처리 50 | Shape Change 노드 수·비드 최대 높이 |

- 작업 `progress` 표시 = 6 step 가중(1·1·1·85·10·2 %). 화면 step 목록에 OS_SOLVE 반복 수·목적값 보조 줄.

## 7. 입력 검증

### 7.1 크기 일치 (OR-7)
- 기준(anchor) = 선택 첫 ESL. 각 ESL `e`: (가) `opt_run.size.require_inch: true` 이고 anchor·e 모두 `model.inch` 가 있으면 같아야 함. 한쪽이 null 이면 치수만 보고 경고 `INCH_UNKNOWN`. (나) `|L_xi(e)−L_xi(a)|/L_xi(a) ≤ tol_rel` 그리고 η 도 같음.
- 평판: ESL 그룹 대표 치수 = 선택 ESL `L_xi`·`L_eta` 중앙값. `|L_plate − L_rep|/L_rep ≤ plate_tol_rel` (ξ, η 각각). 위반 → `SIZE_MISMATCH`.
- ESL 정규화 격자(nx×ny)가 서로 다르면 `GRID_MISMATCH`(기존).
- 검사 시점 3곳: 화면(즉시), `POST /opt/plate-check`·`POST /opt/runs`(DB `summary.frame` 값), OPT_PREP(항목 파일 값 — 불일치 시 실패, DB·파일 차이는 경고 기록).

### 7.2 평판 메시 품질·형식 (OR-8)

| 검사 | 오류(실행 불가) | 경고 |
|---|---|---|
| 파일 | `.rad` 0개 또는 2개 이상, include 누락, 파싱 실패 | 파트 2개 이상(선택 필요) |
| 요소 | QUAD4/TRIA3 외 존재(`PLATE_ELEM_UNSUPPORTED`), 요소 수 > `max_elems`(기본 500 000) | TRIA3 비율 > 20 % |
| 재료·두께 | 두께 ≤ 0, E·ν 해석 불가(설정 override 없음) | – |
| 연결 | 미사용 노드만 있는 경우 제외 후 요소 0 | 연결 성분 > 1, 일치 노드(거리 ≤ 1e-6·bbox) 존재 |
| 평탄도 | – | `z_range/max(L_xi,L_eta)` > `flat_tol_rel`(0.02) "평판 아님(굴곡 형상)" |
| 법선 | – | n 과 반대인 요소 수 > 0 → "연결 순서 자동 정렬 n개"(OR-D-7) |
| 요소 크기 | – | 비드 최소폭 MW < 2 × 요소 크기 중앙값 → "비드 폭이 요소에 비해 작음"(OptiStruct 권장) |
| 매핑 해상도 | – | 셀당 노드 중앙값 < 64 |
| 형상 | – | 최대 종횡비 > 10, 최대 뒤틀림 > 15° (값 표시만) |
| 3-2-1 | 자동 선택 rank < 6(`SUPPORT_DEGENERATE`) | – |

- 비설계 PID 를 제외하면 설계 요소 0 → `PLATE_INVALID`("설계 요소가 없음").
- plate-check 는 결과를 `uploads.result`(`{"purpose":"plate", ...PlateCheckOut 요약}`)에 저장하고 업로드를 COMPLETED 로 바꾼다(Case 화면 업로드 목록은 `purpose=plate` 제외). 업로드 폴더에는 쓰지 않는다.

## 8. 솔버 실행 (OS_SOLVE)

### 8.1 실행 규칙 (OR-9)
- 작업 폴더 `solve/`: `fresh_dir` 후 `deck/` 의 `esl_bead.fem`·`esl_loads.inc` 복사(덱 원본 보존). 스크래치 `solve/tmp/`.
- argv: `commands.os_check` → 성공 시 `commands.os_solve`. argv[0] = `{optistruct}` 만, placeholder `optistruct, fem, fem_fwd, nt, work_dir, scratch, mem_mb`. 치환값 검사·shell=False·프로세스 트리 종료·작업별 제한기(Windows Job / POSIX RLIMIT)는 `h3d.py` 와 같은 함수(공통 모듈로 이동, §13).
- `cwd = solve/`, env = 기존 `worker.env_passthrough`(예 `ALTAIR_LICENSE_PATH`) + 설정 `opt_run.solve.env`(키 허용 목록: `ALTAIR_LICENSE_PATH`, `ALTAIR_HOME`, `OMP_*`). 실행 직전 argv 를 `job_steps.command`에 저장.
- 동시 실행: DB 세마포어 `acquire_os`(advisory lock 키 신규, step outputs `os_acquired`, `altair.max_concurrent_os` 기본 1). 대기 중 lease 갱신·취소 확인.
- 성공 판정(본 실행): 종료코드 0 + `.out` 에 `opt_run.solve.error_patterns` 불일치 + 필수 출력 `<deck>.out`, `<deck>_des.h3d` 존재. `-check` 성공: 종료코드 0 + 오류 패턴 불일치.
- 수렴 판정: `.out` 의 수렴 문구(`opt_run.solve.converged_patterns`, 기본 `"OPTIMIZATION HAS CONVERGED"`) → converged; 반복 수 = 마지막 `ITERATION n`.
- 종료 시 `solve/solve.json` `{deck_sha256, argv, exit_code, seconds, iterations, converged, license_waits, ok:true}`. `solve/tmp/` 는 지우지 않고 다음 실행의 `fresh_dir` 때 `_backup/<UTC>/`로 옮긴다(삭제 없음 원칙 유지, 용량 정리는 운영).

### 8.2 덱 서버 카드 (OR-10, `optdeck.write(design={"server": {...}})`)
- `server` 키가 있을 때만 추가(기존 LIB_ANALYZE 덱 출력 바이트 불변 — 골든 시험 유지):
  - `DOPTPRM, DESMAX, <opt_run.solve.desmax>`(기본 30) [확신도 상]
  - `OUTPUT, H3D, ALL` 및 설계 이력 h3d(`_des.h3d`) 기본 출력 확인 [확신도 중상 — 실기 V-OR-R1]
  - 법선 정렬 반영 연결 순서, 헤더에 `opt_run <id>`.

### 8.3 라이선스 부족·실패·재시도 (OR-11)
- 라이선스 감지: 종료코드≠0 이고 stdout/`.out` 에 `opt_run.solve.license_patterns` 일치(기본 `["(?i)license.*(not available|checkout failed|insufficient|exceeded)", "(?i)ALM_\\w+_ERROR", "(?i)units? (are )?not available"]`).
- 재시도: `license_retry.max`(3)회, 대기 `wait_s`(300) — 대기 중 세마포어 **반납**, 취소 즉시 반영, step 상태 RUNNING + outputs `license_waits`. 소진 → `OS_LICENSE_UNAVAILABLE`.
- 그 밖 실패는 자동 재시도 없음. 사용자 재시도 = 기존 `POST /jobs/{id}/retry`(power 이상, 새 작업). OR-D-10 재사용 규칙: `solve.json.ok` + 덱 sha256 동일 → OS_SOLVE SKIPPED("이전 해석 재사용"), OPT_PREP·MAP·DECK 는 다시 실행해 sha 를 비교(빠름).
- 시간 제한 `timeout_h`(12) → 트리 종료 `OS_TIMEOUT`. 메모리 한도 초과 → `SOLVER_OUT_OF_MEMORY`(기존).
- 워커 재시작·lease 상실: 기존 INTERRUPTED 처리 + OptiStruct 트리 종료.

## 9. 결과물 (OPT_POST)

### 9.1 추출 (OR-12)
- `commands.bead_post`(argv[0] `{hw}`, placeholder `hw, post_tcl_fwd, h3d_fwd, out_dir_fwd, request_fwd`) 로 `resources/tcl/esl_bead_post.tcl` 실행 → `post/shape.csv`(node_id, dx, dy, dz; 마지막 반복 Shape Change), `post/done.json`. hw 세마포어(`altair.max_concurrent_hw`) 공유.
- 검사: node_id 집합 = plate node_id(불일치 → `BEAD_POST_FAILED`).

### 9.2 산출 (OR-13)

| 파일 | 내용 |
|---|---|
| `post/bead.npz` | node_id, shape (N,3), h = shape·n_i(노드 법선 성분), design mask |
| `post/bead_nodes.csv` | node_id, x0, y0, z0, h, dx, dy, dz |
| `post/bead_map.png` | (ξ,η) 평면 2D 맵, 요소 채움색 = 요소 평균 h(0→BH, 순차 색), 비설계 회색, 3-2-1 기호, 색 범례·축 mm. 크기 `opt_run.post.png_px`(기본 1600×900). 순수 Python 래스터 + zlib PNG |
| `post/history.csv` | iteration, objective, (subcase별 comp) — `.out` 파싱 |
| `post/bead_mesh.rad` | x0 + shape 좌표의 평판(원 ID·PID·두께·재료 유지, `write_rad`) — 검증 낙하용 |
| `post/bead_mesh.fem` | 같은 메시 OptiStruct bulk(GRID/CQUAD4/CTRIA3/PSHELL/MAT1) |
| `report.html` | 자체 완결 HTML(기존 보고서 규칙): 입력 ESL 표·크기, 평판 요약·품질, 매핑(셀 포락), 덱 설정, 수렴 그래프(inline SVG), 비드 맵(inline SVG), subcase 컴플라이언스 초기/최종, 한계(선형 ESL·매핑 근사·비드 반영 후 검증 낙하 필요) |
| `opt.json` | OptResult 원본 |

- 다운로드 목록(files): 위 + `deck/*`, `solve/<deck>.out`·`.h3d`·`_des.h3d`·`.hist`·`.stat`(있으면). 큰 파일은 `too_large`(> `ui.max_artifact_bytes`)면 bundle 로만.

### 9.3 원본 보존
- `solve/` 의 OptiStruct 원본 출력은 수정하지 않는다. 후처리는 `post/` 에만 쓴다.

### 9.4 라이브러리 반영
- 하지 않음(OR-D-13). `opt_runs` 목록을 라이브러리 화면 보조 탭과 실행 이력(`/history`, job_type 필터 "비드 최적화")에 노출.

## 10. 화면 (최소 UI, 2560×1440 기준 · 1920×1080 잘림 없음)

- 공통: 화면당 주 버튼 1개, 오른쪽 서랍(대기열·워커) 기존 그대로. 1920 폭에서 카드 2열 → 1열 접힘(`min-width` 기준 `ui/fit-viewport` 규칙), 가로 스크롤 없음.

### 10.1 라이브러리 목록 (변경)
```
[라이브러리]  [항목 | 종합분석 | 버전 비교 | 최적화 실행]            (탭: 보조)
필터: 모델[▼] 크기[75형 1662×948 ▼] 씬유형[☑꼭지점☑모서리☑면] 판정[PASS만▼]
선택 3개 · 기준 75형 1662×948      [선택한 ESL로 비드 최적화 (3)]  [종합분석 만들기](주)
┌☐┬모델────┬인치┬크기(mm)──┬씬──────────────┬판정┬오차┐
│☑│75QN80H │75 │1662×948 │17 Corner 146 2nd│PASS│0.4%│
│☐̸│65QN80H │65 │1452×826 │…  (비활성: 크기 다름)        │
```
### 10.2 새 비드 최적화 `/opt/new`
```
새 비드 최적화                                                     [최적화 실행](주, 비활성 사유 툴팁)
┌① ESL (3개 · 75형 · 1662×948)──────────┐┌② 평판 메시──────────────────────────────┐
│ 75QN80H v072 17 Corner 146  [빼기]    ││ [.rad 끌어다 놓기 / 파일 선택]  ███ 72%  │
│ …                                     ││ 파트: plate_v1 · 노드 48 210 · 요소 47 600│
└───────────────────────────────────────┘│ 크기 1660×950 ✓ (ESL 대비 −0.1 % / +0.2 %)│
┌③ 옵션─────────────────────────────────┐│ 품질: 오류 0 · 경고 1 [펼치기]           │
│ 목적 (●minmax ○weighted)              ││ PID  제목   요소   두께  설계            │
│ 하중 (●모든 씬 ○대표+최악)            ││ 1    plate 47 000 1.0  ☑               │
│ 비드 폭 10.0  높이 3.0  각도 60°       ││ 2    mount   600  1.0  ☐               │
│ 제목 [            ]                   ││ 3-2-1: 101(123) 2201(23) 4410(3) 자동    │
└───────────────────────────────────────┘└──────────────────────────────────────────┘
솔버 미설정이면 상단 경고 띠: "서버 OptiStruct 경로가 설정되지 않았습니다(관리자 문의)"
```
### 10.3 최적화 상세 `/opt/:id`
```
비드 최적화 · 75형 강건 비드 1차      상태 실행 중 (OS_SOLVE 반복 12/30)   [보고서 보기](주, 완료 후)
┌진행──────────────────────────────────────────┐┌결과(완료 후)─────────────────────────────┐
│ ✓평판 준비 ✓매핑 ✓덱 ●OptiStruct ○후처리 ○등록││ [bead_map.png]                          │
│ 목적값 1.00 → 0.62 (반복 12)  라이선스 대기 0  ││ 수렴 그래프                              │
│ [로그 보기] [취소]                            ││ 수렴 ✓ 반복 18 · 비드 면적 34 %           │
└──────────────────────────────────────────────┘│ subcase 표(초기/최종 컴플라이언스)        │
                                                 │ 받기: [비드 메시 .rad] [.fem] [전체 zip]  │
                                                 └──────────────────────────────────────────┘
```
- 실패 시 결과 카드 자리에 오류 코드·메시지 + [다시 시도](power 이상, 기존 retry).

## 11. 설정 키 (`config/esl_platform*.example.yaml`, 하드코딩 금지)

```yaml
altair:
  optistruct_path: "C:/Program Files/Altair/2026.1/hwsolvers/scripts/optistruct.bat"   # 예시. 없으면 OPT_RUN 비활성(503)
  max_concurrent_os: 1                  # 동시 OptiStruct 수(라이선스 한도) — DB 세마포어
commands:                               # argv[0] = {optistruct} | {hw}
  os_check: ["{optistruct}", "{fem}", "-check", "-tmpdir", "{scratch}"]
  os_solve: ["{optistruct}", "{fem}", "-nt", "{nt}", "-tmpdir", "{scratch}"]
  bead_post: ["{hw}", "-clientconfig", "hwpost.dat", "-b", "-tcl", "{post_tcl_fwd}", "-input", "{h3d_fwd}", "-output", "{out_dir_fwd}", "-config", "{request_fwd}"]
opt_run:                                # 섹션이 없으면 enabled: false
  enabled: true
  max_entries: 200
  size: {tol_rel: 0.02, plate_tol_rel: 0.05, require_inch: true}
  plate: {max_elems: 500000, flat_tol_rel: 0.02, max_tria_frac: 0.2}
  solve:
    nt: 4                               # 작업 제한기 코어 수를 넘으면 그 값으로 줄임(경고)
    desmax: 30
    timeout_h: 12
    log_tail_lines: 2000
    error_patterns: ["(?m)^\\s*\\*\\*\\* ERROR"]
    converged_patterns: ["OPTIMIZATION HAS CONVERGED"]
    license_patterns: ["(?i)license.*(not available|checkout failed|insufficient|exceeded)", "(?i)ALM_\\w+_ERROR"]
    license_retry: {max: 3, wait_s: 300}
    env: {}                             # 허용 키만(ALTAIR_LICENSE_PATH, ALTAIR_HOME, OMP_*)
  post: {png_px: [1600, 900]}
upload:
  allowed_ext: [...기존]                # .rad/.inc 이미 포함 — 변경 없음
```
- 비드 기본값·목적·subcase 상한·id_offset 은 기존 `library.yaml optdeck` 그대로 사용(중복 키 만들지 않음).
- 설정 검증: `optistruct_path` 는 실행 파일만(공백 허용), 환경 점검(`check.py`)이 존재·`-version` 실행 가능 여부·`esl_bead_post.tcl` 존재를 표시. 알 수 없는 키 `CONFIG_INVALID`(기존 규칙, `opt_run` 은 섹션 단위로 선택).
- TCL 경로는 설정이 아니라 코드 스냅샷 `resources/tcl/esl_bead_post.tcl`(기존 추출 TCL 과 같은 원칙).

## 12. DB 변경 — migration `0010_opt_runs`

- 번호: HEAD 0008, 0009 = MCP 예약 → **0010**. 체인 규칙 OR-D-14. 멱등(`IF NOT EXISTS`/`checkfirst`), downgrade 미지원(기존 관례, 호출 시 `NotImplementedError`).
- `opt_runs`: `id` PK, `project_id` NOT NULL, `title` varchar(200), `entry_ids` JSONB NOT NULL(배열 ≥1), `analysis_id` FK analysis_runs NULL, `size` JSONB NOT NULL(`{inch, L_xi, L_eta, tol_rel, plate_tol_rel}`), `plate` JSONB NOT NULL(`{upload_id, file_name, part_title, sha256, n_nodes, n_elems, L_xi, L_eta}`), `design` JSONB NOT NULL, `options` JSONB NOT NULL, `job_id` NULL(최신 작업), `result` JSONB NULL, `report_rel` NULL, `dir_rel` NOT NULL(`_opt/<id>`, CHECK 상대·`..` 금지), `created_by`, `created_by_name`, `created_at`, `updated_at`. Index `(project_id, created_at desc)`.
- `jobs.opt_run_id` FK opt_runs NULL. 제약 교체(DROP CONSTRAINT IF EXISTS → ADD): `ck_jobs_job_type`(OPT_RUN 추가), `ck_jobs_stage` `BETWEEN 1 AND 10`, `ck_jobs_subject`(OPT_RUN 은 `opt_run_id NOT NULL`, 나머지 셋 NULL; 기존 분기는 `opt_run_id IS NULL` 추가). Index `jobs(opt_run_id)`.
- `artifacts.kind` 허용 목록에 `opt_result`, `opt_solve` 추가(`ARTIFACT_KINDS`).
- `uploads` 변경 없음(`result.purpose` JSONB 키).

## 13. 보안 · 권한

- 권한: 조회(GET) = ACTIVE 로그인 + 프로젝트 조회 권한, `plate-check`·`POST /opt/runs`·retry·cancel = 프로젝트 `power` 이상, 남의 작업 취소·대기열 = 전역 관리자(기존). 판정 순서 401→404→403→409.
- 업로드: 본인 업로드만(`_owned`), `upload_root` 본인 폴더 격리·`_backup` 거부·심링크 거부(기존 함수). plate-check 는 업로드 폴더 **읽기만**. 업로드 밖 include 는 거부(Case 와 달리 확인 후 허용 없음 — 평판은 단일 파일 기대).
- 외부 실행: 워커 LOCAL step 에서만, argv 템플릿 + 허용 argv[0] + 치환값 메타문자 거부 + shell=False. 덱 파일명·경로는 서버가 만든 값만(사용자 문자열 미포함; 제목은 덱 주석에 ASCII 이스케이프로만).
- 경로: 다운로드 `rel` 은 files 목록 일치만, `realpath` 가 `_opt/<id>/` 안인지 확인. 응답에 서버 절대경로 없음(`file_name`, `rel` 만). `job_steps.command` 는 전역 관리자만.
- 자원: OptiStruct 는 작업 제한기(메모리·코어) 안에서 실행, `-nt` ≤ 제한 코어. 동시 수 세마포어. 디스크: 실행 생성 시 `esl_root` 여유 < `upload.min_free_gb` 면 507 `INSUFFICIENT_STORAGE`.
- 보고서 HTML CSP·inline JSON 이스케이프는 기존 규칙(`esl.report.html.json_text`).
- 로그 마스킹 패턴 유지(라이선스 서버 주소는 마스킹 대상 아님 — 단 `password|token` 패턴 적용).

## 14. 검증 계획

| ID | 시험 | 위치 |
|---|---|---|
| V-OR-1 | 크기 규칙: 같은 인치·치수 ±2 % 통과, 2.1 % 거부, 인치 null 경고, 평판 ±5 % 경계, 화면·API·OPT_PREP 결과 일치 | `tests/opt/test_size.py`, `backend/tests/test_opt_api.py`, `frontend/__tests__/opt.test.tsx` |
| V-OR-2 | 평판 검사: 비지원 요소·두께 0·요소 상한·연결 성분·일치 노드·평탄도·법선 반전 n개·MW/요소 크기·셀당 노드·3-2-1 퇴화 — 각 오류/경고 코드 | `tests/opt/test_plate.py` |
| V-OR-3 | PlateTarget 로 `analysis.run` — 합성 평판 + 합성 ESL 3개: 셀 합력·합모멘트 보존(상대 1e-9), 평형 보정, 기존 대상 항목 경로와 같은 결과(같은 메시를 항목/평판 두 경로로) | `tests/opt/test_map.py` |
| V-OR-4 | 덱: `server` 없을 때 기존 골든 바이트 불변, 있을 때 DOPTPRM·OUTPUT 카드·법선 정렬 연결 순서 골든 | `tests/library/test_optdeck*.py` |
| V-OR-5 | OS_SOLVE 가짜 솔버(`tests/fake_optistruct.py` — `.out`·`_des.h3d` 생성, 시나리오: 정상·check 실패·라이선스 2회 후 성공·라이선스 소진·종료코드 1·타임아웃·무한 대기 취소) → 상태·코드·재시도 횟수·세마포어 반납 | `worker/tests/test_opt_solve.py` |
| V-OR-6 | argv: 허용 argv[0] 외 `CONFIG_INVALID`, 치환값 메타문자 거부, .bat 추가 문자, command 저장·관리자만 열람 | `worker/tests/test_opt_solve.py`, `backend/tests/test_opt_api.py` |
| V-OR-7 | 세마포어: `max_concurrent_os=1` 에서 OPT_RUN 2개 동시 → 하나 대기 로그, lease 만료 시 해제 | `worker/tests/test_opt_solve.py` (PG) |
| V-OR-8 | 재시도 재사용: 후처리 실패 → retry → OS_SOLVE SKIPPED, 덱 sha 다르면 재실행 | `worker/tests/test_opt_e2e.py` |
| V-OR-9 | 후처리: 가짜 shape.csv → bead.npz·csv·PNG(시그니처·크기·결정적 바이트)·bead_mesh.rad 를 `parse_rad` 로 다시 읽어 좌표 = x0+shape·ID 동일·bead_mesh.fem 카드 수 | `tests/opt/test_post.py` |
| V-OR-10 | 입력 보호: 실행 전후 업로드 폴더 파일 목록·mtime·sha256 불변, `_opt/<id>/plate/input` sha 기록, 업로드 stale 이동 후에도 retry 성공 | `worker/tests/test_opt_e2e.py` |
| V-OR-11 | API: 권한(viewer 403, 다른 프로젝트 404, 남의 업로드 404), `PLATE_CHANGED`, `UPLOAD_NOT_READY`, `SOLVER_NOT_CONFIGURED`, 다운로드 rel 탈출·symlink 거부, bundle 상한, 보고서 CSP | `backend/tests/test_opt_api.py` |
| V-OR-12 | migration 0010: 빈 DB·0008 DB 업그레이드, 재실행 멱등, `tables.py` 와 스키마 일치, 기존 작업 행 제약 통과, 0009 존재/부재 두 체인 | `backend/tests/test_migrations.py` |
| V-OR-13 | E2E(가짜 솔버·가짜 hw): 업로드 → plate-check → 실행 → SUCCEEDED → 결과·파일·이력·알림 | `worker/tests/test_opt_e2e.py` |
| V-OR-14 | UI: 행 선택·크기 비활성·선택 버튼, 분석 상세 진입(혼합 크기 제외 경고), 새 화면 주 버튼 비활성 사유, 진행·결과·실패 재시도, 2560×1440·1920×1080 잘림·가로 스크롤 없음(Playwright 스크린샷) | `frontend/__tests__/opt.test.tsx`, mock |
| V-OR-15 | 환경 점검: optistruct_path 없음/있음, TCL 없음 → `check.py` 표시와 `/opt/settings.solver_ready` 일치 | `backend/tests/test_check.py` |
| V-OR-R1 | **실기(운영 서버, 사용자 실행)**: 작은 평판(약 5 000 요소)·ESL 3개로 `-check` 통과, 본 실행 수렴, `_des.h3d` Shape Change 추출, 비드 맵이 HyperView 화면과 일치. DTPG 필드 순서·DOBJREF·OUTPUT 카드 확신도 해소 기록 | 수동 체크리스트 `docs/manual/opt_run_check.md`(구현 단계에서 작성) |
| V-OR-R2 | 실기: 라이선스 부족 시 실제 메시지로 `license_patterns` 확인·조정 | 수동 |

## 15. 단계적 구현 분해 (파일 소유권)

| 단계 | 담당 | 파일(소유) | 완료 조건 |
|---|---|---|---|
| O1 코어 | Impl-Core | `esl/opt/__init__.py`, `esl/opt/plate.py`(parse·품질·frame·크기·법선·3-2-1), `esl/opt/target.py`(PlateTarget), `esl/opt/size.py`(크기 규칙 — 백엔드도 import), `esl/opt/osout.py`(.out 파싱·라이선스/수렴 판정), `esl/opt/post.py`(bead·csv·rad/fem), `esl/opt/png.py`, `esl/opt/report_opt.py`; `esl/library/optdeck.py`(`server` 옵션·법선 정렬만 추가); `resources/tcl/esl_bead_post.tcl`; `tests/opt/*` | V-OR-1~4, 9 |
| O2 백엔드 | Impl-Backend | `migrations/versions/0010_opt_runs.py`, `core/db/tables.py`, `core/job_types.py`, `core/config.py`(`OptRunCfg`, `altair.optistruct_path/max_concurrent_os`, commands), `core/paths.py`(`OPT_DIR`), `core/repositories/opt.py`, `core/repositories/jobs.py`(`acquire_os`), `api/routers/opt.py`, `api/services/opt.py`, `api/schemas.py`(Opt*), `api/services/library.py`(entries `size`), `api/services/uploads.py`(purpose=plate 목록 제외), `api/services/history.py`(OPT_RUN 라벨·요약), `check.py`, `config/*.example.yaml`, `backend/tests/test_opt_api.py`, `test_migrations.py` | V-OR-11, 12, 15 |
| O3 워커 | Impl-Worker | `worker/esl_worker/localproc.py`(신규: `h3d.py` 의 argv 검사·start·트리 종료 공통화 — h3d.py 는 이를 호출하도록 최소 수정), `worker/esl_worker/os_solve.py`(신규), `worker/esl_worker/opt_jobs.py`(준비·plate 복사), `executor.py`(OPT_RUN 디스패치·LOCAL step 분기), `core_adapter.py`(opt_prep/opt_map/opt_deck/opt_post), `register.py`(OPT_REGISTER), `worker/tests/test_opt_*.py`, `tests/fake_optistruct.py` | V-OR-5~8, 10, 13 |
| O4 프런트 | Impl-Frontend | `frontend/src/api/opt.ts`, `api/types.ts`(Opt*), `api/history.ts`(라벨), `pages/opt/OptNew.tsx`, `pages/opt/OptDetail.tsx`, `pages/opt/OptList.tsx`(라이브러리 탭), `pages/library/LibraryList.tsx`(행 선택·크기 필터·보조 버튼·탭), `pages/library/AnalysisDetail.tsx`(진입 버튼), `app/App.tsx`(라우트), `mock/optdata.ts`, `__tests__/opt.test.tsx`, `pages/guide/*`(비드 최적화 카드) | V-OR-14 |
| O5 문서 | Plan/Impl | `CHANGELOG.md`·`VERSION` 0.7.0, `docs/decisions.md`, `docs/manual/user.md`, `docs/manual/opt_run_check.md` | V-OR-R1 체크리스트 |

- 순서: O1 → (O2 ∥ O3 — O3 는 O2 의 job_types·tables·config 를 먼저 받음) → O4(mock 으로 O2 와 병행 가능) → 통합 E2E → 실기 V-OR-R1.
- 경계: 백엔드는 코어 `esl.opt.size`·`esl.opt.plate.check` 만 import(plate-check 동기 실행, 요소 상한 안에서 수 초). 그 밖 코어는 워커 자식 프로세스에서만.

## 16. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-OR-1 | DTPG·DOBJREF·OUTPUT 카드와 `_des.h3d` Shape Change 결과명이 실행 검증된 적 없음(확신도 중상) | `-check` 선행, 가짜 솔버로 흐름 시험, V-OR-R1 실기로 확정 후 정식 공지. 필요 시 `card_format: fixed` |
| R-OR-2 | 라이선스 경합(HyperView 추출·사용자 PC 작업과 공유) → 장시간 대기·실패 | `max_concurrent_os`, 자동 대기 재시도, 대기 표시, 재시도 시 해석 재사용 |
| R-OR-3 | 서버 자원: OptiStruct 장시간 실행이 SLOT 을 점유해 Case 작업 지연 | 작업 제한기 메모리·코어, `-nt` 상한, `max_concurrent_os` 1 기본, 타임아웃 |
| R-OR-4 | 정규화 좌표 매핑은 기하 비례 가정 — 평판과 실제 chassis 의 마운트·보스 위치 차이 | 같은 크기만 허용, 보고서 한계 명시, 셀당 노드 경고, 비드 반영 후 검증 낙하 안내 |
| R-OR-5 | 평판 법선 불일치·굴곡 형상 → 비드 방향 오류 | 법선 자동 정렬·평탄도 경고·결과 맵에서 h 부호 표시 |
| R-OR-6 | migration 번호 체인(0010 이 0009 보다 먼저 적용) 혼동 | OR-D-14 규칙, V-OR-12 두 체인 시험, decisions 기록 |

## 17. 미결 질문 (결과를 바꾸는 것만)

- **Q1 평판 메시 형식**: (A) Radioss `.rad`만 (B) OptiStruct/Nastran `.fem`만 (C) 둘 다. **권장 A** — 기존 `parse_rad`(E·ν·두께·PID·include) 재사용으로 새 파서·검증 부담 0, `.fem`은 v0.7.x 추가.
- **Q2 "같은 크기" 기준**: (A) 인치 같음 + 치수 ESL 간 ±2 %·평판 ±5 % (B) 인치만 같으면 허용 (C) 치수만(±2 %/±5 %, 인치 무시). **권장 A** — 같은 인치라도 파생 모델 치수가 다를 수 있고, 인치 메타 누락 항목도 치수로 거를 수 있음.
- **Q3 비드 방향**: (A) 후면 바깥(+n) 한쪽 (B) 안쪽(−n) 한쪽 (C) 양방향 허용(BOUNDS −1~1). **권장 A** — 현재 덱 기본(BOUNDS 0~1)과 같고 제조(프레스) 방향이 한쪽이라 해석이 명확.
- **Q4 최적화 결과의 라이브러리 반영**: (A) 반영 안 함, 라이브러리 화면 "최적화 실행" 탭에만 표시 (B) 비드 반영 메시를 다음 "설계 버전" 표식으로 저장해 버전 비교에서 연결. **권장 A** — 라이브러리는 낙하 ESL 저장소로 유지, 버전 연결은 검증 낙하 Case 등록 시 기존 버전 비교로 충분.
- **Q5 라이선스 부족 시 동작**: (A) 자동 대기 재시도(3회 × 5분) 후 실패 (B) 즉시 실패 + 사용자가 다시 시도 (C) 라이선스가 날 때까지 무기한 대기(취소만 가능). **권장 A** — 짧은 경합은 자동 흡수, 장기 부족은 실패로 드러나 SLOT 점유를 막음.
