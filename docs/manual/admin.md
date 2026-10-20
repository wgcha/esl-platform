# ESL 플랫폼 관리자 매뉴얼(서버 설치·운영)

- 대상: ESL 서버(백엔드·워커)를 설치·운영하는 서버 관리자, 전역 관리자(대시보드 `is_global_admin`)
- 기준: 브랜치 `claude/dreamy-newton-xvutyl`(2026-10-19), 패키지 버전 `0.1.0`, DB migration head `0004`(0001 → 0002 → 0003 → 0004)
- 근거 문서: 계약 [esl_platform_p1b.md](../contracts/esl_platform_p1b.md)(플랫폼), [esl_p2_library.md](../contracts/esl_p2_library.md)(라이브러리·분석·보고서), [esl.md](../contracts/esl.md)(원형), [E2E 체크리스트](../e2e-checklist.md).
- 같은 서버의 **physicsai-platform 관리자 매뉴얼과 같은 절차·같은 절 번호**를 쓴다(해당 없는 §5~§9·§11은 생략). 운영자는 두 플랫폼을 같은 순서로 설치·업데이트한다.

> 배포 스크립트(`deploy/`)는 **실제 Windows에서 실행 검증되지 않았다**(Linux에서 pwsh 7 파싱·순수 함수·실행기·시연 E2E만 시험). 첫 설치는 E2E 체크리스트 E0-1~E0-8을 함께 기록하면서 진행한다.

> **두 가지 "업데이트"를 구분한다.** 저장소 루트의 `update.bat`(→ `scripts\windows\update.ps1`)은 **사용자 PC**에서 HyperView TCL(`ESL_probe.bat`·`ESL_extract.bat`)을 배포하는 것이다(README §2.1). 이 매뉴얼의 서버 설치·업데이트는 모두 `deploy\` 아래(`setup.ps1`·`update-repo.ps1`·`install.bat`·`update.bat`)다.

---

## 1. 구성 개요

### 1.1 구성 요소

| 구성 요소 | 실행 형태 | 역할 | 기본 위치·포트 |
|---|---|---|---|
| 프런트엔드 | 정적 파일(Vite build, base `/esl/`) | 화면 ①~⑥·라이브러리·분석. 대시보드 Caddy가 서빙(§2.6.1) | git 폴더 설치 `<git>\.runtime\frontend`, 묶음 `<install_root>\frontend`(= `deploy.json` `caddy_frontend_root`) |
| 백엔드(API) | 실행기 `esl_service.py backend`(uvicorn, `esl_platform.api.main`) | 입력 검증·권한·작업 생성·조회·보고서. **외부 프로그램을 실행하지 않는다** | `127.0.0.1:8110`, 접두 `/esl/api` |
| 워커 | 실행기 `esl_service.py worker`(`esl_worker`) | 대기열 claim, 코어(`esl.pipeline.run`)를 자식 프로세스(spawn)로 실행, 취소, 보고서·라이브러리 분석 | PC당 1개 |
| DB | PostgreSQL 18(대시보드와 **같은 인스턴스, 별도** DB `esl`·역할 `esl_app`) | Case·작업·결과 요약. 대용량 배열은 파일 | 대시보드 `.env` `DATABASE_URL`의 host·port |
| 산출물 | 파일 시스템 | Case 폴더(`<esl_root>\<case>\01_extract`~`07_report`), 라이브러리 `_library`, 분석 `_analysis` | `storage.esl_root` |

```text
브라우저 ── http://<대시보드 주소>/esl/…   (같은 origin → 대시보드 세션 쿠키 analysis_canvas_session 이 함께 전송)
   │
