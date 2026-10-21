# 계약: MCP 준비(사내 LLM 조작 사전 작업) — esl-mcp-ready

- 상태: **초안 — 미결 없음**(2026-10-21, Plan; 미결 3건 사용자 확정 → EM-C1). 사용자 요청(2026-10-21): "esl-platform도 MCP를 사용할 수 있게 구상하고, 기능 추가에도 문제없도록 계획."
- 기준: main 5632262(v0.5.2), migration HEAD `0007`(history_indexes).
- 형제 계약: physicsai-platform `docs/contracts/mcp-ready.md`(같은 사용자·같은 서버·같은 대시보드). 원칙·도구 이름·봉투·오류 코드·토큰 규칙은 **그 문서와 같게** 하고, 다른 점은 §17 표에만 둔다.
- 우선순위: **이 문서 > [esl.md](esl.md) §5(API 공통·권한)·[esl_p3_ux.md](esl_p3_ux.md) §9.1(PC 연결 토큰)** — 이 문서가 바꾸는 것은 §2.1 "기존 규칙 예외" 표에만 있다.
- ID 규칙: 결정 `EM-n`, 시험 `V-EM-n`, 변경 메모 `EM-Cn`.

## 0. 사용자 결정·설계 원칙(2026-10-20·21, physicsai와 공통)

1. 대상 LLM은 **폐쇄망 사내 LLM만**. 외부 LLM·외부 네트워크 호출 없음. MCP 미지원 클라이언트를 위해 **OpenAI 호환 function 정의**를 병행한다.
2. 이번 범위는 **플랫폼 쪽 준비**(인증·확인 절차·감사·요약·스펙)다. MCP 서버 프로세스 자체는 후속(비범위).
3. **기능을 나중에 추가해도 MCP 쪽 수정이 최소화**되어야 한다(§15): 도구 정의는 openapi `x-mcp`에서 자동 생성, 작업 생성은 공통 작업 계약으로 일원화, 요약은 레지스트리, 용어집은 코드 자동 추출, 누락은 정적 시험이 잡는다, 깨지는 변경은 새 도구 이름.
4. 기본값으로는 기존 동작 불변: `mcp.enabled: false`(API 토큰 인증·`/mcp/*`·토큰 화면 전부 꺼짐). PC 연결 토큰(`esl_ct_`) 흐름은 켜고 끔과 무관하게 그대로.
5. 두 플랫폼을 사내 LLM이 **같은 방식으로** 다루게 한다: 같은 도구 이름(`plan_job`·`run_job`·`job_status`…), 같은 `JobPlan`·`JobStatus`·`Summary` 봉투, 같은 MCP 오류 코드, 같은 토큰 수명·범위 규칙. 다른 것은 접두·대상 id·도메인 엔티티뿐.

## 1. 범위

| 범위 | 비범위(후속) |
|---|---|
| 사용자별 API 토큰 `esl_at_`(발급·폐기·만료·범위), Bearer 인증 경로 | MCP 서버(stdio/HTTP) 구현·배포, 사내 LLM 연결 |
| 공통 작업 계약 `/mcp/jobs*`(plan → confirm_token → run → status → summary → cancel) | 기존 생성 API(`POST /cases/{id}/jobs`·`/library/analyses`·`/library/comparisons`) 개조 — 웹 흐름 불변 |
| 토큰 요청 감사 `api_audit`·조회·보존 | **업로드**(`/uploads*` — 브라우저·PC 도구 전용, 확정 비범위) |
| 요약 레지스트리 `/mcp/summary/*`(이력·결과·라이브러리 서비스 재사용) | Case **수정·보관**(`PATCH /cases/{id}`·archive — 확정 제외) |
| **Case 생성** `create_case`(서버에 이미 있는 입력만 — 완료된 업로드·허용 루트 폴더, §5.4) + 입력 후보 조회 `list_case_inputs` | |
| openapi `x-mcp`·도구 스펙 생성기(MCP + OpenAI)·용어집 | 사용자 판단 단계(t* 확정·BC 지지점 저장·재료 override·라이브러리 등록/폐기) — §5.3 제외 목록 |
| 토큰별 호출 제한(429) | 다중 API 프로세스용 분산 제한(현재 uvicorn 단일 프로세스, `deploy/esl_service.py`) |
| "내 API 토큰" 화면(최소) | 유사 Case 검색·임베딩 RAG(사내 임베딩 모델 있을 때 별도 계약) |

## 2. 현황(코드 확인, 5632262)

| 항목 | 현재 | 근거 |
|---|---|---|
| 인증 | 대시보드 세션 introspection(TTL 캐시, 키 sha256). 쿠키 `analysis_canvas_session` 우선, 없으면 Bearer — **`esl_ct_` 이외 Bearer 값은 대시보드로 전달** | `core/auth.py`(`DashboardAuth.authenticate`), `api/deps.py:get_principal` |
| 기계 토큰(기존) | PC 연결 토큰 `esl_ct_<token_urlsafe(32)>`: 6자리 코드 교환으로 발급, `client_tokens`(sha256·`token_prefix` 12자·**project_id 1개·role 스냅숏**·device_name·expires/revoked/last_used), 범위 = 그 프로젝트 `/uploads*`·`GET /version`(밖은 403 `CLIENT_TOKEN_SCOPE`), CSRF 면제, 매 요청 `last_used_at` 갱신 | `services/client_tokens.py`, `tables.client_tokens`, migration 0006 |
| 권한 | 역할 `general/power/admin`(대시보드 `/auth/me`, 프로젝트별) + `is_global_admin`. 조회 = ACTIVE 전원, 실행 = 그 project power+(`require_execute`), 취소·재시도 = **작업 생성자 또는 전역 관리자**(`_can_touch`) | esl.md §5, `services/jobs.py` |
| CSRF | 비GET은 `X-ESL-Request: 1`(없으면 403 `CSRF_HEADER_REQUIRED`) | deps.py |
| 감사 | **감사 테이블 없음**(physicsai `audit_events`에 해당하는 것 없음). 작업은 `jobs.created_by/_name`, 토큰은 `client_tokens.revoked_by`만 | `core/db/tables.py` |
| openapi | `scripts/dump_openapi.py [--check]` → `docs/contracts/openapi_p1b.json`(정렬·결정적, test-all). operation 69개, operationId = FastAPI 기본. 프런트 `check:api`가 **components.schemas ↔ `src/api/types.ts`(+history.ts) 키 대조**(operationId 고정 시험은 없음) | scripts, `frontend/scripts/check-api.mjs` |
| 작업 종류 | `JOB_TYPES` 7종: `CASE_EXTRACT`(SLOT; step H3D_EXTRACT(LOCAL, h3d 입력만)·EXTRACT·TSTAR_SCAN·EXTRACT_REGISTER), `ESL_SOLVE`(SLOT), `VALIDATE`(SLOT), `EXPORT`(LIGHT), `CASE_REPORT`(LIGHT, VALIDATE 성공 시 자동 큐), `LIB_ANALYZE`(SLOT, case 없음·analysis_id), `LIB_COMPARE`(LIGHT, comparison_id). **t*는 별도 작업이 아니라 CASE_EXTRACT step** | `core/job_types.py` |
| 작업 생성 | Case 작업 = `POST /cases/{id}/jobs {job_type, params}` → `jobs._prepare`(사전조건 409 `PREREQUISITE_MISSING`+missing, params 422 `INVALID_PARAMS`) → insert. 라이브러리 = `POST /library/analyses`·`/library/comparisons`. 미리보기(dry-run) API 없음 | `services/jobs.py`, `services/library.py`, `services/comparisons.py` |
| 사용자 판단 쓰기 | `PUT /cases/{id}/tstar`(t* 확정), `POST /cases/{id}/support-sets`(BC 지지점 저장), `POST …/support-sets/suggest`, `ESL_SOLVE.params.material_override`, `POST /library/entries`·`…/retire`(등록·폐기) | routers/cases.py, library.py |
| Case 입력 | `POST /cases {project_id, folder_name(FOLDER_RE), title, rad_path, results_dir|h3d_path(정확히 하나), part_title?}` — power+(`require_execute`)·`require_config_ok`. 경로는 `check_input_path`(`storage.input_roots` 안 — `upload_root`는 설정 로드 때 자동 포함, 루트 아래 심링크 성분 거부·realpath 탈출 거부·`esl_root`/`spdm_roots`와 겹치면 `PATH_UNSAFE`) + `check_principal_upload_area`(업로드 루트 아래는 본인 사용자 폴더만 — 아니면 403 `UPLOAD_FOLDER_FORBIDDEN`, `_backup` 거부, 전역 관리자 예외). rad include도 같은 두 검사. 파트는 `_check_part` → 422 `PART_NOT_FOUND`·`PART_AMBIGUOUS`·`PART_MISMATCH`(done.json part_id ≠ rad 파트 id) — **불일치면 생성 안 함**. h3d 입력은 `altair.hw_exe_path` 없으면 503 `H3D_EXTRACT_UNAVAILABLE`. 중복 409 `CASE_NAME_EXISTS`·`FOLDER_EXISTS` | `services/cases.py:create_case·_check_part`, `core/paths.py:check_input_path`, `core/uploads.py:check_upload_area`, schemas.CaseCreate |
| 업로드 | `uploads(project_id, user_id, dir_path=<upload_root>/<user_seg>/<UTC>_<name>, state OPEN/COMPLETED/CANCELED/STALE, result)`. 소유 = 생성자 또는 전역 관리자(`_owned`, 아니면 404 `UPLOAD_NOT_FOUND`), PC 토큰은 묶인 프로젝트만. complete 시 `inspect_upload`가 `rad/`의 `_0000.rad`(또는 단일 .rad) 1개·`.h3d` 1개 또는 `results/` 아래 done.json 폴더 1개·include(업로드 안만 따라감)·`list_parts`를 검사해 `result{ok, rad_path, results_dir, h3d_path, parts, missing_includes, problems}` 저장 | `services/uploads.py`, `tables.uploads` |
| 서버 폴더 찾아보기 | `GET /fs/browse?root=&path=` — 루트 = `input_roots`(업로드 루트 포함) + (`browse_spdm`이면) `spdm_roots`, 인덱스·상대경로 지정, 심링크·숨김·`_backup`·`.part` 제외, 업로드 루트 아래 본인 폴더만 | `services/fsbrowse.py:roots·browse` |
| 동시 실행 | SLOT 레인 `worker.slots`(기본 2), LIGHT 1. 같은 Case 비종료 같은 종류 1개(`ux_jobs_case_type_active` → 409 `CASE_JOB_BUSY`), 같은 Case RUNNING 1개, 분석·비교별 비종료 1개 | tables.py 인덱스, worker runtime |
| 이력·결과 조회 | `GET /history`(keyset), `GET /jobs/{id}/review`(timing·input·error·logs·result{availability,state,stale_reasons,diff}), `/esl-runs/{id}`(+`/forces`), `/validations/{id}`, `/cases/{id}/artifacts`, 라이브러리 목록·상세 | esl_p3_history.md, services/history.py·results.py |
| 파트 title | `part_title_match` `exact`|`exact_ci`(공백·_·- 연속 = 한 칸, casefold), 오류 `PART_NOT_FOUND`·`PART_AMBIGUOUS`·`PART_MISMATCH` | `services/system.py:norm_title·match_parts`, `esl/rad/parser.py` |
| 로그 마스킹 | `logging.mask_patterns`(설정 정규식)를 작업 로그 응답에 적용 | `services/jobs.py:_masker` |

