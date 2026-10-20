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
