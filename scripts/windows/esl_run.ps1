# esl_run.ps1 -- ESL_probe.bat / ESL_extract.bat / ESL_upload.bat 가 (current\esl_launch.ps1 을 거쳐) 부르는 실행기
#   update.ps1 이 deploy_dir\versions\<버전>\ 에 TCL·esl_upload_lib.ps1 과 함께 배포한다. 같은 폴더의 것을 쓴다.
#
#   ESL_probe.bat   <h3d> [<h3d> ...] [<part>]
#   ESL_extract.bat <h3d> [<h3d> ...] [<rad>] [<part>] [/original|/slim|/pcextract]   (part 기본값 = 설정 default_part)
#       기본 = 압축 모드(계약 esl_upload_speed.md): hvtrans 로 대상 파트·결과 3종·전 프레임만 남긴 슬림 h3d + rad + include 를
#       ESL 서버로 올리고 새 Case 화면을 연다. 실행할 때 설정 slim_prompt_sec 초 동안 묻는다([Enter=압축 / O=원본 / P=PC 추출]).
#       /original = 원본 h3d 를 그대로, /pcextract = 기존 방식(PC HyperView 로 추출한 결과 폴더 + rad 를 올림, 계약 esl_p3_ux.md §9.2).
#       rad 를 같이 끌어다 놓지 않으면 파일 선택 창이 뜬다(취소 = PC 추출만).
#   ESL_upload.bat  <결과 폴더> [<rad>]                  추출 없이 올리기만(중단된 업로드 이어 올리기)
#   ESL_upload.bat  <h3d> <rad> [<part>] [/original|/slim]   추출 없이 h3d(압축 또는 원본) + rad 를 올리기(중단 후 다시 실행 = 이어 올림)
#
# 출력 폴더 = <work_root>\<h3d 파일명(확장자 제외)>\probe | csv
# h3d 가 있는 폴더(공유 SPDM 등)와 protected_roots 아래에는 절대 쓰지 않는다(출력 폴더가 그 아래면 거부).
# 배포 폴더(deploy_dir) 안의 h3d 는 받지 않는다(update 때 지워질 수 있음): 원본 위치의 h3d 를 그대로 쓴다.
# 설정: %LOCALAPPDATA%\esl\esl_deploy.json (update.bat 이 만든다). 실행할 때마다 다시 읽는다.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('probe', 'extract', 'upload')][string]$Mode,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Items = @()
)

$ErrorActionPreference = 'Stop'
$ConfigPath = Join-Path $env:LOCALAPPDATA 'esl\esl_deploy.json'
$BadChars = '[%!&]'

# 서버 올리기(HttpClient·토큰·include 수집·이어 올리기·병렬 전송)
. (Join-Path $PSScriptRoot 'esl_upload_lib.ps1')
# 압축 모드(hvtrans 슬림 h3d)
. (Join-Path $PSScriptRoot 'esl_slim_lib.ps1')

function Say([string]$Message, [string]$Color = 'Gray') { Write-Host $Message -ForegroundColor $Color }

