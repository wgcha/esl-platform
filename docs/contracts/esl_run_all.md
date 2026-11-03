# 계약: ESL 생성 Case 일괄 실행 (RUN_ALL, v0.13.0)

- 상태: **초안** (2026-11-02, 사용자 확정 (a)~(c) 반영, 결정 필요 2건 — §16 권장안으로 진행 가능). 구현 코드 없음. 이 문서가 구현·검증의 원본이다.
- 기준: main `b11a0bc` (v0.12.3).
- 범위: ESL 생성 Case 의 ①입력(추출) → ②t*·지지점 → ③ESL → ④검증을 한 번의 요청으로 이어서 실행한다. 새 작업 종류·새 코어 단계 없음 — 기존 CASE_EXTRACT·ESL_SOLVE·VALIDATE 작업과 기존 ② 확정 로직(`PUT /tstar` 와 같은 코드)을 순서대로 부른다.
- ID 규칙: 결정 `RA-D-n`, 요구 `RA-n`, 시험 `V-RA-n`, 리스크 `R-RA-n`.
- 사용자 확정 사항(2026-11-02, 변경 금지):
  - (a) ④검증이 PASS 로 끝나도 **라이브러리 등록 전에 멈춘다**(사람이 [라이브러리에 등록]).
  - (b) 사람 판단이 필요한 상태(② t* 확인 필요, 지지점 자동 선택 BLOCKED 등)면 **그 단계에서 멈추고 사유 표시** → 사람이 고친 뒤 [이어서 실행]. 작업 실패도 그 단계에서 멈춘다.
  - (c) 버튼 위치: 새 Case 화면 체크박스 **'생성 후 일괄 실행'** 1개 + Case 화면 주 버튼 **[일괄 실행]**(멈춘 뒤에는 **[이어서 실행]**).

## 0. 현황 조사 (main b11a0bc)

| 항목 | 위치 | 현재 동작 |
|---|---|---|
| 단계 실행 API | `POST /cases/{id}/jobs {job_type, params}` → `services/jobs.create_job` → `_prepare` | Case 잠금(FOR UPDATE) → `require_execute`·`require_config_ok`·`require_active_case` → 사전조건(미충족 409 `PREREQUISITE_MISSING` + `missing`) → `insert_job`. 같은 Case·종류 비종료 작업 있으면 409 `CASE_JOB_BUSY`(부분 unique `ux_jobs_case_type_active`) |
| 작업 종류 | `core/job_types.py` | CASE_EXTRACT(SLOT: [H3D_EXTRACT]·EXTRACT·TSTAR_SCAN·EXTRACT_REGISTER), ESL_SOLVE(SLOT: ESL·ESL_REGISTER), VALIDATE(SLOT: VALIDATE·VAL_REGISTER). ②는 작업이 아님(동기 API) |
| 화면 4단계 상태 | `services/cases.step_status(case, stage_status)` | `{input, tstar, esl, validate}` 각 `{state: none|running|done|stale|failed, job_id, reason?}`. tstar: 추출 stale → stale, 지지 세트 있음 → done, `support_auto.status == BLOCKED` → failed + `SUPPORT_AUTO_BLOCKED`, t* 만 있고 지지 없음 → none + `TSTAR_NOT_CONFIRMED` |
| t* 자동 | `worker/register.register_extract` | 추출 등록 때 `case.tstar = {metric: default_metric, frame_index, …, source:"auto"}`(코어 1순위, D 밖이면 코어가 D 안 후보로 바꿈 = `adjusted`), `current_esl_run_id = NULL`, 이전 지지 세트는 노드가 모두 남을 때만 유지 |
| t* 확정 | `PUT /cases/{id}/tstar` → `services/cases.put_tstar` | 지표·후보·in_D 검사 → `source:"user"`. 지지 세트 없으면 코어 `auto_321`(+품질 검사) 결과 OK → 세트 생성(`support_auto.OK`), 실패 → `support_auto.BLOCKED`(200, t* 는 저장). 세트 있으면 `KEPT`(MR-D-3·MR-D-4) |
| 사람 확인 규칙 | `docs/decisions.md` "사용자가 후보 중에서 확정", `esl_menu_restructure.md` §5 | 새 Case(지지 세트 없음)는 [t* 확정] 을 눌러야 ③이 가능(ESL_SOLVE 409 `missing:["support_set"]`). 지지 세트가 이미 있으면 auto t* 그대로 ③ 가능(확정 강제 없음) |
| stale | `core/inputs.extract_stale`·`esl_run_stale` | 추출 stale = `extract_summary.requested_part_title ≠ case.part_title`. ESL 실행 stale = `inputs_hash`(추출 작업 id·part_title·t*(frame, metric)·지지 세트 id) 불일치 또는 추출 stale |
| 검증 판정 | `register_validation` | `verdict ∈ PASS|FAIL|UNDETERMINED`(+scheme), 작업 `result.registered.verdict`. VALIDATE 성공 시 `report.auto` 면 CASE_REPORT(LIGHT) 자동 큐 |
| 누적 입력 | `esl_cumulative_input.md` | 누적 씬 t* = 누적 순위 + 증분 first-reach. D 밖 후보면 경고 `CUMULATIVE_FRAME_NOT_EXTRACTED` + `adjusted`. 일괄 실행 규칙은 비누적과 같음(§4.2 G2 가 이 경우를 멈춤으로 잡음) |
| 작업 연쇄 선례 | `executor._queue_report`(VALIDATE→CASE_REPORT), `scx_verify.on_finish`(VERIFY_DROP→VERIFY_POST) | **워커가 종료 전이와 같은 트랜잭션**에서 다음 작업 `insert_job`(savepoint, IntegrityError 는 경고) |
| 종료 전이 지점 | `jobs_repo.release`(워커 E5~E7), `jobs_repo.interrupt`(리퍼 E8, `runtime.py`), `jobs_repo.request_cancel`(QUEUED → 즉시 CANCELED, API) | 3곳 |
| 직렬 규칙 | `jobs_repo` claim 조건 + `ux_jobs_case_running` | 같은 Case RUNNING 작업 최대 1개(lane 무관). SLOT 레인 `worker.slots` 개 |
| 권한 | `require_execute`(power 이상), 취소·재시도 `_can_touch`(작성자 또는 전역 관리자) | |

