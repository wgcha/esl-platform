# esl_upload_lib.ps1 -- PC 추출 결과 자동 올리기(계약 docs/contracts/esl_p3_ux.md §9.1·§9.2, 업로드 API §1.1·§8)
#   esl_run.ps1 이 dot-source 한다(update.ps1 이 versions\<버전>\ 에 함께 배포).
#
#   서버 주소 : esl_deploy.json 의 server_url (예 http://<대시보드 주소>/esl, API = <server_url>/api)
#   토큰      : %LOCALAPPDATA%\esl\client_token.bin  (DPAPI CurrentUser 로 암호화, 평문 저장 금지)
#   이어 올리기: %LOCALAPPDATA%\esl\uploads.json    (기준 파일 경로·크기·mtime -> upload_id)
#
# HTTP 는 System.Net.Http.HttpClient(Invoke-WebRequest 아님): 청크마다 FileStream 에서 읽은 버퍼 하나만 메모리에 둔다.
# 시스템 프록시를 따르고(사내 주소), 루프백 주소면 프록시를 쓰지 않는다.
# Windows 전용 부분(DPAPI, 파일 선택 창, 브라우저 열기)은 아래 함수 몇 개에만 있다 - 시험은 이 함수들을 바꿔 끼워
# Linux pwsh 에서 나머지를 실제로 실행한다(tests/windows/test_pc_upload_client.py). PowerShell 5.1 호환 문법만 쓴다.

$EslAllowedExt = @('.rad', '.inc', '.k', '.csv', '.json', '.txt', '.tcl')
$EslSegmentBad = '[\x00-\x1f\x7f<>:"|?*\\&^%!]'
$EslReserved = '^(con|prn|aux|nul|com[0-9]|lpt[0-9]|conin\$|conout\$)$'
$EslRetries = 5
$EslRetryBaseMs = 1000
$EslHttpTimeoutSec = 900

function Say([string]$Message, [string]$Color = 'Gray') { Write-Host $Message -ForegroundColor $Color }

function Get-EslHome { return (Join-Path $env:LOCALAPPDATA 'esl') }

# ---- Windows 전용(시험에서 바꿔 끼움) -----------------------------------------------------------

function Read-EslInput([string]$Prompt) { return (Read-Host $Prompt) }

function Test-EslWindows { return ($env:OS -eq 'Windows_NT') }

# pwsh/powershell -NonInteractive 로 실행 중이면 $true(묻지 않고 안전한 기본값을 쓴다)
function Test-EslNonInteractive {
    foreach ($a in @([Environment]::GetCommandLineArgs())) { if ([string]$a -match '^-noni') { return $true } }
    return $false
}

# 문자열 -> DPAPI(CurrentUser) 암호문. Windows 가 아니면 거부(다른 OS 의 ConvertFrom-SecureString 은 암호화하지 않음).
function Protect-EslSecret([string]$Plain) {
    if (-not (Test-EslWindows)) { throw 'DPAPI 는 Windows 에서만 쓸 수 있습니다(토큰을 평문으로 저장하지 않음).' }
    $sec = ConvertTo-SecureString -String $Plain -AsPlainText -Force
    return (ConvertFrom-SecureString -SecureString $sec)
}

function Unprotect-EslSecret([string]$Cipher) {
    if (-not (Test-EslWindows)) { throw 'DPAPI 는 Windows 에서만 쓸 수 있습니다.' }
    $sec = ConvertTo-SecureString -String $Cipher
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

# rad 파일 선택 창. 창을 못 띄우면 경로를 입력받는다. 취소 = ''.
function Select-EslRadFile([string]$InitialDir, [string]$Title) {
    if (Test-EslWindows) {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            $dlg = New-Object System.Windows.Forms.OpenFileDialog
            $dlg.Title = $Title
            $dlg.Filter = 'Radioss Starter (*.rad)|*.rad|All files (*.*)|*.*'
            if ($InitialDir -and (Test-Path -LiteralPath $InitialDir -PathType Container)) { $dlg.InitialDirectory = $InitialDir }
            $dlg.Multiselect = $false
            if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { return $dlg.FileName }
            return ''
        }
        catch { Say "  파일 선택 창을 열지 못했습니다: $($_.Exception.Message)" 'Yellow' }
    }
    $line = Read-EslInput "$Title - rad 파일 경로(Enter = 올리지 않음)"
    if (-not $line) { return '' }
    return $line.Trim().Trim('"').Trim()
}

function Open-EslBrowser([string]$Url) {
    try { Start-Process -FilePath $Url | Out-Null }
    catch { Say "  브라우저를 열지 못했습니다. 주소를 직접 여세요: $Url" 'Yellow' }
}

# ---- 설정·경로 ------------------------------------------------------------------------------

