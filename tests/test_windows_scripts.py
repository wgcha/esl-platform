"""Windows 원클릭 업데이트 스크립트 검사.

정적 검사(pwsh 없어도 실행): update.bat -> scripts/windows/update.ps1 위임, 파괴적 git 명령·무조건 재귀 삭제·
폴더 rename 없음, 실행기(esl_run.ps1)의 h3d 폴더·보호 폴더 출력 거부, 예시 설정 키, 인코딩·줄끝 규칙.
pwsh 가 있으면(Linux 도 가능) 파싱 오류 0 과 배포 함수(esl_deploy_lib.ps1)·Publish-Deployment·런처를 임시 폴더에서 실제 실행.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(ROOT, "update.bat")
WIN = os.path.join(ROOT, "scripts", "windows")
UPDATE_PS1 = os.path.join(WIN, "update.ps1")
RUN_PS1 = os.path.join(WIN, "esl_run.ps1")
LIB_PS1 = os.path.join(WIN, "esl_deploy_lib.ps1")
LAUNCH_PS1 = os.path.join(WIN, "esl_launch.ps1")
EXAMPLE = os.path.join(ROOT, "config", "esl_deploy.example.json")
PS1_FILES = [UPDATE_PS1, RUN_PS1, LIB_PS1, LAUNCH_PS1]


def _read(p: str) -> str:
    with open(p, "rb") as f:
        raw = f.read()
    return raw.decode("utf-8-sig")


def _code_lines(p: str) -> list[str]:
    """주석(# ...) 줄을 뺀 코드 줄."""
    return [ln for ln in _read(p).splitlines() if not ln.lstrip().startswith("#")]


def _function_body(text: str, name: str) -> str:
    m = re.search(r"^function\s+" + re.escape(name) + r"\b[^\n]*\{", text, re.M)
    assert m, f"function {name} 없음"
    depth, i = 0, m.end() - 1
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise AssertionError(f"function {name} 괄호 불일치")


# ---- update.bat -------------------------------------------------------------------------------

def test_update_bat_delegates_to_ps1():
    text = _read(BAT)
    assert re.search(r'powershell\.exe\s+-NoProfile\s+-ExecutionPolicy\s+Bypass\s+-File\s+"%~dp0scripts\\windows\\update\.ps1"', text)
    assert "if errorlevel 1" in text
    assert text.lower().count("pause") >= 2          # 실패·성공 모두 멈춤
    assert "exit /b 1" in text and "exit /b 0" in text


def test_update_bat_ascii_crlf():
    raw = open(BAT, "rb").read()
    raw.decode("ascii")
    assert raw.endswith(b"\r\n")
    assert raw.count(b"\n") == raw.count(b"\r\n"), "update.bat 은 CRLF 줄끝"


def test_gitattributes_keeps_crlf():
    text = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read()
    assert re.search(r"^\*\.bat\s+text\s+eol=crlf", text, re.M)


# ---- 인코딩 -------------------------------------------------------------------------------------

def test_ps1_encoding_bom_if_non_ascii():
    for p in PS1_FILES:
        raw = open(p, "rb").read()
        body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
        try:
            body.decode("ascii")
        except UnicodeDecodeError:
            assert raw.startswith(b"\xef\xbb\xbf"), f"{p}: 한글 등 비ASCII 가 있으면 UTF-8 BOM 필수 (Windows PowerShell 5.1)"
        body.decode("utf-8")


# ---- 파괴적 명령 금지 -----------------------------------------------------------------------------

def test_no_destructive_git():
    for p in PS1_FILES:
        for ln in _code_lines(p):
            low = ln.lower()
            assert "reset" not in low or "git" not in low, f"{p}: {ln}"
            assert not re.search(r"\bpush\b", low), f"{p}: {ln}"
            assert "--force" not in low, f"{p}: {ln}"
            assert not re.search(r"\bclean\b", low) or "git" not in low, f"{p}: {ln}"


def test_git_subcommands_whitelist():
    text = _read(UPDATE_PS1)
    calls = re.findall(r"Invoke-Git(?:Checked)?\s+@\('([a-z-]+)'", text)
    assert calls, "git 호출 없음"
    assert set(calls) <= {"rev-parse", "status", "fetch", "show-ref", "checkout", "merge"}, calls
    merges = re.findall(r"@\('merge'[^)]*\)", text)
    assert merges and all("'--ff-only'" in m for m in merges)
    # git.exe 직접 호출은 Invoke-Git 안에서만
    direct = [ln for ln in _code_lines(UPDATE_PS1) if re.search(r"&\s*git", ln)]
    assert len(direct) == 1 and "@GitArgs" in direct[0]


def test_no_recursive_remove_item():
    for p in PS1_FILES:
        for ln in _code_lines(p):
            assert not re.search(r"Remove-Item\b.*-Recurse|\brm\s+-r|\brmdir\b|\brd\s+/s", ln, re.I), f"{p}: {ln}"
def test_deletes_only_inside_deploy_dir():
    lib = _read(LIB_PS1)
    lib_code = "\n".join(_code_lines(LIB_PS1))
    upd_code = "\n".join(_code_lines(UPDATE_PS1))
    # 폴더 삭제는 Remove-DeployTree 안에서만, 그 첫 줄은 deploy_dir 안 확인
    body = _function_body(lib, "Remove-DeployTree")
    assert body.split("\n")[1].strip().startswith("$full = Assert-InsideDeployDir")
    assert "Test-IsLink" in body and "Get-ForeignFiles $full" in body
    assert lib_code.count("[IO.Directory]::Delete(") == 1 and "[IO.Directory]::Delete(" in body
    assert "[IO.Directory]::Delete(" not in upd_code
    assert body.count("Remove-DeployTree") == 0, "재귀 삭제 금지(하위 폴더가 있으면 사용자 것으로 보고 거부)"
    guard = _function_body(lib, "Assert-InsideDeployDir")
    assert "Test-PathUnder" in guard and "-ieq $root" in guard
    one = _function_body(lib, "Remove-DeployFile")
    assert one.split("\n")[1].strip().startswith("$full = Assert-InsideDeployDir")
    assert "Test-IsLink" in one and "-notmatch $DeployFilePattern" in one
    # 파일 삭제: Remove-DeployTree/Remove-DeployFile, 포인터 임시 파일, work_root 쓰기 시험 임시 파일
    lib_deletes = sorted(ln.strip() for ln in lib_code.splitlines() if "[IO.File]::Delete(" in ln)
    assert lib_deletes == sorted(["[IO.File]::Delete($f)", "[IO.File]::Delete($full)",
                                  "try { if ([IO.File]::Exists($tmp)) { [IO.File]::Delete($tmp) } } catch { }"])
    upd_deletes = [ln.strip() for ln in upd_code.splitlines() if "[IO.File]::Delete(" in ln]
    assert upd_deletes == ["[IO.File]::Delete($probe)"]
    for p in PS1_FILES:
        assert "Remove-Item" not in "\n".join(_code_lines(p)), p


def test_no_folder_rename_pointer_swap_instead():
    """실기 오류(current 폴더 Move 가 탐색기·cmd 잠금으로 실패) 재발 방지: 폴더 rename 없음, 포인터 파일 교체."""
    for p in PS1_FILES:
        code = "\n".join(_code_lines(p))
        assert "[IO.Directory]::Move(" not in code and "Rename-Item" not in code, p
        assert "Move-Item" not in code, p
    lib = _read(LIB_PS1)
    setp = _function_body(lib, "Set-CurrentVersion")
    assert "[IO.File]::Replace($tmp, $dst, [NullString]::Value)" in setp   # $null 은 "" 로 바뀌어 예외
    assert "[IO.File]::Move($tmp, $dst)" in setp and "$Retries" in setp and "Start-Sleep" in setp
    assert ".tmp-" in setp and "throw" in setp
    upd = _read(UPDATE_PS1)
    assert ". (Join-Path $PSScriptRoot 'esl_deploy_lib.ps1')" in upd
    pub = _function_body(upd, "Publish-Deployment")
    # 순서: 버전 폴더 작성 -> 포인터 교체 -> 런처 -> 예전 구조 정리 -> 오래된 버전 정리
    order = [pub.index("Find-VersionSlot"), pub.index("Set-CurrentVersion"), pub.index("Update-LauncherFile"),
             pub.index("Get-LegacyArtifacts"), pub.index("Select-VersionsToPrune")]
    assert order == sorted(order)
    assert "$KeepVersions = 5" in upd and "Select-VersionsToPrune $all $active $KeepVersions" in pub
    assert "if ($launchersOk)" in pub          # 예전 런처가 남아 있으면 예전 산출물을 지우지 않음
    for fn in ("Read-CurrentVersion", "Find-VersionSlot", "Get-LegacyDeployDirs", "Update-LauncherFile"):
        assert re.search(r"^function " + fn + r"\b", lib, re.M), fn


def test_lock_log_retry():
    text = _read(UPDATE_PS1)
    assert "[IO.FileShare]::None" in text and "DeleteOnClose" in text
    assert re.search(r"Join-Path \$EslHome 'logs'", text) and "update_{0}.log" in text
    assert "$FetchRetries = 4" in text and "$delay *= 2" in text
    assert "--untracked-files=no" in text and "작업 트리 변경 있음" in text


def test_ps5_compatible_syntax():
    """PowerShell 5.1 에 없는 연산자(??, ?., 삼항, &&, ||) 금지 (문자열 밖 대략 검사)."""
    for p in PS1_FILES:
        for ln in _code_lines(p):
            code = re.sub(r"'[^']*'|\"[^\"]*\"", "''", ln)
            assert "??" not in code and "?." not in code, f"{p}: {ln}"
            assert "&&" not in code and "||" not in code, f"{p}: {ln}"
            assert not re.search(r"\s\?\s[^:]+\s:\s", code), f"{p}: {ln}"


# ---- 런처 ---------------------------------------------------------------------------------------

def test_launcher_template():
    lib = _read(LIB_PS1)
    body = _function_body(lib, "Get-LauncherBat")
    assert '-File `"%~dp0esl_launch.ps1`" -Mode $Mode %*' in body
    assert "DisableDelayedExpansion" in body and "'pause'" in body
    assert '-join "`r`n"' in body
    assert "esl_run.ps1" not in body.split("powershell.exe")[1]   # 버전 폴더를 직접 가리키지 않음
    for s in re.findall(r"'([^']*)'", body):
        s.encode("ascii")
    pub = _function_body(_read(UPDATE_PS1), "Publish-Deployment")
    assert "[Text.Encoding]::ASCII.GetBytes((Get-LauncherBat 'probe'))" in pub
    assert "[Text.Encoding]::ASCII.GetBytes((Get-LauncherBat 'extract'))" in pub
    launch = _read(LAUNCH_PS1)
    assert "Split-Path -Parent $PSScriptRoot" in launch and "'current_version.txt'" in launch
    assert "'versions'" in launch and "& $runner -Mode $Mode @Items" in launch and "exit $LASTEXITCODE" in launch
    # 런처의 버전 이름 검사 = 라이브러리 규칙
    vpat = re.search(r"^\$VersionNamePattern = '([^']+)'", lib, re.M).group(1)
    assert f"-cnotmatch '{vpat}'" in launch


def test_runner_rejects_h3d_folder_and_protected_roots():
    text = _read(RUN_PS1)
    guard = _function_body(text, "Assert-OutputAllowed")
    assert "Test-PathUnder $cand $H3dDir" in guard and "Test-PathUnder $cand $root" in guard
    assert "Resolve-RealPath" in guard and "throw" in guard
    # 출력 폴더를 만들기 전과 후 모두 확인
    loop = text[text.index("foreach ($h3d in $h3ds)"):]
    a = loop.index("Assert-OutputAllowed $outDir $h3dDir $protected")
    n = loop.index("New-Item -ItemType Directory -Force -Path $outDir")
    assert a < n and loop.count("Assert-OutputAllowed $outDir") == 2
    # 출력 = <work_root>\<stem>\probe|csv
    assert "GetFileNameWithoutExtension($h3d)" in text
    assert "Join-Path (Join-Path $workRoot $stem) $sub" in text
    assert "if ($Mode -eq 'probe') { 'probe' } else { 'csv' }" in text
    # %, !, & 거부, 기본 파트, 콘솔 로그, 결과 요약, 탐색기
    assert "$BadChars = '[%!&]'" in text and "-match $BadChars" in text
    assert "$part = $defaultPart" in text
    assert "_console.log" in text and "-RedirectStandardOutput $log" in text
    assert "'probe.json'" in text and "'done.json'" in text
    for key in ("$j.ok", "$j.failed_step", "$j.error"):
        assert key in text
    assert "'explorer.exe'" in text


def test_test_path_under_semantics():
    """Test-PathUnder 와 같은 규칙(접두 + 구분자)을 파이썬으로 확인: 형제 폴더 오탐 없음."""
    def under(c, p):
        c = c.rstrip("\\").lower() + "\\"
        p = p.rstrip("\\").lower() + "\\"
        return c.startswith(p)
    assert under(r"F:\Hyper_work\X\CUMULATIVE\drop", r"F:\Hyper_work\X\CUMULATIVE")
    assert under(r"f:\hyper_work\x\cumulative", r"F:\Hyper_work\X\CUMULATIVE\\")
    assert not under(r"F:\Hyper_work\X\CUMULATIVE2", r"F:\Hyper_work\X\CUMULATIVE")
    text = _read(RUN_PS1)
    assert "TrimEnd('\\') + '\\'" in _function_body(text, "Test-PathUnder")
    assert "OrdinalIgnoreCase" in _function_body(text, "Test-PathUnder")


# ---- 예시 설정 ----------------------------------------------------------------------------------

def test_example_config_keys():
    cfg = json.load(open(EXAMPLE, encoding="utf-8"))
    assert set(cfg) == {"hw_exe", "work_root", "deploy_dir", "branch", "default_part", "protected_roots"}
    assert cfg["hw_exe"].lower().endswith("hw.exe") and "2026.1" in cfg["hw_exe"]
    assert cfg["work_root"].startswith("%USERPROFILE%")
    assert cfg["deploy_dir"].startswith("%LOCALAPPDATA%")
    assert cfg["branch"] == "" and cfg["default_part"] == "chassis_rear"
    assert cfg["protected_roots"] == []


def test_config_defaults_come_from_example_only():
    """하드코딩 경로는 예시 설정에만: 스크립트에 드라이브 문자·Program Files 리터럴 없음."""
    for p in PS1_FILES:
        for ln in _code_lines(p):
            assert not re.search(r"""['"][A-Za-z]:[\\/]""", ln), f"{p}: {ln}"
            assert "Program Files" not in ln, f"{p}: {ln}"
    assert "config\\esl_deploy.example.json" in _read(UPDATE_PS1)


def test_readme_sections():
    for p in (os.path.join(ROOT, "README.md"), os.path.join(ROOT, "resources", "tcl", "README.md")):
        text = open(p, encoding="utf-8").read()
        assert "Windows 설치·업데이트" in text and "update.bat" in text
        assert "ESL_extract.bat" in text and "수동 실행" in text


# ---- 배포 폴더 보호(사용자가 h3d 를 deploy_dir\current 에 복사해 실행한 사례) ---------------------

def test_runner_rejects_h3d_inside_deploy_dir():
    text = _read(RUN_PS1)
    guard = _function_body(text, "Assert-InputOutsideDeploy")
    assert "Resolve-RealPath $H3d" in guard and "Test-PathUnder $cand $root" in guard
    assert "@($DeployDir, $PSScriptRoot)" in guard and "throw" in guard
    assert "원본 위치의 h3d를 그대로 끌어다 놓으세요(읽기 전용으로 사용)" in guard
    assert "$deployDir = Expand-ConfigPath ([string]$cfg.deploy_dir)" in text
    # h3d 마다, 출력 폴더 검사·생성·hw 실행보다 먼저
    loop = text[text.index("foreach ($h3d in $h3ds)"):]
    i = loop.index("Assert-InputOutsideDeploy $h3d $deployDir")
    assert i < loop.index("Assert-OutputAllowed $outDir") < loop.index("Start-Process -FilePath $hwExe")


def test_update_keeps_foreign_files_in_deploy_dir():
    lib = _read(LIB_PS1)
    pat = re.search(r"^\$DeployFilePattern = '([^']+)'", lib, re.M).group(1)
    rx = re.compile(pat, re.I)              # PowerShell -match 는 대소문자 무시
    for ok in ("esl_h3d_probe.tcl", "esl_run.ps1", "ESL_extract.bat", "README.md", "VERSION.txt",
               "esl_probe_fallback.json", "esl_extract_done_fallback.json"):
        assert rx.match(ok), ok
    for bad in ("model.h3d", "run_0001.h3d", "notes.txt", "probe.json", "data.csv", "x.tcl.h3d", "README.md.bak"):
        assert not rx.match(bad), bad
    body = _function_body(lib, "Remove-DeployTree")
    a = body.index("Assert-InsideDeployDir")
    b = body.index("Test-IsLink $full")
    c = body.index("Get-ForeignFiles $full")
    d = body.index("[IO.File]::Delete(")
    assert a < b < c < d
    fn = _function_body(lib, "Get-ForeignFiles")
    assert "PSIsContainer" in fn and "-notmatch $DeployFilePattern" in fn   # 하위 폴더도 사용자 것으로 본다
    legacy = _function_body(lib, "Get-LegacyArtifacts")
    assert "PSIsContainer" in legacy and "ReparsePoint" in legacy and "$LauncherNames -contains" in legacy


# ---- pwsh 로 실제 실행 (Linux 임시 폴더) -----------------------------------------------------------

PWSH = os.environ.get("ESL_PWSH") or shutil.which("pwsh") or (
    "/tmp/claude-0/pwsh/pwsh" if os.path.isfile("/tmp/claude-0/pwsh/pwsh") else None)
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh 없음")


def _pwsh_file(script, *args, timeout=180):
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(script), *map(str, args)],
                          capture_output=True, text=True, timeout=timeout)


