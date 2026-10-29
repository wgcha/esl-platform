# 계약: v0.10.0 메뉴 재구성 — [ESL 생성] · [ESL 라이브러리]

- 상태: **확정** (2026-10-29, 사용자 확정 1~3 + 미결 Q1 A·Q2 B·Q3 B 확정 — §15). 구현 코드 없음. 이 문서가 구현·검증의 원본이다.
- 버전: v0.10.0 (기준 main v0.9.0 `a48d691`).
- 대체 범위: `esl_p3_ux.md` §2(⑥ 결과 받기 위치)·§4(가이드 ①~⑥), `esl_disp_primary.md` §8(라이브러리 등록 규칙 — FAIL·UNDETERMINED 사유 등록 폐지), `esl_opt_run.md` §10.1·`esl_bead_doe.md` §12.1(라이브러리 탭·선택 줄), `esl_p3_history.md` §5(단계 링크 번호). 충돌 시 이 문서 우선.
- ID 규칙: 결정 `MR-D-n`, 시험 `V-MR-n`, 리스크 `R-MR-n`.

## 0. 사용자 확정 (2026-10-29)

1. 최상단 메뉴 2개: **[ESL 생성] [ESL 라이브러리]**.
   - ESL 생성 = 케이스 목록 + 새 케이스. 케이스 단계 **①입력 ②t*·지지점 ③ESL ④검증** → [라이브러리에 등록]. 기존 ③지지점 단계 폐지 — 3-2-1 자동 선택을 ② t* 확정 때 함께 수행하고 ② 요약에 표시만(편집 UI 없음). 자동 선택이 품질 검사(공선·근접 등)에 걸리면 이유와 함께 ②에서 멈춤. 기존 ⑥내보내기 단계 폐지(케이스 헤더 [결과 받기(zip)]은 유지 — FAIL 원인 조사용).
   - ESL 라이브러리 = ESL 목록(필터·선택 체크) + 선택한 ESL 대상 동작 [내보내기] [강성 평가 스터디] [비드 최적화] [종합분석]. 탭: **ESL 목록 | 강성 평가 스터디 | 비드 최적화 | 종합분석·버전 비교 | 템플릿**. '비드 DOE' → '강성 평가 스터디'(화면·가이드·보고서 문구).
2. 내보내기는 라이브러리에서만: ESL 여러 개 선택 → [내보내기] 창(형식·옵션) → zip. 기존 EXPORT 작업 재사용, 여러 ESL용 API 1개.
3. 라이브러리 등록 = 변위 기준 **PASS만**. FAIL·판정 불가(UNDETERMINED) 등록 불가(사유 표시). 기존 LEGACY 항목은 유지 + LEGACY 배지, 강성 평가·비드 최적화·종합분석에서 기본 선택 불가, [재검증] → 현재 기준 검증 재실행 → PASS면 정상 항목으로 전환(FAIL이면 LEGACY 유지 또는 폐기 안내).

## 1. 현황 (main a48d691, v0.9.0)

| 대상 | 위치 | 현재 동작 |
|---|---|---|
| 라우트 | `frontend/src/app/App.tsx` | `/p/:pid`(CaseList), `/p/:pid/c/:cid/stage/:n`(n=1..6), `/p/:pid/library`(`?tab=items\|analyses\|comparisons\|opt\|templates\|doe`), `/p/:pid/opt*`, `/p/:pid/doe*`, 이력 3종 |
| 상단 바 | `shell/Shell.tsx` `TopBar` | 프로젝트 안에서 메뉴 1개 [라이브러리] |
| 단계 | `shell/StageStepper.tsx` `STAGE_NAMES` | 입력·t*·지지점·ESL·검증·내보내기(6), 상태 = `case.stage_status["1".."6"]` |
| ② t* | `stages/Stage2.tsx`, `PUT /cases/{id}/tstar` | 추출 등록 시 t* 자동(source auto). 확정 버튼은 값이 바뀔 때만 활성 |
| ③ 지지점 | `stages/Stage3.tsx`, `POST /cases/{id}/support-sets/suggest`·`POST …/support-sets` | 동기 API(작업 아님). PCA 4꼭지점 → `pick_321`(삼각형 면적 최대 + σmin/σmax ≥ 1e-6) 제안, 사용자가 노드 ID 3칸 편집·저장. `support_sets.source` auto/user |
| ESL_SOLVE | `api/services/jobs.py _prepare` | `current_support_set_id` 없으면 409 `PREREQUISITE_MISSING missing:["support_set"]` |
| ⑥ 내보내기 | `stages/Stage6.tsx`, 작업 EXPORT(LIGHT, step EXPORT→EXP_REGISTER), 코어 `stage_export` | 대상 radioss_inc·fem·csv, **현재 ESL run만**(워커 사전 재확인), Case `06_export/` 덮어쓰기 + `history/<job_id>/` 보존 |
| 라이브러리 등록 | `api/services/library.py register_entry`, `components/LibraryRegister.tsx`(⑤ 결과 카드 보조 버튼) | PASS 사유 불필요, FAIL·UNDETERMINED `force_reason` 필수, LEGACY는 당시 verdict 규칙. 항목 폴더 `_library/entries/<id>/{entry.json, raw.npz, summary.npz}`(수정 불가). raw = node_id·x0·elem_id·elem_type·conn·elem_pid·elem_mid·thickness·E·nu·f(F_eq)·u_rel·is_bc·3-2-1, meta.model = max_ids·mats |
| 라이브러리 선택 | `pages/library/LibraryList.tsx pickBlock` | 첫 행 = 기준, 같은 크기만 체크 가능(비드 최적화·DOE용). LEGACY 제한 없음 |
| 작업 제약 | `tables.py` | `ux_jobs_case_type_active`(Case·종류당 비종료 1), `ux_jobs_case_running`(Case당 RUNNING 1), `CK_JOBS_SUBJECT`(EXPORT는 case_id 필수) |
| '비드 DOE' | 화면 30여 곳, `esl/doe/report_doe.py`, `resources/doe_messages.json`, 이력 라벨, 가이드·`docs/manual/user.md` | API `/doe/*`, 작업 DOE_*, 테이블 `bead_does`, 설정 `bead_doe.*`, 폴더 `_doe/` |

## 2. 범위 / 비범위

| 범위 | 비범위 |
|---|---|
| 상단 메뉴 2개, 라우트·리다이렉트, 케이스 4단계 | 대시보드·physicsai 쪽 메뉴 |
| ② t* 확정 시 3-2-1 자동 선택 + 품질 검사 | 지지 방식 B(체결점)·C(스프링) |
| 라이브러리 다중 내보내기(API·창·zip) | 새 내보내기 형식(기존 3종만) |
| 등록 PASS 전용, LEGACY 배지·게이트·재검증 | 판정 기준값 변경, 과거 검증 일괄 재계산 |
| '비드 DOE' → '강성 평가 스터디' 사용자 문구 | API·DB·설정·폴더 이름 변경 |
| 화면 목업(2560×1440·1920×1080) | 새 시각 디자인 |

## 3. 결정

