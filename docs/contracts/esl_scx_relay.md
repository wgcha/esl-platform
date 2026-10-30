# 계약: 대시보드 SCX 릴레이 사용 — A) SCX 드라이브에서 고르기 · B) Radioss 검증 낙하 (v0.11.0)

- 상태: **확정** (2026-10-30, 사용자 확정 Q1 A·Q2 A·Q3 A + Q4 씬 선택 — §17). 구현 코드 없음. 이 문서가 구현·검증의 원본이다.
- 버전: **v0.11.0** (기준 main v0.10.1 `3b71469`).
- 참고(읽기 전용): physicsai-platform `release/v0.2.14` `a363a89e8f93d3acfe90a9601318bf4f6cade0a7` — `docs/contracts/scx_relay.md`(릴레이 정본 v1, 이하 **RL**), `s20_scx_version.md`(버전 입력), `packages/simdash_adapters`(0.1.0, 표준 라이브러리만).
- 대체 범위: `esl_p3_ux.md` §7(범위 밖 "검증 낙하 Radioss·HPC 제출")을 이 계약으로 일부 해제(검증 낙하만 — OptiStruct HPC 제출은 여전히 범위 밖). 새 Case 탭 3개 → 4개(`esl_p3_ux.md` §1). 충돌 시 이 문서 우선.
- ID 규칙: 결정 `SR-D-n`, 시험 `V-SR-n`, 리스크 `R-SR-n`.

## 0. 사용자 확정 · 배경 (변경 금지)

1. 모든 플랫폼(대시보드·physicsai·esl)이 **한 Windows 서버**. 대시보드는 상시 가동(관리자 책임). esl 로그인은 기존대로 대시보드 계정(세션 쿠키 introspection).
2. SCX 연결은 **대시보드 릴레이**(RL)를 쓴다 — esl 은 SCX 어댑터·토큰을 갖지 않는다. 릴레이 = 대시보드 loopback 내부 HTTP `/internal/scx-relay/v1`, 헤더 `X-SCX-Relay-Key`(공유 비밀) + `X-SCX-Relay-Client: esl`.
3. 재사용 = physicsai `packages/simdash_adapters`(위 커밋)를 **esl 저장소에 wheel 동봉 + lock 고정**(v0.10.1 paicad 방식, 정규화 sha256). physicsai 워커 코드(physicsai_core 의존)는 복사하지 않고 esl 이 오케스트레이션을 새로 쓴다.
4. 기능 A(1순위) = SCX 드라이브에서 rad(+include 자동)·h3d 를 골라 esl 업로드 폴더로 내려받아 기존 흐름으로 Case 생성. **드라이브 쓰기 없음.**
5. 기능 B(2순위) = 강성 평가 스터디 **① 같은 모델**의 최적 안(또는 고른 안) 모핑 Ch/R include + 원 Case rad 세트를 SCX 에 올려 Radioss 실행 → 결과 회수 → 기존 추출로 원 낙하 대비 변위·변형률 비교. **②③ 시나리오는 범위 밖**(원 모델에 다른 형상을 넣을 수 없음).
6. 원칙: 필수 UI만, 2560×1440·1920×1080(잘림·가로 스크롤 없음, 화면당 주 버튼 1개), 하드코딩 금지(설정), 쓰기는 esl 이 소유한 폴더만, 경로·심링크 검사 재사용, **외부 명령 없음(HTTP 만)**, 릴레이 꺼짐·대시보드 다운 시 해당 탭·버튼만 비활성 + 사유.

## 1. 현황 조사 (main 3b71469 + physicsai a363a89)

| 항목 | 위치 | 이 계약에 주는 영향 |
|---|---|---|
| 릴레이 읽기 범위 | RL §4: 읽기 = `SIMDASH_SCX_RELAY_DRIVE_BASE` 아래 + relay 가 기록한 잡의 `output_rel` 아래, **SPDM 마스터 루트(`SIMDASH_SCX_DRIVE_ROOT`) 읽기·쓰기 금지**, 첫 구간 `.` 금지 | A 의 탐색 범위는 공용 계정 홈(`/Users/vd.dashboard`)의 릴레이 기준 폴더 안뿐(Q1) |
| 릴레이 쓰기 | RL §5.2·5.3: 대시보드 업로드 대기열(MKDIR+FILE, 덮어쓰기·삭제·이동 없음, 202 비동기, 묶음 폴링), 파일 업로드 대상 폴더 = 기준 아래 깊이 ≥ 2 | B 는 `<drive_base>/<프로젝트>/<잡 폴더>/` 에만 쓴다 |
| 다운로드 | RL §5.6: 대시보드가 SCX → 자기 임시 폴더로 **전부 받은 뒤** 스트리밍, `X-Content-SHA256`, **Range 없음**, 상한 `SIMDASH_SCX_RELAY_MAX_DOWNLOAD_BYTES` 기본 20 GiB | 바이트 단위 이어받기 불가(SR-D-7), 30 GB h3d 는 대시보드 상한 상향 필요(R-SR-3) |
| 제출 | RL §5.7: `request_id` 멱등 replay, `SUBMISSION_UNKNOWN` = 사람 확인, `/submissions/{rid}/resolve`(attach·abandon), 모든 경로 = input_path 부모 폴더 아래 | B 의 request_id 영속·UNKNOWN 처리(SR-D-11), include 배치 제약(SR-D-14) |
| 어댑터 클라이언트 이름 | `simdash_adapters.hpc.scx.ScxHpcGateway._load_secret` 가 `ScxRelayClient(...)` 를 `client_name` 없이 만듦 → 헤더 `physicsai` 고정 | esl 은 얇은 하위 클래스로 `esl` 을 넣는다(SR-D-3) |
| 어댑터 버전 | wheel 버전 `0.1.0` 이지만 scx 코드는 CHANGELOG "미배포(0.1.0 유지)" | 동일성은 lock 의 **커밋 + 정규화 sha256** 으로만 판정(SR-D-2) |
| 시험 가짜 | `packages/simdash_adapters/tests/fake_scx_relay.py`(표준 라이브러리, 510줄) | esl 시험에 출처 머리말과 함께 사본(수정은 esl 사본에서만) |
| 새 Case 탭 | `frontend/src/pages/newcase/NewCase.tsx` `TABS = upload·server·pc`, `InputSelection{rad_path, source, parts, ok}` | 4번째 탭 `scx` 가 같은 `InputSelection` 을 낸다 |
| 업로드 세션 | `uploads`(files JSONB: rel·size·sha256·done·client…), `inspect_upload`(rad 파싱·include 해석·h3d 검사), `cleanup_stale`(OPEN 72 h → `_backup`) | A 는 업로드 세션을 그대로 쓰고 files[] 키만 더한다(migration 은 jobs 쪽만) |
| include 수집 | `esl.rad.parser.scan_include_refs`(재귀 깊이 `case.rad_include_max_depth`, 상태 파일 `.sta/.str` 포함) | A 워커가 내려받은 rad 로 반복 수집 |
| ① 산출물 | `esl_bead_doe.md` BD-D-17·18: `best/<did>/`(순위 1 + 상위 `paicad.keep_files_top`=3) = paicad check 통과 `out_files/<rel>`(조립 폴더 = 기준 Case 입력 폴더 기준 상대, `/NODE` 좌표만 바뀐 파일) | B 대상 안 = `best/` 가 있는 안(Q2) |
| 워커 레인 | `jobs.lane IN ('SLOT','LIGHT')`, SLOT = `worker.slots`(2), LIGHT 1개 FIFO | 수 시간 HTTP 대기 작업이 SLOT·LIGHT 를 막지 않게 새 레인 `XFER`(SR-D-9) |
| migration | HEAD `0011`(down 0010), 0009 = MCP 예약(구현 시점 HEAD 뒤) | 이 계약 = `0012`(down 0011), 0011 CHECK 고정 상수화(SR-D-17) |

## 2. 범위 / 비범위

| 범위 (v0.11.0) | 비범위 |
|---|---|
| A: 드라이브 탐색(릴레이 list), rad + include 폐포 + 엔진 rad + h3d 내려받기(sha256), 업로드 세션 → 기존 complete·Case 생성 | 드라이브 쓰기·삭제·이동(A), 결과 폴더(done.json) 내려받기, 바이트 이어받기(Range) |
| B: ① 같은 모델 안 1개 × 낙하 씬 1~`max_scenes` 개(씬마다 별도 제출, Q4), 올리기 → 제출 → 폴링 → h3d·out 회수 → 서버 추출 → 비교 카드·CSV | ②③ 시나리오, 누적 씬(상태 파일 사용 Case — 연쇄 실행은 후속), 여러 안 일괄 제출, OptiStruct HPC 제출, 검증 결과의 자동 Case·ESL 등록(Q3), 드라이브 정리 |
| 공통: 연결 계층(설정·비밀·마스킹·헬스·오류 문구), 새 레인 XFER, migration 0012, wheel 동봉 | 대시보드 저장소 변경(릴레이 Range·읽기 범위 확장은 후속 요청 §16) |

## 3. 결정 (SR-D-n)