### 2.1 기존 규칙 예외(이 문서가 바꾸는 것 — 이 표 밖은 불변)

| 기존 규칙 | 예외 | 이유 |
|---|---|---|
| esl.md §5 인증 = 대시보드 introspection(Bearer도 대시보드로) | 접두 `esl_at_` Bearer는 **대시보드로 보내지 않고** `api_tokens`로 검증(`esl_ct_`와 같은 처리) | 토큰 유출 경로 축소, 대시보드 변경 없음 |
| esl.md §5 역할 = 대시보드가 단일 출처 | `api_tokens.principal_snapshot`에 **전 프로젝트 역할 스냅숏** 저장·세션 로그인 때 갱신(§4.3). 선례: `client_tokens.role`(1개 프로젝트) | 토큰 요청에는 세션이 없어 introspection 불가 |
| esl.md §5 비GET CSRF 헤더 | `esl_at_` 토큰 요청은 면제(`esl_ct_` 선례와 동일) | 쿠키 미사용 → CSRF 대상 아님 |
| esl.md §5 판정 순서 401 → 404 → 403 → 409 | 토큰 요청은 401 → 403(허용 operation·범위) → 429 → 404 → 403(역할) → 409 | 대상 존재 여부를 범위 밖 토큰에 노출하지 않음 |

취소 규칙은 예외가 아니라 **더 좁힘**: 토큰 요청의 `cancel_job`은 그 토큰이 만든 작업만(§5.2). 기존 웹 취소(생성자·전역 관리자)는 불변.

## 3. 결정 요약

| ID | 결정 |
|---|---|
| EM-1 | 기계 인증 = 사용자별 API 토큰 `esl_at_<id8>_<secret43>`(Bearer). **별도 테이블 `api_tokens`**, 해시·접두 판정·`last_used` 간격 갱신은 공용 모듈 `core/tokens.py`로 뽑아 `client_tokens`도 import만 바꾼다(동작 불변). 범위 `read < run < admin` |
| EM-2 | `client_tokens`를 확장하지 않는 이유: 발급 경로(코드 교환 대 세션 발급)·결속(1개 프로젝트 대 사용자 전체)·범위 모델(경로 접두 대 x-mcp 허용 목록)·스냅숏 갱신이 모두 달라 조건부 CHECK·nullable 열이 늘고, 운영 중인 PC 도구 흐름 회귀 위험이 큼. `esl_ct_` 토큰은 MCP 도구를 **절대** 쓸 수 없다(V-EM-3) |
| EM-3 | 토큰 주체 = 소유자. 권한 = min(토큰 범위, 역할 스냅숏). **권한 출처 = 역할 스냅숏 방식(확정, EM-C1)** — 스냅숏은 소유자 **세션 introspection 캐시 미스 후 성공**마다 갱신, `snapshot_max_age_days`(기본 **30**) 넘으면 401 `API_TOKEN_STALE` |
| EM-4 | 토큰 요청은 **`x-mcp.tool`이 붙은 operation만** 허용, 그 밖은 403 `API_TOKEN_OPERATION_NOT_ALLOWED`. 토큰 관리 API는 세션 전용(403 `SESSION_REQUIRED`) |
| EM-5 | 작업 생성은 `/mcp/jobs*` + **작업 종류 레지스트리 `JOB_KINDS`**로 일원화. plan_fn·create_fn은 기존 `_prepare`·`create_job`·`library.create_analysis`·`comparisons.create` 호출만(로직 복제 금지). 기존 생성 API·웹 흐름 불변 |
| EM-6 | `cost: heavy` 종류(SLOT 레인: case_extract·esl_solve·validate·lib_analyze)는 `plan_job` → `confirm_token`(600초·1회용·요청 해시 결합) → `run_job`. 토큰 요청에만 강제 |
| EM-7 | 사용자 판단 단계(t* 확정·지지점 저장/제안·재료 override·라이브러리 등록/폐기)와 Case 수정·보관·업로드·재시도는 `MCP_JOB_EXCLUDED`(사유 필수)로 제외. Case 생성은 제외가 아니라 EM-16. MCP용 params 모델은 웹 params의 **부분 집합**(예: esl_solve에 material_override 없음) |
| EM-8 | 감사 = 새 테이블 `api_audit`(토큰 요청의 모든 비GET·모든 거부·`plan_job`·`run_job`·`create_case`, 세션의 `/mcp/jobs*`·`/mcp/cases` 쓰기, 토큰 발급·폐기). **본문·값·토큰 원문 미저장**. esl에는 기존 감사 테이블이 없으므로 신설만 |
| EM-9 | 요약 = 엔티티 레지스트리 `SUMMARIES` + 공통 봉투, 응답 ≤ 8 KiB. summary_fn은 이력·결과·라이브러리 **기존 서비스 함수 호출만** |
| EM-10 | `x-mcp` 확장(도구명·위험도·confirm·버전). 기존 operationId 불변, 새 `/mcp/*`만 명시 operationId. 모든 operation은 `x-mcp`(도구/제외) 또는 동결 목록 `LEGACY_UNMARKED` — 정적 시험 |
| EM-11 | `scripts/gen_tool_specs.py`가 openapi에서 MCP tool·OpenAI function·용어집 JSON을 결정적으로 생성, `--check`를 test-all에 |
| EM-12 | 호출 제한 = 토큰별 분당 요청·분당 plan·동시 진행 작업 상한, 429 + `Retry-After`(프로세스 메모리) |
| EM-13 | 용어집 = 코드 자동 추출(JOB_TYPES·step·JOB_KINDS·SUMMARIES·오류 코드·enum·코어 설정 enum) + 사람 YAML. `GET /mcp/glossary` |
| EM-14 | 깨지는 변경은 새 도구 이름(`<tool>_v2`)·새 kind 이름. 생성기 `--check`가 직전 스펙과 비교해 막는다 |
| EM-15 | MCP 전용 응답·요청 스키마 이름은 `Mcp` 접두. 프런트 `check:api`는 `^Mcp` 스키마를 대조에서 뺀다(프런트가 쓰지 않음). `ApiToken*`·`StatusOut.features`는 프런트 타입에 추가 |
| EM-16 | **Case 생성 허용(확정, EM-C1)**: "프로젝트 입력 데이터"(§5.4.1 — 그 프로젝트의 완료된 업로드 또는 허용 루트 안 폴더의 rad 1개 + h3d 1개/추출 결과 폴더 1개)로만. 임의 경로 문자열·업로드는 받지 않는다. 후보 조회 `list_case_inputs`(read) + 생성 `create_case`(run, `confirm: never`, 공통 작업 계약 밖의 쓰기 = `MCP_ACTIONS` 등록). 생성은 기존 `cases.create_case` 호출만(경로·파트·중복 검사 그대로 — 파트 불일치 422, 미생성). 감사·호출 제한 적용 |
| EM-17 | `denied_job_kinds` 기본 `[]`(확정, EM-C1) — 무거운 작업 통제는 confirm_token(EM-6)으로 충분 |

## 4. 기계용 인증(API 토큰)

### 4.1 형식·저장

- 형식 `esl_at_<id8>_<secret>`: `id8` = 소문자 base32 8자(공개 식별자), `secret` = `secrets.token_urlsafe(32)`(43자). 전체 길이 고정 검사(58자), 200자 초과·형식 오류는 DB 조회 없이 401.
- DB에는 `token_hash = sha256(전체)` hex(UNIQUE)와 `token_prefix = "esl_at_<id8>"`(15자)만. 평문은 `POST /me/api-tokens` 응답 1회. 고엔트로피라 느린 해시·pepper 없음(`client_tokens`와 같은 `secret_hash`).
- `logging.mask_patterns` 예시 설정에 `esl_(at|ct|cf)_[A-Za-z0-9_\-]+` 추가(config 예시 파일만, 기존 배포는 키 그대로). 오류 메시지에는 prefix만.

### 4.2 인증 흐름(`deps.get_principal` — 세션·`esl_ct_` 경로 코드 불변)

```text
bearer = Authorization 헤더 값
if bearer 가 "esl_at_" 로 시작:                       # API 토큰 경로(쿠키 무시)
    mcp.enabled=false            → 401 AUTHENTICATION_REQUIRED (대시보드 호출 0회)
    형식 오류·해시 불일치         → 401 API_TOKEN_INVALID
    revoked_at                   → 401 API_TOKEN_REVOKED
    expires_at ≤ now             → 401 API_TOKEN_EXPIRED
    now - snapshot_at > snapshot_max_age_days → 401 API_TOKEN_STALE("ESL 웹 화면에 한 번 접속해 권한을 갱신하세요")
    route 에 x-mcp.tool 없음      → 403 API_TOKEN_OPERATION_NOT_ALLOWED
    범위 부족                     → 403 API_TOKEN_SCOPE (required)
    호출 제한(§11)                → 429
    Principal = 스냅숏(user_id, username, display_name, is_global_admin, roles) + api_token_id
    CSRF 면제
elif bearer 가 "esl_ct_" 로 시작:  기존 client_tokens 경로 그대로(MCP 도구 불가 — 범위가 /uploads*·/version)
else:                              기존 세션 경로 그대로
    성공(캐시 미스) + mcp.enabled → 그 user_id 의 유효 API 토큰 스냅숏 갱신(§4.3)
```

