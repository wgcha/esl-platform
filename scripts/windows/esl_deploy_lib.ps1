# esl_deploy_lib.ps1 -- update.ps1 이 dot-source 하는 배포 함수 모음
#
# 배포 구조 (deploy_dir 기본 %LOCALAPPDATA%\esl\app):
#   versions\<git 해시>\     TCL, esl_run.ps1, esl_upload_lib.ps1, esl_slim_lib.ps1, README.md, VERSION.txt  (버전마다 새 폴더, 기존 폴더는 고치지 않음)
#   current_version.txt      활성 버전 이름 한 줄 (임시 파일을 쓴 뒤 파일 단위 교체, 실패 시 재시도)
#   current\                 사용자가 여는 고정 폴더: 얇은 런처 ESL_probe.bat, ESL_extract.bat, ESL_upload.bat, esl_launch.ps1 만
# 폴더 rename 을 하지 않으므로 탐색기·명령창·실행 중인 hw 가 current 나 versions 폴더를 잡고 있어도 업데이트된다.
#
# Windows 전용 cmdlet 을 쓰지 않는다(Linux pwsh 로 tests/test_windows_scripts.py 가 직접 실행해 시험).
# PowerShell 5.1 호환 문법만 쓴다.

# 배포 산출물: *.tcl, *.bat, *.ps1, README*, VERSION.txt (+ TCL 이 쓰는 esl_*_fallback.json 진단 파일).
# 그 밖의 파일·하위 폴더(사용자가 복사해 둔 h3d 등)는 지우거나 옮기지 않는다.
$DeployFilePattern = '^(?:[^\\/]+\.(?:tcl|bat|ps1)|README(?:\.md|\.txt)?|VERSION\.txt|esl_[a-z_]+_fallback\.json)$'
# versions 아래 폴더 이름: git 짧은 해시, 같은 해시에 내용이 다르면 -2, -3 ...
$VersionNamePattern = '^[0-9a-f]{7,40}(?:-[0-9]{1,2})?$'
# 예전 구조(current 폴더 교체 방식)가 deploy_dir 바로 아래 남긴 폴더
$LegacyDirPattern = '^(?:[0-9a-f]{7,40}|current\.new|current\.old\.[0-9]{8}_[0-9]{6})$'
$LauncherNames = @('ESL_probe.bat', 'ESL_extract.bat', 'ESL_upload.bat', 'esl_launch.ps1')
$PointerName = 'current_version.txt'

