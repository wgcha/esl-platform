<#
.SYNOPSIS
  ESL 서버(백엔드·워커) 시작·멈춤·재시작. 작업 스케줄러 작업 ESL-Backend·ESL-Worker를 다룬다(관리자 권한 불필요 — update-repo.ps1과 같음).
.DESCRIPTION
  더블클릭용 esl-start.bat·esl-stop.bat·esl-restart.bat이 이 스크립트를 -Action 으로 부른다. 작업 이름·health 주소·로그 위치는
  <저장소>\.runtime\deploy.json 과 설정 파일(server.port·base_path)에서 읽는다(install-common.ps1 재사용, 값을 여기 적지 않음).
  start/restart: 시작 뒤 health 확인까지 기다려 "성공/실패 + 로그 위치"를 출력. stop/restart: 대기·실행 중 계산 작업이 있으면 경고하고 Y/N을 묻는다
  (작업 수를 DB에서 읽을 수 없으면 경고 문구만 보이고 묻는다). 이 질문 없이 진행하려면 -Force.
.PARAMETER Action
  start | stop | restart
.PARAMETER Only
  backend | worker — 한쪽 작업만. 생략하면 둘 다.
.PARAMETER Force
  실행 중 작업 경고에 묻지 않고 진행
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('start', 'stop', 'restart')][string]$Action,
    [ValidateSet('backend', 'worker')][string]$Only = '',
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$EslTag = 'ESL 서버'
. (Join-Path $PSScriptRoot 'install-common.ps1')

$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$rt = Join-Path $repo '.runtime'
$deployPath = Join-Path $rt 'deploy.json'
$logDir = Join-Path $rt 'logs'
$ep = $null

try {
    if (-not (Test-Path -LiteralPath $deployPath)) {
        throw "설치 정보가 없습니다: $deployPath — 먼저 설치하세요: $(Join-Path $PSScriptRoot 'setup.ps1')"
    }
    $cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $deployPath | ConvertFrom-Json
    $names = switch ($Only) { 'backend' { @($EslTaskNames[0]) } 'worker' { @($EslTaskNames[1]) } default { @($EslTaskNames) } }
    $venvPy = Join-Path $rt 'venv\Scripts\python.exe'
    $ep = Get-EslEndpoint -ConfigPath $cfg.config_path -VenvPy $venvPy -Launcher (Get-EslLauncher $rt)

    if (($Action -eq 'stop' -or $Action -eq 'restart') -and ($names -contains $EslTaskNames[1])) {
        $active = $null
        try { $active = Get-EslActiveJobCount -PgBin $cfg.pg_bin -DbUrl (Get-EslDbUrl -RuntimeDir $rt) }
        catch { Write-Verbose "작업 수 확인 실패: $($_.Exception.Message)" }
        if ($null -eq $active) { Write-Warning '진행 중인 계산 작업 수를 확인하지 못했습니다 — 워커를 멈추면 실행 중 작업은 lease 만료 뒤 INTERRUPTED가 됩니다' }
        elseif ($active -gt 0) { Write-Warning "대기·실행 중 계산 작업이 $active 건 있습니다 — 워커를 멈추면 실행 중 작업은 lease 만료 뒤 INTERRUPTED가 됩니다" }
        if (-not $Force -and ($null -eq $active -or $active -gt 0)) {
            $a = Read-Host '계속할까요? (Y/N)'
            if ($a -notmatch '^[Yy]') { Write-Host '취소했습니다 — 아무것도 바꾸지 않았습니다'; exit 0 }
        }
    }
    if ($Action -eq 'stop' -or $Action -eq 'restart') {
        Stop-EslTasks -Names $names
        Write-EslStep ('중지: ' + ($names -join ', '))
    }
    if ($Action -eq 'start' -or $Action -eq 'restart') {
        Start-EslTasksAndWait -HealthUrl $ep.Health -LogDir $logDir -Names $names | Out-Null
        Write-EslStep ('시작: ' + ($names -join ', '))
    }
} catch {
    Write-Host ''
    Write-EslStep "ESL $Action 실패: $($_.Exception.Message)"
    Write-EslStep "로그 위치: $logDir"
    exit 1
}
Write-Host ''
Write-EslStep "ESL $Action 성공 — 접속: $($ep.Health -replace '/api/health$', '/')  (로그: $logDir)"