function Test-EslPathUnder([string]$Child, [string]$Parent) {
    if (-not $Child -or -not $Parent) { return $false }
    $sep = [IO.Path]::DirectorySeparatorChar
    $c = [IO.Path]::GetFullPath($Child).TrimEnd('\', '/') + $sep
    $p = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/') + $sep
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

function ConvertTo-EslServerUrl([string]$Value) {
    if (-not $Value) { return '' }
    $v = $Value.Trim().Trim('"').Trim().TrimEnd('/')
    if ($v -notmatch '^https?://[^/\s]+') { throw "서버 주소는 http:// 또는 https:// 로 시작해야 합니다: $Value" }
    return $v
}

# esl_deploy.json 의 server_url. 비어 있으면 묻고 설정 파일에 저장한다.
function Get-EslServerUrl([string]$ConfigPath, $Cfg) {
    $url = ''
    if ($Cfg -and ($Cfg.PSObject.Properties.Name -contains 'server_url')) { $url = [string]$Cfg.server_url }
    if ($url) { return (ConvertTo-EslServerUrl $url) }
    Say '  ESL 서버 주소가 설정되지 않았습니다(처음 한 번만 묻습니다).' 'Yellow'
    for ($i = 0; $i -lt 3; $i++) {
        $line = Read-EslInput '  ESL 서버 주소(예 http://<대시보드 주소>/esl)'
        try { $url = ConvertTo-EslServerUrl $line } catch { Say "  $($_.Exception.Message)" 'Red'; $url = '' }
        if ($url) { break }
    }
    if (-not $url) { throw '서버 주소가 없어 올릴 수 없습니다. 설정 server_url 을 채우세요: ' + $ConfigPath }
    if ($Cfg) {
        if ($Cfg.PSObject.Properties.Name -contains 'server_url') { $Cfg.server_url = $url }
        else { $Cfg | Add-Member -NotePropertyName 'server_url' -NotePropertyValue $url }
        if ($ConfigPath) {
            $json = $Cfg | ConvertTo-Json -Depth 5
            [IO.File]::WriteAllText($ConfigPath, $json, (New-Object Text.UTF8Encoding($false)))
            Say "  서버 주소를 저장했습니다: $ConfigPath" 'Green'
        }
    }
    return $url
}

function Write-EslTextFile([string]$Path, [string]$Text) {
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $tmp = $Path + '.tmp'
    [IO.File]::WriteAllText($tmp, $Text, (New-Object Text.UTF8Encoding($false)))
    if ([IO.File]::Exists($Path)) { [IO.File]::Replace($tmp, $Path, [NullString]::Value) }
    else { [IO.File]::Move($tmp, $Path) }
}

# ---- HTTP -----------------------------------------------------------------------------------

function Test-EslLoopback([string]$Url) {
    $u = New-Object Uri($Url)
    if ($u.IsLoopback) { return $true }
    $h = $u.Host.Trim('[', ']')
    return ($h -ieq 'localhost' -or $h -like '127.*' -or $h -eq '::1')
}

function New-EslHttpClient([string]$ServerUrl, [int]$TimeoutSec = $EslHttpTimeoutSec) {
    try { Add-Type -AssemblyName System.Net.Http } catch { }
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
    $handler = New-Object System.Net.Http.HttpClientHandler
    if (Test-EslLoopback $ServerUrl) {
        $handler.UseProxy = $false
    }
    else {
        $handler.UseProxy = $true
        $proxy = [Net.WebRequest]::GetSystemWebProxy()
        if ($proxy) {
            $proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials
            $handler.Proxy = $proxy
        }
    }
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
    $client.DefaultRequestHeaders.ExpectContinue = $false
    return $client
}

function New-EslContext([string]$ServerUrl, $Client) {
    if (-not $Client) { $Client = New-EslHttpClient $ServerUrl }
    return [pscustomobject]@{
        ServerUrl = $ServerUrl; ApiBase = ($ServerUrl + '/api'); Client = $Client
        Token = ''; ProjectId = ''; User = ''; TokenPath = (Join-Path (Get-EslHome) 'client_token.bin')
        StatePath = (Join-Path (Get-EslHome) 'uploads.json')
        Retries = $EslRetries; RetryBaseMs = $EslRetryBaseMs
    }
}

function New-EslAuthError([string]$Message) {
    $e = New-Object Exception($Message)
    $e.Data['esl_auth'] = $true
    return $e
}

function Test-EslAuthError($ErrorRecord) {
    $ex = $ErrorRecord.Exception
    while ($ex) {
        if ($ex.Data -and $ex.Data['esl_auth']) { return $true }
        $ex = $ex.InnerException
    }
    return $false
}

# 오류 응답 {detail:{code,message,...}} 에서 code·message
function Get-EslErrorInfo($Resp) {
    $code = ''; $msg = ''
    if ($Resp.Json -and ($Resp.Json.PSObject.Properties.Name -contains 'detail')) {
        $d = $Resp.Json.detail
        if ($d -is [string]) { $msg = $d }
        elseif ($d -is [Array]) { $msg = (@($d | ForEach-Object { $_.msg }) -join '; ') }
        else { $code = [string]$d.code; $msg = [string]$d.message }
    }
    if (-not $msg) { $msg = $Resp.Text }
    if ($msg -and $msg.Length -gt 300) { $msg = $msg.Substring(0, 300) }
    return [pscustomobject]@{ Code = $code; Message = $msg; Status = $Resp.Status }
}

function Format-EslError($Resp, [string]$What) {
    $i = Get-EslErrorInfo $Resp
    return ("{0} 실패 (HTTP {1} {2}): {3}" -f $What, $i.Status, $i.Code, $i.Message)
}

# 요청 한 번(+ 네트워크 오류·5xx·429 는 지수 백오프로 최대 Retries 회 재시도).
# 401 은 토큰 문제로 보고 New-EslAuthError 를 던진다(-NoAuth 면 그대로 돌려줌). 그 밖의 상태는 그대로 돌려준다.
function Invoke-EslHttp {
    param($Ctx, [string]$Method, [string]$Path, $Body = $null, [byte[]]$Bytes = $null, [int]$Count = 0,
        [string]$ChunkSha = '', [switch]$NoAuth)
    $attempt = 0
    while ($true) {
        $req = New-Object System.Net.Http.HttpRequestMessage((New-Object System.Net.Http.HttpMethod($Method)), ($Ctx.ApiBase + $Path))
        [void]$req.Headers.TryAddWithoutValidation('X-ESL-Request', '1')
        [void]$req.Headers.TryAddWithoutValidation('Accept', 'application/json')
        if (-not $NoAuth -and $Ctx.Token) { [void]$req.Headers.TryAddWithoutValidation('Authorization', 'Bearer ' + $Ctx.Token) }
        if ($null -ne $Bytes) {
            $content = New-Object System.Net.Http.ByteArrayContent($Bytes, 0, $Count)
            $content.Headers.ContentType = New-Object System.Net.Http.Headers.MediaTypeHeaderValue('application/octet-stream')
            $req.Content = $content
            if ($ChunkSha) { [void]$req.Headers.TryAddWithoutValidation('X-Chunk-Sha256', $ChunkSha) }
        }
        elseif ($null -ne $Body) {
            $json = $Body | ConvertTo-Json -Depth 8 -Compress
            $req.Content = New-Object System.Net.Http.StringContent($json, [Text.Encoding]::UTF8, 'application/json')
        }
        $status = 0; $text = ''; $netErr = ''
        try {
            $resp = $Ctx.Client.SendAsync($req).GetAwaiter().GetResult()
            try {
                $status = [int]$resp.StatusCode
                $text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            }
            finally { $resp.Dispose() }
        }
        catch {
            $ex = $_.Exception
            while ($ex.InnerException) { $ex = $ex.InnerException }
            $netErr = $ex.Message
            $status = 0
        }
        finally { $req.Dispose() }
        # -NoAuth(연결 코드 교환): 429 = 코드 잠금이라 재시도하지 않고, 401 = 코드 틀림이라 그대로 돌려준다
        $retryable = ($status -eq 0) -or ($status -eq 429 -and -not $NoAuth) -or ($status -eq 500) -or ($status -eq 502) -or ($status -eq 503) -or ($status -eq 504)
        if (-not $retryable) {
            $obj = $null
            if ($text) { try { $obj = $text | ConvertFrom-Json } catch { $obj = $null } }
            $r = [pscustomobject]@{ Status = $status; Json = $obj; Text = $text }
            if ($status -eq 401 -and -not $NoAuth) {
                throw (New-EslAuthError ("서버가 PC 연결을 거부했습니다(토큰 만료·폐기): " + (Get-EslErrorInfo $r).Message))
            }
            return $r
        }
        $why = $(if ($status -eq 0) { "네트워크 오류: $netErr" } else { "서버 응답 $status" })
        if ($attempt -ge $Ctx.Retries) {
            throw ("{0} {1} 실패 - {2} ({3}회 재시도 후). 다시 실행하면 이어 올립니다." -f $Method, $Path, $why, $Ctx.Retries)
        }
        $delay = [int]($Ctx.RetryBaseMs * [Math]::Pow(2, $attempt))
        $attempt++
        Write-Host ''
        Say ("  {0} - {1:N1}초 뒤 다시 시도 ({2}/{3})" -f $why, ($delay / 1000.0), $attempt, $Ctx.Retries) 'Yellow'
        Start-Sleep -Milliseconds $delay
    }
}

# ---- PC 연결(토큰) ----------------------------------------------------------------------------

function Read-EslToken($Ctx) {
    if (-not (Test-Path -LiteralPath $Ctx.TokenPath -PathType Leaf)) { return $null }
    try {
        $cipher = ([IO.File]::ReadAllText($Ctx.TokenPath)).Trim()
        $info = (Unprotect-EslSecret $cipher) | ConvertFrom-Json
    }
    catch {
        Say "  저장된 PC 연결을 읽지 못했습니다(다시 연결합니다): $($_.Exception.Message)" 'Yellow'
        return $null
    }
    if ([string]$info.server_url -ne $Ctx.ServerUrl) {
        Say "  저장된 PC 연결의 서버($($info.server_url))가 설정과 달라 다시 연결합니다." 'Yellow'
        return $null
    }
    if ($info.expires_at) {
        try {
            $exp = [DateTimeOffset]::Parse([string]$info.expires_at, [Globalization.CultureInfo]::InvariantCulture)
            if ($exp -le [DateTimeOffset]::UtcNow) { Say '  PC 연결이 만료되었습니다(다시 연결합니다).' 'Yellow'; return $null }
        }
        catch { }
    }
    if (-not $info.token -or -not $info.project_id) { return $null }
    return $info
}

function Get-EslProjectId($Project) {
    if ($null -eq $Project) { return '' }
    if ($Project -is [string]) { return $Project }
    foreach ($k in @('id', 'project_id', 'slug')) {
        if ($Project.PSObject.Properties.Name -contains $k -and $Project.$k) { return [string]$Project.$k }
    }
    return ''
}

# 연결 코드 -> POST /client-tokens/exchange -> 토큰을 DPAPI 로 암호화해 저장
function Connect-EslClient($Ctx, [switch]$Force) {
    if (-not $Force) {
        $info = Read-EslToken $Ctx
        if ($info) {
            $Ctx.Token = [string]$info.token; $Ctx.ProjectId = [string]$info.project_id; $Ctx.User = [string]$info.user
            return $Ctx
        }
    }
    Say ''
    Say '  이 PC 를 ESL 에 연결합니다(처음 한 번, 만료·폐기 시 다시).' 'Cyan'
    Say "  ESL 화면 새 Case -> 'PC에서 추출해 올리기' -> 'PC 연결 코드 만들기' 의 6자리 코드를 입력하세요."
    Say "  서버: $($Ctx.ServerUrl)" 'DarkGray'
    $device = $env:COMPUTERNAME
    if (-not $device) { $device = [Environment]::MachineName }
    for ($i = 0; $i -lt 5; $i++) {
        $code = Read-EslInput '  연결 코드'
        if ($null -eq $code) { $code = '' }
        $code = $code.Trim()
        if (-not $code) { throw '연결 코드를 입력하지 않았습니다.' }
        $r = Invoke-EslHttp $Ctx 'POST' '/client-tokens/exchange' @{ code = $code; device_name = $device } -NoAuth
        if ($r.Status -eq 200 -or $r.Status -eq 201) {
            $pid2 = Get-EslProjectId $r.Json.project
            if (-not $r.Json.token -or -not $pid2) { throw '서버 응답에 token·project 가 없습니다: ' + $r.Text }
            $user = $r.Json.user
            if ($user -and -not ($user -is [string])) {
                if ($user.PSObject.Properties.Name -contains 'username') { $user = $user.username } else { $user = ($user | ConvertTo-Json -Compress) }
            }
            $save = [ordered]@{ server_url = $Ctx.ServerUrl; token = [string]$r.Json.token; project_id = $pid2
                user = [string]$user; expires_at = [string]$r.Json.expires_at; device = $device; saved_at = (Get-Date).ToString('o') }
            $plain = $save | ConvertTo-Json -Compress
            Write-EslTextFile $Ctx.TokenPath (Protect-EslSecret $plain)
            $Ctx.Token = $save.token; $Ctx.ProjectId = $pid2; $Ctx.User = $save.user
            Say ("  연결됨: 프로젝트 {0}, 사용자 {1}, 만료 {2}" -f $pid2, $save.user, $save.expires_at) 'Green'
            return $Ctx
        }
        Say ('  ' + (Format-EslError $r '연결')) 'Red'
        if ($r.Status -eq 429) { throw '연결 코드를 여러 번 잘못 입력해 잠시 잠겼습니다. 잠시 뒤 ESL 화면에서 새 코드를 만들어 다시 실행하세요.' }
    }
    throw '연결하지 못했습니다. ESL 화면에서 새 코드를 만들어 다시 실행하세요.'
}

# ---- rad include 수집(서버 esl/rad/parser.py scan_includes 와 같은 규칙) --------------------------

function Get-EslIncludeSpec([string]$Line) {
    return $Line.Trim().Trim('"').Trim("'").Trim()
}

function Read-EslIncludeSpecsWith([string]$Path, [Text.Encoding]$Encoding) {
    $specs = New-Object System.Collections.ArrayList
    $sr = New-Object IO.StreamReader($Path, $Encoding, $true)
    try {
        $pending = $false
        while ($null -ne ($line = $sr.ReadLine())) {
            if ($pending) {
                if (-not $line.Trim() -or $line.StartsWith('#')) { continue }
                $pending = $false
                [void]$specs.Add((Get-EslIncludeSpec $line))
                continue
            }
            if ($line.StartsWith('#')) {
                if ($line.Length -ge 8 -and $line.Substring(0, 8) -ieq '#include') { [void]$specs.Add((Get-EslIncludeSpec $line.Substring(8))) }
                continue
            }
            if ($line.StartsWith('/')) {
                $tok = @($line.Split([char[]]@(' ', "`t"), [StringSplitOptions]::RemoveEmptyEntries))
                $head = $(if ($tok.Count -gt 0) { $tok[0] } else { $line })
                $pieces = @($head.Split('/') | Where-Object { $_ })
                $kw = $(if ($pieces.Count -gt 0) { $pieces[0].ToUpperInvariant() } else { '' })
                if ($kw -eq 'END') { break }
                if ($kw -eq 'INCLUDE') {
                    $t = $line.Trim()
                    $rest = $(if ($t.Length -gt 8) { $t.Substring(8).Trim() } else { '' })
                    if ($rest) { [void]$specs.Add((Get-EslIncludeSpec $rest)) } else { $pending = $true }
                }
            }
        }
    }
    finally { $sr.Dispose() }
    return $specs.ToArray()
}

# 줄 단위로 읽는다(파일 전체를 메모리에 올리지 않음). UTF-8 -> cp949 -> latin-1 순서.
function Read-EslIncludeSpecs([string]$Path) {
    $encs = @((New-Object Text.UTF8Encoding($false, $true)))
    try { $encs += [Text.Encoding]::GetEncoding(949, [Text.EncoderFallback]::ExceptionFallback, [Text.DecoderFallback]::ExceptionFallback) } catch { }
    $encs += [Text.Encoding]::GetEncoding(28591)
    foreach ($enc in $encs) {
        try { return @(Read-EslIncludeSpecsWith $Path $enc) }
        catch {
            $ex = $_.Exception; $dec = $false
            while ($ex) { if ($ex -is [Text.DecoderFallbackException]) { $dec = $true }; $ex = $ex.InnerException }
            if (-not $dec) { throw }
        }
    }
    return @()
}

function Test-EslAbsSpec([string]$Name) {
    return ($Name -match '^[A-Za-z]:/' -or $Name.StartsWith('//') -or $Name.StartsWith('/'))
}

function Resolve-EslInclude([string]$Spec, [string]$RootDir, [string]$SrcPath) {
    $name = $Spec.Replace('\', '/')
    $srcDir = Split-Path -Parent ([IO.Path]::GetFullPath($SrcPath))
    $abs = Test-EslAbsSpec $name
    $native = $name.Replace('/', [IO.Path]::DirectorySeparatorChar)
    if ($abs) { $cands = @($native) } else { $cands = @((Join-Path $RootDir $native), (Join-Path $srcDir $native)) }
    $full = @()
    foreach ($c in $cands) {
        $f = $c
        try { $f = [IO.Path]::GetFullPath($c) } catch { }
        $full += $f
        if (Test-Path -LiteralPath $f -PathType Leaf) {
            return [pscustomobject]@{ Spec = $Spec; Source = $SrcPath; Path = $f; Found = $true; Absolute = $abs; ByName = $false; Candidates = $full }
        }
    }
    $base = @($name.TrimEnd('/').Split('/'))[-1]
    if ($base -and $abs) {
        foreach ($d in @($RootDir, $srcDir) | Select-Object -Unique) {
            $c = Join-Path $d $base
            if (Test-Path -LiteralPath $c -PathType Leaf) {
                return [pscustomobject]@{ Spec = $Spec; Source = $SrcPath; Path = [IO.Path]::GetFullPath($c); Found = $true; Absolute = $abs; ByName = $true; Candidates = $full }
            }
        }
    }
    return [pscustomobject]@{ Spec = $Spec; Source = $SrcPath; Path = $full[0]; Found = $false; Absolute = $abs; ByName = $false; Candidates = $full }
}

function Add-EslIncludeWalk([string]$Path, [int]$Depth, [string]$RootDir, $Out, $Seen, [int]$MaxDepth) {
    $key = [IO.Path]::GetFullPath($Path).ToLowerInvariant()
    if ($Seen.ContainsKey($key)) { return }
    $Seen[$key] = $true
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $specs = @()
    try { $specs = @(Read-EslIncludeSpecs $Path) } catch { Say "  include 를 읽지 못했습니다: $Path ($($_.Exception.Message))" 'Yellow'; return }
    foreach ($s in $specs) {
        if (-not $s) { continue }
        $r = Resolve-EslInclude $s $RootDir $Path
        if (-not (@($Out | Where-Object { $_.Path -eq $r.Path }).Count)) { [void]$Out.Add($r) }
        if ($r.Found -and ($Depth + 1) -le $MaxDepth) { Add-EslIncludeWalk $r.Path ($Depth + 1) $RootDir $Out $Seen $MaxDepth }
    }
}

# rad 의 /INCLUDE·#include 를 재귀로 따라간 목록(찾지 못한 것도 Found=$false 로 포함)
function Get-EslRadIncludes([string]$RadPath, [int]$MaxDepth = 8) {
    $root = [IO.Path]::GetFullPath($RadPath)
    $out = New-Object System.Collections.ArrayList
    Add-EslIncludeWalk $root 0 (Split-Path -Parent $root) $out @{} $MaxDepth
    return $out.ToArray()
}

# ---- 올릴 파일 목록 ----------------------------------------------------------------------------

function Test-EslRelSegment([string]$Seg) {
    if (-not $Seg -or $Seg -eq '.' -or $Seg -eq '..' -or $Seg.Length -gt 255) { return $false }
    if ($Seg -match $EslSegmentBad) { return $false }
    if ($Seg -ne $Seg.Trim() -or $Seg.EndsWith('.')) { return $false }
    if ($Seg.Split('.')[0].Trim() -match $EslReserved) { return $false }
    return $true
}

function Test-EslRel([string]$Rel) {
    if ($Rel.Length -gt 400) { return $false }
    foreach ($s in $Rel.Split('/')) { if (-not (Test-EslRelSegment $s)) { return $false } }
    return ($EslAllowedExt -contains [IO.Path]::GetExtension($Rel).ToLowerInvariant())
}

function Get-EslRelativeRel([string]$Path, [string]$BaseDir) {
    $sep = [IO.Path]::DirectorySeparatorChar
    $b = [IO.Path]::GetFullPath($BaseDir).TrimEnd('\', '/') + $sep
    $p = [IO.Path]::GetFullPath($Path)
    return $p.Substring($b.Length).Replace('\', '/')
}

function New-EslPlanFile([string]$Rel, [string]$Path) {
    $fi = New-Object IO.FileInfo($Path)
    return [pscustomobject]@{ Rel = $Rel; Path = $fi.FullName; Size = [int64]$fi.Length; Mtime = $fi.LastWriteTimeUtc.Ticks }
}

# 결과 폴더(done.json) + rad + include -> rel 규칙(results/<폴더>/..., rad/...) 목록과 경고·문제
#   include: rad 폴더 아래 = rad/<상대경로>, 절대경로 include = rad/<파일 이름>(서버가 파일 이름으로 rad 폴더에서 찾음)
#   rad 폴더 밖 절대경로 include(PC 의 다른 폴더 파일)는 Outside 로만 알리고 -AllowOutside(사용자가 Y 로 확인)일 때만 올린다.
#   rad 폴더 밖 상대경로(..\)는 서버에서 찾을 수 없어 문제로 둔다(올리지 않음).
function Get-EslUploadPlan([string]$ResultsDir, [string]$RadPath, [int]$MaxDepth = 8, [switch]$AllowOutside) {
    $files = New-Object System.Collections.ArrayList
    $outside = New-Object System.Collections.ArrayList
    $warn = New-Object System.Collections.ArrayList
    $prob = New-Object System.Collections.ArrayList
    $missing = New-Object System.Collections.ArrayList
    $byRel = @{}
    $add = {
        param($rel, $path)
        $k = $rel.ToLowerInvariant()
        if ($byRel.ContainsKey($k)) {
            if ($byRel[$k] -ne [IO.Path]::GetFullPath($path)) { [void]$prob.Add("같은 이름으로 올릴 파일이 둘입니다: $rel ($($byRel[$k]), $path)") }
            return
        }
        if (-not (Test-EslRel $rel)) { [void]$prob.Add("올릴 수 없는 이름·확장자입니다: $rel (허용 $($EslAllowedExt -join ' '))"); return }
        $byRel[$k] = [IO.Path]::GetFullPath($path)
        [void]$files.Add((New-EslPlanFile $rel $path))
    }

    if ($ResultsDir) {
        $rd = [IO.Path]::GetFullPath($ResultsDir).TrimEnd('\', '/')
        if (-not (Test-Path -LiteralPath (Join-Path $rd 'done.json') -PathType Leaf)) {
            [void]$prob.Add("결과 폴더에 done.json 이 없습니다: $rd (ESL_extract.bat 이 만든 csv 폴더를 지정하세요)")
        }
        $leaf = Split-Path -Leaf $rd
        $skipped = 0
        foreach ($f in @(Get-ChildItem -LiteralPath $rd -Recurse -File -Force | Sort-Object FullName)) {
            $ext = $f.Extension.ToLowerInvariant()
            if ($EslAllowedExt -notcontains $ext) { $skipped++; continue }
            & $add ("results/$leaf/" + (Get-EslRelativeRel $f.FullName $rd)) $f.FullName
        }
        if ($skipped) { [void]$warn.Add("결과 폴더에서 올리지 않는 파일 $skipped 개(.log 등 허용 확장자 밖)") }
    }
    if ($RadPath) {
        $rad = [IO.Path]::GetFullPath($RadPath)
        $radDir = Split-Path -Parent $rad
        & $add ('rad/' + (Split-Path -Leaf $rad)) $rad
        foreach ($inc in @(Get-EslRadIncludes $rad $MaxDepth)) {
            if (-not $inc.Found) {
                [void]$missing.Add($inc)
                $where = (@($inc.Candidates | Select-Object -Unique) -join ', ')
                if ($inc.Absolute) { [void]$warn.Add("include 를 찾을 수 없습니다(절대경로 - 이 PC 에 없는 드라이브·폴더?): $($inc.Spec)  <- $($inc.Source)") }
                else { [void]$warn.Add("include 를 찾을 수 없습니다: $($inc.Spec)  <- $($inc.Source)  (찾은 위치: $where)") }
                continue
            }
            if ($inc.Absolute) {
                $rel = 'rad/' + (Split-Path -Leaf $inc.Path)
                if (-not (Test-EslPathUnder $inc.Path $radDir)) {
                    [void]$outside.Add([pscustomobject]@{ Spec = $inc.Spec; Path = $inc.Path; Source = $inc.Source; Rel = $rel })
                    if (-not $AllowOutside) {
                        [void]$warn.Add("rad 폴더 밖 include 는 올리지 않습니다(확인하지 않음): $($inc.Spec)")
                        continue
                    }
                    [void]$warn.Add("rad 폴더 밖 include 를 확인 후 rad 폴더로 올립니다: $($inc.Spec) -> $rel")
                }
                elseif (-not $inc.ByName) { [void]$warn.Add("절대경로 include 는 rad 폴더로 올립니다(서버가 파일 이름으로 찾음): $($inc.Spec) -> $rel") }
            }
            elseif (Test-EslPathUnder $inc.Path $radDir) { $rel = 'rad/' + (Get-EslRelativeRel $inc.Path $radDir) }
            else {
                [void]$prob.Add("include 가 rad 폴더 밖 상대경로라 서버에서 찾을 수 없습니다: $($inc.Spec) <- $($inc.Source) (include 파일을 rad 폴더 아래로 옮기세요)")
                continue
            }
            & $add $rel $inc.Path
        }
    }
    $total = [int64]0
    foreach ($f in $files) { $total += $f.Size }
    return [pscustomobject]@{ Files = $files.ToArray(); Warnings = $warn.ToArray(); Problems = $prob.ToArray(); Missing = $missing.ToArray()
        RadDir = $(if ($RadPath) { Split-Path -Parent ([IO.Path]::GetFullPath($RadPath)) } else { '' }); TotalBytes = $total
        Outside = $outside.ToArray(); OutsideAllowed = [bool]$AllowOutside; ResultsDir = $ResultsDir; RadPath = $RadPath; MaxDepth = $MaxDepth }
}

# rad 폴더 밖 include 목록을 보여 주고 명시 확인(Y)을 받으면 그 파일까지 넣은 계획을 돌려준다.
# 확인하지 않거나(기본 N) -NonInteractive 실행이면 제외한 계획 그대로.
function Confirm-EslOutsideIncludes($Plan) {
    $out = @($Plan.Outside)
    if ($out.Count -eq 0 -or $Plan.OutsideAllowed) { return $Plan }
    Say ("  rad 폴더 밖 include {0}개 - PC 의 다른 폴더 파일입니다. 확인 없이는 올리지 않습니다:" -f $out.Count) 'Yellow'
    foreach ($o in $out) { Say ("    - {0}  ({1})  <- {2}" -f $o.Spec, $o.Path, $o.Source) 'Yellow' }
    if (Test-EslNonInteractive) { Say '  비대화형 실행: rad 폴더 밖 include 는 올리지 않습니다.' 'Yellow'; return $Plan }
    $a = ''
    try { $a = Read-EslInput '  위 파일들도 서버로 올릴까요? (y/N)' } catch { $a = '' }
    if ($a -and $a.Trim() -match '^(y|yes|예|ㅇ)$') {
        return (Get-EslUploadPlan $Plan.ResultsDir $Plan.RadPath $Plan.MaxDepth -AllowOutside)
    }
    Say '  rad 폴더 밖 include 는 올리지 않습니다.' 'Yellow'
    return $Plan
}

# ---- 이어 올리기 상태(uploads.json) -----------------------------------------------------------

# 기준 파일(h3d 또는 결과 폴더의 done.json) 경로·크기·mtime
function Get-EslUploadKey([string]$AnchorPath) {
    $fi = New-Object IO.FileInfo([IO.Path]::GetFullPath($AnchorPath))
    return ('{0}|{1}|{2}' -f $fi.FullName.ToLowerInvariant(), $fi.Length, $fi.LastWriteTimeUtc.Ticks)
}

function Get-EslPlanFingerprint($Plan) {
    $lines = @($Plan.Files | ForEach-Object { '{0}|{1}|{2}' -f $_.Rel.ToLowerInvariant(), $_.Size, $_.Mtime } | Sort-Object)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $h = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))) } finally { $sha.Dispose() }
    return (-join ($h | ForEach-Object { $_.ToString('x2') }))
}

function Read-EslUploadState([string]$Path) {
    $state = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $state }
    try {
        $j = [IO.File]::ReadAllText($Path) | ConvertFrom-Json
        foreach ($p in $j.PSObject.Properties) { $state[$p.Name] = $p.Value }
    }
    catch { Say "  이어 올리기 기록을 읽지 못했습니다(새로 올립니다): $Path" 'Yellow' }
    return $state
}

function Save-EslUploadState([string]$Path, $State) {
    $o = [ordered]@{}
    foreach ($k in @($State.Keys | Sort-Object)) { $o[$k] = $State[$k] }
    Write-EslTextFile $Path ($o | ConvertTo-Json -Depth 6)
}

# ---- 진행률 ------------------------------------------------------------------------------------

function Format-EslBytes([double]$B) {
    if ($B -ge 1GB) { return ('{0:N2} GB' -f ($B / 1GB)) }
    if ($B -ge 1MB) { return ('{0:N1} MB' -f ($B / 1MB)) }
    if ($B -ge 1KB) { return ('{0:N0} KB' -f ($B / 1KB)) }
    return ('{0:N0} B' -f $B)
}

function New-EslProgress([int64]$Total, [int64]$Already) {
    return [pscustomobject]@{ Total = $Total; Done = $Already; Sent = [int64]0; Watch = [Diagnostics.Stopwatch]::StartNew(); LastMs = [int64]-1000 }
}

function Show-EslProgress($P, [string]$Name, [switch]$Final) {
    $ms = $P.Watch.ElapsedMilliseconds
    if (-not $Final -and ($ms - $P.LastMs) -lt 500) { return }
    $P.LastMs = $ms
    $pct = $(if ($P.Total -gt 0) { 100.0 * $P.Done / $P.Total } else { 100.0 })
    $sec = [Math]::Max($ms / 1000.0, 0.001)
    $rate = $P.Sent / $sec
    $eta = '--:--'
    if ($rate -gt 0) {
        $left = [TimeSpan]::FromSeconds([Math]::Ceiling(($P.Total - $P.Done) / $rate))
        $eta = $(if ($left.TotalHours -ge 1) { '{0}:{1:mm\:ss}' -f [int][Math]::Floor($left.TotalHours), $left } else { $left.ToString('mm\:ss') })
    }
    $line = ("  [{0,5:N1}%] {1} / {2}  {3}/s  남은 시간 {4}  {5}" -f $pct, (Format-EslBytes $P.Done), (Format-EslBytes $P.Total), (Format-EslBytes $rate), $eta, $Name)
    if ($line.Length -gt 118) { $line = $line.Substring(0, 118) }
    Write-Host ("`r" + $line.PadRight(118)) -NoNewline
    if ($Final) { Write-Host '' }
}

# ---- 업로드 ------------------------------------------------------------------------------------

function Get-EslSha256Hex([byte[]]$Buf, [int]$Count) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $h = $sha.ComputeHash($Buf, 0, $Count) } finally { $sha.Dispose() }
    return (-join ($h | ForEach-Object { $_.ToString('x2') }))
}