- 허용 판정은 라우트의 `openapi_extra["x-mcp"]`를 앱 기동 시 `route_policy.build(app)`이 `(method, path_template) → x-mcp` 표로 만들어 둔다(요청마다 openapi 생성 안 함).
- 범위: `x-mcp.risk` read → read+, run → run+, admin → admin(+스냅숏 `is_global_admin`). 그 위에 기존 `require_execute` 등이 스냅숏 역할로 그대로 돈다.
- `Principal`에 `api_token_id: str | None` 필드 추가(기본 None — 기존 생성자 호환). 요청 문맥 contextvar `current_api_token_id`로 `jobs_repo.insert_job`이 `jobs.api_token_id`를 채운다.
- `last_used_at`·`last_used_ip`는 `mcp.token.last_used_update_s`(60초) 간격으로만 갱신.

### 4.3 역할 스냅숏

- 발급 시 세션 Principal의 `{is_global_admin, roles}` 저장, `snapshot_at = now`.
- 세션 introspection 캐시 미스 후 성공(≤ `auth.cache_ttl_s`에 1회/사용자)마다 같은 user_id 미폐기·미만료 토큰 스냅숏 갱신(같은 값이면 `snapshot_at`만). `dev_static` 모드는 갱신 안 함(시험은 직접 주입).
- 갱신 시 `is_global_admin`이 false가 되면 admin 토큰 자동 폐기(`revoked_by = "system:role_change"`).
- 계정 정지(대시보드 403 `ACCOUNT_NOT_ACTIVE`)는 스냅숏이 갱신되지 않아 `snapshot_max_age_days`(기본 **30일**, 1~90) 후 막힌다. 즉시 차단은 전역 관리자 폐기.
- 권한 출처는 **역할 스냅숏 방식으로 확정**(2026-10-21, EM-C1): 대시보드 서비스 introspection(토큰 요청마다 대시보드에 사용자 상태 질의)은 쓰지 않는다. physicsai와 같은 대시보드이므로 같은 방식·같은 기본값(30일)을 쓴다(V-EM-14 공통 항목).

### 4.4 API(세션 전용 — 토큰 요청 403 `SESSION_REQUIRED`, `x-mcp.exclude`)

| 메서드·경로 | 권한 | 요청 | 응답 | 오류 |
|---|---|---|---|---|
| `GET /me/api-tokens` | 로그인 | – | `ApiToken[]`(최신순, 폐기 포함 최근 90일) | 404 `MCP_DISABLED` |
| `POST /me/api-tokens` | 로그인 | `{name, scope, expires_in_days?}` | `201 {token:"esl_at_…", api_token}` | 403 `API_TOKEN_SCOPE`(run = 어느 프로젝트든 power+, admin = 전역 관리자), 409 `API_TOKEN_LIMIT`·`API_TOKEN_NAME_EXISTS`, 422 |
| `DELETE /me/api-tokens/{id}` | 소유자 | – | `204`(멱등, revoked_at) | 404 `API_TOKEN_NOT_FOUND` |
| `GET /admin/api-tokens?user_id=&active=` | 전역 관리자 | – | `ApiToken[]`(+user_id, username) | |
| `POST /admin/api-tokens/{id}/revoke` | 전역 관리자 | – | `ApiToken` | 404 |

`ApiToken` = `{id, name, scope, token_prefix, created_at, expires_at, last_used_at, revoked_at, revoked_by, snapshot_at, status:"active"|"expired"|"revoked"|"stale"}`(physicsai와 동일 키). `name` 1~64자 `^[0-9A-Za-z가-힣 _.-]+$`. `expires_in_days` 기본 30, 1~90, 무기한 없음. 발급·폐기는 `api_audit`(`operation_id` = 해당 operation, `result_code` null).

### 4.5 화면(최소, Impl-Frontend)

- 사용자 메뉴 "내 API 토큰"(`/status` `features.mcp` true일 때만): 표(이름·범위·접두·만료·마지막 사용·상태) + 발급(이름·범위 라디오·만료일 수) + 폐기(확인 대화). 기존 "PC 연결" 메뉴와 별개 화면, 문구로 구분("PC 도구용 연결은 PC 연결 메뉴").
- 발급 직후 평문 1회 대화(복사·"닫으면 다시 볼 수 없습니다"). 평문을 localStorage·상태 저장소·로그에 남기지 않음(정적 시험).

## 5. 공통 작업 계약(dry-run + 확인 토큰)

### 5.1 `JOB_KINDS`(`esl_platform/api/mcp/job_kinds.py`)

종류 하나 = `{kind, version, label_ko, stage(UI 1~9), target:"case"|"project", job_types[], cost:"heavy"|"light", params_model(pydantic — 모든 필드 설명·단위·범위), plan_fn, create_fn, summary_entity, cancel_fn?}`.
- plan_fn: **읽기 전용 연결**에서 기존 `_prepare`(Case 종류) 또는 라이브러리 선택 함수(분석·비교)를 호출해 사전조건·params를 검사하고, insert 없이 `JobPlan`을 만든다. `DomainError`는 `problems[{code, message, missing?}]`로 바꾼다(422·409 그대로 코드 유지). 같은 Case 같은 종류 비종료 작업이 있으면 problem `CASE_JOB_BUSY`.
- create_fn: 기존 `jobs.create_job`(Case) / `library.create_analysis` / `comparisons.create_comparison` 호출. MCP params를 웹 params로 옮기기만 한다.
- 추정: `estimate_min` = 같은 job_type(case_extract는 같은 `input_kind`) 최근 성공 20건 `finished_at−started_at` 중앙값, 없으면 `estimate_basis:"none"`. `queue_ahead` = 같은 레인 QUEUED 수(`jobs_repo.queue_lane_all`).

초기 등록(첫 구현 범위 — 7개 job_type 전부):

| kind | job_type(기존 경로) | target | cost | MCP params(웹의 부분 집합) | plan 근거(재사용) | summary_entity |
|---|---|---|---|---|---|---|
| `case_extract` | CASE_EXTRACT(`POST /cases/{id}/jobs`) | case | heavy | h3d 입력만 `{hot_k? 1..100000, top_n? 1..100}` | `_prepare`(입력 경로·include 검사·fingerprint), `input_kind`·h3d 크기[bytes]·`H3D_EXTRACT` step 유무·`altair.max_concurrent_hw` | `extract` |
| `esl_solve` | ESL_SOLVE | case | heavy | `{frame_index? (t* 후보만), support_set_id? (저장된 세트만)}` — **material_override 없음** | `_prepare`(extract·tstar·support_set·disp_frame missing), 사용 frame·metric·지지점 수·요소 수 | `esl_run` |
| `validate` | VALIDATE | case | heavy | `{esl_run_id?}`(없으면 현재 run) | `_prepare`(현재·READY·stale 아님) | `validation` |
| `export` | EXPORT | case | light | `{esl_run_id?, targets? ⊂ [radioss_inc, fem, csv]}` | `_prepare` + 그 run 최신 검증 verdict(없으면 warning `EXPORT_UNVALIDATED`) | `export` |
| `case_report` | CASE_REPORT | case | light | `{validation_id?}` | `_prepare` | `report` |
| `lib_analyze` | LIB_ANALYZE(`POST /library/analyses`) | project | heavy | `AnalysisCreate` − project_id | 필터 적용 항목 수(`library.list_entries` 같은 필터 함수)·대상 항목·덱 생성 여부 | `analysis` |
| `lib_compare` | LIB_COMPARE(`POST /library/comparisons`) | project | light | `ComparisonCreate` − project_id | 두 버전 항목 수·base_version 해석 결과 | `comparison` |

### 5.2 API(`esl_platform/api/routers/mcp.py`, 접두 `/esl/api/mcp`, 세션·토큰 모두 허용)

| 메서드·경로 | operationId(= tool) | risk | 요청 | 응답 |
|---|---|---|---|---|
| `GET /mcp/job-kinds` | `list_job_kinds` | read | – | `[{kind, version, label_ko, stage, target, cost, confirm_required, summary_entity}]` |
| `GET /mcp/job-kinds/{kind}` | `describe_job_kind` | read | – | `{kind, version, target, params_schema, example, limits, cost}` |
| `POST /mcp/jobs/plan` | `plan_job` | read | `{kind, case_id?, project_id?, params}` | `McpJobPlan` |
| `POST /mcp/jobs` | `run_job` | run | `{kind, case_id?, project_id?, params, confirm_token?}` | `201 McpJobStatus` |
| `GET /mcp/jobs?project_id=&case_id=&state=&kind=&mine=&limit≤50&cursor=` | `list_jobs` | read | – | `{items: McpJobStatus[](짧은 형태), next_cursor}` — `history.list_history` 재사용 |
| `GET /mcp/jobs/{job_id}` | `job_status` | read | – | `McpJobStatus` |
| `GET /mcp/jobs/{job_id}/summary?top_n=` | `job_summary` | read | – | `McpSummary`(`summary_entity`로 위임, 실패 작업은 `job` 엔티티) |
| `GET /mcp/jobs/{job_id}/log?step=&cursor=` | `job_log` | read | – | 기존 `LogOut`(마스킹·1000줄/256 KiB 상한) — `jobs.job_log` 재사용 |
| `POST /mcp/jobs/{job_id}/cancel` | `cancel_job` | run | – | `202 McpJobStatus`(멱등) |