## 1. 결정

- **RA-D-1 체인 = 새 테이블 `run_alls` 1행(시도 1회 = 1행).** 시작·[이어서 실행]마다 새 행. RUNNING 외 상태(STOPPED·DONE·CANCELED)는 종료 상태 — [이어서 실행]은 이전 행을 되살리지 않고 `resumed_from_id` 로 잇는 새 행을 만든다(이력이 시도별로 남음).
- **RA-D-2 연쇄 = 작업 종료 훅, 종료 전이와 같은 트랜잭션.** 훅 `core/run_all.on_job_end(conn, job, prep=None)` 를 `jobs_repo.release`·`interrupt`·`request_cancel`(즉시 CANCELED 경로) 안에서 부른다(지연 import). 워커가 다음 작업을 만드는 기존 선례(RA-0 표)를 따른다 — 백엔드에 배경 루프가 없고, 같은 트랜잭션이라 "작업은 끝났는데 다음 작업이 안 생김"이 없다.
- **RA-D-3 시작·이어서 = API 가 첫 동작까지 동기 수행.** `POST /run-all` 은 §4 평가로 첫 동작(작업 생성·② 자동 확정·건너뛰기·멈춤)을 그 요청 안에서 끝낸다. ② 가 첫 동작이면 `put_tstar` 와 같은 순서(트랜잭션 밖 `auto_321` → 트랜잭션 안 저장)로 처리하고 바로 ESL_SOLVE 까지 만든다.
- **RA-D-4 ② 자동 확정은 가드 통과 때만**(§4.2, 결정 필요 Q1 권장안). 가드 실패·BLOCKED 는 멈춤.
- **RA-D-5 done 은 건너뛰고 stale·none·failed 는 다시 실행.** 이미 실행 중(사람이 직접 누른 작업 포함)이면 그 작업을 **입양**해 끝나기를 기다린다(새로 만들지 않음).
- **RA-D-6 코어 설정 스냅샷은 체인 행에 1번.** 시작 시 API 가 `ctx.config.core` 사본을 `run_alls.core_settings` 에 저장, 워커는 이 값으로 ESL_SOLVE·VALIDATE params 를 만든다(워커는 코어 설정 파일을 읽지 않음). params 생성 코드는 API·워커 공용 `core/job_params.py` 로 옮긴다(동작 불변).
- **RA-D-7 체인 RUNNING 동안 그 Case 의 상태 변경 API 는 409 `RUN_ALL_ACTIVE`.** 대상: `POST /cases/{id}/jobs`(CASE_EXTRACT·ESL_SOLVE·VALIDATE — CASE_REPORT·EXPORT 는 허용), `PUT /tstar`, `POST /support-sets`, `PATCH /cases/{id}`(part_title 변경 시), `POST /archive`, `POST /jobs/{id}/retry`(그 Case 의 위 3종). 조회·보고서·결과 받기는 허용. 바꾸려면 먼저 [일괄 취소].
- **RA-D-8 라이브러리 등록은 하지 않는다**(사용자 확정 a). ④ PASS → 체인 DONE, 화면은 ④ 의 기존 [라이브러리에 등록] 으로 안내만.

## 2. 데이터 (migration `0013_run_all`, down_revision `0012`)

`run_alls`:

| 열 | 형 | 설명 |
|---|---|---|
| `id` | uuid PK | |
| `case_id` | FK cases | |
| `project_id` | text | 권한·이력 필터용 |
| `from_step` | text | `input|tstar|esl|validate` — 요청 시작점 |
| `status` | text | `RUNNING|STOPPED|DONE|CANCELED` |
| `cur_step` | text NULL | 진행 중 단계(RUNNING 일 때) |
| `cur_job_id` | FK jobs NULL | 기다리는 작업(생성 또는 입양). 훅은 이 값이 끝난 작업 id 일 때만 진행 |
| `stop_step` | text NULL | STOPPED 일 때 멈춘 단계(CANCELED 는 취소 시점 단계) |
| `stop_code` | text NULL | §7 |
| `stop_reason` | jsonb NULL | `{message, detail}` — detail 은 코드별(`missing`, `problems`, `job_id`, `failure_code`, `reasons`, `verdict`) |
| `verdict` | text NULL | ④ 를 지난 경우 판정(PASS·FAIL·UNDETERMINED) |
| `job_ids` | jsonb | 이 체인이 만든·입양한 작업 `[{step, job_id, adopted}]`(순서대로) |
| `skipped` | jsonb | 건너뛴 단계 `[{step, state}]`(done) |
| `prev_user_tstar` | jsonb NULL | 시작 시 `case.tstar` 가 `source:"user"` 였으면 `{metric, frame_index}`(§4.2 G4) |
| `core_settings` | jsonb | RA-D-6 |
| `resumed_from_id` | FK run_alls NULL | [이어서 실행] 원본 |
| `created_by`, `created_by_name` | text | 시작한 사람. 체인이 만드는 작업의 `created_by` 도 이 값 |
| `canceled_by` | text NULL | |
| `created_at`, `updated_at`, `finished_at` | timestamptz | |

