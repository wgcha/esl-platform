"""결과 받기(zip) — `GET /cases/{id}/bundle`·`GET /library/analyses/{id}/bundle`(계약 esl_p3_ux.md §2).

- 파일 목록을 먼저 정하고 합계가 ui.max_bundle_bytes 를 넘으면 413 BUNDLE_TOO_LARGE(경로 안내).
- 스트리밍: zipfile 을 쓰기 전용 버퍼에 쓰면서 조각을 내보낸다(메모리에 전체를 올리지 않음, ZIP64).
- 경로 탈출 방지: os.walk(심링크 따라가지 않음), 심링크 파일·폴더 제외, realpath 가 기준 폴더 밖이면 제외,
  zip 안 이름은 기준 폴더 상대경로('/' 구분, '..' 없음). `_backup`·`.tmp`·`runs/` 스냅샷은 넣지 않는다.
- 대용량 배열(npz)은 기본 제외 — parts 에 raw 가 있을 때만.
"""

from __future__ import annotations

import os
import zipfile
from collections.abc import Iterator
from typing import Any

from ...core import core_outputs as co
from ...core.config import is_within
from ...core.errors import DomainError, not_found, unprocessable
from ...core.paths import ANALYSIS_DIR, esl_subdir
from ..context import AppContext
from .common import case_dir, load_case

CASE_PARTS = ("export", "report", "summary", "raw")
CASE_DEFAULT = ("export", "report", "summary")
ANALYSIS_PARTS = ("report", "deck", "csv", "raw")
ANALYSIS_DEFAULT = ("report", "deck", "csv")
READ_CHUNK = 1 << 20
_SKIP_DIRS = {"_backup", "__pycache__", "logs"}
_STORED_EXT = {".npz", ".zip", ".png", ".jpg", ".gz", ".h3d"}


def parse_parts(raw: str | None, allowed: tuple[str, ...], default: tuple[str, ...]) -> list[str]:
    if raw is None or not raw.strip():
        return list(default)
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    bad = [p for p in parts if p not in allowed]
    if bad:
        raise unprocessable("INVALID_PARAMS", f"parts 에 알 수 없는 값: {', '.join(bad)} (가능: {', '.join(allowed)})")
    return list(dict.fromkeys(parts))


def _walk(base: str, sub: str = "") -> Iterator[tuple[str, str]]:
    """base/sub 아래 일반 파일 (절대경로, base 기준 '/' 상대경로). 심링크·탈출·임시 파일 제외."""
    start = os.path.join(base, *sub.split("/")) if sub else base
    if not os.path.isdir(start) or os.path.islink(start):
        return
    real_base = os.path.realpath(base)
    for root, dirs, names in os.walk(start, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not os.path.islink(os.path.join(root, d)))
        for n in sorted(names):
            p = os.path.join(root, n)
            if os.path.islink(p) or not os.path.isfile(p) or n.endswith((".tmp", ".part")):
                continue
            if not is_within(os.path.realpath(p), real_base):
                continue
            rel = os.path.relpath(p, base).replace(os.sep, "/")
            if rel.startswith("../") or "/../" in rel:
                continue
            yield p, rel


def case_files(cdir: str, parts: list[str]) -> list[tuple[str, str]]:
    raw = "raw" in parts
    out: dict[str, str] = {}

    def add(p: str, rel: str) -> None:
        if rel.lower().endswith(".npz") and not raw:
            return
        out.setdefault(rel, p)

    if "export" in parts:
        for p, rel in _walk(cdir, co.D_EXPORT):
            add(p, rel)
    if "report" in parts:
        for p, rel in _walk(cdir, co.D_REPORT):
            add(p, rel)
    if "summary" in parts or raw:
        for name in ("case.json", co.RUN_JSON):
            p = os.path.join(cdir, name)
            if os.path.isfile(p) and not os.path.islink(p):
                add(p, name)
        for d in (co.D_EXTRACT, co.D_TSTAR, co.D_BC, co.D_ESL, co.D_VAL):
            for p, rel in _walk(cdir, d):
                low = rel.lower()
                if raw or low.endswith((".json", ".csv", ".txt")):
                    add(p, rel)
    return sorted(((p, rel) for rel, p in out.items()), key=lambda x: x[1])


