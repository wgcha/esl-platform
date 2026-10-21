# 계약: P3-이력 — 실행 이력 목록과 과거 실행 다시 확인

- 상태: **확정** (2026-10-21, §9 미결 3건 사용자 확인: 내보내기·보고서 작업별 파일 보존 = 예, 조회 = ACTIVE 사용자 전체 유지, t* 확정 이력 = 이번 범위 밖). 사용자 요청: "실행 이력 목록이 있어서 다시 확인하는 기능".
- 사용자 확정(2026-10-21):
  - 위치: (a) Case 화면 안 '실행 이력' 탭(그 Case 작업, 시간순) + (b) 프로젝트 전체 실행 이력 페이지(필터·검색).
  - 다시 확인 범위: ① 로그·입력값(params)·오류(실패 코드·메시지)·소요 시간 보기, ② 그때 결과 다시 열기(과거 ESL run, 검증, t*, 추출, 내보내기를 그 시점 값으로 읽기 전용 열람).
- ID 규칙: 결정 `H-n`, 시험 `V-H-n`.

## 0. 현황 조사 (main, 2026-10-21)
| 대상 | 저장 | 실행별 보존? |
|---|---|---|
| 작업 자체 | `jobs`(params·result·warnings·failure_*·queued/started/finished_at·created_by) + `job_steps`(step별 상태·시각·exit_code·failure_*·log_rel·command) | 보존(행 삭제 없음). `jobs.result` = step별 코어 기록 + `registered`(등록 요약) |
| 로그 | `<case>/logs/<job_id>/step_NN_<key>.log`(라이브러리 작업은 `_analysis/<id>/…`) | 보존(작업 id 폴더) |
| 추출 요약·t* | `cases.extract_summary`·`cases.tstar`, 파일 `01_extract`·`02_tstar` | **덮어쓰기**. 과거 값은 해당 CASE_EXTRACT `jobs.result.registered.{extract,tstar}`에만. 사용자 t* 확정(`PUT /tstar`)은 작업이 아니라 이력 없음 — 단 ESL run 행에 사용한 frame_index·metric이 남음 |
| ESL run | `esl_runs` 행(실행별) + 파일 `runs/<run_id>/{03_bc,04_esl}` 스냅샷 | 보존(P1b 이후 실행). 그 이전 실행은 스냅샷 없음(`legacy`) |
| 검증 | `validations` 행(실행별, hotspots·field 요약·verdict·criteria) + 파일 `runs/<run_id>/05_val`(그 run의 **최신 검증만**, 표식 `platform_validation_id.txt`) | 행은 보존. 같은 run의 이전 검증 파일은 `_backup/<ts>/runs/<run_id>/05_val`로 이동(표식 포함) → 현재 `field`·`section` API는 409 `VALIDATION_FILES_GONE` |
| 내보내기 | `06_export`(파일), 요약은 EXPORT `jobs.result.registered.files·targets·id_range` | **덮어쓰기**(이전 것은 `_backup/<ts>/06_export`, 어느 작업 것인지 표식 없음). `artifacts`는 `(case_id, rel)` upsert라 job_id도 최신으로 바뀜 |
| Case 보고서 | `07_report/report.html` | **덮어쓰기**(이전 것 `_backup`) |
| 라이브러리 분석·비교 | `analysis_runs`·`comparisons` 1행 + 같은 폴더 재실행(_backup) | 최신 작업 결과만 |
- 기존 API: `GET /cases/{id}/jobs`(최신 100개 고정, 페이지 없음, 필터 없음), `GET /jobs/{id}`(steps 포함, command 제외), `GET /jobs/{id}/log`(step·cursor, 마스킹), `POST /jobs/{id}/retry`, `GET /queue`, `GET /cases/{id}/esl-runs`, `GET /esl-runs/{id}`(+`/forces` — 스냅샷이 있으면 과거 run도 됨), `GET /cases/{id}/validations`, `GET /validations/{id}`(+`/field`·`/section`), `GET /cases/{id}/tstar`(현재 파일 기준), `GET /cases/{id}/artifacts`.
- 권한 현황: 모든 GET은 인증된 ACTIVE 대시보드 사용자면 가능(프로젝트 역할 검사 없음). `job_steps.command`는 어떤 API에도 나오지 않음.
- 인덱스 현황: `ix_jobs_case_created(case_id, created_at desc)`만. 프로젝트 범위 목록용 인덱스, `esl_runs.job_id`·`validations.job_id` 인덱스 없음.

