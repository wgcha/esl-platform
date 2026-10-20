"""PC 업로드 클라이언트(scripts/windows/esl_upload_lib.ps1) 실제 실행 시험 — 계약 esl_p3_ux.md §9.2·§9.3.

pwsh(Linux 도 가능)로 라이브러리를 dot-source 하고, Windows 전용 함수(DPAPI·입력·브라우저)만 바꿔 끼운 뒤
같은 폴더의 가짜 업로드 서버(esl_fake_upload_server.py, http.server)를 상대로 실행한다:
include 수집(상대·절대·Windows 매핑 실패·rad 폴더 밖), 청크·청크 sha256·연결 끊김 재시도·409 received 이어 올리기,
중단 후 다시 실행하면 같은 서버 세션 이어 가기(uploads.json), complete 의 누락 include 추가, 토큰 교환·401 재연결,
브라우저 URL, 루프백 프록시 제외, server_url 저장.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LIB = os.path.join(ROOT, "scripts", "windows", "esl_upload_lib.ps1")
RUN = os.path.join(ROOT, "scripts", "windows", "esl_run.ps1")

PWSH = os.environ.get("ESL_PWSH") or shutil.which("pwsh") or (
    "/tmp/claude-0/pwsh/pwsh" if os.path.isfile("/tmp/claude-0/pwsh/pwsh") else None)
pytestmark = pytest.mark.skipif(PWSH is None, reason="pwsh 없음")

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


def run_ps(tmp_path, body, inputs=(), timeout=180):
    script = tmp_path / "harness.ps1"
    script.write_text(f". '{LIB}'\n" + MOCKS + body, encoding="utf-8")
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "appdata"), ESL_TEST_INPUTS="|".join(inputs))
    env.pop("HTTP_PROXY", None)
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)], capture_output=True, text=True,
                       timeout=timeout, env=env)
    return r


def kv(r):
    return dict(ln.split("=", 1) for ln in r.stdout.splitlines() if "=" in ln and not ln.startswith(" "))


@pytest.fixture()
def server():
    srv, state, url = fake.start()
    yield state, url
    srv.shutdown()
    srv.server_close()


def make_case(tmp_path, big=300_000):
    """결과 폴더(csv) + rad + include 트리."""
    res = tmp_path / "work" / "drop" / "csv"
    res.mkdir(parents=True)
    (res / "done.json").write_text(json.dumps({"ok": True, "part_title": "chassis_rear"}))
    (res / "elem_hist.csv").write_bytes(os.urandom(big))
    (res / "frames.csv").write_text("frame,t\n0,0.0\n")
    (res / "empty.txt").write_bytes(b"")
    (res / "extract_console.log").write_text("log")          # 허용 확장자 밖 -> 건너뜀
    (res / "sub").mkdir()
    (res / "sub" / "x.json").write_text("{}")
    rad = tmp_path / "model" / "drop_0000.rad"
    (rad.parent / "inc" / "deep").mkdir(parents=True)
    rad.write_text(
        "#RADIOSS STARTER\n"
        "/INCLUDE \"inc/a.inc\"\n"
        "#include inc/b.inc\n"
        "/INCLUDE\n"
        "# 주석\n"
        "C:\\models\\shared\\mat.inc\n"          # Windows 절대경로: 이 PC 에 없음 -> 파일 이름으로 rad 폴더에서 찾음
        "/INCLUDE \"D:/nowhere/missing_abs.inc\"\n"
        "/INCLUDE missing_rel.inc\n"
        "/END\n"
        "/INCLUDE after_end.inc\n", encoding="utf-8")
    (rad.parent / "inc" / "a.inc").write_text("#include deep/c.inc\n/INCLUDE inc/a.inc\n")   # 순환은 한 번만
    (rad.parent / "inc" / "deep" / "c.inc").write_bytes("$ 한글 주석\n".encode("cp949") + b"/NODE\n")
    (rad.parent / "inc" / "b.inc").write_text("/NODE\n")
    (rad.parent / "mat.inc").write_text("/MAT\n")
    (rad.parent / "late.inc").write_text("/PROP\n")         # rad 가 참조하지 않음(서버가 누락이라고 알려 줄 것)
    return res, rad


# ---- include 수집 ----------------------------------------------------------------------------------

def test_include_scan_and_plan(tmp_path):
    res, rad = make_case(tmp_path, big=10)
    outside = tmp_path / "model2" / "x_0000.rad"
    outside.parent.mkdir()
    outside.write_text("/INCLUDE ../model/inc/b.inc\n/INCLUDE \"bad name%.inc\"\n")
    (outside.parent / "bad name%.inc").write_text("x")
    r = run_ps(tmp_path, f"""
