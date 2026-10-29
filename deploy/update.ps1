<#
.SYNOPSIS
  ESL 업데이트(오프라인 묶음 — 폐쇄망 서버용. git 폴더 설치는 update-repo.ps1). 기존 venv·app·프런트를 _backup\<UTC>로 이동(삭제 없음)한 뒤 새 묶음 설치.
.DESCRIPTION
  physicsai-platform deploy\update.ps1과 같은 절차. 일반 PowerShell(관리자 권한 불필요).
  (저장소 루트의 update.bat은 사용자 PC용 HyperView TCL 배포 — 서버 업데이트는 이 deploy\update.bat·update.ps1)
  ① 실행 중 작업 확인(묻지 않고 DB 직접 조회) → 있으면 중단(-Force면 경고 후 진행)
  ② 작업 2개 중지 ③ 기존 venv·app·프런트를 <install_root>\_backup\<UTC>로 이동 ④ 새 wheel·app·프런트(묶음의 빌드본) 배치
     (v0.9.0 비드 DOE: OCP·gmsh·paicad wheel(deploy\paicad.lock 대조)도 — 실패해도 업데이트 계속, DOE만 비활성)
  ④' 작업 정의가 지금 설치와 다르면 다시 등록(Interactive만) — 새 코드 배치가 끝난 뒤에만
  ⑤ 설정 보충(기존 값 유지, 새로 생긴 관리 키만) ⑥ alembic upgrade head ⑦ 시작·health·환경 점검 ⑧ 실패 시 되돌리는 방법 안내(자동 되돌림 없음)
