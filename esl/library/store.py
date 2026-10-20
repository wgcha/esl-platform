"""파일 기반 라이브러리 저장소 (이 단계 한정; DB 연동은 플랫폼 단계).

배치::

  <root>/library/index.jsonl              추가 전용 이벤트 로그 (register / retire)
  <root>/library/entries/<entry_id>/      entry.json, summary.npz, raw.npz (등록 후 수정 불가)
  <root>/_analysis/<analysis_id>/         analysis.json, mapped_loads.npz, envelope.csv, representatives.csv,
                                          opt/(덱), report.html  — 덮어쓰기 전 _backup/<ts>/ 로 이동
  <root>/_compare/<compare_id>/           compare.json, report.html (설계 버전 비교, §12.2)

색인 이벤트::

  {"event":"register", "at":..., "entry": {entry_id, status, 모델·씬·품질 요약, mesh_sha256, case_dir, run_id, path}}
  {"event":"retire",   "at":..., "entry_id":..., "reason":..., "superseded_by":...}
"""
from __future__ import annotations

import json
import os

from esl.errors import EslError
from esl.library import _util as U
from esl.library import entry as en

LIB, INDEX, ENTRIES, ANALYSIS, COMPARE = "library", "index.jsonl", "entries", "_analysis", "_compare"
FILTER_KEYS = ("entry_id", "product", "model", "inch", "version", "project", "scenario", "drop_type", "drop_class",
               "orient", "scene", "verdict", "status", "mesh_sha256", "variant", "round")


def index_path(root: str) -> str:
    return os.path.join(root, LIB, INDEX)


def entry_dir(root: str, entry_id: str) -> str:
    return os.path.join(root, LIB, ENTRIES, entry_id)


def analysis_dir(root: str, analysis_id: str) -> str:
    return os.path.join(root, ANALYSIS, analysis_id)


def compare_dir(root: str, compare_id: str) -> str:
    return os.path.join(root, COMPARE, compare_id)


def brief(meta: dict) -> dict:
    s = meta.get("scene") or {}
    m = meta.get("model") or {}
    q = meta.get("quality") or {}
    return {"entry_id": meta["entry_id"], "status": meta.get("status", "active"),
            "registered_at": meta.get("registered_at"), "registered_by": meta.get("registered_by"),
            "product": m.get("product"), "model": m.get("product"), "inch": m.get("inch"),
            "version": m.get("version"), "project": m.get("project"), "scenario": s.get("scenario"),
            "seq": s.get("seq"), "drop_type": s.get("drop_type"), "drop_class": s.get("drop_class"),
            "orient": s.get("orient"), "scene": s.get("scene"), "round": s.get("round"), "variant": s.get("variant"),
            "verdict": q.get("verdict"), "confirmed_fail": q.get("confirmed_fail"),
            "hotspot1_rel_err": q.get("hotspot1_rel_err"), "mesh_sha256": meta.get("mesh_sha256"),
            "case_dir": (meta.get("source") or {}).get("case_dir"), "run_id": (meta.get("source") or {}).get("run_id"),
            "path": f"{LIB}/{ENTRIES}/{meta['entry_id']}"}


def read_index(root: str) -> dict:
    """entry_id → 현재 상태 레코드(이벤트 접기)."""
    p = index_path(root)
    out: dict = {}
    if not os.path.isfile(p):
        return out
    with open(p, "r", encoding="utf-8") as fh:
        for no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                raise EslError("INDEX_CORRUPT", f"{p}:{no} JSON 아님") from None
            if ev.get("event") == "register":
                out[ev["entry"]["entry_id"]] = dict(ev["entry"])
            elif ev.get("event") == "retire":
                r = out.get(ev["entry_id"])
                if r is not None:
                    r.update(status="retired", retired_at=ev.get("at"), retire_reason=ev.get("reason"),
                             superseded_by=ev.get("superseded_by"))
    return out


def _append(root: str, ev: dict, w: U.Writer) -> None:
    p = index_path(root)
    w.makedirs(os.path.dirname(p))
    with open(w.guard(p), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(U.jsonable(ev), ensure_ascii=False) + "\n")


def register(root: str, entry: en.LibraryEntry, w: U.Writer, supersedes: str | None = None,
             reason: str | None = None) -> dict:
    idx = read_index(root)
    eid = entry.entry_id
    if eid in idx:
        raise EslError("ENTRY_EXISTS", f"이미 등록된 항목 {eid} (상태 {idx[eid]['status']}) — 같은 ESL 결과의 재등록 불가")
    if supersedes is not None:
        old = idx.get(supersedes)
        if old is None:
            raise EslError("ENTRY_NOT_FOUND", f"--supersedes {supersedes}: 색인에 없음")
        if old["status"] == "retired":
            raise EslError("INPUT_INVALID", f"{supersedes} 는 이미 retired")
        entry.meta["supersedes"] = supersedes
    en.save(entry, entry_dir(root, eid), w)
    b = brief(entry.meta)
    _append(root, {"event": "register", "at": U.utcnow(), "entry": b}, w)
    if supersedes is not None:
        _append(root, {"event": "retire", "at": U.utcnow(), "entry_id": supersedes,
                       "reason": reason or "정정(새 등록으로 대체)", "superseded_by": eid}, w)
    return b


def retire(root: str, entry_id: str, reason: str, w: U.Writer) -> None:
    idx = read_index(root)
    if entry_id not in idx:
        raise EslError("ENTRY_NOT_FOUND", f"색인에 없음: {entry_id}")
    _append(root, {"event": "retire", "at": U.utcnow(), "entry_id": entry_id, "reason": reason,
                   "superseded_by": None}, w)


def parse_filters(items) -> dict:
    """['drop_type=Corner,Edge', 'inch=75'] → {key: [값...]} (대소문자 무시 비교)."""
    out: dict = {}
    for it in items or []:
        if "=" not in it:
            raise EslError("INPUT_INVALID", f"--filter 는 key=값[,값] (값 {it!r})")
        k, v = it.split("=", 1)
        k = k.strip()
        if k not in FILTER_KEYS:
            raise EslError("INPUT_INVALID", f"--filter 키 {k!r}: {list(FILTER_KEYS)} 중 하나")
        out.setdefault(k, []).extend(x.strip() for x in v.split(",") if x.strip())
    return out


def query(root: str, filters: dict | None = None, include_retired: bool = False) -> list[dict]:
    rows = []
    for r in read_index(root).values():
        if r["status"] == "retired" and not include_retired and "status" not in (filters or {}):
            continue
        ok = True
        for k, vals in (filters or {}).items():
            if str(r.get(k)).lower() not in {str(v).lower() for v in vals}:
                ok = False
                break
        if ok:
            rows.append(r)
    return rows                 # 색인(등록) 순서


def load_entry(root: str, entry_id: str, raw: bool = False, verify: bool = True) -> en.LibraryEntry:
    d = entry_dir(root, entry_id)
    if not os.path.isdir(d):
        raise EslError("ENTRY_NOT_FOUND", f"항목 폴더가 없음: {d}")
    return en.load(d, raw=raw, verify=verify)
