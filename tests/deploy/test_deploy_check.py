"""환경 점검 CLI `python -m esl_platform.check`: 경로 쓰기·DB·migration head·솔버 백엔드·pypardiso(Windows 규칙)·설정 검증 표."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from conftest import ROOT
from esl_platform import check

ALEMBIC_HEAD = "0010"


def _cfg(tmp_path: Path, **storage) -> Path:
    cfgd = tmp_path / "config"
    cfgd.mkdir(exist_ok=True)
    for n, src in (("esl.yaml", "esl.example.yaml"), ("library.yaml", "library.example.yaml"), ("ista6.yaml", "ista6.yaml")):
        shutil.copy(ROOT / "config" / src, cfgd / n)
    d = yaml.safe_load((ROOT / "config" / "esl_platform.prod.example.yaml").read_text(encoding="utf-8"))
    (tmp_path / "esl_root").mkdir(exist_ok=True)
    (tmp_path / "inputs").mkdir(exist_ok=True)
    d["storage"] = {"esl_root": str(tmp_path / "esl_root"), "input_roots": [str(tmp_path / "inputs")], "spdm_roots": [], **storage}
    p = cfgd / "esl_platform.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    return p


def _st(items) -> dict[str, str]:
    return {i.key: i.status for i in items}


def test_all_ok_with_migrated_db(tmp_path, empty_db_url):
    from alembic import command
    from alembic.config import Config

    ac = Config(str(ROOT / "alembic.ini"))
    ac.attributes["url"] = empty_db_url
    command.upgrade(ac, "head")
    cfg = _cfg(tmp_path)
    items = check.run_checks(str(cfg), environ={"ESL_DATABASE_URL": empty_db_url}, min_free_gb=0)
    st = _st(items)
    for k in ("config.valid", "config.auth", "config.library", "storage.esl_root.write", "storage.esl_root.free",
              "storage.input_roots", "storage.spdm_roots", "solver.backend", "db.connection", "db.migration_head"):
        assert st[k] == "OK", (k, [i for i in items if i.key == k])
    assert st["worker.heartbeat"] == "WARN"                   # 워커가 아직 없음
    assert next(i for i in items if i.key == "db.migration_head").detail.startswith(ALEMBIC_HEAD)
    db = next(i for i in items if i.key == "db.connection").detail
    assert "@127.0.0.1" in db and empty_db_url.split("@")[0].split("//")[1] not in db.replace("postgres@", "")
    assert not list((tmp_path / "esl_root").iterdir())        # 쓰기 시험 파일은 지운다
    assert check.migration_head() == ALEMBIC_HEAD


def test_h3d_extract_and_slots_rows(tmp_path, monkeypatch):
    """P3-UX §6: hw 실행 파일·추출 TCL 존재, worker.slots(작업별 메모리·코어)."""
    cfg = _cfg(tmp_path)
    items = check.run_checks(str(cfg), use_db=False, platform="linux")
    st = {i.key: i for i in items}
    assert st["altair.extract_tcl"].status == "OK" and st["altair.extract_tcl"].detail.endswith("esl_h3d_extract.tcl")
    assert st["altair.hw_exe_path"].status == "WARN" and "파일이 없습니다" in st["altair.hw_exe_path"].detail
    assert st["worker.slots"].status == "OK" and "64 GB" in st["worker.slots"].detail
    win = {i.key: i for i in check.run_checks(str(cfg), use_db=False, platform="win32")}
    assert win["altair.hw_exe_path"].status == "FAIL"
    hw = tmp_path / "Altair" / "hw.exe"
    hw.parent.mkdir()
    hw.write_bytes(b"")
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    d["altair"]["hw_exe_path"] = str(hw)
    cfg.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    ok = {i.key: i for i in check.run_checks(str(cfg), use_db=False, platform="win32")}
    assert ok["altair.hw_exe_path"].status == "OK"
    from esl_platform.core import config as cfgmod

    monkeypatch.setattr(cfgmod, "default_extract_tcl", lambda: str(tmp_path / "none.tcl"))
    miss = {i.key: i for i in check.run_checks(str(cfg), use_db=False, platform="linux")}
    assert miss["altair.extract_tcl"].status == "FAIL"


def test_upload_root_rows(tmp_path):
    """P3-UX: storage.upload_root 쓰기·여유 공간 행(없으면 WARN), 입력 루트 읽기에 자동 포함."""
    (tmp_path / "esl-input").mkdir()
    cfg = _cfg(tmp_path, upload_root=str(tmp_path / "esl-input"))
    d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    d["upload"]["min_free_gb"] = 0
    cfg.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    items = check.run_checks(str(cfg), environ={}, min_free_gb=0)
    st = _st(items)
    assert st["config.valid"] == "OK" and st["storage.upload_root.write"] == "OK"
    assert st["storage.upload_root.free"] == "OK" and st["storage.input_roots"] == "OK"
    assert str(tmp_path / "esl-input") in next(i for i in items if i.key == "storage.input_roots").detail
    assert not list((tmp_path / "esl-input").iterdir())
    st = _st(check.run_checks(str(_cfg(tmp_path)), environ={}, min_free_gb=0))
    assert st["storage.upload_root"] == "WARN"


def test_failures_reported(tmp_path, empty_db_url):
    cfg = _cfg(tmp_path, input_roots=[str(tmp_path / "missing_in")])
    shutil.rmtree(tmp_path / "esl_root")
    items = check.run_checks(str(cfg), environ={"ESL_DATABASE_URL": empty_db_url})
    st = _st(items)
    assert st["storage.esl_root.write"] == "FAIL" and st["storage.input_roots"] == "FAIL"
    assert st["db.connection"] == "OK" and st["db.migration_head"] == "FAIL"   # 빈 DB = migration 미적용
    items = check.run_checks(str(cfg), environ={})
    assert _st(items)["db.connection"] == "FAIL"                              # DB 접속 정보 없음
    bad = check.run_checks(str(cfg), environ={"ESL_DATABASE_URL": "postgresql+psycopg://x:Wr0ngPw@127.0.0.1:1/esl"})
    det = next(i for i in bad if i.key == "db.connection")
    assert det.status == "FAIL" and "Wr0ngPw" not in det.detail


def test_invalid_config(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.write_text(cfg.read_text(encoding="utf-8") + "unknown: 1\n", encoding="utf-8")
    items = check.run_checks(str(cfg), use_db=False)
    assert _st(items)["config.valid"] == "FAIL" and "unknown" in items[-1].detail
    assert _st(check.run_checks(None, use_db=False))["config.valid"] == "FAIL"


def test_solver_rules_windows(monkeypatch):
    """Windows: pypardiso(MKL)가 없거나 로드 실패면 FAIL, scikit-sparse 는 SKIP(Windows 제외). 다른 OS 는 WARN."""
    from esl_worker import core_adapter

    monkeypatch.setattr(core_adapter, "solver_backends", lambda cfg: {"solver_backend": "superlu",
                                                                      "solver_backends_available": ["superlu", "iterative"]})
    monkeypatch.setattr(check, "_dist_version", lambda n: None)
    win = {i.key: i for i in check.check_solver({"solver": {"backend": "auto"}}, "win32")}
    assert win["solver.pypardiso"].status == "FAIL" and win["solver.cholmod"].status == "SKIP"
    assert win["solver.backend"].status == "OK"
    lin = {i.key: i for i in check.check_solver({"solver": {"backend": "auto"}}, "linux")}
    assert lin["solver.pypardiso"].status == "WARN"
    monkeypatch.setattr(check, "_dist_version", lambda n: "0.4.7" if n == "pypardiso" else None)
    win = {i.key: i for i in check.check_solver({"solver": {"backend": "pardiso"}}, "win32")}
    assert win["solver.pypardiso"].status == "FAIL" and "MKL" in win["solver.pypardiso"].detail
    assert win["solver.backend"].status == "FAIL"             # 설정 pardiso 인데 사용 불가
    monkeypatch.setattr(core_adapter, "solver_backends", lambda cfg: {"solver_backend": "pardiso",
                                                                      "solver_backends_available": ["pardiso", "superlu", "iterative"]})
    win = {i.key: i for i in check.check_solver({"solver": {"backend": "auto"}}, "win32")}
    assert win["solver.pypardiso"].status == "OK" and win["solver.backend"].detail.startswith("설정 auto → pardiso")


def test_runtime_secret_and_cli(tmp_path, empty_db_url):
    rt = tmp_path / "rt"
    (rt / "secrets").mkdir(parents=True)
    (rt / "secrets" / "database_url").write_text(empty_db_url + "\n", encoding="utf-8")
    assert check.read_runtime_db_url(str(rt)) == empty_db_url
    cfg = _cfg(rt)
    assert check.resolve_config_path(None, str(rt), {}) == str(cfg)
    env = {k: v for k, v in os.environ.items() if k != "ESL_DATABASE_URL"}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "backend"), str(ROOT / "worker"), str(ROOT)])
    r = subprocess.run([sys.executable, "-m", "esl_platform.check", "--runtime", str(rt), "--json", "--min-free-gb", "0"],
                       capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=120)
    out = json.loads(r.stdout)
    st = {i["key"]: i["status"] for i in out["items"]}
    assert st["db.connection"] == "OK" and st["db.migration_head"] == "FAIL" and r.returncode == 1
    assert out["ok"] is False
    t = subprocess.run([sys.executable, "-m", "esl_platform.check", "--runtime", str(rt), "--no-db"],
                       capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=120)
    assert t.returncode == 0, t.stdout
    assert "항목" in t.stdout and "요약: OK" in t.stdout and "db.connection" in t.stdout
    assert subprocess.run([sys.executable, "-m", "esl_platform.check", "--nope"], env=env, capture_output=True).returncode == 2


@pytest.mark.parametrize("ver,status", [((3, 12, 13), "OK"), ((3, 13, 1), "WARN")])
def test_python_version_rule(monkeypatch, ver, status):
    monkeypatch.setattr(check.sys, "version_info", type("V", (), {"major": ver[0], "minor": ver[1], "micro": ver[2]})())
    assert check.check_python().status == status


def test_frontend_root_row(tmp_path, fake_frontend):
    """server.frontend_root(백엔드 정적 서빙): null = SKIP(Caddy 등 외부 서빙), 폴더·index.html 없음 = WARN, 있으면 OK."""
    cfg = _cfg(tmp_path)

    def row(value):
        d = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        d["server"]["frontend_root"] = value
        cfg.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        items = check.run_checks(str(cfg), use_db=False)
        assert _st(items)["config.valid"] == "OK", items
        return next(i for i in items if i.key == "server.frontend_root")

    assert row(None).status == "SKIP"
    r = row(str(tmp_path / "nofe"))
    assert r.status == "WARN" and "폴더가 없습니다" in r.detail
    (tmp_path / "empty_fe").mkdir()
    r = row(str(tmp_path / "empty_fe"))
    assert r.status == "WARN" and "index.html" in r.detail
    r = row(str(fake_frontend))
    assert r.status == "OK" and "/esl/" in r.detail and str(fake_frontend) in r.detail
    out: list[str] = []
    check.main(["--config", str(cfg), "--no-db"], out=out.append)
    assert "server.frontend_root" in "\n".join(out)
