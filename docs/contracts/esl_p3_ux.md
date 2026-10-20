# 계약: P3-UX — 브라우저 입력 선택·업로드, 결과 받기, 버전 표기·업데이트 내역, 사용 가이드

- 상태: 확정 (2026-10-20, 사용자 요청: "경로 복사 붙여넣기 말고 브라우저로 찾아보고 선택", "결과 다시 가져오기", "버전 업데이트 표기·버전 게시판", "사용 가이드").
- P0 결정 "업로드 엔드포인트 없음"을 **이 계약으로 대체**한다(decisions.md 기록). 업로드는 아래 §1 규칙을 지키는 전용 경로 하나만 허용.

## 1. 입력 넣기 — 새 Case 화면에서 두 가지
### 1.1 내 PC에서 올리기(기본 탭)
- 브라우저 선택: ① rad 파일(`_0000.rad`)과 include 파일들(여러 개 선택 또는 폴더 선택 `webkitdirectory`), ② extract 결과 폴더(`ESL_extract.bat`이 만든 CSV 폴더 — 폴더 선택). 끌어다 놓기도 지원.
- 서버 저장 위치: 설정 `storage.upload_root`(절대경로, SPDM 밖, esl_root와 겹치지 않음, input_roots에 자동 포함되어 이후 선택 가능). 폴더 = `<upload_root>/<username>/<UTC yyyymmdd-HHMMSS>_<이름>/{rad,results}/`. 기존 파일 덮어쓰기 없음.
- 전송: 파일별 분할 업로드(청크 기본 16 MB, 설정), 중단 후 이어 올리기(서버가 받은 크기 응답), 파일별 sha256 검증, 진행률 표시. 업로드 세션 API:
  - `POST /uploads` `{project_id, name, files:[{rel, size, sha256?}]}` → `{upload_id, chunk_size}`(용량·확장자·이름 사전 검사)
  - `PUT /uploads/{id}/files/{index}?offset=` (application/octet-stream 청크, 순서 검증) → `{received}`
  - `GET /uploads/{id}` → 파일별 received/검증 상태
  - `POST /uploads/{id}/complete` → 서버 검사(rad 파싱으로 파트 목록·include 해석, results done.json·필수 CSV) → `{rad_path, results_dir, parts[], missing_includes[], problems[]}`. 누락 include가 있으면 화면에서 추가 업로드 후 다시 complete.
  - `DELETE /uploads/{id}`(미완료 세션 취소 — 받은 파일은 `_backup`으로 이동, 삭제 없음)
- 제한(설정): 확장자 허용 목록(`.rad .inc .k .csv .json .txt .tcl`), 파일당·업로드당 최대 크기(기본 20 GB·50 GB), 사용자당 동시 업로드 2, 이름 정규화(경로 구분자·`..`·제어문자·Windows 예약어 거부, 상대경로는 선택 폴더 기준만), realpath가 업로드 폴더 밖이면 거부. 권한: power 이상. CSRF 헤더 동일. multipart 사용 안 함(청크 PUT).
- 미완료 세션은 `upload.stale_hours`(기본 72) 후 `_backup`으로 이동(삭제 없음).

### 1.2 서버 폴더에서 고르기
- `GET /fs/browse?root=<input_root 인덱스>&path=<상대>` → `{roots:[{index,label,path}], entries:[{name, type:dir|file, size, mtime, hint:"rad"|"results"|null}]}` — input_roots(+upload_root) 안만, realpath 검사, 숨김·시스템 파일 제외, 항목 수 상한 표시(페이지네이션).
- 화면: 폴더 트리 + 목록, rad 파일 클릭 → rad 선택, `done.json` 있는 폴더 → 결과 폴더 선택. 경로 직접 입력칸은 '고급'으로 접어 둔다.