# Child 가 Parent 와 같거나 그 아래인지 (대소문자 무시, 구분자 \ / 모두 허용)
function Test-PathUnder([string]$Child, [string]$Parent) {
    if (-not $Child -or -not $Parent) { return $false }
    $c = ([IO.Path]::GetFullPath($Child).Replace('/', '\')).TrimEnd('\') + '\'
    $p = ([IO.Path]::GetFullPath($Parent).Replace('/', '\')).TrimEnd('\') + '\'
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

function Test-IsLink([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    return [bool]((Get-Item -Force -LiteralPath $Path).Attributes -band [IO.FileAttributes]::ReparsePoint)
}

function Test-VersionName([string]$Name) {
    if (-not $Name) { return $false }
    return [bool]($Name -cmatch $VersionNamePattern)
}

# 배포 산출물이 아닌 항목(하위 폴더 포함)의 전체 경로
function Get-ForeignFiles([string]$Dir) {
    if (-not (Test-Path -LiteralPath $Dir -PathType Container)) { return @() }
    $out = @()
    foreach ($e in @(Get-ChildItem -Force -LiteralPath $Dir)) {
        if ($e.PSIsContainer -or ($e.Name -notmatch $DeployFilePattern)) { $out += $e.FullName }
    }
    return $out
}

function Assert-InsideDeployDir([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\').TrimEnd('/')
    if (-not $script:DeployDir) { throw 'deploy_dir 미정' }
    $root = [IO.Path]::GetFullPath($script:DeployDir).TrimEnd('\').TrimEnd('/')
    if ($full -ieq $root -or -not (Test-PathUnder $full $root)) {
        throw "deploy_dir 밖 경로는 지우지 않습니다: $full"
    }
    return $full
}

# 링크를 따라가지 않고 파일·폴더를 하나씩 지운다(deploy_dir 아래만). 링크·사용자 파일이 있으면 아무것도 지우지 않고 throw.
function Remove-DeployTree([string]$Path) {
    $full = Assert-InsideDeployDir $Path
    if (-not (Test-Path -LiteralPath $full)) { return }
    if (Test-IsLink $full) { throw "링크(junction/symlink)는 지우지 않습니다: $full" }
    $foreign = @(Get-ForeignFiles $full)
    if ($foreign.Count -gt 0) { throw "배포 산출물이 아닌 파일 $($foreign.Count)개가 있어 지우지 않습니다: $($foreign -join ', ')" }
    foreach ($f in [IO.Directory]::GetFiles($full)) {
        $fi = New-Object IO.FileInfo($f)
        if ($fi.Attributes -band [IO.FileAttributes]::ReadOnly) { $fi.Attributes = $fi.Attributes -bxor [IO.FileAttributes]::ReadOnly }
        [IO.File]::Delete($f)
    }
    [IO.Directory]::Delete($full, $false)
}

# deploy_dir 아래 배포 산출물 파일 하나만 지운다(링크·사용자 파일·폴더는 거부)
function Remove-DeployFile([string]$Path) {
    $full = Assert-InsideDeployDir $Path
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { return }
    if (Test-IsLink $full) { throw "링크는 지우지 않습니다: $full" }
    if ((Split-Path -Leaf $full) -notmatch $DeployFilePattern) { throw "배포 산출물이 아니어서 지우지 않습니다: $full" }
    [IO.File]::Delete($full)
}

# ---- 활성 버전 포인터 -------------------------------------------------------------------------

function Read-CurrentVersion([string]$DeployDir) {
    $p = Join-Path $DeployDir $PointerName
    for ($i = 0; $i -lt 3; $i++) {
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { return '' }
        try {
            $v = ([IO.File]::ReadAllText($p)).Trim()
            if (Test-VersionName $v) { return $v }
            return ''
        }
        catch { Start-Sleep -Milliseconds 200 }
    }
    return ''
}

# 임시 파일에 쓴 뒤 파일 단위로 교체(File.Replace, 없으면 Move). 잠겨 있으면 $Retries 번까지 재시도.
# 성공하면 시도 횟수를 돌려주고, 끝내 실패하면 임시 파일을 지우고 throw(이전 포인터 그대로).
function Set-CurrentVersion([string]$DeployDir, [string]$Version, [int]$Retries = 3, [int]$DelayMs = 500) {
    if (-not (Test-VersionName $Version)) { throw "버전 이름이 올바르지 않습니다: $Version" }
    $dst = Join-Path $DeployDir $PointerName
    $tmp = Join-Path $DeployDir ($PointerName + '.tmp-' + [Guid]::NewGuid().ToString('N'))
    [IO.File]::WriteAllText($tmp, $Version + "`r`n", [Text.Encoding]::ASCII)
    $lastErr = ''
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            if ([IO.File]::Exists($dst)) { [IO.File]::Replace($tmp, $dst, [NullString]::Value) }
            else { [IO.File]::Move($tmp, $dst) }
            return $i
        }
        catch {
            $lastErr = $_.Exception.Message
            if ($i -lt $Retries) { Start-Sleep -Milliseconds $DelayMs }
        }
    }
    try { if ([IO.File]::Exists($tmp)) { [IO.File]::Delete($tmp) } } catch { }
    throw "$PointerName 을(를) 교체하지 못했습니다($Retries 회 시도, 이전 버전 그대로): $lastErr"
}

# ---- 버전 폴더 --------------------------------------------------------------------------------

function Test-SameBytes([byte[]]$A, [byte[]]$B) {
    if ($null -eq $A -or $null -eq $B) { return $false }
    if ($A.Length -ne $B.Length) { return $false }
    return ([Convert]::ToBase64String($A) -ceq [Convert]::ToBase64String($B))
}

# Dir 안에 Sources 의 모든 파일이 같은 이름·같은 내용으로 있는지
function Test-SameFiles([string]$Dir, [string[]]$Sources) {
    foreach ($s in $Sources) {
        $t = Join-Path $Dir (Split-Path -Leaf $s)
        if (-not (Test-Path -LiteralPath $t -PathType Leaf)) { return $false }
        if (-not (Test-SameBytes ([IO.File]::ReadAllBytes($s)) ([IO.File]::ReadAllBytes($t)))) { return $false }
    }
    return $true
}

# 새 버전을 쓸 versions 아래 폴더 이름을 고른다. 기존 폴더는 절대 고치지 않는다:
#   같은 내용이 이미 있으면 그 폴더 재사용(Reuse), 없으면 비어 있는 이름(<해시>, <해시>-2, ...)
function Find-VersionSlot([string]$VersionsRoot, [string]$Version, [string[]]$Sources) {
    for ($n = 1; $n -le 20; $n++) {
        $name = if ($n -eq 1) { $Version } else { "$Version-$n" }
        $dir = Join-Path $VersionsRoot $name
        if (-not (Test-Path -LiteralPath $dir)) { return [pscustomobject]@{ Name = $name; Path = $dir; Reuse = $false } }
        if ((-not (Test-IsLink $dir)) -and (Test-Path -LiteralPath $dir -PathType Container) -and (Test-SameFiles $dir $Sources)) {
            return [pscustomobject]@{ Name = $name; Path = $dir; Reuse = $true }
        }
    }
    throw "versions 폴더에 $Version 이름의 폴더가 너무 많습니다: $VersionsRoot"
}

# 지울 버전 이름: 최근(LastWriteTime) $Keep 개와 활성 버전은 남긴다. $Versions 는 Name, LastWriteTime 속성 객체.
function Select-VersionsToPrune($Versions, [string]$Active, [int]$Keep) {
    $sorted = @(@($Versions) | Where-Object { $_ -and (Test-VersionName $_.Name) } |
        Sort-Object -Property @{ Expression = 'LastWriteTime'; Descending = $true }, @{ Expression = 'Name'; Descending = $false })
    $out = @()
    for ($i = 0; $i -lt $sorted.Count; $i++) {
        $name = $sorted[$i].Name
        if ($i -lt $Keep -or $name -ceq $Active) { continue }
        $out += $name
    }
    return $out
}

# ---- 런처·예전 구조 이전 ----------------------------------------------------------------------

# current\ESL_*.bat 내용(ASCII, CRLF). 버전과 무관: esl_launch.ps1 이 실행 때 current_version.txt 를 읽는다.
function Get-LauncherBat([string]$Mode) {
    if ($Mode -eq 'probe') {
        $usage = 'ESL_probe.bat <h3d> [<h3d> ...] [<part>]'
        $what = 'Drag and drop h3d file(s) onto this file. Output: <work_root>\<h3d name>\probe'
    }
    elseif ($Mode -eq 'upload') {
        $usage = 'ESL_upload.bat <results folder> [<rad>]  or  <h3d> <rad> [<part>] [/original|/slim]   (upload only, no extraction; resumes an interrupted upload)'
        $what = 'Drag and drop the csv folder made by ESL_extract.bat (or an h3d) and the rad file onto this file. Server: setting server_url'
    }
    else {
        $usage = 'ESL_extract.bat <h3d> [<h3d> ...] [<rad>] [<part>] [/original|/slim|/pcextract]   (part default: setting default_part)'
        $what = 'Drag and drop h3d (+ rad) file(s) onto this file. Default = slim h3d via hvtrans (asks for 10 s: Enter=slim / O=original / P=PC extract), upload to server_url. Output: <work_root>\<h3d name>\slim or \csv'
    }
    $lines = @(
        '@echo off',
        'setlocal DisableDelayedExpansion',
        "rem $usage",
        "rem $what",
        'rem Launcher: runs ..\versions\<version>\esl_run.ps1 named in ..\current_version.txt (see esl_launch.ps1).',
        'rem Generated by scripts\windows\update.ps1 - do not edit (overwritten on update).',
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0esl_launch.ps1`" -Mode $Mode %*",
        'echo.',
        'pause',
        'exit /b 0'
    )
    return (($lines -join "`r`n") + "`r`n")
}

# 내용이 다를 때만 파일 단위로 덮어쓴다. 결과: 'same' | 'written' | 'locked: <메시지>' | 'link'
function Update-LauncherFile([string]$Path, [byte[]]$Bytes) {
    if (Test-IsLink $Path) { return 'link' }
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        try { if (Test-SameBytes ([IO.File]::ReadAllBytes($Path)) $Bytes) { return 'same' } } catch { }
    }
    try { [IO.File]::WriteAllBytes($Path, $Bytes); return 'written' }
    catch { return ('locked: ' + $_.Exception.Message) }
}

# 예전 구조에서 current 에 직접 있던 배포 산출물(런처 제외, 최상위 파일만). 사용자 파일·폴더·링크는 포함하지 않는다.
function Get-LegacyArtifacts([string]$CurrentDir) {
    if (-not (Test-Path -LiteralPath $CurrentDir -PathType Container)) { return @() }
    $out = @()
    foreach ($e in @(Get-ChildItem -Force -LiteralPath $CurrentDir)) {
        if ($e.PSIsContainer) { continue }
        if ($e.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        if ($e.Name -notmatch $DeployFilePattern) { continue }
        if ($LauncherNames -contains $e.Name) { continue }
        $out += $e.FullName
    }
    return $out
}

function Test-LegacyLayout([string]$CurrentDir) {
    return (@(Get-LegacyArtifacts $CurrentDir).Count -gt 0)
}

# 예전 구조가 deploy_dir 바로 아래 남긴 폴더(<해시>, current.new, current.old.<시각>)
function Get-LegacyDeployDirs([string]$DeployDir) {
    if (-not (Test-Path -LiteralPath $DeployDir -PathType Container)) { return @() }
    return @(Get-ChildItem -Force -LiteralPath $DeployDir -Directory | Where-Object { $_.Name -cmatch $LegacyDirPattern } | ForEach-Object { $_.FullName })
}
