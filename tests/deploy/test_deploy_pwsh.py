"""PowerShell 배포 스크립트(pwsh 7 로 Linux 임시 폴더에서): 파싱 오류 0, 대시보드 .env·.tools 해석(비밀번호 비노출),
deploy.json 기본값 채움, 작업 인자, DB URL, 코드 배치, 포트 읽기, 런타임 비밀 파일, 설정 계획 호출, 프런트 해시, Python 선택."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import DEPLOY, PWSH, ROOT, needs_pwsh, run_pwsh

pytestmark = needs_pwsh
COMMON = DEPLOY / "install-common.ps1"


def _dot(*names: str) -> str:
    return "".join(f". '{DEPLOY / n}'\n" for n in names)


def _json_out(r: subprocess.CompletedProcess):
    assert r.returncode == 0, r.stdout + r.stderr
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("JSON=")][-1]
    return json.loads(line[5:])


def test_parse_all_ps1():
    files = sorted(DEPLOY.rglob("*.ps1"))
    assert len(files) >= 14
    lst = ",".join(f"'{p}'" for p in files)
    r = subprocess.run([PWSH, "-NoProfile", "-Command",
                        f"foreach ($f in @({lst})) {{ $t=$null;$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($f,[ref]$t,[ref]$e); "
                        "foreach ($x in $e) { Write-Output \"${f}:$($x.Extent.StartLineNumber): $($x.Message)\" } }; 'DONE'"],
                       capture_output=True, text=True, timeout=180)
    assert r.stdout.strip() == "DONE", r.stdout + r.stderr


def _fake_dashboard(tmp_path: Path) -> Path:
    d = tmp_path / "simdashboard"
    for v in ("3.12.9", "3.12.13"):
        p = d / ".tools" / "python" / f"cpython-{v}-windows-x86_64-none"
        p.mkdir(parents=True)
        (p / "python.exe").write_text("x")
    (d / ".tools" / "python" / "cpython-3.11.9-windows-x86_64-none").mkdir()
    n = d / ".tools" / "node-v22.23.2-win-x64"
    n.mkdir(parents=True)
    (n / "node.exe").write_text("x")
    (d / ".env").write_text('POSTGRES_BIN="E:\\PostgreSQL\\18\\bin"\n'
                            "DATABASE_URL=postgresql+psycopg://dash_user:S3cretPw@127.0.0.1:5434/simdash\n"
                            "WINDOWS_WEB_BASE_PATH=/home/\nWINDOWS_WEB_PORT=8080\n", encoding="utf-8")
    return d


def test_dashboard_env_and_merge(tmp_path):
    dash = _fake_dashboard(tmp_path)
    body = _dot("dashboard-env.ps1") + f"""
$d = Get-DashboardRuntimeDefaults -DashboardRoot '{dash}'
$cfg = [pscustomobject]@{{ pg_bin = ''; pg_host = '10.0.0.5'; python_exe = $null }}
$filled = Merge-DashboardDefaults -Config $cfg -Defaults $d
'JSON=' + (@{{ d = $d; cfg = $cfg; filled = @($filled) }} | ConvertTo-Json -Depth 4 -Compress)
"""
    r = run_pwsh(body, tmp_path)
    out = _json_out(r)
    d = out["d"]
    assert d["PgBin"] == "E:\\PostgreSQL\\18\\bin" and d["PgHost"] == "127.0.0.1" and d["PgPort"] == 5434
    assert d["PythonExe"].endswith("cpython-3.12.13-windows-x86_64-none/python.exe")   # 3.12 중 최신
    assert d["NodeExe"].endswith("node-v22.23.2-win-x64/node.exe")
    assert d["WebBasePath"] == "/home/" and d["WebPort"] == 8080
    assert out["cfg"]["pg_host"] == "10.0.0.5"                                           # deploy.json 명시 값 우선
    assert out["cfg"]["pg_bin"] == "E:\\PostgreSQL\\18\\bin" and out["cfg"]["pg_port"] == 5434
    assert sorted(out["filled"]) == ["pg_bin", "pg_port", "python_exe"]
    assert "S3cretPw" not in r.stdout + r.stderr and "dash_user" not in r.stdout + r.stderr


def test_task_arguments_without_frontend(tmp_path):
    """작업 인자에는 --frontend 가 없다(프런트 정적 서빙은 설정 server.frontend_root 가 유일한 출처)."""
    body = _dot("install-common.ps1") + """
