<#
.SYNOPSIS
  Python 3.12 선택·검증 공용 함수. setup.ps1·update-repo.ps1·install.ps1·update.ps1·collect-offline.ps1·demo\demo-python.ps1이 dot-source 한다.
.DESCRIPTION
  physicsai-platform deploy\python-select.ps1과 같은 규칙(함수 이름만 Esl).
  선택 순서: -PythonExe > 대시보드 고정 Python 3.12(dashboard-env.ps1) > `py -3.12` > PATH의 python·python3.
  각 후보는 실제로 실행해 sys.version_info[:2] == (3, 12)인지 확인하고, 실패하면(pyenv shim 미설정·Microsoft Store 별칭·다른 버전 등) 다음 후보로 간다.
  이 파일은 패키지를 설치하지 않는다(설치는 호출 쪽이 항상 별도 venv에).
#>

function Test-EslPython312 {
    <# 후보를 실제로 실행한다. Python 3.12면 실제 실행 파일 경로(sys.executable)·버전을, 아니면 $null을 돌려준다. 실패 이유는 -Reason 변수에. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Exe, [string[]]$PreArgs = @(), [ref]$Reason)
    # 실행 결과에서 찾을 표지. 코드에는 cmd 특수문자(| & < > ^ % ")를 쓰지 않는다(pyenv shim 등 .bat 경유)
    $marker = 'ESL_PY='
    $code = "import sys; print('$marker' + '.'.join(map(str, sys.version_info[:3])) + ' ' + sys.executable); sys.exit(0 if sys.version_info[:2] == (3, 12) else 3)"
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # Windows PowerShell 5.1: 자식의 stderr가 오류 레코드가 되어 중단되지 않게
    try {
        $out = @(& $Exe @PreArgs -c $code 2>&1 | ForEach-Object { "$_" })
        $rc = $LASTEXITCODE
    } catch {
        if ($Reason) { $Reason.Value = "실행 불가($($_.Exception.Message))" }
        return $null
    } finally { $ErrorActionPreference = $eap }
    $line = $out | Where-Object { $_.StartsWith($marker) } | Select-Object -Last 1
    if (-not $line) {
        $first = ($out | Where-Object { "$_".Trim() } | Select-Object -First 1)
        if ($Reason) { $Reason.Value = "실행 실패(종료코드 $rc$(if ($first) { ": $("$first".Trim())" }))" }
        return $null
    }
    $ver, $exePath = $line.Substring($marker.Length).Trim().Split([char[]]' ', 2)
    if ($rc -ne 0) {
        if ($Reason) { $Reason.Value = "Python $ver(3.12 아님)" }
        return $null
    }
    return [pscustomobject]@{ Exe = $exePath; Version = $ver }
}

function Get-EslPythonCandidates {
    <# 선택 순서대로 후보 목록(Label·Exe·PreArgs). 비어 있는 값은 건너뛴다. #>
    [CmdletBinding()]
    param([string]$PythonExe = '', [string]$DashboardPython = '')
    $c = New-Object System.Collections.Generic.List[object]
    if ($PythonExe) { $c.Add([pscustomobject]@{ Label = '-PythonExe'; Exe = $PythonExe; PreArgs = @() }) }
    if ($DashboardPython) { $c.Add([pscustomobject]@{ Label = '대시보드 Python 3.12'; Exe = $DashboardPython; PreArgs = @() }) }
    $pyLauncher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pyLauncher) { $c.Add([pscustomobject]@{ Label = 'py -3.12'; Exe = $pyLauncher.Source; PreArgs = @('-3.12') }) }
    foreach ($n in 'python', 'python3') {
        foreach ($g in @(Get-Command $n -CommandType Application -All -ErrorAction SilentlyContinue)) {
            if (-not ($c | Where-Object { $_.Exe -eq $g.Source })) { $c.Add([pscustomobject]@{ Label = "PATH $n"; Exe = $g.Source; PreArgs = @() }) }
        }
    }
    return , $c.ToArray()
}

function Select-EslPython {
    <# 후보를 차례로 실행해 첫 Python 3.12를 고른다. 고른 것을 1줄 출력. 없으면 원인·다음 행동을 담아 중단. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Candidates, [string]$Tag = 'ESL')
    $tried = @()
    foreach ($cand in $Candidates) {
        $why = ''
        $r = Test-EslPython312 -Exe $cand.Exe -PreArgs $cand.PreArgs -Reason ([ref]$why)
        if ($r) {
            Write-Host "[$Tag] Python 선택: $($cand.Label) → $($r.Exe) (Python $($r.Version))"
            return [pscustomobject]@{ Exe = $r.Exe; Version = $r.Version; Label = $cand.Label }
        }
        Write-Host "[$Tag] Python 후보 건너뜀: $($cand.Label) ($($cand.Exe)) — $why"
        $tried += "$($cand.Label)"
    }
    throw ("Python 3.12를 찾지 못했습니다(시도: $(if ($tried) { $tried -join ', ' } else { '후보 없음' })).`n" +
        "다음 행동: -DashboardRoot <대시보드 폴더>(.tools\python\cpython-3.12.*) 또는 -PythonExe <python.exe 경로>로 Python 3.12를 지정하세요.")
}

function Assert-EslPython312 {
    <#
      deploy.json python_exe(또는 dashboard_root로 채운 값)를 실제로 실행해 Python 3.12인지 확인한다(install.ps1·update.ps1).
      맞으면 실제 실행 파일(sys.executable)·버전을 돌려주고, 아니면 원인·다음 행동을 담아 중단한다.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Exe)
    $why = ''
    $r = $null
    if ($Exe) { $r = Test-EslPython312 -Exe $Exe -Reason ([ref]$why) } else { $why = '값 없음' }
    if ($r) { return $r }
    throw ("deploy.json python_exe가 Python 3.12로 실행되지 않습니다(대시보드와 같은 3.12.13 권장): $Exe — $why`n" +
        "다음 행동: python_exe를 실제 python.exe 경로(예 <대시보드>\.tools\python\cpython-3.12.13-windows-x86_64-none\python.exe)로 고치거나, " +
        "python_exe를 비우고 dashboard_root에 대시보드 폴더를 지정하세요(pyenv shim·Microsoft Store 별칭 WindowsApps\python.exe는 쓰지 마세요).")
}
