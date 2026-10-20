"""시험 공용 fixture: 임시 PostgreSQL, 설정, 가짜 대시보드, 앱 클라이언트, 워커, 합성 Case 입력.

PostgreSQL: env ESL_TEST_DATABASE_URL(scripts/test-all 이 띄운 임시 클러스터)이 있으면 사용, 없으면 PG_BIN 또는
/usr/lib/postgresql/<ver>/bin 으로 임시 클러스터를 만든다. 없으면 DB 시험은 실패한다(skip 금지).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "backend", REPO / "worker", REPO, REPO / "tests" / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

API = "/esl/api"
CORE_EXAMPLE = REPO / "config" / "esl.example.yaml"
PLATFORM_EXAMPLE = REPO / "config" / "esl_platform.example.yaml"
LIBRARY_EXAMPLE = REPO / "config" / "library.example.yaml"


# ---------------------------------------------------------------- PostgreSQL
def find_pg_bin() -> str | None:
    cand = os.environ.get("PG_BIN")
    if cand and os.path.isfile(os.path.join(cand, "initdb")):
        return cand
    base = Path("/usr/lib/postgresql")
    if base.is_dir():
        for v in sorted(base.iterdir(), reverse=True):
            if (v / "bin" / "initdb").is_file():
                return str(v / "bin")
    w = shutil.which("initdb")
    return os.path.dirname(w) if w else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TempCluster:
    def __init__(self) -> None:
        self.bin = find_pg_bin()
        if not self.bin:
            pytest.fail("PostgreSQL 을 찾을 수 없습니다(PG_BIN 또는 ESL_TEST_DATABASE_URL 필요). DB 시험은 skip 하지 않습니다")
        self.dir = tempfile.mkdtemp(prefix="esl-pg-")
        self.port = _free_port()
        self.as_root = os.geteuid() == 0
        if self.as_root:
            shutil.chown(self.dir, user="postgres")
            os.chmod(self.dir, 0o700)
        self.data = os.path.join(self.dir, "data")
        self._run([f"{self.bin}/initdb", "-D", self.data, "-A", "trust", "-U", "postgres", "-E", "UTF8", "--no-sync"])
        self._run([f"{self.bin}/pg_ctl", "-D", self.data, "-l", os.path.join(self.dir, "log"), "-w", "-o",
                   f"-p {self.port} -k {self.dir} -c listen_addresses=127.0.0.1 -c fsync=off -c max_connections=200",
                   "start"])
        self.url = f"postgresql+psycopg://postgres@127.0.0.1:{self.port}/postgres"

    def _run(self, argv: list[str]) -> None:
        if self.as_root:
            argv = ["runuser", "-u", "postgres", "--", *argv]
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode != 0:
            pytest.fail(f"PostgreSQL 임시 클러스터 실패: {' '.join(argv)}\n{r.stdout}\n{r.stderr}")

    def stop(self) -> None:
        try:
            self._run([f"{self.bin}/pg_ctl", "-D", self.data, "-m", "immediate", "stop"])
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)


def with_db(url: str, db: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{db}"


def run_alembic_upgrade(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def pg_server():
    from esl_platform.core.db.engine import normalize_url

    ext = os.environ.get("ESL_TEST_DATABASE_URL")
    cluster = None
    if ext:
        admin_url = with_db(normalize_url(ext), "postgres")
    else:
        cluster = TempCluster()
        admin_url = cluster.url
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    tpl = f"esl_tpl_{uuid.uuid4().hex[:8]}"
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{tpl}"'))
    run_alembic_upgrade(with_db(admin_url, tpl))
    yield {"admin": admin, "admin_url": admin_url, "template": tpl}
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{tpl}" WITH (FORCE)'))
    admin.dispose()
    if cluster:
        cluster.stop()


@pytest.fixture()
def db_url(pg_server):
    name = f"esl_t_{uuid.uuid4().hex[:10]}"
    with pg_server["admin"].connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{pg_server["template"]}"'))
    url = with_db(pg_server["admin_url"], name)
    yield url
    with pg_server["admin"].connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture()
def engine(db_url):
    from esl_platform.core.db.engine import make_engine

    eng = make_engine(db_url, pool_size=5)
    yield eng
    eng.dispose()


# ---------------------------------------------------------------- 설정
def core_settings(precision64: bool = True) -> dict[str, Any]:
    d = yaml.safe_load(CORE_EXAMPLE.read_text(encoding="utf-8"))
    if precision64 and isinstance(d.get("extract"), dict) and "disp_precision" in d["extract"]:
        d["extract"]["disp_precision"] = "float64"   # 합성 사례 변위는 float64 저장
    return d


def make_settings_dict(base: Path, **overrides: Any) -> dict[str, Any]:
    esl_root = base / "esl_root"
    inputs = base / "inputs"
    esl_root.mkdir(exist_ok=True)
    inputs.mkdir(exist_ok=True)
    d: dict[str, Any] = yaml.safe_load(PLATFORM_EXAMPLE.read_text(encoding="utf-8"))
    d["profile"] = "dev"
    d["auth"]["mode"] = "dashboard"
    d["storage"] = {"esl_root": str(esl_root), "input_roots": [str(inputs)], "spdm_roots": [str(base / "spdm")]}
    d["worker"].update({"heartbeat_interval_s": 0.3, "lease_ttl_s": 3, "claim_interval_s": 0.1,
                        "cancel_check_interval_s": 0.2, "terminate_grace_s": 2, "state_dir": str(base / "state")})
    d["core"] = {"settings": core_settings()}
    d["library"] = {"config_path": str(LIBRARY_EXAMPLE)}
    d["report"] = {"auto": False}       # 기존 시험은 자동 보고서 없이(자동 큐 시험은 report={"auto": True})
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


@pytest.fixture()
def settings_dict(tmp_path):
    return make_settings_dict(tmp_path)


@pytest.fixture()
def loaded_config(settings_dict):
    from esl_platform.core.config import load_config_dict

    lc = load_config_dict(settings_dict, environ={})
    assert lc.ok, lc.errors()
    return lc


@pytest.fixture()
def inputs_root(settings_dict) -> Path:
    return Path(settings_dict["storage"]["input_roots"][0])


@pytest.fixture()
def esl_root(settings_dict) -> Path:
    return Path(settings_dict["storage"]["esl_root"])


# ---------------------------------------------------------------- 가짜 대시보드
USERS: dict[str, dict[str, Any]] = {
    "tok-admin": {"id": "u-admin", "username": "admin", "display_name": "관리자", "account_status": "ACTIVE",
                  "is_global_admin": True, "memberships": []},
    "tok-power": {"id": "u-power", "username": "power", "display_name": "파워", "account_status": "ACTIVE",
                  "is_global_admin": False, "memberships": [{"project_id": "p-1", "role": "power"}]},
    "tok-power2": {"id": "u-power2", "username": "power2", "display_name": "파워2", "account_status": "ACTIVE",
                   "is_global_admin": False, "memberships": [{"project_id": "p-1", "role": "power"}]},
    "tok-general": {"id": "u-general", "username": "general", "display_name": "일반", "account_status": "ACTIVE",
                    "is_global_admin": False, "memberships": [{"project_id": "p-1", "role": "general"}]},
    "tok-nonmember": {"id": "u-non", "username": "non", "display_name": "비멤버", "account_status": "ACTIVE",
                      "is_global_admin": False, "memberships": [{"project_id": "p-2", "role": "power"}]},
    "tok-pending": {"id": "u-pend", "username": "pend", "display_name": "대기", "account_status": "PENDING",
                    "is_global_admin": False, "memberships": []},
}
PROJECTS = [{"id": "p-1", "name": "포장 낙하", "product_name": "TV"},
            {"id": "p-2", "name": "브래킷", "product_name": "Monitor"}]


class FakeDashboard:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.mode = "ok"  # ok | 503 | timeout | badjson | 500

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if self.mode == "503":
            return httpx.Response(503, json={"detail": {"code": "AUTH_SETUP_REQUIRED"}})
        if self.mode == "500":
            return httpx.Response(500, json={})
        if self.mode == "badjson":
            return httpx.Response(200, content=b"<html>")
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if token == "tok-suspended":
            return httpx.Response(403, json={"detail": {"code": "AUTH_ACCOUNT_SUSPENDED"}})
        user = USERS.get(token)
        if user is None:
            return httpx.Response(401, json={"detail": "인증 필요"})
        if request.url.path == "/api/auth/me":
            return httpx.Response(200, json=user)
        if request.url.path == "/api/projects":
            return httpx.Response(200, json=PROJECTS)
        return httpx.Response(404, json={})

    def me_calls(self) -> int:
        return sum(1 for c in self.calls if c.url.path == "/api/auth/me")


@pytest.fixture()
def fake_dashboard():
    return FakeDashboard()


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def app_ctx(engine, loaded_config, fake_dashboard, clock):
    from esl_platform.api.context import build_context

    return build_context(loaded_config, engine, transport=httpx.MockTransport(fake_dashboard.handler), clock=clock)


@pytest.fixture()
def client(app_ctx):
    from fastapi.testclient import TestClient

    from esl_platform.api.main import create_app

    with TestClient(create_app(app_ctx), base_url="http://127.0.0.1") as c:
        yield c


def H(token: str, write: bool = False) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if write:
        h["X-ESL-Request"] = "1"
    return h


# ---------------------------------------------------------------- 워커
@pytest.fixture()
def worker_factory(engine, loaded_config):
    from esl_worker.runtime import Worker

    made: list[Any] = []

    def make(**kw: Any) -> Any:
        w = Worker(loaded_config, engine, **kw)
        made.append(w)
        return w

    yield make
    for w in made:
        w.stop()


def wait_for(pred, timeout: float = 30.0, interval: float = 0.05) -> Any:
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    raise AssertionError("시간 내 조건 충족 실패")


# ---------------------------------------------------------------- 합성 Case 입력
@pytest.fixture()
def synth_inputs(inputs_root) -> dict[str, Any]:
    """코어 합성 E2E 생성기(tests/pipeline/synth_case.py)로 rad + 결과 CSV 폴더를 input_roots 아래에 만든다."""
    import synth_case

    c = synth_case.build(str(inputs_root))
    return c


def create_case(client, synth: dict[str, Any], folder: str = "case01", title: str = "합성 Case",
                token: str = "tok-power", **extra: Any):
    body = {"project_id": "p-1", "folder_name": folder, "title": title, "rad_path": synth["rad"],
            "results_dir": synth["csv"], **extra}
    return client.post(f"{API}/cases", json=body, headers=H(token, True))


@pytest.fixture()
def mini_inputs(inputs_root) -> dict[str, Any]:
    """솔버 없이 만드는 작은 입력(2×2 판 rad + done.json·frames.csv·model.csv). 인증·경로·큐 시험용."""
    import json

    import numpy as np
    from esl.rad import write_rad

    d = inputs_root / "mini"
    (d / "csv").mkdir(parents=True)
    xs = np.array([[x, y, 0.0] for x in range(3) for y in range(3)], float) * 10.0
    nid = np.arange(1, 10, dtype=np.int64)
    conn = np.array([[1, 4, 5, 2], [2, 5, 6, 3], [4, 7, 8, 5], [5, 8, 9, 6]], dtype=np.int64)
    rad = write_rad(str(d / "mini_0000.rad"), nid, xs, np.arange(101, 105, dtype=np.int64),
                    np.full(4, 4, np.int8), conn, 7, "Chassis rear", 70, 2.0, 700, 2.1e5, 0.3)
    (d / "csv" / "done.json").write_text(json.dumps({"ok": True, "n_frames": 2, "part_id": 7, "warnings": []}))
    (d / "csv" / "frames.csv").write_text("frame_index,time\n0,0.0\n1,0.001\n")
    (d / "csv" / "model.csv").write_text("node_id,x0,y0,z0\n" + "".join(
        f"{i},{x},{y},{z}\n" for i, (x, y, z) in zip(nid, xs)))
    return {"rad": rad, "csv": str(d / "csv")}