```jsonc
// McpJobPlan — physicsai JobPlan과 같은 키 + 대상 키만 다름(study_id → case_id|project_id)
{"kind":"esl_solve","kind_version":1,"case_id":"…","project_id":"…","valid":true,
 "runs":1,"parallel":1,"lane":"SLOT","uses_global_slot":true,"hpc_jobs":0,
 "estimate_min":12,"estimate_basis":"recent_median"|"none","disk_bytes_est":null,
 "targets":{"case":"chassis_rear 낙하 F1 (rear_f1)","part_title":"CHASSIS_REAR","frame":"87 (t=0.0123 s, max_strain)","support_set":"자동 3-2-1 (ss-2)"},
 "queue_ahead":1,"warnings":[{"code":"…","message":"…"}],"problems":[],
 "confirm_required":true,"confirm_token":"esl_cf_…"|null,"expires_at":"…"}
// McpJobStatus — physicsai JobStatus와 같은 키(+case_id·project_id)
{"job_id":"…","kind":"esl_solve","job_type":"ESL_SOLVE","case_id":"…","project_id":"…","state":"RUNNING",
 "progress_pct":40,"progress_label":"…","queue_position":null,"entity":{"type":"esl_run","id":"…"}|null,
 "created_by_name":"…","via_token":"esl_at_ab12cd34"|null,"created_at":"…","started_at":"…","finished_at":null,
 "error":{"code":"…","message":"…"}|null}
```

규칙(physicsai §5.2와 같음):
- `case_id`·`project_id`는 kind의 `target`에 맞는 것 정확히 하나(아니면 422 `INVALID_PARAMS`). case 종류의 project 권한은 Case의 project로 판정.
- `problems` 있으면 `valid:false`, `confirm_token:null`. read 토큰·세션 요청도 `confirm_token:null`.
- `confirm_token` = `esl_cf_` + 난수. `mcp_plans`에 해시 저장, **(api_token_id, kind, case_id|project_id, sha256(정규화 JSON params))** 결합, TTL 600초, 1회용.
- `run_job`(토큰 + heavy + `require_confirm_for_token`): 없으면 428 `CONFIRM_REQUIRED`(+`plan_with:"plan_job"`), 불일치·만료·사용됨·모름 409 `CONFIRM_INVALID`(+`reason: mismatch|expired|used|unknown`). light·세션은 confirm 없이 생성(세션이 보내면 검증만).
- 생성 시점 재검증: create_fn이 기존 검증을 그대로 거쳐 plan 이후 변화(`CASE_JOB_BUSY`·`PREREQUISITE_MISSING`)는 기존 409.
- `cancel_job`: 기존 `jobs.cancel_job`. 토큰 요청은 **그 토큰이 만든 작업**(`jobs.api_token_id` 일치)만, 아니면 403 `FORBIDDEN`. 세션은 기존 권한.
- `entity`: 성공 후 결과 참조(= `history` 의 `result_ref`: extract·esl_run·validation·export·report·analysis·comparison).
- `mcp.allowed_job_kinds`(null = 전체)/`denied_job_kinds`(기본 `[]` 확정 — 7종 전부 허용, heavy는 confirm으로 통제) → 403 `JOB_KIND_DENIED`, 모르는 kind 422 `JOB_KIND_UNKNOWN`. 운영자가 HyperView 라이선스 등 사유로 막으려면 설정에 `[case_extract]` 등을 넣는다.

### 5.3 제외 목록 `MCP_JOB_EXCLUDED`(`job_kinds.py`, 사유 필수)

키 = job_type 또는 `action:<이름>`(작업이 아닌 쓰기). 값 = `{reason, operations:[operationId…]}`. 초기:

| 키 | operations | 사유 |
|---|---|---|
| `action:TSTAR_CONFIRM` | `PUT /cases/{id}/tstar` | 사람 판단: t* 확정 |
| `action:SUPPORT_SET` | `POST …/support-sets`, `POST …/support-sets/suggest` | 사람 판단: BC 지지점 |
| `action:MATERIAL_OVERRIDE` | (esl_solve params에서 제외) | 사람 판단: 재료 값 |
| `action:LIBRARY_ENTRY` | `POST /library/entries`, `PATCH …/{eid}`, `POST …/{eid}/retire` | 사람 판단: 라이브러리 등록·폐기 |
| `action:CASE_EDIT` | `PATCH /cases/{id}`, `POST …/archive`, `POST /paths/inspect` | Case 수정·보관은 사람이 웹에서(확정). 경로 문자열 검사는 `list_case_inputs`가 대체 |
| `action:UPLOAD` | `/uploads*` 전부 | PC·브라우저 전용 |
| `action:JOB_RETRY` | `POST /jobs/{id}/retry` | 후속(run_job으로 대체) |

- 정적 시험 V-EM-7: `JOB_TYPES` ⊆ (JOB_KINDS.job_types ∪ 제외 키), 그리고 **모든 기존 비GET operation** ∈ (JOB_KINDS 생성 경로 ∪ `MCP_ACTIONS` 원본 operations ∪ 제외 operations ∪ 세션 전용 목록(client-tokens·api-tokens)). 새 쓰기 API를 만들면 셋 중 하나에 넣어야 통과.
- `MCP_ACTIONS`(`job_kinds.py`, 작업이 아닌 **허용된** 쓰기 — 공통 작업 계약 밖): 값 = `{tool, mcp_operation, origin_operations, risk, confirm, reason}`. 초기 1건: `action:CASE_CREATE` = `{tool:"create_case", mcp_operation:"POST /mcp/cases", origin_operations:["POST /cases"], risk:"run", confirm:"never"}`. 원본 `POST /cases`는 계속 토큰 직접 호출 불가(x-mcp 없음 — 허용 목록 밖), 토큰은 `/mcp/cases`로만.
- 사람 판단 단계를 나중에 MCP로 열려면 별도 계약(사용자 확정) 후 제외 목록에서 빼고 kind 또는 `MCP_ACTIONS`로 등록.

### 5.4 Case 생성(`list_case_inputs`·`create_case`, EM-16)

#### 5.4.1 "프로젝트 입력 데이터" 정의(코드 근거 §2 `Case 입력`·`업로드`·`서버 폴더` 행)

입력 출처는 아래 둘 중 **정확히 하나**. 도구는 경로 문자열을 받지 않고, 서버가 출처에서 rad·h3d·결과 폴더를 고른다.

| 출처 | 조건(모두 만족) | rad·h3d/결과 결정 |
|---|---|---|
| `upload_id` | `uploads` 행이 있고 **`project_id` = 요청 project_id**, 소유 규칙 = 기존 `_owned`(생성자 또는 전역 관리자 — 아니면 404 `UPLOAD_NOT_FOUND`, 다른 프로젝트도 같은 404로 존재 비노출), `state = COMPLETED` 그리고 `result.ok = true`(아니면 409 `INPUT_NOT_READY` + result.problems 요약) | 저장된 `result.rad_path`·`h3d_path`|`results_dir` 그대로(complete 때 `inspect_upload`가 고른 것). h3d·결과 둘 다 있으면 결과 폴더 우선(서버 추출 생략) — `input_kind`를 응답에 표시 |
| `folder {root, path}` | `root` = `fsbrowse.roots()` 인덱스 중 `kind ∈ {upload, input}`(`spdm`은 `check_input_path`가 `PATH_UNSAFE`로 거부하므로 후보에서 뺌), `path` = 루트 기준 상대경로(`/fs/browse`와 같은 해석·`lexical_check`). 폴더 자체와 고른 파일 각각에 `check_input_path`(루트 밖 422 `PATH_OUTSIDE_ROOT`, 심링크 성분·realpath 탈출·esl_root/SPDM 겹침 422 `PATH_UNSAFE`) + `check_principal_upload_area`(업로드 루트 아래 남의 폴더 403 `UPLOAD_FOLDER_FORBIDDEN`, `_backup` 422 `PATH_UNSAFE`). **업로드 루트 아래 폴더가 어떤 업로드의 `dir_path` 안이면 그 업로드도 위 `upload_id` 조건(프로젝트 일치·COMPLETED)을 만족해야 함**(아니면 404 `UPLOAD_NOT_FOUND`) | 폴더 바로 아래 또는 `rad/` 아래 `.rad`: `_0000.rad` 1개(없으면 단일 .rad) — `inspect_upload`와 같은 선택 규칙. h3d: 폴더 바로 아래(또는 1단계 하위) `.h3d` 1개. 결과: 1단계 하위에 `done.json` 있는 폴더 1개. 심링크·숨김 항목은 `fsbrowse`와 같이 무시. 2개 이상이면 422 `INPUT_AMBIGUOUS`(+후보 상대 이름 목록), 없으면 422 `PATH_NOT_FOUND` |

- 서버 폴더(업로드 루트 밖 `input_roots`)는 웹 `POST /cases`와 같이 **프로젝트 결속이 없다**(권한은 project power+만). 프로젝트 결속은 업로드에만 있다.
- 업로드 자체(`/uploads*`)·PC 경로·임의 절대경로는 계속 범위 밖(EM-7).

#### 5.4.2 API(`routers/mcp.py`, 세션·토큰 모두 허용)

| 메서드·경로 | operationId(= tool) | risk | 요청 | 응답 |
|---|---|---|---|---|
| `GET /mcp/case-inputs?project_id=&root=&path=&part_title=` | `list_case_inputs` | read | `project_id` 필수. `root`·`path` 없으면 업로드 후보 + 루트 목록, 있으면 그 폴더 평가 + 하위 폴더 이름(`fsbrowse.browse` 재사용, ≤ 200) | `McpCaseInputs` |
| `POST /mcp/cases` | `create_case` | run | `{project_id, title, folder_name(FOLDER_RE), part_title?, source:{upload_id} | {folder:{root, path}}}` | `201 McpCaseCreated` |

