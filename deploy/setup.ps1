<#
.SYNOPSIS
  ESL 서버 같은 PC·git 폴더 설치(권장). 저장소를 받은 폴더에 그대로 설치한다 — 묶음·압축 없음. 다시 실행해도 안전(이미 있으면 확인 후 갱신).
.DESCRIPTION
  physicsai-platform deploy\setup.ps1과 같은 절차. 일반 Windows PowerShell(관리자 권한 불필요)에서:
    powershell -NoProfile -ExecutionPolicy Bypass -File <git 폴더>\deploy\setup.ps1
  (저장소 루트의 update.bat은 사용자 PC용 HyperView TCL 배포 — 서버 설치와 무관)
  ① Python 3.12 선택(python-select.ps1: -PythonExe > deploy.json > 대시보드 고정 Python > py -3.12 > PATH, 각 후보를 실제 실행해 확인)
  ② 런타임 폴더 <git>\.runtime\(그 안의 .gitignore로 git 제외): venv, app(코드 스냅샷), frontend(배치), config\esl_platform.yaml(+esl.yaml·library.yaml·ista6.yaml),
     secrets\database_url, deploy.json, logs, state, _backup
  ③ venv에 deploy\requirements.lock(고정 버전, pypardiso·MKL 포함 — 사내 pip 설정·프록시 그대로)
  ④ 설정 계획(setup_config.py): deploy.json·esl_platform.yaml — 이미 있으면 보존하고 빠진 키만 보충. profile prod, server.port 8110,
     server.frontend_root(= .runtime\frontend — 백엔드가 /esl/ 직접 서빙, 키가 없을 때만 — 바꾼 값·null 유지),
     storage.esl_root(폴더 생성, SPDM 밖)·input_roots·spdm_roots, auth.dashboard_public_login_url(대시보드 웹 경로), core·library 설정 파일,
     대시보드 .env VITE_ESL_TARGET·SIMDASH_ESL_ENABLED(없을 때만 끝에 추가 — 기존 값 보존, 바꾸기 전 _backup\<UTC>\dashboard.env)
  ⑤ 확인 표 출력 후 Y/N(-NonInteractive면 생략)
  ⑥ 기존 설치가 있으면 대기열 확인 후 작업 중지 → 패키지 갱신 → 코드 스냅샷(.runtime\app, 이전 것은 _backup) → 설정 작성 → 프런트 배치
     (소스가 바뀌었을 때만 Node 22로 빌드 — 대시보드 고정 Node 우선)
  ⑦ DB(대시보드와 같은 PostgreSQL 18에 esl DB·esl_app 역할 — 없을 때만, 기존 연결이 되면 비밀번호를 다시 묻지 않음)
     → DB 접속 정보 파일 .runtime\secrets\database_url(현재 사용자·SYSTEM만 읽기) → alembic upgrade head(0001~0004)
     → 작업 스케줄러 ESL-Backend·ESL-Worker(현재 사용자 Interactive·Limited, 실행기 esl_service.py --runtime) → 시작·health → 환경 점검 표
  ⑧ 접속 연결 안내: 대시보드 .env VITE_ESL_TARGET·SIMDASH_ESL_ENABLED=true(백엔드가 /esl/ 직접 서빙 — 추가했으면 대시보드 재시작), Caddy는 대안(esl.caddy)
  업데이트: powershell -NoProfile -ExecutionPolicy Bypass -File <git 폴더>\deploy\update-repo.ps1 (git pull 포함)
.PARAMETER DashboardRoot
  대시보드 폴더. 기본: deploy.json 값 → <git 폴더의 부모>\simdashboard(있으면). .env의 POSTGRES_BIN·DATABASE_URL(host·port만)과 .tools의 Python 3.12·Node 22를 쓴다
.PARAMETER EslRoot
  ESL 루트(Case 산출물, SPDM master 밖, 공백·특수문자 없는 경로). 기본: deploy.json 값 → <git 폴더의 부모>\esl-data
.PARAMETER UploadRoot
  브라우저 업로드 저장 위치(SPDM 밖, ESL 루트와 겹치지 않게). 기본: deploy.json 값 → <ESL 루트의 부모>\esl-input. input_roots에 자동 포함되고 폴더를 만든다
