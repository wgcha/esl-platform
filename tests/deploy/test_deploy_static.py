"""배포 스크립트 정적 검사(pwsh 없어도 실행): 파일 구성, 인코딩·줄끝, PowerShell 5.1 호환 문법, 비밀번호 취급, 작업 스케줄러 설정,
Caddy 스니펫, 예시 설정, requirements.lock, 클라이언트 update.bat 과의 구분, README 배포 절."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from conftest import DEPLOY, ROOT

PS1 = sorted(DEPLOY.rglob("*.ps1"))
BAT = sorted(DEPLOY.rglob("*.bat"))
PY = sorted(DEPLOY.rglob("*.py"))
EXPECTED = [
    "RESOURCES.txt", "caddy/esl.caddy", "collect-offline.ps1", "collect-offline.sh", "dashboard-env.ps1", "deploy.example.json",
    "esl_service.py", "install-common.ps1", "install.bat", "install.ps1", "loopback-http.ps1", "node-select.ps1",
    "python-select.ps1", "requirements.lock", "setup.ps1", "setup_config.py", "uninstall-tasks.ps1", "update-repo.ps1",
    "update.bat", "update.ps1",
    "demo/start-demo.bat", "demo/start-demo.ps1", "demo/stop-demo.bat", "demo/stop-demo.ps1", "demo/demo-python.ps1",
    "demo/demo_setup.py", "demo/demo_common.py", "demo/demo_db.py", "demo/demo_init.py", "demo/demo_procs.py",
    "demo/demo_seed.py", "demo/demo_synth.py",
]
PHYSICSAI_LOCK = Path("/home/user/wgcha/physicsai-phase3/deploy/requirements.lock")


def _text(p: Path) -> str:
    return p.read_bytes().decode("utf-8-sig")


def _code_lines(p: Path) -> list[tuple[int, str]]:
    """주석·도움말 블록(<# ... #>)·문자열을 뺀 코드 줄(대략)."""
    out, in_block = [], False
    for no, ln in enumerate(_text(p).splitlines(), 1):
        s = ln.strip()
        if in_block:
            if "#>" in s:
                in_block = False
            continue
        if s.startswith("<#"):
            in_block = "#>" not in s[2:]
            continue
        if s.startswith("#"):
            continue
        code = re.sub(r"'[^']*'|\"(?:[^\"`]|`.)*\"", "''", ln)
        code = code.split(" #", 1)[0]
        out.append((no, code))
    return out


def test_expected_files():
    missing = [f for f in EXPECTED if not (DEPLOY / f).is_file()]
    assert missing == []
    assert (ROOT / "config" / "esl_platform.prod.example.yaml").is_file()
    assert (ROOT / "backend" / "esl_platform" / "check.py").is_file()


def test_ps1_bom_crlf():
    assert len(PS1) >= 14
    for p in PS1:
        raw = p.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), f"{p}: 한글이 있으므로 UTF-8 BOM(PowerShell 5.1)"
        assert raw.count(b"\n") == raw.count(b"\r\n"), f"{p}: CRLF 줄끝"


def test_bat_ascii_crlf_and_delegate():
    assert {p.name for p in BAT} == {"install.bat", "update.bat", "start-demo.bat", "stop-demo.bat"}
    for p in BAT:
        raw = p.read_bytes()
        raw.decode("ascii")
        assert raw.count(b"\n") == raw.count(b"\r\n"), p
        text = raw.decode("ascii")
        ps1 = p.with_suffix(".ps1").name
        assert re.search(r'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0' + re.escape(ps1) + r'" %\*', text), p
        assert "set PSModulePath=" in text, p   # pwsh 7 창에서도 5.1 기본 모듈


PS7_ONLY = {
    "??": re.compile(r"\?\?"),
    "?.": re.compile(r"\?\.(?!\d)"),
    "&&/||": re.compile(r"&&|\|\|"),
    "삼항": re.compile(r"\s\?\s[^:]+\s:\s"),
    "-AsHashtable": re.compile(r"-AsHashtable\b", re.IGNORECASE),
    "ForEach -Parallel": re.compile(r"-Parallel\b", re.IGNORECASE),
    "$PSStyle/$IsWindows": re.compile(r"\$(PSStyle|IsWindows|IsLinux|IsMacOS|IsCoreCLR)\b", re.IGNORECASE),
    "Test-Json/Get-Error": re.compile(r"\b(Test-Json|Get-Error|ConvertFrom-Markdown)\b", re.IGNORECASE),
    "-AdditionalChildPath": re.compile(r"-AdditionalChildPath\b", re.IGNORECASE),
    "-SkipCertificateCheck": re.compile(r"-SkipCertificateCheck\b", re.IGNORECASE),
}