```jsonc
// McpCaseInputs
{"project_id":"…","roots":[{"index":0,"label":"업로드","kind":"upload"},{"index":1,"label":"drop_tests","kind":"input"}],
 "uploads":[{"upload_id":"…","name":"rear_f1","completed_at":"…","input_kind":"RESULTS"|"H3D","rad":"rad/model_0000.rad",
             "creatable":true,"part_check":{…},"problems":[]}],          // 그 프로젝트·본인(관리자는 전체) COMPLETED, 최신 20건
 "folder":{"root":1,"path":"rear/f1","rad":"model_0000.rad","h3d":"model.h3d","results":null,"input_kind":"H3D",
           "creatable":true,"part_check":{…},"problems":[],"subfolders":["f2","f3"]}|null,
 "default_part_title":"chassis rear","part_title_match":"exact_ci"}
// part_check — system.inspect_rad 결과 요약(값은 표시 이름·상대 이름만, 절대경로 없음)
{"part_title":"chassis rear","target_part":{"id":2000001,"title":"CHASSIS_REAR"}|null,
 "parts":[{"id":…,"title":"…"}](≤ 50, total_parts),"result":"ok"|"PART_NOT_FOUND"|"PART_AMBIGUOUS"|"PART_MISMATCH",
 "includes":{"count":3,"ok":3,"missing":0,"outside":0}}
// McpCaseCreated
{"case":{"id":"…","project_id":"…","title":"…","folder_name":"…","input_kind":"H3D","part_title":"…","part_id":2000001,"status":"ACTIVE"},
 "part_check":{…},"source":{"upload_id":"…"}|{"folder":{"root":1,"path":"rear/f1"}},
 "next":"plan_job(kind=case_extract, case_id=…)"}
```

- 생성 = 해석한 경로로 `CaseCreate`를 만들어 기존 `services/cases.create_case` 호출(검사·fingerprint·case.json·중복 처리 복제 금지). 파트 불일치는 **기존 동작 그대로 422 `PART_NOT_FOUND`·`PART_AMBIGUOUS`·`PART_MISMATCH`, Case 미생성**(응답 problem에 `part_check` 동봉). h3d 입력 + hw 미설정 503 `H3D_EXTRACT_UNAVAILABLE`, 중복 409 그대로.
- `confirm: never`(가벼운 쓰기 — 폴더·DB 행 1개, 무거운 작업은 뒤따르는 `case_extract` plan/confirm이 통제). `list_case_inputs`의 `creatable`·`part_check`가 plan 역할.
- 권한: 기존 `require_execute`(project power+) + 토큰 범위 run+. `list_case_inputs`는 read 토큰도 가능하나 업로드 소유·폴더 격리 규칙은 같다.
- 감사: `create_case`는 토큰·세션 모두 `api_audit` 1행(`target_type:"case"`, project_id, case_id, `params_sha256`; title·경로·upload_id 값 미저장 — §6.1). 거부도 기록.
- 호출 제한: 공통 `requests_per_min` + `case_creates_per_min`(5, 토큰별) → 429 `RATE_LIMITED`.
- 응답·로그에 절대경로 금지(루트 인덱스·상대 이름만). `list_case_inputs`는 존재 확인 통로가 되지 않게 루트 밖·남의 폴더에 대해 `/fs/browse`와 같은 오류만 준다.

## 6. 감사 로그

### 6.1 기록 대상·위치

- **`api_audit`**(새 테이블, 미들웨어가 응답 후 별도 트랜잭션 — 실패 요청도 남음): 토큰 요청의 모든 비GET, 모든 거부(401·403·428·429), `plan_job`·`run_job`·`create_case`(세션 포함), 토큰 발급·폐기. 토큰 GET은 `mcp.audit.record_reads`(false)일 때만.
- 열: `id, occurred_at, user_id, username, api_token_id, token_prefix, operation_id, tool, method, route(템플릿), target_type, target_id, project_id, case_id, kind, job_id, plan_id, status_code, result_code, duration_ms, request_id, client_ip, params_sha256`.
- `client_ip`는 기존 규칙(proxy_headers=False, XFF는 `client_token.trusted_proxies`일 때만 — `client_tokens.request_source` 재사용).
- **본문 저장 금지**: 요청·응답 본문, 파라미터 값, 쿼리 값, 토큰·confirm_token 원문, 파일 경로를 저장하지 않는다. 본문은 `params_sha256`만. 정적 시험이 insert 인자 목록을 고정.
- `jobs.api_token_id`가 작업 단위 추적을 맡는다(이력 화면 `HistoryItem`에 `via_token` 추가는 후속 — 이번엔 API 응답 `McpJobStatus.via_token`만).

### 6.2 조회·보존

| 메서드·경로 | tool | 권한 | 응답 |
|---|---|---|---|
| `GET /mcp/audit?user_id=&token_id=&operation_id=&status=&since=&until=&limit≤200&cursor=` | `list_audit` | admin(세션 전역 관리자 또는 admin 토큰) | `{items, next_cursor}` 최신순 |

- 보존 `mcp.audit.retention_days`(180, 30~3650). 워커 `runtime.py`에 `maintenance_once()`(10분 간격, `reap_once` 옆)로 초과 행·만료 1일 지난 `mcp_plans` 삭제. 사용자 산출물 삭제 금지 규칙과 별개(플랫폼 내부 기록).

## 7. 요약형 조회 API(레지스트리)

- `SUMMARIES`(`esl_platform/api/mcp/summaries.py`): `{entity: (load_fn, summary_fn, id_label)}`. summary_fn은 **기존 서비스 함수**만 호출(SQL·npz·CSV 파서 복제 금지).
- `GET /mcp/summary/{entity}/{id}?top_n=` → tool `get_summary`(read). 모르는 entity 404 `SUMMARY_ENTITY_UNKNOWN`.
- `GET /mcp/system` → tool `system_status`(`system.status` + `system.queue`: 슬롯 수·실행 중·대기 앞 5·워커 온라인·설정 ok·코어 버전·features).
- 공통 봉투 `McpSummary` = physicsai `Summary`와 같은 키: `{entity, id, title, state, as_of, facts(스칼라 ≤ 30키), tables[{name, columns, rows, total_rows, stats}], links[{entity, id, rel}], truncated, bytes}`.

| entity | 재사용 서비스 | 내용(요지) |
|---|---|---|
| `case` | `cases.get_case`·`stage_status`, `history.list_history(case_id, limit 5)` | 제목·폴더·input_kind·part_title·단계별 상태(①~⑦: 없음/실행/완료/stale/실패)·현재 t*·현재 지지점 세트·현재 ESL run·최신 검증 verdict·최근 작업 5 |
| `extract` | `history.review`(CASE_EXTRACT `registered.extract/tstar`) | n_nodes·n_elems·n_frames·t_end·재료 표·t* 후보 상위 N(frame·time·값)·확정 t* |
| `esl_run` | `results.get_esl_run`·`results.forces(top)` | frame·metric·지지점 수·kabsch 잔차·합력 노름[N]·하중 상위 N 노드 표(Fx·Fy·Fz[N])·stale 사유 |
| `validation` | `results.get_validation` | verdict·criteria·disp_rms_rel·reaction_rel·hotspot 최대 오차·hotspot 상위 N |
| `export` | `history.review`(EXPORT) | targets·id_range·파일 이름·크기·validation_verdict(경로 없음) |
| `report` | `history.review`(CASE_REPORT) | verdict·bytes·보존 여부 |
| `analysis` | `library.get_analysis` | 필터·항목 수·대표/최악 케이스·덱 생성 여부 |
| `comparison` | `comparisons.get_comparison` | 모델·두 버전·cos 수렴 판정·셀별 상위 N |
| `library_entry` | `library.get_entry` | 모델·버전·씬·verdict·상태 |
| `job` | `history.review` | McpJobStatus + timing·error(failed_step)·result{availability, state, stale_reasons, diff} |

- 크기 `mcp.summary.max_bytes`(8192) 초과 시 표 행 축소 + `truncated:true`. `top_n` 기본 10, 최대 50. 절대경로 금지(표시 이름·id만). 수치 열은 `[단위]` 접미(N·mm·s, 변형률은 무차원 표시 없음). `job_steps.command`는 넣지 않는다.

## 8. openapi 보강·`x-mcp`

- 라우트 `openapi_extra={"x-mcp": {...}}`. 도구: `{"tool", "risk":"read|run|admin", "confirm":"never|by_kind|always", "version":1, "summary_ko", "deprecated":false}`. 제외: `{"exclude":"사유"}`.
- 도구 operation 필수(V-EM-6): `summary`, 한국어 `description`(언제 쓰는지·부작용), 모든 요청 필드·쿼리 `description`, 수치에 단위(`x-unit` 또는 설명 `[mm]`)·`minimum`/`maximum` 또는 enum, 요청 `examples` ≥1, 응답 모델, 오류 code 목록.
- operationId: 기존 불변. 새 `/mcp/*`는 `operation_id=<tool>`. 도구 이름 단일 출처 = `x-mcp.tool`.
- 동결 목록: 5632262의 기존 69개 operation을 `esl_platform/api/mcp/route_policy.py` `LEGACY_UNMARKED`로. 새 operation은 `x-mcp` 없으면 실패, 동결 목록은 줄기만(없는 id 있으면 실패).
- 기존 operation 중 도구로 표시: `GET /me` → `whoami`, `GET /projects` → `list_projects`, `GET /cases` → `list_cases`. 기존 비GET은 토큰 불가(허용 목록 밖).
- 출력 경로: openapi는 그대로 `docs/contracts/openapi_p1b.json`(`dump_openapi.py`). 생성기는 `dump_openapi.render()`를 import해 같은 앱 구성을 쓴다.

## 9. 도구 스펙 생성기

- `scripts/gen_tool_specs.py [--check] [--out DIR]` → `backend/esl_platform/api/mcp/generated/`
  - `tools.mcp.json` — `{schema_version:1, generated_from:"openapi <version>", tools:[{name, description, inputSchema, annotations:{readOnlyHint, destructiveHint, x-risk, x-confirm, x-version}, x-http:{method, path, operationId}}]}`
  - `tools.openai.json` — `[{type:"function", function:{name, description, parameters, strict:false}}]`. 경로·쿼리·본문 평탄화(충돌 시 생성 실패), 최상위 oneOf/anyOf 금지, `params`는 `{"type":"object"}` + "describe_job_kind로 스키마 확인".
  - `glossary.json` — §10.
- 결정적(키 정렬·`ensure_ascii=False`·indent 2·끝 줄바꿈·시각/경로 없음). `--check`는 디스크와 다르면 실패 + **호환 검사**(직전 커밋 `tools.mcp.json` 대비 같은 이름 도구의 인자 제거·이름/타입 변경·새 필수 인자 → 실패, `_v2` + 옛 도구 `deprecated:true` 1 릴리스 유지). kind params도 같은 규칙.
- 서빙 `GET /mcp/tools?format=mcp|openai`(x-mcp exclude "MCP 서버 부팅용", 세션·토큰 read 허용). 패키지 데이터로 포함(`pyproject.toml` package-data).

