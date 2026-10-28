# esl_slim_lib.ps1 -- 압축 모드(hvtrans 슬림 h3d) 업로드 (계약 docs/contracts/esl_upload_speed.md §4, v0.6.0)
#   esl_run.ps1 이 esl_upload_lib.ps1 다음에 dot-source 한다(update.ps1 이 versions\<버전>\ 에 함께 배포).
#
#   흐름 : rad(+include) 의 /PART title -> 파트 ID(서버 match_parts 와 같은 정규화) -> hvtrans cfg 생성 -> hvtrans 실행
#          -> 슬림 h3d 검증 -> h3d + rad + include 를 병렬 업로드(메타 포함)
#   출력 : <work_root>\<h3d 파일명>\slim\  (esl_slim.cfg, hvtrans.log, <h3d 파일명>_slim.h3d, esl_slim.json). 원본 h3d 폴더에는 쓰지 않는다.
#   실패 : 원인 1줄 + 로그 경로를 보이고 원본 업로드를 묻는다(비대화형이면 올리지 않고 실패).
# Windows 전용 부분(키 입력 대기·탐색기)은 몇 함수에만 있다 - 시험은 그 함수들과 hvtrans·hw 를 가짜로 바꿔 Linux pwsh 에서 실행한다.
# PowerShell 5.1 호환 문법만 쓴다.

if (-not (Get-Command Resolve-EslInclude -ErrorAction SilentlyContinue)) { . (Join-Path $PSScriptRoot 'esl_upload_lib.ps1') }
$script:EslSlimLibDir = $PSScriptRoot

# 기본 결과 = 서버 추출 TCL(resources/tcl/esl_h3d_extract.tcl)의 기본값(strain_type·strain_layer·epsp_type·epsp_layer·disp_type)과 같아야 한다(정적 시험).
$EslSlimResultsDefault = '[{"type":"Displacement"},{"type":"Max_Strain","layer":"Mid"},{"type":"Plastic Strain","layer":"Mid"}]'
$EslSlimModes = @('slim', 'original', 'pcextract')
$EslSlimPoolDefault = 'Component'
$EslSlimLayerStylesDefault = @('paren', 'bare')

# ---- 설정 --------------------------------------------------------------------------------------------

function Get-EslCfgValue($Cfg, [string]$Name, $Default) {
    if ($null -ne $Cfg -and ($Cfg.PSObject.Properties.Name -contains $Name)) {
        $v = $Cfg.$Name
        if ($null -ne $v -and "$v" -ne '') { return $v }
    }
    return $Default
}

function ConvertTo-EslCfgInt($Value, [int]$Default, [int]$Min, [int]$Max) {
    $n = 0
    if (-not [int]::TryParse([string]$Value, [ref]$n)) { return $Default }
    return [Math]::Min([Math]::Max($n, $Min), $Max)
}

function ConvertTo-EslCfgBool($Value, [bool]$Default) {
    if ($Value -is [bool]) { return $Value }
    $t = ([string]$Value).Trim().ToLowerInvariant()
    if ($t -in @('true', '1', 'yes', 'y')) { return $true }
    if ($t -in @('false', '0', 'no', 'n')) { return $false }
    return $Default
}

# esl_deploy.json -> 압축 모드 설정(없는 키는 기본값). 키 이름은 계약 §7.
function Get-EslSlimSettings($Cfg) {
    $mode = ([string](Get-EslCfgValue $Cfg 'upload_mode_default' 'slim')).Trim().ToLowerInvariant()
    if ($EslSlimModes -notcontains $mode) { $mode = 'slim' }
    $exe = [string](Get-EslCfgValue $Cfg 'hvtrans_exe' (Get-EslCfgValue $Cfg 'hvtrans_exe_path' ''))
    $rawResults = Get-EslCfgValue $Cfg 'slim_results' $null
    if ($null -eq $rawResults) { $rawResults = $EslSlimResultsDefault | ConvertFrom-Json }
    $results = New-Object System.Collections.ArrayList
    foreach ($r in @($rawResults)) {
        if ($null -eq $r -or -not ($r.PSObject.Properties.Name -contains 'type') -or -not ([string]$r.type).Trim()) { continue }
        $layer = $null
        if ($r.PSObject.Properties.Name -contains 'layer' -and $null -ne $r.layer -and ([string]$r.layer).Trim()) { $layer = ([string]$r.layer).Trim() }
        [void]$results.Add([pscustomobject]@{ type = ([string]$r.type).Trim(); layer = $layer })
    }
    if ($results.Count -eq 0) { foreach ($r in @($EslSlimResultsDefault | ConvertFrom-Json)) { [void]$results.Add([pscustomobject]@{ type = $r.type; layer = $(if ($r.PSObject.Properties.Name -contains 'layer') { $r.layer } else { $null }) }) } }
    $pools = @(@(Get-EslCfgValue $Cfg 'slim_pool' $EslSlimPoolDefault) | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    $styles = @(@(Get-EslCfgValue $Cfg 'slim_layer_styles' $EslSlimLayerStylesDefault) | ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } | Where-Object { $_ -in @('paren', 'bare') })
    if ($styles.Count -eq 0) { $styles = @($EslSlimLayerStylesDefault) }
    $sub = ([string](Get-EslCfgValue $Cfg 'slim_subcase' 'all')).Trim()
    if (-not $sub) { $sub = 'all' }
    return [pscustomobject]@{
        HvtransExe     = $exe
        ModeDefault    = $mode
        PromptSec      = (ConvertTo-EslCfgInt (Get-EslCfgValue $Cfg 'slim_prompt_sec' 10) 10 0 120)
        Results        = @($results.ToArray() | Select-Object -First 8)
        Subcase        = $sub
        Verify         = (ConvertTo-EslCfgBool (Get-EslCfgValue $Cfg 'slim_verify' $true) $true)
        TimeoutMin     = (ConvertTo-EslCfgInt (Get-EslCfgValue $Cfg 'slim_timeout_min' 120) 120 1 1440)
        MinFreeGb      = (ConvertTo-EslCfgInt (Get-EslCfgValue $Cfg 'slim_min_free_gb' 20) 20 0 100000000)
        UploadParallel = (ConvertTo-EslCfgInt (Get-EslCfgValue $Cfg 'upload_parallel' $EslDefaultParallel) $EslDefaultParallel 1 $EslMaxParallel)
        Pools          = $(if ($pools.Count -gt 0) { $pools } else { @($EslSlimPoolDefault) })
        LayerStyles    = $styles
    }
}