| ID | 결정 | 근거 |
|---|---|---|
| SR-D-1 | **연결 계층 1곳**: `backend/esl_platform/core/scx/`(백엔드·워커 공용) — 설정 변환, 게이트웨이 생성(프로세스당 1개, 지연 생성), 헬스 TTL 캐시, 오류 → 사용자 문구, 마스킹, 드라이브 경로 규칙. 백엔드는 **가벼운 호출만**(health·list·resolve), 내려받기·올리기·제출·폴링은 **워커 작업만** | 요청 스레드에서 GB 전송 금지, A 의 계층을 B 가 그대로 씀 |
| SR-D-2 | `simdash_adapters` = `deploy/wheels/simdash_adapters-0.1.0-py3-none-any.whl` + `deploy/simdash_adapters.lock`(paicad.lock 과 같은 키, `subdir` = `packages/simdash_adapters`, `console_script` null, `runtime_requires` []). 동일성 = lock `commit`·정규화 `sha256`. 런타임 확인 = `import simdash_adapters.hpc` + `ScxHpcGateway`·`ScxRadiossRequest` 존재(없으면 `SCX_ADAPTER_MISSING`, 해당 기능만 비활성) | v0.10.1 방식, 0.1.0 버전 문자열은 scx 포함 여부를 말해 주지 않음 |
| SR-D-3 | **클라이언트 이름 `esl`**: `EslScxGateway(ScxHpcGateway)` 가 `_load_secret` 만 재정의해 `ScxRelayClient(..., client_name=cfg_client)`(설정 `hpc.scx.client_name`, 기본 `"esl"`, `^[a-z0-9_-]{1,32}$`). 비공개 메서드 의존은 lock 고정 + 시험(V-SR-2 헤더 값 검사)으로 묶고, physicsai 에 `client_name` 인자 추가를 후속 요청(§16) | 릴레이 감사·대기열 `requested_by` 구분. 어댑터 수정 금지(읽기 전용) |
| SR-D-4 | **설정 키 이름은 physicsai `hpc.scx.*` 와 같게**(관리자가 블록을 복사) + esl 추가 키 `client_name`. 기능 키는 `scx_drive.*`(A)·`verify_drop.*`(B). 기본 꺼짐(`enabled: false`) | 두 플랫폼 운영 일관성 |
| SR-D-5 | **탐색 범위 = 설정 `scx_drive.roots[]`**(릴레이 기준 상대 경로 + 이름 + 선택 `projects`) 안만. 서버 쪽에서 매 요청 `rel_problem`·`forbidden_reason`(health 의 `forbidden_prefixes`·`relay_base`)·루트 포함 검사. 사용자별 범위는 두지 않음 — SCX 는 공용 계정 1개라 사용자 구분 수단이 없고, 권한은 esl 프로젝트 역할(power 이상) + 루트별 프로젝트 제한으로 충분. 누가 무엇을 받았는지는 esl `jobs`(created_by)·업로드 행에 남음 | 거짓 보안 회피, 감사 가능 |
| SR-D-6 | **A 저장 위치 = 기존 업로드 세션**: `POST /scx/fetches` 가 `uploads` 행(OPEN, 본인 폴더 `<upload_root>/<user>/<UTC>_<이름>/`)과 `SCX_FETCH` 작업을 한 트랜잭션에 만든다. 파일은 `rad/…`(include 공통 조상 기준 상대 배치 — 원문 수정 없이 `../` include 유지)·`h3d/<이름>.h3d`. 끝나면 워커가 기존 `inspect_upload` 를 실행해 `uploads.result` 저장(ok 면 COMPLETED). 이후는 기존 `?upload=` 화면·`POST /cases` 그대로 | 업로드 폴더 규칙·경로 검사·Case 생성 재사용, 쓰기 = upload_root 아래 세션 폴더만 |
| SR-D-7 | **이어받기 = 파일 단위만**: sha256 확인이 끝난 파일은 재시도에서 건너뜀(크기·sha 기록), 받다 끊긴 파일은 `.part` 를 `_backup` 이 아니라 **덮어 새로 받음**(워커가 만든 자기 임시 파일). 재시도 가능한 오류(전송 오류·`DRIVE_BUSY`·`DRIVE_TIMEOUT`·`DRIVE_UNAVAILABLE`·`DRIVE_STAGING_FULL`·`HASH_MISMATCH`)는 파일마다 `scx_drive.file_retries`(2)회, 대기 `retry_wait_s`(30) | 릴레이에 Range 없음(RL §5.6). 대시보드 Range 지원은 후속(§16) |
| SR-D-8 | **include 폐포는 워커가 계산**: rad 를 먼저 받고 `scan_include_refs`(로컬 사본) → 못 찾은 참조를 "참조한 파일의 드라이브 폴더 기준 상대"로 드라이브 경로화 → 같은 루트 안이면 받고 다시 스캔(깊이 `case.rad_include_max_depth`, 파일 수 `scx_drive.max_files` 2000). 절대경로(`C:\…`)·루트 밖·드라이브에 없음 = 받지 않고 `missing_includes` 로(기존 complete 표시 → 사용자는 SCX 패널의 [추가로 올리기]로 같은 세션에 추가). 엔진 rad(`<stem>_0001.rad`…, 패턴 `scx_drive.engine_globs`)가 같은 폴더에 있으면 함께 받음(B 에 필요) | 백엔드는 list 만(가벼움), 상태 파일 `.sta/.str` 도 include 라 자동 |
| SR-D-9 | **새 레인 `XFER`**: HTTP 전송·원격 대기 작업(SCX_FETCH·VERIFY_DROP) 전용, 루프 수 `worker.xfer_lanes`(기본 2, 1~8), 자식 프로세스·자원 제한기 없음(워커 스레드 + 스트리밍), lease 갱신·취소 확인은 청크·폴링마다. 계산(추출·비교)은 SLOT 작업 `VERIFY_POST` 로 분리해 VERIFY_DROP 이 끝날 때 같은 트랜잭션에서 큐 | 수 시간 SCX 대기가 SLOT(2)·LIGHT(1)를 막지 않음, 계산 자원 규칙 유지 |
| SR-D-10 | **B 대상** = 강성 평가 스터디 `scenario='same'`, phase DONE, `best/<did>/` 가 있는 안(순위 1~`paicad.keep_files_top`, Q2 A) × **낙하 씬 = 실행 시 사용자 선택(Q4)**: (A) **가장 나쁜 씬 N개** — 그 안의 ESL별 개선율 r_{d,i}(v0.10.0 §11.4, 비 = C_{d,i}/C_{d000,i}) **큰 순**(가장 덜 개선·악화 먼저, 동률 = entry_id 순), N 입력 기본 3 / (B) **스터디에서 고른 ESL 전부**. 씬 = ESL 항목의 출처 Case(같은 Case 의 ESL 이 여럿이면 r 최대 1개로 합침). 합계 ≤ `verify_drop.max_scenes`(기본 5, 넘으면 422 `VD_TOO_MANY_SCENES`). **씬마다 `verify_drops` 행 1개·VERIFY_DROP 1개·별도 Radioss 제출**, 한 번 요청한 행들은 `batch_id` 로 묶음. 같은 (스터디, 안, Case) 비종료 검증은 1개(겹치면 그 씬만 건너뛰고 경고 `VD_ALREADY_ACTIVE`) | ①만 원 모델 rad 에 형상 대입 가능(사용자 확정 5), 씬별 최악 확인(Q4) |
| SR-D-11 | **제출 기록 영속**: 새 표 `scx_submissions`(request_id PK). 순서 = (1) 행 `SUBMITTING` 커밋 → (2) `submit_radioss`(어댑터가 같은 request_id 로만 replay) → (3) `SUBMITTED`(scx_job_id)·`UNKNOWN`·`FAILED`. request_id = `esl-vd-<verify_drop_id>-a<attempt>`. 워커 재시작·재시도 시 `SUBMITTING` 행은 **같은 request_id 로 다시 보냄**(릴레이 replay — 원격 중복 없음), `UNKNOWN` 은 자동 진행 금지 → 작업 FAILED `SCX_SUBMISSION_UNKNOWN` + 화면 [잡 ID 연결]·[포기](`/resolve` → 릴레이 resolve). 포기 후 재시도 = 새 attempt(새 request_id) | RL §1.4·§5.7·§5.10 |
| SR-D-12 | **B 드라이브 폴더** = `hpc.scx.drive_base`(기본 `"~/esl"`) 아래 `<프로젝트 구간>/VD<no>_<UTC yyyymmddTHHMMSS>`(어댑터 `ensure_new_dir`, `scx_naming.sanitize_project`). 기준은 health `relay_base` 안이어야 함(아니면 `SCX_BASE_OUTSIDE_RELAY`). 항상 새 폴더, esl 은 지우지 않음 | RL §0 "잡 폴더는 항상 새로" |
| SR-D-13 | **B 파일 세트 = 원 Case 입력 사본 + 노드 ID 기준 좌표 패치(Q4)**: 원 Case rad(starter) + include 폐포(Case 와 같은 `scan_includes`) + 엔진 rad(`verify_drop.engine_globs`, 없으면 그 씬 제외 + 경고 `VD_ENGINE_MISSING`). 모핑 좌표 = `best/<did>/` 사본에서 대상 파트(Ch/R) 노드 `{node_id: xyz}`(`esl.doe.nodes` 재사용). 세트의 모든 파일에서 `/NODE` 블록의 그 node_id 줄만 좌표 필드를 고쳐 쓴다(Ch/R 노드가 **어느 include 에 있든**, ID·다른 줄·다른 카드 불변, 고정폭 I10+F20×3 — 원 줄이 공백 구분이면 같은 형식, 값 `%20.13E`). 바뀐 파일만 `_verify/<id>/stage/<rel>` 에 쓰고 나머지는 원본을 그대로 올림. 세트에서 못 찾은 Ch/R 노드가 있으면 그 씬 실패 `VD_NODES_MISSING`(개수·상위 10). 각 파일 sha256·크기·source(orig|patched)·패치 줄 수 기록(`verify_drops.files`) | 씬마다 include 구조가 달라도 같은 형상, 노드 ID 불변 모핑(BD-D-10) |
| SR-D-14 | **배치 제약**: 릴레이는 모든 경로가 starter 부모 폴더 아래여야 함 → include 가 rad 폴더 밖(`../`)·절대경로·`include_path_map` 사용이면 409 `VD_INCLUDE_LAYOUT`(목록 표시). rad 폴더 기준 상대 배치를 그대로 올림(원문 수정 없음) | RL §5.7 검증, 덱 재작성 위험 회피 |
| SR-D-15 | **누적 씬 제외(Q4)**: include 그래프에 상태 파일(`.str`·`.sta`, `esl_cumulative_input.md` §2 판정)이 있는 Case 는 씬 후보에서 **제외 + 경고** `VD_CUMULATIVE_EXCLUDED`("이전 런 상태를 쓰는 누적 씬은 검증 낙하 대상이 아닙니다 — 연쇄 실행은 후속"). 화면 목록에 회색 + 사유, 남은 씬이 0 이면 409 `VD_NO_SCENES` | 상태 좌표가 모핑을 덮고 연쇄 런이 필요(후속) |
| SR-D-16 | **비교 = 정보 표시(PASS/FAIL 없음, Q3 A)**: 같은 추출 TCL·설정으로 검증 h3d 를 서버 추출(`H3D_EXTRACT` 재사용) → 코어 `esl.verify.compare` 가 원 Case `01_extract` 와 대조. 대상 파트 요소 ID 집합·연결이 다르면 `VD_TOPOLOGY_MISMATCH`. 지표 §9.3, 판단 = 개선(비 < 1−tol)·악화(> 1+tol)·비슷(`verify_drop.compare.same_tol` 0.02) + ESL 선형 예측 비 r(해당 ESL)과 방향 일치 여부 | "기존 추출·비교로", 선형 예측의 낙하 타당성 확인이 목적 |
| SR-D-17 | **migration 0012**(down `0011`): jobs `upload_id`·`verify_drop_id`, 표 `verify_drops`·`scx_submissions`, CHECK 교체(job_type +3, stage 1~13, lane +XFER, subject, artifacts kind +VERIFY_RESULT). **0011 수정**: 0011 이 `tables.CK_*`(현재 정의)를 쓰던 것을 0011 시점 고정 상수(`*_0011`)로(BD-D-21 의 0010 수정과 같은 규칙). MCP 예약 0009 는 계속 "구현 시점 HEAD 뒤"(지금 기준 down `0012`) | 단일 head, 0008·0010·0011 운영 DB 업그레이드 |
| SR-D-18 | **비밀**: `hpc.scx.secret_file` = 절대경로(대시보드 `SIMDASH_SCX_RELAY_SECRET_FILE` 과 같은 파일을 가리켜도 됨 — 같은 PC·같은 서비스 계정일 때 권장, 복사 금지 권장). 값은 프로세스 메모리에만, 로그 필터에 등록해 `***` 로 바꿈(어댑터 `on_secret` 콜백), 응답·작업 로그·failure_message·설정 응답(`redacted_settings`)에 경로만. 환경 점검: 파일 형식(`read_secret_file`)·Windows ACL(Everyone·Users·Authenticated Users 읽기 허용이면 경고 `SCX_SECRET_ACL_WIDE`) | RL §3 비밀 취급 |
| SR-D-19 | **비활성 판정 1곳**: `GET /scx/status`(헬스 TTL `hpc.scx.health_ttl_s` 30 s 캐시) → 기능별 `enabled`·`reason_code`·`reason`. 원인 순서: 설정 꺼짐 → 어댑터 없음 → 설정 오류 → 비밀 문제 → 릴레이 연결 실패(대시보드 다운) → `RELAY_DISABLED`·`DRIVE_MODE_DISABLED` → (A) 루트 0개 / (B) `writes_active=false`·`job_api=false`·`appliance` 미설정. 화면은 이 값으로 탭·버튼만 비활성 + 사유 | 사용자 확정 6 |

