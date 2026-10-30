<#
.SYNOPSIS
  ESL git 폴더 설치(setup.ps1)의 업데이트. 이 스크립트 한 줄(인자·질문 없음, git pull 포함)로 반영한다.
.DESCRIPTION
  physicsai-platform deploy\update-repo.ps1과 같은 절차. 일반 Windows PowerShell(관리자 권한 불필요)에서, 어느 폴더에서든:
    <git 폴더>\deploy\update-repo.ps1
    (실행 정책 오류 — "스크립트를 실행할 수 없습니다" — 가 나면: powershell -NoProfile -ExecutionPolicy Bypass -File <git 폴더>\deploy\update-repo.ps1)
  (저장소 루트의 update.bat은 사용자 PC용 HyperView TCL 배포 — 서버 업데이트는 이 스크립트)
  모든 값은 <git>\.runtime\deploy.json(setup.ps1이 만든 것)에서 읽고, 아무것도 묻지 않는다.
  ⓪ git pull --ff-only(자격 증명을 묻지 않음 — GIT_TERMINAL_PROMPT=0·credential.interactive=never). 추적 파일에 로컬 변경이 있으면 안내 후 중단
     (바꾼 것 없음). 분리된 HEAD(특정 커밋 고정 — 되돌리기)면 pull 없이 그 커밋으로 반영. 새 커밋을 받았으면 새 update-repo.ps1로 다시 실행(-SkipPull).
     실행 중인 서비스는 <런타임>\app 복사본을 쓰므로 git pull이 실행 중 코드를 바꾸지 않는다.
  ① 대기·실행 중 작업 확인(DB 직접 조회) → 있으면 안내 후 중단(-Force면 진행)
  ② 작업 2개 중지 ③ venv 의존성 갱신(deploy\requirements.lock, 비드 DOE OCP·gmsh·paicad 는 따로 — paicad = 저장소 동봉 deploy\wheels 우선(v0.10.1),
     없을 때만 deploy.json paicad_wheels·physicsai_root,
     실패해도 업데이트 계속·DOE만 비활성) ④ 코드 스냅샷 <런타임>\app(이전 것은 _backup)
  ⑤ 설정 보충(setup_config.py: 기존 값 유지, 새로 생긴 관리 키만 — 바뀌면 먼저 _backup 복사. server.frontend_root가 없으면 .runtime\frontend,
     대시보드 .env VITE_ESL_TARGET·SIMDASH_ESL_ENABLED는 없을 때만 추가 — 추가했으면 대시보드 재시작 안내)
  ⑥ 프런트: 소스가 바뀌었을 때만 Node 22로 빌드 → <런타임>\frontend(이전 것은 _backup)
  ⑥' 작업 정의가 지금 설치와 다르면 다시 등록(Interactive만) — 새 코드 배치가 끝난 뒤에만
  ⑦ alembic upgrade head ⑧ 작업 시작·health·환경 점검. 끝 줄은 "업데이트 성공 — 접속: …" 또는 "업데이트 실패 — 접속: …".
  ⑦ 전에 실패하면 이전 app·프런트를 되돌리고 작업 2개를 다시 시작한다(서비스를 멈춘 채 두지 않음). ⑦ 이후 실패는 되돌리는 방법을 안내.
.PARAMETER Force
  대기·실행 중 작업이 있어도 진행(실행 중 작업은 lease 만료 후 INTERRUPTED)
.PARAMETER NonInteractive
  호환용(이 스크립트는 묻는 것이 없다)
.PARAMETER NoStart
  작업 시작·health 확인을 하지 않는다
.PARAMETER SkipPull
  git pull 없이 현재 커밋을 반영한다(새 커밋을 받은 뒤 스스로 다시 실행할 때 쓰는 값)
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NonInteractive,
    [switch]$NoStart,
    [switch]$SkipPull
)
$ErrorActionPreference = 'Stop'
$EslTag = 'ESL 업데이트'
. (Join-Path $PSScriptRoot 'install-common.ps1')
. (Join-Path $PSScriptRoot 'python-select.ps1')
. (Join-Path $PSScriptRoot 'node-select.ps1')
. (Join-Path $PSScriptRoot 'dashboard-env.ps1')
function Write-Step([string]$m) { Write-EslStep $m }

$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$rt = Join-Path $repo '.runtime'
$deployPath = Join-Path $rt 'deploy.json'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backupDir = Join-Path $rt "_backup\$stamp"
$accessUrl = Get-EslAccessUrl -Dash $null
$cfg = $null
$stopped = $false
$migrationStarted = $false
$stage = '준비'