# 배포 폴더의 VERSION.txt(update.ps1 이 씀) -> 도구 버전. 없으면 'unknown'.
function Get-EslToolVersion {
    $p = Join-Path $script:EslSlimLibDir 'VERSION.txt'
    $ver = ''; $fallback = ''
    if (Test-Path -LiteralPath $p -PathType Leaf) {
        try {
            foreach ($ln in [IO.File]::ReadAllLines($p)) {
                if ($ln -match '^tool_version=(.+)$') { $ver = $Matches[1].Trim() }
                elseif ($ln -match '^version=(.+)$') { $fallback = $Matches[1].Trim() }
            }
        }
        catch { }
    }
    if (-not $ver) { $ver = $fallback }
    if (-not $ver) { $ver = 'unknown' }
    if ($ver.Length -gt 32) { $ver = $ver.Substring(0, 32) }
    return $ver
}

# ---- 모드 결정(스위치 > 질문 > 설정 기본값) -----------------------------------------------------------

# 인자 하나가 모드 스위치(/original /slim /pcextract, 대소문자 무시)면 모드 이름, 아니면 ''. 경로로 해석하지 않는다.
function Get-EslModeSwitch([string]$Arg) {
    if ($Arg -match '^/(original|slim|pcextract)$') { return $Matches[1].ToLowerInvariant() }
    return ''
}

# 콘솔에서 키 입력을 받을 수 있는가(리다이렉트·-NonInteractive 면 $false). 시험에서 바꿔 끼운다.
function Test-EslInteractiveConsole {
    if (Test-EslNonInteractive) { return $false }
    try { if ([Console]::IsInputRedirected) { return $false } } catch { return $false }
    return $true
}

# 제한 시간 동안 키를 기다린다. 반환: 'ENTER' | 그 키 문자 | ''(시간 초과). 시험에서 바꿔 끼운다.
function Wait-EslKey([int]$Seconds, [string]$Label) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    $shown = -1
    while ([DateTime]::UtcNow -lt $deadline) {
        $left = [int][Math]::Ceiling(($deadline - [DateTime]::UtcNow).TotalSeconds)
        if ($left -ne $shown) {
            $shown = $left
            Write-Host ("`r  {0}초 뒤 {1} " -f $left, $Label) -NoNewline -ForegroundColor Cyan
        }
        if ([Console]::KeyAvailable) {
            $k = [Console]::ReadKey($true)
            Write-Host ''
            if ($k.Key -eq [ConsoleKey]::Enter) { return 'ENTER' }
            return [string]$k.KeyChar
        }
        Start-Sleep -Milliseconds 100
    }
    Write-Host ''
    return ''
}

function Get-EslModeLabel([string]$Mode) {
    if ($Mode -eq 'original') { return '원본' }
    if ($Mode -eq 'pcextract') { return 'PC에서 추출' }
    return '압축'
}

# 업로드 방식 결정. -Switch 가 있으면 그것, 없으면 질문(PromptSec 초 카운트다운, 비대화형이면 묻지 않음), 그다음 설정 기본값.
function Resolve-EslUploadMode([string]$Switch, $Settings, [string]$PartText, [bool]$AllowPcExtract = $true) {
    if ($Switch) {
        if (-not $AllowPcExtract -and $Switch -eq 'pcextract') { throw '/pcextract 는 ESL_extract.bat 에서만 쓸 수 있습니다(ESL_upload.bat 은 추출하지 않음).' }
        return $Switch
    }
    $default = $Settings.ModeDefault
    if (-not $AllowPcExtract -and $default -eq 'pcextract') { $default = 'slim' }
    if ($Settings.PromptSec -le 0 -or -not (Test-EslInteractiveConsole)) { return $default }
    $part = $(if ($PartText) { "파트 $PartText + " } else { '' })
    $keys = $(if ($AllowPcExtract) { '[Enter=압축 / O=원본 / P=PC에서 추출]' } else { '[Enter=압축 / O=원본]' })
    Say ("  압축 모드로 올립니다: {0}변위·최대 변형률(Mid)·소성 변형률(Mid) 전 프레임만 남긴 h3d (원본은 PC에 남음)." -f $part) 'Cyan'
    Say ("  {0}" -f $keys) 'Cyan'
    $label = Get-EslModeLabel $default
    $deadline = [DateTime]::UtcNow.AddSeconds($Settings.PromptSec)
    while ($true) {
        $left = [int][Math]::Ceiling(($deadline - [DateTime]::UtcNow).TotalSeconds)
        if ($left -le 0) { return $default }
        $k = Wait-EslKey $left $label
        if ($k -eq '') { return $default }
        if ($k -eq 'ENTER') { return 'slim' }
        $c = $k.ToLowerInvariant()
        if ($c -eq 'o') { return 'original' }
        if ($c -eq 'p' -and $AllowPcExtract) { return 'pcextract' }
        if ($c -eq 's') { return 'slim' }
    }
}

# ---- hvtrans 탐지·검증 ---------------------------------------------------------------------------------

function ConvertTo-EslNativePath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $v = [Environment]::ExpandEnvironmentVariables($Value.Trim().Trim('"').Trim())
    return $v.Replace('/', [IO.Path]::DirectorySeparatorChar)
}