def _top_level_args(rest: str) -> list[str]:
    """명령 뒤 인자를 괄호 깊이 0의 공백으로 나눈다(닫는 괄호·파이프·세미콜론·중괄호에서 끝)."""
    args, cur, depth = [], "", 0
    for ch in rest:
        if depth == 0 and ch in ")|;}":
            break
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if depth == 0 and ch.isspace():
            if cur:
                args.append(cur)
            cur = ""
            continue
        cur += ch
    if cur:
        args.append(cur)
    return args


def test_ps5_compatible_syntax():
    """PowerShell 5.1 에 없는 문법·매개변수 금지(문자열·주석 밖). -NoProxy 는 loopback-http.ps1 의 PS 6+ 분기에서만."""
    hits = []
    for p in PS1:
        for no, code in _code_lines(p):
            for name, rx in PS7_ONLY.items():
                if rx.search(code):
                    hits.append(f"{p.relative_to(DEPLOY)}:{no}: {name}: {code.strip()}")
            if re.search(r"-NoProxy\b", code) and p.name != "loopback-http.ps1":
                hits.append(f"{p.relative_to(DEPLOY)}:{no}: -NoProxy")
            # Join-Path 위치 인자 3개 이상(PS 6+). Join-Path a b 만 허용
            for m in re.finditer(r"\bJoin-Path\s+", code):
                args = _top_level_args(code[m.end():])
                if len([a for a in args if not a.startswith("-")]) > 2:
                    hits.append(f"{p.relative_to(DEPLOY)}:{no}: Join-Path 인자 3개 이상: {code.strip()}")
    assert hits == [], "\n".join(hits)
    lb = _text(DEPLOY / "loopback-http.ps1")
    assert "PSVersion.Major -ge 6" in lb


def test_param_defaults_do_not_use_psscriptroot():
    """Windows PowerShell 5.1 은 param 기본값에서 $PSScriptRoot 가 빈 값."""
    for p in PS1:
        t = _text(p)
        m = re.search(r"^param\((.*?)^\)", t, re.DOTALL | re.MULTILINE)
        if m:
            code = "\n".join(ln.split("#", 1)[0] for ln in m.group(1).splitlines())
            assert "$PSScriptRoot" not in code, p


def test_passwords_never_as_arguments_or_files():
    for p in PS1:
        t = _text(p)
        top = re.search(r"^param\((.*?)^\)", t, re.DOTALL | re.MULTILINE)   # 스크립트 매개변수(함수 내부 param 은 들여쓰기)
        assert not (top and re.search(r"\[(string|securestring)\]\$\w*Password\b", top.group(1), re.IGNORECASE)), \
            f"{p}: 비밀번호 매개변수 금지(화면 입력 또는 -PasswordsFromEnv 만)"
        assert not re.search(r"SetEnvironmentVariable\([^)]*'(Machine|User)'", t), f"{p}: 머신·사용자 환경변수 쓰기 금지"
        assert not re.search(r"Write-(Host|Output|EslStep|Step)[^\n]*\$(url|DbUrl|dbUrl|existingUrl|appPw|adminPw)\b", t), p
    common = _text(DEPLOY / "install-common.ps1")
    assert "Read-Host -AsSecureString" in common
    for name in ("ESL_INSTALL_PG_ADMIN_PASSWORD", "ESL_INSTALL_DB_PASSWORD", "ESL_INSTALL_SERVICE_PASSWORD"):
        assert name in common
    assert common.count("$env:PGPASSWORD = $null") >= 3       # 쓰고 나면 지운다
    assert "SET log_statement = 'none'" in common              # 역할 생성 SQL 이 서버 로그에 남지 않게
    assert "secrets" in common and "/inheritance:r" in common  # 런타임 DB 파일은 현재 사용자·SYSTEM만
    for p in ("setup.ps1", "install.ps1"):
        t = _text(DEPLOY / p)
        assert "-PasswordsFromEnv:$PasswordsFromEnv" in t
        assert "Remove-Variable -Name url" in t


