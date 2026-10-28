"""S2 템플릿(계약 esl_opt_run.md §3.2·§5·§7.2, OR-D-8·9): 검사·등록·목록·상세·삭제(보관).

- 템플릿은 전역 자원: ACTIVE 로그인 누구나 조회·사용, 등록 = (업로드한 프로젝트의) power 이상, 삭제 = 등록자·전역 관리자.
- 검사(`POST /opt/templates/check`): 본인 업로드(파일을 모두 받은 것)의 `.fem` 또는 `.rad`(+include, 업로드 밖 include
  거부)를 코어 ``esl.opt.mesh_check.check_file`` 로 읽기만 한다 → 결과를 uploads.result(purpose = template)에 저장, COMPLETED.
- 등록(`POST /opt/templates`): 업로드 파일 sha256 이 검사 때와 같아야 함(아니면 409 PLATE_CHANGED). 업로드 파일을
  ``<esl_root>/_templates/<id>/input/`` 로 복사(sha256 재확인) → ``template.npz``(법선 n 쪽 정렬 메시, esl.opt.target
  .build_template) · ``template.json``(frame·법선·자동 3-2-1·형식·sha256) · ``preview.json``(평면도 자료, esl.opt.keepout
  .plan_view — 워커 마스크와 같은 함수) + DB 행. 실패하면 만든 폴더는 ``_templates/_backup/`` 으로(삭제 없음).
- 삭제: 실행이 참조 중이면 ARCHIVED(보관 — 새 실행 거부, retry 는 허용), 아니면 행 삭제(금지 영역 세트 함께) + 폴더를
  ``_templates/_backup/<UTC>_<id>`` 로 이동.
- 쓰기는 ``_templates/<id>/`` 아래만. 업로드 폴더는 읽기만.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import uuid
from typing import Any

import numpy as np
from sqlalchemy import func

from ...core import uploads as U
from ...core.auth import Principal
from ...core.config import opt_settings
from ...core.errors import DomainError, conflict, forbidden, not_found, unprocessable
from ...core.inputs import sha256_file
from ...core.paths import TEMPLATE_DIR, esl_subdir, template_dir
from ...core.repositories import opt as opt_repo
from ..context import AppContext
from . import uploads as up_svc
from .common import require_config_ok, require_execute

MESH_ERRORS = ("MESH_INVALID", "MESH_FORMAT_UNSUPPORTED", "PART_NOT_FOUND", "PART_AMBIGUOUS")
TEMPLATE_EXT = [".rad", ".inc", ".fem"]


def _cfg(ctx: AppContext) -> dict[str, Any]:
    return opt_settings(ctx.settings)


def _depth(ctx: AppContext) -> int:
    return int(((ctx.config.core or {}).get("case") or {}).get("rad_include_max_depth") or 8)


def _axis_ref(ctx: AppContext) -> dict | None:
    lib = ctx.config.library or {}
    return (lib.get("library") or {}).get("axis_ref")


def _stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _stash(ctx: AppContext, d: str, tid: str) -> str | None:
    """템플릿 폴더를 _templates/_backup/<UTC>_<id> 로 옮긴다(삭제 없음)."""
    if not os.path.lexists(d):
        return None
    if U.is_link_like(d):
        raise unprocessable("PATH_UNSAFE", "템플릿 폴더가 링크입니다")
    bdir = esl_subdir(ctx.settings, TEMPLATE_DIR, "_backup")
    os.makedirs(bdir, exist_ok=True)
    dst = os.path.join(bdir, f"{_stamp()}_{tid}")
    shutil.move(d, dst)
    return dst


# ---------------------------------------------------------------- 직렬화·파일
def template_out(t: dict[str, Any], principal: Principal | None, n_runs: int) -> dict[str, Any]:
    q = t.get("quality") or {}
    d = dict(t)
    d["quality_warnings"] = list(q.get("warnings") or [])
    d["supports_auto"] = list(q.get("supports_auto") or [])
    d["n_runs"] = int(n_runs)
    d["can_delete"] = bool(principal is not None and (principal.is_global_admin or t["created_by"] == principal.user_id))
    return d


def load_template(conn, tid: str, *, for_update: bool = False) -> dict[str, Any]:
    t = opt_repo.get_template(conn, tid, for_update=for_update)
    if t is None:
        raise not_found("TEMPLATE_NOT_FOUND", "템플릿을 찾을 수 없습니다")
    return t


def template_folder(ctx: AppContext, t: dict[str, Any]) -> str:
    return template_dir(ctx.settings, t["id"])


def template_meta(ctx: AppContext, t: dict[str, Any]) -> dict[str, Any]:
    """template.json(frame·법선·자동 3-2-1 …)."""
    p = os.path.join(template_folder(ctx, t), "template.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        raise DomainError("TEMPLATE_FILES_MISSING", "템플릿 파일(template.json)을 읽을 수 없습니다", status=500) from None


def template_arrays(ctx: AppContext, t: dict[str, Any]) -> dict[str, np.ndarray]:
    p = os.path.join(template_folder(ctx, t), "template.npz")
    try:
        with np.load(p, allow_pickle=False) as z:
            return {k: z[k] for k in z.files}
    except (OSError, ValueError):
        raise DomainError("TEMPLATE_FILES_MISSING", "템플릿 파일(template.npz)을 읽을 수 없습니다", status=500) from None


def template_preview(ctx: AppContext, t: dict[str, Any]) -> dict[str, Any]:
    """preview.json(평면도 파생 캐시). 없거나 깨졌으면 template.npz 로 다시 만든다(_templates/<id>/ 안에만 씀)."""
    from ...core.opt_core import keepout

    p = os.path.join(template_folder(ctx, t), "preview.json")
    try:
        with open(p, encoding="utf-8") as fh:
            pv = json.load(fh)
        if "kinds" in (pv.get("auto_keepout") or {}):
            return pv
        # kinds(구멍/가장자리) 없는 구 캐시 → 다시 만든다
    except (OSError, ValueError):
        pass
    o = _cfg(ctx)
    pv = keepout.plan_view(template_arrays(ctx, t), template_meta(ctx, t)["frame"], o["keepout"],
                           int(o["ui"]["max_preview_points"]))
    _write_json(p, pv)
    return pv


def _write_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 검사
def _run_check(ctx: AppContext, up: dict[str, Any], path: str, part_title: str | None) -> dict[str, Any]:
    from ...core.opt_core import EslError
    from ...core.opt_core import mesh_check

    o = _cfg(ctx)
    if path.lower().endswith(".rad"):
        problems, missing = up_svc.template_include_problems(ctx, up, path)
        if problems or missing:
            raise unprocessable("MESH_INVALID", "; ".join(problems + [f"include 누락: {m}" for m in missing]),
                                problems=problems, missing_includes=missing)
    try:
        res = mesh_check.check_file(path, part_title, o, bead=o["bead_defaults"], max_include_depth=_depth(ctx))
    except EslError as exc:
        code = exc.code if exc.code in MESH_ERRORS else "MESH_INVALID"
        raise unprocessable(code, exc.message) from None
    res["upload_id"] = up["id"]
    res["rel"] = os.path.relpath(path, up["dir_path"]).replace(os.sep, "/")
    return res


def check_template(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    require_execute(principal, body.project_id)
    up, path = up_svc.template_source(ctx, principal, body.upload_id, project_id=body.project_id)
    res = _run_check(ctx, up, path, body.part_title)
    up_svc.save_template_check(ctx, up["id"], res, res["rel"])
    return res


# ---------------------------------------------------------------- 등록
def register_template(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    from ...core.opt_core import EslError
    from ...core.opt_core import keepout, mesh_check
    from ...core.opt_core import build_template

    require_execute(principal, body.project_id)
    require_config_ok(ctx)
    up, path = up_svc.template_source(ctx, principal, body.upload_id, project_id=body.project_id)
    sha = sha256_file(path)
    if sha.lower() != body.sha256.lower():
        raise conflict("PLATE_CHANGED", "검사 이후 업로드 파일이 바뀌었습니다 — 다시 검사하세요", sha256=sha)
    prev = up.get("result") or {}
    pc = prev.get("check") or {}
    same = (prev.get("purpose") == up_svc.TEMPLATE_PURPOSE and prev.get("sha256") == sha
            and (body.part_title is None or body.part_title == pc.get("part_title")))
    res = pc if same and pc else None
    if res is None:
        res = _run_check(ctx, up, path, body.part_title)
    if not res.get("ok"):
        raise unprocessable("MESH_INVALID", "템플릿 검사 오류가 있어 등록할 수 없습니다",
                            errors=(res.get("quality") or {}).get("errors") or [])
    o = _cfg(ctx)
    tid = str(uuid.uuid4())
    tdir = template_dir(ctx.settings, tid)
    if os.path.lexists(tdir):
        raise conflict("TEMPLATE_EXISTS", "템플릿 폴더가 이미 있습니다")
    root = up_svc._upload_root(ctx)
    rel_main = os.path.relpath(path, up["dir_path"]).replace(os.sep, "/")
    try:
        inp = os.path.join(tdir, "input")
        os.makedirs(inp)
        for f in up["files"]:
            if f.get("removed"):
                continue
            segs = f["rel"].split("/")
            src = U.target_path(up["dir_path"], segs, upload_root=root)
            dst = os.path.join(inp, *segs)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        main = os.path.join(inp, *rel_main.split("/"))
        if sha256_file(main) != sha:
            raise conflict("PLATE_CHANGED", "복사 중 업로드 파일이 바뀌었습니다 — 다시 검사하세요")
        try:
            mesh, info = mesh_check.load_mesh(main, body.part_title or res.get("part_title"),
                                              max_include_depth=_depth(ctx))
            arrays, tmeta = build_template(mesh, _axis_ref(ctx))
            pv = keepout.plan_view(arrays, tmeta["frame"], o["keepout"], int(o["ui"]["max_preview_points"]))
        except EslError as exc:
            code = exc.code if exc.code in MESH_ERRORS else "MESH_INVALID"
            raise unprocessable(code, exc.message) from None
        fr = tmeta["frame"]
        fmt = info.get("format") or res.get("format")
        tmeta = {**tmeta, "format": fmt, "file_name": os.path.basename(main), "input_rel": f"input/{rel_main}",
                 "part_title": info.get("part_title"), "sha256": sha, "inch": body.inch, "title": body.title,
                 "template_id": tid}
        np.savez_compressed(os.path.join(tdir, "template.npz"), **{k: np.asarray(v) for k, v in arrays.items()})
        _write_json(os.path.join(tdir, "template.json"), tmeta)
        _write_json(os.path.join(tdir, "preview.json"), pv)
        q = dict(res.get("quality") or {})
        q["supports_auto"] = tmeta.get("supports_auto") or res.get("supports_auto") or []
        q["normals"] = tmeta.get("normals")
        with ctx.engine.begin() as conn:
            t = opt_repo.insert_template(
                conn, id=tid, title=body.title, description=body.description or "", inch=body.inch, format=fmt,
                file_name=os.path.basename(main), part_title=info.get("part_title"), sha256=sha,
                n_nodes=int(tmeta["n_nodes"]), n_elems=int(tmeta["n_elems"]), L_xi=float(fr["L_xi"]),
                L_eta=float(fr["L_eta"]), z_range=[float(v) for v in fr["z_range"]],
                pids=list(res.get("pids") or []), quality=_jsonable(q), dir_rel=f"{TEMPLATE_DIR}/{tid}",
                status="ACTIVE", origin_project_id=body.project_id, created_by=principal.user_id,
                created_by_name=principal.display_name)
    except BaseException:
        try:
            _stash(ctx, tdir, tid)
        except Exception:  # noqa: BLE001 - 원래 오류를 낸다
            pass
        raise
    return template_out(t, principal, 0)


def _jsonable(o: Any) -> Any:
    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x)))


# ---------------------------------------------------------------- 조회·삭제
def list_templates(ctx: AppContext, principal: Principal, status: str | None, q: str | None) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        rows = opt_repo.list_templates(conn, status=status, q=(q or "").strip() or None)
        counts = opt_repo.template_run_counts(conn, [t["id"] for t in rows])
    return [template_out(t, principal, counts.get(t["id"], 0)) for t in rows]


def get_template(ctx: AppContext, principal: Principal, tid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        t = load_template(conn, tid)
        n = opt_repo.template_run_counts(conn, [tid]).get(tid, 0)
    return template_out(t, principal, n)


def delete_template(ctx: AppContext, principal: Principal, tid: str) -> dict[str, Any]:
    require_config_ok(ctx)
    with ctx.engine.begin() as conn:
        t = load_template(conn, tid, for_update=True)
        if not (principal.is_global_admin or t["created_by"] == principal.user_id):
            raise forbidden("등록자 또는 전역 관리자만 템플릿을 삭제할 수 있습니다", code="NOT_TEMPLATE_OWNER")
        n = opt_repo.template_run_counts(conn, [tid]).get(tid, 0)
        if n:
            if t["status"] != "ARCHIVED":
                opt_repo.update_template(conn, tid, status="ARCHIVED", archived_by=principal.user_id,
                                         archived_at=func.now())
            return {"deleted": False, "archived": True}
        d = template_folder(ctx, t)
        opt_repo.delete_template(conn, tid)
        _stash(ctx, d, tid)            # 실패하면 예외 → 행 삭제도 롤백
    return {"deleted": True, "archived": False}
