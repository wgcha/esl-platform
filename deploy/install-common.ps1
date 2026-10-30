<#
.SYNOPSIS
  ESL 서버 설치·업데이트 공용 함수. setup.ps1(git 폴더)·update-repo.ps1(git 폴더)·install.ps1(묶음)·update.ps1(묶음)이 dot-source 한다.
.DESCRIPTION
  physicsai-platform deploy\install-common.ps1과 같은 구조·규칙(함수 이름 Esl, 작업 ESL-Backend·ESL-Worker).
  DB 역할·DB 생성, 런타임 파일(DB 접속 정보), 코드 배치(<런타임>\app), alembic, 작업 스케줄러 등록·시작·중지, health 확인,
  환경 점검 표, 실행 중 작업 확인을 한 곳에 둔다(설치 방식과 무관). 관리자 권한이 필요 없다: 머신 환경변수를 쓰지 않는다.
  - DB URL(앱 비밀번호 포함)은 <런타임>\secrets\database_url 한 파일(현재 사용자·SYSTEM만 읽기)에만 둔다. 설정은 <런타임>\config\esl_platform.yaml.
  - 플랫폼 코드는 환경변수(ESL_PLATFORM_CONFIG·ESL_DATABASE_URL)만 읽으므로, 작업은 실행기 <런타임>\app\esl_service.py
    (backend|worker --runtime <런타임>)로 등록한다 — 실행기가 두 파일을 읽어 자기 프로세스 환경에만 넣는다(인자·로그에 비밀값 없음).
  - 비밀번호는 Read-Host -AsSecureString(대화형) 또는 -PasswordsFromEnv(프로세스 환경변수)로만 받고, psql에는 PGPASSWORD 프로세스 환경으로만
    넘긴다(명령 인자·로그·파일에 남기지 않음). 출력 머리말은 호출 스크립트의 $EslTag(예 'ESL 설치').
  - 127.0.0.1 호출은 loopback-http.ps1(Invoke-LoopbackRest, 프록시 미사용)을 쓴다.
#>

. (Join-Path $PSScriptRoot 'loopback-http.ps1')

$EslTaskNames = @('ESL-Backend', 'ESL-Worker')
# <런타임>\app 으로 복사하는 코드(저장소 루트·묶음 app 폴더 기준 상대경로). 실행기는 deploy\esl_service.py → app\esl_service.py
# resources/tcl: 서버 h3d 추출 TCL(esl_h3d_extract.tcl — 워커가 <런타임>\app\resources\tcl 에서 실행, 계약 esl_p3_ux.md §6)
# resources/opt_method_sources.json: 비드 최적화 방법·출처(GET /opt/settings — v0.7.2 전에는 빠져 새 비드 최적화 화면이 비었음)
# resources/doe_messages.json·doe_method_sources.json: v0.9.0 비드 DOE 사용자 문구·방법 출처(계약 esl_bead_doe.md §6.4, V-BD-18)
# v0.10.0(계약 esl_menu_restructure.md §13 MR5): 새 런타임 파일 esl/export/from_entry.py(라이브러리 내보내기 코어 어댑터)·backend/esl_platform/api/services/library_export.py 는 'esl'·'backend/esl_platform' 폴더째 복사에 포함(새 resources 없음, tests/deploy/test_menu_deploy.py)
# v0.10.1: deploy/wheels(저장소 동봉 paicad wheel)는 설치 때 venv 에 pip 로 넣는 것이라 <런타임>\app 복사 대상이 아니다(여기 넣지 않음).
#   git 폴더 설치는 <git>\deploy\wheels 를 그대로 읽고, 오프라인 묶음은 collect-offline 이 deploy\ 째(→ 묶음 deploy\wheels)와 묶음 wheels\ 에 넣는다.
# v0.11.0(계약 esl_scx_relay.md §5.2·§13): resources/scx_messages.json = SCX 릴레이 오류 → 사용자 문구(백엔드·워커·화면 공용 원본).
#   deploy/wheels 의 simdash_adapters wheel(동봉)은 paicad 와 같이 venv 에 pip 로 넣는다(Install-EslScxAdapters — app 복사 대상 아님).
$EslAppItems = @('esl', 'backend/esl_platform', 'worker/esl_worker', 'migrations', 'resources/tcl', 'resources/opt_method_sources.json', 'resources/doe_messages.json', 'resources/doe_method_sources.json', 'resources/scx_messages.json', 'alembic.ini', 'pyproject.toml', 'VERSION', 'CHANGELOG.md')   # '/'는 Windows·pwsh 모두 구분자
$EslActiveJobsSql = "SELECT count(*) FROM jobs WHERE state IN ('QUEUED','RUNNING')"

function Write-EslStep([string]$Message) {
    $t = if ($script:EslTag) { $script:EslTag } else { 'ESL' }
    Write-Host "[$t] $Message"
}

function Assert-EslExit([string]$What) {
    if ($LASTEXITCODE -ne 0) { throw "$What 실패(종료코드 $LASTEXITCODE)" }
}

function Test-EslAccessDenied {
    <# 오류 레코드가 권한 부족(액세스 거부)인지 — 작업 스케줄러(CIM)·파일 API 공통. -AlreadyExists면 "이미 있음"도(보이지 않는 관리자 작업). #>
    param($ErrorRecord, [switch]$AlreadyExists)
    if (-not $ErrorRecord) { return $false }
    $e = if ($ErrorRecord -is [Management.Automation.ErrorRecord]) { $ErrorRecord.Exception } else { $ErrorRecord }
    if ($ErrorRecord -is [Management.Automation.ErrorRecord] -and "$($ErrorRecord.CategoryInfo.Category)" -eq 'PermissionDenied') { return $true }
    if ($e -is [UnauthorizedAccessException] -or $e.HResult -eq -2147024891) { return $true }   # 0x80070005
    $m = "$($e.Message)"
    if ($m -match '(?i)access is denied|access denied|액세스가 거부|0x80070005|E_ACCESSDENIED') { return $true }
    if ($AlreadyExists -and ($e.HResult -eq -2147024713 -or $m -match '(?i)already exists|0x800700B7|이미 있')) { return $true }
    return $false
}

function Get-EslTaskAdminMessage {
    return ("작업 스케줄러 작업(ESL-Backend·ESL-Worker)을 바꿀 권한이 없습니다(다른 계정 또는 관리자 권한으로 등록된 작업).`n" +
        "다음 행동: 처음 등록한 것과 같은 사용자 계정으로 PowerShell을 '관리자 권한으로 실행'해 이 스크립트를 한 번 실행하세요(그 뒤로는 일반 PowerShell로 됩니다).`n" +
        "  다른 관리자 계정으로 로그인해 실행하지 마세요 — DB 접속 정보 폴더(secrets)는 지금 사용자만 읽을 수 있습니다.")
}

function ConvertTo-EslPlain([Security.SecureString]$Secure) {
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

function Read-EslSecret {
    <# 기본은 Read-Host -AsSecureString(대화형). -FromEnv면 프로세스 환경변수(명령 인자·로그에 남지 않음). #>
    param([string]$Prompt, [string]$EnvName, [switch]$FromEnv, [switch]$NonInteractive)
    if ($FromEnv) {
        $v = [Environment]::GetEnvironmentVariable($EnvName, 'Process')
        if ($null -eq $v) { throw "-PasswordsFromEnv: 환경변수 $EnvName 이 없습니다" }
        $ss = New-Object Security.SecureString
        foreach ($ch in $v.ToCharArray()) { $ss.AppendChar($ch) }
        $ss.MakeReadOnly()
        return $ss
    }
    if ($NonInteractive) { throw "-NonInteractive: '$Prompt' 을(를) 물을 수 없습니다. -PasswordsFromEnv와 환경변수 $EnvName 을(를) 쓰세요" }
    return (Read-Host -AsSecureString $Prompt)
}

function Invoke-EslNative {
    <# 외부 명령 실행(출력은 화면으로). Windows PowerShell 5.1에서 자식 stderr가 오류 레코드로 중단되지 않게 하고 종료코드로만 판단한다. #>
    param([Parameter(Mandatory = $true)][string]$What, [Parameter(Mandatory = $true)][string]$Exe,
          [string[]]$Arguments = @(), [string]$Hint = '위 출력을 확인하세요')
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }; $rc = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
    if ($rc -ne 0) { throw "실패: $What (종료코드 $rc)`n다음 행동: $Hint" }
}

function Invoke-EslPip {
    <# venv의 pip. 사내 pip 설정(PIP_INDEX_URL·pip.ini)·프록시(HTTPS_PROXY)는 그대로 쓴다. 실패하면 인덱스 접근 문제인지 판단해 한국어로 중단. #>
    param([Parameter(Mandatory = $true)][string]$Py, [Parameter(Mandatory = $true)][string[]]$PipArgs, [Parameter(Mandatory = $true)][string]$What)
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = @(& $Py -m pip @PipArgs --progress-bar off --disable-pip-version-check 2>&1 | ForEach-Object { $s = "$_"; Write-Host $s; $s })
        $rc = $LASTEXITCODE
    } finally { $ErrorActionPreference = $eap }
    if ($rc -eq 0) { return }
    $text = $out -join "`n"
    if ($text -match '(?i)NewConnectionError|ConnectTimeout|ConnectionError|ProxyError|Max retries exceeded|Temporary failure in name resolution|getaddrinfo failed|No matching distribution found|Could not find a version that satisfies|SSLError|CERTIFICATE_VERIFY_FAILED|403 Client Error|407') {
        throw ("$What 실패: 패키지 인덱스(PyPI 또는 PIP_INDEX_URL)에 접근할 수 없습니다.`n" +
            "다음 행동: 사내 프록시면 pip 설정(pip.ini의 index-url·proxy, 또는 환경변수 PIP_INDEX_URL·HTTPS_PROXY)을 확인하세요. 인터넷이 안 되는 서버면 오프라인 묶음(deploy\collect-offline.ps1 → install.ps1)을 쓰세요.")
    }
    throw ("$What 실패(pip 종료코드 $rc).`n다음 행동: 위 pip 출력을 확인하세요.")
}

