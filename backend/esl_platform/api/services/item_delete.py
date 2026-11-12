"""목록 항목 삭제 서비스(계약 esl_item_delete.md §1·§2·§4·§6, v0.19.0): 강성 평가 스터디·비드 최적화·종합 분석·버전 비교.

공통 흐름(`delete_item`) — 하나의 DB 트랜잭션:
  ① 항목의 job(스터디는 그 verify_drops 의 job 까지) `FOR UPDATE`(id 순) → ② 항목 행 `FOR UPDATE` → ③ (스터디) verify_drops
  `FOR UPDATE` → ④ 차단 검사 → ⑤ 폴더를 `<esl_root>/_trash` 로 이동(core.trash) → ⑥ 자식 삭제(명시적 연쇄, ON DELETE CASCADE 없음)
  → ⑦ 항목 행 삭제 → ⑧ `deletions` 기록 → 커밋. 커밋·삭제 실패면 옮긴 폴더를 역순 `restore`.
잠금 순서는 jobs → 항목(api/services/jobs.py retry 와 같음). ①~⑦ 사이에 다른 트랜잭션이 새 job 을 넣으면 ⑥·⑦ 의 FK 위반(또는
교착 40P01)이 409 ITEM_BUSY — 남겨 둔 FK 가 최후 안전장치다.
영구 삭제는 이 모듈이 하지 않는다(워커 리퍼 worker/esl_worker/trash_purge.py).
삭제 흐름은 입력 폴더·SPDM·Case 원본·SCX 릴레이를 건드리지 않는다(릴레이 호출 없음).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

from ...core import trash
from ...core.auth import Principal
from ...core.db.tables import (
    analysis_runs,
    bead_does,
    comparisons,
    job_steps,
    jobs,
    notifications,
    opt_runs,
    scx_submissions,
    verify_drops,
)
from ...core.errors import DomainError, conflict, forbidden, not_found, unprocessable
from ...core.repositories import deletions as del_repo
from ...core.state_machine import TERMINAL
from ..context import AppContext
from .common import require_config_ok, require_execute

log = logging.getLogger("esl_platform.api")
audit = logging.getLogger("esl_platform.audit")

DROP_TERMINAL = ("DONE", "FAILED", "CANCELED")
SUBMISSION_OPEN = ("SUBMITTING", "SUBMITTED", "UNKNOWN")


@dataclass(frozen=True)
class _Spec:
    table: Any
    job_col: Any
    not_found_code: str
    not_found_msg: str


SPECS: dict[str, _Spec] = {
    "DOE": _Spec(bead_does, jobs.c.bead_doe_id, "DOE_NOT_FOUND", "강성 평가 스터디를 찾을 수 없습니다"),
    "OPT": _Spec(opt_runs, jobs.c.opt_run_id, "OPT_RUN_NOT_FOUND", "최적화 실행을 찾을 수 없습니다"),
    "ANALYSIS": _Spec(analysis_runs, jobs.c.analysis_id, "ANALYSIS_NOT_FOUND", "분석을 찾을 수 없습니다"),
    "COMPARE": _Spec(comparisons, jobs.c.comparison_id, "COMPARISON_NOT_FOUND", "비교를 찾을 수 없습니다"),
}


# ---------------------------------------------------------------- 공통 도우미
def _enabled(ctx: AppContext) -> bool:
    return bool(ctx.settings.item_delete.enabled)


def require_enabled(ctx: AppContext) -> None:
    if not _enabled(ctx):
        raise DomainError("ITEM_DELETE_DISABLED", "목록 항목 삭제가 설정(item_delete.enabled)으로 꺼져 있습니다", status=503)


def title_of(kind: str, row: dict[str, Any]) -> str:
    t = row.get("title")
    return str(t) if t else str(row["id"])[:8]


def is_permitted(principal: Principal | None, row: dict[str, Any]) -> bool:
    """§4: 실행 권한 + (등록자 또는 전역 관리자)."""
    if principal is None:
        return False
    return principal.can_execute(row["project_id"]) and (principal.is_global_admin
                                                         or row.get("created_by") == principal.user_id)


def _require_permitted(principal: Principal, row: dict[str, Any]) -> None:
    require_execute(principal, row["project_id"])
    if not (principal.is_global_admin or row.get("created_by") == principal.user_id):
        raise forbidden("등록자 또는 전역 관리자만 삭제할 수 있습니다", code="NOT_ITEM_OWNER")


def _load(conn: Connection, kind: str, item_id: str, *, for_update: bool = False) -> dict[str, Any]:
    sp = SPECS[kind]
    q = select(sp.table).where(sp.table.c.id == item_id)
    if for_update:
        q = q.with_for_update()
    r = conn.execute(q).first()
    if r is not None:
        return dict(r._mapping)
    if del_repo.get_by_item(conn, kind, item_id) is not None:
        raise not_found("ITEM_DELETED", "이미 삭제된 항목입니다")
    raise not_found(sp.not_found_code, sp.not_found_msg)


def _block(code: str, message: str, *, job: dict[str, Any] | None = None, verify_drop_id: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "job_id": job["id"] if job else None,
            "job_type": job["job_type"] if job else None, "state": job["state"] if job else None,
            "verify_drop_id": verify_drop_id}


def blocked_map(conn: Connection, kind: str, ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """§2 차단 사유(항목별 DeleteBlockOut 사전 목록). 쿼리 수는 항목 수와 무관(종류당 최대 4회)."""
    out: dict[str, list[dict[str, Any]]] = {i: [] for i in ids}
    if not ids:
        return out
    sp = SPECS[kind]
    drops: list[Any] = []
    if kind == "DOE":
        drops = conn.execute(select(verify_drops.c.id, verify_drops.c.bead_doe_id, verify_drops.c.phase)
                             .where(verify_drops.c.bead_doe_id.in_(ids)).order_by(verify_drops.c.created_at,
                                                                                   verify_drops.c.id)).all()
    drop_study = {d.id: d.bead_doe_id for d in drops}
    cond = sp.job_col.in_(ids)
    if drop_study:
        cond = or_(cond, jobs.c.verify_drop_id.in_(list(drop_study)))
    rows = conn.execute(select(jobs).where(and_(cond, jobs.c.state.notin_(list(TERMINAL))))
                        .order_by(jobs.c.created_at, jobs.c.id)).all()
    for r in rows:
        j = dict(r._mapping)
        if kind == "DOE" and j.get("verify_drop_id"):
            sid = drop_study.get(j["verify_drop_id"])
            if sid in out:
                out[sid].append(_block("VERIFY_JOB_ACTIVE", "검증 낙하의 작업이 진행 중입니다 — 먼저 취소·포기하세요", job=j,
                                       verify_drop_id=j["verify_drop_id"]))
            continue
        sid = j.get({"DOE": "bead_doe_id", "OPT": "opt_run_id", "ANALYSIS": "analysis_id", "COMPARE": "comparison_id"}[kind])
        if sid in out:
            out[sid].append(_block("JOB_ACTIVE", "대기 중이거나 실행 중인 작업이 있습니다 — 끝나거나 취소된 뒤에 삭제하세요", job=j))
    if kind == "DOE":
        for d in drops:
            if d.phase not in DROP_TERMINAL and d.bead_doe_id in out:
                out[d.bead_doe_id].append(_block("VERIFY_DROP_ACTIVE", "검증 낙하가 진행 중입니다 — 먼저 취소·포기하세요",
                                                 verify_drop_id=d.id))
        if drop_study:
            subs = conn.execute(select(scx_submissions.c.verify_drop_id).where(and_(
                scx_submissions.c.verify_drop_id.in_(list(drop_study)),
                scx_submissions.c.state.in_(SUBMISSION_OPEN))).order_by(scx_submissions.c.request_id)).all()
            seen: set[str] = set()
            for s in subs:
                if s.verify_drop_id in seen:
                    continue
                seen.add(s.verify_drop_id)
                out[drop_study[s.verify_drop_id]].append(_block(
                    "SCX_SUBMISSION_ACTIVE", "SCX 제출이 진행 중이거나 확인되지 않았습니다 — 검증 낙하를 먼저 취소·포기하세요",
                    verify_drop_id=s.verify_drop_id))
    return out


def blocked_summary(blocks: list[dict[str, Any]]) -> str | None:
    if not blocks:
        return None
    msg = blocks[0]["message"]
    return msg if len(blocks) == 1 else f"{msg} (외 {len(blocks) - 1}건)"


def flags(ctx: AppContext, conn: Connection, principal: Principal | None, kind: str,
          rows: list[dict[str, Any]]) -> dict[str, tuple[bool, str | None]]:
    """목록·상세 Out 의 (can_delete, delete_blocked) — 행마다 job 상태 집계는 종류당 한 묶음 쿼리로(§4)."""
    on = _enabled(ctx)
    bm = blocked_map(conn, kind, [r["id"] for r in rows])
    return {r["id"]: (on and is_permitted(principal, r), blocked_summary(bm.get(r["id"], []))) for r in rows}


def apply_flags(out: dict[str, Any], fl: dict[str, tuple[bool, str | None]] | None, item_id: str) -> dict[str, Any]:
    can, blk = (fl or {}).get(item_id, (False, None))
    out["can_delete"] = bool(can)
    out["delete_blocked"] = blk
    return out


def annotate(ctx: AppContext, conn: Connection, principal: Principal | None, kind: str,
             pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
    """(행, Out dict) 목록에 can_delete·delete_blocked 를 한 번에 채운다."""
    fl = flags(ctx, conn, principal, kind, [r for r, _ in pairs])
    for r, o in pairs:
        apply_flags(o, fl, r["id"])


# ---------------------------------------------------------------- 폴더 목록
def _dir_specs(kind: str, row: dict[str, Any], drops: list[dict[str, Any]]) -> list[tuple[str, str, str | None]]:
    """지울 폴더 [(trash kind, id, dir_rel)] — 스터디는 `_doe/<id>` 다음에 각 `_verify/<vid>` 순서."""
    specs = [(kind, row["id"], row.get("dir_rel"))]
    if kind == "DOE":
        specs += [("VERIFY", d["id"], d.get("dir_rel")) for d in drops]
    return specs


def _drops(conn: Connection, kind: str, item_id: str, *, for_update: bool = False) -> list[dict[str, Any]]:
    if kind != "DOE":
        return []
    q = select(verify_drops).where(verify_drops.c.bead_doe_id == item_id).order_by(verify_drops.c.created_at,
                                                                                    verify_drops.c.id)
    if for_update:
        q = q.with_for_update()
    return [dict(r._mapping) for r in conn.execute(q).all()]


def _path_unsafe(exc: trash.PathUnsafe) -> DomainError:
    return unprocessable("PATH_UNSAFE", str(exc) or "경로가 안전하지 않습니다")


def _validated_dirs(ctx: AppContext, specs: list[tuple[str, str, str | None]]) -> list[tuple[str, str, str, str]]:
    """모든 폴더 경로를 이동 전에 검사 → [(kind, id, rel, 절대경로)]. 하나라도 위험하면 422 PATH_UNSAFE(아무것도 옮기지 않음)."""
    res = []
    for k, i, rel in specs:
        try:
            d = trash.item_dir(ctx.settings, k, i, rel)
        except trash.PathUnsafe as exc:
            raise _path_unsafe(exc) from None
        res.append((k, i, f"{trash.KIND_DIR[k]}/{i}", d))
    return res


# ---------------------------------------------------------------- GET delete-check
def delete_check(ctx: AppContext, principal: Principal, kind: str, item_id: str) -> dict[str, Any]:
    require_config_ok(ctx)
    require_enabled(ctx)
    with ctx.engine.connect() as conn:
        row = _load(conn, kind, item_id)
        _require_permitted(principal, row)
        drops = _drops(conn, kind, item_id)
        blocks = blocked_map(conn, kind, [item_id])[item_id]
        sp = SPECS[kind]
        if kind == "DOE":
            n_jobs = int(conn.execute(select(func.count()).select_from(jobs).where(or_(
                sp.job_col == item_id, jobs.c.verify_drop_id.in_([d["id"] for d in drops] or [""])))).scalar_one())
        else:
            n_jobs = int(conn.execute(select(func.count()).select_from(jobs).where(sp.job_col == item_id)).scalar_one())
        n_opt = int(conn.execute(select(func.count()).select_from(opt_runs).where(opt_runs.c.analysis_id == item_id))
                    .scalar_one()) if kind == "ANALYSIS" else 0
        folders = []
        for _k, _i, rel, d in _validated_dirs(ctx, _dir_specs(kind, row, drops)):
            folders.append({"rel": rel, "exists": os.path.isdir(d)})
        return {"kind": kind, "id": item_id, "title": title_of(kind, row), "can_delete": not blocks, "blocked": blocks,
                "n_jobs": n_jobs, "n_verify_drops": len(drops), "n_opt_unlinked": n_opt, "folders": folders}


# ---------------------------------------------------------------- DELETE
def _lock_jobs(conn: Connection, kind: str, item_id: str) -> None:
    """① 항목의 job(스터디는 verify_drops 의 job 까지)을 id 순으로 FOR UPDATE — 교착 방지."""
    sp = SPECS[kind]
    cond = sp.job_col == item_id
    if kind == "DOE":
        drop_ids = [r.id for r in conn.execute(select(verify_drops.c.id).where(verify_drops.c.bead_doe_id == item_id)).all()]
        if drop_ids:
            cond = or_(cond, jobs.c.verify_drop_id.in_(drop_ids))
    conn.execute(select(jobs.c.id).where(cond).order_by(jobs.c.id).with_for_update()).all()


def _job_ids(conn: Connection, kind: str, item_id: str, drops: list[dict[str, Any]]) -> list[str]:
    sp = SPECS[kind]
    cond = sp.job_col == item_id
    if drops:
        cond = or_(cond, jobs.c.verify_drop_id.in_([d["id"] for d in drops]))
    return [r.id for r in conn.execute(select(jobs.c.id).where(cond).order_by(jobs.c.created_at, jobs.c.id)).all()]


def _sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def _is_race(exc: BaseException) -> bool:
    """FK 위반(23503)·교착(40P01)·직렬화 실패(40001) = 동시 생성과 경합."""
    return isinstance(exc, (IntegrityError, DBAPIError)) and _sqlstate(exc) in ("23503", "40P01", "40001")


def _busy_details(ctx: AppContext, kind: str, item_id: str) -> list[dict[str, Any]]:
    try:
        with ctx.engine.connect() as conn:
            return blocked_map(conn, kind, [item_id])[item_id]
    except Exception:  # noqa: BLE001 — 진단용
        return []


def _busy(blocks: list[dict[str, Any]], message: str = "삭제할 수 없습니다 — 진행 중인 작업이 있습니다") -> DomainError:
    return conflict("ITEM_BUSY", blocks[0]["message"] if blocks else message, blocked=blocks)


def delete_item(ctx: AppContext, principal: Principal, kind: str, item_id: str) -> dict[str, Any]:
    require_config_ok(ctx)
    require_enabled(ctx)
    moves: list[trash.TrashMove] = []
    result: dict[str, Any] = {}
    try:
        with ctx.engine.begin() as conn:
            _lock_jobs(conn, kind, item_id)                                           # ①
            row = _load(conn, kind, item_id, for_update=True)                         # ②
            _require_permitted(principal, row)
            drops = _drops(conn, kind, item_id, for_update=True)                      # ③
            blocks = blocked_map(conn, kind, [item_id])[item_id]                      # ④
            if blocks:
                raise _busy(blocks)
            specs = _dir_specs(kind, row, drops)
            _validated_dirs(ctx, specs)                                               # 이동 전에 전부 검사
            for k, i, rel in specs:                                                   # ⑤ 폴더 → 휴지통
                try:
                    mv = trash.move_to_trash(ctx.settings, k, i, rel)
                except trash.PathUnsafe as exc:
                    raise _path_unsafe(exc) from None
                except trash.FileLocked as exc:
                    log.warning("삭제 중 폴더 잠김 kind=%s id=%s", kind, item_id)
                    raise conflict("FILE_LOCKED", "폴더가 열려 있어 옮기지 못했습니다(보고서·3D 보기 창을 닫고 다시 시도하세요)",
                                   path=exc.path) from None
                if mv is not None:
                    moves.append(mv)
            job_ids = _job_ids(conn, kind, item_id, drops)                            # ⑥ 자식 삭제
            n_unlinked = 0
            if job_ids:
                conn.execute(delete(notifications).where(notifications.c.job_id.in_(job_ids)))
                conn.execute(delete(job_steps).where(job_steps.c.job_id.in_(job_ids)))
                conn.execute(delete(jobs).where(jobs.c.id.in_(job_ids)))
            if kind == "DOE" and drops:
                drop_ids = [d["id"] for d in drops]
                conn.execute(delete(scx_submissions).where(scx_submissions.c.verify_drop_id.in_(drop_ids)))
                conn.execute(delete(verify_drops).where(verify_drops.c.id.in_(drop_ids)))
            if kind == "ANALYSIS":
                n_unlinked = conn.execute(update(opt_runs).where(opt_runs.c.analysis_id == item_id)
                                          .values(analysis_id=None)).rowcount
            sp = SPECS[kind]
            conn.execute(delete(sp.table).where(sp.table.c.id == item_id))             # ⑦
            did = str(uuid.uuid4())                                                    # ⑧
            jmax = int(ctx.settings.item_delete.summary_job_ids_max)
            summary: dict[str, Any] = {"n_jobs": len(job_ids), "n_verify_drops": len(drops), "n_opt_unlinked": n_unlinked,
                                       "job_ids": job_ids[:jmax]}
            for key in ("scenario", "phase"):
                if row.get(key) is not None:
                    summary[key] = row[key]
            purge = "PENDING" if moves else "ABSENT"
            del_repo.insert_deletion(
                conn, id=did, kind=kind, item_id=item_id, project_id=row["project_id"], title=row.get("title"),
                item_created_by_name=row.get("created_by_name"), deleted_by=principal.user_id,
                deleted_by_name=principal.display_name, summary=summary,
                dirs=[{"rel": f"{trash.KIND_DIR[m.kind]}/{m.item_id}", "trash_name": m.trash_name} for m in moves],
                purge_state=purge)
            result = {"deleted": True, "kind": kind, "id": item_id, "purge": purge, "deletion_id": did,
                      "n_jobs": len(job_ids), "n_verify_drops": len(drops), "n_opt_unlinked": int(n_unlinked)}
        # with 를 나오면 커밋 완료
    except BaseException as exc:
        for mv in reversed(moves):
            if not trash.restore(ctx.settings, mv):
                log.error("삭제 롤백 중 폴더 되돌리기 실패 — 휴지통 항목에 DB 행이 남아 있어 리퍼가 되돌립니다: %s", mv.trash_name)
        if _is_race(exc):
            raise _busy(_busy_details(ctx, kind, item_id), "동시에 만들어진 작업이 있어 삭제하지 못했습니다 — 다시 시도하세요") from None
        raise
    if kind == "DOE":
        from . import doe_select

        doe_select.reset_caches()
    audit.info("DELETE kind=%s id=%s project=%s by=%s jobs=%d dirs=%s", kind, item_id, row["project_id"], principal.user_id,
               result["n_jobs"], [f"{trash.KIND_DIR[m.kind]}/{m.item_id}" for m in moves])
    return result


__all__ = ["SPECS", "delete_check", "delete_item", "flags", "apply_flags", "annotate", "blocked_map", "blocked_summary",
           "is_permitted", "require_enabled"]
