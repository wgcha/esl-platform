"""v0.10.1 esl 단독 설치: paicad 정규화 wheel 저장소 동봉(deploy/wheels) — 파일 존재·sha256 = lock·정규화 멱등·.gitattributes binary,
paicad_wheel.py check --wheel(동봉 wheel 대조), Install-EslBeadDoe 설치 우선순위(동봉 → 묶음 wheels·paicad_wheels → physicsai_root,
동봉 불일치면 중단 — 정적 + pwsh 모의), collect-offline 이 동봉 wheel 을 빌드 없이 묶음에 넣음, $EslAppItems 에는 넣지 않음."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import paicad_wheel as pw
import pytest
from conftest import DEPLOY, PWSH, ROOT, needs_pwsh, run_pwsh

LOCK = DEPLOY / "paicad.lock"
WHEELS = DEPLOY / "wheels"
HELPER = DEPLOY / "paicad_wheel.py"


def _lock() -> dict:
    return pw.read_lock(LOCK)


def _vendored() -> Path:
    return WHEELS / _lock()["wheel"]


def _text(p: Path) -> str:
    return p.read_bytes().decode("utf-8-sig")


def _fn(text: str, name: str) -> str:
    i = text.index(f"function {name} {{")
    j = text.index("\nfunction ", i + 10)
    return text[i:j]


# ------------------------------------------------------------------ 동봉 wheel 자체
def test_vendored_wheel_present_and_matches_lock():
    lock = _lock()
    w = _vendored()
    assert w.is_file(), f"동봉 wheel 없음: {w}"
    assert sorted(p.name for p in WHEELS.iterdir()) == [lock["wheel"]]          # 옛 버전 wheel 이 남지 않음
    data = w.read_bytes()
    assert 100_000 < len(data) < 5_000_000                                      # 정규화(무압축) paicad wheel 크기 범위
    assert hashlib.sha256(data).hexdigest() == lock["sha256"]                    # 파일 그대로 = lock(정규화본으로 커밋)
    assert pw.normalize_bytes(data) == data                                      # 이미 정규화본(멱등)
    v = pw.verify_bytes(data, lock)
    assert v["ok"], v["problems"]
    assert v["version"] == lock["version"] and lock["console_script"] in v["console_scripts"]
    z = zipfile.ZipFile(w)
    assert all(i.compress_type == zipfile.ZIP_STORED and i.date_time == pw.ZIP_DATE for i in z.infolist())
    assert any(n.startswith("paicad/") for n in z.namelist())


def test_gitattributes_whl_binary():
    lines = [ln.split() for ln in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert ["*.whl", "binary"] in lines                                          # 줄 끝 변환·diff 없음 → sha256 유지


def test_vendored_wheel_not_ignored_by_git():
    if not (ROOT / ".git").exists() or shutil.which("git") is None:
        pytest.skip("git 저장소 아님")
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(_vendored())], capture_output=True)
    assert r.returncode == 1, "deploy/wheels 의 wheel 이 .gitignore 에 걸림"


# ------------------------------------------------------------------ check --wheel
def _cli(*args: str) -> tuple[int, dict]:
    r = subprocess.run([sys.executable, "-I", str(HELPER), *args], capture_output=True, text=True, timeout=60)
    return r.returncode, json.loads(r.stdout)


def test_check_wheel_only_vendored_ok():
    rc, res = _cli("check", "--lock", str(LOCK), "--wheel", str(_vendored()))
    assert rc == 0 and res["ok"] is True and res["problems"] == []
    assert res["wheel"] == {"path": str(_vendored()), "ok": True, "sha256": _lock()["sha256"]}
    assert res["paicad"] is None and res["gmsh"] is None                         # --wheel 만 = 파일 대조만(실행·gmsh 확인 없음)


def test_check_wheel_mismatch_and_missing(tmp_path):
    bad = tmp_path / _lock()["wheel"]
    data = _vendored().read_bytes()
    with zipfile.ZipFile(_vendored()) as src, zipfile.ZipFile(bad, "w") as dst:   # 내용 1개 바꾼 wheel
        for n in src.namelist():
            b = src.read(n)
            dst.writestr(n, b + b"\n# tampered\n" if n == "paicad/__init__.py" else b)
    assert data != bad.read_bytes()
    rc, res = _cli("check", "--lock", str(LOCK), "--wheel", str(bad))
    assert rc == 1 and not res["ok"] and res["wheel"]["ok"] is False
    assert any(p.startswith("PAICAD_WHEEL_MISMATCH") and "sha256" in p for p in res["problems"])
    rc, res = _cli("check", "--lock", str(LOCK), "--wheel", str(tmp_path / "none.whl"))
    assert rc == 1 and res["problems"][0].startswith("PAICAD_WHEEL_NOT_FOUND")
    rc, res = _cli("check", "--lock", str(LOCK))                                  # --exe·--wheel 둘 다 없음
    assert rc == 1 and not res["ok"]


def test_check_api_wheel_with_missing_exe():
    r = pw.check(_lock(), "/nonexistent/paicad.exe", wheel=str(_vendored()))
    assert r["wheel"]["ok"] is True and not r["ok"]
    assert [p[:16] for p in r["problems"]] == ["PAICAD_NOT_FOUND"]                # exe 판정은 그대로


# ------------------------------------------------------------------ 설치 우선순위(정적)
def test_install_bead_doe_priority_static():
    f = _fn(_text(DEPLOY / "install-common.ps1"), "Install-EslBeadDoe")
    assert "[string]$VendoredWheels = ''" in f
    assert "if (-not $VendoredWheels) { $VendoredWheels = Join-Path $PSScriptRoot 'wheels' }" in f
    a = f.index("$vend = Join-Path $VendoredWheels $lock.wheel")
    b = f.index("(Join-Path $Wheels $lock.wheel)")
    c = f.index("(Join-Path $PaicadWheels $lock.wheel)")
    d = f.index("if (-not $whl -and $PhysicsaiRepo)")
    v = f.index("'verify', '--lock', $PaicadLock, '--wheel', $whl")
    p = f.index("'--no-index', '--no-deps', '--force-reinstall', $whl")
    assert a < b < c < d < v < p                                                  # (a) 동봉 → (b) 묶음·paicad_wheels → (c) physicsai → 대조 → 설치
    # (b)(c)는 앞 단계에서 못 찾았을 때만 — 동봉이 불일치여도 다른 곳으로 넘어가지 않는다(verify 실패 = throw → DOE 만 비활성)
    assert "if (-not $whl -and $Wheels" in f and "if (-not $whl -and $PaicadWheels" in f
    assert "$res.Source = 'vendored'" in f and "git checkout -- deploy/wheels" in f
    assert f.index("} catch {") > p and "return [pscustomobject]$res" in f       # 실패해도 throw 밖으로 안 나감
    # OCP·gmsh 는 그대로 lock bead_doe 절
    assert ".BeadDoe" in f and f.index(".BeadDoe") < a


@pytest.mark.parametrize("script", ["setup.ps1", "update-repo.ps1"])
def test_git_folder_scripts_pass_vendored(script):
    t = _text(DEPLOY / script)
    i = t.index("Install-EslBeadDoe -VenvPy $venvPy")
    call = t[i:i + 600]
    assert "-VendoredWheels (Join-Path $repo 'deploy\\wheels')" in call


def test_app_items_exclude_wheels_and_bundle_includes():
    t = _text(DEPLOY / "install-common.ps1")
    items = re.search(r"\$EslAppItems = @\(([^)]*)\)", t).group(1)
    assert "wheels" not in items                                                  # 런타임 app 복사 대상 아님(venv 에 pip 설치)
    sh, ps = _text(DEPLOY / "collect-offline.sh"), _text(DEPLOY / "collect-offline.ps1")
    assert "cp -r deploy/. '$OUTDIR/deploy/'" in sh and "Copy-Item -Recurse -Force 'deploy\\*' 'dist\\bundle\\deploy\\'" in ps
    assert "--wheel '$VENDORED'" in sh
    assert "$pwArgs += @('--wheel', $vendored)" in ps and "Join-Path 'deploy\\wheels'" in ps


# ------------------------------------------------------------------ collect-offline: 동봉 wheel 그대로(빌드 없음)
def test_collect_dry_run_uses_vendored(tmp_path, fake_frontend):
    out = tmp_path / "b" / "bundle"
    env = {**os.environ, "PYTHON": sys.executable}
    r = subprocess.run(["bash", str(DEPLOY / "collect-offline.sh"), "--dry-run", "--no-download", "--out", str(out), "--frontend-dist",
                        str(fake_frontend)], capture_output=True, text=True, timeout=60, env=env)
    assert r.returncode == 0, r.stderr
    line = [ln for ln in r.stdout.splitlines() if "paicad_wheel.py collect" in ln]
    assert len(line) == 1 and f"--wheel 'deploy/wheels/{_lock()['wheel']}'" in line[0] and "--repo" not in line[0]
    assert "저장소 동봉" in r.stdout and not out.exists()


def test_collect_bundle_contains_vendored(tmp_path, fake_frontend):
    out = tmp_path / "b" / "bundle"
    r = subprocess.run(["bash", str(DEPLOY / "collect-offline.sh"), "--no-download", "--out", str(out), "--frontend-dist",
                        str(fake_frontend)], capture_output=True, text=True, timeout=600, env={**os.environ, "PYTHON": sys.executable})
    assert r.returncode == 0, r.stdout + r.stderr
    sha = _lock()["sha256"]
    for p in (out / "wheels" / _lock()["wheel"], out / "deploy" / "wheels" / _lock()["wheel"]):
        assert p.is_file(), p
        assert hashlib.sha256(p.read_bytes()).hexdigest() == sha


# ------------------------------------------------------------------ 설치 우선순위(pwsh 모의 — pip 은 기록만)
def _mock_body(lock: Path, venv_py: str, rec: Path, **kw: str) -> str:
    args = " ".join(f"-{k} '{v}'" for k, v in kw.items())
    return f"""