$EslLockOptionalMarker = '# ==== bead_doe'   # requirements.lock 에서 이 줄 아래 = 비드 DOE 선택 의존성(OCP·gmsh — 따로 설치, 실패해도 기존 기능 유지)

function Get-EslLockPackages {
    <# requirements.lock → @{ Core = 기본 고정 목록; BeadDoe = '# ==== bead_doe' 줄 아래 고정 목록 } (주석·빈 줄 제외, 'name==ver' 그대로). #>
    param([Parameter(Mandatory = $true)][string]$LockFile)
    $core = New-Object System.Collections.Generic.List[string]
    $opt = New-Object System.Collections.Generic.List[string]
    $inOpt = $false
    foreach ($ln in (Get-Content -Encoding UTF8 -LiteralPath $LockFile)) {
        $s = "$ln".Trim()
        if ($s.StartsWith($EslLockOptionalMarker)) { $inOpt = $true; continue }
        if (-not $s -or $s.StartsWith('#')) { continue }
        if ($inOpt) { $opt.Add($s) } else { $core.Add($s) }
    }
    return @{ Core = [string[]]$core.ToArray(); BeadDoe = [string[]]$opt.ToArray() }
}

function Install-EslPackages {
    <#
      venv에 외부 의존성(deploy\requirements.lock — 고정 버전, Windows cp312: FastAPI·SQLAlchemy·psycopg·numpy·scipy·pypardiso+MKL·pyamg·psutil)을 설치한다.
      -Wheels(오프라인 묶음): --no-index --find-links <wheels>. 아니면 인덱스(사내 pip 설정). 플랫폼 코드는 pip로 설치하지 않는다(<런타임>\app 복사본).
      lock 의 bead_doe 절(OCP·gmsh)은 여기서 설치하지 않는다 — Install-EslBeadDoe(실패해도 기존 기능 유지).
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$LockFile, [string]$Wheels = '')
    $core = (Get-EslLockPackages -LockFile $LockFile).Core
    $a = @('install') + $core
    if ($Wheels) { $a = @('install', '--no-index', '--find-links', $Wheels) + $core }
    Invoke-EslPip -Py $VenvPy -PipArgs $a -What "의존성($LockFile) 설치"
    Invoke-EslNative '설치 확인(import)' $VenvPy @('-c', 'import fastapi, uvicorn, sqlalchemy, psycopg, alembic, httpx, pydantic, yaml, numpy, scipy') '위 오류를 확인하세요(venv 패키지 설치가 끝나지 않음)'
}

function Install-EslBeadDoe {
    <#
      v0.9.0 비드 DOE(계약 esl_bead_doe.md §6.4·BD-D-19·20): ① requirements.lock bead_doe 절(cadquery-ocp·vtk·gmsh 등 — 사내 pip 인덱스,
         <Wheels> 가 있으면 오프라인 묶음) ② paicad wheel — v0.10.1 설치 우선순위(esl 단독 설치 — physicsai 저장소·wheel 폴더 불필요):
         (a) <VendoredWheels>(기본 = 이 파일 옆 deploy\wheels — 저장소 동봉)의 deploy\paicad.lock 이름 wheel: 설치 전 lock 대조
             (paicad_wheel.py verify — 버전·정규화 sha256), 불일치면 (b)(c)로 넘어가지 않고 중단(사유 기록 — DOE 만 비활성)
         (b) <Wheels>(오프라인 묶음 wheels) 또는 <PaicadWheels>(deploy.json paicad_wheels 폴더)
         (c) <PhysicsaiRepo>(deploy.json physicsai_root, 읽기만)의 lock 커밋으로 <WorkDir>에 빌드
         → verify → pip install --no-deps ③ 확인(paicad_wheel.py check: paicad version --json 의
         paicad ≥ lock·ocp 있음, gmsh import). 관리자 권한·머신 환경변수 없음. 실패해도 throw 하지 않는다 — 기존 기능은 그대로,
      비드 DOE 만 비활성(워커 점검이 사유 PAICAD_* 를 기록).
      결과 [pscustomobject]{Ok, Paicad, Ocp, Gmsh, Exe, Source, Reason, Warnings} — Source = vendored·wheels·paicad_wheels·physicsai_root·installed.
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$LockFile,
          [Parameter(Mandatory = $true)][string]$PaicadLock, [string]$Wheels = '', [string]$PaicadWheels = '',
          [string]$PhysicsaiRepo = '', [string]$WorkDir = '', [string]$VendoredWheels = '')
    $res = [ordered]@{ Ok = $false; Paicad = $null; Ocp = $null; Gmsh = $null; Exe = $null; Source = ''; Reason = ''; Warnings = @() }
    $helper = Join-Path $PSScriptRoot 'paicad_wheel.py'
    if (-not $VendoredWheels) { $VendoredWheels = Join-Path $PSScriptRoot 'wheels' }   # 저장소 동봉(deploy\wheels, v0.10.1)
    $exe = Join-Path (Split-Path -Parent $VenvPy) 'paicad.exe'   # <venv>\Scripts\paicad.exe (console script 'paicad')
    $res.Exe = $exe
    try {
        $pkgs = @((Get-EslLockPackages -LockFile $LockFile).BeadDoe)
        if ($pkgs.Count) {
            $a = @('install')
            if ($Wheels) { $a += @('--no-index', '--find-links', $Wheels) }
            Invoke-EslPip -Py $VenvPy -PipArgs ($a + $pkgs) -What '강성 평가 스터디 의존성(cadquery-ocp·gmsh) 설치'
        }
        $lock = Get-Content -Raw -Encoding UTF8 -LiteralPath $PaicadLock | ConvertFrom-Json
        $whl = $null
        # (a) 저장소 동봉 wheel — 있으면 이것만 쓴다(불일치면 아래 verify 에서 중단, (b)(c)로 넘어가지 않음)
        $vend = Join-Path $VendoredWheels $lock.wheel
        if (Test-Path -LiteralPath $vend) {
            $whl = $vend; $res.Source = 'vendored'
            Write-EslStep "paicad $($lock.version) wheel: 저장소 동봉 $vend (physicsai 저장소 불필요)"
        }
        # (b) 오프라인 묶음 wheels · deploy.json paicad_wheels
        if (-not $whl -and $Wheels -and (Test-Path -LiteralPath (Join-Path $Wheels $lock.wheel))) { $whl = Join-Path $Wheels $lock.wheel; $res.Source = 'wheels' }
        if (-not $whl -and $PaicadWheels -and (Test-Path -LiteralPath (Join-Path $PaicadWheels $lock.wheel))) { $whl = Join-Path $PaicadWheels $lock.wheel; $res.Source = 'paicad_wheels' }
        # (c) physicsai_root 저장소에서 빌드(읽기만)
        if (-not $whl -and $PhysicsaiRepo) {
            if (-not $WorkDir) { throw 'physicsai_root 로 paicad 를 빌드할 작업 폴더가 없습니다' }
            if (Test-Path -LiteralPath $WorkDir) { Remove-Item -LiteralPath $WorkDir -Recurse -Force }
            Write-EslStep "paicad $($lock.version) wheel 빌드: $PhysicsaiRepo (커밋 $($lock.commit.Substring(0, 12)) — 저장소는 읽기만)"
            Invoke-EslNative 'paicad wheel 빌드' $VenvPy @($helper, 'collect', '--lock', $PaicadLock, '--out-dir', $WorkDir, '--repo', $PhysicsaiRepo, '--work', (Join-Path $WorkDir 'build')) `
                'physicsai 저장소에 lock 커밋이 있는지(git fetch), 사내 pip 설정으로 setuptools 를 받을 수 있는지 확인하세요'
            $whl = Join-Path $WorkDir $lock.wheel; $res.Source = 'physicsai_root'
        }
        if ($whl) {
            $hint = if ($res.Source -eq 'vendored') {
                "저장소 동봉 wheel($vend)이 deploy\paicad.lock 과 다릅니다(파일 손상·부분 갱신) — git status 로 확인하고 git checkout -- deploy/wheels 로 되돌리세요(lock 은 고치지 마세요)"
            } else { 'wheel 이 lock 과 다릅니다 — collect-offline 으로 다시 만든 묶음을 쓰세요' }
            Invoke-EslNative 'paicad wheel 대조(deploy\paicad.lock — 버전·sha256)' $VenvPy @($helper, 'verify', '--lock', $PaicadLock, '--wheel', $whl) $hint
            Invoke-EslPip -Py $VenvPy -PipArgs @('install', '--no-index', '--no-deps', '--force-reinstall', $whl) -What "paicad $($lock.version) 설치"
        } elseif (Test-Path -LiteralPath $exe) {
            $res.Source = 'installed'
            Write-EslStep 'paicad wheel 위치가 없어 venv 에 이미 설치된 paicad 를 확인만 합니다'
        } else {
            throw ("paicad wheel($($lock.wheel))이 없습니다 — 저장소 동봉 deploy\wheels 가 빠졌습니다(git checkout -- deploy/wheels). " +
                '그 밖에는 deploy.json 에 paicad_wheels(wheel 폴더) 또는 physicsai_root(physicsai 저장소)를 쓰세요')
        }
        $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { $raw = @(& $VenvPy $helper check --lock $PaicadLock --exe $exe 2>$null) } finally { $ErrorActionPreference = $eap }
        $chk = (($raw | Where-Object { "$_".StartsWith('{') }) | Select-Object -Last 1) | ConvertFrom-Json
        $res.Paicad = $chk.paicad; $res.Ocp = $chk.ocp; $res.Gmsh = $chk.gmsh; $res.Warnings = @($chk.warnings)
        if (-not $chk.ok) { throw (@($chk.problems) -join '; ') }
        $res.Ok = $true
    } catch {
        $res.Reason = $_.Exception.Message
    }
    foreach ($w in @($res.Warnings)) { if ($w) { Write-Warning "강성 평가 스터디: $w" } }
    if ($res.Ok) {
        Write-EslStep "강성 평가 스터디 형상 엔진: paicad $($res.Paicad) (OCP $($res.Ocp)), gmsh $(if ($res.Gmsh) { $res.Gmsh } else { '없음 — ③ 만 비활성' }) — $exe (wheel: $($res.Source))"
    } else {
        Write-Warning "강성 평가 스터디 비활성(다른 기능은 그대로): $($res.Reason)"
    }
    return [pscustomobject]$res
}

function Install-EslScxAdapters {
    <#
      v0.11.0 SCX 릴레이 어댑터(계약 esl_scx_relay.md §13·SR-D-2): physicsai packages/simdash_adapters(표준 라이브러리만,
      의존성 없음) 정규화 wheel 을 venv 에 넣는다. 설치 우선순위: (a) <VendoredWheels>(기본 = 이 파일 옆 deploy\wheels — 저장소 동봉)
      → (b) <Wheels>(오프라인 묶음 wheels). 설치 전 deploy\simdash_adapters.lock 대조(paicad_wheel.py verify — 버전·정규화 sha256),
      pip install --no-index --no-deps → import 확인(paicad_wheel.py check --module simdash_adapters.hpc: ScxHpcGateway·ScxRadiossRequest).
      실패해도 throw 하지 않는다 — 설치는 계속, SCX 기능(SCX 드라이브에서 고르기·검증 낙하)만 비활성(워커 heartbeat info.scx 사유).
      결과 [pscustomobject]{Ok, Version, Commit, Source, Reason}.
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$ScxLock,
          [string]$Wheels = '', [string]$VendoredWheels = '')
    $res = [ordered]@{ Ok = $false; Version = $null; Commit = $null; Source = ''; Reason = '' }
    $helper = Join-Path $PSScriptRoot 'paicad_wheel.py'
    if (-not $VendoredWheels) { $VendoredWheels = Join-Path $PSScriptRoot 'wheels' }
    try {
        $lock = Get-Content -Raw -Encoding UTF8 -LiteralPath $ScxLock | ConvertFrom-Json
        $res.Commit = "$($lock.commit)".Substring(0, 12)
        $whl = $null
        $vend = Join-Path $VendoredWheels $lock.wheel
        if (Test-Path -LiteralPath $vend) { $whl = $vend; $res.Source = 'vendored' }
        elseif ($Wheels -and (Test-Path -LiteralPath (Join-Path $Wheels $lock.wheel))) { $whl = Join-Path $Wheels $lock.wheel; $res.Source = 'wheels' }
        if (-not $whl) {
            throw "simdash_adapters wheel($($lock.wheel))이 없습니다 — 저장소 동봉 deploy\wheels 가 빠졌습니다(git checkout -- deploy/wheels)"
        }
        Write-EslStep "SCX 릴레이 어댑터 simdash_adapters $($lock.version) (커밋 $($res.Commit)) wheel: $whl"
        Invoke-EslNative 'simdash_adapters wheel 대조(deploy\simdash_adapters.lock — 버전·sha256)' $VenvPy @($helper, 'verify', '--lock', $ScxLock, '--wheel', $whl) `
            'wheel 이 lock 과 다릅니다(파일 손상·부분 갱신) — git checkout -- deploy/wheels 로 되돌리세요(lock 은 고치지 마세요)'
        Invoke-EslPip -Py $VenvPy -PipArgs @('install', '--no-index', '--no-deps', '--force-reinstall', $whl) -What "simdash_adapters $($lock.version) 설치"
        $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { $raw = @(& $VenvPy $helper check --lock $ScxLock --module 'simdash_adapters.hpc' 2>$null) } finally { $ErrorActionPreference = $eap }
        $chk = (($raw | Where-Object { "$_".StartsWith('{') }) | Select-Object -Last 1) | ConvertFrom-Json
        $res.Version = $chk.version
        if (-not $chk.ok) { throw (@($chk.problems) -join '; ') }
        $res.Ok = $true
    } catch {
        $res.Reason = $_.Exception.Message
    }
    if ($res.Ok) {
        Write-EslStep "SCX 릴레이 어댑터: simdash_adapters $($res.Version) (커밋 $($res.Commit), wheel: $($res.Source))"
    } else {
        Write-Warning "SCX 기능 비활성(다른 기능은 그대로 — SCX_ADAPTER_MISSING): $($res.Reason)"
    }
    return [pscustomobject]$res
}