## 4. 데이터 흐름 · 폴더

```
A) SCX 드라이브에서 고르기
 브라우저 ─GET /scx/browse──▶ 백엔드 ─GET /list──▶ 릴레이(대시보드) ─▶ SCX 드라이브(공용 계정 홈, roots 안)
 브라우저 ─POST /scx/fetches─▶ 백엔드: uploads 행(OPEN) + jobs SCX_FETCH(XFER) 커밋
 워커(XFER) SF_RAD : rad → <up>/rad/<rel>.part → sha 대조 → rename → include 스캔 → 반복(SR-D-8) + 엔진 rad
           SF_H3D : h3d → <up>/h3d/<name>.h3d.part (진행률·취소) → sha 대조 → rename
           SF_REGISTER : inspect_upload → uploads.result(ok → COMPLETED)
 브라우저: 기존 complete 결과(파트·누락 include) → [Case 만들기] = 기존 POST /cases
   <up> = <upload_root>/<user>/<UTC>_<이름>/{rad/…, h3d/…}       ← esl 이 쓰는 곳은 여기뿐

B) Radioss 검증 낙하
 브라우저 ─POST /verify-drops─▶ 백엔드: 씬 선택·검사(SR-D-10·13·14·15) + 씬마다 verify_drops 행 + VERIFY_DROP(XFER)
 워커(XFER) VD_PREP   : 파일 세트·교체·sha256 → <esl_root>/_verify/<id>/stage.json (원본은 읽기만, 복사 없음)
           VD_STAGE  : ensure_new_dir → 파일마다 upload(…request_id) → batch 폴링(DONE 까지)
           VD_SUBMIT : scx_submissions SUBMITTING → submit_radioss → SUBMITTED | UNKNOWN | FAILED
           VD_WAIT   : status 폴링(verify_drop.poll_s) → Completed | Failed/Aborted
           VD_FETCH  : list(output_rel) → h3d·out 내려받기 → _verify/<id>/result/
           (끝) 같은 트랜잭션에서 VERIFY_POST(SLOT) 큐
 워커(SLOT) H3D_EXTRACT(LOCAL hw, 기존) → VD_EXTRACT(코어 extract, out=_verify/<id>/work) → VD_COMPARE(코어) → VD_REGISTER
   <esl_root>/_verify/<id>/{stage.json, result/, raw/(추출 CSV), work/01_extract/, compare.json, compare.csv, logs/}
   SCX 드라이브: <drive_base>/<프로젝트>/VD<no>_<UTC>/{<starter>.rad, <engine>.rad, <include 상대 배치>…}  (+ SCX 결과 폴더)
```

- 입력 보호: 원 Case 입력 폴더·DOE `best/` 는 읽기만(VD_PREP 전후 sha·mtime 불변 — V-SR-14). `_verify/<id>/` 쓰기는 기존 `fresh_dir`·realpath ⊂ `_verify/<id>` 검사.
- `.part` 는 워커가 만든 자기 임시 파일 — 같은 세션 폴더 안에서만 열고(`O_EXCL` 아님: 재시도 때 덮어씀, 그 외 기존 `check_existing_file`·성분 링크 검사), 완료 파일은 `os.replace` 전 링크·junction 검사.

## 5. 릴레이 연동 규약

### 5.1 호출 (모두 `EslScxGateway` 경유 — `http.client` 직접 사용 금지)

| 용도 | 어댑터 메서드 | 호출 위치 | 시간 한도 |
|---|---|---|---|
| 상태 | `health()` | 백엔드 `/scx/status`(TTL 캐시)·워커 작업 시작 | 3 s(어댑터 `HEALTH_TIMEOUT_S`) |
| 탐색 | `list(rel, max_entries)` | 백엔드 `/scx/browse`, 워커 SF_RAD·VD_FETCH | `http_timeout_s` |
| 내려받기 | `download(rel, dst_part, max_bytes, on_chunk)` → (size, sha) | 워커 | `transfer_timeout_s`(첫 바이트 전 대시보드 임시 받기 시간 포함 — R-SR-3) |
| 폴더 이름 | `ensure_new_dir(parent, name)` | 워커 VD_STAGE | `http_timeout_s` |
| 올리기 | `upload(local, rel_dir, name, sha256, request_id, size, on_chunk)` → batch_id, `batch(id)` | 워커 VD_STAGE | `transfer_timeout_s` / `stage_poll_s`·`stage_timeout_s` |
| 제출 | `submit_radioss(ScxRadiossRequest)` → `ScxSubmitOutcome` | 워커 VD_SUBMIT | 어댑터 replay `submit_replay_*` |
| 상태·취소 | `status(job_id)`·`cancel(job_id)` | 워커 VD_WAIT·취소 | `http_timeout_s` |
| 결과 모름 정리 | `resolve(request_id, action, job_id)` | 백엔드 `/verify-drops/{id}/resolve` | `http_timeout_s` |

- 헤더는 어댑터가 붙인다: `X-SCX-Relay-Key`(비밀), `X-SCX-Relay-Client: esl`. relay_url 은 `parse_relay_url`(127.0.0.1·[::1]·localhost + 포트만, 경로·쿼리·사용자 정보 없음). 리다이렉트 안 따름.
- 업로드 request_id = `esl-vd-<id>-a<attempt>:f<index>`(정규식 `^[A-Za-z0-9_.:\-]{1,128}$`) — 같은 파일 재시도는 같은 id(릴레이 멱등, 같은 내용 DONE). 묶음 판정은 RL §5.4 그대로(`PAUSED` = 계속 기다림 + 진행 라벨 "대시보드 SCX 재로그인 필요").
- 다운로드 상한 = min(`hpc.scx.max_download_bytes`, health `max_download_bytes`, A 는 `upload.max_file_bytes`). 넘으면 시작 전 422 `SCX_FILE_TOO_LARGE`(값 병기).
- SCX 상태 해석 = 어댑터 `SCX_STATUS_MAP`(Completed → 성공, Failed → 실패, Aborted·취소 계열 → CANCELED). `SCX_JOB_NOT_FOUND` 가 `verify_drop.lost_after_polls`(10)회 연속이면 FAILED `SCX_JOB_LOST`.

### 5.2 오류 → 사용자 문구 (원본 1곳 `resources/scx_messages.json`, 백엔드·워커·화면 공용)