## 1. 범위 / 비범위
- 범위: 이력 목록 2곳(Case 탭·프로젝트 페이지), 작업 상세(개요·입력값·오류·소요 시간·step·로그), 과거 결과 읽기 전용 열람(추출 요약·t*·ESL run·검증·내보내기·Case 보고서), 과거 결과와 현재 결과의 다른 점 표시, 이후 내보내기·보고서 파일 보존(§4), 목록 인덱스(migration 0007).
- 비범위: 재실행·새 버튼으로 재시도(기존 `POST /jobs/{id}/retry`·화면 그대로), zip(기존 `bundle` 그대로), 과거 결과로 검증·내보내기·라이브러리 등록 같은 후속 작업, 라이브러리 분석·비교의 과거 결과 값(목록에는 나오고 '열기'는 현재 상세 화면으로), 이력 삭제·보존 기간 정리, `_backup` 일반 찾아보기, 사용자 t* 확정 이력 기록.

## 2. 결정
- **H-1** 이력의 단위는 `jobs` 행 1개. 새 이력 테이블을 만들지 않는다(행 삭제가 없고 필요한 값이 이미 있음).
- **H-2** 과거 결과의 값은 **DB에 기록된 그 시점 값**(job.result.registered, esl_runs, validations 행)으로 보여 주고 현재 입력으로 다시 계산하지 않는다. 파일이 필요한 보기(하중표·전 요소 비교·단면·내보내기 파일·보고서)는 §4 보존 파일이 있을 때만.
- **H-3** 결과 보존 수준 `result_availability`: `full`(값 + 파일), `summary`(DB 값만 — 파일은 이전 버전 실행이라 보존 안 됨 또는 `_backup`으로 이동), `none`(결과 없는 작업: 실패·취소·대기·실행 중, 또는 등록 전 실패). 화면은 `summary`일 때 "파일 보존 안 됨 — 기록된 값만 표시"를 한 줄 표시.
- **H-4** `_backup` 처리: API는 `_backup`을 목록·다운로드로 노출하지 않는다(P3-UX 보안 규칙 유지). 예외는 **표식으로 정확히 식별되는 검증 파일**뿐 — `_backup/*/runs/<run_id>/05_val/platform_validation_id.txt`가 그 검증 id와 같을 때 읽기 전용으로 `field`·`section`에 사용. 탐색은 Case 폴더 안 realpath 검사, 최신 순, 최대 `history.backup_scan_max`(기본 100) 폴더, 심링크 무시.
- **H-5** 이후 실행분부터 내보내기·Case 보고서를 작업별로 보존: EXPORT·CASE_REPORT 등록 성공 직후 워커가 `06_export`(또는 `07_report/report.html`)를 `<case>/history/<job_id>/`로 **복사**(심링크 제외, `.tmp` 후 rename, 실패해도 작업은 성공 + warning `HISTORY_ARCHIVE_FAILED`). 기존 `_backup` 이동 규칙은 그대로. 이 폴더는 bundle·artifacts 등록 대상 아님(용량 = 실행당 export/report 크기, 보통 수십 MB 이하).
- **H-6** stale(입력 바뀐 뒤) 표시 규칙 — 결과 상태 `result_state`:
  - `current`: 그 결과가 Case의 현재 결과이고 입력이 그대로(ESL: `is_current && !stale`; 검증: 현재 run의 최신 검증; 추출: `extract_summary.job_id == job.id`; 내보내기·보고서: 같은 종류 최신 성공 작업).
  - `past`: 그 외 모두. 배지 "과거 실행 · <완료 시각(로컬)>".
  - 추가 칩 "입력 바뀜"(`stale_reasons` 비어 있지 않을 때): `extract`(이후 재추출), `part_title`, `tstar`(frame·metric 다름), `support_set`(지지점 다름), `input_files`(rad·h3d 지문 변경 — `changed_inputs`). 서버가 run 값과 현재 Case 값을 비교해 계산(ESL·검증·내보내기는 대상 run 기준, 추출·t*는 `extract`·`part_title`·`input_files`만).