- **MR-D-1 DB 변경 없음(migration 없음).** 새 상태는 기존 JSONB에만 키 추가: `cases.tstar.support_auto`(§5.2), `jobs.params.origin·batch_id·items`(§6·§7), `library_entries.quality.revalidated`(§7.4). CHECK·컬럼·인덱스·job_type·stage 불변.
- **MR-D-2 백엔드 단계 번호 불변, 화면만 재번호.** `jobs.stage`(1..11)·`CaseOut.stage_status["1".."6"]`(기존 의미)는 하위 호환으로 유지(deprecated). 새 키 `CaseOut.step_status{input, tstar, esl, validate}`를 추가하고 화면은 이것만 쓴다(§5.4).
- **MR-D-3 지지 자동 선택 위치 = `PUT /cases/{id}/tstar` 서비스(동기 API, 작업 아님).** 기존에도 지지점은 작업이 아닌 동기 API였고 계산은 model.npz 좌표만 쓰는 PCA·SVD(30만 노드 < 1 s)라 새 job/step을 만들지 않는다. 현재 지지 세트가 **없을 때만** 자동 선택·저장, 있으면(자동·이전 수동 편집 모두) 그대로 둔다 — 지지점은 t*와 무관(초기 좌표만 사용).
- **MR-D-4 품질 검사 실패 = t*는 저장, 지지 세트 없음, ② 상태 failed + 사유.** 오류 응답(422) 대신 200 + `tstar.support_auto.status = "BLOCKED"`로 돌려 ②에서 멈춘 이유를 화면이 그대로 보여 준다. ESL_SOLVE는 409 `PREREQUISITE_MISSING missing:["support_set"]` + `support_blocked: true` + `problems`(화면은 support_blocked 면 "② 지지점 자동 선택 실패" 문구).
- **MR-D-5 다중 내보내기 = 기존 EXPORT 작업(job_type·step·LIGHT 레인)을 `params.origin = "library"` 모드로 재사용.** `CK_JOBS_SUBJECT`가 EXPORT에 case_id를 요구하고 `ux_jobs_case_type_active`가 Case당 비종료 EXPORT 1개만 허용하므로 **묶음(batch) 1개 = 서로 다른 Case마다 EXPORT 작업 1개**(같은 Case의 ESL 여러 개는 한 작업의 `items`). 새 job_type(LIB_EXPORT)은 migration이 필요해 택하지 않음.
- **MR-D-6 다중 내보내기의 원본 = 라이브러리 항목 폴더(`raw.npz`·`entry.json`)**, Case 폴더에는 쓰지 않는다(라이브러리 원칙 유지 — Case가 재추출·보관돼도 등록 당시 하중 그대로). 출력·로그 = `<esl_root>/_exports/<batch_id>/`. 코어 작성기(`esl/export/radioss.py`·`optistruct.py`·`csvout.py`, `plan_ids`)를 그대로 쓰고 입력 어댑터만 새로 둔다(§6.4).
- **MR-D-7 Case 단위 EXPORT API(`POST /cases/{id}/jobs` EXPORT)는 유지(CLI·스크립트 호환), 화면 진입점만 없앤다.** `stage_status["6"]`은 origin이 없는(Case) EXPORT만 본다.
- **MR-D-8 등록 = 현재 기준(scheme `disp_primary/1`) PASS만.** FAIL·UNDETERMINED → 422 `VALIDATION_NOT_PASS`(사유가 있어도), LEGACY 검증으로 새 등록 → 422 `VALIDATION_LEGACY`. `force_reason`은 스키마에 남기되 무시(구 클라이언트 호환).
- **MR-D-9 재검증 = 기존 VALIDATE 작업을 `params.origin = "library_revalidate"`로 재사용**, 대상 = 항목의 `esl_run_id`(현재 run 아니어도 됨 — 스냅샷 `runs/<run>/`에서 되돌림, 기존 `esl_snapshot.ensure_on_disk`). 조건 = 그 run의 추출이 Case 현재 추출과 같음(§7.3). PASS면 VAL_REGISTER가 같은 트랜잭션에서 항목을 정상으로 전환, 아니면 LEGACY 유지.
- **MR-D-10 게이트(서버 강제).** 비드 최적화(`POST /opt/runs`)·강성 평가 스터디(`POST /doe/studies`)·종합분석(`POST /library/analyses`)은 **적격 항목만**: `quality.status == "PASS"` 이고 scheme 있음. 부적격이 entry_ids에 있으면 422 `ENTRY_NOT_ELIGIBLE`, 필터 기반 분석은 부적격을 빼고 `excluded_ineligible` 수를 응답. 내보내기는 LEGACY 포함 허용(창에 경고) — 하중 자체는 유효. 기존 분석·최적화·스터디 결과는 그대로(스냅샷).
- **MR-D-11 이름 변경은 사용자 문구만.** API 경로 `/doe/*`, 작업 `DOE_*`, 테이블 `bead_does`·`jobs.bead_doe_id`, 설정 `bead_doe.*`, 폴더 `_doe/`, 오류 코드, 쿼리 키 `doe`, 파일명은 유지(근거: 이력 행·북마크·CLI 호환, migration 비용, 사용자에게 안 보임). 화면 상세 URL `/p/:pid/doe/:id`도 유지.
- **MR-D-12 URL은 북마크 호환 리다이렉트.** 케이스 단계 경로를 `/stage/:n` → `/step/:n`(n=1..4)으로 바꿔 옛 번호와 새 번호가 같은 URL에서 다른 화면을 뜻하지 않게 한다. 옛 `/stage/:n`은 매핑 리다이렉트(§4.2).

## 4. 화면 구조·라우트

### 4.1 상단 바 (`TopBar`, 프로젝트 안에서만)
- 메뉴 2개 `[ESL 생성]` → `/p/:pid`, `[ESL 라이브러리]` → `/p/:pid/library`. 활성 규칙: 경로가 `/library`·`/opt`·`/doe`로 시작하면 라이브러리, 그 외(`/p/:pid`, `/cases/new`, `/c/…`, `/history`, `/jobs/…`)는 생성.
- 경로 막대: `등가정적하중 › <프로젝트> › ESL 생성 › <케이스> › ② t*·지지점` / `… › ESL 라이브러리 › <탭 이름>`.

### 4.2 라우트 표

| 새 경로 | 화면 | 옛 경로(리다이렉트, `replace`, query 유지) |
|---|---|---|
| `/p/:pid` | ESL 생성 — 케이스 목록 + [새 케이스](주) + '실행 이력' 링크 | — |
| `/p/:pid/cases/new` | 새 케이스(그대로) | — |
| `/p/:pid/c/:cid` | → `step/1` | — |
| `/p/:pid/c/:cid/step/:n` (1..4) | 케이스 단계 | `/stage/1`→`/step/1`, `/stage/2`→`/step/2`, `/stage/3`→`/step/2`, `/stage/4`→`/step/3`(`?run=` 유지), `/stage/5`→`/step/4`(`?val=` 유지), `/stage/6`→`/step/4?moved=export`(한 줄 안내 "내보내기는 ESL 라이브러리로 옮겨졌습니다 — 등록 후 라이브러리에서 내보내세요" + 링크) |
| `/p/:pid/c/:cid/history`, `/p/:pid/history`, `/p/:pid/jobs/:jobId` | 그대로 | — |
| `/p/:pid/library?tab=` | ESL 라이브러리: `items`(기본)·`study`·`opt`·`analyses`·`templates` | `?tab=doe`→`study`, `?tab=comparisons`→`analyses#comparisons` |
| `/p/:pid/library/analyses/*`, `/library/comparisons/*`, `/opt/new`, `/opt/:id`, `/doe/new`, `/doe/:id` | 그대로(라벨만 변경) | `/p/:pid/doe`→`library?tab=study`, `/p/:pid/opt`→`library?tab=opt` |

- 이력 링크: `api/history.ts`는 서버 `links.stage`(옛 1..6)를 `stepOfStage = {1:1,2:2,3:2,4:3,5:4,6:4}`로 바꿔 `/step/:n`을 만든다. `JobReview`의 Case 링크도 `job.stage ≤ 6`이면 같은 매핑, 그 외 step 1. 가이드 `target {kind:"stage", n}`은 새 번호.

### 4.3 케이스 단계 (재번호)

| 새 | 화면(파일) | 주 버튼 | 내용 |
|---|---|---|---|
| ① 입력 | `Stage1.tsx`(그대로) | 추출 실행 | 변경 없음 |
| ② t*·지지점 | `Stage2.tsx`(확장) | **t* 확정** | 기존 t* 화면 + 카드 "지지점 (3-2-1, 자동)"(§5.3) |
| ③ ESL | `Stage4.tsx`(제목·번호만) | ESL 계산 | 변경 없음(차단 사유에 지지 BLOCKED 문구) |
| ④ 검증 | `Stage5.tsx`(등록 버튼 위치) | 검증 실행 / **라이브러리에 등록** | §7.1 |

- `Stage3.tsx`·`Stage6.tsx` 삭제. `Stage6`에서 다른 곳이 쓰는 것(`CopyPath`·`TOO_LARGE_TEXT` 재수출)은 import를 `components/CopyPath`로 바꾼다.
- 케이스 헤더(case-menu): 누적 배지 · '실행 이력' · **[결과 받기(zip)] 유지**(`GET /cases/{id}/bundle`, 그대로).
- 주 버튼 1개 원칙 유지.

## 5. ② t*·지지점 — 자동 3-2-1

### 5.1 백엔드 흐름 (`api/services/cases.py put_tstar`)
1. 기존 t* 검사(지표·후보·in_D) 그대로. **같은 t* 재확정 허용**(지지 재시도용, 화면도 허용 — §5.3).
2. 잠금 전에 Case를 읽어 `current_support_set_id`가 없으면 `core_adapter.auto_support(x0, check_cfg)` 계산(모델 로드 + 계산, 트랜잭션 밖).
3. `for_update` 잠금 → version 검사 → 결과 반영:
   - 지지 세트 있음: `tstar.support_auto = {status:"KEPT", source:<auto|user>}`.
   - 자동 OK: `support_sets` 행 삽입(`source:"auto"`, plane) + `current_support_set_id` 설정, `tstar.support_auto = {status:"OK", mode, checks, rule_version}`.
   - 자동 BLOCKED: 지지 세트 없음, `tstar.support_auto = {status:"BLOCKED", mode, problems:[{code, message, value, limit}], rule_version}`.