| 릴레이 code / 어댑터 | esl code | 사용자 문구(요지) | 자동 재시도 |
|---|---|---|---|
| 연결 거부·시간 초과(transport) | `SCX_RELAY_UNREACHABLE` | 대시보드에 연결할 수 없습니다(대시보드 실행 여부·relay_url 포트 확인 — 관리자) | 전송만(SR-D-7) |
| `RELAY_DISABLED`·404 경로 없음 | `SCX_RELAY_DISABLED` | 대시보드 SCX 릴레이가 꺼져 있습니다(SIMDASH_SCX_RELAY_ENABLED) | – |
| `RELAY_UNAUTHORIZED` | `SCX_RELAY_UNAUTHORIZED` | 릴레이 비밀 값이 대시보드와 다릅니다(관리자: 같은 비밀 파일 사용, 두 앱 재시작) | – |
| `RELAY_FORBIDDEN` | `SCX_RELAY_FORBIDDEN` | relay_url 이 대시보드 백엔드 loopback 포트가 아닙니다(프록시 경유 금지) | – |
| `DRIVE_MODE_DISABLED` | `SCX_DRIVE_MODE_OFF` | 대시보드가 SCX 모드가 아닙니다(SIMDASH_DRIVE_GATEWAY=scx) | – |
| `DRIVE_WRITE_DISABLED` | `SCX_WRITES_OFF` | 대시보드 드라이브 쓰기가 꺼져 있습니다(SIMDASH_DRIVE_WRITES_ENABLED) — 검증 낙하만 불가 | – |
| `JOB_API_UNAVAILABLE` | `SCX_JOB_API_OFF` | 대시보드 어댑터에 잡 API 가 없습니다(v0.3.0 이상) | – |
| `DRIVE_AUTH_REQUIRED` | `SCX_AUTH_REQUIRED` | 대시보드 관리 화면에서 SCX 재로그인이 필요합니다 | 아니오(재로그인 뒤 [재시도]) |
| `DRIVE_BUSY`·`LOCKED`·`DRIVE_TIMEOUT`·`DRIVE_UNAVAILABLE`·`DRIVE_INTERNAL` | `SCX_BUSY` | SCX 가 바쁘거나 응답이 없습니다(잠시 뒤 자동 재시도) | 예 |
| `DRIVE_STAGING_FULL` | `SCX_DASHBOARD_DISK` | 대시보드 서버 임시 공간이 부족합니다(관리자) | 예(횟수 한도) |
| `TOO_LARGE` | `SCX_FILE_TOO_LARGE` | 파일이 릴레이 상한(<값>)을 넘습니다(관리자: SIMDASH_SCX_RELAY_MAX_DOWNLOAD_BYTES) | – |
| `HASH_MISMATCH` | `SCX_HASH_MISMATCH` | 받은 파일 해시가 다릅니다 | 예 |
| `NOT_FOUND` | `SCX_PATH_NOT_FOUND` | 드라이브에 없는 경로입니다(이동·삭제됨) | – |
| `PATH_NOT_ALLOWED`·`INVALID_PATH` | `SCX_PATH_NOT_ALLOWED` | 허용 범위 밖 경로입니다 | – |
| `LIMIT` | `SCX_LIST_LIMIT` | 폴더 항목이 너무 많습니다(하위 폴더로) | – |
| 묶음 `CONFLICT` | `SCX_STAGE_CONFLICT` | 드라이브에 같은 이름·다른 내용 파일이 있습니다(새 폴더로 재시도) | – |
| `SUBMISSION_UNKNOWN`(replay 소진 포함) | `SCX_SUBMISSION_UNKNOWN` | 제출 결과를 알 수 없습니다. SCX 화면에서 잡을 확인한 뒤 [잡 ID 연결] 또는 [포기]를 고르세요 | **아니오(사람 확인)** |
| 그 밖 제출 오류 | `SCX_SUBMIT_FAILED` | SCX 제출 실패(<릴레이 code>) | – |
| `SCX_JOB_ERROR`·Failed | `SCX_RADIOSS_FAILED` | Radioss 실행 실패(SCX 오류 문구 마스킹 200자) | – |

- 문구에 들어가는 원문(릴레이 message·JobInfo.error_message)은 `core/scx/mask.py` 를 거친다: 비밀 값·`Bearer …`·JWT 형태·`X-SCX-Relay-Key` 값 → `***`, 서버 절대경로 → 기존 `mask_server_paths` 규칙, 200자.

## 6. 설정 키 (기본값 단일 출처 = `core/config.py`, 예시 yaml·prod 예시·관리자 매뉴얼 동기화)

```yaml
hpc:
  scx:                                   # 키 이름 = physicsai hpc.scx.* (SR-D-4). 섹션이 없으면 SCX 기능 전부 비활성
    relay_url: ""                        # 필수. http://127.0.0.1:<대시보드 백엔드 포트>
    secret_file: ""                      # 필수. 절대경로(대시보드 SIMDASH_SCX_RELAY_SECRET_FILE 과 같은 파일 권장)
    client_name: "esl"                   # esl 추가 키 ^[a-z0-9_-]{1,32}$
    drive_base: "~/esl"                  # B 쓰기 기준("~" | "~/<상대>"), health.relay_base 안이어야 함
    home_display: "/Users/vd.dashboard"  # 표시 전용
    appliance: ""                        # B 필수(비면 B 비활성 사유 SCX_APPLIANCE_MISSING)
    version: "26.1"                      # 작업별 입력 기본값(S20 과 같음)
    ncpu: 16
    memory_gb: null
    queue_type: "implicit"
    run_type: "both - use starter and engine files"
    mpi: "Pure MPI"                      # 목록 밖 값은 설정 경고(S20 보강 1)
    single_precision: false
    poll_interval_s: null                # 어댑터 필드 유지용(esl 은 verify_drop.poll_s 사용)
    max_download_bytes: 68719476736      # 64 GiB(대시보드 상한도 맞춰야 함 — R-SR-3)
    stage_patterns: ["*.rad", "*.inc", "*.k", "*.sta", "*.str"]   # esl 은 include 그래프로 고르고 이 목록은 허용 확장자 필터로만
    list_additional_paths: true
    max_stage_bytes: 21474836480
    stage_poll_s: 5
    stage_timeout_s: 14400
    submit_replay_attempts: 3
    submit_replay_wait_s: 10
    http_timeout_s: 30
    transfer_timeout_s: 14400            # 30 GB h3d: 대시보드 임시 받기 + 스트리밍
    collect_max_depth: 2
    health_ttl_s: 30
scx_drive:                               # 기능 A
  enabled: false
  roots:                                 # 릴레이 홈 기준 상대(첫 구간 '.' 금지, SPDM 루트 밖). 0개면 A 비활성(SCX_NO_ROOTS)
    - {key: "drop", label: "낙하해석 공유", rel: "share/drop", projects: []}   # projects [] = 모든 프로젝트
  list_max_entries: 5000                 # 릴레이 max_entries(1~50000), 화면 페이지는 ui.browse_page_max
  max_files: 2000                        # rad + include + 엔진 합계
  engine_globs: ["{stem}_0001.rad", "{stem}_000[2-9].rad"]
  file_retries: 2
  retry_wait_s: 30
verify_drop:                             # 기능 B
  enabled: false
  max_scenes: 5                          # 한 요청의 씬(=제출) 수 상한(Q4)
  default_worst_n: 3                     # '가장 나쁜 씬 N개' 기본 N
  max_running: 2                         # 동시에 VD_STAGE 이후를 진행하는 VERIFY_DROP 수(초과분은 QUEUED 대기 — claim 조건)
  est_hours_per_scene: 3                 # 예상 시간 표시 기본값(같은 프로젝트 완료 검증이 있으면 그 중앙값 사용)
  poll_s: 60
  max_wait_h: 72                         # 넘으면 FAILED VD_WAIT_TIMEOUT(SCX 잡은 종료하지 않음 — [재시도]는 폴링부터)
  lost_after_polls: 10
  engine_globs: ["{stem}_0001.rad", "{stem}_000[2-9].rad"]
  result_globs: {h3d: ["*.h3d"], out: ["*_0000.out", "*_0001.out"]}
  out_ok_patterns: ["NORMAL TERMINATION"]
  out_error_patterns: ["(?m)^\\s*ERROR TERMINATION", "(?i)\\*\\*\\s*ERROR"]
  max_result_bytes: 68719476736
  compare: {same_tol: 0.02, hot_n: 20}
worker:
  xfer_lanes: 2                          # XFER 레인 루프 수(1~8)
```

- 검증: `hpc.scx` 는 어댑터 `validate_scx_config`(문제 목록 그대로 설정 오류 키 `hpc.scx.*`) + esl 키. `scx_drive.roots[].rel` = `scx_naming.rel_problem` 통과, key `^[a-z0-9_-]{1,32}$` 유일. 값이 틀려도 **기동은 하고** 해당 기능만 비활성(기존 bead_doe·opt_run 과 같은 방식).
- 업로드 확장자: A 가 받는 rad·include·상태·h3d 는 `upload.allowed_ext` 안이어야 함(밖 = `missing_includes` 에 "허용되지 않는 확장자" 사유로, 받지 않음).

## 7. API (접두 `/esl/api`, 기존 오류 형식, 비GET `X-ESL-Request: 1`)

