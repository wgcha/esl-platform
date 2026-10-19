"""입력 경로 검사(계약 esl_platform_p1b.md §1, V-SEC-2·V-P1B-3). 코어 출력 겹침 보호와 이중으로 둔다.

- 절대경로만, 제어문자·cmd 메타문자(`& | < > ^ % ! "`)·`..` 성분 → 422 `PATH_UNSAFE`
- `storage.input_roots` 밖 → 422 `PATH_OUTSIDE_ROOT`
- `esl_root`·`spdm_roots`와 겹침, root 아래 심링크 성분, realpath 가 root 밖 → 422 `PATH_UNSAFE`
- 없음 / 종류 불일치(RAD=파일, RESULTS=폴더) → 422 `PATH_NOT_FOUND`
- 완전한 절대경로 판정은 OS 의미(ntpath | posixpath)를 명시해서 한다(`os.path.isabs` 는 Python·OS 버전마다
  드라이브 없는 루트 상대 `\\x`·드라이브 상대 `C:x` 처리가 달라 쓰지 않음).
- rad 의 include 가 `input_roots` 밖 → 422 `PATH_OUTSIDE_ROOT`(어떤 include 인지 표시, 파일 내용은 읽지 않음)
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re

from .config import Settings, is_within, overlaps
from .errors import unprocessable

META = re.compile(r'[&|<>^%!"\x00-\x1f\x7f]')


def _unsafe(msg: str):
    return unprocessable("PATH_UNSAFE", msg)


def host_flavor() -> str:
    return "nt" if os.name == "nt" else "posix"


def is_fully_qualified(raw: str, flavor: str | None = None) -> bool:
    """flavor(nt|posix) 의미로 완전한 절대경로인지.

    nt: 드라이브 + 루트(`C:\\x`, `C:/x`) 또는 UNC(`\\\\srv\\share\\x`). 드라이브 없는 루트 상대(`\\x`, `/x`)·
    드라이브 상대(`C:x`)는 False. posix: `/` 로 시작.
    """
    flavor = flavor or host_flavor()
    if not isinstance(raw, str) or not raw:
        return False
    if flavor == "nt":
        drive, rest = ntpath.splitdrive(raw)
        if not drive:
            return False
        if drive.startswith(("\\\\", "//")):            # UNC: \\srv\share — 공유 이름까지 있어야 함
            return len(re.split(r"[\\/]+", drive.strip("\\/"))) >= 2
        return rest[:1] in ("\\", "/")
    return posixpath.isabs(raw)


def lexical_check(raw: str, flavor: str | None = None) -> str:
    """문자열만 보는 검사(파일시스템 접근 없음). 통과 시 flavor 의미로 정규화한 경로."""
    flavor = flavor or host_flavor()
    if not isinstance(raw, str) or not raw or len(raw) > 1024:
        raise _unsafe("경로가 비었거나 너무 깁니다")
    if META.search(raw):
        raise _unsafe('경로에 제어문자나 & | < > ^ % ! " 를 쓸 수 없습니다')
    parts = re.split(r"[\\/]+", raw)
    if any(p == ".." for p in parts):
        raise _unsafe("경로에 '..' 를 쓸 수 없습니다")
    if not is_fully_qualified(raw, flavor):
        raise _unsafe("절대경로만 허용합니다(Windows 는 드라이브와 루트를 포함한 전체 경로)")
    return (ntpath if flavor == "nt" else posixpath).normpath(raw)


def check_input_path(settings: Settings, raw: str, purpose: str) -> str:
    """검사 통과 시 정규화 경로. purpose: RAD | RESULTS."""
    p = lexical_check(raw)
    st = settings.storage
    root = next((r for r in st.input_roots if is_within(p, r)), None)
    if root is None:
        raise unprocessable("PATH_OUTSIDE_ROOT", "허용된 입력 루트(storage.input_roots) 밖의 경로입니다")
    if overlaps(p, st.esl_root) or any(overlaps(p, s) for s in st.spdm_roots):
        raise _unsafe("산출물 루트(esl_root)·SPDM 루트와 겹치는 경로는 입력으로 쓸 수 없습니다")
    # root 아래 성분 중 심링크 거부
    rootn = os.path.normpath(root)
    rel = os.path.relpath(p, rootn)
    cur = rootn
    if rel != ".":
        for comp in rel.split(os.sep):
            cur = os.path.join(cur, comp)
            if os.path.islink(cur):
                raise _unsafe("심볼릭 링크 경로는 허용하지 않습니다")
    if not is_within(os.path.realpath(p), os.path.realpath(rootn)):
        raise _unsafe("실제 경로가 입력 루트 밖입니다")
    if purpose == "RAD":
        if not os.path.isfile(p):
            raise unprocessable("PATH_NOT_FOUND", "rad 파일이 없습니다")
    elif purpose == "RESULTS":
        if not os.path.isdir(p):
            raise unprocessable("PATH_NOT_FOUND", "결과 폴더가 없습니다")
    else:
        raise unprocessable("INVALID_PARAMS", "purpose 는 RAD | RESULTS")
    return p


def check_includes(settings: Settings, includes: list[str]) -> None:
    """rad 의 include 경로(scan_includes 결과)가 모두 input_roots 안(심링크 탈출 없음)이어야 함.

    밖이면 422 PATH_OUTSIDE_ROOT(include 경로 표시). 이 검사는 include 파일 내용을 읽지 않는다.
    """
    st = settings.storage
    for inc in includes:
        p = os.path.normpath(os.path.abspath(inc))
        root = next((r for r in st.input_roots if is_within(p, r)), None)
        bad = root is None
        if not bad:
            rp = os.path.realpath(p)
            bad = not any(is_within(rp, os.path.realpath(r)) for r in st.input_roots)
        if not bad:
            bad = overlaps(p, st.esl_root) or any(overlaps(p, s) for s in st.spdm_roots)
        if bad:
            raise unprocessable("PATH_OUTSIDE_ROOT", f"rad 의 include 가 허용된 입력 루트(storage.input_roots) 밖입니다: "
                                f"{inc}", include=inc)


def case_dir(settings: Settings, folder_name: str) -> str:
    return os.path.join(settings.storage.esl_root, folder_name)


def safe_case_file(case_root: str, rel: str) -> str:
    """Case 폴더 안 상대경로 → 절대경로(realpath 기준 밖·심링크 탈출 거부)."""
    if not rel or os.path.isabs(rel) or any(p == ".." for p in re.split(r"[\\/]+", rel)):
        raise _unsafe("잘못된 산출물 경로")
    p = os.path.normpath(os.path.join(case_root, rel))
    if not is_within(os.path.realpath(p), os.path.realpath(case_root)):
        raise _unsafe("산출물 경로가 Case 폴더 밖입니다")
    return p


# ---------------------------------------------------------------- P2: esl_root 아래 플랫폼 폴더(_library, _analysis)
LIBRARY_DIR = "_library"      # 라이브러리 항목 <esl_root>/_library/entries/<id>/ (Case 폴더명은 _ 로 시작 불가 → 충돌 없음)
ANALYSIS_DIR = "_analysis"    # 종합분석 <esl_root>/_analysis/<id>/ (계약 §3)
_SEG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$")


def esl_subdir(settings: Settings, *parts: str) -> str:
    """esl_root 아래 플랫폼 폴더 절대경로. 성분 문자 제한, root 아래 심링크 성분·realpath 탈출 거부(PATH_UNSAFE).

    입력 루트와는 설정 검증에서 이미 겹치지 않음(esl_root ∩ input_roots = ∅).
    """
    root = os.path.normpath(settings.storage.esl_root)
    cur = root
    for seg in parts:
        if not _SEG.match(seg or "") or seg in (".", ".."):
            raise _unsafe("잘못된 폴더 이름")
        cur = os.path.join(cur, seg)
        if os.path.islink(cur):
            raise _unsafe("심볼릭 링크 경로는 허용하지 않습니다")
    if not is_within(os.path.realpath(cur), os.path.realpath(root)):
        raise _unsafe("실제 경로가 esl_root 밖입니다")
    if any(overlaps(cur, r) for r in settings.storage.input_roots):
        raise _unsafe("입력 루트와 겹치는 경로에는 쓰지 않습니다")
    return cur
