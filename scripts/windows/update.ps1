# update.ps1 -- esl-platform Windows 원클릭 업데이트·배포 (update.bat 이 호출)
#
#  1) git 최신화: 작업 트리 변경이 있으면 중단, fetch(재시도) -> 브랜치 checkout -> merge --ff-only
#     (reset·force 는 쓰지 않는다. fast-forward 가 안 되면 중단)
#  2) 설정: %LOCALAPPDATA%\esl\esl_deploy.json (없으면 config\esl_deploy.example.json 으로 생성)
#  3) 배포 (폴더 rename 없음 - 탐색기·명령창·실행 중인 hw 가 폴더를 잡고 있어도 됨):
#     resources\tcl\*.tcl, README, esl_run.ps1 -> <deploy_dir>\versions\<git 짧은 해시>\ (새 폴더, 같은 내용이면 재사용)
#     활성 버전 = <deploy_dir>\current_version.txt (임시 파일 작성 후 파일 단위 교체, 3회 재시도)
#  4) 런처: <deploy_dir>\current\ESL_probe.bat, ESL_extract.bat, esl_launch.ps1 (버전 무관, 바뀐 경우만 덮어쓰기)
#     예전 구조(current 에 TCL·esl_run.ps1 이 직접 있음)는 그 배포 산출물만 파일 단위로 정리(사용자 파일은 그대로)
#     오래된 versions 는 최근 5개 + 활성 버전만 남기고 정리(잠겼거나 사용자 파일이 있으면 건너뜀)
#  5) 점검표: hw.exe, 활성 버전, TCL, 런처, work_root 쓰기, git 상태
#
# 삭제는 esl_deploy_lib.ps1 의 Remove-DeployTree / Remove-DeployFile 에서만 하며, deploy_dir 아래(링크 아님)의
# 배포 산출물만 지운다. 사용자 파일(배포 산출물 이외)이 있는 폴더는 지우지 않는다.
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
# 배포 함수(Test-PathUnder, Remove-DeployTree, 포인터 교체, 버전 정리 등): Linux pwsh 로도 시험하는 공용 파일
. (Join-Path $PSScriptRoot 'esl_deploy_lib.ps1')

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
# 폴더 rename 없음: 새 버전은 versions\<해시>\ 에 쓰고, 활성 버전은 current_version.txt 파일 하나만 교체한다.
# current\ 에는 버전과 무관한 런처만 둔다(내용이 바뀐 경우에만 파일 단위 덮어쓰기, 잠겨 있으면 경고).

