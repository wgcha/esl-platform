"""입력 경로 검사(계약 esl_platform_p1b.md §1, V-SEC-2·V-P1B-3). 코어 출력 겹침 보호와 이중으로 둔다.

- 절대경로만, 제어문자·cmd 메타문자(`& | < > ^ % ! "`)·`..` 성분 → 422 `PATH_UNSAFE`
- `storage.input_roots` 밖 → 422 `PATH_OUTSIDE_ROOT`
- `esl_root`·`spdm_roots`와 겹침, root 아래 심링크 성분, realpath 가 root 밖 → 422 `PATH_UNSAFE`
- 없음 / 종류 불일치(RAD=파일, RESULTS=폴더) → 422 `PATH_NOT_FOUND`
"""

from __future__ import annotations

import os
import re

from .config import Settings, is_within, overlaps
from .errors import unprocessable

META = re.compile(r'[&|<>^%!"\x00-\x1f\x7f]')


def _unsafe(msg: str):
    return unprocessable("PATH_UNSAFE", msg)


def check_input_path(settings: Settings, raw: str, purpose: str) -> str:
    """검사 통과 시 정규화 경로. purpose: RAD | RESULTS."""
    if not isinstance(raw, str) or not raw or len(raw) > 1024:
        raise _unsafe("경로가 비었거나 너무 깁니다")
    if META.search(raw):
        raise _unsafe('경로에 제어문자나 & | < > ^ % ! " 를 쓸 수 없습니다')
    parts = re.split(r"[\\/]+", raw)
    if any(p == ".." for p in parts):
        raise _unsafe("경로에 '..' 를 쓸 수 없습니다")
    if not os.path.isabs(raw):
        raise _unsafe("절대경로만 허용합니다")
    p = os.path.normpath(raw)
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
