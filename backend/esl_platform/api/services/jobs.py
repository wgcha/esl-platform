"""작업 서비스: 등록(사전조건·코어 설정 스냅샷), 조회, 취소, 재시도, step 로그."""

from __future__ import annotations

import copy
import os
import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from ...core import core_outputs as co
from ...core.auth import Principal
from ...core.errors import DomainError, conflict, forbidden, unprocessable
from ...core.inputs import case_inputs_hash, changed_inputs, fingerprint, fingerprint_h3d
from ...core.paths import check_includes, check_input_path
from ...core.repositories import cases as cases_repo
from ...core.repositories import jobs as jobs_repo
from ...core.state_machine import CANCELED, FAILED, INTERRUPTED, TERMINAL
from ..context import AppContext
from ..schemas import CaseExtractParams, CaseReportParams, EslSolveParams, ExportParams, RunRefParams
from .common import (
    analysis_dir,
    case_dir,
    esl_run_stale,
    extract_stale,
    job_out,
    load_case,
    load_job,
    require_active_case,
    require_config_ok,
    require_execute,
    require_job_view,
)

LOG_MAX_LINES = 1000
LOG_MAX_BYTES = 256 * 1024


def core_settings_for(ctx: AppContext, case: dict[str, Any], *, metric: str | None = None,
                      material_override: dict | None = None) -> dict[str, Any]:
    """코어 설정 스냅샷 + Case 값(part_title, t* 지표, 재료 override)."""
    cfg = copy.deepcopy(ctx.config.core or {})
    cfg.setdefault("case", {})["part_title"] = case["part_title"]
    if metric and isinstance(cfg.get("tstar"), dict) and "metric" in cfg["tstar"]:
        cfg["tstar"]["metric"] = metric
    if material_override:
        mo = dict(cfg["case"].get("material_override") or {})
        mo.update({str(k): dict(v) for k, v in material_override.items()})
        cfg["case"]["material_override"] = mo
    return cfg


def _params(model, raw: dict[str, Any]):
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        errors = [{"loc": list(e.get("loc", [])), "msg": str(e.get("msg", ""))} for e in exc.errors()]
        raise unprocessable("INVALID_PARAMS", "작업 params 가 올바르지 않습니다", errors=errors) from None


