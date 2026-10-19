# update.ps1 -- esl-platform Windows 원클릭 업데이트·배포 (update.bat 이 호출)
#
#  1) git 최신화: 작업 트리 변경이 있으면 중단, fetch(재시도) -> 브랜치 checkout -> merge --ff-only
#     (reset·force 는 쓰지 않는다. fast-forward 가 안 되면 중단)
#  2) 설정: %LOCALAPPDATA%\esl\esl_deploy.json (없으면 config\esl_deploy.example.json 으로 생성)
#  3) 배포: resources\tcl\*.tcl, README, 실행기를 <deploy_dir>\<git 짧은 해시>\ 로 복사 후
#     <deploy_dir>\current 를 디렉터리 교체로 갱신(실패 시 이전 current 유지). 버전 폴더는 최근 5개만 유지
#  4) 실행 래퍼: <deploy_dir>\current\ESL_probe.bat, ESL_extract.bat (h3d 드래그&드롭)
#  5) 점검표: hw.exe, TCL, work_root 쓰기, git 상태
#
# 삭제는 Remove-DeployTree 한 곳에서만 하며, deploy_dir 아래(링크 아님)인 것만 지운다.
[CmdletBinding()]
param(
    [string]$Branch = '',
    [switch]$SkipGit
)

$ErrorActionPreference = 'Stop'
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
$EslHome = Join-Path $env:LOCALAPPDATA 'esl'
$ConfigPath = Join-Path $EslHome 'esl_deploy.json'
$ExamplePath = Join-Path $RepoRoot 'config\esl_deploy.example.json'
$LogDir = Join-Path $EslHome 'logs'
$LockPath = Join-Path $EslHome 'update.lock'
$KeepVersions = 5
$FetchRetries = 4
$BadChars = '[%!&]'

$script:LogPath = $null
$script:Checks = New-Object System.Collections.ArrayList
$script:DeployDir = $null

function Write-Log([string]$Message) {
    if (-not $script:LogPath) { return }
    try { Add-Content -LiteralPath $script:LogPath -Value ('{0} {1}' -f (Get-Date).ToString('o'), $Message) -Encoding UTF8 } catch { }
}
function Say([string]$Message, [string]$Color = 'Gray') { Write-Host $Message -ForegroundColor $Color; Write-Log $Message }
function Stage([string]$Message) { Write-Host ''; Say "==> $Message" 'Cyan' }
function Add-Check([string]$Item, [string]$Result, [string]$Detail) {
    [void]$script:Checks.Add([pscustomobject]@{ '항목' = $Item; '결과' = $Result; '내용' = $Detail })
    Write-Log "CHECK $Item $Result $Detail"
}

