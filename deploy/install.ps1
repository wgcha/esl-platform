<#
.SYNOPSIS
  ESL Windows 폐쇄망 설치(오프라인 묶음 esl-offline-<version>.zip 방식 — 폐쇄망 서버용. 같은 PC·git 폴더 설치는 setup.ps1). 실제 Windows 실행은 사용자 E2E로 확인한다(미검증).
.DESCRIPTION
  physicsai-platform deploy\install.ps1과 같은 절차. 일반 PowerShell(관리자 권한 불필요. Background 모드 작업 등록만 관리자 권한이 필요할 수 있음).
  ① Python 3.12 확인(대시보드와 같은 3.12.13 권장, python_exe를 실제로 실행 — python-select.ps1)
  ② venv 생성·오프라인 wheel 설치(wheels, deploy\requirements.lock — pypardiso·MKL 포함) ③ 코드 배치(<install_root>\app — 묶음의 app 폴더)
  ④ 프런트 배치(묶음의 빌드본 → caddy_frontend_root) ⑤ 설정 파일(setup_config.py: 없으면 config\esl_platform.prod.example.yaml로 만들고
  deploy.json의 esl_root·input_roots·spdm_roots를 넣음, 있으면 보존·빠진 키만 보충, esl.yaml·library.yaml·ista6.yaml 없을 때만 복사, ESL 루트 폴더 생성)
  ⑥ DB 역할·DB(없을 때만 생성) ⑦ DB 접속 정보 파일 <install_root>\secrets\database_url(현재 사용자·SYSTEM만 읽기 — 머신 환경변수 쓰지 않음)
  ⑧ alembic upgrade head(0001~0004) ⑨ 작업 스케줄러 등록(ESL-Backend, ESL-Worker — 실행기 app\esl_service.py backend|worker --runtime <install_root>)
  ⑩ 시작·health·환경 점검 표 ⑪ 연결 안내 — 묶음은 Caddy 기준(esl.caddy 스니펫). Caddy 없이 대시보드 Vite 프록시로 쓰려면
  설정 server.frontend_root를 caddy_frontend_root로 두고 대시보드 .env에 VITE_ESL_TARGET·SIMDASH_ESL_ENABLED(관리자 매뉴얼 §2.6.1).
  경로 문자열은 deploy.json(예: deploy.example.json 복사)과 매개변수에만 있다. 비밀번호는 Read-Host -AsSecureString으로
  받아 PGPASSWORD 프로세스 환경변수로만 전달하고 로그·설정 파일·명령 인자에 남기지 않는다.
  deploy.json에 dashboard_root(선택)가 있으면 대시보드 .env의 POSTGRES_BIN과 DATABASE_URL의 host·port, 대시보드 고정 Python 3.12를
  pg_bin·pg_host·pg_port·python_exe의 기본값으로 쓴다(deploy.json 명시 값 우선, dashboard-env.ps1). PostgreSQL 서버가 18이 아니면 경고.
.PARAMETER ConfigFile
  설치 매개변수 JSON(기본: 이 폴더의 deploy.json).
.PARAMETER ServiceUser
  작업 실행 계정(기본 deploy.json service_user). ESL 루트 쓰기·입력 루트 읽기 권한이 있는 계정.
.PARAMETER RunMode
  Background(로그온 여부와 관계없이, 세션 0 — 작업 등록에 관리자 권한이 필요할 수 있음) | Interactive(로그온 사용자 세션, 관리자 불필요). 기본 deploy.json run_mode.
.PARAMETER PasswordsFromEnv
  무인 설치(CI·자동화)용: 비밀번호를 대화형 입력 대신 이 프로세스 환경변수에서 읽는다
  (ESL_INSTALL_PG_ADMIN_PASSWORD, ESL_INSTALL_DB_PASSWORD, Background면 ESL_INSTALL_SERVICE_PASSWORD). 명령 인자로는 받지 않는다.
.PARAMETER NoStart
  작업 등록까지만 하고 시작·health 확인(⑩)은 하지 않는다.
