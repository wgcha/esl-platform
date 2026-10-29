"""V-BD-18 배포(계약 esl_bead_doe.md §6.4·D5): deploy/paicad.lock 형식·정규화 wheel sha256 대조, requirements.lock 의 bead_doe 절
(cadquery-ocp·gmsh — paicad 고정과 같음), 설치 스크립트(실패해도 기존 기능 유지·설정 단계 전 설치·하드코딩 경로 없음),
$EslAppItems·collect-offline 의 resources/doe_*.json, setup_config 의 bead_doe.paicad.exe 자동 감지(파일 있을 때만·기존 값 불변·
BOM/CRLF 유지·백업)·allowed_ext .step·.stp 1회 보충, paicad 설치 확인(check). 네트워크 빌드 대조는 ESL_TEST_NETWORK=1."""

from __future__ import annotations

import io
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import paicad_wheel as pw
import pytest
import setup_config as sc
import yaml
from conftest import DEPLOY, ROOT
from test_deploy_setup_config import _inputs, _run

LOCK = DEPLOY / "paicad.lock"
REQ = DEPLOY / "requirements.lock"
MARKER = "# ==== bead_doe"


def _text(p: Path) -> str:
    return p.read_bytes().decode("utf-8-sig")


def _lock_sections() -> tuple[dict[str, str], dict[str, str]]:
    core, opt, cur = {}, {}, None
    cur = core
    for ln in REQ.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s.startswith(MARKER):
            cur = opt
            continue
        if s and not s.startswith("#"):
            n, v = s.split("==")
            cur[n.lower().replace("_", "-")] = v
    return core, opt


# ------------------------------------------------------------------ paicad.lock · requirements.lock
def test_paicad_lock_format_and_pins():
    lock = pw.read_lock(LOCK)
    assert lock["version"] == "0.14.0" and lock["source"] == "wgcha/physicsai-platform"
    assert lock["branch"] == "release/v0.2.14" and re.fullmatch(r"[0-9a-f]{40}", lock["commit"])
    assert lock["wheel"] == "paicad-0.14.0-py3-none-any.whl" and re.fullmatch(r"[0-9a-f]{64}", lock["sha256"])
    assert lock["console_script"] == "paicad" and lock["build_requires"] == ["setuptools==80.9.0"]
    assert pw._vt(lock["version"]) >= (0, 14, 0)                       # 확정 1: ≥ 0.14.0
    core, opt = _lock_sections()
    ocp = [r for r in lock["runtime_requires"] if r.startswith("cadquery-ocp==")]
    assert ocp == [f"cadquery-ocp=={opt['cadquery-ocp']}"] == ["cadquery-ocp==7.8.1.1.post1"]   # paicad 고정과 같음
    assert "paicad" not in core and "paicad" not in opt                 # paicad 자신은 lock 파일(PyPI 미배포)
    # 파일에 경로·비밀값 없음
    t = LOCK.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]|/home/|password", t, re.IGNORECASE)


def test_requirements_lock_bead_doe_section():
    core, opt = _lock_sections()
    for need in ("cadquery-ocp", "vtk", "gmsh", "matplotlib"):
        assert need in opt and need not in core, need
    assert re.fullmatch(r"4\.\d+\.\d+", opt["gmsh"])                   # gmsh>=4.11,<5(paicad test extra 범위)
    assert not set(core) & set(opt)
    for k in ("numpy", "scipy"):                                        # paicad numpy<3·scipy<2 를 기본 고정이 만족
        assert int(core[k].split(".")[0]) == (2 if k == "numpy" else 1)
    # 설치 스크립트가 같은 표지로 나눈다
    assert f"$EslLockOptionalMarker = '{MARKER}'" in _text(DEPLOY / "install-common.ps1")


@pytest.mark.parametrize("bad", [{"commit": "abc"}, {"sha256": "x" * 64}, {"wheel": "paicad-0.13.0-py3-none-any.whl"},
                                 {"build_requires": ["setuptools>=68"]}, {"console_script": "pc"}, {"version": "0.14"}])
def test_read_lock_rejects_bad_fields(tmp_path, bad):
    d = json.loads(LOCK.read_text(encoding="utf-8"))
    d.update(bad)
    p = tmp_path / "paicad.lock"
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(pw.LockError):
        pw.read_lock(p)


