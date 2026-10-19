"""Case 서비스: 생성·조회·수정·보관, 단계 상태, t*, 미리보기, 지지점 세트(동기 API)."""

from __future__ import annotations

import json
import os
import shutil
from typing import Any

import numpy as np
from sqlalchemy.exc import IntegrityError

from esl_worker import core_adapter

from ...core import core_outputs as co
from ...core.auth import Principal
from ...core.errors import DomainError, conflict, not_found, unprocessable
from ...core.inputs import fingerprint
from ...core.paths import check_input_path
from ...core.repositories import cases as cases_repo
from ...core.repositories import jobs as jobs_repo
from ...core.repositories.cases import VersionConflict
from ...core.state_machine import FAILED, INTERRUPTED, QUEUED, RUNNING, SUCCEEDED
from ..context import AppContext
from . import system
from .common import (
    case_dir,
    case_out,
    esl_run_out,
    esl_run_stale,
    extract_stale,
    load_case,
    require_active_case,
    require_config_ok,
    require_execute,
)

ACTIVE_STATES = (QUEUED, RUNNING)


def _projects(ctx: AppContext, principal: Principal, token: str | None, rid: str) -> list[dict]:
    return ctx.auth.projects(principal, token, rid)


# ---------------------------------------------------------------- 단계 상태
def stage_status(conn, case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest = {jt: jobs_repo.latest_job(conn, case["id"], jt) for jt in ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE",
                                                                         "EXPORT")}

    def st(state: str, job: dict | None = None) -> dict[str, Any]:
        return {"state": state, "job_id": job["id"] if job else None}

    def failed(j: dict | None) -> bool:
        return j is not None and j["state"] in (FAILED, INTERRUPTED)

    out: dict[str, dict[str, Any]] = {}
    ex = latest["CASE_EXTRACT"]
    ex_stale = extract_stale(case)
    if ex and ex["state"] in ACTIVE_STATES:
        out["1"] = st("running", ex)
        out["2"] = st("running", ex)
    else:
        if case.get("extract_summary"):
            out["1"] = st("stale" if ex_stale else "done", ex)
        else:
            out["1"] = st("failed" if failed(ex) else "none", ex)
        if case.get("tstar"):
            out["2"] = st("stale" if ex_stale else "done")
        else:
            out["2"] = st("failed" if failed(ex) else "none", ex)
    out["3"] = st(("stale" if ex_stale else "done") if case.get("current_support_set_id") else "none")

    run = cases_repo.get_esl_run(conn, case["current_esl_run_id"]) if case.get("current_esl_run_id") else None
    run_stale = esl_run_stale(case, run) if run else False
    es = latest["ESL_SOLVE"]
    if es and es["state"] in ACTIVE_STATES:
        out["4"] = st("running", es)
    elif run:
        out["4"] = st("stale" if run_stale else "done", es)
    else:
        out["4"] = st("failed" if failed(es) else "none", es)

    va = latest["VALIDATE"]
    vals = cases_repo.list_validations(conn, esl_run_id=run["id"]) if run else []
    if va and va["state"] in ACTIVE_STATES:
        out["5"] = st("running", va)
    elif vals:
        out["5"] = st("stale" if run_stale else "done", va)
    else:
        out["5"] = st("failed" if failed(va) else "none", va)

    ep = latest["EXPORT"]
    if ep and ep["state"] in ACTIVE_STATES:
        out["6"] = st("running", ep)
    elif ep and ep["state"] == SUCCEEDED and run and (ep["params"] or {}).get("esl_run_id") == run["id"]:
        out["6"] = st("stale" if run_stale else "done", ep)
    else:
        out["6"] = st("failed" if failed(ep) else "none", ep)
    return out


# ---------------------------------------------------------------- 생성
def _check_part(ctx: AppContext, rad: str, results: str, part_title: str) -> tuple[dict, dict | None, list[str]]:
    info = system.inspect_rad(ctx, rad, part_title)
    for p in info["problems"]:
        if p.startswith("PART_NOT_FOUND"):
            raise unprocessable("PART_NOT_FOUND", f"대상 파트 '{part_title}' 가 rad 에 없습니다")
        if p.startswith("PART_AMBIGUOUS"):
            raise unprocessable("PART_AMBIGUOUS", f"대상 파트 '{part_title}' 가 rad 에 여러 개입니다")
    done, _ = system.read_done(results)
    target = info["target_part"]
    if target and done and done.get("part_id") is not None:
        try:
            dpid = int(done["part_id"])
        except (TypeError, ValueError):
            dpid = None
        if dpid is not None and dpid != int(target["id"]):
            raise unprocessable("PART_MISMATCH", f"결과 폴더(done.json part_id={dpid})와 rad 파트 id "
                                f"{target['id']} 가 다릅니다", rad_part_id=int(target["id"]), results_part_id=dpid)
    return info, done, [i["path"] for i in info["includes"]]