- 인덱스: `ux_run_alls_case_running (case_id) WHERE status='RUNNING'`(Case 당 RUNNING 1개 — 중복 시작 방지 최종 보장), `ix_run_alls_case_created (case_id, created_at desc)`.
- `jobs.run_all_id` (FK run_alls NULL) 열 추가 — 체인이 **만든** 작업만 채움(입양 작업은 NULL, 체인 행 `job_ids.adopted=true` 로만 기록). `insert_job(..., run_all_id=None)` 키워드 추가.

## 3. 상태 기계

```
            POST /run-all (평가 → 첫 동작)
                     │
                     ▼
   ┌──────────── RUNNING ───────────────┐
   │  cur_step·cur_job_id 갱신(훅)       │
   │                                     │
   │ 멈춤 조건(§4)          ④ PASS      │ 취소(체인 취소·작업 취소)
   ▼                         ▼          ▼
 STOPPED                   DONE      CANCELED
   │ [이어서 실행] = 새 행(resumed_from_id, from_step = stop_step)
   └──────────────► RUNNING(새 행)
```

- 전이는 모두 `run_alls` 행 FOR UPDATE 아래에서. 종료 상태에서 다른 상태로 가는 전이 없음.
- 평가 함수 `evaluate(conn, case, run) → Action` 은 순수 규칙(§4): `Skip(step)`·`Create(job_type, params)`·`Adopt(job)`·`ConfirmTstar`·`Stop(step, code, detail)`·`Done`. 한 번의 훅/요청에서 `Skip`·`ConfirmTstar` 는 이어서 평가를 계속하고, `Create`·`Adopt`·`Stop`·`Done` 에서 끝난다.

## 4. 단계별 진입 조건·자동 결정 규칙

평가는 `max(from_step, 첫 단계)` 부터 `step_status` 로 한다. `from_step` 보다 앞 단계가 done 이 아니면 시작 시 409 `PREREQUISITE_MISSING`(missing = 그 단계들). 모든 단계의 공통 앞 조건: Case ACTIVE·설정 OK(시작 시 API 검사, 워커 훅에서는 Case ACTIVE 만 재확인 — 아니면 STOPPED `CASE_ARCHIVED`).

### 4.1 ① 입력(CASE_EXTRACT)

| `step_status.input` | 동작 |
|---|---|
| done | 건너뜀 |
| running | 그 작업 입양 |
| none·failed·stale | CASE_EXTRACT 생성. params: 결과 폴더 Case `{}`, h3d Case 는 같은 Case 마지막 CASE_EXTRACT 의 `h3d.hot_k·top_n`(없으면 `{}` = 설정 기본). `_prepare` 그대로(입력 경로·include 검사·지문 갱신) |

- 생성 시 `_prepare` 오류(경로 밖·입력 없음 등)는 STOPPED `PREREQUISITE_MISSING`(detail = 오류 code·message). 시작 요청이면 409 대신 201 + STOPPED 행으로 돌려준다(화면이 사유를 같은 자리에 표시).
- 작업 FAILED(`INPUT_CHANGED` 포함) → STOPPED `STEP_FAILED`, INTERRUPTED → `STEP_INTERRUPTED`.

### 4.2 ② t*·지지점(동기, 작업 아님)

| `step_status.tstar` | 동작 |
|---|---|
| done | G4 만 검사 → 통과 시 건너뜀, 실패 시 멈춤 `TSTAR_REVIEW_REQUIRED` |
| failed + `SUPPORT_AUTO_BLOCKED` | 멈춤 `SUPPORT_AUTO_BLOCKED`(detail `problems` = `tstar.support_auto.problems`). 같은 t* 재확정은 결정적이라 같은 결과 → 재시도하지 않음 |
| none + `TSTAR_NOT_CONFIRMED` | 가드 G1~G4 모두 통과 → **자동 확정**, 하나라도 실패 → 멈춤 `TSTAR_REVIEW_REQUIRED`(detail `reasons`) |
| none(t* 없음)·stale·running | ① 이 done 이 아니라는 뜻 — ① 규칙에서 이미 처리(여기 도달하지 않음). 도달하면 멈춤 `PREREQUISITE_MISSING` |

자동 확정 가드(모두 기존 규칙·기존 산출물에서 판정, 새 코어 출력 없음):

| 가드 | 조건(통과) | 실패 reason | 근거 |
|---|---|---|---|
| G1 | `tstar_info` 를 읽을 수 있고 `case.tstar.metric` 블록에 `error` 없음 | `TSTAR_METRIC_ERROR` | `_tstar_info` PREREQUISITE_MISSING / 코어 metric error |
| G2 | 그 지표 후보 1순위 `candidates[0]` 이 `in_D != false` 이고 `frame_index == case.tstar.frame_index`(코어가 D 밖이라 다른 후보로 바꾸지 않았음 — `CUMULATIVE_FRAME_NOT_EXTRACTED` 포함) | `TSTAR_ADJUSTED` | 코어 `adjusted` 경고 = 1순위를 못 씀 → 사람이 후보를 봐야 함 |
| G3 | `put_tstar` 와 같은 검사 통과(지표 있음·후보에 있음·in_D 아님 아님) | `FRAME_NOT_CANDIDATE` | `put_tstar` |
| G4 | `run.prev_user_tstar` 가 없거나, 현재 `case.tstar` 의 `(metric, frame_index)` 와 같음 | `USER_TSTAR_CHANGED` | 사람이 고른 t* 를 체인 중 재추출이 auto 로 덮어쓴 경우(기존 `register_extract` 동작) — 사람이 다시 골라야 함 |