4. 응답 200 `CaseOut`(step_status 포함). 잠금 중 다른 사용자가 먼저 지지 세트를 만들었으면 그것을 유지(KEPT).
- 추출 재등록(`register_extract`)은 지금처럼 t*를 auto로 다시 쓰고(→ `support_auto` 사라짐) 지지 세트는 노드가 모두 남을 때만 유지 — 변경 없음.
- `POST …/support-sets/suggest`·`GET …/support-sets`는 API 호환으로 유지. `POST …/support-sets`(수동 지정, Q2 B의 '고급' 칸이 사용)는 저장 전 §5.2 검사 중 `SUPPORT_DEGENERATE`·`SUPPORT_COLLINEAR`·`SUPPORT_TOO_CLOSE`·`SUPPORT_ILL_CONDITIONED`를 **같은 기준으로** 적용(후보 확장 없음, 준 3노드만) → 실패 시 422 `SUPPORT_CHECK_FAILED {problems}`(기존 `NODE_NOT_IN_PART`·중복 노드 422 유지), 성공 시 `tstar.support_auto = {status:"MANUAL", checks, rule_version}`. `suggest`도 같은 `auto_support` 결과를 돌려준다(`status`·`problems` 키 추가).

### 5.2 품질 검사 규칙 (코어 `esl/mech/supports.py auto_321`, 순수 함수)
입력 X0(N×3), PCA 평면(기존 `pca_corners` 축·부호), 면내 범위 L_a = max a − min a, L_b = max b − min b, D = √(L_a² + L_b²).

| 순서 | 후보 | 설명 |
|---|---|---|
| 1 | `pca4` | 기존 PCA 4꼭지점 → `pick_321`과 같은 삼각형·dof 규칙 (opt·DOE `esl/opt/target.py`와 같은 결과) |
| 2 | `pca8` (`expand_candidates`일 때만, 1이 검사 실패 시) | 4꼭지점 + a·b 단독 극점 4개(최대/최소 a, 최대/최소 b) = 최대 8개, 3개 조합 전부(≤ 56) 평가 → 검사 전부 통과 중 삼각형 면적 최대(동률은 낮은 인덱스) |

검사(삼각형 p1..p3, 모두 통과해야 OK):

| 코드 | 값 | 기준(설정, 기본·임시) | 의미 |
|---|---|---|---|
| `SUPPORT_DEGENERATE` | PCA 공선 또는 3-2-1 구속행렬 σmin/σmax < 1e-6 | 코어 상수(기존) | 정할 수 없음 |
| `SUPPORT_COLLINEAR` | area_ratio = A_tri / (0.5·L_a·L_b) | `support.auto_check.min_area_ratio` **0.10** | 세 점이 거의 한 줄(직사각 판 꼭지점 = 1.0) |
| `SUPPORT_TOO_CLOSE` | min_dist_rel = min ‖p_i − p_j‖ / D | `support.auto_check.min_dist_rel` **0.15** | 두 점이 너무 가까움 |
| `SUPPORT_ILL_CONDITIONED` | cond_ratio = σmin/σmax(강체 6모드 구속행렬, 기존 `_rigid_matrix`) | `support.auto_check.min_cond_ratio` **1e-3** | 구속이 수치적으로 약함 |

- 반환: `{status:"OK"|"BLOCKED", mode:"pca4"|"pca8", idx, dofs, plane, corners, checks:{area_ratio, min_dist_rel, cond_ratio}, problems:[…]}`. BLOCKED의 `problems` = pca4 삼각형의 실패 검사(값·기준 포함) + (확장했으면) `{code:"SUPPORT_NO_VALID_CANDIDATE", message:"후보 8개 조합 중 통과 없음"}`.
- 메시지(한글, `message`): 예 "지지 3점이 거의 한 줄입니다(면적비 0.04 < 0.10)", "지지 두 점이 너무 가깝습니다(거리 0.08·대각선 < 0.15)", "지지 구속이 약합니다(조건비 4e-4 < 1e-3)".
- 기존 `pca_corners`·`pick_321`은 그대로(opt·DOE·코어 CLI 결과 불변).

### 5.3 ② 화면
- 주 버튼 **"t* 확정"** 활성 조건: 권한·추출 완료·후보 선택 + (t*가 바뀜 **또는** 지지 세트 없음). 지지 세트가 이미 있고 t*가 같으면 기존처럼 "현재 확정된 t*와 같습니다".
- 기존 max-hold·후보·hotspot 카드 아래 카드 **"지지점 (3-2-1, 자동)"** (편집 UI 없음):
  - 지지 세트 있음: 표 3행 `역할(1번 3방향 / 2번 2방향 / 3번 1방향) · 노드 ID · dof`, 출처 배지 `자동` 또는 `사용자 지정(이전 버전에서 편집)`, `checks` 있으면 한 줄 "면적비 0.82 · 최소 거리 0.61 · 조건비 0.12"(작은 글씨).
  - 아직 없음: "t* 확정 시 자동으로 정합니다".
  - BLOCKED: warn-box "지지점을 자동으로 정하지 못했습니다" + `problems` 목록(메시지) + 안내 한 줄 "모델(대상 파트) 형상을 확인하거나 관리자에게 기준(support.auto_check) 조정을 요청하세요". 
  - **BLOCKED일 때만** 카드 아래 접힌 `<details>` **'고급 — 지지 노드 직접 지정'**(기본 접힘, 권한 없으면 숨김): 노드 ID 3칸(1번 3방향·2번 2방향·3번 1방향) + 보조 버튼 [지정 저장] → 기존 `POST /cases/{id}/support-sets`. 저장 성공 → 지지 세트(source user) 설정, `tstar.support_auto = {status:"MANUAL", checks}`, ② done. 평소(OK·KEPT)에는 이 칸이 없다(편집 UI 없음 원칙 유지).
- ③ ESL 차단 사유: 지지 세트 없음 + BLOCKED → "② 지지점 자동 선택 실패 — ②에서 사유 확인", 없음 + 미확정 → "② t* 확정이 필요합니다".

### 5.4 `step_status` (CaseOut 새 키, `services/cases.py`)
`StageStatus`에 선택 키 `reason: {code, message} | null` 추가.

| 키 | 계산 |
|---|---|
| `input` | 기존 `"1"` |
| `tstar` | 추출 실행 중 → running. 추출 stale → stale(t* 있을 때). t* 있음 ∧ 지지 세트 있음 → done. t* 있음 ∧ `support_auto.status == BLOCKED` → failed, reason `SUPPORT_AUTO_BLOCKED`. t* 있음 ∧ 지지 없음 → none, reason `TSTAR_NOT_CONFIRMED`. t* 없음 → 기존 `"2"` 규칙 |
| `esl` | 기존 `"4"` |
| `validate` | 기존 `"5"` |

- 기존 `stage_status` 유지(값 계산 동일, 단 `"6"`은 origin 없는 EXPORT만).

### 5.5 기존 케이스 하위 호환

| 기존 상태 | v0.10.0 동작 |
|---|---|
| t* + 지지 세트(자동) | ② done, 배지 `자동`. ESL·검증 결과 그대로 |
| t* + 지지 세트(사용자 수동 편집) | ② done, 배지 `사용자 지정(이전 버전에서 편집)`, **덮어쓰지 않음**. 이후 t* 재확정해도 유지(MR-D-3) |
| t*(auto)만, 지지 없음 | ② none("t* 확정 필요") → 확정 시 자동 선택 |
| 이전 run이 다른 지지 세트 사용 | 기존 stale 규칙(`support_set` 사유) 그대로 |
| 옛 북마크 `/stage/3`·`/stage/6` | §4.2 리다이렉트 |

## 6. 다중 내보내기 (라이브러리)

### 6.1 API
**`POST /library/exports`** (power 이상, CSRF, `require_config_ok`·`require_library_config`)
```json
{ "project_id": "…", "entry_ids": ["…", "…"], "targets": ["radioss_inc", "fem", "csv"],
  "options": { "id_offset": "auto", "id_policy": "per_model_sequential" } }
```
- `entry_ids` 1..`library_export.max_entries`(50 — 화면은 상수 대신 `GET /version` 의 `ui.library_export_max_entries`로 받아 선택 줄 [내보내기] 비활성 사유에 쓰고, 최종 판정은 422 `TOO_MANY_ENTRIES`), 중복 금지, 이 프로젝트 ACTIVE 항목만. `targets` ≥1, 값 = 기존 `EXPORT_TARGETS`. `options.id_offset` = `"auto"`(기본 = 설정 `export.radioss.id_offset`) 또는 정수 ≥ 0. `options.id_policy` = `per_model_sequential`(기본, Q3 확정 B) | `independent`(API 전용 — 창에는 선택지 없음).
- 처리: batch_id(uuid) → `_exports/<batch_id>/batch.json` 작성(project_id, created_by, entry_ids, labels, targets, options, job_ids) → 항목을 `case_id`로 묶어 Case마다 EXPORT 작업 1개 삽입(한 트랜잭션, 하나라도 `ux_jobs_case_type_active` 충돌이면 전체 롤백 + 409).
- 응답 **202** `ExportBatchOut`(아래).