# 파일 하나를 offset(서버 received)부터 청크로 보낸다. FileStream 에서 청크 크기 버퍼 하나만 쓴다.
function Send-EslFile($Ctx, [string]$UploadId, $File, $Local, [int64]$Received, [int]$ChunkSize, $Progress) {
    $fi = New-Object IO.FileInfo($Local.Path)
    if (-not $fi.Exists) { throw "올릴 파일이 없어졌습니다: $($Local.Path)" }
    if ($fi.Length -ne [int64]$File.size) { throw "파일 크기가 바뀌었습니다(올리는 중 수정됨?): $($Local.Path) ($($fi.Length) <> $($File.size)) - 다시 실행하세요." }
    $size = [int64]$File.size
    $offset = $Received
    $buf = New-Object byte[] ([int][Math]::Max([int64]1, [Math]::Min([int64]$ChunkSize, [Math]::Max($size, [int64]1))))
    $badSha = 0; $restarted = $false
    $fs = New-Object IO.FileStream($Local.Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite, 1048576)
    try {
        while ($offset -lt $size -or ($size -eq 0 -and $offset -eq 0)) {
            [void]$fs.Seek($offset, [IO.SeekOrigin]::Begin)
            $want = [int][Math]::Min([int64]$buf.Length, $size - $offset)
            $n = 0
            while ($n -lt $want) {
                $k = $fs.Read($buf, $n, $want - $n)
                if ($k -le 0) { break }
                $n += $k
            }
            if ($n -ne $want) { throw "파일을 끝까지 읽지 못했습니다: $($Local.Path)" }
            $sha = Get-EslSha256Hex $buf $n
            $r = Invoke-EslHttp $Ctx 'PUT' ("/uploads/{0}/files/{1}?offset={2}" -f $UploadId, $File.index, $offset) -Bytes $buf -Count $n -ChunkSha $sha
            $info = Get-EslErrorInfo $r
            if ($r.Status -eq 200) {
                $new = [int64]$r.Json.received
                $Progress.Done += ($new - $offset); $Progress.Sent += [Math]::Max([int64]0, $new - $offset)
                $offset = $new
                Show-EslProgress $Progress $File.rel
                if ($r.Json.done -or $size -eq 0) { break }
            }
            elseif ($r.Status -eq 409 -and $info.Code -eq 'UPLOAD_OFFSET_MISMATCH') {
                $new = [int64]$r.Json.detail.received
                Write-Host ''
                Say ("  서버가 받은 크기부터 이어 올립니다: {0} @ {1}" -f $File.rel, (Format-EslBytes $new)) 'DarkGray'
                $Progress.Done += ($new - $offset)
                $offset = $new
            }
            elseif ($r.Status -eq 409 -and $info.Code -eq 'UPLOAD_FILE_DONE') {
                $Progress.Done += ($size - $offset)
                break
            }
            elseif ($r.Status -eq 422 -and $info.Code -eq 'CHUNK_SHA256_MISMATCH' -and $badSha -lt $Ctx.Retries) {
                $badSha++
                Write-Host ''
                Say "  청크 sha256 불일치(전송 중 손상) - 같은 위치로 다시 보냅니다 ($badSha/$($Ctx.Retries))" 'Yellow'
            }
            elseif ($r.Status -eq 422 -and $info.Code -eq 'SHA256_MISMATCH' -and -not $restarted) {
                $restarted = $true
                Write-Host ''
                Say "  파일 sha256 불일치 - 처음부터 다시 올립니다: $($File.rel)" 'Yellow'
                $Progress.Done -= $offset
                $offset = 0
            }
            else { throw (Format-EslError $r "청크 올리기($($File.rel) @ $offset)") }
        }
    }
    finally { $fs.Dispose() }
}

