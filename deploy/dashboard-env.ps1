<#
.SYNOPSIS
  대시보드(simulation_workbench) 실행 환경 재사용: deploy.json의 dashboard_root(선택)로 PostgreSQL bin·host·port와
  Python 3.12 실행 파일 기본값을 찾는다. setup.ps1·update-repo.ps1·install.ps1·update.ps1·collect-offline.ps1·demo\start-demo.ps1이
  dot-source 한다(physicsai-platform deploy\dashboard-env.ps1과 같은 코드 — 같은 대시보드 .env·.tools를 같은 규칙으로 읽는다).
.DESCRIPTION
  읽는 것(대시보드 <dashboard_root>\.env): POSTGRES_BIN 값, DATABASE_URL의 host·port만, WINDOWS_WEB_BASE_PATH(대시보드 웹 경로 —
  setup_config.py가 auth.dashboard_public_login_url에 씀), WINDOWS_WEB_PORT(설치·업데이트 끝 접속 주소).
  DATABASE_URL의 사용자명·비밀번호는 정규식에서 캡처하지 않고, 원문 줄은 파싱 직후 변수에서 지운다(출력·로그 없음).
  Python 후보: <dashboard_root>\.tools\python\cpython-3.12.*-windows-x86_64-none\python.exe (대시보드 setup.ps1 고정 런타임).
  Node 후보: <dashboard_root>\.tools\node-v22.*-win-x64\node.exe (대시보드 고정 Node 22 — 프런트 빌드용).
  deploy.json·매개변수의 명시 값이 항상 우선이다(여기 값은 비어 있을 때만 쓰는 기본값).
#>

function Get-DashboardRuntimeDefaults {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$DashboardRoot)
    if (-not (Test-Path -LiteralPath $DashboardRoot -PathType Container)) { throw "dashboard_root 폴더가 없습니다: $DashboardRoot" }
    $r = [ordered]@{ PgBin = $null; PgHost = $null; PgPort = $null; PythonExe = $null; NodeExe = $null; EnvFile = $null; WebBasePath = $null; WebPort = $null }
    $envFile = Join-Path $DashboardRoot '.env'
    if (Test-Path -LiteralPath $envFile -PathType Leaf) {
        $r.EnvFile = $envFile
        foreach ($line in [IO.File]::ReadAllLines($envFile)) {
            $m = [regex]::Match($line, '^\s*(?:export\s+)?(POSTGRES_BIN|DATABASE_URL|WINDOWS_WEB_BASE_PATH|WINDOWS_WEB_PORT)\s*=\s*(.*?)\s*$')
            if (-not $m.Success) { continue }
            $val = $m.Groups[2].Value
            if ($val.Length -ge 2 -and ($val[0] -eq '"' -or $val[0] -eq "'") -and $val[-1] -eq $val[0]) { $val = $val.Substring(1, $val.Length - 2) }
            if ($m.Groups[1].Value -eq 'POSTGRES_BIN') {
                if ($val) { $r.PgBin = $val }
            } elseif ($m.Groups[1].Value -eq 'WINDOWS_WEB_BASE_PATH') {
                if ($val) { $r.WebBasePath = $val }
            } elseif ($m.Groups[1].Value -eq 'WINDOWS_WEB_PORT') {
                if ($val -match '^\d{1,5}$') { $r.WebPort = [int]$val }
            } else {
                # scheme://[userinfo@]host[:port]/... — userinfo는 캡처하지 않는다(host·port만)
                $u = [regex]::Match($val, '^[A-Za-z][A-Za-z0-9+.\-]*://(?:[^@/?#]*@)?(\[[^\]]+\]|[^:/?#]+)(?::(\d+))?')
                if ($u.Success) {
                    $r.PgHost = $u.Groups[1].Value.Trim('[', ']')
                    $r.PgPort = if ($u.Groups[2].Success) { [int]$u.Groups[2].Value } else { 5432 }
                }
                $u = $null
            }
            $val = $null; $m = $null
        }
        $line = $null
    }
    $pyRoot = Join-Path $DashboardRoot '.tools\python'
    if (Test-Path -LiteralPath $pyRoot -PathType Container) {
        $cands = @(Get-ChildItem -LiteralPath $pyRoot -Directory -Filter 'cpython-3.12.*' -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'python.exe') -PathType Leaf } |
            Sort-Object -Descending -Property @{ Expression = { $v = [regex]::Match($_.Name, '^cpython-(\d+\.\d+\.\d+)'); if ($v.Success) { [version]$v.Groups[1].Value } else { [version]'0.0.0' } } })
        if ($cands.Count) { $r.PythonExe = Join-Path $cands[0].FullName 'python.exe' }
    }
    $tools = Join-Path $DashboardRoot '.tools'
    if (Test-Path -LiteralPath $tools -PathType Container) {
        $nodes = @(Get-ChildItem -LiteralPath $tools -Directory -Filter 'node-v22.*-win-x64' -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'node.exe') -PathType Leaf } |
            Sort-Object -Descending -Property @{ Expression = { $v = [regex]::Match($_.Name, '^node-v(\d+\.\d+\.\d+)'); if ($v.Success) { [version]$v.Groups[1].Value } else { [version]'0.0.0' } } })
        if ($nodes.Count) { $r.NodeExe = Join-Path $nodes[0].FullName 'node.exe' }
    }
    return [pscustomobject]$r
}

function Merge-DashboardDefaults {
    <# deploy.json 객체($cfg)에서 pg_bin·pg_host·pg_port·python_exe가 비어 있거나 없을 때만 대시보드 값으로 채운다. 채운 키 이름 목록을 돌려준다. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Config, [Parameter(Mandatory = $true)]$Defaults)
    $filled = @()
    $map = [ordered]@{ pg_bin = $Defaults.PgBin; pg_host = $Defaults.PgHost; pg_port = $Defaults.PgPort; python_exe = $Defaults.PythonExe }
    foreach ($k in $map.Keys) {
        $p = $Config.PSObject.Properties[$k]
        $cur = if ($p) { $p.Value } else { $null }
        if (($null -eq $cur -or "$cur" -eq '') -and $null -ne $map[$k] -and "$($map[$k])" -ne '') {
            $Config | Add-Member -NotePropertyName $k -NotePropertyValue $map[$k] -Force
            $filled += $k
        }
    }
    return , $filled
}