**`GET /library/exports/{batch_id}`** → `ExportBatchOut`:
```text
{batch_id, project_id, created_by, created_by_name, created_at, targets, options,
 state: QUEUED|RUNNING|SUCCEEDED|PARTIAL|FAILED|CANCELED,
 jobs: [{job_id, case_id, state, progress_pct, failure_code, failure_message}],
 items: [{entry_id, label, case_id, legacy: bool, state: PENDING|DONE|FAILED, files: [{rel, size}], id_range, warnings, error}],
 bundle: {ready: bool, bytes: int|null}}
```
- state: 작업 모두 SUCCEEDED·항목 모두 DONE → SUCCEEDED, 종료 + DONE 일부 → PARTIAL, 종료 + DONE 0 → FAILED, 취소 포함 종료 → CANCELED, 그 외 RUNNING/QUEUED.

**`GET /library/exports?project_id=&limit=`** → 최근 묶음 요약 목록(기본 20, 최대 100): `jobs`에서 `project_id`·`job_type='EXPORT'`·`params->>'origin'='library'`를 created_at desc로 읽어 batch_id로 묶음(인덱스 `ix_jobs_project_created` 사용, 새 인덱스 없음).

**`GET /library/exports/{batch_id}/bundle`** → 스트리밍 zip(`services/bundle.stream_zip` 재사용), 파일명 `esl_export_<yyyymmdd-HHMM>_<n>.zip`:
```text
manifest.json          # batch 요약 + 항목별 {entry_id, label, case_id, esl_run_id, validation status, id_range, files, warnings}
README.txt             # 한글: 폴더 구조, ID 배정 방식, LEGACY 항목 표시
<NN>_<label>/esl_cload.inc  esl_bcs.inc  esl_force.fem  f_eq.csv  u_rel.csv  supports_321.csv  [reactions_321.csv  validation.csv]
```
- `GET /library/exports` 행 = `ExportBatchSummary {batch_id, project_id, created_by, created_by_name, created_at, state, targets, n_items, job_ids}`(프런트 `library.ts`가 이 모양 그대로). `ExportBatchItem.id_range` = `[시작, 끝]`(양 끝 포함, Radioss·fem 대상 없으면 null).
- `<label>` = 모델_씬(entryLabel 규칙, 파일명 안전 문자만, ≤ 60자) + `_<entry_id 앞 8자>`, `<NN>` = 선택 순서 2자리.
- 상한 `library_export.max_bundle_bytes`(기본 = `ui.max_bundle_bytes`).

| 오류 | 코드 |
|---|---|
| targets 비었음·알 수 없는 값·entry_ids 비었음/중복·id_offset 형식 | 422 `INVALID_PARAMS` |
| 항목 수 초과 | 422 `TOO_MANY_ENTRIES` {max} |
| 다른 프로젝트·폐기·없는 항목 | 422 `ENTRY_NOT_FOUND` {entry_ids} |
| 항목 폴더 `raw.npz`·`entry.json` 없음 | 409 `ENTRY_FILES_MISSING` {entry_ids} |
| 같은 Case에 비종료 EXPORT 있음 | 409 `CASE_JOB_BUSY` {case_ids} |
| 권한 | 403 |
| 묶음 없음 | 404 `EXPORT_NOT_FOUND` |
| bundle: 진행 중 | 409 `EXPORT_NOT_READY` |
| bundle: 성공 항목 0 | 409 `EXPORT_FAILED` |
| bundle: 상한 초과 | 413 `BUNDLE_TOO_LARGE`(기존 형식, 경로 안내) |

### 6.2 EXPORT 작업 — library 모드 params
```json
{ "origin": "library", "batch_id": "…", "targets": [...], "options": {...},
  "items": [{"entry_id": "…", "esl_run_id": "…", "dir_rel": "_library/entries/<id>", "label": "01_…", "id_offset": 9000000}],
  "settings": {"export": {...코어 export 설정 스냅샷...}} }
```
- 항목별 `id_offset`:
  - `independent`: 전부 `options.id_offset`(정수 또는 `"auto"`).
  - `per_model_sequential`(기본, Q3 확정 B): 같은 `topo_sha256` 항목을 **(Case 작업 순서 → 선택 순서)**로 줄 세워 첫 항목만 `options.id_offset`, 나머지는 `"after:<앞 entry_id>"`. Case 작업 순서 = 각 Case 의 첫 선택 순(작업도 이 순서로 큐에 삽입), 같은 Case 안은 선택 순서 그대로. **근거(통합 시 구현 기준으로 갱신)**: EXPORT 는 LIGHT 레인 FIFO 라, 순수 선택 순서(예: A1·B1·A2·B2 — A·B 는 Case)로 이으면 A 작업이 B1 결과를, B 작업이 A2 결과를 서로 기다리는 교차 대기가 생기고 LIGHT 레인이 1개면 뒤 작업이 시작도 못 해 `EXPORT_ORDER_TIMEOUT`(600 s)으로 끝난다. Case 작업 순서를 먼저 두면 앞 항목은 항상 같은 작업의 앞쪽이거나 먼저 큐에 든 작업에 있어 대기가 한 방향(뒤 작업 → 앞 작업)뿐이고 교착이 없다. 선택 순서는 zip 폴더 번호 `<NN>`과 manifest 순서에만 쓰이고, 실제 ID 범위는 manifest `id_range`·창의 항목별 `ID 시작–끝`으로 확인한다. 사용량(`id_max_used`)은 실행해야 알 수 있으므로 워커가 앞 항목 결과 `_exports/<batch>/<label>/export.json id_max_used`를 읽어 그 다음 정수를 시작으로 쓴다. 같은 Case 작업 안이면 순서대로 처리, 앞 항목이 다른 Case 작업에 있으면 그 결과가 생길 때까지 이 항목은 `PENDING`으로 대기(lease 갱신·취소 확인 계속, 최대 `library_export.wait_s` 600 s → 항목 실패 `EXPORT_ORDER_TIMEOUT`). 앞 항목이 실패하면 이 항목도 실패 `EXPORT_ORDER_PREV_FAILED`.
- 워커(`executor.py`):
  - 작업 폴더 = `_exports/<batch_id>/`, 로그 = `_exports/<batch_id>/logs/<job_id>/step_NN_<key>.log`(LIB_ANALYZE와 같은 방식). **Case 폴더에 쓰지 않음.**
  - 건너뜀: 입력 지문 재확인(INPUT_CHANGED), VALIDATE·EXPORT 현재 run 사전 재확인, `history/<job_id>/` 보존(H-5), artifacts 등록, `stage_status`.
  - step EXPORT: 자식 프로세스가 코어 `esl.export.from_entry.run_items(items, out_root, targets, cfg)` 실행 — 항목별 try, 실패 항목은 `error{code, message}` 기록 후 다음 항목.
  - step EXP_REGISTER: `jobs.result.registered = {batch_id, items:[{entry_id, state, files, id_range, id_max_used, warnings, error}]}`. 항목 전부 실패면 작업 FAILED `EXPORT_ALL_FAILED`(첫 오류 메시지), 일부 실패는 SUCCEEDED + warnings.

### 6.3 [내보내기] 창 (라이브러리)
- 열기: ESL 목록에서 1개 이상 선택 → [내보내기](주). 모달 1개.
- 내용(필수만): 선택 수·LEGACY 수 줄("LEGACY 2개 포함 — 하중은 같고 판정 체계만 이전입니다"), **형식** 체크 3개(Radioss inc (/CLOAD·/BCS) · OptiStruct fem · CSV, 기본 전부), **Radioss·fem ID 시작** 라디오(자동(rad 최대 ID 위) / 지정 [숫자]), 한 줄 설명 "같은 모델 ESL은 ID가 겹치지 않게 이어서 배정". 버튼 [내보내기 시작](주)·[닫기].
- 실행 후 같은 창에서 진행(항목별 상태 칩·작업 진행률, 2초 폴링), 끝나면 **[zip 받기]**(주) + 실패 항목 사유 표. 창을 닫아도 작업은 계속, 창 하단 "최근 내보내기" 접힘 목록(`GET /library/exports`)에서 다시 받기.
- 상단 바 상태 칩·서랍에 작업이 보이고, 이력에는 "내보내기(라이브러리)" 라벨 + 요약 `{n_items, targets}`.

### 6.4 코어 어댑터 `esl/export/from_entry.py` (신규)
- `load_entry_model(entry_dir)` → 항목 `raw.npz`(allow_pickle=False) + `entry.json`으로 `write_force_fem`이 요구하는 model 속성(node_id·x0·elem_id·elem_type·conn·elem_pid·thickness·mats·max_ids·part_id·part_title) 객체.
- `export_entry(entry_dir, out_dir, targets, cfg, id_offset)` → 기존 `plan_ids`·`all_ids`·`force_mask`·`radioss.write_cload_inc`·`write_bcs_inc`·`optistruct.write_force_fem`·`csvout`을 `stage_export`와 같은 순서·같은 헤더 형식으로 호출. 반환 `{files, id_range, id_max_used, id_plan, warnings}` + `export.json` 저장.
- CSV 묶음(라이브러리): `f_eq.csv`(같은 헤더), `u_rel.csv`(같은 헤더 — `u_total` 열은 항목 raw에 없으므로 비우고 경고 1줄 "u_total 은 Case 결과 zip 참고"), `supports_321.csv`(node_id, dof), 그리고 항목 검증 스냅샷이 있으면(`entry.json source.snapshot_dir/05_val` 표식 = 항목 validation_id, 읽기만) `reactions_321.csv`·`validation.csv`. `tstar_candidates.csv`·`hotspots.csv`는 Case 자료라 넣지 않음(Case [결과 받기(zip)]).
- inc·fem 본문은 같은 입력이면 `stage_export`와 **바이트 동일**(헤더 생성 시각 줄 제외) — V-MR-11.