# 설정 hvtrans_exe -> (없으면) hw.exe 옆 설치 구조 -> (없으면) Program Files\Altair\<버전> 순으로 찾는다.
function Find-EslHvtrans([string]$Configured, [string]$HwExe = '') {
    $tried = New-Object System.Collections.ArrayList
    $cands = New-Object System.Collections.ArrayList
    $c0 = ConvertTo-EslNativePath $Configured
    if ($c0) { [void]$cands.Add([pscustomobject]@{ Path = $c0; Source = '설정 hvtrans_exe' }) }
    $hw = ConvertTo-EslNativePath $HwExe
    if ($hw) {
        try {
            $desk = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $hw)))   # ...\hwdesktop
            if ($desk) {
                $p = [IO.Path]::Combine($desk, 'io', 'result_readers', 'bin', 'win64', 'hvtrans.exe')
                [void]$cands.Add([pscustomobject]@{ Path = $p; Source = 'hw.exe 옆 설치 폴더' })
            }
        }
        catch { }
    }
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $root) { continue }
        $alt = Join-Path $root 'Altair'
        if (-not (Test-Path -LiteralPath $alt -PathType Container)) { continue }
        foreach ($d in @(Get-ChildItem -LiteralPath $alt -Directory | Sort-Object Name -Descending)) {
            $p = [IO.Path]::Combine($d.FullName, 'hwdesktop', 'io', 'result_readers', 'bin', 'win64', 'hvtrans.exe')
            [void]$cands.Add([pscustomobject]@{ Path = $p; Source = 'Altair 설치 폴더(ProgramFiles)' })
        }
    }
    foreach ($c in $cands) {
        [void]$tried.Add($c.Path)
        if (Test-Path -LiteralPath $c.Path -PathType Leaf) {
            $fi = New-Object IO.FileInfo($c.Path)
            if ($fi.Length -le 0) { continue }
            $ver = $null
            try {
                $vi = [Diagnostics.FileVersionInfo]::GetVersionInfo($c.Path)
                if ($vi.FileVersion) { $ver = [string]$vi.FileVersion } elseif ($vi.ProductVersion) { $ver = [string]$vi.ProductVersion }
                if ($ver -and $ver.Length -gt 64) { $ver = $ver.Substring(0, 64) }
            }
            catch { $ver = $null }
            return [pscustomobject]@{ Ok = $true; Path = $fi.FullName; Version = $ver; Source = $c.Source; Tried = $tried.ToArray() }
        }
    }
    $why = "hvtrans.exe 를 찾을 수 없습니다: '$Configured' -> 설정 hvtrans_exe 를 고치세요"
    return [pscustomobject]@{ Ok = $false; Path = ''; Version = $null; Source = ''; Tried = $tried.ToArray(); Reason = $why }
}

# ---- rad /PART 읽기(서버 esl/rad/parser.py 의 /PART 해석과 같은 규칙) -------------------------------------
# '/' 로 시작하는 헤더 줄, 첫 토큰을 '/' 로 쪼갠 조각에서 키워드 PART 와 첫 정수 = part ID,
# 바로 다음 '#' 로 시작하지 않는 줄(빈 줄 포함)의 앞 100자 오른쪽 공백 제거 = title. /END 뒤는 읽지 않고, 같은 ID 가 다시 나오면 뒤의 것.
# include(/INCLUDE·#include)는 나온 위치에서 열어 읽는다(찾는 규칙은 업로드 목록과 같은 Resolve-EslInclude).

function Read-EslRadPartEventsWith([string]$Path, [Text.Encoding]$Encoding) {
    $ev = New-Object System.Collections.ArrayList
    $sr = New-Object IO.StreamReader($Path, $Encoding, $true, 1048576)
    try {
        $await = $null          # 방금 본 /PART 헤더의 이벤트(다음 비주석 줄 = title)
        $pending = $false
        while ($null -ne ($line = $sr.ReadLine())) {
            if ($pending) {
                if (-not $line.Trim() -or $line.StartsWith('#')) { continue }
                $pending = $false
                [void]$ev.Add([pscustomobject]@{ Kind = 'inc'; Spec = (Get-EslIncludeSpec $line); Id = 0; Title = '' })
                continue
            }
            if ($line.Length -eq 0) {
                if ($null -ne $await) { $await.Title = ''; $await = $null }
                continue
            }
            $c0 = $line[0]
            if ($c0 -eq '#') {
                if ($line.Length -ge 8 -and $line.Substring(0, 8) -ieq '#include') {
                    $await = $null
                    [void]$ev.Add([pscustomobject]@{ Kind = 'inc'; Spec = (Get-EslIncludeSpec $line.Substring(8)); Id = 0; Title = '' })
                }
                continue
            }
            if ($c0 -eq '/') {
                $await = $null
                $tok = @($line.Split([char[]]@(' ', "`t"), [StringSplitOptions]::RemoveEmptyEntries))
                $head = $(if ($tok.Count -gt 0) { $tok[0] } else { $line })
                $pieces = @($head.Split('/') | Where-Object { $_ })
                $kw = $(if ($pieces.Count -gt 0) { $pieces[0].ToUpperInvariant() } else { '' })
                if ($kw -eq 'END') { break }
                if ($kw -eq 'INCLUDE') {
                    $t = $line.Trim()
                    $rest = $(if ($t.Length -gt 8) { $t.Substring(8).Trim() } else { '' })
                    if ($rest) { [void]$ev.Add([pscustomobject]@{ Kind = 'inc'; Spec = (Get-EslIncludeSpec $rest); Id = 0; Title = '' }) }
                    else { $pending = $true }
                    continue
                }
                if ($kw -eq 'PART') {
                    $hid = $null
                    for ($i = 1; $i -lt $pieces.Count; $i++) {
                        if ($pieces[$i] -match '^[+-]?[0-9]+$') { $hid = [int64]$pieces[$i]; break }
                    }
                    if ($null -ne $hid) {
                        $e = [pscustomobject]@{ Kind = 'part'; Spec = ''; Id = $hid; Title = '' }
                        [void]$ev.Add($e)
                        $await = $e
                    }
                }
                continue
            }
            if ($null -ne $await) {
                $t = $(if ($line.Length -gt 100) { $line.Substring(0, 100) } else { $line })
                $await.Title = $t.TrimEnd()
                $await = $null
            }
        }
    }
    finally { $sr.Dispose() }
    return $ev.ToArray()
}

# UTF-8 -> cp949 -> latin-1 순서(서버 _decode 와 같은 순서)
function Read-EslRadPartEvents([string]$Path) {
    $encs = @((New-Object Text.UTF8Encoding($false, $true)))
    try { $encs += [Text.Encoding]::GetEncoding(949, [Text.EncoderFallback]::ExceptionFallback, [Text.DecoderFallback]::ExceptionFallback) } catch { }
    $encs += [Text.Encoding]::GetEncoding(28591)
    foreach ($enc in $encs) {
        try { return @(Read-EslRadPartEventsWith $Path $enc) }
        catch {
            $ex = $_.Exception; $dec = $false
            while ($ex) { if ($ex -is [Text.DecoderFallbackException]) { $dec = $true }; $ex = $ex.InnerException }
            if (-not $dec) { throw }
        }
    }
    return @()
}