function Publish-Deployment($Cfg, [string]$Version) {
    Stage "배포 (버전 $Version)"
    $tclDir = Join-Path $RepoRoot 'resources\tcl'
    $runner = Join-Path $PSScriptRoot 'esl_run.ps1'
    $launchPs1 = Join-Path $PSScriptRoot 'esl_launch.ps1'
    foreach ($f in @($runner, $launchPs1)) { if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { throw "실행기 없음: $f" } }
    $sources = @(@(Get-ChildItem -LiteralPath $tclDir -Filter '*.tcl' -File | ForEach-Object { $_.FullName }) +
        @((Join-Path $tclDir 'README.md'), $runner))

    New-Item -ItemType Directory -Force -Path $script:DeployDir | Out-Null
    if (Test-IsLink $script:DeployDir) { throw "deploy_dir 가 링크입니다. 실제 폴더를 지정하세요: $($script:DeployDir)" }
    $versionsRoot = Join-Path $script:DeployDir 'versions'
    $currentDir = Join-Path $script:DeployDir 'current'
    foreach ($d in @($versionsRoot, $currentDir)) {
        if (Test-IsLink $d) { throw "링크(junction/symlink)는 쓰지 않습니다. 지우고 다시 실행하세요: $d" }
        New-Item -ItemType Directory -Force -Path $d | Out-Null
    }
    $previous = Read-CurrentVersion $script:DeployDir

    # 1) 버전 폴더: 같은 내용이 있으면 재사용, 없으면 새 폴더에 쓴다(기존 폴더는 고치지 않음)
    $slot = Find-VersionSlot $versionsRoot $Version $sources
    if ($slot.Reuse) {
        Say "    versions\$($slot.Name) 재사용(내용 같음)"
    }
    else {
        New-Item -ItemType Directory -Force -Path $slot.Path | Out-Null
        foreach ($s in $sources) { Copy-Item -LiteralPath $s -Destination $slot.Path -Force; Say "    복사: $(Split-Path -Leaf $s)" }
        [IO.File]::WriteAllText((Join-Path $slot.Path 'VERSION.txt'), ("version={0}`r`nrepo={1}`r`ndeployed={2}`r`n" -f $slot.Name, $RepoRoot, (Get-Date).ToString('s')), (New-Object Text.UTF8Encoding($false)))
        Say "    versions\$($slot.Name) 작성" 'Green'
    }
    (Get-Item -LiteralPath $slot.Path).LastWriteTime = Get-Date   # 정리 때 최근 버전으로 남게

    # 2) 활성 버전 포인터 교체(임시 파일 -> 파일 단위 교체, 3회 재시도). 실패하면 이전 버전 그대로 throw.
    if ($previous -ceq $slot.Name) { Say "    활성 버전 그대로: $($slot.Name)" 'Green' }
    else {
        $tries = Set-CurrentVersion $script:DeployDir $slot.Name 3 1000
        Say ("    활성 버전: {0} -> {1}{2}" -f $(if ($previous) { $previous } else { '(없음)' }), $slot.Name, $(if ($tries -gt 1) { " ($tries 회째 성공)" } else { '' })) 'Green'
    }
    Write-Log "POINTER $($slot.Name)"

    # 3) current 런처: 내용이 바뀐 경우에만 덮어쓰기. 잠겨 있으면 경고만(런처는 버전과 무관)
    $want = [ordered]@{
        'ESL_probe.bat'   = [Text.Encoding]::ASCII.GetBytes((Get-LauncherBat 'probe'))
        'ESL_extract.bat' = [Text.Encoding]::ASCII.GetBytes((Get-LauncherBat 'extract'))
        'esl_launch.ps1'  = [IO.File]::ReadAllBytes($launchPs1)
    }
    $launchersOk = $true
    foreach ($name in $want.Keys) {
        $r = Update-LauncherFile (Join-Path $currentDir $name) $want[$name]
        if ($r -eq 'written') { Say "    런처 갱신: current\$name" }
        elseif ($r -ne 'same') {
            $launchersOk = $false
            Say "    런처를 갱신하지 못했습니다(다음 update 에서 다시 시도): current\$name - $r" 'Yellow'
            Add-Check "런처 $name" 'WARN' "갱신 못 함: $r"
        }
    }

    # 4) 예전 구조 이전: current 에 직접 있던 배포 산출물(TCL, esl_run.ps1 등)만 파일 단위로 정리.
    #    런처가 모두 새 것일 때만(예전 런처가 남았으면 예전 파일이 필요). 잠겨 못 지우면 경고만.
    $legacy = @(Get-LegacyArtifacts $currentDir)
    if ($legacy.Count -gt 0) {
        if ($launchersOk) {
            Say "    예전 구조 정리: current 의 배포 산출물 $($legacy.Count)개"
            foreach ($f in $legacy) {
                try { Remove-DeployFile $f; Write-Log "REMOVED $f" }
                catch { Say "    지우지 못함(무시, 동작에는 영향 없음): $f - $($_.Exception.Message)" 'Yellow' }
            }
        }
        else { Say '    예전 런처가 남아 있어 current 의 예전 배포 산출물은 이번에는 그대로 둡니다.' 'Yellow' }
    }
    $foreign = @(Get-ForeignFiles $currentDir)
    if ($foreign.Count -gt 0) {
        Say "    current 에 배포 산출물이 아닌 파일 $($foreign.Count)개(그대로 둠). h3d 는 원본 위치에서 끌어다 놓으세요(current 안의 h3d 는 거부):" 'Yellow'
        foreach ($p in $foreign) { Say "      $p" 'Yellow' }
    }
    foreach ($d in @(Get-LegacyDeployDirs $script:DeployDir)) {
        try { Remove-DeployTree $d; Say "    예전 버전 폴더 정리: $d"; Write-Log "REMOVED $d" }
        catch { Say "    예전 폴더를 남겨 둠(다음 update 에서 다시 시도): $d - $($_.Exception.Message)" 'Yellow' }
    }

    # 5) 오래된 버전 정리: 최근 $KeepVersions 개 + 활성 버전 유지. 잠김·사용자 파일이면 건너뜀(오류 아님)
    $active = Read-CurrentVersion $script:DeployDir
    $all = @(Get-ChildItem -Force -LiteralPath $versionsRoot -Directory)
    $prune = @(Select-VersionsToPrune $all $active $KeepVersions)
    foreach ($name in $prune) {
        $d = Join-Path $versionsRoot $name
        try { Remove-DeployTree $d; Say "    오래된 버전 정리: versions\$name"; Write-Log "REMOVED $d" }
        catch { Say "    정리 건너뜀(다음 update 에서 다시 시도): versions\$name - $($_.Exception.Message)" 'Yellow' }
    }

    return [pscustomobject]@{ Current = $currentDir; Active = (Join-Path $versionsRoot $active); Version = $active }
}

# ---- 점검 ------------------------------------------------------------------------------------
function Test-Environment($Cfg, $Deploy, [string]$WorkRoot, [string[]]$Protected) {
    Stage '점검'
    $hw = Expand-ConfigPath ([string]$Cfg.hw_exe)
    if ($hw -and (Test-Path -LiteralPath $hw -PathType Leaf)) { Add-Check 'hw.exe' 'OK' $hw }
    else { Add-Check 'hw.exe' 'FAIL' "없음: '$hw' -> 설정 hw_exe 수정" }

    if ($Deploy.Version) { Add-Check $PointerName 'OK' $Deploy.Version } else { Add-Check $PointerName 'FAIL' '활성 버전을 읽지 못함' }
    foreach ($n in @('esl_h3d_probe.tcl', 'esl_h3d_extract.tcl', 'esl_run.ps1')) {
        $p = Join-Path $Deploy.Active $n
        if (Test-Path -LiteralPath $p -PathType Leaf) { Add-Check $n 'OK' $p } else { Add-Check $n 'FAIL' "없음: $p" }
    }
    foreach ($n in $LauncherNames) {
        $p = Join-Path $Deploy.Current $n
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
    $deploy = Publish-Deployment $cfg $version
    $currentDir = $deploy.Current
    Add-Check 'deploy' 'OK' "$($deploy.Active) (활성 $($deploy.Version))"
    Test-Environment $cfg $deploy $workRoot $protected

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
