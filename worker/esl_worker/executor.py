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
- P2(계약 esl_p2_library.md §11): LIB_ANALYZE 는 Case 가 없고 작업 폴더 = `<esl_root>/_analysis/<id>/`(로그도 그 아래),
  입력 지문 확인 대신 항목 폴더 존재 확인, 대상이 없으면 OPTDECK step 은 SKIPPED. VALIDATE 등록이 끝나면
  설정 `report.auto` 일 때 CASE_REPORT(LIGHT)를 같은 트랜잭션에서 큐에 넣는다(이미 대기 중이면 경고만).
- P3-UX §6: CASE_EXTRACT 첫 step H3D_EXTRACT(LOCAL, h3d 입력 Case 만)는 hw 를 직접 실행한다(esl_worker.h3d) —
  `altair.max_concurrent_hw` DB 세마포어를 잡을 때까지 대기(lease 갱신·취소 확인 계속), 작업별 제한기(limiter.for_job)로
  자원 제한, 취소·lease 상실 시 hw 프로세스 트리 종료. 실패 코드 `H3D_EXTRACT_FAILED`.
- 작업별 자원 제한기: SLOT 레인이 worker.slots 개 동시 실행되므로 작업마다 limiter.for_job(슬롯 번호)로 만든다.
- v0.7.0 OPT_RUN(계약 esl_opt_run.md): 대상 = jobs.opt_run_id, 작업 폴더 `<esl_root>/_opt/<id>/`. 준비·step 실행은
  opt_jobs(OS_SOLVE = os_solve, 외부 실행 공통 = localproc). OS_SOLVE 재사용이면 step SKIPPED. 코어 자식은 진행률 파일
  (`<log>.progress`, 정수 %)을 쓸 수 있고 부모가 step progress_pct(OPT_RUN 은 작업 진행률 가중)로 옮긴다.
- v0.9.0 DOE_PREP·DOE_PREVIEW·DOE_RUN(계약 esl_bead_doe.md): 대상 = jobs.bead_doe_id, 작업 폴더 `<esl_root>/_doe/<id>/`.
  준비·step 실행은 doe_jobs(paicad = paicad_proc, 코어 = esl.doe.stages), 작업 진행률 = DOE_STEP_WEIGHTS 가중.
- v0.11.0 SCX_FETCH(XFER, 계약 esl_scx_relay.md §9.1): 대상 = jobs.upload_id, 작업 폴더 = `<업로드 세션>/_scx/`(로그·기록),
  step 은 scx_fetch(HTTP 전송 — 별도 스레드, 이 스레드는 lease 갱신·취소 확인), 작업 진행률 = SCX_STEP_WEIGHTS 가중.
- v0.10.0(esl_menu_restructure.md §6.2·§7.3): EXPORT params.origin = library → 작업 폴더·로그 `<esl_root>/_exports/<batch>/`,
  Case 폴더 쓰기 없음(입력 지문·현재 run 재확인·history 보존·artifacts·자동 보고서 건너뜀), 자식이 코어
  esl.export.from_entry.run_items 실행. VALIDATE params.origin = library_revalidate → "현재 run" 대신 "그 run 의 추출이 Case
  현재 추출과 같음" 재확인 후 스냅샷 되돌림(ensure_on_disk), CASE_REPORT 자동 큐 없음, 등록 시 항목 전환(register).
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import time
from typing import Any

from esl_platform.core.errors import DomainError, LeaseLost
from esl_platform.core.inputs import changed_inputs, esl_run_stale, extract_stale, inputs_hash
from esl_platform.core.paths import ANALYSIS_DIR, check_includes, esl_subdir
from esl_platform.core.repositories import cases as cases_repo
from esl_platform.core.repositories import jobs as jobs_repo
from esl_platform.core.state_machine import CANCELED, FAILED, SUCCEEDED
from sqlalchemy.exc import IntegrityError

from esl_platform.core.job_types import DOE_JOB_TYPES, SCX_JOB_TYPES

