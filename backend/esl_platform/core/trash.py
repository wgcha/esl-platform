"""목록 항목 삭제의 폴더 안전장치와 휴지통(계약 esl_item_delete.md §3, v0.19.0).

삭제 흐름이 쓰거나 옮기거나 지우는 경로는 `<esl_root>/{_doe,_opt,_analysis,_compare,_verify}/<uuid>` 와
`<esl_root>/_trash/*` 뿐이다. 입력 폴더(input_roots·upload_root)·SPDM 루트·Case 원본·SCX 드라이브는 대상이 아니다.

- `move_to_trash` : 항목 폴더를 `<esl_root>/_trash/<UTC>_<KIND>_<id>` 로 `os.replace`(같은 볼륨, 원자적) 이동. 호출자(서비스)가
  DB 트랜잭션 안에서 부르고, 커밋 실패·후속 이동 실패면 `restore` 로 되돌린다.
- `purge_entry` : 휴지통 항목의 영구 삭제. 링크·junction 은 링크 객체만 지우고 대상은 따라가지 않는다. 호출은 워커 리퍼만
  (DB 행이 없을 때만 — 그 판단은 리퍼 몫).
- 이 모듈은 DB 를 모른다(순수 함수 + 파일시스템). 오류는 `PathUnsafe`(→ 422 PATH_UNSAFE)·`FileLocked`(→ 409 FILE_LOCKED).
- 주의: 서버 절대 경로는 예외 메시지·`PurgeResult.error` 에 넣지 않는다(esl_root 기준 상대 표시만).
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import re
import stat
import time
from dataclasses import dataclass
from typing import Any

from .atomic import FileLocked as _AtomicLocked
from .atomic import atomic_replace, user_path
from .config import Settings, overlaps
from .errors import DomainError
from .paths import esl_subdir
from .uploads import is_link_like

log = logging.getLogger("esl_platform.trash")

TRASH_DIR = "_trash"
KIND_DIR: dict[str, str] = {"DOE": "_doe", "OPT": "_opt", "ANALYSIS": "_analysis", "COMPARE": "_compare",
                            "VERIFY": "_verify"}

# §11 item_delete 기본값 단일 출처(core/config.ItemDeleteCfg 와 같음 — 시험이 확인). 두 예시 yaml 도 같은 값.
DEFAULTS: dict[str, Any] = {"enabled": True, "purge_interval_s": 60, "purge_batch": 20, "purge_max_attempts": 20,
                            "summary_job_ids_max": 50}

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_STAMP_FMT = "%Y%m%d-%H%M%S"
_TRASH_NAME = re.compile(r"^(\d{8}-\d{6})_(" + "|".join(KIND_DIR) + r")_([0-9a-f-]{36})$")
_ERR_MAX = 200


@dataclass(frozen=True)
class TrashMove:
    src: str
    dst: str
    kind: str
    item_id: str
    trash_name: str


@dataclass(frozen=True)
class PurgeResult:
    ok: bool
    removed_files: int
    skipped_links: int
    error: str | None


class PathUnsafe(Exception):
    """경로가 안전하지 않다(링크·junction·루트 탈출·보호 루트와 겹침·형식 오류). 서비스가 422 PATH_UNSAFE 로."""


class FileLocked(Exception):
    """폴더 이동이 재시도(worker.fs_retry) 끝까지 잠금에 막혔다. 서비스가 409 FILE_LOCKED 로. `path` = 마스킹한 표시 경로."""

    def __init__(self, path: str, message: str = "") -> None:
        super().__init__(message or f"파일이 잠겨 있어 옮기지 못했습니다: {path}")
        self.path = path


# ---------------------------------------------------------------- 이름
def trash_root(settings: Settings) -> str:
    """`<esl_root>/_trash` (경로 문자열만 — 존재·링크 검사는 호출자)."""
    return os.path.join(os.path.normpath(settings.storage.esl_root), TRASH_DIR)


def make_trash_name(kind: str, item_id: str, now: _dt.datetime | None = None) -> str:
    return f"{(now or _dt.datetime.now(_dt.timezone.utc)).strftime(_STAMP_FMT)}_{kind}_{item_id}"


def parse_trash_name(name: str) -> tuple[str, str, str] | None:
    """`<UTC %Y%m%d-%H%M%S>_<KIND>_<uuid>` → (stamp, kind, item_id), 형식이 다르면 None."""
    if not isinstance(name, str):
        return None
    m = _TRASH_NAME.match(name)
    if m is None or not _UUID.match(m.group(3)):
        return None
    try:
        _dt.datetime.strptime(m.group(1), _STAMP_FMT)
    except ValueError:
        return None
    return m.group(1), m.group(2), m.group(3)


# ---------------------------------------------------------------- 경로 검사
def _protected_roots(settings: Settings) -> list[str]:
    st = settings.storage
    return [r for r in (*st.input_roots, st.upload_root, *st.spdm_roots) if r]


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def _check_not_protected(settings: Settings, path: str) -> None:
    for r in _protected_roots(settings):
        if overlaps(path, r):
            raise PathUnsafe("입력·SPDM 루트와 겹치는 경로는 지우거나 옮기지 않습니다")


def _check_dir_not_link(path: str, what: str) -> None:
    if is_link_like(path):
        raise PathUnsafe(f"{what}가 링크·junction 입니다")


def item_dir(settings: Settings, kind: str, item_id: str, dir_rel: str | None = None) -> str:
    """항목 폴더 `<esl_root>/<KIND_DIR>/<id>` 절대경로(§3 (a)~(g) 전부 통과해야 함, 실패 = PathUnsafe).

    폴더가 없어도 경로는 검사한다(없음 판정은 호출자). 경로는 항상 (kind, id)로 다시 만든다 — DB 의 dir_rel 은 믿지 않고 대조만.
    """
    if kind not in KIND_DIR:                                                          # (a)
        raise PathUnsafe("알 수 없는 항목 종류입니다")
    if not isinstance(item_id, str) or not _UUID.match(item_id):
        raise PathUnsafe("항목 id 형식이 올바르지 않습니다")
    kdir = KIND_DIR[kind]
    if dir_rel is not None and dir_rel != f"{kdir}/{item_id}":                       # (b)
        raise PathUnsafe("저장된 폴더 경로가 항목과 맞지 않습니다")
    try:
        d = esl_subdir(settings, kdir, item_id)                                       # (c)
    except DomainError as exc:
        raise PathUnsafe(exc.message) from None
    root = os.path.normpath(settings.storage.esl_root)
    kind_root = os.path.join(root, kdir)
    for p, what in ((kind_root, f"{kdir} 폴더"), (os.path.join(root, TRASH_DIR), "휴지통 폴더"), (d, "항목 폴더")):   # (d)
        _check_dir_not_link(p, what)
    real_parent = os.path.dirname(os.path.realpath(d))                                # (e)
    if _norm(real_parent) != _norm(os.path.join(os.path.realpath(root), kdir)):
        raise PathUnsafe("실제 경로가 esl_root 아래 항목 폴더가 아닙니다")
    _check_not_protected(settings, d)                                                 # (f)
    if _norm(d) in (_norm(root), _norm(kind_root)):                                   # (g)
        raise PathUnsafe("항목 폴더가 루트 자체입니다")
    return d


def _ensure_trash(settings: Settings) -> str:
    """`<esl_root>/_trash` 확인·생성(링크 검사 전후). 보호 루트와 겹치면 PathUnsafe."""
    root = os.path.normpath(settings.storage.esl_root)
    t = os.path.join(root, TRASH_DIR)
    _check_dir_not_link(t, "휴지통 폴더")
    _check_not_protected(settings, t)
    try:
        os.makedirs(t, exist_ok=True)
    except OSError as exc:
        raise PathUnsafe(f"휴지통 폴더를 만들 수 없습니다({type(exc).__name__})") from None
    _check_dir_not_link(t, "휴지통 폴더")
    if not os.path.isdir(t) or _norm(os.path.dirname(os.path.realpath(t))) != _norm(os.path.realpath(root)):
        raise PathUnsafe("휴지통 폴더가 esl_root 바로 아래 폴더가 아닙니다")
    return t


# ---------------------------------------------------------------- 이동·되돌리기
def move_to_trash(settings: Settings, kind: str, item_id: str, dir_rel: str | None = None) -> TrashMove | None:
    """항목 폴더를 휴지통으로 이동. None = 폴더 없음. 잠금이 끝까지 풀리지 않으면 FileLocked(아무것도 옮겨지지 않은 상태)."""
    d = item_dir(settings, kind, item_id, dir_rel)
    if not os.path.lexists(d):
        return None
    if not os.path.isdir(d):
        raise PathUnsafe("항목 경로가 폴더가 아닙니다")
    t = _ensure_trash(settings)
    now = _dt.datetime.now(_dt.timezone.utc)
    name = dst = ""
    for i in range(120):                                       # 같은 초에 같은 항목이 다시 들어오는 극단 경우: 1초씩 미룸
        name = make_trash_name(kind, item_id, now + _dt.timedelta(seconds=i))
        dst = os.path.join(t, name)
        if not os.path.lexists(dst):
            break
    else:
        raise PathUnsafe("휴지통 이름이 겹칩니다")
    try:
        atomic_replace(d, dst)
    except _AtomicLocked as exc:
        log.warning("휴지통 이동 잠김: %s", exc.log_text())
        raise FileLocked(user_path(d, settings.storage.esl_root)) from None
    return TrashMove(src=d, dst=dst, kind=kind, item_id=item_id, trash_name=name)


def restore(settings: Settings, mv: TrashMove) -> bool:
    """휴지통에서 원래 자리로 되돌린다. 되돌릴 게 없거나 원래 자리가 차 있거나 잠기면 False(로그만 — 예외 없음)."""
    try:
        parsed = parse_trash_name(mv.trash_name)
        if parsed is None or parsed[1] != mv.kind or parsed[2] != mv.item_id:
            log.warning("휴지통 되돌리기 거부: 이름 불일치 %s", mv.trash_name)
            return False
        t = os.path.join(os.path.normpath(settings.storage.esl_root), TRASH_DIR)
        src = os.path.join(t, mv.trash_name)
        if _norm(src) != _norm(mv.dst) or is_link_like(src) or not os.path.isdir(src):
            return False
        dest = item_dir(settings, mv.kind, mv.item_id)
        if os.path.lexists(dest):
            log.warning("휴지통 되돌리기 보류: 원래 자리가 이미 있음 %s", mv.trash_name)
            return False
        atomic_replace(src, dest)
        return True
    except (PathUnsafe, OSError, _AtomicLocked) as exc:
        log.warning("휴지통 되돌리기 실패 %s: %s", mv.trash_name, type(exc).__name__)
        return False


# ---------------------------------------------------------------- 영구 삭제
def _retry_cfg(settings: Settings) -> tuple[int, float, float]:
    fr = settings.worker.fs_retry
    return int(fr.attempts), float(fr.base_s), float(fr.max_wait_s)


def _fmt_err(exc: BaseException, rel: str) -> str:
    we = getattr(exc, "winerror", None)
    why = f"WinError {we}" if we is not None else (f"errno {exc.errno}" if getattr(exc, "errno", None) else "")
    return f"{type(exc).__name__}{' ' + why if why else ''}: {rel}"[:_ERR_MAX]


def _remove_link(path: str) -> None:
    """링크·junction 객체만 지운다(대상은 따라가지 않음)."""
    try:
        os.unlink(path)
    except (IsADirectoryError, PermissionError):
        os.rmdir(path)           # Windows 디렉터리 심링크·junction
    except OSError:
        os.rmdir(path)


def _remove_file(path: str, attempts: int, base_s: float, max_wait_s: float) -> None:
    """파일 1개 삭제: PermissionError 는 쓰기 속성 부여 후 지수 백오프로 재시도(worker.fs_retry)."""
    waited = 0.0
    for i in range(max(1, attempts)):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
            if i == attempts - 1 or waited >= max_wait_s:
                raise
            d = min(base_s * (2 ** i), max_wait_s - waited)
            if d > 0:
                time.sleep(d)
                waited += d
    os.unlink(path)


def purge_entry(settings: Settings, trash_name: str) -> PurgeResult:
    """`<esl_root>/_trash/<trash_name>` 영구 삭제. 이름 형식·경로·링크 검사에 실패하면 아무것도 지우지 않고 ok=False."""
    if parse_trash_name(trash_name) is None:
        return PurgeResult(False, 0, 0, "휴지통 이름 형식이 다릅니다")
    root = os.path.normpath(settings.storage.esl_root)
    t = os.path.join(root, TRASH_DIR)
    top = os.path.join(t, trash_name)
    try:
        _check_dir_not_link(t, "휴지통 폴더")
        _check_not_protected(settings, top)
        if _norm(os.path.dirname(os.path.realpath(top))) != _norm(os.path.join(os.path.realpath(root), TRASH_DIR)):
            raise PathUnsafe("휴지통 항목의 실제 경로가 휴지통 밖입니다")
    except PathUnsafe as exc:
        return PurgeResult(False, 0, 0, str(exc)[:_ERR_MAX])
    try:
        st = os.lstat(top)
    except FileNotFoundError:
        return PurgeResult(True, 0, 0, None)                  # 이미 없음
    except OSError as exc:
        return PurgeResult(False, 0, 0, _fmt_err(exc, trash_name))
    attempts, base_s, max_wait_s = _retry_cfg(settings)
    removed = skipped = 0
    first_err: str | None = None
    if is_link_like(top) or not stat.S_ISDIR(st.st_mode):
        # 휴지통 최상위가 링크·파일이면 그 객체만 지운다(따라가지 않음)
        try:
            if is_link_like(top):
                _remove_link(top)
                return PurgeResult(True, 0, 1, None)
            _remove_file(top, attempts, base_s, max_wait_s)
            return PurgeResult(True, 1, 0, None)
        except OSError as exc:
            return PurgeResult(False, 0, 0, _fmt_err(exc, trash_name))
    # 반복 순회(재귀 깊이 제한 회피): 후위 순서로 파일 → 빈 폴더
    stack: list[tuple[str, str, bool]] = [(top, "", False)]
    while stack:
        path, rel, visited = stack.pop()
        if visited:
            try:
                os.rmdir(path)
            except OSError as exc:
                first_err = first_err or _fmt_err(exc, rel or trash_name)
            continue
        stack.append((path, rel, True))
        try:
            with os.scandir(path) as it:
                children = list(it)
        except OSError as exc:
            first_err = first_err or _fmt_err(exc, rel or trash_name)
            continue
        for e in children:
            cp = e.path
            crel = f"{rel}/{e.name}" if rel else e.name
            try:
                if is_link_like(cp):
                    _remove_link(cp)
                    skipped += 1
                    log.warning("휴지통 영구 삭제: 링크는 대상을 따라가지 않고 링크만 지움 %s/%s", trash_name, crel)
                elif e.is_dir(follow_symlinks=False):
                    stack.append((cp, crel, False))
                else:
                    _remove_file(cp, attempts, base_s, max_wait_s)
                    removed += 1
            except OSError as exc:
                first_err = first_err or _fmt_err(exc, crel)
    if first_err is not None:
        return PurgeResult(False, removed, skipped, first_err)
    return PurgeResult(True, removed, skipped, None)


__all__ = ["TRASH_DIR", "KIND_DIR", "DEFAULTS", "TrashMove", "PurgeResult", "PathUnsafe", "FileLocked", "item_dir",
           "move_to_trash", "restore", "purge_entry", "parse_trash_name", "trash_root", "make_trash_name"]
