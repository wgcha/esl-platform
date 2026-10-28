# 계약: 대용량 h3d 업로드 속도 — B 압축 모드(hvtrans 슬림 h3d) + A 전송 병렬화 + 업로드 목록 선택 지우기 (v0.6.0)

- 상태: **확정** (2026-10-28, 미결 Q1~Q3 확정 §13, 사용자 결정 2026-10-28: "결과 h3d가 20~50 GB. B+A 진행", 20:00 추가 요구: 업로드 목록 행별 선택·선택 지우기). 구현 코드 없음. 이 문서가 구현·검증의 원본이다.
- 버전 제안: **v0.6.0** (업로드 프로토콜 2 + PC 도구 기본 동작 변경 = 사용자에게 보이는 큰 변경).
- DB migration: **없음** (업로드 상태는 기존 `uploads.files` JSONB 안의 새 키로, Case 표시는 `uploads.result` 조회로. §6.5). MCP 예정 0009 영향 없음.
- 대체 범위: `esl_p3_ux.md` §1.1 "PUT … 순서 검증"·"청크 기본 16 MB", §8 "동시 2청크·서버 received 기준", §9.2 "ESL_extract = PC HyperView 추출 후 결과 폴더 업로드(기본)" → 이 문서 §4~§7로 대체. 충돌 시 이 문서 우선. 보안 규칙(§1.1·§10)은 그대로 유지·확장.
- 결정 번호 `US-n`, 시험 번호 `V-US-n`, 실기 확인 `P0-n`.

## 0. 사용자 결정 (2026-10-28)

1. 결과 h3d 20~50 GB. **B(보내는 양 줄이기) + A(전송 병렬화)** 둘 다.
2. B: PC에서 `hvtrans`로 **대상 파트 + Displacement·Max_Strain(Mid)·Plastic Strain(Mid) + 전 프레임**만 남긴 h3d를 만들어 올리고, 서버 추출(H3D_EXTRACT)은 그대로. 대상 파트 ID는 rad `/PART` title(서버와 같은 정규화 규칙)에서. **압축 모드 기본 ON**, 원본을 원하면 해제. 원본 h3d는 PC에 남음.
3. A: 청크 동시 3~4개·청크 32~64 MB(설정), 서버 위치 지정 쓰기·받은 청크 집합으로 이어 올리기·본문 스트리밍 저장 + 서버 sha256 스트리밍, complete 시 누락·크기 확인, 구 순차 클라이언트 호환, 보안 규칙 유지. 브라우저·PC 도구(PowerShell 5.1) 모두 병렬.
4. 도움말: 사용 가이드·새 Case 화면에 압축 모드 짧은 설명(무엇을 남기는지, 언제 해제하는지).
5. (20:00) 새 Case '내 PC에서 올리기' 파일 목록: 행별 체크박스 + 머리글 전체 선택(일부 선택 시 indeterminate). '지우기'는 **선택한 파일만** 제거, 선택 없으면 비활성 + 사유. 별도 '모두 지우기' 없음(전체 선택 후 지우기). 전송 중 파일은 선택 불가.

## 1. 현황 (main f44c2c5, v0.5.9)

| 항목 | 위치 | 현재 동작 |
|---|---|---|
| 경로 | 브라우저 → 대시보드 Vite 프록시(`/esl/api` → `127.0.0.1:8200`) → uvicorn 백엔드 1 프로세스 | PC 도구는 `server_url`(대시보드 주소 `/esl`)로 같은 경로 |
| 브라우저 업로더 | `frontend/src/lib/uploader.ts` | 청크 16 MB(서버 `chunk_size`), **PUT 동시 1개** + 다음 청크 미리 읽기·Web Crypto sha256 1개(PARALLEL=2 = 파이프라인 깊이). 409면 서버 `received`로 맞춤. 이어 올리기 = localStorage 세션 + 서버 `received` |
| 라우터 | `api/routers/uploads.py put_chunk` | `request.stream()`을 **청크 전체 bytearray로 메모리에 모은 뒤** `bytes()` 복사 → threadpool |
| 서비스 | `api/services/uploads.py put_chunk` | 업로드 행 `FOR UPDATE` 잠금 **안에서** 청크 sha256(1회) → `.part`에 append → 파일 전체 hasher.update(2회) → 마지막 청크면 sha256_expected 비교·rename. `offset == .part 크기`만 허용(409 `UPLOAD_OFFSET_MISMATCH` + received). 해시 상태는 프로세스 메모리 `_HASHES`(없으면 받은 부분 다시 읽기) |
| 쓰기 | `core/uploads.py append_chunk` | `O_APPEND`(새 파일 `O_EXCL`), 기존 파일은 열린 fd로 일반 파일·`st_nlink==1`·realpath 확인. 사전 할당·fsync 없음 |
| 설정 | `core/config.py UploadCfg` | `chunk_mb 16`(1..256), `max_file_bytes 64 GB`, `max_upload_bytes 100 GB`, `min_free_gb 20`, `max_files 5000`, `max_concurrent_per_user 2`, `stale_hours 72`, `allowed_ext` |
| DB | `uploads` (migration 0005) | `files` JSONB `[{rel,size,sha256_expected,sha256,done}]`, `result` JSONB(complete 검사, `h3d_path` 포함) |
| PC 도구 | `scripts/windows/esl_run.ps1`, `esl_upload_lib.ps1` | `ESL_extract.bat` = **PC HyperView로 추출 → 결과 CSV 폴더 + rad + include 업로드**(h3d 자체는 안 올림). `ESL_upload.bat <결과 폴더> [rad]`. 업로드 = `Send-EslFile` **완전 순차**(읽기 → sha256 → PUT → 응답 대기), HttpClient 1개, 청크 = 서버 `chunk_size`, 타임아웃 900 s, 5xx·429·네트워크 오류 지수 백오프. 토큰 DPAPI(`%LOCALAPPDATA%\esl\client_token.bin`), 범위 `/uploads*`·`/version` |
| 새 Case 화면 | `pages/newcase/{NewCase,UploadPanel,PcPanel}.tsx` | '내 PC에서 올리기' 목록 표(파일·크기·받음). **'지우기' = `reset()` 전체 초기화**(서버 세션은 취소하지 않고 남김). 올리기 시작 후 선택 칸 잠김 |
| 서버 추출 | `worker/esl_worker/h3d.py`, `resources/tcl/esl_h3d_extract.tcl` | 파트 = title(이름 정규화 비교) 또는 ID로 h3d component 찾기. 결과 기본 `Max_Strain`(XX YY ZZ XY, vonMises, layer Mid), `Plastic Strain`(Scalar value, Mid), `Displacement`(X Y Z), subcase 1, 전 프레임 |

### 1.1 병목 (20~50 GB 기준)

1. **양 자체**: 50 GB는 1 Gbps 이론치로도 ≈7분, 실효 30 MB/s면 ≈28분. 대상 파트(보통 전체 요소의 수 %)와 결과 3종만 필요한데 전 모델·전 결과를 보낸다 → **B가 가장 큰 이득**.
2. **한 번에 PUT 1개(정지-대기)**: 청크마다 왕복 + 서버 처리(본문 전량 버퍼링 → 복사 → sha256 2회 → 쓰기 → DB 커밋) 동안 링크가 논다. 프록시 1홉(Vite/node) 추가.
3. 서버 처리 중 **행 잠금 보유**: 쓰기·해시가 `FOR UPDATE` 안이라 같은 업로드의 청크를 겹칠 수 없다(설계상 순서 강제).
4. 서버 메모리: 청크 전체(16 MB) + `bytes()` 복사본. 64 MB로 키우면 요청당 128 MB.
5. PC 도구: 읽기·해시·전송이 직렬(겹침 없음). .NET Framework `ServicePointManager.DefaultConnectionLimit` 기본 2(병렬화 시 반드시 올려야 함).

## 2. 범위