## 2. 결과 받기
- Case 화면(⑥ 및 상단 Case 메뉴)에 "결과 받기(zip)": `GET /cases/{id}/bundle?parts=export,report,summary` → 스트리밍 zip(`06_export/`, `07_report/report.html`, 주요 json·csv 요약). 크기 상한 `ui.max_bundle_bytes`(기본 5 GB), 초과 시 413 + 경로 안내. 대용량 npz는 기본 제외(`parts=raw` 선택 시 포함).
- 라이브러리 분석도 같은 방식(`GET /library/analyses/{id}/bundle`: 덱·보고서·csv).

## 3. 버전 표기·업데이트 내역(버전 게시판)
- 버전 원천: 저장소 `VERSION`(SemVer, 예 `0.4.0`)과 `CHANGELOG.md`(최신이 위, `## [0.4.0] - 2026-10-20` + 사용자용 항목: 추가/변경/수정). 배포 시 코드 스냅샷에 git 짧은 해시 기록(`.runtime/app/BUILD.json` {version, commit, built_at}).
- `GET /version` → `{version, commit, built_at}`; `GET /changelog` → `[{version, date, sections:{추가,변경,수정}:[...]}]`.
- 화면: 상단 바에 `v0.4.0` 표시(툴팁 commit·배포 시각). 새 버전이 마지막으로 본 버전보다 높으면 점 배지(localStorage). 클릭 → "업데이트 내역" 페이지(버전별 카드). physicsai·대시보드 톤과 같은 스타일.
- 규칙: 사용자에게 보이는 변경이 있는 PR은 CHANGELOG에 한 줄 이상 추가(테스트가 VERSION과 CHANGELOG 최상단 버전 일치를 검사).

## 4. 사용 가이드
- 화면 "사용 가이드"(상단 바 도움말 링크, 대시보드 HelpCenter와 같은 형식: 작업별 단계 카드 + 해당 화면 바로가기): Case란, PC에서 h3d 추출(update.bat·ESL_extract.bat), 새 Case(올리기/서버 폴더), ①~⑥ 단계별 의미·판단 기준, 결과 받기, 라이브러리 등록·종합분석·비드 덱, 버전 비교, 자주 묻는 질문.
- 같은 내용 문서 `docs/manual/user.md`.

## 5. 시험
- 업로드: 청크 순서·이어 올리기·sha256 불일치·용량·확장자·이름 공격(`..`, 절대경로, 예약어, 심링크)·권한·CSRF·업로드 폴더 밖 쓰기 0·complete 검사(누락 include 표시)·stale 정리(_backup 이동).
- browse: 루트 밖 탈출 불가, 심링크, 페이지네이션.
- bundle: zip 내용·크기 상한·경로 탈출.
- 버전: VERSION↔CHANGELOG 일치, API, 배지 로직.
- UI: 새 Case 두 탭 흐름(mock + 실서버 Playwright), 가이드·업데이트 내역 페이지, 주 버튼 1개 규칙.

