"""V-SEC-1·V-CFG-2 (정적): 제품 코드에 shell=True·os.system·subprocess·pickle·allow_pickle=True·하드코딩 실행파일 0건.
V-SEC-2(P3-UX 갱신, 계약 esl_p3_ux.md §1.1): multipart/UploadFile 0개, 업로드는 허용된 /uploads 경로만
(요청 본문을 원시 스트림으로 읽는 곳은 청크 PUT 하나)."""

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


# P3-UX §6: 외부 프로그램 실행은 서버 h3d 추출 모듈 하나만(argv 템플릿·shell=False — esl.md §4.4)
ALLOWED = {"worker/esl_worker/h3d.py": {"subprocess"}}


def test_no_forbidden_patterns():
    hits = []
    for p in _files():
        text = p.read_text(encoding="utf-8")
        rel = p.relative_to(REPO).as_posix()
        for name, rx in FORBIDDEN.items():
            if rx.search(text) and name not in ALLOWED.get(rel, set()):
                hits.append(f"{rel}: {name}")
    assert hits == []


def test_h3d_runs_without_shell():
    """h3d 추출 모듈: Popen 은 shell=False 리터럴로만, os.system·shell=True 없음."""
    text = (REPO / "worker" / "esl_worker" / "h3d.py").read_text(encoding="utf-8")
    calls = re.findall(r"subprocess\.(Popen|run)\(([^)]*)", text)
    assert calls and all("shell=False" in args for _, args in calls)


ALLOWED_UPLOAD_ROUTES = {
    ("POST", "/uploads"), ("GET", "/uploads"), ("GET", "/uploads/{upload_id}"),
    ("POST", "/uploads/{upload_id}/files"), ("PUT", "/uploads/{upload_id}/files/{index}"),
    ("POST", "/uploads/{upload_id}/complete"), ("DELETE", "/uploads/{upload_id}"),
    ("DELETE", "/uploads/{upload_id}/files/{index}"),
}
RAW_BODY_ROUTES = {("PUT", "/uploads/{upload_id}/files/{index}")}


def test_no_multipart_routes(client):
    spec = client.get(f"{API}/openapi.json").json()
    assert "multipart/form-data" not in str(spec)
    from fastapi.routing import APIRoute

    for r in client.app.routes:
        if isinstance(r, APIRoute):
            for f in r.dependant.body_params:
                assert "UploadFile" not in repr(f), r.path


def test_only_allowed_upload_routes(client):
    """업로드 관련 라우트는 허용 목록과 정확히 같고, octet-stream 본문은 청크 PUT 하나뿐."""
    spec = client.get(f"{API}/openapi.json").json()
    upload_like, raw = set(), set()
    for path, ops in spec["paths"].items():
        p = path.removeprefix(API)
        for method, op in ops.items():
            key = (method.upper(), p)
            if "upload" in p.lower():
                upload_like.add(key)
            content = ((op.get("requestBody") or {}).get("content") or {})
            if any(ct != "application/json" for ct in content):
                raw.add(key)
    assert upload_like == ALLOWED_UPLOAD_ROUTES
    assert raw == RAW_BODY_ROUTES


def test_raw_body_read_only_in_upload_router():
    rx = re.compile(r"request\.(stream|body|form)\s*\(")
    hits = [str(p.relative_to(REPO)) for p in _files() if rx.search(p.read_text(encoding="utf-8"))]
    assert hits == ["backend/esl_platform/api/routers/uploads.py"]


def test_core_called_only_via_adapter():
    """플랫폼은 코어를 어댑터에서만 import 한다: 워커 core_adapter, 백엔드 비드 최적화 opt_core(v0.7.0 — esl.opt 의
    가벼운 함수만, 계약 esl_opt_run.md §15 경계)."""
    rx = re.compile(r"^\s*(from\s+esl(\.\w+)*\s+import|import\s+esl(\.\w+)*)\b", re.M)
    adapters = {"worker/esl_worker/core_adapter.py", "backend/esl_platform/core/opt_core.py"}
    bad = [str(p.relative_to(REPO)) for p in _files() if rx.search(p.read_text(encoding="utf-8"))
           and p.relative_to(REPO).as_posix() not in adapters]
    assert bad == []