def _lib_script(tmp_path, body: str, name="t.ps1"):
    p = tmp_path / name
    p.write_text(f". '{LIB_PS1}'\n$ErrorActionPreference = 'Stop'\n" + body, encoding="utf-8")
    return p


@needs_pwsh
def test_ps1_parse_with_pwsh():
    for p in PS1_FILES:
        r = subprocess.run([PWSH, "-NoProfile", "-Command",
                            "$t=$null;$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
                            f"'{p}',[ref]$t,[ref]$e); $e.Count"], capture_output=True, text=True, timeout=120)
        assert r.stdout.strip() == "0", (p, r.stdout, r.stderr)


@needs_pwsh
def test_lib_pure_functions_with_pwsh(tmp_path):
    d = tmp_path / "current"
    d.mkdir()
    for n in ("esl_h3d_probe.tcl", "esl_run.ps1", "ESL_probe.bat", "ESL_extract.bat", "esl_launch.ps1",
              "README.md", "VERSION.txt", "esl_probe_fallback.json", "big.h3d"):
        (d / n).write_text("x")
    (d / "sub").mkdir()
    (d / "sub" / "a.tcl").write_text("x")
    dep = tmp_path / "dep"
    for n in ("abc1234", "current.new", "current.old.20260101_000000", "versions", "mydata", "abc"):
        (dep / n).mkdir(parents=True)
    script = _lib_script(tmp_path, f"""
function leaf($xs) {{ (@($xs) | ForEach-Object {{ Split-Path -Leaf $_ }} | Sort-Object) -join ',' }}
"foreign=" + (leaf (Get-ForeignFiles '{d}'))
"legacy=" + (leaf (Get-LegacyArtifacts '{d}'))
"islegacy=" + (Test-LegacyLayout '{d}')
"legacydirs=" + (leaf (Get-LegacyDeployDirs '{dep}'))
"names=" + ((@('1a2b3c4', '1a2b3c4-2', '1A2B3C4', '..', 'abc', '1a2b3c4-x', '1a2b3c4\\..') | ForEach-Object {{ Test-VersionName $_ }}) -join ',')
$t0 = Get-Date '2026-01-01'
$vs = @(1..8 | ForEach-Object {{ [pscustomobject]@{{ Name = ('a' * 6) + $_; LastWriteTime = $t0.AddDays($_) }} }})
$vs += [pscustomobject]@{{ Name = 'notaversion'; LastWriteTime = $t0 }}
"prune_active_new=" + ((Select-VersionsToPrune $vs 'aaaaaa8' 5) -join ',')
"prune_active_old=" + ((Select-VersionsToPrune $vs 'aaaaaa1' 5) -join ',')
"prune_few=" + (@(Select-VersionsToPrune $vs[0..2] 'aaaaaa1' 5).Count)
"under=" + (Test-PathUnder '{tmp_path}/a/b' '{tmp_path}/a') + ',' + (Test-PathUnder '{tmp_path}/ab' '{tmp_path}/a')
""")
    r = _pwsh_file(script)
    out = dict(ln.split("=", 1) for ln in r.stdout.strip().splitlines() if "=" in ln)
    assert out["foreign"] == "big.h3d,sub", (r.stdout, r.stderr)
    assert out["legacy"] == "esl_h3d_probe.tcl,esl_probe_fallback.json,esl_run.ps1,README.md,VERSION.txt"
    assert out["islegacy"] == "True"
    assert out["legacydirs"] == "abc1234,current.new,current.old.20260101_000000"
    assert out["names"] == "True,True,False,False,False,False,False"
    assert out["prune_active_new"] == "aaaaaa3,aaaaaa2,aaaaaa1"
    assert out["prune_active_old"] == "aaaaaa3,aaaaaa2"          # 활성 버전은 오래돼도 유지
    assert out["prune_few"] == "0"
    assert out["under"] == "True,False"