| 메서드·경로 | 요청 | 응답 | 오류 |
|---|---|---|---|
| `GET /scx/status?project_id=` | – | `ScxStatusOut` | – (항상 200, 사유를 본문에) |
| `GET /scx/browse?project_id=&root=&path=&offset=&limit=` | – | `ScxBrowseOut` | 403 `FORBIDDEN`(general), 404 `SCX_ROOT_NOT_FOUND`·`SCX_PATH_NOT_FOUND`, 422 `SCX_PATH_NOT_ALLOWED`, 503 `SCX_UNAVAILABLE{reason_code}`, 413 `SCX_LIST_LIMIT` |
| `POST /scx/fetches` | `ScxFetchIn` | `202 ScxFetchOut` | 위 + 422 `UPLOAD_NAME_INVALID`·`SCX_NOT_RAD`·`SCX_NOT_H3D`·`SCX_FILE_TOO_LARGE`, 507 `INSUFFICIENT_STORAGE`, 429 `UPLOAD_LIMIT`(기존 사용자당 동시 업로드, detail `limit`·`open_uploads`) |
| `POST /verify-drops` | `VerifyDropIn` | `201 VerifyDropOut`(+ VERIFY_DROP) | 404 `DOE_NOT_FOUND`, 409 `RESULT_NOT_READY`·`VD_NO_SCENES`, 422 `VD_SCENARIO_UNSUPPORTED`(②③)·`VD_DESIGN_NO_FILES`·`VD_TOO_MANY_SCENES`·`VD_ENTRY_NOT_IN_STUDY`·`INVALID_PARAMS`, 503 `SCX_UNAVAILABLE`. 씬별 제외(`VD_CUMULATIVE_EXCLUDED`·`VD_ENGINE_MISSING`·`VD_INCLUDE_LAYOUT`·`VD_ALREADY_ACTIVE`)는 오류가 아니라 응답 `excluded[]` |
| `POST /verify-drops/plan` | `VerifyDropIn` | `VerifyPlanOut`(저장 안 함 — 대화상자 씬 목록·제출 건수·예상 시간) | 위와 같음 |
| `GET /verify-drops?bead_doe_id=` · `GET /verify-drops/{id}` | – | `[VerifyDropOut]` / `VerifyDropOut` | 404 `VD_NOT_FOUND` |
| `POST /verify-drops/{id}/resolve` | `{version, action: "attach"\|"abandon", scx_job_id?}` | `VerifyDropOut` | 409 `VD_NOT_UNKNOWN`·`VERSION_CONFLICT`, 404 `SCX_JOB_NOT_FOUND`, 409 `SCX_JOB_ID_IN_USE` |
| `GET /verify-drops/{id}/compare.csv` · `/files/{name}`(out·stage.json) | – | 첨부 | 404, 409 `RESULT_NOT_READY` |
| 기존 `POST /jobs/{id}/cancel`·`/retry`, 작업 로그 | – | SCX_FETCH·VERIFY_DROP·VERIFY_POST 에 적용 | 재시도 409 `SCX_SUBMISSION_UNKNOWN`(미정리) |

권한: 모두 해당 프로젝트 power 이상(`require_execute`), 조회는 멤버. A 업로드 세션은 만든 사용자 소유(기존 규칙 — 남의 세션 404).

### 7.1 스키마 (요지 — `schemas.py`, openapi 갱신)

```
ScxStatusOut { fetch: Avail, verify: Avail, roots: [{key, label}],       // 프로젝트에 허용된 루트만
               relay: {reachable, drive_state|null, queue_paused, writes_active, job_api, max_download_bytes|null, checked_at},
               adapters: {version, commit} }
Avail { enabled: bool, reason_code: str|null, reason: str|null }
ScxBrowseOut { root, path, display, entries: [{name, kind: "dir"|"file", size|null, modified_at|null,
               hint: "rad"|"engine"|"h3d"|"include"|"state"|null}], total, truncated }
ScxFetchIn  { project_id, name(≤64, safe_name), root, rad_rel, h3d_rel }  // rel = 루트 기준, h3d 필수
ScxFetchOut { upload_id, job_id }
VerifyDropIn { bead_doe_id, design_id, mode: "worst"|"all", n?(worst 일 때, 1~max_scenes, 기본 default_worst_n),
               title?(≤200), hpc?: {version?(S20 pattern), ncpu?(1~4096)} }
VerifyPlanOut { scenes: [{entry_id, case_id, case_title, r_c, r_umax, r_epsmax}], excluded: [{entry_id, case_id, code, reason}],
                n_submit, est_hours, max_scenes }
VerifyDropCreateOut { batch_id, drops: [VerifyDropOut], excluded: [...] }   // POST /verify-drops 응답(201)
VerifyDropOut { id, batch_id, bead_doe_id, design_id, case_id, entry_id, title, phase, version,
                drive_dir_display|null, scx_job_id|null, scx_status|null, submission: {request_id, state}|null,
                files_n, files_bytes, predicted: {r_umax, r_epsmax, r_c}|null, result: VerifyCompare|null,
                job_ids, created_by_name, created_at, updated_at }
VerifyCompare { rows: [{key, label, orig, verify, ratio, predicted|null, verdict: "better"|"worse"|"same", agree|null}],
                hot: {n, mean_ratio, max_ratio}, warnings: [], tstar: {orig_time, verify_time} }
```
- `hint`: `*_0000.rad` → rad, `engine_globs` 일치 → engine, `.h3d` → h3d, `.inc .k` → include, `.sta .str` → state. 숨김(`.` 시작) 제외, 폴더 먼저·이름 순, offset·limit(≤ `ui.browse_page_max`).
- 진행: 기존 `GET /jobs/{id}`(progress_pct·progress_label 예 "h3d 12.3 / 30.0 GB", "대시보드가 SCX에서 받는 중", "SCX 대기 Queued 00:42") + `GET /uploads/{id}`(파일별 done·sha256, SF_H3D 동안 받는 중 h3d 항목 `done:false`·`received`·`received_total` = 받은 바이트 — 실패·취소 시 그 항목은 빠짐).
- `ScxStatusOut.verify`: v0.11.0 은 항상 `enabled: false`(`VD_DISABLED` — 설정 꺼짐, 켜도 판정 끝에 `VD_NOT_AVAILABLE` "v0.12.0 에서 제공"). 화면은 B 버튼을 그리지 않는다.
- `ScxRelayOut.checked_at`: 헬스를 확인하지 않았으면(기능 A·B 모두 꺼짐·어댑터 없음 등) `null`.
- 오류 detail: 503 `SCX_UNAVAILABLE{reason_code}`, 507 `INSUFFICIENT_STORAGE{need, free, reserve}`, 422 `SCX_FILE_TOO_LARGE{size, limit}`, 429 `UPLOAD_LIMIT{limit, open_uploads}`, 409 `UPLOAD_SCX_MANAGED{rel}`(source scx 파일에 브라우저 PUT)·`UPLOAD_SCX_BUSY{job_id}`(비종료 SCX_FETCH 세션에 파일 추가·빼기·complete·취소).

## 8. 작업 종류 (`job_types.py`)

| 작업 | stage | 레인 | step(종류) | 진행 가중 |
|---|---|---|---|---|
| `SCX_FETCH` | 12 | XFER | `SF_RAD`(INTERNAL) → `SF_H3D`(INTERNAL) → `SF_REGISTER`(INTERNAL) | 10 / 85 / 5 (바이트 기준) |
| `VERIFY_DROP` | 13 | XFER | `VD_PREP` → `VD_STAGE` → `VD_SUBMIT` → `VD_WAIT` → `VD_FETCH` | 2 / 18 / 1 / 59 / 20 |
| `VERIFY_POST` | 13 | SLOT | `H3D_EXTRACT`(LOCAL, 기존 hw·세마포어) → `VD_EXTRACT`(코어 `extract`) → `VD_COMPARE`(코어 `vd_compare`) → `VD_REGISTER` | 40 / 40 / 15 / 5 |

- 대상: SCX_FETCH = `jobs.upload_id`, VERIFY_* = `jobs.verify_drop_id`(나머지 대상 NULL). 비종료 작업 = 업로드당 1개, 검증당 1개.
- 취소: SF_* = 전송 중단(.part 남김 — 재시도 때 덮어씀), 업로드 행은 OPEN 유지(사용자가 기존 [취소]로 정리). VD_STAGE = 폴링 중단(이미 대기열에 들어간 항목은 대시보드가 계속 올림 — 드라이브 불변 원칙상 정리 없음, 안내 문구). VD_WAIT = `cancel(job_id)` **1회**(확인 창 "SCX 잡도 종료합니다") 후 CANCELED. VD_SUBMIT 중 취소는 제출 결과가 정해질 때까지 기다린 뒤 처리(UNKNOWN 이면 그대로 UNKNOWN 표시).
- 재시도: 실패 step 부터(`resume_from_step`). SF = 확인된 파일 건너뜀. VD_STAGE = 같은 폴더·같은 request_id(멱등). VD_SUBMIT = §3 SR-D-11. VD_WAIT 이후 = 같은 scx_job_id. VERIFY_POST 재시도는 VD_FETCH 결과 재사용.
- lease·상실: XFER 작업도 기존 heartbeat·리퍼. 워커가 죽으면 INTERRUPTED → [재시도]. VD_SUBMIT 도중 죽어 `SUBMITTING` 이 남으면 재시도가 같은 request_id 로 보냄(replay).
- 실패 코드(신규, `failure_code`): `SCX_*`(§5.2), `VD_ENGINE_MISSING`·`VD_INCLUDE_LAYOUT`·`VD_CUMULATIVE_EXCLUDED`(시작 시 재검사)·`VD_NODES_MISSING`, `VD_STAGE_TIMEOUT`, `VD_WAIT_TIMEOUT`, `SCX_JOB_LOST`, `VD_RESULT_MISSING`(h3d 0개·여러 개면 이름 = starter stem 우선, 그래도 여럿이면 실패), `VD_RADIOSS_ABNORMAL`(out 에 오류 패턴 또는 정상 종료 패턴 없음), `VD_TOPOLOGY_MISMATCH`, 기존 `H3D_EXTRACT_FAILED`·`INPUT_CHANGED`(원 Case 입력 지문이 VD_PREP 기록과 다름).
- 알림: 기존 notifications(작업 끝) 그대로 — VERIFY_POST 성공·VERIFY_* 실패·UNKNOWN.

