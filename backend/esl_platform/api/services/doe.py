"""비드 형상 DOE 서비스(계약 esl_bead_doe.md §10): 설정, 입력 검사, 연구 생성·조회·복제, 변수 표·평면도, 행렬·미리보기·실행,
결과·파일·보고서·3D 비교.

경계(§17): 백엔드는 코어 ``esl.doe`` 의 가벼운 함수(settings·matrix·paicad_io 결과 읽기·scenario 폴더 검사·물성 기본값)와
``esl.opt`` size·identity·mesh_check 만 쓴다(어댑터 ``core.opt_core``). paicad·gmsh·쉘 솔버·대형 rad 파싱은 워커 몫 —
① Case 입력 rad 는 경로·include 검사와 폴더 크기(stat)만 본다. paicad 사용 가능 여부는 워커가 heartbeat ``info.paicad``·
``info.gmsh`` 에 기록한 값만 읽는다(§6.5).

쓰기: DB(bead_does·jobs·uploads.result)만. 연구 폴더 ``<esl_root>/_doe/<id>/`` 는 워커가 만든다(여기서는 경로 안전성만).
Case 입력·업로드 폴더는 읽기만.

작업 params(워커 D3 계약, DOE_PREP·DOE_PREVIEW·DOE_RUN 공통)::

    {"bead_doe_id": <id>, "kind": "PREP"|"PREVIEW"|"RUN", "out_rel": "_doe/<id>",
     "doe": <esl.doe.stages spec["doe"] 그대로 — 워커는 spec = {"stage", "out": <esl_root>/_doe/<id>, "progress_path",
             "doe": params["doe"] (+ design·paicad·paicad_version)} 로 run_stage 호출>:
        {id, scenario, title, created_at, cfg{bead_doe, opt_run, commands(paicad_*)}, core, mapping,
         entries[{id, dir(절대), label, case}], base?{entry_id, case_id, rad_path, part_title, case_dir}(①),
         step{path, file_name, sha256, upload_id}, mesh?{path, upload_root(업로드 폴더), part_title, sha256, upload_id}(②),
         inch, props?{t,E,nu}(③), mesh_size_mm?(③),
         rev·spec·matrix_sha256 (PREVIEW·RUN), run{solver, parallel} (RUN)},
     "warnings": [...]}

DB 등록(워커 BD_*_REGISTER → ``repositories.doe.update_study``):
- BD_PREP_REGISTER: phase READY, prep = {n_beads, n_params, paicad_version, warnings[{code, message}], boundary{n_warn,
  n_info}|null}, paicad_version.
- BD_PREVIEW_REGISTER: phase PREVIEW_READY, doe.preview = {rev, matrix_sha256, ok, skipped{collision, fixed, geom}}
  (doe 의 나머지 키 유지). 셀 상태는 백엔드가 doe/<rev>/grid/grid_manifest.json 에서 읽는다.
- BD_REGISTER: phase DONE, result = post/result.json 요약, report_rel = "report.html".
작업이 실패·취소되면 phase 는 바꾸지 않는다 — 응답 phase 는 최근 작업 상태로 파생(PREP→FAILED, PREVIEW→READY, RUN→FAILED).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Any

from sqlalchemy import null
from sqlalchemy.exc import IntegrityError

from ...core.auth import Principal
from ...core.config import bead_doe_commands, bead_doe_settings, opt_settings, paicad_exe_status
from ...core.errors import DomainError, conflict, forbidden, not_found, unprocessable
from ...core.paths import DOE_DIR, doe_dir, safe_case_file
from ...core.repositories import doe as doe_repo
from ...core.repositories import jobs as jobs_repo
from ...core.repositories.cases import VersionConflict
from ..context import AppContext
from . import bundle as bundle_svc
from . import uploads as up_svc
from .common import job_out, require_config_ok, require_execute, require_library_config
from .library import backfill_opt_meta, entry_folder, require_eligible, require_eligible_ids
from .opt import _entry_mesh, _s1_base, _same_model_rows, _size_row, entries_in_order

log = logging.getLogger("esl_platform.api")

TERMINAL = ("SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED")
DID_RE = re.compile(r"^[0-9a-z_]{1,64}$")
BEAD_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
VIEW3D_FILES = {"part.glb": "model/gltf-binary", "part_lod.glb": "model/gltf-binary",
                "values.bin": "application/octet-stream"}
ERROR_CODES_422 = ("DOE_PARAM_UNKNOWN", "DOE_RANGE_INVALID", "DOE_TOO_LARGE", "DOE_NO_PARAMS")


# ---------------------------------------------------------------- 공통
def cfg(ctx: AppContext) -> dict[str, Any]:
    return bead_doe_settings(ctx.settings)


def require_view(principal: Principal, project_id: str) -> None:
    if principal.role(project_id) is None:
        raise forbidden("이 프로젝트의 조회 권한이 없습니다")


def _jsonable(o: Any) -> Any:
    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x)))


def _read_json(path: str, max_mb: float) -> Any:
    """연구 폴더 안 JSON(크기 상한 후 파싱, §15). 없거나 깨졌으면 None."""
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > max_mb * 1024 * 1024:
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def study_dir(ctx: AppContext, s: dict[str, Any]) -> str:
    return doe_dir(ctx.settings, s["id"])


def load_study(conn, sid: str, *, for_update: bool = False) -> dict[str, Any]:
    s = doe_repo.get_study(conn, sid, for_update=for_update)
    if s is None:
        raise not_found("DOE_NOT_FOUND", "강성 평가 스터디를 찾을 수 없습니다")
    return s


def _max_mb(c: dict[str, Any]) -> float:
    return float(c["limits"]["max_json_mb"])


# ---------------------------------------------------------------- 사용 가능 여부(§6.5)
_STATUS_CACHE: dict[int, tuple[float, dict[str, Any] | None]] = {}
_STATUS_LOCK = threading.Lock()


def _worker_record(ctx: AppContext, c: dict[str, Any]) -> dict[str, Any] | None:
    ttl = float(c.get("settings_cache_s") or 0)
    key = id(ctx)
    now = time.monotonic()
    with _STATUS_LOCK:
        hit = _STATUS_CACHE.get(key)
        if hit is not None and ttl > 0 and now - hit[0] < ttl:
            return hit[1]
    with ctx.engine.connect() as conn:
        rec = doe_repo.paicad_record(conn)
    with _STATUS_LOCK:
        _STATUS_CACHE[key] = (now, rec)
    return rec


def reset_status_cache() -> None:
    with _STATUS_LOCK:
        _STATUS_CACHE.clear()


def status(ctx: AppContext) -> dict[str, Any]:
    """{enabled, reason, paicad{ready, version, pinned, warning}, gmsh{ready, version}, scenarios{same, mesh, step}}."""
    c = cfg(ctx)
    ok, reason = paicad_exe_status(ctx.settings)
    rec = _worker_record(ctx, c) if ok else None
    pc = (rec or {}).get("paicad") or {}
    gm = (rec or {}).get("gmsh") or {}
    paicad = {"ready": False, "version": pc.get("version"), "pinned": c["paicad"].get("pinned_version"),
              "warning": pc.get("warning")}
    if ok:
        if not pc:
            reason = "PAICAD_CHECK_FAILED"           # 워커 점검 기록 없음(워커가 아직 점검 전·오프라인)
        elif not pc.get("ready"):
            reason = pc.get("reason") or "PAICAD_CHECK_FAILED"
        else:
            paicad["ready"] = True
    gmsh = {"ready": bool(gm.get("ready")), "version": gm.get("version")}
    enabled = reason is None
    return {"enabled": enabled, "reason": reason, "paicad": paicad, "gmsh": gmsh,
            "scenarios": {"same": enabled, "mesh": enabled, "step": enabled and gmsh["ready"]}}


def require_enabled(ctx: AppContext, scenario: str | None = None) -> dict[str, Any]:
    st = status(ctx)
    if not st["enabled"]:
        raise DomainError(st["reason"] or "DOE_DISABLED", _disabled_message(st["reason"]), status=503)
    if scenario == "step" and not st["gmsh"]["ready"]:
        raise DomainError("GMSH_UNAVAILABLE", "메시 생성기(gmsh)가 없어 'STEP만' 시나리오를 쓸 수 없습니다(관리자 문의)",
                          status=503)
    return st


def _disabled_message(reason: str | None) -> str:
    if reason == "DOE_DISABLED":
        return "강성 평가 스터디가 꺼져 있습니다(설정 bead_doe.enabled — 관리자 문의)"
    try:
        from ...core.opt_core import doe_message

        msg = doe_message(reason or "PAICAD_NOT_CONFIGURED")
        if msg and msg != reason:
            return msg
    except Exception:  # noqa: BLE001 - 자료 파일이 없어도 문구는 낸다
        pass
    return "형상 엔진(paicad)이 설치되지 않았습니다(관리자 문의)"


def method_sources(principal: Principal | None) -> dict[str, Any]:
    """resources/doe_method_sources.json → 화면 형식 {version, summary_ko, methods{lhs,halton,fullfact}, metrics{score,
    sensitivity}, limits[], sources[]} (원본 1곳, 보고서와 같은 자료)."""
    from ...core.opt_core import EslError, doe_load_method_sources

    try:
        ms = doe_load_method_sources()
    except EslError as exc:
        log.warning("강성 평가 스터디 방법·출처 자료를 읽지 못함: %s", exc.message)
        return {"error": exc.message if principal is not None and principal.is_global_admin
                else "방법·출처 자료를 읽지 못했습니다(관리자 문의)"}
    m = ms.get("methods") or {}
    return {"version": ms["version"], "summary_ko": list(ms["summary_ko"]),
            "methods": {k: m[k] for k in ("lhs", "halton", "fullfact") if k in m},
            "metrics": {k: v for k, v in m.items() if k not in ("lhs", "halton", "fullfact")},
            "limits": list(ms.get("limits_ko") or []), "sources": list(ms["sources"])}


# ---------------------------------------------------------------- GET /doe/settings
def settings_out(ctx: AppContext, principal: Principal | None = None) -> dict[str, Any]:
    c = cfg(ctx)
    st = status(ctx)
    d = c["doe"]
    return {**st, "max_entries": int(c["max_entries"]), "max_designs": int(c["max_designs"]),
            "doe": {"methods": ["lhs", "halton", "fullfact"], "default_method": d["default_method"],
                    "default_n": int(d["default_n"]), "seed": int(d["seed"]), "levels_default": int(d["levels_default"]),
                    "levels_max": int(d["levels_max"]), "default_types": list(d["default_types"])},
            "mesh": {"size_auto": True, "size_min_mm": float(c["mesh"]["size_min_mm"]),
                     "size_max_mm": float(c["mesh"]["size_max_mm"])},
            "boundary": {k: float(c["boundary"][k]) for k in ("fastener_warn_mm", "load_warn_mm", "load_share_min")},
            "step_max_mb": float(c["step_max_mb"]), "part_title": c["part_title"],
            "method_sources": method_sources(principal)}


# ---------------------------------------------------------------- POST /doe/check-inputs
def _esl_error(exc) -> DomainError:
    return unprocessable(exc.code, exc.message)


def _step_input(ctx: AppContext, principal: Principal, body, c: dict[str, Any]) -> tuple[dict[str, Any], dict]:
    up, _root, path = up_svc.doe_source(ctx, principal, body.step_upload_id, body.project_id, "step")
    info = up_svc.step_check(path, float(c["step_max_mb"]))
    sha = up_svc.upload_file_sha(up, path)
    rel = os.path.relpath(path, up["dir_path"]).replace(os.sep, "/")
    up_svc.save_doe_check(ctx, up["id"], up_svc.DOE_STEP_PURPOSE, rel, sha, True)
    return {"file_name": info["file_name"], "sha256": sha, "size_mb": info["size_mb"]}, \
        {"path": path, "file_name": info["file_name"], "sha256": sha, "upload_id": up["id"]}


def _mesh_input(ctx: AppContext, principal: Principal, body, c: dict[str, Any], rows: list[dict[str, Any]]):
    """② B 메시: 업로드 밖 include 거부·메시 검사(v0.7.0 템플릿 검사와 같은 함수) + 크기 규칙(B = 템플릿 자리)."""
    from ...core.opt_core import EslError
    from ...core.opt_core import size as osize
    from .opt_templates import _run_check

    if not body.mesh_upload_id:
        raise unprocessable("INVALID_PARAMS", "'다른 모델(메시 있음)'에는 mesh_upload_id 가 필요합니다")
    up, _root, path = up_svc.doe_source(ctx, principal, body.mesh_upload_id, body.project_id, "mesh")
    part_title = body.part_title or c["part_title"]
    chk = _run_check(ctx, up, path, part_title)
    sha = up_svc.upload_file_sha(up, path)
    fr = chk.get("frame") or {}
    if not chk.get("ok") or fr.get("L_xi") is None or fr.get("L_eta") is None:
        errs = (chk.get("quality") or {}).get("errors") or []
        raise unprocessable("MESH_INVALID", "B 메시 검사 오류: " + "; ".join(e.get("message", "") for e in errs[:5]),
                            errors=errs)
    o = opt_settings(ctx.settings)
    try:
        res = osize.assert_ok([_size_row(e) for e in rows], o["size"],
                              {"inch": body.inch, "L_xi": fr["L_xi"], "L_eta": fr["L_eta"]})
    except EslError as exc:
        raise _esl_error(exc) from None
    med = ((res.get("template") or {}).get("median")) or {}
    size = {"L_xi": float(fr["L_xi"]), "L_eta": float(fr["L_eta"]), "inch": body.inch,
            "rel_xi": (float(fr["L_xi"]) / float(med["L_xi"]) - 1.0) if med.get("L_xi") else 0.0,
            "rel_eta": (float(fr["L_eta"]) / float(med["L_eta"]) - 1.0) if med.get("L_eta") else 0.0}
    up_svc.save_doe_check(ctx, up["id"], up_svc.DOE_MESH_PURPOSE, chk["rel"], sha, True,
                          {"part_title": chk.get("part_title")})
    warns = [{"code": "SIZE_WARNING", "message": w} for w in res.get("warnings") or []]
    warns += [{"code": w.get("code") or "MESH_WARNING", "message": w.get("message")}
              for w in (chk.get("quality") or {}).get("warnings") or [] if isinstance(w, dict)]
    mesh_p = {"path": path, "upload_root": up["dir_path"], "part_title": chk.get("part_title") or part_title,
              "sha256": sha, "file_name": os.path.basename(path), "upload_id": up["id"]}
    return chk, size, warns, mesh_p


def check_inputs(ctx: AppContext, principal: Principal, body, *, _internal: bool = False) -> dict[str, Any]:
    """DoeCheckOut. ``_internal`` 이면 (DoeCheckOut, 작업 params 재료) 를 돌려준다(연구 생성이 같은 검사를 쓴다)."""
    from ...core.opt_core import EslError
    from ...core.opt_core import doe_scenario

    require_execute(principal, body.project_id)
    require_config_ok(ctx)
    c = cfg(ctx)
    require_enabled(ctx, body.scenario)
    if len(body.entry_ids) > int(c["max_entries"]):
        raise unprocessable("INVALID_PARAMS", f"ESL 은 최대 {c['max_entries']}개 (요청 {len(body.entry_ids)}개)")
    if body.scenario != "mesh" and (body.mesh_upload_id or body.part_title):
        raise unprocessable("INVALID_PARAMS", "mesh_upload_id·part_title 은 '다른 모델(메시 있음)'에서만 지정합니다")
    with ctx.engine.connect() as conn:
        rows = entries_in_order(conn, body.project_id, list(body.entry_ids))
    rows = backfill_opt_meta(ctx, rows)
    step_out, step_p = _step_input(ctx, principal, body, c)
    out: dict[str, Any] = {"ok": True, "step": step_out, "base": None, "mesh": None, "entries": [], "size": None,
                           "props_default": None, "mesh_size_default_mm": None, "warnings": []}
    mat: dict[str, Any] = {"rows": rows, "step": step_p, "base": None, "base_db": None, "mesh": None,
                           "props_default": None, "mesh_size_default_mm": None}
    if body.scenario == "same":
        same = _same_model_rows(rows)
        out["entries"] = [{"entry_id": r["entry_id"], "ok": bool(r["same_model"]), "reason": r["reason"]} for r in same]
        out["ok"] = all(r["same_model"] for r in same)
        with ctx.engine.connect() as conn:
            base = _s1_base(ctx, conn, body.project_id, rows[0], with_mesh=False)
        base.pop("frame", None)
        cumulative = base.pop("_cumulative", False)
        case_in = os.path.dirname(base["rad_path"])
        try:
            assem = doe_scenario.assem_dir_check(case_in, float(c["same"]["max_assem_mb"]))
        except EslError as exc:
            raise _esl_error(exc) from None
        if cumulative:
            out["warnings"].append({"code": "BD_BASE_CUMULATIVE",
                                    "message": "기준 Case 가 누적 낙하 씬입니다 — 형상 = rad /NODE 공칭, ESL 은 누적 변형 상태 기준"})
        out["base"] = {"entry_id": base["entry_id"], "case_id": base["case_id"], "case_title": base.get("case_title"),
                       "part_title": base.get("part_title"), "n_nodes": base.get("n_nodes"),
                       "n_elems": base.get("n_elems"), "topo_sha256": base.get("topo_sha256")}
        mat["base"] = {"entry_id": base["entry_id"], "case_id": base["case_id"], "rad_path": base["rad_path"],
                       "part_title": base.get("part_title"), "case_dir": case_in}
        mat["base_db"] = {**out["base"], "rad_file_name": base.get("rad_file_name"), "assem": assem}
    else:
        out["entries"] = [{"entry_id": e["id"], "ok": True, "reason": None} for e in rows]
        if body.scenario == "mesh":
            chk, size, warns, mesh_p = _mesh_input(ctx, principal, body, c, rows)
            out.update(mesh=chk, size=size)
            out["warnings"] += warns
            mat["mesh"] = mesh_p
        else:
            from ...core.opt_core import size as osize

            try:
                osize.assert_ok([_size_row(e) for e in rows], opt_settings(ctx.settings)["size"])
            except EslError as exc:
                raise _esl_error(exc) from None
            _mesh, _meta, raw = _entry_mesh(ctx, rows[0])
            try:
                pd = doe_scenario.props_default(raw)
                h = doe_scenario.mesh_size_default(raw, c["mesh"])
            except (EslError, KeyError, ValueError) as exc:
                raise unprocessable("MESH_INVALID", f"기준 ESL 메시에서 물성·요소 크기 기본값을 얻지 못했습니다: {exc}") from None
            out["props_default"] = {"t": float(pd["t"]), "E": float(pd["E"]), "nu": float(pd["nu"])}
            out["mesh_size_default_mm"] = round(float(h), 3)
            mat["props_default"] = out["props_default"]
            mat["mesh_size_default_mm"] = out["mesh_size_default_mm"]
    out = _jsonable(out)
    if _internal:
        return {"out": out, "mat": mat}
    return out


# ---------------------------------------------------------------- 직렬화
def _derived_phase(s: dict[str, Any], job: dict[str, Any] | None) -> str:
    ph = s["phase"]
    if job is not None and job["state"] in ("FAILED", "CANCELED", "INTERRUPTED") and ph in ("PREP", "PREVIEW", "RUN"):
        if ph == "PREVIEW":
            return "READY"
        return "FAILED"
    return ph


def _grid_dir(ctx: AppContext, s: dict[str, Any], rev: int) -> str:
    return os.path.join(study_dir(ctx, s), "doe", str(int(rev)), "grid")


def _matrix_doc(ctx: AppContext, s: dict[str, Any], rev: int, c: dict[str, Any]) -> dict[str, Any] | None:
    m = _read_json(os.path.join(study_dir(ctx, s), "doe", str(int(rev)), "matrix.json"), _max_mb(c))
    return m if isinstance(m, dict) and isinstance(m.get("designs"), list) else None


def _cell_thumb(gdir: str, manifest: dict[str, Any], did: str) -> str | None:
    """셀(또는 공칭 d000) 썸네일 경로(grid 폴더 안, 링크 아님) 또는 None."""
    rels: list[str] = []
    if did == "d000":
        nom = manifest.get("nominal") if isinstance(manifest, dict) else None
        if isinstance(nom, dict) and isinstance(nom.get("thumb"), str):
            rels.append(nom["thumb"])
        rels += ["nominal/thumb.png", "cells/nominal/thumb.png", "nominal.png"]
    else:
        for cell in (manifest or {}).get("cells") or []:
            if isinstance(cell, dict) and cell.get("id") == did and isinstance(cell.get("thumb"), str):
                rels.append(cell["thumb"])
        rels.append(f"cells/{did}/thumb.png")
    for rel in rels:
        try:
            p = safe_case_file(gdir, rel)
        except DomainError:
            continue
        if os.path.isfile(p) and not os.path.islink(p):
            return p
    return None


def preview_cells(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> list[dict[str, Any]] | None:
    """미리보기 셀 [{id, values, status, code, thumb}] (d000 제외) — doe/<rev>/grid/grid_manifest.json + matrix.json."""
    from ...core.opt_core import EslError
    from ...core.opt_core import doe_paicad_io as pio

    pv = (s.get("doe") or {}).get("preview")
    if not isinstance(pv, dict) or pv.get("rev") is None:
        return None
    rev = int(pv["rev"])
    m = _matrix_doc(ctx, s, rev, c)
    if m is None:
        return None
    ids = [d["id"] for d in m["designs"] if d.get("id") != "d000"]
    gdir = _grid_dir(ctx, s, rev)
    try:
        g = pio.read_grid(gdir, ids, _max_mb(c))
    except (EslError, OSError, ValueError):
        return None
    by = {r["id"]: r for r in g["cells"]}
    out = []
    for d in m["designs"]:
        if d.get("id") == "d000":
            continue
        r = by.get(d["id"]) or {"state": "SKIPPED_GEOM", "code": "GRID_CELL_MISSING", "warning": None}
        thumb = r.get("warning") != "THUMB_UNAVAILABLE" and _cell_thumb(gdir, g.get("manifest") or {}, d["id"]) is not None
        out.append({"id": d["id"], "values": d.get("values") or {}, "status": r["state"], "code": r.get("code"),
                    "thumb": bool(thumb)})
    return out


def _doe_out(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> dict[str, Any] | None:
    doe = s.get("doe")
    if not isinstance(doe, dict):
        return None
    d = {k: doe.get(k) for k in ("rev", "spec", "matrix_sha256", "n_designs")}
    pv = doe.get("preview")
    if isinstance(pv, dict):
        p = {"rev": pv.get("rev"), "matrix_sha256": pv.get("matrix_sha256"), "ok": int(pv.get("ok") or 0),
             "skipped": {k: int((pv.get("skipped") or {}).get(k) or 0) for k in ("collision", "fixed", "geom")}}
        cells = preview_cells(ctx, s, c)
        if cells is not None:
            p["cells"] = cells
        d["preview"] = p
    else:
        d["preview"] = None
    return d


def study_out(ctx: AppContext, conn, s: dict[str, Any], job: dict[str, Any] | None = None, *,
              c: dict[str, Any] | None = None, with_job_lookup: bool = True) -> dict[str, Any]:
    c = c or cfg(ctx)
    if job is None and with_job_lookup:
        job = doe_repo.latest_job(conn, s["id"])
    phase = _derived_phase(s, job)
    inputs = dict(s.get("inputs") or {})
    rr = False
    if phase == "DONE" and s.get("result") is not None:
        rr = True
    prep = s.get("prep")
    if isinstance(prep, dict):
        prep = {"n_beads": int(prep.get("n_beads") or 0), "n_params": int(prep.get("n_params") or 0),
                "paicad_version": prep.get("paicad_version") or s.get("paicad_version"),
                "warnings": list(prep.get("warnings") or []),
                "boundary": prep.get("boundary") or {"n_warn": 0, "n_info": 0}}
    return {"id": s["id"], "project_id": s["project_id"], "scenario": s["scenario"], "title": s["title"],
            "entry_ids": list(s["entry_ids"]), "inputs": inputs, "phase": phase, "version": int(s["version"]),
            "prep": prep, "doe": _doe_out(ctx, s, c), "job": job_out(conn, job, with_steps=True) if job else None,
            "result_ready": rr, "created_by_name": s["created_by_name"], "created_at": s["created_at"]}


def list_studies(ctx: AppContext, principal: Principal, project_id: str | None) -> list[dict[str, Any]]:
    c = cfg(ctx)
    with ctx.engine.connect() as conn:
        if project_id:
            require_view(principal, project_id)
            rows = doe_repo.list_studies(conn, project_id=project_id)
        elif principal.is_global_admin:
            rows = doe_repo.list_studies(conn)
        else:
            rows = doe_repo.list_studies(conn, project_ids=list(principal.roles))
        jobs = doe_repo.latest_jobs(conn, [r["id"] for r in rows])
        return [study_out(ctx, conn, r, jobs.get(r["id"]), c=c, with_job_lookup=False) for r in rows]


def get_study(ctx: AppContext, principal: Principal, sid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        s = load_study(conn, sid)
        require_view(principal, s["project_id"])
        return study_out(ctx, conn, s)


def _viewable(ctx: AppContext, principal: Principal, sid: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    with ctx.engine.connect() as conn:
        s = load_study(conn, sid)
        require_view(principal, s["project_id"])
        return s, doe_repo.latest_job(conn, sid)


# ---------------------------------------------------------------- POST /doe/studies
def _entry_label(e: dict[str, Any]) -> str:
    m = e.get("model") or {}
    sc = e.get("scene") or {}
    parts = [str(m.get("name") or ""), str(sc.get("drop_type") or ""), str(sc.get("scene_no") or "")]
    return " ".join(p for p in parts if p).strip() or e["id"]


def _snapshot_cfg(ctx: AppContext) -> dict[str, Any]:
    return {"bead_doe": cfg(ctx), "opt_run": opt_settings(ctx.settings), "commands": bead_doe_commands(ctx.settings)}


def _validate_step_extras(body, c: dict[str, Any], mat: dict[str, Any]) -> tuple[dict | None, float | None]:
    if body.scenario != "step":
        if body.props is not None or body.mesh_size_mm is not None:
            raise unprocessable("INVALID_PARAMS", "props·mesh_size_mm 은 '다른 모델(STEP만)'에서만 지정합니다")
        return None, None
    props = body.props.model_dump() if body.props is not None else dict(mat["props_default"])
    h = float(body.mesh_size_mm) if body.mesh_size_mm is not None else float(mat["mesh_size_default_mm"])
    lo, hi = float(c["mesh"]["size_min_mm"]), float(c["mesh"]["size_max_mm"])
    if not lo <= h <= hi:
        raise unprocessable("INVALID_PARAMS", f"요소 크기는 {lo:g}..{hi:g} mm (값 {h:g})")
    return {k: float(props[k]) for k in ("t", "E", "nu")}, h


def _insert_study_job(ctx: AppContext, principal: Principal, *, sid: str, project_id: str, scenario: str, title: str,
                      entry_ids: list[str], base_db: dict | None, inputs: dict[str, Any], params: dict[str, Any],
                      warns: list) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        s = doe_repo.insert_study(conn, id=sid, project_id=project_id, scenario=scenario, title=title,
                                  entry_ids=entry_ids, base=_jsonable(base_db) if base_db else null(),
                                  inputs=_jsonable(inputs), phase="PREP", dir_rel=f"{DOE_DIR}/{sid}",
                                  created_by=principal.user_id, created_by_name=principal.display_name)
        job = _insert_job(conn, principal, s, "DOE_PREP", params, warns=warns)
        return study_out(ctx, conn, s, job)


def _insert_job(conn, principal: Principal, s: dict[str, Any], job_type: str, params: dict[str, Any], *,
                warns: list | None = None, retry_of: str | None = None, resume: int | None = None) -> dict[str, Any]:
    # MR-D-10: 스터디의 모든 작업(준비·미리보기·실행·재시도)은 대상 ESL 이 지금도 적격일 때만(통합 검증 지적 1c)
    require_eligible_ids(conn, s.get("entry_ids"))
    try:
        with conn.begin_nested():
            job = jobs_repo.insert_job(conn, case_id=None, bead_doe_id=s["id"], project_id=s["project_id"],
                                       job_type=job_type, params=_jsonable(params), created_by=principal.user_id,
                                       created_by_name=principal.display_name, retry_of_job_id=retry_of,
                                       resume_from_step=resume)
    except IntegrityError:
        raise conflict("JOB_ACTIVE", "이 강성 평가 스터디의 작업이 대기 중이거나 실행 중입니다") from None
    if warns:
        from sqlalchemy import update

        from ...core.db.tables import jobs

        conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(warnings=_jsonable(warns)))
        job = jobs_repo.get_job(conn, job["id"])
    return job


def create_study(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    c = cfg(ctx)
    r = check_inputs(ctx, principal, body, _internal=True)
    out, mat = r["out"], r["mat"]
    require_eligible(mat["rows"])                 # v0.10.0 MR-D-10: 현재 기준 PASS 항목만(422 ENTRY_NOT_ELIGIBLE)
    if body.scenario == "same" and not out["ok"]:
        bad = [e for e in out["entries"] if not e["ok"]]
        raise unprocessable("MODEL_MISMATCH", f"기준 모델과 다른 ESL {len(bad)}개 — '같은 모델' DOE 는 같은 모델만"
                            "(다른 모델은 빼거나 '다른 모델' 시나리오 사용)", entries=bad)
    props, h = _validate_step_extras(body, c, mat)
    lib_cfg = require_library_config(ctx)
    rows = mat["rows"]
    sid = str(uuid.uuid4())
    doe_dir(ctx.settings, sid)                    # 경로 안전성(실제 생성은 워커)
    title = (body.title or "").strip() or f"강성 평가 스터디 {out['step']['file_name']}"
    part_title = (mat["mesh"] or {}).get("part_title") if body.scenario == "mesh" else (
        (mat["base"] or {}).get("part_title") if body.scenario == "same" else None)
    step_p = mat["step"]
    inputs = {"step": {"upload_id": step_p["upload_id"], "file_name": step_p["file_name"], "sha256": step_p["sha256"]},
              "mesh": None, "part_title": part_title, "inch": body.inch, "props": props, "mesh_size_mm": h}
    if mat["mesh"]:
        mp = mat["mesh"]
        inputs["mesh"] = {"upload_id": mp["upload_id"], "file_name": mp["file_name"], "sha256": mp["sha256"]}
    import datetime as _dt

    created = _dt.datetime.now(_dt.timezone.utc).isoformat()
    doe = {"id": sid, "scenario": body.scenario, "title": title, "created_at": created, "cfg": _snapshot_cfg(ctx),
           "core": copy.deepcopy(ctx.config.core or {}), "mapping": (lib_cfg or {}).get("mapping"),
           "entries": [{"id": e["id"], "dir": entry_folder(ctx, e), "label": _entry_label(e), "case": e.get("case_id")}
                       for e in rows],
           "step": dict(step_p), "inch": body.inch}
    if mat["base"]:
        doe["base"] = dict(mat["base"])
    if mat["mesh"]:
        doe["mesh"] = dict(mat["mesh"])
    if props is not None:
        doe["props"] = props
        doe["mesh_size_mm"] = h
    params = {"bead_doe_id": sid, "kind": "PREP", "out_rel": f"{DOE_DIR}/{sid}", "doe": doe,
              "warnings": list(out["warnings"])}
    return _insert_study_job(ctx, principal, sid=sid, project_id=body.project_id, scenario=body.scenario, title=title,
                             entry_ids=[e["id"] for e in rows], base_db=mat["base_db"], inputs=inputs, params=params,
                             warns=out["warnings"])


# ---------------------------------------------------------------- 준비 결과: 변수 표·비드 PNG·평면도
def _require_prep(s: dict[str, Any], job: dict[str, Any] | None) -> None:
    """준비 요약(BD_PREP_REGISTER)이 있어야 변수 표·평면도·행렬을 낸다(아니면 409 PREP_NOT_READY)."""
    if s.get("prep") is None:
        raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다")


def _params_doc(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    p = _read_json(os.path.join(study_dir(ctx, s), "prep", "params.json"), _max_mb(c))
    if not isinstance(p, dict) or not isinstance(p.get("params"), list):
        raise conflict("PREP_NOT_READY", "준비 결과(prep/params.json)가 없습니다")
    return p


def _pair(v: Any, fallback: list[float]) -> list[float]:
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return [float(v[0]), float(v[1])]
    return list(fallback)


def params_out(ctx: AppContext, principal: Principal, sid: str) -> dict[str, Any]:
    c = cfg(ctx)
    s, job = _viewable(ctx, principal, sid)
    _require_prep(s, job)
    doc = _params_doc(ctx, s, c)
    beads = []
    for b in doc.get("beads") or []:
        if not isinstance(b, dict) or "id" not in b:
            continue
        nom = b.get("nominal") or {}
        beads.append({"id": str(b["id"]), "k": int(b.get("k") or 0), "shape": str(b.get("shape") or ""),
                      "sense": str(b.get("sense") or ""), "center_ab": _pair(b.get("center_ab"), [0.0, 0.0]),
                      "nominal": {"depth": nom.get("depth"), "width": nom.get("width"), "length": nom.get("length")},
                      "fixed_overlap": bool(b.get("fixed_overlap")), "png": b.get("png") if isinstance(b.get("png"), str)
                      else None})
    params = []
    for p in doc.get("params") or []:
        if not isinstance(p, dict) or p.get("type") not in ("D", "W", "U", "V"):
            continue
        nomv = float(p.get("nominal") or 0.0)
        fe = _pair(p.get("feasible"), _pair(p.get("default_range"), [nomv, nomv]))
        params.append({"name": str(p["name"]), "type": p["type"], "bead": str(p.get("bead") or ""), "nominal": nomv,
                       "feasible": fe, "feasible_source": p.get("feasible_source") if p.get("feasible_source") in
                       ("estimate", "sweep") else "estimate", "default_range": _pair(p.get("default_range"), fe),
                       "use_default": bool(p.get("use_default", True)),
                       "group_members": [str(x) for x in p.get("group_members") or [p["name"]]]})
    warns = [w for w in doc.get("warnings") or [] if isinstance(w, dict)]
    return _jsonable({"beads": beads, "params": params, "warnings": warns})


def bead_png(ctx: AppContext, principal: Principal, sid: str, bead: str) -> str:
    c = cfg(ctx)
    s, job = _viewable(ctx, principal, sid)
    _require_prep(s, job)
    if not BEAD_RE.match(bead or ""):
        raise not_found("FILE_NOT_FOUND", "비드 그림이 없습니다")
    doc = _params_doc(ctx, s, c)
    b = next((x for x in doc.get("beads") or [] if isinstance(x, dict) and str(x.get("id")) == bead), None)
    rel = b.get("png") if b else None
    if not isinstance(rel, str) or not rel:
        raise not_found("FILE_NOT_FOUND", "비드 그림이 없습니다")
    base = os.path.join(study_dir(ctx, s), "prep", "extract")
    try:
        p = safe_case_file(base, rel)
    except DomainError:
        raise not_found("FILE_NOT_FOUND", "비드 그림이 없습니다") from None
    return _png_or_404(p)


def _png_or_404(p: str) -> str:
    if not os.path.isfile(p) or os.path.islink(p):
        raise not_found("FILE_NOT_FOUND", "그림이 없습니다")
    with open(p, "rb") as fh:
        if fh.read(8) != PNG_MAGIC:
            raise not_found("FILE_NOT_FOUND", "PNG 그림이 아닙니다")
    return p


def _link_coords(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """links[] 에 선 긋기 좌표(B 평면 mm)·종류를 붙인다: from = A 체결점 label / '하중 <entry_id> <label>', to = B 후보 label."""
    a_by = {str(p.get("label")): [float(p["a"]), float(p["b"])] for p in plan.get("a_points") or []
            if isinstance(p, dict) and "a" in p and "b" in p}
    f_by = {str(p.get("label")): [float(p["a"]), float(p["b"])] for p in plan.get("fixed") or []
            if isinstance(p, dict) and "a" in p and "b" in p}
    l_by = {}
    for q in plan.get("load_points") or []:
        if isinstance(q, dict) and "a" in q and "b" in q:
            key = f"하중 {q.get('entry_id')} {q.get('label') or ''}".strip()
            l_by[key] = [float(q["a"]), float(q["b"])]
    out = []
    for ln in plan.get("links") or []:
        if not isinstance(ln, dict):
            continue
        d = dict(ln)
        frm, to = str(d.get("from")), str(d.get("to"))
        if frm in a_by:
            d.setdefault("kind", "fastener")
            d.setdefault("from_ab", a_by[frm])
        elif frm in l_by:
            d.setdefault("kind", "load")
            d.setdefault("from_ab", l_by[frm])
        if to in f_by:
            d.setdefault("to_ab", f_by[to])
        out.append(d)
    return out


def plan_view(ctx: AppContext, principal: Principal, sid: str) -> dict[str, Any]:
    c = cfg(ctx)
    s, job = _viewable(ctx, principal, sid)
    _require_prep(s, job)
    p = _read_json(os.path.join(study_dir(ctx, s), "prep", "plan.json"), _max_mb(c))
    if not isinstance(p, dict) or "frame" not in p:
        raise conflict("PREP_NOT_READY", "준비 결과(prep/plan.json)가 없습니다")
    limit = int(ctx.settings.view3d.max_nodes)
    n = ((p.get("elems") or {}).get("n_total"))
    if isinstance(n, int) and n > limit:
        raise DomainError("PLAN_VIEW_TOO_LARGE", f"요소 {n} > 상한 {limit}", status=413)
    p = dict(p)
    p["links"] = _link_coords(p)
    p["warnings"] = [str(w) for w in p.get("warnings") or []]
    return p


# ---------------------------------------------------------------- 행렬·미리보기·실행
def _generate(ctx: AppContext, s: dict[str, Any], spec: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from ...core.opt_core import EslError
    from ...core.opt_core import doe_matrix

    tab = _params_doc(ctx, s, c)["params"]
    try:
        return doe_matrix.generate(spec, tab, c)
    except EslError as exc:
        code = exc.code if exc.code in ERROR_CODES_422 else "DOE_RANGE_INVALID"
        raise unprocessable(code, exc.message) from None


def _spec_dict(body) -> dict[str, Any]:
    sp = body.spec.model_dump()
    out = {"method": sp["method"], "params": [{"name": p["name"], "lo": p["lo"], "hi": p["hi"]} for p in sp["params"]]}
    for k in ("n", "levels", "seed"):
        if sp.get(k) is not None:
            out[k] = sp[k]
    return out


def _study_cfg(conn, s: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """행렬 생성 설정 = 연구 준비(DOE_PREP) 시점 스냅샷 bead_doe(워커 BD_MATRIX 와 같은 값 — 준비 뒤 서버 설정이 바뀌어도
    MATRIX_MISMATCH 가 나지 않게, 검증 지적). 스냅샷이 없으면 지금 설정."""
    j = doe_repo.latest_job(conn, s["id"], job_type="DOE_PREP", state="SUCCEEDED")
    snap = (((j or {}).get("params") or {}).get("doe") or {}).get("cfg") or {}
    bd = snap.get("bead_doe") if isinstance(snap, dict) else None
    return bd if isinstance(bd, dict) and bd.get("doe") else current


def matrix(ctx: AppContext, principal: Principal, sid: str, body) -> dict[str, Any]:
    """행렬 생성만(저장 안 함) — 화면 안 수·경고 즉시 표시. 같은 함수를 미리보기·워커 BD_MATRIX 가 쓴다(같은 sha)."""
    c = cfg(ctx)
    s, job = _viewable(ctx, principal, sid)
    _require_prep(s, job)
    with ctx.engine.connect() as conn:
        mc = _study_cfg(conn, s, c)
    return _jsonable(_generate(ctx, s, _spec_dict(body), mc))


def _prep_params(conn, s: dict[str, Any]) -> dict[str, Any]:
    """연구 스냅샷 = 최근 성공한 DOE_PREP 작업 params(경로·설정). 없으면 409 PREP_NOT_READY."""
    j = doe_repo.latest_job(conn, s["id"], job_type="DOE_PREP", state="SUCCEEDED")
    if j is None or not isinstance((j.get("params") or {}).get("doe"), dict):
        raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다")
    return j["params"]


def _lock(conn, sid: str, version: int) -> tuple[dict[str, Any], dict[str, Any] | None]:
    s = load_study(conn, sid, for_update=True)
    if int(version) != int(s["version"]):
        raise conflict("VERSION_CONFLICT", "다른 곳에서 연구가 바뀌었습니다 — 새로 고친 뒤 다시 하세요",
                       version=int(s["version"]))
    return s, doe_repo.latest_job(conn, sid)


def preview(ctx: AppContext, principal: Principal, sid: str, body) -> dict[str, Any]:
    c = cfg(ctx)
    with ctx.engine.connect() as conn:
        s0 = load_study(conn, sid)
    require_execute(principal, s0["project_id"])
    require_config_ok(ctx)
    require_enabled(ctx, s0["scenario"])
    spec = _spec_dict(body)
    with ctx.engine.begin() as conn:
        s, job = _lock(conn, sid, body.version)
        if job is not None and job["state"] not in TERMINAL:
            raise conflict("JOB_ACTIVE", "이 강성 평가 스터디의 작업이 대기 중이거나 실행 중입니다")
        if s.get("run") is not None or s["phase"] in ("RUN", "DONE"):
            raise conflict("ALREADY_RUN", "이미 실행한 연구입니다 — 다시 하려면 복제하세요")
        if s.get("prep") is None:
            raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다")
        m = _generate(ctx, s, spec, _study_cfg(conn, s, c))
        base = _prep_params(conn, s)
        rev = int(((s.get("doe") or {}).get("rev")) or 0) + 1
        doe = copy.deepcopy(base["doe"])
        doe.update(rev=rev, spec=m["spec"], matrix_sha256=m["matrix_sha256"], paicad_version=s.get("paicad_version"))
        params = {"bead_doe_id": sid, "kind": "PREVIEW", "out_rel": s["dir_rel"], "doe": doe,
                  "warnings": [w for w in m["warnings"]]}
        s = doe_repo.update_study(conn, sid, phase="PREVIEW",
                                  doe=_jsonable({"rev": rev, "spec": m["spec"], "matrix_sha256": m["matrix_sha256"],
                                                 "n_designs": m["n_designs"], "preview": None}))
        job = _insert_job(conn, principal, s, "DOE_PREVIEW", params, warns=m["warnings"])
        return study_out(ctx, conn, s, job, c=c)


def run(ctx: AppContext, principal: Principal, sid: str, body) -> dict[str, Any]:
    c = cfg(ctx)
    with ctx.engine.connect() as conn:
        s0 = load_study(conn, sid)
    require_execute(principal, s0["project_id"])
    require_config_ok(ctx)
    if body.solver != "linear":
        raise unprocessable("SOLVER_UNSUPPORTED", f"solver 는 linear 만 지원합니다(값 {body.solver!r}) — 탄소성은 후속")
    require_enabled(ctx, s0["scenario"])
    with ctx.engine.begin() as conn:
        s, job = _lock(conn, sid, body.version)
        if job is not None and job["state"] not in TERMINAL:
            raise conflict("JOB_ACTIVE", "이 강성 평가 스터디의 작업이 대기 중이거나 실행 중입니다")
        if s.get("run") is not None or s["phase"] in ("RUN", "DONE"):
            raise conflict("ALREADY_RUN", "이미 실행한 연구입니다 — 다시 하려면 복제하세요")
        doe = s.get("doe") or {}
        pv = doe.get("preview") or {}
        if (_derived_phase(s, job) != "PREVIEW_READY" or not pv or pv.get("matrix_sha256") != doe.get("matrix_sha256")
                or body.matrix_sha256 != doe.get("matrix_sha256")):
            raise conflict("PREVIEW_STALE", "이 DOE 행렬의 미리보기가 끝나지 않았거나 행렬이 바뀌었습니다 — 미리보기를 다시 하세요",
                           matrix_sha256=doe.get("matrix_sha256"))
        base = _prep_params(conn, s)
        run_opts = {"solver": "linear", "parallel": int(c["run"]["parallel"])}
        d = copy.deepcopy(base["doe"])
        d.update(rev=int(doe["rev"]), spec=doe["spec"], matrix_sha256=doe["matrix_sha256"],
                 paicad_version=s.get("paicad_version"), run=run_opts)
        params = {"bead_doe_id": sid, "kind": "RUN", "out_rel": s["dir_rel"], "doe": d,
                  "preview": {"rev": pv.get("rev"), "ok": pv.get("ok")}, "warnings": []}
        s = doe_repo.update_study(conn, sid, phase="RUN", run=run_opts)
        job = _insert_job(conn, principal, s, "DOE_RUN", params)
        return study_out(ctx, conn, s, job, c=c)


def clone(ctx: AppContext, principal: Principal, sid: str, body: dict[str, Any] | None) -> dict[str, Any]:
    """같은 입력(연구 스냅샷 경로·설정은 지금 설정)으로 새 연구 + DOE_PREP. 준비 산출물은 재사용하지 않는다."""
    body = body or {}
    if set(body) - {"title"}:
        raise unprocessable("INVALID_PARAMS", f"알 수 없는 키: {sorted(set(body) - {'title'})}")
    title = body.get("title")
    if title is not None and (not isinstance(title, str) or len(title) > 200):
        raise unprocessable("INVALID_PARAMS", "title 은 200자 이하 문자열입니다")
    with ctx.engine.connect() as conn:
        s = load_study(conn, sid)
        require_execute(principal, s["project_id"])
        require_eligible_ids(conn, s["entry_ids"])          # MR-D-10: 복제도 적격 항목만(422 ENTRY_NOT_ELIGIBLE)
        prep_job = doe_repo.latest_job(conn, sid, job_type="DOE_PREP")
        # §15 업로드는 본인 것만: 복제는 원 연구의 STEP·B 메시 업로드(서버 경로)를 그대로 다시 쓰므로 업로드 소유자만(검증 지적)
        from ...core.db.tables import uploads as uploads_t

        snap = ((prep_job or {}).get("params") or {}).get("doe") or {}
        for k in ("step", "mesh"):
            uid = (snap.get(k) or {}).get("upload_id")
            if not uid:
                continue
            owner = conn.execute(uploads_t.select().with_only_columns(uploads_t.c.user_id)
                                 .where(uploads_t.c.id == uid)).scalar()
            if owner != principal.user_id:
                raise DomainError("UPLOAD_NOT_OWNED", "원 연구의 입력 파일은 올린 사람만 다시 쓸 수 있습니다 — "
                                  "같은 ESL 을 골라 STEP 을 새로 올려 새 강성 평가 스터디를 만드세요", status=403, input=k)
    require_config_ok(ctx)
    require_enabled(ctx, s["scenario"])
    if prep_job is None or not isinstance((prep_job.get("params") or {}).get("doe"), dict):
        raise conflict("PREREQUISITE_MISSING", "원 연구의 입력 스냅샷이 없습니다", missing=["prep_job"])
    old = prep_job["params"]["doe"]
    st = old.get("step") or {}
    if not st.get("path") or not os.path.isfile(st["path"]) or os.path.islink(st["path"]):
        raise conflict("PREREQUISITE_MISSING", "원 연구의 STEP 업로드가 더 이상 없습니다 — 새로 올려 주세요", missing=["step"])
    nid = str(uuid.uuid4())
    doe_dir(ctx.settings, nid)
    import datetime as _dt

    d = {k: copy.deepcopy(v) for k, v in old.items() if k not in ("rev", "spec", "matrix_sha256", "run",
                                                                   "paicad_version", "design", "paicad")}
    new_title = (title or "").strip() or f"{s['title']} (복제)"[:200]
    d.update(id=nid, title=new_title, created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
             cfg=_snapshot_cfg(ctx), core=copy.deepcopy(ctx.config.core or {}))
    params = {"bead_doe_id": nid, "kind": "PREP", "out_rel": f"{DOE_DIR}/{nid}", "doe": d,
              "warnings": list(prep_job["params"].get("warnings") or [])}
    return _insert_study_job(ctx, principal, sid=nid, project_id=s["project_id"], scenario=s["scenario"],
                             title=new_title, entry_ids=list(s["entry_ids"]), base_db=s.get("base"),
                             inputs=dict(s.get("inputs") or {}), params=params, warns=[])


# 연구 진행 순서(phase) — 오래된 작업 재시도·등록이 연구를 되돌리지 않게(검증 지적)
PHASE_ORDER = {"PREP": 0, "READY": 1, "PREVIEW": 2, "PREVIEW_READY": 3, "RUN": 4, "DONE": 5}
JOB_PHASE = {"DOE_PREP": "PREP", "DOE_PREVIEW": "PREVIEW", "DOE_RUN": "RUN"}


def _require_retry_current(conn, s: dict[str, Any], job: dict[str, Any]) -> None:
    """재시도 허용 = 그 연구의 **가장 최근 작업**이고(이미 재시도했거나 뒤에 다른 작업이 있으면 거부), 연구가 끝나지 않았고(DONE),
    연구 단계가 그 작업 단계를 지나지 않았을 때만. 아니면 409 DOE_RETRY_STALE."""
    latest = doe_repo.latest_job(conn, s["id"])
    why = None
    if s["phase"] == "DONE":
        why = "연구가 이미 끝났습니다"
    elif latest is None or latest["id"] != job["id"]:
        why = "이 작업 뒤에 다른 작업(재시도·다음 단계)이 있습니다"
    elif PHASE_ORDER.get(s["phase"], -1) > PHASE_ORDER[JOB_PHASE[job["job_type"]]]:
        why = "연구가 이 작업 단계를 이미 지났습니다"
    if why:
        raise conflict("DOE_RETRY_STALE", f"오래된 강성 평가 작업은 재시도할 수 없습니다 — {why}. 연구 화면에서 현재 단계를 진행하세요",
                       phase=s["phase"], latest_job_id=(latest or {}).get("id"))


def retry_job(conn, principal: Principal, job: dict[str, Any]) -> dict[str, Any]:
    """DOE_* 재시도(§9.3): 같은 params(연구 스냅샷)로 실패 step 부터(BD-D-16 이어하기 — 안 done.json 재사용은 워커).
    phase 를 그 작업의 진행 상태로 되돌린다."""
    s = load_study(conn, job["bead_doe_id"], for_update=True)
    _require_retry_current(conn, s, job)
    start = jobs_repo.first_failed_step(conn, job["id"])
    new = _insert_job(conn, principal, s, job["job_type"], dict(job["params"]), retry_of=job["id"],
                      resume=start if start > 1 else None)
    phase = {"DOE_PREP": "PREP", "DOE_PREVIEW": "PREVIEW", "DOE_RUN": "RUN"}[job["job_type"]]
    try:
        doe_repo.update_study(conn, s["id"], phase=phase)
    except VersionConflict:  # pragma: no cover - 행 잠금 중
        pass
    return job_out(conn, new, with_steps=True)


# ---------------------------------------------------------------- 결과
def _result_doc(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> dict[str, Any] | None:
    r = _read_json(os.path.join(study_dir(ctx, s), "post", "result.json"), _max_mb(c))
    if isinstance(r, dict):
        return r
    return s.get("result") if isinstance(s.get("result"), dict) else None


def _file_entry(base: str, rel: str, lim: int) -> dict[str, Any] | None:
    try:
        p = safe_case_file(base, rel)
    except DomainError:
        return None
    if not os.path.isfile(p) or os.path.islink(p):
        return None
    size = os.path.getsize(p)
    return {"rel": rel, "size": size, "downloadable": size <= lim}


def results(ctx: AppContext, principal: Principal, sid: str) -> dict[str, Any]:
    c = cfg(ctx)
    s, job = _viewable(ctx, principal, sid)
    if _derived_phase(s, job) != "DONE":
        raise conflict("RESULT_NOT_READY", "DOE 실행 결과가 아직 없습니다")
    r = _result_doc(ctx, s, c)
    if r is None:
        raise conflict("RESULT_NOT_READY", "DOE 실행 결과(post/result.json)가 없습니다")
    base = study_dir(ctx, s)
    lim = ctx.settings.ui.max_artifact_bytes
    designs = _read_json(os.path.join(base, "post", "designs.json"), _max_mb(c)) or {}
    rev = int(((s.get("doe") or {}).get("rev")) or 0)
    m = _matrix_doc(ctx, s, rev, c) if rev else None
    vals = {d["id"]: d.get("values") or {} for d in (m or {}).get("designs") or [] if isinstance(d, dict)}
    excluded = [{"id": d["id"], "status": d.get("status"), "code": d.get("code"), "values": vals.get(d["id"], {})}
                for d in designs.get("designs") or []
                if isinstance(d, dict) and d.get("id") != "d000" and d.get("status") not in ("OK", None)]
    ranking = []
    for x in r.get("ranking") or []:
        row = {k: v for k, v in x.items() if k != "C"}
        if row.get("noise") is None:
            row.pop("noise", None)
        ranking.append(row)
    best = r.get("best")
    if isinstance(best, dict) and best.get("id"):
        files = []
        for f in best.get("files") or []:
            rel = f if isinstance(f, str) else (f.get("rel") if isinstance(f, dict) else None)
            if not isinstance(rel, str):
                continue
            full = rel if rel.startswith("best/") else f"best/{best['id']}/{rel}"
            e = _file_entry(base, full, lim)
            if e is not None:
                files.append(e)
        best = {"id": best["id"], "files": files}
    else:
        best = None
    b = dict(r.get("baseline") or {})
    warns = [w if isinstance(w, dict) else {"code": str(w).split(":", 1)[0], "message": str(w)}
             for w in r.get("warnings") or []]
    if r.get("sensitivity") is None and r.get("sensitivity_reason"):
        warns.append({"code": "SENSITIVITY_TOO_FEW", "message": str(r.get("sensitivity_reason"))})
    out = {"C_ref": r.get("C_ref"), "baseline": {k: b.get(k) for k in ("id", "score", "umax", "epsmax")} | {"id": "d000"},
           "n_ok": int(r.get("n_ok") or 0), "n_skipped": {k: int(v) for k, v in (r.get("n_skipped") or {}).items()},
           "n_failed": {k: int(v) for k, v in (r.get("n_failed") or {}).items()}, "ranking": ranking,
           "excluded": excluded, "sensitivity": r.get("sensitivity"),
           "boundary_warnings_n": int(r.get("boundary_warnings_n") or 0),
           "view3d": [str(v) for v in r.get("view3d") or [] if v], "best": best, "noise_floor": r.get("noise_floor"),
           "warnings": warns}
    return _jsonable(out)


# ---------------------------------------------------------------- 파일·보고서·받기
def _kind(rel: str) -> str:
    top = rel.split("/", 1)[0]
    if rel == "report.html":
        return "report"
    if rel == "post/ranking.csv":
        return "ranking"
    return {"post": "result", "best": "best", "doe": "preview", "prep": "prep", "input": "input",
            "run": "run"}.get(top, "other")


_ORDER = {"report": 0, "ranking": 1, "result": 2, "best": 3, "preview": 4, "prep": 5, "input": 6, "run": 7, "other": 8}
_ADMIN_ONLY = re.compile(r"(^|/)(paicad\.log|argv[^/]*)$")


def _walk(base: str, principal: Principal) -> list[tuple[str, str]]:
    out = []
    for p, rel in bundle_svc._walk(base):
        if _ADMIN_ONLY.search(rel) and not principal.is_global_admin:
            continue                                   # argv·paicad.log 는 전역 관리자만(§15)
        out.append((p, rel))
    return out


def list_files(ctx: AppContext, principal: Principal, sid: str) -> list[dict[str, Any]]:
    s, _job = _viewable(ctx, principal, sid)
    base = study_dir(ctx, s)
    lim = ctx.settings.ui.max_artifact_bytes
    out = []
    for p, rel in _walk(base, principal) if os.path.isdir(base) else []:
        size = os.path.getsize(p)
        out.append({"rel": rel, "size": size, "downloadable": size <= lim, "_k": _kind(rel)})
    out.sort(key=lambda x: (_ORDER[x["_k"]], x["rel"]))
    for x in out:
        x.pop("_k")
    return out


def study_file(ctx: AppContext, principal: Principal, sid: str, rel: str) -> str:
    files = {f["rel"] for f in list_files(ctx, principal, sid)}
    with ctx.engine.connect() as conn:
        s = load_study(conn, sid)
    base = study_dir(ctx, s)
    path = safe_case_file(base, rel)
    if rel not in files or not os.path.isfile(path) or os.path.islink(path):
        raise not_found("FILE_NOT_FOUND", "파일이 없습니다")
    size = os.path.getsize(path)
    if size > ctx.settings.ui.max_artifact_bytes:
        raise DomainError("ARTIFACT_TOO_LARGE", "파일이 커서 다운로드할 수 없습니다(관리자에게 폴더를 요청하세요)",
                          status=413, rel=rel, size=size, limit=ctx.settings.ui.max_artifact_bytes)
    return path


def report(ctx: AppContext, principal: Principal, sid: str) -> str:
    s, _job = _viewable(ctx, principal, sid)
    path = safe_case_file(study_dir(ctx, s), s.get("report_rel") or "report.html")
    if not os.path.isfile(path) or os.path.islink(path):
        raise not_found("REPORT_NOT_FOUND", "보고서가 아직 없습니다(DOE 실행 완료 후 생성)")
    return path


DOE_PARTS = ("best", "report", "ranking", "result", "prep", "raw")
DOE_DEFAULT = ("best", "report", "ranking")


def bundle(ctx: AppContext, principal: Principal, sid: str, parts_raw: str | None) -> dict[str, Any]:
    parts = bundle_svc.parse_parts(parts_raw, DOE_PARTS, DOE_DEFAULT)
    s, _job = _viewable(ctx, principal, sid)
    base = study_dir(ctx, s)
    raw = "raw" in parts
    files = []
    for p, rel in _walk(base, principal) if os.path.isdir(base) else []:
        k = _kind(rel)
        take = ((k in parts and k in ("best", "report", "ranking", "result", "prep"))
                or (raw and k in ("run", "input")))
        if take and rel.lower().endswith(".npz") and not raw:
            take = False
        if take and k == "prep" and not raw and not rel.lower().endswith((".json", ".png")):
            take = False                               # 준비 자료는 JSON·비드 그림만(대형 메시 사본은 raw)
        if take:
            files.append((p, rel))
    if not files:
        raise not_found("BUNDLE_EMPTY", "받을 강성 평가 스터디 파일이 아직 없습니다")
    size = bundle_svc._check_size(ctx, files, base)
    return {"files": files, "prefix": f"doe_{sid}", "filename": f"doe_{sid}.zip", "size": size}


# ---------------------------------------------------------------- 썸네일·3D 비교
def thumb(ctx: AppContext, principal: Principal, sid: str, did: str) -> str:
    s, _job = _viewable(ctx, principal, sid)
    pv = (s.get("doe") or {}).get("preview")
    if not DID_RE.match(did or "") or not isinstance(pv, dict) or pv.get("rev") is None:
        raise not_found("FILE_NOT_FOUND", "썸네일이 없습니다")
    gdir = _grid_dir(ctx, s, int(pv["rev"]))
    c = cfg(ctx)
    manifest = _read_json(os.path.join(gdir, "grid_manifest.json"), _max_mb(c)) or {}
    p = _cell_thumb(gdir, manifest, did)
    if p is None:
        raise not_found("FILE_NOT_FOUND", "썸네일이 없습니다")
    return _png_or_404(p)


def _view3d_dir(ctx: AppContext, principal: Principal, sid: str, did: str) -> str:
    s, job = _viewable(ctx, principal, sid)
    if not DID_RE.match(did or ""):
        raise not_found("VIEW3D_NOT_FOUND", "3D 비교 자료가 없습니다")
    d = safe_case_file(study_dir(ctx, s), f"post/view3d/{did}")
    if not os.path.isdir(d) or os.path.islink(d):
        raise not_found("VIEW3D_NOT_FOUND", "3D 비교 자료가 없습니다(순위 상위·베이스라인만)")
    return d


def view3d_manifest(ctx: AppContext, principal: Principal, sid: str, did: str) -> dict[str, Any]:
    d = _view3d_dir(ctx, principal, sid, did)
    m = _read_json(os.path.join(d, "manifest.json"), 64)
    if not isinstance(m, dict) or not isinstance(m.get("geometry"), dict) or not isinstance(m.get("values"), dict):
        raise not_found("VIEW3D_NOT_FOUND", "3D 비교 자료(manifest.json)가 없습니다")
    names = [m["geometry"].get("name"), m["values"].get("name")] + ([m["lod"].get("name")] if m.get("lod") else [])
    if not all(isinstance(n, str) and n in VIEW3D_FILES and os.path.isfile(os.path.join(d, n)) for n in names):
        raise not_found("VIEW3D_NOT_FOUND", "3D 비교 파일이 없습니다")
    base = f"/doe/studies/{sid}/view3d/{did}"
    out = dict(m)
    out["geometry_url"] = f"{base}/{m['geometry']['name']}"
    out["lod_url"] = f"{base}/{m['lod']['name']}" if m.get("lod") else None
    out["values_url"] = f"{base}/{m['values']['name']}"
    return out


def view3d_file(ctx: AppContext, principal: Principal, sid: str, did: str, name: str) -> tuple[str, str]:
    if name not in VIEW3D_FILES:
        raise not_found("NOT_FOUND", "찾을 수 없습니다")
    d = _view3d_dir(ctx, principal, sid, did)
    p = os.path.join(d, name)
    if not os.path.isfile(p) or os.path.islink(p):
        raise not_found("VIEW3D_NOT_FOUND", "3D 비교 파일이 없습니다")
    return p, VIEW3D_FILES[name]


__all__ = ["settings_out", "check_inputs", "create_study", "list_studies", "get_study", "params_out", "plan_view",
           "matrix", "preview", "run", "clone", "results", "list_files", "study_file", "report", "bundle", "thumb",
           "view3d_manifest", "view3d_file", "bead_png", "retry_job", "status", "reset_status_cache"]
