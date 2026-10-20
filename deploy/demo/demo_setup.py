"""ESL 시연 모드 준비(Altair·HyperView 불필요 — 합성 Case). start-demo.ps1이 부르며, 직접 실행해도 된다.

  python demo_setup.py init --root <시연 폴더> [--port 8191] [--frontend <프런트 빌드 폴더>]
      시연 폴더 아래 esl_root·inputs·state·logs·config 를 만들고, 시연 설정(<시연 폴더>/config/esl_platform.yaml — profile dev,
      auth dev_static, 127.0.0.1)과 코어·라이브러리 설정을 쓰고, 합성 낙하 Case 입력(inputs/demo_drop: rad + 결과 CSV)을 만든다.
  python demo_setup.py db-up --root <시연 폴더> --pg-bin <PostgreSQL bin 폴더> [--pg-port 55433]
      시연 전용 PostgreSQL 클러스터(<시연 폴더>/pgdata, 127.0.0.1만, trust)를 만들고(없을 때만) 시작, DB esl_demo 를 만든다.
      기존 PostgreSQL을 쓰려면 이 단계 대신 ESL_DATABASE_URL 환경변수를 준다.
  python demo_setup.py db-down --root <시연 폴더>      시연 클러스터 중지(파일은 그대로)
  python demo_setup.py up --root <시연 폴더> [--no-prerun]
      migration(upgrade head) → 백엔드(프런트 직접 서빙 포함) 기동·health 확인 → 워커 기동 → seed(Case 2개, 하나는 ①~⑥ 완료).
      로그 <시연 폴더>/logs, 프로세스 정보 <시연 폴더>/state/demo-procs.json. DB URL은 ESL_DATABASE_URL(있으면) 또는 db-up 결과.
  python demo_setup.py down --root <시연 폴더>         백엔드·워커(와 자식 프로세스) 종료
  python demo_setup.py seed --root <시연 폴더> --url http://127.0.0.1:<port> [--prerun]   (백엔드·워커 기동 후) Case 만들기

경로 규칙: 시연 폴더 경로에 공백과 & | < > ^ % ! " ; , = ( ) 를 쓰지 않는다(플랫폼 경로 규칙).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
if HERE_DIR not in sys.path:  # 격리 실행(-I) 등으로 스크립트 폴더가 빠진 경우에도 같은 폴더 모듈을 찾는다
    sys.path.insert(0, HERE_DIR)
sys.dont_write_bytecode = True  # deploy/ 아래에 __pycache__를 만들지 않는다(정적 검사·오프라인 묶음 대상 폴더)

from demo_common import _log, add_code_paths, launcher, local_urlopen  # noqa: E402
from demo_db import cmd_db_down, cmd_db_up  # noqa: E402
from demo_init import cmd_init  # noqa: E402
from demo_procs import _orphan_backend, _proc_alive, _stop_procs, _stop_tree  # noqa: E402
from demo_seed import cmd_seed  # noqa: E402

PROCS_FILE = "demo-procs.json"


def _database_url(root: Path) -> str:
    url = os.environ.get("ESL_DATABASE_URL")
    if url:
        return url
    f = root / "state" / "demo-db.json"
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))["url"]
    raise SystemExit("DB 접속 정보가 없습니다: db-up을 먼저 실행하거나 ESL_DATABASE_URL 환경변수를 설정하세요")


def _child_env(root: Path, url: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"ESL_PLATFORM_CONFIG": str(root / "config" / "esl_platform.yaml"), "ESL_DATABASE_URL": url,
                "ESL_BIND_HOST": "127.0.0.1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return env


def _spawn(argv: list[str], env: dict[str, str], log: Path, cwd: Path) -> subprocess.Popen:
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP(콘솔 창 닫혀도 유지)
    else:
        kw["start_new_session"] = True
    fh = open(log, "ab")  # noqa: SIM115 - 자식 프로세스가 계속 쓴다
    return subprocess.Popen(argv, env=env, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, **kw)


def _health_error(port: int) -> str | None:
    """시연 백엔드 health. 정상이면 None, 아니면 원인 문자열. 프록시를 타지 않는다(local_urlopen)."""
    try:
        with local_urlopen(f"http://127.0.0.1:{port}/esl/api/health", timeout=2) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"
    try:
        status = json.loads(body).get("status")
    except (ValueError, AttributeError):
        return f"health 응답 형식 오류: {body[:200]!r}"
    return None if status == "ok" else f"health status={status!r}"


def _health(port: int) -> bool:
    return _health_error(port) is None


def _note(root: Path, msg: str) -> None:
    """화면 출력 + <시연 폴더>/logs/demo-setup.log(원인 추적용)."""
    _log(msg)
    try:
        (root / "logs").mkdir(parents=True, exist_ok=True)
        with open(root / "logs" / "demo-setup.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def cmd_up(args: argparse.Namespace) -> int:
    import psutil

    root = Path(args.root).resolve()
    cfg = root / "config" / "esl_platform.yaml"
    if not cfg.is_file():
        raise SystemExit(f"시연 설정이 없습니다: {cfg} — init을 먼저 실행하세요")
    add_code_paths()
    from esl_platform.core.config import load_config

    lc = load_config(str(cfg), environ={})
    if not lc.ok:
        raise SystemExit("시연 설정 검증 실패: " + "; ".join(f"{i.key}: {i.message}" for i in lc.issues))
    port = lc.settings.server.port
    info = json.loads((root / "state" / "demo.json").read_text(encoding="utf-8")) if (root / "state" / "demo.json").is_file() else {}
    frontend = str(info.get("frontend") or "")
    state = root / "state" / PROCS_FILE
    if state.is_file():
        old = json.loads(state.read_text(encoding="utf-8") or "{}")
        alive = sorted(k for k, v in old.items() if _proc_alive(v))
        if alive:
            if set(alive) >= {"backend", "worker"} and _health(port):
                _log(f"이미 실행 중입니다: http://127.0.0.1:{port}/esl/  (끝내려면 down)")
                print(json.dumps({"url": f"http://127.0.0.1:{port}/esl/", "already_running": True}))
                return 0
            _note(root, f"이전 실행이 일부만 남아 있어({', '.join(alive)}) 정리하고 다시 시작합니다")
            _stop_procs(old)
        state.write_text("{}", encoding="utf-8")
    if _health(port):
        orphan = _orphan_backend(port, root)
        if orphan is None:
            raise SystemExit(f"포트 {port}를 다른 프로그램이 쓰고 있습니다 — init --port로 바꾸세요")
        _note(root, f"실행 정보 없이 남은 이전 시연 백엔드(PID {orphan})를 종료합니다")
        _stop_tree(orphan)
    url = _database_url(root)
    env = _child_env(root, url)
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    svc = str(launcher())
    r = subprocess.run([sys.executable, svc, "migrate", "--config", str(cfg)], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"DB migration 실패: {(r.stderr or r.stdout)[-2000:]}")
    procs: dict[str, dict] = {}
    try:
        argv = [sys.executable, svc, "backend", "--config", str(cfg), "--log-dir", str(logs)]
        if frontend:
            argv += ["--frontend", frontend]
        be = _spawn(argv, env, logs / "backend.out.log", root)
        procs["backend"] = {"pid": be.pid, "create_time": psutil.Process(be.pid).create_time()}
        state.write_text(json.dumps(procs), encoding="utf-8")
        end = time.time() + float(args.timeout)
        while (err := _health_error(port)) is not None:
            if be.poll() is not None:
                raise SystemExit(f"백엔드 기동 실패: 프로세스 종료(종료코드 {be.returncode}, 마지막 health 오류: {err}) — "
                                 f"{logs / 'backend.out.log'}·{logs / 'backend.log'} 확인")
            if time.time() > end:
                raise SystemExit(f"백엔드 기동 실패: {args.timeout:g}초 안에 health 확인 안 됨(마지막 오류: {err}) — "
                                 f"{logs / 'backend.log'} 확인")
            time.sleep(0.5)
        _log(f"백엔드 기동: http://127.0.0.1:{port}/esl/")
        wk = _spawn([sys.executable, svc, "worker", "--config", str(cfg), "--log-dir", str(logs)], env,
                    logs / "worker.out.log", root)
        procs["worker"] = {"pid": wk.pid, "create_time": psutil.Process(wk.pid).create_time()}
        state.write_text(json.dumps(procs), encoding="utf-8")
        time.sleep(1.0)
        if wk.poll() is not None:
            raise SystemExit(f"워커 기동 실패 — {logs / 'worker.out.log'}·{logs / 'worker.log'} 확인")
        _log("워커 기동")
        cmd_seed(argparse.Namespace(root=str(root), url=f"http://127.0.0.1:{port}", prerun=not args.no_prerun,
                                    timeout=args.job_timeout))
    except BaseException as e:
        _note(root, f"시연 기동 실패: {e}")
        stopped = _stop_procs(procs)
        if stopped:
            _note(root, f"이번에 띄운 프로세스 정리: {', '.join(stopped)}")
        state.write_text("{}", encoding="utf-8")
        raise
    _log(f"브라우저에서 http://127.0.0.1:{port}/esl/ 을 여세요(시연 관리자로 자동 로그인)")
    print(json.dumps({"url": f"http://127.0.0.1:{port}/esl/", "already_running": False}))
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    state = root / "state" / PROCS_FILE
    if not state.is_file():
        _log("실행 정보가 없습니다")
        return 0
    procs = json.loads(state.read_text(encoding="utf-8") or "{}")
    for name in _stop_procs(procs):
        _log(f"{'워커' if name == 'worker' else '백엔드'} 종료")
    state.write_text("{}", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="demo_setup", description="ESL 시연 모드 준비")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("init", help="시연 폴더·설정·합성 Case 입력 만들기")
    a.add_argument("--root", required=True)
    a.add_argument("--port", type=int, default=8191)
    a.add_argument("--frontend", default="")
    a.set_defaults(func=cmd_init)
    b = sub.add_parser("seed", help="시연 Case 만들기(백엔드·워커 기동 후)")
    b.add_argument("--root", required=True)
    b.add_argument("--url", required=True)
    b.add_argument("--prerun", action="store_true")
    b.add_argument("--timeout", type=float, default=600)
    b.set_defaults(func=cmd_seed)
    c = sub.add_parser("db-up", help="시연 전용 PostgreSQL 클러스터 준비·시작")
    c.add_argument("--root", required=True)
    c.add_argument("--pg-bin", required=True)
    c.add_argument("--pg-port", type=int, default=55433)
    c.set_defaults(func=cmd_db_up)
    d = sub.add_parser("db-down", help="시연 전용 PostgreSQL 중지")
    d.add_argument("--root", required=True)
    d.set_defaults(func=cmd_db_down)
    e = sub.add_parser("up", help="migration·백엔드·워커·seed")
    e.add_argument("--root", required=True)
    e.add_argument("--timeout", type=float, default=90)
    e.add_argument("--job-timeout", type=float, default=600)
    e.add_argument("--no-prerun", action="store_true", help="①~⑥ 완료 Case를 미리 돌리지 않는다")
    e.set_defaults(func=cmd_up)
    f = sub.add_parser("down", help="백엔드·워커 종료")
    f.add_argument("--root", required=True)
    f.set_defaults(func=cmd_down)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