#>
[CmdletBinding()]
param(
    [string]$ConfigFile = '',   # 비우면 이 스크립트 폴더의 deploy.json (PS 5.1은 param 기본값에서 $PSScriptRoot가 빔)
    [string]$ServiceUser,
    [ValidateSet('Background', 'Interactive')][string]$RunMode,
    [switch]$PasswordsFromEnv,
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
if (-not $ConfigFile) { $ConfigFile = Join-Path $PSScriptRoot 'deploy.json' }
$EslTag = 'ESL 설치'
. (Join-Path $PSScriptRoot 'install-common.ps1')
function Write-Step([string]$m) { Write-EslStep $m }

# ---- 매개변수 -------------------------------------------------------------------
if (-not (Test-Path $ConfigFile)) { throw "설치 매개변수 파일이 없습니다: $ConfigFile (deploy.example.json을 복사해 수정하세요)" }
$ConfigFile = [IO.Path]::GetFullPath($ConfigFile)
$cfg = Get-Content -Raw -Encoding UTF8 $ConfigFile | ConvertFrom-Json
if (-not $ServiceUser) { $ServiceUser = "$($cfg.service_user)" }
if (-not $ServiceUser) { $ServiceUser = "$env:USERDOMAIN\$env:USERNAME" }
if (-not $RunMode) { $RunMode = if ("$($cfg.run_mode)" -eq 'Background') { 'Background' } else { 'Interactive' } }
$dash = $null
if ($cfg.dashboard_root) {
    . (Join-Path $PSScriptRoot 'dashboard-env.ps1')
    $dash = Get-DashboardRuntimeDefaults -DashboardRoot $cfg.dashboard_root
    $filled = Merge-DashboardDefaults -Config $cfg -Defaults $dash
    Write-Step "대시보드 환경($($cfg.dashboard_root)): 기본값으로 채운 키 = $(if ($filled.Count) { $filled -join ', ' } else { '없음(deploy.json 명시 값 사용)' })"
}
foreach ($k in 'install_root', 'pg_bin', 'pg_host', 'pg_port', 'python_exe') {
    if ("$($cfg.$k)" -eq '') { throw "deploy.json에 $k 값이 없습니다(직접 쓰거나 dashboard_root로 대시보드 환경을 지정하세요)" }
}
$root = "$($cfg.install_root)".TrimEnd('\')
$pkg = Split-Path -Parent $PSScriptRoot          # 오프라인 묶음 루트(wheels, frontend, app, config, deploy)
foreach ($need in 'wheels', 'frontend\index.html', 'app\backend\esl_platform', 'config\esl_platform.prod.example.yaml') {
    if (-not (Test-Path -LiteralPath (Join-Path $pkg $need))) { throw "오프라인 묶음 구성이 아닙니다(없음: $(Join-Path $pkg $need)) — 묶음을 푼 폴더의 deploy\install.ps1을 실행하세요(git 폴더면 setup.ps1)" }
}
$configPath = if ("$($cfg.config_path)") { "$($cfg.config_path)" } else { Join-Path $root 'config\esl_platform.yaml' }
$frontendRoot = if ("$($cfg.caddy_frontend_root)") { "$($cfg.caddy_frontend_root)" } else { Join-Path $root 'frontend' }
$venvPy = Join-Path $root 'venv\Scripts\python.exe'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backupDir = Join-Path $root "_backup\$stamp"

# ---- ① Python 3.12(대시보드와 같은 마이너) ---------------------------------------------------------
. (Join-Path $PSScriptRoot 'python-select.ps1')
$basePy = Assert-EslPython312 -Exe "$($cfg.python_exe)"
Write-Step "Python $($basePy.Version): $($basePy.Exe)"

# ---- ② venv + 오프라인 wheel(재설치면 먼저 작업 중지 — 실행 중인 venv의 DLL·코드를 바꾸지 않게) ----------------------------
New-Item -ItemType Directory -Force -Path $root | Out-Null
if (Get-ScheduledTask -TaskName 'ESL-Backend' -ErrorAction SilentlyContinue) {
    $oldUrl = Get-EslDbUrl -RuntimeDir $root
    if ($oldUrl -and (Test-Path -LiteralPath (Join-Path "$($cfg.pg_bin)" 'psql.exe'))) { Assert-EslNoActiveJobs -PgBin "$($cfg.pg_bin)" -DbUrl $oldUrl }
    Remove-Variable -Name oldUrl -ErrorAction SilentlyContinue
    Stop-EslTasks
    Write-Step '기존 작업 중지(재설치)'
}
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Step "venv 생성: $root\venv"
    Invoke-EslNative 'venv 생성' $basePy.Exe @('-m', 'venv', (Join-Path $root 'venv')) "설치 폴더 쓰기 권한과 Python($($basePy.Exe))의 venv 모듈을 확인하세요"
}
Install-EslPackages -VenvPy $venvPy -LockFile (Join-Path $PSScriptRoot 'requirements.lock') -Wheels (Join-Path $pkg 'wheels')

# ---- ③ 코드 배치 · ④ 프런트 배치(이전 것은 _backup) -------------------------------------------------
Install-EslApp -Source (Join-Path $pkg 'app') -Dest (Join-Path $root 'app') -BackupDir $backupDir
Publish-EslFrontend -Dist (Join-Path $pkg 'frontend') -Dest $frontendRoot -BackupDir $backupDir

# ---- ⑤ 설정 파일(있으면 보존 — 빠진 키만 보충) -------------------------------------------------------------
# deploy.json 파일은 바꾸지 않는다 — 비어 있는 값만 이번 실행의 기본값(대시보드 환경으로 채운 pg_*·python_exe 포함)으로 메모리에서 보충
$defaults = [ordered]@{ install_mode = 'bundle'; install_root = $root; python_exe = "$($cfg.python_exe)"; pg_bin = "$($cfg.pg_bin)"
    pg_host = "$($cfg.pg_host)"; pg_port = [int]$cfg.pg_port; db_name = 'esl'; db_role = 'esl_app'; config_path = $configPath
    caddy_frontend_root = $frontendRoot; service_user = $ServiceUser; run_mode = $RunMode }
$inputs = [ordered]@{ mode = 'bundle'; source_root = $pkg; code_root = (Join-Path $root 'app'); runtime_dir = $root; stamp = $stamp
    deploy_path = $ConfigFile; deploy_defaults = $defaults; deploy_explicit = [ordered]@{} }
if ($dash -and $dash.WebBasePath) { $inputs['dashboard_web_base_path'] = "$($dash.WebBasePath)" }
$result = Invoke-EslSetupConfig -VenvPy $venvPy -Action write -RuntimeDir $root -Inputs $inputs
Write-EslConfigValidation -Result $result | Out-Null
$d = $result.deploy

# ---- ⑥ DB(없을 때만) — 비밀번호는 Read-Host -AsSecureString(또는 -PasswordsFromEnv), PGPASSWORD 프로세스 환경으로만 ----------
$url = Initialize-EslDatabase -PgBin $d.pg_bin -PgHost $d.pg_host -PgPort ([int]$d.pg_port) -DbName $d.db_name -DbRole $d.db_role `
    -PasswordsFromEnv:$PasswordsFromEnv -ReuseExisting -ExistingUrl (Get-EslDbUrl -RuntimeDir $root)

# ---- ⑦ DB 접속 정보 파일(<install_root>\secrets\database_url — 관리자 권한 불필요) ----------------------
Write-EslRuntimeSecret -RuntimeDir $root -DbUrl $url -ServiceUser $ServiceUser
Remove-Variable -Name url -ErrorAction SilentlyContinue

# ---- ⑧ migration --------------------------------------------------------------------------
Invoke-EslMigration -VenvPy $venvPy -RuntimeDir $root -ConfigPath $configPath

# ---- ⑨ 작업 스케줄러 등록(ExecutionTimeLimit 0·RestartCount 999·IgnoreNew — install-common.ps1) ---------------------------------
Register-EslTasks -VenvPy $venvPy -WorkDir $root -ServiceUser $ServiceUser -RunMode $RunMode -RuntimeDir $root -ConfigPath $configPath `
    -PasswordsFromEnv:$PasswordsFromEnv

# ---- ⑩ 시작·health·환경 점검 ------------------------------------------------------------------------
$ep = Get-EslEndpoint -ConfigPath $configPath -VenvPy $venvPy -Launcher (Get-EslLauncher $root)
if ($NoStart) {
    Write-Step '-NoStart: 작업 시작·health 확인을 건너뜁니다(Start-ScheduledTask -TaskName ESL-Backend, ESL-Worker로 시작)'
    return
}
Start-EslTasksAndWait -HealthUrl $ep.Health -LogDir (Join-Path $root 'logs') | Out-Null
Invoke-EslCheck -VenvPy $venvPy -RuntimeDir $root -ConfigPath $configPath | Out-Null

# ---- ⑪ 연결 안내(묶음은 Caddy 기준 + Vite 프록시를 고르는 방법) --------------------------------------------------------------------------
Write-Host ''
Write-Step '설치 완료. 남은 연결 작업:'
Write-EslConnectGuide -Port $ep.Port -BasePath $ep.BasePath -DashboardRoot "$($cfg.dashboard_root)" -FrontendRoot $frontendRoot -SnippetDir (Join-Path $PSScriptRoot 'caddy') -Bundle
Write-Step "  3) 설정: $configPath (입력 루트 storage.input_roots, 판정 기준은 같은 폴더 esl.yaml). 고친 뒤 Stop/Start-ScheduledTask ESL-Worker, ESL-Backend"
