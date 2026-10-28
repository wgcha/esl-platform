"""배포(deploy/) 시험 공용: 경로, pwsh, PostgreSQL(backend/tests/esl_test_support 의 pg_server 재사용), 빈 DB, 가짜 프런트 빌드."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
DEMO = DEPLOY / "demo"
for _p in (ROOT / "backend" / "tests", ROOT / "backend", ROOT / "worker", ROOT, DEPLOY, DEMO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.dont_write_bytecode = True   # deploy/ 아래 __pycache__ 를 만들지 않는다(정적 검사·묶음 대상)

from esl_test_support import pg_server, with_db  # noqa: F401  (fixture 재노출)

# pwsh 찾기: 환경변수 ESL_PWSH → PATH 의 pwsh. 없으면 None(해당 시험 skip)
PWSH = os.environ.get("ESL_PWSH") or shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh 없음")


def run_pwsh(script_text: str, tmp_path: Path, *, timeout: int = 180, env: dict | None = None) -> subprocess.CompletedProcess:
    """임시 .ps1 을 써서 pwsh -File 로 실행(BOM UTF-8)."""
    p = tmp_path / f"t_{uuid.uuid4().hex[:8]}.ps1"
    p.write_bytes(b"\xef\xbb\xbf" + ("$ErrorActionPreference = 'Stop'\n" + script_text).encode("utf-8"))
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(p)], capture_output=True, text=True,
                          timeout=timeout, env={**os.environ, **(env or {})})


@pytest.fixture()
def empty_db_url(pg_server):
    """migration 하지 않은 빈 DB(설치 스크립트·시연·migrate 시험용)."""
    from sqlalchemy import text

    name = f"esl_dep_{uuid.uuid4().hex[:10]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    yield with_db(pg_server["admin_url"], name)
    with pg_server["admin"].connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture()
def fake_frontend(tmp_path) -> Path:
    """빌드된 프런트 흉내(index.html + assets/)."""
    d = tmp_path / "fe_dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>ESL</title><div id=root></div>", encoding="utf-8")
    (d / "assets" / "app-abc123.js").write_text("console.log('esl')", encoding="utf-8")
    return d


def free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