function Get-EslUpload($Ctx, [string]$UploadId) {
    $r = Invoke-EslHttp $Ctx 'GET' "/uploads/$UploadId"
    if ($r.Status -eq 200) { return $r.Json }
    if ($r.Status -eq 404 -or $r.Status -eq 403) { return $null }
    throw (Format-EslError $r '업로드 상태 확인')
}

# 서버 세션 파일(rel,size)이 모두 로컬 목록에 같은 크기로 있으면 이어 쓸 수 있다. 로컬에만 있는 파일 = 추가할 것.
function Compare-EslSession($Up, $Plan) {
    $local = @{}
    foreach ($f in $Plan.Files) { $local[$f.Rel.ToLowerInvariant()] = $f }
    $srv = @{}
    foreach ($f in @($Up.files)) {
        $k = ([string]$f.rel).ToLowerInvariant()
        if (-not $local.ContainsKey($k) -or $local[$k].Size -ne [int64]$f.size) { return [pscustomobject]@{ Ok = $false; Extra = @() } }
        $srv[$k] = $true
    }
    $extra = @($Plan.Files | Where-Object { -not $srv.ContainsKey($_.Rel.ToLowerInvariant()) })
    return [pscustomobject]@{ Ok = $true; Extra = $extra }
}

function ConvertTo-EslFileSpecs($Files) {
    return @($Files | ForEach-Object { [ordered]@{ rel = $_.Rel; size = $_.Size } })
}