## 7. 라이브러리 등록·LEGACY·재검증

### 7.1 ④ 검증 화면 — [라이브러리에 등록]
- 주 버튼 규칙(1개): 현재 run의 최신 검증 없음·stale → "검증 실행". 최신 검증 PASS(scheme 있음) ∧ 미등록 → **"라이브러리에 등록"**. 등록됨 → 주 버튼 "검증 실행" + 결과 카드에 `라이브러리 등록됨 · 보기`.
- FAIL·판정 불가: 등록 버튼 비활성, 사유 한 줄 "변위 기준 PASS만 등록할 수 있습니다 — FAIL 사유는 [결과 받기(zip)]로 확인". LEGACY(이전 검증): "현재 기준으로 다시 검증한 뒤 등록하세요".
- `LibraryRegister.tsx`: 사유 입력 대화상자 삭제, 등록 = 바로 POST.

### 7.2 등록 API (`POST /library/entries`, 기존)
| 검증 status | 결과 |
|---|---|
| PASS(scheme 있음) | 201 (기존) |
| FAIL·UNDETERMINED | 422 `VALIDATION_NOT_PASS` {verdict}(force_reason 무시) |
| LEGACY | 422 `VALIDATION_LEGACY` "이전 판정 체계 결과는 등록할 수 없습니다 — ④에서 다시 검증하세요" |
- 그 외 오류(ENTRY_EXISTS·VALIDATION_NOT_LATEST·PREREQUISITE_MISSING)는 그대로.

### 7.3 재검증 API — `POST /library/entries/{eid}/revalidate` (power 이상)
- 대상: ACTIVE 항목 중 부적격 전부 — `quality.scheme` 없음(LEGACY) + 사유와 함께 등록된 FAIL·UNDETERMINED(Q1 확정 A, 화면 배지는 `LEGACY` 옆에 당시 상태 `FAIL`/`판정 불가`).
- 검사(순서): 항목 없음 404 `ENTRY_NOT_FOUND` · 폐기 409 `ENTRY_RETIRED` · 이미 적격(PASS·scheme) 409 `ENTRY_NOT_LEGACY` · Case 보관 409 `CASE_ARCHIVED` · run 스냅샷 없음 409 `REVALIDATE_NOT_POSSIBLE{reason:"RUN_SNAPSHOT_MISSING"}` · 추출 바뀜: `inputs_hash(extract_job_id = 현재 extract_summary.job_id, part_title = 현재, tstar = {run.frame_index, run.metric}, support_set_id = run.support_set_id) != run.inputs_hash` 또는 `extract_stale(case)` → 409 `REVALIDATE_NOT_POSSIBLE{reason:"EXTRACT_CHANGED"}`(안내: "Case를 다시 계산해 새로 등록하세요") · 같은 Case 비종료 VALIDATE 409 `CASE_JOB_BUSY`.
- 생성: VALIDATE 작업 `params = {esl_run_id, origin:"library_revalidate", entry_id, settings(현재 판정 기준)}` → 201 `JobOut`.
- 워커: 사전 재확인에서 "현재 run" 조건 대신 위 추출 동일 조건 재검사(실패 `PREREQUISITE_MISSING`), `ensure_on_disk`로 스냅샷 되돌림(기존 경고 문구), 코어 validate 그대로. CASE_REPORT 자동 큐는 하지 않음(현재 run 보고서가 아니므로).

### 7.4 전환 (VAL_REGISTER, 같은 트랜잭션)
- 새 검증 행 등록(기존) 후 `origin == "library_revalidate"`이면 항목 행 잠금:
  - 항목이 아직 ACTIVE ∧ `esl_run_id` 같음 ∧ 새 status PASS → `validation_id` = 새 검증, `quality`의 판정 키(`verdict, status, scheme, undetermined_reason, disp_rms_rel, disp_max_rel, disp_noise_rel, reaction_rel, strain_exceed_frac, fail_reasons, field_*`)를 새 검증으로 갱신 + `quality.revalidated = {from_validation_id, from_status, job_id, at, by, by_name}`, `force_reason`·`confirmed_*` = null, version+1. → 결과 `revalidate.outcome = "PROMOTED"`.
  - FAIL·UNDETERMINED → 항목 불변, `outcome = "KEPT_LEGACY"` + status.
  - 결과 키(`jobs.result.revalidate`, 세 경우 공통): `{outcome: PROMOTED|KEPT_LEGACY|ENTRY_CHANGED, status: 새 검증 PASS|FAIL|UNDETERMINED|LEGACY, fail_reasons: [새 검증 FAIL 사유 코드 — 예 "DISP_MAX"], verdict, entry_id, validation_id}`. 화면 KEPT_LEGACY 안내 "현재 기준 FAIL(DISP_MAX) …"의 괄호 = `fail_reasons`(통합 시 추가 — 프런트가 쓰는 키를 서버가 제공).
  - 항목이 그사이 폐기·변경 → 불변, `outcome = "ENTRY_CHANGED"`(경고).
- 항목 폴더(`entry.json`·`raw.npz`)는 **바꾸지 않는다**(하중 불변, 수정 불가 규칙 유지). 판정의 원본 = DB `quality`; 종합분석 overlay(작업 params)에 `quality.status·scheme`를 추가해 보고서도 DB 값을 쓴다.
- 화면(행): LEGACY 행에 배지 `LEGACY` + 보조 버튼 [재검증] → 행 상태 칩(대기·실행 중) → 끝나면 목록 다시 읽기. PROMOTED: 배지 사라짐 + 토스트 "현재 기준 PASS — 정상 항목으로 전환". KEPT_LEGACY: 행 아래 한 줄 "현재 기준 FAIL(DISP_MAX) — LEGACY로 유지하거나 [폐기]하세요"(기존 retire). REVALIDATE_NOT_POSSIBLE: 버튼 비활성 + 사유 툴팁(목록 응답 `revalidate_block`으로 미리 계산 — 아래).
- `EntryOut` 추가 키: `eligible: bool`, `ineligible_reason: "LEGACY"|"FAIL"|"UNDETERMINED"|null`, `revalidate_block: {code, reason, message}|null`(code = 오류 코드 `CASE_ARCHIVED`·`REVALIDATE_NOT_POSSIBLE`·`CASE_JOB_BUSY`, reason = 세부 `RUN_SNAPSHOT_MISSING`·`EXTRACT_CHANGED`(없으면 code), message = 한글 안내 — 화면 툴팁은 message; 목록 조회 시 Case·run 행 일괄 조회로 계산, N+1 금지), `revalidate_job: {job_id, state}|null`(비종료 VALIDATE origin library_revalidate).

### 7.5 게이트 (MR-D-10)
- `POST /opt/runs`·`POST /doe/studies`(entry_ids)·`POST /library/analyses`(filters.entry_ids, target_entry_id): 부적격 → 422 `ENTRY_NOT_ELIGIBLE {entry_ids, reasons}`. 필터만 준 분석은 부적격 제외 후 응답 `excluded_ineligible: n`(0이면 생략), 남은 항목 0이면 기존 422 `NO_MATCHING_ENTRIES`.
- 화면: 체크는 자유(폐기만 불가), 동작 버튼마다 비활성 사유 — 강성 평가·비드 최적화·종합분석: "LEGACY n개 선택됨 — 재검증 후 사용"; 강성 평가·비드 최적화: 기존 같은 크기 규칙("크기 다름(기준 …)"); 내보내기: 50개 초과만.

## 8. ESL 라이브러리 화면