from . import doe_jobs, esl_snapshot, h3d, limiter, opt_jobs, register, scx_fetch
from .child import child_entry
from . import lib_jobs  # noqa: E402,I001 - Case 없는 라이브러리 작업 준비 디스패치(LIB_COMPARE, §12.2)

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
        self.hw_proc = None
        self.case: dict[str, Any] | None = None
        self.lib: dict[str, Any] | None = None
        self.lim = limiter.for_job(worker, job.get("slot_id"))   # 작업별 자원 제한(worker.slots 로 나눔)

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
        hp = self.hw_proc
        if hp is not None:
            self.hw_proc = None
            h3d.kill_tree(hp, self.settings.worker.terminate_grace_s, self.lim)
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
                steps = jobs_repo.get_steps(conn, job["id"])
                case = cases_repo.get_case(conn, job["case_id"]) if job.get("case_id") else None
            if job["job_type"] == "LIB_ANALYZE":
                self._prepare_analysis()
            elif job["job_type"] == "OPT_RUN":                 # v0.7.0 비드 최적화(대상 = opt_run_id, esl_opt_run.md)
                try:
                    self.cdir, self.lib = opt_jobs.prepare(self)
                except opt_jobs.PrepareFailed as exc:
                    raise _StepFailed(exc.code, exc.message) from None
            elif job["job_type"] in DOE_JOB_TYPES:             # v0.9.0 비드 DOE(대상 = bead_doe_id, esl_bead_doe.md)
                try:
                    self.cdir, self.lib = doe_jobs.prepare(self)
                except doe_jobs.PrepareFailed as exc:
                    raise _StepFailed(exc.code, exc.message) from None
            elif job["job_type"] in SCX_JOB_TYPES:             # v0.11.0 SCX 드라이브 내려받기(대상 = upload_id, XFER)
                try:
                    self.cdir, self.lib = scx_fetch.prepare(self)
                except scx_fetch.PrepareFailed as exc:
                    raise _StepFailed(exc.code, exc.message) from None
            elif lib_jobs.is_lib_export(job):                  # v0.10.0 라이브러리 다중 내보내기(Case 폴더 쓰기 없음)
                try:
                    self.cdir, self.lib = lib_jobs.prepare_lib_export(self.settings, job)
                except lib_jobs.PrepareFailed as exc:
                    raise _StepFailed(exc.code, exc.message) from None
            elif job["job_type"] in lib_jobs.PREPARE:          # LIB_COMPARE 등(디스패치는 lib_jobs)
                try:
                    self.cdir, self.lib = lib_jobs.PREPARE[job["job_type"]](self.settings, job)
                except lib_jobs.PrepareFailed as exc:
                    raise _StepFailed(exc.code, exc.message) from None
            else:
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
        except Exception as exc:
            self._kill_child()
            log.exception("작업 %s 실행 오류", job["id"])
            try:
                self._finish(FAILED, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}"[:450])
            except LeaseLost:
                return "LEASE_LOST"
            return FAILED
        finally:
            self._kill_child()
            if self.lim is not limiter.of(self.worker):
                self.lim.close()   # Windows: 작업 Job 핸들 닫기(KILL_ON_JOB_CLOSE)

    # ---------------------------------------------------------------- LIB_ANALYZE 준비
    def _prepare_analysis(self) -> None:
        """작업 폴더 <esl_root>/_analysis/<id>/(안전 경로) + 항목 폴더(params dir_rel → 절대경로) 확인."""
        p = self.job["params"] or {}
        aid = self.job["analysis_id"]
        try:
            self.cdir = esl_subdir(self.settings, ANALYSIS_DIR, aid)
            lib_root = esl_subdir(self.settings, "_library")
            os.makedirs(self.cdir, exist_ok=True)

            def resolve(it):
                if it is None:
                    return None
                d = esl_subdir(self.settings, *it["dir_rel"].split("/"))
                if not os.path.isfile(os.path.join(d, "entry.json")):
                    raise _StepFailed("PREREQUISITE_MISSING", f"라이브러리 항목 폴더가 없습니다: {it['dir_rel']}")
                return {"id": it["id"], "dir": d, "overlay": it.get("overlay")}

            self.lib = {"cfg": p.get("settings") or {}, "lib_root": lib_root, "analysis_id": aid,
                        "entries": [resolve(it) for it in p.get("entries") or []], "target": resolve(p.get("target")),
                        "options": p.get("options") or {}, "filters": p.get("filters") or {}, "title": p.get("title")}
        except DomainError as exc:
            raise _StepFailed(exc.code, exc.message) from None

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
        if is_revalidate(self.job):
            # §7.3: 대상 = 항목의 run(현재 run 아니어도 됨) — 그 run 의 추출이 Case 현재 추출과 같을 때만
            if run is None or run["case_id"] != case["id"] or run["status"] != "READY" or not same_extract(case, run):
                raise _StepFailed("PREREQUISITE_MISSING", "재검증 대상 ESL 결과의 추출이 Case 현재 추출과 다릅니다 — "
                                  "Case를 다시 계산해 새로 등록하세요")
        elif (run is None or run["case_id"] != case["id"] or run["status"] != "READY"
                or case.get("current_esl_run_id") != run["id"]):
            raise _StepFailed("PREREQUISITE_MISSING", stale)
        elif jt == "VALIDATE" and esl_run_stale(case, run):
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

    def _register_artifacts(self, conn, rels: list[str]) -> None:
        if self.case is not None:
            register.register_artifacts(conn, self.case["id"], self.job["id"], self.cdir, rels)

    def _run_step(self, st: dict[str, Any]) -> None:
        no, key = st["step_no"], st["step_key"]
        if st["core_stage"] == "lib_optdeck" and not (self.lib or {}).get("target"):
            with self._tx() as conn:
                jobs_repo.step_update(conn, self.job["id"], self.token, no, state="SKIPPED", started_at=_now(conn),
                                      finished_at=_now(conn), outputs={"skipped": "대상 모델 없음 — 덱 생성 안 함"})
            return
        log_rel = f"logs/{self.job['id']}/step_{no:02d}_{key}.log"
        with self._tx() as conn:
            jobs_repo.step_update(conn, self.job["id"], self.token, no, state="RUNNING", log_rel=log_rel,
                                  started_at=_now(conn), progress_pct=0.0)
        log_path = os.path.join(self.cdir, log_rel)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        final = "SUCCEEDED"
        try:
            if self.job["job_type"] == "OPT_RUN":
                outputs = opt_jobs.run_step(self, st, log_path)
                if outputs.pop("_skipped", False):
                    final = "SKIPPED"          # OS_SOLVE 재사용(OR-D-19)
            elif self.job["job_type"] in DOE_JOB_TYPES:
                outputs = doe_jobs.run_step(self, st, log_path)
                if outputs.pop("_skipped", False):
                    final = "SKIPPED"          # BD_MESH0(③ 아님)
            elif self.job["job_type"] in SCX_JOB_TYPES:
                outputs = scx_fetch.run_step(self, st, log_path)
            elif st["step_key"] == "H3D_EXTRACT":
                outputs = self._run_h3d(st, log_path)
                with self._tx() as conn:
                    jobs_repo.patch_result(conn, self.job["id"], self.token, {"h3d_extract": outputs.get("done")})
                    self._register_artifacts(conn, [log_rel])
            elif st["core_stage"] and self.case is None:
                self._run_core(st, log_path)
                outputs = {"core_stage": st["core_stage"]}
                with self._tx() as conn:
                    jobs_repo.patch_result(conn, self.job["id"], self.token, {st["core_stage"]: {"status": "done"}})
            elif st["core_stage"]:
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
                    case = cases_repo.get_case(conn, self.case["id"], for_update=True) if self.case else None
                    try:
                        res = register.REGISTER[self.job["job_type"]](conn, self.job, case, self.cdir)
                    except register.RegisterError as exc:
                        raise _StepFailed(exc.code, exc.message) from None
                    job_warns = res.pop("warnings_job", None) if isinstance(res, dict) else None
                    jobs_repo.patch_result(conn, self.job["id"], self.token, {"registered": _jsonable(res)})
                    if isinstance(res, dict) and res.get("revalidate"):
                        jobs_repo.patch_result(conn, self.job["id"], self.token,
                                               {"revalidate": _jsonable(res["revalidate"])})
                        if res["revalidate"].get("outcome") == "ENTRY_CHANGED":
                            jobs_repo.add_warnings(conn, self.job["id"], self.token,
                                                   ["재검증 중 라이브러리 항목이 폐기·변경되어 항목을 전환하지 않았습니다"])
                    if job_warns:                    # 라이브러리 내보내기 일부 항목 실패 → 작업 경고(§6.2)
                        jobs_repo.add_warnings(conn, self.job["id"], self.token, [str(w) for w in job_warns])
                    if (self.job["job_type"] == "VALIDATE" and self.settings.report.auto
                            and not is_revalidate(self.job)):        # 재검증은 현재 run 보고서가 아님(§7.3)
                        self._queue_report(conn, res)
                outputs = {"registered": True}
                note = self._archive_history()
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"[esl-worker] {key}: DB 등록 완료\n")
                    if note:
                        fh.write(f"[esl-worker] {note}\n")
                with self._tx() as conn:
                    self._register_artifacts(conn, [log_rel])
        except _StepFailed as exc:
            with self._tx() as conn:
                jobs_repo.step_update(conn, self.job["id"], self.token, no, state="FAILED", failure_code=exc.code,
                                      failure_message=exc.message[:500], exit_code=exc.exit_code,
                                      finished_at=_now(conn))
                self._register_artifacts(conn, [log_rel, "run.json"])
            raise
        with self._tx() as conn:
            jobs_repo.step_update(conn, self.job["id"], self.token, no, state=final,
                                  exit_code=0 if final == "SUCCEEDED" else None,
                                  progress_pct=100.0, finished_at=_now(conn), outputs=outputs)
            if self.job["job_type"] == "OPT_RUN":
                opt_jobs.mark_job_progress(conn, self, st["step_key"], 100.0)
            elif self.job["job_type"] in DOE_JOB_TYPES:
                doe_jobs.mark_job_progress(conn, self, st["step_key"], 100.0)
            elif self.job["job_type"] in SCX_JOB_TYPES:
                scx_fetch.mark_job_progress(conn, self, st["step_key"], 100.0)

    def _archive_history(self) -> str | None:
        """H-5: EXPORT·CASE_REPORT 등록 성공 직후 결과 파일을 <case>/history/<job_id>/ 에 복사(설정 history.archive_files).
        실패해도 작업은 성공 — 경고 HISTORY_ARCHIVE_FAILED 만 남긴다."""
        if self.job["job_type"] not in ("EXPORT", "CASE_REPORT") or not self.settings.history.archive_files:
            return None
        if lib_jobs.is_lib_export(self.job):        # 라이브러리 내보내기는 Case 폴더에 쓰지 않음(묶음 폴더가 보존본)
            return None
        try:
            n = register.archive_history(self.cdir, self.job["job_type"], self.job["id"])
            return f"history 보존: {n}개 파일 → history/{self.job['id']}/" if n else None
        except Exception as exc:  # noqa: BLE001 - 보존 실패가 작업 결과를 바꾸지 않는다
            msg = f"HISTORY_ARCHIVE_FAILED: 작업별 결과 파일 보존 실패({type(exc).__name__}: {exc})"[:300]
            log.warning("작업 %s %s", self.job["id"], msg)
            with self._tx() as conn:
                jobs_repo.add_warnings(conn, self.job["id"], self.token, [msg])
            return msg

    def _queue_report(self, conn, res: dict[str, Any]) -> None:
        """VALIDATE 성공 → CASE_REPORT(LIGHT) 자동 큐(설정 report.auto). 같은 Case 에 대기 중인 보고서가 있으면 경고만."""
        p = self.job["params"] or {}
        params = {"settings": p.get("settings") or {}, "validation_id": res.get("validation_id"),
                  "esl_run_id": p.get("esl_run_id"), "auto": True}
        try:
            with conn.begin_nested():
                rj = jobs_repo.insert_job(conn, case_id=self.case["id"], project_id=self.job["project_id"],
                                          job_type="CASE_REPORT", params=params, created_by=self.job["created_by"],
                                          created_by_name=self.job["created_by_name"])
            jobs_repo.patch_result(conn, self.job["id"], self.token, {"report_job_id": rj["id"]})
        except IntegrityError:
            jobs_repo.add_warnings(conn, self.job["id"], self.token,
                                   ["보고서 작업이 이미 대기 중이라 자동 보고서를 추가하지 않았습니다"])

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
        progress_path = log_path[:-4] + ".progress"
        for pth in (result_path, progress_path):
            if os.path.exists(pth):
                os.remove(pth)
        spec = {"cfg": p.get("settings") or {}, "rad": case["rad_path"] if case else None,
                "results": case["results_dir"] if case else None, "lib": self.lib,
                "out": self.cdir, "stage": stage, "frame": frame, "support_nodes": support,
                "log_path": log_path, "result_path": result_path, "priority": self.settings.worker.priority,
                "target": self.worker.core_target, "job_id": self.job["id"], "tag": self.job["id"],
                "export_targets": list(p["targets"]) if stage == "export" and p.get("targets") else None,
                "parent_pid": os.getpid(), "progress_path": progress_path}
        gate = limiter.prepare(self.worker, spec, self.lim)
        self.proc = _SPAWN.Process(target=child_entry, args=(spec,), name=f"esl-core-{stage}")
        self.proc.start()
        applied = limiter.after_start(self.worker, self.proc, gate)  # 자원 제한(Windows Job) → 자식 시작 신호
        with self._tx() as conn:
            jobs_repo.step_update(conn, self.job["id"], self.token, st["step_no"],
                                  outputs={"pid": self.proc.pid, "core_stage": stage, "limiter": applied})
        w = self.settings.worker
        last_renew = last_cancel = time.monotonic()
        poll = min(0.2, w.cancel_check_interval_s, w.heartbeat_interval_s)
        shown = [-1]
        while True:
            self.proc.join(poll)
            if not self.proc.is_alive():
                break
            self._core_progress(st, progress_path, shown)
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


    def _core_progress(self, st: dict[str, Any], path: str, shown: list[int]) -> None:
        """코어 자식이 쓰는 진행률 파일(정수 %, 선택) → step progress_pct(단조 증가). OPT_RUN 은 작업 진행률(가중)도."""
        try:
            with open(path, encoding="ascii") as fh:
                pct = int(float(fh.read().strip() or -1))
        except (OSError, ValueError):
            return
        if pct <= shown[0]:
            return
        shown[0] = pct
        if self.job["job_type"] == "OPT_RUN":
            opt_jobs.set_progress(self, st, float(pct))
        elif self.job["job_type"] in DOE_JOB_TYPES:
            doe_jobs.set_progress(self, st, float(pct))
        else:
            with self._tx() as conn:
                jobs_repo.step_update(conn, self.job["id"], self.token, st["step_no"], progress_pct=float(pct))

    # ---------------------------------------------------------------- H3D_EXTRACT(LOCAL, P3-UX §6)
    def _wait_tick(self, state: dict[str, float]) -> None:
        """대기·실행 중 주기 작업: lease 갱신(heartbeat_interval_s), 취소 확인(cancel_check_interval_s)."""
        w = self.settings.worker
        now = time.monotonic()
        if now - state["renew"] >= w.heartbeat_interval_s:
            self._renew()
            state["renew"] = now
        if now - state["cancel"] >= w.cancel_check_interval_s:
            state["cancel"] = now
            if self._cancel_requested():
                raise _Canceled()

    def _run_h3d(self, st: dict[str, Any], log_path: str) -> dict[str, Any]:
        from esl_platform.core.config import default_extract_tcl
        from esl_platform.core.paths import h3d_work_dir

        p = (self.job["params"] or {}).get("h3d") or {}
        s = self.settings
        no = st["step_no"]

        def echo(msg: str) -> None:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")

        if not p.get("h3d_path") or not p.get("out_dir"):
            raise _StepFailed("PREREQUISITE_MISSING", "h3d 추출 params 가 없습니다(h3d 입력 Case 가 아님)")
        tcl = default_extract_tcl()
        if not os.path.isfile(tcl):
            raise _StepFailed("TOOL_OUTPUT_MISSING", f"추출 TCL 이 코드 스냅샷에 없습니다: {tcl}")
        hw = s.altair.hw_exe_path
        if not hw:
            raise _StepFailed(h3d.FAILURE, "hw 실행 파일 경로(altair.hw_exe_path)가 설정되지 않았습니다")
        if not os.path.isfile(hw):
            raise _StepFailed(h3d.FAILURE, f"hw 실행 파일이 없습니다(altair.hw_exe_path): {hw}")
        try:
            work = h3d_work_dir(s, self.case["folder_name"])
        except DomainError as exc:
            raise _StepFailed(exc.code, exc.message) from None
        out_dir = p["out_dir"]
        if os.path.normcase(os.path.normpath(out_dir)) != os.path.normcase(os.path.join(work, "raw")):
            raise _StepFailed("PATH_UNSAFE", "h3d 추출 출력 폴더가 Case 의 서버 추출 폴더가 아닙니다")
        os.makedirs(out_dir, exist_ok=True)
        prev = h3d.backup_previous(out_dir)
        if prev:
            echo(f"[esl-worker] 이전 추출 산출물을 옮김: {prev}")
        request = os.path.join(work, "request.txt")
        # 누적 씬(rad 가 이전 런 상태 파일 include): 대상 파트 이전 소성 CSV → TCL '+prev' 순위·F0 패스
        prev_csv = os.path.join(work, h3d.PREV_CSV)
        moved = h3d.backup_prev_csv(work)
        if moved:
            echo(f"[esl-worker] 이전 prev.csv 를 옮김: {moved}")
        cum = None
        if self.case.get("rad_path"):
            from . import core_adapter
            try:
                cum = core_adapter.cumulative_prev(self.case["rad_path"], p["part"], prev_csv,
                                                   (self.job["params"] or {}).get("settings") or {})
            except core_adapter.CoreError as exc:
                echo(f"[esl-worker] 누적 씬 판정 생략({exc.code}: {exc.message}) — 기존 추출로 진행")
        if cum:
            echo(f"[esl-worker] 누적 씬: 상태 파일 {[os.path.basename(x) for x in cum['state_files']]}, "
                 f"prev.csv {cum['n']}요소 → request prev_file·frame0_pass·cum_min_incr")
        try:
            h3d.write_request(request, part=p["part"], hot_k=p["hot_k"], top_n=p["top_n"],
                              extra=h3d.cumulative_request(cum, prev_csv))
        except h3d.H3dError as exc:
            raise _StepFailed(exc.code, exc.message) from None
        try:
            argv = h3d.build_argv(list(s.commands.h3d_extract), h3d.values_for(
                hw=hw, tcl=tcl, h3d=p["h3d_path"], request=request, out_dir=out_dir, part=p["part"],
                hot_k=p["hot_k"], top_n=p["top_n"]))
        except h3d.H3dError as exc:
            raise _StepFailed(exc.code, exc.message) from None

        # hw 동시 실행 한도(DB 세마포어) — 잡을 때까지 대기
        tick = {"renew": time.monotonic(), "cancel": time.monotonic()}
        limit = s.altair.max_concurrent_hw
        waited = False
        while True:
            with self._tx() as conn:
                if jobs_repo.acquire_hw(conn, self.job["id"], self.token, no, limit):
                    break
            if not waited:
                echo(f"[esl-worker] hw 동시 실행 한도 {limit}개(altair.max_concurrent_hw) — 다른 추출이 끝나기를 기다립니다")
                waited = True
            time.sleep(min(0.5, s.worker.claim_interval_s))
            self._wait_tick(tick)
        if waited:
            echo("[esl-worker] hw 실행 권한을 얻었습니다")
        with self._tx() as conn:
            jobs_repo.step_update(conn, self.job["id"], self.token, no, command=argv)
        echo(f"[esl-worker] H3D_EXTRACT: {p['h3d_path']} → {out_dir} (part={p['part']}, hot_k={p['hot_k']}, "
             f"top_n={p['top_n']})")
        echo("[esl-worker] argv: " + json.dumps(argv, ensure_ascii=False))
        env = dict(os.environ)
        env.update({"ESL_INPUT": h3d.fwd(p["h3d_path"]), "ESL_OUTPUT": h3d.fwd(out_dir), "ESL_PART": str(p["part"]),
                    "ESL_CONFIG": h3d.fwd(request)})
        t0 = time.time()
        with open(log_path, "ab") as log_fh:
            try:
                self.hw_proc = h3d.start(argv, cwd=work, log_fh=log_fh, env=env,
                                         preexec=limiter.posix_preexec(self.lim), priority=s.worker.priority)
            except h3d.H3dError as exc:
                raise _StepFailed(exc.code, exc.message) from None
            try:
                applied = limiter.attach_popen(self.lim, self.hw_proc)
            except limiter.LimiterError as exc:
                h3d.kill_tree(self.hw_proc, s.worker.terminate_grace_s, self.lim)
                self.hw_proc = None
                raise _StepFailed(limiter.FAILURE_CODE, str(exc)) from None
            pid = self.hw_proc.pid
            echo(f"[esl-worker] hw pid {pid} 시작, 자원 제한 {applied}")
            with self._tx() as conn:
                jobs_repo.step_update(conn, self.job["id"], self.token, no,
                                      outputs={"hw_acquired": True, "pid": pid, "limiter": applied})
            # hw(GUI 서브시스템)는 Tcl stdout 을 로그로 내보내지 않을 수 있어 TCL 이 출력 폴더에 쓰는 progress.log 를 옮긴다
            tail = h3d.ProgressTail(out_dir)
            trk = h3d.ProgressTracker(h3d.expected_load_s(p["h3d_path"]))
            hb_s = float(getattr(s.worker, "progress_heartbeat_s", h3d.PROGRESS_HEARTBEAT_S))
            last_poll = last_out = time.monotonic()
            shown = [0]

            def drain(flush: bool = False) -> bool:
                new = tail.poll(flush=flush)
                for ln in new:
                    echo(ln)
                    trk.feed(ln)
                pct = trk.tick()
                if int(pct) > shown[0]:        # 정수 % 가 바뀔 때만 DB 기록(단조 증가)
                    shown[0] = int(pct)
                    with self._tx() as conn:
                        jobs_repo.step_update(conn, self.job["id"], self.token, no, progress_pct=float(shown[0]))
                return bool(new)

            while self.hw_proc.poll() is None:
                time.sleep(0.1)
                self._wait_tick(tick)
                now = time.monotonic()
                if now - last_poll >= h3d.PROGRESS_POLL_S:
                    last_poll = now
                    if drain():
                        last_out = now
                    elif now - last_out >= hb_s:
                        last_out = now
                        echo(f"[esl-worker] 추출 진행 중… 경과 {(time.time() - t0) / 60:.1f}분, "
                             f"출력 폴더 크기 {h3d.dir_size_mb(out_dir):.1f} MB, 진행률 {trk.pct:.0f}%"
                             + (f", 마지막 단계 {trk.last_step}" if trk.last_step else ""))
            code = self.hw_proc.returncode
            drain(flush=True)
            # 그룹에 남은 자식(hw 가 띄운 프로세스)도 정리
            h3d.kill_tree(self.hw_proc, s.worker.terminate_grace_s, self.lim)
            self.hw_proc = None
        self._renew()
        ok, msg, lines, done = h3d.evaluate(code, out_dir, slim=bool(p.get("slim")))
        for ln in lines:
            echo(ln)
        echo(f"[esl-worker] hw 종료코드 {code} ({time.time() - t0:.1f}s) — {'성공' if ok else '실패: ' + msg}")
        if ok:
            echo("[esl-worker] extract done -> pack")
        if not ok:
            raise _StepFailed(h3d.FAILURE, msg, code)
        return {"done": h3d.done_summary(done), "exit_code": code, "hw_acquired": False}


def is_revalidate(job: dict[str, Any]) -> bool:
    return job.get("job_type") == "VALIDATE" and (job.get("params") or {}).get("origin") == "library_revalidate"


def same_extract(case: dict[str, Any], run: dict[str, Any]) -> bool:
    """§7.3: inputs_hash(현재 추출 job·part_title, run 의 t*·지지 세트) == run.inputs_hash 이고 추출 비stale."""
    es = case.get("extract_summary") or {}
    ih = inputs_hash(extract_job_id=es.get("job_id"), part_title=case["part_title"],
                     tstar={"frame_index": run["frame_index"], "metric": run["metric"]},
                     support_set_id=run["support_set_id"])
    return ih == run["inputs_hash"] and not extract_stale(case)


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
