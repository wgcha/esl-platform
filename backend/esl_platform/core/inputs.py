"""입력 지문·최신성(계약 esl_platform_p1b.md §3).

- `fingerprint(rad, results_dir, includes)`: `{rad:{size,mtime,sha256}, includes:[{path,size,mtime}],
  results:{done_json_sha256, files:{name:{size,mtime}}}}`
- `fingerprint_h3d(rad, h3d, includes)`: 서버 h3d 추출 Case(P3-UX §6) — results 대신 `h3d:{path,size,mtime}`
  (결과 CSV 는 작업이 만드는 산출물이라 지문에 넣지 않음)
- `changed_inputs(fp)`: size·mtime 이 달라진(또는 사라진) 경로 목록 → 작업 시작 시 `INPUT_CHANGED`.
- `inputs_hash(...)`: ESL 실행의 입력(추출 작업·part_title·t*·지지점 세트) 해시 → 다르면 stale.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _stat(path: str) -> dict[str, Any]:
    st = os.stat(path)
    return {"size": int(st.st_size), "mtime": float(st.st_mtime)}


def results_files(results_dir: str) -> dict[str, dict[str, Any]]:
    out = {}
    for name in sorted(os.listdir(results_dir)):
        p = os.path.join(results_dir, name)
        if os.path.isfile(p) and not os.path.islink(p):
            out[name] = _stat(p)
    return out


def fingerprint(rad: str, results_dir: str, includes: list[str]) -> dict[str, Any]:
    done = os.path.join(results_dir, "done.json")
    return {
        "rad": {"path": rad, **_stat(rad), "sha256": sha256_file(rad)},
        "includes": [{"path": p, **_stat(p)} for p in includes if os.path.isfile(p)],
        "results": {"path": results_dir, "done_json_sha256": sha256_file(done) if os.path.isfile(done) else None,
                    "files": results_files(results_dir)},
    }


def fingerprint_h3d(rad: str, h3d: str, includes: list[str]) -> dict[str, Any]:
    return {
        "rad": {"path": rad, **_stat(rad), "sha256": sha256_file(rad)},
        "includes": [{"path": p, **_stat(p)} for p in includes if os.path.isfile(p)],
        "h3d": {"path": h3d, **_stat(h3d)},
        "results": None,
    }


def changed_inputs(fp: dict[str, Any]) -> list[str]:
    out: list[str] = []

    def chk(path: str, ref: dict[str, Any]) -> None:
        try:
            st = _stat(path)
        except OSError:
            out.append(path)
            return
        if st["size"] != ref.get("size") or st["mtime"] != ref.get("mtime"):
            out.append(path)

    rad = fp.get("rad") or {}
    if rad.get("path"):
        chk(rad["path"], rad)
    for inc in fp.get("includes") or []:
        chk(inc["path"], inc)
    h3d = fp.get("h3d") or {}
    if h3d.get("path"):
        chk(h3d["path"], h3d)
    res = fp.get("results") or {}
    base = res.get("path")
    if base:
        for name, ref in (res.get("files") or {}).items():
            chk(os.path.join(base, name), ref)
    return out


def inputs_hash(*, extract_job_id: str | None, part_title: str, tstar: dict[str, Any] | None,
                support_set_id: str | None) -> str:
    key = {
        "extract_job_id": extract_job_id,
        "part_title": part_title,
        "tstar": None if not tstar else {"frame_index": tstar.get("frame_index"), "metric": tstar.get("metric")},
        "support_set_id": support_set_id,
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()


def case_inputs_hash(case: dict[str, Any]) -> str:
    es = case.get("extract_summary") or {}
    return inputs_hash(extract_job_id=es.get("job_id"), part_title=case["part_title"], tstar=case.get("tstar"),
                       support_set_id=case.get("current_support_set_id"))


def extract_stale(case: dict[str, Any]) -> bool:
    es = case.get("extract_summary") or {}
    return bool(es) and es.get("requested_part_title") != case["part_title"]


def esl_run_stale(case: dict[str, Any], run: dict[str, Any]) -> bool:
    return run["inputs_hash"] != case_inputs_hash(case) or extract_stale(case)