function Expand-ConfigPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $expanded = [Environment]::ExpandEnvironmentVariables($Value.Trim())
    return [IO.Path]::GetFullPath($expanded.Replace('/', '\')).TrimEnd('\')
}
function Test-PathUnder([string]$Child, [string]$Parent) {
    if (-not $Child -or -not $Parent) { return $false }
    $c = [IO.Path]::GetFullPath($Child).TrimEnd('\') + '\'
    $p = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}
function Test-IsLink([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    return [bool]((Get-Item -Force -LiteralPath $Path).Attributes -band [IO.FileAttributes]::ReparsePoint)
}

# ---- git -------------------------------------------------------------------------------------
function Invoke-Git([string[]]$GitArgs) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & git.exe -C $RepoRoot @GitArgs 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $old }
    Write-Log ("git {0} -> {1}" -f ($GitArgs -join ' '), $code)
    foreach ($l in @($out)) { Write-Log "  $l" }
    return [pscustomobject]@{ Code = $code; Output = @($out) }
}
function Invoke-GitChecked([string[]]$GitArgs, [string]$What) {
    $r = Invoke-Git $GitArgs
    if ($r.Code -ne 0) {
        foreach ($l in $r.Output) { Say "    $l" 'Yellow' }
        throw "$What 실패 (git $($GitArgs -join ' '), 종료 코드 $($r.Code))"
    }
    return $r
}

function Update-Repository([string]$WantBranch) {
    Stage 'git 최신화'
    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'git.exe 를 찾을 수 없습니다. Git for Windows 를 설치한 뒤 다시 실행하세요.' }
    [void](Invoke-GitChecked @('rev-parse', '--is-inside-work-tree') '저장소 확인')

    $status = Invoke-GitChecked @('status', '--porcelain', '--untracked-files=no') '작업 트리 확인'
    $dirty = @($status.Output | Where-Object { $_ -and $_.Trim() })
    if ($dirty.Count -gt 0) {
        Say '작업 트리에 커밋되지 않은 변경이 있어 업데이트를 중단합니다(덮어쓰지 않음):' 'Red'
        foreach ($l in $dirty) { Say "    $l" 'Yellow' }
        Add-Check 'git' 'FAIL' "변경 파일 $($dirty.Count)개 - 되돌리거나 다른 곳에 보관한 뒤 다시 실행"
        throw '작업 트리 변경 있음'
    }

    $current = ((Invoke-GitChecked @('rev-parse', '--abbrev-ref', 'HEAD') '현재 브랜치 확인').Output | Select-Object -First 1).Trim()
    $target = if ($WantBranch) { $WantBranch } else { $current }
    if (-not $target -or $target -eq 'HEAD') { throw '현재 브랜치가 없습니다(detached HEAD). 설정 branch 를 지정하세요.' }
    if ($target -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$') { throw "브랜치 이름이 올바르지 않습니다: $target" }
    Say "    브랜치: $target (현재 $current)"

    $delay = 2
    for ($i = 0; ; $i++) {
        $r = Invoke-Git @('fetch', 'origin', $target)
        if ($r.Code -eq 0) { break }
        if ($i -ge $FetchRetries) {
            foreach ($l in $r.Output) { Say "    $l" 'Yellow' }
            throw "git fetch 실패($($FetchRetries)회 재시도). 네트워크·프록시·저장소 권한을 확인하세요."
        }
        Say ("    fetch 실패, {0}초 뒤 재시도 ({1}/{2})" -f $delay, ($i + 1), $FetchRetries) 'Yellow'
        Start-Sleep -Seconds $delay
        $delay *= 2
    }

    if ($target -ne $current) {
        $local = Invoke-Git @('show-ref', '--verify', '--quiet', "refs/heads/$target")
        if ($local.Code -eq 0) { [void](Invoke-GitChecked @('checkout', $target) 'checkout') }
        else { [void](Invoke-GitChecked @('checkout', '-b', $target, '--track', "origin/$target") 'checkout') }
        Say "    브랜치 전환: $current -> $target"
    }
    $before = ((Invoke-GitChecked @('rev-parse', '--short', 'HEAD') 'HEAD 확인').Output | Select-Object -First 1).Trim()
    $m = Invoke-Git @('merge', '--ff-only', "origin/$target")
    if ($m.Code -ne 0) {
        foreach ($l in $m.Output) { Say "    $l" 'Yellow' }
        Add-Check 'git' 'FAIL' "origin/$target 로 fast-forward 불가 (로컬 커밋 있음)"
        throw "fast-forward 병합이 불가능합니다. 로컬 커밋을 정리한 뒤 다시 실행하세요(자동 reset/force 는 하지 않음)."
    }
    $after = ((Invoke-GitChecked @('rev-parse', '--short', 'HEAD') 'HEAD 확인').Output | Select-Object -First 1).Trim()
    if ($before -eq $after) { Say "    이미 최신: $after" 'Green' } else { Say "    갱신: $before -> $after" 'Green' }
    Add-Check 'git' 'OK' "$target @ $after"
}

# ---- 설정 ------------------------------------------------------------------------------------
function Get-DeployConfig {
    Stage '설정 읽기'
    if (-not (Test-Path -LiteralPath $ExamplePath -PathType Leaf)) { throw "예시 설정이 없습니다: $ExamplePath" }
    $example = Get-Content -Raw -Encoding UTF8 -LiteralPath $ExamplePath | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        New-Item -ItemType Directory -Force -Path $EslHome | Out-Null
        [IO.File]::WriteAllText($ConfigPath, [IO.File]::ReadAllText($ExamplePath), (New-Object Text.UTF8Encoding($false)))
        Say "    설정 파일을 기본값으로 만들었습니다: $ConfigPath" 'Yellow'
        Say '    hw_exe(HyperWorks 경로), work_root(출력 폴더, 공유 SPDM 폴더 금지), protected_roots 를 확인하세요.' 'Yellow'
    }
    else { Say "    설정: $ConfigPath" }
    try { $cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $ConfigPath | ConvertFrom-Json }
    catch { throw "설정 파일 JSON 오류: $ConfigPath ($($_.Exception.Message))" }
    foreach ($p in $example.PSObject.Properties) {
        if (-not ($cfg.PSObject.Properties.Name -contains $p.Name)) {
            Say "    설정에 '$($p.Name)' 없음 -> 예시 기본값 사용" 'Yellow'
            $cfg | Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value
        }
    }
    return $cfg
}