- 탭(`LibTab`): `items` ESL 목록 | `study` 강성 평가 스터디(기존 DoeList) | `opt` 비드 최적화(기존 OptList, 탭 이름 '최적화 실행' → '비드 최적화') | `analyses` 종합분석·버전 비교(분석 표 + `#comparisons` 비교 표, 비교 표 머리에 보조 [버전 비교 만들기]) | `templates` 템플릿.
- ESL 목록: 기존 필터(모델·씬 유형·orient·모드·판정·폐기 포함), 판정 필터 값 PASS / LEGACY / FAIL·판정 불가(Q1 A — 셋 다 부적격, 재검증 대상). 머리 체크 = 보이는 ACTIVE 행 전체 선택. 열: 선택 · 모델 · 인치/크기 · 씬 · 모드 · 판정(PASS·LEGACY 배지) · 등록자·시각 · 동작([수정] [재검증] [폐기]).
- 선택 줄(선택 ≥ 1일 때 고정 표시): `선택 n개 · LEGACY k · 기준 크기 …` + **[내보내기 (n)](주)** [강성 평가 스터디 (n)] [비드 최적화 (n)] [종합분석 (n)] [선택 해제]. 종합분석은 `/library/analyses/new?entries=…`(AnalysisNew가 entries 쿼리로 entry_ids 채움).
- 탭이 템플릿일 때만 그 탭 주 버튼(템플릿 등록) — 기존 규칙. 페이지 머리의 '종합분석 만들기' 주 버튼은 폐지(선택 줄로 대체).

