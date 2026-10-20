# 사용자 E2E 체크리스트 (ESL 서버 — Windows Server)

- 대상: 대시보드(simulation_workbench)·physicsai-platform과 **같은 Windows Server PC**(Python 3.12.13, PostgreSQL 18 같은 인스턴스, Caddy)
- 목적: 자동 시험(Linux, 합성 Case — `scripts/test-all`)으로 확인할 수 없는 실제 동작 확인. 배포 스크립트(`deploy/`)는 Windows에서 실행 검증되지 않았다(관리자 매뉴얼 §15).
- 기록: 각 항목 결과 칸에 `통과` / `실패(내용)` / `미수행`과 날짜, 확인한 실제 값(명령 출력·파일 이름)은 "메모"에 남긴다. 실패·미확정은 Plan에 전달한다.
- 입력 데이터: 사용자 PC에서 HyperView TCL(저장소 루트 `update.bat` → `ESL_extract.bat`)로 만든 rad + 결과 CSV 폴더를 서버 `storage.input_roots` 아래에 둔다. 처음에는 시연 모드(E0-8)의 합성 Case로 화면 흐름을 먼저 확인해도 된다.

## E0. 설치·환경 점검 (먼저 수행)

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E0-1 | (git 폴더) 일반 PowerShell에서 `deploy\setup.ps1 -DashboardRoot <대시보드>` 실행: Python 선택 줄이 대시보드 `cpython-3.12.13`, 확인 표(ESL 루트·입력 루트·PostgreSQL host:port — 대시보드 DB 사용자·비밀번호 출력 없음), 비밀번호 2개 입력, `.runtime\` 구성(venv·app·frontend·config 4개 파일·secrets·logs·state·`.gitignore`), DB `esl`·역할 `esl_app` 생성, migration head `0004`, 작업 `ESL-Backend`·`ESL-Worker` 등록(실행 시간 제한 없음·999회 재시작), health OK, 환경 점검 표 FAIL 0 | | |
| E0-2 | 환경 점검 표에서 `solver.backend` = `auto → pardiso`, `solver.pypardiso` OK(MKL 버전), `solver.cholmod` SKIP(Windows 제외), `storage.esl_root.write` OK, `worker.heartbeat` OK. `.runtime\secrets` 폴더 권한이 현재 사용자·SYSTEM만인지(`icacls .runtime\secrets`) | | |
| E0-3 | 재부팅(Interactive면 그 계정 로그온) 후 두 작업이 자동 시작되고 `http://127.0.0.1:8110/esl/api/health` 응답. `-RunMode Background`로 다시 설치해 로그온 없이 기동되는지(관리자 권한 필요 여부 메모) | | |
| E0-4 | `deploy\setup.ps1` 재실행: 비밀번호를 다시 묻지 않음(기존 연결 재사용), 설정 파일 사용자 수정값 유지, `_backup\<UTC>`에 이전 app·tasks XML | | |
| E0-5 | 연결(기본 — 대시보드 Vite 프록시 + 백엔드 정적 서빙): 설정 `server.frontend_root` = `<git>\.runtime\frontend`, 대시보드 `.env`에 `VITE_ESL_TARGET=http://127.0.0.1:8110`·`SIMDASH_ESL_ENABLED=true`(setup.ps1이 없을 때만 추가 — `_backup\<UTC>\dashboard.env` 사본, 다시 실행하면 "이미 들어 있음") → 대시보드 재시작 → `http://<대시보드 주소>/esl/` 접속, 대시보드 로그인 공유(이름·프로젝트 표시), 사이드바 ESL 버튼, `/esl/cases/...` 새로고침해도 화면 유지, `/esl` → `/esl/`, 이 PC `http://127.0.0.1:8110/esl/api/health` OK, 환경 점검 `server.frontend_root` OK. (Caddy를 쓰는 설치: Caddyfile에 `deploy\caddy\esl.caddy` + `ESL_PORT`·`ESL_FRONTEND_ROOT`로 같은 확인) | | |
| E0-6 | `deploy\update-repo.ps1`(git 폴더): 실행 중 작업이 있으면 중단 안내, 없으면 git pull → 작업 중지 → app·프런트 교체(프런트 소스 변경 없으면 Node 단계 없음) → migration → health → "업데이트 성공 — 접속: …" | | |
| E0-7 | (폐쇄망) 준비 PC `deploy\collect-offline.ps1 -DashboardRoot …` → `dist\esl-offline-<ver>.zip`(wheels 38개, pypardiso·mkl 포함) → 서버에서 `deploy\install.bat`(deploy.json) 설치, 이후 새 묶음으로 `deploy\update.bat`(저장소 루트 update.bat과 다른 파일) — venv·app·frontend가 `_backup`으로 이동 | | |
| E0-8 | (선택) 시연 모드: `deploy\demo\start-demo.bat -DashboardRoot …` → `http://127.0.0.1:8191/esl/` 자동 로그인, "①~⑥ 완료" Case 결과·보고서 보임 → `stop-demo.bat` | | |