- 포함: B 압축 모드(PC 도구), A 업로드 프로토콜 2(백엔드·브라우저·PC 도구), 업로드 메타(압축 정보) 기록·표시, 새 Case 화면 UX(압축 안내·대용량 권장 안내·목록 선택 지우기), 업로드 세션에서 파일 하나 빼기 API, 사용 가이드·`docs/manual/user.md` 갱신, 설정 키.
- 제외: 서버에서 hvtrans 실행(서버로 원본을 보내는 것이 병목이라 의미 없음), 브라우저에서 압축(브라우저는 hvtrans 실행 불가 → PC 도구 권장 안내만), HTTP/2·전용 전송 도구(rsync/SMB), 여러 파트 슬림(Case 1개 = 대상 파트 1개, 기존 규칙).

## 3. 결정 요약

| ID | 결정 |
|---|---|
| US-1 | 압축 모드 = PC 도구가 `hvtrans`로 슬림 h3d(대상 파트 1개 + 결과 3종 + 전 프레임)를 `work_root`에 만들고 **그 h3d + rad + include**를 올린다. 서버는 기존 h3d 입력 경로(H3D_EXTRACT) 그대로. |
| US-2 | `ESL_extract.bat`(h3d + rad 끌어다 놓기)의 **기본 = 압축 모드**. 실행 시 10초 카운트다운 질문 `[Enter=압축 / O=원본 / P=PC 추출(기존)]`(설정 `slim_prompt_sec`, 0 = 묻지 않고 기본값). 스위치 `/original` `/slim` `/pcextract`(스크립트용). 기존 PC 추출 동작은 `P`/`/pcextract`로 유지. |
| US-3 | **웹 체크 상태 → PC 도구 전달은 하지 않는다(도구 쪽 기본값 + 실행 시 질문)**. 근거: ① 서버 저장이면 사용자 설정 저장소가 없어 migration(`client_tokens`/`client_codes` 열 추가) + 토큰 범위 확장(`/client-tokens/self`)이 필요, ② 도구는 웹 화면과 다른 시점에 끌어다 놓기로 실행되므로 "그 실행"의 선택은 실행 창에서 하는 것이 정확, ③ 끌어다 놓기는 스위치를 붙일 수 없어 어차피 질문이 필요. 웹 체크박스(기본 ON, localStorage `esl.slim.v1`)는 **이 브라우저의 안내 기본값**으로, 해제하면 "실행 창에서 O(원본)를 누르세요 / `/original`" 안내로 바뀐다. 양쪽 기본 ON이라 동작은 일치. 실제로 어떤 모드로 올라왔는지는 업로드 메타로 웹에 보인다(US-8). |
| US-4 | 대상 파트 ID = PC 도구가 rad(+include)의 `/PART/<id>` 다음 title 줄을 읽어, 인자(또는 설정 `default_part`) title을 **서버 `match_parts` 규칙**(exact → 실패 시 `exact_ci`: `[\s_-]+`를 한 칸, 앞뒤 공백 제거, casefold)으로 찾는다. 숫자 인자는 `/PART` ID로 먼저 찾는다. 0개·2개 이상이면 후보 표(최대 40행) + ID 입력 또는 O(원본). |
| US-5 | hvtrans cfg는 PC 도구가 생성(형식 = physicsai 큐레이션 `hvtrans_cfg`: `BeginParts`/`Pool`, `BeginSubcase`/`BeginSimulation`, `datatype|comp`). 결과 이름·layer 표기·Radioss h3d component ID = rad part ID 여부는 **P0 실기 확인**. 실패하면 원본 업로드 안내(US-7). |
| US-6 | 슬림 h3d 검증(올리기 전, PC): 종료코드 0, 파일 존재·헤더 `HYPER3D`, 크기 < 원본, 설정 `slim_verify`(기본 true)면 기존 `esl_h3d_probe.tcl`로 component(파트 ID)·subcase가 보이는지 확인. |
| US-7 | 압축 실패(hvtrans 없음·종료코드≠0·시간 초과·출력 없음·헤더·검증 실패·파트 못 찾음) → 원인 1줄 + 로그 경로 + "원본(xx GB)을 올릴까요? [y/N]". 비대화형이면 올리지 않고 종료코드 1. 서버 쪽 실패(H3D_EXTRACT에서 파트·결과 없음)면 실패 메시지에 "압축 모드 h3d — 원본으로 다시 올리세요" 힌트. |
| US-8 | 압축 메타(원본 이름·크기·mtime, 슬림 크기, hvtrans 시간·버전, cfg 원문·sha256, 파트 ID·title, 결과 목록, 도구 버전)를 `POST /uploads` `files[].meta`로 보내 `uploads.files[i].meta`에 저장, complete 결과에 `h3d_meta`로 복사. Case 입력 요약에 **'압축 모드'** 배지 + "48.2 GB → 2.9 GB · hvtrans 6분 · 파트 1234". |
| US-9 | 슬림 업로드로 Case를 만들 때 rad 대상 파트 ID ≠ 메타 `part_id`면 422 `SLIM_PART_MISMATCH`("압축 모드 h3d에는 파트 1234(chassis_rear)만 있습니다 — 다른 파트는 원본 h3d로 올리세요"). Case의 파트를 바꾸는 다른 경로에도 같은 검사. |
| US-10 | 브라우저 '내 PC에서 올리기'에서 h3d가 `ui.upload_slim_hint_gb`(기본 5) 초과면 한 줄 안내: "큰 h3d(23.4 GB)입니다 — 'PC에서 추출해 올리기'(압축 모드)로 올리면 대상 파트·필요한 결과만 보내 훨씬 빠릅니다." 진행은 막지 않음. |
| US-11 | 업로드 **프로토콜 2**: 청크 k = `[k·C, min(size,(k+1)·C))`(C = 세션 생성 시 고정된 `chunk_size`). PUT은 **정렬된 청크 하나를 정확히** 덮어야 함(offset = k·C, 길이 = 기대 길이). 순서 무관·동시 허용(업로드당 동시 `upload.parallel`, 초과 429). 이미 받은 청크 → 200 `duplicate:true`(쓰지 않음). |
| US-12 | 서버 쓰기 = **본문 스트리밍 위치 지정 쓰기**: 청크 본문을 1 MB 단위로 읽어 `.part`의 k·C 위치에 직접 쓴다(요청당 메모리 ≤ 버퍼 2개). 행 잠금은 쓰기 **밖**에서 짧게(검사·청크 표시만). |
| US-13 | 이어 올리기 기준 = 서버 `files[i].got`(받은 청크 번호 범위 목록 `[[a,b),…]`). 응답 `received` = **앞에서부터 연속으로 받은 바이트**(구 클라이언트용 이어 올리기 offset), 새 필드 `received_total`·`chunks`(범위)·`n_chunks`. |
| US-14 | 파일 전체 sha256 = **해시 추적기**: 파일별 hasher가 "연속으로 받은 앞부분"을 따라가며 디스크(직후라 OS 캐시)에서 읽어 갱신. 마지막 청크를 받은 요청이 끝까지 따라잡고 `fsync` → 크기·sha256_expected 확인 → rename. 청크 sha256(`X-Chunk-Sha256`)은 스트리밍 중 계산해 비교(다르면 422, 받은 것으로 표시 안 함). |
| US-15 | 구 클라이언트 호환: 구 순차 클라이언트(현 PC 도구·현 브라우저 업로더)는 서버 `chunk_size`로 offset = received 순서로 보내므로 프로토콜 2에서 그대로 동작. 업그레이드 전 생성된 OPEN 세션(파일 항목에 `proto` 없음)은 **프로토콜 1(append) 경로 유지**. 새 클라이언트는 응답에 `protocol`이 없으면(구 서버) 순차로. |
| US-16 | 기본값: `upload.chunk_mb` 16 → **64**, `upload.parallel` **4**(1..8). 클라이언트 동시 수 = min(클라이언트 설정, 서버 `max_parallel`). |
| US-17 | 업로드 세션에서 파일 하나 빼기 `DELETE /uploads/{id}/files/{index}`: 항목은 지우지 않고 **`removed:true` 표시(index 유지 — 동시 PUT 경로 안정)**, 받은 부분(`.part`/완성 파일)은 `_backup`으로 이동. COMPLETED 업로드는 이 업로드 경로를 쓰는 Case가 없을 때만 허용하고 state → OPEN·result 비움(다시 complete = 재검사). |
| US-18 | 목록 UX: 행 체크박스 + 머리글 전체 선택(indeterminate), '지우기' = 선택한 파일만, 선택 없으면 비활성 + 사유 "지울 파일을 선택하세요". 전송 중인 파일 행은 체크박스 비활성(툴팁 "전송 중 — 멈춤 후 선택"). 전체를 선택해 지우면 서버 세션은 취소(`DELETE /uploads/{id}`, `_backup` 이동)하고 목록 비움 = 기존 '지우기'(전체 초기화)를 대체. 올리기 시작 후에도 전송 중이 아니면 선택 칸을 다시 열고 새로 고른 파일은 `POST /uploads/{id}/files`로 추가. |

