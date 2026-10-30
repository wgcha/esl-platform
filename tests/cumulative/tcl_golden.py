"""V-CI-B1(TCL): request 키 없는 기본 mock 실행의 CSV 출력 지문(v0.7.2 TCL 로 만든 골든과 비교).

사용(골든 생성): python tests/cumulative/tcl_golden.py <작업 폴더> <출력 json>
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(REPO, "tests", "io"), REPO]

DONE_SKIP = {"h3d", "output", "backup_dir", "elapsed_s", "created_at", "finished_at", "started_at", "tcl_version",
             "script", "request", "config", "esl_version", "version", "log", "progress_log", "api", "env"}
# v0.12.1(esl_strain_fallback.md §3): done.json 추가 키 — 골든 비교에서 뺀다(CSV·기존 키는 그대로 같아야 함)
DONE_ADDED = {"strain_source", "strain_source_type", "strain_layers", "strain_mode", "strain_tried", "epsp_available"}


def tcl_digest(work: str) -> dict:
    import test_tcl_mock as tm
    p = pathlib.Path(work)
    p.mkdir(parents=True, exist_ok=True)
    _m, _ref, drv, out = tm._setup(p)
    r = tm._run(drv)
    assert r.returncode == 0, r.stderr
    res = {}
    for f in sorted(os.listdir(out)):
        if f.endswith(".csv"):
            res[f] = hashlib.sha256((out / f).read_bytes()).hexdigest()[:16]
    done = json.loads((out / "done.json").read_text())
    keep = {k: v for k, v in done.items() if k not in DONE_SKIP and k not in DONE_ADDED and "time" not in k
            and not k.endswith("_s")}
    keep.pop("passes", None)
    res["done.json"] = hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:16]
    res["done_keys"] = sorted(k for k in done if k not in DONE_ADDED)
    return res


if __name__ == "__main__":
    d = tcl_digest(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)
