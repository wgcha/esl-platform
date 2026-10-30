"""브라우저·PC 분할 업로드 세션(계약 esl_p3_ux.md §1.1, esl_upload_speed.md).

흐름: POST /uploads(사전 검사·폴더 생성) → PUT /uploads/{id}/files/{index}?offset=(청크) → POST /uploads/{id}/complete
(누락 검사·rad 파싱·include 해석·결과 폴더/h3d 검사, 누락 include 목록) → (누락 시 POST /uploads/{id}/files 로 추가 후
다시 complete). DELETE /uploads/{id} 는 미완료 세션 취소, DELETE /uploads/{id}/files/{index} 는 파일 하나 빼기
(둘 다 받은 파일은 _backup 으로 이동, 삭제 없음). 미완료 세션은 upload.stale_hours 뒤 _backup 으로 이동(STALE).

프로토콜 2(새 세션, 파일 항목에 proto=2): 청크 k = [k·C, min(size,(k+1)·C)). 정렬된 청크 하나를 정확히 덮어쓰는 PUT 을
순서 무관·동시(upload.parallel)로 받고, 본문은 스트리밍으로 `.part`(사전 할당) 의 k·C 위치에 직접 쓴다. 받은 청크는
files[i].got([[a,b),…] 청크 번호 범위)로 기록하고 행 잠금은 표시할 때만 짧게 잡는다. 파일 전체 sha256 은 "연속으로 받은
앞부분"을 따라가는 해시 추적기가 계산한다. 프로토콜 1(업그레이드 전 OPEN 세션: proto 키 없음)은 기존 append 경로를 유지한다.
프로세스 메모리 상태(진행 중 청크·해시)는 백엔드 1 프로세스 전제(기존 _HASHES 와 같음).
v0.7.0(esl_opt_run.md §7.2): S2 템플릿 업로드(`rad/` 아래 .fem 또는 .rad+include)는 complete 대신 POST /opt/templates/check 가
`template_source`(읽기만)·`save_template_check`(result.purpose = template, COMPLETED)로 연결한다.
v0.9.0(esl_bead_doe.md §10): 비드 DOE STEP(`rad/<파일>.step|.stp`, purpose 없이 업로드)·② B 메시는 POST /doe/check-inputs 가
`doe_source`·`step_check`(머리·크기)·`save_doe_check`(result.purpose = doe_step|doe_mesh, COMPLETED)로 연결한다.
v0.11.0(esl_scx_relay.md §9.1·SR-D-6): SCX 드라이브에서 고르기 — POST /scx/fetches 가 OPEN 세션(files [])과 SCX_FETCH 작업을 같이
만들고, 워커가 files[] 에 `source: "scx"`·`drive_rel` 항목을 더한 뒤 같은 `inspect_upload` 로 result(+ `scx`)를 저장한다.
scx 항목에는 브라우저 PUT 409 UPLOAD_SCX_MANAGED, 비종료 SCX_FETCH 가 있는 세션은 파일 추가·빼기·complete·취소 409
UPLOAD_SCX_BUSY 이고 stale 정리에서 건너뛴다. 누락 include 는 작업이 끝난 뒤 기존 POST /uploads/{id}/files 로 같은 세션에.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, func, insert, or_, select, update

from esl_worker import core_adapter

from ...core import uploads as U
from ...core.auth import Principal
from ...core.config import is_within
from ...core.db.tables import cases, uploads
from ...core.errors import DomainError, conflict, not_found, unprocessable
from ...core.inputs import sha256_file
from ..context import AppContext
from . import system
from .common import require_config_ok, require_execute

OPEN, COMPLETED, CANCELED, STALE = "OPEN", "COMPLETED", "CANCELED", "STALE"
log = logging.getLogger("esl.uploads")
META_MAX_BYTES = 16 * 1024


def _upload_root(ctx: AppContext) -> str:
    root = ctx.settings.storage.upload_root
    if not root:
        raise DomainError("UPLOAD_DISABLED", "업로드 저장 위치(storage.upload_root)가 설정되지 않았습니다", status=503)
    return root


def _row(conn, upload_id: str, *, for_update: bool = False) -> dict[str, Any]:
    q = select(uploads).where(uploads.c.id == upload_id)
    if for_update:
        q = q.with_for_update()
    r = conn.execute(q).mappings().first()
    if r is None:
        raise not_found("UPLOAD_NOT_FOUND", "업로드를 찾을 수 없습니다")
    return dict(r)


def _owned(conn, principal: Principal, upload_id: str, *, for_update: bool = False) -> dict[str, Any]:
    up = _row(conn, upload_id, for_update=for_update)
    if up["user_id"] != principal.user_id and not principal.is_global_admin:
        raise not_found("UPLOAD_NOT_FOUND", "업로드를 찾을 수 없습니다")
    if principal.token_project_id is not None and up["project_id"] != principal.token_project_id:
        raise not_found("UPLOAD_NOT_FOUND", "업로드를 찾을 수 없습니다")   # PC 토큰: 묶인 프로젝트의 업로드만
    return up


def _require_open(up: dict[str, Any]) -> None:
    if up["state"] != OPEN:
        raise conflict("UPLOAD_CLOSED", f"이미 끝난 업로드입니다({up['state']})", state=up["state"])


def _scx_job(conn, upload_id: str) -> dict[str, Any] | None:
    from ...core.repositories import jobs as jobs_repo

    return jobs_repo.active_upload_job(conn, upload_id)


def _require_not_fetching(conn, upload_id: str) -> None:
    """v0.11.0: 비종료 SCX_FETCH 가 있는 세션은 파일 추가·빼기·complete·취소 불가(워커가 쓰는 중)."""
    job = _scx_job(conn, upload_id)
    if job is not None:
        raise conflict("UPLOAD_SCX_BUSY", "SCX 에서 내려받는 중입니다 — 끝난 뒤(또는 작업 취소 뒤) 다시 하세요", job_id=job["id"])


def _reject_scx_file(f: dict[str, Any]) -> None:
    if f.get("source") == "scx":
        raise conflict("UPLOAD_SCX_MANAGED", f"SCX 에서 내려받는 파일은 브라우저로 올릴 수 없습니다: {f['rel']}", rel=f["rel"])


def _segs(f: dict[str, Any]) -> list[str]:
    return f["rel"].split("/")


# ---------------------------------------------------------------- 청크 범위 계산(청크 번호 [a,b) 목록)
def _is_p2(f: dict[str, Any]) -> bool:
    return f.get("proto") == 2


def _n_chunks(size: int, c: int) -> int:
    return (int(size) + c - 1) // c if c > 0 else 0


def _chunk_len(size: int, c: int, k: int) -> int:
    return min(int(size), (k + 1) * c) - k * c


def _r_has(ranges: list, k: int) -> bool:
    return any(a <= k < b for a, b in ranges)


def _r_add(ranges: list, k: int) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in sorted([list(r) for r in ranges] + [[k, k + 1]]):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _r_missing(ranges: list, n: int) -> list[list[int]]:
    out: list[list[int]] = []
    cur = 0
    for a, b in sorted(list(r) for r in ranges):
        if a > cur:
            out.append([cur, a])
        cur = max(cur, b)
    if cur < n:
        out.append([cur, n])
    return out


def _contig_bytes(ranges: list, size: int, c: int) -> int:
    """앞에서부터 연속으로 받은 바이트."""
    rs = sorted(list(r) for r in ranges)
    if rs and rs[0][0] == 0:
        return min(int(size), rs[0][1] * c)
    return 0


def _got_bytes(ranges: list, size: int, c: int) -> int:
    return sum(min(int(size), b * c) - a * c for a, b in ranges)


def _received(up: dict[str, Any], f: dict[str, Any]) -> int:
    p = os.path.join(up["dir_path"], *_segs(f))
    if f.get("done"):
        return int(f["size"])
    try:
        return os.path.getsize(p + U.PART_SUFFIX)
    except OSError:
        return 0


def session_proto(up: dict[str, Any]) -> int:
    fs = up["files"]
    return 2 if (not fs or _is_p2(fs[0])) else 1


def session_chunk(up: dict[str, Any], cfg) -> int:
    fs = up["files"]
    if fs and _is_p2(fs[0]):
        return int(fs[0]["chunk"])
    return cfg.chunk_bytes


def _session_client(up: dict[str, Any]) -> dict[str, str] | None:
    """세션을 만든 클라이언트 {name, version} — DB migration 없이 files[] 항목의 client 키에 둔다(만들 때 모든 항목, 추가 파일은 이어받음)."""
    for f in up["files"]:
        c = f.get("client")
        if isinstance(c, dict) and c.get("name"):
            return {"name": str(c["name"]), "version": str(c.get("version") or "")}
    return None


def upload_out(up: dict[str, Any], cfg) -> dict[str, Any]:
    """cfg = UploadCfg. 파일별 received(연속 앞부분)·received_total·chunks·n_chunks·removed·meta."""
    files = []
    sc = session_chunk(up, cfg)
    for i, f in enumerate(up["files"]):
        size = int(f["size"])
        removed = bool(f.get("removed"))
        done = bool(f.get("done"))
        if _is_p2(f):
            c = int(f["chunk"])
            n = _n_chunks(size, c)
            if removed:
                rec = tot = 0
                ch: list = []
            elif done:
                rec = tot = size
                ch = [[0, n]] if n else []
            elif up["state"] == OPEN:
                ch = [list(r) for r in (f.get("got") or [])]
                rec, tot = _contig_bytes(ch, size, c), _got_bytes(ch, size, c)
            else:
                rec = tot = 0
                ch = []
        else:
            n = _n_chunks(size, sc)
            rec = _received(up, f) if (up["state"] == OPEN or done) and not removed else 0
            tot = rec
            ch = [[0, n]] if (done and n) else []
        files.append({"index": i, "rel": f["rel"], "source": f.get("source") or "browser", "drive_rel": f.get("drive_rel"),
                      "size": size, "received": rec, "received_total": tot, "chunks": ch,
                      "n_chunks": n, "removed": removed, "meta": f.get("meta"), "done": done,
                      "sha256": f.get("sha256"), "sha256_expected": f.get("sha256_expected")})
    live = [f for f in files if not f["removed"]]
    res = up.get("result") or {}
    return {"upload_id": up["id"], "project_id": up["project_id"], "name": up["name"], "state": up["state"],
            "dir_path": up["dir_path"], "protocol": session_proto(up), "chunk_size": sc,
            "max_parallel": cfg.parallel, "total_bytes": sum(f["size"] for f in live),
            "received_bytes": sum(f["received_total"] for f in live),
            "problems_count": len(res.get("problems") or []) + len(res.get("missing_includes") or []),
            "client": _session_client(up),
            "files": files, "result": up.get("result"),
            "backup_path": up.get("backup_path"), "created_at": up["created_at"], "updated_at": up["updated_at"],
            "completed_at": up.get("completed_at")}


def _check_meta(f, rel: str) -> dict[str, Any] | None:
    if f.meta is None:
        return None
    if not rel.lower().endswith(".h3d"):
        raise unprocessable("UPLOAD_META_INVALID", f"meta 는 .h3d 파일에만 쓸 수 있습니다: {rel}", rel=rel)
    meta = f.meta.model_dump(exclude_none=True)
    if len(json.dumps(meta, ensure_ascii=False).encode("utf-8")) > META_MAX_BYTES:
        raise unprocessable("UPLOAD_META_INVALID", f"meta 가 너무 큽니다(최대 {META_MAX_BYTES} B): {rel}", rel=rel)
    if meta.get("slim_bytes") is not None and meta["slim_bytes"] != f.size:
        raise unprocessable("UPLOAD_META_INVALID", f"meta.slim_bytes({meta['slim_bytes']}) 가 파일 크기({f.size})와 "
                            f"다릅니다: {rel}", rel=rel)
    if meta["kind"] == "h3d_slim" and meta.get("part_id") is None:
        raise unprocessable("UPLOAD_META_INVALID", f"h3d_slim meta 에는 part_id 가 필요합니다: {rel}", rel=rel)
    return meta


def _norm_files(ctx: AppContext, files: list[Any], existing: list[dict[str, Any]],
                session: tuple[int, int] | None = None) -> list[dict[str, Any]]:
    """session = (proto, chunk) — 기존 세션에 추가할 때 그 세션 것을 이어받는다(없으면 새 세션: 프로토콜 2·설정 청크)."""
    cfg = ctx.settings.upload
    proto, chunk = session or (2, cfg.chunk_bytes)
    live = [f for f in existing if not f.get("removed")]
    seen = {f["rel"].casefold() for f in live}
    out = []
    for f in files:
        U.check_rel(f.rel, cfg.allowed_ext)
        if f.size > cfg.max_file_bytes:
            raise DomainError("UPLOAD_TOO_LARGE", f"파일이 너무 큽니다({f.rel}: {f.size} B > {cfg.max_file_bytes} B)",
                              status=413, rel=f.rel, limit=cfg.max_file_bytes)
        key = f.rel.casefold()
        if key in seen:
            raise conflict("UPLOAD_FILE_DUPLICATE", f"같은 경로의 파일이 이미 있습니다(대소문자 무시): {f.rel}", rel=f.rel)
        seen.add(key)
        sha = f.sha256.lower() if f.sha256 else None
        ent = {"rel": f.rel, "size": int(f.size), "sha256_expected": sha, "sha256": None, "done": False}
        if proto == 2:
            ent.update(proto=2, chunk=chunk, got=[], removed=False)
        meta = _check_meta(f, f.rel)
        if meta is not None:
            ent["meta"] = meta
        out.append(ent)
    if len(live) + len(out) > cfg.max_files:
        raise DomainError("UPLOAD_TOO_MANY_FILES", f"파일이 너무 많습니다(최대 {cfg.max_files}개)", status=413)
    total = sum(f["size"] for f in live) + sum(f["size"] for f in out)
    if total > cfg.max_upload_bytes:
        raise DomainError("UPLOAD_TOO_LARGE", f"업로드 전체 크기가 상한({cfg.max_upload_bytes} B)을 넘습니다", status=413,
                          limit=cfg.max_upload_bytes, total=total)
    return out


def disk_free(root: str) -> int | None:
    try:
        return shutil.disk_usage(root).free
    except OSError:
        return None


def _check_free(ctx: AppContext, root: str, need: int) -> None:
    """필요량 + upload.min_free_gb 보다 여유가 적으면 507 INSUFFICIENT_STORAGE."""
    free = disk_free(root)
    if free is None:
        return
    reserve = int(ctx.settings.upload.min_free_gb * 1024 ** 3)
    if free < need + reserve:
        raise DomainError("INSUFFICIENT_STORAGE", f"업로드 위치의 여유 공간이 부족합니다(필요 {need} B + 여유 "
                          f"{ctx.settings.upload.min_free_gb} GB, 현재 여유 {free} B)", status=507, need=need,
                          free=free, reserve=reserve)


# 파일 전체 sha256. 프로토콜 1: 받으며 이어서 계산(업로드 행 잠금 아래에서만). 프로토콜 2: 해시 추적기 — "연속으로 받은 앞부분"
# 까지 디스크에서 읽어 갱신(_advance_hash, 파일별 Lock). 프로세스 재시작 등으로 상태가 없거나 어긋나면 처음부터 다시 읽어 복원.
_HASHES: dict[tuple[str, int], tuple[Any, int]] = {}
_HASH_LOCK = threading.Lock()
_FLOCKS: dict[tuple[str, int], threading.Lock] = {}
# 진행 중 청크 {upload_id: {(index, k)}}, 빼는 중인 파일 {(upload_id, index)} — 프로세스 메모리(백엔드 1 프로세스 전제)
_GUARD = threading.Lock()
_INFLIGHT: dict[str, set[tuple[int, int]]] = {}
_REMOVING: set[tuple[str, int]] = set()


def reset_state() -> None:
    """프로세스 메모리 상태 비우기(시험: 재시작 흉내)."""
    with _HASH_LOCK:
        _HASHES.clear()
    with _GUARD:
        _INFLIGHT.clear()
        _REMOVING.clear()


def _flock(key: tuple[str, int]) -> threading.Lock:
    with _HASH_LOCK:
        return _FLOCKS.setdefault(key, threading.Lock())


def _hash_state(key: tuple[str, int], part: str, received: int):
    with _HASH_LOCK:
        st = _HASHES.get(key)
    if st is not None and st[1] == received:
        return st[0]
    h = hashlib.sha256()
    if received:
        with open(part, "rb") as fh:
            left = received
            while left:
                b = fh.read(min(left, 1 << 20))
                if not b:
                    break
                h.update(b)
                left -= len(b)
    return h


def _hash_put(key: tuple[str, int], h, received: int | None) -> None:
    with _HASH_LOCK:
        if received is None:
            _HASHES.pop(key, None)
        else:
            _HASHES[key] = (h, received)


def _advance_hash_locked(key: tuple[str, int], part: str, target: int) -> int:
    """파일 Lock 을 쥔 채 해시를 target 바이트까지 따라가게 한다. 반환 = 실제 도달 바이트."""
    with _HASH_LOCK:
        st = _HASHES.get(key)
    if st is None or st[1] > target:
        h, pos = hashlib.sha256(), 0
    else:
        h, pos = st
    if pos < target:
        fd = os.open(part, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            os.lseek(fd, pos, os.SEEK_SET)
            while pos < target:
                b = os.read(fd, min(1 << 20, target - pos))
                if not b:
                    break
                h.update(b)
                pos += len(b)
        finally:
            os.close(fd)
    _hash_put(key, h, pos)
    return pos


def _advance_hash(key: tuple[str, int], part: str, target: int, *, block: bool) -> bool:
    lk = _flock(key)
    if not lk.acquire(blocking=block):
        return False
    try:
        _advance_hash_locked(key, part, target)
    finally:
        lk.release()
    return True


def _prepare_files(root: str, up_dir: str, new: list[dict[str, Any]]) -> None:
    """빈 파일(size 0)은 바로 만들고 검증, 나머지는 대상 경로가 비어 있는지(덮어쓰기 없음)·안전한지 확인."""
    for f in new:
        p = U.target_path(up_dir, _segs(f), create_parents=True, upload_root=root)
        if os.path.lexists(p):
            raise conflict("UPLOAD_FILE_EXISTS", f"이미 있는 파일입니다(덮어쓰지 않음): {f['rel']}", rel=f["rel"])
        if f["size"] == 0:
            U.append_chunk(p + U.PART_SUFFIX, b"", up_dir)
            sha = sha256_file(p + U.PART_SUFFIX)
            if f["sha256_expected"] and f["sha256_expected"] != sha:
                raise unprocessable("SHA256_MISMATCH", f"sha256 이 다릅니다: {f['rel']}", rel=f["rel"])
            os.replace(p + U.PART_SUFFIX, p)
            f.update(done=True, sha256=sha)


# ---------------------------------------------------------------- 세션
def _open_uploads_detail(conn, ctx: AppContext, user_id: str) -> list[dict[str, Any]]:
    rows = [dict(r) for r in conn.execute(select(uploads).where(and_(uploads.c.user_id == user_id,
            uploads.c.state == OPEN)).order_by(uploads.c.created_at.desc())).mappings()]
    out = []
    for r in rows:
        o = upload_out(r, ctx.settings.upload)
        out.append({"id": o["upload_id"], "name": o["name"], "created_at": o["created_at"].isoformat(),
                    "received_bytes": o["received_bytes"], "total_bytes": o["total_bytes"],
                    "problems_count": o["problems_count"]})
    return out


def create_upload(ctx: AppContext, principal: Principal, body) -> dict[str, Any]:
    require_config_ok(ctx)
    root = _upload_root(ctx)
    require_execute(principal, body.project_id)
    cleanup_stale(ctx)
    name_seg = U.safe_name(body.name)
    user_seg = U.user_segment(principal.username, principal.user_id)
    files = _norm_files(ctx, body.files, [])
    os.makedirs(root, exist_ok=True)
    _check_free(ctx, root, sum(f["size"] for f in files))
    cfg = ctx.settings.upload
    if getattr(body, "client", None) is not None:
        log.info("upload client %s %s (user %s)", body.client.name, body.client.version, principal.username)
        for f in files:
            f["client"] = {"name": body.client.name, "version": body.client.version}
    with ctx.engine.begin() as conn:
        # 사용자당 동시(OPEN) 업로드 수 — 사용자 행 잠금 대신 같은 트랜잭션에서 세고 바로 넣는다(advisory lock 으로 직렬화)
        conn.execute(select(func.pg_advisory_xact_lock(func.hashtext("esl-upload:" + principal.user_id))))
        n_open = conn.execute(select(func.count()).select_from(uploads).where(
            and_(uploads.c.user_id == principal.user_id, uploads.c.state == OPEN))).scalar_one()
        if n_open >= cfg.max_concurrent_per_user:
            raise DomainError("UPLOAD_LIMIT", f"진행 중인 업로드 세션이 {n_open}개입니다(사용자당 최대 "
                              f"{cfg.max_concurrent_per_user}개, 계산 대기열과 별개) — 새 Case 화면의 '진행 중인 업로드'에서 "
                              "이어서 하거나 취소하세요", status=429, limit=cfg.max_concurrent_per_user,
                              open_uploads=_open_uploads_detail(conn, ctx, principal.user_id))
        up_dir = U.make_upload_dir(root, user_seg, name_seg, U.utc_stamp())
        try:
            _prepare_files(root, up_dir, files)
            uid = str(uuid.uuid4())
            conn.execute(insert(uploads).values(
                id=uid, project_id=body.project_id, user_id=principal.user_id, username=principal.username,
                name=body.name.strip(), dir_path=up_dir, state=OPEN, files=files,
                total_bytes=sum(f["size"] for f in files)))
        except BaseException:
            U.move_to_backup(root, user_seg, up_dir)      # 만든 폴더는 지우지 않고 _backup 으로
            raise
        up = _row(conn, uid)
    return upload_out(up, cfg)


def add_files(ctx: AppContext, principal: Principal, upload_id: str, body) -> dict[str, Any]:
    require_config_ok(ctx)
    _upload_root(ctx)
    cfg = ctx.settings.upload
    with ctx.engine.begin() as conn:
        up = _owned(conn, principal, upload_id, for_update=True)
        require_execute(principal, up["project_id"])
        _require_open(up)
        _require_not_fetching(conn, upload_id)
        session = (session_proto(up), session_chunk(up, cfg)) if up["files"] else None
        new = _norm_files(ctx, body.files, up["files"], session)
        client = _session_client(up)
        if client is not None:
            for f in new:
                f["client"] = client
        _check_free(ctx, ctx.settings.storage.upload_root, sum(f["size"] for f in new))
        _prepare_files(_upload_root(ctx), up["dir_path"], new)
        files = list(up["files"]) + new
        conn.execute(update(uploads).where(uploads.c.id == upload_id).values(
            files=files, total_bytes=sum(f["size"] for f in files if not f.get("removed")),
            updated_at=func.now(), result=None))
        up = _row(conn, upload_id)
    return upload_out(up, cfg)


def get_upload(ctx: AppContext, principal: Principal, upload_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        up = _owned(conn, principal, upload_id)
    if up["state"] == OPEN and _finalize_ready(ctx, up):
        try:
            _finalize_ready_files(ctx, up)
        except DomainError as exc:       # GET 은 마무리 실패를 던지지 않는다(complete/PUT 이 알림)
            log.warning("upload %s finalize: %s", upload_id, exc.code)
        with ctx.engine.connect() as conn:
            up = _owned(conn, principal, upload_id)
    return upload_out(up, ctx.settings.upload)


def list_uploads(ctx: AppContext, principal: Principal, state: str | None) -> list[dict[str, Any]]:
    q = select(uploads).where(uploads.c.user_id == principal.user_id).order_by(uploads.c.created_at.desc()).limit(50)
    if principal.token_project_id is not None:
        q = q.where(uploads.c.project_id == principal.token_project_id)
    if state:
        q = q.where(uploads.c.state == state)
    with ctx.engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(q).mappings()]
    return [upload_out(r, ctx.settings.upload) for r in rows]


# ---------------------------------------------------------------- PUT: 프로토콜 2
@dataclass
class ChunkPlan:
    mode: int                                   # 1 = 구 세션(append 경로), 2 = 프로토콜 2
    upload_id: str = ""
    index: int = 0
    k: int = 0
    offset: int = 0
    size: int = 0                               # 파일 크기
    chunk: int = 0                              # C
    exp_len: int = 0
    rel: str = ""
    dir_path: str = ""
    duplicate: bool = False
    registered: bool = False
    got: list = field(default_factory=list)
    out: dict[str, Any] = field(default_factory=dict)   # 중복 응답용


def _plan(ctx: AppContext, principal: Principal, upload_id: str, index: int, offset: int,
          content_length: int | None) -> ChunkPlan:
    """본문 읽기 전 사전 검사(계약 §5.2-1) — DB 읽기만, 잠금 없음."""
    require_config_ok(ctx)
    _upload_root(ctx)
    with ctx.engine.connect() as conn:
        up = _owned(conn, principal, upload_id)
    require_execute(principal, up["project_id"])
    _require_open(up)
    if index < 0 or index >= len(up["files"]):
        raise not_found("UPLOAD_FILE_NOT_FOUND", "업로드 파일 번호가 없습니다")
    f = up["files"][index]
    if f.get("removed"):
        raise conflict("UPLOAD_FILE_REMOVED", f"목록에서 뺀 파일입니다: {f['rel']}", rel=f["rel"])
    _reject_scx_file(f)
    if not _is_p2(f):
        return ChunkPlan(mode=1, upload_id=upload_id, index=index, offset=offset)
    size, c = int(f["size"]), int(f["chunk"])
    if f.get("done"):
        raise conflict("UPLOAD_FILE_DONE", f"이미 다 받은 파일입니다: {f['rel']}", received=size)
    got = [list(r) for r in (f.get("got") or [])]
    n = _n_chunks(size, c)
    if offset % c != 0 or offset // c >= n:
        raise conflict("UPLOAD_OFFSET_MISMATCH", f"offset {offset} 은 청크 경계(chunk_size {c})가 아니거나 범위 밖입니다",
                       received=_contig_bytes(got, size, c), chunk_size=c)
    k = offset // c
    exp = _chunk_len(size, c, k)
    if content_length is None:
        raise DomainError("LENGTH_REQUIRED", "Content-Length 헤더가 필요합니다", status=411)
    if content_length > c:
        raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({c} B)보다 큽니다", status=413, limit=c)
    if content_length != exp:
        raise unprocessable("CHUNK_LENGTH_MISMATCH", f"청크 {k} 의 길이는 {exp} B 여야 합니다(선언 {content_length} B)",
                            expected=exp, chunk=k)
    pl = ChunkPlan(mode=2, upload_id=upload_id, index=index, k=k, offset=offset, size=size, chunk=c, exp_len=exp,
                   rel=f["rel"], dir_path=up["dir_path"], got=got)
    if _r_has(got, k):
        pl.duplicate = True
        pl.out = _chunk_out(index, got, size, c, k, True, False, None)
    return pl


def _chunk_out(index: int, got: list, size: int, c: int, k: int, dup: bool, done: bool, sha: str | None) -> dict[str, Any]:
    return {"index": index, "received": size if done else _contig_bytes(got, size, c),
            "received_total": size if done else _got_bytes(got, size, c), "chunk": k, "duplicate": dup,
            "done": done, "sha256": sha}


def acquire_chunk(ctx: AppContext, principal: Principal, upload_id: str, index: int, offset: int,
                  content_length: int | None) -> ChunkPlan:
    """사전 검사 + (새 청크면) 진행 중 등록. 같은 청크가 쓰는 중이면 409 CHUNK_IN_FLIGHT, 업로드당 동시 수 초과 429.
    등록 뒤 한 번 더 검사해 그 사이 파일 빼기·완료·중복을 잡는다. 등록했으면 release_chunk 로 해제해야 한다."""
    pl = _plan(ctx, principal, upload_id, index, offset, content_length)
    if pl.mode == 1 or pl.duplicate:
        return pl
    parallel = ctx.settings.upload.parallel
    with _GUARD:
        if (upload_id, index) in _REMOVING:
            raise conflict("UPLOAD_FILE_BUSY", "이 파일을 빼는 중입니다", rel=pl.rel)
        cur = _INFLIGHT.setdefault(upload_id, set())
        if (index, pl.k) in cur:
            raise conflict("CHUNK_IN_FLIGHT", f"청크 {pl.k} 가 이미 전송 중입니다 — 잠시 뒤 상태를 확인하세요", chunk=pl.k)
        if len(cur) >= parallel:
            raise DomainError("UPLOAD_PARALLEL_LIMIT", f"이 업로드의 동시 전송이 한도({parallel})를 넘었습니다", status=429,
                              headers={"Retry-After": "1"}, limit=parallel)
        cur.add((index, pl.k))
    pl.registered = True
    try:
        again = _plan(ctx, principal, upload_id, index, offset, content_length)
    except BaseException:
        release_chunk(pl)
        raise
    if again.duplicate:
        release_chunk(pl)
        return again
    pl.got = again.got
    return pl


def release_chunk(pl: ChunkPlan) -> None:
    if not pl.registered:
        return
    pl.registered = False
    with _GUARD:
        cur = _INFLIGHT.get(pl.upload_id)
        if cur is not None:
            cur.discard((pl.index, pl.k))
            if not cur:
                _INFLIGHT.pop(pl.upload_id, None)


class ChunkSink:
    """한 청크의 스트리밍 위치 지정 쓰기. 요청마다 새 fd(Windows lseek+write 가 fd 간 위치를 공유하지 않음)."""

    def __init__(self, ctx: AppContext, pl: ChunkPlan) -> None:
        self.pl = pl
        self.total = 0
        self.h = hashlib.sha256()
        self.fd: int | None = None
        cfg = ctx.settings.upload
        self.buf_size = cfg.write_buffer_bytes
        p = U.target_path(pl.dir_path, pl.rel.split("/"), create_parents=True, upload_root=_upload_root(ctx))
        if os.path.lexists(p):
            raise conflict("UPLOAD_FILE_EXISTS", f"이미 있는 파일입니다(덮어쓰지 않음): {pl.rel}", rel=pl.rel)
        self.part = p + U.PART_SUFFIX
        try:
            self.fd = U.open_part_for_write(self.part, pl.size, pl.dir_path, preallocate=cfg.preallocate)
        except OSError as exc:
            raise _disk_error(exc, pl.size) from None

    def write(self, data: bytes) -> None:
        try:
            U.write_chunk_at(self.fd, self.pl.offset + self.total, data)
        except OSError as exc:
            raise _disk_error(exc, len(data)) from None
        self.h.update(data)
        self.total += len(data)

    def close(self) -> None:
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)


def _disk_error(exc: OSError, need: int) -> Exception:
    if U.is_enospc(exc):
        return DomainError("INSUFFICIENT_STORAGE", "업로드 위치의 디스크 공간이 부족합니다", status=507, need=need)
    return exc


def open_sink(ctx: AppContext, pl: ChunkPlan) -> ChunkSink:
    return ChunkSink(ctx, pl)


def commit_chunk(ctx: AppContext, principal: Principal, pl: ChunkPlan, sink: ChunkSink,
                 chunk_sha256: str | None) -> dict[str, Any]:
    """본문을 다 쓴 뒤: 길이·청크 sha256 확인 → 짧은 트랜잭션으로 got 표시 → 해시 추적기 → 마무리."""
    sink.close()
    if sink.total != pl.exp_len:
        raise unprocessable("CHUNK_LENGTH_MISMATCH", f"받은 본문 {sink.total} B 가 기대 길이 {pl.exp_len} B 와 다릅니다 "
                            "(표시하지 않음 — 같은 청크를 다시 보내세요)", expected=pl.exp_len, chunk=pl.k)
    if chunk_sha256 is not None and sink.h.hexdigest() != chunk_sha256.lower():
        raise unprocessable("CHUNK_SHA256_MISMATCH", "청크 sha256 이 다릅니다(표시하지 않음) — 같은 청크를 다시 보내세요",
                            chunk=pl.k)
    with ctx.engine.begin() as conn:
        up = _owned(conn, principal, pl.upload_id, for_update=True)
        _require_open(up)
        files = [dict(f) for f in up["files"]]
        f = files[pl.index]
        if f.get("removed"):
            raise conflict("UPLOAD_FILE_REMOVED", f"목록에서 뺀 파일입니다: {f['rel']}", rel=f["rel"])
        if f.get("done"):
            raise conflict("UPLOAD_FILE_DONE", f"이미 다 받은 파일입니다: {f['rel']}", received=int(f["size"]))
        got = _r_add(f.get("got") or [], pl.k)
        f["got"] = got
        conn.execute(update(uploads).where(uploads.c.id == pl.upload_id).values(files=files, updated_at=func.now()))
    key = (pl.upload_id, pl.index)
    part = os.path.join(pl.dir_path, *pl.rel.split("/")) + U.PART_SUFFIX
    _advance_hash(key, part, _contig_bytes(got, pl.size, pl.chunk), block=False)     # 비차단: 다른 요청이 따라가는 중이면 건너뜀
    done, sha = False, None
    if not _r_missing(got, _n_chunks(pl.size, pl.chunk)):
        done, sha = _finalize_file(ctx, pl.upload_id, pl.index)
    return _chunk_out(pl.index, got, pl.size, pl.chunk, pl.k, False, done, sha)


# ---------------------------------------------------------------- 파일 마무리(멱등)
def _finalize_file(ctx: AppContext, upload_id: str, index: int) -> tuple[bool, str | None]:
    """모든 청크가 모인 프로토콜 2 파일을 마무리: 해시 끝까지 → fsync → 크기·sha256_expected 확인 → rename → done 표시.
    이미 done 이면 (True, sha). 아직 덜 모였으면 (False, None)."""
    root = _upload_root(ctx)
    key = (upload_id, index)
    with _flock(key):
        with ctx.engine.connect() as conn:
            up = _row(conn, upload_id)
        if up["state"] != OPEN:
            return False, None
        f = up["files"][index]
        if f.get("removed"):
            return False, None
        if f.get("done"):
            return True, f.get("sha256")
        size, c = int(f["size"]), int(f["chunk"])
        if _r_missing(f.get("got") or [], _n_chunks(size, c)):
            return False, None
        p = U.target_path(up["dir_path"], _segs(f), create_parents=True, upload_root=root)
        part = p + U.PART_SUFFIX
        user_seg = U.user_segment(up["username"], up["user_id"])
        try:
            reached = _advance_hash_locked(key, part, size)
            fd = os.open(part, os.O_RDWR | getattr(os, "O_BINARY", 0))
            try:
                os.fsync(fd)
                disk = os.fstat(fd).st_size
            finally:
                os.close(fd)
        except FileNotFoundError:
            reached, disk = -1, -1
        if reached != size or disk != size:
            _reset_file(ctx, upload_id, index, key)
            raise unprocessable("UPLOAD_SIZE_MISMATCH", f"디스크의 파일 크기({disk} B)가 선언 크기({size} B)와 다릅니다 — "
                                f"이 파일을 처음부터 다시 올리세요: {f['rel']}", rel=f["rel"], received=0)
        sha = _HASHES[key][0].hexdigest()
        if f.get("sha256_expected") and sha != f["sha256_expected"]:
            moved = U.move_to_backup(root, user_seg, part,
                                     f"{os.path.basename(up['dir_path'])}__{'_'.join(_segs(f))}.mismatch")
            _reset_file(ctx, upload_id, index, key)
            raise unprocessable("SHA256_MISMATCH", f"sha256 이 다릅니다 — 처음부터 다시 올리세요: {f['rel']}",
                                rel=f["rel"], expected=f["sha256_expected"], actual=sha, received=0, backup_path=moved)
        if os.path.lexists(p):
            raise conflict("UPLOAD_FILE_EXISTS", f"이미 있는 파일입니다(덮어쓰지 않음): {f['rel']}", rel=f["rel"])
        os.rename(part, p)
        with ctx.engine.begin() as conn:
            up = _row(conn, upload_id, for_update=True)
            files = [dict(x) for x in up["files"]]
            files[index].update(done=True, sha256=sha)
            conn.execute(update(uploads).where(uploads.c.id == upload_id).values(files=files, updated_at=func.now()))
        _hash_put(key, None, None)
        return True, sha


def _reset_file(ctx: AppContext, upload_id: str, index: int, key: tuple[str, int]) -> None:
    """받은 청크 표시를 비우고 해시 상태를 버린다(처음부터 다시)."""
    _hash_put(key, None, None)
    with ctx.engine.begin() as conn:
        up = _row(conn, upload_id, for_update=True)
        files = [dict(x) for x in up["files"]]
        files[index].update(got=[], done=False, sha256=None)
        conn.execute(update(uploads).where(uploads.c.id == upload_id).values(files=files, updated_at=func.now()))


def _finalize_ready(ctx: AppContext, up: dict[str, Any]) -> list[int]:
    """모든 청크가 모였는데 done 이 아닌 프로토콜 2 파일 번호(예: 마무리 직전 프로세스 중단)."""
    out = []
    for i, f in enumerate(up["files"]):
        if _is_p2(f) and not f.get("removed") and not f.get("done") and f.get("got"):
            if not _r_missing(f["got"], _n_chunks(f["size"], int(f["chunk"]))):
                out.append(i)
    return out


def _finalize_ready_files(ctx: AppContext, up: dict[str, Any]) -> None:
    for i in _finalize_ready(ctx, up):
        _finalize_file(ctx, up["id"], i)


# ---------------------------------------------------------------- PUT: 프로토콜 1(업그레이드 전 OPEN 세션 — 기존 append 경로)
def put_chunk_v1(ctx: AppContext, principal: Principal, upload_id: str, index: int, offset: int,
                 data: bytes, chunk_sha256: str | None = None) -> dict[str, Any]:
    require_config_ok(ctx)
    root = _upload_root(ctx)
    chunk = ctx.settings.upload.chunk_bytes
    with ctx.engine.begin() as conn:
        up = _owned(conn, principal, upload_id, for_update=True)
        require_execute(principal, up["project_id"])
        _require_open(up)
        if index < 0 or index >= len(up["files"]):
            raise not_found("UPLOAD_FILE_NOT_FOUND", "업로드 파일 번호가 없습니다")
        files = [dict(f) for f in up["files"]]
        f = files[index]
        if f.get("removed"):
            raise conflict("UPLOAD_FILE_REMOVED", f"목록에서 뺀 파일입니다: {f['rel']}", rel=f["rel"])
        _reject_scx_file(f)
        if f.get("done"):
            raise conflict("UPLOAD_FILE_DONE", f"이미 다 받은 파일입니다: {f['rel']}", received=int(f["size"]))
        p = U.target_path(up["dir_path"], _segs(f), create_parents=True, upload_root=root)
        part = p + U.PART_SUFFIX
        received = os.path.getsize(part) if os.path.isfile(part) else 0
        if offset != received:
            raise conflict("UPLOAD_OFFSET_MISMATCH", f"offset {offset} 이 받은 크기 {received} 와 다릅니다(이어 올리기는 "
                           "received 부터)", received=received)
        if len(data) > chunk:
            raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({chunk} B)보다 큽니다", status=413, limit=chunk)
        if offset + len(data) > f["size"]:
            raise unprocessable("CHUNK_OVERFLOW", "선언한 파일 크기를 넘는 청크입니다", size=int(f["size"]),
                                received=received)
        if os.path.lexists(p):
            raise conflict("UPLOAD_FILE_EXISTS", f"이미 있는 파일입니다(덮어쓰지 않음): {f['rel']}", rel=f["rel"])
        if chunk_sha256 is not None and hashlib.sha256(data).hexdigest() != chunk_sha256.lower():
            raise unprocessable("CHUNK_SHA256_MISMATCH", "청크 sha256 이 다릅니다(쓰지 않음) — 같은 offset 으로 다시 보내세요",
                                received=received)
        key = (upload_id, index)
        h = _hash_state(key, part, received)
        if data:
            U.append_chunk(part, data, up["dir_path"])      # 사전할당·fsync 없이 append(재시작 시 received = .part 크기)
            h.update(data)
        received += len(data)
        _hash_put(key, h, received)
        if received == f["size"]:
            sha = h.hexdigest()
            _hash_put(key, None, None)
            if f.get("sha256_expected") and sha != f["sha256_expected"]:
                user_seg = U.user_segment(up["username"], up["user_id"])
                moved = U.move_to_backup(root, user_seg, part,
                                         f"{os.path.basename(up['dir_path'])}__{'_'.join(_segs(f))}.mismatch")
                raise unprocessable("SHA256_MISMATCH", f"sha256 이 다릅니다 — 처음부터 다시 올리세요: {f['rel']}",
                                    rel=f["rel"], expected=f["sha256_expected"], actual=sha, received=0,
                                    backup_path=moved)
            if os.path.lexists(p):
                raise conflict("UPLOAD_FILE_EXISTS", f"이미 있는 파일입니다(덮어쓰지 않음): {f['rel']}", rel=f["rel"])
            os.rename(part, p)
            f.update(done=True, sha256=sha)
        conn.execute(update(uploads).where(uploads.c.id == upload_id).values(files=files, updated_at=func.now()))
    return {"index": index, "received": received, "received_total": received, "chunk": None, "duplicate": False,
            "done": bool(f.get("done")), "sha256": f.get("sha256")}


# ---------------------------------------------------------------- 파일 하나 빼기
def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _case_uses_upload(conn, up: dict[str, Any]) -> bool:
    """이 업로드 폴더 경로를 입력(rad·결과·h3d)으로 쓰는 Case 가 있는가."""
    name = os.path.basename(os.path.normpath(up["dir_path"])).lower()
    pat = f"%{_like_escape(name)}%"
    cols = (cases.c.rad_path, cases.c.results_dir, cases.c.h3d_path)
    q = select(*cols).where(or_(*[func.lower(c).like(pat, escape="\\") for c in cols]))
    for row in conn.execute(q):
        if any(v and is_within(v, up["dir_path"]) for v in row):
            return True
    return False


def remove_file(ctx: AppContext, principal: Principal, upload_id: str, index: int) -> dict[str, Any]:
    """_REMOVING 표시는 DB 커밋(트랜잭션 종료) 뒤에 푼다 — 그 사이 같은 파일 PUT 이 removed 아닌 상태를 보지 않게."""
    removing: list[tuple[str, int]] = []
    try:
        return _remove_file(ctx, principal, upload_id, index, removing)
    finally:
        with _GUARD:
            for k in removing:
                _REMOVING.discard(k)


def _remove_file(ctx: AppContext, principal: Principal, upload_id: str, index: int,
                 removing: list[tuple[str, int]]) -> dict[str, Any]:
    require_config_ok(ctx)
    root = _upload_root(ctx)
    cfg = ctx.settings.upload
    with ctx.engine.begin() as conn:
        up = _owned(conn, principal, upload_id, for_update=True)
        require_execute(principal, up["project_id"])
        if index < 0 or index >= len(up["files"]):
            raise not_found("UPLOAD_FILE_NOT_FOUND", "업로드 파일 번호가 없습니다")
        files = [dict(f) for f in up["files"]]
        f = files[index]
        if f.get("removed"):
            return upload_out(up, cfg)              # 멱등
        if up["state"] in (CANCELED, STALE):
            raise conflict("UPLOAD_CLOSED", f"이미 끝난 업로드입니다({up['state']})", state=up["state"])
        if up["state"] == COMPLETED and _case_uses_upload(conn, up):
            raise conflict("UPLOAD_IN_USE", "이 업로드로 만든 Case 가 있어 파일을 뺄 수 없습니다")
        _require_not_fetching(conn, upload_id)
        key = (upload_id, index)
        with _GUARD:
            if any(i == index for i, _k in _INFLIGHT.get(upload_id, ())) or key in _REMOVING:
                raise conflict("UPLOAD_FILE_BUSY", f"이 파일의 청크를 받는 중입니다 — 멈춘 뒤 다시 시도하세요: {f['rel']}",
                               rel=f["rel"])
            _REMOVING.add(key)
        removing.append(key)
        lk = _flock(key)
        if not lk.acquire(blocking=False):
            raise conflict("UPLOAD_FILE_BUSY", f"이 파일을 마무리하는 중입니다: {f['rel']}", rel=f["rel"])
        try:
            p = U.target_path(up["dir_path"], _segs(f), create_parents=False, upload_root=root)
            user_seg = U.user_segment(up["username"], up["user_id"])
            base = f"{os.path.basename(up['dir_path'])}__{'_'.join(_segs(f))}.removed"
            for src, nm in ((p, base), (p + U.PART_SUFFIX, base + ".part")):
                U.move_to_backup(root, user_seg, src, nm)
            _hash_put(key, None, None)
            f.update(removed=True, done=False, got=[], sha256=None)
            vals: dict[str, Any] = {"files": files, "updated_at": func.now(), "result": None,
                                    "total_bytes": sum(x["size"] for x in files if not x.get("removed"))}
            if up["state"] == COMPLETED:
                vals.update(state=OPEN, completed_at=None)
            conn.execute(update(uploads).where(uploads.c.id == upload_id).values(**vals))
        finally:
            lk.release()
        up = _row(conn, upload_id)
    return upload_out(up, cfg)


# ---------------------------------------------------------------- complete 검사
def _rel_of(up_dir: str, p: str) -> str | None:
    if is_within(p, up_dir):
        return os.path.relpath(p, up_dir).replace(os.sep, "/")
    return None


STATE_EXT = (".sta", ".str")              # 누적 씬 이전 런 상태 파일(계약 esl_cumulative_input.md §2·§9.2)
STATE_HEADER = b"#radioss state file"
STATE_KIND_SCAN_BYTES = 4 * 1024 * 1024   # 종류(형상·초기 상태) 확인은 파일 앞부분 블록 헤더만 본다(수 GB 대비)


def _state_ext(name: str) -> bool:
    return os.path.splitext(str(name).replace("\\", "/").rstrip("/"))[1].lower() in STATE_EXT


def _state_probe(path: str, header_only: bool = False, scan_bytes: int = STATE_KIND_SCAN_BYTES) -> tuple[bool, list[str]]:
    """(상태 파일 헤더 여부, 종류[geometry|initial]) — 앞 scan_bytes 만 읽음(header_only 면 첫 행만).

    줄 단위 반복(``for raw in fh``)은 줄바꿈 없는 거대 줄을 통째로 메모리에 올리므로(200 MB 한 줄 → RSS +400 MB),
    ``readline(남은 예산)`` 으로 읽고 예산을 넘는 줄(줄바꿈 없이 예산을 채움)이면 거기서 멈춘다 — 첫 행이 그렇다면
    상태 파일 헤더가 아니다(너무 긴 줄).
    """
    head, kinds = False, set()
    budget = max(1, int(scan_bytes))
    try:
        with open(path, "rb") as fh:
            first = True
            n = 0
            while n < budget:
                raw = fh.readline(budget - n)
                if not raw:
                    break
                n += len(raw)
                too_long = not raw.endswith(b"\n") and n >= budget
                s = raw.strip()
                if first and s:
                    head = (not too_long) and s.lower().startswith(STATE_HEADER)
                    first = False
                    if header_only:
                        break
                u = raw[:8].upper()
                if u.startswith((b"/NODE", b"/SHELL", b"/SH3N")):
                    kinds.add("geometry")
                elif u.startswith(b"/INISHE"):
                    kinds.add("initial")
                if too_long or len(kinds) == 2:
                    break
    except OSError:
        pass
    return head, sorted(kinds)


def inspect_upload(ctx: AppContext, up: dict[str, Any]) -> dict[str, Any]:
    d = up["dir_path"]
    rels = [f["rel"] for f in up["files"] if not f.get("removed")]
    problems: list[str] = []
    missing: list[str] = []
    state_incs: list[dict[str, Any]] = []
    parts: list[dict] = []
    rad_path = results_dir = None
    # rad: rad/ 아래 .rad — _0000.rad 하나 또는 .rad 하나
    rads = [r for r in rels if r.startswith("rad/") and r.lower().endswith(".rad")]
    if rads:
        main = [r for r in rads if r.lower().endswith("_0000.rad")]
        pick = main if len(main) >= 1 else rads
        if len(pick) == 1:
            rad_path = os.path.join(d, *pick[0].split("/"))
        else:
            problems.append(f"rad 파일이 여러 개입니다({', '.join(pick)}) — Starter(_0000.rad) 하나만 올리세요")
    elif any(r.startswith("rad/") for r in rels):
        problems.append("rad/ 에 .rad 파일이 없습니다")
    if rad_path:
        core = ctx.config.core or {}
        cc = core.get("case") or {}
        depth = int(cc.get("rad_include_max_depth") or 8)
        pmap = cc.get("include_path_map") or None
        real_d = os.path.realpath(d)

        def inside(p: str) -> bool:      # 업로드 폴더 안(경로·실제 경로 모두) — 밖 파일은 읽지도 따라가지도 않는다
            return _rel_of(d, p) is not None and is_within(os.path.realpath(p), real_d)

        try:
            refs = core_adapter.scan_include_refs(rad_path, depth, pmap, follow=inside)
        except core_adapter.CoreError as exc:
            refs = []
            problems.append(f"{exc.code}: {exc.message}")
        outside = False
        for ref in refs:
            p = ref["path"]
            if ref["found"] and inside(p):
                by_ext = _state_ext(p) or _state_ext(ref["spec"])
                scan = int(ctx.settings.upload.state_scan_kb) * 1024
                head, kinds = _state_probe(p, header_only=not by_ext, scan_bytes=scan)
                if head and not by_ext:
                    head, kinds = _state_probe(p, scan_bytes=scan)
                if head or by_ext:
                    state_incs.append({"rel": _rel_of(d, p), "spec": ref["spec"], "kinds": kinds, "found": True})
                continue
            if not ref["found"] and p and inside(p):
                rel = _rel_of(d, p)
                if rel not in missing:
                    missing.append(rel)
                if _state_ext(ref["spec"]):
                    state_incs.append({"rel": rel, "spec": ref["spec"], "kinds": [], "found": False})
                    msg = f"STATE_INCLUDE_MISSING: 누적 해석 상태 파일 include 가 업로드에 없습니다: {ref['spec']}"
                    if msg not in problems:
                        problems.append(msg)
                continue
            # 업로드 밖(절대·상위 경로 등): 존재 여부와 무관하게 같은 메시지(서버 파일 존재 확인 통로 차단)
            outside = True
            msg = f"업로드에 포함되지 않은 include: {ref['spec']}"
            if msg not in problems:
                problems.append(msg)
        if not missing and not outside:
            try:
                parts = core_adapter.list_parts(rad_path, depth, pmap)
            except core_adapter.CoreError as exc:
                problems.append(f"{exc.code}: {exc.message}")
    # 결과: results/ 아래 done.json 이 있는 폴더 하나
    res_rels = [r for r in rels if r.startswith("results/")]
    if res_rels:
        dones = sorted({r.rsplit("/", 1)[0] for r in res_rels if r.rsplit("/", 1)[-1].lower() == "done.json"})
        if len(dones) == 1:
            results_dir = os.path.join(d, *dones[0].split("/"))
            info = system.inspect_results(results_dir)
            problems += [f"결과 폴더: {p}" for p in info["problems"]]
        elif not dones:
            problems.append("결과 폴더에 done.json 이 없습니다(ESL_extract.bat 이 만든 폴더를 고르세요)")
        else:
            problems.append(f"done.json 이 있는 폴더가 여러 개입니다: {', '.join(dones)}")
    h3d_path = None
    h3ds = [r for r in rels if r.lower().endswith(".h3d")]
    if len(h3ds) == 1:
        h3d_path = os.path.join(d, *h3ds[0].split("/"))
        problems += [f"h3d: {p}" for p in check_h3d(h3d_path)]
    elif len(h3ds) > 1:
        problems.append(f"h3d 파일이 여러 개입니다({', '.join(h3ds)}) — 하나만 올리세요")
    # 계약 §6: rad(+include) 필수 + (h3d | 결과 폴더) 중 하나
    if not rad_path and not any(p.startswith("rad") for p in problems):
        problems.append("rad 파일(_0000.rad)이 필요합니다")
    if not h3ds and not res_rels:
        problems.append("h3d 파일 또는 추출 결과 폴더(done.json) 중 하나가 필요합니다")
    ok = not problems and not missing
    h3d_meta = None
    if h3d_path:
        h3d_meta = next((f.get("meta") for f in up["files"] if not f.get("removed") and f["rel"] == h3ds[0]), None)
    return {"ok": ok, "rad_path": rad_path, "results_dir": results_dir, "h3d_path": h3d_path, "h3d_meta": h3d_meta,
            "parts": parts,
            "missing_includes": missing, "problems": problems, "state_includes": state_incs}


H3D_MAGIC = b"HYPER3D"


def check_h3d(path: str) -> list[str]:
    """h3d 파일 가벼운 검사(크기·헤더 HYPER3D). 추출은 서버 H3D_EXTRACT 작업(다음 단계)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(256)
    except OSError as exc:
        return [f"읽을 수 없습니다: {exc}"]
    if size == 0:
        return ["빈 파일입니다"]
    if H3D_MAGIC not in head.upper():
        return ["h3d 헤더(HYPER3D)가 아닙니다"]
    return []


