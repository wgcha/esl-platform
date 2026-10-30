"""Case 서비스: 생성·조회·수정·보관, 단계 상태, t*, 미리보기, 지지점 세트(동기 API).

v0.10.0(esl_menu_restructure.md §5): PUT /tstar 가 지지 세트가 없을 때만 3-2-1 자동 선택(코어 auto_321 + 품질 검사)을
같은 요청에서 수행해 저장(``tstar.support_auto`` = OK|KEPT|BLOCKED|MANUAL). 수동 지정 POST /support-sets 도 같은 검사
(실패 422 SUPPORT_CHECK_FAILED). 화면 4단계 상태 ``step_status{input, tstar, esl, validate}``(옛 ``stage_status`` 유지).
"""

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
from ...core.inputs import fingerprint, fingerprint_h3d
from ...core.paths import check_input_path, h3d_raw_dir
from ...core.repositories import cases as cases_repo
from ...core.repositories import jobs as jobs_repo
from ...core.repositories.cases import VersionConflict
from ...core.db.tables import jobs as jobs_t
from ...core.state_machine import FAILED, INTERRUPTED, QUEUED, RUNNING, SUCCEEDED
from ...core.uploads import check_principal_upload_area
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
def _latest_case_export(conn, case_id: str) -> dict[str, Any] | None:
    """Case 단위 EXPORT(params.origin 없음)의 최신 작업 — 라이브러리 내보내기(origin=library)는 ⑥ 상태에 영향 없음(MR-D-7)."""
    from sqlalchemy import and_, select

    from ...core.repositories import row_dict

    return row_dict(conn.execute(
        select(jobs_t).where(and_(jobs_t.c.case_id == case_id, jobs_t.c.job_type == "EXPORT",
                                  jobs_t.c.params["origin"].astext.is_(None)))
        .order_by(jobs_t.c.created_at.desc()).limit(1)).first())