function Add-EslRadPartsWalk([string]$Path, [int]$Depth, [string]$RootDir, $Parts, $Chain, [int]$MaxDepth) {
    $key = [IO.Path]::GetFullPath($Path).ToLowerInvariant()
    if ($Chain.ContainsKey($key)) { return }
    $Chain[$key] = $true
    try {
        foreach ($e in @(Read-EslRadPartEvents $Path)) {
            if ($e.Kind -eq 'part') { $Parts[[int64]$e.Id] = [string]$e.Title; continue }
            if (-not $e.Spec -or ($Depth + 1) -gt $MaxDepth) { continue }
            $r = Resolve-EslInclude $e.Spec $RootDir $Path
            if ($r.Found) { Add-EslRadPartsWalk $r.Path ($Depth + 1) $RootDir $Parts $Chain $MaxDepth }
        }
    }
    finally { $Chain.Remove($key) }
}

# rad(+include) 의 모든 /PART -> [{Id, Title}] (ID 순)
function Read-EslRadParts([string]$RadPath, [int]$MaxDepth = 8) {
    $root = [IO.Path]::GetFullPath($RadPath)
    $parts = @{}
    Add-EslRadPartsWalk $root 0 (Split-Path -Parent $root) $parts @{} $MaxDepth
    return @($parts.Keys | Sort-Object | ForEach-Object { [pscustomobject]@{ Id = [int64]$_; Title = [string]$parts[$_] } })
}

# 서버 api/services/system.py norm_title / match_parts 와 같은 정규화
function ConvertTo-EslTitleKey([string]$Title, [string]$Mode) {
    if ($Mode -eq 'exact') { return [regex]::Replace($Title.Trim(), '\s+', ' ') }
    return [regex]::Replace($Title, '[\s_-]+', ' ').Trim().ToLowerInvariant()
}

# 숫자 인자는 /PART ID 가 우선, 없으면 title. title 은 exact -> 실패 시 exact_ci.
function Find-EslParts($Parts, [string]$Spec) {
    $s = $Spec.Trim()
    $all = @($Parts)
    if (-not $s) { return [pscustomobject]@{ Hits = @(); By = '' } }
    $idv = [int64]0
    if ($s -match '^[0-9]+$' -and [int64]::TryParse($s, [ref]$idv)) {
        $hits = @($all | Where-Object { $_.Id -eq $idv })
        if ($hits.Count -gt 0) { return [pscustomobject]@{ Hits = $hits; By = 'id' } }
    }
    $want = ConvertTo-EslTitleKey $s 'exact'
    $hits = @($all | Where-Object { (ConvertTo-EslTitleKey $_.Title 'exact') -ceq $want })
    if ($hits.Count -gt 0) { return [pscustomobject]@{ Hits = $hits; By = 'exact' } }
    $want = ConvertTo-EslTitleKey $s 'exact_ci'
    $hits = @($all | Where-Object { (ConvertTo-EslTitleKey $_.Title 'exact_ci') -eq $want })
    return [pscustomobject]@{ Hits = $hits; By = $(if ($hits.Count -gt 0) { 'exact_ci' } else { '' }) }
}

# 후보 표(최대 40행)
function Show-EslPartTable($Parts) {
    $rows = @($Parts)
    foreach ($p in @($rows | Select-Object -First 40)) { Say ("    {0,10}  {1}" -f $p.Id, $p.Title) 'Yellow' }
    if ($rows.Count -gt 40) { Say ("    ... 외 {0}개" -f ($rows.Count - 40)) 'Yellow' }
}

# 대상 파트 결정. 하나로 정해지면 그것, 아니면 후보 표 + ID 입력(O = 원본). 반환 {Ok, Part, Reason, WantOriginal}
function Select-EslSlimPart($Parts, [string]$Spec) {
    $all = @($Parts)
    if ($all.Count -eq 0) { return [pscustomobject]@{ Ok = $false; Part = $null; Reason = 'rad 에서 /PART 를 하나도 찾지 못했습니다(Starter rad 가 맞는지 확인)'; WantOriginal = $false } }
    $m = Find-EslParts $all $Spec
    if ($m.Hits.Count -eq 1) { return [pscustomobject]@{ Ok = $true; Part = $m.Hits[0]; Reason = ''; WantOriginal = $false } }
    $why = $(if ($m.Hits.Count -eq 0) { "파트 '$Spec' 에 맞는 /PART 가 rad 에 없습니다" } else { "파트 '$Spec' 에 맞는 /PART 가 $($m.Hits.Count)개입니다(모호)" })
    $show = $(if ($m.Hits.Count -gt 1) { $m.Hits } else { $all })
    Say "  $why. 후보:" 'Yellow'
    Show-EslPartTable $show
    if (-not (Test-EslInteractiveConsole)) { return [pscustomobject]@{ Ok = $false; Part = $null; Reason = $why; WantOriginal = $false } }
    for ($i = 0; $i -lt 3; $i++) {
        $a = Read-EslInput '  파트 ID 를 입력하세요 (O = 원본 h3d 로 올리기, Enter = 취소)'
        if ($null -eq $a -or -not $a.Trim()) { break }
        $a = $a.Trim()
        if ($a -ieq 'o') { return [pscustomobject]@{ Ok = $false; Part = $null; Reason = '원본 h3d 를 올리기로 했습니다'; WantOriginal = $true } }
        if ($a -match '^[0-9]+$') {
            $hit = @($all | Where-Object { $_.Id -eq [int64]$a })
            if ($hit.Count -eq 1) { return [pscustomobject]@{ Ok = $true; Part = $hit[0]; Reason = ''; WantOriginal = $false } }
        }
        Say "  목록에 없는 ID 입니다: $a" 'Red'
    }
    return [pscustomobject]@{ Ok = $false; Part = $null; Reason = $why; WantOriginal = $false }
}

# ---- hvtrans cfg ---------------------------------------------------------------------------------------
# 형식(계약 §4.2, physicsai 큐레이션 hvtrans_cfg): BeginParts/Pool/EndParts, BeginSubcase/BeginSimulation/EndSimulation/EndSubcase, datatype|comp.
# 결과 표기·layer 위치·Pool 이름은 P0-1~3 실기 확인 대상이라 후보(설정 slim_pool, slim_layer_styles)를 순서대로 시도한다.
#   LayerStyle paren : "Max_Strain (Mid)|all"    bare : "Max_Strain|all"(layer 지정 없음 - 더 크지만 안전한 상위 집합)