def test_task_scheduler_contract():
    common = _text(DEPLOY / "install-common.ps1")
    assert "$EslTaskNames = @('ESL-Backend', 'ESL-Worker')" in common
    assert "-ExecutionTimeLimit (New-TimeSpan -Seconds 0)" in common
    assert "-RestartCount 999" in common and "-MultipleInstances IgnoreNew" in common
    assert "-LogonType Interactive -RunLevel Limited" in common   # Interactive: 관리자 권한 불필요
    assert "New-ScheduledTaskTrigger -AtStartup" in common        # Background(Service, 세션 0)
    assert "--runtime" in common and "esl_service.py" in common
    un = _text(DEPLOY / "uninstall-tasks.ps1")
    assert "'ESL-Backend', 'ESL-Worker'" in un and "Unregister-ScheduledTask" in un
    assert "QUEUED','RUNNING'" in common.replace(" ", "")


def test_caddy_snippet():
    t = (DEPLOY / "caddy" / "esl.caddy").read_text(encoding="utf-8")
    assert "redir /esl /esl/ 308" in t
    assert re.search(r"handle /esl/api/\* \{\s*reverse_proxy 127\.0\.0\.1:\{\$ESL_PORT:8110\}\s*\}", t)
    assert re.search(r"handle /esl/\* \{\s*root \* \{\$ESL_FRONTEND_ROOT\}\s*uri strip_prefix /esl\s*try_files \{path\} /index\.html\s*file_server", t)
    assert t.index("/esl/api/*") < t.index("handle /esl/*")      # API 가 먼저
    vite = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert 'base: "/esl/"' in vite


def test_deploy_example_json():
    d = json.loads((DEPLOY / "deploy.example.json").read_text(encoding="utf-8"))
    for k in ("install_root", "dashboard_root", "python_exe", "pg_bin", "pg_host", "pg_port", "db_name", "db_role", "config_path",
              "service_user", "run_mode", "caddy_frontend_root", "esl_root", "input_roots", "spdm_roots"):
        assert k in d, k
    assert "backend_serves_frontend" not in d          # 프런트 정적 서빙은 설정 server.frontend_root 가 유일한 출처
    assert d["db_name"] == "esl" and d["db_role"] == "esl_app" and d["run_mode"] in ("Interactive", "Background")
    assert isinstance(d["input_roots"], list) and isinstance(d["spdm_roots"], list)
    for k in ("altair_root", "original_app_root", "resources"):
        assert k not in d
    assert not any("password" in k.lower() for k in d)


def _lock(p: Path) -> dict[str, str]:
    out = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip() and not ln.startswith("#"):
            name, ver = ln.split("==")
            out[name.lower().replace("_", "-")] = ver.strip()
    return out


def test_requirements_lock():
    lock = _lock(DEPLOY / "requirements.lock")
    assert all(re.fullmatch(r"\d+(\.\d+)*", v) for v in lock.values())
    for need in ("fastapi", "uvicorn", "sqlalchemy", "psycopg", "psycopg-binary", "alembic", "httpx", "pydantic", "pyyaml",
                 "numpy", "scipy", "pypardiso", "mkl", "intel-openmp", "tbb", "pyamg", "psutil", "colorama", "tzdata"):
        assert need in lock, need
    assert "scikit-sparse" not in lock and "pytest" not in lock and "esl" not in lock
    plat = (ROOT / "requirements-platform.txt").read_text(encoding="utf-8")
    for ln in plat.splitlines():
        m = re.match(r"^([A-Za-z][\w\-]*)(\[\w+\])?", ln.strip())
        if m and m.group(1).lower() != "pytest":
            assert m.group(1).lower().replace("_", "-") in lock, ln


@pytest.mark.skipif(not PHYSICSAI_LOCK.is_file(), reason="physicsai-platform 기준 저장소 없음")
def test_lock_matches_physicsai_versions():
    """같은 서버·같은 Python — 겹치는 패키지는 physicsai 와 같은 버전."""
    mine, ref = _lock(DEPLOY / "requirements.lock"), _lock(PHYSICSAI_LOCK)
    diff = {k: (mine[k], ref[k]) for k in mine.keys() & ref.keys() if mine[k] != ref[k]}
    assert diff == {}