$rt = '/srv/esl/rt'
$o = [ordered]@{
  def = Get-EslTaskArguments -Command backend -RuntimeDir $rt -ConfigPath '/srv/esl/rt/config/esl_platform.yaml'
  custom = Get-EslTaskArguments -Command worker -RuntimeDir ($rt + '/') -ConfigPath '/etc/esl/x.yaml'
  specs = @(Get-EslTaskSpecs -RuntimeDir $rt | ForEach-Object { $_.Name })
  specArgs = @(Get-EslTaskSpecs -RuntimeDir $rt | ForEach-Object { $_.Args })
  oldFn = [bool](Get-Command Get-EslTaskFrontend -ErrorAction SilentlyContinue)
  access = Get-EslAccessUrl -Dash ([pscustomobject]@{ EnvFile = 'x'; WebPort = 8080 })
  access80 = Get-EslAccessUrl -Dash ([pscustomobject]@{ EnvFile = 'x'; WebPort = $null })
  accessNone = Get-EslAccessUrl -Dash $null
  under = @((Test-EslUnderPath '/a/b/c' '/a/b'), (Test-EslUnderPath '/a/bc' '/a/b'), (Test-EslUnderPath '/A/B' '/a/b'))
}
'JSON=' + ($o | ConvertTo-Json -Depth 4 -Compress)
"""
    o = _json_out(run_pwsh(body, tmp_path))
    assert o["def"] == '"/srv/esl/rt/app/esl_service.py" backend --runtime "/srv/esl/rt"'      # 기본 설정이면 --config 생략
    assert o["custom"] == '"/srv/esl/rt/app/esl_service.py" worker --runtime "/srv/esl/rt" --config "/etc/esl/x.yaml"'
    assert o["specs"] == ["ESL-Backend", "ESL-Worker"]
    assert not any("--frontend" in a for a in o["specArgs"]) and o["oldFn"] is False
    assert o["access"].endswith(":8080/esl/") and o["access80"].endswith("/esl/") and ":80/" not in o["access80"]
    assert o["accessNone"] == "http://<대시보드 주소>/esl/"
    assert o["under"] == [True, False, True]


def _guide(tmp_path: Path, env: str | None, extra: str = "") -> str:
    dash = tmp_path / "dash"
    dash.mkdir(exist_ok=True)
    if env is not None:
        (dash / ".env").write_text(env, encoding="utf-8")
    body = _dot("install-common.ps1") + f"""
Write-EslConnectGuide -Port 8123 -BasePath '/esl' -DashboardRoot '{dash}' -FrontendRoot 'D:\\esl\\.runtime\\frontend' -SnippetDir '/x/caddy' {extra}
"""
    r = run_pwsh(body, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_connect_guide_vite_proxy_default(tmp_path):
    """연결 안내(physicsai Write-PhysicsAIConnectGuide 와 같은 문구): Vite 프록시 + 백엔드 정적 서빙이 기본, Caddy 는 대안."""
    out = _guide(tmp_path, "X=1\n")
    assert "VITE_ESL_TARGET=http://127.0.0.1:8123 , SIMDASH_ESL_ENABLED=true 를 넣고 대시보드를 다시 시작하세요" in out
    assert "백엔드가 프런트 D:\\esl\\.runtime\\frontend 를 /esl/ 아래에 서빙 — 설정 server.frontend_root" in out
    assert "접속: http://<대시보드 주소>/esl/" in out and "health: http://127.0.0.1:8123/esl/api/health" in out
    assert "Caddy를 쓰는 설치: /x/caddy/esl.caddy" in out
    out = _guide(tmp_path, 'SIMDASH_ESL_ENABLED=true\nVITE_ESL_TARGET="http://127.0.0.1:8123"\n')
    assert "SIMDASH_ESL_ENABLED=true — 이미 들어 있음" in out
    out = _guide(tmp_path, "SIMDASH_ESL_ENABLED=true\nVITE_ESL_TARGET=http://127.0.0.1:8100\n")   # 포트가 다르면 다시 안내
    assert "를 넣고 대시보드를 다시 시작하세요" in out
    out = _guide(tmp_path, "SIMDASH_ESL_ENABLED=true\nVITE_ESL_TARGET=http://127.0.0.1:8123\n",
                 "-EnvResult ([pscustomobject]@{ added = @('VITE_ESL_TARGET'); backup = '/rt/_backup/T/dashboard.env' })")
    assert "— 추가함(VITE_ESL_TARGET, 이전 .env 사본: /rt/_backup/T/dashboard.env). 대시보드를 다시 시작하세요" in out


def test_connect_guide_bundle_caddy_with_vite_option(tmp_path):
    out = _guide(tmp_path, None, "-Bundle")
    assert "(묶음 설치 — Caddy 기준)" in out and "/x/caddy/esl.caddy" in out and "ESL_PORT=8123" in out
    assert "Caddy 없이 대시보드 Vite 프록시로 쓰려면: 설정 server.frontend_root: D:/esl/.runtime/frontend" in out
    assert "VITE_ESL_TARGET=http://127.0.0.1:8123 , SIMDASH_ESL_ENABLED=true 를 넣고 대시보드를 다시 시작하세요" in out


def test_dashboard_env_plan_cell(tmp_path):
    body = _dot("install-common.ps1") + """