function Add-EslUploadFiles($Ctx, [string]$UploadId, $Files) {
    $r = Invoke-EslHttp $Ctx 'POST' "/uploads/$UploadId/files" @{ files = @(ConvertTo-EslFileSpecs $Files) }
    if ($r.Status -ne 200) { throw (Format-EslError $r '파일 추가') }
    Say ("  파일 {0}개를 업로드에 추가했습니다." -f @($Files).Count) 'DarkGray'
    return $r.Json
}

function Send-EslPending($Ctx, $Up, $Plan) {
    $local = @{}
    foreach ($f in $Plan.Files) { $local[$f.Rel.ToLowerInvariant()] = $f }
    $files = @($Up.files)
    $total = [int64]0; $done = [int64]0
    foreach ($f in $files) { $total += [int64]$f.size; $done += [int64]$f.received }
    $todo = @($files | Where-Object { -not $_.done })
    if ($todo.Count -eq 0) { return }
    Say ("  올리기: 파일 {0}개 중 {1}개 남음, {2} / {3}" -f $files.Count, $todo.Count, (Format-EslBytes $done), (Format-EslBytes $total))
    $p = New-EslProgress $total $done
    foreach ($f in $todo) {
        $l = $local[([string]$f.rel).ToLowerInvariant()]
        if (-not $l) { throw "서버 업로드의 파일이 이 PC 목록에 없습니다: $($f.rel)" }
        Send-EslFile $Ctx $Up.upload_id $f $l ([int64]$f.received) ([int]$Up.chunk_size) $p
    }
    Show-EslProgress $p '완료' -Final
    $sec = [Math]::Max($p.Watch.Elapsed.TotalSeconds, 0.001)
    Say ("  보낸 양 {0}, {1:N0}초, 평균 {2}/s" -f (Format-EslBytes $p.Sent), $sec, (Format-EslBytes ($p.Sent / $sec))) 'DarkGray'
}