# ---- 배포 ------------------------------------------------------------------------------------
function Assert-InsideDeployDir([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $script:DeployDir) { throw 'deploy_dir 미정' }
    if ($full -ieq $script:DeployDir -or -not (Test-PathUnder $full $script:DeployDir)) {
        throw "deploy_dir 밖 경로는 지우지 않습니다: $full"
    }
    return $full
}

# 링크를 따라가지 않고 파일·폴더를 하나씩 지운다(deploy_dir 아래만). 링크를 만나면 중단.
function Remove-DeployTree([string]$Path) {
    $full = Assert-InsideDeployDir $Path
    if (-not (Test-Path -LiteralPath $full)) { return }
    if (Test-IsLink $full) { throw "링크(junction/symlink)는 지우지 않습니다: $full" }
    foreach ($f in [IO.Directory]::GetFiles($full)) {
        $fi = New-Object IO.FileInfo($f)
        if ($fi.Attributes -band [IO.FileAttributes]::ReadOnly) { $fi.Attributes = $fi.Attributes -bxor [IO.FileAttributes]::ReadOnly }
        [IO.File]::Delete($f)
    }
    foreach ($d in [IO.Directory]::GetDirectories($full)) { Remove-DeployTree $d }
    [IO.Directory]::Delete($full, $false)
}