자동 확정 = `put_tstar` 와 같은 코드(공용 `core/tstar_confirm.apply`):
- `tstar = {…현재 auto 값, source:"auto", confirmed:{by:"run_all", run_all_id, user_id: run.created_by}}`(사람 확정은 기존대로 `source:"user"`).
- 지지 세트 없음 → `auto_321` → OK: 세트 생성(`source:"auto"`) + `support_auto.OK` → ③ 으로 계속. BLOCKED: t* 저장 + `support_auto.BLOCKED` → 멈춤 `SUPPORT_AUTO_BLOCKED`(② failed 표시는 기존 `step_status` 그대로).
- `auto_321` 이 코어 오류(`CoreError`) → 멈춤 `SUPPORT_AUTO_ERROR`(detail = 코어 code·message), 아무것도 저장하지 않음.
- 실행 위치: 시작·이어서 요청이면 API(RA-D-3). ① 성공 직후면 **워커**: `executor` 가 CASE_EXTRACT 등록 성공 후 `_finish(SUCCEEDED)` 전에 "이 작업을 기다리는 RUNNING 체인이 있고 등록 후 Case 에 지지 세트가 없음"이면 트랜잭션 밖에서 `model.npz` 로드 + `auto_321`(설정 = `run.core_settings` 의 support_check)을 계산해 `release(..., run_all_prep=…)` 로 넘긴다. 훅은 Case FOR UPDATE 후 `extract_summary.job_id == 끝난 작업 id` 를 재확인(다르면 멈춤 `CASE_CHANGED`)하고 가드·저장한다.

### 4.3 ③ ESL(ESL_SOLVE)

| `step_status.esl` | 동작 |
|---|---|
| done | 건너뜀 |
| running | 입양 |
| none·failed·stale | ESL_SOLVE 생성: params = 기존 `_prepare` ESL_SOLVE 와 같음(`frame_index`·`support_set_id` = Case 현재값, `material_override` 없음, settings = `run.core_settings` + 지표) |

- 사전조건 미충족(`missing`: extract·tstar·support_set·disp_frame) → 멈춤 `PREREQUISITE_MISSING`(detail `missing`, `support_blocked` 면 코드 `SUPPORT_AUTO_BLOCKED`).
- FAILED → `STEP_FAILED`, INTERRUPTED → `STEP_INTERRUPTED`.

### 4.4 ④ 검증(VALIDATE)

| `step_status.validate` | 동작 |
|---|---|
| done | 현재 ESL 실행의 최신 검증 `verdict` 로 끝 판정(아래) |
| running | 입양 |
| none·failed·stale | VALIDATE 생성: `esl_run_id = case.current_esl_run_id`(기존 `_prepare` — READY·현재·비stale 검사) |

- 끝 판정: PASS → **DONE**(`verdict:"PASS"`, 라이브러리 등록 안 함 — RA-D-8). FAIL → STOPPED `VALIDATION_FAIL`, UNDETERMINED → STOPPED `VALIDATION_UNDETERMINED`(결정 필요 Q2 권장안). detail = `{verdict, validation_id, fail_reasons|undetermined_reason}`.
- VALIDATE 성공 후 기존 `report.auto` CASE_REPORT 자동 큐는 그대로(체인은 기다리지 않음, `run_all_id` 도 채우지 않음).

### 4.5 [이어서 실행]

- 새 행, `from_step = 이전 행.stop_step`(화면 기본값; API 는 `from` 생략 시 `input` 부터 평가해도 결과가 같다 — done 건너뜀). 사람이 고친 결과가 반영되는 방식: ② 를 사람이 [t* 확정] → `source:"user"`·지지 세트 생김 → ② done → ③ 부터. ④ FAIL 뒤 t*·지지점을 바꾸면 ESL 실행이 stale → ③④ 다시. 아무것도 안 고치고 누르면 같은 사유로 다시 STOPPED(정상).
- 사람이 실패 작업을 기존 [재시도] 로 다시 돌린 뒤 [이어서 실행] 해도 된다(그 단계가 done 이면 건너뜀, 아직 running 이면 입양).

## 5. 작업 연쇄·멱등

- 훅 `on_job_end(conn, job, prep)`:
  1. `run_alls` 에서 `status='RUNNING' AND cur_job_id = job.id` 행 FOR UPDATE. 없으면 아무것도 안 함(체인 무관 작업·이미 처리됨·취소된 체인).
  2. `job.state`: SUCCEEDED → Case FOR UPDATE 후 §4 평가를 다음 단계부터 계속. FAILED → STOPPED `STEP_FAILED`(detail `{job_id, job_type, failure_code, failure_message}`). INTERRUPTED → `STEP_INTERRUPTED`. CANCELED → 체인 CANCELED(`stop_code: JOB_CANCELED`, 작업만 따로 취소한 경우 포함).
  3. 새 작업은 savepoint 안 `insert_job(..., run_all_id=run.id)`. IntegrityError(같은 Case·종류 비종료 작업이 이미 있음) → 그 작업을 찾아 **입양**. 그 다음 `cur_job_id`·`cur_step`·`job_ids` 갱신.