### 9.1 도구 후보(18개 — physicsai와 같은 이름 13개 + esl 고유 5개)

| tool | risk | 경로 | physicsai 대응 |
|---|---|---|---|
| `whoami` | read | `GET /me` | 같음 |
| `system_status` | read | `GET /mcp/system` | 같음 |
| `list_projects` | read | `GET /projects` | **esl 고유** |
| `list_cases` | read | `GET /cases` | `list_studies` 대응 |
| `list_case_inputs` | read | `GET /mcp/case-inputs` | **esl 고유**(§5.4) |
| `create_case` | run | `POST /mcp/cases` | **esl 고유**(§5.4, confirm never) |
| `get_summary` | read | `GET /mcp/summary/{entity}/{id}` | 같음 |
| `get_glossary` | read | `GET /mcp/glossary` | 같음 |
| `list_job_kinds` | read | `GET /mcp/job-kinds` | 같음 |
| `describe_job_kind` | read | `GET /mcp/job-kinds/{kind}` | 같음 |
| `plan_job` | read | `POST /mcp/jobs/plan` | 같음 |
| `run_job` | run | `POST /mcp/jobs` | 같음 |
| `list_jobs` | read | `GET /mcp/jobs` | 같음(이력 서비스 재사용) |
| `job_status` | read | `GET /mcp/jobs/{id}` | 같음 |
| `job_summary` | read | `GET /mcp/jobs/{id}/summary` | 같음 |
| `job_log` | read | `GET /mcp/jobs/{id}/log` | **esl 고유**(실패 원인 확인) |
| `cancel_job` | run | `POST /mcp/jobs/{id}/cancel` | 같음 |
| `list_audit` | admin | `GET /mcp/audit` | 같음 |

`check_prediction_input`·`find_similar_designs`(physicsai)는 esl에 없음.

## 10. 도메인 용어집(경량 온톨로지)

- `GET /mcp/glossary?section=` → `get_glossary`(read). 생성 `glossary.json` + 사람 파일 병합(≤ 64 KiB, section 부분 조회).
- **자동 추출**(생성기, 손 유지보수 없음):
  - `job_types`(JOB_TYPES: stage·lane·steps[key·kind·h3d_only]), `job_kinds`, `entities`(SUMMARIES 키 + 관계), `stages`(UI 1~9 번호·이름: ① 추출 ② t* ③ BC ④ ESL ⑤ 검증 ⑥ 내보내기 ⑦ Case 보고서 ⑧ 라이브러리 분석 ⑨ 버전 비교 — 번호 원천은 JOB_TYPES.stage, 이름은 사람 파일).
  - `enums`: openapi 스키마 enum(작업 상태·레인·EXPORT_TARGETS·범위 등) + 코어 설정 enum(`esl/config.py`의 `_enum(...)` 호출을 **AST로** 읽음: `part_title_match`, t* metric 등 — 플랫폼 시험에서 코어 import는 허용되나 생성기는 AST로 결정성 유지).
  - `error_codes`: backend·worker·esl 코어 소스 AST에서 `DomainError("CODE", …)`·`conflict/unprocessable("CODE", …)`·`not_found("CODE", …)`·`forbidden(…, code="CODE")`·`EslError("CODE", …)`·`CoreError/H3dError/RegisterError("CODE", …)` 문자열 리터럴 → `{code, status, message_ko(첫 출처), sources}`(파일 경로순). `PART_NOT_FOUND`·`PART_AMBIGUOUS`·`PART_MISMATCH` 포함.
- **사람 파일** `backend/esl_platform/api/mcp/glossary_terms.yaml`(키는 자동 키 참조만):

```yaml
schema_version: 1
terms:
  - key: entity:esl_run
    ko: 등가정적하중(ESL) 결과
    synonyms: [ESL, 등가하중, 등가정적하중, F_eq]
  - key: step:TSTAR_SCAN
    ko: 최대 변형 시점(t*) 탐색
    synonyms: [t*, 티스타, 최대변형 시점]
  - key: enum:part_title_match:exact_ci
    ko: 파트 이름 느슨한 일치(공백·_·- 연속 = 한 칸, 대소문자 무시)
  - key: stage:3
    ko: BC 지지점(3-2-1 정정 구속)
  - key: unmapped:hotspot
    ko: 검증 비교 대상 고변형 요소
error_hints:
  PART_NOT_FOUND: 대상 파트 title이 rad에 없습니다. 생성 전이면 list_case_inputs의 part_check.parts에서 title을 골라 create_case에 part_title로 다시 주세요. 이미 만든 Case는 ESL 웹 ① 화면에서 고쳐야 합니다(MCP로 Case 수정 불가)
  PART_AMBIGUOUS: 정규화 후 같은 title 파트가 2개 이상입니다. part_check.parts의 정확한 title을 주거나 웹에서 고르세요
  INPUT_NOT_READY: 업로드가 완료·검사 통과 상태가 아닙니다. 웹·PC 도구에서 업로드를 마치세요(MCP로 업로드 불가)
  INPUT_AMBIGUOUS: 폴더에 rad·h3d·결과 폴더 후보가 여러 개입니다. 하나만 있는 하위 폴더를 고르세요
  PREREQUISITE_MISSING: missing 항목(extract·tstar·support_set…)을 확인하세요. tstar·support_set은 사람이 웹에서 확정합니다
  CONFIRM_REQUIRED: plan_job을 먼저 호출해 confirm_token을 받으세요
```

- 정적 시험 V-EM-10: 사람 키 ⊂ 자동 키, 자동 `job_kinds`·`entities`·`stages`·`steps` 전부 사람 `ko` 있음, `error_hints` 키 ⊂ `error_codes`.

## 11. 호출 제한(physicsai와 같은 값)

| 설정 | 기본 | 초과 |
|---|---|---|
| `mcp.rate_limit.requests_per_min` | 60(토큰별, 고정 창) | 429 `RATE_LIMITED` + `Retry-After` |
| `mcp.rate_limit.plans_per_min` | 10 | 429 `RATE_LIMITED` |
| `mcp.rate_limit.max_active_jobs_per_token` | 3(`jobs.api_token_id` 비종료 수) | 429 `TOKEN_ACTIVE_JOB_LIMIT`(+active_job_ids) |
| `mcp.rate_limit.case_creates_per_min` | 5(토큰별 `create_case`, esl 고유) | 429 `RATE_LIMITED` |

- 세션 무제한(기존 불변). 기존 제약(`worker.slots`·`CASE_JOB_BUSY`·분석/비교 1개)이 먼저.
- 카운터는 API 프로세스 메모리(단일 uvicorn). 워커 프로세스와 무관.

## 12. 설정·배포

```yaml
mcp:
  enabled: false                 # false면 esl_at_ 인증·/mcp/*·/me/api-tokens*·토큰 화면 모두 꺼짐(404 MCP_DISABLED)
  require_confirm_for_token: true
  confirm_ttl_s: 600             # 60~3600
  allowed_job_kinds: null
  denied_job_kinds: []           # 확정(EM-17): 기본 전부 허용, heavy는 confirm_token
  token: {default_expiry_days: 30, max_expiry_days: 90, max_per_user: 5, snapshot_max_age_days: 30, last_used_update_s: 60}   # snapshot 1~90
  rate_limit: {requests_per_min: 60, plans_per_min: 10, max_active_jobs_per_token: 3, case_creates_per_min: 5}
  audit: {retention_days: 180, record_reads: false}
  summary: {max_bytes: 8192, top_n_default: 10, top_n_max: 50}
```

- `core/config.py`에 `McpCfg`(기본값 = 위) + `Settings.mcp: McpCfg = McpCfg()`. `config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml`에 블록 **추가만**(주석), `deploy/setup_config.py` 불변(키 없으면 기본값).
- `/status`에 `features: {mcp: bool}` 추가(`StatusOut`·프런트 타입 동시 수정).
- 라우트는 설정과 무관하게 등록(openapi 결정성), 꺼져 있으면 핸들러 404 `MCP_DISABLED`.

## 13. DB — migration `0008_mcp_ready`(HEAD 0007 다음)

| 테이블·열 | 내용 |
|---|---|
| `api_tokens` | `id, user_id, username, display_name, name, scope, token_prefix, token_hash(UNIQUE), principal_snapshot JSONB{is_global_admin, roles}, snapshot_at, created_at, expires_at, last_used_at, last_used_ip, revoked_at, revoked_by`; CHECK scope ∈ (read,run,admin)·expires>created; 인덱스 (user_id, revoked_at), UNIQUE(user_id, name) WHERE revoked_at IS NULL |
| `mcp_plans` | `id, api_token_id, user_id, kind, kind_version, case_id, project_id, params_sha256, confirm_hash(UNIQUE), summary JSONB(수치만), created_at, expires_at, used_at, used_job_id` |
| `api_audit` | §6.1 열, 인덱스 (occurred_at), (api_token_id, occurred_at), (user_id, occurred_at) |
| `jobs.api_token_id` | nullable 추가(FK 없음), 부분 인덱스 (api_token_id) WHERE api_token_id IS NOT NULL AND state 비종료 |

- 기존 관례: 0001이 `tables.metadata`를 create_all하므로 새 테이블은 `tables.py`에 정의 + migration은 `checkfirst`/`IF NOT EXISTS`(멱등). downgrade는 0006·0007처럼 **미지원**(RuntimeError).

## 14. (예약)

physicsai 계약 §12(검색)에 대응하는 항목은 esl에 없음 — 유사 Case 검색은 라이브러리 특징(셀 합력) 기반으로 별도 계약.

## 15. 확장 규칙(기능 추가 시 할 일과 시험)

