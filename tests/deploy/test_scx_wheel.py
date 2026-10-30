"""V-SR-1 simdash_adapters wheel·lock(계약 esl_scx_relay.md SR-D-2·§13): 동봉 wheel 정규화 sha256 = lock, lock 커밋 = a363a89…,
import·ScxHpcGateway 존재, 손상 wheel → 대조 실패(사유 SCX_ADAPTER_WHEEL_MISMATCH — 설치 함수는 throw 없이 SCX 만 비활성),
paicad_wheel.py 일반화(console_script null·check --module), 설치·묶음 스크립트 연결(정적)."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import paicad_wheel as pw
import pytest
from conftest import DEPLOY, ROOT

LOCK = DEPLOY / "simdash_adapters.lock"
HELPER = DEPLOY / "paicad_wheel.py"
COMMIT = "a363a89e8f93d3acfe90a9601318bf4f6cade0a7"


def _lock() -> dict:
    return pw.read_lock(LOCK)


def _wheel() -> Path:
    return DEPLOY / "wheels" / _lock()["wheel"]


def _text(p: Path) -> str:
    return p.read_bytes().decode("utf-8-sig")


def _fn(text: str, name: str) -> str:
    i = text.index(f"function {name} {{")
    j = text.index("\nfunction ", i + 10)
    return text[i:j]


def test_lock_format_and_pin():
    lk = _lock()
    assert lk["commit"] == COMMIT and lk["branch"] == "release/v0.2.14" and lk["source"] == "wgcha/physicsai-platform"
    assert lk["subdir"] == "packages/simdash_adapters" and lk["wheel"] == "simdash_adapters-0.1.0-py3-none-any.whl"
    assert lk["console_script"] is None and lk["runtime_requires"] == [] and lk["build_requires"] == ["setuptools==80.9.0"]
    assert pw.package_name(lk) == "simdash_adapters" and pw.code_prefix(lk) == "SCX_ADAPTER"
    assert not re.search(r"[A-Za-z]:[\\/]|/home/|password|secret", LOCK.read_text(encoding="utf-8"), re.IGNORECASE)


@pytest.mark.parametrize("bad", [{"console_script": "a b"}, {"wheel": "paicad-0.1.0-py3-none-any.whl"},
                                 {"subdir": "packages/Bad-Name"}, {"commit": "abc"}])
def test_read_lock_rejects_bad_fields(tmp_path, bad):
    d = json.loads(LOCK.read_text(encoding="utf-8"))
    d.update(bad)
    p = tmp_path / "simdash_adapters.lock"
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(pw.LockError):
        pw.read_lock(p)


def test_vendored_wheel_matches_lock_and_imports(tmp_path):
    data = _wheel().read_bytes()
    assert hashlib.sha256(data).hexdigest() == _lock()["sha256"] and pw.normalize_bytes(data) == data
    v = pw.verify_bytes(data, _lock())
    assert v["ok"], v["problems"]
    names = zipfile.ZipFile(_wheel()).namelist()
    assert "simdash_adapters/hpc/scx.py" in names and "simdash_adapters/hpc/scx_client.py" in names
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import simdash_adapters, simdash_adapters.hpc as h; "
            "print(simdash_adapters.__version__, hasattr(h, 'ScxHpcGateway'), hasattr(h, 'ScxRadiossRequest'))")
    r = subprocess.run([sys.executable, "-I", "-c", code, str(_wheel())], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.split() == ["0.1.0", "True", "True"], r.stderr
    rc = subprocess.run([sys.executable, "-I", str(HELPER), "verify", "--lock", str(LOCK), "--wheel", str(_wheel())],
                        capture_output=True, text=True, timeout=60)
    assert rc.returncode == 0 and json.loads(rc.stdout)["ok"]


def test_damaged_wheel_mismatch_and_check_module(tmp_path):
    bad = tmp_path / _lock()["wheel"]
    with zipfile.ZipFile(_wheel()) as src, zipfile.ZipFile(bad, "w") as dst:
        for n in src.namelist():
            b = src.read(n)
            dst.writestr(n, b + b"\n# tampered\n" if n == "simdash_adapters/hpc/scx.py" else b)
    r = pw.check_wheel(_lock(), str(bad))
    assert not r["ok"] and any(p.startswith("SCX_ADAPTER_WHEEL_MISMATCH") and "sha256" in p for p in r["problems"])
    assert pw.check_wheel(_lock(), str(tmp_path / "none.whl"))["problems"][0].startswith("SCX_ADAPTER_WHEEL_NOT_FOUND")
    # check --module(설치 venv 의 Python, -I): 이 시험 Python 에는 설치돼 있지 않을 수 있음 → 결과 형식·사유 코드만
    rc = subprocess.run([sys.executable, "-I", str(HELPER), "check", "--lock", str(LOCK), "--module", "simdash_adapters.hpc",
                         "--wheel", str(bad)], capture_output=True, text=True, timeout=60)
    res = json.loads(rc.stdout)
    assert rc.returncode == 1 and res["module"] == "simdash_adapters.hpc" and res["wheel"]["ok"] is False
    assert all(p.split(":")[0].startswith("SCX_ADAPTER_") for p in res["problems"])


def test_check_module_ok_with_installed(tmp_path):
    """pip 설치를 흉내: wheel 을 풀어 둔 폴더를 그 Python 의 경로에(-I 를 쓰지 않는 하위 Python 대신 .pth 없는 venv 흉내 없이)."""
    site = tmp_path / "site"
    zipfile.ZipFile(_wheel()).extractall(site)
    stub = tmp_path / "py"
    stub.write_text(f"#!/bin/sh\nPYTHONPATH={site} exec {sys.executable} \"$@\"\n", encoding="utf-8")
    stub.chmod(0o755)
    if sys.platform.startswith("win"):
        pytest.skip("POSIX 셸 대역")
    res = pw.check_module(_lock(), "simdash_adapters.hpc", python=str(stub))
    assert res["problems"] and res["problems"][0].startswith("SCX_ADAPTER_MISSING")   # -I 는 PYTHONPATH 무시(격리 확인)
    pkg = site / "simdash_adapters"
    assert (pkg / "hpc" / "scx.py").is_file()


def test_install_function_never_throws_and_is_wired():
    t = _text(DEPLOY / "install-common.ps1")
    f = _fn(t, "Install-EslScxAdapters")
    assert "} catch {" in f and "return [pscustomobject]$res" in f and "SCX 기능 비활성" in f
    for k in ("'verify', '--lock', $ScxLock, '--wheel', $whl", "'--no-index', '--no-deps', '--force-reinstall', $whl",
              "check --lock $ScxLock --module 'simdash_adapters.hpc'", "Join-Path $PSScriptRoot 'wheels'"):
        assert k in f, k
    assert f.index("$vend = Join-Path $VendoredWheels $lock.wheel") < f.index("(Join-Path $Wheels $lock.wheel)")
    assert not re.search(r"[A-Za-z]:\\[A-Za-z]", f) and "RunAs" not in f and "Machine" not in f
    items = re.search(r"\$EslAppItems = @\(([^)]*)\)", t).group(1)
    assert "'resources/scx_messages.json'" in items
    for p in ("install.ps1", "setup.ps1", "update-repo.ps1"):
        assert "Install-EslScxAdapters -VenvPy $venvPy -ScxLock" in _text(DEPLOY / p), p
    sh = _text(DEPLOY / "collect-offline.sh")
    ps = _text(DEPLOY / "collect-offline.ps1")
    assert "collect --lock deploy/simdash_adapters.lock --out-dir '$OUTDIR/wheels' --wheel '$SCX_VENDORED'" in sh
    assert "'deploy/simdash_adapters.lock'" in ps and "'resources\\scx_messages.json'" in ps
    assert "resources/scx_messages.json" in sh


def test_test_all_uses_vendored_wheel():
    t = (ROOT / "scripts" / "test-all").read_text(encoding="utf-8")
    assert "deploy/simdash_adapters.lock" in t and "paicad_wheel.py\" verify" in t and 'PYTHONPATH="$SCX_WHEEL:' in t