- 멱등: 같은 작업에 훅이 두 번 불려도 2번째는 1단계에서 행이 없다(`cur_job_id` 가 이미 바뀜·종료). 상태 전이는 `check_transition` 이 1회만 허용. 체인 시작 중복은 `ux_run_alls_case_running`(IntegrityError → 409 `RUN_ALL_ACTIVE`).
- 끊김 복구: RUNNING 체인인데 `cur_job_id` 작업이 이미 종료(훅 누락 — 이론상 없음) → 리퍼 루프(`runtime.py`)가 주기마다 이런 행을 찾아 `on_job_end` 를 1회 호출(행 잠금으로 중복 없음). `cur_job_id` NULL 인 RUNNING 은 API 동기 처리 중에만 존재(같은 트랜잭션 안) — 커밋된 상태로는 생기지 않음.
- 체인이 만드는 작업의 `created_by(_name)` = `run.created_by(_name)` → 기존 취소·재시도 권한(`_can_touch`) 그대로 적용.

## 6. 취소·권한·동시성

- **취소** `POST /cases/{id}/run-all/cancel`: RUNNING 행 FOR UPDATE → `status=CANCELED, canceled_by, stop_step=cur_step, stop_code=RUN_ALL_CANCELED, finished_at` → `cur_job_id` 가 **이 체인이 만든 작업**(`jobs.run_all_id = run.id`)이고 비종료면 `request_cancel`(QUEUED 즉시 CANCELED, RUNNING 은 플래그 → 워커 E7). 입양한 작업은 취소하지 않고 놓아 둠(남의 작업). 훅은 행이 이미 CANCELED 라 아무것도 안 함. RUNNING 이 아니면 409 `RUN_ALL_NOT_RUNNING`.
- **권한**: 시작·이어서 = 그 프로젝트 `require_execute`(power 이상) + `require_config_ok` + `require_active_case`(기존 단계 실행 권한과 같음). 취소 = `require_execute` + (시작한 사람 또는 전역 관리자) — 기존 작업 취소 규칙과 같음. 조회 = 프로젝트 조회 권한(Case 조회와 같음).
- **동시성**: Case 당 RUNNING 체인 1개(`ux_run_alls_case_running`). 체인은 한 번에 작업 1개만 큐에 둔다 → 기존 "같은 Case RUNNING 1개"와 충돌 없음. 슬롯 예약 없음 — 다음 작업은 SLOT 레인 FIFO 뒤에 붙는다(다른 Case 작업이 사이에 실행될 수 있음, 우선순위 없음). 여러 Case 의 체인은 서로 독립(슬롯 수만큼 병렬).

## 7. 멈춤·오류 코드

멈춤 코드(`run_alls.stop_code`, 메시지는 `resources` 없이 서비스 상수 — `REASON_MESSAGES` 옆):

| 코드 | 단계 | 메시지(화면) | 사람이 할 일 |
|---|---|---|---|
| `TSTAR_REVIEW_REQUIRED` | ② | "t* 확인이 필요합니다 — ②에서 후보를 보고 [t* 확정]" + reasons 한 줄씩(`TSTAR_ADJUSTED`: "1순위 시점이 변위 추출 프레임에 없어 다른 후보로 바뀌었습니다", `TSTAR_METRIC_ERROR`, `FRAME_NOT_CANDIDATE`, `USER_TSTAR_CHANGED`: "직접 고른 t*(frame N)와 새 자동 t*(frame M)가 다릅니다") | ②에서 확정 |
| `SUPPORT_AUTO_BLOCKED` | ② | 기존 문구 "지지점을 자동으로 정하지 못했습니다 — ②에서 사유 확인" + problems | ② 고급 지정 또는 입력 수정 |
| `SUPPORT_AUTO_ERROR` | ② | "지지점 자동 선택 중 오류: …" | 관리자 확인 |
| `PREREQUISITE_MISSING` | ①③④ | "앞 단계가 필요합니다: …"(missing) | 해당 단계 |
| `STEP_FAILED` | ①③④ | "<단계> 작업 실패: <failure_code> <message>" + 작업 링크 | 로그 확인·[재시도] 또는 입력 수정 |
| `STEP_INTERRUPTED` | ①③④ | "워커가 끊겨 작업이 중단되었습니다" | [이어서 실행] |
| `VALIDATION_FAIL` | ④ | "검증 FAIL — 원인 확인 후 ②·③ 조건을 바꿔 [이어서 실행]" | ④ 결과 확인 |
| `VALIDATION_UNDETERMINED` | ④ | "검증 판정 불가 — <undetermined_reason>" | ④ 결과 확인 |
| `CASE_CHANGED` | ② | "실행 중 Case 가 바뀌었습니다" | [이어서 실행] |
| `CASE_ARCHIVED` | 아무 단계 | "보관된 Case 입니다" | — |
| `JOB_CANCELED` / `RUN_ALL_CANCELED` | 아무 단계 | "작업이 취소되었습니다" / "일괄 실행을 취소했습니다" | — (CANCELED) |

API 오류:

