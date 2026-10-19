"""V-SEC-1·V-CFG-2 (정적): 제품 코드에 shell=True·os.system·subprocess·pickle·allow_pickle=True·하드코딩 실행파일 0건.
V-SEC-2: 업로드(multipart/UploadFile) 라우트 0개."""

from __future__ import annotations

import re
from pathlib import Path

from esl_test_support import API, REPO

PRODUCT = [REPO / "backend" / "esl_platform", REPO / "worker" / "esl_worker", REPO / "migrations",
           REPO / "scripts" / "dump_openapi.py"]
FORBIDDEN = {
    "shell=True": re.compile(r"shell\s*=\s*True"),
    "os.system": re.compile(r"\bos\.system\b"),
    "os.popen": re.compile(r"\bos\.popen\b"),
    "subprocess": re.compile(r"\bsubprocess\b"),
    "pickle": re.compile(r"^\s*(import|from)\s+(c?pickle|dill|shelve)\b|\bpickle\.(loads?|dumps?)\b", re.M),
    "allow_pickle=True": re.compile(r"allow_pickle\s*=\s*True"),
    "Program Files": re.compile(r"Program Files", re.I),
    ".exe/.bat 경로": re.compile(r"[\"'][^\"']*\.(exe|bat|cmd)[\"']", re.I),
    "UploadFile": re.compile(r"\bUploadFile\b|\bFile\(|\bForm\("),
}


def _files():
    for base in PRODUCT:
        if base.is_file():
            yield base
        else:
            yield from (p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_forbidden_patterns():
    hits = []
    for p in _files():
        text = p.read_text(encoding="utf-8")
        for name, rx in FORBIDDEN.items():
            if rx.search(text):
                hits.append(f"{p.relative_to(REPO)}: {name}")
    assert hits == []


def test_no_multipart_routes(client):
    spec = client.get(f"{API}/openapi.json").json()
    assert "multipart/form-data" not in str(spec)
    from fastapi.routing import APIRoute

    for r in client.app.routes:
        if isinstance(r, APIRoute):
            for f in r.dependant.body_params:
                assert "UploadFile" not in repr(f), r.path


def test_core_called_only_via_adapter():
    """플랫폼은 코어를 core_adapter 한 곳에서만 import 한다."""
    rx = re.compile(r"^\s*(from\s+esl(\.\w+)*\s+import|import\s+esl(\.\w+)*)\b", re.M)
    bad = [str(p.relative_to(REPO)) for p in _files() if rx.search(p.read_text(encoding="utf-8"))
           and p.name != "core_adapter.py"]
    assert bad == []
