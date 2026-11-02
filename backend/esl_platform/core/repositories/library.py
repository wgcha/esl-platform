"""라이브러리 항목·종합분석·설계 버전 비교 저장소(계약 esl_p2_library.md §11·§12). 호출자가 트랜잭션을 연다."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.engine import Connection

from ..db.tables import analysis_runs, comparisons, library_entries
from . import row_dict
from .cases import VersionConflict

# 목록 필터: 쿼리 키 → (JSONB 열, 키)
ENTRY_FILTERS = {"model": ("model", "name"), "inch": ("model", "inch"), "drop_type": ("scene", "drop_type"),
                 "drop_class": ("scene", "drop_class"), "orient": ("scene", "orient"),
                 "scenario": ("scene", "scenario"), "verdict": ("quality", "verdict")}


# ---------------------------------------------------------------- library_entries
def insert_entry(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(insert(library_entries).values(**values))
    return get_entry(conn, values["id"])


def get_entry(conn: Connection, eid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(library_entries).where(library_entries.c.id == eid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def active_entry_for_run(conn: Connection, esl_run_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(library_entries).where(and_(
        library_entries.c.esl_run_id == esl_run_id, library_entries.c.status == "ACTIVE"))).first())


def list_entries(conn: Connection, *, project_id: str | None = None, status: str | None = None,
                 ids: list[str] | None = None, **filters: list[str] | str | None) -> list[dict[str, Any]]:
    q = select(library_entries)
    conds = []
    if project_id:
        conds.append(library_entries.c.project_id == project_id)
    if status:
        conds.append(library_entries.c.status == status)
    if ids is not None:
        conds.append(library_entries.c.id.in_(list(ids)))
    for key, vals in filters.items():
        if vals is None or key not in ENTRY_FILTERS:
            continue
        vals = [vals] if isinstance(vals, str) else list(vals)
        if not vals:
            continue
        col, k = ENTRY_FILTERS[key]
        if key == "verdict":
            # 계약 esl_disp_primary.md §7: LEGACY = quality.scheme 없음, 그 외 = quality.status(없으면 quality.verdict)
            qc = library_entries.c.quality
            st = func.upper(func.coalesce(qc["status"].astext, qc["verdict"].astext))
            conds.append(or_(*[(qc["scheme"].astext.is_(None) if str(v).upper() == "LEGACY" else st == str(v).upper())
                               for v in vals]))
            continue
        expr = func.lower(library_entries.c[col][k].astext)
        conds.append(or_(*[expr == str(v).lower() for v in vals]))
    if conds:
        q = q.where(and_(*conds))
    return [row_dict(r) for r in conn.execute(q.order_by(library_entries.c.registered_at.desc(),
                                                         library_entries.c.id)).all()]


def active_stats_for_cases(conn: Connection, case_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Case 목록용 등록 현황 일괄 조회(#49, 2쿼리 고정): {case_id: {count, latest}} — ACTIVE 항목 수와 가장 최근 등록 항목
    (latest = {id, quality, registered_at}). 항목 없는 Case 는 빠진다."""
    ids = sorted({i for i in case_ids if i})
    if not ids:
        return {}
    active = and_(library_entries.c.case_id.in_(ids), library_entries.c.status == "ACTIVE")
    out: dict[str, dict[str, Any]] = {
        cid: {"count": int(n), "latest": None}
        for cid, n in conn.execute(select(library_entries.c.case_id, func.count()).where(active)
                                   .group_by(library_entries.c.case_id)).all()}
    rn = func.row_number().over(partition_by=library_entries.c.case_id,
                                order_by=(library_entries.c.registered_at.desc(), library_entries.c.id)).label("rn")
    sub = (select(library_entries.c.case_id, library_entries.c.id, library_entries.c.quality,
                  library_entries.c.registered_at, rn).where(active).subquery())
    q = select(sub.c.case_id, sub.c.id, sub.c.quality, sub.c.registered_at).where(sub.c.rn == 1)
    for cid, eid, quality, at in conn.execute(q).all():
        out[cid]["latest"] = {"id": eid, "quality": quality, "registered_at": at}
    return out


def update_entry(conn: Connection, eid: str, version: int | None, **values: Any) -> dict[str, Any]:
    cond = library_entries.c.id == eid
    if version is not None:
        cond = and_(cond, library_entries.c.version == int(version))
    r = conn.execute(update(library_entries).where(cond).values(updated_at=func.now(),
                                                                version=library_entries.c.version + 1, **values))
    if r.rowcount != 1:
        raise VersionConflict(eid)
    return get_entry(conn, eid)


# ---------------------------------------------------------------- analysis_runs
def insert_analysis(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(insert(analysis_runs).values(**values))
    return get_analysis(conn, values["id"])


def get_analysis(conn: Connection, aid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(analysis_runs).where(analysis_runs.c.id == aid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def list_analyses(conn: Connection, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    q = select(analysis_runs)
    if project_id:
        q = q.where(analysis_runs.c.project_id == project_id)
    return [row_dict(r) for r in conn.execute(q.order_by(analysis_runs.c.created_at.desc()).limit(limit)).all()]


def update_analysis(conn: Connection, aid: str, **values: Any) -> dict[str, Any]:
    conn.execute(update(analysis_runs).where(analysis_runs.c.id == aid).values(updated_at=func.now(), **values))
    return get_analysis(conn, aid)


# ---------------------------------------------------------------- comparisons (§12.2)
def insert_comparison(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(insert(comparisons).values(**values))
    return get_comparison(conn, values["id"])


def get_comparison(conn: Connection, cid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(comparisons).where(comparisons.c.id == cid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def list_comparisons(conn: Connection, project_id: str | None = None, model: str | None = None,
                     limit: int = 200) -> list[dict[str, Any]]:
    q = select(comparisons)
    if project_id:
        q = q.where(comparisons.c.project_id == project_id)
    if model:
        q = q.where(func.lower(comparisons.c.model) == model.lower())
    return [row_dict(r) for r in conn.execute(q.order_by(comparisons.c.created_at.desc()).limit(limit)).all()]


def update_comparison(conn: Connection, cid: str, **values: Any) -> dict[str, Any]:
    conn.execute(update(comparisons).where(comparisons.c.id == cid).values(updated_at=func.now(), **values))
    return get_comparison(conn, cid)