def stage_status(conn, case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest = {jt: jobs_repo.latest_job(conn, case["id"], jt) for jt in ("CASE_EXTRACT", "ESL_SOLVE", "VALIDATE")}
    latest["EXPORT"] = _latest_case_export(conn, case["id"])

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


REASON_MESSAGES = {
    "SUPPORT_AUTO_BLOCKED": "지지점을 자동으로 정하지 못했습니다 — ②에서 사유 확인",
    "TSTAR_NOT_CONFIRMED": "t* 확정이 필요합니다(확정 시 지지점 자동 선택)",
}


def step_status(case: dict[str, Any], ss: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """화면 4단계(§5.4): input = 옛 1, tstar = t*·지지점, esl = 옛 4, validate = 옛 5."""
    def r(code: str) -> dict[str, str]:
        return {"code": code, "message": REASON_MESSAGES[code]}

    t2 = dict(ss["2"])
    ts = case.get("tstar")
    if t2["state"] != "running" and ts:
        auto = (ts.get("support_auto") or {}) if isinstance(ts, dict) else {}
        if extract_stale(case):
            t2 = {"state": "stale", "job_id": None}
        elif case.get("current_support_set_id"):
            t2 = {"state": "done", "job_id": None}
        elif auto.get("status") == "BLOCKED":
            t2 = {"state": "failed", "job_id": None, "reason": r("SUPPORT_AUTO_BLOCKED")}
        else:
            t2 = {"state": "none", "job_id": None, "reason": r("TSTAR_NOT_CONFIRMED")}
    return {"input": dict(ss["1"]), "tstar": t2, "esl": dict(ss["4"]), "validate": dict(ss["5"])}


def case_full(ctx: AppContext, conn, case: dict[str, Any]) -> dict[str, Any]:
    ss = stage_status(conn, case)
    d = case_out(ctx, case, ss)
    d["step_status"] = step_status(case, ss)
    return d


# ---------------------------------------------------------------- 생성
def _check_part(ctx: AppContext, rad: str, results: str | None, part_title: str) -> tuple[dict, dict | None, list[str]]:
    info = system.inspect_rad(ctx, rad, part_title)
    for p in info["problems"]:
        if p.startswith("PART_NOT_FOUND"):
            raise unprocessable("PART_NOT_FOUND", f"대상 파트 '{part_title}' 가 rad 에 없습니다")
        if p.startswith("PART_AMBIGUOUS"):
            raise unprocessable("PART_AMBIGUOUS", f"대상 파트 '{part_title}' 가 rad 에 여러 개입니다")
    done = system.read_done(results)[0] if results else None
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
    """v0.12.0: PATH_OUTSIDE_ROOT(include 가 입력 루트 밖) 문구·detail 의 서버 절대경로는 일반 사용자에게 가린다(전역 관리자 원문)."""
    try:
        return _create_case(ctx, principal, token, rid, body)
    except DomainError as exc:
        if exc.code != "PATH_OUTSIDE_ROOT" or principal.is_global_admin:
            raise
        from .jobs import _root_labels, mask_server_paths

        roots = _root_labels(ctx)
        extra = {k: (mask_server_paths(v, roots) if isinstance(v, str) else v) for k, v in exc.extra.items()}
        raise DomainError(exc.code, mask_server_paths(exc.message, roots), status=exc.status, headers=exc.headers,
                          **extra) from None


def _create_case(ctx: AppContext, principal: Principal, token: str | None, rid: str, body) -> dict[str, Any]:
    projects = _projects(ctx, principal, token, rid)
    if body.project_id not in {p["id"] for p in projects}:
        raise not_found("PROJECT_NOT_FOUND", "프로젝트를 찾을 수 없습니다")
    require_execute(principal, body.project_id)
    require_config_ok(ctx)
    s = ctx.settings
    rad = check_input_path(s, body.rad_path, "RAD")
    check_principal_upload_area(s.storage.upload_root, rad, principal)
    h3d = None
    if body.h3d_path is not None:
        # P3-UX §6: 서버 h3d 추출 — results_dir = <esl_root>/_h3d/<폴더>/raw(작업 H3D_EXTRACT 가 채움)
        from .uploads import check_h3d

        if not s.altair.hw_exe_path:
            raise DomainError("H3D_EXTRACT_UNAVAILABLE", "서버 h3d 추출이 설정되지 않았습니다(altair.hw_exe_path) — "
                              "PC에서 추출한 결과 폴더로 Case 를 만드세요", status=503)
        h3d = check_input_path(s, body.h3d_path, "H3D")
        check_principal_upload_area(s.storage.upload_root, h3d, principal)
        probs = check_h3d(h3d)
        if probs:
            raise unprocessable("INPUT_INVALID", "h3d 파일이 올바르지 않습니다: " + "; ".join(probs), problems=probs)
        results = h3d_raw_dir(s, body.folder_name)
    else:
        results = check_input_path(s, body.results_dir, "RESULTS")
        check_principal_upload_area(s.storage.upload_root, results, principal)
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
    info, done, includes = _check_part(ctx, rad, None if h3d else results, part_title)
    h3d_meta = None
    if h3d:
        from .uploads import check_slim_part, h3d_meta_for

        with ctx.engine.connect() as conn:
            h3d_meta = h3d_meta_for(conn, h3d)
        check_slim_part(h3d_meta, int(info["target_part"]["id"]) if info["target_part"] else None)
    for inc in includes:
        check_principal_upload_area(s.storage.upload_root, inc, principal)
    fp = fingerprint_h3d(rad, h3d, includes) if h3d else fingerprint(rad, results, includes)
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
                rad_path=rad, results_dir=results, h3d_path=h3d or (done or {}).get("h3d"),
                input_kind="H3D" if h3d else "RESULTS", input_fingerprint=fp,
                part_title=part_title, part_id=int(target["id"]) if target else None,
                created_by=principal.user_id, created_by_name=principal.display_name,
            )
        with open(os.path.join(cdir, "case.json"), "w", encoding="utf-8") as fh:
            json.dump({"id": case["id"], "project_id": case["project_id"], "title": case["title"],
                       "rad_path": rad, "results_dir": results, "h3d_path": case["h3d_path"],
                       "input_kind": case["input_kind"],
                       "h3d_mode": ((h3d_meta or {}).get("kind") or "").removeprefix("h3d_") or None if h3d else None,
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
    from .uploads import h3d_metas_for

    with ctx.engine.connect() as conn:
        rows = cases_repo.list_cases(conn, project_id, status)
        metas = h3d_metas_for(conn, [c["h3d_path"] for c in rows if c.get("input_kind") == "H3D"])
        return [case_out(ctx, c, None, metas) for c in rows]


def get_case(ctx: AppContext, case_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
        return case_full(ctx, conn, case)


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
            if case.get("input_kind") == "H3D" and case.get("h3d_path"):      # 압축 모드 h3d 는 대상 파트가 고정
                from .uploads import check_slim_part, h3d_meta_for

                meta = h3d_meta_for(conn, case["h3d_path"])
                if meta and meta.get("kind") == "h3d_slim":
                    tgt = system.inspect_rad(ctx, case["rad_path"], body.part_title)["target_part"]
                    check_slim_part(meta, int(tgt["id"]) if tgt else None)
        try:
            case = cases_repo.update_case(conn, case_id, body.version, **vals)
        except VersionConflict:
            raise conflict("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요") from None
        except IntegrityError:
            raise conflict("CASE_NAME_EXISTS", "같은 제목의 Case 가 있습니다") from None
        return case_full(ctx, conn, case)


def archive_case(ctx: AppContext, principal: Principal, case_id: str) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        case = load_case(conn, case_id, for_update=True)
        require_execute(principal, case["project_id"])
        require_config_ok(ctx)
        if jobs_repo.has_active_jobs(conn, case_id):
            raise conflict("CASE_HAS_ACTIVE_JOB", "실행 중이거나 대기 중인 작업이 있습니다")
        if case["status"] != "ARCHIVED":
            case = cases_repo.update_case(conn, case_id, None, status="ARCHIVED")
        return case_full(ctx, conn, case)


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
    out = {"selected": case.get("tstar"), "default_metric": info["default_metric"], "metrics": info["metrics"],
           "hotspots": blk.get("hotspots", info["hotspots"]), "frames_D": info.get("frames_D") or []}
    if info.get("cumulative"):
        out["cumulative"] = info["cumulative"]
    return out


def _check_cfg(ctx: AppContext) -> dict[str, Any]:
    return core_adapter.support_check_settings(ctx.config.core or {})


def _auto_support(ctx: AppContext, case: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    """모델 로드 + 코어 auto_321(트랜잭션 밖, 30만 노드 < 1 s)."""
    nid, x0 = _model(ctx, case)
    return _core_call(core_adapter.auto_support, x0, _check_cfg(ctx)), nid, x0


def put_tstar(ctx: AppContext, principal: Principal, case_id: str, body) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        pre = load_case(conn, case_id)
    require_execute(principal, pre["project_id"])
    auto = None
    if not pre.get("current_support_set_id") and pre.get("extract_summary") and pre.get("status") == "ACTIVE":
        auto = _auto_support(ctx, pre)
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
        if case["version"] != body.version:
            raise conflict("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요")
        vals: dict[str, Any] = {}
        if case.get("current_support_set_id"):
            # 지지 세트 있음(자동·이전 수동 편집 모두) → 그대로(MR-D-3). 잠금 중 다른 사용자가 먼저 만든 경우도 여기
            sup = cases_repo.get_support_set(conn, case["current_support_set_id"])
            tstar["support_auto"] = {"status": "KEPT", "source": (sup or {}).get("source")}
        else:
            if auto is None:
                auto = _auto_support(ctx, case)
            res, nid, _x0 = auto
            if res["status"] == "OK":
                s = cases_repo.insert_support_set(
                    conn, case_id=case_id, node_ids=[int(nid[i]) for i in res["idx"]], dofs=list(res["dofs"]),
                    source="auto", plane=res.get("plane"), created_by=principal.user_id)
                vals["current_support_set_id"] = s["id"]
                tstar["support_auto"] = {"status": "OK", "mode": res["mode"], "checks": res.get("checks"),
                                         "rule_version": res.get("rule_version")}
            else:
                tstar["support_auto"] = {"status": "BLOCKED", "mode": res["mode"], "problems": res.get("problems") or [],
                                         "checks": res.get("checks"), "rule_version": res.get("rule_version")}
        try:
            case = cases_repo.update_case(conn, case_id, body.version, tstar=tstar, **vals)
        except VersionConflict:
            raise conflict("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요") from None
        return case_full(ctx, conn, case)


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


def _suggest_out(res: dict[str, Any], node_id: np.ndarray, x0: np.ndarray) -> dict[str, Any]:
    idx = [int(i) for i in res.get("idx") or []]
    return {"node_ids": [int(node_id[i]) for i in idx], "dofs": list(res.get("dofs") or []),
            "coords": [x0[i].tolist() for i in idx], "plane": res.get("plane"),
            "corners": [int(node_id[i]) for i in res.get("corners") or []], "status": res["status"],
            "mode": res.get("mode"), "checks": res.get("checks"), "problems": res.get("problems") or [],
            "rule_version": res.get("rule_version")}


def suggest_support(ctx: AppContext, principal: Principal, case_id: str) -> dict[str, Any]:
    """§5.1: PUT /tstar 와 같은 auto_321 결과(status·problems 포함). BLOCKED 면 node_ids 는 pca4 삼각형(표시용)."""
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
    require_execute(principal, case["project_id"])
    res, nid, x0 = _auto_support(ctx, case)
    return _suggest_out(res, nid, x0)


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
    cfg = _check_cfg(ctx)
    chk = _core_call(core_adapter.check_support, x0, idx, cfg)
    if chk["status"] != "OK":
        # §5.1(Q2 B): 수동 지정도 자동 선택과 같은 품질 검사(후보 확장 없음)
        raise unprocessable("SUPPORT_CHECK_FAILED", "지정한 지지 노드가 품질 검사를 통과하지 못했습니다: "
                            + "; ".join(p["message"] for p in chk["problems"]), problems=chk["problems"])
    dof_by_idx = dict(zip(idx, chk["dofs"]))
    try:
        sug = _core_call(core_adapter.auto_support, x0, cfg)
        source = "auto" if sug["status"] == "OK" and sorted(int(nid[i]) for i in sug["idx"]) == sorted(
            body.node_ids) else "user"
        plane = sug.get("plane") or chk.get("plane")
    except DomainError:
        source, plane = "user", chk.get("plane")
    with ctx.engine.begin() as conn:
        case = load_case(conn, case_id, for_update=True)
        s = cases_repo.insert_support_set(conn, case_id=case_id, node_ids=[int(n) for n in body.node_ids],
                                          dofs=[dof_by_idx[i] for i in idx], source=source, plane=plane,
                                          created_by=principal.user_id)
        vals: dict[str, Any] = {"current_support_set_id": s["id"]}
        if isinstance(case.get("tstar"), dict):
            vals["tstar"] = {**case["tstar"], "support_auto": {"status": "MANUAL", "checks": chk.get("checks"),
                                                               "rule_version": chk.get("rule_version")}}
        case = cases_repo.update_case(conn, case_id, None, **vals)
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