| 새로 추가하는 것 | 개발자가 할 일(한 줄 등록) | 자동으로 따라오는 것 | 빠지면 실패하는 시험 |
|---|---|---|---|
| 조회 API(GET) | `x-mcp`(tool + 필수 설명·단위·예시) 또는 `exclude` 사유 | 도구 스펙·OpenAI 함수·토큰 허용 판정·용어집 enum | V-EM-6 |
| 쓰기 API(비GET, 작업 아님) | `x-mcp exclude` + `MCP_JOB_EXCLUDED`에 `action:<이름>` 사유(사람 판단이면 그렇게 표기). MCP로 열기로 사용자가 확정한 쓰기는 `/mcp/*` 래퍼 + `MCP_ACTIONS` 한 줄(create_case 선례) | 토큰 요청 403 / 래퍼 도구·감사·제한 | V-EM-6, V-EM-7 |
| 새 Case 입력 형태(예: 새 업로드 레이아웃) | `inspect_upload`·폴더 선택 규칙 한 곳(§5.4.1)만 수정 — `list_case_inputs`·`create_case`가 같은 해석 함수 사용 | 두 도구 | V-EM-15 |
| 새 작업(job_type) | `JOB_KINDS` 한 줄(params_model은 웹 params 부분 집합, plan_fn·create_fn은 기존 서비스 호출, summary_entity) 또는 `MCP_JOB_EXCLUDED`+사유. heavy 판단 = SLOT 레인이면 heavy | `plan_job`·`run_job`·`job_status`·`job_summary`·`job_log`·`cancel_job`, confirm·감사·제한 | V-EM-7 |
| 새 결과 엔티티 | `SUMMARIES` 한 줄(기존 조회 서비스 호출) + 사람 용어 `ko` | `get_summary`, 용어집 entities, `McpJobStatus.entity` | V-EM-8, V-EM-10 |
| 새 오류 코드 | 없음(AST 자동 추출). LLM이 다음 행동을 알아야 하면 `error_hints` 한 줄 | `get_glossary` error_codes | V-EM-10(힌트 키가 실제 코드에 없으면 실패) |
| 새 step·UI 단계·enum | 사람 용어 `ko` 한 줄 | 용어집 | V-EM-10 |
| 새 설정 enum(코어) | 없음 | 용어집 enums | – |
| 깨지는 API·params 변경 | 새 도구 이름 `_v2`·새 kind 이름(또는 `kind_version`+1과 새 이름), 옛 것 deprecated 1 릴리스 | 생성 스펙 | V-EM-9 |
| 사람 판단 단계를 MCP로 개방 | 별도 계약·사용자 확정 → 제외 목록에서 삭제 + kind 등록 | 위 작업 행과 같음 | V-EM-7 |

MCP 서버(후속)는 `GET /mcp/tools`를 읽어 도구를 동적 노출하므로, 위 표만 지키면 서버 코드는 바뀌지 않는다. 두 플랫폼 MCP 서버는 같은 코드에 base URL·토큰만 다르게 쓰는 것을 목표로 한다.

## 16. 단계·파일 소유(병렬 가능하게 — 공유 파일은 한 단계만 소유)

| 단계 | 내용 | 소유 파일 | 선행 |
|---|---|---|---|
| M1 | 설정 `McpCfg`·migration 0008·`tables.py` 추가·`core/tokens.py`(client_tokens import 전환)·`esl_at_` 인증 경로·스냅숏 갱신·토큰 API·`api_audit` 미들웨어·호출 제한·`route_policy.py`(동결 목록·허용 표)·워커 `maintenance_once`·`/status` features | Impl-Backend A: `core/{config.py, tokens.py, auth.py(스냅숏 훅), db/tables.py, repositories/{api_tokens,api_audit,mcp_plans}.py}`, `api/{deps.py, main.py, mcp/route_policy.py, mcp/audit_mw.py, mcp/ratelimit.py, routers/api_tokens.py, services/api_tokens.py, services/client_tokens.py(import만), services/system.py(features)}`, `core/repositories/jobs.py`(api_token_id), `migrations/versions/0008_mcp_ready.py`, `worker/esl_worker/runtime.py`, config 예시 2개 | – |
| M2 | `JOB_KINDS`·`MCP_JOB_EXCLUDED`·`MCP_ACTIONS`·`/mcp/jobs*`·plan_fn 7종·`/mcp/case-inputs`·`/mcp/cases`(§5.4)·`SUMMARIES`·`/mcp/summary`·`/mcp/system`·`/mcp/audit` | Impl-Backend B: `api/mcp/{job_kinds.py, summaries.py, plan.py, case_inputs.py}`, `api/routers/mcp.py`, `api/schemas_mcp.py`(`Mcp*` 스키마). `services/cases.py`·`uploads.py`·`fsbrowse.py`·`core/paths.py`·`core/uploads.py`는 **import만**(수정 금지 — 필요한 공개 함수가 없으면 Plan에 반환) | M1의 `Principal.api_token_id`·repositories 인터페이스(계약 §4.2·§13로 고정 — 병행 가능, 통합은 M1 후) |
| M3 | `x-mcp` 표시·설명 보강(기존 3개 + 새 라우트 + 제외 사유 전부), `scripts/gen_tool_specs.py`·generated·`/mcp/tools`·`/mcp/glossary`·`glossary_terms.yaml`, test-all 연결, `openapi_p1b.json` 갱신 | Impl-Backend C: `scripts/gen_tool_specs.py`, `api/mcp/{generated/*, glossary.py, glossary_terms.yaml}`, `api/routers/{system.py, cases.py, library.py, jobs.py, history.py, results.py, uploads.py, client_tokens.py}`(openapi_extra만), `scripts/test-all`, `pyproject.toml`(package-data), `docs/contracts/openapi_p1b.json` | 생성기·용어집은 M1·M2와 병행, 최종 `--check`는 M2 후 |
| M4 | "내 API 토큰" 화면, `types.ts`(`ApiToken*`·`StatusOut.features`), `check-api.mjs`의 `^Mcp` 제외 + 그 시험, `frontend-dist` | Impl-Frontend: `frontend/src/account/apiTokens/*`, `frontend/src/api/types.ts`, `frontend/scripts/check-api.mjs`·`check-api.test.mjs` | M1 API 모양(§4.4 고정 — 가짜 응답으로 병행) |

시험 파일: M1 `backend/tests/test_mcp_tokens.py`·`test_mcp_audit.py`, M2 `test_mcp_jobs.py`·`test_mcp_summary.py`·`test_mcp_cases.py`, M3 `test_mcp_static.py`·`tests`(생성기), M4 vitest. CHANGELOG·VERSION(0.6.0)은 통합 시 한 번.

## 17. physicsai와 다른 점(나머지는 동일)

| 항목 | physicsai | esl |
|---|---|---|
| 토큰·확인 접두 | `pai_<id8>_<secret>`, `pcf_` | `esl_at_<id8>_<secret>`, `esl_cf_`(기존 `esl_ct_`와 같은 계열) |
| API 접두·CSRF 헤더 | `/physicsai/api`, `X-PhysicsAI-Request` | `/esl/api`, `X-ESL-Request` |
| 작업 대상 키 | `study_id` | `case_id`(Case 종류) 또는 `project_id`(라이브러리 종류), kind의 `target`이 결정 |
| 기존 기계 토큰 | 없음 | `esl_ct_` PC 연결 토큰 공존(별도 테이블 유지, MCP 불가) |
| 역할 스냅숏 | 예외 신설 | 선례 있음(`client_tokens.role`) — 전 프로젝트로 확장 |
| 기존 감사 | `audit_events` 있음 + `detail.api_token_id` | 없음 → `api_audit`만 신설, 토큰 발급·폐기·세션 `/mcp/jobs*` 쓰기도 여기에 |
| 작업 취소 | 기존 = 전역 관리자 → 토큰 자기 작업 **예외** | 기존 = 생성자·전역 관리자 → 토큰은 자기 토큰 작업으로 **좁힘** |
| 권한 거부 코드 | `PERMISSION_DENIED` | `FORBIDDEN`(기존 그대로) |
| 초기 kind | doe_generate·solve_pbs·predict·predict_batch·surrogate_opt(_verify)·equiv_check·fem_verify·geom_preview | case_extract·esl_solve·validate·export·case_report·lib_analyze·lib_compare(job_type 전부) |
| 제외 목록 | job_type 위주 | job_type 없음 + `action:*`(사람 판단 쓰기·Case 수정/보관·업로드) |
| 허용된 비작업 쓰기 | 없음 | `MCP_ACTIONS`: `create_case`(`POST /mcp/cases`, run, confirm never) |
| 도구 | `list_studies`·`check_prediction_input`·`find_similar_designs`(Q2) | `list_projects`·`list_cases`·`list_case_inputs`·`create_case`·`job_log` |
| 호출 제한 | 공통 3종 | 공통 3종 + `case_creates_per_min` |
| 요약 엔티티 | study·param_set·train_doe·predict_*·surrogate_opt·equiv_check·fem_verify·geom_preview·job | case·extract·esl_run·validation·export·report·analysis·comparison·library_entry·job(이력 review 재사용) |
| 용어집 자동 원천 | paicad TYPE_ABBR(AST) | 코어 `esl/config.py` enum·`EslError` 코드(AST), JOB_TYPES step |
| 동시 실행 | 전역 슬롯 1·HPC | `worker.slots`(2)·Case별 직렬, HPC 없음 |
| openapi 출력·프런트 검사 | `backend/openapi.json`, 프런트가 operationId 일부 고정 | `docs/contracts/openapi_p1b.json`, 프런트는 스키마 대조 → `Mcp*` 제외 규칙 |
| migration | 0019 예상, downgrade 데이터 있으면 거부 | 0008, downgrade 미지원(기존 관례) |
| 입력·Case 생성 | 해당 없음(대응 도구 없음) | Case 생성 허용 — 서버에 이미 있는 입력만(완료된 업로드·허용 루트 폴더, §5.4). 업로드·Case 수정은 비범위 |

## 18. Verifier 체크(V-EM-*)

