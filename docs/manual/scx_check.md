# SCX 드라이브에서 고르기 — 실기 체크리스트 (v0.11.0 기능 A)

계약 `docs/contracts/esl_scx_relay.md` §16 V-SR-R1 중 **기능 A** 분(검증 낙하 B 는 v0.12.0). 클라우드 시험은 가짜 릴레이
(`backend/tests/scx/fake_scx_relay.py`)·작은 합성 모델로만 돌았으므로 **Windows 운영 서버에서 처음 켤 때** 이 순서로 확인한다.
순서: **0 설치·연결 → 1 상태 화면 → 2 탐색 → 3 가져오기(소용량) → 4 가져오기(대용량 30 GB) → 5 끊김·재시도 → 6 릴레이 다운**.
결과(통과/실패·시간·메모)는 각 표 오른쪽 칸에 적고, 고친 값은 설정 파일에만 반영한다(코드 수정 없음).
`<런타임>` = 설치 폴더(git 폴더 설치는 `<git>\.runtime`). 설정 방법은 관리자 매뉴얼 §2.7.2.

## 0. 설치·연결

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 0-1 | 어댑터 | 설치·업데이트 콘솔에 `simdash_adapters 0.1.0 (커밋 a363a89e8f93)` — 환경 점검 `scx.adapter` OK, `scx.adapter.lock` FAIL 없음 | |
| 0-2 | 대시보드 설정 | 대시보드 `.env`: `SIMDASH_SCX_RELAY_ENABLED=true`, `SIMDASH_DRIVE_GATEWAY=scx`, `SIMDASH_SCX_RELAY_SECRET_FILE=<절대경로>`, `SIMDASH_SCX_RELAY_DRIVE_BASE=<기준>`, `SIMDASH_SCX_RELAY_MAX_DOWNLOAD_BYTES=68719476736`(≥ 64 GiB). 대시보드 임시 폴더 드라이브 여유 ≥ 가장 큰 h3d × `worker.xfer_lanes` | |
| 0-3 | 비밀 파일 | esl `hpc.scx.secret_file` 이 대시보드와 **같은 파일**. `icacls <파일>` 에 Everyone·Users·Authenticated Users 없음 → 환경 점검 `hpc.scx.secret_file` OK(ACL 경고 없음) | |
| 0-4 | esl 설정 | `hpc.scx.relay_url` = 대시보드 백엔드 loopback 포트, `scx_drive.enabled: true`, `roots` 1개 이상, `worker.xfer_lanes: 2`. 백엔드·워커 재시작 | |
| 0-5 | 환경 점검 | `esl_service.py check --runtime <런타임>` → `hpc.scx` OK, `scx.relay` OK(`drive_mode scx`), `scx.relay.max_download_bytes` 경고 없음, `worker.xfer_lanes` OK | |

## 1. 상태 화면

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 1-1 | 탭 표시 | 새 Case → 4번째 탭 **SCX 드라이브에서 고르기** 가 켜짐(사유 툴팁 없음), 다른 탭 3개 그대로 | |
| 1-2 | 상태 API | (관리자) `GET /esl/api/scx/status?project_id=<id>` → `fetch.enabled: true`, `verify.enabled: false`(`VD_DISABLED`), `roots` = 설정한 루트(프로젝트 제한 반영), `relay.reachable: true`, `relay.max_download_bytes` = 대시보드 값, `adapters.commit` = lock 12자 | |
| 1-3 | 관리자 표시 | 전역 관리자로 탭이 꺼진 상태(아래 6)를 만들면 전체 문구 + `fetch: <코드> · verify: VD_DISABLED`, 일반 사용자는 괄호 앞 짧은 사유만 | |
| 1-4 | 프로젝트 제한 | `roots[].projects` 에 다른 프로젝트만 넣으면 이 프로젝트에서 탭 비활성 `SCX_NO_ROOTS`(되돌림) | |

## 2. 탐색

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 2-1 | 루트·폴더 | 루트 선택(2개 이상이면 드롭다운) → 폴더 이름 클릭으로 들어가기, 경로 줄(›)로 위로. 폴더 먼저·이름 순, 숨김(`.` 시작) 없음, 표시 경로 = 공용 계정 홈 기준 | |
| 2-2 | 표지 | `*_0000.rad` = rad, `*_0001.rad` = 엔진 rad · 자동, `.inc/.k` = include · 자동, `.sta/.str` = 상태 · 자동, `.h3d` = h3d. rad·h3d 만 고를 수 있음 | |
| 2-3 | 큰 폴더 | 항목이 `ui.browse_page_max` 보다 많은 폴더 → [더 보기] 로 이어 보기. `list_max_entries` 를 넘으면 `SCX_LIST_LIMIT`(하위 폴더로 안내) | |
| 2-4 | 범위 밖 | 주소 조작 등으로 루트 밖·SPDM 경로 요청 → 422 `SCX_PATH_NOT_ALLOWED`(화면 줄 안 사유). 드라이브 쓰기 0(대시보드 릴레이 로그에 POST 없음) | |
| 2-5 | 응답 시간 | 항목 수백 개 폴더 목록 시간(초) 기록 | |

