"""`python -m esl_worker` — env ESL_PLATFORM_CONFIG, ESL_DATABASE_URL(설정 database.url_env)."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading


def main() -> int:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.path.dirname(here)
    for p in (os.path.join(root, "backend"), here, root):
        if p not in sys.path:
            sys.path.insert(0, p)
    from esl_platform.core.config import load_config
    from esl_platform.core.db.engine import make_engine

    from .runtime import Worker

    cfg = load_config()
    if cfg.settings is None:
        print("CONFIG_INVALID: " + "; ".join(f"{i.key}: {i.message}" for i in cfg.issues), file=sys.stderr)
        return 2
    logging.basicConfig(level=cfg.settings.logging.level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    url = os.environ.get(cfg.settings.database.url_env)
    if not url:
        print(f"DB 접속 정보가 없습니다: 환경변수 {cfg.settings.database.url_env}", file=sys.stderr)
        return 2
    w = Worker(cfg, make_engine(url, cfg.settings.database.pool_size))
    done = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: done.set())
    w.start()
    done.wait()
    w.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
