<#
.SYNOPSIS
  시연 Python 선택·시연 venv 준비. deploy\demo\start-demo.ps1이 dot-source 한다(저장소·오프라인 묶음 공통).
.DESCRIPTION
  Python 선택(deploy\python-select.ps1 공용) 순서: -PythonExe > 대시보드 고정 Python 3.12(dashboard-env) > `py -3.12` > PATH의 python.
  패키지는 대시보드 런타임이나 시스템 Python에 설치하지 않는다 — 항상 <시연 폴더>\venv에 deploy\requirements.lock을 설치한다
  (묶음: --no-index --find-links wheels, 저장소: 인덱스 — 기록 해시가 같으면 건너뜀). 플랫폼 코드는 설치하지 않는다(실행기가 sys.path로 찾음).
#>

. (Join-Path (Split-Path -Parent $PSScriptRoot) 'python-select.ps1')

function Get-DemoDepsStamp {
    <# 의존성 기록값: requirements.lock 내용 해시(바뀌면 다시 설치). #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$LockFile)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($LockFile))) -replace '-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Invoke-DemoPip {
    <# venv의 pip 실행. 실패하면 인덱스 접근 문제인지 판단해 한국어로 중단한다. 기존 pip 설정(PIP_INDEX_URL 등)은 그대로 쓴다. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Py, [Parameter(Mandatory = $true)][string[]]$PipArgs, [Parameter(Mandatory = $true)][string]$What)
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = @(& $Py -m pip @PipArgs --progress-bar off --disable-pip-version-check 2>&1 | ForEach-Object { $s = "$_"; Write-Host $s; $s })
        $rc = $LASTEXITCODE
    } finally { $ErrorActionPreference = $eap }
    if ($rc -eq 0) { return }
    $text = $out -join "`n"
    if ($text -match '(?i)NewConnectionError|ConnectTimeout|ConnectionError|ProxyError|Max retries exceeded|Temporary failure in name resolution|getaddrinfo failed|No matching distribution found|Could not find a version that satisfies|SSLError|CERTIFICATE_VERIFY_FAILED|403 Client Error|407') {
        throw ("$What 실패: 패키지 인덱스(PyPI 또는 PIP_INDEX_URL)에 접근할 수 없습니다.`n" +
            "다음 행동: 인터넷이 안 되는 PC면 오프라인 묶음(deploy\collect-offline.ps1로 만든 zip)을 풀어 그 안의 deploy\demo\start-demo.bat로 실행하세요(사내 프록시면 pip 설정 PIP_INDEX_URL·HTTPS_PROXY 확인).")
    }
    throw ("$What 실패(pip 종료코드 $rc).`n다음 행동: 위 pip 출력을 확인하세요.")
}

function Initialize-DemoVenv {
    <# <시연 폴더>\venv를 준비하고 그 python.exe 경로를 돌려준다. -Wheels가 있으면 오프라인 설치. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$DemoRoot, [Parameter(Mandatory = $true)][object[]]$Candidates,
          [Parameter(Mandatory = $true)][string]$LockFile, [string]$Wheels = '')
    $venv = Join-Path $DemoRoot 'venv'
    $py = Join-Path $venv 'Scripts\python.exe'
    if (Test-Path -LiteralPath $py) {
        $why = ''
        $r = Test-EslPython312 -Exe $py -Reason ([ref]$why)
        if (-not $r) {
            throw ("기존 시연 venv가 Python 3.12가 아니거나 실행되지 않습니다: $venv ($why).`n" +
                "다음 행동: 그 venv 폴더 이름을 바꾼(예 venv_old) 뒤 다시 실행하세요(새 venv를 만듭니다).")
        }
        Write-Host "[ESL 시연] Python: 기존 시연 venv 사용 → $py (Python $($r.Version))"
    } else {
        $base = Select-EslPython -Candidates $Candidates -Tag 'ESL 시연'
        Write-Host "[ESL 시연] 시연용 venv 생성: $venv"
        $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { & $base.Exe -m venv $venv 2>&1 | ForEach-Object { Write-Host "$_" }; $rc = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
        if ($rc -ne 0 -or -not (Test-Path -LiteralPath $py)) {
            throw ("venv 생성 실패(종료코드 $rc): $venv`n다음 행동: 시연 폴더 쓰기 권한과 Python($($base.Exe))의 venv 모듈을 확인하거나 -PythonExe로 다른 Python 3.12를 지정하세요.")
        }
    }
    $stampFile = Join-Path $venv 'esl-deps.sha256'
    $want = Get-DemoDepsStamp -LockFile $LockFile
    $have = if (Test-Path -LiteralPath $stampFile) { ([IO.File]::ReadAllText($stampFile)).Trim() } else { '' }
    if ($have -eq $want) {
        Write-Host '[ESL 시연] 시연 venv 의존성: 설치되어 있음(requirements.lock 변경 없음 — 건너뜀)'
    } else {
        Write-Host '[ESL 시연] 시연 venv에 의존성 설치: deploy\requirements.lock (처음 한 번, 몇 분 걸림)'
        $a = @('install', '-r', $LockFile)
        if ($Wheels) { $a = @('install', '--no-index', '--find-links', $Wheels, '-r', $LockFile) }
        Invoke-DemoPip -Py $py -PipArgs $a -What '의존성(deploy\requirements.lock) 설치'
        [IO.File]::WriteAllText($stampFile, $want)
    }
    return $py
}