@needs_pwsh
def test_pointer_swap_and_launcher_file_with_pwsh(tmp_path):
    dep = tmp_path / "dep"
    dep.mkdir()
    bad = tmp_path / "bad"
    (bad / "current_version.txt").mkdir(parents=True)      # 교체 불가(폴더) -> 재시도 후 실패
    cur = tmp_path / "cur"
    cur.mkdir()
    (cur / "locked.bat").mkdir()                            # 쓰기 불가 대역
    script = _lib_script(tmp_path, f"""
"first=" + (Set-CurrentVersion '{dep}' 'abc1234' 3 10)
"read1=" + (Read-CurrentVersion '{dep}')
"second=" + (Set-CurrentVersion '{dep}' 'def5678-2' 3 10)
"read2=" + (Read-CurrentVersion '{dep}')
"tmpleft=" + @(Get-ChildItem '{dep}' -Filter '*.tmp-*').Count
try {{ Set-CurrentVersion '{dep}' '..\\evil' 3 10; 'badname=accepted' }} catch {{ 'badname=rejected' }}
try {{ Set-CurrentVersion '{bad}' 'abc1234' 3 10; 'fail=no' }} catch {{ 'fail=' + ($_.Exception.Message -match '3 회 시도') }}
"badtmp=" + @(Get-ChildItem '{bad}' -Filter '*.tmp-*').Count
[IO.File]::WriteAllText('{dep}/current_version.txt', 'garbage..')
"readbad=[" + (Read-CurrentVersion '{dep}') + "]"
$b = [Text.Encoding]::ASCII.GetBytes((Get-LauncherBat 'probe'))
"w1=" + (Update-LauncherFile '{cur}/ESL_probe.bat' $b)
"w2=" + (Update-LauncherFile '{cur}/ESL_probe.bat' $b)
"w3=" + ((Update-LauncherFile '{cur}/locked.bat' $b) -like 'locked:*')
""")
    r = _pwsh_file(script)
    out = dict(ln.split("=", 1) for ln in r.stdout.strip().splitlines() if "=" in ln)
    assert out.get("first") == "1", (r.stdout, r.stderr)
    assert out["read1"] == "abc1234" and out["second"] == "1" and out["read2"] == "def5678-2"
    assert out["tmpleft"] == "0" and out["badname"] == "rejected"
    assert out["fail"] == "True" and out["badtmp"] == "0"
    assert out["readbad"] == "[]"
    assert (out["w1"], out["w2"], out["w3"]) == ("written", "same", "True")
    bat = (cur / "ESL_probe.bat").read_bytes()
    bat.decode("ascii")
    assert bat.count(b"\n") == bat.count(b"\r\n") and b"-Mode probe %*" in bat
    assert b"Output: <work_root>\\<h3d name>\\probe\r\n" in bat