## 4. B 설계 — 압축 모드

### 4.1 흐름 (`ESL_extract.bat <h3d> [<rad>] [<part>]`)

1. 인자 분류(기존) + 스위치 `/original`·`/slim`·`/pcextract`(대소문자 무시, 경로로 해석하지 않음).
2. rad 결정(끌어다 놓기 또는 선택 창). rad가 없으면 압축 불가 → 기존 "PC 추출만"으로(현재 동작과 같음).
3. 모드 결정: 스위치 > 질문(`slim_prompt_sec` 초 카운트다운, `[Console]::KeyAvailable` 폴링, 리다이렉트·비대화형이면 묻지 않음) > 설정 `upload_mode_default`(기본 `slim`). 콘솔 문구:
   `압축 모드로 올립니다: 파트 1234(chassis_rear) + 변위·최대 변형률(Mid)·소성 변형률(Mid) 전 프레임만 남긴 h3d (원본은 PC에 남음). [Enter=압축 / O=원본 / P=PC에서 추출] 10초 뒤 압축`
4. `slim`: 파트 ID 결정(§4.3) → cfg 생성(§4.2) → hvtrans 실행(§4.4) → 검증(US-6) → 업로드 계획 = `h3d/<stem>_slim.h3d`(meta 포함) + `rad/…` + include → 기존 `Invoke-EslPcUpload`(프로토콜 2 병렬, §5.5) → complete → 브라우저 `…/cases/new?upload=<id>`.
5. `original`: 업로드 계획 = `h3d/<원본 이름>.h3d` + rad + include(메타 `{kind:"h3d_original"}`만).
6. `pcextract`: 현재 동작 그대로(PC HyperView 추출 → 결과 폴더 업로드).
7. `ESL_upload.bat`: 인자가 **결과 폴더**면 현재 동작, **h3d + rad**면 4~5와 같은 모드 결정(pcextract 제외). 중단 후 다시 실행하면 이어 올림(키 = 원본 h3d 경로, 슬림 파일 재사용 §4.5).

### 4.2 hvtrans cfg 생성 규칙

- 문법은 **physicsai 큐레이션 생성기(`hvtrans_cfg`)를 그대로 옮긴다**(Impl-PC가 physicsai 저장소에서 블록 이름·구분자·주석 규칙을 확인해 복사, 코드 복사가 아니라 형식만). 구조(개략, 정확한 키워드는 P0-1):

```
BeginParts
  Pool <component pool 이름>          # Radioss h3d의 component pool (P0-2)
  <part_id>                           # 대상 파트 1개
EndParts
BeginSubcase <subcase>                # 설정 slim_subcase: "all"(기본) | 번호
  BeginSimulation all                 # 전 프레임 (P0-1: 'all' 표기)
  EndSimulation
  Displacement|all                    # datatype|comp — comp 'all' = 모든 성분 (P0-3)
  Max_Strain|all                      # layer Mid 표기 위치는 P0-3 (예: "Max_Strain (Mid)" 또는 별도 layer 줄)
  Plastic Strain|all
EndSubcase
```

- 결과 목록은 설정 `slim_results`(기본 = 서버 TCL 기본값과 같은 `Displacement`, `Max_Strain`@Mid, `Plastic Strain`@Mid). 성분은 'all'로 남겨 표기 위험을 줄인다(크기 차이 작음). **PC 기본값 = TCL 기본값**을 정적 시험으로 고정(V-US-22).
- cfg 파일: `<work_root>\<stem>\slim\esl_slim.cfg`(UTF-8 BOM 없음, CRLF — P0-1에서 hvtrans가 요구하는 인코딩 확인). 경로에 `%!&` 금지(기존 규칙).
- 원본에 Plastic Strain이 없는 탄성 해석: hvtrans가 없는 결과로 실패하면(P0-3) Plastic Strain을 뺀 cfg로 1회 재시도하고 메타 `results`에 실제 남긴 것만 기록(서버 TCL은 epsp 없음 = 0 처리 경로가 이미 있음 — 원본 업로드와 같은 결과).

### 4.3 대상 파트 ID (US-4)

- rad 읽기: `Get-EslRadIncludes`가 모은 rad + include 파일에서 `/PART/<id>` 줄(Radioss 블록 키워드, 앞 공백 허용)과 바로 다음 비주석 줄(title, `#` 주석 줄 건너뜀)을 읽는다. 읽기만, 큰 rad는 스트리밍(줄 단위) — 서버 `list_parts`와 같은 결과여야 함(V-US-21: 같은 시험 rad로 서버 `list_parts`와 비교).
- 매칭: 서버 `api/services/system.py match_parts`와 같은 규칙(exact: 연속 공백 1칸·앞뒤 제거 후 같음, 실패 시 exact_ci: `[\s_-]+` → 한 칸, casefold). 숫자 인자는 ID 일치 우선, 없으면 title로.
- 결과는 메타 `part_id`·`part_title`(rad 원문 title)로 기록 — Case 화면 파트 자동 채움은 기존(complete의 parts) 그대로.

### 4.4 hvtrans 실행