## 9. 기능 상세

### 9.1 A — SF_RAD·SF_H3D·SF_REGISTER
1. 시작: health → 범위 재검사(루트 설정이 바뀌었으면 `SCX_PATH_NOT_ALLOWED`) → rad·h3d `list`(부모 폴더)로 크기 확인 → upload_root 여유 ≥ 합계 + `upload.min_free_gb`(아니면 `INSUFFICIENT_STORAGE`).
2. SF_RAD: rad·엔진 rad → 스캔 → include 반복(SR-D-8). 엔진 rad 탐색은 starter 이름이 `<stem>_0000.rad` 일 때만(아니면 로그 + 작업 경고 "엔진 rad 를 찾지 않았습니다" — 화면 탭은 hint `rad`(`*_0000.rad`)만 고르게 하므로 API 직접 호출 때만 생김). 배치 = 받은 파일들의 드라이브 공통 조상 C 기준 상대(`rad/<rel from C>`), 상대 경로는 `core/uploads.check_rel` 통과해야 함(아니면 그 파일은 `missing_includes` 에 사유). `uploads.files[]` 에 항목 추가: `{rel, size, sha256, done, source:"scx", drive_rel, client:{name:"scx-relay", version:<lock commit 12>}}`.
3. SF_H3D: `h3d/<원 이름>`. 진행률 = 받은 바이트/크기(첫 바이트 전에는 "대시보드가 SCX에서 받는 중" 라벨, 경과 시간). 시작 때 `uploads.files[]` 에 받는 중 항목(`source:"scx"`, `done:false`, 내부 키 `scx_got`)을 넣고 진행마다 갱신 → `GET /uploads/{id}` 의 그 파일 `received`·`received_total`(파일별 진행률). 끝나면 완료 항목(sha256)으로 바꾸고, 실패·취소면 뺀다.
4. SF_REGISTER: 기존 `inspect_upload` 와 같은 함수 → `uploads.result`(ok 면 COMPLETED), `result.scx = {root, rad_rel, h3d_rel, missing_specs[]}`.
- 업로드 서비스 변경: `source:"scx"` 항목에는 브라우저 PUT 거부(409 `UPLOAD_SCX_MANAGED`), `cleanup_stale` 은 비종료 SCX_FETCH 가 있는 세션 건너뜀, 목록·화면 출처 표시 = `files[].source == "scx"`(세션 `client` 는 첫 파일 배치 전에는 null 이라 화면은 `client.name == "scx-relay"` 또는 source scx 파일 존재로 판정). 추가 파일(누락 include)은 기존 `POST /uploads/{id}/files` 로 같은 세션에.

### 9.2 B — VD_PREP·STAGE·SUBMIT·WAIT·FETCH
1. VD_PREP: SR-D-13~15 재검사, 원 Case 입력 지문 = Case `inputs_hash` 와 같아야 함(아니면 `INPUT_CHANGED`), 노드 패치(코어 `esl.verify.patch`, 자식 프로세스 — 대형 rad 스트리밍, 원본 읽기만) → `stage/`·sha256 → `stage.json`, 합계 ≤ `hpc.scx.max_stage_bytes`.
2. VD_STAGE: `ensure_new_dir(<drive_base>/<프로젝트>, VD<no>_<UTC>)` → `verify_drops.drive_dir_rel` 저장(재시도 재사용) → 파일마다 `upload`(rel_dir = 폴더 + 상대 하위) → 모든 batch DONE.
3. VD_SUBMIT: `ScxRadiossRequest(request_id, input_path=<dir>/<starter>, engine_paths=[<dir>/<engine>…], additional_paths=[나머지], version=params.hpc.version or cfg.version, appliance, ncpu=params.hpc.ncpu or cfg.ncpu, …, client_ref={app:"esl", verify_drop_id, design_id, case_id})`.
4. VD_WAIT: `status` 폴링 → `verify_drops.scx_status` 갱신·진행 라벨, 전이 SUBMITTED→RUNNING→FETCHED.
5. VD_FETCH: `output_rel`(null 이면 `SCX_OUTPUT_UNRESOLVED` — RL §5.8, 사람 확인) list → `result_globs` 파일 내려받기(sha) → out 판정 → 같은 트랜잭션에서 VERIFY_POST 큐.

### 9.3 B — VD_COMPARE (`esl/verify/compare.py`, 결정적, 숫자만)
- 입력: 원 Case `01_extract/{final,history,disp,frames}`·`model.npz`, 검증 `work/01_extract/…`, DOE 결과에서 그 안·그 ESL 항목의 r 값.
- 위상: 대상 파트 요소 ID 집합·연결 동일(좌표는 다름 — 모핑).
- 행(`rows`):
  | key | 정의 |
  |---|---|
  | `eps_peak` | 시간·요소 최대 ε_eq(기존 추출 정의, 누적 아님), 요소 ID·시각 병기 |
  | `eps_hot` | 원 낙하 상위 `hot_n` 요소의 요소별 시간 최대 ε_eq 비 → 평균·최대 |
  | `disp_peak` | 프레임별 기존 강체 제거(전 노드 Kabsch)한 ‖u_rel‖ 최대의 시간 최대 |
  | `eps_tstar`·`disp_tstar` | 원 Case 확정 t* 에 가장 가까운 검증 프레임의 같은 지표 |
- `predicted` = 스터디 ESL별 개선 지표(v0.10.0 §11.4) 중 그 Case 의 ESL 항목 r(umax·epsmax), `agree` = (ratio−1)·(predicted−1) > 0 또는 둘 다 `same`.
- 출력 `compare.json`(+ `compare.csv` 같은 행), `verify_drops.result` 요약, artifacts kind `VERIFY_RESULT`.

## 10. 화면 (2560×1440 기준, 1920×1080 잘림 없음, 화면당 주 버튼 1개)

### 10.1 새 Case — 4번째 탭 "SCX 드라이브에서 고르기" (`pages/newcase/ScxPanel.tsx`)
```
[내 PC에서 올리기][서버 폴더에서 고르기][PC에서 추출해 올리기][SCX 드라이브에서 고르기]
┌ 루트 [낙하해석 공유 ▾]   share/drop / 75QN90 / drop_front                      (탐색 중 오류 → 줄 안 사유) ┐
│ 📁 ..   📁 sub1                                                                                          │
│ 📄 ref_0000.rad   rad     1.2 MB   2026-10-28   (선택 ●)                                                  │
│ 📄 ref_0001.rad   engine  4 KB                                                                           │
│ 📄 ref.h3d        h3d     28.4 GB  (선택 ●)                                                               │
├ 선택: rad ref_0000.rad · h3d ref.h3d(28.4 GB) · include 는 내려받을 때 자동 수집                          │
│ 이름 [75QN90_front]                                    [SCX에서 내려받기](주)                            │
└ 진행: JobProgress 재사용 — "h3d 12.3 / 28.4 GB", [취소]                                                   ┘
```
- 탭 비활성: `/scx/status.fetch.enabled=false` 이면 탭 버튼에 사유 툴팁 + 패널에 사유 1줄(다른 탭 정상).
- 끝나면 패널이 기존 업로드 complete 결과 표시(파트·누락 include·`?upload=<id>` 로 주소 갱신) → 주 버튼은 페이지의 기존 [Case 만들기]. 누락 include 가 있으면 결과 표의 [추가로 올리기](브라우저 파일 선택 → 같은 세션 `POST /uploads/{id}/files` → complete 다시) — 다른 탭으로 옮기지 않는다.

### 10.2 강성 평가 스터디 결과 — [검증 낙하] (`pages/doe/DoeStudy.tsx` 받기 줄 옆, `components/VerifyDropCard.tsx`)
- 버튼 표시 조건: 시나리오 ①·phase DONE. 비활성 사유(툴팁): B 꺼짐·SCX 사유(§3 SR-D-19)·선택 안에 `best/` 없음.
- 대화상자: 안 [순위 1 d017 ▾](best 있는 안만), 씬 라디오 2개 [● 가장 나쁜 씬 N개 (N [3])  ○ 고른 ESL 전부], 씬 표(Case·r·제외 사유 회색 — `POST /verify-drops/plan`), 줄 "제출 n건 · 예상 약 h시간(씬당)·상한 max_scenes", 접힌 '고급' Radioss 버전(초기 = 설정, S20 규칙)·ncpu, 안내 "SCX 실행은 수 시간 걸릴 수 있습니다". 주 버튼 [검증 낙하 시작].
- 카드 "검증 낙하"(스터디 화면 아래, batch 별 묶음 · 씬마다 1행): 안·씬·단계(올리는 중·SCX 대기·실행 중·결과 받는 중·추출·완료·실패)·SCX 잡 ID·드라이브 폴더(표시용 경로 복사).
  - UNKNOWN: 사유 + 잡 ID 입력칸 [잡 ID 연결] · [포기] (확인 창 "SCX 에 잡이 실제로 있으면 중복 실행될 수 있습니다").
  - 완료: 비교 표 `지표 | 원 낙하 | 검증 낙하 | 비 | ESL 선형 예측 비 | 판단(개선/악화/비슷) | 일치` + [CSV] [out 받기], 경고 줄(`VD_RADIOSS_ABNORMAL` 아님 경고·추출 경고).

## 11. DB 변경 — migration `0012_scx_relay`