def test_prod_example_config():
    d = yaml.safe_load((ROOT / "config" / "esl_platform.prod.example.yaml").read_text(encoding="utf-8"))
    dev = yaml.safe_load((ROOT / "config" / "esl_platform.example.yaml").read_text(encoding="utf-8"))
    assert d["profile"] == "prod" and d["auth"]["mode"] == "dashboard" and "dev_static_principal" not in d["auth"]
    assert set(d) == set(dev)                                       # 같은 스키마(최상위 키)
    assert d["server"] == {"host": "127.0.0.1", "port": 8110, "base_path": "/esl", "frontend_root": None}   # setup.ps1 이 채움
    assert d["core"] == {"config_path": "esl.yaml"} and d["library"] == {"config_path": "library.yaml"}
    assert d["database"]["url_env"] == "ESL_DATABASE_URL"
    for k in ("altair", "resources", "commands"):
        assert k not in d


def test_client_update_bat_untouched_and_separate():
    root_bat = (ROOT / "update.bat").read_text(encoding="ascii")
    assert "scripts\\windows\\update.ps1" in root_bat           # 루트 update.bat = 사용자 PC TCL 배포
    srv = (DEPLOY / "update.bat").read_text(encoding="ascii")
    assert "update.ps1" in srv and "scripts\\windows" not in srv
    for p in ("update.ps1", "update-repo.ps1", "setup.ps1"):
        assert "사용자 PC" in _text(DEPLOY / p), p                # 두 용도를 구분하는 안내


def test_readme_deploy_section():
    t = (ROOT / "README.md").read_text(encoding="utf-8")
    for s in ("deploy\\setup.ps1", "deploy\\update-repo.ps1", "deploy\\install.ps1", "deploy\\update.bat", "esl.caddy",
              "SIMDASH_ESL_ENABLED", "VITE_ESL_TARGET", "server.frontend_root", "start-demo.bat", "esl_platform.check", "사용자 PC"):
        assert s in t, s
    assert "backend_serves_frontend" not in t


def test_deploy_python_no_bytecode_and_no_secrets():
    for p in PY:
        t = p.read_text(encoding="utf-8")
        assert "dont_write_bytecode = True" in t or p.name.startswith("demo_") and p.name != "demo_setup.py", p
        assert not re.search(r"(password|passwd)\s*=\s*['\"][^'\"]+['\"]", t, re.IGNORECASE), p
    assert not list(DEPLOY.rglob("__pycache__"))


def test_docs_exist():
    admin = (ROOT / "docs" / "manual" / "admin.md").read_text(encoding="utf-8")
    for s in ("## 2. 설치", "## 3. 업데이트", "## 4. 설정 파일", "## 10. 환경 점검", "## 13. 문제 해결", "## 14. 시연 모드"):
        assert s in admin, s
    # 접속 연결: physicsai 와 같은 순서 — Vite 프록시 + 백엔드 정적 서빙이 기본, Caddy 는 대안
    a, b = admin.index("#### 2.6.1 대시보드 Vite 프록시 + 백엔드 정적 서빙(기본)"), admin.index("#### 2.6.2 Caddy(대안)")
    assert a < b
    for s in ("VITE_ESL_TARGET=http://127.0.0.1:8110", "SIMDASH_ESL_ENABLED=true", "http://<대시보드 주소>/esl/",
              "http://127.0.0.1:8110/esl/api/health", "server.frontend_root", "dashboard.env"):
        assert s in admin[a:b], s
    e2e = (ROOT / "docs" / "e2e-checklist.md").read_text(encoding="utf-8")
    assert "VITE_ESL_TARGET" in e2e and "server.frontend_root" in e2e
    for s in ("①", "②", "③", "④", "⑤", "⑥", "라이브러리", "보고서"):
        assert s in e2e, s


def test_alembic_ini_ascii():
    # Windows alembic 은 ini 를 로캘 코덱(cp949)으로 읽는다 — 비ASCII 가 있으면 migrate 가 UnicodeDecodeError(#7)
    raw = (ROOT / "alembic.ini").read_bytes()
    assert raw.isascii(), "alembic.ini 는 ASCII 전용"
