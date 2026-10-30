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
| 프런트엔드 | 정적 파일(Vite build, base `/esl/`) | 화면 ①~⑥·라이브러리·분석. ESL 백엔드가 `/esl/` 아래에 서빙(`server.frontend_root`, §2.6.1 — Caddy를 쓰는 설치는 Caddy가 서빙, §2.6.2) | git 폴더 설치 `<git>\.runtime\frontend`, 묶음 `<install_root>\frontend`(= `deploy.json` `caddy_frontend_root`) |
| 백엔드(API) | 실행기 `esl_service.py backend`(uvicorn, `esl_platform.api.main`) | 입력 검증·권한·작업 생성·조회·보고서. **외부 프로그램을 실행하지 않는다** | `127.0.0.1:8110`, 접두 `/esl/api` |
| 워커 | 실행기 `esl_service.py worker`(`esl_worker`) | 대기열 claim, 코어(`esl.pipeline.run`)를 자식 프로세스(spawn)로 실행, 취소, 보고서·라이브러리 분석 | PC당 1개 |
| DB | PostgreSQL 18(대시보드와 **같은 인스턴스, 별도** DB `esl`·역할 `esl_app`) | Case·작업·결과 요약. 대용량 배열은 파일 | 대시보드 `.env` `DATABASE_URL`의 host·port |
| 산출물 | 파일 시스템 | Case 폴더(`<esl_root>\<case>\01_extract`~`07_report`), 라이브러리 `_library`, 분석 `_analysis` | `storage.esl_root` |

```text
브라우저 ── http://<대시보드 주소>/esl/…   (같은 origin → 대시보드 세션 쿠키 analysis_canvas_session 이 함께 전송)
   │
대시보드 Vite(start.ps1) ─┬─ /esl/*        → ESL 백엔드 127.0.0.1:8110 (경로 그대로, .env VITE_ESL_TARGET)
                          │                    ├─ /esl/api/* → API
                          │                    └─ 그 밖      → 프런트 정적 파일(server.frontend_root, 없는 경로는 index.html)
                          ├─ /physicsai/*  → PhysicsAI(VITE_PHYSICSAI_TARGET)
                          └─ 그 밖          → 대시보드(기존)
   (대안: 대시보드 앞 Caddy — /esl/api/* → 백엔드, /esl/* → 정적 파일, deploy\caddy\esl.caddy, §2.6.2)
ESL 백엔드 ── GET /api/auth/me, /api/projects ──▶ 대시보드 백엔드(루프백 127.0.0.1:8000)
     │
PostgreSQL `esl` ◀── claim/renew/release ── esl_worker ── spawn ── esl.pipeline(extract·tstar·esl·validate·export·report) / esl.library
```

### 1.2 대시보드와의 관계

- **같은 Windows Server PC**에서 대시보드(simulation_workbench)·physicsai-platform과 나란히 돈다. 실행 환경도 같다: Python **3.12.13**(대시보드 `.tools\python\cpython-3.12.13-*`), PostgreSQL **18**(같은 인스턴스), Node **22.23.2**(프런트 빌드 때만).
- 로그인 공유: 사용자는 대시보드에서 로그인한다. ESL 백엔드는 쿠키 토큰으로 대시보드 `GET /api/auth/me`를 호출해 사용자·역할을 확인한다(30초 캐시, `auth.*`). 권한은 대시보드 역할 그대로(조회 = ACTIVE 사용자, 실행 = 프로젝트 `power`·`admin`, 전역 관리 = `is_global_admin`).
- 대시보드 코드는 바꾸지 않는다. 대시보드 `.env`에 두 줄(`VITE_ESL_TARGET`, `SIMDASH_ESL_ENABLED`)만 넣는다(§2.6.1 — git 폴더 설치는 `setup.ps1`이 없을 때만 넣는다). 대시보드는 `VITE_ESL_TARGET`이면 `/esl` 경로를 그대로 이 백엔드로 프록시하고, `SIMDASH_ESL_ENABLED=true`이면 사이드바에 ESL 버튼을 보인다(physicsai `VITE_PHYSICSAI_TARGET`·`SIMDASH_PHYSICSAI_ENABLED`와 같은 방식 — 대시보드 쪽 지원 버전 필요). Caddy를 쓰는 설치는 대신 Caddyfile에 ESL용 스니펫을 추가한다(§2.6.2).

### 1.3 경로 `/esl/`

- 백엔드 라우트 접두 `{server.base_path}/api`(기본 `/esl/api`)와 프런트 빌드 base `/esl/`(frontend/vite.config.ts)는 같아야 한다. `server.base_path`를 바꾸지 않는다.
- 대시보드 Vite 프록시는 `/esl` 전체를 접두 그대로 백엔드로 넘기고, 백엔드가 `/esl/api/*`는 API로, 그 밖은 `server.frontend_root`의 정적 파일(없는 경로는 `index.html`)로 응답한다(§2.6.1). Caddy를 쓰면 `/esl/api/*`만 백엔드로 넘기고 프런트는 Caddy가 `uri strip_prefix /esl` 후 정적 파일을 준다(§2.6.2).

---

## 2. 설치

> 처음 설치는 단계별 요약 [install-quickstart.md](install-quickstart.md)를 먼저 본다. 이 절은 상세·예외다.

설치 방식은 둘이다(physicsai와 같음). **대시보드와 같은 PC에 인터넷(사내 프록시 포함)이 되면 §2.0 git 폴더 설치**(권장). §2.2~§2.4 오프라인 묶음은 인터넷이 안 되는 **폐쇄망 서버용**이다. §2.1·§2.5~§2.8은 공통.

### 2.0 같은 PC·git 폴더 설치(권장)

저장소를 받은 git 폴더에 그대로 설치한다. **일반 Windows PowerShell**(관리자 권한 불필요)에서:

```powershell
E:\VD_SIMULATION_WEB\esl-platform\deploy\setup.ps1        # 설치(다시 실행해도 안전)
E:\VD_SIMULATION_WEB\esl-platform\deploy\update-repo.ps1  # 업데이트(§3.0, git pull 포함)
# 실행 정책 오류(스크립트를 실행할 수 없습니다)가 나면 powershell -NoProfile -ExecutionPolicy Bypass -File …로 실행
```

- **관리자 권한이 필요 없다**: 머신 환경변수를 쓰지 않는다. DB 접속 정보(앱 비밀번호 포함 URL)는 `.runtime\secrets\database_url` 한 파일에 두고 상속을 끊어 **현재 사용자·SYSTEM만** 읽게 한다(`icacls` — 실패하면 경고만). 설정은 `.runtime\config\esl_platform.yaml`.
- **실행기**: 플랫폼 코드는 환경변수(`ESL_PLATFORM_CONFIG`, `ESL_DATABASE_URL`)만 읽는다. 그래서 작업 스케줄러 작업은 `.runtime\venv\Scripts\python.exe "<git>\.runtime\app\esl_service.py" backend|worker --runtime "<git>\.runtime"`로 등록되고, 실행기가 두 파일을 읽어 **자기 프로세스 환경에만** 넣는다(physicsai `--runtime`과 같은 규약 — 비밀값은 인자·로그에 없음).
- **코드 스냅샷**: 서비스는 git 폴더가 아니라 `.runtime\app`(esl·backend\esl_platform·worker\esl_worker·migrations·alembic.ini·esl_service.py 복사본)을 실행한다. `git pull`이 실행 중인 코드를 바꾸지 않는다.
- **런타임 폴더는 git에서 제외**: `.runtime\.gitignore`(`*` 한 줄)를 만든다(저장소 `.gitignore`는 바꾸지 않음).
- **Node**: ESL 저장소에는 빌드된 화면이 커밋되어 있지 않다 → 처음 설치와 프런트 소스가 바뀐 업데이트에서만 Node 22로 `npm ci`(package-lock.json이 바뀔 때만) → `npm run build`. 소스 해시가 같으면 Node·npm 단계 없음. 대시보드 고정 Node(`<대시보드>\.tools\node-v22.*-win-x64`)를 먼저 쓴다. Node가 없는 서버는 §2.2 묶음을 쓴다.
- `.bat` 실행이 보안 정책으로 막혀도 위처럼 `.ps1`을 직접 실행하면 된다(실행 정책 오류면 `powershell -NoProfile -ExecutionPolicy Bypass -File …`).
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
| ④ | 설정 계획(`deploy\setup_config.py`): `deploy.json`·`esl_platform.yaml`을 **새로 만들거나, 있으면 보존하고 빠진 키만 보충**(사용자가 고친 값은 덮어쓰지 않음, 비어 있는 storage 경로만 채움). 새 설정 = `config\esl_platform.prod.example.yaml`(`profile: prod`, `server.port: 8110`) + `server.frontend_root`(= `.runtime\frontend` — 백엔드가 `/esl/` 직접 서빙. 키가 없을 때만 보충, 사용자가 바꾼 값·`null`은 유지) + `storage.esl_root`(폴더 생성)·`input_roots`·`spdm_roots` + `auth.dashboard_public_login_url`(대시보드 `.env` `WINDOWS_WEB_BASE_PATH`, 기본 `/home/`). 같은 폴더에 `esl.yaml`(코어 판정 기준)·`library.yaml`·`ista6.yaml`을 없을 때만 예시에서 복사. 경로 검사: 절대경로, 공백·`& | < > ^ % ! "` 없음, ESL 루트가 입력·SPDM 루트와 겹치지 않음. 대시보드 `.env` 연결 키 계획(§2.6.1 — 추가/이미 있음/유지) |
| ⑤ | 확인 표(위치·Python·PostgreSQL·ESL 루트·입력 루트·설정 처리·작업 실행·프런트 배치·대시보드 `.env`) → `Y/N` |
| ⑥ | 이미 설치돼 있으면 대기열 확인(실행 중 작업이 있으면 중단, `-Force`) → 기존 작업 정의를 `_backup\<UTC>\tasks\*.xml`로 → 작업 중지 → 의존성 갱신 → 코드 스냅샷(이전 `app`은 `_backup`) → 설정 작성(바뀌는 기존 파일은 먼저 `_backup` 복사 — 대시보드 `.env`는 `_backup\<UTC>\dashboard.env`) → 프런트 배치(이전 것은 `_backup`) |
| ⑦ | DB 역할·DB(없을 때만) → `.runtime\secrets\database_url` → `alembic upgrade head`(실행기 `migrate` — 0001~0004) → 작업 스케줄러 `ESL-Backend`·`ESL-Worker`(§2.5) → 시작·health(`http://127.0.0.1:8110/esl/api/health`) → **환경 점검 표**(§10) |
| ⑧ | 접속 연결 안내(§2.6.1): 대시보드 `.env`에 `VITE_ESL_TARGET=http://127.0.0.1:<server.port>`·`SIMDASH_ESL_ENABLED=true`(④에서 없을 때만 추가 → "추가함 … 대시보드를 다시 시작하세요", 이미 있으면 "이미 들어 있음"), 접속 주소 `http://<대시보드 주소>/esl/`. Caddy를 쓰는 설치는 `deploy\caddy\esl.caddy`(§2.6.2) |

