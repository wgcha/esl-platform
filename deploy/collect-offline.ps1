<#
.SYNOPSIS
  인터넷 되는 준비 PC(Windows)에서 폐쇄망 설치 묶음 esl-offline-<version>.zip을 만든다(physicsai deploy\collect-offline.ps1과 같은 구성).
.DESCRIPTION
  Python 3.12 선택(deploy\python-select.ps1, 시연과 같은 규칙): -PythonExe > -DashboardRoot의 고정 Python 3.12 > py -3.12 > PATH의 python.
  pip download는 고른 Python으로 만든 빌드용 임시 venv(dist\_buildvenv)에서 실행한다 — 대시보드 런타임·시스템 Python에는 아무것도 설치하지 않고,
  임시 venv는 끝나면 지우며 묶음에도 넣지 않는다.
  프런트는 Node 22로 빌드한다(-DashboardRoot의 고정 Node > PATH의 node, deploy\node-select.ps1). ESL 저장소에는 빌드본이 커밋되어 있지 않다.
  묶음 구성: wheels(win_amd64 cp312 — deploy\requirements.lock, pypardiso·MKL 포함), frontend(빌드본), app(esl·backend\esl_platform·worker\esl_worker·
  migrations·alembic.ini·pyproject.toml·esl_service.py), config(예시 설정), deploy.
.PARAMETER DryRun
  Python·Node만 확인하고 실행할 명령을 출력한다(빌드·내려받기 없음).
.PARAMETER PythonExe
  Python 3.12 실행 파일(대시보드와 같은 3.12.13 권장). 비우면 자동 선택(위 순서).
.PARAMETER DashboardRoot
  대시보드 폴더(예 E:\VD_SIMULATION_WEB\simdashboard, 선택). .tools의 고정 Python 3.12·Node 22를 후보로 쓴다(.env 비밀번호는 읽지 않음).
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$PythonExe = '',
    [string]$DashboardRoot = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$version = (Select-String -Path (Join-Path $root 'pyproject.toml') -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value
$out = "dist\esl-offline-$version.zip"   # dist\에는 '*' .gitignore를 둔다(git 제외)
$tag = 'ESL 묶음'
function Write-Step([string]$m) { Write-Host "[$tag] $m" }

function Invoke-Step([string]$Text, [scriptblock]$Block) {
    Write-Host "+ $Text"
    if (-not $DryRun) { & $Block }
}

function Invoke-Native([string]$What, [string]$Exe, [string[]]$Arguments, [string]$Hint = '위 출력을 확인하세요') {
    # Windows PowerShell 5.1: 자식의 stderr(pip 경고 등)가 오류 레코드로 중단되지 않게 하고, 종료코드로만 판단한다
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }; $rc = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
    if ($rc -ne 0) { throw "실패: $What (종료코드 $rc)`n다음 행동: $Hint" }
}

# ---- 실행 환경: Python 3.12·Node 22(대시보드 고정 런타임 우선) -------------------------------------------
$dash = $null
if ($DashboardRoot) {
    . (Join-Path $PSScriptRoot 'dashboard-env.ps1')
    $dash = Get-DashboardRuntimeDefaults -DashboardRoot $DashboardRoot
    Write-Step "대시보드 환경: $DashboardRoot (Python 3.12 $(if ($dash.PythonExe) { '있음' } else { '없음' }), Node 22 $(if ($dash.NodeExe) { '있음' } else { '없음' }))"
}
. (Join-Path $PSScriptRoot 'python-select.ps1')
$cands = Get-EslPythonCandidates -PythonExe $PythonExe -DashboardPython $(if ($dash) { "$($dash.PythonExe)" } else { '' })
$base = Select-EslPython -Candidates $cands -Tag $tag
. (Join-Path $PSScriptRoot 'node-select.ps1')
. (Join-Path $PSScriptRoot 'install-common.ps1')   # Write-EslBuildInfo(BUILD.json)
$node = Select-EslNode -DashboardNode $(if ($dash) { "$($dash.NodeExe)" } else { '' }) -RepoRoot $root -Tag $tag