$p = [pscustomobject]@{ path = 'D:/dash/.env'; exists = $true; add = @('VITE_ESL_TARGET=x')
  rows = @([pscustomobject]@{ key = 'VITE_ESL_TARGET'; action = '추가' }, [pscustomobject]@{ key = 'SIMDASH_ESL_ENABLED'; action = '이미 있음' }) }
$o = [ordered]@{ a = (Format-EslDashboardEnvPlan $p); none = (Format-EslDashboardEnvPlan $null)
  missing = (Format-EslDashboardEnvPlan ([pscustomobject]@{ path = 'D:/dash/.env'; exists = $false })) }
'JSON=' + ($o | ConvertTo-Json -Compress)
"""
    o = _json_out(run_pwsh(body, tmp_path))
    assert o["a"] == "VITE_ESL_TARGET 추가, SIMDASH_ESL_ENABLED 이미 있음 — 바꾸기 전 _backup에 사본, 대시보드 재시작 필요 (D:/dash/.env)"
    assert o["none"].startswith("(대시보드 없음") and o["missing"].startswith("D:/dash/.env 없음")


def test_db_url_roundtrip(tmp_path):
    body = _dot("install-common.ps1") + """
$u = New-EslDbUrl -Role 'esl_app' -Password "p@ss:w/rd'%" -PgHost '127.0.0.1' -PgPort 5434 -DbName 'esl'
$p = ConvertFrom-EslDbUrl $u
$bad = ConvertFrom-EslDbUrl 'not a url'
'JSON=' + (@{ ok = ($p.Password -ceq "p@ss:w/rd'%"); user = $p.User; host = $p.Host; port = $p.Port; db = $p.Db; bad = ($null -eq $bad); enc = ($u -notmatch 'p@ss') } | ConvertTo-Json -Compress)
"""
    o = _json_out(run_pwsh(body, tmp_path))
    assert o == {"ok": True, "user": "esl_app", "host": "127.0.0.1", "port": 5434, "db": "esl", "bad": True, "enc": True}


def test_runtime_secret_and_gitignore(tmp_path):
    rt = tmp_path / "rt"
    body = _dot("install-common.ps1") + f"""
$rt = '{rt}'
Write-EslRuntimeSecret -RuntimeDir $rt -DbUrl 'postgresql+psycopg://esl_app:Xy7pw@127.0.0.1:5432/esl' -WarningAction SilentlyContinue
Write-EslRuntimeSecret -RuntimeDir $rt -DbUrl 'postgresql+psycopg://esl_app:Xy7pw@127.0.0.1:5432/esl' -WarningAction SilentlyContinue
Set-EslRuntimeGitIgnore -RuntimeDir $rt
'JSON=' + (@{{ back = ((Get-EslDbUrl -RuntimeDir $rt) -ceq 'postgresql+psycopg://esl_app:Xy7pw@127.0.0.1:5432/esl'); none = (Get-EslDbUrl -RuntimeDir '{tmp_path / "none"}') }} | ConvertTo-Json -Compress)
"""
    r = run_pwsh(body, tmp_path)
    o = _json_out(r)
    assert o == {"back": True, "none": ""}
    assert "Xy7pw" not in r.stdout                                                      # 값은 출력하지 않음
    assert "(변경 없음)" in r.stdout
    raw = (rt / "secrets" / "database_url").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and not raw.endswith(b"\n")
    assert (rt / ".gitignore").read_text() == "*\n"


def test_install_app_and_endpoint(tmp_path):
    rt = tmp_path / "rt"
    cfg = tmp_path / "flow.yaml"
    cfg.write_text("server: {host: 127.0.0.1, port: 8444, base_path: /esl}\n", encoding="utf-8")
    blk = tmp_path / "block.yaml"
    blk.write_text("schema_version: 1\nserver:\n  host: 127.0.0.1\n  port: 8555\n  base_path: /esl\n", encoding="utf-8")
    (ROOT / "esl" / "__pycache__").mkdir(exist_ok=True)
    body = _dot("install-common.ps1") + f"""