## 3. 가져오기 — 소용량(h3d 1 GB 안팎)

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 3-1 | 시작 | rad(`_0000.rad`) + h3d 선택 → 줄 "자동 포함: include · 엔진 rad n개" → **SCX에서 내려받기**. 202 후 진행 화면(작업 SCX 내려받기, 레인 XFER) | |
| 3-2 | 진행률 | 작업 줄 `rad 받는 중` → `rad·include n개 받음` → h3d 첫 바이트 전 `h3d: 대시보드가 SCX에서 받는 중 mm:ss` → `h3d x.x / y.y GB`. 파일 표 h3d 행에 진행 막대·`받은 / 크기 (%)`(2초마다 갱신) | |
| 3-3 | 완료 | 파일 표 모두 `받음 · sha256 확인`, 결과 표(파트·누락 include 0) → 주소 `?upload=<id>` → 아래 Case 이름 확인 → **Case 만들기** → ① 단계 진입(추출 작업 시작) | |
| 3-4 | 파일·시간 | 업로드 폴더 `<upload_root>\<사용자>\<시각>_<이름>\rad\…`·`h3d\<이름>.h3d`, `.part` 없음, `_scx\fetch.json`. 총 시간(대시보드 임시 받기 포함)·워커 메모리 최대 기록 | |
| 3-5 | 누락 include | 루트 밖·절대경로 include 가 있는 모델 → 결과 표 "누락 include" 와 사유, 작업 경고 1줄 → **[추가로 올리기]** 로 PC 파일 선택 → 같은 세션 확인 OK → Case 만들기 | |
| 3-6 | 출처 표시 | 같은 세션을 '진행 중인 업로드'·`?upload=<id>` 로 다시 열면 배지 **SCX에서 받음**. 그 세션의 SCX 파일에 브라우저로 다시 올리기 → 409 `UPLOAD_SCX_MANAGED` | |
| 3-7 | 동시 한도 | 진행 중 업로드가 `max_concurrent_per_user` 개일 때 시작 → 429 `UPLOAD_LIMIT` + '내 PC에서 올리기' 진행 중 업로드 정리 안내 | |

## 4. 가져오기 — 대용량(h3d 30 GB)

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 4-1 | 상한 | 대시보드 상한이 20 GiB(기본)면 고를 때 빨간 줄 "릴레이 내려받기 상한을 넘습니다" + 버튼 비활성, API 직접이면 422 `SCX_FILE_TOO_LARGE{size, limit}`. 64 GiB 로 올린 뒤 정상 | |
| 4-2 | 여유 공간 | `upload_root` 여유 < h3d + `min_free_gb` 이면 507 `INSUFFICIENT_STORAGE` + "필요 · 현재 여유 · 남겨 둘 여유" | |
| 4-3 | 시간 | 30 GB: 대시보드 임시 받기 시간(라벨 `대시보드가 SCX에서 받는 중` 지속 시간)과 esl 로 스트리밍 시간 따로 기록. `hpc.scx.transfer_timeout_s`(14400) 안인지 | |
| 4-4 | 자원 | 워커 메모리가 파일 크기와 무관(스트리밍 — 수백 MB 이하)인지, 대시보드 임시 폴더가 끝난 뒤 비워지는지 | |
| 4-5 | 다른 작업 | 30 GB 받는 동안 다른 Case 의 추출·ESL 계산(SLOT·LIGHT 레인)이 막히지 않음 | |

## 5. 끊김·재시도·취소

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 5-1 | 자동 재시도 | h3d 받는 중 대시보드 백엔드를 잠시 재시작 → 작업 로그 `… s 뒤 다시(1/2)`, `scx_drive.retry_wait_s` 뒤 h3d 를 처음부터 다시 받음(Range 없음), 끝나면 성공 | |
| 5-2 | 실패 → [재시도] | 재시작이 `file_retries` 를 넘게 걸리면 작업 실패 + 사유. 대시보드 복구 후 [재시도] → 실패한 단계부터(rad·include 를 다시 받지 않음 — sha256 확인된 파일 건너뜀), h3d 는 처음부터 | |
| 5-3 | 취소 | h3d 받는 중 [취소] → 취소됨 + 이어받기 안내, h3d 행 사라짐(받은 rad 는 세션에 남음). [다른 파일 고르기] 또는 '진행 중인 업로드'에서 [취소]로 정리 | |
| 5-4 | 진행 중 잠금 | 내려받는 동안 그 세션에 파일 추가·complete·취소 → 409 `UPLOAD_SCX_BUSY` | |

## 6. 릴레이 다운

| # | 확인 | 방법 / 기대 | 결과 |
|---|---|---|---|
| 6-1 | 대시보드 중지 | 대시보드 백엔드 중지 → `health_ttl_s`(30 s) 안에 새 Case 를 다시 열면 SCX 탭 버튼 비활성 + 툴팁·패널 사유 "대시보드에 연결할 수 없습니다"(`SCX_RELAY_UNREACHABLE`), 다른 탭 정상 | |
| 6-2 | 릴레이 꺼짐 | `SIMDASH_SCX_RELAY_ENABLED=false` → `SCX_RELAY_DISABLED` / `SIMDASH_DRIVE_GATEWAY` ≠ scx → `SCX_DRIVE_MODE_OFF` / 비밀 불일치 → `SCX_RELAY_UNAUTHORIZED` | |
| 6-3 | SCX 재로그인 | 대시보드 SCX 세션 만료 → `SCX_AUTH_REQUIRED`(대시보드 관리 화면 재로그인 안내) | |
| 6-4 | 받는 중 다운 | 내려받기 중 대시보드 중지 → 재시도 뒤 실패 `SCX_RELAY_UNREACHABLE`, 복구 후 [재시도] 성공(5-2 와 같음) | |
| 6-5 | 복구 | 대시보드 재기동 → 30 s 안에 탭 다시 켜짐(esl 재시작 불필요) | |