$incs = @(Get-EslRadIncludes '{rad}')
foreach ($i in $incs) {{ Write-Output ("INC|{{0}}|{{1}}|{{2}}|{{3}}" -f $i.Spec, $i.Found, $i.Absolute, $i.ByName) }}
$plan = Get-EslUploadPlan '{res}' '{rad}'
foreach ($f in $plan.Files) {{ Write-Output ("FILE|{{0}}|{{1}}" -f $f.Rel, $f.Size) }}
foreach ($w in $plan.Warnings) {{ Write-Output "WARN|$w" }}
foreach ($p in $plan.Problems) {{ Write-Output "PROB|$p" }}
Write-Output ("missing=" + @($plan.Missing).Count)
$p2 = Get-EslUploadPlan '' '{outside}'
foreach ($p in $p2.Problems) {{ Write-Output "PROB2|$p" }}
Write-Output ("files2=" + (@($p2.Files | ForEach-Object {{ $_.Rel }}) -join ','))
""")
    assert r.returncode == 0, (r.stdout, r.stderr)
    lines = r.stdout.splitlines()
    incs = [ln.split("|")[1:] for ln in lines if ln.startswith("INC|")]
    specs = [i[0] for i in incs]
    assert specs == ["inc/a.inc", "deep/c.inc", "inc/b.inc", "C:\\models\\shared\\mat.inc",
                     "D:/nowhere/missing_abs.inc", "missing_rel.inc"], incs
    assert "after_end.inc" not in r.stdout                    # /END 뒤는 읽지 않음
    found = {i[0]: (i[1], i[2], i[3]) for i in incs}
    assert found["C:\\models\\shared\\mat.inc"] == ("True", "True", "True")   # 파일 이름으로 찾음
    assert found["D:/nowhere/missing_abs.inc"] == ("False", "True", "False")
    assert found["missing_rel.inc"][0] == "False"
    files = {ln.split("|")[1]: int(ln.split("|")[2]) for ln in lines if ln.startswith("FILE|")}
    assert set(files) == {"results/csv/done.json", "results/csv/elem_hist.csv", "results/csv/frames.csv",
                          "results/csv/empty.txt", "results/csv/sub/x.json", "rad/drop_0000.rad",
                          "rad/inc/a.inc", "rad/inc/deep/c.inc", "rad/inc/b.inc", "rad/mat.inc"}, files
    warns = [ln for ln in lines if ln.startswith("WARN|")]
    assert any("missing_abs.inc" in w and "절대경로" in w for w in warns), warns       # Windows 매핑 실패 경고
    assert any("missing_rel.inc" in w for w in warns)
    assert any("1 개" in w and ".log" in w for w in warns)
    assert not [ln for ln in lines if ln.startswith("PROB|")]
    assert kv(r)["missing"] == "2"
    prob2 = [ln for ln in lines if ln.startswith("PROB2|")]
    assert any("rad 폴더 밖 상대경로" in p for p in prob2), prob2
    assert any("bad name%.inc" in p and "올릴 수 없는" in p for p in prob2), prob2
    assert kv(r)["files2"] == "rad/x_0000.rad"


def test_outside_include_needs_explicit_yes(tmp_path):
    """rad 폴더 밖 절대경로 include(PC 의 다른 폴더 파일)는 목록을 보여 주고 Y 확인이 있어야만 올린다.
    -NonInteractive 실행은 묻지 않고 제외, 상위 경로(..) include 는 문제로 남고 올리지 않는다."""
    res, rad = make_case(tmp_path, big=10)
    secret = tmp_path / "private" / "secret.inc"
    secret.parent.mkdir()
    secret.write_text("/SECRET\n")
    (tmp_path / "up.inc").write_text("/UP\n")
    rad.write_text(f"/INCLUDE inc/b.inc\n/INCLUDE \"{secret}\"\n/INCLUDE ../up.inc\n/END\n", encoding="utf-8")
    body = f"""