function Test-EslVenvDeps {
    <# venv에 설정 계획·검증에 필요한 패키지가 있는지(yaml·pydantic·sqlalchemy). #>
    param([Parameter(Mandatory = $true)][string]$VenvPy)
    if (-not (Test-Path -LiteralPath $VenvPy)) { return $false }
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $VenvPy -c "import yaml, pydantic, sqlalchemy, numpy" 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) } finally { $ErrorActionPreference = $eap }
}

function Install-EslApp {
    <#
      코드 스냅샷 배치: <Source>(저장소 루트 또는 묶음 app 폴더)의 esl·backend\esl_platform·worker\esl_worker·migrations·alembic.ini·pyproject.toml과
      실행기(<Source>\esl_service.py 또는 <Source>\deploy\esl_service.py)를 <Dest>(<런타임>\app)로. 기존 <Dest>는 지우지 않고 $BackupDir\app으로 이동.
      __pycache__는 복사하지 않는다. 작업이 실행 중인 코드를 덮어쓰지 않게(git pull과 실행 코드 분리) 항상 작업 중지 뒤에 부른다.
    #>
    param([Parameter(Mandatory = $true)][string]$Source, [Parameter(Mandatory = $true)][string]$Dest, [Parameter(Mandatory = $true)][string]$BackupDir)
    $launcher = Join-Path $Source 'esl_service.py'
    if (-not (Test-Path -LiteralPath $launcher)) { $launcher = Join-Path (Join-Path $Source 'deploy') 'esl_service.py' }
    if (-not (Test-Path -LiteralPath $launcher)) { throw "실행기 esl_service.py를 찾을 수 없습니다: $Source" }
    foreach ($it in $EslAppItems) {
        if (-not (Test-Path -LiteralPath (Join-Path $Source $it))) { throw "코드가 없습니다: $(Join-Path $Source $it) (저장소 또는 묶음 app 폴더가 맞는지 확인)" }
    }
    if (Test-Path -LiteralPath $Dest) {
        New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
        Move-Item -LiteralPath $Dest -Destination (Join-Path $BackupDir 'app')
    }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    foreach ($it in $EslAppItems) {
        $src = Join-Path $Source $it
        $dst = Join-Path $Dest $it
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
        if (Test-Path -LiteralPath $src -PathType Container) {
            Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
            Get-ChildItem -LiteralPath $dst -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        } else {
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
    }
    Copy-Item -LiteralPath $launcher -Destination (Join-Path $Dest 'esl_service.py') -Force
    $build = Write-EslBuildInfo -Source $Source -Dest $Dest
    Write-EslStep "코드 배치: $Dest (esl·esl_platform·esl_worker·migrations·실행기 esl_service.py, v$($build.version) $($build.commit))"
}

function Get-EslGitCommit {
    <# 저장소의 짧은 커밋 해시. git이 있으면 rev-parse, 없으면 .git/HEAD·refs·packed-refs를 직접 읽는다. 저장소가 아니면 $null. #>
    param([Parameter(Mandatory = $true)][string]$Repo)
    $gitDir = Join-Path $Repo '.git'
    if (-not (Test-Path -LiteralPath $gitDir)) { return $null }
    $git = (Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    if ($git) {
        $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try {
            $out = & $git -c "safe.directory=$($Repo -replace '\\', '/')" -C $Repo rev-parse --short=7 HEAD 2>$null
            if ($LASTEXITCODE -eq 0 -and "$out" -match '^[0-9a-f]{7,}$') { return "$out".Trim() }
        } finally { $ErrorActionPreference = $eap }
    }
    if (-not (Test-Path -LiteralPath $gitDir -PathType Container)) { return $null }
    $head = "$(Get-Content -LiteralPath (Join-Path $gitDir 'HEAD') -Raw -ErrorAction SilentlyContinue)".Trim()
    $sha = $head
    if ($head -like 'ref:*') {
        $ref = $head.Substring(4).Trim()
        $refFile = Join-Path $gitDir $ref
        $sha = if (Test-Path -LiteralPath $refFile) { "$(Get-Content -LiteralPath $refFile -Raw)".Trim() } else { '' }
        if (-not $sha) {
            $packed = Join-Path $gitDir 'packed-refs'
            if (Test-Path -LiteralPath $packed) {
                foreach ($ln in Get-Content -LiteralPath $packed) { $p = "$ln".Split(' '); if ($p.Count -eq 2 -and $p[1] -eq $ref) { $sha = $p[0] } }
            }
        }
    }
    if ($sha -match '^[0-9a-f]{7,}$') { return $sha.Substring(0, 7) }
    return $null
}

function Write-EslBuildInfo {
    <#
      코드 스냅샷에 BUILD.json {version, commit, built_at} 기록(계약 esl_p3_ux.md §3 — 상단 바 버전·툴팁).
      묶음 app 폴더에 이미 BUILD.json 이 있으면(collect-offline) 그대로 복사, 없으면 VERSION·git 짧은 해시·지금(UTC)으로 만든다.
    #>
    param([Parameter(Mandatory = $true)][string]$Source, [Parameter(Mandatory = $true)][string]$Dest)
    $srcBuild = Join-Path $Source 'BUILD.json'
    $dst = Join-Path $Dest 'BUILD.json'
    if (Test-Path -LiteralPath $srcBuild) {
        Copy-Item -LiteralPath $srcBuild -Destination $dst -Force
        return (Get-Content -LiteralPath $dst -Raw -Encoding UTF8 | ConvertFrom-Json)
    }
    $verFile = Join-Path $Source 'VERSION'
    $ver = if (Test-Path -LiteralPath $verFile) { "$(Get-Content -LiteralPath $verFile -Raw)".Trim() } else { '0.0.0' }
    $info = [ordered]@{ version = $ver; commit = (Get-EslGitCommit -Repo $Source); built_at = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ') }
    [IO.File]::WriteAllText($dst, ($info | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
    return [pscustomobject]$info
}

function Get-EslLauncher([string]$RuntimeDir) { return (Join-Path (Join-Path $RuntimeDir 'app') 'esl_service.py') }

function Get-EslEndpoint {
    <# 포트·경로는 설정 파일(server.port·base_path) 한 곳에서만 읽는다(deploy.json에 포트 없음). 실행기 endpoint → 실패하면 yaml 직접 → 기본 8110·/esl. #>
    param([string]$ConfigPath, [string]$VenvPy = '', [string]$Launcher = '')
    $port = 8110; $base = '/esl'
    $done = $false
    if ($VenvPy -and $Launcher -and (Test-Path -LiteralPath $VenvPy) -and (Test-Path -LiteralPath $Launcher) -and $ConfigPath) {
        $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try {
            $j = (& $VenvPy $Launcher endpoint --config $ConfigPath 2>$null) -join ''
            if ($LASTEXITCODE -eq 0 -and $j) { $o = $j | ConvertFrom-Json; $port = [int]$o.port; $base = "$($o.base_path)"; $done = $true }
        } catch { Write-Verbose "실행기로 포트 읽기 실패 — yaml에서 직접 읽습니다" } finally { $ErrorActionPreference = $eap }
    }
    if (-not $done -and $ConfigPath -and (Test-Path -LiteralPath $ConfigPath)) {
        $t = Get-Content -Raw -Encoding UTF8 -LiteralPath $ConfigPath
        $m = [regex]::Match($t, '(?m)^server:\s*\r?\n(?:[ \t]+.*\r?\n)*?[ \t]+port:\s*(\d+)')
        if (-not $m.Success) { $m = [regex]::Match($t, '(?m)^server:\s*\{[^}\r\n]*\bport:\s*(\d+)') }
        if ($m.Success) { $port = [int]$m.Groups[1].Value }
        $b = [regex]::Match($t, '(?m)^(?:server:\s*\r?\n(?:[ \t]+.*\r?\n)*?[ \t]+|server:\s*\{[^}\r\n]*\b)base_path:\s*"?(/[A-Za-z0-9_\-/]+)')
        if ($b.Success) { $base = $b.Groups[1].Value }
    }
    $base = '/' + $base.Trim('/')
    return [pscustomobject]@{ Port = $port; BasePath = $base; Health = "http://127.0.0.1:$port$base/api/health" }
}

function ConvertFrom-EslDbUrl([string]$Url) {
    <# postgresql+psycopg://user:pw@host:port/db → 각 부분(비밀번호 포함 — 호출 쪽은 출력·로그에 쓰지 않는다). 해석 불가면 $null. #>
    if (-not $Url) { return $null }
    $m = [regex]::Match($Url, '^postgres(?:ql)?(?:\+\w+)?://(?<u>[^:@/]+):(?<p>[^@]*)@(?<h>[^:/]+):(?<port>\d+)/(?<d>[^?]+)')
    if (-not $m.Success) { return $null }
    return [pscustomobject]@{
        User = [Uri]::UnescapeDataString($m.Groups['u'].Value); Password = [Uri]::UnescapeDataString($m.Groups['p'].Value)
        Host = $m.Groups['h'].Value; Port = [int]$m.Groups['port'].Value; Db = $m.Groups['d'].Value
    }
}

function New-EslDbUrl {
    <# 앱 DB URL(비밀번호는 URL 인코딩). 반환값은 출력·로그에 쓰지 않는다. #>
    param([Parameter(Mandatory = $true)][string]$Role, [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Password,
          [Parameter(Mandatory = $true)][string]$PgHost, [Parameter(Mandatory = $true)][int]$PgPort, [Parameter(Mandatory = $true)][string]$DbName)
    return "postgresql+psycopg://${Role}:$([Uri]::EscapeDataString($Password))@${PgHost}:$PgPort/$DbName"
}

function Test-EslDbLogin {
    <# 앱 역할로 접속 가능한지(비밀번호는 PGPASSWORD 프로세스 환경으로만, 끝나면 지움). #>
    param([Parameter(Mandatory = $true)][string]$PgBin, [Parameter(Mandatory = $true)]$Parts)
    $psql = Join-Path $PgBin 'psql.exe'
    if (-not (Test-Path -LiteralPath $psql)) { return $false }
    $env:PGPASSWORD = $Parts.Password
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $r = & $psql -h $Parts.Host -p ([string]$Parts.Port) -U $Parts.User -d $Parts.Db -w -tAc 'SELECT 1' 2>$null
        return ($LASTEXITCODE -eq 0 -and "$r".Trim() -eq '1')
    } catch { return $false } finally { $ErrorActionPreference = $eap; $env:PGPASSWORD = $null }
}

function Initialize-EslDatabase {
    <#
      대시보드와 같은 PostgreSQL(기준 18)에 앱 역할·DB(기본 esl_app·esl)를 없을 때만 만들고, 앱 DB URL(비밀번호 포함)을 돌려준다.
      -ReuseExisting: 기존 DB URL(-ExistingUrl — 런타임 파일)이 같은 host·port·DB·역할을 가리키고 실제로 접속되면 그대로 쓴다(비밀번호를 묻지 않음).
    #>
    param([Parameter(Mandatory = $true)][string]$PgBin, [Parameter(Mandatory = $true)][string]$PgHost, [Parameter(Mandatory = $true)][int]$PgPort,
          [Parameter(Mandatory = $true)][string]$DbName, [Parameter(Mandatory = $true)][string]$DbRole,
          [switch]$PasswordsFromEnv, [switch]$ReuseExisting, [switch]$NonInteractive, [string]$ExistingUrl = '')
    if ($DbName -notmatch '^[A-Za-z_][A-Za-z0-9_]*$' -or $DbRole -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw "db_name·db_role은 영문·숫자·밑줄만 씁니다: $DbName / $DbRole"
    }
    $psql = Join-Path $PgBin 'psql.exe'
    if (-not (Test-Path -LiteralPath $psql)) { throw "psql.exe가 없습니다: $psql (pg_bin 또는 대시보드 .env의 POSTGRES_BIN 확인)" }
    if ($ReuseExisting) {
        $cur = ConvertFrom-EslDbUrl $ExistingUrl
        if ($cur -and $cur.Host -eq $PgHost -and $cur.Port -eq $PgPort -and $cur.Db -eq $DbName -and $cur.User -eq $DbRole) {
            if (Test-EslDbLogin -PgBin $PgBin -Parts $cur) {
                Write-EslStep "DB: 기존 연결 재사용($DbRole@${PgHost}:$PgPort/$DbName — 비밀번호를 다시 묻지 않음)"
                return $ExistingUrl
            }
            Write-EslStep '기존 DB 접속 정보로 접속되지 않습니다 — 비밀번호를 다시 받습니다'
        }
    }
    $adminPw = Read-EslSecret 'PostgreSQL 관리자(postgres) 비밀번호' 'ESL_INSTALL_PG_ADMIN_PASSWORD' -FromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive
    $appPwSecure = Read-EslSecret "앱 DB 역할($DbRole) 비밀번호(이미 있으면 기존과 같은 값)" 'ESL_INSTALL_DB_PASSWORD' -FromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive
    $appPw = ConvertTo-EslPlain $appPwSecure
    $env:PGPASSWORD = ConvertTo-EslPlain $adminPw
    try {
        $common = @('-h', $PgHost, '-p', [string]$PgPort, '-U', 'postgres', '-v', 'ON_ERROR_STOP=1', '-q')
        # 대시보드와 같은 PostgreSQL 18 인스턴스(별도 DB·역할)를 기준으로 한다 — 다른 주 버전이면 경고만(설치는 계속)
        $verNum = & $psql @common -d postgres -tAc 'SHOW server_version_num'; Assert-EslExit 'psql 서버 버전 확인'
        $verMajor = [int][math]::Floor([int]("$verNum".Trim()) / 10000)
        if ($verMajor -ne 18) { Write-Warning "PostgreSQL 서버 주 버전이 $verMajor 입니다(기준: 대시보드와 같은 18). 계속 진행합니다" }
        else { Write-EslStep "PostgreSQL 서버 버전: $("$verNum".Trim())" }
        $hasRole = & $psql @common -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname = '$DbRole'"; Assert-EslExit 'psql 역할 확인'
        if (-not $hasRole) {
            Write-EslStep "DB 역할 생성: $DbRole"
            # 비밀번호가 서버 로그에 남지 않게: 이 세션만 문장 로그·오류 문장 로그·느린 문장 로그를 끈 뒤 생성(superuser 세션 SET).
            # SQL은 표준 입력으로(명령 인자에 비밀번호 없음)
            $sql = "SET log_statement = 'none'; SET log_min_error_statement = 'panic'; SET log_min_duration_statement = -1; " +
                "SET password_encryption = 'scram-sha-256'; " +
                "CREATE ROLE `"$DbRole`" LOGIN PASSWORD '" + $appPw.Replace("'", "''") + "';"
            $sql | & $psql @common -d postgres | Out-Host; Assert-EslExit 'CREATE ROLE'
            Remove-Variable -Name sql -ErrorAction SilentlyContinue
        } else {
            Write-EslStep "DB 역할 있음: $DbRole (비밀번호는 바꾸지 않음)"
        }
        $hasDb = & $psql @common -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$DbName'"; Assert-EslExit 'psql DB 확인'
        if (-not $hasDb) {
            Write-EslStep "DB 생성: $DbName"
            "CREATE DATABASE `"$DbName`" OWNER `"$DbRole`" ENCODING 'UTF8';" | & $psql @common -d postgres | Out-Host; Assert-EslExit 'CREATE DATABASE'
        } else {
            Write-EslStep "DB 있음: $DbName"
        }
    } finally {
        Remove-Variable -Name adminPw -ErrorAction SilentlyContinue
        $env:PGPASSWORD = $null
    }
    $url = New-EslDbUrl -Role $DbRole -Password $appPw -PgHost $PgHost -PgPort $PgPort -DbName $DbName
    Remove-Variable -Name appPw, appPwSecure -ErrorAction SilentlyContinue
    return $url
}

# ---- 런타임 파일(관리자 권한 없이) ---------------------------------------------------------------------------------
# DB URL(앱 비밀번호 포함)은 <런타임>\secrets\database_url 한 파일(UTF-8, BOM·줄바꿈 없음)에만 둔다. 백엔드·워커는 실행기
# esl_service.py `--runtime <런타임>` 인자(파일 경로만 — 비밀값은 인자·로그에 없음)로 찾는다.

function Get-EslRuntimeSecretPath([string]$RuntimeDir) { return (Join-Path (Join-Path $RuntimeDir 'secrets') 'database_url') }

function Get-EslDbUrl {
    <# DB URL: 런타임 파일 → 빈 문자열. 값은 출력하지 않는다. #>
    param([string]$RuntimeDir = '')
    if ($RuntimeDir) {
        $f = Get-EslRuntimeSecretPath $RuntimeDir
        if (Test-Path -LiteralPath $f -PathType Leaf) {
            $v = ([IO.File]::ReadAllText($f)).Trim().TrimStart([char]0xFEFF)
            if ($v) { return $v }
        }
    }
    return ''
}

function Protect-EslSecretPath {
    <#
      비밀 폴더 ACL: 상속 해제 + 현재 사용자·SYSTEM 모든 권한(+작업 실행 계정이 다르면 읽기)만, 하위로 상속((OI)(CI)) — icacls(Windows 기본 도구).
      폴더에만 적용한다(/T 없음). 실패하거나 icacls가 없으면 경고만 하고 계속한다. 성공하면 $true.
    #>
    param([Parameter(Mandatory = $true)][string]$Path, [string]$ServiceUser = '')
    $icacls = Get-Command icacls -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $icacls) { Write-Warning "비밀 파일 권한 제한을 건너뜁니다(icacls 없음): $Path"; return $false }
    $me = "$env:USERDOMAIN\$env:USERNAME"
    try { $me = '*' + [Security.Principal.WindowsIdentity]::GetCurrent().User.Value } catch { Write-Verbose '현재 사용자 SID를 읽지 못함 — 이름으로 지정' }
    $grants = @("${me}:(OI)(CI)F", '*S-1-5-18:(OI)(CI)F')
    $cur = "$env:USERDOMAIN\$env:USERNAME"
    if ($ServiceUser -and $ServiceUser -ine $cur) { $grants += "${ServiceUser}:(OI)(CI)R" }
    $icArgs = @($Path, '/inheritance:r', '/grant:r') + $grants + @('/Q')
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $out = @(& $icacls.Source @icArgs 2>&1 | ForEach-Object { "$_" }); $rc = $LASTEXITCODE }
    catch { $out = @("$($_.Exception.Message)"); $rc = -1 }
    finally { $ErrorActionPreference = $eap }
    if ($rc -ne 0) {
        Write-Warning "비밀 파일 권한 제한 실패(icacls 종료코드 $rc): $Path — $(($out | Where-Object { $_ }) -join ' ') (설치는 계속합니다. 다른 사용자가 이 PC에 로그온한다면 이 폴더 권한을 직접 확인하세요)"
        return $false
    }
    return $true
}

function Write-EslRuntimeSecret {
    <# DB URL을 <런타임>\secrets\database_url에 쓴다(값은 출력하지 않음, 같은 값이면 다시 쓰지 않음) + ACL 제한 시도. 관리자 권한 불필요. #>
    param([Parameter(Mandatory = $true)][string]$RuntimeDir, [Parameter(Mandatory = $true)][string]$DbUrl, [string]$ServiceUser = '')
    $dir = Join-Path $RuntimeDir 'secrets'
    $f = Get-EslRuntimeSecretPath $RuntimeDir
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $ok = Protect-EslSecretPath -Path $dir -ServiceUser $ServiceUser   # 폴더 먼저 → 파일은 그 ACL을 상속
    $same = $false
    if (Test-Path -LiteralPath $f -PathType Leaf) {
        try { $same = (([IO.File]::ReadAllText($f)).Trim() -ceq $DbUrl) }
        catch {
            Write-Warning "DB 접속 정보 파일을 읽을 수 없어 권한을 폴더 기준으로 되돌립니다: $f"
            $ic = Get-Command icacls -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($ic) { $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'; try { & $ic.Source $f '/reset' '/Q' 2>&1 | Out-Null } finally { $ErrorActionPreference = $eap } }
        }
    }
    if (-not $same) { [IO.File]::WriteAllText($f, $DbUrl, (New-Object Text.UTF8Encoding($false))) }
    if (([IO.File]::ReadAllText($f)).Trim() -cne $DbUrl) { throw "DB 접속 정보 파일을 다시 읽지 못했습니다: $f" }
    Write-EslStep "DB 접속 정보: $f $(if ($same) { '(변경 없음)' } else { '(저장)' })$(if ($ok) { ' — 현재 사용자·SYSTEM만 읽기' }) (값은 출력하지 않음)"
}

function Invoke-EslMigration {
    <# alembic upgrade head(0001~0004) — 실행기 migrate가 런타임 DB 파일을 읽는다(이 PowerShell 환경에는 DB URL을 두지 않음). #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '')
    $a = @((Get-EslLauncher $RuntimeDir), 'migrate', '--runtime', $RuntimeDir)
    if ($ConfigPath) { $a += @('--config', $ConfigPath) }
    Invoke-EslNative 'alembic upgrade head' $VenvPy $a 'DB 접속 정보(secrets\database_url)·PostgreSQL 실행 상태를 확인하세요'
}

function Invoke-EslCheck {
    <# 환경 점검 표(esl_platform.check — 경로 쓰기·DB·migration·워커·솔버 백엔드·pypardiso·설정 검증). FAIL이 있으면 $false(경고만, 중단하지 않음). #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '')
    $a = @((Get-EslLauncher $RuntimeDir), 'check', '--runtime', $RuntimeDir)
    if ($ConfigPath) { $a += @('--config', $ConfigPath) }
    Write-EslStep '환경 점검(esl_platform.check):'
    $eap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $VenvPy @a 2>&1 | ForEach-Object { Write-Host "$_" }; $rc = $LASTEXITCODE } finally { $ErrorActionPreference = $eap }
    if ($rc -ne 0) {
        Write-Warning "환경 점검에 FAIL 항목이 있습니다(위 표). 설정 파일을 고친 뒤 다시 점검: & '$VenvPy' '$(Get-EslLauncher $RuntimeDir)' check --runtime '$RuntimeDir'"
        return $false
    }
    return $true
}

function Export-EslTasks {
    <# 기존 작업 정의를 XML로 남긴다(덮어쓰기 전 _backup). 없으면 아무것도 하지 않는다. 남긴 개수를 돌려준다. #>
    param([Parameter(Mandatory = $true)][string]$Dest)
    $n = 0
    foreach ($name in $EslTaskNames) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            New-Item -ItemType Directory -Force -Path $Dest | Out-Null
            Export-ScheduledTask -TaskName $name | Set-Content -LiteralPath (Join-Path $Dest "$name.xml") -Encoding Unicode
            $n++
        }
    }
    return $n
}

function Get-EslTaskArguments {
    <#
      작업 실행 인자: "<런타임>\app\esl_service.py" backend|worker --runtime "<런타임>" [--config "<설정>"](설정이 <런타임>\config\esl_platform.yaml이
      아닐 때만). 비밀값 없음(파일 경로만). 프런트 정적 서빙은 인자가 아니라 설정 server.frontend_root(유일한 출처).
    #>
    param([Parameter(Mandatory = $true)][ValidateSet('backend', 'worker')][string]$Command, [Parameter(Mandatory = $true)][string]$RuntimeDir,
          [string]$ConfigPath = '')
    $rt = $RuntimeDir.TrimEnd('\', '/')
    $a = "`"$(Get-EslLauncher $rt)`" $Command --runtime `"$rt`""
    $defCfg = Join-Path (Join-Path $rt 'config') 'esl_platform.yaml'
    if ($ConfigPath -and -not ([IO.Path]::GetFullPath($ConfigPath) -ieq [IO.Path]::GetFullPath($defCfg))) { $a += " --config `"$ConfigPath`"" }
    return $a
}

function Get-EslTaskSpecs {
    param([Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '')
    return @(
        @{ Name = 'ESL-Backend'; Args = (Get-EslTaskArguments -Command backend -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath) },
        @{ Name = 'ESL-Worker'; Args = (Get-EslTaskArguments -Command worker -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath) }
    )
}

function Grant-EslTaskAccess {
    <# 등록한 작업의 보안 설명자에 실행 계정 모든 권한(FA)을 더한다(최선 노력 — 실패는 조용히). 그 뒤 일반 PowerShell에서 중지·시작·다시 등록할 수 있게. #>
    param([Parameter(Mandatory = $true)][string]$TaskName, [Parameter(Mandatory = $true)][string]$User)
    try {
        $sid = (New-Object Security.Principal.NTAccount($User)).Translate([Security.Principal.SecurityIdentifier]).Value
        $svc = New-Object -ComObject 'Schedule.Service'
        $svc.Connect()
        $task = $svc.GetFolder('\').GetTask($TaskName)
        $sd = $task.GetSecurityDescriptor(4)   # DACL
        if ($sd -notmatch [regex]::Escape(";;;$sid)")) { $task.SetSecurityDescriptor($sd + "(A;;FA;;;$sid)", 0) }
    } catch { Write-Verbose "작업 권한 추가 건너뜀($TaskName): $($_.Exception.Message)" }
}

function Register-EslTasks {
    <#
      작업 스케줄러 등록 ESL-Backend·ESL-Worker(실행기 esl_service.py backend|worker --runtime <런타임>). 이미 있으면 다시 등록(같은 이름).
      ExecutionTimeLimit = 0(무제한) 필수 — 기본 72시간이면 장시간 솔버 작업 중 워커가 종료된다. 실패 시 1분 간격 999회 재시작, IgnoreNew.
      Interactive(기본): 실행 계정(기본 현재 사용자) 로그온 시, LogonType Interactive·RunLevel Limited — 관리자 권한 불필요.
      Background: 부팅 시(AtStartup)·비밀번호 저장(Service 모드, 세션 0) — 이 모드만 관리자 권한이 필요할 수 있다(거부되면 안내).
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$WorkDir,
          [Parameter(Mandatory = $true)][string]$ServiceUser, [Parameter(Mandatory = $true)][ValidateSet('Background', 'Interactive')][string]$RunMode,
          [Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '',
          [switch]$PasswordsFromEnv, [switch]$NonInteractive)
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    if ($RunMode -eq 'Interactive') {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $ServiceUser
        $principal = New-ScheduledTaskPrincipal -UserId $ServiceUser -LogonType Interactive -RunLevel Limited
    } else {
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $svcPw = Read-EslSecret "작업 실행 계정($ServiceUser) 비밀번호" 'ESL_INSTALL_SERVICE_PASSWORD' -FromEnv:$PasswordsFromEnv -NonInteractive:$NonInteractive
    }
    foreach ($t in (Get-EslTaskSpecs -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath)) {
        $action = New-ScheduledTaskAction -Execute $VenvPy -Argument $t.Args -WorkingDirectory $WorkDir
        try {
            if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
                Stop-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
                Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction Stop
            }
            if ($RunMode -eq 'Interactive') {
                Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -ErrorAction Stop | Out-Null
            } else {
                Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings `
                    -User $ServiceUser -Password (ConvertTo-EslPlain $svcPw) -RunLevel Limited -ErrorAction Stop | Out-Null
            }
        } catch {
            Remove-Variable -Name svcPw -ErrorAction SilentlyContinue
            if (Test-EslAccessDenied $_ -AlreadyExists) {
                if ($RunMode -eq 'Background') {
                    throw ("작업 등록이 거부되었습니다($($t.Name), Background 모드). Background(부팅 시·비밀번호 저장) 등록은 관리자 권한이 필요할 수 있습니다.`n" +
                        "다음 행동: 기본 Interactive 모드를 쓰거나(deploy.json run_mode 또는 -RunMode Interactive), 이 모드만 같은 사용자 계정으로 PowerShell을 '관리자 권한으로 실행'해 실행하세요.")
                }
                throw (Get-EslTaskAdminMessage)
            }
            throw
        }
        Grant-EslTaskAccess -TaskName $t.Name -User $ServiceUser
        Write-EslStep "작업 등록: $($t.Name) ($RunMode, $ServiceUser, 작업 폴더 $WorkDir, 인자 $($t.Args))"
    }
    Remove-Variable -Name svcPw -ErrorAction SilentlyContinue
}