- **H-7** "현재와 다른 점" `diff`: 서버가 키별 `{key, label, past, current}`를 최대 12개 만든다(같으면 생략, 현재 결과가 없으면 `current: null`). 키 고정 목록 — 추출: part_title·n_elems·n_frames·tstar.frame_index·tstar.metric·tstar.value; ESL: frame_index·metric·support_node_ids·kabsch.bc_residual·forces.total_norm; 검증: verdict·disp_rms_rel·reaction_rel·hotspot_max_err·criteria; 내보내기: targets·id_range·files 수·validation_verdict. 값 형식은 JSON 그대로(화면이 단위·자릿수 처리).
- **H-8** 권한: 이력 목록·상세·로그·과거 결과 조회 = ACTIVE 사용자(기존 GET과 동일, 프로젝트 역할 검사 없음). `job_steps.command`(argv)는 **전역 관리자에게만** 상세 응답의 step에 포함(그 외 키 자체 없음). 로그는 기존 마스킹 적용. 재시도는 기존 규칙(본인·전역 관리자, power 이상).
- **H-9** 페이지네이션: keyset 커서(`created_at DESC, id DESC`), `limit` 기본 50·최대 200, 응답 `next_cursor`(불투명 base64url, 위조·형식 오류 422 `INVALID_CURSOR`). 전체 개수 세지 않음(`has_more`만). 정렬은 생성 시각 고정.
- **H-10** "내 작업만" 토글 포함(`mine=true` → `created_by = 본인`) — 프로젝트 페이지에서 공용 서버 다수 사용자의 작업이 섞이므로 필요. Case 탭에는 없음(작업 수 적음).
- **H-11** 라이브러리 작업(LIB_ANALYZE·LIB_COMPARE)은 프로젝트 이력에 나오고 상세(입력값·오류·로그·소요 시간)도 같지만, 결과는 `result_availability = summary`로 `jobs.result` 요약만 + "현재 분석 열기" 링크(과거 값 재현 비범위). 그 작업이 분석의 최신 작업이 아니면 "이후 다시 실행됨" 표시.

## 3. API (prefix `/esl/api`, 모두 GET, 기존 오류 형식)
### 3.1 `GET /history`
- query: `project_id`(필수), `case_id`(선택 — 그 프로젝트 Case가 아니면 404 `CASE_NOT_FOUND`), `job_type`(쉼표 목록, `JOB_TYPES` 밖 422), `state`(쉼표 목록: QUEUED·RUNNING·SUCCEEDED·FAILED·CANCELED·INTERRUPTED), `mine`(bool), `q`(≤100자: Case 제목·폴더명 ILIKE 부분 일치 또는 작업 id 접두 8자 이상, 분석·비교 제목), `from`·`to`(ISO 날짜시각, created_at 범위), `cursor`, `limit`.
- 응답 `{items: HistoryItem[], next_cursor: string|null, has_more: bool}`.
- `HistoryItem` 키: `id, job_type, stage, state, case_id, case_title, case_folder, analysis_id, comparison_id, subject_title, created_by, created_by_name, created_at, queued_at, started_at, finished_at, duration_s`(finished−started, 실행 중이면 지금−started, 미시작 null)`, wait_s`(started−queued)`, current_step_no, progress_pct, failure_code, failure_message, retry_of_job_id, retried_by_job_id`(이 작업을 재시도한 작업, 없으면 null)`, result_ref`(`{kind: "extract"|"esl_run"|"validation"|"export"|"report"|"analysis"|"comparison", id}` | null)`, result_state`(`current`|`past`|null)`, stale`(bool)`, summary`(목록 한 줄용: 추출 = `{n_elems, tstar_frame, tstar_value}`, ESL = `{frame_index, metric}`, 검증 = `{verdict, disp_rms_rel}`, 내보내기 = `{targets, n_files}`, 그 외 null).
- `params`·`result`·`steps` 원문은 목록에 넣지 않는다(성능). `result_state`·`stale`은 목록에서도 계산(Case 행 1회 조회 + run 행 일괄 조회, N+1 금지).

