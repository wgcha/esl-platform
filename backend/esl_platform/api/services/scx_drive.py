"""SCX 드라이브에서 고르기 — 백엔드 쪽(계약 esl_scx_relay.md 기능 A, §7·SR-D-5·6·19).

백엔드는 가벼운 릴레이 호출만(health·list): 상태(`/scx/status`), 탐색(`/scx/browse`), 내려받기 요청(`/scx/fetches` = 업로드
세션 OPEN + SCX_FETCH 작업을 한 트랜잭션에). 실제 내려받기는 워커 XFER 작업(esl_worker.scx_fetch). 드라이브 쓰기 없음.
탐색 범위 = 설정 scx_drive.roots(프로젝트 제한) 안, SPDM 마스터 루트·릴레이 읽기 범위 밖 거부(core.scx.paths), 권한 power 이상.
릴레이 다운·비활성 = 503 SCX_UNAVAILABLE{reason_code}.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from sqlalchemy import and_, func, insert, select

from ...core import uploads as U
from ...core.auth import Principal
from ...core.db.tables import uploads
from ...core.errors import DomainError, forbidden, unprocessable
from ...core.repositories import jobs as jobs_repo
from ...core.scx import messages, paths, status
from ...core.scx.settings import scx_cfg
from ..context import AppContext
from . import uploads as up_svc
from .common import require_config_ok, require_execute

_ERR_STATUS = {"SCX_PATH_NOT_FOUND": 404, "SCX_PATH_NOT_ALLOWED": 422, "SCX_LIST_LIMIT": 413}


def _relay_error(exc: BaseException) -> DomainError:
    """어댑터 오류 → API 오류(404·422·413 은 그 코드, 나머지 503 SCX_UNAVAILABLE{reason_code})."""
    f = messages.classify(exc)
    st = _ERR_STATUS.get(f.code)
    if st:
        return DomainError(f.code, f.message, status=st)
    return DomainError("SCX_UNAVAILABLE", f.message, status=503, reason_code=f.code)


def _gateway_errors():
    from ...core.scx.gateway import gateway_error

    return gateway_error()


def _require_member(principal: Principal, project_id: str) -> None:
    if principal.role(project_id) is None:
        raise forbidden("이 프로젝트의 조회 권한이 없습니다")


# ---------------------------------------------------------------- 상태
def get_status(ctx: AppContext, principal: Principal, project_id: str) -> dict[str, Any]:
    """항상 200 — 기능별 enabled·reason_code·reason, 프로젝트에 허용된 루트, 릴레이 요약(비밀·서버 경로 없음)."""
    _require_member(principal, project_id)
    st = status.evaluate(ctx.settings, project_id)
    return status.public(st)


# ---------------------------------------------------------------- 탐색
def _list(gw, rel: str, max_entries: int) -> list[dict[str, Any]]:
    try:
        return gw.list(rel, max_entries)
    except _gateway_errors() as exc:
        raise _relay_error(exc) from None


def browse(ctx: AppContext, principal: Principal, project_id: str, root_key: str, path: str | None, offset: int,
           limit: int | None) -> dict[str, Any]:
    require_execute(principal, project_id)
    s = ctx.settings
    gw, health = status.require_fetch(s, project_id)
    root, rel = paths.resolve(s, project_id, root_key, path, health)
    ents = _list(gw, rel, int(s.scx_drive.list_max_entries))
    globs = list(s.scx_drive.engine_globs)
    out = []
    for e in ents:
        name = str(e.get("name") or "")
        kind = e.get("kind")
        if not name or name.startswith(paths.HIDDEN) or kind not in ("dir", "file") or "/" in name or "\\" in name:
            continue
        size = e.get("size") if kind == "file" and isinstance(e.get("size"), int) else None
        mod = e.get("modified_at")
        out.append({"name": name, "kind": kind, "size": size, "modified_at": mod if isinstance(mod, str) else None,
                    "hint": paths.hint(name, globs) if kind == "file" else None})
    out.sort(key=lambda x: (x["kind"] != "dir", x["name"].casefold()))
    cap = int(s.ui.browse_page_max)
    lim = cap if limit is None else max(1, min(int(limit), cap))
    off = max(0, int(offset))
    page = out[off:off + lim]
    return {"root": root.key, "path": paths.root_sub(rel, root.rel), "display": gw.display(rel), "entries": page,
            "total": len(out), "truncated": off + len(page) < len(out)}


# ---------------------------------------------------------------- 내려받기 요청
def _file_size(gw, rel: str, max_entries: int) -> int:
    """드라이브 파일 크기(부모 폴더 list — 가벼운 호출). 없으면 404 SCX_PATH_NOT_FOUND."""
    parent, _, name = rel.rpartition("/")
    for e in _list(gw, parent, max_entries):
        if str(e.get("name") or "") == name:
            if e.get("kind") != "file":
                break
            return int(e.get("size") or 0)
    raise DomainError("SCX_PATH_NOT_FOUND", f"{messages.text('SCX_PATH_NOT_FOUND')}: {name}", status=404)


RELAY_LIMIT_KEY = "대시보드 SIMDASH_SCX_RELAY_MAX_DOWNLOAD_BYTES"


def download_limit_info(settings, health: dict[str, Any], *, upload: bool = True) -> tuple[int, str]:
    """(다운로드 상한, 그 상한을 정한 설정 이름). 상한 = min(hpc.scx.max_download_bytes, health max_download_bytes,
    [기능 A] upload.max_file_bytes) — v0.12.0 L3: 너무 큰 파일 안내가 실제 원인 설정을 가리키게(같으면 앞쪽 = esl 설정)."""
    lims = [(int(scx_cfg(settings).max_download_bytes), "hpc.scx.max_download_bytes")]
    if upload:
        lims.append((int(settings.upload.max_file_bytes), "upload.max_file_bytes"))
    hm = health.get("max_download_bytes")
    if isinstance(hm, int) and hm > 0:
        lims.append((hm, RELAY_LIMIT_KEY))
    return min(lims, key=lambda x: x[0])


def download_limit(settings, health: dict[str, Any]) -> int:
    """다운로드 상한 = min(hpc.scx.max_download_bytes, health max_download_bytes, upload.max_file_bytes)."""
    return download_limit_info(settings, health)[0]


def too_large_text(limit: int, key: str) -> str:
    """SCX_FILE_TOO_LARGE 사용자 문구 — 상한 값과 원인 설정(관리자 조치 대상)."""
    return messages.text("SCX_FILE_TOO_LARGE", f"{limit} B") + f" — 관리자: {key}"


def create_fetch(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    require_config_ok(ctx)
    root_dir = up_svc._upload_root(ctx)
    require_execute(principal, body.project_id)
    s = ctx.settings
    name_seg = U.safe_name(body.name)                    # 422 UPLOAD_NAME_INVALID
    gw, health = status.require_fetch(s, body.project_id)
    root, rad = paths.resolve(s, body.project_id, body.root, body.rad_rel, health)
    _, h3d = paths.resolve(s, body.project_id, body.root, body.h3d_rel, health)
    if not rad.casefold().endswith(".rad"):
        raise unprocessable("SCX_NOT_RAD", messages.text("SCX_NOT_RAD"))
    if not h3d.casefold().endswith(".h3d"):
        raise unprocessable("SCX_NOT_H3D", messages.text("SCX_NOT_H3D"))
    for seg in (rad.rsplit("/", 1)[-1], h3d.rsplit("/", 1)[-1]):
        U.check_segment(seg, seg)                        # Windows 예약어·메타문자 이름은 받지 않음(§12)
    mx = int(s.scx_drive.list_max_entries)
    rad_size, h3d_size = _file_size(gw, rad, mx), _file_size(gw, h3d, mx)
    limit, lkey = download_limit_info(s, health)
    for nm, sz in ((rad, rad_size), (h3d, h3d_size)):
        if sz > limit:
            raise unprocessable("SCX_FILE_TOO_LARGE", too_large_text(limit, lkey) + f" ({nm.rsplit('/', 1)[-1]} {sz} B)",
                                limit=limit, size=sz, setting=lkey)
    if rad_size + h3d_size > s.upload.max_upload_bytes:
        raise DomainError("UPLOAD_TOO_LARGE", f"업로드 전체 크기가 상한({s.upload.max_upload_bytes} B)을 넘습니다", status=413,
                          limit=s.upload.max_upload_bytes)
    up_svc.cleanup_stale(ctx)
    os.makedirs(root_dir, exist_ok=True)
    up_svc._check_free(ctx, root_dir, rad_size + h3d_size)     # 507 INSUFFICIENT_STORAGE(include 는 워커가 다시 검사)
    user_seg = U.user_segment(principal.username, principal.user_id)
    cfg = s.upload
    core_case = (ctx.config.core or {}).get("case") or {}
    params = {"root": root.key, "root_rel": root.rel, "rad_rel": rad, "h3d_rel": h3d, "rad_size": rad_size, "h3d_size": h3d_size,
              "name": body.name.strip(), "include_max_depth": int(core_case.get("rad_include_max_depth") or 8)}
    with ctx.engine.begin() as conn:
        conn.execute(select(func.pg_advisory_xact_lock(func.hashtext("esl-upload:" + principal.user_id))))
        n_open = conn.execute(select(func.count()).select_from(uploads).where(
            and_(uploads.c.user_id == principal.user_id, uploads.c.state == up_svc.OPEN))).scalar_one()
        if n_open >= cfg.max_concurrent_per_user:
            raise DomainError("UPLOAD_LIMIT", f"진행 중인 업로드 세션이 {n_open}개입니다(사용자당 최대 "
                              f"{cfg.max_concurrent_per_user}개) — 새 Case 화면의 '진행 중인 업로드'에서 이어서 하거나 취소하세요",
                              status=429, limit=cfg.max_concurrent_per_user,
                              open_uploads=up_svc._open_uploads_detail(conn, ctx, principal.user_id))
        up_dir = U.make_upload_dir(root_dir, user_seg, name_seg, U.utc_stamp())
        try:
            uid = str(uuid.uuid4())
            conn.execute(insert(uploads).values(
                id=uid, project_id=body.project_id, user_id=principal.user_id, username=principal.username,
                name=body.name.strip(), dir_path=up_dir, state=up_svc.OPEN, files=[], total_bytes=0))
            job = jobs_repo.insert_job(conn, case_id=None, upload_id=uid, project_id=body.project_id, job_type="SCX_FETCH",
                                       params=params, created_by=principal.user_id,
                                       created_by_name=principal.display_name)
        except BaseException:
            U.move_to_backup(root_dir, user_seg, up_dir)      # 만든 폴더는 지우지 않고 _backup 으로
            raise
    return {"upload_id": uid, "job_id": job["id"]}


def retry_fetch(conn, principal: Principal, job: dict[str, Any]) -> dict[str, Any]:
    """SCX_FETCH 재시도: 같은 세션·같은 params, 실패 step 부터(확인된 파일은 워커가 건너뜀 — SR-D-7). 세션이 OPEN 이어야 함."""
    from sqlalchemy.exc import IntegrityError

    from ...core.errors import conflict
    from .common import job_out

    up = up_svc._row(conn, job["upload_id"], for_update=True)
    if up["state"] != up_svc.OPEN:
        raise conflict("UPLOAD_CLOSED", f"이미 끝난 업로드입니다({up['state']}) — 새로 고르세요", state=up["state"])
    start = jobs_repo.first_failed_step(conn, job["id"])
    try:
        with conn.begin_nested():
            new = jobs_repo.insert_job(conn, case_id=None, upload_id=up["id"], project_id=job["project_id"],
                                       job_type="SCX_FETCH", params=dict(job["params"]), created_by=principal.user_id,
                                       created_by_name=principal.display_name, retry_of_job_id=job["id"],
                                       resume_from_step=start if start > 1 else None)
    except IntegrityError:
        raise conflict("UPLOAD_SCX_BUSY", "이 업로드의 SCX 내려받기가 대기 중이거나 실행 중입니다") from None
    return job_out(conn, new, with_steps=True)


__all__ = ["get_status", "browse", "create_fetch", "retry_fetch", "download_limit", "download_limit_info", "too_large_text"]
