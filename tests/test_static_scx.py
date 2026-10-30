"""V-SR-14(기능 A 부분) 정적 검사(계약 esl_scx_relay.md §12): 새 SCX 코드에 외부 명령(subprocess·os.system·Popen) 없음,
어댑터 드라이브 쓰기 메서드(upload·mkdirs·submit_radioss·resolve·cancel·ensure_new_dir)를 부르는 esl 모듈 없음(v0.12.0 은
worker/esl_worker/scx_verify.py 하나만 허용), 삭제·이동 이름 없음, http.client 직접 사용 없음(어댑터 경유), 어댑터 import 는
core/scx(+ 환경 점검 check.py)에서만, 시험 가짜 릴레이 사본에 출처 머리말."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW = [*sorted((ROOT / "backend/esl_platform/core/scx").glob("*.py")), ROOT / "backend/esl_platform/api/services/scx_drive.py",
       ROOT / "backend/esl_platform/api/routers/scx.py", ROOT / "worker/esl_worker/scx_fetch.py",
       # v0.12.0 기능 B
       ROOT / "worker/esl_worker/scx_verify.py", ROOT / "worker/esl_worker/verify_post.py",
       ROOT / "backend/esl_platform/api/services/verify_drop.py", ROOT / "backend/esl_platform/api/routers/verify.py",
       *sorted((ROOT / "esl/verify").glob("*.py"))]
WRITE_METHODS = {"upload", "upload_file", "mkdirs", "submit_radioss", "resolve", "cancel", "ensure_new_dir"}
ALLOWED_WRITER = ROOT / "worker/esl_worker/scx_verify.py"


def _tree(p: Path) -> ast.AST:
    return ast.parse(p.read_text(encoding="utf-8"), str(p))


def test_new_scx_code_has_no_external_commands():
    for p in NEW:
        t = _tree(p)
        for n in ast.walk(t):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in n.names] + ([n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
                assert not any(x and x.split(".")[0] in ("subprocess", "pty") for x in names), (p, names)
                assert not any(x == "http.client" or x == "client" and getattr(n, "module", "") == "http" for x in names), p
            if isinstance(n, ast.Attribute) and n.attr in ("system", "popen", "Popen", "spawnv", "execv", "startfile"):
                raise AssertionError(f"{p}: {n.attr}")


def test_no_drive_write_calls_outside_verify_module():
    for base in ("backend/esl_platform", "worker/esl_worker"):
        for p in sorted((ROOT / base).rglob("*.py")):
            if p == ALLOWED_WRITER or "/core/scx/gateway.py" in str(p).replace("\\", "/"):
                continue                                   # gateway.py 는 어댑터 클래스 정의(재정의 _load_secret)만
            src = p.read_text(encoding="utf-8")
            if "scx" not in src.lower():
                continue
            for n in ast.walk(_tree(p)):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in WRITE_METHODS:
                    tgt = ast.unparse(n.func.value)
                    if re.search(r"(^|\.)(gw|gateway|client\(\))$|_gw$", tgt):
                        raise AssertionError(f"{p}:{n.lineno}: 드라이브 쓰기 {tgt}.{n.func.attr}")


def test_no_delete_or_move_names_in_scx_code():
    pat = re.compile(r"\b(delete_file|remove_file|move_file|rename_file|rmtree|os\.remove|os\.unlink|shutil\.move)\b")
    for p in NEW:
        assert not pat.search(p.read_text(encoding="utf-8")), p


def test_adapter_imported_only_in_scx_layer():
    allowed = {ROOT / "backend/esl_platform/check.py"} | set((ROOT / "backend/esl_platform/core/scx").glob("*.py"))
    for base in ("backend/esl_platform", "worker/esl_worker"):
        for p in sorted((ROOT / base).rglob("*.py")):
            for n in ast.walk(_tree(p)):
                mods = []
                if isinstance(n, ast.ImportFrom) and n.module:
                    mods = [n.module]
                elif isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                if any(m.split(".")[0] == "simdash_adapters" for m in mods):
                    assert p in allowed, p


def test_fake_relay_copy_has_source_header():
    head = (ROOT / "backend/tests/scx/fake_scx_relay.py").read_text(encoding="utf-8").splitlines()[:3]
    assert "a363a89e8f93d3acfe90a9601318bf4f6cade0a7" in head[0] and "packages/simdash_adapters/tests/fake_scx_relay.py" in head[1]


def test_verify_module_is_the_only_writer_and_writes_exist_there():
    """v0.12.0: 어댑터 쓰기 호출(ensure_new_dir·upload·submit_radioss·cancel·resolve)은 scx_verify.py 에 실제로 있고(그 모듈만),
    백엔드 [잡 ID 연결]·[포기]는 그 모듈 함수(resolve_submission)를 거친다."""
    calls = set()
    for n in ast.walk(_tree(ALLOWED_WRITER)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in WRITE_METHODS:
            calls.add(n.func.attr)
    assert {"ensure_new_dir", "upload", "submit_radioss", "cancel", "resolve"} <= calls
    src = (ROOT / "backend/esl_platform/api/services/verify_drop.py").read_text(encoding="utf-8")
    assert "scx_verify.resolve_submission(" in src