Install-EslApp -Source '{ROOT}' -Dest '{rt / "app"}' -BackupDir '{rt / "_backup" / "T1"}'
Install-EslApp -Source '{ROOT}' -Dest '{rt / "app"}' -BackupDir '{rt / "_backup" / "T2"}'
$py = '{sys.executable}'
$o = [ordered]@{{
  viaLauncher = Get-EslEndpoint -ConfigPath '{blk}' -VenvPy $py -Launcher (Get-EslLauncher '{rt}')
  flowYaml = Get-EslEndpoint -ConfigPath '{cfg}'
  blockYaml = Get-EslEndpoint -ConfigPath '{blk}'
  missing = Get-EslEndpoint -ConfigPath '{tmp_path / "nope.yaml"}'
}}
'JSON=' + ($o | ConvertTo-Json -Depth 4 -Compress)
"""
    o = _json_out(run_pwsh(body, tmp_path))
    assert o["viaLauncher"] == {"Port": 8555, "BasePath": "/esl", "Health": "http://127.0.0.1:8555/esl/api/health"}
    assert o["flowYaml"]["Port"] == 8444 and o["blockYaml"]["Port"] == 8555 and o["missing"]["Port"] == 8110
    app = rt / "app"
    for rel in ("esl_service.py", "alembic.ini", "pyproject.toml", "esl/__init__.py", "backend/esl_platform/check.py",
                "worker/esl_worker/__main__.py", "migrations/versions/0003_library_report.py"):
        assert (app / rel).is_file(), rel
    assert not list(app.rglob("__pycache__"))
    assert (rt / "_backup" / "T2" / "app" / "esl_service.py").is_file()                # 이전 app 은 지우지 않고 이동


def test_setup_config_via_pwsh(tmp_path):
    """PowerShell → setup_config.py(JSON 입력·출력 파일) 경계: 단일 원소 배열·한글 경로 표 행이 그대로 돌아온다."""
    rt = tmp_path / "rt"
    (tmp_path / "inputs").mkdir()
    body = _dot("install-common.ps1") + f"""
$defaults = [ordered]@{{ install_mode = 'repo'; install_root = '{rt}'; config_path = '{rt / "config" / "esl_platform.yaml"}'
  esl_root = '{tmp_path / "esl_root"}'; input_roots = @('{tmp_path / "inputs"}'); spdm_roots = @(); db_name = 'esl'; db_role = 'esl_app' }}
$inputs = [ordered]@{{ mode = 'repo'; source_root = '{ROOT}'; code_root = '{ROOT}'; runtime_dir = '{rt}'; stamp = 'T1'
  deploy_path = '{rt / "deploy.json"}'; deploy_defaults = $defaults; deploy_explicit = [ordered]@{{}} }}