| HTTP | 코드 | 언제 |
|---|---|---|
| 409 | `RUN_ALL_ACTIVE` | 이미 RUNNING 체인(시작), 체인 중 상태 변경 API(RA-D-7) |
| 409 | `RUN_ALL_NOT_RUNNING` | 취소할 RUNNING 체인 없음 |
| 409 | `PREREQUISITE_MISSING` | `from` 앞 단계가 done 아님(missing) |
| 409 | `CASE_ARCHIVED` | 기존 |
| 403 | (기존 forbidden) | 권한 |
| 404 | `CASE_NOT_FOUND` | 기존 |
| 422 | `INVALID_PARAMS` | `from` 값 오류 |
| 503 | 기존 설정 오류 | `require_config_ok` |

## 8. API

- `POST /cases/{id}/run-all` body `{from?: "input"|"tstar"|"esl"|"validate"}`(기본 `input`) → 201 `RunAllOut`. 응답 시점에 이미 STOPPED·DONE 일 수 있음(첫 동작이 멈춤·전부 done PASS).
- `GET /cases/{id}/run-all` → 200 `RunAllOut | null`(최신 1행). `GET /cases/{id}/run-all?all=1` → 200 `RunAllOut[]`(최신순, 최대 50 — 이력 화면).
- `POST /cases/{id}/run-all/cancel` → 200 `RunAllOut`(CANCELED).
- `POST /cases` body 에 `run_all: bool = false` 추가. true 면 Case 생성 커밋 뒤 같은 요청에서 시작(별도 트랜잭션). 시작이 실패해도 Case 는 만들어진다 — 응답 `CaseOut.run_all` = 생성된 행(STOPPED 포함) 또는 null + `run_all_error: {code, message}`.
- `CaseOut.run_all`(최신 1행 요약, `case_full` 에서 채움 — 기존 Case 폴링으로 화면 갱신) — `RunAllOut` 과 같은 형식.
- `RunAllOut = {id, case_id, from_step, status, cur_step, cur_job_id, cur_job_state, stop_step, stop_code, stop_reason:{message, detail}, verdict, job_ids, skipped, resumed_from_id, created_by, created_by_name, canceled_by, created_at, finished_at, can_resume: bool, superseded: bool}`. `can_resume` = STOPPED ∧ 이후 RUNNING 행 없음. `superseded` = 종료 뒤 이 체인과 무관한 그 Case 의 ①③④ 작업이 새로 생김(화면이 지난 결과 줄을 숨기는 용도).
- 이력: `GET /history` 항목·`GET /jobs/{id}/review` 에 `run_all_id`(NULL 가능) 추가.

## 9. 화면 (필수만)

- **새 Case**(`NewCase.tsx`): [Case 만들기] 옆 체크박스 1개 **'생성 후 일괄 실행'**(기본 꺼짐, 기억 안 함). 켜면 `createCase({…, run_all: true})` → 기존처럼 `/step/1` 로 이동. `run_all_error` 가 있으면 Case 화면 진행 줄에 그 문구.
- **Case 화면**(`CasePage.tsx` case-bar `case-menu`): 주 버튼 1개.
  - 라벨: 최신 체인이 STOPPED ∧ `can_resume` → **[이어서 실행]**, 그 밖 → **[일괄 실행]**.
  - 비활성 사유(`PrimaryButton disabledReason`): 권한 없음 / 보관된 Case / "일괄 실행 중" / 네 단계 모두 done ∧ 최신 검증 PASS → "모든 단계가 완료되었습니다(PASS) — ④에서 라이브러리에 등록".
  - [일괄 실행] = `from` 생략, [이어서 실행] = `from = stop_step`.
- **진행 줄**(`shell/RunAllBar.tsx`, stepper 바로 아래 1줄, 체인이 없거나 `superseded` 면 숨김). 단계 점은 **기존 `StageStepper` 4점 그대로**(추가 점 없음) — 진행 줄은 현재 단계에 테두리 강조(`data-run-all-step`)만 더한다.
  - RUNNING: "일괄 실행 중 — ③ ESL · 대기 중|실행 중" + 텍스트 버튼 [일괄 취소](확인 창 1회).
  - STOPPED: "② t*·지지점에서 멈춤 — <stop_reason.message>" + [그 단계로 가기] 링크(주 버튼이 [이어서 실행]).
  - DONE: "④ 검증 PASS — 라이브러리 등록은 ④에서" + ④ 링크.
  - CANCELED: "일괄 실행 취소됨"(회색).
- 폴링: 기존 `anyRunning` 조건에 `c.run_all?.status === "RUNNING"` 추가(작업 사이 순간에도 2 s 갱신 유지).
- 이력(`CaseHistory`·`ProjectHistory`·`HistoryTable`): `run_all_id` 있는 작업 행에 작은 배지 **'일괄'**(title: 시작자·시작 시각). `JobReview` 머리에 "일괄 실행으로 생성" 1줄. `CaseHistory` 위에 접힌 `<details>` "일괄 실행 기록"(시작 시각·시작자·시작 단계·결과(DONE/STOPPED 단계·사유/CANCELED)·작업 수) — `GET …/run-all?all=1`.
- 가이드(`pages/guide/content.ts`)·`docs/manual/user.md`: 일괄 실행 절 1개(멈추는 경우 표 = §7 상위 6개).

## 10. 이력 표시 규칙

