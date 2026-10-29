"""오프라인 묶음(deploy/collect-offline.sh): Linux 에서 구조 생성(휠은 목록만 — 네트워크 시험은 ESL_TEST_NETWORK=1),
묶음 안의 코드만으로 실행기·설정 계획·환경 점검이 동작하는지."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from conftest import DEPLOY, ROOT

SH = DEPLOY / "collect-offline.sh"


def _bundle(tmp_path: Path, fe: Path, *extra: str) -> tuple[subprocess.CompletedProcess, Path]:
    out = tmp_path / "b" / "bundle"
    r = subprocess.run(["bash", str(SH), "--out", str(out), "--frontend-dist", str(fe), *extra],
                       capture_output=True, text=True, timeout=600, env={**os.environ, "PYTHON": sys.executable})
    return r, out


def _version() -> str:
    return re.search(r'^version = "(.*)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE).group(1)


def test_dry_run_changes_nothing(tmp_path, fake_frontend):
    r, out = _bundle(tmp_path, fake_frontend, "--dry-run", "--no-download")
    assert r.returncode == 0, r.stderr
    assert "+ cp deploy/esl_service.py" in r.stdout and "python" in r.stdout.lower()
    assert not out.exists() and not (tmp_path / "b").exists()


def test_refuses_dangerous_out(tmp_path, fake_frontend):
    for bad in ("/", str(ROOT), str(ROOT / "deploy"), str(ROOT / "esl")):
        r = subprocess.run(["bash", str(SH), "--out", bad, "--no-download", "--frontend-dist", str(fake_frontend)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 2, bad


def test_bundle_structure_and_runs_from_bundle(tmp_path, fake_frontend):
    r, out = _bundle(tmp_path, fake_frontend, "--no-download")
    assert r.returncode == 0, r.stdout + r.stderr
    z = tmp_path / "b" / f"esl-offline-{_version()}.zip"
    assert z.is_file()
    names = zipfile.ZipFile(z).namelist()
    tops = {n.split("/")[0] for n in names}
    assert tops == {"wheels", "frontend", "app", "config", "deploy"}
    need = ["wheels/DOWNLOAD-LIST.txt", "frontend/index.html", "app/esl_service.py", "app/alembic.ini", "app/pyproject.toml",
            "app/esl/__init__.py", "app/backend/esl_platform/check.py", "app/worker/esl_worker/__main__.py",
            "app/migrations/env.py", "app/migrations/versions/0001_initial.py", "app/migrations/versions/0003_library_report.py",
            "config/esl_platform.prod.example.yaml", "config/esl_platform.example.yaml", "config/esl.example.yaml",
            "config/library.example.yaml", "config/ista6.yaml", "deploy/install.ps1", "deploy/install.bat", "deploy/update.bat",
            "deploy/install-common.ps1", "deploy/setup_config.py", "deploy/requirements.lock", "deploy/caddy/esl.caddy",
            "deploy/demo/start-demo.bat", "deploy/demo/demo_setup.py", "deploy/demo/demo_synth.py"]
    need += ["app/resources/opt_method_sources.json", "app/resources/tcl/esl_bead_post.tcl"]   # v0.7.2: 비드 최적화 자료
    need += ["app/resources/doe_messages.json", "app/resources/doe_method_sources.json",   # v0.9.0 비드 DOE(V-BD-18)
             "deploy/paicad.lock", "deploy/paicad_wheel.py"]
    need += ["app/VERSION", "app/CHANGELOG.md", "app/BUILD.json"]                  # 버전 표기(계약 esl_p3_ux.md §3)
    for n in need:
        assert n in names, n
    build = json.loads(zipfile.ZipFile(z).read("app/BUILD.json"))
    assert build["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip() and build["built_at"].endswith("Z")
    assert build["commit"] is None or len(build["commit"]) == 7
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    assert not any(".runtime" in n or "secrets" in n or n.startswith("app/tests") or "/tests/" in n for n in names)
    assert (out / "wheels" / "DOWNLOAD-LIST.txt").read_text() == (DEPLOY / "requirements.lock").read_text()

    # 묶음을 풀어 묶음 코드만으로: 설정 계획(bundle 모드) → 실행기 endpoint·check(--no-db)
    ex = tmp_path / "x"
    zipfile.ZipFile(z).extractall(ex)
    rt = tmp_path / "rt"
    (tmp_path / "inputs").mkdir()
    dj = ex / "deploy" / "deploy.json"
    dj.write_text(json.dumps({"install_root": str(rt), "esl_root": str(tmp_path / "esl_root"),
                              "input_roots": [str(tmp_path / "inputs")], "spdm_roots": []}), encoding="utf-8")
    inputs = {"mode": "bundle", "source_root": str(ex), "code_root": str(ex / "app"), "runtime_dir": str(rt), "stamp": "T",
              "deploy_path": str(dj), "deploy_defaults": {"config_path": str(rt / "config" / "esl_platform.yaml")},
              "deploy_explicit": {}}
    f = tmp_path / "in.json"
    f.write_text(json.dumps(inputs), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    r = subprocess.run([sys.executable, "-I", str(ex / "deploy" / "setup_config.py"), "write", "--inputs", str(f)],
                       capture_output=True, text=True, env=env, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)
    assert res["write"]["validation"]["ok"] is True, res["write"]["validation"]
    cfg = rt / "config" / "esl_platform.yaml"
    r = subprocess.run([sys.executable, "-I", str(ex / "app" / "esl_service.py"), "endpoint", "--config", str(cfg)],
                       capture_output=True, text=True, env=env, timeout=60, cwd=str(tmp_path))
    assert json.loads(r.stdout)["port"] == 8110
    r = subprocess.run([sys.executable, "-I", str(ex / "app" / "esl_service.py"), "check", "--config", str(cfg), "--no-db",
                        "--min-free-gb", "0", "--json"], capture_output=True, text=True, env=env, timeout=120, cwd=str(tmp_path))
    st = {i["key"]: i["status"] for i in json.loads(r.stdout)["items"]}
    assert st["config.valid"] == "OK" and st["storage.esl_root.write"] == "OK" and st["solver.backend"] == "OK", r.stdout


@pytest.mark.skipif(os.environ.get("ESL_TEST_NETWORK") != "1", reason="네트워크 시험(ESL_TEST_NETWORK=1)")
def test_windows_wheels_download_exactly_lock(tmp_path, fake_frontend):
    """requirements.lock 이 win_amd64·cp312 휠로 추가 패키지 없이 모두 내려받아지는지(pypardiso·MKL 포함, 약 260 MB)."""
    r, out = _bundle(tmp_path, fake_frontend)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    lock = {}
    for ln in (DEPLOY / "requirements.lock").read_text(encoding="utf-8").splitlines():
        if ln.strip() and not ln.startswith("#"):
            n, v = ln.split("==")
            lock[n.lower().replace("_", "-")] = v
    got = {}
    paicad = out / "wheels" / json.loads((DEPLOY / "paicad.lock").read_text(encoding="utf-8"))["wheel"]
    assert paicad.is_file()                                   # v0.9.0: lock 커밋 빌드·sha256 대조를 통과한 paicad wheel
    for w in (out / "wheels").glob("*.whl"):
        if w == paicad:
            continue
        n, v = w.name.split("-")[:2]
        got[n.lower().replace("_", "-")] = v
        assert w.name.endswith(("-none-any.whl", "-win_amd64.whl")), w.name
    assert got == lock