| ID | 검사 | 완료 기준 |
|---|---|---|
| V-EM-1 | 기본값 불변 | `mcp` 키 없는 설정으로 기존 전체 시험 통과, `esl_at_` Bearer → 401 + 가짜 대시보드 호출 0회, `/mcp/*`(`/mcp/cases`·`/mcp/case-inputs` 포함)·`/me/api-tokens*` 404 `MCP_DISABLED`, 웹 `POST /cases` 응답 불변, 세션·`esl_ct_` 응답·CSRF 동일, `openapi_p1b.json`의 기존 operation 바이트 동일(새 operation·스키마만 추가) |
| V-EM-2 | 토큰 수명 | 발급 응답만 평문, 목록에 평문·해시 없음, DB 문자열 검색에 평문 없음, 폐기·만료·stale(시계 주입: `snapshot_at`+30일 이내 통과·초과 401 `API_TOKEN_STALE`, 설정 키 없을 때 기본 30)·형식 오류 각 401 코드, 상한 409, 세션 전용 API에 토큰 403 `SESSION_REQUIRED` |
| V-EM-3 | 범위·허용 목록·토큰 분리 | read 토큰 `run_job` 403 `API_TOKEN_SCOPE`, 비 x-mcp operation 403, `esl_ct_` 토큰으로 `/mcp/*` 403 `CLIENT_TOKEN_SCOPE`, `esl_at_`로 `/uploads` 403, 스냅숏 갱신(웹 로그인 후 power 제거 → run 403), 관리자 해제 시 admin 토큰 자동 폐기, `client_tokens` 기존 시험 전부 통과 |
| V-EM-4 | confirm | heavy+토큰: 없음 428, 다른 params 409 mismatch, 만료(시계 주입)·재사용 409, 정상 201 + `used_job_id`; light·세션 confirm 없이 201; problems 있으면 token null; 웹 `POST /cases/{id}/jobs` 결과 불변 |
| V-EM-5 | 감사 | 토큰 비GET·거부·plan·run·발급·폐기 각 1행, 실패 요청 기록, 본문·값·경로·토큰 원문 없음(insert 인자 고정 + DB 문자열 검색), 보존 초과 정리, `list_audit` admin만 |
| V-EM-6 | x-mcp 정적 | 모든 operation이 x-mcp 또는 `LEGACY_UNMARKED`, 동결 목록에 없는 id 없음, 도구 필수 항목 누락 0, 도구 이름 유일 |
| V-EM-7 | 작업 종류·제외 | JOB_TYPES ⊆ JOB_KINDS ∪ 제외, 모든 기존 비GET ∈ 생성 경로 ∪ `MCP_ACTIONS` 원본 ∪ 제외 operations ∪ 세션 전용(`POST /cases`는 `MCP_ACTIONS`, `PATCH /cases/{id}`·archive·paths/inspect는 제외에 있음), `denied_job_kinds` 기본 `[]`(설정 키 없을 때 7종 모두 plan 가능), 각 kind plan_fn·create_fn·summary_entity·params 설명·단위, plan_fn이 쓰기 0회(트랜잭션 rollback·행 수 불변), create_fn이 기존 서비스 호출(가짜 주입), esl_solve params에 material_override 없음 |
| V-EM-8 | 요약 | 모든 엔티티 봉투 모양·`max_bytes` 이하(대형 픽스처로 truncated)·절대경로·command 없음, summary_entity ⊆ SUMMARIES, `case` 단계 상태가 `stage_status`와 같음 |
| V-EM-9 | 생성기 | 두 번 실행 바이트 동일, `--check` 최신, OpenAI 출력 최상위 oneOf/anyOf 없음·인자 충돌 없음, 호환 검사(필수 인자 추가·제거·타입 변경 실패, 새 이름 통과) |
| V-EM-10 | 용어집 | 자동 키가 코드와 일치(JOB_TYPES·steps·JOB_KINDS·SUMMARIES·error_codes에 PART_* 포함·코어 enum), 사람 키 ⊂ 자동 키, 필수 `ko` 누락 0, error_hints 키 ⊂ error_codes |
| V-EM-11 | 호출 제한 | 분당 61번째 429 + Retry-After, plan 11번째 429, 동시 작업 4번째 429, 세션 무제한 |
| V-EM-12 | 토큰 취소 | 같은 토큰 작업만 `cancel_job` 성공, 같은 사용자의 웹 작업·다른 토큰 작업 403, 기존 `POST /jobs/{id}/cancel` 권한 불변 |
| V-EM-13 | 화면·프런트 검사 | features.mcp false면 메뉴 숨김, 평문 1회·저장 코드 없음(정적), 폐기 확인, `check:api` 통과(`Mcp*` 제외, `ApiToken*`·`StatusOut` 대조) |
| V-EM-15 | Case 생성 | (a) 그 프로젝트·본인 COMPLETED+ok 업로드로 `create_case` 201 → 웹 `POST /cases`로 같은 입력을 만든 행과 rad_path·results_dir|h3d_path·input_kind·fingerprint·part_id 동일(기존 서비스 호출 확인), 응답 `part_check` 포함; (b) **다른 프로젝트 업로드** 404 `UPLOAD_NOT_FOUND`, 남의 업로드 404, OPEN/CANCELED/STALE·ok=false 409 `INPUT_NOT_READY`; (c) 폴더: 루트 인덱스 범위 밖·spdm 루트 422, `../` 탈출 422 `PATH_OUTSIDE_ROOT`|`PATH_UNSAFE`, **루트 아래 심링크 성분·심링크 파일 422 `PATH_UNSAFE`**, 업로드 루트 아래 남의 폴더 403 `UPLOAD_FOLDER_FORBIDDEN`, `_backup` 422, 다른 프로젝트 업로드의 dir_path 안 폴더 404; rad 2개 422 `INPUT_AMBIGUOUS`; (d) 파트 불일치 422(`PART_*`, Case·폴더 미생성 — DB 행 수·esl_root 불변); (e) read 토큰 `create_case` 403 `API_TOKEN_SCOPE`, general 역할 403, 토큰으로 원본 `POST /cases` 403 `API_TOKEN_OPERATION_NOT_ALLOWED`; (f) 감사 1행·경로/title/upload_id 값 없음, 분당 6번째 429; (g) 응답·`list_case_inputs`에 절대경로 없음(문자열 검사) |
| V-EM-14 | 형제 일치 | 공통 도구 13개 이름·`McpJobPlan`/`McpJobStatus`/`McpSummary` 키·MCP 오류 코드가 physicsai 계약 표와 같음(대상 키 차이만 허용 — 시험 상수 표로 고정) |

## 19. 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| 토큰 유출 | 소유자 권한으로 작업 생성 | 해시·1회 표시·만료 ≤ 90일·허용 목록·제한·감사·즉시 폐기, `esl_at_` 접두로 비밀 검사 도구 탐지·로그 마스킹 |
| 사내 LLM 오조작(반복 추출·풀이) | SLOT 점유(slots 2), HyperView 라이선스 사용 | heavy confirm(요청 해시 결합)·동시 작업 3·`CASE_JOB_BUSY`·`denied_job_kinds`·자기 작업 취소·plan에 대기열·예상 시간 |
| 사용자 판단 우회 | 잘못된 t*·지지점으로 ESL | 판단 쓰기 전부 제외(EM-7), esl_solve는 저장된 t*·세트만, 없으면 plan problems로 "웹에서 확정" 안내 |
| PC 토큰 회귀 | PC 도구 업로드 중단 | `client_tokens` 테이블·범위 불변, 공용 모듈은 함수 이동만, 기존 시험 유지(V-EM-3) |
| 역할 스냅숏 지연 | 권한 회수(계정 정지 포함) 최대 30일 지연 | 스냅숏 방식 확정(EM-C1) — 웹 접속 즉시 갱신·전역 관리자 즉시 폐기·admin 자동 폐기, 필요 시 운영자가 `snapshot_max_age_days`를 줄임(1~90), physicsai와 같은 값 |
| LLM의 Case 남발·잘못된 입력 선택 | Case·산출물 폴더 증가, 잘못된 파트로 추출 | 입력은 서버에 있는 것만(§5.4.1)·파트 불일치 422 미생성·`case_creates_per_min`·감사, 추출은 별도 heavy confirm, 정리는 웹 보관 |
| plan 추정 부정확(이력 적음) | 판단 오류 | `estimate_basis:"none"` 명시, 요소 수·frame·대기열 정보 우선 |
| 요약이 화면과 어긋남 | 다른 숫자 | 이력·결과 서비스 호출만(V-EM-8) |
| 두 플랫폼 계약 표류 | LLM 혼동 | V-EM-14 상수 표, 공통 항목 변경은 두 계약 동시 변경 메모 |
| 단일 프로세스 전제 | 다중 프로세스면 제한 약화 | 전환 시 DB 카운터(변경 메모) |

## 20. 미결(사용자 확인)

(없음 — 2026-10-21 확정, EM-C1)

## 변경 메모(EM-Cn)

- **EM-C1**(2026-10-21, 사용자 결정 — 옛 Q1~Q3 확정):
  1. Case 생성(옛 Q1 → (b)): "프로젝트 폴더에 입력 데이터가 있다면 케이스 생성에 포함." → `list_case_inputs`(read)·`create_case`(run, confirm never, `MCP_ACTIONS`) 추가, 입력은 서버에 이미 있는 것만(§5.4.1 — 프로젝트 일치·소유 규칙 통과한 COMPLETED 업로드, 또는 허용 루트 폴더의 rad 1 + h3d 1/결과 폴더 1, 기존 경로·심링크·업로드 격리 검사 재사용). 업로드·Case 수정/보관은 계속 제외. 바뀐 절: §1, §2, §3(EM-7·EM-8·EM-16), §5.3, §5.4(신설), §6.1, §9.1(16 → 18개), §10, §11, §12, §15, §16, §17, §18(V-EM-1·7·15), §19.
  2. 토큰 권한 출처(옛 Q2): 역할 스냅숏 방식 확정(대시보드 서비스 introspection 안 씀), `snapshot_max_age_days` 기본 14 → **30**. 바뀐 절: §3 EM-3, §4.3, §12, §18 V-EM-2, §19.
  3. `denied_job_kinds` 기본 `[]` 확정(무거운 작업은 confirm_token). 바뀐 절: §3 EM-17, §5.2, §12, §18 V-EM-7.
  - physicsai 계약의 snapshot 기본값도 30으로 맞춰야 한다(V-EM-14 공통 항목 — 형제 계약 동시 변경 필요).