def _pending_item(cfg, i: int, f: dict[str, Any], received: int) -> dict[str, Any]:
    size = int(f["size"])
    if _is_p2(f):
        c = int(f["chunk"])
        n = _n_chunks(size, c)
        missing = [[0, n]] if f.get("done") else _r_missing(f.get("got") or [], n)
    else:
        c = cfg.chunk_bytes
        n = _n_chunks(size, c)
        missing = [[received // c, n]] if received // c < n else []
    return {"index": i, "rel": f["rel"], "missing": missing}


def scx_meta(up: dict[str, Any]) -> dict[str, Any] | None:
    """SCX 세션이면 마지막 SF_REGISTER 가 기록한 출처(result.scx 가 add_files 로 지워진 경우 — files[] 의 scx 표지)."""
    return next(((f.get("scx_session") or None) for f in up["files"] if f.get("scx_session")), None)


def complete(ctx: AppContext, principal: Principal, upload_id: str) -> dict[str, Any]:
    require_config_ok(ctx)
    _upload_root(ctx)
    with ctx.engine.connect() as conn:
        up0 = _owned(conn, principal, upload_id)
    if up0["state"] == OPEN:
        _finalize_ready_files(ctx, up0)          # 다 모였는데 마무리 전인 파일(멱등) — 행 잠금 밖에서
    cfg = ctx.settings.upload
    with ctx.engine.begin() as conn:
        up = _owned(conn, principal, upload_id, for_update=True)
        require_execute(principal, up["project_id"])
        if up["state"] == COMPLETED and up.get("result"):
            return {"upload_id": upload_id, "state": COMPLETED, **up["result"]}
        _require_open(up)
        _require_not_fetching(conn, upload_id)
        pending = []
        for i, f in enumerate(up["files"]):
            if f.get("removed"):
                continue
            p = os.path.join(up["dir_path"], *_segs(f))
            if f.get("done"):
                try:
                    ok = os.path.getsize(p) == int(f["size"])
                except OSError:
                    ok = False
                if not ok:
                    pending.append(_pending_item(cfg, i, f, 0))     # 디스크 크기 ≠ 선언 크기 → 전체 누락으로 본다
            else:
                pending.append(_pending_item(cfg, i, f, _received(up, f)))
        if pending:
            raise conflict("UPLOAD_INCOMPLETE", f"아직 다 받지 못한 파일이 {len(pending)}개 있습니다", pending=pending[:100])
        res = inspect_upload(ctx, up)
        prev_scx = (up.get("result") or {}).get("scx") or scx_meta(up)
        if prev_scx:
            res["scx"] = prev_scx                   # v0.11.0: SCX 세션 출처(누락 include 를 추가한 뒤 complete 해도 유지)
        vals: dict[str, Any] = {"result": res, "updated_at": func.now()}
        if res["ok"]:
            vals.update(state=COMPLETED, completed_at=func.now())
        conn.execute(update(uploads).where(uploads.c.id == upload_id).values(**vals))
        state = COMPLETED if res["ok"] else OPEN
    return {"upload_id": upload_id, "state": state, **res}


# ---------------------------------------------------------------- v0.7.0 S2 템플릿 업로드 연결(계약 esl_opt_run.md §5.1·§7.2)
TEMPLATE_PURPOSE = "template"
TEMPLATE_MESH_EXT = (".fem", ".rad")


def _ready_upload(ctx: AppContext, principal: Principal, upload_id: str,
                  project_id: str | None = None) -> tuple[dict[str, Any], str, list[str]]:
    """플랫폼 기능(템플릿·비드 DOE)이 읽을 업로드: 본인 업로드(아니면 404 UPLOAD_NOT_FOUND)·그 프로젝트 power,
    파일을 모두 받았어야 함(아니면 409 UPLOAD_NOT_READY), 업로드 폴더 자체(루트→사용자→폴더) 링크·junction 검사.
    반환 (업로드 행, 업로드 루트, 살아 있는 파일 rel 목록). 업로드 폴더에는 쓰지 않는다."""
    require_config_ok(ctx)
    root = _upload_root(ctx)
    with ctx.engine.connect() as conn:
        up0 = _owned(conn, principal, upload_id)
    if project_id is not None and up0["project_id"] != project_id:
        raise not_found("UPLOAD_NOT_FOUND", "업로드를 찾을 수 없습니다")
    require_execute(principal, up0["project_id"])
    if up0["state"] == OPEN:
        _finalize_ready_files(ctx, up0)          # 다 모였는데 마무리 전인 파일(멱등)
    with ctx.engine.connect() as conn:
        up = _owned(conn, principal, upload_id)
    if up["state"] not in (OPEN, COMPLETED):
        raise conflict("UPLOAD_NOT_READY", f"끝난 업로드입니다({up['state']}) — 다시 올리세요", state=up["state"])
    live = [f for f in up["files"] if not f.get("removed")]
    pending = []
    for f in live:
        p = os.path.join(up["dir_path"], *_segs(f))
        try:
            ok = bool(f.get("done")) and os.path.getsize(p) == int(f["size"])
        except OSError:
            ok = False
        if not ok:
            pending.append(f["rel"])
    if not live or pending:
        raise conflict("UPLOAD_NOT_READY", f"아직 다 받지 못한 파일이 {len(pending)}개 있습니다" if pending else
                       "업로드에 파일이 없습니다", pending=pending[:100])
    U.check_upload_dir(root, up["dir_path"])
    return up, root, [f["rel"] for f in live]


def template_source(ctx: AppContext, principal: Principal, upload_id: str,
                    project_id: str | None = None) -> tuple[dict[str, Any], str]:
    """템플릿 메시 업로드의 메시 파일 경로(읽기만). 본인 업로드(아니면 404 UPLOAD_NOT_FOUND)·그 프로젝트 power,
    파일을 모두 받았어야 함(아니면 409 UPLOAD_NOT_READY). 업로드 폴더 자체(루트→사용자→폴더) 링크·junction 검사 후
    `.fem` 하나 또는 `.rad` 하나(`*_0000.rad` 우선)를 고른다 — 없으면 422 MESH_FORMAT_UNSUPPORTED, 여러 개면 MESH_INVALID."""
    up, root, rels = _ready_upload(ctx, principal, upload_id, project_id)
    fems = [r for r in rels if r.lower().endswith(".fem")]
    rads = [r for r in rels if r.lower().endswith(".rad")]
    main0 = [r for r in rads if r.lower().endswith("_0000.rad")]
    if fems and rads:
        raise unprocessable("MESH_INVALID", "템플릿은 .fem 또는 .rad 중 하나만 올리세요", files=fems + rads)
    pick = fems or main0 or rads
    if not pick:
        raise unprocessable("MESH_FORMAT_UNSUPPORTED", "템플릿 메시 파일(.fem 또는 .rad)이 없습니다", files=rels[:20])
    if len(pick) > 1:
        raise unprocessable("MESH_INVALID", f"메시 파일이 여러 개입니다({', '.join(pick[:5])}) — 하나만 올리세요",
                            files=pick)
    path = U.target_path(up["dir_path"], pick[0].split("/"), upload_root=root)
    return up, path


# ---------------------------------------------------------------- v0.9.0 비드 DOE 업로드 연결(계약 esl_bead_doe.md §10·§13)
DOE_STEP_EXT = (".step", ".stp")
DOE_STEP_PURPOSE = "doe_step"
DOE_MESH_PURPOSE = "doe_mesh"
STEP_MAGIC = b"ISO-10303-21;"


def doe_source(ctx: AppContext, principal: Principal, upload_id: str, project_id: str,
               kind: str) -> tuple[dict[str, Any], str, str]:
    """비드 DOE 입력 업로드(읽기만) → (업로드 행, 업로드 루트, 주 파일 절대경로). purpose 없이 올린 업로드(rel `rad/<파일>`)를
    여기서 판정한다(complete 를 거치지 않아도 됨).

    - kind ``step``: `.step`·`.stp` 정확히 1개(아니면 422 STEP_INVALID).
    - kind ``mesh``: ② B 메시 — `.rad` 하나(`*_0000.rad` 우선, + include) 또는 `.rad` 가 없으면 `.inc` 하나
      (아니면 422 MESH_INVALID·MESH_FORMAT_UNSUPPORTED). `.fem` 은 받지 않는다(paicad 조립 = rad/inc)."""
    up, root, rels = _ready_upload(ctx, principal, upload_id, project_id)
    if kind == "step":
        pick = [r for r in rels if r.lower().endswith(DOE_STEP_EXT)]
        if len(pick) != 1:
            raise unprocessable("STEP_INVALID", "중립면 STEP(.step·.stp) 파일을 정확히 1개 올리세요"
                                + (f"(지금 {len(pick)}개)" if pick else ""), files=pick[:20] or rels[:20])
    elif kind == "mesh":
        rads = [r for r in rels if r.lower().endswith(".rad")]
        incs = [r for r in rels if r.lower().endswith(".inc")]
        main0 = [r for r in rads if r.lower().endswith("_0000.rad")]
        pick = main0 or rads or incs
        if not pick:
            raise unprocessable("MESH_FORMAT_UNSUPPORTED", "B 메시 파일(.rad + include 또는 .inc)이 없습니다", files=rels[:20])
        if len(pick) > 1:
            raise unprocessable("MESH_INVALID", f"주 메시 파일이 여러 개입니다({', '.join(pick[:5])}) — 하나만 올리세요",
                                files=pick[:20])
    else:  # pragma: no cover - 호출자 결함
        raise ValueError(kind)
    return up, root, U.target_path(up["dir_path"], pick[0].split("/"), upload_root=root)


def step_check(path: str, max_mb: float) -> dict[str, Any]:
    """STEP 머리(`ISO-10303-21;`)·크기 검사(파일 앞부분만 읽음). 실패 422 STEP_INVALID. 반환 {file_name, size_mb}."""
    if os.path.islink(path) or not os.path.isfile(path):
        raise unprocessable("STEP_INVALID", "STEP 파일을 읽을 수 없습니다")
    size = os.path.getsize(path)
    mb = size / (1024 * 1024)
    if mb > float(max_mb):
        raise unprocessable("STEP_INVALID", f"STEP 파일이 큽니다({mb:.1f} MB > {float(max_mb):g} MB, bead_doe.step_max_mb)",
                            size_mb=round(mb, 3), limit_mb=float(max_mb))
    with open(path, "rb") as fh:
        head = fh.read(256)
    if not head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(STEP_MAGIC):
        raise unprocessable("STEP_INVALID", "STEP(ISO-10303-21) 파일이 아닙니다(머리 'ISO-10303-21;' 없음)")
    return {"file_name": os.path.basename(path), "size_mb": round(mb, 3)}


def upload_file_sha(up: dict[str, Any], path: str) -> str:
    """업로드 기록의 sha256(받을 때 계산) — 없으면 파일에서 계산."""
    rel = os.path.relpath(path, up["dir_path"]).replace(os.sep, "/")
    for f in up["files"]:
        if f.get("rel") == rel and not f.get("removed") and f.get("sha256"):
            return str(f["sha256"]).lower()
    return sha256_file(path)


def save_doe_check(ctx: AppContext, upload_id: str, purpose: str, rel: str, sha256: str, ok: bool,
                   extra: dict[str, Any] | None = None) -> None:
    """비드 DOE 입력 검사 결과를 uploads.result(purpose = doe_step|doe_mesh)에 저장, 통과하면 COMPLETED(stale 정리 대상에서
    빠짐 — 워커 BD_INPUT 이 sha256 확인 후 _doe/<id>/input 으로 복사). 업로드 폴더에는 쓰지 않는다."""
    with ctx.engine.begin() as conn:
        up = _row(conn, upload_id, for_update=True)
        vals: dict[str, Any] = {"result": {"purpose": purpose, "ok": bool(ok), "rel": rel, "sha256": sha256,
                                           **(extra or {})}, "updated_at": func.now()}
        if ok and up["state"] == OPEN:
            vals.update(state=COMPLETED, completed_at=func.now())
        conn.execute(update(uploads).where(uploads.c.id == upload_id).values(**vals))


def template_include_problems(ctx: AppContext, up: dict[str, Any], rad_path: str) -> tuple[list[str], list[str]]:
    """rad 템플릿 include: 업로드 폴더 밖(존재 여부 무관 같은 메시지)·누락 목록. 밖 파일은 읽지도 따라가지도 않는다."""
    d = up["dir_path"]
    real_d = os.path.realpath(d)
    core = ctx.config.core or {}
    cc = core.get("case") or {}

    def inside(p: str) -> bool:
        return _rel_of(d, p) is not None and is_within(os.path.realpath(p), real_d)

    problems: list[str] = []
    missing: list[str] = []
    try:
        refs = core_adapter.scan_include_refs(rad_path, int(cc.get("rad_include_max_depth") or 8), None, follow=inside)
    except core_adapter.CoreError as exc:
        return [f"{exc.code}: {exc.message}"], []
    for ref in refs:
        p = ref["path"]
        if ref["found"] and inside(p):
            continue
        if not ref["found"] and p and inside(p):
            rel = _rel_of(d, p)
            if rel not in missing:
                missing.append(rel)
            continue
        msg = f"업로드에 포함되지 않은 include: {ref['spec']}"
        if msg not in problems:
            problems.append(msg)
    return problems, missing


def save_template_check(ctx: AppContext, upload_id: str, check: dict[str, Any], rel: str) -> None:
    """템플릿 검사 결과를 uploads.result(purpose = template)에 저장. 통과하면 업로드 COMPLETED(업로드 폴더에는 쓰지 않음)."""
    with ctx.engine.begin() as conn:
        up = _row(conn, upload_id, for_update=True)
        vals: dict[str, Any] = {"result": {"purpose": TEMPLATE_PURPOSE, "ok": bool(check.get("ok")), "rel": rel,
                                           "sha256": check.get("sha256"), "check": check,
                                           "problems": [e.get("message", "") for e in
                                                        (check.get("quality") or {}).get("errors") or []]},
                                "updated_at": func.now()}
        if check.get("ok") and up["state"] == OPEN:
            vals.update(state=COMPLETED, completed_at=func.now())
        conn.execute(update(uploads).where(uploads.c.id == upload_id).values(**vals))


# ---------------------------------------------------------------- 취소·stale(삭제 없이 _backup 으로)
def _retire(ctx: AppContext, conn, up: dict[str, Any], state: str, *, strict: bool = True) -> dict[str, Any]:
    """업로드 폴더를 _backup 으로 옮기고 state 표시. 폴더(또는 사용자 폴더)가 링크로 바뀌었으면 옮기지 않는다:
    strict(취소)면 PATH_UNSAFE, 아니면(stale 정리) 경고만 남기고 상태만 바꾼다."""
    root = _upload_root(ctx)
    user_seg = U.user_segment(up["username"], up["user_id"])
    moved = None
    d = up["dir_path"]
    if os.path.lexists(d):
        try:
            U.check_upload_dir(root, d)
            moved = U.move_to_backup(root, user_seg, d)
        except DomainError as exc:
            if strict:
                raise
            log.warning("upload %s retire: 폴더를 옮기지 않음(%s)", up["id"], exc.code)
    with _HASH_LOCK:
        for k in [k for k in _HASHES if k[0] == up["id"]]:
            _HASHES.pop(k, None)
    conn.execute(update(uploads).where(uploads.c.id == up["id"]).values(state=state, backup_path=moved,
                                                                         updated_at=func.now()))
    return _row(conn, up["id"])


def cancel(ctx: AppContext, principal: Principal, upload_id: str) -> dict[str, Any]:
    require_config_ok(ctx)
    with ctx.engine.begin() as conn:
        up = _owned(conn, principal, upload_id, for_update=True)
        require_execute(principal, up["project_id"])
        if up["state"] == COMPLETED:
            raise conflict("UPLOAD_COMPLETED", "완료된 업로드는 취소할 수 없습니다(Case 입력으로 쓰일 수 있음)")
        _require_open(up)
        _require_not_fetching(conn, upload_id)
        with _GUARD:
            busy = bool(_INFLIGHT.get(upload_id)) or any(k[0] == upload_id for k in _REMOVING)
        if busy:
            raise conflict("UPLOAD_FILE_BUSY", "청크를 받는 중입니다 — 멈춘 뒤(진행 중 청크가 끝난 뒤) 다시 취소하세요")
        up = _retire(ctx, conn, up, CANCELED)
    return upload_out(up, ctx.settings.upload)


def cleanup_stale(ctx: AppContext, now: _dt.datetime | None = None) -> list[str]:
    """updated_at 이 upload.stale_hours 보다 오래된 OPEN 세션 → _backup 으로 옮기고 STALE. 옮긴 id 목록."""
    if not ctx.settings.storage.upload_root:
        return []
    hours = ctx.settings.upload.stale_hours
    with ctx.engine.connect() as conn:
        ref = now if now is not None else conn.execute(select(func.now())).scalar_one()
    cutoff = ref - _dt.timedelta(hours=hours)
    out = []
    with ctx.engine.connect() as conn:
        ids = [r[0] for r in conn.execute(select(uploads.c.id).where(
            and_(uploads.c.state == OPEN, uploads.c.updated_at < cutoff)))]
    for uid in ids:
        with ctx.engine.begin() as conn:
            up = _row(conn, uid, for_update=True)
            if up["state"] != OPEN or up["updated_at"] >= cutoff:
                continue
            if _scx_job(conn, uid) is not None:     # v0.11.0: SCX_FETCH 진행 중(대기 포함) 세션은 정리하지 않음
                continue
            _retire(ctx, conn, up, STALE, strict=False)
            out.append(uid)
    return out


# ---------------------------------------------------------------- Case ↔ 업로드 메타(계약 esl_upload_speed.md §5.6·§6.5)
def h3d_metas_for(conn, h3d_paths: list[str]) -> dict[str, dict[str, Any] | None]:
    """Case 의 h3d 경로 → 그 h3d 를 올린 COMPLETED 업로드의 meta(없으면 None). 목록은 IN 한 번."""
    paths = sorted({p for p in h3d_paths if p})
    if not paths:
        return {}
    keys = {p: os.path.normcase(os.path.normpath(p)).lower() for p in paths}
    cand = sorted(set(keys.values()) | {p.lower() for p in paths})
    rows = conn.execute(select(uploads.c.result["h3d_path"].astext, uploads.c.result["h3d_meta"]).where(and_(
        uploads.c.state == COMPLETED, func.lower(uploads.c.result["h3d_path"].astext).in_(cand)
    )).order_by(uploads.c.completed_at.desc())).all()
    by = {}
    for hp, meta in rows:
        by.setdefault(os.path.normcase(os.path.normpath(hp)).lower(), meta if isinstance(meta, dict) else None)
    return {p: by.get(keys[p]) for p in paths}


def h3d_meta_for(conn, h3d_path: str | None) -> dict[str, Any] | None:
    return h3d_metas_for(conn, [h3d_path]).get(h3d_path) if h3d_path else None


def check_slim_part(meta: dict[str, Any] | None, part_id: int | None) -> None:
    """압축 모드 h3d 에는 meta.part_id 파트만 있다 — 다른 파트로 Case 를 만들거나 바꾸면 422 SLIM_PART_MISMATCH."""
    if not meta or meta.get("kind") != "h3d_slim" or part_id is None or meta.get("part_id") is None:
        return
    if int(meta["part_id"]) != int(part_id):
        title = f"({meta['part_title']})" if meta.get("part_title") else ""
        raise unprocessable("SLIM_PART_MISMATCH", f"압축 모드 h3d에는 파트 {meta['part_id']}{title}만 있습니다 — "
                            "다른 파트는 원본 h3d로 올리세요", meta_part_id=int(meta["part_id"]),
                            part_id=int(part_id))