def _prepare(ctx: AppContext, conn, case: dict[str, Any], job_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    """사전조건 확인 → jobs.params. 미충족 409 PREREQUISITE_MISSING + missing."""
    cdir = case_dir(ctx, case)
    if job_type == "CASE_EXTRACT":
        h3d_case = case.get("input_kind") == "H3D"
        if raw and not h3d_case:
            raise unprocessable("INVALID_PARAMS", "CASE_EXTRACT params 는 {} 입니다(h3d 입력 Case 만 hot_k·top_n)")
        opts = _params(CaseExtractParams, raw)
        s = ctx.settings
        rad = check_input_path(s, case["rad_path"], "RAD")
        if h3d_case:
            h3d = check_input_path(s, case["h3d_path"], "H3D")
            res = None
        else:
            res = check_input_path(s, case["results_dir"], "RESULTS")
        from esl_worker import core_adapter

        cc = (ctx.config.core or {}).get("case") or {}
        try:
            incs = core_adapter.scan_includes(rad, int(cc.get("rad_include_max_depth") or 8),
                                              cc.get("include_path_map") or None)
        except core_adapter.CoreError:  # 스캔 실패는 이전 목록 유지
            incs = [i["path"] for i in (case["input_fingerprint"].get("includes") or [])]
        check_includes(s, incs)
        settings = core_settings_for(ctx, case)
        if not h3d_case:
            return {"settings": settings, "input_fingerprint": fingerprint(rad, res, incs),
                    "part_title": case["part_title"]}
        from .uploads import h3d_meta_for

        slim = (h3d_meta_for(conn, h3d) or {}).get("kind") == "h3d_slim"
        hot_k = opts.hot_k or int((settings.get("extract") or {}).get("hot_k") or 200)
        top_n = opts.top_n or int((settings.get("tstar") or {}).get("top_n_times") or 5)
        return {"settings": settings, "input_fingerprint": fingerprint_h3d(rad, h3d, incs),
                "part_title": case["part_title"],
                "h3d": {"h3d_path": h3d, "out_dir": case["results_dir"], "part": case["part_title"],
                        "hot_k": int(hot_k), "top_n": int(top_n), "slim": bool(slim)}}

    missing: list[str] = []
    if job_type == "CASE_REPORT":
        p = _params(CaseReportParams, raw)
        if not case.get("extract_summary") or extract_stale(case):
            raise conflict("PREREQUISITE_MISSING", "추출(①)이 먼저 필요합니다", missing=["extract"])
        out = {"settings": core_settings_for(ctx, case, metric=(case.get("tstar") or {}).get("metric")),
               "validation_id": None, "esl_run_id": case.get("current_esl_run_id"), "auto": False}
        if p.validation_id:
            val = cases_repo.get_validation(conn, p.validation_id)
            if val is None or val["case_id"] != case["id"]:
                raise unprocessable("INVALID_PARAMS", "이 Case 의 검증 결과가 아닙니다")
            out.update(validation_id=val["id"], esl_run_id=val["esl_run_id"])
        return out
    if job_type == "ESL_SOLVE":
        p = _params(EslSolveParams, raw)
        if not case.get("extract_summary") or extract_stale(case):
            missing.append("extract")
        ts = case.get("tstar")
        if not ts:
            missing.append("tstar")
        sid = p.support_set_id or case.get("current_support_set_id")
        sup = cases_repo.get_support_set(conn, sid) if sid else None
        if sup is None or sup["case_id"] != case["id"]:
            missing.append("support_set")
        frame = p.frame_index if p.frame_index is not None else (ts or {}).get("frame_index")
        if not missing and frame not in co.disp_frames(cdir):
            missing.append("disp_frame")
        if missing:
            # v0.10.0 MR-D-4: ② 지지점 자동 선택이 품질 검사에 걸렸으면 support_blocked + 사유
            auto = (ts or {}).get("support_auto") if isinstance(ts, dict) else None
            blocked = "support_set" in missing and isinstance(auto, dict) and auto.get("status") == "BLOCKED"
            extra = {"support_blocked": True, "problems": auto.get("problems") or []} if blocked else {}
            raise conflict("PREREQUISITE_MISSING", "② 지지점 자동 선택 실패 — ②에서 사유 확인" if blocked
                           else "앞 단계가 필요합니다", missing=missing, **extra)
        metric = ts.get("metric") or "max_strain"
        if p.frame_index is not None and p.frame_index != ts.get("frame_index"):
            info = co.tstar_info(cdir)
            cands = [c["frame_index"] for c in (info["metrics"].get(metric) or {}).get("candidates", [])]
            if p.frame_index not in cands:
                raise unprocessable("FRAME_NOT_CANDIDATE", f"frame {p.frame_index} 은 후보가 아닙니다", candidates=cands)
        es = case["extract_summary"] or {}
        from ...core.inputs import inputs_hash

        ih = inputs_hash(extract_job_id=es.get("job_id"), part_title=case["part_title"],
                         tstar={"frame_index": frame, "metric": metric}, support_set_id=sup["id"])
        return {"settings": core_settings_for(ctx, case, metric=metric, material_override=p.material_override),
                "frame_index": int(frame), "metric": metric, "support_set_id": sup["id"],
                "support_node_ids": list(sup["node_ids"]), "support_dofs": list(sup["dofs"]), "inputs_hash": ih,
                "material_override": p.material_override}

    model = RunRefParams if job_type == "VALIDATE" else ExportParams
    p = _params(model, raw)
    run = cases_repo.get_esl_run(conn, p.esl_run_id)
    if run is None or run["case_id"] != case["id"] or run["status"] != "READY":
        missing.append("esl_run")
    elif case.get("current_esl_run_id") != run["id"]:
        missing.append("current_esl_run")
    elif job_type == "VALIDATE" and esl_run_stale(case, run):
        missing.append("fresh_esl_run")
    if missing:
        raise conflict("PREREQUISITE_MISSING", "유효한 ESL 결과가 필요합니다", missing=missing)
    out = {"settings": core_settings_for(ctx, case, metric=run["metric"]), "esl_run_id": run["id"],
           "frame_index": run["frame_index"], "support_node_ids": None}
    sup = cases_repo.get_support_set(conn, run["support_set_id"])
    out["support_node_ids"] = list(sup["node_ids"]) if sup else None
    if job_type == "EXPORT":
        out["targets"] = list(p.targets)
        vals = cases_repo.list_validations(conn, esl_run_id=run["id"])
        out["validation_verdict"] = vals[0]["verdict"] if vals else None
    return out


def create_job(ctx: AppContext, principal: Principal, case_id: str, body) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        case = load_case(conn, case_id, for_update=True)
        require_execute(principal, case["project_id"])
        require_config_ok(ctx)
        require_active_case(case)
        params = _prepare(ctx, conn, case, body.job_type, dict(body.params or {}))
        try:
            with conn.begin_nested():
                job = jobs_repo.insert_job(conn, case_id=case_id, project_id=case["project_id"],
                                           job_type=body.job_type, params=params, created_by=principal.user_id,
                                           created_by_name=principal.display_name,
                                           h3d=case.get("input_kind") == "H3D")
        except IntegrityError:
            raise conflict("CASE_JOB_BUSY", "같은 Case 에서 같은 종류의 작업이 대기 중이거나 실행 중입니다") from None
        if body.job_type == "CASE_EXTRACT":
            cases_repo.update_case(conn, case_id, None, input_fingerprint=params["input_fingerprint"])
        return job_out(conn, job, with_steps=True)


def get_job(ctx: AppContext, job_id: str, principal: Principal | None = None) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        job = load_job(conn, job_id)
        if principal is not None:
            require_job_view(principal, job)
        return job_out(conn, job, with_steps=True)


def check_job_view(ctx: AppContext, principal: Principal, job_id: str) -> None:
    """작업 하위 경로(로그·이력 파일·보고서) 조회 전 권한 확인(OPT_RUN·DOE_* = 프로젝트 조회 권한)."""
    with ctx.engine.connect() as conn:
        require_job_view(principal, load_job(conn, job_id))


def list_case_jobs(ctx: AppContext, case_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        load_case(conn, case_id)
        return [job_out(conn, j) for j in jobs_repo.list_case_jobs(conn, case_id)]


def _can_touch(principal: Principal, job: dict[str, Any]) -> None:
    require_execute(principal, job["project_id"])
    if not principal.is_global_admin and job["created_by"] != principal.user_id:
        raise forbidden("다른 사용자의 작업은 전역 관리자만 취소·재시도할 수 있습니다")


def cancel_job(ctx: AppContext, principal: Principal, job_id: str) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        job = load_job(conn, job_id, for_update=True)
        _can_touch(principal, job)
        if job["state"] in TERMINAL:
            raise conflict("JOB_TERMINAL", "이미 끝난 작업입니다")
        job = jobs_repo.request_cancel(conn, job_id, principal.user_id)
        return job_out(conn, job, with_steps=True)


def retry_job(ctx: AppContext, principal: Principal, job_id: str) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        job = load_job(conn, job_id, for_update=True)
        _can_touch(principal, job)
        require_config_ok(ctx)
        if job["state"] not in (FAILED, INTERRUPTED, CANCELED):
            code = "JOB_TERMINAL" if job["state"] in TERMINAL else "JOB_NOT_TERMINAL"
            raise conflict(code, "실패·중단·취소된 작업만 재시도할 수 있습니다")
        if job["job_type"] == "LIB_ANALYZE":
            return _retry_analysis(conn, principal, job)
        if job["job_type"] == "LIB_COMPARE":
            return _retry_comparison(conn, principal, job)
        if job["job_type"] == "OPT_RUN":
            from .opt import retry_run

            return retry_run(conn, principal, job)
        if job.get("bead_doe_id"):
            from .doe import retry_job as retry_doe

            return retry_doe(conn, principal, job)
        case = load_case(conn, job["case_id"], for_update=True)
        require_active_case(case)
        start = jobs_repo.first_failed_step(conn, job_id)
        params = dict(job["params"])
        if job["job_type"] == "EXPORT" and params.get("origin") == "library":
            # 라이브러리 내보내기: 실패는 대개 EXP_REGISTER(항목 전부 실패 = EXPORT_ALL_FAILED)에서 드러나므로 실패 step 부터
            # 이어 하면 같은 실패 결과만 다시 등록한다 → EXPORT 단계부터 다시(항목 폴더는 _backup 후 새로, 통합 검증 지적 4f)
            start = 1
        if job["failure_code"] == "INPUT_CHANGED":
            # 입력이 바뀌어 실패한 작업: 예전 지문으로 재시도하면 또 실패 → CASE_EXTRACT 는 현재 입력으로 다시
            # 준비(새 지문, 처음 step 부터), 그 밖의 작업은 추출부터 다시 해야 하므로 거부.
            if job["job_type"] != "CASE_EXTRACT":
                raise conflict("INPUT_CHANGED", "입력 파일이 추출 이후 바뀌었습니다. 추출(①)부터 다시 실행하세요")
            old = params.get("h3d") or {}
            params = _prepare(ctx, conn, case, "CASE_EXTRACT",
                              {k: old[k] for k in ("hot_k", "top_n") if old.get(k)} if old else {})
            start = 1
        try:
            with conn.begin_nested():
                new = jobs_repo.insert_job(conn, case_id=job["case_id"], project_id=job["project_id"],
                                           job_type=job["job_type"], params=params, created_by=principal.user_id,
                                           created_by_name=principal.display_name, retry_of_job_id=job_id,
                                           resume_from_step=start if start > 1 else None,
                                           h3d=job["job_type"] == "CASE_EXTRACT" and case.get("input_kind") == "H3D")
        except IntegrityError:
            raise conflict("CASE_JOB_BUSY", "같은 Case 에서 같은 종류의 작업이 대기 중이거나 실행 중입니다") from None
        if job["failure_code"] == "INPUT_CHANGED":
            cases_repo.update_case(conn, case["id"], None, input_fingerprint=params["input_fingerprint"])
        return job_out(conn, new, with_steps=True)


def _retry_analysis(conn, principal: Principal, job: dict[str, Any]) -> dict[str, Any]:
    """LIB_ANALYZE 재시도: 같은 분석 폴더에서 실패 step 부터(이전 step 산출물 재사용, 덮어쓰기는 _backup)."""
    from ...core.repositories import library as lib_repo

    an = lib_repo.get_analysis(conn, job["analysis_id"], for_update=True)
    if an is None:
        raise DomainError("ANALYSIS_NOT_FOUND", "분석을 찾을 수 없습니다", status=404)
    from .library import require_eligible_ids

    require_eligible_ids(conn, [*(an.get("entry_ids") or []), an.get("target_entry_id")])   # MR-D-10(지적 1c)
    start = jobs_repo.first_failed_step(conn, job["id"])
    try:
        with conn.begin_nested():
            new = jobs_repo.insert_job(conn, case_id=None, analysis_id=an["id"], project_id=job["project_id"],
                                       job_type="LIB_ANALYZE", params=dict(job["params"]),
                                       created_by=principal.user_id, created_by_name=principal.display_name,
                                       retry_of_job_id=job["id"], resume_from_step=start if start > 1 else None)
    except IntegrityError:
        raise conflict("ANALYSIS_JOB_BUSY", "이 분석의 작업이 대기 중이거나 실행 중입니다") from None
    lib_repo.update_analysis(conn, an["id"], job_id=new["id"])
    return job_out(conn, new, with_steps=True)


def _retry_comparison(conn, principal: Principal, job: dict[str, Any]) -> dict[str, Any]:
    """LIB_COMPARE 재시도: 같은 params(생성 시점 항목·메타 스냅샷)로 처음부터(산출물 덮어쓰기는 _backup)."""
    from ...core.repositories import library as lib_repo

    c = lib_repo.get_comparison(conn, job["comparison_id"], for_update=True)
    if c is None:
        raise DomainError("COMPARISON_NOT_FOUND", "비교를 찾을 수 없습니다", status=404)
    try:
        with conn.begin_nested():
            new = jobs_repo.insert_job(conn, case_id=None, comparison_id=c["id"], project_id=job["project_id"],
                                       job_type="LIB_COMPARE", params=dict(job["params"]),
                                       created_by=principal.user_id, created_by_name=principal.display_name,
                                       retry_of_job_id=job["id"])
    except IntegrityError:
        raise conflict("COMPARISON_JOB_BUSY", "이 비교의 작업이 대기 중이거나 실행 중입니다") from None
    lib_repo.update_comparison(conn, c["id"], job_id=new["id"], verdict=None)
    return job_out(conn, new, with_steps=True)


# ---------------------------------------------------------------- 로그
# 서버 절대경로 가리기(계약 esl_bead_doe.md §15 "응답·로그에 서버 절대경로 없음(일반 사용자)" — 검증 지적: paicad·OptiStruct argv
# 로그). 알려진 루트는 이름표 + 루트 기준 상대 경로, 그 밖 절대경로는 ‹…›/파일명. 전역 관리자는 원문.
_WIN_ABS = re.compile(r"(?<![\w])[A-Za-z]:(?:\\\\|\\|/)[^\s\"',;\]\)]*")
_POSIX_ABS = re.compile(r"(?<![\w.:/~\-›])/(?:[^\s/\"',;\]\)]+/)+[^\s\"',;\]\)]*")


def _root_labels(ctx: AppContext) -> list[tuple[str, str]]:
    st = ctx.settings.storage
    out: list[tuple[str, str]] = []

    def add(p: str | None, label: str) -> None:
        if not p:
            return
        base = os.path.normpath(str(p)).rstrip("\\/")
        if len(base) < 2:
            return
        for v in {base, base.replace("\\", "/"), base.replace("/", "\\"), base.replace("/", "\\").replace("\\", "\\\\")}:
            out.append((v, label))

    add(st.esl_root, "‹ESL_ROOT›")
    add(getattr(st, "upload_root", None), "‹UPLOAD›")
    for p in st.input_roots or []:
        add(p, "‹INPUT›")
    for p in st.spdm_roots or []:
        add(p, "‹SPDM›")
    out.sort(key=lambda x: -len(x[0]))          # 긴(안쪽) 루트 먼저
    return out


def mask_server_paths(line: str, roots: list[tuple[str, str]]) -> str:
    for raw, label in roots:
        if raw in line:
            line = line.replace(raw, label)
    def tail(m: re.Match) -> str:
        v = m.group(0)
        name = re.split(r"[\\/]+", v.rstrip("\\/"))[-1] if v.rstrip("\\/") else ""
        return f"‹…›/{name}" if name else "‹…›"
    line = _WIN_ABS.sub(tail, line)
    return _POSIX_ABS.sub(tail, line)


def _masker(ctx: AppContext, principal: Principal | None = None):
    pats = [re.compile(p) for p in ctx.settings.logging.mask_patterns]
    hide_paths = principal is not None and not principal.is_global_admin
    roots = _root_labels(ctx) if hide_paths else []

    def mask(line: str) -> str:
        for p in pats:
            line = p.sub("***", line)
        if hide_paths:
            line = mask_server_paths(line, roots)
        return line

    return mask


def job_log(ctx: AppContext, job_id: str, step: int | None, cursor: int,
            principal: Principal | None = None) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        job = load_job(conn, job_id)
        if principal is not None:
            require_job_view(principal, job)
        if job.get("analysis_id"):
            from ...core.repositories import library as lib_repo

            base = analysis_dir(ctx, lib_repo.get_analysis(conn, job["analysis_id"]))
        elif job.get("comparison_id"):
            from ...core.repositories import library as lib_repo

            base = analysis_dir(ctx, lib_repo.get_comparison(conn, job["comparison_id"]))
        elif job.get("opt_run_id"):
            from ...core.repositories import opt as opt_repo

            base = analysis_dir(ctx, opt_repo.get_run(conn, job["opt_run_id"]))
        elif job.get("bead_doe_id"):
            from ...core.repositories import doe as doe_repo

            base = analysis_dir(ctx, doe_repo.get_study(conn, job["bead_doe_id"]))
        elif job["job_type"] == "EXPORT" and (job.get("params") or {}).get("origin") == "library":
            # v0.10.0 라이브러리 내보내기: 로그 = <esl_root>/_exports/<batch_id>/logs/<job_id>/
            from ...core.paths import EXPORTS_DIR, esl_subdir

            base = esl_subdir(ctx.settings, EXPORTS_DIR, str(job["params"].get("batch_id")))
        else:
            base = case_dir(ctx, load_case(conn, job["case_id"]))
        steps = jobs_repo.get_steps(conn, job_id)
    if not steps:
        return {"step": 0, "lines": [], "next_cursor": 0, "eof": True}
    if step is None:
        ran = [s for s in steps if s["log_rel"]]
        st = ran[-1] if ran else steps[0]
    else:
        st = next((s for s in steps if s["step_no"] == step), None)
        if st is None:
            raise DomainError("STEP_NOT_FOUND", "step 이 없습니다", status=404)
    terminal = job["state"] in TERMINAL or st["state"] in ("SUCCEEDED", "FAILED", "SKIPPED", "CANCELED")
    if not st["log_rel"]:
        return {"step": st["step_no"], "lines": [], "next_cursor": 0, "eof": terminal}
    path = os.path.join(base, st["log_rel"])
    if not os.path.isfile(path):
        return {"step": st["step_no"], "lines": [], "next_cursor": cursor, "eof": terminal}
    size = os.path.getsize(path)
    cursor = max(0, min(int(cursor), size))
    with open(path, "rb") as fh:
        fh.seek(cursor)
        data = fh.read(LOG_MAX_BYTES)
    # 완결된 줄까지만(끝이 아니면)
    cut = data.rfind(b"\n") + 1
    if cursor + len(data) < size or not terminal:
        data = data[:cut]
    raw_lines = data.split(b"\n")
    if raw_lines and raw_lines[-1] == b"":
        raw_lines.pop()
    raw_lines = raw_lines[:LOG_MAX_LINES]
    consumed = min(len(data), sum(len(x) + 1 for x in raw_lines))
    lines = [x.rstrip(b"\r").decode("utf-8", errors="replace") for x in raw_lines]
    mask = _masker(ctx, principal)
    nxt = cursor + consumed
    return {"step": st["step_no"], "lines": [mask(x) for x in lines], "next_cursor": nxt,
            "eof": terminal and nxt >= size}


def check_inputs_changed(case: dict[str, Any]) -> list[str]:
    return changed_inputs(case["input_fingerprint"])


__all__ = ["create_job", "get_job", "cancel_job", "retry_job", "job_log", "case_inputs_hash"]