- 설정은 `.runtime\config\esl_platform.yaml`에서 직접 고친다(§4). 다시 실행하거나 업데이트해도 덮어쓰지 않는다. 고친 뒤 `Stop-ScheduledTask`/`Start-ScheduledTask ESL-Worker`(백엔드도).
- Caddy가 없는 대시보드 구성(대시보드 `start.ps1`의 Vite 서버만 쓰는 경우)이 기본이다: 대시보드 Vite가 `/esl`을 백엔드로 넘기고 백엔드가 프런트를 서빙한다(§2.6.1). 같은 주소라 대시보드 로그인이 공유된다.

### 2.1 준비물

| 항목 | 내용 |
|---|---|
| OS | Windows Server(대시보드와 같은 PC), 일반 PowerShell(관리자 권한 불필요. `-RunMode Background` 등록만 관리자 권한이 필요할 수 있음) |
| 실행 환경 | **대시보드와 동일**: Python **3.12.13**, PostgreSQL **18**(같은 인스턴스), Node **22.23.2**(git 폴더 설치에서 프런트 빌드 때만) |
| PostgreSQL | `postgres` 관리자 비밀번호를 알고 있음(`pg_bin`에 `psql.exe`) |
| 대시보드 `.env` | 대시보드 폴더 `.env` 쓰기(git 폴더 설치가 연결 키 2줄을 추가)·대시보드 재시작 권한. Caddy를 쓰는 설치만 Caddyfile 수정 권한(§2.6.2) |
| 실행 계정 | ESL 루트 쓰기·입력 루트 읽기 권한. 기본은 현재 사용자 `Interactive` |
| ESL 루트 | Case 산출물 폴더(예 `E:/shared/ESL_WORK`). **SPDM master 밖**, 경로에 공백·`& | < > ^ % ! "` 금지 |
| 입력 루트 | 사용자가 HyperView TCL로 만든 rad·결과 CSV 폴더가 있는 공유(읽기 전용) |
| Altair | **불필요**(서버에서 외부 프로그램을 실행하지 않음 — 사용자 PC의 TCL 추출만 HyperView 사용) |

### 2.2 오프라인 묶음 만들기(폐쇄망 서버용 — 인터넷 되는 준비 PC)

