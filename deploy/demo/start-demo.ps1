<#
.SYNOPSIS
  ESL 시연 모드 원클릭 시작(Altair·HyperView 없이 — 합성 낙하 Case). 관리자 권한 불필요. physicsai deploy\demo\start-demo.ps1과 같은 구조.
.DESCRIPTION
  ① Python 준비(저장소·묶음 공통): Python 3.12를 골라 <시연 폴더>\venv를 만들고 거기에만 deploy\requirements.lock 설치
     (묶음: wheels / 저장소: 인덱스. 이미 설치돼 있으면 건너뜀). 프런트 빌드(저장소 frontend\dist)가 없으면 Node 22로 빌드
  ② demo_setup.py init: 시연 폴더·설정(<시연 폴더>\config\esl_platform.yaml — profile dev, dev_static, 127.0.0.1)·합성 Case 입력(rad + 결과 CSV)
  ③ DB: 시연 전용 PostgreSQL 클러스터(<시연 폴더>\pgdata, 127.0.0.1:PgPort, trust) 또는 -UseExistingDb
  ④ demo_setup.py up: migration → 백엔드(프런트 직접 서빙 포함, Caddy 불필요) → 워커 → 시연 Case 2개
     (demo_new = 입력만 — ①부터 직접, demo_done = ①~⑥ 완료 — 결과·보고서를 바로 봄. -NoPrerun이면 미리 돌리지 않음)
  ⑤ 브라우저로 http://127.0.0.1:<Port>/esl/ 열기(시연 관리자로 자동 로그인)
  끝내기: stop-demo.ps1 (파일·DB는 지우지 않는다)
.PARAMETER DemoRoot
  시연 폴더(공백·특수문자 없는 경로). 기본 <시스템 드라이브>\esl-demo
.PARAMETER Port
  백엔드 포트(127.0.0.1 전용). 운영(8110)·physicsai(8100)·physicsai 시연(8190)과 겹치지 않게 기본 8191
.PARAMETER PythonExe
  Python 3.12(대시보드와 같은 3.12.13 권장). 선택 순서: -PythonExe > -DashboardRoot의 고정 Python 3.12 > py -3.12 > PATH의 python
.PARAMETER PgBin
  PostgreSQL bin 폴더(initdb.exe·pg_ctl.exe·psql.exe, 기준 18). 비우면 -DashboardRoot의 .env POSTGRES_BIN → PATH → PGBIN 환경변수 순
.PARAMETER DashboardRoot
  대시보드 폴더(선택). .env의 POSTGRES_BIN과 .tools 고정 Python 3.12·Node 22를 기본값으로 쓴다(비밀번호는 읽지 않음)
.PARAMETER PgPort
  시연 전용 PostgreSQL 포트(기본 55433 — physicsai 시연 55432와 겹치지 않게)
.PARAMETER UseExistingDb
  시연 클러스터 대신 기존 PostgreSQL의 빈 DB 사용. 접속 URL은 환경변수 ESL_DEMO_DATABASE_URL로 준다(명령 인자에 비밀번호 금지)
.PARAMETER NoPrerun
  ①~⑥ 완료 Case(demo_done)를 미리 돌리지 않는다(입력만 있는 Case 2개)
.PARAMETER NoBrowser
  브라우저를 열지 않는다
#>
[CmdletBinding()]
param(
    [string]$DemoRoot = (Join-Path $env:SystemDrive 'esl-demo'),
    [int]$Port = 8191,
    [string]$PythonExe = '',
    [string]$PgBin = '',
    [string]$DashboardRoot = '',
    [int]$PgPort = 55433,
    [switch]$UseExistingDb,
    [switch]$NoPrerun,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
function Write-Step([string]$m) { Write-Host "[ESL 시연] $m" }
function Assert-Ok([string]$what) { if ($LASTEXITCODE -ne 0) { throw "$what 실패(종료코드 $LASTEXITCODE)" } }

if ($DemoRoot -match '[\s&|<>^%!";,=()]') { throw "시연 폴더 경로에 공백·특수문자를 쓸 수 없습니다: $DemoRoot" }
$deployDir = Split-Path -Parent $PSScriptRoot
$pkg = Split-Path -Parent $deployDir   # 저장소 루트 또는 오프라인 묶음 루트
$setup = Join-Path $PSScriptRoot 'demo_setup.py'
New-Item -ItemType Directory -Force -Path $DemoRoot | Out-Null
$dash = $null
if ($DashboardRoot) {
    . (Join-Path $deployDir 'dashboard-env.ps1')
    $dash = Get-DashboardRuntimeDefaults -DashboardRoot $DashboardRoot
    Write-Step "대시보드 환경: $DashboardRoot (POSTGRES_BIN $(if ($dash.PgBin) { '있음' } else { '없음' }), Python 3.12 $(if ($dash.PythonExe) { '있음' } else { '없음' }))"
}

# ---- ① Python(<시연 폴더>\venv — 대시보드 런타임·시스템 Python에는 설치하지 않는다) ----------------
. (Join-Path $PSScriptRoot 'demo-python.ps1')
$cands = Get-EslPythonCandidates -PythonExe $PythonExe -DashboardPython $(if ($dash) { "$($dash.PythonExe)" } else { '' })
$wheels = Join-Path $pkg 'wheels'
$lock = Join-Path $deployDir 'requirements.lock'
if (Test-Path -LiteralPath $wheels) {
    $py = Initialize-DemoVenv -DemoRoot $DemoRoot -Candidates $cands -LockFile $lock -Wheels $wheels   # 오프라인 묶음
    $frontend = Join-Path $pkg 'frontend'
} else {
    $py = Initialize-DemoVenv -DemoRoot $DemoRoot -Candidates $cands -LockFile $lock                   # 저장소(인덱스)
    $frontend = Join-Path $pkg 'frontend\dist'
    if (-not (Test-Path -LiteralPath (Join-Path $frontend 'index.html'))) {
        Write-Step '프런트 빌드(frontend\dist)가 없어 만듭니다: npm ci → npm run build (Node 22, 몇 분 걸림)'
        . (Join-Path $deployDir 'node-select.ps1')
        $node = Select-EslNode -DashboardNode $(if ($dash) { "$($dash.NodeExe)" } else { '' }) -RepoRoot $pkg -Tag 'ESL 시연'
        Invoke-EslFrontendBuild -Node $node -RepoRoot $pkg
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $frontend 'index.html'))) { throw "프런트 빌드가 없습니다: $frontend`n다음 행동: 저장소면 frontend에서 npm ci; npm run build, 묶음이면 묶음을 다시 만드세요(deploy\collect-offline.ps1)." }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