function Format-EslCfgResult($Result, [string]$LayerStyle) {
    $name = [string]$Result.type
    if ($LayerStyle -eq 'paren' -and $null -ne $Result.layer -and [string]$Result.layer) { $name = "$name ($($Result.layer))" }
    return ($name + '|all')
}

function New-EslHvtransCfg([int64]$PartId, $Results, [string]$Subcase, [string]$Pool, [string]$LayerStyle) {
    $lines = New-Object System.Collections.ArrayList
    [void]$lines.Add('BeginParts')
    [void]$lines.Add("  Pool $Pool")
    [void]$lines.Add("  $PartId")
    [void]$lines.Add('EndParts')
    [void]$lines.Add("BeginSubcase $Subcase")
    [void]$lines.Add('  BeginSimulation all')
    [void]$lines.Add('  EndSimulation')
    foreach ($r in @($Results)) { [void]$lines.Add('  ' + (Format-EslCfgResult $r $LayerStyle)) }
    [void]$lines.Add('EndSubcase')
    return (($lines.ToArray() -join "`r`n") + "`r`n")
}

# 시도할 cfg 후보 순서: (Pool × LayerStyle) 전체 결과 -> 그다음 Plastic Strain 을 뺀 같은 조합(탄성 해석 대비)
function Get-EslCfgVariants($Settings, [int64]$PartId) {
    $out = New-Object System.Collections.ArrayList
    $epsp = [string]((Get-EslTclDefaultNames).Epsp)
    $noPlastic = @($Settings.Results | Where-Object { [string]$_.type -ne $epsp })
    foreach ($withPlastic in @($true, $false)) {
        if (-not $withPlastic -and $noPlastic.Count -eq @($Settings.Results).Count) { continue }
        $res = $(if ($withPlastic) { @($Settings.Results) } else { $noPlastic })
        if ($res.Count -eq 0) { continue }
        foreach ($pool in $Settings.Pools) {
            foreach ($style in $Settings.LayerStyles) {
                if ($style -eq 'bare' -and @($res | Where-Object { $null -ne $_.layer }).Count -eq 0 -and $out.Count -gt 0) { continue }   # layer 없는 결과뿐이면 paren 과 같음
                $text = New-EslHvtransCfg $PartId $res $Settings.Subcase $pool $style
                [void]$out.Add([pscustomobject]@{ Text = $text; Pool = $pool; Style = $style; Results = $res; WithPlastic = $withPlastic })
            }
        }
    }
    return $out.ToArray()
}

function Get-EslTclDefaultNames { return [pscustomobject]@{ Strain = 'Max_Strain'; Epsp = 'Plastic Strain'; Disp = 'Displacement' } }

function Get-EslTextSha256([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $h = $sha.ComputeHash((New-Object Text.UTF8Encoding($false)).GetBytes($Text)) } finally { $sha.Dispose() }
    return (-join ($h | ForEach-Object { $_.ToString('x2') }))
}

# ---- hvtrans 실행·검증 -----------------------------------------------------------------------------------

function Format-EslArg([string]$Value) { return '"' + $Value + '"' }

function Format-EslElapsed([double]$Sec) {
    $t = [TimeSpan]::FromSeconds([Math]::Floor($Sec))
    if ($t.TotalHours -ge 1) { return ('{0}:{1:mm\:ss}' -f [int][Math]::Floor($t.TotalHours), $t) }
    return $t.ToString('m\:ss')
}

function Stop-EslProcessTree($Proc) {
    try {
        if (Test-EslWindows) { & taskkill.exe /PID $Proc.Id /T /F 2>&1 | Out-Null }
        else { $Proc.Kill() }
    }
    catch { try { $Proc.Kill() } catch { } }
}

# 프로세스를 실행하고 끝날 때까지 기다린다(2초마다 경과·출력 크기 표시). 반환 {ExitCode, Seconds, TimedOut}
function Invoke-EslProcess([string]$Exe, [string]$ArgLine, [string]$WorkDir, [string]$StdOut, [string]$StdErr, [double]$TimeoutMin, [string]$Label, [string]$WatchFile = '') {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -FilePath $Exe -ArgumentList $ArgLine -WorkingDirectory $WorkDir -RedirectStandardOutput $StdOut `
        -RedirectStandardError $StdErr -NoNewWindow -PassThru
    $keepHandle = $proc.Handle          # 종료 코드를 읽으려면 핸들을 먼저 잡아 둔다(PowerShell Start-Process -PassThru 알려진 문제)
    $timedOut = $false
    $isTty = $true
    try { $isTty = -not [Console]::IsOutputRedirected } catch { }
    while (-not $proc.WaitForExit(2000)) {
        $sec = $watch.Elapsed.TotalSeconds
        if ($sec -gt ($TimeoutMin * 60)) { $timedOut = $true; Stop-EslProcessTree $proc; [void]$proc.WaitForExit(10000); break }
        $size = ''
        if ($WatchFile -and (Test-Path -LiteralPath $WatchFile -PathType Leaf)) { $size = ', 출력 ' + (Format-EslBytes ([double](New-Object IO.FileInfo($WatchFile)).Length)) }
        $line = ("  {0} 실행 중... {1} 경과{2}" -f $Label, (Format-EslElapsed $sec), $size)
        if ($isTty) { Write-Host ("`r" + $line.PadRight(100)) -NoNewline }
    }
    if ($isTty) { Write-Host ("`r" + (' ' * 100) + "`r") -NoNewline }
    $proc.WaitForExit()
    $code = $proc.ExitCode
    if ($null -eq $code) { $code = -1 }
    return [pscustomobject]@{ ExitCode = [int]$code; Seconds = $watch.Elapsed.TotalSeconds; TimedOut = $timedOut }
}

function Get-EslLastLines([string]$Path, [int]$N = 3) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    try {
        $lines = @([IO.File]::ReadAllLines($Path) | Where-Object { $_ -and $_.Trim() })
        return ((@($lines | Select-Object -Last $N) | ForEach-Object { $_.Trim() }) -join ' / ')
    }
    catch { return '' }
}