function Invoke-UpdateGit {
    <#
      git 실행. safe.directory는 이 저장소 경로만·이 실행에만. 자격 증명을 묻지 않는다(GIT_TERMINAL_PROMPT=0, GCM_INTERACTIVE=never,
      credential.interactive=never) — 인증이 필요하면 기다리지 않고 실패한다(저장된 자격 증명은 그대로 쓰임). 출력·종료코드.
    #>
    param([Parameter(Mandatory = $true)][string[]]$GitArgs, [switch]$Console)
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $saved = @{}
    foreach ($k in 'GIT_TERMINAL_PROMPT', 'GCM_INTERACTIVE') { $saved[$k] = [Environment]::GetEnvironmentVariable($k, 'Process') }
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'never'
    $safe = $repo -replace '\\', '/'
    $pre = @('-c', "safe.directory=$safe", '-c', 'credential.interactive=never', '-C', $repo)
    try {
        if ($Console) {
            & $script:gitExe @pre @GitArgs | Out-Host
            return [pscustomobject]@{ Rc = $LASTEXITCODE; Out = '' }
        }
        $o = @(& $script:gitExe @pre @GitArgs 2>&1 | ForEach-Object { "$_" })
        return [pscustomobject]@{ Rc = $LASTEXITCODE; Out = ($o -join "`n").Trim() }
    } finally {
        $ErrorActionPreference = $eap
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], 'Process') }
    }
}