def _publish_harness(tmp_path):
    """update.ps1 의 Publish-Deployment 를 그대로 떼어 내 Linux 임시 폴더에서 실행하는 스크립트."""
    upd = _read(UPDATE_PS1)
    pub = _function_body(upd, "Publish-Deployment")
    sd = tmp_path / "scripts"
    sd.mkdir()
    (sd / "esl_launch.ps1").write_bytes(open(LAUNCH_PS1, "rb").read())
    (sd / "esl_run.ps1").write_text(       # 실행기 대역: 자기 폴더·인자를 출력하고 7 로 종료
        "param([string]$Mode,[Parameter(ValueFromRemainingArguments=$true)][string[]]$Items=@())\n"
        "Write-Output \"RUN $PSScriptRoot $Mode $($Items -join '|')\"\nexit 7\n")
    repo = tmp_path / "repo"
    (repo / "resources" / "tcl").mkdir(parents=True)
    for n in ("esl_h3d_probe.tcl", "esl_h3d_extract.tcl", "README.md"):
        (repo / "resources" / "tcl" / n).write_text(n)
    h = sd / "h.ps1"
    h.write_text(f". '{LIB_PS1}'\n$ErrorActionPreference = 'Stop'\n"
                 "function Say($m, $c) { Write-Host \"SAY $m\" }\nfunction Stage($m) { }\nfunction Write-Log($m) { }\n"
                 "function Add-Check($a, $b, $c) { Write-Host \"CHECK $a $b\" }\n"
                 "$RepoRoot = $args[0]; $script:DeployDir = $args[1]; $KeepVersions = 5\n"
                 "function Publish-Deployment($Cfg, [string]$Version) " + pub + "\n"
                 "$r = Publish-Deployment $null $args[2]\nWrite-Host \"RESULT $($r.Version)\"\n", encoding="utf-8")
    return h, repo


