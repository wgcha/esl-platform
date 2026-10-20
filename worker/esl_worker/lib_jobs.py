"""Case 가 없는 라이브러리 작업의 실행 준비(작업 폴더·항목 폴더 확인) — 작업 유형별 디스패치.

executor 는 ``PREPARE[job_type](settings, job) -> (작업 폴더, spec["lib"])`` 만 부른다. 실패는 ``PrepareFailed``
(executor 가 FAILED step 으로 바꾼다).

- LIB_COMPARE(계약 esl_p2_library.md §12.2): 작업 폴더 ``<esl_root>/_compare/<comparison_id>/``(안전 경로),
  params 의 기준·비교 항목 ``dir_rel`` → 절대경로(entry.json 없으면 PREREQUISITE_MISSING).
  (LIB_ANALYZE 준비는 executor._prepare_analysis — 기존 구현 유지.)
"""

from __future__ import annotations

import os
from typing import Any

from esl_platform.core.errors import DomainError
from esl_platform.core.paths import COMPARE_DIR, LIBRARY_DIR, esl_subdir


class PrepareFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _entry_dir(settings, it: dict[str, Any]) -> dict[str, Any]:
    d = esl_subdir(settings, *it["dir_rel"].split("/"))
    if not os.path.isfile(os.path.join(d, "entry.json")):
        raise PrepareFailed("PREREQUISITE_MISSING", f"라이브러리 항목 폴더가 없습니다: {it['dir_rel']}")
    return {"id": it["id"], "dir": d, "overlay": it.get("overlay")}


def prepare_compare(settings, job: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    p = job["params"] or {}
    cid = job["comparison_id"]
    try:
        out = esl_subdir(settings, COMPARE_DIR, cid)
        lib_root = esl_subdir(settings, LIBRARY_DIR)
        os.makedirs(out, exist_ok=True)
        lib = {"cfg": p.get("settings") or {}, "lib_root": lib_root, "comparison_id": cid,
               "model": p.get("model"), "base_version": p.get("base_version"), "new_version": p.get("new_version"),
               "base": [_entry_dir(settings, it) for it in p.get("base") or []],
               "new": [_entry_dir(settings, it) for it in p.get("new") or []],
               "options": p.get("options") or {}, "filters": p.get("filters") or {}, "title": p.get("title")}
    except DomainError as exc:
        raise PrepareFailed(exc.code, exc.message) from None
    return out, lib


PREPARE = {"LIB_COMPARE": prepare_compare}
