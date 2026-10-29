"""비드 최적화 서비스(계약 esl_opt_run.md §3·§5·§7·§13): 설정, S1 확인, 평면도, 실행 생성·조회·파일.

- 백엔드는 코어 ``esl.opt`` 의 가벼운 함수만 부른다(size·identity·keepout·modes·settings·방법·출처). 쉘 솔버·대형 rad
  파싱은 워커(O3) 몫 — S1 Case rad 는 경로·include 검사만 하고 읽지 않는다.
- 실행 생성(`POST /opt/runs`): 입력 검사(S1 같은 모델 = topo_sha256, S2 크기 규칙 ±2 %/±5 %, 템플릿 ACTIVE, 금지 영역
  사각형, 전략·k·목표 기준) → ``opt_runs`` 행(설계·금지 영역 스냅샷) + OPT_RUN 작업(QUEUED). 산출물 폴더
  ``<esl_root>/_opt/<id>/`` 는 워커가 만든다(여기서는 경로 안전성만).
- 작업 params(워커 계약): {opt_run_id, scenario, title, settings{opt_run, core, library}, entries[{id, dir_rel, case_id,
  mode, inch, L_xi, L_eta, grid}], base(S1)|None, template(S2)|None, design{bead, nondesign_pids, keepout{rects, auto}},
  options{objective_norm, load_strategy, k, supports}, keepout_key{template_id|topo_sha256}}.
- 다운로드 ``rel`` 은 파일 목록에 있는 것만 + realpath 가 ``_opt/<id>/`` 안. 결과 폴더 쓰기 없음.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import uuid
from typing import Any

from sqlalchemy import null
from sqlalchemy.exc import IntegrityError

from ...core.auth import Principal
from ...core.config import opt_settings, opt_solver_status
from ...core.errors import DomainError, conflict, forbidden, not_found, unprocessable
from ...core.paths import OPT_DIR, check_includes, check_input_path, opt_run_dir, safe_case_file
from ...core.repositories import cases as cases_repo
from ...core.repositories import jobs as jobs_repo
from ...core.repositories import library as lib_repo
from ...core.repositories import opt as opt_repo
from ..context import AppContext
from . import bundle as bundle_svc
from .common import job_out, require_config_ok, require_execute, require_library_config
from .library import backfill_opt_meta, entry_folder, entry_size
from .opt_keepouts import validate_keepout
from .opt_templates import TEMPLATE_EXT, load_template, template_arrays, template_meta, template_preview


log = logging.getLogger("esl_platform.api")


def cfg(ctx: AppContext) -> dict[str, Any]:
    return opt_settings(ctx.settings)


def require_view(principal: Principal, project_id: str) -> None:
    if principal.role(project_id) is None:
        raise forbidden("이 프로젝트의 조회 권한이 없습니다")


def _esl_error(exc) -> DomainError:
    return unprocessable(exc.code, exc.message)


def public_reason(reason: str | None, principal: Principal | None) -> str | None:
    """솔버 미준비 사유: 서버 경로(': <경로>' 뒤)·설정 키('(…)')는 전역 관리자에게만, 일반 사용자는 문구 + '관리자 문의'."""
    if reason is None or (principal is not None and principal.is_global_admin):
        return reason
    head = re.split(r": |\(", reason, maxsplit=1)[0].rstrip()
    return f"{head} — 관리자 문의"


# ---------------------------------------------------------------- GET /opt/settings
def settings_out(ctx: AppContext, principal: Principal | None = None) -> dict[str, Any]:
    from ...core.opt_core import EslError
    from ...core.opt_core import load_method_sources

    o = cfg(ctx)
    ready, reason = opt_solver_status(ctx.settings)
    reason = public_reason(reason, principal)
    try:
        ms = load_method_sources()
    except EslError as exc:
        # 코드 스냅샷에 resources/opt_method_sources.json 이 없음(v0.7.1 이전 배포) 등 — 화면은 설명 없이 동작(프런트가 error 표시)
        log.warning("방법·출처 자료를 읽지 못함(GET /opt/settings method_sources.error): %s", exc.message)
        ms = {"error": exc.message if principal is not None and principal.is_global_admin else "방법·출처 자료를 읽지 못했습니다(관리자 문의)"}
    lo = o["loads"]
    return {"enabled": bool(o["enabled"]), "solver_ready": ready, "solver_reason": reason,
            "size": {k: o["size"][k] for k in ("tol_rel", "plate_tol_rel", "require_inch")},
            "bead_defaults": {k: float(o["bead_defaults"][k]) for k in ("angle", "min_width", "height")},
            "keepout_auto": {k: float(o["keepout"][k]) for k in ("hole_radius_mm", "edge_band_mm")},
            "loads": {"default_objective_norm": lo["default_objective_norm"], "default_strategy": lo["default_strategy"],
                      "mac_merge": float(lo["mac_merge"]), "max_cases": int(lo["max_cases"]),
                      "default_k": int(lo["default_k"])},
            "method_sources": ms, "max_rects": int(o["keepout"]["max_rects"]), "max_entries": int(o["max_entries"]),
            "template_max_elems": int(o["template"]["max_elems"]), "template_ext": list(TEMPLATE_EXT),
            "max_preview_points": int(o["ui"]["max_preview_points"])}


# ---------------------------------------------------------------- 항목 도우미
def entries_in_order(conn, project_id: str, ids: list[str]) -> list[dict[str, Any]]:
    """요청 순서(첫 행 = 기준)의 이 프로젝트 ACTIVE 항목. 중복 422 INVALID_PARAMS, 없음 422 ENTRY_NOT_FOUND."""
    if len(set(ids)) != len(ids):
        raise unprocessable("INVALID_PARAMS", "entry_ids 에 중복이 있습니다")
    rows = lib_repo.list_entries(conn, project_id=project_id, status="ACTIVE", ids=ids)
    by = {e["id"]: e for e in rows}
    miss = [i for i in ids if i not in by]
    if miss:
        raise unprocessable("ENTRY_NOT_FOUND", "이 프로젝트의 활성 라이브러리 항목이 아닙니다", entry_ids=miss)
    return [by[i] for i in ids]


def _size_row(e: dict[str, Any]) -> dict[str, Any]:
    sz = entry_size(e)
    g = ((e.get("summary") or {}).get("grid") or {})
    grid = (int(g["nx"]), int(g["ny"])) if g.get("nx") and g.get("ny") else None
    if sz["L_xi"] is None or sz["L_eta"] is None:
        raise unprocessable("SIZE_MISMATCH", f"{e['id']}: 크기(L_xi·L_eta) 정보가 없는 항목입니다", entry_id=e["id"])
    return {"entry_id": e["id"], "inch": sz["inch"], "L_xi": sz["L_xi"], "L_eta": sz["L_eta"], "grid": grid}


def _entry_meta(ctx: AppContext, e: dict[str, Any]) -> dict[str, Any]:
    try:
        with open(os.path.join(entry_folder(ctx, e), "entry.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        meta = None
    if not isinstance(meta, dict):
        raise conflict("PREREQUISITE_MISSING", f"라이브러리 항목 파일(entry.json)을 읽을 수 없습니다: {e['id']}",
                       missing=["entry_files"])
    return meta


def _entry_mesh(ctx: AppContext, e: dict[str, Any]):
    """(mesh, meta) — 항목 raw.npz(라이브러리 항목 = ESL 자신의 메시)."""
    from ...core.opt_core import EslError
    from ...core.opt_core import library_entry as lib_entry

    try:
        ent = lib_entry.load(entry_folder(ctx, e), raw=True)
        return ent.mesh(), ent.meta, ent.raw
    except (EslError, OSError, ValueError, KeyError, TypeError, AttributeError):
        raise conflict("PREREQUISITE_MISSING", f"라이브러리 항목 원본(raw.npz)을 읽을 수 없습니다: {e['id']}",
                       missing=["entry_files"]) from None


def _pids(mesh: dict[str, Any]) -> list[dict[str, Any]]:
    import numpy as np

    pid = np.asarray(mesh["elem_pid"], dtype=np.int64)
    t = np.asarray(mesh["thickness"], dtype=np.float64)
    E = np.broadcast_to(np.asarray(mesh["E"], dtype=np.float64), pid.shape)
    nu = np.broadcast_to(np.asarray(mesh["nu"], dtype=np.float64), pid.shape)
    out = []
    for p in np.unique(pid).tolist():
        m = pid == p
        out.append({"pid": int(p), "title": None, "n_elems": int(m.sum()), "thickness": float(np.median(t[m])),
                    "E": float(E[m][0]), "nu": float(nu[m][0])})
    return out


def _case_input_check(ctx: AppContext, case: dict[str, Any]) -> str:
    """기준 Case 입력 rad: 경로 검사 + include(Case 지문) input_roots 안. 파일은 읽지 않는다. 실패 409."""
    try:
        rad = check_input_path(ctx.settings, case["rad_path"], "RAD")
        incs = [i["path"] for i in ((case.get("input_fingerprint") or {}).get("includes") or []) if i.get("path")]
        check_includes(ctx.settings, incs)
    except DomainError as exc:
        raise conflict("PREREQUISITE_MISSING", "기준 Case 입력 rad 를 읽을 수 없습니다 — Case 입력을 다시 올리거나 템플릿 "
                       f"최적화를 쓰세요({exc.code}: {exc.message})", missing=["case_input"]) from None
    return rad


def _same_model_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = rows[0].get("topo_sha256")
    out = []
    for e in rows:
        t = e.get("topo_sha256")
        if not base or not t:
            out.append({"entry_id": e["id"], "same_model": False, "reason": "MODEL_INFO_MISSING"})
        elif t != base:
            out.append({"entry_id": e["id"], "same_model": False, "reason": "TOPOLOGY"})
        else:
            out.append({"entry_id": e["id"], "same_model": True, "reason": None})
    return out


def _s1_base(ctx: AppContext, conn, project_id: str, e: dict[str, Any], *, with_mesh: bool) -> dict[str, Any]:
    case = cases_repo.get_case(conn, e["case_id"])
    if case is None or case["project_id"] != project_id:
        raise conflict("PREREQUISITE_MISSING", "기준 ESL 의 Case 가 없습니다", missing=["case"])
    rad = _case_input_check(ctx, case)
    m = e.get("model") or {}
    base = {"entry_id": e["id"], "case_id": case["id"], "case_title": case["title"], "part_title": case["part_title"],
            "rad_path": rad, "rad_file_name": os.path.basename(rad), "n_nodes": m.get("n_nodes"),
            "n_elems": m.get("n_elems"), "topo_sha256": e.get("topo_sha256"), "pids": [], "supports": []}
    if with_mesh:
        mesh, meta, _raw = _entry_mesh(ctx, e)
        base.update(n_nodes=int(len(mesh["node_id"])), n_elems=int(len(mesh["elem_id"])), pids=_pids(mesh),
                    supports=list(((meta.get("esl") or {}).get("supports")) or []))
    else:
        meta = _entry_meta(ctx, e)
        base["supports"] = list(((meta.get("esl") or {}).get("supports")) or [])
    base["frame"] = meta.get("frame")
    base["_cumulative"] = bool((case.get("extract_summary") or {}).get("cumulative"))
    return base


# ---------------------------------------------------------------- POST /opt/s1-check
def s1_check(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    require_view(principal, body.project_id)
    with ctx.engine.connect() as conn:
        rows = entries_in_order(conn, body.project_id, list(body.entry_ids))
    rows = backfill_opt_meta(ctx, rows)
    with ctx.engine.connect() as conn:
        base = _s1_base(ctx, conn, body.project_id, rows[0], with_mesh=True)
    base.pop("frame", None)
    base.pop("rad_path", None)
    warns = []
    if base.pop("_cumulative", False):       # 계약 esl_cumulative_input.md §10 — 실행은 허용(정보)
        warns.append({"code": "S1_BASE_CUMULATIVE",
                      "message": "기준 Case 가 누적 낙하 씬입니다 — 최적화 형상 = 이전 런 변형 좌표(.str)·변형 두께"})
    return {"base": base, "entries": _same_model_rows(rows), "warnings": warns}


# ---------------------------------------------------------------- GET /opt/plan-view
def plan_view(ctx: AppContext, principal: Principal, template_id: str | None, entry_id: str | None) -> dict[str, Any]:
    from ...core.opt_core import EslError
    from ...core.opt_core import keepout

    if (template_id is None) == (entry_id is None):
        raise unprocessable("INVALID_PARAMS", "template_id 와 entry_id 중 정확히 하나가 필요합니다")
    o = cfg(ctx)
    limit = int(ctx.settings.view3d.max_nodes)
    if template_id is not None:
        with ctx.engine.connect() as conn:
            t = load_template(conn, template_id)
        if int(t["n_nodes"]) > limit:
            raise DomainError("PLAN_VIEW_TOO_LARGE", f"노드 {t['n_nodes']} > 상한 {limit}", status=413)
        pv = dict(template_preview(ctx, t))
        pv["key"] = {"template_id": t["id"], "topo_sha256": None}
        return pv
    with ctx.engine.connect() as conn:
        e = lib_repo.get_entry(conn, entry_id)
        if e is None:
            raise not_found("ENTRY_NOT_FOUND", "라이브러리 항목을 찾을 수 없습니다")
        require_view(principal, e["project_id"])
    n = (e.get("model") or {}).get("n_nodes")
    if isinstance(n, int) and n > limit:
        raise DomainError("PLAN_VIEW_TOO_LARGE", f"노드 {n} > 상한 {limit}", status=413)
    e = backfill_opt_meta(ctx, [e])[0]
    mesh, meta, _raw = _entry_mesh(ctx, e)
    if len(mesh["node_id"]) > limit:
        raise DomainError("PLAN_VIEW_TOO_LARGE", f"노드 {len(mesh['node_id'])} > 상한 {limit}", status=413)
    try:
        pv = keepout.plan_view(mesh, meta["frame"], o["keepout"], int(o["ui"]["max_preview_points"]))
    except EslError as exc:
        raise _esl_error(exc) from None
    pv["key"] = {"template_id": None, "topo_sha256": e.get("topo_sha256")}
    return pv


# ---------------------------------------------------------------- 직렬화
def run_dir(ctx: AppContext, r: dict[str, Any]) -> str:
    return opt_run_dir(ctx.settings, r["id"])


def run_out(ctx: AppContext, conn, r: dict[str, Any]) -> dict[str, Any]:
    d = dict(r)
    job = jobs_repo.get_job(conn, r["job_id"]) if r.get("job_id") else None
    d["job"] = job_out(conn, job, with_steps=True) if job else None
    d["state"] = job["state"] if job else "NONE"
    d["template"] = None
    if r.get("template_id"):
        t = opt_repo.get_template(conn, r["template_id"])
        if t is not None:
            d["template"] = {k: t[k] for k in ("id", "title", "status", "inch", "L_xi", "L_eta", "format", "file_name",
                                               "n_nodes", "n_elems")}
    base = dict(r["base"]) if r.get("base") else None
    if base is not None:
        base.pop("rad_path", None)       # 서버 경로는 응답에 넣지 않는다(파일명만)
    d["base"] = base
    folder = os.path.join(ctx.settings.storage.esl_root, *r["dir_rel"].split("/"))
    d["folder_path"] = folder
    rep = r.get("report_rel") or "report.html"
    p = os.path.join(folder, *rep.split("/"))
    d["report_ready"] = bool(r.get("report_rel")) and os.path.isfile(p) and not os.path.islink(p)
    return d


def load_run(conn, rid: str, *, for_update: bool = False) -> dict[str, Any]:
    r = opt_repo.get_run(conn, rid, for_update=for_update)
    if r is None:
        raise not_found("OPT_RUN_NOT_FOUND", "최적화 실행을 찾을 수 없습니다")
    return r


def list_runs(ctx: AppContext, principal: Principal, project_id: str | None, scenario: str | None) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        if project_id:
            require_view(principal, project_id)
            rows = opt_repo.list_runs(conn, project_id=project_id, scenario=scenario)
        elif principal.is_global_admin:
            rows = opt_repo.list_runs(conn, scenario=scenario)
        else:
            rows = opt_repo.list_runs(conn, project_ids=list(principal.roles), scenario=scenario)
        return [run_out(ctx, conn, r) for r in rows]


def get_run(ctx: AppContext, principal: Principal, rid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        r = load_run(conn, rid)
        require_view(principal, r["project_id"])
        return run_out(ctx, conn, r)


# ---------------------------------------------------------------- POST /opt/runs
def _options(o: dict[str, Any], body) -> dict[str, Any]:
    lo = o["loads"]
    op = body.options
    strategy = op.load_strategy or lo["default_strategy"]
    norm = op.objective_norm or lo["default_objective_norm"]
    mx = int(lo["max_cases"])
    if op.k is not None and not 1 <= int(op.k) <= mx:
        raise unprocessable("INVALID_PARAMS", f"k 는 1..{mx} (값 {op.k})")
    k = (int(op.k) if op.k is not None else int(lo["default_k"])) if strategy == "C" else None
    if body.scenario == "S1" and op.supports is not None:
        raise unprocessable("INVALID_PARAMS", "options.supports 는 템플릿 최적화(S2)에서만 지정합니다(S1 = 기준 ESL 3-2-1)")
    sup = [{"node_id": int(s.node_id), "dof": s.dof} for s in op.supports] if op.supports else None
    return {"objective_norm": norm, "load_strategy": strategy, "k": k, "supports": sup}


def _bead(o: dict[str, Any], body) -> dict[str, float]:
    b = dict(o["bead_defaults"])
    if body.design.bead is not None:
        b.update(body.design.bead.model_dump())
    b = {k: float(b[k]) for k in ("angle", "min_width", "height")}
    if not (0 < b["angle"] < 90) or b["min_width"] <= 0 or b["height"] <= 0:
        raise unprocessable("INVALID_PARAMS", f"비드 치수: 0 < 경사 < 90°, 폭·높이 > 0 (값 {b})")
    return b


def create_run(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    from ...core.opt_core import EslError
    from ...core.opt_core import modes
    from ...core.opt_core import size as osize

    require_execute(principal, body.project_id)
    require_config_ok(ctx)
    o = cfg(ctx)
    if not o["enabled"]:
        raise DomainError("OPT_RUN_DISABLED", "비드 최적화가 꺼져 있습니다(설정 opt_run.enabled)", status=503)
    ready, reason = opt_solver_status(ctx.settings)
    if not ready:
        raise DomainError("SOLVER_NOT_CONFIGURED", public_reason(reason, principal) or "서버 OptiStruct 가 설정되지 않았습니다",
                          status=503)
    lib_cfg = require_library_config(ctx)
    opts = _options(o, body)
    bead = _bead(o, body)
    if len(body.entry_ids) > int(o["max_entries"]):
        raise unprocessable("INVALID_PARAMS", f"ESL 은 최대 {o['max_entries']}개 (요청 {len(body.entry_ids)}개)")
    nd_pids = sorted({int(p) for p in (body.design.nondesign_pids or [])})
    with ctx.engine.connect() as conn:
        rows = entries_in_order(conn, body.project_id, list(body.entry_ids))
        if body.analysis_id:
            a = lib_repo.get_analysis(conn, body.analysis_id)
            if a is None or a["project_id"] != body.project_id:
                raise unprocessable("INVALID_PARAMS", "이 프로젝트의 종합분석이 아닙니다")
    rows = backfill_opt_meta(ctx, rows)
    base = template = size_res = None
    with ctx.engine.connect() as conn:
        if body.scenario == "S1":
            if body.template_id:
                raise unprocessable("INVALID_PARAMS", "template_id 는 템플릿 최적화(S2)에서만 지정합니다")
            same = _same_model_rows(rows)
            bad = [r for r in same if not r["same_model"]]
            if bad:
                raise unprocessable("MODEL_MISMATCH", f"기준 모델과 다른 ESL {len(bad)}개 — 기존 형상 최적화는 같은 모델만"
                                    "(다른 모델은 빼거나 템플릿 최적화 사용)", entries=bad)
            base = _s1_base(ctx, conn, body.project_id, rows[0], with_mesh=False)
            frame = base.pop("frame")
            base.pop("_cumulative", None)
            keepout_key = {"topo_sha256": base["topo_sha256"]}
        else:
            if not body.template_id:
                raise unprocessable("TEMPLATE_NOT_FOUND", "템플릿 최적화(S2)에는 template_id 가 필요합니다")
            t = opt_repo.get_template(conn, body.template_id)
            if t is None:
                raise unprocessable("TEMPLATE_NOT_FOUND", "템플릿을 찾을 수 없습니다")
            if t["status"] != "ACTIVE":
                raise unprocessable("TEMPLATE_ARCHIVED", "보관된 템플릿은 새 실행에 쓸 수 없습니다")
            try:
                size_res = osize.assert_ok([_size_row(e) for e in rows], o["size"],
                                           {"inch": t["inch"], "L_xi": t["L_xi"], "L_eta": t["L_eta"]})
            except EslError as exc:
                raise _esl_error(exc) from None
            tm = template_meta(ctx, t)
            frame = tm["frame"]
            if opts["supports"]:
                nids = {int(v) for v in template_arrays(ctx, t)["node_id"].tolist()}
                miss = [s["node_id"] for s in opts["supports"] if s["node_id"] not in nids]
                if miss:
                    raise unprocessable("INVALID_PARAMS", f"3-2-1 노드 {miss} 가 템플릿 메시에 없습니다")
            template = {"id": t["id"], "dir_rel": t["dir_rel"], "sha256": t["sha256"], "inch": t["inch"],
                        "L_xi": t["L_xi"], "L_eta": t["L_eta"], "format": t["format"]}
            keepout_key = {"template_id": t["id"]}
    ko = validate_keepout(ctx, [r.model_dump() for r in body.design.keepout.rects],
                          body.design.keepout.auto.model_dump(), frame)
    eff = [modes.effective(e.get("deform_mode")) for e in rows]
    if opts["load_strategy"] == "B" and not any(eff):
        raise unprocessable("NO_MODE_CANDIDATES", "전략 B: 변형 모드(덴팅·뒤틀림·굽힘)가 정해진 ESL 이 없습니다 — 모드를 "
                            "지정하거나 전략 A·C 를 쓰세요")
    rid = str(uuid.uuid4())
    opt_run_dir(ctx.settings, rid)          # 경로 안전성(실제 생성은 워커)
    design = {"bead": bead, "nondesign_pids": nd_pids, "keepout": {"rects": ko["rects"], "auto": ko["auto"]}}
    size_json = None
    if size_res is not None:
        size_json = _jsonable({"entries": size_res["entries"], "template": size_res["template"],
                               "warnings": size_res["warnings"]})
    warns = list(ko["warnings"]) + (list(size_res["warnings"]) if size_res else [])
    entries_p = [{"id": e["id"], "dir_rel": e["dir_rel"], "case_id": e["case_id"], "mode": m,
                  **entry_size(e), "grid": ((e.get("summary") or {}).get("grid"))} for e, m in zip(rows, eff)]
    params = {"opt_run_id": rid, "scenario": body.scenario, "title": body.title,
              "settings": {"opt_run": copy.deepcopy(o), "core": copy.deepcopy(ctx.config.core or {}),
                           "library": copy.deepcopy(lib_cfg)},
              "entries": entries_p, "base": base, "template": template, "design": design, "options": opts,
              "keepout_key": keepout_key, "warnings": warns}
    with ctx.engine.begin() as conn:
        r = opt_repo.insert_run(
            conn, id=rid, project_id=body.project_id, scenario=body.scenario, title=body.title,
            entry_ids=[e["id"] for e in rows], analysis_id=body.analysis_id, base=_jsonable(base) if base else null(),
            template_id=template["id"] if template else None, size=size_json if size_json is not None else null(),
            design=design, options=opts,
            load_strategy=opts["load_strategy"], objective_norm=opts["objective_norm"], k=opts["k"],
            dir_rel=f"{OPT_DIR}/{rid}", created_by=principal.user_id, created_by_name=principal.display_name)
        job = jobs_repo.insert_job(conn, case_id=None, opt_run_id=rid, project_id=body.project_id, job_type="OPT_RUN",
                                   params=_jsonable(params), created_by=principal.user_id,
                                   created_by_name=principal.display_name)
        if warns:
            from sqlalchemy import update

            from ...core.db.tables import jobs

            conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(warnings=warns))
        r = opt_repo.update_run(conn, rid, job_id=job["id"])
        return run_out(ctx, conn, r)


def _jsonable(o: Any) -> Any:
    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x)))


def retry_run(conn, principal: Principal, job: dict[str, Any]) -> dict[str, Any]:
    """OPT_RUN 재시도(계약 §8.3): 같은 실행 폴더·같은 params(실행 스냅샷 — 금지 영역·모드·전략 포함)로 처음부터.
    워커가 OPT_PREP 에서 입력 변경(S1 INPUT_CHANGED 경고)을 다시 확인하고, 덱 sha256 이 같으면 OS_SOLVE 를 재사용한다.
    보관(ARCHIVED) 템플릿이어도 허용."""
    r = opt_repo.get_run(conn, job["opt_run_id"], for_update=True)
    if r is None:
        raise not_found("OPT_RUN_NOT_FOUND", "최적화 실행을 찾을 수 없습니다")
    try:
        with conn.begin_nested():
            new = jobs_repo.insert_job(conn, case_id=None, opt_run_id=r["id"], project_id=job["project_id"],
                                       job_type="OPT_RUN", params=dict(job["params"]), created_by=principal.user_id,
                                       created_by_name=principal.display_name, retry_of_job_id=job["id"])
    except IntegrityError:
        raise conflict("JOB_ACTIVE", "이 최적화 실행의 작업이 대기 중이거나 실행 중입니다") from None
    opt_repo.update_run(conn, r["id"], job_id=new["id"])
    return job_out(conn, new, with_steps=True)


# ---------------------------------------------------------------- 파일·보고서·받기
def _kind(rel: str) -> str:
    top = rel.split("/", 1)[0]
    if rel == "report.html":
        return "report"
    if rel == "opt.json" or top == "post":
        return "result"
    if top == "load":
        return "selection"
    if top in ("deck", "solve", "target"):
        return top
    if top == "logs":
        return "log"
    return "other"


_ORDER = {"report": 0, "result": 1, "selection": 2, "deck": 3, "solve": 4, "target": 5, "log": 6, "other": 7}


def _walk_run(base: str) -> list[tuple[str, str]]:
    out = []
    for p, rel in bundle_svc._walk(base):
        if rel.startswith("solve/tmp/"):
            continue
        out.append((p, rel))
    return out


def list_files(ctx: AppContext, principal: Principal, rid: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        r = load_run(conn, rid)
        require_view(principal, r["project_id"])
    base = run_dir(ctx, r)
    lim = ctx.settings.ui.max_artifact_bytes
    out = []
    for p, rel in _walk_run(base) if os.path.isdir(base) else []:
        size = os.path.getsize(p)
        out.append({"rel": rel, "kind": _kind(rel), "size": size, "downloadable": size <= lim})
    out.sort(key=lambda x: (_ORDER[x["kind"]], x["rel"]))
    return out


def run_file(ctx: AppContext, principal: Principal, rid: str, rel: str) -> str:
    files = {f["rel"]: f for f in list_files(ctx, principal, rid)}
    with ctx.engine.connect() as conn:
        r = load_run(conn, rid)
    base = run_dir(ctx, r)
    path = safe_case_file(base, rel)
    if rel not in files or not os.path.isfile(path) or os.path.islink(path):
        raise not_found("FILE_NOT_FOUND", "파일이 없습니다")
    size = os.path.getsize(path)
    if size > ctx.settings.ui.max_artifact_bytes:
        raise DomainError("ARTIFACT_TOO_LARGE", "파일이 커서 다운로드할 수 없습니다. 폴더를 직접 여세요", status=413,
                          rel=rel, path=path, size=size, limit=ctx.settings.ui.max_artifact_bytes)
    return path


def run_report(ctx: AppContext, principal: Principal, rid: str) -> str:
    with ctx.engine.connect() as conn:
        r = load_run(conn, rid)
        require_view(principal, r["project_id"])
    path = safe_case_file(run_dir(ctx, r), r.get("report_rel") or "report.html")
    if not os.path.isfile(path) or os.path.islink(path):
        raise not_found("REPORT_NOT_FOUND", "보고서가 아직 없습니다(최적화 완료 후 생성)")
    return path


def bead_map(ctx: AppContext, principal: Principal, rid: str) -> str:
    with ctx.engine.connect() as conn:
        r = load_run(conn, rid)
        require_view(principal, r["project_id"])
    path = safe_case_file(run_dir(ctx, r), "post/bead_map.png")
    if not os.path.isfile(path) or os.path.islink(path):
        raise not_found("FILE_NOT_FOUND", "비드 맵이 아직 없습니다(후처리 완료 후 생성)")
    return path


OPT_PARTS = ("report", "result", "deck", "solve", "raw")
OPT_DEFAULT = ("report", "result", "deck")


def run_bundle(ctx: AppContext, principal: Principal, rid: str, parts_raw: str | None) -> dict[str, Any]:
    parts = bundle_svc.parse_parts(parts_raw, OPT_PARTS, OPT_DEFAULT)
    with ctx.engine.connect() as conn:
        r = load_run(conn, rid)
        require_view(principal, r["project_id"])
    base = run_dir(ctx, r)
    raw = "raw" in parts
    files = []
    for p, rel in _walk_run(base) if os.path.isdir(base) else []:
        k = _kind(rel)
        low = rel.lower()
        take = (("report" in parts and k == "report") or ("result" in parts and k in ("result", "selection"))
                or ("deck" in parts and k == "deck") or ("solve" in parts and k == "solve")
                or (raw and k == "target"))
        if take and low.endswith(".npz") and not raw:
            take = False
        if take:
            files.append((p, rel))
    if not files:
        raise not_found("BUNDLE_EMPTY", "받을 최적화 파일이 아직 없습니다")
    size = bundle_svc._check_size(ctx, files, base)
    return {"files": files, "prefix": f"opt_{rid}", "filename": f"opt_{rid}.zip", "size": size}