@needs_pwsh
def test_publish_migrates_legacy_layout_with_pwsh(tmp_path):
    h, repo = _publish_harness(tmp_path)
    dep = tmp_path / "dep"
    cur = dep / "current"
    (cur / "sub").mkdir(parents=True)
    for n in ("esl_h3d_probe.tcl", "esl_h3d_extract.tcl", "esl_run.ps1", "ESL_probe.bat", "ESL_extract.bat",
              "README.md", "VERSION.txt", "esl_probe_fallback.json", "big.h3d"):
        (cur / n).write_text("old")
    (cur / "sub" / "keep.h3d").write_text("u")
    for n in ("abc1234", "def5678", "current.old.20260101_000000"):
        (dep / n).mkdir()
    (dep / "abc1234" / "x.tcl").write_text("x")
    (dep / "def5678" / "user.h3d").write_text("u")          # 사용자 파일이 있는 예전 폴더는 남김

    r = _pwsh_file(h, repo, dep, "1111111")
    assert r.returncode == 0 and "RESULT 1111111" in r.stdout + r.stderr, (r.stdout, r.stderr)
    assert (dep / "current_version.txt").read_text().strip() == "1111111"
    v = dep / "versions" / "1111111"
    assert sorted(os.listdir(v)) == ["README.md", "VERSION.txt", "esl_h3d_extract.tcl", "esl_h3d_probe.tcl", "esl_run.ps1"]
    assert sorted(os.listdir(cur)) == ["ESL_extract.bat", "ESL_probe.bat", "big.h3d", "esl_launch.ps1", "sub"]
    assert (cur / "big.h3d").read_text() == "old" and (cur / "sub" / "keep.h3d").read_text() == "u"
    assert not (dep / "abc1234").exists() and not (dep / "current.old.20260101_000000").exists()
    assert (dep / "def5678" / "user.h3d").exists()

    # 같은 내용 재실행: 재사용, 포인터 그대로
    r = _pwsh_file(h, repo, dep, "1111111")
    assert "재사용" in r.stdout and "활성 버전 그대로" in r.stdout, r.stdout
    # 같은 해시에 내용이 다르면 기존 폴더를 고치지 않고 -2
    (repo / "resources" / "tcl" / "esl_h3d_probe.tcl").write_text("changed")
    r = _pwsh_file(h, repo, dep, "1111111")
    assert (dep / "current_version.txt").read_text().strip() == "1111111-2", r.stdout
    assert (v / "esl_h3d_probe.tcl").read_text() == "esl_h3d_probe.tcl"

    # 런처: 포인터가 가리키는 versions 폴더의 실행기로 인자 전달, 종료 코드 전달
    r = _pwsh_file(cur / "esl_launch.ps1", "-Mode", "extract", "/x y/a.h3d", "mypart")
    assert r.returncode == 7, (r.stdout, r.stderr)
    assert f"RUN {dep / 'versions' / '1111111-2'} extract /x y/a.h3d|mypart" in r.stdout
    (dep / "current_version.txt").write_text("..")
    r = _pwsh_file(cur / "esl_launch.ps1", "-Mode", "probe", "a.h3d")
    assert r.returncode == 1 and "update.bat" in r.stdout


