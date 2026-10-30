"""SCX 드라이브 경로 규칙(계약 esl_scx_relay.md SR-D-5·§12). 순수 함수 — 네트워크·파일시스템 없음.

드라이브 경로 = 공용 계정 홈 기준 상대(`/` 구분, 앞 `/`·`~` 없음 — 어댑터 관례). 탐색·내려받기 범위 = 설정 scx_drive.roots 안만:
요청 경로(루트 기준 상대)의 구간 검사(빈·`.`·`..`·`\\`·`~`·제어문자 거부) → 루트 rel 과 이음 → 어댑터 `rel_problem`(첫 구간 `.` 금지,
길이) → health `forbidden_prefixes`(SPDM 마스터 루트, 대소문자·NFC 무시) → health `relay_base` 안. 루트 포함은 접두가 아닌 구간 비교.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from ..errors import DomainError, not_found
from . import messages

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
HIDDEN = "."


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


def find_root(settings, project_id: str, key: str):
    """프로젝트에 허용된 루트(key) — 없으면 404 SCX_ROOT_NOT_FOUND(다른 프로젝트 전용 루트도 없음과 같게)."""
    from .status import allowed_roots

    for r in allowed_roots(settings, project_id):
        if r.key == key:
            return r
    raise not_found("SCX_ROOT_NOT_FOUND", messages.text("SCX_ROOT_NOT_FOUND"))


def _bad(why: str) -> DomainError:
    return DomainError("SCX_PATH_NOT_ALLOWED", f"{messages.text('SCX_PATH_NOT_ALLOWED')}({why})", status=422)


def sub_segments(path: str | None) -> list[str]:
    """루트 기준 상대 경로 → 구간 목록(빈 문자열 = 루트 자체). 형식이 틀리면 422 SCX_PATH_NOT_ALLOWED."""
    p = unicodedata.normalize("NFC", path or "")
    if not p:
        return []
    if _CTRL.search(p):
        raise _bad("제어문자")
    if "\\" in p:
        raise _bad("'\\' 구분자")
    if p.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", p):
        raise _bad("절대경로·'~'")
    segs = p.split("/")
    for s in segs:
        if s in ("", ".", ".."):
            raise _bad("빈 구간·'.'·'..'")
        if len(s) > 255:
            raise _bad("구간이 255자를 넘음")
    return segs


def check_drive_rel(rel: str, health: dict[str, Any] | None, home_display: str = "") -> str:
    """완성된 드라이브 상대 경로 검사(어댑터 rel_problem + SPDM 금지 + relay_base 안). 통과하면 NFC 정규화 경로."""
    from simdash_adapters.hpc.scx_naming import forbidden_reason, rel_problem

    rel = unicodedata.normalize("NFC", rel or "")
    why = rel_problem(rel)
    if why:
        raise _bad(why)
    h = health or {}
    fb = forbidden_reason(rel, list(h.get("forbidden_prefixes") or []), "", str(h.get("home_display") or home_display))
    if fb:
        raise _bad(fb)
    rb = str(h.get("relay_base") or "").strip("/")
    if rb and not within(rel, rb):
        raise _bad("릴레이 읽기 범위 밖")
    return rel


def within(rel: str, base: str) -> bool:
    """rel 이 base 와 같거나 그 안(구간 비교, NFC·casefold)."""
    a, b = _fold(rel.strip("/")).split("/"), _fold(base.strip("/")).split("/")
    return len(a) >= len(b) and a[: len(b)] == b


def resolve(settings, project_id: str, root_key: str, path: str | None, health: dict[str, Any] | None) -> tuple[Any, str]:
    """(루트, 드라이브 상대 경로). 루트·형식·SPDM·relay_base 검사."""
    from .settings import scx_cfg

    root = find_root(settings, project_id, root_key)
    segs = sub_segments(path)
    rel = "/".join([root.rel.strip("/"), *segs])
    cfg = scx_cfg(settings)
    rel = check_drive_rel(rel, health, getattr(cfg, "home_display", "") if cfg else "")
    if not within(rel, root.rel):
        raise _bad("루트 밖")
    return root, rel


def in_root(rel: str, root_rel: str) -> bool:
    return within(rel, root_rel)


def root_sub(rel: str, root_rel: str) -> str:
    """드라이브 상대 경로 → 루트 기준 상대(표시·저장용)."""
    a, b = rel.strip("/").split("/"), root_rel.strip("/").split("/")
    return "/".join(a[len(b):])


def hint(name: str, engine_globs: list[str]) -> str | None:
    """파일 이름 → 화면 표지: `*_0000.rad` → rad, engine_globs 일치(`<stem>_000N.rad`) → engine, `.h3d` → h3d,
    `.inc`·`.k` → include, `.sta`·`.str` → state."""
    import fnmatch

    low = name.casefold()
    if low.endswith("_0000.rad"):
        return "rad"
    if low.endswith(".rad"):
        for g in engine_globs:
            if fnmatch.fnmatchcase(low, g.replace("{stem}", "*").casefold()):
                return "engine"
        return None
    if low.endswith(".h3d"):
        return "h3d"
    if low.endswith((".inc", ".k")):
        return "include"
    if low.endswith((".sta", ".str")):
        return "state"
    return None


__all__ = ["find_root", "sub_segments", "check_drive_rel", "resolve", "within", "in_root", "root_sub", "hint"]