# ---- ② 시연 폴더·설정·합성 Case 입력 --------------------------------------------------------------------
& $py $setup init --root $DemoRoot --port $Port --frontend $frontend; Assert-Ok '시연 준비(init)'

# ---- ③ DB --------------------------------------------------------------------------------------
if ($UseExistingDb) {
    if (-not $env:ESL_DEMO_DATABASE_URL) { throw '-UseExistingDb: 환경변수 ESL_DEMO_DATABASE_URL을 설정하세요(빈 DB)' }
    $env:ESL_DATABASE_URL = $env:ESL_DEMO_DATABASE_URL
    Write-Step '기존 PostgreSQL 사용(ESL_DEMO_DATABASE_URL — 값은 출력하지 않음)'
} else {
    if (-not $PgBin -and $dash -and $dash.PgBin) { $PgBin = $dash.PgBin }
    if (-not $PgBin) {
        $initdb = Get-Command initdb.exe -ErrorAction SilentlyContinue
        if ($initdb) { $PgBin = Split-Path -Parent $initdb.Source }
        elseif ($env:PGBIN) { $PgBin = $env:PGBIN }
        else { throw 'PostgreSQL bin 폴더를 -PgBin으로 지정하세요(initdb.exe·pg_ctl.exe·psql.exe가 있는 폴더 — 포터블 zip 압축 해제본도 됨)' }
    }
    $env:ESL_DATABASE_URL = $null   # 시연 클러스터 URL을 쓰게(이 프로세스 환경변수만 비움)
    & $py $setup db-up --root $DemoRoot --pg-bin $PgBin --pg-port $PgPort; Assert-Ok '시연 PostgreSQL 준비(db-up)'
}

# ---- ④ 백엔드·워커·시연 Case ------------------------------------------------------------------------------
$upArgs = @($setup, 'up', '--root', $DemoRoot)
if ($NoPrerun) { $upArgs += '--no-prerun' }
& $py @upArgs
if ($LASTEXITCODE -ne 0) {
    # up은 실패 시 자신이 띄운 백엔드·워커를 정리한다. 시연 DB는 켜 둔 채(다음 실행의 db-up이 그대로 재사용)
    throw ("시연 기동(up) 실패(종료코드 $LASTEXITCODE). 위 출력의 원인과 $DemoRoot\logs\demo-setup.log·backend.log·worker.log를 확인하세요.`n" +
        "다음 행동: 원인을 고친 뒤 이 스크립트를 다시 실행하세요(남은 프로세스는 자동 정리). DB까지 끄려면 $(Join-Path $PSScriptRoot 'stop-demo.ps1') -DemoRoot $DemoRoot")
}

# ---- ⑤ 안내 ------------------------------------------------------------------------------------
$demoUrl = "http://127.0.0.1:$Port/esl/"
Write-Step "시연 주소: $demoUrl  (시연 관리자로 자동 로그인 — dev_static)"
Write-Step "① 입력 경로: rad $DemoRoot\inputs\demo_drop\model_0000.rad · 결과 폴더 $DemoRoot\inputs\demo_drop\csv"
Write-Step "Case 산출물: $DemoRoot\esl_root\<Case 폴더>(07_report\report.html = Case 보고서)"
Write-Step "로그: $DemoRoot\logs   끝내기: $(Join-Path $PSScriptRoot 'stop-demo.ps1') -DemoRoot $DemoRoot"
if (-not $NoBrowser) { Start-Process $demoUrl }
