"""서버 폴더 찾아보기 `GET /fs/browse`(계약 esl_p3_ux.md §1.2).

- 루트: storage.input_roots(upload_root 자동 포함) + (storage.browse_spdm 이면) spdm_roots — 읽기 전용, 인덱스로 지정.
- `path` 는 루트 기준 상대경로('/' 구분). `..`·절대경로·제어문자·cmd 메타문자 거부, 성분 심링크 거부, realpath 가 루트 밖이면 거부.
- 항목: 심링크·숨김·시스템 파일(점·$ 로 시작, desktop.ini 등, Windows 숨김/시스템 속성)·업로드 `_backup`·`.part` 제외.
  hint: `.rad` → rad, `.h3d` → h3d, done.json 이 있는 폴더 → results. 정렬: 폴더 먼저, 이름(대소문자 무시).
- 항목 수가 많으면 offset·limit(≤ ui.browse_page_max) 페이지네이션, total·truncated 표시.
"""

from __future__ import annotations

import os
import re
import stat
from typing import Any

from ...core.config import is_within
from ...core.errors import not_found, unprocessable
from ...core.uploads import BACKUP_DIR, PART_SUFFIX
from ..context import AppContext

_META = re.compile(r'[\x00-\x1f\x7f&|<>^%!"*?]')
_SYSTEM = {"desktop.ini", "thumbs.db", "system volume information", "$recycle.bin", "__pycache__"}
_HIDDEN_ATTR = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2) | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 4)


def roots(ctx: AppContext) -> list[dict[str, Any]]:
    st = ctx.settings.storage
    out: list[dict[str, Any]] = []
    for r in st.input_roots:
        is_up = bool(st.upload_root) and os.path.normcase(os.path.normpath(r)) == os.path.normcase(
            os.path.normpath(st.upload_root))
        out.append({"index": len(out), "label": "업로드" if is_up else (os.path.basename(r.rstrip("/\\")) or r),
                    "path": r, "kind": "upload" if is_up else "input", "writable": False})
    if st.browse_spdm:
        for r in st.spdm_roots:
            out.append({"index": len(out), "label": "SPDM " + (os.path.basename(r.rstrip("/\\")) or r), "path": r,
                        "kind": "spdm", "writable": False})
    return out


def _split_rel(path: str) -> list[str]:
    if not path or path in ("/", "."):
        return []
    if len(path) > 1024 or _META.search(path):
        raise unprocessable("PATH_UNSAFE", '경로에 제어문자나 & | < > ^ % ! " * ? 를 쓸 수 없습니다')
    if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
        raise unprocessable("PATH_UNSAFE", "루트 기준 상대경로만 허용합니다")
    segs = [s for s in re.split(r"[\\/]+", path) if s not in ("", ".")]
    if any(s == ".." for s in segs):
        raise unprocessable("PATH_UNSAFE", "경로에 '..' 를 쓸 수 없습니다")
    return segs


def _hidden(name: str, st: os.stat_result) -> bool:
    n = name.lower()
    if name.startswith((".", "$", "~$")) or n in _SYSTEM:
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _HIDDEN_ATTR)


def browse(ctx: AppContext, root: int | None, path: str, offset: int, limit: int | None) -> dict[str, Any]:
    rs = roots(ctx)
    page_max = ctx.settings.ui.browse_page_max
    lim = min(limit or page_max, page_max)
    base = {"roots": rs, "root": root, "path": "", "parent": None, "abs_path": None, "hint": None, "entries": [],
            "total": 0, "offset": offset, "limit": lim, "truncated": False}
    if root is None:
        return base
    if root < 0 or root >= len(rs):
        raise not_found("BROWSE_ROOT_NOT_FOUND", "찾아보기 루트가 없습니다")
    r = rs[root]
    rootp = os.path.normpath(r["path"])
    segs = _split_rel(path)
    cur = rootp
    for s in segs:
        cur = os.path.join(cur, s)
        if os.path.islink(cur):
            raise unprocessable("PATH_UNSAFE", "심볼릭 링크 경로는 허용하지 않습니다")
    if not os.path.isdir(rootp):
        raise not_found("PATH_NOT_FOUND", f"루트 폴더가 없습니다: {r['path']}")
    if not is_within(os.path.realpath(cur), os.path.realpath(rootp)):
        raise unprocessable("PATH_UNSAFE", "실제 경로가 루트 밖입니다")
    if not os.path.isdir(cur):
        raise not_found("PATH_NOT_FOUND", "폴더가 없습니다")
    is_upload = r["kind"] == "upload"
    items: list[tuple[bool, str, os.stat_result]] = []
    try:
        with os.scandir(cur) as it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if _hidden(e.name, st):
                    continue
                is_dir = stat.S_ISDIR(st.st_mode)
                if not is_dir and not stat.S_ISREG(st.st_mode):
                    continue
                if is_upload and not segs and is_dir and e.name == BACKUP_DIR:
                    continue
                if not is_dir and e.name.endswith(PART_SUFFIX):
                    continue
                items.append((is_dir, e.name, st))
    except OSError as exc:
        raise unprocessable("PATH_NOT_READABLE", f"폴더를 읽을 수 없습니다: {exc.strerror or exc}") from None
    items.sort(key=lambda x: (not x[0], x[1].casefold(), x[1]))
    total = len(items)
    page = items[offset:offset + lim]
    entries = []
    for is_dir, name, st in page:
        hint = None
        if is_dir:
            if os.path.isfile(os.path.join(cur, name, "done.json")):
                hint = "results"
        else:
            low = name.lower()
            hint = "rad" if low.endswith(".rad") else ("h3d" if low.endswith(".h3d") else None)
        entries.append({"name": name, "type": "dir" if is_dir else "file", "size": None if is_dir else int(st.st_size),
                        "mtime": float(st.st_mtime), "hint": hint})
    rel = "/".join(segs)
    return {**base, "path": rel, "parent": None if not segs else "/".join(segs[:-1]), "abs_path": cur,
            "hint": "results" if os.path.isfile(os.path.join(cur, "done.json")) else None,
            "entries": entries, "total": total, "truncated": offset + len(page) < total}
