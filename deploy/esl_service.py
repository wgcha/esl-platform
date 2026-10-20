"""ESL 서버 실행기(작업 스케줄러 ESL-Backend·ESL-Worker, 설치 스크립트, 시연 모드 공용).

  python <app>/esl_service.py backend  [--runtime <런타임>] [--config <설정>] [--frontend <프런트 빌드 폴더>]
  python <app>/esl_service.py worker   [--runtime <런타임>] [--config <설정>]
  python <app>/esl_service.py migrate  [--runtime <런타임>] [--config <설정>]     alembic upgrade head
  python <app>/esl_service.py check    [--runtime <런타임>] [--config <설정>] [check 인자...]   환경 점검 표(esl_platform.check)
  python <app>/esl_service.py endpoint [--runtime <런타임>] [--config <설정>]     {"host","port","base_path","health"} JSON

physicsai-platform 의 `--runtime` 규약과 같다: 플랫폼 코드는 환경변수(ESL_PLATFORM_CONFIG, 설정 database.url_env — 기본
ESL_DATABASE_URL)만 읽으므로, 이 실행기가 `<런타임>/config/esl_platform.yaml`(또는 --config)과 `<런타임>/secrets/database_url`
(설치 스크립트가 쓴 DB 접속 정보 — 현재 사용자·SYSTEM만 읽기)을 읽어 **이 프로세스 환경에만** 넣고 백엔드·워커를 시작한다.
작업 인자에는 파일 경로만 있고 비밀값은 인자·로그에 남지 않는다. --runtime 이 없으면 기존 환경변수를 그대로 쓴다(시연·개발).

- 로그: --runtime 이 있으면 `<런타임>/logs/backend.log`·`worker.log`(10 MB × 5 회전, 표준 출력·오류 포함). 없거나 --console 이면 콘솔.
- --frontend: 백엔드가 `{base_path}/`(기본 /esl/) 아래에서 프런트 빌드를 직접 서빙(시연 모드, 또는 Caddy 없이 대시보드
  Vite 프록시로 /esl 전체를 넘기는 구성). 운영 기본은 Caddy(deploy/caddy/esl.caddy)가 프런트를 서빙한다.
- 코드 위치: 이 파일 옆(설치본 `<런타임>/app/`) 또는 부모(저장소 `deploy/`)의 backend·worker·esl 을 sys.path 에 넣는다.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import sys
from typing import Any

sys.dont_write_bytecode = True   # deploy/ 아래에 __pycache__를 만들지 않는다(정적 검사·오프라인 묶음 대상 폴더)

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_NAME = "esl_platform.yaml"
DEFAULT_URL_ENV = "ESL_DATABASE_URL"
LOG_BYTES, LOG_COUNT = 10 * 1024 * 1024, 5


def app_root(here: str = HERE) -> str:
    """코드 루트: 설치본은 이 파일 폴더(<런타임>/app), 저장소는 그 부모(deploy/ 의 부모)."""
    for cand in (here, os.path.dirname(here)):
        if os.path.isdir(os.path.join(cand, "backend", "esl_platform")):
            return cand
    raise SystemExit(f"ESL 코드(backend/esl_platform)를 찾을 수 없습니다: {here}")


def add_code_paths(root: str) -> None:
    for p in (os.path.join(root, "worker"), os.path.join(root, "backend"), root):
        if p not in sys.path:
            sys.path.insert(0, p)


def config_path(runtime: str | None, config: str | None, environ: dict[str, str]) -> str:
    if config:
        return os.path.abspath(config)
    if runtime:
        return os.path.join(runtime, "config", CONFIG_NAME)
    p = environ.get("ESL_PLATFORM_CONFIG")
    if not p:
        raise SystemExit("설정 파일이 없습니다: --runtime, --config 또는 환경변수 ESL_PLATFORM_CONFIG")
    return os.path.abspath(p)


def read_secret(runtime: str) -> str:
    p = os.path.join(runtime, "secrets", "database_url")
    try:
        with open(p, encoding="utf-8-sig") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def url_env_name(cfg: str) -> str:
    """설정의 database.url_env(스키마 검증 전에도 읽는다 — migrate 는 설정 오류와 무관하게 동작). 없으면 기본값."""
    try:
        import yaml

        with open(cfg, encoding="utf-8-sig") as fh:
            d = yaml.safe_load(fh) or {}
        v = ((d.get("database") or {}) if isinstance(d, dict) else {}).get("url_env")
        if isinstance(v, str) and v:
            return v
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_URL_ENV


def server_settings(cfg: str) -> dict[str, Any]:
    """server.host·port·base_path(설정 파일에서 직접 — 검증 실패해도 포트는 읽는다)."""
    out = {"host": "127.0.0.1", "port": 8110, "base_path": "/esl"}
    try:
        import yaml

        with open(cfg, encoding="utf-8-sig") as fh:
            d = yaml.safe_load(fh) or {}
        s = d.get("server") if isinstance(d, dict) else None
        if isinstance(s, dict):
            for k in out:
                if s.get(k) is not None:
                    out[k] = s[k]
    except Exception:  # noqa: BLE001
        pass
    out["port"] = int(out["port"])
    out["base_path"] = "/" + str(out["base_path"]).strip("/")
    return out


def prepare_env(runtime: str | None, cfg: str, environ: dict[str, str]) -> dict[str, str]:
    """이 프로세스 환경(environ)에 설정 경로·DB URL·바인딩 호스트를 넣는다(런타임 DB 파일이 있으면 그것이 우선)."""
    environ["ESL_PLATFORM_CONFIG"] = cfg
    name = url_env_name(cfg)
    if runtime:
        url = read_secret(runtime)
        if url:
            environ[name] = url
    environ.setdefault("ESL_BIND_HOST", str(server_settings(cfg)["host"]))
    environ.setdefault("PYTHONUTF8", "1")
    return environ


class _ToLogger:
    """print·traceback(표준 출력·오류)을 로거로(회전 파일 핸들러 하나만 파일을 연다 — Windows 회전 안전)."""

    def __init__(self, logger: logging.Logger, level: int) -> None:
        self.logger, self.level, self.buf = logger, level, ""

    def write(self, s: str) -> int:
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line.rstrip())
        return len(s)

    def flush(self) -> None:
        if self.buf.strip():
            self.logger.log(self.level, self.buf.rstrip())
        self.buf = ""

    def isatty(self) -> bool:
        return False


def setup_logging(log_file: str | None, level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        h: logging.Handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=LOG_BYTES, backupCount=LOG_COUNT,
                                                                  encoding="utf-8")
        h.setFormatter(fmt)
        root.addHandler(h)
        sys.stdout = _ToLogger(logging.getLogger("stdout"), logging.INFO)  # type: ignore[assignment]
        sys.stderr = _ToLogger(logging.getLogger("stderr"), logging.ERROR)  # type: ignore[assignment]
    else:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _log_level(cfg: str) -> str:
    try:
        import yaml

        with open(cfg, encoding="utf-8-sig") as fh:
            d = yaml.safe_load(fh) or {}
        v = str(((d.get("logging") or {}) if isinstance(d, dict) else {}).get("level") or "INFO").upper()
        return v if v in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO"
    except Exception:  # noqa: BLE001
        return "INFO"


# ---------------------------------------------------------------- 프런트 정적 서빙(--frontend)
def safe_static_path(dist: str, rel: str) -> str | None:
    """dist 안의 파일 경로(없거나 밖을 가리키면 None). '..'·드라이브·역슬래시·콜론은 거부."""
    if not rel or "\\" in rel or ":" in rel or "\x00" in rel:
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    root = os.path.realpath(dist)
    p = os.path.realpath(os.path.join(root, *parts))
    if os.path.commonpath([p, root]) != root or not os.path.isfile(p):
        return None
    return p


def add_frontend(app: Any, base_path: str, dist: str) -> None:
    """`{base}` → 308 `{base}/`, `{base}/<파일>` 그대로, 없는 경로는 index.html(화면 내부 경로). `{base}/api/...` 는 API 404 유지."""
    from starlette.exceptions import HTTPException
    from starlette.responses import FileResponse, RedirectResponse

    base = "/" + base_path.strip("/")
    index = os.path.join(dist, "index.html")

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        return RedirectResponse(base + "/", status_code=307)

    @app.get(base, include_in_schema=False)
    def _base() -> RedirectResponse:
        return RedirectResponse(base + "/", status_code=308)

    @app.get(base + "/{rel:path}", include_in_schema=False)
    def _static(rel: str) -> FileResponse:
        if rel == "api" or rel.startswith("api/"):
            raise HTTPException(status_code=404)
        p = safe_static_path(dist, rel) if rel else None
        if p is not None:
            cache = "public, max-age=31536000, immutable" if rel.startswith("assets/") else "no-cache"
            return FileResponse(p, headers={"Cache-Control": cache})
        if not os.path.isfile(index):
            raise HTTPException(status_code=404, detail="프런트 빌드가 없습니다")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- 명령
def cmd_backend(args: argparse.Namespace, cfg: str) -> int:
    import uvicorn
    from esl_platform.api import main as api_main

    srv = server_settings(cfg)
    try:
        app = api_main.app
    except api_main.StartupRefused as exc:
        logging.getLogger("esl_service").error("기동 거부: %s", exc)
        print(f"기동 거부: {exc}", file=sys.stderr)
        return 2
    if args.frontend:
        dist = os.path.abspath(args.frontend)
        if not os.path.isfile(os.path.join(dist, "index.html")):
            logging.getLogger("esl_service").warning("프런트 빌드(index.html)가 없습니다: %s — 화면 요청은 404", dist)
        add_frontend(app, srv["base_path"], dist)
    logging.getLogger("esl_service").info("백엔드 시작: http://%s:%s%s/api (설정 %s)", srv["host"], srv["port"],
                                         srv["base_path"], cfg)
    uvicorn.run(app, host=str(srv["host"]), port=int(srv["port"]), log_config=None, access_log=False)
    return 0


def cmd_worker(args: argparse.Namespace, cfg: str) -> int:
    from esl_worker.__main__ import main as worker_main

    logging.getLogger("esl_service").info("워커 시작(설정 %s)", cfg)
    return int(worker_main() or 0)


def cmd_migrate(args: argparse.Namespace, cfg: str) -> int:
    from alembic import command
    from alembic.config import Config

    url = os.environ.get(url_env_name(cfg), "")
    if not url:
        print(f"DB 접속 정보가 없습니다: 환경변수 {url_env_name(cfg)} 또는 <런타임>/secrets/database_url", file=sys.stderr)
        return 2
    ini = os.path.join(app_root(), "alembic.ini")
    acfg = Config(ini)
    acfg.attributes["url"] = url
    command.upgrade(acfg, "head")
    print("alembic upgrade head 완료", flush=True)
    return 0


def cmd_check(args: argparse.Namespace, cfg: str, rest: list[str]) -> int:
    from esl_platform import check

    argv = ["--config", cfg] + (["--runtime", args.runtime] if args.runtime else []) + rest
    return check.main(argv)


def cmd_endpoint(args: argparse.Namespace, cfg: str) -> int:
    s = server_settings(cfg)
    s["health"] = f"http://127.0.0.1:{s['port']}{s['base_path']}/api/health"
    print(json.dumps(s, ensure_ascii=False), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="esl_service", description="ESL 서버 실행기")
    ap.add_argument("command", choices=("backend", "worker", "migrate", "check", "endpoint"))
    ap.add_argument("--runtime", default="", help="설치 런타임 폴더(config/esl_platform.yaml, secrets/database_url, logs)")
    ap.add_argument("--config", default="", help="플랫폼 설정 파일(기본 <런타임>/config/esl_platform.yaml 또는 env ESL_PLATFORM_CONFIG)")
    ap.add_argument("--frontend", default="", help="(backend) 프런트 빌드 폴더를 {base_path}/ 아래에서 직접 서빙")
    ap.add_argument("--log-dir", default="", help="로그 폴더(기본 <런타임>/logs, 런타임이 없으면 콘솔)")
    ap.add_argument("--console", action="store_true", help="로그를 파일 대신 콘솔로(문제 해결 — 작업을 멈추고 직접 띄울 때)")
    args, rest = ap.parse_known_args(argv)
    if rest and args.command != "check":
        ap.error(f"알 수 없는 인자: {' '.join(rest)}")
    runtime = os.path.abspath(args.runtime) if args.runtime else None
    args.runtime = runtime or ""
    cfg = config_path(runtime, args.config or None, dict(os.environ))
    add_code_paths(app_root())
    if args.command == "endpoint":
        return cmd_endpoint(args, cfg)
    prepare_env(runtime, cfg, os.environ)  # type: ignore[arg-type]
    if args.command in ("backend", "worker"):
        log_dir = "" if args.console else (args.log_dir or (os.path.join(runtime, "logs") if runtime else ""))
        setup_logging(os.path.join(log_dir, f"{args.command}.log") if log_dir else None, _log_level(cfg))
        if runtime:
            os.makedirs(os.path.join(runtime, "state"), exist_ok=True)
        return cmd_backend(args, cfg) if args.command == "backend" else cmd_worker(args, cfg)
    if args.command == "migrate":
        return cmd_migrate(args, cfg)
    return cmd_check(args, cfg, rest)


if __name__ == "__main__":
    sys.exit(main())
