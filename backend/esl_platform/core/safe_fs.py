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
            if os.path.islink(cur):
                raise UnsafePath(f"심링크 경로를 거칩니다: {name}")
        except OSError as exc:
            raise UnsafePath(f"경로 확인 실패: {name}") from exc
    rr = os.path.realpath(root)
    rp = os.path.realpath(path)
    if rp != rr and not rp.startswith(rr.rstrip(os.sep) + os.sep):
        raise UnsafePath(f"Case 폴더 밖 경로: {os.path.basename(path)}")
    return path