@needs_pwsh
def test_publish_prunes_old_versions_with_pwsh(tmp_path):
    import time
    h, repo = _publish_harness(tmp_path)
    dep = tmp_path / "dep"
    vroot = dep / "versions"
    now = time.time()
    names = [f"aaaaaa{i}" for i in range(1, 8)]
    for i, n in enumerate(names):
        (vroot / n).mkdir(parents=True)
        (vroot / n / "esl_run.ps1").write_text("x")
        if n == "aaaaaa2":
            (vroot / n / "copied.h3d").write_text("u")     # 사용자 파일 -> 건너뜀(오류 아님)
        os.utime(vroot / n, (now - 1000 + i, now - 1000 + i))
    (vroot / "notes").mkdir()                              # 버전 이름이 아닌 폴더는 건드리지 않음
    r = _pwsh_file(h, repo, dep, "2222222")
    assert r.returncode == 0, (r.stdout, r.stderr)
    left = sorted(os.listdir(vroot))
    # 새 버전 + 최근 4개 유지, 나머지 정리(사용자 파일 있는 aaaaaa2 는 남김)
    assert left == ["2222222", "aaaaaa2", "aaaaaa4", "aaaaaa5", "aaaaaa6", "aaaaaa7", "notes"], (left, r.stdout)
    assert "정리 건너뜀" in r.stdout


@needs_pwsh
def test_publish_keeps_legacy_files_when_launcher_locked_with_pwsh(tmp_path):
    h, repo = _publish_harness(tmp_path)
    dep = tmp_path / "dep"
    cur = dep / "current"
    cur.mkdir(parents=True)
    for n in ("esl_h3d_probe.tcl", "esl_run.ps1", "ESL_probe.bat"):
        (cur / n).write_text("old")
    (cur / "ESL_extract.bat").mkdir()                      # 갱신 불가 대역 -> 경고만
    r = _pwsh_file(h, repo, dep, "3333333")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "CHECK 런처 ESL_extract.bat WARN" in r.stdout
    assert (cur / "esl_run.ps1").exists() and (cur / "esl_h3d_probe.tcl").exists()   # 예전 런처용으로 남김
    assert (dep / "current_version.txt").read_text().strip() == "3333333"