- `jobs.upload_id` VARCHAR(36) NULL FK uploads, `jobs.verify_drop_id` VARCHAR(36) NULL FK verify_drops; 부분 인덱스 `ix_jobs_upload`·`ux_jobs_upload_active`·`ix_jobs_verify_drop`·`ux_jobs_verify_drop_active`(비종료 1개).
- **`verify_drops`**: `id`, `batch_id` VARCHAR(36)(한 요청 묶음), `project_id`, `bead_doe_id` FK, `design_id` varchar(64), `case_id` FK, `entry_id` FK library_entries, `title`(200), `phase` CHECK IN (`PREP`,`STAGING`,`SUBMITTED`,`RUNNING`,`FETCHED`,`POST`,`DONE`,`FAILED`,`CANCELED`), `version` bigint ≥1, `params` JSONB(hpc 덮어쓰기), `files` JSONB(배열: rel·size·sha256·source orig|morph), `drive_dir_rel` NULL(≤1024), `scx_job_id` NULL, `scx_status` NULL, `predicted` JSONB NULL, `result` JSONB NULL, `dir_rel`(`_verify/<id>`, CHECK 상대·`..` 없음), `created_by(_name)`, `created_at`, `updated_at`. Index `(bead_doe_id, created_at desc)`, `(batch_id)`, 부분 UNIQUE `(bead_doe_id, design_id, case_id) WHERE phase NOT IN ('DONE','FAILED','CANCELED')`.
- **`scx_submissions`**: `request_id` PK(≤128), `verify_drop_id` FK, `attempt` int ≥1, `request_sha256`(64), `state` CHECK IN (`SUBMITTING`,`SUBMITTED`,`UNKNOWN`,`FAILED`,`ATTACHED`,`ABANDONED`), `scx_job_id` NULL UNIQUE, `error_code`, `error_message`(≤200, 마스킹), `created_at`, `updated_at`, `resolved_at`, `resolved_by`. UNIQUE `(verify_drop_id, attempt)`. 삭제 없음.
- CHECK 교체: `ck_jobs_job_type`(+SCX_FETCH·VERIFY_DROP·VERIFY_POST), `ck_jobs_stage`(1~13), `ck_jobs_lane`(SLOT·LIGHT·XFER), `ck_jobs_subject`(SCX_FETCH = upload_id NOT NULL·나머지 NULL, VERIFY_* = verify_drop_id NOT NULL·나머지 NULL, 기존 분기에 두 열 IS NULL), `ck_artifacts_kind`(+VERIFY_RESULT). `ck_jobs_holds_slot` 불변(XFER 는 슬롯 없음).
- `uploads` 변경 없음(files[] 키 `source`·`drive_rel`, result 키 `scx`).
- 멱등(0011 과 같은 방식: checkfirst·IF NOT EXISTS·DROP IF EXISTS 후 재추가), downgrade 미지원. 0011 의 CHECK 를 `*_0011` 고정 상수로(SR-D-17).

## 12. 보안

- **loopback 전용**: relay_url 검사(어댑터 `parse_relay_url`), 프록시 환경변수 무시(`http.client` 직접 연결 — urllib 프록시 미사용, 시험으로 고정). 브라우저는 릴레이에 직접 닿지 않음(esl 백엔드만 호출).
- **비밀**: SR-D-18. `repr`·예외·설정 응답에 값 없음(정적 시험 + caplog). `secret_file` 은 설정 응답에 경로만.
- **경로**: 드라이브 rel = 어댑터 `rel_problem`·`forbidden_reason` + 루트 포함(접두가 아닌 구간 비교, NFC·casefold). 로컬 쓰기 = A 세션 폴더(`check_upload_dir`·`target_path`·성분 링크/junction 검사·realpath ⊂ 세션), B `_verify/<id>`(realpath ⊂). 내려받은 파일 이름은 `check_segment`(Windows 예약어·메타문자) 통과 못 하면 받지 않음.
- **드라이브 쓰기**: B 의 `upload` 만(대시보드 대기열, 덮어쓰기 없음). 삭제·이동 호출 없음 — esl 코드에서 어댑터 쓰기 메서드를 부르는 모듈은 `worker/esl_worker/scx_verify.py` 하나(정적 시험).
- **권한**: power 이상(프로젝트), 루트별 `projects` 제한, 업로드 세션 소유자 규칙 그대로.
- **외부 명령 없음**: 새 코드에 subprocess 없음(hw 추출은 기존 H3D_EXTRACT 경로).

## 13. 배포

- `deploy/simdash_adapters.lock` + `deploy/wheels/simdash_adapters-0.1.0-py3-none-any.whl`(`.gitattributes *.whl binary` 기존), `deploy/paicad_wheel.py` 를 lock 일반화(`console_script` null 허용, `check` 는 console_script 없으면 import 확인 `--module simdash_adapters.hpc`) — 파일 이름 유지(호출부 호환).
- `install-common.ps1` `Install-EslScxAdapters`: 동봉 wheel → lock 대조 → `pip install --no-index --no-deps` → import 확인. 실패해도 설치 계속, SCX 기능만 비활성 + 사유(`worker_heartbeats.info.scx = {ok, version, commit, reason}`). `collect-offline`(sh·ps1)은 동봉 wheel 대조 후 묶음에 넣음. `requirements.lock` 변경 없음(의존성 없음).
- 개발·CI: `pip install deploy/wheels/simdash_adapters-*.whl`(lock 대조 스크립트 포함), 시험 가짜 릴레이 사본 `backend/tests/scx/fake_scx_relay.py`(출처 머리말: physicsai 커밋 a363a89, 경로).
- 환경 점검(`check.py`): 어댑터 import·lock 일치, `hpc.scx` 검증, 비밀 파일 형식·ACL 경고, health(연결·job_api·writes_active·relay_base 안의 drive_base·max_download_bytes < 가장 큰 기대 h3d 경고), XFER 레인 수.
- 관리자 매뉴얼 `docs/manual/admin.md` 새 절: 대시보드 쪽 필수 설정(SIMDASH_SCX_RELAY_ENABLED·SECRET_FILE·DRIVE_GATEWAY=scx·DRIVE_WRITES_ENABLED·RELAY_DRIVE_BASE·MAX_DOWNLOAD_BYTES ≥ 64 GiB 권장·임시 공간), esl `hpc.scx` 블록 복사, 비밀 파일 공유 방법. 사용 가이드: 새 Case SCX 탭, 검증 낙하.
- CHANGELOG `[0.11.0]`, VERSION `0.11.0`.

## 14. 검증 계획 (V-SR-*)