$p0 = Get-EslUploadPlan '{res}' '{rad}'
"base=" + ((@($p0.Files | ForEach-Object {{ $_.Rel }}) | Where-Object {{ $_ -like 'rad/*' }}) -join ',')
"outside=" + (@($p0.Outside | ForEach-Object {{ $_.Spec }}) -join ',')
foreach ($p in $p0.Problems) {{ Write-Output "PROB|$p" }}
foreach ($w in $p0.Warnings) {{ Write-Output "WARN|$w" }}
$p1 = Confirm-EslOutsideIncludes $p0
"final=" + ((@($p1.Files | ForEach-Object {{ $_.Rel }}) | Where-Object {{ $_ -like 'rad/*' }}) -join ',')
"""
    interactive = "function Test-EslNonInteractive { return $false }\n"
    # 1) -NonInteractive(실제 명령줄) -> 묻지 않고 제외
    r = run_ps(tmp_path, body)
    out = kv(r)
    assert out.get("base") == "rad/drop_0000.rad,rad/inc/b.inc", (r.stdout, r.stderr)
    assert out["outside"] == str(secret) and out["final"] == out["base"] and "ASK" not in r.stdout
    assert str(secret) in r.stdout and "비대화형" in r.stdout                       # 목록은 보여 줌
    assert any("../up.inc" in ln and "rad 폴더 밖 상대경로" in ln for ln in r.stdout.splitlines() if ln.startswith("PROB|"))
    assert any("올리지 않습니다" in ln and str(secret) in ln for ln in r.stdout.splitlines() if ln.startswith("WARN|"))
    # 2) 대화형 + Enter(기본 N) / n -> 제외
    for ans in ([], ["n"]):
        r = run_ps(tmp_path, interactive + body, inputs=ans)
        out = kv(r)
        assert "ASK" in r.stdout and out.get("final") == "rad/drop_0000.rad,rad/inc/b.inc", (ans, r.stdout, r.stderr)
    # 3) 대화형 + Y -> rad/<파일 이름> 으로 포함(상위 경로 include 는 여전히 제외)
    r = run_ps(tmp_path, interactive + body, inputs=["Y"])
    assert kv(r).get("final") == "rad/drop_0000.rad,rad/inc/b.inc,rad/secret.inc", (r.stdout, r.stderr)
    assert "up.inc" not in kv(r)["final"]


def test_loopback_proxy_and_url(tmp_path):
    r = run_ps(tmp_path, """
"lb=" + ((@('http://127.0.0.1:8080/esl', 'http://localhost/esl', 'http://[::1]:9/esl', 'http://10.1.2.3/esl', 'http://dash.corp.local/esl') | ForEach-Object { Test-EslLoopback $_ }) -join ',')
$c = New-EslHttpClient 'http://127.0.0.1:1/esl' 30
"timeout=" + $c.Timeout.TotalSeconds
"url=" + (Get-EslCaseUrl 'http://dash/esl' 'p 1' 'up_1')
"norm=" + (ConvertTo-EslServerUrl ' "http://dash:8080/esl/" ')
try { ConvertTo-EslServerUrl 'dash/esl'; 'bad=accepted' } catch { 'bad=rejected' }
""")
    out = kv(r)
    assert out.get("lb") == "True,True,True,False,False", (r.stdout, r.stderr)
    assert out["timeout"] == "30"
    assert out["url"] == "http://dash/esl/p/p%201/cases/new?upload=up_1"
    assert out["norm"] == "http://dash:8080/esl" and out["bad"] == "rejected"


def test_server_url_asked_and_saved(tmp_path):
    cfgp = tmp_path / "esl_deploy.json"
    cfgp.write_text(json.dumps({"hw_exe": "x", "protected_roots": []}))
    r = run_ps(tmp_path, f"""