대시보드 Caddy ─┬─ /esl/api/*  → ESL 백엔드 127.0.0.1:8110 (deploy\caddy\esl.caddy)
               ├─ /esl/*      → 프런트 정적 파일(ESL_FRONTEND_ROOT, strip_prefix /esl, SPA index.html)
               ├─ /physicsai/* → PhysicsAI(별도 스니펫)
               └─ 그 밖        → 대시보드(기존)
ESL 백엔드 ── GET /api/auth/me, /api/projects ──▶ 대시보드 백엔드(루프백 127.0.0.1:8000)
     │
PostgreSQL `esl` ◀── claim/renew/release ── esl_worker ── spawn ── esl.pipeline(extract·tstar·esl·validate·export·report) / esl.library
```

### 1.2 대시보드와의 관계

- **같은 Windows Server PC**에서 대시보드(simulation_workbench)·physicsai-platform과 나란히 돈다. 실행 환경도 같다: Python **3.12.13**(대시보드 `.tools\python\cpython-3.12.13-*`), PostgreSQL **18**(같은 인스턴스), Node **22.23.2**(프런트 빌드 때만).
- 로그인 공유: 사용자는 대시보드에서 로그인한다. ESL 백엔드는 쿠키 토큰으로 대시보드 `GET /api/auth/me`를 호출해 사용자·역할을 확인한다(30초 캐시, `auth.*`). 권한은 대시보드 역할 그대로(조회 = ACTIVE 사용자, 실행 = 프로젝트 `power`·`admin`, 전역 관리 = `is_global_admin`).
- **대시보드 쪽 요청 사항(이 저장소 밖)**: physicsai와 같은 패턴으로 대시보드 `.env`에 `SIMDASH_ESL_ENABLED=true`를 두면 대시보드 메뉴에 ESL 링크가 보이도록(physicsai `SIMDASH_PHYSICSAI_ENABLED`와 같은 방식) — 대시보드 저장소 변경이 필요하다(README "서버 배포" 요청 사항). Caddy 대신 대시보드 Vite 프록시를 쓰는 구성이면 `VITE_ESL_TARGET=http://127.0.0.1:8110`로 `/esl` 전체를 백엔드에 넘기는 프록시도 대시보드 쪽에 필요하다(§2.6.2).

### 1.3 경로 `/esl/`

- 백엔드 라우트 접두 `{server.base_path}/api`(기본 `/esl/api`)와 프런트 빌드 base `/esl/`(frontend/vite.config.ts)는 같아야 한다. `server.base_path`를 바꾸지 않는다.

---

## 2. 설치

설치 방식은 둘이다(physicsai와 같음). **대시보드와 같은 PC에 인터넷(사내 프록시 포함)이 되면 §2.0 git 폴더 설치**(권장). §2.2~§2.4 오프라인 묶음은 인터넷이 안 되는 **폐쇄망 서버용**이다. §2.1·§2.5~§2.8은 공통.

### 2.0 같은 PC·git 폴더 설치(권장)

저장소를 받은 git 폴더에 그대로 설치한다. **일반 Windows PowerShell**(관리자 권한 불필요)에서:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\VD_SIMULATION_WEB\esl-platform\deploy\setup.ps1        # 설치(다시 실행해도 안전)
powershell -NoProfile -ExecutionPolicy Bypass -File E:\VD_SIMULATION_WEB\esl-platform\deploy\update-repo.ps1  # 업데이트(§3.0, git pull 포함)
```

- **관리자 권한이 필요 없다**: 머신 환경변수를 쓰지 않는다. DB 접속 정보(앱 비밀번호 포함 URL)는 `.runtime\secrets\database_url` 한 파일에 두고 상속을 끊어 **현재 사용자·SYSTEM만** 읽게 한다(`icacls` — 실패하면 경고만). 설정은 `.runtime\config\esl_platform.yaml`.
- **실행기**: 플랫폼 코드는 환경변수(`ESL_PLATFORM_CONFIG`, `ESL_DATABASE_URL`)만 읽는다. 그래서 작업 스케줄러 작업은 `.runtime\venv\Scripts\python.exe "<git>\.runtime\app\esl_service.py" backend|worker --runtime "<git>\.runtime"`로 등록되고, 실행기가 두 파일을 읽어 **자기 프로세스 환경에만** 넣는다(physicsai `--runtime`과 같은 규약 — 비밀값은 인자·로그에 없음).
- **코드 스냅샷**: 서비스는 git 폴더가 아니라 `.runtime\app`(esl·backend\esl_platform·worker\esl_worker·migrations·alembic.ini·esl_service.py 복사본)을 실행한다. `git pull`이 실행 중인 코드를 바꾸지 않는다.
- **런타임 폴더는 git에서 제외**: `.runtime\.gitignore`(`*` 한 줄)를 만든다(저장소 `.gitignore`는 바꾸지 않음).
- **Node**: ESL 저장소에는 빌드된 화면이 커밋되어 있지 않다 → 처음 설치와 프런트 소스가 바뀐 업데이트에서만 Node 22로 `npm ci`(package-lock.json이 바뀔 때만) → `npm run build`. 소스 해시가 같으면 Node·npm 단계 없음. 대시보드 고정 Node(`<대시보드>\.tools\node-v22.*-win-x64`)를 먼저 쓴다. Node가 없는 서버는 §2.2 묶음을 쓴다.
- `.bat` 실행이 보안 정책으로 막혀도 위처럼 `.ps1`을 `-File`로 직접 실행하면 된다.
- **묻는 것**(Enter = 괄호 안 기본값): 대시보드 폴더(`<git 부모>\simdashboard`), ESL 루트(`<git 부모>\esl-data` — SPDM 밖), 입력 루트(rad·결과 CSV 폴더를 고를 수 있는 폴더, 쉼표로 여러 개, Enter = 건너뜀), SPDM 루트(선택), 확인 표 뒤 `Y/N`, 비밀번호 2개(PostgreSQL `postgres` 관리자·앱 역할 `esl_app` — 이미 설치돼 있고 접속되면 묻지 않음). `Background` 모드면 실행 계정 비밀번호를 한 번 더 묻는다.
- 인자로 줄 수도 있다: `-DashboardRoot`, `-EslRoot`, `-InputRoots a,b`, `-SpdmRoots`, `-PythonExe`, `-ServiceUser`(기본 현재 사용자), `-RunMode Interactive|Background`(기본 `Interactive`), `-NonInteractive`(묻지 않음 — 비밀번호는 `-PasswordsFromEnv`), `-NoStart`, `-Force`.
- **Python**: `-PythonExe` → deploy.json → 대시보드 고정 Python 3.12 → `py -3.12` → PATH 순으로 **실제로 실행해** 3.12인지 확인(망가진 pyenv shim·Store 별칭은 건너뜀). 대시보드 Python에는 아무것도 설치하지 않는다(항상 `.runtime\venv`).
- **PostgreSQL**: 대시보드 `.env`의 `POSTGRES_BIN`과 `DATABASE_URL`의 **host·port만** 읽는다(사용자명·비밀번호는 읽지도 출력하지도 않음). 같은 인스턴스에 DB `esl`·역할 `esl_app`을 **없을 때만** 만든다. 서버가 18이 아니면 경고만.
- **솔버 의존성**: `deploy\requirements.lock`(고정 버전, physicsai lock과 겹치는 패키지는 같은 버전)에 pypardiso + MKL(mkl·intel-openmp·tbb 등 Windows 휠), pyamg, psutil이 들어 있다. scikit-sparse(CHOLMOD)는 Windows 휠이 없어 제외 → `solver.backend: auto`는 Windows에서 `pardiso`.

| 단계 | 내용 |
|---|---|
| ① | Python 3.12 선택(관리자 권한 확인 없음) |
| ② | 런타임 폴더 `<git>\.runtime\`: `venv`, `app`(코드 스냅샷), `frontend`(배치), `config\esl_platform.yaml`(+`esl.yaml`·`library.yaml`·`ista6.yaml`), `secrets\database_url`, `deploy.json`, `logs`, `state`, `_backup` |
| ③ | `.runtime\venv`에 `deploy\requirements.lock` 설치(사내 pip 설정 `pip.ini`·`PIP_INDEX_URL`·`HTTPS_PROXY` 그대로) |
| ④ | 설정 계획(`deploy\setup_config.py`): `deploy.json`·`esl_platform.yaml`을 **새로 만들거나, 있으면 보존하고 빠진 키만 보충**(사용자가 고친 값은 덮어쓰지 않음, 비어 있는 storage 경로만 채움). 새 설정 = `config\esl_platform.prod.example.yaml`(`profile: prod`, `server.port: 8110`) + `storage.esl_root`(폴더 생성)·`input_roots`·`spdm_roots` + `auth.dashboard_public_login_url`(대시보드 `.env` `WINDOWS_WEB_BASE_PATH`, 기본 `/home/`). 같은 폴더에 `esl.yaml`(코어 판정 기준)·`library.yaml`·`ista6.yaml`을 없을 때만 예시에서 복사. 경로 검사: 절대경로, 공백·`& | < > ^ % ! "` 없음, ESL 루트가 입력·SPDM 루트와 겹치지 않음 |
| ⑤ | 확인 표(위치·Python·PostgreSQL·ESL 루트·입력 루트·설정 처리·작업 실행) → `Y/N` |
| ⑥ | 이미 설치돼 있으면 대기열 확인(실행 중 작업이 있으면 중단, `-Force`) → 기존 작업 정의를 `_backup\<UTC>\tasks\*.xml`로 → 작업 중지 → 의존성 갱신 → 코드 스냅샷(이전 `app`은 `_backup`) → 설정 작성(바뀌는 기존 파일은 먼저 `_backup` 복사) → 프런트 배치(이전 것은 `_backup`) |
| ⑦ | DB 역할·DB(없을 때만) → `.runtime\secrets\database_url` → `alembic upgrade head`(실행기 `migrate` — 0001~0004) → 작업 스케줄러 `ESL-Backend`·`ESL-Worker`(§2.5) → 시작·health(`http://127.0.0.1:8110/esl/api/health`) → **환경 점검 표**(§10) |
| ⑧ | 접속 연결 안내(§2.6): Caddy 스니펫·환경변수, 대시보드 `.env` `SIMDASH_ESL_ENABLED=true`(대시보드 지원 필요), 접속 주소 |

- 설정은 `.runtime\config\esl_platform.yaml`에서 직접 고친다(§4). 다시 실행하거나 업데이트해도 덮어쓰지 않는다. 고친 뒤 `Stop-ScheduledTask`/`Start-ScheduledTask ESL-Worker`(백엔드도).

### 2.1 준비물

| 항목 | 내용 |
|---|---|
| OS | Windows Server(대시보드와 같은 PC), 일반 PowerShell(관리자 권한 불필요. `-RunMode Background` 등록만 관리자 권한이 필요할 수 있음) |
| 실행 환경 | **대시보드와 동일**: Python **3.12.13**, PostgreSQL **18**(같은 인스턴스), Node **22.23.2**(git 폴더 설치에서 프런트 빌드 때만) |
| PostgreSQL | `postgres` 관리자 비밀번호를 알고 있음(`pg_bin`에 `psql.exe`) |
| Caddy | 대시보드가 쓰는 Caddy(Caddyfile 수정 권한) — physicsai와 같은 Caddy에 스니펫 하나 추가 |
| 실행 계정 | ESL 루트 쓰기·입력 루트 읽기 권한. 기본은 현재 사용자 `Interactive` |
| ESL 루트 | Case 산출물 폴더(예 `E:/shared/ESL_WORK`). **SPDM master 밖**, 경로에 공백·`& | < > ^ % ! "` 금지 |
| 입력 루트 | 사용자가 HyperView TCL로 만든 rad·결과 CSV 폴더가 있는 공유(읽기 전용) |
| Altair | **불필요**(서버에서 외부 프로그램을 실행하지 않음 — 사용자 PC의 TCL 추출만 HyperView 사용) |

### 2.2 오프라인 묶음 만들기(폐쇄망 서버용 — 인터넷 되는 준비 PC)

```powershell
# Windows 준비 PC(저장소 폴더에서). 대시보드가 같은 PC에 있으면 -DashboardRoot 권장(대시보드 고정 Python 3.12·Node 22)
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\collect-offline.ps1 -DashboardRoot E:\VD_SIMULATION_WEB\simdashboard -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\collect-offline.ps1 -DashboardRoot E:\VD_SIMULATION_WEB\simdashboard
```

```bash
# Linux 준비 PC
bash deploy/collect-offline.sh --dry-run
bash deploy/collect-offline.sh                       # → dist/esl-offline-<version>.zip (dist/ 는 '*' .gitignore)
bash deploy/collect-offline.sh --frontend-dist frontend/dist   # 이미 빌드한 프런트를 그대로(npm 생략)
```

- 묶음 구성(최상위 5개): `wheels`(win_amd64·cp312 — `deploy/requirements.lock` 전부, pypardiso·MKL 포함 약 260 MB), `frontend`(빌드본), `app`(esl, backend\esl_platform, worker\esl_worker, migrations, alembic.ini, pyproject.toml, esl_service.py), `config`(예시 설정 5개), `deploy`.
- `pip download`는 고른 Python으로 만든 빌드용 임시 venv(`dist\_buildvenv`)에서 실행하고 끝나면 지운다(대시보드 런타임에 설치 없음).
- `--no-download`(sh)는 휠 대신 `wheels/DOWNLOAD-LIST.txt`만 둔다 — 구조 시험용이며 이 묶음으로는 설치할 수 없다.
- 확인: `requirements.lock`의 38개 패키지가 정확히 그 버전 휠로 내려받아져야 한다(시험 `tests/deploy/test_deploy_collect.py`, `ESL_TEST_NETWORK=1`).

### 2.3 설치 매개변수 `deploy.json`(폐쇄망 서버용 묶음)

zip을 풀고 `deploy\deploy.example.json`을 같은 폴더에 `deploy.json`으로 복사해 고친다. **경로 문자열은 이 파일에만** 둔다(비밀번호는 넣지 않는다).

| 키 | 의미 | 예시 |
|---|---|---|
| `install_root` | 설치 루트(= 런타임: venv·app·frontend·config·secrets·logs·state·`_backup`) | `D:\esl` |
| `dashboard_root` | (선택) 대시보드 폴더. 비어 있는 `pg_bin`·`pg_host`·`pg_port`·`python_exe`만 대시보드 `.env`·`.tools`로 채운다(명시 값 우선, 비밀번호는 읽지 않음) | `E:\simulation_workbench` |
| `python_exe` | Python 3.12 실행 파일 | `D:\Python312\python.exe` |
| `pg_bin` / `pg_host` / `pg_port` | PostgreSQL 18 bin(`psql.exe`)·주소(대시보드와 같은 인스턴스) | `E:\PostgreSQL\18\bin` / `127.0.0.1` / `5432` |
| `db_name` / `db_role` | 만들 DB·앱 역할 | `esl` / `esl_app` |
| `config_path` | 설정 파일(작업 인자 `--config` — `<install_root>\config\esl_platform.yaml`이면 생략됨) | `D:\esl\config\esl_platform.yaml` |
| `service_user` | 작업 실행 계정 | `CORP\svc_esl` |
| `run_mode` | `Interactive`(로그온 세션, 기본) / `Background`(로그온 무관, 세션 0 Service) | `Interactive` |
| `caddy_frontend_root` | 프런트 배치 위치(Caddy `root`, 환경변수 `ESL_FRONTEND_ROOT`) | `D:\esl\frontend` |
| `backend_serves_frontend` | `true`면 백엔드가 `/esl/`에서 프런트도 서빙(Caddy 없이 대시보드 Vite 프록시 구성, §2.6.2). 기본 `false` | `false` |
| `esl_root` | ESL 루트(설정이 없을 때 새 설정에 넣음, 폴더 생성) | `E:/shared/ESL_WORK` |
| `input_roots` / `spdm_roots` | 입력 루트 목록 / SPDM 루트 목록(겹침 검사) | `["E:/shared/ESL_INPUT"]` / `[]` |

### 2.4 설치 실행(폐쇄망 서버용 묶음)

```powershell
# 일반 PowerShell, 풀어 둔 묶음의 deploy 폴더에서
.\install.bat                       # 또는 .\install.ps1 [-ConfigFile .\deploy.json] [-ServiceUser CORP\svc] [-RunMode Interactive]
```

| 단계 | 내용 |
|---|---|
| ① | Python 3.12 확인(`python_exe`를 실제 실행 — 아니면 원인·다음 행동과 함께 중단) |
| ② | `<install_root>\venv` 생성, `pip install --no-index --find-links wheels -r deploy\requirements.lock` |
| ③ | 코드 배치 `<install_root>\app`(묶음의 app, 이전 것은 `_backup\<UTC>\app`) |
| ④ | 프런트 배치 `caddy_frontend_root`(이전 것은 `_backup`) |
| ⑤ | 설정(`setup_config.py`, 묶음 모드 — `deploy.json`은 바꾸지 않음): 없으면 운영 예시로 만들고 `esl_root`·`input_roots`·`spdm_roots`·로그인 링크를 넣음, 있으면 보존·빠진 키만 보충. 검증 결과 출력 |
| ⑥ | DB 역할·DB가 **없을 때만** 생성. 비밀번호 2개를 화면 입력(`Read-Host -AsSecureString`)으로 받아 `PGPASSWORD` 프로세스 환경으로만 전달. 역할 생성 SQL은 표준 입력으로, 그 세션의 문장 로그를 끈 뒤 실행 |
| ⑦ | DB 접속 정보 파일 `<install_root>\secrets\database_url`(값은 출력하지 않음, 현재 사용자·SYSTEM(+실행 계정 읽기)만) |
| ⑧ | `alembic upgrade head`(실행기 `migrate`) — head `0004` |
| ⑨ | 작업 스케줄러 `ESL-Backend`·`ESL-Worker`(§2.5) |
| ⑩ | 두 작업 시작 → health 60초까지 → 환경 점검 표(§10) |
| ⑪ | Caddy 스니펫·환경변수 안내(§2.6) |

- **재설치 시 앱 역할 비밀번호**: 역할이 이미 있으면 비밀번호를 바꾸지 않는다. 기존 런타임 파일로 접속되면 묻지 않고, 아니면 **기존 역할과 같은 비밀번호**를 입력한다.
- `install.bat`·`update.bat`·`start-demo.bat`·`stop-demo.bat`은 `PSModulePath`를 비우고 Windows PowerShell 5.1을 부른다(pwsh 7 창에서 실행해도 5.1 기본 모듈).

### 2.5 작업 스케줄러(서비스 대신)

| 설정 | 값 | 이유 |
|---|---|---|
| 작업 | `ESL-Backend`(`… esl_service.py backend --runtime <런타임>`), `ESL-Worker`(`… worker --runtime <런타임>`), 작업 폴더 = 런타임 | `worker.state_dir: ./state` → `<런타임>\state` |
| 트리거 | `Interactive`: 실행 계정 로그온 시(`AtLogOn`) / `Background`: 부팅 시(`AtStartup`, 비밀번호 저장 — Service 모드) | |
| 실행 시간 제한 | **0(무제한)** | 기본 72시간이면 장시간 솔버 작업 중 워커가 종료됨 |
| 실패 시 재시작 | 1분 간격, 999회 | |
| 여러 인스턴스 | `IgnoreNew` | |
| 권한 수준 | `Limited`(관리자 권한 없이 등록·중지·시작) | |
| 인자 | 실행기 경로·`--runtime`·(필요할 때만)`--config`·`--frontend` — 파일 경로만 | 비밀값 없음 |

- 수동 조작: `Start-ScheduledTask ESL-Worker`, `Stop-ScheduledTask ESL-Worker`(백엔드도). 워커를 멈추면 실행 중 작업은 약 1분(lease) 뒤 `INTERRUPTED`.
- ESL은 외부 GUI 프로그램을 실행하지 않으므로 `Background`(세션 0)에서도 기능 차이가 없다(physicsai와 달리 세션 0 제약 없음). 매핑 드라이브를 입력·ESL 루트로 쓰면 세션별 매핑 문제는 같다(§13).
- 해제: `deploy\uninstall-tasks.ps1`.

### 2.6 접속 연결

#### 2.6.1 Caddy(기본)

`deploy\caddy\esl.caddy`를 **대시보드 Caddyfile 사이트 블록 안, catch-all `handle` 앞**(physicsai 스니펫 옆)에 넣는다.

```caddyfile
redir /esl /esl/ 308

handle /esl/api/* {
	reverse_proxy 127.0.0.1:{$ESL_PORT:8110}
}

handle /esl/* {
	root * {$ESL_FRONTEND_ROOT}
	uri strip_prefix /esl
	try_files {path} /index.html
	file_server
}
```

- Caddy 실행 환경에 `ESL_PORT`(= `server.port`), `ESL_FRONTEND_ROOT`(= `caddy_frontend_root`, git 폴더 설치는 `<git>\.runtime\frontend`)를 두거나 값을 직접 적고 Caddy 설정을 다시 읽는다.
- 대시보드 `.env`에 `SIMDASH_ESL_ENABLED=true`(대시보드 메뉴 — 대시보드 쪽 지원 후).
- 확인: `http://<대시보드 주소>/esl/` → 대시보드 로그인 상태면 이름·프로젝트가 보인다. 이 PC에서 health: `http://127.0.0.1:8110/esl/api/health`.

#### 2.6.2 대시보드 Vite 프록시(대안 — Caddy 없는 대시보드)

physicsai 기본 구성처럼 대시보드 Vite가 `/esl` 전체를 백엔드로 넘기는 구성. ESL 백엔드는 실행기 `--frontend`로 `/esl/` 아래에서 프런트를 직접 서빙한다(`index.html` no-cache, `assets/` 1년 캐시, 없는 경로는 `index.html`, `/esl/api/…` 404는 JSON 그대로, `..`·드라이브·링크 밖 경로 거부).

1. `deploy.json`에 `"backend_serves_frontend": true` → `setup.ps1`(또는 `update-repo.ps1`)을 다시 실행(작업 인자에 `--frontend <caddy_frontend_root>` 추가).
2. 대시보드 `.env`: `VITE_ESL_TARGET=http://127.0.0.1:8110`, `SIMDASH_ESL_ENABLED=true` — **대시보드 쪽 프록시 지원이 필요**(README 요청 사항).

### 2.7 반입 자원(없음)과 솔버 의존성

서버에 따로 복사할 원본 자원이 없다(`deploy\RESOURCES.txt`). 입력(rad + 결과 CSV)은 사용자 PC에서 HyperView TCL로 만들고(루트 `update.bat` — 사용자 PC용), 서버는 `storage.input_roots` 아래에서 읽기만 한다. 솔버 가속(pypardiso·MKL, pyamg, psutil)은 `requirements.lock`에 포함되어 설치되며 환경 점검 `solver.*`로 확인한다.

### 2.8 DB 수동 생성(설치 스크립트 없이)

```sql
-- postgres 관리자로. 비밀번호가 서버 로그에 남지 않게 이 세션의 문장 로그를 끈다
SET log_statement = 'none'; SET log_min_error_statement = 'panic'; SET log_min_duration_statement = -1;
CREATE ROLE "esl_app" LOGIN PASSWORD '<비밀번호>';
CREATE DATABASE "esl" OWNER "esl_app" ENCODING 'UTF8';
```

```powershell
# 런타임 DB 파일(현재 사용자만 읽기 — setup.ps1 이 하는 것과 같음)을 만든 뒤 실행기로 migration
D:\esl\venv\Scripts\python.exe D:\esl\app\esl_service.py migrate --runtime D:\esl
```

- downgrade는 지원하지 않는다. 되돌리려면 DB 백업에서 복원한다(§3.3).

### 2.9 개발 실행(참고)

`scripts/test-all`(Linux, PostgreSQL 임시 클러스터) — 코어·플랫폼·워커·배포(`tests/deploy`)·프런트. 백엔드 직접 실행: `ESL_PLATFORM_CONFIG=config/esl_platform.yaml ESL_DATABASE_URL=… python deploy/esl_service.py backend`(런타임 없이 환경변수 사용).

---

## 3. 업데이트·제거·백업

### 3.0 업데이트(git 폴더 설치 — §2.0)

**일반 Windows PowerShell**에서 **한 줄**(인자·질문 없음 — 값은 `.runtime\deploy.json`, `git pull`도 스스로):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\VD_SIMULATION_WEB\esl-platform\deploy\update-repo.ps1
```

끝 줄은 `업데이트 성공 — 접속: …` 또는 `업데이트 실패 — 접속: …`(`http://<서버>:<대시보드 .env WINDOWS_WEB_PORT, 기본 80>/esl/`).

| 단계 | 내용 |
|---|---|
| ⓪ | `git pull --ff-only`(자격 증명을 묻지 않음 — 인증 필요 시 바로 실패). 추적 파일에 로컬 변경이 있으면 안내 후 중단(바꾼 것 없음). 분리된 HEAD·추적 브랜치 없음이면 pull 없이 현재 커밋. 새 커밋을 받으면 받은 새 `update-repo.ps1`로 이어서 실행 |
| ① | 대기·실행 중 작업 확인(`jobs.state` QUEUED·RUNNING, DB 직접 조회). 있으면 안내 후 중단(`-Force`면 진행) |
| ② | 작업 2개 중지 |
| ③ | venv 의존성 갱신(`requirements.lock`). venv가 3.12로 실행되지 않으면 `_backup`으로 옮기고 새로 |
| ④ | 코드 스냅샷 `.runtime\app`(이전 것은 `_backup\<UTC>\app`) |
| ⑤ | 설정 보충(기존 값 유지, 새로 생긴 관리 키만 — 예: P2 이전 설정에 `library` 블록) |
| ⑥ | 프런트: 소스가 바뀌었을 때만 Node 22로 빌드 → `.runtime\frontend` |
| ⑥' | 작업 정의가 지금 설치와 다르면 다시 등록(Interactive만, Background는 안내) |
| ⑦ | `alembic upgrade head` |
| ⑧ | 시작·health·환경 점검 → 성공 + 접속 주소 |

- ⑦ 전에 실패하면 이전 `app`·프런트를 되돌리고 작업 2개를 다시 시작한다(이전 버전으로 계속 사용). ⑦ 이후 실패면 되돌리는 방법을 출력한다(`git checkout <이전 커밋>` 후 다시 실행, DB는 백업 복원).
- `.runtime\_backup`은 자동으로 지우지 않는다. 업데이트 전 DB 백업(§3.3)을 먼저 한다.

### 3.1 업데이트(폐쇄망 서버용 묶음)

```powershell
# 일반 PowerShell, 새 묶음의 deploy 폴더(기존 deploy.json을 복사해 둔다)
.\update.bat              # 또는 .\update.ps1 [-Force]   ← 저장소 루트 update.bat(사용자 PC TCL)과 다른 파일
```

| 단계 | 내용 |
|---|---|
| ① | Python 확인(아니면 아무것도 바꾸지 않고 중단) → 대기·실행 중 작업 확인(있으면 중단, `-Force`) |
| ② | 작업 2개 중지 |
| ③ | 기존 `venv`·`app`·프런트를 `<install_root>\_backup\<UTC>\`로 **이동**(삭제 없음) |
| ④ | 새 venv·wheel·app·프런트 배치, 작업 정의 갱신(Interactive만) |
| ⑤ | 설정 보충(기존 값 유지) |
| ⑥ | `alembic upgrade head` |
| ⑦ | 시작·health·환경 점검 |
| ⑧ | 실패하면 되돌리는 방법 출력(자동 되돌림 없음) |

### 3.2 제거

```powershell
.\uninstall-tasks.ps1     # 작업 스케줄러 등록 해제만(파일·DB·런타임 파일은 그대로)
```

완전 제거(백업 후): ① Caddyfile에서 ESL 스니펫 삭제 → Caddy 다시 읽기, 대시보드 `.env`의 `SIMDASH_ESL_ENABLED` 삭제 ② 런타임 폴더의 `secrets\database_url` 삭제 ③ DB `esl`·역할 `esl_app` 삭제(`pg_dump` 후) ④ 런타임 폴더 정리 ⑤ **ESL 루트의 Case·라이브러리·분석 폴더는 사용자 산출물** — 플랫폼은 지우지 않는다.

### 3.3 백업·복원

| 대상 | 방법 | 주기(권장) |
|---|---|---|
| DB `esl` | `pg_dump -Fc`(아래) | 매일 + 업데이트 직전 |
| ESL 루트(`storage.esl_root`) | 사내 파일 백업(Case 폴더, `_library`, `_analysis`) | 사내 정책 |
| 설정 | `<런타임>\config\*.yaml`, `deploy.json` 사본 | 변경 시 |

```powershell
$pg = 'E:\PostgreSQL\18\bin'
$s = Read-Host -AsSecureString 'esl_app 비밀번호'
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
& "$pg\pg_dump.exe" -h 127.0.0.1 -U esl_app -Fc -f "D:\backup\esl_$(Get-Date -Format yyyyMMdd).dump" esl
$env:PGPASSWORD = $null
# 복원(작업 2개 중지 후): pg_restore -h 127.0.0.1 -U esl_app -d esl --clean --if-exists <파일>
```

- 복원할 때는 **DB와 ESL 루트를 같은 시점**으로 맞춘다. 비밀번호는 명령 인자에 넣지 않는다.

---

## 4. 설정 파일 레퍼런스

### 4.1 위치·우선순위·검증

- 운영: `<런타임>\config\esl_platform.yaml`(작업 인자 `--runtime`; 다른 위치면 `--config`). 예시: `config/esl_platform.prod.example.yaml`(운영, `profile: prod`), `config/esl_platform.example.yaml`(개발).
- 함께 두는 파일(상대경로는 설정 파일 기준): 코어 `esl.yaml`(`core.config_path`), 라이브러리 `library.yaml`(`library.config_path`) → `ista6.yaml`(`library.ista6`).
- 환경변수 `ESL_PROFILE`이 `profile`보다 우선. **모든 키 필수, 알 수 없는 키는 `CONFIG_INVALID`** — 백엔드는 조회만(쓰기 API 503), 워커는 기동 거부(종료코드 2, 작업 스케줄러가 1분마다 재시작).
- 검증: 환경 점검 `config.valid`(§10) 또는 `GET /esl/api/status`의 `config.errors`.

### 4.2 반영 시점

설정은 시작할 때 읽는다. 고친 뒤 `Stop-ScheduledTask`/`Start-ScheduledTask ESL-Worker`, `ESL-Backend`. Case 작업은 생성 시점의 코어 설정을 스냅샷한다(이미 만든 작업은 바뀌지 않음).

### 4.3 키 표(운영에서 고치는 것)

| 키 | 설명 | 운영 기본 |
|---|---|---|
| `profile` | `prod`(dev_static 인증 금지) | `prod` |
| `server.host` / `port` / `base_path` | 루프백 바인딩 / 포트(Caddy `ESL_PORT`) / `/esl`(바꾸지 않음) | `127.0.0.1` / `8110` / `/esl` |
| `database.url_env` | DB URL 환경변수 **이름**(실행기가 런타임 파일 값을 이 이름으로 넣음) | `ESL_DATABASE_URL` |
| `auth.dashboard_internal_url` | 대시보드 백엔드 내부 주소 | `http://127.0.0.1:8000` |
| `auth.dashboard_public_login_url` | 로그인·"대시보드로" 링크(같은 origin 경로) — 설치가 `WINDOWS_WEB_BASE_PATH`로 맞춤 | `/home/` |
| `storage.esl_root` | Case 산출물 루트(쓰기, SPDM 밖) | 설치 시 입력 |
| `storage.input_roots` | rad·결과 폴더 선택 허용 루트(읽기 전용). 비면 Case 생성 불가 | 설치 시 입력 |
| `storage.spdm_roots` | 겹침 검사용 SPDM 루트 | `[]` |
| `worker.heartbeat_interval_s` / `lease_ttl_s` | 하트비트 / 리스(취소·중단 감지) | `10` / `60` |
| `worker.max_logical_cores` / `max_memory_gb` / `priority` / `limiter` | 자원 제한(Windows: Job Object — 메모리·CPU 비율·우선순위·워커 종료 시 자식 종료 / POSIX: nice·RLIMIT_AS·affinity). `limiter`: auto|windows_job|posix|none | `16` / `32` / `below_normal` / `auto` |
| `ui.max_preview_points` | ⑤ 겹쳐보기·2D 산점 최대 점 수 | `20000` |
| `core.config_path` | 코어 설정(`esl.yaml` — t*·솔버·판정 기준 `validation`·`compare`) | `esl.yaml` |
| `report.auto` | VALIDATE 성공 시 Case 보고서 자동 | `true` |
| `library.config_path` | 라이브러리·분석·덱 설정(없으면 라이브러리 쓰기 API 503) | `library.yaml` |

- 코어 `esl.yaml`의 `solver.backend: auto` → Windows에서 `pardiso`(pypardiso·MKL). `extract.disp_precision`은 TCL 출력 정밀도(H3D 보통 `float32`).
- 판정 기준(`validation.*`, `compare.*`)과 ISTA 6 낙하 높이 표는 **임시값·TODO** — 사내 확인 후 교체(§15).

---

## 10. 환경 점검

관리 화면의 환경 점검이 아직 없으므로 두 가지로 확인한다. 설치·업데이트 스크립트는 시작 뒤 자동으로 표를 출력한다.

```powershell
# 서버에서(작업과 같은 --runtime — 런타임 DB 파일·설정을 읽음)
D:\esl\venv\Scripts\python.exe D:\esl\app\esl_service.py check --runtime D:\esl            # 표
D:\esl\venv\Scripts\python.exe D:\esl\app\esl_service.py check --runtime D:\esl --json     # JSON
# (개발 저장소) python -m esl_platform.check --config config/esl_platform.yaml   — DB URL 은 환경변수
```

| 항목(key) | 판정 |
|---|---|
| `python` | 3.12 → OK, 아니면 WARN(기준: 대시보드와 같은 3.12.13) |
| `config.valid` | 스키마·의미(루트 겹침·경로 문자)·코어·라이브러리 설정 검증. 오류 → FAIL(키: 메시지) |
| `config.auth` / `config.library` | dev_static이면 WARN(prod면 FAIL) / library 블록 없음 → WARN |
| `storage.esl_root.write` / `.free` | 임시 파일 쓰기·삭제 / 여유 공간 < `--min-free-gb`(기본 20) → WARN |
| `storage.input_roots` / `storage.spdm_roots` | 각 폴더 존재·목록 읽기(입력 루트 없음 → FAIL, 비어 있음 → WARN) |
| `worker.state_dir` | 쓰기 가능(없으면 WARN — 워커가 만듦) |
| `solver.backend` | 설정 값 → 해석 값(코어와 같은 규칙), 사용 가능 목록. 설정한 백엔드가 미설치면 FAIL |
| `solver.pypardiso` | pypardiso 버전·MKL(mkl_rt) 로드. **Windows에서 없거나 MKL 로드 실패면 FAIL**(묶음에 포함되어야 함) |
| `solver.cholmod` | Windows: SKIP(scikit-sparse 휠 없음 — 제외) |
| `solver.pyamg` / `solver.psutil` | 반복법 전처리 / 메모리 추정 — 없으면 WARN |
| `db.connection` / `db.server_version` | 접속(대상 host:port/db만 표시, 비밀번호 비노출) / 18 아니면 WARN |
| `db.migration_head` | `alembic_version` = head(`0004`) — 아니면 FAIL(`esl_service.py migrate`) |
| `worker.heartbeat` | 최근 하트비트 ≤ 3×주기 → OK, 아니면 WARN(워커 오프라인) |

- 종료코드 0 = FAIL 없음, 1 = FAIL 있음. 화면에서는 `GET /esl/api/status`(설정 오류·워커 온라인·솔버 백엔드)로도 본다.

## 12. 로그 위치

| 로그 | 위치 |
|---|---|
| 백엔드·워커 | `<런타임>\logs\backend.log`·`worker.log`(실행기 — 10 MB × 5 회전, 표준 출력·오류 포함, 비밀값 없음) |
| 작업 step | `<esl_root>\<case>\logs\<job_id>\step_NN_<key>.log`(화면 "로그") |
| 설치·업데이트 | 콘솔 출력(필요하면 `Start-Transcript`) |
| 시연 | `<DemoRoot>\logs\`(`backend.log`·`worker.log`·`*.out.log`·`demo-setup.log`) |

## 13. 문제 해결(FAQ)

**먼저 `<런타임>\logs\worker.log`·`backend.log`를 본다.** 그래도 모르면 콘솔에서 직접 띄워 본다(작업과 같은 인자):

```powershell
Stop-ScheduledTask ESL-Worker
cd D:\esl                                   # git 폴더 설치는 <git>\.runtime
.\venv\Scripts\python.exe .\app\esl_service.py worker --runtime . --console   # 기동 거부·오류 메시지를 콘솔에서 확인
# 확인 후 Ctrl+C, Start-ScheduledTask ESL-Worker
```

**Q. 워커가 1분마다 재시작한다 / 작업이 대기에서 안 넘어간다.** 설정 오류(`CONFIG_INVALID`, 종료코드 2) 또는 DB 접속 정보 없음. 환경 점검 `config.valid`·`db.*`를 보고 설정 파일을 고친다. `db.migration_head` FAIL이면 `esl_service.py migrate --runtime <런타임>`.

**Q. 경로를 넣으면 `PATH_OUTSIDE_ROOT`.** rad·결과 폴더(와 rad의 include)는 `storage.input_roots` 아래여야 한다. 공유를 추가했으면 설정 `storage.input_roots`에 넣고 백엔드 재시작.

**Q. 매핑 드라이브(E: → `\\서버\share`)를 입력·ESL 루트로 쓰는데 워커만 못 읽는다.** 매핑 드라이브는 로그온 세션별이다. `Background`(세션 0)에서는 사용자가 매핑한 드라이브가 보이지 않는다 → UNC 경로를 쓰거나 `Interactive`로 등록.

**Q. ESL 계산이 매우 느리거나 메모리 부족.** 환경 점검 `solver.backend`가 `superlu`면 pypardiso/MKL이 로드되지 않은 것이다(`solver.pypardiso` 메시지). 묶음 설치면 wheels에 mkl·intel-openmp·tbb가 있는지 확인. 코어 `validation.full_solve`(auto|never)도 본다.

**Q. 화면이 "대시보드에서 로그인하세요"만 보인다 / 503.** 같은 주소(origin)로 접속했는지, `auth.dashboard_internal_url`로 대시보드 백엔드에 닿는지.

**Q. 회사 프록시(`HTTP_PROXY`)에서 health 확인이 실패한다.** 설치 스크립트·시연의 127.0.0.1 호출은 프록시를 쓰지 않는다(`loopback-http.ps1`, physicsai와 같은 처리). pip·npm은 기존 프록시 설정을 그대로 쓴다.

**Q. `.bat` 실행이 "액세스가 거부되었습니다".** `powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install.ps1`(또는 `setup.ps1`, `demo\start-demo.ps1`)처럼 `.ps1`을 직접 실행한다(인자 동일).

**Q. 작업 스케줄러 작업을 바꿀 권한이 없다고 나온다.** 다른 계정이나 관리자 권한으로 등록된 작업이다. 처음 등록한 것과 **같은 사용자 계정**으로 '관리자 권한으로 실행'한 창에서 한 번 실행하면 그 뒤로는 일반 PowerShell로 된다.

---

## 14. 시연 모드

Altair·HyperView·대시보드 없이 **합성 낙하 Case**로 ①~⑥·보고서를 바로 보는 모드다(운영 설치와 포트·폴더·DB 분리). 관리자 권한 불필요.

### 14.1 시작

```powershell
deploy\demo\start-demo.bat                                                   # 또는 start-demo.ps1
deploy\demo\start-demo.ps1 -DemoRoot D:\esl-demo -DashboardRoot E:\simulation_workbench   # PgBin·Python·Node를 대시보드 환경에서
```

| 인자 | 기본 | 뜻 |
|---|---|---|
| `-DemoRoot` | `<시스템 드라이브>\esl-demo` | 시연 폴더(공백·특수문자 금지) |
| `-Port` | `8191` | 백엔드 포트(127.0.0.1 전용 — 운영 8110·physicsai 8100·physicsai 시연 8190과 겹치지 않게) |
| `-PythonExe` | 자동 선택(§2.0과 같은 규칙) | Python 3.12. 시연 venv `<DemoRoot>\venv`를 처음 만들 때만 |
| `-PgBin` | `-DashboardRoot` `.env` `POSTGRES_BIN` → PATH → `PGBIN` | `initdb.exe`·`pg_ctl.exe`·`psql.exe` 폴더 |
| `-DashboardRoot` | – | (선택) 대시보드 폴더(`.env`의 POSTGRES_BIN, `.tools` Python 3.12·Node 22) |
| `-PgPort` | `55433` | 시연 전용 PostgreSQL 포트(physicsai 시연 55432와 겹치지 않게) |
| `-UseExistingDb` | – | 시연 클러스터 대신 기존 PostgreSQL의 빈 DB(URL은 환경변수 `ESL_DEMO_DATABASE_URL`로만) |
| `-NoPrerun` | – | ①~⑥ 완료 Case를 미리 돌리지 않음 |
| `-NoBrowser` | – | 브라우저를 열지 않음 |

하는 일: ① `<DemoRoot>\venv`에 `requirements.lock` 설치(묶음은 wheels, 저장소는 인덱스 — lock이 같으면 건너뜀). 저장소에 `frontend\dist`가 없으면 Node 22로 빌드 ② 시연 설정(`profile: dev`, `auth: dev_static`, 127.0.0.1)·합성 입력 `<DemoRoot>\inputs\demo_drop\model_0000.rad` + `csv\`(TCL 출력과 같은 형식, t* = frame 6) ③ 시연 전용 PostgreSQL(`<DemoRoot>\pgdata`, trust, 127.0.0.1) ④ migration → 백엔드(프런트 직접 서빙 — Caddy 불필요) → 워커 → Case 2개 ⑤ 브라우저 `http://127.0.0.1:8191/esl/`.

### 14.2 사용

- 시연 관리자(dev_static, 전역 관리자)로 자동 로그인. 프로젝트 `demo`.
- **"시연 Case — ①~⑥ 완료"**(`demo_done`): 추출 → t* → 지지점(자동) → ESL → 검증(PASS) → 내보내기가 끝나 있고 Case 보고서(`07_report\report.html`)가 자동 생성된다 — ②의 t* 곡선, ④ F_eq, ⑤ 겹쳐보기·단면선·히스토그램, ⑥ 파일 목록을 바로 본다. 라이브러리 등록(⑤ 결과 카드)도 해 볼 수 있다.
- **"시연 Case — 입력만"**(`demo_new`): ①부터 직접 — rad·결과 폴더 경로는 시작 화면 안내(`<DemoRoot>\inputs\demo_drop\…`).
- 로그: `<DemoRoot>\logs\`. Case 산출물: `<DemoRoot>\esl_root\<Case 폴더>`.

### 14.3 종료

```powershell
deploy\demo\stop-demo.bat            # 백엔드·워커·시연 DB 중지(파일·DB는 그대로)
deploy\demo\stop-demo.bat -KeepDb    # 시연 PostgreSQL은 계속
```

### 14.4 오프라인 묶음과 안전장치

- 묶음에 `deploy\demo`가 들어 있다(합성 Case는 스스로 생성 — 추가 자원 없음). 폐쇄망 PC에서도 묶음의 `deploy\demo\start-demo.bat`으로 시연한다.
- `auth.mode: dev_static`은 `profile: dev`이고 127.0.0.1 바인딩일 때만 허용된다(위반 시 기동 거부). 운영 설정에 넣지 않는다.

### 14.5 무인 설치(참고 — CI·자동화용)

```powershell
$env:ESL_INSTALL_PG_ADMIN_PASSWORD = '…'; $env:ESL_INSTALL_DB_PASSWORD = '…'
$env:ESL_INSTALL_SERVICE_PASSWORD = '…'      # Background 모드일 때
.\setup.ps1 -NonInteractive -PasswordsFromEnv -NoStart     # 묶음은 .\install.ps1 -PasswordsFromEnv -NoStart
```

비밀번호는 프로세스 환경변수로만 받는다(명령 인자·로그·설정 파일에 남지 않음). 끝나면 그 창을 닫는다.

## 15. 미확정 항목·Windows 실기 미검증

| 항목 | 상태 | 확인 위치 |
|---|---|---|
| `setup.ps1`·`update-repo.ps1`·`install.ps1`·`update.ps1`·`collect-offline.ps1`·시연 `.ps1` 실제 Windows 실행 | **미검증**(Linux pwsh 7.4 파싱·PS 5.1 금지 문법 정적 검사·순수 함수 시험만) | E2E E0-1~E0-8 |
| 작업 스케줄러 등록·Interactive/Background·재부팅 자동 기동·icacls ACL | 미검증 | E0-3·E0-4 |
| pypardiso + MKL Windows 휠 실제 로드(`mkl_rt.2.dll`) | 미검증(Linux에서 같은 lock 버전 + pardiso로 플랫폼 시험 159건 통과) | 환경 점검 `solver.pypardiso` |
| Caddy 스니펫·대시보드 `SIMDASH_ESL_ENABLED`(대시보드 쪽 지원) | 대시보드 변경 필요(이 저장소 밖) | E0-5 |
| 워커 자원 제한: `worker.limiter`·`max_logical_cores`·`max_memory_gb`·`priority` | 적용됨(Windows Job Object). 할당 실패 시 작업 step이 `LIMITER_FAILED`로 실패 — `python -m esl_platform.check`의 `worker.limiter` 행 확인 | §4.3 |
| 판정 기준(`validation`·`compare`)·ISTA 6 낙하 높이 | 임시값·TODO | 코어 `esl.yaml`, `ista6.yaml` |