.PARAMETER InputRoots
  rad·결과 CSV 폴더를 고를 수 있는 루트(읽기 전용, 여러 개 가능 — 쉼표로 구분해 입력). 비우면(Enter) 설정 파일에서 나중에 채움
.PARAMETER SpdmRoots
  (선택) SPDM master 루트(겹침 검사용 — ESL 루트가 이 안이면 거부)
.PARAMETER PythonExe
  (선택) Python 3.12 python.exe
.PARAMETER ServiceUser
  작업 실행 계정. 기본: deploy.json 값 → 현재 사용자(<도메인>\<이름>)
.PARAMETER RunMode
  Interactive(기본, 그 계정 로그온 세션 — 관리자 권한 불필요) | Background(로그온 무관, 세션 0 Service 모드 — 계정 비밀번호를 한 번 더 받음.
  부팅 시 작업 등록이라 이 모드만 관리자 권한이 필요할 수 있다). ESL은 외부 프로그램을 실행하지 않으므로 세션 0 제약이 없다
.PARAMETER NonInteractive
  묻지 않는다(기본값·deploy.json 값 사용, 확인 표 Y/N 생략). 비밀번호가 필요하면 -PasswordsFromEnv
.PARAMETER PasswordsFromEnv
  비밀번호를 화면 입력 대신 프로세스 환경변수에서(ESL_INSTALL_PG_ADMIN_PASSWORD, ESL_INSTALL_DB_PASSWORD, Background면 ESL_INSTALL_SERVICE_PASSWORD)
.PARAMETER NoStart
  작업 등록까지만(시작·health 확인·환경 점검 생략)
.PARAMETER Force
  재실행 때 대기·실행 중 작업이 있어도 진행(실행 중 작업은 INTERRUPTED)
