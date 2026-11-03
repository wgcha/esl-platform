"""일괄 실행 API 서비스(계약 esl_run_all.md §6·§8, v0.13.0).

- 시작·이어서(`start`): 첫 동작(작업 생성·② 자동 확정·건너뛰기·멈춤)까지 이 요청 안에서(RA-D-3). ② auto_321 은 put_tstar 와
  같은 순서(트랜잭션 밖 계산 → 트랜잭션 안 저장). 코어 설정 스냅샷은 체인 행에 1번(RA-D-6).
- 취소(`cancel`): 체인 CANCELED + 체인이 만든 진행 중 작업만 request_cancel(입양 작업은 그대로).
- 권한: 시작 = require_execute·require_config_ok·require_active_case, 취소 = require_execute + 시작자 또는 전역 관리자,
  조회 = Case 조회와 같음.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.exc import IntegrityError

from ...core import run_all as core
from ...core.auth import Principal
from ...core.errors import DomainError, conflict, forbidden, unprocessable
from ...core.repositories import jobs as jobs_repo
from ...core.repositories import run_all as repo
from ...core.state_machine import TERMINAL
from ...core.step_status import stage_status, step_status
from ..context import AppContext
from .common import case_dir, load_case, require_active_case, require_config_ok, require_execute

OUT_KEYS = ("id", "case_id", "from_step", "status", "cur_step", "cur_job_id", "stop_step", "stop_code", "stop_reason",
            "verdict", "job_ids", "skipped", "resumed_from_id", "created_by", "created_by_name", "canceled_by",
            "created_at", "finished_at")


def run_out(conn, run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    d = {k: run.get(k) for k in OUT_KEYS}
    d["job_ids"] = list(d["job_ids"] or [])
    d["skipped"] = list(d["skipped"] or [])
    job = jobs_repo.get_job(conn, run["cur_job_id"]) if run.get("cur_job_id") else None
    d["cur_job_state"] = job["state"] if job else None
    d["can_resume"] = run["status"] == "STOPPED" and not repo.later_running(conn, run)
    d["superseded"] = repo.superseded(conn, run)
    return d


def latest_out(conn, case_id: str) -> dict[str, Any] | None:
    return run_out(conn, repo.latest_for_case(conn, case_id))


def _extract_params(ctx: AppContext, principal: Principal):
    """CASE_EXTRACT params = services.jobs._prepare 그대로(입력 경로·include 검사·지문). h3d Case 는 마지막 추출의 hot_k·top_n."""
    from .jobs import _prepare
    from .pathmask import mask_error

    def make(conn, case: dict[str, Any]) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        if case.get("input_kind") == "H3D":
            last = jobs_repo.latest_job(conn, case["id"], "CASE_EXTRACT")
            h = ((last or {}).get("params") or {}).get("h3d") or {}
            raw = {k: h[k] for k in ("hot_k", "top_n") if h.get(k)}
        try:
            return _prepare(ctx, conn, case, "CASE_EXTRACT", raw)
        except DomainError as exc:
            raise mask_error(ctx, principal, exc) from None
    return make


def start(ctx: AppContext, principal: Principal, case_id: str, from_step: str | None = None) -> dict[str, Any]:
    from_step = from_step or "input"
    if from_step not in core.STEPS:
        raise unprocessable("INVALID_PARAMS", f"from 은 {list(core.STEPS)} 중 하나입니다")
    with ctx.engine.connect() as conn:
        pre = load_case(conn, case_id)
    require_execute(principal, pre["project_id"])
    require_config_ok(ctx)
    require_active_case(pre)
    auto = None
    if not pre.get("current_support_set_id") and pre.get("extract_summary"):
        # ② 자동 확정 후보(지지 세트 없음) — auto_321 은 트랜잭션 밖(put_tstar 와 같은 순서). 쓰이지 않으면 버림
        auto = core.prepare_auto(case_dir(ctx, pre), ctx.config.core, (pre["extract_summary"] or {}).get("job_id"))
    with ctx.engine.begin() as conn:
        case = load_case(conn, case_id, for_update=True)
        require_execute(principal, case["project_id"])
        require_config_ok(ctx)
        require_active_case(case)
        if repo.running_for_case(conn, case_id) is not None:
            raise conflict("RUN_ALL_ACTIVE", "이미 일괄 실행 중입니다")
        idx = core.STEPS.index(from_step)
        ss = step_status(case, stage_status(conn, case))
        missing = [s for s in core.STEPS[:idx] if ss[s]["state"] != "done"]
        if missing:
            raise conflict("PREREQUISITE_MISSING", "앞 단계가 먼저 필요합니다", missing=missing)
        prev = repo.latest_for_case(conn, case_id)
        ts = case.get("tstar") or {}
        prev_user = ({"metric": ts.get("metric"), "frame_index": ts.get("frame_index")}
                     if ts.get("source") == "user" else None)
        try:
            with conn.begin_nested():
                run = repo.insert_run(conn, case_id=case_id, project_id=case["project_id"], from_step=from_step,
                                      core_settings=copy.deepcopy(ctx.config.core or {}),
                                      created_by=principal.user_id, created_by_name=principal.display_name,
                                      prev_user_tstar=prev_user,
                                      resumed_from_id=prev["id"] if prev and prev["status"] == "STOPPED" else None)
        except IntegrityError:
            raise conflict("RUN_ALL_ACTIVE", "이미 일괄 실행 중입니다") from None
        env = core.Env(esl_root=ctx.settings.storage.esl_root, auto=auto,
                       extract_params=_extract_params(ctx, principal))
        run = core.advance(conn, run, case, env, idx)
        return run_out(conn, run)


def get_latest(ctx: AppContext, case_id: str) -> dict[str, Any] | None:
    with ctx.engine.connect() as conn:
        load_case(conn, case_id)
        return latest_out(conn, case_id)


def list_runs(ctx: AppContext, case_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        load_case(conn, case_id)
        return [run_out(conn, r) for r in repo.list_for_case(conn, case_id, limit)]


def cancel(ctx: AppContext, principal: Principal, case_id: str) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        case = load_case(conn, case_id)
        require_execute(principal, case["project_id"])
        run = repo.running_for_case(conn, case_id)
        if run is None:
            raise conflict("RUN_ALL_NOT_RUNNING", "실행 중인 일괄 실행이 없습니다")
        if not principal.is_global_admin and run["created_by"] != principal.user_id:
            raise forbidden("다른 사용자가 시작한 일괄 실행은 전역 관리자만 취소할 수 있습니다")
        # 잠금 순서: 작업 → 체인 행(워커 종료 훅과 같은 순서)
        job = jobs_repo.get_job(conn, run["cur_job_id"], for_update=True) if run.get("cur_job_id") else None
        run = repo.get_run(conn, run["id"], for_update=True)
        if run is None or run["status"] != "RUNNING":
            raise conflict("RUN_ALL_NOT_RUNNING", "실행 중인 일괄 실행이 없습니다")
        if run.get("cur_job_id") and (job is None or job["id"] != run["cur_job_id"]):
            job = jobs_repo.get_job(conn, run["cur_job_id"], for_update=True)
        run = repo.finish(conn, run, "CANCELED", canceled_by=principal.user_id, stop_step=run.get("cur_step"),
                          stop_code="RUN_ALL_CANCELED", stop_reason=core.stop_reason("RUN_ALL_CANCELED",
                                                                                     run.get("cur_step"), {}))
        if job is not None and job.get("run_all_id") == run["id"] and job["state"] not in TERMINAL:
            jobs_repo.request_cancel(conn, job["id"], principal.user_id)
        return run_out(conn, run)