def analysis_files(adir: str, parts: list[str]) -> list[tuple[str, str]]:
    raw = "raw" in parts
    out: dict[str, str] = {}
    for p, rel in _walk(adir):
        low = rel.lower()
        take = False
        if "report" in parts and (rel == "report.html" or low.endswith((".png", ".svg"))):
            take = True
        if "deck" in parts and rel.startswith("opt/"):
            take = True
        if "csv" in parts and (low.endswith(".csv") or rel == "analysis.json"):
            take = True
        if raw and low.endswith(".npz"):
            take = True
        if take and (raw or not low.endswith(".npz")):
            out.setdefault(rel, p)
    return sorted(((p, rel) for rel, p in out.items()), key=lambda x: x[1])


class _Sink:
    """zipfile 이 쓰는 쓰기 전용(되감기 없음) 스트림 — 쌓인 바이트를 꺼내 간다."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.pos = 0

    def write(self, b) -> int:
        self.buf += b
        self.pos += len(b)
        return len(b)

    def tell(self) -> int:
        return self.pos

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        out = bytes(self.buf)
        self.buf.clear()
        return out


def stream_zip(files: list[tuple[str, str]], prefix: str) -> Iterator[bytes]:
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", allowZip64=True) as zf:  # type: ignore[arg-type]
        for path, rel in files:
            ext = os.path.splitext(rel)[1].lower()
            zi = zipfile.ZipInfo.from_file(path, f"{prefix}/{rel}")
            zi.compress_type = zipfile.ZIP_STORED if ext in _STORED_EXT else zipfile.ZIP_DEFLATED
            try:
                src = open(path, "rb")
            except OSError:
                continue
            with src, zf.open(zi, "w", force_zip64=True) as dst:
                while True:
                    b = src.read(READ_CHUNK)
                    if not b:
                        break
                    dst.write(b)
                    if len(sink.buf) >= READ_CHUNK:
                        yield sink.take()
            yield sink.take()
    yield sink.take()


def _check_size(ctx: AppContext, files: list[tuple[str, str]], where: str) -> int:
    total = 0
    for p, _ in files:
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    limit = ctx.settings.ui.max_bundle_bytes
    if total > limit:
        raise DomainError("BUNDLE_TOO_LARGE", f"받을 파일이 상한({limit} B)보다 큽니다 — 폴더를 직접 여세요: {where}",
                          status=413, path=where, size=total, limit=limit)
    return total


def case_bundle(ctx: AppContext, case_id: str, parts_raw: str | None) -> dict[str, Any]:
    parts = parse_parts(parts_raw, CASE_PARTS, CASE_DEFAULT)
    with ctx.engine.connect() as conn:
        case = load_case(conn, case_id)
    cdir = case_dir(ctx, case)
    if not os.path.isdir(cdir):
        raise not_found("CASE_DIR_NOT_FOUND", "Case 폴더가 없습니다")
    files = case_files(cdir, parts)
    if not files:
        raise not_found("BUNDLE_EMPTY", "받을 결과 파일이 아직 없습니다(내보내기·보고서 생성 후)")
    size = _check_size(ctx, files, cdir)
    name = case["folder_name"]
    return {"files": files, "prefix": name, "filename": f"{name}_results.zip", "size": size}


def analysis_bundle(ctx: AppContext, aid: str, parts_raw: str | None) -> dict[str, Any]:
    from .library import _load_analysis

    parts = parse_parts(parts_raw, ANALYSIS_PARTS, ANALYSIS_DEFAULT)
    with ctx.engine.connect() as conn:
        a = _load_analysis(conn, aid)
    adir = esl_subdir(ctx.settings, ANALYSIS_DIR, a["id"])
    files = analysis_files(adir, parts) if os.path.isdir(adir) else []
    if not files:
        raise not_found("BUNDLE_EMPTY", "받을 분석 파일이 아직 없습니다(분석 작업 완료 후)")
    size = _check_size(ctx, files, adir)
    return {"files": files, "prefix": f"analysis_{aid}", "filename": f"analysis_{aid}.zip", "size": size}
