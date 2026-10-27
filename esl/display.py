"""사용자에게 보이는 경로 표기 통일(이슈 #24).

설정 루트가 ``E:/data`` 처럼 슬래시인데 ``os.path.join`` 이 역슬래시를 붙여 ``E:/data\\Case`` 처럼 섞여 보이는 문제.
``display_path`` 는 **표시·응답 경계에서만** 쓴다(내부 저장값·비교 로직은 그대로).

스타일: ``ESL_DISPLAY_PATH_STYLE`` = ``auto``(기본: 운영 OS 가 Windows 면 windows) | ``windows`` | ``posix``.
windows 스타일은 ``ntpath.normpath`` — 구분자를 ``\\`` 로 통일, 중복·``.``·``..`` 정리, 드라이브 문자·UNC 유지.
posix 스타일(Linux 개발·시험)은 문자열을 그대로 둔다.
"""
from __future__ import annotations

import ntpath
import os

ENV_STYLE = "ESL_DISPLAY_PATH_STYLE"


def is_windows_style(style: str | None = None) -> bool:
    s = (style or os.environ.get(ENV_STYLE) or "auto").strip().lower()
    if s == "windows":
        return True
    if s == "posix":
        return False
    return os.name == "nt"


def display_path(p, style: str | None = None):
    """경로 문자열을 표시용으로 정규화. 문자열이 아니거나 빈 값이면 그대로."""
    if not isinstance(p, str) or not p:
        return p
    return ntpath.normpath(p) if is_windows_style(style) else p
