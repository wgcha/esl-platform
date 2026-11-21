"""Case 폴더 안 삭제·이동 공용 가드(심링크 탈출 방지).

``checked_path(root, path)`` — ``path`` 가 ``root``(Case 폴더) 아래이고, ``root`` 다음부터 ``path`` 까지 모든 구성 요소(자신 포함)가
심링크가 아니며, 실제 경로(realpath)도 ``root`` 의 realpath 안일 때만 ``path`` 를 돌려준다. 아니면 ``UnsafePath``(OSError) —
호출한 쪽은 삭제·이동 대신 사유를 기록한다. ``root`` 자신 위쪽의 링크(예: /data → 다른 디스크)는 검사하지 않는다(root 기준 상대 검사).
"""

from __future__ import annotations

import os


class UnsafePath(OSError):
    """삭제·이동 대상이 Case 폴더 밖이거나 심링크를 거친다."""


def _lex_rel(root: str, path: str) -> list[str]:
    rr = os.path.abspath(root)
    rp = os.path.abspath(path)
    try:
        if os.path.commonpath([rr, rp]) != rr:
            raise ValueError
    except ValueError:
        raise UnsafePath(f"Case 폴더 밖 경로: {os.path.basename(path)}") from None
    rel = os.path.relpath(rp, rr)
    return [] if rel == os.curdir else rel.split(os.sep)


def checked_path(root: str, path: str) -> str:
    parts = _lex_rel(root, path)
    cur = os.path.abspath(root)
    for name in parts:
        cur = os.path.join(cur, name)
        try:
            linked = os.path.islink(cur)
        except OSError as exc:                      # islink 자체의 오류만 "확인 실패" — 아래 UnsafePath 는 이 except 밖
            raise UnsafePath(f"경로 확인 실패: {name}") from exc
        if linked:
            raise UnsafePath(f"심링크 경로를 거칩니다: {name}")
    rr = os.path.realpath(root)
    rp = os.path.realpath(path)
    if rp != rr and not rp.startswith(rr.rstrip(os.sep) + os.sep):
        raise UnsafePath(f"Case 폴더 밖 경로: {os.path.basename(path)}")
    return path


def checked_target(root: str, path: str) -> str:
    """아직 없을 수 있는 쓰기 대상 검사: ``path`` 와 그 상위 전부(root 아래)를 ``checked_path`` 로 검사한다.
    존재하지 않는 구성 요소는 가장 가까운 존재 상위까지만 검사하고, 그 상위의 realpath 가 root 안인지 본다."""
    parts = _lex_rel(root, path)
    cur = os.path.abspath(root)
    near = cur
    for name in parts:
        cur = os.path.join(cur, name)
        if not os.path.lexists(cur):
            break
        near = cur
    checked_path(root, near)
    return path


def open_nofollow(path: str, mode: str = "wb", **kw):
    """쓰기용 열기 — ``path`` 자체가 심링크면 따라가지 않고 ``UnsafePath``(링크 대상 파일은 건드리지 않음). mode: w·wb·a·ab.
    POSIX 는 ``O_NOFOLLOW`` 로 열기와 검사가 한 번에(경쟁 없음), 없는 플랫폼(Windows)은 열기 직전 lstat 검사. ``kw`` 는 텍스트 모드의 encoding·newline 등."""
    base = mode.replace("b", "").replace("+", "")
    if base not in ("w", "a"):
        raise ValueError(f"쓰기 모드만 허용: {mode}")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if base == "w" else os.O_APPEND)
    flags |= getattr(os, "O_BINARY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow and os.path.islink(path):
        raise UnsafePath(f"심링크에는 쓰지 않음: {os.path.basename(path)}")
    try:
        fd = os.open(path, flags | nofollow, 0o666)
    except OSError as exc:
        if nofollow and os.path.islink(path):            # ELOOP(링크) — 사유를 분명히
            raise UnsafePath(f"심링크에는 쓰지 않음: {os.path.basename(path)}") from exc
        raise
    return os.fdopen(fd, mode, **kw)