#>
[CmdletBinding()]
param(
    [string]$DashboardRoot = '',
    [string]$EslRoot = '',
    [string]$UploadRoot = '',
    [string[]]$InputRoots = @(),
    [string[]]$SpdmRoots = @(),
    [string]$PythonExe = '',
    [string]$ServiceUser = '',
    [ValidateSet('Background', 'Interactive')][string]$RunMode,
    [switch]$NonInteractive,
    [switch]$PasswordsFromEnv,
    [switch]$NoStart,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
# 경로 기본값은 본문에서 만든다(Windows PowerShell 5.1은 param 기본값에서 $PSScriptRoot가 빔)
$EslTag = 'ESL 설치'
. (Join-Path $PSScriptRoot 'install-common.ps1')
. (Join-Path $PSScriptRoot 'python-select.ps1')
. (Join-Path $PSScriptRoot 'node-select.ps1')
. (Join-Path $PSScriptRoot 'dashboard-env.ps1')
function Write-Step([string]$m) { Write-EslStep $m }

$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$parent = Split-Path -Parent $repo
$rt = Join-Path $repo '.runtime'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backupDir = Join-Path $rt "_backup\$stamp"

# ---- 0. 위치(관리자 권한 확인 없음) -------------------------------------------------------
if (-not (Test-Path -LiteralPath (Join-Path $repo 'pyproject.toml')) -or -not (Test-Path -LiteralPath (Join-Path $repo 'backend\esl_platform')) -or
    -not (Test-Path -LiteralPath (Join-Path $repo 'frontend\package.json'))) {
    throw "git 폴더(저장소)가 아닙니다: $repo`n다음 행동: 오프라인 묶음을 풀어 둔 폴더라면 deploy\install.ps1(폐쇄망 서버용)을 쓰세요."
}
Write-Step "git 폴더: $repo  (런타임 폴더: $rt — git에서 제외)"
New-Item -ItemType Directory -Force -Path $rt | Out-Null
Set-EslRuntimeGitIgnore -RuntimeDir $rt

$deployPath = Join-Path $rt 'deploy.json'
$prev = $null
if (Test-Path -LiteralPath $deployPath) {
    $prev = Get-Content -Raw -Encoding UTF8 -LiteralPath $deployPath | ConvertFrom-Json
    Write-Step "기존 설치 발견(deploy.json) — 확인 후 갱신합니다(기존 값 유지, 빠진 값만 보충)"
}
function Get-Prev([string]$Key) {
    if ($prev -and $prev.PSObject.Properties[$Key] -and "$($prev.$Key)" -ne '') { return $prev.$Key }
    return ''
}
$existingUrl = Get-EslDbUrl -RuntimeDir $rt
$legacyDb = ConvertFrom-EslDbUrl $existingUrl

# ---- 입력 값(명시 인자 > deploy.json > 파생 기본값). -NonInteractive가 아니면 Enter로 기본값 -------------------------
$explicit = [ordered]@{}
function Resolve-FullPath([string]$p) {
    # 상대경로는 현재 PowerShell 위치($PWD) 기준
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($p.Trim().Trim('"')).TrimEnd('\')
}
function Resolve-SetupValue {
    param([string]$Key, [string]$Given, [string]$Derived, [string]$Prompt, [switch]$AllowSkip)
    if ($Given) { $v = Resolve-FullPath $Given; $script:explicit[$Key] = $v; return $v }
    $def = "$(Get-Prev $Key)"
    if (-not $def) { $def = $Derived }
    if ($NonInteractive) { return $def }
    $hint = if ($def) { " [Enter = $def$(if ($AllowSkip) { ", '-' = 비움" })]" } elseif ($AllowSkip) { ' [Enter = 건너뜀]' } else { '' }
    $ans = "$(Read-Host "$Prompt$hint")".Trim().Trim('"')
    if ($AllowSkip -and $ans -eq '-') { $script:explicit[$Key] = ''; return '' }
    if ($ans) { $v = Resolve-FullPath $ans; $script:explicit[$Key] = $v; return $v }
    return $def
}
function Resolve-SetupList {
    <# 목록 값(input_roots·spdm_roots): 명시 인자 > deploy.json > 질문(쉼표 구분, Enter = 기존 값 유지, '-' = 비움). #>
    param([string]$Key, [string[]]$Given, [string]$Prompt)
    $g = @($Given | Where-Object { "$_".Trim() })
    if ($g.Count) { $v = @($g | ForEach-Object { Resolve-FullPath "$_" }); $script:explicit[$Key] = $v; return , $v }
    $def = @(Get-Prev $Key | Where-Object { "$_".Trim() })
    if ($NonInteractive) { return , $def }
    $hint = if ($def.Count) { " [Enter = $($def -join ', '), '-' = 비움]" } else { ' [Enter = 건너뜀]' }
    $ans = "$(Read-Host "$Prompt(쉼표로 여러 개)$hint")".Trim()
    if ($ans -eq '-') { $script:explicit[$Key] = @(); return , @() }
    if ($ans) {
        $v = @($ans.Split(',') | ForEach-Object { "$_".Trim().Trim('"') } | Where-Object { $_ } | ForEach-Object { Resolve-FullPath $_ })
        $script:explicit[$Key] = $v
        return , $v
    }
    return , $def
}
$derivedDash = Join-Path $parent 'simdashboard'
if (-not (Test-Path -LiteralPath $derivedDash -PathType Container)) { $derivedDash = '' }
$dashRoot = Resolve-SetupValue -Key 'dashboard_root' -Given $DashboardRoot -Derived $derivedDash -Prompt '대시보드 폴더'
$eslRootV = Resolve-SetupValue -Key 'esl_root' -Given $EslRoot -Derived (Join-Path $parent 'esl-data') -Prompt 'ESL 루트(Case 산출물 폴더, SPDM 밖)'
$uploadRootV = Resolve-SetupValue -Key 'upload_root' -Given $UploadRoot -Derived $(if ($eslRootV) { Join-Path (Split-Path -Parent $eslRootV) 'esl-input' } else { '' }) -Prompt '업로드 위치(브라우저로 올린 rad·h3d·결과 폴더 저장, SPDM 밖)'
$inputRootsV = Resolve-SetupList -Key 'input_roots' -Given $InputRoots -Prompt '입력 루트(rad·결과 CSV 폴더를 고를 수 있는 폴더, 읽기 전용)'
$spdmRootsV = Resolve-SetupList -Key 'spdm_roots' -Given $SpdmRoots -Prompt 'SPDM 루트(겹침 검사용, 선택)'
if ($ServiceUser) { $svcUser = $ServiceUser; $explicit['service_user'] = $svcUser } else { $svcUser = "$(Get-Prev 'service_user')" }
if (-not $svcUser) { $svcUser = "$env:USERDOMAIN\$env:USERNAME" }
# $RunMode는 ValidateSet 변수라 빈 값을 다시 넣을 수 없다 → 별도 변수
if ($RunMode) { $runModeV = $RunMode; $explicit['run_mode'] = $runModeV } else { $runModeV = "$(Get-Prev 'run_mode')" }
if ($runModeV -notin @('Background', 'Interactive')) { $runModeV = 'Interactive' }

$dash = $null
if ($dashRoot) {
    $dash = Get-DashboardRuntimeDefaults -DashboardRoot $dashRoot
    Write-Step "대시보드 환경: $dashRoot (POSTGRES_BIN $(if ($dash.PgBin) { '있음' } else { '없음' }), DB 포트 $(if ($dash.PgPort) { $dash.PgPort } else { '없음' }), Python 3.12 $(if ($dash.PythonExe) { '있음' } else { '없음' }), Node 22 $(if ($dash.NodeExe) { '있음' } else { '없음' }))"
}
$pgBin = "$(Get-Prev 'pg_bin')"; if (-not $pgBin -and $dash) { $pgBin = "$($dash.PgBin)" }
$pgHost = "$(Get-Prev 'pg_host')"; if (-not $pgHost -and $dash) { $pgHost = "$($dash.PgHost)" }; if (-not $pgHost -and $legacyDb) { $pgHost = $legacyDb.Host }
$pgPort = "$(Get-Prev 'pg_port')"; if (-not $pgPort -and $dash -and $dash.PgPort) { $pgPort = "$($dash.PgPort)" }; if (-not $pgPort -and $legacyDb) { $pgPort = "$($legacyDb.Port)" }
if (-not $pgBin -or -not $pgHost -or -not $pgPort) {
    throw ("PostgreSQL 위치를 정하지 못했습니다(pg_bin=$pgBin, host=$pgHost, port=$pgPort).`n" +
        "다음 행동: -DashboardRoot <대시보드 폴더>를 주세요(.env의 POSTGRES_BIN·DATABASE_URL을 씁니다). 또는 $deployPath 에 pg_bin·pg_host·pg_port를 쓰세요.")
}
$dbName = "$(Get-Prev 'db_name')"; if (-not $dbName) { $dbName = if ($legacyDb) { $legacyDb.Db } else { 'esl' } }
$dbRole = "$(Get-Prev 'db_role')"; if (-not $dbRole) { $dbRole = if ($legacyDb) { $legacyDb.User } else { 'esl_app' } }

# ---- ① Python 3.12 --------------------------------------------------------------------------
$pyFirst = if ($PythonExe) { $PythonExe } else { "$(Get-Prev 'python_exe')" }
$cands = Get-EslPythonCandidates -PythonExe $pyFirst -DashboardPython $(if ($dash) { "$($dash.PythonExe)" } else { '' })
$basePy = Select-EslPython -Candidates $cands -Tag $EslTag
if ($PythonExe) { $explicit['python_exe'] = $basePy.Exe }

# ---- ② venv(.runtime\venv) — 있으면 재사용, 3.12가 아니면 _backup으로 옮기고 새로 ----------------------------------------
$venv = Join-Path $rt 'venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
$lock = Join-Path $repo 'deploy\requirements.lock'
$freshVenv = $false
if (Test-Path -LiteralPath $venvPy) {
    $why = ''
    if (Test-EslPython312 -Exe $venvPy -Reason ([ref]$why)) {
        Write-Step "venv 재사용: $venv"
    } else {
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        Move-Item -LiteralPath $venv -Destination (Join-Path $backupDir 'venv')
        Write-Step "기존 venv가 Python 3.12로 실행되지 않아($why) 옮겼습니다: $backupDir\venv"
    }
}
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Step "venv 생성: $venv"
    Invoke-EslNative 'venv 생성' $basePy.Exe @('-m', 'venv', $venv) "런타임 폴더 쓰기 권한과 Python($($basePy.Exe))의 venv 모듈을 확인하세요"
    $freshVenv = $true
}
$hasDeps = (-not $freshVenv) -and (Test-EslVenvDeps -VenvPy $venvPy)
if (-not $hasDeps) {
    # ③ 처음(또는 패키지가 없는 venv): 설정 계획·검증에 yaml·pydantic이 필요하므로 먼저 설치
    Write-Step 'venv에 의존성 설치(deploy\requirements.lock — numpy·scipy·pypardiso·MKL 포함, 처음 한 번 몇 분 걸림)'
    Install-EslPackages -VenvPy $venvPy -LockFile $lock
}

# ---- ④ 설정 계획(파일은 아직 바꾸지 않음) ----------------------------------------------------------------
$defaults = [ordered]@{
    install_mode = 'repo'; repo_root = $repo; install_root = $rt; dashboard_root = $dashRoot; python_exe = $basePy.Exe
    pg_bin = $pgBin; pg_host = $pgHost; pg_port = [int]$pgPort; db_name = $dbName; db_role = $dbRole
    config_path = (Join-Path $rt 'config\esl_platform.yaml'); service_user = $svcUser; run_mode = $runModeV
    caddy_frontend_root = (Join-Path $rt 'frontend')
    esl_root = $eslRootV; upload_root = $uploadRootV; input_roots = [string[]]@($inputRootsV | ForEach-Object { "$_" }); spdm_roots = [string[]]@($spdmRootsV | ForEach-Object { "$_" })
}
$inputs = [ordered]@{ mode = 'repo'; source_root = $repo; code_root = $repo; runtime_dir = $rt; stamp = $stamp
    deploy_path = $deployPath; deploy_defaults = $defaults; deploy_explicit = $explicit }
if ($dash -and $dash.WebBasePath) { $inputs['dashboard_web_base_path'] = "$($dash.WebBasePath)" }
$plan = Invoke-EslSetupConfig -VenvPy $venvPy -Action plan -RuntimeDir $rt -Inputs $inputs
$d = $plan.deploy

# ---- ⑤ 확인 표 ------------------------------------------------------------------------------------
$cfgState = switch ($plan.config_source) {
    'existing' { if ($plan.config_changed) { "기존 유지 + 보충 $(@($plan.config_changed_keys).Count)개" } else { '기존 유지(변경 없음)' } }
    default { '새로 만듦(config\esl_platform.prod.example.yaml 기준 + esl.yaml·library.yaml·ista6.yaml)' }
}
$rows = @(
    [pscustomobject]@{ 항목 = 'git 폴더(설치 위치)'; 값 = $repo }
    [pscustomobject]@{ 항목 = '런타임 폴더'; 값 = "$rt (venv·app·frontend·config·logs·deploy.json)" }
    [pscustomobject]@{ 항목 = '대시보드'; 값 = $(if ($d.dashboard_root) { $d.dashboard_root } else { '(없음)' }) }
    [pscustomobject]@{ 항목 = 'Python'; 값 = "$($basePy.Exe) ($($basePy.Version))" }
    [pscustomobject]@{ 항목 = 'PostgreSQL'; 값 = "$($d.pg_host):$($d.pg_port)  DB $($d.db_name) / 역할 $($d.db_role)  (psql: $($d.pg_bin))" }
    [pscustomobject]@{ 항목 = 'ESL 루트'; 값 = "$($plan.esl_root)$(if ($plan.esl_root -and -not (Test-Path -LiteralPath $plan.esl_root)) { ' (만듦)' })" }
    [pscustomobject]@{ 항목 = '업로드 위치'; 값 = "$(if ($plan.upload_root) { $plan.upload_root } else { '(없음 — 업로드 끔)' })$(if ($plan.upload_root -and -not (Test-Path -LiteralPath $plan.upload_root)) { ' (만듦)' })  (입력 루트에 자동 포함)" }
    [pscustomobject]@{ 항목 = '입력 루트'; 값 = $(if (@($plan.input_roots).Count) { @($plan.input_roots) -join ', ' } else { '(없음 — 설정 파일에서 나중에 추가)' }) }
    [pscustomobject]@{ 항목 = 'SPDM 루트'; 값 = $(if (@($plan.spdm_roots).Count) { @($plan.spdm_roots) -join ', ' } else { '(없음)' }) }
    [pscustomobject]@{ 항목 = '설정 파일'; 값 = "$($plan.config_path) — $cfgState" }
    [pscustomobject]@{ 항목 = 'deploy.json'; 값 = "$deployPath — $(if (-not $plan.deploy_exists) { '새로 만듦' } elseif ($plan.deploy_changed) { "보충: $(@($plan.deploy_added) -join ', ')$(if (@($plan.deploy_overridden).Count) { " / 인자로 바꿈: $(@($plan.deploy_overridden) -join ', ')" })" } else { '변경 없음' })" }
    [pscustomobject]@{ 항목 = '작업 실행'; 값 = "$($d.service_user) / $($d.run_mode)  (ESL-Backend·ESL-Worker, 작업 폴더 $rt)" }
    [pscustomobject]@{ 항목 = '프런트 배치'; 값 = "$($d.caddy_frontend_root) (백엔드가 /esl/ 서빙 — 설정 server.frontend_root)" }
    [pscustomobject]@{ 항목 = '대시보드 .env'; 값 = (Format-EslDashboardEnvPlan $plan.dashboard_env) }
)
Write-Host ''
Write-Host ($rows | Format-Table -AutoSize -Wrap | Out-String -Width 240)
$detail = @($plan.config_rows | Where-Object { $_.action -notin @('유지', '예시 값') })
if ($detail.Count) {
    Write-Host '설정 파일 값(관리 대상 키):'
    Write-Host ($detail | Select-Object @{ n = '키'; e = { $_.key } }, @{ n = '처리'; e = { $_.action } }, @{ n = '값'; e = { if ("$($_.value)" -eq '') { '(빈 값)' } else { "$($_.value)" } } } | Format-Table -AutoSize -Wrap | Out-String -Width 240)
}
foreach ($w in @($plan.warnings)) { if ($w) { Write-Warning $w } }
if (-not $NonInteractive) {
    do { $ans = "$(Read-Host '이대로 설치할까요? (Y/N)')".Trim() } while ($ans -eq '')   # 빈 입력(붙여넣기 줄바꿈 등)은 다시 묻는다
    if ($ans -notmatch '^(?i:y|yes|예|ㅛ)$') { Write-Step '취소했습니다(설정 파일·DB·작업 스케줄러는 바꾸지 않았습니다)'; return }
}

# ---- ⑥ 기존 설치 갱신이면 대기열 확인 → 작업 중지(venv·app 교체 전에) ------------------------------------------
$tasksExist = [bool](Get-ScheduledTask -TaskName 'ESL-Backend' -ErrorAction SilentlyContinue)
if ($tasksExist) {
    if ($existingUrl -and (Test-Path -LiteralPath (Join-Path $d.pg_bin 'psql.exe'))) {
        Assert-EslNoActiveJobs -PgBin $d.pg_bin -DbUrl $existingUrl -Force:$Force
    }
    $n = Export-EslTasks -Dest (Join-Path $backupDir 'tasks')
    if ($n) { Write-Step "기존 작업 정의를 남겼습니다: $backupDir\tasks" }
    Stop-EslTasks
    Write-Step '기존 작업 중지'
}
if ($hasDeps) {
    Write-Step 'venv 의존성 갱신(deploy\requirements.lock)'
    Install-EslPackages -VenvPy $venvPy -LockFile $lock
}
Install-EslApp -Source $repo -Dest (Join-Path $rt 'app') -BackupDir $backupDir

# ---- 설정 작성(바뀌는 기존 파일은 먼저 _backup으로 복사) + ESL 루트 폴더 -----------------------------------------
$inputs['code_root'] = (Join-Path $rt 'app')
$result = Invoke-EslSetupConfig -VenvPy $venvPy -Action write -RuntimeDir $rt -Inputs $inputs
$d = $result.deploy
Write-EslConfigValidation -Result $result | Out-Null
$envResult = $result.write.dashboard_env

# ---- 프런트 → <런타임>\frontend: 소스가 바뀌었을 때만 Node 22로 빌드(결과를 변수에 받지 않는다 — npm 콘솔 그대로) ----------
Install-EslFrontendFromRepo -RepoRoot $repo -Dest $d.caddy_frontend_root -BackupDir $backupDir -StampFile (Join-Path $rt 'frontend-source.sha256') `
    -DepsStampFile (Join-Path $rt 'frontend-deps.sha256') -DashboardNode $(if ($dash) { "$($dash.NodeExe)" } else { '' })

# ---- ⑦ DB → 런타임 DB 접속 파일 → alembic → 작업 스케줄러 → 시작·health·환경 점검 -------------------------------------
$url = Initialize-EslDatabase -PgBin $d.pg_bin -PgHost $d.pg_host -PgPort ([int]$d.pg_port) -DbName $d.db_name -DbRole $d.db_role `
    -PasswordsFromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive -ReuseExisting -ExistingUrl $existingUrl
Write-EslRuntimeSecret -RuntimeDir $rt -DbUrl $url -ServiceUser $d.service_user
Remove-Variable -Name url, existingUrl -ErrorAction SilentlyContinue
Invoke-EslMigration -VenvPy $venvPy -RuntimeDir $rt -ConfigPath $d.config_path
Register-EslTasks -VenvPy $venvPy -WorkDir $rt -ServiceUser $d.service_user -RunMode $d.run_mode -RuntimeDir $rt -ConfigPath $d.config_path `
    -PasswordsFromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive
$ep = Get-EslEndpoint -ConfigPath $d.config_path -VenvPy $venvPy -Launcher (Get-EslLauncher $rt)
if ($NoStart) {
    Write-Step '-NoStart: 작업 시작·health 확인을 건너뜁니다(Start-ScheduledTask -TaskName ESL-Backend, ESL-Worker로 시작)'
} else {
    Start-EslTasksAndWait -HealthUrl $ep.Health -LogDir (Join-Path $rt 'logs') | Out-Null
    Invoke-EslCheck -VenvPy $venvPy -RuntimeDir $rt -ConfigPath $d.config_path | Out-Null
}

# ---- ⑧ 안내 -----------------------------------------------------------------------------------------
Write-Host ''
Write-Step '설치 완료. 남은 연결 작업:'
Write-EslConnectGuide -Port $ep.Port -BasePath $ep.BasePath -DashboardRoot "$($d.dashboard_root)" -FrontendRoot "$($d.caddy_frontend_root)" `
    -SnippetDir (Join-Path $PSScriptRoot 'caddy') -EnvResult $envResult
Write-Step '  3) 설정은 이 파일에서 고칩니다(입력 루트 storage.input_roots, 워커 메모리 worker.max_memory_gb):'
Write-Step "     $($d.config_path)"
Write-Step '     같은 폴더 esl.yaml 의 판정 기준(validation·compare)은 임시값, ista6.yaml 낙하 높이 표는 비어 있음 — 사내 기준으로 채우세요'
Write-Step '     고친 뒤: Stop-ScheduledTask ESL-Worker; Stop-ScheduledTask ESL-Backend; Start-ScheduledTask ESL-Backend; Start-ScheduledTask ESL-Worker'
if (-not @($inputRootsV).Count) { Write-Step "     입력 루트가 비어 있습니다 — 새 Case 입력은 브라우저 업로드(업로드 위치 $($d.upload_root))로 넣습니다(공유 폴더를 쓰려면 storage.input_roots 에 추가)" }
Write-Step "  4) 환경 점검: & '$venvPy' '$(Get-EslLauncher $rt)' check --runtime '$rt'   (로그: $(Join-Path $rt 'logs'))"
Write-Step "  5) 새 Case: ESL 화면 '내 PC에서 올리기'로 _0000.rad(include 포함)와 h3d 또는 추출 결과 폴더를 올립니다(업로드 위치 $($d.upload_root))"
Write-Step "이후 코드 업데이트(인자 없이, 설정 유지):  powershell -NoProfile -ExecutionPolicy Bypass -File $(Join-Path $PSScriptRoot 'update-repo.ps1')"
Write-Step "단계별 가이드: $(Join-Path (Split-Path $PSScriptRoot -Parent) 'docs\manual\install-quickstart.md')"