### 3.2 `GET /jobs/{id}/review`
- 응답 `{job, timing, input, error, logs, result}`:
  - `job`: 기존 `JobOut`(steps 포함). 전역 관리자면 각 step에 `command`(argv 배열) 추가.
  - `timing`: `{queued_at, started_at, finished_at, wait_s, duration_s, steps: [{step_no, step_key, started_at, finished_at, duration_s}]}`.
  - `input`: `{params}`(기존 job_out 규칙 — `settings` 제거) + `{settings_summary}`(코어 설정 중 판정 기준·t* 지표·재료 override만, 키 고정) + 추출이면 `{input_fingerprint: [{kind, path, size, mtime}]}`.
  - `error`: 실패·중단이면 `{failure_code, failure_message, failed_step: {step_no, step_key, exit_code, failure_code, failure_message}|null, warnings}`, 아니면 `{warnings}`.
  - `logs`: `[{step_no, step_key, state, has_log, size}]` — 본문은 기존 `GET /jobs/{id}/log?step=&cursor=`로.
  - `result`: `{ref, availability: "full"|"summary"|"none", state: "current"|"past"|null, stale_reasons: string[], files_note: string|null, past: {...}, diff: [{key,label,past,current}], links: {...}}`.
    - `past`(H-2): 추출 = `registered.extract` + `registered.tstar`; ESL = `esl_run_out`(그 run); 검증 = `validation_out` + `has_field`(파일 찾음 여부); 내보내기 = `{targets, id_range, validation_verdict, files:[{name, size, downloadable}], warnings}`; 보고서 = `{verdict, bytes}`; 라이브러리 = `jobs.result` 요약.
    - `links`: 화면 이동용 상대 경로만(예 `{"stage": 4, "query": {"run": "<id>"}}`).
- 404 `JOB_NOT_FOUND`.

### 3.3 과거 결과 파일
- `GET /jobs/{id}/files` → `[{name, size, downloadable}]` — `history/<job_id>/` 아래(EXPORT·CASE_REPORT만, 없으면 404 `HISTORY_FILES_GONE`).
- `GET /jobs/{id}/files/{name}/download` → 파일(이름은 목록에 있는 것만, 경로 구분자·`..` 거부, realpath 검사, `ui.max_artifact_bytes` 초과 413 기존 형식).
- `GET /jobs/{id}/report` → 보관된 Case 보고서 HTML(기존 `/cases/{id}/report`와 같은 응답 헤더·CSP).
- 변경: `GET /validations/{vid}/field`·`/section`의 파일 찾기에 H-4 표식 탐색 추가(실패 시 기존 409 `VALIDATION_FILES_GONE` 유지).
- 변경 없음(이미 과거 run 지원): `GET /esl-runs/{id}`, `/esl-runs/{id}/forces`(스냅샷), `GET /validations/{vid}`.

### 3.4 기존 `GET /cases/{id}/jobs`
- 그대로 둔다(진행 표시용). 이력 화면은 `GET /history?case_id=`를 쓴다.

## 4. DB · 파일
- **migration 0007 필요**(`migrations/versions/0007_history_indexes.py`, Revises 0006, 인덱스만·멱등 `IF NOT EXISTS`, 테이블·컬럼 변경 없음):
  - `ix_jobs_project_created` on `jobs(project_id, created_at DESC, id DESC)`
  - `ix_jobs_project_creator_created` on `jobs(project_id, created_by, created_at DESC)`
  - `ix_jobs_retry_of` on `jobs(retry_of_job_id)` WHERE `retry_of_job_id IS NOT NULL`
  - `ix_esl_runs_job` on `esl_runs(job_id)`, `ix_validations_job` on `validations(job_id)`
  - `tables.py`에 같은 `Index` 선언(0001 create_all과 일치).
- 설정 추가: `history.backup_scan_max`(100), `history.archive_files`(true).
- 파일: `<case>/history/<job_id>/{06_export/…, report.html}`(H-5). `history`는 코어 출력 폴더명과 겹치지 않음을 시험으로 확인.

