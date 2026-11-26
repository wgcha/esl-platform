"""SCX 드라이브 경로 규칙(계약 esl_scx_relay.md SR-D-5·§12). 순수 함수 — 네트워크·파일시스템 없음.

드라이브 경로 = 공용 계정 홈 기준 상대(`/` 구분, 앞 `/`·`~` 없음 — 어댑터 관례). 탐색·내려받기 범위 = 설정 scx_drive.roots 안만:
요청 경로(루트 기준 상대)의 구간 검사(빈·`.`·`..`·`\\`·`~`·제어문자 거부) → 루트 rel 과 이음 → 어댑터 `rel_problem`(첫 구간 `.` 금지,
길이) → (쓰기만) health `forbidden_prefixes`(SPDM 마스터 루트, 대소문자·NFC 무시 — 읽기는 relay 가 판정) → health `relay_base` 안. 루트 포함은 접두가 아닌 구간 비교.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from ..errors import DomainError, not_found
from . import messages

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")          # 드라이브 문자 구간('C:' — 홈 기준 상대 경로에 올 수 없음)
HIDDEN = "."


def drive_segment(rel: str) -> str | None:
    """기본 안전 검사(읽기·쓰기·설정 루트 rel 공통): 어느 구간이든 드라이브 문자('C:')로 시작하면 사유, 아니면 None.
    #92 읽기 완화(SEGMENT_RE 제외) 뒤에도 드라이브 문자 구간은 거부(재검증 Fail)."""
    return "드라이브 문자 구간('X:')" if any(_DRIVE.match(g) for g in (rel or "").split("/")) else None


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
    if p.startswith(("/", "~")) or _DRIVE.match(p):
        raise _bad("절대경로·'~'")
    segs = p.split("/")
    for s in segs:
        if s in ("", ".", ".."):
            raise _bad("빈 구간·'.'·'..'")
        if len(s) > 255:
            raise _bad("구간이 255자를 넘음")
    return segs


def check_drive_rel(rel: str, health: dict[str, Any] | None, home_display: str = "", *, write: bool = False,
                    new_from: int | None = None) -> str:
    """완성된 드라이브 상대 경로 검사(어댑터 rel_problem + SPDM 금지 + relay_base 안). 통과하면 NFC 정규화 경로.
    write=False(기능 A 읽기 — 목록·고르기·내려받기) = esl 은 SPDM 판정을 하지 않음(대시보드 relay 가 판정 — 403 PATH_NOT_ALLOWED
    는 SCX_PATH_NOT_ALLOWED "대시보드가 SPDM 폴더 읽기를 막고 있습니다"로 안내). write=True(기능 B 업로드·제출 폴더) = 어댑터
    forbidden_reason 그대로(SPDM 루트 안, 또는 프로젝트 폴더가 SPDM 루트이거나 그 상위 폴더면 거부).
    폴더 이름 형식(어댑터 SEGMENT_RE — ASCII)은 esl 이 새로 만드는 구간에만(#92): 읽기는 어느 구간에도 적용하지 않고(기본 안전 검사
    — 제어문자·`\\`·빈 구간·`..`·길이·첫 구간 `.` — 만), 쓰기는 `new_from` 번째 구간부터(없으면 전체 — 이전 동작)."""
    from simdash_adapters.hpc.scx_naming import forbidden_reason, rel_problem

    rel = unicodedata.normalize("NFC", rel or "")
    nseg = rel.count("/") + 1
    start = nseg if not write else (0 if new_from is None else new_from)      # SEGMENT_RE 적용 시작 구간
    why = rel_problem(rel, segment_check_from=start) or drive_segment(rel)
    if why:
        raise _bad(why)
    if not write and any(g.startswith(HIDDEN) for g in rel.split("/")):          # 목록이 숨기는 '.' 시작 폴더·파일은 읽지 않음
        raise _bad("숨김 이름('.' 시작)")
    h = health or {}
    hd = str(h.get("home_display") or home_display)
    fb = forbidden_reason(rel, list(h.get("forbidden_prefixes") or []), "", hd) if write else None
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


def display(settings, rel: str | None) -> str | None:
    """드라이브 상대 경로 → 표시 전용 경로(hpc.scx.home_display 기준). 계산에 쓰지 않는다."""
    from simdash_adapters.hpc.scx_naming import display_path

    from .settings import scx_cfg

    if not rel:
        return None
    cfg = scx_cfg(settings)
    return display_path(getattr(cfg, "home_display", "") if cfg else "", rel)


def job_new_from(settings) -> int:
    """기능 B 잡 경로(`<drive_base>/<프로젝트>/<잡>`)에서 esl 이 새로 만드는 첫 구간 번호 = drive_base 구간 수(설정 값 — SEGMENT_RE 제외)."""
    from simdash_adapters.hpc.scx_naming import drive_base_rel

    from .settings import scx_cfg

    base = drive_base_rel(scx_cfg(settings).drive_base)
    return len(base.split("/")) if base else 0


def verify_job_parent(settings, project_folder: str) -> str:
    """기능 B 잡 폴더의 부모 = <drive_base>/<프로젝트 구간>(SR-D-12, 어댑터 drive_base_rel·sanitize_project)."""
    from simdash_adapters.hpc.scx_naming import drive_base_rel, sanitize_project

    from .settings import scx_cfg

    base = drive_base_rel(scx_cfg(settings).drive_base)
    seg = sanitize_project(project_folder)
    return f"{base}/{seg}" if base else seg


__all__ = ["find_root", "sub_segments", "check_drive_rel", "resolve", "within", "in_root", "root_sub", "hint", "display",
           "verify_job_parent", "job_new_from"]
