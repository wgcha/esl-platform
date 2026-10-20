"""실행기 deploy/esl_service.py(작업 스케줄러 ESL-Backend·ESL-Worker 대상): 런타임 파일 해석, 환경 주입, 정적 서빙, migrate·backend·worker 실제 기동."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import esl_service as svc
import pytest
import yaml
from conftest import DEPLOY, ROOT, free_port

PY = sys.executable
LAUNCHER = DEPLOY / "esl_service.py"


def _runtime(tmp_path: Path, url: str = "", port: int = 8110, frontend_root: str | None = None) -> Path:
    """설치 런타임 흉내: config/esl_platform.yaml(+esl.yaml·library.yaml·ista6.yaml), secrets/database_url."""
    rt = tmp_path / "rt"
    cfgd = rt / "config"
    cfgd.mkdir(parents=True)
    d = yaml.safe_load((ROOT / "config" / "esl_platform.prod.example.yaml").read_text(encoding="utf-8"))
    (tmp_path / "esl_root").mkdir()
    (tmp_path / "inputs").mkdir()
    d["server"]["port"] = port
    d["server"]["frontend_root"] = frontend_root
    d["storage"] = {"esl_root": str(tmp_path / "esl_root"), "input_roots": [str(tmp_path / "inputs")], "spdm_roots": []}
    d["worker"].update({"heartbeat_interval_s": 0.5, "lease_ttl_s": 5, "claim_interval_s": 0.2})
    (cfgd / "esl_platform.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    shutil.copy(ROOT / "config" / "esl.example.yaml", cfgd / "esl.yaml")
    shutil.copy(ROOT / "config" / "library.example.yaml", cfgd / "library.yaml")
    shutil.copy(ROOT / "config" / "ista6.yaml", cfgd / "ista6.yaml")
    if url:
        (rt / "secrets").mkdir()
        (rt / "secrets" / "database_url").write_bytes(b"\xef\xbb\xbf" + url.encode("utf-8"))
    return rt


def test_app_root_repo_and_installed(tmp_path):
    assert svc.app_root(str(DEPLOY)) == str(ROOT)                    # 저장소: deploy/ 의 부모
    app = tmp_path / "app"
    (app / "backend" / "esl_platform").mkdir(parents=True)
    assert svc.app_root(str(app)) == str(app)                        # 설치본: <런타임>/app
    with pytest.raises(SystemExit):
        svc.app_root(str(tmp_path / "nowhere"))


def test_config_and_env_resolution(tmp_path):
    rt = _runtime(tmp_path, url="postgresql+psycopg://esl_app:p%40ss@127.0.0.1:5432/esl")
    cfg = svc.config_path(str(rt), None, {})
    assert cfg == str(rt / "config" / "esl_platform.yaml")
    assert svc.config_path(None, None, {"ESL_PLATFORM_CONFIG": "x.yaml"}) == os.path.abspath("x.yaml")
    with pytest.raises(SystemExit):
        svc.config_path(None, None, {})
    env: dict[str, str] = {"ESL_DATABASE_URL": "old"}
    svc.prepare_env(str(rt), cfg, env)
    assert env["ESL_DATABASE_URL"].endswith("@127.0.0.1:5432/esl")    # 런타임 파일이 우선(BOM 제거)
    assert env["ESL_PLATFORM_CONFIG"] == cfg and env["ESL_BIND_HOST"] == "127.0.0.1"
    # url_env 를 바꾼 설정은 그 이름으로
    t = Path(cfg).read_text(encoding="utf-8").replace("url_env: ESL_DATABASE_URL", "url_env: MY_DB_URL")
    Path(cfg).write_text(t, encoding="utf-8")
    env2: dict[str, str] = {}
    svc.prepare_env(str(rt), cfg, env2)
    assert "MY_DB_URL" in env2 and "ESL_DATABASE_URL" not in env2


def test_server_settings_block_and_flow(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("server: {host: 127.0.0.1, port: 8222, base_path: /esl/}\n", encoding="utf-8")
    assert svc.server_settings(str(p)) == {"host": "127.0.0.1", "port": 8222, "base_path": "/esl"}
    p.write_text("server:\n  port: 8333\n", encoding="utf-8")
    assert svc.server_settings(str(p))["port"] == 8333
    p.write_text(": broken", encoding="utf-8")
    assert svc.server_settings(str(p))["port"] == 8110


def test_endpoint_command(tmp_path):
    rt = _runtime(tmp_path, port=8123)
    r = subprocess.run([PY, str(LAUNCHER), "endpoint", "--runtime", str(rt)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"host": "127.0.0.1", "port": 8123, "base_path": "/esl",
                                    "health": "http://127.0.0.1:8123/esl/api/health"}
    r = subprocess.run([PY, str(LAUNCHER), "worker", "--bogus"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2


def _wait_health(port: int, proc: subprocess.Popen, timeout: float = 60) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise AssertionError(f"프로세스 종료: {proc.returncode}")
        try:
            with opener.open(f"http://127.0.0.1:{port}/esl/api/health", timeout=2) as r:
                if json.loads(r.read())["status"] == "ok":
                    return
        except OSError:
            time.sleep(0.3)
    raise AssertionError("health 시간 초과")


def _get(url: str) -> tuple[int, dict[str, str], str]:
    import urllib.error

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: ANN002, ANN003
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    try:
        with opener.open(url, timeout=10) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8")


def _post(url: str, body: dict, headers: dict[str, str]) -> tuple[int, str]:
    import urllib.error

    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def test_uvicorn_options_no_proxy_headers():
    o = svc.uvicorn_options({"host": "127.0.0.1", "port": 8110, "base_path": "/esl"})
    assert o["proxy_headers"] is False and "forwarded_allow_ips" not in o and o["port"] == 8110


def test_migrate_backend_worker_check_with_runtime(tmp_path, empty_db_url, fake_frontend):
    """작업 스케줄러와 같은 인자(--runtime, --frontend 없음)로: migrate → backend(로그 파일·health·설정 server.frontend_root 정적 서빙)
    → worker(heartbeat) → check 표."""
    port = free_port()
    rt = _runtime(tmp_path, url=empty_db_url, port=port, frontend_root=str(fake_frontend))
    env = {k: v for k, v in os.environ.items() if k not in ("ESL_DATABASE_URL", "ESL_PLATFORM_CONFIG")}
    r = subprocess.run([PY, str(LAUNCHER), "migrate", "--runtime", str(rt)], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr + r.stdout
    procs = []
    try:
        be = subprocess.Popen([PY, str(LAUNCHER), "backend", "--runtime", str(rt)], cwd=rt, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(be)
        _wait_health(port, be)
        # 대시보드 Vite 프록시가 넘기는 그대로(/esl 경로 유지): 화면은 백엔드가 서빙, API 404 는 JSON
        st_, h, body = _get(f"http://127.0.0.1:{port}/esl/cases/abc")
        assert st_ == 200 and "<title>ESL</title>" in body and h["cache-control"] == "no-cache"
        st_, h, _ = _get(f"http://127.0.0.1:{port}/esl/assets/app-abc123.js")
        assert st_ == 200 and "max-age=31536000" in h["cache-control"]
        st_, h, _ = _get(f"http://127.0.0.1:{port}/esl")
        assert st_ == 308 and h["location"] == "/esl/"
        st_, h, body = _get(f"http://127.0.0.1:{port}/esl/api/nope")
        assert st_ == 404 and json.loads(body)["detail"]["code"] == "NOT_FOUND"
        assert _get(f"http://127.0.0.1:{port}/")[0] == 404                   # 운영은 '/'를 가로채지 않음(대시보드 몫)
        # 연결 코드 잠금: 루프백 peer + X-Forwarded-For 회전(trusted_proxies 비어 있음) → 서버 전체 30회 키(XFF 위조 무시)
        st = [_post(f"http://127.0.0.1:{port}/esl/api/client-tokens/exchange", {"code": "000000", "device_name": "pc"},
                    {"X-Forwarded-For": f"10.0.0.{i}"})[0] for i in range(31)]
        assert st[:29] == [401] * 29 and st[29:] == [429, 429], st
        wk = subprocess.Popen([PY, str(LAUNCHER), "worker", "--runtime", str(rt)], cwd=rt, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(wk)
        time.sleep(2.5)
        assert wk.poll() is None
        r = subprocess.run([PY, str(LAUNCHER), "check", "--runtime", str(rt), "--json"], capture_output=True, text=True,
                           env=env, timeout=120)
        out = json.loads(r.stdout)
        st = {i["key"]: i["status"] for i in out["items"]}
        assert st["config.valid"] == "OK" and st["db.connection"] == "OK" and st["db.migration_head"] == "OK", out
        assert st["worker.heartbeat"] == "OK" and st["storage.esl_root.write"] == "OK"
        assert st["server.frontend_root"] == "OK"
        assert empty_db_url.rsplit("@", 1)[0] not in r.stdout                 # 사용자:비밀번호 부분 비노출
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()
    blog = (rt / "logs" / "backend.log").read_text(encoding="utf-8")
    assert "백엔드 시작" in blog and "Uvicorn running" in blog and "프런트 정적 서빙(server.frontend_root)" in blog
    assert "워커 시작" in (rt / "logs" / "worker.log").read_text(encoding="utf-8")
    assert (rt / "state").is_dir()
    for f in (rt / "logs").iterdir():
        assert "postgresql" not in f.read_text(encoding="utf-8"), f      # 로그에 DB URL 없음


def test_backend_refuses_invalid_config(tmp_path, empty_db_url):
    rt = _runtime(tmp_path, url=empty_db_url, port=free_port())
    cfg = rt / "config" / "esl_platform.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "unknown_key: 1\n", encoding="utf-8")
    r = subprocess.run([PY, str(LAUNCHER), "backend", "--runtime", str(rt)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
    assert "기동 거부" in (rt / "logs" / "backend.log").read_text(encoding="utf-8")