```powershell
# Windows 준비 PC(저장소 폴더에서). 대시보드가 같은 PC에 있으면 -DashboardRoot 권장(대시보드 고정 Python 3.12·Node 22)
.\deploy\collect-offline.ps1 -DashboardRoot E:\VD_SIMULATION_WEB\simdashboard -DryRun
.\deploy\collect-offline.ps1 -DashboardRoot E:\VD_SIMULATION_WEB\simdashboard
# 실행 정책 오류(스크립트를 실행할 수 없습니다)가 나면 powershell -NoProfile -ExecutionPolicy Bypass -File …로 실행
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
| `caddy_frontend_root` | 프런트 배치 위치(Caddy `root`·환경변수 `ESL_FRONTEND_ROOT`. Vite 프록시로 쓰면 설정 `server.frontend_root`에 같은 값) | `D:\esl\frontend` |
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
| ⑪ | 연결 안내: 묶음은 **Caddy 기준**(스니펫·환경변수, §2.6.2). Caddy 없이 대시보드 Vite 프록시로 쓰려면 설정 `server.frontend_root`를 `caddy_frontend_root`로 두고(백엔드 재시작) 대시보드 `.env`에 두 줄(§2.6.1) — 묶음 설치는 대시보드 `.env`를 바꾸지 않는다 |

- 이전 묶음 `deploy.json`에 `"backend_serves_frontend": true`(작업 인자 `--frontend` 방식)가 있으면 설정 `server.frontend_root`(키가 없을 때만)로 이어받는다. 작업 인자에는 더 이상 `--frontend`가 없다.
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
| 인자 | 실행기 경로·`--runtime`·(필요할 때만)`--config` — 파일 경로만. 프런트 정적 서빙은 인자가 아니라 설정 `server.frontend_root` | 비밀값 없음 |

- 수동 조작: `Start-ScheduledTask ESL-Worker`, `Stop-ScheduledTask ESL-Worker`(백엔드도). 워커를 멈추면 실행 중 작업은 약 1분(lease) 뒤 `INTERRUPTED`.
- ESL은 외부 GUI 프로그램을 실행하지 않으므로 `Background`(세션 0)에서도 기능 차이가 없다(physicsai와 달리 세션 0 제약 없음). 매핑 드라이브를 입력·ESL 루트로 쓰면 세션별 매핑 문제는 같다(§13).
- 해제: `deploy\uninstall-tasks.ps1`.

### 2.6 접속 연결

#### 2.6.1 대시보드 Vite 프록시 + 백엔드 정적 서빙(기본)

운영 대시보드(`start.ps1`)는 Caddy 없이 Vite 서버가 화면을 주고, `/esl` 아래 요청 전체를 ESL 백엔드로 **경로 그대로** 넘긴다. 백엔드는 `/esl/api/*`를 API로, 그 밖의 `/esl/…`를 프런트 빌드(`server.frontend_root`)로 응답한다.

1. `esl_platform.yaml`의 `server.frontend_root`를 프런트 배치 폴더로 둔다. git 폴더 설치(§2.0)는 `setup.ps1`·`update-repo.ps1`이 `<git>\.runtime\frontend`로 넣는다(키가 없을 때만 — 이미 있는 값·`null`은 유지). 바꾸면 백엔드 재시작.
2. 대시보드 `<dashboard_root>\.env`에 두 줄을 넣고 대시보드를 다시 시작한다(포트는 `server.port`와 같게):

   ```dotenv
   VITE_ESL_TARGET=http://127.0.0.1:8110
   SIMDASH_ESL_ENABLED=true
   ```

   git 폴더 설치는 `setup.ps1`·`update-repo.ps1`이 **없을 때만 끝에 추가**한다(다른 줄·인코딩·줄 끝 보존, 바꾸기 전 `.runtime\_backup\<UTC>\dashboard.env`로 복사). 이미 있으면 "이미 들어 있음", 값이 다르면(예: 포트) 그대로 두고 경고한다 — 직접 고친다. 추가했으면 안내대로 **대시보드를 다시 시작**해야 반영된다. `VITE_ESL_TARGET`은 대시보드 Vite가 `/esl`을 이 주소로 프록시하게, `SIMDASH_ESL_ENABLED=true`는 대시보드 사이드바에 ESL 버튼을 보이게 한다(대시보드 쪽 지원 버전 필요).
3. 접속: `http://<대시보드 주소>/esl/`(대시보드에 로그인한 상태로). 이 PC 확인용 health: `http://127.0.0.1:8110/esl/api/health`.
   예: 대시보드가 `WINDOWS_WEB_PORT=8080`이면 ESL `http://<서버>:8080/esl/`, 대시보드 `http://<서버>:8080/home/`(`WINDOWS_WEB_BASE_PATH`, 기본 `/home/`).
   화면의 로그인·"대시보드로" 링크는 `auth.dashboard_public_login_url`(같은 origin 경로) — `setup.ps1`·`update-repo.ps1`이 대시보드 `.env`의 `WINDOWS_WEB_BASE_PATH`로 맞춘다(값이 `/`이거나 없을 때만, 직접 넣은 값은 유지).

- 서빙 규칙: `/esl` → 308 `/esl/`(쿼리 유지). 빌드 폴더 안의 파일은 그대로, 없는 경로는 `index.html`(화면 내부 경로 새로고침 대응). `index.html`은 `Cache-Control: no-cache`, 해시 이름 자산(`assets/`)은 1년 캐시. `..`·드라이브 경로·빌드 폴더 밖을 가리키는 링크는 404. `/esl/api/…`는 정적 처리로 가지 않는다(없는 API = JSON 404). 운영에서는 `/`를 가로채지 않는다(대시보드 몫).
- 정적 파일은 인증 없이 준다(화면이 `/esl/api/me`로 로그인 여부를 판단). API 인증은 그대로다.
- 빌드 폴더나 `index.html`이 없어도 백엔드는 기동한다. 환경 점검(§10)의 `server.frontend_root` 행이 WARN으로 알리고, 화면 요청은 404 "프런트 빌드가 없습니다". 설정하지 않으면(`null`) 행은 SKIP(외부 서빙).
- ESL 백엔드가 인증을 확인하는 대시보드 내부 주소 `auth.dashboard_internal_url`의 기본값 `http://127.0.0.1:8000`은 대시보드 `start.ps1`의 백엔드 기본 포트(`-BackendPort 8000`)와 같다. 대시보드를 다른 포트로 띄우면 이 값도 바꾼다.

#### 2.6.2 Caddy(대안)

대시보드 앞에 Caddy를 두는 설치(폐쇄망 묶음 설치의 기준)는 `deploy\caddy\esl.caddy` 내용을 **대시보드 Caddyfile 사이트 블록 안, catch-all `handle` 앞**(physicsai 스니펫 옆)에 넣는다. 이때 `server.frontend_root`는 `null`로 두어도 된다(프런트는 Caddy가 서빙).

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

- `{$…}`는 Caddy가 **설정을 읽을 때** 자기 프로세스 환경변수로 바꾼다. Caddy 실행 환경에 `ESL_PORT`(= `server.port`), `ESL_FRONTEND_ROOT`(= `caddy_frontend_root`, git 폴더 설치는 `<git>\.runtime\frontend`)를 두거나 값을 직접 적고 Caddy 설정을 다시 읽는다.
- 대시보드 사이드바 버튼은 대시보드 `.env` `SIMDASH_ESL_ENABLED=true`.
- PC 연결 코드 잠금(`client_token.*`): ESL은 Caddy 뒤에서 모든 요청이 `127.0.0.1`에서 오므로 기본(`trusted_proxies: []`)으로는 출발지를 구분하지 않고 **서버 전체 30회/15분**(`lock_global`·`lock_minutes`)으로 센다. Caddy가 붙이는 `X-Forwarded-For`를 믿으려면 `client_token.trusted_proxies: ["127.0.0.1", "::1"]` — 그러면 **PC 주소별 5회/15분**(`lock_per_source`).
- 확인: `http://<대시보드 주소>/esl/` → 대시보드 로그인 상태면 이름·프로젝트가 보인다(E0-5). 이 PC에서 health: `http://127.0.0.1:8110/esl/api/health`.

### 2.7 반입 자원(없음)과 솔버 의존성

서버에 따로 복사할 원본 자원이 없다(`deploy\RESOURCES.txt`). 입력(rad + 결과 CSV)은 사용자 PC에서 HyperView TCL로 만들고(루트 `update.bat` — 사용자 PC용), 서버는 `storage.input_roots` 아래에서 읽기만 한다. 솔버 가속(pypardiso·MKL, pyamg, psutil)은 `requirements.lock`에 포함되어 설치되며 환경 점검 `solver.*`로 확인한다.

#### 2.7.1 강성 평가 스터디 형상 엔진 paicad·OCP·gmsh(v0.9.0, 이전 이름: 비드 DOE) — 설치·확인

강성 평가 스터디(계약 `docs/contracts/esl_bead_doe.md` §6.4)는 physicsai-platform 의 `packages/paicad`(형상 엔진, 외부 명령)와 gmsh(③ STEP 만 시나리오 메싱)를 쓴다.
설치·업데이트 스크립트가 **기본 의존성 다음에 따로** 설치하며, 실패해도 설치·업데이트는 계속되고 **다른 기능은 그대로 — 강성 평가 스터디 만 비활성**이다
(콘솔 경고 `강성 평가 스터디 비활성(다른 기능은 그대로): …`, 화면 상단 "형상 엔진(paicad)이 설치되지 않았습니다(관리자 문의)").
관리자 권한은 필요 없다(설치 venv 안에만 설치).

| 무엇 | 고정 위치 | 설치 |
|---|---|---|
| paicad 0.14.0 | `deploy\paicad.lock` — physicsai 커밋(브랜치 `release/v0.2.14`)·버전·**정규화 wheel sha256**·빌드 도구 고정(`setuptools==80.9.0`). wheel 자체는 **저장소에 동봉**(v0.10.1): `deploy\wheels\paicad-0.14.0-py3-none-any.whl` | wheel 대조(`deploy\paicad_wheel.py verify`) 후 `pip install --no-index --no-deps` → `<런타임>\venv\Scripts\paicad.exe` |
| cadquery-ocp 7.8.1.1.post1(+vtk·matplotlib 계열), gmsh 4.15.2 | `deploy\requirements.lock` 의 `# ==== bead_doe` 절 | 묶음 wheels(`--no-index`) 또는 사내 pip 인덱스 |

- **paicad wheel 설치 우선순위(v0.10.1 — esl 단독 설치)**: `setup.ps1`·`update-repo.ps1`·`install.ps1`·`update.ps1` 모두 같은 순서로 찾는다
  (`Install-EslBeadDoe`, 설치 콘솔 끝 `… — <venv>\Scripts\paicad.exe (wheel: vendored)` 처럼 어느 것을 썼는지 표시).
  1. **저장소 동봉** `deploy\wheels\paicad-0.14.0-py3-none-any.whl`(git 폴더 = `<git>\deploy\wheels`, 묶음 = 묶음 `deploy\wheels`) — 설치 전
     lock 의 버전·sha256 과 대조하고 **불일치면 2·3 으로 넘어가지 않고 중단**(강성 평가 스터디 만 비활성, 사유 = 파일 손상·부분 갱신 →
     `git status` 확인 후 `git checkout -- deploy/wheels`. lock 은 고치지 않는다)
  2. 오프라인 묶음 `wheels\` · `deploy.json` 의 `paicad_wheels` 폴더
  3. `deploy.json` 의 `physicsai_root`(physicsai 저장소에서 빌드, 읽기만)

  즉 **physicsai 저장소·wheel 폴더 없이** `git pull` + `deploy\update-repo.ps1` 만으로 paicad 가 설치된다. `paicad_wheels`·`physicsai_root` 는 동봉 wheel 이
  없을 때만 쓰는 예비 경로다(지워도 됨). OCP·gmsh 등 런타임 의존은 그대로 `requirements.lock` bead_doe 절(사내 pip 인덱스 또는 묶음 wheels)이다.
- **오프라인 묶음(§2.2)**: v0.10.1 부터 `collect-offline.ps1`(`.sh`)은 동봉 wheel 을 **빌드 없이** 대조만 해서 묶음 `wheels\` 에 넣는다(GitHub·git 불필요,
  `.sh` 는 `--no-download` 여도 넣음). `-PhysicsaiRepo`·`-PaicadWheel` 을 주면 그쪽을 쓴다. 동봉 wheel 이 없을 때(예전 방식)는 `collect-offline.ps1` 이 lock 커밋의 `packages/paicad` 를 GitHub 에서 그 커밋만 받아(또는 `-PhysicsaiRepo <로컬 physicsai 저장소>`, 읽기만)
  빌드·정규화하고 버전·sha256 을 lock 과 대조해 `wheels\paicad-0.14.0-py3-none-any.whl` 로 넣는다. **불일치면 묶음을 만들지 않고 중단**한다.
  이미 빌드된 wheel 은 `-PaicadWheel <파일>`(대조만), 강성 평가 스터디 없이 묶으려면 `-NoPaicad`. 준비 PC 에 git 이 있어야 한다(빌드 시).
  `install.ps1`·`update.ps1` 은 묶음의 `wheels` 에서 설치한다(추가 매개변수 없음).
- **git 폴더 설치(§2.0·§3.0)**: paicad 는 PyPI 에 없다 — v0.10.1 부터 동봉 wheel 로 설치되므로 아래 값은 **필요 없다**. 동봉 wheel 이 없는 예전 판에서만
  `<git>\.runtime\deploy.json` 에 둘 중 하나를 적는다(없으면 이미 설치된 paicad 확인만, 없으면 DOE 비활성).
  - `"paicad_wheels": "E:/.../wheels"` — 위 묶음의 `wheels` 폴더처럼 `paicad-0.14.0-py3-none-any.whl` 이 있는 폴더(대조 후 설치)
  - `"physicsai_root": "E:/.../physicsai-platform"` — lock 커밋이 들어 있는 physicsai 저장소(읽기만 — 커밋이 없으면 그 저장소에서 `git fetch` 후 다시 실행).
    `<런타임>\paicad-wheel` 에 빌드한다(사내 pip 설정으로 setuptools 를 받음)
- 설정: 설치 venv 에 `paicad.exe` 가 **실제 있을 때만** `setup_config.py` 가 `bead_doe.paicad.exe`(비었을 때만)·`bead_doe.enabled: true`(키가 없을 때만 —
  명시 `false` 는 그대로, 경고 1줄)를 넣는다. 바꾸기 전 `_backup\<UTC>\esl_platform.yaml`, 콘솔 1줄 `강성 평가 스터디 자동 설정: …`. `commands.paicad_*` 는 코드 기본값
  (argv[0] `{paicad}` = `bead_doe.paicad.exe`)이라 쓰지 않는다. `upload.allowed_ext` 를 직접 적은 설정에는 `.step`·`.stp` 를 한 번 보충한다(상태 `state\ext_supplement.json` 키 `0.9.0`).
- **확인 명령**(설치 후, 일반 PowerShell):

```powershell
& '<런타임>\venv\Scripts\paicad.exe' version --json          # {"paicad": "0.14.0", "ocp": "7.8.1…", "numpy": …} — paicad ≥ 0.14.0, ocp 가 null 이 아니어야 함
& '<런타임>\venv\Scripts\python.exe' -c "import gmsh; print(gmsh.__version__)"   # 4.15.2 — 실패하면 ③(STEP 만)·STEP 내보내기만 비활성
& '<런타임>\venv\Scripts\python.exe' '<deploy>\paicad_wheel.py' check --lock '<deploy>\paicad.lock' --exe '<런타임>\venv\Scripts\paicad.exe'
# v0.10.1: 동봉 wheel 도 함께 대조 — 결과 "wheel": {"ok": true, "sha256": "<lock 과 같음>"}
& '<런타임>\venv\Scripts\python.exe' '<deploy>\paicad_wheel.py' check --lock '<deploy>\paicad.lock' --exe '<런타임>\venv\Scripts\paicad.exe' --wheel '<deploy>\wheels\paicad-0.14.0-py3-none-any.whl'
```

  (git 폴더 설치의 `<deploy>` = `<git>\deploy`, 묶음은 묶음을 푼 폴더의 `deploy`.) `check` 결과 JSON 의 `problems` 코드는 화면 비활성 사유와 같다:
  `PAICAD_NOT_FOUND`(실행 파일 없음) · `PAICAD_VERSION_LOW`(< 0.14.0) · `PAICAD_OCP_MISSING`(OCP 로드 실패 — VC++ 런타임·`cadquery-ocp` 설치 확인) · `PAICAD_CHECK_FAILED`(실행 실패)
  · `PAICAD_WHEEL_NOT_FOUND`·`PAICAD_WHEEL_MISMATCH`(`--wheel` 로 준 동봉 wheel 이 없음·lock 과 다름).
  고정 버전과 다른 paicad(예 0.15.x)는 **경고만**(관리자 화면·결과에 기록). 워커가 `bead_doe.paicad.check_interval_s`(600 s)마다 같은 점검을 해 `GET /doe/settings` 에 반영한다.
- **lock 갱신**(paicad 새 버전): physicsai 의 새 커밋으로 `deploy\paicad.lock` 의 `version`·`branch`·`commit`·`wheel` 을 바꾸고,
  `python deploy\paicad_wheel.py collect --lock deploy\paicad.lock --out-dir <임시>` 가 출력하는 `sha256` 을 확인해 lock 에 적은 뒤 다시 실행해 `ok: true` 를 확인한다.
  그다음 `--out-dir deploy\wheels` 로 한 번 더 실행해 동봉 wheel 을 새 버전으로 바꾸고(옛 wheel 파일은 지움) lock 과 함께 커밋한다
  (`tests/deploy` 가 동봉 wheel sha256 = lock 을 확인).
  `runtime_requires` 의 `cadquery-ocp` 고정이 바뀌면 `requirements.lock` bead_doe 절도 같은 값으로 바꾸고 `scripts/test-all` 을 다시 돌린다.
  정규화(무압축·고정 시각·권한·순서)는 빌드 OS·시각과 무관하게 같은 바이트를 만들므로 Windows·Linux 준비 PC 결과를 같은 sha256 으로 대조한다.
- 묶음 크기: OCP·vtk·gmsh 로 수백 MB 늘어난다. gmsh 는 GPL(+링크 예외) — 사내 설치 용도.

#### 2.7.2 SCX 릴레이 — 'SCX 드라이브에서 고르기'(v0.11.0, 계약 [esl_scx_relay.md](../contracts/esl_scx_relay.md))

새 Case 4번째 탭 **SCX 드라이브에서 고르기**는 같은 서버의 **대시보드 SCX 릴레이**(loopback 내부 HTTP `/internal/scx-relay/v1`)를 거쳐 SCX 드라이브의 rad·include·h3d 를 esl 워커가 직접 내려받는다. esl 은 SCX 토큰·어댑터 로그인을 갖지 않고 **드라이브에 쓰지 않는다**(읽기만). 설정이 없거나 틀리면 esl 은 정상 기동하고 이 탭만 비활성 + 사유(다른 탭 그대로).

**① 대시보드 쪽(대시보드 `.env`, 대시보드 관리자가 설정 후 대시보드 백엔드 재시작)**

| 환경변수 | 값 | 비고 |
|---|---|---|
| `SIMDASH_SCX_RELAY_ENABLED` | `true` | 꺼져 있으면 사유 `SCX_RELAY_DISABLED` |
| `SIMDASH_DRIVE_GATEWAY` | `scx` | 아니면 `SCX_DRIVE_MODE_OFF` |
| `SIMDASH_SCX_RELAY_SECRET_FILE` | 공유 비밀 파일 절대경로(예 `D:\secrets\scx_relay.key`) | esl `hpc.scx.secret_file` 이 **같은 파일**을 가리키게(복사 금지 권장). 값이 다르면 `SCX_RELAY_UNAUTHORIZED` |
| `SIMDASH_SCX_RELAY_DRIVE_BASE` | 릴레이 읽기 기준 폴더(공용 계정 홈 기준, 예 `share`) | esl `scx_drive.roots[].rel` 은 이 안이어야 함. SPDM 마스터 루트(`SIMDASH_SCX_DRIVE_ROOT`)는 릴레이가 항상 거부 |
| `SIMDASH_SCX_RELAY_MAX_DOWNLOAD_BYTES` | **≥ 64 GiB 권장**(`68719476736`) | 기본 20 GiB 이면 30 GB h3d 는 시작 전 422 `SCX_FILE_TOO_LARGE`. 환경 점검 `scx.relay.max_download_bytes` 가 경고 |
| (대시보드 임시 공간) | 가장 큰 h3d × 동시 내려받기 수(`worker.xfer_lanes`) 이상 여유 | 릴레이는 SCX → 자기 임시 폴더로 **전부 받은 뒤** esl 로 스트리밍(Range 없음). 부족하면 `SCX_DASHBOARD_DISK` |
| `SIMDASH_DRIVE_WRITES_ENABLED` | (v0.11.0 은 불필요) | 검증 낙하(v0.12.0)에서만 필요 |

**② 비밀 파일 권한(Windows)**: 대시보드·esl 서비스 계정(같은 계정 권장)과 Administrators 만 읽기. `Everyone`·`Users`·`Authenticated Users` 읽기가 있으면 환경 점검 `hpc.scx.secret_file` 이 `SCX_SECRET_ACL_WIDE` 경고.

```powershell
icacls D:\secrets\scx_relay.key /inheritance:r /grant:r "<서비스계정>:R" "Administrators:F"
```

비밀 값은 esl 프로세스 메모리에만 있고 로그·오류·설정 응답에는 경로만 나온다.

**③ esl 설정(`<런타임>\config\esl_platform.yaml`)** — `hpc.scx` 는 physicsai 의 `hpc.scx` 블록을 그대로 복사하고 `client_name` 만 더한다.

```yaml
hpc:
  scx:
    relay_url: "http://127.0.0.1:8000"     # 대시보드 백엔드 loopback 포트(화면·프록시 포트 아님, 경로 없이)
    secret_file: ""                        # "" = 대시보드 따라가기(아래 표). 명시하면 절대경로(예 "D:\\secrets\\scx_relay.key")
    dashboard_root: "D:\\simdashboard"      # v0.12.0 대시보드 설치 폴더(setup 이 형제 폴더에서 자동 감지 — secret_file "" 일 때)
    client_name: "esl"
    max_download_bytes: 68719476736        # 64 GiB — 실제 상한 = min(이 값, 대시보드 상한, upload.max_file_bytes)
    transfer_timeout_s: 14400              # 30 GB h3d: 대시보드 임시 받기 + 스트리밍
    health_ttl_s: 30
    # (나머지 키 drive_base·appliance·version·ncpu… 는 검증 낙하 v0.12.0 용 — 예시 파일 값 그대로)
scx_drive:
  enabled: true                            # 기본 false
  roots:                                   # 릴레이 기준 상대(첫 구간 '.' 금지). key ^[a-z0-9_-]{1,32}$ 유일
    - {key: drop, label: "낙하해석", rel: "share/drop"}   # projects 생략 = 모든 프로젝트(아니면 projects: [프로젝트 id…])
  list_max_entries: 5000
  max_files: 2000                          # rad + include + 엔진 rad 합계
  engine_globs: ["{stem}_0001.rad", "{stem}_000[2-9].rad"]
  file_retries: 2                          # 끊김·SCX_BUSY·해시 불일치 시 파일당 자동 재시도
  retry_wait_s: 30
verify_drop:
  enabled: false                           # v0.12.0 검증 낙하(켜면 /scx/status.verify 판정 — 릴레이 쓰기·잡 API·appliance 필요)
worker:
  xfer_lanes: 2                            # XFER 레인 루프 수(1~8) = 동시 SCX 내려받기 수. SLOT·LIGHT 와 독립
```

**비밀 파일 경로 해석(v0.12.0)** — `hpc.scx.secret_file` 에 절대경로를 쓰면 그대로(상대경로는 설정 오류). 비워 두면(`""`) **대시보드 비밀 파일을 따라간다**(대시보드는 릴레이를 켜면 `SIMDASH_SCX_RELAY_SECRET_FILE` 절대경로가 필수이고 `<대시보드>\.env` 또는 `<대시보드>\backend\.env` 에서 읽는다):

| 순서 | 출처 | 비고 |
|---|---|---|
| 1 | esl 프로세스 환경변수 `SIMDASH_SCX_RELAY_SECRET_FILE` | 절대경로만 |
| 2 | `hpc.scx.dashboard_root` 의 `.env` → `backend\.env` | 그 키 줄만 읽음(python-dotenv 형식 — `export`·따옴표·주석). 다른 값은 읽지도 로그에도 남기지 않음 |
| 3 | `<런타임>\secrets\scx_relay_key` | 설치 기본 위치 |

셋 다 없으면 `SCX_SECRET_INVALID` + 안내. 환경 점검 `hpc.scx.secret_file` 에 `출처: env | 대시보드 .env(<경로>) | 런타임 기본 | 설정` 이 보인다(값은 출력하지 않음). `setup.ps1`·업데이트는 `dashboard_root` 가 비어 있으면 esl 설치 폴더의 형제 폴더 중 `backend\app\services\drive\config.py` 가 있는 대시보드를 찾아 넣는다(콘솔 1줄).

- 받은 파일은 사용자 업로드 폴더(`storage.upload_root`)에 저장되므로 `upload.max_file_bytes`(파일당)·`max_upload_bytes`(업로드당)·`min_free_gb`(여유, 부족하면 507 `INSUFFICIENT_STORAGE{need, free, reserve}`)와 `upload.allowed_ext`(rad·inc·k·sta·str·h3d 포함)가 그대로 적용된다. 사용자당 동시 업로드 한도(`max_concurrent_per_user`)도 SCX 세션을 센다(429 `UPLOAD_LIMIT`).
- starter 는 `<이름>_0000.rad` 만 고를 수 있다(화면 hint `rad`). 같은 폴더의 엔진 rad(`engine_globs`)와 include(상대·`../`·상태 파일 .sta/.str)는 워커가 rad 를 읽어 자동으로 받는다. 절대경로·루트 밖·드라이브에 없는 include 는 받지 않고 사용자가 SCX 탭의 **[추가로 올리기]**로 같은 세션에 넣는다.
- 적용: 설정을 고친 뒤 `ESL-Backend`·`ESL-Worker` 재시작(§4.2). 대시보드 쪽을 고쳤으면 대시보드 백엔드도 재시작 — esl 은 health 를 `health_ttl_s` 마다 다시 본다(재시작 불필요).
- 확인: 환경 점검(§10) `scx.adapter`·`hpc.scx`·`hpc.scx.secret_file`·`scx.relay`·`scx.relay.max_download_bytes`·`worker.xfer_lanes`, 그리고 실기 체크리스트 [scx_check.md](scx_check.md).
- 어댑터(`simdash_adapters`, physicsai 커밋 고정 `deploy\simdash_adapters.lock`)는 저장소 동봉 wheel 로 설치된다. 설치 실패 시 SCX 기능만 비활성(`SCX_ADAPTER_MISSING`) — 설치·업데이트를 다시 실행.

| 화면 사유(코드) | 조치 |
|---|---|
| `SCX_NOT_CONFIGURED` / `SCX_FETCH_DISABLED` / `SCX_NO_ROOTS` | `hpc.scx` 블록 / `scx_drive.enabled: true` / 이 프로젝트에 허용된 `roots` 추가 |
| `SCX_RELAY_UNREACHABLE` | 대시보드 백엔드 실행 여부, `relay_url` 포트 |
| `SCX_RELAY_FORBIDDEN` | `relay_url` 이 프록시·화면 포트를 가리킴 → 백엔드 loopback 포트로 |
| `SCX_PATH_NOT_ALLOWED` "대시보드가 SPDM 폴더 읽기를 막고 있습니다" | 읽기(조회·내려받기)의 SPDM 판정은 대시보드 relay 가 한다(esl 은 숨기거나 막지 않음 — SPDM 루트의 상위 폴더 `SharedWithMe` 같은 루트도 조회 가능). 그 폴더가 필요하면 대시보드 relay 설정. 검증 낙하 쓰기 폴더(`drive_base`)는 esl 이 SPDM 안·상위를 계속 거부 |
| `SCX_RELAY_UNAUTHORIZED` / `SCX_SECRET_INVALID` | 두 앱이 같은 비밀 파일을 읽는지, 파일 형식 — 고친 뒤 두 앱 재시작 |
| `SCX_AUTH_REQUIRED` | 대시보드 관리 화면에서 SCX 재로그인 |
| `SCX_FILE_TOO_LARGE` | `SIMDASH_SCX_RELAY_MAX_DOWNLOAD_BYTES`·`hpc.scx.max_download_bytes`·`upload.max_file_bytes` 상향 |
| `SCX_DASHBOARD_DISK` / `INSUFFICIENT_STORAGE` | 대시보드 임시 공간 / esl `storage.upload_root` 드라이브 여유 |

> **들여쓰기 주의**: `scx_drive`·`verify_drop`·`worker` 는 **최상위 키**다. `hpc:` 밑(또는 `hpc.scx:` 밑)에 들여쓰면 esl 은 physicsai 공용 키처럼 조용히 무시한다 — v0.12.0 부터 설정 검증(설치 콘솔)·환경 점검 `config.valid` 가 WARN "hpc.scx_drive 는 최상위 키입니다 — 들여쓰기를 없애세요". 루트 항목 키는 `rel`(릴레이 홈 기준 상대)이다(`path` 아님).

#### 2.7.3 Radioss 검증 낙하(v0.12.0, 계약 [esl_scx_relay.md](../contracts/esl_scx_relay.md) 기능 B)

강성 평가 스터디(① 같은 모델·완료) 화면의 **[검증 낙하]**는 고른 안의 모핑 좌표를 원 Case 입력 사본에 노드 ID 기준으로 넣어 씬마다 SCX 에서 Radioss 낙하를 다시 돌리고 원 낙하와 비교한다(PASS/FAIL 없음). §2.7.2 의 릴레이 연결이 먼저 되어 있어야 하고, 추가로 **대시보드 드라이브 쓰기**와 **잡 API** 가 필요하다.

**드라이브 폴더 분리**: 공유 홈(릴레이 홈)은 조회(기능 A) 위주, PBS 제출은 계정 **전용 폴더**에 만든다. `hpc.scx.drive_base` 가 `"~"`(홈 자체)이면 `verify_drop.enabled` 일 때 설정 경고 + 검증 낙하만 비활성 `VD_DRIVE_BASE_SHARED`("검증 낙하는 전용 폴더가 필요합니다: hpc.scx.drive_base 를 \"~/<전용 폴더>\" 로"). 권장 `drive_base: "~/esl"`, 조회 루트는 `scx_drive.roots: [{key: drop, label: "낙하해석", rel: "share/drop"}]`.

**① 대시보드 쪽**: `SIMDASH_DRIVE_WRITES_ENABLED=true`(아니면 `SCX_WRITES_OFF`), 대시보드 어댑터 v0.3.0 이상(잡 API — 아니면 `SCX_JOB_API_OFF`). `SIMDASH_SCX_RELAY_DRIVE_BASE`(relay_base) 안에 esl `hpc.scx.drive_base` 가 있어야 함(아니면 `SCX_BASE_OUTSIDE_RELAY`).

**② esl 설정** — `hpc.scx` 의 `drive_base`·`appliance`·`version`·`ncpu` 와 최상위 `verify_drop`:

```yaml
hpc:
  scx:
    # … §2.7.2 의 relay_url·secret_file·client_name …
    drive_base: "~/esl"                    # 검증 낙하 전용 쓰기 폴더("~/<상대>" — "~" 홈 자체면 VD_DRIVE_BASE_SHARED) — 대시보드 relay_base 안
    appliance: "<SCX Radioss appliance>"   # 필수(비면 SCX_APPLIANCE_MISSING)
    version: "26.1"                        # 대화상자 '고급' 기본값(작업별 덮어쓰기 가능)
    ncpu: 16
verify_drop:                               # 최상위 키(hpc 밑 아님)
  enabled: true                            # 기본 false(VD_DISABLED)
  max_scenes: 5                            # 한 요청의 씬(= SCX 제출) 수 상한 — 넘으면 422 VD_TOO_MANY_SCENES
  default_worst_n: 3                       # '가장 나쁜 씬 N개' 기본 N(대화상자 초기값)
  max_running: 2                           # 동시 활성(VD_STAGE 이후 진행) VERIFY_DROP 수 — 넘는 것은 QUEUED 로 대기
  est_hours_per_scene: 3                   # 예상 시간 표시 기본값(같은 프로젝트 완료 기록이 있으면 그 중앙값)
  poll_s: 60                               # SCX 잡 상태 폴링 주기
  max_wait_h: 72                           # 넘으면 VD_WAIT_TIMEOUT(SCX 잡은 종료하지 않음 — [재시도]는 폴링부터)
  out_ok_patterns: ["NORMAL TERMINATION"]  # Radioss out 정상 종료 판정
  max_result_bytes: 68719476736            # 회수(h3d·out) 상한 64 GiB
  compare: {same_tol: 0.02, hot_n: 20}     # '비슷' 허용치 · 상위 요소 수
```

| 키 | 기본 | 뜻 |
|---|---|---|
| `verify_drop.enabled` | `false` | 기능 B 켜기. 꺼져 있으면 버튼 비활성 사유 `VD_DISABLED`. 켰는데 `hpc.scx.drive_base: "~"` 면 `VD_DRIVE_BASE_SHARED` |
| `verify_drop.max_scenes` | 5 | 한 번에 제출할 씬 상한(라이선스·SCX 시간 보호). 대화상자가 이 값을 상한으로 표시 |
| `verify_drop.default_worst_n` | 3 | '가장 나쁜 씬 N개'의 기본 N(1~`max_scenes`) |
| `verify_drop.max_running` | 2 | 동시 활성 검증 낙하 수(동시 활성 상한). 같은 (안, 씬)은 비종료 1개만(`VD_ALREADY_ACTIVE` — 제외 목록) |

**③ 드라이브 폴더**: 씬마다 `<drive_base>/<project_id>/VD<n>_<UTC>`(예 `~/esl/body/VD7_20261030T091200`, `<n>` = 그 프로젝트의 검증 낙하 순번, UTC `YYYYMMDDTHHMMSS`). 원 Case 의 rad 폴더 기준 상대 배치를 그대로 올린다(include 가 rad 폴더 밖·절대경로·`include_path_map` 이면 그 씬은 제외 `VD_INCLUDE_LAYOUT`). 화면 카드에 표시 경로(복사 버튼)가 보인다. esl 은 이 폴더를 지우지 않는다(정리는 SCX 쪽에서).

**④ 제외·오류 코드(씬별 제외는 오류가 아니라 대화상자 경고)**: `VD_CUMULATIVE_EXCLUDED`(누적 씬 — .sta/.str 상태 파일), `VD_ENGINE_MISSING`(엔진 rad 없음), `VD_INCLUDE_LAYOUT`, `VD_ALREADY_ACTIVE`(같은 안·씬 진행 중), `VD_CASE_NOT_READY`(원 Case 가 없거나 보관됨·추출 결과 없음 — Case 추출을 먼저). 제출 결과를 모르면(`SCX_SUBMISSION_UNKNOWN`) 자동으로 다시 내지 않는다: 사용자가 SCX 화면에서 잡을 확인해 **[잡 ID 연결]**(서버가 폴링부터 새 작업을 자동으로 큐 — 재시도 불필요) 또는 **[포기]**(뒤 [재시도] = 새 제출).

- 적용: 설정 수정 후 `ESL-Backend`·`ESL-Worker` 재시작. 대시보드 쪽을 고쳤으면 대시보드 백엔드 재시작.
- 확인: 환경 점검 `scx_drive.enabled`·`scx.relay`(둘 다 꺼져 있으면 SKIP), 관리자 `GET /esl/api/scx/status?project_id=<id>` 의 `verify.enabled: true`.
- **실기 확인 V-SR-R1(B)**: 실 릴레이·22만 요소 Ch/R ① 최적 안 1건 — [scx_check.md](scx_check.md) §7 표(폴더·include 배치·NORMAL TERMINATION 판정·h3d 이름·coord_check·`requested_by=esl`·대용량 회수 시간·실행 중 취소)를 채워 둔다.

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

### 2.8.1 서버 시작·멈춤·재시작(v0.6.0)

`deploy\esl-start.bat`·`esl-stop.bat`·`esl-restart.bat`을 더블클릭(관리자 권한 불필요). 작업 스케줄러 작업 ESL-Backend·ESL-Worker를 다루고 health 주소·로그 위치는 `.runtime\deploy.json`과 설정에서 읽는다.
시작·재시작은 health 확인까지 기다려 성공/실패와 로그 위치(`.runtime\logs`)를 한글로 보여 주고 창은 `pause`로 남는다. 중지·재시작은 대기·실행 중 계산 작업이 있으면 경고 후 Y/N을 묻는다(`-Force`면 묻지 않음).
한쪽만: `deploy\esl-restart.bat -Only worker`(또는 `backend`). 직접 호출: `powershell -NoProfile -ExecutionPolicy Bypass -File deploy\esl-service.ps1 -Action start|stop|restart [-Only backend|worker] [-Force]`.

### 2.9 개발 실행(참고)

`scripts/test-all`(Linux, PostgreSQL 임시 클러스터) — 코어·플랫폼·워커·배포(`tests/deploy`)·프런트. 백엔드 직접 실행: `ESL_PLATFORM_CONFIG=config/esl_platform.yaml ESL_DATABASE_URL=… python deploy/esl_service.py backend`(런타임 없이 환경변수 사용).

---

## 3. 업데이트·제거·백업

### 3.0 업데이트(git 폴더 설치 — §2.0)

**일반 Windows PowerShell**에서 **한 줄**(인자·질문 없음 — 값은 `.runtime\deploy.json`, `git pull`도 스스로):

```powershell
E:\VD_SIMULATION_WEB\esl-platform\deploy\update-repo.ps1
# 실행 정책 오류(스크립트를 실행할 수 없습니다)가 나면 powershell -NoProfile -ExecutionPolicy Bypass -File …로 실행
```

끝 줄은 `업데이트 성공 — 접속: …` 또는 `업데이트 실패 — 접속: …`(`http://<서버>:<대시보드 .env WINDOWS_WEB_PORT, 기본 80>/esl/`).

| 단계 | 내용 |
|---|---|
| ⓪ | `git pull --ff-only`(자격 증명을 묻지 않음 — 인증 필요 시 바로 실패). 추적 파일에 로컬 변경이 있으면 안내 후 중단(바꾼 것 없음). 분리된 HEAD·추적 브랜치 없음이면 pull 없이 현재 커밋. 새 커밋을 받으면 받은 새 `update-repo.ps1`로 이어서 실행 |
| ① | 대기·실행 중 작업 확인(`jobs.state` QUEUED·RUNNING, DB 직접 조회). 있으면 안내 후 중단(`-Force`면 진행) |
| ② | 작업 2개 중지 |
| ③ | venv 의존성 갱신(`requirements.lock`). venv가 3.12로 실행되지 않으면 `_backup`으로 옮기고 새로 |
| ④ | 코드 스냅샷 `.runtime\app`(이전 것은 `_backup\<UTC>\app`) |
| ⑤ | 설정 보충(기존 값 유지, 새로 생긴 관리 키만 — 예: P2 이전 설정에 `library` 블록, `server.frontend_root`가 없으면 `.runtime\frontend`). 대시보드 `.env` `VITE_ESL_TARGET`·`SIMDASH_ESL_ENABLED`가 없으면 추가(백업 후 — "대시보드를 다시 시작해야 /esl/ 연결이 반영됩니다") |
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

완전 제거(백업 후): ① 대시보드 `.env`에서 `VITE_ESL_TARGET`·`SIMDASH_ESL_ENABLED` 삭제 → 대시보드 재시작(Caddy를 쓰면 Caddyfile에서 ESL 스니펫 삭제 → Caddy 다시 읽기) ② 런타임 폴더의 `secrets\database_url` 삭제 ③ DB `esl`·역할 `esl_app` 삭제(`pg_dump` 후) ④ 런타임 폴더 정리 ⑤ **ESL 루트의 Case·라이브러리·분석 폴더는 사용자 산출물** — 플랫폼은 지우지 않는다.

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
| `server.host` / `port` / `base_path` | 루프백 바인딩 / 포트(대시보드 `.env` `VITE_ESL_TARGET` 또는 Caddy `ESL_PORT`와 일치) / `/esl`(바꾸지 않음) | `127.0.0.1` / `8110` / `/esl` |
| `server.frontend_root` | 백엔드가 `/esl/` 아래에 직접 서빙할 프런트 빌드 폴더(절대경로, §2.6.1). `null` = 서빙 안 함(Caddy 등 외부 서빙). 바꾸면 백엔드 재시작 | git 폴더 설치 `<git>/.runtime/frontend`, 묶음·예시 `null` |
| `database.url_env` | DB URL 환경변수 **이름**(실행기가 런타임 파일 값을 이 이름으로 넣음) | `ESL_DATABASE_URL` |
| `auth.dashboard_internal_url` | 대시보드 백엔드 내부 주소 | `http://127.0.0.1:8000` |
| `auth.dashboard_public_login_url` | 로그인·"대시보드로" 링크(같은 origin 경로) — 설치가 `WINDOWS_WEB_BASE_PATH`로 맞춤 | `/home/` |
| `storage.esl_root` | Case 산출물 루트(쓰기, SPDM 밖) | 설치 시 입력 |
| `storage.input_roots` | rad·결과 폴더 선택 허용 루트(읽기 전용). 비면 Case 생성 불가 | 설치 시 입력 |
| `storage.spdm_roots` | 겹침 검사용 SPDM 루트 | `[]` |
| `worker.heartbeat_interval_s` / `lease_ttl_s` | 하트비트 / 리스(취소·중단 감지) | `10` / `60` |
| `worker.max_logical_cores` / `max_memory_gb` / `priority` / `limiter` | 자원 제한(Windows: Job Object — 메모리(커밋 합계)·CPU 비율·우선순위·워커 종료 시 자식 종료 / POSIX: nice·RLIMIT_AS·affinity). `limiter`: auto|windows_job|posix|none. `max_memory_gb` 근거: 서버 RAM 512 GB, 30만 요소 직접법 RSS 약 13 GB·100만 요소 추정 45 GB(×1.5 ≈ 68 GB) 수용 + 대시보드·physicsai 공유 여유 — 서버 RAM 이 다르면 약 1/4 | `16` / `128` / `below_normal` / `auto` |
| `worker.vm_headroom` | POSIX 전용: RLIMIT_AS(가상 주소 공간) = `max_memory_gb` × 이 값(가상 크기 VmPeak 가 실사용 RSS 보다 큼). Windows Job 메모리는 커밋 기준이라 곱하지 않음. 없으면 1.5 | `1.5` |
| `ui.max_preview_points` | ⑤ 겹쳐보기·2D 산점 최대 점 수 | `20000` |
| `core.config_path` | 코어 설정(`esl.yaml` — t*·솔버·판정 기준 `validation`·`compare`) | `esl.yaml` |
| `report.auto` | VALIDATE 성공 시 Case 보고서 자동 | `true` |
| `history.backup_scan_max` | 실행 이력: 이전 검증 파일을 `_backup` 에서 표식으로 찾을 때 열어 보는 폴더 최대 수(최신 순, 넘으면 "파일 보존 안 됨" 으로 기록된 값만 표시) | `100` |
| `history.archive_files` | 실행 이력: 내보내기(⑥)·Case 보고서 성공 시 `<Case>\history\<작업 id>\` 에 작업별로 복사해 두어 나중에도 그때 파일을 받을 수 있게 함(Case 폴더 용량이 실행당 내보내기·보고서 크기만큼 늘어남, 정리 정책 없음). 끄면 이후 실행분은 기록된 값만 표시 | `true` |
| `library.config_path` | 라이브러리·분석·덱 설정(없으면 라이브러리 쓰기 API 503) | `library.yaml` |
| `ui.library_export_enabled` | v0.10.0 라이브러리 [내보내기](여러 ESL zip) 화면 노출. `false`(기본) = 화면 숨김, `/library/exports` API 는 전역 관리자만(그 외 403 `EXPORT_DISABLED`). 비드 최적화·강성 평가가 플랫폼 안에서 돌아 수작업 외부 계산용으로 켤 때만 | `false` |
| `library_export.max_entries` | v0.10.0 라이브러리 내보내기 한 번에 고를 수 있는 ESL 수(넘으면 422 `TOO_MANY_ENTRIES`). 화면은 `GET /version` 의 `ui.library_export_max_entries` 로 같은 값을 받아 [내보내기] 비활성 사유에 씀 | `50` |
| `library_export.max_bundle_bytes` | 내보내기 zip 상한(넘으면 413 `BUNDLE_TOO_LARGE` + `_exports\<묶음>` 경로 안내). `null` = `ui.max_bundle_bytes` | `null` |
| `library_export.wait_s` | 같은 모델 ESL 이 서로 다른 Case 작업에 나뉘었을 때 앞 항목 ID 결과를 기다리는 최대 초(넘으면 항목 실패 `EXPORT_ORDER_TIMEOUT`) | `600` |

- 코어 `esl.yaml`의 `solver.backend: auto` → Windows에서 `pardiso`(pypardiso·MKL). `extract.disp_precision`은 TCL 출력 정밀도(H3D 보통 `float32`).
- v0.12.1 코어 `esl.yaml` `extract` 선택 키(h3d 변형률 결과 대체, 계약 `esl_strain_fallback.md`): `dump_keep`(기본 `false`) — `Strain` 텐서 대체 시 원자료(`strain_raw.csv`·`disp.csv`)를 변환 후 서버 추출 폴더에서 지운다. `true` 면 보존(문제 조사용, 용량은 프레임 수 × 요소 수 × 층 수에 비례). `dump_max_bytes`(기본 42949672960 = 40 GiB) — 원자료 크기 상한. 추출 전에 추정하고 실제 크기도 다시 봐서 넘으면 `STRAIN_DUMP_TOO_LARGE`, 디스크 여유가 모자라면 `INSUFFICIENT_STORAGE`. 대체 순서·결과 이름 후보는 `extract.strain_sources`·`result_names`·`tensor_comps`·`vm_comps`·`scalar_comps`·`tensor_layer_exclude`(없으면 기본값, `config/esl.example.yaml` 주석 참고).
- v0.12.1 플랫폼 설정 `bead_doe.fixed_scan`(강성 평가 스터디 체결 스캔 입력 정규화): paicad `fixed-scan` 에 넘기는 **모델 전체 사본 `prep/assem_full/`**(②③ A Case = `prep/a_assem_full/`)에서만 paicad 0.14.0 이 못 읽는 집합 카드를 같은 의미로 바꿔 쓴다 — 원본·run 모핑 결과 파일은 바뀌지 않는다(모핑 사본 중 재작성 파일은 원본 + 모핑 `/NODE` 좌표로 복원). `enabled`(기본 `true`, 정규화 전체 끄고 켜기) · `rules`(기본 `[[SURF/PART/EXT, SURF/PART], [SURF/PART/ALL, SURF/PART]]`, 키워드 줄만 `["KW/SUB/OPT", "KW/SUB"]` 형식으로 바꿈, 최대 50개) · `expand_subset`(기본 `true`, `/SURF/SUBSET/<EXT|ALL>`·`/GRNOD/SUBSET` → 파트 목록) · `expand_gene`(기본 `true`, `/GRNOD/GENE` → `/GRNOD/NODE`) · `expand_solid`(기본 `true`, 솔리드 파트를 포함한 `/SURF/PART`·`SUBSET` → `/SURF/SEG`, EXT = 외곽 면, ALL = 모든 면) · `subset_format`(기본 `auto`, `auto`|`2024`|`2026`|`legacy` — `/SUBSET` 해석 규칙. `auto` = starter `/BEGIN` Invers 칸(없으면 머리 주석 `#RADIOSS STARTER … 2024.1`)으로 2026 이상이면 `2026`, 아니면 `2024`. 2024·2026 = `/SUBSET` 데이터는 하위 subset 목록만이고 파트 소속은 `/PART` 셋째 칸, `legacy` = 데이터에 파트 id 도 허용. 설정값·실제 사용값은 매니페스트·로그에 기록). `/GRNOD/GENE` 은 (first, last) 쌍, 증분은 `/GRNOD/GEN_INCR` 로 읽는다. 사본 범위는 기준 starter 의 include 트리 전체(폴더 밖 상위·형제 포함, 허용 루트 밖·링크는 `PATH_OUTSIDE_ROOT`), 엔진 rad 포함 여부 `bead_doe.same.engine_rad`(기본 `false`), 합계 상한 `bead_doe.same.max_assem_mb`(기본 4096). 스캔 시간 상한 `bead_doe.paicad.timeout_s.fixed_scan`(기본 3600 s). 체결 정의를 못 찾으면 `FIXED_PARSE_FAILED`(읽은 파일 수·솔리드 면 tie 미지원 안내).
- 코어 `esl.yaml` 선택 절 `support.auto_check`(v0.10.0 ② 3-2-1 자동 선택 품질 검사, 없으면 기본값): `min_area_ratio` 0.10(세 점 공선) · `min_dist_rel` 0.15(두 점 근접, 대각선 대비) · `min_cond_ratio` 1e-3(구속 조건비) · `expand_candidates` true(PCA 4꼭지점 실패 시 8후보 탐색) · `rule_version` 1. **임시값** — 실제 파트에서 자동 선택이 자주 막히면(사용자 화면 "지지점을 자동으로 정하지 못했습니다") 값을 조정. 판정 cfg 에 주입하지 않아 설정 해시·보고서 불변.
- 라이브러리 내보내기 출력은 `<esl_root>\_exports\<묶음 id>\`(batch.json·ESL 별 폴더·logs·manifest·README)에 쌓이고 정리 정책이 없다(묶음당 수십 MB) — 용량이 차면 오래된 묶음 폴더를 지운다(지우면 그 묶음 zip 다시 받기 불가).
- 판정 기준(`validation.*`, `compare.*`)과 ISTA 6 낙하 높이 표는 **임시값·TODO** — 사내 확인 후 교체(§15).
- 라이브러리 설정(`library.yaml`)의 설계 버전 비교 수렴 기준 `convergence`: `cos_min`(기본 0.95), `rep_same`(기본 true — 짝 대표(medoid)의 cos ≥ `cos_min` 이면 같은 대표, medoid 씬이 달라도 됨), `min_nodes_per_cell`(기본 64 — 셀당 노드 중앙값이 이보다 작으면 경고, 16 미만이면 "판정 신뢰 낮음" 배지), `coarsen`(false|half — 2×2 셀 묶음으로 cos 계산, 12×7 이하 격자에서는 무시). 설치본 `library.yaml`은 업데이트 때 덮어쓰지 않으므로 빠진 키는 이 기본값으로 채운다(이전 기본 0.9 를 적어 둔 파일은 그 값이 유지됨).
- 오류 코드 `SOLVER_OUT_OF_MEMORY`: 쉘 솔버(조립·분해·해)나 코어 처리 중 메모리 부족(MemoryError, PARDISO error -2, CHOLMOD out-of-memory). 비양정치·구속 부족(`SOLVER_SINGULAR`)과 구분된다 — 13장 FAQ.

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
| `config.valid` | 스키마·의미(루트 겹침·경로 문자)·코어·라이브러리 설정 검증. 오류 → FAIL(키: 메시지). v0.12.0: `hpc`·`hpc.scx` 밑에 들여쓴 최상위 키(`scx_drive`·`verify_drop`·`worker` 등 — 조용히 무시됨) → WARN "hpc.scx_drive 는 최상위 키입니다 — 들여쓰기를 없애세요" |
| `config.auth` / `config.library` | dev_static이면 WARN(prod면 FAIL) / library 블록 없음 → WARN |
| `server.frontend_root` | 프런트 정적 서빙(§2.6.1): 폴더와 `index.html`이 있으면 OK, 없으면 WARN(백엔드는 기동, 화면 404), `null`이면 SKIP(Caddy 등 외부 서빙) |
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
| `scx.adapter` / `scx.adapter.lock` | v0.11.0 SCX 릴레이 어댑터 import·버전·커밋 / 코드 고정값 = `deploy/simdash_adapters.lock`(다르면 FAIL) |
| `hpc.scx` / `hpc.scx.secret_file` | 설정 검사(없으면 SKIP — SCX 안 씀) / 비밀 파일 형식·Windows 권한(`SCX_SECRET_ACL_WIDE` WARN)·`출처: env \| 대시보드 .env(<경로>) \| 런타임 기본 \| 설정`, 값은 출력 안 함 |
| `scx_drive.enabled` | v0.12.0 기능 A 켜짐/꺼짐 · roots 개수(켜졌는데 0개면 WARN `SCX_NO_ROOTS`) |
| `scx.relay` / `scx.relay.max_download_bytes` | 대시보드 릴레이 health(연결·drive_mode·job_api) — 실패면 켜진 기능 쪽의 실제 원인 코드 WARN(`SCX_RELAY_UNREACHABLE` 등, `*_DISABLED` 아님). `scx_drive`·`verify_drop` 둘 다 꺼짐이면 SKIP(릴레이 시험 안 함) / 상한 < 64 GiB 면 WARN |
| `worker.xfer_lanes` | XFER 레인 수(동시 SCX 내려받기) |

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

**Q. 작업이 `SOLVER_OUT_OF_MEMORY`로 실패한다.** 코어 자식이 메모리 한도에 걸렸다. `worker.max_memory_gb`(Windows: Job 안 코어 자식 커밋 합계 — SLOT·LIGHT 동시 실행분 포함, POSIX: × `vm_headroom` 가상 한도)와 서버 가용 메모리를 확인하고, 동시에 도는 다른 작업을 줄이거나 코어 `solver.backend: iterative`(반복법)를 쓴다. 특이(`SOLVER_SINGULAR`)와는 원인이 다르다(구속·메시 문제가 아님).

**Q. ESL 계산이 매우 느리거나 메모리 부족.** 환경 점검 `solver.backend`가 `superlu`면 pypardiso/MKL이 로드되지 않은 것이다(`solver.pypardiso` 메시지). 묶음 설치면 wheels에 mkl·intel-openmp·tbb가 있는지 확인. 코어 `validation.full_solve`(auto|never)도 본다.

**Q. 화면이 "대시보드에서 로그인하세요"만 보인다 / 503.** 같은 주소(origin)로 접속했는지, `auth.dashboard_internal_url`로 대시보드 백엔드에 닿는지.

**Q. 회사 프록시(`HTTP_PROXY`)에서 health 확인이 실패한다.** 설치 스크립트·시연의 127.0.0.1 호출은 프록시를 쓰지 않는다(`loopback-http.ps1`, physicsai와 같은 처리). pip·npm은 기존 프록시 설정을 그대로 쓴다.

**Q. `.bat` 실행이 "액세스가 거부되었습니다".** `.\deploy\install.ps1`(또는 `setup.ps1`, `demo\start-demo.ps1`)처럼 `.ps1`을 직접 실행한다(인자 동일). 실행 정책 오류(스크립트를 실행할 수 없습니다)가 나면 `powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install.ps1`로 실행한다.

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
| 대시보드 Vite 프록시 `VITE_ESL_TARGET`·사이드바 `SIMDASH_ESL_ENABLED`(대시보드 쪽 지원 버전) / Caddy 스니펫(대안) | 실기 미검증 | E0-5 |
| 워커 자원 제한: `worker.limiter`·`max_logical_cores`·`max_memory_gb`·`vm_headroom`·`priority` | **적용됨(실기 미검증)** — POSIX는 Linux 자식 프로세스 실제 적용 시험, Windows Job Object는 가짜 kernel32 인자 시험 + 64비트 구조체 배치(basic 64 B·extended 144 B·JobMemoryLimit 오프셋 120·CPU 8 B) 단언만. 할당 실패 시 작업 step이 `LIMITER_FAILED`, 한도 초과는 `SOLVER_OUT_OF_MEMORY` — `python -m esl_platform.check`의 `worker.limiter` 행 확인 | §4.3, E2E E0 |
| 판정 기준(`validation`·`compare`)·ISTA 6 낙하 높이 | 임시값·TODO | 코어 `esl.yaml`, `ista6.yaml` |
