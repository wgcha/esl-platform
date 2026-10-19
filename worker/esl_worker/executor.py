"""작업 실행기: step 순서대로 코어 단계(spawn 자식 프로세스) → 등록 step(DB).

- 시작 시 입력 지문(size·mtime) 재확인 → 다르면 FAILED `INPUT_CHANGED`.
- 자식 대기 중 `heartbeat_interval_s`마다 lease 갱신(실패 → 자식 종료, 상태를 더 쓰지 않음),
  `cancel_check_interval_s`마다 취소 플래그 확인 → terminate(→ grace 후 kill) → CANCELED(E7).
- 로그: `<case>/logs/<job_id>/step_<NN>_<key>.log`. 실행 시간 한도 없음.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import time
from typing import Any

from esl_platform.core.errors import LeaseLost
from esl_platform.core.inputs import changed_inputs
from esl_platform.core.repositories import cases as cases_repo
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.state_machine import CANCELED, FAILED, SUCCEEDED

from . import register
from .child import child_entry

log = logging.getLogger("esl_worker.executor")
_SPAWN = multiprocessing.get_context("spawn")


class _Canceled(Exception):
    pass


class _StepFailed(Exception):
    def __init__(self, code: str, message: str, exit_code: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.exit_code = exit_code


class Executor:
    def __init__(self, worker, job: dict[str, Any]) -> None:
        self.worker = worker
        self.engine = worker.engine
        self.settings = worker.settings
        self.job = job
        self.token = job["lease_token"]
        self.slot = job["lane"] == "SLOT"
        self.proc = None

    # ---------------------------------------------------------------- 도우미
    def _tx(self):
        return self.engine.begin()

    def _renew(self) -> None:
        with self._tx() as conn:
            if not jobs_repo.renew(conn, self.job["id"], self.token, self.settings.worker.lease_ttl_s, slot=self.slot):
                raise LeaseLost(self.job["id"])

    def _cancel_requested(self) -> bool:
        with self.engine.connect() as conn:
            return jobs_repo.is_cancel_requested(conn, self.job["id"])

    def _finish(self, state: str, code: str | None = None, message: str | None = None) -> None:
        with self._tx() as conn:
            jobs_repo.release(conn, self.job["id"], self.token, state, failure_code=code, failure_message=message)

    def _kill_child(self) -> None:
        p = self.proc
        if p is None or not p.is_alive():
            return
        p.terminate()
        p.join(self.settings.worker.terminate_grace_s)
        if p.is_alive():
            p.kill()
            p.join(5)

    # ---------------------------------------------------------------- 실행
    def run(self) -> str:
        job = self.job
        try:
            with self.engine.connect() as conn:
                case = cases_repo.get_case(conn, job["case_id"])
                steps = jobs_repo.get_steps(conn, job["id"])
            self.case = case
            self.cdir = os.path.join(self.settings.storage.esl_root, case["folder_name"])
            fp = (job["params"] or {}).get("input_fingerprint") or case["input_fingerprint"]
            changed = changed_inputs(fp)
            if changed:
                self._finish(FAILED, "INPUT_CHANGED", f"입력 파일이 바뀌었습니다: {changed[:3]}")
                return FAILED
            for st in steps:
                if st["state"] != "PENDING":
                    continue
                if self._cancel_requested():
                    raise _Canceled()
                self._run_step(st)
            self._finish(SUCCEEDED)
            return SUCCEEDED
        except _Canceled:
            self._kill_child()
            self._finish(CANCELED, "CANCELED", "사용자 취소")
            return CANCELED
        except _StepFailed as exc:
            self._finish(FAILED, exc.code, exc.message)
            return FAILED
        except LeaseLost:
            self._kill_child()
            log.error("lease 를 잃었습니다 — 작업 %s 상태를 더 쓰지 않습니다", job["id"])
            return "LEASE_LOST"
        finally:
            self._kill_child()

    def _run_step(self, st: dict[str, Any]) -> None:
        no, key = st["step_no"], st["step_key"]
        log_rel = f"logs/{self.job['id']}/step_{no:02d}_{key}.log"
        with self._tx() as conn:
            jobs_repo.step_update(conn, self.job["id"], self.token, no, state="RUNNING", log_rel=log_rel,
                                  started_at=_now(conn), progress_pct=0.0)
        log_path = os.path.join(self.cdir, log_rel)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        try:
            if st["core_stage"]:
                self._run_core(st, log_path)
                outputs = {"core_stage": st["core_stage"]}
                rels = [self._stage_dir(st["core_stage"]), "run.json", log_rel]
                if st["core_stage"] == "esl":
                    rels.insert(0, "03_bc")
                with self._tx() as conn:
                    jobs_repo.assert_lease(conn, self.job["id"], self.token)
                    register.register_artifacts(conn, self.case["id"], self.job["id"], self.cdir, rels)
                    rec = _stage_summary(self.cdir, st["core_stage"])
                    jobs_repo.patch_result(conn, self.job["id"], self.token, {st["core_stage"]: rec})
                    if rec.get("warnings"):
                        jobs_repo.add_warnings(conn, self.job["id"], self.token,
                                               [f"[{st['core_stage']}] {w}" for w in rec["warnings"]])
            else:
                with self._tx() as conn:
                    jobs_repo.assert_lease(conn, self.job["id"], self.token)
                    case = cases_repo.get_case(conn, self.case["id"], for_update=True)
                    try:
                        res = register.REGISTER[self.job["job_type"]](conn, self.job, case, self.cdir)
                    except register.RegisterError as exc:
                        raise _StepFailed(exc.code, exc.message) from None
                    jobs_repo.patch_result(conn, self.job["id"], self.token, {"registered": _jsonable(res)})
                outputs = {"registered": True}
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"[esl-worker] {key}: DB 등록 완료\n")
                with self._tx() as conn:
                    register.register_artifacts(conn, self.case["id"], self.job["id"], self.cdir, [log_rel])
        except _StepFailed as exc:
            with self._tx() as conn:
                jobs_repo.step_update(conn, self.job["id"], self.token, no, state="FAILED", failure_code=exc.code,
                                      failure_message=exc.message[:500], exit_code=exc.exit_code,
                                      finished_at=_now(conn))
                register.register_artifacts(conn, self.case["id"], self.job["id"], self.cdir, [log_rel, "run.json"])
            raise
        with self._tx() as conn:
            jobs_repo.step_update(conn, self.job["id"], self.token, no, state="SUCCEEDED", exit_code=0,
                                  progress_pct=100.0, finished_at=_now(conn), outputs=outputs)

    @staticmethod
    def _stage_dir(stage: str) -> str:
        from esl_platform.core.core_outputs import STAGE_DIRS

        return STAGE_DIRS.get(stage, stage)

    def _run_core(self, st: dict[str, Any], log_path: str) -> None:
        p = self.job["params"] or {}
        case = self.case
        stage = st["core_stage"]
        frame = p.get("frame_index") if stage in ("esl",) else None
        support = p.get("support_node_ids") if stage in ("esl",) else None
        result_path = log_path[:-4] + ".result.json"
        if os.path.exists(result_path):
            os.remove(result_path)
        spec = {"cfg": p.get("settings") or {}, "rad": case["rad_path"], "results": case["results_dir"],
                "out": self.cdir, "stage": stage, "frame": frame, "support_nodes": support,
                "log_path": log_path, "result_path": result_path, "priority": self.settings.worker.priority,
                "target": self.worker.core_target, "job_id": self.job["id"]}
        self.proc = _SPAWN.Process(target=child_entry, args=(spec,), name=f"esl-core-{stage}")
        self.proc.start()
        with self._tx() as conn:
            jobs_repo.step_update(conn, self.job["id"], self.token, st["step_no"],
                                  outputs={"pid": self.proc.pid, "core_stage": stage})
        w = self.settings.worker
        last_renew = last_cancel = time.monotonic()
        poll = min(0.2, w.cancel_check_interval_s, w.heartbeat_interval_s)
        while True:
            self.proc.join(poll)
            if not self.proc.is_alive():
                break
            now = time.monotonic()
            if now - last_renew >= w.heartbeat_interval_s:
                self._renew()
                last_renew = now
            if now - last_cancel >= w.cancel_check_interval_s:
                last_cancel = now
                if self._cancel_requested():
                    raise _Canceled()
        code = self.proc.exitcode
        self.proc = None
        self._renew()
        res = None
        if os.path.isfile(result_path):
            try:
                with open(result_path, encoding="utf-8") as fh:
                    res = json.load(fh)
            except (OSError, ValueError):
                res = None
        if code == 0 and res and res.get("ok"):
            return
        if res and not res.get("ok"):
            raise _StepFailed(res.get("code") or "INTERNAL_ERROR", res.get("message") or "코어 실패", code)
        raise _StepFailed("CORE_PROCESS_DIED", f"코어 프로세스가 비정상 종료했습니다(exit {code})", code)


def _now(conn):
    from sqlalchemy import func, select

    return conn.execute(select(func.now())).scalar_one()


def _stage_summary(cdir: str, stage: str) -> dict[str, Any]:
    from esl_platform.core.core_outputs import stage_record

    rec = stage_record(cdir, stage)
    return _jsonable({"status": rec.get("status"), "elapsed_s": rec.get("elapsed_s"),
                      "warnings": list(rec.get("warnings") or []), "summary": rec.get("summary")})


def _jsonable(o: Any) -> Any:
    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x)))