## 5. 화면 (필수 UI만, 주 버튼 1개 원칙)
- **Case 탭**: Case 메뉴(`case-menu`)에 '실행 이력' → `/p/:projectId/c/:caseId/history`. 표: 시각 · 단계(①~⑥ 아이콘+작업 종류) · 상태 칩 · 소요 시간 · 실행자 · 결과 칩(`현재`/`과거`/`입력 바뀜`) · 한 줄 요약. 필터는 상태(전체/성공/실패·중단)만. 행 클릭 → 상세. 하단 "더 보기"(커서).
- **프로젝트 이력 페이지**: 프로젝트 상단(CaseList) 링크 '실행 이력' → `/p/:projectId/history`. 같은 표 + Case 열, 필터: 작업 종류·상태·기간, 검색(q), '내 작업만' 토글. 필터는 URL query로 유지.
- **작업 상세** `/p/:projectId/jobs/:jobId`(목록 두 곳 공통): 개요(상태·시각·대기·소요·실행자·재시도 원본/후속 링크) · 입력값(키-값 표, settings_summary 접힘) · 오류(코드·메시지·실패 step, 실패일 때만 맨 위) · step 표(step별 소요, 관리자는 command 접힘) · 로그(step 선택 + 기존 로그 뷰어 재사용) · 결과 카드.
  - 주 버튼 1개: 결과가 있으면 "그때 결과 열기", 없으면 없음(로그는 탭). 실패 작업은 기존 재시도 버튼을 보조 버튼으로만(새 동작 없음).
- **과거 결과 열기**: 단계 화면을 읽기 전용 모드로 연다 — ④ `?run=<esl_run_id>`, ⑤ `?val=<validation_id>`, ①·②·⑥·보고서는 상세 화면 결과 카드 안에서(요약 표 / 파일 목록·다운로드 / 보고서 새 탭). 읽기 전용 모드: 상단 배지 **"과거 실행 · <시각>"**, '입력 바뀜' 칩(사유 툴팁), "현재와 다른 점" 표(diff, 접힘 기본 펼침), 실행·확정·내보내기·등록 버튼 숨김, "현재 결과로" 링크 1개. `availability = summary`면 파일 기반 패널 대신 "파일 보존 안 됨 — 기록된 값만 표시".

## 6. 시험
- V-H-1 `/history` 프로젝트 범위·case_id 범위·다른 프로젝트 case_id 404·정렬(created_at, id desc)·같은 created_at 다수에서 커서 누락·중복 0.
- V-H-2 필터 job_type·state·mine·q(제목·폴더·id 접두)·from/to, 잘못된 값 422, 커서 위조 422 `INVALID_CURSOR`, limit 상한 200.
- V-H-3 duration_s·wait_s(대기·실행 중·종료·미시작 null), retried_by_job_id 연결.
- V-H-4 result_state·stale·stale_reasons: 재추출·part_title 변경·t* 변경·지지점 변경·입력 파일 변경 각각, 현재 결과는 `current`.
- V-H-5 diff 키·같은 값 생략·현재 결과 없음(`current: null`)·12개 상한.
- V-H-6 review: 추출·ESL·검증·내보내기·보고서·실패·취소·라이브러리 작업 각각의 `past`·availability.
- V-H-7 권한: ACTIVE 아니면 403, command는 전역 관리자만 키 존재(일반·power·프로젝트 admin 응답에 없음), 로그 마스킹 유지.
- V-H-8 H-4 표식 탐색: 이전 검증 field·section 200, 표식 불일치·폴더 밖 심링크·탐색 상한 초과 409, `_backup` 목록 노출 0.
- V-H-9 H-5 보존: EXPORT·CASE_REPORT 후 `history/<job_id>/` 생성, 이후 내보내기 뒤에도 이전 파일 다운로드 가능, 복사 실패 시 작업 성공 + warning, bundle·artifacts에 history 미포함, 파일 이름 공격(`..`, 구분자, 목록 밖) 거부.
- V-H-10 migration 0007 upgrade·downgrade·재실행 멱등, tables.py와 일치(기존 스키마 비교 시험).
- V-H-11 성능: jobs 10만 행(프로젝트 3개) 시드에서 `/history` 첫 페이지·5번째 페이지 각 p95 < 300 ms, `EXPLAIN`이 `ix_jobs_project_created` 사용, 목록 쿼리 수 상수(N+1 없음).
- V-H-12 UI(mock + Playwright 실서버): Case 탭·프로젝트 페이지 표·필터 URL 유지·더 보기, 상세 섹션, "그때 결과 열기" → ④/⑤ 읽기 전용(배지·diff·실행 버튼 없음), summary 안내 문구, 화면당 주 버튼 1개 규칙.