## E1. ① 입력 ~ ⑥ 내보내기 (실제 Radioss 낙하 Case)

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E1-1 | ① rad 경로·결과 폴더 경로 "확인": 파트 목록·대상 파트(part_title 일치), include 목록, done.json ok·후보 프레임 수. input_roots 밖 경로·include는 `PATH_OUTSIDE_ROOT`로 거부(파일 내용 비노출) | | |
| E1-2 | ① Case 생성 → "추출 실행": 진행·step 로그, `01_extract`·`02_tstar` 생성, 22만 요소 규모 소요 시간·메모리 메모 | | |
| E1-3 | ② t*: 지표 토글(Max_Strain/Plastic), max-hold 곡선의 t* 표시, 후보 표에서 다른 프레임 선택 → "t* 확정" → ④⑤ stale 표시 | | |
| E1-4 | ③ 지지점: PCA 평면 산점·자동 3-2-1 노드·dof, 노드 ID 직접 입력(파트 밖 → `NODE_NOT_IN_PART`) → "지지점 저장" | | |
| E1-5 | ④ ESL 계산: 강체 회전각, ΣF·ΣM·평형 오차, 잡음 지표(`noise.force_rel`·`hotspot_strain_rel` — float32 H3D 잡음 바닥 경고 여부), F_eq 상위 표. 솔버 백엔드 pardiso(작업 로그) | | |
| E1-6 | ⑤ 검증: 변위 RMS·반력·hotspot 오차 표(제외 요소·사유), PASS/FAIL·fail_reasons, `full_solve` 판단(auto: 메모리 추정) | | |
| E1-7 | ⑤ 겹쳐보기: 레이어 Radioss ε / ESL ε / 오차 % 전환, 불투명도 슬라이더, 공통 색 범위, 비교 불가 요소 회색, hotspot 표시, 최대변형률 비교·분위수·히스토그램, 단면선(ξ/η, 배율 슬라이더) | | |
| E1-8 | ⑥ 내보내기: 대상 체크(inc·fem·csv) → `06_export`의 `esl_cload.inc`·`esl_bcs.inc`·`esl_force.fem`·csv, 다운로드·경로 복사. inc를 원본 Radioss 모델에 include해 정적 해석이 도는지(사용자 측) | | |
| E1-9 | 작업 취소: ② 이후 긴 작업(ESL·검증) 실행 중 취소 → 코어 프로세스 종료(작업 관리자에서 python 자식 확인), 상태 CANCELED, 다음 실행 때 부분 산출물 `_backup` | | |
| E1-10 | 입력 폴더(input_roots)에 아무 파일도 생기지 않음(실행 전후 목록 비교), SPDM 폴더 무변경 | | |

## E2. 보고서

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E2-1 | 검증 성공 후 Case 보고서 자동 생성(`07_report\report.html`, CASE_REPORT 작업) → ⑤ "보고서 보기"(새 탭): 입력 요약·t* 곡선·지지점·F_eq 상위·검증·재현 정확도·겹쳐보기·단면선·히스토그램 | | |
| E2-2 | 보고서 다운로드 파일을 인터넷 없는 PC·다른 브라우저에서 열어도 그림·표가 그대로(외부 의존 0), 라이트/다크 | | |
| E2-3 | 종합분석 보고서(E3-4)의 표지·씬 표·포락 맵·대표 케이스·덱 설정 요약·한계 절 | | |

## E3. 라이브러리·종합분석·덱

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E3-1 | ⑤ 결과 카드 "라이브러리 등록"(PASS) → 상단 "라이브러리" 목록에 모델·인치·씬(파일명 규칙 파싱 — drop_type·orient·round 등)·verdict·오차 표시. 파싱 실패 필드 메타 수정 | | |
| E3-2 | FAIL Case는 사유 입력 시에만 등록(power 이상), 같은 ESL 실행 중복 등록 `ENTRY_EXISTS`, retire 후 재등록 | | |
| E3-3 | 실제 씬 여러 개(가능하면 인치 2종 이상) 등록 → 필터(모델·씬·verdict) 동작 | | |
| E3-4 | 종합분석 생성(대상 모델·필터·정규화 모드·대표 수·목적 minmax) → LIB_ANALYZE 진행 → 요약(대표 씬·포락·통계)·보고서·덱 다운로드(`_analysis\<id>\opt\`) | | |
| E3-5 | 덱 `esl_bead*.fem`을 사용자 측에서 `optistruct -check`로 문법 확인(DTPG·DESOBJ minmax, OptiStruct 2026.1) — 결과 메모 | | |
| E3-6 | ISTA 6 면 번호·낙하 높이 표(`ista6.yaml` TODO)와 TV 포장 면 2/4·5/6 방향 가정 확인 → 설정 갱신 요청 | | |

## E4. 운영

| # | 확인 | 결과 | 메모 |
|---|---|---|---|
| E4-1 | 워커 작업 중 대시보드·physicsai 응답 속도(같은 PC 자원 경합 — ESL 워커는 Windows에서 우선순위·메모리 제한이 아직 없음, 관리자 매뉴얼 §15) | | |
| E4-2 | 로그 `<런타임>\logs\backend.log`·`worker.log` 회전(10 MB × 5), 비밀번호·DB URL이 로그에 없음 | | |
| E4-3 | DB 백업(`pg_dump -Fc esl`)·복원 리허설(ESL 루트와 같은 시점) | | |