## 6. 서버 측 h3d 추출 · 워커 동시 실행 (2026-10-20 사용자 확인)
- 확인: 운영 서버에 HyperView 2026.1·라이선스 있음. 사용자 PC 경로(예 `F:\Hyper_work`)는 서버에서 보이지 않음 → 서버 입력은 **업로드**(`storage.upload_root`, 예 `E:/VD_SIMULATION_WEB/esl-input`) 또는 그 안의 폴더 선택뿐. 산출물은 `storage.esl_root`(예 `E:/VD_SIMULATION_WEB/esl-data`). `storage.browse_spdm` 기본 false.
- Case 입력 = **rad(+include) 필수 + h3d 또는 추출 결과 폴더 중 하나**. 기본은 h3d(서버 추출), 결과 폴더는 대안(PC에서 `ESL_extract.bat`으로 미리 추출한 경우).
- `CASE_EXTRACT` 작업 첫 step `H3D_EXTRACT`(LOCAL, h3d 입력일 때만): 워커가 `commands.h3d_extract` argv 템플릿(argv[0] = `{hw}` → `altair.hw_exe_path`, P0 `esl.md` §4.4 규칙 — shell=False, 메타문자 거부)으로 `resources/tcl/esl_h3d_extract.tcl`(배포 스냅샷 안 경로)을 실행해 `<case>/01_extract/raw/`에 CSV를 만든 뒤 기존 pack 단계로 이어진다. h3d는 읽기만. 성공 판정 = 종료코드 0 + done.json ok. 실패 시 done.json의 failed_step·error·errorInfo를 step 로그·실패 코드(`H3D_EXTRACT_FAILED`)로.
- 설정: `altair.hw_exe_path`(기본 `C:/Program Files/Altair/2026.1/hwdesktop/hw/bin/win64/hw.exe`), `altair.max_concurrent_hw`(동시 hw 수, 기본 2 — 라이선스 한도에 맞춰 조정), 추출 옵션(part·hot_k·top_n)은 Case 값.
- 워커 동시 실행: `worker.slots`(SLOT 레인 동시 작업 수, 기본 2), LIGHT 레인 별도. 같은 Case 직렬화(기존 규칙)는 유지. GPU 사용 없음. 자원 제한(Job Object)은 작업별로 `max_memory_gb`·코어를 slots로 나눠 적용(설정 `worker.per_job_memory_gb` 우선).
- 환경 점검: `altair.hw_exe_path` 존재, TCL 존재, `worker.slots`.
- 사용자 PC 추출(update.bat·ESL_extract.bat)은 대안으로 유지.

## 7. 범위 밖(나중, P4)
- PBS/HPC 제출(OptiStruct 비드 덱 실행, 검증 낙하 Radioss) 및 결과 h3d 자동 Case 등록 — physicsai `hpc.*`·대시보드 SCX relay 구현을 참고해 별도 계약.

## 8. 대용량 h3d(최대 30 GB급) — 2026-10-20
- 상한 기본: 파일당 64 GB, 업로드당 100 GB(설정). 업로드 시작 시 upload_root 여유 공간 검사(필요량 + `upload.min_free_gb` 20) → 부족 507 `INSUFFICIENT_STORAGE`.
- 무결성: 청크별 sha256(`X-Chunk-Sha256`) + 서버 스트리밍 전체 sha256 기록. 브라우저 전체 해시 계산 없음. File.slice 스트리밍, 동시 2청크, 이어 올리기(서버 received 기준, 탭 재시작 후에도).
- 참고 시간: 30 GB ≈ 1 Gbps 약 5분, 100 Mbps 약 45분. 매우 큰 h3d는 PC에서 `ESL_extract.bat`으로 추출한 결과 폴더(수백 MB)만 올리는 대안을 가이드에 안내.

## 9. PC 추출 + 자동 올리기(대용량 대안을 편하게) — 2026-10-20
목적: 사용자는 PC에서 h3d·rad를 `ESL_extract.bat`에 끌어다 놓기만 하면, PC HyperView로 추출 → 결과 폴더(수백 MB)와 rad·include를 서버로 자동 업로드 → 브라우저에서 새 Case 화면이 업로드가 채워진 채로 열린다.

### 9.1 PC 연결(한 번만)
- ESL 화면 새 Case → 탭 "PC에서 추출해 올리기" → "PC 연결 코드 만들기"(power 이상): 6자리 코드, 15분 유효, **현재 프로젝트에 묶임**. 화면에 도구 설치 안내(저장소 루트 `update.bat`)와 코드 표시.
- `POST /client-tokens/codes` {project_id} → {code, expires_at}; `POST /client-tokens/exchange` {code, device_name} → {token, user, project, expires_at}(코드 1회용, 실패 5회 잠금). 토큰 `esl_ct_<random>` 서버엔 해시만 저장, 기본 30일(설정), 범위 = 해당 프로젝트 업로드 API(`/uploads*`)와 `/version`만. `GET /client-tokens`(내 토큰 목록), `DELETE /client-tokens/{id}`(폐기). 화면 "연결된 PC" 목록·폐기.
- 업로드 API는 세션 쿠키 또는 `Authorization: Bearer esl_ct_...`를 받는다(쿠키 없는 PC 도구용 — CSRF 헤더는 Bearer일 때 면제). 업로드 소유자 = 토큰 사용자.

