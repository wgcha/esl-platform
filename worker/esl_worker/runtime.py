"""워커 런타임: heartbeat·리퍼·SLOT/LIGHT 레인 루프. 시험은 `run_once(lane)`를 직접 호출한다.

P3-UX §6: SLOT 레인 루프는 `worker.slots` 개(각자 claim → 실행, DB worker_slot 행 1..slots 로 동시 수 보장, 같은 Case 는
claim 조건·부분 unique 로 직렬), LIGHT 레인은 별도 1개.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from esl_platform import __version__
from esl_platform.core.config import LoadedConfig, Settings
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.repositories import workers as workers_repo

from . import limiter as limiter_mod
from . import paicad_proc
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
        # 자원 제한기(worker.limiter): Windows 는 여기서 워커 수명 Job Object 를 만든다(실패 → 코어 step LIMITER_FAILED)
        self.proc_limiter = limiter_mod.create(self.settings.worker)
        self.doe_cache = paicad_proc.StatusCache()   # heartbeat info.paicad·gmsh(v0.9.0 비드 DOE)

    @property
    def settings(self) -> Settings:
        assert self.config.settings is not None
        return self.config.settings

    @property
    def limiter(self) -> str:
        """/status worker.limiter·환경 점검 heartbeat 에 보이는 한 줄(모드: 적용 내용 또는 사용 불가 이유)."""
        return limiter_mod.describe(self.proc_limiter)

    def doe_status(self, *, force: bool = False) -> dict[str, Any]:
        """v0.9.0 비드 DOE(§6.5): paicad version·OCP, gmsh import 점검 → heartbeat info.paicad·info.gmsh.
        bead_doe.paicad.check_interval_s 마다 다시(캐시). bead_doe 꺼짐 → {}."""
        try:
            v = self.doe_cache.get(self.settings, force=force)
        except Exception:  # noqa: BLE001 - 점검 실패가 heartbeat 를 막지 않음
            log.exception("paicad·gmsh 점검 오류")
            return {}
        return dict(v) if v else {}

    def heartbeat_once(self) -> None:
        info = {"claims_paused": self.claims_paused,
                "limits": self.proc_limiter.summary(),
                "slots": self.settings.worker.slots,
                "per_job": limiter_mod.job_limits(self.settings.worker).__dict__,
                "max_concurrent_hw": self.settings.altair.max_concurrent_hw}
        info.update(self.doe_status())
        with self.engine.begin() as conn:
            workers_repo.heartbeat(conn, worker_id=self.worker_id, host=socket.gethostname(), pid=os.getpid(),
                                   app_version=__version__, limiter=self.limiter, info=info)

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
                    return jobs_repo.claim_slot(conn, self.worker_id, ttl, self.settings.worker.slots)
                return jobs_repo.claim_light(conn, self.worker_id, ttl)
        except (jobs_repo.ClaimRace, IntegrityError):
            # IntegrityError = 같은 Case 의 다른 작업이 동시에 RUNNING 이 됨(ux_jobs_case_running) → 다음 주기에
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
        specs = [(self.heartbeat_once, w.heartbeat_interval_s)]
        specs += [(lambda: self.run_once("SLOT"), w.claim_interval_s) for _ in range(int(w.slots))]
        specs += [(lambda: self.run_once("LIGHT"), w.claim_interval_s)]
        for fn, iv in specs:
            t = threading.Thread(target=self._loop, args=(fn, iv), daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()
        self.proc_limiter.close()  # Windows: Job 핸들 닫기(KILL_ON_JOB_CLOSE — 남은 코어 자식 종료)