function Test-EslTasksCurrent {
    <# 등록된 두 작업의 실행 파일·인자·작업 폴더가 원하는 값과 같으면 $true(다시 등록할 필요 없음). #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$WorkDir,
          [Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '')
    foreach ($t in (Get-EslTaskSpecs -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath)) {
        $cur = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
        if (-not $cur -or -not $cur.Actions.Count) { return $false }
        $a = $cur.Actions[0]
        if ("$($a.Execute)" -ne $VenvPy -or "$($a.Arguments)" -ne $t.Args -or "$($a.WorkingDirectory)" -ne $WorkDir) { return $false }
    }
    return $true
}

function Update-EslTaskRegistration {
    <#
      업데이트(update-repo.ps1·update.ps1): 작업 정의(실행 파일·인자·작업 폴더)가 지금 설치와 다르면 다시 등록(Interactive만 — 질문 없음). 다시 등록했으면 $true.
      Background는 비밀번호가 필요해 자동으로 다시 등록하지 않고 안내만 한다. 새 코드(venv·app)가 배치된 뒤에 부를 것.
    #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][string]$WorkDir,
          [Parameter(Mandatory = $true)][string]$RuntimeDir, [string]$ConfigPath = '',
          [string]$ServiceUser = '', [string]$RunMode = 'Interactive')
    if (Test-EslTasksCurrent -VenvPy $VenvPy -WorkDir $WorkDir -RuntimeDir $RuntimeDir -ConfigPath $ConfigPath) {
        Write-EslStep '작업 등록 그대로(실행 파일·인자 확인)'
        return $false
    }
    if (-not $ServiceUser) { $ServiceUser = "$env:USERDOMAIN\$env:USERNAME" }
    if ($RunMode -eq 'Background') {
        Write-Warning ("작업 정의가 지금 설치와 다르지만 Background 모드라 자동으로 다시 등록하지 않습니다(비밀번호 필요). " +
            "setup.ps1(또는 install.ps1)을 다시 실행하세요(Background 등록은 관리자 권한이 필요할 수 있음).")
        return $false
    }
    Write-EslStep '작업 다시 등록(실행기 esl_service.py --runtime <런타임>)'
    Register-EslTasks -VenvPy $VenvPy -WorkDir $WorkDir -ServiceUser $ServiceUser -RunMode 'Interactive' -RuntimeDir $RuntimeDir `
        -ConfigPath $ConfigPath -NonInteractive
    return $true
}

function Stop-EslTasks {
    <# 두 작업 중지(없으면 건너뜀). 다른 계정·관리자 권한으로 만든 작업이라 거부되면 안내와 함께 중단. -Names 로 일부만(esl-service.ps1 -Only). #>
    param([string[]]$Names = $EslTaskNames)
    foreach ($t in $Names) {
        if (-not (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue)) { continue }
        try { Stop-ScheduledTask -TaskName $t -ErrorAction Stop }
        catch {
            if (Test-EslAccessDenied $_) { throw (Get-EslTaskAdminMessage) }
            Write-Warning "작업 중지 실패: $t — $($_.Exception.Message)"
        }
    }
    Start-Sleep -Seconds 5
}

function Wait-EslHealth {
    <# health 주소(예 http://127.0.0.1:8110/esl/api/health)가 {"status":"ok"}가 될 때까지(최대 약 60초). 성공하면 $true. #>
    param([Parameter(Mandatory = $true)][string]$HealthUrl, [int]$Tries = 30)
    for ($i = 0; $i -lt $Tries; $i++) {
        Start-Sleep -Seconds 2
        try { if ((Invoke-LoopbackRest -Uri $HealthUrl -TimeoutSec 3).status -eq 'ok') { return $true } } catch { Write-Verbose "health 대기: $($_.Exception.Message)" }
    }
    return $false
}

function Start-EslTasksAndWait {
    <# 두 작업 시작 → health 확인. 실패하면 원인 확인 위치와 함께 중단. health 주소를 돌려준다. #>
    param([Parameter(Mandatory = $true)][string]$HealthUrl, [string]$LogDir = '', [string[]]$Names = $EslTaskNames)
    foreach ($t in $Names) {
        try { Start-ScheduledTask -TaskName $t -ErrorAction Stop }
        catch { if (Test-EslAccessDenied $_) { throw (Get-EslTaskAdminMessage) }; throw }
    }
    if ($Names -notcontains 'ESL-Backend') { return '' }      # 워커만 시작: health 주소는 백엔드 것이라 확인하지 않음
    if (-not (Wait-EslHealth -HealthUrl $HealthUrl)) {
        $where = if ($LogDir) { " 로그: $LogDir\backend.log" } else { '' }
        throw "health 확인 실패: $HealthUrl — 작업 스케줄러 기록과 설정을 확인하세요.$where"
    }
    Write-EslStep "health OK: $HealthUrl"
    return $HealthUrl
}

function Get-EslActiveJobCount {
    <#
      대기·실행 중 작업 수(jobs.state QUEUED·RUNNING). 묻지 않고 DB URL(런타임 파일)로 psql 직접 조회한다.
      접속 정보는 PG* 프로세스 환경으로만 전달(명령 인자에 비밀번호 없음).
    #>
    param([Parameter(Mandatory = $true)][string]$PgBin, [string]$DbUrl = '')
    $p = ConvertFrom-EslDbUrl $DbUrl
    if (-not $p) { throw 'DB 접속 정보(<런타임>\secrets\database_url)가 없거나 형식을 해석할 수 없어 대기열을 확인할 수 없습니다(setup.ps1·install.ps1을 먼저 하세요)' }
    $env:PGUSER = $p.User; $env:PGHOST = $p.Host; $env:PGPORT = [string]$p.Port; $env:PGDATABASE = $p.Db; $env:PGPASSWORD = $p.Password
    try {
        $n = & (Join-Path $PgBin 'psql.exe') -w -tAc $EslActiveJobsSql
        Assert-EslExit 'psql 작업 확인'
        return [int]"$n".Trim()
    } finally {
        $env:PGPASSWORD = $null; $env:PGUSER = $null; $env:PGHOST = $null; $env:PGPORT = $null; $env:PGDATABASE = $null
    }
}

function Assert-EslNoActiveJobs {
    <# 대기·실행 중 작업이 있으면 묻지 않고 안내와 함께 중단(-Force면 경고 후 진행). #>
    param([Parameter(Mandatory = $true)][string]$PgBin, [string]$DbUrl = '', [switch]$Force)
    $active = Get-EslActiveJobCount -PgBin $PgBin -DbUrl $DbUrl
    if ($active -gt 0) {
        if (-not $Force) { throw "대기·실행 중 작업이 $active 건 있습니다. 끝난 뒤 다시 실행하세요(기다리지 않으려면 -Force)" }
        Write-Warning "-Force: 실행 중 작업은 lease 만료 후 INTERRUPTED가 됩니다($active 건)"
    } else {
        Write-EslStep '대기·실행 중 작업 없음'
    }
}

function Test-EslUnderPath {
    <# $Path가 $Root 자신이거나 그 안에 있으면 $true(대소문자 무시). #>
    param([string]$Path, [string]$Root)
    if (-not $Path -or -not $Root) { return $false }
    try {
        $p = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
        $r = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    } catch { return $false }
    return ($p -ieq $r) -or $p.StartsWith($r + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Publish-EslFrontend {
    <# 프런트 빌드 결과를 배치 위치로. 기존 배치는 지우지 않고 $BackupDir\frontend로 이동한다. #>
    param([Parameter(Mandatory = $true)][string]$Dist, [Parameter(Mandatory = $true)][string]$Dest, [Parameter(Mandatory = $true)][string]$BackupDir)
    if (-not (Test-Path -LiteralPath (Join-Path $Dist 'index.html'))) { throw "프런트 빌드에 index.html이 없습니다: $Dist" }
    if (Test-Path -LiteralPath $Dest) {
        New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
        Move-Item -LiteralPath $Dest -Destination (Join-Path $BackupDir 'frontend')
    }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Copy-Item -Recurse -Force (Join-Path $Dist '*') $Dest
    Write-EslStep "프런트 배치: $Dest"
}

function Install-EslFrontendFromRepo {
    <#
      git 폴더의 프런트 배치: 소스 해시(node-select.ps1 Get-EslFrontendSourceHash)가 <StampFile>(지난 배치)과 같고 $Dest\index.html이 있으면
      그대로(Node·npm 단계 없음). 다르면 Node 22로 빌드(npm ci는 package-lock.json이 바뀔 때만) → $Dest(이전 것은 $BackupDir\frontend) → 기록.
      반환값 없음 — 결과를 변수에 받지 말 것(받으면 npm 출력이 파이프가 된다). node-select.ps1을 함께 dot-source 해야 한다.
    #>
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [Parameter(Mandatory = $true)][string]$Dest, [Parameter(Mandatory = $true)][string]$BackupDir,
          [Parameter(Mandatory = $true)][string]$StampFile, [string]$DepsStampFile = '', [string]$DashboardNode = '')
    $hash = Get-EslFrontendSourceHash -FrontendDir (Join-Path $RepoRoot 'frontend')
    $have = if (Test-Path -LiteralPath $StampFile) { ([IO.File]::ReadAllText($StampFile)).Trim() } else { '' }
    if ($have -eq $hash -and (Test-Path -LiteralPath (Join-Path $Dest 'index.html'))) {
        Write-EslStep "프런트: 소스 변경 없음($($hash.Substring(0, 12))) — 배치 그대로(Node·npm 불필요)"
        return
    }
    Write-EslStep "프런트: 소스가 바뀌었거나 배치가 없습니다 — Node 22로 빌드합니다"
    $node = Select-EslNode -DashboardNode $DashboardNode -RepoRoot $RepoRoot -Tag $script:EslTag
    Invoke-EslFrontendBuild -Node $node -RepoRoot $RepoRoot -StampFile $DepsStampFile
    Publish-EslFrontend -Dist (Join-Path (Join-Path $RepoRoot 'frontend') 'dist') -Dest $Dest -BackupDir $BackupDir
    [IO.File]::WriteAllText($StampFile, $hash)
}

function Restore-EslAfterFailedUpdate {
    <#
      업데이트가 migration 전에 실패했을 때 서비스가 멈춘 채 남지 않게: 이번에 $BackupDir로 옮긴 이전 app·frontend가 있으면 원위치로
      (새로 배치하던 것은 $BackupDir\<이름>-failed로 — 삭제 없음) → 작업 2개 다시 시작(-NoStart면 생략). 스스로는 던지지 않는다.
    #>
    param([Parameter(Mandatory = $true)][string]$BackupDir, [string]$AppDest = '', [string]$FrontendDest = '', [switch]$NoStart)
    foreach ($pair in @(@('app', $AppDest), @('frontend', $FrontendDest))) {
        $name = $pair[0]; $dest = $pair[1]
        if (-not $dest) { continue }
        $prev = Join-Path $BackupDir $name
        try {
            if (Test-Path -LiteralPath $prev) {
                if (Test-Path -LiteralPath $dest) { Move-Item -LiteralPath $dest -Destination (Join-Path $BackupDir "$name-failed") }
                Move-Item -LiteralPath $prev -Destination $dest
                Write-EslStep "이전 $name 로 되돌렸습니다: $dest"
            }
        } catch { Write-Warning "이전 $name 되돌리기 실패: $($_.Exception.Message) — $prev 를 $dest 로 옮기세요" }
    }
    if ($NoStart) { return }
    foreach ($t in $EslTaskNames) {
        try { Start-ScheduledTask -TaskName $t -ErrorAction Stop; Write-EslStep "작업 다시 시작: $t" }
        catch { Write-Warning "작업 다시 시작 실패: $t — $($_.Exception.Message)" }
    }
}

function Get-EslAccessUrl {
    <# 접속 주소 한 줄: 대시보드 .env의 WINDOWS_WEB_PORT(없으면 80) → http://<이 서버>[:포트]/esl/. 대시보드 .env를 읽지 못했으면 http://<대시보드 주소>/esl/. #>
    param($Dash, [string]$BasePath = '/esl')
    $b = '/' + $BasePath.Trim('/') + '/'
    if (-not $Dash -or -not $Dash.EnvFile) { return "http://<대시보드 주소>$b" }
    $webPort = if ($Dash.WebPort) { [int]$Dash.WebPort } else { 80 }
    return "http://$([Environment]::MachineName)$(if ($webPort -ne 80) { ":$webPort" })$b"
}

function Write-EslUtf8File {
    <# BOM 없는 UTF-8(Python json이 읽는 형식). #>
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Text)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Set-EslRuntimeGitIgnore {
    <# git 폴더 설치의 런타임 폴더(<git>\.runtime)를 git에서 제외: 그 폴더 안에 '*' 한 줄짜리 .gitignore(저장소 .gitignore는 바꾸지 않음). #>
    param([Parameter(Mandatory = $true)][string]$RuntimeDir)
    $f = Join-Path $RuntimeDir '.gitignore'
    if (-not (Test-Path -LiteralPath $f)) { Write-EslUtf8File -Path $f -Text "*`n" }
}

