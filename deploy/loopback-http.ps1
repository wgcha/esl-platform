<#
.SYNOPSIS
  루프백(127.0.0.1·localhost·::1) HTTP 호출 공용 함수 — 프록시를 타지 않는다(physicsai GitHub #1과 같은 처리, 회사 PC HTTP_PROXY·시스템 프록시).
.DESCRIPTION
  install-common.ps1(install.ps1·update.ps1·setup.ps1·update-repo.ps1)이 dot-source 한다(physicsai-platform deploy\loopback-http.ps1과 같은 코드). Windows PowerShell 5.1과 PowerShell 7 모두 동작.
  PS 7(HttpClient): HTTP_PROXY·HTTPS_PROXY 환경변수와 시스템 프록시를 쓰므로 -NoProxy로 끈다.
  PS 5.1(HttpWebRequest): [System.Net.WebRequest]::DefaultWebProxy(시스템 프록시)를 호출 동안만 빈 WebProxy(직접 연결)로 바꾼다.
  루프백이 아닌 주소는 받지 않는다(외부 호출은 기존 프록시 설정을 그대로 써야 하므로).
#>

function Test-LoopbackUri([string]$Uri) {
    $h = ([Uri]$Uri).Host.Trim('[', ']').ToLowerInvariant()
    if ($h -eq 'localhost') { return $true }
    $ip = $null
    if ([System.Net.IPAddress]::TryParse($h, [ref]$ip)) { return [System.Net.IPAddress]::IsLoopback($ip) }
    return $false
}

function Invoke-LoopbackRest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [string]$Method = 'Get',
        [hashtable]$Headers = @{},
        [int]$TimeoutSec = 10
    )
    if (-not (Test-LoopbackUri $Uri)) { throw "Invoke-LoopbackRest는 루프백 주소만 받습니다: $Uri" }
    $p = @{ Uri = $Uri; Method = $Method; Headers = $Headers; TimeoutSec = $TimeoutSec }
    if ($PSVersionTable.PSVersion.Major -ge 6) {
        return Invoke-RestMethod @p -NoProxy
    }
    $old = [System.Net.WebRequest]::DefaultWebProxy
    try {
        [System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy   # 주소 없는 WebProxy = 직접 연결
        return Invoke-RestMethod @p
    } finally {
        [System.Net.WebRequest]::DefaultWebProxy = $old
    }
}