# ------------------------------------------------------------------ 정규화·대조
def _fake_wheel(version="0.14.0", *, ts=(2026, 10, 26, 12, 0, 0), mode=0o100664, compress=zipfile.ZIP_DEFLATED,
                order=None, scripts=("paicad",), body=b"__version__ = '0.14.0'\n") -> bytes:
    di = f"paicad-{version}.dist-info"
    files = {"paicad/__init__.py": body, "paicad/cli.py": b"def main():\n    return 0\n",
             f"{di}/METADATA": f"Metadata-Version: 2.4\nName: paicad\nVersion: {version}\nRequires-Dist: cadquery-ocp==7.8.1.1.post1\n\nbody\n".encode(),
             f"{di}/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
             f"{di}/entry_points.txt": ("[console_scripts]\n" + "".join(f"{s} = paicad.cli:main\n" for s in scripts)).encode(),
             f"{di}/RECORD": b"paicad/__init__.py,,\n"}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in (order or list(files)):
            zi = zipfile.ZipInfo(n, date_time=ts)
            zi.compress_type = compress
            zi.external_attr = mode << 16
            z.writestr(zi, files[n])
    return out.getvalue()


def _lock_for(tmp_path: Path, data: bytes, **over) -> Path:
    d = json.loads(LOCK.read_text(encoding="utf-8"))
    d["sha256"] = pw.sha256_bytes(pw.normalize_bytes(data))
    d.update(over)
    p = tmp_path / "paicad.lock"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_normalize_is_independent_of_zip_metadata():
    a = _fake_wheel()
    names = list(zipfile.ZipFile(io.BytesIO(a)).namelist())
    b = _fake_wheel(ts=(2030, 1, 2, 3, 4, 6), mode=0o100755, compress=zipfile.ZIP_STORED, order=list(reversed(names)))
    assert a != b
    na, nb = pw.normalize_bytes(a), pw.normalize_bytes(b)
    assert na == nb and pw.normalize_bytes(na) == na                       # 같은 내용 → 같은 바이트, 멱등
    z = zipfile.ZipFile(io.BytesIO(na))
    assert z.namelist()[-1].endswith(".dist-info/RECORD") and z.namelist()[0].startswith("paicad/")
    assert all(i.compress_type == zipfile.ZIP_STORED and i.date_time == pw.ZIP_DATE for i in z.infolist())
    assert {n: z.read(n) for n in z.namelist()} == {n: zipfile.ZipFile(io.BytesIO(a)).read(n) for n in names}
    # 내용이 1바이트라도 다르면 다른 sha
    assert pw.normalize_bytes(_fake_wheel(body=b"__version__ = '0.14.1'\n")) != na


def test_verify_detects_version_sha_and_script(tmp_path):
    w = _fake_wheel()
    lk = pw.read_lock(_lock_for(tmp_path, w))
    assert pw.verify_bytes(w, lk)["ok"] is True
    r = pw.verify_bytes(_fake_wheel(body=b"x = 1\n"), lk)
    assert not r["ok"] and any("sha256" in p for p in r["problems"])
    r = pw.verify_bytes(_fake_wheel(version="0.13.0"), lk)
    assert any("버전 0.13.0" in p for p in r["problems"])
    r = pw.verify_bytes(_fake_wheel(scripts=("other",)), lk)
    assert any("실행 명령 paicad" in p for p in r["problems"])