- 체인이 만든 작업은 기존 이력과 똑같이 1행씩 남는다(새 작업 종류 없음) + 배지. 입양한 작업은 배지 없음(사람이 만든 작업).
- ② 자동 확정은 작업이 아니므로 작업 이력에 행이 없다 — 체인 행 `skipped`/`job_ids` 와 `case.tstar.confirmed.by = "run_all"` 로 남고, 일괄 실행 기록 표의 결과 칸에 "② 자동 확정(t* frame N, 지지점 자동)" 으로 보인다.

## 11. 요구

- RA-1 체인 1회로 ①→②→③→④ 를 사람 조작 없이 실행(가드 통과·BLOCKED 아님·PASS).
- RA-2 done 단계 건너뜀, stale·none·failed 다시, running 입양.
- RA-3 §7 멈춤 조건마다 그 단계에서 STOPPED + 사유, [이어서 실행] 으로 이어감.
- RA-4 ④ PASS → DONE, 라이브러리 등록 없음.
- RA-5 취소 = 체인 CANCELED + 체인이 만든 진행 중 작업 취소.
- RA-6 Case 당 RUNNING 체인 1개, 체인 RUNNING 중 상태 변경 API 409.
- RA-7 기존 수동 단계 실행·`PUT /tstar`·검증·보고서 동작 불변(체인이 없을 때 회귀 없음).

## 12. 시험

| ID | 내용 | 종류 |
|---|---|---|
| V-RA-1 | `evaluate` 표(§4) 전 조합: 단계별 none/running/done/stale/failed × ② reason × 가드 G1~G4 → 기대 Action | 단위(core, DB 없음) |
| V-RA-2 | 새 Case `run_all:true` → ① 작업 생성(201, run_all RUNNING, `jobs.run_all_id`) | API(PG) |
| V-RA-3 | 워커 체인 전체: ① 성공 → ② 자동 확정(`source auto`·`confirmed.by run_all`·지지 세트 auto) → ③ 생성 → ④ 생성 → PASS → DONE, 라이브러리 항목 0 | 워커(PG, 코어 소형 픽스처) |
| V-RA-4 | ② 가드: `adjusted`(1순위 D 밖) → STOPPED `TSTAR_REVIEW_REQUIRED/TSTAR_ADJUSTED`; 누적 씬 `CUMULATIVE_FRAME_NOT_EXTRACTED` 같음; `prev_user_tstar` 다름 → `USER_TSTAR_CHANGED`, 같으면 통과 | 워커·API |
| V-RA-5 | ② BLOCKED → STOPPED `SUPPORT_AUTO_BLOCKED` + problems, t* 저장·② failed; 사람이 `POST /support-sets` → [이어서 실행] → ③ 부터 | API·워커 |
| V-RA-6 | 건너뜀: 전 단계 done + PASS 에서 시작 → 201 DONE, 작업 0개; ESL stale(t* 변경) → ③④ 만 | API |
| V-RA-7 | 입양: 수동 ESL_SOLVE QUEUED 상태에서 시작 → 새 작업 없이 `cur_job_id` = 그 작업, 끝나면 ④ 진행 | API·워커 |
| V-RA-8 | 실패: ③ FAILED → STOPPED `STEP_FAILED`(failure_code); 리퍼 INTERRUPTED → `STEP_INTERRUPTED`; 수동 [재시도] 성공 뒤 [이어서 실행] → ④ | 워커 |
| V-RA-9 | ④ FAIL → STOPPED `VALIDATION_FAIL`; UNDETERMINED → `VALIDATION_UNDETERMINED`; 그대로 [이어서 실행] → 같은 사유 STOPPED, 작업 0개 | 워커·API |
| V-RA-10 | 취소: QUEUED 작업 → 즉시 CANCELED·체인 CANCELED; RUNNING → 플래그·워커 E7 뒤 다음 작업 안 생김; 입양 작업은 취소 안 됨; 작업만 취소 → 체인 CANCELED `JOB_CANCELED` | API·워커 |
| V-RA-11 | 멱등·중복: 동시 시작 2회 → 1개 201·1개 409 `RUN_ALL_ACTIVE`; 같은 작업 훅 2회 → 다음 작업 1개; 같은 종류 작업 선점 시 IntegrityError → 입양 | API(PG, 동시) |
| V-RA-12 | RA-D-7: 체인 RUNNING 중 `PUT /tstar`·`POST /jobs ESL_SOLVE`·archive·retry → 409 `RUN_ALL_ACTIVE`; CASE_REPORT·결과 받기 허용 | API |
| V-RA-13 | 권한: viewer 시작 403; 다른 power 사용자 취소 403, 전역 관리자 허용 | API |
| V-RA-14 | 회귀: 체인 없이 기존 `test_menu_restructure`·`test_state_machine`·`test_p3_history` 그대로 통과(`_prepare`→`job_params` 이동, `put_tstar`→`tstar_confirm` 이동) | 기존 |
| V-RA-15 | 끊김 복구: `cur_job_id` 종료인데 RUNNING 인 행 → 리퍼 1주기 뒤 진행 | 워커 |
| V-RA-16 | 화면: 체크박스 전송값; 주 버튼 라벨·비활성 사유 4종; 진행 줄 4상태 문구·[일괄 취소] 확인; 폴링 조건; 이력 '일괄' 배지 | 프런트(vitest, mock) |
| V-RA-E2E | 실서버: 새 Case(체크) → 자동 ①②③④ → PASS DONE → ④ [라이브러리에 등록] 사람 클릭; BLOCKED 픽스처로 ② 멈춤 → 고급 지정 → [이어서 실행] → DONE | `scripts/e2e_run_all.mjs` |

## 13. 파일 소유권

