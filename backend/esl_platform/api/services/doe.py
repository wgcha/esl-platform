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

from .pathmask import masks_paths
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
def _select():
    """v0.15.0 select 서비스(doe_select — 순환 import 를 피해 지연)."""
    from . import doe_select

    return doe_select


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


def compare_reason(c: dict[str, Any], gmsh_ready: bool) -> str | None:
    """④ 비활성 사유(SC-D-3): DOE_DISABLED·COMPARE_DISABLED·GMSH_UNAVAILABLE — paicad 사유는 보지 않는다.
    v0.16.0 C2-D-16: 활성 = enabled ∧ compare.enabled ∧ (gmsh.ready ∨ mesh_input.enabled) — gmsh 가 없어도 메시 입력만으로 쓸
    수 있다(STEP 형상은 check-inputs 에서 503 GMSH_UNAVAILABLE)."""
    if not c.get("enabled"):
        return "DOE_DISABLED"
    cc = c.get("compare") or {}
    if not cc.get("enabled", True):
        return "COMPARE_DISABLED"
    if not gmsh_ready and not (cc.get("mesh_input") or {}).get("enabled", False):
        return "GMSH_UNAVAILABLE"
    return None


def remesh_available(ctx: AppContext, c: dict[str, Any]) -> bool:
    """C2-D-16·R-C2-1: 삼각형 재메시 가능 = bead_doe.enabled ∧ compare.remesh.enabled ∧ 워커 점검 기록 gmsh.ready ∧
    gmsh.remesh(워커가 ``gmsh.model.mesh.importStl`` 존재를 확인해 기록 — 기록이 없으면 불가로 본다)."""
    rm = (c.get("compare") or {}).get("remesh") or {}
    if not c.get("enabled") or not rm.get("enabled", False):
        return False
    gm = (_worker_record(ctx, c) or {}).get("gmsh") or {}
    return bool(gm.get("ready") and gm.get("remesh"))


def select_reason(c: dict[str, Any]) -> str | None:
    """select 비활성 사유(BS-D-2): DOE_DISABLED·SELECT_DISABLED — paicad·gmsh 는 보지 않는다."""
    if not c.get("enabled"):
        return "DOE_DISABLED"
    if not (c.get("select") or {}).get("enabled", True):
        return "SELECT_DISABLED"
    return None


def status(ctx: AppContext) -> dict[str, Any]:
    """{enabled, reason, paicad{ready, version, pinned, warning}, gmsh{ready, version}, scenarios{same, mesh, step, compare,
    select}, compare_reason, select_reason}. enabled·reason 은 paicad 기준(①②③), ④ compare 는 bead_doe.enabled ∧
    compare.enabled ∧ gmsh(SC-D-3), select 는 bead_doe.enabled ∧ select.enabled(BS-D-2, paicad 무관)."""
    c = cfg(ctx)
    ok, reason = paicad_exe_status(ctx.settings)
    rec = _worker_record(ctx, c) if c.get("enabled") else None      # gmsh 점검은 paicad 와 무관하게 읽는다(④)
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
    cr = compare_reason(c, gmsh["ready"])
    sr = select_reason(c)
    return {"enabled": enabled, "reason": reason, "paicad": paicad, "gmsh": gmsh,
            "scenarios": {"same": enabled, "mesh": enabled, "step": enabled and gmsh["ready"], "compare": cr is None,
                          "select": sr is None,
                          # v0.16.2(esl_bead_auto.md §3.2): 자동 탐지 = select 가능 ∧ paicad 준비됨, ② B 메시 기준 select =
                          # select 가능(수동은 paicad 불필요 — 자동 탐지는 select_auto 도 봐야 함)
                          "select_auto": sr is None and paicad["ready"], "select_mesh": sr is None},
            "compare_reason": cr, "select_reason": sr}


COMPARE_DISABLED_MSG = {
    "DOE_DISABLED": "강성 평가 스터디가 꺼져 있습니다(설정 bead_doe.enabled — 관리자 문의)",
    "COMPARE_DISABLED": "형상 직접 비교가 꺼져 있습니다(설정 bead_doe.compare.enabled — 관리자 문의)",
    "GMSH_UNAVAILABLE": "메시 생성기(gmsh)가 없어 '형상 직접 비교'를 쓸 수 없습니다(관리자 문의)",
}


SELECT_DISABLED_MSG = {
    "DOE_DISABLED": "강성 평가 스터디가 꺼져 있습니다(설정 bead_doe.enabled — 관리자 문의)",
    "SELECT_DISABLED": "비드 직접 선택이 꺼져 있습니다(설정 bead_doe.select.enabled — 관리자 문의)",
}