def create_case(ctx: AppContext, principal: Principal, token: str | None, rid: str, body) -> dict[str, Any]:
    projects = _projects(ctx, principal, token, rid)
    if body.project_id not in {p["id"] for p in projects}:
        raise not_found("PROJECT_NOT_FOUND", "프로젝트를 찾을 수 없습니다")
    require_execute(principal, body.project_id)
    require_config_ok(ctx)
    s = ctx.settings
    rad = check_input_path(s, body.rad_path, "RAD")
    results = check_input_path(s, body.results_dir, "RESULTS")
    part_title = body.part_title or (ctx.config.core or {}).get("case", {}).get("part_title")
    if not part_title:
        raise unprocessable("INVALID_PARAMS", "part_title 이 필요합니다")
    cdir = os.path.join(s.storage.esl_root, body.folder_name)
    with ctx.engine.connect() as conn:
        dup = [c for c in cases_repo.list_cases(conn, body.project_id, "ACTIVE") if c["title"] == body.title]
        if dup:
            raise conflict("CASE_NAME_EXISTS", "같은 제목의 Case 가 있습니다")
        if any(c["folder_name"].lower() == body.folder_name.lower() for c in cases_repo.list_cases(conn, None, None)):
            raise conflict("FOLDER_EXISTS", "같은 폴더 이름의 Case 가 있습니다")
    if os.path.lexists(cdir):
        raise conflict("FOLDER_EXISTS", "산출물 폴더가 이미 있습니다")
    info, done, includes = _check_part(ctx, rad, results, part_title)
    fp = fingerprint(rad, results, includes)
    target = info["target_part"]
    os.makedirs(s.storage.esl_root, exist_ok=True)
    try:
        os.makedirs(cdir, exist_ok=False)
    except FileExistsError:
        raise conflict("FOLDER_EXISTS", "산출물 폴더가 이미 있습니다") from None
    try:
        with ctx.engine.begin() as conn:
            case = cases_repo.insert_case(
                conn, project_id=body.project_id, folder_name=body.folder_name, title=body.title, status="ACTIVE",
                rad_path=rad, results_dir=results, h3d_path=(done or {}).get("h3d"), input_fingerprint=fp,
                part_title=part_title, part_id=int(target["id"]) if target else None,
                created_by=principal.user_id, created_by_name=principal.display_name,
            )
        with open(os.path.join(cdir, "case.json"), "w", encoding="utf-8") as fh:
            json.dump({"id": case["id"], "project_id": case["project_id"], "title": case["title"],
                       "rad_path": rad, "results_dir": results, "h3d_path": case["h3d_path"],
                       "created_at": case["created_at"].isoformat()}, fh, ensure_ascii=False, indent=2)
    except IntegrityError as exc:
        shutil.rmtree(cdir, ignore_errors=True)
        if "folder" in str(exc.orig if hasattr(exc, "orig") else exc):
            raise conflict("FOLDER_EXISTS", "같은 폴더 이름(대소문자 무시)의 Case 가 있습니다") from None
        raise conflict("CASE_NAME_EXISTS", "같은 제목 또는 폴더의 Case 가 있습니다") from None
    except BaseException:
        shutil.rmtree(cdir, ignore_errors=True)
        raise
    return case_out(ctx, case, None)


def list_cases(ctx: AppContext, project_id: str | None, status: str | None) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        return [case_out(ctx, c) for c in cases_repo.list_cases(conn, project_id, status)]


