"""휴지통 영구 삭제 리퍼(계약 esl_item_delete.md §3, v0.19.0): `<esl_root>/_trash/*` 를 `item_delete.purge_interval_s` 마다 정리.

- A. 삭제 기록 주도: `deletions.purge_state IN (PENDING, FAILED)` 이고 `purge_attempts < item_delete.purge_max_attempts` 인 행의
  dirs[] 를 `core.trash.purge_entry` 로 영구 삭제 → PURGED, 하나라도 실패면 FAILED(`purge_attempts`+1, `purge_error` ≤ 200자 마스킹 —
  다음 주기에 재시도, 상한에 닿으면 재시도 중지 + check.py WARN).
- B. 휴지통 직접 확인: 삭제 기록이 없는 항목 — 이름 형식이 다르면 건드리지 않고 경고(한 번만), 그 kind·id 의 DB 항목 행이 **있으면**
  지우지 않는다(롤백 잔여): 원래 자리가 비었으면 `core.trash.restore`, 아니면 경고. 행이 없으면 `purge_entry`.
- 동시 삭제와의 경합: 삭제 서비스는 폴더를 옮기기 전에 항목 행(스터디는 verify_drops 행도)을 `FOR UPDATE` 로 잠그므로, 리퍼는 행을
  `FOR UPDATE NOWAIT` 로 확인해 잠겨 있으면(삭제 진행 중) 이번 주기엔 건드리지 않는다.
- 링크·junction 은 링크 객체만 지우고 대상은 따라가지 않는다(purge_entry). 입력·SPDM 폴더는 대상이 아니다(trash 경로 검사).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from esl_platform.core import trash
from esl_platform.core.config import Settings
from esl_platform.core.db import tables
from esl_platform.core.repositories import deletions as del_repo
from esl_platform.core.uploads import is_link_like

log = logging.getLogger("esl_worker.trash_purge")

_TABLES = {"DOE": tables.bead_does, "OPT": tables.opt_runs, "ANALYSIS": tables.analysis_runs,
           "COMPARE": tables.comparisons, "VERIFY": tables.verify_drops}
_LOCK_NOT_AVAILABLE = "55P03"
_WARNED: set[str] = set()          # 이름 형식이 다른 항목은 프로세스당 한 번만 경고


@dataclass
class PurgeSummary:
    purged: int = 0          # 영구 삭제 끝난 휴지통 항목 수
    failed: int = 0          # 영구 삭제 실패(FAILED 기록·재시도 대기)
    restored: int = 0        # DB 행이 있어 원래 자리로 되돌린 항목 수
    skipped: int = 0         # 건드리지 않음(이름 형식·삭제 진행 중·되돌릴 수 없음 등)


def _sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def _row_state(engine: Engine, kind: str, item_id: str) -> bool | None:
    """True = DB 행 있음, False = 없음(확정), None = 삭제 트랜잭션이 잠그고 있음(이번엔 건드리지 않음)."""
    t = _TABLES[kind]
    try:
        with engine.begin() as conn:
            return conn.execute(select(t.c.id).where(t.c.id == item_id).with_for_update(nowait=True)).first() is not None
    except DBAPIError as exc:
        if _sqlstate(exc) == _LOCK_NOT_AVAILABLE:
            return None
        raise


def _warn_once(name: str, why: str) -> None:
    if name not in _WARNED:
        _WARNED.add(name)
        log.warning("휴지통 항목을 건드리지 않음(%s): %s", why, name)


def _restore_leftover(settings: Settings, kind: str, item_id: str, name: str) -> bool:
    try:
        src = trash.item_dir(settings, kind, item_id)
    except trash.PathUnsafe as exc:
        log.warning("휴지통 롤백 잔여를 되돌릴 수 없음(경로 검사 실패 — %s): %s", exc, name)
        return False
    mv = trash.TrashMove(src=src, dst=os.path.join(trash.trash_root(settings), name), kind=kind, item_id=item_id,
                         trash_name=name)
    ok = trash.restore(settings, mv)
    if ok:
        log.warning("DB 행이 있는 휴지통 항목을 원래 자리로 되돌림: %s", name)
    else:
        log.warning("DB 행이 있는 휴지통 항목 — 되돌리지 못함(원래 자리가 차 있거나 잠김, 지우지 않음): %s", name)
    return ok


def _purge_deletion(settings: Settings, engine: Engine, d: dict, out: PurgeSummary) -> None:
    """삭제 기록 1건의 dirs[] 전부 영구 삭제 → PURGED/FAILED 기록."""
    err: str | None = None
    n_ok = 0
    for ent in d.get("dirs") or []:
        name = ent.get("trash_name") if isinstance(ent, dict) else None
        parsed = trash.parse_trash_name(name or "")
        if parsed is None:
            err = err or "삭제 기록의 휴지통 이름 형식이 다릅니다"
            continue
        if _row_state(engine, parsed[1], parsed[2]) is not False:       # 행이 있거나(비정상) 잠김 → 이번엔 지우지 않음
            err = err or "DB 항목 행이 있어 지우지 않았습니다"
            continue
        res = trash.purge_entry(settings, name)
        if res.ok:
            n_ok += 1
            log.info("휴지통 영구 삭제: %s (파일 %d, 링크 %d)", name, res.removed_files, res.skipped_links)
        else:
            err = err or (res.error or "영구 삭제 실패")
    with engine.begin() as conn:
        if err is None:
            del_repo.mark_purge(conn, d["id"], "PURGED")
            out.purged += n_ok
        else:
            del_repo.mark_purge(conn, d["id"], "FAILED", error=err)
            out.failed += 1
            out.purged += n_ok
            log.warning("휴지통 영구 삭제 실패(시도 %d회째): %s — %s", int(d.get("purge_attempts") or 0) + 1, d["id"], err)


def purge_once(settings: Settings, engine: Engine) -> PurgeSummary:
    """리퍼 1주기. 한 주기에 다루는 휴지통 항목은 최대 item_delete.purge_batch 개."""
    out = PurgeSummary()
    cfg = settings.item_delete
    troot = trash.trash_root(settings)
    if not os.path.isdir(troot) and not _has_pending(engine, cfg.purge_max_attempts):
        return out
    if is_link_like(troot):
        log.warning("휴지통 폴더가 링크·junction 이라 리퍼를 건너뜀")
        return out
    budget = int(cfg.purge_batch)
    handled: set[str] = set()
    with engine.connect() as conn:
        pend = del_repo.list_pending(conn, max_attempts=cfg.purge_max_attempts, limit=budget)
    for d in pend:                                                  # A. 삭제 기록 주도
        n = max(1, len(d.get("dirs") or []))
        if budget <= 0 or (budget < n and handled):
            break
        budget -= n
        handled.update(e.get("trash_name") for e in d.get("dirs") or [] if isinstance(e, dict))
        _purge_deletion(settings, engine, d, out)
    if budget <= 0 or not os.path.isdir(troot):
        return out
    try:
        with os.scandir(troot) as it:
            names = sorted(e.name for e in it)
    except OSError as exc:
        log.warning("휴지통 폴더를 읽지 못함(%s)", type(exc).__name__)
        return out
    for name in names:                                              # B. 삭제 기록 없는 항목
        if budget <= 0:
            break
        if name in handled:
            continue
        parsed = trash.parse_trash_name(name)
        if parsed is None:
            out.skipped += 1
            _warn_once(name, "이름 형식이 다름")
            continue
        _stamp, kind, item_id = parsed
        state = _row_state(engine, kind, item_id)
        if state is None:                                           # 삭제 진행 중
            out.skipped += 1
            continue
        budget -= 1
        if state:                                                   # 롤백 잔여 → 되돌림
            if _restore_leftover(settings, kind, item_id, name):
                out.restored += 1
            else:
                out.skipped += 1
            continue
        with engine.connect() as conn:
            dl = del_repo.find_by_trash_name(conn, name)
        if dl is not None and dl["purge_state"] in ("PENDING", "FAILED"):
            out.skipped += 1                                        # A 의 몫(재시도 상한에 닿아 멈춘 항목은 그대로 둠)
            continue
        res = trash.purge_entry(settings, name)
        if res.ok:
            out.purged += 1
            log.info("휴지통 영구 삭제(삭제 기록 없음): %s (파일 %d, 링크 %d)", name, res.removed_files, res.skipped_links)
        else:
            out.failed += 1
            log.warning("휴지통 영구 삭제 실패(삭제 기록 없음): %s — %s", name, res.error)
    return out


def _has_pending(engine: Engine, max_attempts: int) -> bool:
    try:
        with engine.connect() as conn:
            return bool(del_repo.list_pending(conn, max_attempts=max_attempts, limit=1))
    except Exception:  # noqa: BLE001
        return False