function Invoke-EslSetupConfig {
    <# deploy\setup_config.py plan|write를 venv Python으로 실행하고 결과 JSON 객체를 돌려준다(입력·결과 파일은 <런타임>\setup-*.json, 비밀값 없음). #>
    param([Parameter(Mandatory = $true)][string]$VenvPy, [Parameter(Mandatory = $true)][ValidateSet('plan', 'write')][string]$Action,
          [Parameter(Mandatory = $true)][string]$RuntimeDir, [Parameter(Mandatory = $true)]$Inputs)
    $inFile = Join-Path $RuntimeDir 'setup-inputs.json'
    $outFile = Join-Path $RuntimeDir "setup-$Action.json"
    Write-EslUtf8File -Path $inFile -Text ($Inputs | ConvertTo-Json -Depth 6)
    Invoke-EslNative "설정 파일 $Action" $VenvPy @((Join-Path $PSScriptRoot 'setup_config.py'), $Action, '--inputs', $inFile, '--out', $outFile) '위 오류를 확인하세요(설정 파일 형식 등)'
    return (Get-Content -Raw -Encoding UTF8 -LiteralPath $outFile | ConvertFrom-Json)
}

function Write-EslConfigValidation {
    <# setup_config.py write 결과의 백업·작성·검증 결과를 출력. 검증 오류가 있으면 $false. #>
    param([Parameter(Mandatory = $true)]$Result)
    foreach ($b in @($Result.write.backups)) { if ($b) { Write-EslStep "바꾸기 전 사본: $b" } }
    foreach ($w in @($Result.write.written)) { if ($w) { Write-EslStep "작성: $w" } }
    foreach ($w in @($Result.write.created)) { if ($w) { Write-EslStep "폴더 생성: $w" } }
    # v0.8.0: OptiStruct 경로 자동 감지·업로드 확장자 보충 결과 1줄씩(setup_config.py write 가 만든 문구)
    if ($Result.write.opt_autodetect -and $Result.write.opt_autodetect.line) { Write-EslStep $Result.write.opt_autodetect.line }
    if ($Result.write.ext_supplement -and $Result.write.ext_supplement.line) { Write-EslStep $Result.write.ext_supplement.line }
    # v0.9.0: 비드 DOE paicad 경로 자동 감지(bead_doe.paicad.exe) 결과 1줄, 감지 못 했으면 안내 1줄
    if ($Result.write.doe_autodetect -and $Result.write.doe_autodetect.line) { Write-EslStep $Result.write.doe_autodetect.line } elseif ($Result.doe_autodetect -and $Result.doe_autodetect.hint) { Write-EslStep $Result.doe_autodetect.hint }
    foreach ($w in @($Result.warnings)) { if ($w) { Write-Warning $w } }
    $v = $Result.write.validation
    if ($v.ok -eq $false) {
        foreach ($i in @($v.issues)) { if ($i) { Write-Warning "설정 검증: $i" } }
        Write-Warning "설정 검증 오류가 있습니다 — 백엔드는 뜨지만 쓰기 API는 503, 워커는 설정 오류로 작업을 받지 못합니다. $($Result.config_path) 를 고친 뒤 Stop/Start-ScheduledTask ESL-Worker, ESL-Backend"
        return $false
    }
    Write-EslStep '설정 검증 통과'
    return $true
}