# 슬림 h3d 기본 검사: 존재·헤더 HYPER3D·원본보다 작음. 반환 {Ok, Reason}
function Test-EslSlimFile([string]$Path, [int64]$SourceBytes) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return [pscustomobject]@{ Ok = $false; Reason = 'hvtrans 가 출력 파일을 만들지 않았습니다' } }
    $fi = New-Object IO.FileInfo($Path)
    if ($fi.Length -le 0) { return [pscustomobject]@{ Ok = $false; Reason = '출력 h3d 가 비어 있습니다' } }
    $head = New-Object byte[] 7
    $fs = New-Object IO.FileStream($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try { $n = $fs.Read($head, 0, 7) } finally { $fs.Dispose() }
    if ($n -lt 7 -or [Text.Encoding]::ASCII.GetString($head).ToUpperInvariant() -ne 'HYPER3D') {
        return [pscustomobject]@{ Ok = $false; Reason = '출력 파일이 h3d 가 아닙니다(헤더 HYPER3D 없음)' }
    }
    if ($SourceBytes -gt 0 -and $fi.Length -ge $SourceBytes) {
        return [pscustomobject]@{ Ok = $false; Reason = ("출력 h3d({0})가 원본({1})보다 작지 않습니다 - 압축 효과 없음" -f (Format-EslBytes ([double]$fi.Length)), (Format-EslBytes ([double]$SourceBytes))) }
    }
    return [pscustomobject]@{ Ok = $true; Reason = '' }
}

# hw + esl_h3d_probe.tcl 로 슬림 h3d 에 파트(component)와 subcase 가 보이는지 확인(US-6). 반환 {Ok, Reason, Warnings, Skipped}
function Test-EslSlimProbe([string]$HwExe, [string]$Slim, [int64]$PartId, [string]$PartTitle, [string]$OutDir, [double]$TimeoutMin = 30) {
    $tcl = Join-Path $script:EslSlimLibDir 'esl_h3d_probe.tcl'
    if (-not $HwExe -or -not (Test-Path -LiteralPath $HwExe -PathType Leaf) -or -not (Test-Path -LiteralPath $tcl -PathType Leaf)) {
        return [pscustomobject]@{ Ok = $true; Skipped = $true; Reason = ''; Warnings = @('hw.exe 또는 probe TCL 이 없어 슬림 h3d 검증(slim_verify)을 건너뜁니다') }
    }
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $hwArgs = @('-clientconfig', 'hwpost.dat', '-b', '-tcl', (Format-EslArg $tcl), '-input', (Format-EslArg $Slim), '-output', (Format-EslArg $OutDir))
    $env:ESL_INPUT = $Slim; $env:ESL_OUTPUT = $OutDir; $env:ESL_PART = ''; $env:ESL_CONFIG = ''
    $log = Join-Path $OutDir 'probe_console.log'
    $run = Invoke-EslProcess $HwExe ($hwArgs -join ' ') $OutDir $log (Join-Path $OutDir 'probe_stderr_console.log') $TimeoutMin 'hw 검증'
    $pj = Join-Path $OutDir 'probe.json'
    if (-not (Test-Path -LiteralPath $pj -PathType Leaf)) {
        return [pscustomobject]@{ Ok = $false; Skipped = $false; Reason = "슬림 h3d 검증 실패: probe.json 이 없습니다(hw 종료 코드 $($run.ExitCode)) - $log"; Warnings = @() }
    }
    try { $j = [IO.File]::ReadAllText($pj) | ConvertFrom-Json }
    catch { return [pscustomobject]@{ Ok = $false; Skipped = $false; Reason = "슬림 h3d 검증 실패: probe.json 을 읽지 못했습니다 - $pj"; Warnings = @() } }
    if ($j.ok -ne $true) {
        return [pscustomobject]@{ Ok = $false; Skipped = $false; Reason = ("슬림 h3d 검증 실패: hw 가 h3d 를 열지 못했습니다 ({0}) - {1}" -f [string]$j.error, $pj); Warnings = @() }
    }
    $key = ConvertTo-EslTitleKey $PartTitle 'exact_ci'
    $comp = @(@($j.components) | Where-Object { $_ -and (([string]$_.id -eq [string]$PartId) -or ((ConvertTo-EslTitleKey ([string]$_.name) 'exact_ci') -eq $key)) })
    if ($comp.Count -eq 0) {
        return [pscustomobject]@{ Ok = $false; Skipped = $false; Reason = "슬림 h3d 검증 실패: 파트 $PartId($PartTitle) component 가 슬림 h3d 에 없습니다 (component ID 와 rad part ID 가 다를 수 있음 - 원본으로 올리세요) - $pj"; Warnings = @() }
    }
    if (@($j.subcases).Count -eq 0) {
        return [pscustomobject]@{ Ok = $false; Skipped = $false; Reason = "슬림 h3d 검증 실패: subcase 가 없습니다(결과가 남지 않음) - $pj"; Warnings = @() }
    }
    return [pscustomobject]@{ Ok = $true; Skipped = $false; Reason = ''; Warnings = @() }
}

function Get-EslFreeBytes([string]$Path) {
    try {
        $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path))
        if (-not $root) { return -1 }
        return [int64](New-Object IO.DriveInfo($root)).AvailableFreeSpace
    }
    catch { return -1 }
}

# ---- 슬림 h3d 만들기 -------------------------------------------------------------------------------------

function Get-EslSlimMeta($Src, [string]$SlimPath, $Part, $Cfg, [double]$Sec, $Hv, $Results) {
    $fi = New-Object IO.FileInfo($SlimPath)
    $srcName = $Src.Name
    if ($srcName.Length -gt 255) { $srcName = $srcName.Substring(0, 255) }
    $title = [string]$Part.Title
    if ($title.Length -gt 200) { $title = $title.Substring(0, 200) }
    $res = @($Results | ForEach-Object { [ordered]@{ type = [string]$_.type; layer = $_.layer } })
    $ver = $null
    if ($Hv -and $Hv.Version) { $ver = [string]$Hv.Version }
    return [ordered]@{
        kind = 'h3d_slim'; v = 1
        source_name = $srcName; source_bytes = [int64]$Src.Length
        source_mtime = $Src.LastWriteTimeUtc.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture)
        slim_bytes = [int64]$fi.Length; hvtrans_sec = [Math]::Round($Sec, 1); hvtrans_version = $ver
        cfg = [string]$Cfg; cfg_sha256 = (Get-EslTextSha256 ([string]$Cfg))
        part_id = [int64]$Part.Id; part_title = $title; results = $res; frames = 'all'
        tool_version = (Get-EslToolVersion)
    }
}

