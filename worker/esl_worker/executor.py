"""작업 실행기: step 순서대로 코어 단계(spawn 자식 프로세스) → 등록 step(DB).

- 시작 시 입력 지문(size·mtime) 재확인 → 다르면 FAILED `INPUT_CHANGED`. CASE_EXTRACT 는 rad include 가
  input_roots 안인지 다시 확인 → 밖이면 FAILED `PATH_OUTSIDE_ROOT`.
- VALIDATE·EXPORT 는 시작 직전 사전조건 재확인: 대상 ESL 실행이 아직 Case 의 현재 결과인지(VALIDATE 는 비stale
  까지) → 아니면 FAILED `PREREQUISITE_MISSING`(stale). 디스크 04_esl 이 그 실행의 것인지(esl_summary.json tag =
  ESL_SOLVE 작업 id) 확인하고, 다르면 runs/<esl_run_id>/ 스냅샷에서 되돌린다(불가 → `PREREQUISITE_MISSING`).
  같은 Case 의 작업은 claim 단계에서 동시에 1개만 RUNNING 이므로 확인 뒤 실행 중에 바뀌지 않는다.
- 코어 호출 인자: tag = 작업 id(ESL 결과 식별), export 는 params.targets → export_targets.
- run() 의 예기치 않은 예외는 즉시 FAILED `INTERNAL_ERROR`(lease 만료를 기다리지 않음).
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

from esl_platform.core.errors import DomainError, LeaseLost
from esl_platform.core.inputs import changed_inputs, esl_run_stale
from esl_platform.core.paths import check_includes
from esl_platform.core.repositories import cases as cases_repo
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.state_machine import CANCELED, FAILED, SUCCEEDED

from . import esl_snapshot, register
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
            self._precheck()
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
        except Exception as exc:  # noqa: BLE001 - 예기치 않은 오류 → 즉시 FAILED(lease 만료 대기 없음)
            self._kill_child()
            log.exception("작업 %s 실행 오류", job["id"])
            try:
                self._finish(FAILED, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}"[:450])
            except LeaseLost:
                return "LEASE_LOST"
            return FAILED
        finally:
            self._kill_child()

    # ---------------------------------------------------------------- 사전조건 재확인
    def _precheck(self) -> None:
        jt = self.job["job_type"]
        p = self.job["params"] or {}
        if jt == "CASE_EXTRACT":
            from . import core_adapter

            cc = ((p.get("settings") or {}).get("case")) or {}
            try:
                incs = core_adapter.scan_includes(self.case["rad_path"], int(cc.get("rad_include_max_depth") or 8),
                                                  cc.get("include_path_map") or None)
                check_includes(self.settings, incs)
            except DomainError as exc:
                raise _StepFailed(exc.code, exc.message) from None
            return
        if jt not in ("VALIDATE", "EXPORT"):
            return
        stale = "대상 ESL 결과가 더 이상 최신이 아닙니다(이후 ESL 계산 또는 입력 변경) — 현재 결과로 새 작업을 만드세요"
        with self._tx() as conn:
            case = cases_repo.get_case(conn, self.job["case_id"])
            run = cases_repo.get_esl_run(conn, p.get("esl_run_id")) if p.get("esl_run_id") else None
        if (run is None or run["case_id"] != case["id"] or run["status"] != "READY"
                or case.get("current_esl_run_id") != run["id"]):
            raise _StepFailed("PREREQUISITE_MISSING", stale)
        if jt == "VALIDATE" and esl_run_stale(case, run):
            raise _StepFailed("PREREQUISITE_MISSING", stale)
        try:
            how = esl_snapshot.ensure_on_disk(self.cdir, run)
        except (LookupError, OSError) as exc:
            raise _StepFailed("PREREQUISITE_MISSING", f"ESL 산출물이 대상 결과와 다릅니다: {exc}") from None
        if how != "current":
            with self._tx() as conn:
                jobs_repo.add_warnings(conn, self.job["id"], self.token,
                                       [f"04_esl 을 ESL 결과 {run['id']} 스냅샷에서 되돌림" if how == "restored"
                                        else "04_esl 에 실행 태그가 없음(이전 형식) — 현재 산출물로 진행"])

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
                "target": self.worker.core_target, "job_id": self.job["id"], "tag": self.job["id"],
                "export_targets": list(p["targets"]) if stage == "export" and p.get("targets") else None,
                "parent_pid": os.getpid()}
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
