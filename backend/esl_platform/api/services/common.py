"""서비스 공용: 설정 확인(503), Case 조회(404), 권한(403), 직렬화(lease_* 제거)."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.engine import Connection

from ...core.auth import Principal
from ...core.errors import DomainError, forbidden, not_found
from ...core.inputs import esl_run_stale, extract_stale  # noqa: F401 - 서비스들이 여기서 import
from ...core.repositories import cases as cases_repo
from ...core.repositories import jobs as jobs_repo
from ...core.repositories.jobs import LEASE_COLUMNS
from ...core.state_machine import QUEUED
from ..context import AppContext


def require_config_ok(ctx: AppContext) -> None:
    if not ctx.config.ok:
        raise DomainError("CONFIG_INVALID", "설정 검증 실패로 쓰기 작업을 할 수 없습니다", status=503,
                          errors=ctx.config.errors())


def require_execute(principal: Principal, project_id: str) -> None:
    if not principal.can_execute(project_id):
        raise forbidden("이 프로젝트에서 실행 권한(power 이상)이 없습니다")


def load_case(conn: Connection, case_id: str, *, for_update: bool = False) -> dict[str, Any]:
    case = cases_repo.get_case(conn, case_id, for_update=for_update)
    if case is None:
        raise not_found("CASE_NOT_FOUND", "Case 를 찾을 수 없습니다")
    return case


def load_job(conn: Connection, job_id: str, *, for_update: bool = False) -> dict[str, Any]:
    job = jobs_repo.get_job(conn, job_id, for_update=for_update)
    if job is None:
        raise not_found("JOB_NOT_FOUND", "작업을 찾을 수 없습니다")
    return job


def case_dir(ctx: AppContext, case: dict[str, Any]) -> str:
    return os.path.join(ctx.settings.storage.esl_root, case["folder_name"])


def analysis_dir(ctx: AppContext, analysis: dict[str, Any]) -> str:
    """<esl_root>/_analysis/<id> (dir_rel 은 esl_root 기준 상대경로)."""
    return os.path.join(ctx.settings.storage.esl_root, *analysis["dir_rel"].split("/"))


def require_library_config(ctx: AppContext) -> dict[str, Any]:
    require_config_ok(ctx)
    if ctx.config.library is None:
        raise DomainError("LIBRARY_CONFIG_MISSING", "라이브러리 설정(library)이 없어 등록·분석을 할 수 없습니다",
                          status=503)
    return ctx.config.library


def require_active_case(case: dict[str, Any]) -> None:
    if case["status"] != "ACTIVE":
        raise DomainError("CASE_ARCHIVED", "보관된 Case 입니다", status=409)


# ---------------------------------------------------------------- 직렬화
def case_out(ctx: AppContext, case: dict[str, Any], stage_status: dict | None = None,
             h3d_metas: dict[str, Any] | None = None) -> dict[str, Any]:
    """h3d_metas = {h3d_path: meta} (목록은 한 번에 조회해 넘김). None 이면 H3D 입력 Case 만 여기서 조회."""
    d = dict(case)
    d["input_h3d_meta"] = None
    if case.get("input_kind") == "H3D" and case.get("h3d_path"):
        if h3d_metas is not None:
            d["input_h3d_meta"] = h3d_metas.get(case["h3d_path"])
        else:
            from .uploads import h3d_meta_for

            with ctx.engine.connect() as conn:
                d["input_h3d_meta"] = h3d_meta_for(conn, case["h3d_path"])
    d["case_dir"] = case_dir(ctx, case)
    d["folder_path"] = d["case_dir"]
    if stage_status is not None:
        d["stage_status"] = stage_status
    return d


def job_out(conn: Connection, job: dict[str, Any], *, with_steps: bool = False) -> dict[str, Any]:
    d = {k: v for k, v in job.items() if k not in LEASE_COLUMNS and k not in ("queue_seq", "holds_slot",
                                                                                 "env_snapshot")}
    d["cancel_requested"] = job.get("cancel_requested_at") is not None
    d.pop("cancel_requested_at", None)
    d.pop("cancel_requested_by", None)
    params = dict(job.get("params") or {})
    params.pop("settings", None)  # 코어 설정 스냅샷은 크고 내부용
    d["params"] = params
    d["queue_position"] = None
    if job["state"] == QUEUED and job.get("queue_seq") is not None:
        from sqlalchemy import and_, func, select

        from ...core.db.tables import jobs

        d["queue_position"] = int(conn.execute(
            select(func.count()).where(and_(jobs.c.state == QUEUED, jobs.c.lane == job["lane"],
                                            jobs.c.queue_seq <= job["queue_seq"]))
        ).scalar_one())
    if with_steps:
        d["steps"] = [{k: v for k, v in s.items() if k not in ("outputs", "log_rel", "id", "job_id", "command")}
                      for s in jobs_repo.get_steps(conn, job["id"])]
    return d


def esl_run_out(case: dict[str, Any], run: dict[str, Any], conn: Connection | None = None) -> dict[str, Any]:
    d = dict(run)
    d["latest_validation_id"] = None
    if conn is not None:
        vals = cases_repo.list_validations(conn, esl_run_id=run["id"])
        d["latest_validation_id"] = vals[0]["id"] if vals else None
    d["stale"] = esl_run_stale(case, run)
    d["is_current"] = case.get("current_esl_run_id") == run["id"]
    return d


def validation_status(val: dict[str, Any]) -> str:
    """표시 상태(계약 esl_disp_primary.md §3.3): scheme 이 없으면 LEGACY(이전 판정 체계), 아니면 verdict."""
    return val["verdict"] if val.get("scheme") else "LEGACY"


def validation_out(case: dict[str, Any], run: dict[str, Any], val: dict[str, Any]) -> dict[str, Any]:
    d = dict(val)
    d["status"] = validation_status(val)
    d["stale"] = esl_run_stale(case, run) or case.get("current_esl_run_id") != run["id"]
    return d