## 7. 파일 소유 (병렬 구현)
- **Impl-Backend**: `migrations/versions/0007_history_indexes.py`, `backend/esl_platform/core/db/tables.py`(Index만), `backend/esl_platform/core/repositories/history.py`(신규), `backend/esl_platform/api/services/history.py`(신규), `backend/esl_platform/api/routers/history.py`(신규), `backend/esl_platform/api/main.py`(라우터 등록 1줄), `backend/esl_platform/api/schemas.py`(History* 모델 끝에 추가), `backend/esl_platform/api/services/results.py`(H-4), `backend/esl_platform/core/core_outputs.py`(history 경로·표식 탐색 함수), `backend/esl_platform/core/config.py`(history 설정), `worker/esl_worker/executor.py`·`register.py`(H-5), 시험 `backend/tests/test_p3_history.py`·`worker/tests/test_history_archive.py`, `docs/contracts/openapi_*`(있으면 갱신), `docs/manual/admin.md`(설정 2개).
- **Impl-Frontend**: `frontend/src/api/history.ts`(타입·호출 — `types.ts`·`endpoints.ts`는 건드리지 않음), `frontend/src/components/HistoryTable.tsx`·`PastBadge.tsx`·`DiffTable.tsx`, `frontend/src/pages/history/{CaseHistory,ProjectHistory,JobReview}.tsx`, `frontend/src/app/App.tsx`(라우트 3줄), `frontend/src/pages/CasePage.tsx`(메뉴 링크), `frontend/src/pages/CaseList.tsx`(링크), `frontend/src/stages/Stage4.tsx`·`Stage5.tsx`(`?run`·`?val` 읽기 전용), `frontend/src/mock/historymock.ts`(+ `server.ts` 등록), `frontend/src/__tests__/history.test.tsx`, `docs/manual/user.md`(이력 절), `CHANGELOG.md`·`VERSION`(사용자용 항목 1개).
- 접점은 §3 응답 키뿐 — 프런트는 mock으로 먼저 구현, 백엔드 완료 후 실서버 Playwright(V-H-12)를 Verifier가 수행.

## 8. 리스크
- 과거 내보내기·보고서는 이 기능 배포 **이후** 실행분만 파일 다시 열기 가능(이전 것은 summary) — 사용자 기대와 다를 수 있음.
- t*·추출 과거 보기는 요약 값만(후보 그래프·최대값 이력 그래프는 현재 파일 기준이라 재현 불가). 사용자 t* 수동 확정은 작업이 아니어서 이력에 없음(그 t*로 계산한 ESL run에는 남음).
- `history/` 보존으로 Case 폴더 용량 증가(내보내기 반복이 많으면). 정리 정책 없음.
- `_backup` 표식 탐색은 `_backup` 폴더가 많으면 느려질 수 있음 → 상한 100, 넘으면 summary.
- 조회 권한이 프로젝트 역할과 무관(기존 정책 계승) — 다른 프로젝트 사용자도 params·로그를 볼 수 있음.

## 9. 미결 (사용자 확인 필요)
- Q1 과거 내보내기·보고서 파일을 작업별로 보존(H-5, Case 폴더 용량 증가)해도 되는가? 아니면 요약 값만으로 충분한가?
- Q2 이력 조회를 지금처럼 모든 ACTIVE 사용자에게 열어 둘지, 그 프로젝트에 역할이 있는 사용자(전역 관리자 포함)로 좁힐지?
- Q3 사용자의 t* 수동 확정(②에서 후보 선택)도 이력 항목으로 남길지(현재는 작업이 아니라 기록 없음 — 남기면 테이블·migration 추가)?