| 담당 | 파일 |
|---|---|
| **Impl-Backend** | `migrations/versions/0013_run_all.py`(신규) · `backend/esl_platform/core/db/tables.py`(run_alls, jobs.run_all_id, 인덱스) · `core/run_all.py`(신규: evaluate·advance·on_job_end·가드·멈춤 메시지) · `core/job_params.py`(신규: `core_settings_for`·ESL_SOLVE·VALIDATE params — `services/jobs._prepare` 에서 이동) · `core/tstar_confirm.py`(신규: `put_tstar` 저장부 이동) · `core/repositories/run_all.py`(신규) · `core/repositories/jobs.py`(`insert_job run_all_id`, release·interrupt·request_cancel 훅 호출) · `api/services/run_all.py`(신규) · `api/services/cases.py`(put_tstar 위임, create_case run_all, case_full run_all, RA-D-7 검사) · `api/services/jobs.py`(_prepare 위임, create_job·retry RA-D-7) · `api/services/history.py`(run_all_id) · `api/routers/cases.py`(3 경로) · `api/schemas.py`(RunAllStart·RunAllOut·CaseCreate.run_all·CaseOut.run_all·run_all_error·이력 필드) · `worker/esl_worker/executor.py`(② 사전 계산 → release prep) · `worker/esl_worker/runtime.py`(끊김 복구) · `backend/tests/test_run_all*.py`·`worker/tests/test_run_all_chain.py`(신규) · `docs/manual/user.md`(절 1개) · `scripts/e2e_run_all.mjs`(신규) |
| **Impl-Frontend** | `frontend/src/api/types.ts`(RunAll, Case.run_all, 이력 run_all_id) · `frontend/src/api/p3.ts`(startRunAll·getRunAll·listRunAll·cancelRunAll, createCase run_all) · `frontend/src/pages/newcase/NewCase.tsx`(체크박스) · `frontend/src/pages/CasePage.tsx`(주 버튼·폴링·RunAllBar 배치) · `frontend/src/shell/RunAllBar.tsx`(신규) · `frontend/src/shell/StageStepper.tsx`(현재 체인 단계 강조 속성만) · `frontend/src/components/HistoryTable.tsx`·`pages/history/CaseHistory.tsx`·`pages/history/JobReview.tsx`(배지·기록) · `frontend/src/mock/p3mock.ts`·`mock/server.ts`(mock 경로) · `frontend/src/pages/guide/content.ts` · `frontend/src/__tests__/run_all.test.tsx`(신규) |

- 공유 경계: 프런트는 §8 형식만 의존. 백엔드는 `REASON_MESSAGES` 와 §7 메시지를 응답 `stop_reason.message` 로 완성해 보낸다(프런트 문구 사전 없음).

## 14. 리스크

- R-RA-1 ② 자동 확정이 사람 검토를 건너뜀 — 가드 G1~G4 로 기존 규칙상 "1순위를 못 쓰는" 경우만 잡는다. 1순위가 물리적으로 부적절한(예: 국부 이상 요소) 경우는 가드가 못 잡음 → 결과는 ④ 판정과 사람의 [라이브러리에 등록] 단계에서 걸러진다(사용자 확정 a). Q1 B 를 고르면 사라지는 리스크.
- R-RA-2 워커 훅 트랜잭션이 길어짐 — `auto_321` 계산은 트랜잭션 밖(prep)이라 트랜잭션 안은 DB 쓰기·`job_params`(disp_frames 목록 읽기)뿐.
- R-RA-3 슬롯 대기열 끼어들기 — 체인 사이에 다른 Case 작업이 실행돼 총 시간이 늘 수 있음(우선순위 없음, 의도된 공정성).
- R-RA-4 `_prepare`·`put_tstar` 이동 회귀 — V-RA-14 로 기존 시험 그대로 통과를 요구.

## 15. 범위 밖

- 라이브러리 자동 등록, CASE_REPORT 대기, ESL 재료 override 지정, 여러 Case 일괄(프로젝트 단위), 체인 우선순위·슬롯 예약, 실패 작업 자동 재시도(사람이 [재시도] 또는 [이어서 실행]).

## 16. 결정 필요 (권장안 = 이 문서 본문에 반영된 값)

| # | 질문 | 권장안(확정값으로 진행) | 대안 |
|---|---|---|---|
| Q1 | ② `TSTAR_NOT_CONFIRMED`(지지 세트 없음, auto t* 만) 에서 체인이 t* 를 자동 확정해도 되나? | **A: 가드 G1~G4 통과 시 자동 확정**(1순위 t* 가 D 안·조정 없음·지표 오류 없음·사람이 고른 t* 와 같음), 실패 시 멈춤. 일괄 실행 시작 = 추천 t* 수락 의사로 보고 `tstar.confirmed.by = run_all` 로 기록 | B: 항상 ② 에서 멈춤(새 Case 는 매번 ① 뒤 멈춤 → 사람이 [t* 확정] 후 [이어서 실행]) |
| Q2 | ④ FAIL·UNDETERMINED 의 체인 상태 | **STOPPED**(`VALIDATION_FAIL`·`VALIDATION_UNDETERMINED`, ④ 에서 사유 표시 — 사람 판단 필요) | DONE + verdict(완료로 보고 사유만 표시) |

## 변경 메모

- (2026-11-02) 초안 작성(main b11a0bc). 사용자 확정 (a)~(c) 반영, 결정 필요 Q1·Q2 권장안 본문 반영.