function Expand-ConfigPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $expanded = [Environment]::ExpandEnvironmentVariables($Value.Trim())
    $sep = [IO.Path]::DirectorySeparatorChar
    if ($sep -eq '\') { $expanded = $expanded.Replace('/', '\') }
    return [IO.Path]::GetFullPath($expanded).TrimEnd('\', '/')
}

# a 가 b 와 같거나 b 아래인지 (대소문자 무시, 전체 경로 기준)
function Test-PathUnder([string]$Child, [string]$Parent) {
    if (-not $Child -or -not $Parent) { return $false }
    $sep = [string][IO.Path]::DirectorySeparatorChar
    $c = [IO.Path]::GetFullPath($Child).TrimEnd('\', '/') + $sep
    $p = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/') + $sep
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

# 경로 자체와 그 위 폴더들 중 실제로 있는 것의 링크(junction/symlink)를 풀어 실제 대상 경로를 돌려준다
function Resolve-RealPath([string]$Path) {
    $sep = [string][IO.Path]::DirectorySeparatorChar
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $probe = $full
    $tail = ''
    while ($probe -and -not (Test-Path -LiteralPath $probe)) {
        $tail = $sep + (Split-Path -Leaf $probe) + $tail
        $probe = Split-Path -Parent $probe
    }
    if (-not $probe) { return $full }
    $item = Get-Item -Force -LiteralPath $probe
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        $target = @($item.Target)[0]
        if ($target) { return ([IO.Path]::GetFullPath($target).TrimEnd('\', '/') + $tail) }
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

# 입력 h3d 가 배포 폴더(deploy_dir, 이 실행기 폴더) 아래면 거부: update 의 예전 구조 정리·버전 정리 때
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

# done.json 이 있고 ok 인지
function Test-ExtractOk([string]$OutDir) {
    $p = Join-Path $OutDir 'done.json'
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { return $false }
    try { return ((Get-Content -Raw -Encoding UTF8 -LiteralPath $p | ConvertFrom-Json).ok -eq $true) } catch { return $false }
}

# 결과 폴더 + rad(+include) -> 서버. 실패해도 예외 대신 $false (다른 h3d 는 계속)
function Publish-Results($Ctx, [string]$OutDir, [string]$Rad, [string]$Name, [string]$Anchor) {
    Say ''
    Say "==> [upload] $OutDir" 'Cyan'
    Say "    rad: $Rad"
    try {
        if (-not (Test-ExtractOk $OutDir)) { throw "추출 결과가 ok 가 아닙니다(done.json): $OutDir" }
        $plan = Confirm-EslOutsideIncludes (Get-EslUploadPlan $OutDir $Rad)   # rad 폴더 밖 include 는 Y 확인 시만
        if (-not (Confirm-EslPlan $plan)) { Say '    올리기를 취소했습니다.' 'Yellow'; return $false }
        $res = Invoke-EslPcUpload $Ctx $plan $Name (Get-EslUploadKey $Anchor)
        return [bool]$res.Ok
    }
    catch {
        Write-Host ''
        Say ("    [오류] " + $_.Exception.Message) 'Red'
        Say "    다시 실행하면 이어 올립니다(추출 없이: ESL_upload.bat `"$OutDir`" `"$Rad`")" 'Yellow'
        return $false
    }
}

function Get-RadArg([string]$V) {
    if ($V -match $BadChars) { throw "경로에 %, !, & 문자가 있으면 지원하지 않습니다: $V" }
    if (-not (Test-Path -LiteralPath $V -PathType Leaf)) { throw "rad 파일이 없습니다: $V" }
    return [IO.Path]::GetFullPath($V)
}

# hw.exe·TCL 이 필요한 모드(probe, PC 추출)에서만 확인한다(압축·원본 업로드는 hw 없이도 된다)
function Assert-HwReady([string]$HwExe, [string]$Tcl) {
    if (-not $HwExe -or -not (Test-Path -LiteralPath $HwExe -PathType Leaf)) {
        throw "hw.exe 를 찾을 수 없습니다: '$HwExe'  -> 설정 hw_exe 를 고치세요: $ConfigPath"
    }
    if (-not (Test-Path -LiteralPath $Tcl -PathType Leaf)) { throw "TCL 파일이 없습니다: $Tcl  -> update.bat 을 다시 실행하세요." }
}

# 압축(slim)·원본(original) 업로드 한 건. 출력 폴더(<work_root>\<h3d>\slim)는 h3d 폴더·보호 폴더 아래이면 거부한다.
function Invoke-H3dModeUpload($Ctx, [string]$H3d, [string]$Rad, [string]$UploadMode, [string]$PartSpec, $SlimSettings, [string]$WorkRoot, [string]$HwExe, [string]$DeployDir, [string[]]$Protected) {
    if (-not $WorkRoot) { throw "설정 work_root 가 비어 있습니다: $ConfigPath" }
    Assert-InputOutsideDeploy $H3d $DeployDir
    $script:GuardH3dDir = Split-Path -Parent $H3d
    $script:GuardProtected = @($Protected)
    $guard = { param($d) Assert-OutputAllowed $d $script:GuardH3dDir $script:GuardProtected }
    $name = [IO.Path]::GetFileNameWithoutExtension($H3d)
    return (Publish-EslH3d $Ctx $H3d $Rad $UploadMode $PartSpec $SlimSettings $WorkRoot $HwExe $name $guard)
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
    $slim = Get-EslSlimSettings $cfg
    $toolVersion = Get-EslToolVersion

    # ---- 올리기만: ESL_upload.bat <결과 폴더> [<rad>]  또는  <h3d> <rad> [<part>] [/original|/slim] ----
    if ($Mode -eq 'upload') {
        $resDir = ''; $rad = ''; $h3dUp = ''; $partUp = ''; $swUp = ''
        $unknown = @()
        $raw = @($Items | Where-Object { $_ -ne $null -and $_.Trim() -ne '' })
        if ($raw.Count -eq 0) {
            $line = Read-EslInput '결과 폴더(ESL_extract.bat 이 만든 csv 폴더) 또는 h3d 경로'
            if ($line) { $raw = @($line) }
        }
        foreach ($a in $raw) {
            $v = $a.Trim().Trim('"').Trim()
            if (-not $v) { continue }
            $sw = Get-EslModeSwitch $v
            if ($sw) {
                if ($sw -eq 'pcextract') { throw '/pcextract 는 ESL_extract.bat 에서만 쓸 수 있습니다(ESL_upload.bat 은 추출하지 않음).' }
                if ($swUp -and $swUp -ne $sw) { throw "모드 스위치는 하나만 지정할 수 있습니다: /$swUp, /$sw" }
                $swUp = $sw
                continue
            }
            if ($v -match $BadChars) { throw "경로에 %, !, & 문자가 있으면 지원하지 않습니다: $v" }
            if (Test-Path -LiteralPath $v -PathType Container) {
                if ($resDir) { throw "결과 폴더는 하나만 지정할 수 있습니다: $resDir, $v" }
                $resDir = [IO.Path]::GetFullPath($v).TrimEnd('\')
            }
            elseif ([IO.Path]::GetExtension($v) -ieq '.rad') {
                if ($rad) { throw "rad 는 하나만 지정할 수 있습니다(Starter _0000.rad): $rad, $v" }
                $rad = Get-RadArg $v
            }
            elseif ([IO.Path]::GetExtension($v) -ieq '.h3d' -and (Test-Path -LiteralPath $v -PathType Leaf)) {
                if ($h3dUp) { throw "h3d 는 하나만 지정할 수 있습니다: $h3dUp, $v" }
                $h3dUp = [IO.Path]::GetFullPath($v)
            }
            else { $unknown += $v }
        }
        if ($h3dUp) {
            # h3d(압축 또는 원본) + rad 올리기
            if ($resDir) { throw "결과 폴더와 h3d 를 함께 지정할 수 없습니다: $resDir, $h3dUp" }
            if ($unknown.Count -gt 1) { throw ("파트는 하나만 지정할 수 있습니다: " + ($unknown -join ', ')) }
            $partUp = $(if ($unknown.Count -eq 1) { $unknown[0] } else { $defaultPart })
            if (-not $rad) {
                $rad = Select-EslRadFile (Split-Path -Parent $h3dUp) "rad 파일 선택 - $(Split-Path -Leaf $h3dUp)"
                if (-not $rad) { throw 'rad 파일이 없어 올리지 않습니다.' }
                $rad = Get-RadArg $rad
            }
            $upMode = Resolve-EslUploadMode $swUp $slim $partUp $false
            if ($upMode -ne 'slim' -and $upMode -ne 'original') { $upMode = 'slim' }
            Say ''
            Say "==> [$upMode] $h3dUp" 'Cyan'
            Say "    rad: $rad"
            $ctx = New-EslContext (Get-EslServerUrl $ConfigPath $cfg) $null $slim.UploadParallel
            $ctx.ToolVersion = $toolVersion
            try {
                [void](Connect-EslClient $ctx)
                if (-not (Invoke-H3dModeUpload $ctx $h3dUp $rad $upMode $partUp $slim $workRoot $hwExe $deployDir $protected)) { $exitCode = 1 }
            }
            catch {
                Write-Host ''
                Say ("    [오류] " + $_.Exception.Message) 'Red'
                Say "    다시 실행하면 이어 올립니다(ESL_upload.bat `"$h3dUp`" `"$rad`")" 'Yellow'
                $exitCode = 1
            }
            exit $exitCode
        }
        if ($unknown.Count -gt 0) { throw "결과 폴더나 rad 파일이 아닙니다: $($unknown[0])" }
        if ($swUp) { throw "/$swUp 는 h3d 를 올릴 때만 쓸 수 있습니다(결과 폴더 올리기에는 모드가 없음)." }
        if (-not $resDir) { throw '결과 폴더가 지정되지 않았습니다. ESL_extract.bat 이 만든 csv 폴더를 ESL_upload.bat 위로 끌어다 놓으세요.' }
        $done = Join-Path $resDir 'done.json'
        if (-not (Test-Path -LiteralPath $done -PathType Leaf)) { throw "결과 폴더에 done.json 이 없습니다: $resDir" }
        if (-not $rad) {
            $rad = Select-EslRadFile '' "rad 파일 선택 - $(Split-Path -Leaf $resDir)"
            if (-not $rad) { throw 'rad 파일이 없어 올리지 않습니다.' }
            $rad = Get-RadArg $rad
        }
        $name = Split-Path -Leaf $resDir
        if ($name -ieq 'csv') { $name = Split-Path -Leaf (Split-Path -Parent $resDir) }
        $ctx = New-EslContext (Get-EslServerUrl $ConfigPath $cfg) $null $slim.UploadParallel
        $ctx.ToolVersion = $toolVersion
        if (-not (Publish-Results $ctx $resDir $rad $name $done)) { $exitCode = 1 }
        exit $exitCode
    }

    if (-not $workRoot) { throw "설정 work_root 가 비어 있습니다: $ConfigPath" }
    $tcl = Join-Path $PSScriptRoot $(if ($Mode -eq 'probe') { 'esl_h3d_probe.tcl' } else { 'esl_h3d_extract.tcl' })
    if ($Mode -eq 'probe') { Assert-HwReady $hwExe $tcl }     # extract 는 PC 추출(pcextract)을 할 때만 hw 가 필요

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

    # 인자 분류: 있는 파일 = h3d (extract 는 .rad 도), 그 외(.h3d 로 끝나지 않는 것 1개) = 파트
    $h3ds = @()
    $part = ''
    $radArg = ''
    $modeSwitch = ''
    foreach ($a in $raw) {
        $v = $a.Trim().Trim('"').Trim()
        if (-not $v) { continue }
        $sw = Get-EslModeSwitch $v
        if ($sw) {
            if ($Mode -ne 'extract') { throw "/$sw 는 ESL_extract.bat 에서만 쓸 수 있습니다." }
            if ($modeSwitch -and $modeSwitch -ne $sw) { throw "모드 스위치는 하나만 지정할 수 있습니다: /$modeSwitch, /$sw" }
            $modeSwitch = $sw
            continue
        }
        if ($v -match $BadChars) {
            throw "경로/인자에 %, !, & 문자가 있으면 지원하지 않습니다(배치 파일이 값을 바꿀 수 있음): $v  -> 파일/폴더 이름을 바꾸세요."
        }
        if ($Mode -eq 'extract' -and [IO.Path]::GetExtension($v) -ieq '.rad' -and (Test-Path -LiteralPath $v -PathType Leaf)) {
            if ($radArg) { throw "rad 는 하나만 끌어다 놓으세요(Starter _0000.rad): $radArg, $v" }
            $radArg = [IO.Path]::GetFullPath($v)
            continue
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

    # extract: h3d 마다 rad(끌어다 놓은 것 또는 선택 창, 취소 = PC 추출만) + 업로드 방식 + 서버 연결(처음엔 주소·연결 코드 질문)
    #   방식(계약 esl_upload_speed.md US-2): 스위치(/original /slim /pcextract) > 실행 시 질문(slim_prompt_sec 초) > 설정 upload_mode_default(기본 slim)
    $radFor = @{}
    $ctx = $null
    $runMode = 'pcextract'
    if ($Mode -eq 'extract') {
        foreach ($h in $h3ds) {
            if ($radArg) { $radFor[$h] = $radArg; continue }
            $sel = Select-EslRadFile (Split-Path -Parent $h) ("rad 파일 선택 - " + (Split-Path -Leaf $h) + " (취소 = PC 추출만)")
            if ($sel) { $radFor[$h] = (Get-RadArg $sel) } else { Say "    $(Split-Path -Leaf $h): rad 를 고르지 않아 PC 추출만 합니다(압축 모드는 rad 가 필요)." 'Yellow' }
        }
        if ($radFor.Count -gt 0) {
            $runMode = Resolve-EslUploadMode $modeSwitch $slim $part $true
            Say ("    업로드 방식: {0}" -f $runMode) 'DarkGray'
        }
        elseif ($modeSwitch -eq 'slim' -or $modeSwitch -eq 'original') {
            Say "    [경고] rad 가 없어 /$modeSwitch 를 쓸 수 없습니다 - PC 추출만 합니다." 'Yellow'
        }
        if ($radFor.Count -gt 0) {
            try {
                $ctx = New-EslContext (Get-EslServerUrl $ConfigPath $cfg) $null $slim.UploadParallel
                $ctx.ToolVersion = $toolVersion
                [void](Connect-EslClient $ctx)
            }
            catch {
                Say ("    [경고] 서버 연결 준비 실패 - " + $(if ($runMode -eq 'pcextract') { '추출만 합니다(나중에 ESL_upload.bat)' } else { '업로드하지 않습니다' }) + ": " + $_.Exception.Message) 'Yellow'
                $ctx = $null
            }
        }
    }

    $sub = if ($Mode -eq 'probe') { 'probe' } else { 'csv' }
    $jsonName = if ($Mode -eq 'probe') { 'probe.json' } else { 'done.json' }
    $okCount = 0
    foreach ($h3d in $h3ds) {
        $stem = [IO.Path]::GetFileNameWithoutExtension($h3d)
        $h3dDir = Split-Path -Parent $h3d
        $outDir = Join-Path (Join-Path $workRoot $stem) $sub
        $rad = $(if ($ctx -and $radFor.ContainsKey($h3d)) { $radFor[$h3d] } else { '' })
        $hMode = $(if ($Mode -eq 'extract' -and $radFor.ContainsKey($h3d)) { $runMode } else { 'pcextract' })
        Say ''
        if ($hMode -eq 'slim' -or $hMode -eq 'original') {
            Say "==> [$hMode] $h3d" 'Cyan'
            if ($part) { Say "    파트: $part" }
            try {
                if (-not $ctx) { throw '서버에 연결하지 못해 올릴 수 없습니다(위 경고 확인). 연결 뒤 ESL_extract.bat 을 다시 실행하세요.' }
                if (Invoke-H3dModeUpload $ctx $h3d $radFor[$h3d] $hMode $part $slim $workRoot $hwExe $deployDir $protected) { $okCount++ }
                else { $exitCode = 1 }
            }
            catch {
                Write-Host ''
                Say ("    [오류] " + $_.Exception.Message) 'Red'
                Say "    다시 실행하면 이어 올립니다(ESL_upload.bat `"$h3d`" `"$($radFor[$h3d])`")" 'Yellow'
                $exitCode = 1
            }
            continue
        }
        Say "==> [$Mode] $h3d" 'Cyan'
        Say "    출력: $outDir"
        if ($part) { Say "    파트: $part" }
        try {
            Assert-InputOutsideDeploy $h3d $deployDir
            Assert-OutputAllowed $outDir $h3dDir $protected
            New-Item -ItemType Directory -Force -Path $outDir | Out-Null
            Assert-OutputAllowed $outDir $h3dDir $protected   # 만든 뒤 링크 경로로 다시 확인
            $skip = $false
            if ($rad -and (Test-ExtractOk $outDir) -and (Read-EslUploadState $ctx.StatePath).ContainsKey((Get-EslUploadKey $h3d))) {
                $ans = Read-EslInput '    이 h3d 의 올리기가 진행 중입니다. 기존 추출 결과로 올리기만 이어 갈까요? (Y/n)'
                $skip = -not ($ans -and $ans.Trim() -match '^(n|no|아니오|ㄴ)$')
            }
            if ($skip) { Say '    추출 생략(기존 결과 사용)' 'DarkGray'; $okCount++ }
            else {
                Assert-HwReady $hwExe $tcl
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
                if (Show-Result (Join-Path $outDir $jsonName) $Mode) { $okCount++ } else { $exitCode = 1; $rad = '' }
                if (-not $rad) { Start-Process -FilePath 'explorer.exe' -ArgumentList (Quote-Arg $outDir) }
            }
            if ($rad) {
                if (-not (Publish-Results $ctx $outDir $rad $stem $h3d)) { $exitCode = 1 }
            }
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
