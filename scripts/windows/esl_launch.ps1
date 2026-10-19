# esl_launch.ps1 -- deploy_dir\current\ESL_probe.bat / ESL_extract.bat 가 부르는 런처 (update.ps1 이 current 에 복사)
#
# 버전과 무관한 얇은 런처: 실행할 때마다 ..\current_version.txt 에서 활성 버전을 읽어
# ..\versions\<버전>\esl_run.ps1 (같은 폴더의 TCL 사용)을 실행한다.
# 실행 중에 update 가 활성 버전을 바꿔도, 이미 시작한 작업은 자기 versions 폴더를 계속 쓴다.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('probe', 'extract')][string]$Mode,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Items = @()
)

$ErrorActionPreference = 'Stop'
$DeployDir = Split-Path -Parent $PSScriptRoot
$Pointer = Join-Path $DeployDir 'current_version.txt'

$version = ''
$lastErr = ''
for ($i = 0; $i -lt 3 -and -not $version; $i++) {
    try {
        if (Test-Path -LiteralPath $Pointer -PathType Leaf) { $version = ([IO.File]::ReadAllText($Pointer)).Trim() }
        else { $lastErr = '파일 없음' }
    }
    catch { $lastErr = $_.Exception.Message }
    if (-not $version) { Start-Sleep -Milliseconds 300 }
}
if ($version -cnotmatch '^[0-9a-f]{7,40}(?:-[0-9]{1,2})?$') {
    Write-Host "[오류] 활성 버전을 읽지 못했습니다: $Pointer ($lastErr '$version')  -> 저장소 폴더의 update.bat 을 다시 실행하세요." -ForegroundColor Red
    exit 1
}
$runner = Join-Path (Join-Path (Join-Path $DeployDir 'versions') $version) 'esl_run.ps1'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    Write-Host "[오류] 실행기가 없습니다: $runner  -> 저장소 폴더의 update.bat 을 다시 실행하세요." -ForegroundColor Red
    exit 1
}
Write-Host "ESL 버전 $version ($runner)" -ForegroundColor DarkGray
& $runner -Mode $Mode @Items
exit $LASTEXITCODE