$plan = Invoke-EslSetupConfig -VenvPy '{sys.executable}' -Action plan -RuntimeDir '{rt}' -Inputs $inputs
$res = Invoke-EslSetupConfig -VenvPy '{sys.executable}' -Action write -RuntimeDir '{rt}' -Inputs $inputs
$ok = Write-EslConfigValidation -Result $res
'JSON=' + (@{{ src = $plan.config_source; roots = @($plan.input_roots); valid = $ok; written = @($res.write.written).Count }} | ConvertTo-Json -Compress)
"""
    o = _json_out(run_pwsh(body, tmp_path))
    assert o["src"] == "example" and o["roots"] == [str(tmp_path / "inputs")] and o["valid"] is True and o["written"] == 5


def _py_frontend_hash(fe: Path) -> str:
    """node-select.ps1 Get-EslFrontendSourceHash 와 같은 규칙(Python 참조 구현)."""
    import fnmatch

    rels = [p.name for p in fe.iterdir() if p.is_file() and any(fnmatch.fnmatchcase(p.name, pat) for pat in
                                                                ("index.html", "package.json", "package-lock.json", "vite.config.*", "tsconfig*.json"))]
    for tree in ("src", "public"):
        if (fe / tree).is_dir():
            rels += [p.relative_to(fe).as_posix() for p in (fe / tree).rglob("*") if p.is_file()]
    rels.sort()
    crlf, lf = b"\r\n", b"\n"
    digests = [hashlib.sha256((fe / r).read_bytes().replace(crlf, lf)).hexdigest() for r in rels]
    buf = "".join(r + "\0" + d + "\n" for r, d in zip(rels, digests))
    return hashlib.sha256(buf.encode("utf-8")).hexdigest()


def test_frontend_source_hash(tmp_path):
    fe = tmp_path / "frontend"
    (fe / "src" / "a").mkdir(parents=True)
    (fe / "index.html").write_bytes(b"<html>\r\n</html>\r\n")
    (fe / "package.json").write_text("{}")
    (fe / "vite.config.ts").write_text("x")
    (fe / "README.md").write_text("ignored")
    (fe / "src" / "a" / "b.tsx").write_text("const x = 1\n")
    body = _dot("node-select.ps1") + f"'JSON=' + (@{{ h = (Get-EslFrontendSourceHash -FrontendDir '{fe}') }} | ConvertTo-Json -Compress)"
    h1 = _json_out(run_pwsh(body, tmp_path))["h"]
    assert h1 == _py_frontend_hash(fe)
    (fe / "index.html").write_bytes(b"<html>\n</html>\n")                 # CRLF→LF 만 다르면 같은 해시
    (fe / "README.md").write_text("changed")
    assert _json_out(run_pwsh(body, tmp_path))["h"] == h1
    (fe / "src" / "a" / "b.tsx").write_text("const x = 2\n")
    assert _json_out(run_pwsh(body, tmp_path))["h"] != h1


def test_python_select(tmp_path):
    py312 = shutil.which("python3.12")
    py313 = shutil.which("python3.13") or sys.executable
    if not py312:
        pytest.skip("python3.12 없음")
    body = _dot("python-select.ps1") + f"""
$why = ''
$ok = Test-EslPython312 -Exe '{py312}' -Reason ([ref]$why)
$why2 = ''
$no = Test-EslPython312 -Exe '{py313}' -Reason ([ref]$why2)
$why3 = ''
$gone = Test-EslPython312 -Exe '{tmp_path / "missing" / "python"}' -Reason ([ref]$why3)
$sel = Select-EslPython -Candidates @([pscustomobject]@{{ Label = 'bad'; Exe = '{py313}'; PreArgs = @() }},
                                     [pscustomobject]@{{ Label = 'good'; Exe = '{py312}'; PreArgs = @() }})
$err = ''
try {{ Assert-EslPython312 -Exe '{py313}' | Out-Null }} catch {{ $err = $_.Exception.Message }}
'JSON=' + (@{{ ok = $ok.Version; why2 = $why2; gone = ($null -eq $gone); why3 = $why3; sel = $sel.Label; err = $err }} | ConvertTo-Json -Compress)
"""
    o = _json_out(run_pwsh(body, tmp_path))
    assert o["ok"].startswith("3.12.") and "3.12 아님" in o["why2"] and o["gone"] and o["why3"]
    assert o["sel"] == "good" and "python_exe" in o["err"]


def test_setup_refuses_outside_repo(tmp_path):
    """setup.ps1 은 git 폴더가 아니면(묶음을 푼 폴더 등) install.ps1 안내로 중단 — 아무것도 바꾸지 않는다."""
    fake = tmp_path / "pkg"
    (fake / "deploy").mkdir(parents=True)
    for n in ("setup.ps1", "install-common.ps1", "loopback-http.ps1", "python-select.ps1", "node-select.ps1", "dashboard-env.ps1"):
        shutil.copy(DEPLOY / n, fake / "deploy" / n)
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(fake / "deploy" / "setup.ps1"), "-NonInteractive"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "install.ps1" in (r.stdout + r.stderr)
    assert not (fake / ".runtime").exists()