function New-Wrapper([string]$Dir, [string]$Name, [string]$Mode) {
    $usage = if ($Mode -eq 'probe') { 'ESL_probe.bat <h3d> [<h3d> ...] [<part>]' } else { 'ESL_extract.bat <h3d> [<h3d> ...] [<part>]   (part default: setting default_part)' }
    $lines = @(
        '@echo off',
        'setlocal DisableDelayedExpansion',
        "rem $usage",
        'rem Drag and drop h3d file(s) onto this file. Output: <work_root>\<h3d name>\' + $(if ($Mode -eq 'probe') { 'probe' } else { 'csv' }),
        'rem Generated by scripts\windows\update.ps1 - do not edit (overwritten on update).',
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0esl_run.ps1`" -Mode $Mode %*",
        'echo.',
        'pause',
        'exit /b 0'
    )
    [IO.File]::WriteAllText((Join-Path $Dir $Name), (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
}

function Publish-Deployment($Cfg, [string]$Version) {
    Stage "배포 (버전 $Version)"
    $tclDir = Join-Path $RepoRoot 'resources\tcl'
    $sources = @(Get-ChildItem -LiteralPath $tclDir -Filter '*.tcl' -File) + @(Get-Item -LiteralPath (Join-Path $tclDir 'README.md'))
    $runner = Join-Path $PSScriptRoot 'esl_run.ps1'
    if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "실행기 없음: $runner" }

    New-Item -ItemType Directory -Force -Path $script:DeployDir | Out-Null
    if (Test-IsLink $script:DeployDir) { throw "deploy_dir 가 링크입니다. 실제 폴더를 지정하세요: $($script:DeployDir)" }
    $verDir = Join-Path $script:DeployDir $Version
    if (Test-Path -LiteralPath $verDir) { Remove-DeployTree $verDir }
    New-Item -ItemType Directory -Force -Path $verDir | Out-Null
    foreach ($s in $sources) { Copy-Item -LiteralPath $s.FullName -Destination $verDir -Force; Say "    복사: $($s.Name)" }
    Copy-Item -LiteralPath $runner -Destination $verDir -Force
    New-Wrapper $verDir 'ESL_probe.bat' 'probe'
    New-Wrapper $verDir 'ESL_extract.bat' 'extract'
    [IO.File]::WriteAllText((Join-Path $verDir 'VERSION.txt'), ("version={0}`r`nrepo={1}`r`ndeployed={2}`r`n" -f $Version, $RepoRoot, (Get-Date).ToString('s')), (New-Object Text.UTF8Encoding($false)))
    (Get-Item -LiteralPath $verDir).LastWriteTime = Get-Date

    # current 교체: current.new 준비 -> current 를 current.old.<ts> 로 -> current.new 를 current 로
    $current = Join-Path $script:DeployDir 'current'
    $staging = Join-Path $script:DeployDir 'current.new'
    $oldDir = Join-Path $script:DeployDir ('current.old.' + (Get-Date).ToString('yyyyMMdd_HHmmss'))
    if (Test-Path -LiteralPath $staging) { Remove-DeployTree $staging }
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    foreach ($f in [IO.Directory]::GetFiles($verDir)) { Copy-Item -LiteralPath $f -Destination $staging -Force }
    $hadCurrent = Test-Path -LiteralPath $current
    if ($hadCurrent) {
        if (Test-IsLink $current) { throw "current 가 링크입니다: $current" }
        try { [IO.Directory]::Move($current, $oldDir) }
        catch {
            Remove-DeployTree $staging
            throw "current 를 교체하지 못했습니다(열린 창·탐색기·실행 중인 ESL 을 닫고 다시 실행). 이전 버전은 그대로입니다: $($_.Exception.Message)"
        }
    }
    try { [IO.Directory]::Move($staging, $current) }
    catch {
        if ($hadCurrent) { [IO.Directory]::Move($oldDir, $current) }
        throw "current 교체 실패, 이전 버전으로 되돌렸습니다: $($_.Exception.Message)"
    }
    if ($hadCurrent) {
        try { Remove-DeployTree $oldDir } catch { Say "    이전 current 정리 실패(무시): $oldDir" 'Yellow' }
    }
    Say "    current -> $Version" 'Green'

    # 오래된 버전 정리: 최근 $KeepVersions 개 초과분만
    $versions = @(Get-ChildItem -LiteralPath $script:DeployDir -Directory |
        Where-Object { $_.Name -match '^[0-9a-f]{7,40}$' -and $_.Name -ne $Version } |
        Sort-Object LastWriteTime -Descending)
    $excess = @($versions | Select-Object -Skip ($KeepVersions - 1))
    if ($excess.Count -gt 0) {
        Say ("    오래된 버전 정리 대상: {0}" -f (($excess | ForEach-Object { $_.Name }) -join ', '))
        foreach ($d in $excess) {
            try { Remove-DeployTree $d.FullName; Write-Log "REMOVED $($d.FullName)" }
            catch { Say "    정리 실패(무시): $($d.FullName) - $($_.Exception.Message)" 'Yellow' }
        }
    }
    return $current
}

# ---- 점검 ------------------------------------------------------------------------------------
function Test-Environment($Cfg, [string]$CurrentDir, [string]$WorkRoot, [string[]]$Protected) {
    Stage '점검'
    $hw = Expand-ConfigPath ([string]$Cfg.hw_exe)
    if ($hw -and (Test-Path -LiteralPath $hw -PathType Leaf)) { Add-Check 'hw.exe' 'OK' $hw }
    else { Add-Check 'hw.exe' 'FAIL' "없음: '$hw' -> 설정 hw_exe 수정" }

    foreach ($n in @('esl_h3d_probe.tcl', 'esl_h3d_extract.tcl', 'esl_run.ps1', 'ESL_probe.bat', 'ESL_extract.bat')) {
        $p = Join-Path $CurrentDir $n
        if (Test-Path -LiteralPath $p -PathType Leaf) { Add-Check $n 'OK' $p } else { Add-Check $n 'FAIL' "없음: $p" }
    }

    $wrOk = $true
    if (-not $WorkRoot) { Add-Check 'work_root' 'FAIL' '설정 work_root 비어 있음'; $wrOk = $false }
    elseif ($WorkRoot -match $BadChars) { Add-Check 'work_root' 'FAIL' "%, !, & 문자 사용 불가: $WorkRoot"; $wrOk = $false }
    else {
        foreach ($r in $Protected) {
            if ($r -and ((Test-PathUnder $WorkRoot $r) -or (Test-PathUnder $r $WorkRoot))) {
                Add-Check 'work_root' 'FAIL' "보호 폴더와 겹침: $WorkRoot / $r"; $wrOk = $false
            }
        }
    }
    if ($wrOk) {
        try {
            New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
            $probe = Join-Path $WorkRoot ('.esl_write_test_' + [Guid]::NewGuid().ToString('N'))
            [IO.File]::WriteAllText($probe, 'ok')
            [IO.File]::Delete($probe)
            Add-Check 'work_root' 'OK' "쓰기 가능: $WorkRoot"
        }
        catch { Add-Check 'work_root' 'FAIL' "쓰기 불가: $WorkRoot ($($_.Exception.Message))" }
    }
}

function Show-Checks {
    if ($script:Checks.Count -eq 0) { return }
    Write-Host ''
    Write-Host '==> 점검 결과' -ForegroundColor Cyan
    $table = ($script:Checks | Format-Table -AutoSize -Wrap | Out-String).TrimEnd()
    Write-Host $table
    Write-Log $table
}

# ---- main ------------------------------------------------------------------------------------
$lockStream = $null
$exitCode = 0
try {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $script:LogPath = Join-Path $LogDir ('update_{0}.log' -f (Get-Date).ToString('yyyyMMdd_HHmmss'))
    try {
        $lockStream = New-Object IO.FileStream($LockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None, 1, [IO.FileOptions]::DeleteOnClose)
    }
    catch { throw "다른 update 가 실행 중입니다(잠금: $LockPath). 끝난 뒤 다시 실행하세요." }
    Say "esl-platform 업데이트  저장소: $RepoRoot"
    Say "로그: $($script:LogPath)"

    $cfg = Get-DeployConfig
    $script:DeployDir = Expand-ConfigPath ([string]$cfg.deploy_dir)
    $workRoot = Expand-ConfigPath ([string]$cfg.work_root)
    $protected = @(@($cfg.protected_roots) | Where-Object { $_ } | ForEach-Object { Expand-ConfigPath ([string]$_) })
    if (-not $script:DeployDir) { throw "설정 deploy_dir 가 비어 있습니다: $ConfigPath" }
    if ($script:DeployDir -match $BadChars) { throw "deploy_dir 에 %, !, & 문자는 쓸 수 없습니다: $($script:DeployDir)" }
    if ($script:DeployDir -ieq ([IO.Path]::GetPathRoot($script:DeployDir)).TrimEnd('\')) { throw "deploy_dir 로 드라이브 루트는 쓸 수 없습니다: $($script:DeployDir)" }
    if ((Test-PathUnder $script:DeployDir $RepoRoot) -or (Test-PathUnder $RepoRoot $script:DeployDir)) { throw "deploy_dir 가 저장소 폴더와 겹칩니다: $($script:DeployDir)" }
    foreach ($r in $protected) { if (Test-PathUnder $script:DeployDir $r) { throw "deploy_dir 가 보호 폴더 아래입니다: $($script:DeployDir)" } }

    $want = if ($Branch) { $Branch } else { [string]$cfg.branch }
    if ($SkipGit) { Add-Check 'git' 'WARN' '-SkipGit: git 최신화 생략' } else { Update-Repository $want }

    $version = ((Invoke-GitChecked @('rev-parse', '--short', 'HEAD') '버전 확인').Output | Select-Object -First 1).Trim()
    $currentDir = Publish-Deployment $cfg $version
    Add-Check 'deploy' 'OK' "$currentDir ($version)"
    Test-Environment $cfg $currentDir $workRoot $protected

    Show-Checks
    $failed = @($script:Checks | Where-Object { $_.'결과' -eq 'FAIL' })
    Write-Host ''
    Say '사용법:' 'Cyan'
    Say "  1) 탐색기에서 이 폴더를 여세요: $currentDir"
    Say '  2) h3d 파일을 ESL_probe.bat 위로 끌어다 놓기 -> probe.json (파트 이름·결과 유형 확인)'
    Say "  3) h3d 파일을 ESL_extract.bat 위로 끌어다 놓기 -> CSV (파트 기본값 '$($cfg.default_part)', 다른 파트: ESL_extract.bat <h3d> <part>)"
    Say "  출력: $workRoot\<h3d 이름>\probe | csv      설정: $ConfigPath"
    if ($failed.Count -gt 0) {
        Say ("점검 실패 {0}건 - 위 표의 FAIL 항목을 설정 파일에서 고친 뒤 update.bat 을 다시 실행하세요." -f $failed.Count) 'Red'
        $exitCode = 1
    }
    else { Say '업데이트 완료.' 'Green' }
}
catch {
    Show-Checks
    Say ("[오류] " + $_.Exception.Message) 'Red'
    if ($script:LogPath) { Say "로그: $($script:LogPath)" 'Yellow' }
    $exitCode = 1
}
finally {
    if ($lockStream) { $lockStream.Dispose() }
}
exit $exitCode