function Format-EslDashboardEnvPlan {
    <# 확인 표 한 칸: setup_config.py plan의 dashboard_env(대시보드 .env 연결 키 계획) → "VITE_ESL_TARGET 추가, SIMDASH_ESL_ENABLED 이미 있음 (경로)". #>
    param($Plan)
    if (-not $Plan) { return '(대시보드 없음 — 끝에 넣을 줄 안내)' }
    if (-not $Plan.exists) { return "$($Plan.path) 없음 — 끝에 넣을 줄 안내" }
    $parts = @(@($Plan.rows) | ForEach-Object { "$($_.key) $($_.action)" })
    $tail = if (@($Plan.add).Count) { ' — 바꾸기 전 _backup에 사본, 대시보드 재시작 필요' } else { '' }
    return "$($parts -join ', ')$tail ($($Plan.path))"
}

function Write-EslConnectGuide {
    <#
      접속 연결 안내(설치·업데이트 끝, physicsai Write-PhysicsAIConnectGuide와 같은 문구). 기본: 대시보드 Vite 프록시(/esl → 이 백엔드, 경로 그대로)
      + 백엔드의 프런트 직접 서빙(esl_platform.yaml server.frontend_root). Caddy는 대안.
      git 폴더 설치는 setup_config.py가 대시보드 .env에 두 키를 없을 때만 추가한다(-EnvResult = 그 결과: write.dashboard_env). 이 함수는 .env를 읽기만 한다.
      -Bundle(묶음 install.ps1): Caddy 기준 안내 + Vite 프록시를 고르는 방법.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][int]$Port, [string]$BasePath = '/esl', [string]$DashboardRoot = '', [string]$FrontendRoot = '',
          [string]$SnippetDir = '', $EnvResult = $null, [switch]$Bundle)
    $b = '/' + $BasePath.Trim('/')
    $envFile = if ($DashboardRoot) { [IO.Path]::Combine($DashboardRoot, '.env') } else { '' }   # Join-Path는 없는 드라이브에서 오류
    $target = "http://127.0.0.1:$Port"
    $hasOn = $false; $hasTarget = $false
    if ($envFile -and (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        $hasOn = [bool](Select-String -LiteralPath $envFile -Pattern '^\s*SIMDASH_ESL_ENABLED\s*=\s*"?(true|1|yes|on)"?\s*$' -Quiet)
        $hasTarget = [bool](Select-String -LiteralPath $envFile -Pattern ('^\s*VITE_ESL_TARGET\s*=\s*"?' + [regex]::Escape($target) + '/?"?\s*$') -Quiet)
    }
    $where = if ($envFile) { $envFile } else { '대시보드 .env' }
    $snippet = if ($SnippetDir) { [IO.Path]::Combine($SnippetDir, 'esl.caddy') } else { 'deploy\caddy\esl.caddy' }
    if ($Bundle) {
        Write-EslStep "  1) (묶음 설치 — Caddy 기준) 대시보드 Caddyfile 사이트 블록 안, catch-all handle 앞(physicsai 스니펫 옆)에 $snippet 내용을 넣고"
        Write-EslStep "     Caddy 환경변수 ESL_PORT=$Port , ESL_FRONTEND_ROOT=$FrontendRoot 로 Caddy 설정을 다시 읽으세요"
        Write-EslStep "     Caddy 없이 대시보드 Vite 프록시로 쓰려면: 설정 server.frontend_root: $($FrontendRoot.Replace('\', '/')) (백엔드 재시작) +"
        Write-EslStep "     $where 에 VITE_ESL_TARGET=$target , SIMDASH_ESL_ENABLED=true$(if ($hasOn -and $hasTarget) { ' — 이미 들어 있음' } else { ' 를 넣고 대시보드를 다시 시작하세요' })"
        Write-EslStep "  2) 접속: http://<대시보드 주소>$b/ (대시보드에 로그인한 상태로). 이 PC 확인용 health: $target$b/api/health"
        return
    }
    $added = @(if ($EnvResult) { @($EnvResult.added) | Where-Object { $_ } })
    $state = ' 를 넣고 대시보드를 다시 시작하세요'
    if ($added.Count) { $state = " — 추가함($($added -join ', '), 이전 .env 사본: $($EnvResult.backup)). 대시보드를 다시 시작하세요" }
    elseif ($hasOn -and $hasTarget) { $state = ' — 이미 들어 있음' }
    Write-EslStep "  1) $where 에 VITE_ESL_TARGET=$target , SIMDASH_ESL_ENABLED=true$state"
    Write-EslStep "     (대시보드 Vite가 $b 전체를 이 백엔드로 넘기고, 백엔드가 프런트 $FrontendRoot 를 $b/ 아래에 서빙 — 설정 server.frontend_root)"
    Write-EslStep "     대시보드는 ESL 연결이 들어간 버전이어야 합니다(사이드바 '등가정적하중' 버튼·$b 프록시 — simdashboard PR #56)."
    Write-EslStep "     대시보드 백엔드가 8000이 아닌 포트면 설정 auth.dashboard_internal_url 을 그 포트로 바꾸고 ESL 작업을 재시작하세요"
    Write-EslStep "  2) 접속: 대시보드 로그인 → 사이드바 'AI 예측' 아래 '등가정적하중' (또는 http://<대시보드 주소>$b/). 이 PC 확인용 health: $target$b/api/health"
    Write-EslStep "  Caddy를 쓰는 설치: $snippet (Caddy 환경변수 ESL_PORT=$Port, ESL_FRONTEND_ROOT=$FrontendRoot)"
}