$cfg = Get-Content -Raw '{cfgp}' | ConvertFrom-Json
"url=" + (Get-EslServerUrl '{cfgp}' $cfg)
$cfg2 = Get-Content -Raw '{cfgp}' | ConvertFrom-Json
"again=" + (Get-EslServerUrl '{cfgp}' $cfg2)
""", inputs=["ftp://x", "http://dash.corp/esl/"])
    out = kv(r)
    assert out.get("url") == "http://dash.corp/esl", (r.stdout, r.stderr)
    assert out["again"] == "http://dash.corp/esl" and r.stdout.count("ASK") == 2   # 두 번째는 묻지 않음
    saved = json.loads(cfgp.read_text())
    assert saved["server_url"] == "http://dash.corp/esl" and saved["hw_exe"] == "x"


# ---- 업로드 ----------------------------------------------------------------------------------------

UPLOAD = """
$ctx = New-EslContext '{url}'
$plan = Get-EslUploadPlan '{res}' '{rad}'
try {{
    $r = Invoke-EslPcUpload $ctx $plan 'drop' (Get-EslUploadKey '{anchor}')
    "ok=" + $r.Ok
    "upload_id=" + $r.UploadId
    "url=" + $r.Url
}}
catch {{ "error=" + $_.Exception.Message }}
"""


def _check_server_files(state, upload_id, res, rad):
    up = state.uploads[upload_id]
    for f in up["files"]:
        rel = f["rel"]
        if rel.startswith("results/csv/"):
            local = res / rel[len("results/csv/"):]
        else:
            local = rad.parent / rel[len("rad/"):]
        assert f["done"], rel
        assert bytes(f["data"]) == local.read_bytes(), rel
        assert f["sha256"] == hashlib.sha256(local.read_bytes()).hexdigest()


def test_upload_flow_with_faults(tmp_path, server):
    state, url = server
    state.codes["123456"] = "p1"
    state.required_includes = ["rad/late.inc"]            # 서버 rad 파싱이 찾은 추가 include
    state.drop_after_write = {2}                           # 쓰고 끊김 -> 재시도 -> 409 received
    state.fail_status = {4: 503}                           # 일시 오류 -> 백오프 재시도
    state.corrupt_puts = {6}                               # 청크 sha256 불일치 -> 같은 offset 재전송
    res, rad = make_case(tmp_path)
    anchor = tmp_path / "drop.h3d"
    anchor.write_bytes(b"HYPER3D" + b"0" * 100)
    r = run_ps(tmp_path, UPLOAD.format(url=url, res=res, rad=rad, anchor=anchor), inputs=["999999", "123456"])
    out = kv(r)
    assert out.get("ok") == "True", (r.stdout, r.stderr)
    uid = out["upload_id"]
    assert out["url"] == f"{url}/p/p1/cases/new?upload={uid}"
    assert f"BROWSER {url}/p/p1/cases/new?upload={uid}" in r.stdout
    assert "연결 실패" in r.stdout and "CLIENT_CODE_INVALID" in r.stdout   # 틀린 코드(401) -> 다시 질문
    assert state.exchanges[-1]["device_name"]
    _check_server_files(state, uid, res, rad)
    rels = [f["rel"] for f in state.uploads[uid]["files"]]
    assert "rad/late.inc" in rels and state.uploads[uid]["state"] == "COMPLETED"
    assert "누락 include 1개" in r.stdout
    assert "서버가 받은 크기부터 이어 올립니다" in r.stdout
    assert "다시 시도" in r.stdout and "청크 sha256 불일치" in r.stdout
    puts = [e for e in state.log if e[0] == "PUT"]
    assert max(int(e[2]) for e in puts) > 0                                 # 여러 청크
    # 청크는 chunk_size 이하(서버가 413 을 주지 않았음), 진행률·속도·남은 시간 표시
    assert "남은 시간" in r.stdout and "/s" in r.stdout
    # 토큰: DPAPI(대역) 로 저장, 평문 없음
    tok = (tmp_path / "appdata" / "esl" / "client_token.bin").read_text()
    assert tok.startswith("MOCK:") and "esl_ct_" not in tok
    st = json.loads((tmp_path / "appdata" / "esl" / "uploads.json").read_text())
    (key, ent), = st.items()
    assert key.startswith(str(anchor).lower() + "|") and ent["upload_id"] == uid

    # 같은 파일 다시 실행: 이미 완료된 세션 -> 새로 만들지 않고 브라우저만
    n_create = sum(1 for e in state.log if e[0] == "POST" and e[1] == "/uploads")
    r2 = run_ps(tmp_path, UPLOAD.format(url=url, res=res, rad=rad, anchor=anchor))
    assert kv(r2).get("upload_id") == uid, (r2.stdout, r2.stderr)
    assert "이미 올린 업로드" in r2.stdout and "ASK" not in r2.stdout     # 저장된 토큰 사용
    assert sum(1 for e in state.log if e[0] == "POST" and e[1] == "/uploads") == n_create


def test_resume_after_interrupted_run(tmp_path, server):
    state, url = server
    state.codes["111111"] = "p1"
    state.fail_puts_from = 3                               # 2청크 받은 뒤 계속 503 -> 클라이언트 포기
    res, rad = make_case(tmp_path)
    anchor = tmp_path / "drop.h3d"
    anchor.write_bytes(b"HYPER3D")
    body = UPLOAD.format(url=url, res=res, rad=rad, anchor=anchor)
    r = run_ps(tmp_path, body, inputs=["111111"])
    out = kv(r)
    assert "error" in out and "5회 재시도 후" in out["error"], (r.stdout, r.stderr)
    (uid,) = state.uploads
    received1 = sum(len(f["data"]) for f in state.uploads[uid]["files"])
    assert received1 > 0
    n_put_before = len([e for e in state.log if e[0] == "PUT"])
    state.fail_puts_from = None
    r2 = run_ps(tmp_path, body)
    out2 = kv(r2)
    assert out2.get("ok") == "True" and out2["upload_id"] == uid, (r2.stdout, r2.stderr)
    assert "이전 업로드를 이어 갑니다" in r2.stdout
    assert len(state.uploads) == 1                          # 새 세션 없음
    new_puts = [e for e in state.log if e[0] == "PUT"][n_put_before:]
    assert int(new_puts[0][2]) > 0 or received1 >= 300_000   # 받은 위치부터(처음부터 다시 보내지 않음)
    assert sum(int(e[2]) == 0 for e in new_puts if "/files/0" in e[1]) <= 1
    _check_server_files(state, uid, res, rad)

    # 결과 파일이 바뀌면(다시 추출) 이전 세션과 다름 -> 새 세션(이전 미완료는 취소)
    state.required_includes = []
    (res / "frames.csv").write_text("frame,t\n0,0.0\n1,0.1\n")
    r3 = run_ps(tmp_path, body)
    assert kv(r3).get("ok") == "True", (r3.stdout, r3.stderr)
    assert len(state.uploads) == 2 and "파일이 달라 새로 올립니다" in r3.stdout


def test_token_expired_or_revoked_asks_code_again(tmp_path, server):
    state, url = server
    state.codes["222222"] = "p1"
    state.codes["333333"] = "p1"
    res, rad = make_case(tmp_path, big=1000)
    anchor = tmp_path / "drop.h3d"
    anchor.write_bytes(b"HYPER3D")
    body = UPLOAD.format(url=url, res=res, rad=rad, anchor=anchor)
    r = run_ps(tmp_path, body, inputs=["222222"])
    assert kv(r).get("ok") == "True", (r.stdout, r.stderr)
    # 서버에서 폐기 -> 401 -> 코드 다시 묻기 -> 같은 사용자 새 토큰으로 계속
    state.tokens.clear()
    (res / "frames.csv").write_text("frame,t\n0,0.0\n1,0.1\n2,0.2\n")
    r2 = run_ps(tmp_path, body, inputs=["333333"])
    assert kv(r2).get("ok") == "True", (r2.stdout, r2.stderr)
    assert "토큰 만료·폐기" in r2.stdout and r2.stdout.count("ASK") == 1
    # 저장된 토큰의 만료 시각이 지났으면 서버에 묻기 전에 다시 연결
    tokp = tmp_path / "appdata" / "esl" / "client_token.bin"
    import base64
    info = json.loads(base64.b64decode(tokp.read_text()[5:]))
    info["expires_at"] = "2020-01-01T00:00:00+00:00"
    tokp.write_text("MOCK:" + base64.b64encode(json.dumps(info).encode()).decode())
    r3 = run_ps(tmp_path, f"$ctx = New-EslContext '{url}'\n[void](Connect-EslClient $ctx)\n'tok=' + $ctx.Token.StartsWith('esl_ct_')",
                inputs=[])
    assert "만료되었습니다" in r3.stdout and "연결 코드를 입력하지 않았습니다" in (r3.stdout + r3.stderr)
    # 코드 잠금(429): 재시도하지 않고 바로 안내
    state.locked = True
    n_ex = len(state.exchanges)
    r5 = run_ps(tmp_path, f"$ctx = New-EslContext '{url}'\ntry {{ Connect-EslClient $ctx -Force }} catch {{ 'err=' + $_.Exception.Message }}",
                inputs=["444444"])
    assert "잠시 잠겼습니다" in kv(r5).get("err", ""), (r5.stdout, r5.stderr)
    assert len(state.exchanges) == n_ex + 1 and "다시 시도" not in r5.stdout
    # 다른 서버 주소로 저장된 토큰은 쓰지 않음
    r4 = run_ps(tmp_path, "$ctx = New-EslContext 'http://127.0.0.1:9/esl'\n'tok=' + [bool](Read-EslToken $ctx)")
    assert kv(r4)["tok"] == "False" and "서버" in r4.stdout


def test_real_dpapi_refused_off_windows(tmp_path):
    """Windows 가 아니면 Protect-EslSecret 은 거부(ConvertFrom-SecureString 이 암호화하지 않는 OS 에서 평문 저장 금지)."""
    script = tmp_path / "p.ps1"
    script.write_text(f". '{LIB}'\ntry {{ Protect-EslSecret 'x'; 'r=stored' }} catch {{ 'r=refused' }}\n", encoding="utf-8")
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)], capture_output=True, text=True,
                       timeout=120, env=dict(os.environ, OS="Linux"))
    assert kv(r)["r"] == "refused", (r.stdout, r.stderr)


def test_esl_run_upload_mode_end_to_end(tmp_path, server):
    """esl_run.ps1 -Mode upload(ESL_upload.bat) 를 그대로 실행: 저장된 토큰(대역 DPAPI = 이 OS 의 SecureString) 사용."""
    state, url = server
    res, rad = make_case(tmp_path, big=200_000)
    priv = tmp_path / "private" / "secret.inc"
    priv.parent.mkdir()
    priv.write_text("/SECRET\n")
    rad.write_text("/INCLUDE inc/b.inc\n/INCLUDE \"C:\\models\\mat.inc\"\n"     # 누락 없음 -> 묻지 않음
                   f"/INCLUDE \"{priv}\"\n/END\n")                                   # rad 폴더 밖 -> 비대화형은 제외
    app = tmp_path / "appdata" / "esl"
    app.mkdir(parents=True)
    (app / "esl_deploy.json").write_text(json.dumps({"hw_exe": "", "work_root": str(tmp_path / "work"),
                                                     "deploy_dir": str(tmp_path / "dep"), "protected_roots": [],
                                                     "server_url": url}))
    state.tokens["esl_ct_pre"] = {"project_id": "p9", "user": "kim"}
    plain = json.dumps({"server_url": url, "token": "esl_ct_pre", "project_id": "p9", "user": "kim",
                        "expires_at": "2099-01-01T00:00:00+00:00"})
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "appdata"), OS="Windows_NT")
    enc = subprocess.run([PWSH, "-NoProfile", "-Command",
                          f". '{LIB}'; Write-EslTextFile '{app / 'client_token.bin'}' (Protect-EslSecret $env:P)"],
                         capture_output=True, text=True, timeout=120, env=dict(env, P=plain))
    assert enc.returncode == 0, enc.stderr
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", RUN, "-Mode", "upload", str(res), str(rad)],
                       capture_output=True, text=True, timeout=180, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    (uid,) = state.uploads
    assert state.uploads[uid]["name"] == "drop" and state.uploads[uid]["project_id"] == "p9"
    assert f"/p/p9/cases/new?upload={uid}" in r.stdout
    _check_server_files(state, uid, res, rad)
    assert "rad/secret.inc" not in [f["rel"] for f in state.uploads[uid]["files"]] and "비대화형" in r.stdout
    # 결과 폴더가 아니면 거부
    r2 = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", RUN, "-Mode", "upload", str(rad.parent), str(rad)],
                        capture_output=True, text=True, timeout=120, env=env)
    assert r2.returncode == 1 and "done.json" in r2.stdout