### 9.2 PC 도구(`scripts/windows`, 루트 `update.bat`이 배포)
- `ESL_extract.bat`에 h3d와 rad를 함께 끌어다 놓기(또는 h3d만 → rad 파일 선택 창). 처음 실행 시 서버 주소(`esl_deploy.json` `server_url`, 예 `http://<대시보드 주소>/esl`)와 연결 코드를 묻고 토큰을 DPAPI로 암호화해 `%LOCALAPPDATA%\esl\client_token.bin`에 저장(평문 저장 금지). 토큰 만료·폐기 시 코드를 다시 묻는다.
- 순서: ① PC HyperView 추출(기존 3패스, 출력 `%USERPROFILE%\esl_work\<h3d 이름>\csv`) ② rad의 `/INCLUDE`·`#include`를 따라 include 파일 목록 수집(누락 시 경고, 계속 여부 질문) ③ 업로드(결과 폴더 + rad + include, 청크·이어 올리기·청크 sha256, 진행률 콘솔 표시) ④ complete → 브라우저로 `…/esl/p/<project>/cases/new?upload=<upload_id>` 열기(파트·이름 자동 채움, 사용자는 "Case 만들기"만).
- 업로드만 다시: `ESL_upload.bat <결과 폴더>`(추출 생략). 실패·중단 시 다시 실행하면 이어 올린다.
- h3d 원본 폴더에는 쓰지 않는다(기존 보호 규칙). 프록시: 서버 주소가 사내 주소이면 시스템 프록시 설정을 따른다(루프백 아님).

### 9.3 시험
- 코드 발급·교환·만료·1회용·잠금·폐기·범위(다른 API 403)·다른 프로젝트 업로드 거부·토큰 해시 저장.
- PC 도구: include 수집(상대·절대·Windows 매핑 실패 경고), 업로드 클라이언트(청크·이어 올리기·sha256 — pwsh로 Linux에서 실서버 대상 실행), 브라우저 열기 URL. ps1 PS 5.1 호환·CRLF·BOM.
- UI: PC 연결 탭(코드·연결된 PC·폐기), `?upload=` 진입 시 채워진 새 Case.

## 10. 구현 반영 (2026-10-20)
- 서버 추출 출력 위치: `<esl_root>/_h3d/<Case 폴더>/raw`(계약 §6의 `<case>/01_extract/raw` 대체 — 코어가 출력 폴더 안 입력 폴더를 거부하고 `01_extract`를 통째로 백업하므로). 재추출 전 이전 출력은 `_backup/<UTC>`로.
- Case 응답에 `input_kind`(h3d|results). `/queue`에 `running_all`·`slots`.
- PC 연결 코드 실패 잠금: 출발지(peer IP·신뢰 프록시의 X-Forwarded-For)로 구분 가능하면 출발지별 5회/15분, 구분 불가(모두 루프백 프록시)면 서버 전체 기준 30회/15분으로 완화(서비스 거부 방지) — 설정 `client_token.lock_*`.
- 보안 강화(Verifier 결함 수정): 백엔드 uvicorn `proxy_headers=False`(출발지 = 원래 TCP peer, XFF 는 peer 가 `client_token.trusted_proxies` 일 때만). 업로드 루트 아래는 찾아보기·Case 입력·경로 검사 모두 본인 사용자 폴더만(전역 관리자 전체), `_backup` 은 어느 깊이에서도 거부. complete: 업로드 밖 include 는 존재 여부와 무관하게 `업로드에 포함되지 않은 include: <원문>`(밖 파일은 읽지 않음). 업로드 쓰기: 기존 파일은 일반 파일·링크 수 1·실제 경로 안, 새 파일은 O_EXCL. PC 도구: rad 폴더 밖 절대경로 include 는 목록을 보여 주고 Y 확인 시에만 올림(-NonInteractive 는 제외). API 버전 = VERSION(런타임 BUILD.json).
