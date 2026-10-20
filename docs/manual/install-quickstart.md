# ESL 설치 단계별 가이드(운영 서버, 처음 한 번)

대시보드(simulation_workbench)·physicsai와 **같은 PC**, 인터넷(사내 프록시 포함)이 되는 경우의 git 폴더 설치. 상세·예외는 [admin.md](admin.md) §2.0·§2.6·§10. 폐쇄망은 admin.md §2.2~§2.4.

예시 경로: 대시보드 `E:\VD_SIMULATION_WEB\simdashboard`, ESL `E:\VD_SIMULATION_WEB\esl-platform`.

## 0. 준비
| 항목 | 내용 |
|---|---|
| 권한 | 일반 PowerShell(관리자 불필요) |
| 대시보드 | ESL 연결이 들어간 버전(simdashboard PR #56 — 사이드바 "등가정적하중"·`/esl` 프록시) |
| 비밀번호 | PostgreSQL `postgres` 관리자, 새로 정할 앱 역할 `esl_app` |
| ESL 루트 | Case 산출물 폴더(SPDM 밖, 공백·`& \| < > ^ % ! "` 금지). 기본 `<git 부모>\esl-data` |
| 입력 루트 | rad·extract CSV 폴더를 둘 공유 폴더(서버는 읽기만). 미리 만들어 둔다 |

## 1. 저장소 받기
```powershell
cd E:\VD_SIMULATION_WEB
git clone https://github.com/wgcha/esl-platform.git      # 이미 있으면: cd esl-platform; git checkout main; git pull --ff-only
mkdir E:\VD_SIMULATION_WEB\esl-input                      # 입력 루트(다른 공유 폴더면 그 경로)
```

## 2. 설치(처음 한 번 — 입력 루트는 이때 한 번만 지정)
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\VD_SIMULATION_WEB\esl-platform\deploy\setup.ps1 -DashboardRoot E:\VD_SIMULATION_WEB\simdashboard -InputRoots E:/VD_SIMULATION_WEB/esl-input
```
1. 확인 표를 본다: Python `cpython-3.12.13`, PostgreSQL host:port(대시보드와 같은 인스턴스), ESL 루트, 입력 루트, **대시보드 `.env` 추가 계획**(`VITE_ESL_TARGET`·`SIMDASH_ESL_ENABLED`).
2. `Y` 입력 후 Enter(빈 Enter는 다시 묻는다).
3. 비밀번호 2개(postgres, esl_app). 재실행 때 esl_app은 **처음 정한 값과 같게**(기존 연결로 접속되면 묻지 않음).
4. 성공 기준: 마지막에 `health OK` + 환경 점검 표 **FAIL 0** — `solver.backend auto → pardiso`, `solver.pypardiso` OK, `db.migration_head` 0004, `server.frontend_root` OK.

설치가 하는 일: `.runtime\`(venv·app·frontend·config·secrets) 생성, DB `esl`·역할 `esl_app`(없을 때만), migration, 작업 스케줄러 `ESL-Backend`·`ESL-Worker` 등록·시작, 대시보드 `.env`에 두 줄 추가(없을 때만, 백업 `.runtime\_backup\<UTC>\dashboard.env`).

## 3. 대시보드 재시작
대시보드 폴더에서 `stop.bat` → `start.bat`. `.env`에 아래 두 줄이 있는지 확인(다른 값이 이미 있으면 setup은 바꾸지 않고 경고만 한다):
```dotenv
VITE_ESL_TARGET=http://127.0.0.1:8110
SIMDASH_ESL_ENABLED=true
```
대시보드 백엔드를 8000이 아닌 포트로 띄우면 ESL 설정 `.runtime\config\esl_platform.yaml`의 `auth.dashboard_internal_url`을 그 포트로 바꾸고 ESL 작업을 재시작한다.

## 4. 접속 확인
- 대시보드 로그인 → 사이드바 "AI 예측" 아래 **"등가정적하중"** → ESL 화면에 이름·프로젝트 표시.
- 직접 주소: `http://<대시보드 주소>/esl/`. 서버 안에서 health: `http://127.0.0.1:8110/esl/api/health`.

## 5. 설정 확인(필요 시)
`.runtime\config\`:
- `esl_platform.yaml`: `storage.input_roots`(추가·변경), `worker.max_memory_gb`(운영 128).
- `esl.yaml`: 판정 기준 `validation`·`compare`(임시값 — 사내 기준으로 교체).
- `ista6.yaml`: 낙하 높이 표(비어 있음).

고친 뒤 재시작:
```powershell
Stop-ScheduledTask ESL-Worker; Stop-ScheduledTask ESL-Backend
Start-ScheduledTask ESL-Backend; Start-ScheduledTask ESL-Worker
```

## 6. 이후 코드 업데이트(인자 없이)
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\VD_SIMULATION_WEB\esl-platform\deploy\update-repo.ps1
```
git pull → 작업 중지 → 코드·프런트 교체 → migration → health. 입력 루트 등 설정은 저장된 값을 그대로 쓴다. 실행 중 작업이 있으면 멈추고 안내한다.

## 7. 점검·문제 해결
```powershell
E:\VD_SIMULATION_WEB\esl-platform\.runtime\venv\Scripts\python.exe E:\VD_SIMULATION_WEB\esl-platform\.runtime\app\esl_service.py check --runtime E:\VD_SIMULATION_WEB\esl-platform\.runtime
```
로그: `.runtime\logs\`. 막히면 콘솔 화면과 로그를 GitHub 이슈에 올린다.

## 8. 사용자 PC(TCL 추출)
서버 설치와 별개. 사용자 PC 클론에서 루트 `update.bat`(서버용 `deploy\update.bat`과 다름) → `%LOCALAPPDATA%\esl\app\current\ESL_extract.bat`에 원본 h3d를 끌어다 놓기 → 생긴 CSV 폴더와 `_0000.rad`(include 포함)를 서버 입력 루트 아래로 복사 → ESL 화면에서 새 Case.
