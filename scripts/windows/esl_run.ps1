# esl_run.ps1 -- ESL_probe.bat / ESL_extract.bat 가 부르는 실행기 (update.ps1 이 deploy_dir\current 로 배포)
#
#   ESL_probe.bat   <h3d> [<h3d> ...] [<part>]
#   ESL_extract.bat <h3d> [<h3d> ...] [<part>]      (part 기본값 = 설정 default_part)
#
# 출력 폴더 = <work_root>\<h3d 파일명(확장자 제외)>\probe | csv
# h3d 가 있는 폴더(공유 SPDM 등)와 protected_roots 아래에는 절대 쓰지 않는다(출력 폴더가 그 아래면 거부).
# 배포 폴더(deploy_dir) 안의 h3d 는 받지 않는다(update 때 지워질 수 있음): 원본 위치의 h3d 를 그대로 쓴다.
# 설정: %LOCALAPPDATA%\esl\esl_deploy.json (update.bat 이 만든다). 실행할 때마다 다시 읽는다.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('probe', 'extract')][string]$Mode,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Items = @()
)

$ErrorActionPreference = 'Stop'
$ConfigPath = Join-Path $env:LOCALAPPDATA 'esl\esl_deploy.json'
$BadChars = '[%!&]'

function Say([string]$Message, [string]$Color = 'Gray') { Write-Host $Message -ForegroundColor $Color }

