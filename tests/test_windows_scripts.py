"""Windows 원클릭 업데이트 스크립트 정적 검사 (pwsh 없는 환경용).

update.bat -> scripts/windows/update.ps1 위임, 파괴적 git 명령·무조건 재귀 삭제 없음,
실행기(esl_run.ps1)의 h3d 폴더·보호 폴더 출력 거부, 예시 설정 키, 인코딩·줄끝 규칙.
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
EXAMPLE = os.path.join(ROOT, "config", "esl_deploy.example.json")
PS1_FILES = [UPDATE_PS1, RUN_PS1]


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
    text = _read(UPDATE_PS1)
    code = "\n".join(_code_lines(UPDATE_PS1))
    # 폴더 삭제는 Remove-DeployTree 안에서만, 그 첫 줄은 deploy_dir 안 확인
    body = _function_body(text, "Remove-DeployTree")
    assert body.split("\n")[1].strip().startswith("$full = Assert-InsideDeployDir")
    assert "Test-IsLink" in body
    assert code.count("[IO.Directory]::Delete(") == 1 and "[IO.Directory]::Delete(" in body
    guard = _function_body(text, "Assert-InsideDeployDir")
    assert "Test-PathUnder" in guard and "-ieq $script:DeployDir" in guard
    # 파일 삭제: Remove-DeployTree 안, 또는 work_root 쓰기 시험 임시 파일 1개
    file_deletes = [ln.strip() for ln in code.splitlines() if "[IO.File]::Delete(" in ln]
    assert sorted(file_deletes) == sorted(["[IO.File]::Delete($f)", "[IO.File]::Delete($probe)"])
    assert "Remove-Item" not in code
    assert "Remove-Item" not in "\n".join(_code_lines(RUN_PS1))


def test_lock_log_retry_and_retention():
    text = _read(UPDATE_PS1)
    assert "[IO.FileShare]::None" in text and "DeleteOnClose" in text
    assert re.search(r"Join-Path \$EslHome 'logs'", text) and "update_{0}.log" in text
    assert "$FetchRetries = 4" in text and "$delay *= 2" in text
    assert "$KeepVersions = 5" in text
    assert "--untracked-files=no" in text and "작업 트리 변경 있음" in text
    assert "'current.new'" in text and "[IO.Directory]::Move($oldDir, $current)" in text   # 실패 시 되돌림


# ---- 실행 래퍼 ----------------------------------------------------------------------------------

def test_wrapper_template():
    text = _read(UPDATE_PS1)
    body = _function_body(text, "New-Wrapper")
    assert '-File `"%~dp0esl_run.ps1`" -Mode $Mode %*' in body
    assert "DisableDelayedExpansion" in body and "'pause'" in body
    assert '-join "`r`n"' in body and "[Text.Encoding]::ASCII" in body
    assert "New-Wrapper $verDir 'ESL_probe.bat' 'probe'" in text
    assert "New-Wrapper $verDir 'ESL_extract.bat' 'extract'" in text
    # 템플릿 문자열 자체도 ASCII (bat 은 ASCII 로 저장)
    for s in re.findall(r"'([^']*)'", body):
        s.encode("ascii")


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
    text = _read(UPDATE_PS1)
    pat = re.search(r"^\$DeployFilePattern = '([^']+)'", text, re.M).group(1)
    rx = re.compile(pat, re.I)              # PowerShell -match 는 대소문자 무시
    for ok in ("esl_h3d_probe.tcl", "esl_run.ps1", "ESL_extract.bat", "README.md", "VERSION.txt",
               "esl_probe_fallback.json", "esl_extract_done_fallback.json"):
        assert rx.match(ok), ok
    for bad in ("model.h3d", "run_0001.h3d", "notes.txt", "probe.json", "data.csv", "x.tcl.h3d", "README.md.bak"):
        assert not rx.match(bad), bad
    # Remove-DeployTree: deploy_dir 확인 -> 링크 확인 -> 사용자 파일 확인 후에만 삭제
    body = _function_body(text, "Remove-DeployTree")
    a = body.index("Assert-InsideDeployDir")
    b = body.index("Test-IsLink $full")
    c = body.index("Assert-OnlyDeployFiles $full")
    d = body.index("[IO.File]::Delete(")
    assert a < b < c < d
    guard = _function_body(text, "Assert-OnlyDeployFiles")
    assert "Get-ForeignFiles" in guard and "throw" in guard and "foreach ($p in $foreign)" in guard
    fn = _function_body(text, "Get-ForeignFiles")
    assert "PSIsContainer" in fn and "-notmatch $DeployFilePattern" in fn   # 하위 폴더도 사용자 것으로 본다
    # 사전 점검: current/current.new/같은 버전/정리 대상 버전을 Move·삭제보다 먼저 확인
    pub = _function_body(text, "Publish-Deployment")
    pre = pub.index("$touched = @($current, $staging, $verDir) + @($excess")
    assert pre < pub.index("Remove-DeployTree $verDir") < pub.index("[IO.Directory]::Move($current, $oldDir)")
    assert pub.index("Assert-OnlyDeployFiles $current") < pub.index("[IO.Directory]::Move($current, $oldDir)")
    assert "throw \"배포 폴더에 배포 산출물이 아닌 파일" in pub


PWSH = os.environ.get("ESL_PWSH") or shutil.which("pwsh") or (
    "/tmp/claude-0/pwsh/pwsh" if os.path.isfile("/tmp/claude-0/pwsh/pwsh") else None)


@pytest.mark.skipif(PWSH is None, reason="pwsh 없음")
def test_ps1_parse_and_foreign_files_with_pwsh(tmp_path):
    for p in PS1_FILES:
        r = subprocess.run([PWSH, "-NoProfile", "-Command",
                            "$t=$null;$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
                            f"'{p}',[ref]$t,[ref]$e); $e.Count"], capture_output=True, text=True, timeout=120)
        assert r.stdout.strip() == "0", (p, r.stdout, r.stderr)
    text = _read(UPDATE_PS1)
    pat_line = re.search(r"^\$DeployFilePattern = '[^']+'", text, re.M).group(0)
    d = tmp_path / "current"
    d.mkdir()
    for n in ("esl_h3d_probe.tcl", "esl_run.ps1", "ESL_probe.bat", "README.md", "VERSION.txt", "big.h3d"):
        (d / n).write_text("x")
    (d / "sub").mkdir()
    script = tmp_path / "t.ps1"
    script.write_text(pat_line + "\n" + _function_body(text, "Get-ForeignFiles").join(
        ["function Get-ForeignFiles([string]$Dir) ", ""]) + f"\n(Get-ForeignFiles '{d}' | ForEach-Object {{ Split-Path -Leaf $_ }} | Sort-Object) -join ','\n")
    r = subprocess.run([PWSH, "-NoProfile", "-File", str(script)], capture_output=True, text=True, timeout=120)
    assert r.stdout.strip() == "big.h3d,sub", (r.stdout, r.stderr)
