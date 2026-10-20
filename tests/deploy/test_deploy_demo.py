"""시연 모드(deploy/demo): 합성 Case 입력·설정 생성(init), 백엔드(프런트 직접 서빙)·워커 기동과 ①~⑥ 미리 실행(up), 종료(down).
시연 전용 PostgreSQL(db-up)은 Windows 포터블 initdb 용이라 여기서는 시험 클러스터의 빈 DB(ESL_DATABASE_URL)를 쓴다."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request

import yaml
from conftest import DEMO, free_port

SETUP = DEMO / "demo_setup.py"


def _run(*args: str, env: dict | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    e = {k: v for k, v in os.environ.items() if k not in ("ESL_DATABASE_URL", "ESL_PLATFORM_CONFIG", "PYTHONPATH")}
    e.update(env or {})
    return subprocess.run([sys.executable, str(SETUP), *args], capture_output=True, text=True, env=e, timeout=timeout)


def _get(url: str):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=10) as r:
        return r.status, r.headers.get("content-type", ""), r.read().decode("utf-8")


def test_init_creates_valid_demo(tmp_path, fake_frontend):
    root = tmp_path / "demo"
    r = _run("init", "--root", str(root), "--port", "8191", "--frontend", str(fake_frontend))
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = yaml.safe_load((root / "config" / "esl_platform.yaml").read_text(encoding="utf-8"))
    assert cfg["profile"] == "dev" and cfg["auth"]["mode"] == "dev_static" and cfg["server"]["host"] == "127.0.0.1"
    assert cfg["server"]["port"] == 8191 and cfg["storage"]["input_roots"] == [str(root / "inputs").replace("\\", "/")]
    core = yaml.safe_load((root / "config" / "esl.yaml").read_text(encoding="utf-8"))
    assert core["extract"]["disp_precision"] == "float64"
    d = root / "inputs" / "demo_drop"
    assert (d / "model_0000.rad").is_file()
    for n in ("done.json", "frames.csv", "model.csv", "final.csv", "history.csv", "strain_frames.csv", "disp.csv"):
        assert (d / "csv" / n).is_file(), n
    assert json.loads((d / "csv" / "done.json").read_text())["ok"] is True
    # 다시 실행: 입력·설정은 그대로(있으면 재사용), 다른 포트면 이전 설정은 _backup 으로 이동
    mtime = (d / "model_0000.rad").stat().st_mtime
    r = _run("init", "--root", str(root), "--port", "8192")
    assert r.returncode == 0 and (d / "model_0000.rad").stat().st_mtime == mtime
    assert list((root / "_backup").rglob("esl_platform.yaml"))
    assert _run("init", "--root", str(tmp_path / "bad dir")).returncode != 0


def test_up_prerun_and_down(tmp_path, fake_frontend, empty_db_url):
    root = tmp_path / "demo"
    port = free_port()
    assert _run("init", "--root", str(root), "--port", str(port), "--frontend", str(fake_frontend)).returncode == 0
    env = {"ESL_DATABASE_URL": empty_db_url}
    try:
        r = _run("up", "--root", str(root), env=env, timeout=900)
        assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
        assert json.loads(r.stdout.strip().splitlines()[-1]) == {"url": f"http://127.0.0.1:{port}/esl/", "already_running": False}
        st, ct, body = _get(f"http://127.0.0.1:{port}/esl/")
        assert st == 200 and "text/html" in ct and "ESL" in body                       # 백엔드가 프런트 직접 서빙
        assert _get(f"http://127.0.0.1:{port}/esl/cases/x")[2] == body
        st, _, h = _get(f"http://127.0.0.1:{port}/esl/api/health")
        assert json.loads(h)["status"] == "ok"
        cases = {c["folder_name"]: c for c in json.loads(_get(f"http://127.0.0.1:{port}/esl/api/cases?project_id=demo")[2])}
        assert set(cases) == {"demo_new", "demo_done"}
        api = f"http://127.0.0.1:{port}/esl/api/cases/"
        done = json.loads(_get(api + cases["demo_done"]["id"])[2])
        assert all(done["stage_status"][str(i)]["state"] == "done" for i in range(1, 7)), done["stage_status"]
        new = json.loads(_get(api + cases["demo_new"]["id"])[2])
        assert new["stage_status"]["1"]["state"] != "done"
        cdir = root / "esl_root" / "demo_done"
        assert json.loads((cdir / "05_val" / "validation.json").read_text(encoding="utf-8"))["verdict"] == "PASS"
        assert (cdir / "06_export" / "esl_cload.inc").is_file()
        # 다시 up → 이미 실행 중
        r2 = _run("up", "--root", str(root), env=env)
        assert r2.returncode == 0 and json.loads(r2.stdout.strip().splitlines()[-1])["already_running"] is True
    finally:
        d = _run("down", "--root", str(root))
    assert d.returncode == 0 and "백엔드 종료" in d.stdout
    procs = json.loads((root / "state" / "demo-procs.json").read_text())
    assert procs == {}
    logs = {p.name for p in (root / "logs").iterdir()}
    assert {"backend.log", "worker.log"} <= logs
