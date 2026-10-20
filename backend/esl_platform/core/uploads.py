"""브라우저 분할 업로드의 이름·경로 규칙(계약 esl_p3_ux.md §1.1). DB·HTTP 없음(순수 함수 + 파일시스템 검사).

- 업로드 폴더: `<upload_root>/<사용자>/<UTC yyyymmdd-HHMMSS>_<이름>/{rad,results,h3d}/...` — 기존 폴더·파일 덮어쓰기 없음.
- 파일 `rel`: `/` 구분 상대경로, 첫 성분은 rad | results | h3d. 절대경로·드라이브·`\\`·`..`·`.`·빈 성분·제어문자·
  `< > : " | ? * & ^ % !`·끝 점/공백·Windows 예약 장치명(확장자 붙어도) 거부. 확장자는 설정 허용 목록.
- 쓰기 대상은 업로드 폴더 아래만: 성분 중 심링크 거부, realpath 가 업로드 폴더 밖이면 거부(PATH_UNSAFE).
- 취소·stale·sha256 불일치 파일은 지우지 않고 `<upload_root>/_backup/<사용자>/...` 로 옮긴다.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import stat

from .config import is_within
from .errors import forbidden, unprocessable

KINDS = ("rad", "results", "h3d")
BACKUP_DIR = "_backup"
PART_SUFFIX = ".part"
MAX_REL = 400
MAX_SEG = 255
_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"|?*\\&^%!]')
_WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9]|conin\$|conout\$)$", re.IGNORECASE)
_NAME_REPLACE = re.compile(r"[^0-9A-Za-z가-힣_.\-]+")


def _bad(msg: str, **extra):
    return unprocessable("UPLOAD_NAME_INVALID", msg, **extra)


def check_segment(seg: str, what: str) -> None:
    if not seg:
        raise _bad(f"{what}: 빈 이름(연속 '/')은 쓸 수 없습니다")
    if seg in (".", ".."):
        raise _bad(f"{what}: '.'·'..' 은 쓸 수 없습니다")
    if len(seg) > MAX_SEG:
        raise _bad(f"{what}: 이름이 너무 깁니다")
    if _BAD_CHARS.search(seg):
        raise _bad(f'{what}: 제어문자·\\ < > : " | ? * & ^ % ! 는 쓸 수 없습니다')
    if seg != seg.strip() or seg.endswith("."):
        raise _bad(f"{what}: 앞뒤 공백이나 끝 점은 쓸 수 없습니다")
    if _WIN_RESERVED.match(seg.split(".", 1)[0].strip()):
        raise _bad(f"{what}: Windows 예약 이름은 쓸 수 없습니다")


def check_rel(rel: str, allowed_ext: list[str]) -> list[str]:
    """파일 상대경로 검사 → 성분 목록. 첫 성분 rad | results | h3d, 확장자 허용 목록."""
    if not isinstance(rel, str) or not rel or len(rel) > MAX_REL:
        raise _bad("파일 경로가 비었거나 너무 깁니다", rel=rel)
    if rel.startswith("/") or "\\" in rel or re.match(r"^[A-Za-z]:", rel):
        raise _bad(f"절대경로나 '\\' 구분자는 쓸 수 없습니다(선택 폴더 기준 상대경로만): {rel}", rel=rel)
    segs = rel.split("/")
    for s in segs:
        check_segment(s, rel)
    if len(segs) < 2 or segs[0] not in KINDS:
        raise _bad(f"파일 경로는 {', '.join(k + '/' for k in KINDS)} 로 시작해야 합니다: {rel}", rel=rel)
    ext = os.path.splitext(segs[-1])[1].lower()
    if ext not in [e.lower() for e in allowed_ext]:
        raise unprocessable("UPLOAD_EXT_NOT_ALLOWED", f"허용되지 않는 확장자입니다({ext or '없음'}): {rel}", rel=rel,
                            allowed=list(allowed_ext))
    return segs


def safe_name(name: str, what: str = "업로드 이름") -> str:
    """폴더 이름 성분으로 쓸 이름: 경로 구분자·'..'·제어문자·예약어 거부, 나머지 특수문자는 '_'(최대 64자)."""
    if not isinstance(name, str) or not name.strip():
        raise _bad(f"{what}이 비었습니다")
    n = name.strip()
    if "/" in n or "\\" in n or ".." in n or re.search(r"[\x00-\x1f\x7f]", n):
        raise _bad(f"{what}에 경로 구분자·'..'·제어문자를 쓸 수 없습니다")
    if _WIN_RESERVED.match(n.split(".", 1)[0].strip()):
        raise _bad(f"{what}에 Windows 예약 이름은 쓸 수 없습니다")
    out = _NAME_REPLACE.sub("_", n)[:64].strip("._") or "upload"
    return out


def user_segment(username: str, user_id: str) -> str:
    try:
        return safe_name(username, "사용자 이름")
    except Exception:  # noqa: BLE001 - 이상한 사용자 이름이면 id 로
        return _NAME_REPLACE.sub("_", user_id)[:64].strip("._") or "user"


def upload_area_segments(upload_root: str | None, path: str) -> list[str] | None:
    """path 가 upload_root 아래면 upload_root 기준 성분 목록(루트 자체면 []), 아니면 None."""
    if not upload_root:
        return None
    rootn = os.path.normpath(upload_root)
    pn = os.path.normpath(path)
    if not is_within(pn, rootn):
        return None
    rel = os.path.relpath(pn, rootn)
    return [] if rel == os.curdir else rel.split(os.sep)


def check_upload_area(upload_root: str | None, path: str, own_seg: str, is_admin: bool) -> None:
    """업로드 루트 격리: `_backup` 은 어느 깊이에서도 거부(관리자 포함), 사용자 폴더는 본인 것만(전역 관리자는 전체).
    실제 경로(realpath)도 같은 규칙으로 본다."""
    for cand in dict.fromkeys((os.path.normpath(path), os.path.realpath(path))):
        segs = upload_area_segments(upload_root, cand)
        if segs is None and upload_root and cand != os.path.normpath(path):
            segs = upload_area_segments(os.path.realpath(upload_root), cand)
        if not segs:
            continue
        if any(s.casefold() == BACKUP_DIR for s in segs):
            raise unprocessable("PATH_UNSAFE", "업로드 백업(_backup)은 볼 수도 입력으로 쓸 수도 없습니다")
        if not is_admin and os.path.normcase(segs[0]) != os.path.normcase(own_seg):
            raise forbidden("다른 사용자의 업로드 폴더입니다(본인 폴더만)", code="UPLOAD_FOLDER_FORBIDDEN")


def check_principal_upload_area(upload_root: str | None, path: str, principal) -> None:
    """Case 입력·경로 검사: 업로드 루트 아래 경로는 본인 폴더만(전역 관리자 제외), `_backup` 거부."""
    check_upload_area(upload_root, path, user_segment(principal.username, principal.user_id),
                      bool(principal.is_global_admin))


def utc_stamp(now: _dt.datetime | None = None) -> str:
    return (now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y%m%d-%H%M%S")


def _no_links_below(root: str, path: str) -> None:
    """root 아래 path 까지 이미 있는 성분 중 심링크가 있으면 거부, realpath 가 root 밖이면 거부."""
    rootn = os.path.normpath(root)
    rel = os.path.relpath(os.path.normpath(path), rootn)
    if rel == os.curdir:
        return
    if rel.startswith(os.pardir):
        raise unprocessable("PATH_UNSAFE", "업로드 폴더 밖 경로입니다")
    cur = rootn
    for comp in rel.split(os.sep):
        cur = os.path.join(cur, comp)
        if os.path.islink(cur):
            raise unprocessable("PATH_UNSAFE", "심볼릭 링크 경로에는 쓰지 않습니다")
    if not is_within(os.path.realpath(path), os.path.realpath(rootn)):
        raise unprocessable("PATH_UNSAFE", "실제 경로가 업로드 폴더 밖입니다")


def make_upload_dir(upload_root: str, user_seg: str, name_seg: str, stamp: str) -> str:
    """새 업로드 폴더를 만든다(이미 있으면 _2, _3 … — 덮어쓰기 없음)."""
    os.makedirs(upload_root, exist_ok=True)
    if os.path.islink(upload_root):
        raise unprocessable("PATH_UNSAFE", "업로드 루트가 심볼릭 링크입니다")
    udir = os.path.join(upload_root, user_seg)
    _no_links_below(upload_root, udir)
    os.makedirs(udir, exist_ok=True)
    _no_links_below(upload_root, udir)
    for i in range(1, 1000):
        d = os.path.join(udir, f"{stamp}_{name_seg}" + ("" if i == 1 else f"_{i}"))
        try:
            os.mkdir(d)
        except FileExistsError:
            continue
        _no_links_below(upload_root, d)
        return d
    raise unprocessable("UPLOAD_DIR_EXISTS", "업로드 폴더를 만들 수 없습니다(같은 이름이 너무 많음)")


def target_path(upload_dir: str, segs: list[str], *, create_parents: bool = False) -> str:
    """업로드 폴더 안 파일 경로(성분 심링크·realpath 탈출 거부). create_parents 면 상위 폴더를 만든 뒤 다시 검사."""
    p = os.path.join(upload_dir, *segs)
    parent = os.path.dirname(p)
    _no_links_below(upload_dir, parent)
    if create_parents:
        os.makedirs(parent, exist_ok=True)
        _no_links_below(upload_dir, parent)
    if os.path.islink(p) or os.path.islink(p + PART_SUFFIX):
        raise unprocessable("PATH_UNSAFE", "심볼릭 링크 경로에는 쓰지 않습니다")
    for q in (p, p + PART_SUFFIX):
        if os.path.lexists(q):
            check_existing_file(q, upload_dir)
    return p


def _check_stat(st: os.stat_result) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise unprocessable("PATH_UNSAFE", "일반 파일이 아닌 경로에는 쓰지 않습니다")
    if st.st_nlink != 1:
        raise unprocessable("PATH_UNSAFE", "하드 링크된 파일에는 쓰지 않습니다")


def check_existing_file(path: str, root: str | None = None) -> None:
    """이미 있는 파일: 심링크 아님·일반 파일·링크 수 1(하드 링크 거부)·realpath 가 root 안."""
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        raise unprocessable("PATH_UNSAFE", "심볼릭 링크 경로에는 쓰지 않습니다")
    _check_stat(st)
    if root is not None and not is_within(os.path.realpath(path), os.path.realpath(root)):
        raise unprocessable("PATH_UNSAFE", "실제 경로가 업로드 폴더 밖입니다")


def append_chunk(part_path: str, data: bytes, root: str | None = None) -> None:
    """part_path 에 이어 쓴다. 새 파일은 O_EXCL 로 만들고, 기존 파일은 열린 fd 로 일반 파일·링크 수 1 을 확인
    (하드 링크로 밖 파일에 쓰기 방지)·root 가 주어지면 realpath 가 그 안인지 확인."""
    base = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(part_path, base | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        fd = os.open(part_path, base)
        try:
            _check_stat(os.fstat(fd))
            if root is not None and not is_within(os.path.realpath(part_path), os.path.realpath(root)):
                raise unprocessable("PATH_UNSAFE", "실제 경로가 업로드 폴더 밖입니다")
        except BaseException:
            os.close(fd)
            raise
    try:
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
    finally:
        os.close(fd)


def backup_dest(upload_root: str, user_seg: str, name: str) -> str:
    base = os.path.join(upload_root, BACKUP_DIR, user_seg)
    os.makedirs(base, exist_ok=True)
    for i in range(1, 1000):
        d = os.path.join(base, name + ("" if i == 1 else f"_{i}"))
        if not os.path.lexists(d):
            return d
    raise unprocessable("BACKUP_EXISTS", "백업 위치를 정할 수 없습니다")


def move_to_backup(upload_root: str, user_seg: str, src: str, name: str | None = None) -> str | None:
    """src(파일·폴더)를 <upload_root>/_backup/<사용자>/<이름> 으로 옮긴다(삭제 없음). 없으면 None."""
    if not os.path.lexists(src):
        return None
    dest = backup_dest(upload_root, user_seg, name or os.path.basename(src))
    shutil.move(src, dest)
    return dest