# ---- 빌드용 임시 venv(고른 Python 3.12로 만든다 — 대시보드 런타임에는 설치하지 않음, 끝나면 지움·묶음 미포함) ----------------
$buildVenv = Join-Path $root 'dist\_buildvenv'
$py = Join-Path $buildVenv 'Scripts\python.exe'
Invoke-Step "python -m venv dist\_buildvenv (빌드용 임시 — pip는 여기서, 끝나면 지움·묶음 미포함)" {
    if (Test-Path -LiteralPath $buildVenv) { Remove-Item -LiteralPath $buildVenv -Recurse -Force }
    Invoke-Native 'python -m venv dist\_buildvenv' $base.Exe @('-m', 'venv', $buildVenv) "dist 폴더 쓰기 권한과 Python($($base.Exe))의 venv 모듈을 확인하거나 -PythonExe로 다른 Python 3.12를 지정하세요."
    if (-not (Test-Path -LiteralPath $py)) { throw "빌드용 venv에 python.exe가 없습니다: $py" }
}
$pipHint = '위 pip 출력을 확인하세요(인덱스 접근 문제면 사내 프록시 pip 설정 PIP_INDEX_URL·HTTPS_PROXY 확인).'
$savedPath = $env:PATH
try {
    Invoke-Step 'mkdir dist\bundle\{wheels,frontend,app,config,deploy}' {
        New-Item -ItemType Directory -Force -Path 'dist' | Out-Null
        if (-not (Test-Path -LiteralPath 'dist\.gitignore')) { [IO.File]::WriteAllText((Join-Path $root 'dist\.gitignore'), "*`n") }
        foreach ($d in 'dist\bundle\wheels', 'dist\bundle\frontend', 'dist\bundle\app', 'dist\bundle\config', 'dist\bundle\deploy') {
            if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force }   # 이전 묶음 내용이 섞이지 않게(dist 안만)
            New-Item -ItemType Directory -Force -Path $d | Out-Null
        }
    }
    Invoke-Step 'pip download -r deploy/requirements.lock --only-binary=:all: --platform win_amd64 --python-version 3.12 -d dist/bundle/wheels' {
        Invoke-Native 'pip download (requirements.lock)' $py @('-m', 'pip', 'download', '--disable-pip-version-check', '-r', 'deploy/requirements.lock',
            '--only-binary=:all:', '--platform', 'win_amd64', '--python-version', '3.12', '-d', 'dist/bundle/wheels') $pipHint
    }
    Invoke-Step "npm ci && npm run build (frontend, Node $($node.Version))" {
        # npm은 창에서 직접 친 것과 같이 콘솔 그대로(node-select.ps1 Invoke-EslNpm)
        Invoke-EslFrontendBuild -Node $node -RepoRoot $root
    }
    Invoke-Step 'copy frontend\dist, app(esl·backend\esl_platform·worker\esl_worker·migrations·alembic.ini·pyproject.toml·esl_service.py), config, deploy' {
        Copy-Item -Recurse -Force 'frontend\dist\*' 'dist\bundle\frontend\'
        foreach ($it in 'esl', 'backend\esl_platform', 'worker\esl_worker', 'migrations', 'resources\tcl', 'resources\opt_method_sources.json') {
            $dst = Join-Path 'dist\bundle\app' $it
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            Copy-Item -Recurse -Force $it $dst
        }
        Copy-Item -Force 'alembic.ini', 'pyproject.toml', 'VERSION', 'CHANGELOG.md' 'dist\bundle\app\'
        # 코드 스냅샷 버전 기록(계약 esl_p3_ux.md §3): BUILD.json {version, commit, built_at}
        Write-EslBuildInfo -Source $root -Dest (Join-Path $root 'dist\bundle\app') | Out-Null
        Copy-Item -Force 'deploy\esl_service.py' 'dist\bundle\app\esl_service.py'
        Copy-Item -Force 'config\esl_platform.prod.example.yaml', 'config\esl_platform.example.yaml', 'config\esl.example.yaml', 'config\library.example.yaml', 'config\ista6.yaml' 'dist\bundle\config\'
        Copy-Item -Recurse -Force 'deploy\*' 'dist\bundle\deploy\'
        Get-ChildItem -LiteralPath 'dist\bundle' -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    }
} finally {
    $env:PATH = $savedPath
    if (-not $DryRun -and (Test-Path -LiteralPath $buildVenv)) { Remove-Item -LiteralPath $buildVenv -Recurse -Force -ErrorAction SilentlyContinue }
}
# 묶음에는 이 5개 폴더만(빌드용 임시 venv 등은 넣지 않음 — collect-offline.sh와 같은 구성)
Invoke-Step "Compress-Archive dist\bundle\{wheels,frontend,app,config,deploy} $out" {
    Compress-Archive -Path 'dist\bundle\wheels', 'dist\bundle\frontend', 'dist\bundle\app', 'dist\bundle\config', 'dist\bundle\deploy' -DestinationPath $out -Force
}
Write-Host "묶음: $out"
