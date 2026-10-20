"""시연 `db-up`/`db-down`: 시연 전용 PostgreSQL 클러스터(127.0.0.1, trust) 준비·시작·중지(physicsai 시연과 같은 방식)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from demo_common import DB_NAME, _log


def _pg(bin_dir: str, name: str) -> str:
    exe = Path(bin_dir) / (name + (".exe" if os.name == "nt" else ""))
    if not exe.is_file():
        raise SystemExit(f"PostgreSQL 실행 파일이 없습니다: {exe} (--pg-bin 확인)")
    return str(exe)


def _run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    # pg_ctl이 띄운 서버가 파이프를 물고 있지 않도록 출력은 DEVNULL(로그는 -l 파일)
    return subprocess.run(argv, stdin=subprocess.DEVNULL, **kw)


def cmd_db_up(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    data = root / "pgdata"
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    port = int(args.pg_port)
    if not (data / "PG_VERSION").is_file():
        _log(f"시연 PostgreSQL 클러스터 생성: {data}")
        r = _run([_pg(args.pg_bin, "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale"],
                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode != 0:
            raise SystemExit(f"initdb 실패: {r.stderr[-2000:]}")
    st = _run([_pg(args.pg_bin, "pg_ctl"), "-D", str(data), "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if st.returncode != 0:
        _log(f"시연 PostgreSQL 시작: 127.0.0.1:{port}")
        r = _run([_pg(args.pg_bin, "pg_ctl"), "-D", str(data), "-l", str(root / "logs" / "postgres.log"), "-w", "-o",
                  f"-p {port} -c listen_addresses=127.0.0.1" + ("" if os.name == "nt" else " -c unix_socket_directories=''"),
                  "start"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            raise SystemExit(f"PostgreSQL 시작 실패 — {root / 'logs' / 'postgres.log'} 확인(포트 {port} 사용 중일 수 있음)")
    psql = [_pg(args.pg_bin, "psql"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-tAc"]
    has = _run([*psql, f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}'"], capture_output=True, text=True)
    if has.returncode != 0:
        raise SystemExit(f"PostgreSQL 접속 실패: {has.stderr[-1000:]}")
    if has.stdout.strip() != "1":
        r = _run([*psql, f'CREATE DATABASE "{DB_NAME}"'], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"DB 생성 실패: {r.stderr[-1000:]}")
    url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/{DB_NAME}"  # 비밀번호 없음(trust, 127.0.0.1 전용)
    (root / "state" / "demo-db.json").write_text(json.dumps({"pg_bin": str(Path(args.pg_bin).resolve()), "data": str(data),
                                                              "port": port, "url": url}), encoding="utf-8")
    print(json.dumps({"database_url": url}))
    return 0


def cmd_db_down(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    f = root / "state" / "demo-db.json"
    if not f.is_file():
        _log("시연 PostgreSQL 정보가 없습니다(db-up을 쓰지 않음)")
        return 0
    info = json.loads(f.read_text(encoding="utf-8"))
    r = _run([_pg(info["pg_bin"], "pg_ctl"), "-D", info["data"], "-m", "fast", "-w", "stop"],
             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _log("시연 PostgreSQL 중지" if r.returncode == 0 else "시연 PostgreSQL이 이미 멈춰 있습니다")
    return 0