function New-EslSlimFail([string]$Reason, [string]$Log = '', [bool]$WantOriginal = $false) {
    return [pscustomobject]@{ Ok = $false; Reason = $Reason; Log = $Log; SlimPath = ''; Meta = $null; Reused = $false; WantOriginal = $WantOriginal }
}

# 원본 h3d + rad -> <work_root>\<stem>\slim\<stem>_slim.h3d. 실패해도 예외 대신 {Ok=$false, Reason, Log}.
#   OutputGuard : 출력 폴더 금지 규칙(h3d 폴더·protected_roots 아래 거부)을 호출자가 넘기는 스크립트블록 param($dir)
function Invoke-EslSlimBuild([string]$H3d, [string]$Rad, [string]$PartSpec, $Settings, [string]$WorkRoot, [string]$HwExe = '', [scriptblock]$OutputGuard = $null) {
    $src = New-Object IO.FileInfo($H3d)
    $stem = [IO.Path]::GetFileNameWithoutExtension($H3d)
    $slimDir = Join-Path (Join-Path $WorkRoot $stem) 'slim'
    $slim = Join-Path $slimDir ($stem + '_slim.h3d')
    $cfgPath = Join-Path $slimDir 'esl_slim.cfg'
    $infoPath = Join-Path $slimDir 'esl_slim.json'
    $log = Join-Path $slimDir 'hvtrans.log'

    $hv = Find-EslHvtrans $Settings.HvtransExe $HwExe
    if (-not $hv.Ok) { return (New-EslSlimFail $hv.Reason) }
    Say "    hvtrans: $($hv.Path)$(if ($hv.Version) { ' (' + $hv.Version + ')' } else { '' })" 'DarkGray'

    # 대상 파트 ID (rad /PART title, 서버 match_parts 규칙)
    $parts = @()
    try { $parts = @(Read-EslRadParts $Rad) } catch { return (New-EslSlimFail "rad 를 읽지 못했습니다: $($_.Exception.Message)") }
    $sel = Select-EslSlimPart $parts $PartSpec
    if (-not $sel.Ok) { return (New-EslSlimFail $sel.Reason '' $sel.WantOriginal) }
    $part = $sel.Part
    $nres = @($Settings.Results).Count
    Say ("==> [slim] 파트 {0}({1}) · 결과 {2}종 · 전 프레임" -f $part.Id, $part.Title, $nres) 'Cyan'

    # 출력 폴더 금지 규칙(만들기 전·후) + 여유 공간
    try {
        if ($OutputGuard) { & $OutputGuard $slimDir }
        New-Item -ItemType Directory -Force -Path $slimDir | Out-Null
        if ($OutputGuard) { & $OutputGuard $slimDir }
    }
    catch { return (New-EslSlimFail $_.Exception.Message) }
    $free = Get-EslFreeBytes $slimDir
    if ($free -ge 0 -and $free -lt ([int64]$Settings.MinFreeGb * 1GB)) {
        return (New-EslSlimFail ("출력 드라이브 여유 공간이 부족합니다: {0} 남음 < slim_min_free_gb {1} GB ({2})" -f (Format-EslBytes ([double]$free)), $Settings.MinFreeGb, $slimDir))
    }

    $variants = @(Get-EslCfgVariants $Settings $part.Id)
    $settingsKey = Get-EslTextSha256 ((($variants | ForEach-Object { $_.Text }) -join '|') + '|' + $part.Id)

    # 재사용: 원본(경로·크기·mtime)·설정·파트가 같고 슬림 파일 크기가 같으면 hvtrans 생략(§4.5)
    if ((Test-Path -LiteralPath $infoPath -PathType Leaf) -and (Test-Path -LiteralPath $slim -PathType Leaf)) {
        try {
            $old = [IO.File]::ReadAllText($infoPath) | ConvertFrom-Json
            $slimLen = (New-Object IO.FileInfo($slim)).Length
            if ([string]$old.source_path -ieq $src.FullName -and [int64]$old.source_bytes -eq $src.Length -and [int64]$old.source_mtime_ticks -eq $src.LastWriteTimeUtc.Ticks `
                    -and [string]$old.settings_key -eq $settingsKey -and [int64]$old.slim_bytes -eq $slimLen) {
                $chk = Test-EslSlimFile $slim $src.Length
                if ($chk.Ok) {
                    $meta = Get-EslSlimMeta $src $slim $part ([string]$old.cfg) ([double]$old.hvtrans_sec) $hv @($old.results)
                    Say ("    기존 슬림 h3d 를 다시 씁니다(원본·설정 같음): {0}" -f $slim) 'DarkGray'
                    return [pscustomobject]@{ Ok = $true; Reason = ''; Log = $log; SlimPath = $slim; Meta = $meta; Reused = $true; WantOriginal = $false }
                }
            }
        }
        catch { }
    }

    # cfg 후보를 순서대로 hvtrans 로 시도
    $argHv = $hv.Path
    $lastReason = ''
    $lastLog = ''
    $n = 0
    foreach ($v in $variants) {
        $n++
        [IO.File]::WriteAllText($cfgPath, $v.Text, (New-Object Text.UTF8Encoding($false)))
        $logN = $(if ($n -eq 1) { $log } else { Join-Path $slimDir ("hvtrans_{0}.log" -f $n) })
        $errN = $(if ($n -eq 1) { Join-Path $slimDir 'hvtrans_stderr.log' } else { Join-Path $slimDir ("hvtrans_stderr_{0}.log" -f $n) })
        if (Test-Path -LiteralPath $slim -PathType Leaf) { [IO.File]::Delete($slim) }       # 이전 시도의 불완전 출력(슬림 폴더 안)
        $line = ('-c {0} {1} {2} -o {3} -zh0' -f (Format-EslArg $cfgPath), (Format-EslArg $H3d), (Format-EslArg $H3d), (Format-EslArg $slim))
        Say ("    hvtrans 시도 {0}/{1}: Pool {2}, 결과 표기 {3}{4}" -f $n, $variants.Count, $v.Pool, $v.Style, $(if ($v.WithPlastic) { '' } else { ', Plastic Strain 제외' })) 'DarkGray'
        $run = Invoke-EslProcess $argHv $line $slimDir $logN $errN $Settings.TimeoutMin 'hvtrans' $slim
        $lastLog = $logN
        if ($run.TimedOut) { return (New-EslSlimFail ("hvtrans 가 제한 시간 {0}분을 넘겨 중단했습니다(slim_timeout_min)" -f $Settings.TimeoutMin) $logN) }
        if ($run.ExitCode -ne 0) {
            $tail = Get-EslLastLines $errN 2
            if (-not $tail) { $tail = Get-EslLastLines $logN 2 }
            $lastReason = "hvtrans 종료 코드 $($run.ExitCode)" + $(if ($tail) { " ($tail)" } else { '' })
            Say "    $lastReason" 'Yellow'
            continue
        }
        $chk = Test-EslSlimFile $slim $src.Length
        if (-not $chk.Ok) { $lastReason = $chk.Reason; Say "    $lastReason" 'Yellow'; continue }
        # 성공: 검증(probe) -> 기록
        if ($Settings.Verify) {
            $pr = Test-EslSlimProbe $HwExe $slim $part.Id ([string]$part.Title) (Join-Path $slimDir 'probe') $Settings.TimeoutMin
            foreach ($w in @($pr.Warnings)) { if ($w) { Say "    [경고] $w" 'Yellow' } }
            if (-not $pr.Ok) { return (New-EslSlimFail $pr.Reason $logN) }
        }
        $sec = $run.Seconds
        $meta = Get-EslSlimMeta $src $slim $part $v.Text $sec $hv $v.Results
        $info = [ordered]@{ source_path = $src.FullName; source_bytes = $src.Length; source_mtime_ticks = $src.LastWriteTimeUtc.Ticks
            settings_key = $settingsKey; part_id = $part.Id; slim_bytes = $meta.slim_bytes; hvtrans_sec = $meta.hvtrans_sec
            cfg = $v.Text; cfg_sha256 = $meta.cfg_sha256; results = @($meta.results); created = (Get-Date).ToString('o') }
        Write-EslTextFile $infoPath ($info | ConvertTo-Json -Depth 6)
        Say ("    {0} -> {1} ({2:N1}%), {3}" -f (Format-EslBytes ([double]$src.Length)), (Format-EslBytes ([double]$meta.slim_bytes)),
            (100.0 * $meta.slim_bytes / [Math]::Max($src.Length, 1)), (Format-EslElapsed $sec)) 'Green'
        return [pscustomobject]@{ Ok = $true; Reason = ''; Log = $logN; SlimPath = $slim; Meta = $meta; Reused = $false; WantOriginal = $false }
    }
    if ($variants.Count -gt 1) { $lastReason = "$lastReason (cfg 후보 $($variants.Count)개 모두 실패)" }
    return (New-EslSlimFail $lastReason $lastLog)
}

# ---- 업로드 계획·실행 --------------------------------------------------------------------------------------

# rad + include (+ h3d 한 개 + 메타) -> 올릴 파일 계획. h3d 는 rel 'h3d/<이름>'.
function New-EslH3dUploadPlan([string]$Rad, [string]$H3dPath, [string]$H3dRel, $Meta) {
    $base = Confirm-EslOutsideIncludes (Get-EslUploadPlan '' $Rad)        # rad 폴더 밖 include 는 Y 확인 시만
    $problems = @($base.Problems)
    if (-not (Test-EslRel $H3dRel)) { $problems += "올릴 수 없는 h3d 이름입니다: $H3dRel (허용되지 않는 문자·형식)" }
    $plan = Add-EslPlanFiles $base @((New-EslPlanFile $H3dRel $H3dPath $Meta))
    $plan.Problems = $problems
    return $plan
}

# 슬림(또는 원본) h3d + rad 를 서버에 올린다. 압축 실패 시 원본 업로드를 묻는다. 성공 $true.
#   Mode : 'slim' | 'original'
function Publish-EslH3d($Ctx, [string]$H3d, [string]$Rad, [string]$Mode, [string]$PartSpec, $Settings, [string]$WorkRoot, [string]$HwExe, [string]$Name, [scriptblock]$OutputGuard = $null) {
    $src = New-Object IO.FileInfo($H3d)
    $useMode = $Mode
    $slimPath = ''; $meta = $null
    if ($useMode -eq 'slim') {
        $b = Invoke-EslSlimBuild $H3d $Rad $PartSpec $Settings $WorkRoot $HwExe $OutputGuard
        if ($b.Ok) { $slimPath = $b.SlimPath; $meta = $b.Meta }
        else {
            Say ("    [압축 실패] " + $b.Reason) 'Red'
            if ($b.Log) { Say ("    로그: " + $b.Log) 'Red' }
            $go = $b.WantOriginal
            if (-not $go) {
                if (-not (Test-EslInteractiveConsole)) {
                    Say '    비대화형 실행: 원본을 올리지 않고 종료합니다(원본으로 올리려면 /original).' 'Red'
                    return $false
                }
                $a = Read-EslInput ("    원본({0})을 올릴까요? [y/N]" -f (Format-EslBytes ([double]$src.Length)))
                $go = [bool]($a -and $a.Trim() -match '^(y|yes|예|ㅇ)$')
            }
            if (-not $go) { Say '    올리기를 취소했습니다.' 'Yellow'; return $false }
            $useMode = 'original'
        }
    }
    if ($useMode -eq 'original') {
        $slimPath = $H3d
        $meta = [ordered]@{ kind = 'h3d_original' }
        Say ("==> [original] 원본 h3d 를 올립니다: {0}" -f (Format-EslBytes ([double]$src.Length))) 'Cyan'
    }
    $leaf = Split-Path -Leaf $slimPath
    $plan = New-EslH3dUploadPlan $Rad $slimPath ('h3d/' + $leaf) $meta
    if (-not (Confirm-EslPlan $plan)) { Say '    올리기를 취소했습니다.' 'Yellow'; return $false }
    $res = Invoke-EslPcUpload $Ctx $plan $Name (Get-EslUploadKey $H3d)
    return [bool]$res.Ok
}