function Expand-ConfigPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $expanded = [Environment]::ExpandEnvironmentVariables($Value.Trim())
    return [IO.Path]::GetFullPath($expanded.Replace('/', '\')).TrimEnd('\')
}

# a 가 b 와 같거나 b 아래인지 (대소문자 무시, 전체 경로 기준)
function Test-PathUnder([string]$Child, [string]$Parent) {
    if (-not $Child -or -not $Parent) { return $false }
    $c = [IO.Path]::GetFullPath($Child).TrimEnd('\') + '\'
    $p = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

# 경로 자체와 그 위 폴더들 중 실제로 있는 것의 링크(junction/symlink)를 풀어 실제 대상 경로를 돌려준다
function Resolve-RealPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $probe = $full
    $tail = ''
    while ($probe -and -not (Test-Path -LiteralPath $probe)) {
        $tail = '\' + (Split-Path -Leaf $probe) + $tail
        $probe = Split-Path -Parent $probe
    }
    if (-not $probe) { return $full }
    $item = Get-Item -Force -LiteralPath $probe
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        $target = @($item.Target)[0]
        if ($target) { return ([IO.Path]::GetFullPath($target).TrimEnd('\') + $tail) }
    }
    return $full
}

# 출력 폴더 금지 규칙: h3d 폴더 아래 / protected_roots 아래 (링크를 푼 경로로도 다시 확인)
function Assert-OutputAllowed([string]$OutDir, [string]$H3dDir, [string[]]$Protected) {
    foreach ($cand in @($OutDir, (Resolve-RealPath $OutDir))) {
        if (Test-PathUnder $cand $H3dDir) {
            throw "출력 폴더가 h3d 폴더 아래입니다(공유 폴더에는 쓰지 않음): $cand  -> 설정 work_root 를 다른 곳으로 바꾸세요: $ConfigPath"
        }
        foreach ($root in $Protected) {
            if ($root -and (Test-PathUnder $cand $root)) {
                throw "출력 폴더가 보호 폴더(protected_roots) 아래입니다: $cand (보호: $root)"
            }
        }
    }
}

# 입력 h3d 가 배포 폴더(deploy_dir, 이 실행기 폴더) 아래면 거부: update 의 current 교체·버전 정리 때
# 지워질 수 있다. 원본 위치의 h3d 를 그대로(읽기 전용으로) 쓰게 한다. 링크를 푼 경로로도 확인.
function Assert-InputOutsideDeploy([string]$H3d, [string]$DeployDir) {
    foreach ($cand in @($H3d, (Resolve-RealPath $H3d))) {
        foreach ($root in @($DeployDir, $PSScriptRoot)) {
            if ($root -and (Test-PathUnder $cand $root)) {
                throw "h3d 가 배포 폴더 안에 있습니다(update 때 지워질 수 있음): $cand (배포 폴더: $root)  -> 원본 위치의 h3d를 그대로 끌어다 놓으세요(읽기 전용으로 사용). 배포 폴더에 복사한 h3d 는 다른 곳으로 옮기세요."
            }
        }
    }
}

function Quote-Arg([string]$Value) { return '"' + $Value + '"' }

function Show-Result([string]$JsonPath, [string]$Kind) {
    if (-not (Test-Path -LiteralPath $JsonPath -PathType Leaf)) {
        $fallback = Join-Path $PSScriptRoot ($(if ($Kind -eq 'probe') { 'esl_probe_fallback.json' } else { 'esl_extract_done_fallback.json' }))
        if (Test-Path -LiteralPath $fallback -PathType Leaf) {
            Say "  결과 파일이 출력 폴더에 없어 대체 파일을 읽습니다: $fallback" 'Yellow'
            $JsonPath = $fallback
        }
        else {
            Say "  결과 파일 없음: $JsonPath (콘솔 로그를 확인하세요)" 'Red'
            return $false
        }
    }
    try {
        $j = Get-Content -Raw -Encoding UTF8 -LiteralPath $JsonPath | ConvertFrom-Json
    }
    catch {
        Say "  결과 JSON 을 읽지 못했습니다: $JsonPath ($($_.Exception.Message))" 'Red'
        return $false
    }
    $ok = ($j.ok -eq $true)
    Say ("  ok          : {0}" -f $ok) $(if ($ok) { 'Green' } else { 'Red' })
    if (-not $ok) {
        Say ("  code        : {0}" -f $j.code) 'Red'
        Say ("  failed_step : {0}" -f $j.failed_step) 'Red'
        Say ("  error       : {0}" -f $j.error) 'Red'
    }
    if ($Kind -eq 'probe') {
        Say ("  components  : {0}" -f @($j.components).Count)
        Say ("  subcases    : {0}" -f @($j.subcases).Count)
    }
    else {
        if ($ok) { Say ("  part        : {0} ({1})  frames={2} elems={3} nodes={4}" -f $j.part_title, $j.part_id, $j.n_frames, $j.n_elems, $j.n_nodes) }
        elseif (@($j.components).Count -gt 0) {
            Say '  h3d 의 component 목록(파트 이름/ID 를 골라 다시 실행: ESL_extract.bat <h3d> <part>):' 'Yellow'
            foreach ($c in @($j.components | Select-Object -First 40)) { Say ("    {0,8}  {1}" -f $c.id, $c.name) }
        }
    }
    foreach ($w in @($j.warnings)) { if ($w) { Say "  warning     : $w" 'Yellow' } }
    return $ok
}

$exitCode = 0
try {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "설정 파일이 없습니다: $ConfigPath  -> 저장소 폴더의 update.bat 을 먼저 실행하세요."
    }
    $cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $ConfigPath | ConvertFrom-Json
    $hwExe = Expand-ConfigPath ([string]$cfg.hw_exe)
    $workRoot = Expand-ConfigPath ([string]$cfg.work_root)
    $defaultPart = [string]$cfg.default_part
    $protected = @(@($cfg.protected_roots) | Where-Object { $_ } | ForEach-Object { Expand-ConfigPath ([string]$_) })
    $deployDir = Expand-ConfigPath ([string]$cfg.deploy_dir)
    if (-not $hwExe -or -not (Test-Path -LiteralPath $hwExe -PathType Leaf)) {
        throw "hw.exe 를 찾을 수 없습니다: '$hwExe'  -> 설정 hw_exe 를 고치세요: $ConfigPath"
    }
    if (-not $workRoot) { throw "설정 work_root 가 비어 있습니다: $ConfigPath" }
    $tcl = Join-Path $PSScriptRoot $(if ($Mode -eq 'probe') { 'esl_h3d_probe.tcl' } else { 'esl_h3d_extract.tcl' })
    if (-not (Test-Path -LiteralPath $tcl -PathType Leaf)) { throw "TCL 파일이 없습니다: $tcl  -> update.bat 을 다시 실행하세요." }

    # 인자 없으면 입력 받기
    $raw = @($Items | Where-Object { $_ -ne $null -and $_.Trim() -ne '' })
    if ($raw.Count -eq 0) {
        $line = Read-Host 'h3d 파일 경로를 입력하세요(따옴표 가능)'
        if ($line) { $raw = @($line) }
        if ($Mode -eq 'extract') {
            $p = Read-Host "파트 이름 또는 ID (Enter = $defaultPart)"
            if ($p) { $raw += $p }
        }
    }

    # 인자 분류: 있는 파일 = h3d, 그 외(.h3d 로 끝나지 않는 것 1개) = 파트
    $h3ds = @()
    $part = ''
    foreach ($a in $raw) {
        $v = $a.Trim().Trim('"').Trim()
        if (-not $v) { continue }
        if ($v -match $BadChars) {
            throw "경로/인자에 %, !, & 문자가 있으면 지원하지 않습니다(배치 파일이 값을 바꿀 수 있음): $v  -> 파일/폴더 이름을 바꾸세요."
        }
        if (Test-Path -LiteralPath $v -PathType Leaf) {
            if ([IO.Path]::GetExtension($v) -ne '.h3d') { throw "h3d 파일만 받습니다: $v" }
            $h3ds += [IO.Path]::GetFullPath($v)
        }
        elseif ($v -match '\.h3d$' -or $v -match '[\\/]') {
            throw "h3d 파일이 없습니다: $v  (경로에 %, !, & 가 있으면 배치 파일이 경로를 잘라 냅니다)"
        }
        elseif ($part) {
            throw "파트는 하나만 지정할 수 있습니다: '$part', '$v'"
        }
        else { $part = $v }
    }
    if ($h3ds.Count -eq 0) { throw 'h3d 파일이 지정되지 않았습니다. h3d 파일을 이 bat 파일 위로 끌어다 놓으세요.' }
    if ($Mode -eq 'extract' -and -not $part) { $part = $defaultPart }

    $sub = if ($Mode -eq 'probe') { 'probe' } else { 'csv' }
    $jsonName = if ($Mode -eq 'probe') { 'probe.json' } else { 'done.json' }
    $okCount = 0
    foreach ($h3d in $h3ds) {
        $stem = [IO.Path]::GetFileNameWithoutExtension($h3d)
        $h3dDir = Split-Path -Parent $h3d
        $outDir = Join-Path (Join-Path $workRoot $stem) $sub
        Say ''
        Say "==> [$Mode] $h3d" 'Cyan'
        Say "    출력: $outDir"
        if ($part) { Say "    파트: $part" }
        try {
            Assert-InputOutsideDeploy $h3d $deployDir
            Assert-OutputAllowed $outDir $h3dDir $protected
            New-Item -ItemType Directory -Force -Path $outDir | Out-Null
            Assert-OutputAllowed $outDir $h3dDir $protected   # 만든 뒤 링크 경로로 다시 확인
            $hwArgs = @('-clientconfig', 'hwpost.dat', '-b', '-tcl', (Quote-Arg $tcl), '-input', (Quote-Arg $h3d), '-output', (Quote-Arg $outDir))
            if ($part) { $hwArgs += @('-part', (Quote-Arg $part)) }
            # 인자가 hw 에 전달되지 않는 설치본 대비(TCL 이 환경변수도 읽음)
            $env:ESL_INPUT = $h3d; $env:ESL_OUTPUT = $outDir; $env:ESL_PART = $part; $env:ESL_CONFIG = ''
            $log = Join-Path $outDir ($Mode + '_console.log')
            $errLog = Join-Path $outDir ($Mode + '_stderr_console.log')
            Say "    실행 중... (콘솔 로그: $log)"
            $proc = Start-Process -FilePath $hwExe -ArgumentList ($hwArgs -join ' ') -WorkingDirectory $outDir `
                -RedirectStandardOutput $log -RedirectStandardError $errLog -NoNewWindow -Wait -PassThru
            Say ("    hw 종료 코드: {0}" -f $proc.ExitCode)
            if (Show-Result (Join-Path $outDir $jsonName) $Mode) { $okCount++ } else { $exitCode = 1 }
            Start-Process -FilePath 'explorer.exe' -ArgumentList (Quote-Arg $outDir)
        }
        catch {
            Say ("    [오류] " + $_.Exception.Message) 'Red'
            $exitCode = 1
        }
    }
    Say ''
    Say ("완료: 성공 {0} / 전체 {1}" -f $okCount, $h3ds.Count) $(if ($okCount -eq $h3ds.Count) { 'Green' } else { 'Yellow' })
}
catch {
    Say ("[오류] " + $_.Exception.Message) 'Red'
    $exitCode = 1
}
exit $exitCode