def test_cli_collect_with_wheel_and_verify(tmp_path):
    w = _fake_wheel()
    src = tmp_path / "in" / "paicad-0.14.0-py3-none-any.whl"
    src.parent.mkdir()
    src.write_bytes(w)
    lock = _lock_for(tmp_path, w)
    out = tmp_path / "wheels"
    r = subprocess.run([sys.executable, "-I", str(DEPLOY / "paicad_wheel.py"), "collect", "--lock", str(lock), "--out-dir", str(out),
                        "--wheel", str(src)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)
    dst = out / "paicad-0.14.0-py3-none-any.whl"
    assert res["ok"] and res["how"] == "wheel" and Path(res["wheel"]) == dst
    assert pw.sha256_bytes(dst.read_bytes()) == json.loads(lock.read_text())["sha256"]   # 묶음 안 = 정규화본
    r = subprocess.run([sys.executable, "-I", str(DEPLOY / "paicad_wheel.py"), "verify", "--lock", str(lock), "--wheel", str(dst)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and json.loads(r.stdout)["ok"]
    # 불일치 → 종료 1, 파일 안 둠
    bad = tmp_path / "bad.whl"
    bad.write_bytes(_fake_wheel(body=b"y = 2\n"))
    out2 = tmp_path / "wheels2"
    r = subprocess.run([sys.executable, "-I", str(DEPLOY / "paicad_wheel.py"), "collect", "--lock", str(lock), "--out-dir", str(out2),
                        "--wheel", str(bad)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and not json.loads(r.stdout)["ok"] and not out2.exists()
    assert "sha256" in r.stderr


# ------------------------------------------------------------------ 설치 확인(check)
def _fake_exe(tmp_path: Path, payload: str, rc: int = 0) -> str:
    p = tmp_path / "Scripts" / "paicad"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"#!{sys.executable}\nimport sys\nif sys.argv[1:] != ['version', '--json']:\n    sys.exit(2)\n"
                 f"print({payload!r})\nsys.exit({rc})\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


@pytest.mark.skipif(os.name == "nt", reason="가짜 실행 파일은 shebang")
@pytest.mark.parametrize("payload,rc,ok,code", [
    ('{"paicad": "0.14.0", "ocp": "7.8.1", "numpy": "2.4.6"}', 0, True, None),
    ('{"paicad": "0.15.1", "ocp": "7.8.1"}', 0, True, None),
    ('{"paicad": "0.13.9", "ocp": "7.8.1"}', 0, False, "PAICAD_VERSION_LOW"),
    ('{"paicad": "0.14.0", "ocp": null}', 0, False, "PAICAD_OCP_MISSING"),
    ("oops", 3, False, "PAICAD_CHECK_FAILED"),
])
def test_check_installed_paicad(tmp_path, payload, rc, ok, code):
    exe = _fake_exe(tmp_path, payload, rc)
    r = pw.check(pw.read_lock(LOCK), exe)
    assert r["ok"] is ok
    if code:
        assert any(p.startswith(code) for p in r["problems"]), r
    if ok and r["paicad"] != "0.14.0":
        assert any("배포 고정 0.14.0" in w for w in r["warnings"])        # 고정과 다르면 경고만
    if r["gmsh"] is None:
        assert any(w.startswith("GMSH_UNAVAILABLE") for w in r["warnings"])   # gmsh 없음 = ③ 만, ok 판정 무관


def test_check_missing_exe():
    r = pw.check(pw.read_lock(LOCK), "/nonexistent/paicad.exe")
    assert not r["ok"] and r["problems"][0].startswith("PAICAD_NOT_FOUND")


# ------------------------------------------------------------------ 설치 스크립트(정적)
def _fn(text: str, name: str) -> str:
    i = text.index(f"function {name} {{")
    j = text.index("\nfunction ", i + 10)
    return text[i:j]


def test_install_common_bead_doe_function():
    t = _text(DEPLOY / "install-common.ps1")
    items = re.search(r"\$EslAppItems = @\(([^)]*)\)", t).group(1)
    assert "'resources/doe_messages.json'" in items and "'resources/doe_method_sources.json'" in items
    pk = _fn(t, "Install-EslPackages")
    assert "(Get-EslLockPackages -LockFile $LockFile).Core" in pk and "'-r'" not in pk   # 기본 의존성만(OCP·gmsh 실패가 기존 설치를 막지 않음)
    f = _fn(t, "Install-EslBeadDoe")
    assert "} catch {" in f and "return [pscustomobject]$res" in f
    assert "Write-Warning \"비드 DOE 비활성(다른 기능은 그대로)" in f
    for k in ("'verify'", "'check'" if "'check'" in f else "check --lock", "'--no-index', '--no-deps', '--force-reinstall'",
              ".BeadDoe", "'paicad.exe'", "--find-links"):
        assert k in f, k
    assert not re.search(r"[A-Za-z]:\\\\|[A-Za-z]:\\[A-Za-z]", f)           # 하드코딩 경로 없음
    assert "RunAs" not in f and "Machine" not in f                          # 관리자 권한·머신 환경변수 없음
    # setup_config 감지 결과 콘솔 1줄
    assert "Write-EslStep $Result.write.doe_autodetect.line" in t


@pytest.mark.parametrize("script,wheels", [("install.ps1", True), ("update.ps1", True), ("setup.ps1", False), ("update-repo.ps1", False)])
def test_scripts_install_bead_doe_before_config(script, wheels):
    t = _text(DEPLOY / script)
    i = t.index("Install-EslBeadDoe -VenvPy $venvPy")
    j = t.index("Invoke-EslSetupConfig -VenvPy $venvPy -Action write")
    assert i < j                                                            # paicad.exe 가 있어야 setup_config 가 감지
    call = t[i:t.index("\n", t.index("-PaicadLock", i))]
    assert "paicad.lock" in call
    if wheels:
        assert "-Wheels (Join-Path $pkg 'wheels')" in call
    else:
        nxt = t[i:i + 400]
        assert "paicad_wheels" in nxt and "physicsai_root" in nxt           # git 폴더: deploy.json 값(하드코딩 없음)
    assert t.index("Install-EslPackages -VenvPy $venvPy") < i


def test_collect_scripts_paicad_and_resources():
    ps = _text(DEPLOY / "collect-offline.ps1")
    sh = _text(DEPLOY / "collect-offline.sh")
    assert "'resources\\doe_messages.json', 'resources\\doe_method_sources.json'" in ps
    assert "resources/doe_messages.json resources/doe_method_sources.json" in sh
    assert "'paicad_wheel.py'), 'collect', '--lock', 'deploy/paicad.lock', '--out-dir', 'dist/bundle/wheels'" in ps
    assert "deploy/paicad_wheel.py collect --lock deploy/paicad.lock --out-dir '$OUTDIR/wheels'" in sh
    for k in ("[switch]$NoPaicad", "[string]$PhysicsaiRepo", "[string]$PaicadWheel"):
        assert k in ps, k
    for k in ("--no-paicad", "--physicsai-repo", "--paicad-wheel"):
        assert k in sh, k
    r = (DEPLOY / "RESOURCES.txt").read_text(encoding="utf-8")
    assert "paicad" in r and "gmsh" in r and "paicad.lock" in r


def test_collect_dry_run_prints_paicad_step(tmp_path, fake_frontend):
    out = tmp_path / "b" / "bundle"
    r = subprocess.run(["bash", str(DEPLOY / "collect-offline.sh"), "--dry-run", "--out", str(out), "--frontend-dist", str(fake_frontend),
                        "--physicsai-repo", "/x/physicsai"], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHON": sys.executable})
    assert r.returncode == 0, r.stderr
    line = [ln for ln in r.stdout.splitlines() if "paicad_wheel.py collect" in ln]
    assert len(line) == 1 and "--repo '/x/physicsai'" in line[0] and not out.exists()
    r = subprocess.run(["bash", str(DEPLOY / "collect-offline.sh"), "--dry-run", "--no-paicad", "--out", str(out), "--frontend-dist",
                        str(fake_frontend)], capture_output=True, text=True, timeout=60, env={**os.environ, "PYTHON": sys.executable})
    assert "paicad_wheel.py collect" not in r.stdout and "비드 DOE 는 비활성" in r.stdout


# ------------------------------------------------------------------ setup_config 자동 감지
def _old_cfg(tmp_path: Path, edit=None) -> tuple[dict, Path]:
    inp = _inputs(tmp_path)
    cfg = Path(_run("write", inp)["config_path"])
    text = cfg.read_text(encoding="utf-8")
    text = re.sub(r"(?ms)^bead_doe:.*?(?=^\S|\Z)", "", text)              # v0.8.0 이전 모양(bead_doe 절 없음)
    if edit:
        text = edit(text)
    cfg.write_text(text, encoding="utf-8")
    return inp, cfg


def _paicad_exe(inp: dict) -> str:
    p = Path(inp["runtime_dir"]) / "venv" / "Scripts" / "paicad.exe"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    return sc.fwd(str(p))


@pytest.fixture()
def doe_code(monkeypatch):
    """코드 스키마에 bead_doe 가 있는 상태(D2 백엔드 병합 후)를 흉내 — 설정 검증 결과는 보지 않는다."""
    monkeypatch.setattr(sc, "code_supports", lambda section, code_root: section == "bead_doe")


def test_doe_autodetect_skipped_when_code_lacks_bead_doe(tmp_path):
    if sc.code_supports("bead_doe", str(ROOT)):
        pytest.skip("코드에 bead_doe 가 이미 있음(D2 병합 후) — doe_code 시험이 대신 확인")
    inp, cfg = _old_cfg(tmp_path)
    _paicad_exe(inp)
    r = _run("write", inp)
    assert r["doe_autodetect"] == {"added": {}, "candidate": None, "supported": False, "hint": None}
    assert "bead_doe" not in yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert r["write"]["validation"]["ok"] is True                         # 코드보다 앞선 설정을 쓰지 않음


def test_doe_autodetect_adds_exe_and_enabled(tmp_path, doe_code):
    inp, cfg = _old_cfg(tmp_path)
    exe = _paicad_exe(inp)
    before = cfg.read_text(encoding="utf-8")
    r = _run("write", inp)
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert d["bead_doe"] == {"enabled": True, "paicad": {"exe": exe}}
    assert r["doe_autodetect"]["added"] == {"bead_doe.enabled": True, "bead_doe.paicad.exe": exe}
    line = r["write"]["doe_autodetect"]["line"]
    assert line.startswith("비드 DOE 자동 설정: bead_doe.enabled = true, bead_doe.paicad.exe = ") and "(백업 " in line
    bk = r["write"]["doe_autodetect"]["backup"]
    assert Path(bk).read_text(encoding="utf-8") == before
    assert sc.DOE_AUTODETECT_NOTE in cfg.read_text(encoding="utf-8")
    r2 = _run("write", inp)                                                # 다시 실행해도 그대로
    assert r2["doe_autodetect"]["added"] == {} and r2["write"]["doe_autodetect"]["line"] is None
    assert not r2["config_changed"] or "bead_doe" not in " ".join(r2["config_changed_keys"])


def test_doe_autodetect_no_exe_hint_only(tmp_path, doe_code):
    inp, cfg = _old_cfg(tmp_path)
    r = _run("write", inp)
    assert r["doe_autodetect"]["added"] == {} and r["doe_autodetect"]["hint"] == sc.DOE_HINT
    assert "bead_doe" not in yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert not [w for w in r["warnings"] if "DOE" in w]                     # 경고가 아니라 안내 1줄


@pytest.mark.parametrize("block,expect", [
    ('bead_doe:\n  enabled: true\n  paicad:\n    exe: "C:/Other/paicad.exe"\n', "keep"),
    ("bead_doe:\n  enabled: true\n  paicad:\n    exe: null\n    threads: 8\n", "fill"),
    ('bead_doe:\n  max_designs: 100\n  paicad:\n    threads: 8   # 사용자\n', "fill_enable"),
    ("bead_doe:\n  enabled: false\n", "disabled"),
    ("bead_doe:\n  enabled: true\n  paicad: {threads: 8}\n", "flow"),
])
def test_doe_autodetect_existing_values(tmp_path, doe_code, block, expect):
    inp, cfg = _old_cfg(tmp_path, edit=lambda t: t + block)
    exe = _paicad_exe(inp)
    r = _run("write", inp)
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))["bead_doe"]
    if expect == "keep":                                                   # 기존 값은 파일이 없어도 불변
        assert d["paicad"]["exe"] == "C:/Other/paicad.exe" and r["doe_autodetect"]["added"] == {}
    elif expect == "fill":
        assert d == {"enabled": True, "paicad": {"exe": exe, "threads": 8}}
        assert r["doe_autodetect"]["added"] == {"bead_doe.paicad.exe": exe}
    elif expect == "fill_enable":
        assert d == {"enabled": True, "max_designs": 100, "paicad": {"exe": exe, "threads": 8}}
        assert "# 사용자" in cfg.read_text(encoding="utf-8")
    elif expect == "disabled":                                             # 명시 false 불변 + 경고 1줄
        assert d["enabled"] is False and d["paicad"]["exe"] == exe
        assert [w for w in r["warnings"] if "bead_doe.enabled: false" in w]
    else:                                                                   # 흐름 표기 → 자동 보충 안 함, 직접 고치라는 안내
        assert d == {"enabled": True, "paicad": {"threads": 8}}
        assert any("자동으로 보충하지 못했습니다" in w for w in r["warnings"]) and r["write"]["doe_autodetect"]["line"] is None


def test_doe_autodetect_keeps_bom_crlf(tmp_path, doe_code):
    inp, cfg = _old_cfg(tmp_path)
    raw = cfg.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8")
    cfg.write_bytes(b"\xef\xbb\xbf" + raw)
    exe = _paicad_exe(inp)
    _run("write", inp)
    out = cfg.read_bytes()
    assert out.startswith(b"\xef\xbb\xbf") and out.count(b"\n") == out.count(b"\r\n")
    assert yaml.safe_load(out.decode("utf-8-sig"))["bead_doe"]["paicad"]["exe"] == exe


def test_allowed_ext_step_supplement_once(tmp_path, doe_code):
    def explicit(text):
        return re.sub(r"(?m)^  allowed_ext:.*$", "  allowed_ext: [.rad, .inc, .csv, .h3d, .sta, .str]   # 사용자 목록", text)
    inp, cfg = _old_cfg(tmp_path, edit=explicit)
    st = Path(inp["runtime_dir"]) / "state" / "ext_supplement.json"
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps({"0.8.0": [".sta", ".str"]}), encoding="utf-8")   # v0.8.0 설치에서 이미 보충
    r = _run("write", inp)
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert d["upload"]["allowed_ext"] == [".rad", ".inc", ".csv", ".h3d", ".sta", ".str", ".step", ".stp"]
    assert json.loads(st.read_text(encoding="utf-8")) == {"0.8.0": [".sta", ".str"], "0.9.0": [".step", ".stp"]}
    assert "# 사용자 목록" in cfg.read_text(encoding="utf-8") and ".step .stp 추가" in r["write"]["ext_supplement"]["line"]
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(', ".step", ".stp"]', "]"), encoding="utf-8")
    r2 = _run("write", inp)                                                  # 사용자가 뺀 뒤 → 다시 넣지 않음
    assert ".step" not in yaml.safe_load(cfg.read_text(encoding="utf-8"))["upload"]["allowed_ext"]
    assert r2["ext_supplement"]["added"] == []


def test_set_yaml_nested_new_section_and_insert():
    t = "a: 1\n"
    t2 = sc.set_yaml_nested(t, ("bead_doe", "paicad", "exe"), "C:/x/paicad.exe", "n")
    assert yaml.safe_load(t2) == {"a": 1, "bead_doe": {"paicad": {"exe": "C:/x/paicad.exe"}}}
    t3 = sc.set_yaml_nested("bead_doe:\n    enabled: true\nz: 2\n", ("bead_doe", "paicad", "exe"), "p")
    assert yaml.safe_load(t3) == {"bead_doe": {"enabled": True, "paicad": {"exe": "p"}}, "z": 2}


# ------------------------------------------------------------------ 네트워크: 실제 physicsai 커밋 빌드 = lock sha256
@pytest.mark.skipif(os.environ.get("ESL_TEST_NETWORK") != "1", reason="네트워크 시험(ESL_TEST_NETWORK=1)")
def test_build_from_github_matches_lock(tmp_path):
    r = subprocess.run([sys.executable, "-I", str(DEPLOY / "paicad_wheel.py"), "collect", "--lock", str(LOCK), "--out-dir",
                        str(tmp_path / "w"), "--work", str(tmp_path / "work")], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    res = json.loads(r.stdout)
    assert res["ok"] and res["version"] == "0.14.0" and res["sha256"] == pw.read_lock(LOCK)["sha256"]


def test_manuals_paicad_sections():
    admin = (ROOT / "docs" / "manual" / "admin.md").read_text(encoding="utf-8")
    assert "#### 2.7.1 비드 DOE 형상 엔진 paicad·OCP·gmsh(v0.9.0)" in admin
    for s in ("paicad.exe' version --json", "import gmsh", "paicad_wheels", "physicsai_root", "-NoPaicad", "PAICAD_OCP_MISSING"):
        assert s in admin, s
    chk = (ROOT / "docs" / "manual" / "bead_doe_check.md").read_text(encoding="utf-8")
    a, b, c = chk.index("## R-③"), chk.index("## R-②"), chk.index("## R-①")
    assert chk.index("## 0. 설치") < a < b < c                                 # 실기 순서 ③ → ② → ①
    assert "paicad.exe' version --json" in chk and "import gmsh; print(gmsh.__version__)" in chk
