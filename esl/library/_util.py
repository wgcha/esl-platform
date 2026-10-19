"""라이브러리 공용 도구: JSON·npz 입출력, sha256, 경로 겹침 검사, 덮어쓰기 전 _backup 이동.

esl.pipeline 은 다른 작업자가 수정 중이므로 import 하지 않고 같은 규약을 여기서 다시 구현한다
(npz 는 allow_pickle=False, JSON 은 비유한 실수를 문자열로).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os

import numpy as np

from esl.errors import EslError

BACKUP_DIR = "_backup"
_CHUNK = 4 * 1024 * 1024


def utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utcstamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return v if np.isfinite(v) else str(v)
    if isinstance(o, np.str_):
        return str(o)
    return o


def dumps(obj) -> str:
    return json.dumps(jsonable(obj), ensure_ascii=False, indent=1)


def write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dumps(obj))
        fh.write("\n")


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_npz(path: str) -> dict:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(_CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_arrays(*arrays) -> str:
    """배열 내용(dtype·shape 포함) 해시 — 메시·하중 지문."""
    h = hashlib.sha256()
    for a in arrays:
        a = np.ascontiguousarray(a)
        h.update(str(a.dtype).encode())
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def real_path(path: str) -> str:
    """심볼릭 링크를 푼 실제 경로(존재하지 않으면 가장 가까운 존재 조상의 realpath + 나머지)."""
    p = os.path.abspath(os.fspath(path))
    rest: list[str] = []
    cur = p
    while not os.path.lexists(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        rest.append(os.path.basename(cur))
        cur = parent
    r = os.path.realpath(cur)
    for part in reversed(rest):
        r = os.path.join(r, part)
    return os.path.normpath(r)


def is_within(child: str, parent: str) -> bool:
    child, parent = os.path.normcase(child), os.path.normcase(parent)
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def check_no_overlap(out: str, inputs: list[tuple[str, str]]) -> str:
    """출력 realpath 가 입력 폴더 안이거나 입력을 포함하면 INPUT_INVALID (입력 폴더 쓰기 금지)."""
    ro = real_path(out)
    for name, p in inputs:
        rp = real_path(p)
        if is_within(ro, rp) or is_within(rp, ro):
            raise EslError("INPUT_INVALID", f"출력 {out} (실제 {ro}) 가 입력({name} {rp})과 겹침 — 입력 폴더에는 쓰지 않음")
    return ro


class Writer:
    """출력 루트 안에서만 쓰고, 기존 파일·폴더는 ``<base>/_backup/<ts>/`` 로 이동한 뒤 쓴다."""

    def __init__(self, root: str, inputs: list[tuple[str, str]] | None = None, ts: str | None = None):
        self.root = os.path.abspath(root)
        self.inputs = list(inputs or [])
        self.root_real = check_no_overlap(self.root, self.inputs)
        self.ts = ts or utcstamp()

    def guard(self, path: str) -> str:
        r = real_path(path)
        if not is_within(r, self.root_real):
            raise EslError("INPUT_INVALID", f"쓰기 대상 {path} (실제 {r}) 가 출력 루트 {self.root_real} 밖 — 쓰지 않음")
        for name, p in self.inputs:
            if is_within(r, real_path(p)):
                raise EslError("INPUT_INVALID", f"쓰기 대상 {path} 가 입력({name}) 안 — 쓰지 않음")
        return path

    def makedirs(self, d: str) -> str:
        self.guard(d)
        os.makedirs(d, exist_ok=True)
        return self.guard(d)

    def backup(self, path: str, base: str) -> str | None:
        """path 가 있으면 ``base/_backup/<ts>/<base 기준 상대경로>`` 로 이동. 이동한 경로 반환."""
        self.guard(path)
        if not os.path.lexists(path):
            return None
        rel = os.path.relpath(path, base)
        dst = os.path.join(base, BACKUP_DIR, self.ts, rel)
        k = 1
        while os.path.lexists(dst):
            dst = os.path.join(base, BACKUP_DIR, self.ts, f"{rel}.{k}")
            k += 1
        self.makedirs(os.path.dirname(dst))
        os.replace(path, self.guard(dst))
        return dst

    def fresh_file(self, path: str, base: str) -> str:
        self.makedirs(os.path.dirname(path))
        self.backup(path, base)
        return self.guard(path)

    def fresh_dir(self, d: str, base: str) -> str:
        """d 에 내용이 있으면 통째로 백업 이동 후 빈 폴더."""
        self.guard(d)
        if os.path.isdir(d) and os.listdir(d):
            self.backup(d, base)
        return self.makedirs(d)