# complete 가 알려 준 누락 include(rel 'rad/...') -> 로컬 파일
function Find-EslMissingLocal($Missing, $Plan, $Up) {
    $have = @{}
    foreach ($f in @($Up.files)) { $have[([string]$f.rel).ToLowerInvariant()] = $true }
    $add = @(); $lost = @()
    foreach ($m in @($Missing)) {
        $rel = ([string]$m).Replace('\', '/')
        $p = ''
        if ($rel.StartsWith('rad/') -and $Plan.RadDir) {
            $p = Join-Path $Plan.RadDir ($rel.Substring(4).Replace('/', [IO.Path]::DirectorySeparatorChar))
        }
        if ($p -and -not $have.ContainsKey($rel.ToLowerInvariant()) -and (Test-Path -LiteralPath $p -PathType Leaf) -and (Test-EslRel $rel)) {
            $add += (New-EslPlanFile $rel $p)
        }
        else { $lost += $rel }
    }
    return [pscustomobject]@{ Add = $add; Lost = $lost }
}

function Add-EslPlanFiles($Plan, $Files) {
    $all = @($Plan.Files) + @($Files)
    $total = [int64]0
    foreach ($f in $all) { $total += $f.Size }
    return [pscustomobject]@{ Files = $all; Warnings = $Plan.Warnings; Problems = $Plan.Problems; Missing = $Plan.Missing
        RadDir = $Plan.RadDir; TotalBytes = $total; Outside = $Plan.Outside; OutsideAllowed = $Plan.OutsideAllowed
        ResultsDir = $Plan.ResultsDir; RadPath = $Plan.RadPath; MaxDepth = $Plan.MaxDepth }
}

function Get-EslCaseUrl([string]$ServerUrl, [string]$ProjectId, [string]$UploadId) {
    return ('{0}/p/{1}/cases/new?upload={2}' -f $ServerUrl, [Uri]::EscapeDataString($ProjectId), [Uri]::EscapeDataString($UploadId))
}

# 업로드 세션 찾기·만들기 -> 청크 전송 -> complete(누락 include 추가 후 다시) -> 결과
function Invoke-EslUpload($Ctx, $Plan, [string]$Name, [string]$Key) {
    $state = Read-EslUploadState $Ctx.StatePath
    $fp = Get-EslPlanFingerprint $Plan
    $up = $null
    $prev = $state[$Key]
    $added = @()
    if ($prev -and ($prev.PSObject.Properties.Name -contains 'added') -and @($prev.added).Count -gt 0) {
        # 지난번 complete 가 알려 줘 추가로 올린 include 도 이번 목록에 넣는다(세션 비교·이어 올리기용)
        $f = Find-EslMissingLocal @($prev.added) $Plan ([pscustomobject]@{ files = @($Plan.Files | ForEach-Object { [pscustomobject]@{ rel = $_.Rel } }) })
        if (@($f.Add).Count -gt 0) { $Plan = Add-EslPlanFiles $Plan $f.Add; $added = @($f.Add | ForEach-Object { $_.Rel }) }
    }
    if ($prev -and [string]$prev.server_url -eq $Ctx.ServerUrl -and [string]$prev.project_id -eq $Ctx.ProjectId) {
        $old = Get-EslUpload $Ctx ([string]$prev.upload_id)
        if ($old -and ($old.state -eq 'OPEN' -or $old.state -eq 'COMPLETED')) {
            $cmp = Compare-EslSession $old $Plan
            $same = $cmp.Ok -and ([string]$prev.fingerprint -eq $fp -or -not $prev.fingerprint)
            if ($same -and $old.state -eq 'COMPLETED' -and @($cmp.Extra).Count -eq 0) {
                Say "  이미 올린 업로드입니다: $($old.upload_id)" 'Green'
                $up = $old
            }
            elseif ($same -and $old.state -eq 'OPEN') {
                Say ("  이전 업로드를 이어 갑니다: {0} (서버가 받은 양 {1} / {2})" -f $old.upload_id, (Format-EslBytes ([double]$old.received_bytes)), (Format-EslBytes ([double]$old.total_bytes))) 'Green'
                $up = $old
                if (@($cmp.Extra).Count -gt 0) { $up = Add-EslUploadFiles $Ctx $up.upload_id $cmp.Extra }
            }
            else {
                Say "  이전 업로드($($old.upload_id))와 파일이 달라 새로 올립니다." 'Yellow'
                if ($old.state -eq 'OPEN') {
                    $c = Invoke-EslHttp $Ctx 'DELETE' "/uploads/$($old.upload_id)"
                    if ($c.Status -eq 200) { Say '  이전 미완료 업로드는 취소했습니다(서버 _backup 으로 이동, 삭제 없음).' 'DarkGray' }
                }
            }
        }
    }
    if (-not $up) {
        $body = @{ project_id = $Ctx.ProjectId; name = $Name; files = @(ConvertTo-EslFileSpecs $Plan.Files) }
        $r = Invoke-EslHttp $Ctx 'POST' '/uploads' $body
        if ($r.Status -ne 201 -and $r.Status -ne 200) { throw (Format-EslError $r '업로드 시작') }
        $up = $r.Json
        Say ("  새 업로드: {0} (파일 {1}개, {2}, 청크 {3})" -f $up.upload_id, @($up.files).Count, (Format-EslBytes ([double]$up.total_bytes)), (Format-EslBytes ([double]$up.chunk_size)))
    }
    $saveState = {
        $state[$Key] = [ordered]@{ upload_id = [string]$up.upload_id; server_url = $Ctx.ServerUrl; project_id = $Ctx.ProjectId
            name = $Name; fingerprint = $fp; added = @($added); saved_at = (Get-Date).ToString('o') }
        Save-EslUploadState $Ctx.StatePath $state
    }
    . $saveState

    $result = $null
    for ($round = 0; $round -lt 4; $round++) {
        if ($up.state -ne 'COMPLETED') { Send-EslPending $Ctx $up $Plan }
        $r = Invoke-EslHttp $Ctx 'POST' "/uploads/$($up.upload_id)/complete"
        $info = Get-EslErrorInfo $r
        if ($r.Status -eq 409 -and $info.Code -eq 'UPLOAD_INCOMPLETE') { $up = Get-EslUpload $Ctx $up.upload_id; continue }
        if ($r.Status -ne 200) { throw (Format-EslError $r '서버 검사(complete)') }
        $result = $r.Json
        if ($result.state -eq 'COMPLETED') { break }
        $miss = @($result.missing_includes)
        if ($miss.Count -eq 0) { break }
        $up = Get-EslUpload $Ctx $up.upload_id
        $f = Find-EslMissingLocal $miss $Plan $up
        foreach ($l in $f.Lost) { Say "  서버가 찾는 include 를 이 PC 에서 찾지 못했습니다: $l" 'Yellow' }
        if (@($f.Add).Count -eq 0) { break }
        Say ("  서버가 알려 준 누락 include {0}개를 추가로 올립니다." -f @($f.Add).Count) 'Cyan'
        $Plan = Add-EslPlanFiles $Plan $f.Add
        $up = Add-EslUploadFiles $Ctx $up.upload_id $f.Add
        $added = @($added) + @($f.Add | ForEach-Object { $_.Rel })
        . $saveState
    }
    return [pscustomobject]@{ UploadId = [string]$up.upload_id; ProjectId = [string]$Ctx.ProjectId; Result = $result
        Ok = ($null -ne $result -and $result.state -eq 'COMPLETED'); Url = (Get-EslCaseUrl $Ctx.ServerUrl $Ctx.ProjectId ([string]$up.upload_id)) }
}

# 경고·문제를 보여 주고 계속 여부를 묻는다(문제가 있으면 기본 '아니오')
function Confirm-EslPlan($Plan) {
    foreach ($w in @($Plan.Warnings)) { Say "  [경고] $w" 'Yellow' }
    foreach ($p in @($Plan.Problems)) { Say "  [문제] $p" 'Red' }
    Say ("  올릴 파일 {0}개, {1}" -f @($Plan.Files).Count, (Format-EslBytes ([double]$Plan.TotalBytes)))
    if (@($Plan.Missing).Count -eq 0 -and @($Plan.Problems).Count -eq 0) { return $true }
    $a = Read-EslInput '  그래도 올릴까요? (y/N)'
    return ($a -and $a.Trim() -match '^(y|yes|예|ㅇ)$')
}

# 서버 연결(+ 401 이면 코드 다시 묻기) -> 올리기 -> 브라우저
function Invoke-EslPcUpload($Ctx, $Plan, [string]$Name, [string]$Key, [switch]$NoBrowser) {
    for ($attempt = 0; ; $attempt++) {
        try {
            [void](Connect-EslClient $Ctx -Force:($attempt -gt 0))
            $res = Invoke-EslUpload $Ctx $Plan $Name $Key
            break
        }
        catch {
            if ((Test-EslAuthError $_) -and $attempt -lt 2) {
                Write-Host ''
                Say "  $($_.Exception.Message)" 'Yellow'
                continue
            }
            throw
        }
    }
    if ($res.Ok) {
        Say ("  서버 검사 통과: 파트 {0}개" -f @($res.Result.parts).Count) 'Green'
        Say "  새 Case 화면: $($res.Url)" 'Green'
        if (-not $NoBrowser) { Open-EslBrowser $res.Url }
    }
    else {
        Say '  서버 검사에서 문제가 남았습니다(업로드는 서버에 남아 있음 - 고친 뒤 다시 실행하면 이어 갑니다):' 'Red'
        if ($res.Result) {
            foreach ($m in @($res.Result.missing_includes)) { Say "    누락 include: $m" 'Red' }
            foreach ($p in @($res.Result.problems)) { Say "    $p" 'Red' }
        }
        Say "  새 Case 화면(문제 확인): $($res.Url)" 'Yellow'
    }
    return $res
}