def get_case(ctx: AppContext, case_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
        return case_out(ctx, case, stage_status(conn, case))


def patch_case(ctx: AppContext, principal: Principal, case_id: str, body) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        case = load_case(conn, case_id, for_update=True)
        require_execute(principal, case["project_id"])
        require_config_ok(ctx)
        require_active_case(case)
        vals: dict[str, Any] = {}
        if body.title is not None:
            vals["title"] = body.title.strip()
        if body.part_title is not None and body.part_title != case["part_title"]:
            vals["part_title"] = body.part_title
        try:
            case = cases_repo.update_case(conn, case_id, body.version, **vals)
        except VersionConflict:
            raise conflict("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요") from None
        except IntegrityError:
            raise conflict("CASE_NAME_EXISTS", "같은 제목의 Case 가 있습니다") from None
        return case_out(ctx, case, stage_status(conn, case))


def archive_case(ctx: AppContext, principal: Principal, case_id: str) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        case = load_case(conn, case_id, for_update=True)
        require_execute(principal, case["project_id"])
        require_config_ok(ctx)
        if jobs_repo.has_active_jobs(conn, case_id):
            raise conflict("CASE_HAS_ACTIVE_JOB", "실행 중이거나 대기 중인 작업이 있습니다")
        if case["status"] != "ARCHIVED":
            case = cases_repo.update_case(conn, case_id, None, status="ARCHIVED")
        return case_out(ctx, case, stage_status(conn, case))


# ---------------------------------------------------------------- t*
def _tstar_info(ctx: AppContext, case: dict[str, Any]) -> dict[str, Any]:
    if not case.get("extract_summary"):
        raise conflict("PREREQUISITE_MISSING", "추출(①)이 먼저 필요합니다", missing=["extract"])
    try:
        return co.tstar_info(case_dir(ctx, case))
    except (co.OutputMissing, OSError, ValueError):
        raise conflict("PREREQUISITE_MISSING", "t* 산출물(02_tstar/tstar.json)이 없습니다", missing=["tstar"]) from None


def get_tstar(ctx: AppContext, case_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
    info = _tstar_info(ctx, case)
    sel = case.get("tstar") or {}
    blk = info["metrics"].get(sel.get("metric") or info["default_metric"]) or {}
    return {"selected": case.get("tstar"), "default_metric": info["default_metric"], "metrics": info["metrics"],
            "hotspots": blk.get("hotspots", info["hotspots"]), "frames_D": info.get("frames_D") or []}


def put_tstar(ctx: AppContext, principal: Principal, case_id: str, body) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        case = load_case(conn, case_id, for_update=True)
        require_execute(principal, case["project_id"])
        require_config_ok(ctx)
        require_active_case(case)
        info = _tstar_info(ctx, case)
        m = info["metrics"].get(body.metric)
        if m is None:
            raise unprocessable("INVALID_METRIC", f"지표 {body.metric} 가 없습니다 (가능: {list(info['metrics'])})")
        hit = next((c for c in m["candidates"] if c["frame_index"] == body.frame_index), None)
        if hit is not None and hit.get("in_D") is False:
            raise unprocessable("FRAME_NOT_CANDIDATE", f"frame {body.frame_index} 은 변위가 추출된 후보 프레임(D)이 "
                                "아닙니다", candidates=[c["frame_index"] for c in m["candidates"] if c.get("in_D")
                                                       is not False])
        if hit is None:
            raise unprocessable("FRAME_NOT_CANDIDATE", f"frame {body.frame_index} 은 {body.metric} 후보가 아닙니다",
                                candidates=[c["frame_index"] for c in m["candidates"]])
        tstar = {"metric": body.metric, "frame_index": hit["frame_index"], "time": hit["time"],
                 "elem_id": hit["elem_id"], "value": hit["value"], "source": "user"}
        try:
            case = cases_repo.update_case(conn, case_id, body.version, tstar=tstar)
        except VersionConflict:
            raise conflict("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요") from None
        return case_out(ctx, case, stage_status(conn, case))


# ---------------------------------------------------------------- 모델 노드·지지점
def _model(ctx: AppContext, case: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if not case.get("extract_summary"):
        raise conflict("PREREQUISITE_MISSING", "추출(①)이 먼저 필요합니다", missing=["extract"])
    try:
        return co.model_nodes(case_dir(ctx, case))
    except (co.OutputMissing, OSError, ValueError, KeyError):
        raise conflict("PREREQUISITE_MISSING", "모델 산출물(01_extract/model.npz)이 없습니다",
                       missing=["extract"]) from None


def _core_call(fn, *args):
    try:
        return fn(*args)
    except core_adapter.CoreError as exc:
        if exc.code in ("SUPPORT_DEGENERATE", "INPUT_INVALID"):
            raise unprocessable(exc.code, exc.message) from None
        raise DomainError(exc.code, exc.message, status=500) from None


def _suggest(node_id: np.ndarray, x0: np.ndarray) -> dict[str, Any]:
    pc = _core_call(core_adapter.pca_corners, x0)
    corners = [int(i) for i in pc["idx"]]
    sup = _core_call(core_adapter.pick_321, x0, corners)
    idx = [i for i, _ in sup]
    return {"node_ids": [int(node_id[i]) for i in idx], "dofs": [d for _, d in sup],
            "coords": [x0[i].tolist() for i in idx], "plane": pc["plane"],
            "corners": [int(node_id[i]) for i in corners]}


def suggest_support(ctx: AppContext, principal: Principal, case_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
    require_execute(principal, case["project_id"])
    nid, x0 = _model(ctx, case)
    return _suggest(nid, x0)


def support_out(case: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    d = dict(s)
    d["is_current"] = case.get("current_support_set_id") == s["id"]
    return d


def create_support(ctx: AppContext, principal: Principal, case_id: str, body) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
    require_execute(principal, case["project_id"])
    require_config_ok(ctx)
    require_active_case(case)
    nid, x0 = _model(ctx, case)
    pos = np.searchsorted(nid, body.node_ids)
    bad = [n for n, p in zip(body.node_ids, pos) if p >= nid.size or int(nid[p]) != int(n)]
    if bad:
        raise unprocessable("NODE_NOT_IN_PART", f"대상 파트에 없는 노드: {bad}", node_ids=bad)
    idx = [int(p) for p in pos]
    sup = _core_call(core_adapter.pick_321, x0, idx)
    dof_by_idx = {i: d for i, d in sup}
    if set(dof_by_idx) != set(idx):
        raise unprocessable("SUPPORT_DEGENERATE", "3-2-1 지지점을 정할 수 없습니다")
    try:
        sug = _suggest(nid, x0)
        source = "auto" if sorted(sug["node_ids"]) == sorted(body.node_ids) else "user"
        plane = sug["plane"]
    except DomainError:
        source, plane = "user", None
    with ctx.engine.begin() as conn:
        case = load_case(conn, case_id, for_update=True)
        s = cases_repo.insert_support_set(conn, case_id=case_id, node_ids=[int(n) for n in body.node_ids],
                                          dofs=[dof_by_idx[i] for i in idx], source=source, plane=plane,
                                          created_by=principal.user_id)
        case = cases_repo.update_case(conn, case_id, None, current_support_set_id=s["id"])
        return support_out(case, s)


def list_supports(ctx: AppContext, case_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
        return [support_out(case, s) for s in cases_repo.list_support_sets(conn, case_id)]


# ---------------------------------------------------------------- 미리보기
def preview(ctx: AppContext, case_id: str, frame_index: int | None) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
        sup = cases_repo.get_support_set(conn, case["current_support_set_id"]) if case.get(
            "current_support_set_id") else None
    nid, x0 = _model(ctx, case)
    cdir = case_dir(ctx, case)
    if frame_index is None:
        frame_index = (case.get("tstar") or {}).get("frame_index")
    u = co.disp_frame(cdir, frame_index) if frame_index is not None else None
    if frame_index is not None and u is None:
        raise unprocessable("FRAME_NOT_AVAILABLE", f"frame {frame_index} 변위가 없습니다(후보 프레임만 추출됨)",
                            frames=co.disp_frames(cdir))
    plane = _core_call(core_adapter.pca_corners, x0)["plane"]
    o, e1, e2 = (np.asarray(plane[k], float) for k in ("origin", "e1", "e2"))
    a = (x0 - o) @ e1
    b = (x0 - o) @ e2
    val = np.linalg.norm(u, axis=1) if u is not None else np.zeros(nid.size)
    n = nid.size
    mx = ctx.settings.ui.max_preview_points
    keep = np.arange(n)
    decimated = False
    if n > mx:
        decimated = True
        step = int(np.ceil(n / mx))
        keep = np.arange(0, n, step)
        if sup:
            extra = np.searchsorted(nid, sup["node_ids"])
            keep = np.unique(np.concatenate([keep, extra[extra < n]]))
    pts = [[int(nid[i]), float(a[i]), float(b[i]), float(val[i])] for i in keep]
    return {"frame_index": frame_index, "plane": plane, "points": pts, "decimated": decimated, "n_nodes": int(n),
            "value": "|u|", "supports": ([{"node_id": int(nn), "dof": d} for nn, d in zip(sup["node_ids"],
                                                                                          sup["dofs"])]
                                         if sup else [])}


def list_esl_runs(ctx: AppContext, case_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
        return [esl_run_out(case, r, conn) for r in cases_repo.list_esl_runs(conn, case_id)]