def require_enabled(ctx: AppContext, scenario: str | None = None) -> dict[str, Any]:
    st = status(ctx)
    if scenario == "select":                        # BS-D-2: paicad 없음·버전 낮음·gmsh 없음은 select 를 막지 않는다
        if st["select_reason"]:
            raise DomainError(st["select_reason"], SELECT_DISABLED_MSG[st["select_reason"]], status=503)
        return st
    if scenario == "compare":                       # SC-D-3: paicad 없음·버전 낮음은 ④ 를 막지 않는다
        if st["compare_reason"]:
            raise DomainError(st["compare_reason"], COMPARE_DISABLED_MSG[st["compare_reason"]], status=503)
        return st
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
def _compare_settings(ctx: AppContext, c: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
    """④ 블록(SC-D-3 + v0.16.0 §6): mesh_mode(설정 기본), remesh_available, mesh_input{enabled, formats, max_mb},
    step_ready(= gmsh.ready — STEP 형상 사용 가능)."""
    cc = c["compare"]
    mi = cc["mesh_input"]
    df = cc["defeature"]
    return {"enabled": st["scenarios"]["compare"], "reason": st["compare_reason"],
            "max_shapes": int(cc["max_shapes"]), "total_max_mb": float(cc["total_max_mb"]),
            "mesh_size_mm": float(cc["mesh"]["size_mm"]), "mesh_mode": str(cc["mesh"]["mode"]),
            "remesh_available": remesh_available(ctx, c),
            "mesh_input": {"enabled": bool(mi["enabled"]), "formats": list(mi["formats"]), "max_mb": float(mi["max_mb"])},
            "step_ready": bool(st["gmsh"]["ready"]),
            # v0.16.1(esl_select_relax.md §4.4): 사다리(defeature 포함)·작은 형상 억제 기준(화면 툴팁)
            "mesh": {"ladder": list(cc["mesh"]["ladder"])},
            "defeature": {"hole_max_d_mm": float(df["hole_max_d_mm"]), "min_bead_height_mm": float(df["min_bead_height_mm"]),
                          "fillet_max_r_mm": float(df["fillet_max_r_mm"]), "kinds": list(df["kinds"])}}


def settings_out(ctx: AppContext, principal: Principal | None = None) -> dict[str, Any]:
    c = cfg(ctx)
    st = status(ctx)
    d = c["doe"]
    sc = c["select"]
    return {**st, "max_entries": int(c["max_entries"]), "max_designs": int(c["max_designs"]),
            "doe": {"methods": ["lhs", "halton", "fullfact"], "default_method": d["default_method"],
                    "default_n": int(d["default_n"]), "seed": int(d["seed"]), "levels_default": int(d["levels_default"]),
                    "levels_max": int(d["levels_max"]), "default_types": list(d["default_types"])},
            "mesh": {"size_auto": True, "size_min_mm": float(c["mesh"]["size_min_mm"]),
                     "size_max_mm": float(c["mesh"]["size_max_mm"])},
            "boundary": {k: float(c["boundary"][k]) for k in ("fastener_warn_mm", "load_warn_mm", "load_share_min")},
            "step_max_mb": float(c["step_max_mb"]), "part_title": c["part_title"],
            "method_sources": method_sources(principal),
            "compare": _compare_settings(ctx, c, st),
            "select": {"enabled": st["scenarios"]["select"], "reason": st["select_reason"],
                       "feature_angle_deg": float(sc["feature_angle_deg"]), "max_beads": int(sc["max_beads"]),
                       "max_tiers": int(sc["max_tiers"]),
                       "blend": {"min_mm": float(sc["blend"]["min_mm"]), "max_mm": float(sc["blend"]["max_mm"])},
                       # v0.16.1(esl_select_relax.md §4.4): 고정 침범·품질 FAIL 정책, 체결 구멍 둘레 고정 기본값(툴팁)
                       "fixed_policy": str(sc["fixed_policy"]), "quality_fail_policy": str(sc["quality"]["fail_policy"]),
                       "hold": {"ring_mm": float(sc["hold"]["ring_mm"]), "blend_mm": float(sc["hold"]["blend_mm"])},
                       # 섬 판정 거울 키(SR-D-26 — 브라우저 enclosedIslands 가 같은 값으로)
                       "island": {"max_mm": float(sc["island"]["max_mm"]),
                                  "ring_frac": float(sc["island"].get("ring_frac", 0.9))},
                       # v0.16.2 AD-D-7 구멍 건너 잇기 상한(브라우저 거울)
                       "hole": {"bridge_max_mm": float((sc.get("hole") or {}).get("bridge_max_mm", 20.0))}}}


# ---------------------------------------------------------------- POST /doe/check-inputs
def select_kind(body) -> tuple[str, str]:
    """v0.16.2 select (bead_source, select_base) — 생략 = ("manual", "case")(esl_bead_auto.md §3.3)."""
    return (getattr(body, "bead_source", None) or "manual"), (getattr(body, "select_base", None) or "case")


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


@masks_paths
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
    if body.scenario == "compare":
        r = _compare_check(ctx, principal, body, c)
        return r if _internal else r["out"]
    if body.shapes is not None:
        raise unprocessable("INVALID_PARAMS", "shapes 는 '형상 직접 비교'에서만 지정합니다")
    if body.mesh_mode is not None or body.mesh_refine is not None:
        raise unprocessable("INVALID_PARAMS", up_svc.doe_text("MESH_MODE_COMPARE_ONLY"))
    src, sbase = select_kind(body)
    is_sel = body.scenario == "select"
    if is_sel:
        # v0.16.2(esl_bead_auto.md §3.3·AD-D-1·13·14): 자동 탐지 = paicad extract·tag 입력 STEP 필수, 수동 = STEP 금지.
        # case = 같은 모델 Case 메시(B 메시·파트 금지), mesh = ② B 메시(.rad/.inc) 필수
        if src == "auto" and not body.step_upload_id:
            raise unprocessable("INVALID_PARAMS", "'자동 탐지'에는 step_upload_id(STEP — paicad 비드 탐지 입력)가 필요합니다")
        if src == "manual" and body.step_upload_id:
            raise unprocessable("INVALID_PARAMS", "step_upload_id 는 '비드 직접 선택 — 수동'에서 쓰지 않습니다(자동 탐지만)")
        if sbase == "case" and (body.mesh_upload_id or body.part_title):
            raise unprocessable("INVALID_PARAMS", "mesh_upload_id·part_title 은 '비드 직접 선택'(같은 모델)에서 쓰지 않습니다"
                                "(기준 = 같은 모델 Case 메시 — 다른 모델은 select_base mesh)")
        if sbase == "mesh" and not body.mesh_upload_id:
            raise unprocessable("INVALID_PARAMS", "'비드 직접 선택 — 다른 모델(B 메시)'에는 mesh_upload_id 가 필요합니다")
    elif body.bead_source is not None or body.select_base is not None:
        raise unprocessable("INVALID_PARAMS", "bead_source·select_base 는 '비드 직접 선택'에서만 지정합니다")
    elif not body.step_upload_id:
        raise unprocessable("INVALID_PARAMS", "step_upload_id 가 필요합니다")
    if body.scenario not in ("mesh", "select") and (body.mesh_upload_id or body.part_title):
        raise unprocessable("INVALID_PARAMS", "mesh_upload_id·part_title 은 '다른 모델(메시 있음)'에서만 지정합니다")
    mesh_base = body.scenario == "mesh" or (is_sel and sbase == "mesh")
    with ctx.engine.connect() as conn:
        rows = entries_in_order(conn, body.project_id, list(body.entry_ids))
    rows = backfill_opt_meta(ctx, rows)
    step_out, step_p = _step_input(ctx, principal, body, c) if (not is_sel or src == "auto") else (None, None)
    out: dict[str, Any] = {"ok": True, "step": step_out, "base": None, "mesh": None, "entries": [], "size": None,
                           "props_default": None, "mesh_size_default_mm": None, "warnings": []}
    mat: dict[str, Any] = {"rows": rows, "step": step_p, "base": None, "base_db": None, "mesh": None,
                           "props_default": None, "mesh_size_default_mm": None, "bead_source": src if is_sel else None,
                           "select_base": sbase if is_sel else None}
    if body.scenario == "same" or (is_sel and not mesh_base):     # select(case) = ① 같은 모델 기준(BS-D-1)
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
        if mesh_base:           # ② · select(mesh) — ② 입력·검사 그대로(AD-D-14: 같은 모델 검사 없음, 크기 규칙 B = 템플릿)
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


# ---------------------------------------------------------------- ④ 형상 직접 비교 입력(esl_step_compare.md §3)
def _shape_name(raw: str, index: int) -> str:
    import unicodedata

    name = (raw or "").strip()
    if not 1 <= len(name) <= 64 or any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Zl", "Zp") for ch in name):
        raise unprocessable("SHAPE_NAME_INVALID", f"형상 {index + 1}: 이름은 1~64자, 제어 문자 없이 입력하세요", index=index)
    return name


PARTS_OUT_MAX = 50          # check-inputs 메시 형상 parts[] 상한(계약 §3 — 화면 datalist)


def _pick_mesh_part(info: dict[str, Any], part_id: int | None, index: int) -> tuple[int, list[dict[str, Any]]]:
    """v0.16.0 C2-D-4 파트 선택(deck.scan 결과만): 쉘 파트 하나면 part_id 생략 가능, 둘 이상이면 422 MESH_INPUT_PART_REQUIRED,
    없는 ID → MESH_INPUT_PART_NOT_FOUND, 파트에 쉘이 아닌 요소 → MESH_INPUT_UNSUPPORTED_ELEMENT. /PART 카드 없이 쉘 블록만
    있으면 허용 + info MESH_INPUT_PART_CARD_MISSING. 반환 (part_id, 경고)."""
    parts = info["parts"]
    pub = [{k: p[k] for k in ("id", "title", "n_shells")} for p in parts[:PARTS_OUT_MAX]]
    if not parts:
        raise unprocessable("MESH_INPUT_INVALID", up_svc.doe_text("MESH_INPUT_NO_SHELL"), parts=[])
    if part_id is None:
        if len(parts) != 1:
            raise unprocessable("MESH_INPUT_PART_REQUIRED", up_svc.doe_text("MESH_INPUT_PART_REQUIRED", n=len(parts)),
                                parts=pub)
        p = parts[0]
    else:
        p = next((x for x in parts if x["id"] == int(part_id)), None)
        if p is None:
            if int(part_id) in (info.get("other_parts") or {}):      # 쉘 없이 다른 요소만 있는 파트
                raise unprocessable("MESH_INPUT_UNSUPPORTED_ELEMENT",
                                    up_svc.doe_text("MESH_INPUT_UNSUPPORTED_ELEMENT", part_id=int(part_id)), parts=pub)
            raise unprocessable("MESH_INPUT_PART_NOT_FOUND", up_svc.doe_text("MESH_INPUT_PART_NOT_FOUND",
                                                                              part_id=int(part_id)), parts=pub)
    if p["n_other"]:
        raise unprocessable("MESH_INPUT_UNSUPPORTED_ELEMENT",
                            up_svc.doe_text("MESH_INPUT_UNSUPPORTED_ELEMENT", part_id=p["id"]), parts=pub)
    warns = []
    if not p["card"]:
        warns.append({"code": "MESH_INPUT_PART_CARD_MISSING", "level": "info", "index": index,
                      "message": up_svc.doe_text("MESH_INPUT_PART_CARD_MISSING", part_id=p["id"])})
    return int(p["id"]), warns


def _compare_check(ctx: AppContext, principal: Principal, body, c: dict[str, Any]) -> dict[str, Any]:
    """④ check-inputs: 형상 수·기준·이름·중복·업로드·STEP·합계 크기 → ESL → (기준 미지정) 첫 ESL Case 입력 + 경고.
    반환 {"out": DoeCheckOut, "mat": 작업 재료}. 크기 비교(SC-D-7)는 메시 후라 size = null(준비에서 확정)."""
    from ...core.opt_core import EslError
    from ...core.opt_core import doe_scenario
    from ...core.opt_core import size as osize

    cc = c["compare"]
    if body.step_upload_id or body.mesh_upload_id or body.part_title:
        raise unprocessable("INVALID_PARAMS", "step_upload_id·mesh_upload_id·part_title 은 '형상 직접 비교'에서 쓰지 않습니다"
                            "(형상은 shapes)")
    shapes = list(body.shapes or [])
    if not shapes:
        raise unprocessable("SHAPES_EMPTY", "비교할 형상(STEP)을 올리세요")
    if len(shapes) > int(cc["max_shapes"]):
        raise unprocessable("SHAPES_TOO_MANY", f"형상은 최대 {cc['max_shapes']}개 (요청 {len(shapes)}개)",
                            max_shapes=int(cc["max_shapes"]))
    refs = [i for i, sh in enumerate(shapes) if sh.reference]
    if len(refs) > 1:
        raise unprocessable("REFERENCE_MULTIPLE", "기준 형상은 하나만 지정할 수 있습니다", index=refs)
    need = 2 if refs else 1
    if len(shapes) < need:
        raise unprocessable("SHAPES_TOO_FEW", "기준 STEP 을 지정하면 형상이 2개 이상 필요합니다(비교 대상)" if refs else
                            "형상이 1개 이상 필요합니다", min_shapes=need)
    names = [_shape_name(sh.name, i) for i, sh in enumerate(shapes)]
    seen: dict[str, int] = {}
    for i, n in enumerate(names):
        k = n.casefold()
        if k in seen:
            raise unprocessable("SHAPE_NAME_DUPLICATE", f"형상 이름 '{n}' 이 겹칩니다(대소문자 무시)", index=[seen[k], i])
        seen[k] = i
    # v0.16.0 §6 검증 순서: source 값(스키마 — INVALID_PARAMS) → step 에 part_id → (upload_id, rel) 중복 → 형상별 업로드
    for i, sh in enumerate(shapes):
        if sh.source == "step" and sh.part_id is not None:
            raise unprocessable("INVALID_PARAMS", up_svc.doe_text("SHAPE_PART_ID_STEP", index=i + 1), index=i)
    # 메시 형상은 (upload_id, rel, part_id) — 한 rad 의 다른 파트는 다른 형상. rel 생략 + 같은 업로드 규칙은 STEP 만(메시 rel
    # 생략은 주 파일 규칙으로 하나로 정해지고, 실제 같은 파일·파트는 아래 정규화 경로 판정이 거부)
    ups = [(sh.upload_id, sh.rel, sh.part_id if sh.source == "mesh" else None) for sh in shapes]
    steps = [(sh.upload_id, sh.rel) for sh in shapes if sh.source == "step"]
    if len(set(ups)) != len(ups) or any(r is None for u, r in steps if sum(1 for u2, _ in steps if u2 == u) > 1):
        raise unprocessable("INVALID_PARAMS", "같은 업로드 파일(upload_id·rel)을 두 번 넣었습니다 — 한 업로드에 STEP 이 "
                            "여러 개면 형상마다 rel 을 주세요")
    mi = cc["mesh_input"]
    step_idx = [i for i, sh in enumerate(shapes) if sh.source == "step"]
    mesh_idx = [i for i, sh in enumerate(shapes) if sh.source == "mesh"]
    if mesh_idx and not mi["enabled"]:
        raise unprocessable("INVALID_PARAMS", up_svc.doe_text("MESH_INPUT_DISABLED"), index=mesh_idx)
    st = status(ctx)
    if step_idx and not st["gmsh"]["ready"]:        # C2-D-16: 메시 형상만 있는 비교는 gmsh 없이도 허용
        raise DomainError("GMSH_UNAVAILABLE", up_svc.doe_text("SHAPES_STEP_GMSH"), status=503, index=step_idx)
    ra = remesh_available(ctx, c)
    mode = body.mesh_mode or str(cc["mesh"]["mode"])
    # 화면 '실패 시 세분화 허용'(§8): mesh_refine false → 사다리에서 refine_* 제외, 생략 → 설정 ladder 그대로
    ladder = [x for x in cc["mesh"]["ladder"] if body.mesh_refine is not False or not x.startswith("refine_")]
    warns0: list[dict[str, Any]] = []       # v0.16.0 경고(기존 경고 뒤에 붙임 — 기존 순서 불변)
    if step_idx and not ra:
        ver = st["gmsh"].get("version") or "?"
        if mode == "remesh":
            raise unprocessable("REMESH_UNAVAILABLE", up_svc.doe_text(
                "REMESH_UNAVAILABLE" if cc["remesh"]["enabled"] else "REMESH_DISABLED", ver=ver), mesh_mode=mode)
        if mode == "auto" and "remesh" in ladder:      # 사다리에서 remesh 만 빼고 진행(경고 1회)
            warns0.append({"code": "REMESH_UNAVAILABLE",
                           "message": up_svc.doe_text("REMESH_UNAVAILABLE_AUTO", ver=ver)})
    out_shapes, mat_shapes, total = [], [], 0.0
    seen_path: dict[tuple, int] = {}
    for i, sh in enumerate(shapes):
        minfo = pid = None
        try:
            if sh.source == "mesh":
                up, _root, path = up_svc.doe_source(ctx, principal, sh.upload_id, body.project_id, "mesh", rel=sh.rel,
                                                    formats=mi["formats"])
                ext = os.path.splitext(path)[1].lower()
                if ext not in [f.lower() for f in mi["formats"]]:      # rel 생략(주 파일 자동 선택) 경로의 형식 검사
                    raise unprocessable("MESH_FORMAT_UNSUPPORTED", up_svc.doe_text(
                        "MESH_FORMAT_UNSUPPORTED", ext=ext, formats=", ".join(mi["formats"])), formats=list(mi["formats"]))
                minfo = up_svc.mesh_shape_inspect(up, path, mi)
                pid, pw = _pick_mesh_part(minfo, sh.part_id, i)
                warns0 += pw
                info = {"file_name": os.path.basename(path), "size_mb": minfo["size_mb"]}
            else:
                up, _root, path = up_svc.doe_source(ctx, principal, sh.upload_id, body.project_id, "step", rel=sh.rel)
                info = up_svc.step_check(path, float(c["step_max_mb"]))
        except DomainError as exc:
            raise DomainError(exc.code, f"형상 {i + 1}({names[i]}): {exc.message}", status=exc.status,
                              **{**exc.extra, "index": i}) from None
        # 정규화된 동일 파일 판정(v0.14.0 검증 수정): (upload_id, rel=None) 과 같은 파일을 rel 로 고른 형상 등
        # 지정 방식이 달라도 실제 파일이 같으면 거부(같은 내용 다른 파일은 아래 SHAPE_DUPLICATE_FILE 경고만).
        # 메시 형상은 (파일, part_id) — 한 rad 의 다른 파트는 다른 형상
        key = (os.path.normcase(os.path.realpath(path)), pid)
        if key in seen_path:
            raise unprocessable("INVALID_PARAMS", f"형상 {seen_path[key] + 1}({names[seen_path[key]]})·{i + 1}({names[i]}) 이 "
                                "같은 업로드 파일입니다 — 형상마다 다른 STEP 파일을 고르세요", index=[seen_path[key], i])
        seen_path[key] = i
        if minfo is not None:
            sha = minfo["files"][0]["sha256"]
            pub = {"source": "mesh", "part_id": pid, "main_rel": minfo["main_rel"], "files": minfo["files"],
                   "parts": [{k: p[k] for k in ("id", "title", "n_shells")} for p in minfo["parts"][:PARTS_OUT_MAX]]}
            extra = {"source": "mesh", "part_id": pid, "main_rel": minfo["main_rel"], "files": minfo["files"],
                     "upload_root": up["dir_path"]}
        else:
            sha = up_svc.upload_file_sha(up, path)
            total += os.path.getsize(path) / (1024 * 1024)
            rel0 = os.path.relpath(path, up["dir_path"]).replace(os.sep, "/")
            pub = {"source": "step", "part_id": None, "main_rel": rel0}
            extra = {"source": "step"}
        out_shapes.append({"index": i, "name": names[i], "file_name": info["file_name"], "sha256": sha,
                           "size_mb": info["size_mb"], "reference": bool(sh.reference), **pub})
        mat_shapes.append({"path": path, "upload_id": up["id"], "rel": sh.rel, "name": names[i],
                           "file_name": info["file_name"], "sha256": sha, "reference": bool(sh.reference), "_up": up,
                           **extra})
    if total > float(cc["total_max_mb"]):
        raise unprocessable("SHAPES_TOO_LARGE", f"형상 STEP 합계 {total:.1f} MB > 상한 {float(cc['total_max_mb']):g} MB "
                            "(bead_doe.compare.total_max_mb)", total_mb=round(total, 3),
                            limit_mb=float(cc["total_max_mb"]))
    with ctx.engine.connect() as conn:
        rows = entries_in_order(conn, body.project_id, list(body.entry_ids))
    rows = backfill_opt_meta(ctx, rows)
    warns: list[dict[str, Any]] = []
    src = "step" if refs else "case"
    base_out = base_mat = base_db = None
    if src == "case":
        if not rows[0].get("case_id"):
            raise conflict("PREREQUISITE_MISSING", "기준 STEP 이 없으면 첫 ESL 의 Case 입력이 필요합니다", missing=["case"])
        with ctx.engine.connect() as conn:
            base = _s1_base(ctx, conn, body.project_id, rows[0], with_mesh=False)
        base_out = {"entry_id": base["entry_id"], "case_id": base["case_id"], "part_title": base.get("part_title"),
                    "n_nodes": base.get("n_nodes"), "n_elems": base.get("n_elems")}
        base_mat = {"entry_id": base["entry_id"], "case_id": base["case_id"], "rad_path": base["rad_path"],
                    "part_title": base.get("part_title"), "case_dir": os.path.dirname(base["rad_path"])}
        base_db = {**base_out, "case_title": base.get("case_title"), "rad_file_name": base.get("rad_file_name"),
                   "source": "case"}
        warns.append({"code": "COMPARE_REF_CASE_MESH",
                      "message": "기준이 낙하 메시(다른 메싱 방식)라 개선율에 메시 차이가 섞입니다 — 기준 STEP 지정을 권장합니다"})
    dup: dict[tuple, int] = {}
    for x in out_shapes:                    # 메시 형상은 (주 파일 sha256, part_id) — 같은 rad 의 다른 파트는 다른 형상
        dk = (x["sha256"], x.get("part_id"))
        if dk in dup:
            warns.append({"code": "SHAPE_DUPLICATE_FILE", "message": f"형상 {dup[dk] + 1}·{x['index'] + 1} 이 같은 "
                          f"{'메시' if x.get('source') == 'mesh' else 'STEP'} 파일(sha256)입니다",
                          "index": [dup[dk], x["index"]]})
        dup.setdefault(dk, x["index"])
    warns += warns0
    try:
        osize.assert_ok([_size_row(e) for e in rows], opt_settings(ctx.settings)["size"])
    except EslError as exc:
        raise _esl_error(exc) from None
    _mesh, _meta, raw = _entry_mesh(ctx, rows[0])
    try:
        pd = doe_scenario.props_default(raw)
    except (EslError, KeyError, ValueError) as exc:
        raise unprocessable("MESH_INVALID", f"기준 ESL 메시에서 물성 기본값을 얻지 못했습니다: {exc}") from None
    props_default = {"t": float(pd["t"]), "E": float(pd["E"]), "nu": float(pd["nu"])}
    # SC-D-4 형상 id: 기준 STEP = d000, 나머지 요청 순서 d001…(기준 미지정이면 d000 = Case 메시, STEP 은 d001…)
    order = ([i for i in range(len(mat_shapes)) if mat_shapes[i]["reference"]]
             + [i for i in range(len(mat_shapes)) if not mat_shapes[i]["reference"]])
    k0 = 0 if src == "step" else 1
    for k, i in enumerate(order):
        mat_shapes[i]["id"] = f"d{k + k0:03d}"
        out_shapes[i]["id"] = mat_shapes[i]["id"]
    per_up: dict[tuple, list] = {}
    for sh in mat_shapes:
        up = sh.pop("_up")
        rel = os.path.relpath(sh["path"], up["dir_path"]).replace(os.sep, "/")
        purpose = up_svc.DOE_MESH_PURPOSE if sh.get("source") == "mesh" else up_svc.DOE_STEP_PURPOSE
        row = {"rel": rel, "sha256": sh["sha256"]}
        if sh.get("source") == "mesh":      # 메시 형상: 파트 ID·주 + include 파일 목록(C2-D-3 — BD_INPUT 이 sha 재확인)
            row.update(part_id=sh["part_id"], files=sh["files"])
        per_up.setdefault((up["id"], purpose), []).append(row)
    for (uid, purpose), fs in per_up.items():   # 업로드·용도당 1회(한 세션 여러 형상이면 files 목록)
        extra = {"files": fs} if len(fs) > 1 else (
            {k: fs[0][k] for k in ("part_id", "files")} if purpose == up_svc.DOE_MESH_PURPOSE else None)
        up_svc.save_doe_check(ctx, uid, purpose, fs[0]["rel"], fs[0]["sha256"], True, extra)
    out = {"ok": True, "step": None, "shapes": out_shapes, "reference_source": src, "base": base_out,
           "mesh": None, "entries": [{"entry_id": e["id"], "ok": True, "reason": None} for e in rows], "size": None,
           "props_default": props_default, "mesh_size_default_mm": float(cc["mesh"]["size_mm"]), "warnings": warns,
           "mesh_mode": mode, "remesh_available": ra}
    mat = {"rows": rows, "step": None, "shapes": [mat_shapes[i] for i in order], "reference_source": src,
           "base": base_mat, "base_db": base_db, "mesh": None, "props_default": props_default,
           "mesh_size_default_mm": float(cc["mesh"]["size_mm"]), "mesh_mode": mode,
           "mesh_refine": body.mesh_refine, "mesh_ladder": ladder}
    return {"out": _jsonable(out), "mat": mat}


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
    got = _preview_grid(ctx, s, c)
    return None if got is None else got[0]


def _preview_grid(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> tuple[list[dict[str, Any]], dict] | None:
    """(셀 목록, grid_manifest) 또는 None. v0.16.1 select(esl_select_relax.md §4.3): 셀 warnings(있을 때만)·fixed_viol(침범이
    있으면 상태와 무관 — 코어가 기록한 대로)."""
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
    mcells = [x for x in (g.get("manifest") or {}).get("cells") or [] if isinstance(x, dict)]
    # v0.15.1 select 고정 침범 원인(코어 bd_select_grid 셀 fixed_viol — 있을 때만 그대로 전달)
    viol = {str(x.get("id")): x["fixed_viol"] for x in mcells if isinstance(x.get("fixed_viol"), dict)}
    # v0.16.1 경고 안(READY + SELECT_FIXED_MOVED·SELECT_QUALITY_WARN) — 비었으면 키 없음
    cwarn = {str(x.get("id")): [w for w in x["warnings"] if isinstance(w, dict)] for x in mcells
             if isinstance(x.get("warnings"), list) and any(isinstance(w, dict) for w in x["warnings"])}
    out = []
    for d in m["designs"]:
        if d.get("id") == "d000":
            continue
        r = by.get(d["id"]) or {"state": "SKIPPED_GEOM", "code": "GRID_CELL_MISSING", "warning": None}
        thumb = r.get("warning") != "THUMB_UNAVAILABLE" and _cell_thumb(gdir, g.get("manifest") or {}, d["id"]) is not None
        row = {"id": d["id"], "values": d.get("values") or {}, "status": r["state"], "code": r.get("code"),
               "thumb": bool(thumb)}
        if d["id"] in viol:
            row["fixed_viol"] = viol[d["id"]]
        ws = r.get("warnings") if isinstance(r.get("warnings"), list) and r.get("warnings") else cwarn.get(d["id"])
        if ws:
            row["warnings"] = ws
        out.append(row)
    return out, (g.get("manifest") or {})


def _doe_out(ctx: AppContext, s: dict[str, Any], c: dict[str, Any]) -> dict[str, Any] | None:
    doe = s.get("doe")
    if not isinstance(doe, dict):
        return None
    d = {k: doe.get(k) for k in ("rev", "spec", "matrix_sha256", "n_designs")}
    if s.get("scenario") == "select":
        d["selection_sha256"] = doe.get("selection_sha256")
    pv = doe.get("preview")
    if isinstance(pv, dict):
        sk_keys = ("collision", "fixed", "geom") + (("mesh",) if s.get("scenario") == "select" else ())
        p = {"rev": pv.get("rev"), "matrix_sha256": pv.get("matrix_sha256"), "ok": int(pv.get("ok") or 0),
             "skipped": {k: int((pv.get("skipped") or {}).get(k) or 0) for k in sk_keys}}
        if s.get("scenario") == "select":   # BS-D-3: 미리보기는 선택 sha 까지 같아야 유효
            p["selection_sha256"] = pv.get("selection_sha256") or doe.get("selection_sha256")
            if pv.get("warn") is not None:   # v0.16.1 경고 READY 안 수(워커 요약)
                p["warn"] = int(pv.get("warn") or 0)
        got = _preview_grid(ctx, s, c)
        if got is not None:
            p["cells"] = got[0]
            # v0.16.1 §7.4: 판정 규칙 판(grid_manifest.rules)이 없는 select 미리보기 = v0.16.0 규칙(경고 안도 제외됨) — 화면 띠
            if s.get("scenario") == "select" and not isinstance(got[1].get("rules"), int):
                p["rules_outdated"] = True
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
        p0 = prep
        prep = {"n_beads": int(p0.get("n_beads") or 0), "n_params": int(p0.get("n_params") or 0),
                "paicad_version": p0.get("paicad_version") or s.get("paicad_version"),
                "warnings": list(p0.get("warnings") or []),
                "boundary": p0.get("boundary") or {"n_warn": 0, "n_info": 0}}
        if s["scenario"] == "compare":      # ④ 준비 요약(형상 상태·요소 수·실패 사유)
            prep.update({k: p0.get(k) for k in ("n_shapes", "n_ready", "failed", "reference_source", "shapes", "mesh")})
            if p0.get("n_defeature") is not None:   # v0.16.1 작은 형상 억제 단계로 메시한 형상 수(워커 준비 요약)
                prep["n_defeature"] = int(p0["n_defeature"])
        elif s["scenario"] == "select":     # select 준비 요약(BD_PREP_REGISTER — 노드·요소 수·고정 출처)
            prep.update({k: p0.get(k) for k in ("n_nodes", "n_elems", "fixed")})
            if isinstance(p0.get("auto"), dict):    # v0.16.2 자동 탐지 결과 {ok, step, code, available, n_beads}(auto 만)
                prep["auto"] = p0["auto"]
            if p0.get("select_base") == "mesh":     # v0.16.2 ② B 메시 기준(① 은 키 없음)
                prep["select_base"] = "mesh"
    if s["scenario"] == "select":       # v0.16.2 §3.1: bead_source 기본 manual(v0.16.1 이전 select 스터디), select_base 는 있을 때만
        inputs.setdefault("bead_source", "manual")
    return {"id": s["id"], "project_id": s["project_id"], "scenario": s["scenario"], "title": s["title"],
            "entry_ids": list(s["entry_ids"]), "inputs": inputs, "phase": phase, "version": int(s["version"]),
            "prep": prep, "doe": _doe_out(ctx, s, c), "job": job_out(conn, job, with_steps=True) if job else None,
            "result_ready": rr, "created_by_name": s["created_by_name"], "created_at": s["created_at"],
            "selection": _select().selection_summary(s)}


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
    if body.scenario == "compare":
        if body.mesh_size_mm is not None:
            raise unprocessable("INVALID_PARAMS", "형상 직접 비교의 요소 크기는 설정(bead_doe.compare.mesh.size_mm)으로 고정입니다")
        props = body.props.model_dump() if body.props is not None else dict(mat["props_default"])
        return {k: float(props[k]) for k in ("t", "E", "nu")}, None
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
                      warns: list, selection: dict | None = None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        s = doe_repo.insert_study(conn, id=sid, project_id=project_id, scenario=scenario, title=title,
                                  entry_ids=entry_ids, base=_jsonable(base_db) if base_db else null(),
                                  inputs=_jsonable(inputs), phase="PREP", dir_rel=f"{DOE_DIR}/{sid}",
                                  created_by=principal.user_id, created_by_name=principal.display_name,
                                  **({"selection": _jsonable(selection)} if selection is not None else {}))
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


def _create_compare(ctx: AppContext, principal: Principal, body, out: dict[str, Any], mat: dict[str, Any],
                    props: dict[str, Any]) -> dict[str, Any]:
    """④ 연구 생성: inputs = {shapes[{id, name, file_name, sha256, upload_id, reference, source, part_id}], reference_source,
    inch, props, mesh_mode}, 작업 params.doe += shapes[{… path, source(, 메시: upload_root·main_rel·part_id·files)}],
    reference_source, base?(Case 기준), props, mesh_mode."""
    import datetime as _dt

    lib_cfg = require_library_config(ctx)
    rows = mat["rows"]
    sid = str(uuid.uuid4())
    doe_dir(ctx.settings, sid)
    first = next((x for x in mat["shapes"] if not x["reference"]), mat["shapes"][0])
    title = (body.title or "").strip() or f"형상 직접 비교 {first['name']} 외 {max(len(mat['shapes']) - 1, 0)}"[:200]
    shapes_db = [{**{k: x[k] for k in ("id", "name", "file_name", "sha256", "upload_id", "rel", "reference")},
                  "source": x.get("source", "step"), "part_id": x.get("part_id")} for x in mat["shapes"]]
    # v0.16.0 §3: inputs.shapes[] += {source, part_id}, inputs += {mesh_mode}(요청 또는 설정 — v0.15.x 스터디는 없음 = cad)
    # mesh_refine(요청 원값, null = 설정)·mesh_ladder(적용 사다리 — 워커가 auto 에서 이 순서로 시도)
    inputs = {"shapes": shapes_db, "reference_source": mat["reference_source"], "inch": body.inch, "props": props,
              "mesh_mode": mat["mesh_mode"], "mesh_refine": mat["mesh_refine"]}
    doe = {"id": sid, "scenario": "compare", "title": title,
           "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "cfg": _snapshot_cfg(ctx),
           "core": copy.deepcopy(ctx.config.core or {}), "mapping": (lib_cfg or {}).get("mapping"),
           "entries": [{"id": e["id"], "dir": entry_folder(ctx, e), "label": _entry_label(e), "case": e.get("case_id")}
                       for e in rows],
           "shapes": [dict(x) for x in mat["shapes"]], "reference_source": mat["reference_source"],
           "inch": body.inch, "props": props, "mesh_mode": mat["mesh_mode"], "mesh_refine": mat["mesh_refine"],
           "mesh_ladder": list(mat["mesh_ladder"])}
    if mat["base"]:
        doe["base"] = dict(mat["base"])
    params = {"bead_doe_id": sid, "kind": "PREP", "out_rel": f"{DOE_DIR}/{sid}", "doe": doe,
              "warnings": list(out["warnings"])}
    return _insert_study_job(ctx, principal, sid=sid, project_id=body.project_id, scenario="compare", title=title,
                             entry_ids=[e["id"] for e in rows], base_db=mat["base_db"], inputs=inputs, params=params,
                             warns=out["warnings"])


def create_study(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    c = cfg(ctx)
    r = check_inputs(ctx, principal, body, _internal=True)
    out, mat = r["out"], r["mat"]
    require_eligible(mat["rows"])                 # v0.10.0 MR-D-10: 현재 기준 PASS 항목만(422 ENTRY_NOT_ELIGIBLE)
    if body.scenario == "compare":
        props, _h = _validate_step_extras(body, c, mat)
        return _create_compare(ctx, principal, body, out, mat, props)
    if body.scenario in ("same", "select") and not out["ok"]:
        bad = [e for e in out["entries"] if not e["ok"]]
        raise unprocessable("MODEL_MISMATCH", f"기준 모델과 다른 ESL {len(bad)}개 — '같은 모델' DOE 는 같은 모델만"
                            "(다른 모델은 빼거나 '다른 모델' 시나리오 사용)", entries=bad)
    props, h = _validate_step_extras(body, c, mat)
    lib_cfg = require_library_config(ctx)
    rows = mat["rows"]
    sid = str(uuid.uuid4())
    doe_dir(ctx.settings, sid)                    # 경로 안전성(실제 생성은 워커)
    sel_mesh = body.scenario == "select" and mat.get("select_base") == "mesh"
    if body.scenario == "select":
        b0 = out.get("base") or {}
        label = (mat["mesh"] or {}).get("file_name") if sel_mesh else (b0.get("case_title") or b0.get("part_title"))
        kind = "비드 직접 선택 · B 메시" if sel_mesh else "비드 직접 선택"
        title = (body.title or "").strip() or f"강성 평가 스터디 {label or ''} ({kind})".replace("  ", " ")
    else:
        title = (body.title or "").strip() or f"강성 평가 스터디 {out['step']['file_name']}"
    part_title = (mat["mesh"] or {}).get("part_title") if (body.scenario == "mesh" or sel_mesh) else (
        (mat["base"] or {}).get("part_title") if body.scenario in ("same", "select") else None)
    step_p = mat["step"]
    inputs = {"step": {"upload_id": step_p["upload_id"], "file_name": step_p["file_name"], "sha256": step_p["sha256"]}
              if step_p else None,
              "mesh": None, "part_title": part_title, "inch": body.inch, "props": props, "mesh_size_mm": h}
    if mat["mesh"]:
        mp = mat["mesh"]
        inputs["mesh"] = {"upload_id": mp["upload_id"], "file_name": mp["file_name"], "sha256": mp["sha256"]}
    if body.scenario == "select":       # v0.16.2 §3.1: bead_source(select 만), select_base 는 "mesh" 일 때만(① = 키 없음, AD-D-22)
        inputs["bead_source"] = mat["bead_source"]
        if sel_mesh:
            inputs["select_base"] = "mesh"
    import datetime as _dt

    created = _dt.datetime.now(_dt.timezone.utc).isoformat()
    doe = {"id": sid, "scenario": body.scenario, "title": title, "created_at": created, "cfg": _snapshot_cfg(ctx),
           "core": copy.deepcopy(ctx.config.core or {}), "mapping": (lib_cfg or {}).get("mapping"),
           "entries": [{"id": e["id"], "dir": entry_folder(ctx, e), "label": _entry_label(e), "case": e.get("case_id")}
                       for e in rows],
           "inch": body.inch}
    if step_p:
        doe["step"] = dict(step_p)
    if mat["base"]:
        doe["base"] = dict(mat["base"])
    if mat["mesh"]:
        doe["mesh"] = dict(mat["mesh"])
    if props is not None:
        doe["props"] = props
        doe["mesh_size_mm"] = h
    if body.scenario == "select":       # 워커·코어 분기(BD_INPUT _sel_input·BD_GEOM plan) — select_base 는 mesh 일 때만
        doe["bead_source"] = mat["bead_source"]
        if sel_mesh:
            doe["select_base"] = "mesh"
    params = {"bead_doe_id": sid, "kind": "PREP", "out_rel": f"{DOE_DIR}/{sid}", "doe": doe,
              "warnings": list(out["warnings"])}
    return _insert_study_job(ctx, principal, sid=sid, project_id=body.project_id, scenario=body.scenario, title=title,
                             entry_ids=[e["id"] for e in rows], base_db=mat["base_db"], inputs=inputs, params=params,
                             warns=out["warnings"])


# ---------------------------------------------------------------- 준비 결과: 변수 표·비드 PNG·평면도
def _no_compare(s: dict[str, Any]) -> None:
    """④ 에는 변수·DOE·미리보기·평면도가 없다(SC-D-1) → 409 SCENARIO_UNSUPPORTED."""
    if s.get("scenario") == "compare":
        raise conflict("SCENARIO_UNSUPPORTED", "형상 직접 비교에는 변수·DOE 행렬·미리보기·평면도가 없습니다",
                       scenario="compare")


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
    _no_compare(s)
    _require_prep(s, job)
    if s["scenario"] == "select":       # 변수 = 저장 선택(BS-D-6·7) — prep/params.json 없음
        doc = _select().refresh_derived(ctx, s, c, _select().require_selection(ctx, s, c))   # v0.16.1 §7.5 algo 지연 갱신
        with ctx.engine.connect() as conn:
            mc = _study_cfg(conn, s, c)     # 행렬 생성·작업 표와 같은 설정(fixed_policy·range — 같은 표)
        return _select().params_table(doc, mc)
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
    _no_compare(s)
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
    _no_compare(s)
    _require_prep(s, job)
    if s["scenario"] == "select":
        return _select().plan_view(ctx, principal, sid)
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

    if s.get("scenario") == "select":    # select 변수 표 = 저장 선택(워커는 params.doe.selection.params 로 같은 표)
        tab = _select().params_table(_select().require_selection(ctx, s, cfg(ctx)), c)["params"]
    else:
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
    _no_compare(s)
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
    _no_compare(s0)
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
        sel = _select().require_selection(ctx, s, c) if s["scenario"] == "select" else None
        mc = _study_cfg(conn, s, c)
        m = _generate(ctx, s, spec, mc)
        base = _prep_params(conn, s)
        rev = int(((s.get("doe") or {}).get("rev")) or 0) + 1
        doe = copy.deepcopy(base["doe"])
        doe.update(rev=rev, spec=m["spec"], matrix_sha256=m["matrix_sha256"], paicad_version=s.get("paicad_version"))
        new_doe = {"rev": rev, "spec": m["spec"], "matrix_sha256": m["matrix_sha256"], "n_designs": m["n_designs"],
                   "preview": None}
        if sel is not None:                 # BS-D-3·BD_MATRIX: 선택 rev·sha 와 변수 표를 작업에 고정
            doe["selection"] = _select().job_selection(sel, mc)
            new_doe["selection_sha256"] = sel["sha256"]
        params = {"bead_doe_id": sid, "kind": "PREVIEW", "out_rel": s["dir_rel"], "doe": doe,
                  "warnings": [w for w in m["warnings"]]}
        s = doe_repo.update_study(conn, sid, phase="PREVIEW", doe=_jsonable(new_doe))
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
        if s["scenario"] == "compare":      # SC-D-1: PREP → READY → RUN(행렬·미리보기 없음, matrix_sha256 무시)
            if _derived_phase(s, job) != "READY" or s.get("prep") is None:
                raise conflict("PREP_NOT_READY", "입력 준비가 끝나지 않았습니다 — [입력 준비]를 먼저 하세요")
            base = _prep_params(conn, s)
            run_opts = {"solver": "linear", "parallel": int(c["run"]["parallel"])}
            d = copy.deepcopy(base["doe"])
            d.update(run=run_opts)
            params = {"bead_doe_id": sid, "kind": "RUN", "out_rel": s["dir_rel"], "doe": d, "warnings": []}
            s = doe_repo.update_study(conn, sid, phase="RUN", run=run_opts)
            job = _insert_job(conn, principal, s, "DOE_RUN", params)
            return study_out(ctx, conn, s, job, c=c)
        doe = s.get("doe") or {}
        pv = doe.get("preview") or {}
        if (_derived_phase(s, job) != "PREVIEW_READY" or not pv or pv.get("matrix_sha256") != doe.get("matrix_sha256")
                or body.matrix_sha256 != doe.get("matrix_sha256")):
            raise conflict("PREVIEW_STALE", "이 DOE 행렬의 미리보기가 끝나지 않았거나 행렬이 바뀌었습니다 — 미리보기를 다시 하세요",
                           matrix_sha256=doe.get("matrix_sha256"))
        sel = None
        if s["scenario"] == "select":       # BS-D-3: 선택 sha 까지 같아야(선택을 고친 뒤 미리보기 안 했으면 409)
            sel = _select().current(ctx, s, c)
            psha = pv.get("selection_sha256") or doe.get("selection_sha256")
            if sel is None or not psha or psha != sel.get("sha256"):
                raise conflict("PREVIEW_STALE", "비드 선택이 미리보기 뒤에 바뀌었습니다 — 미리보기를 다시 하세요",
                               matrix_sha256=doe.get("matrix_sha256"), selection_sha256=(sel or {}).get("sha256"))
        base = _prep_params(conn, s)
        run_opts = {"solver": "linear", "parallel": int(c["run"]["parallel"])}
        d = copy.deepcopy(base["doe"])
        d.update(rev=int(doe["rev"]), spec=doe["spec"], matrix_sha256=doe["matrix_sha256"],
                 paicad_version=s.get("paicad_version"), run=run_opts)
        if sel is not None:
            d["selection"] = _select().job_selection(sel, _study_cfg(conn, s, c))
        params = {"bead_doe_id": sid, "kind": "RUN", "out_rel": s["dir_rel"], "doe": d,
                  "preview": {"rev": pv.get("rev"), "ok": pv.get("ok")}, "warnings": []}
        s = doe_repo.update_study(conn, sid, phase="RUN", run=run_opts)
        job = _insert_job(conn, principal, s, "DOE_RUN", params)
        return study_out(ctx, conn, s, job, c=c)


def _clone_shape_present(x: dict[str, Any]) -> bool:
    """④ 복제 전제: STEP = 파일 1개, 메시(v0.16.0 §6) = 주 + include 업로드가 모두 남아 있어야(링크·업로드 폴더 밖 아님)."""
    from ...core.config import is_within

    def ok(p: str | None) -> bool:
        return bool(p) and os.path.isfile(p) and not os.path.islink(p)
    if not ok(x.get("path")):
        return False
    if x.get("source") != "mesh":
        return True
    root = x.get("upload_root")
    if not root:
        return False
    real = os.path.realpath(root)
    for f in x.get("files") or []:
        p = os.path.join(root, *str(f.get("rel") or "").split("/"))
        if not f.get("rel") or not ok(p) or not is_within(os.path.realpath(p), real):
            return False
    return True


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
        uids = [(k, (snap.get(k) or {}).get("upload_id")) for k in ("step", "mesh")]
        uids += [(f"shapes[{i}]", (x or {}).get("upload_id")) for i, x in enumerate(snap.get("shapes") or [])]
        for k, uid in uids:
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
    if s["scenario"] == "compare":       # ④ 모든 형상 업로드가 남아 있어야(missing = 형상 순서 index — id 순)
        shapes_old = old.get("shapes") or []
        miss = [i for i, x in enumerate(shapes_old) if not _clone_shape_present(x)]
        if miss:
            raise conflict("PREREQUISITE_MISSING", f"원 연구의 형상 STEP 업로드 {len(miss)}개가 더 이상 없습니다 — 새로 올려 주세요",
                           missing=miss)
        step_i = [i for i, x in enumerate(shapes_old) if x.get("source", "step") == "step"]
        if step_i and not status(ctx)["gmsh"]["ready"]:      # C2-D-16: STEP 형상은 gmsh 필요(메시 형상만이면 허용)
            raise DomainError("GMSH_UNAVAILABLE", up_svc.doe_text("SHAPES_STEP_GMSH"), status=503, index=step_i)
    elif s["scenario"] != "select" or old.get("step") or old.get("mesh"):
        # select(manual·case) 는 업로드 입력 없음(같은 Case 메시). v0.16.2 select auto = STEP, select(mesh) = B 메시 업로드
        need = ["step"] if s["scenario"] != "select" else [k for k in ("step", "mesh") if old.get(k)]
        miss = [k for k in need if not (old.get(k) or {}).get("path") or not os.path.isfile(old[k]["path"])
                or os.path.islink(old[k]["path"])]
        if miss:
            raise conflict("PREREQUISITE_MISSING", "원 연구의 STEP·B 메시 업로드가 더 이상 없습니다 — 새로 올려 주세요"
                           if miss != ["step"] else "원 연구의 STEP 업로드가 더 이상 없습니다 — 새로 올려 주세요", missing=miss)
    nid = str(uuid.uuid4())
    doe_dir(ctx.settings, nid)
    import datetime as _dt

    d = {k: copy.deepcopy(v) for k, v in old.items() if k not in ("rev", "spec", "matrix_sha256", "run",
                                                                   "paicad_version", "design", "paicad", "selection")}
    sel_copy, sel_warns = _select().clone_selection(ctx, s, cfg(ctx))
    new_title = (title or "").strip() or f"{s['title']} (복제)"[:200]
    d.update(id=nid, title=new_title, created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
             cfg=_snapshot_cfg(ctx), core=copy.deepcopy(ctx.config.core or {}))
    params = {"bead_doe_id": nid, "kind": "PREP", "out_rel": f"{DOE_DIR}/{nid}", "doe": d,
              "warnings": list(prep_job["params"].get("warnings") or []) + sel_warns}
    return _insert_study_job(ctx, principal, sid=nid, project_id=s["project_id"], scenario=s["scenario"],
                             title=new_title, entry_ids=list(s["entry_ids"]), base_db=s.get("base"),
                             inputs=dict(s.get("inputs") or {}), params=params, warns=sel_warns, selection=sel_copy)


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


RESULT_SORT_KEYS = ("score", "worst_ratio", "geo_mean_improvement", "n_worsened", "pareto")


def results(ctx: AppContext, principal: Principal, sid: str, sort: str = "score") -> dict[str, Any]:
    """DoeResultOut. sort = 순위표 정렬 키(기본 score — rank 필드는 score 순위 그대로, 계약 §11.4)."""
    if sort not in RESULT_SORT_KEYS:
        raise unprocessable("INVALID_PARAMS", f"sort 는 {list(RESULT_SORT_KEYS)} 중 하나", sort=sort)
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
    excluded = [{"id": d["id"], "status": d.get("status"), "code": d.get("code"), "values": vals.get(d["id"], {}),
                 **({"shape": d["shape"]} if isinstance(d.get("shape"), dict) else {})}
                for d in designs.get("designs") or []
                if isinstance(d, dict) and d.get("id") != "d000" and d.get("status") not in ("OK", None)]
    ranking = []
    for x in r.get("ranking") or []:
        row = {k: v for k, v in x.items() if k != "C"}
        if row.get("noise") is None:
            row.pop("noise", None)
        ranking.append(row)
    if sort != "score" and all("worst_ratio" in x for x in ranking):
        from ...core import opt_core

        ranking = opt_core.doe_sort_rows(ranking, sort)
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
    if r.get("sensitivity") is None and r.get("sensitivity_reason") and r.get("sensitivity_reason") != "COMPARE_NO_PARAMS":
        warns.append({"code": "SENSITIVITY_TOO_FEW", "message": str(r.get("sensitivity_reason"))})
    keep_b = ("id", "score", "umax", "epsmax") + (("shape",) if s["scenario"] == "compare" else ())
    out = {"scenario": s["scenario"], "reference_source": r.get("reference_source"),
           "sensitivity_reason": r.get("sensitivity_reason"),
           "C_ref": r.get("C_ref"), "baseline": {k: b.get(k) for k in keep_b} | {"id": "d000"},
           "n_ok": int(r.get("n_ok") or 0), "n_skipped": {k: int(v) for k, v in (r.get("n_skipped") or {}).items()},
           "n_failed": {k: int(v) for k, v in (r.get("n_failed") or {}).items()}, "ranking": ranking,
           "excluded": excluded, "sensitivity": r.get("sensitivity"),
           "boundary_warnings_n": int(r.get("boundary_warnings_n") or 0),
           "view3d": [str(v) for v in r.get("view3d") or [] if v], "best": best, "noise_floor": r.get("noise_floor"),
           "ratio_tol": r.get("ratio_tol"), "per_esl_inline": bool(r.get("per_esl_inline")),
           "esl": [e for e in r.get("esl") or [] if isinstance(e, dict)], "sort": sort, "warnings": warns}
    # v0.16.1 select(SR-D-11): 경고 없는 최상위 안(코어 결과 summary.best_clean — 있을 때만). 순위 행 warn 은 행 그대로
    rs = r.get("summary") if isinstance(r.get("summary"), dict) else {}
    if "best_clean" in rs or "best_clean" in r:
        out["summary"] = {"best_clean": rs.get("best_clean", r.get("best_clean"))}
    return _jsonable(out)


def results_per_esl(ctx: AppContext, principal: Principal, sid: str, design: str | None) -> dict[str, Any]:
    """§11.4 ESL별 지표(post/per_esl.json): design = 쉼표로 구분한 안 id(없으면 전부, 최대 max_designs)."""
    c = cfg(ctx)
    s, job = _viewable(ctx, principal, sid)
    if _derived_phase(s, job) != "DONE":
        raise conflict("RESULT_NOT_READY", "DOE 실행 결과가 아직 없습니다")
    d = _read_json(os.path.join(study_dir(ctx, s), "post", "per_esl.json"), _max_mb(c))
    if not isinstance(d, dict):
        raise conflict("RESULT_NOT_READY", "ESL별 지표(post/per_esl.json)가 없습니다 — v0.10.0 이전 실행은 복제해 다시 실행")
    allv = d.get("designs") or {}
    ids = [x for x in (design or "").split(",") if x] if design else sorted(allv)
    if len(ids) > int(c["max_designs"]):
        raise unprocessable("INVALID_PARAMS", f"design 은 최대 {c['max_designs']}개")
    miss = [i for i in ids if i not in allv]
    if miss:
        raise DomainError("DESIGN_NOT_FOUND", f"순위 안에 없는 안입니다: {miss[:5]}", status=404, designs=miss)
    names = d.get("names") if isinstance(d.get("names"), dict) else {}
    return _jsonable({"esl": d.get("esl") or [], "ratio_tol": d.get("ratio_tol"),
                      "designs": [{"id": i, "per_esl": allv[i], **({"name": names[i]} if i in names else {})}
                                  for i in ids]})


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
    _no_compare(s)
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


# ---------------------------------------------------------------- v0.16.1 ④ 작은 형상 억제 목록(esl_select_relax.md §5A.5·§9)
DEFEATURE_LIST = "defeature.json"      # prep/shapes/<did>/mesh/defeature.json(코어 SR-D-20 — defeature 단계로 메시한 형상만)


def shape_defeature(ctx: AppContext, principal: Principal, sid: str, did: str) -> dict[str, Any]:
    """GET …/shapes/{did}/defeature: 억제 목록 그대로(읽기 — 권한 = 스터디 조회). 경로 고정(prep/shapes/<did>/mesh/ 안, 링크
    거부), ④ 가 아니거나 형상 id 형식이 아니거나 파일이 없으면 404 NOT_FOUND."""
    c = cfg(ctx)
    s, _job = _viewable(ctx, principal, sid)
    msg = "작은 형상 억제 목록이 없습니다(형상 단순화 단계로 메시한 형상만)"
    if s.get("scenario") != "compare" or not DID_RE.match(did or ""):
        raise not_found("NOT_FOUND", msg)
    base = study_dir(ctx, s)
    d = safe_case_file(base, f"prep/shapes/{did}/mesh")
    parts = [os.path.join(base, "prep"), os.path.join(base, "prep", "shapes"), os.path.join(base, "prep", "shapes", did), d]
    if any(os.path.islink(x) for x in parts):
        raise not_found("NOT_FOUND", msg)
    doc = _read_json(os.path.join(d, DEFEATURE_LIST), _max_mb(c))      # 링크·크기 초과·깨진 JSON = None
    if not isinstance(doc, dict):
        raise not_found("NOT_FOUND", msg)
    return _jsonable(doc)


__all__ = ["settings_out", "check_inputs", "create_study", "list_studies", "get_study", "params_out", "plan_view",
           "matrix", "preview", "run", "clone", "results", "results_per_esl", "list_files", "study_file", "report", "bundle", "thumb",
           "view3d_manifest", "view3d_file", "bead_png", "retry_job", "status", "reset_status_cache",
           "shape_defeature"]