### 8.1 목업 — 2560×1440 (필수 UI만)
```text
┌ E ESL │ 등가정적하중 › TV75 › ESL 라이브러리 › ESL 목록 │ [ESL 생성] [ESL 라이브러리]      업로드 · ●실행1 ●대기0 · 사용 가이드 · v0.10.0 · 대시보드로 · 홍길동 power ┐
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ESL 라이브러리                                                                                                                                                │
│ [ESL 목록] [강성 평가 스터디] [비드 최적화] [종합분석·버전 비교] [템플릿]                                                                                       │
│ 모델[전체▾] 씬 유형[전체▾] orient[전체▾] 모드[전체▾] 판정[전체▾] □폐기 포함                                                                                   │
│ ┌ 선택 3개 · LEGACY 1 · 기준 75형 1662×948 ──────── [내보내기 (3)]■ [강성 평가 스터디 (3)]░ [비드 최적화 (3)]░ [종합분석 (3)]░ [선택 해제] ┐ ░=비활성: LEGACY 1개 │
│ ├──┬───────────┬──────────┬────────────────────┬──────┬────────────┬────────────────┬───────────────────────┤                                               │
│ │☑ │ 모델       │ 인치/크기 │ 씬                  │ 모드  │ 판정        │ 등록            │                       │                                               │
│ │☑ │ QN75…     │ 75 1662×948│ 1F 낙하 FR #3      │ 굽힘  │ PASS       │ 홍길동 10-28    │ [수정]                 │                                               │
│ │☑ │ QN75…     │ 75 1662×948│ 1C 낙하 #1         │ 뒤틀림│ LEGACY     │ 김철수 10-21    │ [수정] [재검증]        │                                               │
│ │☑ │ QN75…     │ 75 1662×948│ 1E 낙하 #2         │ 덴팅  │ PASS       │ 홍길동 10-28    │ [수정]                 │                                               │
│ │□ │ QN65…     │ 65 1440×822│ …                  │ …     │ PASS       │ …               │ [수정]                 │  (표는 table-wrap scroll, 머리글 고정)        │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
[내보내기] 창(가운데 모달, 폭 560 px):
```text
┌ 내보내기 — ESL 3개 ─────────────────────────────┐
│ LEGACY 1개 포함 — 하중은 같고 판정 체계만 이전입니다 │
│ 형식  ☑ Radioss inc (/CLOAD·/BCS)  ☑ OptiStruct fem  ☑ CSV │
│ ID 시작  ◉ 자동(rad 최대 ID 위)  ○ 지정 [        ]   │
│ 같은 모델 ESL은 ID가 겹치지 않게 이어서 배정합니다     │
│                         [닫기]  [내보내기 시작]■     │
│ ── 실행 후 ──                                        │
│ 01_QN75_1F_FR3   완료   inc·fem·csv  ID 9000001–9001234│
│ 02_QN75_1C_1     실행 중 42%                          │
│ 03_QN75_1E_2     대기                                 │
│                         [닫기]  [zip 받기]■(완료 후)  │
│ ▸ 최근 내보내기                                      │
└──────────────────────────────────────────────────────┘
```
케이스 ② (2560×1440, 기존 2열 `.wide2` 규칙):
```text
│ [①입력●] [②t*·지지점●] [③ESL○] [④검증○]          누적 배지 · 실행 이력 · [결과 받기(zip)] │
│ ② t*·지지점                                                                 [t* 확정]■      │
│ ┌ max-hold 곡선 ─────────────────────────────┐ ┌ 후보 시점 ───────────┐                    │
│ └─────────────────────────────────────────────┘ └──────────────────────┘                    │
│ ┌ hotspot ─────────────────────────────┐ ┌ 지지점 (3-2-1, 자동)  [자동] ───────────────┐     │
│ │                                      │ │ 1번(3방향) 102345 · 123                      │     │
│ │                                      │ │ 2번(2방향) 118002 · 13                       │     │
│ │                                      │ │ 3번(1방향) 120554 · 3                        │     │
│ └──────────────────────────────────────┘ │ 면적비 0.82 · 최소 거리 0.61 · 조건비 0.12   │     │
│                                          └──────────────────────────────────────────────┘     │
```

### 8.2 목업 — 1920×1080
- 라이브러리: 선택 줄은 두 줄로 줄바꿈 허용(요약 / 버튼), 표 열 '등록'은 날짜만, 동작 열 버튼은 small. 표 높이 `--tbl-max` = 100vh − 340 px. 첫 화면에 필터 + 선택 줄 + 표 8행 이상.
- 내보내기 창: 폭 min(560 px, 92vw), 진행 표는 창 안 스크롤(max 40vh).
- 케이스 ②: 1열 쌓기(곡선 → 후보 → hotspot → 지지점), 지지점 카드는 첫 화면 아래여도 됨, 주 버튼은 머리 줄 고정.
- ④ 검증: 기존 §9(esl_disp_primary) 높이 규칙 그대로, 주 버튼 라벨만 상황별.

## 9. 이름 변경 ('비드 DOE' → '강성 평가 스터디')

| 바꿈(사용자 문구) | 유지(이름·키) |
|---|---|
| 라이브러리 탭·선택 줄 버튼·`DoeList`·`DoeStudy` 제목·경로 막대, 이력 작업 라벨(`DOE_PREP` "강성 평가 준비", `DOE_PREVIEW` "강성 평가 미리보기", `DOE_RUN` "강성 평가 실행"), 상태 칩·서랍 라벨, 사용 가이드(`guide/content.ts`), `docs/manual/user.md`·`docs/manual/bead_doe_check.md` 본문, `esl/doe/report_doe.py` 보고서 제목·머리글, `resources/doe_messages.json` 문구, 백엔드 오류 메시지 중 '비드 DOE' 문자열(`services/doe.py`·`services/history.py`), `CHANGELOG.md` 새 항목 | API `/doe/*`, 작업 `DOE_*`·step `BD_*`, 테이블 `bead_does`·`jobs.bead_doe_id`, 설정 `bead_doe.*`, 폴더 `_doe/`, 오류 코드, 화면 URL `/p/:pid/doe/:id`, query `doe`, 파일명·컴포넌트명(`Doe*`), 코드 주석, 이전 CHANGELOG 항목 |
- 'DOE 행렬'·'LHS·Halton·풀 팩토리얼' 같은 방법 용어는 그대로(스터디 안의 실험계획 용어).
- 보고서 HTML에는 부제 "(이전 이름: 비드 DOE)"를 v0.10.x 동안 한 줄 둔다(이미 받은 보고서와 대조용).

## 10. 설정 키

| 키 | 위치 | 기본 | 역할 |
|---|---|---|---|
| `support.auto_check.min_area_ratio` | 코어 `config/esl.example.yaml`, 기본값 `esl/config.py SUPPORT_CHECK_DEFAULTS` | 0.10 | §5.2 (임시) |
| `support.auto_check.min_dist_rel` | 〃 | 0.15 | §5.2 (임시) |
| `support.auto_check.min_cond_ratio` | 〃 | 1.0e-3 | §5.2 (임시) |
| `support.auto_check.expand_candidates` | 〃 | true | pca8 확장 |
| `support.auto_check.rule_version` | 〃 | 1 | 기록용 |
| `library_export.max_entries` | 플랫폼 `backend/esl_platform/core/config.py` | 50 | §6.1 |
| `library_export.max_bundle_bytes` | 〃 | `ui.max_bundle_bytes` | §6.1 |
| `library_export.wait_s` | 〃 | 600 | §6.2 같은 모델 순서 대기 |
- `support.auto_check`는 선택 절: 없으면 기본값, **코어 검증 cfg에 주입하지 않음**(설정 sha256·보고서 불변 — 0.8.0 `cumulative`와 같은 방식). 숫자 리터럴은 기본값 한 곳(V-CFG-2).
- `deploy/setup_config.py`는 새 키를 보충하지 않는다(기본값 동작).

## 11. DB 변경

- **없음.** migration 추가 없음(HEAD 0011 유지). JSONB 키만 추가: `cases.tstar.support_auto`, `jobs.params.{origin, batch_id, items, options, entry_id}`, `jobs.result.registered.{batch_id, items}`·`jobs.result.revalidate`, `library_entries.quality.revalidated`.
- 파일: `<esl_root>/_exports/<batch_id>/{batch.json, <NN>_<label>/…, logs/<job_id>/…}`. 삭제 없음(정리 정책 없음 — R-MR-4).

## 12. 시험

| ID | 기준 | 방법 |
|---|---|---|
| V-MR-1 | `auto_321`: 직사각 판 → pca4 OK(area_ratio≈1), 가늘고 긴 판·L자 판에서 COLLINEAR/TOO_CLOSE 감지, 확장(pca8)으로 통과하는 형상은 OK·mode pca8, 공선 노드 → DEGENERATE, 결정적(같은 입력 같은 결과), 기존 `pick_321`·`pca_corners` 결과 불변 | 단위 |
| V-MR-2 | `PUT /tstar`: 지지 없음 → 자동 세트 생성(source auto)·`support_auto.OK`; 지지 있음(user) → 유지·KEPT; BLOCKED → 200·지지 없음·problems; 같은 t* 재확정 허용; version 충돌 409; 수동 `POST /support-sets` 검사 실패 422 SUPPORT_CHECK_FAILED·성공 MANUAL | API(PG) |
| V-MR-3 | `step_status`: input/tstar/esl/validate 각 상태(running·stale·done·failed+reason·none+reason), 기존 `stage_status` 값 불변(라이브러리 EXPORT가 `"6"`에 영향 없음) | API |
| V-MR-4 | ESL_SOLVE: BLOCKED Case → 409 missing support_set + support_blocked | API |
| V-MR-5 | 하위 호환: v0.9.0 DB 덤프(수동 지지 세트·t* auto만·⑥ 완료 Case)에서 화면·API 동작 §5.5 표대로, 지지 세트 덮어쓰기 0 | PG |
| V-MR-6 | `POST /library/exports`: Case 2개·항목 3개 → 작업 2개(같은 Case 항목은 items 2개), batch.json, 202; 오류 표 전부(INVALID_PARAMS·TOO_MANY_ENTRIES·ENTRY_NOT_FOUND·ENTRY_FILES_MISSING·CASE_JOB_BUSY 전체 롤백·403) | API(PG) |
| V-MR-7 | 워커 library 모드: Case 폴더 쓰기 0(실행 전후 Case 트리 해시 동일), 로그 `_exports/<batch>/logs/`, INPUT_CHANGED·현재 run 검사 건너뜀, 항목 일부 실패 → SUCCEEDED+warnings, 전부 실패 → FAILED EXPORT_ALL_FAILED | 워커 |
| V-MR-8 | `GET /library/exports/{id}` state 계산(QUEUED·RUNNING·SUCCEEDED·PARTIAL·FAILED·CANCELED), `GET /library/exports` 묶음 목록 | API |
| V-MR-9 | bundle: zip 구조(manifest·README·`<NN>_<label>/`), 진행 중 409 EXPORT_NOT_READY, 성공 0 409 EXPORT_FAILED, 상한 413, 경로 탈출 없음 | API |
| V-MR-10 | ID 배정: independent = 전 항목 같은 시작; per_model_sequential = 같은 topo 항목 범위 비겹침·연속, 다른 모델은 독립, 다른 Case 작업 간 순서 대기·`EXPORT_ORDER_TIMEOUT` | 워커 |
| V-MR-11 | `export_entry` 출력 inc·fem = 같은 run의 `stage_export` 출력과 바이트 동일(생성 시각 줄 제외), f_eq.csv 동일, u_rel.csv u_total 빈 열 + 경고 | 단위(골든) |
| V-MR-12 | 등록: PASS 201, FAIL·UNDETERMINED 422 VALIDATION_NOT_PASS(force_reason 있어도), LEGACY 422 VALIDATION_LEGACY | API |
| V-MR-13 | 재검증 API 오류 순서·코드(ENTRY_NOT_FOUND·ENTRY_RETIRED·ENTRY_NOT_LEGACY·CASE_ARCHIVED·RUN_SNAPSHOT_MISSING·EXTRACT_CHANGED·CASE_JOB_BUSY), 비현재 run 재검증 시 스냅샷 되돌림 경고, CASE_REPORT 자동 큐 없음 | API·워커 |
| V-MR-14 | 전환: PASS → quality 갱신·revalidated·validation_id·version+1, entry 폴더 불변(해시); FAIL → 불변·KEPT_LEGACY; 그사이 폐기 → ENTRY_CHANGED | 워커(PG) |
| V-MR-15 | 게이트: opt·doe·analysis에 LEGACY entry_id → 422 ENTRY_NOT_ELIGIBLE, 필터 분석은 excluded_ineligible, 기존 분석·실행 조회 불변 | API |
| V-MR-16 | `EntryOut.eligible·ineligible_reason·revalidate_block·revalidate_job`, 목록 쿼리 수 상수(N+1 없음) | API |
| V-MR-17 | 라우트: 옛 `/stage/1..6`(query 유지)·`?tab=doe|comparisons`·`/doe`·`/opt` 리다이렉트, 이력 링크 stepOfStage 매핑 | 프런트 |
| V-MR-18 | 상단 메뉴 2개·활성 규칙·경로 막대, 스텝퍼 4단계, Stage3·Stage6 없음, 케이스 헤더 [결과 받기(zip)] 유지 | 프런트 |
| V-MR-19 | ②: 주 버튼 활성 조건(지지 없음이면 같은 t*라도 활성), 지지 카드 3상태(자동·사용자 지정·BLOCKED problems), OK·KEPT일 때 편집 입력칸 없음, BLOCKED일 때만 '고급' 접힘 칸 → 저장·422 problems 표시 | 프런트 |
| V-MR-20 | ④: 주 버튼 상황별(검증 실행 / 라이브러리에 등록), FAIL·판정 불가·LEGACY 등록 비활성 사유, 사유 대화상자 없음 | 프런트 |
| V-MR-21 | 라이브러리: 탭 5개 이름, 선택 자유(폐기만 불가), 동작별 비활성 사유(LEGACY·크기), [종합분석]→`analyses/new?entries=` | 프런트 |
| V-MR-22 | 내보내기 창: 형식·ID 옵션 → 요청 본문, 진행 폴링, [zip 받기], 실패 사유 표, 최근 내보내기 | 프런트 |
| V-MR-23 | LEGACY 행: 배지·[재검증]·진행 칩·PROMOTED/KEPT_LEGACY 안내·비활성 툴팁 | 프런트 |
| V-MR-24 | 이름: 화면·가이드·보고서·doe_messages·이력 라벨에 '비드 DOE' 0건(이전 CHANGELOG·주석·코드 식별자 제외 — 정적 검사 스크립트), API·DB 이름 불변 | 정적·단위 |
| V-MR-25 | 설정: support.auto_check·library_export 기본값, 예시 yaml 로드, 코어 cfg 해시 불변(support.auto_check 미주입), V-CFG-2 | 단위·정적 |
| V-MR-26 | 화면 크기: 2560×1440·1920×1080에서 라이브러리 첫 화면(필터+선택 줄+표 8행), 내보내기 창 잘림 없음, ② 주 버튼 보임, 가로 스크롤 없음 | Playwright 실서버 |
| V-MR-E2E | 실서버: 새 Case → ① → ② 확정(자동 지지) → ③ → ④ PASS → 등록 → 라이브러리 3개 선택 → 내보내기 → zip 열어 inc·fem 확인 → LEGACY 항목 재검증 → PASS 전환 | `scripts/e2e_menu.mjs` (PG+backend+워커+빌드 프런트) |

## 13. 구현 분해 · 파일 소유

순서: **MR1 코어 → (MR2 백엔드 ∥ MR3 워커) → 통합**, **MR4 프런트는 mock으로 처음부터 병렬**, MR5 문서·배포는 마지막. 접점은 §5.1·§5.4·§6.1·§6.2·§7.2~7.5의 JSON 키뿐.

| 단위 | 소유 파일 |
|---|---|
| **MR1 코어** | `esl/mech/supports.py`(`auto_321`, 수동 3노드용 `check_321(X0, idx, cfg)` — 같은 검사), `esl/export/from_entry.py`(신규), `esl/export/__init__.py`(필요 시 헬퍼 이동만, 동작 불변), `esl/config.py`(`SUPPORT_CHECK_DEFAULTS`), `config/esl.example.yaml`(주석 절), `esl/doe/report_doe.py`(문구), `resources/doe_messages.json`(문구), `tests/mech/test_support_auto.py`·`tests/export/test_from_entry.py`(골든) |
| **MR2 백엔드** | `backend/esl_platform/api/services/cases.py`(put_tstar·step_status·suggest), `api/services/jobs.py`(EXPORT library·VALIDATE revalidate params, ESL_SOLVE support_blocked), `api/services/library.py`(등록 규칙·revalidate·eligible·게이트·overlay quality), `api/services/library_export.py`(신규: 묶음 생성·조회·목록·bundle), `api/routers/library.py`(라우트 4개), `api/services/opt.py`·`api/services/doe.py`(게이트 + 문구), `api/services/history.py`(라벨·EXPORT 라이브러리 요약·links), `api/services/bundle.py`(export_files 헬퍼), `api/schemas.py`(StageStatus.reason, CaseOut.step_status, ExportBatch*, EntryOut 키, Revalidate), `core/config.py`(`library_export`), `core/paths.py`(`EXPORTS_DIR = "_exports"`), `worker/esl_worker/core_adapter.py`(`auto_support`, `export_items` 래퍼), `docs/contracts/openapi_p1b.json`(재생성), `backend/tests/test_menu_restructure*.py` |
| **MR3 워커** | `worker/esl_worker/executor.py`(library 모드 폴더·로그·검사 건너뜀, revalidate 사전 재확인, 자동 보고서 제외), `worker/esl_worker/child.py`(EXPORT library 자식 진입점), `worker/esl_worker/register.py`(EXP_REGISTER library, VAL_REGISTER 전환), `worker/esl_worker/lib_jobs.py`(필요 시 폴더 헬퍼 공유), `worker/tests/test_lib_export.py`·`test_revalidate.py` |
| **MR4 프런트** | `frontend/src/app/App.tsx`(라우트·리다이렉트 컴포넌트), `shell/Shell.tsx`(메뉴 2개), `shell/StageStepper.tsx`(4단계·step_status), `pages/CasePage.tsx`, `stages/Stage2.tsx`(지지 카드 + BLOCKED 때만 '고급' 접힘 칸), `stages/Stage4.tsx`·`Stage5.tsx`(제목·번호·주 버튼·등록), `stages/common.ts`(blockReason step_status), `stages/Stage3.tsx`·`Stage6.tsx`(삭제), `components/LibraryRegister.tsx`, `components/SupportSummary.tsx`(신규), `components/ExportDialog.tsx`(신규), `pages/library/LibraryList.tsx`(탭·선택 줄·재검증), `pages/library/AnalysisNew.tsx`(`?entries=`), `pages/doe/*`·`components/Doe*`·`view3d/View3DCard.tsx`(문구), `pages/opt/OptList.tsx`(문구), `pages/history/JobReview.tsx`, `api/history.ts`(stepOfStage·라벨), `api/library.ts`(신규: exports·revalidate 호출·타입 — `types.ts`엔 CaseOut·EntryOut 키만 추가), `api/types.ts`, `pages/guide/content.ts`·`Guide.tsx`, `mock/**`, `__tests__/menu_restructure.test.tsx`, `styles.css`, `scripts/check_api*`(대조 목록에 library.ts) |
| **MR5 문서·배포** | `docs/manual/user.md`(메뉴·단계·내보내기·재검증), `docs/manual/admin.md`(설정 8개), `docs/manual/bead_doe_check.md`(문구), `CHANGELOG.md`·`VERSION`(0.10.0), `docs/e2e-checklist.md`, `scripts/e2e_menu.mjs`, `deploy` 수집 목록(새 파일 `esl/export/from_entry.py` 포함 확인) |

## 14. 리스크

| ID | 내용 | 대응 |
|---|---|---|
| R-MR-1 | 지지 자동 선택이 BLOCKED이면 편집 UI가 없어 사용자가 막힘(비대칭·L자·구멍 많은 파트) | pca8 확장 탐색, 사유·기준값 표시, BLOCKED일 때만 '고급 — 지지 노드 직접 지정'(Q2 B, 같은 품질 검사) |
| R-MR-2 | 다중 내보내기가 Case 단위 작업 제약을 물려받음 — 같은 Case에 다른 묶음이 진행 중이면 409, 같은 Case 작업과 직렬 | LIGHT 레인·짧은 작업, 409에 case_ids 표시, 창에 "잠시 후 다시" 안내 |
| R-MR-3 | 라이브러리 CSV가 ⑥ CSV와 다름(u_total 비움, tstar 후보·hotspot 없음) | README·경고 1줄, Case [결과 받기(zip)] 안내 |
| R-MR-4 | `_exports/` 누적 용량(정리 없음) | 묶음당 수십 MB, admin 문서에 위치 안내, 정리 정책은 후속 |
| R-MR-5 | 재검증 불가(추출 바뀜·스냅샷 없음·보관) LEGACY는 영구히 게이트에 막힘 | revalidate_block 사유 표시, "Case 다시 계산 → 새 등록 → 옛 항목 폐기" 안내 |
| R-MR-6 | 재검증 PASS 후 DB quality와 entry.json quality 불일치 | 판정 원본 = DB로 명시, overlay에 quality 추가, entry.json은 하중 원본으로만 사용 |
| R-MR-7 | 재검증이 비현재 run을 Case 폴더 04_esl로 되돌림 — 이후 화면·보고서가 디스크를 직접 읽으면 혼동 | 기존 ensure_on_disk 경로(검증·내보내기)만 사용, CASE_REPORT 자동 큐 제외, V-MR-13 |
| R-MR-8 | 같은 모델 항목이 서로 다른 Case 작업에 있으면 작업 간 대기(lease 점유) | wait_s 상한·EXPORT_ORDER_TIMEOUT, 같은 모델은 대개 같은 Case 묶음 |
| R-MR-9 | 옛 `/stage/n` 외부 링크(메신저·문서)의 번호 의미 변화 | 경로 이름을 `/step`으로 바꿔 충돌 없음 + 리다이렉트 |

## 15. 확정 (2026-10-29, 사용자 확정 — 이전 미결 Q1~Q3)

| 질문 | 확정 | 반영 |
|---|---|---|
| Q1 이미 사유와 함께 등록된 FAIL·판정 불가 항목(scheme 있음) | **A** — LEGACY와 동일: 유지 + 배지, 강성 평가·비드 최적화·종합분석 선택 불가(`eligible=false`, 422 `ENTRY_NOT_ELIGIBLE`), [재검증] 가능 | §7.3 대상, §7.4 전환, §7.5 게이트, §8 필터 |
| Q2 자동 지지 BLOCKED 탈출구 | **B** — BLOCKED일 때만 ②에 접힌 '고급 — 지지 노드 직접 지정'(노드 ID 3칸, 기존 `POST /support-sets` 재사용, 같은 품질 검사 → 422 `SUPPORT_CHECK_FAILED`) | §5.1, §5.3, V-MR-2·V-MR-19 |
| Q3 다중 내보내기 ID 배정 | **B** — 같은 모델(topo_sha256) ESL끼리 겹치지 않게 연속, 다른 모델은 독립(`id_policy` 기본 `per_model_sequential`) | §6.1, §6.2, §6.3, V-MR-10 |

## 16. 변경 메모
- (작성 2026-10-29) 초안.
- (2026-10-29) 사용자 확정 Q1 A·Q2 B·Q3 B → 상태 확정.
- (2026-10-29, 통합 v0.10.0) 구현 정합 반영: §6.2 같은 모델 연속 배정 순서 = Case 작업 순서 → 선택 순서(근거: LIGHT 레인 교차 대기·시간 초과 회피), §7.4 `jobs.result.revalidate.fail_reasons` 추가, `revalidate_block.message`, §6.1 목록 행 모양·`ui.library_export_max_entries`. §5.1 수동 지정 품질 검사, §5.3 고급 칸, §7.3 대상, §8 필터, §6 ID 정책 반영.
- (2026-10-29, 검증 지적) §7.5 게이트는 생성뿐 아니라 복제·재시도·스터디 다음 단계 작업에도 적용(저장된 entry_ids 재검사, 422 ENTRY_NOT_ELIGIBLE). §6.2 워커 쓰기 = <batch>/.<label>.part-<uuid>/ → rename 공개, 경로 링크·realpath 검사(PATH_UNSAFE). origin=library EXPORT 재시도 = EXPORT 단계부터.
- (2026-10-29, 사용자 확정) 강성 평가 스터디 결과에 ESL별 개선 지표(worst_ratio·min_improvement·all_improved·n_improved/n_worsened·geo_mean_improvement·pareto, per_esl) — 정의·API·화면은 `esl_bead_doe.md` §11.4. 근거: 최악 ESL 절대 max 점수는 한 씬의 문제가 다른 씬으로 옮겨가는 상황을 못 본다.
- (2026-10-29, 사용자 확정) 라이브러리 [내보내기] 기본 숨김: 플랫폼 설정 `ui.library_export_enabled`(기본 false, `GET /version` ui 로 전달) — false 면 선택 줄 [내보내기]·창 숨김(강성 평가 스터디가 주 버튼), `/library/exports` API 4개는 유지하되 전역 관리자만(그 외 403 `EXPORT_DISABLED`). 코드·시험은 유지(true 에서 §6 그대로). 413 경로 안내는 추가하지 않음. 근거: 비드 최적화·강성 평가 스터디가 플랫폼 안에서 수행되어 수작업 외부 계산 용도가 사라짐.