- 실행 파일: 설정 `hvtrans_exe`(기본 `C:/Program Files/Altair/2026.1/hwdesktop/io/result_readers/bin/win64/hvtrans.exe`, `update.bat`이 없는 키만 기본값으로 채움). 없으면 US-7.
- 명령(argv, shell 없음): `hvtrans.exe -c <cfg> <h3d> <h3d> -o <slim.h3d> -zh0`. 작업 폴더 = `slim\`, stdout/stderr → `slim\hvtrans.log`, `slim\hvtrans_stderr.log`. 시간 제한 `slim_timeout_min`(기본 120) 초과 시 프로세스 종료 + US-7.
- 출력 위치: `<work_root>\<stem>\slim\<stem>_slim.h3d`. 기존 `Assert-OutputAllowed`(h3d 폴더·protected_roots 아래 금지)·`Assert-InputOutsideDeploy` 그대로 적용. 원본 h3d는 읽기만.
- 여유 공간: `work_root` 드라이브 여유 < `slim_min_free_gb`(기본 20)면 시작 전 중단 + US-7.
- 진행 표시: hvtrans 진행률을 알 수 없으므로 경과 시간·출력 파일 크기를 2초마다 1줄 갱신.

### 4.5 재사용·이어 올리기

- `slim\esl_slim.json` = {원본 경로·크기·mtime, cfg sha256, part_id, 슬림 크기·sha 없음(크기만), hvtrans 시간, 생성 시각}. 다음 실행 때 원본(경로·크기·mtime)·cfg sha256이 같고 슬림 파일 크기가 같으면 hvtrans 생략.
- 업로드 상태 키(`Get-EslUploadKey`)는 원본 h3d 경로 기준(기존) — 슬림을 다시 만들었으면(크기 다름) 세션 비교(`Compare-EslSession`)가 불일치로 새 세션.

### 4.6 업로드 메타 (US-8)

`POST /uploads` `files[i].meta` (선택, `.h3d` 파일에만 허용, JSON 직렬화 ≤ 16 KB, 정의 밖 키 거부):

| 키 | 형식 | 설명 |
|---|---|---|
| `kind` | `"h3d_slim"` \| `"h3d_original"` | 필수 |
| `v` | 1 | 메타 버전 |
| `source_name` | str ≤255 | 원본 파일 이름(경로 아님 — PC 경로는 서버에 남기지 않음) |
| `source_bytes`, `source_mtime` | int, ISO8601 | 원본 크기·수정 시각 |
| `slim_bytes` | int | 슬림 크기(= 파일 size와 같아야 함, 다르면 422) |
| `hvtrans_sec` | number | hvtrans 실행 시간 |
| `hvtrans_version` | str ≤64 \| null | `hvtrans.exe` 파일 버전 |
| `cfg` | str ≤ 8192 | cfg 원문 |
| `cfg_sha256` | hex64 | |
| `part_id` | int | 대상 파트 |
| `part_title` | str ≤200 | rad 원문 title |
| `results` | [{type ≤64, layer ≤32 \| null}] ≤ 8 | 실제 남긴 결과 |
| `frames` | `"all"` | |
| `tool_version` | str ≤32 | PC 도구 버전(VERSION) |

- 서버는 표시·검사용으로만 신뢰한다(파일 내용과 대조하지 않음). 잘못된 메타는 결국 H3D_EXTRACT 실패로 드러난다(US-7 힌트).
- complete 결과 `h3d_meta`(= 그 h3d 파일의 meta 또는 null). Case 응답 `input_h3d_meta`(§6.5).

## 5. A 설계 — 업로드 프로토콜 2

### 5.1 API 변경

| API | 변경 |
|---|---|
| `POST /uploads` | 요청 `files[].meta?`(§4.6), `client?: {name ≤32, version ≤32}`(로그용). 응답(UploadOut)에 `protocol: 2`, `chunk_size`(이 세션 고정 C), `max_parallel`. |
| `GET /uploads/{id}`, 목록 | 파일별 `received`(연속 앞부분 바이트 — 의미 유지), **`received_total`**, **`chunks: [[a,b),…]`**(받은 청크 번호 범위), **`n_chunks`**, **`removed`**, **`meta`**. 상위 `received_bytes` = 제거되지 않은 파일의 `received_total` 합, `total_bytes` = 제거되지 않은 파일 합, `protocol`(1 = 업그레이드 전 세션). |
| `PUT /uploads/{id}/files/{index}?offset=` | 프로토콜 2 규칙(§5.2). 헤더 `Content-Length` **필수**(없으면 411 `LENGTH_REQUIRED`), `X-Chunk-Sha256` 선택(기존). 응답 `{index, received, received_total, chunk, duplicate, done, sha256}`. |
| `POST /uploads/{id}/complete` | 누락 검사 강화: 제거되지 않은 모든 파일이 done이고 디스크 크기 = 선언 크기. 아니면 409 `UPLOAD_INCOMPLETE` `{pending:[{index, rel, missing:[[a,b),…]}]}`(≤100). 결과에 `h3d_meta`. 제거된 파일은 검사 대상 아님. |
| **신규** `DELETE /uploads/{id}/files/{index}` | US-17. 응답 UploadOut. 오류: 404, 409 `UPLOAD_FILE_BUSY`(그 파일 청크가 쓰는 중), 409 `UPLOAD_IN_USE`(COMPLETED이고 Case가 이 업로드 폴더 경로를 입력으로 씀), 409 `UPLOAD_CLOSED`(CANCELED/STALE). 이미 removed면 200(멱등). |
| `POST /uploads/{id}/files` | 제거된 항목의 rel은 중복 검사에서 제외(같은 이름으로 다시 추가 가능 — 이전 파일은 `_backup`에 있음). 새 항목은 세션의 C·`proto:2`. |
| `ui` 설정 응답 | `ui.upload_slim_hint_gb`를 프런트가 읽는 기존 설정 경로로 노출(없으면 `POST /uploads` 응답이 아닌 `GET /version`과 같은 공개 설정 응답에 추가 — Impl-Backend가 현재 프런트가 ui.* 값을 받는 곳에 맞춘다). |

- 권한·소유자·토큰 범위·CSRF: 기존 그대로(`DELETE /uploads/{id}/files/{index}`도 `/uploads/` 아래라 PC 토큰 범위 안, 쿠키면 CSRF 헤더 `X-ESL-Request` 필수, Bearer 면제).

### 5.2 PUT 규칙 (프로토콜 2)

1. **본문 읽기 전 사전 검사**(DB 읽기만, 잠금 없음): 소유·권한·OPEN, index 범위, 파일 removed면 409 `UPLOAD_FILE_REMOVED`·done이면 409 `UPLOAD_FILE_DONE`(기존), `offset % C == 0`이고 `k = offset / C < n_chunks`(아니면 409 `UPLOAD_OFFSET_MISMATCH` + `received`), `Content-Length == expected_len(k)`(아니면 422 `CHUNK_LENGTH_MISMATCH`, 마지막 청크만 짧음), Content-Type octet-stream.
2. k가 이미 `got`에 있으면 **본문을 읽어 버리고(≤C)** 200 `duplicate:true`(쓰기 없음).
3. 같은 (upload, index, k)가 이 프로세스에서 쓰는 중이면 409 `CHUNK_IN_FLIGHT`(클라이언트는 잠시 뒤 상태 확인). 업로드당 쓰는 중 청크 수 ≥ `upload.parallel`이면 429 `UPLOAD_PARALLEL_LIMIT` + `Retry-After: 1`. (프로세스 메모리 집합 + `threading.Lock`; 백엔드는 1 프로세스 — 기존 `_HASHES`와 같은 전제, 시작 시 workers=1 확인.)
4. 스트리밍 쓰기: `.part`를 연다(§5.3) → `request.stream()` 조각을 `upload.write_buffer_kb`(기본 1024) 단위로 모아 threadpool에서 위치 지정 쓰기, 동시에 청크 sha256 갱신. 받은 길이 > 기대 길이면 즉시 413 `CHUNK_TOO_LARGE`, 연결이 끊기거나 짧으면 표시하지 않고 종료(재전송이 덮어씀).
5. 헤더 sha256이 있고 다르면 422 `CHUNK_SHA256_MISMATCH`(쓴 바이트는 표시 안 했으므로 다음 재전송이 덮어씀).
6. 짧은 트랜잭션: 업로드 행 `FOR UPDATE` → 다시 OPEN·not removed 확인 → `got`에 k 병합 → 커밋(잠금 수 ms).
7. 해시 추적기 진행(US-14, 비차단 try-lock). 모든 청크가 모였으면 이 요청이 마무리(§5.4).

### 5.3 위치 지정 쓰기 (`core/uploads.py write_chunk_at`)

- 열기: 새 `.part`는 첫 PUT 또는 세션 생성 시 `O_CREAT|O_EXCL|O_WRONLY|O_BINARY`(+ POSIX `O_NOFOLLOW`)로 만들고 **`os.ftruncate(fd, size)`로 사전 할당**. 이후 요청마다 `O_WRONLY|O_BINARY`(`O_APPEND` 아님)로 새 fd → `fstat`으로 일반 파일·`st_nlink == 1` 확인 → realpath가 업로드 폴더 안인지 확인(기존 `append_chunk` 검사 그대로). `target_path`의 성분 심링크 검사도 그대로.
- 쓰기: POSIX면 `os.pwrite(fd, buf, pos)`. **Windows(운영 서버)는 `os.pwrite`가 없으므로 요청별 fd에서 `os.lseek(fd, pos, SEEK_SET)` 후 `os.write` 반복**(fd는 요청마다 따로 열어 파일 위치가 공유되지 않음 → 동시 요청 안전). `msvcrt`/Win32 직접 호출 없음.
- NTFS 메모: `SetEndOfFile`(ftruncate)은 공간을 예약하고 0 채우기는 미룬다. Valid Data Length보다 뒤에 쓰면 그 사이를 동기적으로 0으로 채우므로, **클라이언트는 청크를 번호 순서로 내보낸다**(동시 창 안에서만 뒤섞임 → 0 채움 ≤ (parallel−1)·C). 이어 올리기에서 생긴 구멍도 앞쪽부터 채움. 실측 P0-8.
- 사전 할당 실패(디스크 부족) → 507 `INSUFFICIENT_STORAGE`(기존 코드).
- fsync: 청크마다 하지 않음. 파일 마무리 때 1회.

### 5.4 받은 청크 집합·마무리·재시작

- 파일 항목(JSONB) 새 키: `proto: 2`, `chunk: C`, `got: [[a,b),…]`(정렬·병합, 순서대로 보내면 1~2개 구간), `removed: false`, `meta`.
- 마무리(마지막 청크를 표시한 요청, 또는 complete/GET이 "다 모였는데 done 아님"을 보면 호출 — 멱등): 파일별 Lock(차단)으로 해시를 끝까지 따라잡음 → `fsync` → `os.fstat` 크기 = size → sha256_expected 비교(다르면 기존처럼 `.part`를 `_backup/…mismatch`로 옮기고 `got` 비움, 422 `SHA256_MISMATCH`) → 최종 이름이 이미 있으면 409 `UPLOAD_FILE_EXISTS` → `os.rename` → 행 잠금 트랜잭션에서 `done:true, sha256`.
- 해시 추적기: `_HASHES[(upload,index)] = (hasher, upto_bytes)`. 연속 앞부분 끝까지 1 MB씩 `.part`를 읽어 갱신. 프로세스 재시작으로 없으면 0부터 다시 읽어 복원(기존 `_hash_state`와 같은 방식). 순서대로 보내면 읽는 범위는 직전에 쓴 OS 캐시.
- 재시작: DB `got`은 디스크에 쓴 뒤에만 표시되므로 "표시됨 ⊂ 실제로 쓴 것"(프로세스 비정상 종료 시 OS 캐시는 남음). OS 자체가 죽어 표시된 청크 내용이 사라진 경우는 마무리 sha256(sha256_expected가 있을 때)·청크 sha 없는 경우 파일 sha 기록으로 감지 범위 제한 — 리스크 R4.
- 프로토콜 1 세션(업그레이드 전 OPEN, 항목에 `proto` 없음): 기존 append 경로·`.part` 크기 기준 received·409 규칙 그대로(코드 경로 유지, `stale_hours` 72 뒤 자연 소멸). 응답 `protocol: 1`, 새 클라이언트는 순차로.

### 5.5 클라이언트

**브라우저 (`frontend/src/lib/uploader.ts`)**
- 동시 수 = min(`max_parallel`, 4). 작업 큐 = 파일 순서 → 청크 번호 순서(받은 범위는 건너뜀). 각 작업: `File.slice` → (Web Crypto 가능하면) ArrayBuffer 읽기 + sha256 → 같은 ArrayBuffer를 본문으로(두 번 읽지 않음). Web Crypto가 없는 비보안 http면 Blob 그대로(메모리 거의 0).
- 메모리 상한 ≈ (동시 수 + 미리 해시 1) × C ≈ 320 MB(C 64 MB). 
- 응답 처리: 200(duplicate 포함) → 범위 갱신. 409 `UPLOAD_OFFSET_MISMATCH`·`CHUNK_IN_FLIGHT` → `GET /uploads/{id}`로 범위 다시 맞춤. 429 → `Retry-After` 뒤 재시도(재시도 횟수에 안 셈). 422 `CHUNK_SHA256_MISMATCH`·5xx·네트워크 → 그 청크만 백오프 재시도(청크별 최대 `maxRetries`). 422 `SHA256_MISMATCH` → 그 파일 처음부터(1회). 507·기타 4xx → 전체 멈춤 + 오류.
- 진행률: 받은 바이트 = 서버 `received_total` + 현재 성공한 청크. 속도는 최근 10초 이동 평균.
- `stop()`: 새 청크를 내보내지 않고 진행 중 PUT은 AbortController로 취소. 이어 올리기 = 서버 `chunks`.
- 구 서버(`protocol` 없음): 기존 순차 로직(남겨 둠).
- `remove(indexes)`(US-17/18): 큐에서 빼고 서버 DELETE 호출.

**PC 도구 (`esl_upload_lib.ps1`, PowerShell 5.1)**
- 시작 시 `[Net.ServicePointManager]::DefaultConnectionLimit = [Math]::Max(현재, parallel*2+2)`(HttpClient 만들기 전).
- 단일 runspace에서 `HttpClient.SendAsync` Task를 최대 N개 띄우고 `[Threading.Tasks.Task]::WaitAny($tasks, 500)`로 완료를 처리. 메인 루프가 그 사이 다음 청크를 `FileStream`에서 읽고 `SHA256`(다음 버퍼) 계산 → 슬롯이 비면 보냄. 버퍼 N+1개(64 MB × 5 = 320 MB) 재사용.
- 청크 단위 재시도·백오프(`Invoke-EslHttp`의 블로킹 재시도 대신 청크 상태 기계), 401 → 기존 인증 오류. 응답 처리 규칙은 브라우저와 같음.
- `HttpClient.Timeout`: 청크 64 MB·느린 망 대비 기존 900 s 유지.
- 진행 표시 `Show-EslProgress` 그대로(동시 전송 수 표시 추가 `×4`). Ctrl+C 후 다시 실행 = 서버 `chunks` 기준.
- 구 서버(`protocol` 없음) → 기존 `Send-EslFile` 순차 경로.
- 설정 `upload_parallel`(기본 4, 1 = 순차와 같음).

### 5.6 DB·migration

- **migration 없음**. 모든 새 상태는 `uploads.files` JSONB 항목 키(`proto, chunk, got, removed, meta`)와 `uploads.result`(`h3d_meta`). 체크 제약(`jsonb_typeof(files)='array'`) 그대로. `total_bytes`는 제거 시 다시 계산해 갱신.
- 청크마다 행 UPDATE(파일 50 GB / 64 MB ≈ 800회, 각 수 ms, `got` 구간 몇 개라 행 크기 작음).
- Case → 업로드 메타 조회: `result->>'h3d_path' = cases.h3d_path`인 COMPLETED 업로드(업로드 행 수가 작아 인덱스 불필요, 목록은 IN 한 번).

## 6. 화면·도구 UX

### 6.1 새 Case — 'PC에서 추출해 올리기' 탭 (`PcPanel.tsx`)

- 연결 안내 아래 체크박스 **☑ 압축 모드(권장)** — 기본 ON, localStorage `esl.slim.v1`.
- 도움말 2줄(체크박스 아래 small):
  - "대상 파트와 변위·최대 변형률(Mid)·소성 변형률(Mid)의 전 프레임만 남긴 h3d를 PC에서 만들어 올립니다(보통 원본의 수 %). 원본 h3d는 PC에 그대로 남습니다."
  - "다른 파트나 다른 결과로 다시 해석할 계획이면 해제하세요 — 그때는 원본 h3d가 필요합니다."
- 사용법 줄: ON → "`ESL_extract.bat`에 h3d와 rad를 끌어다 놓으세요(실행 창에서 Enter = 압축)." OFF → "실행 창에서 **O**를 누르면 원본을 올립니다(스크립트: `ESL_extract.bat /original …`)." (US-3: 체크 상태는 서버·도구에 전달되지 않음을 툴팁에 명시: "PC 도구는 실행할 때 묻습니다.")

### 6.2 새 Case — '내 PC에서 올리기' 탭 (`UploadPanel.tsx`)

- h3d 선택 시 크기 > `ui.upload_slim_hint_gb` → h3d 칸 아래 안내 1줄(US-10) + 'PC에서 추출해 올리기' 탭으로 가는 링크 버튼(텍스트 링크, 주 버튼 아님).
- 예상 시간 문구: `ASSUMED_BPS` 30 MB/s → 실측 속도 표시는 그대로, 가정 속도 상수는 병렬 기준 60 MB/s로(문구 "사내망 60 MB/s 가정").
- **목록 선택(US-18)**:
  - 표 첫 열 체크박스, 머리글 체크박스 = 전체 선택/해제(선택 가능한 행 기준), 일부만이면 `indeterminate`. `aria-label` "파일 선택"/"전체 선택".
  - 선택 불가 행: 지금 전송 중인 파일(업로더가 그 파일 청크를 보내는 중), 'completing' 단계 전체. 툴팁 "전송 중 — 멈춤 후 선택".
  - 요약 줄의 '지우기' 버튼: 선택 0개면 비활성 + 옆 사유 "지울 파일을 선택하세요". 라벨 "지우기(n)".
  - 동작:
    | 상태 | 선택 일부 | 전체 선택 |
    |---|---|---|
    | 세션 없음(올리기 전) | 목록에서만 제거 | 목록 비움(= 기존 초기화) |
    | 세션 OPEN(멈춤·오류·올림·검사 실패, 또는 업로드 중 비전송 파일) | 업로더 큐에서 빼고 파일마다 `DELETE /uploads/{id}/files/{index}` → 목록에서 제거 → 결과(result) 비움, 전송이 남았으면 이어 올리기 버튼 | `DELETE /uploads/{id}`(세션 취소, `_backup`) → 목록 비움·세션 잊기(localStorage) |
    | COMPLETED(Case 만들기 전) | 파일별 DELETE → 서버 state OPEN → 자동으로 `complete` 다시(재검사) → 결과 갱신 | 세션 취소 시도: COMPLETED는 기존 규칙상 취소 불가(409 `UPLOAD_COMPLETED`) → 파일 전부 DELETE(Case 미사용이면 허용) 후 목록 비움 |
    | 409 `UPLOAD_IN_USE` | 오류 줄 "이 업로드로 만든 Case가 있어 뺄 수 없습니다" | 같음 |
  - 지운 뒤 선택 칸(DropZone)은 전송 중이 아니면 다시 열림. 세션이 있으면 새 파일은 `addUploadFiles`로 추가 후 이어 올리기.
  - 별도 '모두 지우기' 버튼 없음. 기존 `reset()`은 "전체 선택 + 지우기" 경로로 흡수.
- PC 업로드(`?upload=`) 진입 화면: 기존 그대로 + 메타가 있으면 배지 **압축 모드** 또는 **원본** + "48.2 GB → 2.9 GB · hvtrans 6분 12초 · 파트 1234 chassis_rear".

### 6.3 Case 입력 요약 (① `stages/Stage1.tsx` 등 입력 요약 위치)

- `input_kind = H3D`이고 `input_h3d_meta.kind = h3d_slim` → 배지 "압축 모드" + 툴팁(원본 이름·크기 → 슬림 크기, hvtrans 시간, 남긴 결과, cfg 보기 접힘). `h3d_original`/null → 표시 없음(기존).

### 6.4 PC 도구 콘솔

- 시작 시 모드 질문(US-2), 압축 단계 `==> [slim] 파트 1234(chassis_rear) · 결과 3종 · 전 프레임`, `hvtrans 실행 중… 3:12 경과, 출력 1.8 GB`, 완료 `48.2 GB → 2.9 GB (6.0%), 6분 12초`. 업로드 진행 줄에 `×4`.
- 실패 시 US-7 문구 + `slim\hvtrans.log` 경로.

### 6.5 Case 응답

- `case_out`에 `input_h3d_meta`(위 조회, 없으면 null). `case.json`에도 `h3d_mode: slim|original|null` 기록(새 Case부터).

### 6.6 도움말

- 사용 가이드(`pages/guide/content.ts`) "PC에서 h3d 추출·올리기" 카드에 압축 모드 3줄(무엇을 남기는지, 원본은 PC에 남음, 해제 시점 = 다른 파트·다른 결과로 재해석). "대용량 h3d" FAQ 갱신(병렬 전송, 압축 모드 권장, 5 GB 안내). 같은 내용 `docs/manual/user.md`.

## 7. 설정 키

**서버 `esl_platform*.yaml`**

| 키 | 기본 | 범위 | 설명 |
|---|---|---|---|
| `upload.chunk_mb` | **64**(기존 16) | 8..256 | 새 세션 청크 크기 C(세션에 고정) |
| `upload.parallel` | **4** | 1..8 | 업로드당 동시 청크(초과 429), 응답 `max_parallel` |
| `upload.write_buffer_kb` | 1024 | 64..8192 | 스트리밍 쓰기 단위 |
| `upload.preallocate` | true | bool | `.part` 사전 할당(ftruncate) |
| `ui.upload_slim_hint_gb` | 5 | ≥0(0 = 안내 끔) | 브라우저 대용량 h3d 안내 임계 |

- 기존 `max_file_bytes 64 GB`·`max_upload_bytes 100 GB`·`min_free_gb`·`max_concurrent_per_user 2` 그대로. 예제 yaml 두 개 갱신.

**PC `%LOCALAPPDATA%\esl\esl_deploy.json`** (`update.bat`이 없는 키만 기본값으로 추가)

| 키 | 기본 |
|---|---|
| `hvtrans_exe` | `C:/Program Files/Altair/2026.1/hwdesktop/io/result_readers/bin/win64/hvtrans.exe` |
| `upload_mode_default` | `slim` (`slim`·`original`·`pcextract`) |
| `slim_prompt_sec` | 10 (0 = 묻지 않음) |
| `slim_results` | `[{"type":"Displacement"},{"type":"Max_Strain","layer":"Mid"},{"type":"Plastic Strain","layer":"Mid"}]` |
| `slim_subcase` | `all` |
| `slim_verify` | true |
| `slim_timeout_min` | 120 |
| `slim_min_free_gb` | 20 |
| `upload_parallel` | 4 |

## 8. 시험

| ID | 내용 | 담당 |
|---|---|---|
| V-US-1 | 순서 뒤섞임: 청크를 무작위 순열(마지막 청크 먼저 포함)로 보내 최종 파일 바이트·sha256이 원본과 같음, `received`(연속 앞부분)·`received_total`·`chunks` 값 | Backend |
| V-US-2 | 중복: 받은 청크 재전송 → 200 `duplicate`·쓰기 없음(mtime·내용 불변), 같은 청크 동시 2요청 → 하나는 409 `CHUNK_IN_FLIGHT`, 손상 청크(sha 불일치)가 이미 받은 청크를 덮지 않음 | Backend |
| V-US-3 | 누락: 구멍 있는 채로 complete → 409 `UPLOAD_INCOMPLETE` + 파일별 missing 범위, 디스크 크기 ≠ 선언 크기 감지 | Backend |
| V-US-4 | 재시작: 일부 청크 후 앱 재생성(해시 상태 소실) → 남은 청크만 보내 완료, sha256 정확. 디스크엔 썼지만 표시 전 중단된 청크 → 재전송이 덮어씀 | Backend |
| V-US-5 | 길이·위치: 정렬 안 된 offset·범위 밖 k → 409, 길이 불일치 → 422, Content-Length 없음 → 411, 선언보다 긴 본문 → 413(디스크 표시 없음), 중간 끊김 → 표시 없음 | Backend |
| V-US-6 | 동시 제한: parallel+1번째 → 429 + Retry-After, 요청당 서버 메모리 ≤ 8 MB(64 MB 청크, tracemalloc) | Backend |
| V-US-7 | 호환: 현재 main의 PC 클라이언트 시험(`tests/windows/test_pc_upload_client.py`)·브라우저 순차 경로가 새 서버에서 그대로 통과. 업그레이드 전 OPEN 세션(proto 없음) 이어 올리기 = append 경로 | Backend·PC |
| V-US-8 | 새 클라이언트 + 구 서버(`protocol` 없음, 가짜 서버) → 순차 | Frontend·PC |
| V-US-9 | 보안: `..`·절대경로·예약어 rel, `.part` 하드 링크(nlink 2)·심링크·폴더 바꿔치기 → `PATH_UNSAFE`, 다른 사용자 업로드 404, PC 토큰 다른 프로젝트 404, 쿠키 + CSRF 헤더 없음 403, Bearer 면제, 마무리 시 최종 이름 존재 → 409, 사전 할당 실패 → 507 | Backend |
| V-US-10 | sha256_expected 불일치 → `_backup/…mismatch` 이동·`got` 비움·처음부터 | Backend |
| V-US-11 | Windows 위치 지정 쓰기(lseek+write, 동시 fd)와 NTFS 사전 할당 — 운영 서버 실기(P0-8), Linux CI는 pwrite 경로 + `os.pwrite` 없는 경로를 monkeypatch로 | Backend |
| V-US-12 | 브라우저 업로더 단위: 동시 상한, 번호 순서 발송, 429 백오프(재시도 수 제외), 범위로 이어 올리기, stop 시 Abort, 버퍼 수 ≤ N+1, sha 없음(비보안 http) 경로 | Frontend |
| V-US-13 | PC 업로더: 가짜 서버(`esl_fake_upload_server.py`에 지연·순서 뒤섞임·429·5xx·연결 끊김 주입) 대상 pwsh 병렬 전송, `DefaultConnectionLimit` 설정 확인, 중단 후 재실행 이어 올리기, PS 5.1 문법·CRLF·BOM | PC |
| V-US-14 | 성능(§9): 10 GB 합성 파일, parallel 1·2·4 × C 16·32·64, 브라우저·PC 각각, 서버 CPU·메모리 기록 — 운영망 실측 | 통합 |
| V-US-20 | cfg 생성 골든(파트 ID, 결과 3종, subcase all, Plastic Strain 없는 재시도 cfg) | PC |
| V-US-21 | rad `/PART` → ID: exact, 정규화(`Chassis_Rear`·`chassis-rear`·`CHASSIS  REAR`), 모호, 없음, 숫자 인자, include 안 파트, 주석 줄 — 같은 rad로 서버 `list_parts`/`match_parts` 결과와 일치 | PC·Backend |
| V-US-22 | PC 기본 `slim_results` = TCL 기본(`strain_type`·`strain_layer`·`epsp_type`·`epsp_layer`·`disp_type`) 정적 비교 | PC |
| V-US-23 | 압축 실패: hvtrans 없음·종료코드≠0·시간 초과·출력 없음·헤더 아님·검증 실패·여유 공간 부족 → 질문(대화형) / 종료코드 1·업로드 없음(비대화형). 원본 h3d 폴더에 쓰기 0 | PC |
| V-US-24 | 메타: `.h3d` 외 파일 meta → 422, 16 KB 초과·모르는 키 → 422, `slim_bytes ≠ size` → 422, complete `h3d_meta`, Case `input_h3d_meta`·`SLIM_PART_MISMATCH` | Backend |
| V-US-25 | **동일성(P0 실기)**: 같은 h3d의 원본 vs 슬림을 서버 H3D_EXTRACT → `model.csv`·`elems.csv`·프레임·변위·변형률·소성 CSV 같음(수치 ≤1e-6 상대), done.json `n_frames`·`frame0_time` 같음, ①~⑤ 결과 같음 | 통합 |
| V-US-26 | UI: 압축 체크 기본 ON·localStorage·안내 문구 전환, 5 GB 초과 안내, `?upload=` 화면·Stage1 배지 | Frontend |
| V-US-30 | 목록 선택: 행 체크·머리글 전체/해제·일부 → indeterminate, 선택 0 → '지우기' 비활성 + 사유, 전송 중 행 비활성 | Frontend |
| V-US-31 | 선택 지우기 동작: 세션 없음(목록만), OPEN 일부(DELETE 호출·큐 제외·이어 올리기), OPEN 전체(세션 취소·localStorage 정리), COMPLETED 일부(DELETE 후 자동 재검사), `UPLOAD_IN_USE` 오류 표시, 지운 뒤 같은 이름 다시 추가 | Frontend |
| V-US-32 | 파일 빼기 API: removed 표시·index 유지·`_backup` 이동(삭제 없음)·total 재계산, 그 파일 PUT → 409 `UPLOAD_FILE_REMOVED`, 쓰는 중 → 409 `UPLOAD_FILE_BUSY`, COMPLETED + Case 사용 → 409 `UPLOAD_IN_USE`, 미사용 → OPEN·result null, 멱등, 권한·토큰 범위 | Backend |

## 9. 성능 목표

| 항목 | 목표 |
|---|---|
| A 처리량(1 Gbps 사내망) | 브라우저·PC 도구 모두 지속 ≥ 80 MB/s, 그리고 같은 망에서 현재(v0.5.9) 순차 대비 ≥ 2배(V-US-14에서 기준선 먼저 측정) |
| A 서버 자원 | 진행 중 PUT당 메모리 ≤ 8 MB, 행 잠금 보유 ≤ 50 ms/청크, 100 MB/s에서 CPU ≤ 1코어(sha256 2회 포함) |
| A 클라이언트 메모리 | 브라우저 ≤ (N+1)·C ≈ 320 MB, PC ≤ 400 MB |
| B 크기 | 슬림 ≤ 원본의 15%(P0-5 실측으로 확정, 대상 파트 비중에 비례) |
| B 전체 시간 | hvtrans + 슬림 업로드 ≤ 원본 업로드(병렬)의 40% (50 GB 기준) |
| 이어 올리기 | 중단 후 재개 시 다시 보내는 양 ≤ N·C(진행 중이던 청크만) |

## 10. 파일 소유 (병렬 구현)

| 담당 | 파일 |
|---|---|
| **Impl-Backend** | `backend/esl_platform/core/uploads.py`(write_chunk_at·preallocate·파일 빼기 이동), `api/services/uploads.py`(프로토콜 2·해시 추적기·마무리·파일 빼기·메타), `api/routers/uploads.py`(스트리밍 PUT·DELETE file), `api/schemas.py`(Upload* 스키마·meta·Case `input_h3d_meta`), `core/config.py`(UploadCfg·UiCfg 키), `config/esl_platform.example.yaml`·`esl_platform.prod.example.yaml`, `api/services/cases.py`·`api/services/common.py`(SLIM_PART_MISMATCH·input_h3d_meta·case.json h3d_mode), `worker/esl_worker/h3d.py`(실패 힌트), `docs/contracts/openapi_p1b.json` 재생성, `backend/tests/test_upload_speed.py`(신규), 기존 `test_p3_ux*.py` 수정 |
| **Impl-Frontend** | `frontend/src/lib/uploader.ts`, `src/api/p3.ts`·`src/api/types.ts`, `src/pages/newcase/{UploadPanel,PcPanel,NewCase}.tsx`, `src/stages/Stage1.tsx`(배지), `src/pages/guide/content.ts`, `src/mock/{server,data}.ts`, `src/styles.css`, `src/__tests__/`(uploader·p3), `docs/manual/user.md` |
| **Impl-PC** | `scripts/windows/esl_upload_lib.ps1`(병렬 전송·메타), `scripts/windows/esl_run.ps1`(모드·질문·스위치), **신규** `scripts/windows/esl_slim_lib.ps1`(rad PART 읽기·cfg 생성·hvtrans 실행·검증·재사용), `scripts/windows/esl_deploy_lib.ps1`·`update.ps1`(설정 기본값·새 ps1 배포 목록), `tests/windows/*`(가짜 서버 확장·pwsh 시험) |
| 통합(Plan/병합) | `VERSION`(0.6.0), `CHANGELOG.md`, `docs/decisions.md`, 이 계약의 구현 반영 절 |

- 경계 계약: API 형식(§5.1)·메타 스키마(§4.6)·오류 코드는 이 문서가 원본. Frontend·PC는 Backend 완료 전 가짜 서버/모의로 개발.

## 11. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R1 | hvtrans cfg 문법·결과 이름·layer 표기가 2026.1 Radioss h3d와 다름 | P0-1·P0-3 실기 먼저, 실패 시 원본 업로드 경로 항상 열림(US-7) |
| R2 | h3d component ID ≠ rad part ID(Radioss 변환 규칙) | P0-2. 다르면 cfg를 component **이름**(title) 기준으로(hvtrans가 이름 선택을 지원하는지 함께 확인), 둘 다 안 되면 압축 모드 보류·원본 기본 |
| R3 | 슬림 h3d에서 서버 추출 결과가 달라짐(노드 좌표·프레임 시간·frame 0 변위·요소 연결 누락) | V-US-25 동일성 시험 통과 전엔 기본 ON 배포 금지(통과 못 하면 `upload_mode_default: original`로 배포) |
| R4 | OS 비정상 종료로 표시된 청크 내용 유실 | 마무리 sha256(PC 도구는 전체 sha 미계산 — 청크 sha만) 한계. 필요 시 마무리 전 fsync 후 청크 sha 재확인은 후속 |
| R5 | NTFS VDL 0 채우기로 뒤 청크 쓰기가 느림 | 번호 순서 발송, P0-8 실측. 문제면 `upload.preallocate: false` |
| R6 | 대시보드 Vite 프록시가 동시 대용량 요청에서 병목·타임아웃 | P0-7 실측. 필요 시 업로드만 백엔드 포트로 직결하는 경로는 별도 결정(보안 검토 필요) |
| R7 | 웹 체크박스가 도구 동작을 바꾸지 않는다는 오해 | 툴팁·안내 문구로 명시, 업로드 메타 배지로 실제 모드 표시. 동기화 요구 시 미결 Q1 |
| R8 | hvtrans가 HyperWorks 라이선스 유닛을 쓰거나 메모리 과다 | P0-6 실측, 가이드에 기록 |

## 12. 실기 확인 P0 (구현 전·중 운영 PC/서버에서)

| ID | 확인 | 실패 시 |
|---|---|---|
| P0-1 | hvtrans 2026.1 cfg 문법(블록 키워드, Pool 줄, 전 프레임 `BeginSimulation` 표기, 인코딩·줄바꿈), `-zh0` 의미, 종료코드 규칙 | physicsai 큐레이션 cfg로 맞춤, 안 되면 압축 모드 보류 |
| P0-2 | Radioss h3d component ID = rad `/PART` ID인지(+ component 이름 = /PART title인지) | R2 |
| P0-3 | 결과 이름·layer 표기: `Displacement`, `Max_Strain` + layer `Mid`, `Plastic Strain` + `Mid`가 hvtrans cfg에서 어떻게 쓰이는지, 없는 결과 지정 시 동작 | §4.2 재시도 규칙 조정 |
| P0-4 | 슬림 h3d를 서버 TCL이 읽을 때 component 이름·노드 ID·요소 연결·프레임 수·시간 라벨·frame 0 좌표가 원본과 같은지 → V-US-25 | R3 |
| P0-5 | 20~50 GB 실제 h3d 2개 이상: hvtrans 시간·최대 메모리·슬림 크기 비율 | §9 목표 갱신 |
| P0-6 | hvtrans 라이선스 사용 여부·동시 실행 | 가이드 기록 |
| P0-7 | 대시보드 Vite 프록시 경유 병렬 PUT(4×64 MB) 처리량·타임아웃·본문 크기 제한 | R6 |
| P0-8 | 운영 서버(Windows, NTFS) 사전 할당 + lseek/write 동시 쓰기 처리량, VDL 0 채우기 영향 | R5 |

## 13. 미결 → 확정 (사용자 결정 2026-10-28) · 변경 메모

- Q1 확정: **웹 체크 상태는 PC 도구에 전달하지 않는다**(migration 없음, `client_tokens.prefs`·토큰 범위 확장 없음). US-3 그대로. 웹 체크박스는 이 브라우저의 안내 기본값.
- Q2 확정: **기존 PC 추출(CSV 결과 폴더 업로드)은 선택지로 계속 유지**한다(`P`/`/pcextract`, 폐기 일정 없음).
- Q3 확정: **PC 도구 기본값은 압축(ON)** (`upload_mode_default: slim`). V-US-25 동일성은 실기 확인(P0)으로 남기되 기본값은 압축.
- 변경 메모(백엔드 구현 반영, 2026-10-28):
  - 요청 `UploadMeta`는 `kind`만 필수, `h3d_slim`이면 `part_id` 필수(없으면 422 `UPLOAD_META_INVALID`). 메타는 JSON(UTF-8) ≤ 16 KB·정의 밖 키 거부·`.h3d`에만·`slim_bytes`=size. `POST /uploads`의 `client{name,version}`은 로그 + 세션에 보관(아래 v0.6.0 통합 메모).
  - `complete` 누락 응답 `pending`은 객체 목록 `{index, rel, missing:[[a,b),…]}` — `missing`은 **청크 번호** 범위(프로토콜 1 파일은 `[[받은 청크 수, n_chunks)]`). 디스크 크기가 선언과 다른 완료 파일도 전체 누락으로 보고.
  - `UploadFileOut`: `received`(연속 앞부분 바이트)·`received_total`·`chunks`([[a,b),…] 청크 번호)·`n_chunks`·`removed`·`meta`. `UploadOut`: `protocol`(1 = 업그레이드 전 세션)·`chunk_size`·`max_parallel`·`problems_count`(complete 검사 문제 + 누락 include 수). `UploadChunkOut`: `{index, received, received_total, chunk, duplicate, done, sha256}`.
  - PUT(프로토콜 2) 순서: Content-Type(415) → 소유·OPEN·index(404)·removed(409 `UPLOAD_FILE_REMOVED`)·done(409 `UPLOAD_FILE_DONE`)·정렬/범위(409 `UPLOAD_OFFSET_MISMATCH` + `received`·`chunk_size`)·Content-Length 없음(411 `LENGTH_REQUIRED`)·>C(413 `CHUNK_TOO_LARGE`)·≠기대 길이(422 `CHUNK_LENGTH_MISMATCH`) → 이미 받은 청크면 본문 버리고 200 `duplicate:true` → 같은 청크 쓰는 중 409 `CHUNK_IN_FLIGHT`·동시 수 ≥ `upload.parallel`이면 429 `UPLOAD_PARALLEL_LIMIT`+`Retry-After: 1`. 본문이 기대 길이보다 길면 스트리밍 중 413, 짧거나 끊기면 표시 없음(`CHUNK_LENGTH_MISMATCH`/연결 끊김). 청크 sha 불일치 422 `CHUNK_SHA256_MISMATCH`. 마지막 청크 요청이 마무리(`SHA256_MISMATCH` 422·`UPLOAD_SIZE_MISMATCH` 422·`UPLOAD_FILE_EXISTS` 409·디스크 부족 507).
  - `upload.chunk_mb` 허용 범위는 계약의 8..256 대신 **1..256**(시험용 작은 청크). 기본 64.
  - `ui.upload_slim_hint_gb`는 `GET /version` 응답의 `ui: {upload_slim_hint_gb}`로 전달.
  - 파일 빼기는 항목에 `removed:true, done:false, got:[]`; 이동 위치 `_backup/<사용자>/<업로드 폴더>__<rel>.removed`(+`.part`). `UPLOAD_IN_USE` 판정 = rad·결과·h3d 경로가 이 업로드 폴더 안인 Case 존재.
  - Case: `input_h3d_meta`(H3D 입력만, `uploads.result.h3d_path` 대조), `case.json`의 `h3d_mode: slim|original|null`, `SLIM_PART_MISMATCH`는 Case 생성과 `PATCH part_title`(H3D·슬림 메타)에서 검사. 추출 작업 params `h3d.slim`이 true면 워커 실패 메시지에 원본 재업로드 힌트.
  - 이슈 #29: `UPLOAD_LIMIT`(429)의 detail에 `open_uploads:[{id,name,created_at,received_bytes,total_bytes,problems_count}]`, 메시지 "진행 중인 업로드 세션이 N개입니다(사용자당 최대 M개, 계산 대기열과 별개) — 새 Case 화면의 '진행 중인 업로드'에서 이어서 하거나 취소하세요". 한도(`max_concurrent_per_user` 2)·`stale_hours` 72 유지.
  - 알려진 한계: 진행 중 청크·해시 상태는 프로세스 메모리(백엔드 1 프로세스 전제). 구 클라이언트가 요청 중복을 보내 `CHUNK_IN_FLIGHT`(409, `received` 없음)를 받을 수 있음(타임아웃 재시도 직후에만 — 구 PC 도구는 GET으로 상태를 다시 맞춤).
- v0.6.0 통합 정합(2026-10-28, release/v0.6.0): `UploadOut.client: {name, version} | null` 추가 — 만들 때 받은 `client`를 DB migration 없이 `uploads.files[]` 항목에 보관(추가 파일은 이어받음, `UploadFileOut`에는 노출 안 함), 없으면 null. 웹 `?upload=` 화면 배지는 `client.name = esl-pc`면 "PC에서 올림", 아니면 "브라우저에서 올림". 웹은 `UPLOAD_LIMIT` detail `open_uploads`(서버 키 그대로)를 읽고, 새 세션 청크는 응답 `chunk_size`(없을 때만 64 MB). PC 도구 `files[].meta`·`client={name:'esl-pc',version}`은 서버 `UploadCreate`·`_check_meta`로 시험(tests/windows/test_pc_slim.py).
