"""브라우저 분할 업로드 세션(계약 esl_p3_ux.md §1.1).

흐름: POST /uploads(사전 검사·폴더 생성) → PUT /uploads/{id}/files/{index}?offset=(청크, 순서 검증, 마지막 청크에서
sha256 검증 후 `.part` → 최종 이름) → POST /uploads/{id}/complete(rad 파싱·include 해석·결과 폴더 검사, 누락 include 목록)
→ (누락 시 POST /uploads/{id}/files 로 추가 후 다시 complete). DELETE 는 미완료 세션 취소(받은 파일은 _backup 으로 이동).
미완료 세션은 upload.stale_hours 뒤 _backup 으로 이동(STALE). 파일 삭제는 하지 않는다.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import shutil
import threading
import uuid
from typing import Any

from sqlalchemy import and_, func, insert, select, update

from esl_worker import core_adapter

from ...core import uploads as U
from ...core.auth import Principal
from ...core.config import is_within
from ...core.db.tables import uploads
from ...core.errors import DomainError, conflict, not_found, unprocessable
from ...core.inputs import sha256_file
from ..context import AppContext
from . import system
from .common import require_config_ok, require_execute

OPEN, COMPLETED, CANCELED, STALE = "OPEN", "COMPLETED", "CANCELED", "STALE"


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


def _segs(f: dict[str, Any]) -> list[str]:
    return f["rel"].split("/")


def _received(up: dict[str, Any], f: dict[str, Any]) -> int:
    p = os.path.join(up["dir_path"], *_segs(f))
    if f.get("done"):
        return int(f["size"])
    try:
        return os.path.getsize(p + U.PART_SUFFIX)
    except OSError:
        return 0


def upload_out(up: dict[str, Any], chunk: int) -> dict[str, Any]:
    files = []
    for i, f in enumerate(up["files"]):
        rec = _received(up, f) if up["state"] == OPEN or f.get("done") else 0
        files.append({"index": i, "rel": f["rel"], "size": int(f["size"]), "received": rec, "done": bool(f.get("done")),
                      "sha256": f.get("sha256"), "sha256_expected": f.get("sha256_expected")})
    return {"upload_id": up["id"], "project_id": up["project_id"], "name": up["name"], "state": up["state"],
            "dir_path": up["dir_path"], "chunk_size": chunk, "total_bytes": int(up["total_bytes"]),
            "received_bytes": sum(f["received"] for f in files), "files": files, "result": up.get("result"),
            "backup_path": up.get("backup_path"), "created_at": up["created_at"], "updated_at": up["updated_at"],
            "completed_at": up.get("completed_at")}


def _norm_files(ctx: AppContext, files: list[Any], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cfg = ctx.settings.upload
    seen = {f["rel"].casefold() for f in existing}
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
        out.append({"rel": f.rel, "size": int(f.size), "sha256_expected": sha, "sha256": None, "done": False})
    if len(existing) + len(out) > cfg.max_files:
        raise DomainError("UPLOAD_TOO_MANY_FILES", f"파일이 너무 많습니다(최대 {cfg.max_files}개)", status=413)
    total = sum(f["size"] for f in existing) + sum(f["size"] for f in out)
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


# 받는 동안 파일 전체 sha256 을 이어서 계산(다시 읽지 않음). 프로세스 재시작 등으로 상태가 없거나 어긋나면
# 디스크의 받은 부분을 한 번 다시 읽어 복원한다. 업로드 행 잠금(FOR UPDATE) 아래에서만 쓰므로 같은 파일 동시 갱신 없음.
_HASHES: dict[tuple[str, int], tuple[Any, int]] = {}
_HASH_LOCK = threading.Lock()


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


def _prepare_files(up_dir: str, new: list[dict[str, Any]]) -> None:
    """빈 파일(size 0)은 바로 만들고 검증, 나머지는 대상 경로가 비어 있는지(덮어쓰기 없음)·안전한지 확인."""
    for f in new:
        p = U.target_path(up_dir, _segs(f), create_parents=True)
        if os.path.lexists(p):
            raise conflict("UPLOAD_FILE_EXISTS", f"이미 있는 파일입니다(덮어쓰지 않음): {f['rel']}", rel=f["rel"])
        if f["size"] == 0:
            U.append_chunk(p + U.PART_SUFFIX, b"")
            sha = sha256_file(p + U.PART_SUFFIX)
            if f["sha256_expected"] and f["sha256_expected"] != sha:
                raise unprocessable("SHA256_MISMATCH", f"sha256 이 다릅니다: {f['rel']}", rel=f["rel"])
            os.replace(p + U.PART_SUFFIX, p)
            f.update(done=True, sha256=sha)


# ---------------------------------------------------------------- 세션
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
    with ctx.engine.begin() as conn:
        # 사용자당 동시(OPEN) 업로드 수 — 사용자 행 잠금 대신 같은 트랜잭션에서 세고 바로 넣는다(advisory lock 으로 직렬화)
        conn.execute(select(func.pg_advisory_xact_lock(func.hashtext("esl-upload:" + principal.user_id))))
        n_open = conn.execute(select(func.count()).select_from(uploads).where(
            and_(uploads.c.user_id == principal.user_id, uploads.c.state == OPEN))).scalar_one()
        if n_open >= cfg.max_concurrent_per_user:
            raise DomainError("UPLOAD_LIMIT", f"진행 중인 업로드가 {n_open}개입니다(사용자당 최대 "
                              f"{cfg.max_concurrent_per_user}개) — 끝내거나 취소한 뒤 다시 시도하세요", status=429,
                              limit=cfg.max_concurrent_per_user)
        up_dir = U.make_upload_dir(root, user_seg, name_seg, U.utc_stamp())
        try:
            _prepare_files(up_dir, files)
            uid = str(uuid.uuid4())
            conn.execute(insert(uploads).values(
                id=uid, project_id=body.project_id, user_id=principal.user_id, username=principal.username,
                name=body.name.strip(), dir_path=up_dir, state=OPEN, files=files,
                total_bytes=sum(f["size"] for f in files)))
        except BaseException:
            U.move_to_backup(root, user_seg, up_dir)      # 만든 폴더는 지우지 않고 _backup 으로
            raise
        up = _row(conn, uid)
    return upload_out(up, cfg.chunk_bytes)


def add_files(ctx: AppContext, principal: Principal, upload_id: str, body) -> dict[str, Any]:
    require_config_ok(ctx)
    _upload_root(ctx)
    with ctx.engine.begin() as conn:
        up = _owned(conn, principal, upload_id, for_update=True)
        require_execute(principal, up["project_id"])
        _require_open(up)
        new = _norm_files(ctx, body.files, up["files"])
        _check_free(ctx, ctx.settings.storage.upload_root, sum(f["size"] for f in new))
        _prepare_files(up["dir_path"], new)
        files = list(up["files"]) + new
        conn.execute(update(uploads).where(uploads.c.id == upload_id).values(
            files=files, total_bytes=sum(f["size"] for f in files), updated_at=func.now(), result=None))
        up = _row(conn, upload_id)
    return upload_out(up, ctx.settings.upload.chunk_bytes)


def get_upload(ctx: AppContext, principal: Principal, upload_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        up = _owned(conn, principal, upload_id)
    return upload_out(up, ctx.settings.upload.chunk_bytes)


def list_uploads(ctx: AppContext, principal: Principal, state: str | None) -> list[dict[str, Any]]:
    q = select(uploads).where(uploads.c.user_id == principal.user_id).order_by(uploads.c.created_at.desc()).limit(50)
    if principal.token_project_id is not None:
        q = q.where(uploads.c.project_id == principal.token_project_id)
    if state:
        q = q.where(uploads.c.state == state)
    with ctx.engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(q).mappings()]
    return [upload_out(r, ctx.settings.upload.chunk_bytes) for r in rows]


def put_chunk(ctx: AppContext, principal: Principal, upload_id: str, index: int, offset: int,
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
        if f.get("done"):
            raise conflict("UPLOAD_FILE_DONE", f"이미 다 받은 파일입니다: {f['rel']}", received=int(f["size"]))
        p = U.target_path(up["dir_path"], _segs(f), create_parents=True)
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
            U.append_chunk(part, data)      # 사전할당·fsync 없이 append(재시작 시 received = .part 크기)
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
    return {"index": index, "received": received, "done": bool(f.get("done")), "sha256": f.get("sha256")}


# ---------------------------------------------------------------- complete 검사
def _rel_of(up_dir: str, p: str) -> str | None:
    if is_within(p, up_dir):
        return os.path.relpath(p, up_dir).replace(os.sep, "/")
    return None


def inspect_upload(ctx: AppContext, up: dict[str, Any]) -> dict[str, Any]:
    d = up["dir_path"]
    rels = [f["rel"] for f in up["files"]]
    problems: list[str] = []
    missing: list[str] = []
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
        try:
            incs = core_adapter.scan_includes(rad_path, depth, pmap)
        except core_adapter.CoreError as exc:
            incs = []
            problems.append(f"{exc.code}: {exc.message}")
        roots = ctx.settings.storage.input_roots
        for inc in incs:
            rel = _rel_of(d, inc)
            if not os.path.isfile(inc):
                missing.append(rel or inc)
                if rel is None:
                    problems.append(f"include 가 업로드 폴더 밖을 가리킵니다(올릴 수 없음): {inc}")
            elif rel is None and not any(is_within(os.path.realpath(inc), os.path.realpath(r)) for r in roots):
                problems.append(f"include 가 허용된 입력 루트 밖입니다: {inc}")
        if not missing:
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
    return {"ok": ok, "rad_path": rad_path, "results_dir": results_dir, "h3d_path": h3d_path, "parts": parts,
            "missing_includes": missing, "problems": problems}


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


def complete(ctx: AppContext, principal: Principal, upload_id: str) -> dict[str, Any]:
    require_config_ok(ctx)
    _upload_root(ctx)
    with ctx.engine.begin() as conn:
        up = _owned(conn, principal, upload_id, for_update=True)
        require_execute(principal, up["project_id"])
        if up["state"] == COMPLETED and up.get("result"):
            return {"upload_id": upload_id, "state": COMPLETED, **up["result"]}
        _require_open(up)
        pending = [f["rel"] for f in up["files"] if not f.get("done")]
        if pending:
            raise conflict("UPLOAD_INCOMPLETE", f"아직 다 받지 못한 파일이 {len(pending)}개 있습니다", pending=pending[:100])
        res = inspect_upload(ctx, up)
        vals: dict[str, Any] = {"result": res, "updated_at": func.now()}
        if res["ok"]:
            vals.update(state=COMPLETED, completed_at=func.now())
        conn.execute(update(uploads).where(uploads.c.id == upload_id).values(**vals))
        state = COMPLETED if res["ok"] else OPEN
    return {"upload_id": upload_id, "state": state, **res}


# ---------------------------------------------------------------- 취소·stale(삭제 없이 _backup 으로)
def _retire(ctx: AppContext, conn, up: dict[str, Any], state: str) -> dict[str, Any]:
    root = _upload_root(ctx)
    user_seg = U.user_segment(up["username"], up["user_id"])
    moved = None
    d = up["dir_path"]
    if os.path.lexists(d) and is_within(d, root) and not os.path.islink(d):
        moved = U.move_to_backup(root, user_seg, d)
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
        up = _retire(ctx, conn, up, CANCELED)
    return upload_out(up, ctx.settings.upload.chunk_bytes)


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
            _retire(ctx, conn, up, STALE)
            out.append(uid)
    return out