#>
[CmdletBinding()]
param(
    [string]$ConfigFile = '',   # 비우면 이 스크립트 폴더의 deploy.json (PS 5.1은 param 기본값에서 $PSScriptRoot가 빔)
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
if (-not $ConfigFile) { $ConfigFile = Join-Path $PSScriptRoot 'deploy.json' }
$EslTag = 'ESL 업데이트'
. (Join-Path $PSScriptRoot 'install-common.ps1')
function Write-Step([string]$m) { Write-EslStep $m }

if (-not (Test-Path $ConfigFile)) { throw "설치 매개변수 파일이 없습니다: $ConfigFile (기존 설치의 deploy.json을 이 폴더에 복사하세요)" }
$ConfigFile = [IO.Path]::GetFullPath($ConfigFile)
$cfg = Get-Content -Raw -Encoding UTF8 $ConfigFile | ConvertFrom-Json
$dash = $null
if ($cfg.dashboard_root) {
    # install.ps1과 같은 규칙: 비어 있는 pg_bin·pg_host·pg_port·python_exe만 대시보드 환경으로 채운다(dashboard-env.ps1)
    . (Join-Path $PSScriptRoot 'dashboard-env.ps1')
    $dash = Get-DashboardRuntimeDefaults -DashboardRoot $cfg.dashboard_root
    Merge-DashboardDefaults -Config $cfg -Defaults $dash | Out-Null
}
# 기존 설치를 옮기기 전에 python_exe가 실제로 Python 3.12로 실행되는지 확인(아니면 원인·다음 행동과 함께 여기서 중단 — 아무것도 바꾸지 않음)
. (Join-Path $PSScriptRoot 'python-select.ps1')
$basePy = Assert-EslPython312 -Exe "$($cfg.python_exe)"
Write-Step "Python $($basePy.Version): $($basePy.Exe)"
$root = "$($cfg.install_root)".TrimEnd('\')
$pkg = Split-Path -Parent $PSScriptRoot
$configPath = if ("$($cfg.config_path)") { "$($cfg.config_path)" } else { Join-Path $root 'config\esl_platform.yaml' }
$frontendRoot = if ("$($cfg.caddy_frontend_root)") { "$($cfg.caddy_frontend_root)" } else { Join-Path $root 'frontend' }
$venvPy = Join-Path $root 'venv\Scripts\python.exe'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backup = Join-Path $root "_backup\$stamp"
$dbUrl = Get-EslDbUrl -RuntimeDir $root
$runMode = if ("$($cfg.run_mode)" -eq 'Background') { 'Background' } else { 'Interactive' }

# ---- ① 실행 중 작업 확인(묻지 않고 DB 직접) ----------------------------------
Assert-EslNoActiveJobs -PgBin $cfg.pg_bin -DbUrl $dbUrl -Force:$Force

# ---- ② 중지 ------------------------------------------------
Stop-EslTasks
$taskReg = 'unchanged'   # 작업 등록 상태: unchanged | trying | done (실패 안내용)

# ---- ③ 기존 설치 백업 이동(삭제 없음) -------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $backup | Out-Null
foreach ($p in @('venv', 'app')) {
    $src = Join-Path $root $p
    if (Test-Path $src) { Move-Item -Path $src -Destination (Join-Path $backup $p) }
}
if (Test-Path $frontendRoot) { Move-Item -Path $frontendRoot -Destination (Join-Path $backup 'frontend') }
Write-Step "기존 venv·app·프런트를 이동했습니다: $backup"

try {
    # ---- ④ 새 설치 ---------------------------------------------------------------------------
    Invoke-EslNative 'venv 생성' $basePy.Exe @('-m', 'venv', (Join-Path $root 'venv'))
    Install-EslPackages -VenvPy $venvPy -LockFile (Join-Path $PSScriptRoot 'requirements.lock') -Wheels (Join-Path $pkg 'wheels')
    $doe = Install-EslBeadDoe -VenvPy $venvPy -LockFile (Join-Path $PSScriptRoot 'requirements.lock') -PaicadLock (Join-Path $PSScriptRoot 'paicad.lock') -Wheels (Join-Path $pkg 'wheels')
    Install-EslApp -Source (Join-Path $pkg 'app') -Dest (Join-Path $root 'app') -BackupDir $backup
    Publish-EslFrontend -Dist (Join-Path $pkg 'frontend') -Dest $frontendRoot -BackupDir $backup

    # ---- ④' 작업 정의 갱신 — 새 venv·app 배치가 끝난 뒤에만 ------------------------------------
    $taskReg = 'trying'
    $re = Update-EslTaskRegistration -VenvPy $venvPy -WorkDir $root -RuntimeDir $root -ConfigPath $configPath `
        -ServiceUser "$($cfg.service_user)" -RunMode $runMode
    $taskReg = if (@($re)[-1] -eq $true) { 'done' } else { 'unchanged' }

    # ---- ⑤ 설정 보충(기존 값 유지) -------------------------------------------------------------------
    $inputs = [ordered]@{ mode = 'bundle'; source_root = $pkg; code_root = (Join-Path $root 'app'); runtime_dir = $root; stamp = $stamp
        deploy_path = $ConfigFile; deploy_defaults = [ordered]@{ install_root = $root; config_path = $configPath }; deploy_explicit = [ordered]@{} }
    if ($dash -and $dash.WebBasePath) { $inputs['dashboard_web_base_path'] = "$($dash.WebBasePath)" }
    $result = Invoke-EslSetupConfig -VenvPy $venvPy -Action write -RuntimeDir $root -Inputs $inputs
    Write-EslConfigValidation -Result $result | Out-Null

    # ---- ⑥ migration(실행기가 런타임 DB 파일을 읽음) -----------------------------------
    Invoke-EslMigration -VenvPy $venvPy -RuntimeDir $root -ConfigPath $configPath

    # ---- ⑦ 시작·health·환경 점검 ------------------------------------------------
    $ep = Get-EslEndpoint -ConfigPath $configPath -VenvPy $venvPy -Launcher (Get-EslLauncher $root)
    Start-EslTasksAndWait -HealthUrl $ep.Health -LogDir (Join-Path $root 'logs') | Out-Null
    Invoke-EslCheck -VenvPy $venvPy -RuntimeDir $root -ConfigPath $configPath | Out-Null
    Write-Step "업데이트 완료 — health OK"
} catch {
    # ---- ⑧ 되돌리는 방법 안내(자동 되돌림 없음) ----------------------------------------------------
    Write-Warning "업데이트 실패: $($_.Exception.Message)"
    Write-Warning "되돌리기: 작업 2개를 중지하고, 새 venv·app·프런트 폴더를 다른 이름으로 옮긴 뒤"
    Write-Warning "  $backup 의 venv·app·frontend 를 원래 위치($root, $frontendRoot)로 이동하고 작업을 시작하세요"
    Write-Warning "  DB migration이 이미 올라갔다면 downgrade는 지원하지 않습니다 — 백업 DB 복원 절차를 따르세요"
    if ($taskReg -ne 'unchanged') {
        Write-Warning "  작업을 다시 등록했습니다(또는 등록 도중 실패) — 이전 venv로 되돌리면 이전 묶음의 install.ps1로 작업을 다시 등록하세요"
    } else {
        Write-Warning "  작업 등록(인자)은 바꾸지 않았습니다 — 이전 venv·app을 되돌리면 그대로 시작됩니다"
    }
    throw
}