| ID | 내용 | 위치 |
|---|---|---|
| V-SR-1 | wheel·lock: 동봉 wheel 정규화 sha256 = lock, lock 커밋 = a363a89…, import·`ScxHpcGateway` 존재, 손상 wheel → 설치 중단 아님·SCX 비활성 사유 | `tests/deploy/test_scx_wheel.py` |
| V-SR-2 | 연결 계층: 헤더 `X-SCX-Relay-Client: esl`(가짜 릴레이 기록), relay_url 비loopback·경로 포함 거부, 비밀 형식 오류 → 비활성 사유, 비밀 값이 caplog·오류 본문·repr·`/scx/status`·설정 응답에 없음, 프록시 환경변수 무시 | `backend/tests/scx/test_gateway.py` |
| V-SR-3 | `/scx/status` 사유 순서(SR-D-19) 전 경로 + TTL 캐시 + 대시보드 다운(포트 닫힘) 시 3 s 안 응답 | `backend/tests/scx/test_status.py` |
| V-SR-4 | `/scx/browse`: 루트 밖·`..`·`/`·`~`·`\`·첫 구간 `.`·SPDM 접두(대소문자 다른 표기)·다른 프로젝트 루트 거부, hint·정렬·페이지, general 403 | `backend/tests/scx/test_browse.py` |
| V-SR-5 | `POST /scx/fetches`: 업로드 행 + 작업 한 트랜잭션, 이름 규칙, 크기 상한(422), 여유 공간(507), 동시 업로드 한도 | `backend/tests/scx/test_fetch_api.py` |
| V-SR-6 | SF 워커(가짜 릴레이): include 폐포(상대·`../`·하위 폴더·상태 파일·절대경로 누락·루트 밖 누락·확장자 밖), 엔진 rad, 배치 = 공통 조상, sha 불일치 재시도 후 성공/실패, 재시도 시 확인 파일 건너뜀, 취소, inspect_upload 결과·COMPLETED, 세션 폴더 밖 쓰기 0, `.part` 링크 거부 | `worker/tests/test_scx_fetch.py` |
| V-SR-7 | 업로드 서비스: scx 항목 PUT 409, stale 정리 제외(활성 작업), 누락 include 를 같은 세션에 추가 후 complete OK | `backend/tests/test_uploads.py`(추가) |
| V-SR-8 | VERIFY 생성 검사: ②③ 422, best 없는 안 422, 씬 선택 worst N(r 큰 순·동률·같은 Case 합침)·all, 상한 422, 누적 씬·엔진 없음·include 배치·활성 중 씬 = excluded, 0개 409, plan = 생성과 같은 씬 | `backend/tests/scx/test_verify_api.py` |
| V-SR-9 | VD 워커: 폴더 새로(`_2` 접미), 업로드 request_id 멱등·PAUSED 대기·CONFLICT 실패·시간 초과, 제출 성공·replay(어댑터 호출 1회)·`unknown` → FAILED UNKNOWN·재시도 409·attach → 폴링부터·abandon → 새 attempt, SUBMITTING 잔존 재시도 = 같은 request_id, 상태 시퀀스·LOST·WAIT 시간 초과, 취소 = terminate 1회, output_rel null, h3d 0·여러 개, out 판정 | `worker/tests/test_scx_verify.py` |
| V-SR-10 | VERIFY_POST: 큐 연결(같은 트랜잭션), 추출·비교, 위상 불일치, 결과 등록·artifacts | `worker/tests/test_verify_post.py` |
| V-SR-11 | 코어 비교: 합성 추출 두 벌(알려진 비) → 행 값·판단·일치·t* 최근접, 결정성 | `tests/verify/test_compare.py` |
| V-SR-16 | 노드 패치: Ch/R 노드가 rad 본문·여러 include 에 흩어진 경우, 고정폭·공백 구분 줄, 다른 줄 바이트 불변, 못 찾은 노드 `VD_NODES_MISSING`, 패치 후 parse_rad 좌표 = 모핑 좌표(1e-9 상대) | `tests/verify/test_patch.py` |
| V-SR-12 | migration 0012: 빈·0008·0010·0011 DB, 멱등, tables.py 일치, 기존 행 제약, 0011 고정 상수, MCP 0009 를 0012 뒤에 붙인 체인 단일 head | `backend/tests/test_migrations.py` |
| V-SR-13 | XFER 레인: SLOT·LIGHT 와 독립 claim, holds_slot false, xfer_lanes 수만큼 동시, 리퍼 INTERRUPTED | `worker/tests/test_runtime.py`(추가) |
| V-SR-14 | 입력 보호: 원 Case 폴더·`best/` 전후 sha·mtime 불변, 드라이브 쓰기 메서드 호출 모듈 1개·삭제/이동 이름 없음(정적), 새 코드 subprocess 없음(정적) | `tests/test_static_scx.py` |
| V-SR-15 | 프런트: 탭 4개·비활성 사유, 탐색·선택·내려받기·진행·완료 후 기존 Case 만들기, [검증 낙하] 조건·대화상자·카드 상태별(UNKNOWN 해결 포함)·비교 표, 2560·1920 레이아웃(가로 스크롤 없음), check:api(openapi 대조) | `frontend/src/__tests__/scx.test.tsx`, `scripts/e2e_scx.mjs`(가짜 릴레이 + 실 백엔드·워커) |
| V-SR-R1 | **실기**: 실 대시보드 릴레이 — 1 GB·30 GB h3d 내려받기 시간(대시보드 임시 받기 포함)·메모리, 22만 요소 Ch/R ① 최적 안 검증 낙하 1회(SCX 시간·결과 크기·out 판정 패턴·추출·비교), relay `requested_by=esl` 확인, 대시보드 재시작 중 비활성 표시 | `docs/manual/scx_check.md` |

## 15. 구현 분해 (파일 소유권 · 순서 — A 먼저, B 는 A 의 연결 계층 재사용)

| 묶음 | 담당 | 파일 | 시험 |
|---|---|---|---|
| SR1 배포·연결 계층 | Impl-Deploy + Impl-Core | `deploy/simdash_adapters.lock`, `deploy/wheels/simdash_adapters-0.1.0-py3-none-any.whl`, `deploy/paicad_wheel.py`(일반화), `deploy/install-common.ps1`·`collect-offline.{sh,ps1}`; `backend/esl_platform/core/scx/{__init__,gateway,settings,status,messages,mask,paths}.py`, `resources/scx_messages.json`, `core/config.py`(hpc·scx_drive·verify_drop·worker.xfer_lanes), `config/*.example.yaml`, `check.py`; `backend/tests/scx/fake_scx_relay.py`(사본) | V-SR-1·2·3 |
| SR2 DB | Impl-Backend | `core/db/tables.py`, `migrations/versions/0012_scx_relay.py`, `0011_bead_doe.py`(고정 상수), `core/job_types.py`(3종·가중), `core/repositories/verify.py` | V-SR-12 |
| SR3 백엔드 A | Impl-Backend | `api/routers/scx.py`, `api/services/scx_drive.py`, `api/services/uploads.py`(scx 항목·stale), `api/schemas.py`, `api/main.py`, openapi | V-SR-4·5·7 |
| SR4 워커 A | Impl-Worker | `worker/esl_worker/runtime.py`(XFER 루프), `executor.py`(디스패치), `worker/esl_worker/scx_fetch.py` | V-SR-6·13 |
| SR5 화면 A | Impl-Frontend | `pages/newcase/{NewCase,ScxPanel}.tsx`, `api/scx.ts`, `api/types.ts`, `mock/*`, `pages/guide/content.ts` | V-SR-15(A) |
| — | **A 출시 게이트**: SR1~SR5 통합·V-SR-R1(A 부분) 후 B 착수 | | |
| SR6 코어 B | Impl-Core | `esl/verify/{__init__,patch,compare}.py`(patch = /NODE 노드 ID 패치, compare = 비교), `esl/pipeline.py`(stage `vd_patch`·`vd_compare` 등록) | V-SR-11·16 |
| SR7 워커 B | Impl-Worker | `worker/esl_worker/scx_verify.py`(VERIFY_DROP — 어댑터 쓰기 호출 유일 모듈), `worker/esl_worker/verify_post.py`, `executor.py`·`register.py`(VD_REGISTER) | V-SR-9·10·14 |
| SR8 백엔드 B | Impl-Backend | `api/routers/verify.py`, `api/services/verify_drop.py`, `schemas.py` | V-SR-8 |
| SR9 화면 B | Impl-Frontend | `pages/doe/DoeStudy.tsx`(버튼), `components/VerifyDropCard.tsx`, `api/scx.ts` | V-SR-15(B) |
| SR10 문서 | Plan/Deploy | `docs/manual/{admin,user,scx_check}.md`, CHANGELOG·VERSION, decisions.md 구현 반영 | – |

- 순서: SR1 → SR2 → (SR3 ∥ SR4, SR4 는 SR2 의 job_types 선행) → SR5(mock 병행) → A 게이트 → SR6 ∥ SR8 → SR7 → SR9 → SR10 → 통합 E2E → 실기.
- 공유 파일 충돌 방지: `schemas.py`·`executor.py`·`job_types.py`·`config.py` 는 묶음별 절(주석 머리) 추가만, 같은 시점 한 묶음만 수정.

## 16. 후속 (v0.11.0 범위 밖 · 다른 저장소 요청)

- 대시보드: 릴레이 `GET /files` Range(이어받기), 읽기 범위에 SPDM 루트 읽기 전용 허용(Q1 B 선택 시), 대기열 관리 화면 출처 이름에 client(현재 "PhysicsAI" 고정).
- physicsai `simdash_adapters`: `ScxHpcGateway(..., client_name=)` 인자(SR-D-3 의 비공개 메서드 재정의 제거), scx 포함 버전 번호 올림.
- esl: 검증 결과를 새 Case 로(Q3 B), 여러 안 일괄 검증, 드라이브 폴더 정리 안내.

## 17. 확정 사항 (2026-10-30, 사용자)

| 질문 | 확정 | 반영 |
|---|---|---|
| Q1 SCX 탐색 범위 | **A**: `scx_drive.roots` = 공용 계정 홈 안 공유 폴더, 대시보드 변경 없음 | SR-D-5, §6 |
| Q2 검증 대상 안 | **A**: 모핑 사본이 남은 순위 1~`paicad.keep_files_top` 안만 | SR-D-10 |
| Q3 결과 처리 | **A**: 정보 비교·CSV 만. 새 ESL 은 기능 A 로 결과를 가져와 Case 생성 | SR-D-16 |
| Q4 씬 선택 | 실행 시 라디오 2개 — (A) 가장 나쁜 씬 N개(r 큰 순, 기본 3) / (B) 고른 ESL 전부, 제출 건수·예상 시간 표시, `verify_drop.max_scenes` 상한. 씬마다 원 Case 입력 사본에 노드 ID 기준 `/NODE` 좌표 패치(Ch/R 노드가 어느 include 에 있든) → 별도 Radioss 제출. 누적 씬(.str/.sta)은 제외 + 경고, 연쇄 실행은 후속 | SR-D-10·13·15, §7·§10.2·§11 |

## 18. 리스크 (R-SR-n)

| ID | 리스크 | 대응 |
|---|---|---|
| R-SR-1 | **대시보드 의존**: 대시보드·릴레이 꺼짐·재로그인 필요 시 A·B 정지, B 대기 중 대시보드 재시작이면 상태 조회 실패 | 기능만 비활성 + 사유(SR-D-19), 폴링은 `SCX_BUSY` 재시도·`lost_after_polls`·`max_wait_h` 후 실패하되 [재시도]가 같은 잡 ID 로 이어감, 제출은 request_id replay |
| R-SR-2 | **SCX 실행 시간·라이선스**: 22만 요소 낙하 1회 수 시간, Radioss 라이선스·appliance 큐 대기, 사용자가 여러 번 누르면 비용 | `verify_drop.max_scenes`(5)·`max_running`(2)·(안, 씬)당 비종료 1개, 대화상자 제출 건수·예상 시간, 취소 = terminate 1회, 결과는 재사용(같은 안·씬 재실행 시 확인 창) |
| R-SR-3 | **결과·전송 크기**: h3d 30 GB 가 릴레이 기본 상한 20 GiB 초과(413), 대시보드가 임시 폴더에 전부 받은 뒤 보내 첫 바이트까지 오래 걸림(시간 초과), 이어받기 없음, 같은 PC 에 대시보드 임시 + esl 업로드 + `_verify` 로 3배 디스크 | 관리자 매뉴얼에 대시보드 상한·임시 공간 필수 설정, `transfer_timeout_s` 14400, 시작 전 크기·여유 공간 검사, 파일 단위 이어받기, Range 후속 요청 |
| R-SR-4 | 어댑터 비공개 메서드 재정의(SR-D-3)가 다음 어댑터 버전에서 깨짐 | lock 고정 + V-SR-2, 후속 `client_name` 인자 |
| R-SR-5 | 드라이브 폴더 누적(삭제 없음) | 폴더 이름 규칙·관리자 안내(SCX 화면 정리), 범위 밖 |
| R-SR-6 | 엔진 rad·include 배치가 실제 덱과 다르면 제출 후 starter 오류 | 시작 전 검사(SR-D-13·14), out 판정 `VD_RADIOSS_ABNORMAL` 과 out 받기 |

## 변경 메모
- (2026-10-30) 초안 작성(Plan).
- (2026-10-30) 사용자 확정 Q1 A·Q2 A·Q3 A·Q4(씬 선택 2방식·노드 ID 패치·누적 씬 제외) 반영, 상태 확정.
