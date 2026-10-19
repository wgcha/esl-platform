"""워커 런타임: heartbeat·리퍼·SLOT/LIGHT 레인 루프. 시험은 `run_once(lane)`를 직접 호출한다."""

from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from typing import Any

from sqlalchemy.engine import Engine

from esl_platform import __version__
from esl_platform.core.config import LoadedConfig, Settings
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.repositories import workers as workers_repo

from .executor import Executor

log = logging.getLogger("esl_worker")


class Worker:
    def __init__(self, config: LoadedConfig, engine: Engine, *, core_target: str | None = None) -> None:
        if config.settings is None:
            raise RuntimeError("CONFIG_INVALID: " + ", ".join(config.error_keys()))
        self.config = config
        self.engine = engine
        self.core_target = core_target  # None = esl_worker.child:run_core (시험에서 대체 가능)
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"
        self.claims_paused = not config.ok
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def settings(self) -> Settings:
        assert self.config.settings is not None
        return self.config.settings

    @property
    def limiter(self) -> str:
        return "nice" if hasattr(os, "nice") and self.settings.worker.priority != "normal" else "none"

    def heartbeat_once(self) -> None:
        with self.engine.begin() as conn:
            workers_repo.heartbeat(conn, worker_id=self.worker_id, host=socket.gethostname(), pid=os.getpid(),
                                   app_version=__version__, limiter=self.limiter,
                                   info={"claims_paused": self.claims_paused})

    def reap_once(self) -> list[str]:
        with self.engine.begin() as conn:
            return jobs_repo.reap_expired(conn)

    def claim(self, lane: str) -> dict[str, Any] | None:
        if self.claims_paused:
            return None
        ttl = self.settings.worker.lease_ttl_s
        try:
            with self.engine.begin() as conn:
                if lane == "SLOT":
                    return jobs_repo.claim_slot(conn, self.worker_id, ttl)
                return jobs_repo.claim_light(conn, self.worker_id, ttl)
        except jobs_repo.ClaimRace:
            return None

    def run_once(self, lane: str = "SLOT") -> str | None:
        """리퍼 → claim → 실행(끝까지). 실행한 작업의 최종 상태 또는 None."""
        self.reap_once()
        job = self.claim(lane)
        if job is None:
            return None
        log.info("작업 %s (%s) 시작", job["id"], job["job_type"])
        return Executor(self, job).run()

    # ---------------------------------------------------------------- 상주
    def _loop(self, fn, interval: float) -> None:
        while not self._stop.is_set():
            try:
                busy = fn()
            except Exception:  # noqa: BLE001 - 루프 유지
                log.exception("워커 루프 오류")
                busy = None
            if not busy:
                self._stop.wait(interval)

    def start(self) -> None:
        w = self.settings.worker
        specs = [(self.heartbeat_once, w.heartbeat_interval_s), (lambda: self.run_once("SLOT"), w.claim_interval_s),
                 (lambda: self.run_once("LIGHT"), w.claim_interval_s)]
        for fn, iv in specs:
            t = threading.Thread(target=self._loop, args=(fn, iv), daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()