function Sync-UpdateRepo {
    <# ⓪ git pull --ff-only. 새 커밋을 받았으면 $true(호출 쪽이 새 스크립트로 다시 실행). 로컬 변경·pull 실패는 던진다(바꾼 것 없음). #>
    $script:gitExe = (Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    if (-not $script:gitExe) { Write-Step 'git이 없어 git pull을 건너뜁니다(현재 파일로 반영)'; return $false }
    $top = Invoke-UpdateGit @('rev-parse', '--show-toplevel')
    if ($top.Rc -ne 0 -or -not $top.Out -or ([IO.Path]::GetFullPath($top.Out).TrimEnd('\', '/') -ine $repo)) {
        Write-Step "git 저장소가 아니어서 git pull을 건너뜁니다: $repo"
        return $false
    }
    $before = (Invoke-UpdateGit @('rev-parse', 'HEAD')).Out
    $head = (Invoke-UpdateGit @('log', '-1', '--format=%h %s')).Out
    Write-Step "git 폴더: $repo — 현재 커밋 $head"
    if ($SkipPull) { Write-Step 'git pull 건너뜀(-SkipPull)'; return $false }
    $dirty = Invoke-UpdateGit @('status', '--porcelain', '--untracked-files=no')
    if ($dirty.Rc -ne 0) { throw "git status 실패: $($dirty.Out)" }
    if ($dirty.Out) {
        throw ("git 폴더에 로컬 변경이 있어 업데이트(git pull)를 하지 않았습니다:`n$($dirty.Out)`n" +
            "다음 행동: 변경을 되돌리거나(git -C `"$repo`" checkout -- <파일>) 따로 보관한 뒤 다시 실행하세요. 설정은 .runtime\config\esl_platform.yaml에서 고칩니다(git 밖).")
    }
    if ((Invoke-UpdateGit @('symbolic-ref', '-q', 'HEAD')).Rc -ne 0) {
        Write-Step '분리된 HEAD(특정 커밋 고정 — 되돌리기 상태)라 git pull을 건너뜁니다(이 커밋으로 반영). 최신으로 가려면: git checkout <브랜치>'
        return $false
    }
    if ((Invoke-UpdateGit @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')).Rc -ne 0) {
        Write-Step '현재 브랜치에 추적(upstream) 브랜치가 없어 git pull을 건너뜁니다(이 커밋으로 반영). 설정: git branch --set-upstream-to=origin/<브랜치>'
        return $false
    }
    Write-Step 'git pull --ff-only'
    $pull = Invoke-UpdateGit @('pull', '--ff-only') -Console
    if ($pull.Rc -ne 0) {
        throw ("git pull --ff-only 실패(종료코드 $($pull.Rc)) — 위 git 출력을 확인하세요(자격 증명은 묻지 않습니다 — 인증이 필요하면 바로 실패).`n" +
            "다음 행동: 네트워크를 확인하거나, 자격 증명이 필요하면 이 창에서 git -C `"$repo`" pull 을 한 번 직접 실행해 저장한 뒤 다시 실행하세요. " +
            "받은 커밋 그대로 반영하려면 -SkipPull을 붙여 다시 실행하세요.")
    }
    $after = (Invoke-UpdateGit @('rev-parse', 'HEAD')).Out
    if ($after -eq $before) { Write-Step 'git: 이미 최신'; return $false }
    Write-Step "git: $($before.Substring(0, [Math]::Min(7, $before.Length))) → $((Invoke-UpdateGit @('log', '-1', '--format=%h %s')).Out)"
    return $true
}

try {
    if (-not (Test-Path -LiteralPath $deployPath)) {
        throw "git 폴더 설치 정보가 없습니다: $deployPath — 먼저 설치하세요: $(Join-Path $PSScriptRoot 'setup.ps1')`n(실행 정책 오류가 나면: powershell -NoProfile -ExecutionPolicy Bypass -File $(Join-Path $PSScriptRoot 'setup.ps1'))"
    }
    $cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $deployPath | ConvertFrom-Json
    $dash = $null
    if ($cfg.dashboard_root -and (Test-Path -LiteralPath $cfg.dashboard_root)) { $dash = Get-DashboardRuntimeDefaults -DashboardRoot $cfg.dashboard_root }
    $accessUrl = Get-EslAccessUrl -Dash $dash

    # ---- ⓪ git pull — 새 커밋이면 새 스크립트로 다시 실행(콘솔 그대로 물려줌) ----------------------
    $stage = 'git pull'
    if (Sync-UpdateRepo) {
        $hostExe = (Get-Process -Id $PID).Path
        Write-Step '받은 새 버전의 update-repo.ps1로 이어서 실행합니다'
        $relaunch = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-SkipPull')
        if ($Force) { $relaunch += '-Force' }
        if ($NoStart) { $relaunch += '-NoStart' }
        $ErrorActionPreference = 'Continue'
        & $hostExe @relaunch
        exit $LASTEXITCODE
    }
    $stage = '준비'
    $venvPy = Join-Path $rt 'venv\Scripts\python.exe'
    $dbUrl = Get-EslDbUrl -RuntimeDir $rt

    # venv가 Python 3.12로 실행되지 않으면(대시보드 Python 교체 등) 옮기고 새로 만든다 — 아무것도 바꾸기 전에 Python부터 확인
    $why = ''
    $venvOk = (Test-Path -LiteralPath $venvPy) -and (Test-EslPython312 -Exe $venvPy -Reason ([ref]$why))
    $basePy = $null
    if (-not $venvOk) {
        $cands = Get-EslPythonCandidates -PythonExe "$($cfg.python_exe)" -DashboardPython $(if ($dash) { "$($dash.PythonExe)" } else { '' })
        $basePy = Select-EslPython -Candidates $cands -Tag $EslTag
    }

    # ---- ① 실행 중 작업 확인(묻지 않고 DB 직접) · ② 중지 ---------------------------------------
    Assert-EslNoActiveJobs -PgBin $cfg.pg_bin -DbUrl $dbUrl -Force:$Force
    Stop-EslTasks
    $stopped = $true
    Write-Step '작업 2개 중지'

    # ---- ③ venv 의존성 갱신 -------------------------------------------------------------------
    $stage = 'venv 의존성 갱신'
    if (-not $venvOk) {
        if (Test-Path -LiteralPath (Join-Path $rt 'venv')) {
            New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
            Move-Item -LiteralPath (Join-Path $rt 'venv') -Destination (Join-Path $backupDir 'venv')
            Write-Step "기존 venv가 Python 3.12로 실행되지 않아($why) 옮겼습니다: $backupDir\venv"
        }
        Invoke-EslNative 'venv 생성' $basePy.Exe @('-m', 'venv', (Join-Path $rt 'venv'))
    }
    Install-EslPackages -VenvPy $venvPy -LockFile (Join-Path $repo 'deploy\requirements.lock')
    $doe = Install-EslBeadDoe -VenvPy $venvPy -LockFile (Join-Path $repo 'deploy\requirements.lock') -PaicadLock (Join-Path $repo 'deploy\paicad.lock') `
        -PaicadWheels "$($cfg.paicad_wheels)" -PhysicsaiRepo "$($cfg.physicsai_root)" -WorkDir (Join-Path $rt 'paicad-wheel') `
        -VendoredWheels (Join-Path $repo 'deploy\wheels')

    # ---- ④ 코드 스냅샷 ---------------------------------------------------------------------------------
    $stage = '코드 배치'
    Install-EslApp -Source $repo -Dest (Join-Path $rt 'app') -BackupDir $backupDir

    # ---- ⑤ 설정 보충(기존 값 유지) -------------------------------------------------------------------
    $stage = '설정 보충'
    $inputs = [ordered]@{ mode = 'repo'; source_root = $repo; code_root = (Join-Path $rt 'app'); runtime_dir = $rt; stamp = $stamp
        deploy_path = $deployPath; deploy_defaults = [ordered]@{}; deploy_explicit = [ordered]@{} }
    if ($dash -and $dash.WebBasePath) { $inputs['dashboard_web_base_path'] = "$($dash.WebBasePath)" }
    $result = Invoke-EslSetupConfig -VenvPy $venvPy -Action write -RuntimeDir $rt -Inputs $inputs
    Write-EslConfigValidation -Result $result | Out-Null
    if ($result.upload_root) {
        Write-Step "업로드 위치(storage.upload_root, 입력 루트에 자동 포함): $($result.upload_root)$(if (@($result.write.created) -contains $result.upload_root) { ' — 새로 만듦' })"
    }
    $envAdded = @($result.write.dashboard_env.added | Where-Object { $_ })
    if ($envAdded.Count) {
        Write-Step "대시보드 .env에 $($envAdded -join ', ') 추가(이전 사본: $($result.write.dashboard_env.backup)) — 대시보드를 다시 시작해야 /esl/ 연결이 반영됩니다"
    }

    # ---- ⑥ 프런트: 소스가 바뀌었을 때만 Node 22로 빌드(결과를 변수에 받지 않는다) -----------------------
    $stage = '프런트 배치'
    Install-EslFrontendFromRepo -RepoRoot $repo -Dest $cfg.caddy_frontend_root -BackupDir $backupDir -StampFile (Join-Path $rt 'frontend-source.sha256') `
        -DepsStampFile (Join-Path $rt 'frontend-deps.sha256') -DashboardNode $(if ($dash) { "$($dash.NodeExe)" } else { '' })

    # ---- ⑥' 작업 정의 갱신 — 새 코드가 배치된 뒤에만 -------------------------------------------------
    $stage = '작업 등록'
    $runMode = if ("$($cfg.run_mode)" -eq 'Background') { 'Background' } else { 'Interactive' }
    Update-EslTaskRegistration -VenvPy $venvPy -WorkDir $rt -RuntimeDir $rt -ConfigPath $cfg.config_path `
        -ServiceUser "$($cfg.service_user)" -RunMode $runMode | Out-Null

    # ---- ⑦ migration(실행기가 런타임 DB 파일을 읽음) ------------------------------------------
    $stage = 'migration'
    $migrationStarted = $true
    if (-not $dbUrl) { throw "DB 접속 정보가 없습니다: $(Get-EslRuntimeSecretPath $rt) — setup.ps1을 다시 실행하세요" }
    Invoke-EslMigration -VenvPy $venvPy -RuntimeDir $rt -ConfigPath $cfg.config_path

    # ---- ⑧ 시작·health·환경 점검 ------------------------------------------------------------------------
    $stage = '작업 시작'
    $ep = Get-EslEndpoint -ConfigPath $cfg.config_path -VenvPy $venvPy -Launcher (Get-EslLauncher $rt)
    $accessUrl = Get-EslAccessUrl -Dash $dash -BasePath $ep.BasePath
    if ($NoStart) {
        Write-Step '-NoStart: 작업 시작·health 확인을 건너뜁니다(Start-ScheduledTask -TaskName ESL-Backend, ESL-Worker로 시작)'
    } else {
        Start-EslTasksAndWait -HealthUrl $ep.Health -LogDir (Join-Path $rt 'logs') | Out-Null
        Invoke-EslCheck -VenvPy $venvPy -RuntimeDir $rt -ConfigPath $cfg.config_path | Out-Null
    }
} catch {
    $msg = $_.Exception.Message
    Write-Host ''
    if (-not $stopped) {
        Write-Step "업데이트하지 않았습니다(바꾼 것 없음): $msg"
    } elseif (-not $migrationStarted) {
        Write-Step "업데이트 실패($stage): $msg"
        Restore-EslAfterFailedUpdate -BackupDir $backupDir -AppDest (Join-Path $rt 'app') -FrontendDest "$($cfg.caddy_frontend_root)" -NoStart:$NoStart
        Write-Step "이전 상태로 계속 쓸 수 있습니다 — 접속: $accessUrl"
    } else {
        Write-Step "업데이트 실패($stage): $msg"
        Write-Step "되돌리기: git checkout <이전 커밋> 뒤 이 스크립트를 다시 실행(이전 app·프런트·venv: $backupDir). DB migration은 되돌리지 않습니다 — 필요하면 백업 DB 복원"
    }
    Write-Step "업데이트 실패 — 접속: $accessUrl"
    exit 1
}
Write-Host ''
Write-Step "업데이트 성공 — 접속: $accessUrl"