. '{DEPLOY / 'install-common.ps1'}'
function Invoke-EslPip {{ param([string]$Py, [string[]]$PipArgs, [string]$What) Add-Content -LiteralPath '{rec}' -Value ($PipArgs -join ' ') }}
$r = Install-EslBeadDoe -VenvPy '{venv_py}' -LockFile '{DEPLOY / 'requirements.lock'}' -PaicadLock '{lock}' {args} 3>$null
Write-Output ('JSON=' + ($r | ConvertTo-Json -Compress))
"""


@needs_pwsh
@pytest.mark.parametrize("case", ["vendored", "wheels", "paicad_wheels", "mismatch"])
def test_install_priority_pwsh_mock(tmp_path, case):
    lock = _lock()
    good = _vendored().read_bytes()
    vend, bw, pwd = tmp_path / "vend", tmp_path / "bundle_wheels", tmp_path / "pw"
    for d in (vend, bw, pwd):
        d.mkdir()
    if case in ("vendored", "mismatch"):
        (vend / lock["wheel"]).write_bytes(good if case == "vendored" else good[:-200] + b"\0" * 200)
    if case in ("wheels", "mismatch"):
        (bw / lock["wheel"]).write_bytes(good)
    (pwd / lock["wheel"]).write_bytes(good)
    rec = tmp_path / "pip.txt"
    kw = {"VendoredWheels": str(vend), "PaicadWheels": str(pwd)}
    if case in ("wheels", "mismatch"):
        kw["Wheels"] = str(bw)
    r = run_pwsh(_mock_body(LOCK, sys.executable, rec, **kw), tmp_path)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("JSON=")]
    assert line, r.stdout + r.stderr
    res = json.loads(line[-1][5:])
    pips = rec.read_text(encoding="utf-8").splitlines() if rec.exists() else []
    paicad_pip = [p for p in pips if "--force-reinstall" in p]
    assert res["Ok"] is False                                                     # 가짜 venv 라 paicad.exe 확인은 실패(설치 단계만 봄)
    if case == "mismatch":
        assert res["Source"] == "vendored" and paicad_pip == []                   # 묶음 wheels 가 있어도 넘어가지 않고 중단
        assert "paicad wheel 대조" in res["Reason"]
    else:
        assert res["Source"] == case
        src = {"vendored": vend, "wheels": bw, "paicad_wheels": pwd}[case]
        assert len(paicad_pip) == 1 and paicad_pip[0].endswith(str(src / lock["wheel"]))
