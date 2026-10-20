"""시연 준비 공용: 경로(저장소·오프라인 묶음 공통), 상수, 로그 출력, 루프백 HTTP, `_backup` 이동, 없을 때만 쓰기."""

from __future__ import annotations

import datetime as _dt
import re
import shutil
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parents[1]  # 저장소 루트 또는 오프라인 묶음 루트


def code_root(pkg: Path = PKG_ROOT) -> Path:
    """ESL 코드(backend·worker·esl·migrations): 묶음은 <묶음>/app, 저장소는 루트."""
    app = pkg / "app"
    if (app / "backend" / "esl_platform").is_dir():
        return app
    if (pkg / "backend" / "esl_platform").is_dir():
        return pkg
    raise SystemExit(f"ESL 코드(backend/esl_platform)를 찾을 수 없습니다: {pkg} — 저장소 또는 오프라인 묶음에서 실행하세요")


def launcher(pkg: Path = PKG_ROOT) -> Path:
    """실행기 esl_service.py: 묶음 <묶음>/app/esl_service.py, 저장소 deploy/esl_service.py."""
    for c in (code_root(pkg) / "esl_service.py", pkg / "deploy" / "esl_service.py"):
        if c.is_file():
            return c
    raise SystemExit("실행기 esl_service.py 를 찾을 수 없습니다")


def add_code_paths(pkg: Path = PKG_ROOT) -> None:
    root = code_root(pkg)
    for p in (root / "worker", root / "backend", root):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


PROJECT_ID = "demo"
CASE_NEW = ("demo_new", "시연 Case — 입력만(①부터 직접)")
CASE_DONE = ("demo_done", "시연 Case — ①~⑥ 완료")
INPUT_NAME = "demo_drop"
DB_NAME = "esl_demo"
UNSAFE = re.compile(r"[\s&|<>^%!\";,=()]")
CSRF = ("X-ESL-Request", "1")


def _log(msg: str) -> None:
    print(f"[ESL 시연] {msg}", flush=True)


# 시연 백엔드(127.0.0.1) 호출 전용 opener: HTTP_PROXY·HTTPS_PROXY 환경변수와 Windows 시스템 프록시를 쓰지 않는다
# (회사 PC에서 루프백 요청이 프록시로 나가 health가 실패하던 문제 — physicsai GitHub #1과 같은 처리).
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_urlopen(req: urllib.request.Request | str, timeout: float):
    """프록시 없이 연다(루프백 전용)."""
    return _LOCAL_OPENER.open(req, timeout=timeout)


def fwd(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def move_to_backup(root: Path, path: Path) -> Path:
    """사용자 산출물은 삭제하지 않고 <root>/_backup/<UTC>/ 로 옮긴다."""
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = root / "_backup" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest / path.name))
    return dest / path.name


def write_if_missing(path: Path, data: str | bytes) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return True
