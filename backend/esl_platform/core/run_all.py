"""ESL 생성 Case 일괄 실행(RUN_ALL, 계약 esl_run_all.md §3~§7, v0.13.0).

- `evaluate(ss, step, facts)`: 순수 규칙(§4) — 화면 4단계 상태 + 사실(가드·판정)로 그 단계의 동작 1개.
  Skip·ConfirmTstar 는 호출자(`advance`)가 이어서 평가하고, Create·Adopt·Stop·Done 에서 끝난다.
- `advance(conn, run, case, env, idx)`: 체인 행·Case 잠금 아래에서 단계 idx 부터 평가·실행(API 시작·이어서, 워커 훅 공용).
- `on_job_end(conn, job, prep)`: 작업 종료 훅 — `jobs_repo.release`·`interrupt`·`request_cancel`(즉시 CANCELED) 안에서
  종료 전이와 같은 트랜잭션으로 불린다(RA-D-2). 이 작업을 기다리는 RUNNING 체인이 없으면 아무것도 안 함(멱등).
  잠금 순서: 작업(호출자) → Case → 체인 행. SUCCEEDED 인데 prep(esl_root) 이 없으면 진행하지 않고 끊김 복구(워커 리퍼 루프 —
  `recover`)가 이어 간다.
- 새 작업 종류·새 코어 단계 없음: CASE_EXTRACT·ESL_SOLVE·VALIDATE 작업과 ② 확정 공용 코드(core.tstar_confirm)를 부른다.
- 라이브러리 등록은 하지 않는다(RA-D-8): ④ PASS → DONE.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import and_, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from . import core_outputs as co
from . import job_params, tstar_confirm
from .db.tables import jobs as jobs_t
from .errors import DomainError, conflict
from .repositories import cases as cases_repo
from .repositories import jobs as jobs_repo
from .repositories import row_dict
from .repositories import run_all as repo
from .state_machine import CANCELED, FAILED, INTERRUPTED, SUCCEEDED, TERMINAL

log = logging.getLogger("esl_platform.run_all")

STEPS = ("input", "tstar", "esl", "validate")
STEP_JOB = {"input": "CASE_EXTRACT", "esl": "ESL_SOLVE", "validate": "VALIDATE"}
JOB_STEP = {v: k for k, v in STEP_JOB.items()}
STEP_LABEL = {"input": "① 입력", "tstar": "② t*·지지점", "esl": "③ ESL", "validate": "④ 검증"}
MISSING_LABEL = {"extract": "① 입력(추출)", "input": "① 입력(추출)", "tstar": "② t*", "support_set": "② 지지점",
                 "disp_frame": "t* 프레임 변위", "esl_run": "③ ESL 결과", "current_esl_run": "현재 ③ ESL 결과",
                 "fresh_esl_run": "최신 ③ ESL 결과", "esl": "③ ESL", "validate": "④ 검증"}

# §7 멈춤 코드 → 화면 문구(백엔드가 stop_reason.message 로 완성해 보낸다 — 프런트 문구 사전 없음)
STOP_MESSAGES = {
    "TSTAR_REVIEW_REQUIRED": "t* 확인이 필요합니다 — ②에서 후보를 보고 [t* 확정]",
    "SUPPORT_AUTO_BLOCKED": "지지점을 자동으로 정하지 못했습니다 — ②에서 사유 확인",
    "SUPPORT_AUTO_ERROR": "지지점 자동 선택 중 오류",
    "PREREQUISITE_MISSING": "앞 단계가 필요합니다",
    "STEP_FAILED": "작업 실패",
    "STEP_INTERRUPTED": "워커가 끊겨 작업이 중단되었습니다",
    "VALIDATION_FAIL": "검증 FAIL — 원인 확인 후 ②·③ 조건을 바꿔 [이어서 실행]",
    "VALIDATION_UNDETERMINED": "검증 판정 불가",
    "CASE_CHANGED": "실행 중 Case 가 바뀌었습니다",
    "CASE_ARCHIVED": "보관된 Case 입니다",
    "JOB_CANCELED": "작업이 취소되었습니다",
    "RUN_ALL_CANCELED": "일괄 실행을 취소했습니다",
    "RUN_ALL_ERROR": "일괄 실행 내부 오류 — 관리자 확인",
}
REASON_TEXT = {
    "TSTAR_ADJUSTED": "1순위 시점이 변위 추출 프레임에 없어 다른 후보로 바뀌었습니다",
    "TSTAR_METRIC_ERROR": "t* 지표 결과를 읽을 수 없습니다",
    "FRAME_NOT_CANDIDATE": "현재 t* 가 후보 프레임이 아닙니다",
    "USER_TSTAR_CHANGED": "직접 고른 t*(frame {prev})와 새 자동 t*(frame {cur})가 다릅니다",
}


# ---------------------------------------------------------------- 동작
@dataclass
class Action:
    kind: str                      # skip | create | adopt | confirm | stop | done
    step: str
    job_type: str | None = None
    job_id: str | None = None
    code: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    verdict: str | None = None


def Skip(step: str) -> Action:            # noqa: N802 - 계약 표기(§3)
    return Action("skip", step)


def Create(step: str) -> Action:          # noqa: N802
    return Action("create", step, job_type=STEP_JOB[step])


def Adopt(step: str, job_id: str) -> Action:   # noqa: N802
    return Action("adopt", step, job_type=STEP_JOB[step], job_id=job_id)


def ConfirmTstar() -> Action:             # noqa: N802
    return Action("confirm", "tstar")


def Stop(step: str, code: str, **detail: Any) -> Action:   # noqa: N802
    return Action("stop", step, code=code, detail=detail)


def Done(verdict: str, **detail: Any) -> Action:            # noqa: N802
    return Action("done", "validate", verdict=verdict, detail={"verdict": verdict, **detail})


def reason(code: str, **kw: Any) -> dict[str, str]:
    return {"code": code, "message": REASON_TEXT[code].format(**kw) if kw else REASON_TEXT[code]}


def evaluate(ss: dict[str, dict[str, Any]], step: str, facts: Any) -> Action:
    """§4 규칙. ss = step_status{input, tstar, esl, validate}, facts = guard_reasons()·g4_reasons()·blocked_problems()·
    verdict() 를 가진 객체(필요할 때만 부름 — 파일·DB 읽기는 facts 안)."""
    s = ss[step]
    st = s.get("state")
    if step in ("input", "esl"):
        if st == "done":
            return Skip(step)
        if st == "running" and s.get("job_id"):
            return Adopt(step, s["job_id"])
        return Create(step)
    if step == "tstar":
        code = (s.get("reason") or {}).get("code")
        if st == "done":
            r = facts.g4_reasons()
            return Stop(step, "TSTAR_REVIEW_REQUIRED", reasons=r) if r else Skip(step)
        if st == "failed" and code == "SUPPORT_AUTO_BLOCKED":
            return Stop(step, "SUPPORT_AUTO_BLOCKED", problems=facts.blocked_problems())
        if st == "none" and code == "TSTAR_NOT_CONFIRMED":
            r = facts.guard_reasons()
            return Stop(step, "TSTAR_REVIEW_REQUIRED", reasons=r) if r else ConfirmTstar()
        return Stop(step, "PREREQUISITE_MISSING", missing=["extract"])
    # validate
    if st == "done":
        v = facts.verdict()
        if v is None:
            return Create(step)
        if v["verdict"] == "PASS":
            return Done("PASS", validation_id=v["validation_id"])
        if v["verdict"] == "FAIL":
            return Stop(step, "VALIDATION_FAIL", verdict="FAIL", validation_id=v["validation_id"],
                        fail_reasons=v.get("fail_reasons") or [])
        return Stop(step, "VALIDATION_UNDETERMINED", verdict=v["verdict"], validation_id=v["validation_id"],
                    undetermined_reason=v.get("undetermined_reason"))
    if st == "running" and s.get("job_id"):
        return Adopt(step, s["job_id"])
    return Create(step)


def stop_message(code: str, step: str | None, detail: dict[str, Any]) -> str:
    base = STOP_MESSAGES.get(code, code)
    if code == "TSTAR_REVIEW_REQUIRED":
        lines = [r.get("message") or r.get("code") for r in detail.get("reasons") or []]
        return "\n".join([base, *lines])
    if code == "SUPPORT_AUTO_BLOCKED":
        lines = [str(p.get("message") or p.get("code")) for p in detail.get("problems") or [] if isinstance(p, dict)]
        return "\n".join([base, *lines])
    if code == "SUPPORT_AUTO_ERROR":
        return f"{base}: {detail.get('code') or ''} {detail.get('message') or ''}".rstrip()
    if code == "PREREQUISITE_MISSING":
        miss = [MISSING_LABEL.get(m, m) for m in detail.get("missing") or []]
        if miss:
            return f"{base}: {', '.join(miss)}"
        return f"{base}: {detail['message']}" if detail.get("message") else base
    if code == "STEP_FAILED":
        lbl = STEP_LABEL.get(step or "", step or "")
        return f"{lbl} 작업 실패: {detail.get('failure_code') or ''} {detail.get('failure_message') or ''}".rstrip()
    if code == "VALIDATION_UNDETERMINED":
        return f"{base} — {detail.get('undetermined_reason') or ''}".rstrip(" —")
    if code == "RUN_ALL_ERROR" and detail.get("message"):
        return f"{base}: {detail['message']}"
    return base


def stop_reason(code: str, step: str | None, detail: dict[str, Any]) -> dict[str, Any]:
    return {"message": stop_message(code, step, detail), "detail": _jsonable(detail)}


# ---------------------------------------------------------------- 실행 환경(API·워커)
@dataclass
class AutoPrep:
    """트랜잭션 밖에서 미리 계산한 ② auto_321 결과(추출 작업 id 기준). value = (res, node_id, x0)."""
    extract_job_id: str | None
    value: tuple | None = None
    error: tuple[str, str] | None = None        # CoreError (code, message)
    missing: str | None = None                  # model.npz 없음 등


@dataclass
class Env:
    esl_root: str
    auto: AutoPrep | None = None
    # CASE_EXTRACT params(API 만 — 입력 경로·include 검사는 설정이 필요). 워커 훅은 None → PREREQUISITE_MISSING
    extract_params: Callable[[Connection, dict[str, Any]], dict[str, Any]] | None = None

    def cdir(self, case: dict[str, Any]) -> str:
        return os.path.join(self.esl_root, case["folder_name"])


@dataclass
class WorkerPrep:
    """executor 가 release 로 넘기는 값(RA-D-2·§4.2): esl_root + (① 성공 직후) ② auto_321 사전 계산."""
    esl_root: str
    auto: AutoPrep | None = None


def compute_auto(cdir: str, core_cfg: dict[str, Any] | None) -> tuple:
    """모델 로드 + 코어 auto_321(트랜잭션 밖). 예외: core_adapter.CoreError, co.OutputMissing·OSError·ValueError·KeyError."""
    from esl_worker import core_adapter

    nid, x0 = co.model_nodes(cdir)
    return core_adapter.auto_support(x0, core_adapter.support_check_settings(core_cfg or {})), nid, x0


def prepare_auto(cdir: str, core_cfg: dict[str, Any] | None, extract_job_id: str | None) -> AutoPrep:
    from esl_worker import core_adapter

    try:
        return AutoPrep(extract_job_id, value=compute_auto(cdir, core_cfg))
    except core_adapter.CoreError as exc:
        return AutoPrep(extract_job_id, error=(exc.code, exc.message))
    except (co.OutputMissing, OSError, ValueError, KeyError) as exc:
        return AutoPrep(extract_job_id, missing=f"{type(exc).__name__}: {exc}"[:300])


class _Facts:
    def __init__(self, conn: Connection, case: dict[str, Any], run: dict[str, Any], env: Env) -> None:
        self.conn, self.case, self.run, self.env = conn, case, run, env
        self._info: Any = None

    def info(self) -> dict[str, Any] | None:
        if self._info is None:
            try:
                self._info = co.tstar_info(self.env.cdir(self.case)) if self.case.get("extract_summary") else False
            except (co.OutputMissing, OSError, ValueError, KeyError, TypeError):
                self._info = False
        return self._info or None

    def g4_reasons(self) -> list[dict[str, str]]:
        prev = self.run.get("prev_user_tstar")
        ts = self.case.get("tstar") or {}
        if prev and (prev.get("metric"), prev.get("frame_index")) != (ts.get("metric"), ts.get("frame_index")):
            return [reason("USER_TSTAR_CHANGED", prev=prev.get("frame_index"), cur=ts.get("frame_index"))]
        return []

    def guard_reasons(self) -> list[dict[str, str]]:
        ts = self.case.get("tstar") or {}
        info = self.info()
        blk = (info or {}).get("metrics", {}).get(ts.get("metric")) if info else None
        out: list[dict[str, str]] = []
        if blk is None or blk.get("error"):                                   # G1
            r = reason("TSTAR_METRIC_ERROR")
            if blk and blk.get("error"):
                r["message"] += f": {blk['error']}"
            out.append(r)
        else:
            cands = blk.get("candidates") or []
            c0 = cands[0] if cands else None
            if c0 is None or c0.get("in_D") is False or c0.get("frame_index") != ts.get("frame_index"):   # G2
                out.append(reason("TSTAR_ADJUSTED"))
            try:                                                              # G3
                tstar_confirm.select_candidate(info, ts.get("metric"), ts.get("frame_index"))
            except DomainError:
                out.append(reason("FRAME_NOT_CANDIDATE"))
        return out + self.g4_reasons()                                        # G4

    def blocked_problems(self) -> list[Any]:
        auto = (self.case.get("tstar") or {}).get("support_auto") or {}
        return list(auto.get("problems") or [])

    def verdict(self) -> dict[str, Any] | None:
        rid = self.case.get("current_esl_run_id")
        vals = cases_repo.list_validations(self.conn, esl_run_id=rid) if rid else []
        if not vals:
            return None
        v = vals[0]
        return {"verdict": v["verdict"], "validation_id": v["id"], "fail_reasons": v.get("fail_reasons") or [],
                "undetermined_reason": v.get("undetermined_reason")}


# ---------------------------------------------------------------- 진행
def _stop(conn: Connection, run: dict[str, Any], step: str, code: str, detail: dict[str, Any]) -> dict[str, Any]:
    status = "CANCELED" if code in ("JOB_CANCELED", "RUN_ALL_CANCELED") else "STOPPED"
    return repo.finish(conn, run, status, stop_step=step, stop_code=code, stop_reason=stop_reason(code, step, detail),
                       verdict=detail.get("verdict") if code.startswith("VALIDATION_") else run.get("verdict"))


def _active_job(conn: Connection, case_id: str, job_type: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(jobs_t).where(and_(
        jobs_t.c.case_id == case_id, jobs_t.c.job_type == job_type, jobs_t.c.state.notin_(list(TERMINAL))))
        .order_by(jobs_t.c.created_at.desc()).limit(1)).first())


def _params_for(conn: Connection, run: dict[str, Any], case: dict[str, Any], env: Env, job_type: str) -> dict[str, Any]:
    if job_type == "CASE_EXTRACT":
        if env.extract_params is None:
            raise conflict("PREREQUISITE_MISSING", "① 입력(추출)이 필요합니다 — [이어서 실행]", missing=["extract"])
        return env.extract_params(conn, case)
    if job_type == "ESL_SOLVE":
        return job_params.esl_solve_params(conn, run["core_settings"], env.cdir(case), case)
    return job_params.run_ref_params(conn, run["core_settings"], case, "VALIDATE", case.get("current_esl_run_id"))


def _wait(conn: Connection, run: dict[str, Any], step: str, job: dict[str, Any], adopted: bool) -> dict[str, Any]:
    ids = list(run.get("job_ids") or []) + [{"step": step, "job_id": job["id"], "adopted": bool(adopted)}]
    return repo.update_run(conn, run["id"], cur_step=step, cur_job_id=job["id"], job_ids=ids)


def _create(conn: Connection, run: dict[str, Any], case: dict[str, Any], env: Env, step: str,
            job_type: str) -> dict[str, Any]:
    try:
        params = _params_for(conn, run, case, env, job_type)
    except DomainError as exc:
        extra = _jsonable(exc.extra)
        code = "SUPPORT_AUTO_BLOCKED" if extra.get("support_blocked") else "PREREQUISITE_MISSING"
        return _stop(conn, run, step, code, {"code": exc.code, "message": exc.message, **extra})
    except (co.OutputMissing, OSError, ValueError) as exc:
        return _stop(conn, run, step, "PREREQUISITE_MISSING", {"code": "PREREQUISITE_MISSING",
                                                                 "message": f"{type(exc).__name__}: {exc}"[:300]})
    adopted = False
    try:
        with conn.begin_nested():
            job = jobs_repo.insert_job(conn, case_id=case["id"], project_id=case["project_id"], job_type=job_type,
                                       params=params, created_by=run["created_by"],
                                       created_by_name=run["created_by_name"], run_all_id=run["id"],
                                       h3d=job_type == "CASE_EXTRACT" and case.get("input_kind") == "H3D")
    except IntegrityError:
        # 같은 Case·종류 비종료 작업이 이미 있음(사람이 먼저 누름 등) → 그 작업을 입양
        job = _active_job(conn, case["id"], job_type)
        if job is None:
            return _stop(conn, run, step, "PREREQUISITE_MISSING",
                         {"code": "CASE_JOB_BUSY", "message": "같은 종류의 작업과 겹쳤습니다 — [이어서 실행]"})
        adopted = True
    if job_type == "CASE_EXTRACT" and not adopted and params.get("input_fingerprint"):
        cases_repo.update_case(conn, case["id"], None, input_fingerprint=params["input_fingerprint"])
    return _wait(conn, run, step, job, adopted)


def _get_auto(case: dict[str, Any], run: dict[str, Any], env: Env) -> AutoPrep:
    ex_id = (case.get("extract_summary") or {}).get("job_id")
    if env.auto is not None and env.auto.extract_job_id == ex_id:
        return env.auto
    return prepare_auto(env.cdir(case), run["core_settings"], ex_id)     # 사전 계산이 없거나 낡음 → 여기서(드묾)


def _confirm(conn: Connection, run: dict[str, Any], case: dict[str, Any], env: Env
             ) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """② 자동 확정(가드 통과 뒤). 반환 (case, 멈춤 행 또는 None)."""
    ts = case["tstar"]
    info = co.tstar_info(env.cdir(case))
    hit = tstar_confirm.select_candidate(info, ts["metric"], ts["frame_index"])
    auto = None
    if not case.get("current_support_set_id"):
        ap = _get_auto(case, run, env)
        if ap.error:
            return case, _stop(conn, run, "tstar", "SUPPORT_AUTO_ERROR", {"code": ap.error[0], "message": ap.error[1]})
        if ap.value is None:
            return case, _stop(conn, run, "tstar", "PREREQUISITE_MISSING",
                               {"missing": ["extract"], "message": ap.missing or "모델 산출물(01_extract/model.npz)이 없습니다"})
        auto = ap.value
    tstar = tstar_confirm.tstar_from(hit, ts["metric"], source="auto",
                                     confirmed={"by": "run_all", "run_all_id": run["id"], "user_id": run["created_by"]})
    case = tstar_confirm.store(conn, case, tstar, auto, created_by=run["created_by"], version=None)
    return case, None


def advance(conn: Connection, run: dict[str, Any], case: dict[str, Any], env: Env, idx: int) -> dict[str, Any]:
    """체인 행 RUNNING·Case 잠금 아래에서 단계 idx 부터. 반환 = 갱신된 체인 행(작업 대기 RUNNING 또는 종료)."""
    from .step_status import stage_status, step_status

    confirmed = False
    while idx < len(STEPS):
        step = STEPS[idx]
        if case["status"] != "ACTIVE":
            return _stop(conn, run, step, "CASE_ARCHIVED", {})
        ss = step_status(case, stage_status(conn, case))
        act = evaluate(ss, step, _Facts(conn, case, run, env))
        if act.kind == "confirm" and confirmed:            # 확정 뒤에도 그대로면 멈춤(무한 반복 방지)
            act = Stop(step, "TSTAR_REVIEW_REQUIRED", reasons=[reason("FRAME_NOT_CANDIDATE")])
        if act.kind == "skip":
            run = repo.update_run(conn, run["id"], cur_step=step,
                                  skipped=list(run.get("skipped") or []) + [{"step": step, "state": "done"}])
            idx += 1
            continue
        if act.kind == "confirm":
            case, stopped = _confirm(conn, run, case, env)
            if stopped is not None:
                return stopped
            confirmed = True
            sa = (case.get("tstar") or {}).get("support_auto") or {}
            if sa.get("status") == "BLOCKED":
                return _stop(conn, run, step, "SUPPORT_AUTO_BLOCKED", {"problems": list(sa.get("problems") or [])})
            ts = case["tstar"]
            run = repo.update_run(conn, run["id"], cur_step=step, skipped=list(run.get("skipped") or []) + [
                {"step": step, "state": "auto_confirmed", "metric": ts.get("metric"),
                 "frame_index": ts.get("frame_index"), "support": sa.get("status")}])
            idx += 1
            continue
        if act.kind == "create":
            return _create(conn, run, case, env, step, act.job_type)
        if act.kind == "adopt":
            job = jobs_repo.get_job(conn, act.job_id)
            if job is None or job["state"] in TERMINAL:      # 방금 끝남 → 다시 평가
                continue
            return _wait(conn, run, step, job, True)
        if act.kind == "done":
            return repo.finish(conn, run, "DONE", verdict="PASS", cur_step=step, stop_step=None, stop_code=None,
                               stop_reason={"message": "④ 검증 PASS — 라이브러리 등록은 ④에서",
                                            "detail": _jsonable(act.detail)})
        return _stop(conn, run, act.step, act.code or "PREREQUISITE_MISSING", act.detail)
    return _stop(conn, run, STEPS[-1], "PREREQUISITE_MISSING", {"missing": ["validate"]})


# ---------------------------------------------------------------- 작업 종료 훅(RA-D-2)
def on_job_end(conn: Connection, job: dict[str, Any] | None, prep: WorkerPrep | None = None) -> dict[str, Any] | None:
    """종료 전이와 같은 트랜잭션. 반환 = 갱신된 체인 행(관계없으면 None). 예외는 호출자(`safe_on_job_end`)가 막는다."""
    if not job or not job.get("case_id") or job.get("job_type") not in JOB_STEP or job.get("state") not in TERMINAL:
        return None
    if repo.waiting_on(conn, job["id"]) is None:
        return None
    if job["state"] == SUCCEEDED and prep is None:
        return None                     # esl_root 모름 → 끊김 복구(워커 리퍼 루프)가 이어 간다
    case = cases_repo.get_case(conn, job["case_id"], for_update=True)
    run = repo.waiting_on(conn, job["id"], for_update=True)
    if run is None or case is None:
        return None
    step = JOB_STEP[job["job_type"]]
    st = job["state"]
    base = {"job_id": job["id"], "job_type": job["job_type"], "failure_code": job.get("failure_code"),
            "failure_message": job.get("failure_message")}
    if st == FAILED:
        return _stop(conn, run, step, "STEP_FAILED", base)
    if st == INTERRUPTED:
        return _stop(conn, run, step, "STEP_INTERRUPTED", base)
    if st == CANCELED:
        return _stop(conn, run, step, "JOB_CANCELED", {"job_id": job["id"], "job_type": job["job_type"]})
    if job["job_type"] == "CASE_EXTRACT" and (case.get("extract_summary") or {}).get("job_id") != job["id"]:
        return _stop(conn, run, "tstar", "CASE_CHANGED", {"job_id": job["id"]})
    env = Env(esl_root=prep.esl_root, auto=prep.auto)
    nxt = STEPS.index(step) if step == "validate" else STEPS.index(step) + 1
    return advance(conn, run, case, env, nxt)


def safe_on_job_end(conn: Connection, job: dict[str, Any] | None,
                    prep: WorkerPrep | None = None) -> dict[str, Any] | None:
    """훅 오류가 종료 전이(작업 상태 기록)를 막지 않게 savepoint 로 감싼다. 실패하면 체인을 STOPPED RUN_ALL_ERROR.
    반환 = 갱신된 체인 행(진행·RUN_ALL_ERROR 멈춤), 관계없거나 오류 기록도 실패하면 None."""
    if not job or not job.get("case_id") or job.get("job_type") not in JOB_STEP:
        return None
    try:
        with conn.begin_nested():
            return on_job_end(conn, job, prep)
    except Exception as exc:  # noqa: BLE001 - 작업 종료 기록이 우선
        log.exception("일괄 실행 훅 오류(작업 %s)", job.get("id"))
        try:
            with conn.begin_nested():
                run = repo.waiting_on(conn, job["id"], for_update=True)
                if run is not None:
                    return _stop(conn, run, JOB_STEP[job["job_type"]], "RUN_ALL_ERROR",
                                 {"job_id": job["id"], "message": f"{type(exc).__name__}: {exc}"[:300]})
        except Exception:  # noqa: BLE001
            log.exception("일괄 실행 오류 기록 실패(작업 %s)", job.get("id"))
        return None


def recover(engine, esl_root: str, limit: int = 20) -> list[str]:
    """끊김 복구(§5): RUNNING 인데 cur_job_id 작업이 이미 종료된 체인마다 훅 1회(행 잠금으로 중복 없음). 반환 = 처리한 체인 id.
    훅은 `safe_on_job_end` 로 부른다 — 훅이 예외를 내면 체인을 STOPPED RUN_ALL_ERROR 로 끝내 주기마다 같은 예외가 반복되지 않게."""
    with engine.connect() as conn:
        rows = repo.orphaned(conn, limit)
    done: list[str] = []
    for r in rows:
        try:
            with engine.begin() as conn:
                job = jobs_repo.get_job(conn, r["cur_job_id"], for_update=True)
                out = safe_on_job_end(conn, job, WorkerPrep(esl_root=esl_root))
                if out is not None:
                    done.append(r["id"])
        except Exception:  # noqa: BLE001 - 다음 주기에 다시
            log.exception("일괄 실행 끊김 복구 오류(체인 %s)", r["id"])
    return done


def _jsonable(o: Any) -> Any:
    import json

    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x)))
