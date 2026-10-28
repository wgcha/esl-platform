"""PC 도구 시험 공용(tests/windows): pwsh 찾기, 가짜 서버 불러오기, 라이브러리를 dot-source 하는 PowerShell 하니스.

Windows 전용 함수(DPAPI·입력·브라우저·키 입력)는 MOCKS 로 바꿔 끼우고, 나머지는 Linux pwsh 에서 실제로 실행한다.
"""
import importlib.util
import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WIN = os.path.join(ROOT, "scripts", "windows")
LIB = os.path.join(WIN, "esl_upload_lib.ps1")
SLIM = os.path.join(WIN, "esl_slim_lib.ps1")
RUN = os.path.join(WIN, "esl_run.ps1")
RAD_FIX = os.path.join(ROOT, "tests", "rad", "fixtures")

# pwsh 찾기: 환경변수 ESL_PWSH → PATH 의 pwsh. 없으면 None(해당 시험 skip)
PWSH = os.environ.get("ESL_PWSH") or shutil.which("pwsh")

_spec = importlib.util.spec_from_file_location("esl_fake_upload_server", os.path.join(HERE, "esl_fake_upload_server.py"))
fake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake)

MOCKS = r"""
$ErrorActionPreference = 'Stop'
$script:Inputs = New-Object System.Collections.Queue
foreach ($x in @($env:ESL_TEST_INPUTS -split '\|')) { if ($x -ne '') { $script:Inputs.Enqueue($x) } }
function Read-EslInput([string]$Prompt) {
    Write-Host "ASK $Prompt"
    if ($script:Inputs.Count -gt 0) { return $script:Inputs.Dequeue() }
    return ''
}
function Protect-EslSecret([string]$Plain) { return 'MOCK:' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Plain)) }
function Unprotect-EslSecret([string]$Cipher) {
    if (-not $Cipher.StartsWith('MOCK:')) { throw 'not mock' }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Cipher.Substring(5)))
}
function Open-EslBrowser([string]$Url) { Write-Host "BROWSER $Url" }
$EslRetryBaseMs = 5
"""

# 대화형 콘솔·키 입력 대역(ESL_TEST_KEYS = '|' 로 구분한 키 목록, 'ENTER' 또는 문자, '-' = 시간 초과)
INTERACTIVE = r"""
$script:Keys = New-Object System.Collections.Queue
foreach ($x in @($env:ESL_TEST_KEYS -split '\|')) { if ($x -ne '') { $script:Keys.Enqueue($x) } }
function Test-EslInteractiveConsole { return $true }
function Test-EslNonInteractive { return $false }
function Wait-EslKey([int]$Seconds, [string]$Label) {
    Write-Host "WAITKEY $Seconds $Label"
    if ($script:Keys.Count -gt 0) {
        $k = $script:Keys.Dequeue()
        if ($k -eq '-') { return '' }
        return $k
    }
    return ''
}
"""


def run_ps(tmp_path, body, inputs=(), keys=None, timeout=240, env_extra=None, libs=(LIB, SLIM), interactive=False):
    script = tmp_path / "harness.ps1"
    pre = "".join(f". '{p}'\n" for p in libs)
    script.write_text(pre + MOCKS + (INTERACTIVE if interactive else "") + body, encoding="utf-8")
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "appdata"), ESL_TEST_INPUTS="|".join(inputs),
               ESL_TEST_KEYS="|".join(keys or []))
    env.pop("HTTP_PROXY", None)
    env.pop("http_proxy", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)], capture_output=True, text=True,
                          timeout=timeout, env=env)


def kv(r):
    return dict(ln.split("=", 1) for ln in r.stdout.splitlines() if "=" in ln and not ln.startswith(" "))


def make_case(tmp_path, big=300_000, with_results=True):
    """결과 폴더(csv, 선택) + rad + include 트리(작은 rad)."""
    res = None
    if with_results:
        res = tmp_path / "work" / "drop" / "csv"
        res.mkdir(parents=True)
        (res / "done.json").write_text(json.dumps({"ok": True, "part_title": "chassis_rear"}))
        (res / "elem_hist.csv").write_bytes(os.urandom(big))
        (res / "frames.csv").write_text("frame,t\n0,0.0\n")
        (res / "empty.txt").write_bytes(b"")
    rad = tmp_path / "model" / "drop_0000.rad"
    rad.parent.mkdir(parents=True)
    rad.write_text("#RADIOSS STARTER\n/INCLUDE \"inc/b.inc\"\n/END\n", encoding="utf-8")
    (rad.parent / "inc").mkdir()
    (rad.parent / "inc" / "b.inc").write_text("/NODE\n")
    return res, rad
